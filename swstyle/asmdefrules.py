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

import fnmatch
import json

import FreeCAD as App

from . import asmcore as ac

PARAM = "User parameter:BaseApp/Preferences/Mod/SWStyle/Defeature"
KINDS = (
    ("Remove internal components", None),
    ("Remove components by name", "name"),
    ("Remove components smaller than", "size"),
    ("Remove holes up to", "size"),
    ("Remove fillets and chamfers up to", "size"),
    ("Replace with bounding box", "name"),
    ("Replace with cylinder", "name"),

    ("Remove components by custom property", "prop"),
    ("Remove components lighter than", "mass"),
)
VALUE_KIND = dict(KINDS)
DEFAULTS = {"name": "*", "size": 10.0, "prop": "Description=*", "mass": 10.0}


def rule(kind, value=None, on=True):
    if kind not in VALUE_KIND:
        raise ValueError("no such rule: %s" % kind)
    vk = VALUE_KIND[kind]
    if vk is not None and value is None:
        value = DEFAULTS[vk]
    if vk in ("size", "mass"):
        value = float(value)
    return {"kind": kind, "value": value, "on": bool(on)}


def text(r):
    vk = VALUE_KIND.get(r["kind"])
    if vk == "size":
        return "%s %g mm" % (r["kind"], r["value"])
    if vk == "mass":
        return "%s %g g" % (r["kind"], r["value"])
    if vk in ("name", "prop"):
        return "%s: %s" % (r["kind"], r["value"])
    return r["kind"]


def saved():
    """The rules as last kept (the Rules Editor's OK)."""
    try:
        data = json.loads(App.ParamGet(PARAM).GetString("Rules", "") or "[]")
        return [rule(d["kind"], d.get("value"), d.get("on", True)) for d in data if d.get("kind") in VALUE_KIND]
    except Exception:
        return []


def keep(rules):
    App.ParamGet(PARAM).SetString("Rules", json.dumps(rules))


def save_file(rules, path):
    with open(path, "w") as f:
        json.dump({"FreeWorks defeature rules": 1, "rules": rules}, f, indent=1)


def load_file(path):
    with open(path) as f:
        data = json.load(f)
    rows = data.get("rules", data) if isinstance(data, dict) else data
    return [rule(d["kind"], d.get("value"), d.get("on", True)) for d in rows if d.get("kind") in VALUE_KIND]


def _match(comp, pattern):
    pattern = (pattern or "*").strip() or "*"
    names = (comp.Label, ac.part_name(comp) if hasattr(ac, "part_name") else comp.Label)
    return any(fnmatch.fnmatch(n.lower(), pattern.lower()) for n in names)


def custom_property(comp, name):
    """A component's custom property (its part's, in the configuration it uses), as text."""
    try:
        from . import fileprops, asmcfginst
        target = comp.getLinkedObject(True)
        config = None
        try:
            config = asmcfginst.configuration(comp)
        except Exception as _fw_err:
            _fw_log("asmdefrules.py:114", _fw_err)
        v = fileprops.value(target.Document, name, config)
        return None if v is None else str(v)
    except Exception:
        return None


def prop_match(comp, spec):
    """spec "Name=pattern" (wildcards): the component's custom property Name matches."""
    name, _eq, pattern = (spec or "").partition("=")
    name, pattern = name.strip(), (pattern.strip() or "*")
    if not name:
        return False
    v = custom_property(comp, name)
    return v is not None and fnmatch.fnmatch(v.lower(), pattern.lower())


def mass_g(comp):
    try:
        from . import asmphysics
        vol_mm3 = sum(x.Volume for x in (comp.Shape.Solids or [comp.Shape]))
        _m, _c, _i, density = asmphysics.mass_props(comp)       # kg/mm^3
        return vol_mm3 * density * 1000.0
    except Exception:
        return None


