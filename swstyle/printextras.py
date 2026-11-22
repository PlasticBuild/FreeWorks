""






import datetime
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import paths

Qt = QtCore.Qt
PAGE = "PageSetup"

LINE_WEIGHTS = (("Thin", 0.18), ("Normal", 0.25), ("Thick", 0.35), ("Thick(2)", 0.5), ("Thick(3)", 0.7),
                ("Thick(4)", 1.0), ("Thick(5)", 1.4), ("Thick(6)", 2.0))
CODES = (("&[Page]", "Page number"), ("&[Pages]", "Total pages"), ("&[Date]", "Date"), ("&[Time]", "Time"),
         ("&[File]", "File name"), ("&[Path]", "File path"), ("&[Sheet]", "Sheet name"), ("&[Scale]", "Scale"))


def _g():
    return paths.params().GetGroup(PAGE)


def header_footer():
    g = _g()
    return {k: g.GetString(k, "") for k in ("HeaderLeft", "HeaderCenter", "HeaderRight",
                                            "FooterLeft", "FooterCenter", "FooterRight")}


def set_header_footer(values):
    g = _g()
    for k, v in values.items():
        g.SetString(k, v)


def header_font_pt():
    return _g().GetFloat("HeaderFont", 9.0)


def line_weights():
    g = _g()
    return [(name, g.GetFloat("LineWeight_" + name.replace("(", "").replace(")", ""), default)) for name, default in LINE_WEIGHTS]


def set_line_weight(name, value):
    _g().SetFloat("LineWeight_" + name.replace("(", "").replace(")", ""), float(value))


def selection():
    g = _g()
    return {"mode": g.GetString("SelectionMode", "screen"),
            "x": g.GetFloat("SelectionX", 0.0), "y": g.GetFloat("SelectionY", 0.0),
            "w": g.GetFloat("SelectionW", 100.0), "h": g.GetFloat("SelectionH", 100.0),
            "scale": g.GetInt("SelectionScale", 100)}


def set_selection(values):
    g = _g()
    g.SetString("SelectionMode", values.get("mode", "screen"))
    for k in ("x", "y", "w", "h"):
        if k in values:
            g.SetFloat("Selection" + k.upper(), float(values[k]))
    if "scale" in values:
        g.SetInt("SelectionScale", int(values["scale"]))


def print_background():
    return _g().GetBool("PrintBackground", False)


def set_print_background(on):
    _g().SetBool("PrintBackground", bool(on))


def expand(text, page=1, pages=1, sheet="", scale=""):
    """The header/footer codes filled in."""
    doc = App.ActiveDocument
    now = datetime.datetime.now()
    name = os.path.basename(doc.FileName) if doc is not None and doc.FileName else (doc.Label if doc else "")
    path = doc.FileName if doc is not None else ""
    for code, value in (("&[Page]", str(page)), ("&[Pages]", str(pages)), ("&[Date]", now.strftime("%x")),
                        ("&[Time]", now.strftime("%X")), ("&[File]", name), ("&[Path]", path), ("&[Sheet]", sheet),
                        ("&[Scale]", scale)):
        text = text.replace(code, value)
    return text


def crop(image):
    """The printed selection cut from the view image (Selection...: a part of the screen)."""
    s = selection()
    if s["mode"] != "selection":
        return image
    w, h = image.width(), image.height()
    x0, y0 = int(w * s["x"] / 100.0), int(h * s["y"] / 100.0)
    cw, ch = max(1, int(w * s["w"] / 100.0)), max(1, int(h * s["h"] / 100.0))
    return image.copy(QtCore.QRect(x0, y0, min(cw, w - x0), min(ch, h - y0)))


