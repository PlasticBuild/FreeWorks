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
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import drawings as D
from . import drawtables as DT

K = 25.4 / 96.0
LAST = []          # [(document name, table name, r0, c0, r1, c1)] the current cell / range (logical rows)
ASK = {}           # tests answer the dialogs here: "text", "width", "height", "size", "line", "kind"
ANCHOR_KINDS = (("Bill of Materials", "BOM"), ("Hole Table", "Hole"), ("Revision Table", "Revision"),
                ("General Table", "General"), ("Weld Table", "Weld"), ("Bend Table", "Bend"),
                ("Punch Table", "Punch"), ("Title Block Table", "TitleBlock"),
                ("Weldment Cut List", "CutList"))


# =========================================================================== geometry
def _flag(t, name):
    return bool(getattr(t, name, False))


def _set_flag(t, name, on, tip):
    if name not in t.PropertiesList:
        t.addProperty("App::PropertyBool", name, "FreeCAD", tip)
    setattr(t, name, bool(on))


def size(t):
    """(rows, columns) of the table, header first; a title row above the header (the revision table's
    REVISIONS) is not counted."""
    end = t.CellEnd
    return int(end[1:]) - DT.title_rows(t), DT.COLS.index(end[0]) + 1


def title_height(t):
    """The title row's height (spreadsheet units), 0 without one."""
    if not DT.title_rows(t):
        return 0.0
    try:
        return float(t.Source.getRowHeight("1"))
    except Exception:
        return 30.0


def widths(t):
    nr, nc = size(t)
    out = []
    for c in range(nc):
        try:
            out.append(float(t.Source.getColumnWidth(DT.COLS[c])))
        except Exception:
            out.append(100.0)
    return out


def heights(t):
    nr, nc = size(t)
    out = []
    top = DT.title_rows(t)
    for r in range(nr):
        try:
            out.append(float(t.Source.getRowHeight(str(r + 1 + top))))
        except Exception:
            out.append(30.0)
    return out


def box(t):
    """(left, top, width, height) of the table on the sheet (mm; TechDraw centres it on X, Y)."""
    k = K * float(getattr(t, "Scale", 1.0) or 1.0)
    w, h = sum(widths(t)) * k, (sum(heights(t)) + title_height(t)) * k
    x, y = float(t.X), float(t.Y)
    return x - w / 2, y + h / 2, w, h


def _physical(t, r):
    """A logical row (0 = header) to the spreadsheet's row (the header is last with Table Header Bottom)."""
    nr, _ = size(t)
    top = DT.title_rows(t)
    if _flag(t, "SWHeaderBottom"):
        return (nr - 1 if r == 0 else r - 1) + top
    return r + top


def _logical(t, r):
    nr, _ = size(t)
    r -= DT.title_rows(t)
    if r < 0:
        return 0                 # the title row belongs to the header
    if _flag(t, "SWHeaderBottom"):
        return 0 if r == nr - 1 else r + 1
    return r


def cell_at(t, p):
    """The (logical row, column) of table t under sheet point p, else None."""
    left, top, w, h = box(t)
    k = K * float(getattr(t, "Scale", 1.0) or 1.0)
    x, y = p[0] - left, top - p[1]
    if not (0 <= x <= w and 0 <= y <= h):
        return None
    c = 0
    acc = 0.0
    for c, cw in enumerate(widths(t)):
        acc += cw * k
        if x <= acc:
            break
    y -= title_height(t) * k
    if y < 0:
        return 0, c              # the title row (REVISIONS): the header's
    r = 0
    acc = 0.0
    for r, rh in enumerate(heights(t)):
        acc += rh * k
        if y <= acc:
            break
    return _logical(t, r + DT.title_rows(t)), c


def table_at(page, p):
    for t in reversed(list(page.Views)):
        if getattr(t, "SWTable", "") and t.TypeId == "TechDraw::DrawViewSpreadsheet":
            try:
                if cell_at(t, p) is not None:
                    return t
            except Exception:
                continue
    return None


def remember(page, p, extend=False):
    """A click at sheet point p: the cell under it becomes current (Shift: the range grows to it)."""
    t = table_at(page, p)
    if t is None:
        return None
    r, c = cell_at(t, p)
    if extend and LAST and LAST[0][:2] == (t.Document.Name, t.Name):
        _, _, r0, c0, _, _ = LAST[0]
        LAST[:] = [(t.Document.Name, t.Name, r0, c0, r, c)]
    else:
        LAST[:] = [(t.Document.Name, t.Name, r, c, r, c)]
    return t, r, c


def current():
    """(table, r0, c0, r1, c1) of the current cell / range (ordered), else None."""
    if not LAST:
        return None
    dn, tn, r0, c0, r1, c1 = LAST[0]
    try:
        t = App.getDocument(dn).getObject(tn)
    except Exception as _fw_err:
        _fw_log("drawtableedit.py:167", _fw_err)
        return None
    if t is None:
        return None
    nr, nc = size(t)
    r0, r1 = sorted((min(r0, nr - 1), min(r1, nr - 1)))
    c0, c1 = sorted((min(c0, nc - 1), min(c1, nc - 1)))
    return t, r0, c0, r1, c1


def set_current(t, r, c, r1=None, c1=None):
    LAST[:] = [(t.Document.Name, t.Name, r, c, r if r1 is None else r1, c if c1 is None else c1)]


# =========================================================================== rewriting a table
def merges(t):
    return list(getattr(t, "SWMerges", []) or [])


def _store_merges(t, ranges):
    if "SWMerges" not in t.PropertiesList:
        t.addProperty("App::PropertyStringList", "SWMerges", "FreeCAD", "merged cells r0,c0,r1,c1 (logical)")
    t.SWMerges = ranges


FORMAT = "SWCellFormats"       # {"r,c": {"style": "bold|italic|underline", "align": "left"}} (logical rows)


def formats(t):
    try:
        return json.loads(getattr(t, FORMAT, "") or "{}")
    except Exception:
        return {}


def _store_formats(t, fm):
    if FORMAT not in t.PropertiesList:
        t.addProperty("App::PropertyString", FORMAT, "FreeCAD", "cell text formats (bold, italic, alignment)")
    setattr(t, FORMAT, json.dumps(fm))


def _shift_formats(t, fn):
    lk = cell_locks(t)
    if lk and any("|" not in k for k in lk):       # positional locks (not a BOM body) move with their cell
        out = {}
        for key, v in lk.items():
            if "|" in key:
                out[key] = v
                continue
            r, c = [int(x) for x in key.split(",")]
            to = fn(r, c)
            if to is not None:
                out["%d,%d" % to] = v
        _store_json(t, CELL_LOCKS, out, "locked cells and the text they keep")
    fm = formats(t)
    if not fm:
        return
    out = {}
    for key, f in fm.items():
        r, c = [int(v) for v in key.split(",")]
        to = fn(r, c)
        if to is not None:
            out["%d,%d" % to] = f
    _store_formats(t, out)


STYLES = ("bold", "italic", "underline")      # the spreadsheet's own cell styles; strikeout is drawn in the text


def set_format(t, cells, style=None, align=None, valign=None, strike=None, color=None):
    """The text format of cells [(r, c)]: style "bold|italic|underline" ("" plain), align left/center/right,
    valign top/vcenter/bottom, strike True/False (Strikeout), color (r, g, b) 0-255 or "" (the table's)."""
    fm = formats(t)
    for r, c in cells:
        f = fm.setdefault("%d,%d" % (r, c), {})
        if style is not None:
            f["style"] = "|".join(x for x in style.split("|") if x in STYLES)
        if align is not None:
            f["align"] = align
        if valign is not None:
            f["valign"] = valign
        if strike is not None:
            f["strike"] = bool(strike)
        if color is not None:
            f["color"] = list(color) if color else ""
    _store_formats(t, fm)
    apply_formats(t)
    t.Document.recompute()


def cell_format(t, r, c):
    """(style, align) a cell shows: its own format, else the table's (bold centred header, left body)."""
    f = formats(t).get("%d,%d" % (r, c), {})
    style = f.get("style", "bold" if r == 0 else "")
    align = f.get("align", "center" if r == 0 else "left")
    return style, align


def cell_extra(t, r, c):
    """(valign, strike, color) a cell shows: top/vcenter/bottom, Strikeout, (r, g, b) or None."""
    f = formats(t).get("%d,%d" % (r, c), {})
    col = f.get("color") or None
    return f.get("valign", "vcenter"), bool(f.get("strike", False)), tuple(col) if col else None


