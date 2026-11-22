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

import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import icons
from .widgets import alive

Qt = QtCore.Qt
PAGE = "ConfigurationManager"
PROP = "Configuration"
ROLE = Qt.UserRole + 1
_ENUM = re.compile(r"^\.(\w+)\.Enum$")
_RANGE = re.compile(r"cells\[<<([A-Z]+)(\d+):([A-Z]+)(\d+)>>\]")


def _col(n):
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _colnum(text):
    n = 0
    for ch in text:
        n = n * 26 + ord(ch) - 64
    return n - 1


# --------------------------------------------------------------------------- tables
class Table:
    """One configuration table: the sheet, its enumeration property and the name cells' range."""

    def __init__(self, sheet, prop, col, first, last):
        self.sheet, self.prop, self.col, self.first, self.last = sheet, prop, col, first, last

    def names(self):
        try:
            return list(self.sheet.getEnumerationsOfProperty(self.prop) or [])
        except Exception as _fw_err:
            _fw_log("configmanager.py:79", _fw_err)
            return []

    def active(self):
        try:
            return getattr(self.sheet, self.prop)
        except Exception:
            return None

    def row_of(self, name):
        for r in range(self.first, self.last + 1):
            if self._text("%s%d" % (self.col, r)) == name:
                return r
        return None

    def _text(self, cell):
        try:
            return str(self.sheet.getContents(cell)).lstrip("'=")
        except Exception:
            return ""

    def columns(self):
        """The parameter columns: row 1 cells after the name column that have something in them."""
        start = _colnum(self.col) + 1
        used = set()
        for cell in self.sheet.getUsedCells():
            m = re.match(r"([A-Z]+)(\d+)$", cell)
            if m and _colnum(m.group(1)) >= start and self.first - 1 <= int(m.group(2)) <= self.last:
                used.add(_colnum(m.group(1)))
        if not used:
            return []
        return [_col(c) for c in range(start, max(used) + 1)]


def tables(doc):
    out = []
    if doc is None:
        return out
    try:
        sheets = doc.findObjects("Spreadsheet::Sheet")     # C++ search: a 300-part assembly build asks often
    except Exception:
        sheets = [o for o in doc.Objects if o.TypeId == "Spreadsheet::Sheet"]
    for obj in sheets:
        if obj.TypeId != "Spreadsheet::Sheet":
            continue
        if any(p.TypeId == "App::LinkGroup" and p.Name.startswith("CopyOnChangeGroup") for p in obj.InList):
            continue        # a part's table copied for an assembly instance (asmcfginst), not this document's
        for path, expr in obj.ExpressionEngine:
            m = _ENUM.match(path)
            r = _RANGE.search(expr or "")
            if m and r and r.group(1) == r.group(3):
                out.append(Table(obj, m.group(1), r.group(1), int(r.group(2)), int(r.group(4))))
    return out


def table(doc):
    t = tables(doc)
    return t[0] if t else None


def _bind(t):
    """Row 1 follows the active configuration's row (FreeCAD's own binding expression)."""
    sheet = t.sheet
    for path, expr in list(sheet.ExpressionEngine):
        if path.startswith(".cells.Bind."):
            sheet.setExpression(path, None)
    cols = t.columns()
    head = t.first - 1
    if not cols:
        return
    off = t.first
    parts = "; ".join("<<%s>> + str(hiddenref(%s) + %d)" % (c, t.prop, off) for c in (cols[0], cols[-1]))
    sheet.setExpression(".cells.Bind.%s%d.%s%d" % (cols[0], head, cols[-1], head), "tuple(.cells; %s)" % parts)


def _set_range(t, last):
    t.sheet.setExpression(".%s.Enum" % t.prop, "cells[<<%s%d:%s%d>>]" % (t.col, t.first, t.col, last))
    t.last = last


def _settle(sheet):
    """Recompute until the configuration list reads its cells (a list made in the same recompute
    as its cells can read them before they are computed)."""
    doc = sheet.Document
    for _ in range(3):
        sheet.touch()
        doc.recompute()


def insert_table(doc, name="Default", design=False):
    ""


    doc.openTransaction("Insert Design Table")
    try:
        sheet = doc.addObject("Spreadsheet::Sheet", "DesignTable")
        sheet.Label = "Design Table"
        sheet.set("A1", "Configuration")
        sheet.set("A2", name)
        sheet.addProperty("App::PropertyEnumeration", PROP, "Configuration", "The configuration shown", 0, False, True)
        doc.recompute()
        t = Table(sheet, PROP, "A", 2, 2)
        _set_range(t, 2)
        doc.recompute()
    finally:
        doc.commitTransaction()
    try:
        from . import cmflows
        meta = dict(doc.Meta)
        if design:
            meta.pop(cmflows.HIDDEN, None)
        else:
            meta[cmflows.HIDDEN] = "1"
        doc.Meta = meta
        if App.GuiUp and sheet.ViewObject is not None:
            sheet.ViewObject.ShowInTree = bool(design)
    except Exception as _fw_err:
        _fw_log("configmanager.py:insert_table", _fw_err)
    return t


def show(t, name):
    ""
    try:
        from . import dtoptions
        dtoptions.reload_link(t.sheet)          # Link to file: the file changed since it was read
    except Exception as error:
        App.Console.PrintLog("FreeCAD: design table link: %s\n" % error)
    if name not in t.names():
        return False
    doc = t.sheet.Document
    doc.openTransaction("Show Configuration")
    try:
        _bind(t)
        held = _suppress_first(t, name)
        setattr(t.sheet, t.prop, name)
        doc.recompute()
        if held:
            for obj, expression in held:
                obj.setExpression("Suppressed", expression)
            doc.recompute()
    finally:
        doc.commitTransaction()
    show_colour(doc, name)
    refresh_all()
    return True


def _suppress_first(t, name):
    ""







    from . import configs
    sheet = t.sheet.Name
    held, first = [], False
    for obj in t.sheet.Document.Objects:
        try:
            expression = dict(obj.ExpressionEngine).get("Suppressed")
        except Exception:
            continue
        m = re.match(r"^\s*%s\.(%s\w+)" % (re.escape(sheet), re.escape(configs.SUPPRESS)), expression or "")
        if not m:
            continue
        value = configs.cell_value(t, m.group(1), name)
        if value is None:
            continue
        on = value.strip() in ("1", "1.0", "True")
        if on != bool(obj.Suppressed):
            # suppressed now, or still suppressed while the values change (unsuppressed last)
            obj.setExpression("Suppressed", "1 == 1")
            held.append((obj, expression))
            first = first or on
    if first:
        t.sheet.Document.recompute()
    return held


