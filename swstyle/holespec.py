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
import traceback

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import naming, paths, sketchstart
from . import holeends, holelegacy, holeoptions, holeslot
from . import holedata


def _error_css():
    ""
    try:
        from . import propertymanager
        return propertymanager.error_css()
    except Exception:
        return "color: #c00000;"

PARAMS = paths.PARAM_PATH + "/HoleWizard"
TITLE = "Hole Specification"
ICON = "FEATURES_HOLE_WIZARD"
PANEL = "SWHoleSpec"

KINDS = ("Counterbore", "Countersink", "Hole", "Straight Tap", "Tapered Tap")

# tables of their round kinds; Legacy Hole (holelegacy.py) is sized by hand
SLOT_KINDS = ("Legacy Hole", "Counterbore Slot", "Countersink Slot", "Slot")
LATER_KINDS = ()
LEGACY = "Legacy Hole"
BASE = {"Counterbore Slot": "Counterbore", "Countersink Slot": "Countersink", "Slot": "Hole"}


def _base(kind):
    """The round hole kind whose standards, types and sizes a slot kind uses."""
    return BASE.get(kind, kind)
NOT_YET = "Not in FreeCAD yet"
NO_FAVORITE = "No Favorite Selected"

# countersinks are cut by holeoptions.py (a Hole Options feature after the Hole).
OPTIONS = {
    "Counterbore": ("Head clearance", "Near side countersink", "Under head countersink", "Far side countersink"),
    "Countersink": ("Head clearance", "Near side countersink", "Far side countersink"),
    "Hole": ("Near side countersink", "Far side countersink"),
}
OPTION_KEYS = {"Head clearance": "clearance", "Near side countersink": "near",
               "Under head countersink": "under", "Far side countersink": "far"}
YELLOW = "QDoubleSpinBox { background: #fff2a8; color: black; }"
METRIC = ("ANSI Metric", "ISO", "AS")
NPT_TAPER = 90.0 - 1.7899          # 1 in 16 on the diameter (NPT, BSPT)

# Type name -> (FreeCAD ThreadType, FreeCAD HoleCutType, tree name word)
CBORE = {
    "Socket Head Cap Screw ISO 4762": ("ISOMetricProfile", "ISO 4762", "Socket Head Cap Screw"),
    "Socket Head Cap Screw with Washer ISO 4762 + 7089":
        ("ISOMetricProfile", "ISO 4762 + 7089", "Socket Head Cap Screw"),
    "Socket Head Cap Screw, Low Head DIN 7984": ("ISOMetricProfile", "DIN 7984", "Low Head Cap Screw"),
    "Hexalobular Pan Head Screw ISO 14583": ("ISOMetricProfile", "ISO 14583", "Pan Head Screw"),
    "Hexalobular Pan Head Screw, Shallow ISO 14583": ("ISOMetricProfile", "ISO 14583 (partial)", "Pan Head Screw"),
    "Socket Head Cap Screw, Fine Thread ISO 12474": ("ISOMetricFineProfile", "ISO 12474", "Socket Head Cap Screw"),
}
CSK = {
    "Socket Countersunk Head Cap Screw ISO 10642": ("ISOMetricProfile", "ISO 10642", "Countersunk Socket Head"),
    "Slotted Countersunk Flat Head ISO 2009": ("ISOMetricProfile", "ISO 2009", "Countersunk Flat Head"),
    "Cross Recessed Countersunk Flat Head ISO 7046": ("ISOMetricProfile", "ISO 7046", "Countersunk Flat Head"),
}
DRILLS = [1.0, 1.5, 2.0, 2.5, 3.0, 3.3, 3.5, 4.0, 4.2, 4.5, 5.0, 5.5, 6.0, 6.5, 6.8, 7.0, 8.0, 8.5, 9.0,
          10.0, 10.2, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0, 22.0, 24.0, 25.0, 26.0,
          28.0, 30.0]
DOWELS = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 13.0, 16.0, 20.0, 25.0]
INCH_DRILLS = ["1/16", "3/32", "1/8", "5/32", "3/16", "7/32", "1/4", "9/32", "5/16", "11/32", "3/8",
               "13/32", "7/16", "15/32", "1/2", "9/16", "5/8", "11/16", "3/4", "13/16", "7/8", "15/16", "1"]

FITS = {"ISOMetricProfile": ("Fine", "Medium", "Coarse"), "UNC": ("Close", "Normal", "Loose")}
FIT_NAMES = ("Close", "Normal", "Loose")

DEFAULT = {"kind": "Hole", "standard": "ISO", "type": "Drill sizes", "size": "Ø10.0",
           "fit": "Normal", "custom": False, "cdia": 0.0, "cdepth": 0.0, "cangle": 90.0,
           "end": "Blind", "depth": 10.0, "tdepth": 0.0, "cosmetic": True,
           "thread_option": "cosmetic", "thread_callout": True, "thread_class": "2B"}

THREAD_OPTIONS = ("cosmetic", "remove", "tapdrill")
THREAD_CLASSES = ("1B", "2B", "3B")                      # ANSI Inch internal thread classes


def thread_option(spec):
    """"cosmetic" (hole at the tap drill, a Cosmetic Thread drawn), "remove" (the thread modelled) or
    "tapdrill" (the hole at the tap drill size, nothing drawn); older specs carry only "cosmetic"."""
    option = spec.get("thread_option")
    if option in THREAD_OPTIONS:
        return option
    return "cosmetic" if spec.get("cosmetic", True) else "remove"


def thread_class(spec):
    cls = spec.get("thread_class") or "2B"
    return cls if spec.get("standard") == "ANSI Inch" else ""


def params():
    return App.ParamGet(PARAMS)


def enabled():
    ""
    return params().GetBool("SolidWorksOrder", True)


def last():
    spec = dict(DEFAULT)
    try:
        spec.update(json.loads(params().GetString("Last", "") or "{}"))
    except ValueError as _fw_err:
        _fw_log("holespec.py:147", _fw_err)
    return spec


def remember(spec):
    params().SetString("Last", json.dumps(spec))


