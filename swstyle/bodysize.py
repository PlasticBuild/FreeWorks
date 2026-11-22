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

import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import multibody

CMD = "SWStyle_SelectBodiesBySize"
OPEN = []


def bodies(doc):
    """[(row, solid)] of every body in the Solid Bodies folder of doc."""
    out = []
    for row in multibody.rows(doc):
        try:
            solid = multibody._row_solid(row)
        except Exception:
            solid = None
        if solid is not None and not solid.isNull():
            out.append((row, solid))
    return out


def small(solids, percent):
    """Indices of the solids whose bounding-box diagonal is at most percent of the whole set's."""
    whole = None
    for solid in solids:
        if whole is None:
            whole = App.BoundBox(solid.BoundBox)
        else:
            whole.add(solid.BoundBox)
    if whole is None or whole.DiagonalLength <= 0:
        return []
    limit = whole.DiagonalLength * percent / 100.0
    return [i for i, solid in enumerate(solids) if solid.BoundBox.DiagonalLength <= limit + 1e-9]


def by_size(doc, percent, items=None):
    """The rows whose bounding-box diagonal is at most percent of the whole part's."""
    items = bodies(doc) if items is None else items
    return [items[i][0] for i in small([s for _r, s in items], percent)]


def body_panel():
    """The open Delete/Keep (or other body feature) PropertyManager, if one is open."""
    panel = multibody.ACTIVE_PANEL[0] if multibody.ACTIVE_PANEL else None
    try:
        if panel is not None and Gui.Control.activeDialog() and panel.obj() is not None:
            return panel
    except Exception as _fw_err:
        _fw_log("bodysize.py:77", _fw_err)
    return None


def fill_panel(panel, percent):
    """In an open body PM the bodies go straight into its Bodies box (picking them in the view
    would toggle them off and on as the slider moves)."""
    pieces = panel._pieces()
    found = small(pieces, percent)
    panel._set("Bodies", [multibody.ref_text(i, pieces[i]) for i in found])
    return found, pieces


def parent_feature(row):
    """The feature that made the body: the one its Solid Bodies name comes from."""
    doc = row.Document
    body = doc.getObject(row.Body)
    if body is None:
        return None
    base = re.sub(r"\[\d+\]$", "", (row.SolidName or "").replace("​", ""))
    found = None
    for f in multibody._chain(body):
        if multibody._source_label(f) == base:
            found = f
    if found is not None and getattr(getattr(found, "Proxy", None), "Type", None) == multibody.NOMERGE_TYPE:
        found = getattr(found, "Source", None) or found
    return found


def picks(doc, percent, parents, items=None):
    rows = by_size(doc, percent, items)
    out = list(rows)
    if parents:
        for row in rows:
            f = parent_feature(row)
            if f is not None and f not in out:
                out.append(f)
    return rows, out


def _select(doc, objs):
    Gui.Selection.clearSelection()
    for o in objs:
        try:
            Gui.Selection.addSelection(doc.Name, o.Name)
        except Exception as _fw_err:
            _fw_log("bodysize.py:123", _fw_err)


class SelectBodiesBySizeBox(QtWidgets.QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc
        self.panel = body_panel()
        self.items = bodies(doc) if self.panel is None else []
        self.kept = list(self.panel.obj().Bodies) if self.panel is not None else None
        self.setObjectName("SWSelectBodiesBySize")
        self.setWindowTitle("Select Bodies by Size")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Select bodies smaller than (% of the part size):"))
        row = QtWidgets.QHBoxLayout()
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setObjectName("SWSelectBodiesBySizeSlider")
        self.slider.setRange(0, 100)
        self.spin = QtWidgets.QSpinBox()
        self.spin.setObjectName("SWSelectBodiesBySizePercent")
        self.spin.setRange(0, 100)
        self.spin.setSuffix("%")
        row.addWidget(self.slider)
        row.addWidget(self.spin)
        lay.addLayout(row)
        self.dynamic = QtWidgets.QCheckBox("Dynamic selection")
        self.dynamic.setObjectName("SWSelectBodiesBySizeDynamic")
        self.dynamic.setToolTip("Picks the bodies as the slider moves")
        self.dynamic.setChecked(True)
        lay.addWidget(self.dynamic)
        self.parents = QtWidgets.QCheckBox("Select Parent Feature")
        self.parents.setObjectName("SWSelectBodiesBySizeParent")
        self.parents.setToolTip("Also picks the feature that made each body")
        self.parents.setChecked(True)
        lay.addWidget(self.parents)
        self.count = QtWidgets.QLabel()
        self.count.setObjectName("SWSelectBodiesBySizeCount")
        lay.addWidget(self.count)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)
        self.spin.valueChanged.connect(self.update_pick)
        self.dynamic.toggled.connect(self.update_pick)
        self.parents.toggled.connect(self.update_pick)
        self.before = [(s.Object, s.SubElementNames) for s in Gui.Selection.getSelectionEx(doc.Name)]
        self.spin.setValue(10)
        self.update_pick()

    def update_pick(self, *_a):
        if self.panel is not None:
            self.parents.setVisible(False)       # the PM takes bodies, not features (no greyed box)
            if self.dynamic.isChecked():
                found, pieces = fill_panel(self.panel, self.spin.value())
            else:
                pieces = self.panel._pieces()
                found = small(pieces, self.spin.value())
            self.count.setText("%d of %d bodies selected" % (len(found), len(pieces)))
            return found
        rows, objs = picks(self.doc, self.spin.value(), self.parents.isChecked(), self.items)
        self.count.setText("%d of %d bodies selected" % (len(rows), len(self.items)))
        if self.dynamic.isChecked():
            _select(self.doc, objs)
        return objs

    def accept(self):
        if self.panel is not None:
            fill_panel(self.panel, self.spin.value())
            OPEN[:] = []
            return super().accept()
        _select(self.doc, picks(self.doc, self.spin.value(), self.parents.isChecked(), self.items)[1])
        OPEN[:] = []
        super().accept()

    def reject(self):
        if self.panel is not None:
            try:
                self.panel._set("Bodies", self.kept)
            except Exception as _fw_err:
                _fw_log("bodysize.py:204", _fw_err)
            OPEN[:] = []
            return super().reject()
        Gui.Selection.clearSelection()
        for obj, subs in self.before:
            try:
                if subs:
                    for s in subs:
                        Gui.Selection.addSelection(self.doc.Name, obj.Name, s)
                else:
                    Gui.Selection.addSelection(self.doc.Name, obj.Name)
            except Exception as _fw_err:
                _fw_log("bodysize.py:216", _fw_err)
        OPEN[:] = []
        super().reject()


def open_box(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    box = SelectBodiesBySizeBox(doc)
    OPEN[:] = [box]
    box.open()
    return box


class _Command:
    def GetResources(self):
        return {"MenuText": "Select Bodies by Size...",
                "ToolTip": "Picks the bodies of a multibody part that are no bigger than a percent of the part",
                "Pixmap": "edit-select-all"}

    def IsActive(self):
        doc = App.ActiveDocument
        if doc is None:
            return False
        if body_panel() is not None:
            return True
        if Gui.Control.activeDialog():
            return False
        return len(multibody.rows(doc)) > 1

    def Activated(self):
        open_box()


def register():
    if CMD not in Gui.listCommands():
        Gui.addCommand(CMD, _Command())
