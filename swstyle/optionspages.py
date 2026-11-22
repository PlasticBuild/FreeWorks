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

import os

import FreeCAD as App
import re

from PySide import QtCore, QtGui, QtWidgets

from . import paths
from .sketchoptions import GENERAL as SK_GENERAL, PREFERENCES, SKETCHER, Bool, Number, Setting, _param

Qt = QtCore.Qt
VIEW = "View"
DOCUMENT = "Document"
TREE = "TreeView"
NOT_YET = "Not in FreeCAD yet"
PLANNED = []


def _fw():
    return paths.params()


# ---------------------------------------------------------------- writing
_managed = []


def _is_managed(path, key):
    """True when the look writes this entry at every start."""
    if not _managed:
        try:
            from . import style
            _managed.append({(p, n) for p, _k, n, _v in style._settings()})
        except Exception:
            _managed.append(set())
    return (PREFERENCES + path, key) in _managed[0]


def write(path, kind, key, value):
    """Writes one FreeCAD setting; for an entry the look sets at every start, as the user's own."""
    if _is_managed(path, key):
        from . import style
        style.set_user_setting(PREFERENCES + path, kind, key, value)
        return
    grp = _param(path)
    {"Boolean": grp.SetBool, "Integer": grp.SetInt, "Unsigned Long": grp.SetUnsigned,
     "Float": grp.SetFloat, "String": grp.SetString}[kind](key, value)


def forget(path, kind, key):
    """Drops the user's own value of an entry the look sets: the look's value comes back."""
    if _is_managed(path, key):
        from . import style
        style.set_user_setting(PREFERENCES + path, kind, key, None)


def _cosmetic():
    """cosmeticthread.py's settings (it redraws when they change)."""
    from . import cosmeticthread
    return App.ParamGet(cosmeticthread.PARAMS)


# ---------------------------------------------------------------- setting kinds
class BoolFn(Bool):
    """A check box over read() and write(value) instead of one parameter."""

    def __init__(self, key, text, read, write, tip="", needs=None, indent=False):
        super().__init__("", key, False, text, tip, needs, indent)
        self.read, self.write = read, write

    def load(self):
        try:
            self.box.setChecked(bool(self.read()))
        except Exception:
            self.box.setChecked(False)
        self.loaded = self.value()

    def save(self):
        if self.changed():
            self.write(self.value())
            self.loaded = self.value()


class LookBool(Bool):
    """A FreeCAD check box whose entry the look may also set (kept as the user's own)."""

    def save(self):
        if self.changed():
            write(self.path, "Boolean", self.key, self.value())
            self.loaded = self.value()


class SwFixed(Setting):
    ""

    def __init__(self, text, on=True, tip=""):
        super().__init__("", "fixed:" + text, on, text, tip or "Always on")

    def widget(self):
        self.box = QtWidgets.QCheckBox(self.text)
        self.box.setChecked(bool(self.default))
        self.box.setEnabled(False)
        self.box.setToolTip(self.tip)
        self.box.setProperty("swFixed", True)
        return self.box

    def value(self):
        return self.default

    def load(self):
        self.loaded = self.default

    def save(self):
        pass


STORE = "Options"


CHOICES = {
    ("Units", "Decimal rounding"): ("Round half away from zero", "Round half towards zero", "Round half to even",
                                    "Truncate without rounding"),
    ("Drawings/Display Style", "Display style"): ("Wireframe", "Hidden lines visible", "Hidden lines removed",
                                                 "Shaded with edges", "Shaded"),
    ("Display Style", "Display style"): ("Wireframe", "Hidden lines visible", "Hidden lines removed",
                                        "Shaded with edges", "Shaded"),
    ("Display Style", "Tangent edges"): ("Visible", "Use font", "Removed"),
    ("Display Style", "Edge quality for new views"): ("High quality", "Draft quality"),
    ("Area Hatch/Fill", "Hatch"): ("None", "Solid", "Hatch"),
    ("Area Hatch/Fill", "Pattern"): ("ANSI31 (Iron BrickStone)", "ANSI32 (Steel)", "ANSI33 (Bronze Brass)",
                                     "ANSI34 (Plastic Rubber)", "ANSI35 (Fire Brick)", "ANSI36 (Marble)",
                                     "ANSI37 (Lead Zinc)", "ANSI38 (Aluminum)", "Concrete", "Earth", "Wood"),
    ("Colors", "Icon color"): ("Default", "Classic"),
    ("Colors", "Current color scheme"): ("Default", "Blue Highlight", "Green Highlight", "Orange Highlight"),  # extapps82
    ("General", "Custom property used as component description"): ("Description", "Title", "Number", "Revision"),
    ("Colors", "Default scene"): ("00 3 point faded", "01 3 point white", "02 Plain white", "03 Studio room"),
    ("Display", "Projection type for four view viewport"): ("First Angle", "Third Angle"),
    ("Performance", "Curvature generation"): ("Only on demand", "Always (for every shaded model)"),
    ("Performance", "Level of detail"): ("Off", "More (slower)", "Less (faster)"),     # extapps86: slider order
    ("Performance", "Magnetic mate proximity"): ("Less", "Medium", "More"),
    ("Assemblies", "Update out-of-date Speedpak configurations when saving files"): ("None", "All", "Prompt"),
    ("External References", "Load referenced documents"): ("Prompt", "All", "None", "Changed"),
    ("External References", "Update out-of-date linked design tables to"): ("Prompt", "Model", "Excel file"),
    ("File Locations", "Show folders for"): ("Document Templates", "Reference Documents", "Sheet Formats",
                                             "Design Library", "Macros", "Material Databases", "Hole Callout Format File",
                                             "Custom Property Files", "Bend Tables", "Appearances", "Decals", "Textures"),
    ("View", "Mouse speed"): ("Slow", "Medium", "Fast"),
    ("View", "Hide/show component"): ("Off", "Slow", "Medium", "Fast"),
    ("View", "Isolate"): ("Off", "Slow", "Medium", "Fast"),
    ("View", "View selector"): ("Off", "Slow", "Medium", "Fast"),
    ("Touch", "Touch Mode"): ("Right Hand", "Left Hand"),
    ("Hole Wizard/Toolbox", "Hole Wizard settings"): ("Transfer settings when changing Hole Wizard hole type",
                                                      "Preserve settings for each Hole Wizard hole type"),
    ("Messages/Errors/Warnings", "When rebuild error occurs"): ("Prompt", "Stop", "Continue"),
    ("Messages/Errors/Warnings", "Display FeatureManager tree warnings"): ("Always", "Never", "All but top level"),
    ("Messages/Errors/Warnings", "Display circular references in equations"): ("In equation dialog only",
                                                                               "Equation dialog and FeatureManager"),
    ("Messages/Errors/Warnings", "Display potential circular references"): ("In equation dialog only",
                                                                           "Equation dialog and FeatureManager"),
    ("Import", "Solid and Surface"): ("Try forming solid(s)", "Knit surface(s)", "Do not knit"),
    ("Import", "Unit"): ("File specified unit", "Document template specified unit"),
    ("Import", "Import as"): ("Graphics Body", "Solid Body", "Surface Body"),
    ("Import", "Unit (STL, OBJ, OFF, PLY)"): ("Millimeters", "Centimeters", "Meters", "Inches", "Feet"),
    ("Fixed", "Unit"): ("File specified unit", "Document template specified unit"),
    ("Search", "Indexing performance"): ("Index only when computer is idle", "Always index"),
    ("Configurations", "Default Bill Of Materials part number for new configurations"): ("Document Name",
                                                                                         "Configuration Name"),
    ("Sketch", "Turn off Automatic Solve Mode and Undo when sketch contains more than"): (
        "1000 sketch entities", "2000 sketch entities", "5000 sketch entities", "10000 sketch entities"),
}


# text -> choices, for rows of that name on any page
TEXT_CHOICES = {
    "Leader style": ("Straight", "Bent", "Underlined"),
    "Leader thickness": ("Thin", "Normal", "Thick"),
    "Leader anchor": ("Closest", "Left", "Right"),
    "Arrows": ("Outside", "Inside", "Smart"),
    "Arrow placement": ("Outside", "Inside", "Smart"),
    "Arrow style": ("Filled", "Open", "Slash", "Dot", "Datum triangle"),
    "Frame style": ("Square", "Circular", "None"),
    "Frame thickness": ("Thin", "Normal", "Thick"),
    "Line style": ("Solid", "Dashed", "Phantom"),
    "Line thickness": ("Thin", "Normal", "Thick"),
    "Box thickness": ("Thin", "Normal", "Thick"),
    "Grid thickness": ("Thin", "Normal", "Thick"),
    "Leading zeroes": ("Standard", "Show", "Remove"),
    "Trailing zeroes": ("Smart", "Show", "Remove", "Standard"),
    "Trailing zeroes, dimensions": ("Smart", "Show", "Remove", "Standard"),
    "Trailing zeroes, tolerances": ("Smart", "Show", "Remove", "Standard"),
    "Trailing zeroes, properties": ("Smart", "Show", "Remove", "Standard"),
    "Primary precision": ("0", ".1", ".12", ".123", ".1234", ".12345"),
    "Dual precision": ("0", ".1", ".12", ".123", ".1234", ".12345"),
    "Precision": ("0", ".1", ".12", ".123", ".1234"),
    "Angle precision": ("0", ".1", ".12", ".123"),
    "Primary tolerance precision": ("Same as nominal", "0", ".1", ".12", ".123"),
    "Dual tolerance precision": ("Same as nominal", "0", ".1", ".12", ".123"),
    "Tolerance": ("None", "Basic", "Bilateral", "Limit", "Symmetric", "MIN", "MAX", "Fit"),
    "Text position": ("Solid leader, aligned text", "Broken leader, horizontal text", "Broken leader, aligned text"),
    "Dual dimension position": ("Top", "Bottom", "Right", "Left"),
    "Fraction style": ("Stacked", "Diagonal", "Horizontal", "Diagonal stacked"),
    "Anchor": ("Top Left", "Top Right", "Bottom Left", "Bottom Right"),
    "Style": ("Circular", "Triangle", "Hexagon", "Box", "Diamond", "Flag", "Underline", "None"),
    "Size": ("Tight Fit", "1 Character", "2 Characters", "3 Characters", "4 Characters", "5 Characters"),
    "Stacked Style": ("Circular", "Triangle", "Hexagon", "Box", "Diamond", "Flag", "Underline", "None"),
    "Stacked Size": ("Tight Fit", "1 Character", "2 Characters", "3 Characters", "4 Characters", "5 Characters"),
    "Upper": ("Item Number", "Quantity", "Part Number", "Custom Property"),
    "Lower": ("Quantity", "Item Number", "Part Number", "Custom Property", "None"),
    "Display type": ("Per Standard", "Square", "Round (GB)"),
    "Format": ("1 X 45°", "45° X 1", "C1"),
    "Scheme": ("Letters", "Numbers"),
    "Alpha/numerical control": ("A, B, C...", "1, 2, 3..."),
    "Virtual sharp style": ("Plus", "Plus with lines", "Star", "Dot", "Hollow dot", "Witness lines"),
    "Methods": ("Block Tolerance", "General Tolerance"),
    "Fillet options": ("Symmetric", "Asymmetric"),
    "Chamfer options": ("Symmetric", "Asymmetric"),
    "Slot dimensioning": ("Width and length", "Width only"),
    "Slot location": ("Center", "End"),
    "Primary datums, form": ("Flatness", "None"),
    "Dimension style": ("Baseline", "Chain"),
    "Pattern dimensioning": ("Linear", "Polar"),
    "Dimensions, redundant": ("Hide", "Show"),
    "Tolerances, redundant": ("Hide", "Show"),
    "Bend line notes": ("Show", "Hide"),
    "Bend direction": ("Up/Down", "Arrow"),
    "Bend note style": ("Above Bend Line", "Below Bend Line", "With Leader", "Inline"),
    "Bead weight": ("Mass from bead volume", "Mass per unit length"),
    "Edge/vertex": ("Filled", "Open", "Dot", "None"),
    "Face/surface": ("Dot", "Filled", "Open", "None"),
    "Unattached": ("Filled", "Open", "Dot", "None"),
    "Zero quantity display": ("0", "-", "Blank"),
    "Missing component": ("Display with strikethrough", "Hide the row"),
    "Default Bill Of Materials part number for new configurations": ("Document Name", "Configuration Name"),
    "Weld bead display": ("Simplified", "Full"),
}


def _store_key(page, text):
    import re
    return re.sub(r"[^A-Za-z0-9]+", "_", "%s__%s" % (page, text)).strip("_")[:120]


def _store():
    return _param("Mod/FreeWorks/" + STORE)


def stored(page, text, default=None):
    ""
    key = _store_key(page, text)
    g = _store()
    if isinstance(default, bool):
        return g.GetBool(key, default)
    if isinstance(default, int):
        return g.GetInt(key, default)
    if isinstance(default, float):
        return g.GetFloat(key, default)
    got = g.GetString(key, "")
    return got if got else default


def set_stored(page, text, value):
    key = _store_key(page, text)
    g = _store()
    if isinstance(value, bool):
        g.SetBool(key, value)
    elif isinstance(value, int):
        g.SetInt(key, value)
    elif isinstance(value, float):
        g.SetFloat(key, value)
    else:
        g.SetString(key, str(value))


# Part and assembly Document Properties rows for annotations a part never has (balloons, weld symbols,

# does not apply. A drawing's own Document Properties (drawdocprops.py) have these and use them.
DRAWING_ONLY = "Applies to drawings: set it in the drawing's Document Properties"
GREYED = {(p, t): DRAWING_ONLY for p, t in (
    ("Balloons", "Font"), ("Surface Finishes", "Font"), ("Surface Finishes", "Leader style"),
    ("Weld Symbols", "Font"), ("Geometric Tolerances", "Leader style"), ("Geometric Tolerances", "Frame style"),
    ("Angular Running", "Font"), ("Angular Running", "Primary precision"), ("Arc Length", "Font"),
    ("Arc Length", "Primary precision"), ("Arc Length", "Arrows"), ("Chamfer", "Font"), ("Chamfer", "Format"),
    ("Chamfer", "Primary precision"), ("Hole Callout", "Font"), ("Ordinate", "Font"),
    ("Ordinate", "Primary precision"), ("Tables", "Font"), ("Bend", "Precision"))}



HIDDEN = set()   # no row is left off: the 15 first listed all have readers (11-19 recheck)



def hidden(setting):
    """True for a kept-with-FreeCAD row that no code reads (look audit 11-19): the box leaves it off."""
    return isinstance(setting, Later) and (setting.page, setting.text) in HIDDEN


# Rows of the drafting sub-pages that no code reads in a part: left off, not shown dead (options-1119)
UNREAD = {("Balloons", "Leader style"), ("Annotations", "Leader style")}

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class SwatchButton(QtWidgets.QPushButton):
    """A colour button: the swatch shows the colour, a click opens the colour picker. text()/setText()
    give and take the colour as #RRGGBB, so kept settings load and save it as before."""

    def __init__(self, title="", empty_ok=False):
        super().__init__()
        self._empty_ok = empty_ok          # "" = not set (a feature colour that follows the part's)
        self._hex = "" if empty_ok else "#000000"
        self._title = title
        self.setFixedSize(56, 22)
        self.clicked.connect(self._pick)
        if empty_ok:
            self.setContextMenuPolicy(Qt.CustomContextMenu)
            self.customContextMenuRequested.connect(self._menu)

    def text(self):
        return self._hex

    def setText(self, value):
        value = str(value or "")
        if _HEX.match(value):
            self._hex = value.upper()
        elif self._empty_ok and not value:
            self._hex = ""
        if not self._hex:
            QtWidgets.QPushButton.setText(self, "Default")
            self.setToolTip("%s: not set (the part's colour). Click to pick one." % self._title)
            self.setStyleSheet("")
            return
        QtWidgets.QPushButton.setText(self, "")
        self.setToolTip("%s: %s" % (self._title, self._hex))
        self.setStyleSheet("QPushButton { background: %s; border: 1px solid #808080; }" % self._hex)

    def _fit(self):
        """look-audit optcut-1120: a colour that may be unset is wide enough for "Default" (56 px cut it to
        "Defaul"), measured with the style the button is shown with."""
        if not self._empty_ok:
            return
        keep = QtWidgets.QPushButton.text(self)
        QtWidgets.QPushButton.setText(self, "Default")
        wide = QtWidgets.QPushButton.sizeHint(self).width()
        QtWidgets.QPushButton.setText(self, keep)
        self.setFixedSize(max(56, wide), 22)

    def showEvent(self, event):
        self._fit()
        QtWidgets.QPushButton.showEvent(self, event)

    def _menu(self, pos):
        menu = QtWidgets.QMenu(self)
        menu.addAction("Use Default", lambda: self.setText(""))
        menu.exec_(self.mapToGlobal(pos))

    def _pick(self):
        colour = QtWidgets.QColorDialog.getColor(QtGui.QColor(self._hex or "#C8C8C8"), self, self._title or "Color")
        if colour.isValid():
            self.setText(colour.name())



SHOWN = {
    ("General", "Check for solutions when the program crashes"): "Check for solutions when FreeCAD crashes",
    ("General", "Enable sounds for events"): "Enable sounds for FreeCAD events",
    ("Backup/Recover", "Backup folder"): "",
}
EDITABLE = {("General", "Custom property used as component description")}

FONT_ROWS = ("Font", "Name font", "Label font")
FONT_ASK = {}       # checks: {"family": name} answers the Choose Font box


def choose_font(parent, family):
    ""
    if FONT_ASK.get("family"):
        return FONT_ASK["family"]
    box = QtWidgets.QDialog(parent)
    box.setWindowTitle("Choose Font")
    lay = QtWidgets.QVBoxLayout(box)
    lay.addWidget(QtWidgets.QLabel("Font:"))
    pick = QtWidgets.QFontComboBox(box)
    pick.setObjectName("SWChooseFontList")
    pick.setCurrentFont(QtGui.QFont(family))
    lay.addWidget(pick)
    sample = QtWidgets.QLabel("AaBbYyZz", box)
    sample.setMinimumHeight(48)
    sample.setFont(QtGui.QFont(pick.currentFont().family(), 16))
    pick.currentFontChanged.connect(lambda f: sample.setFont(QtGui.QFont(f.family(), 16)))
    lay.addWidget(sample)
    bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, box)
    bb.accepted.connect(box.accept)
    bb.rejected.connect(box.reject)
    lay.addWidget(bb)
    if box.exec_() != QtWidgets.QDialog.Accepted:
        return None
    return pick.currentFont().family()


