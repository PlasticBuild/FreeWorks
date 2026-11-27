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
import re
import shutil

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets
from . import drawlive as DL


# formats (sheetformats/ next to this file: our own title block, its fields linked to properties); the rest are
# FreeCAD's TechDraw templates, kept under "(FreeCAD)" names (Only show standard formats off) so none is lost.
SIZES = [
    ("A (ANSI) Landscape", "FW:ANSI", "FW_ANSI_A_Landscape.svg", "FW_ANSI_A_Landscape_blank.svg", True),
    ("A (ANSI) Portrait", "FW:ANSI", "FW_ANSI_A_Portrait.svg", "FW_ANSI_A_Portrait_blank.svg", True),
    ("B (ANSI) Landscape", "FW:ANSI", "FW_ANSI_B_Landscape.svg", "FW_ANSI_B_Landscape_blank.svg", True),
    ("C (ANSI) Landscape", "FW:ANSI", "FW_ANSI_C_Landscape.svg", "FW_ANSI_C_Landscape_blank.svg", True),
    ("D (ANSI) Landscape", "FW:ANSI", "FW_ANSI_D_Landscape.svg", "FW_ANSI_D_Landscape_blank.svg", True),
    ("E (ANSI) Landscape", "FW:ANSI", "FW_ANSI_E_Landscape.svg", "FW_ANSI_E_Landscape_blank.svg", True),
    ("A0 (ISO)", "FW:ISO", "FW_ISO_A0_Landscape.svg", "FW_ISO_A0_Landscape_blank.svg", True),
    ("A1 (ISO)", "FW:ISO", "FW_ISO_A1_Landscape.svg", "FW_ISO_A1_Landscape_blank.svg", True),
    ("A2 (ISO)", "FW:ISO", "FW_ISO_A2_Landscape.svg", "FW_ISO_A2_Landscape_blank.svg", True),
    ("A3 (ISO)", "FW:ISO", "FW_ISO_A3_Landscape.svg", "FW_ISO_A3_Landscape_blank.svg", True),
    ("A4 (ISO)", "FW:ISO", "FW_ISO_A4_Landscape.svg", "FW_ISO_A4_Landscape_blank.svg", True),
    ("A4 (ISO) Portrait", "FW:ISO", "FW_ISO_A4_Portrait.svg", "FW_ISO_A4_Portrait_blank.svg", True),
    ("A (ANSI) Landscape (FreeCAD)", "ASME", "ANSIA_Landscape.svg", "ANSIA_Landscape_blank.svg", False),
    ("A (ANSI) Portrait (FreeCAD)", "ASME", "ANSIA_Portrait.svg", "ANSIA_Portrait_blank.svg", False),
    ("B (ANSI) Landscape (FreeCAD)", "ASME", "ANSIB_Landscape.svg", "ANSIB_Landscape_blank.svg", False),
    ("C (ANSI) Landscape (FreeCAD)", "ASME", "ANSIC_Landscape.svg", "", False),
    ("D (ANSI) Landscape (FreeCAD)", "ASME", "ANSID_Landscape.svg", "", False),
    ("E (ANSI) Landscape (FreeCAD)", "ASME", "ANSIE_Landscape.svg", "", False),
    ("A0 (ISO) (FreeCAD)", "ISO", "A0_Landscape_ISO5457_minimal.svg", "A0_Landscape_blank.svg", False),
    ("A1 (ISO) (FreeCAD)", "ISO", "A1_Landscape_ISO5457_minimal.svg", "A1_Landscape_blank.svg", False),
    ("A2 (ISO) (FreeCAD)", "ISO", "A2_Landscape_ISO5457_minimal.svg", "A2_Landscape_blank.svg", False),
    ("A3 (ISO) (FreeCAD)", "ISO", "A3_Landscape_ISO5457_minimal.svg", "A3_Landscape_blank.svg", False),
    ("A4 (ISO) (FreeCAD)", "ISO", "A4_Landscape_ISO5457_minimal.svg", "A4_Landscape_blank.svg", False),
    ("A4 (ISO) Portrait (FreeCAD)", "ISO", "A4_Portrait_ISO5457_minimal.svg", "A4_Portrait_blank.svg", False),
    ("Letter Landscape", "ASME", "USLetter_Landscape.svg", "USLetter_Landscape_blank.svg", False),
    ("Arch A Landscape", "ASME", "Arch_A_Landscape.svg", "", False),
    ("Arch B Landscape", "ASME", "Arch_B_Landscape.svg", "", False),
    ("Arch C Landscape", "ASME", "Arch_C_Landscape.svg", "", False),
    ("Arch D Landscape", "ASME", "Arch_D_Landscape.svg", "", False),
    ("Arch E Landscape", "ASME", "Arch_E_Landscape.svg", "", False),
]
DEFAULT = "A (ANSI) Landscape"


def template_root():
    for root in (App.getResourceDir(), os.path.join(App.getResourceDir(), "share")):
        path = os.path.join(root, "Mod", "TechDraw", "Templates")
        if os.path.isdir(path):
            return path
    return ""


def formats_root():
    ""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "sheetformats")


def folder_path(folder):
    if folder.startswith("FW:"):
        return os.path.join(formats_root(), folder[3:])
    return os.path.join(template_root(), folder)


def size_path(name, with_format=True):
    """The sheet format file of a size from SIZES (the blank one when with_format is False), else ""."""
    for n, folder, fmt, blank, _ in SIZES:
        if n == name:
            path = os.path.join(folder_path(folder), fmt if with_format or not blank else blank)
            if not with_format and not blank:
                w, h = svg_size(path)
                return blank_sheet(w, h)
            return path if os.path.isfile(path) else ""
    return ""


def own_format(path):
    ""
    base = os.path.basename(path or "")
    for n, folder, fmt, blank, _ in SIZES:
        if not folder.startswith("FW:") and base in (fmt, blank) and n.endswith(" (FreeCAD)"):
            return size_path(n[:-len(" (FreeCAD)")], base == fmt or not blank)
    return ""


def svg_size(path):
    """(width, height) in mm from an SVG's width/height (mm, or plain numbers taken as mm)."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            head = f.read(4000)
        tag = re.search(r"<svg\b[^>]*>", head, re.S).group(0)
        w = float(re.search(r'\bwidth="([\d.]+)', tag).group(1))
        h = float(re.search(r'\bheight="([\d.]+)', tag).group(1))
        return w, h
    except Exception:
        return 279.4, 215.9


def _sheets_dir():
    path = os.path.join(App.getUserAppDataDir(), "FreeWorks", "sheets")
    os.makedirs(path, exist_ok=True)
    return path


def saved_formats():
    ""
    out = []
    try:
        d = _sheets_dir()
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".svg") and not f.startswith("custom_"):
                out.append((os.path.splitext(f)[0].replace("_", " ") + " (saved)", os.path.join(d, f)))
    except Exception as _fw_err:
        _fw_log("drawsheet.py:140", _fw_err)
    return out


def blank_sheet(w, h):
    ""

    path = os.path.join(_sheets_dir(), "custom_%gx%g.svg" % (w, h))
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write('<svg width="%gmm" height="%gmm" viewBox="0 0 %g %g" version="1.1" '
                    'xmlns="http://www.w3.org/2000/svg" '
                    'xmlns:freecad="https://www.freecad.org/wiki/index.php?title=Svg_Namespace">\n'
                    '<rect x="0" y="0" width="%g" height="%g" fill="none" stroke="#000" stroke-width="0.35"/>\n'
                    '</svg>\n' % (w, h, w, h, w, h))
    return path


def page_template_path(page):
    """The sheet format's own file (not the blue copy shown while Edit Sheet Format is on)."""
    real = getattr(page, "FreeWorksFormatFile", "")
    if real:
        return real
    try:
        return page.Template.Template
    except Exception:
        return ""


class _Untinted(object):
    """The sheet format back in its own colours for a while (Save / Reload / a new format while it is edited)."""
    def __init__(self, page):
        self.page = page
        self.tinted = bool(getattr(page, "FreeWorksFormatFile", ""))

    def __enter__(self):
        if self.tinted:
            tint_format(self.page, False)
        return self

    def __exit__(self, *exc):
        if self.tinted and editing_format(self.page):
            tint_format(self.page, True)
        return False


def describe(path):
    ""
    base = os.path.basename(path or "")
    for n, folder, fmt, blank, _ in SIZES:
        if base in (fmt, blank):
            return n
    return base


