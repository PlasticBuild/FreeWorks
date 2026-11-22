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


import math
import re
import shutil

VERSIONS = (("R12", "AC1009"), ("R13", "AC1012"), ("R14", "AC1014"), ("2000-2002", "AC1015"),
            ("2004-2006", "AC1018"), ("2007-2009", "AC1021"), ("2010-2012", "AC1024"), ("2013-2017", "AC1027"),
            ("2018", "AC1032"))
DEFAULT_VERSION = "2000-2002"
TECHDRAW_VERSION = "R14"         # what TechDraw writes (no units field); with no other option set it is left as it is
SAMPLES = 64                     # polyline points for a full ellipse or a spline


# --------------------------------------------------------------------------- reading
def read(path):
    raw = open(path, "rb").read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", "replace")
    lines = text.splitlines()
    tags = []
    for i in range(0, len(lines) - 1, 2):
        try:
            tags.append((int(lines[i].strip()), lines[i + 1].strip() if int(lines[i].strip()) != 1 else
                         lines[i + 1]))
        except ValueError:
            continue
    return tags


def sections(tags):
    out, name, cur = {}, None, None
    i = 0
    while i < len(tags):
        k, v = tags[i]
        if k == 0 and v == "SECTION" and i + 1 < len(tags):
            name, cur = tags[i + 1][1], []
            i += 2
            continue
        if k == 0 and v == "ENDSEC":
            out[name] = cur
            name, cur = None, None
        elif cur is not None:
            cur.append((k, v))
        i += 1
    return out


def split(tags):
    """Tags cut into entities / records, each starting with its 0 tag."""
    out = []
    for t in tags:
        if t[0] == 0:
            out.append([t])
        elif out:
            out[-1].append(t)
    return out


def header_vars(tags):
    out, name = {}, None
    for k, v in tags:
        if k == 9:
            name = v
            out[name] = []
        elif name:
            out[name].append((k, v))
    return out


# --------------------------------------------------------------------------- scaling
def _num(v):
    try:
        return float(v)
    except ValueError:
        return None


def scale_entity(ent, k):
    """Every coordinate and length of an entity times k (angles, ratios, knots and factors kept)."""
    if k == 1.0:
        return ent
    kind = ent[0][1]
    out = []
    for code, v in ent:
        f = _num(v) if code >= 10 else None
        scale = 10 <= code <= 38
        if code == 40 and kind not in ("ELLIPSE", "SPLINE"):
            scale = True
        if code in (41, 43) and kind in ("MTEXT", "LWPOLYLINE", "VERTEX", "POLYLINE"):
            scale = True
        if kind == "INSERT" and code in (41, 42, 43):
            scale = False
        if kind == "DIMENSION" and code == 42:
            scale = False                       # the measured value is the model's own
        out.append((code, _fmt(f * k)) if scale and f is not None else (code, v))
    return out


def _fmt(f):
    s = "%.10f" % f
    s = s.rstrip("0")
    return s + "0" if s.endswith(".") else s


# --------------------------------------------------------------------------- curves to polylines
def _ellipse_points(ent):
    g = _codes(ent)
    cx, cy = g.get(10, 0.0), g.get(20, 0.0)
    mx, my = g.get(11, 1.0), g.get(21, 0.0)
    r = g.get(40, 1.0)
    a0, a1 = g.get(41, 0.0), g.get(42, 2 * math.pi)
    if a1 <= a0:
        a1 += 2 * math.pi
    if g.get(230, 1.0) < 0:                     # seen from behind: the curve mirrored in x
        cx, mx = -cx, -mx
    n = max(4, int(SAMPLES * (a1 - a0) / (2 * math.pi)))
    pts = []
    for i in range(n + 1):
        t = a0 + (a1 - a0) * i / n
        x = cx + mx * math.cos(t) - my * r * math.sin(t)
        y = cy + my * math.cos(t) + mx * r * math.sin(t)
        if g.get(230, 1.0) < 0:
            x = -x
        pts.append((x, y))
    closed = abs((a1 - a0) - 2 * math.pi) < 1e-6
    return pts, closed


def _codes(ent):
    g = {}
    for code, v in ent:
        if code not in g:
            f = _num(v)
            if f is not None:
                g[code] = f
    return g


def _spline_points(ent):
    deg, knots, weights, cps, fits, flags = 3, [], [], [], [], 0
    x = None
    for code, v in ent:
        if code == 71:
            deg = int(float(v))
        elif code == 70:
            flags = int(float(v))
        elif code == 40:
            knots.append(float(v))
        elif code == 41:
            weights.append(float(v))
        elif code == 10:
            x = float(v)
        elif code == 20:
            cps.append((x, float(v)))
        elif code == 11:
            x = float(v)
        elif code == 21:
            fits.append((x, float(v)))
    if len(cps) > deg and len(knots) == len(cps) + deg + 1:
        w = weights if len(weights) == len(cps) else [1.0] * len(cps)
        lo, hi = knots[deg], knots[len(cps)]
        pts = [_de_boor(deg, knots, cps, w, lo + (hi - lo) * i / SAMPLES) for i in range(SAMPLES + 1)]
    else:
        pts = fits or cps
    return pts, bool(flags & 1)


def _de_boor(p, U, P, W, u):
    n = len(P) - 1
    k = p
    while k < n and u >= U[k + 1]:
        k += 1
    d = [(P[j][0] * W[j], P[j][1] * W[j], W[j]) for j in range(k - p, k + 1)]
    for r in range(1, p + 1):
        for j in range(p, r - 1, -1):
            i = j + k - p
            den = U[i + p - r + 1] - U[i]
            a = 0.0 if den == 0 else (u - U[i]) / den
            d[j] = tuple((1 - a) * d[j - 1][m] + a * d[j][m] for m in range(3))
    x, y, wt = d[p]
    return (x / wt, y / wt) if wt else (x, y)


def _lw_points(ent):
    pts, x, bulge = [], None, []
    for code, v in ent:
        if code == 10:
            x = float(v)
        elif code == 20:
            pts.append((x, float(v)))
            bulge.append(0.0)
        elif code == 42 and bulge:
            bulge[-1] = float(v)
    closed = bool(int(float(_codes(ent).get(70, 0))) & 1)
    return pts, bulge, closed


def _common(ent):
    """Layer, linetype, colour, linetype scale: the tags every version shares."""
    keep = []
    for code, v in ent[1:]:
        if code in (8, 6, 62, 48, 60):
            keep.append((code, v))
        if code == 100 and v != "AcDbEntity" and keep:
            break
    if not any(c == 8 for c, _ in keep):
        keep.insert(0, (8, "0"))
    return keep


# --------------------------------------------------------------------------- entity forms
def _r12_polyline(common, pts, closed, bulge=None):
    out = [[(0, "POLYLINE")] + common + [(66, "1"), (10, "0.0"), (20, "0.0"), (30, "0.0"),
                                         (70, "1" if closed else "0")]]
    for i, (x, y) in enumerate(pts):
        v = [(0, "VERTEX")] + common + [(10, _fmt(x)), (20, _fmt(y)), (30, "0.0")]
        if bulge and bulge[i]:
            v.append((42, _fmt(bulge[i])))
        out.append(v)
    out.append([(0, "SEQEND")] + common)
    return out


def _lwpolyline(common, pts, closed):
    e = [(0, "LWPOLYLINE")] + common + [(100, "AcDbPolyline"), (90, str(len(pts))), (70, "1" if closed else "0")]
    for x, y in pts:
        e += [(10, _fmt(x)), (20, _fmt(y))]
    return [e]


def _plain(text):
    import re
    t = text.replace("\\P", " ").replace("\\~", " ")
    t = re.sub(r"\\[A-Za-z][^;\\]*;", "", t)
    return t.replace("{", "").replace("}", "")


