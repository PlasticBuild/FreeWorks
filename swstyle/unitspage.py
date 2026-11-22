# -*- coding: utf-8 -*-
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

from . import chrome
from .sketchoptions import Setting

UNITS = "User parameter:BaseApp/Preferences/Units"


# ImperialDecimal, Centimeter, ImperialBuilding, MmMin, ImperialCivil, FEM, MeterDecimal)
SYSTEMS = [("MKS (meter, kilogram, second)", "MKS", 1),
           ("CGS (centimeter, gram, second)", "CGS", 4),
           ("MMGS (millimeter, gram, second)", "MMGS", 0),
           ("IPS (inch, pound, second)", "IPS", 3),
           ("Custom", "Custom", None)]
# Custom: the length unit picks the schema
LENGTHS = [("millimeters", 0), ("centimeters", 4), ("meters", 9), ("inches", 3), ("feet", 7), ("feet & inches", 5)]
SCHEMA_LENGTH = {0: "millimeters", 1: "meters", 2: "inches", 3: "inches", 4: "centimeters", 5: "feet & inches",
                 6: "millimeters", 7: "feet", 8: "millimeters", 9: "meters"}
# what each system gives for the rows FreeCAD does not set on their own: (mass, per unit volume, force, power, energy)
SYSTEM_ROWS = {"MKS": ("kilograms", "meters^3", "newton", "watt", "joule"),
               "CGS": ("grams", "centimeters^3", "dyne", "erg/s", "erg"),
               "MMGS": ("grams", "millimeters^3", "newton", "watt", "joule"),
               "IPS": ("pounds", "inches^3", "pound-force", "horsepower", "BTU")}
# schema -> the length unit its numbers are written in: (symbol, size in mm)
SCHEMA_UNIT = {0: ("mm", 1.0), 1: ("m", 1000.0), 2: ("in", 25.4), 3: ("in", 25.4), 4: ("cm", 10.0),
               5: ("in", 25.4), 6: ("mm", 1.0), 7: ("ft", 304.8), 8: ("mm", 1.0), 9: ("m", 1000.0)}
DECIMALS = [".1", ".12", ".123", ".1234", ".12345", ".123456", ".1234567", ".12345678"]
ANGLE_DECIMALS = ["None", ".1", ".12", ".123", ".1234", ".12345"]

PAGE = "Units"
LENGTH_NAMES = ["millimeters", "centimeters", "meters", "inches", "feet"]
LENGTH_SIZES = {"millimeters": ("mm", 1.0), "centimeters": ("cm", 10.0), "meters": ("m", 1000.0),
                "inches": ("in", 25.4), "feet": ("ft", 304.8)}
MASS_NAMES = ["grams", "kilograms", "pounds"]
SYSTEM_DUAL = {"MKS": "inches", "CGS": "inches", "MMGS": "inches", "IPS": "millimeters"}
SYSTEM_MASS = {"MKS": ("meters", "kilograms"), "CGS": ("centimeters", "grams"), "MMGS": ("millimeters", "grams"),
               "IPS": ("inches", "pounds")}


def doc_setting(doc, text, default):
    """A Units row the document keeps (Dual Dimension Length, Angle decimals, Mass/Section Properties)."""
    try:
        from . import optionspages
        return optionspages.doc_value(doc, PAGE, text, default)
    except Exception as _fw_err:
        _fw_log("unitspage.py:doc_setting", _fw_err)
        return default


def set_doc_setting(doc, text, value):
    ""

    try:
        from . import optionspages
        key = optionspages.DOC_META + optionspages._store_key(PAGE, text)
        if doc is not None:
            meta = dict(doc.Meta or {})
            raw = ("1" if value else "0") if isinstance(value, bool) else str(value)
            if meta.get(key) != raw:
                meta[key] = raw
                doc.Meta = meta
    except Exception as _fw_err:
        _fw_log("unitspage.py:set_doc_setting", _fw_err)


