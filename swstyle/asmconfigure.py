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
from PySide import QtCore, QtWidgets

from . import asmcore as ac
from . import configs
from . import configmanager as cm

NEW_ROW = "<Creates a new configuration.>"
CFG = "CompCfg_"
HIDE = "Hide_"
MATE_SUP = "MateSup_"
MATE_VAL = "MateVal_"
EXCLUDE = "Excl_"           # Component Properties > Exclude from bill of materials, per configuration
FLEX = "Flex_"              # Component Properties > Solve as Flexible, per configuration


def _alias(prefix, obj):
    return (prefix + configs._safe(obj.Name))[:60]


def has_value(joint):
    return ac.mate_type(joint) in ("Distance", "Angle")


def _mate_value(joint):
    from . import asmtimeline
    return asmtimeline.mate_value(joint)


def _set_mate_value(joint, v):
    from . import asmtimeline
    asmtimeline.set_mate_value(joint, v)


def _part_configs(comp):
    from . import asmmenu
    names, now = asmmenu.config_names(comp)
    return names or ["Default"], now or "Default"


def columns(items):
    """[(obj, kind, header)] for the items: kind suppress / config / hide / msup / mval."""
    out = []
    for obj in items:
        from . import asmmenu
        if asmmenu.is_mate(obj):
            out.append((obj, "msup", "Suppress"))
            if has_value(obj):
                out.append((obj, "mval", "Angle" if ac.mate_type(obj) == "Angle" else "Distance"))
        else:
            out += [(obj, "suppress", "Suppress"), (obj, "config", "Configuration"), (obj, "hide", "Hide")]
    return out


PREFIX = {"suppress": configs.COMP, "config": CFG, "hide": HIDE, "msup": MATE_SUP, "mval": MATE_VAL}


def now_value(obj, kind):
    """What the item is now (the value a new column starts with)."""
    from . import asmcomp, asmmenu
    if kind == "suppress":
        return "1" if asmcomp.is_suppressed(obj) else "0"
    if kind == "config":
        return _part_configs(obj)[1]
    if kind == "hide":
        return "0" if asmmenu.shown(obj) else "1"
    if kind == "msup":
        return "1" if asmmenu.suppressed(obj) else "0"
    return str(_mate_value(obj))


def stored(t, obj, kind, name):
    if t is None:
        return None
    return configs.cell_value(t, _alias(PREFIX[kind], obj), name)


def apply(doc):
    """The active configuration's configure values on the components and mates."""
    from . import asmcomp, asmmenu, asmreplacecomp
    asm = ac.assembly_of(doc)
    t = cm.table(doc)
    if asm is None or t is None:
        return 0
    n = 0
    solve = False
    for comp in ac.components(asm):
        v = configs.cell_value(t, _alias(CFG, comp))
        if v and v != _part_configs(comp)[1] and v in _part_configs(comp)[0]:
            from . import asmcfginst
            asmcfginst.set_configuration(comp, v, recompute=False)     # this instance only
            n += 1
            solve = True        # cfg130: its shape is rebuilt only by a recompute (it kept the other size)
        v = configs.cell_value(t, _alias(HIDE, comp))
        if v is not None and comp.ViewObject is not None:
            want = v.strip() not in ("1", "1.0")
            if bool(comp.ViewObject.Visibility) != want:
                comp.ViewObject.Visibility = want
                n += 1
        v = configs.cell_value(t, _alias(EXCLUDE, comp))
        if v is not None:
            from . import asminsert
            want = v.strip() in ("1", "1.0")
            if asminsert.is_excluded(comp) != want:
                asminsert.set_excluded(comp, want)
                n += 1
        v = configs.cell_value(t, _alias(FLEX, comp))
        if v is not None and ac.is_subassembly(comp):
            want = v.strip() in ("1", "1.0")
            if ac.is_flexible(comp) != want:
                try:
                    ac.set_flexible(asm, comp, want)
                    n += 1
                except Exception as _fw_err:
                    _fw_log("asmconfigure.py:flex", _fw_err)
    for j in ac.mates(asm):
        v = configs.cell_value(t, _alias(MATE_SUP, j))
        if v is not None:
            want = v.strip() in ("1", "1.0")
            if asmmenu.suppressed(j) != want:
                asmmenu.suppress(j, want)
                n += 1
        v = configs.cell_value(t, _alias(MATE_VAL, j))
        if v is not None and has_value(j):
            try:
                f = float(v)
            except ValueError:
                continue
            if abs(f - _mate_value(j)) > 1e-9:
                _set_mate_value(j, f)
                solve = True
                n += 1
    if solve:
        doc.recompute()
        ac.solve(asm)
    return n


