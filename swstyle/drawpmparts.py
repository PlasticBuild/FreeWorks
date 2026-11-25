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
import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import drawings as D

NONE_STYLE = "<NONE>"
NONE_LAYER = "-None-"
LINE_STYLES = ("Solid", "Dashed", "Phantom", "Chain", "Center", "Stitch")
DASHES = {"Solid": "", "Dashed": "2,1", "Phantom": "6,1,1,1,1,1", "Chain": "6,1,1,1", "Center": "8,1.5,1.5,1.5",
          "Stitch": "0.6,0.6"}
THICKNESSES = ("Default", "0.18mm", "0.25mm", "0.35mm", "0.5mm", "0.7mm", "1mm")

# tests answer the dialogs here: {"style_name": str, "save_path": str, "load_path": str, "font": QFont}
ASK = {}


# =========================================================================== store (on the drawing's first sheet)
def _store(doc):
    for o in doc.Objects:
        if o.TypeId == "TechDraw::DrawPage":
            return o
    return None


def _get(doc, prop, default):
    p = _store(doc)
    if p is None or prop not in p.PropertiesList:
        return default
    try:
        return json.loads(getattr(p, prop) or "null") or default
    except ValueError:
        return default


def _set(doc, prop, value, tip):
    p = _store(doc)
    if p is None:
        return
    if prop not in p.PropertiesList:
        p.addProperty("App::PropertyString", prop, "FreeCAD", tip)
        p.setPropertyStatus(prop, "Hidden")
    setattr(p, prop, json.dumps(value))


# =========================================================================== Style
def _option_widgets(panel):
    ""
    skip = getattr(panel, "_style_skip", set())
    out = []
    for w in panel.form.findChildren(QtWidgets.QWidget):
        n = w.objectName() or ""
        if not n.startswith("SW") or n in skip or n.startswith("SWStyle") or n.startswith("SWLayer"):
            continue
        if isinstance(w, (QtWidgets.QPlainTextEdit, QtWidgets.QTextEdit)):
            continue
        if isinstance(w, (QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox, QtWidgets.QLineEdit)) or \
                isinstance(w, QtWidgets.QAbstractButton) and w.isCheckable() or \
                isinstance(w, QtWidgets.QGroupBox) and w.isCheckable():
            out.append(w)
    return out


def snapshot(panel):
    vals = {}
    for w in _option_widgets(panel):
        n = w.objectName()
        if isinstance(w, QtWidgets.QComboBox):
            vals[n] = w.currentText()
        elif isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
            vals[n] = w.value()
        elif isinstance(w, QtWidgets.QLineEdit):
            vals[n] = w.text()
        elif isinstance(w, (QtWidgets.QAbstractButton, QtWidgets.QGroupBox)):
            vals[n] = bool(w.isChecked())
    return vals


def restore(panel, vals):
    for w in _option_widgets(panel):
        n = w.objectName()
        if n not in vals:
            continue
        v = vals[n]
        if isinstance(w, QtWidgets.QComboBox):
            w.setCurrentText(str(v))
        elif isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
            w.setValue(v)
        elif isinstance(w, QtWidgets.QLineEdit):
            w.setText(str(v))
        elif isinstance(w, QtWidgets.QAbstractButton):
            if bool(v) != w.isChecked():
                if w.group() is not None and w.group().exclusive() and not v:
                    continue          # the button that is on in the group switches it off
                w.click()
        elif isinstance(w, QtWidgets.QGroupBox):
            w.setChecked(bool(v))


def styles(doc, kind):
    return _get(doc, "SWAnnotationStyles", {}).get(kind, {})


def save_style(doc, kind, name, vals):
    allst = _get(doc, "SWAnnotationStyles", {})
    allst.setdefault(kind, {})[name] = vals
    _set(doc, "SWAnnotationStyles", allst, "Annotation styles")


def delete_style(doc, kind, name):
    allst = _get(doc, "SWAnnotationStyles", {})
    allst.get(kind, {}).pop(name, None)
    _set(doc, "SWAnnotationStyles", allst, "Annotation styles")


STYLE_BUTTONS = (("Default", "Apply the default attributes", "Std_Refresh"),
                 ("Add", "Add or Update a Style", "list-add"),
                 ("Delete", "Delete a Style", "list-remove"),
                 ("Save", "Save a Style", "document-save"),
                 ("Load", "Load Style", "document-open"))


