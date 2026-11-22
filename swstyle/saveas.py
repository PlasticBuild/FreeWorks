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

import os
import re
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import paths

Qt = QtCore.Qt


PART_TYPES = (
    ("FreeCAD Part (*.FCStd)", ("FCStd",), "native"),
    ("Part (*.sldprt)", ("sldprt",), "cad"),         # saveasname-1120: no product name in the UI
    ("IGES (*.igs)", ("igs", "iges"), "iges"),
    ("STEP AP203 (*.step;*.stp)", ("step", "stp"), "step203"),
    ("STEP AP214 (*.step;*.stp)", ("step", "stp"), "step214"),
    ("STEP AP242 (*.step;*.stp)", ("step", "stp"), "step242"),
    ("Dxf (*.dxf)", ("dxf",), "partdxf"),
    ("IFC 4 (*.ifc)", ("ifc",), "ifc"),
    ("VRML (*.wrl)", ("wrl",), "vrml"),
    ("STL (*.stl)", ("stl",), "stl"),
    ("3D Manufacturing Format (*.3mf)", ("3mf",), "3mf"),
    ("Additive Manufacturing File (*.amf)", ("amf",), "mesh"),
    ("JPEG (*.jpg)", ("jpg", "jpeg"), "image"),
    ("Portable Network Graphics (*.png)", ("png",), "image"),
    ("Adobe Portable Document Format (*.pdf)", ("pdf",), "partpdf"),
    ("Tif (*.tif)", ("tif", "tiff"), "image"),
    ("Wavefront OBJ (*.obj)", ("obj",), "mesh"),
    ("glTF (*.glb;*.gltf)", ("glb", "gltf"), "gltf"),
    ("Rhino (*.3dm)", ("3dm",), "cad"),
)
ASSEMBLY_TYPES = (("FreeCAD Assembly (*.FCStd)", ("FCStd",), "native"),
                  ("Assembly (*.sldasm)", ("sldasm",), "cad")) + PART_TYPES[1:]    # saveasname-1120
DRAWING_TYPES = (
    ("FreeCAD Drawing (*.FCStd)", ("FCStd",), "native"),
    ("Dxf (*.dxf)", ("dxf",), "dxf"),
    ("Dwg (*.dwg)", ("dwg",), "dwg"),
    ("Adobe Portable Document Format (*.pdf)", ("pdf",), "pdf"),

    ("JPEG (*.jpg)", ("jpg", "jpeg"), "drawimage"),
    ("Portable Network Graphics (*.png)", ("png",), "drawimage"),
    ("Tif (*.tif)", ("tif", "tiff"), "drawimage"),
    ("Scalable Vector Graphics (*.svg)", ("svg",), "svg"),
)


OPEN_TYPES = (
    ("FreeCAD Files (*.FCStd)", ("FCStd",)),
    ("Part and Assembly (*.sldprt;*.sldasm)", ("sldprt", "sldasm")),     # saveasname-1120
    ("Part (*.sldprt)", ("sldprt",)),
    ("Assembly (*.sldasm)", ("sldasm",)),
    ("Parasolid (*.x_t;*.x_b)", ("x_t", "x_b")),
    ("ACIS (*.sat;*.sab)", ("sat", "sab")),
    ("Autodesk Inventor (*.ipt;*.iam)", ("ipt", "iam")),
    ("CATIA V5 (*.CATPart)", ("CATPart",)),
    ("Fusion 360 (*.f3d)", ("f3d",)),
    ("Rhino (*.3dm)", ("3dm",)),
    ("Creo View (*.pvz)", ("pvz",)),
    ("Dxf (*.dxf)", ("dxf",)),
    ("Dwg (*.dwg)", ("dwg",)),
    ("IGES (*.igs;*.iges)", ("igs", "iges")),
    ("STEP AP203/214/242 (*.step;*.stp)", ("step", "stp")),
    ("IFC (*.ifc)", ("ifc",)),
    ("VRML (*.wrl)", ("wrl",)),
    ("STL (*.stl)", ("stl",)),
    ("Mesh Files (*.stl;*.obj;*.off;*.ply;*.3mf;*.amf)", ("stl", "obj", "off", "ply", "3mf", "amf")),
    ("3D Manufacturing Format (*.3mf)", ("3mf",)),
    ("BREP (*.brep;*.brp)", ("brep", "brp")),
)

STL_BINARY = "STLBinary"
STL_RESOLUTION = "STLResolution"      # Coarse, Fine, Custom
STL_DEVIATION = "STLDeviation"        # mm
STL_ANGLE = "STLAngle"                # degrees
STL_UNIT = "STLUnit"
STL_INFO = "STLShowInfo"              # Show STL info before file saving
STL_PREVIEW = "STLPreview"            # Preview before saving file
STL_KEEP_SPACE = "STLKeepSpace"       # Do not translate STL output data to positive space
STL_SINGLE = "STLSingleFile"          # Save all components of an assembly in a single file
STL_UNITS = (("Millimeters", 1.0), ("Centimeters", 0.1), ("Meters", 0.001), ("Inches", 1 / 25.4), ("Feet", 1 / 304.8),
             ("Microns", 1000.0))
RESOLUTIONS = {"Coarse": (0.5, 30.0), "Fine": (0.05, 10.0)}


# Save As > Options...). Each is read by its writer below.
VRML_UNIT = "VRMLUnit"                # Output units
VRML_SINGLE = "VRMLSingleFile"        # Save all components of an assembly in one file
PDF_COLOR = "PDFInColor"              # Export PDF in color (off: grayscale)
PDF_HEADER = "PDFHeader"              # Print header: the document's name and the date
PDF_PAPER = "PDFPaper"
IMG_TYPE = "ImageType"                # RGB, Grayscale, Black and White
IMG_OUTPUT = "ImageOutput"            # Screen capture (the view's own size), Print capture (paper size at DPI)
IMG_DPI = "ImageDPI"
IMG_PAPER = "ImagePaper"
PAPERS = (("A4", 297.0, 210.0), ("A3", 420.0, 297.0), ("A2", 594.0, 420.0), ("A1", 841.0, 594.0),
          ("A0", 1189.0, 841.0), ("Letter", 279.4, 215.9), ("Legal", 355.6, 215.9), ("Tabloid", 431.8, 279.4))
IMAGE_TYPES = ("RGB", "Grayscale", "Black and White")
IMAGE_OUTPUTS = ("Screen capture", "Print capture")
VRML_UNITS = tuple(u for u in STL_UNITS if u[0] != "Microns")


def _have_dwg():
    try:
        import importDWG
        for name in ("get_libredwg_converter", "get_oda_converter", "get_qcad_converter", "getTeighaConvertor",
                     "getTeighaConverter"):
            fn = getattr(importDWG, name, None)
            if fn is not None:
                try:
                    if fn():
                        return True
                except Exception as _fw_err:
                    _fw_log("saveas.py:115", _fw_err)
    except Exception as _fw_err:
        _fw_log("saveas.py:117", _fw_err)
    return False


def _have_ifc():
    try:
        import ifcopenshell  # noqa: F401
        return True
    except Exception:
        return False


def _have_swfiles():
    ""
    try:
        import importlib.util
        return importlib.util.find_spec("swfiles") is not None
    except Exception:
        return False


def _have_cadmpeg():
    try:
        from swfiles import cadconv
        return bool(cadconv.executable())
    except Exception:
        return False


def _can_write(ext):
    ""
    if not _have_swfiles():
        return False
    if ext in ("sldprt", "sldasm"):
        try:
            from swfiles import swapp
            return swapp.solidworks_installed()
        except Exception as _fw_err:
            _fw_log("saveas.py:156", _fw_err)
            return False
    return _have_cadmpeg()


# opened by swfiles without anything else; the other CAD types go through cadmpeg
SW_OWN = {"sldprt", "sldasm", "x_t", "x_b"}
CADMPEG = {"sat", "sab", "ipt", "iam", "catpart", "f3d", "3dm", "pvz"}


def kind_of(doc):
    """'Drawing', 'Assembly' or 'Part' for doc."""
    if doc is None:
        return "Part"
    types = {o.TypeId for o in doc.Objects}
    if "TechDraw::DrawPage" in types and not types & {"PartDesign::Body", "Assembly::AssemblyObject"}:
        return "Drawing"
    if "Assembly::AssemblyObject" in types:
        return "Assembly"
    return "Part"



# FreeCAD document saved into the templates folder (newdoc.templates_folder, File > New > Advanced).
TEMPLATE_TYPES = {"Part": ("Part Templates (*.FCStd)", ("FCStd",), "parttemplate"),
                  "Assembly": ("Assembly Templates (*.FCStd)", ("FCStd",), "asmtemplate"),
                  "Drawing": ("Drawing Templates (*.FCStd)", ("FCStd",), "drawtemplate")}
TEMPLATE_WRITERS = {t[2] for t in TEMPLATE_TYPES.values()}


def templates_dir():
    from . import newdoc
    out = os.path.join(newdoc.templates_folder(), "Templates")
    try:
        os.makedirs(out, exist_ok=True)
    except OSError as _fw_err:
        _fw_log("saveas.py:190", _fw_err)
    return out


def save_template(doc, path):
    ""
    if not path.lower().endswith(".fcstd"):
        path += ".FCStd"
    doc.saveAs(path)
    try:
        Gui.getDocument(doc.Name).Modified = False
    except Exception as _fw_err:
        _fw_log("saveas.py:202", _fw_err)
    return path


def save_types(doc):
    kind = kind_of(doc)
    types = {"Part": PART_TYPES, "Assembly": ASSEMBLY_TYPES, "Drawing": DRAWING_TYPES}[kind]
    out = []
    for t in types:
        if t[2] == "dwg" and not _have_dwg():
            continue
        if t[2] == "ifc" and not _have_ifc():
            continue
        if t[2] in ("step203", "step242") and not _have_ap203():
            continue
        if t[2] == "cad" and not _can_write(t[1][0]):
            continue
        out.append(t)
    t = TEMPLATE_TYPES.get(kind)
    if t is not None and t not in out:
        out.insert(1, t)
    return tuple(out)


def open_types():
    out = []
    for label, exts in OPEN_TYPES:
        if "dwg" in exts and not _have_dwg():
            continue
        if "ifc" in exts and not _have_ifc():
            continue
        low = {e.lower() for e in exts}
        if low & (SW_OWN | CADMPEG) and not _have_swfiles():
            continue
        if low <= CADMPEG and not _have_cadmpeg():
            continue
        out.append((label, exts))
    return tuple(out)


def _filter(label):
    return label


# ---------------------------------------------------------------- writers
def export_option(text, default):
    """Options > System Options > Export (kept by optionspages)."""
    try:
        from . import optionspages
        return bool(optionspages.stored("Export", text, default))
    except Exception:
        return default


def _solids(doc, writer=None):
    ""



    tops = [o for o in doc.Objects if o.TypeId == "Assembly::AssemblyObject"]
    if tops:
        out = tops[:1]
        if writer not in ("step203", "step214", "step242", "partpdf") and export_option("Flatten assembly hierarchy", True):
            # x123: every instance where it sits (temporary copies, removed after the export); the dxf panel keeps
            # its objects while it is open, so it still gets the bodies themselves
            flat = (_flatten_placed(doc, tops[0]) if writer not in (None, "partdxf") else None) or _flatten(tops[0])
            if flat:
                out = flat
    else:
        bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
        if bodies:
            out = [b for b in bodies if b.Visibility] or bodies
        else:
            # sv107: a parent counts in this document only (an assembly linking the part is not one)
            out = [o for o in doc.Objects if o.isDerivedFrom("Part::Feature") and not _parents(o) and o.Visibility
                   and not _is_curve_feature(o)]
            # parts grouped in App::Part containers (an imported STEP assembly): the top containers,
            # so a STEP export keeps the structure
            out += [o for o in doc.Objects if o.TypeId == "App::Part" and not _parents(o) and o.Visibility]
    if export_option("Export 3D Curve features", True):
        out += [o for o in doc.Objects if o not in out and _is_curve_feature(o)]
    if export_option("Export sketch entities", False):
        out += [o for o in doc.Objects if o not in out and o.isDerivedFrom("Sketcher::SketchObject") and o.Visibility]
    return out


def _parents(o):
    """The objects of o's own document that use o (InList also holds other documents' links to it)."""
    return [p for p in o.InList if p.Document is o.Document]


def _is_curve_feature(o):
    """A 3D curve feature: a visible Part feature with edges and no faces (helix, composite curve, projected curve...)."""
    if not o.isDerivedFrom("Part::Feature") or o.isDerivedFrom("Sketcher::SketchObject") or not o.Visibility:
        return False
    if o.TypeId == "PartDesign::Body" or any(p.TypeId == "PartDesign::Body" for p in o.InList):
        return False
    try:
        sh = o.Shape
        return bool(sh.Edges) and not sh.Faces
    except Exception:
        return False


def _flatten(asm):
    """Every part body under the assembly (links followed), for a flat export."""
    out, seen = [], set()

    def walk(o, depth=0):
        if depth > 12 or o is None or o.Name in seen:
            return
        seen.add(o.Name)
        if o.TypeId == "PartDesign::Body" or (o.isDerivedFrom("Part::Feature") and not o.isDerivedFrom("App::Link")
                                               and o.TypeId not in ("Assembly::AssemblyObject",) and not o.OutList):
            out.append(o)
            return
        kids = list(getattr(o, "OutList", []) or [])
        linked = getattr(o, "LinkedObject", None)
        if linked is not None:
            kids.append(linked)
        for k in kids:
            walk(k, depth + 1)
    walk(asm)
    return out


FLAT = "FWFlat"           # x123: name of the temporary placed copies of a flat assembly export
_FLAT_STATE = {}
_FLAT_LABEL = {}         # temporary copy's name -> the instance's own name (its Label may get a 001 suffix)


def _comp_label(o):
    return _FLAT_LABEL.get(o.Name, o.Label)


def _comp_file(o):
    """A component's part of a file-component.ext name: 'MmPart (1)' -> MmPart_1."""
    return "".join(ch if ch.isalnum() else "_" for ch in _comp_label(o)).strip("_") or "Component"


def _flatten_placed(doc, asm):
    """x123: a flat export of an assembly wrote each part once, where the part itself sits: a part used twice came
    out once (IGES / STL / 3MF / OBJ / AMF / VRML). Now one temporary copy per instance, at its place in the
    assembly (sub-assemblies followed), named as the instance. _drop_flat removes them."""
    import Part
    out = []

    def leaf(o):
        return o.TypeId == "PartDesign::Body" or (o.isDerivedFrom("Part::Feature") and not o.isDerivedFrom("App::Link")
                                                  and o.TypeId != "Assembly::AssemblyObject")

    def walk(o, pl, label, depth):
        if o is None or depth > 12:
            return
        linked = getattr(o, "LinkedObject", None) if o.isDerivedFrom("App::Link") else None
        if linked is not None:
            try:
                if getattr(o, "ViewObject", None) is not None and not o.ViewObject.Visibility:
                    return
            except Exception as _fw_err:
                _fw_log("saveas.py:flat-vis", _fw_err)
            target = linked[0] if isinstance(linked, tuple) else linked
            walk(target, pl.multiply(o.Placement), o.Label, depth + 1)
            return
        if leaf(o):
            try:
                sh = Part.getShape(o)
                if sh.isNull():
                    return
                sh = sh.copy()
                sh.Placement = pl.multiply(sh.Placement)
                out.append((label or o.Label, sh, o))
            except Exception as _fw_err:
                _fw_log("saveas.py:flat-shape", _fw_err)
            return
        if o.TypeId in ("Assembly::AssemblyObject", "App::Part") or o.isDerivedFrom("App::Part"):
            inner = pl.multiply(o.Placement) if depth else pl      # the top assembly's own place is the origin
            for k in list(getattr(o, "Group", []) or []):
                walk(k, inner, None, depth + 1)

    walk(asm, App.Placement(), None, 0)
    if len(out) < 2:
        return None             # nothing gained over the bodies themselves
    try:
        gdoc = Gui.getDocument(doc.Name)
        _FLAT_STATE[doc.Name] = gdoc.Modified if gdoc is not None else None
    except Exception:
        _FLAT_STATE[doc.Name] = None
    temps = []
    for label, sh, src in out:
        t = doc.addObject("Part::Feature", FLAT)
        t.Shape = sh
        t.Label = label
        _FLAT_LABEL[t.Name] = label
        try:
            if t.ViewObject is not None and src.ViewObject is not None:
                t.ViewObject.ShapeAppearance = src.ViewObject.ShapeAppearance
        except Exception as _fw_err:
            _fw_log("saveas.py:flat-colour", _fw_err)
        temps.append(t)
    return temps


def _drop_flat(doc):
    """x123: removes the temporary placed copies; the document is left as changed or unchanged as it was."""
    names = [o.Name for o in doc.Objects if o.Name.startswith(FLAT) and o.TypeId == "Part::Feature"]
    for n in names:
        _FLAT_LABEL.pop(n, None)
        try:
            doc.removeObject(n)
        except Exception as _fw_err:
            _fw_log("saveas.py:drop-flat", _fw_err)
    was = _FLAT_STATE.pop(doc.Name, None)
    if names and was is False:
        try:
            Gui.getDocument(doc.Name).Modified = False
        except Exception as _fw_err:
            _fw_log("saveas.py:drop-flat-modified", _fw_err)


def _split_periodic(objs, doc):
    ""

    import Part
    temps = []
    for o in objs:
        if o.TypeId in ("App::Part", "Assembly::AssemblyObject") or o.isDerivedFrom("App::Link"):
            continue        # a container: one split copy of it would flatten its structure in the file
        try:
            sh = o.Shape
            cutters = []
            for face in sh.Faces:
                surf = face.Surface
                if getattr(surf, "isUPeriodic", lambda: False)():
                    u0, u1, v0, v1 = face.ParameterRange
                    cutters.append(Part.Edge(surf.uIso((u0 + u1) / 2.0).trim(v0, v1)))
                elif getattr(surf, "isVPeriodic", lambda: False)():
                    u0, u1, v0, v1 = face.ParameterRange
                    cutters.append(Part.Edge(surf.vIso((v0 + v1) / 2.0).trim(u0, u1)))
            if not cutters:
                continue
            res = sh.generalFuse(cutters)[0]
            solids = res.Solids or res.Shells or res.Faces
            new = Part.makeCompound(solids) if len(solids) != 1 else solids[0]
            tmp = doc.addObject("Part::Feature", "ExportSplit")
            tmp.Shape = new
            tmp.Label = o.Label
            temps.append((o, tmp))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: split periodic faces on %s: %s\n" % (o.Label, error))
    return temps


def _with_precision(fn):
    """Use high trim curve accuracy: OpenCASCADE's write.precision.mode 1 (max) for one export."""
    calls = _schema_calls() if export_option("Use high trim curve accuracy", True) else None
    old = None
    if calls is not None:
        put, get = calls
        old = get(b"write.precision.mode")
        put(b"write.precision.mode", b"1")
    try:
        return fn()
    finally:
        if calls is not None and old:
            calls[0](b"write.precision.mode", old)


_SCHEMA = []


def _schema_calls():
    """OpenCASCADE's Interface_Static SetCVal and CVal, found in the TKXSBase library FreeCAD has
    loaded. FreeCAD reads its STEP scheme setting only when it starts, so Save As sets the scheme
    for one export here. None when the library or the calls are not found."""
    if _SCHEMA:
        return _SCHEMA[0]
    import ctypes
    found = None
    names = ("TKXSBase.dll", "TKXSBase", "libTKXSBase.so.7.8", "libTKXSBase.so.7.9", "libTKXSBase.so.7.7",
             "libTKXSBase.so", "libTKXSBase.dylib")
    setters = ("_ZN16Interface_Static7SetCValEPKcS1_", "?SetCVal@Interface_Static@@SA_NQEBD0@Z",
               "?SetCVal@Interface_Static@@SA_NPEBD0@Z")
    getters = ("_ZN16Interface_Static4CValEPKc", "?CVal@Interface_Static@@SAPEBDQEBD@Z",
               "?CVal@Interface_Static@@SAPEBDPEBD@Z")
    for name in names:
        try:
            lib = ctypes.CDLL(name)
        except OSError:
            continue
        put = next((getattr(lib, n) for n in setters if hasattr(lib, n)), None)
        get = next((getattr(lib, n) for n in getters if hasattr(lib, n)), None)
        if put is not None and get is not None:
            put.restype, put.argtypes = ctypes.c_bool, [ctypes.c_char_p, ctypes.c_char_p]
            get.restype, get.argtypes = ctypes.c_char_p, [ctypes.c_char_p]
            found = (put, get)
            break
    _SCHEMA.append(found)
    return found


