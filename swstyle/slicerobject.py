"""An object's own settings and its height range modifiers, as the slicers' object list has them (right-click an
object: Add Settings / Height Range Modifier). They go to the slicer with the plate list (print_params and
height_ranges of its command line's load_assemble_list), so a plate with them is sliced by the slicer's program."""
from PySide import QtCore, QtGui, QtWidgets

import FreeCADGui as Gui

from . import slicersettings

# The settings an object (or a height range of it) can have of its own: the slicers' PrintObjectConfig and
# PrintRegionConfig (Orca Slicer 2.4 source, libslic3r/PrintConfig.hpp)
PER_OBJECT = frozenset((
    "adaptive_layer_height", "align_infill_direction_to_model", "alternate_extra_wall", "bottom_shell_layers",
    "bottom_shell_thickness", "bottom_solid_infill_flow_ratio", "bottom_surface_density",
    "bottom_surface_filament_id", "bridge_acceleration", "bridge_angle", "bridge_density", "bridge_flow",
    "bridge_line_width", "bridge_no_support", "bridge_speed", "brim_ears_detection_length", "brim_ears_max_angle",
    "brim_flow_ratio", "brim_object_gap", "brim_type", "brim_use_efc_outline", "brim_width",
    "calib_flowrate_topinfill_special_order", "default_acceleration", "default_jerk", "default_junction_deviation",
    "detect_narrow_internal_solid_infill", "detect_overhang_wall", "detect_thin_wall", "elefant_foot_compensation",
    "elefant_foot_compensation_layers", "elefant_foot_layers_density", "emit_machine_limits_to_gcode",
    "enable_overhang_speed", "enable_support", "enforce_support_layers", "extra_perimeters_on_overhangs",
    "extra_solid_infills", "filament_ironing_flow", "filament_ironing_inset", "filament_ironing_spacing",
    "filament_ironing_speed", "fill_multiline", "filter_out_gap_fill", "first_layer_flow_ratio", "flush_into_infill",
    "flush_into_objects", "flush_into_support", "fuzzy_skin_first_layer", "fuzzy_skin_layers_between_ripple_offset",
    "fuzzy_skin_octaves", "fuzzy_skin_persistence", "fuzzy_skin_point_distance", "fuzzy_skin_ripple_offset",
    "fuzzy_skin_ripples_per_layer", "fuzzy_skin_scale", "fuzzy_skin_thickness", "gap_fill_flow_ratio",
    "gap_infill_speed", "gyroid_optimized", "hole_to_polyhole", "hole_to_polyhole_threshold",
    "hole_to_polyhole_twisted", "independent_support_layer_height", "infill_anchor", "infill_anchor_max",
    "infill_combination", "infill_combination_max_layer_height", "infill_direction", "infill_jerk",
    "infill_lock_depth", "infill_overhang_angle", "infill_shift_step", "infill_wall_overlap",
    "initial_layer_acceleration", "initial_layer_jerk", "initial_layer_min_bead_width", "inner_wall_acceleration",
    "inner_wall_filament_id", "inner_wall_flow_ratio", "inner_wall_jerk", "inner_wall_line_width",
    "inner_wall_speed", "input_shaping_damp_x", "input_shaping_damp_y", "input_shaping_emit", "input_shaping_freq_x",
    "input_shaping_freq_y", "interface_shells", "interlocking_beam", "interlocking_beam_layer_count",
    "interlocking_beam_width", "interlocking_boundary_avoidance", "interlocking_depth", "interlocking_orientation",
    "internal_bridge_angle", "internal_bridge_density", "internal_bridge_flow", "internal_bridge_speed",
    "internal_solid_filament_id", "internal_solid_infill_acceleration", "internal_solid_infill_flow_ratio",
    "internal_solid_infill_line_width", "internal_solid_infill_speed", "ironing_angle", "ironing_angle_fixed",
    "ironing_direction", "ironing_flow", "ironing_inset", "ironing_spacing", "ironing_speed", "is_infill_first",
    "lateral_lattice_angle_1", "lateral_lattice_angle_2", "layer_height", "lightning_overhang_angle",
    "lightning_prune_angle", "lightning_straightening_angle", "line_width", "machine_max_acceleration_e",
    "machine_max_acceleration_extruding", "machine_max_acceleration_retracting", "machine_max_acceleration_travel",
    "machine_max_acceleration_x", "machine_max_acceleration_y", "machine_max_acceleration_z", "machine_max_jerk_e",
    "machine_max_jerk_x", "machine_max_jerk_y", "machine_max_jerk_z", "machine_max_junction_deviation",
    "machine_max_speed_e", "machine_max_speed_x", "machine_max_speed_y", "machine_max_speed_z",
    "machine_min_extruding_rate", "machine_min_travel_rate", "make_overhang_printable",
    "make_overhang_printable_angle", "make_overhang_printable_hole_size", "max_bridge_length",
    "max_resonance_avoidance_speed", "min_bead_width", "min_feature_size", "min_length_factor",
    "min_resonance_avoidance_speed", "min_width_top_surface", "minimum_sparse_infill_area",
    "mmu_segmented_region_interlocking_depth", "mmu_segmented_region_max_width", "only_one_wall_first_layer",
    "only_one_wall_top", "outer_wall_acceleration", "outer_wall_filament_id", "outer_wall_flow_ratio",
    "outer_wall_jerk", "outer_wall_line_width", "outer_wall_speed", "overhang_1_4_speed", "overhang_2_4_speed",
    "overhang_3_4_speed", "overhang_4_4_speed", "overhang_flow_ratio", "overhang_reverse",
    "overhang_reverse_internal_only", "overhang_reverse_threshold", "precise_outer_wall", "precise_z_height",
    "print_extruder_id", "print_extruder_variant", "print_flow_ratio", "raft_contact_distance", "raft_expansion",
    "raft_first_layer_density", "raft_first_layer_expansion", "raft_layers", "relative_bridge_angle",
    "resonance_avoidance", "role_based_wipe_speed", "scarf_angle_threshold", "scarf_joint_flow_ratio",
    "scarf_joint_speed", "scarf_overhang_threshold", "seam_gap", "seam_slope_conditional", "seam_slope_entire_loop",
    "seam_slope_inner_walls", "seam_slope_min_length", "seam_slope_start_height", "seam_slope_steps",
    "set_other_flow_ratios", "skeleton_infill_density", "skeleton_infill_line_width", "skin_infill_density",
    "skin_infill_depth", "skin_infill_line_width", "skirt_start_angle", "slice_closing_radius",
    "slowdown_for_curled_perimeters", "small_area_infill_flow_compensation", "small_perimeter_speed",
    "small_perimeter_threshold", "solid_infill_direction", "solid_infill_rotate_template",
    "sparse_infill_acceleration", "sparse_infill_density", "sparse_infill_filament_id", "sparse_infill_flow_ratio",
    "sparse_infill_line_width", "sparse_infill_rotate_template", "sparse_infill_speed", "staggered_inner_seams",
    "support_angle", "support_base_pattern_spacing", "support_bottom_interface_spacing", "support_bottom_z_distance",
    "support_critical_regions_only", "support_expansion", "support_filament", "support_flow_ratio",
    "support_interface_bottom_layers", "support_interface_filament", "support_interface_flow_ratio",
    "support_interface_loop_pattern", "support_interface_not_for_body", "support_interface_spacing",
    "support_interface_speed", "support_interface_top_layers", "support_ironing", "support_ironing_flow",
    "support_ironing_spacing", "support_line_width", "support_object_first_layer_gap", "support_object_xy_distance",
    "support_on_build_plate_only", "support_remove_small_overhang", "support_speed", "support_threshold_angle",
    "support_threshold_overlap", "support_top_z_distance", "symmetric_infill_y_axis", "thick_bridges",
    "thick_internal_bridges", "top_bottom_infill_wall_overlap", "top_shell_layers", "top_shell_thickness",
    "top_solid_infill_flow_ratio", "top_surface_acceleration", "top_surface_density", "top_surface_filament_id",
    "top_surface_jerk", "top_surface_line_width", "top_surface_speed", "travel_acceleration", "travel_jerk",
    "tree_support_angle_slow", "tree_support_auto_brim", "tree_support_branch_angle",
    "tree_support_branch_angle_organic", "tree_support_branch_diameter", "tree_support_branch_diameter_angle",
    "tree_support_branch_diameter_organic", "tree_support_branch_distance", "tree_support_branch_distance_organic",
    "tree_support_brim_width", "tree_support_tip_diameter", "tree_support_top_rate", "tree_support_wall_count",
    "wall_distribution_count", "wall_loops", "wall_maximum_deviation", "wall_maximum_resolution",
    "wall_transition_angle", "wall_transition_filter_deviation", "wall_transition_length",
    "wipe_before_external_loop", "wipe_on_loops", "wipe_speed", "xy_contour_compensation", "xy_hole_compensation",
    "zaa_dont_alternate_fill_direction", "zaa_enabled", "zaa_min_z", "zaa_minimize_perimeter_height",
))


