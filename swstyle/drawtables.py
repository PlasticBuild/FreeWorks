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

import datetime
import json
import math
import re
import string

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets
from . import drawlive as DL

from . import drawings as D
from . import drawviews as DV
from . import drawannot as DA

V = App.Vector
COLS = string.ascii_uppercase



def _fw_xs(v):
    """v's XSource as its model(s) (drawviews.xsource: an assembly view's model parts read back as the model)."""
    from . import drawviews as DV
    return DV.xsource(v)

def _cell(c, r):
    return "%s%d" % (COLS[c], r + 1)


UPPER_KINDS = ("Hole", "Revision", "BOM", "General", "TitleBlock")


def table_text(doc, rows):
    """Drafting Standard > All uppercase for tables: the drawing's own Document Properties (drawdocprops), else
    features' docstyle.table_text (which also keeps the Exclusion list)."""
    try:
        from . import drawdocprops
        if drawdocprops.prop(doc, "upper_tables"):
            try:
                from . import docstyle
                return [[docstyle.upper(str(c), drawdocprops.exclusions(doc)) for c in r] for r in rows]
            except Exception:
                return [[str(c).upper() for c in r] for r in rows]
    except Exception as _fw_err:
        _fw_log("drawtables.py:63", _fw_err)
    try:
        from . import docstyle
        return [[docstyle.table_text(doc, c) if isinstance(c, str) else c for c in r] for r in rows]
    except Exception as _fw_err:
        _fw_log("drawtables.py:69", _fw_err)
        return rows


ZERO_PAGES = {"BOM": "Bill of Materials", "TitleBlock": "Title Block Table"}


def _zeros(text, leading, trailing):
    import re as _re
    m = _re.fullmatch(r"(-?)(\d+)\.(\d+)", text.strip())
    if not m:
        return text
    sign, whole, frac = m.groups()
    if trailing == "Remove":
        frac = frac.rstrip("0")
    if leading == "Remove" and whole == "0" and frac:
        whole = ""
    return sign + whole + ("." + frac if frac else "")


def table_zeros(doc, rows, kind):
    """Document Properties > Tables (> Bill of Materials / Title Block Table): Leading zeroes, Trailing zeroes
    on the table's decimal numbers (Remove drops them; Standard / Show / Smart keep the text as written)."""
    page = ZERO_PAGES.get(kind, "Tables")
    try:
        lead = _row(doc, page, "Leading zeroes", "Standard")
        trail = _row(doc, page, "Trailing zeroes", "Smart")
    except Exception:
        return rows
    if lead != "Remove" and trail != "Remove":
        return rows
    return [r if i == 0 else [_zeros(str(c), lead, trail) for c in r] for i, r in enumerate(rows)]


def make_table(page, rows, at, label, kind, widths=None):
    """A spreadsheet holding rows (the first is the header), shown on page at sheet point at."""
    doc = page.Document
    if kind in UPPER_KINDS:
        rows = table_text(doc, rows)
    rows = table_zeros(doc, rows, kind)
    sheet = doc.addObject("Spreadsheet::Sheet", "TableData")
    sheet.Label = label + " data"
    fill(sheet, rows, widths)
    v = doc.addObject("TechDraw::DrawViewSpreadsheet", "Table")
    page.addView(v)
    v.Source = sheet
    _span(v, rows)
    v.X, v.Y = at
    v.Label = label
    v.addProperty("App::PropertyString", "SWTable", "FreeCAD", "Table kind")
    v.SWTable = kind
    hide_data(sheet)
    doc.recompute()
    _fit_columns(sheet, rows)          # now that the table (and its text size) is there
    sheet.recompute()
    doc.recompute()
    return v


def hide_data(sheet):
    ""
    try:
        sheet.ViewObject.Visibility = False
        if getattr(sheet.ViewObject, "ShowInTree", False):
            sheet.ViewObject.ShowInTree = False
    except Exception as _fw_err:
        _fw_log("drawtables.py:130", _fw_err)


def hide_all_data(doc):
    """Older drawings: hide each table's "... data" spreadsheet from the tree."""
    for o in doc.Objects:
        if o.TypeId == "TechDraw::DrawViewSpreadsheet" and getattr(o, "SWTable", None) is not None \
                and getattr(o, "Source", None) is not None:
            hide_data(o.Source)


def _span(v, rows):
    ncols = max([len(r) for r in rows] or [1])
    v.CellStart = "A1"
    v.CellEnd = _cell(ncols - 1, max(0, len(rows) - 1 + title_rows(v)))


def title_of(table):
    ""
    return str(getattr(table, "SWTitleRow", "") or "")


def title_rows(table):
    return 1 if title_of(table) else 0


def set_title(table, text):
    """A title row over the whole table width, above the header (kept as SWTitleRow)."""
    if "SWTitleRow" not in table.PropertiesList:
        table.addProperty("App::PropertyString", "SWTitleRow", "FreeCAD", "title row above the header")
    rows = rows_of(table)
    table.SWTitleRow = str(text or "")
    set_rows(table, rows)


def fill(sheet, rows, widths=None, title=""):
    # cell by cell, not clearAll(): FreeCAD 1.1 does not undo a clearAll, so Undo after a table edit
    # left the table empty
    try:
        for cell in sheet.getUsedCells():
            sheet.clear(cell)
    except Exception as _fw_err:
        _fw_log("drawtables.py:151", _fw_err)
    top = 1 if title else 0
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            text = "" if val is None else str(val)
            # a blank cell (a new General Table's " ") is kept as text: unquoted, the spreadsheet read it as the
            # number 0 and every cell of the table showed "0"
            sheet.set(_cell(c, r + top), "'" + text if text[:1] in "=+-0123456789" or (text and not text.strip())
                      else text)
    if title:

        ncols = max([len(r) for r in rows] or [1])
        sheet.set("A1", "'" + title if title[:1] in "=+-0123456789" else title)
        try:
            if ncols > 1:
                try:
                    sheet.splitCell("A1")            # merged again at the table's width
                except Exception:
                    pass
                sheet.mergeCells("A1:%s" % _cell(ncols - 1, 0))
            sheet.setStyle("A1", "bold")
            sheet.setAlignment("A1", "center|vcenter")
        except Exception as _fw_err:
            _fw_log("drawtables.py:title row", _fw_err)
    if rows:
        for c in range(len(rows[0])):
            try:
                sheet.setStyle(_cell(c, top), "bold")
                sheet.setAlignment(_cell(c, top), "center")
            except Exception as _fw_err:
                _fw_log("drawtables.py:162", _fw_err)
    for c, w in enumerate(widths or []):
        try:
            sheet.setColumnWidth(COLS[c], int(w))
        except Exception as _fw_err:
            _fw_log("drawtables.py:167", _fw_err)
    _fit_columns(sheet, rows)
    sheet.recompute()


def _text_em(text, bold=False):
    """A text's width in text heights (capitals and digits wider than lower case and stops; a bold header wider)."""
    w = sum(0.3 if ch in " .,:;'|!ilI1" else 0.72 if ch.isupper() or ch.isdigit() else 0.55 for ch in text)
    return w * (1.2 if bold else 1.0)


def _drawn(view):
    """The view has its edges (a view of a drawing being opened has none until it is computed)."""
    try:
        return bool(view.getVisibleEdges())
    except Exception:
        return False


def _fit_columns(sheet, rows):
    """A column too narrow for its longest text is widened to fit it, never narrowed (usage run 11-27: a BOM's
    VENDOR column printed MCMASTER past the table's edge). A table whose widths are locked is left alone."""
    try:
        t = next((o for o in sheet.InList if o.isDerivedFrom("TechDraw::DrawViewSpreadsheet")), None)
        if t is None or getattr(t, "SWLockColumnWidth", False):
            return
        size = float(getattr(t, "TextSize", 12.0) or 12.0)
        for c in range(max([len(r) for r in rows] or [0])):
            n = max([_text_em(str(r[c]), bold=(ri == 0)) for ri, r in enumerate(rows)
                     if c < len(r) and r[c] is not None] or [0.0])
            if not n:
                continue
            need = int(round(n * size + size * 0.8))       # the characters and a margin each side
            if sheet.getColumnWidth(COLS[c]) < need:
                sheet.setColumnWidth(COLS[c], need)
    except Exception as _fw_err:
        _fw_log("drawtables.py:fit columns", _fw_err)


def rows_of(table, physical=False):
    """The table's rows, header first (with Table Header Bottom the header is the spreadsheet's last row)."""
    rows = _rows_of(table)
    if not physical and getattr(table, "SWHeaderBottom", False) and rows:
        return rows[-1:] + rows[:-1]
    return rows


def _rows_of(table):
    sheet = table.Source
    out = []
    end = table.CellEnd
    ncols = COLS.index(end[0]) + 1
    nrows = int(end[1:])
    for r in range(title_rows(table), nrows):
        row = []
        for c in range(ncols):
            try:
                row.append(str(sheet.getContents(_cell(c, r))).lstrip("'"))
            except Exception:
                row.append("")
        out.append(row)
    return out


def set_rows(table, rows, widths=None):
    """Rows (header first) into the table; Table Header Bottom, merged cells and locked sizes are kept."""
    if getattr(table, "SWTable", "") in UPPER_KINDS:
        rows = table_text(table.Document, rows)
    if getattr(table, "SWAllUppercase", False):
        rows = upper_rows(table.Document, rows)
    still = None
    if not getattr(table, "SWAttachedToAnchor", False) and getattr(table, "SWAnchorCorner", ""):
        try:
            from . import drawtableedit
            still = (table.SWAnchorCorner, drawtableedit.corner_point(table, table.SWAnchorCorner))
        except Exception as _fw_err:
            _fw_log("drawtables.py:stationary corner", _fw_err)
    if getattr(table, "SWHeaderBottom", False) or getattr(table, "SWMerges", None) or \
            getattr(table, "SWCellFormats", ""):
        from . import drawtableedit
        drawtableedit.write(table, rows, widths)
    else:
        fill(table.Source, rows, widths, title_of(table))
        _span(table, rows)
    if getattr(table, "SWLockColumnWidth", False) or getattr(table, "SWLockRowHeight", False):
        from . import drawtableedit
        drawtableedit.keep_locks(table)
    table.Document.recompute()
    if still is not None:
        try:
            from . import drawtableedit
            drawtableedit.place_corner(table, still[0], still[1])
            table.Document.recompute()
        except Exception as _fw_err:
            _fw_log("drawtables.py:stationary corner place", _fw_err)
    if getattr(table, "SWAttachedToAnchor", False):
        try:                                   # an attached table keeps its anchor corner where it is
            from . import drawtableedit
            drawtableedit.attach_to_anchor(table)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: table anchor: %s\n" % error)


# --------------------------------------------------------------------------- Bill of Materials
BOM_TEMPLATES = ("bom-standard", "bom-material", "bom-weight")


def _material(obj):
    """The part's material name and density (kg/mm^3), from FreeCAD's ShapeMaterial, else ("", None)."""
    for o in (obj, getattr(obj, "LinkedObject", None)):
        m = getattr(o, "ShapeMaterial", None) if o is not None else None
        if m is None:
            continue
        try:
            name = m.Name or ""
            dens = None
            props = getattr(m, "PhysicalProperties", {}) or {}
            if "Density" in props:
                dens = App.Units.Quantity(props["Density"]).getValueAs("kg/mm^3").Value
            if name and name != "Default":
                return name, dens
            return "", None          # FreeCAD's Default material carries a 1e-9 placeholder density
        except Exception as _fw_err:
            _fw_log("drawtables.py:244", _fw_err)
            continue
    return "", None


def _mass(obj):
    try:
        shape = obj.Shape
        name, dens = _material(obj)
        if dens is None or dens <= 0:
            dens = 1e-6
        return shape.Volume * dens
    except Exception as _fw_err:
        _fw_log("drawtables.py:257", _fw_err)
        return None


CONFIG_GROUPING = ("Display configurations of the same part as separate items",
                   "Display all configurations of the same part as one item",
                   "Display configurations with the same name as one item")


def configuration(obj):
    """The configuration an instance shows of its part: its Configuration property if it has one, else for a
    link that changes its copy (LinkCopyOnChange) the link's own label, else "Default"."""
    c = getattr(obj, "Configuration", None)
    if isinstance(c, str) and c:
        return c
    c = getattr(obj, "FwConfiguration", None)     # an assembly instance in its own configuration (asmcfginst)
    if isinstance(c, str) and c and (getattr(obj, "LinkCopyOnChangeSource", None) is not None
                                     or obj.TypeId == "Assembly::AssemblyLink"):
        return c
    base = getattr(obj, "LinkedObject", None)
    if base is not None and base is not obj and getattr(obj, "LinkCopyOnChange", "Disabled") not in ("Disabled", 0):
        return obj.Label
    return "Default"


def _bom_quantity(base):
    """How many one instance counts for: the part's BOM quantity custom property (customprops), else 1."""
    try:
        from . import customprops
        q = customprops.bom_quantity(base.Document)
        return q if q else 1
    except Exception as _fw_err:
        _fw_log("drawtables.py:289", _fw_err)
        return 1


def _bom_description(base, config):
    """DESCRIPTION: the configuration's description when Use in bill of materials is on (configmanager),
    else the part's Label2."""
    try:
        from . import configmanager
        d = configmanager.bom_description(base.Document, config)
        if d is not None:
            return d
    except Exception as _fw_err:
        _fw_log("drawtables.py:294", _fw_err)
    try:
        from . import fileprops                # the configuration's Description, else the Custom one
        got = fileprops.lookup(base.Document, "Description", config)
        if got is not None and str(got).strip():
            return str(got)
    except Exception as _fw_err:
        _fw_log("drawtables.py:301", _fw_err)
    return getattr(base, "Label2", "") or ""


def _part_number(doc, config, base):
    ""

    try:
        from . import configs
        return configs.bom_name(doc, config)
    except Exception:
        return doc.Label or base.Label


def _suppressed(comp):
    try:
        from . import asmcomp
        return asmcomp.is_suppressed(comp)
    except Exception:
        return False


_NOT_COMPONENT = ("Sketcher::SketchObject", "Part::Part2DObject", "Part::Datum", "App::DatumElement", "App::Origin",
                  "App::OriginFeature", "App::Placement")


def _not_component(c):
    """True for what lives in an assembly but is not a component: sketches, datum planes/axes/points, origins."""
    for o in (c, getattr(c, "LinkedObject", None)):
        if o is None:
            continue
        for t in _NOT_COMPONENT:
            try:
                if o.isDerivedFrom(t):
                    return True
            except Exception as _fw_err:
                _fw_log("drawtables.py:337", _fw_err)
    return False


BOM_TYPES = ("Top-level only", "Parts only", "Indented", "Flattened")
BOM_FILTERS = (("parts", "Hide part components"), ("assemblies", "Hide assembly components"),
               ("toolbox", "Hide Toolbox components"))


def _is_toolbox(base):
    try:
        from . import toolbox
        return bool(getattr(base, toolbox.PROP, ""))
    except Exception:
        return False


def _filtered(items, filters):
    ""
    filters = set(filters or ())
    if not filters:
        return items
    out = []
    for it in items:
        base = it[4]
        asm = getattr(base, "TypeId", "") == "Assembly::AssemblyObject"
        if asm and "assemblies" in filters:
            continue
        if not asm and "parts" in filters:
            continue
        if "toolbox" in filters and _is_toolbox(base):
            continue
        out.append(it)
    return out


BARE = {}          # a BOM item's identity ("Spacer (M8x20)") -> the PART NUMBER it shows ("Spacer")
LAST_IDENT = {}    # the last bom_rows: {item identity: item number}
MISSING_IDENT = {}    # the last bom_rows' kept missing rows: {item identity: item number}


def shown_pn(name):
    ""

    return BARE.get(name, name)


def _ident(name, config):
    long = "%s (%s)" % (name, config) if name != config else name
    if long != name:
        BARE[long] = name
    return long


def bom_items(view, bom_type="Top-level only", grouping=CONFIG_GROUPING[0], filters=None):
    ""



    items = []
    index = {}
    view_doc = [None, False]

    def add(obj, depth):

        # document's name (or the configuration's Bill of Materials part number), never the
        # body's label: two parts whose bodies are both "Body" stay two items
        base = getattr(obj, "LinkedObject", None) or obj
        if getattr(obj, "LinkCopyOnChange", "Disabled") != "Disabled" and getattr(obj, "LinkCopyOnChangeSource", None) is not None:
            base = obj.LinkCopyOnChangeSource       # the part itself, not the copy its configuration shows on
        config = configuration(obj)
        source = base.Document
        key_doc = source.FileName or source.Name
        home = getattr(view_doc[0], "Document", None)
        if source is home and view_doc[1]:
            # a body of the drawn document itself (a multibody part, a virtual component): its own item;

            name = base.Label
            key_doc = (key_doc, base.Name)
        else:
            name = _part_number(source, config, base)
        if grouping == CONFIG_GROUPING[1] or config == "Default":
            ident = key_doc
        elif grouping == CONFIG_GROUPING[2]:
            ident = (name, config)
            name = _ident(name, config)
        else:
            ident = (key_doc, config)
            name = _ident(name, config)
        key = (ident, depth) if bom_type == "Indented" else ident
        each = _bom_quantity(base)
        if key in index:
            items[index[key]][2] += each
            return
        desc = _bom_description(base, config)
        index[key] = len(items)
        items.append([name, desc, each, depth, base, config])

    def walk(o, depth):
        if o.TypeId == "Assembly::AssemblyObject":
            for c in o.OutList:
                if c.TypeId in ("Assembly::JointGroup", "Assembly::ViewGroup") or not hasattr(c, "Shape"):
                    continue
                if c.TypeId == "Assembly::AssemblyObject" or getattr(getattr(c, "LinkedObject", None), "TypeId", "") \
                        == "Assembly::AssemblyObject":
                    if bom_type == "Top-level only":
                        add(c, depth)
                        continue
                    if bom_type == "Indented":
                        add(c, depth)
                    if bom_type == "Flattened":
                        add(c, 0)
                        walk(getattr(c, "LinkedObject", None) or c, 0)
                        continue
                    walk(getattr(c, "LinkedObject", None) or c, depth + 1)
                    continue
                if _suppressed(c):
                    continue
                if _not_component(c):
                    continue
                try:
                    if c.Shape.isNull():
                        continue
                except Exception as _fw_err:
                    _fw_log("drawtables.py:468", _fw_err)
                    continue
                add(c, depth)
        else:
            add(o, depth)
    srcs = list(DV.source_shapes(view))
    view_doc[0] = srcs[0] if srcs else None
    view_doc[1] = len(srcs) > 1 or any(o.TypeId == "Assembly::AssemblyObject" for o in srcs)
    for o in srcs:
        walk(o, 0)
    return _filtered(items, filters)


def cut_list_items(part_doc):
    """[(item name, description, quantity, material)] of a weldment part's cut list (identical bodies share an
    item, as its Cut list folder), else []."""
    try:
        from . import wecutlist
    except Exception:
        return []
    try:
        entries = wecutlist.entries(part_doc)
    except Exception as _fw_err:
        _fw_log("drawtables.py:491", _fw_err)
        return []
    groups = []
    for key, props, _obj in entries:
        g = next((g for g in groups if g[0] == key), None)
        if g is None:
            groups.append([key, props, 1])
        else:
            g[2] += 1
    try:
        box = wecutlist.folder(part_doc)
        typed = {it.Key: it for it in (box.Items if box is not None else [])}
    except Exception as _fw_err:
        _fw_log("drawtables.py:cut list items", _fw_err)
        typed = {}
    out = []
    for n, (key, props, count) in enumerate(groups, 1):
        desc = props.get("Description", "")
        item = typed.get(repr(key))
        if item is not None and getattr(item, "Description", ""):
            desc = item.Description
        if props.get("Length"):
            desc = "%s, LENGTH %g" % (desc, props["Length"])
        LAST_CUT_PROPS["Cut-List-Item%d" % n] = props
        out.append(("Cut-List-Item%d" % n, desc, count, props.get("Material", "")))
    return out


LAST_CUT_PROPS = {}    # cut list item name -> its cut list properties (as cut_list_items read them last)

# list property as the BOM quantity (the total LENGTH of the item's members, say, not how many there are)
CUT_QTY_PROPS = ("LENGTH", "ANGLE1", "ANGLE2")


def cut_quantity(props, prop, count):
    """The BOM quantity of a cut list item: its property prop times how many (else the count)."""
    if not prop:
        return count
    key = {"LENGTH": "Length", "ANGLE1": "Angle1", "ANGLE2": "Angle2"}.get(prop.upper(), prop)
    try:
        v = float(props.get(key, props.get(prop, "")))
    except (TypeError, ValueError):
        return count
    return round(v * count, 6)


def with_cut_lists(items, home=None, qty_prop=""):
    """Detailed cut list: under each weldment part's row (a part file of its own, not the assembly's document
    home), its cut list items (quantity per part times the part's quantity). qty_prop: Calculate quantity using BOM
    quantity, the cut list property that is the quantity (LENGTH...)."""
    out = []
    for it in items:
        out.append(it)
        name, desc, qty, depth, obj = it[:5]
        doc = getattr(obj, "Document", None)
        if doc is None or doc is home:
            continue
        for cname, cdesc, count, mat in cut_list_items(doc):
            q = cut_quantity(LAST_CUT_PROPS.get(cname, {}), qty_prop, count) * qty if qty_prop else count * qty
            out.append([cname, cdesc, q, depth + 1, None, mat])
    return out



BOM_COLUMN_TYPES = ("Item No.", "Part Number", "Quantity", "Custom Property", "User Defined")

# system properties), the material applied to the part and its mass; the plain names are the user's custom properties
BOM_PROPERTIES = ("Description", "FW-Material", "FW-Mass", "Material", "Weight", "Mass", "Vendor", "Finish", "Cost",
                  "Revision", "Sheet Metal Gauge", "Sheet Metal Thickness", "Bounding Box Length", "Bounding Box Width")


def qty_title():
    ""

    try:
        from . import optionspages
        if optionspages.stored("Drawings", "Override quantity column name in BOM", False):
            name = str(optionspages.stored("Drawings", "Name to use", "") or "").strip()
            if name:
                return name
    except Exception as _fw_err:
        _fw_log("drawtables.py:qty-title", _fw_err)
    return "QTY."


LAST_QTY_COL = [None]       # the quantity column of the rows bom_rows made last (by position, not by its header)