def style_group(panel, kind=None):
    ""
    kind = kind or panel.TITLE
    box, lay = D._group("Style", panel.form)
    row = QtWidgets.QHBoxLayout()
    icons = {"Default": "TechDraw_Annotation", "Add": "Std_DlgParameter", "Delete": "Std_Delete",
             "Save": "Std_Save", "Load": "Std_Open"}
    for key, tip, theme in STYLE_BUTTONS:
        b = QtWidgets.QToolButton(box)
        b.setObjectName("SWStyle" + key)
        b.setToolTip(tip)
        b.setText(key)

        # the icon theme's
        for name in (icons[key], theme, {"Delete": "edit-delete"}.get(key, "")):
            try:
                ic = QtGui.QIcon(D.pixmap(name)) if name else QtGui.QIcon()
                if ic.isNull() and name:
                    ic = QtGui.QIcon.fromTheme(name)
                if not ic.isNull() and not ic.pixmap(16, 16).isNull():
                    b.setIcon(ic)
                    b.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
                    break
            except Exception as _fw_err:
                _fw_log("drawpmparts.py:168", _fw_err)
        b.clicked.connect(lambda *_, k=key: _style_action(panel, kind, k))
        row.addWidget(b)
    row.addStretch(1)
    lay.addLayout(row)
    panel.style_list = QtWidgets.QComboBox(box)
    panel.style_list.setObjectName("SWStyleList")
    panel.style_list.addItem(NONE_STYLE)
    panel.style_list.addItems(sorted(styles(panel.doc, kind)))
    panel.style_list.activated.connect(lambda *_: _apply_style(panel, kind))
    lay.addWidget(panel.style_list)
    panel.lay.addWidget(box)
    panel._style_kind = kind
    D.after_build(panel, lambda: setattr(panel, "_style_defaults", snapshot(panel)))
    return box


def _apply_style(panel, kind):
    name = panel.style_list.currentText()
    if name == NONE_STYLE:
        return
    vals = styles(panel.doc, kind).get(name)
    if vals:
        restore(panel, vals)