OUTSIDE = "FreeWorks:CfgOutsideDesignTable"


def outside_table(doc):
    ""

    text = dict(doc.Meta or {}).get(OUTSIDE, "")
    return [n for n in text.split("\n") if n]


def set_outside_table(doc, name, on):
    names = [n for n in outside_table(doc) if n != name] + ([name] if on else [])
    meta = dict(doc.Meta)
    if names:
        meta[OUTSIDE] = "\n".join(names)
    else:
        meta.pop(OUTSIDE, None)
    doc.Meta = meta


def add(t, name, from_table=False):
    ""


    name = (name or "").strip()
    if not name or name in t.names():
        return False
    sheet, doc = t.sheet, t.sheet.Document
    outside = False
    if not from_table:
        try:
            from . import dtoptions
            outside = not dtoptions.allow_new_configuration(doc, quiet=True)
        except ImportError:
            pass
    row = t.last + 1
    if any(sheet.getContents("%s%d" % (c, row)) for c in [t.col] + t.columns()):
        return False                                 # the row under the table is in use
    src = t.row_of(t.active()) or t.first
    doc.openTransaction("Add Configuration")
    try:
        sheet.set("%s%d" % (t.col, row), name)
        for c in t.columns():
            sheet.set("%s%d" % (c, row), str(sheet.getContents("%s%d" % (c, src))))
        doc.recompute()                              # the new name cell first, then the list
        _set_range(t, row)
        _settle(sheet)
        _bind(t)
        setattr(sheet, t.prop, name)
        doc.recompute()
        set_outside_table(doc, name, outside)
    finally:
        doc.commitTransaction()
    _new_marks(doc, name)
    refresh_all()
    return True


DISPLAY_MARK = "FreeWorks:CfgDisplayMark:"


def display_mark(doc, name):
    return dict(doc.Meta or {}).get(DISPLAY_MARK + name, "") == "1"


def set_display_mark(doc, name, on):
    ""

    meta = dict(doc.Meta)
    if on:
        meta[DISPLAY_MARK + name] = "1"
    else:
        meta.pop(DISPLAY_MARK + name, None)
        meta.pop("FreeWorks:CfgDisplayData:" + name, None)
    doc.Meta = meta
    refresh_all()


def _purge(doc, active):
    ""

    try:
        from . import optionspages
        if not optionspages.stored("Performance", "Purge cached configuration data", False):
            return
    except Exception:
        return
    meta = dict(doc.Meta)
    keep = "FreeWorks:CfgDisplayData:" + active
    gone = [k for k in meta if k.startswith("FreeWorks:CfgDisplayData:") and k != keep]
    if gone:
        for k in gone:
            meta.pop(k)
        doc.Meta = meta


def save_display_data(doc):
    """On save: the active configuration, when marked, records its box and volume (shown in its tooltip)."""
    t = table(doc)
    if t is None:
        return None
    name = t.active()
    _purge(doc, name)
    if not display_mark(doc, name):
        return None
    import json
    shapes = [o.Shape for o in doc.Objects if o.TypeId == "PartDesign::Body" and not o.Shape.isNull()]
    if not shapes:
        return None
    bb = shapes[0].BoundBox
    for s in shapes[1:]:
        bb.add(s.BoundBox)
    data = {"box": [round(bb.XLength, 3), round(bb.YLength, 3), round(bb.ZLength, 3)],
            "volume": round(sum(s.Volume for s in shapes), 3)}
    meta = dict(doc.Meta)
    meta["FreeWorks:CfgDisplayData:" + name] = json.dumps(data)
    doc.Meta = meta
    return data


def _new_marks(doc, name):
    """Document Properties > Configurations: marks new configurations take."""
    try:
        from . import optionspages
        if optionspages.doc_value(doc, "Configurations", "Add Rebuild on Save mark to new configurations", False):
            set_rebuild_mark(doc, name, True)
        if optionspages.doc_value(doc, "Configurations", "Add Display Data Mark to new configurations", False):
            set_display_mark(doc, name, True)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: configuration marks: %s\n" % error)


def descendants(doc, name):
    """The derived configurations under name, their own derived ones too (deepest last)."""
    out, todo = [], [name]
    while todo:
        for c in children_of(doc, todo.pop(0)):
            if c not in out and c != name:
                out.append(c)
                todo.append(c)
    return out


def can_delete(t, name):
    """Not the active configuration, not one the active one is derived from, not the last one."""
    names = t.names()
    doc = t.sheet.Document
    group = [name] + [c for c in descendants(doc, name) if c in names]
    return name in names and t.active() not in group and len(names) > len(group)


class ConfigConfirmDelete(QtWidgets.QDialog):
    ""


    def __init__(self, name, kids, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setWindowTitle("Confirm Delete")
        self.setObjectName("SWConfirmDelete")
        self.answer = False
        row = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("Delete the following configuration?"))
        item = QtWidgets.QLineEdit(name)
        item.setReadOnly(True)
        item.setObjectName("SWConfirmDeleteItem")
        left.addWidget(item)
        if kids:
            left.addWidget(QtWidgets.QLabel("And its derived configurations:"))
            lst = QtWidgets.QListWidget()
            lst.setObjectName("SWConfirmDeleteDependents")
            lst.addItems(list(kids))
            lst.setMinimumSize(270, 90)
            left.addWidget(lst)
        row.addLayout(left)
        right = QtWidgets.QVBoxLayout()
        for key, text, ans in (("Yes", "&Yes", True), ("No", "&No", False)):
            b = QtWidgets.QPushButton(text)
            b.setObjectName("SWConfirmDelete" + key)
            b.clicked.connect(lambda _c=False, a=ans: self._done(a))
            right.addWidget(b)
            if ans:
                b.setDefault(True)
        right.addStretch(1)
        row.addLayout(right)

    def _done(self, answer):
        self.answer = answer
        self.accept() if answer else self.reject()


def confirm_delete(name, kids):
    box = ConfigConfirmDelete(name, kids)
    box.exec_()
    return box.answer


def delete(t, name, ask=True):
    ""
    if not can_delete(t, name):
        return False
    doc = t.sheet.Document
    kids = [c for c in descendants(doc, name) if c in t.names()]
    if ask and App.GuiUp and not confirm_delete(name, kids):
        return False
    for k in reversed(kids):
        _delete_one(table(doc), k)
    return _delete_one(table(doc), name)


