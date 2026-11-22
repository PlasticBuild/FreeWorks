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
import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import drawings as D
from . import drawpmparts as P
from . import drawlive as DL

TOLERANCES = ("None", "Basic", "Bilateral", "Limit", "Symmetric", "MIN", "MAX", "Fit", "Fit with tolerance",
              "Fit (tolerance only)")
FITS = ("Fit", "Fit with tolerance", "Fit (tolerance only)")
UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}
DUAL_PLACES = ("To right", "Below")

# ISO 286: size steps (mm, upper bound), IT grades and fundamental deviations (micrometres)
STEPS = (3, 6, 10, 18, 30, 50, 80, 120, 180, 250, 315, 400, 500)
IT = {5: (4, 5, 6, 8, 9, 11, 13, 15, 18, 20, 23, 25, 27),
      6: (6, 8, 9, 11, 13, 16, 19, 22, 25, 29, 32, 36, 40),
      7: (10, 12, 15, 18, 21, 25, 30, 35, 40, 46, 52, 57, 63),
      8: (14, 18, 22, 27, 33, 39, 46, 54, 63, 72, 81, 89, 97),
      9: (25, 30, 36, 43, 52, 62, 74, 87, 100, 115, 130, 140, 155),
      10: (40, 48, 58, 70, 84, 100, 120, 140, 160, 185, 210, 230, 250),
      11: (60, 75, 90, 110, 130, 160, 190, 220, 250, 290, 320, 360, 400)}
SHAFT_ES = {"d": (-20, -30, -40, -50, -65, -80, -100, -120, -145, -170, -190, -210, -230),
            "e": (-14, -20, -25, -32, -40, -50, -60, -72, -85, -100, -110, -125, -135),
            "f": (-6, -10, -13, -16, -20, -25, -30, -36, -43, -50, -56, -62, -68),
            "g": (-2, -4, -5, -6, -7, -9, -10, -12, -14, -15, -17, -18, -20),
            "h": (0,) * 13}
SHAFT_EI = {"k": (0, 1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4, 5),
            "m": (2, 4, 6, 7, 8, 9, 11, 13, 15, 17, 20, 21, 23),
            "n": (4, 8, 10, 12, 15, 17, 20, 23, 27, 31, 34, 37, 40),
            "p": (6, 12, 15, 18, 22, 26, 32, 37, 43, 50, 56, 62, 68),
            "r": (10, 15, 19, 23, 28, 34, 41, 51, 63, 77, 94, 108, 126),
            "s": (14, 19, 23, 28, 35, 43, 53, 71, 92, 122, 158, 190, 232)}
HOLE_FITS = ["", "D9", "D10", "E8", "E9", "F7", "F8", "G6", "G7", "H6", "H7", "H8", "H9", "H10", "H11", "JS6", "JS7",
             "K6", "K7", "N6", "N7", "P6", "P7"]
SHAFT_FITS = ["", "d9", "e8", "f7", "g6", "h6", "h7", "h8", "h9", "h11", "js6", "k6", "m6", "n6", "p6", "r6", "s6"]
CLASSES = {"User Defined": None,
           "Clearance": ("H11/d10", "H9/d9", "H8/f7", "H7/g6", "H7/h6"),
           "Transitional": ("H7/k6", "H7/n6"),
           "Press": ("H7/p6", "H7/r6", "H7/s6")}
PRECISIONS = ("None", ".1", ".12", ".123", ".1234", ".12345", ".123456", ".1234567", ".12345678")
DOC_SUFFIX = " (Document)"
SAME_AS_NOMINAL = "Same as nominal"
SYMBOLS = (("⌀", "Diameter"), ("°", "Degree"), ("±", "Plus/Minus"), ("□", "Square"),
           ("⌴", "Counterbore"), ("⌵", "Countersink"), ("↧", "Depth"), ("℄", "Centerline"))
THICKNESS = ("Use document", "0.18mm", "0.25mm", "0.35mm", "0.5mm", "0.7mm", "1mm")
DIM = "<DIM>"


def _step(size):
    for i, top in enumerate(STEPS):
        if size <= top:
            return i
    return len(STEPS) - 1


def fit_deviations(size, fit):
    """(upper, lower) deviations in mm of an ISO 286 class such as "H7" (a hole) or "g6" (a shaft)."""
    m = re.match(r"^(JS|js|[A-Za-z])(\d+)$", fit or "")
    if not m:
        return None
    letter, grade = m.group(1), int(m.group(2))
    if grade not in IT:
        return None
    i = _step(abs(size))
    it = IT[grade][i]
    lo = letter.lower()
    if lo == "js":
        up, dn = it / 2.0, -it / 2.0
    elif lo in SHAFT_ES:
        es = SHAFT_ES[lo][i]
        up, dn = es, es - it
    elif lo in SHAFT_EI:
        ei = SHAFT_EI[lo][i] if not (lo == "k" and grade > 7) else 0
        up, dn = ei + it, ei
    else:
        return None
    if letter[0].isupper():
        # a hole: the shaft deviation mirrored (EI = -es, ES = -ei); K, N, P (grade 8 and finer) add delta
        up, dn = -dn, -up
        if lo in ("k", "n", "p") and grade <= 8 and grade - 1 in IT:
            delta = it - IT[grade - 1][i]
            ES = -SHAFT_EI[lo][i] + delta
            up, dn = ES, ES - it
    return up / 1000.0, dn / 1000.0


FIT_DISPLAYS = ("Linear", "Stacked", "Stacked without line")
FIT_STACKED = ("Stacked", "Stacked without line")


def fit_text(hole, shaft):
    return "/".join(x for x in (hole, shaft) if x)


def _digits(text):
    text = str(text or "")
    if text.endswith(DOC_SUFFIX):
        text = text[:-len(DOC_SUFFIX)]
    if text == "None" or not text.startswith("."):
        return 0 if text == "None" else 2
    return len(text) - 1


def doc_precision(doc, which="unit"):
    """Document Properties > Dimensions > Primary precision: the unit precision (which "unit") or the tolerance
    precision (which "tol"; .12 when the document has no such row), as a precision item."""
    try:
        from . import drawdocprops
        if which == "unit":
            v = str(drawdocprops.prop(doc, "dim_precision") or ".12")
        else:
            if doc_tol_nominal(doc):
                return doc_precision(doc, "unit")
            v = str(drawdocprops.row(doc, "Dimensions", "Tolerance precision", ".12") or ".12")
    except Exception:
        v = ".12"
    return v if v in PRECISIONS else ".12"


def doc_tol_nominal(doc):
    ""
    try:
        from . import drawdocprops
        v = str(drawdocprops.row(doc, "Dimensions", "Tolerance precision", SAME_AS_NOMINAL) or SAME_AS_NOMINAL)
    except Exception:
        return True
    return v not in PRECISIONS


def doc_label(doc, which="unit"):
    """The precision list's Document item, e.g. ".12 (Document)", or "Same as nominal (Document)" for the
    tolerance when the document's tolerance precision is Same as nominal."""
    if which == "tol" and doc_tol_nominal(doc):
        return SAME_AS_NOMINAL + DOC_SUFFIX
    return doc_precision(doc, which) + DOC_SUFFIX


def _resolve_precisions(doc, precision, tol_precision, kept):
    """The Unit and Tolerance precision items as numbers, with how they were chosen: the Document item (follows
    Document Properties), Same as nominal (the tolerance as the unit precision) or a number."""
    prec_doc = str(precision).endswith(DOC_SUFFIX) or bool(kept.get("prec_doc"))
    if prec_doc:
        precision = doc_precision(doc, "unit")
    tp = str(tol_precision)
    mode = "doc" if tp.endswith(DOC_SUFFIX) else "nominal" if tp == SAME_AS_NOMINAL else ""
    if not mode and kept.get("tol_prec") in ("doc", "nominal") and tp == kept.get("tol_prec_was", tp):
        mode = kept.get("tol_prec")
    if mode == "doc":
        tol_precision = precision if doc_tol_nominal(doc) else doc_precision(doc, "tol")
    elif mode == "nominal":
        tol_precision = precision
    return precision, tol_precision, prec_doc, mode


def follow_document_precision(dim):
    """A dimension whose precision is the Document item is written again when Document Properties change it.
    Returns True when it was."""
    o = options_of(dim)
    if o and o.get("tz") != [trailing_zeroes(dim, "dimensions"), trailing_zeroes(dim, "tolerances")]:
        apply(dim, from_doc=getattr(dim, "SWDocDefaults", "") == "1", **o)    # Trailing zeroes changed
        return True
    if not o or not (o.get("prec_doc") or o.get("tol_prec") == "doc"):
        return False
    want_p = doc_precision(dim.Document, "unit") if o.get("prec_doc") else o.get("precision")
    want_t = (want_p if doc_tol_nominal(dim.Document) else doc_precision(dim.Document, "tol")) \
        if o.get("tol_prec") == "doc" else \
        (want_p if o.get("tol_prec") == "nominal" else o.get("tol_precision"))
    if want_p == o.get("precision") and want_t == o.get("tol_precision"):
        return False
    apply(dim, **o)
    return True


def _sprop(o, name, value, doc="Dimension PM"):
    if name not in o.PropertiesList:
        o.addProperty("App::PropertyString", name, "FreeCAD", doc)
    if getattr(o, name) != value:
        setattr(o, name, value)


def tolerance_of(dim):
    t = getattr(dim, "SWTolerance", "")
    if t in TOLERANCES:
        return t
    if getattr(dim, "TheoreticalExact", False):
        return "Basic"
    over, under = float(dim.OverTolerance), float(dim.UnderTolerance)
    if abs(over) < 1e-12 and abs(under) < 1e-12:
        return "None"
    return "Symmetric" if dim.EqualTolerance else "Bilateral"