def _have_ap203():
    return _schema_calls() is not None


def _step(objs, path, scheme):
    # exportopts-1119: Export face/edge properties off writes the shapes without their colours (Import.export)
    plain = not export_option("Export face/edge properties", True)
    calls = _schema_calls()          # stepopts94: AP214 set too, the kept STEP type may be another
    old = None
    if calls is not None:
        put, get = calls
        old = get(b"write.step.schema")
        put(b"write.step.schema", scheme.encode())
    # stepopts94: FreeCAD's own writer (ImportGui) takes the scheme from its setting each time
    kept = [App.ParamGet(k).GetString("Scheme", "") for k in STEP_SCHEME_KEYS]
    for k in STEP_SCHEME_KEYS:
        App.ParamGet(k).SetString("Scheme", scheme)
    try:
        try:
            if plain:
                raise ImportError("face/edge properties off")
            import ImportGui
            ImportGui.export(objs, path)
        except Exception:
            import Import
            Import.export(objs, path)
    finally:
        for k, v in zip(STEP_SCHEME_KEYS, kept):
            if v:
                App.ParamGet(k).SetString("Scheme", v)
            else:
                App.ParamGet(k).RemString("Scheme")
        if calls is not None and old:
            calls[0](b"write.step.schema", old)


def _part_dxf(doc, objs, path):
    ""

    import Part
    shape = None
    for sel in Gui.Selection.getSelectionEx(doc.Name):
        for sub in sel.SubObjects:
            if isinstance(sub, Part.Face) and sub.Surface.__class__.__name__ == "Plane":
                n = sub.normalAt(0, 0)
                rot = App.Rotation(n, App.Vector(0, 0, 1))
                shape = sub.copy()
                shape.Placement = App.Placement(App.Vector(), rot).multiply(shape.Placement)
                shape = Part.Compound(shape.Edges)
                shape.translate(App.Vector(0, 0, -shape.BoundBox.ZMin))
                break
        if shape is not None:
            break
    if shape is None:
        import TechDraw
        whole = Part.makeCompound([o.Shape for o in objs])
        got = TechDraw.projectEx(whole, App.Vector(0, 0, 1))
        shape = Part.makeCompound([e for e in (got[0], got[1]) if e is not None and not e.isNull()])
    from . import drawdxf
    units, size = drawdxf.doc_units(doc)        # units105: written in the part's own units
    if units != 4:
        shape = shape.copy()
        shape.scale(1.0 / size)
    tmp = doc.addObject("Part::Feature", "DxfExport")
    tmp.Shape = shape
    try:
        import importDXF
        importDXF.export([tmp], path)
    finally:
        doc.removeObject(tmp.Name)
    if units != 4:
        _set_insunits(path, units)


def _set_insunits(path, units):
    """The $INSUNITS of a DXF FreeCAD wrote (it writes millimetres, 4) changed to the document's unit."""
    try:
        with open(path, "r", errors="surrogateescape", newline="") as fh:
            text = fh.read()
        new = re.sub(r"(\$INSUNITS\r?\n\s*70\r?\n\s*)4(\r?\n)", r"\g<1>%d\2" % units, text, count=1)
        if new != text:
            with open(path, "w", errors="surrogateescape", newline="") as fh:
                fh.write(new)
    except Exception as _fw_err:
        _fw_log("saveas.py:_set_insunits", _fw_err)


def _part_dxf_panel(doc, path):
    ""

    objs = _solids(doc, "partdxf")
    if not objs:
        return False
    from . import smdxf
    return smdxf.start_part(doc, path, objs) is not None


STEP_WRITERS = {"step203": "AP203", "step214": "AP214IS", "step242": "AP242DIS"}
# units105: OpenCASCADE's names of the document length units (millimetres need nothing set)
OCC_UNITS = {"in": b"INCH", "ft": b"FT", "cm": b"CM", "m": b"M"}


def export_unit(doc):
    ""

    try:
        from . import unitspage
        sym, size = unitspage.length_unit(doc)
    except Exception as _fw_err:
        _fw_log("saveas.py:export_unit", _fw_err)
        return None
    name = OCC_UNITS.get(sym)
    return (name, size) if name and abs(size - 1.0) > 1e-12 else None


def _with_static(key, value, fn):
    """fn() with OpenCASCADE's setting key at value for this one export, the old value put back after."""
    calls = _schema_calls() if value else None
    if calls is None:
        return fn()
    put, get = calls
    old = get(key)
    put(key, value)
    try:
        return fn()
    finally:
        put(key, old or (b"MM" if key.endswith(b".unit") else value))


class _UnitLinkProxy:
    """The temporary link of a unit export carries its object's own label (it is gone after the export)."""
    def __init__(self, obj=None):
        if obj is not None:
            obj.Proxy = self

    def allowDuplicateLabel(self, obj):
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _part_product_name(doc, objs):
    ""

    if len(objs) != 1 or any(o.TypeId == "Assembly::AssemblyObject" for o in doc.Objects):
        return None
    name = os.path.splitext(os.path.basename(getattr(doc, "FileName", "") or ""))[0] or doc.Label
    return name or None


def _name_products(doc):
    ""


    done = []
    try:
        from . import asmcore as ac
    except Exception as _fw_err:
        _fw_log("saveas.py:_name_products", _fw_err)
        return done
    seen = set()
    for asm in [o for o in doc.Objects if o.TypeId == "Assembly::AssemblyObject"]:
        try:
            comps = ac.components(asm)
        except Exception as _fw_err:
            _fw_log("saveas.py:_name_products comps", _fw_err)
            continue
        for c in comps:
            target = c.getLinkedObject(True) if hasattr(c, "getLinkedObject") else None
            if target is None or target.TypeId == "Assembly::AssemblyObject" or id(target) in seen:
                continue
            seen.add(id(target))
            if target.Document is doc:
                name = target.Label.split("^")[0]         # a virtual part: Plate^Asm
            else:
                name = os.path.splitext(os.path.basename(target.Document.FileName or ""))[0] or target.Document.Label
            if name and target.Label != name:
                try:
                    was = Gui.getDocument(target.Document.Name).Modified
                except Exception:
                    was = True
                done.append((target, target.Label, was))
                try:
                    target.Label = name
                except Exception as _fw_err:
                    _fw_log("saveas.py:_name_products label", _fw_err)
                    done.pop()
    return done


def _unname_products(done):
    clean = set()
    for obj, label, was in reversed(done):
        try:
            obj.Label = label
            if not was:
                clean.add(obj.Document.Name)
        except Exception as _fw_err:
            _fw_log("saveas.py:_unname_products", _fw_err)

    def unchanged():
        # the label put back is no change to the part: it stays unmodified (also after the links hear of it)
        for n in clean:
            try:
                if n in App.listDocuments() and Gui.getDocument(n).Modified:
                    Gui.getDocument(n).Modified = False
            except Exception as _fw_err:
                _fw_log("saveas.py:_unname_products clean", _fw_err)
    unchanged()
    if clean:
        QtCore.QTimer.singleShot(400, unchanged)
        QtCore.QTimer.singleShot(1500, unchanged)


def _unit_links(doc, objs, size, labels=None):
    """Temporary links to objs scaled 1/size: OpenCASCADE 7.8 labels a STEP file with write.step.unit but
    keeps the millimetre numbers, so the shapes are handed over already in the document's units.
    The links keep the objects' names (or labels), colours and assembly structure, and are removed after
    the export."""
    links = []
    try:
        for i, o in enumerate(objs):
            link = doc.addObject("App::LinkPython", "FwUnitExport")
            _UnitLinkProxy(link)
            link.LinkedObject = o
            if abs(size - 1.0) > 1e-12:
                link.ScaleVector = App.Vector(1, 1, 1) * (1.0 / size)
            link.Label = labels[i] if labels and i < len(labels) else o.Label
            try:
                link.ViewObject.Visibility = False
            except Exception:
                pass
            links.append(link)
        doc.recompute(links)
    except Exception as _fw_err:
        _fw_log("saveas.py:_unit_links", _fw_err)
        _remove_links(doc, links)
        raise
    return links


def _remove_links(doc, links):
    for link in links:
        try:
            doc.removeObject(link.Name)
        except Exception as _fw_err:
            _fw_log("saveas.py:_remove_links", _fw_err)


def _solid_export(doc, objs, path, writer):
    ""

    temps = _split_periodic(objs, doc) if export_option("Split periodic faces", True) else []
    swap = dict((o.Name, t) for o, t in temps)
    objs = [swap.get(o.Name, o) for o in objs]
    try:
        groups = [(path, objs)]
        if len(objs) > 1 and any(o.TypeId == "Assembly::AssemblyObject" for o in doc.Objects) \
                and not export_option("Save all components of an assembly in one file", True):
            stem, ext = os.path.splitext(path)
            groups = [("%s-%s%s" % (stem, _comp_file(o), ext), [o]) for o in objs]

        unit = export_unit(doc)
        named = _part_product_name(doc, objs)
        renamed = _name_products(doc) if writer in STEP_WRITERS else []

        def go():
            for p, group in groups:
                if writer in STEP_WRITERS:
                    labels = [named] if named and len(group) == 1 else None
                    links = _unit_links(doc, group, unit[1] if unit else 1.0, labels) if unit or labels else []
                    try:
                        _with_static(b"write.step.unit", unit and unit[0],
                                     lambda: _step(links or group, p, STEP_WRITERS[writer]))
                    finally:
                        _remove_links(doc, links)
                elif writer == "iges" and iges_wireframe():
                    _with_static(b"write.iges.unit", unit and unit[0], lambda: _iges_wireframe(group, p))
                else:
                    import Import
                    # imp144: Output as (Manifold Solid 186 / Trimmed Surface 144): FreeCAD reads its own IGES setting
                    # only when it starts, so the choice is set on OpenCASCADE for this export
                    _with_static(b"write.iges.brep.mode", iges_brep_mode(),
                                 lambda: _with_static(b"write.iges.unit", unit and unit[0], lambda: Import.export(group, p)))
        try:
            _with_precision(go)
        finally:
            _unname_products(renamed)
    finally:
        for _o, t in temps:
            try:
                doc.removeObject(t.Name)
            except Exception as _fw_err:
                _fw_log("saveas.py:487", _fw_err)


def iges_brep_mode():
    """System Options > Export > IGES > Output as: b"BRep" (Manifold Solid, type 186) or b"Faces" (Trimmed Surface, 144)."""
    mode = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Part/IGES").GetInt("BrepMode", 0)
    return b"BRep" if mode == 1 else b"Faces"


def iges_wireframe():
    """System Options > Export > IGES > Output as: Wireframe (type 110)."""
    return App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks").GetBool("IGESWireframe", False)


def _iges_wireframe(objs, path):
    """IGES as wireframe: the model's edges only (lines and curves, no surfaces or solids)."""
    import Part
    edges = []
    for o in objs:
        shape = getattr(o, "Shape", None)
        if shape is not None and not shape.isNull():
            edges.extend(e.copy() for e in shape.Edges)
    if not edges:
        raise RuntimeError("Nothing to write as IGES wireframe")
    Part.makeCompound(edges).exportIges(path)


def stl_settings():
    p = paths.params()
    res = p.GetString(STL_RESOLUTION, "Fine")
    if res in RESOLUTIONS:
        dev, ang = RESOLUTIONS[res]
    else:
        dev, ang = p.GetFloat(STL_DEVIATION, 0.05), p.GetFloat(STL_ANGLE, 10.0)
    return p.GetBool(STL_BINARY, True), res, dev, ang


def stl_flags():
    p = paths.params()
    return {"unit": p.GetString(STL_UNIT, "Millimeters"), "info": p.GetBool(STL_INFO, False),
            "preview": p.GetBool(STL_PREVIEW, False), "keep": p.GetBool(STL_KEEP_SPACE, False),
            "single": p.GetBool(STL_SINGLE, False)}


def _stl_mesh(objs, dev, ang):
    import Mesh
    import MeshPart
    mesh = Mesh.Mesh()
    for o in objs:
        shape = o.Shape.copy(False)
        shape.Placement = o.getGlobalPlacement() if hasattr(o, "getGlobalPlacement") else shape.Placement
        mesh.addMesh(MeshPart.meshFromShape(Shape=shape, LinearDeflection=dev, AngularDeflection=ang * 3.14159265 / 180,
                                            Relative=False))
    return mesh


def _stl_info(doc, groups, binary):
    ""

    flags = stl_flags()
    shown = []
    try:
        if flags["preview"] and doc is not None:
            for _p, mesh in groups:
                o = doc.addObject("Mesh::Feature", "STLPreview")
                o.Mesh = mesh
                if o.ViewObject is not None:
                    o.ViewObject.DisplayMode = "Flat Lines"
                shown.append(o.Name)
            Gui.updateGui()
        lines = []
        for path, mesh in groups:
            size = 84 + 50 * mesh.CountFacets if binary else None
            lines.append("File: %s\nFile format: %s\nNumber of triangles: %d%s" % (
                path, "Binary" if binary else "ASCII", mesh.CountFacets,
                "\nFile size: %d (Bytes)" % size if size is not None else ""))
        box = QtWidgets.QMessageBox(Gui.getMainWindow())
        box.setObjectName("FW_StlInfo")
        box.setWindowTitle("Save As")
        box.setIcon(QtWidgets.QMessageBox.Information)
        box.setText("\n\n".join(lines) + "\n\nDo you want to save the file?")
        box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        box.setDefaultButton(QtWidgets.QMessageBox.Yes)
        return box.exec_() == QtWidgets.QMessageBox.Yes
    finally:
        for name in shown:
            try:
                doc.removeObject(name)
            except Exception as _fw_err:
                _fw_log("saveas.py:570", _fw_err)


def _stl(objs, path, doc=None):
    ""


    binary, _res, dev, ang = stl_settings()
    flags = stl_flags()
    scale = dict(STL_UNITS).get(flags["unit"], 1.0)
    parts = [(path, objs)]
    if doc is not None and len(objs) > 1 and not flags["single"] and \
            any(o.TypeId == "Assembly::AssemblyObject" for o in doc.Objects):
        stem, ext = os.path.splitext(path)
        parts = [("%s-%s%s" % (stem, _comp_file(o), ext), [o]) for o in objs]
    groups = []
    for p, group in parts:
        mesh = _stl_mesh(group, dev, ang)
        if not flags["keep"] and mesh.CountPoints:
            box = mesh.BoundBox
            mesh.translate(-box.XMin, -box.YMin, -box.ZMin)
        if abs(scale - 1.0) > 1e-12:
            m = App.Matrix()
            m.scale(scale, scale, scale)
            mesh.transform(m)
        groups.append((p, mesh))
    if flags["info"] and App.GuiUp:
        if not _stl_info(doc, groups, binary):
            return False
    for p, mesh in groups:
        mesh.write(p, "STL" if binary else "AST")
    return True


TMF_UNIT, TMF_MATERIALS, TMF_APPEARANCES = "3MFUnit", "3MFIncludeMaterials", "3MFIncludeAppearances"
TMF_UNITS = (("Millimeters", "millimeter", 1.0), ("Centimeters", "centimeter", 10.0), ("Meters", "meter", 1000.0),
             ("Microns", "micron", 0.001), ("Inches", "inch", 25.4), ("Feet", "foot", 304.8))


def tmf_settings():
    p = paths.params()
    return p.GetString(TMF_UNIT, "Millimeters"), p.GetBool(TMF_MATERIALS, True), p.GetBool(TMF_APPEARANCES, True)


def _colour_of(o):
    try:
        vo = o.ViewObject
        app = getattr(vo, "ShapeAppearance", None)
        c = app[0].DiffuseColor if app else vo.ShapeColor
        return "#%02X%02X%02X" % tuple(int(round(max(0.0, min(1.0, x)) * 255)) for x in c[:3])
    except Exception:
        return "#B4B4B4"


def _3mf(doc, objs, path):
    ""

    import zipfile
    import MeshPart
    from xml.sax.saxutils import quoteattr
    unit, with_mat, with_app = tmf_settings()
    _label, unit_name, scale = next((u for u in TMF_UNITS if u[0] == unit), TMF_UNITS[0])
    _binary, _res, dev, ang = stl_settings()
    try:
        from . import material as mat
        mat_name = mat.current(doc)[1] or "Material"
    except Exception:
        mat_name = "Material"
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<model unit="%s" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">' % unit_name,
           ' <metadata name="Application">FreeCAD</metadata>', ' <resources>']
    materials = with_mat or with_app
    if materials:
        out.append('  <basematerials id="1">')
        for o in objs:
            out.append('   <base name=%s displaycolor="%s" />' % (quoteattr(mat_name if with_mat else _comp_label(o)),
                                                                  _colour_of(o) if with_app else "#B4B4B4"))
        out.append('  </basematerials>')
    ids = []
    for i, o in enumerate(objs):
        shape = o.Shape.copy(False)
        shape.Placement = o.getGlobalPlacement() if hasattr(o, "getGlobalPlacement") else shape.Placement
        mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=dev, AngularDeflection=ang * 3.14159265 / 180,
                                      Relative=False)
        pts, tris = mesh.Topology
        oid = i + 2
        ids.append(oid)
        out.append('  <object id="%d" name=%s type="model"%s>' % (oid, quoteattr(_comp_label(o)),
                                                                ' pid="1" pindex="%d"' % i if materials else ""))
        out.append('   <mesh>')
        out.append('    <vertices>')
        out += ['     <vertex x="%.6g" y="%.6g" z="%.6g" />' % (p.x / scale, p.y / scale, p.z / scale) for p in pts]
        out.append('    </vertices>')
        out.append('    <triangles>')
        out += ['     <triangle v1="%d" v2="%d" v3="%d" />' % t for t in tris]
        out.append('    </triangles>')
        out.append('   </mesh>')
        out.append('  </object>')
    out.append(' </resources>')
    out.append(' <build>')
    out += ['  <item objectid="%d" />' % oid for oid in ids]
    out.append(' </build>')
    out.append('</model>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" />'
            '</Relationships>')
    types = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", "\n".join(out))


def _is_asm(doc):
    return doc is not None and any(o.TypeId == "Assembly::AssemblyObject" for o in doc.Objects)


def _per_component(doc, objs, path, single):
    ""

    if single or len(objs) < 2 or not _is_asm(doc):
        return [(path, objs)]
    stem, ext = os.path.splitext(path)
    return [("%s-%s%s" % (stem, _comp_file(o), ext), [o]) for o in objs]


def _mesh_file(objs, path):
    ""
    _binary, _res, dev, ang = stl_settings()
    mesh = _stl_mesh(objs, dev, ang)
    try:
        mesh.write(path)
        return
    except Exception as _fw_err:           # AMF: FreeCAD writes it from a mesh object only
        _fw_log("saveas.py:mesh_write", _fw_err)
    import Mesh
    scratch = App.newDocument("FwMeshExport", hidden=True, temp=True)
    try:
        f = scratch.addObject("Mesh::Feature", "Mesh")
        f.Mesh = mesh
        Mesh.export([f], path)
    finally:
        App.closeDocument(scratch.Name)