def compose(sheet, image, x, y, w, h, dpi, fit, page=1, pages=1, sheet_name=""):
    """Draws the view image (fitted, or scaled as Scale... says), the header and the footer on the
    page image sheet; x, y, w, h is the printable area in device pixels."""
    painter = QtGui.QPainter(sheet)
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    image = crop(image)
    k = min(w / float(image.width()), h / float(image.height()))
    if not fit:
        k *= selection()["scale"] / 100.0 if selection()["mode"] == "selection" else 1.0
    iw, ih = max(1, int(image.width() * k)), max(1, int(image.height() * k))
    painter.drawImage(QtCore.QRect(x + (w - iw) // 2, y + (h - ih) // 2, min(iw, w), min(ih, h)),
                      image if iw <= w and ih <= h else image.copy(0, 0, int(w / k), int(h / k)))
    hf = header_footer()
    font = QtGui.QFont("Arial")
    font.setPointSizeF(max(4.0, header_font_pt() * dpi / 72.0))
    painter.setFont(font)
    painter.setPen(QtGui.QColor("black"))
    fm = painter.fontMetrics()
    th = fm.height()
    for row, keys in (("Header", ("HeaderLeft", "HeaderCenter", "HeaderRight")),
                      ("Footer", ("FooterLeft", "FooterCenter", "FooterRight"))):
        top = max(0, y - th - 2) if row == "Header" else min(sheet.height() - th, y + h + 2)
        for key, align in zip(keys, (Qt.AlignLeft, Qt.AlignHCenter, Qt.AlignRight)):
            text = expand(hf[key], page, pages, sheet_name)
            if text:
                painter.drawText(QtCore.QRect(x, top, w, th), int(align | Qt.AlignVCenter), text)
    painter.end()
    return sheet


# --------------------------------------------------------------------------- the boxes
class HeaderFooterDialog(QtWidgets.QDialog):
    ""


    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWStyle_HeaderFooter")
        self.setWindowTitle("Header/Footer")
        values = header_footer()
        lay = QtWidgets.QVBoxLayout(self)
        self.fields = {}
        self.last = None
        for group in ("Header", "Footer"):
            box = QtWidgets.QGroupBox(group, self)
            gl = QtWidgets.QGridLayout(box)
            for col, side in enumerate(("Left", "Center", "Right")):
                gl.addWidget(QtWidgets.QLabel(side + ":", box), 0, col)
                edit = QtWidgets.QLineEdit(values[group + side], box)
                edit.setObjectName("SWStyle_%s%s" % (group, side))
                edit.installEventFilter(self)
                gl.addWidget(edit, 1, col)
                self.fields[group + side] = edit
            lay.addWidget(box)
        codes = QtWidgets.QGroupBox("Insert", self)
        cl = QtWidgets.QHBoxLayout(codes)
        for code, tip in CODES:
            b = QtWidgets.QToolButton(codes)
            b.setObjectName("SWStyle_HF_" + tip.replace(" ", ""))
            b.setText(tip)
            b.setToolTip(code)
            b.clicked.connect(lambda _c=False, c=code: self._insert(c))
            cl.addWidget(b)
        lay.addWidget(codes)
        row = QtWidgets.QHBoxLayout()
        font = QtWidgets.QPushButton("Font...", self)
        font.setObjectName("SWStyle_HeaderFooterFont")
        font.clicked.connect(self._font)
        row.addWidget(font)
        self.font_label = QtWidgets.QLabel("Arial %g pt" % header_font_pt(), self)
        row.addWidget(self.font_label)
        row.addStretch(1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        lay.addLayout(row)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.FocusIn and obj in self.fields.values():
            self.last = obj
        return False

    def _insert(self, code):
        edit = self.last or self.fields["HeaderLeft"]
        edit.insert(code)
        edit.setFocus()

    def _font(self):
        f = QtGui.QFont("Arial")
        f.setPointSizeF(header_font_pt())
        got = QtWidgets.QFontDialog.getFont(f, self)
        ok, font = (got[0], got[1]) if isinstance(got[0], bool) else (got[1], got[0])
        if ok:
            _g().SetFloat("HeaderFont", font.pointSizeF())
            self.font_label.setText("%s %g pt" % (font.family(), font.pointSizeF()))

    def accept(self):
        set_header_footer({k: e.text() for k, e in self.fields.items()})
        super().accept()


class LineWeightsDialog(QtWidgets.QDialog):
    ""

    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWStyle_LineWeights")
        self.setWindowTitle("Line Weights")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Line weights for printing (mm):", self))
        form = QtWidgets.QFormLayout()
        self.spins = {}
        for name, value in line_weights():
            spin = QtWidgets.QDoubleSpinBox(self)
            spin.setObjectName("SWStyle_LineWeight_" + name.replace("(", "").replace(")", ""))
            spin.setRange(0.01, 10.0)
            spin.setDecimals(2)
            spin.setSingleStep(0.05)
            spin.setSuffix(" mm")
            spin.setValue(value)
            form.addRow(name + ":", spin)
            self.spins[name] = spin
        lay.addLayout(form)
        row = QtWidgets.QHBoxLayout()
        reset = QtWidgets.QPushButton("Reset", self)
        reset.setObjectName("SWStyle_LineWeightsReset")
        reset.clicked.connect(self._reset)
        row.addWidget(reset)
        row.addStretch(1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        lay.addLayout(row)

    def _reset(self):
        for name, default in LINE_WEIGHTS:
            self.spins[name].setValue(default)

    def accept(self):
        for name, spin in self.spins.items():
            set_line_weight(name, spin.value())
        super().accept()


class SelectionDialog(QtWidgets.QDialog):
    ""


    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWStyle_PrintSelection")
        self.setWindowTitle("Print Selection")
        s = selection()
        lay = QtWidgets.QVBoxLayout(self)
        self.screen = QtWidgets.QRadioButton("Current screen image", self)
        self.screen.setObjectName("SWStyle_SelectionScreen")
        self.area = QtWidgets.QRadioButton("Selection", self)
        self.area.setObjectName("SWStyle_SelectionArea")
        (self.area if s["mode"] == "selection" else self.screen).setChecked(True)
        lay.addWidget(self.screen)
        lay.addWidget(self.area)
        box = QtWidgets.QGroupBox("Selection (% of the view)", self)
        form = QtWidgets.QFormLayout(box)
        self.spins = {}
        for key, label in (("x", "Left:"), ("y", "Top:"), ("w", "Width:"), ("h", "Height:")):
            spin = QtWidgets.QDoubleSpinBox(box)
            spin.setObjectName("SWStyle_Selection_" + key)
            spin.setRange(0.0, 100.0)
            spin.setSuffix(" %")
            spin.setValue(s[key])
            form.addRow(label, spin)
            self.spins[key] = spin
        self.scale = QtWidgets.QSpinBox(box)
        self.scale.setObjectName("SWStyle_SelectionScale")
        self.scale.setRange(1, 1000)
        self.scale.setSuffix(" %")
        self.scale.setValue(s["scale"])
        form.addRow("Selection scale:", self.scale)
        pick = QtWidgets.QPushButton("Use the view's middle half", box)
        pick.setObjectName("SWStyle_SelectionMiddle")
        pick.clicked.connect(lambda: [self.spins[k].setValue(v) for k, v in (("x", 25.0), ("y", 25.0), ("w", 50.0), ("h", 50.0))])
        form.addRow(pick)
        lay.addWidget(box)
        self.area.toggled.connect(box.setVisible)       # filemenu-1119: shown with Selection, not greyed
        box.setVisible(self.area.isChecked())
        self.area.toggled.connect(lambda _on: self.adjustSize())
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def accept(self):
        values = {k: spin.value() for k, spin in self.spins.items()}
        values["mode"] = "selection" if self.area.isChecked() else "screen"
        values["scale"] = self.scale.value()
        set_selection(values)
        super().accept()


class ScaleDialog(QtWidgets.QDialog):
    ""

    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWStyle_PrintScale")
        self.setWindowTitle("Print Scale")
        g = _g()
        lay = QtWidgets.QVBoxLayout(self)
        self.fit = QtWidgets.QRadioButton("Scale to fit", self)
        self.fit.setObjectName("SWStyle_PrintScaleFit")
        self.scaled = QtWidgets.QRadioButton("Scale:", self)
        self.scaled.setObjectName("SWStyle_PrintScaleScaled")
        self.scale = QtWidgets.QSpinBox(self)
        self.scale.setObjectName("SWStyle_PrintScaleValue")
        self.scale.setRange(1, 1000)
        self.scale.setSuffix(" %")
        self.scale.setValue(g.GetInt("Scale", 100))
        (self.fit if g.GetBool("ScaleToFit", True) else self.scaled).setChecked(True)
        lay.addWidget(self.fit)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.scaled)
        row.addWidget(self.scale)
        row.addStretch(1)
        lay.addLayout(row)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def accept(self):
        g = _g()
        g.SetBool("ScaleToFit", self.fit.isChecked())
        g.SetInt("Scale", self.scale.value())
        super().accept()
