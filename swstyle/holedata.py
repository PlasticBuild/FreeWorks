# SPDX-License-Identifier: LGPL-2.1-or-later
""












import math

INCH = 25.4
STANDARDS = ["ANSI Inch", "ANSI Metric", "AS", "BSI", "DIN", "GB", "IS", "ISO", "JIS", "KS", "PEM Inch", "PEM Metric"]
METRIC_STANDARDS = [s for s in STANDARDS if s not in ("ANSI Inch", "PEM Inch")]
# AS (Australian) follows ISO; PEM lists its self-clinching hole types under Hole and borrows ANSI's for the rest
BASE = {"AS": "ISO", "PEM Inch": "ANSI Inch", "PEM Metric": "ANSI Metric"}


def is_inch(standard):
    return standard in ("ANSI Inch", "PEM Inch")
FITS = ("Close", "Normal", "Loose")

# ------------------------------------------------------------------ metric
# ISO 261 coarse pitches, every size FreeCAD's ISO metric tap list has (PATCH-MERGE PM thread pkg148:
# M1-M1.4, M1.8, M2.2, M4.5, M7, M9, M11, M39, M45, M52-M68 fell back to d x 0.15)
COARSE = {1: .25, 1.1: .25, 1.2: .25, 1.4: .3, 1.6: .35, 1.8: .35, 2: .4, 2.2: .45, 2.5: .45, 3: .5, 3.5: .6,
          4: .7, 4.5: .75, 5: .8, 6: 1.0, 7: 1.0, 8: 1.25, 9: 1.25, 10: 1.5, 11: 1.5, 12: 1.75,
          14: 2.0, 16: 2.0, 18: 2.5, 20: 2.5, 22: 2.5, 24: 3.0, 27: 3.0, 30: 3.5, 33: 3.5, 36: 4.0,
          39: 4.0, 42: 4.5, 45: 4.5, 48: 5.0, 52: 5.0, 56: 5.5, 60: 5.5, 64: 6.0, 68: 6.0}
FINE = [(8, 1.0), (10, 1.25), (10, 1.0), (12, 1.5), (12, 1.25), (14, 1.5), (16, 1.5), (18, 1.5), (20, 1.5),
        (20, 2.0), (22, 1.5), (24, 2.0), (27, 2.0), (30, 2.0), (33, 2.0), (36, 3.0), (42, 3.0), (48, 3.0)]
# clearance series fine / medium / coarse (Close / Normal / Loose)
CLEAR = {1.6: (1.7, 1.8, 2.0), 2: (2.2, 2.4, 2.6), 2.5: (2.7, 2.9, 3.1), 3: (3.2, 3.4, 3.6), 3.5: (3.7, 3.9, 4.2),
         4: (4.3, 4.5, 4.8), 5: (5.3, 5.5, 5.8), 6: (6.4, 6.6, 7.0), 8: (8.4, 9.0, 10.0), 10: (10.5, 11.0, 12.0),
         12: (13.0, 13.5, 14.5), 14: (15.0, 15.5, 16.5), 16: (17.0, 17.5, 18.5), 18: (19.0, 20.0, 21.0),
         20: (21.0, 22.0, 24.0), 22: (23.0, 24.0, 26.0), 24: (25.0, 26.0, 28.0), 27: (28.0, 30.0, 32.0),
         30: (31.0, 33.0, 35.0), 33: (34.0, 36.0, 38.0), 36: (37.0, 39.0, 42.0), 42: (43.0, 45.0, 48.0),
         48: (50.0, 52.0, 56.0)}
# heads: size -> (head diameter, head height)
SHCS = {1.6: (3.0, 1.6), 2: (3.8, 2), 2.5: (4.5, 2.5), 3: (5.5, 3), 4: (7, 4), 5: (8.5, 5), 6: (10, 6), 8: (13, 8),
        10: (16, 10), 12: (18, 12), 14: (21, 14), 16: (24, 16), 20: (30, 20), 24: (36, 24), 30: (45, 30),
        36: (54, 36), 42: (63, 42), 48: (72, 48)}
LOW_HEAD = {3: (5.5, 2), 4: (7, 2.8), 5: (8.5, 3.5), 6: (10, 4), 8: (13, 5), 10: (16, 6), 12: (18, 7), 16: (24, 9),
            20: (30, 11), 24: (36, 13)}
HEX_FLATS = {1.6: 3.2, 2: 4, 2.5: 5, 3: 5.5, 4: 7, 5: 8, 6: 10, 8: 13, 10: 16, 12: 18, 14: 21, 16: 24, 18: 27,
             20: 30, 22: 34, 24: 36, 27: 41, 30: 46, 33: 50, 36: 55, 42: 65, 48: 75}
HEX_HEIGHT = {1.6: 1.1, 2: 1.4, 2.5: 1.7, 3: 2, 4: 2.8, 5: 3.5, 6: 4, 8: 5.3, 10: 6.4, 12: 7.5, 14: 8.8, 16: 10,
              18: 11.5, 20: 12.5, 22: 14, 24: 15, 27: 17, 30: 18.7, 33: 21, 36: 22.5, 42: 26, 48: 30}