def _delete_one(t, name):
    names = t.names()
    if name not in names or name == t.active() or len(names) < 2:
        return False
    sheet, doc = t.sheet, t.sheet.Document
    row = t.row_of(name)
    if row is None:
        return False
    active = t.active()
    cols = [t.col] + t.columns()
    doc.openTransaction("Delete Configuration")
    try:
        if name in outside_table(doc):
            set_outside_table(doc, name, False)
        for r in range(row, t.last):
            for c in cols:
                sheet.set("%s%d" % (c, r), str(sheet.getContents("%s%d" % (c, r + 1))))
        for c in cols:
            sheet.clear("%s%d" % (c, t.last))
        doc.recompute()
        _set_range(t, t.last - 1)
        _settle(sheet)
        _bind(t)
        setattr(sheet, t.prop, active)
        doc.recompute()
    finally:
        doc.commitTransaction()
    meta = dict(doc.Meta)
    up = meta.pop(PARENT + name, "")
    for k in [k for k, v in meta.items() if k.startswith(PARENT) and v == name]:
        if up:
            meta[k] = up
        else:
            meta.pop(k)
    meta.pop(MARK + name, None)
    for key in EXTRAS.values():
        meta.pop(key + name, None)
    doc.Meta = meta
    try:
        from . import fileprops         # fp96: its own properties go with it
        fileprops.config_deleted(doc, name)
    except Exception as _fw_err:
        _fw_log("configmanager.py:delete-props", _fw_err)
    try:
        from . import displaystates        # its own display states go with it (linked)
        displaystates.config_deleted(doc, name)
    except Exception as _fw_err:
        _fw_log("configmanager.py:delete-states", _fw_err)
    refresh_all()
    return True


def edit_table(t, new_window=False):
    ""

    try:
        from . import dtedit
        return dtedit.open_editor(t.sheet.Document, new_window) is not None
    except Exception as error:
        App.Console.PrintLog("FreeCAD: design table window: %s\n" % error)
    try:
        Gui.ActiveDocument.setEdit(t.sheet.Name)
    except Exception:
        return False
    try:
        from . import dtoptions     # Options > Enable cell drop-down lists
        dtoptions.install_dropdowns(t.sheet)
    except Exception as _fw_err:
        _fw_log("configmanager.py:404", _fw_err)
    return True


def part_name(doc):
    return doc.Label if doc is not None else ""


