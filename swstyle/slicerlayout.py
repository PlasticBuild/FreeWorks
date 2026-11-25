"""The settings window's list for Orca Slicer and Bambu Studio, built at run time from the presets of the user's own
downloaded copy (resources/profiles: every vendor's process, filament and printer presets). No settings list ships
with the add-on. Each setting's kind (number, percentage, on/off, choice, text) and its choices come from the values
the presets give it; the pages, labels, units and short descriptions are the add-on's own. Kept in the slicer's work
folder until that copy or its presets change."""
import json
import re

LAYOUT_VERSION = 3
TABS = {"process": "process", "filament": "filament", "machine": "printer"}

# preset bookkeeping, not settings
META = {"name", "inherits", "from", "type", "instantiation", "setting_id", "filament_id", "version", "renamed_from",
        "description", "is_custom_defined", "filament_settings_id", "print_settings_id", "printer_settings_id",
        "printer_model", "printer_variant", "default_print_profile", "default_filament_profile",
        "default_materials", "upward_compatible_machine", "base_id", "alias", "compatible_printers",
        "compatible_prints", "compatible_printers_condition", "compatible_prints_condition", "inherits_group",
        "different_settings_to_system", "print_compatible_printers", "user_id", "updated_time", "printer_agent",
        "printer_technology", "filament_vendor_id", "printer_settings_id", "thumbnails_format"}

# the add-on's own pages: (title, pattern on the setting name); the last page of a tab takes the rest
PAGES = {
    "process": (("Quality", r"layer_height|line_width|seam|resolution|precision|elefant|wall_generator|ironing|"
                            r"arc_fitting|xy_.*compensation|bridge_flow|only_one_wall|detect_|reduce_crossing|"
                            r"wall_sequence|is_infill_first|print_flow_ratio|slice_closing|fuzzy"),
                ("Strength", r"wall_loops|shell|top_|bottom_|infill|internal_solid|fill_|minimum_sparse|"
                             r"ensure_vertical|alternate_extra_wall|wall_direction"),
                ("Speed", r"speed|accel|jerk|smooth_|pressure_advance|max_volumetric"),
                ("Support", r"support|raft|tree_|bridge_no_support"),
                ("Multimaterial", r"prime_tower|wipe_tower|flush|ooze|wiping|purge|single_extruder|interlocking|"
                                  r"mmu|enable_prime"),
                ("Others", r"")),
    "filament": (("Filament", r"temperature|temp|flow_ratio|density|diameter|cost|filament_type|soluble|"
                              r"filament_colou?r|shrink|max_volumetric|pressure_advance|adhesiveness"),
                 ("Cooling", r"fan|cool|slow_down|overhang_fan|air_filtration|close_fan|reduce_fan|"
                             r"activate_chamber"),
                 ("Multimaterial", r"ramming|toolchange|cooling_tube|unloading|loading|multitool|"
                                   r"filament_minimal_purge|wipe_tower|nozzle_temperature_range"),
                 ("Advanced", r"gcode|retract|wipe|z_hop|deretraction"),
                 ("Notes", r"notes"),
                 ("Others", r"")),
    "printer": (("Basic information", r"printable|bed|print_height|extruder_clearance|nozzle_type|"
                                      r"auxiliary_fan|chamber|support_air|gcode_flavor|scan_first|"
                                      r"use_relative|silent_mode|thumbnails|best_object_pos|z_offset"),
                ("Machine G-code", r"gcode|template"),
                ("Motion ability", r"machine_max|machine_min|max_layer|min_layer|emit_machine|resonance"),
                ("Extruder", r"nozzle|retract|wipe|z_hop|extruder|deretraction|lift|travel_slope"),
                ("Multimaterial", r"single_extruder|cooling_tube|parking|extra_loading|high_current|"
                                  r"purge_in_prime|enable_filament_ramming|manual_filament"),
                ("Notes", r"notes"),
                ("Others", r"")),
}

WORDS = {"gcode": "G-code", "z": "Z", "xy": "XY", "pa": "PA", "id": "ID", "rpm": "RPM", "ams": "AMS",
         "mmu": "MMU", "pei": "PEI", "abs": "ABS", "pla": "PLA", "petg": "PETG", "tpu": "TPU", "hms": "HMS",
         "pwm": "PWM", "3d": "3D", "2d": "2D", "tpms": "TPMS", "cfs": "CFS", "acc": "acceleration",
         "nozzle_hrc": "nozzle HRC"}