def _vrml(doc, objs, path):
    ""

    import tempfile
    p = paths.params()
    unit = p.GetString(VRML_UNIT, "Millimeters")
    scale = dict(VRML_UNITS).get(unit, 1.0)
    for out, group in _per_component(doc, objs, path, p.GetBool(VRML_SINGLE, True)):
        tmp = os.path.join(tempfile.mkdtemp(prefix="fw-vrml-"), "model.wrl")
        Gui.export(group, tmp)
        with open(tmp, encoding="utf-8", errors="replace") as f:
            text = f.read()
        if abs(scale - 1.0) > 1e-12:
            head, _nl, body = text.partition("\n")
            text = "%s\n# units: %s\nTransform {\n  scale %.9g %.9g %.9g\n  children [\n%s\n  ]\n}\n" % (
                head, unit.lower(), scale, scale, scale, body)
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        try:
            os.remove(tmp)
        except OSError as _fw_err:
            _fw_log("saveas.py:vrml_tmp", _fw_err)
    return path


def paper_mm(name):
    """(width, height) in mm, landscape, of a paper size in PAPERS (A4 when unknown)."""
    return next(((w, h) for n, w, h in PAPERS if n == name), (297.0, 210.0))


def image_settings():
    p = paths.params()
    return {"type": p.GetString(IMG_TYPE, "RGB"), "output": p.GetString(IMG_OUTPUT, "Screen capture"),
            "dpi": p.GetInt(IMG_DPI, 300), "paper": p.GetString(IMG_PAPER, "A4")}


def image_size(doc=None):
    ""

    st = image_settings()
    if st["output"] == "Print capture":
        w, h = paper_mm(st["paper"])
        k = max(50, min(1200, st["dpi"])) / 25.4
        return min(14000, int(round(w * k))), min(14000, int(round(h * k)))
    try:
        view = Gui.getDocument((doc or App.ActiveDocument).Name).ActiveView
        size = view.getSize()
        # open126: a document whose window is behind another one has a 400 x 300 view; the graphics area is

        front = Gui.ActiveDocument
        if doc is not None and front is not None and front.Document is not doc and hasattr(front.ActiveView, "getSize"):
            size = front.ActiveView.getSize()
        if size[0] > 10 and size[1] > 10:
            return int(size[0]), int(size[1])
    except Exception as _fw_err:
        _fw_log("saveas.py:image_size", _fw_err)
    return 1920, 1080


def _toned(image, kind):
    from PySide import QtGui
    if kind == "Grayscale":
        return image.convertToFormat(QtGui.QImage.Format_Grayscale8)
    if kind == "Black and White":
        return image.convertToFormat(QtGui.QImage.Format_Mono, QtCore.Qt.ThresholdDither)
    return image


def _image(doc, path):
    ""

    from PySide import QtGui
    st = image_settings()
    w, h = image_size(doc)
    view = Gui.getDocument(doc.Name).ActiveView
    if st["type"] == "RGB":
        view.saveImage(path, w, h, "Current")
    else:
        import tempfile
        tmp = os.path.join(tempfile.mkdtemp(prefix="fw-img-"), "view.png")
        view.saveImage(tmp, w, h, "White")
        image = _toned(QtGui.QImage(tmp), st["type"])
        if not image.save(path):
            raise RuntimeError("the picture could not be written")
        try:
            os.remove(tmp)
        except OSError as _fw_err:
            _fw_log("saveas.py:image_tmp", _fw_err)
    if st["output"] == "Print capture":
        image = QtGui.QImage(path)
        if not image.isNull():
            dpm = int(round(st["dpi"] / 0.0254))
            image.setDotsPerMeterX(dpm)
            image.setDotsPerMeterY(dpm)
            image.save(path)
    return path


def _part_pdf(doc, path):
    ""


    import tempfile, time
    from PySide import QtGui
    view = Gui.getDocument(doc.Name).ActiveView
    tmp = os.path.join(tempfile.gettempdir(), "freeworks_pdf_view_%d.png" % os.getpid())     # pkg321: per session
    p = paths.params()
    in_colour, header = p.GetBool(PDF_COLOR, True), p.GetBool(PDF_HEADER, True)
    pw, ph = paper_mm(p.GetString(PDF_PAPER, "A4"))
    view.saveImage(tmp, 2400, int(2400 * ph / pw), "White")
    writer = QtGui.QPdfWriter(path)
    try:
        writer.setPageSize(QtGui.QPageSize(QtCore.QSizeF(ph, pw), QtGui.QPageSize.Millimeter))
        writer.setPageOrientation(QtGui.QPageLayout.Landscape)
    except Exception as _fw_err:
        _fw_log("saveas.py:699", _fw_err)
    writer.setResolution(300)
    writer.setTitle(doc.Label)
    painter = QtGui.QPainter(writer)
    try:
        page = painter.viewport()
        image = QtGui.QImage(tmp)
        if not in_colour:
            image = _toned(image, "Grayscale")
        margin = int(page.height() * 0.06)
        area = QtCore.QRect(margin, margin, page.width() - 2 * margin, page.height() - 3 * margin)
        scaled = image.scaled(area.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        x = area.x() + (area.width() - scaled.width()) // 2
        painter.drawImage(x, area.y(), scaled)
        font = painter.font()
        font.setPointSize(10)
        painter.setFont(font)
        if header:
            painter.drawText(QtCore.QRect(margin, page.height() - 2 * margin, page.width() - 2 * margin, margin),
                             QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                             "%s    %s" % (doc.Label, time.strftime("%Y-%m-%d %H:%M")))
    finally:
        painter.end()
    try:
        os.remove(tmp)
    except OSError as _fw_err:
        _fw_log("saveas.py:722", _fw_err)
    return path


def write(doc, path, writer):
    """Writes doc to path with writer; the document itself only for 'native'."""
    if writer in TEMPLATE_WRITERS:
        return save_template(doc, path)
    if writer == "native":
        doc.saveAs(path)
        try:
            # App's save leaves the GUI document "modified" (title asterisk, Save prompt on close: ChatGPT C13-01)
            Gui.getDocument(doc.Name).Modified = False
        except Exception as _fw_err:
            _fw_log("saveas.py:736", _fw_err)
        return
    # x123: an export is a copy: it left the part (or an assembly using it) marked changed, so closing asked to save
    clean = []
    try:
        # a document still waiting for the clean-up of an export just before counts as unchanged
        clean = [n for n in App.listDocuments() if Gui.getDocument(n) is not None
                 and (not Gui.getDocument(n).Modified or _CLEAN_LATER.get(n))]
    except Exception as _fw_err:
        _fw_log("saveas.py:export-clean", _fw_err)
    for n in clean:
        _CLEAN_LATER[n] = _CLEAN_LATER.get(n, 0) + 1
    try:
        return _write_export(doc, path, writer)
    finally:
        _keep_clean(clean, False)
        # open126: an assembly linking the exported part hears of the part's temporary objects a moment later
        # (a queued link update): clear it again then, once
        QtCore.QTimer.singleShot(400, lambda c=list(clean): _keep_clean(c, True))


_CLEAN_LATER = {}       # document name -> exports whose late clean-up is still to come


def _keep_clean(clean, late):
    for n in clean:
        if late:
            _CLEAN_LATER[n] = _CLEAN_LATER.get(n, 1) - 1
            if _CLEAN_LATER[n] <= 0:
                _CLEAN_LATER.pop(n, None)
        try:
            if n in App.listDocuments() and Gui.getDocument(n).Modified:
                Gui.getDocument(n).Modified = False
        except Exception as _fw_err:
            _fw_log("saveas.py:export-clean2", _fw_err)


def _write_export(doc, path, writer):
    if writer in ("dxf", "dwg", "pdf", "svg", "drawimage"):
        pages = [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage"]
        if not pages:
            raise RuntimeError("the drawing has no sheet")
        try:
            from . import drawexport          # the drawings thread's writer: all sheets, no-print layers (drawings-land37)
        except Exception:
            drawexport = None
        if drawexport is not None:
            return drawexport.write(doc, path, writer)
        page = pages[0]
        if writer == "dxf":
            import TechDraw
            TechDraw.writeDXFPage(page, path)
        elif writer == "dwg":
            import TechDraw, importDWG, tempfile
            tmp = os.path.join(tempfile.mkdtemp(), "page.dxf")
            TechDraw.writeDXFPage(page, tmp)
            convert = getattr(importDWG, "convertToDwg", None)
            if convert is None or not convert(tmp, path):
                raise RuntimeError("the DWG converter did not write the file")
        elif writer == "pdf":
            import TechDrawGui
            TechDrawGui.exportPageAsPdf(page, path)
        else:
            import TechDrawGui
            TechDrawGui.exportPageAsSvg(page, path)
        return
    objs = _solids(doc, writer)
    try:
        return _write_objs(doc, objs, path, writer)
    finally:
        _drop_flat(doc)


def _no_shape(o):
    try:
        sh = getattr(o, "Shape", None)
        return sh is None or sh.isNull() or not (sh.Faces or sh.Edges)
    except Exception:
        return False


def _write_objs(doc, objs, path, writer):
    if writer == "image":
        return _image(doc, path)
    if writer == "partpdf":
        return _part_pdf(doc, path)
    if not objs or all(_no_shape(o) for o in objs):
        raise RuntimeError("nothing to export")     # open128: an empty Body counted as something
    if writer == "partdxf":
        _part_dxf(doc, objs, path)
    elif writer in ("step203", "step214", "step242", "iges"):
        _solid_export(doc, objs, path, writer)
    elif writer == "stl":
        _stl(objs, path, doc)
    elif writer == "3mf":
        _3mf(doc, objs, path)
    elif writer == "mesh":
        _mesh_file(objs, path)
    elif writer == "vrml":
        _vrml(doc, objs, path)
    elif writer == "gltf":
        import ImportGui
        ImportGui.export(objs, path)
    elif writer == "ifc":
        import importers.exportIFC as exportIFC
        exportIFC.export(objs, path)
    elif writer == "cad":

        from swfiles import save
        ext = os.path.splitext(path)[1].lower()
        if ext == ".sldprt":
            save.export_part(objs, path)
        elif ext == ".sldasm":
            save.export_assembly(objs, path)
        else:
            from swfiles import cadconv
            cadconv.save_file(objs, path)
    else:
        raise RuntimeError("unknown type %s" % writer)


# ---------------------------------------------------------------- boxes
def _kb(size):
    return "%d bytes" % size if size < 10240 else ("%.0f KB" % (size / 1024.0) if size < 10 * 1048576
                                                     else "%.1f MB" % (size / 1048576.0))


class StlOptions(QtWidgets.QDialog):
    ""


    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("FW_StlOptions")
        self.setWindowTitle("Export Options")
        binary, res, dev, ang = stl_settings()
        lay = QtWidgets.QVBoxLayout(self)
        out = QtWidgets.QGroupBox("Output as")
        ol = QtWidgets.QHBoxLayout(out)
        self.binary = QtWidgets.QRadioButton("Binary")
        self.ascii = QtWidgets.QRadioButton("ASCII")
        (self.binary if binary else self.ascii).setChecked(True)
        ol.addWidget(self.binary)
        ol.addWidget(self.ascii)
        flags = stl_flags()
        ol.addStretch(1)
        ol.addWidget(QtWidgets.QLabel("Unit:"))
        self.unit = QtWidgets.QComboBox()
        self.unit.setObjectName("FW_StlUnit")
        self.unit.addItems([n for n, _s in STL_UNITS])
        self.unit.setCurrentText(flags["unit"])
        ol.addWidget(self.unit)
        lay.addWidget(out)
        box = QtWidgets.QGroupBox("Resolution")
        rl = QtWidgets.QGridLayout(box)
        self.res = {}
        for i, name in enumerate(("Coarse", "Fine", "Custom")):
            b = QtWidgets.QRadioButton(name)
            b.setChecked(name == res)
            b.toggled.connect(self._toggled)
            self.res[name] = b
            rl.addWidget(b, 0, i)
        self.dev_label = QtWidgets.QLabel("Deviation")
        rl.addWidget(self.dev_label, 1, 0)
        self.dev = QtWidgets.QDoubleSpinBox()
        self.dev.setDecimals(4)
        self.dev.setRange(0.0001, 100.0)
        self.dev.setSuffix(" mm")
        self.dev.setValue(dev)
        rl.addWidget(self.dev, 1, 1)
        self.ang_label = QtWidgets.QLabel("Angle")
        rl.addWidget(self.ang_label, 2, 0)
        self.ang = QtWidgets.QDoubleSpinBox()
        self.ang.setRange(0.5, 90.0)
        self.ang.setSuffix(" deg")
        self.ang.setValue(ang)
        rl.addWidget(self.ang, 2, 1)

        self.dev_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.dev_slider.setObjectName("FW_StlDeviationSlider")
        self.dev_slider.setRange(0, 100)
        self.ang_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.ang_slider.setObjectName("FW_StlAngleSlider")
        self.ang_slider.setRange(0, 100)
        rl.addWidget(self.dev_slider, 1, 2)
        rl.addWidget(self.ang_slider, 2, 2)
        self._sync_sliders()
        self.dev_slider.valueChanged.connect(self._slid)
        self.ang_slider.valueChanged.connect(self._slid)
        self.dev.valueChanged.connect(self._typed)
        self.ang.valueChanged.connect(self._typed)
        lay.addWidget(box)
        # export87: the result of the resolution on this document, and the triangles in the graphics area
        prev = QtWidgets.QGroupBox("Preview")
        pl = QtWidgets.QVBoxLayout(prev)
        self.show_preview = QtWidgets.QCheckBox("Show the triangles in the graphics area")
        self.show_preview.setObjectName("FW_StlShowPreview")
        self.show_preview.toggled.connect(lambda _on: self._refresh_preview())
        self.preview_info = QtWidgets.QLabel("")
        self.preview_info.setObjectName("FW_StlPreviewInfo")
        pl.addWidget(self.show_preview)
        pl.addWidget(self.preview_info)
        lay.addWidget(prev)
        self._overlay = None
        self._preview_timer = QtCore.QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(150)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self.checks = {}
        for key, text in ((STL_INFO, "Show STL info before file saving"), (STL_PREVIEW, "Preview before saving file"),
                          (STL_KEEP_SPACE, "Do not translate STL output data to positive space"),
                          (STL_SINGLE, "Save all components of an assembly in a single file")):
            c = QtWidgets.QCheckBox(text)
            c.setObjectName("FW_" + key)
            c.setChecked(paths.params().GetBool(key, False))
            self.checks[key] = c
            lay.addWidget(c)
        # exportopts-1119: Preview is shown under Show STL info only when that is on (no greyed box)
        self.checks[STL_INFO].toggled.connect(lambda on: self.checks[STL_PREVIEW].setVisible(on))
        self.checks[STL_PREVIEW].setVisible(self.checks[STL_INFO].isChecked())
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._toggled()
        self.binary.toggled.connect(lambda _on: self._preview_timer.start())

    # export87: sliders over the Custom values (log scale for the deviation)
    DEV_RANGE = (0.001, 2.0)
    ANG_RANGE = (0.5, 60.0)

    @staticmethod
    def _to_slider(v, lo, hi):
        import math
        v = max(lo, min(hi, v))
        return int(round(100 * (1 - math.log(v / lo) / math.log(hi / lo))))   # right = finer

    @staticmethod
    def _from_slider(i, lo, hi):
        return lo * (hi / lo) ** (1 - i / 100.0)

    def _sync_sliders(self):
        for slider, spin, rng in ((self.dev_slider, self.dev, self.DEV_RANGE), (self.ang_slider, self.ang, self.ANG_RANGE)):
            slider.blockSignals(True)
            slider.setValue(self._to_slider(spin.value(), *rng))
            slider.blockSignals(False)

    def _slid(self, *_a):
        for slider, spin, rng, nd in ((self.dev_slider, self.dev, self.DEV_RANGE, 4), (self.ang_slider, self.ang, self.ANG_RANGE, 1)):
            if slider is self.sender():
                spin.blockSignals(True)
                spin.setValue(round(self._from_slider(slider.value(), *rng), nd))
                spin.blockSignals(False)
        self._preview_timer.start()

    def _typed(self, *_a):
        self._sync_sliders()
        self._preview_timer.start()

    def resolution(self):
        """(deviation mm, angle deg) the boxes stand at."""
        name = next((n for n, b in self.res.items() if b.isChecked()), "Fine")
        return RESOLUTIONS.get(name, (self.dev.value(), self.ang.value()))

    def preview_mesh(self):
        """The document's export triangles at the resolution picked (None without a document or a solid)."""
        doc = App.ActiveDocument
        if doc is None:
            return None
        try:
            objs = [o for o in _solids(doc, "stl") if getattr(o, "Shape", None) is not None and not o.Shape.isNull()]
            if not objs:
                return None
            dev, ang = self.resolution()
            return _stl_mesh(objs, dev, ang)
        finally:
            _drop_flat(doc)

    def _refresh_preview(self):
        try:
            mesh = self.preview_mesh()
        except Exception as error:
            mesh = None
            _fw_log("saveas.py:stl_preview", error)
        if mesh is None:
            self.preview_info.setText("Open a part or an assembly to see its triangles here.")
            self._hide_overlay()
            return
        n = mesh.CountFacets
        size = 84 + 50 * n if self.binary.isChecked() else 250 * n
        self.preview_info.setText("%d triangles, file size about %s." % (n, _kb(size)))
        self.preview_count = n
        self._hide_overlay()
        if self.show_preview.isChecked():
            self._show_overlay(mesh)

    def _show_overlay(self, mesh):
        try:
            from pivy import coin
            view = Gui.ActiveDocument.ActiveView
            pts, tris = mesh.Topology
            sep = coin.SoSeparator()
            sep.setName("FW_StlPreview")
            colour = coin.SoBaseColor()
            colour.rgb = (0.05, 0.25, 0.75)
            sep.addChild(colour)
            style = coin.SoDrawStyle()
            style.lineWidth = 1
            sep.addChild(style)
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
            sep.addChild(coords)
            lines = coin.SoIndexedLineSet()
            idx = []
            for a, b, c in tris:
                idx += [a, b, c, a, -1]
            lines.coordIndex.setValues(0, len(idx), idx)
            sep.addChild(lines)
            view.getSceneGraph().addChild(sep)
            self._overlay = (view, sep)
        except Exception as error:
            _fw_log("saveas.py:stl_overlay", error)

    def _hide_overlay(self):
        if self._overlay is not None:
            view, sep = self._overlay
            self._overlay = None
            try:
                view.getSceneGraph().removeChild(sep)
            except Exception as error:
                _fw_log("saveas.py:stl_overlay_off", error)

    def done(self, r):
        self._hide_overlay()
        super().done(r)

    def showEvent(self, event):
        super().showEvent(event)
        self._preview_timer.start()

    def _toggled(self, *args):
        name = next(n for n, b in self.res.items() if b.isChecked()) if any(
            b.isChecked() for b in self.res.values()) else "Fine"
        custom = name == "Custom"
        if not custom:
            dev, ang = RESOLUTIONS[name]
            self.dev.setValue(dev)
            self.ang.setValue(ang)
        for w in (self.dev, self.ang, self.dev_label, self.ang_label, self.dev_slider, self.ang_slider):
            w.setVisible(custom)          # exportopts-1119: the tolerances only with Custom (no greyed boxes)
        self._sync_sliders()
        self._preview_timer.start()

    def accept(self):
        p = paths.params()
        p.SetBool(STL_BINARY, self.binary.isChecked())
        name = next((n for n, b in self.res.items() if b.isChecked()), "Fine")
        p.SetString(STL_RESOLUTION, name)
        p.SetFloat(STL_DEVIATION, self.dev.value())
        p.SetFloat(STL_ANGLE, self.ang.value())
        p.SetString(STL_UNIT, self.unit.currentText())
        for key, c in self.checks.items():
            p.SetBool(key, c.isChecked())
        super().accept()


class TmfOptions(StlOptions):
    ""


    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FW_3mfOptions")
        unit, with_mat, with_app = tmf_settings()
        lay = self.layout()
        self.binary.parent().hide()           # 3MF has no Binary / ASCII
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Unit:"))
        self.unit = QtWidgets.QComboBox()
        self.unit.setObjectName("FW_3mfUnit")
        self.unit.addItems([u[0] for u in TMF_UNITS])
        self.unit.setCurrentText(unit)
        row.addWidget(self.unit, 1)
        lay.insertLayout(0, row)
        self.materials = QtWidgets.QCheckBox("Include materials")
        self.materials.setObjectName("FW_3mfMaterials")
        self.materials.setChecked(with_mat)
        self.appearances = QtWidgets.QCheckBox("Include appearances")
        self.appearances.setObjectName("FW_3mfAppearances")
        self.appearances.setChecked(with_app)
        lay.insertWidget(lay.count() - 1, self.materials)
        lay.insertWidget(lay.count() - 1, self.appearances)
        for c in getattr(self, "checks", {}).values():
            c.hide()                          # STL's own rows (STL info, positive space, single file)

    def accept(self):
        p = paths.params()
        p.SetString(TMF_UNIT, self.unit.currentText())
        p.SetBool(TMF_MATERIALS, self.materials.isChecked())
        p.SetBool(TMF_APPEARANCES, self.appearances.isChecked())
        # the Resolution rows are shared with STL; STL's Unit and its other rows stay as they were
        name = next((n for n, b in self.res.items() if b.isChecked()), "Fine")
        p.SetString(STL_RESOLUTION, name)
        p.SetFloat(STL_DEVIATION, self.dev.value())
        p.SetFloat(STL_ANGLE, self.ang.value())
        QtWidgets.QDialog.accept(self)


DRAWING_WRITERS = ("pdf", "dxf", "dwg", "svg")



FORMATS = (("IGES 5.3", ("iges",)), ("STEP", ("step203", "step214", "step242")), ("VRML", ("vrml",)),
           ("STL/3MF/AMF", ("stl", "3mf", "mesh")), ("PDF", ("partpdf",)), ("TIF/JPG/PNG", ("image", "drawimage")),
           ("DXF/DWG", ("partdxf",)))
FORMAT_ALIASES = {"IGES": "IGES 5.3", "STL": "STL/3MF/AMF", "3MF": "STL/3MF/AMF", "AMF": "STL/3MF/AMF"}
STEP_SCHEMES = (("AP203", "step203"), ("AP214", "step214"), ("AP242", "step242"))

# Import-Export > STEP), so File > Export follows it too; set now as well, FreeCAD reads it only at start
STEP_SCHEME_KEYS = ("User parameter:BaseApp/Preferences/Mod/Import/hSTEP", "User parameter:BaseApp/Preferences/Mod/Import",
                    "User parameter:BaseApp/Preferences/Mod/Part/STEP")
FC_SCHEMES = {"step203": "AP203", "step214": "AP214IS", "step242": "AP242DIS"}


def step_scheme():
    """The STEP type written when none is picked: step203 / step214 / step242."""
    for k in STEP_SCHEME_KEYS:
        v = App.ParamGet(k).GetString("Scheme", "")
        w = next((w for w, s in FC_SCHEMES.items() if s == v), None)
        if w:
            return w
    return "step214"


def step_schemes():
    """The STEP types this FreeCAD writes (AP203 and AP242 need OpenCASCADE's schema call)."""
    return [w for _t, w in STEP_SCHEMES if w == "step214" or _have_ap203()]


def set_step_scheme(writer):
    scheme = FC_SCHEMES.get(writer)
    if scheme is None:
        return
    for k in STEP_SCHEME_KEYS:
        App.ParamGet(k).SetString("Scheme", scheme)
    calls = _schema_calls()
    if calls is not None:
        try:
            calls[0](b"write.step.schema", scheme.encode())
        except Exception as _fw_err:
            _fw_log("saveas.py:set_step_scheme", _fw_err)
SHARED_ROWS = ("Export 3D Curve features", "Export sketch entities", "Use high trim curve accuracy",
               "Split periodic faces")
OPTION_WRITERS = tuple(w for _f, ws in FORMATS for w in ws) + DRAWING_WRITERS + ("partdxf",)


def format_of(writer):
    return next((f for f, ws in FORMATS if writer in ws), None)


def _store_export(text, value):
    from . import optionspages
    optionspages.set_stored("Export", text, bool(value))


class ExportOptions(QtWidgets.QDialog):
    ""




    def __init__(self, fmt="STEP", writer=None, parent=None, schemes=None):
        super().__init__(parent or Gui.getMainWindow())
        fmt = FORMAT_ALIASES.get(fmt, fmt)
        self.setObjectName("FW_ExportOptions")
        self.setWindowTitle("Export Options")
        lay = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("File Format:"))
        self.format = QtWidgets.QComboBox()
        self.format.setObjectName("FW_ExportFormat")
        self.format.addItems([f for f, _w in FORMATS])
        row.addWidget(self.format, 1)
        lay.addLayout(row)
        self.stack = QtWidgets.QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.checks = {}
        self.panes = {}
        self.panes["IGES 5.3"] = self._iges()
        self.panes["STEP"] = self._step(writer, schemes)
        self.stl = self._embed(StlOptions)
        self.panes["STL/3MF/AMF"] = self._mesh_pane()
        self.rows = {}
        for f in ("VRML", "PDF", "TIF/JPG/PNG", "DXF/DWG"):
            self.panes[f] = self._rows_pane(f)
        for f, _w in FORMATS:
            self.stack.addWidget(self.panes[f])
        self.format.currentTextChanged.connect(lambda f: self.stack.setCurrentWidget(self.panes[f]))
        self.format.setCurrentText(fmt)
        self.stack.setCurrentWidget(self.panes[fmt])
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
                                             | QtWidgets.QDialogButtonBox.Help)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.helpRequested.connect(self._help)
        lay.addWidget(buttons)

    def _mesh_pane(self):
        ""
        pane = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(pane)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stl)
        unit, with_mat, with_app = tmf_settings()
        box = QtWidgets.QGroupBox("3MF")
        bl = QtWidgets.QGridLayout(box)
        bl.addWidget(QtWidgets.QLabel("Unit:"), 0, 0)
        self.tmf_unit = QtWidgets.QComboBox()
        self.tmf_unit.setObjectName("FW_3mfUnit")
        self.tmf_unit.addItems([u[0] for u in TMF_UNITS])
        self.tmf_unit.setCurrentText(unit)
        bl.addWidget(self.tmf_unit, 0, 1)
        self.tmf_materials = QtWidgets.QCheckBox("Include materials")
        self.tmf_materials.setObjectName("FW_3mfMaterials")
        self.tmf_materials.setChecked(with_mat)
        self.tmf_appearances = QtWidgets.QCheckBox("Include appearances")
        self.tmf_appearances.setObjectName("FW_3mfAppearances")
        self.tmf_appearances.setChecked(with_app)
        bl.addWidget(self.tmf_materials, 1, 0, 1, 2)
        bl.addWidget(self.tmf_appearances, 2, 0, 1, 2)
        lay.addWidget(box)
        lay.addStretch(1)
        return pane

    def _rows_pane(self, fmt):
        """A format whose rows are System Options > Export's own (the same settings, kept the same way)."""
        import copy
        pane = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(pane)
        rows = []
        try:
            from . import optionspages
            sections = optionspages.export_sections(fmt)
        except Exception as error:
            _fw_log("saveas.py:rows_pane", error)
            sections = []
        for heading, settings in sections:
            box = QtWidgets.QGroupBox(heading or fmt)
            bl = QtWidgets.QVBoxLayout(box)
            for spec in settings:
                st = copy.copy(spec)
                bl.addWidget(st.widget())
                st.load()
                rows.append(st)
            lay.addWidget(box)
        lay.addStretch(1)
        self.rows[fmt] = rows
        try:
            from . import optionspages
            when = [(gb, optionspages.EXPORT_WHEN[gb.title()]) for gb in pane.findChildren(QtWidgets.QGroupBox)
                    if gb.title() in optionspages.EXPORT_WHEN]

            def follow():
                for gb, (key, value) in when:
                    gb.setVisible(optionspages.radio_picked(pane, key, value))
            for _gb, (key, value) in when:
                optionspages.radio_picked(pane, key, value, follow)
            follow()
        except Exception as error:
            _fw_log("saveas.py:rows_when", error)
        return pane

    def done(self, r):
        self.stl._hide_overlay()
        super().done(r)

    def _embed(self, cls):
        pane = cls(self)
        pane.setWindowFlags(Qt.Widget)
        for b in pane.findChildren(QtWidgets.QDialogButtonBox):
            b.hide()
        return pane

    def _check(self, layout, fmt, text, default):
        c = QtWidgets.QCheckBox(text)
        c.setObjectName("FW_Export_%s_%s" % (fmt, "".join(w.title() for w in text.split())[:40]))
        c.setChecked(export_option(text, default))
        layout.addWidget(c)
        self.checks.setdefault(fmt, {})[text] = c
        return c

    def _shared(self, layout, fmt):
        for text, default in zip(SHARED_ROWS, (True, False, True, True)):
            self._check(layout, fmt, text, default)

    def _iges(self):
        pane = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(pane)
        box = QtWidgets.QGroupBox("IGES solid/surface features")
        bl = QtWidgets.QHBoxLayout(box)
        bl.addWidget(QtWidgets.QLabel("Output as"))
        self.iges_out = QtWidgets.QComboBox()
        self.iges_out.setObjectName("FW_ExportIgesOutput")
        for text, value in (("Manifold Solid (type 186)", 1), ("Trimmed Surface (type 144)", 0),
                            ("Wireframe (type 110)", 2)):
            self.iges_out.addItem(text, value)
        try:
            from . import optionspages
            self.iges_out.setCurrentIndex(max(0, self.iges_out.findData(optionspages._iges_output_read())))
        except Exception as _fw_err:
            _fw_log("saveas.py:iges_out", _fw_err)
        bl.addWidget(self.iges_out, 1)
        lay.addWidget(box)
        self._shared(lay, "IGES")
        asm = QtWidgets.QGroupBox("IGES assembly structure")
        al = QtWidgets.QVBoxLayout(asm)
        self._check(al, "IGES", "Save all components of an assembly in one file", True)
        self._check(al, "IGES", "Flatten assembly hierarchy", True)
        lay.addWidget(asm)
        lay.addStretch(1)
        return pane

    def _step(self, writer, schemes):
        pane = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(pane)
        box = QtWidgets.QGroupBox("Output as")
        bl = QtWidgets.QHBoxLayout(box)
        self.schemes = {}
        for text, w in STEP_SCHEMES:
            if schemes is not None and w not in schemes:
                continue                     # only the STEP types this FreeCAD writes
            b = QtWidgets.QRadioButton(text)
            b.setObjectName("FW_ExportStep" + text)
            b.setChecked(w == (writer or step_scheme()))
            bl.addWidget(b)
            self.schemes[w] = b
        if self.schemes and not any(b.isChecked() for b in self.schemes.values()):
            next(iter(self.schemes.values())).setChecked(True)
        lay.addWidget(box)
        self._check(lay, "STEP", "Export face/edge properties", True)
        self._shared(lay, "STEP")
        lay.addStretch(1)
        return pane

    def scheme(self):
        """The STEP type picked under Output as (step203 / step214 / step242)."""
        return next((w for w, b in self.schemes.items() if b.isChecked()), "step214")

    def _help(self):
        try:
            from . import helpmenu
            from . import helpguide
            if helpguide.show_topic("export options") is None:
                helpmenu.show("home", search="export options")
        except Exception as _fw_err:
            _fw_log("saveas.py:export_help", _fw_err)

    def accept(self):
        fmt = self.format.currentText()
        for text, c in self.checks.get({"IGES 5.3": "IGES"}.get(fmt, fmt), {}).items():
            _store_export(text, c.isChecked())
        if fmt == "IGES 5.3":
            try:
                from . import optionspages
                optionspages._iges_output_write(self.iges_out.currentData())
            except Exception as _fw_err:
                _fw_log("saveas.py:iges_write", _fw_err)
        elif fmt == "STEP" and self.schemes:
            set_step_scheme(self.scheme())
        elif fmt == "STL/3MF/AMF":
            self.stl.accept()
            p = paths.params()
            p.SetString(TMF_UNIT, self.tmf_unit.currentText())
            p.SetBool(TMF_MATERIALS, self.tmf_materials.isChecked())
            p.SetBool(TMF_APPEARANCES, self.tmf_appearances.isChecked())
        for st in self.rows.get(fmt, []):
            st.save()
        super().accept()


