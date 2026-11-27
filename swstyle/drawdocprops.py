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

import json
import math
import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import drawings as D
from . import drawpmparts as P

STANDARDS = ("ANSI", "ISO", "DIN", "JIS", "BSI", "GOST", "GB")
ARROWS = ("Filled arrow", "Open arrow", "Tick", "Dot", "Open circle", "Fork", "Filled triangle", "None")
PRECISIONS = ("None", ".1", ".12", ".123", ".1234", ".12345")
TOLS = ("None", "Basic", "Bilateral", "Symmetric")
UNIT_SYSTEMS = (("MKS (meter, kilogram, second)", "m"), ("CGS (centimeter, gram, second)", "cm"),
                ("MMGS (millimeter, gram, second)", "mm"), ("IPS (inch, pound, second)", "in"))
SHARPS = ("Plus", "Plus with lines", "Star", "Dot", "Hollow dot", "Witness lines")
CLOUD_STYLES = ("Solid", "Dashed", "Phantom")
THICKNESS_NAMES = ("Thin", "Normal", "Thick", "Thick(2)", "Thick(3)", "Thick(4)", "Thick(5)", "Thick(6)")
THICKNESS_MM = {"Thin": 0.18, "Normal": 0.25, "Thick": 0.35, "Thick(2)": 0.5, "Thick(3)": 0.7, "Thick(4)": 1.0,
                "Thick(5)": 1.4, "Thick(6)": 2.0}


# What the overall drafting standard sets on its pages (Drafting Standard combo: the pages under it take these,
# as when another base standard is picked): arrows, the annotation font, datum and view label styles, projection.
_EN = {"dim_arrow": "Filled arrow", "datum_frame": "Square", "datum_leader": "Filled triangle",
       "ann_font": "Century Gothic", "lbl_section": "SECTION", "lbl_detail": "DETAIL", "lbl_aux": "VIEW"}
_ISO = dict(_EN)
STANDARD_PRESETS = {
    "ANSI": _EN,
    "ISO": _ISO,
    "DIN": _ISO,
    "BSI": _ISO,
    "JIS": dict(_ISO, ann_font="MS Gothic"),
    "GOST": dict(_ISO, ann_font="GOST type A", datum_leader="Filled triangle with shoulder"),
    "GB": dict(_ISO, ann_font="FangSong", datum_frame="Round", datum_leader="Filled triangle with shoulder"),
}


def standard_preset(standard):
    return dict(STANDARD_PRESETS.get(str(standard), _EN))


def _th_key(name):
    return "th_" + re.sub(r"[^A-Za-z0-9]", "", name)
BALLOON_LAYOUTS = ("Square", "Circular", "Top", "Bottom", "Left", "Right")
ZERO_QTY = ("0", "-", "Blank")
MISSING = ("Display with strikethrough", "Hide the row")
HOLE_CONTROL = ("A, B, C...", "1, 2, 3...")
ORIGIN_MARKS = ("Per Standard", "None")
BEND_NOTE_STYLES = ("Above Bend Line", "With Leader", "Inline")
# tests answer the file dialogs here: {"std_save_path": str, "std_load_path": str, "style_name": str}
ASK = {}
STD_FILTER = "FreeCAD drafting standards (*.fwstd)"
LIN_FILTER = "FreeCAD line styles (*.fwlin)"

BUILTIN_STYLES = ("Solid", "Dashed", "Phantom", "Chain", "Center", "Stitch")


TRAILING = ("Smart", "Show", "Remove", "Standard")
# rows of this dialog that the code reads by their Document Properties page and text
ROW_KEYS = {("Dimensions", "Leading zeroes"): "dim_lead", ("Dimensions", "Trailing zeroes, dimensions"): "dim_trail",
            ("Dimensions", "Trailing zeroes, tolerances"): "dim_trail_tol",
            ("Dimensions", "Trailing zeroes, properties"): "dim_trail_prop"}


def row(doc, page, text, default, key=None):
    ""

    key = key if key is not None else ROW_KEYS.get((page, text))
    if key is not None:
        v = stored(doc)
        if key in v:
            return v[key]
    try:
        from . import optionspages
        return optionspages.doc_value(doc, page, text, default)
    except Exception as _fw_err:
        _fw_log("drawdocprops.py:114", _fw_err)
        return default


def thickness_mm(name, default=0.18, doc=None):
    ""

    name = str(name)
    if name not in THICKNESS_MM:
        return default
    try:
        doc = doc or App.ActiveDocument
        if doc is not None:
            v = stored(doc)
            if _th_key(name) in v:
                return float(v[_th_key(name)])
    except Exception as _fw_err:
        _fw_log("drawdocprops.py:129", _fw_err)
    return THICKNESS_MM[name]


LINE_STYLES = ("Visible", "Hidden", "Center", "Phantom", "Section", "CuttingPlane", "Chain", "NoLine")
THICK = ("0.18mm", "0.25mm", "0.35mm", "0.5mm", "0.7mm", "1mm", "1.4mm")


EXCLUSIONS = "m;mm;cm;km;um;\u00b5m;nm;s;Hz;Pa;"


def exclusions(doc=None):
    """The words All uppercase leaves as typed (unit symbols)."""
    text = EXCLUSIONS
    if doc is not None:
        try:
            text = prop(doc, "upper_exclude") or ""
        except Exception as _fw_err:
            _fw_log("drawdocprops.py:147", _fw_err)
    return tuple(w for w in str(text).split(";") if w)


def upper_text(text, doc=None):
    ex = exclusions(doc)
    return re.sub(r"[^\s]+", lambda m: m.group(0) if m.group(0) in ex else m.group(0).upper(), text)


REV_SHAPES = ("Circle", "Triangle", "Square", "Hexagon")          # as drawtables' Revision Table PM
REV_CONTROL = ("A, B, C...", "1, 2, 3...")
REV_MULTI = ("See Sheet 1", "Linked", "Independent")


def S(key, text, kind, default, more=None):
    return {"key": key, "text": text, "kind": kind, "default": default, "more": more}



# in the drawing document (doc.Meta, where the dimensions and tables read them: row() and optionspages.doc_value)
DIM_SUBS = ("Angle", "Angular Running", "Arc Length", "Chamfer", "Diameter", "Hole Callout", "Linear", "Ordinate",
            "Radius")
TABLE_SUBS = ("Bend", "General", "Title Block Table")
ROW = "row:"


def _part_rows(page):
    """[(heading, [setting])] of a part sub-page as this dialog's settings (key row:<page>:<text>)."""
    try:
        from . import optionspages as OP
    except Exception:
        return []
    out = []
    for head, items in OP.SUB_PAGES.get(page, ()):
        ss = []
        for text, default in items:
            if (page, text) in getattr(OP, "UNREAD", ()):
                continue
            key = "%s%s:%s" % (ROW, page, text)
            choices = OP.CHOICES.get((page, text)) or OP.TEXT_CHOICES.get(text)
            if isinstance(default, bool):
                ss.append(S(key, text, "bool", default))
            elif choices:
                ss.append(S(key, text, "combo", default, list(choices) + ([] if str(default) in choices else [str(default)])))
            elif isinstance(default, (int, float)):
                ss.append(S(key, text, "num", float(default), (-1e4, 1e4, "")))
            else:
                ss.append(S(key, text, "text", default))
        if ss:
            out.append((head, ss))
    return out


def _row_key(key):
    page, _sep, text = key[len(ROW):].partition(":")
    return page, text


def _balloon_choices():
    from . import drawannot as DA
    return DA.BalloonPanel.SHAPES, DA.BALLOON_SIZES


