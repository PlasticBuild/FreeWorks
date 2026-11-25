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

import hashlib
import json
import os
import re

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

SHEET = "Equations"
META_COMMENT = "FreeWorks:EqComment:"
META_LINK = "FreeWorks:EqLink"
META_ANGLE = "FreeWorks:EqAngleUnits"
META_SOLVE = "FreeWorks:EqAutoSolveOrder"
META_ORDER = "FreeWorks:EqListedOrder"       # Ordered View with Automatic solve order off: the order dragged by hand
META_PENDING = "FreeWorks:EqPending"         # an equation naming a variable not made yet: kept, red, solved once it is
META_LINK_STAMP = "FreeWorks:EqLinkStamp"    # the linked file as last read or written (an edited file is read again)
PARAMS = "User parameter:BaseApp/Preferences/Mod/SolidWorksStyle"


# ---------------------------------------------------------------------- global variables
def is_sheet(obj):
    """The part's Equations folder in the FeatureManager (the sheet that holds the variables)."""
    try:
        return obj is not None and obj.Name == SHEET and obj.TypeId == "Spreadsheet::Sheet"
    except Exception:
        return False


def sheet(doc, create=False):
    s = doc.getObject(SHEET)
    if s is None and create:
        s = doc.addObject("Spreadsheet::Sheet", SHEET)
        s.Label = SHEET
        s.set("A1", "Global Variable")
        s.set("B1", "Value / Equation")
        if App.GuiUp and s.ViewObject is not None:
            s.ViewObject.ShowInTree = True
    return s


def _rows(s):
    """[(row, name, raw)] of the variables (from row 2 down to the first empty name)."""
    out = []
    r = 2
    while True:
        name = s.getContents("A%d" % r) if s is not None else ""
        if not name:
            break
        out.append((r, name.lstrip("'"), s.getContents("B%d" % r)))
        r += 1
    return out


def variables(doc):
    """[(name, value text, evaluated)]"""
    s = sheet(doc)
    if s is None:
        return []
    out = []
    for r, name, raw in _rows(s):
        try:
            got = s.get("B%d" % r)
        except Exception:
            got = None
        text = raw.lstrip("=")
        if _configured(text):
            text = str(got)      # Configure Equation: the value of the configuration shown
        out.append((name, text, got))
    return out


def _configured(text):
    """The variable follows the configuration table (Configure Equation): <table>.Var_<name>."""
    return re.match(r"^[A-Za-z_]\w*\.Var_\w+$", (text or "").strip()) is not None


def _set_configured(doc, raw, text):
    """A configured variable's new value goes in the shown configuration's cell (This configuration)."""
    from . import configmanager as cm, configs
    t = cm.table(doc)
    alias = raw.strip().lstrip("=").split(".", 1)[1]
    if t is None or configs.column_of(t, alias) is None:
        return False
    configs.set_cell(t, alias, text, [t.active()])
    return True


def _alias_ok(name):
    return re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name) is not None


def _solve(doc, s, rebuild):
    """Recompute: the whole part, or only the Equations sheet (Automatically rebuild off: the model waits for Rebuild)."""
    if rebuild or s is None:
        doc.recompute()
    else:
        s.recompute()


def set_variable(doc, name, value, rebuild=True):
    ""


    if not _alias_ok(name):
        raise ValueError("A global variable name starts with a letter and has letters, digits and _ only")
    s = sheet(doc, create=True)
    rows = _rows(s)
    row = next((r for r, n, _raw in rows if n == name), None)
    if row is None:
        row = 2 + len(rows)
        s.set("A%d" % row, name)
    missing = []
    text = to_freecad(doc, str(value), missing=missing)
    raw = s.getContents("B%d" % row)
    if missing:
        if not raw:
            s.set("B%d" % row, "0")
        if s.getAlias("B%d" % row) not in (name, SAFE + name):
            _set_alias(s, row, name)
        _set_pending(doc, name, str(value).strip().lstrip("=").strip())
        _solve(doc, s, rebuild)
        return
    _set_pending(doc, name, None)
    if _configured(raw.lstrip("=")) and _is_number(text) and _set_configured(doc, raw, text):
        doc.recompute()
        return
    broken = "Invalid" in s.State
    if not _is_number(text):
        try:
            s.evalExpression(text)
        except Exception as error:
            if type(error).__name__ == "ParserError" or "parse" in str(error).lower():
                if not raw:
                    s.clear("A%d" % row)                       # a new row that never took
                raise ValueError(_refused(name, error))
    s.set("B%d" % row, text if _is_number(text) else "=" + text)
    if not _is_number(text) and (s.getContents("B%d" % row) or "").startswith("'"):
        s.set("B%d" % row, raw)
        if not raw:
            s.clear("A%d" % row)
        raise ValueError("The equation for \"%s\" was not accepted: there is a syntax error in it" % name)
    if s.getAlias("B%d" % row) not in (name, SAFE + name):
        try:
            _set_alias(s, row, name)
        except ValueError:
            s.clear("A%d" % row)
            s.clear("B%d" % row)
            raise ValueError("%s cannot be a global variable name" % name)
    _solve(doc, s, rebuild)
    loop = _cycle(doc, (s.Name, "B%d" % row))                 # through a dimension: FreeCAD does not flag it
    if ("Invalid" in s.State and not broken) or loop:

        # so one bad entry never stops every other variable from updating
        circular = loop or _circular(s, row) or "cycl" in _status(s).lower()
        status = _status(s)
        s.set("B%d" % row, raw)
        _solve(doc, s, rebuild)
        why = "it refers back to itself (a circular reference)" if circular else \
            (status if status not in ("", "Valid") else "it cannot be solved")
        raise ValueError("The equation for \"%s\" was not accepted: %s" % (name, why))
    retry_pending(doc, rebuild)


def pending(doc):
    ""
    try:
        got = json.loads(dict(doc.Meta).get(META_PENDING, "") or "{}")
        return got if isinstance(got, dict) else {}
    except Exception:
        return {}


def _set_pending(doc, name, text):
    now = pending(doc)
    if text is None and name not in now:
        return
    if text is None:
        now.pop(name, None)
    else:
        now[name] = text
    meta = dict(doc.Meta)
    if now:
        meta[META_PENDING] = json.dumps(now)
    else:
        meta.pop(META_PENDING, None)
    doc.Meta = meta


def missing_names(doc, text, target=None):
    """The quoted names in text that are neither a global variable nor a dimension of the part."""
    out = []
    to_freecad(doc, text, target=target, missing=out)
    return out


_RETRY = []


def retry_pending(doc, rebuild=True):
    """Solves every waiting variable or equation whose names all exist now; returns how many."""
    if _RETRY:
        return 0
    _RETRY.append(1)
    done = 0
    try:
        progress = True
        while progress:
            progress = False
            names = {n for n, _r, _g in variables(doc)}
            for left, right in list(pending(doc).items()):
                if missing_names(doc, right):
                    continue
                try:
                    if left in names:
                        set_variable(doc, left, right, rebuild)
                    else:
                        set_equation(doc, left, right)
                except Exception as _fw_err:
                    _fw_log("equations.py:retry_pending", _fw_err)
                _set_pending(doc, left, None)
                done += 1
                progress = True
    finally:
        _RETRY[:] = []
    if done and rebuild:
        doc.recompute()
    return done


def _status(obj):
    try:
        return obj.getStatusString()
    except Exception:
        return ""


def _circular(s, row):
    """True when the variable's new expression would lead back to itself through other variables."""
    names = {n: (raw or "") for _r, n, raw in _rows(s)}
    me = next((n for r, n, _raw in _rows(s) if r == row), None)
    if me is None:
        return False
    seen, todo = set(), [me]
    while todo:
        n = todo.pop()
        for m in names:
            if m != n and re.search(r"\b%s\b" % re.escape(alias_of(s.Document, m) or m), names.get(n, "")):
                if m == me:
                    return True
                if m not in seen:
                    seen.add(m)
                    todo.append(m)
    return False


_NAMED = re.compile(r"(?:<<([^>]+)>>|(?<![\w.#])([A-Za-z_]\w*))\.([A-Za-z_]\w*(?:\.[A-Za-z_]\w*|\[\d+\])*)")
_SAME = re.compile(r"(?<![\w>\]])\.([A-Za-z_]\w*(?:\.[A-Za-z_]\w*|\[\d+\])*)")
_BARE = re.compile(r"(?<![\w.#<>])([A-Za-z_]\w*)(?![\w(.])")
_CELL = re.compile(r"^[A-Z]{1,2}\d+$")


def _is_sheet(o):
    return getattr(o, "TypeId", "") == "Spreadsheet::Sheet"


def _node_of(o, prop):
    """The graph node for o.prop: a sheet's alias becomes its cell address."""
    if _is_sheet(o):
        cell = prop if _CELL.match(prop) else None
        if cell is None:
            try:
                cell = o.getCellFromAlias(prop.split(".", 1)[0])
            except Exception:
                cell = None
        return (o.Name, cell) if cell else None
    m = re.match(r"^Constraints\[(\d+)\]$", prop)
    if m:                                                     # one sketch dimension, by number or by name
        try:
            named = o.Constraints[int(m.group(1))].Name
            if named:
                prop = "Constraints." + named
        except Exception as _fw_err:
            _fw_log("equations.py:node", _fw_err)
    return (o.Name, prop)


def _refs(doc, owner, expr):
    """What an expression reads: (object name, property or cell) pairs."""
    text = re.sub(r"<<[^>]*>>(?!\.)", " ", expr or "")       # string literals
    found = []
    for m in _NAMED.finditer(text):
        name = m.group(1) or m.group(2)
        o = doc.getObject(name)
        if o is None:
            got = doc.getObjectsByLabel(name)
            o = got[0] if got else None
        if o is not None:
            found.append(_node_of(o, m.group(3)))
    text = _NAMED.sub(" ", text)
    for m in _SAME.finditer(text):
        found.append(_node_of(owner, m.group(1)))
    text = _SAME.sub(" ", text)
    for m in _BARE.finditer(text):
        word = m.group(1)
        if _is_sheet(owner):
            found.append(_node_of(owner, word))
        elif word in getattr(owner, "PropertiesList", ()):
            found.append((owner.Name, word))
    return [n for n in found if n]


def _graph(doc):
    """Every equation in the part, as node -> the nodes it reads (dimensions, sheet cells)."""
    g = {}
    for o in doc.Objects:
        if _is_sheet(o):
            try:
                cells = o.getUsedCells()
            except Exception:
                cells = []
            for c in cells:
                raw = o.getContents(c) or ""
                if raw.startswith("="):
                    g[(o.Name, c)] = _refs(doc, o, raw[1:])
        else:
            try:
                engine = o.ExpressionEngine
            except Exception:
                continue
            for path, expr in engine:
                g[(o.Name, path.lstrip("."))] = _refs(doc, o, expr)
    return g


def _same(a, b):
    if a[0] != b[0]:
        return False
    x, y = a[1], b[1]
    return x == y or x.startswith(y + ".") or y.startswith(x + ".")


def _cycle(doc, start):
    ""
    g = _graph(doc)
    keys = list(g)
    seen, todo = set(), [k for k in keys if _same(k, start)]
    while todo:
        k = todo.pop()
        if k in seen:
            continue
        seen.add(k)
        for r in g.get(k, ()):
            if _same(r, start):
                return True
            todo.extend(n for n in keys if n not in seen and _same(n, r))
    return False


def _refused(name, error):
    ""
    text = str(error)
    m = re.search(r"Property '([^']+)' not found", text) or re.search(r"[Ii]dentifier '?([^' ]+)'? not found", text)
    if m:
        why = "\"%s\" is not a global variable, dimension or function" % m.group(1)
    elif "parse" in text.lower() or type(error).__name__ == "ParserError":
        why = "there is a syntax error in it"
    else:
        why = text or "it cannot be solved"
    return "The equation for \"%s\" was not accepted: %s" % (name, why)


def accept_expression(doc, obj, path, expr, name):
    ""

    if not expr:
        obj.setExpression(path, None)
        return
    try:
        obj.evalExpression(expr)
    except Exception as error:
        raise ValueError(_refused(name, error))
    old = next((e for p, e in obj.ExpressionEngine if p.lstrip(".") == path.lstrip(".")), None)
    try:
        obj.setExpression(path, expr)
    except Exception as error:
        if "cycl" not in str(error).lower():
            raise ValueError(_refused(name, error))
        obj.setExpression(path, old)
        raise ValueError("The equation for \"%s\" was not accepted: it refers back to itself (a circular reference)" % name)
    if _cycle(doc, (obj.Name, path.lstrip("."))):
        obj.setExpression(path, old)
        raise ValueError("The equation for \"%s\" was not accepted: it refers back to itself (a circular reference)" % name)