def _has_drawexport():
    try:
        from . import drawexport  # noqa: F401
        return True
    except Exception:
        return False


class _FileTypes(QtWidgets.QFileIconProvider):
    ""

    NAMES = {"part": "FreeCAD Part Document", "assembly": "FreeCAD Assembly Document",
             "drawing": "FreeCAD Drawing Document"}

    def type(self, info):
        try:
            if info.isFile() and info.suffix().lower() == "fcstd":
                from . import fcstdinfo
                return self.NAMES.get(fcstdinfo.kind(info.absoluteFilePath()), "FreeCAD Document")
        except Exception as error:
            _fw_log("saveas.py:filetypes", error)
        return super().type(info)


def _file_types(box):
    try:
        box._fw_types = _FileTypes()        # kept with the box: the dialog does not own its provider
        box.setIconProvider(box._fw_types)
    except Exception as error:
        _fw_log("saveas.py:filetypes", error)


def last_folder():
    ""


    try:
        p = App.ParamGet("User parameter:BaseApp/Preferences/General").GetString("FileOpenSavePath", "")
        if p and os.path.isdir(p):
            return p
    except Exception as _fw_err:
        _fw_log("saveas.py:last-folder", _fw_err)
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    return docs if os.path.isdir(docs) else os.path.expanduser("~")


def remember_folder(path):
    try:
        folder = os.path.dirname(os.path.abspath(path))
        if os.path.isdir(folder) and not os.path.basename(folder).startswith("fw_versions_"):
            App.ParamGet("User parameter:BaseApp/Preferences/General").SetString("FileOpenSavePath", folder)
    except Exception as _fw_err:
        _fw_log("saveas.py:remember-folder", _fw_err)


def save_dialog(doc):
    ""
    box = QtWidgets.QFileDialog(Gui.getMainWindow(), "Save As")
    box.setObjectName("FW_SaveAs")
    box.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
    _file_types(box)
    box.setAcceptMode(QtWidgets.QFileDialog.AcceptSave)
    box.setLabelText(QtWidgets.QFileDialog.FileType, "Save as type:")
    types = save_types(doc)
    box.setNameFilters([t[0] for t in types])
    start = doc.FileName or os.path.join(last_folder(), doc.Label + ".FCStd")
    box.setDirectory(os.path.dirname(start))
    box.selectFile(os.path.splitext(os.path.basename(start))[0])
    options = QtWidgets.QPushButton("Options...")
    options.setObjectName("FW_SaveAsOptions")
    current = {"writer": "native"}

    def show_options():
        ""

        if current["writer"] in DRAWING_WRITERS:
            try:
                from . import drawexport
                drawexport.ExportOptionsDialog(doc, current["writer"], box).exec_()
                return
            except Exception as error:
                App.Console.PrintLog("FreeCAD: drawing export options: %s\n" % error)
        fmt = format_of(current["writer"])
        if fmt is not None:

            have = [t[2] for t in types]
            dlg = ExportOptions(fmt, current["writer"], box, schemes=[w for w in have if w.startswith("step")])
            if dlg.exec() and dlg.format.currentText() == "STEP" and current["writer"] != dlg.scheme():
                label = next((t[0] for t in types if t[2] == dlg.scheme()), None)
                if label:
                    box.selectNameFilter(label)       # Output as AP203 / AP214 / AP242 picks that Save as type
                    chosen(label)
            return
        try:
            from . import options as optionsdlg
            page = optionsdlg.OptionsDialog(tab=0)
            page.select("Export")
            page.exec()
            page.deleteLater()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: export options: %s\n" % error)
            StlOptions(box).exec()

    box.description = QtWidgets.QLineEdit(box)
    box.description.setObjectName("FW_SaveAsDescription")
    box.description.setPlaceholderText("Add a description")
    try:
        box.description.setText(doc.Comment or "")
    except Exception as _fw_err:
        _fw_log("saveas.py:1001", _fw_err)
    options.clicked.connect(show_options)
    lay = box.layout()

    # components with Add prefix / Add suffix, and Advanced (the referenced files one by one)
    extras = QtWidgets.QWidget(box)
    el = QtWidgets.QGridLayout(extras)
    el.setContentsMargins(0, 0, 0, 0)
    box.save_mode = QtWidgets.QButtonGroup(extras)
    box.save_plain = QtWidgets.QRadioButton("Save as", extras)
    box.save_plain.setObjectName("FW_SaveAsPlain")
    box.save_plain.setChecked(True)
    box.save_continue = QtWidgets.QRadioButton("Save as copy and continue", extras)
    box.save_continue.setObjectName("FW_SaveAsCopyContinue")
    box.save_open = QtWidgets.QRadioButton("Save as copy and open", extras)
    box.save_open.setObjectName("FW_SaveAsCopyOpen")
    for i, b in enumerate((box.save_plain, box.save_continue, box.save_open)):
        box.save_mode.addButton(b, i)
        el.addWidget(b, i, 0)
    box.include_refs = QtWidgets.QCheckBox("Include all referenced components", extras)
    box.include_refs.setObjectName("FW_SaveAsIncludeRefs")
    el.addWidget(box.include_refs, 0, 1, 1, 2)

    box.add_prefix = QtWidgets.QRadioButton("Add prefix", extras)
    box.add_prefix.setObjectName("FW_SaveAsAddPrefix")
    box.add_prefix.setChecked(True)
    box.add_suffix = QtWidgets.QRadioButton("Add suffix", extras)
    box.add_suffix.setObjectName("FW_SaveAsAddSuffix")
    box.affix = QtWidgets.QLineEdit(extras)
    box.affix.setObjectName("FW_SaveAsAffix")
    box.affix_group = QtWidgets.QButtonGroup(extras)
    box.affix_group.addButton(box.add_prefix)
    box.affix_group.addButton(box.add_suffix)
    el.addWidget(box.add_prefix, 1, 1)
    el.addWidget(box.add_suffix, 2, 1)
    el.addWidget(box.affix, 1, 2)
    advanced = QtWidgets.QPushButton("Advanced", extras)
    advanced.setObjectName("FW_SaveAsAdvanced")

    advanced.clicked.connect(lambda: AdvancedSaveDialog(doc, box).exec() and box.reject())
    el.addWidget(advanced, 0, 3)

    def refs_toggled(on):
        for w in (box.add_prefix, box.add_suffix, box.affix):
            w.setEnabled(bool(on))
            w.setVisible(bool(on))          # shown with Include all referenced components (no greyed boxes)
    box.include_refs.toggled.connect(refs_toggled)
    refs_toggled(False)

    box.hide_folders = QtWidgets.QPushButton("\u25b4 Hide Folders", extras)
    box.hide_folders.setObjectName("FW_SaveAsHideFolders")
    box.hide_folders.setFlat(True)

    def toggle_folders():
        side = box.findChild(QtWidgets.QListView, "sidebar")
        show = side is not None and not side.isVisible()
        if side is not None:
            side.setVisible(show)
        box.hide_folders.setText("\u25b4 Hide Folders" if show else "\u25be Browse Folders")
    box.hide_folders.clicked.connect(lambda checked=False: toggle_folders())

    box.hide_folders.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
    el.addWidget(box.hide_folders, 3, 0, Qt.AlignLeft)
    el.setColumnStretch(4, 1)
    try:        # Include all referenced components and Advanced only mean something when the document links to others
        linked = bool(referenced_documents(doc))
    except Exception:
        linked = False
    box.include_refs.setVisible(linked)
    advanced.setVisible(linked)
    if isinstance(lay, QtWidgets.QGridLayout):
        r = lay.rowCount()
        lay.addWidget(QtWidgets.QLabel("Description:", box), r, 0)
        lay.addWidget(box.description, r, 1)
        lay.addWidget(options, r, 2)
        lay.addWidget(extras, lay.rowCount(), 0, 1, lay.columnCount())

    def chosen(label):
        writer = next((t[2] for t in types if t[0] == label), "native")
        current["writer"] = writer
        options.setEnabled(writer in OPTION_WRITERS)
        options.setVisible(options.isEnabled())     # Options... only for a type that has options (exportopts-1119)
        if writer in TEMPLATE_WRITERS:
            box.setDirectory(templates_dir())
        ext = next((t[1][0] for t in types if t[0] == label), "FCStd")
        box.setDefaultSuffix(ext)
    box.filterSelected.connect(chosen)
    chosen(types[0][0])
    _save_size(box)             # lookaudit-1120 AB1
    return box, types


