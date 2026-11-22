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

import difflib
import gzip
import math
import os
import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import drawings as D

PARAM = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Drawings"


def _param():
    return App.ParamGet(PARAM)


# =========================================================================== Spell Checker
_WORDS = []
_RANK = {}


def dictionary():
    if not _WORDS:
        words = set()
        path = os.path.join(os.path.dirname(__file__), "drawwords.txt.gz")
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                for n, w in enumerate(f):
                    w = w.strip().lower()
                    if w:
                        words.add(w)
                        _RANK.setdefault(w, n)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: spell checker word list not read: %s\n" % error)
        _WORDS.append(words)
    return _WORDS[0] | user_words()


def user_words():
    return set(w for w in _param().GetString("SpellUserWords", "").split("\n") if w)


def add_user_word(word):
    words = user_words()
    words.add(word.lower())
    _param().SetString("SpellUserWords", "\n".join(sorted(words)))


WORD = re.compile(r"[A-Za-z][A-Za-z']*")


def text_items(page):
    ""

    out = []
    for o in page.Views:
        t = getattr(o, "SWText", None)
        if isinstance(t, str) and t:
            out.append((o, "SWText", t))
        elif o.TypeId == "TechDraw::DrawViewAnnotation":
            out.append((o, "Text", "\n".join(o.Text)))
    for o in page.Document.Objects:
        if o.TypeId == "TechDraw::DrawViewDimension" and _on_page(o, page):
            spec = re.sub(r"%[-+ #0-9.]*[a-zA-Z]", " ", o.FormatSpec or "")
            if WORD.search(spec):
                out.append((o, "FormatSpec", o.FormatSpec))
    return out


def _on_page(o, page):
    try:
        return o.findParentPage() == page
    except Exception:
        return False


def misspelled(text, words, ignore=()):
    """[(start, end, word)] of the words in text not in the dictionary (words with digits, and one letter,
    are skipped)."""
    out = []
    for m in WORD.finditer(text):
        w = m.group(0).strip("'")
        if len(w) < 2 or w.lower() in words or w.lower() in ignore:
            continue
        if w.lower().endswith("'s") and w.lower()[:-2] in words:
            continue
        out.append((m.start(), m.start() + len(w), w))
    return out


LETTERS = "abcdefghijklmnopqrstuvwxyz"


def _edits1(w):
    splits = [(w[:i], w[i:]) for i in range(len(w) + 1)]
    out = set(a + b[1:] for a, b in splits if b)
    out |= set(a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1)
    out |= set(a + c + b[1:] for a, b in splits if b for c in LETTERS)
    out |= set(a + c + b for a, b in splits for c in LETTERS)
    return out


def suggestions(word, words, n=6):
    """Words one edit away (most common first), then close matches."""
    low = word.lower()
    near = sorted((w for w in _edits1(low) if w in words), key=lambda w: _RANK.get(w, 10 ** 7))
    got = near[:n]
    if len(got) < n:
        pool = [w for w in words if w[:1] == low[:1] and abs(len(w) - len(low)) <= 2 and w not in got]
        got += difflib.get_close_matches(low, pool, n=n - len(got), cutoff=0.75)
    if word[:1].isupper():
        got = [w.upper() if word.isupper() and len(word) > 1 and word[1:].isupper() else w[:1].upper() + w[1:]
               for w in got]
    return got


def set_text(o, field, old, new):
    """Write corrected text back to the object's field."""
    if field == "SWText":
        from . import drawblocks
        drawblocks.set_note_text(o, new)
    elif field == "Text":
        o.Text = new.split("\n")
    elif field == "FormatSpec":
        o.FormatSpec = new