def system_name(doc=None):
    return system_of(schema_of(doc))


def dual_length(doc=None):
    """(name, symbol, mm, decimals) of the Dual Dimension Length row: inches in a metric part, millimetres in an
    inch part, until it is set."""
    sys_name = system_name(doc)
    default = SYSTEM_DUAL.get(sys_name, "millimeters" if length_unit(doc)[0] in ("in", "ft") else "inches")
    name = str(doc_setting(doc, "Dual dimension length", "") or default)
    if name not in LENGTH_SIZES:
        name = default
    sym, mm = LENGTH_SIZES[name]
    return name, sym, mm, int(doc_setting(doc, "Dual dimension decimals", 3))


def angle_decimals(doc=None):
    ""
    return int(doc_setting(doc, "Angle decimals", 2))


def length_decimals(doc=None):
    ""
    doc = doc if doc is not None else App.ActiveDocument
    try:
        own = doc_setting(doc, "Length decimals", "") if doc is not None else ""
        if str(own) != "":
            return int(own)
    except Exception as _fw_err:
        _fw_log("unitspage.py:length_decimals", _fw_err)
    return decimals()


NEW_PART_DECIMALS = 2
_follow = {"doc": None, "busy": False, "base": None}     # base: FreeCAD's own decimals, the user's (fix02)


def follow(doc=None):
    ""


    doc = doc if doc is not None else App.ActiveDocument
    if doc is None or _follow["busy"] or getattr(doc, "Restoring", False):
        return
    if _follow["base"] is None:
        _follow["base"] = decimals()
    _follow["doc"] = doc.Name
    own = doc_setting(doc, "Length decimals", "")
    if str(own) == "":
        # shown, not written: a new part its template's .12; a file from before it kept decimals, the user's own
        own = _follow["base"] if getattr(doc, "FileName", "") else NEW_PART_DECIMALS
    own = int(own)
    if own != decimals():
        _follow["busy"] = True
        units = App.ParamGet(UNITS)
        user_schema = units.GetInt("UserSchema", 0)     # FreeCAD's page writes the shown part's system as the user's
        try:
            apply_decimals(own)
        finally:
            _follow["busy"] = False
            if units.GetInt("UserSchema", 0) != user_schema:
                units.SetInt("UserSchema", user_schema)


def _restore_base():
    """The last document closed: FreeCAD's own decimals go back to the user's (fix02)."""
    base = _follow["base"]
    if App.listDocuments() or base is None:
        return
    _follow["base"] = None
    if decimals() != base:
        _follow["busy"] = True
        units = App.ParamGet(UNITS)
        user_schema = units.GetInt("UserSchema", 0)
        try:
            apply_decimals(base)
        finally:
            _follow["busy"] = False
            if units.GetInt("UserSchema", 0) != user_schema:
                units.SetInt("UserSchema", user_schema)
        try:
            from . import docstyle
            docstyle.apply_all(doc)
        except Exception as _fw_err:
            _fw_log("unitspage.py:follow restyle", _fw_err)


class _DocWatch:
    def slotActivateDocument(self, doc):
        QtCore.QTimer.singleShot(0, lambda d=doc: _safe_follow(d))

    def slotDeletedDocument(self, doc):
        QtCore.QTimer.singleShot(0, _safe_restore)

    def slotCreatedDocument(self, doc):
        QtCore.QTimer.singleShot(0, lambda d=doc: _safe_follow(d) if App.ActiveDocument is d else None)


def _safe_restore():
    try:
        _restore_base()
    except Exception as _fw_err:
        _fw_log("unitspage.py:restore base", _fw_err)


def _safe_follow(doc):
    try:
        if doc is not None and doc.Name in App.listDocuments():
            follow(doc)
    except Exception as _fw_err:
        _fw_log("unitspage.py:follow", _fw_err)


_watch = []