def effective_process(panel):
    """The plate's process settings: the preset with the panel's changes."""
    base = dict(panel.slicer.resolve(slicersettings.TAB_KIND["process"], panel.choice["process"]))
    base.update(panel.choice.get("overrides") or {})
    return base


def edit_settings(panel, item, parent=None):
    """An object's own settings (the slicers' object Add Settings). True when changed."""
    dlg = slicersettings.SettingsDialog(panel.key, "process", item.name, effective_process(panel), dict(item.settings),
                                        parent or Gui.getMainWindow(), title="Object Settings: %s" % item.name,
                                        only=PER_OBJECT)
    dlg.setObjectName("SWStyle_SlicerObjectSettings")
    panel._object_dialog = dlg
    try:
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return False
        item.settings = {k: str(v) for k, v in dlg.overrides().items() if k in PER_OBJECT}
        return True
    finally:
        panel._object_dialog = None


def summary(item):
    """What the object list shows after an object's name: its own settings and height ranges."""
    parts = []
    if item.settings:
        parts.append("%d setting%s" % (len(item.settings), "" if len(item.settings) == 1 else "s"))
    if item.ranges:
        parts.append("%d height range%s" % (len(item.ranges), "" if len(item.ranges) == 1 else "s"))
    if getattr(item, "parts", None):
        parts.append("%d parts" % len(item.parts))
    return ("   [" + ", ".join(parts) + "]") if parts else ""