def pages():
    ""
    from . import drawannot as DA
    shapes, sizes = _balloon_choices()
    annotations = ("Annotations", [
        ("Text", [S("ann_font", "Font", "text", "Century Gothic"),
                  S("ann_height", "Font height", "num", 3.5, (0.5, 50.0, "mm"))]),
        ("Leader", [S("pm:Note:SWNoteBorder", "Note border", "combo", "None", DA.NOTE_BORDERS)]),
    ], [
        ("Balloons", [("Single balloon", [S("pm:Balloon:SWBalloonStyle", "Style", "combo", "Circular", shapes),
                                          S("pm:Balloon:SWBalloonSize", "Size", "combo", "2 Characters", sizes),
                                          S("pm:Balloon:SWBalloonPadding", "Padding", "num", 1.5, (0, 50, "mm"))]),
                      ("Auto Balloon", [S("pm:Auto Balloon:SWBalloonStyle", "Style", "combo", "Circular", shapes),
                                        S("pm:Auto Balloon:SWBalloonSize", "Size", "combo", "2 Characters", sizes),
                                        S("pm:Auto Balloon:SWAutoBalloonLayout", "Auto balloon layout", "combo",
                                          "Square", BALLOON_LAYOUTS)])],
         []),
        ("Datums", [("Datum feature display type", [
            S("datum_frame", "Frame style", "combo", "Square", DA.DATUM_FRAMES),
            S("datum_leader", "Leader style", "combo", "Filled triangle", DA.DATUM_LEADERS)])], []),
        ("Geometric Tolerances", [("Leader", [S("pm:Geometric Tolerance:SWAnnotArrow", "Leader style", "combo",
                                                 "Filled arrow", ("Filled arrow", "Open arrow", "Dot", "Filled triangle", "None"))])], []),
        ("Notes", [(None, [S("pm:Note:SWNoteFontSize", "Font height", "num", 3.5, (0.5, 50.0, "mm")),
                           S("pm:Note:SWNoteUpper", "All uppercase", "bool", False),
                           S("note_align", "Text alignment", "combo", "Left", NOTE_ALIGNS)]),
                   ("Leader anchor", [S("note_anchor", "Anchor", "combo", "Closest", NOTE_ANCHORS)]),
                   ("Leader display", [S("note_leader", "Leader", "combo", "Bent", NOTE_LEADER_LOOKS)])], []),
        ("Revision Clouds", [(None, [S("pm:Revision Cloud:SWCloudShape", "Shape", "combo", "Rectangle",
                                       ("Rectangle", "Ellipse", "Irregular polygon")),
                                     S("pm:Revision Cloud:SWCloudArc", "Maximum arc radius", "num", 3.0,
                                       (0.5, 100.0, "mm")),
                                     S("cloud_line", "Line style", "combo", "Solid", CLOUD_STYLES)])], []),
        ("Surface Finishes", [("Surface texture standard", [S("pm:Surface Finish:SWFinishStandard", "Standard",
                                                               "combo", "ISO 1302", DA.FINISH_STANDARDS)]),
                              ("Leader", [S("pm:Surface Finish:SWAnnotArrow", "Leader style", "combo", "Filled arrow",
                                            ("Filled arrow", "Open arrow", "Dot", "Filled triangle", "None"))])], []),
        ("Weld Symbols", [(None, [S("weld_fixed", "Fixed size weld symbols", "bool", True),
                                  S("weld_bead", "Weld bead display", "combo", "Simplified", ("Simplified", "Full"))])],
         []),
    ])
    dimensions = ("Dimensions", [
        ("Text", [S("dim_height", "Font height", "num", 3.5, (0.5, 50.0, "mm"))]),
        (None, [S("dim_dual", "Dual dimensions display", "bool", False),
                S("dim_parens", "Add parentheses by default", "bool", False),
                S("dim_center", "Center between extension lines", "bool", False),
                S("dim_broken", "Show dimensions as broken in break views", "bool", True),
                S("dim_reduce", "Reduce spacing when dimensions are deleted or edited", "bool", True)]),
        ("Primary precision", [S("dim_precision", "Unit precision", "combo", ".12", PRECISIONS),
                               S("dim_tolerance", "Tolerance", "combo", "None", TOLS),
                               S("dim_plus", "Maximum variation", "num", 0.1, (-100, 100, "mm")),
                               S("dim_minus", "Minimum variation", "num", -0.1, (-100, 100, "mm"))]),
        ("Zeroes", [S("dim_lead", "Leading zeroes", "combo", "Standard", ("Standard", "Show", "Remove")),
                    S("dim_trail", "Trailing zeroes, dimensions", "combo", "Smart", TRAILING),
                    S("dim_trail_tol", "Trailing zeroes, tolerances", "combo", "Smart", TRAILING),
                    S("dim_trail_prop", "Trailing zeroes, properties", "combo", "Smart", TRAILING)]),
        ("Arrows", [S("dim_arrow", "Style", "combo", "Filled arrow", ARROWS),
                    S("dim_arrows", "Placement", "combo", "Smart", ("Smart", "Inside", "Outside"))]),
        ("Extension lines", [S("dim_gap", "Gap", "num", 0.75, (0.0, 10.0, "")),
                             S("dim_beyond", "Beyond dimension line", "num", 0.0, (0.0, 20.0, "mm")),
                             S("dim_line", "Line thickness", "combo", "0.25mm", THICK)]),
        ("Break dimension/extension lines", [S("dim_break_gap", "Gap", "num", 1.0, (0.0, 20.0, "mm")),
                                             S("dim_break_arrows", "Break around dimension arrows only", "bool",
                                               False)]),
        ("Hole Callout", [S("pm:Hole Callout:SWHolePrecision", "Precision", "combo", ".12", DA.PRECISIONS)]),
    ], [(p, _part_rows(p), []) for p in DIM_SUBS])
    centers = ("Centerlines/Center Marks", [
        ("Center marks", [S("pm:Center Mark:SWCenterMarkSize", "Size", "num", 2.5, (0.1, 100.0, "mm")),
                          S("pm:Center Mark:SWCenterMarkExtended", "Extended lines", "bool", True)]),
        ("Centerlines", [S("cl_over", "Extension", "num", 2.0, (0.0, 50.0, "mm"))]),
    ], [])
    tables = ("Tables", [("Text", [S("tbl_height", "Font height", "num", 3.5, (0.5, 50.0, "mm"))]),
                         ("Border", [S("tbl_line", "Line thickness", "combo", "0.35mm", THICK),
                                     S("tbl_box", "Box thickness", "combo", "Thin", THICKNESS_NAMES),
                                     S("tbl_grid", "Grid thickness", "combo", "Thin", THICKNESS_NAMES)])], [
        ("Bill of Materials", [(None, [S("bom_noqty", "Do not add QTY next to configuration name", "bool", False),
                                       S("bom_zero", "Zero quantity display", "combo", "0", ZERO_QTY),
                                       S("bom_missing", "Missing component", "combo", MISSING[0], MISSING)])], []),
        ("Hole", [(None, [S("hole_alpha", "Alpha/numerical control", "combo", HOLE_CONTROL[0], HOLE_CONTROL),
                          S("hole_origin", "Origin indicator", "combo", ORIGIN_MARKS[0], ORIGIN_MARKS)])], []),
        ("Revision", [("Revision symbol shapes", [S("rev_shape", "Shape", "combo", "Triangle", REV_SHAPES)]),
                      ("Alpha/numerical control", [S("rev_control", "Start with", "combo", REV_CONTROL[0],
                                                     REV_CONTROL)]),
                      ("Multi-sheet style", [S("rev_multi", "Style", "combo", REV_MULTI[0], REV_MULTI)]),
                      (None, [S("pm:Revision Table:SWRevAutoSymbol", "Enable symbol when adding new revision", "bool",
                                True)])], []),
    ] + [(p, _part_rows(p), []) for p in TABLE_SUBS])
    views = ("Views", [
        (None, [S("lbl_on", "Display labels under new views", "bool", True)]),
    ], [
        ("Auxiliary", [("Label", [S("lbl_aux", "Name", "text", "VIEW")])], []),
        ("Detail", [("Label", [S("lbl_detail", "Name", "text", "DETAIL"),
                               S("lbl_detail_scale", "Scale", "bool", True)])], []),
        ("Orthographic", [("Label", [S("lbl_ortho_on", "Display label", "bool", False),
                                     S("lbl_ortho", "Name", "text", "VIEW"),
                                     S("lbl_ortho_scale", "Scale", "bool", False)])], []),
        ("Other", [("Label", [S("lbl_other_on", "Display label", "bool", False),
                              S("lbl_other", "Name", "text", "VIEW"),
                              S("lbl_other_scale", "Scale", "bool", True)])], []),
        ("Section", [("Label", [S("lbl_section", "Name", "text", "SECTION"),
                                S("lbl_section_scale", "Scale", "bool", True)])], []),
    ])
    sharps = ("Virtual Sharps", [(None, [S("sharp_style", "Virtual sharp style", "combo", "Witness lines", SHARPS)])], [])
    drafting = ("Drafting Standard", [
        (None, [S("standard", "Overall drafting standard", "combo", "ANSI", STANDARDS)]),
        ("Uppercase", [S("upper_notes", "All uppercase for notes", "bool", False),
                       S("upper_dims", "All uppercase for dimensions and hole callouts", "bool", False),
                       S("upper_tables", "All uppercase for tables", "bool", False),
                       S("upper_exclude", "Exclusion list", "text", EXCLUSIONS)]),
    ], [annotations, dimensions, centers, tables, views, sharps])
    detailing = ("Detailing", [
        ("Auto insert on view creation", [
            S("auto_holes", "Center marks-holes -part", "bool", True),
            S("auto_fillets", "Center marks-fillets -part", "bool", False),
            S("auto_slots", "Center marks-slots -part", "bool", False),
            S("auto_holes_asm", "Center marks-holes -assembly", "bool", False),
            S("auto_fillets_asm", "Center marks-fillets -assembly", "bool", False),
            S("auto_slots_asm", "Center marks-slots -assembly", "bool", False),
            S("auto_centerlines", "Centerlines", "bool", False),
            S("auto_threads", "Cosmetic threads", "bool", False),
            S("auto_dims", "Dimensions marked for drawing", "bool", False),
            S("auto_balloons", "Balloons", "bool", False)]),
        ("Detailing mode", [S("detail_cache", "Include detailing mode data when saving", "bool", False)]),
        ("Selection", [S("highlight_refs", "Highlight associated elements on reference dimension selection", "bool",
                         True)]),
        ("Display data", [S("save_tess", "Save tessellated data for drawings with shaded and draft quality views",
                            "bool", True)]),
    ], [])
    sheets = ("Drawing Sheets", [("Sheet format/size", [
        S("sheet_own", "Use different sheet format for new sheets", "bool", False),
        S("sheet_format", "Sheet format", "combo", "A (ANSI) Landscape", _sheet_names())]),
        ("Multi-sheet custom properties source", [
            S("sheet_props_all", "Use custom property values from this sheet on all sheets", "bool", False),
            S("sheet_props_number", "Sheet number", "num", 1.0, (1.0, 999.0, ""))])], [])
    grid = ("Grid/Snap", [("Grid", [S("grid_on", "Display grid", "bool", False),
                                    S("grid_major", "Major grid spacing", "num", 10.0, (0.5, 500.0, "mm"))])], [])
    units = ("Units", [(None, [S("units", "Unit system", "combo", "mm", [u for _t, u in UNIT_SYSTEMS])])], [])
    font = ("Line Font", [

        ("Visible Edges", [S("lf_visible", "Thickness", "combo", "0.25mm", THICK)]),
        ("Hidden Edges", [S("lf_hidden", "Thickness", "combo", "0.18mm", THICK)]),
        ("Detail Circle", [S("lf_detail", "Style", "combo", "Hidden", LINE_STYLES)]),
        ("Section Line", [S("lf_section", "Style", "combo", "Center", LINE_STYLES)]),
        ("Break Lines", [S("lf_break", "Style", "combo", "Visible", LINE_STYLES)]),
    ], [])
    thickness = ("Line Thickness", [(None, [S(_th_key(n), n, "num", THICKNESS_MM[n], (0.01, 10.0, "mm"))
                                            for n in THICKNESS_NAMES])], [])
    linestyle = ("Line Style", [("Line styles", [S("line_styles", "Line style", "linestyles", {})])], [])
    quality = ("Image Quality", [
        ("Shaded and draft quality HLR/HLV resolution", [
            S("iq_shaded", "Resolution (Low 1 - 10 High)", "num", 5.0, (1.0, 10.0, ""))]),
        ("Wireframe and high quality HLR/HLV resolution", [
            S("iq_wire", "Resolution (Low 1 - 10 High)", "num", 5.0, (1.0, 10.0, "")),
            S("iq_draft_new", "Draft quality for new views", "bool", False)])], [])
    sheetmetal = ("Sheet Metal", [("Bend notes", [
        S("sm_bend_notes", "Display sheet metal bend notes", "bool", True),
        S("sm_note_style", "Style", "combo", "Above Bend Line", BEND_NOTE_STYLES),
        S("sm_note_format", "Format (<direction> <angle> <radius> <order>)", "text",
          "<direction>  <angle>°  R <radius>")]),
        ("Flat pattern", [S("sm_grain", "Display grain direction", "bool", False),
                          S("sm_bbox", "Display bounding box", "bool", False)]),
        ("Flat pattern colors", [S("sm_col_up", "Bend Lines - Up Direction", "color", "#000000"),
                                 S("sm_col_down", "Bend Lines - Down Direction", "color", "#000000"),
                                 S("sm_col_bbox", "Bounding Box", "color", "#000000")])], [])
    return [drafting, detailing, sheets, grid, units, font, linestyle, thickness, quality, sheetmetal]


def _sheet_names():
    try:
        from . import drawsheet
        return [s[0] for s in drawsheet.SIZES]
    except Exception:
        return ["A (ANSI) Landscape"]


def all_settings():
    out = []

    def walk(items):
        for title, groups, children in items:
            for _h, ss in groups:
                out.extend(ss)
            walk(children)
    walk(pages())
    return out


_DEFAULTS = {}


def defaults():
    """{key: default} of every Document Properties setting. Worked out once: the settings tree is the same all
    session, and prop() asks for it often (the sheet's 1 s tick: 20 ms of a 28 ms tick on the engine drawing)."""
    if not _DEFAULTS:
        _DEFAULTS.update({s["key"]: s["default"] for s in all_settings()})
    return dict(_DEFAULTS)


# --------------------------------------------------------------------------- the store
def stored(doc):
    """The drawing's own values ({} until Document Properties were set once). Until then its drafting standard is
    the sheets' own (an ISO sheet in first angle is ISO): the ANSI default made OK in Document Properties put a
    new ISO drawing's projected views on the other side of their parent."""
    if doc is None:
        return {}
    v = P._get(doc, "SWDocProps", {}) or {}
    if "standard" not in v:
        std = sheet_standard(doc)
        if std:
            v = dict(v, standard=std)
    return v


def sheet_standard(doc):
    """The drafting standard the drawing's first sheet was made with: as last applied, else its projection's."""
    try:
        pages = doc.findObjects("TechDraw::DrawPage")
    except Exception:
        return None
    if not pages:
        return None
    std = getattr(pages[0], "SWDraftStandard", "") or ""
    if std in STANDARDS:
        return std
    return "ISO" if getattr(pages[0], "ProjectionType", "") == "First angle" else "ANSI"


def units(doc):
    """Document Properties > Units of the drawing: as set, else the document's own unit system (an IPS
    document's drawing is IPS)."""
    v = stored(doc)
    if v.get("units") in [u for _t, u in UNIT_SYSTEMS]:
        return v["units"]
    try:
        from . import unitspage
        symbol = unitspage.length_unit(doc)[0]
    except Exception:
        symbol = "mm"
    return {"ft": "in"}.get(symbol, symbol) if {"ft": "in"}.get(symbol, symbol) in [u for _t, u in UNIT_SYSTEMS] \
        else "mm"


def prop(doc, key):
    v = stored(doc)
    if key in v:
        return v[key]
    if not _DEFAULTS:
        defaults()
    return _DEFAULTS.get(key)


def set_props(doc, values):
    P._set(doc, "SWDocProps", values, "Document Properties")


# --------------------------------------------------------------------------- Drafting Standard to a file
STANDARD_PAGES = ("Drafting Standard",)


def standard_keys():
    """The settings a drafting standard file holds: the Drafting Standard page and every page under it."""
    out = []

    def walk(items, inside):
        for title, groups, children in items:
            now = inside or title in STANDARD_PAGES
            if now:
                for _h, ss in groups:
                    out.extend(s["key"] for s in ss)
            walk(children, now)
    walk(pages(), False)
    return out


