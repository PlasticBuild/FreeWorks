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
import os

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtWidgets
except Exception:   # pragma: no cover
    Gui = None

STANDARDS = ("ANSI Metric", "DIN", "ISO")     # the metric tables; ANSI Inch has none of these here
PROP = "FwToolboxPart"     # "<kind>;<size>;<length>;<std>;<display>" on the part
BORE_PROP = "FwBoreFace"   # the inner cylinder (on a shaft)
OUTER_PROP = "FwOuterFace" # the outer cylinder (in a bore)
SEAT_PROP = "FwSeatFace"   # a side face

# bearing series: designation -> (bore d, outside D, width B, C kN, C0 kN)
BALL = {
    "6000": (10, 26, 8, 4.75, 1.96), "6001": (12, 28, 8, 5.4, 2.36), "6002": (15, 32, 9, 5.85, 2.85),
    "6003": (17, 35, 10, 6.37, 3.25), "6004": (20, 42, 12, 9.95, 5.0), "6005": (25, 47, 12, 11.9, 6.55),
    "6006": (30, 55, 13, 13.8, 8.3), "6007": (35, 62, 14, 16.8, 10.2), "6008": (40, 68, 15, 17.8, 11.6),
    "6009": (45, 75, 16, 22.1, 14.6), "6010": (50, 80, 16, 22.9, 16.0),
    "6200": (10, 30, 9, 5.4, 2.36), "6201": (12, 32, 10, 7.28, 3.1), "6202": (15, 35, 11, 8.06, 3.75),
    "6203": (17, 40, 12, 9.95, 4.75), "6204": (20, 47, 14, 13.5, 6.55), "6205": (25, 52, 15, 14.8, 7.8),
    "6206": (30, 62, 16, 20.3, 11.2), "6207": (35, 72, 17, 27.0, 15.3), "6208": (40, 80, 18, 32.5, 19.0),
    "6209": (45, 85, 19, 35.1, 21.6), "6210": (50, 90, 20, 37.1, 23.2),
    "6300": (10, 35, 11, 8.52, 3.4), "6301": (12, 37, 12, 10.1, 4.15), "6302": (15, 42, 13, 11.9, 5.4),
    "6303": (17, 47, 14, 14.3, 6.55), "6304": (20, 52, 15, 16.8, 7.8), "6305": (25, 62, 17, 23.4, 11.6),
    "6306": (30, 72, 19, 29.6, 16.0), "6307": (35, 80, 21, 35.1, 19.0), "6308": (40, 90, 23, 42.3, 24.0),
    "6309": (45, 100, 25, 55.3, 31.5), "6310": (50, 110, 27, 65.0, 38.0),
}
ROLLER = {
    "NU 202": (15, 35, 11, 12.5, 10.2), "NU 203": (17, 40, 12, 17.2, 14.3), "NU 204": (20, 47, 14, 28.5, 22.0),
    "NU 205": (25, 52, 15, 32.5, 27.0), "NU 206": (30, 62, 16, 44.0, 36.5), "NU 207": (35, 72, 17, 56.0, 48.0),
    "NU 208": (40, 80, 18, 62.0, 53.0), "NU 209": (45, 85, 19, 69.5, 64.0), "NU 210": (50, 90, 20, 73.5, 69.5),
}
THRUST = {
    "51100": (10, 24, 9, 10.0, 14.0), "51101": (12, 26, 9, 10.4, 15.3), "51102": (15, 28, 9, 10.6, 16.6),
    "51103": (17, 30, 9, 11.4, 19.0), "51104": (20, 35, 10, 15.1, 24.5), "51105": (25, 42, 11, 19.9, 35.5),
    "51106": (30, 47, 11, 20.3, 39.0), "51107": (35, 52, 12, 22.1, 45.0), "51108": (40, 60, 13, 26.5, 57.0),
    "51109": (45, 65, 14, 27.0, 61.0), "51110": (50, 70, 14, 27.0, 65.5),
}
# DIN 471 (shaft d1): ring thickness s, groove diameter d2, groove width m
EXTERNAL = {6: (0.7, 5.7, 0.8), 8: (0.8, 7.6, 0.9), 10: (1.0, 9.6, 1.1), 12: (1.0, 11.5, 1.1),
            15: (1.0, 14.3, 1.1), 17: (1.0, 16.2, 1.1), 20: (1.2, 19.0, 1.3), 25: (1.2, 23.9, 1.3),
            30: (1.5, 28.6, 1.6), 35: (1.5, 33.0, 1.6), 40: (1.75, 37.5, 1.85), 45: (1.75, 42.5, 1.85),
            50: (2.0, 47.0, 2.15)}