class Later(Setting):
    ""



    def __init__(self, text, default=None, page=""):
        super().__init__("Mod/FreeWorks/" + STORE, _store_key(page, text), default, text, "")
        self.page = page
        if (page, text) not in PLANNED:
            PLANNED.append((page, text))

    def _choices(self):
        return CHOICES.get((self.page, self.text)) or TEXT_CHOICES.get(self.text)

    def widget(self):
        shown = SHOWN.get((self.page, self.text), self.text)
        if isinstance(self.default, bool):
            self.box = QtWidgets.QCheckBox(shown)
            self.tag(self.box)
            self._grey()
            return self.box
        row = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        label = QtWidgets.QLabel(shown)
        choices = self._choices()
        if choices:
            self.box = QtWidgets.QComboBox()
            self.box.addItems(list(choices))
            self.box.setEditable((self.page, self.text) in EDITABLE)
            if self.default is not None and str(self.default) not in choices:
                self.box.addItem(str(self.default))
        elif isinstance(self.default, (int, float)):
            self.box = QtWidgets.QDoubleSpinBox()
            self.box.setRange(-1e6, 1e6)
            self.box.setDecimals(0 if isinstance(self.default, int) else 3)
        elif isinstance(self.default, str) and _HEX.match(self.default):
            self.box = SwatchButton(self.text)
        elif self.default == "" and self.text.lower().endswith(" color"):
            self.box = SwatchButton(self.text, empty_ok=True)     # a colour not set yet (Model Display)
        else:
            self.box = QtWidgets.QLineEdit()
            self.box.setMinimumWidth(220)
        self.box.setObjectName("SWKept_" + self.key)
        self.tag(self.box)
        self._grey(label)
        label.setBuddy(self.box)
        lay.addWidget(label)
        lay.addWidget(self.box, 1 if isinstance(self.box, QtWidgets.QLineEdit) else 0)
        if self.text in FONT_ROWS and isinstance(self.box, QtWidgets.QLineEdit):
            self.box.setReadOnly(True)
            button = QtWidgets.QPushButton("Font...", row)
            button.setObjectName("SWFontButton_" + self.key)

            def pick(_c=False, box=self.box, button=button):
                family = choose_font(button.window(), box.text() or str(self.default or ""))
                if family:
                    box.setText(family)
            button.clicked.connect(pick)
            lay.addWidget(button)
        lay.addStretch(1)
        return row

    def _grey(self, label=None):
        why = GREYED.get((self.page, self.text))
        if why:
            for w in (self.box, label):
                if w is not None:
                    w.setEnabled(False)
                    w.setToolTip(why)

    def value(self):
        b = self.box
        if isinstance(b, QtWidgets.QCheckBox):
            return b.isChecked()
        if isinstance(b, QtWidgets.QComboBox):
            return b.currentText()
        if isinstance(b, QtWidgets.QDoubleSpinBox):
            return int(b.value()) if isinstance(self.default, int) else b.value()
        return b.text()

    def _read(self):
        return stored(self.page, self.text, self.default)

    def load(self):
        v = self._read()
        b = self.box
        if isinstance(b, QtWidgets.QCheckBox):
            b.setChecked(bool(v))
        elif isinstance(b, QtWidgets.QComboBox):
            i = b.findText(str(v)) if v is not None else 0
            b.setCurrentIndex(max(i, 0))
            if i < 0 and b.isEditable() and v:
                b.setEditText(str(v))
        elif isinstance(b, QtWidgets.QDoubleSpinBox):
            b.setValue(float(v or 0))
        else:
            b.setText("" if v is None else str(v))
        self.loaded = self.value()

    def save(self):
        if self.changed():
            set_stored(self.page, self.text, self.value())
            self.loaded = self.value()
            try:
                from . import optionsextras
                optionsextras.refresh_options()
            except Exception as _fw_err:
                _fw_log("optionspages.py:458", _fw_err)


def Fixed(text, on=True, tip=""):
    ""

    row = Later(text, bool(on), "Fixed")
    if tip:
        row.tip = tip
    return row


class FolderLater(Later):
    ""



    def __init__(self, text, page=""):
        super().__init__(text, "", page)

    @staticmethod
    def real_folder():
        try:
            return os.path.normpath(App.getTempPath())
        except Exception:
            return ""

    def widget(self):
        row = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        label = QtWidgets.QLabel(SHOWN.get((self.page, self.text), self.text))
        self.box = QtWidgets.QLineEdit()
        self.box.setMinimumWidth(220)
        self.box.setObjectName("SWKept_" + self.key)
        self.tag(self.box)
        label.setBuddy(self.box)
        browse = QtWidgets.QPushButton("...")
        browse.setObjectName("SWKeptBrowse_" + self.key)
        browse.setFixedWidth(_browse_width(browse))     # look-audit optcut-1120: narrow, "..." whole
        browse.clicked.connect(self._browse)
        lay.addWidget(label)
        lay.addWidget(self.box, 1)
        lay.addWidget(browse)
        return row

    def _browse(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self.box.window(), self.text, self.box.text())
        if path:
            self.box.setText(os.path.normpath(path))

    def _read(self):
        v = str(stored(self.page, self.text, "") or "")
        return v if v and os.path.isdir(v) else self.real_folder()


def FixedValue(text, shown, tip=""):
    ""
    row = Later(text, shown, "Fixed")
    if tip:
        row.tip = tip
    return row


class Radio(Setting):
    ""


    def __init__(self, key, text, choices, read, write, tip=""):
        super().__init__("", key, None, text, tip)
        self.choices, self.read, self.write = choices, read, write

    def widget(self):
        box = QtWidgets.QGroupBox(self.text) if self.text else QtWidgets.QWidget()
        box.setObjectName("SWRadio_" + self.key)
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(6, 4, 6, 4)
        self.group = QtWidgets.QButtonGroup(box)
        self.buttons = []
        for i, (label, value) in enumerate(self.choices):
            b = QtWidgets.QRadioButton(label)
            b.setToolTip(NOT_YET if value is None else self.tip)
            b.setEnabled(value is not None)
            self.group.addButton(b, i)
            lay.addWidget(b)
            self.buttons.append(b)
        self.box = box
        return box

    def value(self):
        i = self.group.checkedId()
        return self.choices[i][1] if i >= 0 else None

    def set(self, value):
        values = [v for _l, v in self.choices]
        if value in values:
            self.buttons[values.index(value)].setChecked(True)

    def load(self):
        try:
            self.set(self.read())
        except Exception as _fw_err:
            _fw_log("optionspages.py:516", _fw_err)
        self.loaded = self.value()

    def save(self):
        if self.changed() and self.value() is not None:
            self.write(self.value())
            self.loaded = self.value()


class Combo(Setting):
    """A drop-down list over read() and write(value); choices may be a function."""

    def __init__(self, key, text, choices, read, write, tip=""):
        super().__init__("", key, None, text, tip)
        self.choices, self.read, self.write = choices, read, write

    def _choices(self):
        return self.choices() if callable(self.choices) else self.choices

    def widget(self):
        row = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        label = QtWidgets.QLabel(self.text)
        self.box = QtWidgets.QComboBox()
        self.box.setObjectName("SWCombo_" + self.key)
        self.box.setToolTip(self.tip)
        self.listed = list(self._choices())
        for text, _v in self.listed:
            self.box.addItem(text)
        label.setBuddy(self.box)
        lay.addWidget(label)
        lay.addWidget(self.box)
        lay.addStretch(1)
        return row

    def value(self):
        i = self.box.currentIndex()
        return self.listed[i][1] if 0 <= i < len(self.listed) else None

    def load(self):
        values = [v for _t, v in self.listed]
        try:
            current = self.read()
        except Exception:
            current = None
        self.box.setCurrentIndex(values.index(current) if current in values else 0)
        self.loaded = self.value()

    def save(self):
        if self.changed():
            self.write(self.value())
            self.loaded = self.value()


class NumberFn(Number):
    """A number box over read() and write(value)."""

    def __init__(self, key, text, unit, low, high, read, write, decimals=0, tip="", needs=None):
        super().__init__("", key, 0, text, unit, low, high, decimals, tip, needs)
        self.read, self.write = read, write

    def load(self):
        self.box.setValue(self.read())
        self.loaded = self.value()

    def save(self):
        if self.changed():
            self.write(self.value())
            self.loaded = self.value()


class QualityFn(NumberFn):
    ""


    STEPS = 100

    def widget(self):
        row = super().widget()
        holder = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        line = QtWidgets.QHBoxLayout()
        self.slider = QtWidgets.QSlider(Qt.Horizontal)
        self.slider.setObjectName("SWQuality_" + self.key)
        self.slider.setRange(0, self.STEPS)
        self.slider.setFixedWidth(220)
        self.slider.setToolTip(self.tip)
        line.addWidget(QtWidgets.QLabel("Low (faster)"))
        line.addWidget(self.slider)
        line.addWidget(QtWidgets.QLabel("High (slower)"))
        line.addStretch(1)
        lay.addLayout(line)
        lay.addWidget(row)
        self._quiet = False
        self.slider.valueChanged.connect(self._from_slider)
        self.box.valueChanged.connect(self._from_box)
        return holder

    def _span(self):
        import math
        low, high = max(self.box.minimum(), 1e-6), max(self.box.maximum(), 1e-6)
        return math.log(low), math.log(high)

    partner = None     # the shaded slider also moves the curves' angular deviation (QualityFn), as


    def _from_slider(self, v):
        if self._quiet:
            return
        import math
        lo, hi = self._span()
        self._quiet = True
        self.box.setValue(math.exp(hi - (hi - lo) * v / float(self.STEPS)))     # right = high quality = small
        self._quiet = False
        other = self.partner
        if other is not None and getattr(other, "box", None) is not None:
            try:
                other.box.setValue(shaded_angular(v / float(self.STEPS)))
            except RuntimeError as _fw_err:
                _fw_log("optionspages.py:637", _fw_err)

    def _from_box(self, value):
        if self._quiet:
            return
        import math
        lo, hi = self._span()
        t = (hi - math.log(max(value, 1e-6))) / (hi - lo) if hi > lo else 0.0
        self._quiet = True
        self.slider.setValue(int(round(max(0.0, min(1.0, t)) * self.STEPS)))
        self._quiet = False

    def load(self):
        super().load()
        self._from_box(self.box.value())


class Slider(Setting):
    ""

    STOPS = ("Off", "Slow", "Medium", "Fast")

    def __init__(self, key, text, read, write, tip=""):
        super().__init__("", key, None, text, tip)
        self.read, self.write = read, write

    def widget(self):
        row = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        label = QtWidgets.QLabel(self.text)
        label.setMinimumWidth(130)
        self.box = QtWidgets.QSlider(Qt.Horizontal)
        self.box.setObjectName("SWSlider_" + self.key)
        self.box.setRange(0, len(self.STOPS) - 1)
        self.box.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.box.setPageStep(1)
        self.box.setFixedWidth(160)
        self.box.setToolTip(self.tip)
        self.shown = QtWidgets.QLabel()
        self.box.valueChanged.connect(lambda v: self.shown.setText(self.STOPS[v]))
        lay.addWidget(label)
        lay.addWidget(QtWidgets.QLabel("Off"))
        lay.addWidget(self.box)
        lay.addWidget(QtWidgets.QLabel("Fast"))
        lay.addStretch(1)
        return row

    def value(self):
        return self.box.value()

    def load(self):
        self.box.setValue(int(self.read()))
        self.shown.setText(self.STOPS[self.box.value()])
        self.loaded = self.value()

    def save(self):
        if self.changed():
            self.write(self.value())
            self.loaded = self.value()


class PercentSlider(Setting):
    ""


    def __init__(self, key, text, read, write, low=0, high=100, step=1, left="0%", right="100%", off_stop=False,
                 tip="", indent=False):
        super().__init__("", key, None, text, tip, None, indent)
        self.read, self.write = read, write
        self.low, self.high, self.step, self.left, self.right, self.off_stop = low, high, step, left, right, off_stop

    def _stops(self):
        values = list(range(self.low, self.high + 1, self.step))
        return ([0] if self.off_stop else []) + values

    def widget(self):
        row = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(20 if self.indent else 0, 0, 0, 0)
        if self.text:
            label = QtWidgets.QLabel(self.text)
            label.setMinimumWidth(130)
            lay.addWidget(label)
        self.box = QtWidgets.QSlider(Qt.Horizontal)
        self.box.setObjectName("SWPercent_" + self.key)
        self.box.setRange(0, len(self._stops()) - 1)
        self.box.setPageStep(1)
        self.box.setFixedWidth(200)
        self.box.setToolTip(self.tip)
        lay.addWidget(QtWidgets.QLabel(self.left))
        lay.addWidget(self.box)
        lay.addWidget(QtWidgets.QLabel(self.right))
        lay.addStretch(1)
        return row

    def value(self):
        return self._stops()[self.box.value()]

    def load(self):
        stops = self._stops()
        try:
            v = int(self.read())
        except Exception:
            v = stops[-1]
        self.box.setValue(min(range(len(stops)), key=lambda i: abs(stops[i] - v)))
        self.loaded = self.value()

    def save(self):
        if self.changed():
            self.write(self.value())
            self.loaded = self.value()


class ModeRadio(Radio):
    """extapps86: round buttons the rows under them hang off (needs = this key): they show while the button
    whose value is shows is picked. A hidden check box carries that state for options.py."""

    def __init__(self, key, text, choices, read, write, tip="", shows=None):
        super().__init__(key, text, choices, read, write, tip)
        self.shows = shows

    def widget(self):
        w = super().widget()
        self.box = QtWidgets.QCheckBox(w)
        self.box.setObjectName("SWModeShows_" + self.key)
        self.box.setVisible(False)
        self.group.buttonToggled.connect(lambda *_a: self.box.setChecked(self.value() == self.shows))
        return w

    def load(self):
        super().load()
        self.box.setChecked(self.value() == self.shows)


class Note(Setting):
    ""

    def __init__(self, text):
        super().__init__("", "note:" + text[:40], None, text, "")

    def widget(self):
        self.box = QtWidgets.QLabel(self.text)
        self.box.setWordWrap(True)
        return self.box

    def value(self):
        return None

    def load(self):
        self.loaded = None

    def save(self):
        pass


class LaterSlider(Later):
    ""


    def widget(self):
        row = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        label = QtWidgets.QLabel(self.text)
        label.setMinimumWidth(130)
        self.stops = list(self._choices() or (str(self.default),))
        self.box = QtWidgets.QSlider(Qt.Horizontal)
        self.box.setObjectName("SWKept_" + self.key)
        self.box.setRange(0, len(self.stops) - 1)
        self.box.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.box.setPageStep(1)
        self.box.setFixedWidth(160)
        self.tag(self.box)
        lay.addWidget(label)
        lay.addWidget(QtWidgets.QLabel(self.stops[0]))
        lay.addWidget(self.box)
        lay.addWidget(QtWidgets.QLabel(self.stops[-1]))
        lay.addStretch(1)
        return row

    def value(self):
        return self.stops[self.box.value()]

    def load(self):
        v = str(self._read())
        self.box.setValue(self.stops.index(v) if v in self.stops else len(self.stops) - 1)
        self.loaded = self.value()


class BackupFolder(FolderLater):
    """extapps82: Backup/Recover > Backup folder: until one is picked, the add-on's own Backups folder."""

    def real_folder(self):
        return ""       # empty: the default folder, named in the box's grey hint

    def widget(self):
        row = super().widget()
        self.box.setPlaceholderText("Backups folder in FreeCAD's user data folder")
        return row


def _backup_here_read():
    return "here" if stored("Fixed", "Save backup files in the same location as the original", True) else "folder"


def _backup_here_write(value):
    set_stored("Fixed", "Save backup files in the same location as the original", value == "here")


def _configure_sounds(dialog=None):
    ""
    import subprocess
    try:
        subprocess.Popen(["control.exe", "mmsys.cpl,,2"])
    except Exception as _fw_err:
        _fw_log("optionspages.py:sounds", _fw_err)


class Button(Setting):
    """A push button (Go To ...): run(dialog), dialog being the Options box."""

    def __init__(self, text, run, tip=""):
        super().__init__("", "button:" + text, None, text, tip)
        self.run = run

    def widget(self):
        row = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        self.box = QtWidgets.QPushButton(self.text)
        self.box.setObjectName("SWGoTo")
        self.box.setToolTip(self.tip)
        self.box.clicked.connect(lambda _c=False: self.run(self.box.window()))
        lay.addWidget(self.box)
        lay.addStretch(1)
        return row

    def value(self):
        return None

    def load(self):
        self.loaded = None

    def save(self):
        pass


def _browse_width(button):
    ""
    return max(28, button.fontMetrics().horizontalAdvance("...") + 28)


class PathFn(Setting):
    """A path box with "..." over read() and write(path); folder=True picks a folder."""

    def __init__(self, key, text, read, write, folder=False, filt="All files (*)", tip=""):
        super().__init__("", key, None, text, tip)
        self.read, self.write, self.folder, self.filt = read, write, folder, filt

    def widget(self):
        row = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QtWidgets.QLabel(self.text))
        self.box = QtWidgets.QLineEdit()
        self.box.setObjectName("SWPath_" + self.key)
        self.box.setMinimumWidth(260)
        self.box.setToolTip(self.tip)
        lay.addWidget(self.box, 1)
        b = QtWidgets.QPushButton("...")
        b.setFixedWidth(_browse_width(b))       # look-audit optcut-1120: 28 px cut "..." to "."
        b.clicked.connect(self._browse)
        lay.addWidget(b)
        return row

    def _browse(self):
        if self.folder:
            got = QtWidgets.QFileDialog.getExistingDirectory(self.box, self.text, self.box.text())
        else:
            got, _f = QtWidgets.QFileDialog.getOpenFileName(self.box, self.text, self.box.text(), self.filt)
        if got:
            self.box.setText(got)

    def value(self):
        return self.box.text().strip()

    def load(self):
        try:
            self.box.setText(self.read() or "")
        except Exception:
            self.box.setText("")
        self.loaded = self.value()

    def save(self):
        if self.changed():
            self.write(self.value())
            self.loaded = self.value()


class TextFn(Setting):
    """A one-line text box over read() and write(text); secret=True hides what is typed."""

    def __init__(self, key, text, read, write, tip="", secret=False):
        super().__init__("", key, None, text, tip)
        self.read, self.write, self.secret = read, write, secret

    def widget(self):
        row = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QtWidgets.QLabel(self.text))
        self.box = QtWidgets.QLineEdit()
        self.box.setObjectName("SWText_" + self.key)
        self.box.setMinimumWidth(260)
        self.box.setToolTip(self.tip)
        if self.secret:
            self.box.setEchoMode(QtWidgets.QLineEdit.Password)
        lay.addWidget(self.box, 1)
        return row

    def value(self):
        return self.box.text().strip()

    def load(self):
        try:
            self.box.setText(self.read() or "")
        except Exception:
            self.box.setText("")
        self.loaded = self.value()

    def save(self):
        if self.changed():
            self.write(self.value())
            self.loaded = self.value()


