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

from . import asmcore as ac

KIND = "FwAssemblyBom"
BOM_TYPES = ("Top-level only", "Parts only", "Indented")
NUMBERING = ("Detailed numbering", "Flat numbering", "No numbering")
THICKNESS = ("Thin", "Normal", "Thick", "Thick(2)", "Thick(3)", "Thick(4)", "Thick(5)", "Thick(6)")
WIDTH = {"Thin": 1, "Normal": 1, "Thick": 2, "Thick(2)": 3, "Thick(3)": 4, "Thick(4)": 5, "Thick(5)": 6, "Thick(6)": 7}


def _dt():
    from . import drawtables
    return drawtables


class _Source:
    """What drawtables reads from a drawing view: the model it shows."""
    def __init__(self, asm):
        self.XSource = []
        self.Source = [asm]


def is_bom(obj):
    try:
        return obj is not None and getattr(obj, "FwKind", "") == KIND
    except ReferenceError:
        return False


def boms(asm):
    return [o for o in getattr(asm, "Group", []) if is_bom(o)]


def assembly_of_bom(bom):
    for o in bom.InList:
        if o.TypeId == "Assembly::AssemblyObject":
            return o
    return ac.assembly_of(bom.Document)


def rows(bom):
    try:
        return json.loads(bom.FwRows or "[]")
    except Exception:
        return []


class _InConfig:
    """The assembly as a configuration has it: its components suppressed there left out (what
    drawtables.bom_items walks: TypeId, OutList, the rest from the assembly)."""

    def __init__(self, asm, config):
        self._asm = asm
        self.TypeId = asm.TypeId
        self.OutList = [c for c in asm.OutList if not _suppressed_in(c, config)]

    def __getattr__(self, name):
        return getattr(self._asm, name)


def _suppressed_in(comp, config):
    try:
        from . import configs, configmanager as cm
        t = cm.table(comp.Document)
        if t is None:
            return False
        v = configs.cell_value(t, configs.COMP + configs._safe(comp.Name), config)
        if v is None:
            from . import asmcomp
            return asmcomp.is_suppressed(comp)
        return v.strip() in ("1", "1.0", "True")
    except Exception as _fw_err:
        _fw_log("asmbom.py:103", _fw_err)
        return False


def configurations(doc):
    """([names], active) of the assembly's configurations."""
    try:
        from . import configmanager as cm
        t = cm.table(doc)
        if t is not None and t.names():
            return list(t.names()), t.active()
    except Exception as _fw_err:
        _fw_log("asmbom.py:113", _fw_err)
    return ["Default"], "Default"


def chosen_configs(bom):
    """The configurations the BOM lists (its Configurations group); [] = the active one."""
    try:
        return [n for n in json.loads(getattr(bom, "FwConfigs", "") or "[]") if isinstance(n, str)]
    except Exception:
        return []


def compute_rows(bom):
    ""

    dt = _dt()
    asm = assembly_of_bom(bom)
    if asm is None:
        return []
    kind = bom.Numbering.split()[0] if bom.BomType == "Indented" else "Detailed"
    keep = None
    if bom.FixedNumbers:
        keep = {r[1]: r[0] for r in rows(bom)[1:] if len(r) > 1}
    grouping = dt.CONFIG_GROUPING[max(0, min(2, bom.Grouping))]

    def run(model, keep_, missing):
        return dt.bom_rows(_Source(model), bom.BomType, bom.StartAt, bom.Increment, bom.Template, kind,
                           keep_, missing, False, bom.FollowOrder, grouping, bom.KeepMissing and bom.Strikeout)
    names, active = configurations(asm.Document)
    chosen = [n for n in chosen_configs(bom) if n in names]
    if len(chosen) < 2:
        model = asm if not chosen or chosen[0] == active else _InConfig(asm, chosen[0])
        return run(model, keep, rows(bom) if bom.KeepMissing else False)
    base = run(asm, keep, False)
    head = base[0]
    qcol = head.index("QTY.") if "QTY." in head else len(head) - 1
    per = []
    for name in chosen:
        r = base if name == active and not any(_suppressed_in(c, name) != _suppressed_now(c) for c in asm.OutList) \
            else run(_InConfig(asm, name), None, False)
        per.append({row[1]: row[qcol] for row in r[1:] if len(row) > qcol})
    out = [head[:qcol] + ["%s/QTY." % n for n in chosen] + head[qcol + 1:]]
    seen = set()
    for row in base[1:]:
        seen.add(row[1])
        out.append(row[:qcol] + [q.get(row[1], "-") for q in per] + row[qcol + 1:])
    last = max([int(r[0]) for r in base[1:] if str(r[0]).isdigit()] or [bom.StartAt - bom.Increment])
    for q in per:                       # parts only in another configuration (suppressed in this one)
        for pn in q:
            if pn not in seen:
                seen.add(pn)
                last += bom.Increment
                row = [str(last), pn] + [""] * (len(head) - 2)
                out.append(row[:qcol] + [qq.get(pn, "-") for qq in per] + row[qcol + 1:])
    return out


