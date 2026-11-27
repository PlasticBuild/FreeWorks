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

TYPES = ["Simulation Data", "Mass Properties", "Dimension", "Measurement", "Interference Detection", "Costing Data"]
SIMULATION = ["Max von Mises Stress", "Max Displacement", "Min Factor of Safety"]
COSTING = ["Material Cost", "Cost per kg"]
COST_NAMES = ("Cost per kg", "CostPerKg", "Cost/kg")
MASS = ["Mass", "Volume", "Surface Area", "Density", "Center of Mass X", "Center of Mass Y", "Center of Mass Z",
        "Bounding Box Length", "Bounding Box Width", "Bounding Box Height"]
RULES = ["Is greater than", "Is less than", "Is exactly", "Is not greater than", "Is not less than", "Is not exactly",
         "Is between", "Is not between"]
TITLE = "Sensor"


# --------------------------------------------------------------------------- the sensor object
def ensure(obj):
    """The properties every sensor type needs on an evaluate2.Sensor (older sensors too)."""
    for prop, kind, tip in (("SensorType", "App::PropertyString", "Mass Properties, Dimension, Measurement or "
                                                                    "Interference Detection"),
                            ("Dimension", "App::PropertyString", "Dimension sensor: object name and property path"),
                            ("References", "App::PropertyLinkSubListGlobal", "Measurement sensor: what is measured"),
                            ("Measurement", "App::PropertyString", "Measurement sensor: the result watched"),
                            ("Unit", "App::PropertyString", "Length unit of the value"),
                            ("ArcMode", "App::PropertyString", "Arc/Circle Measurements"),
                            ("SimProperty", "App::PropertyString", "Simulation Data sensor: the result watched"),
                            ("CostProperty", "App::PropertyString", "Costing Data sensor: Material Cost or Cost per kg"),
                            ("CostPerKg", "App::PropertyFloat", "Costing Data sensor: cost per kg when the part "
                                                                "has no Cost per kg custom property")):
        if prop not in obj.PropertiesList:
            obj.addProperty(kind, prop, "Sensor", tip)
    if not obj.SensorType:
        obj.SensorType = "Mass Properties"
    if "Property" in obj.PropertiesList:
        now = obj.Property
        if list(obj.getEnumerationsOfProperty("Property")) != MASS:
            obj.Property = MASS
            obj.Property = now if now in MASS else "Mass"
    if "Operator" in obj.PropertiesList:
        now = obj.Operator
        if list(obj.getEnumerationsOfProperty("Operator")) != RULES:
            obj.Operator = RULES
            obj.Operator = now if now in RULES else RULES[0]


def dimension_value(obj):
    from . import equations
    text = obj.Dimension or ""
    if "|" not in text:
        return 0.0
    name, path = text.split("|", 1)
    target = obj.Document.getObject(name)
    if target is None:
        return 0.0
    text = equations.evaluate(target, path)          # "10 mm", "30 °", "2.5"
    try:
        return float(App.Units.Quantity(text).Value)
    except Exception:
        try:
            return float(str(text).split()[0])
        except Exception:
            return 0.0


def interference_value(obj):
    from .evaluate import _solids_of, visible_bodies
    bodies = list(obj.Bodies) or [b for b in visible_bodies(obj.Document) if b != obj]
    solids = []
    for b in bodies:
        solids += _solids_of(b)
    vol = 0.0
    for i in range(len(solids)):
        for j in range(i + 1, len(solids)):
            try:
                if solids[i].BoundBox.intersect(solids[j].BoundBox):
                    vol += solids[i].common(solids[j]).Volume
            except Exception as _fw_err:
                _fw_log("sensorpm.py:111", _fw_err)
    return vol


