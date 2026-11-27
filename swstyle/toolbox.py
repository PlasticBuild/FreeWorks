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

import contextlib
import math
import os

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
    Qt = QtCore.Qt
except Exception:   # pragma: no cover
    Gui = None

URL = "toolbox://"
STANDARD = "ISO"
STANDARDS = ("ANSI Inch", "ANSI Metric", "DIN", "ISO")
METRIC = ("ANSI Metric", "DIN", "ISO")     # the metric tables serve all three, with their own designations
_CUR = {"std": None}                       # the standard being made (a drop, a change)
IN = 25.4

# size: (d, pitch, clearance hole (ISO 273 medium), tap drill), mm
SIZES = {
    "M3": (3.0, 0.5, 3.4, 2.5), "M4": (4.0, 0.7, 4.5, 3.3), "M5": (5.0, 0.8, 5.5, 4.2),
    "M6": (6.0, 1.0, 6.6, 5.0), "M8": (8.0, 1.25, 9.0, 6.8), "M10": (10.0, 1.5, 11.0, 8.5),
    "M12": (12.0, 1.75, 13.5, 10.2), "M16": (16.0, 2.0, 17.5, 14.0), "M20": (20.0, 2.5, 22.0, 17.5),
    "M24": (24.0, 3.0, 26.0, 21.0),
}
# ANSI Inch (UNC): d, 1/TPI, normal fit clearance, tap drill, in inches
_INCH = {
    "#4-40": (0.112, 1 / 40.0, 0.1285, 0.089), "#6-32": (0.138, 1 / 32.0, 0.1495, 0.1065),
    "#8-32": (0.164, 1 / 32.0, 0.177, 0.136), "#10-24": (0.190, 1 / 24.0, 0.201, 0.1495),
    "1/4-20": (0.250, 1 / 20.0, 0.266, 0.201), "5/16-18": (0.3125, 1 / 18.0, 0.332, 0.257),
    "3/8-16": (0.375, 1 / 16.0, 0.397, 0.3125), "1/2-13": (0.5, 1 / 13.0, 0.531, 0.4219),
}
SIZES.update({k: tuple(x * IN for x in v) for k, v in _INCH.items()})
ORDER = list(SIZES)
STD_OF = dict([(k, "ISO") for k in ORDER if k.startswith("M")] + [(k, "ANSI Inch") for k in _INCH])
# socket head: head diameter, head height, socket across flats (ISO 4762; ASME B18.3)
SHCS = {"M3": (5.5, 3, 2.5), "M4": (7, 4, 3), "M5": (8.5, 5, 4), "M6": (10, 6, 5), "M8": (13, 8, 6),
        "M10": (16, 10, 8), "M12": (18, 12, 10), "M16": (24, 16, 14), "M20": (30, 20, 17), "M24": (36, 24, 19)}
SHCS.update({k: tuple(x * IN for x in v) for k, v in {
    "#4-40": (0.183, 0.112, 0.09375), "#6-32": (0.226, 0.138, 0.109), "#8-32": (0.270, 0.164, 0.141),
    "#10-24": (0.312, 0.190, 0.156), "1/4-20": (0.375, 0.250, 0.1875), "5/16-18": (0.469, 0.3125, 0.25),
    "3/8-16": (0.5625, 0.375, 0.3125), "1/2-13": (0.75, 0.5, 0.375)}.items()})
# hex head / nut: across flats, head height, nut height (ISO 4017 / 4032; ASME B18.2.1 / B18.2.2,
# machine screw nuts below 1/4)
HEX = {"M3": (5.5, 2, 2.4), "M4": (7, 2.8, 3.2), "M5": (8, 3.5, 4.7), "M6": (10, 4, 5.2), "M8": (13, 5.3, 6.8),
       "M10": (16, 6.4, 8.4), "M12": (18, 7.5, 10.8), "M16": (24, 10, 14.8), "M20": (30, 12.5, 18),
       "M24": (36, 15, 21.5)}
HEX.update({k: tuple(x * IN for x in v) for k, v in {
    "#4-40": (0.25, 0.0, 0.09375), "#6-32": (0.3125, 0.0, 0.109), "#8-32": (0.34375, 0.0, 0.125),
    "#10-24": (0.375, 0.0, 0.125), "1/4-20": (0.4375, 0.163, 0.219), "5/16-18": (0.5, 0.211, 0.266),
    "3/8-16": (0.5625, 0.243, 0.328), "1/2-13": (0.75, 0.323, 0.438)}.items()})
# plain washer: inner, outer, thickness (ISO 7089; SAE flat washer)
WASHER = {"M3": (3.2, 7, 0.5), "M4": (4.3, 9, 0.8), "M5": (5.3, 10, 1), "M6": (6.4, 12, 1.6),
          "M8": (8.4, 16, 1.6), "M10": (10.5, 20, 2), "M12": (13, 24, 2.5), "M16": (17, 30, 3),
          "M20": (21, 37, 3), "M24": (25, 44, 4)}
WASHER.update({k: tuple(x * IN for x in v) for k, v in {
    "#4-40": (0.125, 0.312, 0.032), "#6-32": (0.156, 0.375, 0.049), "#8-32": (0.188, 0.438, 0.049),
    "#10-24": (0.219, 0.5, 0.049), "1/4-20": (0.281, 0.625, 0.065), "5/16-18": (0.344, 0.688, 0.065),
    "3/8-16": (0.406, 0.812, 0.065), "1/2-13": (0.531, 1.062, 0.095)}.items()})
# button head (ISO 7380): head diameter, head height
BUTTON = {"M3": (5.7, 1.65), "M4": (7.6, 2.2), "M5": (9.5, 2.75), "M6": (10.5, 3.3), "M8": (14, 4.4),
          "M10": (17.5, 5.5), "M12": (21, 6.6), "M16": (28, 8.8), "M20": (35, 11), "M24": (42, 13.2)}
BUTTON.update({k: tuple(x * IN for x in v) for k, v in {
    "#4-40": (0.213, 0.060), "#6-32": (0.262, 0.074), "#8-32": (0.312, 0.087), "#10-24": (0.375, 0.105),
    "1/4-20": (0.437, 0.132), "5/16-18": (0.547, 0.166), "3/8-16": (0.656, 0.199), "1/2-13": (0.875, 0.265)}.items()})
# countersunk socket head (ISO 10642; ASME B18.3 flat head): head diameter (90 degree head)
CSK_HEAD = {"M3": 6.72, "M4": 8.96, "M5": 11.2, "M6": 13.44, "M8": 17.92, "M10": 22.4, "M12": 26.88,
            "M16": 33.6, "M20": 40.32, "M24": 48.0}
CSK_HEAD.update({k: v * IN for k, v in {"#4-40": 0.255, "#6-32": 0.307, "#8-32": 0.359, "#10-24": 0.411,
                                        "1/4-20": 0.531, "5/16-18": 0.656, "3/8-16": 0.781, "1/2-13": 1.031}.items()})
# spring lock washer (DIN 127 B; ASME B18.21.1): inner, outer, thickness
SPRING = {"M3": (3.1, 6.2, 0.8), "M4": (4.1, 7.6, 0.9), "M5": (5.1, 9.2, 1.2), "M6": (6.1, 11.8, 1.6),
          "M8": (8.2, 14.8, 2.0), "M10": (10.2, 18.1, 2.2), "M12": (12.2, 21.1, 2.5), "M16": (16.2, 27.4, 3.5),
          "M20": (20.2, 33.6, 4.0), "M24": (24.5, 40.0, 5.0)}
SPRING.update({k: tuple(x * IN for x in v) for k, v in {
    "#4-40": (0.115, 0.209, 0.025), "#6-32": (0.141, 0.250, 0.031), "#8-32": (0.168, 0.293, 0.040),
    "#10-24": (0.194, 0.334, 0.047), "1/4-20": (0.255, 0.489, 0.062), "5/16-18": (0.319, 0.586, 0.078),
    "3/8-16": (0.382, 0.683, 0.094), "1/2-13": (0.509, 0.873, 0.125)}.items()})
# prevailing torque (nylon insert) hex nut (ISO 7040; ASME B18.16.6): height
LOCKNUT = {"M3": 4.0, "M4": 5.0, "M5": 5.0, "M6": 6.0, "M8": 8.0, "M10": 10.0, "M12": 12.0, "M16": 16.0,
           "M20": 20.0, "M24": 24.0}
LOCKNUT.update({k: v * IN for k, v in {"#4-40": 0.141, "#6-32": 0.141, "#8-32": 0.172, "#10-24": 0.172,
                                       "1/4-20": 0.281, "5/16-18": 0.328, "3/8-16": 0.375, "1/2-13": 0.516}.items()})
PIN_DIAMETERS = (2, 3, 4, 5, 6, 8, 10, 12, 16, 20)
PINS_INCH = {"1/8": 0.125 * IN, "3/16": 0.1875 * IN, "1/4": 0.25 * IN, "5/16": 0.3125 * IN,
             "3/8": 0.375 * IN, "1/2": 0.5 * IN}
LENGTHS = (4, 5, 6, 8, 10, 12, 16, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80, 90, 100, 110, 120,
           130, 140, 150, 160, 180, 200)
_IN_LEN = ("1/4", "3/8", "1/2", "5/8", "3/4", "7/8", "1", "1-1/4", "1-1/2", "1-3/4", "2", "2-1/4",
           "2-1/2", "3", "3-1/2", "4", "5", "6")


def _inch(text):
    whole, _, frac = text.partition("-") if "/" in text.partition("-")[2] else ("", "", text)
    if "/" in frac:
        n, d = frac.split("/")
        v = float(n) / float(d)
    else:
        v = float(frac)
    return (float(whole) if whole else 0.0) + v


LENGTHS_INCH = tuple(round(_inch(t) * IN, 4) for t in _IN_LEN)
INCH_TEXT = dict(zip(LENGTHS_INCH, _IN_LEN))

# key: (folder in the Toolbox tree, name shown, {standard: its number}, has a length)
TYPES = {    # folder, name, designation by standard, has a length
    "cheese-head-screw": ("Bolts and Screws/Cheese Head", "Slotted Cheese Head Screw",
                          {"ISO": "ISO 1207", "DIN": "DIN 84", "ANSI Metric": "ISO 1207", "ANSI Inch": "-"}, True),
    "countersunk-screw": ("Bolts and Screws/Countersunk Head", "Socket Countersunk Head Screw",
                          {"ISO": "ISO 10642", "DIN": "DIN 7991", "ANSI Metric": "B18.3.5M", "ANSI Inch": "ASME B18.3"}, True),
    "flat-head-screw": ("Bolts and Screws/Countersunk Head", "Slotted Countersunk Flat Head Screw",
                        {"ISO": "ISO 2009", "DIN": "DIN 963", "ANSI Metric": "ISO 2009", "ANSI Inch": "ASME B18.6.3"}, True),
    "hex-bolt": ("Bolts and Screws/Hex Head", "Hex Bolt",
                 {"ISO": "ISO 4017", "DIN": "DIN 933", "ANSI Metric": "B18.2.3.5M", "ANSI Inch": "ASME B18.2.1"}, True),
    "pan-head-screw": ("Bolts and Screws/Pan Head", "Cross Recessed Pan Head Screw",
                       {"ISO": "ISO 7045", "DIN": "DIN 7985", "ANSI Metric": "ISO 7045", "ANSI Inch": "ASME B18.6.3"}, True),
    "set-screw": ("Bolts and Screws/Set Screws", "Socket Set Screw Flat Point",
                  {"ISO": "ISO 4026", "DIN": "DIN 913", "ANSI Metric": "B18.3.6M", "ANSI Inch": "ASME B18.3"}, True),
    "socket-head-cap-screw": ("Bolts and Screws/Socket Head Screws", "Socket Head Cap Screw",
                              {"ISO": "ISO 4762", "DIN": "DIN 912", "ANSI Metric": "B18.3.1M", "ANSI Inch": "ASME B18.3"}, True),
    "button-head-screw": ("Bolts and Screws/Socket Head Screws", "Socket Button Head Screw",
                          {"ISO": "ISO 7380", "DIN": "ISO 7380", "ANSI Metric": "B18.3.4M", "ANSI Inch": "ASME B18.3"}, True),
    "low-head-cap-screw": ("Bolts and Screws/Socket Head Screws", "Low Head Socket Cap Screw",
                           {"ISO": "DIN 7984", "DIN": "DIN 7984", "ANSI Metric": "DIN 7984", "ANSI Inch": "-"}, True),
    "hex-nut": ("Nuts/Hex Nuts", "Hex Nut",
                {"ISO": "ISO 4032", "DIN": "DIN 934", "ANSI Metric": "B18.2.4.1M", "ANSI Inch": "ASME B18.2.2"}, False),
    "lock-nut": ("Nuts/Lock Nuts", "Prevailing Torque Hex Nut",
                 {"ISO": "ISO 7040", "DIN": "DIN 985", "ANSI Metric": "B18.16.3M", "ANSI Inch": "ASME B18.16.6"}, False),
    "dowel-pin": ("Pins/Dowel Pins", "Dowel Pin",
                  {"ISO": "ISO 2338", "DIN": "DIN 7", "ANSI Metric": "B18.8.5M", "ANSI Inch": "ASME B18.8.2"}, True),
    "spring-pin": ("Pins/Spring Pins", "Spring Pin",
                   {"ISO": "ISO 8752", "DIN": "DIN 1481", "ANSI Metric": "B18.8.4M", "ANSI Inch": "ASME B18.8.2"}, True),
    "plain-washer": ("Washers/Plain Washers", "Plain Washer",
                     {"ISO": "ISO 7089", "DIN": "DIN 125", "ANSI Metric": "B18.22M", "ANSI Inch": "SAE"}, False),
    "spring-washer": ("Washers/Spring Washers", "Spring Lock Washer",
                      {"ISO": "DIN 127", "DIN": "DIN 127", "ANSI Metric": "B18.21.2M", "ANSI Inch": "ASME B18.21.1"}, False),
}
# extapps99: the screws the Hole Wizard has counterbores and countersinks for (head diameter, head height; the Hole Wizard's tables)
LOW_HEAD = {"M3": (5.5, 2), "M4": (7, 2.8), "M5": (8.5, 3.5), "M6": (10, 4), "M8": (13, 5), "M10": (16, 6), "M12": (18, 7),
            "M16": (24, 9), "M20": (30, 11), "M24": (36, 13)}                                    # DIN 7984