class FolderList(Setting):
    ""


    def __init__(self, kinds, read, write):
        super().__init__("", "folders:FileLocations", None, "Show folders for", "")
        self.kinds, self.read, self.write = kinds, read, write

    def widget(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel(self.text))
        self.kind = QtWidgets.QComboBox()
        self.kind.setObjectName("SWFolderKind")
        self.kind.addItems(list(self.kinds))
        top.addWidget(self.kind)
        top.addStretch(1)
        lay.addLayout(top)
        mid = QtWidgets.QHBoxLayout()
        self.box = QtWidgets.QListWidget()
        self.box.setObjectName("SWFolderList")
        mid.addWidget(self.box, 1)
        col = QtWidgets.QVBoxLayout()
        for text, fn in (("Edit All", self._edit_all), ("Add...", self._add), ("Delete", self._delete),
                         ("Move Up", lambda: self._move(-1)),
                         ("Move Down", lambda: self._move(1))):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(lambda _c=False, fn=fn: fn())
            col.addWidget(b)
        col.addStretch(1)
        mid.addLayout(col)
        lay.addLayout(mid)
        self.kind.currentIndexChanged.connect(self._show)
        return w

    def _keep(self):
        k = getattr(self, "_shown", None)
        if k is not None:
            self.data[k] = [self.box.item(i).text() for i in range(self.box.count())]

    def _show(self, _i=None):
        self._keep()
        self._shown = self.kind.currentText()
        self.box.clear()
        self.box.addItems(self.data.get(self._shown, []))

    def _edit_all(self):
        ""
        self._keep()
        d = QtWidgets.QDialog(self.box.window())
        d.setObjectName("SWEditAllLocations")
        d.setWindowTitle("Edit All")
        lay = QtWidgets.QVBoxLayout(d)
        table = QtWidgets.QTableWidget(len(self.kinds), 2, d)
        table.setObjectName("SWEditAllTable")
        table.setHorizontalHeaderLabels(["Folder type", "Folders"])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        for i, k in enumerate(self.kinds):
            kind = QtWidgets.QTableWidgetItem(k)
            kind.setFlags(kind.flags() & ~Qt.ItemIsEditable)
            table.setItem(i, 0, kind)
            table.setItem(i, 1, QtWidgets.QTableWidgetItem(";".join(self.data.get(k, []))))
        table.resizeColumnToContents(0)
        lay.addWidget(table)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, d)
        buttons.accepted.connect(d.accept)
        buttons.rejected.connect(d.reject)
        lay.addWidget(buttons)
        d.resize(640, 360)
        self.edit_all_dialog = d        # checks reach it
        if d.exec() == QtWidgets.QDialog.Accepted:
            self.take_all({table.item(i, 0).text(): table.item(i, 1).text() for i in range(table.rowCount())})

    def take_all(self, texts):
        for k, text in texts.items():
            self.data[k] = [f.strip() for f in str(text).split(";") if f.strip()]
        self._shown = None
        self._show()

    def _add(self):
        got = QtWidgets.QFileDialog.getExistingDirectory(self.box, "Add folder")
        if got:
            self.box.addItem(got)

    def _delete(self):
        for item in self.box.selectedItems():
            self.box.takeItem(self.box.row(item))

    def _move(self, step):
        r = self.box.currentRow()
        if r < 0 or not 0 <= r + step < self.box.count():
            return
        item = self.box.takeItem(r)
        self.box.insertItem(r + step, item)
        self.box.setCurrentRow(r + step)

    def value(self):
        self._keep()
        return {k: list(v) for k, v in self.data.items()}

    def load(self):
        self.data = {k: self.read(k) for k in self.kinds}
        self._shown = None
        self._show()
        self.loaded = {k: list(v) for k, v in self.data.items()}

    def save(self):
        now = self.value()
        for k, v in now.items():
            if v != self.loaded.get(k):
                self.write(k, v)
        self.loaded = now


def go_to(tab, title):
    """A Go To button: the Options box shows a page of the other (or the same) tab."""
    def run(dialog):
        tabs = getattr(dialog, "tabs", None)
        if tabs is None or not tabs.isTabEnabled(tab):
            return
        if tabs.currentIndex() != tab:
            tabs.setCurrentIndex(tab)
        dialog.select(title)
    return run


# ---------------------------------------------------------------- colours
def _to_qcolor(u):
    return QtGui.QColor((u >> 24) & 255, (u >> 16) & 255, (u >> 8) & 255)


def _to_unsigned(c):
    return (c.red() << 24) | (c.green() << 16) | (c.blue() << 8) | 255


SK = "Mod/Sketcher/General"

COLOR_ROWS = (
    ("Selected Item 1", [(VIEW, "SelectionColor"), (VIEW, "SketchSelectionColor")]),
    ("Selected Item 2", None), ("Selected Item 3", None), ("Selected Item 4", None),
    ("Selected Item 5", None), ("Selected Item 6", None),
    ("Viewport Background", [(VIEW, "BackgroundColor")]),
    ("Top Gradient Color", [(VIEW, "BackgroundColor2")]),
    ("Bottom Gradient Color", [(VIEW, "BackgroundColor3")]),
    ("Dynamic Highlight", [(VIEW, "HighlightColor")]),
    ("Highlight", None),                  # treehover.py: the tree row's item outlined in the view
    ("Measure Highlight", None),          # measure.py: the measured items
    # optioncolors-1119: Selected Item Missing Reference, Dimensions Preview and Sketch Not Solved are left
    # out: nothing in FreeCAD draws those items, so the rows could only save a colour that changes nothing
    ("Selected Face, Shaded", [("Mod/FreeWorks", "SelectedFaceShaded")]),      # flatselect.py
    ("Dimensions, Imported (Driving)", [(VIEW, "ConstrainedDimColor")]),
    ("Dimensions, Non Imported (Driven)", [(VIEW, "NonDrivingConstrDimColor")]),
    ("Dimensions, Dangling", [("Mod/FreeWorks", "DanglingColor")]),     # rebuilderrors.py
    ("Sketch, Over Defined", [(VIEW, "OverDefinedColor")]),
    ("Sketch, Fully Defined", [(VIEW, "FullyConstrainedColor"), (VIEW, "FullyConstraintElementColor")]),
    ("Sketch, Under Defined", [(VIEW, "EditedEdgeColor")]),
    ("Sketch, Invalid Geometry", [(VIEW, "InvalidSketchColor")]),
    ("Sketch, Inactive", [(VIEW, "SketchEdgeColor")]),
    ("Grid Lines, Minor", [(SK, "GridLineColor")]),
    ("Grid Lines, Major", [(SK, "GridDivLineColor")]),
    ("Construction Geometry", [(VIEW, "ConstructionColor")]),
    ("Temporary Graphics", [(VIEW, "CreateLineColor")]),
    ("Temporary Graphics Shaded", None),  # pmpreview.py: a feature's shaded preview (when Add/Remove Material are not set)
    ("Add Material", None),               # pmpreview.py: a boss's preview
    ("Remove Material", None),            # pmpreview.py: a cut's preview
    ("Surfaces, Open Edges", None),
    ("Edges In Shaded With Edges Mode", [(VIEW, "DefaultShapeLineColor")]),
    ("FeatureManager Design Tree Text", None),          # style.qss(): the FeatureManager tree's text
    ("Flyout FeatureManager Design Tree Text", None),   # flyouttree.tree_qss(): the flyout tree's text
)
# Selected Item 2-6: propertymanager._qss(), the colour strip of the 2nd..6th selection box on a page


class ColorButton(Setting):
    """One colour: a label and a swatch button that opens the colour box."""

    def __init__(self, path, key, text, tip=""):
        super().__init__(path, key, None, text, tip)

    def widget(self):
        row = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        label = QtWidgets.QLabel(self.text)
        self.box = QtWidgets.QPushButton()
        self.box.setObjectName("SWColorButton_" + self.key)
        self.box.setFixedSize(60, 20)
        self.box.setToolTip(self.tip)
        self.box.clicked.connect(self.pick)
        label.setBuddy(self.box)
        lay.addWidget(label)
        lay.addWidget(self.box)
        lay.addStretch(1)
        return row

    def _paint(self):
        self.box.setStyleSheet("background:%s; border:1px solid #888;" % self.color.name())

    def set_color(self, color):
        self.color = QtGui.QColor(color)
        self._paint()

    def pick(self):
        color = QtWidgets.QColorDialog.getColor(self.color, self.box.window(), self.text)
        if color.isValid():
            self.set_color(color)

    def value(self):
        return self.color.name()

    def load(self):
        u = _param(self.path).GetUnsigned(self.key, 0)
        self.color = _to_qcolor(u) if u else QtGui.QColor(204, 204, 204)
        self._paint()
        self.loaded = self.value()

    def save(self):
        if self.changed():
            write(self.path, "Unsigned Long", self.key, _to_unsigned(self.color))
            self.loaded = self.value()


# rows whose colour only a patched Sketcher reads: row -> native.features() name
ROW_NEEDS = {"Sketch, Over Defined": "overdefined_color"}


def _kept_color(name):
    ""

    import re
    return [("Mod/FreeWorks/Colors", re.sub(r"[^A-Za-z0-9]+", "", name))]


def kept_color(name, default=None):
    ""
    path, key = _kept_color(name)[0]
    u = _param(path).GetUnsigned(key, 0)
    if not u:
        return default
    return ((u >> 24) & 255) / 255.0, ((u >> 16) & 255) / 255.0, ((u >> 8) & 255) / 255.0


def kept_hex(name, default=None):
    ""
    rgb = kept_color(name)
    if rgb is None:
        return default
    return "#%02x%02x%02x" % tuple(int(round(c * 255)) for c in rgb)


TREE_TEXT_ROWS = ("FeatureManager Design Tree Text", "Flyout FeatureManager Design Tree Text")


def _restyle():
    """The window's style sheet again, so the tree text colours show at once (not while a sketch or
    feature is being edited: the look follows when the panel closes, as a theme change does)."""
    try:
        from . import style
        if getattr(style, "_edit_open", lambda: False)():
            return False
        style.signals.theme_changed.emit(style.current_theme())
        return True
    except Exception as _fw_err:
        _fw_log("optionspages.py:restyle", _fw_err)
        return False


def _row_target(name, target):
    ""

    need = ROW_NEEDS.get(name)
    if target is None:
        return _kept_color(name)
    if need is None:
        return target
    try:
        from . import native
        return target if native.has(need) else _kept_color(name)
    except Exception:
        return _kept_color(name)


