"""Filament slots in the Filament section, as the slicers' filament list: a colour and a preset for each slot, Add
Filament, Sync from AMS (the connected Bambu Lab printer's trays), and which slot the picked objects print with.
Slot 1 is the panel's own Filament box; this widget adds its colour and the slots after it."""
from PySide import QtCore, QtGui, QtWidgets

from . import slicer as backend

Qt = QtCore.Qt
MAX_SLOTS = 16
DEFAULT_COLOURS = ("#26a69a", "#e53935", "#1e88e5", "#fdd835", "#8e24aa", "#fb8c00", "#6d4c41", "#ffffff")


def swatch_icon(colour, size=14):
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtGui.QColor(colour))
    return QtGui.QIcon(pix)


def tray_colour(text):
    """'RRGGBBAA' from a Bambu Lab tray to '#rrggbb' ('' when empty)."""
    text = (text or "").strip()
    return "#" + text[:6].lower() if len(text) >= 6 else ""


def ams_trays(ams):
    """The AMS report of a Bambu Lab printer -> [{"unit", "slot", "type", "colour", "idx", "name"}], loaded trays only."""
    out = []
    if not isinstance(ams, dict):
        return out
    for unit in ams.get("ams") or []:
        if not isinstance(unit, dict):
            continue
        for tray in unit.get("tray") or []:
            if not isinstance(tray, dict) or not (tray.get("tray_type") or tray.get("tray_info_idx")):
                continue
            out.append({"unit": unit.get("id", "0"), "slot": tray.get("id", "0"), "type": tray.get("tray_type") or "",
                        "colour": tray_colour(tray.get("tray_color")), "idx": tray.get("tray_info_idx") or "",
                        "name": tray.get("tray_sub_brands") or tray.get("tray_type") or ""})
    return out


