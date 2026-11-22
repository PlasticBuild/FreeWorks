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

import os
import shutil

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import drawings as D
from .drawtdtools import MENU as TD_MENU

PARAM = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Drawings"



def _fw_xs(v):
    """v's XSource as its model(s) (drawviews.xsource: an assembly view's model parts read back as the model)."""
    from . import drawviews as DV
    return DV.xsource(v)

def _views(page):
    return D.views_of(page)


def picked_page_objects(page):
    return [o for o in Gui.Selection.getSelection() if o in page.Views]


# =========================================================================== Edit
def update_all_views(page):
    """Edit > Update All Views: every view on every sheet of the drawing made again from the model."""
    doc = page.Document
    try:
        from . import drawdocprops
        drawdocprops.release(doc)          # sheets held on open (auto-update off) follow again
    except Exception as _fw_err:
        _fw_log("drawmenus.py:58", _fw_err)
    n = 0
    for o in doc.Objects:
        if o.isDerivedFrom("TechDraw::DrawViewPart"):
            o.touch()
            n += 1
    doc.recompute()
    return n


# =========================================================================== View
DISPLAY = {"FreeWorks_DrawDisplayWireframe": "Wireframe", "FreeWorks_DrawDisplayHiddenVisible": "Hidden Lines Visible",
           "FreeWorks_DrawDisplayHiddenRemoved": "Hidden Lines Removed",
           "FreeWorks_DrawDisplayShadedEdges": "Shaded With Edges", "FreeWorks_DrawDisplayShaded": "Shaded"}


def set_style(style):
    from . import drawselect
    return drawselect.display_style(style)


def draft_quality(page, on=None):
    """Draft Quality HLR/HLV: the picked views (else all) drawn coarse (TechDraw's CoarseView)."""
    from . import drawselect
    views = drawselect.picked_views() or _views(page)
    if on is None:
        on = not all(getattr(v, "CoarseView", False) for v in views)
    for v in views:
        try:
            v.CoarseView = on
        except Exception as _fw_err:
            _fw_log("drawmenus.py:89", _fw_err)
    page.Document.recompute()
    return on


def select_tool():
    """Tools > Selection > Select: the pointer back to picking (a running sheet tool ends, as Esc does)."""
    ended = False
    try:
        from . import drawdimtools
        if drawdimtools.SMART:
            drawdimtools.SMART[0].done()
            ended = True
    except Exception as _fw_err:
        _fw_log("drawmenus.py:103", _fw_err)
    try:
        from . import drawhud
        if drawhud.ACTIVE:
            drawhud.ACTIVE[0].done()
            ended = True
    except Exception as _fw_err:
        _fw_log("drawmenus.py:110", _fw_err)
    return ended


def _picked_or_all(page):
    from . import drawselect
    return drawselect.picked_views() or _views(page)


def lightweight(page, on):
    """Edit > Lightweight / Resolve: the picked views (else all) made lightweight (drawn coarse, the view keeps an
    SWLightweight mark) or resolved (drawn in full, then updated)."""
    views = _picked_or_all(page)
    for v in views:
        if "SWLightweight" not in v.PropertiesList:
            v.addProperty("App::PropertyBool", "SWLightweight", "FreeCAD", "Lightweight view (Edit > Resolve)")
        v.SWLightweight = bool(on)
        try:
            v.CoarseView = bool(on)
        except Exception as _fw_err:
            _fw_log("drawmenus.py:130", _fw_err)
        if not on:
            try:
                v.touch()
            except Exception as _fw_err:
                _fw_log("drawmenus.py:135", _fw_err)
    page.Document.recompute()
    return views


def sheet_dxf(page):
    """The sheet as DXF text, as File > Save As DXF writes it."""
    import os
    import tempfile
    import TechDraw
    from . import drawdxf
    raw = os.path.join(tempfile.mkdtemp(), "techdraw.dxf")
    TechDraw.writeDXFPage(page, raw)
    out = os.path.join(tempfile.mkdtemp(), "sheet.dxf")
    drawdxf.convert(raw, out, drawdxf.DEFAULT_VERSION, 1.0, True, "TrueType")
    with open(out, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def copy_to_dwg(page):
    text = sheet_dxf(page)
    data = QtCore.QMimeData()
    data.setText(text)
    for kind in ("image/vnd.dxf", "application/dxf"):
        data.setData(kind, QtCore.QByteArray(text.encode("utf-8")))
    QtWidgets.QApplication.clipboard().setMimeData(data)
    return text


def sheet_svg(page):
    import os
    import tempfile
    import TechDrawGui
    out = os.path.join(tempfile.mkdtemp(), "sheet.svg")
    TechDrawGui.exportPageAsSvg(page, out)
    with open(out, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def copy_to_illustrator(page):
    text = sheet_svg(page)
    data = QtCore.QMimeData()
    data.setText(text)
    data.setData("image/svg+xml", QtCore.QByteArray(text.encode("utf-8")))
    QtWidgets.QApplication.clipboard().setMimeData(data)
    return text


def zoom_to_sheet(page):
    view = D.page_view(page)
    if view is None:
        return False
    w, h = D.sheet_size(page)
    view.fitInView(QtCore.QRectF(D.to_scene(0, h), D.to_scene(w, 0)).normalized(), QtCore.Qt.KeepAspectRatio)
    return True


def sheets(doc):
    return [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage"]


def step_sheet(page, step):
    """Previous Sheet / Next Sheet: the drawing's other sheet in front."""
    from . import drawsheet
    all_ = sheets(page.Document)
    if len(all_) < 2:
        return page
    nxt = all_[(all_.index(page) + step) % len(all_)]
    drawsheet.show_page(nxt)
    return nxt


ANNOTATION_TYPES = ("TechDraw::DrawViewDimension", "TechDraw::DrawViewBalloon", "TechDraw::DrawViewAnnotation",
                    "TechDraw::DrawRichAnno", "TechDraw::DrawLeaderLine", "TechDraw::DrawWeldSymbol",
                    "TechDraw::DrawTileWeld")


def annotations_of(page):
    out = []
    for o in page.Document.Objects:
        if o.TypeId in ANNOTATION_TYPES:
            out.append(o)
        elif o.TypeId == "TechDraw::DrawViewSymbol" and getattr(o, "SWAnnotation", "") not in (
                "", "Block", "AutoBorder", "SheetSketch", "Markup", "MarkupNote", "ZoneLines", "ViewArrow"):
            out.append(o)
    return out


def _flag(page, name):
    return bool(getattr(page, name, True))


def _set_flag(page, name, on):
    if name not in page.PropertiesList:
        page.addProperty("App::PropertyBool", name, "FreeCAD", "View > Hide/Show")
    setattr(page, name, bool(on))


def show_annotations(page, on=None):
    """View > Hide/Show > Annotations: every annotation on the sheet shown or hidden."""
    if on is None:
        on = not _flag(page, "SWShowAnnotations")
    _set_flag(page, "SWShowAnnotations", on)
    for o in annotations_of(page):
        try:
            o.ViewObject.Visibility = on
        except Exception as _fw_err:
            _fw_log("drawmenus.py:242", _fw_err)
    return on


def show_markups(page, on=None):
    from . import drawmarkup
    if on is None:
        on = not _flag(page, "SWShowMarkups")
    _set_flag(page, "SWShowMarkups", on)
    for o in drawmarkup.markups_of(page):
        try:
            o.ViewObject.Visibility = on
        except Exception as _fw_err:
            _fw_log("drawmenus.py:255", _fw_err)
    return on


def show_link_variables(page, on=None):
    ""

    from . import drawannot as DA
    if on is None:
        on = not bool(getattr(page, "SWShowLinkVariables", False))
    _set_flag(page, "SWShowLinkVariables", on)
    n = 0
    for o in list(page.Views):
        raw = getattr(o, "SWText", "") or ""
        if getattr(o, "SWAnnotation", "") != "Note" or "$PRP" not in raw:
            continue
        try:
            DA.redraw_note(o, raw if on else None)
            if "SWLinkedText" in o.PropertiesList:
                o.SWLinkedText = ""            # read again when the values come back
            n += 1
        except Exception as error:
            App.Console.PrintLog("FreeCAD: link variables: %s\n" % error)
    page.Document.recompute()
    return on


def show_grid(page, on=None):
    """View > Hide/Show > Grid: the sheet grid (TechDraw's page grid)."""
    vo = page.ViewObject
    if on is None:
        on = not bool(getattr(vo, "ShowGrid", False))
    try:
        vo.ShowGrid = on
    except Exception as _fw_err:
        _fw_log("drawmenus.py:290", _fw_err)
    return on


def zone_lines_svg(page):
    """Dashed zone lines across the sheet from its Automatic Border's zones (else 4 x 8)."""
    from . import drawmarkup
    w, h = D.sheet_size(page)
    rows, cols = 4, 8
    for o in drawmarkup.borders_of(page):
        try:
            rows, cols = (int(x) for x in o.SWBorderZones.split("x"))
        except Exception as _fw_err:
            _fw_log("drawmenus.py:303", _fw_err)
    m, t = 10.0, 5.0
    x0, y0, x1, y1 = m + t, m + t, w - m - t, h - m - t
    out = []
    for i in range(1, cols):
        x = x0 + (x1 - x0) * i / cols
        out.append('<line x1="%g" y1="%g" x2="%g" y2="%g"/>' % (x, y0, x, y1))
    for j in range(1, rows):
        y = y0 + (y1 - y0) * j / rows
        out.append('<line x1="%g" y1="%g" x2="%g" y2="%g"/>' % (x0, y, x1, y))
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="0 0 %g %g">'
            '<g stroke="#4080c0" stroke-width="0.18" stroke-dasharray="3 2" fill="none">%s</g></svg>'
            % (w, h, w, h, "".join(out)))


def zone_lines(page, on=None):
    ""

    doc = page.Document
    have = [o for o in page.Views if getattr(o, "SWAnnotation", "") == "ZoneLines"]
    if on is None:
        on = not have
    for o in have:
        try:
            page.removeView(o)
        except Exception as _fw_err:
            _fw_log("drawmenus.py:329", _fw_err)
        doc.removeObject(o.Name)
    if on:
        w, h = D.sheet_size(page)
        s = doc.addObject("TechDraw::DrawViewSymbol", "ZoneLines")
        s.Symbol = zone_lines_svg(page)
        page.addView(s)
        s.X, s.Y = w / 2.0, h / 2.0
        s.Label = "Zone Lines"
        s.addProperty("App::PropertyString", "SWAnnotation", "FreeCAD", "")
        s.SWAnnotation = "ZoneLines"
        try:
            s.LockPosition = True
        except Exception as _fw_err:
            _fw_log("drawmenus.py:343", _fw_err)
    doc.recompute()
    return on


# =========================================================================== File
def references(doc):
    """[(label, path)] of the files the drawing's views show."""
    out = []
    seen = {doc.Name}
    todo = []
    for o in doc.Objects:
        try:
            xs = _fw_xs(o)
        except Exception:
            xs = []
        for s in xs:
            d = s.Document
            if d.Name not in seen:
                seen.add(d.Name)
                out.append((d.Label, d.FileName))
                todo.append(d)
    todo.append(doc)

    while todo:
        d = todo.pop()
        try:
            deps = d.getDependentDocuments(False)
        except Exception:
            deps = []
        for x in deps:
            if x.Name not in seen and getattr(x, "FileName", ""):
                seen.add(x.Name)
                out.append((x.Label, x.FileName))
                todo.append(x)
    return out


class FindReferencesDialog(QtWidgets.QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWFindReferences")
        self.setWindowTitle("Find References")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Files referenced by %s:" % doc.Label, self))
        self.table = QtWidgets.QTableWidget(self)
        self.table.setObjectName("SWFindReferencesTable")
        refs = [(doc.Label, doc.FileName)] + references(doc)
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Name", "In Folder"])
        self.table.setRowCount(len(refs))
        for r, (name, path) in enumerate(refs):
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(os.path.basename(path) or name))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(os.path.dirname(path)))
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table)
        row = QtWidgets.QHBoxLayout()
        copy = QtWidgets.QPushButton("Copy List", self)
        copy.setObjectName("SWFindReferencesCopy")
        copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText("\n".join(p for _n, p in refs)))
        close = QtWidgets.QPushButton("Close", self)
        close.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(copy)
        row.addWidget(close)
        lay.addLayout(row)
        self.refs = refs
        self.resize(560, 260)