def default_columns(template="bom-standard"):
    cols = [{"type": "Item No.", "title": "ITEM NO."}, {"type": "Part Number", "title": "PART NUMBER"},
            {"type": "Custom Property", "prop": "Description", "title": "DESCRIPTION"}]
    if template == "bom-material":

        cols.append({"type": "Custom Property", "prop": "FW-Material", "title": "MATERIAL"})
    elif template == "bom-weight":
        cols.append({"type": "Custom Property", "prop": "Weight", "title": "WEIGHT"})
    cols.append({"type": "Quantity", "title": qty_title()})
    return cols


def columns_of(t):
    """The BOM's columns ([{type, prop, title}]): those set on it, else its template's."""
    import json
    text = getattr(t, "SWBomColumns", "") or ""
    if text:
        try:
            return json.loads(text)
        except Exception as _fw_err:
            _fw_log("drawtables.py:543", _fw_err)
    return default_columns(getattr(t, "SWBomTemplate", "bom-standard"))


def store_columns(t, cols):
    import json
    if "SWBomColumns" not in t.PropertiesList:
        t.addProperty("App::PropertyString", "SWBomColumns", "FreeCAD", "the BOM's columns (type, property)")
    t.SWBomColumns = json.dumps(cols)


def _col_index(cols, kind):
    return next((i for i, c in enumerate(cols) if c.get("type") == kind), None)


def mass_text(kg, obj=None):
    ""

    grams = float(kg) * 1000.0
    try:
        from . import customprops
        unit = customprops._doc_unit("mass") or "g"
        return "%.2f %s" % (grams / customprops.UNIT_SIZES["mass"][unit], unit)
    except Exception as _fw_err:
        _fw_log("drawtables.py:mass unit", _fw_err)
        return "%.2f g" % grams


def property_value(obj, name, config=None):
    ""


    if obj is None:
        return ""
    low = name.lower()
    if low in ("fw-material", "sw-material"):
        return _material(obj)[0]            # the system property: the applied material
    if low in ("fw-mass", "sw-mass"):
        m = _mass(obj)
        return "" if m is None else mass_text(m, obj)
    try:
        from . import fileprops
        got = fileprops.lookup(obj.Document, name, config)
        if got is not None:
            return str(got)
    except Exception as _fw_err:
        _fw_log("drawtables.py:570", _fw_err)
    if low == "material":
        return _material(obj)[0]
    if low in ("weight", "mass"):
        m = _mass(obj)
        return "" if m is None else mass_text(m, obj)
    if low == "description":
        return getattr(obj, "Label2", "") or ""
    try:
        return sheet_metal_value(obj, name)
    except Exception as _fw_err:
        _fw_log("drawtables.py:608", _fw_err)
        return ""


SHEET_METAL_PROPERTIES = ("Sheet Metal Gauge", "Sheet Metal Thickness", "Bend Radius", "Bounding Box Length",
                          "Bounding Box Width", "Bends", "Cutting Length-Outer", "Cutting Length-Inner",
                          "Cut Outs", "Bend Allowance")


def sheet_metal_value(obj, name):
    ""

    doc = obj.Document
    low = name.lower()
    if low in ("sheet metal gauge", "gauge"):
        for o in doc.Objects:
            if getattr(o, "SWUseGauge", False) and getattr(o, "SWGauge", ""):
                return str(o.SWGauge)
        return ""
    from . import smcutlist
    names = {p.lower(): p for p in smcutlist.PROPS}
    if low not in names:
        return ""
    for body in smcutlist.sheet_bodies(doc):
        v = smcutlist.values(body).get(names[low])
        if v is None or v == "":
            return ""
        return ("%g" % v) if isinstance(v, float) else str(v)
    return ""


ROW_KEYS = []      # the last bom_rows' item keys (a part's document and object), one per item row


def _row_key(obj):
    try:
        return "%s#%s" % (obj.Document.Name, obj.Name)
    except Exception:
        return ""


def store_row_keys(t, ident=None):
    if "SWBomRowKeys" not in t.PropertiesList:
        t.addProperty("App::PropertyStringList", "SWBomRowKeys", "FreeCAD", "the part of each BOM row")
    t.SWBomRowKeys = list(ROW_KEYS)
    if ident is not None:
        import json
        if "SWBomIdent" not in t.PropertiesList:
            t.addProperty("App::PropertyString", "SWBomIdent", "FreeCAD",
                          "each item's identity (part, configuration) and its item number")
            t.setPropertyStatus("SWBomIdent", ["Hidden"])
        t.SWBomIdent = json.dumps(ident)


def bom_ident(t):
    """{item identity: item number} of a BOM table as last made ({} for one made before identities were kept)."""
    try:
        import json
        got = json.loads(getattr(t, "SWBomIdent", "") or "{}")
        return got if isinstance(got, dict) else {}
    except Exception:
        return {}


def _column_rows(rows, metas, cols, user):
    """rows (the standard columns) as the BOM's own columns. metas: (item, part number, description, qty, obj)
    per row; user: {(column title, part number): text} kept in User Defined columns."""
    out = [[c.get("title", "") for c in cols]]
    for item, name, desc, qty, obj, config in metas:
        row = []
        for c in cols:
            kind = c.get("type")
            if kind == "Item No.":
                row.append(item)
            elif kind == "Part Number":
                row.append(name)
            elif kind == "Quantity":
                row.append(str(qty))
            elif kind == "Custom Property":
                prop = c.get("prop", "")
                row.append(desc if prop.lower() == "description" else property_value(obj, prop, config))
            else:
                u = user or {}
                row.append(u.get((c.get("title", ""), _row_key(obj)), u.get((c.get("title", ""), name), "")))
        out.append(row)
    return out


def bom_rows(view, bom_type="Top-level only", start=1, step=1, template="bom-standard", numbering="Detailed",
             keep=None, keep_missing=False, cut_list=False, follow=True, grouping=CONFIG_GROUPING[0],
             strikeout=False, columns=None, user=None, filters=None, cut_qty="", old_ident=None):
    """ITEM NO., PART NUMBER, DESCRIPTION, (MATERIAL / WEIGHT,) QTY. of the view's model. numbering: Detailed
    (1, 1.1, 1.2) or Flat (1, 2, 3) for an Indented BOM. keep: {part number: item number} to keep (Do not
    change item numbers); keep_missing: previous rows (Keep missing items) whose parts are gone stay."""
    items = bom_items(view, bom_type, grouping, filters)
    if not follow and bom_type != "Indented":
        items = sorted(items, key=lambda it: str(it[0]).lower())   # Follow assembly order off: by part number
    if cut_list and bom_type == "Indented":
        src = DV.source_shapes(view)
        items = with_cut_lists(items, src[0].Document if src else None, cut_qty)
    head = ["ITEM NO.", "PART NUMBER", "DESCRIPTION"]
    if template == "bom-material":
        head.append("MATERIAL")
    elif template == "bom-weight":
        head.append("WEIGHT")
    head.append(qty_title())
    LAST_QTY_COL[0] = len(head) - 1
    rows = [head]
    metas = []
    counters = []
    LAST_IDENT.clear()
    used = set((keep or {}).values())
    nxt = [start]

    def fresh():
        while str(nxt[0]) in used:
            nxt[0] += step
        n = nxt[0]
        nxt[0] += step
        return str(n)
    for n, it in enumerate(items):
        name, desc, qty, depth, obj = it[:5]
        if bom_type == "Indented" and numbering == "Detailed":
            while len(counters) <= depth:
                counters.append(0)
            del counters[depth + 1:]
            counters[depth] += 1
            top = start + (counters[0] - 1) * step
            item = ".".join([str(top)] + [str(c) for c in counters[1:depth + 1]])
        elif bom_type == "Indented" and numbering == "No":
            item = ""
        elif keep and name in keep:
            item = keep[name]
        else:
            item = fresh()
        LAST_IDENT[name] = item
        name = shown_pn(name)
        row = [item, name, desc]

        # own property wins (a configuration's, then the Custom one, linked values evaluated), else the
        # applied material / the mass
        cfg = it[5] if obj is not None and len(it) > 5 else None
        if template == "bom-material":
            row.append(property_value(obj, "Material", cfg) if obj is not None else (it[5] if len(it) > 5 else ""))
        elif template == "bom-weight":
            row.append(property_value(obj, "Weight", cfg) if obj is not None else "")
        row.append(str(qty))
        rows.append(row)
        metas.append((item, name, desc, qty, obj, it[5] if obj is not None and len(it) > 5 else None))
    ROW_KEYS[:] = [_row_key(m[4]) for m in metas]
    pn, dc = 1, 2
    if columns:
        rows = _column_rows(rows, metas, columns, user)
        head = rows[0]
        LAST_QTY_COL[0] = _col_index(columns, "Quantity")
        pn = _col_index(columns, "Part Number")
        dc = next((i for i, c in enumerate(columns) if c.get("type") == "Custom Property" and
                   c.get("prop", "").lower() == "description"), None)
    hide = keep_missing and str(_row(view.Document, "Bill of Materials", "Missing component",
                                     "Display with strikethrough", "bom_missing")) == "Hide the row"
    MISSING_IDENT.clear()
    if keep_missing and pn is not None and not hide:            # Missing component: Hide the row
        have = {r[pn] for r in rows[1:]}
        # by identity (drawings-land279): two configurations' rows both read "Pin", so a gone configuration is
        # found by its (part, configuration) identity, kept from the last update by its item number
        was = {str(v): k for k, v in (old_ident or {}).items() if str(v)}
        for r in keep_missing[1:]:
            r = [unstrike(c) for c in r]
            ident = was.get(r[0]) if r else None
            if ident is not None:
                missing = ident not in LAST_IDENT
            else:
                missing = len(r) > pn and r[pn] not in have
            if len(r) > pn and missing:
                if ident is not None:
                    MISSING_IDENT[ident] = r[0]            # still known as missing at the next update
                gone = list(r) + [""] * (len(head) - len(r))
                gone = gone[:len(head)]
                if strikeout:
                    gone = [strike(c) for c in gone]       # Keep missing items: Strikeout
                elif dc is not None and not gone[dc].endswith("(missing)"):
                    gone[dc] = (gone[dc] + " (missing)").strip()
                rows.append(gone)
    return rows


STRIKE = "\u0336"


def strike(text):
    """Text struck through (a combining long stroke after each character)."""
    return "".join(ch + STRIKE for ch in unstrike(text))


def unstrike(text):
    return str(text).replace(STRIKE, "")


BOM_WIDTHS = (70, 180, 200, 50)


def bom_widths(template):
    if template in ("bom-material", "bom-weight"):
        return (70, 180, 200, 110, 50)
    return BOM_WIDTHS


def anchor(page, kind):
    ""

    w, h = D.sheet_size(page)
    return {"BOM": (w - 75, 72), "Hole": (75, h - 25), "Revision": (w - 70, h - 20),
            "General": (w / 2, h - 20), "Bend": (75, h - 25), "Punch": (75, h - 25), "Weld": (w - 80, 120), "CutList": (w - 80, h - 30),
            "TitleBlock": (w - 95, 32)}.get(kind, (w / 2, h / 2))


def set_border(t, box=0.35, grid=0.18):
    """Box border and grid border thickness (TechDraw draws one line width for the table)."""
    for name, val in (("SWBoxBorder", box), ("SWGridBorder", grid)):
        if name not in t.PropertiesList:
            t.addProperty("App::PropertyFloat", name, "FreeCAD", "table border thickness (mm)")
        setattr(t, name, float(val))
    try:
        t.LineWidth = float(max(box, grid))
    except Exception as _fw_err:
        _fw_log("drawtables.py:769", _fw_err)


def _row(doc, page, text, default, key=None):
    from . import drawdocprops
    return drawdocprops.row(doc, page, text, default, key)


def model_configurations(view):
    """(configuration table, names, active name) of the view's model (ConfigurationManager), or (None, [], "")."""
    try:
        from . import configmanager
        src = DV.source_shapes(view)
        t = configmanager.table(src[0].Document) if src else None
    except Exception:
        t = None
    if t is None:
        return None, [], ""
    try:
        names = list(t.names())
    except Exception:
        names = []
    return t, names, str(getattr(t.sheet, t.prop, "") or "")


def config_quantities(view, bom_type, grouping, names):
    ""

    t, have, active = model_configurations(view)
    out = {}
    if t is None:
        return out, []
    order = []
    try:
        for n in names:
            if n not in have:
                continue
            _show(t, n)
            q = {}
            for it in bom_items(view, bom_type, grouping):
                q[it[0]] = q.get(it[0], 0) + it[2]
                if it[0] not in [o[0] for o in order]:
                    order.append(it)
            out[n] = q
    finally:
        if active:
            _show(t, active)
    return out, order


def _show(t, name):
    """Show Configuration, its components suppressed or resolved as the configuration says."""
    from . import configmanager
    configmanager.show(t, name)
    try:
        from . import configs
        configs.apply_assembly(t.sheet.Document)
    except Exception as _fw_err:
        _fw_log("drawtables.py:827", _fw_err)


def zero_quantity(doc, q):
    """Zero quantity display (Document Properties > Tables > Bill of Materials): 0, a dash or blank."""
    if q:
        return str(q)
    z = str(_row(doc, "Bill of Materials", "Zero quantity display", "0", "bom_zero"))
    return {"-": "-", "Blank": ""}.get(z, "0")


def config_columns(rows, view, bom_type, grouping, names, idents=None):
    """The QTY. column made one column per configuration ("<name>/QTY.", or the name alone with Do not add QTY
    next to configuration name); a part only in another configuration gets its row, 0 where it is not."""
    qc = LAST_QTY_COL[0]        # extapps84: the quantity column by position, whatever its header says
    if qc is None or not rows or qc >= len(rows[0]):
        qc = next((i for i, h in enumerate(rows[0] if rows else []) if h in ("QTY.", qty_title())), None)
    if not names or qc is None:
        return rows
    per, order = config_quantities(view, bom_type, grouping, names)
    names = [n for n in names if n in per]
    if not names:
        return rows
    doc = view.Document
    bare = bool(_row(doc, "Bill of Materials", "Do not add QTY next to configuration name", False, "bom_noqty"))
    head = rows[0][:qc] + [n if bare else "%s/%s" % (n, qty_title()) for n in names] + rows[0][qc + 1:]
    out = [head]
    have = set()
    for i, r in enumerate(rows[1:]):
        pn = r[1] if len(r) > 1 else ""
        if idents and i < len(idents) and shown_pn(idents[i]) == pn:
            pn = idents[i]              # the row's identity (its configuration): the quantities are counted by it
        have.add(pn)
        out.append(r[:qc] + [zero_quantity(doc, per[n].get(pn, 0)) for n in names] + r[qc + 1:])
    nxt = max([int(r[0]) for r in rows[1:] if r and str(r[0]).isdigit()] + [0])
    for it in order:
        if it[0] in have:
            continue
        nxt += 1
        r = [str(nxt), shown_pn(it[0]), it[1]] + [""] * (qc - 3)
        out.append(r + [zero_quantity(doc, per[n].get(it[0], 0)) for n in names] + [""] * (len(rows[0]) - qc - 1))
        have.add(it[0])
    return out


def make_bom(page, view, at, bom_type="Top-level only", start=1, step=1, template="bom-standard",
             numbering="Detailed", keep_missing=False, fixed_numbers=False, cut_list=False, follow=True,
             grouping=CONFIG_GROUPING[0], strikeout=False, configs=None, filters=None, cut_qty=""):
    rows = bom_rows(view, bom_type, start, step, template, numbering, cut_list=cut_list, follow=follow,
                    grouping=grouping, filters=filters, cut_qty=cut_qty if cut_list else "")
    ident = dict(LAST_IDENT)
    if configs:
        rows = config_columns(rows, view, bom_type, grouping, list(configs), list(ident))
    t = make_table(page, rows, at, "Bill of Materials%d" % (1 + len(
        [o for o in page.Document.Objects if getattr(o, "SWTable", "") == "BOM"])), "BOM", bom_widths(template))
    for name, kind, val in (("SWBomView", "App::PropertyString", view.Name), ("SWBomType", "App::PropertyString", bom_type),
                            ("SWBomStart", "App::PropertyInteger", start), ("SWBomStep", "App::PropertyInteger", step),
                            ("SWBomTemplate", "App::PropertyString", template),
                            ("SWBomNumbering", "App::PropertyString", numbering),
                            ("SWBomKeepMissing", "App::PropertyBool", keep_missing),
                            ("SWBomFixedNumbers", "App::PropertyBool", fixed_numbers),
                            ("SWBomCutList", "App::PropertyBool", cut_list),
                            ("SWBomCutQty", "App::PropertyString", cut_qty if cut_list else ""),
                            ("SWBomFollowOrder", "App::PropertyBool", follow),
                            ("SWBomGrouping", "App::PropertyString", grouping),
                            ("SWBomStrikeout", "App::PropertyBool", strikeout),
                            ("SWBomConfigurations", "App::PropertyStringList", list(configs or [])),
                            ("SWBomFilter", "App::PropertyStringList", list(filters or []))):
        t.addProperty(kind, name, "FreeCAD", "Bill of Materials settings")
        setattr(t, name, val)
    store_row_keys(t, ident)
    return t


_SIGS = {}      # (drawing, table) -> the model signature the table was last made from (this session)
TABLE_VIEW = {"BOM": "SWBomView", "Hole": "SWHoleView", "Bend": "SWTableView", "Punch": "SWTableView",
              "CutList": "SWTableView", "DesignTable": "SWBomView"}


_SIZE_CACHE = {}       # (document, object) -> (its shape, (box sizes, faces))


def model_signature(view):
    """A cheap fingerprint of what a view shows: its models, their components and their size."""
    out = []
    for o in DV.source_shapes(view):
        try:
            sh = o.Shape
            key = (o.Document.Name, o.Name)
            got = _SIZE_CACHE.get(key)
            if got is None or not DV.same_shape(got[1], sh, got[0]):     # counting a 301-part assembly's faces
                bb = sh.BoundBox                                             # each second is slow
                got = (DV.SHAPE_GEN[0], sh,
                       (round(bb.XLength, 4), round(bb.YLength, 4), round(bb.ZLength, 4), len(sh.Faces)))
                if len(_SIZE_CACHE) > 5000:
                    _SIZE_CACHE.clear()
                _SIZE_CACHE[key] = got
            size = got[2]
            out.append((o.Name, len(o.OutList)) + size)
        except Exception:
            out.append((getattr(o, "Name", "?"),))
        if o.TypeId == "Assembly::AssemblyObject":
            # a component suppressed or resolved, or swapped for another part, changes the BOM too
            out.append(tuple(sorted((c.Name, _suppressed(c), getattr(getattr(c, "LinkedObject", None), "Name", ""))
                                    for c in o.OutList)))
    return tuple(out)


def _property_documents(view):
    """The part and assembly documents a BOM's rows come from (components of subassemblies too)."""
    out, seen = [], set()
    todo = list(DV.source_shapes(view))
    while todo:
        o = todo.pop()
        try:
            target = o.getLinkedObject(True) if o.TypeId in ("App::Link", "Assembly::AssemblyLink") else o
            d = target.Document
        except Exception:
            continue
        if d.Name not in seen:
            seen.add(d.Name)
            out.append(d)
        if target.TypeId == "Assembly::AssemblyObject" and len(seen) < 2000:
            todo += [c for c in target.OutList if c.TypeId in ("App::Link", "Assembly::AssemblyLink")]
    return out


def _property_signature(view):
    ""


    out = []
    for d in _property_documents(view):
        try:
            meta = tuple(sorted((k, v) for k, v in dict(d.Meta or {}).items() if k.startswith("FreeWorks") or
                                "Prop" in k or "Config" in k or "Cfg" in k))
            out.append((d.Name, d.Label, hash(meta)))
        except Exception:
            out.append((getattr(d, "Name", "?"),))
    return tuple(sorted(out))


def table_signature(t, view):
    """model_signature, and for a weldment cut list its items themselves: the members' lengths can change while
    the view's bodies keep their size and faces (PC 11-11: frame edited to 280, the cut list kept 220)."""
    sig = model_signature(view)
    if getattr(t, "SWTable", "") == "BOM":
        sig = sig + (_property_signature(view),)    # a part's Description, Part Number or BOM quantity edited
    if getattr(t, "SWTable", "") == "Bend":
        sig = sig + (bend_signature(view),)     # a bend moved or opened keeps the flat pattern's size
    if getattr(t, "SWTable", "") in ("Hole", "Punch"):
        try:                                    # the rows come from the view's drawn circles: once the view
            sig = sig + (tuple(sorted((round(c[1].x, 3), round(c[1].y, 3), round(c[2], 3))   # has drawn
                                      for c in DA.circles(view))),)     # the edited model, update again
        except Exception as _fw_err:
            _fw_log("drawtables.py:941", _fw_err)
    if getattr(t, "SWTable", "") == "CutList":
        srcs = _fw_xs(view)
        if srcs:
            try:
                sig = sig + tuple(cut_list_items(srcs[0].Document))
            except Exception as _fw_err:
                _fw_log("drawtables.py:948", _fw_err)
    return sig


_CUT_ROWS = {}        # (drawing, table) -> the cut list rows last written (compared as made, not as shown)


def cut_list_part(t):
    """The weldment (or sheet metal) part document a cut list table lists."""
    doc = t.Document
    view = doc.getObject(getattr(t, "SWTableView", "") or "")
    if view is None:
        return None
    for s in _fw_xs(view):
        try:
            if s.Document is not None:
                return s.Document
        except Exception:          # a body rebuilt by the edit: its old object is gone
            continue
    name = getattr(t, "SWTablePart", "") if "SWTablePart" in t.PropertiesList else ""
    return App.listDocuments().get(name) if name else None


def refresh_cut_list(t):
    ""


    part = cut_list_part(t)
    if part is None:
        return False
    from . import drawmenus
    rows = drawmenus.cut_list_rows(part)
    key = (t.Document.Name, t.Name)
    if key not in _CUT_ROWS:              # first look: what the table was made from
        _CUT_ROWS[key] = rows
        return False
    if len(rows) < 2 or rows == _CUT_ROWS[key]:
        return False
    old = _CUT_ROWS[key]
    _CUT_ROWS[key] = rows
    if getattr(t, "SWKeepMissing", False):            # Keep missing items: rows gone from the model stay
        have = [r[2:4] for r in rows[1:]]
        gone = _CUT_MISSING.setdefault(key, [])
        shown = {tuple(r[2:4]): r for r in (rows_of(t) or [])[1:]}
        for r in old[1:]:
            r = list(shown.get(tuple(r[2:4]), r))        # as the table showed it (its number, its material)
            if r[2:4] not in have and r[2:4] not in [g[2:4] for g in gone]:
                gone.append(r)
        _CUT_MISSING[key] = [r for r in gone if r[2:4] not in have]
    out = dress_cut_rows(t, rows)
    set_rows(t, out, cut_widths(out))
    return True