PAN_HEAD = {"M3": (5.6, 1.8), "M4": (8, 2.4), "M5": (9.5, 3), "M6": (12, 3.6), "M8": (16, 4.8), "M10": (20, 6)}   # ISO 7045 / DIN 7985
CHEESE_HEAD = {"M3": (5.5, 2), "M4": (7, 2.6), "M5": (8.5, 3.3), "M6": (10, 3.9), "M8": (13, 5), "M10": (16, 6)}  # ISO 1207 / DIN 84
FLAT_HEAD = {"M3": 5.5, "M4": 8.4, "M5": 9.3, "M6": 11.3, "M8": 15.8, "M10": 18.3}              # ISO 2009 / DIN 963 head diameter, 90 degrees
PAN_HEAD.update({k: tuple(x * IN for x in v) for k, v in {
    "#4-40": (0.219, 0.068), "#6-32": (0.270, 0.082), "#8-32": (0.322, 0.096), "#10-24": (0.373, 0.110),
    "1/4-20": (0.492, 0.144), "5/16-18": (0.615, 0.178), "3/8-16": (0.740, 0.212)}.items()})          # ASME B18.6.3
FLAT_HEAD.update({k: v * IN for k, v in {"#4-40": 0.225, "#6-32": 0.279, "#8-32": 0.332, "#10-24": 0.385, "1/4-20": 0.507,
                                          "5/16-18": 0.635, "3/8-16": 0.762, "1/2-13": 0.875}.items()})   # 82 degree heads
EXTRA_TABLES = {"low-head-cap-screw": LOW_HEAD, "pan-head-screw": PAN_HEAD, "cheese-head-screw": CHEESE_HEAD,
                "flat-head-screw": FLAT_HEAD}
PINS = ("dowel-pin", "spring-pin")
NUTS = ("hex-nut", "lock-nut")
WASHERS = ("plain-washer", "spring-washer")


def standard_of(kind, size):
    """The standard of a size: inch or metric by the size, which metric one by the one being made
    (a Toolbox drop or a change keeps its standard), else ISO."""
    inch = (str(size) in PINS_INCH) if kind in PINS else STD_OF.get(size, "ISO") == "ANSI Inch"
    if inch:
        return "ANSI Inch"
    cur = _CUR["std"]
    return cur if cur in METRIC else "ISO"


class standard:
    """with standard("DIN"): fastener names and files of that standard."""

    def __init__(self, std):
        self.std = std

    def __enter__(self):
        self.old = _CUR["std"]
        _CUR["std"] = self.std
        return self

    def __exit__(self, *a):
        _CUR["std"] = self.old


def sizes(std, kind=None):
    if kind in PINS:
        return list(PINS_INCH) if std == "ANSI Inch" else [str(d) for d in PIN_DIAMETERS]
    family = "ANSI Inch" if std == "ANSI Inch" else "ISO"
    out = [k for k in ORDER if STD_OF[k] == family]
    if kind == "hex-bolt" and std == "ANSI Inch":
        out = [k for k in out if HEX[k][1] > 0]       # hex bolts start at 1/4
    table = EXTRA_TABLES.get(kind)
    if table is not None:
        out = [k for k in out if k in table]        # extapps99: the sizes of the table (pan, cheese and flat heads stop at M10 / 3/8)
    return [k for k in out if k not in NOT_MADE.get(kind, ())]


# extapps97: sizes the standard does not list (ISO 7380-1 button heads stop at M16, ISO 10642 / DIN 7991 countersunk at M20)
NOT_MADE = {"button-head-screw": ("M20", "M24"), "countersunk-screw": ("M24",)}
# DIN 933 / DIN 934 / DIN 985, the older tables: across flats and nut height where they differ from ISO 4017 / 4032
# (size: across flats, head height, nut height)
DIN_HEX = {"M5": (8, 3.5, 4.0), "M6": (10, 4, 5.0), "M8": (13, 5.3, 6.5), "M10": (17, 6.4, 8.0), "M12": (19, 7.5, 10.0),
           "M16": (24, 10, 13.0), "M20": (30, 12.5, 16.0), "M24": (36, 15, 19.0)}


def hexdims(size):
    """(across flats, head height, nut height) of a hex bolt or nut: DIN's own table while a DIN part is made."""
    if _CUR["std"] == "DIN" and size in DIN_HEX:
        return DIN_HEX[size]
    return HEX[size]


# the longest length of a kind, in diameters (the standards stop well short of 200 on a small screw)
LONGEST = {"socket-head-cap-screw": 17, "hex-bolt": 17, "button-head-screw": 8, "countersunk-screw": 10,
           "set-screw": 8, "dowel-pin": 10, "spring-pin": 20, "low-head-cap-screw": 10, "pan-head-screw": 8,
           "cheese-head-screw": 8, "flat-head-screw": 10}


def lengths_for(std, kind, size):
    """The lengths listed for one size: from the shortest the standard lists to the kind's longest (never fewer than
    three), instead of every length for every size."""
    ls = list(lengths(std))
    try:
        d = pin_d(size) if kind in PINS else SIZES[size][0]
        low = min_length(kind, size)
        high = LONGEST.get(kind, 17) * d
    except Exception:
        return ls
    keep = [L for L in ls if low - 1e-6 <= L <= high + 1e-6]
    if len(keep) < 3:
        keep = [L for L in ls if L >= low - 1e-6][:3]
    return keep or ls


def lengths(std):
    return LENGTHS_INCH if std == "ANSI Inch" else LENGTHS


def length_text(std, L):
    if std == "ANSI Inch":
        return INCH_TEXT.get(round(L, 4), "%g in" % (L / IN))
    return "%g" % L


def pin_d(size):
    return PINS_INCH[size] if str(size) in PINS_INCH else float(size)


SCREWS = ("socket-head-cap-screw", "hex-bolt", "button-head-screw", "countersunk-screw", "low-head-cap-screw",
          "pan-head-screw", "cheese-head-screw", "flat-head-screw")
PROP = "FwToolbox"            # "<type>;<size>;<length>" on the fastener's part
AXIS_PROP = "FwAxisFace"      # the cylinder a hole mate takes
SEAT_PROP = "FwSeatFace"      # the face that sits on the part (under the head, a washer's or nut's bottom)
TOP_PROP = "FwTopFace"        # a washer's top: the next thing in the stack sits there


# --------------------------------------------------------------------------- the tree
FAVORITES = URL + "Favorites"


def _fav_param():
    return App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks/Toolbox")


def favorites():
    ""
    got = _fav_param().GetString("Favorites", "")
    return [u for u in got.split(";") if u and type_of(u)]


def set_favorite(url, on=True):
    favs = [u for u in favorites() if u != url]
    if on:
        favs.append(url)
    _fav_param().SetString("Favorites", ";".join(favs))


def show_favorites():
    try:
        from . import asmrefopts
        return asmrefopts.on(("Hole Wizard/Toolbox", "Display Toolbox Favorites folder", True))
    except Exception:
        return True


def folders():
    ""

    out = [(FAVORITES, "Favorites")] if show_favorites() else []
    for std in STANDARDS:
        out.append((URL + std, std))
        seen = set()
        for key, (folder, _n, _s, _l) in TYPES.items():
            if key in EXTRA_TABLES and not sizes(std, key):
                continue            # extapps99: no folder for a screw the standard does not list
            parts = folder.split("/")
            for i in range(len(parts)):
                p = URL + std + "/" + "/".join(parts[:i + 1])
                if p not in seen:
                    seen.add(p)
                    out.append((p, parts[i]))
        from . import powertrans        # Power Transmission: gears, sprockets, the Shaft Wizard
        out += powertrans.folders(URL + std)
    return out


def _parent_of(p):
    """The folder a Toolbox path sits in; the standards and Favorites sit in the Toolbox root (extapps155)."""
    return p.rsplit("/", 1)[0] if p.count("/") > 2 else URL


def children(path):
    here = URL if path.rstrip("/") == URL.rstrip("/") else path.rstrip("/")
    return [(p, l) for p, l in folders() if _parent_of(p) == here]


def std_of_url(url):
    rest = url[len(URL):]
    for std in STANDARDS:
        if rest == std or rest.startswith(std + "/"):
            return std
    return STANDARD


def items(path):
    """The fastener types in a Toolbox folder: [(url, name)]."""
    if path.rstrip("/") == FAVORITES:
        return [(u, "%s %s" % (TYPES[type_of(u)][2][std_of_url(u)], TYPES[type_of(u)][1])) for u in favorites()]
    std = std_of_url(path)
    rel = path[len(URL + std):].strip("/")
    from . import powertrans
    if rel.startswith(powertrans.FOLDER):
        return powertrans.items(URL + std, rel)
    return [(URL + std + "/" + key, "%s %s" % (TYPES[key][2][std], TYPES[key][1]))
            for key, (folder, _n, _s, _l) in TYPES.items()
            if folder == rel and (key not in EXTRA_TABLES or sizes(std, key))]


def is_toolbox(path):
    return isinstance(path, str) and path.startswith(URL)


def type_of(url):
    key = url.rstrip("/").rsplit("/", 1)[-1]
    return key if key in TYPES else None


# --------------------------------------------------------------------------- sizing
def size_for_diameter(dia, threaded=False, std=None):
    """The fastener size for a hole: its tap drill when threaded, else its clearance hole (in the
    standard asked for, else the closest of all), else the largest one that fits."""
    if dia is None:
        return None
    pool = sizes(std) if std else ORDER
    if not pool:
        return None
    col = 3 if threaded else 2
    for c in (col, 5 - col):
        best = min(pool, key=lambda s: abs(SIZES[s][c] - dia) / SIZES[s][0])
        if abs(SIZES[best][c] - dia) <= 0.12 * SIZES[best][0]:
            return best
    fits = [s for s in (pool if std else sizes(STANDARD)) if SIZES[s][0] <= dia + 1e-6]
    fits.sort(key=lambda s: SIZES[s][0])
    return fits[-1] if fits else pool[0]


def pin_for_diameter(dia, std=None):
    if std == "ANSI Inch":
        return min(PINS_INCH, key=lambda k: abs(PINS_INCH[k] - dia))
    return min(PIN_DIAMETERS, key=lambda d: abs(d - dia))


def length_for(need, shorter=False, std="ISO"):
    """The standard length at least need long (or at most, for a blind tapped hole)."""
    ls = lengths(std)
    if shorter:
        fit = [L for L in ls if L <= need + 1e-6]
        return fit[-1] if fit else ls[0]
    fit = [L for L in ls if L >= need - 1e-6]
    return fit[0] if fit else ls[-1]


def min_length(kind, size):
    """The shortest length the standard lists (socket head near 1.3 d, hex bolts at 2 d)."""
    d = pin_d(size) if kind in PINS else SIZES[size][0]
    return length_for((2.0 if kind == "hex-bolt" else 1.3) * d, std=standard_of(kind, size))


def label(kind, size, length=None):
    std = standard_of(kind, size)
    name, number = TYPES[kind][1], TYPES[kind][2][std]
    size = ("%g" % size) if isinstance(size, float) else size
    if TYPES[kind][3]:
        return "%s %s %s x %s" % (number, name, size, length_text(std, length))
    return "%s %s %s" % (number, name, size)


# --------------------------------------------------------------------------- shapes
def _hexagon(across_flats, height, z0=0.0):
    import Part
    r = across_flats / math.sqrt(3.0)
    pts = [App.Vector(r * math.cos(math.radians(30 + 60 * i)), r * math.sin(math.radians(30 + 60 * i)), z0)
           for i in range(6)]
    wire = Part.makePolygon(pts + [pts[0]])
    return Part.Face(wire).extrude(App.Vector(0, 0, height))


def shape(kind, size, length=None):
    """The solid in its own frame: the axis is Z, the seat (where it sits on the part) is z = 0;
    a screw's shank runs to -length, its head up +Z; a nut or washer goes up +Z from its seat."""
    import Part
    V = App.Vector
    if kind == "socket-head-cap-screw":
        d = SIZES[size][0]
        dk, k, s = SHCS[size]
        head = Part.makeCylinder(dk / 2.0, k, V(0, 0, 0))
        head = head.cut(_hexagon(s, 0.6 * k, k - 0.6 * k + 0.01))
        shank = Part.makeCylinder(d / 2.0, length, V(0, 0, -length))
        return head.fuse(shank).removeSplitter()
    if kind == "hex-bolt":
        d = SIZES[size][0]
        s, k, _m = hexdims(size)
        head = _hexagon(s, k)
        shank = Part.makeCylinder(d / 2.0, length, V(0, 0, -length))
        return head.fuse(shank).removeSplitter()
    if kind == "hex-nut":
        d = SIZES[size][0]
        s, _k, m = hexdims(size)
        return _hexagon(s, m).cut(Part.makeCylinder(d / 2.0, m + 2, V(0, 0, -1)))
    if kind == "plain-washer":
        d1, d2, h = WASHER[size]
        return Part.makeCylinder(d2 / 2.0, h).cut(Part.makeCylinder(d1 / 2.0, h + 2, V(0, 0, -1)))
    if kind == "dowel-pin":
        d = pin_d(size)
        pin = Part.makeCylinder(d / 2.0, length, V(0, 0, -length))
        return pin
    if kind == "spring-pin":
        d = pin_d(size)
        wall = max(0.1 * d, 0.2)
        tube = Part.makeCylinder(d / 2.0, length, V(0, 0, -length)).cut(
            Part.makeCylinder(d / 2.0 - wall, length + 2, V(0, 0, -length - 1)))
        slot = Part.makeBox(0.15 * d, d, length + 2, V(-0.075 * d, 0, -length - 1))
        return tube.cut(slot).removeSplitter()
    if kind == "button-head-screw":
        d = SIZES[size][0]
        dk, k = BUTTON[size]
        head = Part.makeCylinder(dk / 2.0, k, V(0, 0, 0))
        try:
            top = [e for e in head.Edges if abs(e.BoundBox.ZMin - k) < 1e-9]
            head = head.makeFillet(0.6 * k, top)
        except Exception as _fw_err:
            _fw_log("toolbox.py:412", _fw_err)
        s_hex = SHCS.get(size, (0, 0, 0.6 * d))[2] * 0.6
        head = head.cut(_hexagon(s_hex, 0.5 * k, 0.5 * k + 0.01))
        shank = Part.makeCylinder(d / 2.0, length, V(0, 0, -length))
        return head.fuse(shank).removeSplitter()
    if kind == "countersunk-screw":
        # its top is flush with the part (z = 0), the 90 degree head goes down into the countersink
        d = SIZES[size][0]
        dk = CSK_HEAD[size]
        k = (dk - d) / 2.0
        head = Part.makeCone(dk / 2.0, d / 2.0, k, V(0, 0, 0), V(0, 0, -1))
        head = head.cut(_hexagon(SHCS.get(size, (0, 0, 0.6 * d))[2] * 0.8, 0.5 * k, -0.5 * k))
        shank = Part.makeCylinder(d / 2.0, max(length - k, 0.1), V(0, 0, -length))
        return head.fuse(shank).removeSplitter()
    if kind == "low-head-cap-screw":
        d = SIZES[size][0]
        dk, k = LOW_HEAD[size]
        head = Part.makeCylinder(dk / 2.0, k, V(0, 0, 0))
        head = head.cut(_hexagon(SHCS[size][2] * 0.8, 0.6 * k, 0.4 * k + 0.01))
        shank = Part.makeCylinder(d / 2.0, length, V(0, 0, -length))
        return head.fuse(shank).removeSplitter()
    if kind in ("pan-head-screw", "cheese-head-screw"):
        d = SIZES[size][0]
        dk, k = PAN_HEAD[size] if kind == "pan-head-screw" else CHEESE_HEAD[size]
        head = Part.makeCylinder(dk / 2.0, k, V(0, 0, 0))
        if kind == "pan-head-screw":
            try:
                top = [e for e in head.Edges if abs(e.BoundBox.ZMin - k) < 1e-9]
                head = head.makeFillet(0.7 * k, top)
            except Exception as _fw_err:
                _fw_log("toolbox.py:pan", _fw_err)
            w, deep = max(0.12 * dk, 0.4), 0.45 * k       # the cross recess
            head = head.cut(Part.makeBox(0.6 * dk, w, deep + 0.01, V(-0.3 * dk, -w / 2.0, k - deep))).cut(
                Part.makeBox(w, 0.6 * dk, deep + 0.01, V(-w / 2.0, -0.3 * dk, k - deep)))
        else:
            w, deep = max(0.25 * d, 0.4), 0.5 * k          # the slot
            head = head.cut(Part.makeBox(1.2 * dk, w, deep + 0.01, V(-0.6 * dk, -w / 2.0, k - deep)))
        shank = Part.makeCylinder(d / 2.0, length, V(0, 0, -length))
        return head.fuse(shank).removeSplitter()
    if kind == "flat-head-screw":
        # as the socket countersunk: its top flush with the part (z = 0), the head goes down into the countersink
        d = SIZES[size][0]
        dk = FLAT_HEAD[size]
        k = csk_depth(kind, size)
        head = Part.makeCone(dk / 2.0, d / 2.0, k, V(0, 0, 0), V(0, 0, -1))
        w, deep = max(0.25 * d, 0.4), 0.5 * k
        head = head.cut(Part.makeBox(1.2 * dk, w, deep + 0.01, V(-0.6 * dk, -w / 2.0, -deep)))
        shank = Part.makeCylinder(d / 2.0, max(length - k, 0.1), V(0, 0, -length))
        return head.fuse(shank).removeSplitter()
    if kind == "set-screw":
        # its top at z = 0 (flush in the tapped hole), the socket in the top
        d = SIZES[size][0]
        body = Part.makeCylinder(d / 2.0, length, V(0, 0, -length))
        s_hex = SHCS.get(size, (0, 0, 0.5 * d))[2] * 0.6
        return body.cut(_hexagon(s_hex, min(0.6 * d, 0.8 * length), -min(0.6 * d, 0.8 * length) + 0.01)).removeSplitter()
    if kind == "lock-nut":
        d = SIZES[size][0]
        sf, _k, _m = hexdims(size)
        return _hexagon(sf, LOCKNUT[size]).cut(Part.makeCylinder(d / 2.0, LOCKNUT[size] + 2, V(0, 0, -1)))
    if kind == "spring-washer":
        d1, d2, h = SPRING[size]
        ring = Part.makeCylinder(d2 / 2.0, h).cut(Part.makeCylinder(d1 / 2.0, h + 2, V(0, 0, -1)))
        gap = Part.makeBox(0.08 * d2 + 0.2, d2, h + 2, V(-(0.04 * d2 + 0.1), 0, -1))
        return ring.cut(gap).removeSplitter()
    raise ValueError(kind)


