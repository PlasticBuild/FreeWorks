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

import csv
import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import asmevaluate as ae

Qt = QtCore.Qt
PAGE = "AssemblyVisualization"
TAB = ("ASSEMBLIES_VISUALIZATION", "Assembly Visualization", PAGE)
STATE = {"page": None}


class ColourBar(QtWidgets.QWidget):
    """The spectrum beside the list: red at the top (most), blue at the bottom (least)."""

    def __init__(self, slider, parent=None):
        super().__init__(parent)
        self.slider = slider
        self.setFixedWidth(14)

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        g = QtGui.QLinearGradient(0, self.height(), 0, 0)
        mid = self.slider.value() / 100.0
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            at = t * mid * 2 if t <= 0.5 else mid + (t - 0.5) * 2 * (1 - mid)
            g.setColorAt(max(0.0, min(1.0, at)), QtGui.QColor.fromRgbF(*ae.ramp(t)))
        p.fillRect(self.rect(), g)
        p.end()


def remap(t, mid):
    """t (0-1 along the values) with the slider's middle at mid: mid itself shows as green."""
    mid = max(0.01, min(0.99, mid))
    return t / mid * 0.5 if t <= mid else 0.5 + (t - mid) / (1 - mid) * 0.5


PROPS = tuple(ae.PROPERTIES) + ("Density", "Material")
TEXT_PROPS = ("Material",)
SUMS = ("Mass", "Volume", "Surface Area", "Bodies", "Faces", "Triangles", "Rebuild Time")
UNITS = {"Mass": " g", "Volume": " mm^3", "Surface Area": " mm^2", "Rebuild Time": " s", "Density": " kg/m^3"}
PARAM = "User parameter:BaseApp/Preferences/Mod/FreeWorks/AssemblyVisualization"


def is_custom(prop):
    return prop not in PROPS and prop not in ("File Name", "Quantity")


def custom_value(comp, name):
    """A custom property of the component's part (its configuration's own first), as text."""
    from . import fileprops
    target = comp.getLinkedObject(True)
    doc = getattr(target, "Document", None)
    try:
        v = fileprops.value(doc, name) if doc is not None else None
    except Exception:
        v = None
    return "" if v is None else str(v)


_NUM = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")


def as_number(v):
    """A value as a number: floats as they are, text by its leading number ("12.5 kg"), else None."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    m = _NUM.match(str(v or ""))
    return float(m.group(1)) if m else None


def custom_names(asm):
    """The custom property names of the assembly's parts, in the order first found."""
    from . import asmcore as ac, customprops, fileprops
    out = []
    docs = []
    for c in ac.components(asm) + [x for s in ac.components(asm) if ac.is_subassembly(s) for x in ac.sub_components(s)]:
        d = getattr(c.getLinkedObject(True), "Document", None)
        if d is not None and d not in docs:
            docs.append(d)
    for d in docs:
        rows = list(customprops.read(d))
        try:
            rows += list(fileprops.read_config(d, fileprops.active_configuration(d)))
        except Exception as _fw_err:
            _fw_log("asmvistab.py:118", _fw_err)
        for n, _k, _v in rows:
            if n and n not in out:
                out.append(n)
    return out


def prop_value(comp, prop):
    if is_custom(prop):
        return custom_value(comp, prop)
    if prop == "Density":
        return ae._density(comp, 1000.0)
    if prop == "Material":
        part = comp.getLinkedObject(True)
        for obj in (part, getattr(part, "Tip", None)):
            mat = getattr(obj, "ShapeMaterial", None)
            name = getattr(mat, "Name", "") if mat is not None else ""
            if name and name != "Default":
                return name
        return ""
    return ae._value(comp, prop)


def _key_of(comp, asm):
    target = comp.getLinkedObject(True)
    doc = getattr(target, "Document", None)
    return doc.Label if doc is not None and doc is not asm.Document else target.Label


def grouped(asm, comps, props):
    ""
    rows = {}
    for c in comps:
        k = _key_of(c, asm)
        r = rows.get(k)
        if r is None:
            r = rows[k] = {"name": k, "qty": 0, "vals": {}, "comps": [], "kids": []}
            for p in props:
                try:
                    r["vals"][p] = prop_value(c, p)
                except Exception:
                    r["vals"][p] = "" if p in TEXT_PROPS or is_custom(p) else 0.0
        r["qty"] += 1
        r["comps"].append(c)
    return list(rows.values())