# the settings most people change: shown with the Advanced switch off (the rest only with it on)
SIMPLE = {
    "layer_height", "initial_layer_print_height", "line_width", "seam_position", "wall_loops", "top_shell_layers",
    "bottom_shell_layers", "top_shell_thickness", "bottom_shell_thickness", "sparse_infill_density",
    "sparse_infill_pattern", "top_surface_pattern", "bottom_surface_pattern", "enable_support", "support_type",
    "support_style", "support_threshold_angle", "support_on_build_plate_only", "brim_type", "brim_width",
    "skirt_loops", "enable_prime_tower", "prime_tower_width", "outer_wall_speed", "inner_wall_speed",
    "sparse_infill_speed", "travel_speed", "initial_layer_speed", "default_acceleration", "ironing_type",
    "print_sequence", "spiral_mode", "nozzle_temperature", "nozzle_temperature_initial_layer", "hot_plate_temp",
    "textured_plate_temp", "cool_plate_temp", "eng_plate_temp", "filament_flow_ratio", "filament_max_volumetric_speed",
    "filament_type", "filament_diameter", "filament_density", "filament_cost", "fan_min_speed", "fan_max_speed",
    "close_fan_the_first_x_layers", "slow_down_layer_time", "printable_area", "printable_height", "nozzle_diameter",
    "retraction_length", "retraction_speed", "z_hop", "machine_start_gcode", "machine_end_gcode", "gcode_flavor",
    "filament_notes", "printer_notes", "wall_generator", "infill_wall_overlap", "raft_layers",
}

# the add-on's own short descriptions (most other settings get one from the patterns below)
TEXT = {
    "layer_height": "Height of every layer after the first. Thinner layers look smoother and take longer.",
    "initial_layer_print_height": "Height of the first layer. A thicker first layer sticks to the plate better.",
    "line_width": "Default width of the printed lines.",
    "seam_position": "Where each wall loop starts and ends, which leaves a small visible seam.",
    "wall_loops": "How many walls (perimeters) each layer has.",
    "top_shell_layers": "How many solid layers close the top of the part.",
    "bottom_shell_layers": "How many solid layers close the bottom of the part.",
    "top_shell_thickness": "Least thickness of the top shell; more solid layers are added to reach it.",
    "bottom_shell_thickness": "Least thickness of the bottom shell; more solid layers are added to reach it.",
    "sparse_infill_density": "How much of the inside is filled. 0 % leaves it hollow, 100 % makes it solid.",
    "sparse_infill_pattern": "Pattern of the inside fill.",
    "top_surface_pattern": "Pattern of the top skin.",
    "bottom_surface_pattern": "Pattern of the bottom skin.",
    "enable_support": "Prints supports under overhangs.",
    "support_type": "Normal supports grow straight down; tree supports branch out and touch less of the part.",
    "support_threshold_angle": "Overhangs steeper than this (from vertical) get support.",
    "support_on_build_plate_only": "Supports start only on the plate, never on the part.",
    "brim_type": "Whether and where a brim is printed around the first layer.",
    "brim_width": "How far the brim reaches out from the part.",
    "skirt_loops": "Loops of the skirt printed around the parts to prime the nozzle. 0 prints none.",
    "enable_prime_tower": "Prints a tower beside the parts to clean the nozzle after each filament change.",
    "print_sequence": "Layer by layer prints all parts together; object by object finishes each part first.",
    "spiral_mode": "Prints a single wall in one continuous spiral (vase mode).",
    "ironing_type": "Runs the hot nozzle over top surfaces again to smooth them.",
    "travel_speed": "Speed of moves that print nothing.",
    "default_acceleration": "Acceleration of the print head when nothing more specific is set.",
    "nozzle_temperature": "Nozzle temperature after the first layer.",
    "nozzle_temperature_initial_layer": "Nozzle temperature on the first layer.",
    "filament_flow_ratio": "Scales how much filament is pushed. Lower it if lines are too thick.",
    "filament_max_volumetric_speed": "The most filament the hot end can melt per second; speeds are capped to it.",
    "filament_type": "The kind of material (PLA, PETG, ABS...).",
    "filament_diameter": "Diameter of the filament.",
    "filament_density": "Density of the filament, for the weight estimate.",
    "filament_cost": "Price of one kilogram, for the cost estimate.",
    "fan_min_speed": "Part fan speed on layers that print quickly.",
    "fan_max_speed": "Part fan speed on layers that print slowly.",
    "close_fan_the_first_x_layers": "The part fan stays off for this many first layers.",
    "slow_down_layer_time": "Layers quicker than this are slowed down so they can cool.",
    "printable_area": "Outline of the printable area of the plate.",
    "printable_height": "Tallest part the printer can print.",
    "nozzle_diameter": "Diameter of the nozzle.",
    "retraction_length": "How far the filament is pulled back before a travel move, against stringing.",
    "retraction_speed": "How fast the filament is pulled back.",
    "z_hop": "How far the nozzle lifts for travel moves.",
    "machine_start_gcode": "G-code the printer runs before the print.",
    "machine_end_gcode": "G-code the printer runs after the print.",
    "gcode_flavor": "The G-code dialect of the printer's firmware.",
    "filament_notes": "Your own notes on this filament.",
    "printer_notes": "Your own notes on this printer.",
    "wall_generator": "Classic keeps every line one width; Arachne varies the width to fill thin areas.",
    "raft_layers": "Layers of a raft under the part. 0 prints none.",
    "infill_wall_overlap": "How far the infill reaches into the walls, so they bond.",
}