def _open_elsewhere(doc, path):
    """save115: another open document whose file is path (None when there is none)."""
    try:
        # save121 (Reviewer): real paths, so a folder link / junction, a mapped drive or an 8.3 name is caught too
        me = os.path.normcase(os.path.realpath(path))
        there = os.path.exists(path)
        for d in App.listDocuments().values():
            if d is doc or not d.FileName:
                continue
            if os.path.normcase(os.path.realpath(d.FileName)) == me:
                return d
            try:
                if there and os.path.exists(d.FileName) and os.path.samefile(path, d.FileName):
                    return d
            except OSError:
                continue
    except Exception as _fw_err:
        _fw_log("saveas.py:open_elsewhere", _fw_err)
    return None


def save_as(doc=None, path=None, label=None, mode="save", refs=None):
    """Save As: shows the box (or uses path and the type label, for checks) and writes the file.
    mode: "save", "copy" (Save as copy and continue) or "copy_open" (Save as copy and open); refs: (prefix,
    suffix) for Include all referenced components (both given by the box when it is shown).
    Returns the path written, or None."""
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    interactive = path is None
    if path is None:
        box, types = save_dialog(doc)
        if not box.exec():
            return None
        path = box.selectedFiles()[0]
        label = box.selectedNameFilter()
        mode = ("save", "copy", "copy_open")[box.save_mode.checkedId()]
        try:
            if box.description.text() != (doc.Comment or ""):
                doc.Comment = box.description.text()
        except Exception as _fw_err:
            _fw_log("saveas.py:1083", _fw_err)
        if box.include_refs.isChecked():
            refs = (box.affix.text() if box.add_prefix.isChecked() else "",
                    box.affix.text() if box.add_suffix.isChecked() else "")
    else:
        types = save_types(doc)
    entry = next((t for t in types if t[0] == label), types[0])
    if not any(path.lower().endswith("." + e.lower()) for e in entry[1]):
        path += "." + entry[1][0]
    other = _open_elsewhere(doc, path)
    if other is not None:

        msg = ("%s is open in FreeCAD (%s). Close it first, or save under a different name."
               % (os.path.basename(path), other.Label))
        App.Console.PrintWarning("FreeCAD: Save As: %s\n" % msg)
        try:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Save As", msg)
        except Exception as _fw_err:
            _fw_log("saveas.py:open-elsewhere", _fw_err)
        return None
    old_file = doc.FileName
    try:
        if mode in ("copy", "copy_open") and entry[2] == "native":
            doc.saveCopy(path)
        elif entry[2] == "partdxf" and interactive and _part_dxf_panel(doc, path):
            return path         # dxf90: written by the DXF / DWG Output PropertyManager's Cleanup > Save
        else:
            write(doc, path, entry[2])
            # er102: a writer that fails without saying so (PDF into a folder that cannot be made) is caught here
            if entry[2] in WRITERS_CHECKED and not _written(path):
                raise RuntimeError("the file was not written")
        if refs is not None:
            before = old_file if mode == "save" else doc.FileName
            copies = save_referenced(doc, os.path.dirname(path), refs[0], refs[1])
            if copies:
                _relink_copies(copies + [(doc, before, path)])
                if mode == "save":
                    doc = _reopen(doc, path) or doc
        if mode == "save" and entry[2] == "native":
            try:
                from . import filecmds
                if filecmds.is_read_only(doc):
                    filecmds.set_read_only(doc, False)
            except Exception as _fw_err:
                _fw_log("saveas.py:save_as read-only", _fw_err)
        remember_folder(path)
        if mode == "copy_open":
            if entry[2] == "native":
                App.openDocument(path)
            else:
                _open_export(path)
    except Exception as error:

        if str(error) == "nothing to export":
            # open128: an empty new part exported said to check the folder and other programs
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Save As", (
                "%s was not saved: %s has no solid or surface body to export yet."
                % (os.path.basename(path), doc.Label)))
            return None
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Save As", (
            "%s was not saved. Check that the folder can be written to and that the file is not open in another "
            "program.\n\n%s" % (os.path.basename(path), error)))
        return None
    if (entry[2] == "native" and mode != "copy") or entry[2] in TEMPLATE_WRITERS:
        _add_recent(path)       # startup-1120 N8 (filehandling88: a copy not opened is not a recent document)
    return path


def _open_export(path):
    """sv107: Save as copy and open with an export type (STEP, IGES, STL...) opens the file written, through
    FreeCAD's importer for that type, in a document of its own. A type FreeCAD cannot open says so."""
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    try:
        mods = list(App.getImportType(ext) or [])
    except Exception:
        mods = []
    if not mods:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Save As",
                                          "%s was saved. FreeCAD cannot open this file type." % os.path.basename(path))
        return None
    import importlib
    before = set(App.listDocuments())
    importlib.import_module(mods[0]).open(path)     # the importer's open: a new document named after the file
    new = [App.getDocument(n) for n in App.listDocuments() if n not in before]
    if new and not new[0].FileName:
        try:
            new[0].Label = os.path.splitext(os.path.basename(path))[0]
        except Exception as _fw_err:
            _fw_log("saveas.py:_open_export", _fw_err)
    return new[0] if new else App.ActiveDocument


# er102: writers whose file is looked for after Save As (an assembly's components may each get "<name>-<part>.ext")
WRITERS_CHECKED = ("native", "step203", "step214", "step242", "iges", "partpdf", "pdf", "3mf", "gltf", "stl", "vrml")


def _written(path):
    if os.path.isfile(path):
        return True
    stem, ext = os.path.splitext(os.path.basename(path))
    folder = os.path.dirname(path) or "."
    try:
        return any(n.startswith(stem + "-") and n.lower().endswith(ext.lower()) for n in os.listdir(folder))
    except OSError:
        return False


def _add_recent(path):
    ""

    try:
        from . import cleanopen
        cleanopen.recent_add(os.path.abspath(path))
    except Exception as _fw_err:
        _fw_log("saveas.py:_add_recent", _fw_err)


def referenced_documents(doc):
    ""


    out = []
    for obj in doc.Objects:
        try:
            for dep in list(obj.OutList) + [getattr(obj, "LinkedObject", None)]:
                if dep is not None and dep.Document is not doc and dep.Document not in out:
                    out.append(dep.Document)
        except Exception as _fw_err:
            _fw_log("saveas.py:1118", _fw_err)
            continue
    try:
        for dep in doc.getDependentDocuments(True):
            if dep is not doc and dep not in out:
                out.append(dep)
    except Exception:
        pass
    return out


def _relink_copies(written):
    ""


    try:
        from . import asmpackgo
    except Exception:
        return
    mapping = {os.path.normpath(old): os.path.normpath(new) for _d, old, new in written if old}
    if not mapping:
        return
    for _d, old, new in written:
        for src in (os.path.dirname(new), os.path.dirname(old) if old else None):
            if src:
                m = dict(mapping)
                m["__src_dir__"] = src
                try:
                    asmpackgo.relink(new, m)
                except Exception as error:
                    App.Console.PrintWarning("FreeCAD: %s keeps its old links: %s\n" % (os.path.basename(new), error))


def _reopen(doc, path):
    """The document saved under its new name opens again from it, on the renamed copies."""
    try:
        App.closeDocument(doc.Name)
        return App.openDocument(path)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not opened again: %s\n" % (os.path.basename(path), error))
        return None


def save_referenced(doc, folder, prefix="", suffix=""):
    """Include all referenced components: a copy of each referenced document beside the file, with
    the prefix and suffix on its name. Returns the paths written."""
    written = []
    for ref in referenced_documents(doc):
        name = prefix + (os.path.splitext(os.path.basename(ref.FileName))[0] if ref.FileName else ref.Label) + suffix
        target = os.path.join(folder, name + ".FCStd")
        if ref.FileName and os.path.normpath(ref.FileName) == os.path.normpath(target):
            continue        # no prefix or suffix and the same folder: the file itself
        try:
            ref.saveCopy(target)
            written.append((ref, ref.FileName, target))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s not copied: %s\n" % (ref.Label, error))
    return written


class AdvancedSaveDialog(QtWidgets.QDialog):
    ""


    def __init__(self, doc, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc
        self.setObjectName("FW_SaveAsAdvanced")
        self.setWindowTitle("Save As with References")
        self.resize(640, 360)
        lay = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(0, 3, self)
        self.table.setObjectName("FW_SaveAsRefTable")
        self.table.setHorizontalHeaderLabels(["Save", "Name", "Folder"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.docs = [doc] + referenced_documents(doc)
        for d in self.docs:
            r = self.table.rowCount()
            self.table.insertRow(r)
            tick = QtWidgets.QTableWidgetItem()
            tick.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            tick.setCheckState(Qt.Checked)
            self.table.setItem(r, 0, tick)
            base = os.path.splitext(os.path.basename(d.FileName))[0] if d.FileName else d.Label
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(base))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(os.path.dirname(d.FileName) if d.FileName else os.path.expanduser("~")))
        lay.addWidget(self.table, 1)
        row = QtWidgets.QHBoxLayout()
        folder = QtWidgets.QPushButton("Browse folder...", self)
        folder.setObjectName("FW_SaveAsRefFolder")
        folder.clicked.connect(self._folder)
        row.addWidget(folder)
        row.addStretch(1)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        lay.addLayout(row)
        self.written = []

    def _folder(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder for the files", self.table.item(0, 2).text())
        if path:
            for r in range(self.table.rowCount()):
                self.table.item(r, 2).setText(path)

    def accept(self):
        copies, main = [], None
        for r, d in enumerate(self.docs):
            if self.table.item(r, 0).checkState() != Qt.Checked:
                continue
            target = os.path.join(self.table.item(r, 2).text(), self.table.item(r, 1).text() + ".FCStd")
            before = d.FileName
            try:
                if d is self.doc:
                    d.saveAs(target)
                    main = target
                else:
                    d.saveCopy(target)
                self.written.append(target)
                copies.append((d, before, target))
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: %s not saved: %s\n" % (d.Label, error))
        # the new files use each other (the assembly its renamed parts, a part made in context the
        # renamed part it references), and the document goes on from its new file
        _relink_copies(copies)
        if main is not None and len(copies) > 1:
            self.doc = _reopen(self.doc, main) or self.doc
        super().accept()


def _screen_scale():
    try:
        from PySide import QtGui
        return max([1.0] + [float(s.devicePixelRatio()) for s in QtGui.QGuiApplication.screens()])
    except Exception:
        return 1.0


def _quick_icon(kind):
    """Quick Filter pictures: the part, assembly and drawing pictures of the New box; Top-level assemblies is
    the assembly picture with a small blue arrow up drawn on its corner (our own art)."""
    from PySide import QtGui
    try:
        from . import newdoc
        spec = {"part": "Part", "assembly": "Assembly", "drawing": "Drawing", "top": "Assembly"}[kind]
        k = next(x for x in newdoc.KINDS if x[0] == spec)
        icon = newdoc._icon(k[2], k[3])
    except Exception:
        icon = QtGui.QIcon()
    if kind != "top" or icon.isNull():
        return icon
    scale = _screen_scale()
    pix = icon.pixmap(QtCore.QSize(20, 20))
    out = QtGui.QPixmap(int(round(20 * scale)), int(round(20 * scale)))
    out.setDevicePixelRatio(scale)
    out.fill(Qt.transparent)
    p = QtGui.QPainter(out)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.drawPixmap(QtCore.QRectF(0, 0, 20, 20), pix, QtCore.QRectF(pix.rect()))
    p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 1))
    p.setBrush(QtGui.QColor(40, 110, 220))
    p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(14.5, 9), QtCore.QPointF(20, 14.5), QtCore.QPointF(17, 14.5),
                                   QtCore.QPointF(17, 20), QtCore.QPointF(12, 20), QtCore.QPointF(12, 14.5),
                                   QtCore.QPointF(9, 14.5)]))
    p.end()
    return QtGui.QIcon(out)


class _KeepEnabled(QtCore.QObject):
    """filedlg2-1119: puts a button Qt greys back to live (Open in the Open box)."""

    def eventFilter(self, obj, event):
        try:
            if event.type() == QtCore.QEvent.EnabledChange and not obj.isEnabled():
                QtCore.QTimer.singleShot(0, lambda o=obj: o.setEnabled(True) if alive_widget(o) else None)
        except Exception as _fw_err:
            _fw_log("saveas.py:keep_open", _fw_err)
        return False


class _SplitArrow(QtCore.QObject):
    """startdlg-1120 Y2: keeps the Open button's arrow at its right end, behind a thin divider."""

    def __init__(self, arrow):
        super().__init__(arrow)
        self.arrow = arrow

    def place(self, button):
        try:
            h = button.height()
            self.arrow.setFixedSize(18, max(10, h - 4))
            self.arrow.move(button.width() - 20, 2)
            self.arrow.raise_()
            self.arrow.show()
        except Exception as _fw_err:
            _fw_log("saveas.py:split_arrow", _fw_err)

    def eventFilter(self, obj, event):
        if event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show):
            self.place(obj)
        return False


def alive_widget(w):
    try:
        w.objectName()
        return True
    except RuntimeError:
        return False


def _version_copy(backup):
    """A previous version (FreeCAD's backup of a document) as a file FreeCAD can open: a copy named for its date."""
    import shutil
    import tempfile
    folder, name = os.path.split(backup)
    stem = name.split(".")[0]
    when = time.strftime("%Y-%m-%d %H%M", time.localtime(os.path.getmtime(backup)))
    target = os.path.join(tempfile.mkdtemp(prefix="fw_versions_"), "%s (%s).FCStd" % (stem, when))
    shutil.copyfile(backup, target)
    return target


class PreviousVersionsDialog(QtWidgets.QDialog):
    ""


    def __init__(self, path, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("FW_PreviousVersions")
        self.setWindowTitle("Previous Versions")
        self.chosen = None
        self.versions = []
        try:
            from . import optionsextras2
            self.versions = sorted(optionsextras2.backups_of(path), key=os.path.getmtime, reverse=True) if path else []
        except Exception as _fw_err:
            _fw_log("saveas.py:versions", _fw_err)
        if not self.versions:
            QtWidgets.QMessageBox.information(parent, "Previous Versions", "%s has no previous versions."
                                              % (os.path.basename(path) if path else "The picked file"))
            return
        self.resize(420, 300)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Previous versions of %s:" % os.path.basename(path)))
        self.list = QtWidgets.QListWidget(self)
        self.list.setObjectName("FW_PreviousVersionsList")
        for v in self.versions:
            item = QtWidgets.QListWidgetItem("%s    %s" % (time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(v))),
                                                           os.path.basename(v)))
            item.setData(Qt.UserRole, v)
            self.list.addItem(item)
        self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())
        lay.addWidget(self.list, 1)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Open | QtWidgets.QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def accept(self):
        item = self.list.currentItem()
        self.chosen = item.data(Qt.UserRole) if item is not None else None
        super().accept()


def open_dialog():
    box = QtWidgets.QFileDialog(Gui.getMainWindow(), "Open")
    box.setObjectName("FW_Open")
    box.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
    box.setDirectory(last_folder())
    _file_types(box)
    box.setFileMode(QtWidgets.QFileDialog.ExistingFiles)
    box.setLabelText(QtWidgets.QFileDialog.FileType, "File type:")
    types = open_types()
    every = sorted({e for _l, exts in types for e in exts})
    filters = ["All Files (*.*)", "All readable files (%s)" % " ".join("*." + e for e in every)] + [t[0] for t in types]
    box.setNameFilters(filters)
    box.selectNameFilter(filters[1])

    try:
        last = paths.params().GetString(OPEN_FILTER, "")
        if last in filters:
            box.selectNameFilter(last)
        box.filterSelected.connect(lambda f: paths.params().SetString(OPEN_FILTER, f))
    except Exception as _fw_err:
        _fw_log("saveas.py:open-filter", _fw_err)
    mode = QtWidgets.QComboBox(box)
    mode.setObjectName("FW_OpenMode")
    mode.addItems(MODES[""])
    mode.setToolTip("Mode")

    box.speedpak = QtWidgets.QCheckBox("Use Speedpak", box)
    box.speedpak.setObjectName("FW_OpenSpeedpak")
    box.speedpak.setToolTip("Sub-assemblies as graphics only: their parts cannot be picked or edited")
    box.skip_hidden = QtWidgets.QCheckBox("Do not load hidden components", box)
    box.skip_hidden.setObjectName("FW_OpenSkipHidden")
    box.skip_hidden.setToolTip("Components hidden when the assembly was saved stay unloaded (suppressed)")

    box.preview = OpenPreview(box)
    box.preview.setObjectName("FW_OpenPreview")
    box.preview.setFixedSize(160, 160)
    box.preview.setAlignment(Qt.AlignCenter)
    box.preview.setFrameShape(QtWidgets.QFrame.StyledPanel)

    box.configurations = QtWidgets.QComboBox(box)
    box.configurations.setObjectName("FW_OpenConfigurations")
    box.configurations.addItem("Default")
    box.display_states = QtWidgets.QComboBox(box)
    box.display_states.setObjectName("FW_OpenDisplayStates")
    box.display_states.addItem("<Default>_Display State 1")
    refs = QtWidgets.QPushButton("References...", box)
    refs.setObjectName("FW_OpenReferences")
    refs.clicked.connect(lambda: ReferencesDialog(_selected_fcstd(box), box).exec())
    filters = QtWidgets.QWidget(box)
    fl = QtWidgets.QHBoxLayout(filters)
    fl.setContentsMargins(0, 0, 0, 0)
    fl.addWidget(QtWidgets.QLabel("Quick Filter:", filters))
    box.quick = {}
    for kind, text in (("part", "Parts"), ("assembly", "Assemblies"), ("drawing", "Drawings"), ("top", "Top-level assemblies")):
        b = QtWidgets.QToolButton(filters)
        b.setObjectName("FW_OpenFilter_" + kind)
        b.setText(text)
        b.setCheckable(True)
        b.setAutoRaise(True)

        b.setIcon(_quick_icon(kind))
        b.setIconSize(QtCore.QSize(20, 20))
        b.setToolButtonStyle(Qt.ToolButtonIconOnly)
        b.setToolTip("Filter " + text)
        b.toggled.connect(lambda on, k=kind: _quick_filter(box))
        fl.addWidget(b)
        box.quick[kind] = b
    fl.addStretch(1)
    box.proxy = _QuickFilterProxy(box)
    box.setProxyModel(box.proxy)
    lay = box.layout()
    box.configurations.currentTextChanged.connect(lambda _t: _fill_display_states(box))
    box._fw_row_labels = (QtWidgets.QLabel("Configuration:", box), QtWidgets.QLabel("Display State:", box))
    if isinstance(lay, QtWidgets.QGridLayout):
        row = lay.rowCount()
        lay.addWidget(QtWidgets.QLabel("Mode:", box), row, 0)
        lay.addWidget(mode, row, 1)
        lay.addWidget(box._fw_row_labels[0], row + 1, 0)
        lay.addWidget(box.configurations, row + 1, 1)
        lay.addWidget(box._fw_row_labels[1], row + 2, 0)
        lay.addWidget(box.display_states, row + 2, 1)
        lay.addWidget(refs, row + 1, 2)
        lay.addWidget(box.speedpak, row, 2)
        lay.addWidget(box.skip_hidden, row + 2, 2)
        lay.addWidget(filters, row + 3, 0, 1, lay.columnCount())
        lay.addWidget(box.preview, 1, lay.columnCount(), 1, 1, Qt.AlignTop)
    box.currentChanged.connect(lambda path: _open_file_picked(box, path))

    # System Options > Import at that type's File Format (shown only for those types, never greyed)
    box.import_options = QtWidgets.QPushButton("Options...", box)
    box.import_options.setObjectName("FW_OpenImportOptions")
    box.import_options.setToolTip("Import options for this file type")
    box.import_options.clicked.connect(lambda: open_import_options(import_format_for(box), box))
    if isinstance(lay, QtWidgets.QGridLayout):
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if isinstance(w, QtWidgets.QComboBox) and w.objectName() == "fileTypeCombo":
                r, c, rs, cs = lay.getItemPosition(i)
                lay.removeWidget(w)
                row = QtWidgets.QWidget(box)
                row.setObjectName("FW_OpenFileTypeRow")
                rl = QtWidgets.QHBoxLayout(row)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.addWidget(w, 1)
                rl.addWidget(box.import_options)
                lay.addWidget(row, r, c, rs, cs)
                break
    box.filterSelected.connect(lambda _f: _follow_import_options(box))
    box.currentChanged.connect(lambda p: (setattr(box, "_fw_picked", p), _follow_import_options(box)))
    box.mode = mode
    box.speedpak.setVisible(False)                 # until an assembly is picked
    box.skip_hidden.setVisible(False)
    for w in (box.configurations, box.display_states, refs) + box._fw_row_labels:
        w.setVisible(False)                        # open110: until a part or assembly is picked

    box.read_only = False
    buttons = box.findChild(QtWidgets.QDialogButtonBox)
    if buttons is not None:

        # button box stands vertical here, so a button of its own landed above Open)
        ok_button = buttons.button(QtWidgets.QDialogButtonBox.Open)
        arrow = QtWidgets.QToolButton(ok_button if ok_button is not None else box)
        arrow.setText("\u25be")
        arrow.setObjectName("FW_OpenArrow")
        arrow.setToolTip("Open choices")
        arrow.setAutoRaise(True)
        arrow.setCursor(Qt.ArrowCursor)
        menu = QtWidgets.QMenu(arrow)

        def go(read_only):
            box.read_only = read_only
            box.accept()
        menu.addAction("Open", lambda: go(False))
        menu.addAction("Open Read-only", lambda: go(True)).setObjectName("FW_OpenReadOnly")

        def previous_versions():

            files = box.selectedFiles()
            path = files[0] if files else ""
            dlg = PreviousVersionsDialog(path, box)
            if dlg.versions and dlg.exec() and dlg.chosen:
                box.previous_version = dlg.chosen
                box.read_only = True
                box.accept()
        menu.addAction("Show previous versions", previous_versions).setObjectName("FW_OpenPreviousVersions")
        if ok_button is not None:
            arrow.clicked.connect(lambda: menu.exec(ok_button.mapToGlobal(QtCore.QPoint(0, ok_button.height()))))
            if not ok_button.objectName():
                ok_button.setObjectName("FW_OpenButton")
            ok_button.setStyleSheet("QPushButton#%s { padding-right: 20px; }" % ok_button.objectName())
            box._fw_split = _SplitArrow(arrow)
            ok_button.installEventFilter(box._fw_split)
            box._fw_split.place(ok_button)
        else:
            arrow.setMenu(menu)
            buttons.addButton(arrow, QtWidgets.QDialogButtonBox.ActionRole)
        box.open_menu = menu
        # filedlg2-1119: the Open button stays live, as in Windows' Open box (Qt greys it until a name is in the
        # File name box; a click with no name does nothing)
        ok = buttons.button(QtWidgets.QDialogButtonBox.Open)
        if ok is not None:
            box._fw_keep_open = _KeepEnabled(ok)
            ok.installEventFilter(box._fw_keep_open)
            ok.setEnabled(True)
    box.accepted.connect(lambda: _remember_choices(box))
    _follow_import_options(box)
    _open_size(box)             # startup-1120 N6
    return box


