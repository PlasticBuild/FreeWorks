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
import os

TABLES = {}
DEFAULT_RADII = (0.5, 0.8, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0)
K_AIR_BEND = 0.44


def _rows(pairs):
    out = {}
    for gauge, t in pairs:
        radii = [r for r in DEFAULT_RADII if r >= round(t * 0.5, 1)] or [DEFAULT_RADII[-1]]
        out["Gauge %s" % gauge] = {"thickness": t, "radii": radii[:5], "k": K_AIR_BEND}
    return out


TABLES["Steel (Manufacturers' Standard Gauge)"] = _rows([
    (3, 6.073), (4, 5.695), (5, 5.314), (6, 4.935), (7, 4.554), (8, 4.176), (9, 3.797), (10, 3.416),
    (11, 3.038), (12, 2.657), (13, 2.278), (14, 1.897), (15, 1.709), (16, 1.519), (17, 1.367), (18, 1.214),
    (19, 1.062), (20, 0.912), (21, 0.836), (22, 0.759), (23, 0.683), (24, 0.607), (25, 0.531), (26, 0.455),
    (27, 0.417), (28, 0.378)])
TABLES["Aluminum (Brown & Sharpe)"] = _rows([
    (8, 3.264), (9, 2.906), (10, 2.588), (11, 2.305), (12, 2.053), (13, 1.828), (14, 1.628), (16, 1.291),
    (18, 1.024), (20, 0.812), (22, 0.644), (24, 0.511)])
TABLES["Stainless Steel"] = _rows([
    (10, 3.571), (11, 3.175), (12, 2.778), (14, 1.984), (16, 1.587), (18, 1.270), (20, 0.953), (22, 0.794),
    (24, 0.635), (26, 0.476)])

# material name (FreeCAD's library) -> gauge table
MATERIAL_TABLES = (("stainless", "Stainless Steel"), ("alumin", "Aluminum (Brown & Sharpe)"),
                   ("steel", "Steel (Manufacturers' Standard Gauge)"))


def names():
    return list(TABLES)


def table(name):
    return TABLES.get(name)


def gauges(name):
    t = TABLES.get(name) or {}
    return list(t)


def row(name, gauge):
    return (TABLES.get(name) or {}).get(gauge)


def nearest(name, thickness):
    """The gauge of the table closest to a thickness."""
    t = TABLES.get(name) or {}
    return min(t, key=lambda g: abs(t[g]["thickness"] - thickness)) if t else ""


def load(path):
    """Reads a CSV gauge table (Gauge, Thickness, Radius, K-Factor) and adds it under the file's name."""
    rows = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for rec in csv.DictReader(f):
            keys = {k.strip().lower(): (v or "").strip() for k, v in rec.items() if k}
            gauge = keys.get("gauge")
            if not gauge:
                continue
            try:
                t = float(keys.get("thickness", ""))
            except ValueError:
                continue
            radii = []
            for part in (keys.get("radius") or keys.get("radii") or "").replace(",", ";").split(";"):
                try:
                    radii.append(float(part))
                except ValueError as _fw_err:
                    _fw_log("smgauge.py:97", _fw_err)
            try:
                k = float(keys.get("k-factor") or keys.get("k") or K_AIR_BEND)
            except ValueError:
                k = K_AIR_BEND
            label = gauge if not gauge.replace(".", "").isdigit() else "Gauge %s" % gauge
            rows[label] = {"thickness": t, "radii": radii or [t], "k": k}
    if not rows:
        raise ValueError("No gauges in %s: it needs the columns Gauge, Thickness, Radius and K-Factor."
                         % os.path.basename(path))
    name = os.path.splitext(os.path.basename(path))[0]
    TABLES[name] = rows
    return name


def material_of(obj):
    """The material name of the body obj is in (or of obj), else ""."""
    for o in [p for p in getattr(obj, "InList", []) if p.TypeId == "PartDesign::Body"] + [obj]:
        mat = getattr(o, "ShapeMaterial", None)
        name = getattr(mat, "Name", "") if mat is not None else ""
        if name and name.lower() != "default":
            return name
    return ""


def table_for_material(name):
    low = (name or "").lower()
    return next((t for key, t in MATERIAL_TABLES if key in low), None)