class Slots(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.setObjectName("SWStyle_SlicerSlots")
        self.lay = QtWidgets.QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.rows = []              # [(swatch button, combo or None, widget)] slot 1 first
        self.colours = [DEFAULT_COLOURS[0]]
        row = QtWidgets.QHBoxLayout()
        self.first = self._swatch(0)
        row.addWidget(QtWidgets.QLabel("Color of filament 1"))
        row.addStretch(1)
        row.addWidget(self.first)
        self.lay.addLayout(row)
        self.extra = QtWidgets.QVBoxLayout()
        self.lay.addLayout(self.extra)
        buttons = QtWidgets.QHBoxLayout()
        self.add_button = QtWidgets.QPushButton("Add Filament")
        self.add_button.setToolTip("Another filament slot, as the slicers' + beside the filament list")
        self.add_button.clicked.connect(lambda: self.add())
        self.ams_button = QtWidgets.QPushButton("Sync from AMS")
        self.ams_button.setToolTip("Take the filaments and colors from the AMS of the printer connected in the Device tab")
        self.ams_button.clicked.connect(self.sync_ams)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.ams_button)
        self.lay.addLayout(buttons)
        # the slicers' Flushing volumes button: with two filaments or more
        self.flush_button = QtWidgets.QPushButton("Flushing volumes...")
        self.flush_button.setObjectName("SWStyle_SlicerFlushButton")
        self.flush_button.setToolTip("How much is purged at each change from one filament to another")
        self.flush_button.clicked.connect(self._flush)
        self.lay.addWidget(self.flush_button)
        self.flush_button.hide()
        self.object_row = QtWidgets.QWidget()
        orow = QtWidgets.QHBoxLayout(self.object_row)
        orow.setContentsMargins(0, 0, 0, 0)
        olabel = QtWidgets.QLabel("Picked objects use filament")
        olabel.setWordWrap(True)
        orow.addWidget(olabel, 1)
        self.object_slot = QtWidgets.QSpinBox()
        self.object_slot.setRange(1, 1)
        self.object_slot.valueChanged.connect(self._object_slot)
        orow.addWidget(self.object_slot)
        self.lay.addWidget(self.object_row)
        self.object_row.hide()
        self.note = QtWidgets.QLabel()
        self.note.setWordWrap(True)
        self.note.setMinimumWidth(10)
        self.lay.addWidget(self.note)
        self.note.hide()                # shown with a message only (no empty row in the pane)

    # ------------------------------------------------------------------ the rows
    def _swatch(self, index):
        b = QtWidgets.QToolButton()
        b.setObjectName("SWStyle_SlicerSwatch")
        b.setFixedSize(26, 18)
        b.setToolTip("Color of this filament (click to change)")
        b.clicked.connect(lambda _=False, i=index: self.pick_colour(i))
        self._paint(b, self.colours[index] if index < len(self.colours) else "#cccccc")
        return b

    @staticmethod
    def _paint(button, colour):
        button.setStyleSheet("QToolButton{background:%s;border:1px solid #666;}" % colour)

    def pick_colour(self, index):
        c = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.colours[index]), self, "Filament color")
        if c.isValid():
            self.set_colour(index, c.name())

    def set_colour(self, index, colour):
        if not 0 <= index < self.count():
            return                                  # no such slot (the printer takes fewer filaments)
        while len(self.colours) <= index:
            self.colours.append("#cccccc")
        self.colours[index] = colour
        self._paint(self.first if index == 0 else self.rows[index - 1][0], colour)
        self.changed.emit()

    def count(self):
        return 1 + len(self.rows)

    def limit(self):
        """How many filament slots the printer takes: PrusaSlicer one per extruder of the chosen printer (the slicers
        with an AMS: MAX_SLOTS)."""
        s = getattr(self.panel, "slicer", None)
        if s is None or not hasattr(s, "slot_limit"):
            return MAX_SLOTS
        try:
            return max(1, min(MAX_SLOTS, int(s.slot_limit(self.panel.printer.currentData() or ""))))
        except Exception:
            return 1

    def add(self, preset=None, colour=None, quiet=False):
        if self.count() >= self.limit():
            return False
        index = self.count()
        colour = colour or DEFAULT_COLOURS[index % len(DEFAULT_COLOURS)]
        self.colours.append(colour)
        w = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        label = QtWidgets.QLabel("%d" % (index + 1))
        sw = self._swatch(index)
        combo = QtWidgets.QComboBox()
        combo.setMaxVisibleItems(24)
        combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
        remove = QtWidgets.QToolButton()
        remove.setText("×")
        remove.setToolTip("Remove this filament")
        remove.clicked.connect(lambda _=False, wd=w: self.remove(wd))
        for x in (label, sw, combo):
            row.addWidget(x, 1 if x is combo else 0)
        row.addWidget(remove)
        self.extra.addWidget(w)
        w.show()
        self.rows.append((sw, combo, w, label))
        self.refill(self.panel_presets(), {index: preset} if preset else None)
        self._count_changed()
        if not quiet:
            self.changed.emit()
        return True

    def remove(self, widget):
        for i, (_sw, _c, w, _l) in enumerate(self.rows):
            if w is widget:
                del self.rows[i]
                del self.colours[i + 1]
                break
        widget.hide()
        widget.setParent(None)
        widget.deleteLater()
        for i, (_sw, _c, _w, label) in enumerate(self.rows):
            label.setText("%d" % (i + 2))
        # the picked objects on a removed slot go back to filament 1
        for it in self.panel.bed.items:
            if it.slot > self.count():
                it.slot = 1
            for p in it.parts or []:
                if (p.get("slot") or 0) > self.count():
                    p["slot"] = 0                   # a part on a removed slot goes back to its object's filament
        self._count_changed()
        self.changed.emit()

    def clear(self):
        for _sw, _c, w, _l in list(self.rows):
            w.hide()
            w.setParent(None)
            w.deleteLater()
        self.rows = []
        self.colours = self.colours[:1]
        self._count_changed()

    def _count_changed(self):
        n = self.count()
        self.object_slot.setRange(1, n)
        self.object_row.setVisible(n > 1)
        prusa = getattr(self.panel, "key", "") == "prusa"
        self.flush_button.setVisible(n > 1 and not prusa)       # PrusaSlicer purges by its own wipe tower settings
        self.add_button.setVisible(n < self.limit())    # all slots in use: no Add Filament (never greyed)
        self.sync_selection()

    # ------------------------------------------------------------------ presets
    def panel_presets(self):
        combo = self.panel.filament
        return [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]

    def refill(self, presets=None, wanted=None):
        """Fill every extra combo with the printer's filaments; keep what each had (or the slot's wish)."""
        presets = presets if presets is not None else self.panel_presets()
        for i, (_sw, combo, _w, _l) in enumerate(self.rows, 1):
            keep = (wanted or {}).get(i) or combo.currentData() or self.panel.filament.currentData()
            combo.blockSignals(True)
            combo.clear()
            for text, data in presets:
                combo.addItem(text, data)
            j = combo.findData(keep)
            combo.setCurrentIndex(j if j >= 0 else max(0, combo.findData(self.panel.filament.currentData())))
            combo.blockSignals(False)

    def values(self):
        """[{"preset", "colour"}] for every slot; slot 1's preset is the panel's own."""
        out = [{"preset": self.panel.filament.currentData() or "", "colour": self.colours[0]}]
        for i, (_sw, combo, _w, _l) in enumerate(self.rows, 1):
            out.append({"preset": combo.currentData() or "", "colour": self.colours[i]})
        return out

    def load(self, values):
        """Restore slots 2+ (and all colours) saved earlier."""
        self.clear()
        for i, v in enumerate(values or []):
            if i == 0:
                self.colours[0] = v.get("colour") or self.colours[0]
                self._paint(self.first, self.colours[0])
            else:
                self.add(v.get("preset"), v.get("colour"), quiet=True)

    def _flush(self):
        from . import slicerflush
        return slicerflush.edit(self.panel)

    # ------------------------------------------------------------------ picked objects
    def sync_selection(self):
        items = self.panel.bed.targets() if self.panel.bed.items else []
        slots = {it.slot for it in items}
        self.object_slot.blockSignals(True)
        self.object_slot.setValue(slots.pop() if len(slots) == 1 else 1)
        self.object_slot.blockSignals(False)

    def _object_slot(self, n):
        for it in self.panel.bed.targets():
            it.slot = n
        self.changed.emit()

    def slot_of(self):
        """The slot of each object on the plate, in the plate's order."""
        return [it.slot for it in self.panel.bed.items]

    def used_slots(self):
        return sorted(set(self.slot_of())) or [1]

    # ------------------------------------------------------------------ AMS
    def find_preset(self, tray):
        """The filament preset for an AMS tray: the one with the tray's filament id, else the first of its type."""
        presets = self.panel_presets()
        s = self.panel.slicer
        by_type = None
        for _text, name in presets:
            data = s.resolve("filament", name)
            if tray["idx"] and str(data.get("filament_id") or "") == tray["idx"]:
                return name
            if by_type is None and tray["type"] and str(backend._first(data.get("filament_type") or "")).upper() == tray["type"].upper():
                by_type = name
        return by_type

    def sync_ams(self):
        from . import slicerdevice
        trays = ams_trays(slicerdevice.last_ams())
        if not trays:
            self.note.show()
            self.note.setText("No AMS report yet: connect the Bambu Lab printer in the Device tab first (it shows the "
                              "AMS when it has one).")
            return 0
        self.apply_trays(trays)
        return len(trays)

    def apply_trays(self, trays):
        self.clear()
        for i, tray in enumerate(trays):
            preset = self.find_preset(tray) or self.panel.filament.currentData()
            colour = tray["colour"] or DEFAULT_COLOURS[i % len(DEFAULT_COLOURS)]
            if i == 0:
                j = self.panel.filament.findData(preset)
                if j >= 0:
                    self.panel.filament.setCurrentIndex(j)
                self.set_colour(0, colour)
            else:
                self.add(preset, colour, quiet=True)
        self.note.show()
        self.note.setText("%d filament%s taken from the AMS." % (len(trays), "" if len(trays) == 1 else "s"))
        self.changed.emit()
