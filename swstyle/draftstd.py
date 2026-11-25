# -*- coding: utf-8 -*-
""



import json

import FreeCAD as App
from PySide import QtWidgets

FILTER = "FreeCAD drafting standards (*.fwstd)"

PAGES = ("Drafting Standard", "Annotations", "Balloons", "Datums", "Geometric Tolerances", "Notes",
         "Revision Clouds", "Surface Finishes", "Weld Symbols", "Dimensions", "Angle", "Angular Running",
         "Arc Length", "Chamfer", "Diameter", "Hole Callout", "Linear", "Ordinate", "Radius", "Virtual Sharps",
         "Tables", "Bend", "Bill of Materials", "General", "Hole", "Title Block Table", "DimXpert",
         "Size Dimension", "Location Dimension", "Chain Dimension", "Geometric Tolerance", "Chamfer Controls",
         "Display Options")


def _rows(dialog):
    """The dialog's Drafting Standard rows: (setting, key) for the kept ones, and the standard itself."""
    from . import optionspages as OP
    out = []
    for s in getattr(dialog, "settings", []):
        page = getattr(s, "page", None)
        if page in PAGES and hasattr(s, "value"):
            out.append((s, OP._store_key(page, s.text)))
        elif getattr(s, "key", None) == "DraftingStandard":
            out.append((s, "DraftingStandard"))
    return out


def values(dialog):
    out = {}
    dialog.build_all()
    for s, key in _rows(dialog):
        try:
            v = s.value()
        except Exception:
            continue
        out[key] = v if isinstance(v, (bool, int, float, str)) else str(v)
    return out


def save(dialog, path=None):
    if path is None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(dialog, "Save to External File", "standard.fwstd", FILTER)
        if not path:
            return None
    if not path.lower().endswith(".fwstd"):
        path += ".fwstd"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"FreeWorksDraftingStandard": 1, "values": values(dialog)}, f, indent=1, sort_keys=True)
    return path


def _put(s, v):
    """A value into the row's own box (the page keeps it once OK is pressed)."""
    box = getattr(s, "box", None)
    if box is None:
        return False
    if isinstance(box, QtWidgets.QAbstractButton):
        box.setChecked(bool(v))
    elif isinstance(box, QtWidgets.QComboBox):
        choices = getattr(s, "choices", None)
        if choices:
            values_ = [c[1] if isinstance(c, (tuple, list)) else c for c in choices]
            if v in values_:
                box.setCurrentIndex(values_.index(v))
                return True
        i = box.findText(str(v))
        if i < 0:
            return False
        box.setCurrentIndex(i)
    elif isinstance(box, QtWidgets.QAbstractSpinBox):
        box.setValue(float(v)) if isinstance(box, QtWidgets.QDoubleSpinBox) else box.setValue(int(float(v)))
    elif isinstance(box, QtWidgets.QLineEdit):
        box.setText(str(v))
    else:
        return False
    return True


def load(dialog, path=None):
    if path is None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(dialog, "Load From External File", "", FILTER)
        if not path:
            return 0
    with open(path, encoding="utf-8") as f:
        data = json.load(f).get("values", {})
    done = 0
    dialog.build_all()
    for s, key in _rows(dialog):
        if key in data and _put(s, data[key]):
            done += 1
    App.Console.PrintLog("FreeCAD: drafting standard: %d rows from %s\n" % (done, path))
    return done


def buttons():
    """The two buttons, as Options rows (run(dialog))."""
    from .optionspages import Button
    return [Button("Load From External File...", load, "Loads a drafting standard saved to a .fwstd file"),
            Button("Save to External File...", save, "Saves this drafting standard to a .fwstd file")]
