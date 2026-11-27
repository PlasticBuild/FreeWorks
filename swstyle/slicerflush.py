"""Flushing volumes, as the slicers' dialog of that name (the button beside the filaments when there are two or
more): how much of the old filament is purged at each change from one filament to another (mm3), as a table of
from / to, and a multiplier. Auto: the slicer works them out from the filament colours when it slices (it does so
whenever the table is left as it is). An edited table goes to the slicer as flush_volumes_matrix and
flush_multiplier, the slicers' own settings."""
import colorsys
import math
import re

from PySide import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt
DEFAULT_MULTIPLIER = 0.3            # the slicer's own default (PrintConfig flush_multiplier)
MAX_VOLUME = 20000                  # the slicer's limit (g_max_flush_volume)


def _rgb(colour):
    c = QtGui.QColor(colour or "#ffffff")
    return c.redF(), c.greenF(), c.blueF()


def _lumi(r, g, b):
    return r * 0.3 + g * 0.59 + b * 0.11


def estimate(src, dst):
    """The flushing volume (mm3) from one colour to another by the slicers' colour formula (their calc_flush_vol_rgb).
    For filaments it knows, the slicer may use its measured data instead: after a slice the table shows its values."""
    if (src or "").lower() == (dst or "").lower():
        return 0
    sr, sg, sb = _rgb(src)
    dr, dg, db = _rgb(dst)
    h1, s1, v1 = colorsys.rgb_to_hsv(sr, sg, sb)
    h2, s2, v2 = colorsys.rgb_to_hsv(dr, dg, db)
    a1, a2 = h1 * 2 * math.pi, h2 * 2 * math.pi
    dx = math.cos(a1) * s1 * v1 - math.cos(a2) * s2 * v2
    dy = math.sin(a1) * s1 * v1 - math.sin(a2) * s2 * v2
    hs = min(1.2, math.hypot(dx, dy))
    lf, lt = _lumi(sr, sg, sb), _lumi(dr, dg, db)
    if lt >= lf:
        lumi = (lt - lf) ** 0.7 * 560.0
    else:
        lumi = (lf - lt) * 80.0
        hs = min(0.67 * v2 + 0.33 * v1, hs)
    hsf = 230.0 * hs
    vol = math.sqrt(hsf * hsf + lumi * lumi - 2 * hsf * lumi * math.cos(math.radians(120.0)))
    return int(min(MAX_VOLUME, max(vol, 60.0)))


def estimate_matrix(colours):
    return [estimate(a, b) for a in colours for b in colours]


def from_gcode(path):
    """(matrix, multiplier) the slicer used, from its G-code's settings block; (None, None) when not there."""
    matrix, mult = None, None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("; flush_volumes_matrix = "):
                    matrix = [float(v) for v in re.split(r"[,\s]+", line.split("=", 1)[1].strip()) if v]
                elif line.startswith("; flush_multiplier = "):
                    try:
                        mult = float(line.split("=", 1)[1].split(",")[0])
                    except ValueError:
                        pass
                if matrix is not None and mult is not None:
                    break
    except OSError:
        pass
    return matrix, mult


def stored(choice, count):
    """The edited table for count filaments, or None (auto)."""
    f = choice.get("flush") or {}
    m = f.get("matrix") or []
    return f if len(m) == count * count and count > 1 else None


def overrides(choice, count):
    """The process overrides to slice with: the panel's own plus the edited flushing volumes (when there are)."""
    over = dict(choice.get("overrides") or {})
    f = stored(choice, count)
    if f is not None:
        over["flush_volumes_matrix"] = ["%g" % v for v in f["matrix"]]
        over["flush_multiplier"] = ["%g" % float(f.get("multiplier", DEFAULT_MULTIPLIER))]
    return over


def auto_values(panel, colours):
    """The table the slicer works out itself: its own from the last slice when the colours are the same, else the
    colour formula."""
    n = len(colours)
    r = getattr(panel, "result", None) or {}
    last = getattr(panel, "_flush_colours", None)
    if r.get("ok") and r.get("gcode") and last == list(colours):
        m, mult = from_gcode(r["gcode"])
        if m and len(m) >= n * n:
            return [int(v) for v in m[:n * n]], (mult if mult is not None else DEFAULT_MULTIPLIER), True
    return estimate_matrix(colours), DEFAULT_MULTIPLIER, False


