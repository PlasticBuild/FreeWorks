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

import FreeCAD as App
import Part

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

from . import simplefeature as sf
from .simplefeature import Field

V = App.Vector
AXES = ["Z", "X", "Y"]


def _hidden_read(path):
    """(solids, surfaces, meta) of the part file."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".step", ".stp", ".iges", ".igs", ".brep", ".brp"):
        shape = Part.read(path)
        return list(shape.Solids), [s for s in shape.Shells if not _in_solid(s, shape)] or \
            ([f for f in shape.Faces] if not shape.Solids else []), {}
    active = App.ActiveDocument
    already = [d for d in App.listDocuments().values() if os.path.normcase(d.FileName or "") == os.path.normcase(path)]
    doc = already[0] if already else App.openDocument(path, hidden=True)
    try:
        bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
        shapes = []
        if bodies:
            shapes = [b.Shape for b in bodies if not b.Shape.isNull()]
        else:
            for o in doc.Objects:
                if o.isDerivedFrom("Part::Feature") and not o.InList and not o.Shape.isNull():
                    shapes.append(o.Shape)
        solids, surfaces = [], []
        for s in shapes:
            solids += [x.copy() for x in s.Solids]
            if not s.Solids:
                surfaces += [x.copy() for x in (s.Shells or s.Faces)]
        meta = dict(doc.Meta)
        meta[EXTRA] = _extras(doc)
    finally:
        if not already:
            App.closeDocument(doc.Name)
        if active is not None and active.Name in App.listDocuments():
            App.setActiveDocument(active.Name)
    return solids, surfaces, meta


EXTRA = "\x00extras"      # the meta key _hidden_read keeps the other transfer items under
DIM_PROPS = ("Length", "Length2", "Radius", "Radius2", "Height", "Width", "Angle", "Angle2", "Depth", "Diameter",
             "Value", "Offset", "TaperAngle", "Size")


def _outline(placement, size):
    ""
    pts = [placement.multVec(V(x, y, 0)) for x, y in ((-size, -size), (size, -size), (size, size), (-size, size))]
    return Part.makePolygon(pts + [pts[0]])


def _triad(placement, size):
    o = placement.Base
    return Part.makeCompound([Part.LineSegment(o, o + placement.Rotation.multVec(d) * size).toShape()
                              for d in (V(1, 0, 0), V(0, 1, 0), V(0, 0, 1))])


def _extras(doc):
    ""

    out = {k: [] for k in ("Planes", "Axes", "CoordinateSystems", "AbsorbedSketches", "UnabsorbedSketches",
                           "CosmeticThreads", "ModelDimensions", "HoleWizardData", "SheetMetalInfo")}
    size = 10.0
    try:
        boxes = [o.Shape.BoundBox for o in doc.Objects if o.TypeId == "PartDesign::Body" and not o.Shape.isNull()]
        if boxes:
            size = max(b.DiagonalLength for b in boxes) * 0.3 or size
    except Exception as _fw_err:
        _fw_log("insertpart.py:106", _fw_err)
    for o in doc.Objects:
        try:
            origin = any(i.isDerivedFrom("App::Origin") for i in o.InList)
            kind = o.TypeId
            if kind in ("PartDesign::Plane", "App::Plane") and not origin:
                out["Planes"].append(_outline(o.getGlobalPlacement() if hasattr(o, "getGlobalPlacement") else o.Placement, size))
            elif kind in ("PartDesign::Line", "App::Line") and not origin:
                out["Axes"].append(o.Shape.copy() if kind == "PartDesign::Line" else
                                   Part.LineSegment(o.Placement.Base, o.Placement.multVec(V(size, 0, 0))).toShape())
            elif kind in ("PartDesign::CoordinateSystem", "App::LocalCoordinateSystem") and not origin:
                out["CoordinateSystems"].append(_triad(o.getGlobalPlacement() if hasattr(o, "getGlobalPlacement") else o.Placement, size * 0.5))
            elif kind == "Sketcher::SketchObject" and not o.Shape.isNull():
                used = any(i.TypeId.startswith("PartDesign::") and i.TypeId != "PartDesign::Body" for i in o.InList)
                out["AbsorbedSketches" if used else "UnabsorbedSketches"].append(o.Shape.copy())
            elif getattr(o, "SWStyleKind", "") == "CosmeticThread" and not o.Shape.isNull():
                out["CosmeticThreads"].append(o.Shape.copy())
            if kind.startswith("PartDesign::") and kind not in ("PartDesign::Body", "PartDesign::Plane", "PartDesign::Line",
                                                                "PartDesign::Point", "PartDesign::CoordinateSystem") and not origin:
                dims = ["%s=%s" % (p, getattr(o, p)) for p in DIM_PROPS if p in o.PropertiesList and
                        hasattr(getattr(o, p), "Value") and o.getTypeIdOfProperty(p) != "App::PropertyLinkSub"]
                if dims:
                    out["ModelDimensions"].append("%s: %s" % (o.Label, ", ".join(dims)))
            if kind == "PartDesign::Hole" or "HoleWizard" in o.PropertiesList or "SWHoleSpec" in o.PropertiesList:
                bits = ["%s=%s" % (p, getattr(o, p)) for p in ("ThreadType", "ThreadSize", "Diameter", "Depth", "DepthType",
                                                                 "HoleCutType", "Threaded") if p in o.PropertiesList]
                out["HoleWizardData"].append("%s: %s" % (o.Label, ", ".join(bits)))
            if "SWThickness" in o.PropertiesList or (kind.startswith("PartDesign::") and "KFactor" in o.PropertiesList):
                bits = ["%s=%s" % (p, getattr(o, p)) for p in ("SWThickness", "Thickness", "Radius", "KFactor", "SWReliefRatio")
                        if p in o.PropertiesList]
                out["SheetMetalInfo"].append("%s: %s" % (o.Label, ", ".join(bits)))
        except Exception:
            continue
    return out


GEOMETRY = ("Planes", "Axes", "CoordinateSystems", "AbsorbedSketches", "UnabsorbedSketches", "CosmeticThreads")
TEXT = ("ModelDimensions", "HoleWizardData", "SheetMetalInfo")


def _transfer_extras(obj, extras):
    """The ticked other Transfer items: geometry for the shape, text into the feature's own lists."""
    geometry = []
    for name in GEOMETRY:
        if getattr(obj, name, False):
            geometry += extras.get(name, [])
    for name in TEXT:
        prop = "Transferred" + name
        want = list(extras.get(name, [])) if getattr(obj, name, False) else []
        if prop not in obj.PropertiesList:
            obj.addProperty("App::PropertyStringList", prop, "Transferred", "From the original part (%s)" % name)
            obj.setEditorMode(prop, 1)
        if list(getattr(obj, prop)) != want:
            setattr(obj, prop, want)
    return geometry