def model_precision():
    """The model's precision as a Unit precision item: FreeCAD's Units decimals (2 unless changed)."""
    try:
        n = App.ParamGet("User parameter:BaseApp/Preferences/Units").GetInt("Decimals", 2)
    except Exception:
        n = 2
    n = max(0, min(int(n), 6))
    return "None" if n == 0 else "." + "123456"[:n]


def precision_of(spec, default=".12"):
    m = re.search(r"%\.(\d+)[wf]", spec or "")
    if not m:
        return default
    n = int(m.group(1))
    return "None" if n == 0 else "." + "12345678"[:n]


def text_of(dim):
    t = getattr(dim, "SWDimText", "")
    if t:
        return t
    spec = dim.FormatSpec or "%.2w"
    if getattr(dim, "Arbitrary", False):
        return DIM
    return re.sub(r"%[-+ #0]*\d*(\.\d+)?[wfgGeE]", DIM, spec, count=1)


ARC_CONDITIONS = ("Center", "Min", "Max")


def arc_radii(dim):
    """[r1, r2]: the radius of the circle each reference of a distance is the centre of (or the circle itself),
    None where it is not a circle; [] when neither is."""
    try:
        from . import drawannot as DA
        view = dim.References2D[0][0]
        subs = list(dim.References2D[0][1])
        circ = DA.circles(view)
        verts = dict(DA.vertices(view))
    except Exception:
        return []
    out = []
    for sub in subs[:2]:
        r = None
        if sub.startswith("Edge"):
            r = next((c[2] for c in circ if "Edge%d" % c[0] == sub), None)
        elif sub.startswith("Vertex"):
            q = verts.get(int(sub[6:]))
            if q is not None:
                r = next((c[2] for c in circ if abs(c[1].x - q.x) < 1e-4 and abs(c[1].y - q.y) < 1e-4), None)
        out.append(r)
    while len(out) < 2:
        out.append(None)
    return out if any(x is not None for x in out) else []


def arc_value(dim, conds):
    ""
    v = value_of(dim)
    try:
        subs = list(dim.References2D[0][1])
    except Exception:
        subs = []
    radii = arc_radii(dim) or [None, None]
    for r, sub in zip(radii, subs):
        if r is not None and sub.startswith("Edge"):
            v += r                               # TechDraw measures a circle edge from its near side: to the centre
    for r, c in zip(radii, conds):
        if r is not None and c == "Min":
            v -= r
        elif r is not None and c == "Max":
            v += r
    return v


def set_arc_condition(dim, conds):
    _sprop(dim, "SWArcCondition", "|".join(conds), "Arc condition (first|second)")
    edges = any(str(x).startswith("Edge") for x in list(dim.References2D[0][1])) if dim.References2D else False
    if all(c == "Center" for c in conds) and not edges:
        if getattr(dim, "SWArcText", ""):
            dim.FormatSpec = dim.SWArcText       # numeric format first, then Arbitrary off (no TechDraw warning)
            dim.Arbitrary = False
            _sprop(dim, "SWArcText", "", "")
        return
    if not getattr(dim, "SWArcText", ""):
        _sprop(dim, "SWArcText", dim.FormatSpec or "%.2w", "FormatSpec before the arc condition")
    n = _digits((getattr(dim, "SWPrecision", "") or ".12|.12").split("|")[0])
    dim.Arbitrary = True
    dim.FormatSpec = _fmt(arc_value(dim, conds) * 1.0, n)


def value_of(dim):
    try:
        return float(dim.getRawValue())
    except Exception as _fw_err:
        _fw_log("drawdimpm.py:243", _fw_err)
        return 0.0


def options_of(dim):
    try:
        return json.loads(getattr(dim, "SWDimOptions", "") or "{}")
    except ValueError:
        return {}


def _dual_tol_precision(dim, dual_precision):
    """Document Properties > Dimensions > Dual tolerance precision: Same as nominal = the dual precision."""
    try:
        from . import drawdocprops
        tp = drawdocprops.row(dim.Document, "Dimensions", "Dual tolerance precision", "Same as nominal")
    except Exception:
        tp = "Same as nominal"
    return _digits(dual_precision if tp == "Same as nominal" else tp)


def _fmt(v, n):
    return ("%." + str(n) + "f") % v


def trailing_zeroes(dim, what="dimensions"):
    ""


    try:
        from . import drawdocprops as DD
        mode = str(DD.row(dim.Document, "Dimensions", "Trailing zeroes, " + what, "Smart"))
        if mode in ("Smart", "Standard") and dim.Type not in ("Angle", "Angle3Pt") and DD.units(dim.Document) == "in":
            mode = "Show"
    except Exception as _fw_err:
        _fw_log("drawdimpm.py:trailing", _fw_err)
        mode = "Smart"
    return mode if mode in ("Smart", "Show", "Remove", "Standard") else "Smart"


def _whole(value, n):
    return abs(value - round(value)) < 0.5 * 10 ** -n


def _spec(value, n, mode, sign=""):
    """TechDraw's number format for value (in the document's unit) at n places with the Trailing zeroes mode:
    %w drops the zeroes, %f keeps them."""
    trim = mode == "Remove" or (mode in ("Smart", "Standard") and _whole(value, n))
    return "%%%s.%d%s" % (sign, n, "w" if trim else "f")


def _tol_text(value, n, mode, nolead=False, sign=True):
    """A tolerance's text, worked out here: TechDraw's own format writes a value under 0.1 mm in the unit
    schema's smaller unit (-0.05 mm came out as -50, micrometres), so the tolerances are kept as text."""
    if abs(value) < 0.5 * 10 ** -n:
        return "0"
    text = _ztext(_fmt(abs(value), n), mode)
    if nolead:
        text = _nolead(text)
    return (("+" if value > 0 else "-") if sign else "") + text


def _ztext(text, mode):
    """A worked-out number's text with the Trailing zeroes mode (as _spec, for the frozen texts)."""
    if "." not in text or mode == "Show":
        return text
    bare = text.rstrip("0").rstrip(".")
    if mode == "Remove" or "." not in bare:
        return bare
    return text


def _doc_len(dim, v):
    """A length (mm) in the document's length unit, for the numbers worked out here (TechDraw's own %w
    format already writes it so): 50.8 -> 2.0 in an IPS document. Angles are left as they are."""
    if dim.Type in ("Angle", "Angle3Pt"):
        return v
    try:
        from . import unitspage
        return v / unitspage.length_unit(dim.Document)[1]
    except Exception:
        return v


def leading_zero(dim):
    """Document Properties > Dimensions > Zeroes > Leading zeroes: "Show" (0.5) or "Remove" (.5). Standard is
    the drafting standard's way: inch drawings (ANSI) remove it, millimetre ones show it; Fractional display >
    Include leading zero for values less than 1" keeps it on an inch drawing."""
    doc = dim.Document
    try:
        from . import drawdocprops as DD
        mode = DD.row(doc, "Dimensions", "Leading zeroes", "Standard")
        if mode == "Standard":
            # inch drawings drop it (ANSI) unless Fractional display > Include leading zero for values less

            inch = DD.prop(doc, "units") == "in"
            keep = DD.row(doc, "Dimensions", "Include leading zero for values less than 1\"", False)
            mode = "Remove" if inch and not keep else "Show"
        return mode
    except Exception as _fw_err:
        _fw_log("drawdimpm.py:284", _fw_err)
        return "Show"


def _nolead(text):
    """0.5 -> .5 and -0.5 -> -.5 (Leading zeroes: Remove)."""
    if text.startswith("0."):
        return text[1:]
    if text.startswith("-0."):
        return "-" + text[2:]
    return text


