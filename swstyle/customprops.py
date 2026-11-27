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

import datetime
import math
import os
import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt
PREFIX = "CustomProperty:"
TYPES = ("Text", "Date", "Number", "Yes or no")

UNITS = ("", "units", "mm", "cm", "m", "in", "ft", "g", "kg", "lb", "°", "rad", "s", "min", "h", "mm²", "mm³", "N",
         "N·m", "Pa", "MPa", "kg/m³")
UNIT_ALIAS = {"°": "deg", "mm³": "mm^3"}         # the unit box's spellings in convert_unit's table
UNIT_PREFIX = "CustomPropertyUnit:"


def _unit_scope(config=None):
    return UNIT_PREFIX + (config + ":" if config else "")


def units(doc, config=None):
    """{property name: unit} of the document's (or the configuration's) Number properties."""
    if doc is None:
        return {}
    scope = _unit_scope(config)
    out = {}
    for key, unit in dict(doc.Meta or {}).items():
        rest = key[len(scope):] if key.startswith(scope) else None
        if rest and (config or ":" not in rest) and unit:
            out[rest] = unit
    return out


def write_units(doc, mapping, config=None):
    """Stores the units (only those of Number properties are kept), replacing the scope's old ones."""
    scope = _unit_scope(config)
    meta = {k: v for k, v in dict(doc.Meta or {}).items()
            if not (k.startswith(scope) and (config or ":" not in k[len(scope):]))}
    for name, unit in (mapping or {}).items():
        if name.strip() and unit:
            meta[scope + name.strip()] = unit
    doc.Meta = meta


def with_unit(text, unit):
    """A Number's value with its unit box: a value with its own unit (a linked mass "1.0000 kg") is
    converted to the unit; a bare number is in the unit already. Document units ("units") follow
    MMGS/IPS: a bare number counts as millimetres there and is converted."""
    if not text or not unit:
        return text
    want = UNIT_ALIAS.get(unit, unit)
    if want == "units" or re.match(r"^\s*-?[0-9.]+(?:[eE][-+]?[0-9]+)?\s*[A-Za-z][A-Za-z^0-9]*\s*$", str(text)):
        got = convert_unit(text, want)
        if got != text:
            return got.replace(" deg", " °").replace("mm^3", "mm³")
        if want == "units":
            return text
    return "%s %s" % (text, unit)
LINKS = ("Mass", "Volume", "Density", "Material", "File Name", "Description", "Surface Area", "Center of Mass",
         "Configuration Name", "Title", "Author", "Subject", "Keywords", "Comments", "Created Date",
         "Last Saved Date", "Last Saved By", "Short Date", "Long Date", "Folder Name",
         "Total Bounding Box Length", "Total Bounding Box Width", "Total Bounding Box Thickness",
         "Total Bounding Box Volume")

# configuration's own properties, their values follow the box
BOX_LINKS = {"Total Bounding Box Length": "BoxLength", "Total Bounding Box Width": "BoxWidth",
             "Total Bounding Box Thickness": "BoxHeight", "Total Bounding Box Volume": "BoxVolume"}


def read(doc):
    """[(name, type, value)] in their order."""
    if doc is None:
        return []
    meta = dict(doc.Meta or {})
    rows = []
    for key, text in meta.items():
        if not key.startswith(PREFIX):
            continue
        parts = text.split("\t", 2)
        order, kind, value = (parts + ["", "", ""])[:3] if len(parts) == 3 else ("0", "Text", text)
        try:
            order = int(order)
        except ValueError:
            order = 0
        rows.append((order, key[len(PREFIX):], kind if kind in TYPES else "Text", value))
    return [(n, k, v) for o, n, k, v in sorted(rows)]


def write(doc, rows):
    ""
    meta = {k: v for k, v in dict(doc.Meta or {}).items() if not k.startswith(PREFIX)}
    for i, (name, kind, value) in enumerate(rows):
        name = name.strip()
        if name:
            meta[PREFIX + name] = "%d\t%s\t%s" % (i, kind if kind in TYPES else "Text", value)
    doc.Meta = meta
    try:
        Gui.getDocument(doc.Name).Modified = True      # so closing asks to save them
    except Exception as _fw_err:
        _fw_log("customprops.py:127", _fw_err)
    return True


# Edit List: the property names the Property Name cell offers (kept in the user's settings)
NAMES_PARAM = "User parameter:BaseApp/Preferences/Mod/FreeWorks/CustomProperties"
STANDARD_NAMES = ("Description", "PartNo", "Revision", "Material", "Weight", "Finish", "Vendor", "Project",
                  "DrawnBy", "DrawnDate", "CheckedBy", "CheckedDate", "EngineeringApproval", "Number", "Cost")
BOM_QTY = "FreeWorks:BomQuantity"


def name_list():
    text = App.ParamGet(NAMES_PARAM).GetString("Names", "")
    return [n for n in text.split("\n") if n] if text else list(STANDARD_NAMES)


def set_name_list(names):
    App.ParamGet(NAMES_PARAM).SetString("Names", "\n".join(n for n in names if n.strip()))


def bom_quantity_property(doc):
    return dict(doc.Meta or {}).get(BOM_QTY, "") if doc is not None else ""


def set_bom_quantity_property(doc, name):
    meta = dict(doc.Meta or {})
    if name:
        meta[BOM_QTY] = name
    else:
        meta.pop(BOM_QTY, None)
    doc.Meta = meta


def bom_quantity(doc):
    """BOM quantity: how many of this part one instance counts for in a bill of materials (the
    picked custom property's number), 1 without one."""
    name = bom_quantity_property(doc)
    if not name:
        return 1
    for n, kind, v in read(doc):
        if n == name:
            try:
                q = float(evaluate(doc, kind, v).split()[0])
                return int(q) if q == int(q) else q
            except (ValueError, IndexError):
                return 1
    return 1


