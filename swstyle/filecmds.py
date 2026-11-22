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

import ctypes
import os
import shutil
import sys
import tempfile
import zipfile

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import paths

Qt = QtCore.Qt
PAGE = "PageSetup"          # addon parameter group for Page Setup


# ------------------------------------------------------------------ page setup values

def _fw_unsplit(objs):
    """objs with a drawing view's model parts read back as their model (drawviews.unsplit; Drawings land151)."""
    try:
        from . import drawviews as DV
        return DV.unsplit(list(objs or []))
    except Exception:
        return list(objs or [])

def _page():
    return paths.params().GetGroup(PAGE)


def _doc_has_page_setup(doc=None):
    doc = doc or App.ActiveDocument
    try:
        return bool(doc is not None and doc.Meta.get("SWPageSetup", ""))
    except Exception:
        return False


def _doc_page_settings(doc=None):
    """The document's own Page Setup (Use this document settings), or None."""
    doc = doc or App.ActiveDocument
    try:
        text = doc.Meta.get("SWPageSetup", "") if doc is not None else ""
        if not text:
            return None
        landscape, paper, fit, scale, color, margins = text.split("|")
        return {"landscape": landscape == "True", "paper": paper, "fit": fit == "True", "scale": int(scale),
                "color": color, "margins": [float(m) for m in margins.split(",")]}
    except Exception:
        return None


def page_settings():
    own = _doc_page_settings()
    if own is not None:
        return own
    g = _page()
    return {
        "landscape": g.GetBool("Landscape", True),
        "paper": g.GetString("Paper", "Letter"),
        "fit": g.GetBool("ScaleToFit", True),
        "scale": g.GetInt("Scale", 100),
        "color": g.GetString("Color", "Automatic"),
        "margins": [g.GetFloat(k, 0.25) for k in ("MarginTop", "MarginBottom", "MarginLeft", "MarginRight")],
    }


PAPERS = ("Letter", "Legal", "Tabloid", "A4", "A3", "A5")
COLORS = ("Automatic", "Color / Gray scale", "Black and white")


def _doc_title():
    doc = App.ActiveDocument
    return doc.Label if doc is not None else ""


def _row(layout, label, widget):
    h = QtWidgets.QHBoxLayout()
    h.addWidget(QtWidgets.QLabel(label))
    h.addWidget(widget, 1)
    layout.addLayout(h)
    return widget


def _is_drawing(doc=None):
    doc = doc or App.ActiveDocument
    try:
        return doc is not None and any(o.isDerivedFrom("TechDraw::DrawPage") for o in doc.Objects)
    except Exception:
        return False


class PageSetupDialog(QtWidgets.QDialog):
    ""

    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWStyle_PageSetup")
        self.setWindowTitle("Page Setup")
        s = page_settings()
        lay = QtWidgets.QVBoxLayout(self)

        # document's own; the document's are kept in the document
        self.use_system = QtWidgets.QRadioButton("Use system settings")
        self.use_system.setObjectName("SWStyle_PageSetupSystem")
        self.use_document = QtWidgets.QRadioButton("Use this document settings")
        self.use_document.setObjectName("SWStyle_PageSetupDocument")
        (self.use_document if _doc_has_page_setup() else self.use_system).setChecked(True)
        lay.addWidget(self.use_system)
        lay.addWidget(self.use_document)

        res = QtWidgets.QGroupBox("Resolution and scale")
        rl = QtWidgets.QVBoxLayout(res)
        self.fit = QtWidgets.QRadioButton("Scale to fit")
        self.scaled = QtWidgets.QRadioButton("Scale:")
        self.scale = QtWidgets.QSpinBox()
        self.scale.setRange(1, 1000)
        self.scale.setSuffix(" %")
        self.scale.setValue(s["scale"])
        (self.fit if s["fit"] else self.scaled).setChecked(True)
        rl.addWidget(self.fit)
        h = QtWidgets.QHBoxLayout()
        h.addWidget(self.scaled)
        h.addWidget(self.scale)
        h.addStretch(1)
        rl.addLayout(h)
        lay.addWidget(res)

        paper = QtWidgets.QGroupBox("Paper")
        pl = QtWidgets.QVBoxLayout(paper)
        self.paper = _row(pl, "Size:", QtWidgets.QComboBox())
        self.paper.addItems(PAPERS)
        if s["paper"] in PAPERS:
            self.paper.setCurrentText(s["paper"])
        lay.addWidget(paper)

        orient = QtWidgets.QGroupBox("Orientation")
        ol = QtWidgets.QHBoxLayout(orient)
        self.portrait = QtWidgets.QRadioButton("Portrait")
        self.landscape = QtWidgets.QRadioButton("Landscape")
        (self.landscape if s["landscape"] else self.portrait).setChecked(True)
        ol.addWidget(self.portrait)
        ol.addWidget(self.landscape)
        lay.addWidget(orient)

        colour = QtWidgets.QGroupBox("Drawing color")
        cl = QtWidgets.QVBoxLayout(colour)
        self.colours = []
        for name in COLORS:
            b = QtWidgets.QRadioButton(name)
            b.setChecked(name == s["color"])
            cl.addWidget(b)
            self.colours.append(b)
        lay.addWidget(colour)

        margins = QtWidgets.QGroupBox("Margins (in)")
        ml = QtWidgets.QGridLayout(margins)
        self.margins = []
        for i, (name, value) in enumerate(zip(("Top:", "Bottom:", "Left:", "Right:"), s["margins"])):
            box = QtWidgets.QDoubleSpinBox()
            box.setRange(0.0, 5.0)
            box.setDecimals(2)
            box.setSingleStep(0.05)
            box.setValue(value)
            ml.addWidget(QtWidgets.QLabel(name), i // 2, (i % 2) * 2)
            ml.addWidget(box, i // 2, (i % 2) * 2 + 1)
            self.margins.append(box)
        lay.addWidget(margins)

        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
                                        | QtWidgets.QDialogButtonBox.Help)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.helpRequested.connect(self._help)
        lay.addWidget(bb)

    def _help(self):
        try:
            from . import helpmenu
            from . import helpguide
            if helpguide.show_topic("page setup") is None:
                helpmenu.show("home", search="page setup")
        except Exception as _fw_err:
            _fw_log("filecmds.py:pagesetup_help", _fw_err)

    def accept(self):
        g = _page()
        doc = App.ActiveDocument
        if doc is not None:
            meta = dict(doc.Meta)
            if self.use_document.isChecked():
                meta["SWPageSetup"] = "%d|%s|%d|%d|%s|%s" % (
                    self.landscape.isChecked(), self.paper.currentText(), self.fit.isChecked(), self.scale.value(),
                    next((b.text() for b in self.colours if b.isChecked()), "Automatic"),
                    ",".join("%.2f" % b.value() for b in self.margins))
            else:
                meta.pop("SWPageSetup", None)
            doc.Meta = meta
        g.SetBool("Landscape", self.landscape.isChecked())
        g.SetString("Paper", self.paper.currentText())
        g.SetBool("ScaleToFit", self.fit.isChecked())
        g.SetInt("Scale", self.scale.value())
        g.SetString("Color", next((b.text() for b in self.colours if b.isChecked()), "Automatic"))
        for key, box in zip(("MarginTop", "MarginBottom", "MarginLeft", "MarginRight"), self.margins):
            g.SetFloat(key, box.value())
        super().accept()


# ------------------------------------------------------------------ printers
def _qt_printers():
    try:
        from PySide import QtPrintSupport
    except ImportError:
        try:
            from PySide6 import QtPrintSupport
        except ImportError:
            return []
    try:
        return list(QtPrintSupport.QPrinterInfo.availablePrinterNames())
    except Exception:
        return []


def _win_printers():
    """(names, default) from winspool, without pywin32."""
    if sys.platform != "win32":
        return [], ""
    try:
        from ctypes import wintypes
        winspool = ctypes.WinDLL("winspool.drv")
        flags = 2 | 4           # PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
        needed, count = wintypes.DWORD(), wintypes.DWORD()
        winspool.EnumPrintersW(flags, None, 4, None, 0, ctypes.byref(needed), ctypes.byref(count))
        buf = (ctypes.c_byte * max(needed.value, 1))()
        if not winspool.EnumPrintersW(flags, None, 4, buf, needed, ctypes.byref(needed), ctypes.byref(count)):
            return [], ""

        class PRINTER_INFO_4(ctypes.Structure):
            _fields_ = [("pPrinterName", wintypes.LPWSTR), ("pServerName", wintypes.LPWSTR),
                        ("Attributes", wintypes.DWORD)]
        info = ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO_4))
        names = [info[i].pPrinterName for i in range(count.value)]
        size = wintypes.DWORD(0)
        winspool.GetDefaultPrinterW(None, ctypes.byref(size))
        default = ""
        if size.value:
            text = ctypes.create_unicode_buffer(size.value)
            if winspool.GetDefaultPrinterW(text, ctypes.byref(size)):
                default = text.value
        return names, default
    except Exception as error:
        App.Console.PrintLog("FreeCAD: printers not read: %s\n" % error)
        return [], ""