def _suppressed_now(comp):
    try:
        from . import asmcomp
        return asmcomp.is_suppressed(comp)
    except Exception as _fw_err:
        _fw_log("asmbom.py:177", _fw_err)
        return False


def update(bom):
    """The rows again from the assembly; the spreadsheet and the floating table with them."""
    new = compute_rows(bom)
    if json.dumps(new) != bom.FwRows:
        bom.FwRows = json.dumps(new)
        sheet = bom.Data
        if sheet is not None:
            _dt().fill(sheet, new, _dt().bom_widths(bom.Template))
    overlay(bom)
    return new


def update_all(doc):
    asm = ac.assembly_of(doc)
    if asm is None:
        return
    for b in boms(asm):
        try:
            update(b)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Bill of Materials: %s\n" % error)


SETTINGS = ("BomType", "Template", "Grouping", "StartAt", "Increment", "KeepMissing", "Strikeout",
            "FixedNumbers", "FollowOrder", "Numbering", "BoxBorder", "GridBorder", "FwConfigs")


def _later_props(bom):
    """Configurations and Border, added in a later version: older BOMs get them on first use."""
    if not hasattr(bom, "BoxBorder"):
        bom.addProperty("App::PropertyEnumeration", "BoxBorder", "Bill of Materials", "Border: Box border")
        bom.BoxBorder = list(THICKNESS)
        bom.BoxBorder = "Normal"
    if not hasattr(bom, "GridBorder"):
        bom.addProperty("App::PropertyEnumeration", "GridBorder", "Bill of Materials", "Border: Grid border")
        bom.GridBorder = list(THICKNESS)
        bom.GridBorder = "Thin"
    if not hasattr(bom, "FwConfigs"):
        bom.addProperty("App::PropertyString", "FwConfigs", "FreeCAD", "Configurations listed (json)")
        bom.setEditorMode("FwConfigs", 2)


def make(asm, values=None):
    """Bill of Materials<n> in the assembly with the PropertyManager's values."""
    doc = asm.Document
    values = dict(values or {})
    bom = doc.addObject("App::FeaturePython", "BillOfMaterials")
    n = 1
    labels = {o.Label for o in doc.Objects}
    while "Bill of Materials%d" % n in labels:
        n += 1
    bom.Label = "Bill of Materials%d" % n
    bom.addProperty("App::PropertyString", "FwKind", "FreeCAD", "Kind").FwKind = KIND
    bom.setEditorMode("FwKind", 2)
    bom.addProperty("App::PropertyEnumeration", "BomType", "Bill of Materials", "BOM Type")
    bom.BomType = list(BOM_TYPES)
    bom.addProperty("App::PropertyEnumeration", "Template", "Bill of Materials", "Table Template")
    bom.Template = list(_dt().BOM_TEMPLATES)
    bom.addProperty("App::PropertyEnumeration", "Numbering", "Bill of Materials", "Indented numbering")
    bom.Numbering = list(NUMBERING)
    bom.addProperty("App::PropertyInteger", "Grouping", "Bill of Materials", "Part Configuration Grouping (0-2)")
    bom.addProperty("App::PropertyInteger", "StartAt", "Bill of Materials", "Item Numbers: Start at").StartAt = 1
    bom.addProperty("App::PropertyInteger", "Increment", "Bill of Materials", "Item Numbers: Increment").Increment = 1
    for prop, tip, default in (("KeepMissing", "Keep missing items", False), ("Strikeout", "Strikeout", False),
                               ("FixedNumbers", "Do not change item numbers", False),
                               ("FollowOrder", "Follow assembly order", True)):
        bom.addProperty("App::PropertyBool", prop, "Bill of Materials", tip)
        setattr(bom, prop, default)
    bom.addProperty("App::PropertyString", "FwRows", "FreeCAD", "Rows (json)")
    bom.setEditorMode("FwRows", 2)
    bom.addProperty("App::PropertyVector", "FwAt", "FreeCAD", "Table position in the view (px)")
    bom.FwAt = App.Vector(12, 12, 0)
    bom.setEditorMode("FwAt", 2)
    bom.addProperty("App::PropertyLink", "Data", "FreeCAD", "The rows' spreadsheet")
    _later_props(bom)
    sheet = doc.addObject("Spreadsheet::Sheet", "BomData")
    sheet.Label = bom.Label + " data"
    bom.Data = sheet
    set_values(bom, values)
    BomFeature(bom)
    if App.GuiUp:
        ViewProviderBom(bom.ViewObject)
        try:
            sheet.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("asmbom.py:263", _fw_err)
    asm.addObject(bom)
    update(bom)
    return bom


