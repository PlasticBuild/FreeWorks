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
import Part
from PySide import QtCore, QtWidgets

from . import asmcore as ac
from . import weweld

V = App.Vector
TYPES = weweld.TYPES
DEFAULTS = {"mode": "Weld Geometry", "from": [], "to": [], "edges": [], "tangent": True, "type": "Full length",
            "length": 10.0, "pitch": 20.0, "size": 3.0, "other": False, "other_size": 3.0, "symbol": {}}


def new_path(size=3.0):
    p = json.loads(json.dumps(DEFAULTS))
    p["size"] = p["other_size"] = float(size)
    return p


def paths_of(feat):
    """The feature's weld paths (weweld's path dicts, items as 'component|x,y,z')."""
    try:
        s = json.loads(getattr(feat, "WeldSettings", "") or "{}")
    except ValueError:
        s = {}
    paths = s.get("paths")
    if not paths:
        p = new_path(float(getattr(feat.Radius, "Value", feat.Radius)))
        p["from"], p["to"] = list(feat.WeldFrom), list(feat.WeldTo)
        paths = [p]
    out = []
    for p in paths:
        q = new_path()
        q.update(p)
        out.append(q)
    return out


# ---------------------------------------------------------------------- geometry
def _comp(asm, name):
    return next((c for c in ac.components(asm) if c.Name == name), None)


def _item(item):
    name, _bar, xyz = item.partition("|")
    try:
        return name, V(*(float(v) for v in xyz.split(",")))
    except ValueError:
        return name, None


def on_face(face):
    """A point on the face (its centre of mass may be off a curved face)."""
    try:
        u0, u1, v0, v1 = face.ParameterRange
        p = face.valueAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))
        if face.isInside(p, 1e-6, True):
            return p
    except Exception as _fw_err:
        _fw_log("asmweld.py:89", _fw_err)
    return face.Vertexes[0].Point if face.Vertexes else face.CenterOfMass


def _shape(comp):
    from . import asmfeature as af
    return af.global_shape(comp)


def faces(asm, items, tangent):
    """[(component shape, face)] for face items, with the tangent faces when tangent is on."""
    out = []
    for item in items or []:
        name, p = _item(item)
        comp = _comp(asm, name)
        if comp is None or p is None:
            continue
        shape = _shape(comp)
        v = Part.Vertex(comp.Placement.multVec(p))
        face = min(shape.Faces, key=lambda f: f.distToShape(v)[0], default=None)
        if face is None or face.distToShape(v)[0] > 1e-5:
            continue
        for f in (weweld._tangent_chain(shape, face) if tangent else [face]):
            if not any(f.isSame(g) for _s, g in out):
                out.append((shape, f))
    return out


def edges(asm, items):
    """[(component, component shape, edge)] for edge items."""
    out = []
    for item in items or []:
        name, p = _item(item)
        comp = _comp(asm, name)
        if comp is None or p is None:
            continue
        shape = _shape(comp)
        v = Part.Vertex(comp.Placement.multVec(p))
        e = min(shape.Edges, key=lambda x: x.distToShape(v)[0], default=None)
        if e is not None and e.distToShape(v)[0] < 1e-5:
            out.append((comp, shape, e))
    return out


def _path_welds(asm, path):
    """([(edge, from face, to face)], from shapes, to faces) of one path."""
    tangent = path.get("tangent", True)
    if path.get("mode") == "Weld Path":
        out, tos, shapes = [], [], []
        for comp, shape, edge in edges(asm, path.get("edges")):
            shapes.append(shape)
            others = [_shape(c) for c in ac.components(asm) if c is not comp and not ac.is_subassembly(c)]
            for e in (weweld._edge_chain(shape, edge) if tangent else [edge]):
                if any(weweld._same(e, x[0]) for x in out):
                    continue
                mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
                g = next((f for o in others for f in o.Faces if weweld._on(e, f)), None)
                if g is None:
                    continue
                ng = weweld._normal(g, mid)
                f = next((h for h in shape.ancestorsOfType(e, Part.Face)
                          if abs(weweld._normal(h, mid).dot(ng)) < 1 - 1e-6), None)
                if f is not None:
                    out.append((e, f, g))
                    tos.append(g)
        return out, shapes, tos
    froms = faces(asm, path.get("from"), tangent)
    tos = [f for _s, f in faces(asm, path.get("to"), tangent)]
    shapes = []
    for s, _f in froms:
        if not any(s.isSame(x) for x in shapes):
            shapes.append(s)
    return weweld.weld_edges([f for _s, f in froms], tos), shapes, tos