class RangesDialog(QtWidgets.QDialog):
    """Height Range Modifier: from / to (mm above the plate), the layer height in that range, and any other setting
    of the range (Settings...)."""

    def __init__(self, panel, item, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.panel, self.item = panel, item
        self.setObjectName("SWStyle_SlicerHeightRanges")
        self.setWindowTitle("Height Range Modifier: %s" % item.name)
        self.resize(560, 320)
        lay = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel("Settings that apply only between two heights of this object, as the slicers' "
                                "Height Range Modifier (for example finer layers for a detail).")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["From (mm)", "To (mm)", "Layer height (mm)", "Other settings"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)
        row = QtWidgets.QHBoxLayout()
        self.add_button = QtWidgets.QPushButton("Add Range")
        self.add_button.clicked.connect(lambda: self.add())
        self.remove_button = QtWidgets.QPushButton("Remove Range")
        self.remove_button.clicked.connect(self.remove)
        row.addWidget(self.add_button)
        row.addWidget(self.remove_button)
        row.addStretch(1)
        lay.addLayout(row)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.params = []          # per row: the range's settings (without the layer height)
        for r in item.ranges:
            p = dict(r.get("params") or {})
            lh = p.pop("layer_height", "")
            self.add(r.get("min_z", 0.0), r.get("max_z", 0.0), lh, p)

    def _spin(self, value, hi=10000.0, decimals=2, step=0.5):
        b = QtWidgets.QDoubleSpinBox()
        b.setRange(0.0, hi)
        b.setDecimals(decimals)
        b.setSingleStep(step)
        b.setValue(float(value or 0.0))
        return b

    def add(self, lo=None, hi=None, layer="", params=None):
        n = self.table.rowCount()
        if lo is None:
            last = self.table.cellWidget(n - 1, 1).value() if n else 0.0
            lo, hi = last, last + 2.0
        self.table.insertRow(n)
        self.table.setCellWidget(n, 0, self._spin(lo))
        self.table.setCellWidget(n, 1, self._spin(hi))
        lh = self._spin(layer or 0.0, hi=2.0, decimals=3, step=0.02)
        lh.setSpecialValueText("as the object")
        self.table.setCellWidget(n, 2, lh)
        b = QtWidgets.QPushButton()
        b.clicked.connect(lambda _=False, w=b: self.edit_params(self._row_of(w)))
        self.table.setCellWidget(n, 3, b)
        self.params.append(dict(params or {}))
        self._label(n)
        return n

    def _row_of(self, widget):
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 3) is widget:
                return r
        return -1

    def _label(self, r):
        n = len(self.params[r])
        self.table.cellWidget(r, 3).setText("Settings... (%d)" % n if n else "Settings...")

    def edit_params(self, r):
        if r < 0:
            return
        dlg = slicersettings.SettingsDialog(self.panel.key, "process", self.item.name,
                                            effective_process(self.panel), dict(self.params[r]), self,
                                            title="Height Range Settings: %s" % self.item.name,
                                            only=PER_OBJECT - {"layer_height"})
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.params[r] = {k: str(v) for k, v in dlg.overrides().items() if k in PER_OBJECT}
            self._label(r)

    def remove(self):
        r = self.table.currentRow()
        if r < 0:
            r = self.table.rowCount() - 1
        if r >= 0:
            self.table.removeRow(r)
            self.params.pop(r)

    def ranges(self):
        out = []
        for r in range(self.table.rowCount()):
            lo, hi = self.table.cellWidget(r, 0).value(), self.table.cellWidget(r, 1).value()
            if hi <= lo:
                continue
            p = dict(self.params[r])
            lh = self.table.cellWidget(r, 2).value()
            if lh > 0:
                p["layer_height"] = "%g" % lh
            out.append({"min_z": lo, "max_z": hi, "params": p})
        return out


