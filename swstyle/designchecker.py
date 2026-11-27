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

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/DesignChecker"
EXT = "fwchk"
TOL = 1e-6

# key: (title, kind of value, default)
CHECKS = (
    ("units", "Document units", "units", 0),
    ("sketches_defined", "Sketches fully defined", "bool", True),
    ("no_errors", "No features with errors", "bool", True),
    ("no_suppressed", "No suppressed features", "bool", False),
    ("fillet_radii", "Fillet radii allowed (mm)", "list", ""),
    ("chamfer_sizes", "Chamfer sizes allowed (mm)", "list", ""),
    ("hole_diameters", "Hole diameters allowed (mm)", "list", ""),
    ("min_wall", "Minimum fillet radius (mm)", "number", 0.0),
    ("material", "Material assigned", "bool", False),
    ("properties", "Custom properties required", "text", ""),
    ("single_body", "One solid body per part", "bool", False),
    ("doc_props", "Document properties filled in", "text", "CreatedBy"),
    ("asm_defined", "Assembly components fully defined", "bool", True),
    ("mate_errors", "Mates have no errors", "bool", True),

    ("dim_font", "Dimension font", "text", "Century Gothic"),
    ("dim_precision", "Dimension precision (decimals)", "number", 2),
    ("arrow_style", "Dimension arrow style", "text", "Filled"),
    ("overridden", "No overridden dimension values", "bool", True),
    ("dangling", "No dangling dimensions or relations", "bool", True),
    ("tol_types", "Tolerance types allowed", "text", "Symmetric, Bilateral, Basic"),
    ("draft_angles", "Draft angles allowed (deg)", "list", ""),
    ("shell_thickness", "Shell thickness allowed (mm)", "list", ""),
    ("bend_radii", "Sheet metal bend radii allowed (mm)", "list", ""),
    ("sheet_thickness", "Sheet metal thickness allowed (mm)", "list", ""),
    ("grid_off", "Grid display off", "bool", True),
    ("file_name", "File name pattern", "text", ""),
    ("one_fixed", "Only one fixed component", "bool", True),
    ("no_suppressed_comps", "No suppressed components", "bool", False),
)
CATEGORIES = (("Document Checks", ("units", "material", "properties", "doc_props", "grid_off", "file_name")),
              ("Feature Checks", ("sketches_defined", "no_errors", "no_suppressed", "fillet_radii", "chamfer_sizes",
                                  "hole_diameters", "min_wall", "single_body", "draft_angles", "shell_thickness",
                                  "bend_radii", "sheet_thickness")),
              ("Dimension Checks", ("dim_font", "dim_precision", "arrow_style", "overridden", "dangling", "tol_types")),
              ("Assembly Checks", ("asm_defined", "mate_errors", "one_fixed", "no_suppressed_comps")))
TITLES = {k: t for k, t, _kind, _d in CHECKS}
SEVERITIES = ("High", "Medium", "Low")
SEVERITY = {"no_errors": "High", "mate_errors": "High", "sketches_defined": "Low", "no_suppressed": "Low"}
PART_ONLY = ("fillet_radii", "chamfer_sizes", "hole_diameters", "min_wall", "material", "single_body",
             "draft_angles", "shell_thickness", "bend_radii", "sheet_thickness")
ASM_ONLY = ("asm_defined", "mate_errors", "one_fixed", "no_suppressed_comps")
CORRECTABLE = ("units", "properties", "doc_props", "dim_font", "dim_precision", "arrow_style", "grid_off")
DOC_PROPS = ("CreatedBy", "Company", "Comment", "License")
# the earlier assembly checker's check ids -> these keys
_FWSTD = {"doc_prop": "doc_props", "custom_prop": "properties", "units": "units", "material": "material",
          "sketch_defined": "sketches_defined", "feature_errors": "no_errors", "suppressed": "no_suppressed",
          "asm_defined": "asm_defined", "mate_errors": "mate_errors"}


def unit_schemas():
    try:
        return [App.Units.listSchemas(i) for i in range(App.Units.listSchemas())]
    except Exception:
        return ["Standard (mm, kg, s, degree)"]


def current_units():
    return App.ParamGet("User parameter:BaseApp/Preferences/Units").GetInt("UserSchema", 0)


def default_standard():
    return {key: {"on": key in ("sketches_defined", "no_errors", "asm_defined", "mate_errors"), "value": default,
                  "severity": SEVERITY.get(key, "Medium")}
            for key, _t, _kind, default in CHECKS}


def _assembly(doc):
    try:
        from . import asmcore as ac
        return ac.assembly_of(doc)
    except Exception:
        return None


def _pairs(text):
    """'PartNumber, Revision=A' -> [('PartNumber', ''), ('Revision', 'A')]"""
    out = []
    for part in str(text or "").split(","):
        k, _sep, v = part.strip().partition("=")
        if k.strip():
            out.append((k.strip(), v.strip()))
    return out