def favorites():
    ""
    try:
        data = json.loads(params().GetString("Favorites", "") or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def set_favorites(data):
    params().SetString("Favorites", json.dumps(data))


# ------------------------------------------------------------------ the data
_sizes_cache = {}


class _Scratch:
    """A hidden throw-away document; the active document stays the active one."""

    def __enter__(self):
        self.active = App.ActiveDocument
        self.doc = App.newDocument("SWHoleScratch", "SWHoleScratch", True, True)
        return self.doc

    def __exit__(self, *exc):
        name = self.doc.Name
        # Closed on the next turn of the event loop: other add-on parts queue work for
        # every new document (material.py) and would find it gone.
        QtCore.QTimer.singleShot(0, lambda: name in App.listDocuments() and App.closeDocument(name))
        if self.active is not None and self.active.Name in App.listDocuments():
            App.setActiveDocument(self.active.Name)
            try:
                Gui.setActiveDocument(self.active.Name)
            except Exception as _fw_err:
                _fw_log("holespec.py:190", _fw_err)
        return False


def _thread_sizes(thread):
    """FreeCAD's size list for a thread standard, read from a scratch Hole (all at once)."""
    if thread not in _sizes_cache:
        with _Scratch() as doc:
            hole = doc.addObject("PartDesign::Hole", "Hole")
            for each in hole.getEnumerationsOfProperty("ThreadType"):
                hole.ThreadType = each
                _sizes_cache[each] = list(hole.getEnumerationsOfProperty("ThreadSize"))
    return _sizes_cache.get(thread, [])


def standards(kind):
    """Every standard the Hole Wizard lists (FreeCAD's tables for ANSI Metric / ISO, ours for the rest)."""
    return list(holedata.STANDARDS)


# FreeCAD-backed counterbore / countersink types stand for these of our own tables (not listed twice)
_FC_COVERS = {"Socket Head Cap Screw", "Socket Head Cap Screw, Low Head", "Socket Countersunk Head Cap Screw",
              "Flat Head Slotted", "Flat Head Cross Recess"}


def is_data(spec):
    """True when the spec's sizes come from holedata (not from FreeCAD's PartDesign Hole tables)."""
    kind, standard, kind_type = _base(spec["kind"]), spec.get("standard"), spec.get("type")
    if kind == "Counterbore":
        return kind_type not in CBORE
    if kind == "Countersink":
        return kind_type not in CSK
    if kind == "Hole":

        return kind_type not in ("Screw Clearances",) or holedata.is_inch(spec.get("standard"))
    return False


def types(kind, standard):
    kind = _base(kind)
    inch = holedata.is_inch(standard)
    if kind in ("Counterbore", "Countersink"):
        ours = holedata.types(kind, standard)
        if standard in METRIC:
            own = list(CBORE if kind == "Counterbore" else CSK)
            return own + [t for t in ours if t not in _FC_COVERS]
        return ours
    return holedata.types(kind, standard)


def thread_of(spec):
    """FreeCAD ThreadType for the spec, or 'None' for a plain diameter."""
    kind, kind_type = _base(spec["kind"]), spec["type"]
    if kind == LEGACY:
        return "None"
    if is_data(spec):
        return "None"
    if kind == "Counterbore":
        return CBORE.get(kind_type, ("ISOMetricProfile",))[0]
    if kind == "Countersink":
        return CSK.get(kind_type, ("ISOMetricProfile",))[0]
    inch = holedata.is_inch(spec["standard"])
    if kind == "Hole":
        return "UNC" if inch else "ISOMetricProfile"
    if kind == "Straight Tap":
        if inch:
            return kind_type.split()[-1] if kind_type.split()[-1] in ("UNC", "UNF", "UNEF") else "UNC"
        return "ISOMetricFineProfile" if kind_type == "Fine Tapped hole" else "ISOMetricProfile"
    return "NPT" if inch else "BSP"


def _show_size(thread, size):
    ""
    if thread == "ISOMetricProfile":
        return size.split("x")[0]
    return size


def sizes(spec):
    """The size list of a hole type, less the sizes ticked off in Toolbox Settings > Hole Wizard (extapps98)."""
    out = _sizes(spec)
    try:
        from . import toolboxconfig
        return toolboxconfig.hole_wizard_sizes(spec.get("standard"), _base(spec["kind"]), spec.get("type"), out)
    except Exception as _fw_err:
        _fw_log("holespec.py:toolbox-sizes", _fw_err)
        return out


def _sizes(spec):
    if is_data(spec):
        return holedata.sizes(_base(spec["kind"]), spec["standard"], spec["type"])
    thread = thread_of(spec)
    out = [_show_size(thread, s) for s in _thread_sizes(thread)]
    kind = _base(spec["kind"])
    # pkg148: only the sizes the tap tables (ASME B1.1, B1.20.1, ISO 7-1) give a pitch and tap drill for;
    # FreeCAD lists some more (NPT 5-12 in, BSP parallel sizes such as 1 3/4, UNF 1 3/16)
    if kind == "Tapered Tap":
        table = holedata.NPT if holedata.is_inch(spec["standard"]) else holedata.BSPT
        out = [s for s in out if s in table]
    elif kind == "Straight Tap" and holedata.is_inch(spec["standard"]):
        series = thread if thread in ("UNC", "UNF", "UNEF") else "UNC"
        out = [s for s in out if s in holedata.TAP_SERIES[series]]
    return out


def data_dims(spec):
    """holedata's sizes for the spec (hole, head diameter / depth / angle, tap drill, thread name)."""
    return holedata.dims(_base(spec["kind"]), spec["standard"], spec["type"], spec["size"],
                         spec.get("fit", "Normal"))


def _freecad_size(thread, shown):
    for size in _thread_sizes(thread):
        if _show_size(thread, size) == shown:
            return size
    return None


def _fraction(text):
    text = text.strip('"').strip()
    whole = 0.0
    if " " in text:
        head, text = text.split(" ", 1)
        whole = float(head)
    if "/" in text:
        a, b = text.split("/")
        return whole + float(a) / float(b)
    return whole + float(text)


def nominal(spec):
    """(nominal diameter mm, pitch mm) for depth defaults."""
    size = spec["size"]
    if size.startswith("Ø"):
        return float(size[1:]), 0.0
    if _base(spec["kind"]) == "Hole" and is_data(spec):
        try:
            return data_dims(spec)["hole"], 0.0
        except Exception as _fw_err:
            _fw_log("holespec.py:318", _fw_err)
    match = re.match(r"M([\d.]+)(?:x([\d.]+))?", size)
    if match:
        d = float(match.group(1))
        pitch = float(match.group(2)) if match.group(2) else _metric_pitch(d)
        return d, pitch
    match = re.match(r"#(\d+)", size)
    if match:
        d = (0.060 + 0.013 * int(match.group(1))) * 25.4
        return d, d * 0.1
    try:
        d = _fraction(size) * 25.4
    except (ValueError, ZeroDivisionError):
        d = 6.0
    return d, d * 0.1


def _metric_pitch(d):
    for size in _thread_sizes("ISOMetricProfile"):
        match = re.match(r"M([\d.]+)x([\d.]+)", size)
        if match and float(match.group(1)) == d:
            return float(match.group(2))
    return d * 0.15


def tap_depths(spec):
    ""
    d, pitch = nominal(spec)
    thread = round(2 * d, 2)
    return round(thread + max(3 * pitch, 1.0), 1), thread


def has_fit(spec):
    return _base(spec["kind"]) in ("Counterbore", "Countersink") or \
        (_base(spec["kind"]) == "Hole" and spec["type"] == "Screw Clearances")


def custom_fields(spec):
    """Which Show custom sizing fields the spec has."""
    kind = _base(spec["kind"])
    if kind == "Counterbore":
        return ("cdia", "cdepth")
    if kind == "Countersink":
        return ("cdia", "cangle")
    if kind == "Hole":
        return ("cdia",)          # the through hole diameter
    return ()


def hole_sizes(spec):
    """(hole diameter, head diameter, head depth) FreeCAD makes for the spec, for the Options'
    countersink defaults."""
    try:
        with _Scratch() as doc:
            hole = doc.addObject("PartDesign::Hole", "Hole")
            try:
                apply(hole, dict(spec, near=False, under=False, far=False, clearance=False))
            except Exception as _fw_err:
                _fw_log("holespec.py:376", _fw_err)
            cut = str(hole.HoleCutType) != "None"
            return (hole.Diameter.Value, hole.HoleCutDiameter.Value if cut else hole.Diameter.Value,
                    hole.HoleCutDepth.Value if cut else 0.0, hole.HoleCutCountersinkAngle.Value if cut else 90.0)
    except Exception:
        d = nominal(spec)[0]
        return d, d * 1.6, d, 90.0


def is_tap(spec):
    return spec["kind"] in ("Straight Tap", "Tapered Tap")


# ------------------------------------------------------------------ the feature
def apply(hole, spec):
    """Set a PartDesign Hole from the spec (property order matters: thread
    type, then size, then cut type, then custom values)."""
    thread = thread_of(spec)
    kind = _base(spec["kind"])
    custom = bool(spec.get("custom"))
    hole.Threaded = False
    hole.ModelThread = False
    hole.Tapered = False
    hole.HoleCutCustomValues = False
    hole.ThreadType = thread
    data = data_dims(spec) if is_data(spec) else None
    if thread == "None":
        diameter = data["hole"] if data else _fraction(spec["size"]) * 25.4
        if custom and kind == "Hole" and spec.get("cdia"):
            diameter = float(spec["cdia"])
        hole.Diameter = diameter
    else:
        fc_size = _freecad_size(thread, spec["size"])
        if fc_size is not None:
            hole.ThreadSize = fc_size
        if has_fit(spec):
            names = FITS.get(thread, FITS["UNC"] if thread in ("UNF", "UNEF") else FITS["ISOMetricProfile"])
            fit = spec.get("fit", "Normal")
            want = names[FIT_NAMES.index(fit)] if fit in FIT_NAMES else names[1]
            if want in hole.getEnumerationsOfProperty("ThreadFit"):
                hole.ThreadFit = want
    cut = "None"
    if kind == "Counterbore":
        cut = CBORE.get(spec["type"], ("", "ISO 4762"))[1]
    elif kind == "Countersink":
        cut = CSK.get(spec["type"], ("", "ISO 10642"))[1]
    if data and kind in ("Counterbore", "Countersink"):
        cut = kind          # FreeCAD's plain Counterbore / Countersink, sized from our table
    if cut in hole.getEnumerationsOfProperty("HoleCutType"):
        hole.HoleCutType = cut
    if data and kind in ("Counterbore", "Countersink"):
        hole.HoleCutDiameter = data["head_d"]
        if kind == "Counterbore":
            hole.HoleCutDepth = data["head_depth"]
        else:
            hole.HoleCutCountersinkAngle = data["head_angle"]
    if kind in ("Counterbore", "Countersink") and custom:
        hole.HoleCutCustomValues = True
        if spec.get("cdia"):
            hole.HoleCutDiameter = float(spec["cdia"])
        if kind == "Counterbore" and spec.get("cdepth"):
            hole.HoleCutDepth = float(spec["cdepth"])
        if kind == "Countersink" and spec.get("cangle"):
            hole.HoleCutCountersinkAngle = float(spec["cangle"])
    if kind == "Counterbore" and spec.get("clearance") and float(spec.get("clearance_value") or 0) > 0:
        base_depth = float(spec["cdepth"]) if custom and spec.get("cdepth") else hole.HoleCutDepth.Value
        hole.HoleCutCustomValues = True
        hole.HoleCutDepth = base_depth + float(spec["clearance_value"])
    if kind == "Hole" and custom and thread != "None" and spec.get("cdia"):
        # A screw clearance with its own through hole diameter is a plain hole.
        hole.ThreadType = "None"
        hole.Diameter = float(spec["cdia"])
    if "Reversed" in hole.PropertiesList:
        hole.Reversed = bool(spec.get("reverse"))
    through = spec.get("end") == "Through All"
    hole.DepthType = "ThroughAll" if through else "Dimension"
    depth = max(float(spec.get("depth") or 10.0), 0.01)
    if kind in ("Counterbore", "Countersink") and depth <= hole.HoleCutDepth.Value:
        depth = hole.HoleCutDepth.Value + nominal(spec)[0]   # a blind hole below its head
    hole.Depth = depth
    hole.DrillPoint = "Flat" if spec["type"] == "Bottoming Tapped Hole" else "Angled"
    if is_tap(spec):
        hole.Threaded = True
        hole.ModelThread = thread_option(spec) == "remove"
        if kind == "Tapered Tap":
            hole.Tapered = True
            hole.TaperedAngle = NPT_TAPER
            if through:
                # FreeCAD's threaded tapered hole narrows to nothing over Through All's long tool ("Could not
                # revolve sketch", features-429): a depth past the part's far side, short of the point
                import math
                base = getattr(hole, "BaseFeature", None)
                reach = base.Shape.BoundBox.DiagonalLength + 1.0 if base is not None and not base.Shape.isNull() else 100.0
                point = 0.9 * (hole.Diameter.Value / 2.0) / math.tan(math.radians(90.0 - NPT_TAPER))
                hole.DepthType = "Dimension"
                hole.Depth = min(reach, point)
        if through:
            hole.ThreadDepthType = "Hole Depth"
        else:
            hole.ThreadDepthType = "Dimension"
            hole.ThreadDepth = min(float(spec.get("tdepth") or hole.Depth.Value), hole.Depth.Value)
    store(hole, spec)


SPEC_PROPERTY = "HoleWizardSpec"


def store(hole, spec):
    ""

    if SPEC_PROPERTY not in hole.PropertiesList:
        hole.addProperty("App::PropertyString", SPEC_PROPERTY, "Hole Wizard",
                         "Hole Wizard choices: standard, type, size, fit (JSON)")
    keep = {k: v for k, v in spec.items() if isinstance(v, (str, int, float, bool)) or v is None}
    if isinstance(spec.get("tolerances"), dict):    # the Tolerance/Precision group's settings go with the hole
        keep["tolerances"] = {k: dict(v) for k, v in spec["tolerances"].items() if isinstance(v, dict)}
    hole.HoleWizardSpec = json.dumps(keep, sort_keys=True)


def stored(hole):
    """The Hole Wizard choices stored on a hole, or None."""
    try:
        text = getattr(hole, SPEC_PROPERTY, "")
        return json.loads(text) if text else None
    except Exception:
        return None


def tree_name(spec):
    ""
    if spec["kind"] == LEGACY:
        return "Hole"
    if spec["kind"] in BASE:
        name = tree_name(dict(spec, kind=BASE[spec["kind"]]))
        if spec["kind"] == "Slot":
            return name.replace("Hole", "Slot")
        return name.replace("CBore for", "CBore Slot for").replace("CSK for", "CSK Slot for")
    kind, size = spec["kind"], spec["size"]
    thread = thread_of(spec)
    if kind in ("Counterbore", "Countersink"):
        table = CBORE if kind == "Counterbore" else CSK
        word = table[spec["type"]][2] if spec["type"] in table else \
            holedata.tree_word(kind, spec["standard"], spec["type"])
        return "%s for %s %s" % ("CBore" if kind == "Counterbore" else "CSK", size, word)
    if kind == "Straight Tap":
        return "%s%s Tapped Hole" % (size, " " + thread if thread in ("UNC", "UNF", "UNEF") else "")
    if kind == "Tapered Tap":
        return "%s Tapered Pipe Tap" % size.strip('"')
    if spec["type"] == "Screw Clearances":
        return "%s Clearance Hole" % size
    if spec["type"] == "Dowel Holes":
        return "%s Dowel Hole" % size
    if spec["type"] == "Tap Drills":
        return "Tap Drill for %s" % size
    if spec["type"] in ("Letter Drill Sizes", "Number Drill Sizes"):
        return "%s (%.2f) Diameter Hole" % (size, nominal(spec)[0])
    if size.endswith('"'):
        return "%s (%.2f) Diameter Hole" % (size.strip('"'), _fraction(size) * 25.4)
    value = size.lstrip("Ø")
    return "%s (%s) Diameter Hole" % (size, value.rstrip("0").rstrip("."))


def _body_of(obj):
    for parent in obj.InList:
        if parent.TypeId == "PartDesign::Body":
            return parent
    return None


def _make_slot(sketch, spec):
    hole_d, head_d, head_depth, head_angle = hole_sizes(spec)
    base = BASE[spec["kind"]]
    if spec.get("custom"):
        if base == "Hole" and spec.get("cdia"):
            hole_d = float(spec["cdia"])
        if base in ("Counterbore", "Countersink") and spec.get("cdia"):
            head_d = float(spec["cdia"])
        if base == "Counterbore" and spec.get("cdepth"):
            head_depth = float(spec["cdepth"])
        if base == "Countersink" and spec.get("cangle"):
            head_angle = float(spec["cangle"])
    if base == "Counterbore" and spec.get("clearance") and float(spec.get("clearance_value") or 0) > 0:
        head_depth += float(spec["clearance_value"])
    through = spec.get("end") == "Through All"
    depth = max(float(spec.get("depth") or 10.0), 0.01)
    if base == "Counterbore" and depth <= head_depth:
        depth = head_depth + hole_d
    length = float(spec.get("slot_length") or 0.0) or hole_d * 2
    slot = holeslot.make(sketch, spec["kind"], hole_d, length, head_d, head_depth, head_angle, through, depth,
                         naming.next_label(sketch.Document, tree_name(spec)))
    if spec.get("slot_angle"):
        try:
            slot.Angle = float(spec["slot_angle"]) % 360.0     # Tab on the Positions tab turned it
        except Exception as _fw_err:
            _fw_log("holespec.py:561", _fw_err)
    sketch.Document.recompute()
    return slot


def _placeable(obj, sub):
    from . import holewizard
    return holewizard.placeable(obj, sub)


def make(sketch, spec):
    """The Hole on the sketch's points, from the Type tab's choices. Returns it."""
    doc = sketch.Document
    body = _body_of(sketch)
    if body is None:
        return None
    doc.openTransaction("Hole Wizard")
    try:
        options = None
        threads = []
        if spec["kind"] == LEGACY:
            hole = holelegacy.make(sketch, spec, naming.next_label(doc, "Hole"))
            doc.recompute()
        elif spec["kind"] in BASE:
            hole = _make_slot(sketch, spec)
        else:
            hole = body.newObject("PartDesign::Hole", "Hole")
            hole.Profile = (sketch, [])
            apply(hole, spec)
            hole.Label = naming.next_label(doc, tree_name(spec))
            doc.recompute()
            if spec.get("end") not in ("Blind", "Through All", None):
                holeends.attach(hole, spec)
                doc.recompute()
            options = holeoptions.make(hole, spec)
            if options is not None:
                doc.recompute()
            if is_tap(spec) and thread_option(spec) == "cosmetic":
                threads = add_cosmetic_threads(options or hole, sketch, spec)
        if hole is not None and spec["kind"] in (LEGACY,) + tuple(BASE):
            store(hole, spec)
        if options is not None:
            doc.recompute()
        base = hole.BaseFeature
        if getattr(Gui, "ActiveDocument", None) is not None:
            if base is not None and base.ViewObject is not None:
                for prop in ("ShapeAppearance", "LineColor", "PointColor", "Transparency", "DisplayMode"):
                    try:
                        setattr(hole.ViewObject, prop, getattr(base.ViewObject, prop))
                    except Exception as _fw_err:
                        _fw_log("holespec.py:611", _fw_err)
                base.ViewObject.Visibility = False
            sketch.ViewObject.Visibility = False
            hole.ViewObject.Visibility = True
            if options is not None and options.ViewObject is not None:
                for prop in ("ShapeAppearance", "LineColor", "PointColor", "Transparency", "DisplayMode"):
                    try:
                        setattr(options.ViewObject, prop, getattr(hole.ViewObject, prop))
                    except Exception as _fw_err:
                        _fw_log("holespec.py:620", _fw_err)
                hole.ViewObject.Visibility = False
                options.ViewObject.Visibility = True
            if hole is not None and spec["kind"] not in (LEGACY,) + tuple(BASE):
                apply_scope(hole, spec)
            for i, each in enumerate(threads):
                if each.ViewObject is None:
                    continue
                shown = options if options is not None else hole
                for prop in ("ShapeAppearance", "LineColor", "PointColor", "Transparency", "DisplayMode"):
                    try:
                        setattr(each.ViewObject, prop, getattr(shown.ViewObject, prop))
                    except Exception as _fw_err:
                        _fw_log("holespec.py:631", _fw_err)
                last = i == len(threads) - 1
                each.ViewObject.Visibility = last
                if last:
                    shown.ViewObject.Visibility = False
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintError("Hole Wizard: %s\n" % error)
        App.Console.PrintLog(traceback.format_exc())
        return None
    doc.commitTransaction()
    return hole


def scope_solids(base):
    """The bodies (solids) a hole could cut: the part as it is before the hole."""
    try:
        return list(base.Shape.Solids) if base is not None else []
    except Exception:
        return []


def apply_scope(hole, spec):
    ""

    try:
        from . import multibody
        everything = bool(spec.get("scope_all", True))
        if everything and multibody.helper_of(hole) is None:
            return
        solids = multibody._base_solids(hole)
        if len(solids) < 2 and multibody.helper_of(hole) is None:
            return
        picks = [int(x) for x in str(spec.get("scope_pick") or "").split(",") if x.strip().isdigit()]
        multibody.set_scope(hole, everything, bool(spec.get("scope_auto", True)),
                            [solids[i] for i in picks if i < len(solids)])
    except Exception as error:
        _fw_log("holespec.py:scope", error)


# ------------------------------------------------------------------ cosmetic thread, callout
def thread_name(spec):
    """(callout thread name, cosmetic thread standard, cosmetic thread size) for a tap spec."""
    kind = _base(spec["kind"])
    major, pitch, name = holedata.thread(kind, spec["standard"], spec["type"], spec["size"])
    if kind == "Tapered Tap":
        return name, "None", ""
    if holedata.is_inch(spec["standard"]):
        return name, "ANSI Inch", name
    p = "%.1f" % pitch if pitch == int(pitch) else "%g" % pitch
    return name, "ISO", "M%gx%s" % (major, p)


def _points(sketch):
    place = sketch.getGlobalPlacement()
    out = []
    for geo in sketch.Geometry:
        if type(geo).__name__ == "Point":
            out.append(place.multVec(App.Vector(geo.X, geo.Y, geo.Z)))
    return out


def entry_edges(feature, sketch, radius):
    """For each point of the hole's sketch, the circular edge (name) nearest it with about this radius."""
    names = []
    edges = list(enumerate(feature.Shape.Edges, 1))
    for point in _points(sketch):
        best = None
        for i, edge in edges:
            curve = getattr(edge, "Curve", None)
            if type(curve).__name__ != "Circle" or abs(curve.Radius - radius) > max(0.25 * radius, 0.05):
                continue
            score = (App.Vector(curve.Center) - point).Length + abs(curve.Radius - radius)
            if best is None or score < best[0]:
                best = (score, "Edge%d" % i)
        if best is not None and best[1] not in names:
            names.append(best[1])
    return names


def add_cosmetic_threads(feature, sketch, spec):
    ""

    try:
        from . import cosmeticthread, simplefeature as sf
    except Exception:
        return []
    doc = feature.Document
    _name, standard, size = thread_name(spec)
    radius = feature.Diameter.Value / 2.0 if hasattr(feature, "Diameter") else nominal(spec)[0] / 2.0
    if getattr(feature, "TypeId", "") != "PartDesign::Hole":
        for each in feature.OutListRecursive:
            if each.TypeId == "PartDesign::Hole":
                radius = each.Diameter.Value / 2.0
                break
    through = spec.get("end") == "Through All"
    depth = float(spec.get("tdepth") or 0) or tap_depths(spec)[1]
    made, picked = [], feature
    known = {f.name for f in getattr(cosmeticthread.SPEC, "fields", [])}
    for edge in entry_edges(picked, sketch, radius)[:24]:
        values = {"Standard": standard, "EndCondition": "Through" if through else "Blind", "Depth": depth}
        if "ThreadClass" in known and thread_class(spec):
            values["ThreadClass"] = thread_class(spec)          # 1B/2B/3B into the thread's callout
        if "WithCallout" in known:
            values["WithCallout"] = bool(spec.get("thread_callout", True))
        if standard == "None":
            values["Diameter"] = holedata.thread(_base(spec["kind"]), spec["standard"], spec["type"],
                                                 spec["size"])[0]
        else:
            values["Size"] = size
        try:
            obj = _new_simple(cosmeticthread.SPEC, sf, feature, {"Edge": [(picked, [edge])]}, values)
        except Exception as error:
            App.Console.PrintLog("Hole Wizard cosmetic thread: %s\n" % error)
            continue
        if obj is not None and not obj.isValid():
            # a thread our Cosmetic Thread cannot follow (a cone): leave the hole as it is
            body = _body_of(obj)
            doc.removeObject(obj.Name)
            if body is not None and body.Tip is None:
                body.Tip = feature
            doc.recompute()
            continue
        if obj is not None:
            made.append(obj)
            feature = obj          # the next thread follows this one in the body
    return made


def _rename(hole, was, spec):
    """Edit Feature: a hole that kept its Hole Wizard name takes the new one (M6 Tapped Hole1 -> M8 Tapped Hole1)."""
    try:
        before = tree_name(was) if was else None
        after = tree_name(spec)
    except Exception as _fw_err:
        _fw_log("holespec.py:741", _fw_err)
        return
    if not before or before == after or not hole.Label.startswith(before):
        return
    number = hole.Label[len(before):]
    if number.isdigit():
        hole.Label = after + number


def threads_of(hole):
    """The Cosmetic Threads the Hole Wizard put on this hole's edges (on the hole or its Hole Options)."""
    try:
        options = holeoptions.existing(hole)
    except Exception:
        options = None
    owners = [o for o in (hole, options) if o is not None]
    out = []
    for obj in hole.Document.Objects:
        if "SizeFor" not in obj.PropertiesList or "Edge" not in obj.PropertiesList:
            continue
        try:
            links = [each[0] for each in obj.Edge]
        except Exception:
            continue
        if any(link in owners for link in links):
            out.append(obj)
    return out


def _drop(obj, show):
    doc = obj.Document
    body = _body_of(obj)
    if body is not None:
        was_tip = body.Tip is obj
        before = obj.BaseFeature if hasattr(obj, "BaseFeature") else None
        for after in obj.InList:
            if getattr(after, "BaseFeature", None) is obj:
                after.BaseFeature = before
        body.removeObject(obj)
        if was_tip:
            body.Tip = before or show
    doc.removeObject(obj.Name)


def sync_threads(hole, spec):
    ""


    try:
        from . import cosmeticthread, simplefeature as sf
    except Exception:
        return
    threads = threads_of(hole)
    options = holeoptions.existing(hole)
    picked = options or hole
    try:
        sketch = hole.Profile[0] if isinstance(hole.Profile, tuple) else hole.Profile
    except Exception:
        sketch = None
    want = is_tap(spec) and spec.get("cosmetic", True) and sketch is not None
    if not want:
        for obj in reversed(threads):
            _drop(obj, picked)
        if threads and App.GuiUp and picked.ViewObject is not None:
            picked.ViewObject.Visibility = True
        return
    body = _body_of(hole)
    tip = body.Tip if body is not None else None
    if not threads:
        if body is not None and tip is not picked:
            body.Tip = picked
        made = add_cosmetic_threads(picked, sketch, spec)
        if body is not None and tip is not picked and tip is not None:
            body.Tip = tip
            for each in made:
                if each.ViewObject is not None:
                    each.ViewObject.Visibility = False
            return
        if made and App.GuiUp and picked.ViewObject is not None:
            for i, each in enumerate(made):
                if each.ViewObject is not None:
                    each.ViewObject.Visibility = i == len(made) - 1
            picked.ViewObject.Visibility = False
        return
    _name, standard, size = thread_name(spec)
    through = spec.get("end") == "Through All"
    depth = float(spec.get("tdepth") or 0) or tap_depths(spec)[1]
    edges = entry_edges(picked, sketch, hole.Diameter.Value / 2.0)
    for obj, edge in zip(threads, edges):
        obj.Edge = [(picked, [edge])]
        obj.Standard = standard
        if standard == "None":
            obj.Diameter = holedata.thread(_base(spec["kind"]), spec["standard"], spec["type"], spec["size"])[0]
        else:
            try:
                obj.Size = size
            except Exception as _fw_err:
                _fw_log("holespec.py:836", _fw_err)
        obj.EndCondition = "Through" if through else "Blind"
        obj.Depth = depth
        obj.SizeFor = hole.Diameter.Value
    for obj in reversed(threads[len(edges):]):
        _drop(obj, picked)
    last = threads[min(len(threads), len(edges)) - 1] if edges else picked
    extra = edges[len(threads):]
    if extra and body is not None:
        body.Tip = last
    for edge in extra:
        values = {"Standard": standard, "EndCondition": "Through" if through else "Blind", "Depth": depth}
        if standard != "None":
            values["Size"] = size
        last = _new_simple(cosmeticthread.SPEC, sf, last, {"Edge": [(picked, [edge])]}, values) or last
    if extra and body is not None and tip is not None and tip not in threads:
        body.Tip = tip


def _new_simple(spec, sf, after, picks, values):
    """simplefeature.make without its own transaction (it is part of the Hole Wizard's one)."""
    body = _body_of(after)
    if body is None:
        return None
    obj = body.newObject(spec.type, spec.internal)
    sf.Feature(obj, spec)
    if App.GuiUp and Gui.ActiveDocument is not None:
        sf.View(obj.ViewObject)
    obj.Label = naming.next_label(after.Document, spec.label)
    for name, value in list(picks.items()) + list(values.items()):
        setattr(obj, name, value)
    after.Document.recompute()
    return obj


def make_on_points(body, points, spec):
    ""

    import Part
    doc = body.Document
    holes = []
    before = set(o.Name for o in doc.Objects)
    for obj, sub, point in points:
        try:
            face = obj.Shape.getElement(sub)
            u, v = face.Surface.parameter(point)
            normal = App.Vector(face.normalAt(u, v)).normalize()
            if body.Shape.isInside(point + normal * 0.05, 1e-6, True):
                normal = normal * -1           # the normal points out of the material
        except Exception as error:
            App.Console.PrintError("Hole Wizard 3D Sketch: %s\n" % error)
            continue
        doc.openTransaction("Hole Wizard")
        try:
            plane = body.newObject("PartDesign::Plane", "HolePlane")
            plane.Label = naming.next_label(doc, "Hole Plane")
            plane.MapMode = "Deactivated"
            plane.Placement = App.Placement(point, App.Rotation(App.Vector(0, 0, 1), normal))
            sketch = body.newObject("Sketcher::SketchObject", "HoleSketch")
            sketch.Label = naming.next_label(doc, "Hole Sketch")
            sketch.AttachmentSupport = [(plane, "")]
            sketch.MapMode = "FlatFace"
            sketch.addGeometry(Part.Point(App.Vector(0, 0, 0)))
            doc.recompute()
            if App.GuiUp and plane.ViewObject is not None:
                plane.ViewObject.Visibility = False
            doc.commitTransaction()
        except Exception as error:
            doc.abortTransaction()
            App.Console.PrintError("Hole Wizard 3D Sketch: %s\n" % error)
            continue
        hole = make(sketch, spec)
        if hole is not None:
            holes.append(hole)
    if len(holes) > 1:

        try:
            from . import holegroup
            members = [o for o in body.Group if o.Name not in before]
            doc.openTransaction("Hole Wizard")
            try:
                holegroup.make(body, holes, members)
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
        except Exception as error:
            doc.abortTransaction()
            App.Console.PrintError("Hole Wizard: %s\n" % error)
    return holes


def sketch_positions(sketch):
    ""


    out = []

    def add(p):
        p = App.Vector(p.x, p.y, 0)
        if all((p - q).Length > 1e-6 for q in out):
            out.append(p)
    for geo in sketch.Geometry:
        name = type(geo).__name__
        try:
            if name == "Point":
                add(App.Vector(geo.X, geo.Y, geo.Z))
            elif name in ("Circle", "Ellipse"):
                add(geo.Center)
            elif hasattr(geo, "StartPoint"):
                add(geo.StartPoint)
                add(geo.EndPoint)
        except Exception as _fw_err:
            _fw_log("holespec.py:954", _fw_err)
            continue
    return out


def make_from_existing(source, spec, skip=()):
    """The holes at an existing 2D sketch's positions (sketch_positions), leaving out the instance
    numbers in skip (Instances to Skip, counted from 0). The points go on a Hole Sketch on the same
    plane, the source sketch is kept and hidden. Returns the hole."""
    import Part
    body = _body_of(source)
    if body is None:
        return None
    doc = source.Document
    points = [p for i, p in enumerate(sketch_positions(source)) if i not in set(skip)]
    if not points:
        return None
    doc.openTransaction("Hole Wizard")
    try:
        sketch = body.newObject("Sketcher::SketchObject", "HoleSketch")
        sketch.Label = naming.next_label(doc, "Hole Sketch")
        for prop in ("AttachmentSupport", "MapMode", "MapReversed", "AttachmentOffset"):
            try:
                setattr(sketch, prop, getattr(source, prop))
            except Exception as _fw_err:
                _fw_log("holespec.py:969", _fw_err)
        if source.MapMode == "Deactivated" or not source.AttachmentSupport:
            sketch.Placement = source.Placement
        for p in points:
            sketch.addGeometry(Part.Point(p))
        doc.recompute()
        if App.GuiUp and source.ViewObject is not None:
            source.ViewObject.Visibility = False
        doc.commitTransaction()
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintError("Hole Wizard Existing 2D Sketch: %s\n" % error)
        return None
    return make(sketch, spec)


def instances(hole):
    try:
        sketch = hole.Profile[0] if hasattr(hole, "Profile") else hole.Positions    # slots: their Positions sketch
        return max(1, len(_points(sketch)))
    except Exception:
        return 1


def callout_lines(hole):
    """The Hole Callout of a Hole Wizard hole, from its HoleWizardSpec: "4X ⌀6.60 THRU ALL" and
    "⌴ ⌀11.00 ↧ 6.40" for a counterbore, the tap drill and thread for a tap. None for other holes."""
    spec = stored(hole)
    if not spec or spec.get("kind") == LEGACY:
        return None
    kind = _base(spec["kind"])
    try:
        d = data_dims(spec) if is_data(spec) or is_tap(spec) else {}
    except Exception:
        d = {}
    def value(prop, fallback=0.0):
        try:
            return getattr(hole, prop).Value
        except Exception:
            return fallback
    if hasattr(hole, "Diameter"):
        d["hole"] = value("Diameter")
        if kind in ("Counterbore", "Countersink"):
            # a Hole has HoleCut*, a counterbore/countersink slot Head* (its callout read 0.00 before)
            d["head_d"] = value("HoleCutDiameter", value("HeadDiameter", d.get("head_d", 0.0)))
            d["head_depth"] = value("HoleCutDepth", value("HeadDepth", d.get("head_depth", 0.0)))
            d["head_angle"] = value("HoleCutCountersinkAngle", value("HeadAngle", d.get("head_angle", 90.0)))
        if is_tap(spec):
            d["tap_drill"] = d["hole"]
    d.setdefault("head_d", 0.0)
    d.setdefault("head_depth", 0.0)
    d.setdefault("head_angle", 90.0)
    if is_tap(spec):
        d["name"] = thread_name(spec)[0]
    through = spec.get("end") == "Through All"
    depth = value("Depth", float(spec.get("depth") or 0))
    tdepth = value("ThreadDepth", float(spec.get("tdepth") or 0)) if is_tap(spec) else 0.0
    lines = holedata.callout(kind, spec["standard"],
                             spec["type"], spec["size"], d, through, depth, tdepth)
    cls = thread_class(spec)
    if is_tap(spec) and cls and len(lines) > 1 and " - 2B" in lines[1]:
        lines[1] = lines[1].replace(" - 2B", " - " + cls)
    tols = spec.get("tolerances") or {}
    if tols:
        lines = _apply_tolerances(lines, spec, d, depth, tols)
    count = instances(hole)
    if count > 1:
        lines[0] = "%dX %s" % (count, lines[0])
    return lines



TOL_TYPES = ("None", "Basic", "Bilateral", "Limit", "Symmetric", "MIN", "MAX")
PRECISIONS = (".12 (Document)", ".1", ".12", ".123", ".1234")


def callout_values(spec):
    ""
    kind = _base(spec.get("kind", "Hole")) if spec.get("kind") != LEGACY else "Hole"
    through = spec.get("end") == "Through All"
    try:
        tap = is_tap(spec)
    except Exception:
        tap = False
    out = ["Tap Drill Diameter" if tap else ("Thru Hole Diameter" if through else "Hole Diameter")]
    if not through:
        out.append("Hole Depth")
    if kind == "Counterbore":
        out += ["Counterbore Diameter", "Counterbore Depth"]
    elif kind == "Countersink":
        out += ["Countersink Diameter", "Countersink Angle"]
    return out


def tolerance_text(number, tol, angle=False):
    """number with its tolerance as the callout shows it: 6.60 +0.10/-0.05, 6.60 ±0.05, 6.70/6.55..."""
    tol = tol or {}
    precision = tol.get("precision") or PRECISIONS[0]
    document = precision == PRECISIONS[0]
    digits = 2 if document else len(precision.split()[0]) - 1
    unit = "°" if angle else ""
    if angle and document:
        f = lambda x: "%g" % x
    else:
        f = lambda x: "%.*f" % (digits, x)
    plus, minus = float(tol.get("plus") or 0.0), float(tol.get("minus") or 0.0)
    kind = tol.get("type") or "None"
    text = f(number) + unit
    if kind == "Basic":
        return "[%s]" % text
    if kind == "Bilateral":
        return "%s +%s/-%s" % (text, f(plus), f(minus))
    if kind == "Symmetric":
        return "%s ±%s" % (text, f(plus))
    if kind == "Limit":
        return "%s/%s" % (f(number + plus) + unit, f(number - minus) + unit)
    if kind in ("MIN", "MAX"):
        return "%s %s" % (text, kind)
    return text


def _apply_tolerances(lines, spec, d, depth, tols):
    """The callout lines with each toleranced value's number replaced by its tolerance text."""
    first = "tap_drill" if "tap_drill" in d and is_tap(spec) else "hole"
    where = {"Hole Diameter": (0, "⌀", d.get(first), False), "Thru Hole Diameter": (0, "⌀", d.get(first), False),
             "Tap Drill Diameter": (0, "⌀", d.get(first), False), "Hole Depth": (0, "↧ ", depth, False),
             "Counterbore Diameter": (1, "⌀", d.get("head_d"), False),
             "Counterbore Depth": (1, "↧ ", d.get("head_depth"), False),
             "Countersink Diameter": (1, "⌀", d.get("head_d"), False),
             "Countersink Angle": (1, "X ", d.get("head_angle"), True)}
    lines = list(lines)
    for name in callout_values(spec):
        tol = tols.get(name)
        if not tol or ((tol.get("type") or "None") == "None" and (tol.get("precision") or PRECISIONS[0]) == PRECISIONS[0]):
            continue
        i, mark, number, angle = where[name]
        if number is None or i >= len(lines):
            continue
        old = mark + ("%g°" % number if angle else "%.2f" % number)
        if old in lines[i]:
            lines[i] = lines[i].replace(old, mark + tolerance_text(number, tol, angle), 1)
    return lines


def callout_text(hole):
    lines = callout_lines(hole)
    return "\n".join(lines) if lines else None


# ------------------------------------------------------------------ icons
def _kind_icon(kind):
    """Cross-section of each hole type: grey part, white hole (drawn, no art copied)."""
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pix = _hidpi.canvas(32, 32)
    pix.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor("#404040"), 1))
    p.setBrush(QtGui.QColor("#9aa4ad"))
    p.drawRect(2, 6, 28, 22)
    hole = QtGui.QPolygonF()
    pts = {
        "Counterbore": [(8, 6), (24, 6), (24, 13), (20, 13), (20, 24), (16, 27), (12, 24), (12, 13), (8, 13)],
        "Countersink": [(7, 6), (25, 6), (20, 12), (20, 24), (16, 27), (12, 24), (12, 12)],
        "Hole": [(12, 6), (20, 6), (20, 24), (16, 27), (12, 24)],
        "Straight Tap": [(11, 6), (21, 6), (21, 24), (16, 27), (11, 24)],
        "Tapered Tap": [(10, 6), (22, 6), (19, 24), (16, 27), (13, 24)],
        "Legacy Hole": [(12, 6), (20, 6), (20, 28), (12, 28)],
        "Counterbore Slot": [(4, 6), (28, 6), (28, 13), (24, 13), (24, 28), (8, 28), (8, 13), (4, 13)],
        "Countersink Slot": [(4, 6), (28, 6), (24, 12), (24, 28), (8, 28), (8, 12)],
        "Slot": [(6, 6), (26, 6), (26, 28), (6, 28)],
    }[kind]
    for x, y in pts:
        hole.append(QtCore.QPointF(x, y))
    p.setBrush(QtGui.QColor("#ffffff"))
    p.drawPolygon(hole)
    if kind in ("Straight Tap", "Tapered Tap"):
        p.setPen(QtGui.QPen(QtGui.QColor("#1a5fb4"), 1))
        for i, y in enumerate(range(8, 23, 3)):
            inset = (y - 6) * 3 / 18 if kind == "Tapered Tap" else 0
            p.drawLine(QtCore.QPointF(10 + inset, y), QtCore.QPointF(12 + inset, y + 1.5))
            p.drawLine(QtCore.QPointF(22 - inset, y), QtCore.QPointF(20 - inset, y + 1.5))
    p.end()
    return QtGui.QIcon(pix)