def edit_ranges(panel, item):
    dlg = RangesDialog(panel, item)
    panel._object_dialog = dlg
    try:
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return False
        item.ranges = dlg.ranges()
        return True
    finally:
        panel._object_dialog = None


def install(panel):
    """The object list's right-click menu: Add Settings, Height Range Modifier, and clearing them."""
    lst = panel.part_list
    lst.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

    def menu(pos):
        row = lst.indexAt(pos).row()
        items = panel.bed.items
        if row < 0 or row >= len(items):
            return
        item = items[row]
        m = QtWidgets.QMenu(lst)
        m.setObjectName("SWStyle_SlicerObjectMenu")
        a = m.addAction("Object Settings...")
        a.triggered.connect(lambda: panel._object_changed(edit_settings(panel, item)))
        b = m.addAction("Height Range Modifier...")
        b.triggered.connect(lambda: panel._object_changed(edit_ranges(panel, item)))
        if item.settings or item.ranges:
            m.addSeparator()
            c = m.addAction("Remove Object Settings and Ranges")
            c.triggered.connect(lambda: panel._object_changed(_clear(item)))
        if item.parts:
            parts_menu(panel, item, m)
        panel._object_menu = m
        m.popup(lst.viewport().mapToGlobal(pos))
    lst.customContextMenuRequested.connect(menu)
    # the slicers' object list shows an object's own settings under it: here, a table under the list
    table = SettingsTable(panel)
    lay = lst.parentWidget().layout() if lst.parentWidget() is not None else None
    if lay is not None:
        lay.insertWidget(lay.indexOf(lst) + 1, table)
    panel.settings_table = table
    lst.itemSelectionChanged.connect(table.sync)
    changed = panel._object_changed

    def object_changed(c, _changed=changed):
        _changed(c)
        table.sync()
    panel._object_changed = object_changed