def _in_solid(shell, shape):
    return any(shell.isSame(s) for solid in shape.Solids for s in solid.Shells)


def _placement(obj):
    axis = {"X": V(1, 0, 0), "Y": V(0, 1, 0)}.get(str(obj.RotationAxis), V(0, 0, 1))
    return App.Placement(V(obj.Position), App.Rotation(axis, float(obj.Angle)))


def _insert(obj, base):
    path = (obj.File or "").strip()
    if not path:
        return None, None
    if "Cached" not in obj.PropertiesList:
        obj.addProperty("Part::PropertyPartShape", "Cached", "Insert Part", "The bodies as last read")
        obj.setEditorMode("Cached", 2)
    locked = bool(getattr(obj, "FwRefLocked", False))     # asmpkg346: External References' Lock All
    missing = not obj.BreakLink and not locked and not os.path.isfile(path)
    if (obj.BreakLink or missing or locked) and not obj.Cached.isNull():

        bodies = list(obj.Cached.Solids) + ([] if not obj.SurfaceBodies else
                                           [s for s in obj.Cached.Shells if not _in_solid(s, obj.Cached)])
        bodies += [w for w in obj.Cached.Wires if not any(w.isSame(x) for f in obj.Cached.Faces for x in f.Wires)]
        if missing:
            App.Console.PrintWarning("FreeCAD: %s: the part file is not there, the last shape is kept: %s\n" % (obj.Label, path))
        _mark_missing(obj, missing)
    else:
        if not os.path.isfile(path):
            raise RuntimeError("The part file is not there: %s" % path)
        _mark_missing(obj, False)
        _stamp(obj, path)
        solids, surfaces, meta = _hidden_read(path)
        extras = meta.pop(EXTRA, {})
        bodies = (solids if obj.SolidBodies else []) + (surfaces if obj.SurfaceBodies else [])
        bodies += [g.copy() for g in _transfer_extras(obj, extras)]
        if not bodies:
            raise RuntimeError("The part has nothing to transfer with these Transfer choices")
        obj.Cached = Part.makeCompound([b.copy() for b in bodies])
        if obj.CustomProperties and meta:
            doc = obj.Document
            have = dict(doc.Meta)
            new = {k: v for k, v in meta.items() if k not in have and not k.startswith("Fw")}
            if new:
                have.update(new)
                doc.Meta = have
    place = _placement(obj)
    moved = []
    for b in bodies:
        c = b.copy()
        c.Placement = place.multiply(c.Placement)
        moved.append(c)
    in_body = _in_body(obj)
    refs = [m for m in moved if not m.Solids and not m.Shells] if in_body else []
    if in_body:
        # a body feature keeps solids only: the transferred planes, axes, sketches... go on a reference

        moved = [m for m in moved if m.Solids or m.Shells]
        _later_refs(obj, Part.makeCompound(refs) if refs else None)
    keep = list(base.Solids) if base is not None and not base.isNull() else []
    return Part.makeCompound(keep + moved), Part.makeCompound(moved)


