# SPDX-License-Identifier: LGPL-2.1-or-later
"""A part's Document Properties applied to the part (features thread). Drawings keep their own
(drawdocprops.py); a drawing's dimensions can start from a part's style with part_style(doc).

Dimensions (and the Angle / Diameter / Linear / Radius sub-pages' Primary precision, when set):
the number shown on feature dimensions and DimXpert/MBD dimensions takes Primary precision,
Leading zeroes, Trailing zeroes, Dual dimensions display (with Dual precision, Show units for dual
display, Dual dimension position) and Drafting Standard > All uppercase for dimensions (Exclusion
list kept as typed). Notes take All uppercase for notes.

Model Display (only once a row is set for the document, so the look's colours stay otherwise):
Shading color (bodies), Wireframe/HLR color (their edges; Apply same color to wireframe, HLR and
shaded uses the shading colour), Boss/Cut/Fillet/Chamfer color (the faces each kind of feature
made), Ignore feature colors (the feature colours are not used).

Plane Display: Show intersections (with Line Color) draws where shown reference planes cross; Back
Face Color (once set) colours the planes' back side.
Detailing: Point, Axis, and Coordinate System names shown beside them in the view (Hide names off;
Name font), Highlight associated elements on reference dimension selection (an MBD dimension's
faces and edges light up while it is picked), and the MBD annotations' font, text size and
dangling-annotation rows (mbd.py).

Image Quality: Improve curve quality at higher settings (curved bodies drawn with half the angular
deviation), Optimize edge length (half the deviation), Use isometric, zoom to fit view for
document preview (the file's thumbnail is taken from an isometric, fitted view).
"""

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

INCH = 25.4


def _v(doc, page, text, default):
    from . import optionspages
    return optionspages.doc_value(doc, page, text, default)


def _is_set(doc, page, text):
    from . import optionspages
    key = optionspages.DOC_META + optionspages._store_key(page, text)
    return doc is not None and key in dict(doc.Meta or {})


def _decimals(text, default=2):
    t = str(text or "").strip()
    if t in ("0", "None", ""):
        return 0 if t == "0" else default
    return len(t.split(".")[-1]) if "." in t else default


def _sub(kind):
    return {"Distance": "Linear", "DistanceX": "Linear", "DistanceY": "Linear", "Radius": "Radius",
            "Diameter": "Diameter", "Angle": "Angle"}.get(kind, "Linear")


EXCLUSIONS = "m;mm;cm;km;um;µm;nm;s;Hz;Pa;"       # Drafting Standard > Exclusion list default


def _length(doc):
    """(symbol, size in mm) of the document's length unit (Document Properties > Units)."""
    try:
        from . import unitspage
        return unitspage.length_unit(doc)
    except Exception:
        return ("mm", 1.0)


def in_units(doc, mm):
    """A length in mm as a number in the document's length unit (1.0 for 25.4 mm in an IPS part)."""
    return mm / _length(doc)[1]


def dual_unit(doc):
    """(symbol, size in mm) of the dual dimension: Document Properties > Units > Dual Dimension Length (until it is
    set: millimetres when the part is in inches or feet, else inches)."""
    try:
        from . import unitspage
        _name, sym, mm, _dec = unitspage.dual_length(doc)
        return sym, mm
    except Exception:
        return ("mm", 1.0) if _length(doc)[0] in ("in", "ft") else ("in", INCH)


def _dual_decimals(doc):
    try:
        from . import unitspage
        return unitspage.dual_length(doc)[3]
    except Exception:
        return 3


def _units_decimals(doc=None):
    try:
        from . import unitspage
        return unitspage.length_decimals(doc)       # the part's own (docdec-fix01)
    except Exception:
        return 2


def part_style(doc):
    ""

    precision = _decimals(_v(doc, "Dimensions", "Primary precision", ".12")) \
        if _is_set(doc, "Dimensions", "Primary precision") else _units_decimals(doc)
    return {"precision": precision,
            "dual": bool(_v(doc, "Dimensions", "Dual dimensions display", False)),

            "dual_precision": _decimals(_v(doc, "Dimensions", "Dual precision", ".123"), 3)
            if _is_set(doc, "Dimensions", "Dual precision") else _dual_decimals(doc),
            "dual_units": bool(_v(doc, "Dimensions", "Show units for dual display", False)),
            "dual_position": str(_v(doc, "Dimensions", "Dual dimension position", "Top")),
            "leading": str(_v(doc, "Dimensions", "Leading zeroes", "Standard")),
            "trailing": str(_v(doc, "Dimensions", "Trailing zeroes, dimensions", "Smart")),
            "upper_dims": bool(_v(doc, "Drafting Standard", "All uppercase for dimensions and hole callouts", False)),
            "upper_notes": bool(_v(doc, "Drafting Standard", "All uppercase for notes", False)),
            "exclusions": [e for e in str(_v(doc, "Drafting Standard", "Exclusion list", EXCLUSIONS) or "").split(";") if e],
            "font": str(_v(doc, "Dimensions", "Font", "Century Gothic"))}


