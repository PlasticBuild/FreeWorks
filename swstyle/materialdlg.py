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

import copy
import json
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import material

TITLE = "Material"
HELP = ("Pick a material in the tree, then Apply to give it to the part (Close keeps the dialog's changes "
        "out). Materials in FreeCAD Materials are read only: Copy one and Paste it into Custom Materials to "
        "change its values, then Save. Right-click in the tree for New Library, New Category, New Material, "
        "Open Library, Rename, Delete and the sort orders. The Favorites tab lists the materials shown first "
        "on the Material row's right-click menu in the FeatureManager tree.")
LIBRARY = "FreeCAD Materials"
CUSTOM = "Custom Materials"
ROLE = QtCore.Qt.UserRole
PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Materials"


PROPERTIES = [
    ("Elastic Modulus", "YoungsModulus", "stress"),
    ("Poisson's Ratio", "PoissonRatio", "ratio"),
    ("Shear Modulus", "ShearModulus", "stress"),
    ("Mass Density", "Density", "density"),
    ("Tensile Strength", "UltimateTensileStrength", "stress"),
    ("Compressive Strength", "CompressiveStrength", "stress"),
    ("Yield Strength", "YieldStrength", "stress"),
    ("Thermal Expansion Coefficient", "ThermalExpansionCoefficient", "expansion"),
    ("Thermal Conductivity", "ThermalConductivity", "conductivity"),
    ("Specific Heat", "SpecificHeat", "heat"),
    ("Material Damping Ratio", "DampingRatio", "ratio"),
]
# SI value -> shown value: (unit text, factor) per units system
UNITS = {
    "SI - N/m^2 (Pa)": {"stress": ("N/m^2", 1.0), "density": ("kg/m^3", 1.0), "expansion": ("/K", 1.0),
                        "conductivity": ("W/(m·K)", 1.0), "heat": ("J/(kg·K)", 1.0), "ratio": ("N/A", 1.0)},
    "English (IPS)": {"stress": ("psi", 1.0 / 6894.757), "density": ("lb/in^3", 1.0 / 27679.9),
                      "expansion": ("/°F", 1.0 / 1.8), "conductivity": ("BTU/(in·sec·°F)", 1.0 / 74725.0),
                      "heat": ("BTU/(lb·°F)", 1.0 / 4186.8), "ratio": ("N/A", 1.0)},
    "Metric (MKS)": {"stress": ("kgf/cm^2", 1.0 / 98066.5), "density": ("kg/cm^3", 1e-6),
                     "expansion": ("/°C", 1.0), "conductivity": ("cal/(cm·sec·°C)", 1.0 / 418.68),
                     "heat": ("cal/(g·°C)", 1.0 / 4186.8), "ratio": ("N/A", 1.0)},
}
SI_UNIT = {"stress": "Pa", "density": "kg/m^3", "expansion": "1/K", "conductivity": "W/m/K",
           "heat": "J/kg/K", "ratio": None}
MODEL_TYPES = ["Linear Elastic Isotropic", "Linear Elastic Orthotropic", "Linear Elastic Anisotropic",
               "Plasticity - von Mises", "Plasticity - Tresca", "Nonlinear Elastic"]
CRITERIA = ["Max von Mises Stress", "Max Shear Stress (Tresca)", "Mohr-Coulomb Stress", "Max Normal Stress", "Unknown"]
CURVES = ["Stress-Strain curve", "Temperature-dependent Elastic Modulus", "Temperature-dependent Thermal Conductivity",
          "Fatigue SN Curves"]
# the table columns and the graph axes of each curve (values in SI, as the Properties tab stores them)
CURVE_AXES = {"Stress-Strain curve": ("Strain", "Stress (N/m^2)", False),
              "Temperature-dependent Elastic Modulus": ("Temperature (K)", "Elastic Modulus (N/m^2)", False),
              "Temperature-dependent Thermal Conductivity": ("Temperature (K)", "Thermal Conductivity (W/(m.K))", False),
              "Fatigue SN Curves": ("Number of cycles", "Alternating Stress (N/m^2)", True)}


def nice_ticks(lo, hi, n=5):
    """About n round tick values from lo to hi (1, 2, 2.5 or 5 times a power of ten apart)."""
    import math
    if not hi > lo:
        hi = lo + (abs(lo) or 1.0)
    raw = (hi - lo) / float(n)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    first = math.floor(lo / step) * step
    ticks, t = [], first
    while t <= hi + step * 1e-9:
        ticks.append(round(t, 12))
        t += step
    if ticks[-1] < hi:
        ticks.append(ticks[-1] + step)
    return ticks