BUTTON = {3: (5.7, 1.65), 4: (7.6, 2.2), 5: (9.5, 2.75), 6: (10.5, 3.3), 8: (14, 4.4), 10: (17.5, 5.5),
          12: (21, 6.6), 16: (28, 8.8)}
PAN = {1.6: (3.2, 1.0), 2: (4, 1.3), 2.5: (5, 1.5), 3: (5.6, 1.8), 3.5: (7, 2.1), 4: (8, 2.4), 5: (9.5, 3),
       6: (12, 3.6), 8: (16, 4.8), 10: (20, 6)}
CHEESE = {1.6: (3, 1.1), 2: (3.8, 1.4), 2.5: (4.5, 1.8), 3: (5.5, 2), 4: (7, 2.6), 5: (8.5, 3.3), 6: (10, 3.9),
          8: (13, 5), 10: (16, 6)}
SHOULDER = {6: (10, 4.5), 8: (13, 5.5), 10: (16, 7), 12: (18, 8), 16: (24, 10), 20: (30, 14)}  # shoulder size
# countersunk heads: size -> head diameter (90 degrees)
CSK_SOCKET = {3: 6.72, 4: 8.96, 5: 11.2, 6: 13.44, 8: 17.92, 10: 22.4, 12: 26.88, 14: 30.8, 16: 33.6, 20: 40.32}
CSK_FLAT = {1.6: 3.0, 2: 3.8, 2.5: 4.7, 3: 5.5, 3.5: 7.3, 4: 8.4, 5: 9.3, 6: 11.3, 8: 15.8, 10: 18.3}
CSK_RAISED = CSK_FLAT
CSK_HEX = {3: 6.0, 4: 8.0, 5: 10.0, 6: 12.0, 8: 16.0, 10: 20.0, 12: 24.0, 16: 30.0, 20: 36.0}

# fit allowances (Close / Normal / Loose) on a counterbore or countersink diameter, and depth
CBORE_ALLOW = (0.5, 1.0, 2.0)
DEPTH_ALLOW = (0.2, 0.4, 0.8)

# (type name, tree word, head table, how) per standard family; how: "cbore", "hex", "csk"
METRIC_CBORE = [
    ("Socket Head Cap Screw", "Socket Head Cap Screw", SHCS, "cbore"),
    ("Socket Head Cap Screw, Low Head", "Low Head Cap Screw", LOW_HEAD, "cbore"),
    ("Hex Bolt", "Hex Bolt", None, "hex"),
    ("Hex Screw", "Hex Screw", None, "hex"),
    ("Socket Button Head Cap Screw", "Button Head Screw", BUTTON, "cbore"),
    ("Pan Head Cross Recess", "Pan Head Screw", PAN, "cbore"),
    ("Cheese Head Slotted", "Cheese Head Screw", CHEESE, "cbore"),
    ("Hex Socket Shoulder Screw", "Shoulder Screw", SHOULDER, "cbore"),
]
METRIC_CSK = [
    ("Socket Countersunk Head Cap Screw", "Countersunk Socket Head", CSK_SOCKET, "csk"),
    ("Flat Head Slotted", "Flat Head Screw", CSK_FLAT, "csk"),
    ("Flat Head Cross Recess", "Flat Head Screw", CSK_FLAT, "csk"),
    ("Raised Countersunk Head", "Raised Head Screw", CSK_RAISED, "csk"),
    ("Countersunk Hex Socket", "Countersunk Socket Head", CSK_HEX, "csk"),
]
# per standard: which types it lists (by name above) and the name it gives them
METRIC_TYPES = {
    "ANSI Metric": None, "ISO": None,           # all
    "DIN": {"Socket Head Cap Screw": "Socket Head Cap Screw DIN 912", "Hex Bolt": "Hex Bolt DIN 931",
            "Hex Screw": "Hex Screw DIN 933", "Cheese Head Slotted": "Cheese Head Slotted DIN 84",
            "Socket Head Cap Screw, Low Head": "Low Head Cap Screw DIN 7984",
            "Socket Button Head Cap Screw": "Button Head Screw DIN 7380",
            "Pan Head Cross Recess": "Pan Head Cross Recess DIN 7985",
            "Socket Countersunk Head Cap Screw": "Countersunk Socket Head DIN 7991",
            "Flat Head Slotted": "Flat Head Slotted DIN 963", "Flat Head Cross Recess": "Flat Head Cross DIN 965",
            "Raised Countersunk Head": "Raised Countersunk DIN 964"},
    "JIS": {"Socket Head Cap Screw": "Hexagon Socket Head Bolt", "Hex Bolt": "Hexagon Bolt",
            "Pan Head Cross Recess": "Cross Recessed Pan Head", "Cheese Head Slotted": "Slotted Cheese Head",
            "Socket Countersunk Head Cap Screw": "Hexagon Socket Countersunk", "Flat Head Cross Recess":
            "Cross Recessed Countersunk"},
    "BSI": {"Socket Head Cap Screw": "Socket Head Cap Screw", "Hex Bolt": "Hexagon Head Bolt",
            "Hex Screw": "Hexagon Head Screw", "Cheese Head Slotted": "Slotted Cheese Head",
            "Socket Countersunk Head Cap Screw": "Socket Countersunk Head", "Flat Head Slotted": "Slotted Countersunk"},
    "GB": {"Socket Head Cap Screw": "Hexagon Socket Head Cap Screw", "Hex Bolt": "Hexagon Head Bolt",
           "Pan Head Cross Recess": "Cross Recessed Pan Head", "Socket Countersunk Head Cap Screw":
           "Hexagon Socket Countersunk", "Flat Head Cross Recess": "Cross Recessed Countersunk"},
    "IS": {"Socket Head Cap Screw": "Hexagon Socket Head Cap Screw", "Hex Bolt": "Hexagon Head Bolt",
           "Hex Screw": "Hexagon Head Screw", "Flat Head Slotted": "Slotted Countersunk Head"},
    "KS": {"Socket Head Cap Screw": "Hexagon Socket Head Bolt", "Hex Bolt": "Hexagon Bolt",
           "Pan Head Cross Recess": "Cross Recessed Pan Head", "Flat Head Cross Recess": "Cross Recessed Countersunk"},
}