SAVE_PDF = "Save as PDF"


def printers():
    """(names, default, backend): Qt's printers when Qt has its plugin, else Windows'. "Save as PDF"
    is always last, so Print works with no printer at all (Ati's PC runs without the Print
    Spooler: Windows lists no printer, not even Microsoft Print to PDF)."""
    names = _qt_printers()
    if names:
        try:
            from PySide import QtPrintSupport
        except ImportError:
            from PySide6 import QtPrintSupport
        default = QtPrintSupport.QPrinterInfo.defaultPrinterName()
        return names + [SAVE_PDF], default, "qt"
    names, default = _win_printers()
    return names + [SAVE_PDF], default or ("" if names else SAVE_PDF), "gdi"


def spooler_running():
    return bool(_qt_printers() or _win_printers()[0])


def _is_pdf(name):
    return "pdf" in name.lower()


def print_pdf(target):
    """The page as a PDF file through Qt's QPdfWriter (no printer, no spooler)."""
    s = page_settings()
    writer = QtGui.QPdfWriter(target)
    writer.setTitle(_doc_title())
    writer.setCreator("FreeCAD")
    ids = getattr(QtGui.QPageSize, "PageSizeId", QtGui.QPageSize)
    orient = getattr(QtGui.QPageLayout, "Orientation", QtGui.QPageLayout)
    paper = getattr(ids, s["paper"], None) or ids.Letter
    writer.setPageSize(QtGui.QPageSize(paper))
    writer.setPageOrientation(orient.Landscape if s["landscape"] else orient.Portrait)
    writer.setPageMargins(QtCore.QMarginsF(0, 0, 0, 0))
    writer.setResolution(300)
    painter = QtGui.QPainter(writer)
    try:
        area = painter.viewport()
        x, y, w, h = _layout(area.width(), area.height(), 300, 300)
        k = min(1.0, 3000.0 / max(w, h, 1))
        image = view_image(max(int(w * k), 1), max(int(h * k), 1))
        iw, ih = _fit(w, h, image.width(), image.height(), 1.0)
        painter.drawImage(QtCore.QRect(x + (w - iw) // 2, y + (h - ih) // 2, iw, ih), image)
    finally:
        painter.end()
    return os.path.isfile(target)


# ------------------------------------------------------------------ the page picture
def view_image(width, height):
    ""
    view = Gui.ActiveDocument.ActiveView
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        from . import printextras
        background = "Current" if printextras.print_background() else "White"
        view.saveImage(path, int(width), int(height), background)
        image = QtGui.QImage(path)
    finally:
        try:
            os.remove(path)
        except OSError as _fw_err:
            _fw_log("filecmds.py:338", _fw_err)
    if page_settings()["color"] == "Black and white":
        image = image.convertToFormat(QtGui.QImage.Format_Grayscale8)
    return image.convertToFormat(QtGui.QImage.Format_RGB32)


def _fit(area_w, area_h, image_w, image_h, scale):
    k = min(area_w / float(image_w), area_h / float(image_h)) * scale
    return int(image_w * k), int(image_h * k)


def _layout(page_w, page_h, dpi_x, dpi_y):
    """(x, y, w, h) of the picture on the page in device pixels, from Page Setup."""
    s = page_settings()
    top, bottom, left, right = s["margins"]
    x0, y0 = int(left * dpi_x), int(top * dpi_y)
    area_w = max(page_w - int((left + right) * dpi_x), 1)
    area_h = max(page_h - int((top + bottom) * dpi_y), 1)
    if s["fit"]:
        return x0, y0, area_w, area_h
    k = s["scale"] / 100.0
    return x0, y0, int(area_w * k), int(area_h * k)


def print_qt(name, copies, to_file):
    try:
        from PySide import QtPrintSupport
    except ImportError:
        from PySide6 import QtPrintSupport
    printer = QtPrintSupport.QPrinter(QtPrintSupport.QPrinter.HighResolution)
    printer.setPrinterName(name)
    printer.setCopyCount(copies)
    printer.setDocName(_doc_title())
    s = page_settings()
    printer.setPageOrientation(QtGui.QPageLayout.Landscape if s["landscape"] else QtGui.QPageLayout.Portrait)
    if to_file:
        printer.setOutputFileName(to_file)
    page = printer.pageRect(QtPrintSupport.QPrinter.DevicePixel)
    pw, ph = int(page.width()), int(page.height())
    sheet = compose_page(pw, ph, printer.resolution(), printer.resolution())
    painter = QtGui.QPainter(printer)
    painter.drawImage(QtCore.QRect(0, 0, pw, ph), sheet)
    painter.end()
    return True


def compose_page(page_w, page_h, dpi_x, dpi_y, page=1, pages=1):
    """The whole page as an image: the view inside the margins, the header and the footer (printextras)."""
    from . import printextras
    k = min(1.0, 3000.0 / max(page_w, page_h, 1))
    pw, ph = max(1, int(page_w * k)), max(1, int(page_h * k))
    x, y, w, h = _layout(pw, ph, dpi_x * k, dpi_y * k)
    sheet = QtGui.QImage(pw, ph, QtGui.QImage.Format_RGB32)
    sheet.fill(QtGui.QColor("white"))
    image = view_image(max(w, 1), max(h, 1))
    return printextras.compose(sheet, image, x, y, w, h, dpi_x * k, page_settings()["fit"], page, pages)


def print_gdi(name, copies, to_file):
    """Print the view through Windows GDI (no Qt printer plugin needed)."""
    from ctypes import wintypes
    gdi, winspool = ctypes.WinDLL("gdi32"), ctypes.WinDLL("winspool.drv")
    gdi.CreateDCW.restype = wintypes.HDC
    gdi.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]

    # the printer's DEVMODE with Page Setup's orientation and copies
    hprinter = wintypes.HANDLE()
    devmode = None
    if winspool.OpenPrinterW(name, ctypes.byref(hprinter), None):
        try:
            winspool.DocumentPropertiesW.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.LPWSTR,
                                                     ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
            size = winspool.DocumentPropertiesW(None, hprinter, name, None, None, 0)
            if size > 0:
                devmode = (ctypes.c_byte * size)()
                if winspool.DocumentPropertiesW(None, hprinter, name, devmode, None, 2) >= 0:   # DM_OUT_BUFFER
                    # DEVMODEW: dmDeviceName[32] WCHAR (64 bytes), then specVersion, driverVersion,
                    # size, driverExtra (WORD each), fields (DWORD) at 72, orientation (short) at 76,
                    # paper size 78, length 80, width 82, scale 84, copies 86
                    fields = ctypes.c_uint32.from_buffer(devmode, 72)
                    ctypes.c_short.from_buffer(devmode, 76).value = 2 if page_settings()["landscape"] else 1
                    ctypes.c_short.from_buffer(devmode, 86).value = max(1, int(copies))
                    fields.value |= 0x1 | 0x100     # DM_ORIENTATION | DM_COPIES
                    winspool.DocumentPropertiesW(None, hprinter, name, devmode, devmode, 2 | 8)
                else:
                    devmode = None
        finally:
            winspool.ClosePrinter(hprinter)
    hdc = gdi.CreateDCW("WINSPOOL", name, None, ctypes.cast(devmode, ctypes.c_void_p) if devmode else None)
    if not hdc:
        raise RuntimeError("printer %s not opened" % name)
    try:
        HORZRES, VERTRES, LOGPIXELSX, LOGPIXELSY = 8, 10, 88, 90
        page_w, page_h = gdi.GetDeviceCaps(hdc, HORZRES), gdi.GetDeviceCaps(hdc, VERTRES)
        dpi_x, dpi_y = gdi.GetDeviceCaps(hdc, LOGPIXELSX), gdi.GetDeviceCaps(hdc, LOGPIXELSY)
        # the whole page (view, header, footer) at most 3000 px: GDI stretches it onto the paper
        image = compose_page(page_w, page_h, dpi_x, dpi_y)
        x, y, w, h = 0, 0, page_w, page_h
        iw, ih = w, h

        class DOCINFOW(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_int), ("lpszDocName", wintypes.LPCWSTR),
                        ("lpszOutput", wintypes.LPCWSTR), ("lpszDatatype", wintypes.LPCWSTR),
                        ("fwType", wintypes.DWORD)]
        info = DOCINFOW(ctypes.sizeof(DOCINFOW), _doc_title() or "FreeCAD", to_file or None, None, 0)
        if gdi.StartDocW(hdc, ctypes.byref(info)) <= 0:
            return False            # cancelled (a PDF printer's own Save box) or failed
        gdi.StartPage(hdc)

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]
        header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), image.width(), -image.height(),
                                  1, 32, 0, 0, 0, 0, 0, 0)
        bits = image.constBits()
        data = bytes(bits) if not hasattr(bits, "tobytes") else bits.tobytes()
        data = data[:image.bytesPerLine() * image.height()]
        gdi.SetStretchBltMode(hdc, 4)            # HALFTONE
        gdi.StretchDIBits(hdc, x + (w - iw) // 2, y + (h - ih) // 2, iw, ih, 0, 0, image.width(),
                          image.height(), data, ctypes.byref(header), 0, 0x00CC0020)   # SRCCOPY
        gdi.EndPage(hdc)
        gdi.EndDoc(hdc)
        return True
    finally:
        gdi.DeleteDC(hdc)


