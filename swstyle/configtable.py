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

from . import configmanager as cm, configs

Qt = QtCore.Qt
NEW_ROW = "<Creates a new configuration.>"
MATERIAL = "Material"
VAR = "Var_"
META_VIEWS = "FreeWorks:TableViews"
ALL_PARAMETERS = "<All parameters>"
T_CONFIGURE = "Configure Feature"
T_CONFIGURE_DIM = "Configure Dimension"
T_CONFIGURE_EQ = "Configure Equation"
T_CONFIGURE_MAT = "Configure Material"


def _mw():
    return Gui.getMainWindow() if App.GuiUp else None


# --------------------------------------------------------------------------- columns
class Column:
    """One parameter: header text, table alias, kind ("suppress", "value", "text") and how its
    owner follows the table (bind)."""

    def __init__(self, header, alias, kind, current, bind, legacy=None, choices=None):
        self.header, self.alias, self.kind = header, alias, kind
        self.current, self.bind = current, bind
        self.legacy = legacy or []
        self.choices = choices


def _suppress_column(obj):
    return Column("Suppress", configs.SUPPRESS + configs._safe(obj.Name), "suppress",
                  lambda: "1" if getattr(obj, "Suppressed", False) else "0",
                  lambda sheet, alias: obj.setExpression("Suppressed", "%s.%s == 1" % (sheet.Name, alias)),
                  legacy=[("%s_Suppressed" % obj.Name)[:60]])


def _value_column(obj, prop, header=None):
    col = Column(header or prop, configs._alias_for(obj, prop), "value",
                 lambda: configs._number(configs._current(obj, prop)),
                 lambda sheet, alias: obj.setExpression(prop, "%s.%s" % (sheet.Name, alias)))
    try:
        col.length = obj.getTypeIdOfProperty(prop) in ("App::PropertyLength", "App::PropertyDistance")
    except Exception:
        col.length = False
    return col


def _length_unit(doc):
    ""

    try:
        from . import unitspage
        sym, k = unitspage.length_unit(doc)
        return sym, float(k) or 1.0
    except Exception:
        return "mm", 1.0


def _shown_length(value, k):
    try:
        v = float(value) / k
    except (TypeError, ValueError):
        return str(value)
    return ("%.8f" % v).rstrip("0").rstrip(".") if abs(v) < 1e15 else str(v)


def _typed_length(text, k):
    """mm from a length typed in the part's unit ('4' in an inch part is 101.6), or with its own unit ('4 mm')."""
    text = (text or "").strip()
    if not text:
        return text
    plain = text[1:].strip() if text.startswith("=") else text      # a cell's equation, "=2*1.5"
    plain = plain.replace(",", ".")                                   # a comma decimal, "1,5"
    try:
        return repr(float(plain) * k)
    except ValueError:
        pass
    try:
        q = App.Units.Quantity(plain)                  # "1/2", "2*1.5", "25.4 mm", "1 in + 2 mm"
        if q.Unit == App.Units.Quantity("1 mm").Unit:
            return repr(float(q.Value))
        if q.Unit == App.Units.Quantity("1").Unit:
            if text.startswith("="):
                return "=(%s)*%r" % (text[1:].strip(), k)      # the equation stays one, in the part's unit
            return repr(float(q.Value) * k)            # a bare number: in the part's unit
    except Exception:
        pass
    return text


def dimension_names(sk):
    ""
    out, n = [], 0
    for i, c in enumerate(sk.Constraints):
        if c.Type not in ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle"):
            continue
        if not getattr(c, "Driving", True):
            continue
        n += 1
        out.append((i, c.Name or "D%d" % n, c.Name or ""))
    return out


def _named(sk, index, wanted):
    ""

    c = sk.Constraints[index]
    if c.Name:
        return c.Name
    taken = {k.Name for k in sk.Constraints}
    name = wanted
    k = 1
    while name in taken:
        k += 1
        name = "%s_%d" % (wanted, k)
    sk.renameConstraint(index, name)
    return name


