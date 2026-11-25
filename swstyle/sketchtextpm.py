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

import math
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets
from . import unitbox

from . import paths, relationspm, sketchtext, sketchtoolpm

LEFT, CENTER, RIGHT, FIT = "left", "center", "right", "fit"


def document_font():
    """The font file of the document's annotation font (Options > Document Properties >
    Annotations > Font), when the computer has it; else ''."""
    try:
        from . import optionspages
        family = str(optionspages.doc_value(App.ActiveDocument, "Annotations", "Font", "Century Gothic"))
    except Exception:
        family = "Century Gothic"
    want = family.lower().replace(" ", "")
    files = sketchtext.font_files()
    for name in sorted(files, key=len):
        stem = os.path.splitext(name)[0].lower().replace(" ", "").replace("-regular", "")
        if stem == want or stem.replace("-", "") == want:
            return files[name]
    for name in sorted(files, key=len):
        if want and want in name.lower().replace(" ", "").replace("-", ""):
            return files[name]
    return ""


def styled_font(font, bold, italic):
    """The bold / italic file of font's family when there is one (arial.ttf -> arialbd.ttf,
    DejaVuSans.ttf -> DejaVuSans-Bold.ttf ...), else font."""
    if not (bold or italic) or not font:
        return font
    d, name = os.path.split(font)
    stem, ext = os.path.splitext(name)
    base = stem
    for tail in ("-Regular", "_Regular", "Regular"):
        if base.endswith(tail):
            base = base[: -len(tail)]
    want = {(True, False): ("bd", "-Bold", "_Bold", "Bold", "b"), (False, True): ("i", "-Italic", "-Oblique", "Italic", "I"),
            (True, True): ("bi", "z", "-BoldItalic", "-BoldOblique", "BoldItalic")}[(bool(bold), bool(italic))]
    files = sketchtext.font_files()
    lower = {k.lower(): v for k, v in files.items()}
    for suffix in want:
        for e in (ext, ".ttf", ".otf"):
            cand = (base + suffix + e).lower()
            if cand in lower:
                return lower[cand]
            p = os.path.join(d, base + suffix + e)
            if os.path.isfile(p):
                return p
    return font


def _chain(sketch, ids):
    """The picked curves as edges end to end, in order, run so the text reads left to right
    (its up side is then the left of the run: outside a top arc), or None."""
    import Part
    edges = [sketch.Geometry[i].toShape() for i in ids]
    groups = Part.sortEdges(edges)
    if len(groups) != 1:
        return None
    wire = Part.Wire(groups[0])
    out = wire.OrderedEdges if hasattr(wire, "OrderedEdges") else wire.Edges
    first, _ = _at(out, 0.0)
    last, _ = _at(out, sum(e.Length for e in out))
    if last.x < first.x - 1e-9:
        wire = Part.Wire([e.reversed() for e in reversed(out)])
        out = wire.OrderedEdges if hasattr(wire, "OrderedEdges") else wire.Edges
    return out


def _at(edges, s):
    """(point, unit tangent) at arc length s along the chain (clamped)."""
    total = sum(e.Length for e in edges)
    s = max(0.0, min(total, s))
    for e in edges:
        if s <= e.Length + 1e-12 or e is edges[-1]:
            back = e.Orientation == "Reversed"
            # fix265: a reversed edge runs from its curve's end: its length is measured from there
            # too (the text on a top arc, run left to right, came out mirrored: EDCBA)
            u = e.getParameterByLength(e.Length - min(s, e.Length) if back else min(s, e.Length))
            p = e.valueAt(u)
            t = e.tangentAt(u)
            if back:
                t = t * -1
            return p, t
        s -= e.Length
    e = edges[-1]
    return e.valueAt(e.LastParameter), e.tangentAt(e.LastParameter)