class ColorList(Setting):
    ""

    def __init__(self):
        super().__init__("", "colors", None, "Color scheme settings")
        self.pending, self.reset = {}, False
        for name, target in COLOR_ROWS:
            if _row_target(name, target) is None and ("Colors", name) not in PLANNED:
                PLANNED.append(("Colors", name))

    def widget(self):
        box = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QtWidgets.QLabel(self.text))
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWColorList")
        self.list.setMinimumHeight(180)
        lay.addWidget(self.list)
        row = QtWidgets.QHBoxLayout()
        self.swatch = QtWidgets.QLabel()
        self.swatch.setFixedSize(60, 20)
        self.swatch.setObjectName("SWColorSwatch")
        self.edit = QtWidgets.QPushButton("Edit...")
        self.edit.setObjectName("SWColorEdit")
        self.edit.clicked.connect(self.pick)
        self.reset_button = QtWidgets.QPushButton("Reset Colors To Defaults")
        self.reset_button.setObjectName("SWColorReset")
        self.reset_button.clicked.connect(self.reset_all)
        row.addWidget(self.swatch)
        row.addWidget(self.edit)
        row.addStretch(1)
        row.addWidget(self.reset_button)
        lay.addLayout(row)
        self.list.currentRowChanged.connect(self._show)
        self.box = box
        return box

    def color(self, target):
        key = tuple(target[0])
        if key in self.pending:
            return self.pending[key]
        if self.reset:
            return None
        u = _param(key[0]).GetUnsigned(key[1], 0)
        return _to_qcolor(u) if u else None

    def load(self):
        self.list.clear()
        for name, target in COLOR_ROWS:
            target = _row_target(name, target)
            item = QtWidgets.QListWidgetItem(name)
            item.setData(Qt.UserRole, target)
            if target is None:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                item.setToolTip(NOT_YET)
            self.list.addItem(item)
        self.pending, self.reset = {}, False
        self.loaded = None
        self.list.setCurrentRow(0)

    def _show(self, row):
        item = self.list.item(row)
        target = item.data(Qt.UserRole) if item is not None else None
        self.edit.setEnabled(bool(target))
        color = self.color(target) if target else None
        self.swatch.setStyleSheet("background:%s; border:1px solid #888;" % (color.name() if color else "transparent"))
        self.swatch.setToolTip("" if color else "The look's own colour")

    def select(self, name):
        found = self.list.findItems(name, Qt.MatchExactly)
        if found:
            self.list.setCurrentItem(found[0])

    def current_target(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def set_color(self, color, target=None):
        target = target or self.current_target()
        if target:
            for path_key in target:
                self.pending[tuple(path_key)] = QtGui.QColor(color)
            self._show(self.list.currentRow())

    def pick(self):
        target = self.current_target()
        if not target:
            return
        start = self.color(target) or QtGui.QColor(Qt.white)
        color = QtWidgets.QColorDialog.getColor(start, self.box.window(), "Color")
        if color.isValid():
            self.set_color(color, target)

    def reset_all(self):
        self.pending, self.reset = {}, True
        self._show(self.list.currentRow())

    def value(self):
        return (self.reset, sorted((k, c.name()) for k, c in self.pending.items()))

    def changed(self):
        return self.reset or bool(self.pending)

    def save(self):
        if self.reset:
            for name, target in COLOR_ROWS:
                for path, key in _row_target(name, target) or ():
                    forget(path, "Unsigned Long", key)
        tree = self.reset or any(tuple(_kept_color(n)[0]) in self.pending for n in TREE_TEXT_ROWS)
        for (path, key), color in self.pending.items():
            write(path, "Unsigned Long", key, _to_unsigned(color))
        self.pending, self.reset = {}, False
        if tree:
            _restyle()


def _background_read():
    if _fw().GetBool("BackgroundIsImage", False) and background_image():
        return "image"
    from . import style
    own = {(p, n): v for p, _k, n, v in style.user_settings()}
    if (PREFERENCES + VIEW, "Gradient") not in own:
        return "scene"
    return "gradient" if own[(PREFERENCES + VIEW, "Gradient")] else "plain"


def background_image():
    return _fw().GetString("BackgroundImage", "")


def _background_write(choice):
    if choice == "image":
        path, _f = QtWidgets.QFileDialog.getOpenFileName(None, "Background image", background_image(),
                                                         "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        _fw().SetString("BackgroundImage", path)
        _fw().SetBool("BackgroundIsImage", True)
        try:
            from . import optionsextras
            optionsextras.apply_background_image()
        except Exception as _fw_err:
            _fw_log("optionspages.py:1141", _fw_err)
        return
    _fw().SetBool("BackgroundIsImage", False)
    try:
        from . import optionsextras
        optionsextras.apply_background_image()
    except Exception as _fw_err:
        _fw_log("optionspages.py:1148", _fw_err)
    keys = ("Simple", "Gradient", "RadialGradient", "UseBackgroundColorMid")
    if choice == "scene":
        for key in keys:
            forget(VIEW, "Boolean", key)
        return
    for key, on in zip(keys, (choice == "plain", choice == "gradient", False, False)):
        write(VIEW, "Boolean", key, on)


# ---------------------------------------------------------------- read/write helpers
def _english_read():
    return _param("General").GetString("Language", "") == "English"


def _english_write(on):
    g = _param("General")
    if on:
        now = g.GetString("Language", "")
        if now and now != "English":
            _fw().SetString("LanguageBeforeEnglish", now)
        g.SetString("Language", "English")
    else:
        before = _fw().GetString("LanguageBeforeEnglish", "")
        if before:
            g.SetString("Language", before)
        else:
            g.RemString("Language")


def _fw_bool(key, default):
    return (lambda: _fw().GetBool(key, default)), (lambda v: _fw().SetBool(key, bool(v)))


def _single_command_read():
    return not _param(SKETCHER).GetBool("ContinuousCreationMode", True)


def _single_command_write(on):
    _param(SKETCHER).SetBool("ContinuousCreationMode", not on)
    _param(SKETCHER).SetBool("ContinuousConstraintMode", not on)


def _pre2009_read():
    return bool(stored("Display", "Use pre-2009 tangent edge definition", False))


def _pre2009_write(on):
    set_stored("Display", "Use pre-2009 tangent edge definition", bool(on))
    try:
        from . import displayextras
        displayextras.TANGENT.apply_all()
    except Exception as _fw_err:
        _fw_log("optionspages.py:1201", _fw_err)


def _tangent_read():
    from . import displayextras
    return displayextras.tangent_mode()


def _tangent_write(mode):
    from . import displayextras
    displayextras.set_tangent_mode(mode)


def _antialias_read():
    v = _param(VIEW).GetInt("AntiAliasing", 0)
    return 0 if v == 0 else (1 if v == 1 else 2)


def _antialias_write(v):
    write(VIEW, "Integer", "AntiAliasing", {0: 0, 1: 1, 2: 3}.get(v, 1))


def _transition_read():
    if not _param(VIEW).GetBool("UseNavigationAnimations", True):
        return 0
    ms = _param(VIEW).GetInt("AnimationDuration", 250)
    return 3 if ms <= 300 else (2 if ms <= 600 else 1)


def _transition_write(stop):
    write(VIEW, "Boolean", "UseNavigationAnimations", stop != 0)
    if stop:
        write(VIEW, "Integer", "AnimationDuration", {1: 1000, 2: 500, 3: 250}[stop])


def _onview_read():

    return _param("Mod/Sketcher/General").GetBool("OnScreenNumericInput",
                                                  _param("Mod/Sketcher/Tools").GetInt("OnViewParameterVisibility", 0) != 0)


def _onview_write(on):
    write("Mod/Sketcher/General", "Boolean", "OnScreenNumericInput", bool(on))
    write("Mod/Sketcher/Tools", "Integer", "OnViewParameterVisibility", 1 if on else 0)


def _override_drag():
    from . import overridedrag
    p = _param(overridedrag.PARAMS.replace("User parameter:BaseApp/Preferences/", ""))
    return (lambda: p.GetBool(overridedrag.KEY, False)), (lambda v: p.SetBool(overridedrag.KEY, bool(v)))


def _repaint(name, method="update"):
    for w in QtWidgets.QApplication.allWidgets():
        if w.objectName() == name and hasattr(w, method):
            getattr(w, method)()


def _triad_write(on):
    _fw().SetBool("ReferenceTriad", bool(on))
    _repaint("SWViewCorner")


def _corner_write(on):
    _fw().SetBool("ConfirmationCorner", bool(on))
    _repaint("SWConfirmationCorner", "refresh")


def _grid_read():
    from . import viewtypes
    return viewtypes.grid_shown()


def _grid_write(on):
    from . import viewtypes
    viewtypes.set_grid(on)


GRID_SIZE = "Mod/Sketcher/General/GridSize"


def _grid_size():
    text = _param(GRID_SIZE).GetString("GridSize", "10 mm")
    try:
        return float(App.Units.Quantity(text).getValueAs("mm"))
    except Exception:
        try:
            return float(text.split()[0])
        except Exception:
            return 10.0


def _minor_read():
    return max(1, _param(SK_GENERAL).GetInt("GridNumberSubdivision", 10))


def _major_read():
    return _grid_size() * _minor_read()


def _sketches_grid(prop, value):
    ""
    from . import viewtypes
    for sk in viewtypes._sketches(None):
        vo = getattr(sk, "ViewObject", None)
        if vo is not None and hasattr(vo, prop):
            try:
                if prop == "GridSize":
                    if abs(float(vo.GridSize.getValueAs("mm")) - float(value)) > 1e-9:
                        vo.GridSize = App.Units.Quantity("%r mm" % float(value))
                elif getattr(vo, prop) != value:
                    setattr(vo, prop, value)
            except Exception as _fw_err:
                _fw_log("optionspages.py:sketches_grid", _fw_err)


def _major_write(mm):
    _param(GRID_SIZE).SetString("GridSize", "%g mm" % (mm / _minor_read()))
    _sketches_grid("GridSize", mm / _minor_read())


def _minor_write(n):
    major = _major_read()
    _param(SK_GENERAL).SetInt("GridNumberSubdivision", int(n))
    _param(GRID_SIZE).SetString("GridSize", "%g mm" % (major / max(1, int(n))))
    _sketches_grid("GridSize", major / max(1, int(n)))


def _grid_auto_write(on):
    write(SK_GENERAL, "Boolean", "GridAuto", bool(on))
    _sketches_grid("GridAuto", bool(on))


def _each_view_object(prop, value):
    doc = App.ActiveDocument
    for o in doc.Objects if doc else []:
        vo = getattr(o, "ViewObject", None)
        if vo is not None and hasattr(vo, prop):
            try:
                setattr(vo, prop, value)
            except Exception as _fw_err:
                _fw_log("optionspages.py:1319", _fw_err)


def _doc_quality(text, prop, fallback):
    """The active document's own Image Quality value: kept in its file (Meta), else what its shapes
    are drawn with, else the default for new documents."""
    doc = App.ActiveDocument
    if doc is not None:
        raw = (dict(getattr(doc, "Meta", {}) or {})).get(DOC_META + _store_key("Image Quality", text))
        if raw is not None:
            try:
                return float(raw)
            except ValueError as _fw_err:
                _fw_log("optionspages.py:1332", _fw_err)
        for o in doc.Objects:
            vo = getattr(o, "ViewObject", None)
            if vo is not None and prop in getattr(vo, "PropertiesList", ()) and getattr(o, "Shape", None) is not None:
                try:
                    return float(getattr(vo, prop))
                except Exception:
                    break
    return fallback()


def _keep_quality(text, value):
    doc = App.ActiveDocument
    if doc is None:
        return
    try:        # docstyle's rebuild pass keeps each shape's own quality: it is the new one now
        from . import docstyle
        for key in [k for k in docstyle._quality if k[0] == doc.Name]:
            del docstyle._quality[key]
    except Exception as _fw_err:
        _fw_log("optionspages.py:1352", _fw_err)
    try:
        meta = dict(doc.Meta)
        meta[DOC_META + _store_key("Image Quality", text)] = str(float(value))
        doc.Meta = meta
    except Exception as _fw_err:
        _fw_log("optionspages.py:1358", _fw_err)


def _deviation_read():
    return _doc_quality("Deviation", "Deviation", lambda: _param("Mod/Part").GetFloat("MeshDeviation", 0.5))


def _deviation_write(v):
    ""


    _each_view_object("Deviation", float(v))
    _keep_quality("Deviation", v)


def _angular_read():
    return _doc_quality("Angular deviation", "AngularDeflection",
                        lambda: _param("Mod/Part").GetFloat("MeshAngularDeflection", 28.5))


def _angular_write(v):
    _each_view_object("AngularDeflection", float(v))
    _keep_quality("Angular deviation", v)


SHADED_ANGULAR = (28.5, 2.0)


def shaded_angular(t):
    """The angular deviation the shaded Low..High slider sets at t (0 = Low, 1 = High)."""
    import math
    lo, hi = math.log(SHADED_ANGULAR[0]), math.log(SHADED_ANGULAR[1])
    return math.exp(lo + (hi - lo) * max(0.0, min(1.0, t)))


def _material_choices():
    from . import fmmenu
    out = [("<not specified>", "")] + [(label, label) for label, _n in fmmenu.material_favorites()]
    current = _material_read()
    if current and current not in [v for _t, v in out]:
        out.insert(1, (current, current))       # the part's own material, also when it is not a favourite
    return out


def _material_read():
    from . import fmmenu
    doc = App.ActiveDocument
    current = fmmenu.current_material(doc) if doc else ""
    for label, names in fmmenu.material_favorites():
        if current and (current == label or current in names):
            return label
    return current or ""


def _material_write(label):
    from . import fmmenu
    doc = App.ActiveDocument
    if not label and doc is not None:
        from . import material
        material.apply(doc, "", 0.0)              # <not specified>: the part has no material
        return
    for lab, names in fmmenu.material_favorites():
        if lab == label and App.ActiveDocument is not None:
            fmmenu.set_material(App.ActiveDocument, names, lab)


def _density_factor():
    """(kg/m^3 -> the document's density unit, its name): g/mm^3 in MMGS, lb/in^3 in IPS."""
    try:
        from . import massprops
        _l, mm, _n, mass, g, _p = massprops.SYSTEMS[massprops.unit_system()]
        return 1e-6 * mm ** 3 / g, "%s/%s^3" % (mass, _l)
    except Exception:
        return 1e-6, "g/mm^3"


def _material_density(label):
    """kg/m^3 of a material row's name ("" = the part's own density with no material)."""
    from . import material, massprops
    doc = App.ActiveDocument
    if not label:
        return material.part_density(doc) or massprops.DEFAULT_DENSITY
    if label == _material_read():
        value, _name = material.current(doc)
        if value:
            return value
    try:
        from . import fmmenu
        for lab, names in fmmenu.material_favorites():
            if lab == label:
                m = fmmenu._material(names)
                if m is not None:
                    v = material.library_density(m)
                    if v:
                        return v
                for n in names:
                    v = material.known_density(n)
                    if v:
                        return v
        return material.known_density(label) or massprops.DEFAULT_DENSITY
    except Exception:
        return massprops.DEFAULT_DENSITY


class DensityRow(Setting):
    ""



    def __init__(self):
        super().__init__("", "Density", None, "Density", "")
        self.tip = ("The part's density. With a material, the material's density in this part.")

    def widget(self):
        row = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        label = QtWidgets.QLabel(self.text)
        self.factor, unit = _density_factor()
        self.box = QtWidgets.QDoubleSpinBox()
        self.box.setObjectName("SWDensity")
        self.box.setDecimals(8 if self.factor < 0.01 else 4)
        self.box.setRange(0.0, 1e9)
        self.box.setSuffix(" " + unit)
        self.box.setToolTip(self.tip)
        label.setBuddy(self.box)
        lay.addWidget(label)
        lay.addWidget(self.box)
        lay.addStretch(1)
        QtCore.QTimer.singleShot(0, self._link)
        return row

    def _link(self):
        """The material list above: picking a material shows its density here at once."""
        try:
            page = self.box.parentWidget()
            while page is not None and page.findChild(QtWidgets.QComboBox, "SWCombo_Material") is None:
                page = page.parentWidget()
            combo = page.findChild(QtWidgets.QComboBox, "SWCombo_Material") if page is not None else None
            if combo is not None:
                self._combo = combo
                combo.currentIndexChanged.connect(self._picked)
        except RuntimeError as _fw_err:
            _fw_log("optionspages.py:density link", _fw_err)

    def _picked(self, *_args):
        try:
            choices = _material_choices()
            i = self._combo.currentIndex()
            label = choices[i][1] if 0 <= i < len(choices) else ""
            self.box.setValue(_material_density(label) * self.factor)
            self.loaded = self.value()          # the material's own density is not a typed one
        except Exception as _fw_err:
            _fw_log("optionspages.py:density pick", _fw_err)

    def value(self):
        return float(self.box.value()) / self.factor

    def load(self):
        self.box.setValue(_material_density(_material_read()) * self.factor)
        self.loaded = self.value()

    def changed(self):
        return abs(self.value() - self.loaded) > 1e-9 * max(1.0, abs(self.loaded))

    def save(self):
        doc = App.ActiveDocument
        if doc is None or not self.changed():
            return
        from . import material
        material.set_density(doc, self.value())
        self.loaded = self.value()


def _shown(key):
    from . import viewtypes
    return App.ActiveDocument is not None and viewtypes.shown(key)


def _set_shown(key, on):
    from . import viewtypes
    if App.ActiveDocument is not None:
        viewtypes.set_shown(key, on)


def _annotations_read():
    ""

    doc = App.ActiveDocument
    if doc is None:
        return True
    from . import viewtypes
    if viewtypes.objects_of("AllAnnotations", doc):
        return viewtypes.shown("AllAnnotations", doc)
    return doc.Meta.get("FreeWorks_DisplayAnnotations", "1") != "0"


def _annotations_write(on):
    doc = App.ActiveDocument
    if doc is None:
        return
    meta = dict(doc.Meta)
    meta["FreeWorks_DisplayAnnotations"] = "1" if on else "0"
    doc.Meta = meta
    _set_shown("AllAnnotations", on)


def _tree_item(name, default):
    choices = [("Automatic", "Automatic"), ("Hide", "Hide"), ("Show", "Show")]
    return Combo("TreeItem." + name, name, choices,
                 lambda: _fw().GetString("TreeItem." + name, default),
                 lambda v: (_fw().SetString("TreeItem." + name, v), _rebuild_trees()))


def _rebuild_trees():
    try:
        from . import swkeys
        swkeys.rebuild_trees()
    except Exception as _fw_err:
        _fw_log("optionspages.py:1460", _fw_err)


def _later(page):
    return lambda text, default=None: Later(text, default, page)


DOC_META = "FreeWorks:"


def doc_value(doc, page, text, default=None):
    ""

    key = DOC_META + _store_key(page, text)
    meta = dict(getattr(doc, "Meta", {}) or {}) if doc is not None else {}
    if key not in meta:
        return stored(page, text, default)
    raw = meta[key]
    if isinstance(default, bool):
        return raw == "1"
    if isinstance(default, int):
        try:
            return int(float(raw))
        except ValueError:
            return default
    if isinstance(default, float):
        try:
            return float(raw)
        except ValueError:
            return default
    return raw


# Document Properties rows that are lengths (kept in mm) or angles (degrees): shown with the unit, lengths in the

LENGTH_ROWS = {"Arrow width", "Arrow length", "Arrow length with extension", "Leader length", "Bent leader length",
               "Offset from model", "Offset between dimensions", "Maximum arc radius", "Position tolerance",
               "Profile tolerance", "Primary datums, tolerance", "Block tolerance, length"}
ANGLE_ROWS = {"Leader snap angle", "Block tolerance, angle", "Angle"}


class DocLater(Later):
    """A Document Properties setting: kept in the active document (its Meta, saved with the file) and
    as the default for new documents."""

    _size = None        # a length row: the size of the shown unit in mm

    def widget(self):
        row = super().widget()
        b = self.box
        if isinstance(b, QtWidgets.QDoubleSpinBox) and isinstance(self.default, float):
            if self.text in LENGTH_ROWS:
                try:
                    from . import unitspage
                    symbol, self._size = unitspage.length_unit()
                except Exception:
                    symbol, self._size = "mm", 1.0
                b.setRange(0.0, 1e6)
                b.setDecimals(4 if self._size > 1.0 else 2)
                b.setSuffix(" " + symbol)
            elif self.text in ANGLE_ROWS:
                b.setRange(-360.0, 360.0)
                b.setDecimals(2)
                b.setSuffix("°")
        return row

    def value(self):
        if self._size:
            return float(self.box.value()) * self._size
        return super().value()

    def load(self):
        super().load()
        if self._size:
            try:
                v = float(self._read() or 0.0)
            except (TypeError, ValueError):
                v = 0.0
            self.box.setValue(v / self._size)
            self.loaded = self.value()

    def _read(self):
        return doc_value(App.ActiveDocument, self.page, self.text, self.default)

    def save(self):
        if not self.changed():
            return
        value = self.value()
        set_stored(self.page, self.text, value)
        doc = App.ActiveDocument
        if doc is not None:
            meta = dict(doc.Meta)
            meta[DOC_META + _store_key(self.page, self.text)] = ("1" if value else "0") if isinstance(value, bool) \
                else str(value)
            doc.Meta = meta
        self.loaded = value
        try:
            from . import optionsextras
            optionsextras.refresh_options()
        except Exception as _fw_err:
            _fw_log("optionspages.py:1516", _fw_err)


def _assembly(doc=None):
    try:
        from . import asmcore
        return asmcore.assembly_of(doc or App.ActiveDocument)
    except Exception:
        return None


def referenced_part_documents(doc=None):
    """The part documents an assembly's components come from (each once, not the assembly's own)."""
    asm = _assembly(doc)
    if asm is None:
        return []
    out = []
    try:
        from . import asmcore
        comps = asmcore.components(asm)
    except Exception:
        comps = []
    for comp in comps:
        linked = getattr(comp, "LinkedObject", None)
        d = getattr(linked, "Document", None)
        if d is not None and d is not asm.Document and d not in out:
            out.append(d)
    return out


def apply_quality_to_parts(doc=None, deviation=None, angular=None):
    """Image Quality > Apply to all referenced part documents: each component's part document takes
    the assembly's Deviation and Angular deviation (its shapes and its kept Image Quality rows)."""
    deviation = _deviation_read() if deviation is None else float(deviation)
    angular = _angular_read() if angular is None else float(angular)
    done = []
    for d in referenced_part_documents(doc):
        for o in d.Objects:
            vo = getattr(o, "ViewObject", None)
            if vo is None:
                continue
            for prop, value in (("Deviation", deviation), ("AngularDeflection", angular)):
                if prop in vo.PropertiesList:
                    try:
                        setattr(vo, prop, value)
                    except Exception as _fw_err:
                        _fw_log("optionspages.py:1562", _fw_err)
        try:
            meta = dict(d.Meta)
            meta[DOC_META + _store_key("Image Quality", "Deviation")] = str(deviation)
            meta[DOC_META + _store_key("Image Quality", "Angular deviation")] = str(angular)
            d.Meta = meta
        except Exception as _fw_err:
            _fw_log("optionspages.py:1569", _fw_err)
        try:
            from . import docstyle
            for key in [k for k in docstyle._quality if k[0] == d.Name]:
                del docstyle._quality[key]
        except Exception as _fw_err:
            _fw_log("optionspages.py:1575", _fw_err)
        done.append(d.Name)
    return done


class ApplyToParts(DocLater):
    """Assembly Image Quality: Apply to all referenced part documents. Kept with the assembly; on OK
    (after Deviation and Angular deviation are saved) the part documents take the same values."""

    def save(self):
        super().save()
        if self.value():
            doc = App.ActiveDocument
            QtCore.QTimer.singleShot(0, lambda: apply_quality_to_parts(doc))


ASSEMBLY_HIDDEN = ("Material Properties", "Sheet Metal MBD", "Sheet Metal", "Weldments")


def _doc_later(page):
    return lambda text, default=None: DocLater(text, default, page)


def _stub(page, items):
    L = _later(page)
    return [(None, [L(t, d) for t, d in items])]


class _HatchNumber(Later):
    """hatchspin-1120 (lookaudit AF2): System Options > Drawings > Area Hatch/Fill Scale and Angle as the same short
    spin boxes Document Properties > Material Properties shows ("1.000", "0.00\u00b0"), not wide text boxes. The value
    is still kept as text ("1", "0.00deg"), so every reader (drawannot, optionsextras) reads it as before."""

    def widget(self):
        row = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        label = QtWidgets.QLabel(SHOWN.get((self.page, self.text), self.text))
        self.box = QtWidgets.QDoubleSpinBox()
        if self.text == "Angle":
            self.box.setRange(-360.0, 360.0)
            self.box.setDecimals(2)
            self.box.setSuffix("\u00b0")
        else:
            self.box.setRange(0.001, 1e6)
            self.box.setDecimals(3)
        self.box.setObjectName("SWKept_" + self.key)
        self.tag(self.box)
        self._grey(label)
        label.setBuddy(self.box)
        lay.addWidget(label)
        lay.addWidget(self.box)
        lay.addStretch(1)
        return row

    def _number(self, v):
        try:
            return float(str(v).replace("deg", "").replace("\u00b0", "").split()[0])
        except (TypeError, ValueError, IndexError):
            return 0.0 if self.text == "Angle" else 1.0

    def value(self):
        v = self.box.value()
        return ("%.2fdeg" % v) if self.text == "Angle" else ("%g" % v)

    def load(self):
        self.box.setValue(self._number(self._read()))
        self.loaded = self.value()


TREE_FILTER = ("FeatureManager", "Enable FeatureManager tree filter")


def _tree_filter_on():
    return stored(TREE_FILTER[0], TREE_FILTER[1], True)


def _set_tree_filter(on):
    ""
    set_stored(TREE_FILTER[0], TREE_FILTER[1], bool(on))
    for w in QtWidgets.QApplication.allWidgets():
        try:
            if callable(getattr(w, "filter_shown", None)) and callable(getattr(w, "_fit", None)):
                w._fit()
        except Exception as _fw_err:
            _fw_log("optionspages.py:1618", _fw_err)


def _doc_stub(page, items):
    L = _doc_later(page)
    return [(None, [L(t, d) for t, d in items])]


def _not_yet(value, key=""):
    ""
    return (lambda: stored("Radio", key, value)), (lambda v: set_stored("Radio", key, v))


def _edge_option(value, key):
    ""


    def write(v):
        set_stored("Radio", key, v)
        try:
            from . import hlv
            hlv.option_changed(key)
        except Exception as _fw_err:
            _fw_log("optionspages.py:edge-option", _fw_err)
    return (lambda: stored("Radio", key, value)), write


def _dim_names_read():
    return App.ParamGet("User parameter:BaseApp/Preferences/Mod/Sketcher").GetBool("ShowDimensionalName", False)


def _dim_names_write(on):
    App.ParamGet("User parameter:BaseApp/Preferences/Mod/Sketcher").SetBool("ShowDimensionalName", bool(on))
    try:
        from . import featuredims
        featuredims.refresh()
    except Exception as _fw_err:
        _fw_log("optionspages.py:1641", _fw_err)


def _restore_associations(dialog):
    from . import optionsextras2
    return optionsextras2.restore_file_associations(dialog)


# ---------------------------------------------------------------- System Options
def _general():
    L = _later("General")
    return [
        ("Recent documents", [
            # the look sets 50 at every start: written as the user's own so a change outlasts a restart
            NumberFn("RecentFiles", "Maximum recent documents displayed", "", 0, 50,
                     lambda: _param("RecentFiles").GetInt("RecentFiles", 50),
                     lambda v: write("RecentFiles", "Integer", "RecentFiles", int(v))),
            L("Include documents opened from other documents", False),
            Combo("OpenLastDocuments", "Open last used document(s) at startup", [("Never", "Never"), ("Always", "Always")],
                  lambda: _fw().GetString("OpenLastDocuments", "Never"),
                  lambda v: _fw().SetString("OpenLastDocuments", v),
                  "Always: the files open when FreeCAD closed open again at the next start"),
        ]),
        (None, [
            Bool(SKETCHER, "ShowDialogOnDistanceConstraint", True, "Input dimension value",
                 "The Modify box opens when a dimension is placed"),
            BoolFn("SingleCommandPerPick", "Single command per pick", _single_command_read, _single_command_write,
                   "Sketch tools and dimensions end after one use"),


            Bool(DOCUMENT, "SaveThumbnail", True, "Show thumbnail graphics in Windows Explorer",
                 "Saves a picture of the model in the file"),
            Button("Restore File Associations", lambda d: _restore_associations(d),
                   "Makes .FCStd files open in this FreeCAD again"),
            BoolFn("UseSystemSeparator", "Use system separator for dimensions",
                   lambda: _param("General").GetInt("UseLocaleFormatting", 0) == 0,
                   lambda v: _param("General").SetInt("UseLocaleFormatting", 0 if v else 2),
                   "The operating system's decimal separator; off: a point"),
            BoolFn("EnglishMenus", "Use English language menus", _english_read, _english_write,
                   tip="FreeCAD's language set to English (after a restart); off goes back to the language before"),
            Fixed("Use English language feature and file names", False),
            BoolFn("ConfirmationCorner", "Enable Confirmation Corner", lambda: _fw().GetBool("ConfirmationCorner", True),
                   _corner_write),
            Fixed("Auto-show PropertyManager", True, "The PropertyManager opens with each command"),
            L("Auto-size PropertyManager when panels are split", True),
            Fixed("Automatically edit macro after recording", False,
                  "The macro opens in FreeCAD's macro editor when recording stops"),
            L("Stop VSTA debugger on macro exit", True),
            L("Enable FeatureXpert", True),
            BoolFn("FreezeBar", "Enable Freeze bar", *_fw_bool("FreezeBar", False)),
            L("Custom property used as component description", "Description"),
            L("Show latest Technical Alerts and News in Welcome dialog", True),
            L("Check for solutions when the program crashes", True),
            L("Enable sounds for events", True),
        ] + ([Button("Configure Sounds...", _configure_sounds, "Windows' Sound control panel")]
             if os.name == "nt" else [])),    # extapps82
        ("Software updates", [
            BoolFn("UpdateCheck", "Check for updates automatically", lambda: _fw().GetBool("UpdateCheck", True),
                   lambda v: _fw().SetBool("UpdateCheck", bool(v)),
                   "Off: FreeCAD never looks for a newer version by itself"),
            TextFn("UpdateRepo", "Update repository (owner/name)", lambda: _fw().GetString("UpdateRepo", ""),
                   lambda v: _fw().SetString("UpdateRepo", v), "The GitHub repository the updates come from"),
            TextFn("UpdateToken", "Access token", lambda: _fw().GetString("UpdateToken", ""),
                   lambda v: _fw().SetString("UpdateToken", v),
                   "A GitHub token with read access, needed for a private repository; kept in this FreeCAD's "
                   "user settings", secret=True),
            Button("Check for Updates Now", lambda d: __import__("swstyle.selfupdate", fromlist=["x"]).check_now(d),
                   "Looks now, whatever the switch says"),
            Button("Go Back to Previous Version", lambda d: __import__("swstyle.selfupdate", fromlist=["x"]).go_back(d),
                   "Puts back the version kept at the last update, the next time FreeCAD starts"),
        ]),
        # optdead-1120: optl24's "Allow cosmetic threads for upgrade" row is taken off again: FreeCAD files
        # have no older cosmetic threads to upgrade, so the row changed nothing (a dead control)
    ]


def _colors():
    L = _later("Colors")
    return [
        (None, [
            L("Current color scheme", "Default"),     # extapps82: Icon color is listed above Background
            ColorList(),
            ColorButton(VIEW, "DefaultShapeColor", "Default appearance", "The colour of new bodies and features"),
            L("Default scene", "00 3 point faded"),
            Radio("BackgroundAppearance", "Background appearance",
                  [("Use document scene background (recommended)", "scene"),
                   ("Plain (Viewport Background color above)", "plain"),
                   ("Gradient (Top/Bottom Gradient colors above)", "gradient"),
                   ("Image file", "image")], _background_read, _background_write),
            Fixed("Use specified color for Shaded With Edges mode", True,
                  "Edges in Shaded With Edges use the 'Edges In Shaded With Edges Mode' colour above"),
            # drawmaint.py colours a drawing's dimensions changed since the last save, on open (Drawings land117)
            L("Use specified color for changed drawing dimensions on open", False),
            L("Use specified colors when editing parts in assemblies", True),
            Button("Go To Document Colors", go_to(1, "Model Display")),
        ]),
    ]


def _sketch():
    from . import sketchoptions
    L = _later("Sketch")
    sections = dict(sketchoptions.SKETCH[1])
    tools = [s for h, ss in sketchoptions.SKETCH[1] if h != "Over defining dimensions" for s in ss
             if s.key not in ("ShowDialogOnDistanceConstraint", "ContinuousCreationMode",
                              "OnScreenNumericInput")]
    return [
        (None, [
            Fixed("Auto-rotate view normal to sketch plane on sketch creation and sketch edit", True),
            BoolFn("UseFullyDefinedSketches", "Use fully defined sketches", *_fw_bool("UseFullyDefinedSketches", False),
                   tip="Extrude, Cut, Revolve and the other sketch features refuse a sketch that is not fully defined"),
            L("Display arc centerpoints in part/assembly sketches", True),
            L("Display entity points in part/assembly sketches", True),
            L("Prompt to close sketch", True),
            BoolFn("SketchOnNewPart", "Create sketch on new part", *_fw_bool("SketchOnNewPart", False),
                   tip="A new part starts with a sketch open on the Front Plane"),
            BoolFn("OverrideDimsOnDrag", "Override dimensions on drag/move", *_override_drag(),
                   tip="Dragging a sketch entity changes the dimensions that hold it (Tools > Sketch "
                       "Settings > Override Dims on Drag/Move)"),
            Fixed("Display plane when shaded", False, "The sketch plane shows as a see-through face while a sketch is edited"),
            L("Line length measured between virtual sharps in 3d", True),
            L("Enable spline tangency and curvature handles", True),
            Bool(SK_GENERAL, "BSplineControlPolygonVisible", False, "Show spline control polygon by default",
                 "Splines show the lines between their control points when a sketch opens"),
            L("Ghost image on drag", True),
            L("Show curvature comb bounding curve", False),
            BoolFn("AutoScaleMode", "Scale sketch on first dimension creation",
                   lambda: _param("Mod/Sketcher/dimensioning").GetInt("AutoScaleMode", 2) != 1,
                   lambda v: _param("Mod/Sketcher/dimensioning").SetInt("AutoScaleMode", 0 if v else 1),
                   "The first dimension of a sketch scales the whole sketch to its value"),
            BoolFn("OnScreenNumericInput", "Enable on screen numeric input on entity creation", _onview_read,
                   _onview_write, "Length and angle boxes beside the pointer while drawing"),
            BoolFn("DimensionOnlyWhenEntered", "Create dimension only when value is entered",
                   lambda: _param("Mod/Sketcher/General").GetBool("DimensionOnlyWhenEntered", True),
                   lambda v: write("Mod/Sketcher/General", "Boolean", "DimensionOnlyWhenEntered", bool(v)),
                   "Off: with on-screen numeric input, every line drawn keeps its length as a dimension",
                   indent=True),
            BoolFn("PreviewSketchDimension", "Preview sketch dimension when selected",
                   *_fw_bool("PreviewSketchDimension", False),
                   tip="Picking a sketch line, circle or arc shows its length or radius"),
        ]),
        ("Over defining dimensions", sections.get("Over defining dimensions", [])),
        (None, [
            L("Turn off Automatic Solve Mode and Undo when sketch contains more than", "2000 sketch entities"),
            L("Hide missing geometry error for suppressed dimensions", False),
        ]),
        ("Sketch tools", tools),
    ]


def _relations_snaps():
    from . import sketchoptions
    return [(None, [Button("Go To Document Grid Settings", go_to(1, "Grid/Snap"))])] + \
        list(sketchoptions.RELATIONS_SNAPS[1])


_fw_asm_display = True
_fw_asm_perf = True        # and Performance's Assembly loading group (asmlight)


def _asm_display_rows():
    """Assembly transparency for in context edit (and its slider) and Display SpeedPak graphics circle."""
    from . import asmoptions as ao
    return [
        Combo(ao.IN_CONTEXT, "Assembly transparency for in context edit", [(c, c) for c in ao.IN_CONTEXT_CHOICES],
              ao.in_context, lambda v: ao._p().SetString(ao.IN_CONTEXT, v)),
        PercentSlider(ao.IN_CONTEXT_LEVEL, "", ao.in_context_level, lambda v: ao._p().SetInt(ao.IN_CONTEXT_LEVEL, int(v)),
                      tip="How see-through the rest of the assembly is with Force assembly transparency", indent=True),
    ], PercentSlider(ao.SPEEDPAK_OPACITY, "Display SpeedPak graphics circle",
                     lambda: ao._p().GetInt(ao.SPEEDPAK_OPACITY, 100),
                     lambda v: ao._p().SetInt(ao.SPEEDPAK_OPACITY, int(v)), low=10, high=100, step=10,
                     left="Off", right="100%", off_stop=True,
                     tip="How solid the SpeedPak graphics circle is drawn (Off: not drawn)")


def _display():
    L = _later("Display")
    try:
        transparency, speedpak = _asm_display_rows()
    except Exception as _fw_err:
        _fw_log("optionspages.py:asm-display", _fw_err)
        transparency, speedpak = [], None
    return [
        (None, [
            Radio("HiddenEdges", "Hidden edges displayed as", [("Solid", "Solid"), ("Dashed", "Dashed")],
                  *_edge_option("Dashed", "HiddenEdges")),
            Radio("TangentEdges", "Part/Assembly tangent edge display",
                  [("As visible", "Visible"), ("As phantom", "Phantom"), ("Removed", "Removed")],
                  _tangent_read, _tangent_write),
            Radio("ShadedEdges", "Edge display in shaded with edges mode", [("HLR", "HLR"), ("Wireframe", "Wireframe")],
                  *_edge_option("HLR", "ShadedEdges")),
            BoolFn("ThinParts", "Optimize for thin parts", lambda: stored("Display", "Optimize for thin parts", True),
                   lambda v: set_stored("Display", "Optimize for thin parts", bool(v)), indent=True,
                   tip="The far side's edges of a thin plate stop showing through its near face"),
        ] + transparency + [
            Radio("AntiAliasing", "Anti-aliasing",
                  [("None", 0), ("Anti-alias edges/sketches only", 1), ("Full scene anti-aliasing", 2)],
                  _antialias_read, _antialias_write, "3D views opened after OK use it"),
            Fixed("Use shaded face highlighting", True),
            Fixed("Highlight all edges of features selected in graphics view", False,
                  "A pick highlights the face or edge picked"),
            LookBool(VIEW, "EnablePreselection", True, "Dynamic highlight from graphics view"),
            BoolFn("TempAxisHover", "Display temporary axes upon hover over cylindrical faces",
                   *_fw_bool("TempAxisHover", False)),
            L("Show open edges of surfaces in different color", True),
            BoolFn("Pre2009Tangent", "Use pre-2009 tangent edge definition", _pre2009_read, _pre2009_write,
                   tip="Looser tangent test (about 3 degrees instead of 1): nearly smooth edges count as tangent edges"),
            Fixed("Display shaded planes", True, "Planes are drawn as see-through faces"),
            Fixed("Display dimensions flat to screen", False, "Sketch dimensions lie in the sketch plane"),
            L("Display DimXpert dimensions on top of model", False),
            Fixed("Display notes flat to screen", True),
            BoolFn("ReferenceTriad", "Display reference triad", lambda: _fw().GetBool("ReferenceTriad", True),
                   _triad_write),
            BoolFn("DrawingScrollbars", "Display scrollbars in graphics view for drawings",
                   lambda: stored("Display", "Display scrollbars in graphics view for drawings", True),
                   lambda v: set_stored("Display", "Display scrollbars in graphics view for drawings", bool(v)),
                   tip="A drawing sheet's window shows scroll bars"),
        ] + ([speedpak] if speedpak is not None else []) + [
            L("Display pattern information tooltips", True),
        ]),
        ("Breadcrumbs", [
            BoolFn("Breadcrumbs", "Show breadcrumbs on selection", *_fw_bool("Breadcrumbs", True)),
            L("Show breadcrumbs at mouse pointer", False),
        ]),
        (None, [
            L("Display unique equation identifier", True),
            L("Display facet fins in Mesh BREP bodies", True),
            L("Projection type for four view viewport", "First Angle"),
        ]),
    ]


def _bulk_read():
    from . import boxselect
    return boxselect.bulk()


def _bulk_write(kind):
    from . import boxselect
    boxselect.set_bulk(kind)


def _selection():
    L = _later("Selection")
    return [
        (None, [
            Radio("BulkSelection", "Default bulk selection method", [("Lasso", "Lasso"), ("Box", "Box")],
                  lambda: _bulk_read(), lambda v: _bulk_write(v),
                  "What the Select Box / Lasso button and a drag in empty space select with"),     # extapps87
        ]),
        ("Selection of hidden edges", [
            Fixed("Allow selection in wireframe and HLV modes", True, "Off: nothing can be picked in Wireframe and Hidden Lines Visible"),
            Fixed("Allow selection in HLR and shaded modes", False, "On: a click on a face near an edge hidden behind it picks that edge"),
        ]),
        (None, [
            L("Enable selection through transparency", True),
            BoolFn("SmallFacePrecision", "Enhance small face selection precision",
                   lambda: _param(VIEW).GetFloat("PickRadius", 5.0) <= 3.0,
                   lambda v: _param(VIEW).SetFloat("PickRadius", 3.0 if v else 5.0),
                   "A pick radius of 3 pixels instead of 5, so small faces are easier to hit"),
        ]),
    ]


def _assemblies():
    from . import asmoptions
    return asmoptions.page()


def _assembly_loading():
    ""

    from . import asmlight as al
    p = al._p
    auto = ModeRadio("AsmLoadingMode", "", [("Automatically optimize resolved mode, hide lightweight mode", True),
                                        ("Manually manage resolved and lightweight modes", False)],
                 lambda: p().GetBool("PerfAutoOptimize", False), _set_auto_optimize, shows=False)
    rows = [
        auto,
        BoolFn(al.AUTO_LIGHT, "Load component lightweight", al.auto_lightweight,
               lambda v: p().SetBool(al.AUTO_LIGHT, bool(v)), "An opened assembly's components load lightweight"),
        BoolFn(al.RESOLVE_SUBS, "Always resolve subassemblies", al.always_resolve_subs,
               lambda v: p().SetBool(al.RESOLVE_SUBS, bool(v)), "Sub-assemblies stay resolved when their parts load lightweight"),
        Combo(al.CHECK_OOD, "Check out-of-date lightweight components:", [(c, c) for c in al.CHECK_CHOICES],
              al.check_out_of_date, lambda v: p().SetString(al.CHECK_OOD, v),
              "Indicate: a red feather on the component; Always Resolve: resolved on open"),
        Combo(al.RESOLVE_MODE, "Resolve lightweight components:", [(c, c) for c in al.RESOLVE_CHOICES],
              al.resolve_mode, lambda v: p().SetString(al.RESOLVE_MODE, v),
              "An operation that needs the whole component asks first, or just resolves it"),
        BoolFn(al.RESOLVE_ON_EXPAND, "Resolve lightweight components when expanded in the FeatureManager design tree",
               al.resolve_on_expand, lambda v: p().SetBool(al.RESOLVE_ON_EXPAND, bool(v)),
               "Off: expanding a lightweight component's row lists it without resolving it (large assemblies stay quick)"),
        BoolFn("SmartSavePrompts", "Mark assembly as modified when cosmetic changes are made to referenced documents",
               al.mark_cosmetic, al.set_mark_cosmetic,
               "Off: hiding, showing or recolouring components doesn't ask to save the assembly"),
        Combo(al.REBUILD_ON_LOAD, "Rebuild assembly on load:", [(c, c) for c in al.REBUILD_CHOICES],
              al.rebuild_on_load, lambda v: p().SetString(al.REBUILD_ON_LOAD, v),
              "An assembly that needs a rebuild when it opens"),
    ]
    for row in rows[1:6]:
        row.needs = auto.key
    return rows


def _set_auto_optimize(on):
    from . import asmlight as al
    p = al._p()
    p.SetBool("PerfAutoOptimize", bool(on))
    if on:
        p.SetBool(al.AUTO_LIGHT, False)
        p.SetBool(al.RESOLVE_SUBS, True)
        p.SetString(al.CHECK_OOD, al.CHECK_CHOICES[0])
        p.SetString(al.RESOLVE_MODE, "Always")
        p.SetBool(al.RESOLVE_ON_EXPAND, True)


def _performance():
    L = _later("Performance")
    try:
        loading = [("Assembly loading", _assembly_loading())]
    except Exception as _fw_err:
        _fw_log("optionspages.py:asm-loading", _fw_err)
        loading = []
    return [
        (None, [
            Bool("Mod/Part/Boolean", "CheckModel", True, "Verification on rebuild (enable advanced body checking)",
                 "Checks the result of each Boolean operation"),
        ]),
        (None, [
            L("Ignore self-intersection check for some sheet metal features", False),
        ]),
        ("Transparency", [
            BoolFn("HQTransparency", "High quality for normal view mode",
                   lambda: _param(VIEW).GetString("TransparentObjectRenderType", "") == "Backface",
                   lambda v: write(VIEW, "String", "TransparentObjectRenderType", "Backface" if v else "Auto")),
            BoolFn("HQDynamic", "High quality for dynamic view mode",
                   lambda: stored("Performance", "High quality for dynamic view mode", True),
                   lambda v: set_stored("Performance", "High quality for dynamic view mode", bool(v)),
                   "Off: while the view turns, pans or zooms, transparent parts draw the quick way; "
                   "the high quality comes back when the view stops (optionsextras6)"),
        ]),
        (None, [
            L("Curvature generation", "Only on demand"),
            LaterSlider("Level of detail", "More (slower)", "Performance"),
        ]),
    ] + loading + [
        ("Mates", [
            LaterSlider("Magnetic mate proximity", "More", "Performance"),
        ]),
        ("Save", [
            L("Purge cached configuration data", False),
            L("Update mass properties while saving document", False),
        ]),
        (None, [
            Bool("Mod/PartDesign/Preview", "ShowTransparentPreview", True, "Use shaded preview"),
            Bool("OpenGL", "UseSoftwareOpenGL", False, "Use software OpenGL", "Takes effect after a restart"),
            Button("Go To Image Quality", go_to(1, "Image Quality")),
            L("Enhanced graphics performance", True),
            # rough match: the graphics card keeps the drawn edges (FreeCAD's render cache: Auto) or not
            BoolFn("HWSilhouette", "Hardware accelerated silhouette edges",
                   lambda: _param(VIEW).GetInt("RenderCache", 0) == 0,
                   lambda v: write(VIEW, "Integer", "RenderCache", 0 if v else 1)),
        ]),
    ]


def _feature_manager():
    from . import fmmenu
    L = _later("FeatureManager")
    return [
        (None, [
            Bool(TREE, "SyncSelection", True, "Scroll selected item into view"),
            L("Name feature on creation", False),
            Fixed("Arrow key navigation", False, "Up and Down move through the tree while it has the focus"),
            LookBool(TREE, "PreSelection", True, "Dynamic highlight",
                     "Hovering a row highlights the item in the graphics area"),
            L("Use transparent flyout FeatureManager tree in parts/assemblies", True),
            BoolFn("TreeFilterOn", "Enable FeatureManager tree filter", _tree_filter_on, _set_tree_filter,
                   "Shows the filter box at the top of the FeatureManager design tree"),
            L("Allow component files to be renamed from FeatureManager tree", False),
            L("Enable preview of hidden components", True),
            Fixed("Edit name with slow double click", True, "FreeCAD renames on a slow double click and F2"),
            L("Show translated feature names in FeatureManager tree", False),
        ]),
        ("Comments", [
            L("Automatically add timestamp to comments", True),
            L("Show Comments in PropertyManager", True),
        ]),
        ("Hide/show tree items", [_tree_item(n, d) for n, d in fmmenu.TREE_ITEMS]),
    ]


def _spin_number(key, text, unit, low, high, decimals, default):
    return NumberFn(key, text, unit, low, high, lambda: _fw().GetFloat(key, default),
                    lambda v: _fw().SetFloat(key, float(v)), decimals=decimals,
                    tip="The step of the arrows, the wheel and the Up/Down keys in every %s box" %
                    ("angle" if unit == "°" else "length"))


def _time_step_read():
    text = str(stored("Spin Box Increments", "Time increments", "0.10s")).strip().lower().rstrip("s").strip()
    try:
        return float(text)
    except ValueError:
        return 0.1


def _time_step_write(v):
    set_stored("Spin Box Increments", "Time increments", "%.2fs" % float(v))     # the text optionsextras5 reads


def _spin_increments():
    return [
        ("Length increments", [
            _spin_number("SpinLengthEnglish", "English units", "in", 0.01, 100.0, 2, 0.1),      # extapps86: 0.10in
            _spin_number("SpinLengthMetric", "Metric units", "mm", 0.01, 1000.0, 2, 10.0),
        ]),
        (None, [
            _spin_number("SpinAngle", "Angle increments", "°", 0.01, 90.0, 2, 1.0),
            NumberFn("SpinTime", "Time increments", "s", 0.01, 60.0, _time_step_read, _time_step_write, decimals=2,
                     tip="The step of the arrows in every time box (motion study, timeline)"),
        ]),
    ]


def _view():
    L = _later("View")
    return [
        (None, [
            BoolFn("ReverseWheelZoom", "Reverse mouse wheel zoom direction", *_fw_bool("ReverseWheelZoom", False)),
            BoolFn("ZoomFitStandardViews", "Zoom to fit when changing to standard views",
                   *_fw_bool("ZoomFitStandardViews", True), tip="Front, Top, Isometric... also zoom to fit the model"),
        ]),
        ("View rotation", [
            NumberFn("ArrowKeyStep", "Arrow keys", "°", 1, 90, lambda: _fw().GetFloat("ArrowKeyStep", 15.0),
                     lambda v: _fw().SetFloat("ArrowKeyStep", float(v)), decimals=2),
            LaterSlider("Mouse speed", "Fast", "View"),
        ]),
        ("Transitions", [
            Slider("ViewTransition", "View transition", _transition_read, _transition_write),
            LaterSlider("Hide/show component", "Fast", "View"),
            LaterSlider("Isolate", "Fast", "View"),
            LaterSlider("View selector", "Fast", "View"),
        ]),
    ]


def _backup():
    L = _later("Backup/Recover")
    return [
        ("Auto-recover", [
            Bool(DOCUMENT, "AutoSaveEnabled", True, "Save auto-recover information every:"),      # extapps82
            Number(DOCUMENT, "AutoSaveTimeout", 15, "", "minutes", 1, 120, needs="AutoSaveEnabled"),
            FolderLater("Auto-recover folder", "Backup/Recover"),
        ]),
        ("Backup", [
            Bool(DOCUMENT, "CreateBackupFiles", True, "Number of backup copies per document:"),     # extapps82
            Number(DOCUMENT, "CountBackupFiles", 1, "", "", 1, 20, needs="CreateBackupFiles"),
            Radio("BackupWhere", "", [("Backup folder:", "folder"),
                                      ("Save backup files in the same location as the original", "here")],
                  _backup_here_read, _backup_here_write),
            BackupFolder("Backup folder", "Backup/Recover"),
            L("Remove backups older than 7 days", False),
        ]),
    ]


def _messages():
    L = _later("Messages/Errors/Warnings")
    return [
        ("Notifications", [
            BoolFn("SaveReminder", "Remind me when a document has not been saved for", *_fw_bool("SaveReminder", True),
                   tip="A note with Save Now, Save All and Remind Me Later at the lower right"),
            NumberFn("SaveReminderMinutes", "", "minutes", 1, 240, lambda: _fw().GetInt("SaveReminderMinutes", 20),
                     lambda v: _fw().SetInt("SaveReminderMinutes", int(v)), needs="SaveReminder"),
            Bool("NotificationArea", "AutoRemoveUserNotifications", True, "Automatically dismiss notifications"),
            Number("NotificationArea", "NotificationTime", 20, "after", "seconds", 1, 120,
                   needs="AutoRemoveUserNotifications"),
        ]),
        ("Rebuild errors", [
            L("When rebuild error occurs", "Prompt"),
            BoolFn("ShowErrorsEveryRebuild", "Show Whats Wrong for every rebuild",
                   *_fw_bool("ShowErrorsEveryRebuild", True)),
            L("Warn me when saving documents with rebuild errors", True),
        ]),
        ("FeatureManager tree", [L("Display FeatureManager tree warnings", "Always"),
                                 L("Treat missing mate references as errors", False)]),
        ("Assemblies", [L("Automatically dismiss reference and update messages after 10 seconds", True)]),
        ("Circular references", [L("Display circular references in equations", "In equation dialog only"),
                                 L("Display potential circular references", "In equation dialog only")]),
    ]




# "Don't show again", ticked here to show it again. (text, parameter group, key, value while dismissed,
# value that shows it, what was answered)
DISMISSABLE = (
    ("Confirm Delete (features)", "Mod/FreeWorks/ConfirmDelete", "FeatureAsk", False, True, "Delete"),
    ("Confirm Delete (sketch entities with relations or dimensions)", "Mod/FreeWorks/ConfirmDelete",
     "SketcherAsk", False, True, "Delete"),
    ("Make this dimension driven? (over defining a sketch)", "Mod/Sketcher", "PromptDrivenState", False, True,
     "Kept answer"),
    ("Automatic relations would over define the sketch", "Mod/Sketcher/General", "WarnAutoRelationsOverDefine",
     False, True, "Do not add the relation"),
    ("Rebuild the document before saving?", "Mod/FreeWorks", "RebuildOnSave", None, 0, "Kept answer"),
)


def _dismissed_now(row):
    _text, path, key, off, on, _ans = row
    g = _param(path)
    if isinstance(on, bool):
        return g.GetBool(key, on) == off
    return g.GetInt(key, on) != on


def _dismissed_answer(row):
    _text, path, key, _off, on, answer = row
    if key == "RebuildOnSave":
        return {1: "Rebuild and save", 2: "Save without rebuilding"}.get(_param(path).GetInt(key, 0), answer)
    if key == "PromptDrivenState":
        return "Make it driven" if _param(path).GetBool("DrivenWhenOverDefining", True) else "Leave it driving"
    return answer


def show_again(row):
    _text, path, key, _off, on, _ans = row
    if isinstance(on, bool):
        _param(path).SetBool(key, on)
    else:
        _param(path).SetInt(key, on)


class DismissedList(Setting):
    """The dismissed messages, each with a Show again box; OK shows the ticked ones again."""

    def __init__(self):
        super().__init__("", "DismissedMessages", None, "Dismissed messages")

    def widget(self):
        box = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QtWidgets.QLabel("Select messages to show again:"))
        self.box = QtWidgets.QTreeWidget()
        self.box.setObjectName("SWDismissedMessages")
        self.box.setRootIsDecorated(False)
        self.box.setColumnCount(2)
        self.box.setHeaderLabels(["Message", "Always use this answer"])
        self.box.header().setStretchLastSection(True)
        self.box.setColumnWidth(0, 330)
        lay.addWidget(self.box, 1)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        self.all = QtWidgets.QPushButton("Select All")
        self.all.setObjectName("SWDismissedSelectAll")
        self.all.clicked.connect(lambda: [self.box.topLevelItem(i).setCheckState(0, Qt.Checked)
                                          for i in range(self.box.topLevelItemCount())])
        row.addWidget(self.all)
        lay.addLayout(row)
        return box

    def load(self):
        self.box.clear()
        self.rows = [r for r in DISMISSABLE if _dismissed_now(r)]
        for r in self.rows:
            it = QtWidgets.QTreeWidgetItem([r[0], _dismissed_answer(r)])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Unchecked)
            self.box.addTopLevelItem(it)
        self.all.setVisible(bool(self.rows))      # no dead controls: shown only with messages to pick
        self.loaded = self.value()

    def value(self):
        return tuple(self.rows[i][2] for i in range(self.box.topLevelItemCount())
                     if self.box.topLevelItem(i).checkState(0) == Qt.Checked)

    def save(self):
        if not self.changed():
            return
        for r in self.rows:
            if r[2] in self.value():
                show_again(r)
        self.load()