def _favorite_icon(key):
    """Small drawn pictures for the Favorite buttons."""
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pix = _hidpi.canvas(18, 18)
    pix.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    star = QtGui.QPolygonF([QtCore.QPointF(9, 1), QtCore.QPointF(11, 7), QtCore.QPointF(17, 7), QtCore.QPointF(12, 11),
                            QtCore.QPointF(14, 17), QtCore.QPointF(9, 13), QtCore.QPointF(4, 17), QtCore.QPointF(6, 11),
                            QtCore.QPointF(1, 7), QtCore.QPointF(7, 7)])
    p.setPen(QtGui.QPen(QtGui.QColor("#7a5c00"), 1))
    p.setBrush(QtGui.QColor("#f5c400"))
    p.drawPolygon(star)
    mark = {"Defaults": None, "Add": "+", "Delete": "x", "Save": "v", "Load": "^"}[key]
    if key == "Defaults":
        p.setPen(QtGui.QPen(QtGui.QColor("#c00000"), 2))
        p.drawLine(2, 16, 16, 2)
    elif mark:
        p.setPen(QtGui.QPen(QtGui.QColor("#1a5fb4"), 2))
        font = p.font()
        font.setBold(True)
        font.setPixelSize(11)
        p.setFont(font)
        p.drawText(QtCore.QRectF(8, 7, 10, 11), QtCore.Qt.AlignCenter, mark)
    p.end()
    return QtGui.QIcon(pix)