def apply(dim, tol="None", plus=0.0, minus=0.0, precision=".12", tol_precision=".12", text=DIM, parens=False,
          override=None, hole_fit="", shaft_fit="", dual=False, dual_unit="in", dual_place="To right",
          dual_precision=".123", units="Document", inspection=False, from_doc=False, tol_parens=False,
          fit_display="Linear", **_kept):
    """Writes the Value tab (and Override Units) onto a TechDraw dimension: its FormatSpec, tolerances and
    Arbitrary text; the options are kept on the dimension (SWDimOptions) so refresh_dimensions can write them
    again."""
    precision, tol_precision, prec_doc, tol_mode = _resolve_precisions(dim.Document, precision, tol_precision, _kept)
    opts = dict(tol=tol, plus=plus, minus=minus, precision=precision, tol_precision=tol_precision, text=text or DIM,
                parens=parens, override=override, hole_fit=hole_fit, shaft_fit=shaft_fit, dual=dual,
                dual_unit=dual_unit, dual_place=dual_place, dual_precision=dual_precision, units=units,
                inspection=inspection, tol_parens=bool(tol_parens))
    if fit_display != "Linear":
        opts["fit_display"] = fit_display
    if prec_doc:
        opts["prec_doc"] = True
    if tol_mode:
        opts["tol_prec"] = tol_mode
        opts["tol_prec_was"] = tol_precision     # a number typed over it later (the palette) ends the mode
    angle = dim.Type in ("Angle", "Angle3Pt")
    nolead = not angle and leading_zero(dim) == "Remove"
    if nolead:
        opts["lead"] = "Remove"        # refresh_dimensions writes it again when the model changes
    _sprop(dim, "SWDimOptions", json.dumps(opts, sort_keys=True), "Dimension PM options")
    _sprop(dim, "SWDocDefaults", "1" if from_doc else "0", "options from Document Properties")
    n, m = _digits(precision), _digits(tol_precision)
    tz, tzt = trailing_zeroes(dim, "dimensions"), trailing_zeroes(dim, "tolerances")
    opts["tz"] = [tz, tzt]                 # Document Properties > Zeroes as written (a change writes it again)
    _sprop(dim, "SWDimOptions", json.dumps(opts, sort_keys=True), "Dimension PM options")
    v = value_of(dim)
    token = _spec(_doc_len(dim, v), n, tz)
    frozen = False                     # True: the text holds worked-out numbers (Arbitrary)
    if units in UNITS and not angle:
        token = (_nolead if nolead else str)(_ztext(_fmt(v / UNITS[units], n), tz)) + units
        frozen = True
    elif nolead and abs(v) < 1.0:
        token = _nolead(_ztext(_fmt(_doc_len(dim, v), n), tz))     # TechDraw's own format always shows the 0
        frozen = True
    lines = (text or DIM).split("\n")
    k = next((i for i, ln in enumerate(lines) if DIM in ln), None)
    above, below = (lines[:k], lines[k + 1:]) if k is not None else ([], [])
    body = lines[k] if k is not None else (text or DIM)
    if tol == "MIN":
        body += " MIN"
    elif tol == "MAX":
        body += " MAX"
    fit = fit_text(hole_fit, shaft_fit) if tol in FITS else ""
    devs = None
    if tol in FITS:
        devs = fit_deviations(v, hole_fit) if hole_fit else fit_deviations(v, shaft_fit) if shaft_fit else None
        if tol in ("Fit", "Fit with tolerance") and fit:
            if hole_fit and shaft_fit and fit_display in FIT_STACKED:

                mark = "".join(ch + "\u0332" for ch in hole_fit) if fit_display == "Stacked" else hole_fit
                below = [" " * (len(body.replace(DIM, "00.00")) + 1) + shaft_fit] + below
                body += " " + mark
                frozen = True
            else:
                body += " " + fit
    if dual and not angle:
        k = UNITS.get(dual_unit, 25.4)
        dv = _fmt(v / k, _digits(dual_precision))
        if nolead:
            dv = _nolead(dv)
        if tol in ("Bilateral", "Symmetric"):
            tp = _dual_tol_precision(dim, dual_precision)        # Dual tolerance precision (Document Properties)
            dv += (" ±" + _fmt(abs(plus) / k, tp)) if tol == "Symmetric" else \
                (" %s/%s" % (("%+." + str(tp) + "f") % (plus / k), ("%+." + str(tp) + "f") % (minus / k)))
        dv += dual_unit
        body += ("\n[%s]" if dual_place == "Below" else " [%s]") % dv
        frozen = True
    if parens:
        body = "(%s)" % body
    body = "\n".join([ln for ln in above if ln.strip()] + [body] + [ln for ln in below if ln.strip()])
    _sprop(dim, "SWTolerance", tol, "tolerance type")
    _sprop(dim, "SWDimText", text or DIM, "dimension text around <DIM>")
    _sprop(dim, "SWOverride", "" if override is None else override, "override value")
    _sprop(dim, "SWPrecision", precision + "|" + tol_precision, "unit | tolerance precision")
    dim.TheoreticalExact = tol == "Basic"
    if tol != "Limit":
        _numeric_tolerances(dim, m)
    if tol == "Limit":

        lv = float(override) if override not in (None, "") and _number(override) else _doc_len(dim, v)
        dim.Arbitrary = True
        dim.FormatSpec = body.replace(DIM, "")
        dim.ArbitraryTolerances = True
        dim.EqualTolerance = False
        dim.OverTolerance, dim.UnderTolerance = plus, minus
        dim.FormatSpecOverTolerance = _ztext(_fmt(lv + _doc_len(dim, plus), n), tz)
        dim.FormatSpecUnderTolerance = _ztext(_fmt(lv + _doc_len(dim, minus), n), tz)
        return
    if tol in ("Fit with tolerance", "Fit (tolerance only)") and devs is not None:
        dim.EqualTolerance = abs(devs[0] + devs[1]) < 1e-12
        dim.OverTolerance, dim.UnderTolerance = devs[0], devs[1]
        dim.ArbitraryTolerances = True      # first, then the texts (TechDraw warns on a text without a format)
        dim.FormatSpecOverTolerance = _paren(_tol_text(_doc_len(dim, devs[0]), max(m, 3), tzt, nolead), tol_parens)
        dim.FormatSpecUnderTolerance = _paren(_tol_text(_doc_len(dim, devs[1]), max(m, 3), tzt, nolead), tol_parens)
    elif tol in ("Bilateral", "Symmetric"):
        dim.EqualTolerance = tol == "Symmetric"
        dim.OverTolerance = abs(plus) if tol == "Symmetric" else plus
        if tol == "Bilateral":
            dim.UnderTolerance = minus
        sym = tol == "Symmetric"
        dim.ArbitraryTolerances = True      # first, then the texts (TechDraw warns on a text without a format)
        over = _tol_text(_doc_len(dim, abs(plus) if sym else plus), m, tzt, nolead, not sym)
        dim.FormatSpecOverTolerance = _paren(over, tol_parens and not sym)
        dim.FormatSpecUnderTolerance = over if sym else _paren(_tol_text(_doc_len(dim, minus), m, tzt, nolead),
                                                               tol_parens)
    else:
        dim.EqualTolerance = True
        dim.OverTolerance = 0.0
    if override not in (None, ""):
        dim.Arbitrary = True
        dim.FormatSpec = body.replace(DIM, override)
    elif frozen:
        dim.Arbitrary = True
        dim.FormatSpec = body.replace(DIM, token if (units in UNITS or nolead) and "%" not in token else
                                      _ztext(_fmt(_doc_len(dim, v), n), tz))
    else:
        dim.FormatSpec = body.replace(DIM, token)    # the numeric format first: TechDraw warns on a plain text
        dim.Arbitrary = False                        # format the moment Arbitrary goes off ("no numeric format")
    inspection_frame(dim, inspection)
    try:
        from . import drawmaint          # Highlight overridden dimensions in a different color
        drawmaint.paint_overridden(dim)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: overridden colour: %s\n" % error)


def _numeric_tolerances(dim, m):
    """Tolerances back to TechDraw's own formatting: numeric formats first, then ArbitraryTolerances off (the other
    order makes TechDraw warn on the limit texts, and FreeCAD pops its corner notification)."""
    if getattr(dim, "ArbitraryTolerances", False):
        spec = "%%+.%dw" % max(m, 1)
        if "%" not in (dim.FormatSpecOverTolerance or ""):
            dim.FormatSpecOverTolerance = spec
        if "%" not in (dim.FormatSpecUnderTolerance or ""):
            dim.FormatSpecUnderTolerance = spec
    dim.ArbitraryTolerances = False


def _paren(spec, on):
    """Tolerance/Precision > Show parentheses: the tolerance values in brackets."""
    return "(%s)" % spec if on else spec


def shown_text(dim):
    """Roughly the text TechDraw shows for dim (its format with the value put in)."""
    spec = dim.FormatSpec or "%.2w"
    v = value_of(dim)
    return re.sub(r"%[-+ #0]*\d*\.?(\d*)[wfgGeE]",
                  lambda mm: _fmt(_doc_len(dim, v), int(mm.group(1) or 2)), spec, count=1)


def _page_of(o):
    for p in o.InListRecursive:
        if p.TypeId == "TechDraw::DrawPage":
            return p
    return None


def inspection_frame(dim, on):
    """Inspection dimension: an oval around the dimension's text (a symbol that follows the text on refresh)."""
    doc = dim.Document
    old = doc.getObject(getattr(dim, "SWInspectionFrame", "") or "")
    if not on:
        if old is not None:
            doc.removeObject(old.Name)
        _sprop(dim, "SWInspectionFrame", "", "inspection frame symbol")
        return None
    page = _page_of(dim)
    refs = dim.References2D or []
    if page is None or not refs:
        return None
    view = refs[0][0]
    try:
        size = float(getattr(dim.ViewObject.Fontsize, "Value", dim.ViewObject.Fontsize))
    except Exception:
        size = 3.5
    lines = shown_text(dim).split("\n")
    w = max(len(t) for t in lines) * size * 0.62 + size * 1.6
    h = size * (1.5 * len(lines)) + size * 0.4
    body = ('<rect x="%g" y="%g" width="%g" height="%g" rx="%g" ry="%g" fill="none" stroke="#000" '
            'stroke-width="0.25"/>' % (-w / 2, -h / 2, w, h, h / 2, h / 2))
    R = max(w, h) / 2 + 5
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="%g %g %g %g">%s</svg>'
           % (2 * R, 2 * R, -R, -R, 2 * R, 2 * R, body))
    s = old
    if s is None:
        s = doc.addObject("TechDraw::DrawViewSymbol", "InspectionFrame")
        page.addView(s)
        s.addProperty("App::PropertyString", "SWAnnotation", "FreeCAD", "Annotation kind")
        s.SWAnnotation = "InspectionFrame"
        s.addProperty("App::PropertyString", "SWFrameOf", "FreeCAD", "the dimension it frames")
        s.SWFrameOf = dim.Name
    s.Symbol = svg
    s.X = float(view.X) + float(dim.X)
    s.Y = float(view.Y) + float(dim.Y)
    _sprop(dim, "SWInspectionFrame", s.Name, "inspection frame symbol")
    return s