class FlushDialog(QtWidgets.QDialog):
    def __init__(self, panel, colours, parent=None):
        super().__init__(parent)
        self.setObjectName("SWStyle_SlicerFlushDialog")
        self.setWindowTitle("Flushing volumes for filament change")
        self.panel, self.colours = panel, list(colours)
        n = len(colours)
        self.auto, self.auto_mult, self.from_slice = auto_values(panel, colours)
        have = stored(panel.choice, n)
        values = list(have["matrix"]) if have else list(self.auto)
        mult = float(have.get("multiplier", DEFAULT_MULTIPLIER)) if have else self.auto_mult
        lay = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel("Volume of the old filament purged (mm³) at each change, from the filament of the "
                                "row to the filament of the column. Purged = volume × multiplier.")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.table = QtWidgets.QTableWidget(n, n)
        self.table.setObjectName("SWStyle_SlicerFlushTable")
        for i, c in enumerate(colours):
            for header, setter in ((QtWidgets.QTableWidgetItem("%d" % (i + 1)), self.table.setVerticalHeaderItem),
                                   (QtWidgets.QTableWidgetItem("%d" % (i + 1)), self.table.setHorizontalHeaderItem)):
                pix = QtGui.QPixmap(12, 12)
                pix.fill(QtGui.QColor(c))
                header.setIcon(QtGui.QIcon(pix))
                setter(i, header)
        for i in range(n):
            for j in range(n):
                item = QtWidgets.QTableWidgetItem("%d" % int(values[i * n + j]) if i != j else "0")
                item.setTextAlignment(Qt.AlignCenter)
                if i == j:
                    item.setFlags(Qt.ItemIsEnabled)
                    item.setToolTip("No change, no purge")
                self.table.setItem(i, j, item)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        self.table.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setMinimumSectionSize(56)
        self.table.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustToContents)
        self.table.setToolTip("Rows: from this filament. Columns: to this filament.")
        lay.addWidget(self.table)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Multiplier"))
        self.mult = QtWidgets.QDoubleSpinBox()
        self.mult.setObjectName("SWStyle_SlicerFlushMultiplier")
        self.mult.setRange(0.0, 3.0)
        self.mult.setSingleStep(0.05)
        self.mult.setDecimals(2)
        self.mult.setValue(mult)
        row.addWidget(self.mult)
        row.addStretch(1)
        self.auto_button = QtWidgets.QPushButton("Auto-calculate")
        self.auto_button.setToolTip("Back to the volumes the slicer works out from the filament colors")
        self.auto_button.clicked.connect(self.reset)
        row.addWidget(self.auto_button)
        lay.addLayout(row)
        self.state = QtWidgets.QLabel()
        self.state.setWordWrap(True)
        lay.addWidget(self.state)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.table.itemChanged.connect(lambda *_: self._say())
        self.mult.valueChanged.connect(lambda *_: self._say())
        self._say()

    def values(self):
        n = len(self.colours)
        out = []
        for i in range(n):
            for j in range(n):
                if i == j:
                    out.append(0)
                    continue
                try:
                    v = float(self.table.item(i, j).text())
                except (ValueError, AttributeError):
                    v = self.auto[i * n + j]
                out.append(int(max(0, min(MAX_VOLUME, v))))
        return out

    def is_auto(self):
        return self.values() == [int(v) for v in self.auto] and abs(self.mult.value() - self.auto_mult) < 1e-6

    def _say(self):
        if not self.is_auto():
            self.state.setText("Edited: the slicer uses this table.")
        elif self.from_slice:
            self.state.setText("Auto: the slicer works these out from the colors when it slices (shown: its own from "
                               "the last slice).")
        else:
            self.state.setText("Auto: the slicer works these out from the colors when it slices (shown: an estimate "
                               "from the colors; the slicer's own show after a slice).")

    def reset(self):
        n = len(self.colours)
        self.table.blockSignals(True)
        for i in range(n):
            for j in range(n):
                if i != j:
                    self.table.item(i, j).setText("%d" % int(self.auto[i * n + j]))
        self.table.blockSignals(False)
        self.mult.setValue(self.auto_mult)
        self._say()

    def apply(self):
        """Keep the table in the panel's choice (None = auto)."""
        if self.is_auto():
            self.panel.choice.pop("flush", None)
        else:
            self.panel.choice["flush"] = {"matrix": self.values(), "multiplier": round(self.mult.value(), 4),
                                          "colours": list(self.colours)}
        self.panel._flush_changed()


def edit(panel):
    colours = list(panel.slots.colours)
    if len(colours) < 2:
        return None
    import FreeCADGui as Gui
    d = FlushDialog(panel, colours, Gui.getMainWindow())
    panel._flush_dialog = d
    d.accepted.connect(d.apply)
    d.open()
    return d