def _style_action(panel, kind, key):
    mw = Gui.getMainWindow()
    lst = panel.style_list
    if key == "Default":
        restore(panel, getattr(panel, "_style_defaults", {}) or {})
        lst.setCurrentIndex(0)
    elif key == "Add":
        cur = lst.currentText()
        name = ASK.pop("style_name", None)
        if name is None:
            name, ok = QtWidgets.QInputDialog.getText(mw, "Add or Update a Style", "Enter a new name or choose a "
                                                      "style name:", text="" if cur == NONE_STYLE else cur)
            if not ok:
                return
        name = name.strip()
        if not name or name == NONE_STYLE:
            return
        save_style(panel.doc, kind, name, snapshot(panel))
        if lst.findText(name) < 0:
            lst.addItem(name)
        lst.setCurrentText(name)
    elif key == "Delete":
        name = lst.currentText()
        if name == NONE_STYLE:
            return
        delete_style(panel.doc, kind, name)
        lst.removeItem(lst.currentIndex())
        lst.setCurrentIndex(0)
    elif key == "Save":
        name = lst.currentText()
        vals = styles(panel.doc, kind).get(name) if name != NONE_STYLE else None
        if vals is None:
            name, vals = "Style", snapshot(panel)
        path = ASK.pop("save_path", None)
        if path is None:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(mw, "Save a Style", name + ".fwstyle",
                                                            "FreeCAD styles (*.fwstyle)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"kind": kind, "name": name, "values": vals}, f, indent=1)
    elif key == "Load":
        path = ASK.pop("load_path", None)
        if path is None:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(mw, "Load Style", "", "FreeCAD styles (*.fwstyle)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as error:
            App.Console.PrintWarning("FreeCAD: Load Style: %s\n" % error)
            return
        name = data.get("name") or "Style"
        save_style(panel.doc, kind, name, data.get("values", {}))
        if lst.findText(name) < 0:
            lst.addItem(name)
        lst.setCurrentText(name)
        restore(panel, data.get("values", {}))


# =========================================================================== Layers
def layers(doc):
    return _get(doc, "SWLayers", [])


def set_layers(doc, lays):
    _set(doc, "SWLayers", lays, "Drawing layers")


def layer(doc, name):
    for L in layers(doc):
        if L.get("name") == name:
            return L
    return None


def current_layer(doc):
    return _get(doc, "SWCurrentLayer", "") or NONE_LAYER


def set_current_layer(doc, name):
    _set(doc, "SWCurrentLayer", name if name != NONE_LAYER else "", "Current layer")


_COLOUR = re.compile(r'(stroke|fill)="#(?:000|000000|0000ee)"')


def _plain(obj):
    """The object's SVG without the layer's look (kept the first time a layer is applied)."""
    if "SWLayerPlain" in obj.PropertiesList and getattr(obj, "SWLayerSymbol", "") == obj.Symbol:
        return obj.SWLayerPlain
    return obj.Symbol


def apply_layer(obj, name=None):
    """Put obj on layer name (None: keep its layer) and draw it in the layer's colour, line style and thickness;
    hidden while the layer is off."""
    doc = obj.Document
    if name is not None:
        if "SWLayer" not in obj.PropertiesList:
            obj.addProperty("App::PropertyString", "SWLayer", "FreeCAD", "Layer")
        obj.SWLayer = "" if name == NONE_LAYER else name
    L = layer(doc, getattr(obj, "SWLayer", "")) if getattr(obj, "SWLayer", "") else None
    if obj.TypeId == "TechDraw::DrawViewSymbol":
        plain = _plain(obj)
        svg = plain
        if L is not None:
            col = L.get("color", "#000000")
            svg = re.sub(r'stroke="#(?:000|000000)"', 'stroke="%s"' % col, svg)
            svg = re.sub(r'fill="#(?:000|000000)"', 'fill="%s"' % col, svg)
            svg = re.sub(r"<text (?![^>]*fill=)", '<text fill="%s" ' % col, svg)
            dash = DASHES.get(L.get("style", "Solid"), "")
            if dash:
                svg = svg.replace('stroke="%s"' % col, 'stroke="%s" stroke-dasharray="%s"' % (col, dash))
            th = L.get("thickness", "Default")
            if th != "Default":
                svg = re.sub(r'stroke-width="[0-9.]+"', 'stroke-width="%s"' % th[:-2], svg)
        for p, t in (("SWLayerPlain", "SVG without the layer look"), ("SWLayerSymbol", "SVG with it")):
            if p not in obj.PropertiesList:
                obj.addProperty("App::PropertyString", p, "FreeCAD", t)
                obj.setPropertyStatus(p, "Hidden")
        obj.SWLayerPlain = plain
        if obj.Symbol != svg:
            obj.Symbol = svg
        obj.SWLayerSymbol = svg
    else:
        c = QtGui.QColor(L.get("color", "#000000") if L is not None else "#000000")
        rgb = (c.redF(), c.greenF(), c.blueF())
        th = L.get("thickness", "Default") if L is not None else "Default"
        try:
            if hasattr(obj, "TextColor"):              # tables (TechDraw spreadsheet views)
                obj.TextColor = rgb
                if th != "Default" and hasattr(obj, "LineWidth"):
                    obj.LineWidth = float(th[:-2])
            else:
                vo = obj.ViewObject
                if hasattr(vo, "Color"):
                    vo.Color = rgb
                if th != "Default" and hasattr(vo, "LineWidth"):
                    vo.LineWidth = float(th[:-2])
        except Exception as _fw_err:
            _fw_log("drawpmparts.py:335", _fw_err)
    try:
        obj.Visibility = True if L is None else bool(L.get("on", True))
    except Exception:
        try:
            obj.ViewObject.Visibility = True if L is None else bool(L.get("on", True))
        except Exception as _fw_err:
            _fw_log("drawpmparts.py:342", _fw_err)
    return obj


STYLE_NUMBER = {"Solid": 1, "Dashed": 2, "Phantom": 5, "Chain": 4, "Center": 4, "Stitch": 3}


def layer_cosmetic(view, tag, name):
    """A cosmetic line of view (center marks, centerlines) onto layer name: its colour, style, weight, shown."""
    tags = [t for t in list(getattr(view, "SWLayerTags", []) or []) if not t.startswith(tag + "|")]
    if name and name != NONE_LAYER:
        tags.append("%s|%s" % (tag, name))
    if "SWLayerTags" not in view.PropertiesList:
        view.addProperty("App::PropertyStringList", "SWLayerTags", "FreeCAD", "cosmetic line tag|layer")
    view.SWLayerTags = tags
    _look_cosmetic(view, tag, layer(view.Document, name))


def _look_cosmetic(view, tag, L):
    try:
        ce = view.getCosmeticEdge(tag)
    except Exception as _fw_err:
        _fw_log("drawpmparts.py:365", _fw_err)
        return
    if ce is None:
        return
    try:
        raw = ce.Format
        keys = ("style", "weight", "color", "visible")
        fmt = dict(raw) if isinstance(raw, dict) else dict(zip(keys, list(raw)))
        if L is not None:
            c = QtGui.QColor(L.get("color", "#000000"))
            fmt["color"] = (c.redF(), c.greenF(), c.blueF(), 1.0)
            th = L.get("thickness", "Default")
            if th != "Default":
                fmt["weight"] = float(th[:-2])
            st = L.get("style", "Solid")
            if st != "Solid":
                fmt["style"] = STYLE_NUMBER.get(st, fmt.get("style", 1))
            fmt["visible"] = bool(L.get("on", True))
        ce.Format = fmt if isinstance(raw, dict) else tuple(fmt[k] for k in keys[:len(raw)])
        if hasattr(view, "replaceCosmeticEdge"):
            view.replaceCosmeticEdge(ce)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: layer on cosmetic line: %s\n" % error)


def refresh_layers(doc):
    for o in doc.Objects:
        if getattr(o, "SWLayer", ""):
            apply_layer(o)
        for t in list(getattr(o, "SWLayerTags", []) or []):
            tag, _, name = t.partition("|")
            _look_cosmetic(o, tag, layer(doc, name))
    doc.recompute()


def layer_group(panel):
    ""
    box, lay = D._group("Layer", panel.form)
    row = QtWidgets.QHBoxLayout()
    panel.layer = QtWidgets.QComboBox(box)
    panel.layer.setObjectName("SWLayerCombo")
    fill_layers(panel.layer, panel.doc)
    panel.layer.activated.connect(lambda *_: _relayer(panel))
    row.addWidget(panel.layer, 1)
    b = QtWidgets.QToolButton(box)
    b.setObjectName("SWLayerProperties")
    b.setToolTip("Layer Properties")
    b.setText("...")
    b.clicked.connect(lambda *_: (LayerDialog(panel.doc).exec_(), fill_layers(panel.layer, panel.doc,
                                                                           panel.layer.currentText())))
    row.addWidget(b)
    lay.addLayout(row)
    panel.lay.addWidget(box)
    return box


def fill_layers(combo, doc, keep=None):
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(NONE_LAYER)
    combo.addItems([L["name"] for L in layers(doc)])
    combo.setCurrentText(keep if keep and combo.findText(keep) >= 0 else current_layer(doc))
    combo.blockSignals(False)


def _relayer(panel):
    for o in getattr(panel, "made", []):
        try:
            apply_layer(o, panel.layer.currentText())
        except Exception as _fw_err:
            _fw_log("drawpmparts.py:433", _fw_err)
    panel.doc.recompute()


def layer_of(panel):
    return panel.layer.currentText() if getattr(panel, "layer", None) is not None else current_layer(panel.doc)


def finish_layers(panel):
    """At OK: every item the PM made goes on the chosen layer (and keeps its look after text edits)."""
    name = layer_of(panel)
    for o in getattr(panel, "made", []):
        try:
            if o.Document is not None and (name != NONE_LAYER or getattr(o, "SWLayer", "")):
                apply_layer(o, name)
        except Exception as _fw_err:
            _fw_log("drawpmparts.py:449", _fw_err)


class LayerDialog(QtWidgets.QDialog):
    ""

    COLS = ("", "Name", "Description", "On/Off", "Print", "Color", "Style", "Thickness")

    def __init__(self, doc, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc
        self.setObjectName("SWLayerDialog")
        self.setWindowTitle("Layers")
        lay = QtWidgets.QHBoxLayout(self)
        self.table = QtWidgets.QTableWidget(0, len(self.COLS), self)
        self.table.setObjectName("SWLayerTable")
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.cellClicked.connect(self.cell_clicked)
        self.table.setMinimumWidth(560)
        lay.addWidget(self.table, 1)
        col = QtWidgets.QVBoxLayout()
        for text, fn in (("OK", self.ok), ("Cancel", self.reject), ("New", self.new), ("Delete", self.delete),
                         ("Move", self.move)):
            b = QtWidgets.QPushButton(text, self)
            b.setObjectName("SWLayer" + text)
            b.clicked.connect(fn)
            col.addWidget(b)
        col.addStretch(1)
        lay.addLayout(col)
        self.current = current_layer(doc)
        for L in layers(doc):
            self.add_row(L)
        self.mark()

    def add_row(self, L):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(""))
        self.table.item(r, 0).setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
        self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(L.get("name", "")))
        self.table.item(r, 1).setData(QtCore.Qt.UserRole, L.get("name", ""))   # the name it had (renames)
        self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(L.get("description", "")))
        on = QtWidgets.QTableWidgetItem("On" if L.get("on", True) else "Off")
        on.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
        self.table.setItem(r, 3, on)
        pr = QtWidgets.QTableWidgetItem("Print" if L.get("print", True) else "No print")
        pr.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
        self.table.setItem(r, 4, pr)
        c = QtWidgets.QTableWidgetItem(L.get("color", "#000000"))
        c.setBackground(QtGui.QColor(L.get("color", "#000000")))
        c.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
        self.table.setItem(r, 5, c)
        st = QtWidgets.QComboBox(self.table)
        st.setObjectName("SWLayerStyle%d" % r)
        st.addItems(LINE_STYLES)
        st.setCurrentText(L.get("style", "Solid"))
        self.table.setCellWidget(r, 6, st)
        th = QtWidgets.QComboBox(self.table)
        th.setObjectName("SWLayerThickness%d" % r)
        th.addItems(THICKNESSES)
        th.setCurrentText(L.get("thickness", "Default"))
        self.table.setCellWidget(r, 7, th)
        return r

    def rows(self):
        out = []
        for r in range(self.table.rowCount()):
            out.append({"name": self.table.item(r, 1).text().strip(),
                        "description": self.table.item(r, 2).text(),
                        "on": self.table.item(r, 3).text() == "On",
                        "print": self.table.item(r, 4).text() == "Print",
                        "color": self.table.item(r, 5).text(),
                        "style": self.table.cellWidget(r, 6).currentText(),
                        "thickness": self.table.cellWidget(r, 7).currentText()})
        return out

    def mark(self):
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setText("→" if self.table.item(r, 1).text() == self.current else "")

    def cell_clicked(self, r, c):
        if c == 0:
            self.current = self.table.item(r, 1).text()
            self.mark()
        elif c == 3:
            it = self.table.item(r, 3)
            it.setText("Off" if it.text() == "On" else "On")
        elif c == 4:
            it = self.table.item(r, 4)
            it.setText("No print" if it.text() == "Print" else "Print")
        elif c == 5:
            it = self.table.item(r, 5)
            col = ASK.pop("color", None)
            if col is None:
                q = QtWidgets.QColorDialog.getColor(QtGui.QColor(it.text()), self, "Color")
                col = q.name() if q.isValid() else None
            if col:
                it.setText(col)
                it.setBackground(QtGui.QColor(col))

    def new(self):
        names = {L["name"] for L in self.rows()}
        n = 0
        while "Layer%d" % n in names if n else "Layer" in names:
            n += 1
        name = "Layer%d" % n if n else "Layer"
        r = self.add_row({"name": name})
        self.current = name
        self.mark()
        self.table.selectRow(r)
        self.table.editItem(self.table.item(r, 1))

    def delete(self):
        r = self.table.currentRow()
        if r < 0:
            return
        if self.table.item(r, 1).text() == self.current:
            self.current = NONE_LAYER
        self.table.removeRow(r)
        self.mark()

    def move(self):
        """Move: the selected items in the drawing go to the highlighted layer."""
        r = self.table.currentRow()
        if r < 0:
            return
        self.save()
        name = self.table.item(r, 1).text()
        for s in Gui.Selection.getSelection():
            if s.isDerivedFrom("TechDraw::DrawView"):
                apply_layer(s, name)
        self.doc.recompute()

    def save(self):
        for r in range(self.table.rowCount()):        # the arrow follows its row through a rename
            if self.table.item(r, 0).text() == "\u2192":
                self.current = self.table.item(r, 1).text().strip()
        rows = [L for L in self.rows() if L["name"]]
        old = {L["name"] for L in layers(self.doc)}
        renamed = {}
        for r in range(self.table.rowCount()):
            was = self.table.item(r, 1).data(QtCore.Qt.UserRole) or ""
            now = self.table.item(r, 1).text().strip()
            if was and now and was != now:
                renamed[was] = now
        if renamed:
            for o in self.doc.Objects:
                if getattr(o, "SWLayer", "") in renamed:
                    o.SWLayer = renamed[o.SWLayer]
                tags = list(getattr(o, "SWLayerTags", []) or [])
                if tags:
                    new = []
                    for t in tags:
                        tag, _, name = t.partition("|")
                        new.append("%s|%s" % (tag, renamed.get(name, name)))
                    if new != tags:
                        o.SWLayerTags = new
            for r in range(self.table.rowCount()):
                self.table.item(r, 1).setData(QtCore.Qt.UserRole, self.table.item(r, 1).text().strip())
            old = {renamed.get(n, n) for n in old}
        set_layers(self.doc, rows)
        set_current_layer(self.doc, self.current if self.current in {L["name"] for L in rows} else NONE_LAYER)
        gone = old - {L["name"] for L in rows}
        for o in self.doc.Objects:
            if getattr(o, "SWLayer", "") in gone:
                apply_layer(o, NONE_LAYER)
        refresh_layers(self.doc)

    def ok(self):
        self.save()
        self.accept()