# --------------------------------------------------------------------------- Add Configuration PM
class AddPanel:
    ""




    title = "Add Configuration"

    def __init__(self, doc, name=None, parent=None):
        from . import configs
        self.doc = doc
        self.editing = name
        self.parent = parent        # Add Derived Configuration: the configuration it comes under
        derived = bool(parent or (name and parent_of(doc, name)))
        form = QtWidgets.QWidget()
        form.setObjectName("SWAddConfigurationPM" if name is None else "SWConfigurationPropertiesPM")
        form.setWindowTitle(self.title if name is None else "Configuration Properties")
        lay = QtWidgets.QVBoxLayout(form)
        box = QtWidgets.QGroupBox("Configuration Properties")
        g = QtWidgets.QVBoxLayout(box)
        g.addWidget(QtWidgets.QLabel("Configuration name:"))
        self.name = QtWidgets.QLineEdit()
        self.name.setObjectName("SWConfigName")
        t = table(doc)
        n = len(t.names()) + 1 if t else 1
        p = configs.properties(doc, name) if name else configs.properties(doc, "")
        if not name:
            # Document Properties > Configurations: Default Bill Of Materials part number for new configurations
            try:
                from . import optionspages
                p["bom"] = str(optionspages.doc_value(
                    doc, "Configurations", "Default Bill Of Materials part number for new configurations",
                    "Document Name") or "Document Name")
            except Exception as _fw_err:
                _fw_log("configmanager.py:447", _fw_err)
        if parent and not name:
            n = 1 + len(children_of(doc, parent))
            self.name.setText("%s-%d" % (parent, n))
            while t is not None and self.name.text() in t.names():
                n += 1
                self.name.setText("%s-%d" % (parent, n))
        else:
            self.name.setText(name if name else "Configuration%d" % n)
        g.addWidget(self.name)
        g.addWidget(QtWidgets.QLabel("Description:"))
        self.description = QtWidgets.QLineEdit(p["description"])
        self.description.setObjectName("SWConfigDescription")
        g.addWidget(self.description)
        x = extras(doc, name) if name else extras(doc, "")
        self.use_in_bom = QtWidgets.QCheckBox("Use in bill of materials")
        self.use_in_bom.setObjectName("SWConfigUseInBom")
        self.use_in_bom.setToolTip("The bill of materials shows the description above")
        self.use_in_bom.setChecked(x["use_in_bom"])
        g.addWidget(self.use_in_bom)
        g.addWidget(QtWidgets.QLabel("Comment:"))
        self.comment = QtWidgets.QPlainTextEdit(x["comment"])
        self.comment.setObjectName("SWConfigComment")
        self.comment.setFixedHeight(60)
        g.addWidget(self.comment)
        lay.addWidget(box)
        bom = QtWidgets.QGroupBox("Bill of Materials Options")
        gb = QtWidgets.QVBoxLayout(bom)
        wrap = QtWidgets.QLabel("Part number displayed when used in a bill of materials:")
        wrap.setWordWrap(True)                  # the PropertyManager keeps the pane's width
        gb.addWidget(wrap)
        self.bom = QtWidgets.QComboBox()
        self.bom.setObjectName("SWConfigBomMode")
        for m in configs.BOM_MODES:
            if derived or m != configs.PARENT_MODE:

                self.bom.addItem("User Specified Name" if m == "User Specified" else m, m)
        self.bom.setCurrentIndex(max(0, self.bom.findData(p["bom"])))
        gb.addWidget(self.bom)
        self.part_number = QtWidgets.QLineEdit(p["part_number"])
        self.part_number.setObjectName("SWConfigPartNumber")
        # always live: typing a part number picks User Specified Name (no greyed box)
        self.part_number.setPlaceholderText("Type a name to use your own")
        self.part_number.textEdited.connect(self._user_number)
        gb.addWidget(self.part_number)
        lay.addWidget(bom)
        adv = QtWidgets.QGroupBox("Advanced Options")
        ga = QtWidgets.QVBoxLayout(adv)

        self.suppress_new = QtWidgets.QCheckBox("Suppress features")
        self.suppress_new.setObjectName("SWConfigSuppressNew")
        self.suppress_new.setToolTip("Features added while another configuration is shown are suppressed in this one")
        self.suppress_new.setChecked(p["suppress_new"])
        ga.addWidget(self.suppress_new)
        row = QtWidgets.QHBoxLayout()
        self.use_colour = QtWidgets.QCheckBox("Use configuration specific color")
        self.use_colour.setObjectName("SWConfigUseColor")
        self.colour = QtWidgets.QPushButton("Color...")
        self.colour.setObjectName("SWConfigColor")
        self.colour.setMaximumWidth(72)         # beside the box within the pane's width
        self.rgb = x["color"] or (0.8, 0.8, 0.8)
        self.use_colour.setChecked(x["color"] is not None)
        self.colour.clicked.connect(self._pick_colour)       # always live: a picked colour ticks the box
        self._swatch()
        ga.addWidget(self.use_colour)
        row.addSpacing(20)                      # under its box, so the row keeps within the pane's width
        row.addWidget(self.colour)
        row.addStretch(1)
        ga.addLayout(row)

        self.rebuild_mark = QtWidgets.QCheckBox("Add Rebuild/Save Mark")
        self.rebuild_mark.setObjectName("SWConfigRebuildMark")
        self.rebuild_mark.setToolTip("The configuration is rebuilt and its data saved when the part is saved")
        if name:
            self.rebuild_mark.setChecked(rebuild_mark(doc, name))
        else:
            try:
                from . import optionspages
                self.rebuild_mark.setChecked(bool(optionspages.doc_value(
                    doc, "Configurations", "Add Rebuild on Save mark to new configurations", False)))
            except Exception as _fw_err:
                _fw_log("configmanager.py:rebuild_mark", _fw_err)
        ga.addWidget(self.rebuild_mark)
        lay.addWidget(adv)
        if name:

            props = QtWidgets.QPushButton("Custom Properties...")
            props.setObjectName("SWConfigCustomProperties")
            props.clicked.connect(lambda: self._custom_properties())
            lay.addWidget(props)
        lay.addStretch(1)
        self.form = form

    def _custom_properties(self):
        from . import fileprops
        box = fileprops.show(self.doc, tab=2)
        try:
            box.applies.setCurrentText(self.editing)
        except Exception as _fw_err:
            _fw_log("configmanager.py:526", _fw_err)
        return box

    def _swatch(self):
        r, g, b = (int(c * 255) for c in self.rgb[:3])
        ink = "#000000" if 0.299 * r + 0.587 * g + 0.114 * b > 140 else "#ffffff"   # readable: not taken for greyed
        self.colour.setStyleSheet("QPushButton { background: rgb(%d,%d,%d); color: %s; }" % (r, g, b, ink))

    def _pick_colour(self):
        got = QtWidgets.QColorDialog.getColor(QtGui.QColor.fromRgbF(*self.rgb[:3]), self.form, "Configuration color")
        if got.isValid():
            self.rgb = (got.redF(), got.greenF(), got.blueF())
            self._swatch()
            self.use_colour.setChecked(True)

    def _user_number(self, text):
        k = self.bom.findData("User Specified")
        if text.strip() and k >= 0 and self.bom.currentIndex() != k:
            self.bom.setCurrentIndex(k)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _save_extras(self, name):
        if hasattr(self, "rebuild_mark") and rebuild_mark(self.doc, name) != self.rebuild_mark.isChecked():
            set_rebuild_mark(self.doc, name, self.rebuild_mark.isChecked())
        set_extras(self.doc, name, self.use_in_bom.isChecked(), self.comment.toPlainText(),
                   self.rgb if self.use_colour.isChecked() else None)
        t = table(self.doc)
        if t is not None and t.active() == name:
            show_colour(self.doc, name)

    def accept(self):
        from . import configs
        name = self.name.text().strip()
        t = table(self.doc)
        if self.editing is not None:
            if name != self.editing and (not name or (t and name in t.names())):
                QtWidgets.QMessageBox.warning(self.form, "Configuration Properties",
                                              "A configuration with this name exists, or the name is empty.")
                return False
            configs.set_properties(self.doc, self.editing, self.description.text(), self.part_number.text(),
                                   self.bom.currentData(), self.suppress_new.isChecked(),
                                   new_name=name if name != self.editing else None)
            if name != self.editing:
                move_extras(self.doc, self.editing, name)
            self._save_extras(name)
        else:
            if t is None:
                t = insert_table(self.doc, "Default")   # every part has its Default configuration
            if self.parent:
                ok = add_derived(t, self.parent, name)
            elif getattr(self, "rename_default", False) and name and name != "Default":
                configs.rename(t, "Default", name)
                t = table(self.doc)
                ok = t is not None and name in t.names()
            else:
                ok = name == "Default" or add(t, name)
            if not ok:
                QtWidgets.QMessageBox.warning(self.form, "Add Configuration",
                                              "A configuration with this name exists, or the name is empty.")
                return False
            if self.description.text() or self.part_number.text() or self.bom.currentData() != "Document Name" \
                    or self.suppress_new.isChecked():
                configs.set_properties(self.doc, name or "Default", self.description.text(), self.part_number.text(),
                                       self.bom.currentData(), self.suppress_new.isChecked())
            self._save_extras(name or "Default")
        Gui.Control.closeDialog()
        refresh_all()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


# --------------------------------------------------------------------------- Use in BOM, Comment, color
EXTRAS = {"use_in_bom": "FreeWorks:CfgUseInBom:", "comment": "FreeWorks:CfgComment:", "color": "FreeWorks:CfgColor:"}
COLOUR_BASE = "FreeWorks:CfgColorBase"


def extras(doc, name):
    meta = dict(doc.Meta)
    colour = meta.get(EXTRAS["color"] + name, "")
    try:
        colour = tuple(float(x) for x in colour.split(",")[:3]) if colour else None
    except ValueError:
        colour = None
    return {"use_in_bom": meta.get(EXTRAS["use_in_bom"] + name, "0") == "1",
            "comment": meta.get(EXTRAS["comment"] + name, ""), "color": colour}


def set_extras(doc, name, use_in_bom, comment, colour):
    meta = dict(doc.Meta)
    for key, value in ((EXTRAS["use_in_bom"], "1" if use_in_bom else ""), (EXTRAS["comment"], comment or ""),
                       (EXTRAS["color"], ",".join("%.4f" % c for c in colour[:3]) if colour else "")):
        if value:
            meta[key + name] = value
        else:
            meta.pop(key + name, None)
    doc.Meta = meta