def _dismissed():

    return [(None, [BoolFn("ShowDismissedMessagesIcon", "Show dismissed messages icon in status bar",
                           *_fw_bool("ShowDismissedMessagesIcon", True),
                           tip="An icon at the right of the status bar while messages are dismissed; "
                               "click it to come back here")]),
            (None, [DismissedList()])]


class FormatPicker(Setting):
    ""




    def __init__(self, key, formats, when=None):
        super().__init__("", key, None, "File Format:", "Pick a file type to see its settings")
        self.formats, self.when = formats, dict(when or {})

    def widget(self):
        self.row = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(self.row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QtWidgets.QLabel(self.text))
        self.box = QtWidgets.QComboBox()
        self.box.setObjectName("SWFileFormat_" + self.key)
        self.box.setToolTip(self.tip)
        self.box.addItems([name for name, _h in self.formats])
        lay.addWidget(self.box, 1)
        lay.addStretch(1)
        self.box.currentIndexChanged.connect(lambda _i: self.show_boxes())
        QtCore.QTimer.singleShot(0, self.show_boxes)
        return self.row

    def _page(self):
        try:
            return self.row.parentWidget()
        except RuntimeError:
            return None

    def show_boxes(self):
        page = self._page()
        if page is None:
            return
        want = dict(self.formats).get(self.box.currentText(), ())
        boxes = page.findChildren(QtWidgets.QGroupBox, options=Qt.FindDirectChildrenOnly)
        for gb in boxes:
            shown = gb.title() in want
            cond = self.when.get(gb.title())
            if shown and cond is not None:
                shown = radio_picked(page, cond[0], cond[1], self.show_boxes)
            gb.setVisible(shown)

    def value(self):
        return self.box.currentText()

    def load(self):
        name = stored("FileFormat", self.key, self.formats[0][0])
        i = self.box.findText(str(name))
        self.box.setCurrentIndex(max(0, i))
        self.loaded = self.value()
        self.show_boxes()

    def save(self):
        if self.changed():
            set_stored("FileFormat", self.key, self.value())
            self.loaded = self.value()