class PrintDialog(QtWidgets.QDialog):
    ""


    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWStyle_Print")
        self.setWindowTitle("Print")
        names, default, self.backend = printers()
        lay = QtWidgets.QVBoxLayout(self)

        box = QtWidgets.QGroupBox("Document Printer")
        bl = QtWidgets.QVBoxLayout(box)
        self.printer = _row(bl, "Name:", QtWidgets.QComboBox())
        self.printer.setObjectName("SWStyle_PrintPrinter")
        self.printer.addItems(names)
        if default in names:
            self.printer.setCurrentText(default)
        self.status = QtWidgets.QLabel(
            "Ready" if spooler_running() else "Windows lists no printer (the Print Spooler service is not running); "
                                              "Save as PDF writes a PDF file")
        self.status.setWordWrap(True)
        bl.addWidget(self.status)

        from . import printextras
        buttons = QtWidgets.QHBoxLayout()
        for text, name, slot in (("Properties...", "SWStyle_PrintProperties", self._properties),
                                 ("Page Setup...", "SWStyle_PrintPageSetup", lambda: PageSetupDialog(self).exec()),
                                 ("Header/Footer...", "SWStyle_PrintHeaderFooter", lambda: printextras.HeaderFooterDialog(self).exec()),
                                 ("Margins...", "SWStyle_PrintMargins", lambda: PageSetupDialog(self).exec())):
            b = QtWidgets.QPushButton(text)
            b.setObjectName(name)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        bl.addLayout(buttons)
        lay.addWidget(box)

        opts = QtWidgets.QGroupBox("Document Options")
        ol = QtWidgets.QHBoxLayout(opts)
        for text, name, slot in (("Line weights...", "SWStyle_PrintLineWeights", lambda: printextras.LineWeightsDialog(self).exec()),
                                 ("Selection...", "SWStyle_PrintSelection", lambda: printextras.SelectionDialog(self).exec()),
                                 ("Scale...", "SWStyle_PrintScale", lambda: printextras.ScaleDialog(self).exec())):
            b = QtWidgets.QPushButton(text)
            b.setObjectName(name)
            b.clicked.connect(slot)
            ol.addWidget(b)
        ol.addStretch(1)
        lay.addWidget(opts)

        rng = QtWidgets.QGroupBox("Print range")
        rl = QtWidgets.QGridLayout(rng)
        self.range_all = QtWidgets.QRadioButton("All sheets")
        self.range_all.setObjectName("SWStyle_PrintAll")
        self.range_all.setChecked(True)
        self.range_current = QtWidgets.QRadioButton("Current sheet")
        self.range_current.setObjectName("SWStyle_PrintCurrent")
        self.range_sheets = QtWidgets.QRadioButton("Sheets:")
        self.range_sheets.setObjectName("SWStyle_PrintSheets")
        self.sheets = QtWidgets.QLineEdit()
        self.sheets.setObjectName("SWStyle_PrintSheetList")
        self.sheets.setPlaceholderText("1,3,5-7")
        # filemenu-1119: typing sheet numbers picks Sheets: (no greyed field); a part or an assembly has no

        self.sheets.textEdited.connect(lambda _t: self.range_sheets.setChecked(True))
        drawing = _is_drawing()
        for w in (self.range_current, self.range_sheets, self.sheets):
            w.setVisible(drawing)
        if not drawing:
            self.range_all.setText("All")
        rl.addWidget(self.range_all, 0, 0)
        rl.addWidget(self.range_current, 1, 0)
        rl.addWidget(self.range_sheets, 2, 0)
        rl.addWidget(self.sheets, 2, 1)
        rl.addWidget(QtWidgets.QLabel("Number of copies:"), 0, 2)
        self.copies = QtWidgets.QSpinBox()
        self.copies.setObjectName("SWStyle_PrintCopies")
        self.copies.setRange(1, 999)
        rl.addWidget(self.copies, 0, 3)
        lay.addWidget(rng)

        h = QtWidgets.QHBoxLayout()
        self.to_file = QtWidgets.QCheckBox("Print to file")
        self.to_file.setObjectName("SWStyle_PrintToFile")
        h.addWidget(self.to_file)
        self.background = QtWidgets.QCheckBox("Print background")
        self.background.setObjectName("SWStyle_PrintBackground")
        self.background.setChecked(printextras.print_background())
        self.background.toggled.connect(printextras.set_print_background)
        h.addWidget(self.background)
        h.addStretch(1)
        lay.addLayout(h)

        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
                                        | QtWidgets.QDialogButtonBox.Help)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.helpRequested.connect(self._help)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(bool(names))
        lay.addWidget(bb)

    def sheet_range(self):
        ""
        if self.range_current.isChecked():
            return "current"
        if self.range_sheets.isChecked():
            out = []
            for part in self.sheets.text().replace(" ", "").split(","):
                if "-" in part:
                    a, b = part.split("-", 1)
                    if a.isdigit() and b.isdigit():
                        out.extend(range(int(a), int(b) + 1))
                elif part.isdigit():
                    out.append(int(part))
            return out
        return "all"

    def _properties(self):
        name = self.printer.currentText()
        if sys.platform == "win32" and name and name != SAVE_PDF:
            try:
                os.system('rundll32 printui.dll,PrintUIEntry /e /n "%s"' % name)
                return
            except Exception as _fw_err:
                _fw_log("filecmds.py:588", _fw_err)
        QtWidgets.QMessageBox.information(self, "Printer Properties", "%s has no properties box here." % (name or "This printer"))

    def _help(self):
        try:
            from . import helpmenu
            from . import helpguide
            if helpguide.show_topic("print") is None:
                helpmenu.show("home", search="print")
        except Exception as _fw_err:
            _fw_log("filecmds.py:596", _fw_err)

    def accept(self):
        name = self.printer.currentText()
        _page().SetString("SheetRange", str(self.sheet_range()))     # read by the drawing sheet printer
        target = ""
        if self.to_file.isChecked() or _is_pdf(name):
            base = os.path.splitext(getattr(App.ActiveDocument, "FileName", "") or _doc_title())[0]
            kind = "PDF (*.pdf)" if _is_pdf(name) else "Printer files (*.prn)"
            target, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Print to file", base + (".pdf" if _is_pdf(name) else ".prn"), kind)
            if not target:
                return
        self.hide()
        try:
            if name == SAVE_PDF:
                ok = print_pdf(target)
            else:
                run = print_qt if self.backend == "qt" else print_gdi
                ok = run(name, self.copies.value(), target)
            if ok:
                App.Console.PrintMessage("FreeCAD: printed %s on %s%s\n" % (
                    _doc_title(), name, (" to " + target) if target else ""))
        except Exception as error:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Print", "Unable to print: %s" % error)
        super().accept()


PAPER_IN = {"Letter": (8.5, 11.0), "Legal": (8.5, 14.0), "Tabloid": (11.0, 17.0),
            "A4": (8.27, 11.69), "A3": (11.69, 16.54), "A5": (5.83, 8.27)}


class PrintPreviewDialog(QtWidgets.QDialog):
    ""


    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWStyle_PrintPreview")
        self.setWindowTitle("Print Preview")
        self.resize(900, 760)
        lay = QtWidgets.QVBoxLayout(self)
        bar = QtWidgets.QHBoxLayout()
        self.zoom = 1.0
        for text, slot in (("Print...", self._print), ("Page Setup...", self._setup), ("Zoom In", self.zoom_in),
                           ("Zoom Out", self.zoom_out), ("Close", self.reject), ("Help", self._help)):
            b = QtWidgets.QPushButton(text)
            b.setObjectName("SWStyle_PreviewButton_" + text.replace(" ", "").replace(".", ""))
            b.clicked.connect(slot)
            bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.page = QtWidgets.QLabel()
        self.page.setAlignment(Qt.AlignCenter)
        self.page.setStyleSheet("background: #808080;")
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignCenter)
        self.scroll.setWidget(self.page)
        lay.addWidget(self.scroll, 1)
        QtCore.QTimer.singleShot(0, self.draw)

    def zoom_in(self):
        self.zoom = min(4.0, self.zoom * 1.5)
        self.draw()

    def zoom_out(self):
        self.zoom = max(1.0, self.zoom / 1.5)
        self.draw()

    def _help(self):
        try:
            from . import helpmenu
            from . import helpguide
            if helpguide.show_topic("print preview") is None:
                helpmenu.show("home", search="print preview")
        except Exception as _fw_err:
            _fw_log("filecmds.py:preview_help", _fw_err)

    def page_image(self, dpi=72):
        s = page_settings()
        w_in, h_in = PAPER_IN.get(s["paper"], PAPER_IN["Letter"])
        if s["landscape"]:
            w_in, h_in = h_in, w_in
        pw, ph = int(w_in * dpi), int(h_in * dpi)
        return compose_page(pw, ph, dpi, dpi)

    def draw(self):
        area = self.scroll.viewport().size() if hasattr(self, "scroll") else self.page.size()
        dpi = max(20, int(min(area.width() / 17.0, area.height() / 17.0) * 0.95 * getattr(self, "zoom", 1.0)))
        try:
            self.page.setPixmap(QtGui.QPixmap.fromImage(self.page_image(dpi)))
        except Exception as error:
            self.page.setText("No preview: %s" % error)

    def _setup(self):
        if PageSetupDialog(self).exec():
            self.draw()

    def _print(self):
        self.reject()
        QtCore.QTimer.singleShot(0, lambda: PrintDialog().exec())


