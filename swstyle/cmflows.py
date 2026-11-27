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

import re

import FreeCAD as App

TITLE = "Design Table for: %s"
HIDDEN = "FreeWorks:DesignTableDeleted"
ORDER = "FreeWorks:CfgTreeOrder"
ORDERS = ("History", "Numeric", "Literal", "Manual")
PRP = "FreeWorks:CfgPrp:"
FIRST_VALUES = ("Length", "Angle", "Radius", "Size", "Depth", "Height", "Offset", "Value")
SECOND_VALUES = ("Length2", "Size2", "Angle2", "Radius2")
DIMENSIONAL = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle")
_clip = {}


def _cm():
    from . import configmanager
    return configmanager


def _cfg():
    from . import configs
    return configs


def _find(doc, name):
    for o in doc.Objects:
        if o.Label == name or o.Name == name:
            return o
    return None


def _dims(sketch):
    return [(i, c) for i, c in enumerate(sketch.Constraints) if c.Type in DIMENSIONAL and getattr(c, "Driving", True)]


# --------------------------------------------------------------------------- headers
def parse_header(doc, header):
    """(kind, obj, prop) for a design table header, or None when it means nothing here."""
    h = str(header or "").strip()
    if not h:
        return None
    up = h.upper()
    if up in ("$DESCRIPTION", "$PARTNUMBER", "$COLOR", "$COMMENT", "$USER_NOTES", "$PARENT"):
        return (up[1:].lower(), None, None)
    if up.startswith("$PRP@"):
        return ("prp", None, h[5:].strip().strip('"'))
    for head in ("$STATE@", "$CONFIGURATION@", "$SHOW@", "D1@"):
        if up.startswith(head.upper()):
            got = _asm_parse(doc, head, h[len(head):])
            if got:
                return got
    if up.startswith("$STATE@"):
        obj = _find(doc, h[7:].strip())
        return ("state", obj, None) if obj is not None else None
    if up.startswith("$VALUE@") and up.endswith("@EQUATIONS"):

        name = h[7:-10].strip().strip('"')
        try:
            from . import equations
            if any(n == name for n, _raw, _got in equations.variables(doc)):
                return ("var", None, name)
        except Exception as _fw_err:
            _fw_log("cmflows.py:97", _fw_err)
        return None
    if "@" not in h:
        return None
    what, owner = h.split("@", 1)
    obj = _find(doc, owner.strip())
    if obj is None:
        return None
    what = what.strip()
    if obj.TypeId.startswith("Sketcher::SketchObject"):
        for i, c in enumerate(obj.Constraints):
            if c.Name == what and c.Type in DIMENSIONAL:
                return ("value", obj, "Constraints." + what)
        m = re.match(r"D(\d+)$", what)
        dims = _dims(obj)
        if m and 0 < int(m.group(1)) <= len(dims):
            i, c = dims[int(m.group(1)) - 1]
            if not c.Name:
                obj.renameConstraint(i, what)
            return ("value", obj, "Constraints." + (c.Name or what))
        return None
    dims = _extra(obj)
    if dims is not None:                    # D1@Plane1 is the offset, not the size (refdims-fix01)
        m = re.match(r"D(\d+)$", what)
        if m and 0 < int(m.group(1)) <= len(dims):
            return ("value", obj, dims[int(m.group(1)) - 1])
        return ("value", obj, what) if what in dims else None
    if what in obj.PropertiesList:
        return ("value", obj, what)
    m = re.match(r"D(\d+)$", what)
    if m:
        pool = FIRST_VALUES if m.group(1) == "1" else SECOND_VALUES
        for p in pool:
            if p in obj.PropertiesList:
                return ("value", obj, p)
    return None


def _extra(obj):
    try:
        from . import equations
        return equations.extra_dims(obj)
    except Exception as _fw_err:
        _fw_log("cmflows.py:extra", _fw_err)
        return None