def save_standard(values, path):
    keys = standard_keys()
    data = {"FreeWorksDraftingStandard": 1, "standard": values.get("standard"),
            "values": {k: values[k] for k in keys if k in values}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    return path


def load_standard(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "values" not in data:
        raise ValueError("not a drafting standard file")
    keys = set(standard_keys())
    return {k: v for k, v in data["values"].items() if k in keys}


# --------------------------------------------------------------------------- Line Style / Image Quality
def _pattern(text):
    """'6, 1.5, 1' -> '6,1.5,1' (dash, gap, dash... in mm; '' is a solid line)."""
    nums = [float(x) for x in re.split(r"[,;\s]+", str(text).strip()) if x]
    if any(n < 0 for n in nums) or (nums and len(nums) % 2):
        raise ValueError("a line style is pairs of dash and gap lengths")
    return ",".join(("%g" % n) for n in nums)


def line_styles(doc=None):
    ""
    out = {k: P.DASHES.get(k, "") for k in BUILTIN_STYLES}
    own = prop(doc, "line_styles") if doc is not None else {}
    out.update(own or {})
    return out


def apply_line_styles(doc):
    """The drawing's line styles go into the style lists of the annotation and sketch PMs."""
    own = (prop(doc, "line_styles") or {}) if doc is not None else {}
    for k in list(P.DASHES):
        if k not in BUILTIN_STYLES and k not in own:
            del P.DASHES[k]
    P.DASHES.update(own)
    P.LINE_STYLES = tuple(BUILTIN_STYLES) + tuple(k for k in own if k not in BUILTIN_STYLES)


def shaded_ppm(doc=None):
    """Shaded views: picture pixels per sheet mm from Image Quality (5 = 20 px/mm, 10 = 40, 1 = 4)."""
    try:
        return 4.0 * max(1.0, min(10.0, float(prop(doc, "iq_shaded"))))
    except Exception:
        return 20.0


def draft_new_views(doc):
    """New views open in draft quality (TechDraw CoarseView) when Image Quality says so or the wireframe
    resolution is at its lowest."""
    if not stored(doc):
        return None
    return bool(prop(doc, "iq_draft_new")) or float(prop(doc, "iq_wire")) <= 1.0


# --------------------------------------------------------------------------- applying
def _thick(text):
    try:
        return float(text[:-2])
    except Exception:
        return 0.35


def apply_page(page, v):
    want = "Third angle" if v["standard"] == "ANSI" else "First angle"
    was = getattr(page, "SWDraftStandard", None)
    if "SWDraftStandard" not in page.PropertiesList:
        page.addProperty("App::PropertyString", "SWDraftStandard", "FreeCAD", "drafting standard last applied")
    page.SWDraftStandard = v["standard"]
    if was == v["standard"]:
        pass                                # the sheet keeps its own projection (Sheet Properties)
    elif page.ProjectionType != want:
        page.ProjectionType = want
        try:
            D.flip_projected(page)          # the projected views go to the other side of their parent
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: projection type: %s\n" % error)
    for o in page.Views:
        if o.TypeId == "TechDraw::DrawProjGroup":
            o.ProjectionType = page.ProjectionType
    try:
        page.ViewObject.ShowGrid = bool(v["grid_on"])
        page.ViewObject.GridSpacing = float(v["grid_major"])
    except Exception as _fw_err:
        _fw_log("drawdocprops.py:492", _fw_err)


def apply_view(view, v):
    vo = getattr(view, "ViewObject", None)
    if vo is None:
        return
    for name, value in (("LineWidth", _thick(v["lf_visible"])), ("HiddenWidth", _thick(v["lf_hidden"])),
                        ("HighlightLineStyle", v["lf_detail"]), ("SectionLineStyle", v["lf_section"]),
                        ("BreakLineStyle", v["lf_break"])):
        if hasattr(vo, name):
            try:
                setattr(vo, name, value)
            except Exception as _fw_err:
                _fw_log("drawdocprops.py:506", _fw_err)


PLAIN = re.compile(r"^([\u2300R]?)%\.\d+[wf]$")      # the plain value, a diameter's or radius's with its sign


def _upper_spec(spec):
    """Uppercase outside the %... value tokens."""
    parts = re.split(r"(%[-+ #0]*\d*(?:\.\d+)?[wfgGeE])", spec)
    return "".join(p if i % 2 else upper_text(p) for i, p in enumerate(parts))


def apply_dimension(dim, v):
    """The document's dimension settings on dim (its value text only while it is still the plain value and has
    no options of its own from the Dimension PM)."""
    from . import drawdimpm as DP
    vo = getattr(dim, "ViewObject", None)
    if vo is not None:
        try:
            if not getattr(dim, "SWFont", ""):
                vo.Fontsize = float(v["dim_height"])
                font = v.get("ann_font", "")
                page = TEXT_PAGES.get(dim.Type, "Linear")
                from . import optionspages as OP
                # A type's explicit font row is more specific than the global annotation font.
                if OP.DOC_META + OP._store_key(page, "Font") in dict(getattr(dim.Document, "Meta", {}) or {}):
                    font = row(dim.Document, page, "Font", font)
                if font and hasattr(vo, "Font"):
                    vo.Font = font                    # the document font (else TechDraw's osifont)
            vo.ArrowStyle = v["dim_arrow"]
            vo.LineWidth = _thick(v["dim_line"])
            if getattr(dim, "SWDocGap", "1") != "0":
                vo.GapFactorISO = float(v["dim_gap"])
                vo.GapFactorASME = float(v["dim_gap"])
            if not getattr(dim, "SWArrows", ""):
                placement = v.get("dim_arrows", "Smart")
                page = TEXT_PAGES.get(dim.Type, "Linear")
                from . import optionspages as OP
                # The dimension type's explicitly set row is more specific than the document-wide placement.
                if OP.DOC_META + OP._store_key(page, "Arrows") in dict(getattr(dim.Document, "Meta", {}) or {}):
                    placement = row(dim.Document, page, "Arrows", placement)
                vo.FlipArrowheads = placement == "Outside"
            vo.StandardAndStyle = "ASME Inlined" if v["standard"] == "ANSI" else "ISO Oriented"
            text_position(dim, vo, v["standard"])
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Document Properties: %s\n" % error)
    own = DP.options_of(dim) and getattr(dim, "SWDocDefaults", "") != "1"
    if own:
        try:     # the Dimension PM's "(Document)" precision follows the new Primary precision
            DP.follow_document_precision(dim)
        except Exception as _fw_err:
            _fw_log("drawdocprops.py:follow precision", _fw_err)
        return
    plain = PLAIN.match(dim.FormatSpec or "")
    if plain:
        if "SWDocPrefix" not in dim.PropertiesList:
            dim.addProperty("App::PropertyString", "SWDocPrefix", "FreeCAD", "the sign before the value (diameter, radius)")
            dim.setPropertyStatus("SWDocPrefix", ["Hidden"])
        if dim.SWDocPrefix != plain.group(1):
            dim.SWDocPrefix = plain.group(1)
    prefix = getattr(dim, "SWDocPrefix", "") or ""
    if not (plain or getattr(dim, "SWDocDefaults", "") == "1"):
        if v["upper_dims"] and (dim.FormatSpec or "") != _upper_spec(dim.FormatSpec or ""):
            dim.FormatSpec = _upper_spec(dim.FormatSpec)
        return
    angle = dim.Type in ("Angle", "Angle3Pt")
    chosen = units(dim.Document)
    try:
        from . import unitspage
        own = unitspage.length_unit(dim.Document)[0]
    except Exception:
        own = "mm"
    # the document's own unit: TechDraw writes it (with the schema's own format); another unit: worked out here
    units_now = chosen if chosen != own and not angle else "Document"
    tolerance = v["dim_tolerance"]
    page = TEXT_PAGES.get(dim.Type, "Linear")
    from . import optionspages as OP
    # PM options returned above; an explicit type row supplies the default tolerance mode.
    if OP.DOC_META + OP._store_key(page, "Tolerance") in dict(getattr(dim.Document, "Meta", {}) or {}):
        tolerance = row(dim.Document, page, "Tolerance", tolerance)
    DP.apply(dim, tol=tolerance, plus=float(v["dim_plus"]), minus=float(v["dim_minus"]),
             precision=v["dim_precision"], parens=bool(v["dim_parens"]), dual=bool(v["dim_dual"]),
             dual_unit="mm" if chosen == "in" else "in", units=units_now, from_doc=True, text=prefix + DP.DIM)
    if row(dim.Document, "Dimensions", "Center between extension lines", False, "dim_center"):
        DP.center_text(dim)


TEXT_PAGES = {"Diameter": "Diameter", "Radius": "Radius", "Angle": "Angle", "Angle3Pt": "Angle"}
TEXT_DEFAULTS = {"Diameter": "Broken leader, horizontal text", "Radius": "Broken leader, horizontal text",
                 "Angle": "Solid leader, aligned text", "Linear": "Solid leader, aligned text"}


def text_position(dim, vo, standard):
    """Document Properties > Dimensions > <type> > Text position (and Diameter's Display second outside arrow)
    as TechDraw's dimension style. Linear and Angle keep the standard's style unless their row was changed."""
    if getattr(dim, "SWTextPosition", ""):
        return                                   # the dimension's own Custom Text Position
    page = TEXT_PAGES.get(dim.Type, "Linear")
    want = row(dim.Document, page, "Text position", TEXT_DEFAULTS[page])
    if page in ("Linear", "Angle") and want == TEXT_DEFAULTS[page]:
        pass
    elif want == "Broken leader, horizontal text":
        vo.StandardAndStyle = "ASME Referencing" if standard == "ANSI" else "ISO Referencing"
    elif want == "Solid leader, aligned text":
        vo.StandardAndStyle = "ISO Oriented"
    elif want == "Broken leader, aligned text":
        vo.StandardAndStyle = "ISO Referencing" if standard != "ANSI" else "ASME Inlined"
    if dim.Type == "Diameter" and "RenderingExtent" in vo.PropertiesList and \
            not row(dim.Document, "Diameter", "Display second outside arrow", True):
        vo.RenderingExtent = "Reduced"


def apply_table(t, v):
    try:
        if hasattr(t, "TextSize"):
            # look-audit tablefont-1121: Font height is in mm, a table's TextSize in its own units (1/96 in)
            t.TextSize = float(v["tbl_height"]) / (25.4 / 96.0 * float(getattr(t, "Scale", 1.0) or 1.0))
        if hasattr(t, "LineWidth"):
            t.LineWidth = _thick(v["tbl_line"])

        # not TechDraw's osifont; a font picked for the table itself (drawtablecells) stays
        if hasattr(t, "Font"):
            font = v.get("ann_font", "")
            from . import optionspages as OP
            if OP.DOC_META + OP._store_key("Tables", "Font") in dict(getattr(t.Document, "Meta", {}) or {}):
                font = row(t.Document, "Tables", "Font", font)
            if font and t.Font in ("", "osifont", getattr(t, "SWDocFont", "")) and t.Font != font:
                t.Font = font
            if font and t.Font == font and getattr(t, "SWDocFont", None) != font:
                if "SWDocFont" not in t.PropertiesList:
                    t.addProperty("App::PropertyString", "SWDocFont", "FreeCAD", "The document font the table follows")
                    t.setEditorMode("SWDocFont", 2)
                t.SWDocFont = font
    except Exception as _fw_err:
        _fw_log("drawdocprops.py:606", _fw_err)


def apply_annotation(sym, v):
    ""

    from . import drawannot as DA
    if getattr(sym, "SWAnnotation", "") == "DatumFeature" and getattr(sym, "SWDatumDoc", False):
        DA.restyle_datum(sym, v["datum_frame"], v["datum_leader"])
    text = sym.Symbol or ""
    font = v.get("ann_font", "")
    kind = getattr(sym, "SWAnnotation", "")
    if kind in ("Note", "DatumFeature"):
        from . import optionspages as OP
        # These annotations use their explicit page font only when no custom font is already in the SVG.
        page = "Notes" if kind == "Note" else "Datums"
        if OP.DOC_META + OP._store_key(page, "Font") in dict(getattr(sym.Document, "Meta", {}) or {}):
            font = row(sym.Document, page, "Font", font)
    new = DA.with_font(text, font)
    if new != text:
        sym.Symbol = new


def apply_all(doc):
    """OK in Document Properties: the drawing takes the values."""
    v = dict(defaults(), **stored(doc))
    flats = []
    for o in doc.Objects:
        try:
            if o.TypeId == "TechDraw::DrawPage":
                apply_page(o, v)
            elif o.isDerivedFrom("TechDraw::DrawViewPart"):
                apply_view(o, v)
                if getattr(o, "SWFlatPattern", False):
                    flats.append(o)
            elif o.TypeId == "TechDraw::DrawViewDimension":
                apply_dimension(o, v)
            elif o.TypeId == "TechDraw::DrawViewSpreadsheet":
                apply_table(o, v)
            elif o.TypeId == "TechDraw::DrawViewSymbol" and getattr(o, "SWAnnotation", ""):
                apply_annotation(o, v)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Document Properties %s: %s\n" % (o.Name, error))
    for o in flats:                     # Sheet Metal: bend note style, grain direction, bounding box
        try:
            from . import drawtables
            drawtables.flat_pattern_extras(o, v)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: flat pattern display %s: %s\n" % (o.Name, error))
    sync(doc)
    doc.recompute()


_SYNCED = [None]


def sync(doc):
    """The module defaults that follow the drawing in front (annotation text height, centerline extension)."""
    from . import drawannot as DA
    v = dict(defaults(), **stored(doc)) if doc is not None else defaults()
    DA.TEXT_SIZE = float(v["ann_height"]) if doc is not None and stored(doc) else 3.5
    DA.CENTERLINE_OVER[0] = float(v["cl_over"]) if doc is not None and stored(doc) else 2.0
    try:
        apply_line_styles(doc)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: line styles: %s\n" % error)
    _SYNCED[0] = (doc.Name if doc is not None else None, json.dumps(stored(doc), sort_keys=True))


def sync_active():
    try:
        page = D.active_page() if D.in_drawing() else None
        doc = page.Document if page is not None else None
        key = (doc.Name if doc is not None else None, json.dumps(stored(doc), sort_keys=True))
        if key != _SYNCED[0]:
            sync(doc)
    except Exception as _fw_err:
        _fw_log("drawdocprops.py:683", _fw_err)


def _option_rows(panel, title):
    ""


    out = {}
    doc = getattr(panel, "doc", None)
    try:
        if title in ("Balloon", "Auto Balloon", "Stacked Balloon"):
            up = row(doc, "Balloons", "Upper", "Item Number")
            if up != "Item Number":
                out["SWBalloonText"] = up
            low = row(doc, "Balloons", "Lower", "Quantity")
            if low != "Quantity":
                out["SWBalloonLowerText"] = low
        elif title == "Note":
            bent = None
            try:
                from . import optionspages as OP
                if doc is not None and OP.DOC_META + OP._store_key("Notes", "Use bent leaders") in dict(doc.Meta):
                    bent = row(doc, "Notes", "Use bent leaders", True)   # only when the document sets it
            except Exception:
                bent = None
            anchor = row(doc, "Notes", "Leader anchor", "Closest")
            if anchor in ("Left", "Right"):
                out["SWNoteAttach" + anchor] = True
            if bent is not None:
                out["SWNoteLeaderBent" if bent else "SWNoteLeaderStraight"] = True
    except Exception as _fw_err:
        _fw_log("drawdocprops.py:714", _fw_err)
    return out


NOTE_ALIGNS = ("Left", "Center", "Right")
NOTE_ANCHORS = ("Left", "Closest", "Right")
NOTE_LEADER_LOOKS = ("Straight", "Bent", "Underlined")


class _ColorButton(QtWidgets.QPushButton):
    ""

    def __init__(self, color, text, parent=None):
        super().__init__(parent)
        self.label = text
        self.set_color(color)
        self.clicked.connect(self.pick)

    def set_color(self, color):
        c = QtGui.QColor(color)
        self.color = c.name() if c.isValid() else "#000000"
        pix = QtGui.QPixmap(28, 12)
        pix.fill(QtGui.QColor(self.color))
        self.setIcon(QtGui.QIcon(pix))
        self.setText("Edit...")
        self.setToolTip("%s: %s" % (self.label, self.color))

    def pick(self):
        c = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.color), self, self.label)
        if c.isValid():
            self.set_color(c.name())