# (pattern on the setting name, unit, description with {what}): the first match wins
PATTERNS = (
    (r"(.*fan.*speed.*)$", "%", "{What}."),
    (r"^machine_(max|min)_(.*)$", "", "The printer's {first} limit for {what}."),
    (r"(.*)_speed$", "mm/s", "Print speed for {what}."),
    (r"(.*)_acceleration$", "mm/s²", "Acceleration for {what}."),
    (r"(.*)_jerk$", "mm/s", "Jerk (instant speed change) for {what}."),
    (r"(.*)_line_width$", "mm", "Line width for {what}."),
    (r"(.*)_temp(erature)?(_initial_layer)?$", "°C", "Temperature: {what}."),
    (r"(.*)_gcode$", "", "G-code run for {what}."),
    (r"(.*)_fan_speed$", "%", "Fan speed for {what}."),
    (r"(.*)_(height|width|distance|length|spacing|gap|thickness|offset|diameter|clearance|depth)$", "mm",
     "{What}."),
    (r"(.*)_angle$", "°", "{What}."),
    (r"(.*)_(time|layer_time)$", "s", "{What}."),
    (r"(.*)_layers$", "", "Number of {what}."),
    (r"(.*)_flow_ratio$", "", "Flow for {what}, as a share of the normal flow."),
    (r"(.*)_pattern$", "", "Pattern of {what}."),
    (r"(.*)_density$", "%", "How densely {what} is filled."),
    (r"(.*)_loops$", "", "Number of loops of {what}."),
    (r"(.*)_direction$", "°", "Direction of {what}."),
    (r"(.*)_(filament|filament_id)$", "", "Which filament prints {what} (0: the object's own)."),
    (r"(.*)_threshold$", "", "Threshold for {what}."),
    (r"(.*)_(ratio|factor|scale)$", "", "{What}."),
    (r"(.*)_type$", "", "Kind of {what}."),
    (r"(.*)_(mode|style)$", "", "How {what} works."),
    (r"(.*)_(count|number)$", "", "Number of {what}."),
    (r"(.*)_(area|size)$", "mm²", "{What}."),
    (r"(.*)_(margin|overlap|resolution|deviation)$", "mm", "{What}."),
    (r"^(enable|use)_(.*)$", "", "Turns {what} on."),
    (r"^(reduce|avoid|detect|ensure|only)_(.*)$", "", "{What}, when on."),
)


def label_of(key):
    """sparse_infill_density -> "Sparse infill density" (the add-on's own label)."""
    words = [WORDS.get(w, w) for w in str(key).replace("-", "_").split("_") if w]
    if not words:
        return str(key)
    first = words[0] if words[0] != words[0].lower() else words[0][:1].upper() + words[0][1:]
    return " ".join([first] + words[1:])


def _own_text(key):
    """The add-on's own description of a setting: by its name, else by the setting it is a variant of (a filament's
    own retraction, a brass-nozzle temperature...)."""
    from .slicerwords import TEXT as MORE, SUFFIXES
    text = TEXT.get(key) or MORE.get(key)
    if text:
        return text
    for end, note in SUFFIXES:
        if key.endswith(end):
            base = _own_text(key[:-len(end)]) or describe(key[:-len(end)])[1]
            if base:
                return base.rstrip(".") + note + "."
    if key.startswith("filament_"):
        base = TEXT.get(key[9:]) or MORE.get(key[9:])
        if base:
            return base.rstrip(".") + " (this filament's own value, over the printer's)."
    return ""