def _dimension_column(sk, index, sw_name):
    def current():
        return configs._number(sk.Constraints[index].Value)

    def bind(sheet, alias):
        name = _named(sk, index, sw_name)
        sk.setExpression("Constraints.%s" % name, "%s.%s" % (sheet.Name, alias))
    name = sk.Constraints[index].Name or sw_name
    col = Column("%s@%s" % (sw_name, sk.Label), configs._alias_for(sk, "Constraints." + name), "value", current, bind)
    col.angle = sk.Constraints[index].Type == "Angle"
    col.length = not col.angle
    return col


def _sketches_of(feature):
    out = []
    prof = getattr(feature, "Profile", None)
    prof = prof[0] if isinstance(prof, tuple) else prof
    for o in ([prof] if prof is not None else []) + list(getattr(feature, "Sections", []) or []) + \
            [getattr(feature, "Spine", (None,))[0] if isinstance(getattr(feature, "Spine", None), tuple) else None]:
        if o is not None and o.TypeId == "Sketcher::SketchObject" and o not in out:
            out.append(o)
    return out


_EXTRUDES = ("PartDesign::Pad", "PartDesign::Pocket")
_REVOLVES = ("PartDesign::Revolution", "PartDesign::Groove")


def _shown_value(feature, prop):
    ""

    t = feature.TypeId
    kind = str(getattr(feature, "Type", ""))
    if t in _EXTRUDES:
        first = kind in ("Length", "TwoLengths")
        second = kind == "TwoLengths" or (str(getattr(feature, "SideType", "")) == "Two sides"
                                          and str(getattr(feature, "Type2", "")) == "Length")
        if prop == "Length":
            return first
        if prop == "Length2":
            return second
        if prop in ("TaperAngle", "TaperAngle2"):
            on = abs(float(getattr(feature, prop).Value if hasattr(getattr(feature, prop), "Value")
                           else getattr(feature, prop))) > 1e-9
            return on and (first if prop == "TaperAngle" else second)
    if t in _REVOLVES:
        if prop == "Angle":
            return kind in ("Angle", "TwoAngles")
        if prop == "Angle2":
            return kind == "TwoAngles"
    return True


def feature_columns(feature):
    ""

    from . import partextras
    out, n = [], 0
    for p in partextras.feature_values(feature):
        if p == "Suppressed":
            out.append(_suppress_column(feature))
            continue
        if not _shown_value(feature, p):
            continue
        n += 1
        out.append(_value_column(feature, p, "D%d@%s" % (n, feature.Label)))
    for sk in _sketches_of(feature):
        for i, sw, _n in dimension_names(sk):
            out.append(_dimension_column(sk, i, sw))
    return out


def variable_column(doc, name):
    from . import equations

    def current():
        for n, raw, got in equations.variables(doc):
            if n == name:
                return configs._number(got if got is not None else raw)
        return 0.0

    def bind(sheet, alias):
        s = equations.sheet(doc)
        for r, n, _raw in equations._rows(s):
            if n == name:
                s.set("B%d" % r, "=%s.%s" % (sheet.Name, alias))
    return Column('"%s"' % name, VAR + configs._safe(name), "value", current, bind)


def material_column(doc):
    from . import material

    def current():
        return material.current(doc)[1] or ""
    return Column(MATERIAL, MATERIAL, "text", current, lambda sheet, alias: None,
                  choices=[""] + material_names())


def material_names():
    """Every material of the Material dialog (its libraries and Custom Materials), once each."""
    from . import material
    names = []
    try:
        from . import materialdlg
        names = [e["name"] for _lib, _cat, e in materialdlg.entries()]
    except Exception:
        names = [n for _f, n, _v in material.COMMON]
    seen = set()
    return [n for n in names if not (n in seen or seen.add(n))]


def material_density(name):
    """kg/m^3 of a material the Material dialog knows (custom ones too), else the common one's."""
    from . import material
    try:
        from . import materialdlg
        found = materialdlg.find(name)
        if found and found[2].get("values", {}).get("Density"):
            return float(found[2]["values"]["Density"])
    except Exception as _fw_err:
        _fw_log("configtable.py:226", _fw_err)
    return material.known_density(name) or material.DEFAULT_DENSITY