def pack_name(path, prefix="", suffix=""):
    stem, ext = os.path.splitext(os.path.basename(path))
    return prefix + stem + suffix + ext


def _relink(path, renames):
    ""

    import re
    import zipfile
    tmp = path + ".tmp"
    changed = False
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "Document.xml":
                text = data.decode("utf-8")
                for old, new in renames.items():
                    pat = r'(file|path)="([^"]*[\\/])?%s"' % re.escape(old)
                    text, n = re.subn(pat, lambda m: '%s="%s"' % (m.group(1), new), text)
                    changed = changed or n > 0
                data = text.encode("utf-8")
            zout.writestr(item, data)
    if changed:
        os.replace(tmp, path)
    else:
        os.remove(tmp)
    return changed


def pack_and_go(doc, folder, prefix="", suffix="", zip_path=None):
    """Pack and Go: the drawing and the files it references copied into folder (one folder, names with the
    prefix and suffix), each copy's references pointed at the other copies; with zip_path the copies go into
    that Zip file instead. Returns the paths written (the Zip file's members with zip_path)."""
    import tempfile
    import zipfile
    work = tempfile.mkdtemp(prefix="packandgo") if zip_path else folder
    os.makedirs(work, exist_ok=True)
    out = []
    renames = {}
    refs = references(doc)
    for _label, path in refs:
        if path and os.path.isfile(path):
            new = pack_name(path, prefix, suffix)
            shutil.copy2(path, os.path.join(work, new))
            out.append(os.path.join(work, new))
            renames[os.path.basename(path)] = new
    target = os.path.join(work, pack_name(doc.FileName or (doc.Label + ".FCStd"), prefix, suffix))
    doc.saveCopy(target)
    out.insert(0, target)
    for p in out:
        try:
            _relink(p, renames)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Pack and Go references of %s: %s\n" % (os.path.basename(p), error))
    if zip_path:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for p in out:
                z.write(p, os.path.basename(p))
        names = [os.path.basename(p) for p in out]
        shutil.rmtree(work, ignore_errors=True)
        return names
    return out