def non_printing(doc):
    """The drawing items on layers set not to print."""
    off = {L["name"] for L in layers(doc) if not L.get("print", True)}
    return [o for o in doc.Objects if getattr(o, "SWLayer", "") in off] if off else []


def print_drawing(doc, command):
    """Print / Print Preview / PDF: items on layers set not to print are hidden while command runs."""
    hide = []
    for o in non_printing(doc):
        try:
            if o.ViewObject is not None and o.ViewObject.Visibility:
                o.ViewObject.Visibility = False
                hide.append(o)
        except Exception as _fw_err:
            _fw_log("drawpmparts.py:639", _fw_err)
    try:
        Gui.runCommand(command, 0)
    finally:
        for o in hide:
            try:
                o.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("drawpmparts.py:647", _fw_err)


# =========================================================================== Format (font)
def format_group(panel, title="Text Format", box=None, lay=None):
    """Use document font (on) and Font... (live when it is off)."""
    own = box is None
    if own:
        box, lay = D._group(title, panel.form)
    panel.doc_font = QtWidgets.QCheckBox("Use document font", box)
    panel.doc_font.setObjectName("SWFormatDocFont")
    panel.doc_font.setChecked(True)
    panel.font_button = QtWidgets.QPushButton("Font...", box)
    panel.font_button.setObjectName("SWFormatFont")
    panel.font_family = QtWidgets.QLineEdit("osifont", box)
    panel.font_family.setObjectName("SWFormatFamily")
    panel.font_family.hide()
    panel.doc_font.toggled.connect(lambda *_: _refont(panel))
    panel.font_button.clicked.connect(lambda *_: _pick_font(panel))
    lay.addWidget(panel.doc_font)
    lay.addWidget(panel.font_button)
    if own:
        panel.lay.addWidget(box)
    return box


