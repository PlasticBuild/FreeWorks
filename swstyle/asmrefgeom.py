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

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import asmcore as ac
from . import pmboxes

DATUMS = {"PartDesign::Plane": "Part::DatumPlane", "PartDesign::Line": "Part::DatumLine",
          "PartDesign::Point": "Part::DatumPoint", "PartDesign::CoordinateSystem": "Part::LocalCoordinateSystem"}
MATE_TYPES = ("Default", "Coincident", "Concentric", "Tangent", "Parallel", "Perpendicular")
ALIGNMENTS = ("Any", "Aligned", "Anti-Aligned", "Closest")
SLOTS = ("Primary", "Secondary", "Tertiary")
MATEREF_TYPE = "SWStyle::MateReference"
GROUND_PROP = "FwGroundPlane"
OPEN = []


# ---------------------------------------------------------------------- Plane, Axis, Point, CS
class AsmHolder:
    """Stands in for the active body in refplane/refaxis: datums go into the assembly."""

    def __init__(self, asm):
        self.asm = asm
        self.Document = asm.Document

    def newObject(self, kind, name):
        obj = self.Document.addObject(DATUMS.get(kind, kind), name)
        self.asm.addObject(obj)
        return obj

    def removeObject(self, obj):
        try:
            self.asm.removeObject(obj)
        except Exception as _fw_err:
            _fw_log("asmrefgeom.py:63", _fw_err)
        return []

    def __getattr__(self, name):
        return getattr(self.asm, name)


def _editing_body():
    try:
        return Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
    except Exception:
        return None


def holder(doc):
    """AsmHolder for an assembly document when no body is being edited, else None."""
    asm = ac.assembly_of(doc) if doc is not None else None
    if asm is None or _editing_body() is not None:
        return None
    return AsmHolder(asm)


def datum(asm, kind):
    ""

    try:
        from . import refgeom2
        return refgeom2.coordinate_system() if kind == "cs" else refgeom2.point()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: assembly %s PM: %s\n" % (kind, error))
    return _stock_datum(asm, kind)


def _stock_datum(asm, kind):
    """FreeCAD's body-less datum and its dialog, made in the assembly from the picked references."""
    command = {"cs": "Part_CoordinateSystem", "point": "Part_DatumPoint"}[kind]
    view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
    before_part = view.getActiveObject("part") if view is not None else None
    names = set(o.Name for o in asm.Document.Objects)
    try:
        if view is not None:
            view.setActiveObject("part", asm)       # FreeCAD puts the datum in the active part
        Gui.runCommand(command, 0)
    finally:
        if view is not None:
            view.setActiveObject("part", before_part)
    want = "Part::LocalCoordinateSystem" if kind == "cs" else "Part::DatumPoint"
    main = next((o for o in asm.Document.Objects if o.Name not in names and o.TypeId == want), None)
    if main is None:
        return None
    if main not in asm.Group:
        try:
            asm.addObject(main)        # its own axes and planes stay inside it
        except Exception as _fw_err:
            _fw_log("asmrefgeom.py:117", _fw_err)
    main.Label = _next(asm.Document, "Coordinate System" if kind == "cs" else "Point")
    return main


def _next(doc, base):
    used = {o.Label for o in doc.Objects}
    n = 1
    while "%s%d" % (base, n) in used:
        n += 1
    return "%s%d" % (base, n)


# ---------------------------------------------------------------------- mate references
def _kind(shape):
    if shape is None or shape.isNull():
        return None
    if shape.ShapeType == "Face":
        name = type(shape.Surface).__name__
        return "plane" if name == "Plane" else ("cylinder" if name in ("Cylinder", "Cone") else "surface")
    if shape.ShapeType == "Edge":
        name = type(shape.Curve).__name__
        return "line" if name in ("Line", "LineSegment") else ("circle" if name == "Circle" else "curve")
    if shape.ShapeType == "Vertex":
        return "point"
    return None


def default_type(a, b):
    ""
    ka, kb = _kind(a), _kind(b)
    if "cylinder" in (ka, kb) or "circle" in (ka, kb):
        if {ka, kb} <= {"cylinder", "circle", "line"}:
            return "Concentric"
        return "Tangent" if "plane" in (ka, kb) else "Concentric"
    return "Coincident"


class MateReference:
    """The Mate Reference feature: RefName, Entities (Primary, Secondary, Tertiary), their mate
    types and alignments."""
    Type = MATEREF_TYPE

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        props = obj.PropertiesList
        if "RefName" not in props:
            obj.addProperty("App::PropertyString", "RefName", "Mate Reference", "Mate references with the same name mate")
            obj.RefName = "Default"
        if "Entities" not in props:
            # names, not links: a link would take the part's solid out of its root objects
            obj.addProperty("App::PropertyStringList", "Entities", "Mate Reference",
                            "Primary, Secondary, Tertiary as Object:Element")
        if "MateTypes" not in props:
            obj.addProperty("App::PropertyStringList", "MateTypes", "Mate Reference", "Mate type of each entity")
        if "Alignments" not in props:
            obj.addProperty("App::PropertyStringList", "Alignments", "Mate Reference", "Mate alignment of each entity")

        if "NamesMatch" not in props:
            obj.addProperty("App::PropertyBool", "NamesMatch", "Mate Reference",
                            "Create mates only when names match (else a reference of the same entity types mates too)")
        if "Signatures" not in props:
            obj.addProperty("App::PropertyStringList", "Signatures", "Mate Reference",
                            "What each entity was (for Auto Repair when the part changes)")
            obj.setEditorMode("Signatures", 2)
        if "LockRotation" not in props:
            obj.addProperty("App::PropertyBool", "LockRotation", "Mate Reference", "Concentric reference mates lock rotation")

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class MateReferenceView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        from pivy import coin
        vobj.addDisplayMode(coin.SoGroup(), "Default")

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        try:
            from . import icons
            path = icons.path_for("REFGEO_MATE_REF") if hasattr(icons, "path_for") else None
            if path:
                return path
        except Exception as _fw_err:
            _fw_log("asmrefgeom.py:223", _fw_err)
        return ":/icons/Std_Placement.svg"

    def doubleClicked(self, vobj):
        edit_mate_reference(vobj.Object)
        return True

    def setupContextMenu(self, vobj, menu):
        menu.addAction("Edit Feature").triggered.connect(lambda: edit_mate_reference(vobj.Object))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def mate_references(doc):
    return [o for o in (doc.Objects if doc is not None else [])
            if getattr(getattr(o, "Proxy", None), "Type", None) == MATEREF_TYPE]