def property_names(doc):
    """The part's properties, as File > Properties lists them (Summary and Custom)."""
    names = ["Label", "CreatedBy", "Company", "Comment", "LastModifiedBy", "CreationDate",
             "LastModifiedDate", "License"]
    try:
        names += [str(k) for k in dict(doc.Meta) if str(k) not in names]
    except Exception as _fw_err:
        _fw_log("sketchtextpm.py:123", _fw_err)
    return names


def property_value(doc, name):
    if doc is None:
        return ""
    try:
        meta = dict(doc.Meta)
        if name in meta:
            return str(meta[name])
    except Exception as _fw_err:
        _fw_log("sketchtextpm.py:135", _fw_err)
    try:
        return str(getattr(doc, name))
    except Exception:
        return ""


def resolve_properties(text, doc):
    ""
    import re
    return re.sub(r'\$PRP:"([^"]*)"', lambda m: property_value(doc, m.group(1)), text)


ASK = {}         # checks: {"property": name} answers the Link to Property box


def text_loops(text, font, height, spacing=0.0, angle=0.0, x=0.0, y=0.0, curve=None, align=LEFT,
               flip_v=False, flip_h=False, width=100.0):
    """The text's outline loops ([[edges], ...]) in sketch coordinates."""
    import Part
    if not text.strip() or not font or height <= 0:
        return []
    chars = Part.makeWireString(text, font, height, spacing)
    sx = max(0.01, width / 100.0)
    # every character: its wires, and its x span along the base line
    items = []
    for ch in chars:
        wires = [w.copy() for w in ch]
        if not wires:
            items.append(([], None))
            continue
        bb = wires[0].BoundBox
        for w in wires[1:]:
            bb.add(w.BoundBox)
        items.append((wires, bb))
    spans = [bb for _, bb in items if bb is not None]
    if not spans:
        return []
    x0 = min(b.XMin for b in spans)
    x1 = max(b.XMax for b in spans)
    total = (x1 - x0) * sx

    def char_matrix(cx, cy):
        """Width factor, flips and the per-character Rotate, about the character's base centre."""
        m = App.Matrix()
        m.move(App.Vector(-cx, -cy, 0))
        s = App.Matrix()
        s.scale(sx * (-1 if flip_h else 1), -1 if flip_v else 1, 1)
        m = s.multiply(m)
        if angle and curve is not None:
            r = App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), angle)).toMatrix()
            m = r.multiply(m)
        return m

    loops = []
    if curve:
        length = sum(e.Length for e in curve)
        gap = 0.0
        if align == CENTER:
            start = (length - total) / 2.0
        elif align == RIGHT:
            start = length - total
        elif align == FIT and len(spans) > 1:
            start = 0.0
            gap = (length - total) / (len(spans) - 1)
        else:
            start = 0.0
        k = 0
        for wires, bb in items:
            if bb is None:
                continue
            cx = (bb.XMin + bb.XMax) / 2.0
            along = start + (cx - x0) * sx + gap * k
            k += 1
            if flip_h:
                along = length - along
            p, t = _at(curve, along)
            if flip_h:
                t = t * -1
            rot = App.Placement(App.Vector(p.x, p.y, 0),
                                App.Rotation(App.Vector(0, 0, 1), math.degrees(math.atan2(t.y, t.x)))).toMatrix()
            m = rot.multiply(char_matrix(cx, 0.0))
            for w in wires:
                w2 = w.copy()
                w2 = w2.transformGeometry(m) if (sx != 1.0 or flip_v or flip_h) else _placed(w2, m)
                loops.append([e for e in w2.Edges if e.Length > 1e-9])
        return loops
    # no curve: a straight base line from (x, y), turned by Rotate, aligned on the start point
    shift = {CENTER: -total / 2.0, RIGHT: -total}.get(align, 0.0)
    pl = App.Placement(App.Vector(x, y, 0), App.Rotation(App.Vector(0, 0, 1), angle)).toMatrix()
    for wires, bb in items:
        if bb is None:
            continue
        cx = (bb.XMin + bb.XMax) / 2.0
        local = App.Matrix()
        local.move(App.Vector(shift + (cx - x0) * sx, 0, 0))
        m = pl.multiply(local).multiply(char_matrix(cx, 0.0))
        for w in wires:
            w2 = w.copy()
            w2 = w2.transformGeometry(m) if (sx != 1.0 or flip_v or flip_h) else _placed(w2, m)
            loops.append([e for e in w2.Edges if e.Length > 1e-9])
    return loops