class SpellChecker(QtWidgets.QDialog):
    """Spell Checker: each word not in the dictionary in turn, with suggestions; Ignore, Ignore All, Add,
    Change, Change All."""

    def __init__(self, page, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWSpellChecker")
        self.setWindowTitle("Spell Checker")
        self.page = page
        self.doc = page.Document
        self.words = dictionary()
        self.ignored = set()
        self.changes = {}
        lay = QtWidgets.QGridLayout(self)
        lay.addWidget(QtWidgets.QLabel("Not in dictionary:", self), 0, 0, 1, 2)
        self.context = QtWidgets.QTextEdit(self)
        self.context.setObjectName("SWSpellContext")
        self.context.setReadOnly(True)
        self.context.setMaximumHeight(70)
        lay.addWidget(self.context, 1, 0)
        lay.addWidget(QtWidgets.QLabel("Change to:", self), 2, 0)
        self.change_to = QtWidgets.QLineEdit(self)
        self.change_to.setObjectName("SWSpellChangeTo")
        lay.addWidget(self.change_to, 3, 0)
        lay.addWidget(QtWidgets.QLabel("Suggestions:", self), 4, 0)
        self.sugg = QtWidgets.QListWidget(self)
        self.sugg.setObjectName("SWSpellSuggestions")
        self.sugg.currentTextChanged.connect(lambda t: t and self.change_to.setText(t))
        self.sugg.itemDoubleClicked.connect(lambda *_: self.change())
        lay.addWidget(self.sugg, 5, 0)
        col = QtWidgets.QVBoxLayout()
        self.buttons = {}
        for label, fn in (("Ignore", self.ignore), ("Ignore All", self.ignore_all), ("Add", self.add),
                          ("Change", self.change), ("Change All", self.change_all), ("Close", self.close)):
            b = QtWidgets.QPushButton(label, self)
            b.setObjectName("SWSpell" + label.replace(" ", ""))
            b.clicked.connect(fn)
            col.addWidget(b)
            self.buttons[label] = b
        col.addStretch(1)
        lay.addLayout(col, 1, 1, 5, 1)
        self.status = QtWidgets.QLabel("", self)
        self.status.setObjectName("SWSpellStatus")
        lay.addWidget(self.status, 6, 0, 1, 2)
        self.items = text_items(page)
        self.index = 0
        self.pos = 0
        self.current = None
        self.resize(480, 360)
        self.doc.openTransaction("Spell Checker")
        try:
            self.next_word()
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise

    def next_word(self):
        while self.index < len(self.items):
            o, field, text = self.items[self.index]
            text = getattr(o, field) if field != "Text" else "\n".join(o.Text)
            self.items[self.index] = (o, field, text)
            for a, b, w in misspelled(text, self.words, self.ignored):
                if a < self.pos:
                    continue
                if w.lower() in self.changes:
                    self.replace(a, b, self.changes[w.lower()])
                    return self.next_word()
                self.current = (a, b, w)
                self.show_word(o, text, a, b, w)
                return True
            self.index += 1
            self.pos = 0
        self.current = None
        self.context.setPlainText("")
        self.sugg.clear()
        self.change_to.setText("")
        self.status.setText("The spelling check is complete.")
        for k in ("Ignore", "Ignore All", "Add", "Change", "Change All"):
            self.buttons[k].setEnabled(False)
        return False

    def show_word(self, o, text, a, b, w):
        html = (_html(text[:a]) + '<b><font color="#c00000">' + _html(w) + "</font></b>" + _html(text[b:]))
        self.context.setHtml(html)
        self.sugg.clear()
        for s in suggestions(w, self.words):
            self.sugg.addItem(s)
        self.change_to.setText(self.sugg.item(0).text() if self.sugg.count() else w)
        if self.sugg.count():
            self.sugg.setCurrentRow(0)
        self.status.setText(o.Label)
        try:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(o)
        except Exception as _fw_err:
            _fw_log("drawmarkup.py:241", _fw_err)

    def replace(self, a, b, new):
        o, field, text = self.items[self.index]
        text2 = text[:a] + new + text[b:]
        set_text(o, field, text, text2)
        self.items[self.index] = (o, field, text2)
        self.pos = a + len(new)
        self.doc.recompute()

    def ignore(self):
        if self.current:
            self.pos = self.current[1]
            self.next_word()

    def ignore_all(self):
        if self.current:
            self.ignored.add(self.current[2].lower())
            self.next_word()

    def add(self):
        if self.current:
            add_user_word(self.current[2])
            self.words = self.words | {self.current[2].lower()}
            self.next_word()

    def change(self):
        if self.current:
            a, b, w = self.current
            self.replace(a, b, self.change_to.text())
            self.next_word()

    def change_all(self):
        if self.current:
            a, b, w = self.current
            self.changes[w.lower()] = self.change_to.text()
            self.replace(a, b, self.change_to.text())
            self.next_word()

    def _commit(self):
        if not getattr(self, "committed", False):
            self.committed = True
            self.doc.commitTransaction()

    def done(self, r):
        self._commit()
        super().done(r)

    def closeEvent(self, e):
        self._commit()
        super().closeEvent(e)


def _html(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")


# =========================================================================== Automatic Border
def border_svg(w, h, rows=4, cols=8, margins=(10.0, 10.0, 10.0, 10.0), thickness=0.7, zone_line=0.35,
               tick=5.0, text=3.5, letters_rows=True, start="Bottom right"):
    """The sheet's border with zone ticks and labels, as an SVG the size of the sheet (mm)."""
    top, bottom, left, right = margins
    x0, y0, x1, y1 = left, top, w - right, h - bottom
    out = ['<rect x="%g" y="%g" width="%g" height="%g" fill="none" stroke="#000" stroke-width="%g"/>'
           % (x0, y0, x1 - x0, y1 - y0, thickness)]
    ix0, iy0, ix1, iy1 = x0 + tick, y0 + tick, x1 - tick, y1 - tick
    out.append('<rect x="%g" y="%g" width="%g" height="%g" fill="none" stroke="#000" stroke-width="%g"/>'
               % (ix0, iy0, ix1 - ix0, iy1 - iy0, zone_line))
    from_right = "right" in start.lower()
    from_bottom = "bottom" in start.lower()

    def label(i, n, letters):
        return chr(ord("A") + i) if letters else str(i + 1)

    font = 'font-family="osifont, Arial" font-size="%g" text-anchor="middle"' % text
    dx = (ix1 - ix0) / max(1, cols)
    for i in range(cols):
        if i:
            x = ix0 + i * dx
            for ya, yb in ((y0, iy0), (iy1, y1)):
                out.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="%g"/>'
                           % (x, ya, x, yb, zone_line))
        k = cols - 1 - i if from_right else i
        t = label(k, cols, not letters_rows)
        cx = ix0 + (i + 0.5) * dx
        for cy in ((y0 + iy0) / 2.0, (iy1 + y1) / 2.0):
            out.append('<text x="%g" y="%g" %s>%s</text>' % (cx, cy + text * 0.35, font, t))
    dy = (iy1 - iy0) / max(1, rows)
    for j in range(rows):
        if j:
            y = iy0 + j * dy
            for xa, xb in ((x0, ix0), (ix1, x1)):
                out.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="%g"/>'
                           % (xa, y, xb, y, zone_line))
        k = rows - 1 - j if from_bottom else j
        t = label(k, rows, letters_rows)
        cy = iy0 + (j + 0.5) * dy
        for cx in ((x0 + ix0) / 2.0, (ix1 + x1) / 2.0):
            out.append('<text x="%g" y="%g" %s>%s</text>' % (cx, cy + text * 0.35, font, t))
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="0 0 %g %g">%s</svg>'
            % (w, h, w, h, "".join(out)))


