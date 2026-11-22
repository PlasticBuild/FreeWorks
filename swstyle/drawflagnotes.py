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

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import drawings as D

BANK = "FlagNoteBank"
FLAG = "FlagNote"
SHAPES = ("Triangle", "Circle", "Square", "Hexagon")
STROKE = 0.25


def _font(doc):
    try:
        from . import drawannot as DA
        return DA.doc_font(doc)
    except Exception:
        return ""


def _size():
    try:
        from . import drawannot as DA
        return float(DA.TEXT_SIZE)
    except Exception:
        return 3.5


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def flag_shape(shape, cx, cy, r, colour="#000"):
    """The flag outline around (cx, cy), r its size."""
    if shape == "Circle":
        return '<circle cx="%g" cy="%g" r="%g" fill="none" stroke="%s" stroke-width="%g"/>' % (cx, cy, r, colour,
                                                                                               STROKE)
    if shape == "Square":
        return '<rect x="%g" y="%g" width="%g" height="%g" fill="none" stroke="%s" stroke-width="%g"/>' % (
            cx - r, cy - r, 2 * r, 2 * r, colour, STROKE)
    if shape == "Hexagon":
        pts = " ".join("%g,%g" % (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
                       for a in range(0, 360, 60))
    else:
        pts = "%g,%g %g,%g %g,%g" % (cx, cy - r * 1.15, cx + r, cy + r * 0.6, cx - r, cy + r * 0.6)
    return '<polygon points="%s" fill="none" stroke="%s" stroke-width="%g"/>' % (pts, colour, STROKE)


def _flag(shape, number, cx, cy, size, colour="#000"):
    r = size * 0.95
    ty = cy + size * 0.35 + (size * 0.15 if shape == "Triangle" else 0.0)
    return flag_shape(shape, cx, cy, r, colour) + (
        '<text x="%g" y="%g" font-family="osifont, Arial" font-size="%g" text-anchor="middle" fill="%s">%s</text>'
        % (cx, ty, size * 0.8, colour, _esc(number)))


def _wrap(body, R):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="%g %g %g %g">%s</svg>'
            % (2 * R, 2 * R, -R, -R, 2 * R, 2 * R, body))


# --------------------------------------------------------------------------- the bank
def entries(bank):
    try:
        return json.loads(getattr(bank, "SWFlagNotes", "") or "[]")
    except Exception:
        return []


def _store(bank, items):
    if "SWFlagNotes" not in bank.PropertiesList:
        bank.addProperty("App::PropertyString", "SWFlagNotes", "FreeCAD", "the flag notes (id, text)")
    bank.SWFlagNotes = json.dumps(items)


def bank_svg(bank):
    items = entries(bank)
    size = _size()
    shape = getattr(bank, "SWFlagShape", "Triangle") or "Triangle"
    lines = ['<text x="0" y="%g" font-family="osifont, Arial" font-size="%g" font-weight="bold">NOTES:</text>'
             % (0, size)]
    width = 20.0
    for n, e in enumerate(items, 1):
        y = (n + 0.5) * size * 2.2
        lines.append(_flag(shape, str(n), size, y - size * 0.35, size))
        lines.append('<text x="%g" y="%g" font-family="osifont, Arial" font-size="%g">%s</text>'
                     % (size * 2.4, y, size, _esc(e.get("text", ""))))
        width = max(width, size * 2.4 + 0.6 * size * len(e.get("text", "")))
    height = (len(items) + 1) * size * 2.2
    body = '<g transform="translate(%g %g)">%s</g>' % (-width / 2.0, -height / 2.0, "".join(lines))
    try:
        from . import drawannot as DA
        body = DA.with_font(body, _font(bank.Document))
    except Exception as _fw_err:
        _fw_log("drawflagnotes.py:118", _fw_err)
    return _wrap(body, max(width, height) / 2.0 + 5.0)