def csk_depth(kind, size):
    """How far a countersunk head goes down: 90 degrees in metric, 82 degrees in inch (ASME B18.6.3 flat heads)."""
    if kind == "flat-head-screw":
        angle = 82.0 if standard_of(kind, size) == "ANSI Inch" else 90.0
        return (FLAT_HEAD[size] - SIZES[size][0]) / (2.0 * math.tan(math.radians(angle / 2.0)))
    return (CSK_HEAD[size] - SIZES[size][0]) / 2.0


def height(kind, size):
    """How far a nut or washer stands off its seat."""
    if kind == "plain-washer":
        return WASHER[size][2]
    if kind == "spring-washer":
        return SPRING[size][2]
    if kind == "hex-nut":
        return hexdims(size)[2]
    if kind == "lock-nut":
        return LOCKNUT[size]
    return 0.0


def _faces(shp, kind, size):
    """(axis cylinder, seat face, top face) names, found from the geometry."""
    axis = seat = top = None
    if kind in SCREWS or kind in PINS or kind == "set-screw":
        r = (pin_d(size) if kind in PINS else SIZES[size][0]) / 2.0
    elif kind in NUTS:
        r = SIZES[size][0] / 2.0
    elif kind == "spring-washer":
        r = SPRING[size][0] / 2.0
    else:
        r = WASHER[size][0] / 2.0
    top_z = height(kind, size)
    for i, f in enumerate(shp.Faces, 1):
        s = f.Surface
        if s.TypeId == "Part::GeomCylinder" and abs(s.Radius - r) < 1e-6 and axis is None:
            axis = "Face%d" % i
        elif s.TypeId == "Part::GeomPlane":
            z = f.CenterOfMass.z
            n = f.normalAt(0, 0)
            if abs(z) < 1e-6 and n.z < -0.5 and seat is None:
                seat = "Face%d" % i
            elif abs(z - top_z) < 1e-6 and n.z > 0.5 and top is None and top_z > 0:
                top = "Face%d" % i
    if kind in PINS or kind in ("set-screw", "countersunk-screw", "flat-head-screw"):
        seat = None          # no face under a head: it goes in on its axis (the countersink holds a flat head)
    return axis, seat, top


def library_folder(std=STANDARD):
    root = App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks").GetString("ToolboxFolder", "")
    if root:
        return os.path.join(root, std)
    from . import designlib
    return os.path.join(designlib.library_root(), "toolbox", std)


_SCRATCH = []


def _pending_txn():
    """extapps141: (document, name) of the Undo step being recorded, or None."""
    try:
        got = App.getActiveTransaction()
        if got and got[0]:
            for d in App.listDocuments().values():
                if d.HasPendingTransaction:
                    return d, got[0]
            if App.ActiveDocument is not None:      # a step opened and nothing recorded yet: the active document's
                return App.ActiveDocument, got[0]
    except Exception as _fw_err:
        _fw_log("toolbox.py:pending", _fw_err)
    return None


@contextlib.contextmanager
def keep_step():
    """extapps141: FreeCAD ends the Undo step being recorded when a document is created or closed. Whatever does that inside
    this block gets the step opened again afterwards, so the rest of the work stays in one Undo."""
    pend = _pending_txn()
    try:
        yield
    finally:
        if pend is not None and pend[0].Name in App.listDocuments() and App.getActiveTransaction() is None:
            pend[0].openTransaction(pend[1])


def scratch_ready():
    """extapps141: the hidden document part_file builds new fastener files in. It is made once, before an Undo step opens, and stays
    (empty, saved, hidden): making or closing a document inside a step ends the step, so Undo of Smart Fasteners left every
    fastener in place. Returns it."""
    live = []
    for d in _SCRATCH:
        try:
            if d.Name in App.listDocuments():
                live.append(d)
        except ReferenceError:       # closed behind our back
            pass
    _SCRATCH[:] = live
    if not _SCRATCH:
        keep = App.ActiveDocument
        with keep_step():
            try:
                made = App.newDocument("ToolboxScratch", hidden=True, temp=True)
            except TypeError:
                made = App.newDocument("ToolboxScratch")
            import tempfile
            # pkg319: a file of this session's own (two FreeCAD windows shared one and their backups
            # collided); FreeCAD's "Save complete, but error while managing backup history" is only a warning
            try:
                made.saveAs(os.path.join(tempfile.gettempdir(), "fw_toolbox_scratch_%d.FCStd" % os.getpid()))
            except OSError as error:
                if "Save complete" not in str(error):
                    raise
                App.Console.PrintLog("FreeCAD: toolbox scratch: %s\n" % error)
        _SCRATCH.append(made)
        _front_doc(keep)
    return _SCRATCH[0]


def _front_doc(doc):
    if doc is not None and doc.Name in App.listDocuments():
        from . import designlib
        designlib._front(doc)


def part_file(kind, size, length=None, folder=None):
    """The fastener's part file, made the first time it is asked for."""
    folder = folder or os.path.join(library_folder(standard_of(kind, size)), TYPES[kind][0])
    os.makedirs(folder, exist_ok=True)
    name = label(kind, size, length)
    path = os.path.join(folder, name.replace(" ", "_").replace("/", "_").replace("#", "No") + ".FCStd")
    if os.path.isfile(path):
        return path
    return _build_part_file(kind, size, length, name, path, scratch_ready(), False, App.ActiveDocument)


def _build_part_file(kind, size, length, name, path, doc, own, keep):
    try:
        shp = shape(kind, size, length)
        obj = doc.addObject("Part::Feature", "Fastener")
        obj.Shape = shp
        obj.Label = name
        try:        # extapps107: Toolbox Settings > Customize Hardware: the part number, description and custom properties
            from . import toolboxconfig
            number, desc, extra = toolboxconfig.part_defaults(standard_of(kind, size), kind, size)
            if number:
                obj.Label = number
            # extapps110: the Description a part starts with: the one saved in Toolbox Settings, else the type's name (the BOM's DESCRIPTION)
            obj.Label2 = desc or TYPES[kind][1]
            for prop in extra:
                pname = "Custom_" + "".join(ch if ch.isalnum() else "_" for ch in prop)
                if pname not in obj.PropertiesList:
                    obj.addProperty("App::PropertyString", pname, "Toolbox", "Custom property: %s" % prop)
        except Exception as _fw_err:
            _fw_log("toolbox.py:part_defaults", _fw_err)
        axis, seat, top = _faces(shp, kind, size)
        for prop, value, tip in ((PROP, "%s;%s;%s;%s" % (kind, size, length if length is not None else "",
                                                       standard_of(kind, size)), "Toolbox fastener"),
                                 (AXIS_PROP, axis or "", "Hole mate cylinder"),
                                 (SEAT_PROP, seat or "", "Face that sits on the part"),
                                 (TOP_PROP, top or "", "Face the next one sits on")):
            obj.addProperty("App::PropertyString", prop, "Toolbox", tip)
            setattr(obj, prop, value)
        doc.recompute()
        doc.saveAs(path)
    finally:
        if own:
            App.closeDocument(doc.Name)
            _front_doc(keep)
        else:
            doc.removeObject(obj.Name)
            import tempfile
            # pkg320: the same file of this session's own as scratch_ready (pkg319): two FreeCAD windows
            # making fasteners collided here too; the backup-history warning is only a warning
            try:
                doc.saveAs(os.path.join(tempfile.gettempdir(), "fw_toolbox_scratch_%d.FCStd" % os.getpid()))     # the file just made is no longer this document's
            except OSError as error:
                if "Save complete" not in str(error):
                    raise
                App.Console.PrintLog("FreeCAD: toolbox scratch: %s\n" % error)
    return path


def info(comp):
    """(type, size, length) of a fastener component, or None."""
    try:
        target = comp.getLinkedObject(True)
    except Exception:
        target = None
    text = getattr(target, PROP, None)
    if not text:
        return None
    kind, size, length = (text.split(";") + ["", ""])[:3]
    if kind in PINS and size not in PINS_INCH:
        size = float(size)
    return kind, size, float(length) if length else None


def is_fastener(comp):
    return info(comp) is not None


def standard_of_comp(comp):
    """The standard a fastener component was made in (older files: by its size)."""
    try:
        text = getattr(comp.getLinkedObject(True), PROP, "") or ""
    except Exception:
        text = ""
    parts = text.split(";")
    if len(parts) > 3 and parts[3] in STANDARDS:
        return parts[3]
    i = info(comp)
    return standard_of(i[0], i[1]) if i else STANDARD


def set_part_numbers(part, number=None, description=None):
    """The Configure Component PM's Part number (the part's name in the BOM) and Description,
    saved in the fastener's part file."""
    if number:
        part.Label = number
    if description is not None:
        part.Label2 = description
    try:
        if part.Document.FileName:
            part.Document.save()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Toolbox part number: %s\n" % error)


def thread_length(kind, size, length):
    """The thread length the Configure Component PM shows: ISO 4762 / 4017 b = 2d + 6 (to 125),
    2d + 12 (to 200), the whole shank when shorter; inch 2d + 1/4 in (to 6 in)."""
    if not TYPES[kind][3] or kind in PINS or length is None:
        return None
    if kind == "set-screw":
        return length
    d = SIZES[size][0]
    if standard_of(kind, size) == "ANSI Inch":
        b = 2 * d + 0.25 * IN if length <= 6 * IN else 2 * d + 0.5 * IN
    else:
        b = 2 * d + 6 if length <= 125 else 2 * d + 12
    head = csk_depth(kind, size) if kind in ("countersunk-screw", "flat-head-screw") else 0.0
    return min(b, length - head)


# --------------------------------------------------------------------------- holes
def _axis_frame(face):
    s = face.Surface
    return App.Vector(s.Center), App.Vector(s.Axis).normalize(), s.Radius


def _same_line(c1, a1, c2, a2, tol=1e-3):
    if abs(abs(a1.dot(a2)) - 1.0) > 1e-6:
        return False
    d = c2 - c1
    return (d - a1 * d.dot(a1)).Length < tol


def global_shape(comp):
    shp = comp.getLinkedObject(True).Shape.copy()
    shp.Placement = comp.Placement.multiply(shp.Placement)
    return shp


def hole_faces(comp):
    """The holes of a component: [(face name, radius, centre, axis)] for its inner cylinders, in
    the assembly's frame. An inner cylinder's normal points at its axis."""
    out = []
    shp = global_shape(comp)
    for i, f in enumerate(shp.Faces, 1):
        if f.Surface.TypeId != "Part::GeomCylinder":
            continue
        c, a, r = _axis_frame(f)
        u0, u1, v0, v1 = f.ParameterRange
        if u1 - u0 < math.pi:       # a slot's end or a fillet, not a hole
            continue
        p = f.valueAt(u0, (v0 + v1) / 2.0)
        n = f.normalAt(u0, (v0 + v1) / 2.0)
        to_axis = (c + a * (p - c).dot(a)) - p
        if to_axis.Length > 1e-9 and n.dot(to_axis) > 0:
            out.append(("Face%d" % i, r, c, a))
    return out


def _span(face, a):
    zs = [v.Point.dot(a) for v in face.Vertexes] or [face.CenterOfMass.dot(a)]
    if not face.Vertexes:
        bb = face.BoundBox
    return min(zs), max(zs)


_FEAT_TOOLS = {}