def move_extras(doc, old, new):
    meta = dict(doc.Meta)
    for key in EXTRAS.values():
        if key + old in meta:
            meta[key + new] = meta.pop(key + old)
    doc.Meta = meta


def ask_comment(doc, name):
    """Comment > Add Comment: the configuration's comment (also on Configuration Properties)."""
    x = extras(doc, name)
    text, ok = QtWidgets.QInputDialog.getMultiLineText(Gui.getMainWindow(), "Comment",
                                                       "Comment for %s:" % name, x["comment"])
    if not ok:
        return False
    set_extras(doc, name, x["use_in_bom"], text, x["color"])
    refresh_all()
    return True


def bom_description(doc, name):
    """The description the bill of materials shows (Use in bill of materials on), else None."""
    if not extras(doc, name)["use_in_bom"]:
        return None
    from . import configs
    return configs.properties(doc, name)["description"]


def show_colour(doc, name):
    """Use configuration specific color: the part takes the configuration's colour when it is
    shown, and its own colour back in a configuration without one."""
    try:
        from . import appearance
    except ImportError:
        return
    bodies = appearance.bodies(doc)
    if not bodies:
        return
    colour = extras(doc, name)["color"]
    meta = dict(doc.Meta)
    target = appearance.Target("part", bodies[0])
    if colour is not None:
        if COLOUR_BASE not in meta:
            stored = appearance.stored(bodies[0]).get("part", "")
            meta[COLOUR_BASE] = stored or "none"
            doc.Meta = meta
        appearance.apply([target], tuple(colour) + (0.0,))
    elif COLOUR_BASE in meta:
        base = meta.pop(COLOUR_BASE)
        doc.Meta = meta
        if base == "none":
            appearance.remove([target])
        else:
            appearance.apply([target], appearance.decode(base, True))


def configuration_properties(doc, name):
    panel = AddPanel(doc, name)
    QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(panel))
    return panel


_LAST_DEFAULT = []


def default_properties(doc):
    """Configuration Properties of Default before the document has a configuration table: the same
    page; OK makes the table (Default) as Add Configuration does, then stores what was typed."""
    panel = AddPanel(doc)
    panel.rename_default = True     # a new name renames Default (no second configuration)
    _LAST_DEFAULT[:] = [panel]
    panel.name.setText("Default")
    panel.form.setObjectName("SWConfigurationPropertiesPM")
    panel.form.setWindowTitle("Configuration Properties")
    QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(panel))
    return panel


def add_configuration(doc):
    panel = AddPanel(doc)
    QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(panel))
    return panel


# --------------------------------------------------------------------------- derived configurations
PARENT = "FreeWorks:CfgParent:"
MARK = "FreeWorks:CfgRebuildMark:"
PUBLISHED = "FreeWorks:CfgPublished"


def parent_of(doc, name):
    return dict(doc.Meta or {}).get(PARENT + name, "")


def parents_up(doc, name):
    """name's parent, its parent and so on (a derived configuration cannot come under its own child)."""
    out = []
    p = parent_of(doc, name)
    while p and p not in out:
        out.append(p)
        p = parent_of(doc, p)
    return out


def children_of(doc, name):
    return [k[len(PARENT):] for k, v in dict(doc.Meta or {}).items() if k.startswith(PARENT) and v == name]


def add_derived(t, parent, name):
    ""

    doc = t.sheet.Document
    if parent not in t.names():
        return False
    if t.active() != parent:
        show(t, parent)
    if not add(t, name):
        return False
    meta = dict(doc.Meta)
    meta[PARENT + name] = parent
    doc.Meta = meta
    refresh_all()
    return True


def follow_parent(t, parent, column, old, new):
    """A parent's value changed from old to new: its derived configurations that still had old take new."""
    doc = t.sheet.Document
    for child in children_of(doc, parent):
        r = t.row_of(child)
        if r is None:
            continue
        cell = "%s%d" % (column, r)
        if str(t.sheet.getContents(cell)) == str(old):
            t.sheet.set(cell, str(new))
            follow_parent(t, child, column, old, new)
    doc.recompute()


def ask_derived(doc, parent):
    t = table(doc)
    if t is None:
        return False

    panel = AddPanel(doc, parent=parent)
    QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(panel))
    return panel


def rebuild_mark(doc, name):
    return dict(doc.Meta or {}).get(MARK + name, "") == "1"


def set_rebuild_mark(doc, name, on):
    meta = dict(doc.Meta)
    if on:
        meta[MARK + name] = "1"
    else:
        meta.pop(MARK + name, None)
    doc.Meta = meta
    refresh_all()


LAST_REBUILT = {}      # doc name -> {configuration: (ok, failed labels, time)}


def marked(doc):
    t = table(doc)
    return [n for n in (t.names() if t else []) if rebuild_mark(doc, n)]


def rebuild_marked(doc):
    ""



    import time
    t = table(doc)
    names = [n for n in marked(doc) if t is not None and n != t.active()]
    if not names:
        return {}
    active = t.active()
    gdoc = Gui.getDocument(doc.Name) if Gui is not None else None
    was_modified = gdoc.Modified if gdoc is not None else False
    out = {}
    try:
        _bind(t)
        for name in names:
            setattr(t.sheet, t.prop, name)
            doc.recompute()
            bad = [o.Label for o in doc.Objects if "Invalid" in o.State]
            out[name] = (not bad, bad)
    finally:
        setattr(t.sheet, t.prop, active)
        doc.recompute()
        if gdoc is not None and not was_modified:
            gdoc.Modified = False
    LAST_REBUILT[doc.Name] = {n: (ok, bad, time.strftime("%H:%M:%S")) for n, (ok, bad) in out.items()}
    failed = [n for n, (ok, _b) in out.items() if not ok]
    msg = "Rebuild/Save Mark: rebuilt %s" % ", ".join(out)
    if failed:
        msg += "; rebuild errors in %s" % ", ".join(failed)
        App.Console.PrintWarning(msg + "\n")
    try:
        Gui.getMainWindow().statusBar().showMessage(msg, 8000)
    except Exception as _fw_err:
        _fw_log("configmanager.py:802", _fw_err)
    refresh_all()
    return out


# --------------------------------------------------------------------------- Configuration Publisher
def published(doc):
    """[(column alias, control)] the Configuration Publisher shows, control "List" or "Number"."""
    raw = dict(doc.Meta or {}).get(PUBLISHED, "")
    out = []
    for part in raw.split(";"):
        if ":" in part:
            a, c = part.split(":", 1)
            out.append((a, c))
    return out