_CUT_MISSING = {}     # (drawing, table) -> rows the model lost, kept by Keep missing items
CUT_TEMPLATES = ("cut list-standard", "cut list-material")


def cut_widths(rows):
    n = len(rows[0]) if rows else 4
    return {4: (60, 50, 220, 80), 5: (60, 50, 200, 80, 80)}.get(n, (40, 30, 50, 60, 60, 60, 60)[:n] + (60,) * max(0, n - 7))


def dress_cut_rows(t, rows, part=None):
    """The Weldment Cut List PM's choices on the part's cut list rows: the Table Template (cut list-material
    adds MATERIAL), the Item Numbers (Start at, Increment) and Keep missing items (struck through)."""
    rows = [list(r) for r in rows]
    tmpl = str(getattr(t, "SWTableTemplate", "") or "")
    if tmpl == "cut list-material" and rows and len(rows[0]) == 4:
        part = part or cut_list_part(t)
        mats = []
        try:
            mats = [m for (_n, _d, _c, m) in cut_list_items(part)] if part is not None else []
        except Exception:
            mats = []
        rows[0].append("MATERIAL")
        for i, r in enumerate(rows[1:]):
            r.append(str(mats[i]) if i < len(mats) and mats[i] else "-")
    start, step = int(getattr(t, "SWItemStart", 1) or 0), int(getattr(t, "SWItemStep", 1) or 1)
    if not getattr(t, "SWItemFixed", False):
        for i, r in enumerate(rows[1:]):
            r[0] = str(start + i * step)
    if getattr(t, "SWKeepMissing", False):
        n = len(rows[0])
        for r in _CUT_MISSING.get((t.Document.Name, t.Name), []):
            r = (list(r) + ["-"] * n)[:n]
            r[1] = "0"
            if getattr(t, "SWStrikeout", True):
                r[2] = "".join(ch + "\u0336" for ch in r[2])
            rows.append(r)
    return rows


def auto_update_tables(doc):
    ""

    done = []
    try:
        if DV.relink_weldment_views(doc):   # a frame edit made the member bodies again: the views follow
            doc.recompute()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: weldment views: %s\n" % error)
    try:
        refresh_bend_notes(doc)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: bend notes update: %s\n" % error)
    try:
        DA.drop_lost_weld_symbols(doc)      # a weld symbol from the model goes with its bead
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: weld symbols update: %s\n" % error)
    for t in [o for o in doc.Objects if getattr(o, "SWTable", "") == "Weld"]:
        try:
            if refresh_weld_table(t):
                done.append(t)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: weld table update: %s\n" % error)
    tables = [o for o in doc.Objects if TABLE_VIEW.get(getattr(o, "SWTable", ""))]   # a table update may take tags away
    for t in tables:
        prop = TABLE_VIEW.get(getattr(t, "SWTable", ""))
        if prop is None:
            continue
        if getattr(t, "SWTable", "") == "CutList":
            try:
                if refresh_cut_list(t):
                    done.append(t)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: cut list update: %s\n" % error)
            continue
        if getattr(t, "SWTable", "") == "DesignTable":
            try:            # it follows the configuration table's values, which no view's shape shows
                if refresh_design_table(t):
                    done.append(t)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: design table update: %s\n" % error)
            continue
        view = doc.getObject(getattr(t, prop, "") or "")
        if view is None:
            continue
        try:
            sig = table_signature(t, view)
        except Exception:
            continue
        key = (doc.Name, t.Name)
        kept = getattr(t, "SWModelSignature", "")        # a bend table: what it was made for, kept in the file
        if key not in _SIGS and not (kept and kept != repr(sig)):
            _SIGS[key] = sig
            continue
        if _SIGS.get(key) == sig:
            continue
        _SIGS[key] = sig
        try:
            update_table(t)
            _keep_table_signature(t, sig)
            done.append(t)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: table update: %s\n" % error)
    if done:
        doc.recompute()
    return done


def _keep_table_signature(t, sig):
    ""

    if getattr(t, "SWTable", "") != "Bend":
        return
    try:
        if "SWModelSignature" not in t.PropertiesList:
            t.addProperty("App::PropertyString", "SWModelSignature", "FreeCAD", "the model the table was made from")
            t.setPropertyStatus("SWModelSignature", ["Hidden"])
        t.SWModelSignature = repr(sig)
    except Exception as _fw_err:
        _fw_log("drawtables.py:1120", _fw_err)


def update_table(t):
    """Update Table: a BOM or Hole Table made again from the model."""
    doc = t.Document
    kind = getattr(t, "SWTable", "")
    if kind == "DesignTable":
        return refresh_design_table(t)
    if kind == "BOM":
        view = doc.getObject(t.SWBomView)
        if view is not None:
            old = rows_of(t)
            template = getattr(t, "SWBomTemplate", "bom-standard")
            cols = columns_of(t) if getattr(t, "SWBomColumns", "") else None
            pn = _col_index(cols, "Part Number") if cols else 1
            item = _col_index(cols, "Item No.") if cols else 0
            keep = {r[pn]: r[item] for r in old[1:] if pn is not None and item is not None and len(r) > max(pn, item)} \
                if getattr(t, "SWBomFixedNumbers", False) else None
            if keep is not None:
                keep.update(bom_ident(t))       # by identity: two configurations' rows both read "Spacer"
            user = {}
            if cols and pn is not None:
                keys = list(getattr(t, "SWBomRowKeys", []) or [])
                for c, col in enumerate(cols):
                    if col.get("type") == "User Defined":
                        for i, r in enumerate(old[1:]):
                            if len(r) > max(c, pn) and r[c]:
                                user[(col.get("title", ""), unstrike(r[pn]))] = r[c]   # typed values kept
                                if i < len(keys) and keys[i]:
                                    user[(col.get("title", ""), keys[i])] = r[c]        # by part, renamed too
            if cols:
                from . import drawtableedit
                ws = drawtableedit.widths(t)
            else:
                ws = bom_widths(template)
            rows = bom_rows(view, t.SWBomType, t.SWBomStart, t.SWBomStep, template,
                            getattr(t, "SWBomNumbering", "Detailed"), keep,
                            old if getattr(t, "SWBomKeepMissing", False) else False,
                            getattr(t, "SWBomCutList", False), getattr(t, "SWBomFollowOrder", True),
                            getattr(t, "SWBomGrouping", CONFIG_GROUPING[0]),
                            getattr(t, "SWBomStrikeout", False), cols, user,
                            list(getattr(t, "SWBomFilter", []) or []),
                            getattr(t, "SWBomCutQty", "") if getattr(t, "SWBomCutList", False) else "",
                            old_ident=bom_ident(t))
            ident = dict(MISSING_IDENT)
            ident.update(LAST_IDENT)
            cfg = list(getattr(t, "SWBomConfigurations", []) or [])
            if cfg and not cols:
                rows = config_columns(rows, view, t.SWBomType, getattr(t, "SWBomGrouping", CONFIG_GROUPING[0]), cfg,
                                      list(LAST_IDENT))
            from . import drawtableedit
            rows = drawtableedit.bom_view_rows(t, rows)          # Hide > Row and Sort... are kept
            set_rows(t, rows, ws)
            store_row_keys(t, ident)
            drawtableedit.keep_overrides(t)        # overridden values and locked cells stay
            try:
                DA.refresh_balloons(doc)            # the balloons follow the BOM's item numbers
            except Exception as error:
                App.Console.PrintLog("FreeCAD: balloons: %s\n" % error)
    elif kind == "Hole":
        view = doc.getObject(t.SWHoleView)
        if view is not None:
            write_hole_rows(t, all_hole_rows(view, hole_origin(t, view), more_sets(t), **hole_options(t))[0])
    elif kind == "Bend":
        view = doc.getObject(t.SWTableView)
        if view is not None and not _drawn(view):
            # sheet metal run 11-27: a drawing opened again refreshed its bend table before the flat pattern view
            # was drawn: no bends, so the tags were deleted and not made again, and the drawing (12 items saved,
            # 10 read) opened read-only as damaged. The table waits for the view.
            view = None
        if view is not None:
            rows, tags = bend_rows(view, getattr(t, "SWBendControl", "Alpha"), getattr(t, "SWBendStart", "A"))
            set_rows(t, rows, BEND_WIDTHS)
            page = next((o for o in t.InList if o.TypeId == "TechDraw::DrawPage"), None)
            if page is not None:                # the bend tags follow their bends, one per row
                for o in list(doc.Objects):
                    if getattr(o, "SWAnnotation", "") == "BendTag" and getattr(o, "SWTagOf", t.Name) == t.Name:
                        doc.removeObject(o.Name)
                _tags(page, view, tags, "BendTag", t)
    elif kind == "Punch":
        view = doc.getObject(t.SWTableView)
        if view is not None:
            set_rows(t, punch_rows(view, hole_origin(t, view))[0], PUNCH_WIDTHS)
    elif kind == "CutList":
        view = doc.getObject(getattr(t, "SWTableView", "") or "")
        srcs = _fw_xs(view) if view is not None else []
        part = srcs[0].Document if srcs else None
        if part is not None:
            from . import drawmenus
            rows = dress_cut_rows(t, drawmenus.cut_list_rows(part), part)
            set_rows(t, rows, cut_widths(rows))
    elif kind == "Weld":
        page = next((o for o in t.InList if o.TypeId == "TechDraw::DrawPage"), None)
        if page is not None:
            v = doc.getObject(getattr(t, "SWTableView", "") or "") if getattr(t, "SWTableView", "") else None
            set_rows(t, weld_rows(page, v), WELD_WIDTHS)
    elif kind == "TitleBlock":
        page = next((o for o in t.InList if o.TypeId == "TechDraw::DrawPage"), None)
        if page is not None:
            set_rows(t, title_block_rows(page, getattr(t, "SWTitleBlockTemplate", "standard title block")),
                     TITLE_BLOCK_WIDTHS)


def _template_group(panel, items, default):
    box, lay = D._group("Table Template", panel.form)
    panel.template = QtWidgets.QComboBox(box)
    panel.template.setObjectName("SWTableTemplate")
    panel.template.addItems(items)
    panel.template.setCurrentText(default)
    lay.addWidget(panel.template)
    panel.lay.addWidget(box)


def _position_group(panel, default=True):
    box, lay = D._group("Table Position", panel.form)
    panel.attach = QtWidgets.QCheckBox("Attach to anchor point", box)
    panel.attach.setObjectName("SWTableAttach")
    panel.attach.setChecked(default)
    lay.addWidget(panel.attach)
    panel.lay.addWidget(box)


THICKNESS = ("0.18mm", "0.25mm", "0.35mm", "0.5mm", "0.7mm", "1mm")


def thickness_text(name):
    """Document Properties > Tables' Box/Grid thickness (Thin, Normal, Thick) as the PM's Border entry."""
    from . import drawdocprops
    if str(name) in THICKNESS:
        return str(name)
    return "%gmm" % drawdocprops.thickness_mm(name, 0.18)


def _border_group(panel):
    box, lay = D._group("Border", panel.form)
    grid = QtWidgets.QGridLayout()
    panel.box_border = QtWidgets.QComboBox(box)
    panel.box_border.setObjectName("SWTableBoxBorder")
    panel.grid_border = QtWidgets.QComboBox(box)
    panel.grid_border.setObjectName("SWTableGridBorder")
    doc = panel.doc
    for c, d in ((panel.box_border, _row(doc, "Tables", "Box thickness", "Thin", "tbl_box")),
                 (panel.grid_border, _row(doc, "Tables", "Grid thickness", "Thin", "tbl_grid"))):
        c.addItems(THICKNESS)
        c.setCurrentText(thickness_text(d))
    grid.addWidget(QtWidgets.QLabel("Box border:", box), 0, 0)
    grid.addWidget(panel.box_border, 0, 1)
    grid.addWidget(QtWidgets.QLabel("Grid border:", box), 1, 0)
    grid.addWidget(panel.grid_border, 1, 1)

    # take the drawing's Document Properties > Tables values, and picking another thickness unticks it
    panel.border_doc = QtWidgets.QCheckBox("Use document settings", box)
    panel.border_doc.setObjectName("SWTableBorderDoc")
    lay.addWidget(panel.border_doc)
    lay.addLayout(grid)
    panel.lay.addWidget(box)
    panel.border_doc.toggled.connect(lambda on, p=panel: _border_doc(p, on))
    for c in (panel.box_border, panel.grid_border):
        c.activated.connect(lambda _i, p=panel: p.border_doc.setChecked(False))
    # Text Format: [ ] All uppercase (the table's own setting; the drawing's Drafting Standard default ticks it)
    tbox, tlay = D._group("Text Format", panel.form)
    panel.all_upper = QtWidgets.QCheckBox("All uppercase", tbox)
    panel.all_upper.setObjectName("SWTableAllUppercase")
    try:
        from . import drawdocprops
        panel.all_upper.setChecked(bool(drawdocprops.prop(doc, "upper_tables")))
    except Exception as _fw_err:
        _fw_log("drawtables.py:all uppercase default", _fw_err)
    tlay.addWidget(panel.all_upper)
    panel.lay.addWidget(tbox)
    order = tuple(getattr(panel, "GROUP_ORDER", ()) or ())     # Layer comes in after build(): Text Format is last
    panel.GROUP_ORDER = order + tuple(t for t in ("Layer", "Text Format") if t not in order)


def doc_border(doc):
    """The drawing's Document Properties > Tables box and grid thickness texts."""
    return (thickness_text(_row(doc, "Tables", "Box thickness", "Thin", "tbl_box")),
            thickness_text(_row(doc, "Tables", "Grid thickness", "Thin", "tbl_grid")))


def _border_doc(panel, on):
    if not on:
        return
    box, grid = doc_border(panel.doc)
    panel.box_border.setCurrentText(box)
    panel.grid_border.setCurrentText(grid)


def upper_rows(doc, rows):
    """Rows in capitals (the drawing's uppercase Exclusion list is kept)."""
    try:
        from . import drawdocprops, docstyle
        ex = drawdocprops.exclusions(doc)
        return [[docstyle.upper(str(c), ex) if isinstance(c, str) else c for c in r] for r in rows]
    except Exception:
        return [[c.upper() if isinstance(c, str) else c for c in r] for r in rows]


def set_all_uppercase(t, on):
    """Text Format > All uppercase for one table (kept as SWAllUppercase); the cells are rewritten."""
    if t is None:
        return
    if "SWAllUppercase" not in t.PropertiesList:
        if not on:
            return
        t.addProperty("App::PropertyBool", "SWAllUppercase", "FreeCAD", "Text Format: All uppercase")
    was = bool(t.SWAllUppercase)
    t.SWAllUppercase = bool(on)
    if on and not was:
        set_rows(t, rows_of(t))


def _apply_border(panel, t):
    set_border(t, float(panel.box_border.currentText()[:-2]), float(panel.grid_border.currentText()[:-2]))
    if t is not None and getattr(panel, "border_doc", None) is not None:
        if "SWBorderFromDoc" not in t.PropertiesList:
            t.addProperty("App::PropertyBool", "SWBorderFromDoc", "FreeCAD", "Border: Use document settings")
        t.SWBorderFromDoc = panel.border_doc.isChecked()
    if t is not None and getattr(panel, "all_upper", None) is not None:
        try:
            set_all_uppercase(t, panel.all_upper.isChecked())
        except Exception as _fw_err:
            _fw_log("drawtables.py:all uppercase", _fw_err)
    if t is not None and getattr(panel, "attach", None) is not None:
        set_attached(t, panel.attach.isChecked())


def set_attached(t, on):
    """Table Position > Attach to anchor point, kept on the table: an attached table follows its anchor when
    Set as Anchor moves it (drawtableedit.set_anchor)."""
    if "SWAttachedToAnchor" not in t.PropertiesList:
        t.addProperty("App::PropertyBool", "SWAttachedToAnchor", "FreeCAD", "Attach to anchor point")
    t.SWAttachedToAnchor = bool(on)


def is_assembly_view(view):
    ""

    try:
        for o in DV.source_shapes(view):
            for x in (o, getattr(o, "LinkedObject", None)):
                if x is not None and x.TypeId == "Assembly::AssemblyObject":
                    return True
    except Exception as _fw_err:
        _fw_log("drawtables.py:is_assembly_view", _fw_err)
        return True
    return False


class BomPanel(D._Panel):
    TITLE = "Bill of Materials"
    LAYER = True
    GROUP_ORDER = ("Table Template", "Table Position", "BOM Type", "Configurations", "Part Configuration Grouping",
                   "Keep Missing Item/Row", "Filter", "Item Numbers", "Border", "Layer")
    PIXMAP = "TechDraw_SpreadsheetView"

    def grouping_text(self):
        ""
        return next((CONFIG_GROUPING[n] for n, b in enumerate(self.grouping) if b.isChecked()), CONFIG_GROUPING[0])

    def build(self):
        self.say("Click a view to make its Bill of Materials (then click where the table goes, unless it is "
                 "attached to the anchor point).")
        _template_group(self, BOM_TEMPLATES, "bom-standard")
        _position_group(self, False)
        box, lay = D._group("BOM Type", self.form)
        self.bom_type = QtWidgets.QButtonGroup(box)
        for n, k in enumerate(BOM_TYPES):
            b = QtWidgets.QRadioButton(k, box)
            b.setObjectName("SWBomType" + k.split()[0].replace("-", ""))
            self.bom_type.addButton(b, n)
            lay.addWidget(b)
            b.setChecked(n == 0)
        self.numbering = QtWidgets.QComboBox(box)
        self.numbering.setObjectName("SWBomNumbering")
        self.numbering.addItems(["No numbering", "Detailed numbering", "Flat numbering"])
        self.cut_list = QtWidgets.QCheckBox("Detailed cut list", box)
        self.cut_list.setObjectName("SWBomDetailedCutList")

        self.cut_qty = QtWidgets.QCheckBox("Calculate quantity using BOM quantity", box)
        self.cut_qty.setObjectName("SWBomCutQty")
        self.cut_qty_prop = QtWidgets.QComboBox(box)
        self.cut_qty_prop.setObjectName("SWBomCutQtyProperty")
        self.cut_qty_prop.addItems(list(CUT_QTY_PROPS))
        DL.sets(self.cut_qty, True, self.cut_qty_prop)      # a property picked turns the BOM quantity on

        # rows that do not apply are hidden, never greyed (drawings-land287)
        def cut_qty_on(*a):
            on = not self.cut_list.isHidden() and self.cut_list.isChecked()
            DL.row(self.cut_qty, on)
            DL.row(self.cut_qty_prop, on)
        self.cut_list.toggled.connect(cut_qty_on)
        self.cut_qty.toggled.connect(cut_qty_on)
        self._cut_qty_on = cut_qty_on

        def indented(*a):
            on = self.bom_type.checkedButton() is not None and self.bom_type.checkedButton().text() == "Indented"
            DL.row(self.numbering, on)
            DL.row(self.cut_list, on)
            self._cut_qty_on()
        self.bom_type.buttonToggled.connect(indented)
        indented()                                   # hidden until Indented (never greyed)
        lay.addWidget(self.numbering)
        lay.addWidget(self.cut_list)
        lay.addWidget(self.cut_qty)
        lay.addWidget(self.cut_qty_prop)
        self.lay.addWidget(box)
        box, lay = D._group("Filter", self.form)
        self.filters = {}
        for key, text in BOM_FILTERS:
            c = QtWidgets.QCheckBox(text, box)
            c.setObjectName("SWBomFilter" + key.capitalize())
            lay.addWidget(c)
            self.filters[key] = c
        self.lay.addWidget(box)
        box, lay = D._group("Keep Missing Item/Row", self.form)
        self.keep_missing = QtWidgets.QCheckBox("Keep missing items", box)
        self.keep_missing.setObjectName("SWBomKeepMissing")
        lay.addWidget(self.keep_missing)
        self.strikeout = QtWidgets.QCheckBox("Strikeout", box)
        self.strikeout.setObjectName("SWBomStrikeout")
        DL.sets(self.keep_missing, True, self.strikeout)    # Strikeout ticked keeps the missing rows (never greyed)
        self.strikeout.setChecked(_row(self.doc, "Bill of Materials", "Missing component",
                                       "Display with strikethrough", "bom_missing") == "Display with strikethrough")
        lay.addWidget(self.strikeout)
        self.lay.addWidget(box)
        box, lay = D._group("Configurations", self.form)
        self.configs = QtWidgets.QListWidget(box)
        self.configs.setObjectName("SWBomConfigurations")
        self.configs.setMaximumHeight(90)
        self.configs_note = QtWidgets.QLabel("Click a view to list its model's configurations.", box)
        self.configs_note.setWordWrap(True)
        lay.addWidget(self.configs_note)
        lay.addWidget(self.configs)
        self.lay.addWidget(box)
        box, lay = D._group("Part Configuration Grouping", self.form)
        self.grouping = []
        for n, k in enumerate(CONFIG_GROUPING):

            row = QtWidgets.QHBoxLayout()
            b = QtWidgets.QRadioButton("", box)
            b.setObjectName("SWBomGrouping%d" % n)
            b.setToolTip(k)
            b.setChecked(n == 0)
            label = QtWidgets.QLabel(k, box)
            label.setObjectName("SWBomGroupingText%d" % n)
            label.setWordWrap(True)
            label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
            label.mousePressEvent = lambda _e, b=b: b.setChecked(True)      # the label picks it, as its text did
            row.addWidget(b, 0, QtCore.Qt.AlignTop)
            row.addWidget(label, 1)
            lay.addLayout(row)
            self.grouping.append(b)
        self.lay.addWidget(box)
        box, lay = D._group("Item Numbers", self.form)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Start at:", box))
        self.start = QtWidgets.QSpinBox(box)
        self.start.setObjectName("SWBomStart")
        self.start.setRange(0, 100000)
        self.start.setValue(1)
        row.addWidget(self.start)
        lay.addLayout(row)
        row = QtWidgets.QHBoxLayout()           # its own row: beside Start at it made the pane 341 px wide
        row.addWidget(QtWidgets.QLabel("Increment:", box))
        self.step = QtWidgets.QSpinBox(box)
        self.step.setObjectName("SWBomIncrement")
        self.step.setRange(1, 1000)
        self.step.setValue(1)
        row.addWidget(self.step)
        lay.addLayout(row)
        self.fixed = QtWidgets.QCheckBox("Do not change item numbers", box)
        self.fixed.setObjectName("SWBomFixedNumbers")
        lay.addWidget(self.fixed)
        self.follow = QtWidgets.QCheckBox("Follow assembly order", box)
        self.follow.setObjectName("SWBomFollowOrder")
        self.follow.setChecked(True)
        lay.addWidget(self.follow)
        self.lay.addWidget(box)
        _border_group(self)
        self.view = None
        self.table = None
        if type(self) is BomPanel:
            pre = D.preselected_view(self.page)
            if pre is not None:
                self.view = pre
                self.fit_types()
                several = len(self.fill_configs()) > 1
                if self.attach.isChecked():
                    self.say("%s: %sOK (the table goes to the anchor point)." % (
                        pre.Label, "check the configurations, then " if several else ""))
                else:
                    self.say("%s: %sclick where the table goes." % (
                        pre.Label, "check the configurations, then " if several else ""))

    def fit_types(self):
        ""
        part = self.view is not None and not is_assembly_view(self.view)
        for b in self.bom_type.buttons():
            DL.row(b, not part or b.text() == "Parts only")
            if part and b.text() == "Parts only":
                b.setChecked(True)

    def fill_configs(self):
        ""
        self.configs.clear()
        _t, names, active = model_configurations(self.view)
        for n in names:
            it = QtWidgets.QListWidgetItem(n, self.configs)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if n == active else QtCore.Qt.Unchecked)
        self.configs_note.setText("Check the configurations the table counts." if names else
                                  "The model has one configuration.")
        return names

    def cut_quantity_property(self):
        """Calculate quantity using BOM quantity: the cut list property picked, else "" (count the members)."""
        return self.cut_qty_prop.currentText() if not self.cut_qty.isHidden() and self.cut_qty.isChecked() else ""

    def checked_filters(self):
        return [k for k, c in getattr(self, "filters", {}).items() if c.isChecked()]

    def checked_configs(self):
        out = []
        for i in range(self.configs.count()):
            it = self.configs.item(i)
            if it.checkState() == QtCore.Qt.Checked:
                out.append(it.text())
        return out if self.configs.count() > 1 else []

    def finish(self):
        ""

        if self.table is None and self.view is not None:
            self.make(anchor(self.page, "BOM"), close=False)
            attach(self.table)

    def make(self, at, close=True):
        kind = self.numbering.currentText().split()[0] if not self.numbering.isHidden() else "Detailed"
        self.table = make_bom(self.page, self.view, at, self.bom_type.checkedButton().text(), self.start.value(),
                              self.step.value(), self.template.currentText(), kind, self.keep_missing.isChecked(),
                              self.fixed.isChecked(), not self.cut_list.isHidden() and self.cut_list.isChecked(),
                              self.follow.isChecked(),
                              self.grouping_text(),
                              self.keep_missing.isChecked() and self.strikeout.isChecked(),
                              self.checked_configs(), self.checked_filters(), self.cut_quantity_property())
        _apply_border(self, self.table)
        self.made.append(self.table)
        if close:
            QtCore.QTimer.singleShot(0, self.accept)

    def sheet_click(self, p):
        if self.table is not None:
            return False
        if self.view is None:
            v = DV.view_at(self.page, p)
            if v is None:
                self.say("Click a drawing view.")
                return True
            self.view = v
            self.fit_types()
            several = len(self.fill_configs()) > 1
            if self.attach.isChecked() and not several:
                self.make(anchor(self.page, "BOM"))
                attach(self.table)
                return True
            if self.attach.isChecked():
                self.say("Check the configurations, then OK (the table goes to the anchor point).")
                return True
            self.say("Check the configurations, then click where the table goes." if several else
                     "Click where the table goes.")
            return True
        if self.attach.isChecked():
            return True
        self.make(p)
        self._place_top_left(p)
        return True


    # pointer), and its outline follows the pointer until that click
    def _place_top_left(self, p):
        try:
            from . import drawtableedit
            drawtableedit.place_corner(self.table, "Top Left", p)
        except Exception as _fw_err:
            _fw_log("drawtables.py:BOM place top left", _fw_err)
        self._ghost_off()

    def _ghost_size(self):
        key = (self.view, self.bom_type.checkedButton().text(), self.template.currentText())
        kept = getattr(self, "_bom_ghost", None)
        if kept is None or kept[0] != key:
            from . import drawtableedit
            try:
                n = len(bom_rows(self.view, key[1], 1, 1, key[2]))
            except Exception:
                n = 3
            k = drawtableedit.K
            kept = self._bom_ghost = (key, (sum(bom_widths(key[2])) * k, max(2, n) * 20.0 * k))
        return kept[1]

    def _ghost_off(self):
        try:
            self.clicks.ghost(None)
        except Exception as _fw_err:
            _fw_log("drawtables.py:BOM ghost off", _fw_err)

    def sheet_move(self, p):
        if getattr(self, "edit_table", None) is not None:
            return
        if self.table is not None or self.view is None or self.attach.isChecked():
            self._ghost_off()
            return
        try:
            w, h = self._ghost_size()
            self.clicks.ghost((p[0] + w / 2.0, p[1] - h / 2.0), (w, h))
        except Exception as _fw_err:
            _fw_log("drawtables.py:BOM ghost", _fw_err)