def apply(asm, comps, rules):
    """Runs the rules in order. Returns ({component name: (shape or None, what)}, log lines)."""
    from . import asmtools, asmmenubar, asmdefeature as df
    state = {}
    for c in comps:
        try:
            sh = asmtools._global_shape(c)
        except Exception:
            sh = None
        if sh is not None and not sh.isNull():
            state[c.Name] = [sh, "kept"]
    by_name = {c.Name: c for c in comps}
    log = []
    inside = None
    for i, r in enumerate(rules, 1):
        if not r.get("on", True):
            log.append("%d. %s: off" % (i, text(r)))
            continue
        kind, value = r["kind"], r.get("value")
        hit = 0
        live = [n for n in state if state[n][0] is not None]
        if kind == "Remove internal components":
            if inside is None:
                inside = {c.Name for c in asmmenubar.internal(asm)}
            for n in live:
                if n in inside:
                    state[n] = [None, "removed (internal)"]
                    hit += 1
            log.append("%d. %s: %d component(s) removed" % (i, text(r), hit))
        elif kind == "Remove components by name":
            for n in live:
                if _match(by_name[n], value):
                    state[n] = [None, "removed (name)"]
                    hit += 1
            log.append("%d. %s: %d component(s) removed" % (i, text(r), hit))
        elif kind == "Remove components smaller than":
            for n in live:
                if state[n][0].BoundBox.DiagonalLength < value:
                    state[n] = [None, "removed (small)"]
                    hit += 1
            log.append("%d. %s: %d component(s) removed" % (i, text(r), hit))
        elif kind in ("Remove holes up to", "Remove fillets and chamfers up to"):
            holes = kind == "Remove holes up to"
            faces = 0
            for n in live:
                out, k = df.remove_details(state[n][0], holes=holes, hole_max=value, fillets=not holes,
                                           fillet_max=value)
                if k:
                    state[n][0] = out
                    state[n][1] = (state[n][1] if state[n][1] != "kept" else "simplified")
                    faces += k
                    hit += 1
            log.append("%d. %s: %d face(s) in %d component(s)" % (i, text(r), faces, hit))
        elif kind == "Remove components by custom property":
            for n in live:
                if prop_match(by_name[n], value):
                    state[n] = [None, "removed (property)"]
                    hit += 1
            log.append("%d. %s: %d component(s) removed" % (i, text(r), hit))
        elif kind == "Remove components lighter than":
            for n in live:
                m = mass_g(by_name[n])
                if m is not None and m < value:
                    state[n] = [None, "removed (mass)"]
                    hit += 1
            log.append("%d. %s: %d component(s) removed" % (i, text(r), hit))
        elif kind in ("Replace with bounding box", "Replace with cylinder"):
            shape_kind = "Bounding box" if kind == "Replace with bounding box" else "Cylinder"
            for n in live:
                if _match(by_name[n], value):
                    state[n] = [df.silhouette(state[n][0], shape_kind), "replaced (%s)" % shape_kind.lower()]
                    hit += 1
            log.append("%d. %s: %d component(s) replaced" % (i, text(r), hit))
    return {n: tuple(v) for n, v in state.items()}, log


def make_part(asm, comps, result, name=None, propagate=True):
    """The defeatured part: one body per component left, where the assembly shows it."""
    doc = App.newDocument(name or (asm.Document.Label + "_Defeature"))
    for c in comps:
        got = result.get(c.Name)
        if got is None or got[0] is None:
            continue
        body = doc.addObject("Part::Feature", "Body")
        body.Shape = got[0]
        body.Label = c.Label
        if propagate:
            propagate_visuals(c, body)
    doc.recompute()
    return doc


def visuals(comp):
    """(appearance, transparency, face colours) a component shows: its own override in the
    assembly, else its part's."""
    vo = getattr(comp, "ViewObject", None)
    try:
        if vo is not None and getattr(vo, "OverrideMaterial", False) and hasattr(vo, "ShapeMaterial"):
            return [vo.ShapeMaterial], getattr(vo, "Transparency", 0), None
    except Exception as _fw_err:
        _fw_log("asmdefrules.py:241", _fw_err)
    try:
        target = comp.getLinkedObject(True)
        tvo = target.ViewObject
        return list(getattr(tvo, "ShapeAppearance", []) or []), getattr(tvo, "Transparency", 0), None
    except Exception as _fw_err:
        _fw_log("asmdefrules.py:248", _fw_err)
        return None, 0, None


def propagate_visuals(comp, body):
    ""
    if body.ViewObject is None:
        return
    app, transp, _faces = visuals(comp)
    try:
        if app:
            body.ViewObject.ShapeAppearance = app if len(app) in (1, len(body.Shape.Faces)) else app[:1]
        body.ViewObject.Transparency = int(transp or 0)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: visual properties: %s\n" % error)


# ---------------------------------------------------------------- the Rules Editor
def _qt():
    from PySide import QtWidgets
    return QtWidgets


