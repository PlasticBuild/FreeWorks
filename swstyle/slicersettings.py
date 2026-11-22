""






import json
import os

from PySide import QtCore, QtGui, QtWidgets


class WheelGuard(QtCore.QObject):
    """The mouse wheel over a field that is not being edited scrolls the page instead of
    changing the field (Ati: scrolling the slicer panel changed settings under the pointer)."""

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.Wheel and not obj.hasFocus():
            w = obj.parentWidget()
            while w is not None and not isinstance(w, QtWidgets.QAbstractScrollArea):
                w = w.parentWidget()
            if w is not None:
                QtCore.QCoreApplication.sendEvent(w.verticalScrollBar(), event)
            return True
        return False


WHEEL_GUARD = WheelGuard()
FIELDS = (QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox, QtWidgets.QAbstractSlider)


def guard_wheel(*roots):
    """Fields under these widgets take the wheel only once clicked into (focused)."""
    for root in roots:
        for kind in FIELDS:
            widgets = root.findChildren(kind) + ([root] if isinstance(root, kind) else [])
            for w in widgets:
                if isinstance(w, QtWidgets.QScrollBar):
                    continue
                w.setFocusPolicy(QtCore.Qt.StrongFocus)
                w.installEventFilter(WHEEL_GUARD)

Qt = QtCore.Qt
HERE = os.path.dirname(os.path.abspath(__file__))
_LAYOUTS = {}

TAB_KIND = {"process": "process", "filament": "filament", "printer": "machine"}
TAB_TITLE = {"process": "Process", "filament": "Filament", "printer": "Printer"}


def layout(key):
    """{"pages": {tab: [page...]}, "options": {key: def}} for "orca" | "bambu" | "prusa". No list ships with the
    add-on: each is built from the user's own copy of that slicer (slicerlayout for Orca Slicer and Bambu Studio,
    from its presets; slicerprusa for PrusaSlicer, from its command line), kept once found."""
    if not _LAYOUTS.get(key, {}).get("options"):
        try:
            if key == "prusa":
                from . import slicerprusa
                _LAYOUTS[key] = slicerprusa.runtime_layout()
            else:
                from . import slicer as backend, slicerlayout
                _LAYOUTS[key] = slicerlayout.runtime_layout(backend.get(key))
        except Exception as error:
            from . import slicer as backend
            backend._fw_log("slicersettings layout", error)
            _LAYOUTS[key] = {"pages": {}, "options": {}}
    return _LAYOUTS[key]


def first(value):
    if isinstance(value, list):
        return value[0] if value else ""
    return value


def text_of(value):
    value = first(value)
    return "" if value is None else str(value)


def same(a, b):
    a, b = text_of(a).strip(), text_of(b).strip()
    if a == b:
        return True
    try:
        return abs(float(a.rstrip("%")) - float(b.rstrip("%"))) < 1e-9 and a.endswith("%") == b.endswith("%")
    except ValueError:
        return False


def count(key, tab):
    return sum(len(g["options"]) for p in layout(key)["pages"].get(tab, []) for g in p["groups"])


def lock_icon(open_):
    """The slicers' lock beside a setting, drawn here: closed and green = the preset's value, open and orange =
    changed (a click puts the preset's value back)."""
    pm = QtGui.QPixmap(18, 18)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    col = QtGui.QColor("#e8862a" if open_ else "#3b9a6b")
    pen = QtGui.QPen(col, 1.8)
    p.setPen(pen)
    p.setBrush(QtCore.Qt.NoBrush)
    if open_:
        p.drawArc(QtCore.QRectF(9.5, 1.5, 6, 7), 0, 180 * 16)        # the shackle, swung open
        p.drawLine(QtCore.QPointF(15.5, 5), QtCore.QPointF(15.5, 7))
    else:
        p.drawArc(QtCore.QRectF(5, 1.5, 8, 9), 0, 180 * 16)
        p.drawLine(QtCore.QPointF(5, 6), QtCore.QPointF(5, 9))
        p.drawLine(QtCore.QPointF(13, 6), QtCore.QPointF(13, 9))
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(col)
    p.drawRoundedRect(QtCore.QRectF(3, 8.5, 12, 8), 1.5, 1.5)
    p.end()
    return QtGui.QIcon(pm)