# ------------------------------------------------------------------ inch
NUMBERED = {"#0": .060, "#1": .073, "#2": .086, "#3": .099, "#4": .112, "#5": .125, "#6": .138, "#8": .164,
            "#10": .190, "#12": .216}
FRACTIONAL = {"1/4": .25, "5/16": .3125, "3/8": .375, "7/16": .4375, "1/2": .5, "9/16": .5625, "5/8": .625,
              "3/4": .75, "7/8": .875, "1": 1.0, "1 1/8": 1.125, "1 1/4": 1.25, "1 1/2": 1.5}
INCH_SIZES = list(NUMBERED) + list(FRACTIONAL)
UNC = {"#1": 64, "#2": 56, "#3": 48, "#4": 40, "#5": 40, "#6": 32, "#8": 32, "#10": 24, "#12": 24, "1/4": 20,
       "5/16": 18, "3/8": 16, "7/16": 14, "1/2": 13, "9/16": 12, "5/8": 11, "3/4": 10, "7/8": 9, "1": 8,
       "1 1/8": 7, "1 1/4": 7, "1 3/8": 6, "1 1/2": 6, "1 3/4": 5, "2": 4.5, "2 1/4": 4.5, "2 1/2": 4,
       "2 3/4": 4, "3": 4, "3 1/4": 4, "3 1/2": 4, "3 3/4": 4, "4": 4}     # ASME B1.1 (PATCH-MERGE pkg148: above 1 1/2)
UNF = {"#0": 80, "#1": 72, "#2": 64, "#3": 56, "#4": 48, "#5": 44, "#6": 40, "#8": 36, "#10": 32, "#12": 28,
       "1/4": 28, "5/16": 24, "3/8": 24, "7/16": 20, "1/2": 20, "9/16": 18, "5/8": 18, "3/4": 16, "7/8": 14,
       "1": 12, "1 1/8": 12, "1 1/4": 12, "1 3/8": 12, "1 1/2": 12}
# ASME B1.1 UNEF (PATCH-MERGE pkg148: 11/16, 13/16, 15/16 and the sizes above 1)
UNEF = {"#12": 32, "1/4": 32, "5/16": 32, "3/8": 32, "7/16": 28, "1/2": 28, "9/16": 24, "5/8": 24, "11/16": 24,
        "3/4": 20, "13/16": 20, "7/8": 20, "15/16": 20, "1": 20, "1 1/16": 18, "1 1/8": 18, "1 3/16": 18,
        "1 1/4": 18, "1 5/16": 18, "1 3/8": 18, "1 7/16": 18, "1 1/2": 18, "1 9/16": 18, "1 5/8": 18, "1 11/16": 18}
TAP_SERIES = {"UNC": UNC, "UNF": UNF, "UNEF": UNEF}
INCH_SHCS = {"#0": (.096, .060), "#1": (.118, .073), "#2": (.140, .086), "#3": (.161, .099), "#4": (.183, .112),
             "#5": (.205, .125), "#6": (.226, .138), "#8": (.270, .164), "#10": (.312, .190), "#12": (.343, .216),
             "1/4": (.375, .25), "5/16": (.469, .3125), "3/8": (.562, .375), "7/16": (.656, .4375),
             "1/2": (.75, .5), "5/8": (.938, .625), "3/4": (1.125, .75), "7/8": (1.312, .875), "1": (1.5, 1.0)}
INCH_HEX_FLATS = {"1/4": .4375, "5/16": .5, "3/8": .5625, "7/16": .625, "1/2": .75, "9/16": .8125, "5/8": .9375,
                  "3/4": 1.125, "7/8": 1.3125, "1": 1.5}
INCH_HEX_HEIGHT = {"1/4": .172, "5/16": .219, "3/8": .25, "7/16": .297, "1/2": .344, "9/16": .375, "5/8": .422,
                   "3/4": .5, "7/8": .578, "1": .672}