def shown_value(got):
    """A global variable's Evaluates to: a length or angle in the part's units (2in in an inch part)."""
    if hasattr(got, "UserString"):
        try:
            return got.UserString
        except Exception as _fw_err:
            _fw_log("equations.py:shown", _fw_err)
    if isinstance(got, float):
        return "%g" % got
    return got


def _var_error(got):
    """A global variable's value that is an error, as text ("" when it has a value)."""
    if got is None:
        return "this variable has no value"
    if isinstance(got, str) and got.startswith("ERR"):
        return got.split("\n")[0]
    return ""


def broken(obj):
    ""
    try:
        if "Invalid" in obj.State:
            return _status(obj) or "this equation cannot be solved"
    except Exception as _fw_err:
        _fw_log("equations.py:broken", _fw_err)
    return ""


SAFE = "gv_"     # a name FreeCAD reads as a unit or function (W, m, s, sin) is kept as gv_<name>


def _set_alias(s, row, name):
    ""

    try:
        s.setAlias("B%d" % row, name)
    except ValueError:
        s.setAlias("B%d" % row, SAFE + name)


def alias_of(doc, name):
    """The sheet alias of global variable name (name, or gv_name)."""
    s = sheet(doc)
    for r, n, _raw in _rows(s) if s is not None else []:
        if n == name:
            return s.getAlias("B%d" % r) or name
    return name


def rename_variable(doc, old, new):
    ""

    new = new.strip().strip('"')
    if new == old:
        return False
    if not _alias_ok(new):
        raise ValueError("A global variable name starts with a letter and has letters, digits and _ only")
    if any(n == new for n, _v, _e in variables(doc)):
        raise ValueError("There is already a global variable called %s" % new)
    s = sheet(doc)
    row = next((r for r, n, _raw in (_rows(s) if s is not None else []) if n == old), None)
    if row is None:
        raise ValueError("No global variable called %s" % old)
    was = s.getAlias("B%d" % row) or old
    s.set("A%d" % row, new)
    _set_alias(s, row, new)
    now = s.getAlias("B%d" % row) or new
    pattern = re.compile(r"(\b%s\.)%s\b" % (re.escape(SHEET), re.escape(was)))
    for o in doc.Objects:
        for path, expr in list(getattr(o, "ExpressionEngine", []) or []):
            if pattern.search(expr or ""):
                o.setExpression(path, pattern.sub(lambda m: m.group(1) + now, expr))
    if s is not None:
        for r, _n, raw in _rows(s):
            if raw.startswith("=") and re.search(r"\b%s\b" % re.escape(was), raw) and r != row:
                s.set("B%d" % r, re.sub(r"\b%s\b" % re.escape(was), now, raw))
    doc.recompute()
    return True


def delete_variable(doc, name):
    """Takes a global variable off. The rows under it move up; every equation keeps the names it was written
    with (FreeCAD turns a reference to a cleared name into a cell address, which after the move would point
    at another variable), so one that used the deleted variable still names it and shows as broken."""
    _set_pending(doc, name, None)
    s = sheet(doc)
    if s is None:
        return
    rows = _rows(s)
    keep = [(n, raw) for _r, n, raw in rows if n != name]
    written = []
    for o in doc.Objects:
        if o is s:
            continue
        for path, expr in list(getattr(o, "ExpressionEngine", []) or []):
            if (SHEET + ".") in (expr or ""):
                written.append((o, path, expr))
    for r, _n, _raw in rows:
        s.setAlias("B%d" % r, "")
        s.clear("A%d" % r)
        s.clear("B%d" % r)
    for i, (n, raw) in enumerate(keep):
        r = 2 + i
        s.set("A%d" % r, n)
        _set_alias(s, r, n)
    for i, (n, raw) in enumerate(keep):
        s.set("B%d" % (2 + i), raw)
    for o, path, expr in written:
        try:
            o.setExpression(path, expr)
        except Exception as _fw_err:
            _fw_log("equations.py:delete_variable", _fw_err)
    doc.recompute()
    if park_broken(doc):          # an equation that used it stays, in red, and its dimension keeps its value
        doc.recompute()


def _is_number(text):
    try:
        float(str(text).strip())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------- names
def _by_label(doc, label):
    hits = doc.getObjectsByLabel(label)
    return hits[0] if hits else doc.getObject(label)


def _dim_name(n, cname):
    ""

    if cname and not re.match(r"^D\d+$", cname):
        return cname
    return "D%d" % n


def _sketch_dims(sk):
    ""
    out = []
    for i, c in enumerate(sk.Constraints):
        if c.Type in ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle"):
            out.append((i, c.Name))
    return out


FEATURE_DIMS = {"PartDesign::Pad": ("Length", "Length2"), "PartDesign::Pocket": ("Length", "Length2"),
                "PartDesign::Revolution": ("Angle",), "PartDesign::Groove": ("Angle",),
                "PartDesign::Fillet": ("Radius",), "PartDesign::Chamfer": ("Size", "Size2"),
                "PartDesign::Thickness": ("Value",), "PartDesign::Hole": ("Diameter", "Depth"),
                "PartDesign::LinearPattern": ("Length", "Occurrences"),
                "PartDesign::PolarPattern": ("Angle", "Occurrences"), "PartDesign::Draft": ("Angle",)}


def dimension_path(doc, name):
    """(object, property path) for "D1@Sketch1", "Length@Pad", "Pad.Length" or "Sketch.Constraints.Width"."""
    name = name.strip().strip('"')
    if "@" in name:
        dim, label = name.split("@", 1)
        obj = _by_label(doc, label)
        if obj is None:
            return None
        if obj.isDerivedFrom("Sketcher::SketchObject"):
            dims = _sketch_dims(obj)
            m = re.match(r"^D(\d+)$", dim)
            if m and 0 < int(m.group(1)) <= len(dims):
                i, cname = dims[int(m.group(1)) - 1]
                return obj, (".Constraints.%s" % cname) if cname else (".Constraints[%d]" % i)
            if any(n == dim for _i, n in dims):
                return obj, ".Constraints.%s" % dim
            return None
        props = FEATURE_DIMS.get(obj.TypeId, ())
        m = re.match(r"^D(\d+)$", dim)
        if m and 0 < int(m.group(1)) <= len(props):
            return obj, props[int(m.group(1)) - 1]
        return (obj, dim) if dim in obj.PropertiesList else None
    if "." in name:
        head, prop = name.split(".", 1)
        obj = _by_label(doc, head)
        if obj is None:
            return None
        return obj, ("." + prop) if prop.startswith("Constraints") else prop
    obj = _by_label(doc, name)
    return (obj, "Suppressed") if obj is not None and "Suppressed" in obj.PropertiesList else None


def sw_name(obj, path):
    ""
    p = path.lstrip(".")
    if p == "Suppressed":
        return obj.Label
    if obj.isDerivedFrom("Sketcher::SketchObject") and p.startswith("Constraints"):
        dims = _sketch_dims(obj)
        m = re.match(r"^Constraints(?:\.(\w+)|\[(\d+)\])$", p)
        if m:
            for n, (i, cname) in enumerate(dims, 1):
                if (m.group(1) and cname == m.group(1)) or (m.group(2) and i == int(m.group(2))):
                    return "%s@%s" % (_dim_name(n, cname), obj.Label)
    props = FEATURE_DIMS.get(obj.TypeId, ())
    if p in props:
        return "D%d@%s" % (props.index(p) + 1, obj.Label)
    return "%s@%s" % (p, obj.Label)


# ---------------------------------------------------------------------- File Properties and Measure
FILE_PROPERTIES = ("SW-Mass", "SW-Density", "SW-Volume", "SW-SurfaceArea",
                   "SW-CenterofMassX", "SW-CenterofMassY", "SW-CenterofMassZ")
MEASURE = "Measure..."


def _measured_body(doc):
    for o in doc.Objects:
        if o.TypeId == "PartDesign::Body":
            return o
    for o in doc.Objects:
        if o.TypeId.startswith("Part::") and not o.InList and getattr(o, "Shape", None) is not None:
            return o
    return None


def file_property(doc, name):
    ""

    body = _measured_body(doc)
    if body is None:
        return None
    b = "<<%s>>.Shape" % body.Label
    density = "1000"
    try:
        from . import material
        row = material.row(doc)
        if row is not None and float(row.Density or 0) > 0:
            density = "<<%s>>.Density" % row.Label
    except Exception as _fw_err:
        _fw_log("equations.py:297", _fw_err)
    return {"SW-Volume": "%s.Volume" % b, "SW-SurfaceArea": "%s.Area" % b,
            "SW-Mass": "(%s.Volume * %s * 1e-6)" % (b, density), "SW-Density": "(%s * 1e-6)" % density,
            "SW-CenterofMassX": "%s.CenterOfMass.x" % b, "SW-CenterofMassY": "%s.CenterOfMass.y" % b,
            "SW-CenterofMassZ": "%s.CenterOfMass.z" % b}.get(name)


def measure_selection():
    ""

    import FreeCADGui as Gui
    subs = [shp for sel in Gui.Selection.getSelectionEx() for shp in (sel.SubObjects or [getattr(sel.Object, "Shape", None)])
            if shp is not None]
    k = _doc_length(App.ActiveDocument)[1]       # in the part's unit, as every number of an equation
    if len(subs) >= 2:
        return round(subs[0].distToShape(subs[1])[0] / k, 6)
    if len(subs) == 1 and subs[0].ShapeType == "Edge":
        e = subs[0]
        if type(e.Curve).__name__ == "Circle":
            return round(2 * e.Curve.Radius / k, 6)
        return round(e.Length / k, 6)
    return None


# ---------------------------------------------------------------------- angular equation units
TRIG = ("sin", "cos", "tan")
ARC = ("asin", "acos", "atan", "atan2")


def angle_units(doc):
    """Equations box > Angular equation units: "Degrees" (FreeCAD's own) or "Radians"."""
    try:
        return dict(doc.Meta).get(META_ANGLE, "Degrees")
    except Exception as _fw_err:
        _fw_log("equations.py:362", _fw_err)
        return "Degrees"


def _calls(text, names):
    """[(start, open paren, close paren, name)] of each call of one of names, outermost first."""
    out = []
    for m in re.finditer(r"\b(%s)\s*\(" % "|".join(sorted(names, key=len, reverse=True)), text):
        depth, i = 0, m.end() - 1
        for j in range(i, len(text)):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    out.append((m.start(), i, j, m.group(1)))
                    break
    return out


def _radians_in(text):
    ""
    calls = _calls(text, TRIG + ARC)
    if not calls:
        return text
    s, i, j, name = calls[0]
    inner = _radians_in(text[i + 1:j])
    rest = _radians_in(text[j + 1:])
    if name in TRIG:
        return text[:s] + "%s((%s) * 1 rad)" % (name, inner) + rest
    return text[:s] + "(%s(%s) / 1 rad)" % (name, inner) + rest


def _closes(text, i):
    """The index of the paren that closes text[i]."""
    depth = 0
    for j in range(i, len(text)):
        depth += {"(": 1, ")": -1}.get(text[j], 0)
        if depth == 0:
            return j
    return -1


def _radians_out(text):
    ""
    changed = True
    while changed:
        changed = False
        for s, i, j, name in _calls(text, TRIG + ARC):
            if name in TRIG:
                inner = text[i + 1:j]
                m = re.match(r"^(.*?)\s*\*\s*1\s*rad$", inner, flags=re.S)
                if m:
                    arg = m.group(1).strip()
                    if arg.startswith("(") and _closes(arg, 0) == len(arg) - 1:
                        arg = arg[1:-1]
                    text = text[:i + 1] + arg + text[j:]
                    changed = True
                    break
            else:
                m = re.match(r"^\s*/\s*1\s*rad", text[j + 1:])
                if m:
                    end = j + 1 + m.end()
                    if s > 0 and text[s - 1] == "(" and text[end:end + 1] == ")":
                        text = text[:s - 1] + text[s:j + 1] + text[end + 1:]
                    else:
                        text = text[:s] + text[s:j + 1] + text[end:]
                    changed = True
                    break
    return text


def convert_angles(doc, old, new):
    ""
    if old == new:
        return 0
    n = 0
    for o, path, expr in equations(doc):
        sw = to_sw(doc, expr, old, owner=o)
        fc = to_freecad(doc, sw, new, target=(o, path))
        if fc != expr:
            try:
                o.setExpression(path, fc)
                n += 1
            except Exception as error:
                App.Console.PrintWarning("FreeCAD equations: %s %s: %s\n" % (o.Label, path, error))
    s = sheet(doc)
    if s is not None:
        for r, _name, raw in _rows(s):
            if raw.startswith("=") and not _configured(raw[1:]):
                fc = to_freecad(doc, to_sw(doc, raw[1:], old), new)
                if fc != raw[1:]:
                    s.set("B%d" % r, "=" + fc)
                    n += 1
    return n



