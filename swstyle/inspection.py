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
import re
import zipfile

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

TAB = "Inspection"
KEY = "FreeWorksInspection"
BALLOON_TAG = "SWInspectionItem"
HEADERS = ("Item", "Zone", "Type", "Requirement", "Nominal", "Lower", "Upper", "Measured", "Result", "Classification",
           "Method", "Notes")
COL = dict((h, n) for n, h in enumerate(HEADERS))
TYPES = {"Distance": "Linear", "DistanceX": "Linear", "DistanceY": "Linear", "DistanceZ": "Linear",
         "Radius": "Radial", "Diameter": "Diameter", "Angle": "Angular", "Angle3Pt": "Angular"}
KINDS = ("Dimensions", "Hole Callouts", "Notes", "GD&T", "Surface Finish", "Welds", "Datums")
ANNOT = {"Note": ("Notes", "Note"), "GeometricTolerance": ("GD&T", "GD&T"), "SurfaceFinish": ("Surface Finish", "Surface Finish"),
         "WeldSymbol": ("Welds", "Weld"), "DatumFeature": ("Datums", "Datum")}
CLASSES = ("Incidental", "Minor", "Major", "Critical")
METHODS = ("Visual", "Caliper", "Micrometer", "Height Gauge", "Pin Gauge", "Thread Gauge", "Radius Gauge", "Protractor",
           "CMM", "Surface Tester", "Other")
SORTS = ("Horizontal", "Vertical")
SHAPES = ("Circular", "Triangle", "Hexagon", "Square", "Diamond")
TEMPLATE = {"start": 1, "sort": "Horizontal", "shape": "Circular", "extract": list(KINDS[:6]), "tol_mode": "Single",
            "precision": {"0": 0.5, "1": 0.1, "2": 0.05, "3": 0.005, "4": 0.0005}, "class": "Minor", "method": "Caliper"}
_state = {"dialog": None}


# ------------------------------------------------------------------ the sheet
def _page():
    from . import drawings
    return drawings.active_page()


def kind_of(obj):
    """(template group, type shown) of a characteristic object, or None when it is none."""
    if obj.TypeId == "TechDraw::DrawViewDimension":
        if getattr(obj, "SWHoleCallout", False):
            return "Hole Callouts", "Hole Callout"
        return "Dimensions", TYPES.get(obj.Type, obj.Type)
    got = ANNOT.get(getattr(obj, "SWAnnotation", ""))
    return got


def position(page, obj):
    """Where a characteristic sits on the sheet (mm)."""
    if obj.TypeId == "TechDraw::DrawViewDimension":
        from . import drawdimtools as T
        try:
            return T.label_centre(page, obj)
        except Exception as _fw_err:
            _fw_log("inspection.py:centre", _fw_err)
    return float(obj.X), float(obj.Y)


def _chars(page, settings=None):
    """The sheet's characteristics the template extracts, in its order: Horizontal is top to bottom then left to
    right (bands of 8 mm count as one row), Vertical left to right then top to bottom."""
    s = settings or TEMPLATE
    want = set(s.get("extract", TEMPLATE["extract"]))
    found = []
    for o in page.Views or []:
        k = kind_of(o)
        if k is None or k[0] not in want:
            continue
        x, y = position(page, o)
        if s.get("sort") == "Vertical":
            found.append((round(x / 8.0), -y, o.Name, o))
        else:
            found.append((-round(y / 8.0), x, o.Name, o))
    found.sort(key=lambda t: t[:3])
    return [t[3] for t in found]


def _dims(page):
    """The page's characteristics with the default template (older callers)."""
    return _chars(page)


def zone(page, obj):
    """The sheet zone of a characteristic: column numbers from the left, row letters from the top, 50 mm zones."""
    try:
        w, h = float(page.Template.Width), float(page.Template.Height)
    except Exception:
        w, h = 420.0, 297.0
    x, y = position(page, obj)
    cols, rows_ = max(1, int(round(w / 50.0))), max(1, int(round(h / 50.0)))
    c = min(cols, max(1, int(x / (w / cols)) + 1))
    r = min(rows_, max(1, int((h - y) / (h / rows_)) + 1))
    return "%s%d" % ("ABCDEFGHJKLMNPQRSTUVWXYZ"[r - 1], c)


def _nominal(dim):
    try:
        return float(dim.getRawValue())
    except Exception:
        pass
    m = re.search(r"[-+]?\d+(?:\.\d+)?", (dim.getText() or "").replace(",", "."))
    return float(m.group()) if m else 0.0


def _num(value):
    return float(getattr(value, "Value", value))


def decimals(dim):
    """The decimal places a dimension shows (its format, else its text)."""
    m = re.search(r"%\.(\d+)[fgw]", str(getattr(dim, "FormatSpec", "") or ""))
    if m:
        return int(m.group(1))
    m = re.search(r"\d+[.,](\d+)", dim.getText() or "") if hasattr(dim, "getText") else None
    return len(m.group(1)) if m else 0


def default_tolerance(dim, data):
    """The +/- a dimension without its own tolerance takes: the project's one value, or by its decimals."""
    s = settings(data)
    if s.get("tol_mode") == "By precision":
        table = s.get("precision") or TEMPLATE["precision"]
        n = str(min(decimals(dim), max(int(k) for k in table)))
        return float(table.get(n, data.get("default", 0.1)))
    return float(data.get("default", 0.1))


def _first_number(text):
    m = re.search(r"\d+(?:[.,]\d+)?", str(text or ""))
    return float(m.group().replace(",", ".")) if m else None


