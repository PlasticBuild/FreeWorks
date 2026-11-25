# SPDX-License-Identifier: LGPL-2.1-or-later
""






import json

import FreeCAD as App

NONE = "<None>"
ROOT = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Favorites/"
FILTER = "FreeCAD favorites (*.fwfav)"


def _group(kind):
    return App.ParamGet(ROOT + kind)


def names(kind):
    return sorted(_group(kind).GetStrings())


def get(kind, name):
    text = _group(kind).GetString(name, "")
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def put(kind, name, values):
    _group(kind).SetString(name, json.dumps(values, sort_keys=True))


def remove(kind, name):
    _group(kind).RemString(name)


def save(kind, path):
    """Writes all the favorites of kind to path."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"kind": kind, "favorites": {n: get(kind, n) for n in names(kind)}}, f, indent=1,
                  sort_keys=True)


def load(kind, path):
    """Reads favorites from path (a file Save Favorites wrote); returns their names."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or data.get("kind") != kind:
        raise ValueError("This file has no %s favorites." % kind)
    out = []
    for name, values in (data.get("favorites") or {}).items():
        if isinstance(values, dict):
            put(kind, name, values)
            out.append(name)
    return out


class FavoriteRows:
    """The Favorite box: values() gives the PM's values as a dict, apply(dict) puts them back."""

    def __init__(self, layout, kind, prefix, values, apply):
        from PySide import QtWidgets
        self.kind, self.values, self.apply = kind, values, apply
        self.combo = QtWidgets.QComboBox()
        self.combo.setObjectName(prefix + "Favorite")
        self.combo.setToolTip("Favorites")
        row = QtWidgets.QHBoxLayout()
        self.buttons = {}
        for key, icon, tip, slot in (("Add", "list-add", "Add or Update Favorite", self.add),
                                     ("Delete", "list-remove", "Delete Favorite", self.delete),
                                     ("Save", "document-save", "Save Favorites", self.save),
                                     ("Load", "document-open", "Load Favorites", self.load)):
            b = QtWidgets.QToolButton()
            b.setObjectName("%sFavorite%s" % (prefix, key))
            b.setToolTip(tip)
            b.setIcon(_icon(icon))
            if b.icon().isNull():
                b.setText(key)
            b.clicked.connect(slot)
            row.addWidget(b)
            self.buttons[key] = b
        row.addStretch(1)
        layout.addRow(row)
        layout.addRow(self.combo)
        self.refill(NONE)
        self.combo.currentIndexChanged.connect(self._picked)

    def refill(self, current=None):
        current = current or self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(NONE)
        self.combo.addItems(names(self.kind))
        i = self.combo.findText(current)
        self.combo.setCurrentIndex(max(i, 0))
        self.combo.blockSignals(False)
        self.buttons["Delete"].setEnabled(self.combo.currentIndex() > 0)

    def _picked(self, *_a):
        name = self.combo.currentText()
        self.buttons["Delete"].setEnabled(self.combo.currentIndex() > 0)
        values = get(self.kind, name) if self.combo.currentIndex() > 0 else None
        if values:
            self.apply(values)

    def add(self, name=None):
        if not name:
            from PySide import QtWidgets
            import FreeCADGui as Gui
            current = self.combo.currentText() if self.combo.currentIndex() > 0 else ""
            name, ok = QtWidgets.QInputDialog.getText(Gui.getMainWindow(), "Add or Update Favorite",
                                                      "Enter a name for the favorite:", text=current)
            if not ok:
                return None
        name = (name or "").strip()
        if not name or name == NONE:
            return None
        put(self.kind, name, self.values())
        self.refill(name)
        return name

    def delete(self):
        if self.combo.currentIndex() > 0:
            remove(self.kind, self.combo.currentText())
            self.refill(NONE)

    def save(self, path=None):
        if not path:
            from PySide import QtWidgets
            import FreeCADGui as Gui
            path, _f = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save Favorites",
                                                             self.kind + ".fwfav", FILTER)
        if path:
            save(self.kind, path)
        return path

    def load(self, path=None):
        if not path:
            from PySide import QtWidgets
            import FreeCADGui as Gui
            path, _f = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Load Favorites", "", FILTER)
        if not path:
            return []
        try:
            got = load(self.kind, path)
        except (OSError, ValueError) as e:
            from PySide import QtWidgets
            import FreeCADGui as Gui
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Load Favorites", str(e))
            return []
        self.refill(got[0] if got else None)
        self._picked()
        return got


def _icon(name):
    """FreeCAD's own icon (in its resources), else the desktop theme's."""
    from PySide import QtCore, QtGui
    path = ":/icons/%s.svg" % name
    return QtGui.QIcon(path) if QtCore.QFile.exists(path) else QtGui.QIcon.fromTheme(name)