def describe(key):
    """(unit, short description) of a setting, in the add-on's own words."""
    own = _own_text(key)
    for pattern, unit, text in PATTERNS:
        m = re.match(pattern, key)
        if m:
            g = [x for x in m.groups() if x]
            two = pattern.startswith("^(") or pattern.startswith("^machine")
            name = (g[-1] if two else g[0]) if g else key
            what = label_of(name).lower()
            return unit, own or text.format(what=what, What=label_of(key), first=g[0] if g else "")
    return "", own


_NUM = re.compile(r"^-?\d+(\.\d+)?$")
_PCT = re.compile(r"^-?\d+(\.\d+)?%$")
_POINT = re.compile(r"^-?\d+(\.\d+)?x-?\d+(\.\d+)?$")
_WORD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\- ]{0,30}$")
BOOLISH = re.compile(r"^(enable|use|is|only|reduce|detect|ensure|avoid|wipe_on|gcode_add|support_chamber|"
                     r"no_|disable|allow|auto|thick_|flush_into|wipe_tower_no|precise|spiral_mode|interface_shells|"
                     r"exclude|independent|manual)|_(enabled|enable|only|first|mode|control|flag)$")
NUMBERISH = re.compile(r"(count|loops|layers|number|_num|density|speed|temp|ratio|angle|depth|width|length|size|"
                       r"scale|cost|offset|deviation|filament|_id|orientation|time|height|distance|margin|area|"
                       r"multiline|percent|threshold|factor|overlap|diameter|limit|accel|jerk)")
INTISH = re.compile(r"(loops|layers|count|number|_num$|_id$|filament$|multiline|_lines?$|percent|perimeters|"
                    r"_fan_speed|fan_.*speed|temperature|_temp$|threshold$)")


def kind_of(key, values):
    """The editor kind of a setting from every value the presets give it."""
    plural = any(isinstance(v, list) for v in values)
    items = []
    for v in values:
        items += [str(x) for x in v] if isinstance(v, list) else [str(v)]
    items = [x for x in items if x != ""] or [""]
    distinct = set(items)
    if key.endswith("gcode") or key.endswith("notes") or any("\n" in x for x in items):
        t = "coString"
    elif all(_POINT.match(x) for x in items):
        return "coPoints", None
    elif distinct <= {"0", "1"} and (BOOLISH.search(key) or not NUMBERISH.search(key)):
        t = "coBool"
    elif all(_NUM.match(x) for x in items):
        t = "coInt" if all(re.match(r"^-?\d+$", x) for x in items) and INTISH.search(key) else "coFloat"
    elif all(_NUM.match(x) or _PCT.match(x) for x in items):
        t = "coPercent" if all(_PCT.match(x) for x in items) else "coFloatOrPercent"
    elif len(distinct) >= 2 and all(_WORD.match(x) for x in distinct) and len(distinct) <= 40 \
            and not re.search(r"(name|_id$|colou?r|vendor|model|variant|printer$|filament_type)", key):
        return ("coEnums" if plural else "coEnum"), sorted(distinct)
    else:
        t = "coString"
    return (t + "s") if plural and t != "coString" else ("coStrings" if plural else t), None


# misspelt names a few vendor files carry beside the real setting
SLIPS = {"sparse_infill_patter", "temperture_vitrification", "thic_birdges", "layer_heigth", "percise_outer_wall",
         "nozzle_temperature_intial_layer"}
SETTING = re.compile(r"^[a-z][A-Za-z0-9_]*$")
# the printer's network login and the vendor's own bookkeeping: the Device panel and Add Printer handle the network
HIDDEN = re.compile(r"^(print_?host.*|printhost_.*|bbl_use_printhost|url|family|model|model_id|include|data|total|"
                    r"combinations|desciption|box_id|scan_folder|is_artillery|remaining_times|bed_model|bed_texture|"
                    r"hotend_model|.*_texture_rect.*|bottom_texture_end_name|right_icon_offset_bed|"
                    r"active_feeder_motor_name|physical_extruder_map|thumbnails_internal.*)$")