def apply_material(doc, name=None):
    """Show Configuration: the configuration's material (Configure Material) becomes the part's."""
    t = cm.table(doc)
    if t is None or configs.column_of(t, MATERIAL) is None:
        return None
    want = (configs.cell_value(t, MATERIAL, name) or "").strip()
    from . import material
    if want == (material.current(doc)[1] or ""):
        return want
    if want:
        material.assign(doc, want, material_density(want))
    else:
        material.assign(doc, "", 0.0)
    return want


# --------------------------------------------------------------------------- table views
def table_views(doc):
    try:
        return json.loads(dict(doc.Meta).get(META_VIEWS, "") or "{}")
    except Exception:
        return {}


def save_table_view(doc, name, shown):
    views = table_views(doc)
    views[name] = list(shown)
    meta = dict(doc.Meta)
    meta[META_VIEWS] = json.dumps(views)
    doc.Meta = meta
    return views


def delete_table_view(doc, name):
    views = table_views(doc)
    views.pop(name, None)
    meta = dict(doc.Meta)
    meta[META_VIEWS] = json.dumps(views)
    doc.Meta = meta
    return views


# --------------------------------------------------------------------------- the box
class ModifyConfigurations(QtWidgets.QDialog):
    def __init__(self, doc, columns, title="", parent=None):
        super().__init__(parent or _mw())
        self.setObjectName("SWConfigureFeature")
        self.setWindowTitle("Modify Configurations")
        self.doc, self.columns = doc, columns
        self.t = cm.table(doc)
        self.names = list(self.t.names()) if self.t is not None else ["Default"]
        lay = QtWidgets.QVBoxLayout(self)
        if title:
            lay.addWidget(QtWidgets.QLabel(title))
        self.grid = QtWidgets.QTableWidget(0, len(columns))
        self.grid.setObjectName("SWConfigureGrid")
        self.grid.setHorizontalHeaderLabels([c.header for c in columns])
        self.grid.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.horizontalHeader().customContextMenuRequested.connect(self._header_menu)
        self.grid.verticalHeader().sectionDoubleClicked.connect(self._name_row)
        for name in self.names:
            self._add_row(name, {c.alias: self._current(name, c) for c in columns})
        self._new_row()
        lay.addWidget(self.grid, 1)
        low = QtWidgets.QHBoxLayout()
        low.addWidget(QtWidgets.QLabel("Table view:"))
        self.view = QtWidgets.QComboBox()
        self.view.setObjectName("SWTableView")
        low.addWidget(self.view, 1)
        self.save_button = QtWidgets.QPushButton("Save Table View...")
        self.save_button.setObjectName("SWSaveTableView")
        self.save_button.clicked.connect(self._save_view)
        low.addWidget(self.save_button)
        self.delete_button = QtWidgets.QPushButton("Delete Table View")
        self.delete_button.clicked.connect(self._delete_view)
        low.addWidget(self.delete_button)
        lay.addLayout(low)
        self._fill_views()
        self.view.currentTextChanged.connect(self.use_view)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel |
                                        QtWidgets.QDialogButtonBox.Apply)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(self.apply)
        lay.addWidget(bb)
        self._fit()

    def _fit(self):
        ""

        g = self.grid
        try:
            g.resizeColumnsToContents()
            for c in range(g.columnCount()):
                g.setColumnWidth(c, max(g.columnWidth(c), 80))
            width = g.verticalHeader().width() + sum(g.columnWidth(c) for c in range(g.columnCount())) \
                + 2 * g.frameWidth() + g.verticalScrollBar().sizeHint().width()
            height = g.horizontalHeader().height() + sum(g.rowHeight(r) for r in range(g.rowCount())) + 2 * g.frameWidth()
            screen = (self.screen() or QtWidgets.QApplication.primaryScreen()).availableGeometry()
            extra_w = self.sizeHint().width() - g.sizeHint().width()
            extra_h = self.sizeHint().height() - g.sizeHint().height()
            self.resize(min(max(420, width + max(0, extra_w)), int(screen.width() * 0.9)),
                        min(max(240, height + max(0, extra_h)), int(screen.height() * 0.8)))
        except Exception as _fw_err:
            _fw_log("configtable.py:fit", _fw_err)
            self.resize(max(420, 110 * (len(self.columns) + 1)), 240)

    # ---- values
    def _current(self, cname, col):
        t = self.t
        if t is not None:
            for alias in [col.alias] + col.legacy:
                if configs.column_of(t, alias) is not None:
                    v = configs.cell_value(t, alias, cname)
                    if v not in (None, ""):
                        return v
        return col.current()

    def _cell(self, col, value, editable=True):
        cell = QtWidgets.QTableWidgetItem()
        if col.kind == "suppress":
            cell.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            cell.setCheckState(Qt.Checked if str(value).strip().lower() in ("1", "1.0", "true") else Qt.Unchecked)
        else:
            text = str(value)
            if getattr(col, "length", False):
                k = _length_unit(self.doc)[1]
                if k != 1.0:
                    text = _shown_length(value, k)
                    cell.setData(Qt.UserRole, (str(value), text))     # kept as it was unless typed over
            cell.setText(text)
            if not editable:
                cell.setFlags(Qt.NoItemFlags)
        return cell

    def _typed(self, col, item):
        """The cell's text for the table: a length typed in the part's unit goes in as mm."""
        text = item.text()
        if not getattr(col, "length", False):
            return text
        k = _length_unit(self.doc)[1]
        if k == 1.0:
            return text
        kept = item.data(Qt.UserRole)
        if kept and kept[1] == text:
            return kept[0]
        return _typed_length(text, k)

    def _add_row(self, name, values):
        r = self.grid.rowCount()
        self.grid.insertRow(r)
        self.grid.setVerticalHeaderItem(r, QtWidgets.QTableWidgetItem(name))
        for c, col in enumerate(self.columns):
            self.grid.setItem(r, c, self._cell(col, values.get(col.alias, "")))
            if col.choices is not None:
                box = QtWidgets.QComboBox()
                box.setEditable(True)
                box.addItems(col.choices)
                box.setCurrentText(str(values.get(col.alias, "")))
                box.currentTextChanged.connect(lambda text, item=self.grid.item(r, c): item.setText(text))
                self.grid.setCellWidget(r, c, box)

    def _new_row(self):
        r = self.grid.rowCount()
        self.grid.insertRow(r)
        self.grid.setVerticalHeaderItem(r, QtWidgets.QTableWidgetItem(NEW_ROW))
        for c, col in enumerate(self.columns):
            cell = QtWidgets.QTableWidgetItem()
            cell.setFlags(Qt.NoItemFlags)
            self.grid.setItem(r, c, cell)

    def name_row(self, name):
        """<Creates a new configuration.> gets a name: a row of its own with the values shown now."""
        name = (name or "").strip()
        if not name or name in self.names:
            return False
        self.grid.removeRow(self.grid.rowCount() - 1)
        self.names.append(name)
        self._add_row(name, {c.alias: c.current() for c in self.columns})
        self._new_row()
        return True

    def _name_row(self, r):
        if r != len(self.names):
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Modify Configurations", "Configuration name:")
        if ok:
            self.name_row(name)

    def value(self, cname, header):
        r, c = self.names.index(cname), [k.header for k in self.columns].index(header)
        item = self.grid.item(r, c)
        if self.columns[c].kind == "suppress":
            return item.checkState() == Qt.Checked
        return item.text()

    def set_value(self, cname, header, value):
        r, c = self.names.index(cname), [k.header for k in self.columns].index(header)
        item = self.grid.item(r, c)
        if self.columns[c].kind == "suppress":
            item.setCheckState(Qt.Checked if value else Qt.Unchecked)
        else:
            item.setText(str(value))
            w = self.grid.cellWidget(r, c)
            if w is not None:
                w.setCurrentText(str(value))

    # ---- table views
    def shown(self):
        return [c.header for i, c in enumerate(self.columns) if not self.grid.isColumnHidden(i)]

    def hide_column(self, header, on=True):
        i = [c.header for c in self.columns].index(header)
        self.grid.setColumnHidden(i, on)

    def show_all(self):
        for i in range(len(self.columns)):
            self.grid.setColumnHidden(i, False)

    def _header_menu(self, pos):
        i = self.grid.horizontalHeader().logicalIndexAt(pos)
        menu = QtWidgets.QMenu(self)
        if i >= 0:
            menu.addAction("Hide", lambda: self.grid.setColumnHidden(i, True))
        menu.addAction("Show All", self.show_all)
        menu.addSeparator()
        menu.addAction("Save Table View...", self._save_view)
        menu.exec_(self.grid.horizontalHeader().mapToGlobal(pos))

    def _fill_views(self, select=None):
        self.view.blockSignals(True)
        self.view.clear()
        self.view.addItem(ALL_PARAMETERS)
        for name in sorted(table_views(self.doc)):
            self.view.addItem(name)
        if select:
            self.view.setCurrentText(select)
        self.view.blockSignals(False)
        self._delete_shown()

    def _delete_shown(self):
        """Delete Table View only while a saved view is picked (it does nothing on All parameters)."""
        self.delete_button.setVisible(self.view.currentText() not in ("", ALL_PARAMETERS))

    def save_view(self, name):
        save_table_view(self.doc, name, self.shown())
        self._fill_views(name)
        return name

    def _save_view(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "Save Table View", "Table view name:")
        if ok and name.strip():
            self.save_view(name.strip())

    def _delete_view(self):
        name = self.view.currentText()
        if name and name != ALL_PARAMETERS:
            delete_table_view(self.doc, name)
            self._fill_views()
            self.show_all()

    def use_view(self, name):
        self._delete_shown()
        if name == ALL_PARAMETERS or not name:
            self.show_all()
            return
        keep = set(table_views(self.doc).get(name, []))
        for i, c in enumerate(self.columns):
            self.grid.setColumnHidden(i, c.header not in keep)

    # ---- write
    def apply(self):
        doc = self.doc
        if self.t is None:
            self.t = cm.insert_table(doc, self.names[0] if self.names else "Default")
        t = self.t
        active = t.active()
        for name in self.names:
            if name not in t.names():
                cm.add(t, name)                 # the new row's configuration, from the one shown
        if t.active() != active and active in t.names():
            cm.show(t, active)
        doc.openTransaction(T_CONFIGURE)
        changed = set()
        try:
            for c, col in enumerate(self.columns):
                configs.ensure_column(t, col.alias, col.current() if col.kind != "suppress" else col.current())
                for r, cname in enumerate(self.names):
                    row = t.row_of(cname)
                    if row is None:
                        continue
                    item = self.grid.item(r, c)
                    if col.kind == "suppress":
                        text = "1" if item.checkState() == Qt.Checked else "0"
                    elif col.kind == "text":
                        text = "'" + item.text() if item.text() else ""
                    else:
                        text = self._typed(col, item)
                    cell = "%s%d" % (configs.column_of(t, col.alias), row)
                    if str(t.sheet.getContents(cell)) != text:
                        changed.add(cname)
                    t.sheet.set(cell, text)
            doc.recompute()
            cm._bind(t)
            for col in self.columns:
                col.bind(t.sheet, col.alias)
            doc.recompute()
            _rebuild_kept(t, changed - {t.active()})
        finally:
            doc.commitTransaction()
        if any(c.alias == MATERIAL for c in self.columns):
            apply_material(doc)
        cm.refresh_all()
        return True

    def accept(self):
        self.apply()
        super().accept()