def borders_of(page):
    return [o for o in page.Views if getattr(o, "SWAnnotation", "") == "AutoBorder"]


def automatic_border(page, **kw):
    """Automatic Border: the sheet's zone border (replaces an earlier one)."""
    doc = page.Document
    w, h = D.sheet_size(page)
    for o in borders_of(page):
        try:
            page.removeView(o)
        except Exception as _fw_err:
            _fw_log("drawmarkup.py:356", _fw_err)
        doc.removeObject(o.Name)
    s = doc.addObject("TechDraw::DrawViewSymbol", "AutomaticBorder")
    s.Symbol = border_svg(w, h, **kw)
    page.addView(s)
    s.X, s.Y = w / 2.0, h / 2.0
    s.Label = "Automatic Border"
    s.addProperty("App::PropertyString", "SWAnnotation", "FreeCAD", "Annotation kind")
    s.SWAnnotation = "AutoBorder"
    s.addProperty("App::PropertyString", "SWBorderZones", "FreeCAD", "rows x columns")
    s.SWBorderZones = "%dx%d" % (kw.get("rows", 4), kw.get("cols", 8))
    try:
        s.LockPosition = True
    except Exception as _fw_err:
        _fw_log("drawmarkup.py:370", _fw_err)
    return s


class AutomaticBorderPanel(D._Panel):
    """Automatic Border: Zones (rows, columns, labels, start corner), Margins, Formatting; OK puts the border
    on the sheet format; Delete Border removes it."""
    TITLE = "Automatic Border"
    PIXMAP = "TechDraw_PageTemplate"

    def _spin(self, box, name, value, lo, hi, dec=2, suffix=" mm"):
        s = QtWidgets.QDoubleSpinBox(box) if dec else QtWidgets.QSpinBox(box)
        s.setObjectName(name)
        s.setRange(lo, hi)
        if dec:
            s.setDecimals(dec)
        s.setValue(value)
        if suffix:
            s.setSuffix(suffix)
        return s

    def build(self):
        self.say("Set the zones and margins of the sheet border, then OK.")
        box, lay = D._group("Zone Size", self.form)
        f = QtWidgets.QFormLayout()
        self.rows = self._spin(box, "SWBorderRows", 4, 1, 26, 0, "")
        self.cols = self._spin(box, "SWBorderColumns", 8, 1, 50, 0, "")
        f.addRow("Rows", self.rows)
        f.addRow("Columns", self.cols)
        self.letters = QtWidgets.QComboBox(box)
        self.letters.setObjectName("SWBorderRowLabels")
        self.letters.addItems(["Rows: letters, columns: numbers", "Rows: numbers, columns: letters"])
        f.addRow(self.letters)
        self.start = QtWidgets.QComboBox(box)
        self.start.setObjectName("SWBorderStart")
        self.start.addItems(["Bottom right", "Bottom left", "Top right", "Top left"])
        f.addRow("Start from", self.start)
        lay.addLayout(f)
        self.lay.addWidget(box)
        box, lay = D._group("Margins", self.form)
        f = QtWidgets.QFormLayout()
        self.margins = []
        for side in ("Top", "Bottom", "Left", "Right"):
            s = self._spin(box, "SWBorderMargin" + side, 10.0, 0.0, 100.0)
            self.margins.append(s)
            f.addRow(side, s)
        lay.addLayout(f)
        self.lay.addWidget(box)
        box, lay = D._group("Formatting", self.form)
        f = QtWidgets.QFormLayout()
        self.thick = self._spin(box, "SWBorderThickness", 0.7, 0.05, 5.0)
        self.zone_line = self._spin(box, "SWBorderZoneLine", 0.35, 0.05, 5.0)
        self.tick = self._spin(box, "SWBorderMarginWidth", 5.0, 1.0, 30.0)
        self.text = self._spin(box, "SWBorderTextHeight", 3.5, 1.0, 20.0)
        f.addRow("Border line", self.thick)
        f.addRow("Zone lines", self.zone_line)
        f.addRow("Zone band", self.tick)
        f.addRow("Text height", self.text)
        lay.addLayout(f)
        self.lay.addWidget(box)
        self.delete = QtWidgets.QPushButton("Delete Border", self.form)
        self.delete.setObjectName("SWBorderDelete")
        self.delete.setEnabled(bool(borders_of(self.page)))
        self.delete.clicked.connect(self.delete_border)
        self.lay.addWidget(self.delete)
        self.deleted = False

    def options(self):
        return dict(rows=int(self.rows.value()), cols=int(self.cols.value()),
                    margins=tuple(s.value() for s in self.margins), thickness=self.thick.value(),
                    zone_line=self.zone_line.value(), tick=self.tick.value(), text=self.text.value(),
                    letters_rows=self.letters.currentIndex() == 0, start=self.start.currentText())

    def delete_border(self):
        for o in borders_of(self.page):
            try:
                self.page.removeView(o)
            except Exception as _fw_err:
                _fw_log("drawmarkup.py:448", _fw_err)
            self.doc.removeObject(o.Name)
        self.deleted = True
        self.delete.setEnabled(False)
        self.say("Border deleted. OK to keep the sheet without it.")

    def finish(self):
        if not self.deleted:
            self.made = [automatic_border(self.page, **self.options())]