def to_r12(ent, splines=True):
    kind = ent[0][1]
    common = _common(ent)
    if kind == "LWPOLYLINE":
        pts, bulge, closed = _lw_points(ent)
        return _r12_polyline(common, pts, closed, bulge)
    if kind == "ELLIPSE":
        pts, closed = _ellipse_points(ent)
        return _r12_polyline(common, pts, closed)
    if kind == "SPLINE":
        pts, closed = _spline_points(ent)
        return _r12_polyline(common, pts, closed)
    if kind == "MTEXT":
        g = _codes(ent)
        text = "".join(v for c, v in ent if c in (3, 1))
        e = [(0, "TEXT")] + common + [(10, _fmt(g.get(10, 0))), (20, _fmt(g.get(20, 0))), (30, "0.0"),
                                      (40, _fmt(g.get(40, 2.5))), (1, _plain(text))]
        if 50 in g:
            e.append((50, _fmt(g[50])))
        return [e]
    if kind in ("HATCH", "IMAGE", "IMAGEDEF", "WIPEOUT", "LEADER", "MLEADER", "VIEWPORT", "ACAD_TABLE"):
        return []
    out, skip = [], False
    for code, v in ent:
        if code == 102:
            skip = v.startswith("{") and not skip
            continue
        if skip or code in (5, 105, 330, 360, 100, 370, 420, 430, 440, 390, 347, 284):
            continue
        out.append((code, v))
    return [out]


MARKERS = {"LINE": "AcDbLine", "CIRCLE": "AcDbCircle", "POINT": "AcDbPoint", "SOLID": "AcDbTrace",
           "ARC": "AcDbCircle", "TEXT": "AcDbText"}


def to_r2000(ent, splines=True):
    """An entity without handle or owner (they are added when it is written), splines as polylines if asked."""
    kind = ent[0][1]
    common = _common(ent)
    if kind == "SPLINE" and not splines:
        pts, closed = _spline_points(ent)
        return _lwpolyline(common, pts, closed)
    body, seen_sub, skip = [], False, False
    for code, v in ent[1:]:
        if code == 102:
            skip = v.startswith("{") and not skip
            continue
        if skip or code in (5, 105, 330, 360):
            continue
        if code == 100:
            if v == "AcDbEntity":
                continue
            seen_sub = True
        if not seen_sub and code in (8, 6, 62, 48, 60, 67):
            continue
        body.append((code, v))
    if not seen_sub and kind in MARKERS:
        body.insert(0, (100, MARKERS[kind]))
        if kind == "ARC":
            i = next((n for n, (c, _) in enumerate(body) if c == 50), len(body))
            body.insert(i, (100, "AcDbArc"))
    return [[(0, kind)] + common + body]


# --------------------------------------------------------------------------- writing
class _Out(object):
    def __init__(self):
        self.tags = []
        self.next = 0x20

    def handle(self):
        self.next += 1
        return "%X" % self.next

    def add(self, *tags):
        self.tags.extend(tags)

    def ext(self, tags):
        self.tags.extend(tags)


def _extents(ents):
    xs, ys = [], []
    for e in ents:
        for code, v in e:
            if code == 10:
                xs.append(float(v))
            elif code == 20:
                ys.append(float(v))
    if not xs:
        return (0.0, 0.0), (1.0, 1.0)
    return (min(xs), min(ys)), (max(xs), max(ys))


def _records(tables, name):
    """The records of one source table, without their handle / owner / subclass tags."""
    recs = []
    for r in split(tables):
        if r[0][1] != name:
            continue
        body, skip = [], False
        for code, v in r[1:]:
            if code == 102:
                skip = v.startswith("{") and not skip
                continue
            if skip or code in (5, 105, 330, 360, 100, 390, 347, 348):
                continue
            body.append((code, v))
        recs.append(body)
    return recs


def _name(rec):
    return next((v for c, v in rec if c == 2), "")


_VECTORS = {"ELLIPSE": (11,), "MTEXT": (11,), "SPLINE": (12, 13), "XLINE": (11,), "RAY": (11,)}


def shift_entity(ent, dx):
    """An entity moved dx along X (its points, not its direction vectors)."""
    if not dx:
        return ent
    keep = _VECTORS.get(ent[0][1], ())
    out = []
    for code, v in ent:
        f = _num(v) if 10 <= code <= 18 and code not in keep else None
        out.append((code, _fmt(f + dx)) if f is not None else (code, v))
    return out


def block_name(label, taken):
    """A view's label as a DXF block name (letters, digits, - and _), unique among taken (added to it)."""
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", label or "View").strip("_") or "View"
    name, n = base, 1
    while name.upper() in taken:
        n += 1
        name = "%s_%d" % (base, n)
    taken.add(name.upper())
    return name


def insert_entity(name, layer="0"):
    """A block reference at the origin (the block's entities keep their sheet coordinates)."""
    return [(0, "INSERT"), (8, layer), (100, "AcDbBlockReference"), (2, name), (10, "0.0"), (20, "0.0"), (30, "0.0")]



INSUNITS = {"in": 1, "ft": 2, "mm": 4, "cm": 5, "m": 6}
UNITS_CODE = [4]            # the $INSUNITS of the file being written (convert's units)


def doc_units(doc):
    """($INSUNITS code, size in mm) of the document's length unit: (1, 25.4) in an IPS part or drawing."""
    try:
        from . import unitspage
        sym, size = unitspage.length_unit(doc)
        if sym in INSUNITS and size > 0:
            return INSUNITS[sym], size
    except Exception as _fw_err:
        _fw_log("drawdxf.py:doc_units", _fw_err)
    return 4, 1.0


def convert(src, dst, version=DEFAULT_VERSION, scale=1.0, splines=True, font="TrueType", more=(), hidden=None, merge=0.0,
            extra=(), layers=None, view_blocks=None, units=4):
    ""












    UNITS_CODE[0] = units
    if (hidden and hidden.get("lines")) or merge > 0 or extra or layers or view_blocks:
        pass
    elif not more and version == TECHDRAW_VERSION and scale == 1.0 and splines and font == "TrueType" and units == 4:
        if src != dst:
            shutil.copyfile(src, dst)
        return dst
    acad = dict(VERSIONS).get(version, "AC1014")
    convert_one = to_r12 if acad == "AC1009" else to_r2000
    tables = None
    ents, conv_blocks = [], []
    anon = [0]
    for n, (path, dx) in enumerate([(src, 0.0)] + list(more)):
        secs = sections(read(path))
        if tables is None:
            tables = secs.get("TABLES", [])
        blocks = []                       # (name, flags, base, entities)
        rename = {}
        for b in _blocks(secs.get("BLOCKS", [])):
            name = b[0]
            if name.upper() in ("*MODEL_SPACE", "*PAPER_SPACE", "$MODEL_SPACE", "$PAPER_SPACE"):
                continue
            if name.startswith("*"):
                if n or not re.match(r"\*[DUXTA]\d+$", name):
                    anon[0] += 1
                    rename[name] = "*D%d" % (anon[0] + 1000 * n)
            elif n:
                rename[name] = "%s_S%d" % (name, n + 1)       # each sheet's own blocks
            blocks.append(b)
        if n == 0 and hidden and hidden.get("lines"):
            tables = list(tables) + linetype_record(hidden.get("linetype", HIDDEN_LTYPES[0][0]), acad == "AC1009")
        if n == 0 and extra:
            known = {nm for nm, _d, _p in HIDDEN_LTYPES + CENTER_LTYPES}
            want = sorted({_tag(e, 6) for e in extra} & known)
            have = {_name(r) for r in _records(tables, "LTYPE")}
            for name in want:
                if name not in have:
                    tables = list(tables) + linetype_record(name, acad == "AC1009")
        mine = [g for x0, g in (hidden or {}).get("lines", []) if abs(x0 - dx) < 1e-9]
        pre = []
        for e in split(secs.get("ENTITIES", [])):
            if mine and is_hidden(e, mine):
                e = with_linetype(e, hidden.get("linetype", "HIDDEN"))
            pre.append(scale_entity(shift_entity(e, dx), scale))
        if n == 0 and extra:
            pre.extend(scale_entity(e, scale) for e in extra)
        if merge > 0:
            pre = merge_entities(pre, merge)[0]
        vb = (view_blocks[n] if view_blocks and n < len(view_blocks) else None) or {}
        grouped = {}
        for e in pre:
            w = _weight_of(e, layers)
            home = vb.get(_tag(e, 8))
            for x in convert_one(e, splines):
                x = _relayer(_renamed(x, rename), layers, w, acad)
                if home:
                    if acad == "AC1009":
                        x = [(c, v) for c, v in x if c != 100]
                    grouped.setdefault(home, []).append(x)
                else:
                    ents.append(x)
        for home in sorted(grouped, key=lambda b: list(vb.values()).index(b) if b in vb.values() else 0):
            conv_blocks.append((home, 0, (0.0, 0.0, 0.0), grouped[home]))
            ins = insert_entity(home)
            if acad == "AC1009":
                ins = [(c, v) for c, v in ins if c != 100]
            ents.append(ins)
        for name, flags, base, bents in blocks:
            cb = []
            for e in bents:
                w = _weight_of(e, layers)
                for x in convert_one(scale_entity(e, scale), splines):
                    cb.append(_relayer(_renamed(x, rename), layers, w, acad))
            conv_blocks.append((rename.get(name, name), 1 if name in rename and name.startswith("*") else flags,
                                tuple(b * scale for b in base), cb))
    if layers and layers.get("records"):
        # every layer the entities use, the drawing's first (TechDraw's per-view layers left out)
        used = {_tag(e, 8) for e in ents} | {_tag(e, 8) for b in conv_blocks for e in b[3]}
        recs = [r for r in layers["records"]]
        have = {_name(r) for r in recs}
        for name in sorted(n for n in used if n and n not in have):
            recs.append([(2, name), (70, "0"), (62, "7"), (6, "CONTINUOUS")])
        LAYER_RECORDS[0] = recs
    else:
        LAYER_RECORDS[0] = None
    o = _Out()
    if acad == "AC1009":
        _write_r12(o, tables, conv_blocks, ents, font)
    else:
        _write_r2000(o, acad, tables, conv_blocks, ents, font)
    enc = "utf-8" if acad >= "AC1021" else "cp1252"
    with open(dst, "w", encoding=enc, errors="strict", newline="\n") as f:
        for code, v in o.tags:
            f.write("%3d\n%s\n" % (code, _encode(v, enc)))
    return dst