class EditListDialog(QtWidgets.QDialog):
    """Edit List: the names offered in the Property Name cells (Add, Delete, Move Up, Move Down)."""

    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWEditPropertyList")
        self.setWindowTitle("Edit Custom Property List")
        lay = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        self.entry = QtWidgets.QLineEdit()
        self.entry.setPlaceholderText("Type a new value")
        left.addWidget(self.entry)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWEditPropertyListNames")
        self.list.addItems(name_list())
        left.addWidget(self.list, 1)
        lay.addLayout(left, 1)
        side = QtWidgets.QVBoxLayout()
        for text, fn in (("Add", self.add), ("Delete", self.remove), ("Move Up", lambda: self.move(-1)),
                         ("Move Down", lambda: self.move(1))):
            b = QtWidgets.QPushButton(text)
            b.setObjectName("SWEditPropertyList" + text.replace(" ", ""))
            b.clicked.connect(lambda checked=False, fn=fn: fn())
            side.addWidget(b)
        side.addStretch(1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.setOrientation(Qt.Vertical)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        side.addWidget(bb)
        lay.addLayout(side)

    def names(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def add(self, name=None):
        name = (name or self.entry.text()).strip()
        if name and name not in self.names():
            self.list.addItem(name)
            self.entry.clear()
            return True
        return False

    def remove(self):
        r = self.list.currentRow()
        if r >= 0:
            self.list.takeItem(r)

    def move(self, step):
        r = self.list.currentRow()
        to = r + step
        if r >= 0 and 0 <= to < self.list.count():
            item = self.list.takeItem(r)
            self.list.insertItem(to, item)
            self.list.setCurrentRow(to)

    def accept(self):
        set_name_list(self.names())
        super().accept()


class _NameDelegate(QtWidgets.QStyledItemDelegate):
    """The Property Name cell: a drop-down of the Edit List names that also takes a typed name."""

    def createEditor(self, parent, option, index):
        box = QtWidgets.QComboBox(parent)
        box.setEditable(True)
        box.addItems(name_list())
        return box

    def setEditorData(self, editor, index):
        editor.setCurrentText(index.data() or "")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText())

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        try:

            if not (index.data() or "") and index.row() == index.model().rowCount() - 1:
                painter.save()
                painter.setPen(option.palette.color(QtGui.QPalette.Disabled, QtGui.QPalette.Text))
                painter.drawText(option.rect.adjusted(4, 0, -4, 0), int(Qt.AlignLeft | Qt.AlignVCenter),
                                 NEW_ROW_TEXT)
                painter.restore()
        except Exception as _fw_err:
            _fw_log("customprops.py:new-row", _fw_err)


NEW_ROW_TEXT = "<Type a new property>"


def link_text(doc, name, config=None):
    ""

    file_name = os.path.basename(doc.FileName) if getattr(doc, "FileName", "") else doc.Label + ".FCStd"
    if config:
        return '"SW-%s@@%s@%s"' % (name, config, file_name)
    return '"SW-%s@%s"' % (name, file_name)


class _ValueDelegate(QtWidgets.QStyledItemDelegate):
    ""


    def createEditor(self, parent, option, index):
        box = QtWidgets.QComboBox(parent)
        box.setEditable(True)
        box.setObjectName("SWCustomPropertiesValueBox")
        editor = self.parent().parent() if self.parent() is not None else None
        doc = getattr(editor, "doc", None) or App.ActiveDocument
        config = getattr(editor, "config", None) if type(editor).__name__ == "ConfigEditor" else None


        links = list(LINKS)
        box.textActivated.connect(lambda t, b=box, d=doc, c=config: self._link_picked(b, t, d, c))
        try:
            own = index.model().index(index.row(), 0).data() or ""
            links += ['$PRP:"%s"' % n for n, _k, _v in read(doc) if n and n != own]
            from . import configtable
            for o in doc.Objects:
                if o.TypeId.startswith("Sketcher::"):
                    links += ['"%s@%s"' % (sw, o.Label) for _i, sw, _n in configtable.dimension_names(o)]
        except Exception as _fw_err:
            _fw_log("customprops.py:271", _fw_err)
        links += cut_list_links(doc)
        box.addItems(links)
        box.insertSeparator(box.count())
        box.addItems(UNIT_CHOICES)
        box.setProperty("swLastText", "")
        box.currentTextChanged.connect(lambda t, b=box: self._unit_picked(b, t))
        return box

    @staticmethod
    def _link_picked(box, text, doc, config):
        if text not in LINKS or doc is None:
            return
        box.blockSignals(True)
        box.setEditText(link_text(doc, text, config))
        box.blockSignals(False)
        box.setProperty("swLastText", box.currentText())

    @staticmethod
    def _unit_picked(box, text):
        if text in UNIT_CHOICES:
            expr, _old = split_unit(box.property("swLastText") or "")
            box.blockSignals(True)
            box.setEditText(("%s %s" % (expr, text)).strip())
            box.blockSignals(False)
        box.setProperty("swLastText", box.currentText())

    def setEditorData(self, editor, index):
        editor.setCurrentText(index.data() or "")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText())


def cut_list_items(doc):
    """The weldment / structure system cut list items of the part, or []."""
    try:
        from . import wecutlist
        box = wecutlist.folder(doc)
        return list(box.Items) if box is not None else []
    except Exception as _fw_err:
        _fw_log("customprops.py:304", _fw_err)
        return []


def cut_list_links(doc):
    ""
    out = []
    try:
        from . import wecutlist
        for item in cut_list_items(doc):
            for n, _k, v in wecutlist.item_properties(item):
                text = str(v)
                if "@@@" not in text:
                    part = os.path.basename(doc.FileName or doc.Label)
                    text = '"%s@@@%s@%s"' % (n, item.Label.split("(")[0], part)
                if text not in out:
                    out.append(text)
    except Exception as _fw_err:
        _fw_log("customprops.py:320", _fw_err)
    return out