def _numbers(text):
    out = []
    for part in str(text).replace(";", ",").split(","):
        try:
            out.append(float(part.strip()))
        except ValueError as _fw_err:
            _fw_log("designchecker.py:137", _fw_err)
    return out


def _numbers_text(values):
    return ", ".join("%g" % v for v in sorted(set(round(v, 4) for v in values)))


def _features(doc, *types):
    return [o for o in doc.Objects if any(o.TypeId == t for t in types)]


def _radius(f):
    return float(getattr(f, "Radius", 0.0))


def _chamfer(f):
    return float(getattr(f, "Size", 0.0))


def _hole(f):
    return float(getattr(f, "Diameter", 0.0))


def _bodies(doc):
    return [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]


def _material(doc):
    for body in _bodies(doc):
        for prop in ("ShapeMaterial", "Material"):
            mat = getattr(body, prop, None)
            name = getattr(mat, "Name", None) if mat is not None else None
            if name and name.lower() not in ("default", "default material", ""):
                return name
    return None


def learn(doc):
    """A standard filled in from the document."""
    std = default_standard()
    std["units"] = {"on": True, "value": current_units()}
    radii = [_radius(f) for f in _features(doc, "PartDesign::Fillet")]
    sizes = [_chamfer(f) for f in _features(doc, "PartDesign::Chamfer")]
    holes = [_hole(f) for f in _features(doc, "PartDesign::Hole")]
    for key, values in (("fillet_radii", radii), ("chamfer_sizes", sizes), ("hole_diameters", holes)):
        std[key] = {"on": bool(values), "value": _numbers_text(values)}
    if radii:
        std["min_wall"] = {"on": True, "value": min(radii)}
    mat = _material(doc)
    std["material"] = {"on": mat is not None, "value": True}
    meta = sorted(k for k, v in (dict(getattr(doc, "Meta", {}) or {})).items() if v)
    std["properties"] = {"on": bool(meta), "value": ", ".join(meta)}
    sketches = [o for o in doc.Objects if o.isDerivedFrom("Sketcher::SketchObject")]
    std["sketches_defined"] = {"on": bool(sketches) and all(_fully_defined(s) for s in sketches), "value": True}
    std["no_errors"] = {"on": True, "value": True}
    std["no_suppressed"] = {"on": not any(getattr(o, "Suppressed", False) for o in doc.Objects), "value": True}
    std["single_body"] = {"on": all(len(b.Shape.Solids) <= 1 for b in _bodies(doc)), "value": True}
    filled = [n for n in DOC_PROPS if str(getattr(doc, n, "") or "").strip()]
    std["doc_props"] = {"on": bool(filled), "value": ", ".join(filled)}
    asm = _assembly(doc) is not None
    std["asm_defined"] = {"on": asm, "value": True}
    std["mate_errors"] = {"on": asm, "value": True}
    for key, kind, getter in (("draft_angles", "PartDesign::Draft", lambda f: _q(f.Angle)),
                              ("shell_thickness", "PartDesign::Thickness", lambda f: _q(f.Value))):
        vals = [getter(f) for f in _features(doc, kind)]
        std[key] = {"on": bool(vals), "value": _numbers_text(vals)}
    for key, prop in (("bend_radii", "radius"), ("sheet_thickness", "thickness")):
        vals = [_q(getattr(o, p)) for o, p in _sheet_metal(doc, prop)]
        std[key] = {"on": bool(vals), "value": _numbers_text(vals)}
    std["dim_font"] = {"on": True, "value": str(_dp(doc, "Dimensions", "Font", "Century Gothic"))}
    std["arrow_style"] = {"on": True, "value": str(_dp(doc, "Dimensions", "Arrow style", "Filled"))}
    pmi = _pmi(doc)
    if pmi:
        from . import mbd
        decs = [_decimals_of(o.Text) for o in pmi if o.Kind in ("Size", "Location", "Pattern") and not mbd.overridden(o)]
        if decs:
            std["dim_precision"] = {"on": True, "value": max(set(decs), key=decs.count)}
        std["tol_types"] = {"on": True, "value": ", ".join(sorted({_tol_type(o) for o in pmi if o.Kind in (
            "Size", "Location", "Angle", "BasicLocation", "BasicSize", "Pattern")}))}
    std["grid_off"] = {"on": not _grid_on(), "value": True}
    if asm:
        std["one_fixed"] = {"on": True, "value": True}
    for key, entry in std.items():
        entry.setdefault("severity", SEVERITY.get(key, "Medium"))
    return std


def _fully_defined(sketch):
    if "FullyConstrained" in sketch.PropertiesList:
        return bool(sketch.FullyConstrained)
    try:
        return sketch.solve() == 0 and not sketch.getGeometryWithDependentParameters()
    except Exception:
        return True


def _allowed(value, allowed):
    return any(abs(value - a) < 1e-4 for a in allowed)