# --------------------------------------------------------------------------- Sheet Format/Size
class SheetFormatBox(QtWidgets.QWidget):
    ""

    def __init__(self, parent=None, current="", standard=None):
        super().__init__(parent)
        self.setObjectName("SWSheetFormat")

        self.family = None
        if standard:
            self.family = "ANSI" if str(standard).upper().startswith(("ANSI", "ASME")) else "ISO"
        lay = QtWidgets.QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        left = QtWidgets.QVBoxLayout()
        self.standard = QtWidgets.QRadioButton("Standard sheet size", self)
        self.standard.setObjectName("SWSheetStandard")
        self.only = QtWidgets.QCheckBox("Only show standard formats", self)
        self.only.setObjectName("SWSheetOnlyStandard")
        self.only.setChecked(True)
        self.sizes = QtWidgets.QListWidget(self)
        self.sizes.setObjectName("SWSheetSizes")
        self.sizes.setMinimumHeight(150)
        self.file = QtWidgets.QLineEdit(self)
        self.file.setObjectName("SWSheetFile")
        self.file.setReadOnly(True)
        self.browse = QtWidgets.QPushButton("Browse...", self)
        self.browse.setObjectName("SWSheetBrowse")
        self.display = QtWidgets.QCheckBox("Display sheet format", self)
        self.display.setObjectName("SWSheetDisplayFormat")
        self.display.setChecked(True)
        self.custom = QtWidgets.QRadioButton("Custom sheet size", self)
        self.custom.setObjectName("SWSheetCustom")
        self.width = QtWidgets.QDoubleSpinBox(self)
        self.width.setObjectName("SWSheetWidth")
        self.height = QtWidgets.QDoubleSpinBox(self)
        self.height.setObjectName("SWSheetHeight")
        for s in (self.width, self.height):
            s.setRange(10, 5000)
            s.setDecimals(2)
            s.setSuffix("mm")
        self.width.setValue(279.4)
        self.height.setValue(215.9)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.file, 1)
        row.addWidget(self.browse)
        dims = QtWidgets.QHBoxLayout()
        dims.addWidget(QtWidgets.QLabel("Width:", self))
        dims.addWidget(self.width)
        dims.addWidget(QtWidgets.QLabel("Height:", self))
        dims.addWidget(self.height)
        for w in (self.standard, self.only, self.sizes):
            left.addWidget(w)
        left.addLayout(row)
        left.addWidget(self.display)
        left.addWidget(self.custom)
        left.addLayout(dims)
        lay.addLayout(left, 0, 0)
        right = QtWidgets.QVBoxLayout()
        right.addWidget(QtWidgets.QLabel("Preview:", self))
        self.preview = QtWidgets.QLabel(self)
        self.preview.setObjectName("SWSheetPreview")
        self.preview.setFixedSize(220, 170)
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setFrameShape(QtWidgets.QFrame.Box)
        right.addWidget(self.preview)
        self.size_label = QtWidgets.QLabel("", self)
        self.size_label.setObjectName("SWSheetSizeLabel")
        right.addWidget(self.size_label)
        right.addStretch(1)
        lay.addLayout(right, 0, 1)
        self.extra = {}       # browsed file name -> path
        self.saved = {}       # saved sheet format name -> path
        self.only.toggled.connect(self.fill)
        self.sizes.currentItemChanged.connect(lambda *_: self.update_preview())
        self.browse.clicked.connect(self.browse_file)
        self.display.toggled.connect(lambda *_: self.update_preview())
        self.standard.toggled.connect(self._mode)
        self.custom.toggled.connect(self._mode)
        self.width.valueChanged.connect(lambda *_: self.update_preview())
        self.height.valueChanged.connect(lambda *_: self.update_preview())
        self.fill()
        self.set_current(current)

    def fill(self, *_):
        keep = self.current_name()
        self.sizes.blockSignals(True)
        self.sizes.clear()
        for n, folder, fmt, blank, std in SIZES:
            if self.only.isChecked() and self.family and "(%s)" % self.family not in n:
                continue
            if std or not self.only.isChecked():
                if os.path.isfile(os.path.join(folder_path(folder), fmt)):
                    self.sizes.addItem(n)
        for n in self.extra:
            self.sizes.addItem(n)
        if not self.only.isChecked():

            for n, path in saved_formats():
                if n not in self.extra and not self.sizes.findItems(n, QtCore.Qt.MatchExactly):
                    self.saved[n] = path
                    self.sizes.addItem(n)
        self.sizes.blockSignals(False)
        self.select(keep or DEFAULT)

    def select(self, name):
        items = self.sizes.findItems(name, QtCore.Qt.MatchExactly)
        if items:
            self.sizes.setCurrentItem(items[0])
        elif self.sizes.count():
            self.sizes.setCurrentRow(0)
        self.update_preview()

    def set_current(self, path):
        """Show path (a sheet's present format) as the choice."""
        self.standard.setChecked(True)
        if not path:
            self.select(DEFAULT)
            return
        base = os.path.basename(path)
        if base.startswith("custom_"):
            w, h = svg_size(path)
            self.custom.setChecked(True)
            self.width.setValue(w)
            self.height.setValue(h)
            return
        name = describe(path)
        known = any(name == s[0] for s in SIZES)
        if not known:
            self.extra[name] = path
            self.fill()
        else:
            if not any(name == s[0] and s[4] for s in SIZES) or not self.sizes.findItems(name, QtCore.Qt.MatchExactly):
                self.only.setChecked(False)           # the sheet's own format is always in the list
            self.display.setChecked(not any(base == s[3] for s in SIZES if s[3]))
        self.select(name)

    def current_name(self):
        item = self.sizes.currentItem() if hasattr(self, "sizes") else None
        return item.text() if item is not None else ""

    def _mode(self, *_):
        # never greyed (drawings-land287): a size picked turns Standard on, a width or height typed turns Custom on
        if not getattr(self, "_fw_live", False):
            self._fw_live = True
            DL.sets(self.custom, True, self.width, self.height)
            DL.sets(self.standard, True, self.only, self.browse, self.display)
            self.sizes.itemClicked.connect(lambda *_: self.standard.isChecked() or self.standard.setChecked(True))
        self.update_preview()

    def browse_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open", formats_root(), "Sheet format (*.svg)")
        if path:
            self.add_file(path)

    def add_file(self, path):
        name = os.path.basename(path)
        self.extra[name] = path
        self.standard.setChecked(True)
        self.fill()
        self.select(name)

    def chosen(self):
        """The sheet format file the box stands for."""
        if self.custom.isChecked():
            return blank_sheet(round(self.width.value(), 2), round(self.height.value(), 2))
        name = self.current_name()
        if name in self.extra:
            return self.extra[name]
        if name in self.saved:
            return self.saved[name]
        return size_path(name, self.display.isChecked())

    def update_preview(self):
        try:
            path = self.chosen()
        except Exception:
            path = ""
        self.file.setText(os.path.basename(path) if path else "")
        self.file.setToolTip(path or "")
        self.file.setCursorPosition(0)
        w, h = svg_size(path) if path else (0, 0)

        self.size_label.setText("Width: %.2fmm\nHeight: %.2fmm" % (w, h) if path else "")
        if path and self.standard.isChecked() and w and h:
            # usage run 11-27 (File handling): Custom's Width/Height read 279.40 x 215.90 beside an A3 pick; they
            # follow the picked size, so a switch to Custom starts from it
            for spin, val in ((self.width, w), (self.height, h)):
                spin.blockSignals(True)
                spin.setValue(val)
                spin.blockSignals(False)
        pix = QtGui.QPixmap(self.preview.size())
        pix.fill(QtGui.QColor("white"))
        if path:
            try:
                try:
                    from PySide import QtSvg
                except ImportError:
                    from PySide6 import QtSvg
                r = QtSvg.QSvgRenderer(path)
                p = QtGui.QPainter(pix)
                k = min((pix.width() - 10) / max(w, 1), (pix.height() - 10) / max(h, 1))
                rw, rh = w * k, h * k
                r.render(p, QtCore.QRectF((pix.width() - rw) / 2, (pix.height() - rh) / 2, rw, rh))
                p.end()
            except Exception as _fw_err:
                _fw_log("drawsheet.py:383", _fw_err)
        self.preview.setPixmap(pix)


class SheetFormatDialog(QtWidgets.QDialog):
    ""

    def __init__(self, parent=None, current=""):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWSheetFormatSize")
        self.setWindowTitle("Sheet Format/Size")
        lay = QtWidgets.QVBoxLayout(self)
        self.box = SheetFormatBox(self, current)
        lay.addWidget(self.box)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        for b in bb.buttons():
            b.setIcon(QtGui.QIcon())
        lay.addWidget(bb)
        self.buttons = bb


def ask_sheet_format(page=None, modal=True):
    """The Sheet Format/Size box; OK puts the format on page. Returns the chosen file, or None on Cancel."""
    dlg = SheetFormatDialog(current=page_template_path(page) if page is not None else "")
    ask_sheet_format.dialog = dlg
    if not modal:
        dlg.finished.connect(lambda r: r and page is not None and set_format(page, dlg.box.chosen()))
        dlg.show()
        return dlg
    if dlg.exec() != QtWidgets.QDialog.Accepted:
        return None
    path = dlg.box.chosen()
    if page is not None:
        set_format(page, path)
    return path


def set_format(page, path):
    """Put the sheet format file path on page (its template), keeping the title block's typed values."""
    if not path:
        return
    with _Untinted(page):
        _set_format(page, path)


OWN_FIELDS = ("size",)       # fields that belong to the sheet format (its size letter): not carried to another


def _set_format(page, path):
    tpl = page.Template
    if tpl is None or tpl.TypeId != "TechDraw::DrawSVGTemplate":
        tpl = page.Document.addObject("TechDraw::DrawSVGTemplate", "Template")
        page.Template = tpl
    old = dict(getattr(tpl, "EditableTexts", {}) or {})
    tpl.Template = path
    try:
        from . import drawings as D_, drawlayout
        texts = dict(tpl.EditableTexts)
        links = drawlayout.field_links(page)
        soft0 = set(drawlayout.soft_fields(page))   # soft links come back through default_field_links
        by_role = {}                      # the old format's linked fields, by role (typed ones stay with the format)
        for k, v in old.items():
            r = D_.field_role(k)
            if r and v and k in links and k not in soft0 and r not in by_role:
                by_role[r] = (k, v)
        soft = set(drawlayout.soft_fields(page))
        for k in texts:
            if k in old and old[k] and k.lower() not in OWN_FIELDS:
                texts[k] = old[k]
                continue
            r = D_.field_role(k)          # another format's field of the same role (ANSI title -> ISO title)
            if r in by_role:
                ok, v = by_role[r]
                texts[k] = v
                if ok in links and k not in links:
                    links[k] = links[ok]
                    if ok in soft:
                        soft.add(k)
        drawlayout.set_field_links(page, links)
        if soft:
            drawlayout.set_soft_fields(page, sorted(soft))
        tpl.EditableTexts = drawlayout.resolve_fields(page, texts)
        D_.default_field_links(page)
    except Exception as _fw_err:
        _fw_log("drawsheet.py:467", _fw_err)
    sw_names(page.Document)
    page.Document.recompute()


def reload_format(page):
    """Reload: the sheet format read again from its file, dropping the changes made to it (its typed values too)."""
    with _Untinted(page):
        _reload_format(page)


def _reload_format(page):
    tpl = page.Template
    if tpl is None or tpl.TypeId != "TechDraw::DrawSVGTemplate":
        return
    path = tpl.Template
    doc = page.Document
    doc.openTransaction("Reload Sheet Format")
    try:
        tpl.EditableTexts = {}
        tpl.Template = ""
        tpl.Template = path
        tpl.recompute()
        if hasattr(page, "SWFieldLinks"):
            page.SWFieldLinks = "{}"
    finally:
        doc.commitTransaction()
    sw_names(doc)
    doc.recompute()


# --------------------------------------------------------------------------- zones
def _sheet_size(page):
    try:
        return float(page.Template.Width), float(page.Template.Height)
    except Exception:
        return 279.4, 215.9


def default_zones(page):
    W, H = _sheet_size(page)
    return dict(cols=max(2, int(round(W / 50.0))), rows=max(2, int(round(H / 50.0))),
                left=0.0, right=0.0, top=0.0, bottom=0.0, sizing="even", region="sheet")


def zones(page):
    import json
    z = default_zones(page)
    try:
        stored = json.loads(getattr(page, "FreeWorksZones", "") or "{}")
    except ValueError:
        stored = {}
    if stored and "region" not in stored:
        stored["region"] = "margins"      # zones set before the Region choice existed ran inside the margins
    z.update(stored)
    return z


def set_zones(page, z):
    import json
    if "FreeWorksZones" not in page.PropertiesList:
        page.addProperty("App::PropertyString", "FreeWorksZones", "FreeCAD", "Zone Parameters (JSON)")
    page.FreeWorksZones = json.dumps(z, sort_keys=True)


ZONE_STEP = 50.0


def _even_cuts(a, b, n):
    n = max(1, int(n))
    return [a + (b - a) * i / n for i in range(n + 1)]


def _centre_cuts(a, b, step=ZONE_STEP):
    """Zone edges every 50mm out from the middle of a..b (ISO 5457); an end piece under half a zone joins its
    neighbour."""
    c = (a + b) / 2.0
    cuts = [c]
    k = 1
    while c - k * step > a + 1e-9:
        cuts.append(c - k * step)
        cuts.append(c + k * step)
        k += 1
    cuts = sorted(set([a, b] + [x for x in cuts if a < x < b] + ([c] if a < c < b else [])))
    out = [cuts[0]]
    for x in cuts[1:-1]:
        if x - out[-1] >= step / 2.0 - 1e-9 and cuts[-1] - x >= step / 2.0 - 1e-9:
            out.append(x)
    out.append(cuts[-1])
    return out


def zone_region(page, z=None):
    """x0, y0, x1, y1 the zones span: inside the margins (Region: Margins) or the whole sheet (Region: Sheet)."""
    W, H = _sheet_size(page)
    z = z or zones(page)
    if z.get("region") == "margins":
        return z["left"], z["bottom"], W - z["right"], H - z["top"]
    return 0.0, 0.0, W, H


def zone_cuts(page, z=None):
    """(column edges left to right, row edges bottom to top) of the sheet's zones."""
    z = z or zones(page)
    x0, y0, x1, y1 = zone_region(page, z)
    if z.get("sizing") == "center":
        return _centre_cuts(x0, x1), _centre_cuts(y0, y1)
    return _even_cuts(x0, x1, z["cols"]), _even_cuts(y0, y1, z["rows"])


def zone_counts(page, z=None):
    """(columns, rows): what the Rows and Columns boxes show (worked out when zones are 50mm from center)."""
    xs, ys = zone_cuts(page, z)
    return len(xs) - 1, len(ys) - 1