OPEN_SIZE = "OpenDialogSize"

# opendlg92: the System Options > Import File Format each file type's Options... opens
IMPORT_FORMAT_OF = {e: "STEP/IGES/ACIS" for e in ("step", "stp", "igs", "iges", "sat", "sab", "x_t", "x_b")}
IMPORT_FORMAT_OF.update({e: "Mesh" for e in ("stl", "obj", "off", "ply", "3mf", "amf", "wrl")})


def import_format_for(box):
    """The Import File Format of the picked file, else of the File type shown (None: no import options)."""
    files = [f for f in box.selectedFiles() if os.path.isfile(f)]
    picked = getattr(box, "_fw_picked", "") or ""
    if not files and os.path.isfile(picked):
        files = [picked]        # the file clicked in the list (Windows: selectedFiles can lag behind the click)
    if files:
        fmts = {IMPORT_FORMAT_OF.get(os.path.splitext(f)[1][1:].lower()) for f in files}
        return fmts.pop() if len(fmts) == 1 else None
    exts = [e.lower() for e in re.findall(r"\*\.(\w+)", box.selectedNameFilter())]
    fmts = {IMPORT_FORMAT_OF.get(e) for e in exts}
    if not exts:
        return None
    return fmts.pop() if len(fmts) == 1 else None


def _follow_import_options(box):
    try:
        box.import_options.setVisible(import_format_for(box) is not None)
    except Exception as _fw_err:
        _fw_log("saveas.py:_follow_import_options", _fw_err)


def open_import_options(fmt, parent=None, run=True):
    ""
    from . import options as optionsdlg
    od = optionsdlg.OptionsDialog(tab=0)
    od.select("Import")
    try:
        page = od.stack.currentWidget()
        pick = page.findChild(QtWidgets.QComboBox, "SWFileFormat_ImportFileFormat")
        if pick is not None and fmt:
            pick.setCurrentText(fmt)
    except Exception as _fw_err:
        _fw_log("saveas.py:open_import_options", _fw_err)
    if run:
        od.exec()
    return od


def _open_size(box):
    """startup-1120 N6: Open opens wide enough for its columns (about 55% x 62% of the screen) and keeps the
    size it was last left at."""
    try:
        w, h = [int(v) for v in paths.params().GetString(OPEN_SIZE, "").split("x")]
    except Exception:
        w = h = 0
    try:
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        sw, sh = screen.width(), screen.height()
    except Exception:
        sw, sh = 1920, 1040
    if w < 400 or h < 300:
        w, h = int(sw * 0.55), int(sh * 0.62)
    box.resize(min(w, sw), min(h, sh))
    box.finished.connect(lambda _r: paths.params().SetString(OPEN_SIZE, "%dx%d" % (box.width(), box.height())))
    _open_columns(box)


SAVE_SIZE = "SaveDialogSize"


def _save_size(box):
    """lookaudit-1120 AB1: Save As opens wide enough for its columns (Qt's 629x412 cut them to "29....KiB",
    "Zip...ive") and keeps the size it was last left at, as Open does (startup-1120 N6)."""
    try:
        w, h = [int(v) for v in paths.params().GetString(SAVE_SIZE, "").split("x")]
    except Exception:
        w = h = 0
    try:
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        sw, sh = screen.width(), screen.height()
    except Exception:
        sw, sh = 1920, 1040
    if w < 400 or h < 300:
        w, h = int(sw * 0.55), int(sh * 0.62)
    box.resize(min(w, sw), min(h, sh))
    box.finished.connect(lambda _r: paths.params().SetString(SAVE_SIZE, "%dx%d" % (box.width(), box.height())))
    _open_columns(box)


def _open_columns(box):
    """startup-1120 N6b: the Details columns are wide enough for what they show (Qt keeps its narrow
    defaults whatever the box's size, so Size and Type read "13....KiB", "Zip...ive"); Name takes the rest,
    as in the Windows Open box."""
    try:
        view = box.findChild(QtWidgets.QTreeView, "treeView")
        if view is None:
            return
        head = view.header()
        fm = view.fontMetrics()
        pad = 2 * fm.height()
        widths = {1: fm.horizontalAdvance("999.9 KiB") + pad,
                  2: fm.horizontalAdvance("FreeCAD Assembly Document") + pad,     # opentype-1121: the longest Type name
                  3: fm.horizontalAdvance("20 Nov 2026 23:59:59") + pad}
        split = box.findChild(QtWidgets.QSplitter, "splitter")
        if split is not None and split.count() == 2:       # the places list: names whole ("Computer")
            side = fm.horizontalAdvance("Computer") + 4 * fm.height()
            split.setSizes([side, max(200, split.width() - side)])
        head.setStretchLastSection(False)
        head.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for col, width in widths.items():
            if col < head.count():
                head.setSectionResizeMode(col, QtWidgets.QHeaderView.Interactive)
                head.resizeSection(col, width)
    except Exception as _fw_err:
        _fw_log("saveas.py:_open_columns", _fw_err)


OPEN_FILTER = "OpenLastFileType"
_PENDING = {}       # path -> (configuration, display state, read-only) picked in the Open dialog


def _remember_choices(box):
    """Open's choices, kept for the files picked: whichever opener runs (asmldr wraps this one) applies them."""
    _PENDING.clear()
    files = box.selectedFiles()
    one = len(files) == 1
    for p in files:
        _PENDING[os.path.normcase(os.path.abspath(p))] = (box.configurations.currentText() if one else None,
                                                          box.display_states.currentText() if one else None,
                                                          bool(getattr(box, "read_only", False)))


def _selected_fcstd(box):
    files = box.selectedFiles()
    path = files[0] if files else ""
    return path if path.lower().endswith(".fcstd") and os.path.isfile(path) else ""


def detailing_by_default():
    """System Options > Drawings > Performance > Open drawings in Detailing mode by default."""
    try:
        from . import drawings
        return bool(drawings.system_option("Performance", "Open drawings in Detailing mode by default", False))
    except Exception:
        return False



MODES = {"": ["Resolved"], "part": ["Quick View", "Resolved"],
         "assembly": ["Quick View", "Resolved", "Lightweight", "Large Design Review"],
         "drawing": ["Resolved", "Detailing"]}
OPEN_MODE = "SWOpenMode"            # doc.Meta: Lightweight / Large Design Review (chrome shows it)


def _preview_base():
    """tessave.PreviewWidget (features/110: the saved display mesh, turned with the mouse) when it is
    there, else a plain label."""
    try:
        from . import tessave
        if tessave.PreviewWidget is not None:
            return tessave.PreviewWidget
    except Exception as _fw_err:
        _fw_log("saveas.py:1333", _fw_err)
    return None


class OpenPreview((_preview_base() or QtWidgets.QLabel)):
    ""


    def __init__(self, parent=None):
        if _preview_base() is not None:
            super().__init__("", parent, (160, 160))
        else:
            super().__init__(parent)
        self.live = False
        self.setText("")

    def show_model(self, path):
        """True when the file's saved tessellation is shown (and now turns with the mouse)."""
        if _preview_base() is None or not path:
            self.live = False
            return False
        try:
            self.live = bool(self.set_path(path))
        except Exception:
            self.live = False
        if not self.live:
            self.setText("")
        return self.live

    def mousePressEvent(self, event):
        if self.live:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.live:
            super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.live:
            super().mouseDoubleClickEvent(event)


def _open_file_picked(box, path):
    """A file picked in the list: its kind sets the Mode list, its configurations and display states
    fill the combos, and its saved model or thumbnail the preview (tessave, fcstdinfo)."""
    box.configurations.clear()
    box.display_states.clear()
    info = None
    if path and path.lower().endswith(".fcstd"):
        try:
            from . import fcstdinfo
            info = fcstdinfo.info(path)
        except Exception:
            info = None
    kind = (info or {}).get("kind", "")
    want = MODES.get(kind, MODES[""])
    have = [box.mode.itemText(i) for i in range(box.mode.count())]
    if have != want:
        keep = box.mode.currentText()
        box.mode.clear()
        box.mode.addItems(want)
        if keep in want:
            box.mode.setCurrentText(keep)
        elif "Resolved" in want:
            box.mode.setCurrentText("Resolved")     # extapps90: Quick View is listed first, Resolved is the default
        if kind == "drawing" and detailing_by_default():
            box.mode.setCurrentText("Detailing")
    box.speedpak.setEnabled(kind == "assembly")
    box.skip_hidden.setEnabled(kind == "assembly")
    box.speedpak.setVisible(kind == "assembly")       # shown only where they apply (no greyed boxes)
    box.skip_hidden.setVisible(kind == "assembly")
    is_fcstd = bool(path) and path.lower().endswith(".fcstd")
    shown = False
    if is_fcstd:
        try:
            shown = box.preview.show_model(path)
        except Exception:
            shown = False
    if not shown:
        try:
            from PySide import QtGui
            from . import fcstdinfo
            data = fcstdinfo.thumbnail(path) if is_fcstd else b""
            pix = QtGui.QPixmap()
            if data and pix.loadFromData(data):
                scale = _screen_scale()
                pix = pix.scaled(box.preview.size() * scale, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                pix.setDevicePixelRatio(scale)          # sharp at 175 %
                box.preview.setPixmap(pix)
            else:
                box.preview.setPixmap(QtGui.QPixmap())
                box.preview.setText("No preview" if path else "")
        except Exception as _fw_err:
            _fw_log("saveas.py:1419", _fw_err)
    box.configurations.addItems(info["configurations"] if info else ["Default"])
    box._fw_info = info
    _fill_display_states(box)

    # for a document that references other files; nothing picked, a drawing or another file type: not shown
    model = kind in ("part", "assembly")
    for w in (box.configurations, box.display_states) + tuple(getattr(box, "_fw_row_labels", ())):
        w.setVisible(model)
    refs = box.findChild(QtWidgets.QPushButton, "FW_OpenReferences")
    if refs is not None:
        refs.setVisible(bool(info and info.get("references")))


def _fill_display_states(box):
    ""

    info = getattr(box, "_fw_info", None) or {}
    states = list(info.get("display_states") or [])
    cfg_of = info.get("display_state_configs") or {}
    config = box.configurations.currentText()
    mine = [s for s in states if not cfg_of.get(s) or cfg_of.get(s) == config]
    box.display_states.blockSignals(True)
    box.display_states.clear()
    box.display_states.addItems(mine or states or ["<Default>_Display State 1"])
    box.display_states.blockSignals(False)


class _QuickFilterProxy(QtCore.QSortFilterProxyModel):
    """Quick Filter: only the FCStd files of the kinds ticked (folders always show)."""

    def __init__(self, box):
        super().__init__(box)
        self.kinds = set()

    def filterAcceptsRow(self, row, parent):
        if not self.kinds:
            return True
        model = self.sourceModel()
        index = model.index(row, 0, parent)
        try:
            if model.isDir(index):
                return True
            path = model.filePath(index)
        except Exception:
            return True
        if not path.lower().endswith(".fcstd"):
            return False
        from . import fcstdinfo
        kind = fcstdinfo.kind(path)
        if kind in self.kinds:
            return True
        if "top" in self.kinds and kind == "assembly":
            folder = os.path.dirname(path)
            try:
                others = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".fcstd")]
            except OSError:
                others = []
            return fcstdinfo.is_top_level(path, others)
        return False


def _quick_filter(box):
    box.proxy.kinds = {k for k, b in box.quick.items() if b.isChecked()}
    box.proxy.invalidateFilter()


class ReferencesDialog(QtWidgets.QDialog):
    ""

    redirects = {}      # original path -> new path, read by open_file

    def __init__(self, path, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("FW_OpenReferences")
        self.setWindowTitle("Edit Referenced File Locations")
        self.resize(620, 300)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel(path or "Pick a document in the list first.", self))
        self.table = QtWidgets.QTableWidget(0, 3, self)
        self.table.setObjectName("FW_OpenReferenceTable")
        self.table.setHorizontalHeaderLabels(["Name", "In folder", "New path"])
        self.table.horizontalHeader().setStretchLastSection(True)
        refs = []
        if path:
            try:
                from . import fcstdinfo
                refs = (fcstdinfo.info(path) or {}).get("references", [])
            except Exception:
                refs = []
        for r in refs:
            i = self.table.rowCount()
            self.table.insertRow(i)
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(os.path.basename(r)))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(os.path.dirname(r)))
            self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(self.redirects.get(r, "")))
            self.table.item(i, 0).setData(Qt.UserRole, r)
        lay.addWidget(self.table, 1)
        if not refs:
            lay.addWidget(QtWidgets.QLabel("This document references no other files.", self))
        row = QtWidgets.QHBoxLayout()
        browse = QtWidgets.QPushButton("Browse...", self)
        browse.setObjectName("FW_OpenReferenceBrowse")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        row.addStretch(1)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        lay.addLayout(row)

    def _browse(self):
        r = self.table.currentRow()
        if r < 0:
            return
        path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Referenced file", self.table.item(r, 1).text(), "FreeCAD files (*.FCStd)")
        if path:
            self.table.item(r, 2).setText(path)

    def accept(self):
        for r in range(self.table.rowCount()):
            old = self.table.item(r, 0).data(Qt.UserRole)
            new = self.table.item(r, 2).text().strip()
            if new:
                self.redirects[old] = new
            else:
                self.redirects.pop(old, None)
        super().accept()


def _native(path):
    """save116: a FreeCAD file: .FCStd, and its backups (.FCBak, .FCStd1...), which are FreeCAD files too."""
    low = path.lower()
    return low.endswith(".fcstd") or low.endswith(".fcbak") or re.search(r"\.fcstd\d+$", low) is not None


def missing_parts(path):
    """save116: the files Document.xml points at (shapes, ...) that are not in the .FCStd: [names]."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            xml = z.read("Document.xml").decode("utf-8", "replace")
    except Exception:
        return []
    wanted = re.findall(r'<(?!XLink\b)\w+\b[^>]*?\sfile="([^"]+)"', xml)
    return sorted({w for w in wanted if w and w not in names})


def _tell_missing_parts(path):
    """save116: a file whose shape data is missing opened as an empty model with no word: say it is damaged."""
    gone = missing_parts(path)
    if not gone:
        return
    msg = ("Some of %s could not be read: the file is damaged (%d of its parts %s missing). Keep what was read "
           "with Save As under a new name." % (os.path.basename(path), len(gone), "is" if len(gone) == 1 else "are"))
    App.Console.PrintWarning("FreeCAD: %s Missing: %s\n" % (msg, ", ".join(gone)))
    try:
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Open", msg)
    except Exception as _fw_err:
        _fw_log("saveas.py:missing-parts", _fw_err)


def open_file(path, mode="Resolved", speedpak=False, skip_hidden=False, configuration=None, display_state=None,
              read_only=False):
    if mode == "Quick View":
        mode, read_only = "Resolved", True
    picked = _PENDING.pop(os.path.normcase(os.path.abspath(path)), None)
    if picked is not None:
        configuration = configuration or picked[0]
        display_state = display_state or picked[1]
        read_only = read_only or picked[2]
    if _native(path):
        _same_name_open(path)
    if _native(path) and os.path.isfile(path) and _read_only_on_disk(path):
        read_only = True        # refs129: a file read-only on disk opens read-only (Save says so, Save As works)
    doc = _open_file(path, mode, speedpak, skip_hidden)
    if doc is not None and _native(path):
        _open_choices(doc, configuration, display_state, read_only)
        _tell_missing_parts(path)
        _missing_models(doc, path)
    if doc is not None:
        try:
            from . import cleanopen
            cleanopen.recent_add(os.path.abspath(path))
            remember_folder(path)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: recent documents: %s\n" % error)
    if doc is not None and doc.Name in _STEP_ASM:
        _STEP_ASM.discard(doc.Name)
        _up_to_date(doc)
        QtCore.QTimer.singleShot(500, lambda n=doc.Name: _up_to_date(App.listDocuments().get(n)))
    return doc


_STEP_ASM = set()        # imp144: documents just made assemblies from a STEP file


def _up_to_date(doc):
    """A STEP assembly just made: its links and bodies are touched once more as the assembly settles; rebuilt
    then, so it is saved up to date (no Rebuild question when it is opened again)."""
    if doc is None:
        return
    for _i in range(3):
        if not [o for o in doc.Objects if "Touched" in o.State and o.TypeId != "Assembly::AssemblyObject"]:
            break
        doc.recompute()


def _same_name_open(path):
    ""

    me = os.path.normcase(os.path.abspath(path))
    name = os.path.basename(path).lower()
    for d in App.listDocuments().values():
        f = getattr(d, "FileName", "") or ""
        if f and os.path.basename(f).lower() == name and os.path.normcase(os.path.abspath(f)) != me:
            raise RuntimeError("A document with the same name is already open, from %s. Close it, then open this "
                               "one" % os.path.dirname(os.path.abspath(f)))


def newer_version(path):
    """fh162: the FreeCAD version a .FCStd was saved with, "1.3", when it is newer than this FreeCAD; else ""."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            with z.open("Document.xml") as f:
                head = f.read(4096).decode("utf-8", "replace")
        m = re.search(r'ProgramVersion="(\d+)\.(\d+)', head)
        if not m:
            return ""
        mine = (int(App.Version()[0]), int(App.Version()[1]))
        theirs = (int(m.group(1)), int(m.group(2)))
        return "%d.%d" % theirs if theirs > mine else ""
    except Exception:
        return ""