def cut_list_value(doc, text):
    """A cut list property's evaluated value from its link "NAME@@@Cut-List-Item1@Part1", else None."""
    bare = text.strip().strip('"')
    if "@@@" not in bare:
        return None
    name, rest = bare.split("@@@", 1)
    label = rest.split("@")[0]
    try:
        from . import wecutlist
        for item in cut_list_items(doc):
            if item.Label.split("(")[0] != label:
                continue
            for n, k, v in wecutlist.item_properties(item):
                if n.upper() == name.upper():
                    return wecutlist.evaluated(item, v, k)
    except Exception:
        return None
    return None


def _solids_of(o):
    try:
        shape = o.Shape
        return [] if shape.isNull() else list(shape.Solids)
    except Exception:
        return []


def _bodies(doc):
    """The part's bodies: each PartDesign Body, and (extapps117) every other top-level solid, so an imported STEP or a Part
    workbench solid has a mass too. A feature a later one is built on and a weld bead are left out (visibility does not
    matter: a property is the file's own, shown or not)."""
    out = []
    for o in doc.Objects:
        if not _solids_of(o):
            continue
        try:
            if any(_solids_of(p) for p in o.InList if p.TypeId != "App::Part" and p.Document is o.Document):   # an assembly's link to it does not consume it
                continue
        except Exception:
            continue
        if getattr(o, "FwWeldBead", "") or type(getattr(o, "Proxy", None)).__name__ == "WeldBead":
            continue
        out.append(o)
    return out


def _link_name(text):
    ""
    what = text.strip().strip('"').strip()
    if what.startswith("SW-"):
        what = what[3:].split("@")[0]
    parts = what.split("@")
    if len(parts) >= 3 or (len(parts) == 2 and "." in parts[1]):
        what = "@".join(parts[:-1]) if len(parts) >= 3 else parts[0]
    return what.strip()


def _link_config(text):
    ""
    what = text.strip().strip('"').strip()
    if not what.startswith("SW-") or "@@" not in what or "@@@" in what:
        return None
    return what.split("@@", 1)[1].split("@")[0].strip() or None


MASS_LINKS = ("Volume", "Mass", "Density", "Material", "Surface Area", "Center of Mass")
CFG_MASS = "FreeWorks:CfgMass:"


def remember_mass(doc, config=None):
    ""

    import json
    try:
        from . import fileprops
        config = config or fileprops.active_configuration(doc)
        values = {what: _linked(doc, what, None, 0) for what in MASS_LINKS}
        values["_volume_mm3"] = sum(b.Shape.Volume for b in _bodies(doc))     # fh238: the volume whatever the units
        meta = dict(doc.Meta or {})
        text = json.dumps(values)
        if meta.get(CFG_MASS + config) != text:
            meta[CFG_MASS + config] = text
            doc.Meta = meta
    except Exception as _fw_err:
        _fw_log("customprops.py:remember_mass", _fw_err)


def _remembered(doc, what, config):
    import json
    if not config or what not in MASS_LINKS:
        return None
    try:
        from . import fileprops
        if config == fileprops.active_configuration(doc):
            return None                                  # the shown configuration: its live values
        kept = json.loads((doc.Meta or {}).get(CFG_MASS + config, "") or "{}")
    except Exception:
        return None
    if what not in kept:
        return None
    if what in ("Volume", "Surface Area"):
        return kept[what]                                # the geometry, as last rebuilt
    try:
        return _kept_with_material(doc, what, config, kept)
    except Exception as _fw_err:
        _fw_log("customprops.py:kept material", _fw_err)
        return kept[what]


def _config_material(doc, config):
    """(name, kg/m^3) of a configuration's material: its Configure Material cell, else the part's."""
    from . import material as mat
    try:
        from . import configtable, configs, configmanager as cm
        t = cm.table(doc)
        if t is not None and configs.column_of(t, configtable.MATERIAL) is not None:
            name = (configs.cell_value(t, configtable.MATERIAL, config) or "").strip()
            if name:
                return name, configtable.material_density(name)
            return "", mat.part_density(doc) or mat.DEFAULT_DENSITY
    except Exception as _fw_err:
        _fw_log("customprops.py:config material", _fw_err)
    return mat.current(doc)[1] or "", mat.density(doc)


def _mass_text(grams, doc=None):
    ""

    unit = _doc_unit("mass", doc) or "g"
    return "%.4f %s" % (grams / UNIT_SIZES["mass"][unit], unit)


def _small(value, decimals=2):
    """value at decimals, or at 3 significant digits when that would show 0 (a density in g/mm^3)."""
    if value and abs(value) < 10 ** -decimals:
        return "%.3g" % value
    return "%.*f" % (decimals, value)


def _volume_text(mm3, doc=None):
    length = _doc_unit("length", doc) or "mm"
    return "%.2f %s^3" % (mm3 / UNIT_SIZES["length"][length] ** 3, length)


def _area_text(mm2, doc=None):
    length = _doc_unit("length", doc) or "mm"
    return "%.2f %s^2" % (mm2 / UNIT_SIZES["length"][length] ** 2, length)


def _density_text(kg_m3, doc=None):
    ""
    length, mass = _doc_unit("length", doc) or "mm", _doc_unit("mass", doc) or "g"
    g_mm3 = kg_m3 * 1.0e-6
    value = g_mm3 * UNIT_SIZES["length"][length] ** 3 / UNIT_SIZES["mass"][mass]
    return "%s %s/%s^3" % (_small(value), mass, length)


def _point_text(p, doc=None):
    size = UNIT_SIZES["length"][_doc_unit("length", doc) or "mm"]
    return "%.2f, %.2f, %.2f" % tuple(float(v) / size for v in p)


def _kept_with_material(doc, what, config, kept):
    ""

    from . import massprops
    name, density = _config_material(doc, config)
    if what == "Material":
        return name or "Material <not specified>"
    if what == "Density":
        return _density_text(density, doc)
    over = massprops.overrides(doc, config)
    if what == "Mass":
        if over.get("mass"):
            return _mass_text(float(over["mass"]), doc)
        if "_volume_mm3" in kept:
            vol = float(kept["_volume_mm3"])
        else:
            vol = float(str(kept.get("Volume", "0")).split()[0])
        return _mass_text(vol * density * 1.0e-6, doc)
    if what == "Center of Mass" and over.get("center"):
        return _point_text(over["center"][:3], doc)
    return kept[what]