def unit_k(obj, prop):
    ""

    try:
        from . import equations
        if equations._kind(obj, prop) == "len":
            return equations._doc_length(obj.Document)[1]
    except Exception as _fw_err:
        _fw_log("cmflows.py:unit", _fw_err)
    return None


def _plain(value):
    try:
        float(str(value).strip())
        return True
    except ValueError:
        return False


def from_table(obj, prop, value):
    """A table cell as the dimension's value in mm: a plain number is in the part's unit, 2in or 50mm as written."""
    k = unit_k(obj, prop)
    if k and _plain(value):
        return float(str(value).strip()) * k
    return _cfg()._number(value)


def to_table(obj, prop, text):
    """The other way: a stored mm value as the table shows it, in the part's unit."""
    k = unit_k(obj, prop)
    if not k or k == 1.0 or not _plain(text):
        return text
    return "%.10g" % (float(str(text).strip()) / k)


def equation_on(obj, prop, t=None):
    ""

    engine = dict(getattr(obj, "ExpressionEngine", []) or [])
    expr = engine.get(prop) or engine.get("." + prop) or ""
    if not expr:
        return ""
    sheet = t.sheet.Name if t is not None else None
    if sheet and re.match(r"^\s*%s\.\w+\s*$" % re.escape(sheet), expr):
        return ""
    try:
        from . import configmanager
        tt = configmanager.table(obj.Document)
        if tt is not None and re.match(r"^\s*%s\.\w+\s*$" % re.escape(tt.sheet.Name), expr):
            return ""
    except Exception as _fw_err:
        _fw_log("cmflows.py:eqon", _fw_err)
    return expr


def _truthy_state(text):
    t = str(text).strip().upper()
    return t in ("S", "SUPPRESSED", "1", "1.0", "TRUE", "YES")


def colour_of(value):
    ""
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return None
    return ((n & 255) / 255.0, ((n >> 8) & 255) / 255.0, ((n >> 16) & 255) / 255.0)


def colour_number(rgb):
    r, g, b = (int(round(c * 255)) for c in rgb[:3])
    return r + 256 * g + 65536 * b


# --------------------------------------------------------------------------- reading a table
def header_row(rows):
    for i, row in enumerate(rows[:6]):
        cells = [str(c).strip() for c in row[1:] if str(c).strip()]
        if cells and all("@" in c or c.startswith("$") for c in cells):
            return i
    return 0


def apply_table(doc, rows):
    """A design table's rows into the part: a configuration per row, each header a parameter.
    Returns {"configurations": [...], "parameters": [...], "skipped": [...]}."""
    cm, cf = _cm(), _cfg()
    t = cf.table(doc)
    if table_deleted(doc):
        restore_table(doc)          # a design table read from a file shows
    h = header_row(rows)
    heads = [str(c).strip() for c in rows[h]]
    parsed = [parse_header(doc, c) if i else None for i, c in enumerate(heads)]
    out = {"configurations": [], "parameters": [heads[i] for i, p in enumerate(parsed) if p],
           "skipped": [heads[i] for i, p in enumerate(parsed) if i and heads[i] and not p], "equations": []}
    for i, p in enumerate(parsed):
        if p and p[0] == "value" and equation_on(p[1], p[2], t):
            out["equations"].append(heads[i])     # its equation drives it: the table's values are not used
            App.Console.PrintWarning("FreeCAD design table: %s is driven by an equation; the equation is kept and "
                                     "the table's values for it are not used\n" % heads[i])
            parsed[i] = None
    active = t.active()
    data = [r for r in rows[h + 1:] if r and str(r[0]).strip()]
    pcol = [i for i, p in enumerate(parsed) if p and p[0] == "parent"]
    doc.openTransaction("Design Table")
    try:
        for row in data:
            name = str(row[0]).strip()
            made = name not in t.names()

            parent = str(row[pcol[0]]).strip() if pcol and pcol[0] < len(row) else ""
            if parent not in t.names() or parent == name or name in [parent] + cm.parents_up(doc, parent):
                parent = ""
            if made:
                if parent and t.active() != parent:
                    cm.show(t, parent)          # it starts with its parent's values
                    t = cm.table(doc)
                cm.add(t, name, from_table=True)
                t = cm.table(doc)
            elif name in cm.outside_table(doc):
                cm.set_outside_table(doc, name, False)      # typed into the table: the table has it now
            if parent and cm.parent_of(doc, name) != parent:
                meta = dict(doc.Meta)
                meta[cm.PARENT + name] = parent
                doc.Meta = meta
            out["configurations"].append(name)
            for i, p in enumerate(parsed):
                if not p:
                    continue
                cell = row[i] if i < len(row) else ""
                if str(cell).strip() == "":

                    # configuration the table makes; an existing one keeps what it has)
                    if made and p[0] == "asm" and p[2] in ("suppress", "msup", "hide"):
                        cell = "Y" if p[2] == "hide" else "U"
                    else:
                        continue
                _apply(doc, t, name, p, cell)
                t = cm.table(doc)
    finally:
        doc.commitTransaction()
    t = cm.table(doc)
    cm.show(t, active if active in t.names() else (out["configurations"] or [active])[0])
    return out