def banks(doc):
    return [o for o in doc.Objects if getattr(o, "SWAnnotation", "") == BANK]


def make_bank(page, at, texts=(), shape="Triangle"):
    """A flag note bank at sheet point at with the notes texts."""
    doc = page.Document
    s = doc.addObject("TechDraw::DrawViewSymbol", BANK)
    page.addView(s)
    s.X, s.Y = at
    s.Label = "Flag Note Bank%d" % len(banks(doc))
    s.addProperty("App::PropertyString", "SWAnnotation", "FreeCAD", "FreeCAD annotation kind")
    s.SWAnnotation = BANK
    s.addProperty("App::PropertyString", "SWFlagShape", "FreeCAD", "flag shape")
    s.SWFlagShape = shape
    s.addProperty("App::PropertyInteger", "SWFlagNext", "FreeCAD", "next entry id")
    _store(s, [])
    for t in texts:
        add_note(s, t, sync_now=False)
    sync(doc)
    return s


def add_note(bank, text, sync_now=True):
    items = entries(bank)
    bank.SWFlagNext = int(getattr(bank, "SWFlagNext", 0)) + 1
    fid = "f%d" % bank.SWFlagNext
    items.append({"id": fid, "text": text})
    _store(bank, items)
    if sync_now:
        sync(bank.Document)
    return fid


def edit_note(bank, index, text):
    items = entries(bank)
    if 0 <= index < len(items):
        items[index]["text"] = text
        _store(bank, items)
        sync(bank.Document)


def remove_note(bank, index):
    items = entries(bank)
    if 0 <= index < len(items):
        items.pop(index)
        _store(bank, items)
        sync(bank.Document)


def move_note(bank, index, delta):
    items = entries(bank)
    j = index + delta
    if 0 <= index < len(items) and 0 <= j < len(items):
        items[index], items[j] = items[j], items[index]
        _store(bank, items)
        sync(bank.Document)
        return j
    return index


# --------------------------------------------------------------------------- flags
def flags(doc, bank=None):
    return [o for o in doc.Objects if getattr(o, "SWAnnotation", "") == FLAG and
            (bank is None or getattr(o, "SWFlagBank", "") == bank.Name)]


def number_of(flag):
    """The flag's number in its bank (1...), else None (its entry was deleted)."""
    bank = flag.Document.getObject(getattr(flag, "SWFlagBank", "") or "")
    if bank is None:
        return None
    for n, e in enumerate(entries(bank), 1):
        if e.get("id") == getattr(flag, "SWFlagId", ""):
            return n
    return None


def flag_svg(flag):
    bank = flag.Document.getObject(getattr(flag, "SWFlagBank", "") or "")
    shape = (getattr(bank, "SWFlagShape", "") if bank is not None else "") or "Triangle"
    n = number_of(flag)
    colour = "#000"
    if n is None:
        try:
            from . import drawmaint
            c = drawmaint.dangling_color()
            colour = "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in c[:3])
        except Exception:
            colour = "#808000"
    size = _size()
    body = [_flag(shape, "?" if n is None else str(n), 0, 0, size, colour)]
    reach = size * 1.2
    tip = getattr(flag, "SWTip", None)
    if tip is not None and tip.z >= 0:
        tx, ty = tip.x - float(flag.X), -(tip.y - float(flag.Y))
        L = math.hypot(tx, ty)
        if L > size:
            sx, sy = tx / L * size, ty / L * size
            body.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="%s" stroke-width="%g"/>'
                        % (sx, sy, tx, ty, colour, STROKE))
            a = math.atan2(ty - sy, tx - sx)
            w, l = size * 0.3, size * 0.9
            p1 = (tx - l * math.cos(a) + w * math.sin(a), ty - l * math.sin(a) - w * math.cos(a))
            p2 = (tx - l * math.cos(a) - w * math.sin(a), ty - l * math.sin(a) + w * math.cos(a))
            body.append('<polygon points="%g,%g %g,%g %g,%g" fill="%s"/>' % (tx, ty, p1[0], p1[1], p2[0], p2[1],
                                                                          colour))
            reach = max(reach, L)
    svg = "".join(body)
    try:
        from . import drawannot as DA
        svg = DA.with_font(svg, _font(flag.Document))
    except Exception as _fw_err:
        _fw_log("drawflagnotes.py:235", _fw_err)
    return _wrap(svg, reach + 5.0)