def _in_config(o, prop, config):
    ""

    if not config:
        return None
    try:
        from . import configs, configmanager
        t = configmanager.table(o.Document)
        if t is None or config not in t.names() or config == t.active() or not configs.configured(o, prop):
            return None
        v = configs.value_in(o, prop, config)
        return float(v) if isinstance(v, (int, float)) else None
    except Exception as _fw_err:
        _fw_log("customprops.py:in_config", _fw_err)
        return None


def _dimension(doc, text, config=None):
    """'D1@Sketch1' (or a named dimension 'Width@Sketch1', or 'Length@Pad') -> its value, or None; in
    config when one is named (the configuration's own value)."""
    if "@" not in text:
        return None
    dim, owner = text.split("@", 1)
    objs = [o for o in doc.Objects if o.Label == owner or o.Name == owner]
    if not objs:
        return None
    o = objs[0]
    if o.TypeId.startswith("Sketcher::"):
        try:
            from . import configtable
            for index, sw_name, _own in configtable.dimension_names(o):
                if sw_name == dim:
                    q = o.Constraints[index].Value
                    c = o.Constraints[index]
                    if c.Name and c.Type != "Angle":
                        own = _in_config(o, "Constraints." + c.Name, config)
                        if own is not None:
                            q = own
                    return ("%.6g" % (q if o.Constraints[index].Type != "Angle" else __import__("math").degrees(q)))
        except Exception as _fw_err:
            _fw_log("customprops.py:376", _fw_err)
        return None
    v = getattr(o, dim, None)
    if v is None:
        return None
    own = _in_config(o, dim, config)
    if own is not None:
        return "%.6g" % own
    return "%.6g" % (v.Value if hasattr(v, "Value") else v)


def _measured(doc, bodies, density):
    """Mass Properties' result: each body's own material, and Override Mass Properties."""
    from . import massprops
    r = massprops.compute(bodies, density * 1.0e9)
    return massprops.adjust(r, massprops.overrides(doc)) if r is not None else None


def _mass(doc, bodies, density):
    ""
    try:
        r = _measured(doc, bodies, density)
        if r is not None:
            return r["mass"]
    except Exception as _fw_err:
        _fw_log("customprops.py:398", _fw_err)
    return sum(b.Shape.Volume for b in bodies) * density * 1000.0


def _box_value(doc, what):
    from . import curves
    box = curves.existing_bounding_box(doc)
    if box is None:
        return None
    try:
        if box.Shape.isNull():
            return None
        v = getattr(box, BOX_LINKS[what])
        return ("%.2f" % float(getattr(v, "Value", v))).rstrip("0").rstrip(".")
    except Exception:
        return None


def _linked(doc, what, config, depth):
    if what in BOX_LINKS:
        return _box_value(doc, what)
    kept = _remembered(doc, what, config)
    if kept is not None:
        return kept                       # another configuration's mass properties, as last shown
    bodies = _bodies(doc)
    if what in MASS_LINKS:
        vol = sum(b.Shape.Volume for b in bodies)            # mm^3
        from . import material as mat
        density = mat.density(doc) * 1.0e-9                  # kg/m^3 -> kg/mm^3
        # fh238: in the part's own Mass/Section Properties units, whichever document is active
        if what == "Volume":
            return _volume_text(vol, doc)
        if what == "Mass":
            return _mass_text(_mass(doc, bodies, density), doc)
        if what == "Density":
            return _density_text(density * 1.0e9, doc)
        if what == "Surface Area":
            return _area_text(sum(b.Shape.Area for b in bodies), doc)
        if what == "Center of Mass":
            if not bodies or vol <= 0:
                return "0, 0, 0"
            try:
                r = _measured(doc, bodies, density)
                if r is not None:
                    return _point_text(r["center"], doc)
            except Exception as _fw_err:
                _fw_log("customprops.py:424", _fw_err)
            c = sum((b.Shape.CenterOfMass * b.Shape.Volume for b in bodies), App.Vector()) * (1.0 / vol)
            return _point_text((c.x, c.y, c.z), doc)
        return mat.current(doc)[1] or "Material <not specified>"
    if what == "File Name":
        return os.path.splitext(os.path.basename(doc.FileName))[0] if doc.FileName else doc.Label
    if what == "Folder Name":
        return (os.path.dirname(doc.FileName) + os.sep) if doc.FileName else ""
    if what == "Configuration Name":
        if config:
            return config
        from . import fileprops
        return fileprops.active_configuration(doc)
    if what in ("Title", "Author", "Subject", "Keywords", "Comments"):
        from . import fileprops
        return str(fileprops.summary(doc).get(what) or "")
    if what in ("Created Date", "Last Saved Date"):
        raw = doc.CreationDate if what == "Created Date" else doc.LastModifiedDate
        try:
            return datetime.datetime.fromisoformat(str(raw).replace("Z", "")).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            return str(raw or "")
    if what == "Last Saved By":
        return doc.LastModifiedBy or ""
    if what == "Short Date":
        return datetime.date.today().strftime("%d/%m/%Y")
    if what == "Long Date":
        return datetime.date.today().strftime("%A, %d %B %Y")
    if what == "Description" and not any(n == "Description" for n, _k, _v in read(doc)):
        return doc.Comment or ""
    # another property: the configuration's own first, then the custom one
    if depth < 8:
        rows = []
        if config:
            from . import fileprops
            rows = fileprops.read_config(doc, config)
        for n, k, v in list(rows) + read(doc):
            if n == what:
                return evaluate(doc, k, v, config, depth + 1)
    dim = _dimension(doc, what, config)
    if dim is not None:
        return dim
    return None