def _rebuild_kept(t, names):
    ""


    if not names:
        return
    from . import customprops
    doc, active = t.sheet.Document, t.active()
    try:
        for name in sorted(names):
            if name not in t.names():
                continue
            held = cm._suppress_first(t, name)
            setattr(t.sheet, t.prop, name)
            doc.recompute()
            for obj, expression in held:
                obj.setExpression("Suppressed", expression)
            doc.recompute()
            customprops.remember_mass(doc, name)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: configuration mass: %s\n" % error)
    finally:
        held = cm._suppress_first(t, active)
        setattr(t.sheet, t.prop, active)
        doc.recompute()
        for obj, expression in held:
            obj.setExpression("Suppressed", expression)
        doc.recompute()


def _run(box):
    try:
        from . import fmmenu
        fmmenu._run_dialog(box)            # OK applies (accept)
    except Exception:
        box.exec()
    return box


def configure_feature(feature, run=True):
    box = ModifyConfigurations(feature.Document, feature_columns(feature), feature.Label)
    return _run(box) if run else box


def configure_dimension(sketch, constraint, run=True):
    """Right-click a dimension > Configure Dimension: the box with that one dimension. constraint is
    the constraint's index or name."""
    if isinstance(constraint, str):
        constraint = next(i for i, c in enumerate(sketch.Constraints) if c.Name == constraint)
    sw = next((s for i, s, _n in dimension_names(sketch) if i == constraint), "D%d" % (constraint + 1))
    box = ModifyConfigurations(sketch.Document, [_dimension_column(sketch, constraint, sw)], sketch.Label)
    return _run(box) if run else box