# =========================================================================== Markup
def markup_color():
    return _param().GetString("MarkupColor", "#d01010")


def set_markup_color(color):
    _param().SetString("MarkupColor", QtGui.QColor(color).name())


ASK_COLOR = []      # tests answer the color box here


def pick_color():
    """Markup > Color: the pen color for the next markups."""
    if ASK_COLOR:
        set_markup_color(ASK_COLOR.pop(0))
        return True
    c = QtWidgets.QColorDialog.getColor(QtGui.QColor(markup_color()), Gui.getMainWindow(), "Color")
    if not c.isValid():
        return False
    set_markup_color(c)
    return True


def markup_width():
    return _param().GetFloat("MarkupWidth", 0.7)


def markups_of(page):
    return [o for o in page.Views if getattr(o, "SWAnnotation", "") in ("Markup", "MarkupNote")]


def _symbol(page, name, body, at, reach, label, kind):
    from . import drawannot as DA
    return DA.svg_symbol(page, name, body, reach, at, label, kind)


def markup_stroke(page, pts, color=None, width=None):
    """A freehand markup stroke through sheet points pts."""
    color = color or markup_color()
    width = width or markup_width()
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    rel = [(p[0] - cx, -(p[1] - cy)) for p in pts]
    reach = max(math.hypot(*q) for q in rel) + width
    body = ('<polyline points="%s" fill="none" stroke="%s" stroke-width="%g" stroke-linecap="round" '
            'stroke-linejoin="round"/>' % (" ".join("%.2f,%.2f" % q for q in rel), color, width))
    n = 1 + len([o for o in page.Document.Objects if getattr(o, "SWAnnotation", "") == "Markup"])
    return _symbol(page, "Markup", body, (cx, cy), reach, "Markup%d" % n, "Markup")