def refresh_dimensions(doc):
    """Writes again the dimensions whose text holds worked-out numbers (dual value, override units, fit limits)
    or an inspection frame, after the model changed (Update View, Rebuild). Returns how many."""
    n = 0
    for dim in doc.Objects:
        if dim.TypeId != "TechDraw::DrawViewDimension":
            continue
        o = options_of(dim)
        if o and getattr(dim, "SWLinkPrecision", "") == "1" and o.get("precision") != model_precision():
            o = dict(o, precision=model_precision())        # Link precisions with model: follow the model
            try:
                apply(dim, **o)
                n += 1
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: dimension refresh: %s\n" % error)
            continue
        if not o or not (o.get("dual") or o.get("units", "Document") in UNITS or o.get("tol") in FITS
                         or o.get("inspection") or o.get("lead") or set(o.get("tz") or ()) & {"Smart", "Standard"}):
            continue
        try:       # Trailing zeroes Smart follows the value (120 but 120.50); kept on the document's settings
            apply(dim, from_doc=getattr(dim, "SWDocDefaults", "") == "1", **o)
            n += 1
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: dimension refresh: %s\n" % error)
    return n


def _number(s):
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def _ref_points(dim):
    """The view points (scaled, about the view's centre) the dimension measures between."""
    out = []
    for v, sub in dim.References2D or []:
        subs = sub if isinstance(sub, (list, tuple)) else [sub]
        k = float(getattr(v, "Scale", 1.0) or 1.0)
        for s in subs:
            try:
                n = int(re.sub(r"\D", "", s))
                if s.startswith("Vertex"):
                    p = v.getVertexByIndex(n).Point
                    out.append(App.Vector(p.x * k, p.y * k, 0))
                elif s.startswith("Edge"):
                    e = v.getEdgeByIndex(n)
                    out += [App.Vector(x.Point.x * k, x.Point.y * k, 0) for x in e.Vertexes]
            except Exception as _fw_err:
                _fw_log("drawdimpm.py:536", _fw_err)
                continue
    return out


def center_text(dim):
    """Center dimension: the text halfway between the extension lines."""
    pts = _ref_points(dim)
    if len(pts) < 2:
        return False
    mid = (pts[0] + pts[-1]) * 0.5
    if dim.Type == "DistanceX":
        dim.X = mid.x
    elif dim.Type == "DistanceY":
        dim.Y = mid.y
    else:
        return False
    return True


# --------------------------------------------------------------------------- on the sheet
PARAM = "User parameter:BaseApp/Preferences/Mod/FreeWorks/DimensionPM"
DIM_ITEM = 65575          # TechDraw's QGIViewDimension item type
ARROW_ITEM = 65545        # its QGIArrow children (placed at the arrow tips)
LINES_ITEM = 65553        # its dimension and extension lines
DOT = 1.8


def _dim_item(dim):
    page = _page_of(dim)
    gv = D.page_view(page) if page is not None else None
    if gv is None:
        return None
    for it in gv.scene().items():
        try:
            if it.type() == DIM_ITEM and it.data(1) == dim.Name:
                return it
        except Exception as _fw_err:
            _fw_log("drawdimpm.py:574", _fw_err)
            continue
    return None


def arrow_tips(dim):
    """The sheet points (mm) of a dimension's arrow tips, as drawn now."""
    it = _dim_item(dim)
    if it is None:
        return []
    out = []
    for c in it.childItems():
        if c.type() == ARROW_ITEM and c.isVisible():
            p = c.scenePos()
            out.append((p.x() / D.REZ, -p.y() / D.REZ))
    return out


def flip_arrows(dim):
    """A click on the arrow dot: the arrows from inside to outside, or back."""
    out = not bool(dim.ViewObject.FlipArrowheads)
    dim.Document.openTransaction("Flip arrows")
    try:
        _sprop(dim, "SWArrows", "Outside" if out else "Inside", "arrows outside / inside / smart")
        dim.ViewObject.FlipArrowheads = out
    except BaseException:
        try:
            dim.Document.abortTransaction()
        except Exception:
            pass
        raise
    dim.Document.commitTransaction()
    dim.Document.recompute()
    if D.VIEW_PM and getattr(D.VIEW_PM[0], "dim", None) is dim:
        try:
            D.VIEW_PM[0].show_arrows()
        except Exception as _fw_err:
            _fw_log("drawdimpm.py:599", _fw_err)
    QtCore.QTimer.singleShot(150, lambda: extension_beyond(dim))
    return out


def arrow_press(page, p):
    """A press on the sheet: on an arrow tip of a picked dimension it flips the arrows (True: handled)."""
    try:
        picked = [o for o in Gui.Selection.getSelection() if is_dimension(o)]
    except Exception:
        return False
    for dim in picked:
        if _page_of(dim) is not page:
            continue
        for t in arrow_tips(dim):
            if (t[0] - p[0]) ** 2 + (t[1] - p[1]) ** 2 <= DOT * DOT:
                flip_arrows(dim)
                return True
    return False


def _beyond_of(dim):
    v = getattr(dim, "SWBeyond", "")
    if _number(v) and getattr(dim, "SWDocGap", "1") == "0":
        return float(v)
    try:
        from . import drawdocprops as DDP
        return float(DDP.prop(dim.Document, "dim_beyond") or 0.0)
    except Exception as _fw_err:
        _fw_log("drawdimpm.py:640", _fw_err)
        return 0.0


def extension_beyond(dim):
    """Extension lines run the asked length past the dimension line: TechDraw's own length is drawn longer by a
    line symbol (SWBeyondOf) or shortened under a paper-white one. 0 = TechDraw's standard length. Linear
    dimensions only; made again when the dimension is changed through the PM or Update View."""
    doc = dim.Document
    page = _page_of(dim)
    old = [o for o in (page.Views if page else []) if getattr(o, "SWBeyondOf", "") == dim.Name]
    want = _beyond_of(dim)
    if page is None or not want or dim.Type not in ("Distance", "DistanceX", "DistanceY"):
        for o in old:
            doc.removeObject(o.Name)
        return None
    it = _dim_item(dim)
    tips = arrow_tips(dim)
    refs = dim.References2D or []
    if it is None or len(tips) != 2 or not refs:
        return None
    view = refs[0][0]
    try:
        a, b = dim.getLinearPoints()
    except Exception as _fw_err:
        _fw_log("drawdimpm.py:665", _fw_err)
        return None
    vx, vy = float(view.X), float(view.Y)
    pts = [(vx + a.x, vy - a.y), (vx + b.x, vy - b.y)]
    try:
        lw = float(dim.ViewObject.LineWidth)
    except Exception:
        lw = 0.25
    lines = next((c for c in it.childItems() if c.type() == LINES_ITEM), None)
    br = lines.sceneBoundingRect() if lines is not None else None
    segs = []
    for m in pts:
        t = min(tips, key=lambda q: (q[0] - m[0]) ** 2 + (q[1] - m[1]) ** 2)
        ux, uy = t[0] - m[0], t[1] - m[1]
        L = (ux * ux + uy * uy) ** 0.5
        if L < 1e-6:
            continue
        ux, uy = ux / L, uy / L
        natural = 3.0
        if br is not None:
            # how far TechDraw's own lines reach past the arrow tip, along the extension line
            xs = (br.left() / D.REZ, br.right() / D.REZ)
            ys = (-br.bottom() / D.REZ, -br.top() / D.REZ)
            reach = max((x - t[0]) * ux + (y - t[1]) * uy for x in xs for y in ys)
            natural = max(0.0, reach - lw / 2)
        if abs(want - natural) < 0.05:
            continue
        s0, s1 = (natural, want) if want > natural else (want, natural)
        segs.append((t[0] + ux * s0, t[1] + uy * s0, t[0] + ux * s1, t[1] + uy * s1, want > natural))
    for o in old:
        doc.removeObject(o.Name)
    if not segs:
        return None
    cx = sum(q[0] + q[2] for q in segs) / (2 * len(segs))
    cy = sum(q[1] + q[3] for q in segs) / (2 * len(segs))
    body = ""
    for x0, y0, x1, y1, longer in segs:
        body += ('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="%s" stroke-width="%g" stroke-linecap="butt"/>'
                 % (x0 - cx, -(y0 - cy), x1 - cx, -(y1 - cy), "#000" if longer else "#fff",
                    lw if longer else lw * 2.2))
    R = max(max(abs(q[0] - cx), abs(q[2] - cx), abs(q[1] - cy), abs(q[3] - cy)) for q in segs) + 2
    s = doc.addObject("TechDraw::DrawViewSymbol", "ExtensionBeyond")
    page.addView(s)
    s.addProperty("App::PropertyString", "SWBeyondOf", "FreeCAD", "the dimension whose extension lines it sets")
    s.SWBeyondOf = dim.Name
    s.Symbol = ('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="%g %g %g %g">%s</svg>'
                % (2 * R, 2 * R, -R, -R, 2 * R, 2 * R, body))
    s.X, s.Y = cx, cy
    try:
        s.ViewObject.KeepLabel = False
    except Exception as _fw_err:
        _fw_log("drawdimpm.py:702", _fw_err)
    doc.recompute()
    return s


def refresh_beyond(doc):
    """Update View: the extension-beyond lines made again for the dimensions that have them."""
    for dim in [o for o in doc.Objects if is_dimension(o)]:
        if _beyond_of(dim) or any(getattr(o, "SWBeyondOf", "") == dim.Name for o in doc.Objects):
            try:
                extension_beyond(dim)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: extension lines: %s\n" % error)