def run(doc, std):
    """[(key, title, passed, [(object name, why)])] for the checks that are on."""
    out = []
    asm = _assembly(doc)

    def add(key, bad):
        out.append((key, TITLES[key], not bad, bad))
    for key, _title, _kind, _d in CHECKS:
        entry = std.get(key) or {}
        if not entry.get("on"):
            continue
        if (asm is not None and key in PART_ONLY) or (asm is None and key in ASM_ONLY):
            continue
        value = entry.get("value")
        bad = []
        if key == "units":
            if current_units() != int(value or 0):
                names = unit_schemas()
                want = names[int(value)] if 0 <= int(value) < len(names) else str(value)
                bad.append(("", "units are not %s" % want))
        elif key == "sketches_defined":
            for s in doc.Objects:
                if s.isDerivedFrom("Sketcher::SketchObject") and not _fully_defined(s):
                    bad.append((s.Name, "%s is under defined" % s.Label))
        elif key == "no_errors":
            for o in doc.Objects:
                if "Invalid" in o.State or "Error" in getattr(o, "State", []):
                    bad.append((o.Name, "%s has an error" % o.Label))
        elif key == "no_suppressed":
            for o in doc.Objects:
                if getattr(o, "Suppressed", False):
                    bad.append((o.Name, "%s is suppressed" % o.Label))
        elif key in ("fillet_radii", "chamfer_sizes", "hole_diameters"):
            allowed = _numbers(value)
            kind, size = {"fillet_radii": ("PartDesign::Fillet", _radius),
                          "chamfer_sizes": ("PartDesign::Chamfer", _chamfer),
                          "hole_diameters": ("PartDesign::Hole", _hole)}[key]
            for f in _features(doc, kind):
                if allowed and not _allowed(size(f), allowed):
                    bad.append((f.Name, "%s is %g mm (allowed: %s)" % (f.Label, size(f), _numbers_text(allowed))))
        elif key == "min_wall":
            for f in _features(doc, "PartDesign::Fillet"):
                if _radius(f) < float(value or 0) - TOL:
                    bad.append((f.Name, "%s radius %g mm is under %g mm" % (f.Label, _radius(f), float(value))))
        elif key == "material":
            if _bodies(doc) and _material(doc) is None:
                bad.append(("", "no material is assigned"))
        elif key == "properties":
            meta = dict(getattr(doc, "Meta", {}) or {})
            for name, want in _pairs(value):
                if not meta.get(name):
                    bad.append(("", "custom property %s is missing" % name))
                elif want and meta[name] != want:
                    bad.append(("", "custom property %s is %s, not %s" % (name, meta[name], want)))
        elif key == "doc_props":
            for name, want in _pairs(value):
                got = str(getattr(doc, name, "") or "")
                if not got.strip():
                    bad.append(("", "document property %s is empty" % name))
                elif want and got != want:
                    bad.append(("", "document property %s is %s, not %s" % (name, got, want)))
        elif key in ("asm_defined", "mate_errors"):
            from . import asmcore as ac
            if key == "mate_errors":
                for j in ac.mates(asm):
                    if ac.mate_error(j):
                        bad.append((j.Name, "%s has an error" % j.Label))
            else:
                for c, ok in ac.defined(asm).items():
                    if not ok:
                        bad.append((c.Name, "%s is not fully defined" % c.Label))
        elif key in EXTRA_RUN:
            bad = EXTRA_RUN[key](doc, value, asm)
        elif key == "single_body":
            for b in _bodies(doc):
                if len(b.Shape.Solids) > 1:
                    bad.append((b.Name, "%s has %d solid bodies" % (b.Label, len(b.Shape.Solids))))
        add(key, bad)
    return out


# --------------------------------------------------------------------------- the other checks
def _dp(doc, page, text, default):
    try:
        from . import optionspages
        return optionspages.doc_value(doc, page, text, default)
    except Exception:
        return default


def _pmi(doc):
    try:
        from . import mbd
        return [o for o in doc.Objects if mbd.is_pmi(o)]
    except Exception:
        return []


def _list_check(objs, size, allowed, unit, what):
    bad = []
    allowed = _numbers(allowed)
    for f in objs:
        v = size(f)
        if allowed and v is not None and not _allowed(v, allowed):
            bad.append((f.Name, "%s %s is %g %s (allowed: %s)" % (f.Label, what, v, unit, _numbers_text(allowed))))
    return bad


def _q(v):
    return float(getattr(v, "Value", v))


def _sheet_metal(doc, prop):
    out = []
    for o in doc.Objects:
        for p in (prop, prop.capitalize()):
            if p in o.PropertiesList and ("SheetMetal" in o.TypeId or "SM" in type(getattr(o, "Proxy", None)).__name__
                                          or "sheet" in o.Label.lower() or hasattr(o, "BendRadius") or hasattr(o, "radius")):
                out.append((o, p))
                break
    return out


def _decimals_of(text):
    import re
    m = re.search(r"\d+\.(\d+)", str(text))
    return len(m.group(1)) if m else 0