ROUNDING = ("Round half away from zero", "Round half towards zero", "Round half to even", "Truncate without rounding")


def rounding(doc):
    ""
    try:
        from . import optionspages
        how = optionspages.doc_value(doc, "Units", "Decimal rounding", ROUNDING[0])
        return how if how in ROUNDING else ROUNDING[0]
    except Exception:
        return ROUNDING[0]


def rounded(value, decimals, how=ROUNDING[0]):
    ""

    import decimal
    mode = {ROUNDING[0]: decimal.ROUND_HALF_UP, ROUNDING[1]: decimal.ROUND_HALF_DOWN,
            ROUNDING[2]: decimal.ROUND_HALF_EVEN, ROUNDING[3]: decimal.ROUND_DOWN}.get(how, decimal.ROUND_HALF_UP)
    q = decimal.Decimal(1).scaleb(-max(0, int(decimals)))
    # repr() of the float, so 2.345 is 2.345 and not 2.34499999...
    return str(decimal.Decimal(repr(float(value))).quantize(q, rounding=mode))


def number(value, decimals, leading="Standard", trailing="Smart", how=None):
    text = rounded(value, decimals, how) if how else "%.*f" % (decimals, value)
    if text.startswith("-") and not text.strip("-0."):
        text = text[1:]                                       # -0.00 is 0.00
    if "." in text:
        if trailing == "Remove":
            text = text.rstrip("0").rstrip(".")
        elif trailing in ("Smart", "Standard"):
            whole = text.rstrip("0").rstrip(".")
            if "." not in whole:
                text = whole
    if leading == "Remove":
        if text.startswith("0."):
            text = text[1:]
        elif text.startswith("-0."):
            text = "-" + text[2:]
    return text


def upper(text, exclusions=()):
    out = []
    for word in text.split(" "):
        out.append(word if word in exclusions else word.upper())
    return " ".join(out)


def dim_text(doc, value, kind="Distance", prefix=""):
    ""

    st = part_style(doc)
    page = _sub(kind)
    dec = st["precision"]
    if _is_set(doc, page, "Primary precision") or kind == "Angle":
        dec = _decimals(_v(doc, page, "Primary precision", "0" if kind == "Angle" else ".12"))
    how = rounding(doc)
    symbol, size = _length(doc) if kind != "Angle" else ("", 1.0)

    trailing = "Show" if st["trailing"] == "Smart" and symbol in ("in", "ft") else st["trailing"]
    main = number(value / size, dec, st["leading"], trailing, how)
    if kind != "Angle" and fractional(doc):
        main = fraction(value / INCH, doc)
    if kind == "Angle":
        text = prefix + main + "°"
    else:
        text = prefix + main
        if st["dual"]:
            dual_symbol, dual_size = dual_unit(doc)
            dual = number(value / dual_size, st["dual_precision"], st["leading"], "Show", how)
            dual = "[%s%s]" % (dual, dual_symbol if st["dual_units"] else "")
            pos = st["dual_position"]
            text = {"Top": text + "\n" + dual, "Bottom": dual + "\n" + text,
                    "Left": dual + " " + text}.get(pos, text + " " + dual)
    if st["upper_dims"]:
        text = upper(text, st["exclusions"])
    return text


def fractional(doc):
    """The part shows inches as fractions (FreeCAD's Building US unit system)."""
    schema = str(getattr(doc, "UnitSystem", "") or "")
    if not schema:
        try:
            schema = "Building US" if App.ParamGet("User parameter:BaseApp/Preferences/Units").GetInt(
                "UserSchema", 0) == 5 else ""
        except Exception:
            schema = ""
    return "Building US" in schema or "raction" in schema


FRACTION_SLASH = {"Stacked": "\u2044", "Diagonal": "/", "Horizontal": "/", "Diagonal stacked": "\u2044"}


def fraction(inches, doc=None, denominator=64):
    """Dimensions > Fractional display: style, and Include leading zero for values less than 1"."""
    from fractions import Fraction
    neg = inches < 0
    f = Fraction(abs(inches)).limit_denominator(denominator)
    whole, rest = divmod(f.numerator, f.denominator)
    style = str(_v(doc, "Dimensions", "Fraction style", "Stacked")) if doc is not None else "Stacked"
    lead = bool(_v(doc, "Dimensions", "Include leading zero for values less than 1\"", False)) if doc else False
    parts = []
    if whole or lead or not rest:
        parts.append(str(whole))
    if rest:
        parts.append("%d%s%d" % (rest, FRACTION_SLASH.get(style, "/"), f.denominator))
    text = (" " if style == "Horizontal" else " ").join(parts) + '"'
    return ("-" if neg else "") + text