def requirement(obj):
    """The requirement of a characteristic as text: the dimension's text, the note, the frame, the symbol."""
    if obj.TypeId == "TechDraw::DrawViewDimension":
        try:
            return obj.getText() or ""
        except Exception:
            return ""
    kind = getattr(obj, "SWAnnotation", "")
    if kind == "GeometricTolerance":
        return " | ".join(c for c in (getattr(obj, "SWCells", []) or []) if c)
    if kind == "SurfaceFinish":
        return getattr(obj, "SWFinish", "")
    if kind == "DatumFeature":
        return "Datum %s" % getattr(obj, "SWDatum", "")
    return getattr(obj, "SWText", "") or obj.Label


def limits(obj, data):
    """(nominal, lower, upper) of a characteristic; None for a note or a weld (checked by eye: Pass or Fail)."""
    if obj.TypeId == "TechDraw::DrawViewDimension":
        return _limits(obj, default_tolerance(obj, data))
    kind = getattr(obj, "SWAnnotation", "")
    if kind == "GeometricTolerance":
        cells = list(getattr(obj, "SWCells", []) or [])
        tol = _first_number(cells[1] if len(cells) > 1 else "")
        return (0.0, 0.0, tol) if tol is not None else None
    if kind == "SurfaceFinish":
        ra = _first_number(getattr(obj, "SWFinish", ""))
        return (ra, 0.0, ra) if ra is not None else None
    return None


PASS_WORDS = ("pass", "ok", "yes", "accept", "accepted", "conform", "go")
FAIL_WORDS = ("fail", "ng", "no", "reject", "rejected", "nonconform", "no go")


def _limits(dim, default):
    """(nominal, lower, upper) of a dimension: its tolerance, else the project's default +/-."""
    nominal = _nominal(dim)
    try:
        over, under = _num(dim.OverTolerance), _num(dim.UnderTolerance)
        equal = bool(dim.EqualTolerance)
        exact = bool(getattr(dim, "TheoreticalExact", False))
    except Exception:
        over = under = 0.0
        equal = True
        exact = False
    if exact:
        return nominal, nominal, nominal
    if abs(over) < 1e-12 and abs(under) < 1e-12:
        return nominal, nominal - default, nominal + default
    if equal:
        return nominal, nominal - abs(over), nominal + abs(over)
    return nominal, nominal + min(over, under), nominal + max(over, under)


# ------------------------------------------------------------------ the project (kept in the document)
def _store(doc):
    """What the document keeps: {"part", "revision", "default", "pages": {sheet name: [items]}}, or None."""
    try:
        store = json.loads(dict(doc.Meta).get(KEY, "") or "null")
    except ValueError:
        store = None
    return store if isinstance(store, dict) else None


def project(doc, create=False, page=None):
    """The inspection project of one sheet: the document's part number, revision and default tolerance, and that
    sheet's own characteristics ("items"). Each sheet is numbered on its own, so working on one sheet never
    touches what was typed for another."""
    store = _store(doc)
    if store is None:
        if not create:
            return None
        store = {"part": doc.Label, "revision": "A", "default": 0.1, "pages": {}, "settings": template()}
    name = page.Name if page is not None else ""
    pages = store.get("pages") or {}
    items = pages.get(name)
    if items is None:
        items = store.get("items") or []          # a project of the first version: one list for the document
    excluded = (store.get("excluded") or {}).get(name, [])
    return {"part": store.get("part", doc.Label), "revision": store.get("revision", "A"),
            "default": store.get("default", 0.1), "items": list(items), "page": name,
            "settings": dict(TEMPLATE, **(store.get("settings") or {})), "excluded": list(excluded)}


def settings(data):
    return dict(TEMPLATE, **((data or {}).get("settings") or {}))


def _tp():
    return App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks/Inspection")


def template():
    """The template new projects start from: Save as Default in the Template Editor, else the built-in one."""
    try:
        got = json.loads(_tp().GetString("Template", "") or "{}")
    except ValueError:
        got = {}
    return dict(TEMPLATE, **(got if isinstance(got, dict) else {}))


def save_template(values):
    _tp().SetString("Template", json.dumps(dict(TEMPLATE, **values)))


def _save(doc, data):
    store = _store(doc) or {}
    store.pop("items", None)
    for key in ("part", "revision", "default", "settings"):
        if key in data or key not in store:
            store[key] = data.get(key, store.get(key, ""))
    pages = store.get("pages") or {}
    pages[data.get("page", "")] = data["items"]
    store["pages"] = pages
    excluded = store.get("excluded") or {}
    excluded[data.get("page", "")] = list(data.get("excluded", []))
    store["excluded"] = excluded
    meta = dict(doc.Meta)
    meta[KEY] = json.dumps(store)
    doc.Meta = meta


def sync(doc, page, data):
    """The items follow the sheet's characteristics: new ones are numbered on, gone ones leave, typed values stay;
    one removed in Edit Inspection Project stays out."""
    s = settings(data)
    out = set(data.get("excluded", []))
    dims = [d for d in _chars(page, s) if d.Name not in out]
    have = {i["dim"]: i for i in data["items"]}
    keep = [have[d.Name] for d in dims if d.Name in have]
    keep += [i for i in data["items"] if i["dim"] not in [d.Name for d in dims] and i.get("added")
             and doc.getObject(i["dim"]) is not None and doc.getObject(i["dim"]) in (page.Views or [])]
    next_item = max([i["item"] for i in data["items"]] or [int(s.get("start", 1)) - 1]) + 1
    new = [d for d in dims if d.Name not in have]
    if not data["items"]:
        new = dims                    # a first project: sheet order is the numbering
    for d in new:
        keep.append(new_item(d, next_item, s))
        next_item += 1
    data["items"] = sorted(keep, key=lambda i: i["item"])
    return data


def new_item(obj, number, s=None):
    s = s or TEMPLATE
    return {"dim": obj.Name, "item": int(number), "measured": "", "note": "", "class": s.get("class", "Minor"),
            "method": s.get("method", "Caliper"), "op": ""}


