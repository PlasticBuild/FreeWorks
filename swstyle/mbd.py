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
import math

import FreeCAD as App
import Part

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
    from . import pmboxes
except ImportError:
    Gui = None

V = App.Vector
FOLDER = "Annotations"
HIDE_GHOST = {}              # document name -> names of hidden annotations shown grey (Hide/Show Annotations)
TOL = 0.1                    # default ± tolerance, mm
GTOL_SYMBOLS = {"Position": "⌖", "Flatness": "⏥", "Perpendicularity": "⟂", "Parallelism": "∥",
                "Profile of a Surface": "⌓", "Circularity": "○", "Cylindricity": "⌭",
                "Concentricity": "◎", "Straightness": "⏤", "Angularity": "∠",
                "Total Runout": "⌰", "Circular Runout": "↗", "Symmetry": "⌯"}
KINDS = ("Size", "Location", "Angle", "BasicLocation", "BasicSize", "Datum", "DatumTarget", "GTol", "Pattern",
         "Note", "SurfaceFinish", "Weld", "Reference")
MATERIAL = {"None": "", "MMC": "Ⓜ", "LMC": "Ⓛ", "RFS": "Ⓢ", "Free state": "Ⓕ", "Projected": "Ⓟ",
            "Tangent plane": "Ⓣ"}
TOLERANCE_TYPES = ("Bilateral", "Symmetric", "Limit", "Basic", "MIN", "MAX", "None")
FIT_TYPES = ("Fit", "Fit with tolerance", "Fit (tolerance only)")
TOLERANCED = ("Size Dimension", "Location Dimension", "Angle Dimension", "Pattern Feature")
MATERIAL_CONDITIONS = ("None", "MMC", "LMC", "RFS")
MODIFIERS = ("None", "Free state", "Projected", "Tangent plane")


# --------------------------------------------------------------------- the PMI object
class PMI:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyString", "Kind", "PMI", "Size, Location, Angle, Basic..., Datum, DatumTarget, GTol, Pattern")
        add("App::PropertyLinkSubListGlobal", "References", "PMI", "The faces / edges it annotates")
        add("App::PropertyString", "Text", "PMI", "What it says")
        add("App::PropertyVector", "TextPosition", "PMI", "Where its text is")
        add("App::PropertyFloat", "Value", "PMI", "Its nominal value (mm or degrees)")
        add("App::PropertyFloat", "Plus", "PMI", "Upper tolerance")
        add("App::PropertyFloat", "Minus", "PMI", "Lower tolerance")
        add("App::PropertyString", "SWStyleKind", "Base", "")
        _extra(obj)
        obj.SWStyleKind = "PMI"
        obj.setEditorMode("SWStyleKind", 2)
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, _state):
        return None


def _extra(obj):
    """AutoText (the text it was made with: a different Text is an override) and CreatedView (the
    view direction it was made in, for Detailing > Display items only in the view...)."""
    if "AutoText" not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", "AutoText", "PMI", "The text it was made with")
        obj.setEditorMode("AutoText", 2)
    if "Configurations" not in obj.PropertiesList:
        obj.addProperty("App::PropertyStringList", "Configurations", "PMI",
                        "Configurations it shows in (empty: all); Copy Scheme fills it")
    if "CreatedView" not in obj.PropertiesList:
        obj.addProperty("App::PropertyVector", "CreatedView", "PMI", "View direction it was made in")
        obj.setEditorMode("CreatedView", 2)


ARROWED = ("Size", "Location", "Angle", "BasicLocation", "BasicSize", "GTol", "Pattern", "Note", "Reference", "Weld")