class CurveGraph(QtWidgets.QWidget):
    """The material curve drawn as a graph: white plot, grey grid, the points joined by a blue line with
    markers, named axes (a log axis for the S-N cycles)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWMaterialCurveGraph")
        self.setMinimumHeight(170)
        self.kind, self.points = CURVES[0], []

    def set_curve(self, kind, points):
        self.kind, self.points = kind, [tuple(p) for p in points]
        self.update()

    def axes(self):
        """(x label, y label, log x, x ticks, y ticks) for the points shown."""
        import math
        xl, yl, logx = CURVE_AXES.get(self.kind, ("X", "Y", False))
        pts = self.points
        if logx:
            pts = [(x, y) for x, y in pts if x > 0]
        xs = [math.log10(x) if logx else x for x, _y in pts] or [0.0, 1.0]
        ys = [y for _x, y in pts] or [0.0, 1.0]
        if logx:
            xt = list(range(int(math.floor(min(xs))), int(math.ceil(max(xs))) + 1))
            if len(xt) < 2:
                xt = [xt[0], xt[0] + 1]
        else:
            xt = nice_ticks(min(0.0, min(xs)), max(xs))
        yt = nice_ticks(min(0.0, min(ys)), max(ys))
        return xl, yl, logx, xt, yt

    @staticmethod
    def label(v):
        return ("%.3g" % v) if v and (abs(v) >= 1e4 or abs(v) < 1e-2) else ("%g" % v)

    def paintEvent(self, event):
        import math
        xl, yl, logx, xt, yt = self.axes()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor(255, 255, 255))
        fm = p.fontMetrics()
        left = max(fm.horizontalAdvance(self.label(v)) for v in yt) + fm.height() + 12
        bottom, top, right = 2 * fm.height() + 10, 10, 14
        w, h = self.width() - left - right, self.height() - top - bottom
        if w < 20 or h < 20:
            return
        x0, x1, y0, y1 = xt[0], xt[-1], yt[0], yt[-1]

        def at(x, y):
            xv = math.log10(x) if logx else x
            return QtCore.QPointF(left + (xv - x0) / (x1 - x0) * w, top + h - (y - y0) / (y1 - y0) * h)

        p.setPen(QtGui.QPen(QtGui.QColor(215, 215, 215), 1))
        for v in xt:
            X = left + (v - x0) / (x1 - x0) * w
            p.drawLine(QtCore.QPointF(X, top), QtCore.QPointF(X, top + h))
        for v in yt:
            Y = top + h - (v - y0) / (y1 - y0) * h
            p.drawLine(QtCore.QPointF(left, Y), QtCore.QPointF(left + w, Y))
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0), 1))
        p.drawRect(QtCore.QRectF(left, top, w, h))
        for v in xt:
            X = left + (v - x0) / (x1 - x0) * w
            t = ("1e%d" % v) if logx else self.label(v)
            p.drawText(QtCore.QPointF(X - fm.horizontalAdvance(t) / 2.0, top + h + fm.height()), t)
        for v in yt:
            Y = top + h - (v - y0) / (y1 - y0) * h
            t = self.label(v)
            p.drawText(QtCore.QPointF(left - 6 - fm.horizontalAdvance(t), Y + fm.ascent() / 2.0 - 1), t)
        p.drawText(QtCore.QPointF(left + (w - fm.horizontalAdvance(xl)) / 2.0, self.height() - 6), xl)
        p.save()
        p.translate(fm.height() - 2, top + (h + fm.horizontalAdvance(yl)) / 2.0)
        p.rotate(-90)
        p.drawText(QtCore.QPointF(0, 0), yl)
        p.restore()
        pts = [at(x, y) for x, y in self.points if not logx or x > 0]
        if pts:
            p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 200), 2))
            for a, b in zip(pts, pts[1:]):
                p.drawLine(a, b)
            p.setBrush(QtGui.QColor(0, 0, 200))
            for q in pts:
                p.drawEllipse(q, 2.5, 2.5)
        p.end()


HATCHES = ["None", "ANSI31 (Iron BrickStone)", "ANSI32 (Steel)", "ANSI33 (Bronze Brass Copper)", "ANSI34 (Plastic Rubber)",
           "ANSI35 (Fire Brick Refractory)", "ANSI36 (Marble Slate Glass)", "ANSI37 (Lead Zinc Mg Sound Insul)",
           "ANSI38 (Aluminum)", "Wood", "Solid"]
GAUGES = ["None", "Sample Table - Steel - English Units", "Sample Table - Aluminum - Metric Units",
          "Sample Table - Steel - Metric Units"]


# --------------------------------------------------------------------------- data
def _custom_path():
    folder = os.path.join(App.getUserAppDataDir(), "FreeWorks")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "custom-materials.json")


def load_custom():
    """{category: {name: entry}} of the user's Custom Materials."""
    try:
        with open(_custom_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_custom(data):
    save_library(_custom_path(), data)


# --------------------------------------------------------------------------- user libraries

# Library); each is a file of {category: {material: entry}}, in the order the user put them (Move Up,

LIBRARY_EXT = ".fwmat"


def library_folder():
    folder = os.path.join(App.getUserAppDataDir(), "FreeWorks", "Material Libraries")
    os.makedirs(folder, exist_ok=True)
    return folder


def load_library(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_library(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1)


def library_paths():
    """[(library name, file)] of the user's libraries: Custom Materials first, then the libraries
    made with New Library or opened with Open Library, in the order they were added."""
    out = [(CUSTOM, _custom_path())]
    seen = {CUSTOM}
    for path in App.ParamGet(PARAMS).GetString("Libraries", "").split("\n"):
        if path and os.path.isfile(path):
            name = os.path.splitext(os.path.basename(path))[0]
            while name in seen or name == LIBRARY:
                name += " (2)"
            seen.add(name)
            out.append((name, path))
    return out


def add_library_path(path):
    paths = [p for p in App.ParamGet(PARAMS).GetString("Libraries", "").split("\n") if p]
    if path not in paths:
        paths.append(path)
    App.ParamGet(PARAMS).SetString("Libraries", "\n".join(paths))


def remove_library_path(path):
    paths = [p for p in App.ParamGet(PARAMS).GetString("Libraries", "").split("\n") if p and p != path]
    App.ParamGet(PARAMS).SetString("Libraries", "\n".join(paths))


def set_library_order(paths):
    App.ParamGet(PARAMS).SetString("Libraries", "\n".join(p for p in paths if p != _custom_path()))


SORTS = ("library", "category", "material")


def sort_mode():
    """Sort by Library / Category / Material: what the tree is put in name order by ("" keeps the
    order the user made with Move Up and Move Down)."""
    mode = App.ParamGet(PARAMS).GetString("SortBy", "")
    return mode if mode in SORTS else ""


def merge(into, other):
    """Open and Merge: the other library's categories and materials added to into (a material whose
    name is taken gets a (2), (3)...). Returns how many materials came in."""
    n = 0
    for cat, items in other.items():
        if not isinstance(items, dict):
            continue
        dest = into.setdefault(cat, {})
        for name, entry in items.items():
            base, k, new = name, 1, name
            while new in dest:
                k += 1
                new = "%s (%d)" % (base, k)
            dest[new] = entry
            n += 1
    return n


def favorites():
    ""

    p = App.ParamGet(PARAMS)
    text = p.GetString("Favorites", "")
    if not text and not p.GetBool("FavoritesSet", False):
        try:
            from . import fmmenu
            return [label for label, _names in fmmenu._legacy_favorites()]
        except Exception as _fw_err:
            _fw_log("materialdlg.py:favorites", _fw_err)
    return [n for n in text.split("\n") if n]


def set_favorites(names):
    p = App.ParamGet(PARAMS)
    p.SetString("Favorites", "\n".join(names))
    p.SetBool("FavoritesSet", True)


def _si(text, kind):
    """A FreeCAD quantity text as an SI number (None when empty)."""
    if text in (None, ""):
        return None
    try:
        unit = SI_UNIT.get(kind)
        if unit is None:
            return float(str(text).split()[0])
        return float(App.Units.Quantity(text).getValueAs(unit).Value)
    except Exception:
        try:
            return float(text)
        except Exception:
            return None


def _library_entry(folder, name, density, uuid):
    entry = {"name": name, "category": folder, "values": {"Density": float(density)}, "uuid": uuid, "library": True}
    if not uuid:
        # the common names (material.COMMON) carry only a density here: show the full property table the study

        try:
            from . import simmaterial
            v = dict(simmaterial._table(name))
            v.update(simmaterial._library(name))
            v["Density"] = float(density)
            e, nu = v.get("YoungsModulus"), v.get("PoissonRatio")
            if e and nu is not None and "ShearModulus" not in v:
                v["ShearModulus"] = e / (2.0 * (1.0 + nu))
            entry["values"].update({k: x for k, x in v.items() if x is not None})
        except Exception as _fw_err:
            _fw_log("materialdlg.py:common values", _fw_err)
    if uuid:
        try:
            import Materials
            mat = Materials.MaterialManager().getMaterial(uuid)
            phys = dict(mat.PhysicalProperties)
            for _label, key, kind in PROPERTIES:
                value = _si(phys.get(key), kind)
                if value is not None:
                    entry["values"][key] = value
            entry["description"] = phys.get("Description", "") or getattr(mat, "Description", "") or ""
            entry["source"] = phys.get("ProductURL", "") or phys.get("StandardCode", "")
            look = dict(mat.AppearanceProperties)
            colour = look.get("DiffuseColor")
            if colour:
                entry["color"] = [float(x) for x in colour.strip("()").split(",")[:3]]
        except Exception as _fw_err:
            _fw_log("materialdlg.py:248", _fw_err)
    return entry


def entries():
    """[(library, category, entry)] of every material."""
    out = []
    for folder, name, density in material.COMMON:
        out.append((LIBRARY, folder, _library_entry(folder, name, density, "")))
    for folder, name, density, uuid in material._library():
        out.append((LIBRARY, folder, _library_entry(folder, name, density, uuid)))
    for lib, path in library_paths():
        for category, items in load_library(path).items():
            for name, entry in (items.items() if isinstance(items, dict) else ()):
                e = dict(entry, name=name, category=category, library=False)
                out.append((lib, category, e))
    return out


def find(name):
    for lib, cat, e in entries():
        if e["name"] == name:
            return lib, cat, e
    return None


# --------------------------------------------------------------------------- the part
def give_part(doc, entry, use_colour=False, hatch=None):
    """Apply: the part gets the material (density, the rest kept on its Material row)."""
    density = float(entry.get("values", {}).get("Density") or material.DEFAULT_DENSITY)
    material.apply(doc, entry["name"], density, entry.get("uuid", "") or "")
    obj = material.row(doc)
    if obj is not None:
        if "MaterialData" not in obj.PropertiesList:
            obj.addProperty("App::PropertyString", "MaterialData", "Material",
                            "The material's properties, hatch, custom data (JSON)")
        keep = {k: v for k, v in entry.items() if k not in ("library",)}
        if hatch is not None:
            keep["hatch"] = hatch
        keep["use_color"] = bool(use_colour)
        obj.MaterialData = json.dumps(keep, sort_keys=True)
    if use_colour and entry.get("color"):
        try:
            from . import appearance
            bodies = appearance.bodies(doc)
            if bodies:
                rgbt = tuple(entry["color"][:3]) + (0.0,)
                appearance.apply([appearance.Target("part", bodies[0])], rgbt)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: material colour: %s\n" % error)
    doc.recompute()


def part_data(doc):
    obj = material.row(doc)
    try:
        return json.loads(getattr(obj, "MaterialData", "") or "{}") if obj is not None else {}
    except Exception:
        return {}


# --------------------------------------------------------------------------- the dialog
def give_body(body, entry):
    ""

    from . import massprops
    density = float(entry.get("values", {}).get("Density") or material.DEFAULT_DENSITY)
    massprops.set_body_material(body, entry["name"], density)
    body.Document.recompute()


def _number(value):
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


class MaterialDialog(QtWidgets.QDialog):
    def __init__(self, doc, parent=None, body=None):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc
        self.body = body            # set: Edit Material on one body of a multibody part
        self.clip = None
        self.entry = None
        self.lib = None
        self.paths = dict(library_paths())
        self.libs = {name: load_library(path) for name, path in self.paths.items()}
        self.custom = self.libs[CUSTOM]
        self.setWindowTitle(TITLE if body is None else "%s - %s" % (TITLE, body.Label))
        self.setObjectName("SWMaterialDialog")
        self.resize(900, 560)
        outer = QtWidgets.QVBoxLayout(self)
        split = QtWidgets.QHBoxLayout()
        left = QtWidgets.QVBoxLayout()
        self.search = QtWidgets.QLineEdit(self)
        self.search.setObjectName("SWMaterialSearch")
        self.search.setPlaceholderText("Search")
        self.search.setClearButtonEnabled(True)
        left.addWidget(self.search)
        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setObjectName("SWMaterialTree")
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

        # its names' width and the tree scrolls sideways when they are wider than the pane
        self.tree.setTextElideMode(QtCore.Qt.ElideNone)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.tree.setMinimumWidth(230)
        left.addWidget(self.tree, 1)
        split.addLayout(left, 2)
        self.tabs = QtWidgets.QTabWidget(self)
        self.tabs.setObjectName("SWMaterialTabs")
        self.tabs.tabBar().setUsesScrollButtons(False)
        self.tabs.tabBar().setExpanding(False)
        split.addWidget(self.tabs, 5)
        outer.addLayout(split, 1)
        self._properties_tab()
        self._curves_tab()
        self._appearance_tab()
        self._hatch_tab()
        self._custom_tab()
        self._appdata_tab()
        self._favorites_tab()
        self._sheet_tab()
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        self.apply_button = QtWidgets.QPushButton("Apply", self)
        self.close_button = QtWidgets.QPushButton("Close", self)
        self.save_button = QtWidgets.QPushButton("Save", self)
        self.config_button = QtWidgets.QPushButton("Config...", self)
        self.help_button = QtWidgets.QPushButton("Help", self)
        for b, name in ((self.apply_button, "Apply"), (self.close_button, "Close"), (self.save_button, "Save"),
                        (self.config_button, "Config"), (self.help_button, "Help")):
            b.setObjectName("SWMaterial" + name)
            row.addWidget(b)
        outer.addLayout(row)
        self.apply_button.clicked.connect(self.apply)
        self.close_button.clicked.connect(self.close)
        self.save_button.clicked.connect(self.save)
        self.config_button.clicked.connect(self._config)
        self.help_button.clicked.connect(self._help)
        self.tree.currentItemChanged.connect(lambda *a: self._show())
        # a library material's choices stay live: a change is taken back with the note on how to edit it
        self._readonly = False
        for combo, key, items in ((self.model, "model", MODEL_TYPES), (self.criterion, "criterion", CRITERIA),
                                  (self.gauge, "gauge", None)):
            combo.activated.connect(lambda _i, c=combo, k=key, it=items: self._locked(c, k, it))
        self.favs.currentRowChanged.connect(lambda *a: self._fav_buttons())
        self.tree.currentItemChanged.connect(lambda *a: self._fav_buttons())
        self.tree.itemDoubleClicked.connect(lambda item, col: item.data(0, ROLE) and self.apply())
        self.tree.customContextMenuRequested.connect(self._menu)
        self.search.textChanged.connect(self._filter)
        self._fill()

    # --- tabs
    def _properties_tab(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        self.note = QtWidgets.QLabel("", page)
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        form = QtWidgets.QFormLayout()
        self.model = QtWidgets.QComboBox(page)
        self.model.addItems(MODEL_TYPES)
        self.units = QtWidgets.QComboBox(page)
        self.units.setObjectName("SWMaterialUnits")
        self.units.addItems(list(UNITS))
        self.category = QtWidgets.QLineEdit(page)
        self.name = QtWidgets.QLineEdit(page)
        self.name.setObjectName("SWMaterialName")
        self.criterion = QtWidgets.QComboBox(page)
        self.criterion.addItems(CRITERIA)
        self.description = QtWidgets.QLineEdit(page)
        self.source = QtWidgets.QLineEdit(page)
        self.sustain = QtWidgets.QLabel("Undefined", page)
        for label, w in (("Model Type:", self.model), ("Units:", self.units), ("Category:", self.category),
                         ("Name:", self.name), ("Default failure criterion:", self.criterion),
                         ("Description:", self.description), ("Source:", self.source),
                         ("Sustainability:", self.sustain)):
            form.addRow(label, w)
        lay.addLayout(form)
        self.table = QtWidgets.QTableWidget(len(PROPERTIES), 3, page)
        self.table.setObjectName("SWMaterialProperties")
        self.table.setHorizontalHeaderLabels(["Property", "Value", "Units"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        for i, (label, _key, _kind) in enumerate(PROPERTIES):
            item = QtWidgets.QTableWidgetItem(label)
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.table.setItem(i, 0, item)
        lay.addWidget(self.table, 1)
        self.units.currentIndexChanged.connect(lambda i: self._show_values())
        self.tabs.addTab(page, "Properties")

    def _curves_tab(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        self.curve_type = QtWidgets.QComboBox(page)
        self.curve_type.addItems(CURVES)
        lay.addWidget(QtWidgets.QLabel("Type:", page))
        lay.addWidget(self.curve_type)
        self.curve = QtWidgets.QTableWidget(12, 2, page)
        self.curve.setObjectName("SWMaterialCurve")
        self.curve.setHorizontalHeaderLabels(list(CURVE_AXES[CURVES[0]][:2]))
        self.curve.horizontalHeader().setStretchLastSection(True)

        self.graph = CurveGraph(page)
        split = QtWidgets.QSplitter(QtCore.Qt.Vertical, page)
        split.setObjectName("SWMaterialCurveSplit")
        split.addWidget(self.curve)
        split.addWidget(self.graph)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)
        self._curve_shown = CURVES[0]
        self.curve_type.currentIndexChanged.connect(lambda i: self._show_curve())
        self.curve.itemChanged.connect(lambda *_: self._draw_curve())
        self.tabs.addTab(page, "Tables && Curves")

    def _appearance_tab(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        self.use_colour = QtWidgets.QCheckBox("Use material color", page)
        self.use_colour.setObjectName("SWMaterialUseColor")
        lay.addWidget(self.use_colour)
        self.swatch = QtWidgets.QPushButton("", page)
        self.swatch.setObjectName("SWMaterialColor")
        self.swatch.setFixedSize(120, 40)
        self.swatch.setToolTip("The material's colour (custom materials: click to change)")
        self.swatch.clicked.connect(self._pick_colour)
        lay.addWidget(self.swatch)
        lay.addStretch(1)
        self.tabs.addTab(page, "Appearance")

    def _hatch_tab(self):
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        self.hatch = QtWidgets.QComboBox(page)
        self.hatch.setObjectName("SWMaterialHatch")
        self.hatch.addItems(HATCHES)
        self.hatch_angle = QtWidgets.QDoubleSpinBox(page)
        self.hatch_angle.setRange(-360, 360)
        self.hatch_angle.setSuffix(" °")
        self.hatch_scale = QtWidgets.QDoubleSpinBox(page)
        self.hatch_scale.setRange(0.01, 1000)
        self.hatch_scale.setValue(1.0)
        form.addRow("Pattern:", self.hatch)
        form.addRow("Angle:", self.hatch_angle)
        form.addRow("Scale:", self.hatch_scale)
        self.tabs.addTab(page, "CrossHatch")

    def _custom_tab(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        self.customs = QtWidgets.QTableWidget(8, 2, page)
        self.customs.setObjectName("SWMaterialCustom")
        self.customs.setHorizontalHeaderLabels(["Name", "Value"])
        self.customs.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.customs)
        self.tabs.addTab(page, "Custom")

    def _appdata_tab(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        self.appdata = QtWidgets.QPlainTextEdit(page)
        self.appdata.setObjectName("SWMaterialAppData")
        lay.addWidget(self.appdata)
        self.tabs.addTab(page, "Application Data")

    def _favorites_tab(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(page)
        self.favs = QtWidgets.QListWidget(page)
        self.favs.setObjectName("SWMaterialFavorites")
        lay.addWidget(self.favs, 1)
        side = QtWidgets.QVBoxLayout()
        for text, fn in (("Add", self._fav_add), ("Delete", self._fav_remove), ("Move Up", lambda: self._fav_move(-1)),
                         ("Move Down", lambda: self._fav_move(1))):
            b = QtWidgets.QPushButton(text, page)
            b.setObjectName("SWMaterialFav" + text.replace(" ", ""))
            b.clicked.connect(fn)
            side.addWidget(b)
        side.addStretch(1)
        lay.addLayout(side)
        self.favs.addItems(favorites())
        self.tabs.addTab(page, "Favorites")

    def _sheet_tab(self):
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        self.gauge = QtWidgets.QComboBox(page)
        self.gauge.setObjectName("SWMaterialGauge")
        self.gauge.addItems(GAUGES)
        form.addRow("Gauge table:", self.gauge)
        self.tabs.addTab(page, "Sheet Metal")

    # --- the tree
    def _fill(self):
        # no currentItemChanged while the rows go: Qt reports a row being deleted as current
        self.tree.blockSignals(True)
        try:
            self.tree.setCurrentItem(None)
            self.tree.clear()
        finally:
            self.tree.blockSignals(False)
        names = [LIBRARY] + [n for n, _p in library_paths()]
        mode = sort_mode()
        if mode == "library":
            names.sort(key=str.lower)
        roots = {n: QtWidgets.QTreeWidgetItem(self.tree, [n]) for n in names}
        cats = {}
        now = material.current(self.doc)[1]
        chosen = None
        for lib, cat, e in entries():
            key = (lib, cat)
            if key not in cats:
                cats[key] = QtWidgets.QTreeWidgetItem(roots[lib], [cat])
                cats[key].setData(0, ROLE + 1, (lib, cat))
            item = QtWidgets.QTreeWidgetItem(cats[key], [e["name"]])
            item.setData(0, ROLE, (lib, cat, e))
            if e["name"] == now and chosen is None:
                chosen = item
        for lib, data in self.libs.items():
            for cat in data:
                if (lib, cat) not in cats and lib in roots:
                    cats[(lib, cat)] = QtWidgets.QTreeWidgetItem(roots[lib], [cat])
                    cats[(lib, cat)].setData(0, ROLE + 1, (lib, cat))
        if mode in ("category", "material"):
            for r in roots.values():
                if mode == "category":
                    r.sortChildren(0, QtCore.Qt.AscendingOrder)
                else:
                    for j in range(r.childCount()):
                        r.child(j).sortChildren(0, QtCore.Qt.AscendingOrder)
        for r in roots.values():
            r.setExpanded(True)
            r.setData(0, ROLE + 1, (r.text(0), None))
        if chosen is not None:
            self.tree.setCurrentItem(chosen)
            chosen.parent().setExpanded(True)
        data = part_data(self.doc)
        if data:
            self.use_colour.setChecked(bool(data.get("use_color")))
        self._show()

    def _filter(self, text):
        text = text.strip().lower()

        def walk(item):
            shown = 0
            for j in range(item.childCount()):
                child = item.child(j)
                if child.data(0, ROLE):
                    hide = bool(text) and text not in child.text(0).lower()
                    child.setHidden(hide)
                    shown += not hide
                else:
                    n = walk(child)
                    child.setHidden(n == 0 and bool(text))
                    if text:
                        child.setExpanded(n > 0)
                    shown += n
            return shown
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    def _picked(self):
        item = self.tree.currentItem()
        return item.data(0, ROLE) if item is not None else None

    def _locked(self, combo, key, items):
        if not self._readonly or self.entry is None:
            return
        now = self.entry.get(key, "None" if items is None else "")
        combo.blockSignals(True)
        if items is None:
            combo.setCurrentText(now)
        else:
            combo.setCurrentIndex(max(0, items.index(now) if now in items else 0))
        combo.blockSignals(False)
        self._flash_note()

    def _flash_note(self):
        self.note.setText("Materials in the default library can not be edited. Copy the material and Paste it "
                          "into Custom Materials (right-click in the tree) to change it.")
        self.note.setStyleSheet("color: #b00000;")
        QtCore.QTimer.singleShot(2500, lambda: self.note.setStyleSheet(""))

    def _fav_buttons(self):
        """Favorites: Add while a material is picked in the tree, Delete / Move Up / Move Down while a
        favourite is picked and it can go that way (no buttons that do nothing)."""
        data = self._picked()
        name = data[2]["name"] if data else None
        row, n = self.favs.currentRow(), self.favs.count()
        for b, on in ((self.findChild(QtWidgets.QPushButton, "SWMaterialFavAdd"), bool(name) and name not in favorites()),
                      (self.findChild(QtWidgets.QPushButton, "SWMaterialFavDelete"), 0 <= row < n),
                      (self.findChild(QtWidgets.QPushButton, "SWMaterialFavMoveUp"), 0 < row < n),
                      (self.findChild(QtWidgets.QPushButton, "SWMaterialFavMoveDown"), 0 <= row < n - 1)):
            if b is not None:
                b.setVisible(on)

    def _show(self):
        data = self._picked()
        # Apply only on a material; Save only on a material of a library of the user's own (no dead buttons)
        self.apply_button.setVisible(data is not None)
        self.save_button.setVisible(data is not None and data[0] != LIBRARY)
        if data is None:
            self.entry = None
            self.note.setText("Pick a material.")
            return
        self.lib, cat, e = data
        self.entry = copy.deepcopy(e)
        editable = self.lib != LIBRARY
        self._readonly = not editable
        self.note.setStyleSheet("")
        self.note.setText("Material properties: materials in the default library can not be edited. "
                          "You must first copy the material to a custom library to edit it."
                          if not editable else "Material properties: edit the values, then Save.")
        self.category.setText(cat)
        self.name.setText(e["name"])
        self.description.setText(e.get("description", ""))
        self.source.setText(e.get("source", ""))
        for w in (self.category, self.name, self.description, self.source):
            w.setReadOnly(not editable)
        for combo, key, items in ((self.model, "model", MODEL_TYPES), (self.criterion, "criterion", CRITERIA)):
            combo.setCurrentIndex(max(0, items.index(e[key]) if e.get(key) in items else 0))
        self._show_values()
        self._show_curve()
        colour = e.get("color") or [0.8, 0.8, 0.8]
        self.swatch.setStyleSheet("background: rgb(%d,%d,%d);" % tuple(int(c * 255) for c in colour[:3]))
        hatch = e.get("hatch") or {}
        self.hatch.setCurrentText(hatch.get("pattern", "ANSI32 (Steel)" if "Steel" in cat else "ANSI31 (Iron BrickStone)"))
        self.hatch_angle.setValue(float(hatch.get("angle", 0.0)))
        self.hatch_scale.setValue(float(hatch.get("scale", 1.0)))
        rows = sorted((e.get("custom") or {}).items())
        self.customs.clearContents()
        for i, (k, v) in enumerate(rows[:self.customs.rowCount()]):
            self.customs.setItem(i, 0, QtWidgets.QTableWidgetItem(k))
            self.customs.setItem(i, 1, QtWidgets.QTableWidgetItem(str(v)))
        self.appdata.setPlainText(e.get("appdata", ""))
        self.gauge.setCurrentText(e.get("gauge", "None"))
        for w in (self.customs, self.curve):
            w.setEditTriggers(QtWidgets.QAbstractItemView.AllEditTriggers if editable
                              else QtWidgets.QAbstractItemView.NoEditTriggers)
        self.appdata.setReadOnly(not editable)
        self.curve_type.setEnabled(True)

    def _show_values(self):
        if self.entry is None:
            return
        system = UNITS[self.units.currentText()]
        editable = self.lib != LIBRARY
        values = self.entry.get("values", {})
        for i, (_label, key, kind) in enumerate(PROPERTIES):
            unit, factor = system[kind]
            value = _number(values.get(key))
            item = QtWidgets.QTableWidgetItem("" if value is None else "%.6g" % (value * factor))
            if not editable:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.table.setItem(i, 1, item)
            u = QtWidgets.QTableWidgetItem(unit)
            u.setFlags(u.flags() & ~QtCore.Qt.ItemIsEditable)
            self.table.setItem(i, 2, u)

    def _curve_points(self):
        """The points typed in the table, in order, skipping blank or bad rows."""
        points = []
        for i in range(self.curve.rowCount()):
            a, b = self.curve.item(i, 0), self.curve.item(i, 1)
            try:
                if a is not None and b is not None and a.text().strip() and b.text().strip():
                    points.append([float(a.text()), float(b.text())])
            except ValueError:
                pass
        return points

    def _show_curve(self):
        if self.entry is None:
            return
        kind = self.curve_type.currentText()
        old = getattr(self, "_curve_shown", None)
        if old and old != kind and self.lib != LIBRARY:       # keep the points typed for the curve left
            self.entry.setdefault("curves", {})[old] = self._curve_points()
        self._curve_shown = kind
        points = (self.entry.get("curves") or {}).get(kind, [])
        self.curve.blockSignals(True)
        try:
            self.curve.clearContents()
            self.curve.setRowCount(max(12, len(points) + 1))
            self.curve.setHorizontalHeaderLabels(list(CURVE_AXES.get(kind, ("X", "Y"))[:2]))
            for i, (x, y) in enumerate(points):
                self.curve.setItem(i, 0, QtWidgets.QTableWidgetItem("%g" % x))
                self.curve.setItem(i, 1, QtWidgets.QTableWidgetItem("%g" % y))
        finally:
            self.curve.blockSignals(False)
        self._draw_curve()

    def _draw_curve(self):
        g = getattr(self, "graph", None)
        if g is not None:
            g.set_curve(self.curve_type.currentText(), self._curve_points())

    def _read_back(self):
        """The edits on the tabs into self.entry (custom materials)."""
        e = self.entry
        if e is None or self.lib == LIBRARY:
            return e
        system = UNITS[self.units.currentText()]
        values = {}
        for i, (_label, key, kind) in enumerate(PROPERTIES):
            item = self.table.item(i, 1)
            try:
                v = float(item.text()) if item is not None and item.text().strip() else None
            except ValueError:
                v = None
            if v is not None:
                values[key] = v / system[kind][1]
        e["values"] = values
        e["description"], e["source"] = self.description.text(), self.source.text()
        e["model"], e["criterion"] = self.model.currentText(), self.criterion.currentText()
        e.setdefault("curves", {})[self.curve_type.currentText()] = self._curve_points()
        custom = {}
        for i in range(self.customs.rowCount()):
            a, b = self.customs.item(i, 0), self.customs.item(i, 1)
            if a is not None and a.text().strip():
                custom[a.text().strip()] = b.text() if b is not None else ""
        e["custom"] = custom
        e["appdata"] = self.appdata.toPlainText()
        e["gauge"] = self.gauge.currentText()
        e["hatch"] = self._hatch()
        return e

    def _hatch(self):
        return {"pattern": self.hatch.currentText(), "angle": self.hatch_angle.value(), "scale": self.hatch_scale.value()}

    def _pick_colour(self):
        if self.entry is None:
            return
        if self.lib == LIBRARY:
            self._flash_note()          # a library material's colour: how to change it
            return
        c = self.entry.get("color") or [0.8, 0.8, 0.8]
        got = QtWidgets.QColorDialog.getColor(QtGui.QColor.fromRgbF(*c[:3]), self, "Material color")
        if got.isValid():
            self.entry["color"] = [got.redF(), got.greenF(), got.blueF()]
            self.swatch.setStyleSheet("background: %s;" % got.name())

    # --- buttons
    def apply(self):
        e = self._read_back()
        if e is None:
            return
        if self.body is not None:
            give_body(self.body, e)
            return
        give_part(self.doc, e, self.use_colour.isChecked(), self._hatch())

    def save(self):
        """Save: Custom Materials (with the edits on the tabs) to the custom library file."""
        e = self._read_back()
        lib = self.lib if self.lib in self.libs else CUSTOM
        if e is not None and self.lib != LIBRARY:
            old_name = self.tree.currentItem().text(0)
            cat = self.category.text().strip() or "Custom"
            name = self.name.text().strip() or old_name
            prev = self._picked()[1]
            self.libs[lib].get(prev, {}).pop(old_name, None)
            stored = {k: v for k, v in e.items() if k not in ("name", "category", "library")}
            self.libs[lib].setdefault(cat, {})[name] = stored
        self._save(lib)
        current = self.name.text()
        self._fill()
        self._select(current)

    def _select(self, name, lib=None):
        """Pick a material by name (a custom one first, as a new or saved material is custom)."""
        found = [item for item in self.rows() if item.data(0, ROLE) and item.text(0) == name]
        found.sort(key=lambda i: (i.data(0, ROLE)[0] != (lib or CUSTOM), i.data(0, ROLE)[0] == LIBRARY))
        if found:
            self.tree.setCurrentItem(found[0])

    def _config(self):
        """Config...: where the material libraries are kept (FreeCAD's material settings)."""
        try:
            Gui.showPreferences("Material")
        except Exception:
            Gui.runCommand("Std_DlgPreferences", 0)

    def _help(self):
        QtWidgets.QMessageBox.information(self, TITLE, HELP)


    # Move Down / Cut, Copy, Paste / New Library, New Category, New Material / Open Library, Open and
    # Merge / Sort by Library, Sort by Category, Sort by Material)
    def _save(self, lib):
        if lib in self.paths:
            save_library(self.paths[lib], self.libs[lib])

    def _where(self, item):
        """(kind, library, category, material name) of a tree row: kind is material, category,
        library or None."""
        if item is None:
            return None, None, None, None
        data, place = item.data(0, ROLE), item.data(0, ROLE + 1)
        if data:
            return "material", data[0], data[1], data[2]["name"]
        if place and place[1]:
            return "category", place[0], place[1], None
        if place:
            return "library", place[0], None, None
        return None, None, None, None

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is not None:
            self.tree.setCurrentItem(item)
        menu = self.context_menu(item)
        if not menu.isEmpty():
            menu.exec_(self.tree.viewport().mapToGlobal(pos))

    def context_menu(self, item):
        kind, lib, cat, name = self._where(item)
        own = lib is not None and lib != LIBRARY
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("SWMaterialTreeMenu")

        def add(text, fn):
            act = menu.addAction(text)
            act.triggered.connect(lambda *a: fn())
            return act
        if kind == "material":
            add("Edit", lambda: self.edit_material(item))
        if own and kind in ("material", "category") or kind == "library" and lib not in (CUSTOM, LIBRARY):
            add("Rename", lambda: self.rename(item))
            add("Delete", lambda: self.delete(item))
        menu.addSeparator()
        if kind == "material":
            add("Add to Favorites", lambda: self._fav_add(name))
        if kind is not None and (own or kind == "library"):
            if self._sibling(item, -1) is not None:
                add("Move Up", lambda: self.move(item, -1))
            if self._sibling(item, 1) is not None:
                add("Move Down", lambda: self.move(item, 1))
        menu.addSeparator()
        if kind == "material" and own:
            add("Cut", lambda: self.copy_material(item, cut=True))
        if kind == "material":
            add("Copy", lambda: self.copy_material(item))
        if own and self.clip is not None:
            add("Paste", lambda: self.paste(item))
        menu.addSeparator()
        add("New Library", self.new_library)
        if own or kind is None:
            add("New Category", lambda: self.new_category(library=lib if own else CUSTOM))
        if own and kind in ("category", "material"):
            add("New Material", lambda: self.new_material(category=cat, library=lib))
        menu.addSeparator()
        add("Open Library", self.open_library)
        if own or kind is None:
            add("Open and Merge", lambda: self.open_and_merge(lib if own else CUSTOM))
        menu.addSeparator()
        mode = sort_mode()
        for text, key in (("Sort by Library", "library"), ("Sort by Category", "category"),
                          ("Sort by Material", "material")):
            act = add(text, lambda k=key: self.sort_by(k))
            act.setCheckable(True)
            act.setChecked(mode == key)
        return menu

    def _category_at(self, item):
        kind, lib, cat, _n = self._where(item)
        return cat or "Custom"

    def _library_at(self, item):
        kind, lib, _c, _n = self._where(item)
        return lib if lib in self.libs else CUSTOM

    def _sibling(self, item, step):
        parent = item.parent()
        if parent is None:
            index = self.tree.indexOfTopLevelItem(item)
            if index <= 0 and step < 0 or item.text(0) in (LIBRARY, CUSTOM):
                return None
            other = self.tree.topLevelItem(index + step)
            return other if other is not None and other.text(0) not in (LIBRARY, CUSTOM) else None
        index = parent.indexOfChild(item)
        if 0 <= index + step < parent.childCount():
            return parent.child(index + step)
        return None

    def edit_material(self, item):
        ""

        kind, lib, cat, name = self._where(item)
        if lib == LIBRARY:
            self.copy_material(item)
            self.paste(None, category=cat, library=CUSTOM)
        self.tabs.setCurrentIndex(0)
        self.name.setFocus()
        self.name.selectAll()

    def new_library(self, name=None):
        name = name or QtWidgets.QInputDialog.getText(self, TITLE, "Library name:", text="New Library")[0]
        if not name:
            return None
        base, k, path = name, 1, os.path.join(library_folder(), name + LIBRARY_EXT)
        while os.path.exists(path):
            k += 1
            path = os.path.join(library_folder(), "%s (%d)%s" % (base, k, LIBRARY_EXT))
        save_library(path, {})
        add_library_path(path)
        self._reload()
        return path

    def open_library(self, path=None):
        path = path or QtWidgets.QFileDialog.getOpenFileName(
            self, "Open Library", library_folder(), "Material libraries (*%s *.json)" % LIBRARY_EXT)[0]
        if path and os.path.isfile(path):
            add_library_path(path)
            self._reload()
        return path

    def open_and_merge(self, library=CUSTOM, path=None):
        path = path or QtWidgets.QFileDialog.getOpenFileName(
            self, "Open and Merge", library_folder(), "Material libraries (*%s *.json)" % LIBRARY_EXT)[0]
        if not path or not os.path.isfile(path):
            return 0
        n = merge(self.libs[library], load_library(path))
        self._save(library)
        self._fill()
        return n

    def sort_by(self, mode):
        App.ParamGet(PARAMS).SetString("SortBy", "" if sort_mode() == mode else mode)
        current = self._picked()
        self._fill()
        if current:
            self._select(current[2]["name"], current[0])

    def _reload(self):
        self.paths = dict(library_paths())
        for name, path in self.paths.items():
            if name not in self.libs:
                self.libs[name] = load_library(path)
        self.libs = {n: self.libs[n] for n in self.paths}
        self.custom = self.libs[CUSTOM]
        self._fill()

    def move(self, item, step):
        """Move Up / Move Down: a material within its category, a category within its library, a
        library in the list (the order is kept; the tree leaves Sort by)."""
        kind, lib, cat, name = self._where(item)
        App.ParamGet(PARAMS).SetString("SortBy", "")
        if kind == "library":
            order = [p for n, p in library_paths() if n != CUSTOM]
            i = order.index(self.paths[lib])
            j = i + step
            if 0 <= j < len(order):
                order[i], order[j] = order[j], order[i]
                set_library_order(order)
            self._reload()
            self._select_place(lib, None)
            return
        data = self.libs[lib]
        if kind == "category":
            keys = list(data)
            i = keys.index(cat)
            j = i + step
            if 0 <= j < len(keys):
                keys[i], keys[j] = keys[j], keys[i]
                self.libs[lib] = {k: data[k] for k in keys}
        else:
            items = data[cat]
            keys = list(items)
            i = keys.index(name)
            j = i + step
            if 0 <= j < len(keys):
                keys[i], keys[j] = keys[j], keys[i]
                data[cat] = {k: items[k] for k in keys}
        if lib == CUSTOM:
            self.custom = self.libs[CUSTOM]
        self._save(lib)
        self._fill()
        if kind == "category":
            self._select_place(lib, cat)
        else:
            self._select(name, lib)

    def rows(self):
        """Every row of the tree, depth first (no QTreeWidgetItemIterator: Qt keeps a live iterator
        in a list it updates as rows are deleted, and one left behind crashes the next refill)."""
        out = []

        def walk(item):
            for j in range(item.childCount()):
                child = item.child(j)
                out.append(child)
                walk(child)
        walk(self.tree.invisibleRootItem())
        return out

    def _select_place(self, lib, cat):
        for item in self.rows():
            if item.data(0, ROLE + 1) == (lib, cat):
                self.tree.setCurrentItem(item)
                return

    def new_category(self, name=None, library=None):
        library = library or self._library_at(self.tree.currentItem())
        name = name or QtWidgets.QInputDialog.getText(self, TITLE, "Category name:", text="New Category")[0]
        if name:
            self.libs[library].setdefault(name, {})
            self._save(library)
            self._fill()

    def new_material(self, name=None, category=None, library=None):
        library = library or self._library_at(self.tree.currentItem())
        category = category or self._category_at(self.tree.currentItem())
        name = name or QtWidgets.QInputDialog.getText(self, TITLE, "Material name:", text="New Material")[0]
        if name:
            self.libs[library].setdefault(category, {})[name] = {"values": {"Density": material.DEFAULT_DENSITY}}
            self._save(library)
            self._fill()
            self._select(name, library)

    def copy_material(self, item, cut=False):
        kind, lib, cat, name = self._where(item)
        if kind == "material":
            self.clip = copy.deepcopy(item.data(0, ROLE)[2])
            self.cut_from = (lib, cat, name) if cut and lib != LIBRARY else None

    def paste(self, item, category=None, library=None):
        if self.clip is None:
            return
        library = library or self._library_at(item)
        category = category or self._category_at(item)
        cut = getattr(self, "cut_from", None)
        if cut is not None:
            lib, cat, old = cut
            if (lib, cat) == (library, category):
                return
            self.libs.get(lib, {}).get(cat, {}).pop(old, None)
            self._save(lib)
            self.cut_from = None
        name = self.clip["name"]
        items = self.libs[library].setdefault(category, {})
        base, n = name, 1
        while name in items:
            n += 1
            name = "%s (%d)" % (base, n)
        items[name] = {k: v for k, v in self.clip.items() if k not in ("name", "category", "library", "uuid")}
        if cut is not None:
            self.clip = None
        self._save(library)
        self._fill()
        self._select(name, library)

    def rename(self, item, name=None):
        kind, lib, cat, old = self._where(item)
        current = {"material": old, "category": cat, "library": lib}.get(kind)
        name = name or QtWidgets.QInputDialog.getText(self, TITLE, "New name:", text=current)[0]
        if not name or name == current:
            return
        if kind == "material":
            items = self.libs[lib][cat]
            self.libs[lib][cat] = {(name if k == old else k): v for k, v in items.items()}
        elif kind == "category":
            data = self.libs[lib]
            self.libs[lib] = {(name if k == cat else k): v for k, v in data.items()}
        elif kind == "library":

            old_path = self.paths[lib]
            new_path = os.path.join(os.path.dirname(old_path), name + os.path.splitext(old_path)[1])
            if os.path.exists(new_path):
                return
            save_library(new_path, self.libs[lib])
            order = [new_path if p == old_path else p for n, p in library_paths() if n != CUSTOM]
            set_library_order(order)        # the old file is left where it was
            self._reload()
            return
        if lib == CUSTOM:
            self.custom = self.libs[CUSTOM]
        self._save(lib)
        self._fill()
        if kind == "material":
            self._select(name, lib)

    def delete(self, item, ask=True):
        """Delete: a material, a category (with its materials) or a library (taken off the list; its
        file stays on disk)."""
        kind, lib, cat, name = self._where(item)
        what = {"material": name, "category": cat, "library": lib}.get(kind)
        if ask and kind != "material":
            reply = QtWidgets.QMessageBox.question(self, TITLE, "Delete %s?" % what)
            if reply != QtWidgets.QMessageBox.Yes:
                return
        if kind == "material":
            self.libs[lib].get(cat, {}).pop(name, None)
        elif kind == "category":
            self.libs[lib].pop(cat, None)
        elif kind == "library":
            remove_library_path(self.paths[lib])
            self._reload()
            return
        self._save(lib)
        self._fill()

    def _fav_add(self, name=None):
        if not isinstance(name, str):
            data = self._picked()
            name = data[2]["name"] if data else None
        if name and name not in favorites():
            set_favorites(favorites() + [name])
            self.favs.addItem(name)

    def _fav_remove(self):
        row = self.favs.currentRow()
        if row >= 0:
            names = favorites()
            names.pop(row) if row < len(names) else None
            set_favorites(names)
            self.favs.takeItem(row)

    def _fav_move(self, step):
        row = self.favs.currentRow()
        names = favorites()
        to = row + step
        if 0 <= row < len(names) and 0 <= to < len(names):
            names[row], names[to] = names[to], names[row]
            set_favorites(names)
            self.favs.clear()
            self.favs.addItems(names)
            self.favs.setCurrentRow(to)


_dialog = None


def edit(doc=None, body=None):
    global _dialog
    doc = doc or (body.Document if body is not None else App.ActiveDocument)
    if doc is None:
        return None
    if _dialog is not None:
        try:
            _dialog.close()
        except RuntimeError as _fw_err:
            _fw_log("materialdlg.py:1114", _fw_err)
    _dialog = MaterialDialog(doc, body=body)
    _dialog.show()
    if body is not None:
        try:
            from . import massprops
            name = massprops.body_material(body)[0]
            if name:
                _dialog._select(name)
        except Exception as _fw_err:
            _fw_log("materialdlg.py:1124", _fw_err)
    return _dialog


def apply_favorite(doc, name):
    found = find(name)
    if found is not None:
        data = part_data(doc)
        give_part(doc, found[2], bool(data.get("use_color")), (found[2].get("hatch") or None))