# ------------------------------------------------------------------ references, Pack and Go, Send To
def references(doc=None):
    """The document and every document it references, the document first (paths may be empty
    for a document never saved)."""
    doc = doc or App.ActiveDocument
    if doc is None:
        return []
    try:
        docs = doc.getDependentDocuments()
    except Exception:
        docs = [doc]
    out = [doc] + [d for d in docs if d is not doc]
    return out


def _stored_links(doc):
    """refs129: {component name: the file path its link stored} from the saved document."""
    import re, zipfile
    out = {}
    try:
        with zipfile.ZipFile(doc.FileName) as z:
            xml = z.read("Document.xml").decode("utf-8", "replace")
        for m in re.finditer(r'<Object name="([^"]+)"[^>]*>(.*?)</Object>', xml, re.S):
            x = re.search(r'<Property name="LinkedObject"[^>]*>\s*<XLink file="([^"]+)"', m.group(0))
            if x:
                out[m.group(1)] = x.group(1)
    except Exception as _fw_err:
        _fw_log("filecmds.py:stored-links", _fw_err)
    return out


class FindReferencesDialog(QtWidgets.QDialog):
    ""

    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWStyle_FindReferences")
        self.setWindowTitle("Find References")
        self.resize(640, 300)
        lay = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTreeWidget()
        self.table.setHeaderLabels(["Name", "In Folder"])
        self.table.setRootIsDecorated(False)
        self.table.resizeColumnToContents(0)
        lay.addWidget(self.table)
        self.broken = QtWidgets.QCheckBox("Include broken references", self)
        self.broken.setObjectName("SWStyle_FindReferencesBroken")
        self.broken.toggled.connect(lambda _on: self.fill())

        self.nested = QtWidgets.QCheckBox("Show nested view", self)
        self.nested.setObjectName("SWStyle_FindReferencesNested")
        self.nested.toggled.connect(lambda _on: self.fill())
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.nested)
        row.addWidget(self.broken)
        row.addStretch(1)
        lay.addLayout(row)
        bb = QtWidgets.QDialogButtonBox()
        copy = bb.addButton("Copy Files...", QtWidgets.QDialogButtonBox.ActionRole)
        copy.clicked.connect(self.copy_files)
        self.print_button = bb.addButton("Print...", QtWidgets.QDialogButtonBox.ActionRole)
        self.print_button.clicked.connect(self.print_list)
        bb.addButton(QtWidgets.QDialogButtonBox.Close).clicked.connect(self.reject)
        bb.addButton(QtWidgets.QDialogButtonBox.Help).clicked.connect(self._help)
        lay.addWidget(bb)
        self.fill()

    def _help(self):
        try:
            from . import helpmenu
            from . import helpguide
            if helpguide.show_topic("find references") is None:
                helpmenu.show("home", search="find references")
        except Exception as _fw_err:
            _fw_log("filecmds.py:findref_help", _fw_err)

    def broken_references(self):
        ""
        out = []
        doc = App.ActiveDocument
        if doc is None:
            return out
        try:

            # file, not the component); FreeCAD's App::Link has no LinkedFile, so the rows said "not found".
            # refs129 (Reviewer): the folder from the stored path ("../parts/Bolt.FCStd"), not the assembly's
            from . import asmrefopts
            folder = os.path.dirname(doc.FileName or "")
            where = _stored_links(doc)
            for link, fname, _obj in asmrefopts.missing_links(doc):
                stored = where.get(link.Name, fname)
                out.append((link, os.path.normpath(stored if os.path.isabs(stored) else os.path.join(folder, stored))))
        except Exception as _fw_err:
            _fw_log("filecmds.py:broken-files", _fw_err)
        listed = {o.Name for o, _p in out}
        for obj in doc.Objects:
            if obj.Name in listed:
                continue        # refs129: and the links broken since the last save (not in the saved file)
            try:
                if hasattr(obj, "LinkedObject") and obj.LinkedObject is None and obj.TypeId.startswith("App::Link"):
                    out.append((obj, getattr(obj, "LinkedFile", "") or ""))
            except Exception as _fw_err:
                _fw_log("filecmds.py:729", _fw_err)
        return out

    def fill(self):
        self.table.clear()
        docs = references()
        nested = self.nested.isChecked()
        parents = pack_parents(docs) if nested else {}
        made = {}
        for d in docs:
            path = d.FileName
            made[d.Name] = QtWidgets.QTreeWidgetItem(self.table, [os.path.basename(path) if path else d.Label + " (not saved)",
                                                                  os.path.dirname(path) if path else ""])
        for name, item in made.items():
            up = made.get(parents.get(name))
            if up is not None and up is not item:
                self.table.takeTopLevelItem(self.table.indexOfTopLevelItem(item))
                up.addChild(item)
        self.table.setRootIsDecorated(nested)
        self.table.expandAll()
        if self.broken.isChecked():
            for obj, path in self.broken_references():
                item = QtWidgets.QTreeWidgetItem(self.table, [(os.path.basename(path) or obj.Label) + "  (broken)",
                                                              os.path.dirname(path) if path else "not found"])
                item.setForeground(0, QtGui.QColor(200, 0, 0))
        self.table.resizeColumnToContents(0)

    def print_list(self):
        """Print...: the list as a page, through the print dialog (nothing prints until OK)."""
        try:
            from PySide import QtPrintSupport
        except ImportError:
            from PySide6 import QtPrintSupport      # FreeCAD's PySide shim leaves it out
        lines = ["<h3>Find References</h3><table border='1' cellpadding='3'><tr><th>Name</th><th>In Folder</th></tr>"]
        it = QtWidgets.QTreeWidgetItemIterator(self.table)
        while it.value():
            row, depth, up = it.value(), 0, it.value().parent()
            while up is not None:
                depth, up = depth + 1, up.parent()
            lines.append("<tr><td>%s%s</td><td>%s</td></tr>" % ("&nbsp;" * 4 * depth, row.text(0), row.text(1)))
            it += 1
        lines.append("</table>")
        document = QtGui.QTextDocument()
        document.setHtml("".join(lines))
        printer = QtPrintSupport.QPrinter()
        box = QtPrintSupport.QPrintDialog(printer, self)
        if box.exec() == QtWidgets.QDialog.Accepted:
            (document.print_ if hasattr(document, "print_") else document.print)(printer)

    def copy_files(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Copy Files")
        if not folder:
            return
        for d in references():
            if d.FileName and os.path.isfile(d.FileName):
                shutil.copy2(d.FileName, os.path.join(folder, os.path.basename(d.FileName)))


def _is_drawing_doc(doc):
    return doc is not None and any(o.TypeId == "TechDraw::DrawPage" for o in doc.Objects)


def pack_parents(docs):
    ""


    docs = [d for d in docs if d is not None]
    uses = {}
    for d in docs:
        try:
            uses[d.Name] = {x.Name for x in d.getDependentDocuments() if x is not d}
        except Exception:
            uses[d.Name] = set()
    out = {}
    for d in docs:
        owners = [o for o in docs if o is not d and not _is_drawing_doc(o) and d.Name in uses[o.Name]]
        if owners:
            out[d.Name] = min(owners, key=lambda o: len(uses[o.Name])).Name
    return out


def _pack_file_info(doc, path):
    ""
    size = when = ""
    try:
        if path and os.path.isfile(path):
            st = os.stat(path)
            size = "%d KB" % max(1, (st.st_size + 1023) // 1024)
            import time
            when = time.strftime("%x %H:%M", time.localtime(st.st_mtime))
    except OSError as _fw_err:
        _fw_log("filecmds.py:779", _fw_err)
    kind = "FreeCAD Part"
    try:
        objs = doc.Objects if doc is not None else []
        if any(o.TypeId == "TechDraw::DrawPage" for o in objs):
            kind = "FreeCAD Drawing"
        elif any(o.TypeId == "Assembly::AssemblyObject" or "Assembly" in getattr(o, "Type", "") for o in objs):
            kind = "FreeCAD Assembly"
        elif doc is None:
            ext = os.path.splitext(path or "")[1].lower()
            if ext == ".fcstd":                 # filehandling88: a file not open says what it holds
                from . import fcstdinfo
                k = fcstdinfo.kind(path) if path and os.path.isfile(path) else ""
                if k:
                    return [size, "FreeCAD " + k.title(), when]
            kind = {".fcstd": "FreeCAD Document", ".step": "STEP File", ".stp": "STEP File"}.get(ext, ext[1:].upper() + " File")
    except Exception as _fw_err:
        _fw_log("filecmds.py:791", _fw_err)
    return [size, kind, when]


class PackAndGoDialog(QtWidgets.QDialog):
    ""


    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWStyle_PackAndGo")
        self.setWindowTitle("Pack and Go")
        self.resize(980, 620)           # filehandling88: room for the file list (it showed two rows)
        self.docs = references()
        lay = QtWidgets.QVBoxLayout(self)

        # Include suppressed components, Include custom / default decals, appearances and scenes
        inc = QtWidgets.QGridLayout()
        self.include = {}
        for i, (key, text, on) in enumerate((("drawings", "Include drawings", False),
                                             ("simulation", "Include simulation results", False),
                                             ("toolbox", "Include Toolbox components", True),
                                             ("suppressed", "Include suppressed components", True),
                                             ("custom_decals", "Include custom decals, appearances and scenes", True))):
            # exportopts-1119: no "Include default decals": FreeCAD has no default decal library to pack
            c = QtWidgets.QCheckBox(text)
            c.setObjectName("SWStyle_PackInclude_" + key)
            c.setChecked(on)
            c.toggled.connect(self._fill)
            inc.addWidget(c, i // 2, i % 2)
            self.include[key] = c
        lay.addLayout(inc)
        self.table = QtWidgets.QTreeWidget()
        self.table.setObjectName("SWStyle_PackTable")

        self.table.setHeaderLabels(["Name", "In Folder", "Save To Name", "Save To Folder", "Size", "Type",
                                    "Date Modified"])
        self.table.setRootIsDecorated(False)
        self.table.setEditTriggers(QtWidgets.QTreeWidget.DoubleClicked | QtWidgets.QTreeWidget.EditKeyPressed)
        self.table.itemChanged.connect(self._renamed)
        self.renames = {}       # source path -> Save To Name typed
        self.excluded = set()
        self.table.setMinimumHeight(200)
        lay.addWidget(self.table, 1)
        tools = QtWidgets.QHBoxLayout()

        self.nested = QtWidgets.QRadioButton("Nested view")
        self.nested.setObjectName("SWStyle_PackNested")
        self.flat_view = QtWidgets.QRadioButton("Flat view")
        self.flat_view.setObjectName("SWStyle_PackFlatView")
        self.nested.setChecked(True)
        views = QtWidgets.QButtonGroup(self)
        for b in (self.nested, self.flat_view):
            views.addButton(b)
            tools.addWidget(b)
        self.nested.toggled.connect(self._fill)
        replace = QtWidgets.QPushButton("Select / Replace...")
        replace.setObjectName("SWStyle_PackReplace")
        replace.clicked.connect(self._replace)
        tools.addWidget(replace)
        tools.addStretch(1)
        lay.addLayout(tools)

        dest = QtWidgets.QGroupBox()
        dl = QtWidgets.QGridLayout(dest)
        self.as_folder = QtWidgets.QRadioButton("Save to folder:")
        self.as_zip = QtWidgets.QRadioButton("Save to Zip file:")
        self.as_folder.setChecked(True)
        first = self.docs[0].FileName if self.docs else ""
        start = os.path.dirname(first) if first else os.path.expanduser("~")
        stem = os.path.splitext(os.path.basename(first))[0] if first else _doc_title()
        self.folder = QtWidgets.QLineEdit(os.path.join(start, stem + " Pack and Go"))
        self.zip = QtWidgets.QLineEdit(os.path.join(start, stem + ".zip"))
        for row, (radio, edit) in enumerate(((self.as_folder, self.folder), (self.as_zip, self.zip))):
            browse = QtWidgets.QPushButton("Browse...")
            browse.clicked.connect(lambda _=False, e=edit, z=(radio is self.as_zip): self._browse(e, z))
            dl.addWidget(radio, row, 0)
            dl.addWidget(edit, row, 1)
            dl.addWidget(browse, row, 2)
        self.flatten = QtWidgets.QRadioButton("Flatten to single folder")
        self.flatten.setObjectName("SWStyle_PackFlatten")
        self.minimal = QtWidgets.QRadioButton("Flatten to minimal folders")
        self.minimal.setObjectName("SWStyle_PackMinimal")
        self.keep_paths = QtWidgets.QRadioButton("Keep full folder paths")
        self.keep_paths.setObjectName("SWStyle_PackKeepPaths")
        self.flatten.setChecked(True)
        fgroup = QtWidgets.QButtonGroup(self)
        for b in (self.flatten, self.minimal, self.keep_paths):
            fgroup.addButton(b)
        dl.addWidget(self.flatten, 2, 0)
        dl.addWidget(self.minimal, 2, 1)
        dl.addWidget(self.keep_paths, 2, 2)
        self.email = QtWidgets.QCheckBox("Email after packaging")
        self.email.setObjectName("SWStyle_PackEmail")
        dl.addWidget(self.email, 5, 0, 1, 3)
        self.prefix_on, self.prefix = QtWidgets.QCheckBox("Add prefix:"), QtWidgets.QLineEdit()
        self.suffix_on, self.suffix = QtWidgets.QCheckBox("Add suffix:"), QtWidgets.QLineEdit()
        dl.addWidget(self.prefix_on, 3, 0)
        dl.addWidget(self.prefix, 3, 1)
        dl.addWidget(self.suffix_on, 4, 0)
        dl.addWidget(self.suffix, 4, 1)
        lay.addWidget(dest)
        for w in (self.folder, self.prefix, self.suffix):
            w.textChanged.connect(self._fill)
        for w in (self.prefix_on, self.suffix_on, self.flatten, self.minimal, self.keep_paths, self.as_folder, self.as_zip):
            w.toggled.connect(self._fill)

        bb = QtWidgets.QDialogButtonBox()
        self.save = bb.addButton("Save", QtWidgets.QDialogButtonBox.AcceptRole)
        bb.addButton(QtWidgets.QDialogButtonBox.Cancel)
        bb.addButton(QtWidgets.QDialogButtonBox.Help)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.helpRequested.connect(self._help)
        lay.addWidget(bb)
        self._filling = False
        self._fill()

    def _help(self):
        try:
            from . import helpmenu
            from . import helpguide
            if helpguide.show_topic("pack and go") is None:
                helpmenu.show("home", search="pack and go")
        except Exception as _fw_err:
            _fw_log("filecmds.py:901", _fw_err)

    def _renamed(self, item, column):
        if self._filling:
            return
        if column == 0:
            key = item.data(0, Qt.UserRole)
            if key:
                (self.excluded.discard if item.checkState(0) == Qt.Checked else self.excluded.add)(key)
            return
        if column != 2:
            return
        src = item.data(0, Qt.UserRole)
        if src:
            self.renames[src] = item.text(2)

    def _replace(self):
        """Select / Replace: find text in the Save To Names and replace it."""
        find, ok = QtWidgets.QInputDialog.getText(self, "Select / Replace", "Find in Save To Name:")
        if not ok or not find:
            return
        new, ok = QtWidgets.QInputDialog.getText(self, "Select / Replace", "Replace with:")
        if not ok:
            return
        for d, src, name, folder in self.plan():
            key = src or d.Label
            if find in name:
                self.renames[key] = name.replace(find, new)
        self._fill()

    def extra_files(self):
        """Files beside the documents: drawings of the parts (Include drawings) and the appearance
        images (Include custom decals, appearances and scenes)."""
        out = []
        images = []
        if self.include["drawings"].isChecked():
            for dr, dr_path in drawings_of(self.docs):  # pg95: every drawing of every file packed
                if dr is not None:
                    if dr not in self.docs and dr not in out:
                        out.append(dr)
                elif dr_path not in images:
                    images.append(dr_path)            # a drawing not open: its file is copied as it is
        if self.include["custom_decals"].isChecked():
            for d in self.docs:
                for obj in d.Objects:
                    try:
                        s = getattr(obj, "SWAppearanceImage", None)
                        for key in ("image", "bump"):
                            p = (s or {}).get(key, "")
                            if p and os.path.isfile(p) and p not in images:
                                images.append(p)
                    except Exception as _fw_err:
                        _fw_log("filecmds.py:951", _fw_err)
                        continue
        return out, images

    def _browse(self, edit, as_zip):
        if as_zip:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save to Zip file", edit.text(), "Zip (*.zip)")
        else:
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Save to folder", edit.text())
        if path:
            edit.setText(path)

    def plan(self):
        """[(document, source path, target name, target folder)]"""
        out = []
        base = self.folder.text()
        extra_docs, images = self.extra_files() if hasattr(self, "include") else ([], [])
        # the folders are kept below the deepest folder all the files share (pmfile1 on the PC: the
        # first document was not always the top one, so the part's own folder became the root)
        dirs = [os.path.normpath(os.path.dirname(d.FileName)) for d in list(self.docs) + extra_docs if d.FileName] + \
            [os.path.normpath(os.path.dirname(p)) for p in images if p.lower().endswith(".fcstd")]
        try:
            root = os.path.commonpath(dirs) if dirs else ""
        except ValueError:
            root = dirs[0] if dirs else ""       # files on different drives
        for d in list(self.docs) + extra_docs:
            src = d.FileName
            stem, ext = os.path.splitext(os.path.basename(src)) if src else (d.Label, ".FCStd")
            if self.prefix_on.isChecked():
                stem = self.prefix.text() + stem
            if self.suffix_on.isChecked():
                stem = stem + self.suffix.text()
            name = self.renames.get(src or d.Label, stem + (ext or ".FCStd")) if hasattr(self, "renames") else stem + (ext or ".FCStd")
            out.append((d, src, name, self._folder_for(src, base, root)))
        for p in images:
            name = os.path.basename(p)
            if p.lower().endswith(".fcstd"):          # a drawing file: renamed like the documents
                stem, ext = os.path.splitext(name)
                if self.prefix_on.isChecked():
                    stem = self.prefix.text() + stem
                if self.suffix_on.isChecked():
                    stem = stem + self.suffix.text()
                name = self.renames.get(p, stem + ext) if hasattr(self, "renames") else stem + ext
                out.append((None, p, name, self._folder_for(p, base, root)))   # pg95: kept beside its model
                continue
            out.append((None, p, name, base))
        return out

    def _folder_for(self, src, base, root):
        """The Save To Folder of a file: Flatten to single folder, Flatten to minimal folders (below the
        folder all the files share) or Keep full folder paths."""
        if getattr(self, "keep_paths", None) is not None and self.keep_paths.isChecked() and src:
            # Keep full folder paths: every file under its whole path (drive left out), not the shortest one
            drive, rest = os.path.splitdrive(os.path.dirname(src))
            return os.path.join(base, rest.lstrip("\\/"))
        if not self.flatten.isChecked() and src and root and \
                os.path.normcase(os.path.normpath(os.path.dirname(src))).startswith(os.path.normcase(root)):
            rel = os.path.relpath(os.path.normpath(os.path.dirname(src)), root)
            return base if rel == os.curdir else os.path.join(base, rel)
        return base

    def clashes(self, plan=None):
        ""

        seen = {}
        for d, src, name, folder in (self.packed() if plan is None else plan):
            seen.setdefault(os.path.normcase(os.path.normpath(os.path.join(folder, name))), []).append(
                src or (d.Label if d is not None else name))
        return {k: v for k, v in seen.items() if len(v) > 1}

    def _fill(self, *_):
        self._filling = True
        self.table.clear()
        rows = self.plan()
        clash = self.clashes([r for r in rows if (r[1] or (r[0].Label if r[0] is not None else ""))
                              not in getattr(self, "excluded", set())])
        nested = getattr(self, "nested", None) is not None and self.nested.isChecked()
        parents = pack_parents([r[0] for r in rows]) if nested else {}
        made = {}
        self.table.setRootIsDecorated(nested)
        for d, src, name, folder in rows:
            item = QtWidgets.QTreeWidgetItem(self.table, [os.path.basename(src) if src else d.Label,
                                                          os.path.dirname(src) if src else "", name,
                                                          "(zip)" if self.as_zip.isChecked() else folder]
                                             + _pack_file_info(d, src or name))
            item.setData(0, Qt.UserRole, src or (d.Label if d is not None else ""))
            item.setFlags(item.flags() | Qt.ItemIsEditable | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked if item.data(0, Qt.UserRole) in getattr(self, "excluded", ())
                               else Qt.Checked)
            item.setTextAlignment(4, int(Qt.AlignRight | Qt.AlignVCenter))
            if os.path.normcase(os.path.normpath(os.path.join(folder, name))) in clash:
                for c in (2, 3):
                    item.setForeground(c, QtGui.QColor(200, 0, 0))     # pg95: two files on one Save To path
                item.setToolTip(2, "Another file is saved under this name in this folder")
            if d is not None:
                made.setdefault(d.Name, item)
        for name, item in made.items():         # Nested view: under the document that uses it
            up = made.get(parents.get(name))
            if up is not None and up is not item:
                self.table.takeTopLevelItem(self.table.indexOfTopLevelItem(item))
                up.addChild(item)
        self.table.expandAll()
        for i in range(7):
            self.table.resizeColumnToContents(i)
        self._filling = False

    def packed(self):
        """The rows that are packed: the ticked ones (exportopts-1119)."""
        out = getattr(self, "excluded", set())
        return [r for r in self.plan() if (r[1] or (r[0].Label if r[0] is not None else "")) not in out]

    def accept(self):
        clash = self.clashes()
        if clash:
            names = sorted({os.path.basename(k) for k in clash})
            QtWidgets.QMessageBox.warning(self, "Pack and Go", "More than one file would be saved as %s. Change the "
                                          "Save To Name of one of them, or pick Flatten to minimal folders."
                                          % ", ".join(names))
            return
        try:
            plan = self.packed()
            if self.as_zip.isChecked():
                work = tempfile.mkdtemp(prefix="freeworks-packandgo-")
                written = self._write(plan, work)
                with zipfile.ZipFile(self.zip.text(), "w", zipfile.ZIP_DEFLATED) as z:
                    for path in written:
                        z.write(path, os.path.relpath(path, work))
                shutil.rmtree(work, ignore_errors=True)
            else:
                self._write(plan, None)
            if self.email.isChecked():
                target = self.zip.text() if self.as_zip.isChecked() else self.folder.text()
                send_file(target)
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, "Pack and Go", "Pack and Go did not finish: %s" % error)
            return
        super().accept()

    def _write(self, plan, work):
        written = []
        base = self.folder.text()
        for d, src, name, folder in plan:
            if work is not None:
                folder = os.path.join(work, os.path.relpath(folder, base)) if folder != base else work
            os.makedirs(folder, exist_ok=True)
            target = os.path.join(folder, name)
            if d is None:
                shutil.copy2(src, target)       # an appearance image
            else:
                d.saveCopy(target)
                inc = getattr(self, "include", {}).get("simulation")
                if inc is not None and not inc.isChecked() and simulation_results(d):
                    strip_results(target)       # exportopts-1119: Include simulation results off
            written.append(target)
        return written


def simulation_results(doc):
    """The FEM result objects of a document (results, their meshes and post-processing pipelines)."""
    out = []
    for o in doc.Objects:
        t = o.TypeId
        if t.startswith("Fem::FemResultObject") or t.startswith("Fem::FemPost"):
            out.append(o)
            mesh = getattr(o, "Mesh", None)
            if mesh is not None and hasattr(mesh, "TypeId") and mesh not in out:
                out.append(mesh)
    return out


def strip_results(path):
    """Leaves the simulation results out of a packed copy (the original document is not changed)."""
    before = set(App.listDocuments())
    active = App.ActiveDocument
    try:
        copy = App.openDocument(path, hidden=True)
    except TypeError:
        copy = App.openDocument(path)
    try:
        for o in reversed(simulation_results(copy)):
            try:
                copy.removeObject(o.Name)
            except Exception as _fw_err:
                _fw_log("filecmds.py:strip_results", _fw_err)
        copy.save()
    finally:
        if copy.Name not in before:
            App.closeDocument(copy.Name)
        if active is not None and active.Name in App.listDocuments():
            App.setActiveDocument(active.Name)          # the packed document stays the active one


def send_to():
    ""


    doc = App.ActiveDocument
    if doc is None:
        return False
    folder = tempfile.mkdtemp(prefix="freeworks-sendto-")
    name = os.path.basename(doc.FileName) if doc.FileName else doc.Label + ".FCStd"
    path = os.path.join(folder, name)
    doc.saveCopy(path)
    return send_file(path)


def zip_folder(path):
    """The folder zipped beside it (Pack and Go's Email); file-in-use markers are left out (fh163)."""
    zipped = path.rstrip("\\/") + ".zip"
    with zipfile.ZipFile(zipped, "w", zipfile.ZIP_DEFLATED) as z:
        for root_, _dirs, files in os.walk(path):
            for f in files:
                if f.startswith(".~$") and f.lower().endswith(".lck"):
                    continue
                full = os.path.join(root_, f)
                z.write(full, os.path.relpath(full, path))
    return zipped


def send_file(path):
    """A new mail message with the file (or a zip of the folder) attached; Pack and Go's Email after packaging."""
    if os.path.isdir(path):
        path = zip_folder(path)
    folder = os.path.dirname(path)
    name = os.path.basename(path)
    if sys.platform != "win32":
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder))
        return True
    from ctypes import wintypes

    class MapiFileDescW(ctypes.Structure):
        _fields_ = [("ulReserved", wintypes.ULONG), ("flFlags", wintypes.ULONG), ("nPosition", wintypes.ULONG),
                    ("lpszPathName", wintypes.LPWSTR), ("lpszFileName", wintypes.LPWSTR), ("lpFileType", ctypes.c_void_p)]

    class MapiMessageW(ctypes.Structure):
        _fields_ = [("ulReserved", wintypes.ULONG), ("lpszSubject", wintypes.LPWSTR),
                    ("lpszNoteText", wintypes.LPWSTR), ("lpszMessageType", wintypes.LPWSTR),
                    ("lpszDateReceived", wintypes.LPWSTR), ("lpszConversationID", wintypes.LPWSTR),
                    ("flFlags", wintypes.ULONG), ("lpOriginator", ctypes.c_void_p), ("nRecipCount", wintypes.ULONG),
                    ("lpRecips", ctypes.c_void_p), ("nFileCount", wintypes.ULONG),
                    ("lpFiles", ctypes.POINTER(MapiFileDescW))]
    attach = MapiFileDescW(0, 0, 0xFFFFFFFF, path, name, None)
    message = MapiMessageW(0, name, "", None, None, None, 0, None, 0, None, 1, ctypes.pointer(attach))
    try:
        mapi = ctypes.WinDLL("mapi32.dll")
        send = mapi.MAPISendMailW
        send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(MapiMessageW), wintypes.ULONG, wintypes.ULONG]
        hwnd = int(Gui.getMainWindow().winId())
        result = send(None, hwnd, ctypes.byref(message), 0x1 | 0x8, 0)    # MAPI_LOGON_UI | MAPI_DIALOG
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Send To mail not opened: %s\n" % error)
        result = -1
    if result not in (0, 1):            # SUCCESS_SUCCESS, MAPI_USER_ABORT
        # no mail program answers Simple MAPI: show the file to attach by hand
        os.startfile(folder)
    return True