class PMIView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        from pivy import coin
        self.obj = vobj.Object
        self.root = coin.SoSeparator()
        self.colour = coin.SoBaseColor()
        self.colour.rgb.setValue(0.0, 0.35, 0.85)
        style = coin.SoDrawStyle()
        style.lineWidth.setValue(1.5)
        self.style = style
        self.coords = coin.SoCoordinate3()
        self.lines = coin.SoLineSet()
        self.at = coin.SoTranslation()
        self.label = coin.SoText2()            # Detailing > Always display text at the same size
        self.label3 = coin.SoAsciiText()       # off: text sized in the model (3.5 mm)
        self.font = coin.SoFont()
        self.font.size.setValue(14)
        self.text_switch = coin.SoSwitch()
        self.text_switch.addChild(self.label)
        model = coin.SoSeparator()
        self.font3 = coin.SoFont()
        self.font3.size.setValue(3.5)
        model.addChild(self.font3)
        model.addChild(self.label3)
        self.text_switch.addChild(model)
        self.text_switch.whichChild = 0
        text = coin.SoSeparator()
        text.addChild(self.at)
        text.addChild(self.font)
        text.addChild(self.text_switch)
        self.shown = coin.SoSwitch()           # Detailing > Hide dangling dimensions and annotations
        self.shown.whichChild = -3
        self.arrow = coin.SoSeparator()         # Dimensions > Arrows
        body = coin.SoSeparator()
        self.depth = coin.SoDepthBuffer()      # System Options > Display > DimXpert dimensions on top of model
        body.addChild(self.depth)
        for n in (self.colour, style, self.coords, self.lines, self.arrow, text):
            body.addChild(n)
        self.shown.addChild(body)
        self.root.addChild(self.shown)
        vobj.addDisplayMode(self.root, "Default")
        self.updateData(self.obj, "Text")

    def getDisplayModes(self, _vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def updateData(self, obj, prop):
        if not hasattr(self, "label"):
            return
        anchor = anchor_of(obj)
        tp = obj.TextPosition
        try:
            pts = leader_points(obj, anchor, tp)
        except Exception:
            pts = [anchor, tp]
        self.coords.point.setNum(len(pts))
        self.coords.point.setValues(0, len(pts), [tuple(p) for p in pts])
        self.lines.numVertices.setValues(0, 1, [len(pts)])
        self.leader = pts
        self.at.translation.setValue(tuple(tp))
        lines = datum_text(obj, str(obj.Text)).split("\n")
        self.label.string.setValues(0, len(lines), lines)
        if hasattr(self, "label3"):
            self.label3.string.setValues(0, len(lines), lines)
            self.restyle(obj)
        self._colour(obj)
        if hasattr(self, "arrow"):
            self._arrow(obj, anchor, tp)

    def _colour(self, obj):
        if obj.Name in HIDE_GHOST.get(obj.Document.Name, set()):
            self.colour.rgb.setValue(0.62, 0.62, 0.62)       # hidden: grey while Hide/Show Annotations runs
            return
        if overridden(obj) and bool(_dp(obj.Document, "Dimensions",
                                        "Highlight overridden dimensions in a different color", True)):
            self.colour.rgb.setValue(*OVERRIDDEN)
        elif obj.Kind in ("Datum", "DatumTarget"):
            self.colour.rgb.setValue(0.1, 0.55, 0.1)
        elif obj.Kind == "GTol":
            self.colour.rgb.setValue(0.6, 0.1, 0.6)
        else:
            self.colour.rgb.setValue(0.0, 0.35, 0.85)

    def _arrow(self, obj, anchor, tp):
        """The arrowhead at the model end of the leader, as Dimensions > Arrows says."""
        from pivy import coin
        self.arrow.removeAllChildren()
        if obj.Kind not in ARROWED:
            return
        pts = getattr(self, "leader", None) or [anchor, tp]
        d = anchor - pts[1]            # the arrow points along the leader's first leg
        if d.Length < 1e-9:
            return
        d.normalize()
        a = arrow_style(obj.Document)
        own = annotation_arrow(obj)
        if own is not None:
            if own == "None":
                return
            a = dict(a, style=own)
        length, width = a["length"], a["width"]
        tr = coin.SoTransform()
        tr.translation.setValue(tuple(anchor - d * (length / 2.0)))
        tr.rotation.setValue(coin.SbRotation(coin.SbVec3f(0, 1, 0), coin.SbVec3f(*tuple(d))))
        self.arrow.addChild(tr)
        if a["style"] == "Dot":
            sp = coin.SoSphere()
            sp.radius.setValue(width / 2.0)
            self.arrow.addChild(sp)
        elif a["style"] in ("Open", "Slash"):
            co = coin.SoCoordinate3()
            h = length / 2.0
            if a["style"] == "Open":
                pts = [(-width / 2.0, -h, 0), (0, h, 0), (width / 2.0, -h, 0)]
                n = 3
            else:
                pts = [(-width, -h, 0), (width, h, 0)]
                n = 2
            co.point.setValues(0, n, pts)
            ls = coin.SoLineSet()
            ls.numVertices.setValues(0, 1, [n])
            self.arrow.addChild(co)
            self.arrow.addChild(ls)
        else:                                   # Filled, Datum triangle
            cone = coin.SoCone()
            cone.height.setValue(length)
            cone.bottomRadius.setValue(width / 2.0)
            self.arrow.addChild(cone)

    def onChanged(self, _vobj, _prop):
        pass

    def restyle(self, obj):
        """Document Properties: the font of the annotation's page, text size mode, dangling ones hidden."""
        doc = obj.Document
        page = {"Datum": "Datums", "DatumTarget": "Datums", "GTol": "Geometric Tolerances"}.get(obj.Kind, "Dimensions")
        font = str(_dp(doc, page, "Font", "") or _dp(doc, "Dimensions", "Font", "Century Gothic"))
        self.font.name.setValue(font)
        self.font3.name.setValue(font)
        same = bool(_dp(doc, "Detailing", "Always display text at the same size", True))
        try:        # System Options > Display > Display notes flat to screen (off: the text lies in the model)
            from . import optionspages as _op
            same = same and bool(_op.stored("Fixed", "Display notes flat to screen", True))
        except Exception as _fw_err:
            _fw_log("mbd.py:248", _fw_err)
        self.text_switch.whichChild = 0 if same else 1
        if hasattr(self, "depth"):
            try:
                from . import optionspages as _op
                top = bool(_op.stored("Display", "Display DimXpert dimensions on top of model", False))
            except Exception:
                top = False
            self.depth.test.setValue(not top)
        if hasattr(self, "style"):
            self.style.lineWidth.setValue(leader_width(obj))
        hide = bool(_dp(doc, "Detailing", "Hide dangling dimensions and annotations", False)) and dangling(obj)
        hide = hide or not in_created_view(obj) or not in_configuration(obj)
        try:
            hide = hide or hidden_as_redundant(obj)
        except Exception as _fw_err:
            _fw_log("mbd.py:264", _fw_err)
        self.shown.whichChild = -1 if hide else -3
        stack = str(obj.Text)
        if "/" in stack and any(ch.isdigit() for ch in stack):
            self.font3.size.setValue(3.5 * _percent(_dp(doc, "Dimensions", "Stack size", "100%")))
        self._colour(obj)
        try:
            self._arrow(obj, anchor_of(obj), obj.TextPosition)
        except Exception as _fw_err:
            _fw_log("mbd.py:273", _fw_err)

    def getIcon(self):
        return ":/icons/TechDraw_Dimension.svg"

    def dumps(self):
        return None

    def loads(self, _state):
        return None


def dangling(obj):
    """An annotation whose model element is gone."""
    try:
        for o, subs in obj.References:
            if o is None:
                return True
            for sub in subs or [""]:
                if not sub:
                    continue
                try:
                    if o.Shape.getElement(sub.split(".")[-1]) is None:
                        return True
                except Exception as _fw_err:
                    _fw_log("mbd.py:299", _fw_err)
                    return True
        return not obj.References
    except Exception as _fw_err:
        _fw_log("mbd.py:303", _fw_err)
        return True


DIMENSION_KINDS = ("Size", "Location", "Angle", "BasicLocation", "BasicSize", "Pattern")


def _ref_key(obj):
    out = []
    for o, subs in obj.References or []:
        for sub in (subs if isinstance(subs, (list, tuple)) else [subs]) or [""]:
            out.append((getattr(o, "Name", ""), sub.split(".")[-1] if sub else ""))
    return tuple(sorted(out))


def redundant(obj):
    """A dimension or tolerance that says again what an earlier one says: the same kind (a size, a
    location, a tolerance of the same symbol) on the same model elements."""
    if not is_pmi(obj) or obj.Document is None:
        return False
    key = _ref_key(obj)
    if not key:
        return False
    is_dim = obj.Kind in DIMENSION_KINDS
    group = ("Size", "BasicSize") if obj.Kind in ("Size", "BasicSize") else \
        ("Location", "BasicLocation") if obj.Kind in ("Location", "BasicLocation") else (obj.Kind,)
    symbol = str(obj.Text).split("|")[1] if obj.Kind == "GTol" and "|" in str(obj.Text) else None
    for o in obj.Document.Objects:
        if o is obj:
            return False             # only the earlier ones count
        if not is_pmi(o) or o.Kind not in group or _ref_key(o) != key:
            continue
        if obj.Kind == "GTol" and (str(o.Text).split("|")[1] if "|" in str(o.Text) else None) != symbol:
            continue
        return is_dim or obj.Kind == "GTol"
    return False


def hidden_as_redundant(obj):
    """DimXpert > Display Options: Dimensions, redundant / Tolerances, redundant (Hide or Show)."""
    if obj.Kind in DIMENSION_KINDS:
        row = "Dimensions, redundant"
    elif obj.Kind == "GTol":
        row = "Tolerances, redundant"
    else:
        return False
    return str(_dp(obj.Document, "Display Options", row, "Hide")) == "Hide" and redundant(obj)


OVERRIDDEN = (0.65, 0.35, 0.0)    # Highlight overridden dimensions in a different color


def overridden(obj):
    auto = getattr(obj, "AutoText", "")
    return bool(auto) and str(obj.Text) != auto


def _percent(text):
    try:
        return max(0.1, float(str(text).strip().rstrip("%")) / 100.0)
    except ValueError:
        return 1.0


def arrow_style(doc):
    """Dimensions > Arrows: width, length (with extension when placed outside), style, scaled to the
    text height when asked."""
    length = float(_dp(doc, "Dimensions", "Arrow length", 3.3))
    placement = str(_dp(doc, "Dimensions", "Arrow placement", "Smart"))
    if placement == "Outside":
        length = float(_dp(doc, "Dimensions", "Arrow length with extension", 6.35))
    width = float(_dp(doc, "Dimensions", "Arrow width", 1.0))
    if bool(_dp(doc, "Dimensions", "Scale with dimension height", False)):
        k = 3.5 / 2.5            # text height 3.5 mm against the 2.5 mm the arrow sizes are for
        length, width = length * k, width * k
    return {"length": length, "width": width, "style": str(_dp(doc, "Dimensions", "Arrow style", "Filled")),
            "placement": placement}


ANNOTATION_KINDS = ("Datum", "DatumTarget", "GTol", "SurfaceFinish", "Weld")
THICKNESS = {"Thin": 1.0, "Normal": 1.6, "Thick": 2.6}


def leader_width(obj):
    """Annotations > Leader thickness for annotations and notes; Geometric Tolerances > Frame
    thickness for a tolerance frame; dimensions keep their thin line."""
    doc, kind = obj.Document, obj.Kind
    if kind == "GTol":
        return THICKNESS.get(str(_dp(doc, "Geometric Tolerances", "Frame thickness", "Thin")), 1.0)
    if kind in ANNOTATION_KINDS or kind == "Note":
        return THICKNESS.get(str(_dp(doc, "Annotations", "Leader thickness", "Thin")), 1.0)
    return 1.5


def annotation_arrow(obj):
    """Annotations > Attachments: the leader end of an annotation by what it is attached to:
    Edge/vertex, Face/surface or Unattached (Filled, Open, Dot or None). Dimensions keep
    Dimensions > Arrows."""
    if obj.Kind not in ANNOTATION_KINDS and obj.Kind != "Note":
        return None
    subs = [x for _o, ss in (obj.References or []) for x in (ss if isinstance(ss, (list, tuple)) else [ss])]
    leaf = subs[0].split(".")[-1] if subs else ""
    if not subs:
        row, default = "Unattached", "Filled"
    elif leaf.startswith("Face"):
        row, default = "Face/surface", "Dot"
    else:
        row, default = "Edge/vertex", "Filled"
    return str(_dp(obj.Document, "Annotations", row, default))


def bent_leader(obj):
    """(on, shoulder length): Notes > Use bent leaders and Bent leader length for a note; Annotations >
    Use bent leaders and Leader length for the other annotations; Linear > Use bent leaders and
    Dimensions > Leader length for a dimension."""
    doc, kind = obj.Document, obj.Kind
    if kind == "Note":
        on, length = _dp(doc, "Notes", "Use bent leaders", False), _dp(doc, "Notes", "Bent leader length", 6.35)
    elif kind in ANNOTATION_KINDS:
        on, length = _dp(doc, "Annotations", "Use bent leaders", False), _dp(doc, "Annotations", "Leader length", 6.35)
    else:
        on, length = _dp(doc, "Linear", "Use bent leaders", False), _dp(doc, "Dimensions", "Leader length", 6.35)
    try:
        return bool(on), float(length)
    except (TypeError, ValueError):
        return bool(on), 6.35


def _screen_right():
    try:
        return Gui.ActiveDocument.ActiveView.getCameraOrientation().multVec(V(1, 0, 0))
    except Exception:
        return V(1, 0, 0)


def leader_points(obj, anchor, tp):
    """The leader from the model to the text: straight, or bent with a horizontal shoulder (in the
    screen's horizontal) of the leader length just before the text."""
    on, length = bent_leader(obj)
    if not on or length <= 0 or (tp - anchor).Length < 1e-9:
        return [anchor, tp]
    right = _screen_right()
    side = 1.0 if (tp - anchor).dot(right) >= 0 else -1.0
    knee = tp - right * (side * length)
    return [anchor, knee, tp]


def datum_text(obj, text):
    """Datums > Display type: Round (GB) shows the letter in a circle, Square (and per standard for
    ANSI/ISO) in a box."""
    if obj.Kind not in ("Datum", "DatumTarget"):
        return text
    kind = str(_dp(obj.Document, "Datums", "Display type", "Per Standard"))
    if kind == "Round (GB)":
        return "(%s)" % text
    if kind == "Square":
        return "[%s]" % text
    return text


VIEW_LIMIT = 0.966              # cos 15°: the view counts as the one the annotation was made in


def view_direction():
    try:
        v = Gui.ActiveDocument.ActiveView.getViewDirection()
        return V(v[0], v[1], v[2])
    except Exception as _fw_err:
        _fw_log("mbd.py:471", _fw_err)
        return None


def in_created_view(obj, view=None):
    """Detailing > Display items only in the view in which they are created."""
    if not bool(_dp(obj.Document, "Detailing", "Display items only in the view in which they are created", False)):
        return True
    made = getattr(obj, "CreatedView", None)
    made = V(made) if made is not None else None        # a copy: normalising the property would notify
    if made is None or made.Length < 1e-9:
        return True
    view = view if view is not None else view_direction()
    if view is None or view.Length < 1e-9:
        return True
    return V(made).normalize().dot(V(view).normalize()) >= VIEW_LIMIT


def in_configuration(obj):
    """The annotation belongs to the configuration shown (Copy Scheme gives schemes per configuration)."""
    cfgs = list(getattr(obj, "Configurations", []) or [])
    if not cfgs:
        return True
    try:
        from . import configmanager
        t = configmanager.table(obj.Document)
        return t is None or t.active() in cfgs
    except Exception as _fw_err:
        _fw_log("mbd.py:499", _fw_err)
        return True


def tolerance_text(doc, value, ttype, plus, minus, precision=None, prefix="", suffix="", angle=False):
    """The DimXpert PropertyManager's Tolerance/Precision: Bilateral (+a/-b), Symmetric (±a), Limit
    (upper over lower), Basic (boxed), MIN, MAX or None, with Dimension Text prefix and suffix."""
    def n(v):
        if precision is not None:
            if not angle:
                from . import docstyle
                v = docstyle.in_units(doc or App.ActiveDocument, v)
            return "%.*f" % (precision, v)
        return ("%.1f" % v) if angle else _num(v)

    def tn(v):
        """A tolerance value: Document Properties > Dimensions, Primary tolerance precision and
        Trailing zeroes, tolerances (the dimension's own precision, when given, wins)."""
        if precision is not None or angle:
            return n(v)
        return _tol_num(doc, v)
    unit = "°" if angle else ""
    v = n(value) + unit
    if ttype == "Symmetric":
        body = "%s ±%s%s" % (v, tn(plus), unit)
    elif ttype == "Limit":
        body = "%s%s\n%s%s" % (n(value + plus), unit, n(value + minus), unit)
    elif ttype == "Basic":
        body = "[%s]" % v
    elif ttype == "MIN":
        body = "%s MIN" % v
    elif ttype == "MAX":
        body = "%s MAX" % v
    elif ttype == "None":
        body = v
    else:
        body = "%s +%s/%s" % (v, tn(plus), tn(minus)) if abs(plus + minus) > 1e-9 else "%s ±%s%s" % (v, tn(plus), unit)
    return prefix + body + suffix


def restyle_all(doc):
    for o in doc.Objects:
        if is_pmi(o) and o.ViewObject is not None and hasattr(o.ViewObject.Proxy, "restyle"):
            try:
                o.ViewObject.Proxy.restyle(o)
            except Exception as _fw_err:
                _fw_log("mbd.py:537", _fw_err)


# extapps135: what each MBD tool does, as its tooltip ("Size Dimension: ..."), not "MBD: Size Dimension on the model"
TIPS = {
    "SWStyle_MBDSize": "Size Dimension: Adds the size of the picked hole, boss or face to the model.",
    "SWStyle_MBDLocation": "Location Dimension: Adds the distance between two picked items to the model.",
    "SWStyle_MBDAngle": "Angle Dimension: Adds the angle between two picked faces or edges.",
    "SWStyle_MBDBasicLocation": "Basic Location Dimension: Adds an exact (boxed) distance between two items.",
    "SWStyle_MBDBasicSize": "Basic Size Dimension: Adds an exact (boxed) size to a hole, boss or face.",
    "SWStyle_MBDPattern": "Pattern Feature: Dimensions a pattern of holes with its count and spacing.",
    "SWStyle_MBDDatum": "Datum: Marks a face as a datum feature (A, B, C...).",
    "SWStyle_MBDDatumTarget": "Datum Target: Marks the point, line or area that touches the datum.",
    "SWStyle_MBDGeometricTolerance": "Geometric Tolerance: Adds a feature control frame to the picked face.",
    "SWStyle_MBDReferenceDimension": "Reference Dimension: Adds a distance in parentheses that does not drive the part.",
    "SWStyle_MBDNote": "Note: Adds text to the model, with a leader to the picked item.",
    "SWStyle_MBDSurfaceFinish": "Surface Finish: Adds a surface texture symbol to the picked face.",
    "SWStyle_MBDWeldSymbol": "Weld Symbol: Adds a weld symbol to the picked edge or face.",
    "SWStyle_MBDAutoPair": "Auto Pair Tolerance: Pairs the tolerance of a hole with the others of its pattern.",
}


def is_pmi(obj):
    return getattr(obj, "SWStyleKind", "") == "PMI"


def _elements(obj):
    out = []
    for o, subs in obj.References or []:
        shape = o.Shape
        for s in (subs if isinstance(subs, (list, tuple)) else [subs]):
            try:
                out.append(shape.getElement(s.split(".")[-1]) if s else shape)
            except Exception as _fw_err:
                _fw_log("mbd.py:552", _fw_err)
    return out


def anchor_of(obj):
    els = _elements(obj)
    if not els:
        return obj.TextPosition
    pts = [e.CenterOfMass if hasattr(e, "CenterOfMass") else e.Point for e in els]
    return sum(pts, V()) * (1.0 / len(pts))


def _folder(doc):
    for o in doc.Objects:
        if o.TypeId == "App::DocumentObjectGroup" and o.Label == FOLDER:
            return o
    g = doc.addObject("App::DocumentObjectGroup", "Annotations")
    g.Label = FOLDER
    return g


def _normal(face):
    u0, u1, v0, v1 = face.ParameterRange
    return face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)


def place(doc, obj, base, at):
    """Where an annotation's text goes: Offset from model off the part (along the snap angle for a
    radial/diameter leader), then Offset between dimensions past any text already there."""
    gap = float(_dp(doc, "Dimensions", "Offset from model", 6.0))
    step = float(_dp(doc, "Dimensions", "Offset between dimensions", 10.0))
    c = base.BoundBox.Center if base is not None else V()
    d = at - c
    if d.Length < 1e-6:
        d = V(0, 0, 1)
    d.normalize()
    els = _elements(obj)
    face = els[0] if els else None
    axis = getattr(getattr(face, "Surface", None), "Axis", None)
    if axis is not None and "Cylinder" in type(face.Surface).__name__:
        d = snap_leader(d, axis, float(_dp(doc, "Dimensions", "Leader snap angle", 15.0)))
    # the edge of the part along d
    reach = 0.0
    if base is not None:
        bb = base.BoundBox
        for x in (bb.XMin, bb.XMax):
            for y in (bb.YMin, bb.YMax):
                for z in (bb.ZMin, bb.ZMax):
                    reach = max(reach, (V(x, y, z) - at).dot(d))
    pos = at + d * (reach + gap)
    others = [o.TextPosition for o in doc.Objects if is_pmi(o) and o is not obj]
    for _i in range(20):
        if all((p - pos).Length >= step * 0.5 for p in others):
            break
        pos = pos + d * step
    return pos