def _opened_newer(doc, path):
    ""

    newer = newer_version(path)
    if not newer:
        return
    try:
        from . import filecmds
        filecmds.set_read_only(doc, True)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s could not be made read-only: %s\n" % (doc.Label, error))
    v = App.Version()
    text = ("%s was saved with a newer FreeCAD (%s). This FreeCAD (%s.%s) may not read all of it.\n\nIt was opened "
            "read-only so that Save cannot write over it. Use File > Save As to keep a copy for this version."
            % (os.path.basename(path), newer, v[0], v[1]))
    App.Console.PrintWarning("FreeCAD: %s\n" % text.replace("\n\n", " "))
    QtCore.QTimer.singleShot(0, lambda: _tell_damaged(text))


def _read_only_on_disk(path):
    import stat
    try:
        return not os.access(path, os.W_OK) or not (os.stat(path).st_mode & stat.S_IWUSR)
    except OSError:
        return False


def drawing_models(path):
    """refs129: {view name: [(stored file, object name)]} of a drawing's views, from the saved file."""
    import zipfile
    out = {}
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("Document.xml").decode("utf-8", "replace")
    except Exception:
        return out
    for m in re.finditer(r'<Object name="([^"]+)"[^>]*>(.*?)</Object>', xml, re.S):
        x = re.search(r'<Property name="XSource"[^>]*>(.*?)</Property>', m.group(2), re.S)
        if x:
            refs = re.findall(r'<XLink file="([^"]+)"[^>]*name="([^"]+)"', x.group(1))
            if refs:
                out[m.group(1)] = refs
    return out


def _missing_models(doc, path):
    ""

    if not any(o.TypeId.startswith("TechDraw::") for o in doc.Objects):
        return None
    base = os.path.dirname(path)
    lost = {}
    for view, refs in drawing_models(path).items():
        v = doc.getObject(view)
        if v is None or list(getattr(v, "XSource", []) or []):
            continue
        for stored, name in refs:
            full = os.path.normpath(stored if os.path.isabs(stored) else os.path.join(base, stored))
            if not os.path.isfile(full):
                lost.setdefault(full, []).append((v, name))
    if not lost or not App.GuiUp:
        return lost or None

    QtCore.QTimer.singleShot(1200, lambda n=doc.Name, l=lost: _ask_missing_models(n, l))
    return lost


def _ask_missing_models(name, lost):
    doc = App.listDocuments().get(name)
    if doc is None:
        return
    for full, views in lost.items():
        msg = ("The model of %s was not found:\n%s\n\nIt may have been moved, renamed or deleted. "
               "Browse to it?" % (doc.Label, full))
        if QtWidgets.QMessageBox.question(Gui.getMainWindow(), "File Not Found", msg,
                                          QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
            continue
        pick, _f = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Open", os.path.dirname(full),
                                                         "FreeCAD files (*.FCStd)")
        if pick:
            relink_drawing(doc, views, pick)
    return lost


def relink_drawing(doc, views, pick):
    """refs129: [(view, object name)] of doc onto the same objects in the file pick; True when any moved."""
    model = next((d for d in App.listDocuments().values() if d.FileName and os.path.isfile(d.FileName)
                  and os.path.samefile(d.FileName, pick)), None) or App.openDocument(pick, True)
    done = False
    doc.openTransaction("Browse to the model")      # an undo step: the open's settling leaves it changed
    try:
        for v, name in views:
            obj = model.getObject(name)
            if obj is None:
                continue
            v.XSource = list(v.XSource) + [obj]
            done = True
    finally:
        doc.commitTransaction()
    if done:
        doc.recompute()
        try:
            Gui.getDocument(doc.Name).Modified = True     # Save keeps the model's new place
        except Exception as _fw_err:
            _fw_log("saveas.py:relink-drawing", _fw_err)
    return done


def _open_choices(doc, configuration, display_state, read_only):
    """Open's Configurations and Display States picks, and Open as read-only, on the opened document."""
    if configuration:
        try:
            from . import configmanager
            t = configmanager.table(doc)
            if t is not None and configuration in t.names() and t.active() != configuration:
                configmanager.show(t, configuration)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: open in configuration %s: %s\n" % (configuration, error))
    if display_state:
        try:
            from . import displaystates
            if display_state in displaystates.names(doc) and displaystates.active(doc) != display_state:
                displaystates.activate(doc, display_state)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: open in display state %s: %s\n" % (display_state, error))
    if read_only:
        try:
            from . import filecmds
            filecmds.set_read_only(doc, True)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: open read-only: %s\n" % error)


def _open_file(path, mode="Resolved", speedpak=False, skip_hidden=False):
    """Opens path the way FreeCAD's Open does for its type (a document, or an import into a new one).
    mode Detailing opens a drawing without updating its views from the models (drawdocprops.open_detailing);
    Lightweight opens an assembly without recomputing it; Large Design Review also makes it read-only.
    speedpak: sub-assemblies become graphics only; skip_hidden: hidden components are suppressed."""
    if not os.path.isfile(path):
        raise FileNotFoundError("The file was not found. It may have been moved, renamed or deleted.")
    if _native(path):
        import zipfile
        if os.path.getsize(path) == 0 or not zipfile.is_zipfile(path):
            raise RuntimeError("The file is damaged or is not a FreeCAD file.")
        _n, _why = damage(path)
        if _why and _n == 0:
            raise RuntimeError("The file is damaged or is not a FreeCAD file.")     # dmg151: nothing in it can be read
    if _native(path):
        # References...: a redirected file is opened first, so the link finds it already open
        try:
            from . import fcstdinfo
            for ref in (fcstdinfo.info(path) or {}).get("references", []):
                new = ReferencesDialog.redirects.get(ref)
                if new and os.path.isfile(new) and not any(d.FileName == new for d in App.listDocuments().values()):
                    App.openDocument(new, True)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: references: %s\n" % error)
        if mode == "Detailing":
            try:
                from . import drawdocprops
                return drawdocprops.open_detailing(path)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: Detailing mode: %s\n" % error)
        doc = App.openDocument(path)
        if mode in ("Lightweight", "Large Design Review") or speedpak or skip_hidden:
            _open_as(doc, mode, speedpak, skip_hidden)
        return doc
    import importlib
    ext = os.path.splitext(path)[1][1:]
    mods = App.getImportType(ext) or App.getImportType(ext.lower()) or []
    if not mods:
        raise RuntimeError(NO_READER.get(ext.lower(), "FreeCAD has no reader for .%s files") % ext)
    if ext.lower() in ("igs", "iges", "step", "stp", "brep", "brp"):
        # ImportGui can leave an IGES file's document empty; Part reads the shape then
        mods = list(mods) + ["Part"]
    if ext.lower() in MESH_READ and "Mesh" in mods:

        # reader was listed first (PC test: Block.obj came in 25.4 times too small) Mesh now reads it
        mods = ["Mesh"] + [m for m in mods if m != "Mesh"]
    error = None
    for name in dict.fromkeys(mods):
        before = set(App.listDocuments())
        got = error_here = None
        try:
            got = importlib.import_module(name).open(path)
        except Exception as e:
            error = error_here = e
        if name == "importDXF" and _dxf_box_glitch(error_here) and not (set(App.listDocuments()) - before):
            # fh169: FreeCAD's DXF Import box now and then fails to build on the first DXF of a session
            # ("'QWidgetItem' object has no attribute ..."); a second try works: tried again once, unseen
            App.Console.PrintLog("FreeCAD: DXF Import box failed to build (%s); trying again\n" % error_here)
            got = error_here = None
            try:
                got = importlib.import_module(name).open(path)
            except Exception as e:
                error = error_here = e
        new = set(App.listDocuments()) - before
        if not new and name == "importDXF" and got is None and error_here is None:
            # fh166: Cancel in the DXF Import box: nothing is opened and nothing is said (it said the file could
            # not be read)
            return None
        if not new:
            continue
        doc = App.getDocument(new.pop())
        if name == "importDXF":
            _close_import_step("DXF Post-processing")
        if not doc.Objects:
            App.closeDocument(doc.Name)
            continue
        if _read_nothing(doc):
            # open125 (Reviewer): an STL with no triangles opened as an empty "Unnamed" document, no word said
            App.closeDocument(doc.Name)
            kind = "triangles" if ext.lower() in MESH_READ else "shapes"
            raise RuntimeError("The file has no %s in it. It may be empty or damaged." % kind)
        doc.Label = os.path.splitext(os.path.basename(path))[0]
        doc.recompute()
        if ext.lower() in ("igs", "iges", "step", "stp"):
            _file_units(doc, path)
        if ext.lower() in ("step", "stp"):
            try:
                if as_assembly(doc):        # imp144: a STEP assembly opens as an assembly of its parts
                    _STEP_ASM.add(doc.Name)
                    doc.recompute()
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: the STEP assembly is shown as it was read (%s)\n" % error)
        Gui.SendMsgToActiveView("ViewFit")
        return doc
    raise RuntimeError(str(error or "nothing was read from the file"))


def _dxf_box_glitch(error):
    """fh169: the error FreeCAD's DXF Import box gives when it fails to build (upstream, intermittent)."""
    return isinstance(error, AttributeError) and "QWidgetItem" in str(error)


def _close_import_step(title):
    ""

    try:
        active = App.getActiveTransaction()
        if active and active[0] == title:
            App.closeActiveTransaction()
    except Exception as _fw_err:
        _fw_log("saveas.py:import-step", _fw_err)


# sw158: files made by other CAD programs that FreeCAD cannot read, with what to do instead
_AS_STEP = "Save it as STEP (*.step) or IGES (*.igs) in the program that made it, then open that file here"
NO_READER = {
    "sldprt": "FreeCAD cannot read .%s part files. " + _AS_STEP,
    "sldasm": "FreeCAD cannot read .%s assembly files. Save the assembly as STEP (*.step) in the program that made "
              "it (one file with all its parts), then open that file here",
    "slddrw": "FreeCAD cannot read .%s drawing files. Save the drawing as DXF (*.dxf) or PDF (*.pdf), and its model "
              "as STEP (*.step), in the program that made them; open the STEP file here, or the DXF with File > Open",
    "x_t": "FreeCAD cannot read Parasolid (.%s) files. " + _AS_STEP,
    "x_b": "FreeCAD cannot read Parasolid (.%s) files. " + _AS_STEP,
    "sat": "FreeCAD cannot read ACIS (.%s) files. " + _AS_STEP,
    "sab": "FreeCAD cannot read ACIS (.%s) files. " + _AS_STEP,
    "ipt": "FreeCAD cannot read .%s part files. " + _AS_STEP,
    "iam": "FreeCAD cannot read .%s assembly files. " + _AS_STEP,
    "catpart": "FreeCAD cannot read .%s part files. " + _AS_STEP,
    "f3d": "FreeCAD cannot read .%s files. " + _AS_STEP,
    "prt": "FreeCAD cannot read .%s part files. " + _AS_STEP,
    "par": "FreeCAD cannot read .%s part files. " + _AS_STEP,
}


MESH_READ = ("stl", "ast", "bms", "obj", "off", "ply", "3mf", "amf", "smf")

# imp144: the unit a STEP or IGES file was written in -> the document's unit system (unitspage.SYSTEMS / LENGTHS)
FILE_UNIT_SCHEMA = {"mm": 0, "cm": 4, "m": 1, "in": 3, "ft": 7}
IGES_UNIT_FLAGS = {1: "in", 2: "mm", 4: "ft", 6: "m", 10: "cm"}


def _iges_params(text):
    """The IGES Global section's parameters (strings in nH form read as they are)."""
    delim, end = ",", ";"
    if text.startswith("1H"):
        delim = text[2]
        rest = text[3:].lstrip(delim)
        if rest.startswith("1H"):
            end = rest[2]
    out, i, cur = [], 0, ""
    while i < len(text):
        m = re.match(r"\s*(\d+)H", text[i:])
        if m and not cur.strip():
            n = int(m.group(1))
            start = i + m.end()
            cur = text[start:start + n]
            i = start + n
            continue
        ch = text[i]
        if ch in (delim, end):
            out.append(cur.strip())
            cur = ""
            if ch == end:
                break
        else:
            cur += ch
        i += 1
    return out


def file_length_unit(path):
    """"in", "mm", "cm", "m" or "ft": the length unit a STEP or IGES file says it was written in, None when unknown."""
    ext = os.path.splitext(path)[1].lower()
    try:
        with open(path, "r", errors="replace") as f:
            head = f.read(2000000)
    except OSError:
        return None
    if ext in (".step", ".stp"):
        m = re.search(r"CONVERSION_BASED_UNIT\s*\(\s*'(INCH|FOOT)'", head, re.I)
        if m:
            return "in" if m.group(1).upper() == "INCH" else "ft"
        for rx, unit in ((r"SI_UNIT\s*\(\s*\.MILLI\.\s*,\s*\.METRE\.", "mm"),
                         (r"SI_UNIT\s*\(\s*\.CENTI\.\s*,\s*\.METRE\.", "cm"),
                         (r"SI_UNIT\s*\(\s*\$\s*,\s*\.METRE\.", "m")):
            if re.search(rx, head):
                return unit
        return None
    lines = [ln[:72] for ln in head.splitlines() if len(ln) > 72 and ln[72] == "G"]
    params = _iges_params("".join(lines))
    try:
        return IGES_UNIT_FLAGS.get(int(float(params[13])))
    except (IndexError, ValueError):
        return None


def _file_units(doc, path):
    ""

    unit = file_length_unit(path)
    schema = FILE_UNIT_SCHEMA.get(unit)
    if schema is None or not hasattr(doc, "UnitSystem"):
        return
    try:
        from . import unitspage
        if unitspage.length_unit(doc)[0] == unit:
            return
        doc.UnitSystem = doc.getEnumerationsOfProperty("UnitSystem")[schema]
        if App.ActiveDocument is doc:
            App.Units.setSchema(schema)
    except Exception as _fw_err:
        _fw_log("saveas.py:_file_units", _fw_err)


_CONTAINERS = ("App::LinkGroup", "App::Part")


def _kids(o):
    if o.TypeId == "App::LinkGroup":
        return list(o.ElementList)
    if o.TypeId == "App::Part":
        return [k for k in o.Group if not k.isDerivedFrom("App::Origin")]
    return []


def _step_tree(o, place):
    """[(kind, source, placement, label)] of a container's children: ("part", shape owner) or ("asm", container)."""
    out = []
    for k in _kids(o):
        if k.TypeId == "App::Link":
            target = k.getLinkedObject(True)
            pl = place.multiply(k.Placement)
            if getattr(k, "LinkTransform", False):
                pl = pl.multiply(target.Placement)
            if target.TypeId in _CONTAINERS:
                out.append(("asm", target, pl, k.Label))
            elif hasattr(target, "Shape") and not target.Shape.isNull():
                out.append(("part", target, pl, k.Label))
        elif k.TypeId in _CONTAINERS:
            out.append(("asm", k, place.multiply(k.Placement), k.Label))
        elif k.isDerivedFrom("Part::Feature") and not k.Shape.isNull() and (k.Shape.Faces or k.Shape.Edges):
            out.append(("part", k, place.multiply(k.Placement), k.Label))
    return out


def _step_roots(doc):
    return [o for o in doc.Objects if o.TypeId in _CONTAINERS and not [p for p in o.InList if p.TypeId in _CONTAINERS]
            and not [p for p in o.InList if p.TypeId == "App::Link"]]


def _copy_look(src, dst):
    try:
        a, b = src.ViewObject, dst.ViewObject
        if a is None or b is None:
            return
        for prop in ("ShapeAppearance", "DiffuseColor", "ShapeColor", "LineColor", "Transparency"):
            if hasattr(a, prop) and hasattr(b, prop):
                try:
                    setattr(b, prop, getattr(a, prop))
                except Exception:
                    pass
    except Exception as _fw_err:
        _fw_log("saveas.py:_copy_look", _fw_err)


def as_assembly(doc):
    ""




    roots = _step_roots(doc)
    if len(roots) != 1:
        return False
    root = roots[0]
    tree = _step_tree(root, App.Placement())
    if len(tree) < 2 and not any(k == "asm" for k, _s, _p, _l in tree):
        return False
    from . import asmcore as ac, asminsert
    old = [o.Name for o in doc.Objects]
    parts, subs = {}, {}

    def part_body(src):
        if src.Name in parts:
            return parts[src.Name]
        name = re.sub(r"\d{3}$", "", src.Label) or src.Label      # Body001: FreeCAD's second "Body"
        if any(b.Label.split("^")[0] == name for b in parts.values()):
            name = src.Label
        feat = doc.addObject("Part::Feature", "Imported")
        shape = src.Shape.copy()
        shape.Placement = App.Placement()
        feat.Shape = shape
        feat.Label = "Imported%d" % (len(parts) + 1)
        body = doc.addObject("PartDesign::Body", "Body")
        body.BaseFeature = feat
        body.Label = "%s^%s" % (name, doc.Label)
        _copy_look(src, feat)
        _copy_look(src, body)
        for o in (feat, body):
            try:
                o.ViewObject.Visibility = False
            except Exception:
                pass
        parts[src.Name] = body
        return body

    def virtual(asm, link):
        if not hasattr(link, asminsert.VIRTUAL_PROP):
            link.addProperty("App::PropertyBool", asminsert.VIRTUAL_PROP, "FreeCAD", "Virtual component (kept in the assembly)")
            link.setEditorMode(asminsert.VIRTUAL_PROP, 2)
        setattr(link, asminsert.VIRTUAL_PROP, True)
        link.Label = asminsert._instance(asm, "[%s]" % link.LinkedObject.Label, link)

    def fill(asm, items):
        for kind, src, pl, _label in items:
            if kind == "part":
                target = part_body(src)
            else:
                target = subs.get(src.Name)
                if target is None:
                    from . import asmcomp
                    target = asmcomp.virtual_assembly(doc)
                    subs[src.Name] = target
                    fill(target, _step_tree(src, App.Placement()))
            link = ac.insert(asm, target, pl)
            link.Placement = pl
            virtual(asm, link)

    top = ac.make_assembly(doc)
    fill(top, tree)
    for name in reversed(old):
        o = doc.getObject(name)
        if o is not None and o.TypeId in _CONTAINERS + ("App::Link",):
            doc.removeObject(name)
    for name in reversed(old):
        o = doc.getObject(name)
        if o is not None and not [p for p in o.InList if p.Document is doc]:
            doc.removeObject(name)
    return True


def _read_nothing(doc):
    """open125: True when an import made objects but no triangles or geometry in any of them."""
    for o in doc.Objects:
        m = getattr(o, "Mesh", None)
        if m is not None and getattr(m, "CountFacets", 0):
            return False
        sh = getattr(o, "Shape", None)
        if sh is not None and not sh.isNull() and (sh.Faces or sh.Edges or sh.Vertexes):
            return False
        if m is None and sh is None:
            return False                # something we do not judge (a sheet, a spreadsheet): keep it
    return True