def _file_stamp(path):
    try:
        st = os.stat(path)
        return "%d:%d" % (st.st_mtime_ns, st.st_size)
    except OSError:
        return ""


def _stamp(obj, path):
    ""
    if "SourceStamp" not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", "SourceStamp", "Insert Part", "The part file as last read")
        obj.setEditorMode("SourceStamp", 2)
    stamp = _file_stamp(path)
    if obj.SourceStamp != stamp:
        obj.SourceStamp = stamp


def _mark_missing(obj, missing):
    ""
    label = obj.Label or ""
    if missing and label.endswith("->"):
        obj.Label = label + "?"
    elif not missing and label.endswith("->?"):
        obj.Label = label[:-1]


def _linked(obj):
    return "BreakLink" in obj.PropertiesList and "SolidBodies" in obj.PropertiesList and "File" in obj.PropertiesList \
        and not obj.BreakLink and bool((obj.File or "").strip())


def _in_body(obj):
    try:
        parent = obj.getParentGeoFeatureGroup()
        return parent is not None and parent.TypeId == "PartDesign::Body"
    except Exception:
        return False


def _later_refs(obj, shape):
    """After the rebuild (objects are not added during one): the feature's reference geometry object."""
    def sync():
        try:
            doc = obj.Document
            name = obj.Name + "_Refs"
            ref = doc.getObject(name)
            if shape is None:
                if ref is not None:
                    doc.removeObject(name)
                return
            if ref is None:
                ref = doc.addObject("Part::Feature", name)
                ref.Label = obj.Label + " references"
                try:
                    ref.ViewObject.LineColor = (0.3, 0.6, 1.0)
                except Exception as _fw_err:
                    _fw_log("insertpart.py:242", _fw_err)
            if not ref.Shape.isEqual(shape):
                ref.Shape = shape
        except Exception as error:
            App.Console.PrintLog("FreeCAD Insert Part references: %s\n" % error)
    if App.GuiUp:
        QtCore.QTimer.singleShot(0, sync)
    else:
        sync()


def _browse(obj):
    path, _ = QtWidgets.QFileDialog.getOpenFileName(
        Gui.getMainWindow(), "Insert Part", os.path.dirname(obj.File or obj.Document.FileName or ""),
        "Parts (*.FCStd *.step *.stp *.iges *.igs *.brep);;All files (*)")
    if path:
        obj.File = path
        label = os.path.splitext(os.path.basename(path))[0] + "->"
        obj.Label = label
        obj.Document.recompute()


class _Panel(sf.Panel):
    ""


    def __init__(self, obj):
        super().__init__(obj)
        if not (obj.File or "").strip():
            QtCore.QTimer.singleShot(0, lambda: self._run(_field("Browse")))

    def _run(self, field):
        super()._run(field)
        box = self.widgets.get("File")
        if field.name == "Browse" and box is not None and box.toPlainText() != (self.obj.File or ""):
            self.busy = True
            try:
                box.setPlainText(self.obj.File or "")
            finally:
                self.busy = False
            self._preview()
            self._show()

    def accept(self):
        if not (self.obj.File or "").strip():
            self.error.setText("Select a part file to insert (Browse...).")
            self.error.setVisible(True)
            return False
        return super().accept()


def _field(name):
    return next(f for f in INSERT_PART.fields if f.name == name)


