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

from . import customprops

CFG = "CfgProp:"
SUMMARY_META = ("Title", "Subject", "Keywords")


def configurations(doc):
    try:
        from . import configmanager
        t = configmanager.table(doc)
        if t is not None and t.names():
            return list(t.names())
    except Exception as _fw_err:
        _fw_log("fileprops.py:43", _fw_err)
    return ["Default"]


def active_configuration(doc):
    try:
        from . import configmanager
        t = configmanager.table(doc)
        if t is not None:
            return t.active()
    except Exception as _fw_err:
        _fw_log("fileprops.py:54", _fw_err)
    return "Default"


def read_config(doc, config):
    prefix = CFG + config + ":"
    rows = []
    for key, text in dict(doc.Meta or {}).items():
        if not key.startswith(prefix):
            continue
        parts = text.split("\t", 2)
        order, kind, value = (parts + ["", "", ""])[:3] if len(parts) == 3 else ("0", "Text", text)
        try:
            order = int(order)
        except ValueError:
            order = 0
        rows.append((order, key[len(prefix):], kind, value))
    return [(n, k, v) for _o, n, k, v in sorted(rows)]


def write_config(doc, config, rows):
    prefix = CFG + config + ":"
    meta = {k: v for k, v in dict(doc.Meta or {}).items() if not k.startswith(prefix)}
    for i, (name, kind, value) in enumerate(rows):
        if name.strip():
            meta[prefix + name.strip()] = "%d\t%s\t%s" % (i, kind, value)
    doc.Meta = meta
    try:
        Gui.getDocument(doc.Name).Modified = True
    except Exception as _fw_err:
        _fw_log("fileprops.py:84", _fw_err)


PRP_OLD = "FreeWorks:CfgPrp:"         # cmflows' store before features/181


def _config_scopes(config):
    from .customprops import UNIT_PREFIX
    return (CFG + config + ":", UNIT_PREFIX + config + ":", PRP_OLD + config + ":")


def config_renamed(doc, old, new):
    ""
    if doc is None or not old or not new or old == new:
        return
    meta = dict(doc.Meta or {})
    changed = False
    for a, b in zip(_config_scopes(old), _config_scopes(new)):
        for k in [k for k in meta if k.startswith(a)]:
            meta[b + k[len(a):]] = meta.pop(k)
            changed = True
    if changed:
        doc.Meta = meta


def config_deleted(doc, name):
    """fp96: a deleted configuration's own properties go with it."""
    if doc is None or not name:
        return
    meta = dict(doc.Meta or {})
    drop = [k for k in meta if any(k.startswith(s) for s in _config_scopes(name))]
    if drop:
        for k in drop:
            meta.pop(k)
        doc.Meta = meta


def copy_config(doc, src, dst):
    """fp96: a pasted configuration gets the source's own properties with their types (Number, Date,
    Yes or no...) and units, not only their text."""
    from . import customprops
    rows = list(read_config(doc, src))
    have = {r[0] for r in rows}
    meta = dict(doc.Meta or {})
    old = PRP_OLD + src + ":"
    rows += [(k[len(old):], "Text", v) for k, v in meta.items() if k.startswith(old) and k[len(old):] not in have]
    write_config(doc, dst, rows)
    customprops.write_units(doc, customprops.units(doc, src), dst)


def value(doc, name, config=None):
    ""
    config = config or active_configuration(doc)
    for n, kind, v in read_config(doc, config):
        if n == name:
            return customprops.evaluate(doc, kind, v, config)
    for n, kind, v in customprops.read(doc):
        if n == name:
            return customprops.evaluate(doc, kind, v, config)
    return None


def lookup(doc, name, config=None):
    ""

    if doc is None:
        return None
    names = configurations(doc)
    if config not in names:
        config = None
    config = config or active_configuration(doc)
    low = (name or "").lower()
    for rows, cfg in ((read_config(doc, config), config), (customprops.read(doc), config)):
        for n, kind, v in rows:
            if n.lower() == low:
                return customprops.evaluate(doc, kind, v, cfg)
    return None


def config_values(doc, config=None):
    """{name: evaluated value} of the configuration's own properties (config None: the active one)."""
    out = {}
    if doc is None:
        return out
    if config not in configurations(doc):
        config = None
    config = config or active_configuration(doc)
    for n, kind, v in read_config(doc, config):
        out[n] = str(customprops.evaluate(doc, kind, v, config))
    return out