def mass_value(obj):
    from . import evaluate2
    from .evaluate import visible_bodies
    bodies = list(obj.Bodies) or [b for b in visible_bodies(obj.Document) if b != obj]
    density = _density(obj.Document)
    if obj.Property == "Density":
        return density
    if obj.Property in ("Mass", "Center of Mass X", "Center of Mass Y", "Center of Mass Z"):
        try:
            from . import massprops            # each body's own material and Override Mass Properties
            r = massprops.adjust(massprops.compute(bodies, density * 1e9), massprops.overrides(obj.Document))
            if r is not None:
                return r["mass"] / 1000.0 if obj.Property == "Mass" else r["center"]["XYZ".index(obj.Property[-1])]
        except Exception as _fw_err:
            _fw_log("sensorpm.py:129", _fw_err)
    return evaluate2.sensor_value(obj.Property, bodies, density)


def fem_results(doc):
    """The part's FEM mechanical results (newest last)."""
    out = []
    for o in getattr(doc, "Objects", []):
        if o.TypeId.startswith("Fem::FemResultObject") and "vonMises" in o.PropertiesList:
            out.append(o)
    return out


def _yield(doc):
    """The material's yield strength in MPa (Edit Material), else None."""
    try:
        from . import materialdlg
        v = materialdlg.part_data(doc).get("values", {}).get("YieldStrength")
        if v:
            return float(v) / 1e6
        uuid = materialdlg.part_data(doc).get("uuid")
    except Exception:
        uuid = None
    try:
        from . import material
        name = material.current(doc)[1]
        from . import materialdlg
        found = materialdlg.find(name) if name else None
        v = found[2].get("values", {}).get("YieldStrength") if found else None
        return float(v) / 1e6 if v else None
    except Exception as _fw_err:
        _fw_log("sensorpm.py:161", _fw_err)
        return None


def simulation_value(obj):
    results = fem_results(obj.Document)
    if not results:
        return None
    r = results[-1]
    what = getattr(obj, "SimProperty", "") or SIMULATION[0]
    stress = max(r.vonMises) if r.vonMises else 0.0
    if what == "Max Displacement":
        lengths = list(getattr(r, "DisplacementLengths", []) or [])
        return max(lengths) if lengths else 0.0
    if what == "Min Factor of Safety":
        y = _yield(obj.Document)
        if y is None or stress <= 0:
            return None
        return y / stress
    return stress


def cost_per_kg(obj):
    try:
        from . import customprops
        for n, kind, v in customprops.read(obj.Document):
            if n in COST_NAMES:
                try:
                    return float(customprops.evaluate(obj.Document, kind, v).split()[0])
                except (ValueError, IndexError) as _fw_err:
                    _fw_log("sensorpm.py:189", _fw_err)
    except Exception as _fw_err:
        _fw_log("sensorpm.py:191", _fw_err)
    v = getattr(obj, "CostPerKg", 0.0) or 0.0
    return v if v > 0 else None


def costing_value(obj):
    per = cost_per_kg(obj)
    if per is None:
        return None
    if (getattr(obj, "CostProperty", "") or COSTING[0]) == "Cost per kg":
        return per
    from . import evaluate2
    from .evaluate import visible_bodies
    bodies = list(obj.Bodies) or [b for b in visible_bodies(obj.Document) if b != obj]
    return evaluate2.sensor_value("Mass", bodies, _density(obj.Document)) * per


def missing(obj):
    kind = getattr(obj, "SensorType", "")
    if kind == "Simulation Data":
        if not fem_results(obj.Document):
            return "no study: run a FEM analysis of the part first"
        return "no yield strength: give the part a material with one (Edit Material)"
    if kind == "Costing Data":
        return "no cost: add the custom property \"Cost per kg\" or type the cost per kg in the sensor"
    return "no value"


def watched(obj):
    kind = getattr(obj, "SensorType", "")
    return {"Measurement": getattr(obj, "Measurement", ""),
            "Dimension": getattr(obj, "Dimension", "").split("|")[-1],
            "Interference Detection": "Interference volume",
            "Simulation Data": getattr(obj, "SimProperty", "") or SIMULATION[0],
            "Costing Data": getattr(obj, "CostProperty", "") or COSTING[0]}.get(kind, getattr(obj, "Property", ""))