def snap_leader(d, axis, snap):
    """Radial/Diameter leader snap angle: the leader's angle around the hole axis in snap steps."""
    import math
    a = V(axis).normalize()
    u = d - a * d.dot(a)
    if u.Length < 1e-9 or snap <= 0:
        return d
    ref = V(1, 0, 0) if abs(a.x) < 0.9 else V(0, 1, 0)
    e1 = (ref - a * ref.dot(a)).normalize()
    e2 = a.cross(e1)
    ang = math.atan2(u.dot(e2), u.dot(e1))
    step = math.radians(snap)
    ang = round(ang / step) * step
    out = e1 * math.cos(ang) + e2 * math.sin(ang)
    return out.normalize()


def _out_of(shape, at, size):
    """A text position just off the part, away from its centre."""
    c = shape.BoundBox.Center if shape is not None else V()
    d = at - c
    if d.Length < 1e-6:
        d = V(0, 0, 1)
    d.normalize()
    return at + d * size


def make(doc, kind, refs, text, value=0.0, plus=TOL, minus=-TOL, position=None):
    """refs: [(object, element name)]."""
    obj = doc.addObject("App::FeaturePython", "PMI")
    PMI(obj)
    obj.Kind = kind
    obj.References = [(o, [s]) for o, s in refs]
    obj.Text = text
    obj.Value, obj.Plus, obj.Minus = value, plus, minus
    base = refs[0][0].Shape if refs else None
    at = anchor_of(obj) if refs else V()
    obj.AutoText = text
    view = view_direction()
    if view is not None:
        obj.CreatedView = view
    obj.TextPosition = position if position is not None else place(doc, obj, base, at)
    names = {"Size": "Size Dimension", "Location": "Location Dimension", "Angle": "Angle Dimension",
             "BasicLocation": "Basic Location Dimension", "BasicSize": "Basic Size Dimension", "Datum": "Datum",
             "DatumTarget": "Datum Target", "GTol": "Geometric Tolerance", "Pattern": "Pattern Feature",
             "Note": "Note", "SurfaceFinish": "Surface Finish", "Weld": "Weld Symbol", "Reference": "Reference Dimension"}
    n = 1 + sum(1 for o in doc.Objects if is_pmi(o) and o.Kind == kind and o is not obj)
    obj.Label = "%s%d" % (names[kind].replace(" ", ""), n) if kind not in ("Datum", "DatumTarget") else \
        "%s %s" % (names[kind], text)
    _folder(doc).addObject(obj)
    if App.GuiUp:
        PMIView(obj.ViewObject)
    doc.recompute()
    return obj


def _dp(doc, page, text, default):
    try:
        from . import optionspages
        return optionspages.doc_value(doc or App.ActiveDocument, page, text, default)
    except Exception as _fw_err:
        _fw_log("mbd.py:676", _fw_err)
        return default


def default_tol(doc=None):
    """Document Properties > DimXpert: Block tolerance, length (Methods Block Tolerance), else TOL."""
    if str(_dp(doc, "DimXpert", "Methods", "Block Tolerance")) == "Block Tolerance":
        try:
            return float(_dp(doc, "DimXpert", "Block tolerance, length", TOL))
        except (TypeError, ValueError) as _fw_err:
            _fw_log("mbd.py:680", _fw_err)
    return TOL


def default_angle_tol(doc=None):
    try:
        return float(_dp(doc, "DimXpert", "Block tolerance, angle", 0.5))
    except (TypeError, ValueError):
        return 0.5


def basic_by_default(doc=None):
    """Location Dimension > Create basic dimension, or Display Options > Display as Basic dimensions."""
    return bool(_dp(doc, "Location Dimension", "Create basic dimension", False)) or \
        bool(_dp(doc, "Display Options", "Display as Basic dimensions", False))


def default_gtol(doc=None, symbol="Position"):
    row = {"Position": "Position tolerance", "Profile of a Surface": "Profile tolerance",
           "Profile of a Line": "Profile tolerance"}.get(symbol)
    if row is None and symbol in ("Flatness", "Straightness", "Circularity", "Cylindricity"):
        row = "Primary datums, tolerance"
    try:
        return float(_dp(doc, "Geometric Tolerance", row, 0.1)) if row else 0.1
    except (TypeError, ValueError):
        return 0.1


def _tol_num(doc, value):
    """A tolerance as Document Properties > Dimensions says: Primary tolerance precision (Same as
    nominal, or its own places) and Trailing zeroes, tolerances (Smart, Show, Remove, Standard)."""
    try:
        from . import docstyle
        doc = doc or App.ActiveDocument
        st = docstyle.part_style(doc)
        text = str(_dp(doc, "Dimensions", "Primary tolerance precision", "Same as nominal"))
        dec = st["precision"] if text == "Same as nominal" else docstyle._decimals(text)
        trailing = str(_dp(doc, "Dimensions", "Trailing zeroes, tolerances", "Show"))
        shown = docstyle.in_units(doc, value)
        while value and dec < 6 and round(abs(shown), dec) == 0:      # extapps116: a tolerance never reads +-0.00
            dec += 1
        return docstyle.number(shown, dec, st["leading"], trailing)
    except Exception:
        return _num(value)


def _num(value, tolerance=False):
    """A length (mm) as Document Properties > Dimensions says (precision, leading/trailing zeroes), in the
    document's length unit (Document Properties > Units). A tolerance (extapps116) gets places until it shows
    something: 0.1 mm in an inch part is 0.0039, never 0.00."""
    try:
        from . import docstyle
        doc = App.ActiveDocument
        if docstyle.fractional(doc):
            return docstyle.fraction(value / docstyle.INCH, doc)
        st = docstyle.part_style(doc)
        shown, dec = docstyle.in_units(doc, value), st["precision"]
        while tolerance and value and dec < 6 and round(abs(shown), dec) == 0:
            dec += 1
        return docstyle.number(shown, dec, st["leading"], "Show")
    except Exception:
        return "%.2f" % value


def _tol_text(value, plus, minus, prefix=""):
    if abs(plus + minus) < 1e-9:
        text = "%s%s ±%s" % (prefix, _num(value), _num(plus, True))
    else:
        text = "%s%s +%s/%s" % (prefix, _num(value), _num(plus, True), _num(minus, True))
    try:
        from . import docstyle
        st = docstyle.part_style(App.ActiveDocument)
        if st["upper_dims"]:
            text = docstyle.upper(text, st["exclusions"])
    except Exception as _fw_err:
        _fw_log("mbd.py:747", _fw_err)
    return text


# --------------------------------------------------------------------- measuring
def size_of(face):
    """(value, prefix, kind) of a face's size: a cylinder's diameter, a sphere's, else its thickness."""
    s = face.Surface
    if s.TypeId == "Part::GeomCylinder":
        return 2 * s.Radius, "⌀", "diameter"
    if s.TypeId == "Part::GeomSphere":
        return 2 * s.Radius, "S⌀", "diameter"
    if s.TypeId == "Part::GeomCone":
        return math.degrees(2 * s.SemiAngle), "", "angle"
    return None, "", None


def thickness(shape, face):
    """A planar face's width across the body: the distance to the parallel face opposite."""
    n = _normal(face)
    best = None
    for g in shape.Faces:
        if g.isSame(face) or g.Surface.TypeId != "Part::GeomPlane":
            continue
        m = _normal(g)
        if abs(abs(n.dot(m)) - 1) < 1e-6 and n.dot(m) < 0:
            d = abs((g.CenterOfMass - face.CenterOfMass).dot(n))
            if best is None or d < best[0]:
                best = (d, g)
    return best


def drafted(shape, face, most=30.0):
    """A drafted slab or slot: the planar face opposite that leans back at most `most` degrees in all.
    (width at mid-height, draft angle of each side, the other face) or None."""
    if face.Surface.TypeId != "Part::GeomPlane":
        return None
    n = _normal(face)
    best = None
    for g in shape.Faces:
        if g.isSame(face) or g.Surface.TypeId != "Part::GeomPlane":
            continue
        m = _normal(g)
        between = math.degrees(n.getAngle(m * -1))
        if not 1e-3 < between <= most:
            continue
        mid = (n - m)
        if mid.Length < 1e-9:
            continue
        mid.normalize()
        width = abs((g.CenterOfMass - face.CenterOfMass).dot(mid))
        if best is None or width < best[0]:
            best = (width, between / 2.0, g)
    return best


def distance(a, b):
    if a.ShapeType == "Face" and b.ShapeType == "Face" and a.Surface.TypeId == "Part::GeomPlane" and \
            b.Surface.TypeId == "Part::GeomPlane":
        n = _normal(a)
        return abs((b.CenterOfMass - a.CenterOfMass).dot(n))
    pa = a.Surface.Center if a.ShapeType == "Face" and hasattr(a.Surface, "Center") and \
        a.Surface.TypeId == "Part::GeomCylinder" else None
    pb = b.Surface.Center if b.ShapeType == "Face" and hasattr(b.Surface, "Center") and \
        b.Surface.TypeId == "Part::GeomCylinder" else None
    if pa is not None and b.ShapeType == "Face" and b.Surface.TypeId == "Part::GeomPlane":
        return abs((pa - b.CenterOfMass).dot(_normal(b)))
    if pb is not None and a.ShapeType == "Face" and a.Surface.TypeId == "Part::GeomPlane":
        return abs((pb - a.CenterOfMass).dot(_normal(a)))
    if pa is not None and pb is not None:
        axis = a.Surface.Axis
        d = pb - pa
        return (d - axis * d.dot(axis)).Length
    return a.distToShape(b)[0]


def angle(a, b):
    na = _normal(a) if a.ShapeType == "Face" else (a.Vertexes[-1].Point - a.Vertexes[0].Point)
    nb = _normal(b) if b.ShapeType == "Face" else (b.Vertexes[-1].Point - b.Vertexes[0].Point)
    ang = math.degrees(na.getAngle(nb))
    return min(ang, 180 - ang) if a.ShapeType == "Edge" else 180 - ang if ang > 90 else ang


def _el(obj, sub):
    return obj.Shape.getElement(sub.split(".")[-1])


# --------------------------------------------------------------------- the tab's commands, as functions
def size_dimension(doc, obj, sub, plus=None, minus=None):
    plus = default_tol(doc) if plus is None else plus
    minus = -plus if minus is None else minus
    f = _el(obj, sub)
    if f.Surface.TypeId == "Part::GeomCylinder" and abs(f.ParameterRange[1] - f.ParameterRange[0]) < 6.0 and \
            not _is_hole(obj.Shape, f):
        return fillet_dimension(doc, obj, sub, plus, minus)       # a fillet: by its radius
    value, prefix, what = size_of(f)
    if value is None:
        t = thickness(obj.Shape, f)
        if t is None:
            dr = drafted(obj.Shape, f)
            if dr is None:
                raise RuntimeError("Pick a hole, a boss or a face with a parallel face opposite")

            width, draft, _other = dr
            text = _tol_text(width, plus, minus, "") + "\nDRAFT %.1f°" % draft
            return make(doc, "Size", [(obj, sub)], text, width, plus, minus)
        value = t[0]
    if what == "angle":
        a = default_angle_tol(doc)
        return make(doc, "Size", [(obj, sub)], "%.1f° ±%.1f°" % (value, a), value, a, -a)
    return make(doc, "Size", [(obj, sub)], _tol_text(value, plus, minus, prefix), value, plus, minus)


def fillet_dimension(doc, obj, sub, plus=None, minus=None):
    ""
    plus = default_tol(doc) if plus is None else plus
    minus = -plus if minus is None else minus
    f = _el(obj, sub)
    if f.Surface.TypeId != "Part::GeomCylinder":
        return size_dimension(doc, obj, sub, plus, minus)
    r = f.Surface.Radius
    if str(_dp(doc, "Size Dimension", "Fillet options", "Symmetric")) == "Asymmetric":
        # Asymmetric: the fillet's two legs, the distance it takes off each face (a round fillet: r and r)
        text = _tol_text(r, plus, minus, "").replace(_num(r), "%s X %s" % (_num(r), _num(r)), 1)
        return make(doc, "Size", [(obj, sub)], text, r, plus, minus)
    return make(doc, "Size", [(obj, sub)], _tol_text(r, plus, minus, "R"), r, plus, minus)


def _plane_through(face):
    return face.CenterOfMass, _normal(face)