def apply_formats(t):
    fm = formats(t)
    if not fm:
        return
    sheet = t.Source
    nr, _ = size(t)
    for key, f in fm.items():
        r, c = [int(v) for v in key.split(",")]
        if r >= nr:
            continue
        cell = DT._cell(c, _physical_n(t, r, nr))
        try:
            if "style" in f:
                sheet.setStyle(cell, f["style"] or "")
            if "align" in f or "valign" in f:
                sheet.setAlignment(cell, f.get("align", "center" if r == 0 else "left") + "|" +
                                   f.get("valign", "vcenter"))
            if "color" in f:
                col = f["color"]
                sheet.setForeground(cell, (col[0] / 255.0, col[1] / 255.0, col[2] / 255.0, 1.0) if col
                                    else (0.0, 0.0, 0.0, 1.0))
            if "strike" in f:
                txt = sheet.getContents(cell) or ""
                lead = "'" if txt.startswith("'") else ""
                body = DT.unstrike(txt[len(lead):])
                new = lead + (DT.strike(body) if f["strike"] and body else body)
                if new != txt:
                    sheet.set(cell, new if lead or not new else "'" + new)
        except Exception as _fw_err:
            _fw_log("drawtableedit.py:299", _fw_err)
    sheet.recompute()


def write(t, rows, col_widths=None, row_heights=None, merged=None):
    """Rows (logical order, header first) into the table, with its column widths, row heights and merges."""
    col_widths = col_widths if col_widths is not None else widths(t)
    phys = rows[1:] + rows[:1] if _flag(t, "SWHeaderBottom") and rows else rows
    DT.fill(t.Source, phys, col_widths, DT.title_of(t))
    sheet = t.Source
    if _flag(t, "SWHeaderBottom") and rows:
        top = DT.title_rows(t)
        last = len(rows) - 1 + top
        if top:                      # the header went below: the first table row is a plain row now
            try:
                for c in range(len(rows[0])):
                    sheet.setStyle(DT._cell(c, top), "")
                    sheet.setAlignment(DT._cell(c, top), "left")
            except Exception as _fw_err:
                _fw_log("drawtableedit.py:title header bottom", _fw_err)
        for c in range(len(rows[0])):
            try:
                sheet.setStyle(DT._cell(c, 0), "")
                sheet.setAlignment(DT._cell(c, 0), "left")
                sheet.setStyle(DT._cell(c, last), "bold")
                sheet.setAlignment(DT._cell(c, last), "center")
            except Exception as _fw_err:
                _fw_log("drawtableedit.py:318", _fw_err)
    if row_heights is not None:
        for r, h in enumerate(row_heights):
            try:
                sheet.setRowHeight(str(_physical_n(t, r, len(rows)) + 1), int(round(h)))
            except Exception as _fw_err:
                _fw_log("drawtableedit.py:324", _fw_err)
    DT._span(t, rows)
    if merged is None:
        merged = merges(t)
    keep = []
    nr, nc = len(rows), max([len(r) for r in rows] or [1])
    for m in merged:
        r0, c0, r1, c1 = [int(v) for v in m.split(",")]
        if r1 >= nr or c1 >= nc or (r0, c0) == (r1, c1):
            continue
        p0, p1 = sorted((_physical_n(t, r0, nr), _physical_n(t, r1, nr)))
        try:
            if p0 != p1 and c0 != c1:
                # TechDraw 1.1 draws a merge over rows and columns too big (it adds a column and a row):
                # merged row by row instead, so the block keeps its size (its row lines show inside)
                for p in range(p0, p1 + 1):
                    sheet.mergeCells("%s:%s" % (DT._cell(c0, p), DT._cell(c1, p)))
            else:
                sheet.mergeCells("%s:%s" % (DT._cell(c0, p0), DT._cell(c1, p1)))
            keep.append(m)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: merge %s: %s\n" % (m, error))
    _store_merges(t, keep)
    apply_formats(t)
    sheet.recompute()
    t.Document.recompute()


def _physical_n(t, r, nr):
    top = DT.title_rows(t)
    if _flag(t, "SWHeaderBottom"):
        return (nr - 1 if r == 0 else r - 1) + top
    return r + top


def rows(t):
    return DT.rows_of(t)


def _row_heights(t):
    """Logical-order row heights."""
    hs = heights(t)
    if _flag(t, "SWHeaderBottom") and hs:
        return hs[-1:] + hs[:-1]
    return hs


def _shift_merges(t, fn):
    out = []
    for m in merges(t):
        v = fn(*[int(x) for x in m.split(",")])
        if v is not None:
            out.append(",".join(str(x) for x in v))
    return out


# =========================================================================== operations
def _bom_columns(t, change):
    """A BOM's column list follows its columns (inserted ones are User Defined until a Column type is set)."""
    if getattr(t, "SWTable", "") != "BOM":
        return
    cols = DT.columns_of(t)
    change(cols)
    DT.store_columns(t, cols)


def insert_column(t, c, right=True):
    rs = rows(t)
    at = c + 1 if right else c
    for row in rs:
        row.insert(at, "")
    ws = widths(t)
    ws.insert(at, ws[c] if ws else 100.0)
    m = _shift_merges(t, lambda r0, c0, r1, c1: (r0, c0 + (c0 >= at), r1, c1 + (c1 >= at)))
    _bom_columns(t, lambda cols: cols.insert(at, {"type": "User Defined", "title": ""}))
    _shift_formats(t, lambda r, cc: (r, cc + (cc >= at)))
    write(t, rs, ws, _row_heights(t), m)
    return at


def insert_row(t, r, above=False):
    rs = rows(t)
    at = r if above else r + 1
    at = max(at, 1)                     # never above the header
    rs.insert(at, [""] * len(rs[0]))
    hs = _row_heights(t)
    hs.insert(at, hs[min(r, len(hs) - 1)] if hs else 30.0)
    m = _shift_merges(t, lambda r0, c0, r1, c1: (r0 + (r0 >= at), c0, r1 + (r1 >= at), c1))
    _shift_formats(t, lambda rr, cc: (rr + (rr >= at), cc))
    write(t, rs, None, hs, m)
    return at


def delete_column(t, c):
    rs = rows(t)
    if len(rs[0]) <= 1:
        return delete_table(t)
    for row in rs:
        del row[c]
    ws = widths(t)
    del ws[c]
    m = _shift_merges(t, lambda r0, c0, r1, c1: None if c0 <= c <= c1 else
                      (r0, c0 - (c0 > c), r1, c1 - (c1 > c)))
    _bom_columns(t, lambda cols: cols.pop(c) if c < len(cols) else None)
    _shift_formats(t, lambda r, cc: None if cc == c else (r, cc - (cc > c)))
    write(t, rs, ws, _row_heights(t), m)



# sorted away, so the release row stays while later revisions come and go
LOCK_FIRST = "SWRevLockFirst"


def first_row_locked(t, r=1):
    return r == 1 and getattr(t, "SWTable", "") == "Revision" and bool(getattr(t, LOCK_FIRST, False))


def lock_first_row(t, on=None):
    """Lock First Row (revision table right-click, or the Revision Table PM's Options): on/off (None: toggle)."""
    if on is None:
        on = not bool(getattr(t, LOCK_FIRST, False))
    if LOCK_FIRST not in t.PropertiesList:
        t.addProperty("App::PropertyBool", LOCK_FIRST, "FreeCAD", "Revision Table: Lock First Row")
    setattr(t, LOCK_FIRST, bool(on))
    t.Document.recompute()
    return bool(on)


def delete_row(t, r):
    rs = rows(t)
    if r == 0 or len(rs) <= 1:
        return False                    # the header row stays (Delete > Table removes all)
    if first_row_locked(t, r):
        _locked_message()
        return False
    del rs[r]
    hs = _row_heights(t)
    del hs[r]
    m = _shift_merges(t, lambda r0, c0, r1, c1: None if r0 <= r <= r1 else
                      (r0 - (r0 > r), c0, r1 - (r1 > r), c1))
    _shift_formats(t, lambda rr, cc: None if rr == r else (rr - (rr > r), cc))
    write(t, rs, None, hs, m)
    return True


def delete_table(t):
    doc = t.Document
    sheet = t.Source
    for o in list(doc.Objects):
        if getattr(o, "SWTagOf", "") == t.Name:
            doc.removeObject(o.Name)
    doc.removeObject(t.Name)
    if sheet is not None and not sheet.InList:
        doc.removeObject(sheet.Name)
    LAST[:] = []
    doc.recompute()
    return True


def merge_cells(t, r0, c0, r1, c1):
    if (r0, c0) == (r1, c1):
        return False
    rs = rows(t)
    text = " ".join(v for row in rs[r0:r1 + 1] for v in row[c0:c1 + 1] if v)
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            rs[r][c] = ""
    rs[r0][c0] = text
    m = [x for x in merges(t) if not _overlaps(x, r0, c0, r1, c1)] + ["%d,%d,%d,%d" % (r0, c0, r1, c1)]
    write(t, rs, None, _row_heights(t), m)
    return True


def _overlaps(m, r0, c0, r1, c1):
    a0, b0, a1, b1 = [int(v) for v in m.split(",")]
    return not (a1 < r0 or a0 > r1 or b1 < c0 or b0 > c1)


def merged_at(t, r, c):
    for m in merges(t):
        a0, b0, a1, b1 = [int(v) for v in m.split(",")]
        if a0 <= r <= a1 and b0 <= c <= b1:
            return m
    return None


def unmerge_cell(t, r, c):
    m = merged_at(t, r, c)
    if m is None:
        return False
    write(t, rows(t), None, _row_heights(t), [x for x in merges(t) if x != m])
    return True