def zone_at(page, x, y):
    """The zone at sheet point x, y: rows A.. from the bottom, columns 1.. from the right."""
    xs, ys = zone_cuts(page)
    cols, rows = len(xs) - 1, len(ys) - 1
    ci = sum(1 for e in xs[1:-1] if x >= e)          # 0 = leftmost column
    ri = sum(1 for e in ys[1:-1] if y >= e)          # 0 = bottom row
    c = cols - ci
    letters = "ABCDEFGHJKLMNPRSTUVWXYZ"
    return "%s%d" % (letters[ri % len(letters)], c)


# --------------------------------------------------------------------------- Sheet Properties
def pages(doc):
    ""
    ps = [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage"]
    return sorted(ps, key=lambda p: (getattr(p, "SWSheetOrder", 0) or ps.index(p) + 1, ps.index(p)))


def reorder_sheets(doc, names):
    """Sets the sheet order to names (page Names, first sheet first)."""
    for n, name in enumerate(names):
        p = doc.getObject(name)
        if p is None:
            continue
        if "SWSheetOrder" not in p.PropertiesList:
            p.addProperty("App::PropertyInteger", "SWSheetOrder", "FreeCAD", "sheet order (1 = first)")
            p.setPropertyStatus("SWSheetOrder", "Hidden")
        p.SWSheetOrder = n + 1
    try:
        sheet_tabs_refresh()
    except Exception as _fw_err:
        _fw_log("drawsheet.py:614", _fw_err)
    try:
        tree_order(doc)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: sheet order in the tree: %s\n" % error)
    return pages(doc)


def _tree_widgets():
    out = []
    for tw in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
        try:
            if tw.metaObject().className() == "Gui::TreeWidget":
                out.append(tw)
        except Exception as _fw_err:
            _fw_log("drawsheet.py:629", _fw_err)
    return out


def tree_order(doc):
    ""


    want = [p.Label for p in pages(doc)]
    if len(want) < 2:
        return 0
    moved = 0
    for tw in _tree_widgets():
        for i in range(tw.topLevelItemCount()):
            top = tw.topLevelItem(i)
            if top is None or top.text(0) != doc.Label:
                continue
            rows = [(k, top.child(k)) for k in range(top.childCount())]
            sheets = [(k, it) for k, it in rows if it.text(0) in want]
            if len(sheets) != len(want):
                continue
            now = [it.text(0) for _k, it in sheets]
            if now == want:
                continue
            slots = [k for k, _it in sheets]
            taken = {it.text(0): it for _k, it in sheets}
            for k in sorted(slots, reverse=True):        # take the sheet rows out (bottom first) ...
                top.takeChild(k)
            for slot, label in zip(slots, want):          # ... and put them back in the sheet order
                top.insertChild(slot, taken[label])
                moved += 1
    return moved


def move_sheet(page, to):
    """Moves page to position to (0 = first) in its drawing's sheet order."""
    names = [p.Name for p in pages(page.Document) if p is not page]
    names.insert(max(0, min(to, len(names))), page.Name)
    done = reorder_sheets(page.Document, names)
    refresh_all_fields(page.Document, every=False)
    return done


def _ratio(scale):
    ""
    from fractions import Fraction
    f = Fraction(scale).limit_denominator(1000)
    return f.numerator, f.denominator


def _label_prop(page, name, default="A"):
    return getattr(page, name, default) if hasattr(page, name) else default


def _set_label_prop(page, name, value, tip):
    if not hasattr(page, name):
        page.addProperty("App::PropertyString", name, "FreeCAD", tip)
    setattr(page, name, value)


def property_sheet(doc):
    """Document Properties > Drawing Sheets > Use custom property values from this sheet on all sheets: that sheet
    (None when the option is off)."""
    try:
        from . import drawdocprops as DP
        if not DP.prop(doc, "sheet_props_all"):
            return None
        ps = pages(doc)
        n = int(DP.prop(doc, "sheet_props_number") or 1)
        return ps[min(max(n, 1), len(ps)) - 1] if ps else None
    except Exception:
        return None


def _own_property_view(page):
    label = getattr(page, "FreeWorksPropertyView", "") if hasattr(page, "FreeWorksPropertyView") else ""
    parts = [v for v in page.Views if v.isDerivedFrom("TechDraw::DrawViewPart")]
    if label and label != "Default":
        for v in parts:
            if v.Label == label:
                return v
    return parts[0] if parts else None      # Default: the first view placed on the sheet


def property_view(page):
    """The view whose model the sheet's $PRP fields read: 'Use custom property values from model shown in', or
    the sheet Document Properties names when 'Same as sheet specified in Document Properties' is on (or when this
    sheet has no views of its own and the document option is on)."""
    src = property_sheet(page.Document)
    own = _own_property_view(page)
    if src is not None and src is not page and (getattr(page, "FreeWorksPropertySameAsDoc", False) or own is None):
        return _own_property_view(src)
    if own is None:                 # a sheet with no views yet: the model of the first sheet that has one
        for p in pages(page.Document):
            if p is not page:
                v = _own_property_view(p)
                if v is not None:
                    return v
    return own


class SheetPropertiesDialog(QtWidgets.QDialog):
    ""

    def __init__(self, page, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.page = page
        self.setObjectName("SWSheetProperties")
        self.setWindowTitle("Sheet Properties")
        outer = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget(self)
        self.tabs.setObjectName("SWSheetPropertiesTabs")
        outer.addWidget(self.tabs)
        first = QtWidgets.QWidget(self.tabs)
        lay = QtWidgets.QVBoxLayout(first)
        self.tabs.addTab(first, "Sheet Properties")
        self.zone_tab()
        grid = QtWidgets.QGridLayout()
        self.name = QtWidgets.QLineEdit(page.Label, self)
        self.name.setObjectName("SWSheetName")
        grid.addWidget(QtWidgets.QLabel("Name:", self), 0, 0)
        grid.addWidget(self.name, 0, 1)
        a, b = _ratio(float(page.Scale))
        self.scale_a = QtWidgets.QSpinBox(self)
        self.scale_a.setObjectName("SWSheetScaleA")
        self.scale_b = QtWidgets.QSpinBox(self)
        self.scale_b.setObjectName("SWSheetScaleB")
        for s, v in ((self.scale_a, a), (self.scale_b, b)):
            s.setRange(1, 100000)
            s.setValue(v)
        srow = QtWidgets.QHBoxLayout()
        srow.addWidget(self.scale_a)
        srow.addWidget(QtWidgets.QLabel(":", self))
        srow.addWidget(self.scale_b)
        grid.addWidget(QtWidgets.QLabel("Scale:", self), 1, 0)
        grid.addLayout(srow, 1, 1)
        proj = QtWidgets.QGroupBox("Type of projection", self)
        proj.setMinimumWidth(QtGui.QFontMetrics(proj.font()).horizontalAdvance("Type of projection") + 40)   # never cut
        pl = QtWidgets.QVBoxLayout(proj)
        self.first = QtWidgets.QRadioButton("First angle", proj)
        self.first.setObjectName("SWSheetFirstAngle")
        self.third = QtWidgets.QRadioButton("Third angle", proj)
        self.third.setObjectName("SWSheetThirdAngle")
        (self.third if page.ProjectionType == "Third angle" else self.first).setChecked(True)
        pl.addWidget(self.first)
        pl.addWidget(self.third)
        grid.addWidget(proj, 0, 2, 2, 1)
        self.view_label = QtWidgets.QLineEdit(_label_prop(page, "FreeWorksNextViewLabel"), self)
        self.view_label.setObjectName("SWSheetNextViewLabel")
        self.datum_label = QtWidgets.QLineEdit(_label_prop(page, "FreeWorksNextDatumLabel"), self)
        self.datum_label.setObjectName("SWSheetNextDatumLabel")
        grid.addWidget(QtWidgets.QLabel("Next view label:", self), 2, 0)
        grid.addWidget(self.view_label, 2, 1)
        grid.addWidget(QtWidgets.QLabel("Next datum label:", self), 3, 0)
        grid.addWidget(self.datum_label, 3, 1)
        lay.addLayout(grid)
        try:
            from . import drawannot as DA
            std = DA._standard(page)
        except Exception as _fw_err:
            _fw_log("drawsheet.py:sheet standard", _fw_err)
            std = None
        self.format = SheetFormatBox(self, page_template_path(page), std)
        fbox = QtWidgets.QGroupBox("Sheet Format/Size", self)
        fl = QtWidgets.QVBoxLayout(fbox)
        fl.addWidget(self.format)
        self.reload = QtWidgets.QPushButton("Reload", fbox)
        self.reload.setObjectName("SWSheetReload")
        self.reload.setToolTip("Discards the changes made to the sheet format since it was loaded")
        self.reload.clicked.connect(lambda *_: reload_format(self.page))
        rr = QtWidgets.QHBoxLayout()
        rr.addStretch(1)
        rr.addWidget(self.reload)
        fl.addLayout(rr)
        lay.addWidget(fbox)
        crow = QtWidgets.QHBoxLayout()
        crow.addWidget(QtWidgets.QLabel("Use custom property values from model shown in:", self))
        self.model_view = QtWidgets.QComboBox(self)
        self.model_view.setObjectName("SWSheetModelView")
        self.model_view.addItem("Default")
        for v in page.Views:
            if v.isDerivedFrom("TechDraw::DrawViewPart"):
                self.model_view.addItem(v.Label)
        cur = getattr(page, "FreeWorksPropertyView", "") if hasattr(page, "FreeWorksPropertyView") else ""
        if cur:
            self.model_view.setCurrentText(cur)
        crow.addWidget(self.model_view, 1)
        lay.addLayout(crow)
        self.same_as = QtWidgets.QCheckBox("Same as sheet specified in Document Properties", self)
        self.same_as.setObjectName("SWSheetSameAsDocProps")
        self.same_as.setToolTip("Takes the custom property values from the sheet named in Document Properties > "
                                "Drawing Sheets")
        self.same_as.setChecked(bool(getattr(page, "FreeWorksPropertySameAsDoc", False)))
        self.same_as.toggled.connect(self.same_as_refresh)
        lay.addWidget(self.same_as)
        brow = QtWidgets.QHBoxLayout()
        self.select_sheets = QtWidgets.QPushButton("Select Sheets to Modify...", self)
        self.select_sheets.setObjectName("SWSheetSelectSheets")
        self.select_sheets.clicked.connect(self.pick_sheets)
        brow.addWidget(self.select_sheets)
        brow.addStretch(1)
        self.update_all = QtWidgets.QPushButton("Update All Properties", self)
        self.update_all.setObjectName("SWSheetUpdateAll")
        self.update_all.setToolTip("Applies the custom property source and reads the properties again on every sheet")
        self.update_all.clicked.connect(self.update_all_properties)
        brow.addWidget(self.update_all)
        self.apply = QtWidgets.QPushButton("Apply Changes", self)
        self.apply.setObjectName("SWSheetApply")
        self.apply.setDefault(True)
        self.cancel = QtWidgets.QPushButton("Cancel", self)
        self.cancel.setObjectName("SWSheetCancel")
        self.apply.clicked.connect(self.accept)
        self.cancel.clicked.connect(self.reject)
        brow.addWidget(self.apply)
        brow.addWidget(self.cancel)
        outer.addLayout(brow)
        self.targets = [page]
        self.same_as_refresh()
        for w in self.findChildren(QtWidgets.QWidget):
            for sig in ("textEdited", "valueChanged", "toggled", "currentIndexChanged", "itemSelectionChanged",
                        "currentRowChanged"):
                if w in (self.reload, self.update_all, self.apply, self.cancel):
                    continue
                try:
                    getattr(w, sig).connect(self.changed)
                except (AttributeError, TypeError, RuntimeError) as _fw_err:
                    _fw_log("drawsheet.py:850", _fw_err)
        self.model_view.currentIndexChanged.connect(self.source_changed)
        self.same_as.toggled.connect(self.source_changed)
        self.dirty = False

    def changed(self, *_):
        self.dirty = True
        self.apply.setEnabled(True)
        w = self.sender()
        if isinstance(w, QtWidgets.QWidget) and (w is self.format or self.format.isAncestorOf(w)):
            self.reload.setVisible(False)     # another format picked: nothing to reload (hidden, never greyed)

    def source_changed(self, *_):
        self.update_all.setEnabled(True)

    def same_as_sheet(self):
        """The sheet Document Properties names for custom properties on all sheets (None when that is off or it is
        this sheet)."""
        try:
            from . import drawdocprops as DP
            doc = self.page.Document
            if not DP.prop(doc, "sheet_props_all"):
                return None
            return property_sheet(doc)
        except Exception:
            return None

    def same_as_refresh(self, *_):
        src = self.same_as_sheet()
        ok = src is not None and src is not self.page
        self.same_as.setVisible(ok)           # no other sheet to copy from: hidden (never greyed)
        if not ok and self.same_as.isChecked():
            self.same_as.blockSignals(True)
            self.same_as.setChecked(False)
            self.same_as.blockSignals(False)
        if not getattr(self, "_fw_mv_live", False):
            self._fw_mv_live = True
            DL.sets(self.same_as, False, self.model_view)       # a view picked here is this sheet's own

    def update_all_properties(self):
        doc = self.page.Document
        doc.openTransaction("Update All Properties")
        try:
            self.store_source(self.page)
            from . import drawlayout
            for p in pages(doc):
                drawlayout.refresh_fields(p)
        except Exception as e:
            App.Console.PrintWarning("FreeCAD: Update All Properties: %s\n" % e)
        finally:
            doc.commitTransaction()
        doc.recompute()

    def store_source(self, p):
        _set_label_prop(p, "FreeWorksPropertyView", self.model_view.currentText(),
                        "Custom property values from the model in this view")
        if "FreeWorksPropertySameAsDoc" not in p.PropertiesList:
            p.addProperty("App::PropertyBool", "FreeWorksPropertySameAsDoc", "FreeCAD",
                          "Custom property values from the sheet named in Document Properties")
        p.FreeWorksPropertySameAsDoc = bool(self.same_as.isChecked() and not self.same_as.isHidden())

    def zone_tab(self):
        """Zone Parameters: zones evenly sized (Rows x Columns) or 50mm from center, over the sheet or inside the
        margins (the grid Location Labels and the zone of a view's label come from them)."""
        page = self.page
        z = zones(page)
        tab = QtWidgets.QWidget(self.tabs)
        lay = QtWidgets.QVBoxLayout(tab)
        box = QtWidgets.QGroupBox("Zone Size", tab)
        bl = QtWidgets.QHBoxLayout(box)
        dist = QtWidgets.QGroupBox("Distribution", box)
        g = QtWidgets.QGridLayout(dist)
        self.zone_center = QtWidgets.QRadioButton("50mm from center", dist)
        self.zone_center.setObjectName("SWZoneFromCenter")
        self.zone_even = QtWidgets.QRadioButton("Evenly sized", dist)
        self.zone_even.setObjectName("SWZoneEvenly")
        (self.zone_center if z.get("sizing") == "center" else self.zone_even).setChecked(True)
        g.addWidget(self.zone_center, 0, 0, 1, 2)
        g.addWidget(self.zone_even, 1, 0, 1, 2)
        self.zone_rows = QtWidgets.QSpinBox(dist)
        self.zone_rows.setObjectName("SWZoneRows")
        self.zone_cols = QtWidgets.QSpinBox(dist)
        self.zone_cols.setObjectName("SWZoneColumns")
        for w, v in ((self.zone_cols, z["cols"]), (self.zone_rows, z["rows"])):
            w.setRange(1, 52)
            w.setValue(int(v))
        g.addWidget(QtWidgets.QLabel("Rows:", dist), 2, 0)
        g.addWidget(self.zone_rows, 2, 1)
        g.addWidget(QtWidgets.QLabel("Columns:", dist), 3, 0)
        g.addWidget(self.zone_cols, 3, 1)
        bl.addWidget(dist)
        reg = QtWidgets.QGroupBox("Region", box)
        rl = QtWidgets.QVBoxLayout(reg)
        self.zone_in_margins = QtWidgets.QRadioButton("Margins", reg)
        self.zone_in_margins.setObjectName("SWZoneRegionMargins")
        self.zone_on_sheet = QtWidgets.QRadioButton("Sheet", reg)
        self.zone_on_sheet.setObjectName("SWZoneRegionSheet")
        (self.zone_in_margins if z.get("region") == "margins" else self.zone_on_sheet).setChecked(True)
        rl.addWidget(self.zone_in_margins)
        rl.addWidget(self.zone_on_sheet)
        rl.addStretch(1)
        bl.addWidget(reg)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Margins", tab)
        g = QtWidgets.QGridLayout(box)
        self.margins = {}
        for n, side in enumerate(("Left", "Right", "Top", "Bottom")):
            w = QtWidgets.QDoubleSpinBox(box)
            w.setObjectName("SWZoneMargin" + side)
            w.setRange(0, 200)
            w.setDecimals(2)
            w.setSuffix("mm")
            w.setValue(z[side.lower()])
            g.addWidget(QtWidgets.QLabel(side + ":", box), n // 2, (n % 2) * 2)
            g.addWidget(w, n // 2, (n % 2) * 2 + 1)
            self.margins[side.lower()] = w
            w.valueChanged.connect(self.zone_sizing_changed)
        lay.addWidget(box)
        row = QtWidgets.QHBoxLayout()
        self.zone_reset = QtWidgets.QPushButton("Reset Zones", tab)
        self.zone_reset.setObjectName("SWZoneReset")
        self.zone_reset.clicked.connect(self.reset_zones)
        row.addWidget(self.zone_reset)
        row.addStretch(1)
        self.zone_docprops = QtWidgets.QPushButton("Go to Drawing Sheet Properties", tab)
        self.zone_docprops.setObjectName("SWZoneGoToDocProps")
        self.zone_docprops.setToolTip("Opens Document Properties at Drawing Sheets")
        self.zone_docprops.clicked.connect(self.go_doc_sheet_props)
        row.addWidget(self.zone_docprops)
        lay.addLayout(row)
        lay.addStretch(1)
        for w in (self.zone_center, self.zone_even, self.zone_in_margins, self.zone_on_sheet):
            w.toggled.connect(self.zone_sizing_changed)
        self.tabs.addTab(tab, "Zone Parameters")
        self.zone_sizing_changed()

    def zone_values(self):
        z = dict(cols=self.zone_cols.value(), rows=self.zone_rows.value(),
                 sizing="center" if self.zone_center.isChecked() else "even",
                 region="margins" if self.zone_in_margins.isChecked() else "sheet")
        z.update({k: w.value() for k, w in self.margins.items()})
        return z

    def zone_sizing_changed(self, *_):
        """50mm from center works the rows and columns out (the boxes grey and show them); Evenly sized takes them."""
        center = self.zone_center.isChecked()
        if center:
            c, r = zone_counts(self.page, self.zone_values())
            for w, v in ((self.zone_cols, c), (self.zone_rows, r)):
                w.blockSignals(True)
                w.setValue(v)
                w.blockSignals(False)
        if not getattr(self, "_fw_zone_live", False):
            self._fw_zone_live = True
            DL.sets(self.zone_even, True, self.zone_cols, self.zone_rows)   # counts typed: Evenly sized (never greyed)

    def go_doc_sheet_props(self):
        try:
            from . import drawdocprops
            drawdocprops.document_properties(self.page.Document, start_page="Drawing Sheets")
        except Exception as e:
            App.Console.PrintWarning("FreeCAD: Document Properties: %s\n" % e)
        self.same_as_refresh()

    def reset_zones(self):
        z = default_zones(self.page)
        self.zone_even.setChecked(True)
        self.zone_on_sheet.setChecked(True)
        self.zone_cols.setValue(z["cols"])
        self.zone_rows.setValue(z["rows"])
        for k, w in self.margins.items():
            w.setValue(z[k])

    def pick_sheets(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setObjectName("SWSheetSelectSheetsBox")
        dlg.setWindowTitle("Select Sheets to Modify")
        lay = QtWidgets.QVBoxLayout(dlg)
        lst = QtWidgets.QListWidget(dlg)
        lst.setObjectName("SWSheetSheetList")
        for p in pages(self.page.Document):
            it = QtWidgets.QListWidgetItem(p.Label)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if p in self.targets else QtCore.Qt.Unchecked)
            it.setData(QtCore.Qt.UserRole, p.Name)
            lst.addItem(it)
        lay.addWidget(lst)
        allb = QtWidgets.QCheckBox("All sheets", dlg)
        allb.setObjectName("SWSheetAllSheets")
        allb.toggled.connect(lambda on: [lst.item(i).setCheckState(QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)
                                         for i in range(lst.count())])
        lay.addWidget(allb)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, dlg)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        self.sheet_box = dlg
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            doc = self.page.Document
            self.targets = [doc.getObject(lst.item(i).data(QtCore.Qt.UserRole)) for i in range(lst.count())
                            if lst.item(i).checkState() == QtCore.Qt.Checked] or [self.page]

    def apply_to(self):
        doc = self.page.Document
        doc.openTransaction("Sheet Properties")
        try:
            fmt = self.format.chosen()
            for p in self.targets:
                if p is self.page and self.name.text().strip():
                    p.Label = self.name.text().strip()
                p.Scale = self.scale_a.value() / float(self.scale_b.value())
                want = "Third angle" if self.third.isChecked() else "First angle"
                if p.ProjectionType != want:
                    p.ProjectionType = want
                    try:
                        from . import drawings as _D      # the projected views go to the other side
                        _D.flip_projected(p)
                    except Exception as error:
                        App.Console.PrintWarning("FreeCAD: projection type: %s\n" % error)
                for o in p.Views:
                    if o.TypeId == "TechDraw::DrawProjGroup":
                        o.ProjectionType = p.ProjectionType
                _set_label_prop(p, "FreeWorksNextViewLabel", self.view_label.text().strip() or "A",
                                "Next view label")
                _set_label_prop(p, "FreeWorksNextDatumLabel", self.datum_label.text().strip() or "A",
                                "Next datum label")
                self.store_source(p)
                if fmt and fmt != page_template_path(p):
                    set_format(p, fmt)
                set_zones(p, self.zone_values())
            try:
                from . import drawlayout
                for p in self.targets:
                    drawlayout.refresh_fields(p)
            except Exception as _fw_err:
                _fw_log("drawsheet.py:1083", _fw_err)
        finally:
            doc.commitTransaction()
        doc.recompute()
        sheet_tabs_refresh()


def sheet_properties(page=None):
    page = page or active_page()
    if page is None:
        return None
    dlg = SheetPropertiesDialog(page)
    sheet_properties.dialog = dlg
    if dlg.exec() == QtWidgets.QDialog.Accepted:
        dlg.apply_to()
        return True
    return False


# --------------------------------------------------------------------------- sheets
def active_page():
    """The sheet in front; a sheet picked in the tree (its right-click menu) wins over the first sheet."""
    from . import drawings
    try:
        sel = [o for o in Gui.Selection.getSelection() if o.TypeId == "TechDraw::DrawPage"]
    except Exception:
        sel = []
    if sel:
        return sel[0]
    return drawings.active_page()


def _ptr(obj):
    """The C++ address of a Qt object (Python wrappers of one scene are not always the same object)."""
    if obj is None:
        return None
    try:
        import shiboken6 as shiboken
    except ImportError:
        try:
            import shiboken2 as shiboken
        except ImportError:
            return id(obj)
    try:
        return shiboken.getCppPointer(obj)[0]
    except Exception:
        return id(obj)


def sheet_window(scene):
    """The MDI window showing scene, else None."""
    key = _ptr(scene)
    if key is None:
        return None
    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    for sub in (mdi.subWindowList() if mdi is not None else []):
        try:
            if any(_ptr(v.scene()) == key for v in sub.findChildren(QtWidgets.QGraphicsView)):
                return sub
        except Exception as _fw_err:
            _fw_log("drawsheet.py:1144", _fw_err)
            continue
    return None


def show_page(page):
    """The sheet's window in front (opened when it is not open yet)."""
    try:
        import TechDrawGui
        scene = TechDrawGui.getSceneForPage(page)
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        sub = sheet_window(scene)
        if sub is not None:
            mdi.setActiveSubWindow(sub)
            return
    except Exception as _fw_err:
        _fw_log("drawsheet.py:1158", _fw_err)
    try:
        page.ViewObject.doubleClicked()
    except Exception:
        try:
            page.ViewObject.show()
        except Exception as _fw_err:
            _fw_log("drawsheet.py:1165", _fw_err)


def _drawing_option(text, default):
    """extapps83: Tools > Options > System Options > Drawings: that row's kept value."""
    try:
        from . import optionspages
        return optionspages.stored("Drawings", text, default)
    except Exception:
        return default


def add_sheet(doc=None, like=None):
    """Insert > Sheet...: SheetN with the same format, scale and projection as like (the active sheet)."""
    doc = doc or App.ActiveDocument
    like = like or active_page()
    have = {o.Label for o in doc.Objects}
    n = len(pages(doc)) + 1
    while "Sheet%d" % n in have:
        n += 1
    doc.openTransaction("Add Sheet")
    try:
        page = doc.addObject("TechDraw::DrawPage", "Sheet%d" % n)
        page.Label = "Sheet%d" % n
        path = page_template_path(like) if like is not None else ""
        try:
            from . import drawdocprops        # Document Properties > Drawing Sheets: a different format for new sheets
            if drawdocprops.prop(doc, "sheet_own"):
                path = size_path(drawdocprops.prop(doc, "sheet_format")) or path
        except Exception as _fw_err:
            _fw_log("drawsheet.py:1185", _fw_err)
        if not path:
            from . import newdoc
            path = newdoc.sheet_template() or ""
        if path:
            tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
            tpl.Template = path
            page.Template = tpl
        if like is not None:
            page.Scale = like.Scale
            page.ProjectionType = like.ProjectionType
            try:                                    # the title block's links as on the sheet it is made like
                from . import drawlayout
                links = drawlayout.field_links(like)
                if links and page.Template is not None:
                    drawlayout.set_field_links(page, links)
            except Exception as _fw_err:
                _fw_log("drawsheet.py:1202", _fw_err)
        else:
            from . import drawings
            drawings.sheet_defaults(page)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    sw_names(doc)
    doc.recompute()
    refresh_all_fields(doc, every=False)        # SHEET n OF m: the sheet in front now, the rest when idle
    show_page(page)
    QtCore.QTimer.singleShot(300, sheet_tabs_refresh)
    if _drawing_option("Show sheet format dialog when adding new sheet", False):
        ask_sheet_format(page)              # extapps83: System Options > Drawings
    return page


SHEET_CLIP = {}


def copy_sheet(page):
    """Copy (sheet tab right-click / tree): the sheet with everything on it, for Paste."""
    SHEET_CLIP.clear()
    SHEET_CLIP.update(doc=page.Document.Name, name=page.Name)
    return True


def paste_sheet(doc=None):
    ""

    try:
        src = App.getDocument(SHEET_CLIP.get("doc", "")).getObject(SHEET_CLIP.get("name", ""))
    except Exception:
        src = None
    if src is None:
        return None
    doc = doc or src.Document
    if doc is not src.Document:
        return None
    from . import drawkeys as K
    items = K.sheet_items(src)
    objs = [src] + ([src.Template] if getattr(src, "Template", None) is not None else []) + items
    doc.openTransaction("Paste Sheet")
    try:
        copies = doc.copyObject(objs, False)     # links among the copies point to the copies
    finally:
        doc.commitTransaction()
    copies = copies if isinstance(copies, (list, tuple)) else [copies]
    page = copies[0]
    have = {o.Label for o in doc.Objects if o is not page}
    k = 2
    while "%s(%d)" % (src.Label, k) in have:
        k += 1
    page.Label = "%s(%d)" % (src.Label, k)
    for c in copies[1:]:
        if c.isDerivedFrom("TechDraw::DrawView") and c not in page.Views and not any(
                g.TypeId == "TechDraw::DrawProjGroup" for g in c.InList):
            try:
                page.addView(c)
            except Exception as _fw_err:
                _fw_log("drawsheet.py:1258", _fw_err)
    sw_names(doc)
    doc.recompute()
    try:
        from . import drawviews as DV
        DV.project_now(page, [c for c in copies if c.isDerivedFrom("TechDraw::DrawViewPart")], doc)
    except Exception as _fw_err:
        _fw_log("drawsheet.py:1265", _fw_err)
    refresh_all_fields(doc, every=False)
    show_page(page)
    QtCore.QTimer.singleShot(300, sheet_tabs_refresh)
    return page


_STALE = {}         # document name -> sheet names whose title block fields wait (they are behind other sheets)
_FLUSH = []         # the timer that brings them up to date once the drawing is idle


def _front_page(doc):
    try:
        from . import drawings
        p = drawings.active_page()
        return p if p is not None and p.Document is doc else None
    except Exception as _fw_err:
        _fw_log("drawsheet.py:1291", _fw_err)
        return None


def refresh_all_fields(doc, every=True):
    """Every sheet's linked title block fields read their properties again (sheet count, order, model).
    A title block is drawn again each time a field changes (TechDraw rewrites the sheet format), so adding the
    20th sheet would redraw 20 title blocks (SHEET n OF 20): the sheet in front is brought up to date now, the
    sheets behind it once the drawing is idle (and before it is saved, printed or exported) when a sheet is
    added, copied, moved or deleted (every=False). The sheet tick (every=True) brings every sheet up to date."""
    try:
        from . import drawlayout
        n = 0
        front = None if every else _front_page(doc)
        later = _STALE.setdefault(doc.Name, set())
        for p in pages(doc):
            if front is None or p is front:
                n += bool(drawlayout.refresh_fields(p))
                later.discard(p.Name)
            else:
                later.add(p.Name)
            n += refresh_linked_notes(p)
        if n:
            doc.recompute()
        if later:
            _flush_later(doc.Name)
        return n
    except Exception as _fw_err:
        _fw_log("drawsheet.py:1319", _fw_err)
        return 0


def _flush_later(name):
    if not _FLUSH:
        t = QtCore.QTimer()
        t.setSingleShot(True)
        t.setInterval(600)
        t.timeout.connect(_flush)
        _FLUSH.append(t)
    _FLUSH[0].start()           # again: one flush after the last change


def _flush():
    from . import drawlayout
    for name, later in list(_STALE.items()):
        try:
            doc = App.getDocument(name)
        except Exception:
            _STALE.pop(name, None)
            continue
        n = 0
        for pn in list(later):
            p = doc.getObject(pn)
            later.discard(pn)
            if p is not None:
                try:
                    n += bool(drawlayout.refresh_fields(p))
                except Exception as _fw_err:
                    _fw_log("drawsheet.py:1338", _fw_err)
        if n:
            doc.recompute()


def fields_current(doc):
    """Every sheet's title block up to date now (before a save, print or export)."""
    if _STALE.get(doc.Name):
        refresh_all_fields(doc, every=True)


def refresh_linked_notes(page):
    ""


    try:
        from . import drawannot as DA
        from . import drawlibrary
    except Exception:
        return 0
    n = 0
    if getattr(page, "SWShowLinkVariables", False):
        return 0                # Hide/Show > Annotation Link Variables: the notes show their links, not values
    for o in list(page.Views):
        raw = getattr(o, "SWText", "") or ""
        if "$PRP" not in raw or getattr(o, "SWAnnotation", "") != "Note":
            continue
        tip = getattr(o, "SWTip", None)
        tip = (tip.x, tip.y) if tip is not None and getattr(tip, "z", 0) >= 0 else None
        try:
            text = DA.resolve_properties(page, raw, tip)
        except Exception as _fw_err:
            _fw_log("drawsheet.py:1381", _fw_err)
            continue
        if "SWLinkedText" in o.PropertiesList and o.SWLinkedText == text:
            continue
        try:
            plain = getattr(o, "SWLayer", "")
            drawlibrary.relink(page, o)
            if plain:                      # the note keeps its layer's look
                from . import drawpmparts as PP
                PP.apply_layer(o)
        except Exception as _fw_err:
            _fw_log("drawsheet.py:1392", _fw_err)
            continue
        if "SWLinkedText" not in o.PropertiesList:
            o.addProperty("App::PropertyString", "SWLinkedText", "FreeCAD", "a linked note's text as last shown")
        o.SWLinkedText = text
        n += 1
    return n


def delete_sheet(page):
    ""
    doc = page.Document
    if len(pages(doc)) < 2:
        return False
    box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question, "Confirm Delete",
                                "Delete %s and its views?" % page.Label,
                                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, Gui.getMainWindow())
    box.setObjectName("SWSheetConfirmDelete")
    delete_sheet.box = box
    if box.exec() != QtWidgets.QMessageBox.Yes:
        return False
    doc.openTransaction("Delete Sheet")
    try:
        names = []
        for v in list(page.Views):
            names += [o.Name for o in getattr(v, "Views", [])] + [v.Name]
        tpl = page.Template.Name if page.Template is not None else ""
        for n in names:
            if doc.getObject(n) is not None:
                doc.removeObject(n)
        doc.removeObject(page.Name)
        left = doc.getObject(tpl) if tpl else None
        if left is not None and not left.InList:
            doc.removeObject(tpl)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    refresh_all_fields(doc, every=False)
    show_page(pages(doc)[0])
    QtCore.QTimer.singleShot(300, sheet_tabs_refresh)
    return True


def sw_names(doc):
    ""
    n = 0
    for p in pages(doc):
        tpl = p.Template
        if tpl is not None:
            n += 1
            want = "Sheet Format%d" % n
            if tpl.Label != want and (tpl.Label.startswith("Template") or tpl.Label.startswith("Sheet Format")):
                tpl.Label = want
    used = {o.Label for o in doc.Objects}
    k = 1
    for p in pages(doc):
        for v in p.Views:
            items = list(v.Views) if v.TypeId == "TechDraw::DrawProjGroup" else [v]
            for it in items:
                if not it.isDerivedFrom("TechDraw::DrawViewPart"):
                    continue
                if it.Label.startswith("Drawing View"):
                    continue
                if re.match(r"^(View|ProjItem|ProjGroupItem|Front|Top|Right|Left|Bottom|Rear|"
                            r"FrontTopLeft|FrontTopRight|FrontBottomLeft|FrontBottomRight)\d*$", it.Label):
                    while "Drawing View%d" % k in used:
                        k += 1
                    it.Label = "Drawing View%d" % k
                    used.add(it.Label)


# --------------------------------------------------------------------------- Edit Sheet Format / Edit Sheet
def editing_format(page):
    return bool(getattr(page, "FreeWorksEditFormat", False))


def on_format(o):
    ""
    return bool(getattr(o, "SWOnFormat", False))


def format_items(page):
    """The items on the sheet format: those drawn on it before, and (while it is edited) those drawn now."""
    before = None
    if getattr(page, "FreeWorksEditFormat", False):
        before = set(getattr(page, "FreeWorksFormatBefore", []) or [])
    return [v for v in page.Views if on_format(v) or (before is not None and v.Name not in before)]


def edit_sheet_format(page, on=True):
    """Edit Sheet Format: the views go and only the sheet format (its title block texts, and the notes, lines and
    blocks drawn on it) takes clicks; what is drawn now belongs to the sheet format (Save Sheet Format keeps it).
    Edit Sheet puts the views back; the format's own items stay in sight but are held in place."""
    if not hasattr(page, "FreeWorksEditFormat"):
        page.addProperty("App::PropertyBool", "FreeWorksEditFormat", "FreeCAD", "Editing the sheet format")
    if not hasattr(page, "FreeWorksFormatBefore"):
        page.addProperty("App::PropertyStringList", "FreeWorksFormatBefore", "FreeCAD",
                         "the sheet's items when Edit Sheet Format started")
    was = bool(page.FreeWorksEditFormat)
    page.FreeWorksEditFormat = on
    if on and not was:
        page.FreeWorksFormatBefore = [v.Name for v in page.Views]
    if not on and was:
        before = set(page.FreeWorksFormatBefore or [])
        for v in page.Views:
            if v.Name not in before and not on_format(v):
                try:
                    v.addProperty("App::PropertyBool", "SWOnFormat", "FreeCAD", "drawn on the sheet format")
                except Exception as _fw_err:
                    _fw_log("drawsheet.py:1485", _fw_err)
                v.SWOnFormat = True
        page.FreeWorksFormatBefore = []
    for v in page.Views:
        fmt = on_format(v)
        try:
            v.ViewObject.Visibility = fmt or not on
        except Exception as _fw_err:
            _fw_log("drawsheet.py:1493", _fw_err)
        if fmt and hasattr(v, "LockPosition"):
            try:
                v.LockPosition = not on          # format items move only while the format is edited
            except Exception as _fw_err:
                _fw_log("drawsheet.py:1498", _fw_err)
    try:
        Gui.getMainWindow().statusBar().showMessage("Editing Sheet Format" if on else "Editing " + page.Label, 0)
    except Exception as _fw_err:
        _fw_log("drawsheet.py:1502", _fw_err)
    if on != was:
        tint_format(page, on)
    format_corner(page, on)


FORMAT_BLUE = "#1f5fd0"


def tint_format(page, on=True):
    """The sheet format's lines blue while it is edited (a tinted copy of its SVG, the title block values kept);
    its own file again on Edit Sheet."""
    tpl = page.Template
    if tpl is None or not hasattr(tpl, "Template"):
        return False
    for name, tip in (("FreeWorksFormatFile", "the sheet format's own file while it is shown blue"),):
        if not hasattr(page, name):
            page.addProperty("App::PropertyString", name, "FreeCAD", tip)
    texts = dict(getattr(tpl, "EditableTexts", {}) or {})
    try:
        if on:
            src = str(tpl.Template)
            if not src or not os.path.isfile(src):
                return False
            text = open(src, encoding="utf-8", errors="replace").read()
            text = re.sub(r"(stroke\s*[:=]\s*\"?)(#[0-9a-fA-F]{3,6}|black|rgb\([^)]*\))", r"\g<1>" + FORMAT_BLUE, text)
            folder = os.path.join(App.getUserAppDataDir(), "FreeWorks", "format-edit")
            os.makedirs(folder, exist_ok=True)
            dst = os.path.join(folder, "%s_%s_editing.svg" % (page.Document.Name, page.Name))
            with open(dst, "w", encoding="utf-8") as f:
                f.write(text)
            page.FreeWorksFormatFile = src
            tpl.Template = dst
        else:
            src = getattr(page, "FreeWorksFormatFile", "")
            if not src:
                return False
            tpl.Template = src
            page.FreeWorksFormatFile = ""
        if texts:
            tpl.EditableTexts = texts
        page.Document.recompute()
        return True
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: sheet format colour: %s\n" % error)
        return False


def format_corner(page, on=True):
    """The confirmation corner of Edit Sheet Format: one button at the top right of the sheet window that goes
    back to Edit Sheet."""
    try:
        from . import drawings as D
        gv = D.page_view(page)
    except Exception:
        gv = None
    if gv is None:
        return None
    vp = gv.viewport()
    old = vp.findChild(QtWidgets.QToolButton, "SWFormatCorner")
    if not on:
        if old is not None:
            old.hide()
            old.deleteLater()
        return None
    if old is not None:
        return old
    b = QtWidgets.QToolButton(vp)
    b.setObjectName("SWFormatCorner")
    b.setToolTip("Exit Sheet Format (Edit Sheet)")
    b.setAutoRaise(True)
    b.setFixedSize(36, 36)
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pix = _hidpi.canvas(28, 28)
    pix.fill(QtCore.Qt.transparent)
    pt = QtGui.QPainter(pix)
    pt.setRenderHint(QtGui.QPainter.Antialiasing)
    pt.setPen(QtGui.QPen(QtGui.QColor(FORMAT_BLUE), 1.5))
    pt.setBrush(QtGui.QColor("#ffffff"))
    pt.drawRect(3, 3, 22, 22)                      # a sheet with its title block corner
    pt.drawRect(13, 17, 12, 8)
    pt.setPen(QtGui.QPen(QtGui.QColor("#1a9b1a"), 3))
    pt.drawPolyline([QtCore.QPointF(6, 11), QtCore.QPointF(10, 15), QtCore.QPointF(18, 6)])
    pt.end()
    b.setIcon(QtGui.QIcon(pix))
    b.setIconSize(QtCore.QSize(28, 28))
    b.clicked.connect(lambda: (edit_sheet_format(page, False), page.Document.recompute()))

    class _Keep(QtCore.QObject):
        def eventFilter(self, obj, ev):
            if not isinstance(ev, QtCore.QEvent):
                return False          # a stale PySide wrapper can arrive here
            if ev.type() == QtCore.QEvent.Resize:
                b.move(obj.width() - b.width() - 6, 6)
            return False
    keep = _Keep(b)
    vp.installEventFilter(keep)
    b.move(vp.width() - b.width() - 6, 6)
    b.show()
    b.raise_()
    return b


FORMAT_GREYED = ("FreeWorks_DrawBalloon", "FreeWorks_DrawAutoBalloon", "FreeWorks_DrawMagneticLine",
                 "FreeWorks_DrawWeldSymbol", "FreeWorks_DrawHoleCallout", "FreeWorks_DrawDatumFeature",
                 "FreeWorks_DrawDatumTarget", "FreeWorks_DrawCenterMark", "FreeWorks_DrawRevisionSymbol",
                 "FreeWorks_DrawRevisionCloud")       # what the Annotation tab greys in Edit Sheet Format (read 1)


def greyed_on_format(page, name):
    return name in FORMAT_GREYED and page is not None and editing_format(page)


def _format_svg(page, text):
    """The sheet format's SVG with the items drawn on the format added (symbols, notes and lines at their place)."""
    import re
    w, h = _sheet_size(page)
    parts = []
    for v in format_items(page):
        if v.TypeId == "TechDraw::DrawViewAnnotation":
            parts.append(_annotation_svg(v, h))
            continue
        sym = getattr(v, "Symbol", "")
        if not sym or "<svg" not in sym:
            continue
        m = re.search(r'viewBox="([-\d.eE ]+)"', sym)
        try:
            vb = [float(x) for x in m.group(1).split()] if m else None
        except Exception:
            vb = None
        if not vb:
            continue
        k = float(getattr(v, "Scale", 1.0) or 1.0)
        # the symbol's centre (its viewBox centre) at its X, Y; SVG Tiny has no nested <svg>: a group instead
        cu, cv = vb[0] + vb[2] / 2, vb[1] + vb[3] / 2
        body = re.sub(r"^.*?<svg\b[^>]*>", "", sym, count=1, flags=re.S)
        body = body[:body.rfind("</svg>")] if "</svg>" in body else body
        inner = '<g transform="translate(%g,%g) scale(%g) translate(%g,%g)">%s</g>' % (
            float(v.X), h - float(v.Y), k, -cu, -cv, body)
        parts.append('<g id="%s">%s</g>' % (v.Name, inner))
    if not parts:
        return text
    i = text.rfind("</svg>")
    return text[:i] + "\n".join(parts) + "\n" + text[i:] if i >= 0 else text


def _annotation_svg(v, h):
    """A TechDraw text annotation as SVG text at its place (its first line's centre at X, Y)."""
    from xml.sax.saxutils import escape
    size = float(getattr(v, "TextSize", 5.0) or 5.0)
    font = escape(str(getattr(v, "Font", "") or "osifont"), {'"': "&quot;"})
    lines = list(getattr(v, "Text", []) or [])
    step = size * float(getattr(v, "LineSpace", 100) or 100) / 100.0
    x, y = float(v.X), h - float(v.Y)
    spans = "".join('<tspan x="%g" y="%g">%s</tspan>' % (x, y + i * step, escape(str(s))) for i, s in enumerate(lines))
    return ('<g id="%s"><text x="%g" y="%g" font-family="%s" font-size="%gpx" text-anchor="middle" fill="#000">%s'
            '</text></g>' % (v.Name, x, y, font, size, spans))


def save_sheet_format(page, path=None):
    """File > Save Sheet Format...: the sheet's format (with its title block values and what was drawn on the
    format) to an .svg file."""
    with _Untinted(page):
        return _save_sheet_format(page, path)


def _save_sheet_format(page, path=None):
    tpl = page.Template
    if tpl is None:
        return None
    if path is None:
        start = os.path.join(_sheets_dir(), describe(page_template_path(page)).replace(" ", "_") + ".svg")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save Sheet Format", start,
                                                        "Sheet format (*.svg)")
        if not path:
            return None
    src = getattr(tpl, "PageResult", "") or tpl.Template
    if not format_items(page):
        shutil.copyfile(src, path)
        return path
    with open(src, encoding="utf-8") as f:
        text = f.read()
    with open(path, "w", encoding="utf-8") as f:
        f.write(_format_svg(page, text))
    return path


# --------------------------------------------------------------------------- sheet tabs
TAB_BAR = "SWSheetTabs"


def sheet_icon(add=False, size=16):
    """A sheet tab's icon drawn here (no product art): a page with its corner folded; Add Sheet's has a star."""
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pm = _hidpi.canvas(size, size)
    pm.fill(QtCore.Qt.transparent)
    qp = QtGui.QPainter(pm)
    qp.setRenderHint(QtGui.QPainter.Antialiasing)
    k = size / 16.0
    page = QtGui.QPolygonF([QtCore.QPointF(x * k, y * k) for x, y in ((3, 2), (10, 2), (13, 5), (13, 14), (3, 14))])
    qp.setPen(QtGui.QPen(QtGui.QColor("#404040"), 1.0 * k))
    qp.setBrush(QtGui.QColor("#ffffff"))
    qp.drawPolygon(page)
    qp.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(10 * k, 2 * k), QtCore.QPointF(10 * k, 5 * k),
                                     QtCore.QPointF(13 * k, 5 * k)]))
    if add:
        qp.setPen(QtGui.QPen(QtGui.QColor("#c08000"), 0.8 * k))
        qp.setBrush(QtGui.QColor("#ffcc33"))
        import math
        pts = []
        for i in range(10):
            r = (3.2 if i % 2 == 0 else 1.4) * k
            a = -math.pi / 2 + i * math.pi / 5
            pts.append(QtCore.QPointF(4.5 * k + r * math.cos(a), 4.5 * k + r * math.sin(a)))
        qp.drawPolygon(QtGui.QPolygonF(pts))
    qp.end()
    return pm