def set_published(doc, items):
    meta = dict(doc.Meta)
    meta[PUBLISHED] = ";".join("%s:%s" % (a, c) for a, c in items)
    doc.Meta = meta


def parameters(t):
    """[(column, alias, {configuration: value})] of the table."""
    out = []
    for c in t.columns():
        cell = "%s%d" % (c, t.first - 1)
        alias = t.sheet.getAlias(cell) or t._text(cell)
        values = {n: t._text("%s%d" % (c, t.row_of(n))) for n in t.names() if t.row_of(n)}
        out.append((c, alias, values))
    return out


def _same(a, b):
    """Two table values alike: as numbers (25.4 and 25.400000001), else as text."""
    try:
        x, y = float(str(a)), float(str(b))
        return abs(x - y) <= 1e-6 * max(1.0, abs(x), abs(y))
    except (TypeError, ValueError):
        return str(a) == str(b)


def pick_configuration(t, wanted):
    """The configuration whose values match wanted {alias: value} best (the publisher's Apply)."""
    params = {a: v for _c, a, v in parameters(t)}
    best, score = None, -1
    for n in t.names():
        s = sum(1 for a, w in wanted.items() if a in params and _same(params[a].get(n), w))
        if s > score:
            best, score = n, s
    return best


def parameter_info(doc, sheet, alias):
    ""


    try:
        from . import cmflows
        h = cmflows.header_of(doc, sheet, alias) or alias
        p = cmflows.parse_header(doc, h) if h != alias and not h.startswith("$") else None
        k = cmflows.unit_k(p[1], p[2]) if p and p[0] == "value" else None
        return h, k, h.upper().startswith("$STATE@")
    except Exception as _fw_err:
        _fw_log("configmanager.py:pinfo", _fw_err)
        return alias, None, False


def _shown(text, k):
    if not k:
        return str(text)
    try:
        return "%g" % (float(str(text)) / k)
    except (TypeError, ValueError):
        return str(text)


def controls_for(state):
    ""
    return ["Checkbox", "List"] if state else ["List", "Number"]


def publisher_control(doc, t, alias, kind, values, current, changed=None):
    """(label, widget, read) for one published parameter: a List (the table's values), a Number (a box from the
    smallest to the largest value) or a Checkbox (Suppressed), each in the part's units; read() gives the
    table's own value for pick_configuration."""
    header, k, state = parameter_info(doc, t.sheet, alias)
    if kind not in controls_for(state):
        kind = controls_for(state)[0]
    if kind == "Checkbox":
        w = QtWidgets.QCheckBox("Suppressed")
        w.setChecked(str(current).strip() in ("1", "1.0"))
        if changed:
            w.toggled.connect(lambda *_a: changed())
        return header, w, lambda: "1" if w.isChecked() else "0"
    if kind == "Number":
        w = QtWidgets.QDoubleSpinBox()
        nums = []
        for v in values.values():
            try:
                nums.append(float(_shown(v, k)))
            except ValueError:
                pass
        lo, hi = (min(nums), max(nums)) if nums else (-1e9, 1e9)
        w.setRange(lo, hi if hi > lo else lo + 1e-9)
        try:
            from . import unitspage
            w.setDecimals(max(unitspage.length_decimals(doc), 0) if k else 3)
        except Exception:
            w.setDecimals(3)
        try:
            w.setValue(float(_shown(current, k)))
        except (TypeError, ValueError) as _fw_err:
            _fw_log("configmanager.py:number", _fw_err)
        if changed:
            w.editingFinished.connect(changed)
        return header, w, lambda: "%.12g" % (w.value() * (k or 1.0))
    w = QtWidgets.QComboBox()
    raw = {}
    for v in values.values():
        raw.setdefault(_shown(v, k), v)
    try:
        items = sorted(raw, key=lambda x: (0, float(x)))
    except ValueError:
        items = sorted(raw, key=str)
    w.addItems(items)
    if current is not None:
        w.setCurrentText(_shown(current, k))
    if changed:
        w.currentTextChanged.connect(lambda *_a: changed())
    return header, w, lambda: raw.get(w.currentText(), w.currentText())


class PublisherDialog(QtWidgets.QDialog):
    ""


    def __init__(self, doc, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.doc, self.t = doc, table(doc)
        self.setObjectName("SWConfigurationPublisher")
        self.setWindowTitle("Configuration Publisher")
        self.resize(620, 380)
        lay = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("Parameters"))
        self.list = QtWidgets.QTreeWidget()
        self.list.setObjectName("SWPublisherParameters")
        self.list.setHeaderLabels(["Parameter", "Control"])
        left.addWidget(self.list, 1)
        lay.addLayout(left, 1)
        right = QtWidgets.QVBoxLayout()
        right.addWidget(QtWidgets.QLabel("Preview"))
        self.preview = QtWidgets.QFormLayout()
        box = QtWidgets.QGroupBox()
        box.setLayout(self.preview)
        right.addWidget(box, 1)
        row = QtWidgets.QHBoxLayout()
        self.apply_btn = QtWidgets.QPushButton("Apply")
        self.apply_btn.clicked.connect(self.apply)
        row.addWidget(self.apply_btn)
        self.result = QtWidgets.QLabel("")
        self.result.setObjectName("SWPublisherResult")
        row.addWidget(self.result, 1)
        right.addLayout(row)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        right.addWidget(buttons)
        lay.addLayout(right, 1)
        chosen = dict(published(doc))
        self.controls = {}
        for _c, alias, values in (parameters(self.t) if self.t else []):
            header, _k, state = parameter_info(doc, self.t.sheet, alias)
            item = QtWidgets.QTreeWidgetItem([header, ""])
            item.setData(0, QtCore.Qt.UserRole, alias)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(0, QtCore.Qt.Checked if alias in chosen else QtCore.Qt.Unchecked)
            self.list.addTopLevelItem(item)
            kind = QtWidgets.QComboBox()
            kind.addItems(controls_for(state))
            kind.setCurrentText(chosen.get(alias, controls_for(state)[0]))
            self.list.setItemWidget(item, 1, kind)
            self.controls[alias] = (item, kind, values)
            kind.currentTextChanged.connect(lambda *_a: self.build())
        self.list.itemChanged.connect(lambda *_a: self.build())
        self.build()

    def chosen(self):
        return [(a, k.currentText()) for a, (item, k, _v) in self.controls.items()
                if item.checkState(0) == QtCore.Qt.Checked]

    def build(self):
        while self.preview.rowCount():
            self.preview.removeRow(0)
        self.inputs, self.reads = {}, {}
        for alias, kind in self.chosen():
            values = self.controls[alias][2]
            current = values.get(self.t.active()) if self.t else None
            label, w, read = publisher_control(self.doc, self.t, alias, kind, values, current)
            w.setObjectName("SWPublisherPreview_%s" % alias)
            self.inputs[alias], self.reads[alias] = w, read
            self.preview.addRow(label, w)

    def apply(self):
        if self.t is None:
            return None
        wanted = {a: read() for a, read in self.reads.items()}
        name = pick_configuration(self.t, wanted)
        if name:
            show(self.t, name)
            self.result.setText("Configuration: %s" % name)
        return name

    def accept(self):
        set_published(self.doc, self.chosen())
        super().accept()