def _feature_pieces(feat, asm, comp):
    """The cut solids (in the assembly) of a Hole, Hole Wizard or Hole Series assembly feature that reach `comp`; kept until the feature changes."""
    from . import asmfeature
    kind = getattr(feat, asmfeature.FEATURE_PROP)
    key = (feat.Document.Name, feat.Name, kind, comp.Name,
           "|".join(str(getattr(feat, p, "")) for p in ("Spec", "Points", "Point", "Normal", "Diameter", "Reversed", "EndCondition", "Depth",
                                                         "SeriesMiddle", "SeriesLast", "Tapped")))
    if key not in _FEAT_TOOLS:
        if len(_FEAT_TOOLS) > 200:
            _FEAT_TOOLS.clear()
        if kind == "Series":
            _FEAT_TOOLS[key] = [sol for cc, sol in asmfeature.series_tools(feat, asm) if cc is comp]
        else:
            t = asmfeature.tool(feat, asm)
            _FEAT_TOOLS[key] = [t] if t is not None and not t.isNull() else []
    return _FEAT_TOOLS[key]


def asm_hole_feature(comp, face_name):
    """extapps105: the assembly feature (Simple Hole, Hole Wizard or Hole Series) that made a component's hole face, or None: the one whose
    cut has a round face on the same axis and radius. Smart Fasteners and Autosize read the hole's type and size from it."""
    try:
        from . import asmfeature, asmcore
        asm = asmcore.assembly_of(comp.Document)
        if asm is None:
            return None
        c, a, r = _axis_frame(global_shape(comp).getElement(face_name))
        for feat in asmfeature.features(asm):
            kind = getattr(feat, asmfeature.FEATURE_PROP, "")
            if kind not in ("Hole", "Wizard", "Series") or asmfeature.is_suppressed(feat):
                continue
            for solid in _feature_pieces(feat, asm, comp):
                for f in solid.Faces:
                    if f.Surface.TypeId != "Part::GeomCylinder":
                        continue
                    c2, a2, r2 = _axis_frame(f)
                    if abs(r2 - r) < 1e-4 and _same_line(c, a, c2, a2):
                        return feat
    except Exception as _fw_err:
        _fw_log("toolbox.py:asmhole", _fw_err)
    return None


def hole_hosts(comp, face_name):
    """Hole wizard data of a component's hole face: the PartDesign Hole feature it came from,
    or None."""
    part = comp.getLinkedObject(True)
    body = part if part.TypeId == "PartDesign::Body" else None
    if body is None:
        return asm_hole_feature(comp, face_name)        # extapps105: a hole an assembly feature made
    face = global_shape(comp).getElement(face_name)
    c, a, r = _axis_frame(face)
    patterned = []
    for o in body.Group:
        if o.TypeId in ("PartDesign::LinearPattern", "PartDesign::PolarPattern", "PartDesign::Mirrored",
                        "PartDesign::MultiTransform") and not getattr(o, "Suppressed", False):
            patterned += [h for h in getattr(o, "Originals", None) or [] if getattr(h, "TypeId", "") == "PartDesign::Hole"]
    for o in body.Group:
        if o.TypeId != "PartDesign::Hole":
            continue
        try:
            tool = o.AddSubShape.copy()
        except Exception as _fw_err:
            _fw_log("toolbox.py:658", _fw_err)
            continue
        tool.Placement = comp.Placement.multiply(tool.Placement)
        for f in tool.Faces:
            if f.Surface.TypeId == "Part::GeomCylinder":
                c2, a2, r2 = _axis_frame(f)
                if abs(r2 - r) < 1e-4 and _same_line(c, a, c2, a2):
                    return o
    for o in patterned:         # a copy of the hole: same radius, its axis square to the same face
        try:
            tool = o.AddSubShape.copy()
        except Exception as _fw_err:
            _fw_log("toolbox.py:670", _fw_err)
            continue
        tool.Placement = comp.Placement.multiply(tool.Placement)
        for f in tool.Faces:
            if f.Surface.TypeId == "Part::GeomCylinder":
                c2, a2, r2 = _axis_frame(f)
                if abs(r2 - r) < 1e-4 and abs(abs(a.dot(a2)) - 1.0) < 1e-6:
                    return o
    return None


def wizard_spec(hole):
    """The Hole Wizard's own choices kept on the hole (holespec.stored), or None."""
    if hole is None:
        return None
    if hasattr(hole, "FwAsmFeature"):               # extapps105: an assembly feature keeps its choices in Spec
        try:
            import json
            return json.loads(getattr(hole, "Spec", "") or "") or None
        except ValueError:
            return None
    try:
        from . import holespec
        return holespec.stored(hole) if hasattr(holespec, "stored") else None
    except Exception as _fw_err:
        _fw_log("toolbox.py:689", _fw_err)
        return None


def kind_for(spec):
    """The Toolbox type for a Hole Wizard hole's fastener type ("Socket Head Cap Screw ISO 4762")."""
    text = str((spec or {}).get("type", "")).lower()
    if "pan" in text:                                  # extapps99: the Hole Wizard's pan, cheese, low head and slotted flat heads
        return "pan-head-screw"                        # have their own Toolbox screws (they used to get a hex bolt or a socket head)
    if "cheese" in text:
        return "cheese-head-screw"
    if "low head" in text:
        return "low-head-cap-screw"
    if "countersunk" in text or "flat head" in text or "raised" in text:
        return "countersunk-screw" if "socket" in text else "flat-head-screw"
    if "hex" in text and ("bolt" in text or "screw" in text) and "socket" not in text:
        return "hex-bolt"
    if "dowel" in text or "pin" in text:
        return "dowel-pin"
    if "button" in text:
        return "button-head-screw"
    return "socket-head-cap-screw"


def known_size(text):
    """A Toolbox size from a hole's size text: "M6", "1/4-20", '1/4"', "#10"."""
    text = str(text or "").replace('"', "").replace(" ", "").replace("UNC", "")
    if text in SIZES:
        return text
    for k in _INCH:
        if k.split("-")[0] == text:
            return k
    return None


def hole_spec(comp, face_name):
    """(size, threaded) of a hole: the Hole feature's thread size when it has one, else from
    the diameter."""
    face = global_shape(comp).getElement(face_name)
    r = face.Surface.Radius
    hole = hole_hosts(comp, face_name)
    spec = wizard_spec(hole)
    size = known_size(spec.get("size", "")) if spec else None
    if size:
        return size, spec.get("kind") == "Tap"
    if hole is not None:
        size = known_size(str(getattr(hole, "ThreadSize", "") or "").split("x")[0])     # FreeCAD's "M6x1.0", "1/4"
        threaded = bool(getattr(hole, "Threaded", False))
        if size:
            # a counterbore's own cylinder belongs to the same hole: the size is still the hole's
            return size, threaded
    return size_for_diameter(2 * r), False


def _planes_at(shp, a, level, tol=1e-4):
    """Planar faces of shp square to a at level along a: [(name, normal)]."""
    out = []
    for i, f in enumerate(shp.Faces, 1):
        if f.Surface.TypeId != "Part::GeomPlane":
            continue
        n = f.normalAt(0, 0)
        if abs(abs(n.dot(a)) - 1.0) < 1e-6 and abs(f.CenterOfMass.dot(a) - level) < tol:
            out.append(("Face%d" % i, n))
    return out


def stack(asm, comp, face_name):
    """The hole and the holes lined up with it in other components: a dict with the hole's
    axis (pointing into the material, from the side the head goes), the seat (component, face,
    level), the exit (component, face, level) for through holes, its size and whether it is
    threaded at the far end."""
    shp = global_shape(comp)
    face = shp.getElement(face_name)
    c, a, r = _axis_frame(face)
    size, threaded = hole_spec(comp, face_name)
    # every coaxial hole face of every non-fastener component
    pieces = []
    for other in _components(asm):
        if is_fastener(other):
            continue
        for name, r2, c2, a2 in hole_faces(other):
            if _same_line(c, a, c2, a2) and (other is comp or r2 <= r * 1.6 + 1e-6):
                f = global_shape(other).getElement(name)
                lo, hi = _span(f, a)
                pieces.append((lo, hi, other, name, r2))
    if not pieces:
        return None
    # the group of pieces touching the picked one (end to end along the axis)
    pieces.sort(key=lambda p: p[0])
    lo0, hi0 = _span(face, a)
    group = [p for p in pieces if p[2] is comp and p[3] == face_name]
    changed = True
    while changed:
        changed = False
        lo = min(p[0] for p in group)
        hi = max(p[1] for p in group)
        for p in pieces:
            if p not in group and p[0] <= hi + 1e-4 and p[1] >= lo - 1e-4:
                group.append(p)
                changed = True
    lo = min(p[0] for p in group)
    hi = max(p[1] for p in group)
    # the head goes on the open side: the end with a planar face facing out
    ends = []
    for level, out_dir in ((hi, a), (lo, -a)):
        for lo_, hi_, other, name, r2 in group:
            gs = global_shape(other)
            for fname, n in _planes_at(gs, a, level):
                if n.dot(out_dir) > 0.5:
                    ends.append((level, out_dir, other, fname))
    if not ends:
        return None
    # the head end: the wider hole's side (a counterbore), else the side the Hole Wizard hole
    # was drilled from, else the upper one
    def end_radius(e):
        at = [p[4] for p in group if abs((p[1] if e[1].dot(a) > 0 else p[0]) - e[0]) < 1e-4]
        return max(at) if at else 0.0
    entry = _entry(comp, face_name)

    def rank(e):
        drilled = 0.0
        if entry is not None:
            drilled = -abs((entry - c).dot(a) + c.dot(a) - e[0])
        return (round(end_radius(e), 4), drilled, e[1].z, e[1].dot(a))
    top_end = max(ends, key=rank)
    into = -top_end[1]
    # a counterbore: the seat is the floor where the wide hole meets the narrow one
    seat_level, seat = top_end[0], (top_end[2], top_end[3])
    narrow = min(p[4] for p in group)
    wide = [p for p in group if p[4] > narrow + 1e-4]
    if wide:
        w = min(wide, key=lambda p: abs((p[1] if top_end[1].dot(a) > 0 else p[0]) - top_end[0]))
        floor = w[0] if top_end[1].dot(a) > 0 else w[1]
        for fname, n in _planes_at(global_shape(w[2]), a, floor):
            if n.dot(top_end[1]) > 0.5:
                seat_level, seat = floor, (w[2], fname)
    exit_ = next((e for e in ends if e[1].dot(top_end[1]) < 0), None)
    host = hole_hosts(comp, face_name)
    if exit_ is not None and host is not None and getattr(host, "FwAsmFeature", "") == "Series":
        try:        # extapps105: a Hole Series whose last part is tapped: the screw goes into it, no nut at the far end
            from . import asmfeature
            _mid, last = asmfeature.series_parts(host)
            parts = asmfeature.series_components(host, asm)
            if last.get("kind") == "Straight Tap" and parts and parts[-1] is exit_[2]:
                exit_ = None
        except Exception as _fw_err:
            _fw_log("toolbox.py:series", _fw_err)
    axis_piece = min((p for p in group if abs(p[4] - narrow) < 1e-4), key=lambda p: abs(p[0] - seat_level))
    grip = abs((hi if into.dot(a) > 0 else lo) - seat_level) if exit_ is not None else \
        abs((hi if into.dot(a) > 0 else lo) - seat_level)
    centre = c + a * (seat_level - c.dot(a))
    return {
        "size": size, "threaded": threaded or (exit_ is None),
        "into": into, "centre": centre, "radius": narrow,
        "seat": seat, "seat_level": seat_level,
        "exit": (exit_[2], exit_[3]) if exit_ is not None else None,
        "grip": grip, "axis": (axis_piece[2], axis_piece[3]),
        "components": list(dict.fromkeys(p[2] for p in group)),
    }


def _entry(comp, face_name):
    """Where a Hole Wizard hole was drilled from (its sketch's origin, in the assembly frame)."""
    hole = hole_hosts(comp, face_name)
    if hole is not None and hasattr(hole, "FwAsmFeature"):       # extapps105: where the assembly feature's hole starts (its picked face)
        pts = [App.Vector(p) for p in (list(getattr(hole, "Points", None) or []) or [hole.Point])]
        return pts[0]
    prof = getattr(hole, "Profile", None) if hole is not None else None
    sk = prof[0] if isinstance(prof, tuple) else prof
    if sk is None:
        return None
    return comp.Placement.multiply(sk.getGlobalPlacement()).Base


def _components(asm):
    from . import asmcore
    return asmcore.components(asm)


# --------------------------------------------------------------------------- putting one in
def _placement(centre, into, level_shift=0.0, flip=False):
    """The frame whose +Z points out of the hole (against into) at centre (moved along into)."""
    z = -into if not flip else into
    rot = App.Rotation(App.Vector(0, 0, 1), z)
    return App.Placement(centre + into * level_shift, rot)


def _mate(asm, kind, ref1, ref2):
    """A mate that keeps the fastener where it was put: FreeCAD's solve can take a free part to
    the other alignment (a washer turned over into the plate), so when the new part moved, it goes
    back, and the mate is flipped when it does not hold there."""
    from . import asmcore
    comp = ref2[0]
    pose = App.Placement(comp.Placement)
    try:
        from . import asmrefopts       # Lock rotation of new concentric mates to Toolbox components
        joint = asmcore.add_mate(asm, kind, ref1, ref2,
                                 lock_rotation=kind == "Concentric" and asmrefopts.toolbox_lock())
    except Exception as exc:
        App.Console.PrintWarning("Toolbox: %s mate not made (%s)\n" % (kind, exc))
        return None
    if _moved(comp, pose):
        comp.Placement = pose
        if not asmcore.satisfied(joint):
            joint.Proxy.flipOnePart(joint)
            comp.Placement = pose
        asmcore.solve(asm)
        if _moved(comp, pose):
            comp.Placement = pose
    return joint


def _moved(comp, pose, tol=1e-4):
    p = comp.Placement
    return (p.Base - pose.Base).Length > tol or (pose.Rotation.inverted() * p.Rotation).Angle > 1e-5


def _insert_part(asm, path, placement):
    ""

    keep = App.ActiveDocument
    try:
        return _insert_part0(asm, path, placement)
    finally:
        if keep is not None and keep.Name in App.listDocuments() and App.ActiveDocument is not keep:
            from . import designlib
            designlib._front(keep)


def _insert_part0(asm, path, placement):
    from . import asmcore, designlib
    src, _ = designlib._source(path)
    target = asmcore.part_object(src) or next((o for o in src.Objects if hasattr(o, PROP)), None)
    if target is not None and hasattr(target, PROP) and src.Label != target.Label:
        # the file's name has underscores ("DIN_912_..."); the component is named "DIN 912 ... M6 x 16<1>"
        try:
            src.Label = target.Label
        except Exception as _fw_err:
            _fw_log("toolbox.py:904", _fw_err)
    link = asmcore.insert(asm, target, placement)
    link.Placement = placement
    return link, target