def font_of(panel):
    if getattr(panel, "doc_font", None) is None or panel.doc_font.isChecked():
        return "osifont, Arial"
    return panel.font_family.text() or "osifont, Arial"


FONT_STYLES = ("Regular", "Italic", "Bold", "Bold Italic")
FONT_POINTS = ("8", "9", "10", "11", "12", "14", "16", "18", "20", "24", "28", "36", "48", "72")
PT = 25.4 / 72.0          # one point in mm


class ChooseFontDialog(QtWidgets.QDialog):
    ""


    def __init__(self, family="osifont", style="Regular", height=3.5, space=0.0, strike=False, underline=False,
                 parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWChooseFont")
        self.setWindowTitle("Choose Font")
        lay = QtWidgets.QGridLayout(self)
        self.family = QtWidgets.QFontComboBox(self)
        self.family.setObjectName("SWChooseFontFamily")
        self.family.setCurrentFont(QtGui.QFont(family))
        self.style = QtWidgets.QListWidget(self)
        self.style.setObjectName("SWChooseFontStyle")
        self.style.addItems(FONT_STYLES)
        self.style.setCurrentRow(FONT_STYLES.index(style) if style in FONT_STYLES else 0)
        self.style.setMaximumHeight(90)
        lay.addWidget(QtWidgets.QLabel("Font:", self), 0, 0)
        lay.addWidget(self.family, 1, 0)
        lay.addWidget(QtWidgets.QLabel("Font Style:", self), 0, 1)
        lay.addWidget(self.style, 1, 1)
        hbox = QtWidgets.QGroupBox("Height:", self)
        hl = QtWidgets.QGridLayout(hbox)
        self.units = QtWidgets.QRadioButton("Units", hbox)
        self.units.setObjectName("SWChooseFontUnits")
        self.height = QtWidgets.QDoubleSpinBox(hbox)
        self.height.setObjectName("SWChooseFontHeight")
        self.height.setRange(0.5, 100)
        self.height.setDecimals(2)
        self.height.setSuffix("mm")
        self.height.setValue(height)
        self.points_on = QtWidgets.QRadioButton("Points", hbox)
        self.points_on.setObjectName("SWChooseFontPointsOn")
        self.points = QtWidgets.QComboBox(hbox)
        self.points.setObjectName("SWChooseFontPoints")
        self.points.setEditable(True)
        self.points.addItems(FONT_POINTS)
        self.points.setCurrentText("%g" % round(height / PT))
        self.units.setChecked(True)
        self.space = QtWidgets.QDoubleSpinBox(hbox)
        self.space.setObjectName("SWChooseFontSpace")
        self.space.setRange(0.0, 20.0)
        self.space.setDecimals(2)
        self.space.setSuffix("mm")
        self.space.setValue(space)
        hl.addWidget(self.units, 0, 0)
        hl.addWidget(self.height, 0, 1)
        hl.addWidget(QtWidgets.QLabel("Space:", hbox), 1, 0)
        hl.addWidget(self.space, 1, 1)
        hl.addWidget(self.points_on, 2, 0)
        hl.addWidget(self.points, 2, 1)
        lay.addWidget(hbox, 2, 0)
        ebox = QtWidgets.QGroupBox("Effects", self)
        el = QtWidgets.QVBoxLayout(ebox)
        self.strike = QtWidgets.QCheckBox("Strikeout", ebox)
        self.strike.setObjectName("SWChooseFontStrikeout")
        self.strike.setChecked(strike)
        self.underline = QtWidgets.QCheckBox("Underline", ebox)
        self.underline.setObjectName("SWChooseFontUnderline")
        self.underline.setChecked(underline)
        el.addWidget(self.strike)
        el.addWidget(self.underline)
        lay.addWidget(ebox, 2, 1)
        self.sample = QtWidgets.QLabel("AaBbYyZz", self)
        self.sample.setObjectName("SWChooseFontSample")
        self.sample.setAlignment(QtCore.Qt.AlignCenter)
        self.sample.setMinimumHeight(50)
        self.sample.setFrameShape(QtWidgets.QFrame.Box)
        lay.addWidget(self.sample, 3, 0, 1, 2)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb, 4, 0, 1, 2)
        self.units.toggled.connect(self._units)
        self._units(True)
        for sig in (self.family.currentFontChanged, self.style.currentRowChanged, self.height.valueChanged,
                    self.points.currentTextChanged, self.units.toggled, self.strike.toggled, self.underline.toggled,
                    self.space.valueChanged):
            sig.connect(lambda *_: self._show())
        self._show()

    def _units(self, on):
        # NO DEAD CONTROLS: both boxes stay live; using one picks its radio button
        if not getattr(self, "_fw_live", False):
            self._fw_live = True
            from . import drawlive as DL
            DL.sets(self.units, True, self.height)
            DL.sets(self.points_on, True, self.points)

    def height_mm(self):
        if self.units.isChecked():
            return float(self.height.value())
        try:
            return round(float(self.points.currentText()) * PT, 3)
        except ValueError:
            return float(self.height.value())

    def result(self):
        return dict(family=self.family.currentFont().family(), style=self.style.currentItem().text()
                    if self.style.currentItem() else "Regular", height=self.height_mm(), space=self.space.value(),
                    strike=self.strike.isChecked(), underline=self.underline.isChecked())

    def _show(self):
        r = self.result()
        f = QtGui.QFont(r["family"])
        f.setBold("Bold" in r["style"])
        f.setItalic("Italic" in r["style"])
        f.setStrikeOut(r["strike"])
        f.setUnderline(r["underline"])
        f.setPointSizeF(max(4.0, min(40.0, r["height"] / PT)))
        f.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, r["space"] / PT)
        self.sample.setFont(f)