UNIT_SIZES = {
    "length": {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8},
    "angle": {"deg": 1.0, "rad": 180.0 / math.pi},
    "mass": {"g": 1.0, "kg": 1000.0, "lb": 453.59237},
    "volume": {"mm^3": 1.0, "cm^3": 1.0e3, "m^3": 1.0e9, "in^3": 16387.064, "ft^3": 28316846.592},
}
DOC_UNITS = {"MMGS": ("mm", "g"), "CGS": ("cm", "g"), "MKS": ("m", "kg"), "IPS": ("in", "lb")}
UNIT_CHOICES = ["[units]", "[mm]", "[cm]", "[m]", "[in]", "[ft]", "[deg]", "[rad]", "[g]", "[kg]", "[lb]",
                "[mm^3]", "[cm^3]", "[in^3]"]
_UNIT_TAIL = re.compile(r"^(.*?)\s*\[([^\[\]]+)\]\s*$")


def split_unit(text):
    """'expression [unit]' -> (expression, unit); no unit -> (text, None)."""
    m = _UNIT_TAIL.match(text or "")
    return (m.group(1), m.group(2).strip()) if m else (text, None)


def _kind_of(unit):
    return next((k for k, units in UNIT_SIZES.items() if unit in units), None)


MASS_SYMBOLS = {"grams": "g", "kilograms": "kg", "pounds": "lb"}
_BASE = [False]         # fh238: while a value is converted to a [unit], links give mm and g (no rounding twice)


def _doc_unit(kind, doc=None):
    """The unit symbol of kind (length, mass, volume, angle): doc's own Document Properties > Units >
    Mass/Section Properties (fh238), else the active document's unit system."""
    if _BASE[0]:
        return {"length": "mm", "mass": "g", "volume": "mm^3", "angle": "deg"}.get(kind)
    if doc is not None:
        try:
            from . import unitspage
            length, mass, _ld, _md = unitspage.mass_units(doc)
            ls = unitspage.LENGTH_SIZES.get(length, ("mm", 1.0))[0]
            ms = MASS_SYMBOLS.get(mass, "g")
            if ls in UNIT_SIZES["length"] and ms in UNIT_SIZES["mass"]:
                return {"length": ls, "mass": ms, "volume": ls + "^3", "angle": "deg"}.get(kind)
        except Exception as _fw_err:
            _fw_log("customprops.py:_doc_unit", _fw_err)
    try:
        from . import massprops
        length, mass = DOC_UNITS.get(massprops.unit_system(), DOC_UNITS["MMGS"])
    except Exception:
        length, mass = DOC_UNITS["MMGS"]
    return {"length": length, "mass": mass, "volume": length + "^3", "angle": "deg"}.get(kind)


def convert_unit(evaluated, unit, doc=None):
    """An evaluated value converted to unit and written with it ('25.4' mm, [in] -> '1 in'). A bare number
    counts as millimetres (or degrees for an angle unit); a value written with its own unit is read in it."""
    m = re.match(r"^\s*(-?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*([A-Za-z^0-9]*)\s*$", str(evaluated))
    if not m:
        return evaluated
    number, own = float(m.group(1)), m.group(2)
    own_kind = _kind_of(own) if own else None
    if unit == "units":
        was = _BASE[0]
        _BASE[0] = False
        try:
            unit = _doc_unit(own_kind or "length", doc)
        finally:
            _BASE[0] = was
    kind = _kind_of(unit)
    if kind is None:
        return evaluated
    if own_kind is None:
        own = {"angle": "deg", "mass": "g", "volume": "mm^3"}.get(kind, "mm")
        own_kind = kind
    if own_kind != kind:
        return evaluated                  # a mass asked in inches: left as it is
    value = number * UNIT_SIZES[kind][own] / UNIT_SIZES[kind][unit]
    return "%s %s" % (("%.4f" % value).rstrip("0").rstrip("."), unit)


def evaluate(doc, kind, value, config=None, depth=0):
    expr, unit = split_unit(value.strip())
    if unit is not None and (unit == "units" or _kind_of(unit)) and depth < 8:
        was = _BASE[0]
        _BASE[0] = True
        try:
            inner = evaluate(doc, kind, expr, config, depth + 1)
        finally:
            _BASE[0] = was
        return convert_unit(inner, unit, doc)
    text = value.strip()
    if "@@@" in text:
        got = cut_list_value(doc, text)
        if got is not None:
            return got
    if text.startswith("$PRP:") or text.startswith("$PRPSHEET:"):
        what = _link_name(text.split(":", 1)[1])
        got = _linked(doc, what, config, depth)
        return got if got is not None else text
    if text.startswith('"') and text.endswith('"') and text.strip('"').strip().startswith("SW-") and depth < 8:
        got = _linked(doc, _link_name(text), _link_config(text) or config, depth + 1)
        if got is not None:
            return got
    if text.startswith('"') and text.endswith('"') and "@" in text:
        got = _dimension(doc, _link_name(text), config)      # a linked dimension, "D1@Sketch1@Part1"
        if got is not None:
            return got
    text = text.strip('"')
    if kind == "Yes or no":
        return "Yes" if text.lower() in ("yes", "true", "1") else "No"
    if kind == "Number":
        try:
            return str(float(text)) if "." in text else str(int(text))
        except ValueError:
            return text
    if kind == "Date":
        try:
            return datetime.date.fromisoformat(text).strftime("%d/%m/%Y")
        except ValueError:
            return text
    return text


