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
import Part

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
    from . import pmboxes
except ImportError:
    Gui = None

V = App.Vector


# --------------------------------------------------------------------- small helpers
def _doc():
    return App.ActiveDocument


def _is_drawing(doc):
    return doc is not None and any(o.isDerivedFrom("TechDraw::DrawPage") for o in doc.Objects)


def _is_assembly(doc):
    return doc is not None and any(o.TypeId == "Assembly::AssemblyObject" for o in doc.Objects)


def _part(doc):
    return doc is not None and not _is_drawing(doc) and not _is_assembly(doc)


def _solids(doc):
    """The part's solid bodies: PartDesign bodies and loose solid features (their tips, not the steps)."""
    out = []
    for o in doc.Objects:
        if not o.isDerivedFrom("Part::Feature") and o.TypeId != "PartDesign::Body":
            continue
        if o.TypeId == "PartDesign::Body" or (o.getParentGeoFeatureGroup() is None and not o.InList):
            shape = getattr(o, "Shape", None)
            if shape is not None and not shape.isNull() and shape.Solids:
                if o.TypeId == "PartDesign::Body" or not any(i.TypeId == "PartDesign::Body" for i in o.InList):
                    out.append(o)
    return out


def _picked_objects():
    out = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        obj = sel.Object
        for path in sel.SubElementNames or [""]:
            found = obj
            for part in path.split(".")[:-1]:
                child = obj.Document.getObject(part)
                if child is not None:
                    found = child
            if found not in out:
                out.append(found)
    return out


def _picked_subs(prefix):
    """[(object, element, shape)] of the picked faces / edges."""
    out = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        for sub, shape in zip(sel.SubElementNames, sel.SubObjects):
            leaf = sub.split(".")[-1]
            if leaf.startswith(prefix):
                out.append((sel.Object, sub, shape))
    return out


def _sheet(doc, name, label):
    for o in doc.Objects:
        if o.TypeId == "Spreadsheet::Sheet" and o.Label == label:
            return o, False
    s = doc.addObject("Spreadsheet::Sheet", name)
    s.Label = label
    return s, True


def _column(n):
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _plain_number(value):
    try:
        float(str(value))
        return True
    except ValueError:
        return False


def _fill(sheet, rows):
    for r, row in enumerate(rows, 1):
        for c, value in enumerate(row):
            col = chr(ord("A") + c)
            sheet.set("%s%d" % (col, r), "'" + str(value) if isinstance(value, str) else str(value))
    try:
        sheet.setStyle("A1:%s1" % chr(ord("A") + len(rows[0]) - 1), "bold")
    except Exception as _fw_err:
        _fw_log("insertextras.py:129", _fw_err)


if Gui is not None:
    def _drawn(name):
        """A PM header picture the pack may lack: the pack's family, else our drawing (resources/simicons)."""
        try:
            from . import simicons
            return simicons.family_or_drawing(name)
        except Exception:
            return name

    class _PM:
        """A PropertyManager page: a form, OK / Cancel."""

        def __init__(self, title, icon=None):
            self.form = QtWidgets.QWidget()
            self.form.setWindowTitle(title)
            self.form.setProperty("swstyle_pm_title", title)
            if icon:
                self.form.setProperty("swstyle_pm_icon", icon)
            self.lay = QtWidgets.QFormLayout(self.form)
            self.message = QtWidgets.QLabel("")
            self.message.setWordWrap(True)

        def finish(self):
            self.lay.addRow(self.message)

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def ok(self):
            return True

        def accept(self):
            try:
                if not self.ok():
                    return False
            except Exception as error:
                self.message.setText(str(error))
                self.message.setStyleSheet("color: #c00000;")
                return False
            Gui.Control.closeDialog()
            return True

        def reject(self):
            Gui.Control.closeDialog()
            return True

    def _pick_list(owner, label, prefix):
        """A selection box (light blue: the active one) that takes picks of prefix ("Face", "Edge" or "" for objects)."""
        box = QtWidgets.QListWidget()
        box.setMaximumHeight(70)
        pmboxes.mark(box, True)
        box.items = []
        owner.lay.addRow(QtWidgets.QLabel(label))
        owner.lay.addRow(box)

        def take():
            for sel in Gui.Selection.getSelectionEx("", 0):
                for sub, shape in zip(sel.SubElementNames or [""], sel.SubObjects or [None]):
                    leaf = sub.split(".")[-1] if sub else ""
                    if prefix and not leaf.startswith(prefix):
                        continue
                    key = (sel.Object.Name, sub)
                    if key in [(o.Name, s) for o, s, _ in box.items]:
                        continue
                    box.items.append((sel.Object, sub, shape))
                    box.addItem("%s %s" % (sel.Object.Label, leaf) if leaf else sel.Object.Label)
        box.take = take
        take()
        return box


# --------------------------------------------------------------------- Imported...
IMPORT_FILTER = "3D files (*.step *.stp *.iges *.igs *.brep *.brp *.stl *.obj);;All files (*)"


def insert_imported(doc, path):
    """An Imported body in the part from a STEP / IGES / BREP (or mesh) file."""
    ext = os.path.splitext(path)[1].lower()
    doc.openTransaction("Imported")
    try:
        if ext in (".stl", ".obj"):
            import Mesh
            mesh = Mesh.Mesh(path)
            shape = Part.Shape()
            shape.makeShapeFromMesh(mesh.Topology, 0.05)
            try:
                shape = Part.makeSolid(shape)
            except Exception as _fw_err:
                _fw_log("insertextras.py:212", _fw_err)
        else:
            shape = Part.read(path)
        obj = doc.addObject("Part::Feature", "Imported")
        obj.Shape = shape
        from . import naming
        obj.Label = naming.next_label(doc, "Imported")
        obj.addProperty("App::PropertyFile", "SourceFile", "Imported", "The file this body came from")
        obj.SourceFile = path
        doc.recompute()
    finally:
        doc.commitTransaction()
    return obj


# --------------------------------------------------------------------- FeatureWorks
FW_GROUP = "BaseApp/Preferences/Mod/FreeWorks/FeatureWorks"
KINDS = ("Extrudes", "Revolves", "Holes", "Fillets", "Chamfers")


def fw_options():
    p = App.ParamGet("User parameter:" + FW_GROUP)
    return {"mode": p.GetString("Mode", "Automatic"),
            "kinds": [k for k in KINDS if p.GetBool(k, True)],
            "max_fillet": p.GetFloat("MaxFillet", 20.0),
            "body": p.GetBool("MakeBody", True)}


def set_fw_options(mode, kinds, max_fillet, body):
    p = App.ParamGet("User parameter:" + FW_GROUP)
    p.SetString("Mode", mode)
    for k in KINDS:
        p.SetBool(k, k in kinds)
    p.SetFloat("MaxFillet", max_fillet)
    p.SetBool("MakeBody", body)


def _same_cylinder(faces, i, tol=1e-6):
    """The other cylinder faces on face i's axis line with its radius (the halves of a split round face)."""
    s = faces[i].Surface
    out = []
    for j, g in enumerate(faces):
        t = g.Surface
        if j == i or t.TypeId != "Part::GeomCylinder" or abs(t.Radius - s.Radius) > tol:
            continue
        if t.Axis.cross(s.Axis).Length > 1e-6:
            continue
        d = t.Center - s.Center
        if (d - s.Axis * d.dot(s.Axis)).Length > 1e-5:
            continue
        out.append(j)
    return out


def recognize(shape, kinds=KINDS, max_fillet=20.0):
    """[(kind, size text, [face indices])] recognised on a dumb solid."""
    found = []
    faces = shape.Faces
    done = set()
    for i, f in enumerate(faces):
        s = f.Surface
        if i in done:
            continue
        if s.TypeId == "Part::GeomCylinder":
            # a hole: the solid is outside the cylinder (its face points in)
            u0, u1, v0, v1 = f.ParameterRange
            p = f.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
            n = f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
            axis_pt = s.Center + s.Axis * (p - s.Center).dot(s.Axis)
            inward = (axis_pt - p).dot(n) > 0
            # STEP/IGES split a round hole in halves (periodic faces split on export): the faces on the
            # same axis line with the same radius count as one round face
            group = [i] + [j for j in _same_cylinder(faces, i) if j not in done]
            span = sum(abs(faces[j].ParameterRange[1] - faces[j].ParameterRange[0]) for j in group)
            full = span > 6.0
            if full and len(group) > 1:
                v0 = min(faces[j].ParameterRange[2] for j in group)
                v1 = max(faces[j].ParameterRange[3] for j in group)
            if "Holes" in kinds and inward and full:
                depth = abs(v1 - v0)
                found.append(("Hole", "⌀%.2f x %.2f deep" % (2 * s.Radius, depth), [j + 1 for j in group]))
                done.update(group)
                continue
            if "Fillets" in kinds and not full and s.Radius <= max_fillet:
                found.append(("Fillet", "R%.2f" % s.Radius, [i + 1]))
                done.add(i)
                continue
            if "Extrudes" in kinds and full and not inward:
                found.append(("Boss-Extrude", "⌀%.2f x %.2f" % (2 * s.Radius, abs(v1 - v0)), [j + 1 for j in group]))
                done.update(group)
        elif s.TypeId == "Part::GeomTorus" and "Fillets" in kinds and s.MinorRadius <= max_fillet:
            found.append(("Fillet", "R%.2f" % s.MinorRadius, [i + 1]))
            done.add(i)
        elif s.TypeId in ("Part::GeomSurfaceOfRevolution", "Part::GeomCone", "Part::GeomSphere") and \
                "Revolves" in kinds:
            found.append(("Revolve", s.TypeId.split("Geom")[-1], [i + 1]))
            done.add(i)
        elif s.TypeId == "Part::GeomPlane" and "Chamfers" in kinds and f.Area < 0.05 * shape.Area:
            # a narrow plane strip between two faces at an angle: a chamfer
            n = f.normalAt(0, 0)
            angles = []
            for e in f.Edges:
                for g in shape.ancestorsOfType(e, Part.Face):
                    if g.isSame(f) or g.Surface.TypeId != "Part::GeomPlane":
                        continue
                    a = abs(math_deg(n.getAngle(g.normalAt(0, 0))))
                    angles.append(a)
            if len(angles) >= 2 and all(20 < a < 70 for a in angles[:2]):
                bb = f.BoundBox
                found.append(("Chamfer", "%.2f wide" % min(x for x in (bb.XLength, bb.YLength, bb.ZLength) if x > 1e-6)
                              if any(x > 1e-6 for x in (bb.XLength, bb.YLength, bb.ZLength)) else "", [i + 1]))
                done.add(i)
    if "Extrudes" in kinds:
        planar = [i for i, f in enumerate(faces) if f.Surface.TypeId == "Part::GeomPlane" and i not in done]
        if planar:
            bb = shape.BoundBox
            found.insert(0, ("Base-Extrude", "%.1f x %.1f x %.1f" % (bb.XLength, bb.YLength, bb.ZLength),
                             [i + 1 for i in planar]))
    return found


def math_deg(rad):
    import math
    return math.degrees(rad)


def _hole_feature(body, face):
    """A Hole found on the solid as an editable PartDesign Subtractive Cylinder: radius, depth and
    place from the hole's cylinder."""
    s = face.Surface
    u0, u1, v0, v1 = face.ParameterRange
    axis = App.Vector(s.Axis).normalize()
    lo, hi = min(v0, v1), max(v0, v1)
    base = s.Center + axis * lo
    cyl = body.newObject("PartDesign::SubtractiveCylinder", "Hole")
    cyl.Radius = s.Radius
    cyl.Height = hi - lo
    cyl.Placement = App.Placement(base, App.Rotation(App.Vector(0, 0, 1), axis))
    return cyl


