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
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt
PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/PropertyTabBuilder"
EXT = {"Part": "prtprp", "Assembly": "asmprp", "Drawing": "drwprp"}
KINDS = ("Part", "Assembly", "Drawing")
CONTROLS = (("group", "Group Box"), ("text", "Textbox"), ("list", "List"), ("number", "Number"),
            ("checkbox", "Checkbox"), ("radio", "Radio Buttons"), ("date", "Date"))
LABEL = dict(CONTROLS)
PROPERTY_KIND = {"text": "Text", "list": "Text", "number": "Number", "checkbox": "Yes or no",
                 "radio": "Text", "date": "Date"}
BLANK_DATE = QtCore.QDate(1900, 1, 1)


# --------------------------------------------------------------------------- templates on disk
def folder():
    got = App.ParamGet(PARAMS).GetString("Folder", "")
    if not got:
        got = os.path.join(App.getUserAppDataDir(), "FreeWorks", "PropertyTabs")
    return got


def set_folder(path):
    App.ParamGet(PARAMS).SetString("Folder", path or "")


def kind_of(doc):
    try:
        from . import saveas
        return saveas.kind_of(doc)
    except Exception:
        return "Part"


def template_path(kind, create=False):
    """The template the tab uses for a document type: template.<ext>, else the first <ext> file."""
    d = folder()
    ext = EXT.get(kind, "prtprp")
    main = os.path.join(d, "template." + ext)
    if os.path.isfile(main) or create:
        return main
    try:
        for name in sorted(os.listdir(d)):
            if name.lower().endswith("." + ext):
                return os.path.join(d, name)
    except OSError as _fw_err:
        _fw_log("proptabbuilder.py:90", _fw_err)
    return None


def empty(kind="Part"):
    return {"version": 1, "kind": kind, "message": "", "configs": True,
            "groups": [{"caption": "Group Box", "expanded": True, "controls": []}]}