INCH_FLAT = {"#0": .119, "#1": .146, "#2": .172, "#3": .199, "#4": .225, "#5": .252, "#6": .279, "#8": .332,
             "#10": .385, "#12": .438, "1/4": .507, "5/16": .635, "3/8": .762, "7/16": .812, "1/2": .875,
             "5/8": 1.125, "3/4": 1.375}
INCH_BUTTON = {"#4": (.213, .059), "#6": (.262, .072), "#8": (.312, .093), "#10": (.361, .101), "1/4": (.437, .132),
               "5/16": (.547, .166), "3/8": (.656, .205), "1/2": (.875, .275), "5/8": (1.0, .344)}
INCH_PAN = {"#2": (.167, .053), "#4": (.219, .068), "#6": (.270, .082), "#8": (.322, .096), "#10": (.373, .110),
            "#12": (.425, .125), "1/4": (.492, .144), "5/16": (.615, .178), "3/8": (.740, .212)}
INCH_CBORE = [
    ("Socket Head Cap Screw", "Socket Head Cap Screw", INCH_SHCS, "cbore"),
    ("Hex Bolt", "Hex Bolt", None, "hex"),
    ("Hex Screw", "Hex Screw", None, "hex"),
    ("Button Head Cap Screw", "Button Head Screw", INCH_BUTTON, "cbore"),
    ("Pan Cross Head", "Pan Head Screw", INCH_PAN, "cbore"),
]
INCH_CSK = [
    ("Flat Head Socket Cap Screw (82)", "Flat Head Screw", INCH_FLAT, "csk82"),
    ("Flat Head Machine Screw (82)", "Flat Head Screw", INCH_FLAT, "csk82"),
    ("Flat Head Machine Screw (100)", "Flat Head Screw", INCH_FLAT, "csk100"),
]
# pipe threads: size -> (threads per inch, tap drill mm)
NPT = {"1/16": (27, 6.15), "1/8": (27, 8.43), "1/4": (18, 11.11), "3/8": (18, 14.68), "1/2": (14, 18.26),
       "3/4": (14, 23.42), "1": (11.5, 29.37), "1 1/4": (11.5, 38.1), "1 1/2": (11.5, 44.05), "2": (11.5, 56.36),
       # ASME B1.20.1 8 TPI, tap drills 2 5/8, 3 1/4, 3 3/4, 4 1/4 in (PATCH-MERGE pkg148)
       "2 1/2": (8, 66.68), "3": (8, 82.55), "3 1/2": (8, 95.25), "4": (8, 107.95),
       # ASME B1.20.1 Table 2, 8 TPI. 5 and 6: tap drills 5 9/32 and 6 11/32 in (Engineering ToolBox's
       # B1.20.1 table). 8, 10 and 12 have no published drill: the hole is K0, the table's minor diameter
       # at the small end (8.3336, 10.4453, 12.4328 in) (PATCH-MERGE pkg151)
       "5": (8, 134.14), "6": (8, 161.13), "8": (8, 211.67), "10": (8, 265.31), "12": (8, 315.79)}
BSPT = {"1/16": (28, 6.6), "1/8": (28, 8.4), "1/4": (19, 11.2), "3/8": (19, 14.75), "1/2": (14, 18.25),
        "3/4": (14, 23.75), "1": (11, 30.0), "1 1/4": (11, 38.5), "1 1/2": (11, 44.5), "2": (11, 56.0),
        # ISO 7-1 sizes above 2 (11 TPI); no published taper drill: the hole is the ISO 228-1 minor
        # diameter of the same size, the thread's diameter at the gauge plane (PATCH-MERGE pkg151)
        "2 1/2": (11, 72.226), "3": (11, 84.926), "4": (11, 110.072), "5": (11, 135.472), "6": (11, 160.872)}
# ISO 228-1 Table 1 (G, BSPP) major diameters, mm: ISO 7-1 R / Rc have the same diameter at the gauge
# plane, so the BSPT callout's diameter comes from here (pkg151)
BSP_MAJOR = {"1/16": 7.723, "1/8": 9.728, "1/4": 13.157, "3/8": 16.662, "1/2": 20.955, "5/8": 22.911,
             "3/4": 26.441, "7/8": 30.201, "1": 33.249, "1 1/8": 37.897, "1 1/4": 41.910, "1 1/2": 47.803,
             "1 3/4": 53.746, "2": 59.614, "2 1/4": 65.710, "2 1/2": 75.184, "2 3/4": 81.534, "3": 87.884,
             "3 1/2": 100.330, "4": 113.030, "4 1/2": 125.730, "5": 138.430, "5 1/2": 151.130, "6": 163.830}
# pipe outside diameters (inch), the thread's major diameter at the gauge plane
PIPE_OD = {"1/16": .3125, "1/8": .405, "1/4": .540, "3/8": .675, "1/2": .840, "3/4": 1.050, "1": 1.315,
           "1 1/4": 1.660, "1 1/2": 1.900, "2": 2.375, "2 1/2": 2.875, "3": 3.500, "3 1/2": 4.000, "4": 4.500,
           "5": 5.563, "6": 6.625, "8": 8.625, "10": 10.750, "12": 12.750}
