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
from PySide import QtCore, QtGui, QtWidgets

from . import drawings as D

PARAM = "User parameter:BaseApp/Preferences/Mod/FreeWorks/DrawPrint"
META = "FreeWorks:PageSetup"
COLORS = ("Automatic", "Color / Gray scale", "Black and white")
PAPERS = (("Letter", QtGui.QPageSize.Letter), ("Legal", QtGui.QPageSize.Legal), ("Tabloid", QtGui.QPageSize.Tabloid),
          ("A4", QtGui.QPageSize.A4), ("A3", QtGui.QPageSize.A3), ("A2", QtGui.QPageSize.A2),
          ("A1", QtGui.QPageSize.A1), ("A0", QtGui.QPageSize.A0), ("B (ANSI)", QtGui.QPageSize.AnsiB),
          ("C (ANSI)", QtGui.QPageSize.AnsiC), ("D (ANSI)", QtGui.QPageSize.AnsiD),
          ("E (ANSI)", QtGui.QPageSize.AnsiE))
RANGES = ("All", "Current sheet", "Current screen image", "Sheets", "Selection")
DEFAULT = {"fit": True, "scale": 100, "high": True, "paper": "Letter", "color": "Automatic",
           "landscape": True}
ASK = {}           # checks answer the file dialog here: "file"
SAVE_PDF = "Save as PDF"     # the printer list's own entry, as the part's Print box (filecmds.SAVE_PDF): needs no printer


def print_support():
    """Qt's print module (FreeCAD's PySide shim leaves it out)."""
    try:
        from PySide import QtPrintSupport
        return QtPrintSupport
    except ImportError:
        pass
    try:
        from PySide6 import QtPrintSupport
        return QtPrintSupport
    except ImportError:
        from PySide2 import QtPrintSupport
        return QtPrintSupport


def pages(doc):
    from . import drawsheet
    return drawsheet.pages(doc)      # in the sheet order


# =========================================================================== settings
def system_settings():
    prm = App.ParamGet(PARAM)
    try:
        s = json.loads(prm.GetString("Settings", "") or "{}")
    except Exception:
        s = {}
    out = dict(DEFAULT)
    out.update(s)
    return out


def set_system_settings(s):
    App.ParamGet(PARAM).SetString("Settings", json.dumps(s))


def doc_setup(doc):
    try:
        return json.loads(dict(doc.Meta or {}).get(META, "") or "{}")
    except Exception as _fw_err:
        _fw_log("drawprint.py:88", _fw_err)
        return {}


def set_doc_setup(doc, setup):
    meta = dict(doc.Meta or {})
    meta[META] = json.dumps(setup)
    doc.Meta = meta


def settings_for(page):
    """What Page Setup says for page: the document's own settings (per sheet when Different settings for each
    sheet is on) when Use this document's settings is on, else the system's."""
    setup = doc_setup(page.Document)
    if not setup.get("use_doc"):
        return system_settings()
    out = dict(DEFAULT)
    out.update(setup.get("default", {}))
    if setup.get("per_sheet"):
        out.update(setup.get("sheets", {}).get(page.Label, {}))
    return out


def margins():
    prm = App.ParamGet(PARAM)
    if prm.GetBool("PrinterMargins", True):
        return None
    return tuple(prm.GetFloat(k, 6.35) for k in ("Top", "Bottom", "Left", "Right"))


def parse_sheets(text, n):
    ""
    out = []
    for part in str(text).replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a, b = [int(x) for x in part.split("-", 1)]
                out += [i - 1 for i in range(min(a, b), max(a, b) + 1)]
            else:
                out.append(int(part) - 1)
        except ValueError:
            continue
    seen = []
    for i in out:
        if 0 <= i < n and i not in seen:
            seen.append(i)
    return seen


# =========================================================================== Header/Footer
TOKENS = (("File name", "&f"), ("Sheet name", "&s"), ("Page number", "&p"), ("Number of pages", "&n"),
          ("Date", "&d"), ("Time", "&t"))


def header_footer(doc):
    """Print > Header/Footer...: the drawing's header and footer text (empty: none)."""
    hf = doc_setup(doc).get("hf", {})
    return {"header": str(hf.get("header", "")), "footer": str(hf.get("footer", ""))}


def set_header_footer(doc, header, footer):
    setup = doc_setup(doc)
    setup["hf"] = {"header": header, "footer": footer}
    set_doc_setup(doc, setup)


def expand(text, doc, page, n, total):
    import datetime
    import os
    now = datetime.datetime.now()
    name = os.path.basename(getattr(doc, "FileName", "") or "") or (doc.Label or doc.Name)
    for tok, val in (("&f", name), ("&s", page.Label if page is not None else ""), ("&p", str(n)),
                     ("&n", str(total)), ("&d", now.strftime("%x")), ("&t", now.strftime("%X"))):
        text = text.replace(tok, val)
    return text