def build(presets, templates=()):
    """{"pages", "options"} from [(kind, data)] presets (kind: process | filament | machine)."""
    seen = {}
    templates = list(templates)
    for kind, data in templates + list(presets):
        tab = TABS.get(kind)
        if tab is None or not isinstance(data, dict):
            continue
        # a base preset (fdm_process_common...) or a template lists the slicer's settings on purpose
        base = str(data.get("instantiation", "")).lower() == "false" or "common" in str(data.get("name", "")) \
            or any(data is t for _k, t in templates)
        for k, v in data.items():
            if k in META or k.startswith("_"):
                continue
            if not SETTING.match(k) or HIDDEN.match(k) or k in SLIPS:
                continue
            entry = seen.setdefault(k, {"tab": tab, "values": [], "keys": set(), "n": 0, "template": False})
            entry["n"] += 1
            entry["template"] = entry["template"] or base
            mark = json.dumps(v, sort_keys=True)
            if mark not in entry["keys"] and len(entry["keys"]) < 300:
                entry["keys"].add(mark)
                entry["values"].append(v)
    # a name only one or two selectable presets carry, and no base preset, is a slip in those files (layer_heigth...)
    seen = {k: e for k, e in seen.items() if e["n"] >= 3 or e["template"]}
    options = {}
    for k, entry in sorted(seen.items()):
        t, choices = kind_of(k, entry["values"])
        unit, text = describe(k)
        first = entry["values"][0] if entry["values"] else ""
        if isinstance(first, list):
            first = first[0] if first else ""
        d = {"type": t, "label": label_of(k), "tooltip": text, "sidetext": unit if t not in ("coBool", "coBools",
             "coEnum", "coEnums", "coString", "coStrings") else "", "mode": "simple" if k in SIMPLE else "advanced",
             "category": entry["tab"], "default": str(first)}
        if choices:
            d["enum_values"] = choices
            d["enum_labels"] = [label_of(c) for c in choices]
            d["enum_open"] = True       # the presets show some of the choices, not surely all: a name can be typed
        options[k] = d
    pages = {}
    for tab, rules in PAGES.items():
        keys = [k for k, e in seen.items() if e["tab"] == tab]
        taken, out = set(), []
        for i, (title, rule) in enumerate(rules):
            last = i == len(rules) - 1
            mine = sorted(k for k in keys if k not in taken and (last or (rule and re.search(rule, k))))
            taken.update(mine)
            if mine:
                simple = [k for k in mine if k in SIMPLE]
                rest = [k for k in mine if k not in SIMPLE]
                groups = ([{"title": title, "options": simple}] if simple else []) + \
                    ([{"title": "More %s settings" % title.lower() if simple else title, "options": rest}] if rest else [])
                out.append({"title": title, "groups": groups})
        pages[tab] = out
    return {"source": "runtime", "version": LAYOUT_VERSION, "pages": pages, "options": options}


def _templates(resources):
    out = []
    if resources is None:
        return out
    import glob
    import os
    for kind in ("process", "filament", "machine"):
        for path in glob.glob(os.path.join(str(resources), "profiles_template", "*", kind, "*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    out.append((kind, json.load(f)))
            except (OSError, ValueError):
                pass
    return out


def runtime_layout(slicer_obj):
    """The settings list of this Orca Slicer / Bambu Studio copy (cached per copy and its presets), or an empty list
    when there is no copy yet."""
    from . import slicer as backend
    empty = {"pages": {}, "options": {}}
    if slicer_obj is None or slicer_obj.exe() is None:
        return empty
    try:
        slicer_obj.load()
        stamp = json.loads(json.dumps(slicer_obj._signature(slicer_obj._vendor_dirs()), default=str))
    except Exception as error:
        backend._fw_log("slicerlayout presets", error)
        return empty
    cache = slicer_obj.work_dir() / "settings-layout.json"
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("stamp") == stamp and data.get("version") == LAYOUT_VERSION and data.get("options"):
            return data
    except (OSError, ValueError):
        pass
    presets = [(p.kind, p.data) for p in (getattr(slicer_obj, "_scoped", None) or {}).values()]
    if not presets:
        return empty
    data = build(presets, _templates(slicer_obj.resources()))
    data["stamp"] = stamp
    try:
        cache.write_text(json.dumps(data), encoding="utf-8")
    except OSError as error:
        backend._fw_log("slicerlayout cache", error)
    return data