def value(obj):
    """The sensor's value now (evaluate2.Sensor.execute calls this); None = nothing to read."""
    from . import evaluate2
    kind = getattr(obj, "SensorType", "") or "Mass Properties"
    if kind == "Simulation Data":
        return simulation_value(obj)
    if kind == "Costing Data":
        return costing_value(obj)
    if kind == "Dimension":
        return dimension_value(obj)
    if kind == "Interference Detection":
        return interference_value(obj)
    if kind == "Measurement":
        return evaluate2.measured_value(obj)
    return mass_value(obj)


def display_scale(doc, kind, prop):
    ""

    try:
        from . import massprops
        length, mm, _l, mass, g, _m = massprops.SYSTEMS[massprops.unit_system()]
    except Exception:
        length, mm, mass, g = "mm", 1.0, "g", 1.0
    if kind == "Interference Detection":
        return 1.0 / mm ** 3, length + "^3"
    if kind != "Mass Properties":
        return 1.0, ""
    return {"Mass": (1000.0 / g, mass), "Volume": (1.0 / mm ** 3, length + "^3"),
            "Surface Area": (1.0 / mm ** 2, length + "^2"),
            "Density": (1000.0 / g * mm ** 3, "%s/%s^3" % (mass, length))}.get(prop, (1.0 / mm, length))


def alerting(rule, v, a, b, tol=1e-9):
    lo, hi = min(a, b), max(a, b)
    return {"Is greater than": v > a + tol, "Is less than": v < a - tol, "Is exactly": abs(v - a) <= tol,
            "Is not greater than": v <= a + tol, "Is not less than": v >= a - tol,
            "Is not exactly": abs(v - a) > tol, "Is between": lo <= v <= hi,
            "Is not between": not (lo <= v <= hi)}.get(rule, False)


def _density(doc):
    try:
        from . import material
        return material.density(doc) * 1e-9          # kg/m^3 -> kg/mm^3
    except Exception as _fw_err:
        _fw_log("sensorpm.py:260", _fw_err)
        return 7.85e-6