class PackAndGoDialog(QtWidgets.QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc
        self.setObjectName("SWPackAndGo")
        self.setWindowTitle("Pack and Go")
        lay = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(self)
        self.table.setObjectName("SWPackAndGoFiles")
        refs = [(doc.Label, doc.FileName or (doc.Label + ".FCStd"))] + references(doc)
        self.refs = refs
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Name", "In Folder", "Save to Name", "Save to Folder", "Size",
                                              "Type"])
        self.table.setRowCount(len(refs))
        for r, (name, path) in enumerate(refs):
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(os.path.basename(path) or name))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(os.path.dirname(path)))
            size = os.path.getsize(path) if path and os.path.isfile(path) else 0
            self.table.setItem(r, 4, QtWidgets.QTableWidgetItem("%d KB" % max(1, round(size / 1024.0))))
            self.table.setItem(r, 5, QtWidgets.QTableWidgetItem("Drawing" if r == 0 else "Part / Assembly"))
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table)
        f = QtWidgets.QGridLayout()
        self.to_folder = QtWidgets.QRadioButton("Save to folder:", self)
        self.to_folder.setObjectName("SWPackAndGoToFolder")
        self.to_folder.setChecked(True)
        self.folder = QtWidgets.QLineEdit(os.path.join(os.path.dirname(doc.FileName or os.path.expanduser("~")),
                                                       doc.Label + " Pack and Go"), self)
        self.folder.setObjectName("SWPackAndGoFolder")
        browse = QtWidgets.QPushButton("Browse...", self)
        browse.clicked.connect(self.browse)
        f.addWidget(self.to_folder, 0, 0)
        f.addWidget(self.folder, 0, 1)
        f.addWidget(browse, 0, 2)
        self.to_zip = QtWidgets.QRadioButton("Save to Zip file:", self)
        self.to_zip.setObjectName("SWPackAndGoToZip")
        self.zip = QtWidgets.QLineEdit(os.path.join(os.path.dirname(doc.FileName or os.path.expanduser("~")),
                                                    doc.Label + ".zip"), self)
        self.zip.setObjectName("SWPackAndGoZip")
        zbrowse = QtWidgets.QPushButton("Browse...", self)
        zbrowse.clicked.connect(self.browse_zip)
        f.addWidget(self.to_zip, 1, 0)
        f.addWidget(self.zip, 1, 1)
        f.addWidget(zbrowse, 1, 2)
        self.prefix = QtWidgets.QLineEdit(self)
        self.prefix.setObjectName("SWPackAndGoPrefix")
        self.suffix = QtWidgets.QLineEdit(self)
        self.suffix.setObjectName("SWPackAndGoSuffix")
        f.addWidget(QtWidgets.QLabel("Add prefix:", self), 2, 0)
        f.addWidget(self.prefix, 2, 1)
        f.addWidget(QtWidgets.QLabel("Add suffix:", self), 3, 0)
        f.addWidget(self.suffix, 3, 1)
        lay.addLayout(f)
        for w in (self.folder, self.zip):
            w.textChanged.connect(self.names)
        for w in (self.prefix, self.suffix):
            w.textChanged.connect(self.names)
        for b in (self.to_folder, self.to_zip):
            b.toggled.connect(self.names)
        self.names()
        bb = QtWidgets.QDialogButtonBox(self)
        save = bb.addButton("Save", QtWidgets.QDialogButtonBox.AcceptRole)
        save.setObjectName("SWPackAndGoSave")
        bb.addButton(QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.done_paths = []
        self.resize(620, 360)

    def names(self, *_):
        """Save to Name / Save to Folder follow the prefix, suffix and where the copies go."""
        zip_on = self.to_zip.isChecked()
        self.folder.setEnabled(not zip_on)
        self.zip.setEnabled(zip_on)
        where = os.path.basename(self.zip.text()) if zip_on else self.folder.text()
        for r, (name, path) in enumerate(self.refs):
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(pack_name(path or name, self.prefix.text(),
                                                                          self.suffix.text())))
            self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(where))

    def browse(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Pack and Go", self.folder.text())
        if d:
            self.folder.setText(d)

    def browse_zip(self):
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Pack and Go", self.zip.text(), "Zip file (*.zip)")
        if p:
            self.zip.setText(p)

    def save(self):
        if self.to_zip.isChecked():
            self.done_paths = pack_and_go(self.doc, "", self.prefix.text(), self.suffix.text(), self.zip.text())
        else:
            self.done_paths = pack_and_go(self.doc, self.folder.text(), self.prefix.text(), self.suffix.text())
        self.accept()


_PRINTER = []


def printer():
    """The printer set up by File > Page Setup (paper, orientation), kept for Print."""
    if not _PRINTER:
        from .drawprint import print_support
        QtPrintSupport = print_support()
        p = QtPrintSupport.QPrinter(QtPrintSupport.QPrinter.HighResolution)
        prm = App.ParamGet(PARAM)
        if prm.GetBool("PageLandscape", True):
            p.setPageOrientation(QtGui.QPageLayout.Landscape)
        _PRINTER.append(p)
    return _PRINTER[0]


def page_setup():
    try:
        from . import drawprint
        page = D.active_page()
        if page is not None:
            return bool(drawprint.PageSetupDialog(page.Document).exec_())
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Page Setup: %s\n" % error)
    from .drawprint import print_support
    QtPrintSupport = print_support()
    p = printer()
    dlg = QtPrintSupport.QPageSetupDialog(p, Gui.getMainWindow())
    dlg.setObjectName("SWPageSetup")
    if dlg.exec_():
        App.ParamGet(PARAM).SetBool("PageLandscape",
                                    p.pageLayout().orientation() == QtGui.QPageLayout.Landscape)
        return True
    return False


# =========================================================================== Insert
def add_hyperlink(page, url, obj=None, at=None):
    """Insert > Hyperlink: the picked note gets the link (blue, underlined; Ctrl+double-click opens it), or a
    new note with the link's text."""
    from . import drawblocks
    if obj is None:
        from . import drawannot as DA
        at = at or (D.sheet_size(page)[0] / 2.0, D.sheet_size(page)[1] / 2.0)
        body, reach = DA.note_svg(url, at)
        obj = DA.svg_symbol(page, "Note", body, reach, at, "Note%d" % (1 + len(
            [o for o in page.Document.Objects if getattr(o, "SWAnnotation", "") == "Note"])), "Note")
        obj.addProperty("App::PropertyString", "SWText", "FreeCAD", "note text")
        obj.SWText = url
    if "SWHyperlink" not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", "SWHyperlink", "FreeCAD", "hyperlink")
    obj.SWHyperlink = url
    if "<text" in obj.Symbol and 'fill="#0000ee"' not in obj.Symbol:
        obj.Symbol = obj.Symbol.replace("<text ", '<text fill="#0000ee" text-decoration="underline" ')
    page.Document.recompute()
    return obj


def open_hyperlink(obj):
    url = getattr(obj, "SWHyperlink", "")
    if url:
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromUserInput(url))
        return True
    return False


def _sheet_items(doc):
    """A sheet metal part's cut list items (smcutlist), else []."""
    try:
        from . import smcutlist
        box = smcutlist.update(doc) if smcutlist.sheet_bodies(doc) else None
    except Exception as _fw_err:
        _fw_log("drawmenus.py:651", _fw_err)
        return []
    return list(box.Items) if box is not None else []


def weldment_views(page):
    from . import drawtables
    out = []
    for v in _views(page):
        for s in _fw_xs(v):
            if drawtables.cut_list_items(s.Document) or _sheet_items(s.Document):
                out.append((v, s.Document))
                break
    return out


def cut_list_rows(part):
    """The Weldment Cut List rows of a weldment (or sheet metal) part."""
    from . import drawtables
    rows = [["ITEM NO.", "QTY.", "DESCRIPTION", "LENGTH"]]
    for n, (name, desc, count, mat) in enumerate(drawtables.cut_list_items(part), 1):
        d, _, length = desc.partition(", LENGTH ")
        rows.append([str(n), str(count), d, length])
    sheets = _sheet_items(part) if len(rows) == 1 else []
    if sheets:

        rows = [["ITEM NO.", "QTY.", "DESCRIPTION", "BOUNDING BOX LENGTH", "BOUNDING BOX WIDTH",
                 "SHEET METAL THICKNESS", "MATERIAL"]]
        for n, it in enumerate(sheets, 1):
            L, W, T = float(it.BoundingBoxLength or 0), float(it.BoundingBoxWidth or 0), float(it.SheetMetalThickness or 0)
            if not (L and W and T):
                L, W, T = _flat_size(it, (L, W, T))
            rows.append([str(n), "1", "Sheet", "%g" % L, "%g" % W, "%g" % T, it.Material or "-"])
    return rows


def _flat_size(item, have):
    """Bounding box length, width and thickness of a sheet metal body from its flat pattern view's shape, when the
    cut list item has not been computed (PC 11-11: 0 / 0 / 0)."""
    body = getattr(item, "Body", None)
    try:
        from . import smflatview
        fv = smflatview.flat_view(body.Document if body is not None else item.Document, create=False)
        bb = fv.Shape.BoundBox
        dims = sorted((bb.XLength, bb.YLength, bb.ZLength), reverse=True)
        t = have[2]
        if not t:
            from . import smflatten
            root = smflatten.root(body) if body is not None else None
            t = float(getattr(root, "Thickness", 0) or 0) or dims[2]
        return round(dims[0], 4), round(dims[1], 4), t
    except Exception as _fw_err:
        _fw_log("drawmenus.py:703", _fw_err)
        return have


def weldment_cut_list(page, view=None, at=None):
    """Insert > Tables > Weldment Cut List: ITEM NO., QTY., DESCRIPTION, LENGTH of the view's weldment."""
    from . import drawtables
    found = weldment_views(page)
    if view is not None:
        found = [f for f in found if f[0] is view] or found
    if not found:
        return None
    v, part = found[0]
    rows = cut_list_rows(part)
    w, h = D.sheet_size(page)
    at = at or (w - 80, h - 30)
    t = drawtables.make_table(page, rows, at, "Cut List%d" % (1 + len(
        [o for o in page.Document.Objects if getattr(o, "SWTable", "") == "CutList"])), "CutList",
        (60, 50, 220, 80) if len(rows[0]) == 4 else (40, 30, 50, 60, 60, 60, 60))
    t.addProperty("App::PropertyString", "SWTableView", "FreeCAD", "the view the table lists")
    t.SWTableView = v.Name
    t.addProperty("App::PropertyString", "SWTablePart", "FreeCAD", "the part document the cut list lists")
    t.SWTablePart = part.Name
    try:
        drawtables.remember_signature(t)
    except Exception as _fw_err:
        _fw_log("drawmenus.py:726", _fw_err)
    return t