class SettingsTable(QtWidgets.QTreeWidget):
    """The settings of the selected object, as the slicers' object list shows them under it: the object's own
    settings, its modifier parts' and its height ranges', by category. A value is edited in place (double-click);
    the cross takes a setting off; Add... opens the settings to add more."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.setObjectName("SWStyle_SlicerSettingsTable")
        self.setColumnCount(3)
        self.setHeaderLabels(["Setting", "Value", ""])
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        self.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked | QtWidgets.QAbstractItemView.EditKeyPressed)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.header().setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)
        self.header().resizeSection(2, 24)
        self.setMaximumHeight(170)
        self._sig = None
        self._filling = False
        self.itemChanged.connect(self._edited)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.sync)       # a pick in the graphics area changes the selection too
        self.timer.start()
        self.hide()

    # ------------------------------------------------------------------ what it shows
    def item(self):
        bed = self.panel.bed
        sel = sorted(bed.selected) if bed.items else []
        return bed.items[sel[0]] if len(sel) == 1 and sel[0] < len(bed.items) else None

    def groups(self, it):
        """[(title, owner kind, index, settings dict)] of the object: its own, its modifiers', its ranges'."""
        out = [("%s (object)" % it.name, "object", None, it.settings)]
        for k, p in enumerate(it.parts or []):
            if p.get("type") == "modifier":
                out.append(("%s (modifier)" % p.get("name"), "part", k, p.setdefault("settings", {})))
        for k, r in enumerate(it.ranges or []):
            out.append(("%.2f - %.2f mm (height range)" % (float(r["min_z"]), float(r["max_z"])), "range", k,
                        r.setdefault("params", {})))
        return out

    def signature(self, it):
        if it is None:
            return None
        return (id(it), repr([(t, sorted(d.items())) for t, _k, _i, d in self.groups(it)]))

    def sync(self):
        try:
            if not self.panel._alive():
                self.timer.stop()
                return
        except Exception:
            return
        it = self.item()
        sig = self.signature(it)
        if sig == self._sig:
            return
        self._sig = sig
        self.fill(it)

    def fill(self, it):
        self._filling = True
        try:
            self.clear()
            groups = self.groups(it) if it is not None else []
            if not any(values or kind != "object" for _t, kind, _i, values in groups):
                self.hide()         # as in the slicers: rows only when the object has something of its own
                return
            try:
                opts = slicersettings.layout(self.panel.key)["options"]
            except Exception:
                opts = {}
            for title, kind, index, values in groups:
                top = QtWidgets.QTreeWidgetItem(self, [title, "", ""])
                top.setFirstColumnSpanned(False)
                f = top.font(0)
                f.setBold(True)
                top.setFont(0, f)
                add = QtWidgets.QToolButton()
                add.setText("+")
                add.setObjectName("SWStyle_SlicerSettingsAdd")
                add.setToolTip("Add settings")
                add.setAutoRaise(True)
                add.clicked.connect(lambda _=False, k=kind, i=index, item=it: self.add(item, k, i))
                self.setItemWidget(top, 2, add)
                cats = {}
                for key in sorted(values, key=lambda k: (opts.get(k, {}).get("category", ""),
                                                         opts.get(k, {}).get("label", k))):
                    d = opts.get(key, {})
                    cat = d.get("category") or "Other"
                    if cat not in cats:
                        cats[cat] = QtWidgets.QTreeWidgetItem(top, [cat, "", ""])
                    row = QtWidgets.QTreeWidgetItem(cats[cat], [d.get("label") or key, str(values[key]), ""])
                    row.setToolTip(0, "%s (%s)" % (d.get("label") or key, key))
                    row.setFlags(row.flags() | QtCore.Qt.ItemIsEditable)
                    row.setData(0, QtCore.Qt.UserRole, (kind, index, key))
                    if d.get("sidetext"):
                        row.setToolTip(1, d["sidetext"])
                    rm = QtWidgets.QToolButton()
                    rm.setText("\u00d7")
                    rm.setObjectName("SWStyle_SlicerSettingsRemove")
                    rm.setToolTip("Take this setting off (back to the preset's value)")
                    rm.setAutoRaise(True)
                    rm.clicked.connect(lambda _=False, item=it, k=kind, i=index, key=key: self.remove(item, k, i, key))
                    self.setItemWidget(row, 2, rm)
            self.expandAll()
            self.setVisible(True)
        finally:
            self._filling = False

    # ------------------------------------------------------------------ edits
    def values_of(self, it, kind, index):
        if kind == "object":
            return it.settings
        if kind == "part":
            return it.parts[index].setdefault("settings", {})
        return it.ranges[index].setdefault("params", {})

    def _edited(self, row, column):
        if self._filling or column != 1:
            return
        data = row.data(0, QtCore.Qt.UserRole)
        it = self.item()
        if not data or it is None:
            return
        kind, index, key = data
        text = row.text(1).strip()
        values = self.values_of(it, kind, index)
        if not text:
            values.pop(key, None)
        else:
            values[key] = text
        self._sig = None
        self.panel._object_changed(True)

    def remove(self, it, kind, index, key):
        self.values_of(it, kind, index).pop(key, None)
        self._sig = None
        self.panel._object_changed(True)

    def add(self, it, kind, index):
        if kind == "object":
            changed = edit_settings(self.panel, it)
        elif kind == "part":
            changed = edit_part_settings(self.panel, it, index)
        else:
            changed = edit_ranges(self.panel, it)
        self._sig = None
        self.panel._object_changed(changed)


def parts_menu(panel, item, m):
    """The parts of an object split to parts: each part's filament (Default = the object's), and Merge parts."""
    m.addSeparator()
    sub = m.addMenu("Parts")
    sub.setObjectName("SWStyle_SlicerPartsMenu")
    colours = list(getattr(panel.slots, "colours", []) or ["#cccccc"])
    sub._keep = []                                   # the part menus and their groups live as long as the menu
    for k, part in enumerate(item.parts):
        modifier = part.get("type") == "modifier"
        pm = QtWidgets.QMenu(part["name"] + ("  (modifier)" if modifier else ""), sub)
        sub.addMenu(pm)
        if modifier:
            # a modifier's own settings: what it changes where it is (the slicers' modifier Add Settings)
            sa = pm.addAction("Settings..." + ("  [%d]" % len(part.get("settings") or {}) if part.get("settings") else ""))
            sa.setObjectName("SWStyle_SlicerModifierSettings")
            sa.triggered.connect(lambda _=False, k=k: panel._object_changed(edit_part_settings(panel, item, k)))
            pm.addSeparator()
        group = (getattr(QtGui, "QActionGroup", None) or QtWidgets.QActionGroup)(pm)   # QtGui in Qt 6
        sub._keep += [pm, group]
        for slot in range(0, len(colours) + 1):
            a = pm.addAction("Default (filament %d)" % item.slot if slot == 0 else "Filament %d" % slot)
            a.setCheckable(True)
            a.setChecked(int(part.get("slot") or 0) == slot)
            group.addAction(a)
            if slot:
                pix = QtGui.QPixmap(12, 12)
                pix.fill(QtGui.QColor(colours[slot - 1]))
                a.setIcon(QtGui.QIcon(pix))
            a.triggered.connect(lambda _=False, k=k, slot=slot: set_part_slot(panel, item, k, slot))
    sub.addSeparator()
    merge = sub.addAction("Merge parts")
    merge.setToolTip("Back to one object printed with its own filament")
    merge.triggered.connect(lambda: panel._object_changed(panel.bed.merge_parts(item)))
    return sub


def edit_part_settings(panel, item, k, parent=None):
    """A modifier part's own settings (the object's settings as the base). True when changed."""
    if not item.parts or not 0 <= k < len(item.parts):
        return False
    part = item.parts[k]
    base = effective_process(panel)
    base.update(item.settings or {})
    dlg = slicersettings.SettingsDialog(panel.key, "process", part["name"], base, dict(part.get("settings") or {}),
                                        parent or Gui.getMainWindow(), title="Modifier Settings: %s" % part["name"],
                                        only=PER_OBJECT)
    dlg.setObjectName("SWStyle_SlicerModifierSettingsDialog")
    panel._object_dialog = dlg
    try:
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return False
        part["settings"] = {key: str(v) for key, v in dlg.overrides().items() if key in PER_OBJECT}
        return True
    finally:
        panel._object_dialog = None


def set_part_slot(panel, item, k, slot):
    """A part's filament (0 = the object's own)."""
    if not item.parts or not 0 <= k < len(item.parts):
        return False
    item.parts[k]["slot"] = int(slot)
    panel.bed._redraw()
    panel._object_changed(True)
    return True


def _clear(item):
    item.settings, item.ranges = {}, []
    return True