_publisher = []


def configuration_publisher(doc):
    box = PublisherDialog(doc)
    _publisher[:] = [box]
    box.show()
    return box


# --------------------------------------------------------------------------- the page
_pages = []


def refresh_all():
    for page in list(_pages):
        if alive(page):
            page.later()
        else:
            _pages.remove(page)


TREE_ICONS = {"config": "CONFIGURATION_TAB", "table": "TABLES_DESIGN_TABLE"}


def _tree_icon(kind, active=True):
    ""

    try:
        if kind == "folder":
            icon = QtGui.QIcon(":/icons/folder.svg")
        else:
            icon = icons.family(TREE_ICONS[kind])
        if icon.isNull() or active:
            return icon
        grey = QtGui.QIcon()
        for size in (16, 20, 24, 32):
            grey.addPixmap(icon.pixmap(size, size, QtGui.QIcon.Disabled))
        return grey
    except Exception as _fw_err:
        _fw_log("configmanager.py:tree icon", _fw_err)
        return QtGui.QIcon()


class Page(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWConfigurationManager")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setObjectName("SWConfigurationTree")
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu_at)
        self.tree.itemDoubleClicked.connect(lambda item, col: self.activate(item))

        # Ctrl+V on the picked configuration delete, copy and paste it
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.SelectedClicked | QtWidgets.QAbstractItemView.EditKeyPressed)
        self.tree.setItemDelegate(_RenameDelegate(self))
        self.tree.installEventFilter(self)
        try:
            from . import displaystates
            self.display_states = displaystates.attach(self, lay, self.tree)
        except Exception as _fw_err:
            _fw_log("configmanager.py:displaystates", _fw_err)
            lay.addWidget(self.tree)
        _pages.append(self)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.refresh)
        self._observer = _Observer(self)
        App.addDocumentObserver(self._observer)
        self.destroyed.connect(lambda *a, o=self._observer: _forget(o))

    def later(self):
        if alive(self):
            self._timer.start()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        if not alive(self):
            return
        if self.tree.state() == QtWidgets.QAbstractItemView.EditingState:
            self.later()                # a name being typed: the tree is built again once it is in
            return
        self.tree.clear()
        doc = App.ActiveDocument
        if doc is None:
            return
        t = table(doc)
        active = t.active() if t else None
        root = QtWidgets.QTreeWidgetItem(["%s Configuration(s)  (%s)" % (part_name(doc), active or "Default")])
        root.setIcon(0, icons.family("PART"))
        root.setData(0, ROLE, ("part",))
        self.tree.addTopLevelItem(root)
        if t is not None:
            from . import cmflows
            if not cmflows.table_deleted(doc):      # Delete on the design table keeps the configurations
                folder = QtWidgets.QTreeWidgetItem(["Tables"])
                folder.setData(0, ROLE, ("tables",))
                folder.setIcon(0, _tree_icon("folder"))
                item = QtWidgets.QTreeWidgetItem([t.sheet.Label])
                item.setData(0, ROLE, ("table",))
                item.setIcon(0, _tree_icon("table"))
                folder.addChild(item)
                root.addChild(folder)
            made = {}
            names = cmflows.ordered(doc, t.names())          # Tree Order
            # parents before their derived configurations
            names = [n for n in names if not parent_of(doc, n) or parent_of(doc, n) not in names] + \
                [n for n in names if parent_of(doc, n) in names]
            for name in names:
                text = "%s [ %s ]" % (name, part_name(doc)) if name == active else name
                last = LAST_REBUILT.get(doc.Name, {}).get(name)
                if rebuild_mark(doc, name):
                    text += "  [rebuild/save mark]"
                if display_mark(doc, name):
                    text += "  [display data mark]"
                try:
                    from . import configs
                    desc = configs.properties(doc, name)["description"]
                    if desc:
                        text += "  (%s)" % desc
                except Exception as _fw_err:
                    _fw_log("configmanager.py:1036", _fw_err)
                item = QtWidgets.QTreeWidgetItem([text])
                item.setData(0, ROLE, ("config", name))
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                if last is not None:
                    item.setToolTip(0, "Rebuilt on save at %s: %s" % (last[2], "no errors" if last[0] else
                                                                    "rebuild errors in " + ", ".join(last[1][:6])))
                try:
                    note = extras(doc, name)["comment"]
                    if note:
                        item.setToolTip(0, (item.toolTip(0) + "\n" if item.toolTip(0) else "") + "Comment: " + note)
                except Exception as _fw_err:
                    _fw_log("configmanager.py:1047", _fw_err)

                # others; the names stay plain text (a grey name read as a disabled row)
                item.setIcon(0, _tree_icon("config", name == active))
                if name == active:
                    f = item.font(0)
                    f.setBold(True)
                    item.setFont(0, f)
                made[name] = item
                (made.get(parent_of(doc, name)) or root).addChild(item)
        else:
            # no table yet: the one configuration every part has
            item = QtWidgets.QTreeWidgetItem(["Default [ %s ]" % part_name(doc)])
            item.setData(0, ROLE, ("default",))
            item.setIcon(0, _tree_icon("config", True))
            f = item.font(0)
            f.setBold(True)
            item.setFont(0, f)
            root.addChild(item)
        self.tree.expandAll()

    def item_for(self, name):
        root = self.tree.topLevelItem(0)
        if root is None:
            return None
        todo = [root.child(i) for i in range(root.childCount())]
        while todo:
            c = todo.pop(0)
            d = c.data(0, ROLE) or ()
            if d[:1] == ("config",) and d[1] == name:
                return c
            todo += [c.child(i) for i in range(c.childCount())]
        return None

    def activate(self, item):
        d = (item.data(0, ROLE) if item is not None else None) or ("none",)
        doc = App.ActiveDocument
        t = table(doc)
        if d[0] == "config" and t is not None:
            return show(t, d[1])
        if d[0] == "table" and t is not None:
            return edit_table(t)
        return None

    def entries(self, item):
        """[(text, run, enabled)] for a row's right-click menu."""
        d = (item.data(0, ROLE) if item is not None else None) or ("none",)
        doc = App.ActiveDocument
        if doc is None:
            return []
        t = table(doc)
        out = []
        if d[0] == "config" and t is not None:
            name = d[1]
            out.append(("Show Configuration", lambda: show(t, name), name != t.active()))
            out.append(("Add Configuration...", lambda: add_configuration(doc), True))
            out.append(("Add Derived Configuration...", lambda: ask_derived(doc, name), True))
            mark = rebuild_mark(doc, name)
            out.append(("Remove Rebuild/Save Mark" if mark else "Add Rebuild/Save Mark",
                        lambda: set_rebuild_mark(doc, name, not mark), True))
            dmark = display_mark(doc, name)
            out.append(("Remove Display Data Mark" if dmark else "Add Display Data Mark",
                        lambda: set_display_mark(doc, name, not dmark), True))
            from . import cmflows

            out.append(("Edit Table...", lambda: edit_table(t), not cmflows.table_deleted(doc)))
            out.append(("Delete", lambda: delete(t, name), can_delete(t, name)))
            out.append(("Add Comment...", lambda: ask_comment(doc, name), True))
            out.append(("Properties...", lambda: configuration_properties(doc, name), True))
        elif d[0] in ("part", "default"):
            out.append(("Add Configuration...", lambda: add_configuration(doc), True))
            out.append(("Configuration Publisher...", lambda: configuration_publisher(doc), t is not None))
            if t is None:
                out.append(("Insert Design Table", lambda: (insert_table(doc, design=True), refresh_all()), True))
            else:
                out.append(("Edit Table...", lambda: edit_table(t), True))
            if d[0] == "default":

                out.append(("Properties...", lambda: default_properties(doc), True))
        elif d[0] in ("table", "tables") and t is not None:
            out.append(("Edit Table...", lambda: edit_table(t), True))
            from . import dtoptions
            out.append(("Edit Feature", lambda: dtoptions.edit(doc), True))
        from . import cmflows
        return cmflows.entries(self, doc, t, d, out)

    # ------------------------------------------------------------ rename, Delete, Ctrl+C / Ctrl+V in the tree
    def picked_name(self):
        item = self.tree.currentItem()
        d = (item.data(0, ROLE) if item is not None else None) or ("none",)
        return d[1] if d[0] == "config" else None

    def rename(self, old, new):
        ""
        new = (new or "").strip()
        doc = App.ActiveDocument
        t = table(doc) if doc is not None else None
        if t is None or not new or new == old:
            return False
        if new in t.names():
            QtWidgets.QMessageBox.warning(self, "Rename Configuration", "There is already a configuration named %s." % new)
            return False
        from . import configs
        configs.set_properties(doc, old, new_name=new)
        refresh_all()
        return new in table(doc).names()

    def _keys(self, event):
        """(what, run) for a key on the tree: Delete, Ctrl+C, Ctrl+V; None for any other."""
        doc = App.ActiveDocument
        t = table(doc) if doc is not None else None
        if t is None or self.tree.state() == QtWidgets.QAbstractItemView.EditingState:
            return None
        from . import cmflows
        name = self.picked_name()
        key, mods = event.key(), event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        if key == Qt.Key_Delete and not ctrl and name and can_delete(t, name):
            return lambda: delete(t, name)
        if ctrl and key == Qt.Key_C and name:
            return lambda: cmflows.copy(doc, name)
        if ctrl and key == Qt.Key_V and cmflows.can_paste(doc):
            return lambda: cmflows.paste(doc)
        return None

    def eventFilter(self, obj, event):
        try:
            if obj is self.tree and event.type() in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress):
                run = self._keys(event)
                if run is not None:
                    event.accept()      # the tree's own: not FreeCAD's Delete / Copy / Paste on the 3D view
                    if event.type() == QtCore.QEvent.KeyPress:
                        run()
                    return True
        except Exception as _fw_err:
            _fw_log("configmanager.py:keys", _fw_err)
        return super().eventFilter(obj, event)

    def _menu_at(self, pos):
        item = self.tree.itemAt(pos)
        entries = self.entries(item)
        if not entries:
            return
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("SWConfigurationMenu")
        for text, run, enabled in entries:
            if not enabled:
                continue        # does not apply to this row now: left out, not greyed (no dead entries)
            act = menu.addAction(text)
            act.triggered.connect(lambda checked=False, run=run: run())
        if not menu.actions():
            return
        menu.popup(self.tree.viewport().mapToGlobal(pos))