def set_values(bom, values):
    _later_props(bom)
    for key in SETTINGS:
        if key in values:
            setattr(bom, key, values[key])


def values_of(bom):
    return {k: getattr(bom, k) for k in SETTINGS if hasattr(bom, k)}


class BomFeature:
    def __init__(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderBom:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        try:
            from pivy import coin
            vobj.addDisplayMode(coin.SoGroup(), "Default")
        except Exception as _fw_err:
            _fw_log("asmbom.py:304", _fw_err)

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        return ":/icons/Spreadsheet.svg"

    def claimChildren(self):
        obj = getattr(self, "Object", None)       # not yet attached while a saved file loads
        d = getattr(obj, "Data", None) if obj is not None else None
        return [d] if d is not None else []

    def onChanged(self, vobj, prop):
        if prop == "Visibility":
            QtCore.QTimer.singleShot(0, lambda o=vobj.Object: overlay(o))

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        QtCore.QTimer.singleShot(0, lambda o=vobj.Object: edit(o))
        return False

    def doubleClicked(self, vobj):
        edit(vobj.Object)
        return True

    def onDelete(self, vobj, subelements):
        _drop_overlay(vobj.Object)
        d = getattr(vobj.Object, "Data", None)
        if d is not None:
            name, doc = d.Name, d.Document
            QtCore.QTimer.singleShot(0, lambda: doc.getObject(name) and doc.removeObject(name))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


# ---------------------------------------------------------------- the table over the graphics area
OVERLAYS = {}


def _view_widget(doc):
    try:
        gdoc = Gui.getDocument(doc.Name)
        view = gdoc.ActiveView if gdoc is not None else None
        gv = view.graphicsView() if view is not None else None
        return gv
    except Exception as _fw_err:
        _fw_log("asmbom.py:363", _fw_err)
        return None


class BomOverlay(QtWidgets.QFrame):
    """The Bill of Materials floating over the graphics area; drag its title to move it."""

    def __init__(self, bom, parent):
        super().__init__(parent)
        self.setObjectName("FW_AssemblyBomTable")
        self.doc_name, self.name = bom.Document.Name, bom.Name
        self.setFrameShape(QtWidgets.QFrame.Box)
        self.setAutoFillBackground(True)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)
        self.title = QtWidgets.QLabel(bom.Label, self)
        self.title.setObjectName("FW_AssemblyBomTitle")
        self.title.setCursor(QtCore.Qt.SizeAllCursor)
        lay.addWidget(self.title)
        self.table = QtWidgets.QTableWidget(self)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.table.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 6)
        lay.addWidget(self.table)
        self.drag = None
        self.title.installEventFilter(self)

    def bom(self):
        d = App.listDocuments().get(self.doc_name)
        return d.getObject(self.name) if d is not None else None

    def fill(self, rows_):
        head = rows_[0] if rows_ else []
        body = rows_[1:]
        self.table.setColumnCount(len(head))
        self.table.setRowCount(len(body))
        self.table.setHorizontalHeaderLabels(head)
        for r, row in enumerate(body):
            for c, val in enumerate(row):
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(str(val)))
        self.table.resizeColumnsToContents()
        hh = self.table.horizontalHeader()
        h = hh.sizeHint().height() + self.table.verticalHeader().length() + 2 * self.table.frameWidth()
        w = hh.length() + 2 * self.table.frameWidth()
        self.table.setFixedSize(w, h)
        self.adjustSize()

    def borders(self, box, grid):
        """Border: the box (outer frame) and grid (cell lines) thicknesses."""
        self.setLineWidth(WIDTH.get(box, 1))
        g = WIDTH.get(grid, 1)
        self.table.setShowGrid(True)
        self.table.setStyleSheet("QTableWidget { gridline-color: palette(text); }"
                                 "QTableWidget::item { border: %dpx solid palette(mid); }" % max(0, g - 1))
        self.setProperty("fw_box_border", WIDTH.get(box, 1))
        self.setProperty("fw_grid_border", g)

    def eventFilter(self, watched, e):
        if not isinstance(e, QtCore.QEvent):
            return False
        if watched is self.title:
            if e.type() == QtCore.QEvent.MouseButtonPress and e.button() == QtCore.Qt.LeftButton:
                self.drag = e.globalPosition().toPoint() - self.pos() if hasattr(e, "globalPosition") \
                    else e.globalPos() - self.pos()
                return True
            if e.type() == QtCore.QEvent.MouseMove and self.drag is not None:
                g = e.globalPosition().toPoint() if hasattr(e, "globalPosition") else e.globalPos()
                self.move(g - self.drag)
                return True
            if e.type() == QtCore.QEvent.MouseButtonRelease and self.drag is not None:
                self.drag = None
                b = self.bom()
                if b is not None:
                    b.FwAt = App.Vector(self.x(), self.y(), 0)
                return True
        return super().eventFilter(watched, e)