SW_FUNCTIONS = {
    "sqr": "sqrt(%s)", "atn": "atan(%s)", "arcsin": "asin(%s)", "arccos": "acos(%s)", "int": "trunc(%s)",
    "sgn": "((%s) > 0 ? 1 : ((%s) < 0 ? -1 : 0))", "sec": "(1 / cos(%s))", "cosec": "(1 / sin(%s))",
    "cotan": "(1 / tan(%s))", "arcsec": "acos(1 / (%s))", "arccosec": "asin(1 / (%s))",
    "arccotan": "atan(1 / (%s))",
}


def _split_args(text):
    """Top-level arguments of a call, split at ; or , outside brackets."""
    out, depth, start = [], 0, 0
    for k, ch in enumerate(text):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch in ";," and depth == 0:
            out.append(text[start:k].strip())
            start = k + 1
    out.append(text[start:].strip())
    return out


def _split_word(text, word):
    """text split at the word (any case) outside brackets and <<labels>>."""
    out, depth, start, k = [], 0, 0, 0
    pat = re.compile(r"(?<![\w.])%s(?![\w.])" % word, re.I)
    while k < len(text):
        if text.startswith("<<", k):
            end = text.find(">>", k)
            k = len(text) if end < 0 else end + 2
            continue
        ch = text[k]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif depth == 0:
            m = pat.match(text, k)
            if m:
                out.append(text[start:k])
                start = k = m.end()
                continue
        k += 1
    out.append(text[start:])
    return out


def _logic(text):
    ""


    ors = _split_word(text, "or")
    if len(ors) > 1:
        out = "0"
        for part in reversed(ors):
            out = "(%s ? 1 : %s)" % (_logic(part.strip()), out)
        return out
    ands = _split_word(text, "and")
    if len(ands) > 1:
        out = "1"
        for part in reversed(ands):
            out = "(%s ? %s : 0)" % (_logic(part.strip()), out)
        return out
    m = re.match(r"\s*not(?![\w.])\s*(.*)$", text, re.I | re.S)
    if m:
        return "(%s ? 0 : 1)" % _logic(m.group(1))
    t = text.strip()
    if t.startswith("(") and t.endswith(")") and _closes(t, 0) == len(t) - 1:
        return "(%s)" % _logic(t[1:-1])
    return text


def _sw_functions(text):
    ""

    calls = _calls(text, ["iif"] + list(SW_FUNCTIONS))
    if not calls:
        return text
    s, i, j, name = calls[0]
    inner = _sw_functions(text[i + 1:j])
    rest = _sw_functions(text[j + 1:])
    if name == "iif":
        args = _split_args(inner)
        if len(args) != 3:
            return text[:j + 1] + rest
        return text[:s] + "(%s ? %s : %s)" % (_logic(args[0]), args[1], args[2]) + rest
    form = SW_FUNCTIONS[name]
    return text[:s] + form.replace("%s", inner) + rest


def _doc_length(doc):
    ""
    try:
        from . import unitspage
        sym, k = unitspage.length_unit(doc)
        return sym, float(k)
    except Exception:
        return "mm", 1.0


def _quantity_kind(v):
    """"len" for a length, "deg" for an angle, else None."""
    u = getattr(v, "Unit", None)
    if u is None:
        return None
    try:
        if u == App.Units.Length:
            return "len"
        if u == App.Units.Angle:
            return "deg"
    except Exception as _fw_err:
        _fw_log("equations.py:kind", _fw_err)
    return None


def _kind(obj, path):
    """What a dimension holds: "len", "deg" or None (a count, a suppression)."""
    p = path.lstrip(".")
    try:
        if p.startswith("Constraints"):
            m = re.match(r"^Constraints(?:\.(\w+)|\[(\d+)\])$", p)
            c = obj.Constraints[int(m.group(2))] if m.group(2) else next(c for c in obj.Constraints if c.Name == m.group(1))
            if c.Type == "Angle":
                return "deg"
            return "len" if c.Type in ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter") else None
        return _quantity_kind(obj.getPropertyByName(p))
    except Exception:
        return None


def _variable_kind(doc, name):
    try:
        s = sheet(doc)
        row = next((r for r, n, _raw in _rows(s) if n == name), None)
        return _quantity_kind(s.get("B%d" % row)) if row is not None else None
    except Exception:
        return None


def _in_doc_units(ref, kind, sym):
    ""
    if kind == "len":
        return "(%s / 1 %s)" % (ref, sym)
    if kind == "deg":
        return "(%s / 1 deg)" % ref
    return ref


def to_freecad(doc, text, units=None, target=None, missing=None):
    ""





    sym, _k = _doc_length(doc)
    out = _lengths_in(text.strip().lstrip("="), sym)
    sole = _SOLE.fullmatch(out) is not None
    out = re.sub(r'\$PRP:"([^"]+)"', lambda m: file_property(doc, m.group(1)) or m.group(0), out)
    out = _lower_functions(out)
    out = re.sub(r'"suppressed"', "1", out, flags=re.I)
    out = re.sub(r'"unsuppressed"', "0", out, flags=re.I)

    def ref(m):
        name = m.group(1)
        if "@" in name or "." in name:
            got = dimension_path(doc, name)
            if got is not None:
                obj, path = got
                if target is not None and obj is target[0]:
                    r = "." + path.lstrip(".")          # FreeCAD: a sketch names its own dimensions from inside
                else:
                    r = "<<%s>>%s%s" % (obj.Label, "" if path.startswith(".") else ".", path)
                return _in_doc_units(r, _kind(obj, path), sym)
        if any(n == name for n, _v, _e in variables(doc)):
            return _in_doc_units("%s.%s" % (SHEET, alias_of(doc, name)), _variable_kind(doc, name), sym)
        if missing is not None:
            missing.append(name)             # not made yet (else FreeCAD would read V2 as a cell address)
        return name
    out = re.sub(r'"([^"]+)"', ref, out)
    # IIF(), and IF() as people type it, with ; or , between the arguments
    out = _sw_functions(re.sub(r"\bi?if\s*\(", "iif(", out, flags=re.I))
    if (units or angle_units(doc)) == "Radians":
        out = _radians_in(out)
    else:
        out = _degrees_in(out)
    if target is not None and not sole and _kind(*target) == "len" and out.strip():
        out = "(%s) * 1 %s" % (out, sym)        # the plain number it gives, in the part's unit
    return out


LENGTH_UNITS = ("mm", "cm", "dm", "m", "um", "in", "ft", "yd", "mil", "thou")
_UNITS = "|".join(sorted(LENGTH_UNITS, key=len, reverse=True))
_NUM = r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_LENGTH = re.compile(r"(?<![\w.])(\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?\s*(%s)\b" % _UNITS)
_LENGTH_FC = re.compile(r"\(\s*(%s)\s*(%s)\s*/\s*1\s*(?:%s)\s*\)" % (_NUM, _UNITS, _UNITS))
_SOLE = re.compile(r"\s*%s\s*(?:%s)\s*" % (_NUM, _UNITS))


FUNCTIONS = ("sin", "cos", "tan", "asin", "acos", "atan", "atan2", "abs", "exp", "log", "log10", "sqrt",
             "pow", "round", "trunc", "ceil", "floor", "mod", "min", "max", "sinh", "cosh", "tanh", "hypot",
             "iif", "if") + tuple(SW_FUNCTIONS)
_FUNCTION = re.compile(r"\b(%s)(?=\s*\()" % "|".join(sorted(FUNCTIONS, key=len, reverse=True)), re.I)


def _lower_functions(text):
    ""

    parts = re.split(r'(<<[^>]*>>|"[^"]*")', text)
    for k in range(0, len(parts), 2):
        t = _FUNCTION.sub(lambda m: m.group(1).lower(), parts[k])
        t = re.sub(r"(?<![\w.])pi(?![\w.(])", "pi", t, flags=re.I)
        t = t.replace("<>", "!=")
        parts[k] = re.sub(r"(?<![<>=!])=(?!=)", "==", t)
    return "".join(parts)


def _lengths_in(text, sym="mm"):
    ""



    if not _LENGTH.search(text):
        return text
    if "?" not in text and _SOLE.fullmatch(text):
        return text.strip()                 # a plain "1in": FreeCAD's own form
    parts = re.split(r'(<<[^>]*>>|"[^"]*")', text)
    for k in range(0, len(parts), 2):
        if _LENGTH_FC.search(parts[k]) or _LENGTH_FC_BARE.search(parts[k]):
            continue
        parts[k] = _LENGTH.sub(lambda m: "(%s%s / 1%s)" % (m.group(0)[:-len(m.group(2))].strip(), m.group(2), sym), parts[k])
    return "".join(parts)


_LENGTH_FC_BARE = re.compile(r"(%s)\s*(%s)\s*/\s*1\s*(?:%s)\b" % (_NUM, _UNITS, _UNITS))
_REF = r"(?:<<[^>]+>>|\b[A-Za-z_]\w*)\.(?:Constraints(?:\.\w+|\[\d+\])|\w+)|(?<![\w>\]])\.Constraints(?:\.\w+|\[\d+\])"
_REF_WRAP = re.compile(r"\(\s*(%s)\s*/\s*1\s*(?:%s|deg)\s*\)" % (_REF, _UNITS))
_REF_BARE = re.compile(r"(%s)\s*/\s*1\s*(?:%s|deg)\b" % (_REF, _UNITS))


def _lengths_out(text):
    ""
    text = _LENGTH_FC.sub(lambda m: "%s%s" % (m.group(1), m.group(2)), text)
    text = _LENGTH_FC_BARE.sub(lambda m: "%s%s" % (m.group(1), m.group(2)), text)
    return re.sub(r"(?<![\w.])(%s)\s+(%s)\b(?!\s*/)" % (_NUM, _UNITS), r"\1\2", text)     # 2 in -> 2in


def _low_ops(text):
    """True when text has an operator at its top level that binds looser than * (+ - ? : < > = ! & |)."""
    text = re.sub(r"<<[^>]*>>", "L", text)      # an object's <<label>> is no comparison
    depth, quoted, prev = 0, False, ""
    for k, c in enumerate(text):
        if c == '"':
            quoted = not quoted
        elif quoted:
            pass
        elif c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif depth == 0 and c in "+-":
            unary = prev in ("", "(", "*", "/", "^", "+", "-", "?", ":", ";", ",", "<", ">", "=")
            exponent = prev in ("e", "E") and k >= 2 and text[k - 2].isdigit()
            if not unary and not exponent:
                return True
        elif depth == 0 and c in "?:<>=!&|":
            return True
        if not c.isspace():
            prev = c
    return False


def _units_out(expr, sym=None):
    """Takes off what to_freecad wrote to keep the part's units: (...) * 1 in around the whole, and
    (<<Sketch1>>.Constraints[4] / 1 in) around a dimension or a variable. Only the part's own unit (sym) is taken
    off: an equation written while the part was in another unit keeps that unit in sight ("D1@Sketch1" / 1in + 1)
    * 1in, so the box never shows one thing while the part does another, and the text reads back the same."""
    units = re.escape(sym) if sym else _UNITS
    t = expr.strip()
    m = re.match(r"^(.*\S)\s*\*\s*1\s*(?:%s)$" % units, t, flags=re.S)
    if m:
        inner = m.group(1).strip()
        if inner.startswith("(") and _closes(inner, 0) == len(inner) - 1:
            t = inner[1:-1].strip()
        elif not _low_ops(inner):
            t = inner
    elif sym:
        m = re.match(r"^\(?\s*(%s)\s*\)?\s*\*\s*1\s*(%s)$" % (_NUM, _UNITS), t)
        if m:
            t = "%s %s" % (m.group(1), m.group(2))          # a plain number kept in another unit: 2 in
    if sym:
        t = re.sub(r"\(\s*(%s)\s*/\s*1\s*(?:%s|deg)\s*\)" % (_REF, units), r"\1", t)
        return re.sub(r"(%s)\s*/\s*1\s*(?:%s|deg)\b" % (_REF, units), r"\1", t)
    t = _REF_WRAP.sub(r"\1", t)
    return _REF_BARE.sub(r"\1", t)


def _reciprocal_at(text, s):
    """Where a 1 / just before text[s] starts (a 1 / cos(x) that is sec(x)), or -1."""
    m = re.search(r"1\s*/\s*$", text[:s])
    if not m:
        return -1
    k = m.start()
    before = text[:k].rstrip()
    if before and before[-1] not in "(+-*,;?:<>=!&|":
        return -1
    return k