# ------------------------------------------------------------------ Open Drawing, Browse Recent Folders
def drawing_of(doc=None):
    ""


    doc = doc or App.ActiveDocument
    if doc is None:
        return None, ""
    for other in App.listDocuments().values():
        if other is doc:
            continue
        for obj in other.Objects:
            if obj.TypeId.startswith("TechDraw::DrawViewPart"):
                for src in list(getattr(obj, "Source", []) or []) + _fw_unsplit(getattr(obj, "XSource", [])):
                    if getattr(src, "Document", None) is doc:
                        return other, other.FileName
    if doc.FileName:
        folder = os.path.dirname(doc.FileName)
        stem = os.path.splitext(os.path.basename(doc.FileName))[0]
        for name in (doc.Label + " Drawing.FCStd", stem + " Drawing.FCStd", stem + "-Drawing.FCStd"):
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                return None, path
    return None, ""


def drawings_of(docs):
    ""


    docs = [d for d in docs if d is not None]
    out, seen = [], set()

    def add(dr, path):
        key = dr.Name if dr is not None else os.path.normcase(os.path.normpath(path))
        if key not in seen and dr not in docs:
            seen.add(key)
            if dr is not None and dr.FileName:
                seen.add(os.path.normcase(os.path.normpath(dr.FileName)))
            out.append((dr, path))
    for d in docs:
        try:
            dr, path = drawing_of(d)
        except Exception:
            dr, path = None, ""
        if dr is not None or (path and os.path.isfile(path)):
            add(dr, path)
    names = {d.Name for d in docs}
    for other in App.listDocuments().values():
        if other in docs or not _is_drawing_doc(other):
            continue
        for obj in other.Objects:
            if obj.TypeId.startswith("TechDraw::DrawViewPart") and any(
                    getattr(getattr(x, "Document", None), "Name", None) in names
                    for x in list(getattr(obj, "Source", []) or []) + _fw_unsplit(getattr(obj, "XSource", []))):
                add(other, other.FileName)
                break
    files = {os.path.normcase(os.path.normpath(d.FileName)) for d in docs if d.FileName}
    open_files = {os.path.normcase(os.path.normpath(d.FileName)) for d in App.listDocuments().values() if d.FileName}
    folders = []
    for f in sorted(files):
        if os.path.dirname(f) not in folders:
            folders.append(os.path.dirname(f))
    try:
        from . import fcstdinfo
    except Exception:
        return out
    for folder in folders:
        try:
            names_here = sorted(os.listdir(folder))[:2000]
        except OSError:
            continue
        for n in names_here:
            path = os.path.join(folder, n)
            key = os.path.normcase(os.path.normpath(path))
            if not n.lower().endswith(".fcstd") or key in files or key in seen or key in open_files:
                continue
            i = fcstdinfo.info(path)
            if i and i["kind"] == "drawing" and any(os.path.normcase(os.path.normpath(r)) in files
                                                     for r in i["references"]):
                add(None, path)
    return out