def font_look(panel):
    """The picked font's style, space and effects as SVG text attributes ("" with Use document font)."""
    if getattr(panel, "doc_font", None) is None or panel.doc_font.isChecked():
        return ""
    f = getattr(panel, "font_more", None) or {}
    out = ""
    if "Bold" in f.get("style", ""):
        out += ' font-weight="bold"'
    if "Italic" in f.get("style", ""):
        out += ' font-style="italic"'
    if f.get("space"):
        out += ' letter-spacing="%g"' % float(f["space"])
    deco = " ".join(k for k, on in (("line-through", f.get("strike")), ("underline", f.get("underline"))) if on)
    if deco:
        out += ' text-decoration="%s"' % deco
    return out


def _pick_font(panel):
    f = ASK.pop("font", None)
    size = getattr(panel, "font_size", None)
    if f is None:
        more = getattr(panel, "font_more", None) or {}
        dlg = ChooseFontDialog(panel.font_family.text(), more.get("style", "Regular"),
                               size.value() if size is not None else 3.5, more.get("space", 0.0),
                               more.get("strike", False), more.get("underline", False))
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return
        f = dlg.result()
    if isinstance(f, QtGui.QFont):               # older callers: a QFont
        f = dict(family=f.family(), height=f.pointSizeF() * 0.3528 if f.pointSizeF() > 0 else None,
                 style=("Bold " if f.bold() else "") + ("Italic" if f.italic() else "") or "Regular")
    panel.font_family.setText(f["family"])
    panel.font_more = dict(style=(f.get("style") or "Regular").strip(), space=f.get("space", 0.0),
                           strike=f.get("strike", False), underline=f.get("underline", False))
    if size is not None and f.get("height"):
        size.setValue(round(float(f["height"]), 2))
    doc_font = getattr(panel, "doc_font", None)
    if doc_font is not None and doc_font.isChecked():
        doc_font.setChecked(False)           # a font picked turns Use document font off (the button stays live)
    _refont(panel)