def entries(ref):
    """[(obj, sub, mate type, alignment)] of a mate reference, in Primary, Secondary, Tertiary order."""
    out = []
    types = list(ref.MateTypes)
    aligns = list(ref.Alignments)
    for i, text in enumerate(ref.Entities):
        name, _sep, sub = text.partition(":")
        obj = ref.Document.getObject(name)
        if obj is None:
            continue
        out.append((obj, sub, types[i] if i < len(types) else "Default", aligns[i] if i < len(aligns) else "Any"))
    return out[:3]


def make_mate_reference(doc, name, rows):
    """rows: [(obj, sub, mate type, alignment)] (1 to 3). Returns the feature."""
    obj = doc.addObject("App::FeaturePython", "MateReference")
    MateReference(obj)
    if App.GuiUp:
        MateReferenceView(obj.ViewObject)
    set_mate_reference(obj, name, rows)
    obj.Label = name
    if ac.assembly_of(doc) is None:
        try:
            mate_folder(doc).addObject(obj)
        except Exception as _fw_err:
            _fw_log("asmrefgeom.py:mate folder", _fw_err)
    return obj


FOLDER = "MateReferences"


def _named_by_ref(obj):
    """The tree row still shows the Reference Name: the name itself, or the name with the number FreeCAD added to
    keep labels apart (a second "Default" shows as Default001)."""
    import re
    ref = getattr(obj, "RefName", None) or ""
    return bool(ref) and re.fullmatch(re.escape(ref) + r"\d*", obj.Label or "") is not None


def mate_folder(doc):
    ""
    for o in doc.Objects:
        if o.TypeId == "App::DocumentObjectGroup" and o.Label == FOLDER:
            return o
    group = doc.addObject("App::DocumentObjectGroup", FOLDER)
    group.Label = FOLDER
    return group


def signature(shape):
    """{kind, type, point, dir, size} of an entity, for finding it again."""
    import json
    g = ac.geometry(shape)
    sig = {"kind": shape.ShapeType}
    if g is not None:
        sig.update(type=g[0], point=list(g[1]), dir=list(g[2]) if g[2] is not None else None)
    try:
        sig["size"] = getattr(shape, "Area", 0) if shape.ShapeType == "Face" else getattr(shape, "Length", 0)
        sig["radius"] = getattr(getattr(shape, "Surface", None) or getattr(shape, "Curve", None), "Radius", None)
    except Exception as _fw_err:
        _fw_log("asmrefgeom.py:282", _fw_err)
    return json.dumps(sig)


def find_again(obj, sig_text):
    ""



    import json
    try:
        sig = json.loads(sig_text)
    except Exception:
        return None
    kind = sig.get("kind")
    items = {"Face": obj.Shape.Faces, "Edge": obj.Shape.Edges, "Vertex": obj.Shape.Vertexes}.get(kind, [])
    p0 = App.Vector(*sig["point"]) if sig.get("point") else None
    d0 = App.Vector(*sig["dir"]).normalize() if sig.get("dir") else None
    best, score = None, None
    for i, e in enumerate(items, 1):
        g = ac.geometry(e)
        if g is None or g[0] != sig.get("type"):
            continue
        sc = 0.0
        if d0 is not None and g[2] is not None:
            d = App.Vector(g[2]).normalize()
            if abs(abs(d.dot(d0)) - 1.0) > 1e-4:
                continue
            if p0 is not None:
                off = App.Vector(g[1]) - p0
                if g[0] in ("axis", "line"):
                    sc += (off - d0 * off.dot(d0)).Length
                elif g[0] == "plane":
                    sc += abs(off.dot(d0))
        elif p0 is not None:
            sc += (App.Vector(g[1]) - p0).Length
        r0 = sig.get("radius")
        r1 = getattr(getattr(e, "Surface", None) or getattr(e, "Curve", None), "Radius", None)
        if r0 and r1:
            sc += abs(r1 - r0) * 0.01
        if score is None or sc < score:
            best, score = "%s%d" % (kind, i), sc
    return best if best is not None and score is not None and score < 1e-3 + 1e-2 else None