def configure_equation(doc, name, run=True):
    """Equations: right-click a global variable > Configure Equation."""
    box = ModifyConfigurations(doc, [variable_column(doc, name)], "Global variable %s" % name)
    return _run(box) if run else box


def configure_material(doc, run=True):
    """The Material row's right-click > Configure Material."""
    box = ModifyConfigurations(doc, [material_column(doc)], "Material")
    return _run(box) if run else box


# --------------------------------------------------------------------------- hooks
def install():
    """Every Configure Feature route opens this box; Show Configuration applies the material;
    the Material row and the Equations box get their Configure items."""
    from . import partextras
    if getattr(partextras, "_fw_configtable", False):
        return
    partextras.configure_feature = configure_feature
    partextras.ConfigureFeature = lambda feature, parent=None: configure_feature(feature, run=False)
    partextras._fw_configtable = True
    # a configuration's kept mass properties and its Override Mass Properties go with it (delete, rename)
    cm.EXTRAS.setdefault("mass", "FreeWorks:CfgMass:")
    cm.EXTRAS.setdefault("mass_override", "SWMassOverride@")
    old_show = cm.show

    def show(t, name, *more, **named):
        from . import customprops
        try:
            customprops.remember_mass(t.sheet.Document)        # the configuration being left
        except Exception as error:
            App.Console.PrintLog("FreeCAD: configuration mass: %s\n" % error)
        ok = old_show(t, name, *more, **named)
        if ok:
            try:
                apply_material(t.sheet.Document, name)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: Configure Material: %s\n" % error)
            try:
                customprops.remember_mass(t.sheet.Document, name)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: configuration mass: %s\n" % error)
        return ok
    cm.show = show
    try:
        _patch_material_row()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Configure Material menu: %s\n" % error)
    try:
        _patch_equations()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Configure Equation menu: %s\n" % error)