def result_of(measured, lims):
    """Pass, Fail or "" (nothing typed yet) for what was measured against the limits (None: Pass/Fail typed)."""
    text = str(measured or "").strip()
    if not text:
        return ""
    if lims is None or lims[2] is None:
        low = text.lower()
        return "Pass" if low in PASS_WORDS else "Fail" if low in FAIL_WORDS else ""
    try:
        m = float(text.replace(",", "."))
    except ValueError:
        low = text.lower()
        return "Pass" if low in PASS_WORDS else "Fail" if low in FAIL_WORDS else ""
    lo, hi = lims[1], lims[2]
    return "Pass" if lo - 1e-9 <= m <= hi + 1e-9 else "Fail"


def rows(doc, data):
    """[(item dict, type, nominal, lower, upper, result)] for the table and the exports (nominal and limits None
    for a characteristic checked by eye)."""
    out = []
    for i in data["items"]:
        dim = doc.getObject(i["dim"])
        if dim is None or kind_of(dim) is None:
            continue
        lims = limits(dim, data)
        nominal, lo, hi = lims if lims is not None else (None, None, None)
        out.append((i, kind_of(dim)[1], nominal, lo, hi, result_of(i.get("measured"), lims)))
    return out


def _fmt(v):
    return "" if v is None else "%.4g" % v


def _say(text, ms=8000):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, ms)
    except Exception:
        pass


def _ready():
    """(doc, page, data): the sheet's project, made first when there is none. None when no drawing is open."""
    page = _page()
    if page is None:
        _say("Inspection: open a drawing with dimensions first")
        return None
    doc = page.Document
    data = project(doc, create=True, page=page)
    data = sync(doc, page, data)
    _save(doc, data)
    return doc, page, data


# ------------------------------------------------------------------ balloons
def remove_balloons(doc, page=None):
    """Takes the inspection balloons away: the given sheet's, or all of the document's."""
    on_page = set(o.Name for o in (page.Views or [])) if page is not None else None
    gone = 0
    for o in list(doc.Objects):
        if BALLOON_TAG in getattr(o, "PropertiesList", ()) and (on_page is None or o.Name in on_page):
            doc.removeObject(o.Name)
            gone += 1
    return gone


def balloon_all(page, data):
    from . import drawannot as A
    from . import drawdimtools as T
    doc = page.Document
    made = 0
    doc.openTransaction("Balloon Characteristics")
    try:
        remove_balloons(doc, page)
        shape = settings(data).get("shape", "Circular")
        views = [v for v in (page.Views or []) if v.isDerivedFrom("TechDraw::DrawViewPart")]
        for i in data["items"]:
            dim = doc.getObject(i["dim"])
            if dim is None:
                continue
            if dim.TypeId == "TechDraw::DrawViewDimension":
                view = T.view_of(dim)
            else:      # an annotation: the balloon belongs to the nearest view
                ax, ay = position(page, dim)
                view = min(views, key=lambda v: (float(v.X) - ax) ** 2 + (float(v.Y) - ay) ** 2) if views else None
            if view is None:
                continue
            x, y = position(page, dim)
            try:
                b = A.make_balloon(page, view, (x, y), (x + 9.0, y + 9.0), shape=shape, text=str(i["item"]))
                b.addProperty("App::PropertyInteger", BALLOON_TAG, "FreeCAD", "the characteristic it numbers")
                setattr(b, BALLOON_TAG, int(i["item"]))
                if "SWBalloonKind" in b.PropertiesList:
                    b.SWBalloonKind = "Text"      # a characteristic number, not a BOM item: nothing renumbers it
                made += 1
            except Exception as error:
                App.Console.PrintLog("FreeCAD inspection: balloon %s: %s\n" % (i["item"], error))
    finally:
        doc.commitTransaction()
    doc.recompute()
    return made


# ------------------------------------------------------------------ exports
def _table(doc, data):
    head = ["Part number: %s" % data.get("part", ""), "Revision: %s" % data.get("revision", "")]
    lines = [HEADERS]
    page = doc.getObject(data.get("page", "")) if data.get("page") else None
    for i, kind, nominal, lo, hi, result in rows(doc, data):
        obj = doc.getObject(i["dim"])
        z = zone(page, obj) if page is not None else ""
        lines.append((i["item"], z, kind, requirement(obj), "" if nominal is None else nominal, "" if lo is None else lo,
                      "" if hi is None else hi, i["measured"], result, i.get("class", ""), i.get("method", ""), i["note"]))
    return head, lines


def write_csv(path, doc, data):
    head, lines = _table(doc, data)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(lines)


def _col(n):
    return "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[n]


def _cell(ref, v):
    if isinstance(v, (int, float)):
        return '<c r="%s"><v>%s</v></c>' % (ref, repr(float(v)) if isinstance(v, float) else v)
    text = (str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return '<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, text)


def write_xlsx(path, doc, data):
    """A one-sheet workbook with no library: the numbers stay numbers, so Excel can add them up."""
    head, lines = _table(doc, data)
    sheet = [head] + [()] + [list(l) for l in lines]
    body = []
    for r, row in enumerate(sheet, 1):
        cells = []
        for c, v in enumerate(row):
            if v == "":
                continue
            if r > 3 and c in (COL["Measured"],):
                try:
                    v = float(str(v).replace(",", "."))
                except ValueError:
                    pass
            cells.append(_cell("%s%d" % (_col(c), r), v))
        body.append('<row r="%d">%s</row>' % (r, "".join(cells)))
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    parts = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8"?><workbook %s xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Inspection" sheetId="1" r:id="rId1"/></sheets></workbook>' % ns,
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": '<?xml version="1.0" encoding="UTF-8"?><worksheet %s><sheetData>%s</sheetData></worksheet>' % (ns, "".join(body)),
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            z.writestr(name, text)


def write_pdf(path, doc, page):
    """The ballooned sheet as a PDF (the drawing's own PDF writer)."""
    from . import drawexport
    return drawexport.write_pdf(doc, path, [page])


def _ask_path(title, ext, doc):
    start = (doc.Label or "inspection") + " inspection." + ext
    what = {"xlsx": "Excel workbook", "csv": "CSV", "pdf": "PDF"}.get(ext, ext)
    path, _ = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), title, start, "%s (*.%s)" % (what, ext))
    if path and not path.lower().endswith("." + ext):
        path += "." + ext
    return path