def _same_entity(obj, sig_text):
    """mrefmove: the element that is exactly what the entity was (kind, type, place, direction, size): the entity
    under a new element name after the part's topology changed. None when no element is."""
    import json
    try:
        sig = json.loads(sig_text)
    except Exception:
        return None
    items = {"Face": obj.Shape.Faces, "Edge": obj.Shape.Edges, "Vertex": obj.Shape.Vertexes}.get(sig.get("kind"), [])
    for i, e in enumerate(items, 1):
        try:
            other = json.loads(signature(e))
        except Exception:
            continue
        if other.get("type") != sig.get("type"):
            continue
        same = True
        for key in ("point", "dir"):
            a, b = sig.get(key), other.get(key)
            if (a is None) != (b is None) or (a is not None and (App.Vector(*a) - App.Vector(*b)).Length > 1e-6):
                same = False
        for key in ("size", "radius"):
            a, b = sig.get(key), other.get(key)
            if (a is None) != (b is None) or (a is not None and abs(float(a) - float(b)) > 1e-6):
                same = False
        if same:
            return "%s%d" % (sig.get("kind"), i)
    return None


def _kind_type(shape):
    g = ac.geometry(shape)
    return shape.ShapeType, (g[0] if g is not None else None)


def repair(ref):
    ""




    sigs = list(getattr(ref, "Signatures", []) or [])
    ents = list(ref.Entities)
    fixed = []
    fresh = list(sigs)
    for i, text in enumerate(ents):
        name, _sep, sub = text.partition(":")
        obj = ref.Document.getObject(name)
        if obj is None or i >= len(sigs) or not sigs[i]:
            continue
        try:
            element = obj.Shape.getElement(sub)
        except Exception:
            element = None
        try:
            ok = element is not None and signature(element) == sigs[i]
        except Exception:
            ok = False
        if ok:
            continue
        got = _same_entity(obj, sigs[i])
        if got is None and element is not None:
            try:
                import json
                was = json.loads(sigs[i])
                if _kind_type(element) == (was.get("kind"), was.get("type")):
                    fresh[i] = signature(element)       # the same entity, moved or resized: it stays
                    continue
            except Exception as _fw_err:
                _fw_log("asmrefgeom.py:repair-keep", _fw_err)
        if got is None:
            got = find_again(obj, sigs[i])
        if got and got != sub:
            ents[i] = "%s:%s" % (name, got)
            fixed.append((sub, got))
            try:
                fresh[i] = signature(obj.Shape.getElement(got))
            except Exception as _fw_err:
                _fw_log("asmrefgeom.py:repair-sig", _fw_err)
    if fresh != sigs:
        try:
            ref.Signatures = fresh
        except Exception as _fw_err:
            _fw_log("asmrefgeom.py:repair-fresh", _fw_err)
    if fixed:
        ref.Entities = ents
        App.Console.PrintMessage("FreeCAD: Mate Reference %s repaired: %s\n" % (
            ref.RefName, ", ".join("%s -> %s" % f for f in fixed)))
    return fixed


def set_mate_reference(obj, name, rows):
    obj.RefName = name or "Default"
    obj.Entities = ["%s:%s" % (o.Name, s) for o, s, _t, _a in rows]
    try:
        obj.Proxy.setup(obj)
        obj.Signatures = [signature(o.Shape.getElement(s)) for o, s, _t, _a in rows]
    except Exception as _fw_err:
        _fw_log("asmrefgeom.py:361", _fw_err)
    obj.MateTypes = [t for _o, _s, t, _a in rows]
    obj.Alignments = [a for _o, _s, _t, a in rows]


def _element(comp, obj, sub):
    """The component's element (its subname) matching a mate reference entity of its part."""
    target = getattr(comp, "LinkedObject", None)
    if target is None:
        return None
    if not sub:
        return None
    if obj == target or getattr(target, "Tip", None) == obj:
        return sub
    try:
        want = obj.Shape.getElement(sub)
    except Exception:
        return None
    try:
        # a feature's shape is in its body's coordinates, the component's in the part's: a body with its
        # own placement (or a part holding it) moves its faces, so compare them where the part has them
        def _frame(o):
            up = o.getParentGeoFeatureGroup()
            return up.getGlobalPlacement() if up is not None else App.Placement()
        rel = _frame(target).inverse().multiply(_frame(obj))
        if not rel.isIdentity():
            want = want.copy()
            want.transformShape(rel.toMatrix())
    except Exception as _fw_err:
        _fw_log("asmrefgeom.py:element-frame", _fw_err)
    shape = target.Shape
    kind = want.ShapeType
    items = {"Face": shape.Faces, "Edge": shape.Edges, "Vertex": shape.Vertexes}.get(kind, [])
    for i, e in enumerate(items):
        try:
            if e.isSame(want) or (abs(e.CenterOfMass.distanceToPoint(want.CenterOfMass)) < 1e-6 and
                                  abs(getattr(e, "Area", 0) - getattr(want, "Area", 0)) < 1e-6 and
                                  abs(getattr(e, "Length", 0) - getattr(want, "Length", 0)) < 1e-6):
                return "%s%d" % (kind, i + 1)
        except Exception:
            continue
    return None


def _source_doc(comp):
    target = getattr(comp, "LinkedObject", None)
    return target.Document if target is not None else None


def component_refs(comp, features=False):
    """{name: [(subname on the component, mate type, alignment)]} of a component's part
    (features: {name: the Mate Reference feature} as well)."""
    out, feats = {}, {}
    for ref in mate_references(_source_doc(comp)):
        try:
            repair(ref)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Mate Reference repair: %s\n" % error)
        rows = []
        for obj, sub, kind, align in entries(ref):
            element = _element(comp, obj, sub)
            if element is not None:
                rows.append((element, kind, align))
        if rows and ref.RefName not in out:
            out[ref.RefName] = rows
            feats[ref.RefName] = ref
    return (out, feats) if features else out