# DIN 472 (bore d1): ring thickness s, groove diameter d2, groove width m
INTERNAL = {10: (1.0, 10.4, 1.1), 12: (1.0, 12.5, 1.1), 15: (1.0, 15.7, 1.1), 17: (1.0, 17.8, 1.1),
            20: (1.0, 21.0, 1.1), 25: (1.2, 26.2, 1.3), 30: (1.2, 31.4, 1.3), 35: (1.5, 37.0, 1.6),
            40: (1.75, 42.5, 1.85), 47: (1.75, 49.5, 1.85), 52: (2.0, 55.0, 2.15), 62: (2.0, 65.0, 2.15)}
# ISO 3601-1 class A: cross section d2 -> inside diameters d1
O_RINGS = {
    1.78: (2.9, 4.47, 6.07, 7.65, 9.25, 10.82, 12.42, 14.0, 15.6, 17.17, 18.77, 20.35, 21.95, 23.52, 25.12),
    2.62: (10.77, 12.37, 14.0, 15.54, 17.12, 18.72, 20.29, 21.89, 23.47, 25.07, 26.64, 28.24, 29.82, 31.42,
           33.0, 34.59, 37.77, 40.94, 44.12, 47.29, 50.47),
    3.53: (18.64, 20.22, 21.82, 23.39, 24.99, 26.57, 28.17, 29.74, 31.34, 32.92, 34.52, 36.09, 37.69, 40.87,
           44.04, 47.22, 50.39, 53.57, 56.74, 59.92, 63.09, 66.27, 69.44),
    5.33: (37.47, 40.64, 43.82, 46.99, 50.17, 53.34, 56.52, 59.69, 62.87, 66.04, 69.22, 72.39, 75.57, 82.27,
           88.62, 94.97, 101.32),
}
# DIN 6885 A parallel keys: shaft over (mm) -> width b, height h
KEYS = ((6, 2, 2), (8, 3, 3), (10, 4, 4), (12, 5, 5), (17, 6, 6), (22, 8, 7), (30, 10, 8), (38, 12, 8),
        (44, 14, 9), (50, 16, 10), (58, 18, 11), (65, 20, 12), (75, 22, 14))
KEY_LENGTHS = (6, 8, 10, 12, 14, 16, 18, 20, 22, 25, 28, 32, 36, 40, 45, 50, 56, 63, 70, 80, 90, 100, 110, 125)
# DIN 179 A headless drill bushings: drill size up to (mm) -> outside d2, lengths (short, medium, long)
BUSH = ((1.0, 3, (6, 9)), (1.8, 4, (6, 9)), (2.6, 5, (8, 12, 16)), (3.3, 6, (8, 12, 16)), (4.0, 7, (8, 12, 16)),
        (5.0, 8, (8, 12, 16)), (6.0, 10, (10, 16, 20)), (8.0, 12, (10, 16, 20)), (10.0, 15, (12, 20, 25)),
        (12.0, 18, (12, 20, 25)), (15.0, 22, (16, 28, 36)), (18.0, 26, (16, 28, 36)), (22.0, 30, (20, 36, 45)),
        (26.0, 35, (20, 36, 45)))
BUSH_DRILLS = (2.0, 2.5, 3.0, 3.3, 4.0, 4.2, 5.0, 6.0, 6.8, 8.0, 8.5, 10.0, 10.2, 12.0, 14.0, 16.0, 18.0, 20.0)
DISPLAYS = ("Detailed", "Simplified")

# key: (folder, name, {standard: designation}, has a length)
KINDS = {
    "deep-groove-bearing": ("Bearings/Ball Bearings", "Deep Groove Ball Bearing",
                            {"ISO": "ISO 15", "DIN": "DIN 625", "ANSI Metric": "ABMA 20"}, False),
    "cylindrical-roller-bearing": ("Bearings/Roller Bearings", "Cylindrical Roller Bearing",
                                   {"ISO": "ISO 15", "DIN": "DIN 5412", "ANSI Metric": "ABMA 20"}, False),
    "thrust-ball-bearing": ("Bearings/Thrust Bearings", "Thrust Ball Bearing",
                            {"ISO": "ISO 104", "DIN": "DIN 711", "ANSI Metric": "ABMA 24.1"}, False),
    "drill-bushing": ("Jig Bushings", "Headless Drill Bushing",
                      {"ISO": "ISO 4247", "DIN": "DIN 179 A", "ANSI Metric": "ISO 4247"}, True),
    "parallel-key": ("Keys", "Parallel Key", {"ISO": "ISO 773", "DIN": "DIN 6885 A", "ANSI Metric": "ISO 773"}, True),
    "o-ring": ("O-Rings", "O-Ring", {"ISO": "ISO 3601-1", "DIN": "DIN 3771", "ANSI Metric": "ISO 3601-1"}, False),
    "external-ring": ("Retaining Rings/External", "External Retaining Ring",
                      {"ISO": "DIN 471", "DIN": "DIN 471", "ANSI Metric": "B27.7M"}, False),
    "internal-ring": ("Retaining Rings/Internal", "Internal Retaining Ring",
                      {"ISO": "DIN 472", "DIN": "DIN 472", "ANSI Metric": "B27.7M"}, False),
}
BEARINGS = ("deep-groove-bearing", "cylindrical-roller-bearing", "thrust-ball-bearing")
ON_SHAFT = ("deep-groove-bearing", "cylindrical-roller-bearing", "thrust-ball-bearing", "external-ring",
            "o-ring", "parallel-key")