NUMBER_DRILLS = {"#60": .040, "#55": .052, "#50": .070, "#45": .082, "#43": .089, "#40": .098, "#36": .1065,
                 "#33": .113, "#29": .136, "#25": .1495, "#21": .159, "#20": .161, "#16": .177, "#10": .1935,
                 "#7": .201, "#3": .213, "#1": .228}
LETTER_DRILLS = {"A": .234, "B": .238, "C": .242, "D": .246, "E": .250, "F": .257, "G": .261, "H": .266,
                 "I": .272, "J": .277, "K": .281, "L": .290, "M": .295, "N": .302, "O": .316, "P": .323,
                 "Q": .332, "R": .339, "S": .348, "T": .358, "U": .368, "V": .377, "W": .386, "X": .397,
                 "Y": .404, "Z": .413}
FRACTION_DRILLS = ["1/16", "3/32", "1/8", "5/32", "3/16", "7/32", "1/4", "9/32", "5/16", "11/32", "3/8", "13/32",
                   "7/16", "15/32", "1/2", "9/16", "5/8", "11/16", "3/4", "13/16", "7/8", "15/16", "1"]
METRIC_DRILLS = [0.5, 0.8, 1.0, 1.2, 1.5, 1.6, 1.8, 2.0, 2.2, 2.5, 2.8, 3.0, 3.2, 3.3, 3.5, 3.8, 4.0, 4.2, 4.5,
                 4.8, 5.0, 5.2, 5.5, 5.8, 6.0, 6.5, 6.8, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0, 10.2, 10.5, 11.0, 12.0,
                 13.0, 14.0, 15.0, 16.0, 17.0, 17.5, 18.0, 19.0, 20.0, 21.0, 22.0, 24.0, 25.0, 26.0, 28.0, 30.0,
                 32.0, 35.0, 38.0, 40.0]
DOWELS = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 13.0, 16.0, 20.0, 25.0, 30.0]


def fraction(text):
    text = text.strip('"').strip()
    whole = 0.0
    if " " in text:
        head, text = text.split(" ", 1)
        whole = float(head)
    if "/" in text:
        a, b = text.split("/")
        return whole + float(a) / float(b)
    return whole + float(text)


def _msize(d):
    return "M%g" % d


def _mnum(size):
    try:
        return float(size.split("x")[0].lstrip("M"))
    except ValueError:
        return None


def _inch_d(size):
    s = size.strip('"')
    return NUMBERED.get(s) or FRACTIONAL.get(s) or fraction(s)


# ------------------------------------------------------------------ what each kind lists
def _cbore_types(standard):
    if standard == "ANSI Inch":
        return [t[0] for t in INCH_CBORE]
    names = METRIC_TYPES.get(standard)
    return [names[t[0]] if names else t[0] for t in METRIC_CBORE if names is None or t[0] in names]


def _csk_types(standard):
    if standard == "ANSI Inch":
        return [t[0] for t in INCH_CSK]
    names = METRIC_TYPES.get(standard)
    return [names[t[0]] if names else t[0] for t in METRIC_CSK if names is None or t[0] in names]


def types(kind, standard):
    inch = standard == "ANSI Inch"
    if kind == "Counterbore":
        return _cbore_types(standard)
    if kind == "Countersink":
        return _csk_types(standard)
    if kind == "Hole":
        return (["Fractional Drill Sizes", "Letter Drill Sizes", "Number Drill Sizes", "Screw Clearances",
                 "Tap Drills", "Dowel Holes"] if inch else
                ["Drill sizes", "Screw Clearances", "Tap Drills", "Dowel Holes"])
    if kind == "Straight Tap":
        return (["Tapped hole UNC", "Tapped hole UNF", "Tapped hole UNEF", "Bottoming Tapped Hole"] if inch else
                ["Tapped hole", "Bottoming Tapped Hole", "Fine Tapped hole"])
    if kind == "Tapered Tap":
        return ["Tapered Pipe Tap (NPT)"] if inch else ["Tapered Pipe Tap (BSPT)"]
    return []


def _entry(kind, standard, type_name):
    """(table type tuple) for a counterbore / countersink type name of a standard."""
    if standard == "ANSI Inch":
        rows = INCH_CBORE if kind == "Counterbore" else INCH_CSK
        return next((t for t in rows if t[0] == type_name), None)
    rows = METRIC_CBORE if kind == "Counterbore" else METRIC_CSK
    names = METRIC_TYPES.get(standard) or {}
    for t in rows:
        if t[0] == type_name or names.get(t[0]) == type_name:
            return t
    return None


def tree_word(kind, standard, type_name):
    e = _entry(kind, standard, type_name)
    return e[1] if e else "Screw"