def _links(doc):
    return [o for o in doc.Objects if o.TypeId in ("App::Link", "App::LinkGroup") or o.isDerivedFrom("App::LinkBaseExtension")]


def _open_as(doc, mode, speedpak, skip_hidden):
    ""
    meta = dict(doc.Meta or {})
    if mode in ("Lightweight", "Large Design Review"):
        meta[OPEN_MODE] = mode
    if skip_hidden:
        # hidden when saved: suppressed, so they are not loaded into the recompute
        names = []
        for o in _links(doc):
            try:
                if o.ViewObject is not None and not o.ViewObject.Visibility:
                    o.purgeTouched()                 # left as saved: no recompute, no load of its shape
                    names.append(o.Name)
            except Exception as _fw_err:
                _fw_log("saveas.py:1644", _fw_err)
        meta["SWOpenSkippedHidden"] = ",".join(names)
    if speedpak:
        names = []
        for o in _links(doc):
            try:
                target = getattr(o, "LinkedObject", None)
                if target is not None and target.TypeId == "Assembly::AssemblyObject":
                    o.ViewObject.Selectable = False
                    names.append(o.Name)
            except Exception as _fw_err:
                _fw_log("saveas.py:1655", _fw_err)
        meta["SWOpenSpeedpak"] = ",".join(names)
    doc.Meta = meta
    if mode == "Large Design Review":

        for o in doc.Objects:
            for prop in o.PropertiesList:
                try:
                    o.setPropertyStatus(prop, "ReadOnly")
                except Exception as _fw_err:
                    _fw_log("saveas.py:1665", _fw_err)
    if mode in ("Lightweight", "Large Design Review"):
        try:
            for o in doc.Objects:
                o.purgeTouched()
        except Exception as _fw_err:
            _fw_log("saveas.py:1671", _fw_err)


def open_mode(doc=None):
    """The mode a document was opened in: '', 'Lightweight' or 'Large Design Review'."""
    doc = doc or App.ActiveDocument
    try:
        mode = dict(doc.Meta or {}).get(OPEN_MODE, "") if doc is not None else ""
    except Exception:
        mode = ""
    if not mode and doc is not None:
        try:
            from . import asmldr        # the Open dialog's assembly modes are asmldr's now: it knows a review
            if asmldr.is_ldr(doc):
                mode = "Large Design Review"
        except Exception as error:
            App.Console.PrintLog("Open mode: review state not read: %s\n" % error)
    return mode


def open_files(paths_=None, mode="Resolved", speedpak=False, skip_hidden=False, configuration=None,
               display_state=None, read_only=False):
    if paths_ is None:
        box = open_dialog()
        if not box.exec():
            return []
        paths_ = box.selectedFiles()
        if getattr(box, "previous_version", None):
            paths_ = [_version_copy(box.previous_version)]      # extapps90: Show previous versions
        mode = box.mode.currentText()
        speedpak = box.speedpak.isEnabled() and box.speedpak.isChecked()
        skip_hidden = box.skip_hidden.isEnabled() and box.skip_hidden.isChecked()
        configuration = box.configurations.currentText() if len(paths_) == 1 else None
        display_state = box.display_states.currentText() if len(paths_) == 1 else None
        read_only = bool(box.read_only)
    out, failed = [], []
    for p in paths_:
        try:
            out.append(open_file(p, mode, speedpak, skip_hidden, configuration, display_state, read_only))
        except Exception as error:
            failed.append((p, _open_error_text(error)))
            App.Console.PrintError("FreeCAD: %s not opened: %s\n" % (p, error))
    if failed:
        _tell_not_opened(failed)
    return out


def _open_error_text(error):
    """save114: the reason a file did not open, in words (FreeCAD's own text without its exception wrapping)."""
    text = str(error).strip()
    text = re.sub(r"^(FreeCAD exception thrown|<Exception>)\s*", "", text).strip(" ()")
    if not text:
        text = "FreeCAD could not read it."
    elif "Cannot open STEP file" in text or "Cannot open IGES file" in text or "nothing was read" in text:
        text = "FreeCAD could not read anything from it. The file may be damaged or of another type."
    return text if text.endswith(".") else text + "."


def _tell_not_opened(failed):
    ""

    seen = set()
    failed = [(p, why) for p, why in failed
              if os.path.normcase(os.path.abspath(p)) not in seen and not seen.add(os.path.normcase(os.path.abspath(p)))]
    lines = ["%s could not be opened. %s" % (os.path.basename(p), why) for p, why in failed]
    try:
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Open", "\n\n".join(lines))
    except Exception as _fw_err:
        _fw_log("saveas.py:not-opened", _fw_err)


class SaveAsCommand:
    def GetResources(self):
        return {"MenuText": "Save As...", "Pixmap": "document-save-as",
                "ToolTip": "Saves a copy under another name or file type.",
                "CmdType": "ForEdit"}

    def Activated(self):
        QtCore.QTimer.singleShot(0, save_as)

    def IsActive(self):
        return App.ActiveDocument is not None


class OpenCommand:
    def GetResources(self):
        return {"MenuText": "Open...", "Pixmap": "document-open",
                "ToolTip": "Opens a saved file (Ctrl+O).", "CmdType": "ForEdit"}     # extapps77

    def Activated(self):
        QtCore.QTimer.singleShot(0, open_files)

    def IsActive(self):
        return True



# Changes that only change how an assembly looks (hide / show, appearances, colours, transparency, display mode,
# reference geometry shown or not) do not mark the top assembly as changed, so closing it asks nothing. They are
# still written by the next Save. A real change (a mate, a component moved, a feature) marks it as before.
COSMETIC = {"Visibility", "ShapeAppearance", "ShapeColor", "DiffuseColor", "Transparency", "LineColor",
            "PointColor", "LineWidth", "PointSize", "DisplayMode", "DrawStyle", "SelectionStyle", "ShowInTree",
            "OverrideMaterial", "ColoredParts", "OnTopWhenSelected", "ShapeMaterial", "MaterialList",
            "OverrideMaterialList", "OverrideColorList", "ColoredElements", "LinkVisibility", "VisibilityList"}
SMART_SAVE = "SmartSavePrompts"


_ASM = {}       # document name: holds an assembly (cached: read on every property change)
_LATER = []     # (document name, cosmetic) changes, sorted right after the change (not inside it)


def _is_assembly(doc):
    try:
        got = _ASM.get(doc.Name)
        if got is None:
            got = _ASM[doc.Name] = any(o.TypeId == "Assembly::AssemblyObject" for o in doc.Objects)
        return got
    except Exception:
        return False


class _SmartSave(object):
    """Keeps an assembly unmarked while its only changes since it was opened or saved are cosmetic."""
    dirty = set()          # documents with a real change since their last save / open

    def _on(self):
        return paths.params().GetBool(SMART_SAVE, True)

    # App side
    def slotChangedObject(self, obj, prop):
        # Nothing is read here but the document's name: objects send changes while their C++ side is still
        # being built (a FEM mesh adds its properties then), and listing the document's objects from
        # Python at that moment makes FreeCAD refuse the object ("Cannot add static property").
        if prop in ("Label2",) or (prop.startswith("_") and prop not in COSMETIC):     # _GroupTouched: a child shown
            return
        try:
            name = obj.Document.Name
        except Exception:
            return
        _LATER.append((name, prop in COSMETIC))
        if len(_LATER) == 1:
            QtCore.QTimer.singleShot(0, self._sort_later)

    def _sort_later(self):
        got = list(_LATER)
        del _LATER[:]
        for name, cosmetic in got:
            try:
                if name not in App.listDocuments():
                    continue
                doc = App.getDocument(name)
                if cosmetic:
                    if self._on():
                        self.cosmetic(doc)
                elif _is_assembly(doc):
                    _SmartSave.dirty.add(name)
            except Exception as _fw_err:
                _fw_log("saveas.py:1790", _fw_err)

    def slotCreatedObject(self, obj):
        try:
            _ASM.pop(obj.Document.Name, None)
            _SmartSave.dirty.add(obj.Document.Name)
        except Exception as _fw_err:
            _fw_log("saveas.py:1797", _fw_err)

    def slotDeletedObject(self, obj):
        self.slotCreatedObject(obj)

    def slotFinishSaveDocument(self, doc, _name=None):
        _SmartSave.dirty.discard(doc.Name)

    def slotFinishRestoreDocument(self, doc):
        QtCore.QTimer.singleShot(0, lambda n=doc.Name: _SmartSave.dirty.discard(n))

    def slotDeletedDocument(self, doc):
        _SmartSave.dirty.discard(doc.Name)
        _ASM.pop(doc.Name, None)

    # Gui side: a view provider's cosmetic property
    def slotChangedObjectGui(self, vp, prop):
        if prop not in COSMETIC or not self._on():
            return
        # the view provider is not read here: view providers send these while they are still being built,
        # and reading their object then crashes FreeCAD; the change is the active document's
        QtCore.QTimer.singleShot(0, self._cosmetic_active)

    def sweep(self):
        """Open assemblies marked changed although nothing but their looks changed: unmarked."""
        if not self._on():
            return
        for name in list(_ASM):
            try:
                if _ASM.get(name) and name not in _SmartSave.dirty and name in App.listDocuments():
                    g = Gui.getDocument(name)
                    if g is not None and g.Modified:
                        self.cosmetic(App.getDocument(name))
            except Exception as _fw_err:
                _fw_log("saveas.py:1831", _fw_err)

    def _cosmetic_active(self):
        try:
            doc = App.ActiveDocument
            if doc is not None:
                self.cosmetic(doc)
        except Exception as _fw_err:
            _fw_log("saveas.py:1839", _fw_err)

    def cosmetic(self, doc):
        if not _is_assembly(doc) or doc.Name in _SmartSave.dirty:
            return
        name = doc.Name

        def clear():
            if name in _SmartSave.dirty or name not in App.listDocuments():
                return
            try:
                g = Gui.getDocument(name)
                if g is not None and g.Modified:
                    g.Modified = False
            except Exception as _fw_err:
                _fw_log("saveas.py:1854", _fw_err)
        clear()
        QtCore.QTimer.singleShot(0, clear)


class _SmartSaveGui(object):
    def __init__(self, owner):
        self.owner = owner

    def slotChangedObject(self, vp, prop):
        self.owner.slotChangedObjectGui(vp, prop)


_SMART = []


def _opened_clean(doc):
    _SmartSave.dirty.discard(doc.Name)


# ---------------------------------------------------------------- dmg151: a damaged file opens read-only
_OBJECT = re.compile(r'<Object\s+type="[^"]*"\s+name="([^"]+)"')


def damage(path):
    """How much of a FreeCAD file can be read: (expected objects, why) with why "" when the file is whole.
    expected 0: there is nothing to read (no Document.xml). A Document.xml that does not parse (cut off,
    garbled) gives the objects its list still names."""
    import zipfile
    import xml.etree.ElementTree as ET
    try:
        with zipfile.ZipFile(path) as z:
            if "Document.xml" not in z.namelist():
                return 0, "it has no Document.xml"
            xml = z.read("Document.xml")
    except Exception as error:
        return 0, "it could not be read (%s)" % error
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        text = xml.decode("utf-8", "replace")
        named = len(set(_OBJECT.findall(text)))
        listed = re.search(r'<Objects\s+Count="(\d+)"', text)      # the count comes before the list
        return max(named, int(listed.group(1)) if listed else 0, 1), "its Document.xml is cut off or damaged"
    objects = root.find("Objects")
    if objects is None:
        return 0, ""
    try:
        count = int(objects.get("Count", "0"))
    except ValueError:
        count = len(objects.findall("Object"))
    return count, ""


def listed_objects(path):
    """[(name, type)] of the objects a whole Document.xml lists; [] when it cannot be read."""
    import zipfile
    import xml.etree.ElementTree as ET
    try:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("Document.xml"))
        return [(o.get("name"), o.get("type", "")) for o in root.find("Objects").findall("Object")]
    except Exception:
        return []


def missing_modules(doc, path):
    """{module: [object names]} for the objects the file lists that FreeCAD could not make because their
    type's module (a workbench: Fem::..., Path::..., an add-on's) is not there."""
    out = {}
    for name, kind in listed_objects(path):
        if not name or doc.getObject(name) is not None:
            continue
        module = kind.split("::")[0] if "::" in kind else (kind or "?")
        out.setdefault(module, []).append(name)
    if any(_module_loads(m) for m in out):
        return {}           # a module that is here: those objects failed for another reason (the file is damaged)
    return out


def damaged_text(doc, expected, why, read):
    name = os.path.basename(doc.FileName) if doc.FileName else doc.Label
    what = "FreeCAD read %d of its %d items" % (read, expected) if expected and read < expected else "FreeCAD could not read all of it"
    return ("%s is damaged: %s, %s.\n\nIt was opened read-only so that Save cannot write over the file. "
            "Use File > Save As to keep what was read under a new name." % (name, why or "items are missing", what))


DAMAGED = []        # (document name, text) of the files opened read-only as damaged (checks read it)
_READ_FROM = {}     # dmg153: document name -> the file it is being read from (FileName when it was created)


class _ReadFrom:
    """The file a document is read from. A recovered document (Document Recovery) is read from its recovery copy
    and then given the original's file name: judged against the original, the work done since its last save
    (objects deleted) looked like objects that failed to load, and it opened read-only as damaged."""

    def slotCreatedDocument(self, doc):
        try:
            _READ_FROM[doc.Name] = ""
        except Exception as _fw_err:
            _fw_log("saveas.py:read-from", _fw_err)

    def slotChangedDocument(self, doc, prop):
        # the first file name a new document gets is the file it is read from (set before its objects are read)
        if prop == "FileName":
            try:
                if _READ_FROM.get(doc.Name) == "":
                    _READ_FROM[doc.Name] = doc.FileName or ""
            except Exception as _fw_err:
                _fw_log("saveas.py:read-from name", _fw_err)

    def slotDeletedDocument(self, doc):
        _READ_FROM.pop(getattr(doc, "Name", ""), None)


def _module_loads(module):
    """The module of an object type (Part, Fem, an add-on's) can be loaded here."""
    if not module or module == "?":
        return False
    try:
        __import__(module)
        return True
    except Exception:
        return False


def _opened_damaged(doc):
    ""



    path = _READ_FROM.pop(doc.Name, "") or getattr(doc, "FileName", "") or ""
    if not path.lower().endswith(".fcstd") or not os.path.isfile(path):
        return
    expected, why = damage(path)
    read = len(doc.Objects)
    # fh186: a part a drawing or assembly needs is loaded only in part (FreeCAD's partial loading: only the

    partial = bool(getattr(doc, "Partial", False))
    if not why and (read >= expected or partial):
        _opened_newer(doc, path)
        return
    wb = missing_modules(doc, path) if not why else {}
    if not why:
        why = "items are missing"
    try:
        from . import filecmds
        filecmds.set_read_only(doc, True)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s could not be made read-only: %s\n" % (doc.Label, error))
    text = workbench_text(doc, wb) if wb else damaged_text(doc, expected, why, read)
    DAMAGED.append((doc.Name, text))
    del DAMAGED[:-10]
    App.Console.PrintWarning("FreeCAD: %s\n" % text.replace("\n\n", " "))
    QtCore.QTimer.singleShot(0, lambda: _tell_damaged(text))


def workbench_text(doc, missing):
    """The file is whole, but some of its objects need a workbench FreeCAD does not have: say which."""
    name = os.path.basename(doc.FileName) if doc.FileName else doc.Label
    parts = ["the %s workbench (%s)" % (m, ", ".join(n[:6]) + (", ..." if len(n) > 6 else "")) for m, n in sorted(missing.items())]
    return ("%s is not damaged, but it uses objects from %s, which is not installed or did not load, so FreeCAD "
            "could not open those objects.\n\nIt was opened read-only so that Save cannot drop them from the file. "
            "Install the workbench (Tools > Addon manager) and open the file again, or use File > Save As to keep "
            "the rest under a new name." % (name, " and ".join(parts)))


def _tell_damaged(text):
    try:
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Open", text)
    except Exception as _fw_err:
        _fw_log("saveas.py:damaged", _fw_err)


# ---------------------------------------------------------------- drop155: files dropped on the window
DROP_OPENS = {"fcstd", "step", "stp", "igs", "iges", "brep", "brp", "stl", "obj", "off", "ply", "3mf", "amf"}


def _dropped(event):
    """The local files of a drag, when every one is a file File > Open reads; else []."""
    try:
        mime = event.mimeData()
        if mime is None or not mime.hasUrls():
            return []
        paths_ = [u.toLocalFile() for u in mime.urls()]
    except Exception:
        return []
    if not paths_ or not all(p and os.path.splitext(p)[1][1:].lower() in DROP_OPENS for p in paths_):
        return []
    return paths_


def _over_documents(widget):
    """The drop lands on the main window or on a document's window (graphics area, drawing sheet), not on a
    panel with its own drop (Task Pane, Design Library, FeatureManager tree)."""
    try:
        main = Gui.getMainWindow()
        w = widget
        while w is not None:
            if isinstance(w, QtWidgets.QDockWidget):
                return False
            if isinstance(w, QtWidgets.QMdiArea) or w is main:
                return True
            w = w.parentWidget()
    except Exception as _fw_err:
        _fw_log("saveas.py:drop where", _fw_err)
    return False


def _assembly_active():
    try:
        from . import asmcore
        doc = App.ActiveDocument
        return doc is not None and asmcore.assembly_of(doc) is not None
    except Exception:
        return False


class _DropOpens(QtCore.QObject):
    ""





    def eventFilter(self, obj, event):
        try:
            t = event.type()
            if t not in (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove, QtCore.QEvent.Drop):
                return False
            if not isinstance(obj, QtWidgets.QWidget) or not _over_documents(obj):
                return False
            paths_ = _dropped(event)
            if not paths_ or _assembly_active():
                return False
            event.setDropAction(QtCore.Qt.CopyAction)
            event.accept()
            if t == QtCore.QEvent.Drop:
                QtCore.QTimer.singleShot(0, lambda p=list(paths_): open_files(p))
            return True
        except Exception as _fw_err:
            _fw_log("saveas.py:drop", _fw_err)
            return False


_DROP = []


def install_drop():
    if _DROP:
        return _DROP[0]
    app = QtWidgets.QApplication.instance()
    if app is None:
        return None
    f = _DropOpens(app)
    app.installEventFilter(f)
    _DROP.append(f)
    return f


def install_smart_save():
    if _SMART:
        return _SMART[0]
    o = _SmartSave()
    App.addDocumentObserver(o)
    try:        # an opened file starts with no real change (FreeCAD 1.1 never sends slotFinishRestoreDocument)
        from . import restorehook
        restorehook.on_restored(_opened_clean, delay=100)
        restorehook.on_restored(_opened_damaged)
        App.addDocumentObserver(_ReadFrom())
    except Exception as _fw_err:
        _fw_log("saveas.py:restorehook", _fw_err)
    # The view side (an appearance, a display mode): no Gui document observer. One that takes
    # slotChangedObject is handed every view provider while it is being built, and a FEM mesh's then
    # fails to build ("Cannot add static property"): FreeCAD's own FEM workbench broke. Instead, an
    # assembly marked changed with no real change since it was opened or saved is a cosmetic change.
    try:
        o.timer = QtCore.QTimer()
        o.timer.setInterval(800)
        o.timer.timeout.connect(o.sweep)
        o.timer.start()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: smart save (view side): %s\n" % error)
    _SMART.append(o)
    return o


def register():
    Gui.addCommand("SWStyle_SaveAs", SaveAsCommand())
    Gui.addCommand("SWStyle_Open", OpenCommand())
    try:
        install_smart_save()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: smart save prompts: %s\n" % error)
    try:
        install_drop()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: dropped files: %s\n" % error)
    try:
        from . import filelock          # fh163: a file open in another FreeCAD opens read-only
        filelock.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: file in use: %s\n" % error)