class BomEditPanel(BomPanel):
    ""


    def __init__(self, page, table):
        self.edit_table = table
        super().__init__(page)
        try:
            self.doc.abortTransaction()      # nothing until OK: picking the table and leaving is not an undo step
        except Exception as _fw_err:
            _fw_log("drawtables.py:1490", _fw_err)
        self.corner_row(table)
        self.load(table)
        self.made = [table]                  # ending this PM (another command, another pick) keeps the change
        self.say("Change the table's settings, then OK.")

    def corner_row(self, t):
        ""

        from . import drawtableedit as TE
        box = self.attach.parentWidget()
        lay = box.layout()
        lay.addWidget(QtWidgets.QLabel("Stationary corner:", box))
        row = QtWidgets.QHBoxLayout()
        self.corner = QtWidgets.QButtonGroup(box)
        cur = TE.anchor_corner(t)
        for n, name in enumerate(TE.CORNERS):
            b = QtWidgets.QToolButton(box)
            b.setText(name)
            b.setToolTip(name)
            b.setCheckable(True)
            b.setObjectName("SWTableCorner" + name.replace(" ", ""))
            b.setChecked(name == cur)
            self.corner.addButton(b, n)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

    def load(self, t):
        self.view = t.Document.getObject(getattr(t, "SWBomView", "") or "")
        self.table = t
        self.template.setCurrentText(getattr(t, "SWBomTemplate", "bom-standard"))
        self.attach.setChecked(bool(getattr(t, "SWAttachedToAnchor", False)))
        kind = getattr(t, "SWBomType", "Top-level only")
        for b in self.bom_type.buttons():
            b.setChecked(b.text() == kind)
        if self.view is not None and not is_assembly_view(self.view):
            for b in self.bom_type.buttons():
                DL.row(b, b.text() == kind or b.text() == "Parts only")
        num = getattr(t, "SWBomNumbering", "Detailed")
        for i in range(self.numbering.count()):
            if self.numbering.itemText(i).split()[0] == num:
                self.numbering.setCurrentIndex(i)
        self.cut_list.setChecked(bool(getattr(t, "SWBomCutList", False)))
        cq = getattr(t, "SWBomCutQty", "") or ""
        self.cut_qty.setChecked(bool(cq))
        if cq:
            self.cut_qty_prop.setCurrentText(cq)
        self._cut_qty_on()
        self.keep_missing.setChecked(bool(getattr(t, "SWBomKeepMissing", False)))
        self.strikeout.setChecked(bool(getattr(t, "SWBomStrikeout", False)))
        group = getattr(t, "SWBomGrouping", CONFIG_GROUPING[0])
        for n, b in enumerate(self.grouping):
            b.setChecked(CONFIG_GROUPING[n] == group)
        self.start.setValue(int(getattr(t, "SWBomStart", 1)))
        self.step.setValue(int(getattr(t, "SWBomStep", 1)))
        self.fixed.setChecked(bool(getattr(t, "SWBomFixedNumbers", False)))
        self.follow.setChecked(bool(getattr(t, "SWBomFollowOrder", True)))
        hidden = list(getattr(t, "SWBomFilter", []) or [])
        for k, c in self.filters.items():
            c.setChecked(k in hidden)
        for c, name in ((self.box_border, "SWBoxBorder"), (self.grid_border, "SWGridBorder")):
            if name in t.PropertiesList:
                c.setCurrentText("%gmm" % float(getattr(t, name)))
        if getattr(self, "border_doc", None) is not None:
            self.border_doc.setChecked(bool(getattr(t, "SWBorderFromDoc", False)))
        if getattr(self, "all_upper", None) is not None and "SWAllUppercase" in t.PropertiesList:
            self.all_upper.setChecked(bool(t.SWAllUppercase))
        if self.view is not None:
            self.fill_configs()
            want = list(getattr(t, "SWBomConfigurations", []) or [])
            if want:
                for i in range(self.configs.count()):
                    it = self.configs.item(i)
                    it.setCheckState(QtCore.Qt.Checked if it.text() in want else QtCore.Qt.Unchecked)
        self.loaded = self.settings()

    def settings(self):
        kind = self.bom_type.checkedButton().text() if self.bom_type.checkedButton() is not None else "Top-level only"
        return {"SWBomTemplate": self.template.currentText(), "SWBomType": kind,
                "SWBomNumbering": self.numbering.currentText().split()[0] if kind == "Indented" else
                getattr(self.edit_table, "SWBomNumbering", "Detailed"),
                "SWBomCutList": kind == "Indented" and self.cut_list.isChecked(),
                "SWBomCutQty": self.cut_quantity_property() if kind == "Indented" and self.cut_list.isChecked() else "",
                "SWBomKeepMissing": self.keep_missing.isChecked(),
                "SWBomStrikeout": self.keep_missing.isChecked() and self.strikeout.isChecked(),
                "SWBomGrouping": self.grouping_text(),
                "SWBomStart": self.start.value(), "SWBomStep": self.step.value(),
                "SWBomFixedNumbers": self.fixed.isChecked(), "SWBomFollowOrder": self.follow.isChecked(),
                "SWBomConfigurations": self.checked_configs(),
                "SWBomFilter": self.checked_filters(),
                "SWBoxBorder": float(self.box_border.currentText()[:-2]),
                "SWGridBorder": float(self.grid_border.currentText()[:-2]),
                "SWBorderFromDoc": self.border_doc.isChecked(), "SWAllUppercase": self.all_upper.isChecked(),
                "SWAttachedToAnchor": self.attach.isChecked(),
                "SWAnchorCorner": self.corner.checkedButton().text() if getattr(self, "corner", None) is not None
                and self.corner.checkedButton() is not None else getattr(self.edit_table, "SWAnchorCorner", "")}

    def sheet_click(self, p):
        return False                         # clicks go on to the sheet (another table, a view, a cell)

    def finish(self):
        t = self.edit_table
        now = self.settings()
        if now == self.loaded or t is None:
            return
        apply_bom_settings(t, now)


def apply_bom_settings(t, settings):
    """The BOM PM's settings on an existing Bill of Materials, then Update Table (one undo step)."""
    doc = t.Document
    doc.openTransaction("Bill of Materials")
    try:
        if settings.get("SWBomTemplate", getattr(t, "SWBomTemplate", "")) != getattr(t, "SWBomTemplate", "") \
                and getattr(t, "SWBomColumns", ""):
            t.SWBomColumns = ""
        corner = settings.get("SWAnchorCorner", "")
        if corner:
            from . import drawtableedit
            drawtableedit.set_anchor_corner(t, corner)      # Stationary corner
        for name, val in settings.items():
            if name in ("SWBoxBorder", "SWGridBorder", "SWAttachedToAnchor", "SWAnchorCorner"):
                continue
            if name not in t.PropertiesList:
                kind = {bool: "App::PropertyBool", int: "App::PropertyInteger",
                        list: "App::PropertyStringList"}.get(type(val), "App::PropertyString")
                t.addProperty(kind, name, "FreeCAD", "Bill of Materials settings")
            setattr(t, name, val)
        set_border(t, settings.get("SWBoxBorder", 0.35), settings.get("SWGridBorder", 0.18))
        set_attached(t, settings.get("SWAttachedToAnchor", False))
        update_table(t)
    finally:
        doc.commitTransaction()
    doc.recompute()


def edit_bom(t):
    ""
    page = None
    try:
        from . import drawtableedit
        page = drawtableedit.page_of(t)
    except Exception as _fw_err:
        _fw_log("drawtables.py:1597", _fw_err)
    page = page or D.active_page()
    if page is None:
        return None
    return D._show(BomEditPanel(page, t))


# --------------------------------------------------------------------------- Hole Table
HOLE_WIDTHS = (50, 80, 80, 140)



LETTER_DRILLS = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", (
    .234, .238, .242, .246, .250, .257, .261, .266, .272, .277, .281, .290, .295, .302, .316, .323, .332, .339,
    .348, .358, .368, .377, .386, .397, .404, .413)))
NUMBER_DRILLS = dict(zip(range(1, 61), (
    .228, .221, .213, .209, .2055, .204, .201, .199, .196, .1935, .191, .189, .185, .182, .180, .177, .173, .1695,
    .166, .161, .159, .157, .154, .152, .1495, .147, .144, .1405, .136, .1285, .120, .116, .113, .111, .110, .1065,
    .104, .1015, .0995, .098, .096, .0935, .089, .086, .082, .081, .0785, .076, .073, .070, .067, .0635, .0595,
    .055, .052, .0465, .043, .042, .041, .040)))


def ansi_drill(diameter_mm, tol=0.0006):
    """The ANSI letter or number drill (e.g. "F", "#7") of a diameter in mm, else ""."""
    inch = diameter_mm / 25.4
    best = None
    for name, size in list(LETTER_DRILLS.items()) + [("#%d" % n, v) for n, v in NUMBER_DRILLS.items()]:
        d = abs(size - inch)
        if d <= tol and (best is None or d < best[0]):
            best = (d, name)
    return best[1] if best else ""


def hole_rows(view, origin, control="Alpha", start="A", combine_sizes=False, combine_tags=False, picked=None,
              ansi=False, header=True):
    ""




    holes = []
    every = [(c, r) for _i, c, r in DA.circles(view)]
    for i, c, r in DA.circles(view):
        if any((c - h[1]).Length < 1e-6 and abs(r - h[2]) < 1e-6 for h in holes):
            continue
        if DA.part_of_hole(view, c, r, every):
            continue                       # a counterbore's rim: the hole is listed once, by its drill
        if picked and not any((V(c.x, c.y, 0) - V(q.x, q.y, 0)).Length < 1e-3 for q in picked):
            continue
        holes.append((i, c, r))
    sizes = sorted({round(2 * r, 6) for _, _, r in holes})
    rows = [["TAG", "X LOC", "Y LOC", "SIZE"] + (["QTY"] if combine_sizes else [])]
    tags = []
    numeric = control == "Numerical"
    try:
        n0 = int(start) if numeric else 0
    except Exception:
        n0 = 1
    letter = (str(start) or "A")[:1].upper() if not numeric else "A"
    if not letter.isalpha():
        letter = "A"
    count = n0
    doc = getattr(view, "Document", None)

    # default .12; drawings-land279); an explicit Tables > Hole precision wins
    digits = radius_digits(doc) if doc is not None else 2
    from . import optionspages as OP
    if doc is not None and OP.DOC_META + OP._store_key("Hole", "Precision") in dict(getattr(doc, "Meta", {}) or {}):
        precision = str(_row(doc, "Hole", "Precision", ".12"))
        try:
            digits = int(precision) if "." not in precision else len(precision.split(".", 1)[1])
        except (TypeError, ValueError):
            digits = 2
        digits = max(0, min(12, digits))
    for si, size in enumerate(sizes):
        same = sorted([h for h in holes if abs(2 * h[2] - size) < 1e-6], key=lambda h: (-h[1].y, h[1].x))
        for n, (i, c, r) in enumerate(same):
            if combine_tags:
                tag = str(n0 + si) if numeric else letter
            elif numeric:
                tag = str(count)
                count += 1
            else:
                tag = "%s%d" % (letter, n + 1)
            text = DA.hole_text(view, c, r).replace("%.2w", "%.*f" % (digits, 2 * r)).replace("%%", "%")
            text = re.sub(r"^\d+X ", "", text)      # one row per hole: the callout's "2X" count is not written
            if ansi:
                drill = ansi_drill(2 * r)
                if drill:
                    text += " (%s)" % drill
            fx = lambda v: "%.*f" % (digits, 0.0 if abs(v) < 0.5 * 10 ** -digits else v)    # no "-0.00"
            row = [tag, fx(c.x - origin.x), fx(c.y - origin.y), text]
            if combine_sizes:
                if n == 0:
                    row.append(str(len(same)))
                else:
                    row[3] = ""
                    row.append("")
            rows.append(row)
            tags.append((tag, c, r))
        if not numeric:
            letter = DV._next_letter(letter) if hasattr(DV, "_next_letter") else chr(ord(letter) + 1)
    if not header:
        rows = rows[1:]
    return rows, tags


def _next_start(tags, control):
    """Where the tags of the next view's holes start (Next View): after the last letter or number used."""
    if not tags:
        return "1" if control == "Numerical" else "A"
    if control == "Numerical":
        try:
            return str(max(int(t) for t, c, r in tags) + 1)
        except Exception as _fw_err:
            _fw_log("drawtables.py:1765", _fw_err)
            return "1"
    last = max(t.rstrip("0123456789") for t, c, r in tags)
    return DV._next_letter(last)


def more_sets(t):
    """Next View: the other views' holes of a Hole Table [(view name, origin, [picked centres])]."""
    out = []
    for text in list(getattr(t, "SWHoleMore", []) or []):
        try:
            name, org, pts = text.split("|")
            ox, oy = (float(x) for x in org.split(","))
            picked = [V(*[float(x) for x in q.split(",")], 0) for q in pts.split(";") if q]
            out.append((name, V(ox, oy, 0), picked))
        except Exception as _fw_err:
            _fw_log("drawtables.py:1725", _fw_err)
    return out


def all_hole_rows(view, origin, more=(), **opts):
    """The rows of a Hole Table over its view and the views added with Next View (tags go on from view to view)."""
    rows, tags = hole_rows(view, origin, **opts)
    doc = view.Document
    for name, org, picked in more:
        v = doc.getObject(name)
        if v is None:
            continue
        o2 = dict(opts, picked=picked or None, start=_next_start(tags, opts.get("control", "Alpha")), header=False)
        r2, t2 = hole_rows(v, org, **o2)
        rows += r2
        tags += t2
    return rows, tags


def hole_options(t):
    return {"control": getattr(t, "SWHoleControl", "Alpha"), "start": getattr(t, "SWHoleStart", "A"),
            "combine_sizes": getattr(t, "SWHoleCombineSizes", False),
            "combine_tags": getattr(t, "SWHoleCombineTags", False),
            "picked": list(getattr(t, "SWHolePicked", []) or []) or None,
            "ansi": getattr(t, "SWHoleAnsi", False)}


def tag_merges(rows):
    """Combine same tags: the rows of one tag keep it in their first row, the TAG cells merged down."""
    rows = [list(r) for r in rows]
    merged = []
    r = 1
    while r < len(rows):
        e = r
        while e + 1 < len(rows) and rows[e + 1][0] == rows[r][0]:
            e += 1
        if e > r:
            for k in range(r + 1, e + 1):
                rows[k][0] = ""
            merged.append("%d,0,%d,0" % (r, e))
        r = e + 1
    return rows, merged


def write_hole_rows(t, rows):
    if getattr(t, "SWHoleCombineTags", False):
        from . import drawtableedit
        rows, merged = tag_merges(rows)
        drawtableedit.write(t, rows, hole_widths(t), None, merged)
        if "SWMerges" not in t.PropertiesList:
            t.addProperty("App::PropertyStringList", "SWMerges", "FreeCAD", "merged cells r0,c0,r1,c1 (logical)")
        t.SWMerges = merged
        t.Document.recompute()
    else:
        set_rows(t, rows, hole_widths(t))


def hole_widths(t=None, combine=None):
    combine = getattr(t, "SWHoleCombineSizes", False) if combine is None else combine
    return HOLE_WIDTHS + ((40,) if combine else ())


def _origin_model_point(view, origin, tol=0.05):
    """The model vertex that shows at origin (view geometry) in view, else None."""
    try:
        best = None
        for sh in DV.source_shapes(view):
            for vx in getattr(getattr(sh, "Shape", sh), "Vertexes", []):
                q = DA._project(view, vx.Point)
                dd = ((q.x - origin.x) ** 2 + (q.y - origin.y) ** 2) ** 0.5
                if dd < tol and (best is None or dd < best[0]):
                    best = (dd, vx.Point)
        return best[1] if best else None
    except Exception:
        return None


def keep_origin(t, view, origin):
    ""
    p = _origin_model_point(view, V(origin))
    if p is None:
        return
    if "SWHoleOriginModel" not in t.PropertiesList:
        t.addProperty("App::PropertyVector", "SWHoleOriginModel", "FreeCAD", "Hole Table origin (model vertex)")
    t.SWHoleOriginModel = p


def hole_origin(t, view):
    """The table's origin in view geometry now: its model vertex projected again, else the stored point."""
    o = V(t.SWHoleOrigin)
    if "SWHoleOriginModel" in t.PropertiesList:
        try:
            q = DA._project(view, V(t.SWHoleOriginModel))
            return q
        except Exception as _fw_err:
            _fw_log("drawtables.py:1820", _fw_err)
    return o