def chamfer_faces(shape, width_limit=0.0):
    """[(face index, (leg on the first face, leg on the second))] of the part's chamfers: a narrow
    planar face between two planar faces at right angles, leaning towards both. Chamfer Controls >
    Width limit (when set) leaves out wider ones."""
    out = []
    faces = shape.Faces
    for i, f in enumerate(faces):
        if f.Surface.TypeId != "Part::GeomPlane":
            continue
        n = _normal(f)
        nbrs = []
        for e in f.Edges:
            if e.Curve.TypeId != "Part::GeomLine":
                continue
            for j, g in enumerate(faces):
                if j == i or g.Surface.TypeId != "Part::GeomPlane":
                    continue
                if any(e.isSame(x) for x in g.Edges):
                    nbrs.append((j, g, e))
        pair = None
        for a in range(len(nbrs)):
            for b in range(a + 1, len(nbrs)):
                ja, ga, ea = nbrs[a]
                jb, gb, eb = nbrs[b]
                na, nb = _normal(ga), _normal(gb)
                if abs(na.dot(nb)) > 1e-6 or n.dot(na) < 0.05 or n.dot(nb) < 0.05:
                    continue
                da, db = V(ea.Curve.Direction), V(eb.Curve.Direction)
                if abs(abs(da.normalize().dot(db.normalize())) - 1) > 1e-6:
                    continue
                pair = (ga, ea, gb, eb)
                break
            if pair:
                break
        if pair is None:
            continue
        ga, ea, gb, eb = pair
        pa, na = _plane_through(ga)
        pb, nb = _plane_through(gb)
        leg_a = abs((ea.Vertexes[0].Point - pb).dot(nb))    # along the first face, to the corner
        leg_b = abs((eb.Vertexes[0].Point - pa).dot(na))
        if leg_a < 1e-9 or leg_b < 1e-9:
            continue
        if width_limit > 0 and max(leg_a, leg_b) > width_limit:
            continue
        out.append((i, (leg_a, leg_b)))
    return out


def slot_faces(shape):
    """[(end face index, other end face index, width, length, centre, end centre)] of the part's
    slots: two half-round hole faces of one radius on parallel axes (a straight slot's ends)."""
    halves = []
    for i, f in enumerate(shape.Faces):
        if f.Surface.TypeId != "Part::GeomCylinder":
            continue
        span = abs(f.ParameterRange[1] - f.ParameterRange[0])
        if abs(span - math.pi) > 1e-3 or not _is_hole(shape, f):
            continue
        halves.append((i, f))
    out = []
    used = set()
    for a in range(len(halves)):
        ia, fa = halves[a]
        if ia in used:
            continue
        sa = fa.Surface
        for b in range(a + 1, len(halves)):
            ib, fb = halves[b]
            sb = fb.Surface
            if ib in used or abs(sa.Radius - sb.Radius) > 1e-6:
                continue
            ax = V(sa.Axis).normalize()
            if abs(abs(ax.dot(V(sb.Axis).normalize())) - 1) > 1e-6:
                continue
            d = sb.Center - sa.Center
            d = d - ax * d.dot(ax)
            if d.Length < 1e-6:
                continue
            ca = _feature_point(fa)
            cb = ca + d
            used.update((ia, ib))
            out.append((ia, ib, 2 * sa.Radius, d.Length + 2 * sa.Radius, (ca + cb) * 0.5, ca))
            break
    return out


def slot_dimension(doc, obj, slot, plus=None, minus=None):
    """Size Dimension > Slot dimensioning: Width and length (8.00 X 30.00) or Width only."""
    plus = default_tol(doc) if plus is None else plus
    minus = -plus if minus is None else minus
    ia, ib, width, length, _c, _e = slot
    refs = [(obj, "Face%d" % (ia + 1)), (obj, "Face%d" % (ib + 1))]
    if str(_dp(doc, "Size Dimension", "Slot dimensioning", "Width and length")) == "Width only":
        text = _tol_text(width, plus, minus)
    else:
        text = "%s X %s" % (_tol_text(width, plus, minus), _tol_text(length, plus, minus))
    return make(doc, "Size", refs, text, width, plus, minus)


def slot_location(doc, obj, slot, datum_index, plus=None, minus=None, basic=None):
    """Location Dimension > Slot location: from the datum face to the slot's Center or its End (the
    centre of the end arc nearer the datum)."""
    ia, ib, _w, _l, centre, end = slot
    face = obj.Shape.Faces[datum_index]
    n = _normal(face)
    if str(_dp(doc, "Location Dimension", "Slot location", "Center")) == "End":
        other = obj.Shape.Faces[ib]
        ends = [end, _feature_point(other)]
        at = min(ends, key=lambda p: abs((p - face.CenterOfMass).dot(n)))
        ref = ia if at is end else ib
    else:
        at, ref = centre, ia
    value = abs((at - face.CenterOfMass).dot(n))
    return chain_location(doc, (obj, "Face%d" % (datum_index + 1)), (obj, "Face%d" % (ref + 1)), value, plus, minus,
                          basic)


def chamfer_dimension(doc, obj, sub, legs, plus=None, minus=None):
    """Size Dimension > Chamfer options: Symmetric gives distance X angle (1.00 X 45°), Asymmetric
    gives both distances (1.00 X 2.00). Chamfer Controls > Use tolerance adds the ± tolerance."""
    plus = default_tol(doc) if plus is None else plus
    minus = -plus if minus is None else minus
    a, b = legs
    style = str(_dp(doc, "Size Dimension", "Chamfer options", "Symmetric"))
    if style == "Asymmetric":
        body = "%s X %s" % (_num(a), _num(b))
    else:
        body = "%s X %s°" % (_num(a), _num_angle(math.degrees(math.atan2(b, a))))
    if bool(_dp(doc, "Chamfer Controls", "Use tolerance", True)):
        body += " ±%s" % _tol_num(doc, plus)
        return make(doc, "Size", [(obj, sub)], body, a, plus, minus)
    return make(doc, "Size", [(obj, sub)], body, a, 0.0, 0.0)


def _num_angle(value):
    text = "%.1f" % value
    return text[:-2] if text.endswith(".0") else text


def location_dimension(doc, a, b, plus=None, minus=None, basic=None):
    plus = default_tol(doc) if plus is None else plus
    minus = -plus if minus is None else minus
    basic = basic_by_default(doc) if basic is None else basic
    d = distance(_el(*a), _el(*b))
    text = basic_text(doc, d) if basic else _tol_text(d, plus, minus)
    return make(doc, "BasicLocation" if basic else "Location", [a, b], text, d, 0 if basic else plus,
                0 if basic else minus)


def _feature_point(face):
    """A feature's location point: a hole's or boss's axis point at its middle, else the centre."""
    surf = face.Surface
    if surf.TypeId == "Part::GeomCylinder":
        c, a = surf.Center, V(surf.Axis).normalize()
        return c + a * (face.CenterOfMass - c).dot(a)
    return face.CenterOfMass


def chain_location(doc, a, b, value, plus=None, minus=None, basic=None):
    """A chain location dimension: the distance along one datum direction from the feature before."""
    plus = default_tol(doc) if plus is None else plus
    minus = -plus if minus is None else minus
    basic = basic_by_default(doc) if basic is None else basic
    text = basic_text(doc, value) if basic else _tol_text(value, plus, minus)
    return make(doc, "BasicLocation" if basic else "Location", [a, b], text, value, 0 if basic else plus,
                0 if basic else minus)


def basic_text(doc, value, prefix=""):
    """A basic dimension in its box: Include prefix inside basic tolerance box, Display dual basic
    dimension in one box."""
    main = _num(value)
    inside = bool(_dp(doc, "Dimensions", "Include prefix inside basic tolerance box", False))
    text = "[%s%s]" % (prefix, main) if inside else "%s[%s]" % (prefix, main)
    try:
        from . import docstyle
        st = docstyle.part_style(doc)
        if st["dual"]:
            dual = docstyle.number(value / docstyle.dual_unit(doc)[1], st["dual_precision"], st["leading"], "Show")
            if bool(_dp(doc, "Dimensions", "Display dual basic dimension in one box", False)):
                text = text[:-1] + " %s]" % dual
            else:
                text = text + " [%s]" % dual
    except Exception as _fw_err:
        _fw_log("mbd.py:1064", _fw_err)
    return text


def angle_dimension(doc, a, b, tol=None):
    tol = default_angle_tol(doc) if tol is None else tol
    ang = angle(_el(*a), _el(*b))
    return make(doc, "Angle", [a, b], "%.1f° ±%.1f°" % (ang, tol), ang, tol, -tol)


def next_letter(doc):
    """The first free datum letter from Document Properties > Datums > Next label (A)."""
    used = {o.Text for o in doc.Objects if is_pmi(o) and o.Kind == "Datum"}
    letters = "ABCDEFGHJKLMNPRSTUVWXYZ"
    start = str(_dp(doc, "Datums", "Next label", "A") or "A").strip().upper()[:1]
    if start in letters:
        letters = letters[letters.index(start):] + letters[:letters.index(start)]
    for ch in letters:
        if ch not in used:
            return ch
    return "Z"


def datum(doc, obj, sub, letter=None):
    return make(doc, "Datum", [(obj, sub)], letter or next_letter(doc))


def datum_target(doc, obj, sub, letter=None):
    letter = letter or (next_letter(doc) if not any(is_pmi(o) and o.Kind == "Datum" for o in doc.Objects)
                        else sorted(o.Text for o in doc.Objects if is_pmi(o) and o.Kind == "Datum")[-1])
    n = 1 + sum(1 for o in doc.Objects if is_pmi(o) and o.Kind == "DatumTarget" and o.Text.startswith(letter))
    return make(doc, "DatumTarget", [(obj, sub)], "%s%d" % (letter, n))


def gtol(doc, obj, sub, symbol="Position", value=None, datums=("A", "B", "C"), diameter=None, material="None",
         datum_material=None, composite=None, slot_length=None, modifier="None"):
    """The Geometric Tolerance box: symbol, ⌀, tolerance and material condition, datums (each with its
    own material condition), and a composite second frame (its tolerance) when asked."""
    value = default_gtol(doc, symbol) if value is None else value
    f = _el(obj, sub)
    if diameter is None:
        diameter = symbol == "Position" and f.ShapeType == "Face" and f.Surface.TypeId == "Part::GeomCylinder"
    dm = list(datum_material or [])
    ds = [d + MATERIAL.get(dm[i] if i < len(dm) else "None", "") for i, d in enumerate([d for d in datums if d])]
    parts = [GTOL_SYMBOLS.get(symbol, symbol), ("⌀" if diameter else "") + "%g" % value + (MATERIAL.get(material, "") + MATERIAL.get(modifier or "None", ""))] + ds
    if slot_length and symbol == "Position":
        slot = next((sl for sl in slot_faces(obj.Shape) if f.ShapeType == "Face" and
                     any(f.isSame(obj.Shape.Faces[k]) for k in sl[:2])), None)
        if slot is not None:

            rows = ["|" + "|".join([parts[0], "%g" % value + (MATERIAL.get(material, "") + MATERIAL.get(modifier or "None", ""))] + ds) + "| WIDTH",
                    "|" + "|".join([parts[0], "%g" % slot_length + (MATERIAL.get(material, "") + MATERIAL.get(modifier or "None", ""))] + ds) + "| LENGTH"]
            return make(doc, "GTol", [(obj, sub)], "\n".join(rows), value, value, 0)
    if composite:
        first = "|" + "|".join(parts) + "|"
        second = "|" + "|".join([" " * len(GTOL_SYMBOLS.get(symbol, symbol)),
                                 ("⌀" if diameter else "") + "%g" % composite] + ds[:1]) + "|"
        return make(doc, "GTol", [(obj, sub)], first + "\n" + second, value, value, 0)
    return make(doc, "GTol", [(obj, sub)], "|" + "|".join(parts) + "|", value, value, 0)


SKETCH_KINDS = {"Distance": "Location", "DistanceX": "Location", "DistanceY": "Location",
                "Radius": "Size", "Diameter": "Size", "Angle": "Angle"}


def _sketch_edge(sketch, index):
    """The sketch's Shape edge for geometry index (None for construction or a point)."""
    try:
        g = sketch.Geometry[index]
        if sketch.getConstruction(index):
            return None
        mid = sketch.getGlobalPlacement().multVec(g.value((g.FirstParameter + g.LastParameter) / 2.0)
                                                  if hasattr(g, "FirstParameter") else g.Center)
    except Exception as _fw_err:
        _fw_log("mbd.py:1144", _fw_err)
        return None
    for i, e in enumerate(sketch.Shape.Edges, 1):
        if e.distToShape(Part.Vertex(mid))[0] < 1e-6:
            return "Edge%d" % i
    return None