def _fillet_edges(shape, face):
    """The sharp edges of shape (the solid without its fillets) that a found fillet face rounded:
    straight edges along the fillet's axis, about one to two radii from it."""
    import Part
    s = face.Surface
    axis = App.Vector(s.Axis).normalize()
    r = s.Radius
    out = []
    for i, e in enumerate(shape.Edges, 1):
        try:
            if e.Curve.TypeId != "Part::GeomLine":
                continue
            d = (e.Vertexes[-1].Point - e.Vertexes[0].Point)
            if d.Length < 1e-9 or abs(abs(d.normalize().dot(axis)) - 1) > 1e-6:
                continue
            m = e.CenterOfMass - s.Center
            off = (m - axis * m.dot(axis)).Length
            if r * 0.99 < off < r * 2.01 and e.distToShape(face)[0] < r * 1.01:
                out.append("Edge%d" % i)
        except Exception as _fw_err:
            _fw_log("insertextras.py:374", _fw_err)
            continue
    return out


def make_features(doc, target, source, found):
    """FeatureWorks' Recognize Features: the found holes and fillets become real features of the
    body (a Subtractive Cylinder per hole, a Fillet per radius) on the solid with them taken out
    (OpenCASCADE defeaturing). Kept only when the rebuilt body has the source's volume; else the
    body stays on the imported solid. Returns the features made."""
    import Part
    shape = source.Shape
    holes = [(k, f) for k, _s, f in found if k == "Hole"]
    fillets = [(k, f) for k, _s, f in found if k == "Fillet" and shape.Faces[f[0] - 1].Surface.TypeId == "Part::GeomCylinder"]
    if not holes and not fillets:
        return []
    faces = [shape.Faces[i - 1] for _k, f in holes + fillets for i in f]
    try:
        plain = shape.defeaturing(faces)
        if not plain.isValid() or not plain.Solids:
            return []
    except Exception as _fw_err:
        _fw_log("insertextras.py:396", _fw_err)
        return []
    made = []
    base = doc.addObject("Part::Feature", "Base")
    base.Shape = plain
    base.Label = source.Label + " base"
    try:
        base.Visibility = False
    except Exception as _fw_err:
        _fw_log("insertextras.py:402", _fw_err)
    target.BaseFeature = base
    doc.recompute()
    try:
        for _k, f in holes:
            made.append(_hole_feature(target, shape.Faces[f[0] - 1]))
        doc.recompute()
        by_radius = {}
        for _k, f in fillets:
            face = shape.Faces[f[0] - 1]
            by_radius.setdefault(round(face.Surface.Radius, 6), []).append(face)
        for radius, group in sorted(by_radius.items()):
            tip = target.Tip
            edges = sorted({e for face in group for e in _fillet_edges(tip.Shape, face)})
            if not edges:
                continue
            fil = target.newObject("PartDesign::Fillet", "Fillet")
            fil.Base = (tip, edges)
            fil.Radius = radius
            doc.recompute()
            made.append(fil)
        ok = all("Invalid" not in o.State for o in made) and \
            abs(target.Shape.Volume - shape.Volume) <= 1e-6 * max(1.0, shape.Volume)
    except Exception:
        ok = False
    if not ok:
        for o in reversed(made):
            try:
                target.removeObject(o)
                doc.removeObject(o.Name)
            except Exception as _fw_err:
                _fw_log("insertextras.py:433", _fw_err)
        target.BaseFeature = source
        doc.removeObject(base.Name)
        doc.recompute()
        return []
    import re
    for o in made:
        if not re.search(r"\d+$", o.Label):
            o.Label = naming_label(doc, o)
    return made


def naming_label(doc, obj):
    try:
        from . import naming
        return naming.next_label(doc, "Fillet" if obj.TypeId == "PartDesign::Fillet" else "Hole")
    except Exception:
        return obj.Label


def make_recognized(doc, source, found, body=True):
    """A body built on the imported solid, with a Recognized folder of the found features' faces;
    the holes and fillets also become real, editable features of the body (make_features)."""
    doc.openTransaction("Recognize Features")
    try:
        target = None
        if body:
            target = doc.addObject("PartDesign::Body", "Body")
            target.BaseFeature = source
            target.Label = source.Label + " (recognized)"
            doc.recompute()
            try:
                make_features(doc, target, source, found)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: FeatureWorks features: %s\n" % error)
        group = doc.addObject("App::DocumentObjectGroup", "RecognizedFeatures")
        group.Label = "Recognized Features"
        counts = {}
        for kind, size, faces in found:
            counts[kind] = counts.get(kind, 0) + 1
            ref = doc.addObject("App::FeaturePython", "Recognized")
            ref.addProperty("App::PropertyLinkSub", "Faces", "Recognized", "The faces of this feature")
            ref.addProperty("App::PropertyString", "Kind", "Recognized", "The feature type")
            ref.addProperty("App::PropertyString", "Size", "Recognized", "Its size")
            ref.Faces = (source, ["Face%d" % i for i in faces])
            ref.Kind, ref.Size = kind, size
            ref.Label = "%s%d (%s)" % (kind, counts[kind], size) if size else "%s%d" % (kind, counts[kind])
            if App.GuiUp:
                ref.ViewObject.Proxy = 0
            group.addObject(ref)
        doc.recompute()
    finally:
        doc.commitTransaction()
    return target, group


# --------------------------------------------------------------------- Mate Reference
MATE_TYPES = ["Default", "Tangent", "Coincident", "Concentric", "Parallel"]
ALIGNMENTS = ["Any", "Aligned", "Anti-Aligned", "Closest"]


def make_mate_reference(doc, refs, name="Default"):
    """refs: [(object, element, type, alignment)] for primary, secondary, tertiary."""
    group = None
    for o in doc.Objects:
        if o.Label == "MateReferences" and o.TypeId == "App::DocumentObjectGroup":
            group = o
    if group is None:
        group = doc.addObject("App::DocumentObjectGroup", "MateReferences")
        group.Label = "MateReferences"
    obj = doc.addObject("App::FeaturePython", "MateReference")
    obj.Label = name
    for i, slot in enumerate(("Primary", "Secondary", "Tertiary")):
        obj.addProperty("App::PropertyLinkSub", slot + "Entity", slot, "Reference entity")
        obj.addProperty("App::PropertyEnumeration", slot + "MateType", slot, "Mate type")
        obj.addProperty("App::PropertyEnumeration", slot + "Alignment", slot, "Mate alignment")
        setattr(obj, slot + "MateType", MATE_TYPES)
        setattr(obj, slot + "Alignment", ALIGNMENTS)
        if i < len(refs) and refs[i][0] is not None:
            o, sub, kind, align = refs[i]
            setattr(obj, slot + "Entity", (o, [sub] if sub else []))
            setattr(obj, slot + "MateType", kind)
            setattr(obj, slot + "Alignment", align)
    obj.addProperty("App::PropertyString", "SWStyleKind", "Base", "")
    obj.SWStyleKind = "MateReference"
    if App.GuiUp:
        obj.ViewObject.Proxy = 0
    group.addObject(obj)
    doc.recompute()
    return obj


# --------------------------------------------------------------------- Fillet Bead (weldments)
class FilletBead:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyLinkSubList", "FaceSet1", "Fillet Bead", "First face set")
        add("App::PropertyLinkSubList", "FaceSet2", "Fillet Bead", "Second face set")
        add("App::PropertyLength", "FilletSize", "Fillet Bead", "Leg length")
        add("App::PropertyEnumeration", "BeadType", "Fillet Bead", "Full Length, Intermittent or Staggered")
        add("App::PropertyLength", "BeadLength", "Fillet Bead", "Length of each bead (intermittent)")
        add("App::PropertyLength", "Pitch", "Fillet Bead", "Pitch (intermittent)")
        add("App::PropertyFloat", "TotalLength", "Fillet Bead", "Length of all beads")
        obj.BeadType = ["Full Length", "Intermittent", "Staggered"]
        obj.FilletSize = 3.0
        obj.BeadLength = 10.0
        obj.Pitch = 20.0
        obj.setEditorMode("TotalLength", 1)
        self._more(obj)
        obj.Proxy = self

    @staticmethod
    def _more(obj):
        ""
        add = obj.addProperty
        if "TangentPropagation" not in obj.PropertiesList:
            add("App::PropertyBool", "TangentPropagation", "Fillet Bead", "Add the faces tangent to the picked ones")
            obj.TangentPropagation = False      # old beads were built from the picked faces only
            add("App::PropertyBool", "OtherSide", "Fillet Bead", "A bead on the other side of the joint too")
            add("App::PropertyLength", "OtherFilletSize", "Fillet Bead", "Leg length on the other side")
            obj.OtherFilletSize = 3.0

    def onDocumentRestored(self, obj):
        self._more(obj)

    @staticmethod
    def _faces(links):
        out = []
        for o, subs in links or []:
            shape = o.Shape
            for s in subs:
                out.append(shape.getElement(s))
        return out

    def execute(self, obj):
        from . import weweld
        froms, tos = self._faces(obj.FaceSet1), self._faces(obj.FaceSet2)
        shapes = [o.Shape for o, _subs in (obj.FaceSet1 or [])]
        if getattr(obj, "TangentPropagation", False):
            def spread(faces, links):
                out = []
                for f in faces:
                    shape = next((o.Shape for o, _s in links or [] if any(f.isSame(x) for x in o.Shape.Faces)), None)
                    for g in (weweld._tangent_chain(shape, f) if shape is not None else [f]):
                        if not any(g.isSame(x) for x in out):
                            out.append(g)
                return out
            froms, tos = spread(froms, obj.FaceSet1), spread(tos, obj.FaceSet2)
        kind = obj.BeadType.replace("Full Length", "Full")
        welds = list(weweld.weld_edges(froms, tos))
        beads, total = [], 0.0
        jobs = [(edge, f, g, obj.FilletSize.Value, 0.0, False) for edge, f, g in welds]
        if getattr(obj, "OtherSide", False):
            # Staggered: the other side's beads sit in the gaps of this side's
            start = obj.Pitch.Value / 2.0 if kind == "Staggered" else 0.0
            jobs += [(e, h, g, obj.OtherFilletSize.Value, start, back) for e, h, g, back in weweld._other_side(welds, shapes, tos)]
        for edge, f, g, size, start, back in jobs:
            for piece in weweld._pieces(edge, kind, obj.BeadLength.Value, obj.Pitch.Value, start, back):
                b = weweld.bead(piece, f, g, size)
                if b is not None and not b.isNull():
                    beads.append(b)
                    total += piece.Length
        obj.TotalLength = total
        obj.Shape = Part.makeCompound(beads) if beads else Part.Shape()

    def dumps(self):
        return None

    def loads(self, _state):
        return None


def make_fillet_bead(doc, set1, set2, size=3.0, kind="Full Length", length=10.0, pitch=20.0,
                     tangent=True, other=False, other_size=None):
    from . import naming
    doc.openTransaction("Fillet Bead")
    try:
        obj = doc.addObject("Part::FeaturePython", "FilletBead")
        FilletBead(obj)
        obj.Label = naming.next_label(doc, "Fillet Bead")
        obj.FaceSet1 = [(o, [s]) for o, s in set1]
        obj.FaceSet2 = [(o, [s]) for o, s in set2]
        obj.FilletSize, obj.BeadType, obj.BeadLength, obj.Pitch = size, kind, length, pitch
        obj.TangentPropagation, obj.OtherSide = bool(tangent), bool(other)
        obj.OtherFilletSize = other_size if other_size else size
        if App.GuiUp:
            obj.ViewObject.Proxy = 0
            obj.ViewObject.ShapeAppearance = (App.Material(DiffuseColor=(0.55, 0.55, 0.6)),)
        doc.recompute()
    finally:
        doc.commitTransaction()
    return obj


# --------------------------------------------------------------------- Decimate Mesh Body
def mesh_targets(objs):
    return [o for o in objs if o.TypeId in ("Mesh::Feature",) or hasattr(o, "Mesh")]