def _kinds(comp, rows):
    out = []
    for sub, _t, _a in rows:
        try:
            s = comp.Shape.getElement(sub)
            out.append((s.ShapeType, getattr(getattr(s, "Surface", None), "TypeId", "") or
                        getattr(getattr(s, "Curve", None), "TypeId", "")))
        except Exception:
            out.append(None)
    return out


def _pair(comp, mine, mfeat, other, theirs, tfeat):
    ""

    name = next((n for n in mine if n in theirs), None)
    if name is not None:
        return name, name
    for a, rows in mine.items():
        if getattr(mfeat.get(a), "NamesMatch", False):
            continue
        for b, trows in theirs.items():
            if getattr(tfeat.get(b), "NamesMatch", False) or len(rows) != len(trows):
                continue
            if _kinds(comp, rows) == _kinds(other, trows):
                return a, b
    return None


def _normal(comp, sub):
    try:
        s = comp.Shape.getElement(sub)
        if s.ShapeType == "Face":
            return s.normalAt(*s.Surface.parameter(s.CenterOfMass)) if hasattr(s.Surface, "parameter") else s.normalAt(0, 0)
        if s.ShapeType == "Edge" and type(s.Curve).__name__ in ("Line", "LineSegment"):
            return (s.Vertexes[-1].Point - s.Vertexes[0].Point).normalize()
        if s.ShapeType == "Edge" and hasattr(s.Curve, "Axis"):
            return App.Vector(s.Curve.Axis)
    except Exception as _fw_err:
        _fw_log("asmrefgeom.py:457", _fw_err)
    return None


SOLUTIONS = {}     # (document, component): {"cands": [...], "at": index, "mates": [names]}


def solutions(asm, comp, point=None):
    """Every way the component's mate references can mate: [(other, my name, their name)], the
    nearest to the drop point first."""
    mine, mfeat = component_refs(comp, True)
    if not mine:
        return []
    others = [o for o in ac.components(asm) if o is not comp]
    if point is not None:
        def dist(o):
            try:
                return (o.Shape.BoundBox.Center - point).Length
            except Exception:
                return 1e30
        others.sort(key=dist)
    out = []
    for other in others:
        theirs, tfeat = component_refs(other, True)
        pair = _pair(comp, mine, mfeat, other, theirs, tfeat)
        if pair is not None:
            out.append((other, pair[0], pair[1]))
    return out


def _mate_to(asm, comp, other, name, tname):
    mine, mfeat = component_refs(comp, True)
    theirs, tfeat = component_refs(other, True)
    if name not in mine or tname not in theirs:
        return []
    lock = bool(getattr(mfeat.get(name), "LockRotation", False) or getattr(tfeat.get(tname), "LockRotation", False))
    return _mate_rows(asm, comp, other, mine[name], theirs[tname], lock, name)


def _mate_rows(asm, comp, other, my_rows, their_rows, lock, name):
    rows = []
    for (sa, ta, la), (sb, tb, lb) in zip(my_rows, their_rows):
        kind = ta if ta != "Default" else (tb if tb != "Default" else
                                           default_type(comp.Shape.getElement(sa), other.Shape.getElement(sb)))
        align = la if la != "Any" else lb
        # FreeCAD's joint lines the two entities up aligned; turning one part over makes them
        # anti-aligned. Closest keeps the way they face now. Any: as the other entities need.
        flip = None if align == "Any" else align == "Anti-Aligned"
        if align == "Closest":
            na, nb = _normal(comp, sa), _normal(other, sb)
            flip = bool(na is not None and nb is not None and na.dot(nb) < 0)
        rows.append([kind, sa, sb, flip])
    # an axis with no alignment of its own goes the way an aligned entity turns the part, or the
    # mates would fight (a Concentric holds its axis direction in FreeCAD)
    turned = any(r[3] for r in rows)
    added = []
    for kind, sa, sb, flip in rows:
        try:
            if kind == "Concentric" and lock:
                added.append(ac.add_mate(asm, kind, (other, sb), (comp, sa), flip=turned if flip is None else flip,
                                         lock_rotation=True))
            else:
                added.append(ac.add_mate(asm, kind, (other, sb), (comp, sa), flip=turned if flip is None else flip))
        except Exception as error:
            App.Console.PrintWarning("Mate Reference %s: %s\n" % (name, error))
    added = [a for a in added if a is not None]
    if added:
        try:
            ac.solve(asm)
        except Exception as _fw_err:
            _fw_log("asmrefgeom.py:523", _fw_err)
    return added


def _axis_of(shape):
    """(point, unit direction, radius) of a round face or circular edge, else None."""
    try:
        g = shape.Surface if shape.ShapeType == "Face" else shape.Curve
        if g.TypeId not in ("Part::GeomCylinder", "Part::GeomCircle", "Part::GeomCone"):
            return None
        c = App.Vector(g.Apex if g.TypeId == "Part::GeomCone" else g.Center)
        return c, App.Vector(g.Axis).normalize(), float(getattr(g, "Radius", 0.0))
    except Exception:
        return None


def _is_plane(shape):
    try:
        return shape.ShapeType == "Face" and shape.Surface.TypeId == "Part::GeomPlane"
    except Exception:
        return False