def place(asm, kind, size, length, hole, mates=True, flip=False):
    """One fastener (or nut/washer) in a hole stack: the seat is the hole's seat (or exit when
    flip, for the bottom stack). Returns the component."""
    path = part_file(kind, size, length)
    if flip:
        comp_face = hole["exit"]
        shp = global_shape(comp_face[0])
        f = shp.getElement(comp_face[1])
        level = f.CenterOfMass
        centre = hole["centre"] + hole["into"] * (level - hole["centre"]).dot(hole["into"])
        pl = _placement(centre, -hole["into"])
    else:
        comp_face = hole["seat"]
        pl = _placement(hole["centre"], hole["into"])
    link, target = _insert_part(asm, path, pl)
    if mates:
        if getattr(target, AXIS_PROP, ""):
            _mate(asm, "Concentric", hole["axis"], (link, getattr(target, AXIS_PROP)))
        if getattr(target, SEAT_PROP, ""):
            _mate(asm, "Coincident", comp_face, (link, getattr(target, SEAT_PROP)))
    return link


def _shift(hole, by, flip=False):
    """The hole as seen from on top of a washer: the seat moved out by its thickness."""
    h = dict(hole)
    if flip:
        h["exit_shift"] = h.get("exit_shift", 0.0) + by
    else:
        h["centre"] = hole["centre"] - hole["into"] * by
    return h


def auto_length_for(hole, kind, size, head_shift=0.0, under=0.0, nut=False):
    """The length Smart Fasteners and Autosize pick for a fastener in a hole stack: the grip plus what the washer under the head and the
    bottom stack add, to the next standard length. nut: there is a bottom stack (a nut) on a through hole."""
    std = standard_of(kind, size)
    need = hole["grip"] + head_shift + under
    if hole.get("exit") is None or not nut:
        # blind (tapped) hole: as long as fits; through with no nut: grip plus a thread's worth
        if hole.get("exit") is None:
            return length_for(need, shorter=True, std=std)

        return length_for(need + 1.5 * (pin_d(size) if kind in PINS else SIZES[size][0]), std=std)
    return length_for(need + SIZES[size][1] * 2, std=std)


def mated_hole(asm, comp):
    """extapps104: the hole a fastener component is mated to: (component, face name) of the round face of a non-fastener component that
    one of its mates holds it to, or None. This is the mated geometry Configure Component's Autosize reads."""
    from . import asmcore
    try:
        joints = asmcore.mates(asm)
    except Exception as _fw_err:
        _fw_log("toolbox.py:mated", _fw_err)
        return None
    for j in joints:
        refs = [getattr(j, "Reference1", None), getattr(j, "Reference2", None)]
        if not all(r and r[0] is not None for r in refs):
            continue
        mine = [r for r in refs if r[0] is comp]
        other = [r for r in refs if r[0] is not comp]
        if len(mine) != 1 or len(other) != 1 or is_fastener(other[0][0]):
            continue
        sub = (other[0][1] or [""])[0]
        name = str(sub).split(".")[-1]
        if name.startswith("Face") and any(n == name for n, _r, _c, _a in hole_faces(other[0][0])):
            return other[0][0], name
    return None


def autosize(asm, comp):
    """Autosize to mated geometry for a fastener component: (size, length) from the hole it is mated to (its diameter, or the Hole Wizard's
    size) and the stack in that hole (grip, the washer under the head, the nut and washer at the far end); None when it is not mated to a hole."""
    mh = mated_hole(asm, comp)
    if mh is None:
        return None
    try:
        hole = stack(asm, mh[0], mh[1])
    except Exception as _fw_err:
        _fw_log("toolbox.py:autosize", _fw_err)
        return None
    if hole is None:
        return None
    kind = info(comp)[0]
    std = standard_of_comp(comp)
    have = list(sizes(std, kind))
    size = hole["size"]
    if size not in have:
        if not have or size not in SIZES:
            return None
        size = min((x for x in have if x in SIZES), key=lambda x: abs(SIZES[x][0] - SIZES[size][0]))
    head_shift, under, nut = 0.0, 0.0, False
    if TYPES[kind][3] or kind in PINS:
        axis_line = (hole["centre"], hole["into"])
        for o in _components(asm):
            if o is comp or not is_fastener(o):
                continue
            ok, os_, _ol = info(o)
            if ok not in WASHERS and ok not in ("hex-nut", "lock-nut"):
                continue
            try:
                face = global_shape(o).getElement(_prop(o, AXIS_PROP))
                c2, a2, _r2 = _axis_frame(face)
            except Exception:
                continue
            if not _same_line(axis_line[0], axis_line[1], c2, a2):
                continue
            along = (c2 - hole["centre"]).dot(hole["into"])
            h = height(ok, os_) if os_ in SIZES else 0.0
            if along < 0:
                head_shift += h         # between the head and the seat
            else:
                under += h
                nut = True
    length = None
    if TYPES[kind][3]:
        with standard(std):
            length = auto_length_for(hole, kind, size, head_shift, under, nut)
            length = max(length, min_length(kind, size))
            ls = lengths_for(std, kind, size)
            if ls:
                length = min(length, max(ls))
    return size, length


def put_in(asm, hole, kind="socket-head-cap-screw", size=None, length=None, top_stack=None,
           bottom_stack=(), auto_length=True, mates=True):
    ""

    size = size or hole["size"]
    if kind in EXTRA_TABLES and size not in sizes(standard_of(kind, size), kind):
        kind = "socket-head-cap-screw"        # extapps99: no pan, cheese, low or flat head screw of this size (M12 and up): a socket head
    out = []
    head_shift = 0.0
    if isinstance(top_stack, (tuple, list)):     # Toolbox Settings' stacks come as lists: one washer on top
        top_stack = top_stack[0] if top_stack else None
    if top_stack:
        w = place(asm, top_stack, size, None, hole, mates=False)
        out.append(w)
        head_shift = height(top_stack, size)
        if mates:
            _mate(asm, "Concentric", hole["axis"], (w, _prop(w, AXIS_PROP)))
            _mate(asm, "Coincident", hole["seat"], (w, _prop(w, SEAT_PROP)))
    bottom = list(bottom_stack or ()) if hole.get("exit") else []
    under = sum(height(k, size) for k in bottom)
    std = standard_of(kind, size)
    if length is None or auto_length:
        length = auto_length_for(hole, kind, size, head_shift, under, bool(bottom))
    length = max(length, min_length(kind, size))
    if TYPES[kind][3]:
        length = min(length, max(lengths_for(std, kind, size)))        # extapps97: no longer than the standard lists for the size
    screw_hole = dict(hole)
    screw_hole["centre"] = hole["centre"] - hole["into"] * head_shift
    screw = place(asm, kind, size, length, screw_hole, mates=False)
    out.insert(0, screw)
    if mates:
        _mate(asm, "Concentric", hole["axis"], (screw, _prop(screw, AXIS_PROP)))
        seat_ref = (out[1], _prop(out[1], TOP_PROP)) if top_stack else hole["seat"]
        if _prop(screw, SEAT_PROP):         # (a countersunk head sits in its countersink)
            _mate(asm, "Coincident", seat_ref, (screw, _prop(screw, SEAT_PROP)))
    # bottom stack from the exit face out
    if bottom:
        ex_comp, ex_face = hole["exit"]
        f = global_shape(ex_comp).getElement(ex_face)
        level = (f.CenterOfMass - hole["centre"]).dot(hole["into"])
        at = hole["centre"] + hole["into"] * level
        prev = (ex_comp, ex_face)
        for k in bottom:
            pl = _placement(at, -hole["into"])
            link, target = _insert_part(asm, part_file(k, size), pl)
            out.append(link)
            if mates:
                _mate(asm, "Concentric", hole["axis"], (link, _prop(link, AXIS_PROP)))
                _mate(asm, "Coincident", prev, (link, _prop(link, SEAT_PROP)))
            prev = (link, _prop(link, TOP_PROP))
            at = at + hole["into"] * height(k, size)
    for c in out:
        c.addProperty("App::PropertyString", "FwFastenerGroup", "Toolbox", "Smart Fasteners group") \
            if not hasattr(c, "FwFastenerGroup") else None
        c.FwFastenerGroup = "%s %s" % (size, TYPES[kind][1])
    asm.Document.recompute()
    return out


def _prop(link, name):
    t = link.getLinkedObject(True)
    return getattr(t, name, "")


def drop(url, asm, pick, point=None):
    """A Toolbox item dragged onto a hole of a component: sized from the hole and mated in."""
    kind = type_of(url)
    if kind is None or pick is None:
        return None
    comp, sub = pick
    face_name = str(sub).split(".")[-1]
    if not face_name.startswith(("Face", "Edge")):
        return None
    holes = dict((n, (r, c, a)) for n, r, c, a in hole_faces(comp))
    if face_name not in holes:
        # an edge of the hole or the face round it: the nearest hole to the drop point
        if point is None or not holes:
            return None
        def dist(item):
            r, c, a = item[1]
            d = point - c
            return (d - a * d.dot(a)).Length - r
        face_name = min(holes.items(), key=lambda kv: abs(dist(kv)))[0]
    hole = stack(asm, comp, face_name)
    if hole is None:
        return None
    std = std_of_url(url)
    with standard(std):
        return _drop(kind, std, asm, hole)