def _refont(panel):
    fn = getattr(panel, "retext", None)
    if fn is not None:
        fn()


# =========================================================================== command
class _LayerCommand:
    def GetResources(self):
        return {"MenuText": "Layer Properties", "ToolTip": "Adds, changes and deletes the drawing's layers; the arrow "
                "marks the layer new annotations go on.", "Pixmap": D.pixmap("TechDraw_ToggleFrame")}

    def IsActive(self):
        return D.active_page() is not None

    def Activated(self):
        page = D.active_page()
        if page is not None:
            LayerDialog(page.Document).exec_()


class _PrintCommand:
    """Print / Print Preview on a drawing: the layers set not to print are left out."""

    def __init__(self, which):
        self.which = which

    def GetResources(self):
        return {"MenuText": "Print..." if self.which == "Print" else "Print Preview...",
                "ToolTip": "Prints the drawing; layers set not to print are left out." if self.which == "Print"
                else "Shows the drawing as it will print; layers set not to print are left out.",
                "Pixmap": self.icon()}

    def icon(self):
        name = "document-print" if self.which == "Print" else "document-print-preview"
        for pix in (D.pixmap(name), ":/icons/%s.svg" % name, D.pixmap("TechDraw_PrintAll")):
            if pix and QtCore.QFile.exists(pix):
                return pix
        return D.pixmap("TechDraw_PageDefault")

    def IsActive(self):
        return True

    def target(self):
        for name in ("SWStyle_" + self.which, "Std_" + self.which):
            if name in Gui.listCommands():
                return name
        return None

    def Activated(self):
        cmd = self.target()
        page = D.active_page()
        if page is not None and sheet_in_front(page) and print_sheet(page, self.which):
            return
        if cmd is None:
            return
        if page is None:
            Gui.runCommand(cmd, 0)
        else:
            print_drawing(page.Document, cmd)


def sheet_in_front(page):
    try:
        from . import drawselect
        return drawselect.sheet_in_front()
    except Exception:
        return D.page_view(page) is not None


def sheet_image(page, width, height):
    """The sheet drawn at width x height pixels on white (no selection highlight, no grid), as it prints."""
    import TechDrawGui
    scene = TechDrawGui.getSceneForPage(page)
    w, h = D.sheet_size(page)
    image = QtGui.QImage(max(int(width), 1), max(int(height), 1), QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor("white"))
    picked = [it for it in scene.selectedItems()]
    for it in picked:
        it.setSelected(False)
    grid = False
    try:
        grid = bool(page.ViewObject.ShowGrid)
        if grid:
            page.ViewObject.ShowGrid = False
            QtWidgets.QApplication.processEvents()
    except Exception as _fw_err:
        _fw_log("drawpmparts.py:924", _fw_err)
    painter = QtGui.QPainter(image)
    try:
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        src = QtCore.QRectF(D.to_scene(0, h), D.to_scene(w, 0))
        scene.render(painter, QtCore.QRectF(0, 0, image.width(), image.height()), src, QtCore.Qt.KeepAspectRatio)
    finally:
        painter.end()
        if grid:
            page.ViewObject.ShowGrid = True
        for it in picked:
            try:
                it.setSelected(True)
            except Exception as _fw_err:
                _fw_log("drawpmparts.py:938", _fw_err)
    return image