def sketch_dimensions(doc, body=None, plus=None, minus=None):
    ""

    plus = default_tol(doc) if plus is None else plus
    minus = -plus if minus is None else minus
    bodies = [body] if body is not None else [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    made = []
    for b in bodies:
        for sk in [o for o in b.Group if o.TypeId == "Sketcher::SketchObject" and o.InList]:
            if not any(u.TypeId.startswith("PartDesign::") and u is not b for u in sk.InList):
                continue
            for c in sk.Constraints:
                kind = SKETCH_KINDS.get(c.Type)
                if kind is None or not getattr(c, "Driving", True):
                    continue
                sub = _sketch_edge(sk, c.First) if c.First >= 0 else None
                if sub is None:
                    continue
                refs = [(sk, sub)]
                if c.Type in ("Distance", "DistanceX", "DistanceY") and c.Second >= 0:
                    sub2 = _sketch_edge(sk, c.Second)
                    if sub2 is not None:
                        refs.append((sk, sub2))
                if kind == "Angle":
                    deg = math.degrees(c.Value)
                    a = default_angle_tol(doc)
                    made.append(make(doc, "Angle", refs, "%.1f° ±%.1f°" % (deg, a), deg, a, -a))
                    continue
                prefix = {"Radius": "R", "Diameter": "⌀"}.get(c.Type, "")
                made.append(make(doc, kind, refs, _tol_text(float(c.Value), plus, minus, prefix), float(c.Value),
                                 plus, minus))
    doc.recompute()
    return made


def set_hide_mode(doc, on):
    ""

    ghost = HIDE_GHOST.setdefault(doc.Name, set())
    if on:
        for o in doc.Objects:
            if is_pmi(o) and o.ViewObject is not None and not o.ViewObject.Visibility:
                ghost.add(o.Name)
                o.ViewObject.Visibility = True
                _recolour(o)
    else:
        for name in list(ghost):
            o = doc.getObject(name)
            ghost.discard(name)
            if o is not None and o.ViewObject is not None:
                _recolour(o)
                o.ViewObject.Visibility = False
        HIDE_GHOST.pop(doc.Name, None)
    return ghost


def hide_mode_on(doc):
    return doc is not None and doc.Name in HIDE_GHOST


def toggle_hidden(obj):
    """In Hide/Show Annotations: a shown annotation goes grey (to hide), a grey one is shown again."""
    ghost = HIDE_GHOST.setdefault(obj.Document.Name, set())
    if obj.Name in ghost:
        ghost.discard(obj.Name)
    else:
        ghost.add(obj.Name)
    _recolour(obj)
    return obj.Name in ghost


def _recolour(o):
    try:
        o.ViewObject.Proxy._colour(o)
    except Exception as _fw_err:
        _fw_log("mbd.py:1220", _fw_err)


def equal_holes(shape, face):
    if face.Surface.TypeId != "Part::GeomCylinder":
        return [face]
    r = face.Surface.Radius
    length = face.Length if hasattr(face, "Length") else 0
    out = []
    for g in shape.Faces:
        if g.Surface.TypeId == "Part::GeomCylinder" and abs(g.Surface.Radius - r) < 1e-6 and \
                abs(g.Area - face.Area) < 1e-3 * max(face.Area, 1.0) and _is_hole(shape, g):
            out.append(g)
    return out or [face]


def _is_hole(shape, f):
    s = f.Surface
    u0, u1, v0, v1 = f.ParameterRange
    p = f.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
    n = f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    axis_pt = s.Center + s.Axis * (p - s.Center).dot(s.Axis)
    return (axis_pt - p).dot(n) > 0


def pattern_feature(doc, obj, sub, plus=None, minus=None):
    plus = default_tol(doc) if plus is None else plus
    minus = -plus if minus is None else minus
    f = _el(obj, sub)
    holes = equal_holes(obj.Shape, f)
    value, prefix, _w = size_of(f)
    refs = []
    for g in holes:
        i = next(k for k, h in enumerate(obj.Shape.Faces) if h.isSame(g))
        refs.append((obj, "Face%d" % (i + 1)))
    text = "%dX %s" % (len(holes), _tol_text(value or 0.0, plus, minus, prefix))
    return make(doc, "Pattern", refs, text, value or 0.0, plus, minus)


AUTO_FILTERS = ("Holes", "Bosses", "Fillets", "Chamfers", "Slots")


def polar_location(doc, obj, faces, plus=None, minus=None, basic=False):
    """Pattern dimensioning Polar: a hole pattern located by its bolt circle diameter and the angle
    between holes (one annotation on all the holes)."""
    plus = default_tol(doc) if plus is None else plus
    minus = -plus if minus is None else minus
    shape = obj.Shape
    centres = [shape.Faces[i].Surface.Center for i in faces]
    axis = shape.Faces[faces[0]].Surface.Axis
    c = V()
    for p in centres:
        c = c + p
    c = c * (1.0 / len(centres))
    radial = [(p - c) - axis * (p - c).dot(axis) for p in centres]
    r = sum(v.Length for v in radial) / len(radial)
    step = 360.0 / len(centres)
    dia = 2 * r
    text = ("%s B.C. %dX %g°" % (basic_text(doc, dia, "⌀"), len(centres), round(step, 2)) if basic else
            "%s B.C. %dX %g°" % (_tol_text(dia, plus, minus, "⌀"), len(centres), round(step, 2)))
    return make(doc, "BasicLocation" if basic else "Location", [(obj, "Face%d" % (i + 1)) for i in faces],
                text, dia, 0 if basic else plus, 0 if basic else minus)


def _turned_scheme(doc, obj, plus, minus, geometric, filters, scope):
    """Part type Turned: datum A on the main axis (the largest outside cylinder), datum B on an end
    face; every outside diameter sized, every step face located along the axis from B, holes sized."""
    shape = obj.Shape
    cyl = [(f.Area, i, f) for i, f in enumerate(shape.Faces) if f.Surface.TypeId == "Part::GeomCylinder"
           and abs(f.ParameterRange[1] - f.ParameterRange[0]) >= 6.0]
    outside = sorted([c for c in cyl if not _is_hole(shape, c[2])], key=lambda c: -c[0])
    if not outside:
        return []
    made = []
    _a, ia, fa = outside[0]
    axis = fa.Surface.Axis
    made.append(datum(doc, obj, "Face%d" % (ia + 1)))
    ends = [(f.Area, i, f) for i, f in enumerate(shape.Faces) if f.Surface.TypeId == "Part::GeomPlane"
            and abs(abs(_normal(f).dot(axis)) - 1) < 1e-6]
    ends.sort(key=lambda e: e[2].CenterOfMass.dot(axis))
    ib = ends[0][1] if ends else None
    letters = [made[0].Text]
    if ib is not None:
        d = datum(doc, obj, "Face%d" % (ib + 1))
        letters.append(d.Text)
        made.append(d)
    for _a2, i, f in outside:
        if (scope is not None and i not in scope) or "Bosses" not in filters:
            continue
        made.append(size_dimension(doc, obj, "Face%d" % (i + 1), plus, minus))
        if geometric and i != ia:
            made.append(gtol(doc, obj, "Face%d" % (i + 1), "Concentricity", 2 * plus, tuple(letters[:1])))
    if ib is not None:
        for _a2, i, f in ends[1:]:
            if scope is not None and i not in scope:
                continue
            made.append(location_dimension(doc, (obj, "Face%d" % (ib + 1)), (obj, "Face%d" % (i + 1)), plus, minus,
                                           basic=bool(geometric)))
    if "Holes" in filters:
        for _a2, i, f in cyl:
            if _is_hole(shape, f) and (scope is None or i in scope):
                made.append(size_dimension(doc, obj, "Face%d" % (i + 1), plus, minus))
    return made


def auto_scheme(doc, obj, plus=None, minus=None, geometric=False, datums=None, filters=AUTO_FILTERS,
                part_type="Prismatic", pattern="Linear", scope=None):
    """Auto Dimension Scheme. Reference features: datums A/B/C on the picked faces (datums, "FaceN"),
    else on the three largest mutually perpendicular planes. Tolerance type: Plus and Minus (located
    from B and C with ± dimensions) or Geometric (basic locations and a Position frame to A|B|C).
    Feature filters: Holes, Bosses, Fillets. Part type Turned dimensions a lathe part from its axis;
    Pattern dimensioning Polar locates a hole pattern by its bolt circle; scope: the face indices of
    Selected features (None: all features)."""
    plus = default_tol(doc) if plus is None else plus
    minus = -plus if minus is None else minus
    filters = set(filters or ())
    if part_type == "Turned":
        return _turned_scheme(doc, obj, plus, minus, geometric, filters, scope)
    shape = obj.Shape
    planes = sorted([(f.Area, i, f) for i, f in enumerate(shape.Faces) if f.Surface.TypeId == "Part::GeomPlane"],
                    key=lambda x: -x[0])
    if datums:
        planes = [(0, int(d[4:]) - 1, shape.Faces[int(d[4:]) - 1]) for d in datums if d.startswith("Face")] + planes
    picked = []
    for _a, i, f in planes:
        n = _normal(f)
        if all(abs(n.dot(_normal(g))) < 1e-6 for _j, g in picked):
            picked.append((i, f))
        if len(picked) == 3:
            break
    made = []
    letters = []
    # Chain Dimension > Dimension style: Baseline (each feature from the datums) or Chain (each from
    # the one before it, the first from the datums)
    chain = str(_dp(doc, "Chain Dimension", "Dimension style", "Baseline")) == "Chain"
    located = []
    for i, _f in picked:
        d = datum(doc, obj, "Face%d" % (i + 1))
        letters.append(d.Text)
        made.append(d)
    done = set()
    slots = slot_faces(shape) if "Slots" in filters else []
    for sl in slots:
        if scope is not None and sl[0] not in scope and sl[1] not in scope:
            continue
        done.update((sl[0], sl[1]))
        made.append(slot_dimension(doc, obj, sl, plus, minus))
        for j, _f in picked[1:]:
            made.append(slot_location(doc, obj, sl, j, plus, minus, basic=bool(geometric)))
    for i, f in enumerate(shape.Faces):
        if i in done or f.Surface.TypeId != "Part::GeomCylinder":
            continue
        if scope is not None and i not in scope:
            continue
        full = abs(f.ParameterRange[1] - f.ParameterRange[0]) >= 6.0
        hole = _is_hole(shape, f)
        if not full:
            if "Fillets" in filters and not hole:
                done.add(i)
                made.append(fillet_dimension(doc, obj, "Face%d" % (i + 1), plus, minus))
            continue
        if (hole and "Holes" not in filters) or (not hole and "Bosses" not in filters):
            continue
        group = equal_holes(shape, f) if hole else [f]
        idx = [k for k, h in enumerate(shape.Faces) if any(h.isSame(g) for g in group)]
        done.update(idx)
        made.append(pattern_feature(doc, obj, "Face%d" % (i + 1), plus, minus) if len(idx) > 1 else
                    size_dimension(doc, obj, "Face%d" % (i + 1), plus, minus))
        if pattern == "Polar" and len(idx) > 2:
            made.append(polar_location(doc, obj, idx, plus, minus, basic=bool(geometric)))
            if geometric:
                made.append(gtol(doc, obj, "Face%d" % (i + 1), "Position", 2 * plus, tuple(letters)))
            continue
        if chain:
            located.append(i)
        else:
            for j, _f in picked[1:]:
                made.append(location_dimension(doc, (obj, "Face%d" % (j + 1)), (obj, "Face%d" % (i + 1)), plus,
                                               minus, basic=bool(geometric)))
        if geometric:
            made.append(gtol(doc, obj, "Face%d" % (i + 1), "Position", 2 * plus, tuple(letters)))
    if "Chamfers" in filters:
        for i, legs in chamfer_faces(shape, float(_dp(doc, "Chamfer Controls", "Width limit", 0.0) or 0.0)):
            if scope is not None and i not in scope:
                continue
            made.append(chamfer_dimension(doc, obj, "Face%d" % (i + 1), legs, plus, minus))
    if chain and located:
        for j, _f in picked[1:]:
            n = _normal(shape.Faces[j])
            base_at = shape.Faces[j].CenterOfMass
            order = sorted(located, key=lambda k: abs((_feature_point(shape.Faces[k]) - base_at).dot(n)))
            prev, prev_at = (obj, "Face%d" % (j + 1)), base_at
            for k in order:
                here, at = (obj, "Face%d" % (k + 1)), _feature_point(shape.Faces[k])
                gap = abs((at - prev_at).dot(n))
                if gap < 1e-6:
                    continue                # level with the one before: nothing to chain along n
                made.append(chain_location(doc, prev, here, gap, plus, minus, basic=bool(geometric)))
                prev, prev_at = here, at
    form = str(_dp(doc, "Geometric Tolerance", "Primary datums, form", "Flatness"))
    if picked and geometric and form != "None":
        # Geometric Tolerance > Primary datums: the form tolerance and its value
        try:
            value = float(_dp(doc, "Geometric Tolerance", "Primary datums, tolerance", plus / 2))
        except (TypeError, ValueError):
            value = plus / 2
        made.append(gtol(doc, obj, "Face%d" % (picked[0][0] + 1), form, value, ()))
    return made


def tolerance_status(doc, obj):
    ""


    sized, located = set(), set()
    size_count, pair_count = {}, {}
    patterns = []
    for o in doc.Objects:
        if not is_pmi(o):
            continue
        faces = []
        for ref, subs in o.References:
            if ref is not obj:
                continue
            for s in subs:
                i = int(s.split("Face")[-1]) - 1 if "Face" in s else None
                if i is None:
                    continue
                faces.append(i)
                if o.Kind in ("Size", "Pattern", "BasicSize"):
                    sized.add(i)
                    size_count[i] = size_count.get(i, 0) + 1
                if o.Kind in ("Location", "BasicLocation", "GTol", "Datum", "DatumTarget", "Angle"):
                    located.add(i)
        if o.Kind in ("Location", "BasicLocation", "Angle") and len(set(faces)) >= 2:
            key = tuple(sorted(set(faces)))
            pair_count[key] = pair_count.get(key, 0) + 1
        if o.Kind == "Pattern":
            patterns.append(set(faces))
    # a hole pattern is one DimXpert feature: located through any of its holes, it is located on all of them
    for group in patterns:
        if group & located:
            located.update(group)
    over = {i for i, n in size_count.items() if n > 1}
    for key, n in pair_count.items():
        if n > 1:
            over.update(key)
    out = {}
    for i in over:
        out[i] = "over"
    for i in (sized | located) - over:
        f = obj.Shape.Faces[i]
        needs_size = f.Surface.TypeId != "Part::GeomPlane"
        full = (i in located) and (i in sized or not needs_size)
        out[i] = "full" if full else "partial"
    return out


def _consumed(o):
    """True when another shape feature uses o (an analysis, a PMI or a folder does not count)."""
    for p in o.InList:
        if p.isDerivedFrom("Part::Feature") and getattr(p, "SWStyleKind", "") != "PMI" \
                and not p.TypeId.startswith("Fem::"):
            return True
    return False


_SAVED = {}


def _get_colours(vo):
    try:
        return [m.DiffuseColor for m in vo.ShapeAppearance]
    except Exception:
        return list(getattr(vo, "DiffuseColor", []))


def _set_colours(vo, colours):
    try:
        mats = []
        for c in colours:
            m = App.Material()
            m.DiffuseColor = tuple(c)
            mats.append(m)
        vo.ShapeAppearance = mats
    except Exception:
        vo.DiffuseColor = colours


def _painted(obj):
    """The object whose faces show the colours: a body shows its tip's."""
    if obj.TypeId == "PartDesign::Body" and getattr(obj, "Tip", None) is not None:
        return obj.Tip
    return obj


def show_tolerance_status(doc, obj, on=True):
    vo = _painted(obj).ViewObject
    if not on:
        if obj.Name in _SAVED:
            saved = _SAVED.pop(obj.Name)
            try:
                vo.ShapeAppearance = saved
            except Exception:
                _set_colours(vo, saved)
        return {}
    status = tolerance_status(doc, obj)
    if obj.Name not in _SAVED:
        try:
            _SAVED[obj.Name] = list(vo.ShapeAppearance)
        except Exception:
            _SAVED[obj.Name] = _get_colours(vo)
    base = (0.8, 0.8, 0.8, 0.0)
    colours = []
    for i in range(len(obj.Shape.Faces)):
        s = status.get(i)
        colours.append((0.2, 0.75, 0.2, 0.0) if s == "full" else (0.95, 0.85, 0.1, 0.0) if s == "partial"
                       else (0.9, 0.15, 0.1, 0.0) if s == "over" else base)
    _set_colours(vo, colours)
    return status


def stack_up(dims):
    """Worst case and RSS of a chain of dimensions [(nominal, plus, minus, sign)]."""
    nominal = sum(s * n for n, _p, _m, s in dims)
    worst_hi = sum(p if s > 0 else -m for _n, p, m, s in dims)
    worst_lo = sum(m if s > 0 else -p for _n, p, m, s in dims)
    rss = math.sqrt(sum(((p - m) / 2.0) ** 2 for _n, p, m, _s in dims))
    return {"nominal": nominal, "max": nominal + worst_hi, "min": nominal + worst_lo, "rss": rss}


# ===================================================================== GUI
if Gui is not None:
    def _picks():
        out = []
        for sel in Gui.Selection.getSelectionEx("", 0):
            for sub in sel.SubElementNames:
                path = sub.split(".")
                holder = sel.Object
                for part in path[:-1]:
                    child = sel.Object.Document.getObject(part)
                    if child is not None:
                        holder = child
                if holder.TypeId == "PartDesign::Body" or (holder.TypeId.startswith("PartDesign::") and
                                                         holder.getParentGeoFeatureGroup() is not None):
                    holder = holder.getParentGeoFeatureGroup() or holder
                out.append((holder, path[-1]))
        return out

    class _TextPart:
        ""


        def __init__(self, box, side):
            self.box, self.side = box, side

        def _parts(self):
            t = self.box.text()
            if "<DIM>" not in t:
                return t, ""
            a, b = t.split("<DIM>", 1)
            return a, b

        def text(self):
            return self._parts()[self.side]

        def setText(self, value):
            a, b = self._parts()
            a, b = (value, b) if self.side == 0 else (a, value)
            self.box.setText(a + "<DIM>" + b)

    class PickPM:
        """A PropertyManager that collects `need` picks, then makes the annotation."""

        def __init__(self, title, need, run, extra=None, hint=""):
            self.title, self.need, self.run = title, need, run
            self.form = QtWidgets.QWidget()
            self.form.setWindowTitle(title)
            self.form.setProperty("swstyle_pm_title", title)
            lay = QtWidgets.QFormLayout(self.form)
            lay.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
            self.list = QtWidgets.QListWidget()
            self.list.setMaximumHeight(70)
            pmboxes.mark(self.list, True)
            hint_label = QtWidgets.QLabel(hint or "Pick %d item(s) on the model" % need)
            hint_label.setWordWrap(True)
            lay.addRow(hint_label)
            lay.addRow(self.list)
            self.plus = QtWidgets.QDoubleSpinBox()
            self.plus.setDecimals(3)
            self.plus.setRange(0, 100)
            self.plus.setValue(default_tol())
            self.minus = QtWidgets.QDoubleSpinBox()
            self.minus.setDecimals(3)
            self.minus.setRange(-100, 0)
            self.minus.setValue(-default_tol())
            self.ttype = None
            self.lay = lay
            if title in ("Size Dimension", "Location Dimension", "Angle Dimension"):
                # Tolerance/Precision and Dimension Text, as the DimXpert PropertyManager has them
                self.ttype = QtWidgets.QComboBox()
                self.ttype.setObjectName("SWMBDToleranceType")
                self.ttype.addItems(list(TOLERANCE_TYPES) + ([] if title == "Angle Dimension" else list(FIT_TYPES)))
                self.ttype.setCurrentText("Symmetric")
                lay.addRow("Tolerance type", self.ttype)
            if title in TOLERANCED:

                # has no tolerance rows (they did nothing there)
                lay.addRow("Maximum variation", self.plus)
                lay.addRow("Minimum variation", self.minus)
            if self.ttype is not None:
                from . import drawdimpm as _DP
                self.hole_fit = QtWidgets.QComboBox()
                self.hole_fit.setObjectName("SWMBDHoleFit")
                self.hole_fit.addItems(list(_DP.HOLE_FITS))
                self.hole_fit.setCurrentText("H7")
                self.shaft_fit = QtWidgets.QComboBox()
                self.shaft_fit.setObjectName("SWMBDShaftFit")
                self.shaft_fit.addItems(list(_DP.SHAFT_FITS))
                lay.addRow("Hole fit", self.hole_fit)
                lay.addRow("Shaft fit", self.shaft_fit)
                self.precision = QtWidgets.QComboBox()
                self.precision.setObjectName("SWMBDPrecision")
                self.precision.addItems(["Document", "0", ".1", ".12", ".123", ".1234"])
                lay.addRow("Unit precision", self.precision)

                self.dimtext = QtWidgets.QLineEdit("<DIM>")
                self.dimtext.setObjectName("SWMBDDimText")
                lay.addRow("Dimension text", self.dimtext)
                self.prefix, self.suffix = _TextPart(self.dimtext, 0), _TextPart(self.dimtext, 1)
                self.ttype.currentTextChanged.connect(self._tol_shown)
                self._tol_shown(self.ttype.currentText())
            self.extra = extra(lay) if extra else None
            self.msg = QtWidgets.QLabel("")
            self.msg.setWordWrap(True)
            lay.addRow(self.msg)
            self.items = []
            for p in _picks():
                self._add(*p)
            Gui.Selection.addObserver(self)
            if len(self.items) >= self.need:
                QtCore.QTimer.singleShot(0, self._done_auto)

        def _row(self, w, on):
            ""
            w.setVisible(on)
            label = self.lay.labelForField(w)
            if label is not None:
                label.setVisible(on)

        def _tol_shown(self, t):
            self._row(self.plus, t in ("Bilateral", "Symmetric", "Limit"))
            self._row(self.minus, t in ("Bilateral", "Limit"))
            for w in (getattr(self, "hole_fit", None), getattr(self, "shaft_fit", None)):
                if w is not None:
                    self._row(w, t in FIT_TYPES)

        def restyle_made(self, obj):
            """The made dimension in the picked tolerance type, precision and text."""
            if self.ttype is None or obj is None or not is_pmi(obj):
                return obj
            t = self.ttype.currentText()
            plus = self.plus.value()
            minus = -plus if t == "Symmetric" else self.minus.value()
            prec = self.precision.currentText()
            prec = None if prec == "Document" else (0 if prec == "0" else len(prec) - 1)
            if t in FIT_TYPES:
                return self._fit_made(obj, t, prec)
            text = str(obj.Text)
            lead = ""
            for ch in text:
                if ch.isdigit() or ch in "-.[":
                    break
                lead += ch
            obj.Text = tolerance_text(obj.Document, obj.Value, t, plus, minus, prec,
                                      self.prefix.text() + lead, self.suffix.text(), obj.Kind == "Angle")
            obj.Plus, obj.Minus = (0.0, 0.0) if t in ("Basic", "None", "MIN", "MAX") else (plus, minus)
            if t == "Basic":
                obj.Kind = "BasicSize" if obj.Kind == "Size" else ("BasicLocation" if obj.Kind == "Location" else obj.Kind)
            obj.AutoText = obj.Text
            return obj

        def _fit_made(self, obj, t, prec):
            """Fit, Fit with tolerance and Fit (tolerance only): the ISO 286 class and / or its deviations."""
            from . import drawdimpm as _DP
            hole, shaft = self.hole_fit.currentText(), self.shaft_fit.currentText()
            fit = _DP.fit_text(hole, shaft)
            devs = _DP.fit_deviations(obj.Value, hole) if hole else (_DP.fit_deviations(obj.Value, shaft) if shaft else None)
            plus, minus = devs if devs else (0.0, 0.0)
            text = str(obj.Text)
            lead = ""
            for ch in text:
                if ch.isdigit() or ch in "-.[":
                    break
                lead += ch
            if t == "Fit (tolerance only)" and devs:
                body = tolerance_text(obj.Document, obj.Value, "Bilateral", plus, minus, prec, "", "")
            elif t == "Fit with tolerance" and devs:
                tol = tolerance_text(obj.Document, 0.0, "Bilateral", plus, minus, prec, "", "").split(" ", 1)[-1]
                body = tolerance_text(obj.Document, obj.Value, "None", 0, 0, prec) + (" %s (%s)" % (fit, tol) if fit else " " + tol)
            else:
                body = tolerance_text(obj.Document, obj.Value, "None", 0, 0, prec) + (" " + fit if fit else "")
            obj.Text = self.prefix.text() + lead + body + self.suffix.text()
            obj.Plus, obj.Minus = (plus, minus) if t != "Fit" else (0.0, 0.0)
            obj.AutoText = obj.Text
            return obj

        def _add(self, obj, sub):
            if len(self.items) >= self.need:
                self.items.pop(0)
                self.list.takeItem(0)
            self.items.append((obj, sub))
            self.list.addItem("%s %s" % (obj.Label, sub))

        def addSelection(self, doc, name, sub, _pos):
            if not sub:
                return
            obj = App.getDocument(doc).getObject(name)
            path = sub.split(".")
            for part in path[:-1]:
                child = obj.Document.getObject(part)
                if child is not None:
                    obj = child
            if obj.TypeId.startswith("PartDesign::") and obj.TypeId != "PartDesign::Body":
                obj = obj.getParentGeoFeatureGroup() or obj
            self._add(obj, path[-1])
            if len(self.items) >= self.need:
                QtCore.QTimer.singleShot(0, self._done_auto)

        def _done_auto(self):

            try:
                App.ActiveDocument.openTransaction(self.title)
                try:
                    made = self.run(self, list(self.items))
                    if isinstance(made, tuple):
                        made = made[-1]
                    self.restyle_made(made)
                except BaseException:
                    try:
                        App.ActiveDocument.abortTransaction()
                    except Exception:
                        pass
                    raise
                App.ActiveDocument.commitTransaction()
                self.msg.setStyleSheet("")
                self.msg.setText("%s placed. Pick again for another, or OK." % self.title)
                if self.title == "Datum" and isinstance(self.extra, QtWidgets.QLineEdit):
                    self.extra.setText(next_letter(App.ActiveDocument))
            except Exception as error:
                App.ActiveDocument.abortTransaction()
                self.msg.setStyleSheet("color: #c00000;")
                self.msg.setText(str(error))
            self.items = []
            self.list.clear()
            Gui.Selection.clearSelection()

        def _stop(self):
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("mbd.py:1693", _fw_err)

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def accept(self):
            self._stop()
            Gui.Control.closeDialog()
            return True

        def reject(self):
            self._stop()
            Gui.Control.closeDialog()
            return True

    def _gtol_extra(lay):
        sym = QtWidgets.QComboBox()
        sym.addItems(list(GTOL_SYMBOLS))
        val = QtWidgets.QDoubleSpinBox()
        val.setDecimals(3)
        val.setValue(default_gtol(None, sym.currentText()))
        sym.currentTextChanged.connect(lambda t: val.setValue(default_gtol(None, t)))
        dat = QtWidgets.QLineEdit("A B C")          # kept (hidden): the three datum rows below write it
        dat.setObjectName("SWMBDDatums")
        dia = QtWidgets.QCheckBox("Diameter (⌀)")
        dia.setTristate(False)
        dia.setObjectName("SWMBDDiameter")
        mat = QtWidgets.QComboBox()
        mat.setObjectName("SWMBDMaterial")
        mat.addItems(list(MATERIAL_CONDITIONS))
        mod = QtWidgets.QComboBox()
        mod.setObjectName("SWMBDModifier")
        mod.addItems(list(MODIFIERS))
        dmat = QtWidgets.QComboBox()                # kept (hidden): sets all three datums' conditions
        dmat.setObjectName("SWMBDDatumMaterial")
        dmat.addItems(list(MATERIAL_CONDITIONS))
        rows = []
        for i, (name, letter) in enumerate((("Primary", "A"), ("Secondary", "B"), ("Tertiary", "C"))):
            d = QtWidgets.QLineEdit(letter)
            d.setObjectName("SWMBDDatum" + name)
            d.setMaxLength(4)
            m = QtWidgets.QComboBox()
            m.setObjectName("SWMBDDatumMaterial" + name)
            m.addItems(list(MATERIAL_CONDITIONS))
            rows.append((name, d, m))
        sync = {"on": False}

        def to_line(*_):
            if sync["on"]:
                return
            sync["on"] = True
            dat.setText(" ".join(d.text().strip() for _n, d, _m in rows if d.text().strip()))
            sync["on"] = False

        def from_line(text):
            if sync["on"]:
                return
            sync["on"] = True
            parts = text.split()
            for i, (_n, d, _m) in enumerate(rows):
                d.setText(parts[i] if i < len(parts) else "")
            sync["on"] = False

        def all_conditions(text):
            for _n, _d, m in rows:
                m.setCurrentText(text)
        for _n, d, _m in rows:
            d.textChanged.connect(to_line)
        dat.textChanged.connect(from_line)
        dmat.currentTextChanged.connect(all_conditions)
        comp = QtWidgets.QDoubleSpinBox()
        comp.setObjectName("SWMBDComposite")
        comp.setDecimals(3)
        comp.setSpecialValueText("None")
        slot = QtWidgets.QDoubleSpinBox()
        slot.setObjectName("SWMBDSlotLength")
        slot.setDecimals(3)
        slot.setSpecialValueText("Same as width")
        slot.setToolTip("A slot's position tolerance along its length (Tolerance is across its width)")
        lay.addRow("Symbol", sym)
        lay.addRow(dia)
        lay.addRow("Tolerance", val)
        lay.addRow("Material condition", mat)
        lay.addRow("Modifier", mod)
        for name, d, m in rows:
            row = QtWidgets.QHBoxLayout()
            row.addWidget(d, 1)
            row.addWidget(m, 1)
            lay.addRow(name, row)
        dat.hide()
        dmat.hide()
        lay.addRow("Composite frame tolerance", comp)
        lay.addRow("Slot length tolerance", slot)
        return sym, val, dat, dia, mat, dmat, comp, slot, mod, tuple(m for _n, _d, m in rows)

    def _letter_extra(lay):
        e = QtWidgets.QLineEdit("")
        e.setPlaceholderText("next free letter")
        lay.addRow("Label", e)
        return e

    def _datum_extra(lay):
        ""
        e = _letter_extra(lay)
        e.setObjectName("SWMBDDatumLabel")
        try:
            e.setText(next_letter(App.ActiveDocument))
        except Exception as _fw_err:
            _fw_log("mbd.py:_datum_extra", _fw_err)
        return e

    def _basic_extra(lay):
        b = QtWidgets.QCheckBox("Basic")
        b.setToolTip("Basic dimension: boxed, with no tolerance")
        lay.addRow(b)
        return b

    SPECS = {
        "SWStyle_MBDSize": ("Size Dimension", 1, lambda pm, p: size_dimension(
            App.ActiveDocument, p[0][0], p[0][1], pm.plus.value(), pm.minus.value()), None,
            "Pick a hole, boss or face"),
        "SWStyle_MBDLocation": ("Location Dimension", 2, lambda pm, p: location_dimension(
            App.ActiveDocument, p[0], p[1], pm.plus.value(), pm.minus.value(), basic=False), None, "Pick the two items"),
        "SWStyle_MBDAngle": ("Angle Dimension", 2, lambda pm, p: angle_dimension(
            App.ActiveDocument, p[0], p[1], pm.plus.value()), None, "Pick two faces or edges"),
        "SWStyle_MBDBasicLocation": ("Basic Location Dimension", 2, lambda pm, p: location_dimension(
            App.ActiveDocument, p[0], p[1], basic=True), None, "Pick the two items"),
        "SWStyle_MBDBasicSize": ("Basic Size Dimension", 1, lambda pm, p: (lambda o: (
            setattr(o, "Text", basic_text(o.Document, o.Value)), setattr(o, "AutoText", o.Text),
            setattr(o, "Kind", "BasicSize"), o))(size_dimension(
                App.ActiveDocument, p[0][0], p[0][1], 0, 0)), None, "Pick a hole, boss or face"),
        "SWStyle_MBDPattern": ("Pattern Feature", 1, lambda pm, p: pattern_feature(
            App.ActiveDocument, p[0][0], p[0][1], pm.plus.value(), pm.minus.value()), None, "Pick one hole of the pattern"),
        "SWStyle_MBDDatum": ("Datum", 1, lambda pm, p: datum(App.ActiveDocument, p[0][0], p[0][1],
                                                            pm.extra.text().strip() or None), _datum_extra,
                             "Pick the datum face"),
        "SWStyle_MBDDatumTarget": ("Datum Target", 1, lambda pm, p: datum_target(
            App.ActiveDocument, p[0][0], p[0][1], pm.extra.text().strip() or None), _letter_extra,
            "Pick where the target is"),
        "SWStyle_MBDGeometricTolerance": ("Geometric Tolerance", 1, lambda pm, p: gtol(
            App.ActiveDocument, p[0][0], p[0][1], pm.extra[0].currentText(), pm.extra[1].value(),
            tuple(pm.extra[2].text().split()), True if pm.extra[3].isChecked() else None, pm.extra[4].currentText(),
            [m.currentText() for m in pm.extra[9]][:len(pm.extra[2].text().split())], pm.extra[6].value() or None,
            pm.extra[7].value() or None, pm.extra[8].currentText()),
            _gtol_extra, "Pick the toleranced face"),
    }

    def _solid_obj():
        doc = App.ActiveDocument
        for sel in Gui.Selection.getSelection():
            if isinstance(getattr(sel, "Shape", None), Part.Shape) and sel.Shape.Solids:
                holder = sel.getParentGeoFeatureGroup() if sel.TypeId.startswith("PartDesign::") else None
                return holder or sel
        for o in doc.Objects:
            if o.TypeId == "PartDesign::Body" and o.Shape.Solids:
                return o
        for o in doc.Objects:
            if isinstance(getattr(o, "Shape", None), Part.Shape) and o.Shape.Solids and not _consumed(o):
                return o
        return None

    def _paintable(obj):
        """rcmenus pkg270: Show Tolerance Status colours faces; an assembly or a component has none of its
        own (ViewProviderAssembly has no DiffuseColor), so the picked component's part, else the first one's."""
        if obj is None or not (obj.TypeId == "Assembly::AssemblyObject" or obj.isDerivedFrom("App::Link")):
            return obj
        picks = [s for s in Gui.Selection.getSelection() if s.isDerivedFrom("App::Link")]
        doc = obj.Document
        for o in picks + [o for o in doc.Objects if o.isDerivedFrom("App::Link")]:
            t = o.getLinkedObject(True)
            if t is not None and t is not o and isinstance(getattr(t, "Shape", None), Part.Shape) and t.Shape.Solids \
                    and getattr(t, "ViewObject", None) is not None:
                return t
        return obj

    class _Pick:
        def __init__(self, name):
            self.name = name

        def GetResources(self):
            t = SPECS[self.name][0]
            return {"MenuText": t, "ToolTip": TIPS.get(self.name, t)}

        def IsActive(self):
            return App.ActiveDocument is not None and not Gui.Control.activeDialog() and _solid_obj() is not None

        def Activated(self, checked=None):
            title, need, run, extra, hint = SPECS[self.name]
            Gui.Control.showDialog(PickPM(title, need, run, extra, hint))

    class _Auto:
        def GetResources(self):
            return {"MenuText": "Auto Dimension Scheme",
                    "ToolTip": "Datums on the main faces; every hole sized, located and toleranced from them."}

        def IsActive(self):
            return App.ActiveDocument is not None and _solid_obj() is not None

        def Activated(self, checked=None):
            Gui.Control.showDialog(AutoPM(_solid_obj()))

    class AutoPM:
        """Auto Dimension Scheme PropertyManager: Settings (part type, tolerance type, pattern
        dimensioning), Reference Features (primary/secondary/tertiary datum faces), Scope and
        Feature Filters."""

        def __init__(self, obj):
            self.obj = obj
            self.form = QtWidgets.QWidget()
            self.form.setObjectName("SWMBDAutoPM")
            self.form.setWindowTitle("Auto Dimension Scheme")
            self.form.setProperty("swstyle_pm_title", "Auto Dimension Scheme")
            lay = QtWidgets.QVBoxLayout(self.form)
            g = QtWidgets.QGroupBox("Settings")
            gl = QtWidgets.QFormLayout(g)
            gl.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
            self.part = QtWidgets.QComboBox()
            self.part.addItems(["Prismatic", "Turned"])
            self.tol = QtWidgets.QComboBox()
            self.tol.setObjectName("SWMBDAutoTolerance")
            self.tol.addItems(["Plus and Minus", "Geometric"])
            self.pattern = QtWidgets.QComboBox()
            self.pattern.addItems(["Linear", "Polar"])
            self.pattern.setCurrentText(_dp(obj.Document, "Chain Dimension", "Pattern dimensioning", "Linear"))
            gl.addRow("Part type", self.part)
            gl.addRow("Tolerance type", self.tol)
            gl.addRow("Pattern dimensioning", self.pattern)
            lay.addWidget(g)
            g = QtWidgets.QGroupBox("Reference Features")
            gl = QtWidgets.QVBoxLayout(g)
            self.refs = QtWidgets.QListWidget()
            self.refs.setObjectName("SWMBDAutoRefs")
            self.refs.setMaximumHeight(70)
            pmboxes.mark(self.refs, True)
            self.refs.hide()
            gl.addWidget(self.refs)
            self.datum_boxes = []
            for name in ("Primary Datum", "Secondary Datum", "Tertiary Datum"):
                gl.addWidget(QtWidgets.QLabel(name))
                box = QtWidgets.QListWidget()
                box.setObjectName("SWMBDAuto" + name.replace(" ", ""))
                box.setMaximumHeight(24)
                pmboxes.mark(box, len(self.datum_boxes) == 0)
                self.datum_boxes.append(box)
                gl.addWidget(box)
            lay.addWidget(g)
            g = QtWidgets.QGroupBox("Scope")
            gl = QtWidgets.QVBoxLayout(g)
            self.all = QtWidgets.QRadioButton("All features")
            self.sel = QtWidgets.QRadioButton("Selected features")
            self.all.setChecked(True)
            gl.addWidget(self.all)
            gl.addWidget(self.sel)
            self.scope = []
            self.scope_list = QtWidgets.QListWidget()
            self.scope_list.setObjectName("SWMBDAutoScope")
            self.scope_list.setMaximumHeight(60)
            pmboxes.mark(self.scope_list, True)
            self.scope_list.setVisible(False)
            self.sel.toggled.connect(self.scope_list.setVisible)
            gl.addWidget(self.scope_list)
            lay.addWidget(g)
            g = QtWidgets.QGroupBox("Feature Filters")
            gl = QtWidgets.QVBoxLayout(g)
            self.filters = {}
            for name in AUTO_FILTERS:
                cb = QtWidgets.QCheckBox(name)
                cb.setChecked(True)
                cb.setObjectName("SWMBDAutoFilter" + name)
                self.filters[name] = cb
                gl.addWidget(cb)
            lay.addWidget(g)
            self.datums = []
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)

        def addSelection(self, doc, name, sub, _pos):
            face = sub.split(".")[-1] if sub else ""
            if face.startswith("Face") and self.sel.isChecked():
                if face not in self.scope:      # Scope: Selected features take the picks
                    self.scope.append(face)
                    self.scope_list.addItem(face)
                return
            if sub and sub.split(".")[-1].startswith("Face") and len(self.datums) < 3:
                self.datums.append(sub.split(".")[-1])
                self.refs.addItem(["Primary", "Secondary", "Tertiary"][len(self.datums) - 1] + ": " + self.datums[-1])
                k = len(self.datums) - 1
                self.datum_boxes[k].clear()
                self.datum_boxes[k].addItem(self.datums[-1])
                for i, box in enumerate(self.datum_boxes):     # the next box takes the next pick
                    pmboxes.mark(box, i == len(self.datums))

        def _stop(self):
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("mbd.py:1908", _fw_err)

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def _scope(self):
            """Selected features: the picked faces and the faces of the same hole pattern."""
            if not self.sel.isChecked():
                return None
            shape = self.obj.Shape
            out = set()
            for face in self.scope:
                k = int(face[4:]) - 1
                out.add(k)
                for g in equal_holes(shape, shape.Faces[k]):
                    out.update(j for j, h in enumerate(shape.Faces) if h.isSame(g))
            return out
        def run(self):
            doc = self.obj.Document
            doc.openTransaction("Auto Dimension Scheme")
            try:
                made = auto_scheme(doc, self.obj, geometric=self.tol.currentText() == "Geometric",
                                   datums=self.datums or None,
                                   filters=[n for n, cb in self.filters.items() if cb.isChecked()],
                                   part_type=self.part.currentText(), pattern=self.pattern.currentText(),
                                   scope=self._scope())
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
            App.Console.PrintMessage("Auto Dimension Scheme: %d annotations\n" % len(made))
            return made

        def accept(self):
            self._stop()
            self.run()
            Gui.Control.closeDialog()
            return True

        def reject(self):
            self._stop()
            Gui.Control.closeDialog()
            return True

    class _Status:
        def GetResources(self):
            return {"MenuText": "Show Tolerance Status", "Checkable": False,
                    "ToolTip": "Green: sized and located. Yellow: partly. Click again to turn it off."}

        def IsActive(self):
            return App.ActiveDocument is not None and _solid_obj() is not None

        def Activated(self, checked=None):      # toolbars pass the button's checked state
            obj = _paintable(_solid_obj())
            try:
                show_tolerance_status(obj.Document, obj, obj.Name not in _SAVED)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: Show Tolerance Status: %s\n" % error)

    class StackDialog(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(Gui.getMainWindow())
            self.setWindowTitle("Tolerance Stack-Up Study")
            self.resize(520, 360)
            lay = QtWidgets.QVBoxLayout(self)
            chain_label = QtWidgets.QLabel("Tick the dimensions of the chain; minus subtracts it.")
            chain_label.setWordWrap(True)
            lay.addWidget(chain_label)
            # extapps137: the numbers are in the document's length unit (an inch part read 6.350 for a quarter inch)
            try:
                from . import docstyle
                self.unit, self.per = docstyle._length(App.ActiveDocument)
            except Exception:
                self.unit, self.per = "mm", 1.0
            self.places = 4 if self.per != 1.0 else 3
            self.table = QtWidgets.QTableWidget(0, 4)
            self.table.setHorizontalHeaderLabels(["Dimension", "Nominal (%s)" % self.unit, "Tolerance (%s)" % self.unit, "Minus"])
            self.table.horizontalHeader().setStretchLastSection(True)
            self.dims = [o for o in App.ActiveDocument.Objects if is_pmi(o) and o.Kind in
                         ("Location", "Size", "BasicLocation", "Pattern")]
            for o in self.dims:
                r = self.table.rowCount()
                self.table.insertRow(r)
                item = QtWidgets.QTableWidgetItem(o.Label)
                item.setCheckState(QtCore.Qt.Unchecked)
                self.table.setItem(r, 0, item)
                f = "%%.%df" % self.places
                self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(f % (o.Value / self.per)))
                self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(("+%s/%s" % (f, f)) % (o.Plus / self.per, o.Minus / self.per)))
                sign = QtWidgets.QTableWidgetItem("")
                sign.setCheckState(QtCore.Qt.Unchecked)
                self.table.setItem(r, 3, sign)
            lay.addWidget(self.table)
            self.result = QtWidgets.QLabel("")
            lay.addWidget(self.result)
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
            calc = bb.addButton("Calculate", QtWidgets.QDialogButtonBox.ActionRole)
            calc.clicked.connect(self.calc)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)

        def calc(self):
            chain = []
            for r, o in enumerate(self.dims):
                if self.table.item(r, 0).checkState() == QtCore.Qt.Checked:
                    s = -1 if self.table.item(r, 3).checkState() == QtCore.Qt.Checked else 1
                    chain.append((o.Value, o.Plus, o.Minus, s))
            if not chain:
                self.result.setText("Tick at least one dimension.")
                return
            r = stack_up(chain)
            f = "%%.%df" % self.places
            self.result.setText(("Nominal %s   Worst case %s to %s   RSS ±%s %s" % (f, f, f, f, self.unit)) %
                                (r["nominal"] / self.per, r["min"] / self.per, r["max"] / self.per, r["rss"] / self.per))

    class _Stack:
        def GetResources(self):
            return {"MenuText": "Tolerance Stack-Up Study", "ToolTip": "Worst case and RSS of a chain of dimensions."}

        def IsActive(self):
            return App.ActiveDocument is not None and any(is_pmi(o) for o in App.ActiveDocument.Objects)

        def Activated(self, checked=None):
            StackDialog().exec_()