def hex_rgb(text, default=(0.0, 0.0, 0.0)):
    """'#rrggbb' -> (r, g, b) 0..1."""
    try:
        t = str(text).lstrip("#")
        return tuple(int(t[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except Exception:
        return default


def pm_defaults(panel):
    """A drawing PM opens with the document's defaults for it (by its widgets' names)."""
    vals = stored(panel.doc) or {}
    title = getattr(panel, "TITLE", "")
    mine = {k.split(":", 2)[2]: v for k, v in vals.items() if k.startswith("pm:%s:" % title)}
    mine.update(_option_rows(panel, title))
    if title in ("Balloon", "Auto Balloon", "Stacked Balloon"):
        from . import optionspages as OP
        for text, default in (("Style", "Circular"), ("Size", "2 Characters")):
            key = ("SWStack" if title == "Stacked Balloon" else "SWBalloon") + text
            if key in mine:
                continue
            stored_as = ("Stacked " + text) if title == "Stacked Balloon" else text
            if OP.DOC_META + OP._store_key("Balloons", stored_as) in dict(getattr(panel.doc, "Meta", {}) or {}):
                mine[key] = row(panel.doc, "Balloons", stored_as, default)
    if title == "Datum Feature" and getattr(panel, "doc_style", None) is not None:
        from . import optionspages as OP
        frame = vals.get("datum_frame", "Square")
        if "datum_frame" not in vals and OP.DOC_META + OP._store_key("Datums", "Frame style") in dict(getattr(panel.doc, "Meta", {}) or {}):
            frame = row(panel.doc, "Datums", "Frame style", frame, "datum_frame")
        mine.update({"SWDatumFrame": frame,
                     "SWDatumLeaderStyle": vals.get("datum_leader", "Filled triangle")})
    if title == "Note" and vals.get("upper_notes"):
        mine["SWNoteUpper"] = True
    if title == "Note":
        if vals.get("note_align") in NOTE_ALIGNS:
            mine["SWNoteAlign" + vals["note_align"]] = True
        if vals.get("note_anchor") in NOTE_ANCHORS:
            mine["SWNoteAttach" + {"Closest": "Nearest"}.get(vals["note_anchor"], vals["note_anchor"])] = True
        from . import optionspages as OP
        for text, key, default in (("Style", "SWNoteBorder", "None"), ("Size", "SWNoteBorderSize", "Tight Fit")):
            if key in mine:
                continue
            if OP.DOC_META + OP._store_key("Notes", text) in dict(getattr(panel.doc, "Meta", {}) or {}):
                mine[key] = row(panel.doc, "Notes", text, default)
        leader = vals.get("note_leader")
        if "note_leader" not in vals and panel.doc is not None:
            from . import optionspages as OP
            # An explicitly set document row supplies the PM default; leave unset drawing defaults alone.
            if OP.DOC_META + OP._store_key("Notes", "Leader style") in dict(getattr(panel.doc, "Meta", {}) or {}):
                leader = row(panel.doc, "Notes", "Leader style", "Straight")
        if leader in NOTE_LEADER_LOOKS:
            mine["SWNoteLeader" + leader] = True
    if title == "Revision Table":
        if vals.get("rev_shape") in REV_SHAPES:
            mine["SWRevShape" + vals["rev_shape"]] = True
        if vals.get("rev_control") in REV_CONTROL:
            mine["SWRevNumeric" if vals["rev_control"] == REV_CONTROL[1] else "SWRevAlpha"] = True
        if vals.get("rev_multi") in REV_MULTI:
            mine["SWRevMulti" + vals["rev_multi"].replace(" ", "")] = True
    if not mine:
        return
    for w in panel.form.findChildren(QtWidgets.QWidget):
        n = w.objectName()
        if n not in mine:
            continue
        val = mine[n]
        try:
            if isinstance(w, QtWidgets.QComboBox):
                w.setCurrentText(str(val))
            elif isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                w.setValue(float(val))
            elif isinstance(w, QtWidgets.QAbstractButton) and w.isCheckable():
                w.setChecked(bool(val))
        except Exception as _fw_err:
            _fw_log("drawdocprops.py:821", _fw_err)


# --------------------------------------------------------------------------- new objects
LABEL_OF = {"TechDraw::DrawViewSection": ("lbl_section", "lbl_section_scale"),
            "TechDraw::DrawComplexSection": ("lbl_section", "lbl_section_scale"),
            "TechDraw::DrawViewDetail": ("lbl_detail", "lbl_detail_scale")}


def _scale_text(view):
    ""
    try:
        return D.scale_text(float(view.Scale)).replace(":", " : ")
    except Exception:
        return "%g" % float(view.Scale)


DRIVEN_GREY = (0.5, 0.5, 0.5)


def driven_color():
    """Options > Colors > Dimensions, Non Imported (Driven): the colour of dimensions added in the drawing (the
    model's own, brought in by Model Items, stay black)."""
    try:
        u = App.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned("NonDrivingConstrDimColor", 0)
        try:
            # look-audit dimgrey-1121: the sheet stays white in every theme, so Dark's grey lifted for the dark

            from . import style as _style
            if u and u == dict(_style.DARK_SKETCH_COLORS).get("NonDrivingConstrDimColor"):
                u = dict(_style.SKETCH_COLORS).get("NonDrivingConstrDimColor", u)
        except Exception as _fw_err:
            _fw_log("drawdocprops.py:dimgrey", _fw_err)
        if u:
            return ((u >> 24) & 255) / 255.0, ((u >> 16) & 255) / 255.0, ((u >> 8) & 255) / 255.0
    except Exception as _fw_err:
        _fw_log("drawdocprops.py:849", _fw_err)
    return DRIVEN_GREY


def paint_driven(dim):
    ""
    vo = getattr(dim, "ViewObject", None)
    if vo is None or "Color" not in vo.PropertiesList:
        return
    props = dim.PropertiesList
    if "SWModelItem" in props or "SWDangleColor" in props or "SWOverColor" in props or "SWDrivenPainted" in props:
        return
    if max(tuple(vo.Color)[:3]) > 0.2:
        return                      # a colour of the user's own (the default is black, or near black by theme)
    try:
        dim.addProperty("App::PropertyBool", "SWDrivenPainted", "FreeCAD", "drawn in the driven color")
        dim.setPropertyStatus("SWDrivenPainted", "Hidden")
        dim.SWDrivenPainted = True
        vo.Color = driven_color()
    except Exception as _fw_err:
        _fw_log("drawdocprops.py:869", _fw_err)


def _orthographic(view):
    """True for a view looking straight along a model axis (Front, Top, Right... and their projections)."""
    try:
        d = view.Direction
        return max(abs(d.x), abs(d.y), abs(d.z)) > 1 - 1e-6
    except Exception:
        return False


def _label_plain(view, v):
    ""

    kind = "ortho" if _orthographic(view) else "other"
    if getattr(view, "SWFlatPattern", False) or not v.get("lbl_%s_on" % kind, False):
        return
    page = next((o for o in view.InList if o.TypeId == "TechDraw::DrawPage"), None)
    if page is None:
        grp = next((o for o in view.InList if o.TypeId == "TechDraw::DrawProjGroup"), None)
        page = next((o for o in (grp.InList if grp else []) if o.TypeId == "TechDraw::DrawPage"), None)
    letter = getattr(view, "SWViewLetter", "")
    if not letter and page is not None:
        from . import drawviews as DV
        letter = DV.take_label(page)
        view.addProperty("App::PropertyString", "SWViewLetter", "FreeCAD", "its View Labels letter")
        view.setPropertyStatus("SWViewLetter", ["Hidden"])
        view.SWViewLetter = letter
    text = ("%s %s" % (v.get("lbl_" + kind, "VIEW"), letter)).strip()
    if v.get("lbl_%s_scale" % kind, False):
        text += "\nSCALE %s" % _scale_text(view)
    view.Caption = text


def label_view(view, v):
    """Views: the label under a new section or detail view (SECTION A-A, SCALE 1:2)."""
    keys = LABEL_OF.get(view.TypeId)
    if getattr(view, "SWAuxiliary", ""):
        if v["lbl_on"]:
            view.Caption = "%s %s" % (v["lbl_aux"], view.SWAuxiliary)
        return
    if keys is None and view.TypeId in ("TechDraw::DrawViewPart", "TechDraw::DrawProjGroupItem") and v["lbl_on"]:
        _label_plain(view, v)
        return
    if keys is None or not v["lbl_on"]:
        return
    name = v[keys[0]]
    letter = getattr(view, "SectionSymbol", "") or getattr(view, "Reference", "") or ""
    text = "%s %s" % (name, ("%s-%s" % (letter, letter)) if "Section" in view.TypeId and letter else letter)
    if v[keys[1]] and not _section_at_parent_scale(view):
        text += "\nSCALE %s" % _scale_text(view)
    view.Caption = text.strip()


def _section_at_parent_scale(view):
    ""
    if "Section" not in view.TypeId:
        return False
    base = getattr(view, "BaseView", None)
    try:
        from . import drawviews as DV
        return base is not None and abs(DV.view_scale(view) - DV.view_scale(base)) < 1e-9
    except Exception as _fw_err:
        _fw_log("drawdocprops.py:section scale", _fw_err)
        return False


def _plain_label_later(dname, name):
    """A new plain view is labelled once its direction is set (View Labels > Orthographic / Other)."""
    try:
        doc = App.getDocument(dname)
        obj = doc.getObject(name)
        if obj is None or getattr(obj, "SWAuxiliary", ""):
            return
        label_view(obj, dict(defaults(), **stored(doc)))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: view label: %s\n" % error)


class _Observer:
    """New dimensions, tables and views on a drawing with Document Properties set take them."""

    def slotCreatedObject(self, obj):
        try:
            doc = obj.Document
        except Exception:
            return
        tid = obj.TypeId
        if getattr(doc, "Restoring", False):
            return      # extapps/69: read from the file, not new: it keeps its own settings, layer and labels
        if tid in ("TechDraw::DrawViewDimension", "TechDraw::DrawViewBalloon"):
            QtCore.QTimer.singleShot(0, lambda n=obj.Name, dn=doc.Name: _on_current_layer(dn, n))
        if tid not in ("TechDraw::DrawViewDimension", "TechDraw::DrawViewSpreadsheet", "TechDraw::DrawViewPart",
                       "TechDraw::DrawProjGroupItem", "TechDraw::DrawViewSection", "TechDraw::DrawComplexSection",
                       "TechDraw::DrawViewDetail"):
            return
        name, dname = obj.Name, doc.Name
        if getattr(doc, "Restoring", False) and tid in ("TechDraw::DrawViewPart", "TechDraw::DrawProjGroupItem"):
            _RESTORED.add((dname, name))     # a view read from a file: nothing is auto inserted into it again
        if not stored(doc):
            if tid == "TechDraw::DrawViewDimension":
                QtCore.QTimer.singleShot(0, lambda: _broken_later(dname, name, 0))
            elif tid in LABEL_OF:
                # a drawing whose Document Properties were never set still labels a new section or detail

                QtCore.QTimer.singleShot(0, lambda: _default_label(dname, name, 0))
            elif tid in ("TechDraw::DrawViewPart", "TechDraw::DrawProjGroupItem"):

                QtCore.QTimer.singleShot(300, lambda: _auto_insert(dname, name, 0))
            return
        QtCore.QTimer.singleShot(0, lambda: _created(dname, name, 0))


    def slotDeletedObject(self, obj):
        try:
            if obj.TypeId != "TechDraw::DrawViewDimension" or not prop(obj.Document, "dim_reduce"):
                return
            info = _stack_info(obj)
        except Exception:
            return
        if info:
            QtCore.QTimer.singleShot(0, lambda: reduce_spacing(*info))

    def slotFinishRestoreDocument(self, doc):     # FreeCAD 1.1 never sends it: restorehook (start) does this
        pass

    def slotStartSaveDocument(self, doc, path):
        try:
            store_pictures(doc)
        except Exception as _fw_err:
            _fw_log("drawdocprops.py:store pictures", _fw_err)


def _restored(doc):
    try:
        name = doc.Name
    except Exception:
        return
    QtCore.QTimer.singleShot(0, lambda: hold_on_open(name))
    QtCore.QTimer.singleShot(500, lambda: _remake_pictures(name))
    QtCore.QTimer.singleShot(900, lambda: warn_missing_models(name))
    QtCore.QTimer.singleShot(400, lambda: _hatch_files(name))


def _hatch_files(name):
    """Sections saved with an ANSI hatch FreeCAD's own pattern file lacks: drawn with it (drawviews.ANSI_PAT)."""
    try:
        from . import drawviews
        drawviews.fix_hatch_files(name)
    except Exception as _fw_err:
        _fw_log("drawdocprops.py:hatch files", _fw_err)


def _saved_links(path):
    """{view name: [model file, ...]} as the drawing file stores its views' links (kept even when a file is gone)."""
    import re as _re
    import zipfile
    out = {}
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("Document.xml").decode("utf-8", "replace")
    except Exception as _fw_err:
        _fw_log("drawdocprops.py:saved links", _fw_err)
        return out
    for m in _re.finditer(r'<Object name="([^"]+)"[^>]*>(.*?)</Object>', xml, _re.S):
        files = _re.findall(r'<Property name="XSource"[^>]*>.*?</Property>', m.group(2), _re.S)
        if files:
            out[m.group(1)] = sorted(set(_re.findall(r'file="([^"]+)"', files[0])))
    return out


def missing_models(doc):
    """[(view, model file)] for the drawing's views whose model file cannot be found."""
    import os
    if doc is None or not doc.FileName:
        return []
    views = [o for o in doc.Objects if o.isDerivedFrom("TechDraw::DrawViewPart") and
             o.TypeId not in ("TechDraw::DrawViewSection", "TechDraw::DrawViewDetail", "TechDraw::DrawComplexSection")]
    if not views:
        return []
    links = _saved_links(doc.FileName)
    here = os.path.dirname(doc.FileName)
    out = []
    for v in views:
        if list(getattr(v, "Source", []) or []) or list(getattr(v, "XSource", []) or []):
            continue
        for f in links.get(v.Name, []):
            full = f if os.path.isabs(f) else os.path.normpath(os.path.join(here, f))
            if not os.path.isfile(full):
                out.append((v, full))
    return out


def store_pictures(doc):
    ""


    try:
        import TechDraw
    except Exception as _fw_err:
        _fw_log("drawdocprops.py:pictures import", _fw_err)
        return 0
    if doc is None or not any(o.TypeId == "TechDraw::DrawPage" for o in doc.Objects):
        return 0
    n = 0
    for v in doc.Objects:
        try:
            if not v.isDerivedFrom("TechDraw::DrawViewPart") or getattr(v, "SWModelMissing", ""):
                continue
            es = v.getVisibleEdges()
            if not es:
                continue
            svg = TechDraw.viewPartAsSvg(v)
            if "<path" not in svg:
                continue
            k = float(v.Scale)
            xa, xb = min(e.BoundBox.XMin for e in es), max(e.BoundBox.XMax for e in es)
            ya, yb = min(e.BoundBox.YMin for e in es), max(e.BoundBox.YMax for e in es)
            m = 5.0
            box = (xa * k - m, -yb * k - m, (xb - xa) * k + 2 * m, (yb - ya) * k + 2 * m)
            text = "%.4f %.4f %.4f %.4f|%s" % (box + (svg,))
            if "SWLastPicture" not in v.PropertiesList:
                v.addProperty("App::PropertyString", "SWLastPicture", "FreeCAD", "the view's lines when last saved")
                v.setEditorMode("SWLastPicture", 2)
            if v.SWLastPicture != text:
                v.SWLastPicture = text
            n += 1
        except Exception as _fw_err:
            _fw_log("drawdocprops.py:store picture", _fw_err)
    return n


def _svg_path(svg):
    """A QPainterPath of a view's SVG lines (TechDraw's M, L, C, Q and circular A commands)."""
    import math as _m
    import re as _re
    path = QtGui.QPainterPath()
    for d in _re.findall(r'd="([^"]*)"', svg):
        toks = _re.findall(r"[MLCQAZmlcqaz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", d)
        i, cmd, cur = 0, None, QtCore.QPointF(0, 0)

        def num():
            nonlocal i
            v = float(toks[i])
            i += 1
            return v
        while i < len(toks):
            if toks[i].isalpha():
                cmd = toks[i].upper()
                i += 1
                if cmd == "Z":
                    path.closeSubpath()
                continue
            try:
                if cmd == "M":
                    cur = QtCore.QPointF(num(), num())
                    path.moveTo(cur)
                    cmd = "L"
                elif cmd == "L":
                    cur = QtCore.QPointF(num(), num())
                    path.lineTo(cur)
                elif cmd == "C":
                    a, b, cur = QtCore.QPointF(num(), num()), QtCore.QPointF(num(), num()), QtCore.QPointF(num(), num())
                    path.cubicTo(a, b, cur)
                elif cmd == "Q":
                    a, cur = QtCore.QPointF(num(), num()), QtCore.QPointF(num(), num())
                    path.quadTo(a, cur)
                elif cmd == "A":
                    rx, ry, _rot, large, sweep, x, y = num(), num(), num(), num(), num(), num(), num()
                    p0, p1 = cur, QtCore.QPointF(x, y)
                    r = max(rx, ry)
                    dx, dy = (p1.x() - p0.x()) / 2.0, (p1.y() - p0.y()) / 2.0
                    dd = _m.hypot(dx, dy)
                    if r <= 0 or dd < 1e-12:
                        path.lineTo(p1)
                    else:
                        r = max(r, dd)
                        h = _m.sqrt(max(r * r - dd * dd, 0.0))
                        mx, my = (p0.x() + p1.x()) / 2.0, (p0.y() + p1.y()) / 2.0
                        ux, uy = -dy / dd, dx / dd
                        sgn = 1.0 if bool(large) != bool(sweep) else -1.0
                        cx, cy = mx + sgn * h * ux, my + sgn * h * uy
                        a0 = _m.atan2(p0.y() - cy, p0.x() - cx)
                        a1 = _m.atan2(p1.y() - cy, p1.x() - cx)
                        da = a1 - a0
                        if sweep and da < 0:
                            da += 2 * _m.pi
                        elif not sweep and da > 0:
                            da -= 2 * _m.pi
                        steps = max(8, int(abs(da) * 24))
                        for k in range(1, steps + 1):
                            t = a0 + da * k / steps
                            path.lineTo(cx + r * _m.cos(t), cy + r * _m.sin(t))
                    cur = p1
                else:
                    i += 1
            except (IndexError, ValueError):
                break
    return path


def show_last_pictures(doc):
    """The views that draw nothing (model missing) show their last saved lines on the sheet, until the drawing
    is opened again with its model back. Plain path items (no QObject): the sheet's scene owns them and they go
    with it. Returns how many were shown."""
    if doc is None or not App.GuiUp:
        return 0
    try:
        import TechDrawGui
    except Exception as _fw_err:
        _fw_log("drawdocprops.py:pictures gui", _fw_err)
        return 0
    n = 0
    for v in doc.Objects:
        try:
            pic = str(getattr(v, "SWLastPicture", "") or "")
            if not pic or not v.isDerivedFrom("TechDraw::DrawViewPart") or v.getVisibleEdges():
                continue
            page = next((o for o in v.InList if o.TypeId == "TechDraw::DrawPage"), None)
            if page is None:
                continue
            _head, svg = pic.split("|", 1)
            scene = TechDrawGui.getSceneForPage(page)
            if scene is None:
                continue
            if any(str(it.data(1) or "") == "SWLastPicture:" + v.Name for it in scene.items()):
                continue
            group = next((it for it in scene.items() if it.data(1) == v.Name), None)
            at = group.scenePos() if group is not None else D.to_scene(float(v.X), float(v.Y))
            item = QtWidgets.QGraphicsPathItem(_svg_path(svg))
            pen = QtGui.QPen(QtGui.QColor("#000000"))
            pen.setWidthF(0.35)
            item.setPen(pen)
            item.setScale(10.0)                       # the sheet's scene draws 10 units to the mm
            item.setPos(at)
            item.setToolTip("Last saved view of %s: the model is not found" % v.Label)
            item.setData(1, "SWLastPicture:" + v.Name)
            scene.addItem(item)
            n += 1
        except Exception as _fw_err:
            _fw_log("drawdocprops.py:show picture", _fw_err)
    return n


def warn_missing_models(dname):
    ""

    try:
        doc = App.getDocument(dname) if dname in App.listDocuments() else None
        gone = missing_models(doc)
    except Exception as _fw_err:
        _fw_log("drawdocprops.py:missing models", _fw_err)
        return
    if not gone:
        return
    for v, f in gone:
        try:
            if "SWModelMissing" not in v.PropertiesList:
                v.addProperty("App::PropertyString", "SWModelMissing", "FreeCAD", "the model file this view cannot find")
            v.SWModelMissing = f
            if not str(v.Label2).startswith("Model not found"):
                v.Label2 = "Model not found: %s" % f
        except Exception as _fw_err:
            _fw_log("drawdocprops.py:mark missing", _fw_err)
    try:
        show_last_pictures(doc)
    except Exception as _fw_err:
        _fw_log("drawdocprops.py:last pictures", _fw_err)
    files = sorted(set(f for _v, f in gone))
    text = ("The drawing's model cannot be found:\n\n%s\n\nThe view%s %s as last saved until the file is back in "
            "that folder. Nothing in the drawing is lost: put the file back and open the drawing again."
            % ("\n".join(files), "s" if len(gone) > 1 else "", "show" if len(gone) > 1 else "shows"))
    App.Console.PrintWarning("FreeCAD: %s: model not found: %s\n" % (doc.Label, ", ".join(files)))
    if App.GuiUp:
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning, "FreeCAD", text, QtWidgets.QMessageBox.Ok,
                                    Gui.getMainWindow())
        box.setObjectName("SWModelMissingBox")
        box.setModal(False)
        box.show()


def _remake_pictures(dname):
    """A drawing saved with reduced display data: its shaded views' pictures made again."""
    try:
        from . import drawshade
        drawshade.remake_missing(App.getDocument(dname))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: shaded pictures on open: %s\n" % error)


STACKED = {"DistanceX": "Y", "DistanceY": "X", "Distance": None}


def _stack_info(dim):
    """(doc name, view name, type, axis, offset, name) of a linear dimension, for Reduce spacing."""
    refs = dim.References2D or []
    if not refs or dim.Type not in ("DistanceX", "DistanceY"):
        return None
    axis = STACKED[dim.Type]
    return (dim.Document.Name, refs[0][0].Name, dim.Type, axis, float(getattr(dim, axis)), dim.Name)


def reduce_spacing(dname, vname, kind, axis, at, gone):
    """Document Properties > Dimensions > Reduce spacing when dimensions are deleted: the dimensions stacked
    beyond the deleted one (same view, same direction, same side) close up, each taking the place of the one
    before it. Returns the dimensions moved."""
    try:
        doc = App.getDocument(dname)
    except Exception:
        return []
    side = 1 if at >= 0 else -1
    stack = []
    for o in doc.Objects:
        if o.Name == gone or o.TypeId != "TechDraw::DrawViewDimension" or o.Type != kind:
            continue
        refs = o.References2D or []
        if not refs or refs[0][0].Name != vname:
            continue
        off = float(getattr(o, axis))
        if off * side > at * side:
            stack.append((off * side, o))
    stack.sort(key=lambda t: t[0])
    place, moved = at, []
    for off, o in stack:
        if getattr(o, "LockPosition", False):
            break
        old = off * side
        setattr(o, axis, place)
        moved.append(o)
        place = old
    if moved:
        doc.recompute()
    return moved


def auto_update_on_open():
    """System Options > Drawings > Performance > Allow auto-update when opening drawings."""
    return bool(D.system_option("Performance", "Allow auto-update when opening drawings", True))


def hold_on_open(dname):
    """With auto-update off, an opened drawing's sheets keep what was saved until a rebuild (Ctrl+B or Update)."""
    try:
        doc = App.getDocument(dname)
    except Exception:
        return
    if auto_update_on_open():
        return
    for o in doc.Objects:
        if o.TypeId != "TechDraw::DrawPage" or getattr(o, "SWDetailing", False):
            continue
        if "SWHeldOnOpen" not in o.PropertiesList:
            o.addProperty("App::PropertyBool", "SWHeldOnOpen", "FreeCAD", "views wait for a rebuild")
        o.SWHeldOnOpen = True
        o.KeepUpdated = False


def held(doc):
    return [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage" and getattr(o, "SWHeldOnOpen", False)]


def release(doc):
    """The rebuild that brings held sheets up to date."""
    pages = held(doc)
    for p in pages:
        p.SWHeldOnOpen = False
        p.KeepUpdated = True
    if pages:
        for o in doc.Objects:
            if o.isDerivedFrom("TechDraw::DrawView"):
                o.touch()
        doc.recompute()
    return bool(pages)


# --------------------------------------------------------------------------- broken dimensions
def _gaps(view, horizontal):
    """The empty bands of a broken view (view geometry, along x when horizontal else y): where its pieces part."""
    spans = []
    i = 0
    while True:
        try:
            e = view.getEdgeByIndex(i)
        except Exception as _fw_err:
            _fw_log("drawdocprops.py:1095", _fw_err)
            break
        i += 1
        bb = e.BoundBox
        spans.append((bb.XMin, bb.XMax) if horizontal else (bb.YMin, bb.YMax))
    spans.sort()
    out, reach = [], None
    for lo, hi in spans:
        if reach is not None and lo > reach + 0.5:
            out.append((reach, lo))
        reach = hi if reach is None else max(reach, hi)
    return out


def _dim_ends(dim):
    from . import drawannot as DA
    view = dim.References2D[0][0] if dim.References2D else None
    pts = []
    for sub in (dim.References2D[0][1] if dim.References2D else []):
        try:
            if sub.startswith("Vertex"):
                p = view.getVertexByIndex(int(sub[6:])).Point
                pts.append((p.x, p.y))
            elif sub.startswith("Edge"):
                e = view.getEdgeByIndex(int(sub[4:]))
                for v in (e.Vertexes[0], e.Vertexes[-1]):
                    pts.append((v.Point.x, v.Point.y))
        except Exception as _fw_err:
            _fw_log("drawdocprops.py:1112", _fw_err)
    return view, pts


def _broken_later(dname, name, tries):
    try:
        doc = App.getDocument(dname)
        obj = doc.getObject(name)
    except Exception:
        return
    if obj is None:
        return
    if not obj.References2D:
        if tries < 20:
            QtCore.QTimer.singleShot(100, lambda: _broken_later(dname, name, tries + 1))
        return
    paint_driven(obj)
    if any(r[0].TypeId == "TechDraw::DrawBrokenView" for r in obj.References2D):
        doc.recompute()
        broken_marks(doc)


def broken_marks(doc):
    """Show dimensions as broken in break views: a zigzag on each linear dimension line where it crosses a break
    gap of its broken view (kept as sheet symbols SWBrokenDimMark, made again on each call)."""
    from . import drawannot as DA
    from . import drawviews as DV
    for o in [o for o in doc.Objects if getattr(o, "SWAnnotation", "") == "BrokenDimMark"]:
        try:
            doc.removeObject(o.Name)
        except Exception as _fw_err:
            _fw_log("drawdocprops.py:1143", _fw_err)
    made = []
    for dim in [o for o in doc.Objects if o.TypeId == "TechDraw::DrawViewDimension"]:
        if dim.Type not in ("DistanceX", "DistanceY", "Distance"):
            continue
        view, pts = _dim_ends(dim)
        if view is None or view.TypeId != "TechDraw::DrawBrokenView" or len(pts) < 2:
            continue
        page = next((p for p in view.InList if p.TypeId == "TechDraw::DrawPage"), None)
        if page is None or not row(doc, "Dimensions", "Show dimensions as broken in break views", True,
                                   "dim_broken"):
            continue
        horizontal = dim.Type == "DistanceX" or (dim.Type == "Distance" and abs(pts[1][0] - pts[0][0]) >=
                                                 abs(pts[1][1] - pts[0][1]))
        a, b = sorted((pts[0][0], pts[-1][0]) if horizontal else (pts[0][1], pts[-1][1]))
        k = DV.view_scale(view)
        x0, y0 = D.view_position(view)
        for lo, hi in _gaps(view, horizontal):
            if not (a < lo and hi < b):
                continue
            c = (lo + hi) / 2.0
            at = (x0 + c * k, y0 + float(dim.Y)) if horizontal else (x0 + float(dim.X), y0 + c * k)
            body = ('<polyline points="-2,0 -0.8,0 -0.3,-1.5 0.3,1.5 0.8,0 2,0" fill="none" stroke="#000" '
                    'stroke-width="0.25"%s/>' % ("" if horizontal else ' transform="rotate(90)"'))
            m = DA.svg_symbol(page, "BrokenDimMark", '<rect x="-1.2" y="-2" width="2.4" height="4" fill="#fff"/>' + body,
                              2.5, at, "Broken dimension %s" % dim.Label, "BrokenDimMark")
            made.append(m)
    return made


def _on_current_layer(dname, name):
    ""
    try:
        doc = App.getDocument(dname)
        obj = doc.getObject(name)
        cur = P.current_layer(doc)
        if obj is None or getattr(obj, "SWLayer", "") or cur == P.NONE_LAYER or P.layer(doc, cur) is None:
            return
        P.apply_layer(obj, cur)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: current layer: %s\n" % error)


def _default_label(dname, name, tries):
    try:
        doc = App.getDocument(dname)
        obj = doc.getObject(name)
    except Exception:
        return
    if obj is None or stored(doc):
        return                          # set meanwhile: _created labels it from the stored values
    if not (getattr(obj, "SectionSymbol", "") or getattr(obj, "Reference", "")):
        if tries < 20:
            QtCore.QTimer.singleShot(150, lambda: _default_label(dname, name, tries + 1))
        return
    try:
        if not str(getattr(obj, "Caption", "") or "").strip():
            label_view(obj, defaults())
    except Exception as error:
        _fw_log("drawdocprops.py:default_label", error)


def _created(dname, name, tries):
    try:
        doc = App.getDocument(dname)
        obj = doc.getObject(name)
    except Exception:
        return
    if obj is None:
        return
    v = dict(defaults(), **stored(doc))
    try:
        if obj.TypeId == "TechDraw::DrawViewDimension":
            if not obj.References2D and tries < 20:
                QtCore.QTimer.singleShot(100, lambda: _created(dname, name, tries + 1))
                return
            apply_dimension(obj, v)
            paint_driven(obj)
            if any(r[0].TypeId == "TechDraw::DrawBrokenView" for r in obj.References2D):
                broken_marks(doc)
        elif obj.TypeId == "TechDraw::DrawViewSpreadsheet":
            apply_table(obj, v)
        else:
            apply_view(obj, v)
            draft = draft_new_views(doc)
            if draft and hasattr(obj, "CoarseView") and tries == 0:
                obj.CoarseView = True          # else System Options > Display Style decides (drawings.new_view)
            if obj.TypeId in LABEL_OF:
                if not (getattr(obj, "SectionSymbol", "") or getattr(obj, "Reference", "")) and tries < 20:
                    QtCore.QTimer.singleShot(150, lambda: _created(dname, name, tries + 1))
                    return
                label_view(obj, v)
            elif obj.TypeId in ("TechDraw::DrawViewPart", "TechDraw::DrawProjGroupItem"):
                if v.get("lbl_ortho_on") or v.get("lbl_other_on"):
                    QtCore.QTimer.singleShot(400, lambda: _plain_label_later(dname, name))
                QtCore.QTimer.singleShot(300, lambda: _auto_insert(dname, name, 0))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Document Properties (new %s): %s\n" % (name, error))


AUTO_KEYS = ("auto_holes", "auto_fillets", "auto_slots", "auto_holes_asm", "auto_fillets_asm", "auto_slots_asm",
             "auto_centerlines", "auto_threads", "auto_dims", "auto_balloons")


def _assembly_view(view):
    ""

    from . import drawviews as DV
    try:
        return any(o.TypeId.startswith("Assembly::") or o.TypeId == "App::Part" for o in DV.source_shapes(view))
    except Exception:
        return False


def _marked(view):
    """The model points of the view's center marks (SWCenterMarkAnchors)."""
    out = []
    for row in list(getattr(view, "SWCenterMarkAnchors", []) or []):
        try:
            out.append(App.Vector(*[float(t) for t in row.split("|")[1].split(",")]))
        except Exception:
            pass
    return out


def _has_mark(view, have, c):
    """True when the view already has a center mark at view point c (auto insert never marks a hole twice)."""
    try:
        # a live mark already centred there (view coordinates): the model point can be stale when the part
        # changed before this delayed auto insert ran (drawings-land282: e2e242 got two marks per hole)
        for t in list(getattr(view, "SWCenterMarks", []) or []):
            ce = view.getCosmeticEdge(t)
            if ce is not None and abs((ce.Start.x + ce.End.x) / 2 - c.x) < 1e-3 and \
                    abs((ce.Start.y + ce.End.y) / 2 - c.y) < 1e-3:
                return True
    except Exception as _fw_err:
        _fw_log("drawdocprops.py:has_mark", _fw_err)
    if not have:
        return False
    try:
        from . import drawings as D, drawviews as DV
        _d, x, y = D.view_frame(view)
        p = DV.model_centre(view) + x * c.x + y * c.y
        return any((p - q).Length < 1e-3 for q in have)
    except Exception as _fw_err:
        _fw_log("drawdocprops.py:has_mark", _fw_err)
        return False


def auto_insert(view, v):
    """Detailing > Auto insert on view creation."""
    from . import drawannot as DA
    page = None
    for o in view.InList:
        if o.TypeId == "TechDraw::DrawPage":
            page = o
        elif o.TypeId == "TechDraw::DrawProjGroup":
            page = next((p for p in o.InList if p.TypeId == "TechDraw::DrawPage"), page)
    if page is None:
        return []
    done = []
    sfx = "_asm" if _assembly_view(view) else ""
    on = {k: bool(v.get(k + sfx, False)) for k in ("auto_holes", "auto_fillets", "auto_slots")}
    kinds = DA.round_edges(view) if any(on.values()) else {}

    # share one mark, sized on the outer circle
    marks = {}

    def want(c, r):
        key = (round(c.x, 4), round(c.y, 4))
        if key not in marks or r > marks[key][1]:
            marks[key] = (c, r)
    for key, kind in (("auto_holes", "holes"), ("auto_fillets", "fillets")):
        if on[key]:
            for _i, c, r in kinds.get(kind, []):
                want(c, r)
            done.append(kind)
    if on["auto_slots"]:
        for pair in kinds.get("slots", []):
            for _i, c, r in pair:
                want(c, r)
        done.append("slots")
    have = _marked(view)
    for c, r in marks.values():
        if not _has_mark(view, have, c):
            DA.center_mark(view, c, r)
    if v["auto_centerlines"]:
        DA.auto_centerlines(view)
        done.append("centerlines")
    if v["auto_threads"]:
        DA.cosmetic_threads(page, [view])
        done.append("threads")
    if v["auto_dims"]:
        DA.model_items(page, [view])
        done.append("dimensions")
    if v["auto_balloons"]:
        try:
            DA.auto_balloon(page, view)
            done.append("balloons")
        except Exception as _fw_err:
            _fw_log("drawdocprops.py:1287", _fw_err)
    view.Document.recompute()
    return done


_RESTORED = set()


def _auto_insert(dname, name, tries):
    if (dname, name) in _RESTORED:
        _RESTORED.discard((dname, name))
        return
    try:
        doc = App.getDocument(dname)
        view = doc.getObject(name)
    except Exception:
        return
    if view is None:
        return
    v = dict(defaults(), **stored(doc))
    if not any(v[k] for k in AUTO_KEYS):
        return
    from . import drawannot as DA
    if not DA.edges(view) and tries < 30:
        QtCore.QTimer.singleShot(200, lambda: _auto_insert(dname, name, tries + 1))
        return
    try:
        with DA.quiet_view(view):           # one redraw of the view at the end, not one per line
            auto_insert(view, v)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Auto insert: %s\n" % error)


_OBSERVER = []


def start():
    if not _OBSERVER:
        _OBSERVER.append(_Observer())
        App.addDocumentObserver(_OBSERVER[0])
        try:
            from . import drawdetail         # Detailing mode data written on save
            drawdetail.install()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Detailing mode data: %s\n" % error)
        try:
            from . import restorehook        # "the file has opened", as FreeCAD 1.1 sends it
            restorehook.on_restored(_restored)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Document Properties on open: %s\n" % error)


# --------------------------------------------------------------------------- Line Style page
class _LineStyleEditor(QtWidgets.QWidget):
    ""

    def __init__(self, own, parent=None):
        super().__init__(parent)
        self._own = dict(own)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = QtWidgets.QListWidget(self)
        self.list.setObjectName("SWDPLineStyleList")
        lay.addWidget(self.list)
        form = QtWidgets.QFormLayout()
        self.pattern = QtWidgets.QLineEdit(self)
        self.pattern.setObjectName("SWDPLineStylePattern")
        self.pattern.setToolTip("Line length and spacing values in mm: dash, gap, dash, gap... (empty = solid)")
        form.addRow("Line length and spacing values:", self.pattern)
        self.preview = QtWidgets.QLabel(self)
        self.preview.setObjectName("SWDPLineStylePreview")
        self.preview.setMinimumHeight(18)
        form.addRow("Preview:", self.preview)
        lay.addLayout(form)
        row_ = QtWidgets.QHBoxLayout()
        self.new_b = QtWidgets.QPushButton("New...", self)
        self.new_b.setObjectName("SWDPLineStyleNew")
        self.del_b = QtWidgets.QPushButton("Delete", self)
        self.del_b.setObjectName("SWDPLineStyleDelete")
        self.load_b = QtWidgets.QPushButton("Load...", self)
        self.load_b.setObjectName("SWDPLineStyleLoad")
        self.save_b = QtWidgets.QPushButton("Save...", self)
        self.save_b.setObjectName("SWDPLineStyleSave")
        for b in (self.new_b, self.del_b, self.load_b, self.save_b):
            row_.addWidget(b)
        row_.addStretch(1)
        lay.addLayout(row_)
        self.note = QtWidgets.QLabel("", self)            # no greyed Delete: the button says why it did nothing
        self.note.setObjectName("SWDPLineStyleNote")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self.new_b.clicked.connect(self.new_style)
        self.del_b.clicked.connect(self.delete_style)
        self.load_b.clicked.connect(self.load_styles)
        self.save_b.clicked.connect(self.save_styles)
        self.list.currentTextChanged.connect(self._show)
        self.pattern.editingFinished.connect(self._edited)
        self._fill()

    def styles(self):
        out = {k: P.DASHES.get(k, "") for k in BUILTIN_STYLES}
        out.update(self._own)
        return out

    def own(self):
        self._edited()
        return dict(self._own)

    def set_own(self, own):
        self._own = dict(own)
        self._fill()

    def _fill(self, pick=None):
        self.list.blockSignals(True)
        self.list.clear()
        self.list.addItems(list(self.styles()))
        self.list.blockSignals(False)
        names = list(self.styles())
        self.list.setCurrentRow(names.index(pick) if pick in names else 0)
        self._show(self.list.currentItem().text() if self.list.currentItem() else "")

    def _show(self, name):
        builtin = name in BUILTIN_STYLES
        self.pattern.setText(self.styles().get(name, ""))
        self.pattern.setReadOnly(builtin)
        self.note.setText("A built-in style cannot be changed or deleted: New... makes your own from it." if builtin else "")
        self._draw(self.pattern.text())

    def _draw(self, pattern):
        from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
        pix = _hidpi.canvas(240, 12)
        pix.fill(QtCore.Qt.white)
        p = QtGui.QPainter(pix)
        pen = QtGui.QPen(QtCore.Qt.black, 2)
        try:
            nums = [float(x) for x in _pattern(pattern).split(",") if x]
        except Exception:
            nums = []
        if nums:
            pen.setDashPattern([max(0.1, n * 4 / 2.0) for n in nums])
        p.setPen(pen)
        p.drawLine(4, 6, 236, 6)
        p.end()
        self.preview.setPixmap(pix)

    def _edited(self):
        it = self.list.currentItem()
        if it is None or it.text() in BUILTIN_STYLES:
            return
        try:
            self._own[it.text()] = _pattern(self.pattern.text())
        except Exception:
            self.pattern.setText(self._own.get(it.text(), ""))
        self._draw(self.pattern.text())

    def new_style(self):
        name = ASK.pop("style_name", None)
        if name is None:
            name, ok = QtWidgets.QInputDialog.getText(self, "New Line Style", "Name:")
            if not ok:
                return None
        name = str(name).strip()
        if not name or name in self.styles():
            return None
        self._own[name] = "4,1"
        self._fill(name)
        return name

    def save_styles(self):
        """Save...: the drawing's own line styles to a line style file (.fwlin)."""
        path = ASK.pop("lin_save_path", None)
        if path is None:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Line Styles", "linestyles.fwlin", LIN_FILTER)
        if not path:
            return None
        if not path.lower().endswith(".fwlin"):
            path += ".fwlin"
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"FreeWorksLineStyles": 1, "styles": self.own()}, f, indent=1, sort_keys=True)
        return path

    def load_styles(self):
        """Load...: the styles of a line style file join the drawing's (same names are replaced)."""
        path = ASK.pop("lin_load_path", None)
        if path is None:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load Line Styles", "", LIN_FILTER)
        if not path:
            return None
        try:
            with open(path, encoding="utf-8") as f:
                styles = json.load(f).get("styles", {})
            got = {str(k): _pattern(v) for k, v in styles.items() if str(k) not in BUILTIN_STYLES}
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, "Line Style", "Could not load %s:\n%s" % (path, error))
            return None
        self._own.update(got)
        self._fill(next(iter(got), None))
        return got

    def delete_style(self):
        it = self.list.currentItem()
        if it is None:
            return None
        if it.text() in BUILTIN_STYLES:
            self.note.setText("Built-in line styles cannot be deleted.")
            return None
        name = it.text()
        self._own.pop(name, None)
        self._fill()
        return name