def decimate(obj, reduction, tolerance=0.1):
    """Fewer facets on a mesh body: reduction 0..1 is the share of facets taken out."""
    mesh = obj.Mesh.copy()
    before = mesh.CountFacets
    mesh.decimate(tolerance, reduction)
    obj.Document.openTransaction("Decimate Mesh Body")
    try:
        obj.Mesh = mesh
        obj.Document.recompute()
    finally:
        obj.Document.commitTransaction()
    return before, mesh.CountFacets


# --------------------------------------------------------------------- multibody Exploded View
class PartExplode:
    """The exploded view of a multibody part: steps of bodies moved along a direction."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyString", "Steps", "Exploded View", "Steps (JSON)")
        obj.addProperty("App::PropertyString", "Home", "Exploded View", "Collapsed placements (JSON)")
        obj.addProperty("App::PropertyBool", "Exploded", "Exploded View", "Shown exploded")
        obj.setEditorMode("Steps", 2)
        obj.setEditorMode("Home", 2)
        obj.Steps = "[]"
        obj.Home = "{}"
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, _state):
        return None


def _pl(p):
    return [list(p.Base), list(p.Rotation.Q)]


def _unpl(v):
    return App.Placement(V(*v[0]), App.Rotation(*v[1]))


def explode(obj, on):
    doc = obj.Document
    home = json.loads(obj.Home or "{}")
    steps = json.loads(obj.Steps or "[]")
    for name, pl in home.items():
        o = doc.getObject(name)
        if o is not None:
            o.Placement = _unpl(pl)
    if on:
        for step in steps:
            _explode_step(doc, step)
    obj.Exploded = on
    doc.recompute()


def _centre(o):
    try:
        return o.Shape.BoundBox.Center
    except Exception:
        return o.Placement.Base


def _explode_step(doc, step):
    ""


    bodies = [doc.getObject(n) for n in step["bodies"]]
    bodies = [o for o in bodies if o is not None]
    if not bodies:
        return
    d = V(*step["direction"])
    centre = V()
    for o in bodies:
        centre += _centre(o)
    centre = centre * (1.0 / len(bodies))
    angle = float(step.get("angle", 0.0) or 0.0)
    axis = V(*step.get("rot_axis", step["direction"]))
    for o in bodies:
        if step.get("type") == "Radial":
            out = _centre(o) - centre
            out = out - d * out.dot(d)
            move = (out.normalize() * step["distance"]) if out.Length > 1e-9 else V()
        else:
            move = d * step["distance"]
        pl = App.Placement(o.Placement.Base + move, o.Placement.Rotation)
        if angle:
            pivot = (_centre(o) if step.get("about_own", True) else centre) + move
            turn = App.Placement(V(), App.Rotation(axis, angle), pivot)
            pl = turn.multiply(pl)
        o.Placement = pl


def make_part_explode(doc, steps):
    """steps: [{"bodies": [names], "direction": [x, y, z], "distance": d}]"""
    doc.openTransaction("Exploded View")
    try:
        obj = None
        for o in doc.Objects:
            if isinstance(getattr(o, "Proxy", None), PartExplode):
                obj = o
        if obj is None:
            obj = doc.addObject("App::FeaturePython", "ExplView")
            PartExplode(obj)
            obj.Label = "ExplView1"
            if App.GuiUp:
                obj.ViewObject.Proxy = 0
        home = json.loads(obj.Home or "{}")
        old = json.loads(obj.Steps or "[]")
        if obj.Exploded:
            explode(obj, False)
        for step in steps:
            for name in step["bodies"]:
                if name not in home:
                    home[name] = _pl(doc.getObject(name).Placement)
        obj.Home = json.dumps(home)
        obj.Steps = json.dumps(old + steps)
        explode(obj, True)
    finally:
        doc.commitTransaction()
    return obj


# --------------------------------------------------------------------- Mirror Part
MIRROR_TRANSFER = (("SolidBodies", "Solid bodies", True), ("SurfaceBodies", "Surface bodies", False),
                   ("Axes", "Axes", False), ("Planes", "Planes", False), ("CosmeticThreads", "Cosmetic threads", False),
                   ("AbsorbedSketches", "Absorbed sketches", False), ("UnabsorbedSketches", "Unabsorbed sketches", False),
                   ("CustomProperties", "Custom properties", False), ("CoordinateSystems", "Coordinate systems", False),
                   ("ModelDimensions", "Model dimensions", False), ("HoleWizardData", "Hole Wizard data", False),
                   ("SheetMetalInfo", "Sheet metal information", False))


def mirror_part(source_doc, source, normal, base=V(0, 0, 0), name=None, transfer=None):
    ""


    new = App.newDocument(name or ("Mirror" + source_doc.Name))
    src = None
    if source_doc.FileName:

        # needs the new part saved first), so later changes to the original come through on rebuild
        try:
            from . import insertpart, surfacefeatures
            src = surfacefeatures.make(insertpart.INSERT_PART, new, edit=False, File=source_doc.FileName,
                                       **dict(transfer or {}))
            src.Label = source.Label + "->"
            if src.Shape.isNull():
                raise RuntimeError("nothing read")
        except Exception as error:
            App.Console.PrintWarning("FreeCAD Mirror Part: linked copy failed (%s), copying instead\n" % error)
            if src is not None:
                new.removeObject(src.Name)
            src = None
    if src is None:
        src = new.addObject("Part::Feature", "Source")
        src.Shape = source.Shape.copy()
        src.Label = source.Label
    mir = new.addObject("Part::Mirroring", "MirrorPart")
    mir.Source = src
    mir.Normal = normal
    mir.Base = base
    mir.Label = "Mirror" + source.Label
    new.recompute()
    if App.GuiUp:
        try:
            src.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("insertextras.py:804", _fw_err)
    return new, mir


# --------------------------------------------------------------------- Derive Part
def derive_part(source_doc=None, edit=True):
    ""


    src = source_doc or _doc()
    if src is None:
        return None, None
    if not src.FileName and App.GuiUp:
        answer = QtWidgets.QMessageBox.question(
            Gui.getMainWindow(), "Derive Part",
            "The part must be saved before a part can be derived from it. Save it now?",
            QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Cancel)
        if answer != QtWidgets.QMessageBox.Save:
            return None, None
        App.setActiveDocument(src.Name)
        Gui.runCommand("Std_SaveAs", 0)
    if not src.FileName:
        return None, None
    from . import insertpart, newdoc, surfacefeatures
    try:
        new = newdoc.make("Part")
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Derive Part: new part: %s\n" % error)
        new = App.newDocument("Part")
    body = next((o for o in new.Objects if o.TypeId == "PartDesign::Body"), None)
    feat = surfacefeatures.make(insertpart.INSERT_PART, new, edit=False, File=src.FileName)
    feat.Label = (os.path.splitext(os.path.basename(src.FileName))[0] or src.Label) + "->"
    if body is not None and not feat.Shape.isNull():
        body.BaseFeature = feat              # later features build on the derived bodies
        new.recompute()
    if App.GuiUp:
        try:
            feat.ViewObject.Visibility = body is None
        except Exception as _fw_err:
            _fw_log("insertextras.py:derive view", _fw_err)
        if edit:
            Gui.Selection.clearSelection()
            Gui.getDocument(new.Name).setEdit(feat.Name)
    return new, feat


# --------------------------------------------------------------------- Sketch From Drawing
def drawing_views():
    out = []
    for d in App.listDocuments().values():
        for o in d.Objects:
            if o.isDerivedFrom("TechDraw::DrawViewPart"):
                out.append(o)
    return out


def sketch_from_view(doc, view, body=None):
    """A sketch in the part with the drawing view's visible edges, on the plane the view looks at."""
    edges = []
    scale = getattr(view, "Scale", 1.0) or 1.0
    try:
        edges = view.getVisibleEdges()
    except Exception:
        edges = []
    direction = getattr(view, "Direction", V(0, 0, 1))
    sk_parent = body
    if sk_parent is not None:
        sk = sk_parent.newObject("Sketcher::SketchObject", "Sketch")
    else:
        sk = doc.addObject("Sketcher::SketchObject", "Sketch")
    sk.Label = "Sketch from " + view.Label
    rot = App.Rotation(V(0, 0, 1), direction)
    sk.Placement = App.Placement(V(0, 0, 0), rot)
    for e in edges:
        e = e.copy()
        e.scale(1.0 / scale)
        e.mirror(V(0, 0, 0), V(0, 1, 0))          # drawing Y runs down; the sketch's runs up
        try:
            if e.Curve.TypeId == "Part::GeomLine":
                a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
                if (a - b).Length > 1e-7:
                    sk.addGeometry(Part.LineSegment(V(a.x, a.y, 0), V(b.x, b.y, 0)))
            elif e.Curve.TypeId == "Part::GeomCircle":
                c = e.Curve
                if e.isClosed():
                    sk.addGeometry(Part.Circle(V(c.Center.x, c.Center.y, 0), V(0, 0, 1), c.Radius))
                else:
                    pts = [v.Point for v in e.Vertexes]
                    mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
                    a, b = pts[0], pts[-1]
                    if (mid.x - a.x) * (b.y - mid.y) - (mid.y - a.y) * (b.x - mid.x) < 0:
                        a, b = b, a     # counter-clockwise, as the sketcher draws arcs: a clockwise (-Z) arc can jump on the next solve
                    sk.addGeometry(Part.Arc(V(a.x, a.y, 0), V(mid.x, mid.y, 0), V(b.x, b.y, 0)))
            else:
                pts = [V(p.x, p.y, 0) for p in e.discretize(20)]
                sk.addGeometry(_interp(pts))
        except Exception as _fw_err:
            _fw_log("insertextras.py:859", _fw_err)
            continue
    doc.recompute()
    return sk


def _interp(pts):
    c = Part.BSplineCurve()
    c.interpolate(pts)
    return c


# --------------------------------------------------------------------- DXF / DWG
def _import_2d(doc, path):
    """The objects a DXF / DWG import adds to doc, as plain shapes."""
    before = set(o.Name for o in doc.Objects)
    ext = os.path.splitext(path)[1].lower()
    grp = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
    keep = (grp.GetBool("dxfShowDialog", True), grp.GetInt("DxfImportMode", 2),
            grp.GetBool("dxfImportAsShapes", False), grp.GetBool("dxfImportAsDraft", False))
    grp.SetBool("dxfShowDialog", False)       # no importer pop-up: plain shapes, the sketch takes them
    grp.SetInt("DxfImportMode", 2)
    grp.SetBool("dxfImportAsShapes", True)
    grp.SetBool("dxfImportAsDraft", False)
    try:
        if ext == ".dwg":
            import importDWG
            importDWG.insert(path, doc.Name)
        else:
            import importDXF
            importDXF.insert(path, doc.Name)
    finally:
        grp.SetBool("dxfShowDialog", keep[0])
        grp.SetInt("DxfImportMode", keep[1])
        grp.SetBool("dxfImportAsShapes", keep[2])
        grp.SetBool("dxfImportAsDraft", keep[3])
    return [o for o in doc.Objects if o.Name not in before]


def insert_dxf_drawing(doc, path, page=None):
    ""
    made = _import_2d(doc, path)
    shapes = [o for o in made if getattr(o, "Shape", None) is not None and not o.Shape.isNull()]
    if not shapes:
        return None
    page = page or next(o for o in doc.Objects if o.isDerivedFrom("TechDraw::DrawPage"))
    view = doc.addObject("TechDraw::DrawViewPart", "DXF")
    view.Label = os.path.splitext(os.path.basename(path))[0]
    page.addView(view)
    view.Source = shapes
    view.Direction = V(0, 0, 1)
    view.Scale = 1.0
    if App.GuiUp:
        for o in shapes:
            o.ViewObject.Visibility = False
    doc.recompute()
    return view