def sheet_tab_styles():
    """(tab bar, Add Sheet, List) style sheets for the sheet tabs in the current theme."""
    try:
        from . import style
        dark = style.dark()
        t = style.tokens()
    except Exception:
        dark, t = False, None
    if not dark or t is None:
        return ("QTabBar::tab { padding: 2px 10px; background: #e4e4e4; border: 1px solid #b9b9b9; "
                "border-top: none; } QTabBar::tab:selected { background: #ffffff; font-weight: bold; }",
                "QToolButton { background: #d6d6d6; border: 1px solid #b9b9b9; border-top: none; "
                "padding: 1px 8px; }",
                "QToolButton { background: #e4e4e4; border: 1px solid #b9b9b9; border-top: none; "
                "padding: 1px 6px; }")
    return ("QTabBar::tab { padding: 2px 10px; background: %s; color: %s; border: 1px solid %s; border-top: none; }"
            " QTabBar::tab:hover { background: %s; }"
            " QTabBar::tab:selected { background: %s; color: %s; font-weight: bold; }"
            % (t["tab"], t["text_dim"], t["line_light"], t["tab_hover"], t["pane"], t["text"]),
            "QToolButton { background: %s; color: %s; border: 1px solid %s; border-top: none; padding: 1px 8px; }"
            " QToolButton:hover { background: %s; }" % (t["tab"], t["text"], t["line_light"], t["hover"]),
            "QToolButton { background: %s; color: %s; border: 1px solid %s; border-top: none; padding: 1px 6px; }"
            " QToolButton:hover { background: %s; }" % (t["tab"], t["text"], t["line_light"], t["hover"]))