def geometry_match(asm, comp, point):
    ""




    mine, mfeat = component_refs(comp, True)
    if not mine or point is None:
        return None
    name = sorted(mine)[0]
    rows = mine[name]
    if getattr(mfeat.get(name), "NamesMatch", False):
        return None         # Create mates only when names match
    try:
        first = comp.Shape.getElement(rows[0][0])
    except Exception:
        return None
    if _axis_of(first) is None:
        return None
    best = None
    for other in ac.components(asm):
        if other is comp:
            continue
        try:
            faces = other.Shape.Faces
        except Exception:
            continue
        for i, f in enumerate(faces, 1):
            ax = _axis_of(f) if f.Surface.TypeId == "Part::GeomCylinder" else None
            if ax is None:
                continue
            c, a, _r = ax
            d = point - c
            off = (d - a * d.dot(a)).Length
            if best is None or off < best[0]:
                best = (off, other, i, c, a)
    if best is None:
        return None
    _off, other, hole, c, a = best
    out = [("Face%d" % hole, "Default", "Any")]      # the seat below: FreeCAD puts the faces face to face
    oshape = other.Shape        # one shape: faces of two Shape reads are never isSame
    hole_face = oshape.Faces[hole - 1]
    for sub, _t, _al in rows[1:]:
        try:
            mineshape = comp.Shape.getElement(sub)
        except Exception:
            return None
        if not _is_plane(mineshape):
            break       # only a flat seat is looked for round the hole
        seat = None
        for j, f in enumerate(oshape.Faces, 1):
            if not _is_plane(f) or abs(abs(f.normalAt(0, 0).dot(a)) - 1) > 1e-6:
                continue
            if not any(e.isSame(he) for e in f.Edges for he in hole_face.Edges):
                continue
            dist = abs((f.CenterOfMass - point).dot(a))
            if seat is None or dist < seat[0]:
                seat = (dist, j)
        if seat is None:
            break
        out.append(("Face%d" % seat[1], "Default", "Any"))
    return other, out, name


def auto_mate(asm, comp, point=None):
    ""


    cands = solutions(asm, comp, point)
    for k, (other, name, tname) in enumerate(cands):
        added = _mate_to(asm, comp, other, name, tname)
        if added:
            SOLUTIONS[(asm.Document.Name, comp.Name)] = {"cands": [(o.Name, a, b) for o, a, b in cands], "at": k,
                                                         "mates": [m.Name for m in added]}
            if len(cands) > 1:
                _watch_tab(asm, comp)
                App.Console.PrintMessage("FreeCAD: %s mated by its mate reference to %s (%d solutions: Tab for the next)\n"
                                         % (comp.Label, other.Label, len(cands)))
            return added
    if not cands and point is not None:
        try:
            got = geometry_match(asm, comp, point)
            if got is not None:
                other, theirs, name = got
                mine, mfeat = component_refs(comp, True)
                lock = bool(getattr(mfeat.get(name), "LockRotation", False))
                return _mate_rows(asm, comp, other, mine[name][:len(theirs)], theirs, lock, name)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: mate reference on geometry: %s\n" % error)
    return []


def solution_count(asm, comp):
    got = SOLUTIONS.get((asm.Document.Name, comp.Name))
    return len(got["cands"]) if got else 0


def next_solution(asm, comp):
    """The mates from the component's mate reference moved to the next solution (round to the
    first). Returns the new mates, or [] when there is no other solution."""
    key = (asm.Document.Name, comp.Name)
    got = SOLUTIONS.get(key)
    if not got or len(got["cands"]) < 2:
        return []
    doc = asm.Document
    doc.openTransaction("Mate Reference: next solution")
    try:
        for n in got["mates"]:
            if doc.getObject(n) is not None:
                doc.removeObject(n)
        n = len(got["cands"])
        for step in range(1, n):
            k = (got["at"] + step) % n
            oname, a, b = got["cands"][k]
            other = doc.getObject(oname)
            if other is None:
                continue
            added = _mate_to(asm, comp, other, a, b)
            if added:
                got.update(at=k, mates=[m.Name for m in added])
                doc.recompute()
                return added
        return []
    finally:
        doc.commitTransaction()


_TAB = {}


def _watch_tab(asm, comp):
    """Tab in the graphics area, until something else is picked or inserted: next_solution."""
    if not App.GuiUp:
        return
    try:
        from . import asmspeedpak
        view = asmspeedpak._view_widget()
    except Exception:
        view = None
    if view is None:
        return
    _unwatch_tab()

    class F(QtCore.QObject):
        def eventFilter(self, w, e):
            try:
                if e.type() == QtCore.QEvent.KeyPress and e.key() == QtCore.Qt.Key_Tab:
                    next_solution(asm, comp)
                    return True
                if e.type() == QtCore.QEvent.MouseButtonPress:
                    QtCore.QTimer.singleShot(0, _unwatch_tab)
            except Exception as _fw_err:
                _fw_log("asmrefgeom.py:605", _fw_err)
            return False
    f = F(view)
    view.installEventFilter(f)
    _TAB.update(view=view, filter=f)


def _unwatch_tab():
    view, f = _TAB.pop("view", None), _TAB.pop("filter", None)
    if view is not None and f is not None:
        try:
            view.removeEventFilter(f)
        except Exception as _fw_err:
            _fw_log("asmrefgeom.py:618", _fw_err)


def _patch_insert():
    """Mate references act when the Insert Component PropertyManager places a component."""
    try:
        from . import asmpm
    except Exception:
        return
    panel = asmpm.InsertComponentPanel
    if getattr(panel, "_fw_materef", False):
        return
    old = panel._options
    old_clicked = panel._clicked

    def _clicked(self, cb):
        # asmpkg363: the round face or edge under the drop (the preview itself left out), so a mate reference

        self._fw_drop_at = None
        try:
            pos = cb.getEvent().getPosition().getValue()
            self._fw_drop_at = _round_under(self, (int(pos[0]), int(pos[1])))
        except Exception as _fw_err:
            _fw_log("asmrefgeom.py:drop point", _fw_err)
        return old_clicked(self, cb)

    def _options(self, comp):
        old(self, comp)
        try:
            auto_mate(self.asm, comp, getattr(self, "_fw_drop_at", None))
        except Exception as error:
            App.Console.PrintWarning("Mate Reference: %s\n" % error)

    panel._clicked = _clicked
    panel._options = _options
    panel._fw_materef = True


