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

import hashlib
import json

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import toolbox

TITLE = "Toolbox Settings"
PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Toolbox"
HOLE_KINDS = ("Counterbore", "Countersink", "Hole", "Straight Tap", "Tapered Tap")
PAGES = ("1 Hole Wizard", "2 Customize Hardware", "3 User Settings", "4 Permissions", "5 Smart Fasteners")
GRID = ("Size", "Finish", "Thread Display", "Part Name", "Specification", "Standard", "Configuration Name",
        "Designation", "Part Number", "Description")
# ISO 273 clearance holes: close (fine) and loose (coarse); normal (medium) is toolbox.SIZES[2]
CLOSE = {"M3": 3.2, "M4": 4.3, "M5": 5.3, "M6": 6.4, "M8": 8.4, "M10": 10.5, "M12": 13.0, "M16": 17.0,
         "M20": 21.0, "M24": 25.0}
LOOSE = {"M3": 3.6, "M4": 4.8, "M5": 5.8, "M6": 7.0, "M8": 10.0, "M10": 12.0, "M12": 14.5, "M16": 18.5,
         "M20": 24.0, "M24": 28.0}
DEFAULT_FASTENERS = {"Counterbore": "socket-head-cap-screw", "Countersink": "countersunk-screw",
                     "Hole": "hex-bolt", "Straight Tap": "hex-bolt", "Tapered Tap": "hex-bolt"}


def _p():
    return App.ParamGet(PARAMS)


def _load(key, default):
    try:
        return json.loads(_p().GetString(key, "") or "null") or default
    except Exception as _fw_err:
        _fw_log("toolboxconfig.py:63", _fw_err)
        return default


def _store(key, value):
    _p().SetString(key, json.dumps(value))


# --------------------------------------------------------------------------- what is kept
def left_out(std, kind=None):
    """The sizes left out: for the standard (Hole Wizard page) and for one component (page 4)."""
    data = _load("LeftOut", {})
    out = set(data.get(std, []))
    if kind:
        out |= set(data.get("%s|%s" % (std, kind), []))
    return out


def hole_wizard_sizes(standard, kind, type_name, sizes):
    """The Hole Wizard's size list less the sizes ticked off in Toolbox Settings > Hole Wizard (extapps98). Only the screw sizes of the
    counterbore, countersink, straight tap and screw clearance lists are touched; drill, dowel and pipe sizes stay."""
    from . import holedata
    if kind not in ("Counterbore", "Countersink", "Straight Tap") and \
            not (kind == "Hole" and type_name in ("Screw Clearances", "Tap Drills")):
        return sizes
    std = "ANSI Inch" if holedata.is_inch(standard or "") else (standard if standard in toolbox.STANDARDS else "ISO")
    off = left_out(std)
    if not off:
        return sizes
    keys = set(off) | {k.split("-")[0] for k in off if "-" in k}       # an inch size "1/4-20" is "1/4" in the Hole Wizard
    return [s for s in sizes if str(s).strip('"') not in keys]


def set_left_out(std, sizes, kind=None):
    data = _load("LeftOut", {})
    key = std if not kind else "%s|%s" % (std, kind)
    data[key] = sorted(set(sizes))
    _store("LeftOut", data)


def fastener_for(hole_kind):
    return _load("SmartFasteners", {}).get(hole_kind, DEFAULT_FASTENERS.get(hole_kind, "socket-head-cap-screw"))


def set_fastener_for(hole_kind, kind):
    data = _load("SmartFasteners", {})
    data[hole_kind] = kind
    _store("SmartFasteners", data)


def _key(std, kind, size):
    return "%s|%s|%s" % (std, kind, size)


def part_numbers():
    """{"standard|type|size": [part number, description]}: what a new part of that size starts with."""
    return dict(_load("PartNumbers", {}))


def custom_props():
    """The custom property names every new Toolbox part gets."""
    return list(_load("CustomProps", []))


def part_defaults(std, kind, size):
    """(part number, description, custom property names) for a new Toolbox part."""
    number, desc = part_numbers().get(_key(std, kind, size), ["", ""])
    return number, desc, custom_props()


def stacks():
    return _load("Stacks", {"top": "", "bottom": "plain-washer,hex-nut"})


def editable():
    return _p().GetBool("AllowChanges", True)


def _hash(text):
    return hashlib.sha256(("freeworks-toolbox:" + text).encode()).hexdigest()


