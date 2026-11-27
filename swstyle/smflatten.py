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
import FreeCADGui as Gui
import Part

from . import checkstate, naming

COMMAND = "SWStyle_SMFlatten"
EXIT_COMMAND = "SWStyle_SMExitFlatten"
LABEL = "Flat-Pattern"
GROUP = "Flat-Pattern"
DASHDOT = "Dashdot"


# the features a sheet metal part starts from: Base Flange, Convert to Sheet Metal, Insert Bends
ROOTS = ("SMBaseBend", "SWConvertSolid", "SWInsertBends", "SWLoftedBend", "SWSweptFlange")


def _is_base_flange(obj):
    return type(getattr(obj, "Proxy", None)).__name__ in ROOTS


def is_flat_pattern(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "FlatPattern"


def root(body):
    return next((o for o in body.Group if _is_base_flange(o)), None)


def flat_pattern(body):
    if body is None:
        return None
    return next((o for o in body.InList if is_flat_pattern(o) and o.Body is body), None)


def _body(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    try:
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
    except Exception:
        body = None
    if body is not None and root(body) is not None:
        return body
    return next((o for o in doc.Objects if o.TypeId == "PartDesign::Body" and root(o) is not None), None)


def is_flat(doc=None):
    fp = flat_pattern(_body(doc))
    return fp is not None and fp.SWFlattened


# ---------------------------------------------------------------- fixed face
def _plane_face(shape, normal, point):
    """The planar face of shape on the plane (normal, point) that holds point, else the largest one."""
    best, best_area = None, 0.0
    for i, f in enumerate(shape.Faces, 1):
        if f.Surface.TypeId != "Part::GeomPlane":
            continue
        n = f.normalAt(0, 0)
        if abs(abs(n.dot(normal)) - 1) > 1e-7 or abs((f.CenterOfMass - point).dot(normal)) > 1e-6:
            continue
        if f.isInside(point, 1e-6, True):
            return "Face%d" % i
        if f.Area > best_area:
            best, best_area = "Face%d" % i, f.Area
    return best


def fixed_face(base, tip):
    """The face of tip on the Base Flange's fixed face: its biggest planar face on the sketch plane
    (the other side when none lies there)."""
    if "FixedNormal" in base.PropertiesList:
        return _plane_face(tip.Shape, base.FixedNormal, base.FixedPoint)
    sketch = getattr(base, "BendSketch", None)
    plane = sketch.getGlobalPlacement() if sketch is not None else App.Placement()
    origin = plane.Base
    faces = [f for f in base.Shape.Faces if f.Surface.TypeId == "Part::GeomPlane"]
    if not faces:
        return None
    if sketch is not None and _open_profile(sketch):
        # an open profile is thickened and pulled out of the sketch plane: the faces on that plane are the

        # sheet's biggest flat wall (square to the sketch plane) stays fixed.
        normal = plane.Rotation.multVec(App.Vector(0, 0, 1))
        walls = [f for f in faces if abs(f.normalAt(0, 0).dot(normal)) < 1e-6]
        if walls:
            face = max(walls, key=lambda f: f.Area)
            u0, u1, v0, v1 = face.ParameterRange
            point = face.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
            if not face.isInside(point, 1e-6, True):
                point = face.CenterOfMass
            return _plane_face(tip.Shape, face.normalAt(0, 0), point)
    faces.sort(key=lambda f: (round(abs((f.CenterOfMass - origin).dot(f.normalAt(0, 0))), 6), -f.Area))
    face = faces[0]
    u0, u1, v0, v1 = face.ParameterRange
    point = face.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
    if not face.isInside(point, 1e-6, True):
        point = face.Vertexes[0].Point
    return _plane_face(tip.Shape, face.normalAt(0, 0), point)


def _open_profile(sketch):
    try:
        wires = sketch.Shape.Wires
        return bool(wires) and not wires[0].isClosed()
    except Exception:
        return False


def own_flat(base):
    """(flat solid, bend lines, flat face) when the part's first feature develops itself flat, else None."""
    flat = getattr(getattr(base, "Proxy", None), "flat", None) if base is not None else None
    return flat(base) if callable(flat) else None


class _Part:
    """What the SheetMetal unfolder reads of a part: its name, shape and Refine."""

    def __init__(self, obj, shape):
        self.Name, self.Label, self.Shape = obj.Name, obj.Label, shape
        self.Refine = bool(getattr(obj, "Refine", False))


def _without_welds(body, tip):
    ""


    from . import smformingtool, smgusset, smweldedcorner
    shape = tip.Shape
    if any(smweldedcorner.is_welded_corner(o) for o in body.Group):
        shape = smweldedcorner.without_welds(body, shape)
    bevels = [o.BevelShape for o in body.Group if hasattr(o, "BevelShape") and not o.BevelShape.isNull()
              and o.BevelShape.Solids]
    if bevels:
        # Insert Bends kept chamfered edges: the unfolder cannot lay them flat, so the flat shows them square
        shape = shape.cut(Part.makeCompound(bevels)).removeSplitter()
    if any(smgusset.is_gusset(o) for o in body.Group):
        shape = smgusset.without_gussets(body, shape)
    if any(smformingtool.is_form_feature(o) or type(getattr(o, "Proxy", None)).__name__ == "SWStamp"
           for o in body.Group):
        shape = smformingtool.without_forms(body, shape)
    return tip if shape is tip.Shape else _Part(tip, shape)


# ---------------------------------------------------------------- bounding box
def _bounding_box(face, grain=None):
    ""

    normal = face.normalAt(0, 0)
    lines = [e for e in face.OuterWire.Edges if e.Curve.TypeId == "Part::GeomLine"]
    g = grain - normal * grain.dot(normal) if grain is not None else None
    if g is not None and g.Length > 1e-6:
        xdir = g.normalize()
    elif lines:
        x = max(lines, key=lambda e: e.Length)
        xdir = (x.Vertexes[1].Point - x.Vertexes[0].Point).normalize()
    else:
        xdir = App.Vector(1, 0, 0) if abs(normal.x) < 0.9 else App.Vector(0, 1, 0)
        xdir = (xdir - normal * xdir.dot(normal)).normalize()
    ydir = normal.cross(xdir)
    origin = face.Vertexes[0].Point
    us = [(v.Point - origin).dot(xdir) for v in face.Vertexes]
    vs = [(v.Point - origin).dot(ydir) for v in face.Vertexes]
    for e in face.OuterWire.Edges:      # arcs reach past their end points
        for p in e.discretize(24):
            us.append((p - origin).dot(xdir))
            vs.append((p - origin).dot(ydir))
    corners = [origin + xdir * u + ydir * v for u, v in
               ((min(us), min(vs)), (max(us), min(vs)), (max(us), max(vs)), (min(us), max(vs)))]
    return Part.makePolygon(corners + corners[:1])


def _same_cylinder(a, b):
    """Two cylinder surfaces on one axis line with one radius."""
    if abs(a.Radius - b.Radius) > 1e-6 or abs(abs(a.Axis.dot(b.Axis)) - 1) > 1e-9:
        return False
    d = b.Center - a.Center
    return (d - a.Axis * d.dot(a.Axis)).Length < 1e-5


def custom_bends(body, k):
    """[(cylinder surface, K)] of the bends made by a feature with its own K-Factor (an Edge Flange,
    Hem or Miter Flange with Custom Bend Allowance): the round faces it adds to its base."""
    out = []
    for feature in body.Group:
        own = getattr(feature, "kfactor", None)
        if own is None or abs(float(own) - k) < 1e-9:
            continue
        try:
            before = feature.BaseFeature.Shape if feature.BaseFeature is not None else Part.Shape()
            old = [f.Surface for f in before.Faces if type(f.Surface).__name__ == "Cylinder"]
            for f in feature.Shape.Faces:
                s = f.Surface
                if type(s).__name__ == "Cylinder" and not any(_same_cylinder(s, o) for o in old):
                    out.append((s, float(own)))
        except Exception:
            continue
    return out


class _custom_k:
    ""


    def __init__(self, body, k, shape):
        self.bends = custom_bends(body, k) if body is not None else []
        self.shape = shape
        self.saved = None

    def __enter__(self):
        if not self.bends:
            return self
        import SheetMetalUnfolder as smu
        node = smu.Simple_node
        self.saved = node.__dict__.get("k_Factor")
        bends, shape, original = self.bends, self.shape, self.saved

        def k_factor(this):
            try:
                face = shape.Faces[this.idx]
                for surface, own in bends:
                    if type(face.Surface).__name__ == "Cylinder" and \
                            abs(abs(face.Surface.Axis.dot(surface.Axis)) - 1) < 1e-9:
                        d = face.Surface.Center - surface.Center
                        if (d - surface.Axis * d.dot(surface.Axis)).Length < 1e-5:
                            return own if smu.KFACTORSTANDARD == "ansi" else own / 2
            except Exception as _fw_err:
                _fw_log("smflatten.py:259", _fw_err)
            return original.fget(this)
        node.k_Factor = property(k_factor)
        return self

    def __exit__(self, *exc):
        if self.saved is not None:
            import SheetMetalUnfolder as smu
            smu.Simple_node.k_Factor = self.saved
        return False


def _rehide(doc_name, name):
    """restorefix-1126: a file reopens a hidden Flat-Pattern shown; it is hidden again unless it is flattened."""
    doc = App.listDocuments().get(doc_name)
    fp = doc.getObject(name) if doc is not None else None
    vo = getattr(fp, "ViewObject", None) if fp is not None else None
    if vo is not None and not getattr(fp, "SWFlattened", False) and vo.Visibility:
        was = Gui.getDocument(doc_name).Modified
        vo.Visibility = False
        Gui.getDocument(doc_name).Modified = was


class FlatPattern:
    """The Flat-Pattern feature (Part::FeaturePython outside the body, which it follows)."""

    def __init__(self, obj, body):
        obj.addProperty("App::PropertyLink", "Body", GROUP, "The sheet metal part")
        obj.addProperty("App::PropertyBool", "SWFlattened", GROUP, "Shown flat (Flatten)")
        obj.addProperty("App::PropertyLink", "BendLines", GROUP, "Bend lines of the flat pattern")
        obj.addProperty("App::PropertyLink", "BoundingBox", GROUP, "Bounding box of the flat pattern")
        obj.addProperty("App::PropertyString", "FixedFace", GROUP, "Fixed face on the last feature")
        for name in ("BendLines", "BoundingBox", "FixedFace"):
            obj.setEditorMode(name, 1)
        obj.Body = body
        obj.Proxy = self
        from . import smflatpm
        smflatpm.ensure(obj)

    def dumps(self):
        return None             # self.untrimmed is a shape, rebuilt on recompute: never saved

    def loads(self, state):
        return None

    def onDocumentRestored(self, obj):
        if App.GuiUp and not obj.SWFlattened:
            from PySide import QtCore
            docname, name = obj.Document.Name, obj.Name
            QtCore.QTimer.singleShot(0, lambda: QtCore.QTimer.singleShot(0, lambda: _rehide(docname, name)))

    def execute(self, obj):
        body = obj.Body
        if not obj.SWFlattened or body is None or body.Tip is None:
            return
        base = root(body)
        own = own_flat(base)
        if own is not None:
            # a lofted bend (facet by facet) or a swept flange flattened along its path develops itself
            shape, folds, flat_face = own
            obj.FixedFace = ""
            obj.Shape = self._trimmed(obj, shape)
            lines = Part.makeCompound(folds) if folds else Part.Shape()
            box = _bounding_box(flat_face)
            for child, made in ((obj.BendLines, lines), (obj.BoundingBox, box)):
                if child is not None:
                    child.Shape = made
                    child.purgeTouched()
            return
        from . import smflatpm
        smflatpm.follow(obj)
        tip = _without_welds(body, body.Tip)
        thickness = getattr(base, "Thickness", None)
        tip = smflatpm.shape_for(obj, tip, thickness)
        face = smflatpm.fixed(obj, tip.Shape) or (fixed_face(base, tip) if base is not None else None)
        if face is None:
            raise RuntimeError("Flat-Pattern: no fixed face on the sheet metal part")
        from . import smbendtable, smflatdisplay
        try:
            k = smbendtable.k_of(base, tip.Shape)
        except ValueError as e:
            raise RuntimeError("Flat-Pattern: %s" % e)
        with _custom_k(body, k, tip.Shape):
            shape, folds, _norm, _name, err, _sel, _obj = smflatdisplay.unfold(obj.Name, {1: k}, tip, face, "ansi")
        if shape is None:
            raise RuntimeError("Flat-Pattern: the part does not unfold (error %s)" % err)
        obj.FixedFace = face
        plane = tip.Shape.getElement(face)
        shape = smflatpm.finish(obj, shape, folds, plane.normalAt(0, 0), plane.CenterOfMass, thickness)
        shape = self._trimmed(obj, shape)
        obj.Shape = shape
        flat = _plane_face(shape, plane.normalAt(0, 0), plane.CenterOfMass)
        lines = folds if folds is not None else Part.Shape()
        box = _bounding_box(shape.getElement(flat), smflatpm.grain(obj)) if flat else Part.Shape()
        for child, made in ((obj.BendLines, lines), (obj.BoundingBox, box)):
            if child is not None:
                child.Shape = made
                child.purgeTouched()
        if App.GuiUp:
            from PySide import QtCore
            name, docname = obj.Name, obj.Document.Name
            QtCore.QTimer.singleShot(0, lambda: smflatdisplay.apply(next((d.getObject(name) for d in [App.listDocuments().get(docname)] if d is not None), None)))
        try:
            from . import smcutlist
            smcutlist.later(obj.Document.Name)
        except Exception as _fw_err:
            _fw_log("smflatten.py:347", _fw_err)
        gussets = getattr(obj, "GussetLines", None)
        if gussets is not None:
            from . import smgusset
            from .smnormalcut import inside_point
            try:
                fixed = inside_point(tip.Shape.getElement(face))
                edges = smgusset.flat_lines(body, tip.Shape, fixed, k)
            except Exception as e:
                App.Console.PrintWarning("Flat-Pattern: gusset profiles not shown (%s)\n" % e)
                edges = []
            gussets.Shape = Part.makeCompound(edges) if edges else Part.Shape()
            gussets.purgeTouched()


    def _trimmed(self, obj, shape):
        """The shape with the Corner Trims under the Flat-Pattern; the untrimmed one is kept for their picks."""
        from . import smcornertrim
        self.untrimmed = shape
        return smcornertrim.apply_all(obj, shape)


class ViewProviderFlatPattern:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def claimChildren(self):
        obj = self.Object
        from . import smcornertrim
        return [c for c in _children(obj) if c is not None] + smcornertrim.trims(obj)

    def getIcon(self):
        try:
            import SheetMetalTools
            return os.path.join(SheetMetalTools.icons_path, "SheetMetal_Unfold.svg")
        except Exception:
            return ""

    def doubleClicked(self, vobj):
        toggle(self.Object.Body)
        return True

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        from . import smflatpm
        smflatpm.edit(vobj.Object)
        return True

    def unsetEdit(self, vobj, mode=0):
        return False

    def setupContextMenu(self, vobj, menu):
        fp = vobj.Object
        f = menu.addAction("Unflatten" if fp.SWFlattened else "Flatten")
        f.triggered.connect(lambda: set_flat(fp.Body, not fp.SWFlattened))
        e = menu.addAction("Edit Feature")
        e.triggered.connect(lambda: Gui.ActiveDocument.setEdit(vobj.Object.Name, 0))
        a = menu.addAction("Export to DXF/DWG")
        a.triggered.connect(lambda: Gui.runCommand("SWStyle_SMExportDXF"))

    def onDelete(self, vobj, subelements):
        doc = vobj.Object.Document
        for child in self.claimChildren():
            try:
                doc.removeObject(child.Name)
            except Exception as _fw_err:
                _fw_log("smflatten.py:417", _fw_err)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _child(doc, name, label):
    obj = doc.addObject("Part::Feature", name)
    obj.Label = label
    if App.GuiUp:
        vo = obj.ViewObject
        vo.LineColor = (0.0, 0.0, 0.0)
        vo.LineWidth = 1.0
        try:
            vo.DrawStyle = DASHDOT
        except Exception as _fw_err:
            _fw_log("smflatten.py:437", _fw_err)
        vo.Visibility = False
    return obj


def _children(fp):
    extra = [o for o in fp.Document.Objects if getattr(o, "SWBendNoteOf", "") == fp.Name]
    if "GrainArrow" in fp.PropertiesList:
        extra.append(fp.GrainArrow)
    return (fp.BendLines, fp.BoundingBox, getattr(fp, "GussetLines", None)) + tuple(extra)


def gusset_lines(body):
    """The Flat-Pattern's Gusset-Profiles child, for the gussets' profiles and centres (made when missing)."""
    fp = ensure(body)
    if getattr(fp, "GussetLines", None) is None:
        if "GussetLines" not in fp.PropertiesList:
            fp.addProperty("App::PropertyLink", "GussetLines", GROUP, "Sheet metal gusset profiles in the flat pattern")
            fp.setEditorMode("GussetLines", 1)
        n = fp.Label[len(LABEL):]
        child = _child(fp.Document, "GussetLines", "Gusset-Profiles" + n)
        if App.GuiUp:
            child.ViewObject.DrawStyle = "Solid"
            child.ViewObject.Visibility = bool(fp.SWFlattened)
        fp.GussetLines = child
    return fp.GussetLines


def ensure(body):
    """The part's Flat-Pattern, made (folded, greyed) when missing; the Sheet-Metal folder with it."""
    try:
        from . import smsheetmetal
        smsheetmetal.ensure(body)
    except Exception as e:
        App.Console.PrintWarning("Sheet-Metal folder: %s\n" % e)
    fp = flat_pattern(body)
    if fp is not None:
        return fp
    doc = body.Document
    fp = doc.addObject("Part::FeaturePython", "FlatPattern")
    FlatPattern(fp, body)
    fp.Label = naming.next_label(doc, LABEL)
    n = fp.Label[len(LABEL):]
    fp.BendLines = _child(doc, "BendLines", "Bend-Lines" + n)
    fp.BoundingBox = _child(doc, "BoundingBox", "Bounding-Box" + n)
    if App.GuiUp:
        ViewProviderFlatPattern(fp.ViewObject)
        fp.ViewObject.Visibility = False
    return fp


def _show(fp, flat):
    ""

    body = fp.Body
    try:
        box = getattr(fp, "BoundingBox", None)
        if "SWBoxShown" not in fp.PropertiesList:
            fp.addProperty("App::PropertyBool", "SWBoxShown", GROUP, "The Bounding-Box was shown when the part was last folded")
            fp.setEditorMode("SWBoxShown", 2)
        if not flat and box is not None and box.ViewObject is not None:
            fp.SWBoxShown = bool(box.ViewObject.Visibility)
        fp.ViewObject.Visibility = flat
        for child in _children(fp):
            if child is not None:
                child.ViewObject.Visibility = flat and (child is not box or fp.SWBoxShown)
        body.ViewObject.Visibility = not flat
    except Exception as _fw_err:
        _fw_log("smflatten.py:497", _fw_err)


def set_flat(body, flat):
    fp = ensure(body)
    if bool(fp.SWFlattened) == bool(flat):
        return fp
    doc = body.Document
    doc.openTransaction("Flatten" if flat else "Exit Flatten")
    fp.SWFlattened = flat
    if flat:
        fp.touch()
        doc.recompute()
        if "Invalid" in fp.State:
            fp.SWFlattened = False
            doc.abortTransaction()
            App.Console.PrintError("Flatten: the part does not unfold\n")
            return fp
    _show(fp, flat)
    try:
        from . import smflatdisplay
        smflatdisplay.apply(fp)         # bend notes / grain arrow show and hide with the flat
    except Exception as _fw_err:
        _fw_log("smflatten.py:520", _fw_err)
    doc.commitTransaction()
    Gui.updateGui()
    return fp


def toggle(body=None):
    body = body or _body()
    if body is None:
        return
    fp = flat_pattern(body)
    set_flat(body, not (fp is not None and fp.SWFlattened))


class Command:
    def GetResources(self):
        return {"Pixmap": "SheetMetal_Unfold", "MenuText": "Flatten",
                "ToolTip": "Shows the part as its flat pattern. Click again to fold it back.",
                "Checkable": is_flat()}

    def IsActive(self):
        from . import smnobends
        return _body() is not None and not smnobends.blocked()

    def Activated(self, checked=None):
        toggle()


class ExitCommand:
    def GetResources(self):
        return {"Pixmap": "SheetMetal_Unfold", "MenuText": "Exit Flatten",
                "ToolTip": "Folds the part back."}

    def IsActive(self):
        return is_flat()

    def Activated(self):
        body = _body()
        if body is not None:
            set_flat(body, False)


def blocked():
    ""
    try:
        from . import smnobends
        return is_flat() or smnobends.blocked()
    except Exception as _fw_err:
        _fw_log("smflatten.py:569", _fw_err)
        return False


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
        Gui.addCommand(EXIT_COMMAND, ExitCommand())
    checkstate.register(COMMAND, is_flat)