# ------------------------------------------------------------------ the report
class Report(QtWidgets.QDialog):
    def __init__(self, doc, page):
        super().__init__(Gui.getMainWindow())
        self.setObjectName("SWInspectionReport")
        self.setWindowTitle("Inspection Report")
        self.resize(760, 460)
        self.doc, self.page = doc, page
        lay = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        self.part = QtWidgets.QLineEdit()
        self.rev = QtWidgets.QLineEdit()
        self.rev.setMaximumWidth(60)
        self.tol = QtWidgets.QDoubleSpinBox()
        self.tol.setDecimals(4)
        self.tol.setRange(0.0, 100.0)
        self.tol.setPrefix("+/- ")
        self.tol.setSuffix(" mm")
        self.tol.setToolTip("The limits of a dimension that has no tolerance of its own")
        for label, w in (("Part number", self.part), ("Revision", self.rev), ("Default tolerance", self.tol)):
            top.addWidget(QtWidgets.QLabel(label))
            top.addWidget(w)
        lay.addLayout(top)
        self.table = QtWidgets.QTableWidget(0, len(HEADERS))
        self.table.setObjectName("SWInspectionTable")
        self.table.setHorizontalHeaderLabels(list(HEADERS))
        self.table.setToolTip("Measured and Notes are typed in; Classification and Method are set in Edit Inspection Project")
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        lay.addWidget(self.table, 1)
        self.summary = QtWidgets.QLabel()
        lay.addWidget(self.summary)
        row = QtWidgets.QHBoxLayout()
        for text, slot, tip in (
                ("Update from Drawing", self.update_from_drawing, "Numbers new dimensions, drops deleted ones, keeps what was typed"),
                ("Balloon", self.balloon, "Numbered balloons next to every dimension"),
                ("Export to Excel...", self.to_excel, "A workbook with the table"),
                ("Export to CSV...", self.to_csv, "The table as comma separated text"),
                ("Export to PDF...", self.to_pdf, "The ballooned sheet as a PDF")):
            b = QtWidgets.QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)
        self.table.itemChanged.connect(self._edited)
        self.table.itemSelectionChanged.connect(self._picked)
        for w in (self.part, self.rev):
            w.editingFinished.connect(self._head)
        self.tol.editingFinished.connect(self._head)
        self.load()

    def data(self):
        return project(self.doc, create=True, page=self.page)

    def _summary(self, data):
        table = rows(self.doc, data)
        passed = sum(1 for t in table if t[5] == "Pass")
        failed = sum(1 for t in table if t[5] == "Fail")
        total = len(table)
        self.summary.setText("%d characteristics: %d pass, %d fail, %d not measured yet"
                             % (total, passed, failed, total - passed - failed))

    def _paint_result(self, item, result):
        item.setText(result)
        item.setForeground(QtGui.QBrush(QtGui.QColor("#1b7a1b" if result == "Pass" else "#b00020")))

    def load(self):
        data = self.data()
        self.part.setText(data.get("part", ""))
        self.rev.setText(data.get("revision", ""))
        self.tol.setValue(float(data.get("default", 0.1)))
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for i, kind, nominal, lo, hi, result in rows(self.doc, data):
            r = self.table.rowCount()
            self.table.insertRow(r)
            obj = self.doc.getObject(i["dim"])
            cells = (i["item"], zone(self.page, obj), kind, requirement(obj), _fmt(nominal), _fmt(lo), _fmt(hi),
                     i["measured"], result, i.get("class", ""), i.get("method", ""), i["note"])
            for c, v in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(str(v))
                item.setData(QtCore.Qt.UserRole, i["dim"])
                if c not in (COL["Measured"], COL["Notes"]):
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                if c == COL["Result"] and result:
                    item.setForeground(QtGui.QBrush(QtGui.QColor("#1b7a1b" if result == "Pass" else "#b00020")))
                self.table.setItem(r, c, item)
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        self._summary(data)

    def _head(self):
        data = self.data()
        data["part"], data["revision"], data["default"] = self.part.text(), self.rev.text(), self.tol.value()
        _save(self.doc, data)
        self.load()

    def _edited(self, item):
        if item.column() not in (COL["Measured"], COL["Notes"]):
            return
        data = self.data()
        for i in data["items"]:
            if i["dim"] == item.data(QtCore.Qt.UserRole):
                i["measured" if item.column() == COL["Measured"] else "note"] = item.text().strip()
        _save(self.doc, data)
        # only this row's Result and the summary change: the table is not rebuilt under the cell being typed in
        result = next((t[5] for t in rows(self.doc, data) if t[0]["dim"] == item.data(QtCore.Qt.UserRole)), "")
        cell = self.table.item(item.row(), COL["Result"])
        if cell is not None:
            self.table.blockSignals(True)
            self._paint_result(cell, result)
            self.table.blockSignals(False)
        self._summary(data)

    def _picked(self):
        try:
            dim = self.table.item(self.table.currentRow(), 0).data(QtCore.Qt.UserRole)
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(self.doc.Name, dim)
        except Exception:
            pass

    def _sheet_gone(self):
        try:
            return self.doc.getObject(self.page.Name) is not self.page
        except Exception:
            return True

    def _try(self, what, fn):
        if self._sheet_gone():
            self.summary.setText("This report's sheet was deleted: open Inspection Report again on a sheet.")
            return
        try:
            fn()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD inspection: %s: %s\n" % (what, error))
            self.summary.setText("%s did not work: %s" % (what, error))

    def update_from_drawing(self):
        def go():
            data = sync(self.doc, self.page, self.data())
            _save(self.doc, data)
            self.load()
        self._try("Update from Drawing", go)

    def balloon(self):
        self._try("Balloon", lambda: _say("Inspection: %d balloons placed" % balloon_all(self.page, self.data())))

    def to_excel(self):
        def go():
            path = _ask_path("Export to Excel", "xlsx", self.doc)
            if path:
                write_xlsx(path, self.doc, self.data())
                _say("Inspection report saved: " + path)
        self._try("Export to Excel", go)

    def to_csv(self):
        def go():
            path = _ask_path("Export to CSV", "csv", self.doc)
            if path:
                write_csv(path, self.doc, self.data())
                _say("Inspection report saved: " + path)
        self._try("Export to CSV", go)

    def to_pdf(self):
        def go():
            path = _ask_path("Export to PDF", "pdf", self.doc)
            if path:
                write_pdf(path, self.doc, self.page)
                _say("Inspection sheet saved: " + path)
        self._try("Export to PDF", go)