# --------------------------------------------------------------------------- the PropertyManager
class SensorPanel:
    def __init__(self, doc, sensor=None):
        from . import equations
        self.doc, self.sensor = doc, sensor
        self.dims = equations.dimensions(doc)
        self.picked_bodies = list(sensor.Bodies) if sensor is not None else []
        self.refs = []
        if sensor is not None and "References" in sensor.PropertiesList:
            self.refs = [(o, s) for o, subs in sensor.References for s in (subs or [""])]
        kind = QtWidgets.QWidget()
        kind.setWindowTitle("Sensor Type")
        kind.setObjectName("SWSensorTypeBox")
        kind.setProperty("swstyle_pm_title", TITLE)
        kind.setProperty("swstyle_pm_icon", "TOOLS_SENSOR")
        lay = QtWidgets.QVBoxLayout(kind)
        self.type = QtWidgets.QComboBox()
        self.type.setObjectName("SWSensorType")
        self.type.addItems(TYPES)
        self.type.setCurrentText("Mass Properties")
        lay.addWidget(self.type)
        props = QtWidgets.QWidget()
        props.setWindowTitle("Properties")
        form = QtWidgets.QFormLayout(props)
        self.property = QtWidgets.QComboBox()
        self.property.setObjectName("SWSensorProperty")
        self.property.addItems(MASS)
        self.dimension = QtWidgets.QComboBox()
        self.dimension.setObjectName("SWSensorDimension")
        for name, o, path, v in self.dims:
            self.dimension.addItem(name, "%s|%s" % (o.Name, path))
        self.measurement = QtWidgets.QComboBox()
        self.measurement.setObjectName("SWSensorMeasurement")
        self.sim = QtWidgets.QComboBox()
        self.sim.setObjectName("SWSensorSimulation")
        self.sim.addItems(SIMULATION)
        self.cost = QtWidgets.QComboBox()
        self.cost.setObjectName("SWSensorCosting")
        self.cost.addItems(COSTING)
        self.per = QtWidgets.QDoubleSpinBox()
        self.per.setObjectName("SWSensorCostPerKg")
        self.per.setRange(0, 1e9)
        self.per.setDecimals(4)
        self.per.setToolTip("Used when the part has no \"Cost per kg\" custom property")
        self.picks = QtWidgets.QListWidget()
        self.picks.setObjectName("SWSensorEntities")
        self.picks.setProperty("swpickbox", True)
        self.picks.setFixedHeight(70)
        self.picks.setStyleSheet("QListWidget { background: #cce4f7; }")
        self.picks.setToolTip("Bodies (Mass Properties, Interference Detection) or entities (Measurement): "
                              "click them in the view; a second click takes one out")
        self.picks.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.picks.customContextMenuRequested.connect(self._picks_menu)
        self.now = QtWidgets.QLabel("")
        self.now.setObjectName("SWSensorValue")
        self.rows = {}
        for label, w in (("Property:", self.property), ("Result:", self.sim), ("Dimension:", self.dimension),
                         ("Measurement:", self.measurement), ("Costing:", self.cost), ("Cost per kg:", self.per),
                         ("Entities:", self.picks), ("Value:", self.now)):
            form.addRow(label, w)
            self.rows[w] = form.labelForField(w)
        alert = QtWidgets.QWidget()
        alert.setWindowTitle("Alert")
        form = QtWidgets.QFormLayout(alert)
        self.alert = QtWidgets.QCheckBox("Alert")
        self.alert.setObjectName("SWSensorAlert")
        self.alert.setChecked(True)
        self.rule = QtWidgets.QComboBox()
        self.rule.setObjectName("SWSensorRule")
        self.rule.addItems(RULES)
        self.l1, self.l2 = QtWidgets.QDoubleSpinBox(), QtWidgets.QDoubleSpinBox()
        for sb, name in ((self.l1, "SWSensorLimit1"), (self.l2, "SWSensorLimit2")):
            sb.setRange(-1e12, 1e12)
            sb.setDecimals(6)
            sb.setObjectName(name)
        form.addRow(self.alert)
        form.addRow(self.rule)
        form.addRow("Limit:", self.l1)
        self.l2_label = QtWidgets.QLabel("And:")
        form.addRow(self.l2_label, self.l2)
        self.form = [kind, props, alert]

        # always live (no greyed rule and limits): picking a rule or typing a limit turns the alert on
        self.rule.activated.connect(lambda *_a: self.alert.setChecked(True))
        for sb in (self.l1, self.l2):
            sb.lineEdit().textEdited.connect(lambda *_a: self.alert.setChecked(True))
        if sensor is not None:
            ensure(sensor)
            self.type.setCurrentText(sensor.SensorType or "Mass Properties")
            self.property.setCurrentText(sensor.Property)
            i = self.dimension.findData(sensor.Dimension)
            if i >= 0:
                self.dimension.setCurrentIndex(i)
            self.alert.setChecked(bool(sensor.Alert))
            self.rule.setCurrentText(sensor.Operator)
            k, _unit = display_scale(doc, sensor.SensorType or "Mass Properties", sensor.Property)
            self.l1.setValue(sensor.Limit1 * k)
            self.l2.setValue(sensor.Limit2 * k)
            if sensor.Measurement:
                self.measurement.addItem(sensor.Measurement)
            if sensor.SimProperty:
                self.sim.setCurrentText(sensor.SimProperty)
            if sensor.CostProperty:
                self.cost.setCurrentText(sensor.CostProperty)
            self.per.setValue(sensor.CostPerKg or 0.0)
        self.type.currentIndexChanged.connect(lambda i: self._show(True))
        self.per.valueChanged.connect(lambda v: self._show(True))
        for w in (self.property, self.dimension, self.measurement, self.sim, self.cost):
            w.currentIndexChanged.connect(lambda i: self._show(True))
        self.rule.currentIndexChanged.connect(lambda i: self._show(False))
        self._show(sensor is None)
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    # --- what shows
    def _show(self, reset_limit):
        kind = self.type.currentText()
        for w, on in ((self.property, kind == "Mass Properties"), (self.dimension, kind == "Dimension"),
                      (self.measurement, kind == "Measurement"), (self.sim, kind == "Simulation Data"),
                      (self.cost, kind == "Costing Data"), (self.per, kind == "Costing Data"),
                      (self.picks, kind not in ("Dimension", "Simulation Data"))):
            w.setVisible(on)
            if self.rows.get(w) is not None:
                self.rows[w].setVisible(on)
        between = "between" in self.rule.currentText()
        self.l2.setVisible(between)
        self.l2_label.setVisible(between)
        self._fill_picks()
        if kind == "Measurement":
            self._fill_measurements()
        v = self.current()
        k, unit = self.scale()
        for sb in (self.l1, self.l2):
            sb.setSuffix((" " + unit) if unit else "")
        if v is None:
            self.now.setText(missing(self._scratch()))
            return
        self.now.setText(("%.6g %s" % (v * k, unit)).strip())
        if reset_limit:
            self.l1.setValue(v * k)

    def scale(self):
        """The page shows values and takes limits in the part's own units (display_scale)."""
        return display_scale(self.doc, self.type.currentText(), self.property.currentText())

    def _fill_picks(self):
        self.picks.clear()
        if self.type.currentText() == "Measurement":
            for o, s in self.refs:
                self.picks.addItem("%s@%s" % (s, o.Label) if s else o.Label)
        else:
            for b in self.picked_bodies:
                self.picks.addItem(b.Label)

    def _fill_measurements(self):
        from . import measure
        keep = self.measurement.currentText()
        self.measurement.blockSignals(True)
        self.measurement.clear()
        names = []
        if self.refs:
            shapes = []
            for o, s in self.refs:
                try:
                    shapes.append(o.getSubObject(s) if s else o.Shape)
                except Exception as _fw_err:
                    _fw_log("sensorpm.py:419", _fw_err)
            try:
                units = measure.Units("Millimeters", 6)
                lines, _draw = measure.measure(shapes, units, measure.ARC_MODES[0])
                names = [n for n, v in lines if units.value(v) is not None]
            except Exception:
                names = []
        self.measurement.addItems(names)
        if keep in names:
            self.measurement.setCurrentText(keep)
        self.measurement.blockSignals(False)

    def _scratch(self):
        """A stand-in sensor for the value shown while the page is open."""
        class S:
            pass
        s = S()
        s.Document = self.doc
        s.SensorType = self.type.currentText()
        s.Property = self.property.currentText()
        s.Density = _density(self.doc)
        s.Bodies = list(self.picked_bodies)
        s.Dimension = self.dimension.currentData() or ""
        grouped = {}
        for o, sub in self.refs:
            grouped.setdefault(o, []).append(sub)
        s.References = list(grouped.items())
        s.Measurement = self.measurement.currentText()
        s.Unit, s.ArcMode = "Millimeters", None
        s.SimProperty = self.sim.currentText()
        s.CostProperty = self.cost.currentText()
        s.CostPerKg = self.per.value()
        return s

    def current(self):
        try:
            return value(self._scratch())
        except Exception as _fw_err:
            _fw_log("sensorpm.py:460", _fw_err)
            return 0.0

    # --- picks
    def _alive(self):
        """The page is still up: closed some other way (another task dialog, a closed document), it
        lets go of the selection instead of reaching its deleted widgets."""
        try:
            self.type.currentText()
            self.doc.Name
            return True
        except (RuntimeError, ReferenceError, AttributeError):
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("sensorpm.py:471", _fw_err)
            return False

    def addSelection(self, doc, name, sub, pnt):
        if not self._alive() or doc != self.doc.Name:
            return
        obj = self.doc.getObject(name)
        if obj is not None:
            from . import safe_later as _sl; _sl.later(0, lambda: self.picked(obj, sub), self, "type")

    def picked(self, obj, sub):
        if not self._alive():
            return
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("sensorpm.py:487", _fw_err)
        kind = self.type.currentText()
        if kind in ("Dimension", "Simulation Data"):
            return
        if kind == "Measurement":
            key = (obj, sub)
            self.refs = [r for r in self.refs if r != key] if key in self.refs else self.refs + [key]
        else:
            body = obj
            try:
                parent = obj.getParentGeoFeatureGroup()
                if parent is not None and parent.TypeId == "PartDesign::Body":
                    body = parent
            except Exception as _fw_err:
                _fw_log("sensorpm.py:501", _fw_err)
            if body in self.picked_bodies:
                self.picked_bodies.remove(body)
            else:
                self.picked_bodies.append(body)
        self._show(True)

    def _picks_menu(self, pos):
        menu = QtWidgets.QMenu(self.picks)
        menu.addAction("Clear Selections", self.clear)
        menu.exec_(self.picks.viewport().mapToGlobal(pos))

    def clear(self):
        self.picked_bodies, self.refs = [], []
        self._show(True)

    # --- OK / Cancel
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        from . import evaluate2
        doc = self.doc
        kind = self.type.currentText()
        if kind == "Measurement" and not (self.refs and self.measurement.currentText()):
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), TITLE, "Pick what to measure in the view first.")
            return False
        doc.openTransaction("Edit Sensor" if self.sensor is not None else "Sensor")
        try:
            s = self.sensor
            if s is None:
                s = doc.addObject("App::FeaturePython", "Sensor")
                evaluate2.Sensor(s)
            ensure(s)
            s.SensorType = kind
            s.Property = self.property.currentText()
            s.Density = _density(doc)
            s.Bodies = list(self.picked_bodies)
            s.Dimension = (self.dimension.currentData() or "") if kind == "Dimension" else ""
            grouped = {}
            for o, sub in self.refs:
                grouped.setdefault(o, []).append(sub)
            s.References = list(grouped.items()) if kind == "Measurement" else []
            s.Measurement = self.measurement.currentText() if kind == "Measurement" else ""
            s.Unit = "Millimeters"
            s.ArcMode = "Center to Center"
            s.SimProperty = self.sim.currentText() if kind == "Simulation Data" else ""
            s.CostProperty = self.cost.currentText() if kind == "Costing Data" else ""
            s.CostPerKg = self.per.value()
            s.Alert = self.alert.isChecked()
            s.Operator = self.rule.currentText()
            k, _unit = self.scale()
            s.Limit1, s.Limit2 = self.l1.value() / k, self.l2.value() / k
            what = {"Mass Properties": s.Property, "Dimension": self.dimension.currentText(),
                    "Measurement": s.Measurement, "Interference Detection": "Interference",
                    "Simulation Data": s.SimProperty, "Costing Data": s.CostProperty}[kind]
            if self.sensor is None:
                s.Label = "Sensor - %s" % what
            s.touch()
            doc.recompute()
        finally:
            doc.commitTransaction()
        self.made = s
        self._close()
        return True

    def reject(self):
        self._close()
        return True

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("sensorpm.py:574", _fw_err)
        Gui.Control.closeDialog()