def load_file(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("groups", [])
    data.setdefault("message", "")
    data.setdefault("configs", True)
    for g in data["groups"]:
        g.setdefault("controls", [])
        g.setdefault("expanded", True)
    return data


def save_file(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    return path


def template_for(doc):
    path = template_path(kind_of(doc))
    if not path:
        return None
    try:
        return load_file(path)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Property Tab template %s: %s\n" % (path, error))
        return None


# --------------------------------------------------------------------------- one control's widget
def make_widget(c, value):
    t = c.get("type", "text")
    if t == "list":
        w = QtWidgets.QComboBox()
        w.setEditable(not c.get("readonly"))
        w.addItems([str(i) for i in c.get("items", [])])
        if value and w.findText(value) < 0:
            w.addItem(value)
        w.setCurrentText(value or "")
    elif t == "number":
        w = QtWidgets.QDoubleSpinBox()
        w.setDecimals(int(c.get("decimals", 2)))
        w.setRange(float(c.get("min", -1e9)), float(c.get("max", 1e9)))
        w.setSingleStep(float(c.get("step", 1)))
        try:
            w.setValue(float(value))
        except (TypeError, ValueError) as _fw_err:
            _fw_log("proptabbuilder.py:147", _fw_err)
    elif t == "checkbox":
        w = QtWidgets.QCheckBox(c.get("caption", ""))
        w.setChecked(str(value).strip().lower() in ("yes", "true", "1"))
    elif t == "radio":
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        w.buttons = []
        group = QtWidgets.QButtonGroup(w)
        for item in c.get("items", []):
            b = QtWidgets.QRadioButton(str(item))
            b.setChecked(str(item) == value)
            group.addButton(b)
            lay.addWidget(b)
            w.buttons.append(b)
        w.group = group
    elif t == "date":
        w = QtWidgets.QDateEdit()
        w.setCalendarPopup(True)
        w.setDisplayFormat("dd/MM/yyyy")
        w.setMinimumDate(BLANK_DATE)
        w.setSpecialValueText(" ")
        got = QtCore.QDate.fromString(value, "yyyy-MM-dd") if value else BLANK_DATE
        w.setDate(got if got.isValid() else BLANK_DATE)
    else:
        w = QtWidgets.QLineEdit(value or "")
    if c.get("readonly") and hasattr(w, "setReadOnly"):
        w.setReadOnly(True)
    elif c.get("readonly"):
        w.setEnabled(False)
    w.setProperty("sw_ptb", t)
    w.setProperty("sw_kind", c.get("kind") or PROPERTY_KIND.get(t, "Text"))
    w.setProperty("sw_config", bool(c.get("config")))
    return w


def value_of(w):
    t = w.property("sw_ptb")
    if t == "list":
        return w.currentText()
    if t == "number":
        v = w.value()
        return ("%d" % v) if float(v).is_integer() else repr(round(v, w.decimals()))
    if t == "checkbox":
        return "Yes" if w.isChecked() else "No"
    if t == "radio":
        return next((b.text() for b in w.buttons if b.isChecked()), "")
    if t == "date":
        return "" if w.date() == BLANK_DATE else w.date().toString("yyyy-MM-dd")
    return w.text()


# --------------------------------------------------------------------------- the Task Pane tab drawn from it
def render_into(tab):
    """customprops.PropertyTab._fill from the document type's template. False: no template."""
    doc = tab.doc
    data = template_for(doc) if doc is not None else None
    tab._ptb = data
    if not data:
        return False
    from . import customprops, fileprops
    page = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(page)
    lay.setContentsMargins(2, 2, 2, 2)
    tab.fields = {}
    tab.title.setText("Custom Properties of %s" % doc.Label)
    if data.get("message"):
        m = QtWidgets.QLabel(data["message"])
        m.setWordWrap(True)
        m.setObjectName("SWPropertyTabMessage")
        lay.addWidget(m)
    tab.specific.setVisible(False)          # each control says itself where its value goes
    tab.config.setVisible(bool(data.get("configs", True)))
    tab.config.setEnabled(True)
    config = tab.config.currentText() or fileprops.active_configuration(doc)
    custom = {n: (k, v) for n, k, v in customprops.read(doc)}
    per_cfg = {n: (k, v) for n, k, v in fileprops.read_config(doc, config)} if config else {}
    for g in data.get("groups", []):
        box = QtWidgets.QGroupBox(g.get("caption", ""))
        box.setObjectName("SWPropertyTabGroup_" + (g.get("caption") or "Group"))
        box.setCheckable(True)                  # the caption's tick folds the group, as the arrow does
        box.setChecked(bool(g.get("expanded", True)))
        inner = QtWidgets.QWidget(box)
        form = QtWidgets.QFormLayout(inner)
        outer = QtWidgets.QVBoxLayout(box)
        outer.addWidget(inner)
        box.toggled.connect(inner.setVisible)
        inner.setVisible(box.isChecked())
        for c in g.get("controls", []):
            name = (c.get("property") or c.get("caption") or "").strip()
            if not name:
                continue
            have = (per_cfg if c.get("config") else custom).get(name)
            value = have[1] if have else str(c.get("default", ""))
            if value.startswith("$PRP"):
                kind = have[0] if have else "Text"
                w = QtWidgets.QLineEdit(customprops.evaluate(doc, kind, value, config if c.get("config") else None))
                w.setReadOnly(True)
                w.setProperty("sw_link", value)
                w.setProperty("sw_ptb", "text")
                w.setProperty("sw_kind", kind)
                w.setProperty("sw_config", bool(c.get("config")))
            else:
                w = make_widget(c, value)
            w.setObjectName("SWPropertyTab_" + name)
            w.setProperty("sw_required", bool(c.get("required")))
            caption = c.get("caption") or name
            if c.get("type") == "checkbox":
                form.addRow(w)
            else:
                label = QtWidgets.QLabel(caption + (" *" if c.get("required") else "") + ":")
                if c.get("required"):
                    label.setStyleSheet("QLabel { color: #b00000; }")
                form.addRow(label, w)
            tab.fields[name] = w
        lay.addWidget(box)
    lay.addStretch(1)
    tab.area.setWidget(page)
    return True


def apply_tab(tab):
    """Apply on a template-drawn tab: each value to the custom properties, or the configuration's."""
    from . import customprops, fileprops
    doc = tab.doc
    missing = [n for n, w in tab.fields.items() if w.property("sw_required") and not w.property("sw_link")
               and not value_of(w).strip()]
    if missing:
        QtWidgets.QMessageBox.warning(tab, "Custom Properties",
                                      "These properties are required: %s" % ", ".join(missing))
        return False
    config = tab.config.currentText() or fileprops.active_configuration(doc)
    to_custom, to_cfg = {}, {}
    for name, w in tab.fields.items():
        kind = w.property("sw_kind") or "Text"
        value = w.property("sw_link") or value_of(w)
        (to_cfg if w.property("sw_config") else to_custom)[name] = (kind, value)

    def merged(old, new):
        rows = []
        for n, k, v in old:
            if n in new:
                k, v = new.pop(n)
                if not str(v).strip():
                    continue        # emptied on the tab: it goes
            rows.append((n, k, v))
        rows += [(n, k, v) for n, (k, v) in new.items() if str(v).strip()]
        return rows
    customprops.write(doc, merged(customprops.read(doc), to_custom))
    if to_cfg and config:
        fileprops.write_config(doc, config, merged(fileprops.read_config(doc, config), to_cfg))
    tab._fill()
    return True


# --------------------------------------------------------------------------- the builder
class BuilderDialog(QtWidgets.QDialog):
    def __init__(self, kind=None, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWPropertyTabBuilder")
        self.setWindowTitle("Property Tab Builder")
        self.resize(980, 620)
        self.path = None
        self._loading = False
        lay = QtWidgets.QVBoxLayout(self)
        bar = QtWidgets.QHBoxLayout()
        self.kind = QtWidgets.QComboBox()
        self.kind.setObjectName("SWPTBKind")
        self.kind.addItems(KINDS)
        bar.addWidget(QtWidgets.QLabel("Document type:"))
        bar.addWidget(self.kind)
        for name, text, fn in (("New", "New", self.new), ("Open", "Open...", self.open_dialog),
                               ("Save", "Save", self.save), ("SaveAs", "Save As...", self.save_as)):
            b = QtWidgets.QPushButton(text)
            b.setObjectName("SWPTB" + name)
            b.clicked.connect(lambda _c=False, f=fn: f())
            bar.addWidget(b)
        bar.addStretch(1)
        self.where = QtWidgets.QLabel("")
        self.where.setObjectName("SWPTBPath")
        bar.addWidget(self.where)
        lay.addLayout(bar)
        split = QtWidgets.QHBoxLayout()
        # left: the controls
        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("Control"))
        self.palette = QtWidgets.QListWidget()
        self.palette.setObjectName("SWPTBControls")
        self.palette.setFixedWidth(150)
        for key, text in CONTROLS:
            it = QtWidgets.QListWidgetItem(text)
            it.setData(Qt.UserRole, key)
            self.palette.addItem(it)
        self.palette.itemDoubleClicked.connect(lambda it: self.add(it.data(Qt.UserRole)))
        left.addWidget(self.palette)
        add = QtWidgets.QPushButton("Add")
        add.setObjectName("SWPTBAdd")
        add.clicked.connect(lambda: self.palette.currentItem() and self.add(self.palette.currentItem().data(Qt.UserRole)))
        left.addWidget(add)
        split.addLayout(left)
        # middle: the tab
        mid = QtWidgets.QVBoxLayout()
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Message:"))
        self.message = QtWidgets.QLineEdit()
        self.message.setObjectName("SWPTBMessage")
        self.message.textChanged.connect(self._tab_changed)
        row.addWidget(self.message, 1)
        mid.addLayout(row)
        self.configs = QtWidgets.QCheckBox("Show the configuration selector")
        self.configs.setObjectName("SWPTBConfigs")
        self.configs.toggled.connect(self._tab_changed)
        mid.addWidget(self.configs)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setObjectName("SWPTBTab")
        self.tree.setHeaderLabels(["Tab", "Property"])
        self.tree.currentItemChanged.connect(lambda *a: self._pick())
        mid.addWidget(self.tree, 1)
        moves = QtWidgets.QHBoxLayout()
        for name, text, fn in (("Up", "Move Up", lambda: self.move(-1)), ("Down", "Move Down", lambda: self.move(1)),
                               ("Delete", "Delete", self.delete)):
            b = QtWidgets.QPushButton(text)
            b.setObjectName("SWPTB" + name)
            b.clicked.connect(lambda _c=False, f=fn: f())
            moves.addWidget(b)
        moves.addStretch(1)
        mid.addLayout(moves)
        split.addLayout(mid, 1)
        # right: attributes
        self.attrs = QtWidgets.QGroupBox("Attributes")
        self.attrs.setObjectName("SWPTBAttributes")
        self.attrs.setFixedWidth(300)
        form = QtWidgets.QFormLayout(self.attrs)
        self.a_caption = QtWidgets.QLineEdit()
        self.a_property = QtWidgets.QComboBox()
        self.a_property.setEditable(True)
        try:
            from . import customprops
            self.a_property.addItems(list(customprops.name_list()))
        except Exception as _fw_err:
            _fw_log("proptabbuilder.py:388", _fw_err)
        self.a_kind = QtWidgets.QComboBox()
        self.a_kind.addItems(("Text", "Date", "Number", "Yes or no"))
        self.a_default = QtWidgets.QLineEdit()
        self.a_items = QtWidgets.QPlainTextEdit()
        self.a_items.setFixedHeight(80)
        self.a_min = QtWidgets.QDoubleSpinBox()
        self.a_max = QtWidgets.QDoubleSpinBox()
        self.a_step = QtWidgets.QDoubleSpinBox()
        for s in (self.a_min, self.a_max, self.a_step):
            s.setRange(-1e9, 1e9)
            s.setDecimals(3)
        self.a_readonly = QtWidgets.QCheckBox("Read only")
        self.a_required = QtWidgets.QCheckBox("Required")
        self.a_config = QtWidgets.QCheckBox("Configuration specific")
        self.a_expanded = QtWidgets.QCheckBox("Expanded")
        for name, w in (("Caption", self.a_caption), ("Property", self.a_property), ("Type", self.a_kind),
                        ("Default", self.a_default), ("Items", self.a_items), ("Min", self.a_min),
                        ("Max", self.a_max), ("Step", self.a_step), ("ReadOnly", self.a_readonly),
                        ("Required", self.a_required), ("Config", self.a_config), ("Expanded", self.a_expanded)):
            w.setObjectName("SWPTBAttr" + name)
        form.addRow("Caption:", self.a_caption)
        form.addRow("Custom Property Name:", self.a_property)
        form.addRow("Type:", self.a_kind)
        form.addRow("Value:", self.a_default)
        form.addRow("Items (one per line):", self.a_items)
        form.addRow("Minimum:", self.a_min)
        form.addRow("Maximum:", self.a_max)
        form.addRow("Increment:", self.a_step)
        form.addRow(self.a_readonly)
        form.addRow(self.a_required)
        form.addRow(self.a_config)
        form.addRow(self.a_expanded)
        for w in (self.a_caption, self.a_default):
            w.textChanged.connect(self._attr_changed)
        self.a_property.currentTextChanged.connect(self._attr_changed)
        self.a_kind.currentTextChanged.connect(self._attr_changed)
        self.a_items.textChanged.connect(self._attr_changed)
        for s in (self.a_min, self.a_max, self.a_step):
            s.valueChanged.connect(self._attr_changed)
        for b in (self.a_readonly, self.a_required, self.a_config, self.a_expanded):
            b.toggled.connect(self._attr_changed)
        split.addWidget(self.attrs)
        lay.addLayout(split, 1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.kind.currentTextChanged.connect(self._kind_changed)
        kind = kind or kind_of(App.ActiveDocument)
        self.kind.setCurrentText(kind)
        self._kind_changed(kind)

    # ---- template in the dialog
    def _kind_changed(self, kind):
        path = template_path(kind)
        try:
            self.data = load_file(path) if path else empty(kind)
        except Exception:
            self.data = empty(kind)
        self.path = path
        self.data["kind"] = kind
        self._show_data()

    def _show_data(self, pick=None):
        self._loading = True
        self.message.setText(self.data.get("message", ""))
        self.configs.setChecked(bool(self.data.get("configs", True)))
        self.tree.clear()
        target = None
        for gi, g in enumerate(self.data["groups"]):
            gitem = QtWidgets.QTreeWidgetItem([g.get("caption", ""), ""])
            gitem.setData(0, Qt.UserRole, (gi, None))
            self.tree.addTopLevelItem(gitem)
            if pick == (gi, None):
                target = gitem
            for ci, c in enumerate(g["controls"]):
                citem = QtWidgets.QTreeWidgetItem(["%s: %s" % (LABEL.get(c.get("type"), "?"), c.get("caption", "")),
                                                   c.get("property", "")])
                citem.setData(0, Qt.UserRole, (gi, ci))
                gitem.addChild(citem)
                if pick == (gi, ci):
                    target = citem
            gitem.setExpanded(True)
        self.where.setText(self.path or "(not saved yet)")
        self._loading = False
        if target is not None:
            self.tree.setCurrentItem(target)
        self._pick()

    def _at(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it is not None else None

    def _item(self, at=None):
        at = at or self._at()
        if at is None:
            return None
        gi, ci = at
        g = self.data["groups"][gi]
        return g if ci is None else g["controls"][ci]

    def _pick(self):
        at = self._at()
        item = self._item(at)
        # nothing picked: the Attributes box steps aside (never a greyed box)
        self.attrs.setVisible(item is not None)
        if item is None:
            return
        control = at[1] is not None
        self._loading = True
        self.a_caption.setText(item.get("caption", ""))
        self.a_property.setCurrentText(item.get("property", ""))
        self.a_kind.setCurrentText(item.get("kind") or PROPERTY_KIND.get(item.get("type"), "Text"))
        self.a_default.setText(str(item.get("default", "")))
        self.a_items.setPlainText("\n".join(str(i) for i in item.get("items", [])))
        self.a_min.setValue(float(item.get("min", 0)))
        self.a_max.setValue(float(item.get("max", 1000)))
        self.a_step.setValue(float(item.get("step", 1)))
        self.a_readonly.setChecked(bool(item.get("readonly")))
        self.a_required.setChecked(bool(item.get("required")))
        self.a_config.setChecked(bool(item.get("config")))
        self.a_expanded.setChecked(bool(item.get("expanded", True)))
        t = item.get("type") if control else "group"
        for w, show in ((self.a_property, control), (self.a_kind, control), (self.a_default, control),
                        (self.a_items, t in ("list", "radio")), (self.a_min, t == "number"),
                        (self.a_max, t == "number"), (self.a_step, t == "number"), (self.a_readonly, control),
                        (self.a_required, control), (self.a_config, control), (self.a_expanded, not control)):
            w.setVisible(show)
            label = self.attrs.layout().labelForField(w)
            if label is not None:
                label.setVisible(show)
        self._loading = False

    def _attr_changed(self, *args):
        if self._loading:
            return
        at = self._at()
        item = self._item(at)
        if item is None:
            return
        item["caption"] = self.a_caption.text()
        if at[1] is None:
            item["expanded"] = self.a_expanded.isChecked()
            self.tree.currentItem().setText(0, item["caption"])
            return
        item["property"] = self.a_property.currentText().strip()
        item["kind"] = self.a_kind.currentText()
        item["default"] = self.a_default.text()
        item["items"] = [l.strip() for l in self.a_items.toPlainText().splitlines() if l.strip()]
        if item.get("type") == "number":
            item["min"], item["max"], item["step"] = self.a_min.value(), self.a_max.value(), self.a_step.value()
        item["readonly"] = self.a_readonly.isChecked()
        item["required"] = self.a_required.isChecked()
        item["config"] = self.a_config.isChecked()
        cur = self.tree.currentItem()
        cur.setText(0, "%s: %s" % (LABEL.get(item.get("type"), "?"), item["caption"]))
        cur.setText(1, item["property"])

    def _tab_changed(self, *args):
        if self._loading:
            return
        self.data["message"] = self.message.text()
        self.data["configs"] = self.configs.isChecked()

    # ---- editing
    def add(self, key):
        """Adds a control (or a group box) after the picked one."""
        at = self._at()
        if key == "group":
            gi = (at[0] + 1) if at else len(self.data["groups"])
            self.data["groups"].insert(gi, {"caption": "Group Box", "expanded": True, "controls": []})
            self._show_data((gi, None))
            return (gi, None)
        if not self.data["groups"]:
            self.data["groups"].append({"caption": "Group Box", "expanded": True, "controls": []})
        gi = at[0] if at else len(self.data["groups"]) - 1
        controls = self.data["groups"][gi]["controls"]
        ci = (at[1] + 1) if at and at[1] is not None else len(controls)
        c = {"type": key, "caption": LABEL[key], "property": "", "kind": PROPERTY_KIND[key], "default": "",
             "items": ["Item 1", "Item 2"] if key in ("list", "radio") else [], "readonly": False,
             "required": False, "config": False}
        if key == "number":
            c.update({"min": 0, "max": 1000, "step": 1, "decimals": 2})
        controls.insert(ci, c)
        self._show_data((gi, ci))
        return (gi, ci)

    def move(self, step):
        at = self._at()
        if at is None:
            return
        gi, ci = at
        if ci is None:
            gs = self.data["groups"]
            j = gi + step
            if 0 <= j < len(gs):
                gs[gi], gs[j] = gs[j], gs[gi]
                self._show_data((j, None))
            return
        cs = self.data["groups"][gi]["controls"]
        j = ci + step
        if 0 <= j < len(cs):
            cs[ci], cs[j] = cs[j], cs[ci]
            self._show_data((gi, j))

    def delete(self):
        at = self._at()
        if at is None:
            return
        gi, ci = at
        if ci is None:
            self.data["groups"].pop(gi)
        else:
            self.data["groups"][gi]["controls"].pop(ci)
        self._show_data()

    # ---- files
    def new(self):
        self.data = empty(self.kind.currentText())
        self.path = None
        self._show_data()

    def open_dialog(self):
        ext = EXT[self.kind.currentText()]
        path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Open Template", folder(),
                                                         "Property tab templates (*.%s)" % ext)
        if path:
            self.open(path)

    def open(self, path):
        self.data = load_file(path)
        self.path = path
        kind = next((k for k, e in EXT.items() if path.lower().endswith("." + e)), self.kind.currentText())
        self._loading = True
        self.kind.setCurrentText(kind)
        self._loading = False
        self._show_data()

    def save(self):
        if not self.path:
            self.path = template_path(self.kind.currentText(), create=True)
        self.data["kind"] = self.kind.currentText()
        save_file(self.path, self.data)
        self.where.setText(self.path)
        _refresh_tabs()
        return self.path

    def save_as(self, path=None):
        if path is None:
            ext = EXT[self.kind.currentText()]
            path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Save Template", folder(),
                                                             "Property tab templates (*.%s)" % ext)
            if not path:
                return None
        self.path = path
        return self.save()


def _refresh_tabs():
    """The open Custom Properties tabs redraw from the saved template."""
    try:
        from . import customprops
        for w in Gui.getMainWindow().findChildren(QtWidgets.QWidget, "SWPropertyTab"):
            if isinstance(w, customprops.PropertyTab) and w.doc is not None:
                w._fill()
    except Exception as _fw_err:
        _fw_log("proptabbuilder.py:653", _fw_err)


_OPEN = []


def show(kind=None):
    box = BuilderDialog(kind)
    _OPEN[:] = [box]
    box.show()
    return box


class _Cmd:
    def GetResources(self):
        return {"MenuText": "Property Tab Builder...",
                "ToolTip": "Designs the Task Pane's Custom Properties tab for parts, assemblies and drawings."}

    def Activated(self):
        show()

    def IsActive(self):
        return True


def register():
    if "SWStyle_PropertyTabBuilder" not in Gui.listCommands():
        Gui.addCommand("SWStyle_PropertyTabBuilder", _Cmd())