# =========================================================================== Tools > Align (annotations)
def _box(o):
    from . import drawblocks
    x, y = float(o.X), float(o.Y)
    if o.TypeId == "TechDraw::DrawViewSymbol":
        hw, hh = drawblocks.symbol_box(o)
        pad = 5.0 if getattr(o, "SWAnnotation", "") else 0.0
        hw, hh = max(0.5, hw - pad), max(0.5, hh - pad)
    else:
        hw = hh = 0.0
    return x - hw, y - hh, x + hw, y + hh


def align(objs, how):
    """Tools > Align: Left, Right, Top, Bottom (edges), Horizontal, Vertical (centres) of the picked
    annotations; Space Evenly Across / Down."""
    objs = [o for o in objs if hasattr(o, "X") and hasattr(o, "Y")]
    if len(objs) < 2:
        return 0
    boxes = {o.Name: _box(o) for o in objs}
    if how == "Left":
        v = min(b[0] for b in boxes.values())
        for o in objs:
            o.X = float(o.X) + v - boxes[o.Name][0]
    elif how == "Right":
        v = max(b[2] for b in boxes.values())
        for o in objs:
            o.X = float(o.X) + v - boxes[o.Name][2]
    elif how == "Top":
        v = max(b[3] for b in boxes.values())
        for o in objs:
            o.Y = float(o.Y) + v - boxes[o.Name][3]
    elif how == "Bottom":
        v = min(b[1] for b in boxes.values())
        for o in objs:
            o.Y = float(o.Y) + v - boxes[o.Name][1]
    elif how == "Horizontal":
        v = float(objs[0].Y)
        for o in objs[1:]:
            o.Y = v
    elif how == "Vertical":
        v = float(objs[0].X)
        for o in objs[1:]:
            o.X = v
    elif how in ("Across", "Down"):
        k = "X" if how == "Across" else "Y"
        objs = sorted(objs, key=lambda o: float(getattr(o, k)))
        a, b = float(getattr(objs[0], k)), float(getattr(objs[-1], k))
        for i, o in enumerate(objs):
            setattr(o, k, a + (b - a) * i / (len(objs) - 1))
    elif how in ("TightAcross", "TightDown"):
        # Space Tightly: each one put against the one before, edge to edge, from the first
        k, lo, hi = ("X", 0, 2) if how == "TightAcross" else ("Y", 1, 3)
        objs = sorted(objs, key=lambda o: float(getattr(o, k)))
        edge = boxes[objs[0].Name][hi]
        for o in objs[1:]:
            b = boxes[o.Name]
            setattr(o, k, float(getattr(o, k)) + edge - b[lo])
            edge += b[hi] - b[lo]
    elif how == "BetweenLines":
        # Align Between Lines: the inner ones centred between the outermost two (left and right)
        objs = sorted(objs, key=lambda o: float(o.X))
        if len(objs) >= 3:
            mid = (float(objs[0].X) + float(objs[-1].X)) / 2.0
            for o in objs[1:-1]:
                o.X = mid
    elif how == "Stagger":
        # Stagger: every other one stepped out, so stacked dimension texts do not sit on each other
        objs = sorted(objs, key=lambda o: float(o.Y))
        step = max(3.5, max(boxes[o.Name][2] - boxes[o.Name][0] for o in objs) + 2.0)
        x0 = float(objs[0].X)
        for i, o in enumerate(objs):
            o.X = x0 + (step if i % 2 else 0.0)
    objs[0].Document.recompute()
    return len(objs)


ALIGN = {"FreeWorks_DrawAlignLeft": "Left", "FreeWorks_DrawAlignRight": "Right", "FreeWorks_DrawAlignTop": "Top",
         "FreeWorks_DrawAlignBottom": "Bottom", "FreeWorks_DrawAlignHorizontal": "Horizontal",
         "FreeWorks_DrawAlignVertical": "Vertical", "FreeWorks_DrawSpaceEvenlyAcross": "Across",
         "FreeWorks_DrawSpaceEvenlyDown": "Down",
         "FreeWorks_DrawSpaceTightlyAcross": "TightAcross", "FreeWorks_DrawSpaceTightlyDown": "TightDown",
         "FreeWorks_DrawAlignBetweenLines": "BetweenLines", "FreeWorks_DrawStagger": "Stagger",
         "FreeWorks_DrawAlignDimTextTop": "Top", "FreeWorks_DrawAlignDimTextBottom": "Bottom",
         "FreeWorks_DrawAlignDimTextLeft": "Left", "FreeWorks_DrawAlignDimTextRight": "Right"}
ALIGN_NAMES = {"Across": "Space Evenly Across", "Down": "Space Evenly Down", "TightAcross": "Space Tightly Across",
               "TightDown": "Space Tightly Down", "BetweenLines": "Align Between Lines", "Stagger": "Stagger"}


# =========================================================================== Tools > Align Drawing View
def picked_edge():
    """(view, edge) of a picked view edge, else (None, None)."""
    for s in Gui.Selection.getSelectionEx():
        o = s.Object
        if o.isDerivedFrom("TechDraw::DrawViewPart"):
            for sub in s.SubElementNames:
                if sub.startswith("Edge"):
                    try:
                        return o, o.getEdgeByIndex(int(sub[4:]))
                    except Exception as _fw_err:
                        _fw_log("drawmenus.py:830", _fw_err)
    return None, None


def align_edge(view, edge, horizontal=True):
    """Align Drawing View > Horizontal Edge / Vertical Edge: the view turned so the edge lies flat (upright)."""
    import math
    a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
    ang = math.degrees(math.atan2(b.y - a.y, b.x - a.x))
    target = 0.0 if horizontal else 90.0
    turn = target - ang
    while turn > 90:
        turn -= 180
    while turn < -90:
        turn += 180
    view.Rotation = (float(view.Rotation) + turn) % 360.0
    view.Document.recompute()
    return turn


def rotate_view(view, deg):
    view.Rotation = (float(view.Rotation) + deg) % 360.0
    view.Document.recompute()