class SheetTabs(QtWidgets.QWidget):
    """The tabs under a drawing sheet: one per sheet, + adds a sheet; right-click a tab for its menu."""

    def __init__(self, page, parent):
        super().__init__(parent)
        self.setObjectName(TAB_BAR)
        self.doc_name = page.Document.Name
        self.page_name = page.Name
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(2)
        self.tabs = QtWidgets.QTabBar(self)
        self.tabs.setObjectName("SWSheetTabBar")
        self.tabs.setShape(QtWidgets.QTabBar.RoundedSouth)
        self.tabs.setDrawBase(False)
        self.tabs.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self.menu)

        # a sheet-and-star icon
        self.tabs.setIconSize(QtCore.QSize(14, 14))
        self.add = QtWidgets.QToolButton(self)
        self.add.setObjectName("SWSheetAddTab")
        self.add.setIcon(QtGui.QIcon(sheet_icon(True)))
        self.add.setIconSize(QtCore.QSize(16, 16))
        self.add.setToolTip("Add Sheet")
        self.add.setAutoRaise(True)
        self.add.clicked.connect(lambda: add_sheet(self.doc(), self.page()))

        self.list = QtWidgets.QToolButton(self)
        self.list.setObjectName("SWSheetListTab")
        self.list.setText("List")
        self.list.setToolTip("List all sheets")
        self.list.setArrowType(QtCore.Qt.UpArrow)
        self.list.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.list.setAutoRaise(True)
        self.list.clicked.connect(self.show_list)
        lay.addWidget(self.tabs)
        lay.addWidget(self.add)
        lay.addWidget(self.list)
        lay.addStretch(1)
        self._restyle()
        try:
            from . import style
            style.signals.theme_changed.connect(self._restyle)
        except Exception as _fw_err:
            App.Console.PrintLog("Sheet tabs theme: %s\n" % _fw_err)
        self.refresh()
        self.tabs.tabBarClicked.connect(self.clicked)
        self.tabs.setMovable(True)
        self.tabs.tabMoved.connect(self.moved)


    def _restyle(self, *args):
        ""

        try:
            qss = sheet_tab_styles()
            if getattr(self, "in_row", False):
                # drawrow-1121: on the bottom tab row the tabs are the row's height
                h = max(12, self.height() - 1 if self.height() > 8 else 17)
                qss = (qss[0].replace("padding: 2px 10px;", "padding: 0px 10px; height: %dpx;" % (h - 1)),
                       qss[1].replace("padding: 1px 8px;", "padding: 0px 8px; height: %dpx;" % h),
                       qss[2].replace("padding: 1px 6px;", "padding: 0px 6px; height: %dpx;" % h))
            self.tabs.setStyleSheet(qss[0])
            self.add.setStyleSheet(qss[1])
            self.list.setStyleSheet(qss[2])
        except RuntimeError:
            return

    def list_menu(self):
        """The List button's menu: every sheet in sheet order (the one in front checked), then Add Sheet."""
        d = self.doc()
        m = QtWidgets.QMenu(self)
        m.setObjectName("SWSheetListMenu")
        if d is None:
            return m
        icon = QtGui.QIcon(sheet_icon())
        for p in pages(d):
            a = m.addAction(icon, p.Label)
            a.setCheckable(True)
            a.setChecked(p.Name == self.page_name)
            a.setData(p.Name)
            a.triggered.connect(lambda _=False, n=p.Name: self.pick(n))
        m.addSeparator()
        a = m.addAction(QtGui.QIcon(sheet_icon(True)), "Add Sheet")
        a.setData("")
        a.triggered.connect(lambda _=False: add_sheet(self.doc(), self.page()))
        return m

    def show_list(self):
        m = self.list_menu()
        self.last_menu = m
        m.popup(self.list.mapToGlobal(QtCore.QPoint(0, 0)) - QtCore.QPoint(0, m.sizeHint().height()))

    def pick(self, name):
        d = self.doc()
        p = d.getObject(name) if d is not None else None
        if p is not None and p.Name != self.page_name:
            show_page(p)
            QtCore.QTimer.singleShot(0, sheet_tabs_refresh)

    def moved(self, a, b):
        d = self.doc()
        if d is None:
            return
        names = [self.tabs.tabData(i) for i in range(self.tabs.count())]
        QtCore.QTimer.singleShot(0, lambda: reorder_sheets(d, names))

    def doc(self):
        try:
            return App.getDocument(self.doc_name)
        except Exception as _fw_err:
            _fw_log("drawsheet.py:1833", _fw_err)
            return None

    def page(self):
        d = self.doc()
        return d.getObject(self.page_name) if d is not None else None

    def refresh(self):
        d = self.doc()
        if d is None:
            return
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        icon = QtGui.QIcon(sheet_icon())
        for p in pages(d):
            i = self.tabs.addTab(icon, p.Label)
            self.tabs.setTabData(i, p.Name)
            if p.Name == self.page_name:
                self.tabs.setCurrentIndex(i)
        self.tabs.blockSignals(False)

    def clicked(self, i):
        d = self.doc()
        if d is None or i < 0:
            return
        p = d.getObject(self.tabs.tabData(i))
        if p is not None and p.Name != self.page_name:
            show_page(p)
            from . import safe_later as _sl; _sl.later(0, self.refresh, self, "tabs")

    def menu(self, pos):
        i = self.tabs.tabAt(pos)
        d = self.doc()
        if d is None or i < 0:
            return
        p = d.getObject(self.tabs.tabData(i))
        m = QtWidgets.QMenu(self)
        m.setObjectName("SWSheetTabMenu")
        self.last_menu = m
        acts = [("Properties...", lambda: sheet_properties(p)), ("Add Sheet...", lambda: add_sheet(d, p)),
                ("Copy", lambda: copy_sheet(p)), ("Paste", lambda: paste_sheet(d)),
                ("Rename", lambda: self.rename(i)), ("Delete", lambda: delete_sheet(p))]
        for text, fn in acts:
            if text == "Delete" and len(pages(d)) < 2:
                continue
            if text == "Paste" and SHEET_CLIP.get("doc") != d.Name:
                continue               # nothing copied in this drawing
            a = m.addAction(text)
            a.triggered.connect(fn)
        m.popup(self.tabs.mapToGlobal(pos))

    def rename(self, i):
        d = self.doc()
        p = d.getObject(self.tabs.tabData(i)) if d is not None else None
        if p is None:
            return
        edit = QtWidgets.QLineEdit(p.Label, self.tabs)
        edit.setObjectName("SWSheetTabRename")
        edit.setGeometry(self.tabs.tabRect(i))
        edit.selectAll()
        edit.show()
        edit.setFocus()
        self.rename_edit = edit

        def done():
            text = edit.text().strip()
            if text:
                p.Label = text
            edit.deleteLater()
            sheet_tabs_refresh()
        edit.editingFinished.connect(done)