def open_drawing():
    doc = App.ActiveDocument
    open_doc, path = drawing_of(doc)
    if open_doc is not None:
        for view in Gui.getDocument(open_doc.Name).mdiViewsOfType("TechDrawGui::MDIViewPage") \
                if hasattr(Gui.getDocument(open_doc.Name), "mdiViewsOfType") else []:
            Gui.getMainWindow().setActiveWindow(view)
            return True
        Gui.getDocument(open_doc.Name).setEdit(next(
            (o for o in open_doc.Objects if o.TypeId == "TechDraw::DrawPage"), open_doc.Objects[0]).Name)
        return True
    if path:
        App.openDocument(path)
        for obj in App.ActiveDocument.Objects:
            if obj.TypeId == "TechDraw::DrawPage":
                obj.ViewObject.doubleClicked()
                break
        return True
    QtWidgets.QMessageBox.information(Gui.getMainWindow(), "FreeCAD",
                                      "Unable to locate the drawing file for %s." % (doc.Label if doc else ""))
    return False


def recent_folders():
    """The folders of the recent documents, newest first, each once."""
    from . import swkeys
    out = []
    for text, _action in swkeys.recent_actions():
        folder = os.path.dirname(text.replace("&", ""))
        if folder and folder not in out and os.path.isdir(folder):
            out.append(folder)
    return out