# ------------------------------------------------------------------ the panel
def _fw_retyped(spin):
    """True when the field's text is not what its value shows: a number typed and not taken yet.
    An untouched field is left alone (taking its rounded text again moved linked values: Flex's
    Radius 26.74 turned a typed Angle back to 89.99)."""
    try:
        return spin.text() != spin.prefix() + spin.textFromValue(spin.value()) + spin.suffix()
    except Exception:
        return True


def _length(parent, name):
    box = QtWidgets.QDoubleSpinBox(parent)
    box.setObjectName(name)
    box.setRange(0.0, 1e6)
    box.setDecimals(2)
    box.setSuffix(" mm")
    box.setKeyboardTracking(False)
    return box


def section_picture(ltype, values, w=220, h=150):
    ""
    from PySide import QtGui
    pix = QtGui.QPixmap(w, h)
    pix.fill(QtGui.QColor(255, 255, 255))
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    cx, top, bottom = w // 2, 20, h - 20
    r = 18
    head_r, head_d = 30, 30
    hatch = QtGui.QBrush(QtGui.QColor(150, 150, 150), QtCore.Qt.BDiagPattern)
    pen = QtGui.QPen(QtGui.QColor(40, 40, 40), 1.5)
    p.setPen(pen)
    # the hole's outline (right half mirrored): body hatched on both sides
    def side(sign):
        pts = [QtCore.QPointF(cx + sign * 100, top)]
        if ltype in ("Counterbored", "Counterdrilled"):
            pts += [QtCore.QPointF(cx + sign * head_r, top), QtCore.QPointF(cx + sign * head_r, top + head_d),
                    QtCore.QPointF(cx + sign * r, top + head_d + (8 if ltype == "Counterdrilled" else 0))]
        elif ltype == "Countersunk":
            pts += [QtCore.QPointF(cx + sign * head_r, top), QtCore.QPointF(cx + sign * r, top + head_r - r)]
        else:
            pts += [QtCore.QPointF(cx + sign * r, top)]
        tip = r - (8 if ltype == "Tapered" else 0)
        pts += [QtCore.QPointF(cx + sign * tip, bottom - 12), QtCore.QPointF(cx, bottom),
                QtCore.QPointF(cx, bottom + 15), QtCore.QPointF(cx + sign * 100, bottom + 15)]
        return QtGui.QPolygonF(pts)
    for sign in (-1, 1):
        p.setBrush(hatch)
        p.drawPolygon(side(sign))
    p.setBrush(QtCore.Qt.NoBrush)
    p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 200), 1))
    font = p.font()
    font.setPointSize(7)
    p.setFont(font)

    def fmt(key):
        v = values.get(key)
        if v is None:
            return None
        return ("%g°" % v) if ("angle" in key or "taper" in key) else ("%g" % v)
    if fmt("legacy_dia"):
        y = bottom - 30
        p.drawLine(cx - r, y, cx + r, y)
        p.drawText(QtCore.QRectF(cx - 40, y - 14, 80, 12), QtCore.Qt.AlignCenter, "Ø" + fmt("legacy_dia"))
    if fmt("legacy_head_dia"):
        p.drawLine(cx - head_r, top - 6, cx + head_r, top - 6)
        p.drawText(QtCore.QRectF(cx - 40, 2, 80, 12), QtCore.Qt.AlignCenter, "Ø" + fmt("legacy_head_dia"))
    if fmt("legacy_head_depth"):
        x = cx + head_r + 8
        p.drawLine(x, top, x, top + head_d)
        p.drawText(QtCore.QRectF(x + 2, top + head_d / 2 - 6, 60, 12), QtCore.Qt.AlignLeft, fmt("legacy_head_depth"))
    if fmt("depth"):
        x = cx - 100 + 10
        p.drawLine(x, top, x, bottom - 12)
        p.drawText(QtCore.QRectF(x + 3, (top + bottom) / 2 - 6, 60, 12), QtCore.Qt.AlignLeft, fmt("depth"))
    for key in ("legacy_angle", "legacy_taper"):
        if fmt(key):
            p.drawText(QtCore.QRectF(cx + 20, bottom - 12, 80, 12), QtCore.Qt.AlignLeft, fmt(key))
    p.end()
    return pix


class _FoldHeader(QtWidgets.QWidget):
    ""


    def __init__(self, label, body):
        super().__init__(label.parentWidget())
        self.setObjectName("SWHoleFold_" + re.sub(r"\W", "", label.text()))   # no "/" (Tolerance/Precision): Qt style sheets cannot parse it
        self.label, self.body = label, body
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 6, 0, 2)
        label.setParent(self)
        row.addWidget(label, 1)
        from . import pmlayout
        self._set = pmlayout.set_chevron
        self.open = True
        self.chevron = pmlayout._chevron(self)
        self._set(self.chevron, True)
        self.chevron.clicked.connect(self.toggle)
        row.addWidget(self.chevron)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setStyleSheet("#%s { border-top: 1px solid #c8c8c8; }" % self.objectName())
        label.installEventFilter(self)

    def toggle(self):
        self.open = not self.open
        self.body.setVisible(self.open)
        self._set(self.chevron, self.open)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        if obj is self.label and event.type() in (QtCore.QEvent.ShowToParent, QtCore.QEvent.HideToParent):
            on = event.type() == QtCore.QEvent.ShowToParent
            self.setVisible(on)
            if not on:
                self.body.setVisible(False)
            elif self.open:
                self.body.setVisible(True)
        return False


def _fold(lay, titles, stop=()):
    """Turn each bold title in lay (and the items after it, up to the next title or a stop widget)
    into a folding group: header + body."""
    items = []
    while lay.count():
        items.append(lay.takeAt(0))
    sections, current = [], None
    for item in items:
        w = item.widget()
        if isinstance(w, QtWidgets.QLabel) and w.text() in titles:
            current = (w, [])
            sections.append(current)
            continue
        if w is not None and w in stop:
            current = None
        if current is None:
            sections.append((None, item))
        else:
            current[1].append(item)
    parent = lay.parentWidget()
    for head, rest in sections:
        if head is None:
            w = rest.widget()
            if w is not None:
                lay.addWidget(w)
            elif rest.layout() is not None:
                rest.layout().setParent(None)
                lay.addLayout(rest.layout())
            else:
                lay.addItem(rest)
            continue
        body = QtWidgets.QWidget(parent)
        blay = QtWidgets.QVBoxLayout(body)
        blay.setContentsMargins(0, 0, 0, 0)
        for item in rest:
            w = item.widget()
            if w is not None:
                w.setParent(body)
                blay.addWidget(w)
            elif item.layout() is not None:
                item.layout().setParent(None)
                blay.addLayout(item.layout())
            else:
                blay.addItem(item)
        head.setParent(parent)
        lay.addWidget(_FoldHeader(head, body))
        lay.addWidget(body)


def _bold(parent, text):
    label = QtWidgets.QLabel(text, parent)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


class _Observer:
    def __init__(self, panel):
        self.panel = panel

    def addSelection(self, doc, obj, sub, pnt):
        QtCore.QTimer.singleShot(0, self.panel.picked)


_active = None