def _quit_base():
    """FreeCAD quitting with a part's decimals shown: the user's own go back into the settings file (fix03)."""
    base = _follow["base"]
    if base is not None and decimals() != base:
        App.ParamGet(UNITS).SetInt("Decimals", base)


def install():
    if not _watch:
        _watch.append(_DocWatch())
        App.addDocumentObserver(_watch[0])
        try:
            QtWidgets.QApplication.instance().aboutToQuit.connect(_quit_base)
        except Exception as _fw_err:
            _fw_log("unitspage.py:quit hook", _fw_err)


def mass_units(doc=None):
    """(length name, mass name, length decimals, mass decimals) of the Mass/Section Properties rows."""
    sys_name = system_name(doc)
    base = SYSTEM_MASS.get(sys_name)
    if base is None:
        sym = length_unit(doc)[0]
        base = ("inches", "pounds") if sym in ("in", "ft") else (
            {"cm": "centimeters", "m": "meters"}.get(sym, "millimeters"), "grams")
    length = str(doc_setting(doc, "Mass length", "") or base[0])
    mass = str(doc_setting(doc, "Mass unit", "") or base[1])
    if length not in LENGTH_SIZES:
        length = base[0]
    if mass not in MASS_NAMES:
        mass = base[1]
    return length, mass, int(doc_setting(doc, "Mass length decimals", 2)), int(doc_setting(doc, "Mass decimals", 2))


def _schema():
    doc = App.ActiveDocument
    try:
        if doc is not None and hasattr(doc, "UnitSystem"):
            return doc.getEnumerationsOfProperty("UnitSystem").index(doc.UnitSystem)
    except Exception as _fw_err:
        _fw_log("unitspage.py:57", _fw_err)
    return chrome.current_schema()


def schema_of(doc=None):
    """The unit schema index of doc (the active document when None; FreeCAD's own when there is none)."""
    doc = doc if doc is not None else App.ActiveDocument
    try:
        if doc is not None and hasattr(doc, "UnitSystem"):
            return doc.getEnumerationsOfProperty("UnitSystem").index(doc.UnitSystem)
    except Exception as _fw_err:
        _fw_log("unitspage.py:schema_of", _fw_err)
    return chrome.current_schema()


def length_unit(doc=None):
    """(symbol, size in mm) of the document's length unit: ("in", 25.4) in an IPS part."""
    return SCHEMA_UNIT.get(schema_of(doc), ("mm", 1.0))


def decimals():
    return App.ParamGet(UNITS).GetInt("Decimals", 2)


def _live_decimals():
    """The decimals FreeCAD writes numbers with now (they can differ from the parameter until set)."""
    try:
        text = App.Units.Quantity("0.123456789 mm").getUserPreferred()[0]
        import re
        m = re.search(r"\d[.,](\d+)", text)
        return len(m.group(1)) if m else 0
    except Exception:
        return None


class _PrefsDecimals(QtCore.QObject):
    """Fills FreeCAD's own Preferences page (General: Number of decimals) out of sight and presses OK: the
    only way FreeCAD 1.1 takes new decimals without a restart."""

    def __init__(self, n):
        super().__init__()
        self.n, self.done = n, False

    def eventFilter(self, obj, event):
        try:
            if event.type() == QtCore.QEvent.Show and isinstance(obj, QtWidgets.QDialog) \
                    and "Preferences" in obj.metaObject().className():
                obj.setWindowOpacity(0.0)
                obj.move(-10000, -10000)
                QtCore.QTimer.singleShot(0, lambda o=obj: self.fill(o))
        except Exception as _fw_err:
            _fw_log("unitspage.py:prefs filter", _fw_err)
        return False

    def fill(self, box):
        try:
            spin = box.findChild(QtWidgets.QSpinBox, "spinBoxDecimals")
            if spin is not None:
                spin.setValue(self.n)
                self.done = True
                box.accept()
            else:
                box.reject()
        except Exception as _fw_err:
            _fw_log("unitspage.py:prefs fill", _fw_err)
            box.reject()