# --------------------------------------------------------------------------- the dialog
class DocumentPropertiesDialog(QtWidgets.QDialog):
    """Document Properties for the drawing: the page tree on the left, the page on the right."""

    def __init__(self, doc, parent=None, start_page=None):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc
        self.setObjectName("SWDocProps")
        self.setWindowTitle("Document Properties - %s" % (stored(doc).get("std_name") or prop(doc, "standard")))
        self.values = dict(defaults(), **stored(doc))
        self.values["units"] = units(doc)
        try:
            from . import optionspages as OP
            for key, default in defaults().items():
                if key.startswith(ROW):
                    page, text = _row_key(key)
                    v = OP.doc_value(doc, page, text, default)
                    self.values[key] = float(v) if isinstance(default, float) else v
        except Exception as _fw_err:
            _fw_log("drawdocprops.py:part rows", _fw_err)
        self.widgets = {}
        outer = QtWidgets.QVBoxLayout(self)
        split = QtWidgets.QHBoxLayout()
        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setObjectName("SWDocPropsTree")
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(220)
        self.stack = QtWidgets.QStackedWidget(self)
        self.stack.setObjectName("SWDocPropsPages")
        split.addWidget(self.tree)
        split.addWidget(self.stack, 1)
        outer.addLayout(split, 1)
        self.items = {}
        self._add(pages(), self.tree.invisibleRootItem())
        self.tree.expandAll()
        self.tree.currentItemChanged.connect(lambda it, _old: it is not None and self.stack.setCurrentIndex(
            it.data(0, QtCore.Qt.UserRole)))
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.ok)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)
        self.tree.setCurrentItem(self.items.get(start_page) or self.tree.topLevelItem(0))
        self._loading = False
        if "standard" in self.widgets:
            self.widgets["standard"][1].currentTextChanged.connect(self.standard_changed)
        self.resize(820, 560)

    def standard_changed(self, name):
        """Another overall drafting standard: the pages under it take that standard's values."""
        if self._loading:
            return
        for k, val in standard_preset(name).items():
            if k in self.widgets:
                self.put(k, val)
        self.std_name = None
        self.values.pop("std_name", None)
        self.setWindowTitle("Document Properties - %s" % name)

    def _add(self, items, parent):
        for title, groups, children in items:
            it = QtWidgets.QTreeWidgetItem(parent, [title])
            page = QtWidgets.QWidget(self.stack)
            page.setObjectName("SWDocPropsPage_" + re.sub(r"\W", "", title))
            lay = QtWidgets.QVBoxLayout(page)
            for heading, ss in groups:
                box = QtWidgets.QGroupBox(heading or "", page)
                bl = QtWidgets.QFormLayout(box)
                for s in ss:
                    w = self._widget(s, box)
                    if s["kind"] == "bool":
                        bl.addRow(w)
                    else:
                        bl.addRow(s["text"] + ":", w)
                lay.addWidget(box)
            if not groups:
                lay.addWidget(QtWidgets.QLabel("See the pages under %s." % title, page))
            if title == "Drafting Standard":
                row_ = QtWidgets.QHBoxLayout()
                for text, name, fn in (("Rename...", "SWDPStdRename", self.rename_standard),
                                       ("Load From External File...", "SWDPStdLoad", self.load_standard),
                                       ("Save to External File...", "SWDPStdSave", self.save_standard)):     # optl24 L4
                    b = QtWidgets.QPushButton(text, page)
                    b.setObjectName(name)
                    b.clicked.connect(fn)
                    row_.addWidget(b)
                row_.addStretch(1)
                lay.insertLayout(1, row_)
            lay.addStretch(1)
            # in a scroll area, as the Options box's own pages: Dimensions alone is 900 px tall, which put
            # Options' OK and Cancel below a 768 px screen
            scroll = QtWidgets.QScrollArea(self.stack)
            scroll.setObjectName("SWDocPropsScroll_" + re.sub(r"\W", "", title))
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            scroll.setWidget(page)
            it.setData(0, QtCore.Qt.UserRole, self.stack.addWidget(scroll))
            self.items[title] = it
            self._add(children, it)

    def _widget(self, s, parent):
        key, kind, val = s["key"], s["kind"], self.values.get(s["key"], s["default"])
        if kind == "bool":
            w = QtWidgets.QCheckBox(s["text"], parent)
            w.setChecked(bool(val))
        elif kind == "combo":
            w = QtWidgets.QComboBox(parent)
            w.addItems([str(x) for x in s["more"]])
            if key == "units":
                for i, (t, u) in enumerate(UNIT_SYSTEMS):
                    w.setItemText(i, t)
                w.setCurrentIndex([u for _t, u in UNIT_SYSTEMS].index(val) if val in [u for _t, u in UNIT_SYSTEMS]
                                  else 2)
            else:
                w.setCurrentText(str(val))
        elif kind == "num":
            lo, hi, unit = s["more"]
            w = QtWidgets.QDoubleSpinBox(parent)
            w.setRange(lo, hi)
            w.setDecimals(2)
            if unit:
                w.setSuffix(unit)
            w.setValue(float(val))
        elif kind == "linestyles":
            w = _LineStyleEditor(dict(val or {}), parent)
        elif kind == "color":
            w = _ColorButton(str(val or s["default"]), s["text"], parent)
        else:
            w = QtWidgets.QLineEdit(str(val), parent)
        w.setObjectName("SWDP_" + re.sub(r"[^A-Za-z0-9_]", "_", key))
        self.widgets[key] = (s, w)
        return w

    def read(self):
        out = {}
        for key, (s, w) in self.widgets.items():
            if s["kind"] == "bool":
                out[key] = bool(w.isChecked())
            elif s["kind"] == "combo":
                out[key] = UNIT_SYSTEMS[w.currentIndex()][1] if key == "units" else w.currentText()
            elif s["kind"] == "num":
                out[key] = float(w.value())
            elif s["kind"] == "linestyles":
                out[key] = w.own()
            elif s["kind"] == "color":
                out[key] = w.color
            else:
                out[key] = w.text()
        return out

    def widget(self, key):
        return self.widgets[key][1]

    def put(self, key, val):
        """A value into its widget (Load From External File)."""
        s, w = self.widgets[key]
        if s["kind"] == "bool":
            w.setChecked(bool(val))
        elif s["kind"] == "combo":
            if key == "units":
                units = [u for _t, u in UNIT_SYSTEMS]
                if val in units:
                    w.setCurrentIndex(units.index(val))
            elif w.findText(str(val)) >= 0:
                w.setCurrentText(str(val))
        elif s["kind"] == "num":
            w.setValue(float(val))
        elif s["kind"] == "linestyles":
            w.set_own(dict(val or {}))
        elif s["kind"] == "color":
            w.set_color(str(val))
        else:
            w.setText(str(val))

    def save_standard(self):
        path = ASK.pop("std_save_path", None)
        if path is None:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save to External File",
                                                            str(self.read().get("standard")) + ".fwstd", STD_FILTER)
        if not path:
            return None
        if not path.lower().endswith(".fwstd"):
            path += ".fwstd"
        return save_standard(self.read(), path)

    def load_standard(self):
        path = ASK.pop("std_load_path", None)
        if path is None:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load From External File", "", STD_FILTER)
        if not path:
            return None
        try:
            values = load_standard(path)
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, "Document Properties", "Could not load %s:\n%s" % (path, error))
            return None
        self._loading = True
        try:
            for k, v in values.items():
                if k in self.widgets:
                    self.put(k, v)
        finally:
            self._loading = False
        return values

    def rename_standard(self):
        ""
        name = ASK.pop("std_name", None)
        if name is None:
            name, ok = QtWidgets.QInputDialog.getText(self, "Rename", "Drafting standard name:",
                                                      text=str(self.values.get("std_name") or ""))
            if not ok:
                return None
        self.std_name = str(name).strip()
        self.setWindowTitle("Document Properties - %s" % (self.std_name or self.read().get("standard")))
        return self.std_name

    def ok(self):
        self.doc.openTransaction("Document Properties")
        try:
            values = self.read()
            rows = {k: values.pop(k) for k in list(values) if k.startswith(ROW)}
            if rows:
                from . import optionspages as OP
                meta = dict(self.doc.Meta)
                for k, v in rows.items():
                    page, text = _row_key(k)
                    meta[OP.DOC_META + OP._store_key(page, text)] = ("1" if v else "0") if isinstance(v, bool) else \
                        ("%g" % v if isinstance(v, float) else str(v))
                self.doc.Meta = meta
            name = getattr(self, "std_name", None)
            if name is not None:
                values["std_name"] = name
            elif self.values.get("std_name"):
                values["std_name"] = self.values["std_name"]
            set_props(self.doc, values)
            apply_all(self.doc)
        finally:
            self.doc.commitTransaction()
        self.accept()