def show_report(doc, page):
    dlg = _state.get("dialog")
    try:
        if dlg is not None and dlg.doc is doc:
            dlg.page = page
            dlg.load()
            dlg.show()
            dlg.raise_()
            return dlg
        if dlg is not None:
            dlg.close()
    except RuntimeError:
        pass
    dlg = _state["dialog"] = Report(doc, page)
    dlg.show()
    return dlg


# ------------------------------------------------------------------ project editing (no GUI needed)
def move(data, dim, step):
    """Moves a characteristic up (-1) or down (+1) in the order; the numbers follow the order."""
    items = sorted(data["items"], key=lambda i: i["item"])
    n = next((k for k, i in enumerate(items) if i["dim"] == dim), None)
    m = None if n is None else n + step
    if m is None or not 0 <= m < len(items):
        return False
    items[n]["item"], items[m]["item"] = items[m]["item"], items[n]["item"]
    data["items"] = sorted(items, key=lambda i: i["item"])
    return True


def renumber(data):
    """1, 2, 3 ... (from the template's start) in the present order."""
    start = int(settings(data).get("start", 1))
    for k, i in enumerate(sorted(data["items"], key=lambda i: i["item"])):
        i["item"] = start + k
    data["items"] = sorted(data["items"], key=lambda i: i["item"])


def remove(data, dim):
    """Takes a characteristic out of the project; Update leaves it out."""
    before = len(data["items"])
    data["items"] = [i for i in data["items"] if i["dim"] != dim]
    if dim not in data.setdefault("excluded", []):
        data["excluded"].append(dim)
    return len(data["items"]) < before


def add(data, objs):
    """Adds annotations picked on the sheet as characteristics (numbered on); a removed one comes back."""
    have = set(i["dim"] for i in data["items"])
    s = settings(data)
    n = max([i["item"] for i in data["items"]] or [int(s.get("start", 1)) - 1]) + 1
    made = []
    for o in objs:
        if o is None or o.Name in have or kind_of(o) is None:
            continue
        if o.Name in data.get("excluded", []):
            data["excluded"].remove(o.Name)
        item = new_item(o, n, s)
        item["added"] = True
        data["items"].append(item)
        made.append(item)
        n += 1
    return made


def set_field(data, dim, key, value):
    for i in data["items"]:
        if i["dim"] == dim:
            i[key] = value
            return True
    return False


def delete_project(doc, page):
    """The sheet's project and its balloons go; other sheets' projects stay."""
    gone = remove_balloons(doc, page)
    store = _store(doc)
    if store is not None:
        (store.get("pages") or {}).pop(page.Name, None)
        (store.get("excluded") or {}).pop(page.Name, None)
        meta = dict(doc.Meta)
        if store.get("pages"):
            meta[KEY] = json.dumps(store)
        else:
            meta.pop(KEY, None)
        doc.Meta = meta
    doc.recompute()
    return gone