def _key(v):
    try:
        return (0, float(v), "")
    except ValueError:
        return (1, 0.0, v.lower())


def sort_rows(t, c, ascending=True):
    rs = rows(t)
    keep = 2 if first_row_locked(t) and len(rs) > 1 else 1     # a locked first row stays first
    body = sorted(rs[keep:], key=lambda row: _key(row[c] if c < len(row) else ""), reverse=not ascending)
    write(t, rs[:keep] + body, None, None, [])
    return True


# =========================================================================== Hide / Show, Sort... (BOM)
def _json(t, name, default):
    try:
        return json.loads(getattr(t, name, "") or "") if getattr(t, name, "") else default
    except Exception:
        return default


def _set_json(t, name, value, tip):
    if name not in t.PropertiesList:
        t.addProperty("App::PropertyString", name, "FreeCAD", tip)
    setattr(t, name, json.dumps(value))


def _is_bom(t):
    return getattr(t, "SWTable", "") == "BOM"


def _pn_col(t, rs):
    if _is_bom(t):
        i = DT._col_index(DT.columns_of(t), "Part Number")
        if i is not None:
            return i
    return None


def hide_column(t, c):
    """Hide > Column: the column goes from the sheet; Show > Hidden Columns brings it back where it was."""
    rs = rows(t)
    if len(rs[0]) <= 1:
        return False
    keep = {"at": c, "width": widths(t)[c], "cells": [r[c] if c < len(r) else "" for r in rs]}
    if _is_bom(t):
        cols = DT.columns_of(t)
        if c < len(cols):
            keep["spec"] = cols[c]
    hidden = _json(t, "SWHiddenColumns", [])
    hidden.append(keep)
    _set_json(t, "SWHiddenColumns", hidden, "Hide > Column: the hidden columns")
    delete_column(t, c)
    return True


def show_columns(t):
    """Show > Hidden Columns: every hidden column back at its place (last hidden first back)."""
    hidden = _json(t, "SWHiddenColumns", [])
    if not hidden:
        return 0
    for h in reversed(hidden):
        rs = rows(t)
        at = min(int(h.get("at", 0)), len(rs[0]))
        cells = h.get("cells", [])
        for i, row in enumerate(rs):
            row.insert(at, cells[i] if i < len(cells) else "")
        ws = widths(t)
        ws.insert(at, float(h.get("width", 100.0)))
        m = _shift_merges(t, lambda r0, c0, r1, c1: (r0, c0 + (c0 >= at), r1, c1 + (c1 >= at)))
        if "spec" in h:
            _bom_columns(t, lambda cols: cols.insert(at, h["spec"]))
        _shift_formats(t, lambda r, cc: (r, cc + (cc >= at)))
        write(t, rs, ws, _row_heights(t), m)
    _set_json(t, "SWHiddenColumns", [], "Hide > Column: the hidden columns")
    if _is_bom(t):
        DT.update_table(t)
    return len(hidden)


def hide_row(t, r):
    """Hide > Row: a BOM keeps the part hidden through updates (by its part number)."""
    rs = rows(t)
    if r == 0 or r >= len(rs) or first_row_locked(t, r):
        return False
    hidden = _json(t, "SWHiddenRows", [])
    pn = _pn_col(t, rs)
    hidden.append({"at": r, "cells": rs[r], "part": rs[r][pn] if pn is not None and pn < len(rs[r]) else None})
    _set_json(t, "SWHiddenRows", hidden, "Hide > Row: the hidden rows")
    delete_row(t, r)
    return True


def show_rows(t):
    """Show > Hidden Rows."""
    hidden = _json(t, "SWHiddenRows", [])
    if not hidden:
        return 0
    _set_json(t, "SWHiddenRows", [], "Hide > Row: the hidden rows")
    if _is_bom(t) and getattr(t, "SWBomView", ""):
        DT.update_table(t)
        return len(hidden)
    for h in reversed(hidden):
        rs = rows(t)
        at = max(1, min(int(h.get("at", 1)), len(rs)))
        cells = list(h.get("cells", []))
        cells = (cells + [""] * len(rs[0]))[:len(rs[0])]
        rs.insert(at, cells)
        hs = _row_heights(t)
        hs.insert(at, hs[-1] if hs else 30.0)
        m = _shift_merges(t, lambda r0, c0, r1, c1: (r0 + (r0 >= at), c0, r1 + (r1 >= at), c1))
        _shift_formats(t, lambda rr, cc: (rr + (rr >= at), cc))
        write(t, rs, None, hs, m)
    return len(hidden)


SORT_KEY = "SWBomSort"


def sort_table(t, keys, keep_numbers=True):
    """Sort...: keys [(column title, ascending)], first key first. A BOM keeps the sort through updates, and
    unless Do not change item numbers is on its item numbers run in the new order."""
    rs = rows(t)
    if _is_bom(t):
        _set_json(t, SORT_KEY, {"keys": [[k, bool(a)] for k, a in keys], "keep": bool(keep_numbers)},
                  "Sort...: the BOM's sort")
        DT.update_table(t)
        return True
    body = _sorted(rs[0], rs[1:], keys)
    write(t, rs[:1] + body, None, None, [])
    return True


def _sorted(head, body, keys):
    titles = [h.strip().lower() for h in head]
    for title, asc in reversed([k for k in keys if k and k[0]]):
        if title.strip().lower() not in titles:
            continue
        c = titles.index(title.strip().lower())
        body = sorted(body, key=lambda row: _key(row[c] if c < len(row) else ""), reverse=not asc)
    return body


def bom_view_rows(t, rs):
    """A BOM's rows as made again from the model, with its hidden rows left out and its Sort... applied
    (DT.ROW_KEYS follows the rows)."""
    if not rs:
        return rs
    keys = list(DT.ROW_KEYS) + [""] * max(0, len(rs) - 1 - len(DT.ROW_KEYS))
    pairs = list(zip(rs[1:], keys))
    pn = _pn_col(t, rs)
    gone = {h.get("part") for h in _json(t, "SWHiddenRows", []) if h.get("part")}
    if gone and pn is not None:
        pairs = [(r, k) for r, k in pairs if DT.unstrike(r[pn] if pn < len(r) else "") not in gone]
    srt = _json(t, SORT_KEY, None)
    if srt and srt.get("keys"):
        idx = {id(r): k for r, k in pairs}
        body = _sorted(rs[0], [r for r, _ in pairs], srt["keys"])
        pairs = [(r, idx[id(r)]) for r in body]
        item = DT._col_index(DT.columns_of(t), "Item No.")
        if not srt.get("keep", True) and item is not None and getattr(t, "SWBomType", "") != "Indented":
            n, step = int(getattr(t, "SWBomStart", 1) or 1), int(getattr(t, "SWBomStep", 1) or 1)
            for r, _ in pairs:
                if item < len(r) and r[item]:
                    r[item] = str(n)
                    n += step
    DT.ROW_KEYS[:] = [k for _, k in pairs]
    return rs[:1] + [r for r, _ in pairs]