class Row:
    """One setting: label, editor, unit, lock (reset to the preset's value)."""

    def __init__(self, dialog, key, d, base, value):
        self.dialog, self.key, self.d, self.base = dialog, key, d, base
        t = d.get("type", "coString")
        self.kind = t
        self.label = QtWidgets.QLabel(d.get("label") or key)
        tip = d.get("tooltip", "")
        tip = "<b>%s</b> <span style='color:gray'>(%s)</span><br>%s" % (d.get("full_label") or d.get("label") or key, key, tip)
        self.label.setToolTip(tip)
        if t in ("coBool", "coBools"):
            w = QtWidgets.QCheckBox()
            w.toggled.connect(self.edited)
        elif t in ("coEnum", "coEnums") and d.get("enum_values"):
            w = QtWidgets.QComboBox()
            for v, lab in zip(d["enum_values"], d.get("enum_labels") or d["enum_values"]):
                w.addItem(lab, v)
            w.currentIndexChanged.connect(self.edited)
            if d.get("enum_open"):
                # the choices come from the slicer's presets, which may not use them all: another one can be typed
                w.setEditable(True)
                w.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
                w.lineEdit().textEdited.connect(self.edited)
        elif d.get("multiline") or (t in ("coString", "coStrings") and ("gcode" in key or key.endswith("notes"))):
            w = QtWidgets.QPlainTextEdit()
            w.setFixedHeight(90)
            w.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
            f = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
            w.setFont(f)
            w.textChanged.connect(self.edited)
        else:
            w = QtWidgets.QLineEdit()
            w.setMaximumWidth(220)
            w.textEdited.connect(self.edited)
            if t in ("coInt", "coInts"):
                w.setValidator(QtGui.QRegularExpressionValidator(QtCore.QRegularExpression(r"-?\d*")))
            elif t in ("coFloat", "coFloats"):
                w.setValidator(QtGui.QRegularExpressionValidator(QtCore.QRegularExpression(r"-?\d*[.,]?\d*")))
            elif t in ("coPercent", "coPercents", "coFloatOrPercent", "coFloatsOrPercents"):
                w.setValidator(QtGui.QRegularExpressionValidator(QtCore.QRegularExpression(r"-?\d*[.,]?\d*%?")))
        w.setToolTip(tip)
        self.editor = w
        self.unit = QtWidgets.QLabel(d.get("sidetext", ""))
        self.reset = QtWidgets.QToolButton()
        self.reset.setIconSize(QtCore.QSize(18, 18))
        self.reset.setAutoRaise(True)
        self.reset.clicked.connect(self.revert)
        # a setting the preset leaves out shows the editor's own start (the slicer's default
        # stands); "changed" means changed from what was shown for the preset
        self.set(base)
        self.base = self.value() if text_of(base) == "" else base
        self.set(value)

    # ------------------------------------------------------------------ value
    def set(self, value):
        w = self.editor
        w.blockSignals(True)
        raw = text_of(value)
        if isinstance(w, QtWidgets.QCheckBox):
            w.setChecked(raw in ("1", "true", "True"))
        elif isinstance(w, QtWidgets.QComboBox):
            i = w.findData(raw)
            if i < 0 and raw:
                w.addItem(raw, raw)
                i = w.count() - 1
            w.setCurrentIndex(max(0, i))
        elif isinstance(w, QtWidgets.QPlainTextEdit):
            w.setPlainText(raw.replace("\\n", "\n"))
        else:
            w.setText(raw)
        w.blockSignals(False)
        self.mark()

    def value(self):
        w = self.editor
        if isinstance(w, QtWidgets.QCheckBox):
            return "1" if w.isChecked() else "0"
        if isinstance(w, QtWidgets.QComboBox):
            if w.isEditable():
                i = w.findText(w.currentText())
                return w.itemData(i) if i >= 0 else w.currentText().strip()
            return w.currentData()
        if isinstance(w, QtWidgets.QPlainTextEdit):
            return w.toPlainText()
        if self.kind in ("coFloat", "coFloats", "coPercent", "coPercents", "coFloatOrPercent", "coFloatsOrPercents"):
            return w.text().replace(",", ".")      # a decimal comma typed
        return w.text()

    def changed(self):
        return not same(self.value(), self.base)

    def mark(self):
        on = self.changed()
        for w in (self.label, self.editor):
            f = w.font()
            f.setBold(on)
            w.setFont(f)
        self.reset.setIcon(lock_icon(on))
        self.reset.setToolTip("Changed from the preset: click to put the preset's value back" if on else
                              "The preset's value")

    def edited(self, *_):
        self.mark()
        self.dialog.update_count()

    def revert(self):
        self.set(self.base)
        self.dialog.update_count()

    def matches(self, words):
        hay = " ".join((self.key, self.d.get("label", ""), self.d.get("tooltip", ""))).lower()
        return all(w in hay for w in words)