def _apply(doc, t, name, parsed, value):
    cm, cf = _cm(), _cfg()
    kind, obj, prop = parsed
    if kind == "description":
        cf.set_properties(doc, name, description=str(value))
    elif kind == "partnumber":
        cf.set_properties(doc, name, part_number=str(value), bom="User Specified")
    elif kind == "state":
        alias = cf.SUPPRESS + cf._safe(obj.Name)
        cf.ensure_column(t, alias, "1" if cf.is_suppressed(obj) else "0")
        cf.set_cell(t, alias, "1" if _truthy_state(value) else "0", [name])
        obj.setExpression("Suppressed", "%s.%s == 1" % (t.sheet.Name, alias))
    elif kind == "value":
        alias = cf._alias_for(obj, prop)
        cf.ensure_column(t, alias, cf._number(cf._current(obj, prop)))
        cf.set_cell(t, alias, from_table(obj, prop, value), [name])
        obj.setExpression(prop, "%s.%s" % (t.sheet.Name, alias))
    elif kind == "asm":
        from . import asmconfigure as acf
        prefix = dict((k, p) for k, p, _h in _asm_kinds())[prop]
        alias = acf._alias(prefix, obj)
        cf.ensure_column(t, alias, acf.now_value(obj, prop))
        cf.set_cell(t, alias, _asm_cell(prop, value), [name])
    elif kind == "var":
        from . import configtable, equations
        col = configtable.variable_column(doc, prop)
        alias = configtable.VAR + cf._safe(prop)
        cf.ensure_column(t, alias, cf._number(col.current()))
        cf.set_cell(t, alias, cf._number(value), [name])
        if _variable_bound_to(doc, "%s.%s" % (t.sheet.Name, alias)) is None:
            col.bind(t.sheet, alias)
    elif kind in ("color", "comment"):
        ex = cm.extras(doc, name)
        colour = colour_of(value) if kind == "color" else ex["color"]
        comment = str(value) if kind == "comment" else ex["comment"]
        cm.set_extras(doc, name, ex["use_in_bom"], comment, colour)
    elif kind == "prp":
        set_property(doc, name, prop, str(value))
    elif kind == "user_notes":
        pass
    doc.recompute()


def set_property(doc, name, prop, value):
    ""

    from . import fileprops
    rows = [r for r in fileprops.read_config(doc, name) if r[0] != prop]
    old = [r for r in fileprops.read_config(doc, name) if r[0] == prop]
    if value:
        kind = old[0][1] if old else "Text"
        at = fileprops.read_config(doc, name).index(old[0]) if old else len(rows)
        rows.insert(at, (prop, kind, value))
    fileprops.write_config(doc, name, rows)
    meta = dict(doc.Meta)
    if meta.pop("%s%s:%s" % (PRP, name, prop), None) is not None:      # the old store (before features/181)
        doc.Meta = meta