if Gui is not None:
    class TemplateEditor(QtWidgets.QDialog):
        ""


        def __init__(self, doc, page):
            super().__init__(Gui.getMainWindow())
            self.setObjectName("SWInspectionTemplate")
            self.setWindowTitle("Inspection Template")
            self.doc, self.page = doc, page
            data = project(doc, create=True, page=page)
            s = settings(data)
            lay = QtWidgets.QVBoxLayout(self)
            box = QtWidgets.QGroupBox("Extract")
            g = QtWidgets.QGridLayout(box)
            self.extract = {}
            for n, k in enumerate(KINDS):
                c = QtWidgets.QCheckBox(k)
                c.setObjectName("SWInspExtract_" + re.sub(r"[^A-Za-z]", "", k))
                c.setChecked(k in s.get("extract", []))
                self.extract[k] = c
                g.addWidget(c, n // 2, n % 2)
            lay.addWidget(box)
            box = QtWidgets.QGroupBox("Numbering and Balloons")
            f = QtWidgets.QFormLayout(box)
            self.start = QtWidgets.QSpinBox()
            self.start.setObjectName("SWInspStart")
            self.start.setRange(0, 100000)
            self.start.setValue(int(s.get("start", 1)))
            self.sort = QtWidgets.QComboBox()
            self.sort.setObjectName("SWInspSort")
            self.sort.addItems(SORTS)
            self.sort.setCurrentText(s.get("sort", "Horizontal"))
            self.shape = QtWidgets.QComboBox()
            self.shape.setObjectName("SWInspShape")
            self.shape.addItems(SHAPES)
            self.shape.setCurrentText(s.get("shape", "Circular"))
            f.addRow("Start at:", self.start)
            f.addRow("Sort order:", self.sort)
            f.addRow("Balloon shape:", self.shape)
            lay.addWidget(box)
            box = QtWidgets.QGroupBox("Default Tolerance (dimensions without their own)")
            f = QtWidgets.QFormLayout(box)
            self.mode = QtWidgets.QComboBox()
            self.mode.setObjectName("SWInspTolMode")
            self.mode.addItems(["Single", "By precision"])
            self.mode.setCurrentText(s.get("tol_mode", "Single"))
            self.single = QtWidgets.QDoubleSpinBox()
            self.single.setObjectName("SWInspTolSingle")
            self.single.setDecimals(4)
            self.single.setRange(0, 100)
            self.single.setPrefix("+/- ")
            self.single.setValue(float(data.get("default", 0.1)))
            f.addRow("Tolerance:", self.mode)
            f.addRow("Single value:", self.single)
            self.prec = {}
            for k in sorted((s.get("precision") or TEMPLATE["precision"]), key=int):
                sp = QtWidgets.QDoubleSpinBox()
                sp.setObjectName("SWInspTolPrec%s" % k)
                sp.setDecimals(4)
                sp.setRange(0, 100)
                sp.setPrefix("+/- ")
                sp.setValue(float(s["precision"][k]))
                self.prec[k] = sp
                f.addRow("X" + ("." + "X" * int(k) if int(k) else "") + ":", sp)
            lay.addWidget(box)
            box = QtWidgets.QGroupBox("New Characteristics")
            f = QtWidgets.QFormLayout(box)
            self.cls = QtWidgets.QComboBox()
            self.cls.setObjectName("SWInspClass")
            self.cls.addItems(CLASSES)
            self.cls.setCurrentText(s.get("class", "Minor"))
            self.method = QtWidgets.QComboBox()
            self.method.setObjectName("SWInspMethod")
            self.method.addItems(METHODS)
            self.method.setCurrentText(s.get("method", "Caliper"))
            f.addRow("Classification:", self.cls)
            f.addRow("Inspection method:", self.method)
            lay.addWidget(box)
            row = QtWidgets.QHBoxLayout()
            default = QtWidgets.QPushButton("Save as Default")
            default.setObjectName("SWInspSaveDefault")
            default.clicked.connect(lambda: save_template(self.values()))
            ok = QtWidgets.QPushButton("OK")
            ok.setObjectName("SWInspTemplateOK")
            ok.clicked.connect(self.apply)
            cancel = QtWidgets.QPushButton("Cancel")
            cancel.clicked.connect(self.reject)
            row.addWidget(default)
            row.addStretch(1)
            row.addWidget(ok)
            row.addWidget(cancel)
            lay.addLayout(row)

        def values(self):
            return {"start": self.start.value(), "sort": self.sort.currentText(), "shape": self.shape.currentText(),
                    "extract": [k for k, c in self.extract.items() if c.isChecked()],
                    "tol_mode": self.mode.currentText(),
                    "precision": dict((k, sp.value()) for k, sp in self.prec.items()),
                    "class": self.cls.currentText(), "method": self.method.currentText()}

        def apply(self):
            data = project(self.doc, create=True, page=self.page)
            data["settings"] = self.values()
            data["default"] = self.single.value()
            data = sync(self.doc, self.page, data)
            _save(self.doc, data)
            self.accept()
            return data

    class EditProject(QtWidgets.QDialog):
        ""


        def __init__(self, doc, page):
            super().__init__(Gui.getMainWindow())
            self.setObjectName("SWInspectionEdit")
            self.setWindowTitle("Edit Inspection Project")
            self.resize(720, 420)
            self.doc, self.page = doc, page
            lay = QtWidgets.QVBoxLayout(self)
            self.table = QtWidgets.QTableWidget(0, 6)
            self.table.setObjectName("SWInspectionEditTable")
            self.table.setHorizontalHeaderLabels(["Item", "Type", "Requirement", "Classification", "Operation", "Method"])
            self.table.horizontalHeader().setStretchLastSection(True)
            self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
            lay.addWidget(self.table, 1)
            row = QtWidgets.QHBoxLayout()
            self.buttons = {}
            for text, fn in (("Move Up", lambda: self.move(-1)), ("Move Down", lambda: self.move(1)),
                             ("Renumber", self.renumber), ("Remove", self.remove),
                             ("Add Characteristic", self.add), ("Template...", self.template)):
                b = QtWidgets.QPushButton(text)
                b.setObjectName("SWInspEdit_" + text.replace(" ", "").replace(".", ""))
                b.clicked.connect(lambda *_a, fn=fn: fn())
                self.buttons[text] = b
                row.addWidget(b)
            row.addStretch(1)
            close = QtWidgets.QPushButton("Close")
            close.clicked.connect(self.accept)
            row.addWidget(close)
            lay.addLayout(row)
            self.table.itemSelectionChanged.connect(self._picked)
            self.load()

        def data(self):
            return project(self.doc, create=True, page=self.page)

        def load(self, select=None):
            data = self.data()
            self.table.blockSignals(True)
            self.table.setRowCount(0)
            for i, kind, _n, _lo, _hi, _r in rows(self.doc, data):
                r = self.table.rowCount()
                self.table.insertRow(r)
                for c, v in enumerate((i["item"], kind, requirement(self.doc.getObject(i["dim"])))):
                    it = QtWidgets.QTableWidgetItem(str(v))
                    it.setData(QtCore.Qt.UserRole, i["dim"])
                    it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
                    self.table.setItem(r, c, it)
                cls = QtWidgets.QComboBox()
                cls.addItems(CLASSES)
                cls.setCurrentText(i.get("class", "Minor"))
                cls.currentTextChanged.connect(lambda t, d=i["dim"]: self.set(d, "class", t))
                self.table.setCellWidget(r, 3, cls)
                op = QtWidgets.QLineEdit(str(i.get("op", "")))
                op.editingFinished.connect(lambda w=op, d=i["dim"]: self.set(d, "op", w.text().strip()))
                self.table.setCellWidget(r, 4, op)
                meth = QtWidgets.QComboBox()
                meth.addItems(METHODS)
                meth.setCurrentText(i.get("method", "Caliper"))
                meth.currentTextChanged.connect(lambda t, d=i["dim"]: self.set(d, "method", t))
                self.table.setCellWidget(r, 5, meth)
                if select == i["dim"]:
                    self.table.selectRow(r)
            self.table.blockSignals(False)
            self.table.resizeColumnsToContents()
            self._gate()

        def _gate(self):
            """Move Up, Move Down and Remove act on the picked row: on only when one is picked."""
            row = self.current() is not None
            for text in ("Move Up", "Move Down", "Remove"):
                self.buttons[text].setEnabled(row)
            self.buttons["Renumber"].setEnabled(self.table.rowCount() > 0)

        def current(self):
            it = self.table.item(self.table.currentRow(), 0) if self.table.currentRow() >= 0 else None
            return it.data(QtCore.Qt.UserRole) if it is not None else None

        def _picked(self):
            d = self.current()
            self._gate()
            if d:
                try:
                    Gui.Selection.clearSelection()
                    Gui.Selection.addSelection(self.doc.Name, d)
                except Exception as _fw_err:
                    _fw_log("inspection.py:pick", _fw_err)

        def _change(self, fn, select=None):
            data = self.data()
            done = fn(data)
            _save(self.doc, data)
            self.load(select)
            return done

        def set(self, dim, key, value):
            return self._change(lambda d: set_field(d, dim, key, value), dim)

        def move(self, step):
            d = self.current()
            return self._change(lambda data: move(data, d, step), d) if d else False

        def renumber(self):
            return self._change(renumber)

        def remove(self):
            d = self.current()
            return self._change(lambda data: remove(data, d)) if d else False

        def add(self, objs=None):
            if objs is None:
                objs = [o for o in Gui.Selection.getSelection(self.doc.Name) if o in (self.page.Views or [])]
            made = self._change(lambda data: add(data, objs))
            if not made:
                QtWidgets.QMessageBox.information(self, "Add Characteristic",
                                                  "Pick dimensions or annotations on the sheet that are not in the project yet.")
            return made

        def template(self):
            dlg = TemplateEditor(self.doc, self.page)
            if dlg.exec():
                self.load()


# ------------------------------------------------------------------ commands
def _create():
    r = _ready()
    if r is None:
        return
    doc, page, data = r
    show_report(doc, page)
    _say("Inspection project: %d characteristics numbered. Type what was measured in the table; Balloon numbers the drawing." % len(data["items"]), 12000)


def _balloon():
    r = _ready()
    if r is None:
        return
    doc, page, data = r
    made = balloon_all(page, data)
    _say("Inspection: %d numbered balloons placed next to the dimensions" % made if made else
         "Inspection: no dimensions to balloon on this sheet; add dimensions first")


def _remove():
    page = _page()
    if page is None:
        _say("Inspection: open a drawing first")
        return
    doc = page.Document
    doc.openTransaction("Remove Inspection Balloons")
    try:
        gone = remove_balloons(doc, page)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    doc.recompute()
    _say("Inspection: %d balloons removed" % gone)


def _report():
    r = _ready()
    if r is None:
        return
    show_report(r[0], r[1])
    _say("Inspection report: type the measured values; Result follows the limits", 10000)


def _template():
    page = _page()
    if page is None:
        _say("Inspection: open a drawing first")
        return None
    dlg = TemplateEditor(page.Document, page)
    _state["template"] = dlg
    dlg.show()
    return dlg


def _edit():
    r = _ready()
    if r is None:
        return None
    dlg = EditProject(r[0], r[1])
    _state["edit"] = dlg
    dlg.show()
    return dlg


def _add():
    r = _ready()
    if r is None:
        return None
    doc, page, data = r
    objs = [o for o in Gui.Selection.getSelection(doc.Name) if o in (page.Views or [])]
    made = add(data, objs)
    _save(doc, data)
    _say("Inspection: %d characteristics added" % len(made) if made else
         "Inspection: pick dimensions or annotations on the sheet first, then Add Characteristic")
    return made


def _update():
    r = _ready()
    if r is None:
        return None
    _say("Inspection project updated: %d characteristics" % len(r[2]["items"]))
    dlg = _state.get("dialog")
    try:
        if dlg is not None and dlg.doc is r[0]:
            dlg.load()
    except RuntimeError:
        pass
    return r[2]


def _pdf():
    r = _ready()
    if r is None:
        return
    path = _ask_path("Export to PDF", "pdf", r[0])
    if path:
        write_pdf(path, r[0], r[1])
        _say("Inspection sheet saved: " + path)


def _delete():
    page = _page()
    if page is None:
        _say("Inspection: open a drawing first")
        return None
    doc = page.Document
    if project(doc, page=page) is None:
        _say("Inspection: this sheet has no inspection project")
        return None
    box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question, "Delete Inspection Project",
                                "Delete this sheet's inspection project and its balloons? What was measured goes too.",
                                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, Gui.getMainWindow())
    if box.exec() != QtWidgets.QMessageBox.Yes:
        return None
    doc.openTransaction("Delete Inspection Project")
    try:
        gone = delete_project(doc, page)
    finally:
        doc.commitTransaction()
    _say("Inspection project deleted (%d balloons)" % gone)
    return gone