class GaugeRows:
    """Sheet Metal Gauges and Sheet Metal Parameters From Material for a PM whose thickness, radius and
    K-Factor boxes are already built: the table, its gauge and the gauge's radius drive those boxes
    (Override thickness / Override radius free them). material_check may be None (Convert to Sheet Metal has
    no From Material box). Kept on obj as SWUseMaterial, SWUseGauge,
    SWGaugeTable, SWGaugeFile, SWGauge, SWOverrideThickness and SWOverrideRadius."""

    PROPS = (("SWUseMaterial", "App::PropertyBool", False), ("SWUseGauge", "App::PropertyBool", False),
             ("SWGaugeTable", "App::PropertyString", ""), ("SWGaugeFile", "App::PropertyString", ""),
             ("SWGauge", "App::PropertyString", ""), ("SWOverrideThickness", "App::PropertyBool", False),
             ("SWOverrideRadius", "App::PropertyBool", False))

    def __init__(self, obj, material_check, gauge_check, gauge_layout, params_layout, thick, radius, kfactor,
                 changed):
        from PySide import QtWidgets
        for name, kind, default in self.PROPS:
            if name not in obj.PropertiesList:
                obj.addProperty(kind, name, "Sheet Metal", "Sheet metal gauge")
                setattr(obj, name, default)
        self.obj, self.material, self.gauge = obj, material_check, gauge_check
        self.thick, self.radius, self.kfactor, self.changed = thick, radius, kfactor, changed
        self.busy = True
        if obj.SWGaugeFile and obj.SWGaugeTable not in names():
            try:
                load(obj.SWGaugeFile)
            except Exception as _fw_err:
                _fw_log("smgauge.py:153", _fw_err)
        self.table = QtWidgets.QComboBox()
        self.table.setObjectName("SWSMGaugeTable")
        self.table.addItems(names())
        self.table.setCurrentText(obj.SWGaugeTable if obj.SWGaugeTable in names() else names()[0])
        self.browse = QtWidgets.QPushButton("Browse...")
        self.browse.setObjectName("SWSMGaugeBrowse")
        gauge_layout.addRow(self.table)
        gauge_layout.addRow(self.browse)
        self.number = QtWidgets.QComboBox()
        self.number.setObjectName("SWSMGaugeNo")
        self.override_t = QtWidgets.QCheckBox("Override thickness")
        self.override_t.setObjectName("SWSMOverrideThickness")
        self.override_t.setChecked(bool(obj.SWOverrideThickness))
        self.radii = QtWidgets.QComboBox()
        self.radii.setObjectName("SWSMGaugeRadius")
        self.radii.setToolTip("The bend radii of the gauge. In the built-in tables the radii and the K-Factor are defaults "
                              "(the gauge thicknesses are the published ones); a gauge table file brings its own.")      # extapps120
        self.override_r = QtWidgets.QCheckBox("Override radius")
        self.override_r.setObjectName("SWSMOverrideRadius")
        self.override_r.setChecked(bool(obj.SWOverrideRadius))
        for w in (self.number, self.override_t, self.radii, self.override_r):
            params_layout.addRow(w)
        if material_check is not None:
            material_check.setChecked(bool(obj.SWUseMaterial))
            material_check.setToolTip("Takes the gauge table from the part's material")
        gauge_check.setChecked(bool(obj.SWUseGauge))
        gauge_check.setToolTip("Takes the thickness, bend radius and K-Factor from a gauge table")
        self._fill()
        for w in (self.table, self.number):
            w.currentIndexChanged.connect(self._picked)
        self.radii.currentIndexChanged.connect(self._picked)
        for w in (material_check, gauge_check, self.override_t, self.override_r):
            if w is not None:
                w.toggled.connect(self._picked)
        self.browse.clicked.connect(self._browse)
        self.busy = False

    def from_material(self):
        return self.material is not None and self.material.isChecked()

    def on(self):
        return self.gauge.isChecked() or self.from_material()

    def table_name(self):
        if self.from_material():
            return table_for_material(material_of(self.obj)) or ""
        return self.table.currentText()

    def _fill(self):
        name = self.table_name()
        for w in (self.table, self.number, self.radii):
            w.blockSignals(True)
        if self.from_material() and name:
            self.table.setCurrentText(name)
        keep = self.number.currentText() or self.obj.SWGauge
        self.number.clear()
        self.number.addItems(gauges(name))
        self.number.setCurrentText(keep if keep in gauges(name) else nearest(name, self.thick.value()))
        r = row(name, self.number.currentText())
        self.radii.clear()
        for x in (r or {}).get("radii", []):
            self.radii.addItem("%g mm" % x, x)
        i = self.radii.findData(self.radius.value())
        self.radii.setCurrentIndex(i if i >= 0 else 0)
        for w in (self.table, self.number, self.radii):
            w.blockSignals(False)

    def show(self, enabled=True):
        on = self.on()
        self.gauge.setEnabled(enabled and not self.from_material())
        if self.material is not None:
            self.material.setEnabled(enabled)
        for w in (self.table, self.number, self.override_t, self.radii, self.override_r):
            w.setVisible(on)
            w.setEnabled(enabled)
        self.table.setEnabled(enabled and not self.from_material())
        self.browse.setVisible(on and not self.from_material())
        if on:
            self.thick.setEnabled(enabled and self.override_t.isChecked())
            self.radius.setEnabled(enabled and self.override_r.isChecked())

    def _picked(self, *_a):
        if self.busy:
            return
        self.busy = True
        self._fill()
        self.busy = False
        self.changed()

    def _browse(self):
        from PySide import QtWidgets
        import FreeCADGui as Gui
        path, _f = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Open Gauge Table", "",
                                                         "Gauge tables (*.csv)")
        if path:
            self.add_table(path)

    def add_table(self, path):
        name = load(path)
        self.obj.SWGaugeFile = path
        self.table.blockSignals(True)
        self.table.clear()
        self.table.addItems(names())
        self.table.setCurrentText(name)
        self.table.blockSignals(False)
        self._picked()
        return name

    def apply(self):
        """Puts the gauge's values in the boxes; returns a problem to show, or ""."""
        o = self.obj
        o.SWUseMaterial, o.SWUseGauge = self.from_material(), self.gauge.isChecked()
        o.SWGaugeTable, o.SWGauge = self.table.currentText(), self.number.currentText()
        o.SWOverrideThickness, o.SWOverrideRadius = self.override_t.isChecked(), self.override_r.isChecked()
        if not self.on():
            return ""
        name = self.table_name()
        if not name:
            return ("The part's material has no sheet metal parameters: give the part Steel, Stainless Steel "
                    "or Aluminum (Edit Material), or use a gauge table.")
        r = row(name, self.number.currentText())
        if r is None:
            return "Pick a gauge."
        for w in (self.thick, self.radius, self.kfactor):
            w.blockSignals(True)
        if not self.override_t.isChecked():
            self.thick.setValue(r["thickness"])
        if not self.override_r.isChecked() and self.radii.currentData() is not None:
            self.radius.setValue(float(self.radii.currentData()))
        self.kfactor.setValue(r["k"])
        for w in (self.thick, self.radius, self.kfactor):
            w.blockSignals(False)
        return ""