def place_flag(page, bank, index, at, tip=None):
    """A flag of bank entry index (0-based) at sheet point at, its leader to tip (or none)."""
    items = entries(bank)
    if not 0 <= index < len(items):
        return None
    doc = page.Document
    s = doc.addObject("TechDraw::DrawViewSymbol", FLAG)
    page.addView(s)
    s.X, s.Y = at
    s.addProperty("App::PropertyString", "SWAnnotation", "FreeCAD", "FreeCAD annotation kind")
    s.SWAnnotation = FLAG
    s.addProperty("App::PropertyString", "SWFlagBank", "FreeCAD", "the flag note bank")
    s.SWFlagBank = bank.Name
    s.addProperty("App::PropertyString", "SWFlagId", "FreeCAD", "the bank entry")
    s.SWFlagId = items[index]["id"]
    s.addProperty("App::PropertyVector", "SWTip", "FreeCAD", "leader point")
    s.SWTip = App.Vector(tip[0], tip[1], 0) if tip else App.Vector(0, 0, -1)
    s.Label = "Flag Note%d" % len(flags(doc))
    s.Symbol = flag_svg(s)
    return s


def sync(doc):
    """The banks and their flags drawn again (numbers follow the banks' order)."""
    for b in banks(doc):
        svg = bank_svg(b)
        if b.Symbol != svg:
            b.Symbol = svg
    for f in flags(doc):
        svg = flag_svg(f)
        if f.Symbol != svg:
            f.Symbol = svg
    doc.recompute()