def radio_picked(parent, key, value, follow=None):
    """True when the Radio row `key` under parent has the button `value` picked; follow() is called when it changes."""
    group = parent.findChild(QtWidgets.QWidget, "SWRadio_" + key)
    if group is None:
        return True
    buttons = group.findChildren(QtWidgets.QRadioButton)
    if follow is not None and not group.property("swFollowed"):
        group.setProperty("swFollowed", True)
        for b in buttons:
            b.toggled.connect(lambda _on: follow())
    return any(b.isChecked() and b.text() == value for b in buttons)


IMPORT_FORMATS = (("General", ("General",)), ("STEP/IGES/ACIS", ("STEP/IGES/ACIS",)),
                  ("Mesh", ("Mesh body options",)))


def _import():
    L = _later("Import")

    return [
        (None, [FormatPicker("ImportFileFormat", IMPORT_FORMATS)]),
        ("General", [
            L("Enable 3D Interconnect", True),
            FixedValue("Unit", "File specified unit", "STEP and IGES files are read in the units they were written in"),
        ]),
        ("STEP/IGES/ACIS", [
            L("Solid and Surface", "Try forming solid(s)"),
            L("Perform full entity check and repair errors", True),
            L("Automatically run Import Diagnostics - healing", True),
            L("B-Rep mapping", False),
        ]),
        ("Mesh body options", [
            L("Import as", "Graphics Body"),

            L("Unit (STL, OBJ, OFF, PLY)", "Millimeters"),
        ]),
    ]


def _iges_output_read():
    if _fw().GetBool("IGESWireframe", False):
        return 2
    return _param("Mod/Part/IGES").GetInt("BrepMode", 0)


def _iges_output_write(v):
    v = int(v)
    _fw().SetBool("IGESWireframe", v == 2)
    if v != 2:
        _param("Mod/Part/IGES").SetInt("BrepMode", v)


SHARED_CURVES = "3D curves and faces (IGES and STEP)"
EXPORT_FORMATS = (("IGES 5.3", ("IGES solid/surface features", SHARED_CURVES, "IGES assembly structure")),
                  ("STEP", ("STEP", SHARED_CURVES)), ("VRML", ("VRML",)), ("STL/3MF/AMF", ("STL/3MF/AMF", "3MF")),
                  ("PDF", ("PDF",)), ("TIF/JPG/PNG", ("TIF/JPG/PNG", "Print capture")), ("DXF/DWG", ("DXF/DWG",)))
EXPORT_WHEN = {"Print capture": ("ImageOutput", "Print capture")}


def export_sections(fmt):
    """The Export page's boxes for one File Format (Save As > Options... shows the same rows)."""
    want = dict(EXPORT_FORMATS).get(fmt, ())
    return [(h, rows) for h, rows in _export() if h in want]


def _export():
    L = _later("Export")

    return [
        (None, [FormatPicker("ExportFileFormat", EXPORT_FORMATS, EXPORT_WHEN)]),
        ("IGES solid/surface features", [
            Combo("IGESBrepMode", "Output as",
                  [("Manifold Solid (type 186)", 1), ("Trimmed Surface (type 144)", 0), ("Wireframe (type 110)", 2)],
                  _iges_output_read, _iges_output_write,
                  "How solids are written to IGES files (Wireframe: only the edges)"),
        ]),
        ("STEP", _step_scheme_rows() + [   # exportopts-1119: off writes the shapes without their colours
            L("Export face/edge properties", True),
        ]),
        (SHARED_CURVES, [
            L("Export 3D Curve features", True),
            L("Export sketch entities", False),
            L("Use high trim curve accuracy", True),
            L("Split periodic faces", True),
        ]),
        ("IGES assembly structure", [
            L("Save all components of an assembly in one file", True),
            L("Flatten assembly hierarchy", True),
        ]),

        # Options use the same settings, drawexport.py)
        ("DXF/DWG", _dxf_rows()),
    ] + _mesh_export() + _other_export()


def _step_scheme_rows():
    ""
    try:
        S = _sa()
        names = dict((w, t) for t, w in S.STEP_SCHEMES)
        have = S.step_schemes()
    except Exception as _fw_err:
        _fw_log("optionspages.py:_step_scheme_rows", _fw_err)
        return []
    if len(have) < 2:
        return []           # one STEP type only: nothing to pick
    return [Radio("ExportStepScheme", "Output as", [(names[w], w) for w in have], S.step_scheme, S.set_step_scheme,
                  "The STEP application protocol written")]


def _other_export():
    """export87: VRML, PDF (part and assembly) and TIF/JPG/PNG, read by saveas' writers."""
    try:
        S = _sa()
    except Exception:
        return []
    papers = [(n, n) for n, _w, _h in S.PAPERS]
    return [
        ("VRML", [
            Combo(S.VRML_UNIT, "Output units", [(n, n) for n, _s in S.VRML_UNITS],
                  lambda: _sa_get("s", S.VRML_UNIT, "Millimeters"), _sa_set("s", S.VRML_UNIT),
                  "The unit the VRML file's numbers are in"),
            BoolFn(S.VRML_SINGLE, "Save all components of an assembly in one file",
                   lambda: _sa_get("b", S.VRML_SINGLE, True), _sa_set("b", S.VRML_SINGLE),
                   "Off: one VRML file per component, named after the file and the component"),
        ]),
        ("PDF", [
            BoolFn(S.PDF_COLOR, "Export PDF in color", lambda: _sa_get("b", S.PDF_COLOR, True),
                   _sa_set("b", S.PDF_COLOR), "Off: the model is written in shades of gray"),
            BoolFn(S.PDF_HEADER, "Print header (document name and date)", lambda: _sa_get("b", S.PDF_HEADER, True),
                   _sa_set("b", S.PDF_HEADER)),
            Combo(S.PDF_PAPER, "Paper size", papers, lambda: _sa_get("s", S.PDF_PAPER, "A4"),
                  _sa_set("s", S.PDF_PAPER), "The sheet the part or assembly is put on (landscape)"),
        ]),
        ("TIF/JPG/PNG", [
            Combo(S.IMG_TYPE, "Image type", [(n, n) for n in S.IMAGE_TYPES],
                  lambda: _sa_get("s", S.IMG_TYPE, "RGB"), _sa_set("s", S.IMG_TYPE),
                  "Colour, shades of gray, or black and white only"),
            Radio(S.IMG_OUTPUT, "Output", [(n, n) for n in S.IMAGE_OUTPUTS],
                  lambda: _sa_get("s", S.IMG_OUTPUT, "Screen capture"), _sa_set("s", S.IMG_OUTPUT),
                  "Screen capture: the graphics area's size. Print capture: the paper size at the DPI below"),
        ]),
        ("Print capture", [
            NumberFn(S.IMG_DPI, "DPI", "dpi", 50, 1200, lambda: _sa_get("i", S.IMG_DPI, 300),
                     _sa_set("i", S.IMG_DPI), 0, "Dots per inch of the picture"),
            Combo(S.IMG_PAPER, "Paper size", papers, lambda: _sa_get("s", S.IMG_PAPER, "A4"),
                  _sa_set("s", S.IMG_PAPER), "The picture is this sheet (landscape) at the DPI"),
        ]),
    ]


def _sa():
    from . import saveas
    return saveas


def _sa_get(kind, key, default):
    p = _dxf_params()
    return {"b": p.GetBool, "s": p.GetString, "f": p.GetFloat, "i": p.GetInt}[kind](key, default)


def _sa_set(kind, key):
    def put(v):
        p = _dxf_params()
        {"b": p.SetBool, "s": p.SetString, "f": p.SetFloat, "i": p.SetInt}[kind](
            key, {"b": bool, "s": str, "f": float, "i": lambda x: int(round(float(x)))}[kind](v))
    return put


def _print3d_printers():
    """File > Print3D's printer profiles (print3d.py, slicer86)."""
    try:
        from . import print3d
        return print3d.options_sections()
    except Exception as _fw_err:
        _fw_log("optionspages.py print3d", _fw_err)
        return []