def _placed(shape, m):
    s = shape.copy()
    s.transformShape(m)
    return s



def _glyph_icon(kind):
    ""
    from PySide import QtGui
    pm = QtGui.QPixmap(20, 20)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    pen = QtGui.QPen(QtGui.QColor(40, 40, 40), 1.6)
    p.setPen(pen)
    rows = {"Left": [(3, 15), (3, 11), (3, 15), (3, 9)], "Center": [(3, 17), (5, 15), (3, 17), (6, 14)],
            "Right": [(5, 17), (9, 17), (5, 17), (11, 17)], "Fit": [(3, 17)] * 4}
    if kind in rows:
        for k, (x0, x1) in enumerate(rows[kind]):
            y = 4 + 4 * k
            p.drawLine(x0, y, x1, y)
    elif kind in ("B", "I"):
        f = QtGui.QFont("Arial", 11)
        f.setBold(kind == "B")
        f.setItalic(kind == "I")
        p.setFont(f)
        p.drawText(pm.rect(), int(QtCore.Qt.AlignCenter), kind)
    elif kind == "Prop":
        f = QtGui.QFont("Arial", 7)
        p.setFont(f)
        p.drawText(pm.rect(), int(QtCore.Qt.AlignCenter), "PRP")
    elif kind == "FlipV":
        f = QtGui.QFont("Arial", 11)
        p.setFont(f)
        p.drawText(QtCore.QRect(0, -1, 20, 11), int(QtCore.Qt.AlignCenter), "A")
        p.translate(0, 21)
        p.scale(1, -1)
        p.setPen(QtGui.QPen(QtGui.QColor(140, 140, 140)))
        p.drawText(QtCore.QRect(0, 0, 20, 11), int(QtCore.Qt.AlignCenter), "A")
    elif kind == "FlipH":
        f = QtGui.QFont("Arial", 11)
        p.setFont(f)
        p.drawText(QtCore.QRect(0, 0, 10, 20), int(QtCore.Qt.AlignCenter), "A")
        p.translate(21, 0)
        p.scale(-1, 1)
        p.setPen(QtGui.QPen(QtGui.QColor(140, 140, 140)))
        p.drawText(QtCore.QRect(0, 0, 10, 20), int(QtCore.Qt.AlignCenter), "A")
    p.end()
    return QtGui.QIcon(pm)


def _toggle(parent, kind, tip, checkable=True, text=None, name=None):
    b = QtWidgets.QToolButton(parent)
    b.setIcon(_glyph_icon(kind))
    b.setIconSize(QtCore.QSize(20, 20))
    b.setCheckable(checkable)
    b.setAutoRaise(True)
    b.setToolTip(tip)
    b.setText(text or tip)       # for find-by-text in checks; the button shows its picture only
    b.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
    b.setObjectName(name or "SWText" + tip.replace(" ", ""))
    return b

