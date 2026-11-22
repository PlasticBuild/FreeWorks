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
import json
import math
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import asmcore as ac
from . import asmroute as ar

V = App.Vector
PACKING = 1.15          # bundle diameter: sqrt(sum d^2) x packing (round wires in a round bundle)
EXTRA = 50.0
# name: (gauge, OD mm, colour)
WIRES = {
    "24 AWG": ("24", 1.2, "Black"), "22 AWG": ("22", 1.4, "Black"), "20 AWG": ("20", 1.7, "Black"),
    "18 AWG": ("18", 2.1, "Black"), "16 AWG": ("16", 2.4, "Black"), "14 AWG": ("14", 2.9, "Black"),
    "12 AWG": ("12", 3.4, "Black"), "10 AWG": ("10", 4.2, "Black"),
}
COLOURS = ("Black", "Red", "Blue", "Green", "Yellow", "White", "Brown", "Orange", "Violet", "Grey")


def _user_file():
    d = os.path.join(App.getUserAppDataDir(), "FreeWorks", "Routing")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "wires.json")


def wire_library():
    """{spec: {"gauge", "od", "colour"}}: the built-in specs and the user's."""
    lib = {k: {"gauge": g, "od": od, "colour": c} for k, (g, od, c) in WIRES.items()}
    try:
        with open(_user_file()) as f:
            lib.update(json.load(f))
    except Exception as _fw_err:
        _fw_log("asmelec.py:66", _fw_err)
    return lib


def add_wire_spec(name, gauge, od, colour="Black"):
    try:
        with open(_user_file()) as f:
            user = json.load(f)
    except Exception:
        user = {}
    user[name] = {"gauge": str(gauge), "od": float(od), "colour": colour}
    with open(_user_file(), "w") as f:
        json.dump(user, f, indent=1)
    return user[name]


def bundle_diameter(wires):
    lib = wire_library()
    ds = [float(w.get("od") or lib.get(w.get("spec"), {}).get("od", 0.0)) for w in wires]
    ds = [d for d in ds if d > 0]
    if not ds:
        return 0.0
    if len(ds) == 1:
        return round(ds[0], 2)
    return round(math.sqrt(sum(d * d for d in ds)) * PACKING, 2)


def wire(wid, spec, frm="", frm_pin="", to="", to_pin="", colour=None):
    lib = wire_library().get(spec, {})
    return {"id": str(wid), "spec": spec, "od": float(lib.get("od", 0.0)), "colour": colour or lib.get("colour", ""),
            "from": frm, "from_pin": str(frm_pin), "to": to, "to_pin": str(to_pin)}


def set_wires(route, wires):
    route.Wires = json.dumps([dict(w) for w in wires])
    d = bundle_diameter(wires)
    if d > 0:
        route.OD = d
        route.BendRadius = max(float(route.BendRadius or 0), 2.0 * d)
    route.recompute()
    route.Document.recompute()
    return d


def route_length(route):
    wire_, _b = ar.centreline([V(p) for p in route.Points], float(route.BendRadius))
    return wire_.Length if wire_ is not None else 0.0


def harness_rows(asm):
    """[(cable, wire id, spec, colour, from, from pin, to, to pin, cut length)]."""
    rows = []
    for r in ar.routes(asm):
        if r.Kind != "Electrical":
            continue
        L = route_length(r)
        for w in ar.wires_of(r):
            rows.append((r.Label, w.get("id", ""), w.get("spec", ""), w.get("colour", ""), w.get("from", ""),
                         w.get("from_pin", ""), w.get("to", ""), w.get("to_pin", ""), round(L + 2 * EXTRA, 1)))
    return rows


def save_harness_report(asm, path):
    with open(path, "w", newline="") as f:
        out = csv.writer(f)
        out.writerow(("Cable", "Wire ID", "Spec", "Colour", "From", "From pin", "To", "To pin", "Cut length (mm)"))
        out.writerows(harness_rows(asm))
    return path