def draw_header_footer(painter, area, doc, page, n, total):
    """The header at the top and the footer at the bottom of the printed page, centred."""
    hf = header_footer(doc)
    if not (hf["header"] or hf["footer"]):
        return False
    painter.save()
    f = QtGui.QFont("Arial")
    f.setPixelSize(max(8, int(area.height() / 90)))
    painter.setFont(f)
    painter.setPen(QtGui.QPen(QtCore.Qt.black))
    for key, flag in (("header", QtCore.Qt.AlignTop), ("footer", QtCore.Qt.AlignBottom)):
        if hf[key]:
            painter.drawText(area, int(flag | QtCore.Qt.AlignHCenter), expand(hf[key], doc, page, n, total))
    painter.restore()
    return True


class HeaderFooterDialog(QtWidgets.QDialog):
    """Header/Footer: the text printed at the top and the bottom of each page (&f file, &s sheet, &p page,
    &n pages, &d date, &t time)."""

    def __init__(self, doc, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc
        self.setObjectName("SWHeaderFooter")
        self.setWindowTitle("Header/Footer")
        hf = header_footer(doc)
        lay = QtWidgets.QFormLayout(self)
        self.header = QtWidgets.QLineEdit(hf["header"], self)
        self.header.setObjectName("SWHeaderText")
        self.footer = QtWidgets.QLineEdit(hf["footer"], self)
        self.footer.setObjectName("SWFooterText")
        lay.addRow("Header:", self.header)
        lay.addRow("Footer:", self.footer)
        row = QtWidgets.QHBoxLayout()
        self.insert = QtWidgets.QComboBox(self)
        self.insert.setObjectName("SWHeaderFooterInsert")
        self.insert.addItem("Insert...")
        self.insert.addItems([n for n, _ in TOKENS])
        self.insert.activated.connect(self.put)
        row.addWidget(self.insert)
        lay.addRow("", row)
        self.last = self.footer
        self.header.installEventFilter(self)
        self.footer.installEventFilter(self)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.ok)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.FocusIn:
            self.last = obj
        return False

    def put(self, i):
        if i <= 0:
            return
        self.last.insert(TOKENS[i - 1][1])
        self.insert.setCurrentIndex(0)

    def ok(self):
        set_header_footer(self.doc, self.header.text(), self.footer.text())
        self.accept()


# =========================================================================== drawing a sheet on a page
def _paper(name):
    return next((pid for n, pid in PAPERS if n == name), QtGui.QPageSize.Letter)


def _setup_printer(printer, s):
    """The sheet's Page Setup on the printer. Each setting is set only when it changes. A real printer that
    is already printing (sheet 2 on) takes no new paper, orientation or colour: Qt refuses them ("Cannot be
    changed while printer is active"). Then a sheet of the other orientation is drawn turned 90 degrees, fitted
    to the page there (s["_turn"]). A PDF takes each sheet's own layout."""
    QtPrintSupport = print_support()
    s.pop("_turn", None)
    want = QtGui.QPageLayout.Landscape if s.get("landscape", True) else QtGui.QPageLayout.Portrait
    try:
        locked = printer.printerState() == QtPrintSupport.QPrinter.Active and \
            printer.outputFormat() != QtPrintSupport.QPrinter.PdfFormat
    except Exception:
        locked = False
    layout = printer.pageLayout()
    if locked:
        if layout.orientation() != want:
            s["_turn"] = True
        return
    size = _paper(s.get("paper", "Letter"))
    if layout.pageSize().id() != size:
        printer.setPageSize(QtGui.QPageSize(size))
    if printer.pageLayout().orientation() != want:
        printer.setPageOrientation(want)
    m = margins()
    if m is not None:
        top, bottom, left, right = m
        want_m = QtCore.QMarginsF(left, top, right, bottom)
        have = printer.pageLayout().margins(QtGui.QPageLayout.Millimeter)
        if any(abs(a - b) > 1e-6 for a, b in ((have.left(), left), (have.top(), top), (have.right(), right),
                                              (have.bottom(), bottom))):
            printer.setPageMargins(want_m, QtGui.QPageLayout.Millimeter)
    try:
        mode = QtPrintSupport.QPrinter.GrayScale if s.get("color") == "Black and white" \
            else QtPrintSupport.QPrinter.Color
        if printer.colorMode() != mode:
            printer.setColorMode(mode)
    except Exception as _fw_err:
        _fw_log("drawprint.py:250", _fw_err)


def _sheet_size(page):
    try:
        return float(page.Template.Width), float(page.Template.Height)
    except Exception:
        return 279.4, 215.9


def selection_rect(page, pad=3.0):
    """Print range Selection: the sheet area (scene coordinates) round the items picked on the sheet, else None."""
    gv = D.page_view(page)
    scene = gv.scene() if gv is not None else None
    if scene is None:
        return None
    rect = None
    for it in scene.selectedItems():
        r = it.sceneBoundingRect()
        rect = r if rect is None else rect.united(r)
    if rect is None:
        return None
    k = pad * D.REZ
    return rect.adjusted(-k, -k, k, k)