class SketchTextPage(sketchtoolpm.ToolPage):
    TITLE = "Sketch Text"
    ICON = "SKETCH_TEXT"
    PIXMAP = "Draft_ShapeString"

    def __init__(self, sketch, block=None, at=None):
        self._block_in = block
        self._at = at
        super().__init__(sketch)

    def build(self):
        b = self._block_in or {}
        self._old_ids = sketchtext.block_ids(self.sketch, self._block_in) if self._block_in else []
        self._original = (len(self.sketch.Geometry), len(self.sketch.Constraints))
        self.curves = []
        self.curve_tags = []
        self.made = []
        self._filling = True
        g = self.group("Curves")
        self.curve_list = QtWidgets.QListWidget(g.body)
        self.curve_list.setObjectName("SWSelectedEntities")
        self.curve_list.setFixedHeight(60)
        self.curve_list.setToolTip("Pick sketch lines, arcs or splines for the text to follow")
        g.content.addWidget(self.curve_list)
        g = self.group("Text")
        self.text = QtWidgets.QLineEdit(b.get("text", ""), g.body)
        g.content.addWidget(self.text)
        row = QtWidgets.QHBoxLayout()
        self.bold = _toggle(g.body, "B", "Bold")
        self.italic = _toggle(g.body, "I", "Italic")
        for w in (self.bold, self.italic):
            row.addWidget(w)
        self.bold.setChecked(bool(b.get("bold")))
        self.italic.setChecked(bool(b.get("italic")))

        self.prop_button = _toggle(g.body, "Prop", "Link to Property", checkable=False,
                                   name="SWTextLinkProperty")
        self.prop_button.setObjectName("SWTextLinkProperty")
        self.prop_button.setToolTip("Link to Property")
        self.prop_button.clicked.connect(self.link_property)
        row.addWidget(self.prop_button)
        row.addStretch(1)
        g.content.addLayout(row)

        # them), then Flip Vertical and Flip Horizontal
        self.align = {}
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(2)
        group = QtWidgets.QButtonGroup(g.body)
        group.setExclusive(True)
        for key, label, tip in ((LEFT, "Left", "Align Left"), (CENTER, "Center", "Align Center"),
                                (RIGHT, "Right", "Align Right"), (FIT, "Fit", "Full Justify")):
            r = _toggle(g.body, label, tip, text=label)
            group.addButton(r)
            row.addWidget(r)
            self.align[key] = r
        self.align.get(b.get("align", LEFT), self.align[LEFT]).setChecked(True)
        self._align_group = group
        self.flip_v = _toggle(g.body, "FlipV", "Flip Vertical")
        self.flip_h = _toggle(g.body, "FlipH", "Flip Horizontal")
        self.flip_v.setChecked(bool(b.get("flip_v")))
        self.flip_h.setChecked(bool(b.get("flip_h")))
        row.addSpacing(6)
        row.addWidget(self.flip_v)
        row.addWidget(self.flip_h)
        row.addStretch(1)
        g.content.addLayout(row)
        form = QtWidgets.QFormLayout()
        self.width = self._num(g, b.get("width", 100.0), "%", 1.0, 1000.0, "Width factor")

        pct = b.get("spacing_pct")
        if pct is None:
            h = float(b.get("height", 5.0)) or 5.0
            pct = 100.0 + 100.0 * float(b.get("spacing", 0.0)) / h
        self.spacing = self._num(g, pct, "%", 0.0, 1000.0, "Spacing")
        self.angle = self._num(g, b.get("angle", 0.0), "°", -360.0, 360.0, "Rotate")
        self.height = self._num(g, b.get("height", 5.0), " mm", 0.01, 1e6, "Height")
        self.font = QtWidgets.QComboBox(g.body)
        self.font.setEditable(True)
        files = sketchtext.font_files()
        for name in sorted(files, key=str.lower):
            self.font.addItem(name, files[name])
        current = b.get("font") or sketchtext.default_font()
        i = self.font.findData(current)
        if i < 0 and current:
            self.font.addItem(os.path.basename(current), current)
            i = self.font.count() - 1
        self.font.setCurrentIndex(max(0, i))
        x, y = self._at or (b.get("x", 0.0), b.get("y", 0.0))
        self.x = self._num(g, x, " mm", -1e6, 1e6, "Start X (no curve)")
        self.y = self._num(g, y, " mm", -1e6, 1e6, "Start Y (no curve)")

        self.doc_font = QtWidgets.QCheckBox("Use document font", g.body)
        self.doc_font.setObjectName("SWTextUseDocumentFont")
        if "font" in b:          # editing a text: as it was made
            self.doc_font.setChecked(bool(b.get("doc_font", False)))
        else:
            self.doc_font.setChecked(paths.params().GetBool("TextUseDocumentFont", True))
        for label, w in (("Width factor:", self.width), ("Spacing:", self.spacing), ("Rotate:", self.angle)):
            form.addRow(label, w)
        form.addRow(self.doc_font)

        # with the font and its height; the text starts where it is clicked (or on its curve),
        # so there are no X/Y boxes on the page (fix58)
        self.font_button = QtWidgets.QPushButton("Font...", g.body)
        self.font_button.setObjectName("SWTextFont")
        self.font_button.clicked.connect(self.choose_font)
        form.addRow(self.font_button)
        g.content.addLayout(form)
        for w in (self.height, self.font, self.x, self.y):
            w.hide()
        # no dead (greyed) button: Font... while Use document font is on turns that off first
        self.doc_font.toggled.connect(lambda on: paths.params().SetBool("TextUseDocumentFont", bool(on)))
        self.doc_font.toggled.connect(self.changed)
        for w in (self.width, self.spacing, self.angle, self.height, self.x, self.y):
            w.valueChanged.connect(self.changed)
        self.text.textChanged.connect(self.changed)
        self.font.currentIndexChanged.connect(self.changed)
        for w in (self.bold, self.italic, self.flip_v, self.flip_h) + tuple(self.align.values()):
            w.toggled.connect(self.changed)
        if b.get("curves") or b.get("curve_ids"):
            for i in sketchtext.indices_of(self.sketch, b.get("curves"), b.get("curve_ids")):
                self._add_curve(i)
        self._filling = False
        self.observer = sketchtoolpm.PickObserver(self)
        Gui.Selection.addObserver(self.observer)
        self.placer = _Placer(self)
        self.placer.install()
        for sub in relationspm.picked_subs(self.sketch):
            self.picked(sub)
        self.changed()

    def link_property(self):
        """Link to Property: one of the part's properties (File > Properties), as $PRP:"name"."""
        names = property_names(self.sketch.Document)
        pick = ASK.pop("property", None)
        if pick is None:
            pick, ok = QtWidgets.QInputDialog.getItem(Gui.getMainWindow(), "Link to Property", "Property name:",
                                                      names, 0, False)
            if not ok:
                return
        self.text.insert('$PRP:"%s"' % pick)

    def choose_font(self):
        ""
        if self.doc_font.isChecked():
            self.doc_font.setChecked(False)     # a font of its own: no longer the document's
        box = QtWidgets.QDialog(self)
        box.setObjectName("SWChooseFont")
        box.setWindowTitle("Choose Font")
        form = QtWidgets.QFormLayout(box)
        font = QtWidgets.QComboBox(box)
        font.setObjectName("SWChooseFontFont")
        for i in range(self.font.count()):
            font.addItem(self.font.itemText(i), self.font.itemData(i))
        font.setCurrentIndex(self.font.currentIndex())
        style = QtWidgets.QComboBox(box)
        style.setObjectName("SWChooseFontStyle")
        style.addItems(["Regular", "Italic", "Bold", "Bold Italic"])
        style.setCurrentIndex((2 if self.bold.isChecked() else 0) + (1 if self.italic.isChecked() else 0))
        height = unitbox.UnitSpinBox(box)
        height.setObjectName("SWChooseFontHeight")
        height.setRange(self.height.minimum(), self.height.maximum())
        height.setDecimals(3)
        height.setSuffix(self.height.suffix())
        height.setValue(self.height.value())
        form.addRow("Font:", font)
        form.addRow("Font style:", style)
        form.addRow("Height:", height)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, box)
        buttons.accepted.connect(box.accept)
        buttons.rejected.connect(box.reject)
        form.addRow(buttons)
        self._font_box = box

        def take():
            self.font.setCurrentIndex(font.currentIndex())
            self.bold.setChecked(style.currentIndex() >= 2)
            self.italic.setChecked(style.currentIndex() % 2 == 1)
            self.height.setValue(height.value())
        box.accepted.connect(take)
        box.open()
        return box

    def _num(self, g, value, suffix, low, high, tip):
        box = unitbox.UnitSpinBox(g.body)
        box.setRange(low, high)
        box.setDecimals(3)
        box.setSuffix(suffix)
        box.setValue(value)
        box.setToolTip(tip)
        box.setKeyboardTracking(False)
        return box

    def _add_curve(self, geo):
        if geo in self.curves or geo in self._old_ids:
            return
        self.curves.append(geo)
        self.curve_tags.append(self.sketch.Geometry[geo].Tag)
        self.curve_list.addItem(relationspm._entity_names(self.sketch.Geometry)[geo])

    def picked(self, sub):
        item = sketchtoolpm.item_of(self.sketch, sub)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("sketchtextpm.py:511", _fw_err)
        if item is None or item.geo < 0 or item.geo >= self._original[0]:
            return
        if item.pos in (1, 2, 3) or self.sketch.Geometry[item.geo].TypeId == "Part::GeomPoint":
            p = self.sketch.getPoint(item.geo, item.pos if item.pos in (1, 2, 3) else 1)
            self._filling = True
            self.x.setValue(p.x)
            self.y.setValue(p.y)
            self._filling = False
        else:
            self._add_curve(item.geo)
        self.changed()

    def selection_changed(self):
        pass

    def font_path(self):
        if getattr(self, "doc_font", None) is not None and self.doc_font.isChecked():
            return document_font() or sketchtext.default_font()
        data = self.font.currentData()
        if data and self.font.currentText() == os.path.basename(data):
            return data
        typed = self.font.currentText()
        return typed if os.path.isfile(typed) else (data or "")

    def values(self):
        align = next(k for k, r in self.align.items() if r.isChecked())
        return dict(text=self.text.text(), font=self.font_path(), height=self.height.value(),
                    spacing=(self.spacing.value() - 100.0) / 100.0 * self.height.value(),
                    spacing_pct=self.spacing.value(), angle=self.angle.value(), x=self.x.value(), y=self.y.value(),
                    align=align, flip_v=self.flip_v.isChecked(), flip_h=self.flip_h.isChecked(),
                    width=self.width.value(), bold=self.bold.isChecked(), italic=self.italic.isChecked(),
                    doc_font=self.doc_font.isChecked())

    def undo_work(self):
        self.made = []
        super().undo_work()
        orig = getattr(self, "_original", None)
        if orig is None:
            return
        sk = self.sketch
        try:
            extra = list(range(orig[0], len(sk.Geometry)))
            if extra:
                sk.delGeometries(extra)
            for i in range(len(sk.Constraints) - 1, orig[1] - 1, -1):
                sk.delConstraint(i)
        except Exception as _fw_err:
            _fw_log("sketchtextpm.py:559", _fw_err)

    def changed(self, *args):
        if self._filling:
            return
        self.undo_work()
        v = self.values()
        if not v["text"].strip() or not v["font"]:
            return
        self.begin()
        import Sketcher
        sk = self.sketch
        try:
            curve = _chain(sk, self.curves) if self.curves else None
            if self.curves and curve is None:
                self.show_note("The curves must be one connected chain.", True)
                return
            font = styled_font(v["font"], v["bold"], v["italic"])
            loops = text_loops(resolve_properties(v["text"], sk.Document), font, v["height"], v["spacing"], v["angle"], v["x"], v["y"], curve,
                               v["align"], v["flip_v"], v["flip_h"], v["width"])
        except Exception as error:
            self.show_note("Could not make the text: %s" % error, True)
            return
        self.show_note("")
        if self._old_ids:
            # editing: the old text goes while this one previews (back on Cancel)
            sk.delGeometries(sorted(self._old_ids))
        first = len(sk.Geometry)
        curves = [sketchtext._sketch_curve(e) for loop in loops for e in loop]
        if curves:
            sk.addGeometry(curves, False)
        self.made = list(range(first, first + len(curves)))
        self._loops = [len(loop) for loop in loops]
        if self.made:
            c0 = len(sk.Constraints)
            sk.addConstraint([Sketcher.Constraint("Block", i) for i in self.made])
            try:
                sk.setVirtualSpace(list(range(c0, len(sk.Constraints))), True)
            except Exception as _fw_err:
                _fw_log("sketchtextpm.py:598", _fw_err)
        sketchtoolpm._refresh(sk)

    def finish(self):
        if not self.made:
            return
        sk = self.sketch
        v = self.values()
        if not v.get("doc_font"):
            paths.params().SetString(sketchtext.FONT_PARAM, v["font"])
        items = [b for b in sketchtext.blocks(sk) if not self._block_in or b["tags"] != self._block_in["tags"]]
        geos = sk.Geometry
        block = dict(v, tags=[geos[i].Tag for i in self.made], ids=sketchtext.geo_ids(sk, self.made),
                     loops=self._loops, curves=list(self.curve_tags),
                     curve_ids=sketchtext.geo_ids(sk, self.curves))
        items.append(block)
        sketchtext._save_blocks(sk, items)

    def reject(self):
        super().reject()
        # the sketch is back as it was, its geometry as new objects: the edited text's record
        # takes the Tags of those objects again
        if self._block_in and self._old_ids:
            sk = self.sketch
            try:
                geos = sk.Geometry
                items = []
                for b in sketchtext.blocks(sk):
                    if b["tags"] == self._block_in["tags"]:
                        old = [i for i in sorted(self._old_ids) if i < len(geos)]
                        b = dict(b, tags=[geos[i].Tag for i in old], ids=sketchtext.geo_ids(sk, old))
                    items.append(b)
                sketchtext._save_blocks(sk, items)
            except Exception as _fw_err:
                _fw_log("sketchtextpm.py:630", _fw_err)

    def place_at(self, p):
        ""
        if p is None:
            return
        self.x.setValue(p[0])
        self.y.setValue(p[1])

    def closing(self):
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("sketchtextpm.py:643", _fw_err)
        self.observer.page = None
        try:
            self.placer.remove()
        except Exception as _fw_err:
            _fw_log("sketchtextpm.py:648", _fw_err)