class _RenameDelegate(QtWidgets.QStyledItemDelegate):
    """The configuration's bare name to type over (not "Long [ Part1 ]  (description)"); Enter renames it."""

    def __init__(self, page):
        super().__init__(page.tree)
        self.page = page

    def setEditorData(self, editor, index):
        d = index.data(ROLE) or ()
        if d[:1] == ("config",) and isinstance(editor, QtWidgets.QLineEdit):
            editor.setText(d[1])
            editor.selectAll()
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        d = index.data(ROLE) or ()
        if d[:1] == ("config",) and isinstance(editor, QtWidgets.QLineEdit):
            old, new = d[1], editor.text()
            QtCore.QTimer.singleShot(0, lambda: self.page.rename(old, new))
            return                      # the tree is built again with the new name
        super().setModelData(editor, model, index)


class _Observer:
    def __init__(self, page):
        self.page = page

    def _poke(self):
        if alive(self.page):
            self.page.later()

    def slotChangedObject(self, obj, prop):
        if obj.TypeId == "Spreadsheet::Sheet" or prop == "Label":
            self._poke()

    def slotCreatedObject(self, obj):
        self._poke()

    def slotDeletedObject(self, obj):
        self._poke()

    def slotActivateDocument(self, doc):
        self._poke()

    def slotUndoDocument(self, doc):
        self._poke()

    def slotRedoDocument(self, doc):
        self._poke()


def _forget(observer):
    try:
        App.removeDocumentObserver(observer)
    except Exception as _fw_err:
        _fw_log("configmanager.py:1172", _fw_err)