def _mesh_export():
    ""

    try:
        S = _sa()
    except Exception:
        return []
    units = [(n, n) for n, _s in S.STL_UNITS]
    return [
        ("STL/3MF/AMF", [
            Radio(S.STL_BINARY, "Output as", [("Binary", True), ("ASCII", False)],
                  lambda: _sa_get("b", S.STL_BINARY, True), _sa_set("b", S.STL_BINARY),
                  "STL files are written as binary or as text"),
            Combo(S.STL_UNIT, "Unit", units, lambda: _sa_get("s", S.STL_UNIT, "Millimeters"),
                  _sa_set("s", S.STL_UNIT), "The units the STL file's numbers are in"),
            Radio(S.STL_RESOLUTION, "Resolution", [("Coarse", "Coarse"), ("Fine", "Fine"), ("Custom", "Custom")],
                  lambda: _sa_get("s", S.STL_RESOLUTION, "Fine"), _sa_set("s", S.STL_RESOLUTION),
                  "How finely the faces are cut into triangles (Custom: the deviation and angle below)"),
            NumberFn(S.STL_DEVIATION, "Deviation", "mm", 0.0001, 100.0,
                     lambda: _sa_get("f", S.STL_DEVIATION, 0.05), _sa_set("f", S.STL_DEVIATION), 4,
                     "Custom resolution: the most a triangle may be off the face"),
            NumberFn(S.STL_ANGLE, "Angle", "deg", 0.5, 90.0,
                     lambda: _sa_get("f", S.STL_ANGLE, 10.0), _sa_set("f", S.STL_ANGLE), 1,
                     "Custom resolution: the most the normals of neighbouring triangles may turn"),
            BoolFn(S.STL_INFO, "Show STL info before file saving", lambda: _sa_get("b", S.STL_INFO, False),
                   _sa_set("b", S.STL_INFO)),
            BoolFn(S.STL_PREVIEW, "Preview before saving file", lambda: _sa_get("b", S.STL_PREVIEW, False),
                   _sa_set("b", S.STL_PREVIEW), indent=True),
            BoolFn(S.STL_KEEP_SPACE, "Do not translate STL output data to positive space",
                   lambda: _sa_get("b", S.STL_KEEP_SPACE, False), _sa_set("b", S.STL_KEEP_SPACE)),
            BoolFn(S.STL_SINGLE, "Save all components of an assembly in a single file",
                   lambda: _sa_get("b", S.STL_SINGLE, False), _sa_set("b", S.STL_SINGLE)),
        ]),
        ("3MF", [
            Combo(S.TMF_UNIT, "Unit", [(n, n) for n, *_r in S.TMF_UNITS],
                  lambda: _sa_get("s", S.TMF_UNIT, "Millimeters"), _sa_set("s", S.TMF_UNIT),
                  "The unit written in the 3MF file"),
            BoolFn(S.TMF_MATERIALS, "Include materials", lambda: _sa_get("b", S.TMF_MATERIALS, True),
                   _sa_set("b", S.TMF_MATERIALS)),
            BoolFn(S.TMF_APPEARANCES, "Include appearances", lambda: _sa_get("b", S.TMF_APPEARANCES, True),
                   _sa_set("b", S.TMF_APPEARANCES)),
        ]),
    ]


def _dxf():
    from . import smdxf
    return smdxf


def _dx():
    from . import drawexport
    return drawexport


def _dxf_rows():
    ""
    try:
        from . import drawdxf
        versions = [v for v, _a in drawdxf.VERSIONS]
        styles = list(drawdxf.LINE_STYLES)
        merge_default = drawdxf.MERGE_DISTANCE
    except Exception as _fw_err:
        _fw_log("optionspages.py:_dxf_rows", _fw_err)
        return []
    o = lambda key: _dx().options()[key]
    return [
        Combo("DxfVersion", "Version", [(v, v) for v in versions], lambda: o("version"),
              lambda v: _dx().set_dxf_options(version=v), "The AutoCAD version of the DXF/DWG files written"),
        Radio("DxfFont", "Fonts", [("TrueType", "TrueType"), ("AutoCAD STANDARD", "AutoCAD STANDARD")],
              lambda: o("font"), lambda v: _dx().set_dxf_options(font=v), "The font of the drawings' text"),
        Radio("DxfLineStyles", "Line styles", [(x, x) for x in styles], lambda: o("line_styles"),
              lambda v: _dx().set_dxf_options(line_styles=v), "The line types of hidden and centre lines"),
        BoolFn("DxfScale11", "Scale output 1:1", lambda: o("scale11"),
               lambda v: _dx().set_dxf_options(scale11=v), "Drawings are written at full size, not at the sheet's scale"),
        BoolFn("DxfMergeEnds", "End points merge: Enable merging", lambda: o("merge"),
               lambda v: _dx().set_dxf_options(merge=v), "Line ends closer than the merge distance are written meeting"),
        NumberFn("DxfMergeDistance", "Merge distance", "mm", 0.0001, 100.0, lambda: o("merge_distance") or merge_default,
                 lambda v: _dx().set_dxf_options(merge_distance=v), decimals=4, needs="DxfMergeEnds"),
        Radio("DxfSplines", "Splines", [("Export all splines as splines", "Splines"),
                                        ("Export all splines as polylines", "Polylines")],
              lambda: o("splines"), lambda v: _dx().set_dxf_options(splines=v), "How curves are written"),
        BoolFn("DxfViewsAsBlocks", "Export drawing views as blocks", lambda: o("views_blocks"),
               lambda v: _dx().set_dxf_options(views_blocks=v), "Each drawing view's lines go in a block of its own"),
        Radio("DxfSheets", "Multiple sheet drawing", [(x, x) for x in _dx().DXF_SHEETS], lambda: o("dxf"),
              lambda v: _dx().set_options(dxf=v), "Which sheets of a drawing are written"),
    ]


def _dxf_params():
    from . import paths
    return paths.params()


def _merge(title, sections, freecad, base):
    """options.py's own settings for this page that are not here go on top."""
    if title not in base:
        return sections, freecad
    b_sections, b_freecad = base[title]
    here = {s.key for _h, ss in sections for s in ss}
    extra = [s for _h, ss in b_sections for s in ss if s.key not in here]
    return ([(None, extra)] if extra else []) + sections, freecad or b_freecad


def _tech_template_read():
    return _param("Mod/TechDraw/Files").GetString("TemplateFile", "")


def _tech_template_write(path):
    _param("Mod/TechDraw/Files").SetString("TemplateFile", path)


