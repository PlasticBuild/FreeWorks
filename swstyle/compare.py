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

import datetime
import html
import math
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import evaluate, featurepaint

TITLE = "Compare"
DOC_PROPERTIES = ("Label", "CreatedBy", "CreationDate", "LastModifiedBy", "LastModifiedDate",
                  "Comment", "Company", "License", "Id")
SAME, ONLY_REF, ONLY_MOD, CHANGED = "Same", "Only in reference", "Only in modified", "Changed"


def _text(value):
    if hasattr(value, "UserString"):
        return value.UserString
    if isinstance(value, float):
        return "%g" % value
    return str(value)


def documents(ref, mod):
    """[(property, reference value, modified value, differs)]."""
    out = []
    for name in DOC_PROPERTIES:
        a, b = _text(getattr(ref, name, "")), _text(getattr(mod, name, ""))
        out.append((name, a, b, a != b))
    meta_a, meta_b = dict(getattr(ref, "Meta", {}) or {}), dict(getattr(mod, "Meta", {}) or {})
    for key in sorted(set(meta_a) | set(meta_b)):
        a, b = meta_a.get(key, ""), meta_b.get(key, "")
        out.append(("Custom: " + key, a, b, a != b))
    return out


def _helper(obj):
    """The add-on's own tree rows (Solid Bodies, Material): not features."""
    return type(getattr(obj, "Proxy", None)).__name__.endswith(("Row", "Folder"))


def _features(doc):
    """{label: object} of the document's modelling objects (no origins, planes of origins, or the
    add-on's own tree rows)."""
    out = {}
    for obj in doc.Objects:
        if _helper(obj):
            continue
        if obj.isDerivedFrom("App::Origin") or (obj.TypeId in ("App::Line", "App::Plane", "App::Point")
                                                and any(p.isDerivedFrom("App::Origin") for p in obj.InList)):
            continue
        out[obj.Label] = obj
    return out


def _settings(obj):
    return {name: _text(getattr(obj, name)) for name in featurepaint.parameters(obj)}


def features(ref, mod):
    """[(label, kind, status, what differs)] in the reference's order, then the modified's own."""
    a, b = _features(ref), _features(mod)
    out = []
    for label, obj in a.items():
        other = b.get(label)
        kind = obj.TypeId.split("::")[-1]
        if other is None:
            out.append((label, kind, ONLY_REF, ""))
            continue
        if other.TypeId != obj.TypeId:
            out.append((label, kind, CHANGED, "kind: %s -> %s" % (kind, other.TypeId.split("::")[-1])))
            continue
        sa, sb = _settings(obj), _settings(other)
        diffs = ["%s: %s -> %s" % (featurepaint.words(k), sa.get(k, ""), sb.get(k, ""))
                 for k in sorted(set(sa) | set(sb)) if sa.get(k) != sb.get(k)]
        if obj.isDerivedFrom("Sketcher::SketchObject"):
            if obj.GeometryCount != other.GeometryCount or obj.ConstraintCount != other.ConstraintCount:
                diffs.append("entities %d/%d -> %d/%d" % (obj.GeometryCount, obj.ConstraintCount,
                                                        other.GeometryCount, other.ConstraintCount))
        out.append((label, kind, CHANGED if diffs else SAME, "; ".join(diffs)))
    for label, obj in b.items():
        if label not in a:
            out.append((label, obj.TypeId.split("::")[-1], ONLY_MOD, ""))
    return out


def bom(doc):
    """{part name: quantity}: an assembly's components (links counted by what they show, link
    arrays by their element count), else the document's bodies."""
    out = {}
    links = [o for o in doc.Objects if o.isDerivedFrom("App::Link")]
    for link in links:
        target = link.getLinkedObject(True)
        if target is None or target is link:
            continue
        name = target.Document.Label if target.Document is not doc else target.Label
        count = getattr(link, "ElementCount", 0) or 1
        out[name] = out.get(name, 0) + count
    if not out:
        for obj in evaluate.visible_bodies(doc):
            out[obj.Label] = out.get(obj.Label, 0) + 1
    return out