_panel = None


def open_page(doc=None, sensor=None):
    global _panel
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    if _panel is not None:
        try:
            Gui.Selection.removeObserver(_panel)     # a page closed without OK / Cancel
        except Exception as _fw_err:
            _fw_log("sensorpm.py:592", _fw_err)
    _panel = SensorPanel(doc, sensor)
    Gui.Control.showDialog(_panel)
    return _panel


# --------------------------------------------------------------------------- checked after every rebuild
def is_sensor(obj):
    try:
        return type(getattr(obj, "Proxy", None)).__name__ == "Sensor" and "Alerting" in obj.PropertiesList
    except Exception:
        return False


def refresh(doc):
    """Every sensor of the document measured again (a sensor links nothing, so a rebuild skips it)."""
    for obj in list(getattr(doc, "Objects", [])):
        if is_sensor(obj):
            try:
                obj.Proxy.execute(obj)
                obj.purgeTouched()
            except Exception as error:
                App.Console.PrintLog("FreeCAD: sensor %s: %s\n" % (obj.Label, error))


# --------------------------------------------------------------------------- the alert balloon
_was = {}            # (document, sensor) -> alerting at the last check
ALERTS = []          # the balloons' texts (checks read them)
_balloon = [None]


def alert_text(obj):
    base = obj.Label.lstrip("⚠ ").strip()
    v = obj.Value if obj.Value else value(obj)
    if v is None:
        return "Sensor alert: %s: %s" % (base, missing(obj))
    rule = (obj.Operator or "").lower()
    k, unit = display_scale(obj.Document, getattr(obj, "SensorType", ""), getattr(obj, "Property", ""))
    u = (" " + unit) if unit else ""
    limits = "%g and %g%s" % (obj.Limit1 * k, obj.Limit2 * k, u) if "between" in rule else "%g%s" % (obj.Limit1 * k, u)
    return "Sensor alert: %s: %s = %g%s (%s %s)" % (base, watched(obj), round(v * k, 6), u, rule, limits)