def _page_windows():
    """(page, its MDI QMainWindow) for each open sheet window."""
    out = []
    try:
        import TechDrawGui
    except Exception:
        return out
    for name in App.listDocuments():
        d = App.getDocument(name)
        for p in pages(d):
            try:
                scene = TechDrawGui.getSceneForPage(p)
            except Exception:
                scene = None
            if scene is None:
                continue
            for v in scene.views():
                win = v.parentWidget()
                while win is not None and not isinstance(win, QtWidgets.QMainWindow):
                    win = win.parentWidget()
                if win is not None and win is not Gui.getMainWindow():
                    out.append((p, win))
    return out


def _row_strip():
    """drawrow-1121: the bottom tab row (chrome.ModelTabs, Model / 3D Views / Motion Study) when it is on screen.
    A drawing's sheet tabs go on that row, after its first / previous / next / last arrows, across the whole
    window under the FeatureManager tree too. Without the row the tabs stay under the sheet."""
    try:
        from . import shell
        sh = shell.shell()
        t = getattr(sh, "model_tabs", None) if sh is not None and getattr(sh, "enabled", False) else None
        return t if t is not None and t.isVisible() else None
    except Exception:
        return None


def _same(a, b):
    try:
        import shiboken6
        return shiboken6.getCppPointer(a)[0] == shiboken6.getCppPointer(b)[0]
    except Exception:
        return a is b