def set_specific(comp, kind, value, scope="this"):
    ""



    from . import asminsert, asmcfginst
    doc = comp.Document
    t = cm.table(doc)
    now = {"config": lambda: asmcfginst.configuration(comp),
           "exclude": lambda: "1" if asminsert.is_excluded(comp) else "0",
           "flex": lambda: "1" if ac.is_flexible(comp) else "0"}[kind]
    want = str(value) if kind == "config" else ("1" if value else "0")
    if t is not None:
        alias = _alias({"config": CFG, "exclude": EXCLUDE, "flex": FLEX}[kind], comp)
        configs.ensure_column(t, alias, now())
        names = configs._scope(t, scope)
        configs.set_cell(t, alias, want, names)
        if t.active() not in names:
            return False
    if now() == want:
        return False
    if kind == "config":
        asmcfginst.set_configuration(comp, want)
    elif kind == "exclude":
        asminsert.set_excluded(comp, want == "1")
    else:
        ac.set_flexible(ac.assembly_of(doc), comp, want == "1")
    return True


def apply_hide(doc):
    """The Hide column of the active configuration (after its display state is put back: the
    table's Hide wins and is kept in that display state too). Returns how many changed."""
    asm = ac.assembly_of(doc)
    t = cm.table(doc)
    if asm is None or t is None:
        return 0
    n = 0
    for comp in ac.components(asm):
        v = configs.cell_value(t, _alias(HIDE, comp))
        if v is not None and comp.ViewObject is not None:
            want = v.strip() not in ("1", "1.0")
            if bool(comp.ViewObject.Visibility) != want:
                comp.ViewObject.Visibility = want
                n += 1
    return n