def _functions_out(text):
    ""

    changed = True
    while changed:
        changed = False
        for s, i, j, name in _calls(text, ["cos", "sin", "tan"]):
            k = _reciprocal_at(text, s)
            if k >= 0:
                sw = {"cos": "sec", "sin": "cosec", "tan": "cotan"}[name]
                text = text[:k] + sw + text[i:j + 1] + text[j + 1:]
                changed = True
                break
        if changed:
            continue
        for s, i, j, name in _calls(text, ["acos", "asin", "atan"]):
            m = re.match(r"^\s*1\s*/\s*(.+?)\s*$", text[i + 1:j], flags=re.S)
            if not m:
                continue
            arg = m.group(1)
            if arg.startswith("(") and _closes(arg, 0) == len(arg) - 1:
                arg = arg[1:-1].strip()
            elif _low_ops(arg) or re.search(r"[*/^]", arg):
                continue
            sw = {"acos": "arcsec", "asin": "arccosec", "atan": "arccotan"}[name]
            text = text[:s] + "%s(%s)" % (sw, arg) + text[j + 1:]
            changed = True
            break
    for fc, sw in (("sqrt", "sqr"), ("atan", "atn"), ("asin", "arcsin"), ("acos", "arccos"), ("trunc", "int")):
        text = re.sub(r"\b%s\s*\(" % fc, sw + "(", text)
    return re.sub(r"iif\(([^;]+?) > 0; 1; iif\(\1 < 0; -1; 0\)\)", r"sgn(\1)", text)


def _degrees_in(text):
    ""

    calls = _calls(text, ARC)
    if not calls:
        return text
    s, i, j, name = calls[0]
    if re.match(r"^\s*/\s*1\s*deg", text[j + 1:]):
        return text[:j + 1] + _degrees_in(text[j + 1:])      # already in this form
    inner = _degrees_in(text[i + 1:j])
    rest = _degrees_in(text[j + 1:])
    return text[:s] + "(%s(%s) / 1 deg)" % (name, inner) + rest


def _degrees_out(text):
    ""
    changed = True
    while changed:
        changed = False
        for s, i, j, name in _calls(text, ARC):
            m = re.match(r"^\s*/\s*1\s*deg", text[j + 1:])
            if m:
                end = j + 1 + m.end()
                if s > 0 and text[s - 1] == "(" and text[end:end + 1] == ")":
                    text = text[:s - 1] + text[s:j + 1] + text[end + 1:]
                else:
                    text = text[:s] + text[s:j + 1] + text[end:]
                changed = True
                break
    return text


def to_sw(doc, expr, units=None, owner=None):
    ""

    sym = _doc_length(doc)[0]
    expr = _units_out(expr, sym)
    for name in FILE_PROPERTIES:
        fc = file_property(doc, name)
        if not fc:
            continue
        bare = fc[1:-1] if fc.startswith("(") else fc
        for form in (fc, bare, fc.replace("1e-6", "1e-06"), bare.replace("1e-6", "1e-06")):
            if form in expr:
                expr = expr.replace(form, '$PRP:"%s"' % name)
                break
    out = re.sub(r"\b%s\.(\w+)" % SHEET,
                 lambda m: '"%s"' % (m.group(1)[len(SAFE):] if m.group(1).startswith(SAFE) else m.group(1)), expr)
    # inside the Equations sheet a variable names another by its bare alias (Depth = Width / 4):

    try:
        names = [n for _r, n, _raw in _rows(sheet(doc))]
    except Exception:
        names = []
    for name in sorted(names, key=len, reverse=True):
        out = re.sub(r'(?<![\w".<@$])(?:%s)?%s(?![\w"@.>(])' % (SAFE, re.escape(name)), '"%s"' % name, out)

    def ref(m):
        label, path = m.group(1), m.group(2)
        obj = _by_label(doc, label)
        return '"%s"' % sw_name(obj, path) if obj is not None else m.group(0)
    out = re.sub(r"<<([^>]+)>>(\.Constraints(?:\.\w+|\[\d+\])|\.\w+)", ref, out)

    def bare(m):                            # Sketch001.Constraints[2]: FreeCAD writes a label that is the name bare
        obj = doc.getObject(m.group(1))
        return '"%s"' % sw_name(obj, m.group(2)) if obj is not None else m.group(0)
    out = re.sub(r'(?<![\w".<@$>])([A-Za-z_]\w*)(\.Constraints(?:\.\w+|\[\d+\]))', bare, out)
    if owner is not None:
        out = re.sub(r'(?<![\w".>\]])(\.Constraints(?:\.\w+|\[\d+\]))', lambda m: '"%s"' % sw_name(owner, m.group(1)), out)
    # a variable named inside the Equations sheet (Gap = Wall / 1 in + 1): its number in the part's unit, shown bare
    out = re.sub(r'\(\s*("[^"]+")\s*/\s*1\s*(?:%s|deg)\s*\)' % re.escape(sym), r"\1", out)
    out = re.sub(r'("[^"]+")\s*/\s*1\s*(?:%s|deg)\b' % re.escape(sym), r"\1", out)
    out = _lengths_out(_degrees_out(out))
    m = re.match(r"^\(?\s*(.+?)\s*\?\s*1\s*:\s*0\s*\)?$", out)
    if m:
        out = 'iif(%s; "suppressed"; "unsuppressed")' % m.group(1)
    else:
        out = _ternary_out(out)
    out = _quote_variables(doc, out)
    if (units or angle_units(doc)) == "Radians":
        out = _radians_out(out)
    return _functions_out(out)


def _top_level(text, ch):
    depth, quoted = 0, False
    for k, c in enumerate(text):
        if c == '"':
            quoted = not quoted
        elif quoted:
            continue
        elif c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == ch and depth == 0:
            return k
    return -1


def _ternary_out(text):
    t = text.strip()
    while t.startswith("(") and t.endswith(")") and _top_level(t[1:-1], ")") == -1 and \
            _balanced(t[1:-1]) and _top_level(t[1:-1], "?") != -1:
        t = t[1:-1].strip()
    q = _top_level(t, "?")
    if q < 0:
        return _groups_out(text)
    rest = t[q + 1:]
    depth, nest, c_at, quoted = 0, 0, -1, False      # the ':' that closes this '?' (nested ones counted)
    for k, c in enumerate(rest):
        if c == '"':
            quoted = not quoted
        elif quoted:
            continue
        elif c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif depth == 0 and c == "?":
            nest += 1
        elif depth == 0 and c == ":":
            if nest == 0:
                c_at = k
                break
            nest -= 1
    if c_at < 0:
        return text
    a, b, c = t[:q].strip(), rest[:c_at].strip(), rest[c_at + 1:].strip()
    return "iif(%s; %s; %s)" % (a, _ternary_out(b), _ternary_out(c))


def _groups_out(text):
    """A ? b : c in brackets inside a longer expression: (a ? b : c) + 1 -> iif(a; b; c) + 1."""
    out, k = [], 0
    while k < len(text):
        c = text[k]
        if c == "(":
            depth, j = 0, k
            for j in range(k, len(text)):
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
            inner = text[k + 1:j]
            grouping = not (k > 0 and (text[k - 1].isalnum() or text[k - 1] == "_"))
            if depth == 0 and grouping and _top_level(inner, "?") != -1:
                out.append(_ternary_out(inner))
            elif depth == 0:
                out.append("(" + _groups_out(inner) + ")")
            else:
                out.append(text[k:])
                break
            k = j + 1
            continue
        out.append(c)
        k += 1
    return "".join(out)


def _balanced(text):
    depth = 0
    for c in text:
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _quote_variables(doc, text):
    ""

    try:
        names = {alias_of(doc, n): n for n, _r, _v in variables(doc)}
    except Exception:
        return text
    if not names:
        return text
    pat = re.compile(r"(?<![\w.<\"$])(%s)\b(?!\s*\()" % "|".join(re.escape(a) for a in sorted(names, key=len, reverse=True)))
    parts = re.split(r'("[^"]*")', text)
    for k in range(0, len(parts), 2):
        parts[k] = pat.sub(lambda m: '"%s"' % names[m.group(1)], parts[k])
    return "".join(parts)


# ---------------------------------------------------------------------- equations
def equations(doc):
    """[(object, path, expression)] of every expression in the part (not the Equations sheet's own)."""
    out = []
    for o in doc.Objects:
        if o.Name == SHEET:
            continue
        for path, expr in getattr(o, "ExpressionEngine", []) or []:
            if path.startswith(".cells") or path.startswith(".Configuration"):
                continue
            out.append((o, path, expr))
    return out


def _names_itself(doc, left, right, obj, path):
    """True when the equation's right side names the dimension it drives ("D1@Boss-Extrude1" = "D1@Boss-Extrude1" + 1)."""
    for quoted in re.findall(r'"([^"]+)"', right or ""):
        try:
            got = dimension_path(doc, quoted.strip())
        except Exception:
            got = None
        if got is not None and got[0] is obj and got[1].lstrip(".") == path.lstrip("."):
            return True
    return False


def set_equation(doc, left, right):
    got = dimension_path(doc, left)
    if got is None:
        raise ValueError("No dimension called %s" % left)
    obj, path = got
    if right.strip() and _names_itself(doc, left, right, obj, path):

        raise ValueError("The equation for \"%s\" was not accepted: it refers back to itself (a circular reference)" % left)
    if right.strip() and missing_names(doc, right, target=(obj, path)):
        _set_pending(doc, left, right.strip().lstrip("=").strip())
        return obj, path
    _set_pending(doc, left, None)

    # or a syntax error) and the old equation stays
    accept_expression(doc, obj, path, to_freecad(doc, right, target=(obj, path)) if right.strip() else None, left)
    return obj, path


_GONE = ("No attribute named", "not found", "Unknown", "Invalid object", "no such", "Cannot find")


def park_broken(doc):
    ""



    done = 0
    for obj, path, expr in list(equations(doc)):
        try:
            obj.evalExpression(expr)
            continue
        except Exception as error:
            if not any(k.lower() in str(error).lower() for k in _GONE):
                continue
        try:
            left = sw_name(obj, path)
            text = to_sw(doc, expr, owner=obj)
            text = re.sub(r'"Constraints\.([^"@]+)@', r'"\1@', text or "")
            if not missing_names(doc, text or ""):
                continue            # its names are all there (one of them is in error itself): left as it is
            _set_pending(doc, left, (text or expr).strip().lstrip("=").strip())
            obj.setExpression(path, None)
            done += 1
        except Exception as _fw_err:
            _fw_log("equations.py:park", _fw_err)
    return done


class _ParkWatch:
    """After a rebuild that left a feature failing because a dimension its equation names was deleted, the equation
    is parked (park_broken) and the part rebuilt again."""

    busy = False

    def slotRecomputedDocument(self, doc):
        if _ParkWatch.busy or not any("Invalid" in o.State for o in doc.Objects):
            return
        name = doc.Name

        def later():
            d = App.listDocuments().get(name)
            if d is None or _ParkWatch.busy:
                return
            _ParkWatch.busy = True
            try:
                if park_broken(d):
                    d.recompute()
            finally:
                _ParkWatch.busy = False
        if Gui is not None:
            QtCore.QTimer.singleShot(0, later)
        else:
            later()


_PARK = []


def delete_equation(doc, obj, path):
    _set_pending(doc, sw_name(obj, path), None)
    obj.setExpression(path, None)


def evaluate(obj, path):
    p = path.lstrip(".")
    try:
        if p.startswith("Constraints"):
            m = re.match(r"^Constraints(?:\.(\w+)|\[(\d+)\])$", p)
            if m and m.group(1):
                v = obj.getDatum(m.group(1))
            else:
                v = obj.Constraints[int(m.group(2))].Value
        else:
            v = obj.getPropertyByName(p)
    except Exception:
        return "?"
    if p == "Suppressed":
        return "Suppressed" if v else "Unsuppressed"
    if p.startswith("Constraints") and isinstance(v, (int, float)):

        try:
            c = obj.Constraints[int(m.group(2))] if m.group(2) else next(c for c in obj.Constraints if c.Name == m.group(1))
            if c.Type == "Angle":
                import math
                return App.Units.Quantity(math.degrees(v), App.Units.Angle).UserString
            return App.Units.Quantity(v, App.Units.Length).UserString
        except Exception as _fw_err:
            _fw_log("equations.py:756", _fw_err)
    if hasattr(v, "UserString"):
        return v.UserString
    return "%g" % v if isinstance(v, float) else str(v)


# ---------------------------------------------------------------------- Link Values
META_LINKED = "FreeWorks:LinkedValue:"