# --------------------------------------------------------------------------- end points merge
# Export Options > End points merge (Enable merging, Merge distance). The geometry is dxfmerge (Kimi chunk 2).
MERGE_DISTANCE = 0.01          # mm: the default Merge distance


def _set_xy(ent, start, x, y):
    """Set the first 10/20-style pair at or after tag index start (code cx then cx+10)."""
    for i in range(start, len(ent)):
        if ent[i][0] in (10, 11):
            cx = ent[i][0]
            ent[i] = (cx, _fmt(x))
            for j in range(i + 1, len(ent)):
                if ent[j][0] == cx + 10:
                    ent[j] = (cx + 10, _fmt(y))
                    break
            return


def _entity_item(ent):
    kind = ent[0][1] if ent and ent[0][0] == 0 else ""
    c = _codes(ent)
    try:
        if kind == "LINE":
            return {"kind": "line", "pts": [(float(c[10]), float(c[20])), (float(c[11]), float(c[21]))]}
        if kind == "ARC":
            cx, cy, r = float(c[10]), float(c[20]), float(c[40])
            a0, a1 = math.radians(float(c.get(50, 0))), math.radians(float(c.get(51, 0)))
            return {"kind": "arc", "ends": [(cx + r * math.cos(a0), cy + r * math.sin(a0)),
                                            (cx + r * math.cos(a1), cy + r * math.sin(a1))]}
        if kind == "LWPOLYLINE":
            pts, _b, closed = _lw_points(ent)
            if pts:
                return {"kind": "poly", "pts": pts, "closed": closed}
    except (KeyError, ValueError, TypeError) as _fw_err:
        _fw_log("drawdxf.py:558", _fw_err)
    return {"kind": "other"}


def merge_entities(ents, tol):
    """End points merge on raw DXF entities (tag lists): LINE and open LWPOLYLINE ends closer than tol move
    together (onto an ARC end when there is one; arcs never move); lines that shrink to a point are dropped.
    Returns (entities, number of end points moved)."""
    from . import dxfmerge
    items = []
    for n, e in enumerate(ents):
        it = _entity_item(e)
        it["n"] = n
        items.append(it)
    new, moved = dxfmerge.merge_endpoints(items, tol)
    if not moved:
        return list(ents), 0
    out = []
    for it in new:
        e = list(ents[it["n"]])
        if it["kind"] == "line":
            (x0, y0), (x1, y1) = it["pts"]
            for code, v in ((10, x0), (20, y0), (11, x1), (21, y1)):
                e = [(c, _fmt(v) if c == code else w) for c, w in e]
        elif it["kind"] == "poly" and not it.get("closed"):
            idx = [i for i, (c, _v) in enumerate(e) if c == 10]
            if idx:
                _set_xy(e, idx[0], *it["pts"][0])
                _set_xy(e, idx[-1], *it["pts"][-1])
        out.append(e)
    return out, moved


# --------------------------------------------------------------------------- hidden lines


HIDDEN_LTYPES = (("HIDDEN", "Hidden __ __ __ __ __ __ __ __", (6.35, -3.175)),
                 ("SLD-Dashed", "Dashed __ __ __ __", (6.0, -2.0)))
LINE_STYLES = ("AutoCAD standard styles", "Custom styles (SLD-Dashed)")


def hidden_linetype(style):
    return HIDDEN_LTYPES[1][0] if style == LINE_STYLES[1] else HIDDEN_LTYPES[0][0]


def linetype_record(name, r12=False):
    """A dashed LTYPE table record (tag list, starting with its 0 tag)."""
    desc, pat = next(((d, p) for n, d, p in HIDDEN_LTYPES + CENTER_LTYPES if n == name), HIDDEN_LTYPES[0][1:])
    rec = [(0, "LTYPE"), (2, name), (70, "0"), (3, desc), (72, "65"), (73, str(len(pat))),
           (40, _fmt(sum(abs(x) for x in pat)))]
    for x in pat:
        rec.append((49, _fmt(x)))
        if not r12:
            rec.append((74, "0"))
    return rec


def _tag(e, code):
    return next((v for c, v in e[1:] if c == code), None)


def is_hidden(ent, geo, tol=0.02):
    """True when a TechDraw DXF entity (unshifted, sheet mm) is one of geo's hidden edges: ("line", a, b) or
    ("circle", (cx, cy), r)."""
    kind = ent[0][1]
    try:
        if kind == "LINE":
            a = (float(_tag(ent, 10)), float(_tag(ent, 20)))
            b = (float(_tag(ent, 11)), float(_tag(ent, 21)))
            return any(g[0] == "line" and _same((g[1], g[2]), a, b, tol) for g in geo)
        if kind in ("CIRCLE", "ARC"):
            c = (float(_tag(ent, 10)), float(_tag(ent, 20)))
            r = float(_tag(ent, 40))
            return any(g[0] == "circle" and abs(g[1][0] - c[0]) < tol and abs(g[1][1] - c[1]) < tol and
                       abs(g[2] - r) < tol for g in geo)
    except (TypeError, ValueError):
        return False
    return False


def with_linetype(ent, linetype):
    """The entity with its linetype (code 6) set, right after its layer."""
    body = [(c, v) for c, v in ent[1:] if c != 6]
    i = next((n for n, (c, _v) in enumerate(body) if c == 8), -1) + 1
    return [ent[0]] + body[:i] + [(6, linetype)] + body[i:]