def _source_rect(page, screen=False):
    if isinstance(screen, QtCore.QRectF):
        return QtCore.QRectF(screen)
    w, h = _sheet_size(page)
    src = QtCore.QRectF(D.to_scene(0, h), D.to_scene(w, 0))
    if screen:
        gv = D.page_view(page)
        if gv is not None:
            src = gv.mapToScene(gv.viewport().rect()).boundingRect()
    return src


def draw_page(painter, printer, page, s, screen=False, background=False):
    """The sheet on the printer's page: Scale to fit or the Scale %, in its Drawing Color."""
    from . import drawexport
    scene = drawexport._scene(page)
    if scene is None:
        return False
    for it in scene.selectedItems():
        it.setSelected(False)
    paper = [] if background else _white_paper(scene, page)      # Print background keeps the sheet's colour
    try:
        ok = _draw(painter, printer, page, s, screen, scene)
        if ok:
            _out_of_sync_mark(painter, printer, page)      # extapps84
        return ok
    finally:
        for it, brush in paper:
            try:
                it.setBrush(brush)
            except Exception as _fw_err:
                _fw_log("drawprint.py:304", _fw_err)


def _white_paper(scene, page):
    """The sheet's paper drawn white while printing (the screen shows it tinted): [(item, its brush)]."""
    w, h = _sheet_size(page)
    out = []
    for it in scene.items():
        if not isinstance(it, QtWidgets.QAbstractGraphicsShapeItem):
            continue
        try:
            r = it.sceneBoundingRect()
            if abs(r.width() - w * D.REZ) > 0.05 * w * D.REZ or abs(r.height() - h * D.REZ) > 0.05 * h * D.REZ:
                continue
            b = it.brush()
            if b.style() == QtCore.Qt.NoBrush:
                continue
            out.append((it, QtGui.QBrush(b)))
            it.setBrush(QtGui.QBrush(QtCore.Qt.white))
        except Exception as _fw_err:
            _fw_log("drawprint.py:326", _fw_err)
            continue
    return out


def _draw(painter, printer, page, s, screen, scene):
    if s.get("_turn"):                  # the printer kept the first sheet's orientation: this sheet turned to fit it
        page_px = printer.pageLayout().paintRectPixels(printer.resolution())
        painter.save()
        try:
            painter.translate(page_px.width(), 0)
            painter.rotate(90)
            t = dict(s)
            t.pop("_turn")
            t["fit"] = True
            return _draw(painter, _Turned(printer), page, t, screen, scene)
        finally:
            painter.restore()
    src = _source_rect(page, screen)
    area = printer.pageLayout().paintRectPixels(printer.resolution())
    area = QtCore.QRectF(0, 0, area.width(), area.height())
    if s.get("fit", True) or screen is True:
        target = area
        mode = QtCore.Qt.KeepAspectRatio
    else:
        px_mm = printer.resolution() / 25.4 * float(s.get("scale", 100)) / 100.0
        wmm, hmm = src.width() / D.REZ, src.height() / D.REZ
        target = QtCore.QRectF(0, 0, wmm * px_mm, hmm * px_mm)
        mode = QtCore.Qt.IgnoreAspectRatio
    if s.get("color") == "Black and white":
        dpi = 300 if s.get("high", True) else 150
        wmm, hmm = src.width() / D.REZ, src.height() / D.REZ
        img = QtGui.QImage(int(wmm / 25.4 * dpi), int(hmm / 25.4 * dpi), QtGui.QImage.Format_ARGB32)
        img.fill(QtCore.Qt.white)
        p2 = QtGui.QPainter(img)
        p2.setRenderHint(QtGui.QPainter.Antialiasing, True)
        scene.render(p2, QtCore.QRectF(0, 0, img.width(), img.height()), src, QtCore.Qt.KeepAspectRatio)
        p2.end()
        img = mono(img)
        painter.drawImage(_fit(target, img.width(), img.height()) if mode == QtCore.Qt.KeepAspectRatio else target,
                          img)
    else:
        if s.get("high", True):
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        scene.render(painter, target, src, mode)
    return True


class _Turned:
    """The printer as a sheet drawn turned 90 degrees sees it: its paint area with width and height swapped."""

    def __init__(self, printer):
        self.printer = printer

    def resolution(self):
        return self.printer.resolution()

    def pageLayout(self):
        return self

    def paintRectPixels(self, res):
        r = self.printer.pageLayout().paintRectPixels(res)
        return QtCore.QRect(0, 0, r.height(), r.width())


def _fit(area, w, h):
    k = min(area.width() / float(w), area.height() / float(h))
    return QtCore.QRectF(area.x(), area.y(), w * k, h * k)


def mono(img):
    ""
    out = img.convertToFormat(QtGui.QImage.Format_Grayscale8)
    w, h = out.width(), out.height()
    bpl = out.bytesPerLine()
    try:
        buf = out.bits()
        data = bytearray(bytes(buf)[:bpl * h])
        for i, b in enumerate(data):
            data[i] = 255 if b > 235 else 0
        res = QtGui.QImage(bytes(data), w, h, bpl, QtGui.QImage.Format_Grayscale8).copy()
        return res
    except Exception:
        return out.convertToFormat(QtGui.QImage.Format_Mono, QtCore.Qt.ThresholdDither)