class SettingsDialog(QtWidgets.QDialog):
    """All settings of one preset tab; result() -> overrides."""

    def __init__(self, slicer_key, tab, preset_name, base, overrides, parent=None, title=None, only=None):
        """only: the setting keys to offer (an object's or a height range's own settings), None = all."""
        super().__init__(parent)
        self.tab = tab
        self.lay = layout(slicer_key)
        self.setWindowTitle(title or "%s Settings: %s" % (TAB_TITLE[tab], preset_name))
        self.setObjectName("SWStyle_SlicerSettings")
        self.setStyleSheet(
            "QListWidget#SWStyle_SlicerPages{background:transparent;border:none;border-bottom:1px solid palette(mid);}"
            "QListWidget#SWStyle_SlicerPages::item{padding:6px 14px;border-bottom:3px solid transparent;}"
            "QListWidget#SWStyle_SlicerPages::item:selected{background:transparent;color:palette(text);"
            "border-bottom:3px solid #2f80ed;font-weight:bold;}"
            "QListWidget#SWStyle_SlicerPages::item:hover{background:palette(midlight);}"
            # a group is a bold heading over a thin line, not a box
            "QGroupBox{border:none;border-top:1px solid palette(mid);margin-top:14px;padding-top:8px;font-weight:bold;}"
            "QGroupBox::title{subcontrol-origin:margin;left:0px;padding:0 4px 0 0;}")
        self.resize(900, 640)
        self.rows = {}
        self.pages = []           # (title, widget, [group boxes with rows])
        outer = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search settings")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter)
        self.advanced = QtWidgets.QCheckBox("Show advanced settings")
        self.advanced.setChecked(QtCore.QSettings("FreeCAD", "SWStyleSlicer").value("advanced", True, type=bool))
        self.advanced.toggled.connect(self.filter)
        self.preset_label = QtWidgets.QLabel("<b>%s</b>" % preset_name)
        top.addWidget(self.preset_label)
        top.addStretch(1)
        top.addWidget(self.search, 1)
        top.addWidget(self.advanced)
        outer.addLayout(top)
        body = QtWidgets.QVBoxLayout()
        # the pages as a row of tabs on top, as the slicers' Process / Filament / Printer tabs lay them out
        self.page_list = QtWidgets.QListWidget()
        self.page_list.setFlow(QtWidgets.QListView.LeftToRight)
        self.page_list.setWrapping(False)
        self.page_list.setFixedHeight(34)
        self.page_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.page_list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.page_list.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.page_list.setSpacing(2)
        self.page_list.setObjectName("SWStyle_SlicerPages")
        self.stack = QtWidgets.QStackedWidget()
        body.addWidget(self.page_list)
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)
        values = dict(base)
        values.update(overrides)
        for page in self.lay["pages"].get(tab, []):
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            inner = QtWidgets.QWidget()
            v = QtWidgets.QVBoxLayout(inner)
            boxes = []
            for group in page["groups"]:
                box = QtWidgets.QGroupBox(group["title"].replace("&", "&&"))
                grid = QtWidgets.QGridLayout(box)
                grid.setColumnStretch(2, 1)          # lock | label | editor ...
                rows = []
                for key in group["options"]:
                    d = self.lay["options"].get(key)
                    if d is None or key in self.rows or (only is not None and key not in only):
                        continue
                    # a setting the preset leaves out has the slicer's default
                    start = base.get(key, d.get("default", ""))
                    row = Row(self, key, d, start, values.get(key, start))
                    r = grid.rowCount()
                    grid.addWidget(row.reset, r, 0)
                    grid.addWidget(row.label, r, 1)
                    if isinstance(row.editor, QtWidgets.QPlainTextEdit):
                        grid.addWidget(row.editor, r, 2, 1, 2)
                    else:
                        hl = QtWidgets.QHBoxLayout()
                        hl.addWidget(row.editor)
                        hl.addWidget(row.unit)
                        hl.addStretch(1)
                        grid.addLayout(hl, r, 2)
                    self.rows[key] = row
                    rows.append(row)
                if rows:
                    v.addWidget(box)
                    boxes.append((box, rows))
            v.addStretch(1)
            scroll.setWidget(inner)
            self.stack.addWidget(scroll)
            self.page_list.addItem(page["title"])
            self.pages.append((page["title"], scroll, boxes))
        guard_wheel(self.stack)
        self.page_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.page_list.setCurrentRow(0)
        bottom = QtWidgets.QHBoxLayout()
        self.count_label = QtWidgets.QLabel()
        self.count_label.setMinimumWidth(130)
        self.reset_all = QtWidgets.QPushButton("Reset All")
        self.reset_all.clicked.connect(self.revert_all)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        bottom.addWidget(self.count_label)
        bottom.addWidget(self.reset_all)
        bottom.addStretch(1)
        bottom.addWidget(buttons)
        outer.addLayout(bottom)
        self.extra = {k: v for k, v in overrides.items() if k not in self.rows}   # set elsewhere (plate type...)
        self.filter()
        self.update_count()

    def filter(self, *_):
        QtCore.QSettings("FreeCAD", "SWStyleSlicer").setValue("advanced", self.advanced.isChecked())
        words = [w for w in self.search.text().lower().split() if w]
        adv = self.advanced.isChecked()
        first_hit = None
        for i, (title, _scroll, boxes) in enumerate(self.pages):
            page_hits = 0
            for box, rows in boxes:
                shown = 0
                for row in rows:
                    ok = (adv or row.d.get("mode", "simple") == "simple" or row.changed()) and \
                        (not words or row.matches(words))
                    for w in (row.label, row.editor, row.unit):
                        w.setVisible(ok)
                    row.reset.setVisible(ok)
                    shown += ok
                box.setVisible(shown > 0)
                page_hits += shown
            item = self.page_list.item(i)
            item.setHidden(page_hits == 0)
            if page_hits and first_hit is None:
                first_hit = i
        cur = self.page_list.currentRow()
        if first_hit is not None and (cur < 0 or self.page_list.item(cur).isHidden()):
            self.page_list.setCurrentRow(first_hit)

    def update_count(self):
        n = sum(1 for r in self.rows.values() if r.changed())
        self.count_label.setText("%d setting%s changed" % (n, "" if n == 1 else "s") if n else "As the preset")
        self.reset_all.setVisible(n > 0)        # nothing changed: nothing to reset, no greyed button

    def revert_all(self):
        for r in self.rows.values():
            r.set(r.base)
        self.update_count()

    def overrides(self):
        out = dict(self.extra)
        for key, r in self.rows.items():
            if r.changed():
                out[key] = r.value()
        return out