# key, label, command, caption, icon family (original drawings, interface land229)
KEYS = (("MBD_Auto", "Auto Dimension Scheme", "SWStyle_MBDAutoScheme", "Auto Dimension\nScheme", "MBD_AUTO_SCHEME"),
        ("MBD_Location", "Location Dimension", "SWStyle_MBDLocation", "Location\nDimension", "MBD_LOCATION_DIMENSION"),
        ("MBD_Size", "Size Dimension", "SWStyle_MBDSize", "Size\nDimension", "MBD_SIZE_DIMENSION"),
        ("MBD_Angle", "Angle Dimension", "SWStyle_MBDAngle", "Angle\nDimension", "MBD_ANGLE_DIMENSION"),
        ("MBD_BasicLocation", "Basic Location Dimension", "SWStyle_MBDBasicLocation", "Basic Location\nDimension", "MBD_BASIC_LOCATION"),
        ("MBD_BasicSize", "Basic Size Dimension", "SWStyle_MBDBasicSize", None, "MBD_BASIC_SIZE"),
        ("MBD_Pattern", "Pattern Feature", "SWStyle_MBDPattern", "Pattern\nFeature", "MBD_PATTERN_FEATURE"),
        ("MBD_Datum", "Datum", "SWStyle_MBDDatum", None, "MBD_DATUM"),
        ("MBD_DatumTarget", "Datum Target", "SWStyle_MBDDatumTarget", "Datum\nTarget", "MBD_DATUM_TARGET"),
        ("MBD_GTol", "Geometric Tolerance", "SWStyle_MBDGeometricTolerance", "Geometric\nTolerance", "MBD_GEOMETRIC_TOLERANCE"),
        ("MBD_GenProfile", "General Profile Tolerance", "SWStyle_MBDGeneralProfileTolerance", "General Profile\nTolerance",
         "MBD_GEOMETRIC_TOLERANCE"),
        ("MBD_ImportScheme", "Import Scheme", "SWStyle_MBDImportScheme", "Import\nScheme", "MBD_AUTO_SCHEME"),
        ("MBD_DeleteAll", "Delete All Tolerances", "SWStyle_MBDDeleteAllTolerances", "Delete All\nTolerances",
         "MBD_TOLERANCE_STATUS"),
        ("MBD_Status", "Show Tolerance Status", "SWStyle_MBDToleranceStatus", "Show Tolerance\nStatus", "MBD_TOLERANCE_STATUS"),
        ("MBD_Stack", "Tolerance Stack-Up Study", "SWStyle_MBDStackUp", "Stack-Up\nStudy", "MBD_STACK_UP"))