class HoleSpecPanel:
    """The Hole Wizard's Type tab and Positions tab (a FreeCAD task panel)."""

    def __init__(self, body, face=None, on_positions=None, hole=None, sketch=None):
        self.body = body
        self.face = face                    # (object, "FaceN") picked before or on the panel
        self.on_positions = on_positions    # callable(obj, sub, spec): starts the points sketch
        self.sketch = sketch                # a sketch picked first: its points are the positions
        self.hole = hole                    # Edit Feature: the hole whose choices are shown and changed
        self.spec = dict(DEFAULT)
        self.spec.update((stored(hole) if hole is not None else None) or last())
        if hole is None:
            self.spec["reverse"] = False        # Reverse Direction is the hole's own, not remembered
            self.spec["tolerances"] = {}        # so are its tolerances
            self.spec["scope_all"], self.spec["scope_auto"], self.spec["scope_pick"] = True, True, ""   # and its Feature Scope
        self.opened = False
        self.done = False
        self._busy = False
        self.form = QtWidgets.QWidget()
        self.form.setObjectName(PANEL)
        self.form.setWindowTitle(TITLE)
        self.form.setProperty("swstyle_pm_title", TITLE)
        self.form.setProperty("swstyle_pm_icon", ICON)
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.setContentsMargins(4, 4, 4, 4)
        self.tabs = QtWidgets.QTabBar(self.form)
        self.tabs.setObjectName(PANEL + "Tabs")
        self.tabs.addTab(QtGui.QIcon(_kind_icon("Counterbore")), "Type")
        self.tabs.addTab(Gui.getIcon("Sketcher_CreatePoint") if hasattr(Gui, "getIcon") else QtGui.QIcon(),
                         "Positions")
        self.tabs.setExpanding(False)
        lay.addWidget(self.tabs, 0, QtCore.Qt.AlignLeft)
        self.pages = QtWidgets.QStackedWidget(self.form)
        lay.addWidget(self.pages)
        self.pages.addWidget(self._type_page())
        self.pages.addWidget(self._positions_page())
        self._load()
        self.tabs.currentChanged.connect(self._tab)
        self.observer = _Observer(self)
        Gui.Selection.addObserver(self.observer)
        global _active
        _active = self
        self._note_face()

    # ----------------------------------------------------------- the Type tab
    def _type_page(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        self._favorite_rows(page, lay)
        lay.addWidget(_bold(page, "Hole Type"))
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(2)
        self.kinds = QtWidgets.QButtonGroup(page)
        self.kind_buttons = {}
        for i, kind in enumerate(KINDS + SLOT_KINDS):
            button = QtWidgets.QToolButton(page)
            button.setObjectName("SWHoleKind_" + kind.replace(" ", ""))
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setIcon(_kind_icon(kind))
            button.setIconSize(QtCore.QSize(28, 28))
            button.setToolTip(kind)
            grid.addWidget(button, i // 3, i % 3)
            if kind in LATER_KINDS:
                button.hide()           # a hole type that cannot be made is not shown (no dead controls)
                button.setToolTip(kind + ": " + NOT_YET)
                continue
            self.kinds.addButton(button)
            self.kind_buttons[kind] = button
            button.clicked.connect(lambda checked=False, k=kind: self._set_kind(k))
        row = QtWidgets.QHBoxLayout()
        row.addLayout(grid)
        row.addStretch(1)
        lay.addLayout(row)
        self.labels = {}
        self.legacy_box = QtWidgets.QWidget(page)
        llay = QtWidgets.QFormLayout(self.legacy_box)
        llay.setContentsMargins(0, 0, 0, 0)
        self.legacy_type = QtWidgets.QComboBox(self.legacy_box)
        self.legacy_type.setObjectName(PANEL + "LegacyType")
        self.legacy_type.addItems(list(holelegacy.TYPES))
        llay.addRow(QtWidgets.QLabel("Type:", self.legacy_box), self.legacy_type)
        self.legacy_fields, self.legacy_labels = {}, {}
        for key, text, kind in (("legacy_dia", "Hole Diameter", "length"), ("legacy_head_dia", "C-Bore Diameter", "length"),
                                ("legacy_head_depth", "C-Bore Depth", "length"), ("legacy_angle", "C-Sink Angle", "angle"),
                                ("legacy_taper", "Taper Angle", "angle")):
            if kind == "length":
                field = _length(self.legacy_box, PANEL + key.title().replace("_", ""))
            else:
                field = QtWidgets.QDoubleSpinBox(self.legacy_box)
                field.setObjectName(PANEL + key.title().replace("_", ""))
                field.setRange(0.5, 179.0)
                field.setSuffix(" °")
                field.setKeyboardTracking(False)
            label = QtWidgets.QLabel(text, self.legacy_box)
            llay.addRow(label, field)
            self.legacy_fields[key], self.legacy_labels[key] = field, label

        # Value / Dimension table edited in place); the form rows above stay as the values' store
        for key in self.legacy_fields:
            self.legacy_fields[key].hide()
            self.legacy_labels[key].hide()
        self.legacy_picture = QtWidgets.QLabel(self.legacy_box)
        self.legacy_picture.setObjectName(PANEL + "LegacySection")
        self.legacy_picture.setAlignment(QtCore.Qt.AlignCenter)
        llay.addRow(self.legacy_picture)
        llay.addRow(_bold(self.legacy_box, "Section Dimensions"))
        self.legacy_table = QtWidgets.QTableWidget(0, 2, self.legacy_box)
        self.legacy_table.setObjectName(PANEL + "SectionDimensions")
        self.legacy_table.setHorizontalHeaderLabels(["Value", "Dimension"])
        self.legacy_table.verticalHeader().hide()
        self.legacy_table.horizontalHeader().setStretchLastSection(True)
        self.legacy_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.legacy_table.itemChanged.connect(self._legacy_cell)
        llay.addRow(self.legacy_table)
        self._legacy_rows = []
        lay.addWidget(self.legacy_box)
        self.legacy_box.hide()
        self.standard = self._combo(page, lay, "Standard:", PANEL + "Standard")
        self.standard.setToolTip("Hole standard (ISO, ANSI...)")
        self.kind_type = self._combo(page, lay, "Type:", PANEL + "Type")
        self.kind_type.setToolTip("Fastener type the hole is made for")

        self.spec_title = _bold(page, "Hole Specifications")
        lay.addWidget(self.spec_title)
        self.size = self._combo(page, lay, "Size:", PANEL + "Size")
        self.size.setToolTip("Fastener size")
        self.legacy_type.activated.connect(lambda i: self._changed("legacy"))
        for field in self.legacy_fields.values():
            field.valueChanged.connect(lambda v: self._changed("value"))
        self.fit_label = QtWidgets.QLabel("Fit:", page)
        lay.addWidget(self.fit_label)
        self.fit = QtWidgets.QComboBox(page)
        self.fit.setObjectName(PANEL + "Fit")
        self.fit.addItems(FIT_NAMES)
        lay.addWidget(self.fit)
        self.slot_label = QtWidgets.QLabel("Slot length:", page)
        lay.addWidget(self.slot_label)
        self.slot = _length(page, PANEL + "SlotLength")
        self.slot.setToolTip("Overall length of the slot, end to end")
        lay.addWidget(self.slot)
        self.custom = QtWidgets.QCheckBox("Show custom sizing", page)
        self.custom.setObjectName(PANEL + "Custom")
        self.custom.setToolTip("Show the hole dimensions to change them")
        lay.addWidget(self.custom)
        self.custom_box = QtWidgets.QWidget(page)
        grid = QtWidgets.QFormLayout(self.custom_box)
        grid.setContentsMargins(12, 0, 0, 0)
        self.cdia = _length(self.custom_box, PANEL + "CustomDiameter")
        self.cdepth = _length(self.custom_box, PANEL + "CustomDepth")
        self.cangle = QtWidgets.QDoubleSpinBox(self.custom_box)
        self.cangle.setObjectName(PANEL + "CustomAngle")
        self.cangle.setRange(1.0, 179.0)
        self.cangle.setSuffix(" °")
        self.cangle.setKeyboardTracking(False)
        self.cdia_label = QtWidgets.QLabel("C-Bore Diameter", self.custom_box)
        self.cdepth_label = QtWidgets.QLabel("C-Bore Depth", self.custom_box)
        self.cangle_label = QtWidgets.QLabel("C-Sink Angle", self.custom_box)
        grid.addRow(self.cdia_label, self.cdia)
        grid.addRow(self.cdepth_label, self.cdepth)
        grid.addRow(self.cangle_label, self.cangle)
        self.restore = QtWidgets.QPushButton("Restore Default Values", self.custom_box)
        self.restore.setObjectName(PANEL + "RestoreDefaults")
        self.restore.clicked.connect(self._restore_defaults)
        grid.addRow(self.restore)
        lay.addWidget(self.custom_box)

        lay.addWidget(_bold(page, "End Condition"))
        self.end = QtWidgets.QComboBox(page)
        self.end.setObjectName(PANEL + "End")
        self.end.setToolTip("How deep the hole goes")
        self.end.addItems(list(holeends.ENDS))

        self.end_flip = QtWidgets.QToolButton(page)
        self.end_flip.setObjectName(PANEL + "ReverseDirection")
        self.end_flip.setCheckable(True)
        self.end_flip.setToolTip("Reverse Direction")
        try:
            from . import pmvalues
            self.end_flip.setIcon(pmvalues.reverse_icon())
            self.end_flip.setIconSize(QtCore.QSize(16, 16))
        except Exception:
            self.end_flip.setText("\u21c5")
        end_row = QtWidgets.QHBoxLayout()
        end_row.addWidget(self.end_flip)
        end_row.addWidget(self.end, 1)
        lay.addLayout(end_row)
        # Up To Vertex / Up To Surface / Offset From Surface: the picked vertex or face, the offset
        self.end_target_label = QtWidgets.QLabel("Face/Plane", page)
        lay.addWidget(self.end_target_label)
        self.end_target = QtWidgets.QLineEdit(page)
        self.end_target.setObjectName(PANEL + "EndTarget")
        self.end_target.setReadOnly(True)
        self.end_target.setToolTip("Click the vertex, face or plane the hole goes up to")
        lay.addWidget(self.end_target)
        self.end_offset_label = QtWidgets.QLabel("Offset distance", page)
        lay.addWidget(self.end_offset_label)
        self.end_offset = _length(page, PANEL + "EndOffset")
        lay.addWidget(self.end_offset)
        self.end_reverse = QtWidgets.QCheckBox("Reverse offset", page)
        self.end_reverse.setObjectName(PANEL + "EndReverse")
        lay.addWidget(self.end_reverse)
        self.depth_label = QtWidgets.QLabel("Depth", page)
        lay.addWidget(self.depth_label)
        self.depth = _length(page, PANEL + "Depth")
        self.depth.setToolTip("Blind hole depth")
        lay.addWidget(self.depth)
        self.tdepth_label = QtWidgets.QLabel("Thread depth", page)
        lay.addWidget(self.tdepth_label)
        self.tdepth = _length(page, PANEL + "ThreadDepth")
        lay.addWidget(self.tdepth)

        self.options = QtWidgets.QWidget(page)
        olay = QtWidgets.QVBoxLayout(self.options)
        olay.setContentsMargins(0, 0, 0, 0)
        olay.addWidget(_bold(self.options, "Options"))
        self.cosmetic = QtWidgets.QRadioButton("Cosmetic thread", self.options)
        self.cosmetic.setObjectName(PANEL + "Cosmetic")
        self.cosmetic.setToolTip("The hole at the tap drill size, with a Cosmetic Thread drawn in it")
        self.with_callout = QtWidgets.QCheckBox("With thread callout", self.options)
        self.with_callout.setObjectName(PANEL + "ThreadCallout")
        self.with_callout.setToolTip("The Cosmetic Thread carries the thread callout (shown in drawings)")
        self.with_callout.setStyleSheet("margin-left: 18px;")
        self.remove = QtWidgets.QRadioButton("Remove thread", self.options)
        self.remove.setObjectName(PANEL + "RemoveThread")
        self.remove.setToolTip("The thread modelled in the hole")
        self.tapdrill = QtWidgets.QRadioButton("Tap drill diameter", self.options)
        self.tapdrill.setObjectName(PANEL + "TapDrill")
        self.tapdrill.setToolTip("The hole at the tap drill size, no thread shown")
        olay.addWidget(self.cosmetic)
        olay.addWidget(self.with_callout)
        olay.addWidget(self.remove)
        olay.addWidget(self.tapdrill)
        self.thread_class_row = QtWidgets.QWidget(self.options)
        class_lay = QtWidgets.QHBoxLayout(self.thread_class_row)
        class_lay.setContentsMargins(0, 0, 0, 0)
        class_lay.addWidget(QtWidgets.QLabel("Thread class:", self.thread_class_row))
        self.thread_class = QtWidgets.QComboBox(self.thread_class_row)
        self.thread_class.setObjectName(PANEL + "ThreadClass")
        self.thread_class.addItems(list(THREAD_CLASSES))
        self.thread_class.setToolTip("ANSI Inch internal thread class, in the hole callout")
        class_lay.addWidget(self.thread_class)
        class_lay.addStretch(1)
        olay.addWidget(self.thread_class_row)
        self.option_boxes, self.option_rows, self.option_fields = {}, {}, {}
        for name in ("Head clearance", "Near side countersink", "Under head countersink", "Far side countersink"):
            key = OPTION_KEYS[name]
            box = QtWidgets.QCheckBox(name, self.options)
            box.setObjectName(PANEL + "Option" + name.title().replace(" ", ""))
            box.setToolTip(name)
            olay.addWidget(box)
            self.option_boxes[name] = box
            row = QtWidgets.QWidget(self.options)
            form = QtWidgets.QFormLayout(row)
            form.setContentsMargins(12, 0, 0, 0)
            if key == "clearance":
                field = _length(row, PANEL + "HeadClearance")
                field.setToolTip("Extra depth of the counterbore under the screw head")
                form.addRow(QtWidgets.QLabel("Head clearance", row), field)
                self.option_fields[key] = (field,)
            else:
                dia = _length(row, PANEL + key.title() + "CsinkDiameter")
                angle = QtWidgets.QDoubleSpinBox(row)
                angle.setObjectName(PANEL + key.title() + "CsinkAngle")
                angle.setRange(1.0, 179.0)
                angle.setSuffix(" °")
                angle.setKeyboardTracking(False)
                form.addRow(QtWidgets.QLabel("C-Sink Diameter", row), dia)
                form.addRow(QtWidgets.QLabel("C-Sink Angle", row), angle)
                self.option_fields[key] = (dia, angle)
            olay.addWidget(row)
            row.hide()
            self.option_rows[name] = row
            box.toggled.connect(lambda on, k=key: self._option(k, on))
            for field in self.option_fields[key]:
                field.valueChanged.connect(lambda v: self._changed("value"))
        lay.addWidget(self.options)
        self._tolerance_group(page)
        lay.addWidget(self.tolerance)
        self._scope_group(page)
        lay.addWidget(self.scope)
        self.face_note = QtWidgets.QLabel("", page)
        self.face_note.setObjectName(PANEL + "FaceNote")
        self.face_note.setWordWrap(True)
        lay.addWidget(self.face_note)
        lay.addStretch(1)

        _fold(lay, ("Favorite", "Hole Type", "Hole Specifications", "End Condition"),
              stop=(self.options, self.tolerance, self.face_note))
        _fold(olay, ("Options",))
        _fold(self.tolerance.layout(), ("Tolerance/Precision",))
        _fold(self.scope.layout(), ("Feature Scope",))

        self.standard.activated.connect(lambda i: self._changed("standard"))
        self.kind_type.activated.connect(lambda i: self._changed("type"))
        self.size.activated.connect(lambda i: self._changed("size"))
        self.fit.activated.connect(lambda i: self._changed("fit"))
        self.custom.toggled.connect(lambda on: self._changed("custom"))
        self.end.activated.connect(lambda i: self._changed("end"))
        self.end_flip.toggled.connect(lambda on: self._changed("reverse"))
        for box in (self.cdia, self.cdepth, self.cangle, self.depth, self.tdepth, self.slot, self.end_offset):
            box.valueChanged.connect(lambda v: self._changed("value"))
        self.cosmetic.toggled.connect(lambda on: (self.with_callout.setEnabled(on), self._changed("value")))
        self.remove.toggled.connect(lambda on: self._changed("value"))
        self.tapdrill.toggled.connect(lambda on: self._changed("value"))
        self.with_callout.toggled.connect(lambda on: self._changed("value"))
        self.thread_class.activated.connect(lambda i: self._changed("value"))
        self.end_reverse.toggled.connect(lambda on: self._changed("value"))
        return page

    def _fill_legacy(self, ltype, shown, spec):
        """Section Dimensions: one row per size the hole type has, then Depth (blind holes)."""
        rows = [(key, self.legacy_labels[key].text(), self.legacy_fields[key]) for key in shown]
        if (spec.get("end") or "Blind") == "Blind" and getattr(self, "depth", None) is not None:
            rows.insert(1, ("depth", "Depth", self.depth))
        rows = [r for r in rows if r[2] is not None]
        self._legacy_rows = rows
        t = self.legacy_table
        t.blockSignals(True)
        t.setRowCount(len(rows))
        for i, (key, text, field) in enumerate(rows):
            unit = " °" if "angle" in key or "taper" in key else ""
            value = QtWidgets.QTableWidgetItem(("%g" % field.value()) + unit if unit else "%g mm" % field.value())
            name = QtWidgets.QTableWidgetItem(text)
            name.setFlags(name.flags() & ~QtCore.Qt.ItemIsEditable)
            t.setItem(i, 0, value)
            t.setItem(i, 1, name)
        t.resizeColumnToContents(0)
        t.setFixedHeight(t.horizontalHeader().height() + sum(t.rowHeight(i) for i in range(len(rows))) + 4)
        t.blockSignals(False)
        self.legacy_picture.setPixmap(section_picture(ltype, {k: f.value() for k, _t, f in rows}))

    def _legacy_cell(self, item):
        """A value typed in Section Dimensions goes to its size (units as typed, mm otherwise)."""
        if item.column() != 0 or item.row() >= len(self._legacy_rows):
            return
        key, _text, field = self._legacy_rows[item.row()]
        text = item.text().strip().replace(",", ".")
        try:
            if "angle" in key or "taper" in key:
                v = float(text.replace("°", "").replace("deg", "").strip())
            else:
                v = App.Units.Quantity(text if any(c.isalpha() for c in text) else text + " mm").getValueAs("mm").Value
        except Exception:
            QtCore.QTimer.singleShot(0, lambda: self._changed("value"))
            return
        field.setValue(v)
        QtCore.QTimer.singleShot(0, lambda: self._changed("value"))

    def _combo(self, page, lay, text, name):
        label = QtWidgets.QLabel(text, page)
        lay.addWidget(label)
        combo = QtWidgets.QComboBox(page)
        combo.setObjectName(name)
        lay.addWidget(combo)
        self.labels[combo] = label
        return combo

    def _positions_page(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(_bold(page, "Hole Position"))
        self.positions_note = QtWidgets.QLabel(
            "Select the face for the holes.\nThen click once for each hole, and exit the sketch when done.", page)
        self.positions_note.setObjectName(PANEL + "PositionsNote")
        self.positions_note.setWordWrap(True)
        lay.addWidget(self.positions_note)

        self.sketch3d = QtWidgets.QPushButton("3D Sketch", page)
        self.sketch3d.setObjectName(PANEL + "Sketch3D")
        self.sketch3d.setCheckable(True)
        self.sketch3d.setToolTip("Place holes on any face, round ones too: click a point on a face for each "
                                 "hole; it goes in along the face's normal there")
        self.sketch3d.toggled.connect(self._sketch3d)
        lay.addWidget(self.sketch3d)

        self.existing2d = QtWidgets.QPushButton("Existing 2D Sketch", page)
        self.existing2d.setObjectName(PANEL + "Existing2D")
        self.existing2d.setCheckable(True)
        self.existing2d.setToolTip("Use an existing 2D sketch: a hole at each of its points and at the "
                                   "end points of its lines and arcs, construction geometry too")
        self.existing2d.toggled.connect(self._existing2d)
        lay.addWidget(self.existing2d)
        self.existing_box = QtWidgets.QListWidget(page)
        self.existing_box.setObjectName(PANEL + "ExistingSketch")
        self.existing_box.setFixedHeight(24)
        self.existing_box.setToolTip("The sketch whose points are the hole positions")
        self.existing_box.hide()
        lay.addWidget(self.existing_box)
        self.existing = None                # the existing 2D sketch picked
        self.skip_label = _bold(page, "Instances to Skip")
        self.skip_label.hide()
        lay.addWidget(self.skip_label)
        self.skip_list = QtWidgets.QListWidget(page)
        self.skip_list.setObjectName(PANEL + "Skip")
        self.skip_list.setFixedHeight(88)
        self.skip_list.setToolTip("Tick a position, or click it in the graphics area, to leave its hole out")
        self.skip_list.hide()
        lay.addWidget(self.skip_list)
        self.points_list = QtWidgets.QListWidget(page)
        self.points_list.setObjectName(PANEL + "Points3D")
        self.points_list.setFixedHeight(66)
        self.points_list.setToolTip("The hole points picked; Delete takes one out")
        self.points_list.hide()
        self.points3d = []                  # [(object, "FaceN", App.Vector)]
        try:
            from . import pmboxes
            pmboxes.bind(self.points_list, self._remove_point, self._clear_points)
        except Exception as _fw_err:
            _fw_log("holespec.py:1650", _fw_err)
        lay.addWidget(self.points_list)
        self.error = QtWidgets.QLabel("", page)
        self.error.setWordWrap(True)
        self.error.setStyleSheet(_error_css())
        self.error.hide()
        lay.addWidget(self.error)
        lay.addStretch(1)
        return page

    # ----------------------------------------------------------- filling in
    @staticmethod
    def _fill(combo, items, current):
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(items)
        if current in items:
            combo.setCurrentText(current)
        combo.blockSignals(False)
        return combo.currentText()

    def _load(self):
        """Show self.spec, fixing any part that no longer fits the lists."""
        self._busy = True
        try:
            spec = self.spec
            if spec.get("kind") not in KINDS + tuple(BASE) + (LEGACY,):
                spec["kind"] = "Hole"
            legacy = spec["kind"] == LEGACY
            self.legacy_box.setVisible(legacy)
            for combo in (self.standard, self.kind_type, self.size):
                combo.setVisible(not legacy)
                self.labels[combo].setVisible(not legacy)
            self.spec_title.setVisible(not legacy)
            if legacy:
                ltype = spec.get("legacy_type") if spec.get("legacy_type") in holelegacy.TYPES else "Simple"
                spec["legacy_type"] = ltype
                self.legacy_type.setCurrentText(ltype)
                defaults = {"legacy_dia": 10.0, "legacy_head_dia": 16.0, "legacy_head_depth": 5.0,
                            "legacy_angle": 90.0, "legacy_taper": 5.0}
                for key, field in self.legacy_fields.items():
                    if not spec.get(key):
                        spec[key] = defaults[key]
                    field.setValue(float(spec[key]))
                shown = {"Simple": ("legacy_dia",), "Tapered": ("legacy_dia", "legacy_taper"),
                         "Counterbored": ("legacy_dia", "legacy_head_dia", "legacy_head_depth"),
                         "Countersunk": ("legacy_dia", "legacy_head_dia", "legacy_angle"),
                         "Counterdrilled": ("legacy_dia", "legacy_head_dia", "legacy_head_depth", "legacy_angle")}[ltype]
                names = {"Counterbored": ("C-Bore Diameter", "C-Bore Depth"), "Countersunk": ("C-Sink Diameter", ""),
                         "Counterdrilled": ("C-Drill Diameter", "C-Drill Depth")}.get(ltype, ("", ""))
                if names[0]:
                    self.legacy_labels["legacy_head_dia"].setText(names[0])
                if names[1]:
                    self.legacy_labels["legacy_head_depth"].setText(names[1])
                self.legacy_labels["legacy_angle"].setText("C-Drill Angle" if ltype == "Counterdrilled" else "C-Sink Angle")
                self._fill_legacy(ltype, shown, spec)
            self.kind_buttons[spec["kind"]].setChecked(True)
            spec["standard"] = self._fill(self.standard, standards(spec["kind"]), spec.get("standard"))
            spec["type"] = self._fill(self.kind_type, types(spec["kind"], spec["standard"]), spec.get("type"))
            choices = sizes(spec)
            if spec.get("size") not in choices:
                for guess in ("M5", "Ø5.0", '1/4"', "1/4", "M5x0.5"):
                    if guess in choices:
                        spec["size"] = guess
                        break
                else:
                    spec["size"] = choices[len(choices) // 3] if choices else ""
            spec["size"] = self._fill(self.size, choices, spec["size"])
            self.fit.setCurrentText(spec.get("fit", "Normal"))
            fit = has_fit(spec)
            self.fit.setVisible(fit)
            self.fit_label.setVisible(fit)
            fields = custom_fields(spec)
            self.custom.setVisible(bool(fields))
            self.custom.setChecked(bool(spec.get("custom")) and bool(fields))
            self.custom_box.setVisible(self.custom.isChecked())
            self.cdia_label.setText({"Counterbore": "C-Bore Diameter", "Countersink": "C-Sink Diameter"}.get(
                _base(spec["kind"]), "Through Hole Diameter"))
            slot = spec["kind"] in BASE
            if slot and not spec.get("slot_length"):
                spec["slot_length"] = round(hole_sizes(spec)[0] * 2, 2)
            self.slot_label.setVisible(slot)
            self.slot.setVisible(slot)
            self.slot.setValue(float(spec.get("slot_length") or 0.0))
            for widget, label, key in ((self.cdia, self.cdia_label, "cdia"), (self.cdepth, self.cdepth_label, "cdepth"),
                                       (self.cangle, self.cangle_label, "cangle")):
                widget.setVisible(key in fields)
                label.setVisible(key in fields)
            if fields and not spec.get("cdia"):
                self._custom_defaults()
            self.cdia.setValue(float(spec.get("cdia") or 0.0))
            self.cdepth.setValue(float(spec.get("cdepth") or 0.0))
            self.cangle.setValue(float(spec.get("cangle") or 90.0))
            self.end.setCurrentText(spec.get("end", "Blind"))
            self.end_flip.blockSignals(True)
            self.end_flip.setChecked(bool(spec.get("reverse")))
            self.end_flip.blockSignals(False)
            blind = spec.get("end", "Blind") == "Blind"
            pick = holeends.needs(spec.get("end"))
            self.end_target_label.setText("Vertex" if pick == "Vertex" else "Face/Plane")
            for w in (self.end_target_label, self.end_target):
                w.setVisible(bool(pick))
            self.end_target.setText((spec.get("end_target") or "").replace(":", " "))
            self.end_target.setStyleSheet("" if spec.get("end_target") or not pick else
                                          "QLineEdit { background: #cfe3ff; color: black; }")
            offset = spec.get("end") == "Offset From Surface"
            for w in (self.end_offset_label, self.end_offset, self.end_reverse):
                w.setVisible(offset)
            self.end_offset.setValue(float(spec.get("end_offset") or 0.0))
            self.end_reverse.setChecked(bool(spec.get("end_reverse")))
            tap = is_tap(spec)
            if tap and not spec.get("tdepth"):
                spec["depth"], spec["tdepth"] = tap_depths(spec)
            self.depth.setValue(float(spec.get("depth") or 10.0))
            self.tdepth.setValue(float(spec.get("tdepth") or 0.0))
            self.depth_label.setText("Tap drill depth" if tap else "Depth")
            self.depth.setVisible(blind)
            self.depth_label.setVisible(blind)
            self.tdepth.setVisible(tap and spec.get("end") != "Through All")
            self.tdepth_label.setVisible(tap and spec.get("end") != "Through All")
            shown = () if spec["kind"] in BASE else OPTIONS.get(spec["kind"], ())
            for name, box in self.option_boxes.items():
                key = OPTION_KEYS[name]
                box.setVisible(name in shown)
                box.setChecked(bool(spec.get(key)) and name in shown)
                if box.isChecked():
                    self._option_defaults(key)
                self.option_rows[name].setVisible(box.isChecked())
                fields = self.option_fields[key]
                if key == "clearance":
                    fields[0].setValue(float(spec.get("clearance_value") or 0.0))
                else:
                    fields[0].setValue(float(spec.get(key + "_dia") or 0.0))
                    fields[1].setValue(float(spec.get(key + "_angle") or 90.0))
            self.cosmetic.setVisible(tap)
            self.remove.setVisible(tap)
            self.tapdrill.setVisible(tap)
            self.with_callout.setVisible(tap)
            self.thread_class_row.setVisible(tap and spec.get("standard") == "ANSI Inch")
            self.options.setVisible(tap or bool(shown))
            style = YELLOW if self.custom.isChecked() else ""
            for w in (self.cdia, self.cdepth, self.cangle):
                if w.styleSheet() != style:
                    w.setStyleSheet(style)
            self._fill_favorites()
            option = thread_option(spec)
            spec["cosmetic"] = option == "cosmetic"
            {"cosmetic": self.cosmetic, "remove": self.remove, "tapdrill": self.tapdrill}[option].setChecked(True)
            self.with_callout.setChecked(bool(spec.get("thread_callout", True)))
            self.with_callout.setEnabled(option == "cosmetic")
            self.thread_class.setCurrentText(spec.get("thread_class") or "2B")
            self._tol_show()
        finally:
            self._busy = False

    # ----------------------------------------------------------- Tolerance/Precision
    def _tolerance_group(self, page):
        ""

        self.tolerance = QtWidgets.QWidget(page)
        tl = QtWidgets.QVBoxLayout(self.tolerance)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(_bold(self.tolerance, "Tolerance/Precision"))
        inner = QtWidgets.QWidget(self.tolerance)
        il = QtWidgets.QVBoxLayout(inner)
        il.setContentsMargins(30, 0, 0, 0)
        il.addWidget(QtWidgets.QLabel("Callout value", inner))
        self.tol_value = QtWidgets.QComboBox(inner)
        self.tol_value.setObjectName(PANEL + "CalloutValue")
        self.tol_value.setToolTip("The value of the hole callout the tolerance and precision apply to")
        il.addWidget(self.tol_value)
        self.tol_type = QtWidgets.QComboBox(inner)
        self.tol_type.setObjectName(PANEL + "ToleranceType")
        self.tol_type.setToolTip("Tolerance Type")
        self.tol_type.addItems(list(TOL_TYPES))
        il.addWidget(self.tol_type)
        self.tol_rows = QtWidgets.QWidget(inner)
        form = QtWidgets.QFormLayout(self.tol_rows)
        form.setContentsMargins(0, 0, 0, 0)
        self.tol_plus, self.tol_minus = QtWidgets.QDoubleSpinBox(self.tol_rows), QtWidgets.QDoubleSpinBox(self.tol_rows)
        for box, name, tip in ((self.tol_plus, "ToleranceMax", "Maximum Variation"),
                               (self.tol_minus, "ToleranceMin", "Minimum Variation")):
            box.setObjectName(PANEL + name)
            box.setToolTip(tip)
            box.setDecimals(4)
            box.setRange(0.0, 10000.0)
            box.setSingleStep(0.01)
            box.setKeyboardTracking(False)
            box.valueChanged.connect(lambda v: self._tol_changed())
        self.tol_plus_label, self.tol_minus_label = QtWidgets.QLabel("+", self.tol_rows), QtWidgets.QLabel("-", self.tol_rows)
        form.addRow(self.tol_plus_label, self.tol_plus)
        form.addRow(self.tol_minus_label, self.tol_minus)
        il.addWidget(self.tol_rows)
        self.tol_precision = QtWidgets.QComboBox(inner)
        self.tol_precision.setObjectName(PANEL + "UnitPrecision")
        self.tol_precision.setToolTip("Unit Precision")
        self.tol_precision.addItems(list(PRECISIONS))
        il.addWidget(self.tol_precision)
        tl.addWidget(inner)
        self.tol_value.activated.connect(lambda i: self._tol_show())
        self.tol_type.activated.connect(lambda i: self._tol_changed())
        self.tol_precision.activated.connect(lambda i: self._tol_changed())

    def _scope_group(self, page):
        ""

        self.scope = QtWidgets.QWidget(page)
        self.scope.setObjectName(PANEL + "FeatureScope")
        sl = QtWidgets.QVBoxLayout(self.scope)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(_bold(self.scope, "Feature Scope"))
        inner = QtWidgets.QWidget(self.scope)
        il = QtWidgets.QVBoxLayout(inner)
        il.setContentsMargins(30, 0, 0, 0)
        self.scope_all = QtWidgets.QRadioButton("All bodies", inner)
        self.scope_all.setObjectName(PANEL + "ScopeAll")
        self.scope_some = QtWidgets.QRadioButton("Selected bodies", inner)
        self.scope_some.setObjectName(PANEL + "ScopeSelected")
        self.scope_auto = QtWidgets.QCheckBox("Auto-select", inner)
        self.scope_auto.setObjectName(PANEL + "ScopeAuto")
        self.scope_list = QtWidgets.QListWidget(inner)
        self.scope_list.setObjectName(PANEL + "ScopeBodies")
        self.scope_list.setFixedHeight(80)
        self.scope_list.setToolTip("The bodies the hole cuts: tick them")
        for w in (self.scope_all, self.scope_some, self.scope_auto, self.scope_list):
            il.addWidget(w)
        sl.addWidget(inner)
        base = self.hole.BaseFeature if self.hole is not None else getattr(self.body, "Tip", None)
        solids = scope_solids(base)
        picks = [int(x) for x in str(self.spec.get("scope_pick") or "").split(",") if x.strip().isdigit()]
        for i, solid in enumerate(solids):
            item = QtWidgets.QListWidgetItem("Body %d (%.0f mm\u00b3)" % (i + 1, solid.Volume))
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if i in picks else QtCore.Qt.Unchecked)
            self.scope_list.addItem(item)
        (self.scope_all if self.spec.get("scope_all", True) else self.scope_some).setChecked(True)
        self.scope_auto.setChecked(bool(self.spec.get("scope_auto", True)))
        self.scope.setVisible(len(solids) > 1)
        self._scope_shown()
        self.scope_all.toggled.connect(lambda on: self._scope_changed())
        self.scope_auto.toggled.connect(lambda on: self._scope_changed())
        self.scope_list.itemChanged.connect(lambda item: self._scope_changed())

    def _scope_shown(self):
        self.scope_auto.setVisible(self.scope_some.isChecked())
        self.scope_list.setVisible(self.scope_some.isChecked() and not self.scope_auto.isChecked())

    def _scope_changed(self):
        self._scope_shown()
        self.spec["scope_all"] = self.scope_all.isChecked()
        self.spec["scope_auto"] = self.scope_auto.isChecked()
        self.spec["scope_pick"] = ",".join(str(i) for i in range(self.scope_list.count())
                                           if self.scope_list.item(i).checkState() == QtCore.Qt.Checked)
        if self.hole is not None and not self._busy:
            self._changed("value")

    def _tol_entry(self):
        return self.spec.setdefault("tolerances", {}).get(self.tol_value.currentText()) or {}

    def _tol_show(self):
        """The chosen callout value's tolerance on the fields (and the value list for this hole)."""
        busy, self._busy = self._busy, True
        try:
            self._fill(self.tol_value, callout_values(self.spec), self.tol_value.currentText())
            t = self._tol_entry()
            self.tol_type.setCurrentText(t.get("type") or "None")
            self.tol_precision.setCurrentText(t.get("precision") or PRECISIONS[0])
            for box, key in ((self.tol_plus, "plus"), (self.tol_minus, "minus")):
                box.blockSignals(True)
                box.setValue(float(t.get(key) or 0.0))
                box.blockSignals(False)
            self._tol_rows_shown()
        finally:
            self._busy = busy

    def _tol_rows_shown(self):
        kind = self.tol_type.currentText()
        self.tol_rows.setVisible(kind in ("Bilateral", "Limit", "Symmetric"))
        self.tol_minus.setVisible(kind != "Symmetric")
        self.tol_minus_label.setVisible(kind != "Symmetric")
        self.tol_plus_label.setText("±" if kind == "Symmetric" else "+")

    def _tol_changed(self):
        if self._busy:
            return
        name = self.tol_value.currentText()
        if not name:
            return
        self.spec.setdefault("tolerances", {})[name] = {
            "type": self.tol_type.currentText(), "plus": self.tol_plus.value(),
            "minus": self.tol_minus.value(), "precision": self.tol_precision.currentText()}
        self._tol_rows_shown()
        self._changed("value")

    def _custom_defaults(self):
        """Start the custom fields from what FreeCAD would make."""
        try:
            with _Scratch() as doc:
                hole = doc.addObject("PartDesign::Hole", "Hole")
                spec = dict(self.spec, custom=False)
                try:
                    apply(hole, spec)
                except Exception as _fw_err:
                    _fw_log("holespec.py:1902", _fw_err)
                if _base(spec["kind"]) in ("Counterbore", "Countersink"):
                    self.spec["cdia"] = round(hole.HoleCutDiameter.Value, 2)
                    self.spec["cdepth"] = round(hole.HoleCutDepth.Value, 2)
                    self.spec["cangle"] = round(hole.HoleCutCountersinkAngle.Value, 2)
                else:
                    self.spec["cdia"] = round(hole.Diameter.Value, 2)
        except Exception as error:
            App.Console.PrintWarning("Hole Wizard: no custom sizes (%s)\n" % error)

    # ----------------------------------------------------------- Favorite
    def _favorite_rows(self, page, lay):
        lay.addWidget(_bold(page, "Favorite"))
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(2)
        row.setContentsMargins(30, 0, 0, 0)
        self.fav_buttons = {}
        for key, tip in (("Defaults", "Apply Defaults / No Favorites"), ("Add", "Add or Update Favorite"),
                         ("Delete", "Delete Favorite"), ("Save", "Save Favorite"), ("Load", "Load Favorite")):
            b = QtWidgets.QToolButton(page)
            b.setObjectName(PANEL + "Favorite" + key)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.setIcon(_favorite_icon(key))
            b.setIconSize(QtCore.QSize(18, 18))
            row.addWidget(b)
            self.fav_buttons[key] = b
        row.addStretch(1)
        lay.addLayout(row)
        self.favorite = QtWidgets.QComboBox(page)
        self.favorite.setObjectName(PANEL + "Favorite")
        self.favorite.setToolTip("Saved hole specifications")
        fav_row = QtWidgets.QHBoxLayout()
        fav_row.setContentsMargins(30, 0, 0, 0)
        fav_row.addWidget(self.favorite)
        lay.addLayout(fav_row)
        self.fav_buttons["Defaults"].clicked.connect(self._fav_defaults)
        self.fav_buttons["Add"].clicked.connect(self._fav_add)
        self.fav_buttons["Delete"].clicked.connect(self._fav_delete)
        self.fav_buttons["Save"].clicked.connect(self._fav_save)
        self.fav_buttons["Load"].clicked.connect(self._fav_load)
        self.favorite.activated.connect(lambda i: self._fav_apply())

    def _fill_favorites(self):
        names = sorted(favorites())
        chosen = self.spec.get("favorite") if self.spec.get("favorite") in names else NO_FAVORITE
        self._fill(self.favorite, [NO_FAVORITE] + names, chosen)
        self.fav_buttons["Delete"].setVisible(chosen != NO_FAVORITE)     # nothing to delete: no grey button (no dead controls)
        self.fav_buttons["Save"].setEnabled(True)                         # saves the favorite, or the hole as it stands

    def _fav_apply(self):
        name = self.favorite.currentText()
        data = favorites()
        if name in data:
            self.spec = dict(DEFAULT)
            self.spec.update(data[name])
            self.spec["favorite"] = name
        else:
            self.spec.pop("favorite", None)
        self._load()
        remember(self.spec)

    def _fav_defaults(self):
        kind = self.spec.get("kind", "Hole")
        self.spec = dict(DEFAULT)
        self.spec["kind"] = kind
        self._load()
        remember(self.spec)

    def _fav_add(self, name=None):
        if not name:
            suggested = self.spec.get("favorite") or ("%s %s" % (self.spec.get("size", ""), self.spec.get("kind", ""))).strip()
            name, ok = QtWidgets.QInputDialog.getText(Gui.getMainWindow(), "Add or Update Favorite",
                                                      "Enter a name for the favorite:", text=suggested)
            if not ok or not name.strip():
                return
        data = favorites()
        keep = {k: v for k, v in self.spec.items() if k != "favorite"}
        data[name.strip()] = keep
        set_favorites(data)
        self.spec["favorite"] = name.strip()
        self._load()
        remember(self.spec)

    def _fav_delete(self):
        name = self.favorite.currentText()
        data = favorites()
        if name in data:
            del data[name]
            set_favorites(data)
        self.spec.pop("favorite", None)
        self._load()
        remember(self.spec)

    def _fav_save(self, path=None):
        name = self.favorite.currentText()
        data = favorites()
        if name in data:
            spec = data[name]
        else:
            name = ("%s %s" % (self.spec.get("size", ""), self.spec.get("kind", ""))).strip() or "Hole"
            spec = {k: v for k, v in self.spec.items() if k != "favorite"}
        if not path:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save Favorite",
                                                            name + ".json", "Hole favorite (*.json)")
        if path:
            with open(path, "w") as out:
                json.dump({"name": name, "spec": spec}, out, indent=1)

    def _fav_load(self, path=None):
        if not path:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Load Favorite", "",
                                                            "Hole favorite (*.json)")
        if not path:
            return
        try:
            with open(path) as src:
                got = json.load(src)
            name, spec = got["name"], dict(got["spec"])
        except Exception as error:
            App.Console.PrintWarning("Hole Wizard: favorite not loaded (%s)\n" % error)
            return
        data = favorites()
        data[name] = spec
        set_favorites(data)
        self.spec = dict(DEFAULT)
        self.spec.update(spec)
        self.spec["favorite"] = name
        self._load()
        remember(self.spec)

    def _restore_defaults(self):
        ""
        self.spec["cdia"] = 0.0
        self._custom_defaults()
        self._load()
        remember(self.spec)

    def _set_kind(self, kind):
        if self._busy:
            return
        self.spec["kind"] = kind
        self.spec["tdepth"] = 0.0
        self.spec["cdia"] = 0.0
        for key in ("near", "under", "far"):
            self.spec[key + "_dia"] = 0.0
        self.spec["slot_length"] = 0.0
        self._load()
        remember(self.spec)

    def _option(self, key, on):
        ""
        if self._busy:
            return
        spec = self.spec
        spec[key] = bool(on)
        self._load()
        remember(spec)

    def _option_defaults(self, key):
        spec = self.spec
        if key == "clearance":
            if spec.get("clearance_value"):
                return
        elif spec.get(key + "_dia"):
            return
        hole_d, head_d, head_depth, _angle = hole_sizes(spec)
        if key == "clearance":
            spec["clearance_value"] = round(max(hole_d * 0.2, 0.5), 2)
        else:
            rim = head_d if key == "near" else hole_d
            spec[key + "_dia"] = round(rim + max(1.0, hole_d * 0.2), 2)
            spec[key + "_angle"] = 90.0

    def _changed(self, what):
        if self._busy:
            return
        spec = self.spec
        if what == "standard":
            spec["standard"] = self.standard.currentText()
        elif what == "type":
            spec["type"] = self.kind_type.currentText()
        elif what == "size":
            spec["size"] = self.size.currentText()
        elif what == "fit":
            spec["fit"] = self.fit.currentText()
        elif what == "custom":
            spec["custom"] = self.custom.isChecked()
        elif what == "end":
            if spec.get("end") != self.end.currentText():
                spec["end_target"] = ""
            spec["end"] = self.end.currentText()
        elif what == "reverse":
            spec["reverse"] = self.end_flip.isChecked()
        elif what == "legacy":
            spec["legacy_type"] = self.legacy_type.currentText()
        else:
            for key, field in self.legacy_fields.items():
                spec[key] = field.value()
            spec["cdia"] = self.cdia.value()
            spec["cdepth"] = self.cdepth.value()
            spec["cangle"] = self.cangle.value()
            spec["depth"] = self.depth.value()
            spec["tdepth"] = self.tdepth.value()
            spec["cosmetic"] = self.cosmetic.isChecked()
            spec["thread_option"] = "remove" if self.remove.isChecked() else (
                "tapdrill" if self.tapdrill.isChecked() else "cosmetic")
            spec["thread_callout"] = self.with_callout.isChecked()
            spec["thread_class"] = self.thread_class.currentText() or "2B"
            spec["slot_length"] = self.slot.value()
            spec["end_offset"] = self.end_offset.value()
            spec["end_reverse"] = self.end_reverse.isChecked()
            spec["clearance_value"] = self.option_fields["clearance"][0].value()
            for key in ("near", "under", "far"):
                spec[key + "_dia"] = self.option_fields[key][0].value()
                spec[key + "_angle"] = self.option_fields[key][1].value()
        if what in ("standard", "type", "size"):
            spec["tdepth"] = 0.0
            spec["cdia"] = 0.0
            for key in ("near", "under", "far"):
                spec[key + "_dia"] = 0.0
            spec["slot_length"] = 0.0
        if what != "value":
            self._load()
        remember(spec)
        if self.hole is not None and not self.done:

            # takes it back (the edit's transaction is aborted)
            QtCore.QTimer.singleShot(0, self._preview_edit)

    def _preview_edit(self):
        if self.done or self.hole is None:
            return
        try:
            self._apply()
        except Exception as error:
            App.Console.PrintLog("FreeCAD Hole Wizard: preview: %r\n" % (error,))

    # ----------------------------------------------------------- positions
    def _note_face(self):
        if self.hole is not None:
            self.face_note.setText("Editing %s. Positions opens its sketch." % self.hole.Label)
        elif self.face is not None:
            self.face_note.setText("Holes go on %s of %s." % (self.face[1], self.face[0].Label))
        elif self.sketch is not None:
            self.face_note.setText("Holes go on the points of %s. Positions opens it." % self.sketch.Label)
        else:
            self.face_note.setText("")

    def _take_typed(self):
        ""

        try:
            from . import pmvalues as _fw_pmv
            _fw_pmv.hide_lists()
        except Exception as _fw_err:
            App.Console.PrintLog("FreeCAD: value list: %r\n" % (_fw_err,))
        for x in self.form.findChildren(QtWidgets.QAbstractSpinBox):
            try:
                if x.isVisible() and x.isEnabled() and not x.keyboardTracking() and _fw_retyped(x):
                    x.interpretText()
            except Exception as _fw_err:
                App.Console.PrintLog("FreeCAD: typed value: %r\n" % (_fw_err,))

    def _tab(self, index):
        self._take_typed()
        if index == 1 and self.hole is not None:

            self.tabs.setCurrentIndex(0)
            self._edit_positions()
            return
        if index == 1 and self.sketch is not None:
            # A sketch picked first: Positions is that sketch (its points are the holes)
            self.tabs.setCurrentIndex(0)
            self._edit_sketch(self.sketch)
            return
        self.pages.setCurrentIndex(index)
        if index == 1 and self.face is not None and not self.sketch3d.isChecked():
            self._go(*self.face)

    # ----------------------------------------------------------- Existing 2D Sketch positions
    def _existing2d(self, on):
        if on and self.sketch3d.isChecked():
            self.sketch3d.setChecked(False)
        self.existing_box.setVisible(on)
        self.error.hide()
        if on:
            self.positions_note.setText("Existing 2D Sketch: select the sketch; a hole goes at each of its "
                                        "points and end points. Tick any to skip, then OK.")
        elif not self.sketch3d.isChecked():
            self.positions_note.setText("Select the face for the holes.\nThen click once for each hole, and "
                                        "exit the sketch when done.")
        self._show_existing()

    def set_existing(self, sketch):
        self.existing = sketch
        self.skip_list.clear()
        if sketch is not None:
            for i, p in enumerate(sketch_positions(sketch), 1):
                item = QtWidgets.QListWidgetItem("Instance %d  (%.2f, %.2f)" % (i, p.x, p.y))
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.Unchecked)
                self.skip_list.addItem(item)
        self._show_existing()

    def skipped(self):
        return [i for i in range(self.skip_list.count()) if self.skip_list.item(i).checkState() == QtCore.Qt.Checked]

    def toggle_skip(self, index):
        item = self.skip_list.item(index)
        if item is not None:
            item.setCheckState(QtCore.Qt.Unchecked if item.checkState() == QtCore.Qt.Checked else QtCore.Qt.Checked)

    def _show_existing(self):
        on = self.existing2d.isChecked()
        self.existing_box.clear()
        if self.existing is not None:
            self.existing_box.addItem(self.existing.Label)
        has = on and self.existing is not None and self.skip_list.count() > 0
        self.skip_label.setVisible(has)
        self.skip_list.setVisible(has)
        try:
            from . import pmboxes
            pmboxes.mark(self.existing_box, on, need=on and self.existing is None)
        except Exception as _fw_err:
            _fw_log("holespec.py:2208", _fw_err)

    def _existing_pick(self, entry, sub, points):
        obj = entry.Object
        if obj.TypeId == "Sketcher::SketchObject" and _body_of(obj) is self.body:
            if obj is not self.existing:
                self.set_existing(obj)
            elif points and (sub.startswith("Vertex") or sub.startswith("Edge")):
                # a click on a position of the picked sketch skips it (or takes it back)
                place = obj.getGlobalPlacement().inverse()
                local = place.multVec(App.Vector(points[-1]))
                local = App.Vector(local.x, local.y, 0)
                pos = sketch_positions(obj)
                if pos:
                    k = min(range(len(pos)), key=lambda i: (pos[i] - local).Length)
                    self.toggle_skip(k)
            self.error.hide()
        else:
            self.error.setText("Select a 2D sketch of this body.")
            self.error.show()
        Gui.Selection.clearSelection()

    # ----------------------------------------------------------- 3D Sketch positions
    def _sketch3d(self, on):
        if on and self.existing2d.isChecked():
            self.existing2d.setChecked(False)
        self.points_list.setVisible(on)
        self.error.hide()
        if on:
            self.positions_note.setText("3D Sketch: click a point on any face for each hole (the hole goes in "
                                        "along the face there), then OK.")
        else:
            self.positions_note.setText("Select the face for the holes.\nThen click once for each hole, and "
                                        "exit the sketch when done.")
        self._show_points()

    def _show_points(self):
        self.points_list.clear()
        for obj, sub, point in self.points3d:
            self.points_list.addItem("%s: %s (%.2f, %.2f, %.2f)" % (obj.Label, sub, point.x, point.y, point.z))
        try:
            from . import pmboxes
            pmboxes.mark(self.points_list, self.sketch3d.isChecked(), need=self.sketch3d.isChecked() and not self.points3d)
        except Exception as _fw_err:
            _fw_log("holespec.py:2252", _fw_err)

    def _remove_point(self, row):
        if 0 <= row < len(self.points3d):
            self.points3d.pop(row)
            self._show_points()

    def _clear_points(self):
        self.points3d = []
        self._show_points()

    def _edit_positions(self):
        hole = self.hole
        try:
            sketch = hole.Profile[0] if isinstance(hole.Profile, tuple) else hole.Profile
        except Exception:
            sketch = None
        if sketch is None:
            return
        self._apply()
        self.done = True
        self._cleanup()
        Gui.Control.closeDialog()
        self._leave_edit()
        doc = hole.Document
        QtCore.QTimer.singleShot(0, lambda: Gui.getDocument(doc.Name).setEdit(sketch.Name, 0))

    def _edit_sketch(self, sketch):
        """Positions with a sketch picked first: the sketch opens with the Point tool; its points
        are the holes when it closes (holewizard.start_on_face with the sketch)."""
        spec = dict(self.spec)
        remember(spec)
        self.done = True
        self._cleanup()
        Gui.Control.closeDialog()
        if self.on_positions is not None:
            QtCore.QTimer.singleShot(0, lambda: self.on_positions(sketch, "", spec))
        else:
            doc = sketch.Document
            QtCore.QTimer.singleShot(0, lambda: Gui.getDocument(doc.Name).setEdit(sketch.Name, 0))

    def _leave_edit(self):
        try:
            gdoc = Gui.getDocument(self.hole.Document.Name)
            if gdoc.getInEdit() is not None:
                gdoc.resetEdit()
        except Exception as _fw_err:
            _fw_log("holespec.py:2299", _fw_err)

    def _apply(self):
        """Edit Feature: the shown choices go onto the hole (one undo step)."""
        hole = self.hole
        doc = hole.Document
        spec = dict(self.spec)
        if not self.opened:
            doc.openTransaction("Edit " + hole.Label)
            self.opened = True
        try:
            try:
                from . import holegroup
                group = holegroup.group_of(hole)
                every = holegroup.holes_with(hole)
            except Exception:
                group, every = None, [hole]
            for each in every:          # a Hole Wizard feature on several faces: all its holes change
                if spec["kind"] in (LEGACY,) + tuple(BASE):
                    store(each, spec)    # legacy holes and slots keep their geometry; the choices are kept
                else:
                    was = stored(each)
                    apply(each, spec)
                    apply_scope(each, spec)
                    holeends.attach(each, spec)
                    holeoptions.sync(each, spec)
                    if group is None:
                        _rename(each, was, spec)
                    doc.recompute()
                    sync_threads(each, spec)
            if group is not None:
                was = json.loads(getattr(group, SPEC_PROPERTY, "") or "null") if SPEC_PROPERTY in group.PropertiesList else None
                for i, each in enumerate(group.Holes, 1):
                    each.Label = "%s~%d" % (group.Name, i)          # out of the way of the new name
                _rename(group, was, spec)
                if SPEC_PROPERTY in group.PropertiesList:
                    setattr(group, SPEC_PROPERTY, getattr(hole, SPEC_PROPERTY))
                for i, each in enumerate(group.Holes, 1):
                    each.Label = "%s (Position %d)" % (group.Label, i)
                # threads or options the new choices added stay inside the feature
                members = [m for m in group.Members if m.Document is doc and doc.getObject(m.Name) is m]
                for each in group.Holes:
                    extra = list(threads_of(each))
                    try:
                        extra.append(holeoptions.existing(each))
                    except Exception as _fw_err:
                        _fw_log("holespec.py:2344", _fw_err)
                    members += [m for m in extra if m is not None and m not in members]
                group.Members = members
            doc.recompute()
        except Exception as error:
            App.Console.PrintError("Hole Wizard: %s\n" % error)
            App.Console.PrintLog(traceback.format_exc())

    def picked(self):
        if self.done:
            return
        try:
            selection = Gui.Selection.getSelectionEx()
        except Exception:
            return
        if not selection:
            return
        entry = selection[-1]
        subs = [s for s in entry.SubElementNames if s]
        sub = subs[-1] if subs else ""
        pick = holeends.needs(self.spec.get("end"))
        try:
            tab = self.tabs.currentIndex()
        except RuntimeError:
            self._cleanup()         # the page went without accept or reject: the observer with it
            return
        if tab == 0 and pick and not self.spec.get("end_target") and (
                sub.startswith(pick) or (pick == "Face" and not sub and entry.Object.TypeId in holeends.PLANES)):
            # the End Condition's vertex or face, not the face the holes go on
            self.spec["end_target"] = holeends.target_text(entry.Object, sub)
            remember(self.spec)
            Gui.Selection.clearSelection()
            self._load()
            return
        points = list(getattr(entry, "PickedPoints", []) or [])
        if tab == 1 and self.existing2d.isChecked():
            self._existing_pick(entry, sub, points)
            return
        if tab == 1 and not self.sketch3d.isChecked() and sub.startswith("Face") and points and \
                not sketchstart._is_flat(entry.Object, sub) and _placeable(entry.Object, sub):

            self.sketch3d.setChecked(True)
        if tab == 1 and self.sketch3d.isChecked() and sub.startswith("Face"):
            if points:
                self.points3d.append((entry.Object, sub, App.Vector(points[0])))
                self.error.hide()
            else:
                self.error.setText("Click a point on the face (the tree gives no point).")
                self.error.show()
            Gui.Selection.clearSelection()
            self._show_points()
            return
        if sub.startswith("Face") and _placeable(entry.Object, sub):
            self.face = (entry.Object, sub)
            self.error.hide()
            self._note_face()
            try:
                from . import holewizard
                if entry.PickedPoints:
                    holewizard.note_click(entry.Object, sub, entry.PickedPoints[-1])
            except Exception as _fw_err:
                _fw_log("holespec.py:2405", _fw_err)
            if self.tabs.currentIndex() == 1:
                self._go(*self.face)
            return
        if self.tabs.currentIndex() == 1:
            Gui.Selection.clearSelection()
            self.error.setText("That is not flat. Pick a flat face.")
            self.error.show()

    def _go(self, obj, sub):
        spec = dict(self.spec)
        remember(spec)
        self.done = True
        self._cleanup()
        Gui.Control.closeDialog()
        if self.on_positions is not None:
            QtCore.QTimer.singleShot(0, lambda: self.on_positions(obj, sub, spec))

    def _cleanup(self):
        global _active
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("holespec.py:2428", _fw_err)
        if _active is self:
            _active = None

    # ----------------------------------------------------------- dialog
    def getStandardButtons(self):
        buttons = QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        try:
            return int(buttons)
        except TypeError:
            return buttons.value

    def accept(self):
        ""
        self._take_typed()
        if self.hole is not None:
            self._apply()
            if self.opened:
                self.hole.Document.commitTransaction()
                self.opened = False
            remember(dict(self.spec))
            self.done = True
            self._cleanup()
            Gui.Control.closeDialog()
            self._leave_edit()
            return True
        if self.existing2d.isChecked() and self.existing is not None:
            source, spec, skip = self.existing, dict(self.spec), self.skipped()
            if len(skip) >= self.skip_list.count():
                self.error.setText("Every instance is skipped: leave at least one.")
                self.error.show()
                return False
            remember(spec)
            self.done = True
            self._cleanup()
            Gui.Control.closeDialog()
            QtCore.QTimer.singleShot(0, lambda: make_from_existing(source, spec, skip))
            return True
        if self.points3d:
            body, points, spec = self.body, list(self.points3d), dict(self.spec)
            remember(spec)
            self.done = True
            self._cleanup()
            Gui.Control.closeDialog()
            QtCore.QTimer.singleShot(0, lambda: make_on_points(body, points, spec))
            return True
        if self.sketch is not None:

            sketch, spec = self.sketch, dict(self.spec)
            remember(spec)
            self.done = True
            self._cleanup()
            Gui.Control.closeDialog()
            QtCore.QTimer.singleShot(0, lambda: make(sketch, spec))
        elif self.face is not None:
            face = self.face
            QtCore.QTimer.singleShot(0, lambda: self._go(*face))
        else:
            self.tabs.setCurrentIndex(1)
        return False

    def reject(self):
        self.done = True
        self._cleanup()
        if self.hole is not None:
            if self.opened:
                self.hole.Document.abortTransaction()
                self.opened = False
                self.hole.Document.recompute()
            Gui.Control.closeDialog()
            self._leave_edit()
            return True
        Gui.Control.closeDialog()
        return True


