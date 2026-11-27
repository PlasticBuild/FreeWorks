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

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Swatches"
COMMAND = "SWStyle_ChangeTransparency"


OWN = (
    ("Standard", ("#ffffff", "#c0c0c0", "#808080", "#404040", "#000000", "#ff0000", "#ff8000", "#ffff00",
                  "#80ff00", "#00ff00", "#00ff80", "#00ffff", "#0080ff", "#0000ff", "#8000ff", "#ff00ff",
                  "#800000", "#804000", "#808000", "#008000", "#008080", "#000080", "#400080", "#800040")),
    ("Soft", ("#f4cccc", "#fce5cd", "#fff2cc", "#d9ead3", "#d0e0e3", "#cfe2f3", "#d9d2e9", "#ead1dc",
              "#ea9999", "#f9cb9c", "#ffe599", "#b6d7a8", "#a2c4c9", "#9fc5e8", "#b4a7d6", "#d5a6bd")),
    ("Metals", ("#b5b7ba", "#d4d6d9", "#8c8f93", "#c9ae5d", "#b87333", "#e5e4e2", "#71797e", "#aaa9ad")),
)
OWN_NAMES = tuple(n for n, _c in OWN)


# ---- palettes ----------------------------------------------------------------------------------

def _user():
    try:
        data = json.loads(App.ParamGet(PARAMS).GetString("Palettes", "") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_user(data):
    App.ParamGet(PARAMS).SetString("Palettes", json.dumps(data))


def palettes():
    ""
    user = _user()
    out = [(n, list(c) + list(user.get(n, []))) for n, c in OWN]
    out += [(n, list(c)) for n, c in user.items() if n not in OWN_NAMES]
    return out


def colours(name):
    return dict(palettes()).get(name, [])


def add_colour(name, hexcolour):
    data = _user()
    row = data.setdefault(name, [])
    if hexcolour not in row and hexcolour not in dict(OWN).get(name, ()):
        row.append(hexcolour)
    _save_user(data)


def new_palette(name):
    name = (name or "").strip()
    if not name or name in dict(palettes()):
        return False
    data = _user()
    data[name] = []
    _save_user(data)
    return True


def delete_palette(name):
    ""
    data = _user()
    if name in data:
        del data[name]
        _save_user(data)
        return True
    return False


class SwatchBox(QtWidgets.QGroupBox):
    """The palette list, its cells and the three buttons; picked(QColor) on a cell click."""

    picked = QtCore.Signal(QtGui.QColor)

    def __init__(self, current, parent=None):
        super().__init__("Swatches", parent)
        self.setObjectName("SWSwatches")
        self.current = current          # function: the colour now (for Add)
        lay = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.combo = QtWidgets.QComboBox(self)
        self.combo.setObjectName("SWSwatchPalette")
        self.combo.setToolTip("The palette whose colors show below")
        row.addWidget(self.combo, 1)
        self.add_button = self._tool(row, "+", "SWSwatchAdd", "Adds the color now to this palette", self._add)
        self.new_button = self._tool(row, "New", "SWSwatchNew", "Makes a new, empty palette", self._new)
        self.del_button = self._tool(row, "x", "SWSwatchDelete", "Deletes this palette (on a built-in one, the colors you added)",
                                     self._delete)
        lay.addLayout(row)
        self.grid_host = QtWidgets.QWidget(self)
        self.grid = QtWidgets.QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(2)
        lay.addWidget(self.grid_host)
        self.cells = []
        self.combo.currentIndexChanged.connect(lambda _i: self.fill())
        self.reload()

    def _tool(self, row, text, name, tip, fn):
        b = QtWidgets.QToolButton(self)
        b.setText(text)
        b.setObjectName(name)
        b.setToolTip(tip)
        b.clicked.connect(fn)
        row.addWidget(b)
        return b

    def reload(self, keep=None):
        keep = keep or self.combo.currentText() or "Standard"
        self.combo.blockSignals(True)
        self.combo.clear()
        for name, _c in palettes():
            self.combo.addItem(name)
        i = self.combo.findText(keep)
        self.combo.setCurrentIndex(max(0, i))
        self.combo.blockSignals(False)
        self.fill()

    def fill(self):
        for c in self.cells:
            c.setParent(None)
            c.deleteLater()
        self.cells = []
        for i, hexcolour in enumerate(colours(self.combo.currentText())):
            col = QtGui.QColor(hexcolour)
            b = QtWidgets.QToolButton(self.grid_host)
            b.setFixedSize(16, 16)
            b.setAutoRaise(False)
            b.setToolTip(hexcolour)
            b.setStyleSheet("QToolButton{background:%s; border:1px solid #777;} QToolButton:hover{border:1px solid #fff;}" % hexcolour)
            b.setProperty("swatch_rgb", [col.redF(), col.greenF(), col.blueF()])
            b.clicked.connect(lambda checked=False, col=col: self.picked.emit(col))
            self.grid.addWidget(b, i // 8, i % 8)
            self.cells.append(b)
        self.del_button.setEnabled(self.combo.currentText() in _user())

    def _add(self):
        c = self.current()
        if c is not None and c.isValid():
            add_colour(self.combo.currentText(), c.name())
            self.fill()

    def _new(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "New Palette", "Palette name:")
        if ok and new_palette(name):
            self.reload(name.strip())

    def _delete(self):
        if delete_palette(self.combo.currentText()):
            self.reload()


def add_to_panel(panel):
    """The swatches go under the Appearances PM's colour picker."""
    picker = getattr(panel, "picker", None)
    host = picker.parentWidget() if picker is not None else None
    lay = host.layout() if host is not None else None
    if lay is None or host.findChild(QtWidgets.QGroupBox, "SWSwatches") is not None:
        return None
    box = SwatchBox(picker.currentColor, host)
    box.picked.connect(picker.setCurrentColor)
    i = lay.indexOf(picker)
    if i >= 0 and isinstance(lay, QtWidgets.QBoxLayout):
        lay.insertWidget(i + 1, box)
    else:
        lay.addWidget(box)
    panel.swatches = box
    return box


def _hook_panel():
    from . import appearance
    cls = appearance.AppearancePanel
    if getattr(cls, "_fw_swatches", False):
        return
    init0 = cls.__init__

    def init(self, *a, **k):
        init0(self, *a, **k)
        try:
            add_to_panel(self)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: swatches: %s\n" % error)
    cls.__init__ = init
    cls._fw_swatches = True


# ---- Change Transparency ---------------------------------------------------------------------

def _picked_components():
    from . import appearance
    out, other = [], False
    for entry in Gui.Selection.getSelectionEx("", 0):
        obj = entry.Object
        try:
            if appearance.is_component(obj):
                out.append(obj)
                continue
        except Exception as _fw_err:
            _fw_log("appearextras.py:229", _fw_err)
        other = True
    return out, other


class ChangeTransparencyCommand:
    def GetResources(self):
        return {"MenuText": "Change Transparency", "Pixmap": "Std_ToggleTransparency",
                "ToolTip": "Makes the picked items see-through, or solid again; a component's own, never its part's"}

    def IsActive(self):
        return bool(Gui.Selection.getSelection())

    def Activated(self):
        comps, other = _picked_components()
        if comps:
            from . import asmmenu
            doc = comps[0].Document
            doc.openTransaction("Change Transparency")
            try:
                for c in comps:
                    asmmenu.change_transparency(c)
            finally:
                doc.commitTransaction()
        if other or not comps:
            if comps:
                keep = Gui.Selection.getSelectionEx("", 0)
                Gui.Selection.clearSelection()
                for e in keep:
                    if e.Object not in comps:
                        for sub in (e.SubElementNames or ("",)):
                            Gui.Selection.addSelection(e.Object, sub)
            Gui.runCommand("Std_ToggleTransparency", 0)


def install():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, ChangeTransparencyCommand())
    try:
        _hook_panel()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: appearance extras: %s\n" % error)