# ------------------------------------------------------------------ From-To
def _component(asm, name):
    for c in ac.components(asm):
        if name in (c.Name, c.Label):
            return c
    return None


def _electrical_port(asm, comp):
    for c, cp, p, d in ar.ports(asm):
        if c.Name == comp.Name and cp.RouteType == "Electrical":
            return ar.port_key(c, cp)
    return None


def read_from_to(path):
    rows = []
    with open(path, newline="") as f:
        for row in csv.reader(f):
            row = [x.strip() for x in row]
            if not row or not row[0] or row[0].lower() in ("wire id", "wire", "id"):
                continue
            row += [""] * (6 - len(row))
            rows.append(row[:6])
    return rows


def import_from_to(asm, path, stub=15.0):
    """Cable routes for the From-To list; returns (routes, problems)."""
    groups, problems = {}, []
    for wid, spec, frm, fpin, to, tpin in read_from_to(path):
        a, b = _component(asm, frm), _component(asm, to)
        if a is None or b is None:
            problems.append("%s: no component %s" % (wid, frm if a is None else to))
            continue
        ka, kb = _electrical_port(asm, a), _electrical_port(asm, b)
        if ka is None or kb is None:
            problems.append("%s: %s has no electrical connection point" % (wid, (a if ka is None else b).Label))
            continue
        groups.setdefault(tuple(sorted((ka, kb))), []).append(wire(wid, spec, a.Label, fpin, b.Label, tpin))
    made = []
    doc = asm.Document
    doc.openTransaction("Import From-To")
    try:
        for (ka, kb), wires in groups.items():
            existing = next((r for r in ar.routes(asm) if r.Kind == "Electrical" and
                             sorted((r.StartPort, r.EndPort)) == [ka, kb]), None)
            if existing is not None:
                have = {w.get("id") for w in ar.wires_of(existing)}
                set_wires(existing, ar.wires_of(existing) + [w for w in wires if w["id"] not in have])
                made.append(existing)
                continue
            d = bundle_diameter(wires)
            r = ar.make_route(asm, "Electrical", ka, kb, d, 0.0, 2.0 * d, stub)
            set_wires(r, wires)
            made.append(r)
    finally:
        doc.commitTransaction()
    return made, problems


# ------------------------------------------------------------------ Flatten Route
def flatten(route):
    """The route laid out flat along X: one line per run, its length dimensioned (driving length
    = the run's length along the centre line, bends included in the run after them)."""
    asm = route.Document.getObject(route.AssemblyName)
    pts = [V(p) for p in route.Points]
    wire_, _b = ar.centreline(pts, float(route.BendRadius))
    if wire_ is None:
        return None
    runs = []
    cur = 0.0
    for e in wire_.Edges:
        cur += e.Length
        if type(e.Curve).__name__ in ("Line", "LineSegment"):
            runs.append(cur)
            cur = 0.0
    if cur > 1e-6:
        runs.append(cur)
    doc = route.Document
    sk = doc.addObject("Sketcher::SketchObject", "FlatRoute")
    sk.Label = "Flattened %s" % route.Label
    sk.addProperty("App::PropertyString", "FwFlattenOf", "FreeCAD", "The route this is the flat layout of")
    sk.FwFlattenOf = route.Name
    if asm is not None:
        asm.addObject(sk)
    import Sketcher
    x = 0.0
    tick = max(3.0, float(route.OD) * 1.5)
    prev = None
    for i, L in enumerate(runs):
        g = sk.addGeometry(Part.LineSegment(V(x, 0, 0), V(x + L, 0, 0)))
        if prev is None:
            sk.addConstraint(Sketcher.Constraint("Coincident", g, 1, -1, 1))
        else:
            sk.addConstraint(Sketcher.Constraint("Coincident", prev, 2, g, 1))
        sk.addConstraint(Sketcher.Constraint("Horizontal", g))
        sk.addConstraint(Sketcher.Constraint("DistanceX", g, 1, g, 2, round(L, 3)))
        prev = g
        x += L
        if i < len(runs) - 1:                   # the bend / clip mark
            sk.addGeometry(Part.LineSegment(V(x, -tick / 2, 0), V(x, tick / 2, 0)), True)
    sk.recompute()
    doc.recompute()
    return sk