def browse_recent_folders(pos=None):
    ""

    menu = QtWidgets.QMenu(Gui.getMainWindow())
    menu.setObjectName("SWRecentFolders")
    menu.setAttribute(Qt.WA_DeleteOnClose, True)
    folders = recent_folders()
    if not folders:
        menu.addAction("No recent folders").setEnabled(False)
    for folder in folders:
        act = menu.addAction(folder)
        act.triggered.connect(lambda checked=False, f=folder: QtCore.QTimer.singleShot(0, lambda: _open_in(f)))
    menu.popup(pos or QtGui.QCursor.pos())
    return menu


def _open_in(folder):
    path, _ = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Open", folder,
                                                    "FreeCAD documents (*.FCStd);;All files (*.*)")
    if path:
        App.openDocument(path)


# ------------------------------------------------------------------ commands
def _has_doc():
    return App.ActiveDocument is not None and Gui.ActiveDocument is not None


class _Cmd:
    MENU = TIP = ""
    PIXMAP = ""

    def GetResources(self):
        res = {"MenuText": self.MENU, "ToolTip": self.TIP}
        if self.PIXMAP:
            res["Pixmap"] = self.PIXMAP
        if getattr(self, "FOR_EDIT", False):
            res["CmdType"] = "ForEdit"
        return res

    def IsActive(self):
        return _has_doc()


class OpenDrawingCommand(_Cmd):
    MENU, TIP = "Open Drawing", "Opens the drawing of the active part or assembly"

    def Activated(self):
        open_drawing()

    def IsActive(self):
        doc = App.ActiveDocument
        return doc is not None and not any(o.TypeId == "TechDraw::DrawPage" for o in doc.Objects)


class BrowseRecentFoldersCommand(_Cmd):
    MENU, TIP = "Browse Recent Folders...", "The folders of the recent documents at the pointer"

    def Activated(self):

        # the pointer stays as the fallback
        try:
            from . import recentdocs
            recentdocs.show(tab=1)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: recent folders: %s\n" % error)
            browse_recent_folders()

    def IsActive(self):
        return True


class PageSetupCommand(_Cmd):
    MENU, TIP, PIXMAP = "Page Setup...", "Sets the paper, orientation, scale and margins for printing", "document-print-preview"

    def Activated(self):
        PageSetupDialog().exec()


class PrintCommand(_Cmd):
    MENU, TIP, PIXMAP = "Print...", "Prints the active document (Ctrl+P)", "document-print"
    FOR_EDIT = True

    def Activated(self):
        PrintDialog().exec()

    def IsActive(self):
        return _has_doc() and hasattr(Gui.ActiveDocument.ActiveView, "saveImage")


class PrintPreviewCommand(_Cmd):
    MENU, TIP, PIXMAP = "Print Preview...", "Shows the page as it will print", "document-print-preview"

    def Activated(self):
        PrintPreviewDialog().exec()

    def IsActive(self):
        return _has_doc() and hasattr(Gui.ActiveDocument.ActiveView, "saveImage")


class Print3DCommand(_Cmd):
    MENU, TIP = "Print3D...", "Gets the part ready for a 3D printer and sends it to a slicer"

    def Activated(self):
        try:
            from . import print3d
            print3d.show()
            return
        except Exception as _fw_err:
            _fw_log("filecmds.py Print3D", _fw_err)
        for name in ("SWStyle_SlicerOrca", "SWStyle_SlicerBambu"):
            if name in Gui.listCommands():
                Gui.runCommand(name, 0)
                return