def _tol_type(o):
    if o.Kind.startswith("Basic"):
        return "Basic"
    if abs(o.Plus) < 1e-12 and abs(o.Minus) < 1e-12:
        return "None"
    if "\n" in str(o.Text):
        return "Limit"
    if "MIN" in str(o.Text):
        return "MIN"
    if "MAX" in str(o.Text):
        return "MAX"
    return "Symmetric" if abs(o.Plus + o.Minus) < 1e-9 else "Bilateral"


def _grid_on():
    p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Sketcher/General")
    return p.GetBool("ShowGrid", False)


def _check_dim_font(doc, value, _asm):
    got = str(_dp(doc, "Dimensions", "Font", "Century Gothic"))
    return [] if not value or got == str(value) else [("", "dimension font is %s, not %s" % (got, value))]


def _check_precision(doc, value, _asm):
    want = int(float(value or 0))
    bad = []
    from . import mbd
    for o in _pmi(doc):
        if o.Kind in ("Size", "Location", "Pattern", "Reference") and not mbd.overridden(o) and \
                _decimals_of(o.Text) != want:
            bad.append((o.Name, "%s shows %d decimals, not %d" % (o.Label, _decimals_of(o.Text), want)))
    return bad


def _check_arrows(doc, value, _asm):
    got = str(_dp(doc, "Dimensions", "Arrow style", "Filled"))
    return [] if not value or got == str(value) else [("", "arrow style is %s, not %s" % (got, value))]


def _check_overridden(doc, _value, _asm):
    from . import mbd
    return [(o.Name, "%s has an overridden value (%s)" % (o.Label, o.Text)) for o in _pmi(doc) if mbd.overridden(o)]


def _check_dangling(doc, _value, _asm):
    from . import mbd
    bad = [(o.Name, "%s is dangling" % o.Label) for o in _pmi(doc) if mbd.dangling(o)]
    for s in doc.Objects:
        if s.isDerivedFrom("Sketcher::SketchObject"):
            for prop in ("MalformedConstraints", "Conflicting", "Redundant"):
                v = list(getattr(s, prop, []) or [])
                if v:
                    bad.append((s.Name, "%s has %s relations %s" % (s.Label, prop.lower(), v)))
    return bad


def _check_tol_types(doc, value, _asm):
    allowed = [t.strip() for t in str(value or "").split(",") if t.strip()]
    return [(o.Name, "%s is %s (allowed: %s)" % (o.Label, _tol_type(o), ", ".join(allowed))) for o in _pmi(doc)
            if allowed and o.Kind in ("Size", "Location", "Angle", "BasicLocation", "BasicSize", "Pattern")
            and _tol_type(o) not in allowed]


def _check_draft(doc, value, _asm):
    return _list_check(_features(doc, "PartDesign::Draft"), lambda f: _q(f.Angle), value, "deg", "draft angle")


def _check_shell(doc, value, _asm):
    return _list_check(_features(doc, "PartDesign::Thickness"), lambda f: _q(f.Value), value, "mm", "thickness")


def _check_bends(doc, value, _asm):
    pairs = _sheet_metal(doc, "radius")
    objs = [o for o, _p in pairs]
    props = dict((o.Name, p) for o, p in pairs)
    return _list_check(objs, lambda f: _q(getattr(f, props[f.Name])), value, "mm", "bend radius")


def _check_sheet(doc, value, _asm):
    pairs = _sheet_metal(doc, "thickness")
    objs = [o for o, _p in pairs]
    props = dict((o.Name, p) for o, p in pairs)
    return _list_check(objs, lambda f: _q(getattr(f, props[f.Name])), value, "mm", "thickness")


def _check_grid(_doc, value, _asm):
    return [("", "the sketch grid is shown")] if value and _grid_on() else []


def _check_name(doc, value, _asm):
    import fnmatch
    if not value:
        return []
    name = os.path.basename(doc.FileName) if doc.FileName else doc.Label
    return [] if fnmatch.fnmatch(name.lower(), str(value).lower()) or \
        fnmatch.fnmatch(os.path.splitext(name)[0].lower(), str(value).lower()) else \
        [("", "file name %s does not match %s" % (name, value))]


def _check_one_fixed(_doc, _value, asm):
    from . import asmcore as ac
    fixed = list(ac.grounded(asm))
    return [] if len(fixed) <= 1 else [(c.Name, "%s is fixed too" % c.Label) for c in fixed[1:]]


def _check_suppressed_comps(_doc, _value, asm):
    from . import asmcore as ac
    out = []
    for c in ac.components(asm):
        if getattr(c, "Suppressed", False) or getattr(c, "FwSuppressed", False):
            out.append((c.Name, "%s is suppressed" % c.Label))
    return out