def config_properties(doc, name):
    from . import fileprops
    p = "%s%s:" % (PRP, name)
    out = {k[len(p):]: v for k, v in dict(doc.Meta).items() if k.startswith(p)}      # old store
    for prop, _kind, value in fileprops.read_config(doc, name):
        out[prop] = value
    return out


def import_file(doc, path):
    """Insert > Tables > Design Table > From file: the table read and applied to the part."""
    from . import dtoptions
    rows = dtoptions._read(path)
    if rows is None:
        raise RuntimeError("Could not read %s" % path)
    return apply_table(doc, rows)


# --------------------------------------------------------------------------- writing a table

# $STATE@ / D1@ for mates, on the assembly's Configure Component / Configure Mate columns

def _asm_kinds():
    from . import asmconfigure as acf
    return (("suppress", acf.configs.COMP, "$STATE@"), ("config", acf.CFG, "$CONFIGURATION@"),
            ("hide", acf.HIDE, "$SHOW@"), ("msup", acf.MATE_SUP, "$STATE@"), ("mval", acf.MATE_VAL, "D1@"))


def _asm_items(doc):
    try:
        from . import asmcore as ac
        asm = ac.assembly_of(doc)
        if asm is None:
            return []
        return list(ac.components(asm)) + list(ac.mates(asm))
    except Exception as _fw_err:
        _fw_log("cmflows.py:296", _fw_err)
        return []


def _asm_header(doc, alias):
    try:
        from . import asmconfigure as acf
    except Exception:
        return None
    for kind, prefix, head in _asm_kinds():
        if not alias.startswith(prefix):
            continue
        for obj in _asm_items(doc):
            if acf._alias(prefix, obj) == alias:
                return head + obj.Label
    return None


def _asm_parse(doc, head, rest):
    """("asm", obj, kind) for an assembly header, or None."""
    items = _asm_items(doc)
    if not items:
        return None
    from . import asmmenu
    label = rest.strip()
    obj = next((o for o in items if o.Label == label or o.Name == label), None)
    if obj is None:
        return None
    mate = asmmenu.is_mate(obj)
    kind = {("$STATE@", False): "suppress", ("$STATE@", True): "msup", ("$CONFIGURATION@", False): "config",
            ("$SHOW@", False): "hide", ("D1@", True): "mval"}.get((head, mate))
    return ("asm", obj, kind) if kind else None


def _asm_cell(kind, value):
    v = str(value).strip()
    if kind in ("suppress", "msup"):
        return "1" if _truthy_state(v) else "0"
    if kind == "hide":
        return "0" if v.upper() in ("Y", "YES", "SHOW", "1", "TRUE") else "1"
    return v


def _variable_bound_to(doc, ref):
    """The global variable whose value is the table cell ref (Sheet.Var_x), or None."""
    try:
        from . import equations
        s = equations.sheet(doc)
        if s is None:
            return None
        for _r, n, raw in equations._rows(s):
            if str(raw or "").lstrip("=").strip() == ref:
                return n
    except Exception as _fw_err:
        _fw_log("cmflows.py:348", _fw_err)
    return None


def header_of(doc, sheet, alias):
    ""
    cf = _cfg()
    if alias == cf.DESCRIPTION:
        return "$DESCRIPTION"
    if alias == cf.PART_NUMBER:
        return "$PARTNUMBER"
    if alias.startswith(cf.SUPPRESS):
        for o in doc.Objects:
            if cf._safe(o.Name) == alias[len(cf.SUPPRESS):]:
                return "$STATE@" + o.Label
    asm = _asm_header(doc, alias)
    if asm:
        return asm
    ref = "%s.%s" % (sheet.Name, alias)
    if alias.startswith("Var_"):         # a configured global variable (Configure Equation)
        name = _variable_bound_to(doc, ref)
        if name:
            return "$VALUE@%s@equations" % name
    for o in doc.Objects:
        for path, expr in getattr(o, "ExpressionEngine", []) or []:
            if (expr or "").strip() == ref:
                path = path.lstrip(".")
                if path.startswith("Constraints."):
                    return "%s@%s" % (path.split(".", 1)[1], o.Label)
                if path in FIRST_VALUES:
                    path = "D1"
                elif path in SECOND_VALUES:
                    path = "D2"
                return "%s@%s" % (path, o.Label)
    return None