# =========================================================================== the menus
S = None
DRAWING_MENUS = (
    ("&File", (
        ("New...", "SWStyle_NewDocument|Std_New"), ("Open...", "SWStyle_Open|Std_Open"), ("Open Recent", "fn:recent"),
        ("Close", "Std_CloseActiveWindow"), S,
        ("Save", "SWStyle_Save|Std_Save"), ("Save As...", "SWStyle_SaveAs|Std_SaveAs"),
        ("Save Sheet Format...", "FreeWorks_DrawSaveSheetFormat"), ("Save All", "Std_SaveAll"), S,
        ("Page Setup...", "FreeWorks_DrawPageSetup"), ("Print Preview...", "FreeWorks_DrawPrintPreview|SWStyle_PrintPreview|Std_PrintPreview"),
        ("Print...", "FreeWorks_DrawPrint|SWStyle_Print|Std_Print"), S,
        ("Publish to 3D Viewer", "SWStyle_PublishViewer"), S,
        ("Share", "SWStyle_Share"), ("Pack and Go...", "FreeWorks_DrawPackAndGo"), ("Send To...", "SWStyle_SendTo"), S,
        ("Reload...", "Std_Revert"), ("Find References...", "FreeWorks_DrawFindReferences"),
        ("Properties...", "Std_ProjectInfo"), S,
        ("Exit", "Std_Quit"),
    )),
    ("&Edit", (
        ("Undo", "Std_Undo"), ("Redo", "Std_Redo"), ("Repeat Last Command", "SWStyle_RepeatLastCommand|Std_RepeatLastCommand"), S,
        ("Select All", "FreeWorks_DrawSelectAll|Std_SelectAll"), ("Cut", "FreeWorks_DrawCut|Std_Cut"),
        ("Copy", "FreeWorks_DrawCopy|Std_Copy"), ("Paste", "FreeWorks_DrawPaste|Std_Paste"),
        ("Delete", "FreeWorks_DrawDelete|Std_Delete"), S,
        ("Rebuild", "SWStyle_Rebuild|Std_Refresh"), ("Update View", "FreeWorks_DrawUpdateView"),
        ("Update All Views", "FreeWorks_DrawUpdateAllViews"),
        ("Object", (("Display Content", "SWStyle_ObjectDisplayContent"), ("Display as Icon", "SWStyle_ObjectDisplayIcon"),
                    ("Reset Size", "SWStyle_ObjectResetSize"))), S,
        ("Sheet", "FreeWorks_DrawEditSheet"), ("Sheet Format", "FreeWorks_DrawEditSheetFormat"), S,
        ("Lightweight", "FreeWorks_DrawLightweight"), ("Resolve", "FreeWorks_DrawResolve"),
        ("Resolve Drawing", "FreeWorks_DrawResolveDrawing"), S,
        ("Properties...", "FreeWorks_DrawViewProperties"),
        ("Copy to DWG format", "FreeWorks_DrawCopyToDWG"), S,
        ("Copy to Adobe Illustrator", "FreeWorks_DrawCopyToIllustrator"),
    )),
    ("&View", (
        ("Redraw", "SWStyle_Redraw|TechDraw_RedrawPage"),
        ("Screen Capture", (("Image Capture", "Std_ViewScreenShot"),)), S,
        ("Display", (
            ("Wireframe", "FreeWorks_DrawDisplayWireframe"),
            ("Hidden Lines Visible", "FreeWorks_DrawDisplayHiddenVisible"),
            ("Hidden Lines Removed", "FreeWorks_DrawDisplayHiddenRemoved"),
            ("Shaded With Edges", "FreeWorks_DrawDisplayShadedEdges"), ("Shaded", "FreeWorks_DrawDisplayShaded"), S,
            ("Draft Quality HLR/HLV", "FreeWorks_DrawDraftQuality"), S,
            ("Tangent Edges Visible", "FreeWorks_DrawTangentVisible"),
            ("Tangent Edges With Font", "FreeWorks_DrawTangentWithFont"),
            ("Tangent Edges Removed", "FreeWorks_DrawTangentRemoved"),
            ("Tangent Edges With Hidden Ends", "FreeWorks_DrawTangentWithHiddenEnds"),
        )),
        ("Modify", (
            ("Zoom to Fit", "Std_ViewFitAll"), ("Zoom to Sheet", "FreeWorks_DrawZoomToSheet"),
            ("Zoom to Area", "FreeWorks_DrawZoomArea|Std_ViewBoxZoom"), ("Zoom In/Out", "Std_ViewZoomIn"),
            ("Zoom to Selection", "Std_ViewFitSelection"), ("Zoom to Markup View", "FreeWorks_DrawZoomToMarkup"),
            ("Zoom About Screen Center", "FreeWorks_DrawZoomAboutCenter"), ("Pan", "FreeWorks_DrawPan"),
            ("Rotate View...", "FreeWorks_DrawRotateView"),
            ("Previous View", "FreeWorks_DrawPreviousView"), ("3D Drawing View", "FreeWorks_Draw3DDrawingView"),
        )), S,
        ("Hide / Show", (
            ("Markups", "FreeWorks_DrawShowMarkups"), S,
            ("Grid", "FreeWorks_DrawShowGrid"), S,
            ("Annotations", "FreeWorks_DrawShowAnnotations"),
            ("Annotation Link Variables", "FreeWorks_DrawShowLinkVariables"),
            ("Hide/Show Annotations", "FreeWorks_DrawHideShowAnnotations"),
            ("Hidden Views", "FreeWorks_DrawShowHiddenViews"),
        )), S,
        ("Previous Sheet", "FreeWorks_DrawPreviousSheet"), ("Next Sheet", "FreeWorks_DrawNextSheet"), S,
        ("Toolbars", "fn:sw_toolbars"), ("Workspace", "fn:workspace"),
        ("User Interface", (("Zone Lines", "FreeWorks_DrawZoneLines"),)),
        ("Full Screen", "Std_MainFullscreen"),
    )),
    # Insert: the features thread's drawing Insert menu (features/45, MENU 33 order); its drawing-only entries



    ("&Tools", (
        ("FreeCAD Applications", (("FreeCAD Task Scheduler...", "SWStyle_TaskScheduler"),)),
        ("Lifecycle and Collaboration", (("Lock", "SWStyle_MakeReadOnly"), ("Unlock", "SWStyle_GetWriteAccess"),
                                         ("Reload from Server", "Std_Revert"), ("Properties", "Std_ProjectInfo"))),
        ("Xpress Products", (("Design Automation...", "SWStyle_DriveWorksXpress"),)), S,
        ("Selection", (("Select", "FreeWorks_DrawSelectTool"), ("Magnified Selection", "SWStyle_MagnifiedSelection"),
                       ("Box Selection", "SWStyle_BoxSelection"), ("Lasso Selection", "SWStyle_LassoSelection"),
                       ("Select over Geometry", "SWStyle_BoxSelection|Std_BoxSelection"),
                       ("Select All", "FreeWorks_DrawSelectAll|Std_SelectAll"),
                       ("Invert Selection", "SWStyle_InvertSelection"))), S,
        ("Compare", (
            ("DrawCompare...", "SWStyle_DrawCompare"), ("Documents...", "SWStyle_CompareDocuments"),
            ("Features...", "SWStyle_CompareFeatures"), ("Geometry...", "SWStyle_CompareGeometry"),
            ("BOM...", "SWStyle_CompareBOM"),
            ("3D PMI...", "SWStyle_Compare3DPMI"), S, ("Report Manager...", "SWStyle_CompareReportManager"),
        )),
        ("Find/Modify", (("Find and Replace Annotation...", "SWStyle_FindReplaceAnnotation"),)),
        ("Design Checker", (
            ("Check Active Document", "SWStyle_DesignCheckActive"),
            ("Check Against Existing File...", "SWStyle_DesignCheckFile"),
            ("Build Checks", "SWStyle_DesignCheckBuild"), ("Learn Checks Wizard", "SWStyle_DesignCheckLearn"),
        )),
        ("Spell Checker...", "FreeWorks_DrawSpellChecker"), ("Format Painter...", "FreeWorks_DrawFormatPainter"), S,
        ("Drawing Tools", TD_MENU), S,
        ("Replace Model...", "FreeWorks_DrawReplaceModel"),
        ("Align Drawing View", (
            ("Horizontal Edge", "FreeWorks_DrawAlignHorizontalEdge"),
            ("Vertical Edge", "FreeWorks_DrawAlignVerticalEdge"),
            ("Horizontal To Another View", "FreeWorks_DrawAlignHorizontalCenter"),
            ("Vertical To Another View", "FreeWorks_DrawAlignVerticalCenter"),
            ("Break Alignment", "FreeWorks_DrawBreakAlignment"), S,
            ("Horizontal to Sheet Clockwise", "FreeWorks_DrawRotateClockwise"),
            ("Horizontal to Sheet Counterclockwise", "FreeWorks_DrawRotateCounterclockwise"),
            ("Projected Angle", "FreeWorks_DrawAlignHorizontalEdge"), S,  # rough: the picked edge or axis flat
            ("Default Alignment", "FreeWorks_DrawDefaultAlignment"),
        )), S,
        ("Align", (
            ("Align Left", "FreeWorks_DrawAlignLeft"), ("Align Right", "FreeWorks_DrawAlignRight"),
            ("Align Top", "FreeWorks_DrawAlignTop"), ("Align Bottom", "FreeWorks_DrawAlignBottom"),

            # Evenly and Align Collinear by those names, the DimText rows in the same group; Align Parallel/Concentric
            # is under Tools > Dimensions there. Break Alignment (FreeCAD's own) stays, after Stagger.
            ("Align Horizontal", "FreeWorks_DrawAlignHorizontal"), ("Align Vertical", "FreeWorks_DrawAlignVertical"),
            ("Align Between Lines", "FreeWorks_DrawAlignBetweenLines"), S,
            ("Space Evenly Across", "FreeWorks_DrawSpaceEvenlyAcross"),
            ("Space Evenly Down", "FreeWorks_DrawSpaceEvenlyDown"),
            ("Space Tightly Across", "FreeWorks_DrawSpaceTightlyAcross"),
            ("Space Tightly Down", "FreeWorks_DrawSpaceTightlyDown"), S,
            ("Auto Arrange", "FreeWorks_DrawDimAutoArrange"),
            ("Space Evenly", "FreeWorks_DrawDimSpaceEvenly"),
            ("Align Collinear", "FreeWorks_DrawDimAlignCollinear"),
            ("Stagger", "FreeWorks_DrawStagger"), ("Break Alignment", "FreeWorks_DrawDimBreakAlignment"),
            ("Align DimText Top", "FreeWorks_DrawAlignDimTextTop"),
            ("Align DimText Bottom", "FreeWorks_DrawAlignDimTextBottom"),
            ("Align DimText Left", "FreeWorks_DrawAlignDimTextLeft"),
            ("Align DimText Right", "FreeWorks_DrawAlignDimTextRight"), S,
            ("Group", (("Group", "FreeWorks_DrawDimAlignParallel"),
                       ("Remove From Group", "FreeWorks_DrawDimBreakAlignment"),
                       ("Ungroup", "FreeWorks_DrawDimBreakAlignment"))),
        )), S,
        ("Sketch Entities", (
            ("Line", "FreeWorks_DrawSketchLine"), ("Corner Rectangle", "FreeWorks_DrawSketchRectangle"),
            ("Center Rectangle", "FreeWorks_DrawSketchCenterRectangle"),
            ("3 Point Corner Rectangle", "FreeWorks_DrawSketch3PointCornerRect"),
            ("3 Point Center Rectangle", "FreeWorks_DrawSketch3PointCenterRect"),
            ("Parallelogram", "FreeWorks_DrawSketchParallelogram"), ("Straight Slot", "FreeWorks_DrawSketchSlot"),
            ("Centerpoint Straight Slot", "FreeWorks_DrawSketchCenterSlot"),
            ("3 Point Arc Slot", "FreeWorks_DrawSketchArcSlot"),
            ("Centerpoint Arc Slot", "FreeWorks_DrawSketchCenterArcSlot"), ("Polygon", "FreeWorks_DrawSketchPolygon"),
            S, ("Circle", "FreeWorks_DrawSketchCircle"), ("Perimeter Circle", "FreeWorks_DrawSketchPerimeterCircle"),
            ("Centerpoint Arc", "FreeWorks_DrawSketchArc"), ("Tangent Arc", "FreeWorks_DrawSketchTangentArc"),
            ("3 Point Arc", "FreeWorks_DrawSketchThreePointArc"), S,
            ("Ellipse", "FreeWorks_DrawSketchEllipse"), ("Partial Ellipse", "FreeWorks_DrawSketchPartialEllipse"),
            ("Parabola", "FreeWorks_DrawSketchParabola"), ("Conic", "FreeWorks_DrawSketchConic"),
            ("Spline", "FreeWorks_DrawSketchSpline"), ("Style Spline", "FreeWorks_DrawSketchStyleSpline"),
            ("Point", "FreeWorks_DrawSketchPoint"), ("Centerline", "FreeWorks_DrawSketchCenterline"),
            ("Midpoint Line", "FreeWorks_DrawSketchMidpointLine"), ("Plane", "cat:Plane"),
        )),
        ("Sketch Tools", (
            ("Fillet...", "FreeWorks_DrawSketchFillet"), ("Chamfer...", "FreeWorks_DrawSketchChamfer"),
            ("Offset Entities...", "FreeWorks_DrawOffsetEntities"), ("Convert Entities", "FreeWorks_DrawConvertEntities"),
            ("Silhouette Entities", "cat:SilhouetteEntities"), ("Intersection Curve", "cat:IntersectionCurve"),
            ("Face Curves", "cat:FaceCurves"), S,
            ("Segment...", "FreeWorks_DrawSegment"), ("Trim", "FreeWorks_DrawTrimEntities"),
            ("Extend", "FreeWorks_DrawExtend"), ("Split Entities", "FreeWorks_DrawSplitEntities"),
            ("Jog Line", "FreeWorks_DrawJogLine"), ("Construction Geometry", "FreeWorks_DrawConstructionGeometry"),
            ("Make Path", "FreeWorks_DrawMakePath"), S,
            ("Mirror", "FreeWorks_DrawMirrorEntities"), ("Dissolve", "FreeWorks_DrawDissolve"),
            ("Dynamic Mirror", "FreeWorks_DrawDynamicMirror"), ("Stretch Entities...", "FreeWorks_DrawStretchEntities"),
            ("Move...", "FreeWorks_DrawMoveEntities"), ("Rotate...", "FreeWorks_DrawRotateEntities"),
            ("Scale...", "FreeWorks_DrawScaleEntities"), ("Copy...", "FreeWorks_DrawCopyEntities"),
            ("Replace Entity...", "cat:ReplaceEntity"),
            ("Linear Pattern...", "FreeWorks_DrawLinearSketchPattern"),
            ("Circular Pattern...", "FreeWorks_DrawCircularSketchPattern"), S,
            ("Edit Polygon...", "FreeWorks_DrawEditPolygon"), S,
            ("SketchXpert...", "cat:SketchXpert"),
            ("Align", (("Sketch", "cat:AlignSketch"), ("Align Grid/Origin...", "cat:AlignGridOrigin"))),
            ("Modify...", "FreeWorks_DrawModifySketch"), ("Close Sketch to Model", "cat:CloseSketchToModel"), S,
            ("Sketch Picture...", "cat:SketchPicture"), ("Area Hatch/Fill", "FreeWorks_DrawAreaHatch"),
        )),
        ("Sketch Settings", (
            ("Automatic Relations", "SWStyle_AutomaticRelations"), ("Automatic Solve", "SWStyle_AutomaticSolve"),
            ("Enable Snapping", "SWStyle_QuickSnapsToggle"), ("Shaded Sketch Contours", "cat:ShadedSketchContours"),
            ("No Solve Move", "cat:NoSolveMove"), ("Detach Segment on Drag", "cat:DetachSegmentOnDrag"),
            ("Override Dims on Drag/Move", "cat:OverrideDimsOnDrag"),
        )),
        ("Spline Tools", (
            ("Add Tangency Control", "cat:AddTangencyControl"), ("Add Curvature Control", "cat:AddCurvatureControl"),
            ("Insert Spline Point", "FreeWorks_DrawInsertSplinePoint"),
            ("Insert Control Vertex", "cat:InsertControlVertex"), ("Simplify Spline...", "cat:SimplifySpline"),
            ("Convert to Style Spline...", "cat:ConvertToStyleSpline"),
            ("Convert to Generic Spline...", "cat:ConvertToGenericSpline"), ("Convert to Spline...", "cat:ConvertToSpline"),
            ("Fit Spline...", "cat:FitSpline"), S,
            ("Show Spline Handles", "cat:ShowSplineHandles"), ("Show Spline Control Polygon", "cat:ShowSplineControlPolygon"),
            ("Show Inflection Points", "cat:ShowInflectionPoints"),
            ("Show Minimum Radius of Curvature", "cat:ShowMinimumRadius"), ("Show Curvature", "cat:ShowCurvatureCombs"),
        )),
        ("Dimensions", (
            ("Smart", "FreeWorks_DrawSmartDimension|FreeWorks_SmartDimension"), ("Horizontal", "FreeWorks_DrawHorizontalDimension|TechDraw_HorizontalDimension"),
            ("Vertical", "FreeWorks_DrawVerticalDimension|TechDraw_VerticalDimension"), ("Baseline", "FreeWorks_DrawBaselineDimension"),
            ("Chain", "FreeWorks_DrawChainDimension|TechDraw_ExtensionCreateHorizChainDimension"),
            ("Symmetric", "FreeWorks_DrawSymmetricDiameter"),
            ("Ordinate", "FreeWorks_DrawOrdinateDimension"),
            ("Horizontal Ordinate", "FreeWorks_DrawHorizontalOrdinate"),
            ("Vertical Ordinate", "FreeWorks_DrawVerticalOrdinate"),
            ("Angular Running Dimension", "FreeWorks_DrawAngularRunning"),
            ("Path Length", "TechDraw_ExtensionArcLengthAnnotation"),
            ("Chamfer", "FreeWorks_DrawChamferDimension"), S,
            ("Attach Dimensions", "TechDraw_DimensionRepair"),
            ("Align Collinear/Radial", "FreeWorks_DrawDimAlignCollinear"),
            ("Align Parallel/Concentric", "FreeWorks_DrawDimAlignParallel"),
            ("Dangling Annotations...", "FreeWorks_DrawDanglingAnnotations"), S,
            ("Autodimension...", "FreeWorks_DrawAutodimension"),
        )),
        ("Relations", (
            ("Add...", "FreeWorks_DrawAddRelation"), ("Display/Delete...", "FreeWorks_DrawDisplayDeleteRelations"),
            ("Scan Equal...", "FreeWorks_DrawScanEqual"), ("Constrain All", "FreeWorks_DrawConstrainAll"),
            ("Quick Snaps", "FreeWorks_DrawQuickSnaps"),
        )),
        ("Block", (
            ("Make", "FreeWorks_DrawMakeBlock"), ("Edit", "FreeWorks_DrawEditBlock"),
            ("Insert...", "FreeWorks_DrawInsertBlock"), ("Add/Remove Entities", "FreeWorks_DrawBlockAddRemove"),
            ("Rebuild", "FreeWorks_DrawRebuildBlock"), ("Save...", "FreeWorks_DrawSaveBlock"),
            ("Explode", "FreeWorks_DrawExplodeBlock"),
        )), S,
        ("Large Assembly Settings", "SWStyle_LargeAssemblyMode"), S,
        ("Macro", (("Edit...", "SWStyle_MacroEdit"), ("New...", "SWStyle_MacroNew"), ("Record", "Std_DlgMacroRecord"),
                   ("Run...", "SWStyle_MacroRun"), ("Stop", "SWStyle_MacroStop"), ("Macros...", "Std_DlgMacroExecute"))), S,   # extapps91
        ("Evaluate", (("Measure...", "SWStyle_Measure|Std_Measure"), ("Markup View", "FreeWorks_DrawShowMarkups"), ("Section Properties...", "FreeWorks_DrawSectionProperties"),
                      ("Performance Evaluation", "cat:PerformanceEvaluation"),
                      ("Previous Release Check", "SWStyle_PreviousReleaseCheck"))), S,
        ("Add-Ins...", "SWStyle_AddIns|Std_AddonMgr"), ("Save/Restore Settings...", "SWStyle_SaveRestoreSettings"),
        ("Customize...", "Std_DlgCustomize"), ("Options...", "SWStyle_Options|Std_DlgPreferences"),
    )),
)