def _number(obj, path):
    p = path.lstrip(".")
    m = re.match(r"^Constraints(?:\.(\w+)|\[(\d+)\])$", p)
    if m:
        c = obj.Constraints[int(m.group(2))] if m.group(2) else \
            next(c for c in obj.Constraints if c.Name == m.group(1))
        v = c.Value
        if c.Type == "Angle":
            import math
            return "%.12g deg" % math.degrees(v)
        return "%.12g mm" % v
    v = obj.getPropertyByName(p)
    if hasattr(v, "Value"):
        return "%.12g %s" % (v.Value, "deg" if "Angle" in str(type(v)) or p.endswith("Angle") else "mm")
    return "%.12g" % float(v)


def linked_values(doc):
    ""
    meta = doc.Meta
    return sorted(k[len(META_LINKED):] for k in meta if k.startswith(META_LINKED))


def linked_to(doc, name):
    """[(object, path)] of the dimensions sharing this linked value."""
    ref = "%s.%s" % (SHEET, alias_of(doc, name))
    return [(o, path) for o, path, expr in equations(doc) if expr.strip() == ref]


def link_value(obj, path, name):
    """Puts the dimension obj.path on the linked value name: a new name takes this dimension's
    value, an existing one gives the dimension its value. Works across sketches and features
    (the value is a global variable of the Equations folder, flagged as linked)."""
    doc = obj.Document
    name = name.strip()
    have = [n for n, _t, _v in variables(doc)]
    if name not in have:
        set_variable(doc, name, _number(obj, path))
        meta = doc.Meta
        meta[META_LINKED + name] = "1"
        doc.Meta = meta
    elif name not in linked_values(doc):
        raise ValueError("%s is a global variable, not a linked value" % name)
    obj.setExpression(path, "%s.%s" % (SHEET, alias_of(obj.Document, name)))
    doc.recompute()


def unlink_value(obj, path):
    ""

    doc = obj.Document
    expr = dict(getattr(obj, "ExpressionEngine", []) or []).get(path, "")
    name = _variable_name(expr.split(".", 1)[1]) if expr.startswith(SHEET + ".") else None
    obj.setExpression(path, None)
    doc.recompute()
    if name and name in linked_values(doc) and not linked_to(doc, name):
        delete_variable(doc, name)
        meta = doc.Meta
        meta.pop(META_LINKED + name, None)
        doc.Meta = meta


def linked_name(obj, path):
    expr = dict(getattr(obj, "ExpressionEngine", []) or []).get(path, "")
    if expr.startswith(SHEET + "."):
        name = _variable_name(expr.split(".", 1)[1])
        if name in linked_values(obj.Document):
            return name
    return None


def _variable_name(alias):
    """The global variable's own name for its sheet alias (gv_W -> W)."""
    return alias[len(SAFE):] if alias.startswith(SAFE) else alias


def dimensions(doc):
    ""
    out = []
    for o in doc.Objects:
        if o.isDerivedFrom("Sketcher::SketchObject"):
            for n, (i, cname) in enumerate(_sketch_dims(o), 1):
                path = (".Constraints.%s" % cname) if cname else (".Constraints[%d]" % i)
                out.append(("%s@%s" % (_dim_name(n, cname), o.Label), o, path, evaluate(o, path)))
        for n, p in enumerate(FEATURE_DIMS.get(o.TypeId, ()), 1):
            if p in o.PropertiesList:
                out.append(("D%d@%s" % (n, o.Label), o, p, evaluate(o, p)))
    return out


def comment(doc, key):
    return dict(doc.Meta).get(META_COMMENT + key, "")


def set_comment(doc, key, text):
    meta = dict(doc.Meta)
    if text:
        meta[META_COMMENT + key] = text
    else:
        meta.pop(META_COMMENT + key, None)
    doc.Meta = meta


# ---------------------------------------------------------------------- import / export
def all_rows(doc):
    ""

    wait = pending(doc)
    out = []
    for name, raw, _e in variables(doc):
        out.append((name, wait.get(name) or to_sw(doc, raw), comment(doc, name)))
    seen = set()
    for o, path, expr in equations(doc):
        nm = sw_name(o, path)
        seen.add(nm)
        out.append((nm, wait.get(nm) or to_sw(doc, expr, owner=o), comment(doc, nm)))
    names = {r[0] for r in out}
    for nm, text in wait.items():
        if nm not in names:
            out.append((nm, text, comment(doc, nm)))
    return out


def export_text(doc, names=None):
    ""
    lines = []
    for name, text, note in all_rows(doc):
        if names is not None and name not in names:
            continue
        lines.append('"%s"= %s' % (name, text) + (" '%s" % note if note else ""))
    return "\n".join(lines) + "\n"


def export_file(doc, path, names=None):
    with open(path, "w", encoding="utf-8") as f:
        f.write(export_text(doc, names))
    if path == linked_file(doc):
        _stamp_link(doc, path)
    return path


def read_lines(text):
    """[(name, right side, comment)] of an equation file's lines."""
    out = []
    for line in text.splitlines():
        body, _q, note = line.partition("'")
        m = re.match(r'^"([^"]+)"\s*=\s*(.+)$', body.strip())
        if m:
            out.append((m.group(1), m.group(2).strip(), note.strip()))
    return out


def import_text(doc, text, names=None):
    ""

    n = 0
    for name, right, note in read_lines(text):
        if names is not None and name not in names:
            continue
        if dimension_path(doc, name) is not None and ("@" in name or "." in name or _by_label(doc, name)):
            set_equation(doc, name, right)
        else:
            set_variable(doc, name, right)
        if note:
            set_comment(doc, name, note)
        n += 1
    doc.recompute()
    return n


def import_file(doc, path, names=None):
    with open(path, encoding="utf-8") as f:
        n = import_text(doc, f.read(), names)
    if path == linked_file(doc):
        _stamp_link(doc, path)
    return n


def _file_md5(path):
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except OSError:
        return ""


def _stamp_link(doc, path):
    meta = dict(doc.Meta)
    meta[META_LINK_STAMP] = _file_md5(path)
    doc.Meta = meta


def reread_linked(doc):
    ""
    try:
        path = linked_file(doc)
        if not path or not os.path.isfile(path):
            return 0
        if _file_md5(path) == dict(doc.Meta).get(META_LINK_STAMP, ""):
            return 0
        n = import_file(doc, path)
        _stamp_link(doc, path)
        doc.recompute()
        return n
    except Exception as _fw_err:
        _fw_log("equations.py:reread_linked", _fw_err)
        return 0


# ---------------------------------------------------------------------- Ordered View
def solve_order(doc):
    """Names of the variables and equations in the order they are solved: each after the ones it uses (FreeCAD
    solves by what each uses, Automatic solve order); the listed order breaks ties."""
    rows = all_rows(doc)
    names = [r[0] for r in rows]
    deps = {}
    for name, text, _n in rows:
        deps[name] = {m for m in re.findall(r'"([^"]+)"', text) if m in names and m != name}
    out, left = [], list(names)
    while left:
        nxt = next((n for n in left if deps[n] <= set(out)), left[0])     # a loop: listed order
        out.append(nxt)
        left.remove(nxt)
    return out


def listed_order(doc):
    """Ordered View with Automatic solve order off: the order the rows were dragged into (new rows at the end)."""
    try:
        saved = json.loads(dict(doc.Meta).get(META_ORDER, "") or "[]")
    except Exception:
        saved = []
    names = solve_order(doc)
    return [n for n in saved if n in names] + [n for n in names if n not in saved]


def set_listed_order(doc, names):
    meta = dict(doc.Meta)
    meta[META_ORDER] = json.dumps(list(names))
    doc.Meta = meta


def linked_file(doc):
    return dict(doc.Meta).get(META_LINK, "")


def set_linked_file(doc, path):
    meta = dict(doc.Meta)
    if path:
        meta[META_LINK] = path
    else:
        meta.pop(META_LINK, None)
    doc.Meta = meta