def _excel():
    r = _ready()
    if r is None:
        return
    path = _ask_path("Export to Excel", "xlsx", r[0])
    if path:
        write_xlsx(path, r[0], r[2])
        _say("Inspection report saved: " + path)


def _csv():
    r = _ready()
    if r is None:
        return
    path = _ask_path("Export to CSV", "csv", r[0])
    if path:
        write_csv(path, r[0], r[2])
        _say("Inspection report saved: " + path)


COMMANDS = (
    ("FW_Insp_Create", "Create Inspection Project", "Numbers the sheet's characteristics and opens the report.", _create),
    ("FW_Insp_Template", "Template Editor", "What is extracted, the numbering, balloons, default tolerances, classification.",
     _template),
    ("FW_Insp_Edit", "Edit Inspection Project", "Order, classification, operation and method of the characteristics.", _edit),
    ("FW_Insp_Add", "Add Characteristic", "Adds the dimensions or annotations picked on the sheet.", _add),
    ("FW_Insp_Update", "Update Inspection Project", "Numbers new characteristics on and drops deleted ones.", _update),
    ("FW_Insp_Pdf", "Export Inspection to PDF", "Saves the ballooned sheet as a PDF.", _pdf),
    ("FW_Insp_Delete", "Delete Inspection Project", "Deletes the sheet's inspection project and its balloons.", _delete),
    ("FW_Insp_Balloon", "Balloon Characteristics", "Numbered balloons next to every dimension of the sheet.", _balloon),
    ("FW_Insp_RemoveBalloons", "Remove Inspection Balloons", "Takes the inspection balloons off the sheet.", _remove),
    ("FW_Insp_Report", "Inspection Report", "The table of characteristics: nominal, limits, measured, pass or fail.", _report),
    ("FW_Insp_Excel", "Export Inspection to Excel", "Saves the inspection report as an Excel workbook.", _excel),
    ("FW_Insp_Csv", "Export Inspection to CSV", "Saves the inspection report as comma separated text.", _csv),
)
# catalog key, label, command, caption
KEYS = (
    ("INSP_Create", "Create Inspection Project", "FW_Insp_Create", "Create Inspection\nProject"),
    ("INSP_Template", "Template Editor", "FW_Insp_Template", "Template\nEditor"),
    ("INSP_Edit", "Edit Inspection Project", "FW_Insp_Edit", "Edit Inspection\nProject"),
    ("INSP_Add", "Add Characteristic", "FW_Insp_Add", "Add\nCharacteristic"),
    ("INSP_Update", "Update Inspection Project", "FW_Insp_Update", "Update\nProject"),
    ("INSP_Pdf", "Export Inspection to PDF", "FW_Insp_Pdf", "Export to\nPDF"),
    ("INSP_Delete", "Delete Inspection Project", "FW_Insp_Delete", "Delete\nProject"),
    ("INSP_Balloon", "Balloon Characteristics", "FW_Insp_Balloon", "Balloon"),
    ("INSP_RemoveBalloons", "Remove Inspection Balloons", "FW_Insp_RemoveBalloons", "Remove\nBalloons"),
    ("INSP_Report", "Inspection Report", "FW_Insp_Report", "Inspection\nReport"),
    ("INSP_Excel", "Export Inspection to Excel", "FW_Insp_Excel", "Export to\nExcel"),
    ("INSP_Csv", "Export Inspection to CSV", "FW_Insp_Csv", "Export to\nCSV"),
)
SEP = ("sep",)
LAYOUT = (("large", "INSP_Create", None), ("large", "INSP_Template", None), ("large", "INSP_Edit", None), SEP,
          ("large", "INSP_Add", None), ("large", "INSP_Update", None),
          ("large", "INSP_Balloon", ("INSP_Balloon", "INSP_RemoveBalloons")), SEP,
          ("large", "INSP_Report", None), ("large", "INSP_Excel", ("INSP_Excel", "INSP_Csv", "INSP_Pdf")), SEP,
          ("large", "INSP_Delete", None))