IN_BORE = ("deep-groove-bearing", "cylindrical-roller-bearing", "thrust-ball-bearing", "internal-ring",
           "o-ring", "drill-bushing")


# --------------------------------------------------------------------------- the tree
def _url():
    from . import toolbox
    return toolbox.URL


def kind_of(url):
    if not isinstance(url, str) or not url.startswith(_url()):
        return None
    key = url.rstrip("/").rsplit("/", 1)[-1]
    return key if key in KINDS else None


def handles(url):
    return kind_of(url) is not None


def folders(url_std):
    """[(path, label)] of the folders these parts add under one standard's Toolbox folder."""
    std = url_std[len(_url()):].strip("/")
    if std not in STANDARDS:
        return []
    out, seen = [], set()
    for folder, _n, _s, _l in KINDS.values():
        parts = folder.split("/")
        for i in range(len(parts)):
            p = url_std + "/" + "/".join(parts[:i + 1])
            if p not in seen:
                seen.add(p)
                out.append((p, parts[i]))
    return out


def items(url_std, rel):
    std = url_std[len(_url()):].strip("/")
    if std not in STANDARDS:
        return []
    return [(url_std + "/" + key, "%s %s" % (spec[2][std], spec[1]))
            for key, spec in KINDS.items() if spec[0] == rel]


def owns(rel):
    """True when a folder path (below the standard) is one of ours."""
    return any(spec[0] == rel or spec[0].startswith(rel + "/") for spec in KINDS.values())


def ordered(std_url, rows):
    """A standard's folder rows with the top-level folders A to Z (their sub-folders kept under them)."""
    groups, order = {}, []
    for p, l in rows:
        rel = p[len(std_url):].strip("/")
        top = rel.split("/")[0] if rel else ""
        if top not in groups:
            groups[top] = []
            order.append(top)
        groups[top].append((p, l))
    return [r for top in sorted(order, key=lambda t: t.lower()) for r in groups[top]]


# --------------------------------------------------------------------------- sizes
def table(kind):
    return {"deep-groove-bearing": BALL, "cylindrical-roller-bearing": ROLLER, "thrust-ball-bearing": THRUST}.get(kind)


def sizes(kind):
    """The sizes of a kind, as their text, in the order shown."""
    if kind in BEARINGS:
        return list(table(kind))
    if kind == "external-ring":
        return [str(d) for d in EXTERNAL]
    if kind == "internal-ring":
        return [str(d) for d in INTERNAL]
    if kind == "o-ring":
        return ["%g x %g" % (d1, d2) for d2 in sorted(O_RINGS) for d1 in O_RINGS[d2]]
    if kind == "parallel-key":
        return ["%d x %d" % (b, h) for _o, b, h in KEYS]
    if kind == "drill-bushing":
        return ["%g" % d for d in BUSH_DRILLS]
    return []


def lengths(kind, size):
    if kind == "parallel-key":
        b = int(str(size).split("x")[0])
        return [L for L in KEY_LENGTHS if L >= 2 * b and L <= 18 * b]
    if kind == "drill-bushing":
        return list(_bush(float(size))[1])
    return []


def _bush(drill):
    for over, d2, ls in BUSH:
        if drill <= over + 1e-9:
            return d2, ls
    return BUSH[-1][1], BUSH[-1][2]


def _o_ring(size):
    d1, d2 = (float(x) for x in str(size).split("x"))
    return d1, d2


def dims(kind, size):
    """(inner diameter, outer diameter, width) of a size: what goes on a shaft and in a bore."""
    if kind in BEARINGS:
        d, D, B = table(kind)[size][:3]
        return float(d), float(D), float(B)
    if kind == "external-ring":
        s, d2, _m = EXTERNAL[int(size)]
        return d2, float(size) + 2 * _ring_band(float(size)), s
    if kind == "internal-ring":
        s, d2, _m = INTERNAL[int(size)]
        return float(size) - 2 * _ring_band(float(size)), d2, s
    if kind == "o-ring":
        d1, d2 = _o_ring(size)
        return d1, d1 + 2 * d2, d2
    if kind == "parallel-key":
        b, h = (int(x) for x in str(size).split("x"))
        return 0.0, float(b), float(h)
    if kind == "drill-bushing":
        return float(size), float(_bush(float(size))[0]), 0.0
    raise ValueError(kind)