def hidden_lines(page):
    ""


    import math as _m
    from . import drawings as D
    out = []
    for v in D.views_of(page):
        if not getattr(v, "HardHidden", False) or getattr(v, "SWShadeOf", ""):
            continue
        try:
            edges, shown = v.getHiddenEdges(), v.getVisibleEdges()
        except Exception:
            continue
        x0, y0 = D.view_position(v)
        rot = _m.radians(float(getattr(v, "Rotation", 0.0) or 0.0))
        c, s_ = _m.cos(rot), _m.sin(rot)

        def put(p):
            x, y = p.x, -p.y               # view geometry Y points down
            return (x0 + x * c - y * s_, y0 + x * s_ + y * c)

        def geo(e):
            t = e.Curve.TypeId
            if t == "Part::GeomLine" or t == "Part::GeomLineSegment":
                return ("line", put(e.Vertexes[0].Point), put(e.Vertexes[-1].Point))
            if t == "Part::GeomCircle":
                return ("circle", put(e.Curve.Center), float(e.Curve.Radius))
            return None
        vis = [g for g in (geo(e) for e in shown) if g is not None]
        for e in edges:
            try:
                g = geo(e)
            except Exception:
                g = None
            if g is None:
                continue
            if g[0] == "line" and any(w[0] == "line" and _same((w[1], w[2]), g[1], g[2], 0.02) for w in vis):
                continue
            if g[0] == "circle" and any(w[0] == "circle" and abs(w[2] - g[2]) < 0.02 and
                                        abs(w[1][0] - g[1][0]) < 0.02 and abs(w[1][1] - g[1][1]) < 0.02 for w in vis):
                continue
            out.append(g)
    return out


def _encode(v, enc):
    if enc == "utf-8":
        return v
    out = []
    for ch in v:
        try:
            ch.encode(enc)
            out.append(ch)
        except UnicodeEncodeError:
            out.append("\\U+%04X" % ord(ch))
    return "".join(out)


def _renamed(ent, rename):
    if not rename:
        return ent
    kind = ent[0][1]
    if kind in ("DIMENSION", "INSERT"):
        return [(c, rename.get(v, v) if c == 2 else v) for c, v in ent]
    return ent


def _blocks(tags):
    out, cur = [], None
    for e in split(tags):
        kind = e[0][1]
        if kind == "BLOCK":
            g = _codes(e)
            name = next((v for c, v in e if c == 2), "")
            cur = (name, int(g.get(70, 0)), (g.get(10, 0.0), g.get(20, 0.0), g.get(30, 0.0)), [])
        elif kind == "ENDBLK":
            if cur is not None:
                out.append(cur)
            cur = None
        elif cur is not None:
            cur[3].append(e)
    return out


def _style_font(font):
    return "arial.ttf" if font == "TrueType" else "txt"


def _write_r12(o, tables, blocks, ents, font):
    lo, hi = _extents(ents)
    o.add((0, "SECTION"), (2, "HEADER"), (9, "$ACADVER"), (1, "AC1009"),
          (9, "$INSBASE"), (10, "0.0"), (20, "0.0"), (30, "0.0"),
          (9, "$EXTMIN"), (10, _fmt(lo[0])), (20, _fmt(lo[1])), (30, "0.0"),
          (9, "$EXTMAX"), (10, _fmt(hi[0])), (20, _fmt(hi[1])), (30, "0.0"), (0, "ENDSEC"))
    o.add((0, "SECTION"), (2, "TABLES"))
    ltypes = [r for r in _records(tables, "LTYPE") if _name(r).upper() not in ("BYBLOCK", "BYLAYER")]
    if not any(_name(r).upper() == "CONTINUOUS" for r in ltypes):
        ltypes.insert(0, [(2, "CONTINUOUS"), (70, "0"), (3, "Solid line"), (72, "65"), (73, "0"), (40, "0.0")])
    for table, recs in (("LTYPE", ltypes), ("LAYER", _layers(tables, LAYER_RECORDS[0])), ("STYLE", _styles(tables, font))):
        o.add((0, "TABLE"), (2, table), (70, str(len(recs))))
        for r in recs:
            o.add((0, table))
            o.ext(r)
        o.add((0, "ENDTAB"))
    o.add((0, "ENDSEC"), (0, "SECTION"), (2, "BLOCKS"))
    for name, flags, base, bents in blocks:
        o.add((0, "BLOCK"), (8, "0"), (2, name), (70, str(flags)), (10, _fmt(base[0])), (20, _fmt(base[1])),
              (30, _fmt(base[2])), (3, name))
        for e in bents:
            o.ext(e)
        o.add((0, "ENDBLK"), (8, "0"))
    o.add((0, "ENDSEC"), (0, "SECTION"), (2, "ENTITIES"))
    for e in ents:
        o.ext(e)
    o.add((0, "ENDSEC"), (0, "EOF"))


LAYER_RECORDS = [None]      # the LAYER records of the file being written (convert's layers), else the source's


def _layers(tables, given=None):
    recs = [list(r) for r in given] if given else _records(tables, "LAYER")
    if not any(_name(r) == "0" for r in recs):
        recs.insert(0, [(2, "0"), (70, "0"), (62, "7"), (6, "CONTINUOUS")])
    return recs


def _styles(tables, font):
    recs = _records(tables, "STYLE") or [[(2, "STANDARD"), (70, "0"), (40, "0.0"), (41, "1.0"), (50, "0.0"),
                                          (71, "0"), (42, "2.5"), (3, "txt"), (4, "")]]
    out = []
    for r in recs:
        r = [(c, _style_font(font) if c == 3 else v) for c, v in r]
        if not any(c == 3 for c, _ in r):
            r.append((3, _style_font(font)))
        out.append(r)
    return out