def overlay(bom):
    """Shows, refreshes or hides the floating table as the feature is shown or hidden."""
    key = (bom.Document.Name, bom.Name)
    w = OVERLAYS.get(key)
    shown = False
    try:
        shown = bool(bom.ViewObject.Visibility)
    except Exception as _fw_err:
        _fw_log("asmbom.py:448", _fw_err)
    if not shown or not App.GuiUp:
        if w is not None:
            try:
                w.hide()
            except RuntimeError:
                OVERLAYS.pop(key, None)
        return None
    parent = _view_widget(bom.Document)
    if parent is None:
        return None
    try:
        if w is None or w.parent() is not parent:
            raise RuntimeError
    except RuntimeError:
        w = BomOverlay(bom, parent)
        OVERLAYS[key] = w
    w.title.setText(bom.Label)
    w.fill(rows(bom))
    w.borders(getattr(bom, "BoxBorder", "Normal"), getattr(bom, "GridBorder", "Thin"))
    w.move(int(bom.FwAt.x), int(bom.FwAt.y))
    w.show()
    w.raise_()
    return w


def _drop_overlay(bom):
    w = OVERLAYS.pop((bom.Document.Name, bom.Name), None)
    if w is not None:
        try:
            w.deleteLater()
        except RuntimeError as _fw_err:
            _fw_log("asmbom.py:480", _fw_err)