def beads(asm, path):
    """The bead solids of one path (fillet welds), and the welded length."""
    welds, shapes, tos = _path_welds(asm, path)
    kind, length, pitch = path.get("type"), float(path.get("length", 0)), float(path.get("pitch", 0))
    if kind == "Staggered" and not path.get("other"):
        kind = "Intermittent"
    sides = [(welds, float(path.get("size", 3.0)), 0.0)]
    if path.get("other"):
        sides.append((weweld._other_side(welds, shapes, tos), float(path.get("other_size", path.get("size", 3.0))),
                      pitch / 2 if kind == "Staggered" else 0.0))
    out, total = [], 0.0
    for welded, size, start in sides:
        for edge, f, g, *back in welded:
            for piece in weweld._pieces(edge, kind, length, pitch, start, bool(back and back[0])):
                b = weweld.bead(piece, f, g, size)
                if b is not None and not b.isNull():
                    out.append(b)
                    total += piece.Length
    return out, total


def all_beads(feat, asm):
    out, total = [], 0.0
    for p in paths_of(feat):
        b, n = beads(asm, p)
        out += b
        total += n
    return out, total


def update_weld(feat, asm, structure=False):
    """asmfeature.update_weld: the bead body from all the weld paths."""
    from . import asmfeature as af
    bead = getattr(feat, "Bead", None)
    if bead is None:
        if not structure:
            return
        bead = af._bead_for(feat)
    try:
        solids, _n = all_beads(feat, asm)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: weld bead %s: %s\n" % (feat.Label, error))
        solids = []
    bead.Shape = Part.makeCompound(solids) if solids else Part.Shape()
    try:
        bead.purgeTouched()
    except Exception as _fw_err:
        _fw_log("asmweld.py:211", _fw_err)


def symbol_text(feat):
    return " | ".join(t for t in (weweld.symbol_text(p) for p in paths_of(feat)) if t)


# ---------------------------------------------------------------------- PropertyManager
def _spin(name, value, lo=0.0):
    b = QtWidgets.QDoubleSpinBox()
    b.setObjectName(name)
    b.setRange(lo, 1.0e6)
    b.setDecimals(2)
    b.setSuffix("mm")
    b.setValue(float(value))
    return b