def table_rows(doc):
    ""
    cm, cf = _cm(), _cfg()
    t = cm.table(doc)
    if t is None:
        return []
    cols, heads = [], []
    for c in t.columns():
        try:
            alias = t.sheet.getAlias("%s%d" % (c, t.first - 1))
        except Exception:
            alias = None
        h = header_of(doc, t.sheet, alias) if alias else None
        if h:
            cols.append(c)
            heads.append(h)
    gone = set(cm.outside_table(doc))
    names = [n for n in t.names() if n not in gone]     # added while Options > New configurations was off
    extra = [("$PARENT", lambda n: cm.parent_of(doc, n)),
             ("$COLOR", lambda n: cm.extras(doc, n)["color"]), ("$COMMENT", lambda n: cm.extras(doc, n)["comment"])]
    extra = [(h, fn) for h, fn in extra if any(fn(n) for n in names)]
    props = sorted({p for n in names for p in config_properties(doc, n)})
    rows = [[TITLE % doc.Label], [""] + heads + [h for h, _f in extra] + ["$PRP@" + p for p in props]]
    lengths = {}
    for c, h in zip(cols, heads):
        p = parse_header(doc, h) if not h.startswith("$") else None
        if p and p[0] == "value":
            lengths[c] = (p[1], p[2])
    for n in names:
        r = t.row_of(n)
        row = [n]
        for c in cols:
            v = t._text("%s%d" % (c, r))
            if c in lengths:
                v = to_table(lengths[c][0], lengths[c][1], v)      # in the part's unit
            if c and heads[cols.index(c)].startswith("$STATE@"):
                v = "S" if v.strip() in ("1", "1.0") else "U"
            elif c and heads[cols.index(c)].startswith("$SHOW@"):
                v = "N" if v.strip() in ("1", "1.0") else "Y"
            row.append(v)
        for h, fn in extra:
            v = fn(n)
            row.append(colour_number(v) if h == "$COLOR" and v else (v or ""))
        cp = config_properties(doc, n)
        row += [cp.get(p, "") for p in props]
        rows.append(row)
    return rows


_NUMBER = __import__("re").compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][-+]?[0-9]+)?")