# ---------------------------------------------------------------- PropertyManager
class BomPanel:
    ""

    def __init__(self, asm, bom=None):
        dt = _dt()
        self.asm, self.bom, self.doc = asm, bom, asm.Document
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("FW_AssemblyBomPM")
        self.form.setWindowTitle("Bill of Materials")
        self.form.setProperty("swstyle_pm_title", "Bill of Materials")
        self.form.setProperty("swstyle_pm_icon", "ASSEMBLIES_BOM")
        lay = QtWidgets.QVBoxLayout(self.form)
        v = values_of(bom) if bom is not None else {}

        def group(title):
            box = QtWidgets.QGroupBox(title, self.form)
            gl = QtWidgets.QVBoxLayout(box)
            lay.addWidget(box)
            return box, gl
        box, gl = group("Table Template")
        self.template = QtWidgets.QComboBox(box)
        self.template.setObjectName("SWBomTemplate")
        self.template.addItems(list(dt.BOM_TEMPLATES))
        self.template.setCurrentText(v.get("Template", dt.BOM_TEMPLATES[0]))
        gl.addWidget(self.template)
        box, gl = group("BOM Type")
        self.types = []
        for k in BOM_TYPES:
            b = QtWidgets.QRadioButton(k, box)
            b.setObjectName("SWBomType" + k.split()[0].replace("-", ""))
            b.setChecked(k == v.get("BomType", BOM_TYPES[0]))
            gl.addWidget(b)
            self.types.append(b)
        self.numbering = QtWidgets.QComboBox(box)
        self.numbering.setObjectName("SWBomNumbering")
        self.numbering.addItems(list(NUMBERING))
        self.numbering.setCurrentText(v.get("Numbering", NUMBERING[0]))
        gl.addWidget(self.numbering)
        for b in self.types:
            b.toggled.connect(self._indented)
        box, gl = group("Configurations")
        self.configs = QtWidgets.QListWidget(box)
        self.configs.setObjectName("SWBomConfigurations")
        names, active = configurations(self.doc)
        chosen = (json.loads(v.get("FwConfigs") or "[]") if v.get("FwConfigs") else []) or [active]
        for n in names:
            it = QtWidgets.QListWidgetItem(n, self.configs)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if n in chosen else QtCore.Qt.Unchecked)
        self.configs.setFixedHeight(min(6, max(2, len(names))) * (self.configs.fontMetrics().height() + 6) + 4)
        gl.addWidget(self.configs)
        box, gl = group("Part Configuration Grouping")
        self.grouping = []
        for n, k in enumerate(dt.CONFIG_GROUPING):

            # so the radio carries no text and a word-wrapped label beside it picks it on a click
            row = QtWidgets.QWidget(box)
            hl = QtWidgets.QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            b = QtWidgets.QRadioButton(row)
            b.setObjectName("SWBomGrouping%d" % n)
            b.setAccessibleName(k)
            b.setChecked(n == v.get("Grouping", 0))
            label = QtWidgets.QLabel(k, row)
            label.setObjectName("SWBomGroupingText%d" % n)
            label.setWordWrap(True)
            label.setBuddy(b)
            label.mousePressEvent = lambda _e, b=b: b.setChecked(True)
            hl.addWidget(b, 0, QtCore.Qt.AlignTop)
            hl.addWidget(label, 1)
            gl.addWidget(row)
            self.grouping.append(b)
        box, gl = group("Keep Missing Items/Rows")
        self.keep = QtWidgets.QCheckBox("Keep missing items", box)
        self.keep.setObjectName("SWBomKeepMissing")
        self.keep.setChecked(v.get("KeepMissing", False))
        self.strike = QtWidgets.QCheckBox("Strikeout", box)
        self.strike.setObjectName("SWBomStrikeout")
        self.strike.setChecked(v.get("Strikeout", False))
        self.keep.toggled.connect(self.strike.setEnabled)
        self.strike.setEnabled(self.keep.isChecked())
        gl.addWidget(self.keep)
        gl.addWidget(self.strike)
        box, gl = group("Item Numbers")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Start at:", box))
        self.start = QtWidgets.QSpinBox(box)
        self.start.setObjectName("SWBomStart")
        self.start.setRange(0, 100000)
        self.start.setValue(v.get("StartAt", 1))
        row.addWidget(self.start)
        row.addWidget(QtWidgets.QLabel("Increment:", box))
        self.step = QtWidgets.QSpinBox(box)
        self.step.setObjectName("SWBomIncrement")
        self.step.setRange(1, 1000)
        self.step.setValue(v.get("Increment", 1))
        row.addWidget(self.step)
        gl.addLayout(row)
        self.fixed = QtWidgets.QCheckBox("Do not change item numbers", box)
        self.fixed.setObjectName("SWBomFixedNumbers")
        self.fixed.setChecked(v.get("FixedNumbers", False))
        gl.addWidget(self.fixed)
        self.follow = QtWidgets.QCheckBox("Follow assembly order", box)
        self.follow.setObjectName("SWBomFollowOrder")
        self.follow.setChecked(v.get("FollowOrder", True))
        gl.addWidget(self.follow)
        box, gl = group("Border")
        form = QtWidgets.QFormLayout()
        self.box_border = QtWidgets.QComboBox(box)
        self.box_border.setObjectName("SWBomBoxBorder")
        self.box_border.addItems(list(THICKNESS))
        self.box_border.setCurrentText(v.get("BoxBorder", "Normal"))
        self.box_border.setToolTip("Box border")
        self.grid_border = QtWidgets.QComboBox(box)
        self.grid_border.setObjectName("SWBomGridBorder")
        self.grid_border.addItems(list(THICKNESS))
        self.grid_border.setCurrentText(v.get("GridBorder", "Thin"))
        self.grid_border.setToolTip("Grid border")
        form.addRow("Box border:", self.box_border)
        form.addRow("Grid border:", self.grid_border)
        gl.addLayout(form)
        lay.addStretch(1)
        self._indented()

    def _indented(self, *a):
        self.numbering.setEnabled(self.bom_type() == "Indented")

    def bom_type(self):
        return next((b.text() for b in self.types if b.isChecked()), BOM_TYPES[0])

    def values(self):
        return {"BomType": self.bom_type(), "Template": self.template.currentText(),
                "Grouping": next((n for n, b in enumerate(self.grouping) if b.isChecked()), 0),
                "StartAt": self.start.value(), "Increment": self.step.value(),
                "KeepMissing": self.keep.isChecked(), "Strikeout": self.strike.isChecked(),
                "FixedNumbers": self.fixed.isChecked(), "FollowOrder": self.follow.isChecked(),
                "Numbering": self.numbering.currentText(),
                "BoxBorder": self.box_border.currentText(), "GridBorder": self.grid_border.currentText(),
                "FwConfigs": json.dumps(self.chosen())}

    def chosen(self):
        out = []
        for i in range(self.configs.count()):
            it = self.configs.item(i)
            if it.checkState() == QtCore.Qt.Checked:
                out.append(it.text())
        return out

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        self.doc.openTransaction("Bill of Materials")
        try:
            if self.bom is None:
                self.bom = make(self.asm, self.values())
            else:
                set_values(self.bom, self.values())
                update(self.bom)
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        _refresh_tree()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


