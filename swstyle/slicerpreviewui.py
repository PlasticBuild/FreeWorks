"""The slicers' preview furniture over the 3D view: the legend on the left (view choice, one row per line type with
its colour, time and share, click a row to hide that line type) and the vertical layer slider on the right.
Orca Slicer and Bambu Studio show the same two things in their Preview."""
from PySide import QtCore, QtGui, QtWidgets

from . import style

Qt = QtCore.Qt
# the slicers' view list (Orca Slicer: Line Type ... Layer Time (log); Bambu Studio calls Tool "Filament")
VIEWS = (("Line Type", "type"), ("Layer Height", "height"), ("Line Width", "width"), ("Speed", "speed"),
         ("Fan Speed", "fan"), ("Temperature", "temp"), ("Flow", "flow"), ("Layer Time", "time"),
         ("Layer Time (log)", "timelog"), ("Filament", "tool"))
# view -> (what the bar's two ends show: divisor, unit)
UNITS = {"height": (1.0, "mm"), "speed": (60.0, "mm/s"), "fan": (1.0, "%"), "temp": (1.0, "\u00b0C"), "time": (1.0, "s"),
         "width": (1.0, "mm"), "flow": (1.0, "mm\u00b3/s"), "timelog": (1.0, "s")}
DECIMALS = {"height": 2, "time": 2, "width": 3, "flow": 2, "timelog": 1}
# the slicers' Options under the legend
OPTIONS = (("travel", "Travel"), ("retract", "Retractions"), ("seam", "Seams"))