WIDTH_PROPS = ("LineWidth", "HiddenWidth", "IsoWidth", "ExtraWidth")


def line_weights():
    ""
    try:
        from . import printextras
        return dict(printextras.line_weights())
    except Exception:
        from . import drawdocprops
        return dict(drawdocprops.THICKNESS_MM)


class PrintWeights:
    ""


    def __init__(self, pages, on=True):
        self.pages = [p for p in pages if p is not None]
        self.on = on
        self.saved = []

    def __enter__(self):
        if not self.on:
            return self
        from . import drawdocprops
        weights = line_weights()
        for page in self.pages:
            names = [(n, drawdocprops.thickness_mm(n, doc=page.Document)) for n in drawdocprops.THICKNESS_NAMES]
            for v in page.Views:
                vo = getattr(v, "ViewObject", None)
                if vo is None or not v.isDerivedFrom("TechDraw::DrawViewPart"):
                    continue
                for prop in WIDTH_PROPS:
                    if prop not in vo.PropertiesList:
                        continue
                    try:
                        w = float(getattr(vo, prop).Value if hasattr(getattr(vo, prop), "Value") else getattr(vo, prop))
                    except Exception:
                        continue
                    name = next((n for n, mm in names if abs(mm - w) < 0.005), None)
                    if name is None or name not in weights or abs(weights[name] - w) < 1e-6:
                        continue
                    try:
                        setattr(vo, prop, weights[name])
                        self.saved.append((vo, prop, w))
                    except Exception as _fw_err:
                        _fw_log("drawprint.py:427", _fw_err)
        if self.saved:
            QtWidgets.QApplication.processEvents()
        return self

    def __exit__(self, *_):
        for vo, prop, w in reversed(self.saved):
            try:
                setattr(vo, prop, w)
            except Exception as _fw_err:
                _fw_log("drawprint.py:437", _fw_err)
        if self.saved:
            QtWidgets.QApplication.processEvents()
        self.saved = []


def chosen_pages(doc, rng, sheets_text=""):
    ps = pages(doc)
    if rng == "All":
        return ps
    if rng in ("Current sheet", "Current screen image", "Selection"):
        p = D.active_page()
        return [p] if p is not None and p.Document is doc else ps[:1]
    return [ps[i] for i in parse_sheets(sheets_text, len(ps))]


def _drawing_option(text, default):
    """extapps84: Tools > Options > System Options > Drawings: that row's kept value."""
    try:
        from . import optionspages
        return optionspages.stored("Drawings", text, default)
    except Exception:
        return default


def _out_of_sync_mark(painter, printer, page):
    ""

    if not _drawing_option("Print out-of-sync water mark", True):
        return False
    try:
        from . import drawmaint
        if not any(drawmaint.is_out_of_date(v) for v in D.views_of(page)
                   if v.isDerivedFrom("TechDraw::DrawViewPart")):
            return False
    except Exception as _fw_err:
        _fw_log("drawprint.py:out-of-sync", _fw_err)
        return False
    area = printer.pageLayout().paintRectPixels(printer.resolution())
    w, h = float(area.width()), float(area.height())
    painter.save()
    try:
        font = QtGui.QFont("Arial")
        font.setBold(True)
        font.setPixelSize(max(8, int(min(w, h) / 7)))
        painter.setFont(font)
        painter.setPen(QtGui.QColor(150, 150, 150, 120))
        painter.translate(w / 2.0, h / 2.0)
        painter.rotate(-30)
        painter.drawText(QtCore.QRectF(-w, -h / 2.0, 2 * w, h), int(QtCore.Qt.AlignCenter), "Out of Sync")
    finally:
        painter.restore()
    return True


class _NoBreakLines:
    """extapps84: System Options > Drawings > Print breaklines in broken view off: the broken views' break lines
    (TechDraw's own and the drawn ones) are left out of the print and put back after it; nothing is recomputed."""

    def __init__(self, pages):
        self.pages, self.undo, self.modified = list(pages or []), [], {}

    def __enter__(self):
        if _drawing_option("Print breaklines in broken view", True):
            return self
        for page in self.pages:
            for v in list(getattr(page, "Views", []) or []):
                if v.TypeId != "TechDraw::DrawBrokenView":
                    continue
                try:
                    g = Gui.getDocument(v.Document.Name)
                    self.modified.setdefault(v.Document.Name, bool(g.Modified) if g is not None else None)
                    vo = v.ViewObject
                    kind = getattr(vo, "BreakLineType", None)
                    edges = []
                    for tag in list(getattr(v, "SWBreakLines", []) or []):
                        ce = v.getCosmeticEdge(tag)
                        f = dict(ce.Format)
                        if f.get("visible", True):
                            f["visible"] = False
                            ce.Format = f
                            edges.append(tag)
                    if kind not in (None, "None"):
                        vo.BreakLineType = "None"
                    self.undo.append((v, kind, edges))
                    v.requestPaint()
                except Exception as _fw_err:
                    _fw_log("drawprint.py:no-breaklines", _fw_err)
        if self.undo:
            QtWidgets.QApplication.processEvents()
        return self

    def __exit__(self, *exc):
        for v, kind, edges in self.undo:
            try:
                for tag in edges:
                    ce = v.getCosmeticEdge(tag)
                    f = dict(ce.Format)
                    f["visible"] = True
                    ce.Format = f
                if kind not in (None, "None"):
                    v.ViewObject.BreakLineType = kind
                v.requestPaint()
            except Exception as _fw_err:
                _fw_log("drawprint.py:breaklines-back", _fw_err)
        for name, was in self.modified.items():
            try:
                g = Gui.getDocument(name)
                if g is not None and was is False and g.Modified:
                    g.Modified = False          # printing is not an edit
            except Exception as _fw_err:
                _fw_log("drawprint.py:modified", _fw_err)
        self.undo = []
        return False