def bom_rows(ref, mod):
    a, b = bom(ref), bom(mod)
    out = []
    for name in list(a) + [n for n in b if n not in a]:
        qa, qb = a.get(name, 0), b.get(name, 0)
        status = ONLY_MOD if not qa else ONLY_REF if not qb else SAME if qa == qb else CHANGED
        out.append((name, str(qa) if qa else "", str(qb) if qb else "", status))
    return out


DIMENSION_KINDS = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle")


def dimensions(doc):
    """{name: value text}: each sketch's dimensions (by their name, else Sketch.D<n>) and the
    values of dimension annotations (TechDraw dimensions, measurement objects)."""
    out = {}
    for obj in doc.Objects:
        if obj.isDerivedFrom("Sketcher::SketchObject"):
            for i, c in enumerate(obj.Constraints):
                if c.Type not in DIMENSION_KINDS or not getattr(c, "Driving", True):
                    continue
                name = "%s.%s" % (obj.Label, c.Name or "D%d" % (i + 1))
                out[name] = "%.4g°" % math.degrees(c.Value) if c.Type == "Angle" else "%.4g mm" % c.Value
        elif obj.TypeId.startswith("TechDraw::DrawViewDimension") or obj.TypeId.startswith("Measure::"):
            for prop in ("Distance", "Angle", "Radius", "Diameter", "Result"):
                if prop in obj.PropertiesList:
                    out[obj.Label] = _text(getattr(obj, prop))
                    break
    return out


def pmi_rows(ref, mod):
    a, b = dimensions(ref), dimensions(mod)
    out = []
    for name in list(a) + [n for n in b if n not in a]:
        va, vb = a.get(name, ""), b.get(name, "")
        status = ONLY_MOD if name not in a else ONLY_REF if name not in b else SAME if va == vb else CHANGED
        out.append((name, va, vb, status))
    return out


def reports_folder():
    path = App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks/Compare").GetString("ReportFolder", "")
    if not path:
        path = os.path.join(App.getUserAppDataDir(), "FreeWorks", "CompareReports")
    os.makedirs(path, exist_ok=True)
    return path


def report_html(ref, mod, result):
    """The comparison as one page."""
    def table(head, rows):
        cells = "".join("<th>%s</th>" % html.escape(h) for h in head)
        body = "".join("<tr%s>%s</tr>" % (' class="d"' if any(str(c) in (ONLY_REF, ONLY_MOD, CHANGED, "True") for c in r) else "",
                                          "".join("<td>%s</td>" % html.escape(str(c)) for c in r)) for r in rows)
        return "<table><tr>%s</tr>%s</table>" % (cells, body)
    g = result["geometry"]
    geo = [("Volume", "%.3f" % g["ref_volume"], "%.3f" % g["mod_volume"]),
           ("Surface area", "%.3f" % g["ref_area"], "%.3f" % g["mod_area"]),
           ("Removed volume", "%.3f" % g["removed"], ""), ("Added volume", "", "%.3f" % g["added"])]
    parts = ["<h1>Compare: %s / %s</h1><p>%s</p>" % (html.escape(ref.Label), html.escape(mod.Label),
                                                    datetime.datetime.now().strftime("%Y-%m-%d %H:%M")),
             "<h2>Documents</h2>", table(["Property", "Reference", "Modified", "Differs"], result["documents"]),
             "<h2>Features</h2>", table(["Feature", "Kind", "Result", "Differences"], result["features"]),
             "<h2>Geometry</h2>", table(["Result", "Reference", "Modified"], geo),
             "<h2>BOM</h2>", table(["Part", "Reference", "Modified", "Result"], result.get("bom", [])),
             "<h2>3D PMI</h2>", table(["Dimension", "Reference", "Modified", "Result"], result.get("pmi", []))]
    style = ("<style>body{font-family:sans-serif;font-size:13px}table{border-collapse:collapse;margin-bottom:12px}"
             "td,th{border:1px solid #bbb;padding:2px 6px;text-align:left}tr.d td{background:#ffe2e2}</style>")
    return "<html><head><meta charset='utf-8'><title>Compare</title>%s</head><body>%s</body></html>" % (style, "".join(parts))


def save_report(ref, mod, result, folder=None):
    folder = folder or reports_folder()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in "%s_vs_%s" % (ref.Label, mod.Label))
    path = os.path.join(folder, "%s_%s.html" % (safe, stamp))
    with open(path, "w", encoding="utf-8") as f:
        f.write(report_html(ref, mod, result))
    return path