def summary(doc):
    meta = dict(doc.Meta or {})
    out = {"Author": doc.CreatedBy, "Comments": doc.Comment, "Company": doc.Company,
           "Created": doc.CreationDate, "Last saved": doc.LastModifiedDate, "Last saved by": doc.LastModifiedBy}
    for k in SUMMARY_META:
        out[k] = meta.get("Summary:" + k, "")
    return out


def long_date(text):
    ""

    import datetime
    raw = str(text or "").strip()
    try:
        when = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if when.tzinfo is not None:
        when = when.astimezone()
    hour = when.hour % 12 or 12
    return "%s, %s %d, %d %d:%02d:%02d %s" % (when.strftime("%A"), when.strftime("%B"), when.day, when.year,
                                               hour, when.minute, when.second, "AM" if when.hour < 12 else "PM")


def set_summary(doc, **values):
    meta = dict(doc.Meta or {})
    for k, v in values.items():
        if k == "Author":
            doc.CreatedBy = v
        elif k == "Comments":
            doc.Comment = v
        elif k == "Company":
            doc.Company = v
        elif k in SUMMARY_META:
            meta["Summary:" + k] = v
    doc.Meta = meta


class ConfigEditor(customprops.Editor):
    """The Custom grid for one configuration's own properties."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWConfigProperties")
        self.config = "Default"
        self.pending = {}       # {configuration: (rows, units)} typed, not yet written (OK writes, Cancel drops)

    def keep(self):
        ""
        if self.doc is not None:
            self.pending[self.config] = (self.rows(), self.unit_map())

    def load(self, doc=None):
        self.doc = doc or App.ActiveDocument
        self._filling = True
        try:
            self.table.setRowCount(0)
            self.title.setText("Properties of configuration %s" % self.config)
            held = self.pending.get(self.config)
            have = held[1] if held else customprops.units(self.doc, self.config)
            for name, kind, v in (held[0] if held else read_config(self.doc, self.config)):
                self._add_row(name, kind, v, have.get(name, "") if kind == "Number" else "")
            self._add_row()
        finally:
            self._filling = False
        self._delete_shown()
        self._re_evaluate()

    def apply(self):
        if self.doc is None:
            return False
        self.keep()
        for config, (rows, units) in self.pending.items():
            write_config(self.doc, config, rows)
            customprops.write_units(self.doc, units, config)
        self.pending = {}
        self.load(self.doc)
        return True


class _ConfigList(QtWidgets.QListWidget):
    """The Configuration Properties tab's list of configurations (a drop-down's currentText / setCurrentText)."""

    def currentText(self):
        item = self.currentItem()
        return item.text() if item is not None else ""

    def setCurrentText(self, text):
        for r in range(self.count()):
            if self.item(r).text() == text:
                self.setCurrentRow(r)
                return
        if self.count() and self.currentRow() < 0:
            self.setCurrentRow(0)


class FilePropertiesDialog(QtWidgets.QDialog):
    def __init__(self, doc=None, parent=None, tab=0):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc or App.ActiveDocument
        self.setObjectName("SWFileProperties")
        self.setWindowTitle("Properties")
        self.resize(640, 440)
        lay = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("SWFilePropertiesTabs")
        lay.addWidget(self.tabs, 1)
        # Summary
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        s = summary(self.doc)
        self.fields = {}

        for k in ("Author", "Keywords", "Comments", "Title", "Subject"):
            w = QtWidgets.QPlainTextEdit(s[k]) if k == "Comments" else QtWidgets.QLineEdit(s[k])
            if k == "Comments":
                w.setFixedHeight(70)
            w.setObjectName("SWSummary" + k)
            self.fields[k] = w
            form.addRow(k + ":", w)
        saved = bool(getattr(self.doc, "FileName", ""))

        stats = QtWidgets.QGroupBox("Statistics")
        stats.setObjectName("SWSummaryStatistics")
        sform = QtWidgets.QFormLayout(stats)
        for k in ("Created", "Last saved", "Last saved by", "Last saved with"):
            if k == "Created":
                text = long_date(s[k])
            elif not saved:
                text = ""
            elif k == "Last saved with":
                text = "FreeCAD " + ".".join(App.Version()[:2])
            else:
                text = long_date(s[k]) if k == "Last saved" else str(s[k] or "")
            label = QtWidgets.QLabel(text)
            label.setObjectName("SWSummary" + k.replace(" ", ""))
            sform.addRow(k.title() + ":", label)
        form.addRow(stats)
        self.tabs.addTab(page, "Summary")
        # Custom
        self.custom = customprops.Editor()
        self.custom.load(self.doc)
        self.custom.apply_btn.hide()
        self.tabs.addTab(self.custom, "Custom")
        # Configuration Specific
        cfg = QtWidgets.QWidget()
        cl = QtWidgets.QVBoxLayout(cfg)

        split = QtWidgets.QHBoxLayout()
        self.applies = _ConfigList()
        self.applies.setObjectName("SWConfigList")
        self.applies.setMaximumWidth(150)
        self.applies.addItems(configurations(self.doc))
        self.applies.setCurrentText(active_configuration(self.doc))
        split.addWidget(self.applies)
        cl.addLayout(split, 1)
        self.config = ConfigEditor()
        self.config.apply_btn.hide()
        self.config.config = self.applies.currentText()
        self.config.load(self.doc)
        right = QtWidgets.QVBoxLayout()
        right.addWidget(self.config, 1)
        split.addLayout(right, 1)

        items = customprops.cut_list_items(self.doc)
        self.cut_list = QtWidgets.QTableWidget(0, 3)
        self.cut_list.setObjectName("SWConfigCutListProperties")
        self.cut_list.setHorizontalHeaderLabels(["Cut List Item", "Property Name", "Evaluated Value"])
        self.cut_list.horizontalHeader().setStretchLastSection(True)
        self.cut_list.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.cut_list.setToolTip("Link a property above to one of these: its Value drop-down has "
                                 "\"NAME@@@Cut-List-Item@part\" for each")
        if items:
            right.addWidget(QtWidgets.QLabel("Cut list properties:"))
            right.addWidget(self.cut_list, 1)
            self._fill_cut_list(items)
        else:
            self.cut_list.hide()
        self.applies.currentTextChanged.connect(self._config_changed)

        self.is_drawing = any(o.TypeId == "TechDraw::DrawPage" for o in getattr(self.doc, "Objects", []))
        if self.is_drawing:
            cfg.hide()
            tab = 1 if tab == 2 else (tab - 1 if tab > 2 else tab)
        else:
            self.tabs.addTab(cfg, "Configuration Specific")

        self.config.bom_label.show()
        self.config.bom_qty.show()
        self._sync_bom()
        self.custom.bom_qty.currentIndexChanged.connect(lambda *_: self._sync_bom(self.custom, self.config))
        self.config.bom_qty.currentIndexChanged.connect(lambda *_: self._sync_bom(self.config, self.custom))
        # Properties Summary: every property of the file, custom and per configuration, evaluated

        # Configuration Name | Type | Value / Text Expression | Evaluated Value on the right
        sumpage = QtWidgets.QWidget()
        sl = QtWidgets.QHBoxLayout(sumpage)
        self.summary_names = QtWidgets.QListWidget()
        self.summary_names.setObjectName("SWPropertiesSummaryNames")
        self.summary_names.setMaximumWidth(170)
        sl.addWidget(self.summary_names)
        self.summary_table = QtWidgets.QTableWidget(0, 4)
        self.summary_table.setObjectName("SWPropertiesSummary")
        self.summary_table.setHorizontalHeaderLabels(["Configuration Name", "Type", "Value / Text Expression",
                                                      "Evaluated Value"])
        self.summary_table.horizontalHeader().setStretchLastSection(True)
        self.summary_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        sl.addWidget(self.summary_table, 1)
        self._summary_all = []
        self.summary_names.currentTextChanged.connect(self._show_summary_name)
        self.tabs.addTab(sumpage, "Properties Summary")
        self.tabs.currentChanged.connect(lambda i: i == self.tabs.indexOf(sumpage) and self._fill_summary())
        self.tabs.setCurrentIndex(tab)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
                                             | QtWidgets.QDialogButtonBox.Help)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.helpRequested.connect(self._help)
        lay.addWidget(buttons)

    def _help(self):
        try:
            from . import helpmenu
            from . import helpguide
            if helpguide.show_topic("summary information") is None:
                helpmenu.show("home", search="summary information")
        except Exception as _fw_err:
            _fw_log("fileprops.py:help", _fw_err)

    def _fill_cut_list(self, items):
        from . import wecutlist
        rows = []
        for item in items:
            for n, k, v in wecutlist.item_properties(item):
                rows.append((item.Label, n, wecutlist.evaluated(item, v, k)))
        self.cut_list.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                self.cut_list.setItem(r, c, QtWidgets.QTableWidgetItem(str(text)))
        self.cut_list.resizeColumnsToContents()

    def _sync_bom(self, src=None, dst=None):
        """The BOM quantity drop-downs of Custom and Configuration Properties show the one part setting."""
        if src is None:
            src, dst = self.custom, self.config
            dst._fill_bom_qty()
        want = src.bom_qty.currentData() or ""
        i = dst.bom_qty.findData(want)
        if i < 0:
            dst.bom_qty.addItem(want, want)
            i = dst.bom_qty.count() - 1
        if dst.bom_qty.currentIndex() != i:
            dst.bom_qty.blockSignals(True)
            dst.bom_qty.setCurrentIndex(i)
            dst.bom_qty.blockSignals(False)

    def summary_full(self):
        """(name, configuration, type, value, evaluated) of every property, as the grids hold them now (typed,
        not yet kept by OK, included)."""
        out = []
        for name, kind, value in self.custom.rows():
            out.append((name, "Custom", kind, value, customprops.evaluate(self.doc, kind, value)))
        pending = getattr(self.config, "pending", {})
        for cfg in ([] if getattr(self, "is_drawing", False) else configurations(self.doc)):
            if cfg == self.config.config:
                rows = self.config.rows()
            elif cfg in pending:
                rows = pending[cfg][0]
            else:
                rows = read_config(self.doc, cfg)
            for name, kind, value in rows:
                out.append((name, cfg, kind, value, customprops.evaluate(self.doc, kind, value, cfg)))
        return out

    def summary_rows(self):
        """(name, configuration, value, evaluated) of every property (summary_full without the type)."""
        return [(n, c, v, e) for n, c, _k, v, e in self.summary_full()]

    def _fill_summary(self):
        rows = []
        try:
            rows = self.summary_full()
        except Exception as _fw_err:
            _fw_log("fileprops.py:summary", _fw_err)
        self._summary_all = rows
        keep = self.summary_names.currentItem().text() if self.summary_names.currentItem() else ""
        self.summary_names.blockSignals(True)
        self.summary_names.clear()
        names = []
        for row in rows:
            if row[0] not in names:
                names.append(row[0])
        self.summary_names.addItems(names)
        self.summary_names.blockSignals(False)
        if names:
            self.summary_names.setCurrentRow(names.index(keep) if keep in names else 0)
        self._show_summary_name(self.summary_names.currentItem().text() if self.summary_names.currentItem() else "")

    def _show_summary_name(self, name):
        rows = [r for r in self._summary_all if r[0] == name] if name else []
        t = self.summary_table
        t.setRowCount(len(rows))
        for r, (_n, cfg, kind, value, evaluated) in enumerate(rows):
            for c, text in enumerate((cfg, kind, value, evaluated)):
                t.setItem(r, c, QtWidgets.QTableWidgetItem(str(text)))
        t.resizeColumnsToContents()

    def _config_changed(self, name):
        self.config.keep()          # held until OK, so Cancel still keeps nothing
        self.config.config = name
        self.config.load(self.doc)

    def accept(self):
        vals = {k: (w.toPlainText() if isinstance(w, QtWidgets.QPlainTextEdit) else w.text())
                for k, w in self.fields.items()}
        set_summary(self.doc, **vals)
        self.custom.apply()
        if not getattr(self, "is_drawing", False):
            self.config.apply()
        super().accept()


_OPEN = []


def show(doc=None, tab=0):
    box = FilePropertiesDialog(doc, tab=tab)
    _OPEN[:] = [box]
    box.show()
    return box


class _Cmd:
    def GetResources(self):
        return {"MenuText": "Properties...", "ToolTip": "Summary, custom and per-configuration properties of the file"}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        show()


def register():
    if "SWStyle_FileProperties" not in Gui.listCommands():
        Gui.addCommand("SWStyle_FileProperties", _Cmd())
    try:
        from . import catalog
        cmd = catalog.BY_KEY.get("FileProperties")
        if cmd is not None and "SWStyle_FileProperties" not in cmd.natives:
            cmd.natives = ("SWStyle_FileProperties",) + tuple(cmd.natives)
    except Exception as _fw_err:
        _fw_log("fileprops.py:303", _fw_err)