class ModifyConfigurations(QtWidgets.QDialog):
    ""

    def __init__(self, asm, items, parent=None, first_suppress_only=False):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("FW_AsmModifyConfigurations")
        self.setWindowTitle("Modify Configurations")
        self.asm, self.doc = asm, asm.Document
        self.t = cm.table(self.doc)
        self.cols = columns(items)
        self.names = list(self.t.names()) if self.t is not None else ["Default"]
        lay = QtWidgets.QVBoxLayout(self)
        self.grid = QtWidgets.QTableWidget(0, len(self.cols), self)
        self.grid.setObjectName("FW_AsmConfigureGrid")
        self.grid.setHorizontalHeaderLabels(["%s\n%s" % (o.Label, h) for o, _k, h in self.cols])
        for name in self.names:
            self._add_row(name)
        self._new_row()
        self.grid.verticalHeader().sectionDoubleClicked.connect(self._name_row)

        # column header's right-click, and a double-click on a component in the graphics area adds it
        self.first_suppress_only = first_suppress_only
        if first_suppress_only:
            for c, (_o, kind, _h) in enumerate(self.cols):
                if kind in ("config", "hide"):
                    self.grid.setColumnHidden(c, True)
            self._watch_graphics()
        hh = self.grid.horizontalHeader()
        hh.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        hh.customContextMenuRequested.connect(self._header_menu)
        lay.addWidget(self.grid)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(min(1200, 160 + 120 * max(1, len(self.cols))), 240)


    def shown_headers(self):
        """[(object label, header)] of the columns shown."""
        return [(o.Label, h) for c, (o, _k, h) in enumerate(self.cols) if not self.grid.isColumnHidden(c)]

    def show_column(self, obj, header, on=True):
        for c, (o, _k, h) in enumerate(self.cols):
            if o is obj and h == header:
                self.grid.setColumnHidden(c, not on)
                return True
        return False

    def column_menu(self, c):
        """The column header's right-click: the parameters of that column's item to show or hide, Show All."""
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("FW_AsmConfigureColumns")
        obj = self.cols[c][0] if 0 <= c < len(self.cols) else None
        for i, (o, _k, h) in enumerate(self.cols):
            if o is not obj:
                continue
            act = menu.addAction(h)
            act.setCheckable(True)
            act.setChecked(not self.grid.isColumnHidden(i))
            act.toggled.connect(lambda on, i=i: self.grid.setColumnHidden(i, not on))
        menu.addSeparator()
        menu.addAction("Show All", lambda: [self.grid.setColumnHidden(i, False) for i in range(len(self.cols))])
        return menu

    def _header_menu(self, pos):
        c = self.grid.horizontalHeader().logicalIndexAt(pos)
        self.column_menu(c).exec(self.grid.horizontalHeader().mapToGlobal(pos))

    def add_item(self, obj):
        """A component (or mate) joins the table: its columns, only Suppress shown for a component."""
        if obj is None or any(o is obj for o, _k, _h in self.cols):
            return False
        new = columns([obj])
        first = len(self.cols)
        self.cols += new
        self.grid.setColumnCount(len(self.cols))
        self.grid.setHorizontalHeaderLabels(["%s\n%s" % (o.Label, h) for o, _k, h in self.cols])
        for r, name in enumerate(self.names):
            for c in range(first, len(self.cols)):
                self._cell(r, c, name)
        last = len(self.names)
        for c in range(first, len(self.cols)):
            cell = QtWidgets.QTableWidgetItem()
            cell.setFlags(QtCore.Qt.NoItemFlags)
            self.grid.setItem(last, c, cell)
            if self.first_suppress_only and new[c - first][1] in ("config", "hide"):
                self.grid.setColumnHidden(c, True)
        return True

    def picked_component(self):
        """The component of what is selected in the graphics area (its top-level component)."""
        comps = ac.components(self.asm)
        by_name = {c.Name: c for c in comps}
        try:
            sels = Gui.Selection.getSelectionEx("", 0)
        except Exception:
            sels = Gui.Selection.getSelectionEx()
        for sel in sels:
            if sel.Object in comps:
                return sel.Object
            for sub in sel.SubElementNames or ():
                for part in sub.split("."):
                    if part in by_name:
                        return by_name[part]
        return None

    def _watch_graphics(self):
        try:
            view = Gui.getDocument(self.doc.Name).ActiveView
            gl = view.graphicsView().viewport() if hasattr(view, "graphicsView") else None
        except Exception:
            gl = None
        if gl is None:
            try:
                from PySide import QtOpenGLWidgets
                gl = next(iter(Gui.getMainWindow().findChildren(QtOpenGLWidgets.QOpenGLWidget)), None)
            except Exception:
                gl = None
        self._gl = gl
        if gl is not None:
            gl.installEventFilter(self)
            self.finished.connect(lambda *_: self._unwatch())

    def _unwatch(self):
        try:
            if getattr(self, "_gl", None) is not None:
                self._gl.removeEventFilter(self)
        except Exception as _fw_err:
            _fw_log("asmconfigure.py:295", _fw_err)
        self._gl = None

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.MouseButtonDblClick and self.isVisible():
            QtCore.QTimer.singleShot(150, lambda: self.add_item(self.picked_component()))
        return False

    def _cell(self, r, c, name):
        obj, kind, _h = self.cols[c]
        v = stored(self.t, obj, kind, name)
        if v is None:
            v = now_value(obj, kind)
        if kind in ("suppress", "hide", "msup"):
            cell = QtWidgets.QTableWidgetItem()
            cell.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
            cell.setCheckState(QtCore.Qt.Checked if str(v).strip() in ("1", "1.0") else QtCore.Qt.Unchecked)
            self.grid.setItem(r, c, cell)
        elif kind == "config":
            combo = QtWidgets.QComboBox(self.grid)
            combo.addItems(_part_configs(obj)[0])
            combo.setCurrentText(str(v))
            self.grid.setCellWidget(r, c, combo)
        else:
            cell = QtWidgets.QTableWidgetItem(str(v))
            self.grid.setItem(r, c, cell)

    def _add_row(self, name):
        r = self.grid.rowCount()
        self.grid.insertRow(r)
        self.grid.setVerticalHeaderItem(r, QtWidgets.QTableWidgetItem(name))
        for c in range(len(self.cols)):
            self._cell(r, c, name)

    def _new_row(self):
        r = self.grid.rowCount()
        self.grid.insertRow(r)
        self.grid.setVerticalHeaderItem(r, QtWidgets.QTableWidgetItem(NEW_ROW))
        for c in range(len(self.cols)):
            cell = QtWidgets.QTableWidgetItem()
            cell.setFlags(QtCore.Qt.NoItemFlags)
            self.grid.setItem(r, c, cell)

    def name_row(self, name):
        """The new-configuration row gets a name (values as the model is now)."""
        name = (name or "").strip()
        if not name or name in self.names:
            return False
        self.grid.removeRow(self.grid.rowCount() - 1)
        self.names.append(name)
        self._add_row(name)
        self._new_row()
        return True

    def _name_row(self, r):
        if r != len(self.names):
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Modify Configurations", "Configuration name:")
        if ok:
            self.name_row(name)

    def value(self, r, c):
        _o, kind, _h = self.cols[c]
        if kind in ("suppress", "hide", "msup"):
            return "1" if self.grid.item(r, c).checkState() == QtCore.Qt.Checked else "0"
        if kind == "config":
            return self.grid.cellWidget(r, c).currentText()
        return self.grid.item(r, c).text().strip()

    def set_value(self, name, obj, header, value):
        """For checks: the cell of obj's column header in configuration name."""
        r = self.names.index(name)
        for c, (o, kind, h) in enumerate(self.cols):
            if o is obj and h == header:
                if kind in ("suppress", "hide", "msup"):
                    self.grid.item(r, c).setCheckState(QtCore.Qt.Checked if value else QtCore.Qt.Unchecked)
                elif kind == "config":
                    self.grid.cellWidget(r, c).setCurrentText(str(value))
                else:
                    self.grid.item(r, c).setText(str(value))
                return True
        return False

    def _ok(self):
        if self.apply():
            self.accept()

    def apply(self):
        doc = self.doc
        doc.openTransaction("Modify Configurations")
        try:
            t = self.t = configs.table(doc)
            active = t.active()
            for name in self.names:
                if name not in t.names():
                    cm.add(t, name)
            if t.active() != active and active in t.names():
                cm.show(t, active)
            for c, (obj, kind, _h) in enumerate(self.cols):
                alias = _alias(PREFIX[kind], obj)
                if self.grid.isColumnHidden(c) and configs.column_of(t, alias) is None:
                    continue
                configs.ensure_column(t, alias, now_value(obj, kind))
                for r, name in enumerate(self.names):
                    configs.set_cell(t, alias, self.value(r, c), [name])
            if kind_has_comp(self.cols):
                configs.apply_assembly(doc)
            else:
                apply(doc)
        finally:
            doc.commitTransaction()
        cm.refresh_all()
        return True