def markup_note(page, text, at, color=None):
    color = color or markup_color()
    size = 3.5
    lines = text.split("\n")
    w = 0.6 * size * max(len(l) for l in lines) + 3
    h = size * 1.4 * len(lines) + 2
    body = ['<rect x="%g" y="%g" width="%g" height="%g" fill="#fff6a8" stroke="%s" stroke-width="0.35"/>'
            % (-w / 2, -h / 2, w, h, color)]
    for i, line in enumerate(lines):
        body.append('<text x="%g" y="%g" font-family="osifont, Arial" font-size="%g" fill="%s">%s</text>'
                    % (-w / 2 + 1.5, -h / 2 + 1 + size * (1.1 + 1.4 * i), size, color, _html(line)))
    n = 1 + len([o for o in page.Document.Objects if getattr(o, "SWAnnotation", "") == "MarkupNote"])
    s = _symbol(page, "MarkupNote", "".join(body), at, math.hypot(w, h) / 2, "Markup Note%d" % n, "MarkupNote")
    s.addProperty("App::PropertyString", "SWText", "FreeCAD", "markup note text")
    s.SWText = text
    return s


class _Release(QtCore.QObject):
    def __init__(self, view, fn):
        super().__init__()
        self.view, self.fn = view, fn
        if view is not None:
            view.viewport().installEventFilter(self)

    def stop(self):
        if self.view is not None:
            try:
                self.view.viewport().removeEventFilter(self)
            except Exception as _fw_err:
                _fw_log("drawmarkup.py:540", _fw_err)

    def eventFilter(self, obj, event):
        try:
            if isinstance(event, QtCore.QEvent) and event.type() == QtCore.QEvent.MouseButtonRelease and \
                    event.button() == QtCore.Qt.LeftButton:
                self.fn(D.to_sheet(self.view.mapToScene(event.position().toPoint())))
                return True
        except Exception as _fw_err:
            _fw_log("drawmarkup.py:549", _fw_err)
        return False