def nested(asm, props, comps=None):
    """The nested view: the top components grouped, a subassembly a row with its parts under it."""
    from . import asmcore as ac
    comps = [c for c in (ac.components(asm) if comps is None else comps) if not getattr(c, "FwComponentSuppressed", False)]
    parts = [c for c in comps if not ac.is_subassembly(c)]
    out = grouped(asm, parts, props)
    for s in [c for c in comps if ac.is_subassembly(c)]:
        kids = nested(asm, props, ac.sub_components(s))
        r = {"name": ac.part_name(s), "qty": 1, "vals": {}, "comps": [s], "kids": kids}
        for p in props:
            if p in SUMS:
                r["vals"][p] = sum(float(k["vals"].get(p) or 0) * k["qty"] for k in kids)
            elif p in TEXT_PROPS:
                r["vals"][p] = ""
            elif is_custom(p):
                r["vals"][p] = custom_value(s, p)
            else:
                r["vals"][p] = ""
        out.append(r)
    return out


def _text(prop, v):
    if prop in TEXT_PROPS or is_custom(prop):
        return str(v or "")
    if isinstance(v, float):
        return ae._f(v, 3) + UNITS.get(prop, "")
    return str(v) + UNITS.get(prop, "")


def _num(v):
    try:
        return float(v)
    except Exception:
        return None


def swatch(colour, size=12):
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pm = _hidpi.canvas(size, size)
    pm.fill(QtGui.QColor.fromRgbF(*colour[:3]))
    p = QtGui.QPainter(pm)
    p.setPen(QtGui.QColor(0, 0, 0, 90))
    p.drawRect(0, 0, size - 1, size - 1)
    p.end()
    return QtGui.QIcon(pm)