def document_properties(doc=None, start_page=None):
    if doc is None:
        page = D.active_page()
        doc = page.Document if page is not None else None
    if doc is None:
        return None
    show = _options_box(doc)
    if show is not None:
        def bind(tries=40):
            from . import options
            box = options._open[-1] if getattr(options, "_open", None) else None
            if box is not None and getattr(box, "_dd", None) is not None:
                document_properties.dialog = _InOptions(box)
            elif tries > 0:
                QtCore.QTimer.singleShot(25, lambda: bind(tries - 1))
        document_properties.dialog = None
        QtCore.QTimer.singleShot(0, bind)
        return show(doc, start_page)
    dlg = DocumentPropertiesDialog(doc, start_page=start_page)
    document_properties.dialog = dlg
    return dlg.exec_()


def _options_box(doc):
    """options.show_document_properties when the Options box shows the drawing's pages, else None."""
    try:
        from . import options
        show = getattr(options, "show_document_properties", None)
        if show is None or not hasattr(options, "drawing_properties_available"):
            return None
        if App.ActiveDocument is not doc:
            App.setActiveDocument(doc.Name)
        return show if options.drawing_properties_available(doc) else None
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Document Properties in Options: %s\n" % error)
        return None


class _InOptions(object):
    """document_properties.dialog while the pages show in the Options box: the page tree and stack are the box's,
    the widgets and their saving this module's dialog (box._dd); ok() is the box's OK."""

    def __init__(self, box):
        self.box = box

    @property
    def tree(self):
        return self.box.tree

    @property
    def stack(self):
        return self.box.stack

    @property
    def items(self):
        out = {}
        it = QtWidgets.QTreeWidgetItemIterator(self.box.tree)
        while it.value():
            out.setdefault(it.value().text(0), it.value())
            it += 1
        return out

    def windowTitle(self):
        return self.box.windowTitle()

    def findChild(self, *args):
        return self.box.findChild(*args)

    def findChildren(self, *args):
        return self.box.findChildren(*args)

    def ok(self):
        self.box.accept()

    def accept(self):
        self.box.accept()

    def reject(self):
        self.box.reject()

    def __getattr__(self, name):
        return getattr(self.box._dd, name)


