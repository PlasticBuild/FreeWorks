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
import re

import FreeCAD as App
from PySide import QtCore, QtWidgets

ARROWS = ("Default", "Filled arrow", "Open arrow", "Dot", "Filled triangle", "None")
SHOULDER = 4.0          # mm, a bent leader's horizontal shoulder
_installed = []


def leader_group(panel):
    from . import drawings as D
    settings = panel.shape.parentWidget()
    lay = settings.layout()
    for w, text in ((panel.shape, "Style:"), (panel.fit, "Size:")):
        i = lay.indexOf(w)
        if i >= 0:
            label = QtWidgets.QLabel(text, settings)
            label.setObjectName("SWBalloonLabel" + text[:-1])
            lay.insertWidget(i, label)
    box, blay = D._group("Leader", panel.form)
    box.setObjectName("SWBalloonLeader")
    blay.addWidget(QtWidgets.QLabel("Arrow style:", box))
    panel.arrow = QtWidgets.QComboBox(box)
    panel.arrow.setObjectName("SWBalloonArrow")
    panel.arrow.addItems(ARROWS)
    blay.addWidget(panel.arrow)
    row = QtWidgets.QHBoxLayout()
    panel.leader_display = QtWidgets.QButtonGroup(box)
    for n, name in enumerate(("Straight", "Bent")):
        b = QtWidgets.QToolButton(box)
        b.setText(name)
        b.setToolTip(name + " leader")
        b.setCheckable(True)
        b.setObjectName("SWBalloonLeader" + name)
        b.setChecked(name == "Straight")
        panel.leader_display.addButton(b, n)
        row.addWidget(b)
    row.addStretch(1)
    blay.addLayout(row)
    at = panel.lay.indexOf(settings)
    panel.lay.insertWidget(at + 1 if at >= 0 else panel.lay.count(), box)
    return box


def leader_choice(panel):
    arrow = panel.arrow.currentText() if getattr(panel, "arrow", None) is not None else "Default"
    b = panel.leader_display.checkedButton() if getattr(panel, "leader_display", None) is not None else None
    return arrow, (b.text() == "Bent") if b is not None else False


def leader_arrow(arrow0, arrow, bent):
    """drawannot._arrow for one balloon: its end as picked, and a bent leader's shoulder. In balloon_svg the
    leader runs from the balloon's rim (x1, y1; the balloon's centre is 0, 0) to the tip (x0, y0)."""
    def draw(x0, y0, x1, y1, end="Filled arrow"):
        end = end if arrow == "Default" else arrow
        if not bent:
            return arrow0(x0, y0, x1, y1, end)
        r = math.hypot(x1, y1)
        side = 1.0 if x0 >= 0 else -1.0
        sx, kx = side * r, side * (r + SHOULDER)
        if abs(x0) <= abs(kx):                 # the tip under or over the balloon: no room for a shoulder
            return arrow0(x0, y0, x1, y1, end)
        from . import drawannot as A
        shoulder = '<line x1="%g" y1="0" x2="%g" y2="0" stroke="#000" stroke-width="%g"/>' % (sx, kx, A.STROKE)
        return shoulder + arrow0(x0, y0, kx, 0.0, end)
    return draw


def _font_size(sym):
    m = re.search(r'font-size="([\d.]+)"', sym or "")
    return float(m.group(1)) if m else 3.5


def balloon_text_look(sym, size, family, look=""):
    """The balloon's SVG with its text at size (mm) in family (look: the font's bold / italic attributes)."""
    out = re.sub(r'font-size="[\d.]+"', 'font-size="%g"' % size, sym)
    if family and family != "osifont, Arial" or look:
        out = re.sub(r'font-family="[^"]*"', 'font-family="%s"%s' % (family or "osifont, Arial", look), out)
    return out


