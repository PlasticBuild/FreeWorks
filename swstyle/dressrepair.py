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

import FreeCAD as App

PROP = "FwRefGeometry"


def _f(v):
    return ",".join("%.9g" % x for x in (v.x, v.y, v.z))


def _v(text):
    x, y, z = (float(t) for t in text.split(","))
    return App.Vector(x, y, z)


def signature(shape, name):
    """(kind, point, direction, size) of shape's element name, else None."""
    try:
        el = shape.getElement(name)
    except Exception:
        return None
    try:
        if name.startswith("Edge"):
            t = (el.FirstParameter + el.LastParameter) / 2.0
            d = el.tangentAt(t)
            return ("Edge", el.valueAt(t), d, el.Length)
        if name.startswith("Face"):
            c = el.CenterOfMass
            u, v = el.Surface.parameter(c)
            return ("Face", c, el.normalAt(u, v), el.Area)
    except Exception:
        return None
    return None


def store(feature):
    """Remembers the geometry of the feature's items (called on the PropertyManager's OK)."""
    try:
        base, subs = feature.Base[0], list(feature.Base[1])
    except Exception:
        return
    if base is None or not subs:
        return
    rows = []
    for name in subs:
        sig = signature(base.Shape, name)
        if sig is not None:
            rows.append("%s|%s|%s|%.9g" % (name, _f(sig[1]), _f(sig[2]), sig[3]))
    clean = "Touched" not in feature.State
    if PROP not in feature.PropertiesList:
        feature.addProperty("App::PropertyStringList", PROP, "FreeCAD", "Edges and faces as made (Repair Missing References)")
        feature.setEditorMode(PROP, 2)
    if list(getattr(feature, PROP)) != rows:
        setattr(feature, PROP, rows)
    if clean:
        try:
            feature.purgeTouched()      # a note on the feature, not a change: no rebuild mark
        except Exception as _fw_err:
            _fw_log("dressrepair.py:81", _fw_err)


def stored(feature):
    out = {}
    for row in getattr(feature, PROP, []) or []:
        try:
            name, p, d, size = row.split("|")
            out[name] = (name[:4], _v(p), _v(d), float(size))
        except Exception:
            continue
    return out


def _scale(shape):
    try:
        return max(shape.BoundBox.DiagonalLength, 1e-6)
    except Exception:
        return 1.0


def _same(a, b, scale):
    """True when signature b is the remembered signature a, to modelling precision."""
    if a is None or b is None or a[0] != b[0]:
        return False
    tol = scale * 1e-6 + 1e-7
    return (a[1] - b[1]).Length < tol and abs(abs(a[2].dot(b[2])) - 1) < 1e-6 and abs(a[3] - b[3]) < tol + abs(a[3]) * 1e-6


def _plain(name):
    return name.lstrip("?")     # FreeCAD marks a reference it lost with a leading "?"


def missing(feature, base=None, items=None):
    """The items that are gone, or whose name now gives another edge or face than the one
    remembered (another element matches the remembered one far better). An item that only moved
    or changed size with the part (still the nearest) is not missing."""
    base = base or (feature.Base[0] if getattr(feature, "Base", None) else None)
    if base is None:
        return []
    items = list(feature.Base[1]) if items is None else list(items)
    mem = stored(feature)
    shape = base.Shape
    scale = _scale(shape)
    out = []
    for n in items:
        now = signature(shape, _plain(n)) if not n.startswith("?") else None
        if now is None:
            out.append(n)
            continue
        if n not in mem or _same(mem[n], now, scale):
            continue
        mine = _score(mem[n], now, scale)
        other = best_match(shape, mem[n])
        if other is not None and other != n:
            theirs = _score(mem[n], signature(shape, other), scale)
            if mine is None or theirs * 2 + 1e-6 < mine:
                out.append(n)
    return out


def _score(a, b, scale):
    if a[0] != b[0]:
        return None
    gap = (a[1] - b[1]).Length / scale
    turn = 1 - abs(a[2].dot(b[2]))
    size = abs(a[3] - b[3]) / max(a[3], b[3], 1e-9)
    return gap + turn + 0.5 * size


def best_match(shape, sig, taken=(), limit=0.15):
    """The element name of shape that matches remembered sig best, or None when nothing is near."""
    scale = _scale(shape)
    pool = shape.Edges if sig[0] == "Edge" else shape.Faces
    word = sig[0]
    best = None
    for i in range(len(pool)):
        name = "%s%d" % (word, i + 1)
        if name in taken:
            continue
        cand = signature(shape, name)
        if cand is None:
            continue
        s = _score(sig, cand, scale)
        if s is not None and (best is None or s < best[0]):
            best = (s, name)
    return best[1] if best is not None and best[0] <= limit else None


def repair(feature, base=None, items=None):
    """(new items, names that found no match): each missing item replaced by its best match."""
    base = base or feature.Base[0]
    items = list(feature.Base[1]) if items is None else list(items)
    gone = missing(feature, base, items)
    if not gone:
        return items, []
    mem = stored(feature)
    mem.update({n: mem[_plain(n)] for n in gone if n not in mem and _plain(n) in mem})
    shape = base.Shape
    keep = [n for n in items if n not in gone]
    out, unmatched = [], []
    for n in items:
        if n not in gone:
            out.append(n)
            continue
        m = best_match(shape, mem[n], taken=set(keep) | set(out)) if n in mem else None
        if m is None:
            unmatched.append(n)
            out.append(n)
        else:
            out.append(m)
    return out, unmatched


def remap_stored(feature, old_items, new_items):
    """After a repair the remembered rows follow the new names (so the next check is clean)."""
    mem = getattr(feature, PROP, []) or []
    rows = []
    for row in mem:
        name = row.split("|", 1)[0]
        if name in old_items:
            k = old_items.index(name)
            rows.append(new_items[k] + "|" + row.split("|", 1)[1])
        else:
            rows.append(row)
    clean = "Touched" not in feature.State
    setattr(feature, PROP, rows)
    if clean:
        try:
            feature.purgeTouched()
        except Exception as _fw_err:
            _fw_log("dressrepair.py:212", _fw_err)