def _round_under(panel, pos):
    """The picked point on a round face or circular edge of another component under pos, else None."""
    preview = getattr(panel, "preview", None)
    # every hit along the ray: the preview under the pointer is skipped below (asmpkg364: it was hidden
    # for the pick, a Visibility change that marks the document changed)
    infos = panel.view.getObjectsInfo(pos) or []
    for info in infos:
        try:
            root = info.get("ParentObject") or App.getDocument(info["Document"]).getObject(info["Object"])
            sub = info.get("SubName", "") or info.get("Component", "")
            if preview is not None and (root is preview or preview.Name in sub.split(".")):
                continue
            import Part
            el = Part.getShape(root, sub, needSubElement=True)
            if el.ShapeType == "Face" and el.Surface.TypeId == "Part::GeomCylinder" or \
                    el.ShapeType == "Edge" and el.Curve.TypeId == "Part::GeomCircle":
                return App.Vector(info["x"], info["y"], info["z"])
            return None         # the nearest thing under the drop is not round: no geometry mate
        except Exception:
            continue
    return None


class _Focus(QtCore.QObject):
    def __init__(self, panel, index):
        super().__init__()
        self.panel, self.index = panel, index

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
            self.panel.active = self.index
            self.panel._show()
        return False


def _family_icon(name):
    try:
        from . import icons
        return icons.family(name)
    except Exception:
        return QtGui.QIcon()


def _align_glyph():
    """Two arrows the same way: the alignment mark, drawn here when the icon set has none."""
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pm = _hidpi.canvas(40, 40)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor("#2b6cb0"), 3))
    for y in (13, 27):
        p.drawLine(6, y, 32, y)
        p.drawLine(32, y, 25, y - 6)
        p.drawLine(32, y, 25, y + 6)
    p.end()
    pm.setDevicePixelRatio(2)
    return QtGui.QIcon(pm)


def _type_icon(kind):
    ""
    if kind == "Default":
        return QtGui.QIcon()
    try:
        from . import asmpm
        return asmpm.sw_icon(kind)
    except Exception:
        return QtGui.QIcon()