def _col(n):
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def write_xlsx(rows, path, sheet="Sheet1"):
    """A plain .xlsx workbook of rows (numbers as numbers, the rest as text), written with the standard
    library: stock FreeCAD has no Excel writer."""
    import zipfile
    from xml.sax.saxutils import escape
    lines = []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, v in enumerate(row, 1):
            ref = "%s%d" % (_col(c), r)
            text = "" if v is None else str(v)
            if not text:
                continue            # Excel writes no cell for an empty one
            if _NUMBER.fullmatch(text.strip()):
                cells.append('<c r="%s"><v>%s</v></c>' % (ref, text.strip()))
                continue
            cells.append('<c r="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, escape(text)))
        lines.append('<row r="%d">%s</row>' % (r, "".join(cells)))
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="%s/officeDocument" Target="xl/workbook.xml"/></Relationships>' % rel,
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="%s" xmlns:r="%s"><sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets></workbook>'
        % (ns, rel, escape(sheet)),
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="%s/worksheet" Target="worksheets/sheet1.xml"/></Relationships>' % rel,
        "xl/worksheets/sheet1.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="%s"><sheetData>%s</sheetData></worksheet>' % (ns, "".join(lines)),
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def save_table(doc, path):
    """Save Table...: the design table as a .xlsx (Excel) or .csv file."""
    rows = table_rows(doc)
    if path.lower().endswith(".xlsx"):
        try:
            import openpyxl
        except ImportError:
            return write_xlsx(rows, path)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        for row in rows:
            ws.append(row)
        wb.save(path)
        return path
    import csv
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    return path


# --------------------------------------------------------------------------- Auto-create
def candidates(doc):
    """[(header, obj, prop, value)] the Auto-create Dimensions box lists."""
    out = []
    try:
        from . import equations
        k = equations._doc_length(doc)[1]
    except Exception:
        k = 1.0
    for o in doc.Objects:
        if o.TypeId.startswith("Sketcher::SketchObject"):
            for n, (i, c) in enumerate(_dims(o), 1):
                name = c.Name or "D%d" % n
                path = "Constraints." + name if c.Name else None
                if path and equation_on(o, path):
                    continue
                if not c.Name and equation_on(o, "Constraints[%d]" % i):
                    continue
                out.append(("%s@%s" % (name, o.Label), o, path,
                            c.Value / k if c.Type != "Angle" else c.Value * 57.29577951308232, i))
        elif _extra(o) is not None:
            # a plane's offset or angle (D1@Plane1, never its display size), a Helix/Spiral's values, a
            # circular-profile sweep's diameter; an axis, point or coordinate system has none (refdims-fix01)
            for n, p in enumerate(_extra(o), 1):
                if not equation_on(o, p):
                    v = getattr(o, p)
                    v = v.Value if hasattr(v, "Value") else float(v)
                    out.append(("D%d@%s" % (n, o.Label), o, p, v / k if unit_k(o, p) else v, None))
        elif o.TypeId.startswith("PartDesign::") and o.TypeId not in ("PartDesign::Body",):
            for n, pool in ((1, FIRST_VALUES), (2, SECOND_VALUES)):
                for p in pool:
                    if p in o.PropertiesList and hasattr(getattr(o, p), "Value"):
                        if not _shown(o, p):
                            break
                        if not equation_on(o, p):
                            v = getattr(o, p)
                            out.append(("D%d@%s" % (n, o.Label), o, p, v.Value / k if unit_k(o, p) else v.Value, None))
                        break
    return out


def _shown(obj, prop):
    try:
        from . import equations
        return equations.shown_dim(obj, prop)
    except Exception as _fw_err:
        _fw_log("cmflows.py:shown", _fw_err)
        return True


def auto_create(doc, headers):
    """The picked dimensions become the table's columns (each configuration keeps today's value)."""
    cf = _cfg()
    t = cf.table(doc)
    if table_deleted(doc):
        restore_table(doc)          # a design table made on purpose shows
    made = []
    doc.openTransaction("Auto-create Design Table")
    try:
        for h in headers:
            p = parse_header(doc, h)
            if not p or p[0] != "value":
                continue
            _k, obj, prop = p
            if equation_on(obj, prop, t):
                continue                    # its equation keeps driving it
            alias = cf._alias_for(obj, prop)
            cf.ensure_column(t, alias, cf._number(cf._current(obj, prop)))
            obj.setExpression(prop, "%s.%s" % (t.sheet.Name, alias))
            made.append(h)
        doc.recompute()
    finally:
        doc.commitTransaction()
    _cm().refresh_all()
    return made


def ask_auto_create(doc):
    from PySide import QtCore, QtWidgets
    import FreeCADGui as Gui
    items = candidates(doc)
    if not items:
        return []
    d = QtWidgets.QDialog(Gui.getMainWindow())
    d.setWindowTitle("Dimensions")
    d.setObjectName("SWDesignTableDimensions")
    lay = QtWidgets.QVBoxLayout(d)
    lay.addWidget(QtWidgets.QLabel("Select the dimensions to add to the design table:"))
    lst = QtWidgets.QListWidget()
    for h, _o, _p, v, _i in items:
        it = QtWidgets.QListWidgetItem("%s   %.4g" % (h, v))       # in the part's unit
        it.setData(QtCore.Qt.UserRole, h)
        it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)     # (an int flag fails on PySide6: no box)
        it.setCheckState(QtCore_Unchecked())
        lst.addItem(it)
    lay.addWidget(lst)
    bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    bb.accepted.connect(d.accept)
    bb.rejected.connect(d.reject)
    lay.addWidget(bb)
    if not d.exec():
        return []
    picked = [lst.item(i).data(QtCore.Qt.UserRole) for i in range(lst.count()) if lst.item(i).checkState() == QtCore_Checked()]
    return auto_create(doc, picked)