class SortDialog(QtWidgets.QDialog):
    ""


    def __init__(self, t, column=0, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWTableSort")
        self.setWindowTitle("Sort")
        lay = QtWidgets.QVBoxLayout(self)
        head = [h for h in rows(t)[0]]
        self.levels = []
        for n, lab in enumerate(("Sort by", "Then by", "Then by")):
            box = QtWidgets.QGroupBox(lab, self)
            g = QtWidgets.QHBoxLayout(box)
            combo = QtWidgets.QComboBox(box)
            combo.setObjectName("SWSortKey%d" % n)
            combo.addItems(([] if n == 0 else [""]) + head)
            if n == 0 and column < len(head):
                combo.setCurrentIndex(column)
            asc = QtWidgets.QRadioButton("Ascending", box)
            asc.setObjectName("SWSortAsc%d" % n)
            desc = QtWidgets.QRadioButton("Descending", box)
            desc.setObjectName("SWSortDesc%d" % n)
            asc.setChecked(True)
            for x in (combo, asc, desc):
                g.addWidget(x)
            lay.addWidget(box)
            self.levels.append((combo, asc))
        self.keep = QtWidgets.QCheckBox("Do not change item numbers", self)
        self.keep.setObjectName("SWSortKeepNumbers")
        self.keep.setChecked(False)
        self.keep.setVisible(_is_bom(t))
        lay.addWidget(self.keep)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def keys(self):
        return [(c.currentText(), a.isChecked()) for c, a in self.levels if c.currentText()]


def _place_beside(t, new):
    left, top, w, h = box(t)
    nl, nt, nw, nh = box(new)
    new.X = left + w + 5.0 + nw / 2
    new.Y = float(t.Y)


def _copy_table(t, rs, ws, label):
    page = next((o for o in t.InList if o.TypeId == "TechDraw::DrawPage"), None)
    new = DT.make_table(page, rs, (float(t.X), float(t.Y)), label, t.SWTable, ws)
    for name in ("SWBoxBorder", "SWGridBorder"):
        if name in t.PropertiesList:
            DT.set_border(new, getattr(t, "SWBoxBorder", 0.35), getattr(t, "SWGridBorder", 0.18))
            break
    for prop in ("TextSize", "LineWidth", "Font", "TextColor", "Scale"):
        try:
            setattr(new, prop, getattr(t, prop))
        except Exception as _fw_err:
            _fw_log("drawtableedit.py:749", _fw_err)
    if "SWSplitOf" not in new.PropertiesList:
        new.addProperty("App::PropertyString", "SWSplitOf", "FreeCAD", "the table this was split from")
    new.SWSplitOf = t.Name
    new.Document.recompute()
    _place_beside(t, new)
    return new


def split(t, mode, r, c):
    """mode: "Horizontally Above" / "Horizontally Below" (at row r), "Vertically Left" / "Vertically Right" (at
    column c). The part split off goes into a new table beside it."""
    rs = rows(t)
    ws = widths(t)
    if mode.startswith("Horizontally"):
        cut = r if mode.endswith("Above") else r + 1
        cut = max(1, cut)
        if cut >= len(rs):
            return None
        keep, rest = rs[:cut], rs[:1] + rs[cut:]
        write(t, keep, ws, None, [m for m in merges(t) if int(m.split(",")[2]) < cut])
        return _copy_table(t, rest, ws, t.Label + " (split)")
    cut = c if mode.endswith("Left") else c + 1
    if cut <= 0 or cut >= len(rs[0]):
        return None
    keep = [row[:cut] for row in rs]
    rest = [row[cut:] for row in rs]
    write(t, keep, ws[:cut], None, [m for m in merges(t) if int(m.split(",")[3]) < cut])
    return _copy_table(t, rest, ws[cut:], t.Label + " (split)")


def merge_tables(tables):
    """The tables (one kind) become the first one: rows appended (a repeated header is dropped)."""
    tables = [t for t in tables if getattr(t, "SWTable", "")]
    if len(tables) < 2:
        return None
    first = tables[0]
    rs = rows(first)
    for t in tables[1:]:
        if t.SWTable != first.SWTable:
            continue
        more = rows(t)
        if more and more[0] == rs[0]:
            more = more[1:]
        n = len(rs[0])
        rs += [(row + [""] * n)[:n] for row in more]
        delete_table(t)
    write(first, rs, None, None, merges(first))
    return first


def move_column(t, c, left=True):
    rs = rows(t)
    d = c - 1 if left else c + 1
    if d < 0 or d >= len(rs[0]):
        return False
    for row in rs:
        row[c], row[d] = row[d], row[c]
    ws = widths(t)
    ws[c], ws[d] = ws[d], ws[c]

    def swap(cols):
        if max(c, d) < len(cols):
            cols[c], cols[d] = cols[d], cols[c]
    _bom_columns(t, swap)
    _shift_formats(t, lambda r, cc: (r, d if cc == c else c if cc == d else cc))
    write(t, rs, ws, _row_heights(t), [])
    return True


def column_width(t, c, mm):
    t.Source.setColumnWidth(DT.COLS[c], int(round(mm / (K * float(t.Scale or 1.0)))))
    _remember_locks(t)
    t.Source.recompute()
    t.Document.recompute()


def row_height(t, r, mm):
    t.Source.setRowHeight(str(_physical(t, r) + 1), int(round(mm / (K * float(t.Scale or 1.0)))))
    _remember_locks(t)
    t.Source.recompute()
    t.Document.recompute()


def entire_table(t, text_size=None, line_width=None):
    if text_size:
        t.TextSize = float(text_size) / (K * float(t.Scale or 1.0))      # mm in (look-audit tablefont-1121)
    if line_width:
        t.LineWidth = float(line_width)
    t.Document.recompute()


def _remember_locks(t):
    if _flag(t, "SWLockColumnWidth"):
        _store(t, "SWLockedWidths", widths(t))
    if _flag(t, "SWLockRowHeight"):
        _store(t, "SWLockedHeights", _row_heights(t))


def _store(t, name, vals):
    if name not in t.PropertiesList:
        t.addProperty("App::PropertyString", name, "FreeCAD", "locked sizes")
    setattr(t, name, json.dumps(vals))


def lock(t, what, on):
    name = "SWLockColumnWidth" if what == "width" else "SWLockRowHeight"
    _set_flag(t, name, on, "Lock Column Width" if what == "width" else "Lock Row Height")
    _remember_locks(t)


def keep_locks(t):
    """After a table update (drawtables.update_table): the locked widths / heights back."""
    try:
        if _flag(t, "SWLockColumnWidth") and getattr(t, "SWLockedWidths", ""):
            for c, w in enumerate(json.loads(t.SWLockedWidths)):
                if c < size(t)[1]:
                    t.Source.setColumnWidth(DT.COLS[c], int(round(w)))
        if _flag(t, "SWLockRowHeight") and getattr(t, "SWLockedHeights", ""):
            for r, h in enumerate(json.loads(t.SWLockedHeights)):
                if r < size(t)[0]:
                    t.Source.setRowHeight(str(_physical(t, r) + 1), int(round(h)))
        t.Source.recompute()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: table locks: %s\n" % error)


def header(t, bottom):
    rs = rows(t)
    hs = _row_heights(t)
    m = merges(t)
    _set_flag(t, "SWHeaderBottom", bottom, "Table Header Bottom")
    write(t, rs, None, hs, m)


def edit_cell(t, r, c, text):
    """A cell's text typed in. A locked cell is left as it is (False). On a BOM, a value typed over one that
    the model gives (item number, part number, quantity, a property) is an overridden value: an update keeps
    it, it shows in the overridden colour and Restore Original Value brings the model's value back."""
    rs = rows(t)
    if is_locked(t, r, c, rs) or first_row_locked(t, r):
        _locked_message()
        return False
    if r > 0 and _driven(t, c, rs):
        ov = overrides(t)
        k = cell_key(t, r, c, rs)
        o = ov.get(k)
        original = o["original"] if o else rs[r][c]
        if text == original:
            ov.pop(k, None)
        else:
            ov[k] = {"value": text, "original": original}
        _store_json(t, OVERRIDES, ov, "BOM cells typed over the model's values")
    rs[r][c] = text
    write(t, rs, None, _row_heights(t), merges(t))
    paint_overrides(t)
    if _is_bom(t):
        try:
            from . import drawannot
            drawannot.refresh_balloons(t.Document)      # an item number typed in: its balloons follow
        except Exception as _fw_err:
            _fw_log("drawtableedit.py:910", _fw_err)


# --------------------------------------------------------------------------- overridden and locked cells
OVERRIDES = "SWBomOverrides"   # {"column title|part key": {"value": typed, "original": the model's}}
CELL_LOCKS = "SWLockedCells"   # {"column title|part key" (BOM body) or "r,c": the text kept}
OVERRIDE_COLOR = (0, 0, 255)


def _store_json(t, name, value, doc):
    if name not in t.PropertiesList:
        t.addProperty("App::PropertyString", name, "FreeCAD", doc)
    setattr(t, name, json.dumps(value))


def overrides(t):
    return _json(t, OVERRIDES, {}) or {}


def cell_locks(t):
    return _json(t, CELL_LOCKS, {}) or {}


def cell_key(t, r, c, rs=None):
    """A cell's key that an update, a sort or a hidden row does not move: on a BOM body, its column's title
    and its row's part; else "r,c"."""
    rs = rs if rs is not None else rows(t)
    if not _is_bom(t) or r <= 0 or not rs or r >= len(rs) or c >= len(rs[0]):
        return "%d,%d" % (r, c)
    keys = list(getattr(t, "SWBomRowKeys", []) or [])
    k = keys[r - 1] if r - 1 < len(keys) else ""
    if not k:
        pn = _pn_col(t, rs)
        k = ("pn:" + DT.unstrike(rs[r][pn])) if pn is not None and pn < len(rs[r]) else "row:%d" % r
    return "%s|%s" % (rs[0][c], k)


def _driven(t, c, rs):
    """A BOM column whose values come from the model (not a User Defined column)."""
    if not _is_bom(t) or not rs:
        return False
    cols = DT.columns_of(t) if getattr(t, "SWBomColumns", "") else None
    if cols and len(cols) == len(rs[0]) and c < len(cols):
        return cols[c].get("type") != "User Defined"
    return True


def is_overridden(t, r, c, rs=None):
    return r > 0 and cell_key(t, r, c, rs) in overrides(t)


def is_locked(t, r, c, rs=None):
    return cell_key(t, r, c, rs) in cell_locks(t)


def _locked_message():
    try:
        Gui.getMainWindow().statusBar().showMessage("The cell is locked. Unlock it to edit it.", 4000)
    except Exception as _fw_err:
        _fw_log("drawtableedit.py:969", _fw_err)


def _cells(r0, c0, r1, c1):
    return [(r, c) for r in range(min(r0, r1), max(r0, r1) + 1) for c in range(min(c0, c1), max(c0, c1) + 1)]


def lock_cells(t, cells, on=True):
    """Lock Cells / Unlock Cells: a locked cell can't be edited and an update keeps its text."""
    rs = rows(t)
    lk = cell_locks(t)
    for r, c in cells:
        if r < len(rs) and c < len(rs[r]):
            k = cell_key(t, r, c, rs)
            if on:
                lk[k] = rs[r][c]
            else:
                lk.pop(k, None)
    _store_json(t, CELL_LOCKS, lk, "locked cells and the text they keep")
    t.Document.recompute()


def restore_original(t, cells):
    """Restore Original Value: the model's value back in the overridden cells."""
    rs = rows(t)
    ov = overrides(t)
    done = False
    for r, c in cells:
        k = cell_key(t, r, c, rs)
        if k in ov and not is_locked(t, r, c, rs):
            rs[r][c] = ov.pop(k)["original"]
            done = True
    if not done:
        return False
    _store_json(t, OVERRIDES, ov, "BOM cells typed over the model's values")
    write(t, rs, None, _row_heights(t), merges(t))
    paint_overrides(t)
    try:
        from . import drawannot
        drawannot.refresh_balloons(t.Document)
    except Exception as _fw_err:
        _fw_log("drawtableedit.py:1010", _fw_err)
    t.Document.recompute()
    return True


def keep_overrides(t):
    """After an update (drawtables.update_table): locked cells keep their text and overridden values stay,
    each remembering the model's new value for Restore Original Value."""
    ov, lk = overrides(t), cell_locks(t)
    if not ov and not lk:
        return False
    rs = rows(t)
    changed = False
    for r in range(1, len(rs)):
        for c in range(len(rs[r])):
            k = cell_key(t, r, c, rs)
            if k in lk and rs[r][c] != lk[k]:
                if _driven(t, c, rs) and k not in ov:
                    ov[k] = {"value": lk[k], "original": rs[r][c]}
                else:
                    rs[r][c] = lk[k]
                    changed = True
            if k in ov:
                o = ov[k]
                if rs[r][c] != o["value"]:
                    o["original"] = rs[r][c]
                    rs[r][c] = o["value"]
                    changed = True
    if ov:
        _store_json(t, OVERRIDES, ov, "BOM cells typed over the model's values")
    if changed:
        write(t, rs, None, _row_heights(t), merges(t))
    paint_overrides(t)
    return changed


def paint_overrides(t):
    """Overridden BOM values in the overridden colour (a colour set on the cell itself wins)."""
    if OVERRIDES not in t.PropertiesList:
        return
    ov = overrides(t)
    fm = formats(t)
    rs = rows(t)
    nr = len(rs)
    sheet = t.Source
    for r in range(1, nr):
        for c in range(len(rs[r])):
            if fm.get("%d,%d" % (r, c), {}).get("color"):
                continue
            col = OVERRIDE_COLOR if cell_key(t, r, c, rs) in ov else (0, 0, 0)
            try:
                sheet.setForeground(DT._cell(c, _physical_n(t, r, nr)),
                                    (col[0] / 255.0, col[1] / 255.0, col[2] / 255.0, 1.0))
            except Exception as _fw_err:
                _fw_log("drawtableedit.py:1064", _fw_err)
    try:
        sheet.recompute()
    except Exception as _fw_err:
        _fw_log("drawtableedit.py:1068", _fw_err)


CORNERS = ("Top Left", "Top Right", "Bottom Left", "Bottom Right")


def corner_point(t, corner):
    left, top, w, h = box(t)
    return (left + (w if "Right" in corner else 0.0), top - (h if "Bottom" in corner else 0.0))


def format_points(page):
    """The sheet format's line ends and corners (sheet mm, y up), from the template's SVG: <line>, <rect>,
    <polyline>/<polygon> and simple M/L/H/V <path> data."""
    import re
    import xml.etree.ElementTree as ET
    tmpl = getattr(page, "Template", None)
    path = getattr(tmpl, "PageResult", "") or getattr(tmpl, "Template", "") if tmpl is not None else ""
    try:
        root = ET.parse(path).getroot()
    except Exception as _fw_err:
        _fw_log("drawtableedit.py:1091", _fw_err)
        return []
    h = D.sheet_size(page)[1]
    pts = []

    def num(v):
        try:
            return float(re.sub(r"[a-z%]+$", "", str(v)))
        except Exception as _fw_err:
            _fw_log("drawtableedit.py:1100", _fw_err)
            return None

    def add(x, y):
        if x is not None and y is not None:
            pts.append((x, h - y))
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if el.get("transform"):
            continue                      # moved geometry: left out rather than placed wrong
        if tag == "line":
            add(num(el.get("x1")), num(el.get("y1")))
            add(num(el.get("x2")), num(el.get("y2")))
        elif tag == "rect":
            x, y, w, hh = (num(el.get(k, 0)) for k in ("x", "y", "width", "height"))
            if None not in (x, y, w, hh):
                for px, py in ((x, y), (x + w, y), (x, y + hh), (x + w, y + hh)):
                    add(px, py)
        elif tag in ("polyline", "polygon"):
            v = [float(q) for q in re.findall(r"-?\d+(?:\.\d+)?", el.get("points", ""))]
            for i in range(0, len(v) - 1, 2):
                add(v[i], v[i + 1])
        elif tag == "path":
            x = y = 0.0
            for cmd, args in re.findall(r"([MLHVmlhvZz])([^MLHVmlhvZzCcSsQqTtAa]*)", el.get("d", "")):
                v = [float(q) for q in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", args)]
                if cmd in "ML":
                    for i in range(0, len(v) - 1, 2):
                        x, y = v[i], v[i + 1]
                        add(x, y)
                elif cmd in "ml":
                    for i in range(0, len(v) - 1, 2):
                        x, y = x + v[i], y + v[i + 1]
                        add(x, y)
                elif cmd in "Hh":
                    for q in v:
                        x = q if cmd == "H" else x + q
                        add(x, y)
                elif cmd in "Vv":
                    for q in v:
                        y = q if cmd == "V" else y + q
                        add(x, y)
    return pts


def format_rects(page):
    """The sheet format's rectangles (left, bottom, right, top; sheet mm, y up) from the template's SVG <rect>s."""
    import re
    import xml.etree.ElementTree as ET
    tmpl = getattr(page, "Template", None)
    path = getattr(tmpl, "PageResult", "") or getattr(tmpl, "Template", "") if tmpl is not None else ""
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return []
    h = D.sheet_size(page)[1]
    out = []

    def num(v):
        try:
            return float(re.sub(r"[a-z%]+$", "", str(v)))
        except Exception as _fw_err:
            _fw_log("drawtableedit.py:1162", _fw_err)
            return None
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "rect" or el.get("transform"):
            continue
        x, y, w, hh = (num(el.get(k, 0)) for k in ("x", "y", "width", "height"))
        if None in (x, y, w, hh) or w <= 0 or hh <= 0:
            continue
        out.append((x, h - (y + hh), x + w, h - y))
    return out


def format_anchor(page, kind):
    ""



    rects = format_rects(page)
    if not rects:
        return None
    area = lambda r: (r[2] - r[0]) * (r[3] - r[1])
    w, h = D.sheet_size(page)
    rects = [r for r in rects if area(r) < w * h * 0.999]
    if not rects:
        return None
    big = sorted(rects, key=area, reverse=True)
    border = big[1] if len(big) > 1 and big[1][0] > big[0][0] and big[1][2] < big[0][2] and \
        area(big[1]) > 0.5 * area(big[0]) else big[0]
    if kind in ("BOM", "CutList"):
        tbs = [r for r in rects if r is not border and abs(r[2] - border[2]) < 1.0 and abs(r[1] - border[1]) < 1.0
               and area(r) < 0.5 * area(border)]
        if not tbs:
            return None
        tb = max(tbs, key=area)
        return (tb[2], tb[3]), "Bottom Right"
    if kind == "Revision":
        return (border[2], border[3]), "Top Right"
    if kind in ("Hole", "Bend", "Punch", "General", "Weld"):
        return (border[0], border[3]), "Top Left"
    return None


def anchor_target(page, p, tol=2.0):
    """Right-click while editing the sheet format: the format's line end or corner within tol mm of sheet point
    p (what Set as Anchor puts the anchor on), else None."""
    best = None
    for q in format_points(page):
        d = ((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** 0.5
        if d <= tol and (best is None or d < best[0]):
            best = (d, q)
    return best[1] if best else None


def set_anchor_corner(t, corner):
    """Anchor: the corner of the table that stays put (and attaches to the anchor point)."""
    if "SWAnchorCorner" not in t.PropertiesList:
        t.addProperty("App::PropertyString", "SWAnchorCorner", "FreeCAD", "Table anchor corner")
    t.SWAnchorCorner = corner


def place_corner(t, corner, p):
    left, top, w, h = box(t)
    x = p[0] + (-w / 2 if "Right" in corner else w / 2)
    y = p[1] + (h / 2 if "Bottom" in corner else -h / 2)
    t.X, t.Y = x, y
    t.Document.recompute()


def page_of(t):
    return next((o for o in t.InList if o.TypeId == "TechDraw::DrawPage"), None)


def anchors(page):
    try:
        return json.loads(getattr(page, "SWTableAnchors", "") or "{}")
    except ValueError:
        return {}


def set_anchor(page, kind, p):
    """Set as Anchor (on the sheet format): tables of kind attach at sheet point p."""
    a = anchors(page)
    a[kind] = [float(p[0]), float(p[1])]
    if "SWTableAnchors" not in page.PropertiesList:
        page.addProperty("App::PropertyString", "SWTableAnchors", "FreeCAD", "Table anchor points")
    page.SWTableAnchors = json.dumps(a)
    for t in page.Document.Objects:       # the tables attached to that anchor go with it
        if getattr(t, "SWTable", "") == kind and getattr(t, "SWAttachedToAnchor", False) and page_of(t) is page:
            try:
                attach_to_anchor(t)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: attach %s: %s\n" % (t.Name, error))


DOC_ANCHOR_PAGE = {"BOM": "Bill of Materials", "Hole": "Hole", "General": "General", "Bend": "Bend"}
CORNERS = ("Top Left", "Top Right", "Bottom Left", "Bottom Right")


def doc_anchor(t):
    ""

    page = DOC_ANCHOR_PAGE.get(getattr(t, "SWTable", ""))
    if page is None:
        return ""
    try:
        from . import optionspages
        got = optionspages.doc_value(t.Document, page, "Anchor", None)
    except Exception:
        return ""
    return got if got in CORNERS else ""


def anchor_corner(t):
    ""

    kind = getattr(t, "SWTable", "")
    return getattr(t, "SWAnchorCorner", "") or doc_anchor(t) or ("Bottom Right" if kind in ("BOM", "TitleBlock") else
                                                "Top Left" if kind in ("Hole", "General", "Bend", "Punch")
                                                else "Top Right")


def attach_to_anchor(t):
    page = page_of(t)
    if page is None:
        return False
    kind = t.SWTable
    a = anchors(page).get(kind)
    corner = anchor_corner(t)
    if a is None:
        f = format_anchor(page, kind)
        if f is None:
            x, y = DT.anchor(page, kind)
            t.X, t.Y = x, y
            t.Document.recompute()
            return True
        a = f[0]
        if not getattr(t, "SWAnchorCorner", "") and not doc_anchor(t):
            corner = f[1]
    place_corner(t, corner, a)
    return True


# =========================================================================== commands
COMMANDS = {
    "FreeWorks_DrawTableInsertColumnRight": ("Column Right", "Insert a column to the right of the cell."),
    "FreeWorks_DrawTableInsertColumnLeft": ("Column Left", "Insert a column to the left of the cell."),
    "FreeWorks_DrawTableInsertRowAbove": ("Row Above", "Insert a row above the cell."),
    "FreeWorks_DrawTableInsertRowBelow": ("Row Below", "Insert a row below the cell."),
    "FreeWorks_DrawTableDeleteTable": ("Table", "Delete the table."),
    "FreeWorks_DrawTableDeleteColumn": ("Column", "Delete the column of the cell."),
    "FreeWorks_DrawTableDeleteRow": ("Row", "Delete the row of the cell."),
    "FreeWorks_DrawTableMergeCells": ("Merge Cells", "Merge the selected cells into one."),
    "FreeWorks_DrawTableUnmergeCell": ("Unmerge a Cell", "Split a merged cell back into its cells."),
    "FreeWorks_DrawTableSortAscending": ("Ascending", "Sort the rows by the cell's column, A to Z / 0 to 9."),
    "FreeWorks_DrawTableSortDescending": ("Descending", "Sort the rows by the cell's column, Z to A / 9 to 0."),
    "FreeWorks_DrawTableSplitAbove": ("Horizontally Above", "Split the table above the cell's row."),
    "FreeWorks_DrawTableSplitBelow": ("Horizontally Below", "Split the table below the cell's row."),
    "FreeWorks_DrawTableSplitLeft": ("Vertically Left", "Split the table left of the cell's column."),
    "FreeWorks_DrawTableSplitRight": ("Vertically Right", "Split the table right of the cell's column."),
    "FreeWorks_DrawTableMergeTables": ("Merge Tables", "Join the picked tables (split parts) into one."),
    "FreeWorks_DrawTableMoveColumnLeft": ("Move Column Left", "Move the cell's column one place left."),
    "FreeWorks_DrawTableMoveColumnRight": ("Move Column Right", "Move the cell's column one place right."),
    "FreeWorks_DrawTableColumnWidth": ("Column Width...", "Set the width of the cell's column."),
    "FreeWorks_DrawTableRowHeight": ("Row Height...", "Set the height of the cell's row."),
    "FreeWorks_DrawTableEntireTable": ("Entire Table...", "Set the text size and line weight of the whole table."),
    "FreeWorks_DrawTableLockColumnWidth": ("Lock Column Width", "Keep the column widths when the table updates."),
    "FreeWorks_DrawTableLockRowHeight": ("Lock Row Height", "Keep the row heights when the table updates."),
    "FreeWorks_DrawTableHeaderTop": ("Table Header Top", "The header row at the top of the table."),
    "FreeWorks_DrawTableHeaderBottom": ("Table Header Bottom", "The header row at the bottom of the table."),
    "FreeWorks_DrawTableEditCell": ("Edit Text", "Edit the text of the cell."),
    "FreeWorks_DrawTableRestoreOriginal": ("Restore Original Value",
                                           "Put the model's value back in the overridden BOM cell."),
    "FreeWorks_DrawTableLockCells": ("Lock Cells", "Lock the selected cells: they can't be edited and an update "
                                                   "keeps their text."),
    "FreeWorks_DrawTableUnlockCells": ("Unlock Cells", "Unlock the selected cells."),
    "FreeWorks_DrawTableLockFirstRow": ("Lock First Row", "Revision table: the first row can't be edited, deleted, "
                                                          "hidden or sorted (click again to unlock)."),
    "FreeWorks_DrawTableAnchorTopLeft": ("Top Left", "Anchor the table at its top left corner."),
    "FreeWorks_DrawTableAnchorTopRight": ("Top Right", "Anchor the table at its top right corner."),
    "FreeWorks_DrawTableAnchorBottomLeft": ("Bottom Left", "Anchor the table at its bottom left corner."),
    "FreeWorks_DrawTableAnchorBottomRight": ("Bottom Right", "Anchor the table at its bottom right corner."),
    "FreeWorks_DrawTableAttachToAnchor": ("Attach to Anchor", "Move the table to its anchor point."),
    "FreeWorks_DrawTableSelectTable": ("Table", "Select the whole table."),
    "FreeWorks_DrawTableSelectColumn": ("Column", "Select the column of the cell."),
    "FreeWorks_DrawTableSelectRow": ("Row", "Select the row of the cell."),
    "FreeWorks_DrawTableHideColumn": ("Column", "Hide the column of the cell (Show > Hidden Columns brings it "
                                                "back)."),
    "FreeWorks_DrawTableHideRow": ("Row", "Hide the row of the cell (a BOM keeps the part hidden on update)."),
    "FreeWorks_DrawTableShowColumns": ("Hidden Columns", "Show the hidden columns again."),
    "FreeWorks_DrawTableShowRows": ("Hidden Rows", "Show the hidden rows again."),
    "FreeWorks_DrawTableSort": ("Sort...", "Sort the rows by up to three columns (a BOM keeps the sort)."),
    "FreeWorks_DrawTableSaveAs": ("Save As...", "Save the table as a CSV or text file."),
    "FreeWorks_DrawTableSaveTemplate": ("Save as Template...",
                                        "Save the table as a table template (General Table > Table Template)."),
    "FreeWorks_DrawSetAsAnchor": ("Set as Anchor", "On the sheet format: tables of a kind attach at the point "
                                  "clicked last."),
}


BOM_ONLY = ("Hide", "Show", "Sort...", "Restore Original Value")
REV_ONLY = ("Lock First Row",)
_FOR = [None]                             # the table the menu is being built for


class _TableMenu(list):
    """TABLE_MENU: the rows for the table the right-click is on (the right-click thread's drawmenu reads it)."""

    def __iter__(self):
        t = _FOR[0]
        bom = t is None or getattr(t, "SWTable", "") in ("BOM", "Bill of Materials")
        rev = t is not None and getattr(t, "SWTable", "") == "Revision"
        for e in list.__iter__(self):
            if e is not None and not bom and e[0] in BOM_ONLY:
                continue
            if e is not None and not rev and e[0] in REV_ONLY:
                continue
            yield e


TABLE_MENU = _TableMenu([
    ("Insert", [("Column Right", "FreeWorks_DrawTableInsertColumnRight"),
                ("Column Left", "FreeWorks_DrawTableInsertColumnLeft"),
                ("Row Above", "FreeWorks_DrawTableInsertRowAbove"),
                ("Row Below", "FreeWorks_DrawTableInsertRowBelow")]),
    ("Select", [("Table", "FreeWorks_DrawTableSelectTable"), ("Column", "FreeWorks_DrawTableSelectColumn"),
                ("Row", "FreeWorks_DrawTableSelectRow")]),
    ("Delete", [("Table", "FreeWorks_DrawTableDeleteTable"), ("Column", "FreeWorks_DrawTableDeleteColumn"),
                ("Row", "FreeWorks_DrawTableDeleteRow")]),
    ("Hide", [("Column", "FreeWorks_DrawTableHideColumn"), ("Row", "FreeWorks_DrawTableHideRow")]),
    ("Show", [("Hidden Columns", "FreeWorks_DrawTableShowColumns"), ("Hidden Rows", "FreeWorks_DrawTableShowRows")]),
    ("Merge Cells", "FreeWorks_DrawTableMergeCells"),
    ("Unmerge a Cell", "FreeWorks_DrawTableUnmergeCell"),
    ("Sort...", "FreeWorks_DrawTableSort"),
    ("Sort", [("Ascending", "FreeWorks_DrawTableSortAscending"),
              ("Descending", "FreeWorks_DrawTableSortDescending")]),
    ("Split", [("Horizontally Above", "FreeWorks_DrawTableSplitAbove"),
               ("Horizontally Below", "FreeWorks_DrawTableSplitBelow"),
               ("Vertically Left", "FreeWorks_DrawTableSplitLeft"),
               ("Vertically Right", "FreeWorks_DrawTableSplitRight")]),
    ("Merge Tables", "FreeWorks_DrawTableMergeTables"),
    None,
    ("Move Column Left", "FreeWorks_DrawTableMoveColumnLeft"),
    ("Move Column Right", "FreeWorks_DrawTableMoveColumnRight"),
    ("Formatting", [("Column Width...", "FreeWorks_DrawTableColumnWidth"),
                    ("Row Height...", "FreeWorks_DrawTableRowHeight"),
                    ("Entire Table...", "FreeWorks_DrawTableEntireTable")]),
    ("Lock Column Width", "FreeWorks_DrawTableLockColumnWidth"),
    ("Lock Row Height", "FreeWorks_DrawTableLockRowHeight"),
    ("Table Header", [("Top", "FreeWorks_DrawTableHeaderTop"), ("Bottom", "FreeWorks_DrawTableHeaderBottom")]),
    ("Anchor", [("Top Left", "FreeWorks_DrawTableAnchorTopLeft"), ("Top Right", "FreeWorks_DrawTableAnchorTopRight"),
                ("Bottom Left", "FreeWorks_DrawTableAnchorBottomLeft"),
                ("Bottom Right", "FreeWorks_DrawTableAnchorBottomRight"),
                ("Attach to Anchor", "FreeWorks_DrawTableAttachToAnchor")]),
    None,
    ("Edit Text", "FreeWorks_DrawTableEditCell"),
    ("Restore Original Value", "FreeWorks_DrawTableRestoreOriginal"),
    ("Lock Cells", "FreeWorks_DrawTableLockCells"),
    ("Unlock Cells", "FreeWorks_DrawTableUnlockCells"),
    ("Lock First Row", "FreeWorks_DrawTableLockFirstRow"),
    ("Update Table", "FreeWorks_DrawUpdateTable"),
    ("Save As...", "FreeWorks_DrawTableSaveAs"),       # Save As offers the table template type too
])


def save_table(t, path):
    """The table's text as CSV (comma) or text (tab), one line per row."""
    import csv
    tab = path.lower().endswith(".txt")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t" if tab else ",")
        for row in rows(t):
            w.writerow(row)
    return path


def picked_tables():
    out = []
    for o in Gui.Selection.getSelection():
        if getattr(o, "SWTable", "") and o not in out:
            out.append(o)
    return out


def _ask_number(key, title, label, value, lo, hi):
    v = ASK.pop(key, None)
    if v is not None:
        return float(v)
    v, ok = QtWidgets.QInputDialog.getDouble(Gui.getMainWindow(), title, label, value, lo, hi, 2)
    return float(v) if ok else None


class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.tip = COMMANDS[name]

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": D.pixmap("TechDraw_SpreadsheetView")}

    def IsActive(self):
        page = D.active_page()
        if page is None or not D.sheet_shown(page):
            return False
        n = self.name
        if n == "FreeWorks_DrawSetAsAnchor":
            return _editing_format(page) and bool(LAST_POINT)
        if n == "FreeWorks_DrawTableMergeTables":
            ts = picked_tables()
            return len(ts) >= 2 and len({t.SWTable for t in ts}) == 1
        cur = current()
        if cur is None:
            return False
        t, r0, c0, r1, c1 = cur
        nr, nc = size(t)
        if n == "FreeWorks_DrawTableMergeCells":
            return (r0, c0) != (r1, c1)
        if n == "FreeWorks_DrawTableUnmergeCell":
            return merged_at(t, r0, c0) is not None
        if n == "FreeWorks_DrawTableDeleteRow":
            return r0 > 0 and nr > 1 and not first_row_locked(t, r0)
        if n == "FreeWorks_DrawTableInsertRowAbove":
            return r0 > 0
        if n == "FreeWorks_DrawTableMoveColumnLeft":
            return c0 > 0
        if n == "FreeWorks_DrawTableMoveColumnRight":
            return c0 < nc - 1
        if n == "FreeWorks_DrawTableSplitAbove":
            return r0 >= 2
        if n == "FreeWorks_DrawTableSplitBelow":
            return 1 <= r0 < nr - 1
        if n == "FreeWorks_DrawTableSplitLeft":
            return c0 > 0
        if n == "FreeWorks_DrawTableSplitRight":
            return c0 < nc - 1
        if n == "FreeWorks_DrawTableHeaderTop":
            return _flag(t, "SWHeaderBottom")
        if n == "FreeWorks_DrawTableHeaderBottom":
            return not _flag(t, "SWHeaderBottom")
        if n in ("FreeWorks_DrawTableSortAscending", "FreeWorks_DrawTableSortDescending", "FreeWorks_DrawTableSort"):
            return nr > 2
        if n == "FreeWorks_DrawTableHideColumn":
            return nc > 1
        if n == "FreeWorks_DrawTableHideRow":
            return r0 > 0 and nr > 2
        if n == "FreeWorks_DrawTableRestoreOriginal":
            return any(is_overridden(t, r, c) and not is_locked(t, r, c) for r, c in _cells(r0, c0, r1, c1))
        if n == "FreeWorks_DrawTableLockCells":
            return not all(is_locked(t, r, c) for r, c in _cells(r0, c0, r1, c1))
        if n == "FreeWorks_DrawTableLockFirstRow":
            return getattr(t, "SWTable", "") == "Revision"
        if n == "FreeWorks_DrawTableUnlockCells":
            return any(is_locked(t, r, c) for r, c in _cells(r0, c0, r1, c1))
        if n == "FreeWorks_DrawTableEditCell":
            return not is_locked(t, r0, c0) and not first_row_locked(t, r0)
        if n == "FreeWorks_DrawTableShowColumns":
            return bool(_json(t, "SWHiddenColumns", []))
        if n == "FreeWorks_DrawTableShowRows":
            return bool(_json(t, "SWHiddenRows", []))
        return True

    def Activated(self):
        page = D.active_page()
        n = self.name
        if n == "FreeWorks_DrawSetAsAnchor":
            p = LAST_POINT[0] if LAST_POINT else None
            if page is None or p is None:
                return
            p = anchor_target(page, p) or p          # onto the format's line end or corner under the click
            kind = ASK.pop("kind", None)
            if kind is None:
                names = [a for a, _ in ANCHOR_KINDS]
                kind, ok = QtWidgets.QInputDialog.getItem(Gui.getMainWindow(), "Set as Anchor", "Anchor for:",
                                                          names, 0, False)
                if not ok:
                    return
            kind = dict(ANCHOR_KINDS).get(kind, kind)
            page.Document.openTransaction("Set as Anchor")
            try:
                set_anchor(page, kind, p)
            except BaseException:
                try:
                    page.Document.abortTransaction()
                except Exception:
                    pass
                raise
            page.Document.commitTransaction()
            return
        if n == "FreeWorks_DrawTableMergeTables":
            ts = picked_tables()
            doc = ts[0].Document
            doc.openTransaction(self.text)
            try:
                merge_tables(ts)
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
            return
        cur = current()
        if cur is None:
            return
        t, r0, c0, r1, c1 = cur
        doc = t.Document
        nr, nc = size(t)
        if n == "FreeWorks_DrawTableSelectTable":
            set_current(t, 0, 0, nr - 1, nc - 1)
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(doc.Name, t.Name)
            return
        if n == "FreeWorks_DrawTableSelectColumn":
            set_current(t, 0, c0, nr - 1, c0)
            return
        if n == "FreeWorks_DrawTableSelectRow":
            set_current(t, r0, 0, r0, nc - 1)
            return
        if n == "FreeWorks_DrawTableSaveTemplate":
            path = ASK.pop("template_path", None)
            if path is None:
                path, _ = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save as Template",
                                                                os.path.join(DT.template_folder(), t.Label + ".fwtbt"),
                                                                "Table templates (*.fwtbt)")
                if not path:
                    return
            DT.save_table_template(t, path)
            return
        if n == "FreeWorks_DrawTableSaveAs":
            path = ASK.pop("path", None)
            if path is None:
                path, flt = QtWidgets.QFileDialog.getSaveFileName(
                    Gui.getMainWindow(), "Save As", os.path.join(DT.template_folder(), t.Label),
                    "Table Template (*.fwtbt);;CSV (*.csv);;Text (*.txt)")
                if not path:
                    return
                if "fwtbt" in (flt or "") and not os.path.splitext(path)[1]:
                    path += ".fwtbt"
            if path.lower().endswith(".fwtbt"):
                DT.save_table_template(t, path)
            else:
                save_table(t, path)
            return
        if n == "FreeWorks_DrawTableSort":
            keys = ASK.pop("sort", None)
            keep = ASK.pop("keep", False)
            if keys is None:
                dlg = SortDialog(t, c0)
                if dlg.exec() != QtWidgets.QDialog.Accepted:
                    return
                keys, keep = dlg.keys(), dlg.keep.isChecked()
        if n == "FreeWorks_DrawTableColumnWidth":
            k = K * float(t.Scale or 1.0)
            v = _ask_number("width", "Column Width", "Column width (mm):", widths(t)[c0] * k, 0.5, 1000)
            if v is None:
                return
        elif n == "FreeWorks_DrawTableRowHeight":
            k = K * float(t.Scale or 1.0)
            v = _ask_number("height", "Row Height", "Row height (mm):", _row_heights(t)[r0] * k, 0.5, 1000)
            if v is None:
                return
        elif n == "FreeWorks_DrawTableEntireTable":
            v = _ask_number("size", "Entire Table", "Text size (mm):", float(t.TextSize) * K * float(t.Scale or 1.0), 0.5, 100)
            if v is None:
                return
            lw = _ask_number("line", "Entire Table", "Line weight (mm):", float(t.LineWidth), 0.05, 5)
        elif n == "FreeWorks_DrawTableEditCell":
            text = ASK.pop("text", None)
            if text is None:
                text, ok = QtWidgets.QInputDialog.getText(Gui.getMainWindow(), "Edit Text", "Cell text:",
                                                          text=rows(t)[r0][c0])
                if not ok:
                    return
        doc.openTransaction(self.text)
        try:
            if n == "FreeWorks_DrawTableInsertColumnRight":
                set_current(t, r0, insert_column(t, c0, True))
            elif n == "FreeWorks_DrawTableInsertColumnLeft":
                insert_column(t, c0, False)
                set_current(t, r0, c0 + 1)
            elif n == "FreeWorks_DrawTableInsertRowAbove":
                insert_row(t, r0, True)
                set_current(t, r0 + 1, c0)
            elif n == "FreeWorks_DrawTableInsertRowBelow":
                set_current(t, insert_row(t, r0, False), c0)
            elif n == "FreeWorks_DrawTableDeleteTable":
                delete_table(t)
            elif n == "FreeWorks_DrawTableDeleteColumn":
                delete_column(t, c0)
                set_current(t, r0, max(0, c0 - 1))
            elif n == "FreeWorks_DrawTableDeleteRow":
                delete_row(t, r0)
                set_current(t, max(0, r0 - 1), c0)
            elif n == "FreeWorks_DrawTableMergeCells":
                merge_cells(t, r0, c0, r1, c1)
                set_current(t, r0, c0)
            elif n == "FreeWorks_DrawTableUnmergeCell":
                unmerge_cell(t, r0, c0)
            elif n == "FreeWorks_DrawTableSortAscending":
                sort_rows(t, c0, True)
            elif n == "FreeWorks_DrawTableSortDescending":
                sort_rows(t, c0, False)
            elif n == "FreeWorks_DrawTableSort":
                sort_table(t, keys, keep)
            elif n == "FreeWorks_DrawTableHideColumn":
                hide_column(t, c0)
                set_current(t, r0, max(0, min(c0, nc - 2)))
            elif n == "FreeWorks_DrawTableHideRow":
                hide_row(t, r0)
                set_current(t, max(1, min(r0, nr - 2)), c0)
            elif n == "FreeWorks_DrawTableShowColumns":
                show_columns(t)
            elif n == "FreeWorks_DrawTableShowRows":
                show_rows(t)
            elif n == "FreeWorks_DrawTableSplitAbove":
                split(t, "Horizontally Above", r0, c0)
            elif n == "FreeWorks_DrawTableSplitBelow":
                split(t, "Horizontally Below", r0, c0)
            elif n == "FreeWorks_DrawTableSplitLeft":
                split(t, "Vertically Left", r0, c0)
            elif n == "FreeWorks_DrawTableSplitRight":
                split(t, "Vertically Right", r0, c0)
            elif n == "FreeWorks_DrawTableMoveColumnLeft":
                if move_column(t, c0, True):
                    set_current(t, r0, c0 - 1)
            elif n == "FreeWorks_DrawTableMoveColumnRight":
                if move_column(t, c0, False):
                    set_current(t, r0, c0 + 1)
            elif n == "FreeWorks_DrawTableColumnWidth":
                column_width(t, c0, v)
            elif n == "FreeWorks_DrawTableRowHeight":
                row_height(t, r0, v)
            elif n == "FreeWorks_DrawTableEntireTable":
                entire_table(t, v, lw)
            elif n == "FreeWorks_DrawTableLockColumnWidth":
                lock(t, "width", not _flag(t, "SWLockColumnWidth"))
            elif n == "FreeWorks_DrawTableLockRowHeight":
                lock(t, "height", not _flag(t, "SWLockRowHeight"))
            elif n == "FreeWorks_DrawTableHeaderTop":
                header(t, False)
            elif n == "FreeWorks_DrawTableHeaderBottom":
                header(t, True)
            elif n == "FreeWorks_DrawTableEditCell":
                edit_cell(t, r0, c0, text)
            elif n == "FreeWorks_DrawTableRestoreOriginal":
                restore_original(t, _cells(r0, c0, r1, c1))
            elif n == "FreeWorks_DrawTableLockCells":
                lock_cells(t, _cells(r0, c0, r1, c1), True)
            elif n == "FreeWorks_DrawTableUnlockCells":
                lock_cells(t, _cells(r0, c0, r1, c1), False)
            elif n == "FreeWorks_DrawTableLockFirstRow":
                lock_first_row(t)
            elif n.startswith("FreeWorks_DrawTableAnchor"):
                corner = {"TopLeft": "Top Left", "TopRight": "Top Right", "BottomLeft": "Bottom Left",
                          "BottomRight": "Bottom Right"}[n[len("FreeWorks_DrawTableAnchor"):]]
                set_anchor_corner(t, corner)
            elif n == "FreeWorks_DrawTableAttachToAnchor":
                attach_to_anchor(t)
                DT.set_attached(t, True)
        finally:
            doc.commitTransaction()
        doc.recompute()


def _editing_format(page):
    try:
        from . import drawsheet
        return bool(drawsheet.editing_format(page))
    except Exception:
        return False


LAST_POINT = []      # the last sheet point clicked (Set as Anchor)


def sheet_press(page, p, shift=False):
    """drawselect's sheet click hook: the point, and the table cell under it."""
    LAST_POINT[:] = [p]
    hit = remember(page, p, shift)
    try:
        from . import drawtablecells
        drawtablecells.on_press(page, hit)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: table selection: %s\n" % error)
    try:
        bom_pm(page, hit)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Bill of Materials PM: %s\n" % error)
    return hit


def _open_bom_pm():
    from . import drawings as D
    for panel in list(D.SHOWN):
        if type(panel).__name__ == "BomEditPanel":
            return panel
    return None


def bom_pm(page, hit):
    ""
    from . import drawtables as DT
    pm = _open_bom_pm()
    if hit is None:
        if pm is not None and Gui.Control.activeDialog():
            QtCore.QTimer.singleShot(0, pm.accept)
        return
    t = hit[0]
    if getattr(t, "SWTable", "") != "BOM":
        return
    if pm is not None and pm.edit_table is t:
        return
    if Gui.Control.activeDialog() and pm is None:
        return                               # another PM is open (it keeps the click)
    QtCore.QTimer.singleShot(0, lambda: DT.edit_bom(t))


def sheet_double_click(page, p):
    ""
    hit = remember(page, p)
    if hit is None:
        return False
    try:
        from . import drawtablecells
        t, r, c = hit
        QtCore.QTimer.singleShot(0, lambda: drawtablecells.edit_in_place(page, t, r, c))
        return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: in-place cell editor: %s\n" % error)
    QtCore.QTimer.singleShot(0, lambda: Gui.runCommand("FreeWorks_DrawTableEditCell", 0))
    return True


def _wrap_menu():
    """The table right-click (the right-click thread's drawmenu.table_items) shows the rows for that table."""
    try:
        from . import drawmenu
    except Exception:
        return False
    if getattr(drawmenu, "_fw_tablemenu", False):
        return True
    items0 = drawmenu.table_items

    def table_items(t, *a, **k):
        _FOR[0] = t
        try:
            return items0(t, *a, **k)
        finally:
            _FOR[0] = None
    drawmenu.table_items = table_items
    drawmenu._fw_tablemenu = True
    return True


def register():
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
    _wrap_menu()