class _ColorButton(QtWidgets.QPushButton):
    def __init__(self, color, parent):
        super().__init__(parent)
        self.set(color)
        self.clicked.connect(self.pick)

    def set(self, color):
        self.color = color
        self.setStyleSheet("background-color: %s;" % color)
        self.setText(color)

    def pick(self):
        c = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.color), self, "Markup colour")
        if c.isValid():
            self.set(c.name())


ACTIVE = []


class MarkupDrawPanel(D._Panel):
    """Markup > Draw: press and drag on the sheet to draw; each stroke is one markup."""
    TITLE = "Draw"
    PIXMAP = "TechDraw_Annotation"

    def build(self):
        self.say("Press and drag on the sheet to draw markups. OK when done.")
        box, lay = D._group("Pen", self.form)
        f = QtWidgets.QFormLayout()
        self.color = _ColorButton(markup_color(), box)
        self.color.setObjectName("SWMarkupColor")
        self.width = QtWidgets.QDoubleSpinBox(box)
        self.width.setObjectName("SWMarkupWidth")
        self.width.setRange(0.1, 5.0)
        self.width.setValue(markup_width())
        self.width.setSuffix(" mm")
        f.addRow("Color", self.color)
        f.addRow("Thickness", self.width)
        lay.addLayout(f)
        self.lay.addWidget(box)
        self.stroke = None
        self.presses = self.releases = 0
        self.release = _Release(D.page_view(self.page), self.end)
        ACTIVE[:] = [self]

    def sheet_click(self, p):
        self.presses += 1
        self.stroke = [p]
        return True

    def sheet_move(self, p):
        if self.stroke is not None and QtWidgets.QApplication.mouseButtons() & QtCore.Qt.LeftButton:
            if math.hypot(p[0] - self.stroke[-1][0], p[1] - self.stroke[-1][1]) >= 0.3:
                self.stroke.append(p)

    def end(self, p):
        self.releases += 1
        if self.stroke is None:
            return
        self.stroke.append(p)
        if len(self.stroke) >= 2:
            self.made.append(markup_stroke(self.page, self.stroke, self.color.color, self.width.value()))
            self.doc.recompute()
        self.stroke = None

    def accept(self):
        self.release.stop()
        _param().SetString("MarkupColor", self.color.color)
        _param().SetFloat("MarkupWidth", self.width.value())
        return super().accept()

    def reject(self):
        self.release.stop()
        return super().reject()


class MarkupNotePanel(D._Panel):
    """Markup Note: type the text, click to place it."""
    TITLE = "Markup Note"
    PIXMAP = "TechDraw_Annotation"

    def build(self):
        self.say("Type the markup text, then click on the sheet to place it.")
        box, lay = D._group("Text", self.form)
        self.text = QtWidgets.QPlainTextEdit(box)
        self.text.setObjectName("SWMarkupNoteText")
        self.text.setMaximumHeight(80)
        lay.addWidget(self.text)
        self.lay.addWidget(box)

    def sheet_click(self, p):
        t = self.text.toPlainText().strip()
        if not t:
            self.say("Type the markup text first.")
            return True
        self.made.append(markup_note(self.page, t, p))
        self.doc.recompute()
        self.say("Markup note placed. Click to place another, or OK.")
        return True