class VisualizationTab(ae.VisualizationWindow):
    def __init__(self):
        super().__init__()
        prm = App.ParamGet(PARAM)
        saved = [p for p in (prm.GetString("Columns", "") or "Mass").split(";") if p.strip()]
        self.props = saved or ["Mass"]
        self.sort_prop, self.descending = self.props[0], True
        self.colour_prop = self.props[0] if self.props[0] not in TEXT_PROPS and not is_custom(self.props[0]) else "Mass"
        self.nested = prm.GetBool("Nested", False)
        self.prop.hide()
        for i in range(self.options.count()):
            w = self.options.itemAt(i).widget()
            if isinstance(w, QtWidgets.QLabel) and w.text() == "Property:":
                w.hide()
        head = self.table.header()
        head.setSectionsClickable(True)
        head.sectionClicked.connect(self._header_clicked)
        head.setContextMenuPolicy(Qt.CustomContextMenu)
        head.customContextMenuRequested.connect(self._header_menu)
        self.table.itemSelectionChanged.disconnect()
        self.table.itemSelectionChanged.connect(self._picked_item)
        self.setWindowFlags(Qt.Widget)
        self.setObjectName("SWAssemblyVisualizationTab")
        self.slider = QtWidgets.QSlider(Qt.Vertical)
        self.slider.setObjectName("FW_VisSlider")
        self.slider.setRange(1, 99)
        self.slider.setValue(50)
        self.slider.setToolTip("Drag to move where the colours change")
        self.bar = ColourBar(self.slider)
        self.slider.valueChanged.connect(lambda *_: (self.bar.update(), self._paint()))

        row = QtWidgets.QHBoxLayout()
        self.layout_.removeWidget(self.table)
        row.addWidget(self.table, 1)
        row.addWidget(self.bar)
        row.addWidget(self.slider)
        self.layout_.insertLayout(1, row, 1)
        self.copy.hide()
        self.save_as = QtWidgets.QPushButton("Save As...")
        self.save_as.setObjectName("FW_VisSaveAs")
        self.save_as.setToolTip("Save the list to a .csv (Excel) or .txt file")
        self.save_as.clicked.connect(lambda *_: self.ask_save())
        for i in range(self.layout_.count()):
            lay = self.layout_.itemAt(i).layout()
            if lay is not None and lay.indexOf(self.recalc) >= 0:
                lay.insertWidget(lay.indexOf(self.recalc) + 1, self.save_as)
        self.leaf_items = []
        self.bar.setContextMenuPolicy(Qt.CustomContextMenu)
        self.bar.customContextMenuRequested.connect(self._bar_menu)

    # ---------------------------------------------------------------- the list
    def compute(self):
        asm = ae._asm()
        if asm is None:
            self.table.clear()
            self.rows_ = []
            self.summary.setText("Open an assembly first.")
            return
        heads = ["File Name", "Quantity"] + list(self.props)
        self.table.setColumnCount(len(heads))
        self.table.setHeaderLabels([h + (" \u25bc" if h == self.sort_prop and self.descending else
                                         " \u25b2" if h == self.sort_prop else "") for h in heads])
        self.table.setRootIsDecorated(self.nested)
        props = list(dict.fromkeys(list(self.props) + [self.colour_prop]))
        rows = nested(asm, props) if self.nested else grouped(asm, ae._comps(asm, subassemblies=False), props)
        self._last_rows = rows
        if self.colour_prop not in self.props or not self.numeric(self.colour_prop, rows):
            self.colour_prop = next((p for p in self.props if self.numeric(p, rows)), "Mass")
            if self.colour_prop not in props:
                rows = nested(asm, props + [self.colour_prop]) if self.nested else \
                    grouped(asm, ae._comps(asm, subassemblies=False), props + [self.colour_prop])
                self._last_rows = rows
        self._sort(rows)
        self.table.clear()
        self.items_by_row = {}
        self.rows = []
        self._fill(None, rows)
        if self.nested:
            self.table.expandAll()
        for i in range(self.table.columnCount()):
            self.table.resizeColumnToContents(i)
        leaves = []

        def walk(rs):
            for r in rs:
                if r["kids"]:
                    walk(r["kids"])
                else:
                    leaves.append(r)
        walk(rows)
        cp = self.colour_prop
        self.rows_ = [(r["name"], r["qty"], as_number(r["vals"].get(cp)), r["comps"]) for r in leaves]
        self.leaf_rows = leaves
        self._paint()
        self.summary.setText("%d parts, %d components" % (len(leaves), sum(r["qty"] for r in leaves)))

    def _sort(self, rows):
        p = self.sort_prop
        if p == "File Name":
            key = lambda r: str(r["name"]).lower()
        elif p == "Quantity":
            key = lambda r: r["qty"]
        elif p in TEXT_PROPS or (is_custom(p) and not self.numeric(p, rows)):
            key = lambda r: str(r["vals"].get(p) or "").lower()
        elif is_custom(p):
            key = lambda r: as_number(r["vals"].get(p)) if as_number(r["vals"].get(p)) is not None else float("-inf")
        else:
            key = lambda r: _num(r["vals"].get(p)) or 0.0
        rows.sort(key=key, reverse=self.descending)
        for r in rows:
            if r["kids"]:
                self._sort(r["kids"])

    def numeric(self, prop, rows=None):
        """A custom column whose values are numbers (empty cells left out)."""
        if not is_custom(prop):
            return prop not in TEXT_PROPS
        vals = []

        def walk(rs):
            for r in rs:
                vals.append(r["vals"].get(prop))
                walk(r["kids"])
        walk(rows if rows is not None else getattr(self, "_last_rows", []))
        vals = [v for v in vals if str(v or "").strip()]
        return bool(vals) and all(as_number(v) is not None for v in vals)

    def _fill(self, parent, rows):
        for r in rows:
            cells = [r["name"], str(r["qty"])] + [_text(p, r["vals"].get(p)) for p in self.props]
            it = QtWidgets.QTreeWidgetItem(cells)
            it.setData(0, Qt.UserRole, ae._pick(r["comps"]))
            self.items_by_row[id(r)] = it
            if parent is None:
                self.table.addTopLevelItem(it)
            else:
                parent.addChild(it)
            self._fill(it, r["kids"])

    def _picked_item(self):
        items = self.table.selectedItems()
        if not items:
            return
        Gui.Selection.clearSelection()
        for doc, obj, sub in items[0].data(0, Qt.UserRole) or []:
            try:
                Gui.Selection.addSelection(doc, obj, sub)
            except Exception as _fw_err:
                _fw_log("asmvistab.py:360", _fw_err)

    def _header_clicked(self, col):
        heads = ["File Name", "Quantity"] + list(self.props)
        if col >= len(heads):
            return
        name = heads[col]
        if name == self.sort_prop:
            self.descending = not self.descending
        else:
            self.sort_prop = name
            self.descending = name == "Quantity" or (name in self.props and self.numeric(name))
        if name in self.props and self.numeric(name):
            self.colour_prop = name
        self.refresh()

    def add_column(self, prop):
        prop = (prop or "").strip()
        if prop and prop not in self.props and prop not in ("File Name", "Quantity"):
            self.props.append(prop)
            self._save()
            self.refresh()

    def delete_column(self, prop):
        if prop in self.props and len(self.props) > 1:
            self.props.remove(prop)
            if self.sort_prop == prop:
                self.sort_prop, self.descending = self.props[0], True
            if self.colour_prop == prop:
                self.colour_prop = next((p for p in self.props if self.numeric(p)), "Mass")
            self._save()
            self.refresh()

    def set_nested(self, on):
        self.nested = bool(on)
        App.ParamGet(PARAM).SetBool("Nested", self.nested)
        self.refresh()

    def _save(self):
        App.ParamGet(PARAM).SetString("Columns", ";".join(self.props))

    def header_menu(self, col):
        """The header's right-click menu (built for column col)."""
        heads = ["File Name", "Quantity"] + list(self.props)
        m = QtWidgets.QMenu(self)
        m.setObjectName("FW_VisHeaderMenu")
        add = m.addMenu("Add Column")
        m._fw_add = add          # keep the submenu alive with the menu
        for p in PROPS:
            a = add.addAction(p)
            a.setEnabled(p not in self.props)
            a.triggered.connect(lambda *_, p=p: self.add_column(p))
        add.addSeparator()
        more = add.addAction("More...")
        more.setObjectName("FW_VisMore")
        more.triggered.connect(lambda *_: self.ask_custom())
        name = heads[col] if 0 <= col < len(heads) else ""
        d = m.addAction("Delete Column")
        d.setEnabled(name in self.props and len(self.props) > 1)
        d.triggered.connect(lambda *_: self.delete_column(name))
        m.addSeparator()
        flat = m.addAction("Flat View")
        flat.setCheckable(True)
        flat.setChecked(not self.nested)
        flat.triggered.connect(lambda *_: self.set_nested(False))
        nest = m.addAction("Nested View")
        nest.setCheckable(True)
        nest.setChecked(self.nested)
        nest.triggered.connect(lambda *_: self.set_nested(True))
        return m

    def custom_choices(self):
        asm = ae._asm()
        return [n for n in (custom_names(asm) if asm is not None else []) if n not in self.props]

    def ask_custom(self):
        """More...: a custom property of the parts as a column (a name may also be typed)."""
        names = self.custom_choices()
        name, ok = QtWidgets.QInputDialog.getItem(self, "Custom Column", "Custom property:", names, 0, True)
        if ok and name.strip():
            self.add_column(name.strip())

    def table_rows(self):
        """The list as shown: the header and each row's cells, top to bottom (nested rows indented)."""
        heads = ["File Name", "Quantity"] + list(self.props)
        out = [heads]

        def walk(item, depth):
            cells = [item.text(i) for i in range(len(heads))]
            cells[0] = "    " * depth + cells[0]
            out.append(cells)
            for k in range(item.childCount()):
                walk(item.child(k), depth + 1)
        for i in range(self.table.topLevelItemCount()):
            walk(self.table.topLevelItem(i), 0)
        return out

    def save(self, path):
        rows = self.table_rows()
        if path.lower().endswith(".txt"):
            with open(path, "w", encoding="utf-8") as f:
                for r in rows:
                    f.write("\t".join(r) + "\n")
        else:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerows(rows)
        return path

    def ask_save(self):
        asm = ae._asm()
        start = ""
        if asm is not None and asm.Document.FileName:
            import os
            start = os.path.splitext(asm.Document.FileName)[0] + "_AssemblyVisualization.csv"
        path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Save As", start,
                                                         "CSV (Excel) (*.csv);;Text (Tab delimited) (*.txt)")
        if path:
            return self.save(path)
        return None

    def _header_menu(self, pos):
        col = self.table.header().logicalIndexAt(pos)
        self.header_menu(col).exec_(self.table.header().mapToGlobal(pos))

    def _bar_menu(self, pos):
        m = QtWidgets.QMenu(self)
        a = m.addAction("Reset")
        a.triggered.connect(lambda *_: self.slider.setValue(50))
        m.exec_(self.bar.mapToGlobal(pos))

    def _paint(self):
        self.cleanup()
        for it in getattr(self, "items_by_row", {}).values():
            try:
                it.setIcon(0, QtGui.QIcon())
                it.setData(0, Qt.UserRole + 1, None)
            except RuntimeError as _fw_err:
                _fw_log("asmvistab.py:497", _fw_err)
        if not self.colours.isChecked() or not self.rows_:
            return
        vals = [float(r[2] or 0) for r in self.rows_]
        lo, hi = min(vals), max(vals)
        mid = self.slider.value() / 100.0
        for k, (name, q, v, cs) in enumerate(self.rows_):
            t = 0.5 if hi - lo < 1e-12 else remap((float(v or 0) - lo) / (hi - lo), mid)
            colour = ae.ramp(t)
            try:
                it = self.items_by_row.get(id(self.leaf_rows[k]))
                if it is not None:
                    it.setIcon(0, swatch(colour))
                    it.setData(0, Qt.UserRole + 1, colour)
            except Exception as _fw_err:
                _fw_log("asmvistab.py:512", _fw_err)
            for c in cs:
                vo = getattr(c, "ViewObject", None)
                if vo is None or not hasattr(vo, "OverrideMaterial"):
                    continue
                try:
                    if c not in self.saved:
                        self.saved[c] = (vo.OverrideMaterial, vo.ShapeMaterial)
                    mat = App.Material()
                    mat.DiffuseColor = colour + (0.0,)
                    vo.ShapeMaterial = mat
                    vo.OverrideMaterial = True
                except Exception as _fw_err:
                    _fw_log("asmvistab.py:525", _fw_err)

    def close(self):
        close_tab()
        return True