def command_for(target):
    """The first of "A|B" alternatives that FreeCAD has (SWStyle_ commands come from the interface)."""
    have = Gui.listCommands()
    for t in target.split("|"):
        if t.startswith("cat:"):
            for n in _catalog_natives(t[4:]):
                if n in have:
                    return n
        elif t in have:
            return t
    return None


def _catalog_natives(key):
    """The commands the CommandManager catalog runs for key (the part menus' entries: "cat:Key" here)."""
    try:
        from . import catalog
        for c in getattr(catalog, "_ALL", ()):
            if c.key == key:
                return list(c.natives)
    except Exception as _fw_err:
        _fw_log("drawmenus.py:1100", _fw_err)
    return []


def menu_commands():
    """Every FreeCAD command DRAWING_MENUS names, "A|B" as written (for the checks)."""
    out = []

    def walk(entries):
        for e in entries:
            if e is None:
                continue
            label, target = e
            if isinstance(target, (tuple, list)):
                walk(target)
            elif not target.startswith("fn:"):
                out.append(target)
    for _title, entries in DRAWING_MENUS:
        walk(entries)
    return out


# =========================================================================== commands
COMMANDS = {
    "FreeWorks_DrawSelectTool": ("Select", "edit-select-all",
                                 "Back to picking: ends the sheet tool that is running (Smart Dimension, Zoom to Area)."),
    "FreeWorks_DrawLightweight": ("Lightweight", "TechDraw_View",
                                  "Makes the picked views (else all) lightweight: drawn coarse, quicker to work with."),
    "FreeWorks_DrawResolve": ("Resolve", "TechDraw_View",
                              "Resolves the picked lightweight views (else all): drawn in full again."),
    "FreeWorks_DrawCopyToDWG": ("Copy to DWG format", "TechDraw_ExportPageDXF",
                                "Copies the sheet to the clipboard as a DXF drawing, to paste into a 2D CAD program."),
    "FreeWorks_DrawCopyToIllustrator": ("Copy to Adobe Illustrator", "TechDraw_ExportPageSVG",
                                        "Copies the sheet to the clipboard as vector art (SVG)."),
    "FreeWorks_DrawUpdateAllViews": ("Update All Views", "TechDraw_View", "Updates every view on every sheet."),
    "FreeWorks_DrawDraftQuality": ("Draft Quality HLR/HLV", "TechDraw_View", "Draws the views coarse, faster."),
    "FreeWorks_DrawZoomToSheet": ("Zoom to Sheet", "TechDraw_View", "Zooms to show the whole sheet."),
    "FreeWorks_DrawPreviousSheet": ("Previous Sheet", "TechDraw_PageDefault", "Shows the previous sheet."),
    "FreeWorks_DrawNextSheet": ("Next Sheet", "TechDraw_PageDefault", "Shows the next sheet."),
    "FreeWorks_DrawShowAnnotations": ("Annotations", "TechDraw_Annotation", "Shows or hides the annotations."),
    "FreeWorks_DrawHideShowAnnotations": ("Hide/Show Annotations", "TechDraw_Annotation",
                                          "Hidden annotations are drawn faint: click one to hide or show it."),
    "FreeWorks_DrawShowMarkups": ("Markups", "TechDraw_Annotation", "Shows or hides the markups."),
    "FreeWorks_DrawShowLinkVariables": ("Annotation Link Variables", "TechDraw_Annotation",
                                        "Shows the text expressions of linked notes ($PRP...) instead of their values."),
    "FreeWorks_DrawShowGrid": ("Grid", "TechDraw_PageDefault", "Shows or hides the sheet grid."),
    "FreeWorks_DrawZoneLines": ("Zone Lines", "TechDraw_PageTemplate", "Shows or hides the sheet's zone lines."),
    "FreeWorks_DrawFindReferences": ("Find References...", "TechDraw_View", "Lists the files the drawing uses."),
    "FreeWorks_DrawPackAndGo": ("Pack and Go...", "TechDraw_View",
                                "Copies the drawing and the files it uses into one folder."),
    "FreeWorks_DrawPageSetup": ("Page Setup...", "TechDraw_PageDefault", "Paper and orientation for printing."),
    "FreeWorks_DrawHyperlink": ("Hyperlink...", "TechDraw_Annotation", "Adds a hyperlink to a note."),
    "FreeWorks_DrawWeldmentCutList": ("Weldment Cut List", "TechDraw_Spreadsheet",
                                      "Adds the weldment's cut list table."),
    "FreeWorks_DrawAlignHorizontalEdge": ("Horizontal Edge", "TechDraw_View",
                                          "Turns the view so the picked edge is horizontal."),
    "FreeWorks_DrawAlignVerticalEdge": ("Vertical Edge", "TechDraw_View",
                                        "Turns the view so the picked edge is vertical."),
    "FreeWorks_DrawRotateClockwise": ("Horizontal to Sheet Clockwise", "TechDraw_View",
                                      "Turns the picked view 90 degrees clockwise."),
    "FreeWorks_DrawRotateCounterclockwise": ("Horizontal to Sheet Counterclockwise", "TechDraw_View",
                                             "Turns the picked view 90 degrees counterclockwise."),
}
for _n, _s in DISPLAY.items():
    COMMANDS[_n] = (_s, "TechDraw_View", "%s on the picked views (all views when none is picked)." % _s)