def sizes(kind, standard, type_name):
    inch = standard == "ANSI Inch"
    if kind in ("Counterbore", "Countersink"):
        e = _entry(kind, standard, type_name)
        if e is None:
            return []
        table = e[2]
        if inch:
            keys = list(INCH_HEX_FLATS) if e[3] == "hex" else list(table)
            return keys
        keys = list(HEX_FLATS) if e[3] == "hex" else list(table)
        return [_msize(d) for d in sorted(keys) if d in CLEAR]
    if kind == "Hole":
        if inch:
            if type_name == "Fractional Drill Sizes":
                return ['%s"' % s for s in FRACTION_DRILLS]
            if type_name == "Letter Drill Sizes":
                return list(LETTER_DRILLS)
            if type_name == "Number Drill Sizes":
                return list(NUMBER_DRILLS)
            if type_name == "Dowel Holes":
                return ['%s"' % s for s in ("1/16", "3/32", "1/8", "3/16", "1/4", "5/16", "3/8", "1/2", "5/8", "3/4", "1")]
            return list(INCH_SIZES)
        if type_name == "Drill sizes":
            return ["Ø%.1f" % v for v in METRIC_DRILLS]
        if type_name == "Dowel Holes":
            return ["Ø%.1f" % v for v in DOWELS]
        if type_name == "Tap Drills":
            return [_msize(d) for d in sorted(COARSE)] + ["M%gx%g" % fp for fp in FINE]
        return [_msize(d) for d in sorted(CLEAR)]
    if kind == "Straight Tap":
        if inch:
            table = UNF if type_name.endswith("UNF") else UNEF if type_name.endswith("UNEF") else UNC
            return list(table)
        if type_name == "Fine Tapped hole":
            return ["M%gx%g" % fp for fp in FINE]
        return [_msize(d) for d in sorted(COARSE)]
    if kind == "Tapered Tap":
        return list(NPT if inch else BSPT)
    return []


# ------------------------------------------------------------------ the numbers
def thread(kind, standard, type_name, size):
    """(major diameter mm, pitch mm, callout name) of a tapped size."""
    if standard == "ANSI Inch":
        s = size.strip('"')
        if kind == "Tapered Tap":
            tpi, _drill = NPT[s]
            return PIPE_OD[s] * INCH, INCH / tpi, '%s-%g NPT' % (s, tpi)
        series = "UNF" if type_name.endswith("UNF") else "UNEF" if type_name.endswith("UNEF") else "UNC"
        tpi = {"UNC": UNC, "UNF": UNF, "UNEF": UNEF}[series].get(s) or UNC.get(s) or UNF.get(s, 20)
        return _inch_d(s) * INCH, INCH / tpi, "%s-%g %s" % (s, tpi, series)       # 4.5 TPI: "2-4.5 UNC"
    if kind == "Tapered Tap":
        s = size.strip('"')
        tpi, _drill = BSPT[s]
        return BSP_MAJOR.get(s) or PIPE_OD[s] * INCH, INCH / tpi, "Rc %s" % s
    d = _mnum(size)
    if "x" in size:
        p = float(size.split("x")[1])
    else:
        p = COARSE.get(d, d * 0.15)
    return d, p, "M%gx%g" % (d, p)


# extapps132: the published tap drill charts (Machinery's Handbook, 75 % thread): ISO metric coarse in mm, UNC / UNF in inches
# (the drill that is listed, as a decimal). d - pitch is only the fallback for sizes not listed.
METRIC_TAP = {1.6: 1.25, 2.0: 1.6, 2.5: 2.05, 3.0: 2.5, 3.5: 2.9, 4.0: 3.3, 5.0: 4.2, 6.0: 5.0, 8.0: 6.8, 10.0: 8.5,
              12.0: 10.2, 14.0: 12.0, 16.0: 14.0, 20.0: 17.5, 24.0: 21.0}
INCH_TAP = {"UNC": {"#2": .0700, "#4": .0890, "#6": .1065, "#8": .1360, "#10": .1495, "1/4": .2010, "5/16": .2570,
                    "3/8": .3125, "7/16": .3680, "1/2": .4219, "9/16": .4844, "5/8": .5312, "3/4": .6562, "7/8": .7656,
                    "1": .8750},
            "UNF": {"#4": .0935, "#6": .1130, "#8": .1360, "#10": .1590, "1/4": .2130, "5/16": .2720, "3/8": .3320,
                    "7/16": .3906, "1/2": .4531, "9/16": .5156, "5/8": .5781, "3/4": .6875, "7/8": .8125, "1": .9219}}


def tap_drill(kind, standard, type_name, size):
    if kind == "Tapered Tap":
        table = NPT if standard == "ANSI Inch" else BSPT
        return table[size.strip('"')][1]
    d, p, _n = thread(kind, standard, type_name, size)
    if standard == "ANSI Inch":
        series = "UNF" if type_name.endswith("UNF") else "UNEF" if type_name.endswith("UNEF") else "UNC"
        listed = INCH_TAP.get(series, {}).get(size.strip('"'))
        if listed:
            return round(listed * INCH, 2)
    elif "x" not in size and _mnum(size) in METRIC_TAP:
        return METRIC_TAP[_mnum(size)]
    return round(d - p, 2)


def _fit(fit):
    return FITS.index(fit) if fit in FITS else 1