class MateReferencePanel:
    ""

    def __init__(self, doc, feature=None):
        self.doc = doc
        self.feature = feature
        self.active = 0
        self.rows = [None, None, None]          # (obj, sub)
        doc.openTransaction("Mate Reference")
        try:

            # rule, the fold chevron at its right): one panel widget per group
            def group(title, name):
                w = QtWidgets.QWidget()
                w.setObjectName(name)
                w.setWindowTitle(title)
                gl = QtWidgets.QVBoxLayout(w)
                gl.setContentsMargins(4, 4, 4, 4)
                gl.setSpacing(4)
                return w, gl
            form, bl = group("Reference Name", "SWMateReference")
            form.setProperty("swstyle_pm_title", "Mate Reference")
            form.setProperty("swstyle_pm_icon", "REFGEO_MATE_REF")
            self.groups = [form]
            box = form
            self.name = QtWidgets.QLineEdit(feature.RefName if feature is not None else "Default", box)
            self.name.setObjectName("SWMateRefName")
            bl.addWidget(self.name)
            self.picks, self.types, self.aligns, self.filters = [], [], [], []
            old = entries(feature) if feature is not None else []
            for i, slot in enumerate(SLOTS):
                box, bl = group("%s Reference Entity" % slot, "SWMateRefGroup%d" % i)
                self.groups.append(box)
                pick = QtWidgets.QListWidget(box)
                pick.setObjectName("SWMateRefPick%d" % i)
                pick.setMaximumHeight(28)
                f = _Focus(self, i)
                pick.installEventFilter(f)
                self.filters.append(f)
                pmboxes.bind(pick, remove=lambda row, k=i: self._drop(k))
                bl.addWidget(pick)

                # Alignment as two drop-downs, each with an icon on its left and no text label
                t = QtWidgets.QComboBox(box)
                for kind in MATE_TYPES:
                    t.addItem(_type_icon(kind), kind)
                t.setObjectName("SWMateRefType%d" % i)
                t.setToolTip("Mate Reference Type")
                a = QtWidgets.QComboBox(box)
                a.addItems(ALIGNMENTS)
                a.setObjectName("SWMateRefAlign%d" % i)
                a.setToolTip("Mate Reference Alignment")
                for combo, family, tip in ((t, "ASSEMBLIES_MATE", "Mate Reference Type"),
                                           (a, "ASSEMBLIES_MATE_ALIGNED", "Mate Reference Alignment")):
                    line = QtWidgets.QHBoxLayout()
                    mark = QtWidgets.QLabel(box)
                    mark.setObjectName(combo.objectName() + "Icon")
                    mark.setToolTip(tip)
                    icon = _family_icon(family)
                    if icon.isNull():
                        icon = _type_icon("Coincident") if combo is t else _align_glyph()
                    if not icon.isNull():
                        mark.setPixmap(icon.pixmap(20, 20))
                    mark.setFixedWidth(24)
                    line.addWidget(mark)
                    line.addWidget(combo, 1)
                    bl.addLayout(line)
                self.picks.append(pick)
                self.types.append(t)
                self.aligns.append(a)
                if i < len(old):
                    obj, sub, kind, align = old[i]
                    self.rows[i] = (obj, sub)
                    t.setCurrentText(kind)
                    a.setCurrentText(align)
            opts, ol = self.groups[0], self.groups[0].layout()
            self.names_match = QtWidgets.QCheckBox("Create mates only when names match", opts)
            self.names_match.setObjectName("SWMateRefNamesMatch")
            self.names_match.setChecked(bool(getattr(feature, "NamesMatch", False)))
            self.lock_rotation = QtWidgets.QCheckBox("Lock rotation", opts)
            self.lock_rotation.setObjectName("SWMateRefLockRotation")
            self.lock_rotation.setToolTip("Concentric reference mates lock the component's rotation")
            self.lock_rotation.setChecked(bool(getattr(feature, "LockRotation", False)))
            ol.addWidget(self.names_match)
            ol.addWidget(self.lock_rotation)
            self.form = self.groups
            for sel in Gui.Selection.getSelectionEx(doc.Name):
                for sub in (sel.SubElementNames or ()):
                    self._add(sel.Object, sub)
            self._show()
            Gui.Selection.addObserver(self)
            OPEN.append(self)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise

    def _resolve(self, obj, sub):
        from . import refplane
        return refplane.resolve(obj, sub)

    def addSelection(self, doc, name, sub, pnt):
        if doc != self.doc.Name or not sub:
            return
        obj = self.doc.getObject(name)
        if obj is not None:
            QtCore.QTimer.singleShot(0, lambda: (self._add(obj, sub), self._show()))

    def _add(self, obj, sub):
        obj, sub = self._resolve(obj, sub)
        try:
            if _kind(obj.Shape.getElement(sub)) is None:
                return
        except Exception:
            return
        if (obj, sub) in self.rows:
            i = self.rows.index((obj, sub))
            self.rows[i] = None              # a second pick takes it out
            self.active = i
            return
        slot = self.active if self.rows[self.active] is None else \
            next((i for i, r in enumerate(self.rows) if r is None), self.active)
        self.rows[slot] = (obj, sub)
        self.active = next((i for i, r in enumerate(self.rows) if r is None), slot)

    def _drop(self, slot):
        if self.rows[slot] is None:
            return
        self.rows[slot] = None
        self.active = slot
        self._show()

    def _show(self):

        before = []
        for i, pick in enumerate(self.picks):
            pick.clear()
            r = self.rows[i]
            if r is not None:
                try:
                    from . import refplanelook
                    text = refplanelook.sw_label(r[0], r[1], before)
                except Exception:
                    text = "%s@%s" % (r[1], r[0].Label)
                pick.addItem(text)
                before.append((r[0], r[1]))
            pmboxes.mark(pick, i == self.active)

    def values(self):
        return [(r[0], r[1], self.types[i].currentText(), self.aligns[i].currentText())
                for i, r in enumerate(self.rows) if r is not None]

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmrefgeom.py:838", _fw_err)
        if self in OPEN:
            OPEN.remove(self)
        Gui.Control.closeDialog()

    def accept(self):
        rows = self.values()
        if not rows:
            return False
        name = self.name.text().strip() or "Default"
        if self.feature is None:
            self.feature = make_mate_reference(self.doc, name, rows)
        else:
            if _named_by_ref(self.feature):
                self.feature.Label = name       # the tree follows a new Reference Name
            set_mate_reference(self.feature, name, rows)
        try:
            self.feature.Proxy.setup(self.feature)
            self.feature.NamesMatch = self.names_match.isChecked()
            self.feature.LockRotation = self.lock_rotation.isChecked()
        except Exception as _fw_err:
            _fw_log("asmrefgeom.py:857", _fw_err)
        asm = ac.assembly_of(self.doc)
        if asm is not None and self.feature not in asm.Group:
            try:
                asm.addObject(self.feature)
            except Exception as _fw_err:
                _fw_log("asmrefgeom.py:863", _fw_err)
                from . import fwtell
                fwtell.tell("The reference geometry was made, but it could not be added to the assembly.", _fw_err)
        self.doc.recompute()
        self.doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        self.doc.abortTransaction()
        try:        # FreeCAD's application-wide step stayed open after the abort (Reviewer, features-437)
            App.closeActiveTransaction(True)
        except Exception as _fw_err:
            _fw_log("asmrefgeom.py:materef-close", _fw_err)
        self._close()
        return True


def edit_mate_reference(feature=None, doc=None):
    doc = doc or (feature.Document if feature is not None else App.ActiveDocument)
    if doc is None or Gui.Control.activeDialog():
        return None
    panel = MateReferencePanel(doc, feature)
    Gui.Control.showDialog(panel)
    return panel


# ---------------------------------------------------------------------- ground plane
def ground_plane(asm):
    for o in asm.Group:
        if getattr(o, GROUND_PROP, False):
            return o
    return None