def _ring_band(d):
    """The radial width of a retaining ring's band (DIN 471/472 rings run about 0.08 d + 1.2)."""
    return 0.08 * d + 1.2


def size_for(kind, dia, on_shaft=True):
    """The size that fits a round face of diameter dia: on a shaft by its inside, in a bore by its outside."""
    pool = sizes(kind)
    if not pool:
        return None
    if kind == "parallel-key":
        b = KEYS[0]
        for row in KEYS:
            if dia > row[0] - 1e-9:
                b = row
        return "%d x %d" % (b[1], b[2])
    if kind == "external-ring":
        return str(min(EXTERNAL, key=lambda d: abs(d - dia)))
    if kind == "internal-ring":
        return str(min(INTERNAL, key=lambda d: abs(d - dia)))
    if kind == "drill-bushing":
        return "%g" % min(BUSH_DRILLS, key=lambda d: abs(_bush(d)[0] - dia) + 0.001 * d)
    if kind == "o-ring":
        if on_shaft:     # stretched a little onto the shaft: the largest inside at most the shaft
            fit = [s for s in pool if _o_ring(s)[0] <= dia + 1e-6]
            return max(fit, key=lambda s: (_o_ring(s)[0], -_o_ring(s)[1])) if fit else pool[0]
        fit = [s for s in pool if dims(kind, s)[1] >= dia - 1e-6]     # squeezed a little into the bore
        return min(fit, key=lambda s: (dims(kind, s)[1], -_o_ring(s)[1])) if fit else pool[-1]
    col = 0 if on_shaft else 1
    return min(pool, key=lambda s: abs(dims(kind, s)[col] - dia))