# Geometric Tolerance; Auto Pair Tolerance and Delete All Tolerances under Show Tolerance Status. Copy Scheme and

TAB = ("MBD Dimensions", (
    ("large", "MBD_Auto", None), ("large", "MBD_Location", None), ("large", "MBD_Size", None),
    ("large", "MBD_Angle", None), ("large", "MBD_BasicLocation", ("MBD_BasicLocation", "MBD_BasicSize")),
    ("large", "MBD_Pattern", None), ("large", "MBD_Datum", None), ("large", "MBD_DatumTarget", None),
    ("large", "MBD_GTol", ("MBD_GTol", "MBD_GenProfile")),
    ("sep",),
    ("large", "MBD_Status", ("MBD_Status", "MBD_AutoPair", "MBD_DeleteAll")),
    ("sep",),
    ("large", "MBD_Stack", None),
))


if Gui is not None:
    class _SketchDims:
        def GetResources(self):
            return {"MenuText": "DimXpert from Sketch Dimensions",
                    "ToolTip": "Makes 3D annotations from the driving dimensions of the part's sketches",
                    "Pixmap": "Sketcher_Dimension"}

        def IsActive(self):
            doc = App.ActiveDocument
            return doc is not None and any(o.TypeId == "Sketcher::SketchObject" for o in doc.Objects)

        def Activated(self):
            doc = App.ActiveDocument
            doc.openTransaction("DimXpert from Sketch Dimensions")
            try:
                made = sketch_dimensions(doc)
            finally:
                doc.commitTransaction()
            Gui.getMainWindow().statusBar().showMessage("%d annotations from sketch dimensions" % len(made), 4000)

    class _HideObserver:
        def __init__(self, doc):
            self.doc = doc

        def addSelection(self, doc, name, sub, pos):
            if doc != self.doc.Name or not hide_mode_on(self.doc):
                return
            o = self.doc.getObject(name)
            if o is not None and is_pmi(o):
                toggle_hidden(o)
                QtCore.QTimer.singleShot(0, Gui.Selection.clearSelection)

    _HIDE = {}

    class _HideShow:
        def GetResources(self):
            return {"MenuText": "Hide/Show Annotations",
                    "ToolTip": "Click annotations to hide them (grey) or show them again; click the tool again to finish",
                    "Pixmap": "Std_ToggleVisibility", "Checkable": False}

        def IsActive(self):
            doc = App.ActiveDocument
            return doc is not None and any(is_pmi(o) for o in doc.Objects)

        def Activated(self):
            doc = App.ActiveDocument
            if hide_mode_on(doc):
                stop_hide(doc)
            else:
                start_hide(doc)

    def start_hide(doc):
        doc.openTransaction("Hide/Show Annotations")
        try:
            set_hide_mode(doc, True)
            ob = _HideObserver(doc)
            Gui.Selection.addObserver(ob)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        _HIDE[doc.Name] = ob
        Gui.getMainWindow().statusBar().showMessage(
            "Hide/Show Annotations: click annotations to hide (grey) or show them; the tool again ends it", 0)

    def stop_hide(doc):
        ob = _HIDE.pop(doc.Name, None)
        if ob is not None:
            Gui.Selection.removeObserver(ob)
        set_hide_mode(doc, False)
        doc.commitTransaction()
        Gui.getMainWindow().statusBar().clearMessage()


def register():
    if Gui is None:
        return
    have = set(Gui.listCommands())
    for name in SPECS:
        if name not in have:
            Gui.addCommand(name, _Pick(name))
    for name, cmd in (("SWStyle_MBDAutoScheme", _Auto()), ("SWStyle_MBDToleranceStatus", _Status()),
                      ("SWStyle_MBDStackUp", _Stack()), ("SWStyle_MBDSketchDimensions", _SketchDims()),
                      ("SWStyle_MBDHideShow", _HideShow())):
        if name not in have:
            Gui.addCommand(name, cmd)
    try:
        from . import mbdtab
        mbdtab.register()           # the MBD tab's tools
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: MBD tab: %s\n" % error)
    try:
        # General Profile Tolerance, Import Scheme and Delete All Tolerances (drawings' drawmbd): the
        # MBD Dimensions tab shows them, and nothing else registered them (CommandManager scan)
        from . import drawmbd
        if hasattr(drawmbd, "register"):
            drawmbd.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: MBD scheme tools: %s\n" % error)