for _n, _h in ALIGN.items():
    COMMANDS[_n] = (("Align DimText " + _h) if "DimText" in _n else ALIGN_NAMES.get(_h, "Align " + _h),
                    "TechDraw_Annotation", "Lines up the picked annotations.")

TOGGLES = {"FreeWorks_DrawShowAnnotations": "SWShowAnnotations", "FreeWorks_DrawShowMarkups": "SWShowMarkups"}


def save_first(doc, what):
    ""
    r = QtWidgets.QMessageBox.question(Gui.getMainWindow(), what,
                                       "%s needs the drawing saved. Save it now?" % what,
                                       QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Cancel,
                                       QtWidgets.QMessageBox.Save)
    if r != QtWidgets.QMessageBox.Save:
        return False
    try:
        Gui.setActiveDocument(doc.Name)
        if D.temp_path(doc):
            return bool(D.save_as_first(doc)) and not D.temp_path(doc)   # a new drawing: its first Save
        return D.save_model(doc)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s: %s\n" % (what, error))
    return bool(doc.FileName)


class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.pixmap, self.tip = COMMANDS[name]

    def GetResources(self):
        r = {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": D.pixmap(self.pixmap)}
        if self.name in TOGGLES or self.name in ("FreeWorks_DrawShowGrid", "FreeWorks_DrawZoneLines",
                                                 "FreeWorks_DrawShowLinkVariables"):
            r["Checkable"] = True
        return r

    def IsActive(self):
        page = D.active_page()
        if page is None or D.busy() or not D.sheet_shown(page):
            return False
        n = self.name
        if n in ("FreeWorks_DrawPreviousSheet", "FreeWorks_DrawNextSheet"):
            return len(sheets(page.Document)) > 1
        if n in ALIGN:
            return len(picked_page_objects(page)) >= 2
        if n in ("FreeWorks_DrawAlignHorizontalEdge", "FreeWorks_DrawAlignVerticalEdge"):
            return picked_edge()[0] is not None
        if n in ("FreeWorks_DrawRotateClockwise", "FreeWorks_DrawRotateCounterclockwise"):
            from . import drawselect
            return bool(drawselect.picked_views())
        if n == "FreeWorks_DrawWeldmentCutList":
            return bool(weldment_views(page))
        if n in ("FreeWorks_DrawUpdateAllViews", "FreeWorks_DrawDraftQuality") or n in DISPLAY:
            return bool(_views(page))
        if n == "FreeWorks_DrawLightweight":
            return any(not getattr(v, "SWLightweight", False) for v in _picked_or_all(page))
        if n == "FreeWorks_DrawResolve":
            return any(getattr(v, "SWLightweight", False) for v in _picked_or_all(page))
        return True

    def Activated(self, checked=None):
        page = D.active_page()
        if page is None:
            return
        doc = page.Document
        n = self.name
        if n in ("FreeWorks_DrawFindReferences", "FreeWorks_DrawPackAndGo") and not doc.FileName \
                and not save_first(doc, self.GetResources()["MenuText"].replace("&", "").rstrip(".")):
            return
        if n in DISPLAY:
            set_style(DISPLAY[n])
        elif n == "FreeWorks_DrawUpdateAllViews":
            update_all_views(page)
        elif n == "FreeWorks_DrawDraftQuality":
            draft_quality(page)
        elif n == "FreeWorks_DrawSelectTool":
            select_tool()
        elif n == "FreeWorks_DrawLightweight":
            doc.openTransaction("Lightweight")
            try:
                lightweight(page, True)
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
        elif n == "FreeWorks_DrawResolve":
            doc.openTransaction("Resolve")
            try:
                lightweight(page, False)
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
        elif n == "FreeWorks_DrawCopyToDWG":
            copy_to_dwg(page)
        elif n == "FreeWorks_DrawCopyToIllustrator":
            copy_to_illustrator(page)
        elif n == "FreeWorks_DrawZoomToSheet":
            zoom_to_sheet(page)
        elif n == "FreeWorks_DrawPreviousSheet":
            step_sheet(page, -1)
        elif n == "FreeWorks_DrawNextSheet":
            step_sheet(page, 1)
        elif n == "FreeWorks_DrawShowAnnotations":
            show_annotations(page)
        elif n == "FreeWorks_DrawHideShowAnnotations":
            from . import drawattach
            drawattach.hide_show(page)
        elif n == "FreeWorks_DrawShowMarkups":
            show_markups(page)
        elif n == "FreeWorks_DrawShowGrid":
            show_grid(page)
        elif n == "FreeWorks_DrawShowLinkVariables":
            show_link_variables(page)
        elif n == "FreeWorks_DrawZoneLines":
            zone_lines(page)
        elif n == "FreeWorks_DrawFindReferences":
            FindReferencesDialog(doc).exec_()
        elif n == "FreeWorks_DrawPackAndGo":
            PackAndGoDialog(doc).exec_()
        elif n == "FreeWorks_DrawPageSetup":
            page_setup()
        elif n == "FreeWorks_DrawHyperlink":
            picked = [o for o in picked_page_objects(page) if getattr(o, "SWText", None) is not None]
            url, ok = QtWidgets.QInputDialog.getText(Gui.getMainWindow(), "Hyperlink", "Address:",
                                                     text=getattr(picked[0], "SWHyperlink", "") if picked else "")
            if ok and url.strip():
                doc.openTransaction("Hyperlink")
                try:
                    add_hyperlink(page, url.strip(), picked[0] if picked else None)
                except BaseException:
                    try:
                        doc.abortTransaction()
                    except Exception:
                        pass
                    raise
                doc.commitTransaction()
        elif n == "FreeWorks_DrawWeldmentCutList":
            from . import drawtables
            D._show(drawtables.WeldmentCutListPanel(page))
        elif n in ALIGN:
            doc.openTransaction(COMMANDS[n][0])
            try:
                align(picked_page_objects(page), ALIGN[n])
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
        elif n in ("FreeWorks_DrawAlignHorizontalEdge", "FreeWorks_DrawAlignVerticalEdge"):
            v, e = picked_edge()
            if v is not None:
                doc.openTransaction(COMMANDS[n][0])
                try:
                    align_edge(v, e, n.endswith("HorizontalEdge"))
                except BaseException:
                    try:
                        doc.abortTransaction()
                    except Exception:
                        pass
                    raise
                doc.commitTransaction()
        elif n in ("FreeWorks_DrawRotateClockwise", "FreeWorks_DrawRotateCounterclockwise"):
            from . import drawselect
            doc.openTransaction(COMMANDS[n][0])
            try:
                for v in drawselect.picked_views():
                    rotate_view(v, -90.0 if n.endswith("Clockwise") and "Counter" not in n else 90.0)
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()


class _HyperlinkClick(QtCore.QObject):
    """Ctrl+double-click on a note with a hyperlink opens it."""

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False          # a stale PySide wrapper can arrive here
        try:
            if event.type() == QtCore.QEvent.MouseButtonDblClick and \
                    QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ControlModifier:
                page = D.active_page()
                view = D.page_view(page) if page is not None else None
                if view is not None and obj is view.viewport():
                    from . import drawblocks
                    p = D.to_sheet(view.mapToScene(event.position().toPoint()))
                    o = drawblocks.symbol_at(page, p)
                    if o is not None and open_hyperlink(o):
                        return True
        except Exception as _fw_err:
            _fw_log("drawmenus.py:1327", _fw_err)
        return False


_FILTER = []


def register():
    try:
        from . import drawprint
        drawprint.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: drawing print: %s\n" % error)
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
    try:
        from . import drawrotate            # View > Modify > Rotate View (Rotate Drawing View dialog)
        drawrotate.install()
        from . import drawmodify            # Sketch Tools > Modify... (Modify Sketch dialog)
        drawmodify.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Rotate View: %s\n" % error)
    try:
        from . import drawlineformat        # the Line Format toolbar on a drawing
        drawlineformat.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: drawing Line Format: %s\n" % error)
    try:
        from . import drawdimlines          # Hide Dimension Line / Hide Extension Line
        drawdimlines.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: hidden dimension lines: %s\n" % error)
    try:
        from . import drawpartcfg           # a part's configurations in its drawing views
        drawpartcfg.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: part configurations in drawings: %s\n" % error)
    try:
        from . import drawrcmore            # Show in Exploded / Collapsed State on a view's right-click
        drawrcmore.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: view right-click: %s\n" % error)
    try:
        from . import drawtemplates          # Save As > Drawing / Part / Assembly Templates
        drawtemplates.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: document templates: %s\n" % error)
    try:
        from . import drawlibrary            # Design Library annotations dragged onto a sheet
        drawlibrary.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: design library on drawings: %s\n" % error)
    try:
        from . import drawmaint              # changed dimensions coloured on open (Options > Colors)
        drawmaint.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: changed dimensions: %s\n" % error)
    if not _FILTER:
        _FILTER.append(_HyperlinkClick())
        try:
            from . import events            # the add-on's one application filter
            events.register("draw.hyperlink", (QtCore.QEvent.MouseButtonDblClick,), _FILTER[0].eventFilter)
        except ImportError:
            QtWidgets.QApplication.instance().installEventFilter(_FILTER[0])