def apply_decimals(n):
    ""
    n = max(0, int(n))
    doc = App.ActiveDocument
    if not _follow["busy"]:
        if doc is None:
            _follow["base"] = n             # set with no part open: the user's own from now on
        elif _follow["base"] is None:
            _follow["base"] = decimals()
    App.ParamGet(UNITS).SetInt("Decimals", n)
    if doc is not None and not _follow["busy"]:
        set_doc_setting(doc, "Length decimals", n)       # the part keeps them (docdec-fix01)
    if _live_decimals() == n:
        return True
    schema = schema_of(doc)
    system = getattr(doc, "UnitSystem", None) if doc is not None else None
    app = QtWidgets.QApplication.instance()
    watch = _PrefsDecimals(n)
    app.installEventFilter(watch)
    try:
        Gui.showPreferences("General", 0)
    except Exception as _fw_err:
        _fw_log("unitspage.py:apply_decimals", _fw_err)
    finally:
        app.removeEventFilter(watch)
    # FreeCAD's page also writes its own unit system: the document keeps the one it had
    try:
        if doc is not None and system is not None and doc.UnitSystem != system:
            doc.UnitSystem = system
        App.Units.setSchema(schema)
    except Exception as _fw_err:
        _fw_log("unitspage.py:apply_decimals schema", _fw_err)
    App.ParamGet(UNITS).SetInt("Decimals", n)
    if not watch.done:
        App.Console.PrintMessage("FreeCAD: the new decimals apply when FreeCAD starts again\n")
    return watch.done


def system_of(schema):
    ""
    for _label, short, index in SYSTEMS:
        if index == schema:
            return short
    return "Custom"