class _Placer(QtCore.QObject):
    """Left clicks on empty space of the view while the page is open place the text's start."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.widgets = []

    def install(self):
        shell = sketchtoolpm._shell()
        view = shell.view_widget() if shell is not None else None
        if view is None:
            return
        self.widgets = [view] + ([view.viewport()] if hasattr(view, "viewport") and view.viewport() else [])
        for w in self.widgets:
            w.installEventFilter(self)

    def remove(self):
        for w in self.widgets:
            try:
                if sketchtoolpm.alive(w):
                    w.removeEventFilter(self)
            except Exception as _fw_err:
                _fw_log("sketchtextpm.py:674", _fw_err)
        self.widgets = []
        self.page = None

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter544(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter sketchtextpm.py: %s\n" % exc)
            return False

    def _fw_filter544(self, obj, event):
        page = self.page
        if page is None or not sketchtoolpm.alive(page):
            return False
        if event.type() != QtCore.QEvent.MouseButtonRelease or event.button() != QtCore.Qt.LeftButton:
            return False
        try:
            if Gui.Selection.getPreselection().ObjectName:
                return False        # on an entity: the pick goes to the page as before
        except Exception as _fw_err:
            _fw_log("sketchtextpm.py:698", _fw_err)
        if page.curves:
            return False
        try:
            from .fwsketch.toolbase import ViewMath
            vm = ViewMath()
            vm.setup_view(Gui.ActiveDocument, page.sketch)
            p, _px = vm.pointer()
        except Exception:
            return False
        QtCore.QTimer.singleShot(0, lambda: page.place_at(p) if sketchtoolpm.alive(page) else None)
        return False


def open_page(sketch, block=None, at=None):
    page = SketchTextPage(sketch, block, at)
    sketchtoolpm.open_page(page)
    return page