def folders(kind):
    """The folders kept for a File Locations kind (Options > File Locations)."""
    got = _fw().GetGroup("FileLocations").GetString(kind.replace(" ", ""), "")
    if got:
        return [f for f in got.split(";") if f]
    if kind == "Macros":
        return [App.getUserMacroDir(True)]
    if kind == "Sheet Formats":
        td = _param("Mod/TechDraw/Files").GetString("TemplateDir", "")      # extapps86: TechDraw's own folder
        return [td or os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Templates")]
    if kind == "Material Databases":
        return [os.path.join(App.getResourceDir(), "Mod", "Material", "Resources", "Materials")]
    return []


def _folders_write(kind, values):
    _fw().GetGroup("FileLocations").SetString(kind.replace(" ", ""), ";".join(values))
    if kind == "Macros" and values:
        _param("Macro").SetString("MacroPath", values[0])      # FreeCAD's own macro folder
    try:        # extapps86: the other kinds go to what reads them
        from . import optionswire
        optionswire.folders_changed(kind, values)
    except Exception as _fw_err:
        _fw_log("optionspages.py:folders", _fw_err)


def _external_references():
    L = _later("External References")
    return [
        (None, [
            L("Open referenced documents with read-only access", False),
            L("Don't prompt to save read-only referenced documents (discard changes)", False),
            L("Allow multiple contexts for parts when editing in assembly", False),
            L("Load referenced documents", "Prompt"),
            L("Load documents in memory only", True),
        ]),
        ("Search external references in", [
            L("Reference Documents specified in File Locations", True),
            L("Include sub-folders", False),
            L("Exclude active folders and recent save locations", False),
            Button("Go To Reference Documents", go_to(0, "File Locations")),
        ]),
        (None, [L("Update out-of-date linked design tables to", "Prompt")]),
        ("Assemblies", [
            L("Automatically generate names for referenced geometry", False),
            L("Update component names when documents are replaced", True),
            L("Allow creation of references external to the model", True),
            Radio("RefComponentType", "Reference component type", [("Any component", "Any component"),
                                                                   ("Only envelope component", "Only envelope component")],
                  lambda: stored("External References", "Reference component type", "Any component"),
                  lambda v: set_stored("External References", "Reference component type", v),
                  "Which components a part edited in context can take references from"),     # extapps86
            Radio("RefContext", "In the context of", [("Top level assembly", "Top level assembly"),
                                                      ("Same subassembly", "Same subassembly")],
                  lambda: stored("External References", "In the context of", "Top level assembly"),
                  lambda v: set_stored("External References", "In the context of", v),
                  "Same subassembly: only components of the edited part's own subassembly"),
        ]),
        (None, [
            L("Show \"x\" in feature tree for broken external references", True),
            L("Force referenced document to save to current major version", True),
        ]),
    ]


def _default_templates():
    L = _later("Default Templates")
    fw = _fw()
    return [
        (None, [Note("These templates are used for operations where FreeCAD does not prompt you for a template, "
                     "and in the novice mode of the New FreeCAD Document dialog.")]),
        ("Templates used where a template is not asked for", [
            PathFn("PartTemplate", "Parts", lambda: fw.GetString("PartTemplate", ""),
                   lambda v: fw.SetString("PartTemplate", v), filt="FreeCAD documents (*.FCStd)",
                   tip="A part made by New starts as a copy of this document (empty: an empty part)"),
            PathFn("AssemblyTemplate", "Assemblies", lambda: fw.GetString("AssemblyTemplate", ""),
                   lambda v: fw.SetString("AssemblyTemplate", v), filt="FreeCAD documents (*.FCStd)"),
            PathFn("DrawingTemplate", "Drawings", _tech_template_read, _tech_template_write,
                   filt="Drawing templates (*.svg)", tip="TechDraw's default template"),
        ]),
        ("Up axis for new parts and assemblies", [
            Radio("NewDocUpAxis", "", [("Y-up", "Y"), ("Z-up", "Z")],
                  lambda: "Z" if fw.GetString("NewDocUpAxis", "Y").upper().startswith("Z") else "Y",
                  lambda v: fw.SetString("NewDocUpAxis", "Z" if v == "Z" else "Y"),
                  tip="The up direction new parts and assemblies start with (View > Modify > "
                      "Y-Up / Z-Up changes one document)")]),
        (None, [Radio("TemplatePrompt", "", [("Always use these default document templates", False),
                                             ("Prompt user to select document template", True)],
                      lambda: fw.GetBool("TemplatePrompt", False),
                      lambda v: fw.SetBool("TemplatePrompt", bool(v)))]),
    ]


# extapps86: the kinds something reads (optionswire); Custom Property Files, Appearances and Textures are left out
# (nothing in FreeCAD lists those from folders)
FOLDER_KINDS = ("Document Templates", "Reference Documents", "Sheet Formats", "Design Library", "Macros",
                "Material Databases", "Bend Tables", "Decals")


def _file_locations():
    return [(None, [FolderList(FOLDER_KINDS, folders, _folders_write)])]


def _touch():
    L = _later("Touch")
    return [(None, [
        Radio("TouchMode", "Touch Mode", [("Right Hand (menus on the left)", "Right Hand"),
                                          ("Left Hand (menus on the right)", "Left Hand")],
              lambda: stored("Touch", "Touch Mode", "Right Hand"),
              lambda v: set_stored("Touch", "Touch Mode", v)),
        L("Automatically pop up Selection tool while hunting for precise location", True),
    ])]


def _toolbox_settings(dialog):
    from . import toolboxconfig
    return toolboxconfig.show(dialog)


def _hole_wizard():
    L = _later("Hole Wizard/Toolbox")
    fw = _fw()
    return [
        (None, [
            PathFn("ToolboxFolder", "Hole Wizard and Toolbox folder", lambda: fw.GetString("ToolboxFolder", ""),
                   lambda v: fw.SetString("ToolboxFolder", v), folder=True),
            L("Make this folder the default search location for Toolbox components", True),
            Button("Configure", lambda d: _toolbox_settings(d),
                   "Toolbox Settings: Hole Wizard sizes, permissions, hardware and Smart Fasteners"),
        ]),
        ("Toolbox Task Pane", [L("Display Toolbox Favorites folder", True)]),
        ("Toolbox Mates", [L("Lock rotation of new concentric mates to Toolbox components", False)]),
        ("Hole Wizard settings", [
            Radio("HoleWizardSettings", "", [("Preserve settings for each Hole Wizard hole type", "Preserve"),
                                             ("Transfer settings when changing Hole Wizard hole type", "Transfer")],
                  lambda: stored("Hole Wizard/Toolbox", "Hole Wizard settings mode", "Transfer"),
                  lambda v: set_stored("Hole Wizard/Toolbox", "Hole Wizard settings mode", v))]),
    ]


def _file_explorer():
    L = _later("File Explorer")
    return [("Show in File Explorer view", [
        L("My Documents", True), L("My Computer", True), L("My Network Places", False),
        L("Recent Documents", False), L("Hidden referenced documents", True), L("Samples", False)])]


def _search():
    L = _later("Search")
    return [
        (None, [Fixed("Show search box", True)]),
        ("File and Model Search", [
            L("Search while typing (incremental search)", True),
            L("Include online content results", False),
            L("Results per page", 10),
            L("Maximum results per data source", 100),
        ]),
        ("Indexing performance", [L("Indexing performance", "Index only when computer is idle")]),
    ]


def _collaboration():
    L = _later("Collaboration")
    on = L("Enable multi-user environment", False)
    menus = L("Add shortcut menu items for multi-user environment", False)
    check = L("Check if files opened read-only have been modified by other users", False)
    every = L("Check files every (minutes)", 20)
    menus.needs = check.needs = on.key      # extapps86: shown while the box above them is ticked
    every.needs = check.key
    return [(None, [on, menus, check, every])]


def _drawings_rows():
    ""
    L = _later("Drawings")
    qty = L("Override quantity column name in BOM", False)
    name = L("Name to use", "")             # extapps84: shown while Override quantity column name is ticked
    name.needs = qty.key
    return [
        L("Eliminate duplicate model dimensions on insert", True),
        L("Eliminate duplicate model notes on insert", True),
        L("Automatically scale new drawing views", True),
        L("Enable symbol when adding new revision", True),
        L("Disable note/dimension inference", False),
        L("Print out-of-sync water mark", True),                    # extapps84
        L("Display sketch arc centerpoints", False),
        L("Display sketch entity points", False),
        L("Display sketch hatch behind geometry", False),         # extapps85
        L("Display sketch pictures in drawings", False),
        L("Print breaklines in broken view", True),
        L("Automatically populate View Palette with views", True),
        L("Show sheet format dialog when adding new sheet", False),
        L("Reuse view letters from deleted auxiliary, detail, and section views", False),
        qty,
        name,
        NumberFn("DetailViewScaling", "Detail view scaling", "X", 0.01, 100.0,
                 lambda: float(stored("Drawings", "Detail view scaling", 2.0) or 2.0),
                 lambda v: set_stored("Drawings", "Detail view scaling", float(v)), decimals=2,
                 tip="A new detail view's scale: this many times its parent view's"),
        L("Custom property used as Revision", "Revision"),
    ]


def system_pages(base=()):
    ""
    _managed[:] = []
    base = {t: (s, f) for t, s, f, _c in base}
    pages = [
        ("General", _general(), ("General", 0, "General"), []),
        ("MBD", [(None, [Button("Model Based Definition (Document Properties - Detailing)...", go_to(1, "Detailing"),
                                 "The 3D annotations' settings are the document's: Document Properties > Detailing")])],
         None, []),
        ("Drawings", [(None, _drawings_rows() + [NumberFn("KeyboardMovementIncrement", "Keyboard movement increment", "mm", 0.001, 1000.0,
                                        lambda: _param("Mod/FreeWorks/Drawings").GetFloat("KeyboardMovementIncrement", 10.0),
                                        lambda v: _param("Mod/FreeWorks/Drawings").SetFloat("KeyboardMovementIncrement", float(v)),
                                        decimals=2, tip="How far the arrow keys move a picked drawing item")])],
         ("TechDraw", 0, "TechDraw"), [

            ("Display Style", _stub("Display Style", [("Display style", "Hidden lines removed"),
                                                      ("Tangent edges", "Visible"),
                                                      ("Edge quality for new views", "High quality")]), None, []),
            # hatchspin-1120 (AF2): Scale and Angle as short spin boxes, as on Document Properties > Material Properties
            ("Area Hatch/Fill", [(None, _stub("Area Hatch/Fill", [("Hatch", "Hatch"), ("Pattern", "ANSI31 (Iron BrickStone)")])[0][1]
                                  + [_HatchNumber("Scale", "1", "Area Hatch/Fill"),
                                     _HatchNumber("Angle", "0.00deg", "Area Hatch/Fill")])], None, []),
            ("Performance", _stub("Performance", [("Show contents while dragging drawing view", True),
                                                  ("Allow auto-update when opening drawings", True),

                                                  ("Open drawings in Detailing mode by default", False)]),
             None, [])]),
        ("Colors", _colors(), ("Display", 4, "Display > Colors"), []),
        ("Sketch", _sketch(), ("Sketcher", 2, "Sketcher > General"), [("Relations/Snaps", _relations_snaps(), None, [])]),
        ("Display", _display(), ("Display", 0, "Display > 3D View"), []),
        ("Selection", _selection(), ("General", 2, "General > Selection"), []),
        ("Performance", _performance(), ("Display", 5, "Display > Advanced"), []),
        ("Assemblies", _assemblies(), ("Assembly", 0, "Assembly"), []),
        ("External References", _external_references(), None, []),
        ("Default Templates", _default_templates(), None, []),
        ("File Locations", _file_locations(), None, []),
        ("FeatureManager", _feature_manager(), None, []),
        ("Spin Box Increments", _spin_increments(), None, []),
        ("View", _view(), ("Display", 3, "Display > Navigation"), []),
        ("Backup/Recover", _backup(), ("General", 1, "General > Document"), []),
        ("Touch", _touch(), None, []),
        ("Hole Wizard/Toolbox", _hole_wizard(), None, []),
        ("File Explorer", _file_explorer(), None, []),
        ("Search", _search(), None, []),
        ("Collaboration", _collaboration(), None, []),
        ("Messages/Errors/Warnings", _messages(), None, [("Dismissed Messages", _dismissed(), None, [])]),
        ("Import", _import(), ("Import-Export", 0, "Import-Export"), []),
        ("Export", _export(), ("Import-Export", 0, "Import-Export"), [
            ("Print3D Printers", _print3d_printers(), None, [])]),
    ]
    out = []
    for title, sections, freecad, children in pages:
        sections, freecad = _merge(title, sections, freecad, base)
        out.append((title, sections, freecad, children))
    return out


# ---------------------------------------------------------------- Document Properties
def _doc_set(page, text, value):
    set_stored(page, text, value)
    doc = App.ActiveDocument
    if doc is not None:
        meta = dict(doc.Meta)
        meta[DOC_META + _store_key(page, text)] = ("1" if value else "0") if isinstance(value, bool) else str(value)
        doc.Meta = meta


def _plane_display():
    L = _doc_later("Plane Display")
    return [
        ("Faces", [L("Front Face Color", "#6496C8"), L("Back Face Color", "#C8A064"), L("Transparency (%)", 75)]),
        ("Intersections", [L("Show intersections", True), L("Line Color", "#3C3C3C")]),
    ]


def _configurations():
    L = _doc_later("Configurations")
    return [
        (None, [L("Add Rebuild on Save mark to new configurations", False),
                L("Add Display Data Mark to new configurations", False)]),
        ("Default Bill Of Materials part number for new configurations",
         [L("Default Bill Of Materials part number for new configurations", "Document Name")]),
    ]



# features/options-read-list.md); each holds the settings that page is about, kept per document.
SUB_PAGES = {
    "Annotations": (("Text", (("Font", "Century Gothic"),)), ("Leader", (("Leader style", "Straight"),
                    ("Leader thickness", "Thin"))), ("Attachments", (("Edge/vertex", "Filled"), ("Face/surface",
                    "Dot"), ("Unattached", "Filled"))), (None, (("Use bent leaders", False),
                    ("Leader length", 6.35)))),
    "Balloons": (("Text", (("Font", "Century Gothic"),)), ("Single balloon", (("Style", "Circular"),
                 ("Size", "2 Characters"))), ("Stacked balloons", (("Stacked Style", "Circular"), ("Stacked Size", "2 Characters"))),
                 ("Balloon text", (("Upper", "Item Number"), ("Lower", "Quantity"))), (None, (("Leader style",
                 "Straight"), ("Auto balloon layout", "Square")))),
    "Datums": (("Text", (("Font", "Century Gothic"),)), ("Display type", (("Display type", "Per Standard"),)),
               ("Label", (("Next label", "A"),)), (None, (("Leader style", "Straight"), ("Frame style",
               "Square")))),
    "Geometric Tolerances": (("Text", (("Font", "Century Gothic"),)), ("Leader", (("Leader style", "Straight"),
                             ("Leader anchor", "Closest"))), (None, (("Frame style", "Square"),
                             ("Frame thickness", "Thin")))),
    "Notes": (("Text", (("Font", "Century Gothic"),)), ("Leader", (("Leader style", "Straight"),
              ("Leader anchor", "Closest"))), ("Border", (("Style", "None"), ("Size", "Tight Fit"))),
              (None, (("Bent leader length", 6.35), ("Use bent leaders", False)))),
    "Revision Clouds": ((None, (("Line style", "Solid"), ("Line thickness", "Thick"), ("Maximum arc radius",
                        5.0))),),
    "Surface Finishes": (("Text", (("Font", "Century Gothic"),)), ("Leader", (("Leader style", "Straight"),
                         ("Leader anchor", "Closest"))), (None, (("Display symbols per 2002", True),
                         ("Display symbols per ISO 21920-1", False)))),
    "Weld Symbols": (("Text", (("Font", "Century Gothic"),)), ("Leader", (("Leader style", "Straight"),)),
                     (None, (("Fixed size weld symbols", True), ("Weld bead display", "Simplified")))),
    "Angle": (("Text", (("Font", "Century Gothic"),)), ("Precision", (("Primary precision", "0"),
              ("Tolerance", "None"))), ("Leader display", (("Arrows", "Smart"),)), ("Text position",
              (("Text position", "Solid leader, aligned text"),))),
    "Angular Running": (("Text", (("Font", "Century Gothic"),)), ("Precision", (("Primary precision", "0"),)),
                        (None, (("Display as chain dimension", False), ("Extension line arcs", True)))),
    "Arc Length": (("Text", (("Font", "Century Gothic"),)), ("Precision", (("Primary precision", ".12"),)),
                   ("Leader display", (("Arrows", "Smart"),)), (None, (("Display arc symbol", True),))),
    "Chamfer": (("Text", (("Font", "Century Gothic"),)), ("Chamfer text format", (("Format", "1 X 45°"),)),
                ("Precision", (("Primary precision", ".12"), ("Angle precision", "0")))),
    "Diameter": (("Text", (("Font", "Century Gothic"),)), ("Precision", (("Primary precision", ".12"),
                 ("Tolerance", "None"))), ("Leader display", (("Arrows", "Smart"), ("Display second outside "
                 "arrow", False))), ("Text position", (("Text position", "Broken leader, horizontal text"),))),
    "Hole Callout": (("Text", (("Font", "Century Gothic"),)), ("Precision", (("Primary precision", ".12"),)),
                     (None, (("Use per standard", True), ("Show hole depth", True)))),
    "Linear": (("Text", (("Font", "Century Gothic"),)), ("Precision", (("Primary precision", ".12"),
               ("Tolerance", "None"))), ("Leader display", (("Arrows", "Smart"),)), ("Text position",
               (("Text position", "Solid leader, aligned text"),)), (None, (("Use bent leaders", False),))),
    "Ordinate": (("Text", (("Font", "Century Gothic"),)), ("Precision", (("Primary precision", ".12"),)),
                 (None, (("Display as chain dimension", False), ("Jog lines", True)))),
    "Radius": (("Text", (("Font", "Century Gothic"),)), ("Precision", (("Primary precision", ".12"),
               ("Tolerance", "None"))), ("Leader display", (("Arrows", "Smart"),)), ("Text position",
               (("Text position", "Broken leader, horizontal text"),))),
    "Virtual Sharps": ((None, (("Virtual sharp style", "Plus"), ("Extension lines", False))),),
    "Tables": (("Border", (("Box thickness", "Thin"), ("Grid thickness", "Thin"))), ("Text",
               (("Font", "Century Gothic"),)), (None, (("Leading zeroes", "Standard"), ("Trailing zeroes",
               "Smart")))),
    "Bend": (("Text", (("Font", "Century Gothic"),)), (None, (("Alpha/numerical control", "A, B, C..."),
             ("Precision", ".12"), ("Anchor", "Top Left")))),
    "Bill of Materials": (("Text", (("Font", "Century Gothic"),)), (None, (("Leading zeroes", "Standard"),
                          ("Trailing zeroes", "Smart"), ("Do not add QTY next to configuration name", False),
                          ("Zero quantity display", "0"), ("Missing component", "Display with strikethrough"),
                          ("Anchor", "Top Left")))),
    "General": (("Text", (("Font", "Century Gothic"),)), (None, (("Anchor", "Top Left"),))),
    "Hole": (("Text", (("Font", "Century Gothic"),)), (None, (("Scheme", "Letters"), ("Alpha/numerical "
             "control", "A, B, C..."), ("Origin indicator", "Per Standard"), ("Combine same tags", False),
             ("Precision", ".12"), ("Anchor", "Top Left")))),
    "Title Block Table": (("Text", (("Font", "Century Gothic"),)), (None, (("Leading zeroes", "Standard"),
                          ("Trailing zeroes", "Smart")))),
    "DimXpert": ((None, (("Methods", "Block Tolerance"), ("Block tolerance, length", 0.1),
                         ("Block tolerance, angle", 0.5))),),
    "Size Dimension": ((None, (("Fillet options", "Symmetric"), ("Chamfer options", "Symmetric"),
                               ("Slot dimensioning", "Width and length"))),),
    "Location Dimension": ((None, (("Create basic dimension", False), ("Slot location", "Center"))),),
    "Chain Dimension": ((None, (("Dimension style", "Baseline"), ("Pattern dimensioning", "Linear"))),),
    "Geometric Tolerance": ((None, (("Primary datums, form", "Flatness"), ("Primary datums, tolerance", 0.05),
                                    ("Position tolerance", 0.1), ("Profile tolerance", 0.1))),),
    "Chamfer Controls": ((None, (("Width limit", 0.0), ("Use tolerance", True))),),
    "Display Options": ((None, (("Dimensions, redundant", "Hide"), ("Tolerances, redundant", "Hide"),
                                ("Display as Basic dimensions", False))),),
    "Sheet Metal MBD": ((None, (("Bend line notes", "Show"), ("Bend direction", "Up/Down"),
                                ("Bend angle", True), ("Inner radius", True))),),
    "Sheet Metal": (("Flat pattern colors", (("Bend Lines - Up Direction", "#0000FF"),
                    ("Bend Lines - Down Direction", "#FF0000"), ("Form Features", "#808080"),
                    ("Bend Lines - Hems", "#00FF00"), ("Model Edges", "#000000"),
                    ("Flat Pattern Sketch Color", "#000000"), ("Bounding Box", "#808080"))),
                    ("Bend notes", (("Display sheet metal bend notes", True), ("Bend note style",
                    "Above Bend Line"))), (None, (("Simplify bends", True), ("Corner treatment", True),
                    ("Show fixed face", False), ("Show grain direction", False))),

                    ("Edge Flange Options", (("Automatically add Flange Length dimensions to flange profiles",
                                              False),))),
    "Weldments": ((None, (("Rename cut list folders with Description property value", False),
                          ("Assign custom properties: Description", True), ("Assign custom properties: Length",
                          True), ("Assign custom properties: Angle 1", True), ("Assign custom properties: Angle 2",
                          True), ("Create derived configurations", True))),
                  ("Weld bead", (("Bead weight", "Mass from bead volume"),
                                 ("Mass per unit length (kg/m)", 0.25))),),
}


def _sub_page(page):
    L = _doc_later(page)
    rows = SUB_PAGES.get(page, ((None, (("Font", "Century Gothic"),)),))
    # options-1119: no greyed rows (drawing-only ones live in the drawing's own Document Properties) and no
    # rows nothing reads in a part
    out = []
    for head, items in rows:
        keep = [_shown(L(t, d), head) for t, d in items if (page, t) not in GREYED and (page, t) not in UNREAD]
        if keep:
            out.append((head, keep))
    return out


def _shown(setting, head):
    ""

    if head and setting.text.startswith(head.split()[0] + " "):
        plain = setting.text[len(head.split()[0]) + 1:]
        base = type(setting)

        def widget(self):
            w = base.widget(self)
            for lab in [w] + list(w.findChildren(QtWidgets.QLabel)) + list(w.findChildren(QtWidgets.QCheckBox)):
                try:
                    if lab.text() == self.text:
                        lab.setText(plain)
                except Exception as _fw_err:
                    _fw_log("optionspages.py:2613", _fw_err)
            return w
        # optred-1119: a method of the row's own class, not a function kept on this one object. The Options
        # box builds a copy of each row (options._copy), and a kept function filled the original's box, so
        # the copy had none: 12 Document Properties pages failed to build ("'DocLater' has no attribute 'box'")
        setting.__class__ = type(base.__name__, (base,), {"widget": widget, "__module__": base.__module__})
    return setting


def document_pages(base=()):
    ""
    _managed[:] = []
    base = {t: (s, f) for t, s, f, _c in base}
    drafting, drafting_fc = base.get("Drafting Standard", ([], None))
    units, units_fc = base.get("Units", ([], None))
    LU = _doc_later("Units")
    units = list(units) + [("Decimal rounding", [
        LU("Decimal rounding", "Round half away from zero"),
        LU("Only apply rounding method to dimensions", True),
    ])]
    LS = _doc_later("Drafting Standard")
    from . import draftstd
    drafting = list(drafting) + [(None, draftstd.buttons()), ("Uppercase", [
        LS("All uppercase for notes", False),
        LS("All uppercase for tables", False),
        LS("All uppercase for dimensions and hole callouts", False),
        LS("Exclusion list", "m;mm;cm;km;um;µm;nm;s;Hz;Pa;")])]
    LD = _doc_later("Dimensions")
    dimensions = [
        ("Text", [LD("Font", "Century Gothic")]),
        ("Dual dimensions", [LD("Dual dimensions display", False), LD("Show units for dual display", False),
                             LD("Dual dimension position", "Top")]),
        ("Primary precision", [LD("Primary precision", ".12"), LD("Primary tolerance precision", "Same as nominal")]),
        ("Dual precision", [LD("Dual precision", ".123"), LD("Dual tolerance precision", "Same as nominal")]),
        ("Fractional display", [LD("Fraction style", "Stacked"), LD("Stack size", "100%"),
                                LD("Include leading zero for values less than 1\"", False)]),
        ("Bent leaders", [LD("Leader length", 6.35)]),
        ("Zeroes", [LD("Leading zeroes", "Standard"), LD("Trailing zeroes, dimensions", "Smart"),
                    LD("Trailing zeroes, tolerances", "Smart"), LD("Trailing zeroes, properties", "Smart")]),
        ("Arrows", [LD("Arrow width", 1.0), LD("Arrow length", 3.3), LD("Arrow length with extension", 6.35),
                    LD("Scale with dimension height", False), LD("Arrow style", "Filled"),
                    LD("Arrow placement", "Smart")]),
        ("Offset distances", [LD("Offset from model", 10.0), LD("Offset between dimensions", 6.0)]),
        ("Radial/Diameter leader snap angle", [LD("Leader snap angle", 15.0)]),
        (None, [
            BoolFn("ShowUnits", "Show units of dimensions", lambda: not _param(SKETCHER).GetBool("HideUnits", False),
                   lambda v: write(SKETCHER, "Boolean", "HideUnits", not v)),
            LD("Add parentheses by default", False),
            LD("Center between extension lines", False),
            LD("Show dimensions as broken in break views", True),
            LD("Highlight overridden dimensions in a different color", True),
            LD("Include prefix inside basic tolerance box", False),
            LD("Display dual basic dimension in one box", False),
        ]),
    ]
    LT = _doc_later("Detailing")
    detailing = [
        ("Display filter", [BoolFn("CosmeticThreadsDisplay", "Cosmetic threads",
                                   lambda: _cosmetic().GetBool("Display", True),
                                   lambda v: _cosmetic().SetBool("Display", v)),
                            BoolFn("CosmeticThreadsShaded", "Shaded cosmetic threads",
                                   lambda: _cosmetic().GetBool("Shaded", False),
                                   lambda v: _cosmetic().SetBool("Shaded", v)),
                            LT("Datums", True),
                            LT("Geometric tolerances", True), LT("Datum targets", True), LT("Notes", True),
                            LT("Feature dimensions", False), LT("Surface finish", True),
                            LT("Reference dimensions", True), LT("Welds", True), LT("DimXpert dimensions", True),
                            LT("Display all types", False)]),
        ("Point, Axis, and Coordinate System", [LT("Hide names", False), LT("Name font", "Century Gothic"),
                                                LT("Label font", "Century Gothic")]),
        ("Text scale", [LT("Always display text at the same size", True)]),
        (None, [
            LT("Display items only in the view in which they are created", False),
            BoolFn("DisplayAnnotations", "Display annotations", _annotations_read, _annotations_write),
            LT("Hide dangling dimensions and annotations", False),
            LT("Highlight associated elements on reference dimension selection", True),
        ]),
    ]
    # the grid spacing in the document's length unit (inches in an IPS part)
    try:
        from . import unitspage
        grid_unit = unitspage.length_unit()
    except Exception:
        grid_unit = ("mm", 1.0)
    grid = [
        ("Grid", [
            BoolFn("DisplayGrid", "Display grid", _grid_read, _grid_write),
            BoolFn("GridDash", "Dash", lambda: _param(SK_GENERAL).GetInt("GridLinePattern", 0x0f0f) != 0xffff,
                   lambda v: _param(SK_GENERAL).SetInt("GridLinePattern", 0x0f0f if v else 0xffff),
                   tip="Minor grid lines dashed (FreeCAD's Sketcher grid line pattern)"),
            BoolFn("GridAuto", "Automatic scaling", lambda: _param(SK_GENERAL).GetBool("GridAuto", True),
                   _grid_auto_write),
            NumberFn("MajorGrid", "Major grid spacing", grid_unit[0], 0.0001, 10000, lambda: _major_read() / grid_unit[1],
                     lambda v: _major_write(v * grid_unit[1]), decimals=4 if grid_unit[1] > 1.0 else 2),
            NumberFn("MinorLines", "Minor-lines per major", "", 1, 100, _minor_read, _minor_write),
            DocLater("Snap points per minor", 1, "Grid/Snap"),
        ]),
        (None, [Button("Go To System Snaps", go_to(0, "Relations/Snaps"))]),
    ]
    LM = _doc_later("Model Display")
    model_display = [
        (None, [
            LM("Wireframe/HLR color", "#000000"), LM("Shading color", "#C8C8C8"), LM("Hidden color", "#808080"),
            LM("Boss color", ""), LM("Cut color", ""), LM("Fillet color", ""), LM("Chamfer color", ""),
            LM("Apply same color to wireframe, HLR and shaded", False),
            LM("Ignore feature colors", False),
            Button("Go To System Colors", go_to(0, "Colors")),
        ]),
        ("Comment background colors", [LM("Description", "#FFFFC0"), LM("High Priority", "#FFC0CB"),
                                       LM("Low Priority", "#D3D3D3"), LM("Complete", "#C0FFC0"),
                                       LM("Reminder", "#C0E0FF")]),
        (None, [
            LM("Store appearance, decal, and scene data in model file", False),
            LM("Store images for OLE object data in model file", True),
        ]),
    ]
    material = [
        (None, [
            Combo("Material", "Material", _material_choices, _material_read, _material_write,
                  "The material of every body (the Material row's favourites)"),
            DensityRow(),
            Radio("AreaHatch", "Area hatch/fill", [("None", "None"), ("Solid", "Solid"), ("Hatch", "Hatch")],
                  lambda: doc_value(App.ActiveDocument, "Material Properties", "Area hatch/fill", "Hatch"),
                  lambda v: _doc_set("Material Properties", "Area hatch/fill", v)),
            DocLater("Pattern", "ANSI31 (Iron BrickStone)", "Area Hatch/Fill"),
            DocLater("Scale", 1.0, "Area Hatch/Fill"),
            DocLater("Angle", 0.0, "Area Hatch/Fill"),
        ]),
    ]
    LI = _doc_later("Image Quality")
    is_assembly = _assembly() is not None
    shaded = QualityFn("Deviation", "Deviation", "%", 0.01, 5.0, _deviation_read, _deviation_write, decimals=2,
                       tip="Low (faster) to High (slower): how finely this document's shapes are drawn, round "
                           "faces too (saved with the document)")
    angular = QualityFn("AngularDeflection", "Angular deviation", "°", 1.0, 60.0, _angular_read, _angular_write,
                        decimals=1)
    shaded.partner = angular
    image = [
        ("Shaded and draft quality HLR/HLV resolution", [
            shaded,
            LI("Optimize edge length (higher quality, but slower)", False),
        ] + ([ApplyToParts("Apply to all referenced part documents", False, "Image Quality")] if is_assembly else [
            LI("Save tessellation with part document", False)])),
        ("Wireframe and high quality HLR/HLV resolution", [
            angular,
            LI("Improve curve quality at higher settings", False),
        ]),
        (None, [
            LI("Use isometric, zoom to fit view for document preview", True),
            Button("Go To Performance", go_to(0, "Performance")),
        ]),
    ]

    def stub(page):
        return _sub_page(page)

    def subs(*titles):
        return [(t, stub(t), None, []) for t in titles]

    pages = [

        # Ati's screen 2026-11-01)
        ("Drafting Standard", drafting, drafting_fc, [
            ("Annotations", stub("Annotations"), None, subs("Balloons", "Datums", "Geometric Tolerances",
                                                            "Notes", "Revision Clouds", "Surface Finishes",
                                                            "Weld Symbols")),
            ("Dimensions", dimensions, None, subs("Angle", "Angular Running", "Arc Length", "Chamfer",
                                                  "Diameter", "Hole Callout", "Linear", "Ordinate", "Radius")),
            ("Virtual Sharps", stub("Virtual Sharps"), None, []),
            ("Tables", stub("Tables"), None, subs("Bend", "Bill of Materials", "General", "Hole",
                                                  "Title Block Table")),
            ("DimXpert", stub("DimXpert"), None, subs("Size Dimension", "Location Dimension",
                                                      "Chain Dimension", "Geometric Tolerance",
                                                      "Chamfer Controls", "Display Options")),
        ]),
        ("Detailing", detailing, None, []),
        ("Grid/Snap", grid, None, []),
        ("Units", units, units_fc, []),
        ("Model Display", model_display, None, []),
        ("Material Properties", material, None, []),
        ("Image Quality", image, ("Part/Part Design", 1, "Part/Part Design > Shape View"), []),
        ("Sheet Metal MBD", _sub_page("Sheet Metal MBD"), None, []),
        ("Sheet Metal", _sub_page("Sheet Metal"), None, []),
        ("Weldments", _sub_page("Weldments"), None, []),
        ("Plane Display", _plane_display(), None, []),
        ("Configurations", _configurations(), None, []),
    ]
    if is_assembly:
        # an assembly's Document Properties have no Material Properties, Sheet Metal MBD, Sheet Metal

        pages = [p for p in pages if p[0] not in ASSEMBLY_HIDDEN]
    return pages