def insert_dxf(doc, path, body=None, plane="Front"):
    """The file's 2D geometry as a sketch on a plane of the part."""
    made = _import_2d(doc, path)
    edges = []
    for o in made:
        shape = getattr(o, "Shape", None)
        if shape is not None and not shape.isNull():
            edges += shape.Edges
    sk = body.newObject("Sketcher::SketchObject", "Sketch") if body is not None else \
        doc.addObject("Sketcher::SketchObject", "Sketch")
    sk.Label = os.path.splitext(os.path.basename(path))[0]
    normal = {"Front": V(0, 0, 1), "Top": V(0, 1, 0), "Right": V(1, 0, 0)}[plane]
    if body is not None:
        origin = body.Origin
        feat = {"Front": "XY_Plane", "Top": "XZ_Plane", "Right": "YZ_Plane"}[plane]
        for f in origin.OriginFeatures:
            if f.Role == feat:
                sk.AttachmentSupport = [(f, "")]
                sk.MapMode = "FlatFace"
    else:
        sk.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), normal))
    geos = []           # added in one call: one at a time took 15 s for a 1500-entity file (fix152)
    for e in edges:
        try:
            if e.Curve.TypeId == "Part::GeomLine":
                a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
                geos.append(Part.LineSegment(V(a.x, a.y, 0), V(b.x, b.y, 0)))
            elif e.Curve.TypeId == "Part::GeomCircle" and e.isClosed():
                geos.append(Part.Circle(V(e.Curve.Center.x, e.Curve.Center.y, 0), V(0, 0, 1), e.Curve.Radius))
            else:
                pts = [V(p.x, p.y, 0) for p in e.discretize(24)]
                geos.append(_interp(pts))
        except Exception as _fw_err:
            _fw_log("insertextras.py:951", _fw_err)
            continue
    if geos:
        try:
            sk.addGeometry(geos)
        except Exception:
            for g in geos:
                try:
                    sk.addGeometry(g)
                except Exception as _fw_err:
                    _fw_log("insertextras.py:956", _fw_err)
    for o in made:                               # the importer's own temporaries go: the sketch holds it all
        try:
            doc.removeObject(o.Name)
        except Exception as _fw_err:
            _fw_log("insertextras.py:961", _fw_err)
    doc.recompute()
    return sk


# --------------------------------------------------------------------- Design Study > Parameters
def parameters_sheet(doc, create=True):
    for o in doc.Objects:
        if o.TypeId == "Spreadsheet::Sheet" and o.Label == "Parameters":
            return o
    if not create:
        return None
    s = doc.addObject("Spreadsheet::Sheet", "Parameters")
    s.Label = "Parameters"
    _fill(s, [["Name", "Category", "Value", "Units", "Linked to"]])
    return s


def parameters(doc):
    s = parameters_sheet(doc, False)
    out = []
    if s is None:
        return out
    r = 2
    while True:
        try:
            name = s.getContents("A%d" % r).lstrip("'")
        except Exception:
            name = ""
        if not name:
            break
        out.append({"name": name, "category": s.getContents("B%d" % r).lstrip("'"),
                    "value": s.getContents("C%d" % r).lstrip("'="), "units": s.getContents("D%d" % r).lstrip("'"),
                    "link": s.getContents("E%d" % r).lstrip("'")})
        r += 1
    return out


def set_parameters(doc, rows):
    """rows: [{"name", "category", "value", "units", "link"}]; a link "Object.Property" is driven by the value."""
    s = parameters_sheet(doc)
    doc.openTransaction("Parameters")
    try:
        r = 2
        while s.getContents("A%d" % r):
            for c in "ABCDE":
                s.set("%s%d" % (c, r), "")
            r += 1
        for r, row in enumerate(rows, 2):
            s.set("A%d" % r, "'" + row["name"])
            s.set("B%d" % r, "'" + row.get("category", ""))
            value = row.get("value", "0")
            units = row.get("units", "")
            s.set("C%d" % r, ("=%s %s" % (value, units)).strip() if units else str(value))
            s.set("D%d" % r, "'" + units)
            s.set("E%d" % r, "'" + row.get("link", ""))
            alias = "".join(ch for ch in row["name"] if ch.isalnum() or ch == "_") or "P%d" % r
            if alias[0].isdigit():
                alias = "P" + alias
            try:
                s.setAlias("C%d" % r, alias)
            except Exception as _fw_err:
                _fw_log("insertextras.py:1023", _fw_err)
            link = row.get("link", "")
            if "." in link:
                name, prop = link.split(".", 1)
                target = doc.getObject(name) or next((o for o in doc.Objects if o.Label == name), None)
                if target is not None:
                    try:
                        target.setExpression(prop, "<<%s>>.%s" % (s.Label, alias))
                    except Exception:
                        try:
                            target.setExpression(prop, "%s.%s" % (s.Name, alias))
                        except Exception as _fw_err:
                            _fw_log("insertextras.py:1035", _fw_err)
        doc.recompute()
    finally:
        doc.commitTransaction()
    return s


# --------------------------------------------------------------------- part tables
BOM_TEMPLATES = ("bom-standard", "bom-material")


def part_bom(doc, start=1, increment=1, template="bom-standard"):
    ""

    s, _ = _sheet(doc, "BillOfMaterials", "Bill of Materials")
    material = template == "bom-material"
    rows = [["ITEM NO.", "PART NUMBER", "DESCRIPTION"] + (["MATERIAL"] if material else []) + ["QTY."]]
    counts = {}
    for o in _solids(doc):
        key = o.Label.rstrip("0123456789")
        mat = ""
        try:
            mat = o.ShapeMaterial.Name
        except Exception as _fw_err:
            _fw_log("insertextras.py:1059", _fw_err)
        counts.setdefault(key, [o.Label, getattr(o, "Label2", ""), mat, 0])[3] += 1
    for i, (label, desc, mat, qty) in enumerate(counts.values()):
        rows.append([str(int(start) + i * int(increment)), label, desc] + ([mat] if material else []) + [qty])
    _fill(s, rows)
    doc.recompute()
    return s


def title_block_table(doc):
    s, _ = _sheet(doc, "TitleBlockTable", "Title Block Table")
    rows = [["Field", "Value"],
            ["Title", doc.Label], ["Part number", doc.Name], ["Created by", doc.CreatedBy],
            ["Company", doc.Company], ["Date", doc.CreationDate[:10]], ["Revision", doc.Id or "A"],
            ["Material", ""], ["Comment", doc.Comment]]
    _fill(s, rows)
    doc.recompute()
    return s


# ISO 2768-1 general tolerances for linear sizes, mm (f fine, m medium, c coarse, v very coarse)
ISO2768 = (("0.5 - 3", "0.05", "0.1", "0.2", "-"), ("3 - 6", "0.05", "0.1", "0.3", "0.5"),
           ("6 - 30", "0.1", "0.2", "0.5", "1"), ("30 - 120", "0.15", "0.3", "0.8", "1.5"),
           ("120 - 400", "0.2", "0.5", "1.2", "2.5"), ("400 - 1000", "0.3", "0.8", "2", "4"),
           ("1000 - 2000", "0.5", "1.2", "3", "6"), ("2000 - 4000", "-", "2", "4", "8"))


GRADES = (("f", "f (fine)"), ("m", "m (medium)"), ("c", "c (coarse)"), ("v", "v (very coarse)"))


def general_tolerance(doc, grade="m"):
    s, _ = _sheet(doc, "GeneralTolerance", "General Tolerance")
    try:
        doc.Meta = dict(doc.Meta, FwGeneralToleranceClass=str(grade))     # the class the part uses
    except Exception as _fw_err:
        _fw_log("insertextras.py:1094", _fw_err)
    rows = [["ISO 2768-%s: linear sizes (mm)" % grade, "f (fine)", "m (medium)", "c (coarse)", "v (very coarse)"]]
    rows += [list(r) for r in ISO2768]
    _fill(s, rows)
    doc.recompute()
    return s


def excel_design_table(doc, mode="auto", path=None, pick=False):
    """Blank, Auto-create (from the configurations) or From file (.csv / .xlsx)."""
    from . import editextras
    if mode == "file" and path:
        try:

            # makes the configurations
            from . import cmflows, dtoptions
            rows = dtoptions._read(path)
            if rows and cmflows.header_row(rows) is not None and any(
                    cmflows.parse_header(doc, c) for c in rows[cmflows.header_row(rows)][1:]):
                cmflows.import_file(doc, path)
                from . import configmanager
                return configmanager.table(doc).sheet
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: design table: %s\n" % error)
        s, _ = _sheet(doc, "DesignTable", "Design Table")
        if path.lower().endswith(".csv"):
            s.importFile(path, ",", '"', "\\")
        else:

            from . import dtoptions
            rows = dtoptions._read(path)
            if rows:
                for r, row in enumerate(rows, 1):
                    for c, value in enumerate(row, 1):
                        if str(value) != "":
                            s.set("%s%d" % (_column(c), r), "'" + str(value) if not _plain_number(value) else str(value))
        doc.recompute()
        return s
    if mode == "auto":
        try:
            from . import configs, cmflows, configmanager
            configs.table(doc)
            cmflows.restore_table(doc)
            if App.GuiUp and pick:
                cmflows.ask_auto_create(doc)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: auto-create design table: %s\n" % error)
    if mode == "blank":
        try:

            from . import configs, cmflows
            configs.table(doc)
            cmflows.restore_table(doc)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: blank design table: %s\n" % error)
    return editextras.design_table(doc, create=True)


# --------------------------------------------------------------------- Schematic / Markup File (drawing)
def insert_schematic(doc, page=None):
    """A schematic: a 2D sketch shown on the sheet as a view of its own (Scale 1), opened to draw in."""
    page = page or next(o for o in doc.Objects if o.isDerivedFrom("TechDraw::DrawPage"))
    sk = doc.addObject("Sketcher::SketchObject", "Schematic")
    sk.Label = "Schematic%d" % sum(1 for o in doc.Objects if o.Name.startswith("Schematic") and
                                   o.TypeId == "Sketcher::SketchObject")
    view = doc.addObject("TechDraw::DrawViewPart", "SchematicView")
    view.Label = sk.Label + " view"
    page.addView(view)
    view.Source = [sk]
    view.Direction = V(0, 0, 1)
    view.Scale = 1.0
    view.CoarseView = False
    doc.recompute()
    return sk, view


MARKUP_FILTER = "Markup files (*.fwmarkup *.json);;Pictures (*.png *.jpg *.jpeg *.bmp *.svg);;All files (*)"


def save_markups(doc, path):
    """The document's markups as a markup file (strokes, notes and the view each was drawn in)."""
    from . import markup
    out = []
    for o in doc.Objects:
        if markup.is_markup(o):
            notes = []
            for n in o.Notes:
                try:
                    notes.append([n.LabelText[0] if n.LabelText else n.Label, list(n.Position)])
                except Exception as _fw_err:
                    _fw_log("insertextras.py:1176", _fw_err)
            out.append({"strokes": [[list(p) for p in s] for s in (o.Strokes or [])], "notes": notes,
                        "camera": o.Camera, "label": o.Label})
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"freeworks_markup": 1, "markups": out}, f)
    return len(out)