class _TypeCell(QtWidgets.QWidget):
    ""
    currentTextChanged = QtCore.Signal(str)
    unitChanged = QtCore.Signal(str)

    def __init__(self, kind="Text", unit="", parent=None):
        super().__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.box = QtWidgets.QComboBox()
        self.box.setObjectName("SWCustomPropertyType")
        self.box.addItems(TYPES)
        self.units = QtWidgets.QComboBox()
        self.units.setObjectName("SWCustomPropertyUnit")
        self.units.setToolTip("Unit of measure of the number")
        self.units.addItem("<none>", "")
        self.units.addItem("Document units", "units")
        for u in UNITS[2:]:
            self.units.addItem(u, u)
        lay.addWidget(self.box, 1)
        lay.addWidget(self.units)
        self.box.setCurrentText(kind if kind in TYPES else "Text")
        self.setUnit(unit)
        self.units.setVisible(self.box.currentText() == "Number")
        self.box.currentTextChanged.connect(self._kind)
        self.units.currentIndexChanged.connect(lambda *_a: self.unitChanged.emit(self.unit()))

    def _kind(self, text):
        self.units.setVisible(text == "Number")
        self.currentTextChanged.emit(text)

    def currentText(self):
        return self.box.currentText()

    def setCurrentText(self, text):
        self.box.setCurrentText(text)

    def unit(self):
        return (self.units.currentData() or "") if self.box.currentText() == "Number" else ""

    def setUnit(self, unit):
        i = self.units.findData(unit or "")
        if i < 0 and unit:
            self.units.addItem(unit, unit)       # a unit from another file keeps its text
            i = self.units.count() - 1
        self.units.setCurrentIndex(max(0, i))


class Editor(QtWidgets.QWidget):
    """The grid: Property Name | Type | Value / Text Expression | Evaluated Value, with Delete."""

    COLUMNS = ("Property Name", "Type", "Value / Text Expression", "Evaluated Value")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWCustomProperties")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        row = QtWidgets.QHBoxLayout()
        self.delete = QtWidgets.QPushButton("Delete")
        self.delete.setObjectName("SWCustomPropertiesDelete")
        self.apply_btn = QtWidgets.QPushButton("Apply")
        self.apply_btn.setObjectName("SWCustomPropertiesApply")
        self.edit_list = QtWidgets.QPushButton("Edit List")
        self.edit_list.setObjectName("SWCustomPropertiesEditList")
        self.bom_qty = QtWidgets.QComboBox()
        self.bom_qty.setObjectName("SWCustomPropertiesBomQuantity")
        self.bom_qty.setToolTip("BOM quantity: the property that says how many of this part one instance counts for")
        row.addWidget(self.delete)
        row.addWidget(self.edit_list)
        row.addStretch(1)
        self.bom_label = QtWidgets.QLabel("BOM quantity:")
        row.addWidget(self.bom_label)
        row.addWidget(self.bom_qty)
        if type(self).__name__ != "Editor":         # a configuration's own properties: the part's BOM quantity is on Custom
            self.bom_label.hide()
            self.bom_qty.hide()
        row.addWidget(self.apply_btn)
        lay.addLayout(row)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setObjectName("SWCustomPropertiesTable")
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setStretchLastSection(True)

        try:
            fm = self.table.horizontalHeader().fontMetrics()
            least = (140, 100, 200)
            for i, text in enumerate(self.COLUMNS[:3]):
                self.table.setColumnWidth(i, max(least[i], fm.horizontalAdvance(text) + 28))
        except Exception as _fw_err:
            _fw_log("customprops.py:columns", _fw_err)
        self.table.verticalHeader().setVisible(True)
        self.table.setItemDelegateForColumn(0, _NameDelegate(self.table))
        self.table.setItemDelegateForColumn(2, _ValueDelegate(self.table))
        lay.addWidget(self.table, 1)
        self.title = QtWidgets.QLabel()
        lay.insertWidget(0, self.title)
        self.doc = None
        self._filling = False
        self.table.itemChanged.connect(self._changed)
        self.table.currentCellChanged.connect(lambda *a: self._delete_shown())
        self.delete.clicked.connect(lambda checked=False: self.delete_row())
        self.apply_btn.clicked.connect(lambda checked=False: self.apply())
        self.edit_list.clicked.connect(lambda checked=False: EditListDialog(self).exec())

    def _type_box(self, kind, unit=""):
        box = _TypeCell(kind, unit)
        box.currentTextChanged.connect(lambda *a: self._re_evaluate())
        box.unitChanged.connect(lambda *a: self._re_evaluate())
        return box

    def unit_map(self):
        """{name: unit} of the grid's Number rows."""
        out = {}
        for r in range(self.table.rowCount()):
            name = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip()
            box = self.table.cellWidget(r, 1)
            if name and isinstance(box, _TypeCell) and box.currentText() == "Number" and box.unit():
                out[name] = box.unit()
        return out

    def _add_row(self, name="", kind="Text", value="", unit=""):
        r = self.table.rowCount()
        self.table.insertRow(r)
        name_item = QtWidgets.QTableWidgetItem(name)
        name_item.setData(Qt.UserRole, name)
        self.table.setItem(r, 0, name_item)
        self.table.setCellWidget(r, 1, self._type_box(kind, unit))
        self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(value))
        ev = QtWidgets.QTableWidgetItem("")
        ev.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.table.setItem(r, 3, ev)

    def load(self, doc=None):
        self.doc = doc or App.ActiveDocument
        self._filling = True
        try:
            self.table.setRowCount(0)
            self.title.setText("Custom Properties of %s" % self.doc.Label if self.doc else "No document open")
            have = units(self.doc)
            for name, kind, value in read(self.doc):
                self._add_row(name, kind, value, have.get(name, "") if kind == "Number" else "")
            self._add_row()
            self.table.item(self.table.rowCount() - 1, 0).setToolTip("<Type a new property>")
        finally:
            self._filling = False
        self._delete_shown()
        self._fill_bom_qty()
        self._re_evaluate()

    def _fill_bom_qty(self):
        if not hasattr(self, "bom_qty"):
            return
        self.bom_qty.blockSignals(True)
        self.bom_qty.clear()
        self.bom_qty.addItem("- None -", "")
        for name, _kind, _v in self.rows():
            self.bom_qty.addItem(name, name)
        now = bom_quantity_property(self.doc) if self.doc is not None else ""
        i = self.bom_qty.findData(now)
        self.bom_qty.setCurrentIndex(max(0, i))
        self.bom_qty.blockSignals(False)

    def rows(self):
        out = []
        for r in range(self.table.rowCount()):
            name = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip()
            if not name:
                continue
            box = self.table.cellWidget(r, 1)
            kind = box.currentText() if box is not None else "Text"
            value = self.table.item(r, 2).text() if self.table.item(r, 2) else ""
            out.append((name, kind, value))
        return out

    def _re_evaluate(self):
        if self.doc is None:
            return
        self._filling = True
        try:
            for r in range(self.table.rowCount()):
                if self.table.cellWidget(r, 1) is None or self.table.item(r, 3) is None:
                    continue                 # a row still being added
                box = self.table.cellWidget(r, 1)
                kind = box.currentText()
                value = self.table.item(r, 2).text() if self.table.item(r, 2) else ""
                shown = evaluate(self.doc, kind, value, getattr(self, "config", None)) if value else ""
                if kind == "Number" and isinstance(box, _TypeCell):
                    shown = with_unit(shown, box.unit())
                self.table.item(r, 3).setText(shown)
        finally:
            self._filling = False

    def _changed(self, item):
        if self._filling:
            return
        if item.column() == 0 and not self._name_taken(item):
            self._link_named(item)
            self._filling = True
            try:
                item.setData(Qt.UserRole, item.text().strip())
            finally:
                self._filling = False
        last = self.table.rowCount() - 1
        if item.row() == last and item.column() == 0 and item.text().strip():
            self._filling = True
            try:
                self._add_row()
            finally:
                self._filling = False
        self._re_evaluate()

    def _name_taken(self, item):
        ""

        name = item.text().strip()
        if not name:
            return False
        for r in range(self.table.rowCount()):
            other = self.table.item(r, 0)
            if r != item.row() and other is not None and other.text().strip().lower() == name.lower():
                self._filling = True
                try:
                    item.setText(item.data(Qt.UserRole) or "")      # the name it had before

                finally:
                    self._filling = False
                QtCore.QTimer.singleShot(0, lambda n=name: QtWidgets.QMessageBox.warning(
                    self, "Custom Properties", 'A property named "%s" already exists.' % n))
                return True
        return False

    def _link_named(self, item):
        ""
        name = item.text().strip()
        value = self.table.item(item.row(), 2)
        if name in LINKED_FIELDS and value is not None and not value.text().strip():
            self._filling = True
            try:
                value.setText(LINKED_FIELDS[name])
            finally:
                self._filling = False

    def _delete_shown(self):
        """Delete only while a property's row is picked (on the <Type a new property> row it did nothing)."""
        r = self.table.currentRow()
        self.delete.setVisible(0 <= r < self.table.rowCount() - 1)

    def delete_row(self):
        r = self.table.currentRow()
        if 0 <= r < self.table.rowCount() - 1:
            self.table.removeRow(r)
            self._delete_shown()
            return True
        return False

    def apply(self):
        if self.doc is None:
            return False
        write(self.doc, self.rows())
        write_units(self.doc, self.unit_map())
        if hasattr(self, "bom_qty") and type(self).__name__ == "Editor":
            set_bom_quantity_property(self.doc, self.bom_qty.currentData() or "")
        self.load(self.doc)
        return True