class PackAndGoCommand(_Cmd):
    MENU, TIP = "Pack and Go...", "Gathers the document and every file it references into a folder or Zip file"

    def Activated(self):
        PackAndGoDialog().exec()


class SendToCommand(_Cmd):
    MENU, TIP = "Send To...", "Sends the document by mail"

    def Activated(self):
        send_to()


# --------------------------------------------------------------------------- Reload
READ_ONLY = "SWReadOnly"


_READ_ONLY_DOCS = set()
_RO_WATCH = []


class _ReadOnlyWatch:
    def slotDeletedDocument(self, doc):
        try:
            _READ_ONLY_DOCS.discard(doc.Name)
        except Exception as _fw_err:
            _fw_log("filecmds.py:_ReadOnlyWatch", _fw_err)


def is_read_only(doc):
    try:
        return doc.Name in _READ_ONLY_DOCS
    except Exception as _fw_err:
        _fw_log("filecmds.py:1304", _fw_err)
        return False


def read_only_message(doc):
    ""
    name = os.path.basename(doc.FileName) if doc.FileName else doc.Label
    return "%s was opened read-only and cannot be saved over. Use File > Save As to save it under a new name." % name


def set_read_only(doc, on):
    ""


    if not _RO_WATCH:
        _RO_WATCH.append(_ReadOnlyWatch())
        App.addDocumentObserver(_RO_WATCH[0])
    try:
        gdoc = Gui.getDocument(doc.Name)
        was = bool(gdoc.Modified) if gdoc is not None else None
    except Exception:
        gdoc, was = None, None
    if on:
        _READ_ONLY_DOCS.add(doc.Name)
    else:
        _READ_ONLY_DOCS.discard(doc.Name)
    for obj in doc.Objects:
        for prop in obj.PropertiesList:
            try:
                if on:
                    obj.setPropertyStatus(prop, "ReadOnly")
                else:
                    obj.setPropertyStatus(prop, "-ReadOnly")
            except Exception as _fw_err:
                _fw_log("filecmds.py:1315", _fw_err)
    meta = dict(doc.Meta or {})
    if READ_ONLY in meta:
        meta.pop(READ_ONLY, None)
        doc.Meta = meta
    if gdoc is not None and was is False:
        try:
            gdoc.Modified = False       # marking it read-only is not a change to save
        except Exception as _fw_err:
            _fw_log("filecmds.py:set_read_only", _fw_err)


def _modified(doc):
    """Changes not saved: FreeCAD keeps that on the GUI document (the App document has no Modified),
    so the Reload box said Unchanged and gave no warning before dropping the changes."""
    try:
        gdoc = Gui.getDocument(doc.Name)
        if gdoc is not None:
            return bool(gdoc.Modified)
    except Exception as _fw_err:
        _fw_log("filecmds.py:1332", _fw_err)
    try:
        return bool(getattr(doc, "Modified", False)) or any("Touched" in o.State for o in doc.Objects)
    except Exception as _fw_err:
        _fw_log("filecmds.py:1339", _fw_err)
        return False


def reload_document(doc):
    """Reads the document again from its file, dropping the changes. The document read, or False."""
    if not doc.FileName:
        return False
    name, path = doc.Name, doc.FileName
    try:
        # closed and read again from its file here, not with Std_Revert: FreeCAD's Revert asks again
        # (Reload asked already) and, answered by its default No, left the changes in place
        was_active = App.ActiveDocument is not None and App.ActiveDocument.Name == name
        App.closeDocument(name)
        again = App.openDocument(path)
        if was_active:
            App.setActiveDocument(again.Name)
            try:
                Gui.setActiveDocument(again.Name)
            except Exception as _fw_err:
                _fw_log("filecmds.py:1355", _fw_err)
        return again
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not reloaded: %s\n" % (doc.Label, error))
        return False


class ReloadDialog(QtWidgets.QDialog):
    ""


    def __init__(self, doc=None, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWStyle_Reload")
        self.setWindowTitle("Reload")
        self.resize(620, 360)
        self.doc = doc or App.ActiveDocument
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Reload the documents from disk, or make them read-only. Reloading drops the changes not saved."))
        self.table = QtWidgets.QTableWidget(0, 4, self)
        self.table.setObjectName("SWStyle_ReloadTable")
        self.table.setHorizontalHeaderLabels(["Name", "Reload", "Read-only", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.table.setSelectionBehavior(QtWidgets.QTableWidget.SelectRows)
        self.table.setEditTriggers(QtWidgets.QTableWidget.NoEditTriggers)
        lay.addWidget(self.table, 1)
        self.show_all = QtWidgets.QCheckBox("Show all open documents", self)
        self.show_all.setObjectName("SWStyle_ReloadShowAll")
        self.show_all.toggled.connect(lambda _on: self.fill())
        lay.addWidget(self.show_all)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.setObjectName("SWStyle_ReloadButtons")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.docs = []
        self.fill()

    def documents(self):
        if self.doc is None:
            return []
        out = [self.doc]
        try:
            from . import saveas
            out += [d for d in saveas.referenced_documents(self.doc) if d not in out]
        except Exception as _fw_err:
            _fw_log("filecmds.py:1401", _fw_err)
        if self.show_all.isChecked():
            out += [d for d in App.listDocuments().values() if d not in out]
        return out

    def fill(self):
        self.docs = self.documents()
        self.table.setRowCount(0)
        for doc in self.docs:
            r = self.table.rowCount()
            self.table.insertRow(r)
            name = QtWidgets.QTableWidgetItem(doc.Label + ("" if doc.FileName else "  (not saved)"))
            name.setToolTip(doc.FileName or "")
            self.table.setItem(r, 0, name)
            reload = QtWidgets.QTableWidgetItem()
            reload.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled if doc.FileName else QtCore.Qt.ItemIsEnabled)
            reload.setCheckState(QtCore.Qt.Checked if doc is self.doc and doc.FileName else QtCore.Qt.Unchecked)
            self.table.setItem(r, 1, reload)
            ro = QtWidgets.QTableWidgetItem()
            ro.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
            ro.setCheckState(QtCore.Qt.Checked if is_read_only(doc) else QtCore.Qt.Unchecked)
            self.table.setItem(r, 2, ro)
            status = "Read-only" if is_read_only(doc) else ("Modified" if _modified(doc) else "Unchanged")
            self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(status))

    def choices(self):
        """[(doc, reload, read_only)] as ticked."""
        out = []
        for r, doc in enumerate(self.docs):
            out.append((doc, self.table.item(r, 1).checkState() == QtCore.Qt.Checked,
                        self.table.item(r, 2).checkState() == QtCore.Qt.Checked))
        return out

    def accept(self):
        choices = self.choices()
        changed = [d.Label for d, reload, _ro in choices if reload and _modified(d)]
        if changed:
            answer = QtWidgets.QMessageBox.question(
                self, "Reload", "Reloading drops the changes not saved in:\n%s\nReload anyway?" % "\n".join(changed),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
            if answer != QtWidgets.QMessageBox.Yes:
                return
        self.done_count = 0
        active = App.ActiveDocument
        for doc, reload, ro in choices:
            if reload:
                again = reload_document(doc)
                if again:
                    self.done_count += 1
                    doc = again         # read-only goes on the document as read again
            if ro != is_read_only(doc):
                set_read_only(doc, ro)
        try:
            if active is not None and active.Name in App.listDocuments():
                App.setActiveDocument(active.Name)
        except Exception as _fw_err:
            _fw_log("filecmds.py:1457", _fw_err)
        super().accept()


class ReloadCommand(_Cmd):
    MENU, TIP = "Reload", "Reloads the document and the documents it references from disk, or makes them read-only."

    def Activated(self):
        box = ReloadDialog()
        box.exec()


class FindReferencesCommand(_Cmd):
    MENU, TIP = "Find References...", "Lists the full path of every file the document uses"

    def Activated(self):
        FindReferencesDialog().exec()


COMMANDS = (
    ("SWStyle_OpenDrawing", OpenDrawingCommand),
    ("SWStyle_BrowseRecentFolders", BrowseRecentFoldersCommand),
    ("SWStyle_PageSetup", PageSetupCommand),
    ("SWStyle_Print", PrintCommand),
    ("SWStyle_PrintPreview", PrintPreviewCommand),
    ("SWStyle_Print3D", Print3DCommand),
    ("SWStyle_PackAndGo", PackAndGoCommand),
    ("SWStyle_SendTo", SendToCommand),
    ("SWStyle_FindReferences", FindReferencesCommand),
    ("SWStyle_Reload", ReloadCommand),
)


def _take_ctrl_p():
    ""
    try:
        native = Gui.Command.get("Std_Print")
        if native is not None and native.getShortcut() == "Ctrl+P":
            native.setShortcut("")
        mine = Gui.Command.get("SWStyle_Print")
        if mine is not None and not mine.getShortcut():
            mine.setShortcut("Ctrl+P")
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Ctrl+P not moved to Print: %s\n" % error)


def register():
    have = set(Gui.listCommands())
    for name, cls in COMMANDS:
        if name not in have:
            Gui.addCommand(name, cls())
    _take_ctrl_p()