class DimensionPanel:
    """The Dimension PM of a picked drawing dimension."""
    TITLE = "Dimension"

    def __init__(self, dim, others=()):
        self.view = dim                # D.VIEW_PM's PMs name what they edit .view
        self.dim = dim

        # every picked dimension, and the Primary Value (one dimension's own) is greyed
        self.others = [o for o in others if o is not dim and is_dimension(o)]
        self.made_all = [dim] + self.others
        self.doc = dim.Document
        self.made = list(self.made_all)
        self.started = False
        self.closing = False
        self._after = []
        self._style_skip = {"SWDimOverride", "SWDimOverrideValue"}
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("SWDimPM")
        self.form.setWindowTitle("Dimension")
        self.form.setProperty("swstyle_pm_title", "Dimension")
        self.form.setWindowIcon(QtGui.QIcon(":/icons/TechDraw_LengthDimension.svg"))
        outer = QtWidgets.QVBoxLayout(self.form)
        self.tabs = QtWidgets.QTabWidget(self.form)
        self.tabs.setObjectName("SWDimTabs")
        outer.addWidget(self.tabs)
        self.loading = True
        for name, fn in (("Value", self.value_tab), ("Leaders", self.leaders_tab), ("Other", self.other_tab)):
            page = QtWidgets.QWidget()
            page.setObjectName("SWDimTab" + name)
            self.lay = QtWidgets.QVBoxLayout(page)
            self.lay.setContentsMargins(2, 6, 2, 6)     # the tabs inside the pane's margins: keep it 300 px wide
            fn()
            self.lay.addStretch(1)
            self.tabs.addTab(page, name)
        self.loading = False
        for fn in self._after:
            fn()
        if self.others:
            for g in self.form.findChildren(QtWidgets.QGroupBox):
                if g.title() == "Primary Value":
                    g.setVisible(False)          # several dimensions: no one value to show (never greyed)
        try:
            last = App.ParamGet(PARAM).GetInt("LastTab", 0)
            self.tabs.setCurrentIndex(max(0, min(last, self.tabs.count() - 1)))
        except Exception as _fw_err:
            _fw_log("drawdimpm.py:762", _fw_err)
        self.tabs.currentChanged.connect(lambda i: App.ParamGet(PARAM).SetInt("LastTab", int(i)))

    # ----------------------------------------------------------------- Value
    def value_tab(self):
        dim = self.dim
        P.style_group(self, "Dimension")
        box, lay = D._group("Tolerance/Precision", self.form)
        grid = QtWidgets.QGridLayout()
        self.tol = QtWidgets.QComboBox(box)
        self.tol.setObjectName("SWDimTolerance")
        self.tol.addItems(TOLERANCES)
        self.tol.setCurrentText(tolerance_of(dim))
        self.plus = QtWidgets.QDoubleSpinBox(box)
        self.plus.setObjectName("SWDimMaxVariation")
        self.minus = QtWidgets.QDoubleSpinBox(box)
        self.minus.setObjectName("SWDimMinVariation")
        for w in (self.plus, self.minus):
            w.setDecimals(4)
            w.setRange(-1000, 1000)
            w.setSuffix("mm")
            w.setSingleStep(0.01)
        over, under = float(dim.OverTolerance), float(dim.UnderTolerance)
        self.plus.setValue(over if (abs(over) > 1e-12 or abs(under) > 1e-12) else 0.1)
        self.minus.setValue(under if (abs(over) > 1e-12 or abs(under) > 1e-12) else -0.1)
        prec = (getattr(dim, "SWPrecision", "") or "").split("|")
        o = options_of(dim)
        on_doc = not o or getattr(dim, "SWDocDefaults", "") == "1"      # the dimension follows the document

        # list ends in its Document item ("Same as nominal (Document)" by default) and Same as nominal
        self.precision = QtWidgets.QComboBox(box)
        self.precision.setObjectName("SWDimPrecision")
        self.precision.addItems(list(PRECISIONS) + [doc_label(dim.Document, "unit")])
        cur = prec[0] if prec[0] else precision_of(dim.FormatSpec)
        self.precision.setCurrentText(doc_label(dim.Document, "unit") if (on_doc and cur == doc_precision(
            dim.Document, "unit")) or o.get("prec_doc") else cur)
        self.tol_precision = QtWidgets.QComboBox(box)
        self.tol_precision.setObjectName("SWDimTolPrecision")
        self.tol_precision.addItems(list(PRECISIONS) + [doc_label(dim.Document, "tol"), SAME_AS_NOMINAL])
        tcur = prec[1] if len(prec) > 1 else doc_precision(dim.Document, "tol")
        tdoc = cur if doc_tol_nominal(dim.Document) else doc_precision(dim.Document, "tol")
        mode = o.get("tol_prec") if o.get("tol_prec_was", tcur) == tcur else ""
        self.tol_precision.setCurrentText(SAME_AS_NOMINAL if mode == "nominal" else doc_label(dim.Document, "tol")
                                          if mode == "doc" or (on_doc and tcur == tdoc)
                                          else tcur)
        self.max_label = QtWidgets.QLabel("Maximum variation:", box)
        self.min_label = QtWidgets.QLabel("Minimum variation:", box)
        rows = (("Tolerance:", self.tol), (self.max_label, self.plus), (self.min_label, self.minus),
                ("Unit precision:", self.precision), ("Tolerance precision:", self.tol_precision))
        for n, (lab, w) in enumerate(rows):
            grid.addWidget(lab if isinstance(lab, QtWidgets.QLabel) else QtWidgets.QLabel(lab, box), n, 0)
            grid.addWidget(w, n, 1)
        lay.addLayout(grid)
        # Link precisions with model: the unit precision follows the model's (FreeCAD's Units decimals)
        self.link_precision = QtWidgets.QCheckBox("Link precisions with model", box)
        self.link_precision.setObjectName("SWDimLinkPrecision")
        self.link_precision.setChecked(getattr(dim, "SWLinkPrecision", "") == "1")
        lay.addWidget(self.link_precision)
        if self.link_precision.isChecked():
            self.precision.setCurrentText(model_precision())
        self.link_precision.toggled.connect(self.relink)
        DL.sets(self.link_precision, False, self.precision)     # a precision picked unlinks it (never greyed)
        o = options_of(dim)
        self.fit_box = QtWidgets.QWidget(box)
        fg = QtWidgets.QGridLayout(self.fit_box)
        fg.setContentsMargins(0, 0, 0, 0)
        self.fit_class = QtWidgets.QComboBox(self.fit_box)
        self.fit_class.setObjectName("SWDimFitClass")
        self.fit_class.addItems(list(CLASSES))
        self.hole_fit = QtWidgets.QComboBox(self.fit_box)
        self.hole_fit.setObjectName("SWDimHoleFit")
        self.hole_fit.addItems(HOLE_FITS)
        self.hole_fit.setCurrentText(o.get("hole_fit", "") or ("H7" if dim.Type in ("Diameter", "Radius") else ""))
        self.shaft_fit = QtWidgets.QComboBox(self.fit_box)
        self.shaft_fit.setObjectName("SWDimShaftFit")
        self.shaft_fit.addItems(SHAFT_FITS)
        self.shaft_fit.setCurrentText(o.get("shaft_fit", ""))
        for n, (lab, w) in enumerate((("Classification:", self.fit_class), ("Hole Fit:", self.hole_fit),
                                      ("Shaft Fit:", self.shaft_fit))):
            fg.addWidget(QtWidgets.QLabel(lab, self.fit_box), n, 0)
            fg.addWidget(w, n, 1)

        row = QtWidgets.QHBoxLayout()
        self.fit_display = QtWidgets.QButtonGroup(self.fit_box)
        self.fit_display.setExclusive(True)
        cur = o.get("fit_display", "Linear")
        for n, (obj, tip) in enumerate((("SWDimFitLinear", "Linear display"),
                                        ("SWDimFitStacked", "Stacked with line display"),
                                        ("SWDimFitStackedNoLine", "Stacked without line display"))):
            b = QtWidgets.QToolButton(self.fit_box)
            b.setObjectName(obj)
            b.setText(("Linear", "Stacked", "Stacked, no line")[n])
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setChecked(FIT_DISPLAYS[n] == cur)
            self.fit_display.addButton(b, n)
            row.addWidget(b)
        row.addStretch(1)
        fg.addLayout(row, 3, 0, 1, 2)
        self._fit_display_buttons = self.fit_display.buttons()
        lay.addWidget(self.fit_box)
        self.tol_parens = QtWidgets.QCheckBox("Show parentheses", box)
        self.tol_parens.setObjectName("SWDimTolParens")
        self.tol_parens.setChecked(bool(o.get("tol_parens")))
        lay.addWidget(self.tol_parens)
        self.lay.addWidget(box)
        box, lay = D._group("Primary Value", self.form)
        self.name = QtWidgets.QLineEdit("%s@%s" % (dim.Label, self._view_label()), box)
        self.name.setObjectName("SWDimName")
        self.name.setReadOnly(True)
        lay.addWidget(self.name)
        self.value = QtWidgets.QLineEdit(box)
        self.value.setObjectName("SWDimValue")
        self.value.setReadOnly(True)
        lay.addWidget(self.value)
        self.override = QtWidgets.QCheckBox("Override value:", box)
        self.override.setObjectName("SWDimOverride")
        self.override_value = QtWidgets.QLineEdit(getattr(dim, "SWOverride", "") or "", box)
        self.override_value.setObjectName("SWDimOverrideValue")
        self.override.setChecked(bool(getattr(dim, "SWOverride", "")))
        DL.sets(self.override, True, self.override_value)       # typing a value turns Override value on
        lay.addWidget(self.override)
        lay.addWidget(self.override_value)
        self.lay.addWidget(box)
        box, lay = D._group("Dimension Text", self.form)
        lines = text_of(dim).split("\n")
        k = next((i for i, ln in enumerate(lines) if DIM in ln), 0)
        self.text_above = QtWidgets.QLineEdit("\n".join(lines[:k]).replace("\n", " / "), box)
        self.text_above.setObjectName("SWDimTextAbove")
        self.text_above.setPlaceholderText("text above the value")
        self.text_above.setToolTip("Dimension Text above the dimension line (\" / \" starts another line)")
        self.text = QtWidgets.QLineEdit(lines[k] if lines else DIM, box)
        self.text.setObjectName("SWDimText")
        self.text_below = QtWidgets.QLineEdit(" / ".join(lines[k + 1:]), box)
        self.text_below.setObjectName("SWDimTextBelow")
        self.text_below.setPlaceholderText("text below the value")
        self.text_below.setToolTip("Dimension Text below the dimension line (\" / \" starts another line)")
        lay.addWidget(self.text_above)
        lay.addWidget(self.text)
        lay.addWidget(self.text_below)
        row = QtWidgets.QHBoxLayout()
        for sym, tip in SYMBOLS:
            b = QtWidgets.QToolButton(box)
            b.setObjectName("SWDimSymbol" + tip.replace("/", ""))
            b.setText(sym)
            b.setToolTip(tip)
            b.setFixedWidth(24)
            b.clicked.connect(lambda *_, s=sym: self.insert(s))
            row.addWidget(b)
        row.addStretch(1)
        row.setSpacing(2)
        lay.addLayout(row)
        self.parens = QtWidgets.QCheckBox("Add Parentheses", box)
        self.parens.setObjectName("SWDimParentheses")
        mid = (dim.FormatSpec or "").split("\n")
        mid = mid[min(k, len(mid) - 1)] if mid else ""
        self.parens.setChecked(mid.startswith("(") and mid.endswith(")"))
        lay.addWidget(self.parens)
        self.center = QtWidgets.QCheckBox("Center dimension", box)
        self.center.setObjectName("SWDimCenter")
        self.center.setChecked(getattr(dim, "SWCenterText", "") == "1")
        lay.addWidget(self.center)
        self.inspection = QtWidgets.QCheckBox("Inspection dimension", box)
        self.inspection.setObjectName("SWDimInspection")
        self.inspection.setChecked(bool(o.get("inspection")))
        lay.addWidget(self.inspection)
        self.lay.addWidget(box)
        box, lay = D._group("Dual Dimension", self.form)
        self.dual = QtWidgets.QCheckBox("Dual dimension display", box)
        self.dual.setObjectName("SWDimDual")
        self.dual.setChecked(bool(o.get("dual")))
        lay.addWidget(self.dual)
        dg = QtWidgets.QGridLayout()
        self.dual_unit = QtWidgets.QComboBox(box)
        self.dual_unit.setObjectName("SWDimDualUnit")
        self.dual_unit.addItems(list(UNITS))
        self.dual_unit.setCurrentText(o.get("dual_unit", "in"))
        self.dual_place = QtWidgets.QComboBox(box)
        self.dual_place.setObjectName("SWDimDualPlace")
        self.dual_place.addItems(DUAL_PLACES)
        self.dual_place.setCurrentText(o.get("dual_place", "To right"))
        self.dual_precision = QtWidgets.QComboBox(box)
        self.dual_precision.setObjectName("SWDimDualPrecision")
        self.dual_precision.addItems(PRECISIONS)
        self.dual_precision.setCurrentText(o.get("dual_precision", ".123"))
        for n, (lab, w) in enumerate((("Units:", self.dual_unit), ("Position:", self.dual_place),
                                      ("Precision:", self.dual_precision))):
            dg.addWidget(QtWidgets.QLabel(lab, box), n, 0)
            dg.addWidget(w, n, 1)
        lay.addLayout(dg)
        dual_rows = lambda on: [DL.row(w, on) for w in (self.dual_unit, self.dual_place, self.dual_precision)]
        dual_rows(self.dual.isChecked())
        self.dual.toggled.connect(dual_rows)            # hidden while Dual dimension display is off (never greyed)
        self.lay.addWidget(box)
        if self.parens.isChecked() and self.text.text().startswith("(") and self.text.text().endswith(")"):
            self.text.setText(self.text.text()[1:-1])
        self._text0 = (self.full_text(), self.parens.isChecked())
        self.show_value()
        self.tol.currentTextChanged.connect(self.retol)
        for w in (self.precision, self.tol_precision):
            w.currentTextChanged.connect(self.revalue)
        for w in (self.plus, self.minus):
            w.valueChanged.connect(self.revalue)
        self.override.toggled.connect(lambda on: self.revalue())
        self.override_value.textChanged.connect(self.revalue)
        for w in (self.text, self.text_above, self.text_below):
            w.textChanged.connect(self.revalue)
        self.parens.toggled.connect(self.revalue)
        self.center.toggled.connect(self.recenter)
        for w in (self.hole_fit, self.shaft_fit, self.dual_unit, self.dual_place, self.dual_precision):
            w.currentTextChanged.connect(self.revalue)
        self.fit_class.currentTextChanged.connect(self.reclass)
        self.inspection.toggled.connect(self.revalue)
        self.dual.toggled.connect(self.revalue)
        self.tol_parens.toggled.connect(self.revalue)
        self.fit_display.buttonClicked.connect(lambda *_: self.revalue())
        self.retol(self.tol.currentText(), write=False)

    def _view_label(self):
        refs = self.dim.References2D or []
        return refs[0][0].Label if refs else ""

    def show_value(self):
        n = _digits(self.precision.currentText())
        unit = "°" if self.dim.Type in ("Angle", "Angle3Pt") else "mm"
        self.value.setText(("%." + str(n) + "f%s") % (value_of(self.dim), unit))

    def insert(self, sym):
        self.text.insert(sym)
        self.text.setFocus()

    def retol(self, tol, write=True):
        two = tol in ("Bilateral", "Limit")
        one = tol == "Symmetric"
        for w in (self.plus, self.max_label):
            w.setVisible(two or one)
        for w in (self.minus, self.min_label):
            w.setVisible(two)
        DL.row(self.tol_precision, tol in ("Bilateral", "Symmetric") + FITS)
        self.fit_box.setVisible(tol in FITS)
        self.tol_parens.setVisible(tol in ("Bilateral", "Fit with tolerance", "Fit (tolerance only)"))
        if write:
            self.revalue()

    def revalue(self, *_):
        if self.loading:
            return
        ov = self.override_value.text() if self.override.isChecked() else None
        units = self.units.currentText() if getattr(self, "units", None) is not None and \
            self.own_units.isChecked() else "Document"
        first = self.dim
        text0 = getattr(self, "_text0", None)

        def own(d):
            """Several dimensions: each keeps its own Primary Value (override) and, until the text is edited,
            its own Dimension Text and parentheses."""
            if d is first:
                return self.full_text(), self.parens.isChecked(), ov
            t, par = self.full_text(), self.parens.isChecked()
            if text0 is not None and (t, par) == text0:
                t = text_of(d)
                spec = d.FormatSpec or ""
                par = spec.startswith("(") and spec.endswith(")")
                if par and t.startswith("(") and t.endswith(")"):
                    t = t[1:-1]
            return t, par, (getattr(d, "SWOverride", "") or None)

        self.change(lambda: apply(self.dim, self.tol.currentText(), self.plus.value(), self.minus.value(),
                                  self.precision.currentText(), self.tol_precision.currentText(),
                                  *own(self.dim), self.hole_fit.currentText(),
                                  self.shaft_fit.currentText(), self.dual.isChecked(), self.dual_unit.currentText(),
                                  self.dual_place.currentText(), self.dual_precision.currentText(), units,
                                  self.inspection.isChecked(), tol_parens=self.tol_parens.isChecked(),
                                  fit_display=self.fit_display_name()))
        self.show_value()

    def fit_display_name(self):
        try:
            n = self.fit_display.checkedId()
            on = bool(self.hole_fit.currentText() and self.shaft_fit.currentText())
            for b in self._fit_display_buttons:
                b.setVisible(on)         # one fit only: no stacked display to pick (hidden, never greyed)
            return FIT_DISPLAYS[n] if on and 0 <= n < len(FIT_DISPLAYS) else "Linear"
        except Exception:
            return "Linear"

    def relink(self, on):
        """Link precisions with model on: the unit precision is the model's and is greyed; off: free again."""
        self.change(lambda: _sprop(self.dim, "SWLinkPrecision", "1" if on else "", "precision linked to model"))
        if on:
            self.precision.setCurrentText(model_precision())     # revalue() writes it to every picked dim

    def reclass(self, name):
        """Classification: the hole and shaft lists narrow to that kind of fit (User Defined: all of them)."""
        pairs = CLASSES.get(name)
        holes = HOLE_FITS if not pairs else [""] + sorted({p.split("/")[0] for p in pairs})
        shafts = SHAFT_FITS if not pairs else [""] + sorted({p.split("/")[1] for p in pairs})
        for combo, items in ((self.hole_fit, holes), (self.shaft_fit, shafts)):
            cur = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(items)
            combo.setCurrentText(cur if cur in items else items[1] if len(items) > 1 else "")
            combo.blockSignals(False)
        self.revalue()

    def recenter(self, on):
        if self.loading:
            return

        def go():
            _sprop(self.dim, "SWCenterText", "1" if on else "0", "Center dimension")
            if on:
                center_text(self.dim)
        self.change(go)

    # ----------------------------------------------------------------- Leaders
    def leaders_tab(self):
        dim = self.dim
        vo = dim.ViewObject
        box, lay = D._group("Witness/Leader Display", self.form)
        row = QtWidgets.QHBoxLayout()
        self.arrows = QtWidgets.QButtonGroup(box)
        flip = bool(getattr(vo, "FlipArrowheads", False)) if vo is not None else False
        try:
            from . import drawdocprops as DDP
            stored = DDP.prop(dim.Document, "dim_arrows") or "Smart"     # Document Properties > Dimensions
        except Exception:
            stored = "Smart"
        how = getattr(dim, "SWArrows", "") or ("Outside" if flip else stored if stored != "Outside" else "Smart")
        for name in ("Outside", "Inside", "Smart"):
            b = QtWidgets.QToolButton(box)
            b.setObjectName("SWDimArrows" + name)
            b.setText(name)
            b.setToolTip("Arrows " + name.lower() if name != "Smart" else "Smart")
            b.setCheckable(True)
            b.setChecked(name == how)
            self.arrows.addButton(b)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.arrows.buttonClicked.connect(lambda b: self.rearrow(b.text()))
        self.arrow_style = QtWidgets.QComboBox(box)
        self.arrow_style.setObjectName("SWDimArrowStyle")
        try:
            self.arrow_style.addItems(vo.getEnumerationsOfProperty("ArrowStyle"))
            self.arrow_style.setCurrentText(str(vo.ArrowStyle))
        except Exception:
            self.arrow_style.addItems(["Filled arrow", "Open arrow", "Tick", "Dot", "Open circle", "Fork",
                                       "Filled triangle", "None"])
        self.arrow_style.currentTextChanged.connect(
            lambda t: self.change(lambda: setattr(self.dim.ViewObject, "ArrowStyle", t)))
        lay.addWidget(self.arrow_style)
        self.break_group(box, lay)
        from . import drawdimtools as DDT
        linear = DDT.is_linear_round(dim)
        if dim.Type in ("Radius", "Diameter") or linear:
            row = QtWidgets.QHBoxLayout()
            self.round = QtWidgets.QButtonGroup(box)
            for name in ("Radius", "Diameter", "Linear"):
                b = QtWidgets.QToolButton(box)
                b.setObjectName("SWDim" + name)
                b.setText(name)
                b.setToolTip("Display as " + name.lower())
                b.setCheckable(True)
                b.setChecked(name == "Linear" if linear else dim.Type == name)
                self.round.addButton(b)
                row.addWidget(b)
            row.addStretch(1)
            lay.addLayout(row)
            self.round.buttonClicked.connect(lambda b: self.change(lambda: self.to_round(b.text())))
        self.lay.addWidget(box)
        box, lay = D._group("Leader/Dimension Line Style", self.form)
        self.thickness = QtWidgets.QComboBox(box)
        self.thickness.setObjectName("SWDimLineThickness")
        self.thickness.addItems(THICKNESS)
        self.thickness.setCurrentText(getattr(dim, "SWLineThickness", "") or "Use document")
        self.thickness.currentTextChanged.connect(self.rethick)
        lay.addWidget(self.thickness)
        self.lay.addWidget(box)
        if dim.Type in ("Diameter", "Radius", "Angle", "Angle3Pt"):
            self.text_position_group(dim)
        if dim.Type in ("Distance", "DistanceX", "DistanceY") and arc_radii(dim):
            self.arc_condition_group(dim)
        box, lay = D._group("Extension Line Style", self.form)
        from . import drawdocprops as DDP
        self.doc_gap = QtWidgets.QCheckBox("Use document gaps", box)
        self.doc_gap.setObjectName("SWDimDocGap")
        self.doc_gap.setChecked(getattr(dim, "SWDocGap", "1") != "0")
        lay.addWidget(self.doc_gap)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Extension line gap:", box))
        self.gap = QtWidgets.QDoubleSpinBox(box)
        self.gap.setObjectName("SWDimGap")
        self.gap.setRange(0.0, 10.0)
        self.gap.setDecimals(2)
        self.gap.setSingleStep(0.25)
        self.gap.setToolTip("The gap between the model and the start of the extension lines")
        try:
            self.gap.setValue(float(vo.GapFactorASME if "ASME" in str(vo.StandardAndStyle) else vo.GapFactorISO))
        except Exception:
            self.gap.setValue(0.75)
        self.gap.valueChanged.connect(self.regap)
        row.addWidget(self.gap)
        lay.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Beyond dimension line:", box))
        self.beyond = QtWidgets.QDoubleSpinBox(box)
        self.beyond.setObjectName("SWDimBeyond")
        self.beyond.setRange(0.0, 20.0)
        self.beyond.setDecimals(2)
        self.beyond.setSingleStep(0.5)
        self.beyond.setSuffix("mm")
        self.beyond.setSpecialValueText("Standard")
        self.beyond.setToolTip("How far the extension lines run past the dimension line")
        own = _number(getattr(dim, "SWBeyond", ""))
        self.beyond.setValue(float(dim.SWBeyond) if own else float(DDP.prop(self.doc, "dim_beyond") or 0.0))
        self.beyond.valueChanged.connect(self.rebeyond)
        row.addWidget(self.beyond)
        lay.addLayout(row)
        self.doc_gap.toggled.connect(self.redocgap)
        DL.sets(self.doc_gap, False, self.gap, self.beyond)      # a gap typed is the dimension's own
        self.lay.addWidget(box)

    def break_group(self, box, lay):
        """Witness/Leader Display > Break Lines: gaps where other dimensions' lines cross this one's
        (Use document gap = Document Properties > Dimensions > Break dimension/extension lines)."""
        from . import drawdimlines as L
        dim = self.dim
        self.break_lines = QtWidgets.QCheckBox("Break Lines", box)
        self.break_lines.setObjectName("SWDimBreakLines")
        self.break_lines.setChecked(L.breaks(dim))
        lay.addWidget(self.break_lines)
        self.break_doc = QtWidgets.QCheckBox("Use document gap", box)
        self.break_doc.setObjectName("SWDimBreakDocGap")
        own = getattr(dim, L.BREAK_GAP, "")
        self.break_doc.setChecked(not own)
        lay.addWidget(self.break_doc)
        row = QtWidgets.QHBoxLayout()
        self.break_gap_label = QtWidgets.QLabel("Gap:", box)
        row.addWidget(self.break_gap_label)
        self.break_gap = QtWidgets.QDoubleSpinBox(box)
        self.break_gap.setObjectName("SWDimBreakGap")
        self.break_gap.setRange(0.0, 20.0)
        self.break_gap.setDecimals(2)
        self.break_gap.setSingleStep(0.25)
        self.break_gap.setSuffix("mm")
        self.break_gap.setValue(L.break_gap(dim))
        row.addWidget(self.break_gap)
        lay.addLayout(row)

        def enable():
            on = self.break_lines.isChecked()
            DL.row(self.break_doc, on)              # shown while Break lines is on (never greyed)
            DL.row(self.break_gap, on)
            self.break_gap_label.setVisible(on)
        enable()
        DL.sets(self.break_doc, False, self.break_gap)          # a gap typed is the dimension's own

        def go():
            L.set_break(self.dim, self.break_lines.isChecked(),
                        "" if self.break_doc.isChecked() else self.break_gap.value())

        def changed(*_):
            enable()
            if self.break_doc.isChecked():
                try:
                    from . import drawdocprops as DDP
                    self.break_gap.blockSignals(True)
                    self.break_gap.setValue(float(DDP.prop(self.doc, "dim_break_gap") or 1.0))
                    self.break_gap.blockSignals(False)
                except Exception as _fw_err:
                    _fw_log("drawdimpm.py:1218", _fw_err)
            self.change(go)
            QtCore.QTimer.singleShot(200, L.apply_all)
        self.break_lines.toggled.connect(changed)
        self.break_doc.toggled.connect(changed)
        self.break_gap.valueChanged.connect(changed)

    def arc_condition_group(self, dim):
        """Leaders tab > Arc Condition: a distance to a circle measured from its centre, its near side (Min) or its
        far side (Max), for the first and second item."""
        box, lay = D._group("Arc Condition", self.form)
        cur = (getattr(dim, "SWArcCondition", "") or "Center|Center").split("|")
        self.arc_combos = []
        for n, label in enumerate(("First arc condition:", "Second arc condition:")):
            lab = QtWidgets.QLabel(label, box)
            lay.addWidget(lab)
            c = QtWidgets.QComboBox(box)
            c.setObjectName("SWDimArcCondition%d" % (n + 1))
            c.addItems(ARC_CONDITIONS)
            c.setCurrentText(cur[n] if n < len(cur) else "Center")
            arc = arc_radii(dim)[n] is not None          # not a circle: no arc condition (hidden, never greyed)
            c.setVisible(arc)
            lab.setVisible(arc)
            c.currentTextChanged.connect(lambda *_: self.change(lambda: set_arc_condition(
                self.dim, [x.currentText() for x in self.arc_combos])))
            lay.addWidget(c)
            self.arc_combos.append(c)
        self.lay.addWidget(box)

    TEXT_POSITIONS = ("Solid leader, aligned text", "Broken leader, horizontal text", "Broken leader, aligned text")

    def text_position_group(self, dim):
        """Leaders tab > Custom Text Position: this dimension's own text position over the document's."""
        box, lay = D._group("Custom Text Position", self.form)
        self.custom_pos = QtWidgets.QCheckBox("Custom text position", box)
        self.custom_pos.setObjectName("SWDimCustomTextPosition")
        cur = getattr(dim, "SWTextPosition", "")
        self.custom_pos.setChecked(bool(cur))
        lay.addWidget(self.custom_pos)
        self.pos_buttons = QtWidgets.QButtonGroup(box)
        for n, t in enumerate(self.TEXT_POSITIONS):
            b = QtWidgets.QRadioButton(t, box)
            b.setObjectName("SWDimTextPosition%d" % n)
            b.setChecked(t == (cur or self.TEXT_POSITIONS[1]))
            DL.sets(self.custom_pos, True, b)          # picking a position turns Custom text position on
            self.pos_buttons.addButton(b, n)
            lay.addWidget(b)
        self.custom_pos.toggled.connect(lambda *_: self.change(self.retextpos))
        self.pos_buttons.buttonClicked.connect(lambda *_: self.change(self.retextpos))
        self.lay.addWidget(box)

    def full_text(self):
        """Above / value line / below as one Dimension Text ("<DIM>" on its own line)."""
        out = []
        for w in (getattr(self, "text_above", None), self.text, getattr(self, "text_below", None)):
            if w is None:
                continue
            t = w.text()
            if w is self.text:
                out.append(t)
            else:
                out += [x.strip() for x in t.split(" / ") if x.strip()]
        return "\n".join(out)

    def retextpos(self):
        dim = self.dim
        want = self.pos_buttons.checkedButton().text() if self.custom_pos.isChecked() else ""
        _sprop(dim, "SWTextPosition", want, "Custom text position")
        vo = dim.ViewObject
        if not want:
            from . import drawdocprops
            v = dict(drawdocprops.defaults(), **drawdocprops.stored(dim.Document))
            drawdocprops.text_position(dim, vo, v.get("standard", "ISO"))
            return
        ansi = "ASME" in str(vo.StandardAndStyle)
        vo.StandardAndStyle = {"Solid leader, aligned text": "ISO Oriented",
                               "Broken leader, horizontal text": "ASME Referencing" if ansi else "ISO Referencing",
                               "Broken leader, aligned text": "ISO Referencing"}[want]

    def redocgap(self, on):
        from . import drawdocprops as DDP

        def go():
            _sprop(self.dim, "SWDocGap", "1" if on else "0", "extension line gaps from Document Properties")
            if on:
                g = float(DDP.prop(self.doc, "dim_gap") or 0.75)
                self.dim.ViewObject.GapFactorISO = g
                self.dim.ViewObject.GapFactorASME = g
                _sprop(self.dim, "SWBeyond", "", "extension beyond the dimension line")
        self.change(go)
        if on:
            self.loading = True
            self.gap.setValue(float(DDP.prop(self.doc, "dim_gap") or 0.75))
            self.beyond.setValue(float(DDP.prop(self.doc, "dim_beyond") or 0.0))
            self.loading = False
        self.change(lambda: extension_beyond(self.dim))

    def rebeyond(self, value):
        def go():
            _sprop(self.dim, "SWBeyond", "%g" % value, "extension beyond the dimension line")
        self.change(go)
        QtCore.QTimer.singleShot(150, lambda: extension_beyond(self.dim))

    def regap(self, value):
        def go():
            vo = self.dim.ViewObject
            vo.GapFactorISO = value
            vo.GapFactorASME = value
        self.change(go)

    def rearrow(self, how):
        def go():
            _sprop(self.dim, "SWArrows", how, "arrows outside / inside / smart")
            self.dim.ViewObject.FlipArrowheads = how == "Outside"
        self.change(go)
        QtCore.QTimer.singleShot(150, lambda: extension_beyond(self.dim))

    def show_arrows(self):
        """The Outside / Inside / Smart buttons after the arrows were flipped on the sheet."""
        how = getattr(self.dim, "SWArrows", "") or "Smart"
        for b in self.arrows.buttons():
            b.setChecked(b.text() == how)

    def to_round(self, kind):
        from . import drawdimtools as DDT
        if kind == "Linear":
            DDT.display_as_linear(self.dim)
            return
        if DDT.display_as_round(self.dim, kind):
            return
        fs = self.dim.FormatSpec or ""
        fs = fs.replace("⌀", "R", 1) if kind == "Radius" else fs.replace("R", "⌀", 1) if fs.startswith("R") else fs
        self.dim.Type = kind
        self.dim.FormatSpec = fs

    def rethick(self, text):
        def go():
            _sprop(self.dim, "SWLineThickness", text, "leader line thickness")
            vo = self.dim.ViewObject
            vo.LineWidth = 0.25 if text == "Use document" else float(text[:-2])
        self.change(go)

    # ----------------------------------------------------------------- Other
    def other_tab(self):
        dim = self.dim
        vo = dim.ViewObject
        box, lay = D._group("Text Fonts", self.form)
        fonts_box = box
        P.format_group(self, box=box, lay=lay)
        own = getattr(dim, "SWFont", "")
        if own:
            self.doc_font.setChecked(False)
            self.font_family.setText(own)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Font height:", box))
        self.font_size = QtWidgets.QDoubleSpinBox(box)
        self.font_size.setObjectName("SWDimFontSize")
        self.font_size.setRange(0.5, 50)
        self.font_size.setDecimals(2)
        self.font_size.setSuffix("mm")
        try:
            self.font_size.setValue(float(getattr(vo.Fontsize, "Value", vo.Fontsize)))
        except Exception:
            self.font_size.setValue(3.5)
        DL.sets(self.doc_font, False, self.font_size)          # a height typed turns Use document font off
        self.font_size.valueChanged.connect(lambda *_: self.retext())
        row.addWidget(self.font_size)
        lay.addLayout(row)
        self.lay.addWidget(box)
        box, lay = D._group("Override Units", self.form)
        o = options_of(dim)
        self.own_units = QtWidgets.QCheckBox("Override units", box)
        self.own_units.setObjectName("SWDimOverrideUnits")
        self.own_units.setChecked(o.get("units", "Document") in UNITS)
        self.units = QtWidgets.QComboBox(box)
        self.units.setObjectName("SWDimUnits")
        self.units.addItems(list(UNITS))
        self.units.setCurrentText(o.get("units") if o.get("units") in UNITS else "in")
        DL.sets(self.own_units, True, self.units)             # a unit picked is the dimension's own
        self.own_units.toggled.connect(lambda on: self.revalue())
        self.units.currentTextChanged.connect(self.revalue)
        lay.addWidget(self.own_units)
        lay.addWidget(self.units)
        at = self.lay.indexOf(fonts_box)
        self.lay.insertWidget(at if at >= 0 else self.lay.count(), box)
        box, lay = D._group("Options", self.form)
        self.read_only = QtWidgets.QCheckBox("Read only", box)
        self.read_only.setObjectName("SWDimReadOnly")
        self.read_only.setChecked(bool(getattr(dim, "LockPosition", False)))
        self.read_only.toggled.connect(lambda on: self.change(lambda: setattr(self.dim, "LockPosition", on)))
        lay.addWidget(self.read_only)
        self.lay.addWidget(box)
        P.layer_group(self)
        cur = getattr(dim, "SWLayer", "")
        self.layer.setCurrentText(cur or P.NONE_LAYER)

    def retext(self):
        """Use document font / Font... / font height, live."""
        if self.loading:
            return

        def go():
            vo = self.dim.ViewObject
            if self.doc_font.isChecked():
                _sprop(self.dim, "SWFont", "", "own font")
                vo.Font = "osifont"
                vo.Fontsize = 3.5
            else:
                _sprop(self.dim, "SWFont", self.font_family.text(), "own font")
                vo.Font = self.font_family.text()
                vo.Fontsize = self.font_size.value()
        self.change(go)

    # ----------------------------------------------------------------- the task dialog
    def change(self, fn):
        if self.loading:
            return
        if not self.started:
            self.doc.openTransaction("Dimension")
            self.started = True
        first = self.dim
        try:
            for d in [first] + list(self.others):
                self.dim = d
                try:
                    fn()
                except Exception as error:
                    App.Console.PrintWarning("FreeCAD: Dimension: %s\n" % error)
        finally:
            self.dim = first
        self.doc.recompute()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _end(self, keep):
        if self.closing:
            return
        self.closing = True
        if keep:
            try:
                P.finish_layers(self)
            except Exception as _fw_err:
                _fw_log("drawdimpm.py:1456", _fw_err)
        if self.started:
            if keep:
                self.doc.commitTransaction()
            else:
                self.doc.abortTransaction()
            self.started = False
        self.doc.recompute()
        if D.VIEW_PM and D.VIEW_PM[0] is self:
            D.VIEW_PM[:] = []

    def accept(self):
        self._end(True)
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._end(False)
        Gui.Control.closeDialog()
        return True

    def close_quietly(self):
        self._end(True)