def print_pages(printer, doc, rng="All", sheets_text="", copies=1, background=False, collate=True):
    """Each chosen sheet on its own page (its Page Setup), copies times. Returns the number of pages."""
    from . import drawexport
    drawexport._fields_current(doc)          # every sheet's title block as it is now
    chosen = chosen_pages(doc, rng, sheets_text)
    if not chosen:
        return 0
    n = 0
    area = None
    if rng == "Selection":                # the picked items' area of the active sheet (else the whole sheet)
        area = selection_rect(chosen[0])
    with drawexport._NoPrint(doc), PrintWeights(chosen), _NoBreakLines(chosen):      # extapps84
        painter = None
        copies = max(1, int(copies))
        order = [p for _c in range(copies) for p in chosen] if collate else \
            [p for p in chosen for _c in range(copies)]
        for page in order:
            s = settings_for(page)
            _setup_printer(printer, s)
            if painter is None:
                painter = QtGui.QPainter()
                if not painter.begin(printer):
                    return 0
            elif not printer.newPage():
                break
            draw_page(painter, printer, page, s, area if area is not None else rng == "Current screen image",
                      background)
            n += 1
            # (its own name: this used to overwrite the Selection area, so sheets 2 on printed the screen image)
            paint = printer.pageLayout().paintRectPixels(printer.resolution())
            draw_header_footer(painter, QtCore.QRectF(0, 0, paint.width(), paint.height()), doc, page,
                               chosen.index(page) + 1, len(chosen))
        if painter is not None:
            painter.end()
    return n