def active():
    return _active


def show(body, face=None, on_positions=None, sketch=None):
    panel = HoleSpecPanel(body, face, on_positions, sketch=sketch)
    Gui.Control.showDialog(panel)
    _no_header(panel.form)
    return panel


def _no_header(form, tries=10):
    ""

    try:
        group = form.parentWidget()
        while group is not None and not group.inherits("QSint::ActionGroup"):
            group = group.parentWidget()
    except RuntimeError as _fw_err:
        _fw_log("holespec.py:2532", _fw_err)
        return
    if group is None:
        if tries > 0:
            QtCore.QTimer.singleShot(100, lambda: _no_header(form, tries - 1))
        return
    for child in group.children():
        if isinstance(child, QtWidgets.QWidget) and child.inherits("QSint::TaskHeader"):
            child.hide()


def edits(hole):
    """True when Edit Feature on hole reopens the Hole Wizard (a hole it made)."""
    try:
        return hole.TypeId == "PartDesign::Hole" and stored(hole) is not None and enabled()
    except Exception:
        return False


def edit(hole):
    """Edit Feature on a Hole Wizard hole: the Type tab again, filled, OK changes the hole."""
    body = _body_of(hole)
    if body is None:
        return None
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    panel = HoleSpecPanel(body, None, None, hole=hole)
    Gui.Control.showDialog(panel)
    _no_header(panel.form)
    return panel


try:                     # a suppressed Hole Wizard hole takes its cosmetic threads with it (holegroup.py)
    from . import holegroup as _holegroup
    _holegroup.watch()
except Exception as _fw_err:
    _fw_log("holespec.py:2557", _fw_err)