def load_markup_file(doc, path):
    """A markup file's marks back in the document, or a picture as a markup layer
    (on the sheet of a drawing, else a picture plane in the model). Returns what was made."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".svg"):
        if _is_drawing(doc):
            page = next(o for o in doc.Objects if o.isDerivedFrom("TechDraw::DrawPage"))
            img = doc.addObject("TechDraw::DrawViewImage" if ext != ".svg" else "TechDraw::DrawViewSymbol", "Markup")
            if ext == ".svg":
                img.Symbol = open(path, encoding="utf-8", errors="ignore").read()
            else:
                img.ImageFile = path
            page.addView(img)
        else:
            img = doc.addObject("Image::ImagePlane", "Markup")
            img.ImageFile = path
        img.Label = "Markup " + os.path.basename(path)
        doc.recompute()
        return [img]
    from . import markup
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    made = []
    doc.openTransaction("Markup File")
    try:
        for m in data.get("markups", [data] if "strokes" in data else []):
            strokes = [[tuple(p) for p in s] for s in m.get("strokes", [])]
            notes = [(n[0], tuple(n[1])) for n in m.get("notes", [])]
            obj = markup.make(doc, strokes, notes, m.get("camera", ""))
            if obj is not None and m.get("label"):
                obj.Label = m["label"]
            made.append(obj)
    finally:
        doc.commitTransaction()
    return made


# --------------------------------------------------------------------- Edit Decal (Render Tools)
def apply_decal(obj, face, image, width=None):
    """A decal: the picture laid on a planar face (a picture plane just off the face, sized to it)."""
    import math
    doc = obj.Document
    u0, u1, v0, v1 = face.ParameterRange
    n = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    c = face.CenterOfMass
    bb = face.BoundBox
    size = width or 0.8 * max(min(x for x in (bb.XLength, bb.YLength, bb.ZLength) if x > 1e-6) if
                              any(x > 1e-6 for x in (bb.XLength, bb.YLength, bb.ZLength)) else 10.0, 1.0)
    plane = doc.addObject("Image::ImagePlane", "Decal")
    plane.ImageFile = image
    plane.Label = "Decal " + os.path.basename(image)
    plane.XSize = size
    plane.YSize = size
    plane.Placement = App.Placement(c + n * 0.02, App.Rotation(V(0, 0, 1), n))
    plane.addProperty("App::PropertyLinkGlobal", "DecalOf", "Decal", "The body the decal is on")
    plane.DecalOf = obj
    doc.recompute()
    return plane


# --------------------------------------------------------------------- Object... / Hyperlink...
def insert_object(doc, path):
    obj = doc.addObject("App::FeaturePython", "Object")
    obj.addProperty("App::PropertyFileIncluded", "File", "Object", "The inserted file, kept in the document")
    obj.addProperty("App::PropertyString", "SWStyleKind", "Base", "")
    obj.SWStyleKind = "InsertedObject"
    obj.File = path
    obj.Label = os.path.basename(path)
    if App.GuiUp:
        obj.ViewObject.Proxy = 0
    doc.recompute()
    return obj


class _DocLink:
    """The document as a Hyperlink target: its link is kept in the document's Meta."""

    def __init__(self, doc):
        self.Document, self.Label = doc, doc.Label

    @property
    def Hyperlink(self):
        return dict(self.Document.Meta).get("Hyperlink", "")


def set_hyperlink(obj, url):
    if isinstance(obj, _DocLink):
        meta = dict(obj.Document.Meta)
        meta["Hyperlink"] = url
        obj.Document.Meta = meta
        return
    if "Hyperlink" not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", "Hyperlink", "Hyperlink", "A web page or file this item links to")
    obj.Hyperlink = url


def open_link(url):
    if not url:
        return False
    if os.path.exists(url):
        return QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(url))
    if "://" not in url:
        url = "https://" + url
    return QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))


# --------------------------------------------------------------------- File > Publish / Share
VIEWER = """<!doctype html><html><head><meta charset="utf-8"><title>%(title)s</title>
<style>html,body{margin:0;height:100%%;background:#e8ecf2;font:13px sans-serif}canvas{width:100%%;height:100%%;display:block}
#t{position:absolute;left:12px;top:8px;color:#333}</style></head><body><div id="t">%(title)s: drag to rotate,
right-drag to pan, wheel to zoom</div><canvas id="c"></canvas><script>
const M=%(meshes)s;const c=document.getElementById('c');const g=c.getContext('webgl');
const vs='attribute vec3 p;attribute vec3 n;uniform mat4 m;uniform mat4 r;varying float l;void main(){gl_Position=m*vec4(p,1.);l=.35+.65*abs((r*vec4(n,0.)).z);}';
const fs='precision mediump float;uniform vec3 k;varying float l;void main(){gl_FragColor=vec4(k*l,1.);}';
function sh(t,s){const o=g.createShader(t);g.shaderSource(o,s);g.compileShader(o);return o}
const pr=g.createProgram();g.attachShader(pr,sh(g.VERTEX_SHADER,vs));g.attachShader(pr,sh(g.FRAGMENT_SHADER,fs));g.linkProgram(pr);g.useProgram(pr);
let lo=[1e9,1e9,1e9],hi=[-1e9,-1e9,-1e9];
const B=M.map(o=>{const v=o.v,f=o.f,P=[],N=[];for(let i=0;i<f.length;i+=3){const a=f[i]*3,b=f[i+1]*3,d=f[i+2]*3;
const u=[v[b]-v[a],v[b+1]-v[a+1],v[b+2]-v[a+2]],w=[v[d]-v[a],v[d+1]-v[a+1],v[d+2]-v[a+2]];
const nn=[u[1]*w[2]-u[2]*w[1],u[2]*w[0]-u[0]*w[2],u[0]*w[1]-u[1]*w[0]];const L=Math.hypot(...nn)||1;
for(const j of [a,b,d]){for(let q=0;q<3;q++){P.push(v[j+q]);N.push(nn[q]/L);lo[q]=Math.min(lo[q],v[j+q]);hi[q]=Math.max(hi[q],v[j+q]);}}}
const pb=g.createBuffer();g.bindBuffer(g.ARRAY_BUFFER,pb);g.bufferData(g.ARRAY_BUFFER,new Float32Array(P),g.STATIC_DRAW);
const nb=g.createBuffer();g.bindBuffer(g.ARRAY_BUFFER,nb);g.bufferData(g.ARRAY_BUFFER,new Float32Array(N),g.STATIC_DRAW);
return {pb,nb,n:P.length/3,k:o.c}});
const C=[0,1,2].map(q=>(lo[q]+hi[q])/2),R=Math.hypot(hi[0]-lo[0],hi[1]-lo[1],hi[2]-lo[2])/2||1;
let ax=-1.0,az=0.6,zm=1,px=0,py=0;
function mul(a,b){const o=new Array(16).fill(0);for(let i=0;i<4;i++)for(let j=0;j<4;j++)for(let k=0;k<4;k++)o[j*4+i]+=a[k*4+i]*b[j*4+k];return o}
function rot(){const ca=Math.cos(ax),sa=Math.sin(ax),cz=Math.cos(az),sz=Math.sin(az);
const Z=[cz,sz,0,0,-sz,cz,0,0,0,0,1,0,0,0,0,1],X=[1,0,0,0,0,ca,sa,0,0,-sa,ca,0,0,0,0,1];return mul(X,Z)}
function draw(){c.width=c.clientWidth;c.height=c.clientHeight;g.viewport(0,0,c.width,c.height);g.clearColor(.91,.93,.95,1);
g.clear(g.COLOR_BUFFER_BIT|g.DEPTH_BUFFER_BIT);g.enable(g.DEPTH_TEST);const asp=c.width/c.height,s=zm/R;
const T=[1,0,0,0,0,1,0,0,0,0,1,0,-C[0],-C[1],-C[2],1],r=rot();
const S=[s/Math.max(asp,1e-3),0,0,0,0,s,0,0,0,0,-s*.5,0,px,py,0,1];const m=mul(S,mul(r,T));
g.uniformMatrix4fv(g.getUniformLocation(pr,'m'),false,new Float32Array(m));g.uniformMatrix4fv(g.getUniformLocation(pr,'r'),false,new Float32Array(r));
const lp=g.getAttribLocation(pr,'p'),ln=g.getAttribLocation(pr,'n');
for(const b of B){g.uniform3fv(g.getUniformLocation(pr,'k'),b.k);g.bindBuffer(g.ARRAY_BUFFER,b.pb);g.enableVertexAttribArray(lp);g.vertexAttribPointer(lp,3,g.FLOAT,false,0,0);
g.bindBuffer(g.ARRAY_BUFFER,b.nb);g.enableVertexAttribArray(ln);g.vertexAttribPointer(ln,3,g.FLOAT,false,0,0);g.drawArrays(g.TRIANGLES,0,b.n)}}
let d=null;c.onmousedown=e=>{d=[e.clientX,e.clientY,e.button]};onmouseup=()=>d=null;c.oncontextmenu=e=>e.preventDefault();
onmousemove=e=>{if(!d)return;const dx=e.clientX-d[0],dy=e.clientY-d[1];if(d[2]==2){px+=dx*2/c.width;py-=dy*2/c.height}else{az+=dx*.01;ax+=dy*.01}d=[e.clientX,e.clientY,d[2]];draw()};
c.onwheel=e=>{e.preventDefault();zm*=e.deltaY<0?1.1:1/1.1;draw()};onresize=draw;draw();
</script></body></html>"""


def publish_viewer(doc, path):
    """A web page with the model in 3D (turn, zoom, pan in any browser; no add-on needed)."""
    meshes = []
    for o in doc.Objects:
        shape = getattr(o, "Shape", None)
        if shape is None or shape.isNull() or not shape.Faces:
            continue
        if App.GuiUp and o.ViewObject is not None and not o.ViewObject.Visibility:
            continue
        colour = [0.72, 0.75, 0.8]
        try:
            colour = list(o.ViewObject.ShapeAppearance[0].DiffuseColor[:3])
        except Exception as _fw_err:
            _fw_log("insertextras.py:1340", _fw_err)
        pts, tris = shape.tessellate(max(shape.BoundBox.DiagonalLength / 400.0, 0.01))
        meshes.append({"v": [round(c, 4) for p in pts for c in (p.x, p.y, p.z)],
                       "f": [i for t in tris for i in t], "c": colour})
    with open(path, "w", encoding="utf-8") as out:
        out.write(VIEWER % {"title": doc.Label or doc.Name, "meshes": json.dumps(meshes)})
    return path


def share_copy(doc, folder, kind="zip"):
    """A copy to send: the part file zipped with a STEP, in folder. Returns the path."""
    import zipfile
    base = os.path.join(folder, doc.Label or doc.Name)
    step = base + ".step"
    shapes = [o for o in _solids(doc)]
    if shapes:
        Part.export(shapes, step)
    if kind == "step":
        return step
    fc = base + ".FCStd"
    doc.saveCopy(fc)
    out = base + ".zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in (fc, step):
            if os.path.exists(f):
                z.write(f, os.path.basename(f))
    return out