class RulesEditor:
    """The Rules Editor dialog: rules in order, each on or off; Add, Update, Delete, Move Up/Down,
    Save and Load. OK keeps the rules for Apply Rules."""

    def __init__(self, rules=None, parent=None):
        QtWidgets = _qt()
        self.rules = [dict(r) for r in (saved() if rules is None else rules)]
        d = self.dialog = QtWidgets.QDialog(parent)
        d.setObjectName("FW_DefeatureRulesEditor")
        d.setWindowTitle("Rules Editor")
        lay = QtWidgets.QVBoxLayout(d)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_DefeatureRuleList")
        self.list.currentRowChanged.connect(self._pick)
        self.list.itemChanged.connect(self._checked)
        lay.addWidget(self.list)
        form = QtWidgets.QFormLayout()
        self.kind = QtWidgets.QComboBox()
        self.kind.setObjectName("FW_DefeatureRuleKind")
        self.kind.addItems([k for k, _v in KINDS])
        self.kind.currentIndexChanged.connect(self._kind)
        form.addRow("Rule:", self.kind)
        self.size = QtWidgets.QDoubleSpinBox()
        self.size.setObjectName("FW_DefeatureRuleSize")
        self.size.setRange(0.01, 1e6)
        self.size.setDecimals(2)
        self.size.setSuffix(" mm")
        self.size.setValue(DEFAULTS["size"])
        form.addRow("Size:", self.size)
        self.name = QtWidgets.QLineEdit("*")
        self.name.setObjectName("FW_DefeatureRuleName")
        self.name.setToolTip("Component names; * and ? as wildcards (bolt*, *washer*)")
        form.addRow("Components:", self.name)
        lay.addLayout(form)
        row = QtWidgets.QHBoxLayout()
        self.buttons = {}
        for label, fn in (("Add", self.add), ("Update", self.update), ("Delete", self.delete),
                          ("Move Up", lambda: self.move(-1)), ("Move Down", lambda: self.move(1))):
            b = QtWidgets.QPushButton(label)
            b.setObjectName("FW_DefeatureRule" + label.replace(" ", ""))
            b.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(b)
            self.buttons[label] = b
        lay.addLayout(row)
        row2 = QtWidgets.QHBoxLayout()
        for label, fn in (("Save...", self.save), ("Load...", self.load)):
            b = QtWidgets.QPushButton(label)
            b.setObjectName("FW_DefeatureRule" + label.strip("."))
            b.clicked.connect(lambda _c=False, f=fn: f())
            row2.addWidget(b)
            self.buttons[label] = b
        row2.addStretch(1)
        lay.addLayout(row2)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.ok)
        box.rejected.connect(d.reject)
        lay.addWidget(box)
        self._kind()
        self._show()

    def _value(self):
        vk = VALUE_KIND[self.kind.currentText()]
        if vk in ("size", "mass"):
            return self.size.value()
        if vk == "prop":
            return self.name.text().strip() or DEFAULTS["prop"]
        return (self.name.text().strip() or "*") if vk == "name" else None

    def _kind(self, *_a):
        vk = VALUE_KIND[self.kind.currentText()]
        self.size.setEnabled(vk in ("size", "mass"))
        self.size.setSuffix(" g" if vk == "mass" else " mm")
        self.name.setEnabled(vk in ("name", "prop"))
        self.name.setPlaceholderText("Property=value (wildcards: Vendor=Acme*)" if vk == "prop" else "")

    def _show(self, row=None):
        QtWidgets = _qt()
        from PySide import QtCore
        self.list.blockSignals(True)
        self.list.clear()
        for r in self.rules:
            it = QtWidgets.QListWidgetItem(text(r))
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if r.get("on", True) else QtCore.Qt.Unchecked)
            self.list.addItem(it)
        self.list.blockSignals(False)
        if row is not None and 0 <= row < len(self.rules):
            self.list.setCurrentRow(row)

    def _pick(self, row):
        if not 0 <= row < len(self.rules):
            return
        r = self.rules[row]
        self.kind.setCurrentText(r["kind"])
        vk = VALUE_KIND[r["kind"]]
        if vk in ("size", "mass"):
            self.size.setValue(r["value"])
        elif vk in ("name", "prop"):
            self.name.setText(r["value"])

    def _checked(self, item):
        from PySide import QtCore
        row = self.list.row(item)
        if 0 <= row < len(self.rules):
            self.rules[row]["on"] = item.checkState() == QtCore.Qt.Checked

    def add(self, kind=None, value=None):
        if kind is not None:
            self.kind.setCurrentText(kind)
            if value is not None:
                (self.size.setValue(value) if VALUE_KIND[kind] in ("size", "mass") else self.name.setText(str(value)))
        self.rules.append(rule(self.kind.currentText(), self._value()))
        self._show(len(self.rules) - 1)

    def update(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.rules):
            on = self.rules[row].get("on", True)
            self.rules[row] = rule(self.kind.currentText(), self._value(), on)
            self._show(row)

    def delete(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.rules):
            del self.rules[row]
            self._show(min(row, len(self.rules) - 1))

    def move(self, step):
        row = self.list.currentRow()
        new = row + step
        if 0 <= row < len(self.rules) and 0 <= new < len(self.rules):
            self.rules[row], self.rules[new] = self.rules[new], self.rules[row]
            self._show(new)

    def save(self, path=None):
        if path is None:
            QtWidgets = _qt()
            path = QtWidgets.QFileDialog.getSaveFileName(self.dialog, "Save Rules", "", "Defeature rules (*.json)")[0]
        if path:
            save_file(self.rules, path)
        return path

    def load(self, path=None):
        if path is None:
            QtWidgets = _qt()
            path = QtWidgets.QFileDialog.getOpenFileName(self.dialog, "Load Rules", "", "Defeature rules (*.json)")[0]
        if path:
            self.rules = load_file(path)
            self._show(0)
        return path

    def ok(self):
        keep(self.rules)
        self.dialog.accept()

    def exec_(self):
        return self.dialog.exec_()