INSERT_PART = sf.Spec(
    "SWStyle_InsertPart", "Insert Part", "Part",
    "Brings the bodies of another part in, linked to that part's file.",
    "INSERT_PART", "Part_Import",
    [Field("File", "text", "Part file", "", box="Part to Insert",
           tip="The part file (.FCStd, STEP, IGES or BREP)"),
     Field("Browse", "button", "Browse...", box="Part to Insert", action=_browse),
     Field("SolidBodies", "bool", "Solid bodies", True, box="Transfer"),
     Field("SurfaceBodies", "bool", "Surface bodies", False, box="Transfer"),
     Field("Axes", "bool", "Axes", False, box="Transfer"),
     Field("Planes", "bool", "Planes", False, box="Transfer"),
     Field("CosmeticThreads", "bool", "Cosmetic threads", False, box="Transfer"),
     Field("AbsorbedSketches", "bool", "Absorbed sketches", False, box="Transfer",
           tip="The sketches the other part's features are built on"),
     Field("UnabsorbedSketches", "bool", "Unabsorbed sketches", False, box="Transfer",
           tip="The other part's sketches no feature uses"),
     Field("CustomProperties", "bool", "Custom properties", False, box="Transfer",
           tip="Copies the other part's custom properties this part does not have"),
     Field("CoordinateSystems", "bool", "Coordinate systems", False, box="Transfer"),
     Field("ModelDimensions", "bool", "Model dimensions", False, box="Transfer",
           tip="The other part's feature dimensions, listed on this feature (Transferred group)"),
     Field("HoleWizardData", "bool", "Hole Wizard data", False, box="Transfer",
           tip="The other part's hole data, listed on this feature (Transferred group)"),
     Field("SheetMetalInfo", "bool", "Sheet metal information", False, box="Transfer",
           tip="The other part's sheet metal values, listed on this feature (Transferred group)"),
     Field("BreakLink", "bool", "Break link to original part", False, box="Link",
           tip="Keep the bodies as they are now: later changes to the file are not read"),
     Field("Position", "vector", "Move (X, Y, Z)", V(0, 0, 0), box="Locate Part"),
     Field("RotationAxis", "enum", "Rotate about", "Z", values=AXES, box="Locate Part"),
     Field("Angle", "angle", "Angle", 0.0, box="Locate Part")],
    _insert, needs_body=False, refine=False, panel=_Panel)


class _FileWatch:
    ""


    def slotFinishSaveDocument(self, doc, filename):
        saved = os.path.normcase(os.path.abspath(filename or doc.FileName or ""))
        if not saved:
            return
        for other in list(App.listDocuments().values()):
            if other is doc:
                continue
            for obj in other.Objects:
                try:
                    if _linked(obj) and os.path.normcase(os.path.abspath(obj.File or "")) == saved:
                        obj.touch()
                except Exception as _fw_err:
                    _fw_log("insertpart.py:watch", _fw_err)


    def slotCreatedDocument(self, doc):
        # FreeCAD 1.1 gives Python observers no slotFinishRestoreDocument: wait for the file to finish loading
        try:
            from . import asmgen
            asmgen.after_load(doc.Name, _opened)
        except Exception as _fw_err:
            _fw_log("insertpart.py:created", _fw_err)


def _opened(doc):
    ""

    try:
        name = doc.Name
        stale, missing = [], []
        for obj in doc.Objects:
            if not _linked(obj):
                continue
            path = obj.File.strip()
            if not os.path.isfile(path):
                missing.append(obj.Name)
            elif "SourceStamp" not in obj.PropertiesList or obj.SourceStamp != _file_stamp(path) \
                    or (obj.Label or "").endswith("->?"):          # found again
                stale.append(obj.Name)
    except Exception as _fw_err:
        _fw_log("insertpart.py:open", _fw_err)
        return
    if (stale or missing) and Gui is not None:
        _after_open(name, lambda: _update_opened(name, stale, missing))


def _after_open(name, fn, tries=100):
    """fn() once the opened part is shown (its window made): before that a rebuild does not run the features."""
    try:
        shown = Gui.getDocument(name) is not None
    except Exception:
        shown = False
    if not shown and tries > 0 and name in App.listDocuments():
        QtCore.QTimer.singleShot(50, lambda: _after_open(name, fn, tries - 1))
        return
    QtCore.QTimer.singleShot(0, fn)


def _update_opened(name, stale, missing):
    doc = App.listDocuments().get(name)
    if doc is None:                       # a part read for a moment (another part's Insert Part) and closed again
        return
    try:
        # fh228: the features get their classes back on a timer of their own (cleanfiles); without them this
        # rebuild ran nothing, so a part changed while this one was closed was not read again on open
        from . import cleanfiles
        cleanfiles.restore(doc)
    except Exception as _fw_err:
        _fw_log("insertpart.py:classes", _fw_err)
    try:
        for n in stale + missing:
            obj = doc.getObject(n)
            if obj is not None:
                obj.touch()
        doc.recompute()
    except Exception as _fw_err:
        _fw_log("insertpart.py:update", _fw_err)
    if missing:
        files = sorted({os.path.basename(doc.getObject(n).File.strip()) for n in missing if doc.getObject(n) is not None})
        QtWidgets.QMessageBox.warning(
            Gui.getMainWindow(), "FreeCAD",
            "%s refers to %s, which cannot be found.\n\nThe last shape is kept (shown as ->? in the "
            "FeatureManager design tree) until the file is back, or use Edit Feature > Browse... to find it."
            % (doc.Label, ", ".join(files)))


_WATCH = []


def register():
    sf.register(INSERT_PART)
    if not _WATCH:
        _WATCH.append(_FileWatch())
        App.addDocumentObserver(_WATCH[0])