def _patch_material_row():
    from . import fmmenu
    old = fmmenu.folder_entries

    def folder_entries(shell, folder, view=None, *more, **named):
        items = old(shell, folder, view, *more, **named)
        if getattr(folder, "kind", None) != "material":
            return items
        doc = getattr(folder, "doc", None) or App.ActiveDocument
        keys = [i[0] for i in items]
        new = ("ConfigureMaterial", T_CONFIGURE_MAT, lambda: configure_material(doc), doc is not None)
        at = keys.index("EditMaterial") + 1 if "EditMaterial" in keys else len(items)
        return items[:at] + [new] + items[at:]
    fmmenu.folder_entries = folder_entries


def _patch_equations():
    from . import equations
    dlg = getattr(equations, "EquationsDialog", None)
    if dlg is None or getattr(dlg, "_fw_configure", False):
        return
    old_menu = dlg._menu

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        kind = (item.data(0, Qt.UserRole) if item is not None else None) or ("none",)
        if kind[0] != "var":
            return old_menu(self, pos)
        name = kind[1]
        menu = QtWidgets.QMenu(self)
        menu.addAction(T_CONFIGURE_EQ, lambda: configure_equation(self.doc, name))
        menu.addAction("Delete", lambda: self.delete(item))
        menu.exec_(self.tree.viewport().mapToGlobal(pos))
    dlg._menu = _menu
    dlg._fw_configure = True