# read keep the formula below
SW_INCH_CLEARANCE = {"1/4": (0.2570, 0.2660, 0.2812), "5/16": (0.3230, 0.3320, 0.3437),
                     "3/8": (0.3860, 0.3970, 0.4062), "1/2": (0.5156, 0.5312, 0.5469)}


def clearance(standard, size, fit="Normal"):
    if standard == "ANSI Inch":
        d = _inch_d(size)
        k = _fit(fit)
        read = SW_INCH_CLEARANCE.get(str(size).strip('"').split("-")[0])
        if read:
            return round(read[k] * INCH, 3)
        if k == 1:      # extapps98: Normal fit is ASME B18.2.8's table, the same as the Toolbox (1/4 is .266, not .275)
            try:
                from . import toolbox
                key = next((x for x in toolbox._INCH if x.split("-")[0] == str(size).strip('"')), None)
                if key:
                    return round(toolbox.SIZES[key][2], 3)
            except Exception:
                pass
        return round((d * (1.04, 1.06, 1.10)[k] + (0.004, 0.010, 0.020)[k]) * INCH, 3)
    return CLEAR.get(_mnum(size), (0, _mnum(size) * 1.1, 0))[_fit(fit)]


def dims(kind, standard, type_name, size, fit="Normal"):
    """{"hole", "head_d", "head_depth", "head_angle", "tap_drill", "major", "pitch", "name"} in mm."""
    inch = standard == "ANSI Inch"
    k = _fit(fit)
    out = {"hole": 0.0, "head_d": 0.0, "head_depth": 0.0, "head_angle": 90.0}
    if kind in ("Counterbore", "Countersink"):
        e = _entry(kind, standard, type_name)
        out["hole"] = clearance(standard, size, fit)
        how = e[3] if e else "cbore"
        if inch:
            s = size.strip('"')
            d = _inch_d(s)
            if how == "hex":
                flats, height = INCH_HEX_FLATS.get(s, d * 1.5), INCH_HEX_HEIGHT.get(s, d * 0.7)
                head, h = flats * 1.155, height
            elif how.startswith("csk"):
                head, h = e[2].get(s, d * 2.0), 0.0
                out["head_angle"] = 100.0 if how == "csk100" else 82.0
            else:
                head, h = e[2].get(s, (d * 1.5, d))
            out["head_d"] = round(head * INCH + CBORE_ALLOW[k] * (1 if d < .5 else 2), 3)
            out["head_depth"] = round(h * INCH + DEPTH_ALLOW[k], 3) if h else 0.0
            return out
        d = _mnum(size)
        if how == "hex":
            flats = HEX_FLATS[d]
            if standard == "DIN":       # extapps98: DIN 931 / 933 have their own across flats (M10 17, M12 19), as the Toolbox bolts
                try:
                    from . import toolbox
                    flats = toolbox.DIN_HEX.get(_msize(d), (flats,))[0]
                except Exception:
                    pass
            head, h = flats * 1.155 + 0.25 * d, HEX_HEIGHT[d]
        elif how == "csk":
            head, h = e[2][d], 0.0
        else:
            head, h = e[2][d]
        scale = 1 if d <= 10 else 2
        out["head_d"] = round(head + CBORE_ALLOW[k] * scale, 2)
        out["head_depth"] = round(h + DEPTH_ALLOW[k] * scale, 2) if h else 0.0
        return out
    if kind == "Hole":
        if inch:
            s = size.strip('"')
            if type_name == "Letter Drill Sizes":
                out["hole"] = LETTER_DRILLS[s] * INCH
            elif type_name == "Number Drill Sizes":
                out["hole"] = NUMBER_DRILLS[s] * INCH
            elif type_name == "Screw Clearances":
                out["hole"] = clearance(standard, s, fit)
            elif type_name == "Tap Drills":
                out["hole"] = tap_drill("Straight Tap", standard, "Tapped hole UNC", s)
            else:
                out["hole"] = fraction(s) * INCH
        elif type_name == "Screw Clearances":
            out["hole"] = clearance(standard, size, fit)
        elif type_name == "Tap Drills":
            out["hole"] = tap_drill("Straight Tap", standard, "Tapped hole", size)
        else:
            out["hole"] = float(size.lstrip("Ø"))
        out["hole"] = round(out["hole"], 3)
        return out
    major, pitch, name = thread(kind, standard, type_name, size)
    out.update(hole=tap_drill(kind, standard, type_name, size), tap_drill=tap_drill(kind, standard, type_name, size),
               major=round(major, 3), pitch=round(pitch, 4), name=name)
    return out


def callout(kind, standard, type_name, size, d, through, depth, tdepth=0.0, ends=None):
    ""
    dia = "⌀"
    deep = "↧"
    cb = "⌴"
    cs = "⌵"
    tail = " THRU ALL" if through else " %s %.2f" % (deep, depth)
    if kind == "Counterbore":
        return ["%s%.2f%s" % (dia, d["hole"], tail), "%s %s%.2f %s %.2f" % (cb, dia, d["head_d"], deep, d["head_depth"])]
    if kind == "Countersink":
        return ["%s%.2f%s" % (dia, d["hole"], tail), "%s %s%.2f X %g°" % (cs, dia, d["head_d"], d["head_angle"])]
    if kind in ("Straight Tap", "Tapered Tap"):
        cls = "2B" if standard == "ANSI Inch" else "6H"
        lines = ["%s%.2f%s" % (dia, d["tap_drill"], tail)]
        thr = d["name"] + ("" if kind == "Tapered Tap" else " - " + cls)
        lines.append(thr + (" THRU ALL" if through else " %s %.2f" % (deep, tdepth or depth)))
        return lines
    return ["%s%.2f%s" % (dia, d["hole"], tail)]