def _write_r2000(o, acad, tables, blocks, ents, font):
    layouts = acad >= "AC1015"
    lo, hi = _extents(ents)
    H = o.handle
    t_vport, t_ltype, t_layer, t_style, t_view, t_ucs, t_appid, t_dim, t_br = (H() for _ in range(9))
    root, groups, layout_dict = H(), H(), H()
    br_model, br_paper = H(), H()
    lay_model, lay_paper = H(), H()
    blk_handles = [(H(), b) for b in blocks]
    body = []                      # filled below, header written last for $HANDSEED

    def table(name, th, recs, sub, extra=()):
        body.extend([(0, "TABLE"), (2, name), (5, th), (330, "0"), (100, "AcDbSymbolTable"),
                     (70, str(len(recs)))])
        body.extend(extra)
        for r in recs:
            rh = H()
            body.extend([(0, name), (105 if name == "DIMSTYLE" else 5, rh), (330, th),
                         (100, "AcDbSymbolTableRecord"), (100, sub)])
            body.extend(r(rh) if callable(r) else r)
        body.append((0, "ENDTAB"))

    w, h = max(hi[0] - lo[0], 1.0), max(hi[1] - lo[1], 1.0)
    vport = [(2, "*ACTIVE"), (70, "0"), (10, "0.0"), (20, "0.0"), (11, "1.0"), (21, "1.0"),
             (12, _fmt((lo[0] + hi[0]) / 2)), (22, _fmt((lo[1] + hi[1]) / 2)), (13, "0.0"), (23, "0.0"),
             (14, "10.0"), (24, "10.0"), (15, "10.0"), (25, "10.0"), (16, "0.0"), (26, "0.0"), (36, "1.0"),
             (17, "0.0"), (27, "0.0"), (37, "0.0"), (40, _fmt(h * 1.1)), (41, _fmt(w / h)), (42, "50.0"),
             (43, "0.0"), (44, "0.0"), (50, "0.0"), (51, "0.0"), (71, "0"), (72, "100"), (73, "1"), (74, "3"),
             (75, "0"), (76, "0"), (77, "0"), (78, "0")]
    table("VPORT", t_vport, [vport], "AcDbViewportTableRecord")
    ltypes = [[(2, "ByBlock"), (70, "0"), (3, ""), (72, "65"), (73, "0"), (40, "0.0")],
              [(2, "ByLayer"), (70, "0"), (3, ""), (72, "65"), (73, "0"), (40, "0.0")]]
    src_lt = [r for r in _records(tables, "LTYPE") if _name(r).upper() not in ("BYBLOCK", "BYLAYER")]
    if not any(_name(r).upper() == "CONTINUOUS" for r in src_lt):
        src_lt.insert(0, [(2, "CONTINUOUS"), (70, "0"), (3, "Solid line"), (72, "65"), (73, "0"), (40, "0.0")])
    table("LTYPE", t_ltype, ltypes + src_lt, "AcDbLinetypeTableRecord")
    table("LAYER", t_layer, _layers(tables, LAYER_RECORDS[0]), "AcDbLayerTableRecord")
    table("STYLE", t_style, _styles(tables, font), "AcDbTextStyleTableRecord")
    table("VIEW", t_view, [], "AcDbViewTableRecord")
    table("UCS", t_ucs, [], "AcDbUCSTableRecord")
    table("APPID", t_appid, [[(2, "ACAD"), (70, "0")]], "AcDbRegAppTableRecord")
    dims = []
    names = {_name(r).upper() for r in _records(tables, "DIMSTYLE")} | {"STANDARD"}
    for n in sorted(names):
        dims.append([(2, n), (70, "0")])
    table("DIMSTYLE", t_dim, dims, "AcDbDimStyleTableRecord", extra=[(100, "AcDbDimStyleTable")])
    # block records, with fixed handles (blocks and entities point at them)
    body.extend([(0, "TABLE"), (2, "BLOCK_RECORD"), (5, t_br), (330, "0"), (100, "AcDbSymbolTable"),
                 (70, str(2 + len(blocks)))])
    for bh, name, lay in [(br_model, "*Model_Space", lay_model), (br_paper, "*Paper_Space", lay_paper)] + \
            [(bh, b[0], None) for bh, b in blk_handles]:
        body.extend([(0, "BLOCK_RECORD"), (5, bh), (330, t_br), (100, "AcDbSymbolTableRecord"),
                     (100, "AcDbBlockTableRecord"), (2, name)])
        if layouts:
            body.append((340, lay if lay else "0"))
    body.append((0, "ENDTAB"))
    body.append((0, "ENDSEC"))
    tables_tags = body[:]
    body[:] = []

    def owned(e, owner):
        return [e[0], (5, H()), (330, owner), (100, "AcDbEntity")] + e[1:]

    bl = []
    for bh, name, flags, base, bents in [(br_model, "*Model_Space", 0, (0, 0, 0), []),
                                         (br_paper, "*Paper_Space", 0, (0, 0, 0), [])] + \
            [(bh, b[0], b[1], b[2], b[3]) for bh, b in blk_handles]:
        bl.extend([(0, "BLOCK"), (5, H()), (330, bh), (100, "AcDbEntity"), (8, "0"), (100, "AcDbBlockBegin"),
                   (2, name), (70, str(flags)), (10, _fmt(base[0])), (20, _fmt(base[1])), (30, _fmt(base[2])),
                   (3, name), (1, "")])
        for e in bents:
            bl.extend(owned(e, bh))
        bl.extend([(0, "ENDBLK"), (5, H()), (330, bh), (100, "AcDbEntity"), (8, "0"), (100, "AcDbBlockEnd")])
    en = []
    for e in ents:
        en.extend(owned(e, br_model))
    ob = [(0, "DICTIONARY"), (5, root), (330, "0"), (100, "AcDbDictionary"), (281, "1"),
          (3, "ACAD_GROUP"), (350, groups)]
    if layouts:
        ob += [(3, "ACAD_LAYOUT"), (350, layout_dict)]
    ob += [(0, "DICTIONARY"), (5, groups), (330, root), (100, "AcDbDictionary"), (281, "1")]
    if layouts:
        ob += [(0, "DICTIONARY"), (5, layout_dict), (330, root), (100, "AcDbDictionary"), (281, "1"),
               (3, "Layout1"), (350, lay_paper), (3, "Model"), (350, lay_model)]
        for lh, name, n, brh in ((lay_model, "Model", 0, br_model), (lay_paper, "Layout1", 1, br_paper)):
            ob += [(0, "LAYOUT"), (5, lh), (330, layout_dict), (100, "AcDbPlotSettings"), (1, ""),
                   (2, "none_device"), (4, ""), (6, ""), (40, "0.0"), (41, "0.0"), (42, "0.0"), (43, "0.0"),
                   (44, "0.0"), (45, "0.0"), (46, "0.0"), (47, "0.0"), (48, "0.0"), (49, "0.0"), (140, "0.0"),
                   (141, "0.0"), (142, "1.0"), (143, "1.0"), (70, "1712" if n == 0 else "688"), (72, "1"),
                   (73, "0"), (74, "5"), (7, ""), (75, "16"), (147, "1.0"), (148, "0.0"), (149, "0.0"),
                   (100, "AcDbLayout"), (1, name), (70, "1"), (71, str(n)), (10, "0.0"), (20, "0.0"),
                   (11, _fmt(hi[0])), (21, _fmt(hi[1])), (12, "0.0"), (22, "0.0"), (32, "0.0"),
                   (14, _fmt(lo[0])), (24, _fmt(lo[1])), (34, "0.0"), (15, _fmt(hi[0])), (25, _fmt(hi[1])),
                   (35, "0.0"), (146, "0.0"), (13, "0.0"), (23, "0.0"), (33, "0.0"), (16, "1.0"), (26, "0.0"),
                   (36, "0.0"), (17, "0.0"), (27, "1.0"), (37, "0.0"), (76, "0"), (330, brh)]
    seed = H()
    o.add((0, "SECTION"), (2, "HEADER"), (9, "$ACADVER"), (1, acad), (9, "$ACADMAINTVER"), (70, "0"),
          (9, "$DWGCODEPAGE"), (3, "ANSI_1252"), (9, "$INSBASE"), (10, "0.0"), (20, "0.0"), (30, "0.0"),
          (9, "$EXTMIN"), (10, _fmt(lo[0])), (20, _fmt(lo[1])), (30, "0.0"),
          (9, "$EXTMAX"), (10, _fmt(hi[0])), (20, _fmt(hi[1])), (30, "0.0"),
          (9, "$LIMMIN"), (10, "0.0"), (20, "0.0"), (9, "$LIMMAX"), (10, _fmt(hi[0])), (20, _fmt(hi[1])),
          (9, "$HANDSEED"), (5, seed))
    if acad >= "AC1015":
        u = UNITS_CODE[0]
        o.add((9, "$INSUNITS"), (70, str(u)), (9, "$MEASUREMENT"), (70, "0" if u in (1, 2) else "1"))
    o.add((0, "ENDSEC"), (0, "SECTION"), (2, "CLASSES"), (0, "ENDSEC"), (0, "SECTION"), (2, "TABLES"))
    o.ext(tables_tags)
    o.add((0, "SECTION"), (2, "BLOCKS"))
    o.ext(bl)
    o.add((0, "ENDSEC"), (0, "SECTION"), (2, "ENTITIES"))
    o.ext(en)
    o.add((0, "ENDSEC"), (0, "SECTION"), (2, "OBJECTS"))
    o.ext(ob)
    o.add((0, "ENDSEC"), (0, "EOF"))


# --------------------------------------------------------------------------- bend lines on their own layer
BEND_LAYER = "BEND_LINES"         # as the part's flat pattern DXF / DWG output (smdxf)


def bend_segments(page):
    """The bend lines of the sheet's flat pattern views, in sheet millimetres: [((x1, y1), (x2, y2))]."""
    from . import drawings as D, drawviews as DV, drawtables as DT, drawannot as DA
    out = []
    for v in D.views_of(page):
        try:
            lines = DT.bend_lines(v)
        except Exception:
            lines = []
        if not lines:
            continue
        x0, y0 = D.view_position(v)
        k = DV.view_scale(v)
        for e in lines:
            a = DA._project(v, e.Vertexes[0].Point)
            b = DA._project(v, e.Vertexes[-1].Point)
            out.append(((x0 + a.x * k, y0 + a.y * k), (x0 + b.x * k, y0 + b.y * k)))
    return out