EXTRA_RUN = {"dim_font": _check_dim_font, "dim_precision": _check_precision, "arrow_style": _check_arrows,
             "overridden": _check_overridden, "dangling": _check_dangling, "tol_types": _check_tol_types,
             "draft_angles": _check_draft, "shell_thickness": _check_shell, "bend_radii": _check_bends,
             "sheet_thickness": _check_sheet, "grid_off": _check_grid, "file_name": _check_name,
             "one_fixed": _check_one_fixed, "no_suppressed_comps": _check_suppressed_comps}


def check_folder(std, folder, recursive=False):
    """Design Checker in the Task Scheduler: every model file of a folder checked, one report."""
    with _KeepActive():
        return _check_folder(std, folder, recursive)


def _check_folder(std, folder, recursive):
    lines, n, failed = [], 0, 0
    for root, _dirs, files in os.walk(folder):
        for f in sorted(files):
            if not f.lower().endswith(".fcstd"):
                continue
            path = os.path.join(root, f)
            open_docs = {d.FileName: d for d in App.listDocuments().values()}
            doc = open_docs.get(path)
            opened = doc is None
            try:
                if opened:
                    try:
                        doc = App.openDocument(path, hidden=True)
                    except TypeError:
                        doc = App.openDocument(path)
                results = run(doc, std)
                n += 1
                bad = [r for r in results if not r[2]]
                failed += bool(bad)
                lines.append(report(doc, std, results))
            except Exception as error:
                lines.append("%s: could not be checked (%s)\n" % (path, error))
            finally:
                if opened and doc is not None and doc.Name in App.listDocuments():
                    App.closeDocument(doc.Name)
        if not recursive:
            break
    lines.append("%d files checked, %d with failed checks\n" % (n, failed))
    return "\n".join(lines), n, failed


def severity(std, key):
    return (std.get(key) or {}).get("severity") or SEVERITY.get(key, "Medium")


def sorted_results(results, std):
    """Failed checks first, then by severity."""
    order = {s: i for i, s in enumerate(SEVERITIES)}
    return sorted(results, key=lambda r: (r[2], order.get(severity(std, r[0]), 3)))


def correct(doc, std, key):
    """Fixes a failed check where Design Checker can (missing properties, units). True when it did."""
    value = (std.get(key) or {}).get("value")
    if key == "properties":
        meta = dict(getattr(doc, "Meta", {}) or {})
        for name, want in _pairs(value):
            if not meta.get(name) or (want and meta[name] != want):
                meta[name] = want or "-"
        doc.Meta = meta
        return True
    if key == "doc_props":
        author = App.ParamGet("User parameter:BaseApp/Preferences/Document").GetString("prefAuthor", "") or "FreeCAD"
        for name, want in _pairs(value):
            got = str(getattr(doc, name, "") or "")
            if not got.strip() or (want and got != want):
                try:
                    setattr(doc, name, want or author)
                except Exception:
                    return False
        return True
    if key in ("dim_font", "dim_precision", "arrow_style"):
        from . import optionspages
        if key == "dim_font":
            optionspages._doc_set("Dimensions", "Font", str(value))
        elif key == "arrow_style":
            optionspages._doc_set("Dimensions", "Arrow style", str(value))
        else:
            want = int(float(value or 0))
            optionspages._doc_set("Dimensions", "Primary precision", "0" if want == 0 else "." + "123456"[:want])
            try:
                from . import mbd
                for o in _pmi(doc):
                    if o.Kind in ("Size", "Location", "Pattern", "Reference") and not mbd.overridden(o):
                        import re
                        o.Text = re.sub(r"\d+\.\d+|\d+(?=\s|$)", lambda m: "%.*f" % (want, float(m.group(0))),
                                        str(o.Text))
                        if "AutoText" in o.PropertiesList:
                            o.AutoText = o.Text
                mbd.restyle_all(doc)
            except Exception as _fw_err:
                _fw_log("designchecker.py:572", _fw_err)
        return True
    if key == "grid_off":
        App.ParamGet("User parameter:BaseApp/Preferences/Mod/Sketcher/General").SetBool("ShowGrid", False)
        return True
    if key == "units":
        names = unit_schemas()
        try:
            doc.UnitSystem = names[int(value or 0)]
            return True
        except Exception:
            return False
    return False


def report(doc, std, results):
    lines = ["Design Checker report: %s" % (doc.FileName or doc.Label), ""]
    for key, title, passed, bad in sorted_results(results, std):
        lines.append("%-6s  %-4s  %s" % (severity(std, key), "Pass" if passed else "Fail", title))
        lines += ["                %s" % why for _n, why in bad]
    failed = sum(1 for r in results if not r[2])
    lines += ["", "%d checks, %d failed" % (len(results), failed)]
    return "\n".join(lines) + "\n"