def _alive(obj):
    try:
        obj.objectName()
        return True
    except (RuntimeError, AttributeError):
        return False


def _row_bar(row, win):
    for c in row.findChildren(QtWidgets.QWidget, TAB_BAR):
        w = getattr(c, "win", None)
        if w is not None and _alive(w) and _same(w, win):
            return c
    return None


def place_row_bars(row):
    """drawrow-1121: the sheet tabs of the drawing window in front on the bottom row, after the arrows; the
    other drawing windows' tabs hidden. Called by the row's refresh."""
    try:
        sub = (row.mdi.activeSubWindow() or row.mdi.currentSubWindow()) if row.mdi is not None else None
        front = sub.widget() if sub is not None else None
    except Exception:
        front = None
    x = int(round(row.nav_w)) + 2
    for b in row.findChildren(QtWidgets.QWidget, TAB_BAR):
        w = getattr(b, "win", None)
        if w is None or not _alive(w):
            b.hide()
            b.deleteLater()
            continue
        if front is not None and _same(w, front):
            g = QtCore.QRect(x, 1, max(0, row.width() - x - 1), max(8, row.height() - 1))
            if b.geometry() != g:
                b.setGeometry(g)
                b._restyle()
            if not b.isVisible():
                b.show()
                b.raise_()
        elif b.isVisible():
            b.hide()


def row_nav(row, which):
    """drawrow-1121: the row's arrows in a drawing: first, previous, next, last sheet."""
    bar = next((b for b in row.findChildren(QtWidgets.QWidget, TAB_BAR) if b.isVisible()), None)
    if bar is None:
        return
    n = bar.tabs.count()
    if n < 1:
        return
    i = max(0, bar.tabs.currentIndex())
    target = {0: 0, 1: max(0, i - 1), 2: min(n - 1, i + 1), 3: n - 1}.get(which, i)
    if target != i:
        bar.clicked(target)