# --------------------------------------------------------------------------- PropertyManager
class FlagNotePanel(D._Panel):
    """Flag Note: the bank's notes (Add, Delete, Move Up / Down, the text of the one picked), the flag shape;
    a click on empty sheet places the bank (when the drawing has none), then each click places a flag of the
    note picked; a click on a view's line first gives the flag a leader."""
    TITLE = "Flag Note"
    PIXMAP = "TechDraw_Annotation"
    LAYER = True

    def build(self):
        self.say("Add the notes, pick one, then click where its flag goes (click a line first for a leader).")
        found = banks(self.doc)
        self.bank = found[0] if found else None
        box, lay = D._group("Flag Note Bank", self.form)
        self.list = QtWidgets.QListWidget(box)
        self.list.setObjectName("SWFlagNoteList")
        self.list.setMaximumHeight(130)
        lay.addWidget(self.list)
        self.text = QtWidgets.QLineEdit(box)
        self.text.setObjectName("SWFlagNoteText")
        self.text.setPlaceholderText("Note text")
        lay.addWidget(self.text)
        row = QtWidgets.QGridLayout()           # two by two: four in a row made the pane 361 px wide
        self.buttons = {}
        for n, (name, label) in enumerate((("add", "Add"), ("delete", "Delete"), ("up", "Move Up"),
                                           ("down", "Move Down"))):
            b = QtWidgets.QPushButton(label, box)
            b.setObjectName("SWFlagNote" + label.replace(" ", ""))
            row.addWidget(b, n // 2, n % 2)
            self.buttons[name] = b
        lay.addLayout(row)
        self.lay.addWidget(box)
        box, lay = D._group("Flag", self.form)
        self.shape = QtWidgets.QComboBox(box)
        self.shape.setObjectName("SWFlagNoteShape")
        self.shape.addItems(SHAPES)
        if self.bank is not None:
            self.shape.setCurrentText(getattr(self.bank, "SWFlagShape", "Triangle") or "Triangle")
        lay.addWidget(self.shape)
        self.lay.addWidget(box)
        self.pending = []           # notes added before the bank is placed
        self.tip = None
        self.buttons["add"].clicked.connect(self.add)
        self.buttons["delete"].clicked.connect(self.delete)
        self.buttons["up"].clicked.connect(lambda: self.move(-1))
        self.buttons["down"].clicked.connect(lambda: self.move(1))
        self.text.editingFinished.connect(self.retext)
        self.list.currentRowChanged.connect(self.picked)
        self.shape.currentTextChanged.connect(self.reshape)
        self.fill()

    def items(self):
        return entries(self.bank) if self.bank is not None else [{"id": "", "text": t} for t in self.pending]

    def fill(self, row=None):
        cur = self.list.currentRow() if row is None else row
        self.list.blockSignals(True)
        self.list.clear()
        for n, e in enumerate(self.items(), 1):
            self.list.addItem("%d  %s" % (n, e.get("text", "")))
        self.list.blockSignals(False)
        if self.list.count():
            self.list.setCurrentRow(max(0, min(cur, self.list.count() - 1)))

    def picked(self, row):
        items = self.items()
        self.text.setText(items[row]["text"] if 0 <= row < len(items) else "")

    def add(self, *_):
        text = self.text.text().strip() or "NOTE"
        if self.bank is not None:
            add_note(self.bank, text)
        else:
            self.pending.append(text)
        self.fill(len(self.items()) - 1)

    def delete(self, *_):
        row = self.list.currentRow()
        if row < 0:
            return
        if self.bank is not None:
            remove_note(self.bank, row)
        elif row < len(self.pending):
            self.pending.pop(row)
        self.fill(row)

    def move(self, delta):
        row = self.list.currentRow()
        if self.bank is not None:
            row = move_note(self.bank, row, delta)
        elif 0 <= row + delta < len(self.pending):
            self.pending[row], self.pending[row + delta] = self.pending[row + delta], self.pending[row]
            row += delta
        self.fill(row)

    def retext(self):
        row = self.list.currentRow()
        text = self.text.text().strip()
        if row < 0 or not text:
            return
        if self.bank is not None:
            if entries(self.bank)[row]["text"] != text:
                edit_note(self.bank, row, text)
        else:
            self.pending[row] = text
        self.fill(row)

    def reshape(self, shape):
        if self.bank is not None:
            self.bank.SWFlagShape = shape
            sync(self.doc)

    def sheet_click(self, p):
        if self.bank is None:
            self.bank = make_bank(self.page, p, self.pending, self.shape.currentText())
            self.made.append(self.bank)
            self.pending = []
            self.fill(0)
            self.say("Flag note bank placed. Pick a note, then click where its flag goes.")
            return True
        try:
            from . import drawviews as DV
            on_view = DV.view_at(self.page, p, margin=0.0)
        except Exception:
            on_view = None
        if on_view is not None and self.tip is None:
            self.tip = p
            self.say("Click where the flag goes.")
            return True
        row = self.list.currentRow()
        f = place_flag(self.page, self.bank, max(row, 0), p, self.tip)
        self.tip = None
        if f is not None:
            self.made.append(f)
            self.doc.recompute()
            self.say("Flag %s placed. Click for the next one, or OK." % (number_of(f) or ""))
        return True


# --------------------------------------------------------------------------- command
class _Command:
    def GetResources(self):
        return {"MenuText": "Flag Note...", "ToolTip": "Adds a flag note bank and flags that point to its notes.",
                "Pixmap": D.pixmap("TechDraw_Annotation")}

    def IsActive(self):
        return D.active_page() is not None

    def Activated(self, *_):
        page = D.active_page()
        if page is not None:
            D._show(FlagNotePanel(page))


def register():
    if "FreeWorks_DrawFlagNote" not in Gui.listCommands():
        Gui.addCommand("FreeWorks_DrawFlagNote", _Command())