def _time_text(seconds):
    seconds = int(round(seconds))
    if seconds >= 3600:
        return "%dh %02dm" % (seconds // 3600, seconds % 3600 // 60)
    if seconds >= 60:
        return "%dm %02ds" % (seconds // 60, seconds % 60)
    return "%ds" % seconds


def host_widget(main_window):
    """The 3D view widget of the active document window."""
    try:
        mdi = main_window.findChild(QtWidgets.QMdiArea)
        sub = mdi.activeSubWindow() if mdi is not None else None
        return sub.widget() if sub is not None else None
    except Exception:
        return None


class LayerSlider(QtWidgets.QSlider):
    """The slicers' vertical layer slider: two handles, the top layer (value) and the lowest layer shown (lower).
    Drag either handle; the one nearer the click moves."""
    lowerChanged = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(Qt.Vertical, parent)
        self._lower = 1
        self._drag_lower = False
        self.marks = lambda: []        # [(layer, colour)]: color changes, pauses ... at a layer
        self.setFocusPolicy(Qt.StrongFocus)

    def lower(self):
        return self._lower

    def setLower(self, value):
        value = max(self.minimum(), min(int(value), self.value()))
        if value != self._lower:
            self._lower = value
            self.update()
            if not self.signalsBlocked():
                self.lowerChanged.emit(value)

    def _pos_of(self, value):
        opt = QtWidgets.QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(QtWidgets.QStyle.CC_Slider, opt, QtWidgets.QStyle.SC_SliderGroove, self)
        handle = self.style().subControlRect(QtWidgets.QStyle.CC_Slider, opt, QtWidgets.QStyle.SC_SliderHandle, self)
        span = groove.height() - handle.height()
        y = QtWidgets.QStyle.sliderPositionFromValue(self.minimum(), self.maximum(), value, span, True)
        return groove.top() + y + handle.height() // 2, handle

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._lower <= self.minimum() and self.maximum() <= self.minimum():
            return
        y, handle = self._pos_of(self._lower)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        col = self.palette().color(QtGui.QPalette.Highlight)
        hi, _h = self._pos_of(self.value())
        p.setPen(QtGui.QPen(col, 3))
        x = self.width() // 2
        p.drawLine(x, min(y, hi), x, max(y, hi))           # the shown range on the groove
        p.setBrush(col)
        p.setPen(Qt.NoPen)
        p.drawRect(QtCore.QRect(x - 7, y - 3, 14, 6))       # the lower handle
        for layer, colour in self.marks():
            my, _h = self._pos_of(layer)
            p.setBrush(QtGui.QColor(colour))
            p.drawEllipse(QtCore.QPoint(self.width() - 5, my), 4, 4)   # a tick beside the groove, as the slicers mark them
        p.end()

    def mousePressEvent(self, event):
        y = event.position().y() if hasattr(event, "position") else event.y()
        ly, _h = self._pos_of(self._lower)
        uy, _h = self._pos_of(self.value())
        if abs(y - ly) + 0.5 < abs(y - uy) and abs(y - ly) <= 10:
            self._drag_lower = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_lower:
            y = event.position().y() if hasattr(event, "position") else event.y()
            opt = QtWidgets.QStyleOptionSlider()
            self.initStyleOption(opt)
            groove = self.style().subControlRect(QtWidgets.QStyle.CC_Slider, opt, QtWidgets.QStyle.SC_SliderGroove, self)
            handle = self.style().subControlRect(QtWidgets.QStyle.CC_Slider, opt, QtWidgets.QStyle.SC_SliderHandle, self)
            span = max(1, groove.height() - handle.height())
            v = QtWidgets.QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
                                                         int(y - groove.top() - handle.height() // 2), span, True)
            self.setLower(v)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_lower:
            self._drag_lower = False
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PreviewOverlay(QtCore.QObject):
    def __init__(self, panel, host):
        super().__init__(host)
        self.panel, self.host = panel, host
        self.preview = panel.preview
        self.legend = QtWidgets.QFrame(host)
        self.legend.setObjectName("SWSlicerLegend")
        self.box = QtWidgets.QVBoxLayout(self.legend)
        self.box.setContentsMargins(10, 8, 10, 8)
        self.box.setSpacing(3)
        self.view = QtWidgets.QComboBox()
        for text, key in VIEWS:
            self.view.addItem(text, key)
        self.view.currentIndexChanged.connect(self._view_changed)
        self.box.addWidget(self.view)
        self.rows = QtWidgets.QVBoxLayout()
        self.rows.setSpacing(1)
        self.box.addLayout(self.rows)
        self.total = QtWidgets.QLabel()
        self.box.addWidget(self.total)
        self.options_title = QtWidgets.QLabel("<b>Options</b>")
        self.box.addWidget(self.options_title)
        self.option_boxes = {}
        for key, text in OPTIONS:
            c = QtWidgets.QCheckBox(text)
            c.setObjectName("SWSlicerLegendOption")
            c.setChecked(key in self.preview.options_on)
            c.toggled.connect(lambda on, k=key: self.preview.show_option(k, on))
            self.box.addWidget(c)
            self.option_boxes[key] = c
        self.items = {}
        self.slider_frame = QtWidgets.QFrame(host)
        self.slider_frame.setObjectName("SWSlicerLayerBar")
        col = QtWidgets.QVBoxLayout(self.slider_frame)
        col.setContentsMargins(6, 6, 6, 6)
        self.top_label = QtWidgets.QLabel()
        self.top_label.setAlignment(Qt.AlignHCenter)
        self.slider = LayerSlider()
        self.slider.setObjectName("SWSlicerLayerSlider")
        self.slider.setMinimumWidth(34)            # room for the marks beside the groove
        self.slider.valueChanged.connect(self._slider_moved)
        self.slider.lowerChanged.connect(self._lower_moved)
        from . import slicercodes
        self.slider.marks = lambda: slicercodes.marks(self.panel)
        if getattr(self.panel, "key", "") == "prusa":
            # the layer codes go in Orca Slicer's and Bambu Studio's project file; PrusaSlicer gets plain meshes
            self.slider.setToolTip("Top layer shown; drag the lower handle to hide the layers below it")
        else:
            self.slider.setContextMenuPolicy(Qt.CustomContextMenu)
            self.slider.customContextMenuRequested.connect(
                lambda pos: slicercodes.menu(self.panel, self.slider, self.slider.value(), self.slider.mapToGlobal(pos)))
            self.slider.setToolTip("Top layer shown; drag the lower handle to hide the layers below it. Right-click: "
                                   "color change, pause or filament change at the top layer")
        self.bottom_label = QtWidgets.QLabel("1")
        self.bottom_label.setAlignment(Qt.AlignHCenter)
        col.addWidget(self.top_label)
        col.addWidget(self.slider, 1)
        col.addWidget(self.bottom_label)
        # the slicers' horizontal slider: the top layer's moves, one by one, with the tool head
        self.moves_frame = QtWidgets.QFrame(host)
        self.moves_frame.setObjectName("SWSlicerMovesBar")
        row = QtWidgets.QHBoxLayout(self.moves_frame)
        row.setContentsMargins(8, 4, 8, 4)
        self.moves = QtWidgets.QSlider(Qt.Horizontal)
        self.moves.setObjectName("SWSlicerMovesSlider")
        self.moves.setFocusPolicy(Qt.StrongFocus)
        self.moves.setToolTip("The moves of the top layer, one by one (the tool head shows where)")
        self.moves.valueChanged.connect(self._moves_moved)
        self.moves_label = QtWidgets.QLabel()
        self.moves_label.setMinimumWidth(90)
        row.addWidget(self.moves, 1)
        row.addWidget(self.moves_label)
        # the slicers' G-code window: the lines around the tool head's move, that line marked
        self.code_frame = QtWidgets.QFrame(host)
        self.code_frame.setObjectName("SWSlicerGcodeWindow")
        code_col = QtWidgets.QVBoxLayout(self.code_frame)
        code_col.setContentsMargins(8, 4, 8, 4)
        self.code = QtWidgets.QLabel()
        self.code.setObjectName("SWSlicerGcodeLines")
        self.code.setTextFormat(Qt.RichText)
        self.code.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        code_col.addWidget(self.code)
        self.code_frame.hide()
        self.fill()
        host.installEventFilter(self)
        style.signals.theme_changed.connect(self._restyle)
        self._restyle()
        self.legend.show()
        self.slider_frame.show()
        self.moves_frame.show()
        self.place()

    # ------------------------------------------------------------------ content
    def fill(self):
        pv = self.preview
        while self.rows.count():
            item = self.rows.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.items = {}
        mode = self.view.currentData()
        if mode == "tool":
            tools = sorted({int(t) for _m, _f, series in pv._paint for t in series.get("tool", [])})
            for t in tools:
                r, g, b = pv.tool_colour(t)
                row = QtWidgets.QLabel("Filament %d" % (t + 1))
                pix = QtGui.QPixmap(12, 12)
                pix.fill(QtGui.QColor.fromRgbF(r, g, b))
                swatch = QtWidgets.QLabel()
                swatch.setPixmap(pix)
                line = QtWidgets.QWidget()
                lay = QtWidgets.QHBoxLayout(line)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.addWidget(swatch)
                lay.addWidget(row, 1)
                self.rows.addWidget(line)
                line.show()
                self.items["tool%d" % t] = line
            self.total.setText(self._footer())
            return
        if mode != "type":
            lo, hi = pv.ranges.get(mode, (0.0, 0.0))
            div, unit = UNITS[mode]
            bar = QtWidgets.QLabel()
            grad = QtGui.QLinearGradient(0, 0, 150, 0)
            for i in range(0, 11):
                r, g, b = pv.gradient_colour(mode, lo + (hi - lo) * i / 10.0)
                grad.setColorAt(i / 10.0, QtGui.QColor.fromRgbF(r, g, b))
            from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
            pix = _hidpi.canvas(150, 12)
            painter = QtGui.QPainter(pix)
            painter.fillRect(0, 0, 150, 12, QtGui.QBrush(grad))
            painter.end()
            bar.setPixmap(pix)
            if mode == "timelog":
                lo, hi = 10 ** lo, 10 ** hi          # the bar is logarithmic, its ends are plain seconds
            d = DECIMALS.get(mode, 0)
            text = QtWidgets.QLabel("%.*f  to  %.*f %s" % (d, lo / div, d, hi / div, unit))
            for w in (bar, text):
                self.rows.addWidget(w)
                w.show()
            self.total.setText("")
            return
        total = sum(v[0] for v in pv.stats.values()) or 1.0
        scale = self._time_scale(total)
        for name, (seconds, _mm) in sorted(pv.stats.items(), key=lambda kv: -kv[1][0]):
            seconds *= scale
            r, g, b = pv.palette.get(name, (0.8, 0.8, 0.8))
            colour = QtGui.QColor.fromRgbF(r, g, b).name()
            button = QtWidgets.QToolButton()
            button.setObjectName("SWSlicerLegendRow")
            button.setCheckable(True)
            button.setChecked(name in pv.shown_features)
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            button.setText(self._row_text(name, seconds, total * scale))
            button.setProperty("swatch", colour)
            button.setToolTip("Click to show or hide %s" % name)
            button.clicked.connect(lambda on, n=name: self._toggle(n, on))
            self.rows.addWidget(button)
            button.show()
            self.items[name] = button
        self.total.setText(self._footer())
        self._restyle()

    def _result(self):
        r = getattr(self.panel, "result", None) or {}
        return r if r.get("ok") else {}

    def _time_scale(self, own_total):
        """The line types' times are measured here from the moves; they are scaled so they add up to the slicer's
        own model printing time (its estimate knows the printer's accelerations), as the slicers' legends do."""
        r = self._result()
        target = r.get("model_time") or r.get("time") or 0
        return float(target) / own_total if target and own_total > 0 else 1.0

    def _footer(self):
        """The slicer's own estimate, as in its legend: the total time, and the filament used (length and weight);
        measured from the moves only when the slicer gave none."""
        pv, r = self.preview, self._result()
        seconds = r.get("time") or sum(v[0] for v in pv.stats.values())
        text = "Total  %s" % _time_text(seconds)
        if r.get("model_time") and r.get("prepare_time"):
            text = "Prepare  %s\nModel printing  %s\n%s" % (_time_text(r["prepare_time"]), _time_text(r["model_time"]), text)
        mm = r.get("length_mm") or pv.filament_mm
        if mm > 0:
            grams = r.get("weight_g") if r.get("length_mm") else mm * 3.14159265 * 0.875 ** 2 / 1000.0 * 1.24
            text += "\nFilament  %.2f m   %.2f g" % (mm / 1000.0, grams)
        return text

    @staticmethod
    def _row_text(name, seconds, total):
        return "%s    %s   %d%%" % (name, _time_text(seconds), round(100.0 * seconds / total))

    def _toggle(self, name, on):
        self.preview.show_feature(name, on)

    def _view_changed(self, *_):
        self.preview.set_view(self.view.currentData())
        self.fill()
        self.place()
        if self.moves.value() < self.moves.maximum():
            self._moves_moved(self.moves.value())     # the half-drawn top layer takes the new colours

    # ------------------------------------------------------------------ layer slider
    def set_layers(self, count, value):
        self.slider.blockSignals(True)
        self.slider.setRange(1, max(1, count))
        self.slider.setValue(value)
        self.slider.blockSignals(False)
        self.sync(value)

    def sync(self, n):
        if self.slider.value() != n:
            self.slider.blockSignals(True)
            self.slider.setValue(n)
            self.slider.blockSignals(False)
        if self.slider.lower() > n:
            self.slider.blockSignals(True)
            self.slider.setLower(n)
            self.slider.blockSignals(False)
        layers = self.preview.layers
        z = layers[n - 1] if 0 < n <= len(layers) else 0.0
        self.top_label.setText("%d\n%.2f" % (n, z))
        lo = self.slider.lower()
        zl = layers[lo - 1] if 0 < lo <= len(layers) else 0.0
        self.bottom_label.setText("%d\n%.2f" % (lo, zl))
        self._fill_moves()

    def _fill_moves(self):
        total = self.preview.moves_in_top()
        self.moves.blockSignals(True)
        self.moves.setRange(0, max(0, total))
        self.moves.setValue(total)
        self.moves.blockSignals(False)
        self.moves_label.setText("%d / %d" % (total, total))
        self.code_frame.hide()

    def _slider_moved(self, n):
        self.panel.layer_slider.setValue(n)

    def _lower_moved(self, lo):
        self.preview.show_range(lo, self.slider.value())
        self.sync(self.slider.value())

    def _moves_moved(self, k):
        total = self.preview.moves_in_top()
        self.preview.scrub(None if k >= total else k)
        self.moves_label.setText("%d / %d" % (k, total))
        self._fill_code(k, total)

    def _fill_code(self, k, total):
        """The G-code window: shown while the moves slider is short of the layer's end, as in the slicers."""
        line = self.preview.move_line(k) if 0 <= k < total else 0
        rows = self.preview.gcode_lines(line) if line else []
        if not rows:
            self.code_frame.hide()
            return
        import html
        T = style.T
        out = []
        for n, text in rows:
            cell = "%6d  %s" % (n, html.escape(text[:56]))
            if n == line:
                cell = "<span style='background:%s;color:%s'>%s</span>" % (T.hex("accent"), "#ffffff", cell)
            out.append(cell)
        self.code.setText("<pre style='margin:0;font-family:Consolas,monospace'>%s</pre>" % "\n".join(out))
        self.code_frame.adjustSize()
        self.place()
        self.code_frame.show()
        self.code_frame.raise_()

    # ------------------------------------------------------------------ look and place
    def _restyle(self, *_):
        T = style.T
        self.legend.setStyleSheet(
            "#SWSlicerLegend, #SWSlicerLayerBar{background:%(pane)s;border:1px solid %(line)s;}"
            "#SWSlicerLegend{border-left:4px solid %(accent)s;}"
            "#SWSlicerLegend QLabel, #SWSlicerLayerBar QLabel{color:%(text)s;background:transparent;}"
            "#SWSlicerLegendRow{color:%(text)s;background:transparent;border:1px solid transparent;"
            "padding:1px 4px 1px 18px;text-align:left;}"
            "#SWSlicerLegendRow:hover{background:%(hover)s;border-color:%(hover_line)s;}"
            "#SWSlicerLegendRow:!checked{color:%(dim)s;}"
            % {"pane": T.hex("pane"), "line": T.hex("line_mid"), "accent": T.hex("accent"), "text": T.hex("text"),
               "hover": T.hex("hover"), "hover_line": T.hex("hover_line"), "dim": T.hex("line_mid")})
        self.slider_frame.setStyleSheet("#SWSlicerLayerBar{background:%s;border:1px solid %s;}"
                                        "#SWSlicerLayerBar QLabel{color:%s;background:transparent;}"
                                        % (T.hex("pane"), T.hex("line_mid"), T.hex("text")))
        self.moves_frame.setStyleSheet("#SWSlicerMovesBar{background:%s;border:1px solid %s;}"
                                       "#SWSlicerMovesBar QLabel{color:%s;background:transparent;}"
                                       % (T.hex("pane"), T.hex("line_mid"), T.hex("text")))
        self.code_frame.setStyleSheet("#SWSlicerGcodeWindow{background:%s;border:1px solid %s;}"
                                      "#SWSlicerGcodeWindow QLabel{color:%s;background:transparent;}"
                                      % (T.hex("pane"), T.hex("line_mid"), T.hex("text")))
        for name, button in self.items.items():
            r, g, b = self.preview.palette.get(name, (0.8, 0.8, 0.8))
            pix = QtGui.QPixmap(12, 12)
            pix.fill(QtGui.QColor.fromRgbF(r, g, b))
            button.setIcon(QtGui.QIcon(pix))
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

    def eventFilter(self, obj, event):
        if obj is self.host and event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show):
            self.place()
        return False

    def place(self):
        self.legend.layout().activate()
        self.legend.adjustSize()
        self.legend.move(12, 80)
        self.legend.raise_()
        h = max(120, self.host.height() - 240)       # under FreeCAD's confirmation corner, above the info box
        self.slider_frame.setFixedSize(54, h)
        self.slider_frame.move(max(0, self.host.width() - 54 - 12), 78)
        self.slider_frame.raise_()
        w = max(240, min(640, self.host.width() - 2 * 260))
        self.moves_frame.setFixedWidth(w)
        self.moves_frame.adjustSize()
        self.moves_frame.move((self.host.width() - w) // 2, self.host.height() - self.moves_frame.height() - 14)
        self.moves_frame.raise_()
        # the G-code window: bottom left, just above the moves slider's row (clear of it and of the legend's top)
        self.code_frame.move(12, max(0, self.moves_frame.y() - self.code_frame.height() - 8))

    def remove(self):
        try:
            style.signals.theme_changed.disconnect(self._restyle)
        except Exception:
            pass
        self.host.removeEventFilter(self)
        for w in (self.legend, self.slider_frame, self.moves_frame, self.code_frame):
            w.hide()
            w.setParent(None)
            w.deleteLater()
        self.deleteLater()