def kind_has_comp(cols):
    return any(k == "suppress" for _o, k, _h in cols)


def _asm_of(obj):
    from . import asmmenu
    try:
        return asmmenu.assembly_of(obj)
    except Exception:
        return ac.assembly_of(obj.Document)


def configure_component(comp):
    asm = _asm_of(comp)
    if asm is None:
        return None
    box = ModifyConfigurations(asm, [comp], first_suppress_only=True)
    box.show()
    return box


def configure_mate(joint):
    asm = _asm_of(joint)
    if asm is None:
        return None
    box = ModifyConfigurations(asm, [joint])
    box.show()
    return box


def configuration_table(doc):
    asm = ac.assembly_of(doc)
    if asm is None:
        return None
    joints = ac.mates(asm)
    box = ModifyConfigurations(asm, ac.components(asm) + list(joints))
    box.setWindowTitle("Configuration Table")
    box.show()
    return box


def install():
    """Show Configuration applies these too; the menus get the entries."""
    if getattr(configs, "_fw_asmconfigure", False):
        return
    configs._fw_asmconfigure = True
    old = configs.apply_assembly

    def apply_assembly(doc):
        n = old(doc)
        try:
            n += apply(doc)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Modify Configurations: %s\n" % error)
        return n
    configs.apply_assembly = apply_assembly
    old_entries = cm.Page.entries

    def entries(self, item):
        out = old_entries(self, item)
        doc = App.ActiveDocument
        d = (item.data(0, cm.ROLE) if item is not None else None) or ("none",)
        if doc is not None and ac.assembly_of(doc) is not None and d[0] in ("part", "default", "tables", "table"):
            out.append(("Configuration Table...", lambda: configuration_table(doc), True))
        return out
    cm.Page.entries = entries