# ------------------------------------------------------------------ Edit Wires
class EditWiresDialog(QtWidgets.QDialog):
    """Edit Wires: the cable's wires; Add from the library, Delete, the From / To ends."""

    def __init__(self, wires, asm=None):
        super().__init__(Gui.getMainWindow())
        self.setObjectName("SWEditWires")
        self.setWindowTitle("Edit Wires")
        self.asm = asm
        lay = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(0, 6, self)
        self.table.setObjectName("SWEditWiresTable")
        self.table.setHorizontalHeaderLabels(["Wire ID", "Spec", "From", "From pin", "To", "To pin"])
        lay.addWidget(self.table, 1)
        row = QtWidgets.QHBoxLayout()
        self.spec = QtWidgets.QComboBox(self)
        self.spec.setObjectName("SWEditWiresSpec")
        self.spec.addItems(sorted(wire_library(), key=lambda k: (len(k), k)))
        self.add_btn = QtWidgets.QPushButton("Add", self)
        self.add_btn.setObjectName("SWEditWiresAdd")
        self.del_btn = QtWidgets.QPushButton("Delete", self)
        self.del_btn.setObjectName("SWEditWiresDelete")
        row.addWidget(QtWidgets.QLabel("Wire:"))
        row.addWidget(self.spec, 1)
        row.addWidget(self.add_btn)
        row.addWidget(self.del_btn)
        lay.addLayout(row)
        self.diameter = QtWidgets.QLabel("", self)
        self.diameter.setObjectName("SWEditWiresDiameter")
        lay.addWidget(self.diameter)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.add_btn.clicked.connect(lambda: self.add())
        self.del_btn.clicked.connect(self.delete)
        self.table.itemChanged.connect(lambda *a: self._diameter())
        for w in wires:
            self._row(w)
        self._diameter()

    def _row(self, w):
        r = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(r)
        for c, k in enumerate(("id", "spec", "from", "from_pin", "to", "to_pin")):
            it = QtWidgets.QTableWidgetItem(str(w.get(k, "")))
            if k == "spec":
                it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
                it.setData(QtCore.Qt.UserRole, dict(w))
            self.table.setItem(r, c, it)
        self.table.blockSignals(False)

    def add(self, spec=None):
        spec = spec or self.spec.currentText()
        ids = {self.table.item(r, 0).text() for r in range(self.table.rowCount())}
        n = 1
        while "W%d" % n in ids:
            n += 1
        self._row(wire("W%d" % n, spec))
        self._diameter()

    def delete(self):
        rows = sorted({i.row() for i in self.table.selectedItems()}, reverse=True)
        if not rows and self.table.rowCount():
            rows = [self.table.rowCount() - 1]
        for r in rows:
            self.table.removeRow(r)
        self._diameter()

    def result_wires(self):
        out = []
        for r in range(self.table.rowCount()):
            base = dict(self.table.item(r, 1).data(QtCore.Qt.UserRole) or {})
            for c, k in enumerate(("id", "spec", "from", "from_pin", "to", "to_pin")):
                base[k] = self.table.item(r, c).text()
            out.append(base)
        return out

    def _diameter(self):
        self.diameter.setText("Calculated diameter: %.2fmm" % bundle_diameter(self.result_wires()))