class _Cmd:
    def __init__(self, text, tip, run):
        self.text, self.tip, self.run = text, tip, run

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip}

    def IsActive(self):
        try:
            return _page() is not None
        except Exception:
            return False

    def Activated(self):
        try:
            self.run()
        except Exception as error:
            App.Console.PrintError("FreeCAD inspection: %s\n" % error)
            _say("Inspection: %s" % error)


def _shown():
    try:
        from . import cmtabs
        return TAB not in cmtabs.hidden()
    except Exception as _fw_err:
        _fw_log("inspection.py:622", _fw_err)
        return True


def install():
    """After the add-in tabs: the commands and keys, and the tab on the drawing CommandManager after Evaluate."""
    if Gui is None:
        return
    try:
        from . import catalog
        for name, text, tip, run in COMMANDS:
            if name not in Gui.listCommands():
                Gui.addCommand(name, _Cmd(text, tip, run))
        for key, label, native, caption in KEYS:
            if key not in catalog.BY_KEY:
                catalog.BY_KEY[key] = catalog.c(key, label, (native,), None, label, caption=caption)
        catalog.ALL = tuple(catalog._ALL)
        try:
            from . import simicons      # the tab's pictures (the pack's own FW_INSP_ ones win)
            simicons.install()
        except Exception as _fw_err:
            _fw_log("inspection.py:icons", _fw_err)
        original = getattr(catalog, "drawing_tabs", None)
        if original is None or getattr(original, "_fw_inspection", False):
            return

        def drawing_tabs(part_tabs):
            tabs = list(original(part_tabs))
            if _shown() and not any(t[0] == TAB for t in tabs):
                at = next((n + 1 for n, t in enumerate(tabs) if t[0] == "Evaluate"), len(tabs))
                tabs.insert(at, (TAB, LAYOUT))
            return tuple(tabs)

        drawing_tabs._fw_inspection = True
        drawing_tabs.__doc__ = original.__doc__
        catalog.drawing_tabs = drawing_tabs
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Inspection tab not added (%s)\n" % error)