def is_dimension(o):
    return o is not None and o.TypeId == "TechDraw::DrawViewDimension"


def open_for(dim, others=()):
    """Shows the Dimension PM of dim (in place of the PM of another picked item); others: more picked dimensions
    the PM changes too."""
    if dim is None:
        return None
    if D.VIEW_PM:
        same = set(o.Name for o in getattr(D.VIEW_PM[0], "others", [])) == set(o.Name for o in others
                                                                           if o is not dim)
        if D.VIEW_PM[0].view is dim and same and Gui.Control.activeDialog():
            return D.VIEW_PM[0]
        D.VIEW_PM[0].close_quietly()
        D.VIEW_PM[:] = []
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
    elif Gui.Control.activeDialog():
        return None
    try:
        from . import drawselect
        page = _page_of(dim)
        if page is not None:
            drawselect.hook_page(page)          # the arrow dots answer clicks
    except Exception as _fw_err:
        _fw_log("drawdimpm.py:1507", _fw_err)
    panel = DimensionPanel(dim, others)
    try:
        panel.form.setProperty("swKeepKeys", True)     # a picked dimension's PM leaves the keys on the sheet
    except Exception as _fw_err:
        _fw_log("drawdimpm.py:keep_keys", _fw_err)
    Gui.Control.showDialog(panel)
    D.VIEW_PM[:] = [panel]
    return panel