class UnitsTable(Setting):
    """The whole Units page: the unit system radios and the units table."""

    def __init__(self):
        super().__init__(UNITS, "UserSchema", 0, "Unit system", "")

    def widget(self):
        page = QtWidgets.QWidget()
        page.setObjectName("SWUnitsPage")
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        box = QtWidgets.QGroupBox("Unit system")
        blay = QtWidgets.QVBoxLayout(box)
        self.radios = {}
        for label, short, _index in SYSTEMS:
            r = QtWidgets.QRadioButton(label)
            r.setObjectName("SWUnits_" + short)
            r.toggled.connect(lambda on, s=short: on and self._system(s))
            blay.addWidget(r)
            self.radios[short] = r
        lay.addWidget(box)
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setObjectName("SWUnitsTable")
        self.table.setHorizontalHeaderLabels(["Type", "Unit", "Decimals"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)

        # Mass, Per Unit Volume), Motion Units (Time, Force, Power, Energy)
        rows = [("Basic Units", None), ("Length", "length"), ("Dual Dimension Length", "dual"), ("Angle", "angle"),
                ("Mass/Section Properties", None), ("Length", "mlength"), ("Mass", 0), ("Per Unit Volume", 1),
                ("Motion Units", None), ("Time", "time"), ("Force", 2), ("Power", 3), ("Energy", 4)]
        self.cells = {}
        for name, key in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            item = QtWidgets.QTableWidgetItem(name)
            item.setFlags(QtCore.Qt.ItemIsEnabled)
            if key is None:
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            self.table.setItem(r, 0, item)
            if key is None:
                continue
            if key == "length":
                self.length = QtWidgets.QComboBox()
                self.length.setObjectName("SWUnitsLength")
                self.length.addItems([l for l, _s in LENGTHS])
                self.table.setCellWidget(r, 1, self.length)
                self.decimals = QtWidgets.QComboBox()
                self.decimals.setObjectName("SWUnitsLengthDecimals")
                self.decimals.addItems(DECIMALS)
                self.table.setCellWidget(r, 2, self.decimals)
            elif key in ("dual", "mlength"):
                unit = QtWidgets.QComboBox()
                unit.setObjectName("SWUnitsDual" if key == "dual" else "SWUnitsMassLength")
                unit.addItems(LENGTH_NAMES)
                dec = QtWidgets.QComboBox()
                dec.setObjectName(unit.objectName() + "Decimals")
                dec.addItems(DECIMALS)
                self.table.setCellWidget(r, 1, unit)
                self.table.setCellWidget(r, 2, dec)
                setattr(self, key + "_unit", unit)
                setattr(self, key + "_decimals", dec)
                if key == "mlength":
                    unit.currentIndexChanged.connect(self._mass_picked)
            elif key == "angle":
                cell = QtWidgets.QTableWidgetItem("degrees")
                cell.setFlags(QtCore.Qt.ItemIsEnabled)
                self.table.setItem(r, 1, cell)
                self.cells[key] = cell
                self.angle_decimals = QtWidgets.QComboBox()
                self.angle_decimals.setObjectName("SWUnitsAngleDecimals")
                self.angle_decimals.addItems(ANGLE_DECIMALS)
                self.table.setCellWidget(r, 2, self.angle_decimals)
            elif key == 0:
                self.mass_unit = QtWidgets.QComboBox()
                self.mass_unit.setObjectName("SWUnitsMass")
                self.mass_unit.addItems(MASS_NAMES)
                self.mass_unit.currentIndexChanged.connect(self._mass_picked)
                self.table.setCellWidget(r, 1, self.mass_unit)
                self.mass_decimals = QtWidgets.QComboBox()
                self.mass_decimals.setObjectName("SWUnitsMassDecimals")
                self.mass_decimals.addItems(DECIMALS)
                self.table.setCellWidget(r, 2, self.mass_decimals)
                cell = QtWidgets.QTableWidgetItem("")
                self.cells[key] = cell
            else:
                cell = QtWidgets.QTableWidgetItem("")
                cell.setFlags(QtCore.Qt.ItemIsEnabled)
                self.table.setItem(r, 1, cell)
                self.cells[key] = cell
        self.table.resizeColumnsToContents()
        self.table.setMinimumHeight(self.table.verticalHeader().length() + self.table.horizontalHeader().height() + 4)
        lay.addWidget(self.table)
        lay.addStretch(1)
        self.tag(self.length)
        return page

    # -- what the page shows
    def _system(self, short):
        """A unit system radio: the length unit follows (picking another length unit picks Custom)."""
        custom = short == "Custom"
        if not custom:
            index = dict((s, i) for _l, s, i in SYSTEMS)[short]
            self._setting = True
            try:
                self.length.setCurrentIndex([l for l, _s in LENGTHS].index(SCHEMA_LENGTH[index]))
            finally:
                self._setting = False
        self._rows(short)

    def _length_picked(self, *_args):
        ""
        if getattr(self, "_setting", False):
            return
        if not self.radios["Custom"].isChecked():
            self.radios["Custom"].setChecked(True)
        self._rows("Custom")

    def _mass_picked(self, *_args):
        ""
        if getattr(self, "_setting", False):
            return
        short = next((s for s, r in self.radios.items() if r.isChecked()), "MMGS")
        if short != "Custom" and (self.mlength_unit.currentText(), self.mass_unit.currentText()) != SYSTEM_MASS.get(short):
            self._setting = True
            try:
                self.radios["Custom"].setChecked(True)
            finally:
                self._setting = False

    def _rows(self, short):
        if short == "Custom":
            schema = LENGTHS[max(0, self.length.currentIndex())][1]
            short = system_of(schema)
            if short == "Custom":
                short = "IPS" if schema in (5, 7) else "MMGS"
        for key, text in enumerate(SYSTEM_ROWS[short]):
            self.cells[key].setText(text)
        self.cells["angle"].setText("degrees")
        self.cells["time"].setText("second")
        if not getattr(self, "_loading", False) and not self.radios["Custom"].isChecked():

            self._setting = True
            try:
                ml, mu = SYSTEM_MASS[short]
                self.mlength_unit.setCurrentIndex(LENGTH_NAMES.index(ml))
                self.mass_unit.setCurrentIndex(MASS_NAMES.index(mu))
                self.dual_unit.setCurrentIndex(LENGTH_NAMES.index(SYSTEM_DUAL[short]))
            finally:
                self._setting = False

    def schema(self):
        short = next((s for s, r in self.radios.items() if r.isChecked()), "MMGS")
        if short == "Custom":
            return LENGTHS[max(0, self.length.currentIndex())][1]
        return dict((s, i) for _l, s, i in SYSTEMS)[short]

    def value(self):
        return (self.schema(), self.decimals.currentIndex(), self.dual_unit.currentText(),
                self.dual_decimals.currentIndex() + 1, self.angle_decimals.currentIndex(),
                self.mlength_unit.currentText(), self.mlength_decimals.currentIndex() + 1,
                self.mass_unit.currentText(), self.mass_decimals.currentIndex() + 1)

    def load(self):
        self._loading = True
        try:
            self._load()
        finally:
            self._loading = False
        self.loaded = self.value()

    def _load(self):
        schema = _schema()
        short = system_of(schema)
        doc = App.ActiveDocument
        if short != "Custom" and (doc_setting(doc, "Mass length", "") or doc_setting(doc, "Mass unit", "")):
            short = "Custom"
        self.radios[short].setChecked(True)
        if short == "Custom":
            names = [l for l, _s in LENGTHS]
            self.length.setCurrentIndex(names.index(SCHEMA_LENGTH.get(schema, "millimeters")))
        self.length.currentIndexChanged.connect(self._length_picked)
        self._system(short)
        if short == "Custom":
            self.length.setCurrentIndex([s for _l, s in LENGTHS].index(schema) if schema in [s for _l, s in LENGTHS]
                                        else self.length.currentIndex())
        decimals = length_decimals(App.ActiveDocument)      # the part's own (docdec-fix01)
        self.decimals.setCurrentIndex(min(max(decimals - 1, 0), len(DECIMALS) - 1))
        doc = App.ActiveDocument
        self._setting = True
        try:
            name, _sym, _mm, dd = dual_length(doc)
            self.dual_unit.setCurrentIndex(LENGTH_NAMES.index(name))
            self.dual_decimals.setCurrentIndex(min(max(dd - 1, 0), len(DECIMALS) - 1))
            self.angle_decimals.setCurrentIndex(min(max(angle_decimals(doc), 0), len(ANGLE_DECIMALS) - 1))
            ml, mu, mld, md = mass_units(doc)
            self.mlength_unit.setCurrentIndex(LENGTH_NAMES.index(ml))
            self.mlength_decimals.setCurrentIndex(min(max(mld - 1, 0), len(DECIMALS) - 1))
            self.mass_unit.setCurrentIndex(MASS_NAMES.index(mu))
            self.mass_decimals.setCurrentIndex(min(max(md - 1, 0), len(DECIMALS) - 1))
        finally:
            self._setting = False

    def save(self):
        if not self.changed():
            return
        v = self.value()
        schema, decimals = v[0], v[1]
        if schema != self.loaded[0]:
            chrome.set_schema(schema)
        if decimals != self.loaded[1]:
            apply_decimals(decimals + 1)
        doc = App.ActiveDocument
        short = next((k for k, r in self.radios.items() if r.isChecked()), "MMGS")
        values = list(v[2:])
        if short != "Custom":
            # the system's own units: kept empty so a system picked later (status bar) brings its own
            if values[0] == SYSTEM_DUAL.get(short):
                values[0] = ""
            if (values[3], values[5]) == SYSTEM_MASS.get(short):
                values[3] = values[5] = ""
        for text, value in zip(("Dual dimension length", "Dual dimension decimals", "Angle decimals", "Mass length",
                                "Mass length decimals", "Mass unit", "Mass decimals"), values):
            set_doc_setting(doc, text, value)
        self.loaded = self.value()