def QtCore_Checked():
    from PySide import QtCore
    return QtCore.Qt.Checked


def QtCore_Unchecked():
    from PySide import QtCore
    return QtCore.Qt.Unchecked


# --------------------------------------------------------------------------- ConfigurationManager rows
def copy(doc, name):
    _clip["config"] = (doc.Name, name)
    return name


def can_paste(doc):
    return _clip.get("config", (None,))[0] == doc.Name


def paste(doc):
    """Paste: the copied configuration as "Copy of <name>" with all its values."""
    cm = _cm()
    if not can_paste(doc):
        return None
    t = cm.table(doc)
    src = _clip["config"][1]
    if t is None or src not in t.names():
        return None
    new = "Copy of %s" % src
    n = 2
    while new in t.names():
        new = "Copy of %s (%d)" % (src, n)
        n += 1
    srow = t.row_of(src)
    shown = t.active()
    if not cm.add(t, new):
        return None
    t = cm.table(doc)
    row = t.row_of(new)
    for c in t.columns():
        t.sheet.set("%s%d" % (c, row), str(t.sheet.getContents("%s%d" % (c, srow))))
    ex = cm.extras(doc, src)
    cm.set_extras(doc, new, ex["use_in_bom"], ex["comment"], ex["color"])
    try:
        from . import fileprops         # fp96: with their types and units
        fileprops.copy_config(doc, src, new)
    except Exception as _fw_err:
        _fw_log("cmflows.py:paste-props", _fw_err)
        for p, v in config_properties(doc, src).items():
            set_property(doc, new, p, v)
    doc.recompute()
    cm._bind(t)
    doc.recompute()
    if shown in cm.table(doc).names() and cm.table(doc).active() != shown:
        cm.show(cm.table(doc), shown)
    cm.refresh_all()
    return new


def tree_order(doc):
    o = dict(doc.Meta or {}).get(ORDER, "History")
    return o if o in ORDERS else "History"


def set_tree_order(doc, order):
    meta = dict(doc.Meta)
    meta[ORDER] = order
    doc.Meta = meta
    _cm().refresh_all()


def _natural(text):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", text)]


def ordered(doc, names):
    """Tree Order: History / Manual keep the table's order, Literal sorts by name, Numeric by the
    numbers in the names."""
    o = tree_order(doc)
    if o == "Literal":
        return sorted(names, key=lambda n: n.lower())
    if o == "Numeric":
        return sorted(names, key=_natural)
    return list(names)


def rebuild_all(doc):
    """Rebuild All Configurations: each configuration shown and rebuilt, then the active one again.
    Returns {configuration: [failed features]}."""
    cm = _cm()
    t = cm.table(doc)
    if t is None:
        doc.recompute()
        return {"Default": []}
    active = t.active()
    out = {}
    for n in t.names():
        cm.show(t, n)
        doc.recompute()
        out[n] = [o.Label for o in doc.Objects if "Invalid" in o.State or "Error" in o.State]
    cm.show(cm.table(doc), active)
    return out


def table_deleted(doc):
    return dict(doc.Meta or {}).get(HIDDEN, "") == "1"