def has_password():
    return bool(_p().GetString("Password", ""))


def check_password(text):
    return not has_password() or _hash(text) == _p().GetString("Password", "")


def set_password(text):
    _p().SetString("Password", _hash(text) if text else "")


def clearances(std, size):
    """(close, normal, loose) clearance diameters in mm."""
    d = toolbox.SIZES.get(size) or getattr(toolbox, "_INCH", {}).get(size)
    if d is None:
        return None
    normal = d[2] if size in toolbox.SIZES else d[2] * toolbox.IN
    if size in CLOSE:
        return CLOSE[size], normal, LOOSE[size]
    major = d[0] * (1 if size in toolbox.SIZES else toolbox.IN)
    return round(major + (normal - major) * 0.5, 3), round(normal, 3), round(normal + (normal - major), 3)


# --------------------------------------------------------------------------- the box
class ToolboxSettings(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWToolboxSettings")
        self.setWindowTitle(TITLE)
        self.resize(720, 480)
        lay = QtWidgets.QHBoxLayout(self)
        self.steps = QtWidgets.QListWidget()
        self.steps.setObjectName("SWToolboxSteps")
        self.steps.setFixedWidth(180)
        self.steps.addItems(list(PAGES))
        lay.addWidget(self.steps)
        right = QtWidgets.QVBoxLayout()
        self.stack = QtWidgets.QStackedWidget()
        right.addWidget(self.stack, 1)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Close)
        buttons.button(QtWidgets.QDialogButtonBox.Save).clicked.connect(self.save)
        buttons.rejected.connect(self.reject)
        right.addWidget(buttons)
        lay.addLayout(right, 1)
        self.stack.addWidget(self._hole_wizard())
        self.stack.addWidget(self._hardware())
        self.stack.addWidget(self._user())
        self.stack.addWidget(self._permissions())
        self.stack.addWidget(self._smart())
        self.steps.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.steps.setCurrentRow(0)
        self._lock()

    # ---- 1 Hole Wizard
    def _hole_wizard(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Standard:"))
        self.hw_std = QtWidgets.QComboBox()
        self.hw_std.setObjectName("SWToolboxHWStandard")
        self.hw_std.addItems(list(toolbox.STANDARDS))
        self.hw_std.setCurrentText(toolbox.STANDARD)
        row.addWidget(self.hw_std)
        row.addWidget(QtWidgets.QLabel("Hole type:"))
        self.hw_kind = QtWidgets.QComboBox()
        self.hw_kind.setObjectName("SWToolboxHWType")
        self.hw_kind.addItems(list(HOLE_KINDS))
        row.addWidget(self.hw_kind)
        row.addStretch(1)
        lay.addLayout(row)
        self.hw_table = QtWidgets.QTableWidget(0, 4)
        self.hw_table.setObjectName("SWToolboxHWTable")
        self.hw_table.setHorizontalHeaderLabels(["Size", "Close", "Normal", "Loose"])
        self.hw_table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.hw_table, 1)
        lay.addWidget(QtWidgets.QLabel("Untick a size to leave it out of the size lists."))
        self.hw_std.currentIndexChanged.connect(self._fill_hw)
        self.hw_kind.currentIndexChanged.connect(self._fill_hw)
        self._fill_hw()
        return page

    def _fill_hw(self, *args):
        std, kind = self.hw_std.currentText(), self.hw_kind.currentText()
        out = left_out(std)
        all_sizes = toolbox.sizes.__wrapped__(std) if hasattr(toolbox.sizes, "__wrapped__") else toolbox.sizes(std)
        self.hw_table.setRowCount(0)
        for size in all_sizes:
            r = self.hw_table.rowCount()
            self.hw_table.insertRow(r)
            item = QtWidgets.QTableWidgetItem(size)
            item.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
            item.setCheckState(QtCore.Qt.Unchecked if size in out else QtCore.Qt.Checked)
            self.hw_table.setItem(r, 0, item)
            c = clearances(std, size)
            tapped = kind in ("Straight Tap", "Tapered Tap")
            for col in range(3):
                if tapped:
                    d = toolbox.SIZES.get(size)
                    text = ("%.2f" % d[3]) if (d and col == 1) else ""
                else:
                    text = ("%.2f" % c[col]) if c else ""
                cell = QtWidgets.QTableWidgetItem(text)
                cell.setFlags(QtCore.Qt.ItemIsEnabled)
                self.hw_table.setItem(r, col + 1, cell)
        self.hw_table.setHorizontalHeaderLabels(["Size", "", "Tap drill", ""] if kind in ("Straight Tap", "Tapered Tap")
                                                else ["Size", "Close", "Normal", "Loose"])
        self._lock()

    # ---- 2 User Settings
    def _user(self):
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        row = QtWidgets.QHBoxLayout()
        self.folder = QtWidgets.QLineEdit(App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks")
                                          .GetString("ToolboxFolder", ""))
        self.folder.setObjectName("SWToolboxFolder")
        row.addWidget(self.folder, 1)
        b = QtWidgets.QPushButton("Browse...")
        b.clicked.connect(self._browse)
        row.addWidget(b)
        form.addRow("Hole Wizard and Toolbox folder:", row)
        self.create_parts = QtWidgets.QRadioButton("Create parts (each size is its own part file)")
        self.create_parts.setObjectName("SWToolboxCreateParts")
        self.create_parts.setChecked(True)
        form.addRow(self.create_parts)
        return page

    def _browse(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Hole Wizard and Toolbox folder", self.folder.text())
        if path:
            self.folder.setText(path)

    # ---- 3 Permissions
    def _permissions(self):
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        self.allow = QtWidgets.QCheckBox("Allow changes to the Hole Wizard and Toolbox data")
        self.allow.setObjectName("SWToolboxAllow")
        self.allow.setChecked(editable())
        self.allow.toggled.connect(self._lock)
        form.addRow(self.allow)
        self.password = QtWidgets.QLineEdit()
        self.password.setObjectName("SWToolboxPassword")
        self.password.setEchoMode(QtWidgets.QLineEdit.Password)
        self.password.setPlaceholderText("(set)" if has_password() else "(none)")
        form.addRow("Password to open these settings:", self.password)
        clear = QtWidgets.QPushButton("Remove Password")
        clear.setObjectName("SWToolboxClearPassword")
        clear.clicked.connect(lambda: (set_password(""), self.password.setPlaceholderText("(none)")))
        form.addRow(clear)
        return page

    # ---- 4 Customize Hardware
    def _hardware(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(page)
        self.hw_tree = QtWidgets.QTreeWidget()
        self.hw_tree.setObjectName("SWToolboxHardware")
        self.hw_tree.setHeaderHidden(True)
        for std in toolbox.STANDARDS:
            top = QtWidgets.QTreeWidgetItem([std])
            folders = {}
            for key, (folder, name, desig, _len) in toolbox.TYPES.items():
                parent = top
                for part in folder.split("/"):
                    k = (id(parent), part)
                    if k not in folders:
                        folders[k] = QtWidgets.QTreeWidgetItem([part])
                        parent.addChild(folders[k])
                    parent = folders[k]
                leaf = QtWidgets.QTreeWidgetItem(["%s %s" % (desig[std], name)])
                leaf.setData(0, QtCore.Qt.UserRole, (std, key))
                parent.addChild(leaf)
            self.hw_tree.addTopLevelItem(top)
        lay.addWidget(self.hw_tree, 1)
        right = QtWidgets.QVBoxLayout()
        self.sizes = QtWidgets.QTableWidget(0, len(GRID))
        self.sizes.setObjectName("SWToolboxSizes")
        self.sizes.setHorizontalHeaderLabels(list(GRID))
        self.sizes.horizontalHeader().setStretchLastSection(True)
        right.addWidget(self.sizes, 1)
        right.addWidget(QtWidgets.QLabel("Untick a size to leave it out of the Configure Component list. Part Number and "
                                         "Description are what a new part of that size starts with."))
        self.custom_button = QtWidgets.QPushButton("Custom Properties...")
        self.custom_button.setObjectName("SWToolboxCustomProps")
        self.custom_button.clicked.connect(self._custom_props)
        right.addWidget(self.custom_button)
        lay.addLayout(right, 3)
        self.hw_tree.currentItemChanged.connect(self._fill_sizes)
        self._current = None
        return page

    def _fill_sizes(self, item, *args):
        self._keep_sizes()
        self.sizes.clearContents()
        self.sizes.setRowCount(0)
        data = item.data(0, QtCore.Qt.UserRole) if item is not None else None
        self._current = data
        if not data:
            return
        std, kind = data
        out = left_out(std, kind)
        base = toolbox.sizes.__wrapped__(std, kind) if hasattr(toolbox.sizes, "__wrapped__") else toolbox.sizes(std, kind)
        numbers = part_numbers()
        t = toolbox.TYPES[kind]
        for s in base:
            r = self.sizes.rowCount()
            self.sizes.insertRow(r)
            it = QtWidgets.QTableWidgetItem(s)
            it.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
            it.setCheckState(QtCore.Qt.Unchecked if s in out else QtCore.Qt.Checked)
            self.sizes.setItem(r, 0, it)
            number, desc = numbers.get(_key(std, kind, s), ["", ""])
            desc = desc or t[1]         # extapps110: a part's Description starts as the type's name
            cells = ("None", "Simplified", "%s %s %s" % (t[2][std], t[1], s), t[2][std], std, s,
                     "%s %s" % (t[1], s), number, desc)
            for col, text in enumerate(cells, 1):
                cell = QtWidgets.QTableWidgetItem(text)
                if col < 8:
                    cell.setFlags(QtCore.Qt.ItemIsEnabled)
                self.sizes.setItem(r, col, cell)
        self._lock()

    def _custom_props(self):
        """Create custom properties: names that every new Toolbox part gets (empty, to fill in)."""
        names = custom_props()
        dlg = QtWidgets.QDialog(self)
        dlg.setObjectName("SWToolboxCustomPropsDialog")
        dlg.setWindowTitle("Custom Properties")
        lay = QtWidgets.QVBoxLayout(dlg)
        lst = QtWidgets.QListWidget()
        lst.setObjectName("SWToolboxCustomPropsList")
        lst.addItems(names)
        lay.addWidget(lst)
        row = QtWidgets.QHBoxLayout()
        name = QtWidgets.QLineEdit()
        name.setObjectName("SWToolboxCustomPropsName")
        add = QtWidgets.QPushButton("Add")
        delete = QtWidgets.QPushButton("Delete")
        row.addWidget(name, 1)
        row.addWidget(add)
        row.addWidget(delete)
        lay.addLayout(row)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        lay.addWidget(buttons)

        def _add():
            text = name.text().strip()
            if text and text not in [lst.item(i).text() for i in range(lst.count())]:
                lst.addItem(text)
            name.clear()

        add.clicked.connect(_add)
        delete.clicked.connect(lambda: [lst.takeItem(lst.row(i)) for i in lst.selectedItems()])
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        self._custom_dialog = dlg
        dlg.show()
        if dlg.exec() == QtWidgets.QDialog.Accepted and editable_now(self):
            _store("CustomProps", [lst.item(i).text() for i in range(lst.count())])

    def _keep_sizes(self):
        if not self._current or not editable_now(self):
            return
        std, kind = self._current
        off = [self.sizes.item(i, 0).text() for i in range(self.sizes.rowCount())
               if self.sizes.item(i, 0).checkState() != QtCore.Qt.Checked]
        set_left_out(std, off, kind)
        numbers = part_numbers()
        for i in range(self.sizes.rowCount()):
            key = _key(std, kind, self.sizes.item(i, 0).text())
            pair = [self.sizes.item(i, 8).text().strip(), self.sizes.item(i, 9).text().strip()]
            if pair[1] == toolbox.TYPES[kind][1]:
                pair[1] = ""            # the default Description is not stored
            if any(pair):
                numbers[key] = pair
            else:
                numbers.pop(key, None)
        _store("PartNumbers", numbers)

    # ---- 5 Smart Fasteners
    def _smart(self):
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        screws = [(k, toolbox.TYPES[k][1]) for k in toolbox.TYPES if k not in toolbox.NUTS + toolbox.WASHERS]
        self.smart = {}
        for kind in HOLE_KINDS:
            c = QtWidgets.QComboBox()
            c.setObjectName("SWToolboxSmart_" + kind.replace(" ", ""))
            for key, name in screws:
                c.addItem(name, key)
            c.setCurrentIndex(max(0, c.findData(fastener_for(kind))))
            self.smart[kind] = c
            form.addRow("%s:" % kind, c)
        st = stacks()
        self.top_stack = QtWidgets.QComboBox()
        self.top_stack.setObjectName("SWToolboxTopStack")
        for text, data in (("None", ""), ("Plain Washer", "plain-washer"), ("Spring Lock Washer", "spring-washer")):
            self.top_stack.addItem(text, data)
        self.top_stack.setCurrentIndex(max(0, self.top_stack.findData(st.get("top", ""))))
        form.addRow("Top stack:", self.top_stack)
        self.bottom_stack = QtWidgets.QComboBox()
        self.bottom_stack.setObjectName("SWToolboxBottomStack")
        for text, data in (("None", ""), ("Hex Nut", "hex-nut"), ("Plain Washer + Hex Nut", "plain-washer,hex-nut"),
                           ("Plain Washer + Lock Nut", "plain-washer,lock-nut")):
            self.bottom_stack.addItem(text, data)
        self.bottom_stack.setCurrentIndex(max(0, self.bottom_stack.findData(st.get("bottom", ""))))
        form.addRow("Bottom stack (through holes):", self.bottom_stack)
        return page

    # ---- permissions applied
    def _lock(self, *args):
        on = editable_now(self)
        for w in (getattr(self, "hw_table", None), getattr(self, "sizes", None)):
            if w is not None:
                w.setEnabled(on)

    def save(self):
        if editable_now(self):
            std = self.hw_std.currentText()
            off = [self.hw_table.item(r, 0).text() for r in range(self.hw_table.rowCount())
                   if self.hw_table.item(r, 0).checkState() != QtCore.Qt.Checked]
            set_left_out(std, off)
            self._keep_sizes()
        App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks").SetString("ToolboxFolder", self.folder.text())
        _p().SetBool("AllowChanges", self.allow.isChecked())
        if self.password.text():
            set_password(self.password.text())
            self.password.clear()
            self.password.setPlaceholderText("(set)")
        data = {k: c.currentData() for k, c in self.smart.items()}
        _store("SmartFasteners", data)
        _store("Stacks", {"top": self.top_stack.currentData(), "bottom": self.bottom_stack.currentData()})
        return True


def editable_now(box):
    allow = getattr(box, "allow", None)
    return allow.isChecked() if allow is not None else editable()


def show(parent=None):
    """Configure: the password first when one is set."""
    if has_password():
        text, ok = QtWidgets.QInputDialog.getText(parent or Gui.getMainWindow(), TITLE, "Password:",
                                                  QtWidgets.QLineEdit.Password)
        if not ok or not check_password(text):
            if ok:
                QtWidgets.QMessageBox.warning(parent or Gui.getMainWindow(), TITLE, "The password is not right.")
            return None
    box = ToolboxSettings(parent)
    box.show()
    _open.append(box)
    return box


_open = []


# --------------------------------------------------------------------------- hooks
def install():
    """toolbox.sizes leaves out the sizes ticked off; Smart Fasteners takes its fastener and stacks
    from page 5."""
    if not hasattr(toolbox.sizes, "__wrapped__"):
        plain = toolbox.sizes

        def sizes(std, kind=None):
            out = plain(std, kind)
            off = left_out(std, kind)
            kept = [s for s in out if s not in off]
            return kept
        sizes.__wrapped__ = plain
        toolbox.sizes = sizes
    if not hasattr(toolbox.kind_for, "__wrapped__"):
        plain_kind = toolbox.kind_for

        def kind_for(spec):
            hole = str((spec or {}).get("kind", ""))
            hole = {"Counterbore Slot": "Counterbore", "Countersink Slot": "Countersink", "Slot": "Hole"}.get(hole, hole)
            text = str((spec or {}).get("type", "")).strip()
            if hole in HOLE_KINDS and (not text or _p().GetString("SmartFasteners", "")):
                return fastener_for(hole)
            return plain_kind(spec)
        kind_for.__wrapped__ = plain_kind
        toolbox.kind_for = kind_for
    if not hasattr(toolbox.smart_fasteners, "__wrapped__"):
        plain_smart = toolbox.smart_fasteners

        def smart_fasteners(asm, comps=None, kind=None, top_stack=None, bottom_stack=None, auto_length=True):
            st = stacks()
            if top_stack is None and st.get("top"):
                top_stack = tuple(x for x in st["top"].split(",") if x)
            if bottom_stack is None:
                bottom_stack = tuple(x for x in (st.get("bottom") or "").split(",") if x)
            return plain_smart(asm, comps, kind, top_stack, bottom_stack, auto_length)
        smart_fasteners.__wrapped__ = plain_smart
        toolbox.smart_fasteners = smart_fasteners