def _refresh_tree():
    try:
        from . import fmtree
        for t in Gui.getMainWindow().findChildren(QtWidgets.QTreeView, "SWFeatureTree"):
            m = t.model()
            if hasattr(m, "rebuild"):
                m.rebuild()
    except Exception as _fw_err:
        _fw_log("asmbom.py:647", _fw_err)


def open_panel(asm, bom=None):
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    global LAST
    panel = LAST = BomPanel(asm, bom)
    Gui.Control.showDialog(panel)
    return panel


LAST = None


def edit(bom):
    asm = assembly_of_bom(bom)
    if asm is not None:
        return open_panel(asm, bom)
    return None


class AssemblyBomCommand:
    def GetResources(self):
        return {"MenuText": "Bill of Materials", "ToolTip": "Adds a bill of materials.",
                "Pixmap": "Spreadsheet"}

    def Activated(self, *args):
        asm = ac.assembly_of(App.ActiveDocument) if App.ActiveDocument else None
        if asm is not None:
            open_panel(asm)

    def IsActive(self):
        return App.ActiveDocument is not None and ac.assembly_of(App.ActiveDocument) is not None


class _Observer:
    def slotRecomputedDocument(self, doc):
        if ac.assembly_of(doc) is not None and any(is_bom(o) for o in doc.Objects):
            QtCore.QTimer.singleShot(0, lambda n=doc.Name: _later(n))

    def slotCreatedDocument(self, doc):
        QtCore.QTimer.singleShot(0, lambda n=doc.Name: _restore(n))


def _later(name):
    d = App.listDocuments().get(name)
    if d is not None:
        update_all(d)


def _restore(name):
    """A saved assembly opened: its BOMs get their proxies' view (the table) again."""
    d = App.listDocuments().get(name)
    if d is None:
        return
    if any(is_bom(o) for o in d.Objects):
        QtCore.QTimer.singleShot(300, lambda: [overlay(o) for o in d.Objects if is_bom(o)])


_OBS = None


def register():
    global _OBS
    try:
        Gui.addCommand("SWStyle_AssemblyBOM", AssemblyBomCommand())
    except Exception as _fw_err:
        _fw_log("asmbom.py:715", _fw_err)
    if _OBS is None:
        _OBS = _Observer()
        App.addDocumentObserver(_OBS)