# --------------------------------------------------------------------------- Virtual Sharps
def _intersect(a1, b1, a2, b2):
    d1, d2 = b1 - a1, b2 - a2
    den = d1.x * d2.y - d1.y * d2.x
    if abs(den) < 1e-12:
        return None
    t = ((a2.x - a1.x) * d2.y - (a2.y - a1.y) * d2.x) / den
    return App.Vector(a1.x + d1.x * t, a1.y + d1.y * t, 0)


def sharp_style(doc):
    return row(doc, "Virtual Sharps", "Virtual sharp style", "Witness lines", "sharp_style")


def virtual_sharp(view, a1, b1, a2, b2, style="Witness lines"):
    """A virtual sharp where two lines (view coordinates) would meet: a point to dimension to, drawn in the
    document's style. Returns (point, cosmetic tags)."""
    from . import drawannot as DA
    p = _intersect(a1, b1, a2, b2)
    if p is None:
        raise ValueError("the lines are parallel")
    tags = [view.makeCosmeticVertex(p)]
    s = 1.5
    if style == "Witness lines":
        for a, b in ((a1, b1), (a2, b2)):
            near = a if (a - p).Length < (b - p).Length else b
            u = p - near
            if u.Length > 1e-9:
                u = u * (1.0 / u.Length)
                tags.append(view.makeCosmeticLine(near, p + u * s))
    if style in ("Plus", "Plus with lines", "Cross", "Star"):
        angles = {"Cross": (45, 135), "Star": (0, 60, 120)}.get(style, (0, 90))
        for ang in angles:
            r = math.radians(ang)
            d = App.Vector(math.cos(r) * s, math.sin(r) * s, 0)
            tags.append(view.makeCosmeticLine(p - d, p + d))
    if style == "Plus with lines":
        for a, b in ((a1, b1), (a2, b2)):
            near = a if (a - p).Length < (b - p).Length else b
            if (p - near).Length > 1e-9:
                tags.append(view.makeCosmeticLine(near, p))
    if style == "Dot":
        for rr in (0.35, 0.22, 0.1):                 # TechDraw circles are not filled: rings close enough to read as one
            tags.append(view.makeCosmeticCircle(p, rr))
    elif style == "Hollow dot":
        tags.append(view.makeCosmeticCircle(p, 0.5))
    DA._keep(view, "SWVirtualSharps", tags)
    return p, tags