def notify(doc):
    ""
    texts = []
    for o in list(getattr(doc, "Objects", [])):
        if not is_sensor(o):
            continue
        key = (doc.Name, o.Name)
        now = bool(o.Alerting)
        if now and not _was.get(key):
            texts.append(alert_text(o))
        _was[key] = now
    if texts:
        ALERTS.extend(texts)
        show_balloon("\n".join(texts))
    return texts


def show_balloon(text, ms=8000):
    try:
        old = _balloon[0]
        if old is not None:
            old.close()
    except RuntimeError as _fw_err:
        _fw_log("sensorpm.py:656", _fw_err)
    mw = Gui.getMainWindow()
    box = QtWidgets.QLabel(text, mw, QtCore.Qt.ToolTip)
    box.setObjectName("SWSensorAlertBalloon")
    box.setStyleSheet("QLabel { background: #fff7c2; color: #1a1a1a; border: 1px solid #b58a00; padding: 6px 8px; }")
    box.setWordWrap(True)
    box.setMaximumWidth(360)
    box.adjustSize()
    anchor = None
    try:
        from . import shell
        anchor = shell.shell().left_pane
    except Exception as _fw_err:
        _fw_log("sensorpm.py:669", _fw_err)
    if anchor is not None and anchor.isVisible():
        top_right = anchor.mapToGlobal(QtCore.QPoint(anchor.width() - 8, 48))
    else:
        top_right = mw.mapToGlobal(QtCore.QPoint(260, 140))
    box.move(top_right)
    box.mousePressEvent = lambda e: box.close()
    box.show()
    QtCore.QTimer.singleShot(ms, lambda: box.close() if _alive(box) else None)
    _balloon[0] = box
    return box


def _alive(w):
    try:
        w.objectName()
        return True
    except RuntimeError:
        return False


class _Watch:
    def __init__(self):
        self.busy = False

    def slotRecomputedDocument(self, doc):
        if self.busy or not any(is_sensor(o) for o in doc.Objects):
            return
        name = doc.Name

        def run():
            self.busy = True
            try:
                refresh(App.getDocument(name))
                notify(App.getDocument(name))
            except Exception as _fw_err:
                _fw_log("sensorpm.py:705", _fw_err)
            finally:
                self.busy = False
        QtCore.QTimer.singleShot(0, run)


_watch = None


def watch():
    global _watch
    if _watch is None:
        _watch = _Watch()
        App.addDocumentObserver(_watch)