# ---------------------------------------------------------------------- the box
if Gui is not None:
    Qt = QtCore.Qt
    KIND = Qt.UserRole
    VIEWS = ("Equation View", "Sketch Equation View", "Dimension View", "Ordered View")

    FUNCTIONS = ("sin()", "cos()", "tan()", "sec()", "cosec()", "cotan()", "arcsin()", "arccos()", "atn()",
                 "arcsec()", "arccosec()", "arccotan()", "abs()", "exp()", "log()", "sqr()", "int()", "sgn()",
                 "pi", "iif( ; ; )")

    def completions(doc):
        ""

        out = ['"%s"' % v[0] for v in variables(doc)]
        out += ['"%s"' % d[0] for d in dimensions(doc)]
        return out + list(FUNCTIONS) + ['$PRP:"%s"' % n for n in FILE_PROPERTIES] + [MEASURE]

    _TOKEN = re.compile(r'("[^"]*|\$?[A-Za-z_][\w@.]*)$')

    class _Completing(QtWidgets.QLineEdit):
        """A cell editor that completes the word being typed (a quoted name or a function)."""

        def __init__(self, words, parent=None):
            super().__init__(parent)
            self.words = words
            self.done = QtWidgets.QCompleter(words, self)
            self.done.setCaseSensitivity(Qt.CaseInsensitive)
            self.done.setFilterMode(Qt.MatchContains)
            self.done.setWidget(self)
            self.done.activated[str].connect(self.insert_word)
            self.textEdited.connect(self._typed)
            self.done.popup().installEventFilter(self)

        def eventFilter(self, watched, event):

            # took the Enter and only closed itself (a second Enter was needed): the cell is finished now
            if watched is self.done.popup() and event.type() == QtCore.QEvent.KeyPress \
                    and event.key() in (Qt.Key_Return, Qt.Key_Enter) and not watched.currentIndex().isValid():
                watched.hide()
                QtWidgets.QApplication.sendEvent(self, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, event.key(), event.modifiers()))
                return True
            return False

        def _token(self):
            m = _TOKEN.search(self.text()[:self.cursorPosition()])
            return m.group(1) if m else ""

        def _typed(self, text):
            token = self._token()
            if not token:
                if text[:self.cursorPosition()].strip() == "=":

                    # dimensions, functions, file properties, Measure...)
                    self.done.setCompletionPrefix("")
                    self.done.complete()
                    return
                self.done.popup().hide()
                return
            self.done.setCompletionPrefix(token)
            if self.done.completionCount():
                self.done.complete()
            else:
                self.done.popup().hide()

        def insert_word(self, word):
            if word == MEASURE:
                got = measure_selection()
                word = ("%g" % got) if got is not None else ""
                if got is None:
                    QtWidgets.QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()),
                                                "Pick two entities (or an edge) in the graphics area, then Measure...")
            pos = self.cursorPosition()
            token = self._token()
            head, tail = self.text()[:pos - len(token)], self.text()[pos:]
            self.setText(head + word + tail)
            self.setCursorPosition(len(head + word) - (1 if word.endswith("()") else 0))

        def keyPressEvent(self, event):
            if self.done.popup().isVisible() and event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
                event.ignore()
                return
            super().keyPressEvent(event)

    class _CompleteDelegate(QtWidgets.QStyledItemDelegate):
        def __init__(self, dialog):
            super().__init__(dialog.tree)
            self.dialog = dialog

        def createEditor(self, parent, option, index):
            return _Completing(completions(self.dialog.doc), parent)

    def _view_icon(i):
        ""

        from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
        pm = _hidpi.canvas(40, 40)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        blue, dark = QtGui.QColor(40, 110, 200), QtGui.QColor(70, 70, 70)
        font = p.font()
        font.setPixelSize(26)
        font.setBold(True)
        p.setFont(font)
        if i in (0, 1):
            p.setPen(blue)
            p.drawText(QtCore.QRect(0, 0, 30 if i == 1 else 40, 40), Qt.AlignCenter, "\u03a3")
            if i == 1:
                p.setPen(QtGui.QPen(QtGui.QColor(230, 150, 30), 4))
                p.drawLine(26, 36, 38, 20)
        elif i == 2:
            p.setPen(QtGui.QPen(dark, 3))
            p.drawLine(4, 26, 36, 26)
            p.drawLine(4, 14, 4, 36)
            p.drawLine(36, 14, 36, 36)
            p.setBrush(dark)
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(5, 26), QtCore.QPointF(13, 21), QtCore.QPointF(13, 31)]))
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(35, 26), QtCore.QPointF(27, 21), QtCore.QPointF(27, 31)]))
            font.setPixelSize(14)
            p.setFont(font)
            p.setPen(blue)
            p.drawText(QtCore.QRect(0, 0, 40, 20), Qt.AlignCenter, "D1")
        elif i == 3:
            font.setPixelSize(11)
            p.setFont(font)
            for row in range(3):
                y = 6 + row * 12
                p.setPen(blue)
                p.drawText(QtCore.QRect(2, y - 2, 12, 12), Qt.AlignCenter, str(row + 1))
                p.setPen(QtGui.QPen(dark, 3))
                p.drawLine(17, y + 4, 37, y + 4)
        else:
            p.setPen(QtGui.QPen(dark, 2))
            p.setBrush(QtGui.QColor(60, 60, 60))
            p.drawRoundedRect(QtCore.QRectF(12, 2, 16, 36), 4, 4)
            p.setPen(Qt.NoPen)
            for k, col in enumerate(((220, 50, 40), (240, 190, 30), (40, 180, 60))):
                p.setBrush(QtGui.QColor(*col))
                p.drawEllipse(QtCore.QPointF(20, 9 + k * 11), 4.5, 4.5)
        p.end()
        return QtGui.QIcon(pm)

    def _funnel_icon():
        """The filter funnel at the left of Filter All Fields (equations-1119)."""
        from . import hidpi as _hidpi
        pm = _hidpi.canvas(32, 32)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(QtGui.QPen(QtGui.QColor(70, 70, 70), 2))
        p.setBrush(QtGui.QColor(120, 160, 210))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(3, 5), QtCore.QPointF(29, 5), QtCore.QPointF(19, 17),
                                       QtCore.QPointF(19, 28), QtCore.QPointF(13, 24), QtCore.QPointF(13, 17)]))
        p.end()
        return QtGui.QIcon(pm)

    class EquationsDialog(QtWidgets.QDialog):
        def __init__(self, doc=None, parent=None):
            super().__init__(parent or Gui.getMainWindow())
            self.doc = doc or App.ActiveDocument
            self.setObjectName("SWEquations")
            self.setWindowTitle("Equations, Global Variables, and Dimensions")
            self.resize(780, 460)
            lay = QtWidgets.QVBoxLayout(self)
            bar = QtWidgets.QHBoxLayout()
            self.view_buttons = []
            for i, name in enumerate(VIEWS):
                b = QtWidgets.QToolButton()
                b.setText(name)
                b.setToolTip(name)
                b.setIcon(_view_icon(i))
                b.setIconSize(QtCore.QSize(20, 20))
                b.setToolButtonStyle(Qt.ToolButtonIconOnly)
                b.setAutoRaise(True)
                b.setCheckable(True)
                b.setAutoExclusive(True)
                b.setObjectName("SWEqView%d" % i)
                b.clicked.connect(lambda _c=False, i=i: self.set_view(i))
                bar.addWidget(b)
                self.view_buttons.append(b)
            self.rebuild_button = QtWidgets.QToolButton()
            self.rebuild_button.setObjectName("SWEqRebuild")
            self.rebuild_button.setToolTip("Rebuild: rebuilds the part with the equations now")
            self.rebuild_button.setIcon(_view_icon(4))
            self.rebuild_button.setIconSize(QtCore.QSize(20, 20))
            self.rebuild_button.setAutoRaise(True)
            self.rebuild_button.clicked.connect(self._rebuild_now)
            bar.addSpacing(12)
            self.filter = QtWidgets.QLineEdit()
            self.filter.setObjectName("SWEqFilter")
            self.filter.setClearButtonEnabled(True)
            self.filter.setPlaceholderText("Filter All Fields")
            self.filter.textChanged.connect(self.refresh)
            try:
                self.filter.addAction(_funnel_icon(), QtWidgets.QLineEdit.ActionPosition.LeadingPosition)
            except Exception as _fw_err:
                _fw_log("equations.py:funnel", _fw_err)
            self.filter.setMinimumWidth(190)
            bar.addWidget(self.filter)
            bar.addSpacing(8)
            self.undo_button = self._edit_button("Undo", "STANDARD_UNDO", self._undo_step)
            self.redo_button = self._edit_button("Redo", "STANDARD_REDO", self._redo_step)
            bar.addWidget(self.undo_button)
            bar.addWidget(self.redo_button)
            bar.addStretch(1)
            lay.addLayout(bar)
            self.tree = QtWidgets.QTreeWidget()
            self.tree.setObjectName("SWEquationsTree")
            self.tree.setHeaderLabels(["Name", "Value / Equation", "Evaluates to", "Comments"])
            self.tree.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked |
                                      QtWidgets.QAbstractItemView.EditKeyPressed |
                                      QtWidgets.QAbstractItemView.SelectedClicked)
            self.tree.itemChanged.connect(self._edited)
            self._complete = _CompleteDelegate(self)
            self.tree.setItemDelegateForColumn(0, self._complete)
            self.tree.setItemDelegateForColumn(1, self._complete)
            self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
            self.tree.customContextMenuRequested.connect(self._menu)
            mid = QtWidgets.QHBoxLayout()
            mid.addWidget(self.tree, 1)
            side = QtWidgets.QVBoxLayout()
            mid.addLayout(side)
            lay.addLayout(mid, 1)
            low = QtWidgets.QHBoxLayout()
            self.auto = QtWidgets.QCheckBox("Automatically rebuild")
            self.auto.setObjectName("SWEqAutoRebuild")
            self.auto.setChecked(App.ParamGet(PARAMS).GetBool("EquationsAutoRebuild", True))
            self.auto.toggled.connect(lambda on: App.ParamGet(PARAMS).SetBool("EquationsAutoRebuild", bool(on)))
            low.addWidget(self.auto)
            low.addWidget(self.rebuild_button)
            low.addWidget(QtWidgets.QLabel("Angular equation units:"))
            self.angle = QtWidgets.QComboBox()
            self.angle.addItems(["Degrees", "Radians"])
            self._angle0 = angle_units(self.doc)
            self.angle.setCurrentText(self._angle0)
            self.angle.currentTextChanged.connect(self._angle_changed)
            low.addWidget(self.angle)
            self.solve = QtWidgets.QCheckBox("Automatic solve order")
            self.solve.setObjectName("SWEqAutoSolve")
            self.solve.setChecked(dict(self.doc.Meta).get(META_SOLVE, "1") != "0")
            self.solve.toggled.connect(self._solve_changed)
            low.addWidget(self.solve)
            self.link = QtWidgets.QCheckBox("Link to external file:")
            self.link.setObjectName("SWEqLink")
            self.link_path = QtWidgets.QLineEdit(linked_file(self.doc))
            self.link_path.setObjectName("SWEqLinkPath")
            self.link.setChecked(bool(linked_file(self.doc)))
            # always live: a typed or browsed file ticks the box; ticking with no file asks for one
            self.link_path.textEdited.connect(lambda t: self.link.setChecked(bool(t.strip())))
            self.link_browse = QtWidgets.QToolButton()
            self.link_browse.setObjectName("SWEqLinkBrowse")
            self.link_browse.setText("...")
            self.link_browse.setToolTip("Pick the equations file (.txt)")
            self.link_browse.clicked.connect(self._browse_link)
            self.link.toggled.connect(self._link_toggled)
            low.addStretch(1)
            lay.addLayout(low)
            link_row = QtWidgets.QHBoxLayout()
            link_row.addWidget(self.link)
            link_row.addWidget(self.link_path, 1)
            link_row.addWidget(self.link_browse)
            lay.addLayout(link_row)
            for _w in (self.link_path, self.link_browse):      # the field appears once the box is ticked
                _w.setVisible(self.link.isChecked())
                self.link.toggled.connect(_w.setVisible)
            for text, slot in (("OK", self.accept), ("Cancel", self.reject), ("Import...", self._import),
                               ("Export...", self._export), ("Help", self._help)):
                b = QtWidgets.QPushButton(text)
                b.setObjectName("SWEq" + text.rstrip("."))
                b.clicked.connect(lambda _c=False, slot=slot: slot())
                if text == "OK":
                    b.setDefault(True)
                side.addWidget(b)
            side.addStretch(1)
            self.status = QtWidgets.QLabel("")
            self.status.setObjectName("SWEquationsStatus")
            lay.addWidget(self.status)
            self._filling = False
            self._drag = None                 # Ordered View: [row name, press point, dragging]
            self._drop_line = QtWidgets.QFrame(self.tree.viewport())
            self._drop_line.setObjectName("SWEqDropLine")
            self._drop_line.setFrameShape(QtWidgets.QFrame.HLine)
            self._drop_line.setStyleSheet("color: palette(highlight); background: palette(highlight);")
            self._drop_line.hide()
            self.tree.viewport().installEventFilter(self)
            self.view = 0
            self.view_buttons[0].setChecked(True)
            self._steps, self._redo = [], []          # equations-1119: this box's Undo / Redo list
            self._base = self.doc.UndoCount
            self._watch_steps()
            self._meta0 = self._meta_now()
            self.doc.openTransaction("Equations")
            try:
                if self.link.isChecked() and os.path.isfile(self.link_path.text()):
                    import_file(self.doc, self.link_path.text())
                    _stamp_link(self.doc, self.link_path.text())
                self._seal(self._meta0)
                self.refresh()
            except BaseException:
                try:
                    self.doc.abortTransaction()
                except Exception:
                    pass
                raise

        # ------------------------------------------------------------ Undo / Redo (equations-1119)
        # Every edit of the box is its own step of the document's Undo list; the box keeps the list of its own steps with the
        # angle / solve-order settings each had, so Undo and Redo here step through exactly these edits. Cancel undoes them all.
        def _edit_button(self, text, family, slot):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWEq" + text)
            b.setToolTip(text)
            b.setAutoRaise(True)
            try:
                from . import icons
                icon = icons.family(family)
                if icons.paints(icon):
                    b.setIcon(icon)
                    b.setIconSize(QtCore.QSize(20, 20))
                    b.setToolButtonStyle(Qt.ToolButtonIconOnly)
                else:
                    b.setText(text)
            except Exception:
                b.setText(text)
            b.clicked.connect(lambda _c=False: slot())
            # NO DEAD CONTROLS: shown only while it can act, its place kept so the bar does not jump
            sp = b.sizePolicy()
            sp.setRetainSizeWhenHidden(True)
            b.setSizePolicy(sp)
            return b

        def _meta_now(self):
            m = dict(self.doc.Meta)
            return (angle_units(self.doc), m.get(META_SOLVE, "1"), m.get(META_ORDER, ""))

        def _set_meta(self, meta):
            angle, solve, order = (tuple(meta) + ("",))[:3]
            m = dict(self.doc.Meta)
            m[META_ANGLE], m[META_SOLVE] = angle, solve
            if order:
                m[META_ORDER] = order
            else:
                m.pop(META_ORDER, None)
            self.doc.Meta = m
            for box, call, value in ((self.angle, self.angle.setCurrentText, angle), (self.solve, self.solve.setChecked, solve != "0")):
                box.blockSignals(True)
                call(value)
                box.blockSignals(False)

        # The document's Undo list holds 20 steps (MaxUndoSize): once it is full a new step drops the oldest and UndoCount
        # stays put, so steps are counted from FreeCAD's own transaction signals instead (a commit is only signalled for a
        # transaction that recorded a change); an Undo/Redo or a step not made here means the list is no longer ours.
        def _watch_steps(self):
            self._commits, self._foreign, self._ours_busy = 0, False, False
            box = self

            class _Watch:
                def _mine(self, doc):
                    try:
                        return doc.Name == box.doc.Name
                    except Exception:
                        return False

                def slotCommitTransaction(self, doc):
                    if self._mine(doc):
                        if box._ours_busy:
                            box._commits += 1
                        else:
                            box._foreign = True

                def slotUndoDocument(self, doc):
                    if self._mine(doc) and not box._ours_busy:
                        box._foreign = True

                def slotRedoDocument(self, doc):
                    self.slotUndoDocument(doc)

            self._watch = _Watch()
            try:
                App.addDocumentObserver(self._watch)
            except Exception as _fw_err:
                _fw_log("equations.py:watch", _fw_err)
                self._watch = None
            self.finished.connect(lambda _r=0: self._unwatch())

        def _unwatch(self):
            w, self._watch = getattr(self, "_watch", None), None
            if w is not None:
                try:
                    App.removeDocumentObserver(w)
                except Exception as _fw_err:
                    _fw_log("equations.py:unwatch", _fw_err)

        def _seal(self, before=None):
            """Closes the edit just made as one step of this box's Undo list."""
            doc = self.doc
            self._ours_busy = True
            try:
                if getattr(doc, "HasPendingTransaction", False):
                    doc.commitTransaction()
                App.closeActiveTransaction()     # else the next change (the recompute after an Undo) joins a new "Equations" step
            except Exception as _fw_err:
                _fw_log("equations.py:seal", _fw_err)
            finally:
                self._ours_busy = False
            changed = self._commits > 0
            self._commits = 0
            if self._foreign:
                # something else was done to the document since this box's last step: the older steps can no longer be
                # stepped back in order (the document's Undo would take that other step first)
                self._steps, self._redo, self._foreign = [], [], False
            now = self._meta_now()
            before = before or now
            if changed or before != now:           # a document edit, or only the angle / solve-order setting (kept in the box's own list)
                self._steps.append((before, now, changed))
                self._redo = []
            self._base = doc.UndoCount
            self._sync_undo()

        def _sync_undo(self):
            ours = not self._foreign          # nothing else has been done to the document meanwhile
            # never greyed: an Undo / Redo with nothing to step is left out (its place kept)
            for b, can in ((self.undo_button, bool(self._steps) and ours), (self.redo_button, bool(self._redo) and ours)):
                b.setEnabled(True)
                b.setVisible(can)

        def _move(self, undo):
            doc = self.doc
            self._seal()
            stack, other = (self._steps, self._redo) if undo else (self._redo, self._steps)
            if not stack or self._foreign:
                self._sync_undo()
                return
            before, after, edited = stack.pop()
            if edited:
                self._ours_busy = True
                try:
                    (doc.undo if undo else doc.redo)()
                finally:
                    self._ours_busy = False
            self._set_meta(before if undo else after)
            other.append((before, after, edited))
            self._base = doc.UndoCount
            doc.recompute()
            self.status.setText("")
            self.refresh()
            self._sync_undo()

        def _undo_step(self):
            self._move(True)

        def _redo_step(self):
            self._move(False)

        def _step(fn):
            def run(self, *args, **kwargs):
                before = self._meta_now()
                self._ours_busy = True
                try:
                    return fn(self, *args, **kwargs)
                finally:
                    self._ours_busy = False
                    self._seal(before)
            run.__name__ = fn.__name__
            return run

        def _tx(self):
            """The box's one Undo step. FreeCAD closes the transaction a command is run in when the
            command returns, so the one opened with the box is gone by the first edit: open it again."""
            try:
                if not getattr(self.doc, "HasPendingTransaction", False):
                    self.doc.openTransaction("Equations")
            except Exception as _fw_err:
                _fw_log("equations.py:tx", _fw_err)

        # ------------------------------------------------------------ rows
        def set_view(self, i):
            self.view = i
            self.view_buttons[i].setChecked(True)
            self.refresh()

        def _item(self, parent, cols, kind, editable=(1, 3)):
            item = QtWidgets.QTreeWidgetItem([str(c) for c in cols])
            item.setData(0, KIND, kind)
            if editable:
                item.setFlags(item.flags() | Qt.ItemIsEditable)
            item.setData(0, Qt.UserRole + 1, tuple(editable))
            (parent.addChild(item) if isinstance(parent, QtWidgets.QTreeWidgetItem) else self.tree.addTopLevelItem(item))
            return item

        def _mark(self, item, why):
            ""
            if not why:
                return item
            for c in range(4):
                item.setForeground(c, QtGui.QBrush(QtGui.QColor(220, 0, 0)))
                item.setToolTip(c, why)
            item.setText(2, "Error")
            return item

        def _add_row(self, parent, text, kind):
            item = self._item(parent, [text, "", "", ""], kind, (0,))
            item.setForeground(0, QtGui.QBrush(QtGui.QColor(128, 128, 128)))
            return item

        def _matches(self, cols):
            f = self.filter.text().strip().lower()
            return not f or any(f in str(c).lower() for c in cols)

        def _wait_why(self, text):
            return "Not solved yet: %s is not a global variable or a dimension of the part" % \
                ", ".join('"%s"' % n for n in missing_names(self.doc, text))

        def _var_row(self, parent, name, raw, got):
            wait = pending(self.doc).get(name)
            text = wait if wait else to_sw(self.doc, raw)
            cols = ['"%s"' % name, "= " + text, shown_value(got), comment(self.doc, name)]
            if self._matches(cols):
                return self._mark(self._item(parent, cols, ("var", name)),
                                  self._wait_why(wait) if wait else _var_error(got))
            return None

        def _eq_row(self, parent, o, path, expr):
            doc = self.doc
            nm = sw_name(o, path)
            wait = pending(doc).get(nm)
            shown = wait or to_sw(doc, expr, owner=o)
            if not wait and path.lstrip(".") == "Suppressed" and shown.strip() in ("0", "1", "True", "False"):
                shown = '"suppressed"' if shown.strip() in ("1", "True") else '"unsuppressed"'
            cols = ['"%s"' % nm, "= " + shown, evaluate(o, path), comment(doc, nm)]
            if not self._matches(cols):
                return None
            return self._mark(self._item(parent, cols, ("eq", o.Name, path)), self._wait_why(wait) if wait else broken(o))

        def _waiting_rows(self, parent, shown):
            """Equations that name something not made yet and have no expression on their dimension yet."""
            for nm, text in pending(self.doc).items():
                if nm in shown or any(n == nm for n, _r, _g in variables(self.doc)):
                    continue
                cols = ['"%s"' % nm, "= " + text, "", comment(self.doc, nm)]
                if self._matches(cols):
                    self._mark(self._item(parent, cols, ("pend", nm)), self._wait_why(text))

        def refresh(self):
            self._filling = True
            self.tree.blockSignals(True)
            self.tree.clear()
            doc = self.doc
            ordered = self.view == 3 and not self.solve.isChecked()

            self.tree.setProperty("rowsDraggable", ordered)
            self.tree.setRootIsDecorated(self.view != 3)
            if self.view == 3:
                rows = {}
                for name, raw, got in variables(doc):
                    rows[name] = ("var", name, raw, got)
                for o, path, expr in equations(doc):
                    rows[sw_name(o, path)] = ("eq", o, path, expr)
                for name in (listed_order(doc) if ordered else solve_order(doc)):
                    r = rows.get(name)
                    if r is None:
                        it = None
                        if name in pending(doc):
                            cols = ['"%s"' % name, "= " + pending(doc)[name], "", comment(doc, name)]
                            if self._matches(cols):
                                it = self._mark(self._item(None, cols, ("pend", name)), self._wait_why(pending(doc)[name]))
                    elif r[0] == "var":
                        it = self._var_row(None, r[1], r[2], r[3])
                    else:
                        it = self._eq_row(None, r[1], r[2], r[3])
            else:
                g = self._item(None, ["Global Variables", "", "", ""], ("head",), ())
                for name, raw, got in variables(doc):
                    if self.view in (0, 2):
                        self._var_row(g, name, raw, got)
                if self.view == 0:
                    self._add_row(g, "Add global variable", ("addvar",))
                fts = self._item(None, ["Features", "", "", ""], ("head",), ())
                eqs = self._item(None, ["Dimensions" if self.view == 2 else "Equations", "", "", ""], ("head",), ())
                shown = set()
                for o, path, expr in equations(doc):
                    sketchy = o.isDerivedFrom("Sketcher::SketchObject")
                    shown.add(sw_name(o, path))
                    supp = path.lstrip(".") == "Suppressed"
                    if (self.view == 1 and not sketchy) or (self.view == 2 and not supp):
                        continue
                    self._eq_row(fts if supp else eqs, o, path, expr)
                if self.view == 2:
                    # Dimension View: every dimension of the part, with its equation where it has one
                    for name, o, path, value in dimensions(doc):
                        eq = next((e for ob, p, e in equations(doc) if ob is o and p.lstrip(".") == path.lstrip(".")), "")
                        wait = pending(doc).get(name)
                        cols = [name, ("= " + wait) if wait else (("= " + to_sw(doc, eq, owner=o)) if eq else value), value,
                                comment(doc, name)]
                        if self._matches(cols):
                            self._mark(self._item(eqs, cols, ("dim", o.Name, path), (1, 3)), self._wait_why(wait) if wait else None)
                else:
                    if self.view == 0:
                        self._waiting_rows(eqs, shown)
                    self._add_row(fts, "Add feature suppression", ("addfeat",))
                    self._add_row(eqs, "Add equation", ("addeq",))
                self.tree.expandAll()
            for c in range(4):
                self.tree.resizeColumnToContents(c)
            self.tree.blockSignals(False)
            self._filling = False

        def _drop_at(self, pos):
            """(row index to put the dragged row before, y of the line) for a point in the list."""
            n = self.tree.topLevelItemCount()
            for k in range(n):
                r = self.tree.visualItemRect(self.tree.topLevelItem(k))
                if pos.y() < r.center().y():
                    return k, r.top()
            last = self.tree.visualItemRect(self.tree.topLevelItem(n - 1)) if n else QtCore.QRect()
            return n, last.bottom() + 1

        def eventFilter(self, obj, event):
            # Ordered View, Automatic solve order off: press on a row, drag it to its place, let go (a line shows where)
            try:
                if obj is not self.tree.viewport() or not self.tree.property("rowsDraggable"):
                    return False
                t = event.type()
                if t == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                    it = self.tree.itemAt(event.position().toPoint())
                    self._drag = [it.text(0).strip('"'), event.position().toPoint(), False] if it is not None else None
                elif t == QtCore.QEvent.MouseMove and self._drag is not None and event.buttons() & Qt.LeftButton:
                    pos = event.position().toPoint()
                    if not self._drag[2] and (pos - self._drag[1]).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                        self._drag[2] = True
                        self.tree.viewport().setCursor(Qt.ClosedHandCursor)
                    if self._drag[2]:
                        _k, y = self._drop_at(pos)
                        self._drop_line.setGeometry(0, max(0, y - 1), self.tree.viewport().width(), 2)
                        self._drop_line.show()
                        self._drop_line.raise_()
                        return True
                elif t == QtCore.QEvent.MouseButtonRelease and self._drag is not None:
                    name, _p, dragging = self._drag
                    self._drag = None
                    self._drop_line.hide()
                    self.tree.viewport().unsetCursor()
                    if dragging:
                        k, _y = self._drop_at(event.position().toPoint())
                        QtCore.QTimer.singleShot(0, lambda: self._move_row(name, k))
                        return True
            except Exception as _fw_err:
                _fw_log("equations.py:drag", _fw_err)
            return False

        @_step
        def _move_row(self, name, before):
            shown = [self.tree.topLevelItem(k).text(0).strip('"') for k in range(self.tree.topLevelItemCount())]
            if name not in shown:
                return
            target = shown[before] if before < len(shown) else None
            if target == name:
                return
            order = [n for n in listed_order(self.doc) if n != name]
            order.insert(order.index(target) if target in order else len(order), name)
            set_listed_order(self.doc, order)
            self.status.setText("Equations are solved in the order listed")
            self.refresh()

        def _rebuild_now(self):
            self.doc.recompute()
            self.refresh()

        def _help(self):
            # the User Guide's section on this box; FreeCAD's wiki page on expressions only when the guide has none
            try:
                from . import helpguide
                if helpguide.show_topic("equations") is not None:
                    return
            except Exception as _fw_err:
                _fw_log("equations.py:help", _fw_err)
            QtGui.QDesktopServices.openUrl(QtCore.QUrl("https://wiki.freecad.org/Expressions"))

        # ------------------------------------------------------------ edits
        def _rebuild(self):
            if self.auto.isChecked():
                self.doc.recompute()

        @_step
        def _edited(self, item, col):
            kind = item.data(0, KIND) or ("none",)
            text = item.text(col).strip()
            doc = self.doc
            self._tx()
            try:
                if kind[0] in ("addvar", "addfeat", "addeq"):
                    if col != 0 or not text or text.startswith("Add "):
                        return
                    name = text.strip('"')
                    if kind[0] == "addvar":
                        set_variable(doc, name, "0", self.auto.isChecked())
                    else:
                        got = dimension_path(doc, name)
                        if got is None:
                            raise ValueError("No dimension or feature called %s" % name)
                        obj, path = got
                        cur = evaluate(obj, path)
                        if path != "Suppressed":
                            try:
                                cur = _number(obj, path)        # its full value, not the shown decimals
                            except Exception as _fw_err:
                                _fw_log("equations.py:addeq", _fw_err)
                        if path == "Suppressed":
                            value = "1" if cur == "Suppressed" else "0"
                        else:
                            m = re.match(r"^\s*(-?[0-9.]+(?:e-?\d+)?)", cur.replace(",", "."))
                            value = m.group(1) if m else "0"
                            unit = cur[m.end():].strip() if m else ""
                            if unit and unit != "°":
                                value = "%s %s" % (value, unit)
                        obj.setExpression(path, value)
                elif col == 3:
                    name = item.text(0).strip('"')
                    set_comment(doc, name, text)
                    return
                elif kind[0] == "var" and col == 0:
                    rename_variable(doc, kind[1], text)
                elif kind[0] == "var" and col == 1:
                    set_variable(doc, kind[1], text.lstrip("= ").strip() or "0", self.auto.isChecked())
                elif kind[0] == "pend" and col == 1:
                    right = text.lstrip("=").strip()
                    if right:
                        set_equation(doc, kind[1], right)
                    else:
                        _set_pending(doc, kind[1], None)
                elif kind[0] in ("eq", "dim") and col == 1 and text.startswith("=") and \
                        missing_names(doc, text.lstrip("=").strip(), target=(doc.getObject(kind[1]), kind[2])):
                    # names a variable not made yet: kept in red, solved once it is (its dimension keeps its value)
                    _set_pending(doc, sw_name(doc.getObject(kind[1]), kind[2]), text.lstrip("=").strip())
                elif kind[0] in ("eq", "dim") and col == 1:
                    obj = doc.getObject(kind[1])
                    right = text.lstrip("=").strip()
                    if kind[0] == "dim" and not text.startswith("="):
                        obj.setExpression(kind[2], None)
                        try:
                            q = App.Units.Quantity(right)
                            if _is_number(right) and _kind(obj, kind[2]) == "len":
                                q = App.Units.Quantity(float(right) * _doc_length(doc)[1], App.Units.Length)   # the part's unit
                            if kind[2].startswith(".Constraints"):
                                m = re.match(r"^\.Constraints(?:\.(\w+)|\[(\d+)\])$", kind[2])
                                obj.setDatum(m.group(1) or int(m.group(2)), q)
                            else:
                                setattr(obj, kind[2], q.Value)
                        except Exception as _fw_err:
                            _fw_log("equations.py:1272", _fw_err)
                    else:
                        accept_expression(doc, obj, kind[2], to_freecad(doc, right, target=(obj, kind[2])) if right else None,
                                          sw_name(obj, kind[2]))
                    _set_pending(doc, sw_name(obj, kind[2]), None)
                self.status.setText("" if self.auto.isChecked() else "Rebuild to update the model with the equations")
                self._rebuild()
            except Exception as error:
                self.status.setText(str(error))
            QtCore.QTimer.singleShot(0, self.refresh)

        def _menu(self, pos):
            item = self.tree.itemAt(pos)
            kind = (item.data(0, KIND) if item is not None else None) or ("none",)
            if kind[0] not in ("var", "eq", "pend"):
                return
            menu = QtWidgets.QMenu(self)
            act = menu.addAction("Delete")
            if menu.exec_(self.tree.viewport().mapToGlobal(pos)) is act:
                self.delete(item)

        @_step
        def delete(self, item):
            kind = item.data(0, KIND)
            self._tx()
            if kind[0] == "var":
                delete_variable(self.doc, kind[1])
            elif kind[0] == "eq":
                delete_equation(self.doc, self.doc.getObject(kind[1]), kind[2])
            elif kind[0] == "pend":
                _set_pending(self.doc, kind[1], None)
            self._rebuild()
            self.refresh()

        def keyPressEvent(self, event):
            if event.key() == Qt.Key_Delete and self.tree.currentItem() is not None:
                self.delete(self.tree.currentItem())
                return
            super().keyPressEvent(event)

        def _link_to(self, path):
            self.link.blockSignals(True)
            self.link.setChecked(True)
            self.link.blockSignals(False)
            self.link_path.setText(path)
            self.link_path.setVisible(True)
            self.link_browse.setVisible(True)

        @_step
        def _import(self, path=None, names=None, link=False):
            picked = path is None
            if path is None:
                path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Import Equations", "", "Text (*.txt)")
            if not path:
                return
            if picked:

                try:
                    with open(path, encoding="utf-8") as f:
                        rows = read_lines(f.read())
                except OSError as error:
                    self.status.setText(str(error))
                    return
                box = _Pick(self, "Import Equations", "SWEqImportPick", rows, "Import")
                if not box.exec():
                    return
                names, link = box.picked(), box.link.isChecked()
            self._tx()
            n = import_file(self.doc, path, names)
            if link:
                self._link_to(path)
                _stamp_link(self.doc, path)
            self._rebuild()
            self.status.setText("%d lines read from %s" % (n, path))
            self.refresh()

        def _export(self, path=None, names=None, link=False):
            if path is None:

                box = _Pick(self, "Export Equations", "SWEqExportPick", all_rows(self.doc), "Export")
                if not box.exec():
                    return
                names, link = box.picked(), box.link.isChecked()
                path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Export Equations", "equations.txt", "Text (*.txt)")
            if path:
                export_file(self.doc, path, names)
                if link:
                    self._link_to(path)
                    _stamp_link(self.doc, path)
                self.status.setText("Exported to %s" % path)

        @_step
        def _browse_link(self, path=None):
            if path is None:
                path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Link to external file", self.link_path.text(),
                                                                 "Text (*.txt)")
            if path:
                self.link_path.setText(path)
                self.link_path.setVisible(True)
                self.link_browse.setVisible(True)
                self.link.blockSignals(True)
                self.link.setChecked(True)
                self.link.blockSignals(False)
                if os.path.isfile(path):
                    self._tx()
                    n = import_file(self.doc, path)
                    self._rebuild()
                    self.refresh()
                    self.status.setText("%d lines read from %s" % (n, path))
            return path

        def _link_toggled(self, on):
            if on and not self.link_path.text().strip():
                QtCore.QTimer.singleShot(0, lambda: self._browse_link() or self.link.setChecked(False))

        @_step
        def _angle_changed(self, units):
            self._tx()
            old = angle_units(self.doc)
            n = convert_angles(self.doc, old, units)
            meta = dict(self.doc.Meta)
            meta[META_ANGLE] = units
            self.doc.Meta = meta
            self._rebuild()
            self.refresh()
            self.status.setText("Trigonometric functions now take %s (%d equation(s) read again)" % (units.lower(), n))

        @_step
        def _solve_changed(self, on):
            self._tx()
            if not on and not dict(self.doc.Meta).get(META_ORDER):
                set_listed_order(self.doc, solve_order(self.doc))      # starts from the order they solve in now
            meta = dict(self.doc.Meta)
            meta[META_SOLVE] = "1" if on else "0"
            self.doc.Meta = meta
            # FreeCAD always solves in dependency order; listed order gives the same values for any
            # set of equations without loops, so both settings rebuild the same way. Off, Ordered View's rows are dragged.
            self._rebuild()
            self.refresh()
            self.status.setText("Equations are solved in %s order" % ("dependency" if on else "listed"))

        def accept(self):
            self._tx()
            linked = self.link_path.text().strip() if self.link.isChecked() else ""
            set_linked_file(self.doc, linked)
            if linked:
                try:
                    export_file(self.doc, linked)
                except OSError as error:
                    self.status.setText(str(error))
            meta = dict(self.doc.Meta)
            meta[META_ANGLE] = self.angle.currentText()
            self.doc.Meta = meta
            self._seal()
            self._unwatch()
            self.doc.recompute()
            self._fold()
            super().accept()

        def _fold(self):
            ""

            doc = self.doc
            n = sum(1 for _b, _a, edited in self._steps if edited)
            if n < 2 or self._foreign or n >= 20 or doc.UndoCount < n:
                return                        # one step already, or the list is no longer only ours: left as it is
            try:
                final = [(o.Name, o.TypeId, o.dumpContent()) for o in doc.Objects]
                meta = dict(doc.Meta)
            except Exception as _fw_err:
                _fw_log("equations.py:fold", _fw_err)
                return
            self._ours_busy = True
            try:
                for _k in range(n):
                    doc.undo()
                doc.openTransaction("Equations")
                names = set(n_ for n_, _t, _c in final)
                for o in list(doc.Objects):
                    if o.Name not in names:
                        try:
                            doc.removeObject(o.Name)
                        except Exception as _fw_err:
                            _fw_log("equations.py:fold remove", _fw_err)
                for name, kind, _c in final:
                    if doc.getObject(name) is None:
                        made = doc.addObject(kind, name)
                        if made.Name != name:
                            raise RuntimeError("could not make %s again" % name)
                for name, _t, content in final:
                    o = doc.getObject(name)
                    if o.dumpContent() != content:
                        o.restoreContent(content)
                doc.Meta = meta
                doc.recompute()
                doc.commitTransaction()
                App.closeActiveTransaction()
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: Equations: %s\n" % error)
                try:
                    if getattr(doc, "HasPendingTransaction", False):
                        doc.abortTransaction()
                    for _k in range(n):      # the box's own steps back, as they were
                        doc.redo()
                    doc.Meta = meta
                    doc.recompute()
                except Exception as _fw_err:
                    _fw_log("equations.py:fold back", _fw_err)
            finally:
                self._ours_busy = False

        def reject(self):
            doc = self.doc
            self._seal()
            undone = False
            self._unwatch()
            while self._steps and doc.UndoCount > 0:           # Cancel: every edit made in this box is undone
                if self._steps.pop()[2]:
                    doc.undo()
                    undone = True
                self._base = doc.UndoCount
            self._set_meta(self._meta0)
            if undone:
                # the undone edits must not come back with the document's own Redo: a transaction that changes something empties
                # it (adding and removing an object leaves nothing behind), and its own entry is stepped back into Redo, a no-op
                try:
                    doc.openTransaction("Equations")
                    doc.removeObject(doc.addObject("App::DocumentObject", "FwCancelMark").Name)
                    doc.commitTransaction()
                    App.closeActiveTransaction()
                    doc.undo()
                except Exception as _fw_err:
                    _fw_log("equations.py:cancel", _fw_err)
            doc.recompute()
            super().reject()

    class _Pick(QtWidgets.QDialog):
        """Import / Export Equations: the equations, each with its tick, and Link to file."""

        def __init__(self, parent, title, name, rows, action):
            super().__init__(parent)
            self.setObjectName(name)
            self.setWindowTitle(title)
            self.resize(560, 320)
            lay = QtWidgets.QVBoxLayout(self)
            self.tree = QtWidgets.QTreeWidget()
            self.tree.setObjectName(name + "List")
            self.tree.setRootIsDecorated(False)
            self.tree.setHeaderLabels(["Name", "Value / Equation", "Comments"])
            for nm, text, note in rows:
                it = QtWidgets.QTreeWidgetItem(['"%s"' % nm, "= " + text, note])
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Checked)
                it.setData(0, KIND, nm)
                self.tree.addTopLevelItem(it)
            for c in range(3):
                self.tree.resizeColumnToContents(c)
            self.tree.itemClicked.connect(self._clicked)
            lay.addWidget(self.tree, 1)
            self.link = QtWidgets.QCheckBox("Link to file")
            self.link.setObjectName(name + "Link")
            lay.addWidget(self.link)
            row = QtWidgets.QHBoxLayout()
            row.addStretch(1)
            for text, slot in ((action, self.accept), ("Cancel", self.reject)):
                b = QtWidgets.QPushButton(text)
                b.clicked.connect(lambda _c=False, slot=slot: slot())
                if text == action:
                    b.setDefault(True)
                row.addWidget(b)
            lay.addLayout(row)

        def _clicked(self, it, col):
            # a click anywhere on the row ticks it (not only on the small box)
            r = self.tree.visualItemRect(it)
            pos = self.tree.viewport().mapFromGlobal(QtGui.QCursor.pos())
            if col != 0 or pos.x() > r.left() + 22:
                it.setCheckState(0, Qt.Unchecked if it.checkState(0) == Qt.Checked else Qt.Checked)

        def picked(self):
            return [self.tree.topLevelItem(k).data(0, KIND) for k in range(self.tree.topLevelItemCount())
                    if self.tree.topLevelItem(k).checkState(0) == Qt.Checked]

    _OPEN = []

    def show(doc=None):
        box = EquationsDialog(doc)
        _OPEN[:] = [box]
        box.show()
        return box

    class _Cmd:
        def GetResources(self):
            return {"MenuText": "Equations...", "ToolTip": "The part's variables, equations and dimensions"}

        def IsActive(self):
            return App.ActiveDocument is not None

        def Activated(self):
            show()


def register():
    if Gui is None:
        return
    if not _PARK:
        _PARK.append(_ParkWatch())
        App.addDocumentObserver(_PARK[0])
    if "SWStyle_Equations" not in Gui.listCommands():
        Gui.addCommand("SWStyle_Equations", _Cmd())
    try:
        from . import restorehook
        restorehook.on_restored(reread_linked)       # an edited linked equations file is read when the part opens
    except Exception as _fw_err:
        _fw_log("equations.py:restorehook", _fw_err)
    try:
        from . import catalog
        cmd = catalog.BY_KEY.get("Equations")
        if cmd is not None and "SWStyle_Equations" not in cmd.natives:
            cmd.natives = ("SWStyle_Equations",) + tuple(cmd.natives)
            cmd.tip = "Global variables, equations and dimensions of the part."
    except Exception as _fw_err:
        _fw_log("equations.py:1389", _fw_err)