def save(std, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"FreeWorksDesignChecks": 1, "checks": std}, f, indent=1)
    App.ParamGet(PARAMS).SetString("LastStandard", path)


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    std = default_standard()
    checks = data.get("checks", {})
    if isinstance(checks, list):              # a .fwstd from the earlier assembly checker
        for entry in std.values():
            entry["on"] = False
        merged = {}
        for c in checks:
            key = _FWSTD.get(c.get("id"))
            if key is None:
                continue
            e = merged.setdefault(key, {"on": False, "value": [] if key in ("properties", "doc_props") else None,
                                        "severity": c.get("severity") or SEVERITY.get(key, "Medium")})
            e["on"] = e["on"] or bool(c.get("on", True))
            if key in ("properties", "doc_props"):
                if c.get("value"):
                    e["value"].append(c["value"])
            elif key == "units" and c.get("value"):
                names = unit_schemas()
                e["value"] = next((i for i, n in enumerate(names) if str(c["value"]) in n), 0)
            else:
                e["value"] = True
        for key, e in merged.items():
            if isinstance(e["value"], list):
                e["value"] = ", ".join(e["value"])
            if e["value"] is None:
                e["value"] = std[key]["value"]
            std[key] = e
        return std
    std.update(checks)
    return std


def last_standard():
    path = App.ParamGet(PARAMS).GetString("LastStandard", "")
    if path and os.path.exists(path):
        try:
            return load(path), path
        except Exception as _fw_err:
            _fw_log("designchecker.py:644", _fw_err)
    return default_standard(), ""


class _KeepActive:
    ""



    def __enter__(self):
        self.name = getattr(App.ActiveDocument, "Name", None)
        self.sub = None
        try:
            from PySide import QtWidgets as _W
            area = Gui.getMainWindow().findChild(_W.QMdiArea) if Gui is not None else None
            self.area = area
            self.sub = area.activeSubWindow() if area is not None else None
        except Exception:
            self.area = None
        return self

    def __exit__(self, *_exc):
        if not self.name or self.name not in App.listDocuments():
            return False
        try:
            App.setActiveDocument(self.name)
            if Gui is not None:
                Gui.setActiveDocument(self.name)
            if self.area is not None and self.sub is not None and self.sub in self.area.subWindowList():
                self.area.setActiveSubWindow(self.sub)
        except Exception as _fw_err:
            _fw_log("designchecker.py:keepactive", _fw_err)
        return False


def learn_from_file(path):
    """Opens a model file hidden, learns its standard, closes it."""
    already = [d for d in App.listDocuments().values() if d.FileName and os.path.samefile(d.FileName, path)] \
        if os.path.exists(path) else []
    if already:
        return learn(already[0])
    with _KeepActive():
        doc = App.openDocument(path, hidden=True)
        try:
            return learn(doc)
        finally:
            App.closeDocument(doc.Name)