class WeldPanel:
    ""

    def __init__(self, asm, feat=None):
        from . import asmfeature as af
        from . import asmpm
        af._FeaturePanel._start(self, asm, "Weld", feat)
        self.paths = paths_of(feat) if feat is not None else [new_path()]
        self.current = 0
        self.active = "from"
        self.smart_cbs = None
        self.stroke = None
        self._busy = False
        box, lay = asmpm._box("Weld Path", "Weld Bead", "WELDMENTS_WELD_BEAD")
        self.path_list = QtWidgets.QListWidget()
        self.path_list.setObjectName("FW_AsmWeldPaths")
        self.path_list.setFixedHeight(asmpm._rows(self.path_list, 2))
        lay.addWidget(self.path_list)
        row = QtWidgets.QHBoxLayout()
        self.new_button = QtWidgets.QPushButton("New Weld Path")
        self.new_button.setObjectName("FW_AsmWeldNewPath")
        row.addWidget(self.new_button)
        lay.addLayout(row)
        self.smart = QtWidgets.QPushButton("Smart Weld Selection Tool")
        self.smart.setObjectName("FW_AsmWeldSmart")
        self.smart.setCheckable(True)
        self.smart.setToolTip("Drag across the faces to weld: the first component's faces go in Weld From, "
                              "the others' in Weld To")
        lay.addWidget(self.smart)
        sbox, slay = asmpm._box("Settings")
        mode = QtWidgets.QHBoxLayout()
        self.geometry = QtWidgets.QRadioButton("Weld Geometry")
        self.geometry.setObjectName("FW_AsmWeldGeometry")
        self.by_path = QtWidgets.QRadioButton("Weld Path")
        self.by_path.setObjectName("FW_AsmWeldByPath")
        mode.addWidget(self.geometry)
        mode.addWidget(self.by_path)
        slay.addLayout(mode)
        self.from_label = QtWidgets.QLabel("Weld From:")
        slay.addWidget(self.from_label)
        self.from_list = self._list("FW_AsmWeldFrom")
        slay.addWidget(self.from_list)
        self.to_label = QtWidgets.QLabel("Weld To:")
        slay.addWidget(self.to_label)
        self.to_list = self._list("FW_AsmWeldTo")
        slay.addWidget(self.to_list)
        self.edge_label = QtWidgets.QLabel("Edges:")
        slay.addWidget(self.edge_label)
        self.edge_list = self._list("FW_AsmWeldEdges")
        slay.addWidget(self.edge_list)
        self.tangent = QtWidgets.QCheckBox("Tangent propagation")
        self.tangent.setObjectName("FW_AsmWeldTangent")
        slay.addWidget(self.tangent)
        form = QtWidgets.QFormLayout()
        self.size = _spin("FW_AsmWeldSize", 3.0, 0.001)
        form.addRow("Bead size:", self.size)
        self.kinds = QtWidgets.QComboBox()
        self.kinds.setObjectName("FW_AsmWeldType")
        self.kinds.addItems(list(TYPES))
        form.addRow(self.kinds)
        self.weld_length = _spin("FW_AsmWeldLength10", 10.0, 0.001)
        form.addRow("Weld length:", self.weld_length)
        self.pitch = _spin("FW_AsmWeldPitch", 20.0, 0.001)
        form.addRow("Pitch:", self.pitch)
        slay.addLayout(form)
        self.symbol = QtWidgets.QPushButton("Define Weld Symbol...")
        self.symbol.setObjectName("FW_AsmWeldSymbol")
        slay.addWidget(self.symbol)
        self.other = QtWidgets.QCheckBox("Other Side")
        self.other.setObjectName("FW_AsmWeldOther")
        slay.addWidget(self.other)
        oform = QtWidgets.QFormLayout()
        self.other_size = _spin("FW_AsmWeldOtherSize", 3.0, 0.001)
        oform.addRow("Bead size:", self.other_size)
        slay.addLayout(oform)
        self.length = QtWidgets.QLabel("")
        self.length.setObjectName("FW_AsmWeldLength")
        slay.addWidget(self.length)
        af._FeaturePanel._error_label(self, slay)
        self.form = [box, sbox]
        for w, sig in ((self.geometry, "toggled"), (self.tangent, "toggled"), (self.other, "toggled"),
                       (self.kinds, "currentIndexChanged"), (self.size, "valueChanged"),
                       (self.weld_length, "valueChanged"), (self.pitch, "valueChanged"),
                       (self.other_size, "valueChanged")):
            getattr(w, sig).connect(self._changed)
        self.new_button.clicked.connect(self.add_path)
        self.path_list.currentRowChanged.connect(self._select_path)
        self.symbol.clicked.connect(self.define_symbol)
        self.smart.toggled.connect(self._smart)
        if feat is not None:
            self.active = "to"
        self._load()
        Gui.Selection.addObserver(self, 0)

    # ---------------------------------------------------------------- lists
    def _list(self, name):
        from . import asmpm
        lst = QtWidgets.QListWidget()
        lst.setObjectName(name)
        lst.setFixedHeight(asmpm._rows(lst, 2))
        panel = self

        class F(QtCore.QObject):
            def eventFilter(self, w, e):
                if not isinstance(e, QtCore.QEvent):
                    return False
                if e.type() == QtCore.QEvent.MouseButtonPress:
                    panel.active = {id(panel.from_list): "from", id(panel.to_list): "to"}.get(id(w), "edges")
                    panel._focus()
                return False
        lst._fw_filter = F(lst)
        lst.installEventFilter(lst._fw_filter)
        return lst

    def _focus(self):
        from . import asmpm
        for key, lst in (("from", self.from_list), ("to", self.to_list), ("edges", self.edge_list)):
            lst.setStyleSheet(asmpm.PICK_STYLE if self.active == key else "")

    def path(self):
        return self.paths[self.current]

    def _label(self, item):
        name, _p = _item(item)
        comp = _comp(self.asm, name)
        return comp.Label if comp is not None else name

    def _load(self):
        """The widgets show the current path."""
        self._busy = True
        p = self.path()
        self.path_list.clear()
        for i in range(len(self.paths)):
            self.path_list.addItem("Weld Path%d" % (i + 1))
        self.path_list.setCurrentRow(self.current)
        (self.by_path if p["mode"] == "Weld Path" else self.geometry).setChecked(True)
        self.tangent.setChecked(bool(p["tangent"]))
        self.size.setValue(float(p["size"]))
        self.kinds.setCurrentText(p["type"])
        self.weld_length.setValue(float(p["length"]))
        self.pitch.setValue(float(p["pitch"]))
        self.other.setChecked(bool(p["other"]))
        self.other_size.setValue(float(p["other_size"]))
        self._busy = False
        self._show()

    def _show(self):
        p = self.path()
        path_mode = p["mode"] == "Weld Path"
        if path_mode and self.active != "edges":
            self.active = "edges"
        elif not path_mode and self.active == "edges":
            self.active = "from"
        for lst, key in ((self.from_list, "from"), (self.to_list, "to"), (self.edge_list, "edges")):
            lst.clear()
            for item in p[key]:
                lst.addItem(("Edge@%s" if key == "edges" else "Face@%s") % self._label(item))
        for w in (self.from_label, self.from_list, self.to_label, self.to_list):
            w.setVisible(not path_mode)
        for w in (self.edge_label, self.edge_list):
            w.setVisible(path_mode)
        inter = p["type"] in ("Intermittent", "Staggered")
        from .asmfeature import _row_visible       # only what applies shows (no greyed boxes)
        _row_visible(self.weld_length, inter)
        _row_visible(self.pitch, inter)
        self.kinds.model().item(TYPES.index("Staggered")).setEnabled(bool(p["other"]))
        _row_visible(self.other_size, bool(p["other"]))
        self._focus()
        self._show_length()

    def _changed(self, *args):
        if self._busy:
            return
        p = self.path()
        p["mode"] = "Weld Path" if self.by_path.isChecked() else "Weld Geometry"
        p["tangent"] = self.tangent.isChecked()
        p["size"] = self.size.value()
        p["other"] = self.other.isChecked()
        if not p["other"] and self.kinds.currentText() == "Staggered":
            self._busy = True
            self.kinds.setCurrentText("Intermittent")       # staggered needs both sides
            self._busy = False
        p["type"] = self.kinds.currentText()
        p["length"] = self.weld_length.value()
        p["pitch"] = self.pitch.value()
        p["other_size"] = self.other_size.value()
        self._show()

    def _show_length(self):
        total = 0.0
        try:
            for p in self.paths:
                total += beads(self.asm, p)[1]
        except Exception:
            total = 0.0
        self.length.setText("Weld length: %.2fmm" % total if total else "")

    def add_path(self):
        self.paths.append(new_path(self.size.value()))
        self.current = len(self.paths) - 1
        self.active = "from"
        self._load()

    def _select_path(self, row):
        if self._busy or row < 0 or row >= len(self.paths):
            return
        self.current = row
        self._load()

    def define_symbol(self):
        p = self.path()
        dlg = weweld.WeldSymbolDialog(weweld.symbol_of(p), Gui.getMainWindow())
        if dlg.exec_():
            p["symbol"] = dlg.value()

    # ---------------------------------------------------------------- picks
    def addSelection(self, doc, obj, sub, pnt):
        point = V(*pnt) if pnt else None
        QtCore.QTimer.singleShot(0, lambda: self._pick_named(obj, sub, point))

    def _pick_named(self, obj, sub, point):
        try:
            target = self.doc.getObject(obj)
        except ReferenceError:          # the document closed before the pick was handled
            return
        self._pick(target, sub, point)

    def removeSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass

    def setPreselection(self, *args):
        pass

    def _ref(self, root, sub):
        ref = ac.reference(self.asm, root, sub)
        shape = ac.element(*ref) if ref else None
        return (ref, shape) if shape is not None else (None, None)

    def _pick(self, root, sub, point):
        if root is None or not sub:
            return
        ref, shape = self._ref(root, sub)
        if ref is None:
            return
        p = self.path()
        comp = ref[0]
        if p["mode"] == "Weld Path":
            if shape.ShapeType != "Edge":
                return
            at = shape.valueAt((shape.FirstParameter + shape.LastParameter) / 2)
            key = "edges"
        else:
            if shape.ShapeType != "Face":
                return
            at = point if point is not None and shape.distToShape(Part.Vertex(point))[0] < 1e-4 else on_face(shape)
            key = self.active if self.active in ("from", "to") else "from"
        q = comp.Placement.inverse().multVec(at)
        item = "%s|%.9g,%.9g,%.9g" % (comp.Name, q.x, q.y, q.z)
        if item in p[key]:
            p[key].remove(item)                     # a second pick takes it out
        else:
            p[key].append(item)
        if key == "from" and not p["to"]:
            self.active = "to"
        self.error.hide()
        self._show()
        Gui.Selection.clearSelection()

    # ---------------------------------------------------------------- Smart Weld Selection Tool
    def _smart(self, on):
        if on:
            self._start_smart()
        else:
            self._stop_smart()

    def _start_smart(self):
        try:
            from pivy import coin
            view = Gui.ActiveDocument.ActiveView
        except Exception:
            return
        if self.path()["mode"] == "Weld Path":
            self.geometry.setChecked(True)          # the tool picks faces

        def button(cb):
            ev = cb.getEvent()
            if ev.getButton() != coin.SoMouseButtonEvent.BUTTON1:
                return
            pos = tuple(ev.getPosition().getValue())
            if ev.getState() == coin.SoButtonEvent.DOWN:
                self.stroke = [pos]
                cb.setHandled()
            elif self.stroke is not None:
                points, self.stroke = self.stroke + [pos], None
                cb.setHandled()
                QtCore.QTimer.singleShot(0, lambda: self.smart_stroke(points))

        def motion(cb):
            if self.stroke is not None:
                self.stroke.append(tuple(cb.getEvent().getPosition().getValue()))
                cb.setHandled()

        self.smart_cbs = (view, view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), button),
                          view.addEventCallbackPivy(coin.SoLocation2Event.getClassTypeId(), motion))

    def _stop_smart(self):
        if self.smart_cbs is None:
            return
        try:
            from pivy import coin
            view = self.smart_cbs[0]
            view.removeEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self.smart_cbs[1])
            view.removeEventCallbackPivy(coin.SoLocation2Event.getClassTypeId(), self.smart_cbs[2])
        except Exception as _fw_err:
            _fw_log("asmweld.py:545", _fw_err)
        self.smart_cbs = None
        self.stroke = None

    def smart_stroke(self, points):
        """The faces a stroke (3D-view pixels) crosses: the first component's go in Weld From, the
        other components' in Weld To."""
        try:
            view = Gui.ActiveDocument.ActiveView
        except Exception:
            return
        samples = []
        for (x0, y0), (x1, y1) in zip(points, points[1:] or points):
            n = max(1, int(max(abs(x1 - x0), abs(y1 - y0)) / 3))
            samples += [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(n + 1)]
        hits = []
        for x, y in samples:
            try:
                info = view.getObjectInfo((int(round(x)), int(round(y))))
            except Exception:
                info = None
            if not info:
                continue
            parent = info.get("ParentObject")
            if parent is not None and info.get("SubName"):
                root, sub = parent, info["SubName"]
            else:
                root, sub = self.doc.getObject(info.get("Object", "")), info.get("Component", "")
            if root is None or not str(sub).split(".")[-1].startswith("Face"):
                continue
            ref, shape = self._ref(root, sub)
            if ref is None or shape.ShapeType != "Face":
                continue
            pt = V(info["x"], info["y"], info["z"]) if "x" in info else shape.CenterOfMass
            hits.append((ref[0], shape, pt))
        comps = list(dict.fromkeys(c.Name for c, _s, _p in hits))
        if len(comps) < 2:
            self.error.setText("Drag across the faces of two components.")
            self.error.show()
            return
        p = self.path()
        p["mode"] = "Weld Geometry"
        seen = []
        for comp, shape, pt in hits:
            if any(shape.isSame(s) for s in seen):
                continue
            seen.append(shape)
            q = comp.Placement.inverse().multVec(pt if shape.distToShape(Part.Vertex(pt))[0] < 1e-4 else on_face(shape))
            item = "%s|%.9g,%.9g,%.9g" % (comp.Name, q.x, q.y, q.z)
            key = "from" if comp.Name == comps[0] else "to"
            if item not in p["from"] and item not in p["to"]:
                p[key].append(item)
        self._load()

    # ---------------------------------------------------------------- OK / Cancel
    def _ready(self, p):
        return bool(p["edges"]) if p["mode"] == "Weld Path" else bool(p["from"] and p["to"])

    def _fail(self, text):
        self.error.setText(text)
        self.error.show()
        return False

    def _close(self):
        self._stop_smart()
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmweld.py:613", _fw_err)

    def accept(self):
        from . import asmfeature as af
        paths = [p for p in self.paths if self._ready(p)]
        if not paths:
            return self._fail("Pick the Weld From and the Weld To faces (or the edges for a Weld Path).")
        first = next((p for p in paths if p["mode"] != "Weld Path"), {"from": [], "to": []})
        values = {"WeldFrom": list(first["from"]), "WeldTo": list(first["to"]), "Radius": paths[0]["size"],
                  "WeldSettings": json.dumps({"paths": paths})}
        return af._FeaturePanel._commit(self, values)

    def reject(self):
        from . import asmfeature as af
        return af._FeaturePanel.reject(self)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


def install():
    from . import asmfeature as af
    if getattr(af, "_fw_weld", False):
        return
    names = [e[1] for e in af.EXTRA]
    if "WeldSettings" not in names:
        af.EXTRA = tuple(af.EXTRA) + (("App::PropertyString", "WeldSettings", "Weld Bead",
                                       "Weld paths and their settings (json)"),)
    af.update_weld = update_weld
    af.WeldPanel = WeldPanel
    af._fw_weld = True