# Helicoil (free-running insert) tap drills, mm
HELICOIL = {2: 2.1, 2.5: 2.65, 3: 3.2, 4: 4.2, 5: 5.2, 6: 6.3, 8: 8.4, 10: 10.5, 12: 12.5, 14: 14.5, 16: 16.5,
            20: 20.75, 24: 25.0}
# PEM self-clinching fasteners: mounting hole diameters (inch sizes in inches, metric in mm)
PEM_TYPES = ("Self-Clinching Nuts", "Self-Clinching Studs", "Self-Clinching Standoffs")
PEM_INCH = {"Self-Clinching Nuts": {"#2-56": .166, "#4-40": .166, "#6-32": .188, "#8-32": .213, "#10-24": .250,
                                    "#10-32": .250, "1/4-20": .344, "5/16-18": .413, "3/8-16": .500},
            "Self-Clinching Studs": {"#4-40": .112, "#6-32": .138, "#8-32": .164, "#10-24": .190, "#10-32": .190,
                                     "1/4-20": .250, "5/16-18": .312, "3/8-16": .375},
            "Self-Clinching Standoffs": {"#4-40": .213, "#6-32": .213, "#8-32": .250, "#10-32": .281,
                                         "1/4-20": .344}}
PEM_METRIC = {"Self-Clinching Nuts": {2.5: 4.22, 3: 4.22, 3.5: 4.75, 4: 5.41, 5: 6.35, 6: 8.75, 8: 10.5},
              "Self-Clinching Studs": {2.5: 2.5, 3: 3.0, 3.5: 3.5, 4: 4.0, 5: 5.0, 6: 6.0, 8: 8.0},
              "Self-Clinching Standoffs": {2.5: 4.22, 3: 4.22, 3.5: 5.41, 4: 7.14, 5: 7.14}}

_types, _sizes, _dims, _thread, _tap_drill, _clearance, _callout, _tree_word = \
    types, sizes, dims, thread, tap_drill, clearance, callout, tree_word


def _pem(kind, standard, type_name):
    return kind == "Hole" and standard in ("PEM Inch", "PEM Metric") and type_name in PEM_TYPES


def types(kind, standard):
    if kind == "Hole" and standard in ("PEM Inch", "PEM Metric"):
        return list(PEM_TYPES)
    out = _types(kind, BASE.get(standard, standard))
    if kind == "Hole" and not is_inch(standard):
        out = out + ["Helicoil Tap Drills"]
    return out


def sizes(kind, standard, type_name):
    if _pem(kind, standard, type_name):
        table = (PEM_INCH if standard == "PEM Inch" else PEM_METRIC)[type_name]
        return list(table) if standard == "PEM Inch" else [_msize(d) for d in sorted(table)]
    if kind == "Hole" and type_name == "Helicoil Tap Drills":
        return [_msize(d) for d in sorted(HELICOIL)]
    return _sizes(kind, BASE.get(standard, standard), type_name)


def dims(kind, standard, type_name, size, fit="Normal"):
    if _pem(kind, standard, type_name):
        out = {"hole": 0.0, "head_d": 0.0, "head_depth": 0.0, "head_angle": 90.0}
        if standard == "PEM Inch":
            out["hole"] = round(PEM_INCH[type_name].get(size, .25) * INCH, 3)
        else:
            out["hole"] = PEM_METRIC[type_name].get(_mnum(size), _mnum(size))
        return out
    if kind == "Hole" and type_name == "Helicoil Tap Drills":
        d = _mnum(size)
        return {"hole": HELICOIL.get(d, round(d * 1.04, 2)), "head_d": 0.0, "head_depth": 0.0, "head_angle": 90.0}
    return _dims(kind, BASE.get(standard, standard), type_name, size, fit)


def thread(kind, standard, type_name, size):
    return _thread(kind, BASE.get(standard, standard), type_name, size)


def tap_drill(kind, standard, type_name, size):
    return _tap_drill(kind, BASE.get(standard, standard), type_name, size)


def clearance(standard, size, fit="Normal"):
    return _clearance(BASE.get(standard, standard), size, fit)


def callout(kind, standard, type_name, size, d, through, depth, tdepth=0.0, ends=None):
    return _callout(kind, BASE.get(standard, standard), type_name, size, d, through, depth, tdepth, ends)


def tree_word(kind, standard, type_name):
    if _pem(kind, standard, type_name):
        return "PEM " + type_name.replace("Self-Clinching ", "").rstrip("s")
    return _tree_word(kind, BASE.get(standard, standard), type_name)