class WireLibraryDialog(QtWidgets.QDialog):
    """Cable/Wire Library Wizard: the wire specs; Add a spec of your own."""

    def __init__(self):
        super().__init__(Gui.getMainWindow())
        self.setObjectName("SWWireLibrary")
        self.setWindowTitle("Cable/Wire Library Wizard")
        lay = QtWidgets.QVBoxLayout(self)
        self.list = QtWidgets.QTreeWidget(self)
        self.list.setObjectName("SWWireLibraryList")
        self.list.setHeaderLabels(["Name", "Gauge", "Outside diameter", "Colour"])
        self.list.setRootIsDecorated(False)
        lay.addWidget(self.list, 1)
        form = QtWidgets.QFormLayout()
        self.name = QtWidgets.QLineEdit(self)
        self.gauge = QtWidgets.QLineEdit(self)
        self.od = QtWidgets.QDoubleSpinBox(self)
        self.od.setRange(0.1, 100.0)
        self.od.setSuffix("mm")
        self.od.setValue(2.0)
        self.colour = QtWidgets.QComboBox(self)
        self.colour.addItems(list(COLOURS))
        form.addRow("Name:", self.name)
        form.addRow("Gauge:", self.gauge)
        form.addRow("Outside diameter:", self.od)
        form.addRow("Colour:", self.colour)
        lay.addLayout(form)
        row = QtWidgets.QHBoxLayout()
        self.add_btn = QtWidgets.QPushButton("Add", self)
        self.add_btn.setObjectName("SWWireLibraryAdd")
        close = QtWidgets.QPushButton("Close", self)
        row.addWidget(self.add_btn)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self.add_btn.clicked.connect(self.add)
        close.clicked.connect(self.accept)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for k, v in sorted(wire_library().items(), key=lambda kv: (len(kv[0]), kv[0])):
            self.list.addTopLevelItem(QtWidgets.QTreeWidgetItem([k, str(v["gauge"]), "%.2fmm" % v["od"], v["colour"]]))

    def add(self):
        name = self.name.text().strip()
        if not name:
            return None
        spec = add_wire_spec(name, self.gauge.text().strip(), self.od.value(), self.colour.currentText())
        self.refresh()
        return spec


OPEN = []


# ------------------------------------------------------------------ commands
def edit_wires(asm):
    rs = [r for r in ar.routes(asm) if r.Kind == "Electrical"]
    sel = [s.Object for s in Gui.Selection.getSelectionEx()]
    r = next((x for x in rs if x in sel), rs[-1] if rs else None)
    if r is None:
        return None
    dlg = EditWiresDialog(ar.wires_of(r), asm)
    OPEN.append(dlg)
    dlg.finished.connect(lambda code: (code and _apply(r, dlg), OPEN.remove(dlg) if dlg in OPEN else None))
    dlg.show()
    return dlg


def _apply(route, dlg):
    doc = route.Document
    doc.openTransaction("Edit Wires")
    try:
        set_wires(route, dlg.result_wires())
    finally:
        doc.commitTransaction()


def wire_library_wizard():
    dlg = WireLibraryDialog()
    OPEN.append(dlg)
    dlg.finished.connect(lambda *a: OPEN.remove(dlg) if dlg in OPEN else None)
    dlg.show()
    return dlg


def import_from_to_ask(asm):
    path, _f = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Import From-To List", "",
                                                     "From-To list (*.csv)")
    if not path:
        return None
    made, problems = import_from_to(asm, path)
    if problems:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Import From-To List", "\n".join(problems))
    return made


def flatten_picked(asm):
    rs = [r for r in ar.routes(asm) if r.Kind == "Electrical"]
    sel = [s.Object for s in Gui.Selection.getSelectionEx()]
    r = next((x for x in rs if x in sel), rs[-1] if rs else None)
    if r is None:
        return None
    doc = asm.Document
    doc.openTransaction("Flatten Route")
    try:
        return flatten(r)
    finally:
        doc.commitTransaction()


def harness_report_ask(asm):
    base = asm.Document.FileName
    default = os.path.splitext(base)[0] + "-wires.csv" if base else "wires.csv"
    path, _f = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Wire List", default, "CSV (*.csv)")
    if not path:
        return None
    return save_harness_report(asm, path)