def make_hole_table(page, view, origin, at, control="Alpha", start="A", combine_sizes=False, centres=False,
                    combine_tags=False, datum="Vertex", picked=None, ansi=False, more=()):
    """A Hole Table of view's holes (picked: only those centres, view geometry; else all) measured from origin;
    more: Next View's [(view name, origin, picked)]."""
    rows, tags = all_hole_rows(view, origin, more, control=control, start=start, combine_sizes=combine_sizes,
                               combine_tags=combine_tags, picked=picked, ansi=ansi)
    t = make_table(page, rows, at, "Hole Table%d" % (1 + len(
        [o for o in page.Document.Objects if getattr(o, "SWTable", "") == "Hole"])), "Hole",
        hole_widths(combine=combine_sizes))
    t.addProperty("App::PropertyString", "SWHoleView", "FreeCAD", "Hole Table view")
    t.SWHoleView = view.Name
    t.addProperty("App::PropertyVector", "SWHoleOrigin", "FreeCAD", "Hole Table origin (view geometry)")
    t.SWHoleOrigin = origin
    keep_origin(t, view, origin)
    for name, kind, val in (("SWHoleControl", "App::PropertyString", control),
                            ("SWHoleStart", "App::PropertyString", str(start)),
                            ("SWHoleCombineSizes", "App::PropertyBool", combine_sizes),
                            ("SWHoleCombineTags", "App::PropertyBool", combine_tags),
                            ("SWHoleDatum", "App::PropertyString", datum),
                            ("SWHolePicked", "App::PropertyVectorList", list(picked or [])),
                            ("SWHoleAnsi", "App::PropertyBool", bool(ansi)),
                            ("SWHoleMore", "App::PropertyStringList",
                             ["%s|%r,%r|%s" % (n, o.x, o.y, ";".join("%r,%r" % (q.x, q.y) for q in (pk or [])))
                              for n, o, pk in more])):
        t.addProperty(kind, name, "FreeCAD", "Hole Table settings")
        setattr(t, name, val)
    if combine_tags:
        write_hole_rows(t, rows)
    if _row(page.Document, "Hole", "Origin indicator", "Per Standard", "hole_origin") != "None":
        origin_indicator(page, view, origin, t)

    x0, y0 = D.view_position(view)
    k = DV.view_scale(view)
    n_first = len(hole_rows(view, origin, control=control, start=start, combine_sizes=combine_sizes,
                            combine_tags=combine_tags, picked=picked)[1])
    places = [(view, tg) for tg in tags[:n_first]]
    rest = tags[n_first:]
    for name, org, pk in more:
        v2 = page.Document.getObject(name)
        if v2 is None:
            continue
        n2 = len(hole_rows(v2, org, picked=pk or None)[1])
        places += [(v2, tg) for tg in rest[:n2]]
        rest = rest[n2:]
    for hv, (tag, c, r) in places:
        x0, y0 = D.view_position(hv)
        k = DV.view_scale(hv)
        at2 = (x0 + (c.x + r * 0.8) * k + 3, y0 + (c.y + r * 0.8) * k + 2)
        s = DA.svg_symbol(page, "HoleTag", '<text x="0" y="1.2" font-family="osifont, Arial" font-size="3.5" '
                          'text-anchor="middle">%s</text>' % tag, 3, at2, "Hole Tag %s" % tag, "HoleTag")
        s.addProperty("App::PropertyString", "SWHoleTag", "FreeCAD", "Hole Table tag")
        s.SWHoleTag = tag
        if centres:
            try:
                DA.center_mark(hv, c, r)
            except Exception as _fw_err:
                _fw_log("drawtables.py:1880", _fw_err)
    page.Document.recompute()
    return t


def origin_indicator(page, view, origin, table=None):
    """The Hole Table's origin indicator: X and Y arrows from the datum the holes are measured from."""
    x0, y0 = D.view_position(view)
    k = DV.view_scale(view)
    at = (x0 + origin.x * k, y0 + origin.y * k)
    L = 10.0
    body = ('<g stroke="#000" stroke-width="0.25" fill="none"><path d="M0 0 L%g 0 M0 0 L0 %g"/></g>'
            '<path d="M%g 0 L%g -1 L%g 1 Z M0 %g L-1 %g L1 %g Z" fill="#000"/>'
            '<text x="%g" y="1.2" font-family="osifont, Arial" font-size="3">X</text>'
            '<text x="-1" y="%g" font-family="osifont, Arial" font-size="3">Y</text>'
            % (L, -L, L, L - 2.5, L - 2.5, -L, -L + 2.5, -L + 2.5, L + 1, -L - 1))
    s = DA.svg_symbol(page, "HoleOrigin", body, L + 4, at, "Origin Indicator", "HoleOrigin")
    s.addProperty("App::PropertyString", "SWHoleOriginOf", "FreeCAD", "the Hole Table it marks")
    s.SWHoleOriginOf = table.Name if table is not None else ""
    return s


class HoleTablePanel(D._Panel):
    TITLE = "Hole Table"
    LAYER = True
    GROUP_ORDER = ("Table Template", "Table Position", "Tag Type", "Holes", "Scheme", "Border",
                   "Layer")
    PIXMAP = "TechDraw_SpreadsheetView"
    KIND = "Hole"

    def build(self):
        self.say("Click the origin (a corner of the part, or an X axis edge then a Y axis edge) in a view, then "
                 "click where the table goes (or it goes to the anchor point).")
        _template_group(self, ("standard hole table--letters", "standard hole table--numbers"),
                        "standard hole table--letters")
        _position_group(self, False)
        box, lay = D._group("Tag Type", self.form)
        self.alpha = QtWidgets.QRadioButton("A, B, C...", box)
        self.alpha.setObjectName("SWHoleAlpha")
        self.numeric = QtWidgets.QRadioButton("1, 2, 3...", box)
        self.numeric.setObjectName("SWHoleNumeric")
        self.alpha.setChecked(True)
        self.start = QtWidgets.QLineEdit("A", box)
        self.start.setObjectName("SWHoleStart")
        self.numeric.toggled.connect(lambda on: self.start.setText("1" if on else "A"))
        if _row(self.doc, "Hole", "Alpha/numerical control", "A, B, C...", "hole_alpha") == "1, 2, 3..." or \
                _row(self.doc, "Hole", "Scheme", "Letters") == "Numbers":
            self.numeric.setChecked(True)          # Scheme Numbers: the numbered hole table template's tags
        self.template.currentTextChanged.connect(lambda t: (self.numeric if "numbers" in t else self.alpha).setChecked(True))
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Start at:", box))
        row.addWidget(self.start)
        lay.addWidget(self.alpha)
        lay.addWidget(self.numeric)
        lay.addLayout(row)
        self.lay.addWidget(box)
        box, lay = D._group("Scheme", self.form)
        self.combine_sizes = QtWidgets.QCheckBox("Combine same sizes", box)
        self.combine_sizes.setObjectName("SWHoleCombineSizes")
        self.centres = QtWidgets.QCheckBox("Show hole centers", box)
        self.centres.setObjectName("SWHoleCentres")
        self.combine_tags = QtWidgets.QCheckBox("Combine same tags", box)
        self.combine_tags.setObjectName("SWHoleCombineTags")
        self.combine_tags.setChecked(_row(self.doc, "Hole", "Combine same tags", False))
        self.ansi = QtWidgets.QCheckBox("Show ANSI inch letter and\nnumber drill sizes", box)     # two lines: fits 300 px
        self.ansi.setObjectName("SWHoleAnsi")
        lay.addWidget(self.ansi)
        lay.addWidget(self.combine_tags)
        lay.addWidget(self.combine_sizes)
        lay.addWidget(self.centres)
        self.lay.addWidget(box)

        box, lay = D._group("Holes", self.form)
        self.hole_list = QtWidgets.QListWidget(box)
        self.hole_list.setObjectName("SWHoleList")
        self.hole_list.setMaximumHeight(110)
        lay.addWidget(self.hole_list)
        self.next_view = QtWidgets.QPushButton("Next View", box)
        self.next_view.setObjectName("SWHoleNextView")
        self.next_view.setVisible(False)             # shown once the datum is set (never greyed)
        self.next_view.clicked.connect(self.go_next_view)
        lay.addWidget(self.next_view)
        self.lay.addWidget(box)
        _border_group(self)
        self.view = None
        self.origin = None
        self.table = None
        self.edge_x = None
        self.datum = "Vertex"
        self.picked = []
        self.more = []

    def options(self):
        return ("Numerical" if self.numeric.isChecked() else "Alpha", self.start.text().strip() or
                ("1" if self.numeric.isChecked() else "A"), self.combine_sizes.isChecked(), self.centres.isChecked(),
                self.combine_tags.isChecked(), self.datum)

    def sets(self):
        """(main view, origin, picked, Next View's other views) over what has been picked."""
        done = list(self.more)
        if self.view is not None and self.origin is not None:
            done.append((self.view.Name, self.origin, list(self.picked)))
        if not done:
            return None
        name, org, pk = done[0]
        return self.doc.getObject(name), org, pk, done[1:]

    def make(self, at, close=True):
        st = self.sets()
        if st is None:
            return
        view, origin, picked, more = st
        self.table = make_hole_table(self.page, view, origin, at, *self.options(), picked=picked or None,
                                     ansi=self.ansi.isChecked(), more=more)
        _apply_border(self, self.table)
        self.made.append(self.table)
        if close:
            QtCore.QTimer.singleShot(0, self.accept)

    def refresh_holes(self):
        self.hole_list.clear()
        for name, org, pk in self.more + ([(self.view.Name, self.origin, self.picked)] if self.view else []):
            v = self.doc.getObject(name)
            label = v.Label if v is not None else name
            if not pk:
                self.hole_list.addItem("%s: all holes" % label)
            for q in pk:
                self.hole_list.addItem("%s: hole at %g, %g" % (label, round(q.x - org.x, 2), round(q.y - org.y, 2)))
        self.next_view.setVisible(self.view is not None and self.origin is not None)

    def pick_hole(self, v, p):
        """A click in the datum's view: on a hole's edge picks that hole (again: drops it); elsewhere on the view
        (a face) picks all its holes."""
        g = DV.to_geometry(v, p)
        k = DV.view_scale(v)
        # the hole's rim, not a center mark's line ending on it (center marks go in by themselves)
        hit = DA.circle_at(v, g, 2.0 / k)
        circle = None
        if hit is not None:
            c = hit[1]
            circle = V(c.x, c.y, 0)
        if circle is None:
            self.picked = [c for i, c, r in DA.circles(v)]
            self.say("All holes of the face picked. Pick more holes, Next View, or click where the table goes.")
        else:
            same = [q for q in self.picked if (q - circle).Length < 1e-3]
            if same:
                self.picked = [q for q in self.picked if q not in same]
            else:
                self.picked.append(circle)
            self.say("%d hole(s) picked. Pick more, Next View, or click where the table goes (OK: at the anchor)."
                     % len(self.picked))
        self.refresh_holes()
        return True

    def go_next_view(self):
        """Next View: the holes picked so far are kept; pick the origin and the holes in another view."""
        if self.view is None or self.origin is None:
            return
        self.more.append((self.view.Name, self.origin, list(self.picked)))
        self.view, self.origin, self.picked, self.edge_x = None, None, [], None
        self.refresh_holes()
        self.say("Next View: click the origin in another view, then its holes.")

    def finish(self):
        # OK before the table is placed: it goes to the anchor point (Attach to anchor point) or below the view
        if self.table is None and self.sets() is not None:
            self.make(anchor(self.page, self.KIND), close=False)
            if self.attach.isChecked():
                attach(self.table)

    def pick_origin(self, p):
        v = DV.view_at(self.page, p)
        if v is None:
            self.say("Click a vertex inside a drawing view for the origin.")
            return True
        g = DV.to_geometry(v, p)
        k = DV.view_scale(v)
        best = None
        for i, q in DA.vertices(v):
            dist = math.hypot(q.x - g[0], q.y - g[1])
            if best is None or dist < best[0]:
                best = (dist, q)
        if best is None or best[0] > 3.0 / k:
            hit = DA.edge_at(v, g, 2.0 / k)
            line = _line_of(hit[1]) if hit else None
            if line is None:
                self.say("Click on a vertex (a corner) for the origin, or a straight edge for the X axis.")
                return True
            if self.edge_x is None or self.edge_x[0] is not v:
                self.edge_x = (v, line)
                self.say("X axis edge picked. Click the Y axis edge.")
                return True
            o = _intersect(self.edge_x[1], line)
            if o is None:
                self.say("The edges are parallel. Click a Y axis edge across the X axis edge.")
                return True
            self.view, self.origin, self.datum = v, V(o[0], o[1], 0), "Edges"
        else:
            self.view, self.origin = v, V(best[1].x, best[1].y, 0)
        self.picked = []
        self.refresh_holes()
        if self.attach.isChecked():
            self.say("Pick the holes (edges, or a face for all its holes), then OK: the table goes to the anchor.")
        else:
            self.say("Pick the holes (edges, or a face for all its holes; none: all), then click where the table "
                     "goes.")
        return True

    def sheet_click(self, p):
        if self.table is not None:
            return False
        if self.view is None:
            return self.pick_origin(p)
        v = DV.view_at(self.page, p)
        if v is self.view:
            return self.pick_hole(v, p)
        if v is not None:
            self.say("Click Next View to pick holes in another view.")
            return True
        if self.attach.isChecked():
            self.make(anchor(self.page, self.KIND), close=False)
            attach(self.table)
            QtCore.QTimer.singleShot(0, self.accept)
            return True
        self.make(p)
        return True


def _line_of(e):
    """A straight edge's two end points in view geometry, else None."""
    try:
        if type(e.Curve).__name__ not in ("Line", "LineSegment"):
            return None
        a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
        return (a.x, a.y), (b.x, b.y)
    except Exception:
        return None


def _intersect(l1, l2):
    """Where the lines through two edges meet (the datum of an X axis and a Y axis edge), else None."""
    (x1, y1), (x2, y2) = l1
    (x3, y3), (x4, y4) = l2
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-9:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    return x1 + t * (x2 - x1), y1 + t * (y2 - y1)


# --------------------------------------------------------------------------- Revision Table
REV_WIDTHS = (50, 50, 220, 90, 90)


def revision_table(page):
    return next((o for o in page.Views if getattr(o, "SWTable", "") == "Revision"), None)


REV_SHAPES = ("Circle", "Triangle", "Square", "Hexagon")


def attach(t):
    """A table made at its anchor point: on the anchor set with Set as Anchor, else on the sheet format's own
    (the BOM on the title block, the revision table in the top right corner...), by its anchor corner; it stays
    attached (grows away from the anchor as rows come and go)."""
    if t is None:
        return
    page = next((o for o in t.InList if o.TypeId == "TechDraw::DrawPage"), None)
    if page is None:
        return
    from . import drawtableedit
    if t.SWTable in drawtableedit.anchors(page) or drawtableedit.format_anchor(page, t.SWTable) is not None:
        set_attached(t, True)
        t.Document.recompute()
        drawtableedit.attach_to_anchor(t)


REV_MULTI = ("See Sheet 1", "Linked", "Independent")
REV_HEADER = ["ZONE", "REV.", "DESCRIPTION", "DATE", "APPROVED"]
REV_TITLE = "REVISIONS"