def more_properties_panel(page, balloon):
    ""
    from . import drawings as D, drawpmparts as PP

    class BalloonPropertiesPanel(D._Panel):
        TITLE = "Note"
        PIXMAP = "TechDraw_Balloon"

        def build(self):
            self.balloon = balloon
            self.sym0 = balloon.Symbol
            self.rot0 = float(getattr(balloon, "Rotation", 0.0) or 0.0)
            self.say("The balloon's note properties. Change them, then OK.")
            box, lay = D._group("Text Format", self.form)
            grid = QtWidgets.QGridLayout()
            self.angle = QtWidgets.QDoubleSpinBox(box)
            self.angle.setObjectName("SWBalloonNoteAngle")
            self.angle.setRange(-360, 360)
            self.angle.setSuffix("°")
            self.angle.setValue(self.rot0)
            self.font_size = QtWidgets.QDoubleSpinBox(box)
            self.font_size.setObjectName("SWBalloonNoteHeight")
            self.font_size.setRange(0.5, 50)
            self.font_size.setSuffix("mm")
            self.font_size.setValue(_font_size(self.sym0))
            for n, (text, w) in enumerate((("Angle:", self.angle), ("Font height:", self.font_size))):
                grid.addWidget(QtWidgets.QLabel(text, box), n, 0)
                grid.addWidget(w, n, 1)
            lay.addLayout(grid)
            PP.format_group(self, box=box, lay=lay)
            self.lay.addWidget(box)
            PP.layer_group(self)
            for w in (self.angle, self.font_size):
                w.valueChanged.connect(lambda *_: self.retext())

        def retext(self):
            b = self.balloon
            try:
                b.Symbol = balloon_text_look(self.sym0, self.font_size.value(), PP.font_of(self), PP.font_look(self))
                if "Rotation" in b.PropertiesList:
                    b.Rotation = self.angle.value()
                self.doc.recompute()
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: balloon properties: %s\n" % error)

        def finish(self):
            self.retext()
            name = PP.layer_of(self)
            if name != PP.NONE_LAYER:
                PP.apply_layer(self.balloon, name)

    return BalloonPropertiesPanel(page)


def open_more_properties(panel):
    from FreeCADGui import Control
    made = [o for o in getattr(panel, "made", []) if getattr(o, "SWAnnotation", "") == "Balloon"]
    if not made:
        return None
    last, page = made[-1], panel.page
    panel.accept()
    pm = more_properties_panel(page, last)
    Control.showDialog(pm)
    return pm


def more_button(panel):
    b = QtWidgets.QPushButton("More Properties...", panel.form)
    b.setObjectName("SWBalloonMoreProperties")
    b.clicked.connect(lambda *_: QtCore.QTimer.singleShot(0, lambda: open_more_properties(panel)))
    b.hide()                    # shown once a balloon is placed: it edits that balloon (no dead control)
    panel.more = b
    panel.lay.addWidget(b)
    return b


def install():
    if _installed:
        return
    try:
        from . import drawannot as A
    except Exception as error:
        App.Console.PrintLog("FreeCAD: balloon PM not extended: %s\n" % error)
        return
    cls = A.BalloonPanel
    if getattr(cls, "_fw_balloon", False):
        return
    cls._fw_balloon = True
    build0, click0 = cls.build, cls.sheet_click

    def build(self):
        build0(self)
        if type(self) is not A.BalloonPanel and not hasattr(self, "shape"):
            return
        try:
            leader_group(self)
        except Exception as _fw_err:
            _fw_log("drawballoonpm:build", _fw_err)
        self._after.append(lambda s=self: more_button(s))

    def sheet_click(self, p):
        arrow, bent = leader_choice(self)
        if arrow == "Default" and not bent:
            out = click0(self, p)
        else:
            arrow0 = A._arrow
            A._arrow = leader_arrow(arrow0, arrow, bent)
            try:
                out = click0(self, p)
            finally:
                A._arrow = arrow0
        more = getattr(self, "more", None)
        if more is not None and any(getattr(o, "SWAnnotation", "") == "Balloon" for o in self.made):
            more.show()
        return out

    cls.build, cls.sheet_click = build, sheet_click
    _installed.append(True)