def set_ground(asm, ref, offset=0.0, flip=False, obj=None):
    """The assembly's Ground Plane on a plane or flat face, offset along its normal."""
    doc = asm.Document
    if obj is None:
        obj = doc.addObject("Part::DatumPlane", "GroundPlane")
        asm.addObject(obj)
        obj.addProperty("App::PropertyBool", GROUND_PROP, "FreeCAD", "Ground Plane")
        setattr(obj, GROUND_PROP, True)
        obj.addProperty("App::PropertyDistance", "Offset", "FreeCAD", "Offset from the picked plane")
        obj.addProperty("App::PropertyBool", "Flip", "FreeCAD", "Flip the offset")
        obj.Label = _next(doc, "Ground Plane")
    obj.Offset = offset
    obj.Flip = bool(flip)
    obj.MapMode = "Deactivated"
    obj.AttachmentSupport = [ref]
    obj.MapMode = "FlatFace"
    obj.AttachmentOffset = App.Placement(App.Vector(0, 0, -offset if flip else offset),
                                         App.Rotation(App.Vector(1, 0, 0), 180) if flip else App.Rotation())
    doc.recompute()
    return obj


def floor(asm):
    """(point, upward normal) of the Ground Plane, or None (motion and physics use it as the floor)."""
    g = ground_plane(asm) if asm is not None else None
    if g is None:
        return None
    p = g.getGlobalPlacement() if hasattr(g, "getGlobalPlacement") else g.Placement
    up = p.Rotation.multVec(App.Vector(0, 0, 1))
    try:        # up is the side the components are on
        box = None
        for c in ac.components(asm):
            b = c.Shape.BoundBox
            if b.isValid():
                box = b if box is None else box.united(b)
        if box is not None and (box.Center - p.Base).dot(up) < 0:
            up = -up
    except Exception as _fw_err:
        _fw_log("asmrefgeom.py:930", _fw_err)
    return p.Base, up


class GroundPlanePanel:
    ""

    def __init__(self, asm):
        self.asm, self.doc = asm, asm.Document
        self.obj = ground_plane(asm)
        self.ref = tuple(self.obj.AttachmentSupport[0][:1]) + (self.obj.AttachmentSupport[0][1][0],) \
            if self.obj is not None and self.obj.AttachmentSupport else None
        self.doc.openTransaction("Ground Plane")
        try:
            form = QtWidgets.QWidget()
            form.setObjectName("SWGroundPlane")
            form.setWindowTitle("Ground Plane")
            form.setProperty("swstyle_pm_title", "Ground Plane")
            lay = QtWidgets.QVBoxLayout(form)
            box = QtWidgets.QGroupBox("Selections", form)
            bl = QtWidgets.QVBoxLayout(box)
            self.pick = QtWidgets.QListWidget(box)
            self.pick.setObjectName("SWGroundPick")
            self.pick.setProperty("swpickbox", True)
            self.pick.setMaximumHeight(28)
            bl.addWidget(self.pick)
            row = QtWidgets.QHBoxLayout()
            self.offset = QtWidgets.QDoubleSpinBox(box)
            self.offset.setObjectName("SWGroundOffset")
            self.offset.setRange(-1e6, 1e6)
            self.offset.setDecimals(2)
            self.offset.setSuffix(" mm")
            self.offset.setValue(float(getattr(self.obj, "Offset", 0)) if self.obj is not None else 0.0)
            row.addWidget(QtWidgets.QLabel("Offset:"))
            row.addWidget(self.offset)
            self.flip = QtWidgets.QCheckBox("Flip", box)
            self.flip.setObjectName("SWGroundFlip")
            self.flip.setChecked(bool(getattr(self.obj, "Flip", False)) if self.obj is not None else False)
            row.addWidget(self.flip)
            bl.addLayout(row)
            lay.addWidget(box)
            lay.addStretch(1)
            self.form = form
            self.offset.valueChanged.connect(lambda *a: self.update())
            self.flip.toggled.connect(lambda *a: self.update())
            for sel in Gui.Selection.getSelectionEx(self.doc.Name):
                for sub in (sel.SubElementNames or ()):
                    self._add(sel.Object, sub)
            self.update()
            Gui.Selection.addObserver(self)
            OPEN.append(self)
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise

    def addSelection(self, doc, name, sub, pnt):
        if doc != self.doc.Name:
            return
        obj = self.doc.getObject(name)
        if obj is not None:
            from . import safe_later as _sl; _sl.later(0, lambda: (self._add(obj, sub), self.update()), self, "pick")

    def _add(self, obj, sub):
        from . import refplane
        obj, sub = refplane.resolve(obj, sub or "")
        if self.obj is not None and obj == self.obj:
            return
        if refplane.kind_of(obj, sub) != "plane" and obj.TypeId not in ("Part::DatumPlane", "App::Plane"):
            return
        self.ref = (obj, sub)

    def update(self):
        self.pick.clear()
        if self.ref is None:
            return
        self.pick.addItem("%s@%s" % (self.ref[1], self.ref[0].Label) if self.ref[1] else self.ref[0].Label)
        try:
            self.obj = set_ground(self.asm, self.ref, self.offset.value(), self.flip.isChecked(), self.obj)
        except Exception as error:
            App.Console.PrintWarning("Ground Plane: %s\n" % error)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmrefgeom.py:1013", _fw_err)
        if self in OPEN:
            OPEN.remove(self)
        Gui.Control.closeDialog()

    def accept(self):
        if self.obj is None:
            return False
        self.doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        self.doc.abortTransaction()
        self.doc.recompute()
        self._close()
        return True


def start_ground_plane(asm):
    if Gui.Control.activeDialog():
        return None
    panel = GroundPlanePanel(asm)
    Gui.Control.showDialog(panel)
    return panel


# ---------------------------------------------------------------------- install
def install():
    from . import refplane
    if not getattr(refplane, "_fw_asm_body", False):
        old = refplane.body_of

        def body_of(doc):
            h = holder(doc)
            return h if h is not None else old(doc)

        refplane.body_of = body_of
        refplane._fw_asm_body = True
    _patch_insert()