def _pane():
    try:
        return Gui.getMainWindow().findChild(QtWidgets.QWidget, "SWLeftPane")
    except Exception:
        return None


def open_tab():
    """The Assembly Visualization tab, opened and shown (None when the left pane is not there)."""
    from . import leftpane, icons
    pane = _pane()
    if pane is None or not hasattr(pane, "pages"):
        return None
    page = STATE["page"]
    if page is None or PAGE not in pane.pages:
        page = VisualizationTab()
        pane._add_page(PAGE, page)
        if TAB not in leftpane.TABS:
            leftpane.TABS = tuple(leftpane.TABS) + (TAB,)
            pane.header.icons.append(icons.family(TAB[0]))
        STATE["page"] = page
    page.refresh()
    pane._user_page = PAGE
    pane.select_name(PAGE)
    pane.header.update()
    return page


def close_tab():
    from . import leftpane
    page = STATE["page"]
    STATE["page"] = None
    if page is not None:
        page.cleanup()
    pane = _pane()
    if pane is not None and hasattr(pane, "pages"):
        w = pane.pages.pop(PAGE, None)
        if w is not None:
            pane.stack.removeWidget(w)
            w.deleteLater()
        if TAB in leftpane.TABS:
            i = leftpane.TABS.index(TAB)
            leftpane.TABS = tuple(t for t in leftpane.TABS if t != TAB)
            try:
                pane.header.icons.pop(i)
            except Exception as _fw_err:
                _fw_log("asmvistab.py:578", _fw_err)
            pane.header.current = 0
        pane._user_page = "Model"
        pane.select_name("Model")
        pane.header.update()


def is_open():
    return STATE["page"] is not None