def sheet_tabs_refresh():
    row = _row_strip()          # drawrow-1121
    for p, win in _page_windows():
        tb_own = win.findChild(QtWidgets.QToolBar, "SWSheetTabsBar")
        if tb_own is not None and tb_own.isVisible() != (row is None):
            tb_own.setVisible(row is None)
        if row is not None:
            bar = _row_bar(row, win)
            if bar is None:
                bar = SheetTabs(p, row)
                bar.win = win
                bar.in_row = True
                bar.hide()
                bar._restyle()
                place_row_bars(row)
            else:
                try:
                    bar.refresh()
                except RuntimeError as _fw_err:
                    _fw_log("drawsheet.row", _fw_err)
            continue
        bar = tb_own.findChild(QtWidgets.QWidget, TAB_BAR) if tb_own is not None else None
        if bar is None:
            tb = QtWidgets.QToolBar("Sheets", win)
            tb.setObjectName("SWSheetTabsBar")
            tb.setMovable(False)
            tb.setFloatable(False)
            bar = SheetTabs(p, tb)
            tb.addWidget(bar)
            win.addToolBar(QtCore.Qt.BottomToolBarArea, tb)
        else:
            try:
                bar.refresh()
            except RuntimeError as _fw_err:
                _fw_log("drawsheet.py:1926", _fw_err)
    done = set()
    for p, _win in _page_windows():          # an opened drawing's tree in the sheet order too
        try:
            if p.Document.Name not in done:
                done.add(p.Document.Name)
                tree_order(p.Document)
        except Exception as _fw_err:
            _fw_log("drawsheet.py:1934", _fw_err)


CHANGES = [0]          # document edits seen (any document: tables and title blocks follow the models)
_IN_TICK = [False]     # the sheet tick's own edits are not counted
_DONE = {}             # drawing document name -> (CHANGES, time) of its last full refresh
FULL_EVERY = 3.0       # seconds: a full refresh at least this often, even with nothing edited


def _changed(*_a):
    if not _IN_TICK[0]:
        CHANGES[0] += 1


class _Watch:
    """Keeps the sheet tabs and the tree names up to date as sheets come and go, and counts the edits the
    sheet tick follows (an idle large drawing is not refreshed every second)."""
    me = None

    def slotCreatedObject(self, obj):
        _changed()
        if obj.TypeId == "TechDraw::DrawPage":
            QtCore.QTimer.singleShot(800, sheet_tabs_refresh)

    def slotDeletedObject(self, obj):
        _changed()
        if obj.TypeId == "TechDraw::DrawPage":
            QtCore.QTimer.singleShot(300, sheet_tabs_refresh)

    def slotChangedObject(self, obj, prop):
        _changed()
        if prop == "Label" and obj.TypeId == "TechDraw::DrawPage":
            QtCore.QTimer.singleShot(0, sheet_tabs_refresh)

    slotRecomputedDocument = slotFinishSaveDocument = slotUndoDocument = slotRedoDocument = \
        slotCreatedDocument = slotDeletedDocument = slotRelabelDocument = slotActivateDocument = \
        lambda self, *a: _changed()


def _needs_refresh(doc):
    """True when doc's tables, title blocks and annotations need the tick's full refresh: something was edited
    since the last one, or FULL_EVERY seconds passed."""
    import time
    last = _DONE.get(doc.Name)
    return last is None or last[0] != CHANGES[0] or time.time() - last[1] >= FULL_EVERY


def install():
    if _Watch.me is None:
        _Watch.me = _Watch()
        App.addDocumentObserver(_Watch.me)
        timer = QtCore.QTimer(Gui.getMainWindow())
        timer.setInterval(1000)
        timer.timeout.connect(_tabs_tick)
        timer.start()
        _Watch.timer = timer
        try:
            mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
            mdi.subWindowActivated.connect(lambda *_: QtCore.QTimer.singleShot(200, sheet_tabs_refresh))
            mdi.subWindowActivated.connect(lambda *_: QtCore.QTimer.singleShot(250, status_scale))
        except Exception as _fw_err:
            _fw_log("drawsheet.py:1995", _fw_err)


# --------------------------------------------------------------------------- the status bar's sheet scale
STATUS_SCALE = "SWSheetScaleStatus"
STATUS_SCALES = ("1:1", "1:2", "1:4", "1:5", "1:10", "1:20", "1:50", "2:1", "4:1", "5:1", "10:1")


def set_sheet_scale(page, k):
    """The sheet's scale; the views that use the sheet scale follow (TechDraw's Page scale)."""
    doc = page.Document
    doc.openTransaction("Sheet Scale")
    try:
        page.Scale = float(k)
    finally:
        doc.commitTransaction()
    doc.recompute()
    status_scale()


def _status_button():
    bar = Gui.getMainWindow().statusBar()
    b = bar.findChild(QtWidgets.QToolButton, STATUS_SCALE)
    if b is not None:
        return b
    b = QtWidgets.QToolButton(bar)
    b.setObjectName(STATUS_SCALE)
    b.setToolTip("Sheet scale")
    b.setAutoRaise(True)
    b.setPopupMode(QtWidgets.QToolButton.InstantPopup)
    menu = QtWidgets.QMenu(b)
    menu.setObjectName("SWSheetScaleMenu")
    b.setMenu(menu)
    menu.aboutToShow.connect(lambda: _fill_scale_menu(menu))

    units = next((w for w in bar.findChildren(QtWidgets.QToolButton)
                  if type(w).__name__ == "UnitsButton"), None)
    if units is not None:
        visible = units.isVisible()
        bar.removeWidget(units)
        bar.addPermanentWidget(b)
        bar.addPermanentWidget(units)
        units.setVisible(visible)
    else:
        bar.addPermanentWidget(b)
    return b


def _fill_scale_menu(menu):
    from . import drawings as D
    menu.clear()
    page = D.active_page()
    if page is None:
        return
    now = D.scale_text(page.Scale)
    for text in STATUS_SCALES:
        a = menu.addAction(text)
        a.setCheckable(True)
        a.setChecked(text == now)
        a.triggered.connect(lambda _=False, t=text, p=page: set_sheet_scale(p, D.parse_scale(t)))
    menu.addSeparator()
    u = menu.addAction("User Defined...")
    u.triggered.connect(lambda _=False, p=page: _user_scale(p))
    sp = menu.addAction("Sheet Properties...")
    sp.triggered.connect(lambda _=False, p=page: QtCore.QTimer.singleShot(0, lambda: sheet_properties(p)))


def _user_scale(page):
    from . import drawings as D
    text, ok = QtWidgets.QInputDialog.getText(Gui.getMainWindow(), "User Defined", "Scale:",
                                              text=D.scale_text(page.Scale))
    k = D.parse_scale(text) if ok else None
    if k and k > 0:
        set_sheet_scale(page, k)


def status_scale():
    ""
    try:
        from . import drawings as D
        page = D.active_page()
        b = _status_button()
        if page is None:
            b.hide()
            return None
        a, c = _ratio(float(page.Scale))
        b.setText("%s : %s" % (a, c))
        b.show()
        return b
    except Exception:
        return None


def _tabs_tick():
    status_scale()
    try:
        from . import drawtables
        seen = set()
        for p, _w in _page_windows():
            if p.Document.Name not in seen and _needs_refresh(p.Document):
                seen.add(p.Document.Name)
                _refresh_document(drawtables, p.Document)
            seen.add(p.Document.Name)
            try:
                from . import drawmaint
                drawmaint.paint_out_of_date(p)
            except Exception as _fw_err:
                _fw_log("drawsheet.py:2102", _fw_err)
            try:
                from . import drawdetail         # Detailing mode: the views' saved lines
                drawdetail.paint(p)
            except Exception as _fw_err:
                _fw_log("drawsheet.py:2107", _fw_err)
    except Exception as _fw_err:
        _fw_log("drawsheet.py:2109", _fw_err)
    _tick_hooks()


def _refresh_document(drawtables, doc):
    """The tick's full refresh of a drawing document (its own edits are not counted as new edits)."""
    import time
    _IN_TICK[0] = True
    try:
        drawtables.auto_update_tables(doc)
        drawtables.hide_all_data(doc)
        refresh_all_fields(doc)
        try:
            from . import drawannot          # placed hole callouts follow their holes
            drawannot.refresh_hole_callouts(doc)
            from . import drawmaint
            drawmaint.dangling(doc)
        except Exception as _fw_err:
            _fw_log("drawsheet.py:2127", _fw_err)
        try:
            from . import drawattach         # annotations move with the views they are attached to
            drawattach.follow(doc)
        except Exception as _fw_err:
            _fw_log("drawsheet.py:2132", _fw_err)
    finally:
        _IN_TICK[0] = False
        _DONE[doc.Name] = (CHANGES[0], time.time())


def _tick_hooks():
    try:
        from . import drawselect             # the sheet's press filter (tables, arrow dots) on every open sheet
        for p, _w in _page_windows():
            drawselect.hook_page(p)
    except Exception as _fw_err:
        _fw_log("drawsheet.py:2144", _fw_err)
    try:
        from . import drawtitleblock         # the title block hotspot: a click opens the fill-in
        for p, _w in _page_windows():
            drawtitleblock.hook(p)
    except Exception as _fw_err:
        _fw_log("drawsheet.py:2150", _fw_err)
    try:
        row = _row_strip()                   # drawrow-1121: the tabs are on the bottom row while it is shown
        for p, win in _page_windows():
            if (_row_bar(row, win) if row is not None else win.findChild(QtWidgets.QWidget, TAB_BAR)) is None:
                sheet_tabs_refresh()
                return
    except Exception as _fw_err:
        _fw_log("drawsheet.py:2157", _fw_err)


# --------------------------------------------------------------------------- commands
COMMANDS = {
    "FreeWorks_DrawAddSheet": ("Sheet...", "TechDraw_PageDefault", "Adds a sheet to the drawing."),
    "FreeWorks_DrawSheetProperties": ("Properties...", "TechDraw_PageTemplate",
                                      "Sets the sheet's name, scale, projection type and sheet format."),
    "FreeWorks_DrawEditSheetFormat": ("Edit Sheet Format", "TechDraw_PageTemplate",
                                      "Edits the sheet format: its title block and border."),
    "FreeWorks_DrawEditSheet": ("Edit Sheet", "TechDraw_PageDefault", "Goes back to editing the sheet."),
    "FreeWorks_DrawSaveSheetFormat": ("Save Sheet Format...", "TechDraw_PageTemplate",
                                      "Saves the sheet format to a file."),
}


class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.pixmap, self.tip = COMMANDS[name]

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": _pixmap(self.pixmap)}

    def IsActive(self):
        page = active_page()
        if page is None:
            return False
        if self.name == "FreeWorks_DrawEditSheetFormat":
            return not editing_format(page)
        if self.name == "FreeWorks_DrawEditSheet":
            return editing_format(page)
        return True

    def Activated(self):
        page = active_page()
        if page is None:
            return
        if self.name == "FreeWorks_DrawAddSheet":
            add_sheet(page.Document, page)
        elif self.name == "FreeWorks_DrawSheetProperties":
            sheet_properties(page)
        elif self.name == "FreeWorks_DrawEditSheetFormat":
            edit_sheet_format(page, True)
        elif self.name == "FreeWorks_DrawEditSheet":
            edit_sheet_format(page, False)
        elif self.name == "FreeWorks_DrawSaveSheetFormat":
            save_sheet_format(page)


def register():
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
    install()


def _pixmap(name):
    try:
        from . import drawings
        return drawings.pixmap(name)
    except Exception:
        return name