class ProcessTabs(QtWidgets.QWidget):
    """The slicers' process settings in the panel itself: the Quality / Strength / Speed / Support /
    Multimaterial / Others tabs, every setting of each, with the Advanced switch (simple settings
    only when it is off, as in the slicers). Pages are built when first shown."""

    def __init__(self, slicer_key, on_change=None, tab="process", parent=None):
        super().__init__(parent)
        self.lay_data = layout(slicer_key)
        self.tab = tab
        self.on_change = on_change
        self.base, self.over = {}, {}
        self.rows = {}
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        top = QtWidgets.QHBoxLayout()
        self.advanced = QtWidgets.QCheckBox("Advanced")
        self.advanced.setToolTip("Show every setting (the slicers' Advanced switch); off: the simple ones")
        self.advanced.setChecked(QtCore.QSettings("FreeCAD", "SWStyleSlicer").value("panel_advanced", False, type=bool))
        self.advanced.toggled.connect(self._advanced)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter)
        top.addWidget(self.search, 1)
        top.addWidget(self.advanced)
        outer.addLayout(top)
        self.bar = QtWidgets.QTabBar()
        self.bar.setExpanding(False)
        self.bar.setUsesScrollButtons(True)
        self.bar.setDrawBase(True)
        self.stack = QtWidgets.QStackedWidget()
        self.pages = []           # [page spec, widget or None, [(box, rows)]]
        for page in self.lay_data["pages"].get(tab, []):
            self.bar.addTab(page["title"].replace("&", "&&"))       # "Layers & surfaces": no mnemonic
            holder = QtWidgets.QWidget()
            QtWidgets.QVBoxLayout(holder).setContentsMargins(0, 0, 0, 0)
            self.stack.addWidget(holder)
            self.pages.append([page, holder, None])
        self.bar.currentChanged.connect(self._page)
        outer.addWidget(self.bar)
        outer.addWidget(self.stack)
        self._page(0)

    # ------------------------------------------------------------------ values
    def set_values(self, base, overrides):
        """A preset (resolved) and the changes on top: pages rebuild when next shown."""
        self.base = dict(base)
        self.over = {k: v for k, v in (overrides or {}).items()}
        self.rows = {}
        for entry in self.pages:
            if entry[2] is not None:
                lay = entry[1].layout()
                while lay.count():
                    item = lay.takeAt(0)
                    if item.widget() is not None:
                        item.widget().deleteLater()
                entry[2] = None
        self._page(self.bar.currentIndex())

    def overrides(self):
        return dict(self.over)

    def row(self, key):
        """The Row of a setting (its page built if need be), or None."""
        if key not in self.rows:
            for i, entry in enumerate(self.pages):
                if entry[2] is None and any(key in g["options"] for g in entry[0]["groups"]):
                    entry[2] = self._build(entry[0], entry[1])
                    guard_wheel(entry[1])
                    break
        return self.rows.get(key)

    def update_count(self):
        """A row was edited (the Row interface)."""
        for key, row in self.rows.items():
            if row.changed():
                self.over[key] = row.value()
            else:
                self.over.pop(key, None)
        if self.on_change:
            self.on_change()

    # ------------------------------------------------------------------ pages
    def _page(self, i):
        if not 0 <= i < len(self.pages):
            return
        entry = self.pages[i]
        if entry[2] is None:
            entry[2] = self._build(entry[0], entry[1])
            guard_wheel(entry[1])
        self.stack.setCurrentIndex(i)
        self.filter()

    def _build(self, page, holder):
        boxes = []
        values = dict(self.base)
        values.update(self.over)
        lay = holder.layout()
        for group in page["groups"]:
            box = QtWidgets.QGroupBox(group["title"].replace("&", "&&"))
            box.setObjectName("SWSlicerTabGroup")
            grid = QtWidgets.QGridLayout(box)
            grid.setContentsMargins(6, 6, 2, 4)
            grid.setHorizontalSpacing(6)
            grid.setVerticalSpacing(3)
            grid.setColumnStretch(1, 1)
            rows = []
            for key in group["options"]:
                d = self.lay_data["options"].get(key)
                if d is None or key in self.rows or d.get("mode") == "develop":
                    continue
                start = self.base.get(key, d.get("default", ""))
                row = Row(self, key, d, start, values.get(key, start))
                row.label.setWordWrap(True)
                r = grid.rowCount()
                if isinstance(row.editor, QtWidgets.QPlainTextEdit):
                    grid.addWidget(row.reset, r, 0)
                    grid.addWidget(row.label, r, 1, 1, 2)
                    grid.addWidget(row.editor, r + 1, 0, 1, 3)
                else:
                    if isinstance(row.editor, QtWidgets.QLineEdit):
                        row.editor.setMaximumWidth(90)
                    elif isinstance(row.editor, QtWidgets.QComboBox):
                        row.editor.setMaximumWidth(150)
                        row.editor.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
                        row.editor.setMinimumContentsLength(8)
                    hl = QtWidgets.QHBoxLayout()
                    hl.setSpacing(3)
                    hl.addWidget(row.editor)
                    hl.addWidget(row.unit)
                    grid.addWidget(row.reset, r, 0)
                    grid.addWidget(row.label, r, 1)
                    grid.addLayout(hl, r, 2)
                self.rows[key] = row
                rows.append(row)
            if rows:
                lay.addWidget(box)
                boxes.append((box, rows))
        lay.addStretch(1)
        return boxes

    def _advanced(self, on):
        QtCore.QSettings("FreeCAD", "SWStyleSlicer").setValue("panel_advanced", bool(on))
        self.filter()

    def filter(self, *_):
        words = [w for w in self.search.text().lower().split() if w]
        adv = self.advanced.isChecked()
        if words:
            # searching looks through every page, as the slicers' search does
            for i, entry in enumerate(self.pages):
                if entry[2] is None:
                    entry[2] = self._build(entry[0], entry[1])
                    guard_wheel(entry[1])
        for i, entry in enumerate(self.pages):
            hits = 0
            for box, rows in entry[2] or []:
                shown = 0
                for row in rows:
                    ok = (adv or row.d.get("mode", "simple") == "simple" or row.changed()) and \
                        (not words or row.matches(words))
                    for w in (row.label, row.editor, row.unit):
                        w.setVisible(ok)
                    row.reset.setVisible(ok)
                    shown += ok
                box.setVisible(shown > 0)
                hits += shown
            if entry[2] is not None:
                self.bar.setTabEnabled(i, hits > 0 or not words)
        if words:
            cur = self.bar.currentIndex()
            if not self.bar.isTabEnabled(cur):
                for i in range(self.bar.count()):
                    if self.bar.isTabEnabled(i):
                        self.bar.setCurrentIndex(i)
                        break