class MarkupEraserPanel(D._Panel):
    """Eraser: click a markup to remove it."""
    TITLE = "Eraser"
    PIXMAP = "TechDraw_Annotation"

    def build(self):
        self.say("Click the markups to erase. OK when done.")

    def sheet_click(self, p):
        from . import drawblocks
        o = drawblocks.symbol_at(self.page, p)
        if o is not None and o in markups_of(self.page):
            self.page.removeView(o)
            self.doc.removeObject(o.Name)
            self.doc.recompute()
        return True


def zoom_to_markup(page):
    view = D.page_view(page)
    ms = markups_of(page)
    if view is None or not ms:
        return False
    from . import drawblocks
    xs, ys = [], []
    for o in ms:
        hw, hh = drawblocks.symbol_box(o)
        xs += [float(o.X) - hw, float(o.X) + hw]
        ys += [float(o.Y) - hh, float(o.Y) + hh]
    a, b = D.to_scene(min(xs) - 5, max(ys) + 5), D.to_scene(max(xs) + 5, min(ys) - 5)
    view.fitInView(QtCore.QRectF(a, b).normalized(), QtCore.Qt.KeepAspectRatio)
    return True


class MarkupOptions(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWMarkupOptions")
        self.setWindowTitle("Markup Options")
        f = QtWidgets.QFormLayout(self)
        self.color = _ColorButton(markup_color(), self)
        self.color.setObjectName("SWMarkupOptionsColor")
        self.width = QtWidgets.QDoubleSpinBox(self)
        self.width.setObjectName("SWMarkupOptionsWidth")
        self.width.setRange(0.1, 5.0)
        self.width.setValue(markup_width())
        self.width.setSuffix(" mm")
        self.show_all = QtWidgets.QCheckBox("Show markups", self)
        self.show_all.setObjectName("SWMarkupShow")
        self.show_all.setChecked(_param().GetBool("MarkupShow", True))
        f.addRow("Pen color", self.color)
        f.addRow("Pen thickness", self.width)
        f.addRow(self.show_all)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.apply)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def apply(self):
        _param().SetString("MarkupColor", self.color.color)
        _param().SetFloat("MarkupWidth", self.width.value())
        _param().SetBool("MarkupShow", self.show_all.isChecked())
        page = D.active_page()
        if page is not None:
            for o in markups_of(page):
                try:
                    o.ViewObject.Visibility = self.show_all.isChecked()
                except Exception as _fw_err:
                    _fw_log("drawmarkup.py:722", _fw_err)
        self.accept()


# =========================================================================== commands
COMMANDS = {
    "FreeWorks_DrawSpellChecker": ("Spell Checker", "TechDraw_Annotation",
                                   "Checks the spelling of the notes and dimension text on the sheet."),
    "FreeWorks_DrawAutomaticBorder": ("Automatic Border", "TechDraw_PageTemplate",
                                      "Adds a border with zones to the sheet format (while editing it)."),
    "FreeWorks_DrawMarkupDraw": ("Draw", "TechDraw_Annotation", "Draws markups on the sheet with the mouse."),
    "FreeWorks_DrawMarkupNote": ("Markup Note", "TechDraw_Annotation", "Adds a markup note."),
    "FreeWorks_DrawMarkupEraser": ("Eraser", "TechDraw_Annotation", "Erases markups."),
    "FreeWorks_DrawZoomToMarkup": ("Zoom to Markup", "TechDraw_Annotation", "Zooms to the markups."),
    "FreeWorks_DrawMarkupOptions": ("Markup Options", "TechDraw_Annotation", "Markup pen and display options."),
    "FreeWorks_DrawMarkupColor": ("Color", "TechDraw_Annotation", "The markup pen's color."),
    "FreeWorks_DrawMarkupSelect": ("Select", "TechDraw_Annotation",
                                   "Selects the sheet's markups (then Delete or the arrow keys act on them)."),
    "FreeWorks_DrawMarkupToggle": ("Markup", "TechDraw_Annotation",
                                   "Turns markup on: Color, Draw, Erase, Select, Touch and Note come live."),
    "FreeWorks_DrawMarkupTouch": ("Touch", "TechDraw_Annotation",
                                  "Draws markups with a finger or pen on a touch screen (a touch draws, as Draw)."),
}