def drop_free(url, asm, point=None):
    ""

    kind = type_of(url)
    if kind is None:
        return None
    std = std_of_url(url)
    with standard(std):
        all_sizes = list(sizes(std, kind))
        size = "M6" if "M6" in all_sizes else (all_sizes[len(all_sizes) // 2] if all_sizes else None)
        if size is None:
            return None
        if kind in PINS and size not in PINS_INCH:
            try:
                size = float(size)
            except (TypeError, ValueError) as _fw_err:
                _fw_log("toolbox.py:1055", _fw_err)
        length = None
        if TYPES[kind][3]:
            ls = lengths_for(std, kind, size)
            length = 20 if 20 in ls else (ls[len(ls) // 2] if ls else None)
        path = part_file(kind, size, length)
        link, _t = _insert_part(asm, path, App.Placement(point or App.Vector(), App.Rotation()))
    asm.Document.recompute()
    return [link]


def _drop(kind, std, asm, hole):
    family = "ANSI Inch" if std == "ANSI Inch" else "ISO"
    if kind not in PINS and STD_OF.get(hole["size"]) != family:
        # an ANSI Inch item on a metric hole (or the other way round): the nearest size of its own standard
        hole["size"] = size_for_diameter(2 * hole["radius"], hole["threaded"] and hole.get("exit") is None, std)
    if kind in PINS or kind == "set-screw":
        if kind == "set-screw":
            d = hole["size"]
            length = length_for(min(hole["grip"], 2 * SIZES[d][0]), shorter=True, std=std)
            c = place(asm, kind, d, length, hole, mates=False)
            _mate(asm, "Concentric", hole["axis"], (c, _prop(c, AXIS_PROP)))
            return [c]
        d = pin_for_diameter(2 * hole["radius"], std)
        length = length_for(hole["grip"], shorter=True, std=std)
        pin_hole = dict(hole)
        pin_hole["centre"] = hole["centre"]
        c = place(asm, kind, d, length, pin_hole, mates=False)
        _mate(asm, "Concentric", hole["axis"], (c, _prop(c, AXIS_PROP)))
        return [c]
    if kind in SCREWS:
        return put_in(asm, hole, kind)
    return [place(asm, kind, hole["size"], None, hole)]


# --------------------------------------------------------------------------- Smart Fasteners
def all_holes(asm, comps=None, filled=False):
    """Every hole stack in the components (or all of them), once each: Hole Wizard holes first;
    with no Hole Wizard hole, every round hole. With filled, the holes with a fastener in them too."""
    seen, out = [], []
    for comp in comps or _components(asm):
        if is_fastener(comp):
            continue
        for name, r, c, a in hole_faces(comp):
            if any(_same_line(c, a, c2, a2) for c2, a2 in seen):
                continue
            if hole_hosts(comp, name) is None and _has_hole_features(comp):
                continue
            h = stack(asm, comp, name)
            if h is None:
                continue
            if _filled(asm, h) and not filled:
                seen.append((c, a))
                continue
            seen.append((c, a))
            out.append(h)
    return out


def _has_hole_features(comp):
    part = comp.getLinkedObject(True)
    return part.TypeId == "PartDesign::Body" and any(o.TypeId == "PartDesign::Hole" for o in part.Group)


def _filled(asm, hole):
    """A hole that already has a fastener in it."""
    for comp in _components(asm):
        if not is_fastener(comp) or info(comp)[0] not in SCREWS + PINS + ("set-screw",):
            continue
        p = comp.Placement
        z = p.Rotation.multVec(App.Vector(0, 0, 1))
        if _same_line(p.Base, z, hole["centre"], hole["into"]):
            return True
    return False


def _on_line(comp, hole):
    p = comp.Placement
    return _same_line(p.Base, p.Rotation.multVec(App.Vector(0, 0, 1)), hole["centre"], hole["into"])


def fastener_entries(asm, fasteners=None):
    """Edit Smart Fastener: the Smart Fasteners in the assembly, one entry per hole (its screw
    first, then the washers and nuts on its line, head side to far side), with the stack each
    was made with. With fasteners, only the entries of their groups."""
    comps = [c for c in _components(asm) if is_fastener(c) and getattr(c, "FwFastenerGroup", "")]
    groups = {getattr(c, "FwFastenerGroup", "") for c in fasteners or ()}
    out = []
    for hole in all_holes(asm, filled=True):
        on = [c for c in comps if _on_line(c, hole)]
        screws = [c for c in on if info(c)[0] in SCREWS + PINS + ("set-screw",)]
        if not screws or (groups and screws[0].FwFastenerGroup not in groups):
            continue
        depth = lambda c: (c.Placement.Base - hole["centre"]).dot(hole["into"])
        rest = sorted((c for c in on if c not in screws), key=depth)
        kind, size, length = info(screws[0])
        spec = wizard_spec(hole_hosts(*hole["axis"]))
        default = kind_for(spec) if spec else "socket-head-cap-screw"
        if default in PINS:
            default = "socket-head-cap-screw"
        top = [c for c in rest if depth(c) < depth(screws[0]) + 1e-6 and info(c)[0] in WASHERS]
        e = {"hole": hole, "comps": [screws[0]] + rest, "kind": kind, "default": default,
             "top": info(top[0])[0] if top else None,
             "bottom": tuple(info(c)[0] for c in rest if c not in top)}
        if str(size) != str(hole["size"]):
            e["size"] = size
        e["was"] = dict(kind=kind, size=size, length=length, top=e["top"], bottom=e["bottom"],
                        group=screws[0].FwFastenerGroup, comps=list(e["comps"]))
        out.append(e)
    return out


def smart_fasteners(asm, comps=None, kind=None, top_stack=None,
                    bottom_stack=("plain-washer", "hex-nut"), auto_length=True):
    """Populate: a fastener in each hole found. Returns {group: [components]}."""
    groups = {}
    doc = asm.Document
    scratch_ready()
    doc.openTransaction("Smart Fasteners")
    try:
        for hole in all_holes(asm, comps):
            spec = wizard_spec(hole_hosts(*hole["axis"]))
            k = kind_for(spec) if (spec and kind is None) else (kind or "socket-head-cap-screw")
            if k in PINS:
                k = "socket-head-cap-screw"
            made = put_in(asm, hole, k, top_stack=top_stack, bottom_stack=bottom_stack,
                          auto_length=auto_length)
            groups.setdefault(made[0].FwFastenerGroup, []).extend(made)
    finally:
        doc.commitTransaction()
    return groups


def default_size_length(std, kind, old_kind, old_size, old_len):
    """extapps103: the size and length a fastener takes on when its type is changed (Configure Component > Change Fastener Type): the
    same size when the new type lists it, else the nearest diameter; the length nearest to the old one, else the type's usual length."""
    have = list(sizes(std, kind))
    if not have:
        return None, None
    if old_size in have:
        size = old_size
    else:
        try:
            d0 = SIZES[old_size][0]
            size = min((s for s in have if s in SIZES), key=lambda s: abs(SIZES[s][0] - d0))
        except Exception:
            size = have[len(have) // 2]
    length = None
    if TYPES[kind][3]:
        ls = lengths_for(std, kind, size)
        if ls:
            want = old_len if old_len is not None else 20
            length = min(ls, key=lambda L: abs(L - want))
    return size, length


def change(asm, comp, size=None, length=None, kind=None):
    """The fastener PM's Size / Length: the same type, another part file, same place. kind: another fastener type (extapps103)."""
    kind0, old_size, old_len = info(comp)
    if kind and kind != kind0:
        std0 = standard_of_comp(comp)
        size, length = default_size_length(std0, kind, kind0, old_size, old_len)
        if size is None:
            raise ValueError("%s has no size in %s" % (TYPES[kind][1], std0))
    kind = kind or kind0
    size = size or old_size
    length = length if length is not None else old_len
    keep_doc = App.ActiveDocument
    with standard(standard_of_comp(comp)):
        path = part_file(kind, size, length if TYPES[kind][3] else None)
    from . import designlib, asmcore
    src, _ = designlib._source(path)
    _front_doc(keep_doc if keep_doc is not None else asm.Document)       # extapps141: the assembly stays the active document
    target = asmcore.part_object(src) or next((o for o in src.Objects if hasattr(o, PROP)), None)
    keep = App.Placement(comp.Placement)
    comp.LinkedObject = target
    comp.Placement = keep
    comp.Label = asmcore._instance(asm, asmcore.part_name(comp))
    asm.Document.recompute()
    return comp


def create_part(url, size, length=None):
    ""

    kind = type_of(url)
    std = std_of_url(url)
    if kind is None:
        raise ValueError("not a Toolbox fastener")
    with standard(std):
        name = label(kind, size, length if TYPES[kind][3] else None)
        shp = shape(kind, size, length if TYPES[kind][3] else None)
    doc = App.newDocument(name.replace(" ", "_").replace("/", "_").replace("#", "No"))
    obj = doc.addObject("Part::Feature", "Fastener")
    obj.Shape = shp
    obj.Label = name
    doc.recompute()
    return doc


if Gui is not None:
    class CreatePartDialog(QtWidgets.QDialog):
        """Size and Length of the fastener Create Part... makes."""

        def __init__(self, url, parent=None):
            super().__init__(parent)
            self.url = url
            self.kind, self.std = type_of(url), std_of_url(url)
            self.setObjectName("SWToolboxCreatePart")
            self.setWindowTitle("Create Part")
            lay = QtWidgets.QVBoxLayout(self)
            form = QtWidgets.QFormLayout()
            lay.addLayout(form)
            self.size = QtWidgets.QComboBox()
            self.size.setObjectName("SWToolboxCreateSize")
            self.size.addItems([("%g" % s) if isinstance(s, float) else str(s) for s in sizes(self.std, self.kind)])
            form.addRow("Diameter:" if self.kind in PINS else "Size:", self.size)
            self.length = QtWidgets.QComboBox()
            self.length.setObjectName("SWToolboxCreateLength")
            form.addRow("Length:", self.length)
            self.size.currentTextChanged.connect(lambda *_a: self._fill())
            self._fill()
            if not TYPES[self.kind][3]:
                self.length.setVisible(False)
                form.labelForField(self.length).setVisible(False)
            buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            lay.addWidget(buttons)

        def pick(self):
            size = self.size.currentText()
            if self.kind in PINS and size not in PINS_INCH:
                size = float(size)
            return size, (self.length.currentData() if TYPES[self.kind][3] else None)

        def _fill(self):
            if not TYPES[self.kind][3]:
                return
            size = self.size.currentText()
            try:
                size = float(size) if (self.kind in PINS and size not in PINS_INCH) else size
                ls = lengths_for(self.std, self.kind, size)
            except Exception:
                ls = list(lengths(self.std))
            keep = self.length.currentData() if self.length.count() else None
            self.length.clear()
            for L in ls:
                self.length.addItem(length_text(self.std, L), L)
            if ls:
                self.length.setCurrentIndex(ls.index(min(ls, key=lambda L: abs(L - (keep if keep is not None else 20)))))

    class KindPicker(QtWidgets.QDialog):
        """Configure Component > Change Fastener Type...: the standard's Toolbox folders and types to pick another one from."""

        def __init__(self, std, current, parent=None):
            super().__init__(parent)
            self.setObjectName("SWToolboxChangeType")
            self.setWindowTitle("Change Fastener Type")
            lay = QtWidgets.QVBoxLayout(self)
            self.tree = QtWidgets.QTreeWidget()
            self.tree.setObjectName("SWToolboxChangeTypeTree")
            self.tree.setHeaderHidden(True)
            lay.addWidget(self.tree)
            top = {}
            for key, (folder, _n, _s, _l) in TYPES.items():
                if not sizes(std, key):
                    continue
                parent_item = None
                for i, part in enumerate(folder.split("/")):
                    path = "/".join(folder.split("/")[:i + 1])
                    if path not in top:
                        it = QtWidgets.QTreeWidgetItem([part])
                        (parent_item.addChild(it) if parent_item is not None else self.tree.addTopLevelItem(it))
                        top[path] = it
                    parent_item = top[path]
                leaf = QtWidgets.QTreeWidgetItem(["%s %s" % (TYPES[key][2][std], TYPES[key][1])])
                leaf.setData(0, Qt.UserRole, key)
                parent_item.addChild(leaf)
                if key == current:
                    self.tree.setCurrentItem(leaf)
            self.tree.expandAll()
            buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            lay.addWidget(buttons)
            self.tree.itemDoubleClicked.connect(lambda it, _c: self.accept() if it.data(0, Qt.UserRole) else None)

        def kind(self):
            it = self.tree.currentItem()
            return it.data(0, Qt.UserRole) if it is not None else None

    class _PM:
        ""


        def isVisible(self):
            try:
                return any(w.isVisible() for w in self.form)
            except RuntimeError as _fw_err:
                _fw_log("toolbox.py:1218", _fw_err)
                return False

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        GATE_OK = True      # OK waits for a size (a fastener's own PM); Smart Fasteners: never

        def _gate_ok(self):
            if not self.GATE_OK:
                return
            try:
                from . import pmconfirm
                button = pmconfirm._button("ok")
                if button is not None:
                    button.setEnabled(self.size.count() > 0)
            except Exception as _fw_err:
                _fw_log("toolbox.py:1190", _fw_err)

        def start(self):
            # (not open(): FreeCAD's task dialog calls a panel's open() when it shows it)
            from . import asmpm
            if Gui.Control.activeDialog():
                if not asmpm.close_open():
                    Gui.Control.closeDialog()
            asmpm._track(self)
            Gui.Control.showDialog(self)
            self._gate_ok()
            QtCore.QTimer.singleShot(0, self._gate_ok)
            return self

        def _close(self):
            try:
                Gui.Control.closeDialog()
            except Exception as _fw_err:
                _fw_log("toolbox.py:1208", _fw_err)
            return True

    class FastenerPanel(_PM):
        """A Toolbox component's Configure Component PropertyManager: Properties (Size, Length,
        Thread Length) and Part Number / Description, as the BOM shows them."""

        def __init__(self, asm, comps, parent=None):
            from . import asmpm
            self.asm, self.comps = asm, [c for c in comps if is_fastener(c)]
            kind, size, length = info(self.comps[0])
            self.kind = kind
            # extapps103: Replace Component first, as the Configure Component PM has it: the type's place in the library and Change Fastener Type...
            rbox, rl = asmpm._box("Replace Component")
            rbox.setObjectName("SWToolboxReplace")
            self.change_type = QtWidgets.QPushButton("Change Fastener Type...")
            self.change_type.setObjectName("SWToolboxChangeTypeButton")
            self.change_type.clicked.connect(lambda *_a: self._change_type())
            rl.addWidget(self.change_type)
            self.where = QtWidgets.QLabel("")
            self.where.setObjectName("SWToolboxPath")
            self.where.setWordWrap(True)
            rl.addWidget(self.where)
            box, lay = asmpm._box("Properties", TYPES[kind][1])
            box.setObjectName("SWToolboxFastener")
            self.box = box
            form = QtWidgets.QFormLayout()
            lay.addLayout(form)
            self.size = QtWidgets.QComboBox()
            self.size.setObjectName("SWToolboxSize")
            self.std = standard_of_comp(self.comps[0])
            have = list(sizes(self.std, kind))
            now = ("%g" % size) if isinstance(size, float) else str(size)
            self.size.addItems(have if now in have else have + [now])        # a size made before the list shrank stays
            self.size.setCurrentText(now)
            form.addRow("Diameter:" if kind in PINS else "Size:", self.size)
            self.length = QtWidgets.QComboBox()
            self.length.setObjectName("SWToolboxLength")
            self._length0 = length
            self._fill_lengths()
            form.addRow("Length:", self.length)
            if not TYPES[kind][3]:          # a nut or washer has no length: the row is not shown
                self.length.setVisible(False)
                if form.labelForField(self.length) is not None:
                    form.labelForField(self.length).setVisible(False)
            self.thread = QtWidgets.QLineEdit()
            self.thread.setObjectName("SWToolboxThreadLength")
            self.thread.setReadOnly(True)
            form.addRow("Thread Length:", self.thread)
            self.thread_display = QtWidgets.QLineEdit("Simplified")        # the one display the parts are made in: shown, not typed in
            self.thread_display.setObjectName("SWToolboxThreadDisplay")
            self.thread_display.setReadOnly(True)
            form.addRow("Thread Display:", self.thread_display)
            self.part = self.comps[0].getLinkedObject(True)
            self.comment = QtWidgets.QLineEdit(getattr(self.part, "ToolboxComment", "") or "")
            self.comment.setObjectName("SWToolboxComment")
            form.addRow("Comment:", self.comment)
            self.desc = QtWidgets.QLineEdit(getattr(self.part, "Label2", "") or "")
            self.desc.setObjectName("SWToolboxDescription")
            self.desc.setCursorPosition(0)       # extapps144: a long description reads from its start
            form.addRow("Description:", self.desc)
            self.config = QtWidgets.QLineEdit("")
            self.config.setObjectName("SWToolboxConfigName")
            self.config.setReadOnly(True)
            self.config.setCursorPosition(0)
            form.addRow("Configuration Name:", self.config)
            self.size.currentTextChanged.connect(lambda *_a: (self._fill_lengths(), self._thread()))
            self.length.currentIndexChanged.connect(lambda *_a: self._thread())
            self._thread()
            self._labels(form)
            try:        # extapps144: a short screen (1366 x 768): Part Numbers starts closed, so Properties and Options show without scrolling
                if QtWidgets.QApplication.primaryScreen().availableGeometry().height() < 800:
                    from . import safe_later as _sl; _sl.later(400, lambda: asmpm.fold(self.numbers), self, "numbers")
            except Exception as _fw_err:
                _fw_log("toolbox.py:fold", _fw_err)

            pbox, pl = asmpm._box("Part Numbers")
            pbox.setObjectName("SWToolboxPartNumbers")
            self.number = QtWidgets.QLineEdit(self.part.Label)        # the number in hand (not shown: the list below shows it)
            self.number.setObjectName("SWToolboxPartNumber")
            self.numbers = QtWidgets.QListWidget()
            self.numbers.setObjectName("SWToolboxPartNumberList")
            self.numbers.setFixedHeight(asmpm._rows(self.numbers, 2))
            pl.addWidget(self.numbers)
            nrow = QtWidgets.QHBoxLayout()
            self.num_add = QtWidgets.QPushButton("Add")
            self.num_add.setObjectName("SWToolboxPartNumberAdd")
            self.num_edit = QtWidgets.QPushButton("Edit")
            self.num_edit.setObjectName("SWToolboxPartNumberEdit")
            self.num_delete = QtWidgets.QPushButton("Delete")
            self.num_delete.setObjectName("SWToolboxPartNumberDelete")
            for b in (self.num_add, self.num_edit, self.num_delete):
                nrow.addWidget(b)
            nrow.addStretch(1)
            pl.addLayout(nrow)
            self.num_add.clicked.connect(lambda *_a: self._number_ask(""))
            self.num_edit.clicked.connect(lambda *_a: self._number_ask(self.number.text()))
            self.num_delete.clicked.connect(lambda *_a: self._number_set(None))
            self._assigned = self._auto_name() != self.part.Label
            self._numbers_refresh()
            # Options: Autosize to mated geometry, only for a fastener that is mated to a hole (never greyed)
            obox, ol = asmpm._box("Options")
            obox.setObjectName("SWToolboxOptions")
            self.autosize = QtWidgets.QCheckBox("Autosize to mated geometry")
            self.autosize.setObjectName("SWToolboxAutosize")
            ol.addWidget(self.autosize)
            self._auto, self._auto_busy = None, False
            if len(self.comps) == 1 and TYPES[kind][3] is not None:
                try:
                    self._auto = autosize(self.asm, self.comps[0])
                except Exception as _fw_err:
                    _fw_log("toolbox.py:autosize0", _fw_err)
            obox.setVisible(self._auto is not None)
            if self._auto is not None:
                have_size = self.size.currentText()
                cur_len = self.length.currentData() if TYPES[kind][3] else None
                self.autosize.setChecked(str(self._auto[0]) == have_size and (self._auto[1] is None or cur_len is None or abs(self._auto[1] - cur_len) < 1e-6))
                self.autosize.toggled.connect(lambda on: self._apply_auto() if on else None)
                # a size or length changed by hand (anything but Autosize itself): Autosize off
                self.size.currentTextChanged.connect(lambda *_a: None if self._auto_busy else self.autosize.setChecked(False))
                self.length.currentIndexChanged.connect(lambda *_a: None if self._auto_busy else self.autosize.setChecked(False))
            self.form = [rbox, pbox, box, obox]

        def _auto_name(self):
            """The part's own name for its size and length (what it is called with no number assigned)."""
            try:
                kind, size, length = info(self.comps[0])
                with standard(self.std):
                    return label(kind, size, length if TYPES[kind][3] else None)
            except Exception:
                return ""

        def _numbers_refresh(self):
            self.numbers.clear()
            self.numbers.addItem(self.number.text() if self._assigned else "Part Number Unassigned")
            self.num_add.setVisible(not self._assigned)
            self.num_edit.setVisible(self._assigned)
            self.num_delete.setVisible(self._assigned)

        def _number_ask(self, now):
            text, ok = QtWidgets.QInputDialog.getText(self.numbers, "Part Number", "Part number:", text=now)
            if ok and text.strip():
                self._number_set(text.strip())

        def _number_set(self, text):
            """Add / Edit: this number; Delete (None): back to the part's own name."""
            if text is None:
                self.number.setText(self._auto_name() or self.number.text())
                self._assigned = False
            else:
                self.number.setText(text)
                self._assigned = True
            self._numbers_refresh()

        def _apply_auto(self):
            """Autosize on: the size from the hole, the length from the stack in it."""
            try:
                res = autosize(self.asm, self.comps[0])
            except Exception as _fw_err:
                _fw_log("toolbox.py:autosize1", _fw_err)
                return
            if res is None:
                return
            size, length = res
            text = ("%g" % size) if isinstance(size, float) else str(size)
            self._auto_busy = True
            try:
                self.size.blockSignals(True)
                if self.size.findText(text) >= 0:
                    self.size.setCurrentText(text)
                self.size.blockSignals(False)
                self._length0 = length if length is not None else self._length0
                self._fill_lengths()
                if length is not None:
                    for i in range(self.length.count()):
                        if abs(float(self.length.itemData(i)) - length) < 1e-6:
                            self.length.setCurrentIndex(i)
                self._thread()
            finally:
                self._auto_busy = False

        def _labels(self, form=None):
            """The type's place in the library, and the rows that only some types have."""
            self.where.setText("Toolbox / %s / %s" % (self.std, TYPES[self.kind][0].replace("/", " / ")))
            threaded = self.kind not in PINS and self.kind not in WASHERS
            has_thread = threaded and bool(TYPES[self.kind][3])         # a nut has no length, so no thread length to show
            self.thread.setVisible(has_thread)
            form = form or self.box.layout().itemAt(0).layout()
            # extapps143: the Thread Display choice (Simplified / Cosmetic / Schematic) is asmthread's list under Thread Length; the plain
            # read-only line that was here showed a second "Thread Display" row, so it stays hidden
            for w, on in ((self.thread_display, False), (getattr(self, "_fw_thread_combo", None), threaded), (self.thread, has_thread)):
                if w is None:
                    continue
                w.setVisible(on)
                lab = form.labelForField(w)
                if lab is not None:
                    lab.setVisible(on)

        def _change_type(self):
            """Change Fastener Type...: pick another type of this standard; the component changes in place to its nearest size."""
            dlg = KindPicker(self.std, self.kind, Gui.getMainWindow())
            if dlg.exec() != QtWidgets.QDialog.Accepted:
                return
            new = dlg.kind()
            if not new or new == self.kind:
                return
            doc = self.asm.Document
            scratch_ready()      # extapps142: before the step opens
            doc.openTransaction("Change Fastener Type")
            try:
                for c in self.comps:
                    change(self.asm, c, kind=new)
            except Exception as error:
                doc.abortTransaction()
                App.Console.PrintWarning("FreeCAD: Toolbox change type: %s\n" % error)
                return
            doc.commitTransaction()
            kind, size, length = info(self.comps[0])
            self.kind, self._length0 = kind, length
            self.part = self.comps[0].getLinkedObject(True)
            self.box.setTitle(TYPES[kind][1]) if hasattr(self.box, "setTitle") else None
            have = list(sizes(self.std, kind))
            now = ("%g" % size) if isinstance(size, float) else str(size)
            self.size.blockSignals(True)
            self.size.clear()
            self.size.addItems(have if now in have else have + [now])
            self.size.setCurrentText(now)
            self.size.blockSignals(False)
            self._fill_lengths()
            has_len = TYPES[kind][3]
            self.length.setVisible(bool(has_len))
            lab = self.box.layout().itemAt(0).layout().labelForField(self.length)
            if lab is not None:
                lab.setVisible(bool(has_len))
            self._thread()
            self._labels()
            self.number.setText(self.part.Label)
            self.desc.setText(getattr(self.part, "Label2", "") or "")
            self.comment.setText(getattr(self.part, "ToolboxComment", "") or "")
            self._assigned = self._auto_name() != self.part.Label
            self._numbers_refresh()

        def _fill_lengths(self):
            """The lengths listed for the size picked; the length in hand stays when the size lists it, else the
            nearest one."""
            if not TYPES[self.kind][3]:
                return
            keep = self.length.currentData() if self.length.count() else self._length0
            size = self.size.currentText()
            try:
                size = float(size) if (self.kind in PINS and size not in PINS_INCH) else size
                ls = lengths_for(self.std, self.kind, size)
            except Exception:
                ls = list(lengths(self.std))
            self.length.blockSignals(True)
            self.length.clear()
            for L in ls:
                self.length.addItem(length_text(self.std, L), L)
            if keep is not None and ls:
                near = min(ls, key=lambda L: abs(L - keep))
                self.length.setCurrentIndex(ls.index(near))
            self.length.blockSignals(False)

        def _thread(self):
            try:
                size = self.size.currentText()
                if self.kind in PINS:
                    self.thread.setText("")
                    return
                L = float(self.length.currentData()) if TYPES[self.kind][3] else None
                b = thread_length(self.kind, size, L)
                self.thread.setText(length_text(self.std, b) if (b is not None and self.std != "ANSI Inch")
                                    else ("%.3f in" % (b / IN) if b is not None else ""))
            except Exception:
                self.thread.setText("")
            try:        # the Configuration Name: the part's name for this size and length
                with standard(self.std):
                    sz = self.size.currentText()
                    if self.kind in PINS and sz not in PINS_INCH:
                        sz = float(sz)
                    self.config.setText(label(self.kind, sz, float(self.length.currentData()) if TYPES[self.kind][3] else None))
                    self.config.setCursorPosition(0)        # extapps143: the name reads from its start, not its end
            except Exception:
                self.config.setText("")

        def accept(self):
            kind = info(self.comps[0])[0]
            if self.autosize.isChecked() and not self.autosize.isHidden():
                self._apply_auto()          # extapps104: the hole and its stack as they are now
            size = self.size.currentText()
            if kind in PINS and size not in PINS_INCH:
                size = float(size)
            length = float(self.length.currentData()) if TYPES[kind][3] else None
            number, desc = self.number.text().strip(), self.desc.text().strip()
            old_number = self.part.Label
            doc = self.asm.Document
            scratch_ready()      # extapps142: before the step opens
            doc.openTransaction("Edit Toolbox Component")
            try:
                for c in self.comps:
                    change(self.asm, c, size, length)
            finally:
                doc.commitTransaction()
            part = self.comps[0].getLinkedObject(True)
            same = part is self.part
            if (number and (number != old_number or not same)) or desc != (getattr(part, "Label2", "") or ""):
                set_part_numbers(part, number if (number != old_number or same) else None, desc)
            note = self.comment.text().strip()
            if note != (getattr(part, "ToolboxComment", "") or ""):
                try:
                    if not hasattr(part, "ToolboxComment"):
                        part.addProperty("App::PropertyString", "ToolboxComment", "Toolbox", "Comment shown in the Configure Component PM")
                    part.ToolboxComment = note
                    if part.Document.FileName:
                        part.Document.save()
                except Exception as _fw_err:
                    _fw_log("toolbox.py:comment", _fw_err)
            return self._close()

        def reject(self):
            return self._close()

    class SmartFastenersPanel(_PM):
        ""




        GATE_OK = False     # its Size list is empty until a Results group is picked: OK stays on

        def __init__(self, asm, comps=None, parent=None):
            from . import asmpm
            self.asm = asm
            self.comps = list(comps or [])
            self.entries = []       # {"hole", "comps", "kind", "size", "length", "default"}
            self.current = []       # the entries of the group picked in Results
            self._filling = False
            box, bl = asmpm._box("Selection", "Smart Fasteners")
            box.setObjectName("SWSmartFasteners")
            self.selection = QtWidgets.QListWidget()
            self.selection.setObjectName("SWSmartFastenersSelection")
            self.selection.setStyleSheet(asmpm.PICK_STYLE)
            try:        # extapps145: a short screen (1366 x 768): fewer empty rows in the lists, so the PM needs no scrolling
                short = QtWidgets.QApplication.primaryScreen().availableGeometry().height() < 800
            except Exception:
                short = False
            self.selection.setFixedHeight(asmpm._rows(self.selection, 2 if short else 3))
            for c in self.comps:
                self.selection.addItem(c.Label)
            bl.addWidget(self.selection)
            row = QtWidgets.QHBoxLayout()
            self.add = QtWidgets.QPushButton("Add")
            self.add.setObjectName("SWSmartFastenersAdd")
            self.populate = QtWidgets.QPushButton("Populate All")
            self.populate.setObjectName("SWSmartFastenersPopulate")
            row.addWidget(self.add)
            row.addWidget(self.populate)
            bl.addLayout(row)
            rbox, rl = asmpm._box("Results")
            self.results = QtWidgets.QTreeWidget()
            self.results.setObjectName("SWSmartFastenersResults")
            self.results.setHeaderLabels(["Group", "Qty"])
            self.results.setFixedHeight(asmpm._rows(self.results, 3 if short else 5))
            self.results.setContextMenuPolicy(Qt.CustomContextMenu)
            self.results.customContextMenuRequested.connect(self._results_menu)
            self.results.itemSelectionChanged.connect(self._picked_group)
            rl.addWidget(self.results)
            row = QtWidgets.QHBoxLayout()
            self.edit_group = QtWidgets.QPushButton("Edit Grouping")
            self.edit_group.setObjectName("SWSmartFastenersEditGrouping")
            self.edit_group.setToolTip("Split the picked fastener out of its group, or put it back")
            self.edit_group.clicked.connect(lambda: self.split_picked())
            self.edit_group.setVisible(False)       # extapps96: only while a fastener row is picked in Results (nothing to do otherwise)
            row.addWidget(self.edit_group)
            row.addStretch(1)
            rl.addLayout(row)
            sbox, fl = asmpm._box("Series Components")
            fl2 = QtWidgets.QFormLayout()
            fl.addLayout(fl2)
            self.kind = QtWidgets.QComboBox()
            self.kind.setObjectName("SWSmartFastenersType")
            self.kind.addItem("Default (from the Hole Wizard hole)", None)
            for k in SCREWS:
                self.kind.addItem(TYPES[k][1], k)
            fl2.addRow("Fastener:", self.kind)
            self.auto = QtWidgets.QCheckBox("Auto size to mated geometry")
            self.auto.setObjectName("SWSmartFastenersAutoSize")
            self.auto.setChecked(True)
            fl.addWidget(self.auto)
            fl.addWidget(QtWidgets.QLabel("Top Stack:"))
            self.top = QtWidgets.QComboBox()
            self.top.setObjectName("SWSmartFastenersTopStack")
            self.top.addItem("None", None)
            for k in WASHERS:
                self.top.addItem(TYPES[k][1], k)
            fl.addWidget(self.top)
            fl.addWidget(QtWidgets.QLabel("Bottom Stack:"))
            self.bottom = QtWidgets.QListWidget()
            self.bottom.setObjectName("SWSmartFastenersBottomStack")
            self.bottom.setFixedHeight(asmpm._rows(self.bottom, 2 if short else 3))
            top0, bottom0 = None, ("plain-washer", "hex-nut")
            try:        # Options > Hole Wizard/Toolbox > Configure: the Smart Fasteners stacks to start with
                from . import toolboxconfig
                st = toolboxconfig.stacks()
                top0 = next((x for x in (st.get("top") or "").split(",") if x), None)
                bottom0 = tuple(x for x in (st.get("bottom") or "").split(",") if x)
            except Exception as _fw_err:
                _fw_log("toolbox.py:1374", _fw_err)
            if top0 in WASHERS:
                self.top.setCurrentIndex(self.top.findData(top0))
            for k in bottom0:
                if k in TYPES:
                    self._bottom_item(k)
            fl.addWidget(self.bottom)
            row = QtWidgets.QHBoxLayout()
            self.bottom_kind = QtWidgets.QComboBox()
            self.bottom_kind.setObjectName("SWSmartFastenersBottomKind")
            for k in WASHERS + NUTS:
                self.bottom_kind.addItem(TYPES[k][1], k)
            self.bottom_add = QtWidgets.QPushButton("Add")
            self.bottom_add.setObjectName("SWSmartFastenersBottomAdd")
            self.bottom_del = QtWidgets.QPushButton("Remove")
            self.bottom_del.setObjectName("SWSmartFastenersBottomRemove")
            row.addWidget(self.bottom_kind, 1)
            row.addWidget(self.bottom_add)
            row.addWidget(self.bottom_del)
            fl.addLayout(row)
            pbox, pl = asmpm._box("Properties")
            pform = QtWidgets.QFormLayout()
            pl.addLayout(pform)
            self.size = QtWidgets.QComboBox()
            self.size.setObjectName("SWSmartFastenersSize")
            self.length = QtWidgets.QComboBox()
            self.length.setObjectName("SWSmartFastenersLength")
            pform.addRow("Size:", self.size)
            pform.addRow("Length:", self.length)
            self.thread = QtWidgets.QLineEdit()        # as Configure Component: shown, not typed in
            self.thread.setObjectName("SWSmartFastenersThreadLength")
            self.thread.setReadOnly(True)
            pform.addRow("Thread Length:", self.thread)
            self.pbox = pbox
            self.form = [box, rbox, sbox, pbox]
            QtCore.QTimer.singleShot(0, lambda: None if getattr(self, "_gone", False) else self._props_shown(False))
            self.made = {}
            self.add.clicked.connect(lambda: self.run(self.comps or None))
            self.populate.clicked.connect(lambda: self.run(None))
            self.bottom_add.clicked.connect(lambda: self._bottom_changed(add=self.bottom_kind.currentData()))
            self.bottom_del.clicked.connect(lambda: self._bottom_changed(remove=True))
            self.top.currentIndexChanged.connect(lambda *_a: self._changed())
            self.auto.toggled.connect(lambda *_a: self._changed())
            self.kind.currentIndexChanged.connect(lambda *_a: self._changed(kind=True))
            self.size.currentTextChanged.connect(lambda *_a: self._changed(size=True))
            self.length.currentIndexChanged.connect(lambda *_a: self._changed(length=True))
            Gui.Selection.addObserver(self, 0)

        def _bottom_item(self, k):
            it = QtWidgets.QListWidgetItem(TYPES[k][1])
            it.setData(Qt.UserRole, k)
            self.bottom.addItem(it)

        def bottom_stack(self):
            return tuple(self.bottom.item(i).data(Qt.UserRole) for i in range(self.bottom.count()))

        def _bottom_changed(self, add=None, remove=False):
            if add:
                self._bottom_item(add)
            if remove:
                row = self.bottom.currentRow()
                if row < 0:
                    row = self.bottom.count() - 1
                if row >= 0:
                    self.bottom.takeItem(row)
            self._changed()

        def addSelection(self, doc, obj, sub, pnt):
            from . import asmcore
            o = App.getDocument(doc).getObject(obj) if doc in App.listDocuments() else None
            if o is None:
                return
            names = {c.Name: c for c in asmcore.components(self.asm)}
            comp = names.get(obj) or names.get((sub or "").split(".")[0])
            if comp is not None and comp not in self.comps and not is_fastener(comp):
                self.comps.append(comp)
                self.selection.addItem(comp.Label)

        def options(self):
            return dict(kind=self.kind.currentData(), top_stack=self.top.currentData(),
                        bottom_stack=self.bottom_stack(), auto_length=self.auto.isChecked())

        # ------------------------------------------------------------ the work
        def _put(self, hole, kind, size=None, length=None):
            o = self.options()
            return put_in(self.asm, hole, kind, size=size, length=length, top_stack=o["top_stack"],
                          bottom_stack=o["bottom_stack"], auto_length=o["auto_length"] or length is None)

        def run(self, comps):
            doc = self.asm.Document
            scratch_ready()      # extapps142: before the step opens
            doc.openTransaction("Smart Fasteners")
            groups = {}
            try:
                holes = all_holes(self.asm, comps)
                if not holes:
                    doc.abortTransaction()
                    doc = None
                    _smart_notice(NO_HOLES)
                    self._done()
                    self._close()
                    return groups
                for hole in holes:
                    spec = wizard_spec(hole_hosts(*hole["axis"]))
                    default = kind_for(spec) if spec else "socket-head-cap-screw"
                    if default in PINS:
                        default = "socket-head-cap-screw"
                    kind = self.kind.currentData() or default
                    made = self._put(hole, kind)
                    self.entries.append({"hole": hole, "comps": made, "kind": kind, "default": default})
                    groups.setdefault(made[0].FwFastenerGroup, []).extend(made)
            finally:
                if doc is not None:
                    doc.commitTransaction()
            for g, cs in groups.items():
                self.made.setdefault(g, []).extend(cs)
            self.show_results()
            return groups

        def redo(self, entries, kind=None, size=None, length=None):
            """The entries' fasteners put in again: another type, size or length, or the stacks
            and Auto size as the PM now says."""
            doc = self.asm.Document
            scratch_ready()      # extapps142: before the step opens
            doc.openTransaction("Smart Fasteners")
            try:
                for e in entries:
                    old_kind, old_size, old_len = info(e["comps"][0])
                    for c in e["comps"]:
                        try:
                            _remove(self.asm, c)
                        except Exception as _fw_err:
                            _fw_log("toolbox.py:1495", _fw_err)
                    e["kind"] = kind or e["kind"]
                    keep_size = size or (old_size if e.get("size") else None)
                    e["comps"] = self._put(e["hole"], e["kind"], size=keep_size, length=length)
                    if size:
                        e["size"] = size
            finally:
                doc.commitTransaction()
            doc.recompute()
            self._regroup()
            return entries

        def _regroup(self):
            self.made = {}
            for e in self.entries:
                self.made.setdefault(e["comps"][0].FwFastenerGroup, []).extend(e["comps"])
            self.show_results()

        def load(self, fasteners=None):
            """Edit Smart Fastener: the fasteners' groups in Results, their stacks in Series
            Components, to change as when they were put in (Cancel puts them back)."""
            es = fastener_entries(self.asm, fasteners)
            self._filling = True
            try:
                if es:
                    self.top.setCurrentIndex(max(0, self.top.findData(es[0]["top"])))
                    self.bottom.clear()
                    for k in es[0]["bottom"]:
                        if k in TYPES:
                            self._bottom_item(k)
            finally:
                self._filling = False
            self.entries.extend(es)
            self._regroup()
            if es:
                self.pick_group(es[0]["comps"][0].FwFastenerGroup)
            return es

        def _put_back(self, e):
            """Cancel on an edited Smart Fastener: as it was before the PM."""
            w = e["was"]
            try:
                same = all(c.isValid() for c in w["comps"]) and e["comps"] == w["comps"]
            except Exception:
                same = False
            if same:
                for c in w["comps"]:
                    c.FwFastenerGroup = w["group"]
                return
            for c in e["comps"]:
                try:
                    _remove(self.asm, c)
                except Exception as _fw_err:
                    _fw_log("toolbox.py:put_back", _fw_err)
            made = put_in(self.asm, e["hole"], w["kind"], size=w["size"], length=w["length"],
                          top_stack=w["top"], bottom_stack=w["bottom"], auto_length=w["length"] is None)
            for c in made:
                c.FwFastenerGroup = w["group"]

        def group_entries(self, group):
            return [e for e in self.entries if e["comps"] and e["comps"][0].FwFastenerGroup == group]

        def change_type(self, group, kind):
            return self.redo(self.group_entries(group), kind=kind)

        def revert(self, group):
            out = []
            for e in self.group_entries(group):
                out += self.redo([e], kind=e["default"])
            return out

        def set_size(self, group, size=None, length=None):
            return self.redo(self.group_entries(group), size=size, length=length)

        def split_picked(self):
            """Edit Grouping: the picked fastener gets a group of its own (its own size), or
            joins its type's group again."""
            it = self.results.currentItem()
            if it is None or it.parent() is None:
                return None
            idx = it.data(0, Qt.UserRole)
            if idx is None or not (0 <= idx < len(self.entries)):
                return None
            e = self.entries[idx]
            for c in e["comps"]:
                c.FwFastenerGroup = (c.FwFastenerGroup + " (%d)" % (idx + 1)) if "(" not in c.FwFastenerGroup \
                    else c.FwFastenerGroup.split(" (")[0]
            self._regroup()
            return e

        # ------------------------------------------------------------ the PM
        def show_results(self):
            self.results.blockSignals(True)
            self.results.clear()
            for g, cs in sorted(self.made.items()):
                screws = [c for c in cs if info(c) and info(c)[0] in SCREWS]
                it = QtWidgets.QTreeWidgetItem([g, str(len(screws))])
                it.setData(0, Qt.UserRole + 1, g)
                for i, e in enumerate(self.entries):
                    if e["comps"] and e["comps"][0] in cs:
                        ch = QtWidgets.QTreeWidgetItem([e["comps"][0].Label, ""])
                        ch.setData(0, Qt.UserRole, i)
                        ch.setData(0, Qt.UserRole + 1, g)
                        it.addChild(ch)
                self.results.addTopLevelItem(it)
            self.results.blockSignals(False)
            self._grouping_shown()

        def pick_group(self, group):
            for i in range(self.results.topLevelItemCount()):
                it = self.results.topLevelItem(i)
                if it.data(0, Qt.UserRole + 1) == group:
                    self.results.setCurrentItem(it)
                    return it
            return None

        def _props_shown(self, on):
            ""

            try:
                box = self.pbox
                while box is not None and not box.inherits("Gui::TaskView::TaskBox"):
                    box = box.parentWidget()
                (box or self.pbox).setVisible(on)
            except RuntimeError:
                pass

        def _grouping_shown(self):
            """Edit Grouping works on a fastener row, so it shows only while one is picked."""
            try:
                it = self.results.currentItem()
                self.edit_group.setVisible(it is not None and it.parent() is not None)
            except RuntimeError:
                pass

        def _picked_group(self):
            self._grouping_shown()
            it = self.results.currentItem()
            group = it.data(0, Qt.UserRole + 1) if it is not None else None
            self.current = self.group_entries(group) if group else []
            self._props_shown(bool(self.current))
            if not self.current:
                return
            kind, size, length = info(self.current[0]["comps"][0])
            std = standard_of_comp(self.current[0]["comps"][0])
            self._filling = True
            try:
                self.kind.setCurrentIndex(max(0, self.kind.findData(kind)))
                self.size.clear()
                self.size.addItems(sizes(std, kind))
                self.size.setCurrentText(str(size))
                self.length.clear()
                ls = lengths_for(std, kind, size if kind not in PINS or str(size) in PINS_INCH else float(size))
                if length is not None and length not in ls:
                    ls = sorted(ls + [length])
                for L in ls:
                    self.length.addItem(length_text(std, L), L)
                if length is not None:
                    self.length.setCurrentText(length_text(std, length))
                has = bool(TYPES[kind][3])
                self.length.setVisible(has)
                label = self.length.parentWidget().layout().labelForField(self.length) \
                    if isinstance(self.length.parentWidget().layout(), QtWidgets.QFormLayout) else None
                if label is not None:
                    label.setVisible(has)
                if not hasattr(self.length, "_fw_take_over"):
                    from .asmpattern import _takes_over
                    _takes_over(self.length, self.auto, False)    # a length picked: auto size off
                self._thread(kind, size, length, std)
            finally:
                self._filling = False
            self._gate_ok()

        def _thread(self, kind, size, length, std):
            try:
                b = None if kind in PINS else thread_length(kind, str(size), length if TYPES[kind][3] else None)
                self.thread.setText("" if b is None else
                                    length_text(std, b) if std != "ANSI Inch" else "%.3f in" % (b / IN))
            except Exception:
                self.thread.setText("")

        def _changed(self, kind=False, size=False, length=False):
            if self._filling or not self.current:
                return
            group = self.current[0]["comps"][0].FwFastenerGroup
            if kind and self.kind.currentData():
                self.change_type(group, self.kind.currentData())
            elif size:
                self.set_size(group, size=self.size.currentText())
            elif length and not self.auto.isChecked() and self.length.currentData() is not None:
                self.set_size(group, length=float(self.length.currentData()))
            else:
                self.redo(self.current)
            if self.current:
                self.pick_group(self.current[0]["comps"][0].FwFastenerGroup)

        def _results_menu(self, pos):
            it = self.results.itemAt(pos)
            if it is None:
                return
            group = it.data(0, Qt.UserRole + 1)
            menu = QtWidgets.QMenu(self.results)
            sub = menu.addMenu("Change fastener type")
            for k in SCREWS:
                sub.addAction(TYPES[k][1]).triggered.connect(lambda _c=False, k=k: self.change_type(group, k))
            menu.addAction("Revert to default").triggered.connect(lambda: self.revert(group))
            menu._fw_sub = sub
            menu.exec(self.results.viewport().mapToGlobal(pos))

        def _done(self):
            self._gone = True       # (a timer still to fire must not touch the closed PM)
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("toolbox.py:1635", _fw_err)

        def accept(self):
            self._done()
            return self._close()

        def reject(self):
            self._done()
            doc = self.asm.Document
            for e in self.entries:
                for c in e["comps"]:
                    try:
                        _remove(self.asm, c)
                    except Exception as _fw_err:
                        _fw_log("toolbox.py:1649", _fw_err)
            doc.recompute()
            return self._close()

    def _remove(asm, comp):
        from . import asmcore
        doc = asm.Document
        for j in list(asmcore.joint_group(asm).Group):
            refs = [getattr(j, "Reference1", None), getattr(j, "Reference2", None)]
            if any(r and (r[0] is comp or comp.Name in "".join(r[1] if isinstance(r[1], (list, tuple)) else [r[1]]))
                   for r in refs if r):
                doc.removeObject(j.Name)
        doc.removeObject(comp.Name)

    NO_HOLES = "No holes were found that support use of Smart Fasteners."
    CALC_NOTICE = ("Smart Fasteners calculations may take extra time if the assembly contains lightweight components "
                   "that need to be resolved or the assembly components contain many holes. Click OK to continue, "
                   "or click Cancel to terminate the operation.")

    def _smart_notice(text):
        ""
        box = QtWidgets.QMessageBox(Gui.getMainWindow())
        box.setWindowTitle("Smart Fasteners")
        box.setIcon(QtWidgets.QMessageBox.Information)
        box.setText(text)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        box.exec()

    def smart_calc_dialog(parent=None):
        ""

        box = QtWidgets.QMessageBox(parent or Gui.getMainWindow())
        box.setObjectName("SWSmartFastenersCalc")
        box.setWindowTitle("Smart Fasteners")
        box.setIcon(QtWidgets.QMessageBox.Information)
        box.setText(CALC_NOTICE)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel)
        box.setDefaultButton(QtWidgets.QMessageBox.Ok)
        cb = QtWidgets.QCheckBox("Don't show again")
        cb.setObjectName("SWSmartFastenersCalcDontShow")
        box.setCheckBox(cb)
        box._cb = cb        # (box.checkBox() brought the wrapper down in PySide)
        return box

    def _smart_calc_ok():
        """True to go on: the box (unless Don't show again was ticked there)."""
        prm = App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks/Toolbox")
        if not prm.GetBool("SmartFastenersAsk", True):
            return True
        box = smart_calc_dialog()
        ok = box.exec() == QtWidgets.QMessageBox.Ok
        if ok and box._cb.isChecked():
            prm.SetBool("SmartFastenersAsk", False)
        return ok

    def open_smart_fasteners(asm=None, comps=None, ask=True):
        from . import asmcore
        asm = asm or asmcore.assembly_of()
        if asm is None:
            return None
        if ask and not _smart_calc_ok():
            return None
        if comps is None:
            sel = Gui.Selection.getSelection()
            comps = [o for o in sel if o in asmcore.components(asm)]
        return SmartFastenersPanel(asm, comps).start()

    def _edit_reject(self, _plain=SmartFastenersPanel.reject):
        """Cancel: an edited Smart Fastener back as it was (then the new ones taken out)."""
        for e in [e for e in self.entries if e.get("was")]:
            self._put_back(e)
            self.entries.remove(e)
        return _plain(self)

    SmartFastenersPanel.reject = _edit_reject

    def edit_smart_fasteners(asm, fasteners):
        """Right-click a Smart Fastener > Edit Smart Fastener: the Smart Fasteners PM with its group."""
        p = SmartFastenersPanel(asm, []).start()
        p.load(fasteners)
        return p

    def open_fastener(asm, comps):
        return FastenerPanel(asm, comps).start()


try:
    from . import toolboxconfig     # Options > Hole Wizard/Toolbox > Configure: sizes left out, Smart Fasteners defaults
    toolboxconfig.install()
except Exception as _error:
    App.Console.PrintLog("FreeCAD: Toolbox Settings: %s\n" % _error)