# --------------------------------------------------------------------------- the Task Pane's property tab
BLANK_DATE = QtCore.QDate(1900, 1, 1)
LINKED_FIELDS = {"Material": '$PRP:"Material"', "Weight": '$PRP:"Mass"'}     # filled from the part


def is_link(value):
    ""


    text = str(value or "").strip()
    return text.startswith("$PRP") or (len(text) > 2 and text.startswith('"') and text.endswith('"') and "@" in text)


class PropertyTab(QtWidgets.QWidget):
    """The Task Pane's Custom Properties tab in the form a Property Tab Builder tab has: one labelled
    field per property of the template (Edit List's names, then the part's other properties),
    dates with a calendar, Material and Weight read from the part, "Configuration specific" with the
    configuration it applies to, and Apply / Cancel. "Edit all properties" opens the full grid."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWPropertyTab")
        self.doc = None
        self.fields = {}
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.title = QtWidgets.QLabel("Custom Properties")
        f = self.title.font()
        f.setBold(True)
        self.title.setFont(f)
        lay.addWidget(self.title)
        top = QtWidgets.QHBoxLayout()
        self.specific = QtWidgets.QCheckBox("Configuration specific")
        self.specific.setObjectName("SWPropertyTabSpecific")
        self.config = QtWidgets.QComboBox()
        self.config.setObjectName("SWPropertyTabConfig")
        self.config.setVisible(False)              # filemenu-1119: shown with Configuration specific, not greyed
        self.specific.toggled.connect(self.config.setVisible)
        self.specific.toggled.connect(lambda *a: self._fill())
        self.config.currentTextChanged.connect(lambda *a: self._fill())
        top.addWidget(self.specific)
        top.addWidget(self.config, 1)
        lay.addLayout(top)
        self.area = QtWidgets.QScrollArea()
        self.area.setWidgetResizable(True)
        lay.addWidget(self.area, 1)
        row = QtWidgets.QHBoxLayout()
        self.apply_btn = QtWidgets.QPushButton("Apply")
        self.apply_btn.setObjectName("SWPropertyTabApply")
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.setObjectName("SWPropertyTabCancel")
        self.grid_btn = QtWidgets.QPushButton("Edit all properties...")
        self.grid_btn.setObjectName("SWPropertyTabGrid")
        self.apply_btn.clicked.connect(lambda checked=False: self.apply())
        self.cancel_btn.clicked.connect(lambda checked=False: self._fill())
        self.grid_btn.clicked.connect(lambda checked=False: self._grid())

        self.builder_btn = QtWidgets.QPushButton("Property Tab Builder...")
        self.builder_btn.setObjectName("SWPropertyTabBuilderButton")
        self.builder_btn.clicked.connect(lambda checked=False: self._builder())
        self._ptb = None
        # two rows: the Task Pane is narrow and one row cut the button words ("all properti")
        links = QtWidgets.QHBoxLayout()
        links.addWidget(self.grid_btn)
        links.addWidget(self.builder_btn)
        links.addStretch(1)
        lay.addLayout(links)
        row.addStretch(1)
        row.addWidget(self.apply_btn)
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)

    def _rows(self):
        if self.specific.isChecked():
            from . import fileprops
            return fileprops.read_config(self.doc, self.config.currentText())
        return read(self.doc)

    def load(self, doc=None):
        self.doc = doc or App.ActiveDocument
        self.config.blockSignals(True)
        self.config.clear()
        if self.doc is not None:
            from . import fileprops
            self.config.addItems(fileprops.configurations(self.doc))
            self.config.setCurrentText(fileprops.active_configuration(self.doc))
        self.config.blockSignals(False)
        self._fill()

    def _fill(self):
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        self.fields = {}
        # taskpane-nodoc-1120: nothing open, nothing to apply or edit: Apply, Cancel, Edit all properties and
        # Configuration specific are left out (they stayed clickable and did nothing); they come back with a document
        for w in (self.apply_btn, self.cancel_btn, self.grid_btn):
            w.setVisible(self.doc is not None)
        if self.doc is None:
            self.specific.setVisible(False)
            self.config.setVisible(False)
            form.addRow(QtWidgets.QLabel("No document open"))
            self.area.setWidget(page)
            return
        try:
            from . import proptabbuilder        # PATCH-MERGE: the document type's template draws the tab
            if proptabbuilder.render_into(self):
                return
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Property Tab template: %s\n" % error)
            self._ptb = None
        self.specific.setVisible(True)
        self.config.setVisible(self.specific.isChecked())
        self.title.setText("Custom Properties of %s" % self.doc.Label)
        have = {n: (k, v) for n, k, v in self._rows()}
        names = list(name_list()) + [n for n in have if n not in name_list()]
        config = self.config.currentText() if self.specific.isChecked() else None
        width = self.area.viewport().width() if self.area.isVisible() else 0
        cap = max(70, int((width if width > 150 else 280) * 0.34))
        for name in names:
            kind, value = have.get(name, ("Date" if name.endswith("Date") else "Text", ""))
            if name in LINKED_FIELDS and not value:
                value = LINKED_FIELDS[name]
            if kind == "Date":
                w = QtWidgets.QDateEdit()
                w.setCalendarPopup(True)
                w.setDisplayFormat("dd/MM/yyyy")
                w.setMinimumDate(BLANK_DATE)
                w.setSpecialValueText(" ")         # no date yet: the field shows empty
                got = QtCore.QDate.fromString(value, "yyyy-MM-dd") if value else BLANK_DATE
                w.setDate(got if got.isValid() else BLANK_DATE)
            elif is_link(value):
                w = QtWidgets.QLineEdit(evaluate(self.doc, kind, value, config))
                w.setReadOnly(True)
                w.setProperty("sw_link", value)
                w.setToolTip("From the part: %s" % value)
            else:
                w = QtWidgets.QLineEdit(value)
            if isinstance(w, QtWidgets.QLineEdit):
                w.setCursorPosition(0)              # look-audit AM2: a long value shows its start, not its end
            w.setObjectName("SWPropertyTab_" + name)
            w.setProperty("sw_kind", kind)
            self.fields[name] = w
            # look-audit AM2: the label column is capped at about a third of the pane so the value fields get the
            # room (one long name such as EngineeringApproval took 135 of 298 px); a cut name shows "..." and its
            # whole name as a tooltip
            label = QtWidgets.QLabel()
            full = name + ":"
            text = label.fontMetrics().elidedText(full, Qt.ElideRight, cap)
            if text != full:
                # look-audit TP-2 (BB22): a name too long for the column ("EngineeringApproval") goes whole on
                # its own line with its field under it, not cut to "EngineeringAp..."
                label.setText(full)
                label.setToolTip(name)
                form.addRow(label)
                form.addRow(w)
                continue
            label.setText(text)
            form.addRow(label, w)
        self.area.setWidget(page)

    def values(self):
        out = []
        for name, w in self.fields.items():
            kind = w.property("sw_kind") or "Text"
            if isinstance(w, QtWidgets.QDateEdit):
                if w.date() == BLANK_DATE:
                    continue
                out.append((name, "Date", w.date().toString("yyyy-MM-dd")))
            elif w.property("sw_link"):
                out.append((name, kind, w.property("sw_link")))
            elif w.text().strip():
                out.append((name, kind, w.text()))
        return out

    def apply(self):
        if self.doc is None:
            return False
        if self._ptb:
            from . import proptabbuilder        # PATCH-MERGE: a template-drawn tab writes per control
            return proptabbuilder.apply_tab(self)
        rows = []
        given = dict((n, (k, v)) for n, k, v in self.values())
        for n, k, v in self._rows():
            if n in given:
                k, v = given.pop(n)
            elif n in self.fields:
                continue        # emptied on the tab: it goes
            rows.append((n, k, v))
        rows += [(n, k, v) for n, (k, v) in given.items()]
        if self.specific.isChecked():
            from . import fileprops
            fileprops.write_config(self.doc, self.config.currentText(), rows)
        else:
            write(self.doc, rows)
        self._fill()
        return True

    def _builder(self):
        from . import proptabbuilder
        return proptabbuilder.show(proptabbuilder.kind_of(self.doc))

    def _grid(self):
        from . import fileprops
        return fileprops.show(self.doc, tab=2 if self.specific.isChecked() else 1)


def page(pane):
    w = QtWidgets.QWidget()
    w.setObjectName("SWTaskPaneCustomProperties")
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    tab = PropertyTab(w)
    lay.addWidget(tab)
    w.tab = tab
    w.editor = tab        # kept name for older checks: load(doc) works the same
    w.refresh = lambda: tab.load(App.ActiveDocument)
    return w