def delete_table(doc, ask=True):
    """Delete on the design table: the table goes from the tree, the configurations stay."""
    if ask and App.GuiUp:
        from PySide import QtWidgets
        import FreeCADGui as Gui
        if QtWidgets.QMessageBox.question(Gui.getMainWindow(), "Design Table",
                                          "Delete the design table? The configurations stay.",
                                          QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
            return False
    meta = dict(doc.Meta)
    meta[HIDDEN] = "1"
    doc.Meta = meta
    _show_sheets(doc, False)
    _cm().refresh_all()
    return True


def _show_sheets(doc, on):
    """The design table's sheet in the FeatureManager tree: gone while the table is deleted."""
    t = _cm().table(doc)
    sheet = getattr(t, "sheet", None)
    try:
        if sheet is not None and sheet.ViewObject is not None:
            sheet.ViewObject.ShowInTree = bool(on)
    except Exception as _fw_err:
        _fw_log("cmflows.py:703", _fw_err)


def restore_table(doc):
    meta = dict(doc.Meta)
    meta.pop(HIDDEN, None)
    doc.Meta = meta
    _show_sheets(doc, True)
    _cm().refresh_all()


def edit_in_new_window(t):
    return _cm().edit_table(t, new_window=True)


def _safe(fn):
    try:
        return fn()
    except Exception as error:
        App.Console.PrintLog("FreeCAD cmflows: %s\n" % error)


def ask_save_table(doc):
    from PySide import QtWidgets
    import FreeCADGui as Gui
    p = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save Table", doc.Label + " design table.xlsx",
                                              "Excel (*.xlsx);;CSV (*.csv)")[0]
    return save_table(doc, p) if p else None


def ask_tree_order(doc):
    from PySide import QtWidgets
    import FreeCADGui as Gui
    now = tree_order(doc)
    o, ok = QtWidgets.QInputDialog.getItem(Gui.getMainWindow(), "Tree Order", "Order the configurations by:",
                                           list(ORDERS), ORDERS.index(now), False)
    if ok:
        set_tree_order(doc, o)
    return o if ok else None


def go_to(page, doc):
    """Go To...: the configuration whose name has the text, picked in the tree."""
    from PySide import QtWidgets
    import FreeCADGui as Gui
    text, ok = QtWidgets.QInputDialog.getText(Gui.getMainWindow(), "Go To", "Find what:")
    if not ok or not text.strip():
        return None
    t = _cm().table(doc)
    for n in (t.names() if t else []):
        if text.strip().lower() in n.lower():
            item = page.item_for(n) if page is not None else None
            if item is not None:
                page.tree.setCurrentItem(item)
                page.tree.scrollToItem(item)
            return n
    return None


def entries(page, doc, t, d, out):
    """configmanager.Page.entries' list with these rows added."""
    try:
        keys = [e[0] for e in out]
        if d[0] == "config" and t is not None:
            name = d[1]
            at = keys.index("Delete") if "Delete" in keys else len(out)
            out[at:at] = [("Copy", lambda: copy(doc, name), True), ("Paste", lambda: paste(doc), can_paste(doc))]
        elif d[0] in ("part", "default"):
            if t is not None and table_deleted(doc):
                out = [e for e in out if e[0] != "Edit Table..."]
                out.append(("Insert Design Table", lambda: restore_table(doc), True))
            out += [("Paste", lambda: paste(doc), t is not None and can_paste(doc)),
                    ("Rebuild All Configurations", lambda: rebuild_all(doc), True),
                    ("Tree Order...", lambda: ask_tree_order(doc), t is not None),
                    ("Go To...", lambda: go_to(page, doc), t is not None)]
        elif d[0] == "table" and t is not None:
            from . import dtoptions
            linked = bool(dtoptions.options(t.sheet).get("link"))
            at = keys.index("Edit Table...") + 1 if "Edit Table..." in keys else 0
            out[at:at] = [("Edit Table in New Window", lambda: edit_in_new_window(t), True)]
            out += [("Save Table...", lambda: ask_save_table(doc), True),
                    ("Reload", lambda: dtoptions.reload_link(t.sheet, force=True), linked),
                    ("Delete", lambda: delete_table(doc), True)]
    except Exception as error:
        App.Console.PrintLog("FreeCAD: cmflows.entries: %s\n" % error)
    return out