def table_text(doc, text):
    """Drafting Standard > All uppercase for tables (hole, revision, general tables and BOMs)."""
    st = part_style(doc)
    if bool(_v(doc, "Drafting Standard", "All uppercase for tables", False)):
        return upper(str(text), st["exclusions"])
    return text


def note_text(doc, text):
    st = part_style(doc)
    return upper(text, st["exclusions"]) if st["upper_notes"] else text


# --------------------------------------------------------------------------- Model Display
FEATURE_ROWS = {"Boss color": ("PartDesign::Pad", "PartDesign::Revolution", "PartDesign::AdditiveLoft",
                               "PartDesign::AdditivePipe", "PartDesign::AdditiveHelix", "PartDesign::AdditiveBox",
                               "PartDesign::AdditiveCylinder"),
                "Cut color": ("PartDesign::Pocket", "PartDesign::Groove", "PartDesign::Hole", "PartDesign::SubtractiveLoft",
                              "PartDesign::SubtractivePipe", "PartDesign::SubtractiveHelix"),
                "Fillet color": ("PartDesign::Fillet",), "Chamfer color": ("PartDesign::Chamfer",)}


def _rgb(text):
    t = str(text or "").strip().lstrip("#")
    if len(t) != 6:
        return None
    try:
        return tuple(int(t[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return None


def model_colors(doc):
    """{row: rgb} for the Model Display rows set for doc."""
    out = {}
    for row in ("Shading color", "Wireframe/HLR color", "Hidden color") + tuple(FEATURE_ROWS):
        if _is_set(doc, "Model Display", row):
            c = _rgb(_v(doc, "Model Display", row, ""))
            if c is not None:
                out[row] = c
    return out


def _owner_type(body, tip, i):
    try:
        from . import contextbar
        f = contextbar.owner_feature(tip, "Face%d" % (i + 1))
        return f.TypeId if f is not None else ""
    except Exception:
        return ""



def _face_colors(vo):
    """Per-face colours (r, g, b, a): FreeCAD 1.1 keeps them in ShapeAppearance, older ones in DiffuseColor."""
    try:
        mats = list(vo.ShapeAppearance)
        if mats:
            return [tuple(m.DiffuseColor[:3]) + (float(getattr(m, "Transparency", 0.0)),) for m in mats]
    except Exception as _fw_err:
        _fw_log("docstyle.py:253", _fw_err)
    try:
        return [tuple(c) for c in vo.DiffuseColor]
    except Exception:
        return []


def _set_face_colors(vo, colors):
    """Sets per-face colours through ShapeAppearance (one App.Material per face), else DiffuseColor."""
    colors = [tuple(float(x) for x in c) for c in colors]
    try:
        import FreeCAD as _App
        mats = []
        base = list(vo.ShapeAppearance) or [_App.Material()]
        for i, c in enumerate(colors):
            try:
                m = _App.Material(base[min(i, len(base) - 1)])
            except Exception:
                m = _App.Material()
            m.DiffuseColor = tuple(float(x) for x in c[:3]) + (1.0,)
            if len(c) > 3:
                m.Transparency = float(c[3])
            mats.append(m)
        vo.ShapeAppearance = mats
        return True
    except Exception as _fw_err:
        _fw_log("docstyle.py:279", _fw_err)
    try:
        vo.DiffuseColor = colors
        return True
    except Exception:
        return False


def apply_model_display(doc):
    """Colours bodies from the Model Display rows. The bodies coloured."""
    if not App.GuiUp or doc is None:
        return []
    colors = model_colors(doc)
    if not colors:
        return []
    ignore = bool(_v(doc, "Model Display", "Ignore feature colors", False))
    same = bool(_v(doc, "Model Display", "Apply same color to wireframe, HLR and shaded", False))
    feature = {} if ignore else {r: c for r, c in colors.items() if r in FEATURE_ROWS}
    done = []
    for body in [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]:
        vo = body.ViewObject
        tip = body.Tip
        if vo is None or tip is None or body.Shape.isNull():
            continue
        shade = colors.get("Shading color", tuple(vo.ShapeColor)[:3])
        if "Shading color" in colors:
            vo.ShapeColor = shade
        line = shade if same else colors.get("Wireframe/HLR color")
        if line is not None:
            vo.LineColor = line
        if feature:
            per = []
            for i in range(len(body.Shape.Faces)):
                t = _owner_type(body, tip, i)
                c = next((col for row, col in feature.items() if t in FEATURE_ROWS[row]), shade)
                per.append(tuple(c) + (0.0,))
            _set_face_colors(vo, per)
        done.append(body.Name)
    return done


# --------------------------------------------------------------------------- Image Quality
_quality = {}


def apply_image_quality(doc):
    if not App.GuiUp or doc is None:
        return []
    curves = bool(_v(doc, "Image Quality", "Improve curve quality at higher settings", False))
    edges = bool(_v(doc, "Image Quality", "Optimize edge length (higher quality, but slower)", False))
    done = []
    objs = doc.Objects
    if not curves and not edges:
        # extapps/70: both options off (the default) on every rebuild: only objects changed before need their own
        # quality back (it read two view properties of every object: 0.45 s a rebuild on a 100-feature part)
        objs = [doc.getObject(k[1]) for k in list(_quality) if k[0] == doc.Name]
        objs = [o for o in objs if o is not None]
    for o in objs:
        vo = getattr(o, "ViewObject", None)
        if vo is None or "Deviation" not in vo.PropertiesList or "AngularDeflection" not in vo.PropertiesList:
            continue
        key = (doc.Name, o.Name)
        if key not in _quality:
            _quality[key] = (vo.Deviation, vo.AngularDeflection.Value if hasattr(vo.AngularDeflection, "Value")
                             else float(vo.AngularDeflection))
        dev, ang = _quality[key]
        curved = False
        try:        # only asked when the option is on: every face of every feature, on each rebuild
            curved = curves and any(f.Surface.__class__.__name__ not in ("Plane",) for f in o.Shape.Faces)
        except Exception as _fw_err:
            _fw_log("docstyle.py:343", _fw_err)
        want_dev = dev * (0.5 if edges else 1.0)
        want_ang = ang * (0.5 if curves and curved else 1.0)
        if abs(vo.Deviation - want_dev) > 1e-9:
            vo.Deviation = want_dev
        cur = vo.AngularDeflection.Value if hasattr(vo.AngularDeflection, "Value") else float(vo.AngularDeflection)
        if abs(cur - want_ang) > 1e-9:
            vo.AngularDeflection = want_ang
        if edges or (curves and curved):
            done.append(o.Name)
    return done


_camera = {}


def preview_start(doc):
    """Before a save: an isometric, fitted view for the thumbnail (the view comes back after)."""
    import FreeCADGui as Gui
    if not bool(_v(doc, "Image Quality", "Use isometric, zoom to fit view for document preview", True)):
        return False
    gdoc = Gui.getDocument(doc.Name) if App.GuiUp else None
    view = getattr(gdoc, "ActiveView", None) if gdoc is not None else None
    if view is None or not hasattr(view, "getCamera"):
        return False
    _camera[doc.Name] = _cam_state(view)
    # Fitting walks the whole scene (2 s on a 300-component assembly): the fitted view of the last
    # save is used again while the document and the window are as they were then
    key = _fit_key(doc, view)
    fitted = _fitted.get(doc.Name)
    if key is not None and fitted is not None and fitted[0] == key:
        try:
            _set_cam_state(view, fitted[1])
            return True
        except Exception as _fw_err:
            _fw_log("docstyle.py:378", _fw_err)
    # no zoom animation: FreeCAD's animated fit runs the event loop for 0.3 s on every save
    params = App.ParamGet("User parameter:BaseApp/Preferences/View")
    animate = params.GetBool("UseNavigationAnimations", True)
    if animate:
        params.SetBool("UseNavigationAnimations", False)
    try:
        view.viewIsometric()
        view.fitAll()
    finally:
        if animate:
            params.SetBool("UseNavigationAnimations", True)
    if key is not None:
        try:
            _fitted[doc.Name] = (key, _cam_state(view))
        except Exception as _fw_err:
            _fw_log("docstyle.py:394", _fw_err)
    return True


_fitted = {}        # document name -> (key, the isometric fitted camera of its last save)


def _fit_key(doc, view):
    """What the fitted view hangs on: asmgen's change count (bumped by every recompute, new or
    deleted object, placement-driving property), the objects, and the window's size."""
    try:
        from . import asmgen
        gen = asmgen.gen(doc)
    except Exception:
        return None
    if gen == -1:
        return None
    try:
        size = view.getSize()
    except Exception:
        size = None
    moved = 0.0         # a component dragged without a rebuild moves no count
    for o in doc.Objects:
        if not hasattr(o, "Placement"):     # cleaninstall-1120: FeaturePython objects without one
            continue
        try:
            b = o.Placement.Base
            moved += b.x * 1.0001 + b.y * 1.0002 + b.z * 1.0003 + o.Placement.Rotation.Angle
        except Exception as _fw_err:
            _fw_log("docstyle.py:421", _fw_err)
    return (gen, len(doc.Objects), round(moved, 6), tuple(size) if size is not None else None)


def preview_end(doc):
    import FreeCADGui as Gui
    cam = _camera.pop(doc.Name, None)
    if cam is None:
        return False
    gdoc = Gui.getDocument(doc.Name)
    try:
        _set_cam_state(gdoc.ActiveView, cam)
    except Exception:
        return False
    return True


def _cam_state(view):
    n = view.getCameraNode()
    out = {"position": n.position.getValue().getValue(), "orientation": n.orientation.getValue().getValue(),
           "focal": n.focalDistance.getValue()}
    for f in ("height", "heightAngle"):
        if hasattr(n, f):
            out[f] = getattr(n, f).getValue()
    return out


def _set_cam_state(view, st):
    n = view.getCameraNode()
    n.position.setValue(*st["position"])
    n.orientation.setValue(*st["orientation"])
    n.focalDistance.setValue(st["focal"])
    for f in ("height", "heightAngle"):
        if f in st and hasattr(n, f):
            getattr(n, f).setValue(st[f])


class _Watch:
    def slotRecomputedDocument(self, doc):
        from PySide import QtCore
        QtCore.QTimer.singleShot(0, lambda d=doc: _safe(apply_all, d))

    def slotStartSaveDocument(self, doc, filename):
        _safe(preview_start, doc)
        _safe(store_appearance, doc)
        _safe(ole_start, doc)

    def slotFinishSaveDocument(self, doc, filename):
        _safe(preview_end, doc)
        _safe(ole_end, doc)

    def slotFinishRestoreDocument(self, doc):
        from PySide import QtCore
        QtCore.QTimer.singleShot(600, lambda d=doc: (_safe(restore_appearance, d), _safe(apply_all, d)))


# --------------------------------------------------------------------------- Model Display: storage
APPEARANCE = "FreeWorks:Appearance"
DEFAULT_GREY = (0.8, 0.8, 0.8)


def store_appearance(doc):
    """Store appearance, decal, and scene data in model file: the colours go into the part file
    itself as well (they come back when it is opened where its display file was not kept)."""
    import json
    meta = dict(doc.Meta or {})
    if not _v(doc, "Model Display", "Store appearance, decal, and scene data in model file", False):
        if APPEARANCE in meta:
            del meta[APPEARANCE]
            doc.Meta = meta
        return None
    out = {}
    for o in doc.Objects:
        vo = getattr(o, "ViewObject", None)
        if vo is None or not hasattr(vo, "ShapeColor"):
            continue
        rec = {"ShapeColor": list(vo.ShapeColor)[:3], "Transparency": int(vo.Transparency)}
        try:
            dc = _face_colors(vo)
            if dc and len(set(dc)) > 1:
                rec["DiffuseColor"] = [list(c) for c in dc]
        except Exception as _fw_err:
            _fw_log("docstyle.py:503", _fw_err)
        out[o.Name] = rec
    meta[APPEARANCE] = json.dumps(out)
    doc.Meta = meta
    return out


def restore_appearance(doc):
    import json
    text = dict(doc.Meta or {}).get(APPEARANCE)
    if not text:
        return 0
    n = 0
    for name, rec in json.loads(text).items():
        o = doc.getObject(name)
        vo = getattr(o, "ViewObject", None) if o is not None else None
        if vo is None or not hasattr(vo, "ShapeColor"):
            continue
        if tuple(round(c, 3) for c in vo.ShapeColor[:3]) != DEFAULT_GREY or \
                tuple(round(c, 3) for c in rec["ShapeColor"]) == DEFAULT_GREY:
            continue                  # the display file kept its own colours
        vo.ShapeColor = tuple(rec["ShapeColor"])
        vo.Transparency = rec.get("Transparency", 0)
        if rec.get("DiffuseColor"):
            _set_face_colors(vo, rec["DiffuseColor"])
        n += 1
    return n


_ole = {}
DOC_PARAM = "User parameter:BaseApp/Preferences/Document"


def ole_start(doc):
    """Store images for OLE object data in model file: the picture inside the file (its thumbnail)."""
    p = App.ParamGet(DOC_PARAM)
    _ole[doc.Name] = p.GetBool("SaveThumbnail", True)
    p.SetBool("SaveThumbnail", bool(_v(doc, "Model Display", "Store images for OLE object data in model file", True)))


def ole_end(doc):
    if doc.Name in _ole:
        App.ParamGet(DOC_PARAM).SetBool("SaveThumbnail", _ole.pop(doc.Name))


def apply_all(doc):
    try:
        if doc is None or doc.Name not in App.listDocuments():
            return
    except Exception:
        return              # the document closed before the timer fired
    apply_model_display(doc)
    apply_image_quality(doc)
    apply_overlay(doc)
    try:
        from . import mbd
        mbd.restyle_all(doc)
    except Exception as _fw_err:
        _fw_log("docstyle.py:561", _fw_err)


# --------------------------------------------------------------------------- overlay: planes, names
OVERLAY = "FWDocStyleOverlay"
PLANES = ("App::Plane", "PartDesign::Plane")
NAMED = ("PartDesign::Line", "PartDesign::Point", "PartDesign::CoordinateSystem")
last_overlay = {}           # doc -> {"intersections": n, "backs": n, "names": [..]} for checks


def _visible(o):
    """Shown on screen. An origin plane keeps Visibility True while its App::Origin is hidden
    (FreeCAD draws it only while the Origin is shown), so the Origin must be shown too; else every
    part drew the three origin planes' crossings as X/Y/Z lines through it (Ati 2026-11-06)."""
    try:
        if not (bool(o.ViewObject.Visibility) and o.ViewObject.isVisible()):
            return False
        for p in o.InList:
            if p.isDerivedFrom("App::Origin") and not p.ViewObject.Visibility:
                return False
        return True
    except Exception:
        return False


def _plane_face(o):
    """The plane's face where it is in the part (App::Plane keeps its shape in its own frame)."""
    try:
        s = o.Shape
        if not s.Faces:
            return None
        f = s.Faces[0].copy()
        if o.TypeId == "App::Plane":
            f.Placement = o.getGlobalPlacement()
        if f.BoundBox.DiagonalLength > 1e9:
            f = _finite(o, f)
        return f
    except Exception as _fw_err:
        _fw_log("docstyle.py:600", _fw_err)
        return None


def _finite(o, face):
    """An endless plane (the origin planes) as the square it is drawn as: its own Length/Width, else
    a little bigger than the part."""
    import Part
    pl = o.getGlobalPlacement()
    half = None
    for prop in ("Length", "Width"):
        v = getattr(o, prop, None)
        if v is not None:
            half = max(half or 0.0, (v.Value if hasattr(v, "Value") else float(v)) / 2.0)
    if not half:
        diag = 0.0
        for b in o.Document.Objects:
            try:
                if b.TypeId == "PartDesign::Body" and not b.Shape.isNull() and b.Shape.Solids:
                    diag = max(diag, b.Shape.BoundBox.DiagonalLength)
            except Exception as _fw_err:
                _fw_log("docstyle.py:619", _fw_err)
        half = max(diag * 0.6, 10.0)
    r = pl.Rotation
    c = pl.Base
    ex, ey = r.multVec(App.Vector(1, 0, 0)), r.multVec(App.Vector(0, 1, 0))
    pts = [c + ex * sx * half + ey * sy * half for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    return Part.Face(Part.makePolygon(pts + [pts[0]]))


def plane_intersections(doc):
    """[(p1, p2)] where two shown planes cross (inside both)."""
    faces = [(o, _plane_face(o)) for o in doc.Objects if o.TypeId in PLANES and _visible(o)]
    faces = [(o, f) for o, f in faces if f is not None]
    out = []
    for i in range(len(faces)):
        for j in range(i + 1, len(faces)):
            try:
                sec = faces[i][1].section(faces[j][1])
            except Exception:
                continue
            for e in sec.Edges:
                out.append((e.Vertexes[0].Point, e.Vertexes[-1].Point))
    return out


def _root(doc):
    import FreeCADGui as Gui
    try:
        return Gui.getDocument(doc.Name).ActiveView.getSceneGraph()
    except Exception:
        return None


def _remove_overlay(root):
    for i in reversed(range(root.getNumChildren())):
        if root.getChild(i).getName() == OVERLAY:
            root.removeChild(i)


def apply_overlay(doc):
    if not App.GuiUp or doc is None:
        return None
    root = _root(doc)
    if root is None:
        return None
    from pivy import coin
    _remove_overlay(root)
    sep = coin.SoSeparator()
    sep.setName(OVERLAY)
    info = {"intersections": 0, "backs": 0, "names": []}
    if _v(doc, "Plane Display", "Show intersections", True):
        segs = plane_intersections(doc)
        if segs:
            col = _rgb(_v(doc, "Plane Display", "Line Color", "#3C3C3C")) or (0.24, 0.24, 0.24)
            n = coin.SoSeparator()
            c = coin.SoBaseColor()
            c.rgb.setValue(*col)
            st = coin.SoDrawStyle()
            st.lineWidth.setValue(1.5)
            co = coin.SoCoordinate3()
            pts = [tuple(p) for seg in segs for p in seg]
            co.point.setValues(0, len(pts), pts)
            ls = coin.SoLineSet()
            ls.numVertices.setValues(0, len(segs), [2] * len(segs))
            for x in (c, st, co, ls):
                n.addChild(x)
            sep.addChild(n)
            info["intersections"] = len(segs)
    if _is_set(doc, "Plane Display", "Back Face Color"):
        col = _rgb(_v(doc, "Plane Display", "Back Face Color", ""))
        if col is not None:
            for o in doc.Objects:
                if o.TypeId not in PLANES or not _visible(o):
                    continue
                f = _plane_face(o)
                if f is None:
                    continue
                n = coin.SoSeparator()
                hints = coin.SoShapeHints()
                hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
                hints.shapeType = coin.SoShapeHints.SOLID          # culled from the front
                m = coin.SoMaterial()
                m.diffuseColor.setValue(*col)
                m.transparency.setValue(min(0.9, float(_v(doc, "Plane Display", "Transparency (%)", 75)) / 100.0))
                off = coin.SoPolygonOffset()
                co = coin.SoCoordinate3()
                normal = f.normalAt(0, 0)
                pts = [v.Point for v in f.OuterWire.OrderedVertexes]
                # wound against the face normal: its front looks out of the plane's back
                centre = f.CenterOfMass
                import math
                ax = (pts[0] - centre).normalize() if pts else App.Vector(1, 0, 0)
                ay = normal.cross(ax)
                pts.sort(key=lambda p: -math.atan2((p - centre).dot(ay), (p - centre).dot(ax)))
                co.point.setValues(0, len(pts), [tuple(p) for p in pts])
                fs = coin.SoFaceSet()
                fs.numVertices.setValues(0, 1, [len(pts)])
                for x in (hints, m, off, co, fs):
                    n.addChild(x)
                sep.addChild(n)
                info["backs"] += 1
    if not _v(doc, "Detailing", "Hide names", False):
        font = str(_v(doc, "Detailing", "Name font", "Century Gothic"))
        for o in doc.Objects:
            if o.TypeId not in NAMED or not _visible(o):
                continue
            try:
                bb = o.Shape.BoundBox
                at = App.Vector(bb.XMax, bb.YMax, bb.ZMax)
            except Exception:
                continue
            n = coin.SoSeparator()
            c = coin.SoBaseColor()
            c.rgb.setValue(0.1, 0.1, 0.1)
            t = coin.SoTranslation()
            t.translation.setValue(tuple(at))
            fo = coin.SoFont()
            fo.name.setValue(font)
            fo.size.setValue(12)
            tx = coin.SoText2()
            tx.string.setValue(o.Label)
            for x in (c, t, fo, tx):
                n.addChild(x)
            sep.addChild(n)
            info["names"].append(o.Label)
    if not _v(doc, "Detailing", "Hide names", False):
        lfont = str(_v(doc, "Detailing", "Label font", "Century Gothic"))
        for o in doc.Objects:
            if o.TypeId != "PartDesign::CoordinateSystem" or not _visible(o):
                continue
            pl = o.getGlobalPlacement()
            size = 10.0
            try:
                size = max(o.Shape.BoundBox.DiagonalLength * 0.6, 5.0)
            except Exception as _fw_err:
                _fw_log("docstyle.py:754", _fw_err)
            for letter, axis in (("X", App.Vector(1, 0, 0)), ("Y", App.Vector(0, 1, 0)), ("Z", App.Vector(0, 0, 1))):
                n = coin.SoSeparator()
                c = coin.SoBaseColor()
                c.rgb.setValue(0.1, 0.1, 0.1)
                t = coin.SoTranslation()
                t.translation.setValue(tuple(pl.Base + pl.Rotation.multVec(axis) * size))
                fo = coin.SoFont()
                fo.name.setValue(lfont)
                fo.size.setValue(11)
                tx = coin.SoText2()
                tx.string.setValue(letter)
                for x in (c, t, fo, tx):
                    n.addChild(x)
                sep.addChild(n)
                info.setdefault("labels", []).append("%s.%s" % (o.Label, letter))
    if sep.getNumChildren():
        root.addChild(sep)
    last_overlay[doc.Name] = info
    return info


# --------------------------------------------------------------------------- highlight on dimension pick
HIGHLIGHT = "FWDocStyleHighlight"
highlighted = []


class _PickWatch:
    def addSelection(self, doc, obj, sub, pnt):
        _highlight(doc)

    def removeSelection(self, doc, obj, sub):
        _highlight(doc)

    def setSelection(self, doc):
        _highlight(doc)

    def clearSelection(self, doc):
        _highlight(doc)


_due = set()       # documents with a highlight redraw waiting for the event loop


def _highlight(docname):
    """One redraw per document for a run of picks (Select All of 300 components sent 300, each
    reading the whole selection)."""
    from PySide import QtCore
    if docname in _due:
        return
    _due.add(docname)

    def run():
        _due.discard(docname)
        _safe(highlight_refs, docname)
    QtCore.QTimer.singleShot(0, run)


def highlight_refs(docname):
    import FreeCADGui as Gui
    doc = App.getDocument(docname) if docname in App.listDocuments() else App.ActiveDocument
    docname = doc.Name if doc is not None else docname
    if doc is None:
        return []
    root = _root(doc)
    if root is None:
        return []
    for i in reversed(range(root.getNumChildren())):
        if root.getChild(i).getName() == HIGHLIGHT:
            root.removeChild(i)
    highlighted[:] = []
    if not _v(doc, "Detailing", "Highlight associated elements on reference dimension selection", True):
        return []
    try:
        from . import mbd
        picked = [o for o in Gui.Selection.getSelection(docname) if mbd.is_pmi(o)]
    except Exception:
        picked = []
    if not picked:
        return []
    from pivy import coin
    sep = coin.SoSeparator()
    sep.setName(HIGHLIGHT)
    c = coin.SoBaseColor()
    c.rgb.setValue(1.0, 0.55, 0.0)
    st = coin.SoDrawStyle()
    st.lineWidth.setValue(3.0)
    sep.addChild(c)
    sep.addChild(st)
    for pmi in picked:
        for o, subs in pmi.References:
            for sub in subs or []:
                try:
                    el = o.getSubObject(sub)
                except Exception:
                    el = None
                if el is None:
                    continue
                for e in el.Edges:
                    pts = [tuple(p) for p in e.discretize(24)]
                    co = coin.SoCoordinate3()
                    co.point.setValues(0, len(pts), pts)
                    ls = coin.SoLineSet()
                    ls.numVertices.setValues(0, 1, [len(pts)])
                    n = coin.SoSeparator()
                    n.addChild(co)
                    n.addChild(ls)
                    sep.addChild(n)
                highlighted.append((o.Name, sub))
    root.addChild(sep)
    return list(highlighted)


_sig = {}


_opened = set()


def _tick():
    doc = App.ActiveDocument
    if doc is None:
        return
    key = (doc.Name, doc.FileName)
    if key not in _opened:
        # FreeCAD 1.1 does not send slotFinishRestoreDocument: an opened part is caught here
        _opened.add(key)
        if doc.FileName:
            _safe(restore_appearance, doc)
            _safe(apply_all, doc)
    try:
        sig = tuple((o.Name, _visible(o)) for o in doc.Objects if o.TypeId in PLANES + NAMED)
    except Exception:
        return
    if _sig.get(doc.Name) != sig:
        _sig[doc.Name] = sig
        _safe(apply_overlay, doc)
    _safe(_view_tick, doc)


_view = {}


def _view_tick(doc):
    """Display items only in the view in which they are created: re-check when the view turns."""
    from . import mbd
    if not _v(doc, "Detailing", "Display items only in the view in which they are created", False):
        if _view.pop(doc.Name, None) is not None:
            mbd.restyle_all(doc)        # turned off: everything shows again
        return
    v = mbd.view_direction()
    key = tuple(round(c, 2) for c in v) if v is not None else None
    if _view.get(doc.Name) != key:
        _view[doc.Name] = key
        mbd.restyle_all(doc)


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as error:
        App.Console.PrintLog("FreeCAD docstyle: %s: %s\n" % (getattr(fn, "__name__", fn), error))


_installed = []


def install():
    try:
        from . import unitspage
        unitspage.install()     # each part's own length decimals (docdec-fix01)
    except Exception as _fw_err:
        _fw_log("docstyle.py:units follow", _fw_err)
    if not _installed:
        w = _Watch()
        App.addDocumentObserver(w)
        _installed.append(w)
        if App.GuiUp:
            import FreeCADGui as Gui
            from PySide import QtCore
            pw = _PickWatch()
            Gui.Selection.addObserver(pw)
            _installed.append(pw)
            # shown/hidden planes and names follow the view (visibility changes need no rebuild)
            t = QtCore.QTimer()
            t.timeout.connect(_tick)
            t.start(1500)
            _installed.append(t)
    return _installed[0]