# ===================================================================== GUI
if Gui is not None:
    def _ask_file(title, filt, save=False, default=""):
        mw = Gui.getMainWindow()
        if save:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(mw, title, default, filt)
        else:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(mw, title, default, filt)
        return path

    def _body():
        from . import simplefeature as sf
        return sf.body_of(_doc())

    # ------------------------------------------------------------- FeatureWorks
    class RecognizePM(_PM):
        def __init__(self):
            super().__init__("Feature Recognition", "FEATUREWORKS_RECOGNIZE")
            opts = fw_options()
            self.mode = QtWidgets.QComboBox()
            self.mode.addItems(["Automatic", "Interactive"])
            self.mode.setCurrentText(opts["mode"])
            self.lay.addRow("Recognition mode", self.mode)
            self.checks = {}
            for k in KINDS:
                cb = QtWidgets.QCheckBox(k)
                cb.setChecked(k in opts["kinds"])
                self.checks[k] = cb
                self.lay.addRow(cb)
            bodies = [o for o in _solids(_doc()) if o.TypeId != "PartDesign::Body"]
            self.source = QtWidgets.QComboBox()
            for o in bodies:
                self.source.addItem(o.Label, o.Name)
            picked = [o for o in _picked_objects() if o in bodies]
            if picked:
                self.source.setCurrentIndex(bodies.index(picked[0]))
            self.lay.addRow("Imported body", self.source)
            run = QtWidgets.QPushButton("Recognize Features")
            run.clicked.connect(self.run)
            self.lay.addRow(run)
            self.found_list = QtWidgets.QListWidget()
            self.lay.addRow(self.found_list)
            self.found = []
            self.finish()

            self.mode.currentTextChanged.connect(lambda _t: self.run())
            if bodies:
                self.run()
            else:
                self.message.setText("No imported body: Insert > Features > Imported... brings one in.")

        def kinds(self):
            return [k for k, cb in self.checks.items() if cb.isChecked()]

        def picked_faces(self, obj):
            out = set()
            for sel in Gui.Selection.getSelectionEx(_doc().Name):
                if sel.Object is obj or getattr(sel.Object, "Name", None) == obj.Name:
                    for sub in sel.SubElementNames:
                        tail = sub.split(".")[-1]
                        if tail.startswith("Face") and tail[4:].isdigit():
                            out.add(int(tail[4:]))
            return out

        def run(self):
            name = self.source.currentData()
            obj = _doc().getObject(name) if name else None
            if obj is None:
                return
            found = recognize(obj.Shape, self.kinds(), fw_options()["max_fillet"])
            if self.mode.currentText() == "Interactive":
                picked = self.picked_faces(obj)
                found = [x for x in found if picked & set(x[2])]
                if not picked:
                    self.found = []
                    self.found_list.clear()
                    self.message.setText("Interactive: pick faces of the feature on %s, then click Recognize Features." % obj.Label)
                    return
            self.found = found
            self.found_list.clear()
            for kind, size, faces in self.found:
                item = QtWidgets.QListWidgetItem("%s  %s" % (kind, size))
                item.setCheckState(QtCore.Qt.Checked)
                self.found_list.addItem(item)
            self.message.setText("%d features recognized." % len(self.found))

        def ok(self):
            name = self.source.currentData()
            obj = _doc().getObject(name) if name else None
            if obj is None:
                raise RuntimeError("Pick the imported body")
            keep = [f for i, f in enumerate(self.found) if self.found_list.item(i).checkState() == QtCore.Qt.Checked]
            make_recognized(_doc(), obj, keep, fw_options()["body"])
            return True

    class OptionsDialog(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(Gui.getMainWindow())
            self.setWindowTitle("Feature Recognition Options")
            opts = fw_options()
            lay = QtWidgets.QFormLayout(self)
            self.mode = QtWidgets.QComboBox()
            self.mode.addItems(["Automatic", "Interactive"])
            self.mode.setCurrentText(opts["mode"])
            lay.addRow("Default recognition mode", self.mode)
            self.checks = {}
            for k in KINDS:
                cb = QtWidgets.QCheckBox(k)
                cb.setChecked(k in opts["kinds"])
                self.checks[k] = cb
                lay.addRow(cb)
            self.fillet = QtWidgets.QDoubleSpinBox()
            self.fillet.setRange(0.1, 1000)
            self.fillet.setValue(opts["max_fillet"])
            self.fillet.setSuffix(" mm")
            lay.addRow("Largest fillet radius", self.fillet)
            self.body = QtWidgets.QCheckBox("Build a body on the imported solid")
            self.body.setChecked(opts["body"])
            lay.addRow(self.body)
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addRow(bb)

        def accept(self):
            set_fw_options(self.mode.currentText(), [k for k, c in self.checks.items() if c.isChecked()],
                           self.fillet.value(), self.body.isChecked())
            super().accept()

    # ------------------------------------------------------------- Mate Reference
    class MateReferencePM(_PM):
        def __init__(self):
            super().__init__("Mate Reference", "REFGEO_MATE_REF")
            self.name = QtWidgets.QLineEdit("Default")
            self.lay.addRow("Reference Name", self.name)
            self.slots = []
            picks = _picked_subs("")
            for i, slot in enumerate(("Primary", "Secondary", "Tertiary")):
                ent = QtWidgets.QLineEdit()
                ent.setReadOnly(True)
                ent.setStyleSheet("QLineEdit { background: #cce4f7; color: #000000; border: 1px solid #7eb4ea; }" if i == 0 else "")
                kind = QtWidgets.QComboBox()
                kind.addItems(MATE_TYPES)
                align = QtWidgets.QComboBox()
                align.addItems(ALIGNMENTS)
                self.lay.addRow(QtWidgets.QLabel("<b>%s Reference Entity</b>" % slot))
                self.lay.addRow(ent)
                self.lay.addRow("Mate type", kind)
                self.lay.addRow("Alignment", align)
                ref = [None, ""]
                if i < len(picks):
                    ref[:] = [picks[i][0], picks[i][1]]
                    ent.setText("%s %s" % (picks[i][0].Label, picks[i][1].split(".")[-1]))
                self.slots.append((ent, kind, align, ref))
            self.finish()
            Gui.Selection.addObserver(self)

        def addSelection(self, doc, name, sub, _pos):
            for ent, kind, align, ref in self.slots:
                if ref[0] is None:
                    ref[:] = [App.getDocument(doc).getObject(name), sub]
                    ent.setText("%s %s" % (ref[0].Label, sub.split(".")[-1]))
                    break

        def _done(self):
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("insertextras.py:1516", _fw_err)

        def ok(self):
            refs = [(r[0], r[1], k.currentText(), a.currentText()) for _e, k, a, r in self.slots]
            if refs[0][0] is None:
                raise RuntimeError("Pick the primary reference entity")
            self._done()
            make_mate_reference(_doc(), refs, self.name.text() or "Default")
            return True

        def reject(self):
            self._done()
            return super().reject()

    # ------------------------------------------------------------- Fillet Bead
    class _BoxClicks(QtCore.QObject):
        ""

        def __init__(self, pm):
            super().__init__()
            self.pm = pm

        def eventFilter(self, obj, event):
            if not isinstance(event, QtCore.QEvent):
                return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
            if event.type() == QtCore.QEvent.MouseButtonPress:
                self.pm.activate(obj)
            return False

    class FilletBeadPM(_PM):
        def __init__(self):
            super().__init__("Fillet Bead", "WELDMENTS_FILLET_BEAD")
            self.kind = QtWidgets.QComboBox()
            self.kind.addItems(["Full Length", "Intermittent", "Staggered"])
            self.lay.addRow("Bead type", self.kind)
            self.size = QtWidgets.QDoubleSpinBox()
            self.size.setRange(0.1, 100)
            self.size.setValue(3.0)
            self.size.setSuffix(" mm")
            self.lay.addRow("Fillet size", self.size)
            self.length = QtWidgets.QDoubleSpinBox()
            self.length.setRange(0.1, 10000)
            self.length.setValue(10.0)
            self.pitch = QtWidgets.QDoubleSpinBox()
            self.pitch.setRange(0.1, 10000)
            self.pitch.setValue(20.0)
            self.lay.addRow("Fillet length", self.length)
            self.lay.addRow("Pitch", self.pitch)
            self.tangent = QtWidgets.QCheckBox("Tangent propagation")
            self.tangent.setObjectName("SWWEBeadTangent")
            self.tangent.setChecked(True)
            self.lay.addRow(self.tangent)
            self.set1 = _pick_list(self, "Face Set 1", "Face")
            self.set2 = QtWidgets.QListWidget()
            self.set2.setMaximumHeight(70)
            self.set2.items = []
            self.lay.addRow(QtWidgets.QLabel("Face Set 2"))
            self.lay.addRow(self.set2)

            self.other = QtWidgets.QCheckBox("Other Side")
            self.other.setObjectName("SWWEBeadOtherSide")
            self.lay.addRow(self.other)
            self.other_size = QtWidgets.QDoubleSpinBox()
            self.other_size.setObjectName("SWWEBeadOtherSize")
            self.other_size.setRange(0.1, 100)
            self.other_size.setValue(3.0)
            self.other_size.setSuffix(" mm")
            self.other_size.setEnabled(False)
            self.other.toggled.connect(self.other_size.setEnabled)
            self.other_size.setToolTip("Other side")
            self.lay.addRow("Fillet size", self.other_size)
            self.active = self.set1 if not self.set1.items else self.set2
            self.length.setSuffix(" mm")
            self.pitch.setSuffix(" mm")
            self._clicks = _BoxClicks(self)
            for box in (self.set1, self.set2):
                box.viewport().installEventFilter(self._clicks)
            self._show_active()
            self.finish()
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)

        def _show_active(self):
            for box in (self.set1, self.set2):
                pmboxes.mark(box, box is self.active)

        def activate(self, viewport):
            for box in (self.set1, self.set2):
                if box.viewport() is viewport:
                    self.active = box
            self._show_active()

        def addSelection(self, doc, name, sub, _pos):
            if not sub.split(".")[-1].startswith("Face"):
                return
            obj = App.getDocument(doc).getObject(name)
            self.active.items.append((obj, sub, None))
            self.active.addItem("%s %s" % (obj.Label, sub.split(".")[-1]))
            self.message.setText("Face Set 1: %d, Face Set 2: %d. Click a box to fill it." %
                                 (len(self.set1.items), len(self.set2.items)))

        def _done(self):
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("insertextras.py:1620", _fw_err)

        def ok(self):
            if not self.set1.items or not self.set2.items:
                if self.active is self.set1 and self.set1.items:
                    self.active = self.set2
                    self._show_active()
                    self.message.setText("Now pick Face Set 2, then OK.")
                    return False
                raise RuntimeError("Pick faces for both face sets")
            self._done()
            make_fillet_bead(_doc(), [(o, s) for o, s, _ in self.set1.items], [(o, s) for o, s, _ in self.set2.items],
                             self.size.value(), self.kind.currentText(), self.length.value(), self.pitch.value(),
                             self.tangent.isChecked(), self.other.isChecked(), self.other_size.value())
            return True

        def reject(self):
            self._done()
            return super().reject()

    # ------------------------------------------------------------- Decimate
    class PartBOMPM(_PM):
        ""

        def __init__(self):
            super().__init__("Bill of Materials", _drawn("TABLES_BOM"))
            self.template = QtWidgets.QComboBox()
            self.template.setObjectName("SWPartBOMTemplate")
            self.template.addItems(list(BOM_TEMPLATES))
            self.lay.addRow("Table Template", self.template)
            self.start = QtWidgets.QSpinBox()
            self.start.setObjectName("SWPartBOMStart")
            self.start.setRange(0, 9999)
            self.start.setValue(1)
            self.lay.addRow("Start at", self.start)
            self.inc = QtWidgets.QSpinBox()
            self.inc.setObjectName("SWPartBOMIncrement")
            self.inc.setRange(1, 999)
            self.inc.setValue(1)
            self.lay.addRow("Increment", self.inc)
            self.finish()

        def ok(self):
            start, inc, tpl = self.start.value(), self.inc.value(), self.template.currentText()
            QtCore.QTimer.singleShot(0, lambda: _table(lambda d: part_bom(d, start, inc, tpl)))
            return True

    class GeneralTolerancePM(_PM):
        ""

        def __init__(self):
            super().__init__("General Tolerance", _drawn("TABLES_GENERAL_TOLERANCE"))
            self.standard = QtWidgets.QComboBox()
            self.standard.setObjectName("SWGenTolStandard")
            self.standard.addItems(["ISO 2768-1"])
            self.lay.addRow("Standard", self.standard)
            self.grade = QtWidgets.QComboBox()
            self.grade.setObjectName("SWGenTolClass")
            for key, text in GRADES:
                self.grade.addItem(text, key)
            self.grade.setCurrentIndex(1)
            self.lay.addRow("Tolerance class", self.grade)
            self.finish()

        def ok(self):
            grade = self.grade.currentData()
            QtCore.QTimer.singleShot(0, lambda: _table(lambda d: general_tolerance(d, grade)))
            return True

    class DecimatePM(_PM):
        def __init__(self):
            super().__init__("Decimate Mesh Body", "MESH_DECIMATE")
            self.targets = mesh_targets(_picked_objects()) or mesh_targets(_doc().Objects)[:1]
            self.lay.addRow("Mesh body", QtWidgets.QLabel(", ".join(o.Label for o in self.targets) or "(none)"))
            self.reduction = QtWidgets.QSpinBox()
            self.reduction.setRange(1, 99)
            self.reduction.setValue(50)
            self.reduction.setSuffix(" %")
            self.lay.addRow("Reduce by", self.reduction)
            self.tol = QtWidgets.QDoubleSpinBox()
            self.tol.setRange(0.001, 100)
            self.tol.setValue(0.1)
            self.tol.setSuffix(" mm")
            self.lay.addRow("Maximum deviation", self.tol)
            self.finish()

        def ok(self):
            if not self.targets:
                raise RuntimeError("Pick a mesh body")
            text = []
            for o in self.targets:
                a, b = decimate(o, self.reduction.value() / 100.0, self.tol.value())
                text.append("%s: %d to %d facets" % (o.Label, a, b))
            App.Console.PrintMessage("Decimate Mesh Body: %s\n" % "; ".join(text))
            return True

    # ------------------------------------------------------------- Exploded View (part)
    class PartExplodePM(_PM):
        def __init__(self):
            super().__init__("Explode", "ASSEMBLIES_EXPLODED_VIEW")
            self.steps = []
            self.bodies = _pick_list(self, "Bodies to explode", "")
            self.direction = QtWidgets.QComboBox()
            self.direction.addItems(["X", "Y", "Z", "-X", "-Y", "-Z"])
            self.direction.setCurrentText("Z")
            self.lay.addRow("Explode direction", self.direction)
            self.distance = QtWidgets.QDoubleSpinBox()
            self.distance.setRange(-100000, 100000)
            self.distance.setValue(50.0)
            self.distance.setSuffix(" mm")
            self.lay.addRow("Explode distance", self.distance)

            self.kind = QtWidgets.QComboBox()
            self.kind.setObjectName("SWExplodeStepType")
            self.kind.addItems(["Regular step (translate and rotate)", "Radial step"])
            self.lay.addRow("Explode Step Type", self.kind)
            self.rot_axis = QtWidgets.QComboBox()
            self.rot_axis.setObjectName("SWExplodeRotAxis")
            self.rot_axis.addItems(["X", "Y", "Z"])
            self.rot_axis.setCurrentText("Z")
            self.lay.addRow("Rotation axis", self.rot_axis)
            self.angle = QtWidgets.QDoubleSpinBox()
            self.angle.setObjectName("SWExplodeAngle")
            self.angle.setRange(-360, 360)
            self.angle.setSuffix(" \u00b0")
            self.lay.addRow("Rotation angle", self.angle)
            self.about_own = QtWidgets.QCheckBox("Rotate about each body origin")
            self.about_own.setObjectName("SWExplodeAboutOwn")
            self.about_own.setChecked(True)
            self.lay.addRow(self.about_own)
            self.kind.currentIndexChanged.connect(self._kind)
            add = QtWidgets.QPushButton("Add Step")
            add.clicked.connect(self.add_step)
            self.lay.addRow(add)
            self.list = QtWidgets.QListWidget()
            self.lay.addRow(QtWidgets.QLabel("Explode Steps"))
            self.lay.addRow(self.list)
            self.finish()
            Gui.Selection.addObserver(self)

        def _kind(self, *_a):
            radial = self.kind.currentIndex() == 1
            for w in (self.rot_axis, self.angle, self.about_own):
                w.setEnabled(not radial)

        def addSelection(self, *_a):
            self.bodies.take()

        def _names(self):
            out = []
            for o, _s, _sh in self.bodies.items:
                b = o
                parent = o.getParentGeoFeatureGroup() if hasattr(o, "getParentGeoFeatureGroup") else None
                if parent is not None and parent.TypeId == "PartDesign::Body":
                    b = parent
                if b.Name not in out:
                    out.append(b.Name)
            return out

        def add_step(self):
            names = self._names()
            if not names:
                self.message.setText("Pick the bodies to move")
                return
            d = self.direction.currentText()
            vec = {"X": [1, 0, 0], "Y": [0, 1, 0], "Z": [0, 0, 1]}[d[-1]]
            if d.startswith("-"):
                vec = [-x for x in vec]
            ax = {"X": [1, 0, 0], "Y": [0, 1, 0], "Z": [0, 0, 1]}[self.rot_axis.currentText()]
            radial = self.kind.currentIndex() == 1
            self.steps.append({"bodies": names, "direction": vec, "distance": self.distance.value(),
                               "type": "Radial" if radial else "Regular",
                               "angle": 0.0 if radial else self.angle.value(), "rot_axis": ax,
                               "about_own": self.about_own.isChecked()})
            self.list.addItem("Explode Step%d" % (self.list.count() + 1))
            make_part_explode(_doc(), [self.steps[-1]])
            self.bodies.items = []
            self.bodies.clear()
            Gui.Selection.clearSelection()

        def _done(self):
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("insertextras.py:1804", _fw_err)

        def ok(self):
            if self._names():
                self.add_step()
            self._done()
            return True

        def reject(self):
            self._done()
            return super().reject()

    # ------------------------------------------------------------- Mirror Part
    class MirrorPartPM(_PM):
        def __init__(self):
            super().__init__("Mirror Part", "INSERT_MIRROR_PART")
            self.plane = QtWidgets.QComboBox()
            self.plane.addItems(["Right Plane", "Top Plane", "Front Plane"])
            faces = _picked_subs("Face")
            self.face = faces[0] if faces and faces[0][2].Surface.TypeId == "Part::GeomPlane" else None
            if self.face is not None:
                self.plane.insertItem(0, "Picked face")
                self.plane.setCurrentIndex(0)
            self.lay.addRow("Mirror plane", self.plane)
            self.link = QtWidgets.QCheckBox("Linked to the original")
            self.link.setToolTip("Untick to break the link to the original part")
            self.link.setChecked(True)
            self.lay.addRow(self.link)

            self.lay.addRow(QtWidgets.QLabel("Transfer"))
            self.transfer = {}
            for key, text, default in MIRROR_TRANSFER:
                cb = QtWidgets.QCheckBox(text)
                cb.setObjectName("SWMirrorTransfer" + key)
                cb.setChecked(default)
                self.lay.addRow(cb)
                self.transfer[key] = cb
            self.finish()

        def ok(self):
            doc = _doc()
            solids = _solids(doc)
            if not solids:
                raise RuntimeError("The part has no solid body to mirror")
            src = solids[0] if len(solids) == 1 else _fuse_all(doc, solids)
            text = self.plane.currentText()
            if text == "Picked face":
                f = self.face[2]
                normal, base = f.normalAt(0, 0), f.CenterOfMass
            else:
                normal = {"Right Plane": V(1, 0, 0), "Top Plane": V(0, 0, 1), "Front Plane": V(0, 1, 0)}[text]
                base = V(0, 0, 0)
            if not self.link.isChecked():
                new = App.newDocument("Mirror" + doc.Name)
                o = new.addObject("Part::Feature", "MirrorPart")
                o.Shape = src.Shape.mirror(base, normal)
                o.Label = "Mirror" + src.Label
                new.recompute()
            else:
                mirror_part(doc, src, normal, base, transfer={k: cb.isChecked() for k, cb in self.transfer.items()})
            Gui.SendMsgToActiveView("ViewFit")
            return True

    def _fuse_all(doc, solids):
        o = doc.addObject("Part::MultiFuse", "AllBodies")
        o.Shapes = solids
        doc.recompute()
        if App.GuiUp:
            o.ViewObject.Visibility = False
            for s in solids:
                s.ViewObject.Visibility = True
        return o

    # ------------------------------------------------------------- Sketch From Drawing
    class SketchFromDrawingPM(_PM):
        def __init__(self):
            super().__init__("Sketch From Drawing", "SKETCH_SKETCH")
            self.views = drawing_views()
            self.combo = QtWidgets.QComboBox()
            for v in self.views:
                self.combo.addItem("%s: %s" % (v.Document.Label, v.Label))
            self.lay.addRow("Drawing view", self.combo)
            self.finish()
            if not self.views:
                self.message.setText("Open a drawing of this part first: its views are listed here.")

        def ok(self):
            if not self.views:
                raise RuntimeError("No drawing view is open")
            v = self.views[self.combo.currentIndex()]
            sk = sketch_from_view(_doc(), v, _body())
            Gui.ActiveDocument.setEdit(sk.Name)
            return True

    # ------------------------------------------------------------- DXF/DWG
    class DxfPM(_PM):
        def __init__(self, path):
            super().__init__("DXF/DWG Import", "INSERT_DXF")
            self.path = path
            self.lay.addRow("File", QtWidgets.QLabel(os.path.basename(path)))
            self.plane = QtWidgets.QComboBox()
            self.plane.addItems(["Front", "Top", "Right"])
            self.lay.addRow("Sketch plane", self.plane)
            self.finish()

        def ok(self):
            sk = insert_dxf(_doc(), self.path, _body(), self.plane.currentText())
            if not sk.Geometry:
                raise RuntimeError("Nothing 2D was found in the file")
            return True

    # ------------------------------------------------------------- Parameters
    class ParametersDialog(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(Gui.getMainWindow())
            self.setWindowTitle("Parameters")
            self.resize(560, 300)
            lay = QtWidgets.QVBoxLayout(self)
            self.table = QtWidgets.QTableWidget(0, 5)
            self.table.setHorizontalHeaderLabels(["Name", "Category", "Value", "Units", "Linked to (Object.Property)"])
            self.table.horizontalHeader().setStretchLastSection(True)
            lay.addWidget(self.table)
            for row in parameters(_doc()):
                self._row([row["name"], row["category"], row["value"], row["units"], row["link"]])
            self._row(["", "", "", "mm", ""])
            add = QtWidgets.QPushButton("Add")
            add.clicked.connect(lambda: self._row(["", "", "", "mm", ""]))
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            bb.addButton(add, QtWidgets.QDialogButtonBox.ActionRole)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)

        def _row(self, values):
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, v in enumerate(values):
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(v))

        def accept(self):
            rows = []
            for r in range(self.table.rowCount()):
                get = lambda c: (self.table.item(r, c).text() if self.table.item(r, c) else "").strip()
                if get(0):
                    rows.append({"name": get(0), "category": get(1), "value": get(2) or "0", "units": get(3),
                                 "link": get(4)})
            set_parameters(_doc(), rows)
            super().accept()

    # ------------------------------------------------------------- Excel Design Table
    class DesignTablePM(_PM):
        def __init__(self):
            super().__init__("Excel Design Table", "TABLES_DESIGN_TABLE")
            self.group = QtWidgets.QButtonGroup(self.form)
            self.radios = {}

            source = QtWidgets.QGroupBox("Source")
            source.setObjectName("SWDesignTableSource")
            inside = QtWidgets.QVBoxLayout(source)
            for key, text in (("blank", "Blank"), ("auto", "Auto-create"), ("file", "From file")):
                rb = QtWidgets.QRadioButton(text)
                self.group.addButton(rb)
                self.radios[key] = rb
                inside.addWidget(rb)
            self.radios["auto"].setChecked(True)
            self.path = QtWidgets.QLineEdit()
            browse = QtWidgets.QPushButton("Browse...")
            browse.clicked.connect(self._browse)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self.path)
            row.addWidget(browse)
            inside.addLayout(row)
            self.lay.addRow(source)
            from . import dtoptions
            self.boxes = dtoptions.Boxes(self.lay, None, self.path)
            self.finish()

        def _browse(self):
            p = _ask_file("Design table", "Tables (*.xlsx *.csv)")
            if p:
                self.path.setText(p)
                self.radios["file"].setChecked(True)

        def ok(self):
            mode = next(k for k, r in self.radios.items() if r.isChecked())
            if mode == "file" and not self.path.text():
                raise RuntimeError("Browse to the table file")
            s = excel_design_table(_doc(), mode, self.path.text(), pick=True)
            from . import dtoptions
            values = self.boxes.values()
            if mode != "file":
                values["link"] = ""
            dtoptions.set_options(s, **values)
            from . import configmanager
            t = configmanager.table(_doc())
            if t is not None and t.sheet is s:

                QtCore.QTimer.singleShot(0, lambda: configmanager.edit_table(t))
            else:
                QtCore.QTimer.singleShot(0, lambda: Gui.ActiveDocument.setEdit(s.Name))
            return True

    # ------------------------------------------------------------- Hyperlink
    class HyperlinkDialog(QtWidgets.QDialog):
        def __init__(self, objs):
            super().__init__(Gui.getMainWindow())
            self.objs = objs
            self.setWindowTitle("Insert Hyperlink")
            lay = QtWidgets.QFormLayout(self)
            lay.addRow("Link to", QtWidgets.QLabel(", ".join(o.Label for o in objs)))
            self.url = QtWidgets.QLineEdit(getattr(objs[0], "Hyperlink", "") if objs else "")
            browse = QtWidgets.QPushButton("Browse...")
            browse.clicked.connect(self._browse)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self.url)
            row.addWidget(browse)
            lay.addRow("Type the file or Web page name", row)
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            go = QtWidgets.QPushButton("Open Link")
            go.clicked.connect(lambda: open_link(self.url.text()))
            bb.addButton(go, QtWidgets.QDialogButtonBox.ActionRole)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addRow(bb)

        def _browse(self):
            p = _ask_file("Hyperlink", "All files (*)")
            if p:
                self.url.setText(p)

        def accept(self):
            doc = self.objs[0].Document
            doc.openTransaction("Hyperlink")
            try:
                for o in self.objs:
                    set_hyperlink(o, self.url.text().strip())
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
            super().accept()

    # ------------------------------------------------------------- Share
    class ShareDialog(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(Gui.getMainWindow())
            self.setWindowTitle("Share")
            lay = QtWidgets.QFormLayout(self)
            self.kind = QtWidgets.QComboBox()
            self.kind.addItems(["Part and STEP (zip)", "STEP only", "3D viewer page (html)"])
            lay.addRow("Share as", self.kind)
            self.folder = QtWidgets.QLineEdit(os.path.join(os.path.expanduser("~"), "Desktop")
                                              if os.path.isdir(os.path.join(os.path.expanduser("~"), "Desktop"))
                                              else os.path.expanduser("~"))
            browse = QtWidgets.QPushButton("Browse...")
            browse.clicked.connect(self._browse)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self.folder)
            row.addWidget(browse)
            lay.addRow("Save to", row)
            self.mail = QtWidgets.QCheckBox("Start an email with it")
            lay.addRow(self.mail)
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addRow(bb)
            self.result_path = None

        def _browse(self):
            p = QtWidgets.QFileDialog.getExistingDirectory(self, "Share to", self.folder.text())
            if p:
                self.folder.setText(p)

        def accept(self):
            doc = _doc()
            folder = self.folder.text()
            i = self.kind.currentIndex()
            if i == 2:
                path = publish_viewer(doc, os.path.join(folder, (doc.Label or doc.Name) + ".html"))
            else:
                path = share_copy(doc, folder, "zip" if i == 0 else "step")
            self.result_path = path
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder))
            if self.mail.isChecked():
                QtGui.QDesktopServices.openUrl(QtCore.QUrl(
                    "mailto:?subject=%s&body=Attached: %s" % (doc.Label, os.path.basename(path))))
            super().accept()

    # ------------------------------------------------------------- commands
    def _show(panel):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        Gui.Control.showDialog(panel)

    def _imported():
        p = _ask_file("Imported", IMPORT_FILTER)
        if p:
            obj = insert_imported(_doc(), p)
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(obj)
            Gui.SendMsgToActiveView("ViewFit")

    def _explode_line():
        doc = _doc()
        try:        # pkg302 (Assemblies, patch-merge): in an exploded assembly the CommandManager's
            from . import asmcore, asmexplines
            asm = asmcore.assembly_of(doc)
            if asm is not None and asmexplines._ax().exploded_view(asm) is not None:
                asmexplines.start(asm)
                return
        except ImportError:
            pass
        before = set(o.Name for o in doc.Objects)
        Gui.runCommand("FreeWorks_Sketch3D", 0)
        new = [o for o in doc.Objects if o.Name not in before and "Sketch" in o.TypeId + o.Name]
        if new:
            new[0].Label = "3DExplode"

    def _dxf():
        p = _ask_file("DXF/DWG", "DXF/DWG (*.dxf *.dwg)")
        if p and _is_drawing(_doc()):
            if insert_dxf_drawing(_doc(), p) is None:
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "DXF/DWG", "Nothing 2D was found in the file.")
        elif p:
            _show(DxfPM(p))

    def _object():
        p = _ask_file("Object", "All files (*)")
        if p:
            insert_object(_doc(), p)

    def _schematic():
        sk, _view = insert_schematic(_doc())
        Gui.ActiveDocument.setEdit(sk.Name)

    def _markup_file():
        p = _ask_file("Markup File", MARKUP_FILTER)
        if p:
            made = load_markup_file(_doc(), p)
            App.Console.PrintMessage("Markup File: %d markup(s) brought in\n" % len(made))

    def _decal():
        from . import decalpm
        decalpm.command()

    def _hyperlink():
        # nothing picked: the link goes on the document itself (opened from File > Properties)
        HyperlinkDialog(_picked_objects() or [_DocLink(_doc())]).exec_()

    def _publish():
        doc = _doc()
        default = os.path.join(os.path.dirname(doc.FileName) if doc.FileName else os.path.expanduser("~"),
                               (doc.Label or doc.Name) + ".html")
        p = _ask_file("Publish to 3D Viewer", "Web page (*.html)", save=True, default=default)
        if p:
            publish_viewer(doc, p)
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(p))

    def _table(fn):
        s = fn(_doc())
        Gui.ActiveDocument.setEdit(s.Name)

    def _part_doc():
        return _part(_doc())

    def _model_doc():
        # a part or an assembly: any open document that is not a drawing
        doc = _doc()
        if doc is None:
            return False
        return not any(o.TypeId.startswith("TechDraw::DrawPage") for o in doc.Objects)

    def _has_solid():
        return _part(_doc()) and bool(_solids(_doc()))

    def _has_mesh():
        doc = _doc()
        return doc is not None and bool(mesh_targets(doc.Objects))

    def _mate_reference():
        # the one Mate Reference PropertyManager (asmrefgeom): its references are the kind an

        try:
            from . import asmrefgeom
            asmrefgeom.edit_mate_reference(doc=_doc())
        except Exception as error:
            App.Console.PrintWarning("Mate Reference: %s\n" % error)
            _show(MateReferencePM())

    def _free(fn):
        return lambda: not Gui.Control.activeDialog() and fn()

    def _design_parameters():
        from . import dsparams      # dsparams-1121: the one Parameters dialog, shared with the Design Study
        return dsparams.show()

    COMMANDS = [
        ("SWStyle_InsertImported", "Imported...", "Brings a body in from a STEP, IGES, BREP or mesh file.",
         _free(_part_doc), _imported),
        ("SWStyle_RecognizeFeatures", "Recognize Features...", "Finds holes, fillets, chamfers and extrudes on an imported body.",
         _free(_has_solid), lambda: _show(RecognizePM())),
        ("SWStyle_FeatureWorksOptions", "Options...", "FeatureWorks options: recognition mode and feature types.",
         lambda: True, lambda: OptionsDialog().exec_()),
        ("SWStyle_MateReference", "Mate Reference...", "Names faces, edges or planes the part mates by in an assembly.",
         _free(_has_solid), _mate_reference),
        ("SWStyle_FilletBead", "Fillet Bead...", "A fillet weld bead where two face sets meet.",
         _free(_has_solid), lambda: _show(FilletBeadPM())),
        ("SWStyle_DecimateMesh", "Decimate Mesh Body...", "Takes facets out of a mesh body.",
         _free(_has_mesh), lambda: _show(DecimatePM())),
        ("SWStyle_PartExplodedView", "Exploded View...", "Moves the bodies of a multibody part apart, step by step.",
         _free(_has_solid), lambda: _show(PartExplodePM())),
        ("SWStyle_ExplodeLineSketch", "Explode Line Sketch", "A 3D sketch for the explode lines.",
         _free(lambda: _doc() is not None and not _is_drawing(_doc())), _explode_line),
        ("SWStyle_MirrorPart", "Mirror Part...", "A new part, the mirror image of this one.",
         _free(_has_solid), lambda: _show(MirrorPartPM())),
        ("SWStyle_DerivePart", "Derive Part...", "A new part made from this one, linked to it.",
         _free(_part_doc), lambda: derive_part()),
        ("SWStyle_SketchFromDrawing", "Sketch From Drawing", "A sketch made from a view of a drawing of the part.",
         _free(_part_doc), lambda: _show(SketchFromDrawingPM())),
        ("SWStyle_InsertDXF", "DXF/DWG...", "Brings a DXF or DWG file in: a sketch in a part, a view on a drawing.",
         _free(lambda: _doc() is not None and not _is_assembly(_doc())), _dxf),
        ("SWStyle_DesignParameters", "Parameters...", "Names values that drive sizes of the part.",
         lambda: _doc() is not None, _design_parameters),
        ("SWStyle_PartBOM", "Bill of Materials...", "A table of the part's bodies.",
         _free(_has_solid), lambda: _show(PartBOMPM())),
        ("SWStyle_InsertDesignTable", "Excel Design Table", "A design table: blank, made from the configurations, or from a file.",
         _free(_part_doc), lambda: _show(DesignTablePM())),
        ("SWStyle_TitleBlockTable", "Title Block Table...", "A title block table of the part's properties.",
         _free(_model_doc), lambda: _table(title_block_table)),
        ("SWStyle_GeneralTolerance", "General Tolerance...", "The general tolerance table (ISO 2768).",
         _free(_model_doc), lambda: _show(GeneralTolerancePM())),
        ("SWStyle_InsertObject", "Object...", "Puts a file (document, picture, sheet) into the part.",
         lambda: _doc() is not None, _object),
        ("SWStyle_InsertHyperlink", "Hyperlink...", "Links the picked item to a web page or file.",
         lambda: _doc() is not None, _hyperlink),
        ("SWStyle_InsertSchematic", "Schematic...", "A schematic on the sheet: a 2D sketch shown as its own view.",
         _free(lambda: _is_drawing(_doc())), _schematic),
        ("SWStyle_MarkupFile", "Markup File...", "Brings marks in from a markup file, or a picture as a markup layer.",
         _free(lambda: _doc() is not None), _markup_file),
        ("SWStyle_EditDecal", "Edit Decal", "Puts a picture (logo, label) on a flat face.",
         _free(_has_solid), _decal),
        ("SWStyle_PublishViewer", "Publish to 3D Viewer", "A web page with the model in 3D, to open in any browser.",
         lambda: _doc() is not None, _publish),
        ("SWStyle_Share", "Share...", "A copy of the part to send.", lambda: _doc() is not None,
         lambda: ShareDialog().exec_()),
    ]

    class _Cmd:
        def __init__(self, text, tip, active, run):
            self.text, self.tip, self.active, self.run = text, tip, active, run

        def GetResources(self):
            return {"MenuText": self.text, "ToolTip": self.tip}

        def IsActive(self):
            try:
                return App.ActiveDocument is not None and bool(self.active())
            except Exception:
                return False

        def Activated(self):
            self.run()


def register():
    if Gui is None:
        return
    try:
        from . import decalpm
        decalpm.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: decal follow not installed: %s\n" % error)
    try:
        from . import featuredates  # Feature Properties: each feature's own author and dates
        featuredates.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: feature dates not kept: %s\n" % error)
    for name, text, tip, active, run in COMMANDS:
        try:
            if name not in Gui.listCommands():
                Gui.addCommand(name, _Cmd(text, tip, active, run))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s not added (%s)\n" % (text, error))
