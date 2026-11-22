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
import math
import os
import re

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

KINDS = ("Numeric", "Text", "Drop-down list", "Check box")
STEPS = ("Model Selection", "Capture Dimensions", "Capture Features", "Capture Custom Properties",
         "Form Design", "Rules", "Run")
SIZE_PROPS = ("Length", "Length2", "Width", "Height", "Radius", "Radius1", "Radius2", "Angle", "Offset",
              "Depth", "Diameter", "Occurrences", "Size", "Size2", "Thickness", "Value")
FEATURE_TYPES = ("PartDesign::", "Part::Fillet", "Part::Chamfer", "Part::Extrusion", "Part::Revolution",
                 "Part::Cut", "Part::Fuse", "Part::Box", "Part::Cylinder")


# ---------------------------------------------------------------- the project
def project_path(model_path):
    return os.path.splitext(model_path)[0] + ".dwxpress.json"


def new_project(doc):
    folder = os.path.dirname(doc.FileName)
    return {"model": doc.FileName, "output": os.path.join(folder, "Design Automation"),
            "dimensions": [], "features": [], "properties": [], "form": [], "rules": {},
            "file_names": {}, "created": []}


def load(doc):
    path = project_path(doc.FileName)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            base = new_project(doc)
            base.update(data)
            return base
        except Exception as error:
            App.Console.PrintWarning("Design Automation: %s not read: %s\n" % (path, error))
    return new_project(doc)