def _same(seg, a, b, tol):
    (p, q) = seg
    def close(u, w):
        return abs(u[0] - w[0]) < tol and abs(u[1] - w[1]) < tol
    return (close(p, a) and close(q, b)) or (close(p, b) and close(q, a))


def bend_layer(path, segs, layer=BEND_LAYER, tol=0.05):
    ""


    if not segs:
        return 0
    raw = open(path, "rb").read()
    try:
        text, enc = raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        text, enc = raw.decode("cp1252", "replace"), "cp1252"
    lines = text.split("\n")
    pairs = [(i, lines[i].strip(), lines[i + 1].rstrip("\r")) for i in range(0, len(lines) - 1, 2)]
    section, ent, moved = None, None, 0

    def finish(e):
        nonlocal moved
        if e is None or e["type"] != "LINE" or e.get("layer") is None:
            return
        try:
            a = (float(e["10"]), float(e["20"]))
            b = (float(e["11"]), float(e["21"]))
        except Exception:
            return
        if any(_same(s, a, b, tol) for s in segs):
            lines[e["layer"]] = layer
            moved += 1
    handles = []
    layer_tab, layer0 = None, None              # (start, end) line index of the LAYER table's "0" record
    rec = None
    for n, (i, code, value) in enumerate(pairs):
        if code == "5" and re.match(r"^[0-9A-Fa-f]+$", value.strip()):
            handles.append(int(value.strip(), 16))
        if code == "0":
            if section == "ENTITIES":
                finish(ent)
                ent = {"type": value.strip()}
            if section == "TABLES":
                if rec is not None and rec.get("name") == "0" and layer0 is None:
                    layer0 = (rec["start"], i)
                rec = {"start": i} if value.strip() == "LAYER" and layer_tab == "LAYER" else None
                if value.strip() == "TABLE":
                    layer_tab = None
            if value.strip() == "SECTION" and n + 1 < len(pairs):
                section = pairs[n + 1][2].strip()
            elif value.strip() == "ENDSEC":
                section, ent = None, None
        elif section == "ENTITIES" and ent is not None:
            if code == "8":
                ent["layer"] = i + 1
            elif code in ("10", "20", "11", "21"):
                ent[code] = value
        elif section == "TABLES":
            if code == "2" and layer_tab is None and rec is None:
                layer_tab = value.strip()
            elif code == "2" and rec is not None:
                rec["name"] = value.strip()
    if moved and layer0 is not None and not re.search(r"\n\s*2\n%s\r?\n" % re.escape(layer), text):
        new = lines[layer0[0]:layer0[1]]
        h = (max(handles) + 1) if handles else None
        for j in range(0, len(new) - 1, 2):
            c = new[j].strip()
            if c == "2":
                new[j + 1] = layer
            elif c == "62":
                new[j + 1] = "     3"
            elif c == "5" and h is not None:
                new[j + 1] = "%X" % h
        lines[layer0[1]:layer0[1]] = new
        if h is not None:                        # the header's next free handle past the new one
            for j in range(0, len(lines) - 3, 2):
                if lines[j].strip() == "9" and lines[j + 1].strip() == "$HANDSEED":
                    try:
                        if int(lines[j + 3].strip(), 16) <= h:
                            lines[j + 3] = "%X" % (h + 1)
                    except ValueError as _fw_err:
                        _fw_log("drawdxf.py:1007", _fw_err)
                    break
    if moved:
        with open(path, "w", encoding=enc, newline="") as f:
            f.write("\n".join(lines))
    return moved


# --------------------------------------------------------------------------- layers, line weights, sheet format
FORMAT_LAYER = "FORMAT"
LINEWEIGHTS = (0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211)


def lineweight(mm):
    """The DXF line weight (1/100 mm, one of the standard ones) nearest mm."""
    want = float(mm) * 100.0
    return min(LINEWEIGHTS[1:], key=lambda w: abs(w - want))


def _weight_of(ent, layers):
    """The entity's line weight in mm: its own (370, sheet format lines) or its TechDraw layer's."""
    own = _tag(ent, 370)
    if own is not None:
        try:
            return float(own) / 100.0
        except ValueError as _fw_err:
            _fw_log("drawdxf.py:1033", _fw_err)
    if not layers:
        return None
    return (layers.get("weights") or {}).get(_tag(ent, 8))


def _relayer(ent, layers, weight, acad):
    """The converted entity on its drawing layer, with its line weight (2000 and later)."""
    if not layers:
        return ent
    rename = layers.get("rename") or {}
    out = [ent[0]]
    for c, v in ent[1:]:
        if c == 370:
            continue
        if c == 8:
            out.append((8, rename.get(v, v)))
            if weight is not None and acad >= "AC1015":
                out.append((370, str(lineweight(weight))))
            continue
        out.append((c, v))
    return out


def aci(colour):
    """The AutoCAD colour index nearest a #rrggbb colour (7: black / white)."""
    try:
        c = colour.lstrip("#")
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except Exception:
        return 7
    table = {1: (255, 0, 0), 2: (255, 255, 0), 3: (0, 255, 0), 4: (0, 255, 255), 5: (0, 0, 255), 6: (255, 0, 255),
             8: (128, 128, 128), 9: (192, 192, 192)}
    if max(r, g, b) < 60:
        return 7
    return min(table, key=lambda k: sum((a - b_) ** 2 for a, b_ in zip(table[k], (r, g, b))))


def layer_record(name, colour="#000000", on=True, linetype="CONTINUOUS"):
    n = aci(colour)
    return [(2, name), (70, "0"), (62, str(n if on else -n)), (6, linetype)]



def _mat(a, b):
    """a then b, 2D affine (a, b, c, d, e, f) as SVG's matrix."""
    return (a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1], a[0] * b[2] + a[2] * b[3],
            a[1] * b[2] + a[3] * b[3], a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5])


def _transform(text):
    m = (1, 0, 0, 1, 0, 0)
    for kind, args in re.findall(r"(\w+)\s*\(([^)]*)\)", text or ""):
        v = [float(x) for x in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", args)]
        if kind == "translate":
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif kind == "scale":
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif kind == "matrix" and len(v) == 6:
            t = tuple(v)
        elif kind == "rotate" and v:
            a = math.radians(v[0])
            t = (math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0, 0)
            if len(v) == 3:
                t = _mat(_mat((1, 0, 0, 1, v[1], v[2]), t), (1, 0, 0, 1, -v[1], -v[2]))
        else:
            continue
        m = _mat(m, t)
    return m


def _path_points(d):
    """The polylines of an SVG path (M, L, H, V, Z, absolute and relative; curves by their end points)."""
    toks = re.findall(r"[MmLlHhVvZzCcSsQqTtAa]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", d or "")
    out, cur, x, y, sx, sy, cmd, i = [], [], 0.0, 0.0, 0.0, 0.0, "M", 0
    need = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}
    while i < len(toks):
        tk = toks[i]
        if tk.isalpha():
            cmd = tk
            i += 1
            if cmd in "Zz":
                if cur:
                    cur.append(cur[0])
                    out.append(cur)
                cur = []
                x, y = sx, sy
            continue
        n = need[cmd.upper()]
        try:
            v = [float(t) for t in toks[i:i + n]]
        except ValueError:
            break
        if len(v) < n:
            break
        i += n
        rel = cmd.islower()
        u = cmd.upper()
        if u == "H":
            x = x + v[0] if rel else v[0]
        elif u == "V":
            y = y + v[0] if rel else v[0]
        else:
            x, y = (x + v[-2], y + v[-1]) if rel else (v[-2], v[-1])
        if u == "M":
            if len(cur) > 1:
                out.append(cur)
            cur = [(x, y)]
            sx, sy = x, y
            cmd = "l" if rel else "L"
        else:
            cur.append((x, y))
    if len(cur) > 1:
        out.append(cur)
    return out