class VirtualSharpPanel(D._Panel):
    TITLE = "Virtual Sharp"
    PIXMAP = "TechDraw_CosmeticVertex"

    def build(self):
        self.say("Click two lines in a view: a virtual sharp marks where they would meet.")
        self.first = None

    def sheet_click(self, p):
        from . import drawannot as DA, drawviews as DV
        view = DV.view_at(self.page, p)
        if view is None:
            self.say("Click a line inside a drawing view.")
            return True
        k = DV.view_scale(view)
        hit = DA.line_at(view, DV.to_geometry(view, p), 2.0 / k)
        if hit is None:
            self.say("Click on a straight edge.")
            return True
        if self.first is None or self.first[0] is not view:
            self.first = (view, hit)
            self.say("Click the second line.")
            return True
        (_, (i1, a1, b1)), (i2, a2, b2) = self.first, hit
        self.first = None
        try:
            pt, tags = virtual_sharp(view, a1, b1, a2, b2, sharp_style(self.doc))
        except ValueError as error:
            self.say("%s. Click two lines that meet." % str(error).capitalize())
            return True
        self.doc.recompute()
        self.say("Virtual sharp added. Click two more lines, or OK.")
        return True


# --------------------------------------------------------------------------- Detailing mode
def detailing(doc):
    return any(o.TypeId == "TechDraw::DrawPage" and getattr(o, "SWDetailing", False) for o in doc.Objects)


def set_detailing(doc, on):
    """Detailing mode: the sheets stop following the models (their views keep what they show); off updates them."""
    for o in doc.Objects:
        if o.TypeId != "TechDraw::DrawPage":
            continue
        if "SWDetailing" not in o.PropertiesList:
            o.addProperty("App::PropertyBool", "SWDetailing", "FreeCAD", "Detailing mode")
        o.SWDetailing = on
        o.KeepUpdated = not on
    try:
        Gui.getMainWindow().statusBar().showMessage("Detailing mode" if on else "", 0)
    except Exception as _fw_err:
        _fw_log("drawdocprops.py:1885", _fw_err)
    if not on:
        for o in doc.Objects:
            if o.isDerivedFrom("TechDraw::DrawView"):
                o.touch()
        doc.recompute()


def resolve_drawing(doc):
    """Resolve Drawing: out of Detailing mode, the views made again from their models."""
    if not detailing(doc):
        return False
    set_detailing(doc, False)
    try:
        from . import drawmaint
        for page in [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage"]:
            for v in page.Views:
                drawmaint.OUT_OF_DATE.pop((doc.Name, v.Name), None)
            drawmaint.detailing_notice(page)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Resolve Drawing: %s\n" % error)
    return True


def open_detailing(path):
    """File > Open with Mode: Detailing: the drawing opens with its sheets not following the models. A drawing saved
    with detailing mode data opens without projecting its views (drawdetail), in seconds; else it is projected once
    and held."""
    try:
        from . import drawdetail
        doc = drawdetail.open_fast(path)
        if doc is not None:
            set_detailing(doc, True)
            return doc
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Detailing mode data: %s\n" % error)
    doc = App.openDocument(path)
    set_detailing(doc, True)
    return doc


# --------------------------------------------------------------------------- commands
COMMANDS = {
    "FreeWorks_DrawDocumentProperties": ("Document Properties...", "TechDraw_PageTemplate",
                                         "The drawing's drafting standard, annotations, dimensions, views, detailing, "
                                         "sheets, grid, units and line font."),
    "FreeWorks_DrawVirtualSharp": ("Virtual Sharp", "TechDraw_CosmeticVertex",
                                   "Marks where two lines would meet, to dimension to."),
    "FreeWorks_DrawDetailingMode": ("Detailing Mode", "TechDraw_ToggleFrame",
                                    "Works on the drawing without updating its views from the models."),
    "FreeWorks_DrawResolveDrawing": ("Resolve Drawing", "TechDraw_View",
                                     "Leaves Detailing mode: the views follow their models again and are updated."),
}


class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.pixmap, self.tip = COMMANDS[name]

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": D.pixmap(self.pixmap)}

    def IsActive(self):
        page = D.active_page()
        if page is None:
            return False
        if self.name == "FreeWorks_DrawVirtualSharp":
            return bool(D.views_of(page)) and not D.busy()
        if self.name == "FreeWorks_DrawResolveDrawing":
            return detailing(page.Document)
        return True

    def Activated(self, *_):
        page = D.active_page()
        if page is None:
            return
        if self.name == "FreeWorks_DrawDocumentProperties":
            document_properties(page.Document)
        elif self.name == "FreeWorks_DrawVirtualSharp":
            D._show(VirtualSharpPanel(page))
        elif self.name == "FreeWorks_DrawResolveDrawing":
            resolve_drawing(page.Document)
        elif self.name == "FreeWorks_DrawDetailingMode":
            set_detailing(page.Document, not bool(getattr(page, "SWDetailing", False)))


def register():
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
    start()