MARKUP_ON = []
TAB_TOOLS = ("FreeWorks_DrawMarkupColor", "FreeWorks_DrawMarkupDraw", "FreeWorks_DrawMarkupEraser",
             "FreeWorks_DrawMarkupSelect", "FreeWorks_DrawMarkupTouch", "FreeWorks_DrawMarkupNote")


def markup_on():
    """Markup turned on, and its button shown pressed (a Markup tool picked while Markup is off)."""
    MARKUP_ON[:] = [True]
    try:
        for a in Gui.Command.get("FreeWorks_DrawMarkupToggle").getAction():
            if a.isCheckable() and not a.isChecked():
                a.blockSignals(True)
                a.setChecked(True)
                a.blockSignals(False)
    except Exception as _fw_err:
        _fw_log("drawmarkup:markup_on", _fw_err)


def touch_on():
    return _param().GetBool("MarkupTouch", False)


class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.pixmap, self.tip = COMMANDS[name]

    def GetResources(self):
        r = {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": D.pixmap(self.pixmap)}
        if self.name == "FreeWorks_DrawSpellChecker":
            r["Accel"] = "F7"
        if self.name == "FreeWorks_DrawMarkupToggle":
            r["Checkable"] = bool(MARKUP_ON)
        if self.name == "FreeWorks_DrawMarkupTouch":
            r["Checkable"] = touch_on()
        return r

    def IsActive(self):
        page = D.active_page()
        if page is None or D.busy() or not D.sheet_shown(page):
            return False
        if self.name == "FreeWorks_DrawAutomaticBorder":
            from . import drawsheet
            return drawsheet.editing_format(page)
        # a Markup tool picked while Markup is off turns it on (see markup_on): never greyed for that
        if self.name in ("FreeWorks_DrawMarkupEraser", "FreeWorks_DrawZoomToMarkup", "FreeWorks_DrawMarkupSelect"):
            return bool(markups_of(page))
        return True

    def Activated(self, checked=None):
        if self.name == "FreeWorks_DrawMarkupToggle":
            MARKUP_ON[:] = [True] if (checked if checked is not None else not MARKUP_ON) else []
            return
        if self.name == "FreeWorks_DrawMarkupTouch":
            on = bool(checked) if checked is not None else not touch_on()
            _param().SetBool("MarkupTouch", on)
            if on:
                page = D.active_page()
                if page is not None:
                    D._show(MarkupDrawPanel(page))      # a touch (a mouse press from the screen) draws
            return
        page = D.active_page()
        if page is None:
            return
        if self.name in TAB_TOOLS and not MARKUP_ON:
            markup_on()
        if self.name == "FreeWorks_DrawSpellChecker":
            SpellChecker(page).exec_()
        elif self.name == "FreeWorks_DrawAutomaticBorder":
            D._show(AutomaticBorderPanel(page))
        elif self.name == "FreeWorks_DrawMarkupDraw":
            D._show(MarkupDrawPanel(page))
        elif self.name == "FreeWorks_DrawMarkupNote":
            D._show(MarkupNotePanel(page))
        elif self.name == "FreeWorks_DrawMarkupEraser":
            D._show(MarkupEraserPanel(page))
        elif self.name == "FreeWorks_DrawZoomToMarkup":
            zoom_to_markup(page)
        elif self.name == "FreeWorks_DrawMarkupOptions":
            MarkupOptions().exec_()
        elif self.name == "FreeWorks_DrawMarkupColor":
            pick_color()
        elif self.name == "FreeWorks_DrawMarkupSelect":
            Gui.Selection.clearSelection()
            for o in markups_of(page):
                Gui.Selection.addSelection(page.Document.Name, o.Name)


def register():
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
    try:
        c = Gui.Command.get("FreeWorks_DrawSpellChecker")
        if not c.getShortcut():
            c.setShortcut("F7")
    except Exception as _fw_err:
        _fw_log("drawmarkup.py:829", _fw_err)