def _pages(doc):
    return [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage"]


def revision_tables(doc):
    """Every sheet's revision table, in sheet order."""
    out = []
    for pg in _pages(doc):
        t = revision_table(pg)
        if t is not None:
            out.append(t)
    return out


def _rev_rows_for(page, multi):
    """Multi-sheet style: See Sheet 1 (the other sheets' tables point to the first sheet's), Linked (every linked
    table holds the same revisions) or Independent (each sheet its own)."""
    others = [t for t in revision_tables(page.Document) if t.InList and page not in t.InList]
    if multi == "See Sheet 1" and others and _pages(page.Document).index(page) > 0:
        return [REV_HEADER, ["", "", "SEE SHEET 1", "", ""]]
    if multi == "Linked":
        linked = [t for t in others if getattr(t, "SWRevMultiSheet", "") == "Linked"]
        if linked:
            return rows_of(linked[0])
    return [list(REV_HEADER)]


def make_revision_table(page, at=None, shape="Triangle", control="Alpha", auto_symbol=None, multi="See Sheet 1"):
    attach_it = at is None
    if auto_symbol is None:         # extapps83: System Options > Drawings > Enable symbol when adding new revision
        auto_symbol = bool(_drawing_option("Enable symbol when adding new revision", True))
    if at is None:
        at = anchor(page, "Revision")
    t = make_table(page, _rev_rows_for(page, multi), at, "Revision Table%d" % (1 + len(
        [o for o in page.Document.Objects if getattr(o, "SWTable", "") == "Revision"])), "Revision", REV_WIDTHS)
    set_title(t, REV_TITLE)
    for name, kind, val in (("SWRevShape", "App::PropertyString", shape),
                            ("SWRevControl", "App::PropertyString", control),
                            ("SWRevAutoSymbol", "App::PropertyBool", auto_symbol),
                            ("SWRevMultiSheet", "App::PropertyString", multi)):
        t.addProperty(kind, name, "FreeCAD", "Revision Table settings")
        setattr(t, name, val)
    if attach_it:
        attach(t)
    return t


def _next_revision(last, control):
    if control == "Numerical":
        try:
            return str(int(last) + 1) if last else "1"
        except Exception:
            return "1"
    return DV._next_letter(last) if last else "A"


def add_revision(page, description="", approved=""):
    """Add Revision: the next revision (A, B, C or 1, 2, 3 as the table is set), today's date, one more row."""
    t = revision_table(page) or make_revision_table(page)
    if getattr(t, "SWRevMultiSheet", "") == "See Sheet 1":
        first = revision_tables(page.Document)
        if first and first[0] is not t:
            t = first[0]                    # the revision goes in the first sheet's table
    rows = rows_of(t)
    if len(rows) == 2 and rows[1][2] == "SEE SHEET 1":
        rows = rows[:1]
    last = rows[-1][1] if len(rows) > 1 else ""
    rev = _next_revision(last, getattr(t, "SWRevControl", "Alpha"))
    rows.append(["", rev, description, datetime.date.today().strftime("%m/%d/%Y"), approved])
    set_rows(t, rows, REV_WIDTHS)
    if getattr(t, "SWRevMultiSheet", "") == "Linked":
        for o in revision_tables(page.Document):
            if o is not t and getattr(o, "SWRevMultiSheet", "") == "Linked":
                set_rows(o, rows, REV_WIDTHS)
    set_revision_property(page.Document, rev)
    return rev


def _drawing_option(text, default):
    """extapps83: Tools > Options > System Options > Drawings: that row's kept value."""
    try:
        from . import optionspages
        return optionspages.stored("Drawings", text, default)
    except Exception:
        return default


def set_revision_property(doc, rev):
    ""

    # extapps83: the property's name is System Options > Drawings > Custom property used as Revision
    prop = str(_drawing_option("Custom property used as Revision", "Revision") or "").strip() or "Revision"
    try:
        meta = dict(doc.Meta)
        meta[prop] = str(rev)
        doc.Meta = meta
    except Exception as _fw_err:
        _fw_log("drawtables.py:2299", _fw_err)
        return
    try:
        from . import customprops
        rows = list(customprops.read(doc))
        for i, (n, k, _v) in enumerate(rows):
            if n == prop:
                rows[i] = (n, k, str(rev))
                break
        else:
            rows.append((prop, "Text", str(rev)))
        customprops.write(doc, rows)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Revision property: %s\n" % error)
    for page in [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage"]:
        try:
            from . import drawlayout
            links = drawlayout.field_links(page)
            soft = set(drawlayout.soft_fields(page))
            moved = {k: '$PRP:"%s"' % prop for k, v in links.items()
                     if k in soft and v.replace(" ", "") == '$PRPSHEET:"Revision"'}
            if moved:               # the sheet format's default REV link: the revision table's revision now
                links.update(moved)
                drawlayout.set_field_links(page, links)
            drawlayout.refresh_fields(page)
        except Exception as _fw_err:
            _fw_log("drawtables.py:2268", _fw_err)
        for o in list(page.Views):
            if getattr(o, "SWTable", "") == "TitleBlock":
                try:
                    update_table(o)
                except Exception as _fw_err:
                    _fw_log("drawtables.py:2274", _fw_err)


class RevisionTablePanel(D._Panel):
    TITLE = "Revision Table"
    LAYER = True
    PIXMAP = "TechDraw_SpreadsheetView"

    def build(self):
        self.say("Set the options, then OK (attached to the anchor point) or click where the table goes.")
        _template_group(self, ("standard revision block",), "standard revision block")
        _position_group(self, True)
        box, lay = D._group("Revision Symbol Shapes", self.form)
        row = QtWidgets.QGridLayout()           # two a row: one row of four made the pane wider than 300 px
        row.setHorizontalSpacing(2)
        row.setVerticalSpacing(2)
        self.shapes = QtWidgets.QButtonGroup(box)
        for n, name in enumerate(REV_SHAPES):
            b = QtWidgets.QToolButton(box)
            b.setText(name)
            b.setCheckable(True)
            b.setObjectName("SWRevShape" + name)
            b.setChecked(name == "Triangle")
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            self.shapes.addButton(b, n)
            row.addWidget(b, n // 2, n % 2)
        lay.addLayout(row)
        self.lay.addWidget(box)
        box, lay = D._group("Options", self.form)
        self.auto_symbol = QtWidgets.QCheckBox("Enable symbol when adding new\nrevision", box)
        self.auto_symbol.setObjectName("SWRevAutoSymbol")
        self.auto_symbol.setChecked(bool(_drawing_option("Enable symbol when adding new revision", True)))
        lay.addWidget(self.auto_symbol)
        self.lock_first = QtWidgets.QCheckBox("Lock first row", box)
        self.lock_first.setObjectName("SWRevLockFirst")
        self.lock_first.setToolTip("The first revision row can't be edited, deleted, hidden or sorted.")
        lay.addWidget(self.lock_first)
        self.lay.addWidget(box)
        box, lay = D._group("Alpha/Numerical Control", self.form)
        self.alpha = QtWidgets.QRadioButton("A, B, C...", box)
        self.alpha.setObjectName("SWRevAlpha")
        self.numeric = QtWidgets.QRadioButton("1, 2, 3...", box)
        self.numeric.setObjectName("SWRevNumeric")
        self.alpha.setChecked(True)
        lay.addWidget(self.alpha)
        lay.addWidget(self.numeric)
        self.lay.addWidget(box)
        box, lay = D._group("Multi-sheet style", self.form)
        self.multi = []
        for name in REV_MULTI:
            b = QtWidgets.QRadioButton(name, box)
            b.setObjectName("SWRevMulti" + name.replace(" ", ""))
            b.setChecked(name == "See Sheet 1")
            lay.addWidget(b)
            self.multi.append(b)
        self.lay.addWidget(box)
        _border_group(self)
        self.table = None

    def multi_style(self):
        return next((b.text() for b in self.multi if b.isChecked()), "See Sheet 1")

    def make(self, at):
        self.table = make_revision_table(self.page, at, self.shapes.checkedButton().text(),
                                         "Numerical" if self.numeric.isChecked() else "Alpha",
                                         self.auto_symbol.isChecked(), self.multi_style())
        if self.lock_first.isChecked():
            from . import drawtableedit
            drawtableedit.lock_first_row(self.table, True)
        _apply_border(self, self.table)
        self.made.append(self.table)

    def sheet_click(self, p):
        if self.table is not None or self.attach.isChecked():
            return False
        self.make(p)
        QtCore.QTimer.singleShot(0, self.accept)
        return True

    def finish(self):
        if self.table is None:
            self.make(None)


def revision_symbol_svg(shape, text, r=4.5):
    if shape == "Circle":
        outline = '<circle cx="0" cy="0" r="%g" fill="none" stroke="#000" stroke-width="0.25"/>' % (r * 0.8)
        ty = r * 0.3
    elif shape == "Square":
        a = r * 0.75
        outline = '<rect x="%g" y="%g" width="%g" height="%g" fill="none" stroke="#000" stroke-width="0.25"/>' % (
            -a, -a, 2 * a, 2 * a)
        ty = r * 0.3
    elif shape == "Hexagon":
        pts = " ".join("%g,%g" % (r * 0.85 * math.cos(math.radians(60 * k)), r * 0.85 * math.sin(math.radians(60 * k)))
                       for k in range(6))
        outline = '<polygon points="%s" fill="none" stroke="#000" stroke-width="0.25"/>' % pts
        ty = r * 0.3
    else:
        outline = '<polygon points="0,%g %g,%g %g,%g" fill="none" stroke="#000" stroke-width="0.25"/>' % (
            -r, r * 0.95, r * 0.6, -r * 0.95, r * 0.6)
        ty = r * 0.35
    return outline + ('<text x="0" y="%g" font-family="osifont, Arial" font-size="3" text-anchor="middle">%s</text>'
                      % (ty, DA._esc(text)))


def current_revision(page):
    t = revision_table(page)
    if t is None:
        return ""
    rows = rows_of(t)
    return rows[-1][1] if len(rows) > 1 else ""


class RevisionSymbolPanel(DA._AnnotPanel):
    TITLE = "Revision Symbol"
    LAYER = True
    PIXMAP = "TechDraw_Annotation"
    AGAIN = "Revision symbol placed. Click to place another, or OK."

    def build(self):
        rev = current_revision(self.page) or "A"
        self.say("Click where the leader points and where the symbol goes (revision %s)." % rev)
        box, lay = D._group("Revision", self.form)
        self.rev = QtWidgets.QLineEdit(rev, box)
        self.rev.setObjectName("SWRevisionLetter")
        lay.addWidget(self.rev)
        self.lay.addWidget(box)
        self.leader_group(default=True, arrows=False)

    def place(self, p, tip):
        text = self.rev.text().strip() or "A"
        r = 4.5
        t = revision_table(self.page)
        shape = getattr(t, "SWRevShape", "Triangle") if t is not None else "Triangle"
        body = [revision_symbol_svg(shape, text, r)]
        if tip is not None:
            tx, ty = DA._rel(p, tip)
            L = math.hypot(tx, ty)
            if L > r:
                body.append(DA._arrow(tx, ty, tx * r * 0.6 / L, ty * r * 0.6 / L))
        s = DA.svg_symbol(self.page, "RevisionSymbol", "".join(body), r + DA._reach(p, tip), p,
                          "Revision Symbol %s" % text, "RevisionSymbol")
        s.addProperty("App::PropertyString", "SWRevision", "FreeCAD", "revision letter")
        s.SWRevision = text
        s.addProperty("App::PropertyString", "SWRevShape", "FreeCAD", "revision symbol shape")
        s.SWRevShape = shape
        return s


# --------------------------------------------------------------------------- General Table
class GeneralTablePanel(D._Panel):
    TITLE = "Table"
    LAYER = True
    PIXMAP = "TechDraw_SpreadsheetView"

    def build(self):
        self.say("Set the size, then click where the table goes (or OK, attached to the anchor point).")
        self.templates = table_templates("General")
        _template_group(self, ("standard",) + tuple(self.templates), "standard")
        _position_group(self, default=False)
        box, lay = D._group("Table Size", self.form)
        grid = QtWidgets.QGridLayout()
        self.cols = QtWidgets.QSpinBox(box)
        self.cols.setObjectName("SWTableColumns")
        self.cols.setRange(1, 26)
        self.cols.setValue(2)
        self.rows = QtWidgets.QSpinBox(box)
        self.rows.setObjectName("SWTableRows")
        self.rows.setRange(1, 500)
        self.rows.setValue(2)
        grid.addWidget(QtWidgets.QLabel("Columns:", box), 0, 0)
        grid.addWidget(self.cols, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Rows:", box), 1, 0)
        grid.addWidget(self.rows, 1, 1)
        lay.addLayout(grid)
        self.lay.addWidget(box)
        _border_group(self)
        self.table = None

    def make(self, at):
        rows = [[" "] * self.cols.value() for _ in range(self.rows.value())]
        widths = [90] * self.cols.value()
        path = self.templates.get(self.template.currentText())
        if path:                                  # a saved table template: its text and column widths
            try:
                rows, ws = load_table_template(path)
                widths = ws or [90] * len(rows[0])
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: table template %s: %s\n" % (path, error))
        self.table = make_table(self.page, rows, at, "General Table%d" % (1 + len(
            [o for o in self.doc.Objects if getattr(o, "SWTable", "") == "General"])), "General", widths)
        _apply_border(self, self.table)
        self.made.append(self.table)

    def sheet_click(self, p):
        if self.table is not None or self.attach.isChecked():
            return False
        self.make(p)
        QtCore.QTimer.singleShot(0, self.accept)
        return True

    def finish(self):
        if self.table is None and self.attach.isChecked():
            self.make(anchor(self.page, "General"))
            attach(self.table)


class WeldmentCutListPanel(D._Panel):
    ""

    TITLE = "Weldment Cut List"
    LAYER = True
    PIXMAP = "TechDraw_SpreadsheetView"

    def build(self):
        from . import drawmenus, drawselect
        _template_group(self, CUT_TEMPLATES, CUT_TEMPLATES[0])
        _position_group(self, default=False)
        box, lay = D._group("Keep Missing Items", self.form)
        self.keep_missing = QtWidgets.QCheckBox("Keep missing items", box)
        self.keep_missing.setObjectName("SWCutKeepMissing")
        self.strikeout = QtWidgets.QCheckBox("Strikeout", box)
        self.strikeout.setObjectName("SWCutStrikeout")
        self.strikeout.setChecked(True)
        DL.sets(self.keep_missing, True, self.strikeout)    # never greyed
        lay.addWidget(self.keep_missing)
        lay.addWidget(self.strikeout)
        self.lay.addWidget(box)
        box, lay = D._group("Item Numbers", self.form)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Start at:", box))
        self.start = QtWidgets.QSpinBox(box)
        self.start.setObjectName("SWCutStart")
        self.start.setRange(0, 100000)
        self.start.setValue(1)
        row.addWidget(self.start)
        lay.addLayout(row)
        row = QtWidgets.QHBoxLayout()           # its own row: beside Start at it made the pane 341 px wide
        row.addWidget(QtWidgets.QLabel("Increment:", box))
        self.step = QtWidgets.QSpinBox(box)
        self.step.setObjectName("SWCutIncrement")
        self.step.setRange(1, 1000)
        self.step.setValue(1)
        row.addWidget(self.step)
        lay.addLayout(row)
        self.fixed = QtWidgets.QCheckBox("Do not change item numbers", box)
        self.fixed.setObjectName("SWCutFixedNumbers")
        lay.addWidget(self.fixed)
        self.lay.addWidget(box)
        _border_group(self)
        self.table = None
        self.view = None
        found = drawmenus.weldment_views(self.page)
        try:
            picked = drawselect.picked_views()
        except Exception:
            picked = []
        for v, _part in found:
            if v in picked:
                self.view = v
        if self.view is None and len(found) == 1:
            self.view = found[0][0]
        if not found:
            self.say("No view on this sheet shows a weldment or sheet metal part.")
        elif self.view is None:
            self.say("Click a weldment view.")
        else:
            self.say("Click where the table goes (or OK, attached to the anchor point).")

    def make(self, at):
        from . import drawmenus
        self.table = drawmenus.weldment_cut_list(self.page, self.view, at)
        if self.table is None:
            return
        t = self.table
        for prop, kind, val in (("SWTableTemplate", "App::PropertyString", self.template.currentText()),
                                ("SWItemStart", "App::PropertyInteger", self.start.value()),
                                ("SWItemStep", "App::PropertyInteger", self.step.value()),
                                ("SWItemFixed", "App::PropertyBool", self.fixed.isChecked()),
                                ("SWKeepMissing", "App::PropertyBool", self.keep_missing.isChecked()),
                                ("SWStrikeout", "App::PropertyBool", self.strikeout.isChecked())):
            if prop not in t.PropertiesList:
                t.addProperty(kind, prop, "FreeCAD", "Weldment Cut List PM")
            setattr(t, prop, val)
        part = cut_list_part(t)
        if part is not None:
            from . import drawmenus as M
            out = dress_cut_rows(t, M.cut_list_rows(part), part)
            set_rows(t, out, cut_widths(out))
        _apply_border(self, t)
        self.made.append(t)

    def sheet_click(self, p):
        if self.table is not None:
            return False
        if self.view is None:
            from . import drawmenus
            v = DV.view_at(self.page, p)
            if v is None or v not in [f[0] for f in drawmenus.weldment_views(self.page)]:
                self.say("Click a view of a weldment or sheet metal part.")
                return True
            self.view = v
            self._view_clicked = True
            if self.attach.isChecked():
                self.say("OK puts the table at the anchor point.")
            else:
                self.say("Click where the table goes.")
            return True
        if not getattr(self, "_view_clicked", False):
            # the view was taken for the user (the sheet's only weldment view): a click on a weldment view is
            # still the view pick, not the table's place (sheet metal run 11-27: the table landed on the frame)
            from . import drawmenus
            self._view_clicked = True
            v = DV.view_at(self.page, p)
            if v is not None and v in [f[0] for f in drawmenus.weldment_views(self.page)]:
                self.view = v
                if not self.attach.isChecked():
                    self.say("Click where the table goes.")
                return True
        if self.attach.isChecked():
            return True
        self.make(p)
        QtCore.QTimer.singleShot(0, self.accept)
        return True

    def finish(self):
        if self.table is None and self.attach.isChecked():
            self.make(anchor(self.page, "CutList"))
            if self.table is not None:
                attach(self.table)


# --------------------------------------------------------------------------- commands
# --------------------------------------------------------------------------- Bend, Punch and Weld Tables
def _flat_source(view):
    """The Flat-Pattern-View feature a flat pattern view shows, else None."""
    for o in DV.source_shapes(view):
        if getattr(o, "Body", None) is not None and hasattr(o, "Normal") and hasattr(o, "XAxis"):
            return o
    return None


def _solids(view):
    out = []
    flat = _flat_source(view)
    for o in DV.source_shapes(view):
        try:
            if o is flat:
                out += list(o.Body.Shape.Solids)        # the bends are read from the formed part
                continue
            out += list(o.Shape.Solids)
        except Exception as _fw_err:
            _fw_log("drawtables.py:2611", _fw_err)
    return out


def _same_axis(g, ax, c):
    """A cylinder on group g's axis (loose: the sheet metal tools build a bend's two faces apart)."""
    return abs(abs(g["axis"].dot(ax)) - 1) < 1e-4 and ((c - g["centre"]).cross(g["axis"])).Length < 1e-3


def _fixed_face(solid, flat):
    """The folded part's face lying on the flat pattern's fixed face (same plane), else None."""
    n = V(flat.Normal)
    if n.Length < 1e-9:
        return None
    n.normalize()
    p = None
    try:
        for f in flat.Shape.SubShapes[0].Faces if flat.Shape.SubShapes else flat.Shape.Faces:
            if type(f.Surface).__name__ == "Plane" and abs(abs(f.normalAt(0, 0).dot(n)) - 1) < 1e-6:
                p = f.CenterOfMass
                break
    except Exception as _fw_err:
        _fw_log("drawtables.py:fixed flat", _fw_err)
    best = None
    for f in solid.Faces:
        if type(f.Surface).__name__ != "Plane":
            continue
        m = f.normalAt(0, 0)
        if abs(abs(m.dot(n)) - 1) > 1e-6:
            continue
        if p is not None and abs((f.CenterOfMass - p).dot(n)) > 1e-3:
            continue
        if best is None or f.Area > best.Area:
            best = f
    return best


def _skins(solid):
    """{face index: skin number} for the sheet's two sides: faces meeting smoothly (same normal across their
    shared edge) are one side; a thickness face meets them square and starts its own group."""
    import Part
    faces = solid.Faces
    index = {}
    for i, f in enumerate(faces):
        index[f.hashCode()] = i
    near = {i: [] for i in range(len(faces))}
    for e in solid.Edges:
        try:
            two = [index.get(f.hashCode()) for f in solid.ancestorsOfType(e, Part.Face)]
        except Exception:
            continue
        two = [i for i in two if i is not None]
        if len(two) != 2 or two[0] == two[1]:
            continue
        p = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
        try:
            n = [faces[i].normalAt(*faces[i].Surface.parameter(p)) for i in two]
        except Exception:
            continue
        if n[0].dot(n[1]) > 0.999:
            near[two[0]].append(two[1])
            near[two[1]].append(two[0])
    skin, k = {}, 0
    for i in range(len(faces)):
        if i in skin:
            continue
        todo = [i]
        skin[i] = k
        while todo:
            j = todo.pop()
            for m in near[j]:
                if m not in skin:
                    skin[m] = k
                    todo.append(m)
        k += 1
    return skin


def bends(view):
    ""



    d, _, _ = D.view_frame(view)
    flat = _flat_source(view)
    out = []
    for s in _solids(view):
        groups = []
        for i, f in enumerate(s.Faces):
            srf = f.Surface
            if type(srf).__name__ != "Cylinder":
                continue
            u0, u1, v0, v1 = f.ParameterRange
            ang = math.degrees(u1 - u0)
            if ang >= 359.0:
                continue                       # a hole or a boss, not a bend
            ax, c = srf.Axis, srf.Center
            for g in groups:
                if _same_axis(g, ax, c):
                    g["faces"].append((srf.Radius, ang, f, i))
                    break
            else:
                groups.append({"axis": V(ax), "centre": V(c), "faces": [(srf.Radius, ang, f, i)]})
        groups = [g for g in groups if max(q[0] for q in g["faces"]) - min(q[0] for q in g["faces"]) > 1e-4]
        if not groups:
            continue
        side = None
        fixed = _fixed_face(s, flat) if flat is not None else None
        if fixed is not None:
            try:
                skin = _skins(s)
                fi = [i for i, f in enumerate(s.Faces) if f.isSame(fixed)][0]
                # the viewer sees the fixed face's side when the face looks towards the viewer
                seen = skin[fi] if fixed.normalAt(0, 0).dot(d) > 0 else None
                side = (skin, skin[fi], seen)
            except Exception as _fw_err:
                _fw_log("drawtables.py:skins", _fw_err)
                side = None
        for g in groups:
            r, ang, f, i = min(g["faces"], key=lambda q: q[0])
            mid = f.CenterOfMass
            outer = max(g["faces"], key=lambda q: q[0])[3]
            if side is not None and side[0].get(i) != side[0].get(outer):
                skin, fixed_skin, seen = side
                inner = skin.get(i)
                up = inner == fixed_skin if seen is not None else inner != fixed_skin
            else:
                # no fixed face: UP when the bend's axis is on the viewer's side of the bend
                up = (g["centre"] - mid).dot(d) > 0
            out.append((r, ang, mid, g["axis"], "UP" if up else "DOWN"))
    out.sort(key=lambda b: (round(-b[2].z, 6), round(b[2].x, 6), round(b[2].y, 6)))
    return out


BEND_WIDTHS = (50, 90, 80, 110)


def bend_lines(view):
    """The bend lines of a flat pattern view (model edges of the Flat-Pattern-View's second part)."""
    flat = _flat_source(view)
    if flat is None:
        return []
    try:
        subs = flat.Shape.SubShapes
    except Exception:
        return []
    out = []
    for sub in subs[1:]:
        out += [e for e in sub.Edges if hasattr(e.Curve, "Direction")]
    return out


BEND_NOTE_STYLE = "Above Bend Line"


BEND_NOTE_FORMAT = "<direction>  <angle>°  R <radius>"
BEND_NOTE_FILE = "bendnoteformat.txt"
BEND_NOTE_TOKENS = ("<direction>", "<angle>", "<radius>", "<order>")


def bend_note_file():
    ""

    import os
    return os.path.join(App.getUserAppDataDir(), "FreeWorks", BEND_NOTE_FILE)


def _file_format():
    try:
        with open(bend_note_file(), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except Exception as _fw_err:
        _fw_log("drawtables.py:2691", _fw_err)
    return None


def note_format(doc):
    """Document Properties > Sheet Metal > Bend notes > Format; while it is the default, the format file
    (when there is one) gives it."""
    try:
        from . import drawdocprops as DDP
        own = DDP.prop(doc, "sm_note_format")
    except Exception:
        own = None
    if own and own != BEND_NOTE_FORMAT:
        return own
    return _file_format() or BEND_NOTE_FORMAT


def radius_digits(doc):
    ""

    try:
        from . import drawdocprops as DDP
        p = str(DDP.prop(doc, "dim_precision") or ".12")
    except Exception:
        p = ".12"
    return 0 if p == "None" else max(0, len(p) - 1)


def note_text(fmt, way, angle, radius, order, digits=None):
    """The bend note's text: the format with <direction> (UP/DOWN), <angle> (degrees), <radius> (inside
    radius, at digits decimals) and <order> (the bend's number) filled in, made safe for the sheet's SVG."""
    import html
    text = fmt or BEND_NOTE_FORMAT
    rad = "%g" % round(radius, 2) if digits is None else "%.*f" % (digits, radius)
    for token, value in (("<direction>", way), ("<angle>", "%g" % round(angle, 2)),
                         ("<radius>", rad), ("<order>", "%d" % order)):
        text = text.replace(token, value)
    return html.escape(text, quote=False)


def _note_style(doc):
    try:
        from . import drawdocprops as DDP
        return DDP.prop(doc, "sm_note_style") or BEND_NOTE_STYLE
    except Exception as _fw_err:
        _fw_log("drawtables.py:2781", _fw_err)
        return BEND_NOTE_STYLE


def bend_note_svg(text, angle, style):
    """SVG body of a bend note at 0, 0 on its bend line (angle: the line's direction on the sheet, degrees,
    counter-clockwise). Above Bend Line: along the line, above it; Inline: along the line, on it, the line
    broken under the text; With Leader: level text up and to the right with a leader to the line.
    Returns (body, reach)."""
    font = 'font-family="osifont, Arial" font-size="2.5"'
    a = angle % 180.0
    if a > 90.0:
        a -= 180.0                       # read from below or the right, as drawing text is
    if style == "With Leader":
        tx, ty = 8.0, -6.0
        w = 0.6 * 2.5 * len(text)
        return ('<line x1="0" y1="0" x2="%g" y2="%g" stroke="#000" stroke-width="0.18"/>'
                '<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="0.18"/>'
                '<circle cx="0" cy="0" r="0.5" fill="#000"/>'
                '<text x="%g" y="%g" %s text-anchor="start">%s</text>'
                % (tx, ty, tx, ty, tx + w, ty, tx + 0.5, ty - 0.7, font, text)), tx + w + 2
    w = 0.6 * 2.5 * len(text)
    if style == "Inline":
        body = ('<g transform="rotate(%g)"><rect x="%g" y="-1.6" width="%g" height="3.2" fill="#fff"/>'
                '<text x="0" y="0.9" %s text-anchor="middle">%s</text></g>'
                % (-a, -w / 2 - 0.8, w + 1.6, font, text))
    else:
        body = '<g transform="rotate(%g)"><text x="0" y="-1.0" %s text-anchor="middle">%s</text></g>' % (
            -a, font, text)
    return body, w / 2 + 3


def line_of_bend(view, lines=None, bs=None):
    """{bend index: bend line index} for a flat pattern view: the n-th bend from the fixed face goes with the n-th
    bend line from it (the flat pattern lies on the fixed face's plane). Sheet metal run 11-27: parallel bends
    were matched in list order, so a Bend Table's tags sat together on one line and the notes could swap
    UP and DOWN. {} when it cannot tell (the callers keep their old matching)."""
    import Part
    lines = bend_lines(view) if lines is None else lines
    bs = list(bends(view)) if bs is None else bs
    flat = _flat_source(view)
    if flat is None or not lines or len(lines) != len(bs):
        return {}
    try:
        fixed = None
        for solid in _solids(view):
            fixed = _fixed_face(solid, flat)
            if fixed is not None:
                break
        if fixed is None:
            return {}
        lo = sorted(range(len(lines)), key=lambda i: lines[i].distToShape(fixed)[0])
        bo = sorted(range(len(bs)), key=lambda i: Part.Vertex(bs[i][2]).distToShape(fixed)[0])
        return dict(zip(bo, lo))
    except Exception as _fw_err:
        _fw_log("drawtables.py:line of bend", _fw_err)
        return {}


def bend_notes(page, view, style=None):
    ""

    lines = bend_lines(view)
    if not lines:
        return []
    style = style or _note_style(page.Document)
    fmt = note_format(page.Document)
    bs = list(bends(view))
    x0, y0 = D.view_position(view)
    k = DV.view_scale(view)
    made, used = [], set()
    by_line = {li: bi for bi, li in line_of_bend(view, lines, bs).items()}
    for n, e in enumerate(lines):
        dirn = e.Curve.Direction
        pick = by_line.get(n)
        for i, b in enumerate(bs if pick is None else ()):
            if i not in used and abs(abs(V(b[3]).normalize().dot(dirn)) - 1) < 1e-4:
                pick = i
                break
        if pick is None:
            pick = next((i for i in range(len(bs)) if i not in used), None)
        if pick is None:
            break
        used.add(pick)
        r, ang, _mid, _ax, way = bs[pick]
        text = note_text(fmt, way, ang, r, n + 1, radius_digits(view.Document))
        mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
        q = DA._project(view, mid)
        q2 = DA._project(view, mid + dirn)
        angle = math.degrees(math.atan2(q2.y - q.y, q2.x - q.x))
        at = (x0 + q.x * k, y0 + q.y * k)
        body, reach = bend_note_svg(text, angle, style)
        s = DA.svg_symbol(page, "BendNote", body, reach, at, "Bend Note %d" % (n + 1), "BendNote")
        s.addProperty("App::PropertyString", "SWBendNoteOf", "FreeCAD", "the flat pattern view")
        s.SWBendNoteOf = view.Name
        s.addProperty("App::PropertyString", "SWBendNoteStyle", "FreeCAD", "Document Properties bend note style")
        s.SWBendNoteStyle = style
        s.addProperty("App::PropertyString", "SWBendNoteFormat", "FreeCAD", "the bend note format it was made with")
        s.SWBendNoteFormat = fmt
        made.append(s)
    _keep_bend_signature(view)
    page.Document.recompute()
    return made


def _keep_bend_signature(view):
    try:
        sig = bend_signature(view)
        if "SWBendSignature" not in view.PropertiesList:
            view.addProperty("App::PropertyString", "SWBendSignature", "FreeCAD", "the bends the notes were made for")
            view.setPropertyStatus("SWBendSignature", ["Hidden"])
        view.SWBendSignature = sig
    except Exception as _fw_err:
        _fw_log("drawtables.py:2808", _fw_err)


def bend_signature(view):
    """The bends and bend lines of a flat pattern view, rounded: it changes when a bend moves, opens or closes,
    or a bend is added or taken away (the flat pattern's size may stay the same)."""
    out = []
    for r, ang, mid, _ax, way in bends(view):
        out.append(("b", round(r, 3), round(ang, 2), way, round(mid.x, 3), round(mid.y, 3), round(mid.z, 3)))
    for e in bend_lines(view):
        m = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
        out.append(("l", round(m.x, 3), round(m.y, 3), round(m.z, 3)))
    return repr(out)


def refresh_bend_notes(doc):
    ""


    done = []
    views = [o for o in doc.Objects if getattr(o, "SWFlatPattern", False)]    # before any note is taken away
    for view in views:
        if "SWBendNotesDone" not in view.PropertiesList:
            continue
        try:
            sig = bend_signature(view)
        except Exception:
            continue
        if sig == "[]":
            continue        # the part not loaded yet (a reopened drawing): its bends come later (drawings-land281)
        if "SWBendSignature" not in view.PropertiesList:
            view.addProperty("App::PropertyString", "SWBendSignature", "FreeCAD", "the bends the notes were made for")
            view.setPropertyStatus("SWBendSignature", ["Hidden"])
            view.SWBendSignature = sig
            continue
        if view.SWBendSignature == sig:
            continue
        view.SWBendSignature = sig
        notes = [o for o in doc.Objects if getattr(o, "SWBendNoteOf", "") == view.Name]
        if not notes:
            continue                            # the notes were turned off or deleted: none come back
        style = getattr(notes[0], "SWBendNoteStyle", None)
        page = next((p for p in view.InList if p.TypeId == "TechDraw::DrawPage"), None)
        if page is None:
            continue
        for o in notes:
            doc.removeObject(o.Name)
        bend_notes(page, view, style)
        done.append(view)
    return done


def flat_pattern_placed(page, view):
    ""

    made = []
    try:
        from . import drawdocprops as DDP
        show = DDP.prop(page.Document, "sm_bend_notes") is not False
    except Exception:
        show = True
    try:
        page.Document.recompute()
        if show:
            made = bend_notes(page, view)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: bend notes: %s\n" % error)
    try:
        flat_pattern_extras(view)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: flat pattern display: %s\n" % error)
    return made


def _flat_feature(view):
    """The part's Flat-Pattern feature (it holds GrainDirection), else None."""
    flat = _flat_source(view)
    body = getattr(flat, "Body", None) if flat is not None else None
    for o in (list(getattr(body, "Group", []) or []) + list(getattr(flat, "Document", App).Objects
                                                             if flat is not None else [])):
        if "GrainDirection" in getattr(o, "PropertiesList", []):
            return o
    return None


def _flat_points(view):
    flat = _flat_source(view)
    shapes = []
    try:
        subs = flat.Shape.SubShapes if flat is not None else []
        shapes = [subs[0]] if subs else ([flat.Shape] if flat is not None else [])
    except Exception as _fw_err:
        _fw_log("drawtables.py:2898", _fw_err)
    if not shapes:
        shapes = [o.Shape for o in DV.source_shapes(view) if hasattr(o, "Shape")]
    pts = []
    for sh in shapes:
        for e in sh.Edges:
            try:
                pts += [DA._project(view, p) for p in e.discretize(Deflection=0.05)]
            except Exception as _fw_err:
                _fw_log("drawtables.py:2907", _fw_err)
    return pts


def _clear_cosmetics(view, prop):
    for tag in list(getattr(view, prop, []) or []):
        try:
            view.removeCosmeticEdge(tag)
        except Exception as _fw_err:
            _fw_log("drawtables.py:2916", _fw_err)
    if prop not in view.PropertiesList:
        view.addProperty("App::PropertyStringList", prop, "FreeCAD", "cosmetic lines FreeCAD drew")
    setattr(view, prop, [])


def _colored(view, tag, color):
    ""
    try:
        from . import drawdocprops as DDP
        rgb = DDP.hex_rgb(color)
        ce = view.getCosmeticEdge(tag)
        fmt = ce.Format
        if isinstance(fmt, dict):
            fmt = dict(fmt)
            fmt["color"] = tuple(rgb) + (1.0,) if len(tuple(fmt.get("color", ()))) == 4 else tuple(rgb)
            ce.Format = fmt
        else:
            fmt = list(fmt)
            if len(fmt) > 2:
                fmt[2] = App.Color(*rgb) if hasattr(App, "Color") else tuple(rgb)
                ce.Format = tuple(fmt)
        view.replaceCosmeticEdge(ce) if hasattr(view, "replaceCosmeticEdge") else None
    except Exception as error:
        App.Console.PrintLog("FreeCAD: cosmetic colour: %s\n" % error)
    return tag


BEND_LINE_STYLE = 4         # TechDraw dash-dot: the bend line look


def show_bend_colors(view, up="#000000", down="#000000"):
    """Document Properties > Sheet Metal > Flat pattern colors: the bend lines drawn again in the Up and Down
    colours over the view's own (black) bend lines; nothing extra while both are black (the default)."""
    _clear_cosmetics(view, "SWBendColorLines")
    up, down = (up or "#000000").lower(), (down or "#000000").lower()
    if up == "#000000" and down == "#000000":
        return []
    lines = bend_lines(view)
    bs = list(bends(view))
    used, tags = set(), []
    for e in lines:
        dirn = e.Curve.Direction
        pick = next((i for i, b in enumerate(bs) if i not in used and
                     abs(abs(V(b[3]).normalize().dot(dirn)) - 1) < 1e-4), None)
        if pick is None:
            pick = next((i for i in range(len(bs)) if i not in used), None)
        if pick is None:
            break
        used.add(pick)
        color = up if str(bs[pick][4]).upper().startswith("UP") else down
        if color == "#000000":
            continue
        a = DA._project(view, e.Vertexes[0].Point)
        b = DA._project(view, e.Vertexes[-1].Point)
        tag = view.makeCosmeticLine(V(a.x, a.y, 0), V(b.x, b.y, 0))
        DA._styled(view, tag, BEND_LINE_STYLE)
        tags.append(_colored(view, tag, color) or "")
    view.SWBendColorLines = [t for t in tags if t]
    return view.SWBendColorLines


def show_bounding_box(view, on=True, color="#000000"):
    ""
    _clear_cosmetics(view, "SWBoundingBoxLines")
    if not on:
        return []
    pts = _flat_points(view)
    if not pts:
        return []
    x0, x1 = min(p.x for p in pts), max(p.x for p in pts)
    y0, y1 = min(p.y for p in pts), max(p.y for p in pts)
    c = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
    tags = []
    for a, b in zip(c, c[1:] + c[:1]):
        tags.append(DA._styled(view, view.makeCosmeticLine(a, b), PHANTOM_STYLE) or "")
    if (color or "#000000").lower() != "#000000":
        tags = [_colored(view, t, color) for t in tags if t]
    view.SWBoundingBoxLines = [t for t in tags if t]
    return view.SWBoundingBoxLines


PHANTOM_STYLE = 5           # TechDraw dash-dot-dot


def show_grain(view, on=True):
    """The part's grain direction drawn as an arrow across the middle of the flat pattern view."""
    _clear_cosmetics(view, "SWGrainLines")
    if not on:
        return []
    fp = _flat_feature(view)
    g = getattr(fp, "GrainDirection", None) if fp is not None else None
    d3 = V(g) if g is not None and V(g).Length > 1e-9 else V(1, 0, 0)
    pts = _flat_points(view)
    if not pts:
        return []
    cx = (min(p.x for p in pts) + max(p.x for p in pts)) / 2
    cy = (min(p.y for p in pts) + max(p.y for p in pts)) / 2
    size = 0.3 * max(max(p.x for p in pts) - min(p.x for p in pts), max(p.y for p in pts) - min(p.y for p in pts), 30)
    centre = DV.model_centre(view)
    q = DA._project(view, centre + d3) - DA._project(view, centre)
    d = V(q.x, q.y, 0)
    if d.Length < 1e-9:
        d = V(1, 0, 0)
    d.normalize()
    side = V(-d.y, d.x, 0)
    c = V(cx, cy, 0)
    tip = c + d * size / 2
    head = size * 0.12
    segs = [(c - d * size / 2, tip), (tip, tip - d * head + side * head * 0.6), (tip, tip - d * head - side * head * 0.6)]
    tags = []
    for a, b in segs:
        tags.append(DA._styled(view, view.makeCosmeticLine(a, b), 1) or "")
    view.SWGrainLines = [t for t in tags if t]
    return view.SWGrainLines


def flat_pattern_extras(view, v=None):
    """Document Properties > Sheet Metal on a flat pattern view: bend note style, grain direction, bounding box."""
    doc = view.Document
    try:
        from . import drawdocprops as DDP
        v = v or dict(DDP.defaults(), **DDP.stored(doc))
    except Exception:
        v = v or {}
    page = D.page_of(view) if hasattr(D, "page_of") else None
    if page is None:
        page = next((p for p in view.InList if p.TypeId == "TechDraw::DrawPage"), None)
    style = v.get("sm_note_style", BEND_NOTE_STYLE)
    notes = [o for o in doc.Objects if getattr(o, "SWBendNoteOf", "") == view.Name]
    want = v.get("sm_bend_notes", True) is not False
    fmt = note_format(doc)
    if page is not None and (not want or any(getattr(o, "SWBendNoteStyle", BEND_NOTE_STYLE) != style or
                                             getattr(o, "SWBendNoteFormat", BEND_NOTE_FORMAT) != fmt for o in notes)
                             or (want and not notes and "SWBendNotesDone" in view.PropertiesList)):
        for o in notes:
            doc.removeObject(o.Name)
        if want:
            bend_notes(page, view, style)
    if "SWBendNotesDone" not in view.PropertiesList:
        view.addProperty("App::PropertyBool", "SWBendNotesDone", "FreeCAD", "bend notes placed once")
        view.setPropertyStatus("SWBendNotesDone", ["Hidden"])
    view.SWBendNotesDone = True
    show_grain(view, bool(v.get("sm_grain", False)))
    show_bounding_box(view, bool(v.get("sm_bbox", False)), v.get("sm_col_bbox", "#000000"))
    show_bend_colors(view, v.get("sm_col_up", "#000000"), v.get("sm_col_down", "#000000"))
    doc.recompute()


# --------------------------------------------------------------------------- Design Table on a drawing
def design_table_rows(model_doc):
    ""

    from . import configmanager as cm
    t = cm.table(model_doc)
    if t is None:
        return None
    sheet = t.sheet
    cols = list(t.columns())

    def text(cell):
        try:
            v = sheet.get(cell)
        except Exception:
            return ""
        if isinstance(v, float) and abs(v - round(v)) < 1e-9:
            v = int(round(v))
        return str(getattr(v, "UserString", v))
    head = [""]
    for c in cols:
        try:
            head.append(sheet.getAlias("%s%d" % (c, t.first - 1)) or text("%s%d" % (c, t.first - 1)))
        except Exception:
            head.append(text("%s%d" % (c, t.first - 1)))
    rows = [["Design Table for: %s" % model_doc.Label] + [""] * len(cols), head]
    for r in range(t.first, t.last + 1):
        name = text("%s%d" % (t.col, r))
        if name:
            rows.append([name] + [text("%s%d" % (c, r)) for c in cols])
    return rows


def make_design_table(page, view, at=None):
    """Insert > Tables > Design Table: the design table of the model in view, on the sheet."""
    srcs = DV.source_shapes(view) if view is not None else []
    model = None
    for o in srcs:
        o = getattr(o, "LinkedObject", o) or o
        model = o.Document
        break
    if model is None:
        raise ValueError("Pick a drawing view of a part or assembly with a design table.")
    rows = design_table_rows(model)
    if rows is None:
        raise ValueError("%s has no design table." % model.Label)
    if at is None:
        a, b, c, d = DV.view_box(view)
        at = (a, b - 10 - 4 * len(rows))
    t = make_table(page, rows, at, "Design Table", "DesignTable", [45] + [40] * (len(rows[0]) - 1))
    t.addProperty("App::PropertyString", "SWBomView", "FreeCAD", "the view the table is of")
    t.SWBomView = view.Name
    try:
        t.Source.mergeCells("A1:%s1" % COLS[len(rows[0]) - 1])
    except Exception as _fw_err:
        _fw_log("drawtables.py:3120", _fw_err)
    return t


def refresh_design_table(t):
    """The model's design table changed: the drawing's copy follows."""
    view = t.Document.getObject(getattr(t, "SWBomView", "") or "")
    if view is None:
        return False
    for o in DV.source_shapes(view):
        rows = design_table_rows((getattr(o, "LinkedObject", o) or o).Document)
        if rows and rows != rows_of(t):
            set_rows(t, rows)
            return True
        break
    return False


# --------------------------------------------------------------------------- table templates
def template_folder():
    import os
    path = os.path.join(App.getUserAppDataDir(), "FreeWorks", "tabletemplates")
    os.makedirs(path, exist_ok=True)
    return path


def save_table_template(t, path=None):
    """Save as Template: the table's kind, text and column widths (.fwtbt) in the templates folder."""
    import os, json
    rows = rows_of(t)
    widths = []
    for c in range(len(rows[0]) if rows else 0):
        try:
            widths.append(float(t.Source.getColumnWidth(COLS[c])))
        except Exception:
            widths.append(90.0)
    path = path or os.path.join(template_folder(), t.Label + ".fwtbt")
    if not path.lower().endswith(".fwtbt"):
        path += ".fwtbt"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"FreeWorksTableTemplate": 1, "kind": getattr(t, "SWTable", "General"), "rows": rows,
                   "widths": widths}, f, indent=1)
    return path


def table_templates(kind="General"):
    """{name: path} of the saved table templates of a kind."""
    import os, json, glob
    out = {}
    for p in sorted(glob.glob(os.path.join(template_folder(), "*.fwtbt"))):
        try:
            with open(p, encoding="utf-8") as f:
                if json.load(f).get("kind", "General") == kind:
                    out[os.path.splitext(os.path.basename(p))[0]] = p
        except Exception as _fw_err:
            _fw_log("drawtables.py:3175", _fw_err)
    return out


def load_table_template(path):
    import json
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("rows") or [[" "]], data.get("widths") or None


def _seq_tag(n, control="Alpha", start="A"):
    ""
    if control == "Numerical":
        try:
            return str(int(start) + n)
        except Exception:
            return str(1 + n)
    tag = (str(start) or "A").strip().upper() or "A"
    if not tag.isalpha():
        tag = "A"
    for _ in range(n):
        tag = DV._next_letter(tag)
    return tag


def bend_rows(view, control="Alpha", start="A"):
    rows = [["TAG", "DIRECTION", "ANGLE", "INNER RADIUS"]]
    tags = []
    digits = radius_digits(view.Document)
    bs = list(bends(view))
    lines = bend_lines(view)
    on_line = line_of_bend(view, lines, bs)
    for n, (r, ang, mid, ax, way) in enumerate(bs):
        tag = _seq_tag(n, control, start)
        rows.append([tag, way, "%g°" % round(ang, 2), "%.*f" % (digits, r)])
        if n in on_line:                    # a flat pattern: the tag on its own bend line, not the formed bend
            e = lines[on_line[n]]
            mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
        tags.append((tag, mid))
    return rows, tags


def _tags(page, view, tags, kind, table=None):
    ""
    x0, y0 = D.view_position(view)
    k = DV.view_scale(view)
    for tag, p in tags:
        q = DA._project(view, p)
        at = (x0 + q.x * k + 3, y0 + q.y * k + 3)
        s = DA.svg_symbol(page, kind, '<text x="0" y="1.2" font-family="osifont, Arial" font-size="3.5" '
                          'text-anchor="middle">%s</text>' % tag, 3, at, "%s %s" % (kind, tag), kind)
        s.addProperty("App::PropertyString", "SWTag", "FreeCAD", "table tag")
        s.SWTag = tag
        if table is not None:
            s.addProperty("App::PropertyString", "SWTagOf", "FreeCAD", "the table this tag belongs to")
            s.SWTagOf = table.Name


def make_bend_table(page, view, at, control="Alpha", start="A"):
    rows, tags = bend_rows(view, control, start)
    t = make_table(page, rows, at, "Bend Table%d" % (1 + len(
        [o for o in page.Document.Objects if getattr(o, "SWTable", "") == "Bend"])), "Bend", BEND_WIDTHS)
    t.addProperty("App::PropertyString", "SWTableView", "FreeCAD", "the table's view")
    t.SWTableView = view.Name
    for name, val in (("SWBendControl", control), ("SWBendStart", start)):
        t.addProperty("App::PropertyString", name, "FreeCAD", "Bend Table settings")
        setattr(t, name, val)
    _tags(page, view, tags, "BendTag", t)
    try:
        sig = table_signature(t, view)          # what it was made for
        _SIGS[(page.Document.Name, t.Name)] = sig
        _keep_table_signature(t, sig)
    except Exception as _fw_err:
        _fw_log("drawtables.py:3242", _fw_err)
    page.Document.recompute()
    return t


def punches(view):
    """The punches (non-round cut-outs and forms) of the view's largest flat face square to the view:
    (centre in view geometry, width, height) of each of its inner loops that is not a circle."""
    d, x, y = D.view_frame(view)
    best = None
    for s in _solids(view):
        for f in s.Faces:
            if type(f.Surface).__name__ != "Plane":
                continue
            try:
                n = f.normalAt(0, 0)
            except Exception as _fw_err:
                _fw_log("drawtables.py:3317", _fw_err)
                continue
            if abs(abs(n.dot(d)) - 1) > 1e-6:
                continue
            if best is None or f.Area > best.Area:
                best = f
    out = []
    if best is None:
        return out
    outer = best.OuterWire
    for w in best.Wires:
        if w.isSame(outer):
            continue
        if len(w.Edges) == 1 and type(w.Edges[0].Curve).__name__ == "Circle":
            continue                            # a round hole: the Hole Table's
        c = w.BoundBox.Center
        us = [p.dot(x) for p in w.discretize(Deflection=0.05)]
        vs = [p.dot(y) for p in w.discretize(Deflection=0.05)]
        out.append((DA._project(view, c), max(us) - min(us), max(vs) - min(vs)))
    return out


PUNCH_WIDTHS = (50, 80, 80, 140)


def punch_rows(view, origin):
    rows = [["TAG", "X LOC", "Y LOC", "PUNCH TYPE"]]
    tags = []
    kinds = []
    items = sorted(punches(view), key=lambda q: (-q[0].y, q[0].x))
    for c, w, h in items:
        kind = "%g x %g" % (round(w, 2), round(h, 2))
        if kind not in kinds:
            kinds.append(kind)
    count = {}
    for c, w, h in items:
        kind = "%g x %g" % (round(w, 2), round(h, 2))
        letter = COLS[kinds.index(kind) % 26]
        count[letter] = count.get(letter, 0) + 1
        tag = "%s%d" % (letter, count[letter])
        rows.append([tag, "%g" % round(c.x - origin.x, 2), "%g" % round(c.y - origin.y, 2), kind])
        tags.append((tag, c))
    return rows, tags


def make_punch_table(page, view, origin, at):
    rows, tags = punch_rows(view, origin)
    t = make_table(page, rows, at, "Punch Table%d" % (1 + len(
        [o for o in page.Document.Objects if getattr(o, "SWTable", "") == "Punch"])), "Punch", PUNCH_WIDTHS)
    t.addProperty("App::PropertyString", "SWTableView", "FreeCAD", "the table's view")
    t.SWTableView = view.Name
    t.addProperty("App::PropertyVector", "SWHoleOrigin", "FreeCAD", "table origin (view geometry)")
    t.SWHoleOrigin = origin
    x0, y0 = D.view_position(view)
    k = DV.view_scale(view)
    for tag, c in tags:
        s = DA.svg_symbol(page, "PunchTag", '<text x="0" y="1.2" font-family="osifont, Arial" font-size="3.5" '
                          'text-anchor="middle">%s</text>' % tag, 3, (x0 + c.x * k + 3, y0 + c.y * k + 3),
                          "Punch Tag %s" % tag, "PunchTag")
        s.addProperty("App::PropertyString", "SWTag", "FreeCAD", "table tag")
        s.SWTag = tag
    page.Document.recompute()
    return t


WELD_WIDTHS = (70, 50, 80, 120, 100, 110, 90)     # the last: WELD MASS; wide enough for the headers in the document font (AR2)
WELD_HEAD = ["ITEM NO.", "QTY.", "WELD SIZE", "SYMBOL", "WELD LENGTH", "WELD MATERIAL"]


def model_weld_rows(page, view=None):
    ""

    try:
        from . import weweld
    except Exception:
        return None
    docs = []
    for v in ([view] if view is not None else page.Views):
        if not v.isDerivedFrom("TechDraw::DrawViewPart"):
            continue  # a table's Source is one spreadsheet, not a list of models
        for s in _fw_xs(v) + list(getattr(v, "Source", []) or []):
            if s is not None and s.Document not in docs:
                docs.append(s.Document)
    kinds, qty, length, mass = [], {}, {}, {}
    for doc in docs:
        for o in doc.Objects:
            if not weweld.is_weld_bead(o):
                continue
            try:
                paths = json.loads(o.Paths or "[]")
            except Exception:
                paths = []
            for path in paths:
                try:
                    beads = weweld.path_shapes(doc, path, list(o.Sources))
                except Exception:
                    beads = []
                if not beads:
                    continue
                size = "%g" % float(path.get("size", 3.0))
                if path.get("other"):
                    size += " / %g" % float(path.get("other_size", 3.0))
                sym = "Fillet" + (", both sides" if path.get("other") else "")
                if path.get("type", "Full length") != "Full length":
                    sym += ", %s %g-%g" % (path.get("type"), float(path.get("length", 0)), float(path.get("pitch", 0)))
                key = (size, sym)
                if key not in kinds:
                    kinds.append(key)
                qty[key] = qty.get(key, 0) + len(beads)
                length[key] = length.get(key, 0.0) + sum(weweld._bead_length(b) for b in beads)
                if bead_weight(doc) == "Mass":
                    vol = 0.0
                    for b in beads:
                        try:
                            vol += float(b.Volume)
                        except Exception as _fw_err:
                            _fw_log("drawtables.py:3374", _fw_err)
                    mass[key] = mass.get(key, 0.0) + vol * BEAD_DENSITY
    if not kinds:
        return None
    rows = [list(WELD_HEAD) + (["WELD MASS"] if mass else [])]
    for n, key in enumerate(kinds, 1):
        row = [str(n), str(qty[key]), key[0], key[1], "%.2f" % length[key], "-"]
        if mass:
            row.append(mass_text(mass.get(key, 0.0)))
        rows.append(row)
    return rows


BEAD_DENSITY = 7.85e-6         # kg/mm^3: weld metal (steel) for the bead mass


def bead_weight(doc):
    """Document Properties > Weldments > Bead weight of the weldment part: "Mass" (the Weld Table adds the
    beads' mass) or "Length"."""
    try:
        from . import optionspages
        return optionspages.doc_value(doc, "Weldments", "Bead weight", "Mass")
    except Exception as _fw_err:
        _fw_log("drawtables.py:3456", _fw_err)
        return "Length"


def weld_rows(page, view=None):
    ""


    rows = model_weld_rows(page, view)
    if rows:
        return rows
    kinds = []
    qty = {}
    for o in page.Views:
        w = getattr(o, "SWWeld", "")
        if getattr(o, "SWAnnotation", "") != "WeldSymbol" or not w:
            continue
        if not getattr(o, "SWWeldInTable", True):      # Include this symbol in weld table: off
            continue
        a, asz, b, bsz = (w.split("|") + ["", "", "", ""])[:4]
        key = (a, asz, b, bsz)
        if key not in kinds:
            kinds.append(key)
        qty[key] = qty.get(key, 0) + 1
    rows = [list(WELD_HEAD)]
    for n, key in enumerate(kinds):
        a, asz, b, bsz = key
        sym = " / ".join(s for s in (a, b) if s and s != "None") or "-"
        size = " / ".join(s for s in (asz, bsz) if s) or "-"
        rows.append([str(n + 1), str(qty[key]), size, sym, "-", "-"])
    return rows


def weld_signature(page, view=None):
    """The weld beads of the sheet's models (view: that view's model): name, paths and size, so a bead added,
    edited, moved or deleted changes it."""
    try:
        from . import weweld
    except Exception:
        return ""
    docs = []
    for v in ([view] if view is not None else page.Views):
        if v is None or not v.isDerivedFrom("TechDraw::DrawViewPart"):
            continue
        for src in _fw_xs(v) + list(getattr(v, "Source", []) or []):
            try:
                if src is not None and src.Document not in docs:
                    docs.append(src.Document)
            except Exception as _fw_err:
                _fw_log("drawtables.py:3443", _fw_err)
    out = []
    for doc in docs:
        for o in doc.Objects:
            try:
                if weweld.is_weld_bead(o):
                    vol = round(o.Shape.Volume, 3) if not o.Shape.isNull() else 0.0
                    out.append((doc.Name, o.Name, o.Paths, vol))
            except Exception as _fw_err:
                _fw_log("drawtables.py:3452", _fw_err)
    return repr(out)


def refresh_weld_table(t):
    ""

    page = next((o for o in t.InList if o.TypeId == "TechDraw::DrawPage"), None)
    if page is None:
        return False
    name = getattr(t, "SWTableView", "") if "SWTableView" in t.PropertiesList else ""
    view = t.Document.getObject(name) if name else None
    sig = weld_signature(page, view)
    if "SWWeldSignature" not in t.PropertiesList:
        t.addProperty("App::PropertyString", "SWWeldSignature", "FreeCAD", "the beads the table was made from")
        t.setPropertyStatus("SWWeldSignature", ["Hidden"])
        t.SWWeldSignature = sig
        return False
    if t.SWWeldSignature == sig:
        return False
    t.SWWeldSignature = sig
    set_rows(t, weld_rows(page, view), WELD_WIDTHS)
    return True


def make_weld_table(page, at, view=None):
    t = make_table(page, weld_rows(page, view), at, "Weld Table%d" % (1 + len(
        [o for o in page.Document.Objects if getattr(o, "SWTable", "") == "Weld"])), "Weld", WELD_WIDTHS)
    if view is not None:
        if "SWTableView" not in t.PropertiesList:
            t.addProperty("App::PropertyString", "SWTableView", "FreeCAD", "the view whose model the table lists")
        t.SWTableView = view.Name
    refresh_weld_table(t)                   # what it was made from
    return t


def _alpha_group(panel, prefix):
    """Alpha/Numerical Control: A, B, C... or 1, 2, 3..., with Start at."""
    box, lay = D._group("Alpha/Numerical Control", panel.form)
    panel.alpha = QtWidgets.QRadioButton("A, B, C...", box)
    panel.alpha.setObjectName("SW%sAlpha" % prefix)
    panel.numeric = QtWidgets.QRadioButton("1, 2, 3...", box)
    panel.numeric.setObjectName("SW%sNumeric" % prefix)
    try:                        # Document Properties > Tables > Bend / Hole: Alpha/numerical control
        from . import optionspages
        numeric = optionspages.doc_value(App.ActiveDocument, prefix, "Alpha/numerical control",
                                         "A, B, C...") == "1, 2, 3..."
    except Exception:
        numeric = False
    panel.alpha.setChecked(not numeric)
    panel.numeric.setChecked(numeric)
    panel.start = QtWidgets.QLineEdit("1" if numeric else "A", box)
    panel.start.setObjectName("SW%sStart" % prefix)
    panel.numeric.toggled.connect(lambda on: panel.start.setText("1" if on else "A"))
    row = QtWidgets.QHBoxLayout()
    row.addWidget(QtWidgets.QLabel("Start at:", box))
    row.addWidget(panel.start)
    lay.addWidget(panel.alpha)
    lay.addWidget(panel.numeric)
    lay.addLayout(row)
    panel.lay.addWidget(box)


def _control(panel):
    numeric = panel.numeric.isChecked()
    return ("Numerical" if numeric else "Alpha"), (panel.start.text().strip() or ("1" if numeric else "A"))


class BendTablePanel(D._Panel):
    TITLE = "Bend Table"
    LAYER = True
    PIXMAP = "TechDraw_SpreadsheetView"
    KIND = "Bend"

    def build(self):
        self.say("Click the sheet metal view, then click where the table goes (or it goes to the anchor point).")
        _template_group(self, ("standard bend table",), "standard bend table")
        _position_group(self, False)
        _alpha_group(self, "Bend")
        _border_group(self)
        self.view = None
        self.table = None
        pre = D.preselected_view(self.page)
        if pre is not None and bends(pre):
            self.view = pre
            self.say("%s: click where the table goes, or OK to place it at the anchor point." % pre.Label)

    def make(self, at):
        self.table = make_bend_table(self.page, self.view, at, *_control(self))
        _apply_border(self, self.table)
        self.made.append(self.table)
        QtCore.QTimer.singleShot(0, self.accept)

    def sheet_click(self, p):
        if self.table is not None:
            return False
        if self.view is None:
            v = DV.view_at(self.page, p)
            if v is None:
                self.say("Click a drawing view of the sheet metal part.")
                return True
            if not bends(v):
                self.say("That view's part has no bends. Click a sheet metal view.")
                return True
            self.view = v
            if self.attach.isChecked():
                self.make(anchor(self.page, self.KIND))
                attach(self.table)
                return True
            self.say("Click where the table goes, or OK to place it at the anchor point.")
            return True
        self.make(p)
        return True

    def finish(self):
        ""

        if self.table is None and self.view is not None:
            self.table = make_bend_table(self.page, self.view, anchor(self.page, self.KIND), *_control(self))
            _apply_border(self, self.table)
            attach(self.table)
            self.made.append(self.table)


class PunchTablePanel(HoleTablePanel):
    TITLE = "Punch Table"
    KIND = "Punch"

    def build(self):
        self.say("Click the origin (a corner of the part) in a view, then click where the table goes.")
        _template_group(self, ("standard punch table",), "standard punch table")
        _position_group(self, False)
        _border_group(self)
        self.view = None
        self.origin = None
        self.table = None
        self.edge_x = None
        self.datum = "Vertex"
        self.picked = []
        self.more = []

    def refresh_holes(self):
        pass

    def finish(self):
        pass

    def make(self, at, close=True):
        self.table = make_punch_table(self.page, self.view, self.origin, at)
        _apply_border(self, self.table)
        self.made.append(self.table)
        if close:
            QtCore.QTimer.singleShot(0, self.accept)

    def sheet_click(self, p):
        if self.table is not None:
            return False
        if self.view is None:
            self.pick_origin(p)
            if self.view is not None and self.attach.isChecked():
                self.make(anchor(self.page, self.KIND))
                attach(self.table)
            elif self.view is not None:
                self.say("Click where the table goes.")
            return True
        self.make(p)
        return True


class WeldTablePanel(D._Panel):
    TITLE = "Weld Table"
    LAYER = True
    PIXMAP = "TechDraw_SpreadsheetView"

    def build(self):
        self.view = DV.picked_view() if hasattr(DV, "picked_view") else None
        if self.view is None:
            try:
                from . import drawselect
                self.view = drawselect.picked_view()
            except Exception:
                self.view = None
        self.say("Click a drawing view (its model's welds), then OK (attached to the anchor point) or click where "
                 "the weld table goes." if self.view is None else
                 "Weld Table of %s: OK (attached to the anchor point) or click where it goes." % self.view.Label)
        _template_group(self, ("standard weld table",), "standard weld table")
        _position_group(self, False)
        _border_group(self)
        self.table = None

    def make(self, at):
        self.table = make_weld_table(self.page, at, self.view)
        _apply_border(self, self.table)
        self.made.append(self.table)

    def sheet_click(self, p):
        if self.table is not None:
            return False
        v = DV.view_at(self.page, p)
        if v is not None and v.isDerivedFrom("TechDraw::DrawViewPart"):
            self.view = v
            self.say("Weld Table of %s: OK (attached to the anchor point) or click where it goes." % v.Label)
            return True
        if self.attach.isChecked():
            return False
        self.make(p)
        QtCore.QTimer.singleShot(0, self.accept)
        return True

    def finish(self):
        if self.table is None:
            self.make(anchor(self.page, "Weld"))
            attach(self.table)


# --------------------------------------------------------------------------- Title Block Table
TITLE_BLOCK_WIDTHS = (70, 150, 60, 80)
TITLE_BLOCK_TEMPLATES = ("standard title block", "title block--compact")


def title_block_rows(page, template="standard title block"):
    ""
    from . import drawannot as DA2
    model = DA2.model_document(page)
    k = getattr(page, "Scale", 1.0) or 1.0
    scale = "1:%g" % round(1 / k, 4) if k < 1 else "%g:1" % round(k, 4)
    meta = {}
    for doc in (page.Document, model):
        try:
            meta.update({str(a): str(b) for a, b in dict(doc.Meta).items()})
        except Exception as _fw_err:
            _fw_log("drawtables.py:3679", _fw_err)

    def prop(*names):
        for n in names:
            if meta.get(n):
                return meta[n]
        return ""
    title = prop("Title", "Description") or (model.Label if model is not None else page.Document.Label)
    dwg = prop("PartNo", "Number", "DrawingNo") or page.Document.Label
    drawn = prop("DrawnBy") or getattr(page.Document, "CreatedBy", "") or ""
    date = prop("DrawnDate") or str(getattr(page.Document, "CreationDate", "") or "")[:10]
    sheets = [o for o in page.Document.Objects if o.TypeId == "TechDraw::DrawPage"]
    sheet = "%d OF %d" % (sheets.index(page) + 1 if page in sheets else 1, len(sheets) or 1)
    if template == "title block--compact":
        return [["TITLE:", title, "REV", prop("Revision")],
                ["DWG. NO.", dwg, "SCALE", scale],
                ["DRAWN", drawn, "SHEET", sheet]]
    return [["TITLE:", title, "REV", prop("Revision")],
            ["DWG. NO.", dwg, "SCALE", scale],
            ["MATERIAL", prop("Material"), "WEIGHT", prop("Weight")],
            ["FINISH", prop("Finish"), "SHEET", sheet],
            ["DRAWN", drawn, "DATE", date],
            ["CHECKED", prop("CheckedBy"), "DATE", prop("CheckedDate")]]


def make_title_block_table(page, at=None, template="standard title block"):
    attach_it = at is None
    if at is None:
        at = anchor(page, "TitleBlock")
    t = make_table(page, title_block_rows(page, template), at, "Title Block Table%d" % (1 + len(
        [o for o in page.Document.Objects if getattr(o, "SWTable", "") == "TitleBlock"])), "TitleBlock",
        TITLE_BLOCK_WIDTHS)
    t.addProperty("App::PropertyString", "SWTitleBlockTemplate", "FreeCAD", "Title Block Table template")
    t.SWTitleBlockTemplate = template
    if attach_it:
        attach(t)
    return t


class TitleBlockTablePanel(D._Panel):
    TITLE = "Title Block Table"
    LAYER = True
    PIXMAP = "TechDraw_SpreadsheetView"

    def build(self):
        self.say("Set the options, then OK (attached to the anchor point) or click where the table goes.")
        _template_group(self, TITLE_BLOCK_TEMPLATES, "standard title block")
        _position_group(self, True)
        box, lay = D._group("Table Size", self.form)
        self.lock_widths = QtWidgets.QCheckBox("Lock Column Width", box)
        self.lock_widths.setObjectName("SWTitleBlockLockWidths")
        self.lock_heights = QtWidgets.QCheckBox("Lock Row Height", box)
        self.lock_heights.setObjectName("SWTitleBlockLockHeights")
        lay.addWidget(self.lock_widths)
        lay.addWidget(self.lock_heights)
        self.lay.addWidget(box)
        _border_group(self)
        self.table = None

    def make(self, at):
        self.table = make_title_block_table(self.page, at, self.template.currentText())
        _apply_border(self, self.table)
        if self.lock_widths.isChecked() or self.lock_heights.isChecked():
            from . import drawtableedit
            if self.lock_widths.isChecked():
                drawtableedit.lock(self.table, "width", True)
            if self.lock_heights.isChecked():
                drawtableedit.lock(self.table, "height", True)
        self.made.append(self.table)

    def sheet_click(self, p):
        if self.table is not None or self.attach.isChecked():
            return False
        self.make(p)
        QtCore.QTimer.singleShot(0, self.accept)
        return True

    def finish(self):
        if self.table is None:
            self.make(None)


COMMANDS = {
    "FreeWorks_DrawBOM": ("Bill of Materials", "TechDraw_SpreadsheetView",
                          "Adds a bill of materials of the parts in a view."),
    "FreeWorks_DrawHoleTable": ("Hole Table", "TechDraw_SpreadsheetView",
                                "Adds a table of the holes in a view, located from an origin."),
    "FreeWorks_DrawRevisionTable": ("Revision Table", "TechDraw_SpreadsheetView", "Adds a revision table."),
    "FreeWorks_DrawAddRevision": ("Add Revision", "TechDraw_SpreadsheetView", "Adds a revision to the revision table."),
    "FreeWorks_DrawRevisionSymbol": ("Revision Symbol", "TechDraw_Annotation",
                                     "Adds a revision symbol of the latest revision."),
    "FreeWorks_DrawGeneralTable": ("General Table", "TechDraw_SpreadsheetView", "Adds a general table."),
    "FreeWorks_DrawUpdateTable": ("Update Table", "TechDraw_SpreadsheetView",
                                  "Makes a picked bill of materials or hole table again from the model."),
    "FreeWorks_DrawBendTable": ("Bend Table", "TechDraw_SpreadsheetView", "Adds a table of a sheet metal view's bends."),
    "FreeWorks_DrawPunchTable": ("Punch Table", "TechDraw_SpreadsheetView",
                                 "Adds a table of the punches in a view, located from an origin."),
    "FreeWorks_DrawWeldTable": ("Weld Table", "TechDraw_SpreadsheetView", "Adds a table of the sheet's welds."),
    "FreeWorks_DrawDesignTable": ("Design Table", "TechDraw_SpreadsheetView",
                                  "Adds the design table of the model in the picked view (else the first view)."),
    "FreeWorks_DrawTitleBlockTable": ("Title Block Table", "TechDraw_SpreadsheetView",
                                      "Adds a title block table filled from the model's properties."),
}
PANELS = {"FreeWorks_DrawBOM": BomPanel, "FreeWorks_DrawHoleTable": HoleTablePanel,
          "FreeWorks_DrawRevisionTable": RevisionTablePanel,
          "FreeWorks_DrawRevisionSymbol": RevisionSymbolPanel, "FreeWorks_DrawGeneralTable": GeneralTablePanel,
          "FreeWorks_DrawBendTable": BendTablePanel, "FreeWorks_DrawPunchTable": PunchTablePanel,
          "FreeWorks_DrawWeldTable": WeldTablePanel, "FreeWorks_DrawTitleBlockTable": TitleBlockTablePanel}


def _picked_view(page):
    for o in Gui.Selection.getSelection():
        if o.isDerivedFrom("TechDraw::DrawViewPart"):
            return o
    views = [v for v in D.views_of(page) if v.isDerivedFrom("TechDraw::DrawViewPart")]
    return views[0] if views else None


def picked_table():
    for sel in Gui.Selection.getSelectionEx("", 0):
        if getattr(sel.Object, "SWTable", ""):
            return sel.Object
    return None



def _model3d():
    """drawmbd when a part or assembly window is active (the 3D, MBD versions of the commands)."""
    try:
        from . import drawmbd
    except Exception:
        return None
    return drawmbd if drawmbd.model_doc() is not None else None

class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.pixmap, self.tip = COMMANDS[name]

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": D.pixmap(self.pixmap)}

    def IsActive(self):
        model = _model3d()
        if model is not None:
            return model.active(self.name)     # in a part or assembly: the 3D (MBD) annotation
        page = D.active_page()
        if page is None or D.busy() or not D.sheet_shown(page):
            return False
        try:
            from . import drawsheet
            if drawsheet.greyed_on_format(page, self.name):
                return False
        except Exception as _fw_err:
            _fw_log("drawtables.py:3833", _fw_err)
        if self.name in ("FreeWorks_DrawBOM", "FreeWorks_DrawHoleTable", "FreeWorks_DrawBendTable",
                         "FreeWorks_DrawPunchTable"):
            return bool(D.views_of(page))
        if self.name == "FreeWorks_DrawWeldTable":
            return bool(D.views_of(page))
        if self.name == "FreeWorks_DrawRevisionTable":
            return revision_table(page) is None
        if self.name == "FreeWorks_DrawRevisionSymbol":
            return revision_table(page) is not None or bool(revision_tables(page.Document))   # annotab-1121: greyed until the drawing has a revision table
        if self.name == "FreeWorks_DrawUpdateTable":
            t = picked_table()
            return t is not None and t.SWTable in ("BOM", "Hole", "Bend", "Punch", "Weld", "TitleBlock", "DesignTable", "FamilyTable")
        if self.name == "FreeWorks_DrawDesignTable":
            return bool(D.views_of(page))
        return True

    def Activated(self):
        model = _model3d()
        if model is not None:
            model.run(self.name)
            return
        page = D.active_page()
        if page is None:
            return
        doc = page.Document
        if self.name in PANELS:
            D._show(PANELS[self.name](page))
            return
        doc.openTransaction(self.text)
        try:
            if self.name == "FreeWorks_DrawRevisionTable":
                make_revision_table(page)
            elif self.name == "FreeWorks_DrawAddRevision":
                add_revision(page)
                t = revision_table(page)
                if t is not None and getattr(t, "SWRevAutoSymbol", False):
                    # Enable symbol when adding new revision: the Revision Symbol tool starts
                    QtCore.QTimer.singleShot(0, lambda: D._show(RevisionSymbolPanel(page)))
            elif self.name == "FreeWorks_DrawUpdateTable":
                t = picked_table()
                if t is not None:
                    update_table(t)
            elif self.name == "FreeWorks_DrawDesignTable":
                view = _picked_view(page)
                try:
                    Gui.Selection.clearSelection()
                    Gui.Selection.addSelection(make_design_table(page, view))
                except ValueError as error:
                    QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Design Table", str(error))
        finally:
            doc.commitTransaction()
        doc.recompute()


def register():
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
    try:
        from . import drawtableedit          # the table right-click actions (Insert, Delete, Merge, Sort, Split...)
        drawtableedit.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: table editing commands not added: %s\n" % error)


def remember_signature(t):
    """Record the model a table was just made from, so a later model change updates it."""
    try:
        prop = TABLE_VIEW.get(getattr(t, "SWTable", ""))
        view = t.Document.getObject(getattr(t, prop, "") or "") if prop else None
        if view is not None:
            _SIGS[(t.Document.Name, t.Name)] = table_signature(t, view)
        if getattr(t, "SWTable", "") == "CutList":
            part = cut_list_part(t)
            if part is not None:
                from . import drawmenus
                _CUT_ROWS[(t.Document.Name, t.Name)] = drawmenus.cut_list_rows(part)
    except Exception as _fw_err:
        _fw_log("drawtables.py:3910", _fw_err)


def _remembering(fn, from_arg=False):
    import functools

    @functools.wraps(fn)
    def run(*args, **kwargs):
        out = fn(*args, **kwargs)
        target = args[0] if from_arg and args else out
        if target is not None and hasattr(target, "SWTable"):
            remember_signature(target)
        return out
    return run


for _name in ("make_bom", "make_hole_table", "make_bend_table", "make_punch_table"):
    if not getattr(globals().get(_name), "__wrapped__", None):
        globals()[_name] = _remembering(globals()[_name])
if not getattr(update_table, "__wrapped__", None):
    update_table = _remembering(update_table, from_arg=True)