def _solid(doc):
    shapes = [obj.Shape for obj in evaluate.visible_bodies(doc)]
    if not shapes:
        return None
    s = shapes[0]
    for t in shapes[1:]:
        s = s.fuse(t)
    return s


def geometry(ref, mod):
    """{volume/area of each, removed and added volume, and the removed/added shapes}."""
    a, b = _solid(ref), _solid(mod)
    out = {"ref_volume": a.Volume if a else 0.0, "mod_volume": b.Volume if b else 0.0,
           "ref_area": a.Area if a else 0.0, "mod_area": b.Area if b else 0.0,
           "removed": 0.0, "added": 0.0, "removed_shape": None, "added_shape": None}
    if a is not None and b is not None:
        removed, added = a.cut(b), b.cut(a)
        out.update(removed=removed.Volume, added=added.Volume, removed_shape=removed, added_shape=added)
    elif a is not None:
        out.update(removed=a.Volume, removed_shape=a)
    elif b is not None:
        out.update(added=b.Volume, added_shape=b)
    return out


class CompareWindow(QtWidgets.QDialog):
    def __init__(self):
        super().__init__(Gui.getMainWindow())
        self.setWindowTitle(TITLE)
        self.setObjectName("SWEvaluate_Compare")
        self.resize(720, 520)
        lay = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QFormLayout()
        self.ref = QtWidgets.QComboBox()
        self.ref.setObjectName("SWCompareReference")
        self.mod = QtWidgets.QComboBox()
        self.mod.setObjectName("SWCompareModified")
        top.addRow("Reference document:", self.ref)
        top.addRow("Modified document:", self.mod)
        lay.addLayout(top)
        self.run = QtWidgets.QPushButton("Run Comparison")
        self.run.setObjectName("SWCompareRun")
        self.run.clicked.connect(self.refresh)
        lay.addWidget(self.run, 0, QtCore.Qt.AlignLeft)
        self.tabs = QtWidgets.QTabWidget()
        self.docs = self._table(["Property", "Reference", "Modified"])
        self.feats = self._table(["Feature", "Kind", "Result", "Differences"])
        geo = QtWidgets.QWidget()
        glay = QtWidgets.QVBoxLayout(geo)
        self.geo = self._table(["Result", "Reference", "Modified"])
        glay.addWidget(self.geo, 1)
        self.show_diff = QtWidgets.QPushButton("Show Differences")
        self.show_diff.setObjectName("SWCompareShow")
        self.show_diff.setCheckable(True)
        self.show_diff.toggled.connect(self._overlay)
        glay.addWidget(self.show_diff, 0, QtCore.Qt.AlignLeft)
        self.tabs.addTab(self.docs, "Documents")
        self.tabs.addTab(self.feats, "Features")
        self.tabs.addTab(geo, "Geometry")
        self.bom = self._table(["Part", "Reference", "Modified", "Result"])
        self.pmi = self._table(["Dimension", "Reference", "Modified", "Result"])
        self.tabs.addTab(self.bom, "BOM")
        self.tabs.addTab(self.pmi, "3D PMI")
        lay.addWidget(self.tabs, 1)
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        buttons = QtWidgets.QHBoxLayout()
        self.save = QtWidgets.QPushButton("Save Report")
        self.save.setObjectName("SWCompareSave")
        self.save.clicked.connect(self._save)
        manager = QtWidgets.QPushButton("Report Manager...")
        manager.clicked.connect(report_manager)
        buttons.addWidget(self.save)
        buttons.addWidget(manager)
        buttons.addStretch(1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        lay.addLayout(buttons)
        self.saved = None
        self.overlay = evaluate.Overlay()
        self.result = None
        self._fill_documents()

    def _table(self, columns):
        t = QtWidgets.QTreeWidget()
        t.setHeaderLabels(columns)
        t.setRootIsDecorated(False)
        t.setAlternatingRowColors(True)
        return t

    def _fill_documents(self):
        names = [(d.Label, d.Name) for d in App.listDocuments().values()]
        for box in (self.ref, self.mod):
            box.clear()
            for label, name in names:
                box.addItem(label, name)
        if len(names) > 1:
            active = App.ActiveDocument.Name if App.ActiveDocument else names[-1][1]
            other = next(n for _l, n in names if n != active)
            self.ref.setCurrentIndex(self.ref.findData(other))
            self.mod.setCurrentIndex(self.mod.findData(active))

    def _docs(self):
        return App.getDocument(self.ref.currentData()), App.getDocument(self.mod.currentData())

    def refresh(self):
        self.show_diff.setChecked(False)
        if self.ref.count() < 1:
            self.summary.setText("Open the two documents to compare.")
            return
        ref, mod = self._docs()
        if ref is mod:
            self.summary.setText("Pick two different documents.")
            return
        rows = documents(ref, mod)
        self.docs.clear()
        for name, a, b, differs in rows:
            item = QtWidgets.QTreeWidgetItem([name, a, b])
            if differs:
                for col in range(3):
                    f = item.font(col)
                    f.setBold(True)
                    item.setFont(col, f)
            self.docs.addTopLevelItem(item)
        feats = features(ref, mod)
        self.feats.clear()
        for row in feats:
            self.feats.addTopLevelItem(QtWidgets.QTreeWidgetItem(list(row)))
        g = geometry(ref, mod)
        self.geo.clear()
        for label, a, b in (("Volume", g["ref_volume"], g["mod_volume"]), ("Surface area", g["ref_area"], g["mod_area"]),
                            ("Removed volume", g["removed"], ""), ("Added volume", "", g["added"])):
            cells = [label] + [("%.3f" % v) if isinstance(v, float) else v for v in (a, b)]
            self.geo.addTopLevelItem(QtWidgets.QTreeWidgetItem(cells))
        self.bom.clear()
        brows = bom_rows(ref, mod)
        for row in brows:
            self.bom.addTopLevelItem(QtWidgets.QTreeWidgetItem(list(row)))
        self.pmi.clear()
        prows = pmi_rows(ref, mod)
        for row in prows:
            self.pmi.addTopLevelItem(QtWidgets.QTreeWidgetItem(list(row)))
        for t in (self.docs, self.feats, self.geo, self.bom, self.pmi):
            for i in range(t.columnCount()):
                t.resizeColumnToContents(i)
        self.result = {"documents": rows, "features": feats, "geometry": g, "bom": brows, "pmi": prows}
        changed = sum(1 for r in feats if r[2] != SAME)
        from .evaluate import len_text
        self.summary.setText("%d document properties differ, %d features differ, %s removed and %s added."
                             % (sum(1 for r in rows if r[3]), changed, len_text(g["removed"], 3, 3, ref),
                                len_text(g["added"], 3, 3, ref)))

    def _save(self):
        if not self.result:
            self.refresh()
        if not self.result:
            return
        ref, mod = self._docs()
        try:
            self.saved = save_report(ref, mod, self.result)
            self.summary.setText("Report saved: %s" % self.saved)
        except Exception as error:
            self.summary.setText("The report could not be saved: %s" % error)

    def _overlay(self, on):
        self.overlay.clear()
        if not on or not self.result:
            return
        _ref, mod = self._docs()
        try:
            Gui.getDocument(mod.Name).ActiveView      # the modified document's view shows it
            Gui.ActiveDocument = Gui.getDocument(mod.Name)
        except Exception as _fw_err:
            _fw_log("compare.py:392", _fw_err)
        g = self.result["geometry"]
        if g["removed_shape"] is not None and g["removed"] > 1e-9:
            self.overlay.add(g["removed_shape"], (1.0, 0.0, 0.0), 0.4)
        if g["added_shape"] is not None and g["added"] > 1e-9:
            self.overlay.add(g["added_shape"], (0.0, 0.8, 0.0), 0.4)

    def closeEvent(self, event):
        self.overlay.clear()
        evaluate._OPEN.pop(type(self).__name__, None)
        super().closeEvent(event)


@evaluate.command("SWStyle_Compare", TITLE,
                  "Compares two open documents: their properties, features and geometry.")
def compare(tab=0):
    win = evaluate._OPEN.get(CompareWindow.__name__)
    if win is None or not win.isVisible():
        win = CompareWindow()
        evaluate._OPEN[CompareWindow.__name__] = win
    else:
        win._fill_documents()
    win.tabs.setCurrentIndex(tab)
    win.show()
    win.raise_()
    win.activateWindow()
    if tab and win.ref.count() > 1 and win.result is None:
        win.refresh()
    return win


class ReportManager(QtWidgets.QDialog):
    ""

    def __init__(self):
        super().__init__(Gui.getMainWindow())
        self.setWindowTitle("Report Manager")
        self.setObjectName("SWCompareReportManager")
        self.resize(560, 360)
        lay = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Reports folder:"))
        self.folder = QtWidgets.QLineEdit(reports_folder())
        self.folder.setReadOnly(True)
        row.addWidget(self.folder, 1)
        browse = QtWidgets.QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        lay.addLayout(row)
        self.list = QtWidgets.QTreeWidget()
        self.list.setObjectName("SWCompareReports")
        self.list.setHeaderLabels(["Report", "Date"])
        self.list.setRootIsDecorated(False)
        self.list.itemDoubleClicked.connect(lambda *_a: self._open())
        lay.addWidget(self.list, 1)
        buttons = QtWidgets.QHBoxLayout()
        for text, slot in (("Open", self._open), ("Delete", self._delete), ("Close", self.close)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        lay.addLayout(buttons)
        self.fill()

    def _browse(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Reports folder", self.folder.text())
        if path:
            App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks/Compare").SetString("ReportFolder", path)
            self.folder.setText(path)
            self.fill()

    def reports(self):
        folder = self.folder.text()
        files = [os.path.join(folder, n) for n in os.listdir(folder) if n.lower().endswith(".html")] \
            if os.path.isdir(folder) else []
        return sorted(files, key=os.path.getmtime, reverse=True)

    def fill(self):
        self.list.clear()
        for path in self.reports():
            when = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
            item = QtWidgets.QTreeWidgetItem([os.path.basename(path), when])
            item.setData(0, QtCore.Qt.UserRole, path)
            self.list.addTopLevelItem(item)
        self.list.resizeColumnToContents(0)

    def _current(self):
        item = self.list.currentItem()
        return item.data(0, QtCore.Qt.UserRole) if item else None

    def _open(self):
        path = self._current()
        if path:
            from PySide import QtGui
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    def _delete(self):
        path = self._current()
        if not path:
            return
        if QtWidgets.QMessageBox.question(self, "Report Manager", "Delete %s?" % os.path.basename(path)) \
                != QtWidgets.QMessageBox.Yes:
            return
        try:
            os.remove(path)
        except OSError as _fw_err:
            _fw_log("compare.py:497", _fw_err)
        self.fill()


def report_manager():
    win = evaluate._OPEN.get(ReportManager.__name__)
    if win is None or not win.isVisible():
        win = ReportManager()
        evaluate._OPEN[ReportManager.__name__] = win
    else:
        win.fill()
    win.show()
    win.raise_()
    return win


# ------------------------------------------------------------------ DrawCompare
def drawing_pages():
    """(label, page) for every drawing sheet of every open document."""
    out = []
    for doc in App.listDocuments().values():
        for obj in doc.Objects:
            if obj.TypeId == "TechDraw::DrawPage":
                out.append(("%s : %s" % (doc.Label, obj.Label), obj))
    return out


def page_image(page, width=1600):
    """The sheet drawn to a QImage, white paper, through its SVG export."""
    import tempfile
    from PySide import QtGui, QtSvg
    import TechDrawGui
    path = os.path.join(tempfile.mkdtemp(prefix="fwdrawcompare"), "page.svg")
    TechDrawGui.exportPageAsSvg(page, path)
    renderer = QtSvg.QSvgRenderer(path)
    size = renderer.defaultSize()
    height = max(1, int(width * size.height() / max(1, size.width())))
    image = QtGui.QImage(width, height, QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor("white"))
    painter = QtGui.QPainter(image)
    renderer.render(painter)
    painter.end()
    return image


def overlay_images(a, b):
    """(image, pixels only in a, pixels only in b): ink in both black, only in the reference red,
    only in the modified green."""
    from PySide import QtGui
    w, h = min(a.width(), b.width()), min(a.height(), b.height())
    out = QtGui.QImage(w, h, QtGui.QImage.Format_RGB32)
    out.fill(QtGui.QColor("white"))
    only_a = only_b = 0
    red, green, black = QtGui.qRgb(230, 0, 0), QtGui.qRgb(0, 170, 0), QtGui.qRgb(0, 0, 0)
    for y in range(h):
        for x in range(w):
            ia = QtGui.qGray(a.pixel(x, y)) < 200
            ib = QtGui.qGray(b.pixel(x, y)) < 200
            if ia and ib:
                out.setPixel(x, y, black)
            elif ia:
                out.setPixel(x, y, red)
                only_a += 1
            elif ib:
                out.setPixel(x, y, green)
                only_b += 1
    return out, only_a, only_b


class DrawCompareWindow(QtWidgets.QDialog):
    ""


    def __init__(self):
        super().__init__(Gui.getMainWindow())
        self.setWindowTitle("DrawCompare")
        self.setObjectName("SWDrawCompare")
        self.resize(900, 680)
        lay = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        self.ref = QtWidgets.QComboBox()
        self.mod = QtWidgets.QComboBox()
        self.pages = drawing_pages()
        for label, _p in self.pages:
            self.ref.addItem(label)
            self.mod.addItem(label)
        if len(self.pages) > 1:
            self.mod.setCurrentIndex(1)
        top.addWidget(QtWidgets.QLabel("Reference"))
        top.addWidget(self.ref, 1)
        top.addWidget(QtWidgets.QLabel("Modified"))
        top.addWidget(self.mod, 1)
        run = QtWidgets.QPushButton("Compare")
        run.clicked.connect(self.refresh)
        top.addWidget(run)
        lay.addLayout(top)
        self.view = QtWidgets.QLabel()
        self.view.setAlignment(QtCore.Qt.AlignCenter)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(self.view)
        scroll.setWidgetResizable(True)
        lay.addWidget(scroll, 1)
        self.summary = QtWidgets.QLabel("Open two drawings to compare." if len(self.pages) < 2 else "")
        lay.addWidget(self.summary)
        self.result = None

    def refresh(self):
        from PySide import QtGui
        if len(self.pages) < 2:
            return
        a, b = self.pages[self.ref.currentIndex()][1], self.pages[self.mod.currentIndex()][1]
        if a is b:
            self.summary.setText("Pick two different sheets.")
            return
        image, only_a, only_b = overlay_images(page_image(a, 800), page_image(b, 800))
        self.result = (only_a, only_b)
        self.view.setPixmap(QtGui.QPixmap.fromImage(image))
        self.summary.setText("The sheets match." if not (only_a or only_b) else
                             "Red: only in the reference (%d px). Green: only in the modified (%d px)." % (only_a, only_b))


def draw_compare():
    win = DrawCompareWindow()
    evaluate._OPEN[DrawCompareWindow.__name__] = win
    win.show()
    return win


class _TabCmd:
    def __init__(self, text, tip, tab):
        self.text, self.tip, self.tab = text, tip, tab

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": "TOOLS_COMPARE"}

    def IsActive(self):
        return True

    def Activated(self):
        if self.tab == "draw":
            draw_compare()
        elif self.tab is None:
            report_manager()
        else:
            compare(self.tab)


TAB_COMMANDS = (
    ("SWStyle_DrawCompare", "DrawCompare...", "Lays two drawing sheets over each other and shows the differences.", "draw"),
    ("SWStyle_CompareDocuments", "Documents...", "Compares the properties of two documents.", 0),
    ("SWStyle_CompareFeatures", "Features...", "Compares the features of two documents.", 1),
    ("SWStyle_CompareGeometry", "Geometry...", "Compares the geometry of two documents.", 2),
    ("SWStyle_CompareBOM", "BOM...", "Compares the parts and quantities of two documents.", 3),
    ("SWStyle_Compare3DPMI", "3D PMI...", "Compares the dimensions of two documents.", 4),
    ("SWStyle_CompareReportManager", "Report Manager...", "Lists the saved comparison reports.", None),
)


def register():
    if Gui.Command.get("SWStyle_Compare") is None:
        Gui.addCommand("SWStyle_Compare", evaluate._Cmd("SWStyle_Compare"))
    for name, text, tip, tab in TAB_COMMANDS:
        if Gui.Command.get(name) is None:
            Gui.addCommand(name, _TabCmd(text, tip, tab))