def save(project):
    path = project_path(project["model"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(project, f, indent=1)
    return path


def model_docs(doc):
    """The model and, for an assembly, each part document it uses (deepest first, model last)."""
    out = []

    def walk(d):
        if d in out:
            return
        for o in d.Objects:
            t = getattr(o, "LinkedObject", None)
            if o.TypeId == "App::Link" and t is not None and t.Document is not d:
                walk(t.Document)
        out.append(d)
    walk(doc)
    return out


def _doc_by_file(project, base):
    for d in App.listDocuments().values():
        if d.FileName and os.path.basename(d.FileName) == base:
            return d
    folder = os.path.dirname(project["model"])
    path = os.path.join(folder, base)
    if os.path.exists(path):
        return App.openDocument(path)
    return None


def key(item):
    return "%s|%s|%s" % (item["doc"], item["obj"], item.get("prop", ""))


# ---------------------------------------------------------------- capture
def dimension_candidates(doc):
    """[(item, current value)] of the dimensions DriveWorksXpress can drive in doc's models."""
    out = []
    for d in model_docs(doc):
        base = os.path.basename(d.FileName or d.Label)
        for o in d.Objects:
            if o.TypeId == "Sketcher::SketchObject":
                for i, c in enumerate(o.Constraints):
                    if c.Type in ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle") and c.Driving:
                        name = c.Name or "D%d" % (i + 1)
                        value = c.Value if c.Type != "Angle" else math.degrees(c.Value)
                        out.append(({"doc": base, "obj": o.Name, "prop": "Constraint:%d" % i,
                                     "name": "%s@%s@%s" % (name, o.Label, os.path.splitext(base)[0]),
                                     "unit": "deg" if c.Type == "Angle" else "mm"}, value))
                continue
            if not any(o.TypeId.startswith(t) for t in FEATURE_TYPES):
                continue
            for p in SIZE_PROPS:
                if p not in o.PropertiesList:
                    continue
                v = getattr(o, p)
                try:
                    value = float(v.Value if hasattr(v, "Value") else v)
                except Exception:
                    continue
                if isinstance(getattr(o, p), bool):
                    continue
                out.append(({"doc": base, "obj": o.Name, "prop": p,
                             "name": "%s@%s@%s" % (p, o.Label, os.path.splitext(base)[0])}, value))
    return out


def feature_candidates(doc):
    out = []
    for d in model_docs(doc):
        base = os.path.basename(d.FileName or d.Label)
        for o in d.Objects:
            if o.TypeId.startswith("PartDesign::") and o.TypeId not in ("PartDesign::Body",) \
                    and "Suppressed" in o.PropertiesList:
                out.append({"doc": base, "obj": o.Name, "prop": "Suppressed",
                            "name": "%s@%s" % (o.Label, os.path.splitext(base)[0])})
    return out


def property_candidates(doc):
    from . import customprops
    out = []
    for d in model_docs(doc):
        base = os.path.basename(d.FileName or d.Label)
        for name, _kind, _value in customprops.read(d):
            out.append({"doc": base, "obj": "", "prop": "CustomProperty:" + name,
                        "name": "%s@%s" % (name, os.path.splitext(base)[0])})
    return out


# ---------------------------------------------------------------- rules
_FUNCS = {
    "IF": lambda c, a, b=0: a if c else b, "AND": lambda *a: all(a), "OR": lambda *a: any(a),
    "NOT": lambda a: not a, "ROUND": lambda a, n=0: round(a, int(n)), "ROUNDUP": lambda a, n=0: math.ceil(a * 10 ** n) / 10 ** n,
    "ROUNDDOWN": lambda a, n=0: math.floor(a * 10 ** n) / 10 ** n, "INT": lambda a: int(a), "ABS": abs,
    "MIN": min, "MAX": max, "SQRT": math.sqrt, "PI": lambda: math.pi, "SIN": lambda a: math.sin(math.radians(a)),
    "COS": lambda a: math.cos(math.radians(a)), "TAN": lambda a: math.tan(math.radians(a)),
    "TRUE": True, "FALSE": False, "LEN": len, "UPPER": lambda s: str(s).upper(), "LOWER": lambda s: str(s).lower(),
    "TEXT": lambda a, *f: ("%g" % a) if isinstance(a, (int, float)) else str(a),
    "CONCATENATE": lambda *a: "".join(str(x) for x in a),
}


def _split_top(expr, sep):
    """expr split at sep outside quotes and brackets."""
    parts, depth, quote, cur = [], 0, False, ""
    for ch in expr:
        if ch == '"':
            quote = not quote
        elif not quote and ch == "(":
            depth += 1
        elif not quote and ch == ")":
            depth -= 1
        if ch == sep and not quote and depth == 0:
            parts.append(cur)
            cur = ""
            continue
        cur += ch
    parts.append(cur)
    return parts


def _python(expr):
    """Excel-style comparisons in Python: = to ==, <> to !=, outside quotes."""
    out, quote, i = "", False, 0
    while i < len(expr):
        ch = expr[i]
        if ch == '"':
            quote = not quote
        if not quote:
            two = expr[i:i + 2]
            if two in ("<>",):
                out += "!="
                i += 2
                continue
            if two in ("<=", ">=", "=="):
                out += two
                i += 2
                continue
            if ch == "=":
                out += "=="
                i += 1
                continue
            if ch == "^":
                out += "**"
                i += 1
                continue
        out += ch
        i += 1
    return out


def evaluate(rule, values):
    """The value of a rule (a formula string) for the form's values {name: value}."""
    text = str(rule).strip()
    if text.startswith("="):
        text = text[1:]
    if not text:
        raise ValueError("empty rule")
    names = dict(_FUNCS)
    names.update({re.sub(r"\W", "_", k): v for k, v in values.items()})
    pieces = _split_top(text, "&")
    results = []
    for piece in pieces:
        p = piece.strip()
        for k in values:
            safe = re.sub(r"\W", "_", k)
            if safe != k:
                p = p.replace(k, safe)
        results.append(eval(_python(p), {"__builtins__": {}}, names))
    if len(results) == 1:
        return results[0]
    return "".join(("%g" % r) if isinstance(r, float) else str(r) for r in results)


def defaults(project):
    out = {}
    for c in project["form"]:
        out[c["name"]] = control_value(c, c.get("default"))
    return out


def control_value(c, raw):
    kind = c.get("kind", "Numeric")
    if kind == "Numeric":
        try:
            return float(raw)
        except Exception:
            return 0.0
    if kind == "Check box":
        return raw in (True, "True", "true", "1", 1, "Yes")
    return "" if raw is None else str(raw)


def check_rules(project, values=None):
    """{key: error text or ""} for each rule with the form's default values."""
    values = defaults(project) if values is None else values
    out = {}
    for item in captured(project):
        rule = project["rules"].get(key(item), "")
        if not rule:
            out[key(item)] = "No rule"
            continue
        try:
            evaluate(rule, values)
            out[key(item)] = ""
        except Exception as error:
            out[key(item)] = str(error)
    return out


def captured(project):
    return list(project["dimensions"]) + list(project["features"]) + list(project["properties"])


# ---------------------------------------------------------------- applying and creating
def _read(d, item):
    prop = item["prop"]
    if prop.startswith("CustomProperty:"):
        from . import customprops
        name = prop.split(":", 1)[1]
        return next((v for n, _k, v in customprops.read(d) if n == name), "")
    o = d.getObject(item["obj"])
    if prop.startswith("Constraint:"):
        return o.Constraints[int(prop.split(":")[1])].Value
    v = getattr(o, prop)
    return v.Value if hasattr(v, "Value") else v


def _write(d, item, value, raw=False):
    prop = item["prop"]
    if prop.startswith("CustomProperty:"):
        from . import customprops
        name = prop.split(":", 1)[1]
        rows = customprops.read(d)
        hit = False
        out = []
        for n, k, v in rows:
            if n == name:
                v, hit = ("%g" % value) if isinstance(value, float) else str(value), True
            out.append((n, k, v))
        if not hit:
            out.append((name, "Text", str(value)))
        customprops.write(d, out)
        return
    o = d.getObject(item["obj"])
    if prop.startswith("Constraint:"):
        i = int(prop.split(":")[1])
        if raw:
            o.setDatum(i, value)
        elif item.get("unit") == "deg":
            o.setDatum(i, App.Units.Quantity("%r deg" % float(value)))
        else:
            o.setDatum(i, App.Units.Quantity("%r mm" % float(value)))
        return
    if prop == "Suppressed":
        setattr(o, prop, bool(value))
        return
    current = getattr(o, prop)
    setattr(o, prop, int(value) if isinstance(current, int) and not isinstance(current, bool) else float(value))


def file_name(project, base, values, counter):
    rule = project["file_names"].get(base, "")
    stem = os.path.splitext(base)[0]
    if rule:
        try:
            stem = str(evaluate(rule, values)).strip() or stem
        except Exception as error:
            App.Console.PrintWarning("Design Automation: file name rule for %s: %s\n" % (base, error))
            stem = "%s_%d" % (stem, counter)
    else:
        stem = "%s_%d" % (stem, counter)
    return re.sub(r'[\\/:*?"<>|]', "_", stem) + ".FCStd"


def create(project, values):
    """Run: the new models in the output folder. Returns {original base name: new path}."""
    from . import asmpackgo
    model = _doc_by_file(project, os.path.basename(project["model"]))
    if model is None:
        raise RuntimeError("the model %s is not found" % project["model"])
    folder = project["output"]
    os.makedirs(folder, exist_ok=True)
    counter = len(project.get("created", [])) + 1
    docs = model_docs(model)
    rules = project["rules"]
    items = [i for i in captured(project) if rules.get(key(i))]
    saved = []
    try:
        for item in items:         # the values first, so a rule error leaves the models as they were
            item["_value"] = evaluate(rules[key(item)], values)
        for d in docs:
            base = os.path.basename(d.FileName)
            for item in items:
                if item["doc"] == base:
                    raw = d.getObject(item["obj"]).Constraints[int(item["prop"].split(":")[1])].Value \
                        if item["prop"].startswith("Constraint:") else None
                    saved.append((d, item, raw if raw is not None else _read(d, item)))
                    _write(d, item, item["_value"])
            d.recompute()
        mapping = {"__src_dir__": os.path.dirname(model.FileName)}
        out = {}
        for d in docs:              # parts first, the assembly last
            base = os.path.basename(d.FileName)
            new = os.path.join(folder, file_name(project, base, values, counter))
            from . import asmcore as ac
            asm = ac.assembly_of(d)
            if asm is not None:
                try:
                    ac.solve(asm)
                    d.recompute()
                except Exception as _fw_err:
                    _fw_log("dwxpress.py:395", _fw_err)
            d.saveCopy(new)
            mapping[os.path.normpath(d.FileName)] = new
            out[base] = new
        for base, new in out.items():
            asmpackgo.relink(new, mapping)
    finally:
        for d, item, old in reversed(saved):          # the model as it was
            try:
                _write(d, item, old, raw=item["prop"].startswith("Constraint:"))
            except Exception as _fw_err:
                _fw_log("dwxpress.py:406", _fw_err)
        for d in docs:
            try:
                d.recompute()
                if Gui is not None:
                    Gui.getDocument(d.Name).Modified = False
            except Exception as _fw_err:
                _fw_log("dwxpress.py:413", _fw_err)
        for item in items:
            item.pop("_value", None)
    project.setdefault("created", []).append({"values": values, "files": list(out.values())})
    save(project)
    return out


# ---------------------------------------------------------------- the wizard
if Gui is not None:
    class DriveWorksXpressDialog(QtWidgets.QDialog):
        def __init__(self, doc, parent=None):
            super().__init__(parent or Gui.getMainWindow())
            self.doc = doc
            self.project = load(doc)
            self.setObjectName("FW_DriveWorksXpress")
            self.setWindowTitle("Design Automation")
            lay = QtWidgets.QHBoxLayout(self)
            self.steps = QtWidgets.QListWidget(self)
            self.steps.setObjectName("FW_DWXSteps")
            self.steps.addItems(list(STEPS))
            self.steps.setFixedWidth(190)
            lay.addWidget(self.steps)
            right = QtWidgets.QVBoxLayout()
            self.stack = QtWidgets.QStackedWidget(self)
            right.addWidget(self.stack, 1)
            row = QtWidgets.QHBoxLayout()
            self.back = QtWidgets.QPushButton("< Back")
            self.back.setObjectName("FW_DWXBack")
            self.next = QtWidgets.QPushButton("Next >")
            self.next.setObjectName("FW_DWXNext")
            close = QtWidgets.QPushButton("Close")
            close.setObjectName("FW_DWXClose")
            row.addStretch(1)
            for b in (self.back, self.next, close):
                row.addWidget(b)
            right.addLayout(row)
            lay.addLayout(right, 1)
            self.back.clicked.connect(lambda: self.go(self.stack.currentIndex() - 1))
            self.next.clicked.connect(lambda: self.go(self.stack.currentIndex() + 1))
            close.clicked.connect(self.close)
            self.steps.currentRowChanged.connect(self.go)
            self.pages = [self._model_page(), self._capture_page("dimensions"), self._capture_page("features"),
                          self._capture_page("properties"), self._form_page(), self._rules_page(), self._run_page()]
            for p in self.pages:
                self.stack.addWidget(p)
            self.resize(860, 520)
            self.go(0)

        # -- navigation
        def go(self, i):
            i = max(0, min(len(STEPS) - 1, i))
            self.store()
            self.stack.setCurrentIndex(i)
            if self.steps.currentRow() != i:
                self.steps.blockSignals(True)
                self.steps.setCurrentRow(i)
                self.steps.blockSignals(False)
            self.back.setEnabled(i > 0)
            self.next.setEnabled(i < len(STEPS) - 1)
            refresh = getattr(self.pages[i], "refresh", None)
            if refresh:
                refresh()

        def store(self):
            for p in getattr(self, "pages", []):
                take = getattr(p, "take", None)
                if take:
                    take()
            try:
                save(self.project)
            except Exception as error:
                App.Console.PrintWarning("Design Automation: %s\n" % error)

        def closeEvent(self, e):
            self.store()
            super().closeEvent(e)

        # -- Model Selection
        def _model_page(self):
            w = QtWidgets.QWidget()
            f = QtWidgets.QFormLayout(w)
            f.addRow(QtWidgets.QLabel("<b>Model Selection</b>"))
            self.model_label = QtWidgets.QLabel(self.project["model"])
            self.model_label.setObjectName("FW_DWXModel")
            f.addRow("Model:", self.model_label)
            kids = [os.path.basename(d.FileName) for d in model_docs(self.doc)[:-1]]
            f.addRow("Parts it uses:", QtWidgets.QLabel(", ".join(kids) or "none"))
            row = QtWidgets.QHBoxLayout()
            self.output = QtWidgets.QLineEdit(self.project["output"])
            self.output.setObjectName("FW_DWXOutput")
            browse = QtWidgets.QPushButton("Browse...")
            browse.clicked.connect(self._browse)
            row.addWidget(self.output, 1)
            row.addWidget(browse)
            f.addRow("Output folder:", row)

            def take():
                self.project["output"] = self.output.text().strip() or self.project["output"]
            w.take = take
            return w

        def _browse(self):
            d = QtWidgets.QFileDialog.getExistingDirectory(self, "Output folder", self.output.text())
            if d:
                self.output.setText(d)

        # -- Capture
        def _capture_page(self, what):
            w = QtWidgets.QWidget()
            lay = QtWidgets.QVBoxLayout(w)
            title = {"dimensions": "Capture Dimensions", "features": "Capture Features",
                     "properties": "Capture Custom Properties"}[what]
            lay.addWidget(QtWidgets.QLabel("<b>%s</b>" % title))
            lay.addWidget(QtWidgets.QLabel("Check the items the rules drive. Double-click a name to rename it."))
            table = QtWidgets.QTableWidget(0, 3 if what == "dimensions" else 2)
            table.setObjectName("FW_DWXCapture_" + what)
            table.setHorizontalHeaderLabels(["Name", "Model", "Value"][:table.columnCount()])
            table.horizontalHeader().setStretchLastSection(True)
            lay.addWidget(table, 1)
            if what == "properties":
                row = QtWidgets.QHBoxLayout()
                name = QtWidgets.QLineEdit()
                name.setObjectName("FW_DWXNewProperty")
                name.setPlaceholderText("New property name")
                add = QtWidgets.QPushButton("Add")
                add.setObjectName("FW_DWXAddProperty")
                row.addWidget(name, 1)
                row.addWidget(add)
                lay.addLayout(row)

                def add_prop():
                    n = name.text().strip()
                    if not n:
                        return
                    base = os.path.basename(self.project["model"])
                    w.extra.append({"doc": base, "obj": "", "prop": "CustomProperty:" + n,
                                    "name": "%s@%s" % (n, os.path.splitext(base)[0])})
                    name.clear()
                    take()
                    w.refresh()
                add.clicked.connect(add_prop)
            w.extra = []
            w.table = table
            w.rows = []

            def refresh():
                have = {key(i): i for i in self.project[what]}
                if what == "dimensions":
                    cands = dimension_candidates(self.doc)
                elif what == "features":
                    cands = [(i, None) for i in feature_candidates(self.doc)]
                else:
                    cands = [(i, None) for i in property_candidates(self.doc) + w.extra]
                for i in self.project[what]:
                    if key(i) not in {key(c) for c, _v in cands}:
                        cands.append((i, None))
                table.setRowCount(len(cands))
                w.rows = []
                for r, (item, value) in enumerate(cands):
                    item = dict(have.get(key(item), item))
                    it = QtWidgets.QTableWidgetItem(item["name"])
                    it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEditable)
                    it.setCheckState(QtCore.Qt.Checked if key(item) in have else QtCore.Qt.Unchecked)
                    table.setItem(r, 0, it)
                    m = QtWidgets.QTableWidgetItem(item["doc"])
                    m.setFlags(m.flags() & ~QtCore.Qt.ItemIsEditable)
                    table.setItem(r, 1, m)
                    if what == "dimensions":
                        v = QtWidgets.QTableWidgetItem("" if value is None else "%g" % value)
                        v.setFlags(v.flags() & ~QtCore.Qt.ItemIsEditable)
                        table.setItem(r, 2, v)
                    w.rows.append(item)
                table.resizeColumnsToContents()

            def take():
                if not w.rows:
                    return
                out = []
                for r, item in enumerate(w.rows):
                    cell = table.item(r, 0)
                    if cell is not None and cell.checkState() == QtCore.Qt.Checked:
                        item = dict(item)
                        item["name"] = cell.text().strip() or item["name"]
                        out.append(item)
                self.project[what] = out
            w.refresh, w.take = refresh, take
            return w

        # -- Form Design
        def _form_page(self):
            w = QtWidgets.QWidget()
            lay = QtWidgets.QVBoxLayout(w)
            lay.addWidget(QtWidgets.QLabel("<b>Form Design</b>"))
            lay.addWidget(QtWidgets.QLabel("The inputs of the form. Drop-down list choices: separated by commas."))
            table = QtWidgets.QTableWidget(0, 6)
            table.setObjectName("FW_DWXForm")
            table.setHorizontalHeaderLabels(["Name", "Type", "Default", "Min", "Max", "Choices"])
            table.horizontalHeader().setStretchLastSection(True)
            lay.addWidget(table, 1)
            row = QtWidgets.QHBoxLayout()
            add = QtWidgets.QPushButton("Add Control")
            add.setObjectName("FW_DWXAddControl")
            rem = QtWidgets.QPushButton("Remove")
            rem.setObjectName("FW_DWXRemoveControl")
            row.addWidget(add)
            row.addWidget(rem)
            row.addStretch(1)
            lay.addLayout(row)
            w.table = table

            def put(r, c):
                table.setItem(r, 0, QtWidgets.QTableWidgetItem(c.get("name", "")))
                kind = QtWidgets.QComboBox()
                kind.addItems(list(KINDS))
                kind.setCurrentText(c.get("kind", "Numeric"))
                table.setCellWidget(r, 1, kind)
                for col, k in ((2, "default"), (3, "min"), (4, "max")):
                    v = c.get(k, "")
                    table.setItem(r, col, QtWidgets.QTableWidgetItem("" if v is None else str(v)))
                table.setItem(r, 5, QtWidgets.QTableWidgetItem(", ".join(c.get("choices", []))))

            def refresh():
                table.setRowCount(len(self.project["form"]))
                for r, c in enumerate(self.project["form"]):
                    put(r, c)

            def take():
                out = []
                for r in range(table.rowCount()):
                    name = (table.item(r, 0).text() if table.item(r, 0) else "").strip()
                    if not name:
                        continue
                    txt = lambda col: table.item(r, col).text().strip() if table.item(r, col) else ""
                    out.append({"name": name, "kind": table.cellWidget(r, 1).currentText(), "default": txt(2),
                                "min": txt(3), "max": txt(4),
                                "choices": [x.strip() for x in txt(5).split(",") if x.strip()]})
                self.project["form"] = out

            def add_row():
                take()
                n = len(self.project["form"]) + 1
                names = {c["name"] for c in self.project["form"]}
                while "Input%d" % n in names:
                    n += 1
                self.project["form"].append({"name": "Input%d" % n, "kind": "Numeric", "default": "0",
                                             "min": "", "max": "", "choices": []})
                refresh()

            def remove_row():
                take()
                r = table.currentRow()
                if 0 <= r < len(self.project["form"]):
                    del self.project["form"][r]
                refresh()
            add.clicked.connect(add_row)
            rem.clicked.connect(remove_row)
            w.refresh, w.take = refresh, take
            return w

        # -- Rules
        def _rules_page(self):
            w = QtWidgets.QWidget()
            lay = QtWidgets.QVBoxLayout(w)
            lay.addWidget(QtWidgets.QLabel("<b>Rules</b>"))
            lay.addWidget(QtWidgets.QLabel("A formula per item over the form's inputs, e.g. =Width*2, "
                                           "=IF(Holes>4, \"Heavy\", \"Light\"), \"Plate-\" & Width."))
            table = QtWidgets.QTableWidget(0, 3)
            table.setObjectName("FW_DWXRules")
            table.setHorizontalHeaderLabels(["Item", "Rule", "Status"])
            table.horizontalHeader().setStretchLastSection(True)
            lay.addWidget(table, 1)
            test = QtWidgets.QPushButton("Test Rules")
            test.setObjectName("FW_DWXTestRules")
            lay.addWidget(test)
            w.table = table
            w.keys = []

            def refresh():
                items = [(key(i), i["name"]) for i in captured(self.project)]
                files = [("file:" + os.path.basename(d.FileName), "File name: " + os.path.basename(d.FileName))
                         for d in model_docs(self.doc)]
                rows = items + files
                table.setRowCount(len(rows))
                w.keys = [k for k, _n in rows]
                for r, (k, name) in enumerate(rows):
                    it = QtWidgets.QTableWidgetItem(name)
                    it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
                    table.setItem(r, 0, it)
                    rule = self.project["file_names"].get(k[5:], "") if k.startswith("file:") else \
                        self.project["rules"].get(k, "")
                    table.setItem(r, 1, QtWidgets.QTableWidgetItem(rule))
                status()
                table.resizeColumnToContents(0)

            def status():
                take()
                errors = check_rules(self.project)
                for r, k in enumerate(w.keys):
                    msg = "" if k.startswith("file:") else errors.get(k, "")
                    s = QtWidgets.QTableWidgetItem("OK" if not msg else msg)
                    s.setFlags(s.flags() & ~QtCore.Qt.ItemIsEditable)
                    table.setItem(r, 2, s)

            def take():
                for r, k in enumerate(w.keys):
                    cell = table.item(r, 1)
                    text = cell.text().strip() if cell else ""
                    if k.startswith("file:"):
                        self.project["file_names"][k[5:]] = text
                    else:
                        self.project["rules"][k] = text
            test.clicked.connect(status)
            w.refresh, w.take = refresh, take
            return w

        # -- Run
        def _run_page(self):
            w = QtWidgets.QWidget()
            lay = QtWidgets.QVBoxLayout(w)
            lay.addWidget(QtWidgets.QLabel("<b>Run</b>"))
            box = QtWidgets.QGroupBox("Form")
            box.setObjectName("FW_DWXRunForm")
            self.run_form = QtWidgets.QFormLayout(box)
            lay.addWidget(box)
            create_b = QtWidgets.QPushButton("Create")
            create_b.setObjectName("FW_DWXCreate")
            lay.addWidget(create_b)
            self.created = QtWidgets.QListWidget()
            self.created.setObjectName("FW_DWXCreated")
            lay.addWidget(QtWidgets.QLabel("Created:"))
            lay.addWidget(self.created, 1)
            w.inputs = {}

            def refresh():
                while self.run_form.rowCount():
                    self.run_form.removeRow(0)
                w.inputs = {}
                for c in self.project["form"]:
                    kind = c.get("kind", "Numeric")
                    if kind == "Numeric":
                        e = QtWidgets.QDoubleSpinBox()
                        e.setDecimals(3)
                        lo = control_value(c, c.get("min")) if c.get("min") not in ("", None) else -1e9
                        hi = control_value(c, c.get("max")) if c.get("max") not in ("", None) else 1e9
                        e.setRange(lo, hi)
                        e.setValue(control_value(c, c.get("default")))
                    elif kind == "Check box":
                        e = QtWidgets.QCheckBox()
                        e.setChecked(control_value(c, c.get("default")))
                    elif kind == "Drop-down list":
                        e = QtWidgets.QComboBox()
                        e.addItems(c.get("choices") or [])
                        e.setCurrentText(str(c.get("default") or ""))
                    else:
                        e = QtWidgets.QLineEdit(str(c.get("default") or ""))
                    e.setObjectName("FW_DWXInput_" + c["name"])
                    w.inputs[c["name"]] = e
                    self.run_form.addRow(c["name"] + ":", e)
                self.created.clear()
                for spec in self.project.get("created", []):
                    for f in spec.get("files", []):
                        self.created.addItem(f)

            def values():
                out = {}
                for name, e in w.inputs.items():
                    if isinstance(e, QtWidgets.QDoubleSpinBox):
                        out[name] = e.value()
                    elif isinstance(e, QtWidgets.QCheckBox):
                        out[name] = e.isChecked()
                    elif isinstance(e, QtWidgets.QComboBox):
                        out[name] = e.currentText()
                    else:
                        out[name] = e.text()
                return out

            def run():
                self.store()
                try:
                    made = create(self.project, values())
                except Exception as error:
                    QtWidgets.QMessageBox.warning(self, "Design Automation", "Not created: %s" % error)
                    return
                for f in made.values():
                    self.created.addItem(f)
                App.Console.PrintMessage("Design Automation: created %s\n" % ", ".join(made.values()))
            create_b.clicked.connect(run)
            w.refresh, w.values, w.run = refresh, values, run
            return w


OPEN = []


def can_start():
    d = App.ActiveDocument

    return d is not None and not (Gui and Gui.Control.activeDialog())


def start(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    if not doc.FileName:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Design Automation",
                                          "Save the model first: Design Automation keeps its project beside it.")
        return None
    dlg = DriveWorksXpressDialog(doc)
    OPEN[:] = [dlg]
    dlg.show()
    return dlg


class DriveWorksXpressCommand:
    def GetResources(self):
        return {"MenuText": "Design Automation", "ToolTip": "Automates the design of a part or assembly: "
                "capture dimensions, features and properties, design a form, write rules, and create new models.",
                "Pixmap": "Spreadsheet"}

    def Activated(self, *a):
        start()

    def IsActive(self):
        return can_start()


def register():
    if Gui is None:
        return
    if "SWStyle_DriveWorksXpress" not in Gui.listCommands():
        Gui.addCommand("SWStyle_DriveWorksXpress", DriveWorksXpressCommand())
    from . import catalog
    if "DriveWorksXpress" not in catalog.BY_KEY:
        catalog.BY_KEY["DriveWorksXpress"] = catalog.c(
            "DriveWorksXpress", "Design Automation", ("SWStyle_DriveWorksXpress",), None,
            "Automates the design of a part or assembly with a form and rules.", caption="Design\nAutomation")