# =========================================================================== Page Setup
class PageSetupDialog(QtWidgets.QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc
        self.setObjectName("SWPageSetup")
        self.setWindowTitle("Page Setup")
        self.setup = doc_setup(doc)
        self.sheet_settings = dict(self.setup.get("sheets", {}))
        lay = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        self.use_system = QtWidgets.QRadioButton("Use system settings", self)
        self.use_system.setObjectName("SWPageUseSystem")
        self.use_doc = QtWidgets.QRadioButton("Use this document's settings", self)
        self.use_doc.setObjectName("SWPageUseDocument")
        (self.use_doc if self.setup.get("use_doc") else self.use_system).setChecked(True)
        top.addWidget(self.use_system)
        top.addWidget(self.use_doc)
        lay.addLayout(top)
        row = QtWidgets.QHBoxLayout()
        self.per_sheet = QtWidgets.QCheckBox("Different settings for each sheet", self)
        self.per_sheet.setObjectName("SWPagePerSheet")
        self.per_sheet.setChecked(bool(self.setup.get("per_sheet")))
        row.addWidget(self.per_sheet)
        row.addWidget(QtWidgets.QLabel("Settings for:", self))
        self.sheet = QtWidgets.QComboBox(self)
        self.sheet.setObjectName("SWPageSettingsFor")
        self.sheet.addItems([p.Label for p in pages(doc)])
        cur = D.active_page()
        if cur is not None and cur.Document is doc:
            self.sheet.setCurrentText(cur.Label)
        row.addWidget(self.sheet)
        lay.addLayout(row)
        grid = QtWidgets.QGridLayout()
        rs = QtWidgets.QGroupBox("Resolution and Scale", self)
        rl = QtWidgets.QVBoxLayout(rs)
        self.fit = QtWidgets.QRadioButton("Scale to fit", rs)
        self.fit.setObjectName("SWPageScaleToFit")
        srow = QtWidgets.QHBoxLayout()
        self.scale_on = QtWidgets.QRadioButton("Scale:", rs)
        self.scale_on.setObjectName("SWPageScaleOn")
        self.scale = QtWidgets.QSpinBox(rs)
        self.scale.setObjectName("SWPageScale")
        self.scale.setRange(1, 1000)
        self.scale.setSuffix(" %")
        srow.addWidget(self.scale_on)
        srow.addWidget(self.scale)
        self.high = QtWidgets.QCheckBox("High quality", rs)
        self.high.setObjectName("SWPageHighQuality")
        rl.addWidget(self.fit)
        rl.addLayout(srow)
        rl.addWidget(self.high)
        grid.addWidget(rs, 0, 0)
        pp = QtWidgets.QGroupBox("Paper", self)
        pl = QtWidgets.QFormLayout(pp)
        self.paper = QtWidgets.QComboBox(pp)
        self.paper.setObjectName("SWPagePaperSize")
        self.paper.addItems([n for n, _ in PAPERS])
        pl.addRow("Size:", self.paper)
        grid.addWidget(pp, 0, 1)
        dc = QtWidgets.QGroupBox("Drawing Color", self)
        dl = QtWidgets.QVBoxLayout(dc)
        self.colors = {}
        for name in COLORS:
            b = QtWidgets.QRadioButton(name, dc)
            b.setObjectName("SWPageColor" + name.split()[0].replace("/", ""))
            dl.addWidget(b)
            self.colors[name] = b
        grid.addWidget(dc, 1, 0)
        orient = QtWidgets.QGroupBox("Orientation", self)
        ol = QtWidgets.QVBoxLayout(orient)
        self.portrait = QtWidgets.QRadioButton("Portrait", orient)
        self.portrait.setObjectName("SWPagePortrait")
        self.landscape = QtWidgets.QRadioButton("Landscape", orient)
        self.landscape.setObjectName("SWPageLandscape")
        ol.addWidget(self.portrait)
        ol.addWidget(self.landscape)
        grid.addWidget(orient, 1, 1)
        lay.addLayout(grid)
        self.preview_button = QtWidgets.QPushButton("Preview...", self)
        self.preview_button.setObjectName("SWPagePreview")
        self.preview_button.clicked.connect(lambda: (self.keep_sheet(), self.store(), preview(self.doc, self)))
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.addButton(self.preview_button, QtWidgets.QDialogButtonBox.ActionRole)
        bb.accepted.connect(self.ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.shown_sheet = self.sheet.currentText()
        self.load(self.current_settings())
        self.fit.toggled.connect(lambda on: self.scale.setEnabled(not on))
        self.use_doc.toggled.connect(self.sync)
        self.per_sheet.toggled.connect(self.sync)
        self.sheet.currentTextChanged.connect(self.switch_sheet)
        self.sync()

    def current_settings(self):
        if not self.use_doc.isChecked():
            return system_settings()
        out = dict(DEFAULT)
        out.update(self.setup.get("default", {}))
        if self.per_sheet.isChecked():
            out.update(self.sheet_settings.get(self.sheet.currentText(), {}))
        return out

    def load(self, s):
        self.fit.setChecked(bool(s.get("fit", True)))
        self.scale_on.setChecked(not s.get("fit", True))
        self.scale.setValue(int(s.get("scale", 100)))
        self.scale.setEnabled(not s.get("fit", True))
        self.high.setChecked(bool(s.get("high", True)))
        self.paper.setCurrentText(s.get("paper", "Letter"))
        self.colors.get(s.get("color", "Automatic"), self.colors["Automatic"]).setChecked(True)
        (self.landscape if s.get("landscape", True) else self.portrait).setChecked(True)

    def values(self):
        return {"fit": self.fit.isChecked(), "scale": self.scale.value(), "high": self.high.isChecked(),
                "paper": self.paper.currentText(),
                "color": next(n for n, b in self.colors.items() if b.isChecked()),
                "landscape": self.landscape.isChecked()}

    def sync(self, *_):
        doc_on = self.use_doc.isChecked()
        self.per_sheet.setEnabled(doc_on)
        self.sheet.setEnabled(doc_on and self.per_sheet.isChecked())

    def keep_sheet(self):
        if self.use_doc.isChecked() and self.per_sheet.isChecked():
            self.sheet_settings[self.shown_sheet] = self.values()

    def switch_sheet(self, name):
        self.keep_sheet()
        self.shown_sheet = name
        self.load(self.current_settings())

    def store(self):
        if self.use_doc.isChecked():
            setup = {"use_doc": True, "per_sheet": self.per_sheet.isChecked(),
                     "default": self.setup.get("default", {}) if self.per_sheet.isChecked() else self.values(),
                     "sheets": self.sheet_settings}
            set_doc_setup(self.doc, setup)
            self.setup = setup
        else:
            set_system_settings(self.values())
            setup = dict(self.setup)
            setup["use_doc"] = False
            set_doc_setup(self.doc, setup)
            self.setup = setup

    def ok(self):
        self.keep_sheet()
        self.store()
        self.accept()


# =========================================================================== Margins
class MarginsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWPrintMargins")
        self.setWindowTitle("Margins")
        prm = App.ParamGet(PARAM)
        lay = QtWidgets.QVBoxLayout(self)
        self.use_printer = QtWidgets.QCheckBox("Use printer's margins", self)
        self.use_printer.setObjectName("SWMarginsUsePrinter")
        self.use_printer.setChecked(prm.GetBool("PrinterMargins", True))
        lay.addWidget(self.use_printer)
        form = QtWidgets.QFormLayout()
        self.boxes = {}
        for k in ("Top", "Bottom", "Left", "Right"):
            b = QtWidgets.QDoubleSpinBox(self)
            b.setObjectName("SWMargins" + k)
            b.setRange(0, 100)
            b.setSuffix(" mm")
            b.setValue(prm.GetFloat(k, 6.35))
            b.setEnabled(not self.use_printer.isChecked())
            self.use_printer.toggled.connect(lambda on, b=b: b.setEnabled(not on))
            form.addRow(k + ":", b)
            self.boxes[k] = b
        lay.addLayout(form)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def ok(self):
        prm = App.ParamGet(PARAM)
        prm.SetBool("PrinterMargins", self.use_printer.isChecked())
        for k, b in self.boxes.items():
            prm.SetFloat(k, b.value())
        self.accept()


# =========================================================================== Print
class PrintDialog(QtWidgets.QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        QtPrintSupport = print_support()
        self.doc = doc
        self.setObjectName("SWPrint")
        self.setWindowTitle("Print - " + (doc.Label or doc.Name))
        lay = QtWidgets.QVBoxLayout(self)
        dp = QtWidgets.QGroupBox("Document Printer", self)
        dl = QtWidgets.QHBoxLayout(dp)
        dl.addWidget(QtWidgets.QLabel("Name:", dp))
        self.name = QtWidgets.QComboBox(dp)
        self.name.setObjectName("SWPrintPrinter")
        names = list(QtPrintSupport.QPrinterInfo.availablePrinterNames())
        self.name.addItems(names + [SAVE_PDF])      # as the part's Print box: a PDF needs no printer
        default = QtPrintSupport.QPrinterInfo.defaultPrinterName()
        self.name.setCurrentText(default if default in names else names[0] if names else SAVE_PDF)
        dl.addWidget(self.name, 1)
        self.props = QtWidgets.QPushButton("Properties...", dp)
        self.props.setObjectName("SWPrintProperties")
        self.props.setEnabled(self.name.currentText() != SAVE_PDF)
        self.name.currentTextChanged.connect(lambda t: self.props.setEnabled(t != SAVE_PDF))
        self.props.clicked.connect(self.properties)
        dl.addWidget(self.props)
        lay.addWidget(dp)
        so = QtWidgets.QGroupBox("System Options", self)
        sl = QtWidgets.QHBoxLayout(so)
        self.setup_button = QtWidgets.QPushButton("Page Setup...", so)
        self.setup_button.setObjectName("SWPrintPageSetup")
        self.setup_button.clicked.connect(lambda: PageSetupDialog(self.doc, self).exec_())
        self.margins_button = QtWidgets.QPushButton("Margins...", so)
        self.margins_button.setObjectName("SWPrintMarginsButton")
        self.margins_button.clicked.connect(lambda: MarginsDialog(self).exec_())
        sl.addWidget(self.setup_button)
        sl.addWidget(self.margins_button)
        lay.addWidget(so)
        do = QtWidgets.QGroupBox("Document Options", self)
        dol = QtWidgets.QHBoxLayout(do)
        self.hf_button = QtWidgets.QPushButton("Header/Footer...", do)
        self.hf_button.setObjectName("SWPrintHeaderFooter")
        self.hf_button.clicked.connect(lambda: HeaderFooterDialog(self.doc, self).exec_())
        dol.addWidget(self.hf_button)
        self.weights_button = QtWidgets.QPushButton("Line Weights...", do)
        self.weights_button.setObjectName("SWPrintLineWeights")
        self.weights_button.clicked.connect(self.line_weights)
        dol.addWidget(self.weights_button)
        dol.addStretch(1)
        lay.addWidget(do)
        pr = QtWidgets.QGroupBox("Print range", self)
        pl = QtWidgets.QGridLayout(pr)
        self.ranges = {}
        for i, name in enumerate(RANGES):
            b = QtWidgets.QRadioButton(name + (":" if name == "Sheets" else ""), pr)
            b.setObjectName("SWPrintRange" + name.replace(" ", ""))
            pl.addWidget(b, i, 0)
            self.ranges[name] = b
        self.sheets = QtWidgets.QLineEdit(pr)
        self.sheets.setObjectName("SWPrintSheets")
        self.sheets.setPlaceholderText("1, 3-4")
        pl.addWidget(self.sheets, 3, 1)
        self.ranges["All"].setChecked(True)
        self.sheets.setEnabled(False)
        self.ranges["Sheets"].toggled.connect(self.sheets.setEnabled)
        lay.addWidget(pr)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Number of copies:", self))
        self.copies = QtWidgets.QSpinBox(self)
        self.copies.setObjectName("SWPrintCopies")
        self.copies.setRange(1, 999)
        row.addWidget(self.copies)
        row.addStretch(1)
        self.to_file = QtWidgets.QCheckBox("Print to file", self)
        self.to_file.setObjectName("SWPrintToFile")
        self.to_file.setChecked(not names)
        row.addWidget(self.to_file)
        lay.addLayout(row)
        row2 = QtWidgets.QHBoxLayout()
        self.collate = QtWidgets.QCheckBox("Collate", self)
        self.collate.setObjectName("SWPrintCollate")
        self.collate.setChecked(True)
        self.background = QtWidgets.QCheckBox("Print background", self)
        self.background.setObjectName("SWPrintBackground")
        row2.addWidget(self.collate)
        row2.addWidget(self.background)
        row2.addStretch(1)
        lay.addLayout(row2)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.printed = 0
        self.file = ""

    def printer(self):
        QtPrintSupport = print_support()
        p = QtPrintSupport.QPrinter(QtPrintSupport.QPrinter.HighResolution)
        if self.name.currentText() and self.name.currentText() != SAVE_PDF:
            p.setPrinterName(self.name.currentText())
        return p

    def properties(self):
        QtPrintSupport = print_support()
        dlg = QtPrintSupport.QPrintDialog(self.printer(), self)
        dlg.setWindowTitle("Properties")
        dlg.exec_()

    def line_weights(self):
        """The Line Weights dialog (shared with the part/assembly Print): the print width of each thickness."""
        from . import printextras
        dlg = printextras.LineWeightsDialog(self)
        return dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()

    def range_name(self):
        return next(n for n, b in self.ranges.items() if b.isChecked())

    def ok(self):
        QtPrintSupport = print_support()
        p = self.printer()
        if self.to_file.isChecked() or self.name.currentText() == SAVE_PDF:
            path = ASK.pop("file", None)
            if path is None:
                path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Print to File", (self.doc.Label or "drawing")
                                                                + ".pdf", "PDF (*.pdf)")
            if not path:
                return
            p.setOutputFormat(QtPrintSupport.QPrinter.PdfFormat)
            p.setOutputFileName(path)
            self.file = path
        self.printed = print_pages(p, self.doc, self.range_name(), self.sheets.text(), self.copies.value(),
                                   self.background.isChecked(), self.collate.isChecked())
        self.accept()


def preview(doc, parent=None):
    try:
        from . import filecmds
        own = getattr(filecmds, "DrawingPreviewDialog", None)
    except Exception:
        own = None
    if own is not None:
        dlg = own(doc)
        return dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()
    QtPrintSupport = print_support()
    p = QtPrintSupport.QPrinter(QtPrintSupport.QPrinter.HighResolution)
    dlg = QtPrintSupport.QPrintPreviewDialog(p, parent or Gui.getMainWindow())
    dlg.setObjectName("SWPrintPreview")
    dlg.setWindowTitle("Print Preview")
    dlg.paintRequested.connect(lambda printer: print_pages(printer, doc, "All"))
    preview_buttons(dlg, doc)

    dlg.setWindowState(dlg.windowState() | QtCore.Qt.WindowMaximized)
    dlg.exec_()


def preview_buttons(dlg, doc):
    ""


    done = []
    for act in dlg.findChildren(QtGui.QAction):
        text = act.text().replace("&", "").strip().lower()
        if text not in ("print", "page setup"):
            continue
        try:
            act.triggered.disconnect()
        except Exception as _fw_err:
            _fw_log("drawprint.py:preview button", _fw_err)
        if text == "print":
            def _print(*_a, d=dlg):
                d.accept()                          # the preview closes, then File > Print's box opens
                QtCore.QTimer.singleShot(0, lambda: open_print(doc))
            act.triggered.connect(_print)
        else:
            def _setup(*_a, d=dlg):
                box = PageSetupDialog(doc, d)
                if (box.exec_() if hasattr(box, "exec_") else box.exec()):
                    try:
                        d.updatePreview()
                    except Exception as _fw_err:
                        _fw_log("drawprint.py:preview update", _fw_err)
            act.triggered.connect(_setup)
        act.setObjectName("SWPreview" + text.title().replace(" ", ""))
        done.append(text)
    return done


def open_print(doc):
    """File > Print for the drawing (the same box the menu opens)."""
    dlg = PrintDialog(doc)
    return dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()


# =========================================================================== commands
COMMANDS = {
    "FreeWorks_DrawPageSetup": ("Page Setup...", "TechDraw_PageDefault", "Sets the paper, scale, color and orientation "
                                "for printing the drawing."),
    "FreeWorks_DrawPrintPreview": ("Print Preview...", "document-print-preview", "Shows how the drawing prints."),
    "FreeWorks_DrawPrint": ("Print...", "document-print", "Prints the drawing's sheets."),
}


class _Command:
    def __init__(self, name):
        self.name = name

    def GetResources(self):
        text, pix, tip = COMMANDS[self.name]
        return {"MenuText": text, "ToolTip": tip, "Pixmap": D.pixmap(pix)}

    def IsActive(self):
        return D.active_page() is not None

    def Activated(self):
        page = D.active_page()
        if page is None:
            return
        doc = page.Document
        if self.name == "FreeWorks_DrawPageSetup":
            PageSetupDialog(doc).exec_()
        elif self.name == "FreeWorks_DrawPrintPreview":
            preview(doc)
        else:
            PrintDialog(doc).exec_()


def register():
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