def default_spec(kind, std="ISO"):
    pool = sizes(kind)
    pick = {"deep-groove-bearing": "6204", "cylindrical-roller-bearing": "NU 204", "thrust-ball-bearing": "51104",
            "external-ring": "20", "internal-ring": "47", "o-ring": "20.35 x 1.78", "parallel-key": "6 x 6",
            "drill-bushing": "6"}.get(kind, pool[0] if pool else "")
    spec = {"kind": kind, "size": pick, "std": std, "display": DISPLAYS[0], "length": None}
    if KINDS[kind][3]:
        ls = lengths(kind, pick)
        spec["length"] = ls[len(ls) // 2] if ls else None
    return spec


def ratings(spec):
    """(C, C0) in kN of a bearing, else None."""
    t = table(spec["kind"])
    return tuple(t[spec["size"]][3:5]) if t else None


def title(spec):
    kind, size, std = spec["kind"], spec["size"], spec.get("std", "ISO")
    number, name = KINDS[kind][2].get(std, KINDS[kind][2]["ISO"]), KINDS[kind][1]
    if kind in ("external-ring", "internal-ring"):
        s = EXTERNAL[int(size)][0] if kind == "external-ring" else INTERNAL[int(size)][0]
        text = "%s %s %s x %g" % (number, name, size, s)
    elif kind == "parallel-key":
        text = "%s %s %s x %s" % (number, name, size, spec.get("length"))
    elif kind == "drill-bushing":
        text = "%s %s %s x %s" % (number, name, size, spec.get("length"))
    else:
        text = "%s %s %s" % (number, name, size)
    if kind in BEARINGS and spec.get("display") == "Simplified":
        text += " (Simplified)"
    return text


# --------------------------------------------------------------------------- shapes
def _tube(r_in, r_out, h, z0=0.0):
    import Part
    V = App.Vector
    outer = Part.makeCylinder(r_out, h, V(0, 0, z0))
    if r_in <= 0:
        return outer
    return outer.cut(Part.makeCylinder(r_in, h + 2, V(0, 0, z0 - 1)))


def shape(spec):
    """The solid in its own frame: the axis is Z, a side face at z = 0, the rest up +Z (a key lies along X)."""
    import Part
    V = App.Vector
    kind, size = spec["kind"], spec["size"]
    detailed = spec.get("display", DISPLAYS[0]) != "Simplified"
    if kind in ("deep-groove-bearing", "cylindrical-roller-bearing"):
        d, D, B = dims(kind, size)
        band = (D - d) / 2.0
        ring = 0.3 * band
        inner = _tube(d / 2.0, d / 2.0 + ring, B)
        outer = _tube(D / 2.0 - ring, D / 2.0, B)
        solids = [inner, outer]
        if detailed:
            pitch = (d + D) / 4.0
            if kind == "deep-groove-bearing":
                dw = 0.38 * band + 0.0
                dw = min(dw, band - 2 * ring + 0.6 * ring)
                n = max(6, int(2 * math.pi * pitch / (1.35 * dw)))
                for i in range(n):
                    a = 2 * math.pi * i / n
                    solids.append(Part.makeSphere(dw / 2.0, V(pitch * math.cos(a), pitch * math.sin(a), B / 2.0)))
            else:
                dw = band - 2 * ring
                n = max(6, int(2 * math.pi * pitch / (1.3 * dw)))
                lw = 0.7 * B
                for i in range(n):
                    a = 2 * math.pi * i / n
                    solids.append(Part.makeCylinder(dw / 2.0, lw, V(pitch * math.cos(a), pitch * math.sin(a),
                                                                    (B - lw) / 2.0)))
        else:
            solids.append(_tube(d / 2.0 + ring, D / 2.0 - ring, 0.15 * B, 0.425 * B))   # the cage, as one band
        return Part.makeCompound(solids)
    if kind == "thrust-ball-bearing":
        d, D, H = dims(kind, size)
        washer = 0.3 * H
        shaft = _tube(d / 2.0, D / 2.0 - 0.06 * (D - d), washer)
        housing = _tube(d / 2.0 + 0.06 * (D - d), D / 2.0, washer, H - washer)
        solids = [shaft, housing]
        pitch = (d + D) / 4.0
        dw = H - 2 * washer
        if detailed:
            n = max(6, int(2 * math.pi * pitch / (1.4 * dw)))
            for i in range(n):
                a = 2 * math.pi * i / n
                solids.append(Part.makeSphere(dw / 2.0 * 0.98, V(pitch * math.cos(a), pitch * math.sin(a), H / 2.0)))
        else:
            solids.append(_tube(pitch - 0.3 * dw, pitch + 0.3 * dw, 0.5 * dw, washer + 0.25 * dw))
        return Part.makeCompound(solids)
    if kind in ("external-ring", "internal-ring"):
        d_in, d_out, s = dims(kind, size)
        ring = _tube(d_in / 2.0, d_out / 2.0, s)
        gap = 0.25 * float(size) + 1.0
        cut = Part.makeBox(gap, d_out, s + 2, V(-gap / 2.0, 0, -1))
        ring = ring.cut(cut)
        # the lugs either side of the gap, with their holes for the pliers
        lug_r = 0.6 * (d_out - d_in) / 2.0 + 0.6
        at = (d_in / 2.0 + d_out / 2.0) / 2.0 if kind == "external-ring" else (d_in / 2.0 + d_out / 2.0) / 2.0
        for side in (-1, 1):
            cx = side * (gap / 2.0 + lug_r)
            cy = math.sqrt(max(at * at - cx * cx, 0.0))
            lug = Part.makeCylinder(lug_r, s, V(cx, cy, 0))
            hole = Part.makeCylinder(0.45 * lug_r, s + 2, V(cx, cy, -1))
            ring = ring.fuse(lug.cut(hole))
        return ring.removeSplitter()
    if kind == "o-ring":
        d1, d2 = _o_ring(size)
        return Part.makeTorus(d1 / 2.0 + d2 / 2.0, d2 / 2.0, V(0, 0, d2 / 2.0))
    if kind == "parallel-key":
        b, h = dims(kind, size)[1:]
        L = float(spec.get("length") or 4 * b)
        r = b / 2.0
        body = Part.makeBox(max(L - b, 0.01), b, h, V(-(L - b) / 2.0, -r, 0))
        for x in (-(L - b) / 2.0, (L - b) / 2.0):
            body = body.fuse(Part.makeCylinder(r, h, V(x, 0, 0)))
        return body.removeSplitter()
    if kind == "drill-bushing":
        d1, d2, _w = dims(kind, size)
        L = float(spec.get("length") or lengths(kind, size)[0])
        bush = _tube(d1 / 2.0, d2 / 2.0, L)
        try:     # the lead-in at the drill's entry
            top = [e for e in bush.Edges if abs(e.BoundBox.ZMin - L) < 1e-9 and abs(e.Curve.Radius - d1 / 2.0) < 1e-6]
            bush = bush.makeChamfer(min(0.2 * d1, 0.8), top)
        except Exception as _fw_err:
            _fw_log("toolboxparts.py:chamfer", _fw_err)
        return bush
    raise ValueError(kind)


def faces(shp, spec):
    """(bore, outer, seat) face names: the inner and outer cylinders the part mates by, and a side face."""
    kind = spec["kind"]
    d_in, d_out, _w = dims(kind, spec["size"])
    bore = outer = seat = None
    for i, f in enumerate(shp.Faces, 1):
        s = f.Surface
        if s.TypeId == "Part::GeomCylinder":
            if bore is None and d_in > 0 and abs(s.Radius - d_in / 2.0) < 1e-6:
                bore = "Face%d" % i
            elif outer is None and abs(s.Radius - d_out / 2.0) < 1e-6 and kind not in ("parallel-key",):
                outer = "Face%d" % i
        elif s.TypeId == "Part::GeomToroid" and bore is None:
            # an O-ring mates by its equator (the seam circle round the axis)
            for j, e in enumerate(shp.Edges, 1):
                c = e.Curve
                if c.TypeId == "Part::GeomCircle" and abs(c.Center.x) < 1e-6 and abs(c.Center.y) < 1e-6:
                    bore = "Edge%d" % j
                    break
            if bore is None:
                bore = "Face%d" % i
            outer = outer or bore
        elif s.TypeId == "Part::GeomPlane" and seat is None:
            n = f.normalAt(0, 0)
            if abs(f.CenterOfMass.z) < 1e-6 and n.z < -0.5:
                seat = "Face%d" % i
    return bore, outer, seat


# --------------------------------------------------------------------------- part files
def part_file(spec):
    """The part file of this size, made the first time it is asked for (as Toolbox fasteners are)."""
    from . import toolbox
    folder = os.path.join(toolbox.library_folder(spec.get("std", "ISO")), KINDS[spec["kind"]][0])
    os.makedirs(folder, exist_ok=True)
    name = title(spec)
    path = os.path.join(folder, name.replace(" ", "_").replace("/", "_").replace("(", "").replace(")", "") + ".FCStd")
    if os.path.isfile(path):
        return path
    keep = App.ActiveDocument
    try:
        doc = App.newDocument("Toolbox", hidden=True, temp=True)
    except TypeError:
        doc = App.newDocument("Toolbox")
    try:
        _feature(doc, spec)
        doc.recompute()
        doc.saveAs(path)
    finally:
        App.closeDocument(doc.Name)
        if keep is not None and keep.Name in App.listDocuments():
            from . import designlib
            designlib._front(keep)
    return path


def _feature(doc, spec):
    shp = shape(spec)
    obj = doc.addObject("Part::Feature", "ToolboxPart")
    obj.Shape = shp
    obj.Label = title(spec)
    bore, outer, seat = faces(shp, spec)
    value = "%s;%s;%s;%s;%s" % (spec["kind"], spec["size"], spec.get("length") or "", spec.get("std", "ISO"),
                                spec.get("display", DISPLAYS[0]))
    for prop, val, tip in ((PROP, value, "Toolbox component"), (BORE_PROP, bore or "", "Inner cylinder"),
                           (OUTER_PROP, outer or "", "Outer cylinder"), (SEAT_PROP, seat or "", "Side face")):
        obj.addProperty("App::PropertyString", prop, "Toolbox", tip)
        setattr(obj, prop, val)
    try:
        from . import toolbox
        toolbox.set_part_numbers(obj, title(spec), KINDS[spec["kind"]][1])
    except Exception as _fw_err:
        _fw_log("toolboxparts.py:partno", _fw_err)
    return obj


def info(comp):
    """The spec of a component made from these parts, or None."""
    try:
        target = comp.getLinkedObject(True)
    except Exception:
        target = None
    text = getattr(target, PROP, None)
    if not text:
        return None
    kind, size, length, std, display = (text.split(";") + [""] * 5)[:5]
    return {"kind": kind, "size": size, "length": int(float(length)) if length else None, "std": std or "ISO",
            "display": display or DISPLAYS[0]}


# --------------------------------------------------------------------------- dropping
def round_face(comp, face_name):
    """(centre, axis, radius, on a shaft) of a component's round face, in the assembly's frame, or None."""
    from . import toolbox
    try:
        f = toolbox.global_shape(comp).getElement(face_name)
    except Exception:
        return None
    if f.Surface.TypeId != "Part::GeomCylinder":
        return None
    c, a, r = toolbox._axis_frame(f)
    u0, u1, v0, v1 = f.ParameterRange
    p = f.valueAt(u0, (v0 + v1) / 2.0)
    n = f.normalAt(u0, (v0 + v1) / 2.0)
    to_axis = (c + a * (p - c).dot(a)) - p
    shaft = not (to_axis.Length > 1e-9 and n.dot(to_axis) > 0)
    return c, a, r, shaft


def target_for(kind, comp, face_name):
    """What a drop onto this face means for this kind: (spec size, the face, on a shaft) or None."""
    got = round_face(comp, face_name)
    if got is None:
        return None
    _c, _a, r, shaft = got
    if (shaft and kind not in ON_SHAFT) or (not shaft and kind not in IN_BORE):
        return None
    return size_for(kind, 2 * r, shaft), shaft


def place(spec, doc=None, point=None, target=None):
    """Puts the part in: a component of doc's assembly at point (on target = (component, face) when given,
    mated Concentric), else its own new part document. Returns the component or the part."""
    from . import asmcore, toolbox
    asm = asmcore.assembly_of(doc) if doc is not None and asmcore.is_assembly(doc) else None
    if asm is None:
        from . import newdoc
        try:
            new = newdoc.make("Part")
        except Exception:
            new = App.newDocument("Part")
        for name in [o.Name for o in new.Objects if o.TypeId == "PartDesign::Body" and not o.Group]:
            new.removeObject(name)       # the empty body a new part starts with (its origin goes with it)
        obj = _feature(new, spec)
        new.recompute()
        if App.GuiUp:
            try:
                Gui.SendMsgToActiveView("ViewFit")
            except Exception as _fw_err:
                _fw_log("toolboxparts.py:fit", _fw_err)
        return obj
    path = part_file(spec)
    pl = App.Placement(point or App.Vector(), App.Rotation())
    face = round_face(*target) if target else None
    if face is not None:
        c, a, r, shaft = face
        p = point if point is not None else c
        centre = c + a * (p - c).dot(a)
        if spec["kind"] == "parallel-key":       # the key lies on the shaft, along its axis
            radial = App.Vector(p - centre)
            if radial.Length < 1e-9:
                radial = a.cross(App.Vector(1, 0, 0) if abs(a.x) < 0.9 else App.Vector(0, 1, 0))
            radial.normalize()
            rot = App.Rotation(a, radial.cross(a), radial, "ZXY")     # X along the shaft, Z out of it
            pl = App.Placement(centre + radial * (r - 0.5 * dims("parallel-key", spec["size"])[2]), rot)
        else:
            pl = App.Placement(centre, App.Rotation(App.Vector(0, 0, 1), a))
    doc.openTransaction("Insert Toolbox Component")
    try:
        from . import designlib
        src, _opened = designlib._source(path)
        if src.Label != title(spec):     # the file's name has underscores; the component is named as the part
            src.Label = title(spec)
        link, part = toolbox._insert_part(asm, path, pl)
        link.Placement = pl
        if face is not None and spec["kind"] != "parallel-key":
            mine = getattr(part, BORE_PROP if face[3] else OUTER_PROP, "") or getattr(part, OUTER_PROP, "")
            if mine:
                toolbox._mate(asm, "Concentric", tuple(target), (link, mine))
    finally:
        doc.commitTransaction()
    doc.recompute()
    return link


def drop(url, doc=None, pick=None, point=None):
    """A part of these folders dropped or double-clicked: its PropertyManager sized from the face under the
    drop, then the part."""
    from . import toolbox, asmcore
    kind = kind_of(url)
    if kind is None:
        return None
    spec = default_spec(kind, toolbox.std_of_url(url))
    target = None
    asm = asmcore.assembly_of(doc) if doc is not None and asmcore.is_assembly(doc) else None
    if asm is not None and pick is not None:
        from . import designlib
        comp, name = designlib._component_of(asm, pick)
        if comp is not None and str(name).split(".")[-1].startswith("Face"):
            face_name = str(name).split(".")[-1]
            got = target_for(kind, comp, face_name)
            if got is not None:
                spec["size"] = got[0]
                if KINDS[kind][3]:
                    ls = lengths(kind, spec["size"])
                    spec["length"] = ls[len(ls) // 2] if ls else None
                target = (comp, face_name)
    if asm is not None and App.GuiUp:
        from . import designlib
        if not designlib._saved(doc):
            return None
    if not App.GuiUp:
        return place(spec, doc, point, target)
    panel = Panel(spec, doc, point, target)
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    Gui.Control.showDialog(panel)
    return panel


# --------------------------------------------------------------------------- hooks
def install():
    """The folders in the Toolbox tree (A to Z), their items, and the drop of one."""
    from . import toolbox, designlib
    if not getattr(toolbox.folders, "_fw_parts", False):
        plain_folders = toolbox.folders

        def tb_folders():
            rows = plain_folders()
            out, std_rows, cur = [], [], None

            def flush():
                if cur is not None:
                    out.extend(ordered(_url() + cur, std_rows + folders(_url() + cur)))
            for p, l in rows:
                rel = p[len(_url()):]
                if rel in toolbox.STANDARDS:
                    flush()
                    out.append((p, l))
                    cur, std_rows = rel, []
                elif cur is not None and rel.startswith(cur + "/"):
                    std_rows.append((p, l))
                else:
                    out.append((p, l))
            flush()
            return out
        tb_folders._fw_parts = True
        tb_folders.__wrapped__ = plain_folders
        toolbox.folders = tb_folders
    if not getattr(toolbox.items, "_fw_parts", False):
        plain_items = toolbox.items

        def tb_items(path):
            std = toolbox.std_of_url(path)
            rel = path[len(_url() + std):].strip("/")
            if std in STANDARDS and owns(rel):
                return items(_url() + std, rel)
            return plain_items(path)
        tb_items._fw_parts = True
        tb_items.__wrapped__ = plain_items
        toolbox.items = tb_items
    if not getattr(designlib.insert, "_fw_parts", False):
        plain_insert = designlib.insert

        def insert(path, doc=None, pick=None, point=None, pm=True):
            if handles(path):
                return drop(path, doc or App.ActiveDocument, pick, point)
            return plain_insert(path, doc, pick, point, pm)
        insert._fw_parts = True
        insert.__wrapped__ = plain_insert
        insert.__doc__ = plain_insert.__doc__
        designlib.insert = insert


# --------------------------------------------------------------------------- PropertyManager
if Gui is not None:
    class Panel:
        ""

        def __init__(self, spec, doc, point, target=None):
            self.spec, self.doc, self.point, self.target, self.made = dict(spec), doc, point, target, None
            kind = spec["kind"]
            self.form = QtWidgets.QWidget()
            self.form.setObjectName("SWToolboxPart")
            self.form.setWindowTitle(KINDS[kind][1])
            lay = QtWidgets.QVBoxLayout(self.form)
            box = QtWidgets.QGroupBox("Properties", self.form)
            lay.addWidget(box)
            f = QtWidgets.QFormLayout(box)
            self.size = QtWidgets.QComboBox(box)
            self.size.setObjectName("SWTBP_size")
            self.size.addItems(sizes(kind))
            self.size.setCurrentText(str(spec["size"]))
            f.addRow("Size:", self.size)
            self.length = None
            if KINDS[kind][3]:
                self.length = QtWidgets.QComboBox(box)
                self.length.setObjectName("SWTBP_length")
                f.addRow("Length:", self.length)
                self._lengths()
            self.display = None
            if kind in BEARINGS:
                self.display = QtWidgets.QComboBox(box)
                self.display.setObjectName("SWTBP_display")
                self.display.addItems(DISPLAYS)
                self.display.setCurrentText(spec.get("display", DISPLAYS[0]))
                f.addRow("Display:", self.display)
            self.info = QtWidgets.QLabel(self.form)
            self.info.setObjectName("SWTBP_info")
            self.info.setWordWrap(True)
            lay.addWidget(self.info)
            lay.addStretch(1)
            self.size.currentIndexChanged.connect(lambda *_: (self._lengths(), self._read()))
            if self.length is not None:
                self.length.currentIndexChanged.connect(lambda *_: self._read())
            if self.display is not None:
                self.display.currentIndexChanged.connect(lambda *_: self._read())
            self._read()

        def _lengths(self):
            if self.length is None:
                return
            keep = self.spec.get("length")
            self.length.blockSignals(True)
            self.length.clear()
            ls = lengths(self.spec["kind"], self.size.currentText())
            self.length.addItems([str(L) for L in ls])
            if keep in ls:
                self.length.setCurrentText(str(keep))
            else:
                self.length.setCurrentIndex(len(ls) // 2)
            self.length.blockSignals(False)

        def _read(self):
            s = self.spec
            s["size"] = self.size.currentText()
            if self.length is not None and self.length.currentText():
                s["length"] = int(float(self.length.currentText()))
            if self.display is not None:
                s["display"] = self.display.currentText()
            d_in, d_out, w = dims(s["kind"], s["size"])
            if s["kind"] in BEARINGS:
                C, C0 = ratings(s)
                text = "d %g mm, D %g mm, %s %g mm\nBasic load ratings: C %g kN, C0 %g kN" % (
                    d_in, d_out, "H" if s["kind"] == "thrust-ball-bearing" else "B", w, C, C0)
            elif s["kind"] == "parallel-key":
                text = "b %g mm, h %g mm, for shafts over %g mm" % (d_out, w, next(o for o, b, h in KEYS if b == d_out))
            elif s["kind"] == "drill-bushing":
                text = "Drill %g mm, outside %g mm" % (d_in, d_out)
            elif s["kind"] == "o-ring":
                text = "Inside %g mm, cross section %g mm" % _o_ring(s["size"])
            else:
                row = EXTERNAL[int(s["size"])] if s["kind"] == "external-ring" else INTERNAL[int(s["size"])]
                text = "Groove diameter %g mm, groove width %g mm, thickness %g mm" % (row[1], row[2], row[0])
            self.info.setText(title(s) + "\n" + text)

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def accept(self):
            self._read()
            Gui.Control.closeDialog()
            try:
                self.made = place(self.spec, self.doc, self.point, self.target)
            except Exception as error:
                App.Console.PrintError("Toolbox: %s\n" % error)
            return True

        def reject(self):
            Gui.Control.closeDialog()
            return True