if Gui is not None:
    def _mw():
        return Gui.getMainWindow()

    def _file_filter():
        return "Design checks (*.%s *.fwstd)" % EXT

    class BuildChecks(QtWidgets.QDialog):
        """The checks as rows: a check box and a value each; Save writes the standard."""

        def __init__(self, std=None, title="Build Checks"):
            super().__init__(_mw())
            self.setWindowTitle(title)
            self.setObjectName("SWDesignCheckerBuild")
            self.resize(520, 420)
            self.std = std or last_standard()[0]
            lay = QtWidgets.QVBoxLayout(self)
            self.resize(600, 560)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            inner = QtWidgets.QWidget()
            grid = QtWidgets.QGridLayout(inner)
            scroll.setWidget(inner)
            self.rows = {}
            kinds = {k: (t, kd, d) for k, t, kd, d in CHECKS}
            order = []
            for head, keys in CATEGORIES:
                order.append((None, head))
                order += [(k, None) for k in keys if k in kinds]
            r = -1
            for key, head in order:
                r += 1
                if key is None:
                    lbl = QtWidgets.QLabel("<b>%s</b>" % head)
                    grid.addWidget(lbl, r, 0, 1, 3)
                    continue
                title_, kind, _d = kinds[key]
                entry = self.std.get(key, {})
                box = QtWidgets.QCheckBox(title_)
                box.setChecked(bool(entry.get("on")))
                grid.addWidget(box, r, 0)
                value = entry.get("value")
                if kind == "units":
                    w = QtWidgets.QComboBox()
                    w.addItems(unit_schemas())
                    w.setCurrentIndex(int(value or 0))
                elif kind == "number":
                    w = QtWidgets.QDoubleSpinBox()
                    w.setRange(0, 1e5)
                    w.setDecimals(0 if key == "dim_precision" else 3)
                    w.setSuffix("" if key == "dim_precision" else " mm")
                    w.setValue(float(value or 0))
                elif kind in ("list", "text"):
                    w = QtWidgets.QLineEdit(str(value or ""))
                    w.setPlaceholderText("e.g. 1, 2, 5" if kind == "list" else "e.g. PartNumber, Description")
                else:
                    w = None
                if w is not None:
                    grid.addWidget(w, r, 1)
                sev = QtWidgets.QComboBox()
                sev.addItems(SEVERITIES)
                sev.setCurrentText(entry.get("severity") or SEVERITY.get(key, "Medium"))
                grid.addWidget(sev, r, 2)
                self.rows[key] = (box, w, kind, sev)
            lay.addWidget(scroll, 1)
            buttons = QtWidgets.QHBoxLayout()
            for text, slot in (("Open...", self._open), ("Learn from Active Document", self._learn),
                               ("Save...", self._save), ("Close", self.close)):
                b = QtWidgets.QPushButton(text)
                b.clicked.connect(slot)
                buttons.addWidget(b)
            lay.addLayout(buttons)
            self.status = QtWidgets.QLabel("")
            lay.addWidget(self.status)

        def standard(self):
            out = {}
            for key, (box, w, kind, sev) in self.rows.items():
                if kind == "units":
                    value = w.currentIndex()
                elif kind == "number":
                    value = w.value()
                elif kind in ("list", "text"):
                    value = w.text()
                else:
                    value = True
                out[key] = {"on": box.isChecked(), "value": value, "severity": sev.currentText()}
            return out

        def set_standard(self, std):
            for key, (box, w, kind, sev) in self.rows.items():
                entry = std.get(key, {})
                box.setChecked(bool(entry.get("on")))
                sev.setCurrentText(entry.get("severity") or SEVERITY.get(key, "Medium"))
                value = entry.get("value")
                if kind == "units":
                    w.setCurrentIndex(int(value or 0))
                elif kind == "number":
                    w.setValue(float(value or 0))
                elif kind in ("list", "text"):
                    w.setText(str(value or ""))

        def _learn(self):
            if App.ActiveDocument is not None:
                self.set_standard(learn(App.ActiveDocument))
                self.status.setText("Learned from %s." % App.ActiveDocument.Label)

        def _open(self):
            path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Open Checks", "", _file_filter())
            if path:
                self.set_standard(load(path))
                self.status.setText(path)

        def _save(self):
            path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Save Checks", "standard.%s" % EXT, _file_filter())
            if not path:
                return
            if not path.lower().endswith("." + EXT):
                path += "." + EXT
            save(self.standard(), path)
            self.status.setText("Saved %s" % path)

    class CheckResults(QtWidgets.QDialog):
        """The results of a run: each check Pass/Fail, the failing objects under it."""

        def __init__(self, doc, std, source=""):
            super().__init__(_mw())
            self.setWindowTitle("Design Checker")
            self.setObjectName("SWDesignCheckerResults")
            self.resize(560, 420)
            self.doc, self.std = doc, std
            lay = QtWidgets.QVBoxLayout(self)
            self.source = QtWidgets.QLabel(source or "Standard: built-in checks")
            lay.addWidget(self.source)
            self.tree = QtWidgets.QTreeWidget()
            self.tree.setObjectName("SWDesignCheckerTree")
            self.tree.setHeaderLabels(["Check", "Severity", "Result"])
            self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
            self.tree.itemDoubleClicked.connect(self._select)
            lay.addWidget(self.tree, 1)
            self.summary = QtWidgets.QLabel("")
            lay.addWidget(self.summary)
            buttons = QtWidgets.QHBoxLayout()
            self.buttons = {}
            for text, slot in (("Correct Selected", self.correct_selected), ("Correct All", self.correct_all),
                               ("Run Again", self.refresh), ("Save Report...", self._save_report),
                               ("Open Standard...", self._open), ("Close", self.close)):
                b = QtWidgets.QPushButton(text)
                b.clicked.connect(slot)
                buttons.addWidget(b)
                self.buttons[text] = b
            lay.addLayout(buttons)
            self.tree.itemSelectionChanged.connect(self._can_correct)
            self.refresh()

        def refresh(self):
            self.tree.clear()
            self.results = sorted_results(run(self.doc, self.std), self.std)
            for key, title, passed, bad in self.results:
                item = QtWidgets.QTreeWidgetItem([title, severity(self.std, key), "Pass" if passed else "Fail"])
                try:
                    from . import style as _style
                    _dark = _style.dark()
                except Exception:
                    _dark = False
                if _dark:               # dark green / red are unreadable on the dark panel
                    from PySide import QtGui as _QtGui
                    item.setForeground(2, _QtGui.QColor("#7fe07f") if passed else _QtGui.QColor("#ff8080"))
                else:
                    item.setForeground(2, QtCore.Qt.darkGreen if passed else QtCore.Qt.red)
                item.setData(1, QtCore.Qt.UserRole, key)
                for name, why in bad:
                    child = QtWidgets.QTreeWidgetItem([why, "", ""])
                    child.setData(0, QtCore.Qt.UserRole, name)
                    item.addChild(child)
                self.tree.addTopLevelItem(item)
                item.setExpanded(not passed)
            self.tree.resizeColumnToContents(0)
            failed = sum(1 for r in self.results if not r[2])
            self.summary.setText("%d checks, %d passed, %d failed." % (len(self.results), len(self.results) - failed, failed))
            self._can_correct()

        def _fixable(self, keys):
            return [k for k in keys if k in CORRECTABLE and any(r[0] == k and not r[2] for r in self.results)]

        def _can_correct(self):
            ""
            b = getattr(self, "buttons", {})
            if not b:
                return
            picked = [(i.parent() or i).data(1, QtCore.Qt.UserRole) for i in self.tree.selectedItems()]
            b["Correct All"].setEnabled(bool(self._fixable([r[0] for r in self.results])))
            b["Correct Selected"].setEnabled(bool(self._fixable(picked)))

        def _fix(self, keys):
            keys = self._fixable(keys)
            if not keys:
                self.summary.setText(self.summary.text() + " Nothing to correct.")
                return 0
            self.doc.openTransaction("Design Checker: Correct")
            try:
                done = sum(1 for k in keys if correct(self.doc, self.std, k))
            except BaseException:
                try:
                    self.doc.abortTransaction()
                except Exception:
                    pass
                raise
            self.doc.commitTransaction()
            self.refresh()
            return done

        def correct_selected(self):
            keys = []
            for item in self.tree.selectedItems():
                top = item.parent() or item
                keys.append(top.data(1, QtCore.Qt.UserRole))
            return self._fix(keys)

        def correct_all(self):
            return self._fix([r[0] for r in self.results])

        def _save_report(self, path=None):
            if path is None:
                path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Save Report", "design-check.txt", "Text (*.txt)")
            if path:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(report(self.doc, self.std, self.results))
            return path

        def _select(self, item, _col):
            name = item.data(0, QtCore.Qt.UserRole)
            if name and self.doc.getObject(name):
                Gui.Selection.clearSelection()
                Gui.Selection.addSelection(self.doc.Name, name)

        def _open(self):
            path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Open Checks", "", _file_filter())
            if path:
                self.std = load(path)
                App.ParamGet(PARAMS).SetString("LastStandard", path)
                self.source.setText("Standard: %s" % path)
                self.refresh()

    _OPEN = {}

    def _keep(win):
        _OPEN[type(win).__name__] = win
        win.show()
        win.raise_()
        return win

    def check_active(doc=None):
        std, path = last_standard()
        return _keep(CheckResults(doc or App.ActiveDocument, std, "Standard: %s" % path if path else ""))

    def check_against(doc=None, path=None):
        return check_against_file(path, doc)

    def check_against_file(path=None, doc=None):
        if path is None:
            path, _f = QtWidgets.QFileDialog.getOpenFileName(_mw(), "Check Against Existing File", "",
                                                             "FreeCAD models (*.FCStd)")
        if not path:
            return None
        return _keep(CheckResults(doc or App.ActiveDocument, learn_from_file(path), "Standard learned from %s" % path))

    def check_folder_ask():
        ""
        folder = QtWidgets.QFileDialog.getExistingDirectory(_mw(), "Check Folder")
        if not folder:
            return None
        std, _src = last_standard()
        text, n, failed = check_folder(std, folder, recursive=True)
        path = os.path.join(folder, "Design Checker report.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            path = None
        QtWidgets.QMessageBox.information(_mw(), "Design Checker", "%d files checked, %d with failed checks.%s" % (
            n, failed, ("\nReport: %s" % path) if path else ""))
        return path

    def build_checks():
        return _keep(BuildChecks())

    def learn_wizard():
        win = BuildChecks(learn(App.ActiveDocument), "Learn Checks Wizard")
        win.status.setText("Learned from %s: review the checks, then Save." % App.ActiveDocument.Label)
        return _keep(win)

    class _Cmd:
        def __init__(self, text, tip, fn, needs_doc=True):
            self.text, self.tip, self.fn, self.needs_doc = text, tip, fn, needs_doc

        def GetResources(self):
            return {"MenuText": self.text, "ToolTip": self.tip}

        def IsActive(self):
            return App.ActiveDocument is not None or not self.needs_doc

        def Activated(self):
            self.fn()

    COMMANDS = (
        ("SWStyle_DesignCheckActive", "Check Active Document", "Checks the active document against the standard.", check_active, True),
        ("SWStyle_DesignCheckFile", "Check Against Existing File...", "Checks the active document against another model's settings.", check_against_file, True),
        ("SWStyle_DesignCheckBuild", "Build Checks", "Makes a standard of design checks.", build_checks, False),
        ("SWStyle_DesignCheckLearn", "Learn Checks Wizard", "Makes a standard from the active document.", learn_wizard, True),
        ("SWStyle_DesignCheckFolder", "Check Folder...", "Checks every model file in a folder against the standard.",
         check_folder_ask, False),
    )


def register():
    if Gui is None:
        return
    for name, text, tip, fn, needs in COMMANDS:
        try:
            if name not in Gui.listCommands():
                Gui.addCommand(name, _Cmd(text, tip, fn, needs))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s not added (%s)\n" % (text, error))