def _stroke(el, inherited):
    w = el.get("stroke-width")
    st = el.get("style") or ""
    m = re.search(r"stroke-width\s*:\s*([\d.]+)", st)
    if m:
        w = m.group(1)
    try:
        return float(re.match(r"[\d.]+", w).group(0)) if w else inherited
    except Exception as _fw_err:
        _fw_log("drawdxf.py:1160", _fw_err)
        return inherited


def format_entities(svg_path, texts=None, layer=FORMAT_LAYER):
    """The sheet format at svg_path as DXF entities in sheet mm (Y up), on layer: its lines, rectangles and
    circles, and its texts (the title block fields with their values from texts {field: value})."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(svg_path).getroot()
    except Exception as _fw_err:
        _fw_log("drawdxf.py:1171", _fw_err)
        return []
    vb = [float(x) for x in re.findall(r"[-+]?[\d.]+", root.get("viewBox", ""))]
    h = vb[3] if len(vb) == 4 else float(re.match(r"[\d.]+", root.get("height", "0")).group(0) or 0)
    if len(vb) == 4 and vb[1]:
        h += vb[1]
    texts = texts or {}
    out = []
    ed = "{https://www.freecad.org/wiki/index.php?title=Svg_Namespace}editable"

    def P(m, x, y):
        X = m[0] * x + m[2] * y + m[4]
        Y = m[1] * x + m[3] * y + m[5]
        return X, h - Y

    def lw(w, m):
        return None if w is None else w * math.sqrt(abs(m[0] * m[3] - m[1] * m[2]))

    def line(a, b, w):
        e = [(0, "LINE"), (8, layer)]
        if w is not None:
            e.append((370, str(lineweight(w))))
        out.append(e + [(10, _fmt(a[0])), (20, _fmt(a[1])), (30, "0.0"), (11, _fmt(b[0])), (21, _fmt(b[1])),
                        (31, "0.0")])

    def walk(el, m, w):
        tag = el.tag.split("}")[-1]
        if tag in ("metadata", "defs", "title", "desc", "style"):
            return
        if (el.get("display") == "none") or "display:none" in (el.get("style") or "").replace(" ", ""):
            return
        m = _mat(m, _transform(el.get("transform")))
        w = _stroke(el, w)
        fill_only = (el.get("stroke") == "none") and tag != "text"
        if tag == "rect" and not fill_only:
            x, y = float(el.get("x", 0)), float(el.get("y", 0))
            ww, hh = float(el.get("width", 0)), float(el.get("height", 0))
            pts = [P(m, x, y), P(m, x + ww, y), P(m, x + ww, y + hh), P(m, x, y + hh), P(m, x, y)]
            for a, b in zip(pts, pts[1:]):
                line(a, b, lw(w, m))
        elif tag == "line" and not fill_only:
            line(P(m, float(el.get("x1", 0)), float(el.get("y1", 0))),
                 P(m, float(el.get("x2", 0)), float(el.get("y2", 0))), lw(w, m))
        elif tag in ("polyline", "polygon") and not fill_only:
            v = [float(x) for x in re.findall(r"[-+]?[\d.]+(?:[eE][-+]?\d+)?", el.get("points", ""))]
            pts = [P(m, v[i], v[i + 1]) for i in range(0, len(v) - 1, 2)]
            if tag == "polygon" and pts:
                pts.append(pts[0])
            for a, b in zip(pts, pts[1:]):
                line(a, b, lw(w, m))
        elif tag == "path" and not fill_only:
            for poly in _path_points(el.get("d")):
                pts = [P(m, x, y) for x, y in poly]
                for a, b in zip(pts, pts[1:]):
                    if abs(a[0] - b[0]) > 1e-6 or abs(a[1] - b[1]) > 1e-6:
                        line(a, b, lw(w, m))
        elif tag == "circle" and not fill_only:
            c = P(m, float(el.get("cx", 0)), float(el.get("cy", 0)))
            r = float(el.get("r", 0)) * math.sqrt(abs(m[0] * m[3] - m[1] * m[2]))
            e = [(0, "CIRCLE"), (8, layer)]
            ww = lw(w, m)
            if ww is not None:
                e.append((370, str(lineweight(ww))))
            out.append(e + [(10, _fmt(c[0])), (20, _fmt(c[1])), (30, "0.0"), (40, _fmt(r))])
        elif tag == "text":
            field = el.get(ed)
            spans = [s for s in el.iter() if s.tag.split("}")[-1] == "tspan"] or [el]
            value = texts.get(field) if field else None
            lines = str(value).split("\n") if value is not None else ["".join(s.itertext()) for s in spans[:1]] + \
                ["".join(s.itertext()) for s in spans[1:]]
            size = el.get("font-size") or ""
            for s in spans:
                size = s.get("font-size") or size
            m2 = re.search(r"font-size\s*:\s*([\d.]+)", el.get("style") or "")
            try:
                size = float(re.match(r"[\d.]+", size).group(0)) if size else (float(m2.group(1)) if m2 else 3.5)
            except Exception:
                size = 3.5
            size *= math.sqrt(abs(m[0] * m[3] - m[1] * m[2]))
            anchor = el.get("text-anchor") or "start"
            align = {"start": 0, "middle": 1, "end": 2}.get(anchor, 0)
            for k, txt in enumerate(lines):
                txt = txt.strip("\n")
                if not txt.strip():
                    continue
                s = spans[k] if k < len(spans) else spans[-1]
                x = float(s.get("x") or el.get("x") or 0)
                y = float(s.get("y") or el.get("y") or 0) + (k - min(k, len(spans) - 1)) * size * 1.4
                a = P(m, x, y)
                e = [(0, "TEXT"), (8, layer), (10, _fmt(a[0])), (20, _fmt(a[1])), (30, "0.0"), (40, _fmt(size)),
                     (1, txt)]
                if align:
                    e += [(72, str(align)), (11, _fmt(a[0])), (21, _fmt(a[1])), (31, "0.0")]
                out.append(e)
            return
        for ch in el:
            walk(ch, m, w)

    walk(root, (1, 0, 0, 1, 0, 0), None)
    return out


def sheet_layers(page, visible_mm=0.35, thin_mm=0.18):
    """{"rename", "records", "weights"} for convert: each view's TechDraw layer (its object name) to the
    drawing layer it is on (layer 0 when none; FORMAT for what was drawn on the sheet format), the drawing's
    layers as LAYER records (colour, off when hidden), the views' lines at visible_mm and annotations at
    thin_mm."""
    from . import drawings as D
    try:
        from . import drawextras as DX
    except Exception:
        DX = None
    try:
        from . import drawsheet as DS
    except Exception:
        DS = None
    rename, weights = {}, {}
    seen = set()

    def visit(o):
        if o is None or o.Name in seen:
            return
        seen.add(o.Name)
        name = getattr(o, "SWLayer", "") or getattr(o, "FWLayer", "")
        if not name and DS is not None and DS.on_format(o):
            name = FORMAT_LAYER
        rename[o.Name] = name or "0"
        if o.isDerivedFrom("TechDraw::DrawViewPart"):
            weights[o.Name] = visible_mm
        else:
            weights[o.Name] = thin_mm
        for ch in list(getattr(o, "Views", []) or []):
            visit(ch)
    for o in list(page.Views or []):
        visit(o)
    records = [layer_record("0")]
    if DX is not None:
        try:
            for name, colour, on in DX.layers(page):
                if name not in ("-None-", "0"):
                    records.append(layer_record(name, colour, on != "0"))
        except Exception as _fw_err:
            _fw_log("drawdxf.py:1310", _fw_err)
    if not any(_name(r) == FORMAT_LAYER for r in records):
        records.append(layer_record(FORMAT_LAYER))
    return {"rename": rename, "records": records, "weights": weights}


def center_marks(page, linetype="CENTER", ext=2.5):
    ""

    import math as _m
    from . import drawings as D
    out = []
    for v in D.views_of(page):
        vo = getattr(v, "ViewObject", None)
        if vo is None or not getattr(vo, "ArcCenterMarks", False) or getattr(v, "SWShadeOf", ""):
            continue
        try:
            edges = v.getVisibleEdges()
        except Exception as _fw_err:
            _fw_log("drawdxf.py:1332", _fw_err)
            continue
        x0, y0 = D.view_position(v)
        rot = _m.radians(float(getattr(v, "Rotation", 0.0) or 0.0))
        c, s_ = _m.cos(rot), _m.sin(rot)
        done = []
        for e in edges:
            if e.Curve.TypeId != "Part::GeomCircle":
                continue
            p = e.Curve.Center
            x, y = p.x, -p.y
            cx, cy = x0 + x * c - y * s_, y0 + x * s_ + y * c
            r = float(e.Curve.Radius)
            if any(abs(cx - a) < 0.01 and abs(cy - b) < 0.01 for a, b in done):
                continue
            done.append((cx, cy))
            k = r + ext
            for (ax, ay, bx, by) in ((cx - k * c, cy - k * s_, cx + k * c, cy + k * s_),
                                     (cx + k * s_, cy - k * c, cx - k * s_, cy + k * c)):
                out.append([(0, "LINE"), (8, v.Name), (6, linetype), (370, "18"), (10, _fmt(ax)), (20, _fmt(ay)), (30, "0.0"),
                            (11, _fmt(bx)), (21, _fmt(by)), (31, "0.0")])
    return out


def view_captions(page, size=3.5, layer="0"):
    ""

    from . import drawings as D, drawviews as DV
    out = []
    for v in D.views_of(page):
        text = str(getattr(v, "Caption", "") or "").strip()
        if not text or getattr(v, "SWShadeOf", ""):
            continue
        try:
            a, b, c, _e = DV.view_box(v)
        except Exception:
            continue
        x = (a + c) / 2.0
        for j, line in enumerate(text.splitlines()):
            y = b - 6.0 - j * size * 1.6
            out.append([(0, "TEXT"), (8, layer), (10, _fmt(x)), (20, _fmt(y)), (30, "0.0"), (40, _fmt(size)),
                        (1, line), (72, "1"), (11, _fmt(x)), (21, _fmt(y)), (31, "0.0")])
    return out


def _section_faces(v):
    """The faces a section view cuts (on its section plane) in 3D, and the piece it keeps."""
    import FreeCAD as App
    import Part
    from . import drawviews as DV
    shapes = [s for s in (getattr(o, "Shape", None) for o in DV.source_shapes(v)) if s is not None and not s.isNull()]
    if not shapes:
        return [], None
    whole = shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes)
    o_, n_ = App.Vector(v.SectionOrigin), App.Vector(v.SectionNormal)
    if n_.Length < 1e-9:
        return [], None
    n_.normalize()
    big = whole.BoundBox.DiagonalLength * 4 + 100.0
    u = n_.cross(App.Vector(0, 0, 1))
    if u.Length < 1e-6:
        u = n_.cross(App.Vector(1, 0, 0))
    u.normalize()
    w = n_.cross(u)
    face = Part.makePlane(2 * big, 2 * big, o_ - u * big - w * big, n_, u)
    kept = whole.cut(face.extrude(n_ * big))          # the side away from SectionNormal stays
    cut = []
    for f in kept.Faces:
        if type(f.Surface).__name__ != "Plane" or not all(abs((p.Point - o_).dot(n_)) < 1e-5 for p in f.Vertexes):
            continue
        try:
            if abs(abs(f.normalAt(0, 0).dot(n_)) - 1.0) > 1e-6:
                continue
        except Exception:
            continue
        cut.append(f)
    return cut, kept


def section_hatches(page, layer="0", pattern="ANSI31", scale=1.0):
    ""


    import math as _m
    import FreeCAD as App
    from . import drawings as D, drawviews as DV
    out = []
    for v in D.views_of(page):
        if v.TypeId not in ("TechDraw::DrawViewSection", "TechDraw::DrawComplexSection") or getattr(v, "SWShadeOf", ""):
            continue
        if str(getattr(v, "CutSurfaceDisplay", "PatHatch")) in ("Hide", "None"):
            continue
        try:
            faces, kept = _section_faces(v)
            if not faces:
                continue
            k = DV.view_scale(v)
            dn = App.Vector(v.Direction)
            dn.normalize()
            vx = App.Vector(v.XDirection)
            vx.normalize()
            vy = dn.cross(vx)
            x0, y0 = D.view_position(v)
            rot = _m.radians(float(getattr(v, "Rotation", 0.0) or 0.0))
            c, s_ = _m.cos(rot), _m.sin(rot)
            drawn = []
            for e in v.getVisibleEdges():
                for p in (e.Vertexes[0].Point, e.Vertexes[-1].Point):
                    x, y = p.x, -p.y
                    drawn.append((x0 + x * c - y * s_, y0 + x * s_ + y * c))
            if not drawn:
                continue
            pts3 = [p.Point for p in kept.Vertexes]
            best = None
            for sign in (1.0, -1.0):
                loc = [(p.dot(vx) * k, sign * p.dot(vy) * k) for p in pts3]
                mx = (min(q[0] for q in loc) + max(q[0] for q in loc)) / 2.0
                my = (min(q[1] for q in loc) + max(q[1] for q in loc)) / 2.0
                dx = (min(q[0] for q in drawn) + max(q[0] for q in drawn)) / 2.0
                dy = (min(q[1] for q in drawn) + max(q[1] for q in drawn)) / 2.0
                tx, ty = dx - mx, dy - my
                hit = sum(1 for q in loc if any(abs(q[0] + tx - a) < 0.05 and abs(q[1] + ty - b) < 0.05 for a, b in drawn))
                if best is None or hit > best[0]:
                    best = (hit, sign, tx, ty)
            hit, sign, tx, ty = best
            if hit < max(3, len(pts3) // 3):
                continue                    # the projection does not land on the view's edges: leave it out

            def sheet(p):
                return (p.dot(vx) * k + tx, sign * p.dot(vy) * k + ty)
            for f in faces:
                loops = []
                for wire in [f.OuterWire] + [w_ for w_ in f.Wires if not w_.isSame(f.OuterWire)]:
                    pts = [sheet(p) for p in wire.discretize(Deflection=0.01)]
                    if len(pts) > 2 and abs(pts[0][0] - pts[-1][0]) < 1e-6 and abs(pts[0][1] - pts[-1][1]) < 1e-6:
                        pts = pts[:-1]
                    if len(pts) > 2:
                        loops.append(pts)
                if not loops:
                    continue
                e = [(0, "HATCH"), (8, layer), (100, "AcDbHatch"), (10, "0.0"), (20, "0.0"), (30, "0.0"),
                     (210, "0.0"), (220, "0.0"), (230, "1.0"), (2, pattern), (70, "0"), (71, "0"), (91, str(len(loops)))]
                for j, pts in enumerate(loops):
                    e += [(92, "3" if j == 0 else "2"), (72, "0"), (73, "1"), (93, str(len(pts)))]
                    for x, y in pts:
                        e += [(10, _fmt(x)), (20, _fmt(y))]
                    e += [(97, "0")]
                e += [(75, "0"), (76, "1"), (52, "0.0"), (41, _fmt(scale)), (77, "0"), (78, "1"),
                      (53, "45.0"), (43, "0.0"), (44, "0.0"), (45, _fmt(-2.245 * scale)), (46, _fmt(2.245 * scale)),
                      (79, "0"), (98, "0")]
                out.append(e)
        except Exception as _fw_err:
            _fw_log("drawdxf.py:section_hatches", _fw_err)
    return out


CENTER_LTYPES = (("CENTER", "Center ____ _ ____ _ ____", (31.75, -6.35, 6.35, -6.35)),
                 ("SLD-Center", "Center ____ _ ____", (12.0, -3.0, 2.0, -3.0)))


def center_linetype(style):
    return CENTER_LTYPES[1][0] if style == LINE_STYLES[1] else CENTER_LTYPES[0][0]