def print_sheet(page, which="Print"):
    """Print / Print Preview of the sheet in front through the add-on's print box (filecmds), with the sheet as
    the page picture in place of the 3D view's; layers set not to print are left out."""
    try:
        from . import filecmds
    except Exception:
        return False
    original = getattr(filecmds, "view_image", None)
    box = getattr(filecmds, "PrintDialog" if which == "Print" else "PrintPreviewDialog", None)
    if original is None or box is None:
        return False

    def view_image(width, height):
        image = sheet_image(page, width, height)
        try:
            if filecmds.page_settings()["color"] == "Black and white":
                image = image.convertToFormat(QtGui.QImage.Format_Grayscale8).convertToFormat(
                    QtGui.QImage.Format_RGB32)
        except Exception as _fw_err:
            _fw_log("drawpmparts.py:961", _fw_err)
        return image
    hide = []
    for o in non_printing(page.Document):
        try:
            if o.ViewObject is not None and o.ViewObject.Visibility:
                o.ViewObject.Visibility = False
                hide.append(o)
        except Exception as _fw_err:
            _fw_log("drawpmparts.py:970", _fw_err)
    filecmds.view_image = view_image
    try:
        box().exec()
        if which != "Print":
            # Print Preview's Print button opens the print box a moment after the preview closes
            QtWidgets.QApplication.processEvents()
            for _ in range(10):
                QtWidgets.QApplication.processEvents()
    finally:
        filecmds.view_image = original
        for o in hide:
            try:
                o.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("drawpmparts.py:985", _fw_err)
    return True


# =========================================================================== the Layer toolbar
LAYER_BAR = "SWLayerToolbar"


class LayerBar(QtWidgets.QToolBar):
    ""


    def __init__(self, parent):
        super().__init__("Layer", parent)
        self.setObjectName(LAYER_BAR)
        self.button = QtWidgets.QToolButton(self)
        self.button.setObjectName("SWLayerBarProperties")
        self.button.setToolTip("Layer Properties")
        try:
            self.button.setIcon(QtGui.QIcon(D.pixmap("TechDraw_ToggleFrame")))
        except Exception:
            self.button.setText("Layers")
        self.button.clicked.connect(self.properties)
        self.addWidget(self.button)
        self.combo = QtWidgets.QComboBox(self)
        self.combo.setObjectName("SWLayerBarCombo")
        self.combo.setMinimumWidth(140)
        self.combo.activated.connect(self.picked)
        self.addWidget(self.combo)
        self.key = None

    def items(self):
        return [o for o in Gui.Selection.getSelection() if o.isDerivedFrom("TechDraw::DrawView")
                and not o.isDerivedFrom("TechDraw::DrawPage")]

    def refresh(self, doc):
        sel = self.items()
        names = [L["name"] for L in layers(doc)]
        shown = getattr(sel[0], "SWLayer", "") or NONE_LAYER if sel else current_layer(doc)
        key = (doc.Name, tuple(names), shown)
        if key == self.key or self.combo.view().isVisible():
            return
        self.key = key
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(NONE_LAYER)
        self.combo.addItems(names)
        self.combo.setCurrentText(shown)
        self.combo.blockSignals(False)

    def picked(self, *_):
        page = D.active_page()
        if page is None:
            return
        doc = page.Document
        name = self.combo.currentText()
        sel = self.items()
        if sel:
            doc.openTransaction("Change Layer")
            try:
                for o in sel:
                    apply_layer(o, name)
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
            doc.recompute()
        else:
            set_current_layer(doc, name)
        self.key = None

    def properties(self):
        page = D.active_page()
        if page is not None:
            LayerDialog(page.Document).exec_()
            self.key = None


def layer_bar():
    mw = Gui.getMainWindow()
    bar = mw.findChild(QtWidgets.QToolBar, LAYER_BAR)
    if bar is None:
        bar = LayerBar(mw)
        mw.addToolBar(bar)
        bar.hide()
    return bar


def _bar_tick():
    ""

    try:
        from . import drawdocprops
        drawdocprops.sync_active()
    except Exception as _fw_err:
        _fw_log("drawpmparts.py:1076", _fw_err)
    try:
        bar = layer_bar()
        if not bar.isVisible():
            return
        page = D.active_page() if D.in_drawing() else None
        bar.setEnabled(page is not None)
        if page is not None:
            bar.refresh(page.Document)
    except Exception as _fw_err:
        _fw_log("drawpmparts.py:1086", _fw_err)


_TIMER = []


def register():
    if "FreeWorks_DrawLayerProperties" not in Gui.listCommands():
        Gui.addCommand("FreeWorks_DrawLayerProperties", _LayerCommand())
    for which in ("Print", "PrintPreview"):
        if "FreeWorks_Draw" + which not in Gui.listCommands():
            Gui.addCommand("FreeWorks_Draw" + which, _PrintCommand(which))
    if not _TIMER:
        layer_bar()
        t = QtCore.QTimer(Gui.getMainWindow())
        t.timeout.connect(_bar_tick)
        t.start(600)
        _TIMER.append(t)
