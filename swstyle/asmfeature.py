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
from PySide import QtCore, QtWidgets

from . import asmcore as ac
from . import selguard

V = App.Vector
FEATURE_PROP = "FwAsmFeature"
BODY_PROP = "FwAsmCutBody"
KINDS = {"Extrude": "Cut-Extrude", "Revolve": "Cut-Revolve", "Hole": "Hole", "Fillet": "Fillet", "Chamfer": "Chamfer", "Sweep": "Cut-Sweep", "Wizard": "Hole Wizard", "Series": "Hole Series", "Weld": "Weld Bead", "Belt": "Belt"}
EDGE_KINDS = ("Fillet", "Chamfer")
ICONS = {"Extrude": "PartDesign_Pocket", "Revolve": "PartDesign_Groove", "Hole": "PartDesign_Hole",
         "Fillet": "PartDesign_Fillet", "Chamfer": "PartDesign_Chamfer", "Sweep": "PartDesign_SubtractivePipe",
         "Wizard": "PartDesign_Hole", "Series": "PartDesign_Hole",
         "Weld": "Part_Sweep", "Belt": "Assembly_CreateJointGears"}
EXTRA = (   # added to every assembly feature (older files get them when edited)
    ("App::PropertyVector", "Point", "Hole", "Hole center on the picked face, in the assembly"),
    ("App::PropertyVector", "Normal", "Hole", "The picked face's normal, in the assembly"),
    ("App::PropertyLength", "Diameter", "Hole", "Hole diameter"),
    ("App::PropertyLength", "Radius", "Edges", "Fillet radius or chamfer distance"),
    ("App::PropertyStringList", "Edges", "Edges", "component|x,y,z: a point of each edge on the component"),
    ("App::PropertyLink", "Path", "Sweep", "The path sketch of a Swept Cut"),
    ("App::PropertyString", "Spec", "Hole Wizard", "The Hole Wizard's Type tab choices (json)"),
    ("App::PropertyVectorList", "Points", "Hole Wizard", "Hole positions, in the assembly"),
    ("App::PropertyBool", "Tapped", "Hole Series", "Hole Series: the last part gets a tapped hole"),
    ("App::PropertyString", "SeriesMiddle", "Hole Series", "Middle Part tab (json): auto size, or its own clearance hole"),
    ("App::PropertyString", "SeriesLast", "Hole Series", "Last Part tab (json): Hole or Tap, auto size, end condition"),
    ("App::PropertyBool", "SeriesFasteners", "Hole Series", "Smart Fasteners tab: add fasteners to the series"),
    ("App::PropertyStringList", "WeldFrom", "Weld Bead", "component|x,y,z: a point on each Weld From face"),
    ("App::PropertyStringList", "WeldTo", "Weld Bead", "component|x,y,z: a point on each Weld To face"),
    ("App::PropertyLinkHidden", "Bead", "Weld Bead", "The bead (or belt) the assembly shows"),
    ("App::PropertyStringList", "Members", "Belt", "component|x,y,z: a point on each pulley's round face, in order"),
    ("App::PropertyBool", "UseThickness", "Belt", "Use belt thickness"),
    ("App::PropertyLength", "Thickness", "Belt", "Belt thickness"),
    ("App::PropertyBool", "Engage", "Belt", "Engage belt: the pulleys turn together"),
    ("App::PropertyBool", "BeltPart", "Belt", "Create belt part: a solid belt"),
    ("App::PropertyStringList", "FlipSides", "Belt", "Flip belt side: the members the belt goes round on the inside"),
    ("App::PropertyBool", "Driving", "Belt", "Driving: the belt length sets the distance to the last free pulley"),
    ("App::PropertyLength", "BeltLength", "Belt", "Driving: the belt length"),
    ("App::PropertyVector", "UpToPoint", "Cut", "Up To Vertex / Surface: the point picked, in the assembly"),
    ("App::PropertyVector", "UpToNormal", "Cut", "Up To Surface: the face's normal"),
    ("App::PropertyLength", "Offset", "Cut", "Offset From Surface: the offset"),
    ("App::PropertyBool", "ReverseOffset", "Cut", "Offset From Surface: Reverse offset"),
    ("App::PropertyBool", "Direction2", "Cut", "Direction 2 on"),
    ("App::PropertyBool", "Suppressed", "Base", "Suppressed (Suppress, per configuration with a configuration table)"),
    ("App::PropertyString", "End2", "Cut", "Direction 2 end condition (Blind, Through All)"),
    ("App::PropertyLength", "Depth2", "Cut", "Direction 2 depth"),
    ("App::PropertyAngle", "Angle2", "Cut", "Revolve Direction 2 angle"),
    ("App::PropertyString", "RevolveType", "Cut", "Revolve type: Blind or Mid-Plane"),
    ("App::PropertyBool", "Draft", "Cut", "Draft on/off"),
    ("App::PropertyAngle", "DraftAngle", "Cut", "Draft angle"),
    ("App::PropertyBool", "DraftOutward", "Cut", "Draft outward"),
    ("App::PropertyIntegerList", "Contours", "Cut", "Selected Contours: the profile's closed wires used (all when empty)"),
    ("App::PropertyBool", "Propagate", "Feature Scope", "Propagate feature to parts: the cut goes into the part files too"),
    ("App::PropertyString", "ChamferType", "Edges", "Angle Distance, Distance Distance"),
    ("App::PropertyAngle", "ChamferAngle", "Edges", "Angle Distance: the angle"),
    ("App::PropertyLength", "Distance2", "Edges", "Distance Distance: the second distance"),
    ("App::PropertyBool", "FlipChamfer", "Edges", "Flip direction"),
    ("App::PropertyString", "Orientation", "Sweep", "Swept Cut Options: Follow Path or Keep Normal Constant"),
    ("App::PropertyString", "Twist", "Sweep", "Profile Twist: None, Specify Twist Value, Specify Direction Vector"),
    ("App::PropertyString", "TwistUnit", "Sweep", "Twist control: Degrees, Radians, Turns"),
    ("App::PropertyFloat", "TwistValue", "Sweep", "Direction 1: the twist, in TwistUnit"),
    ("App::PropertyVector", "TwistVector", "Sweep", "Specify Direction Vector: the profile keeps this direction"),
    ("App::PropertyString", "FilletType", "Edges", "Fillet Type: Constant Size or Variable Size"),
    ("App::PropertyLength", "Radius2", "Edges", "Variable Size: the radius at each edge's end"),
    ("App::PropertyLength", "Distance3", "Edges", "Vertex chamfer: the third distance"),
    ("App::PropertyBool", "EqualDistance", "Edges", "Vertex chamfer: Equal distance"),
)
FILLET_TYPES = ("Constant Size", "Variable Size", "Face Fillet", "Full Round Fillet")
FACE_FILLETS = ("Face Fillet", "Full Round Fillet")
SWEEP_ORIENTATIONS = ("Follow Path", "Keep Normal Constant")
SWEEP_TWISTS = ("None", "Specify Twist Value", "Specify Direction Vector")
TWIST_UNITS = ("Degrees", "Radians", "Turns")
BELT_PROP = "FwBeltOf"
BEAD_PROP = "FwWeldBead"
END = ("Blind", "Through All", "Up To Next", "Up To Vertex", "Up To Surface", "Offset From Surface", "Mid Plane")
END2 = ("Blind", "Through All")
REVOLVE_TYPES = ("Blind", "Mid-Plane")
UP_TO = ("Up To Vertex", "Up To Surface", "Offset From Surface")
HOLE_END = ("Blind", "Through All", "Up To Next")


# ---------------------------------------------------------------- objects
class Feature:
    def __init__(self, obj, kind):
        obj.Proxy = self
        obj.addProperty("App::PropertyString", FEATURE_PROP, "FreeCAD", "Assembly feature kind")
        obj.setPropertyStatus(FEATURE_PROP, "Hidden")
        setattr(obj, FEATURE_PROP, kind)
        obj.addProperty("App::PropertyLink", "Profile", "Cut", "The sketch")
        obj.addProperty("App::PropertyEnumeration", "EndCondition", "Cut", "Blind or Through All")
        obj.EndCondition = list(END)
        obj.addProperty("App::PropertyLength", "Depth", "Cut", "Blind depth").Depth = 10.0
        obj.addProperty("App::PropertyAngle", "Angle", "Cut", "Revolve angle").Angle = 360.0
        obj.addProperty("App::PropertyBool", "Reversed", "Cut", "Reverse direction")
        obj.addProperty("App::PropertyBool", "AutoSelect", "Feature Scope", "Every component the cut reaches").AutoSelect = True
        obj.addProperty("App::PropertyStringList", "Scope", "Feature Scope", "The components it cuts (names)")
        _extra(obj)

    def execute(self, obj):
        update(obj)

    def onDocumentRestored(self, obj):
        try:
            _extra(obj)         # older files: Suppressed and the later properties
        except Exception as _fw_err:
            _fw_log("asmfeature.py:126", _fw_err)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_suppressed(feat):
    return bool(getattr(feat, "Suppressed", False))


def _extra(obj):
    for typ, name, group, tip in EXTRA:
        if not hasattr(obj, name):
            obj.addProperty(typ, name, group, tip)
    try:
        if hasattr(obj, "EndCondition") and list(obj.getEnumerationsOfProperty("EndCondition")) != list(END):
            now = obj.EndCondition
            obj.EndCondition = list(END)
            obj.EndCondition = now if now in END else END[0]
    except Exception as _fw_err:
        _fw_log("asmfeature.py:149", _fw_err)
    if float(getattr(obj.Diameter, "Value", obj.Diameter)) == 0:
        obj.Diameter = 10.0
    if float(getattr(obj.Radius, "Value", obj.Radius)) == 0:
        obj.Radius = 2.0


class ViewProviderFeature:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        try:    # an empty picture: FreeCAD's tree greys an object it has none to show for
            from pivy import coin
            vobj.addDisplayMode(coin.SoGroup(), "Default")
        except Exception as _fw_err:
            _fw_log("asmfeature.py:166", _fw_err)

    def getIcon(self):
        kind = getattr(self.Object, FEATURE_PROP, "Extrude") if hasattr(self, "Object") else "Extrude"
        return ICONS.get(kind, "PartDesign_Pocket")

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def claimChildren(self):
        obj = getattr(self, "Object", None)     # (asked before attach while a file opens)
        return [o for o in (getattr(obj, "Profile", None), getattr(obj, "Path", None)) if o is not None]

    def doubleClicked(self, vobj):
        edit(vobj.Object)
        return True

    def setupContextMenu(self, vobj, menu):
        act = menu.addAction("Edit Feature")
        act.triggered.connect(lambda: edit(vobj.Object))

    def onDelete(self, vobj, subs):
        QtCore.QTimer.singleShot(0, lambda doc=vobj.Object.Document.Name: _after_delete(doc))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


class CutBody:
    """The part as a cut component shows it: its shape is set by the assembly's cuts."""

    def __init__(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderCutBody:
    """Shows the part's own icon (the component keeps its part's look in the tree)."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        try:
            own = getattr(self.Object, BODY_PROP, None) or getattr(self.Object, "FwSpeedPakOf")
            icon = own.ViewObject.Icon
            if icon is not None and not icon.isNull():
                return icon
        except Exception as _fw_err:
            _fw_log("asmfeature.py:233", _fw_err)
        return ":/icons/Tree_Part.svg"

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_feature(obj):
    return obj is not None and bool(getattr(obj, FEATURE_PROP, ""))


def is_body(obj):
    return obj is not None and getattr(obj, BODY_PROP, None) is not None


def features(asm):
    return [o for o in asm.Group if is_feature(o)]


_FOLLOW = {}        # (document, feature) -> the components' placements its bead was last made for


def _part_stamp(comp):
    ""

    try:
        return own_part(comp).Shape.hashCode()
    except Exception:
        return None


def _stamp(asm):
    return tuple((c.Name, tuple(round(x, 9) for x in c.Placement.toMatrix().A), _part_stamp(c)) for c in ac.components(asm))


def follow(asm):
    ""



    feats = [f for f in features(asm) if not is_suppressed(f)]
    if not feats:
        return False
    now = _stamp(asm)
    key = (asm.Document.Name, asm.Name)
    old = _FOLLOW.get(key)
    _FOLLOW[key] = now
    if old is None:
        # the first solve after it was made or opened: as it is, unless a part it cuts is not the
        # part the cut was made on (changed in its file, the assembly opened from a copy)
        if not _sources_changed(asm):
            return False
    elif old == now:
        return False
    try:
        from . import asmgen
        structure = not asmgen.recomputing(asm.Document)
    except Exception:
        structure = False
    try:
        update(feats[0], structure)     # every feature of the assembly, cuts first, then beads and belts
    except Exception as error:
        App.Console.PrintLog("FreeCAD: assembly features after a move: %s\n" % error)
        return False
    _sources_changed(asm)
    return True


SRC_PROP = "FwAsmCutSource"


def _source_sig(body):
    """The cut body's own part as built: its volume and box."""
    try:
        sh = getattr(body, BODY_PROP).Shape
        bb = sh.BoundBox
        return "%.6g %.6g %.6g %.6g %.6g %.6g %.6g" % (sh.Volume, bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)
    except Exception:
        return ""


def _sources_changed(asm):
    """True when a cut component's part is not what its cut was last made from; each cut body then
    keeps what it is made from now."""
    changed = False
    for c in ac.components(asm):
        body = getattr(c, "LinkedObject", None)
        if not is_body(body):
            continue
        sig = _source_sig(body)
        if not sig:
            continue
        if SRC_PROP not in body.PropertiesList:
            body.addProperty("App::PropertyString", SRC_PROP, "FreeWorks", "The part the cut was made from")
            body.setEditorMode(SRC_PROP, 2)
        elif getattr(body, SRC_PROP) and getattr(body, SRC_PROP) != sig:
            changed = True
        if getattr(body, SRC_PROP) != sig:
            setattr(body, SRC_PROP, sig)
    return changed


def source(obj):
    """The part a component's linked object stands for (a cut body's own part)."""
    if is_body(obj):
        return getattr(obj, BODY_PROP)
    return obj


def own_part(comp):
    target = comp.LinkedObject if comp.TypeId == "App::Link" else comp
    return source(target)


# ---------------------------------------------------------------- geometry
def _local(obj):
    shape = obj.Shape.copy()
    shape.Placement = App.Placement()
    return shape


def global_shape(comp):
    shape = _local(own_part(comp))
    return shape.transformed(comp.Placement.toMatrix())


def profile_face(sketch, contours=None):
    """The sketch's closed profile; contours (Selected Contours) = the indices of the closed wires used."""
    import Part
    wires = [w for w in sketch.Shape.Wires if w.isClosed()]
    if contours:
        wires = [w for i, w in enumerate(wires) if i in set(contours)]
    if not wires:
        return None
    return Part.makeFace(wires, "Part::FaceMakerBullseye")


def contour_count(sketch):
    return len([w for w in sketch.Shape.Wires if w.isClosed()]) if sketch is not None else 0


def _axis(sketch):
    """The sketch's first construction line, in the assembly: (point, direction)."""
    place = sketch.getGlobalPlacement()
    for i, g in enumerate(sketch.Geometry):
        if g.TypeId == "Part::GeomLineSegment" and sketch.getConstruction(i):
            a, b = place.multVec(g.StartPoint), place.multVec(g.EndPoint)
            return a, (b - a)
    return None


def _length(feat, asm):
    if feat.EndCondition == "Through All":
        return 2.0 * _span(asm or ac.assembly_of(feat.Document)) + 1.0
    return float(getattr(feat.Depth, "Value", feat.Depth))


def _row_visible(w, on):
    ""
    if w.parentWidget() is None:
        return              # a box this kind of PM never lays out
    w.setVisible(bool(on))
    lays = [w.parentWidget().layout()] if w.parentWidget().layout() is not None else []
    while lays:
        lay = lays.pop()
        if isinstance(lay, QtWidgets.QFormLayout):
            label = lay.labelForField(w)
            if label is not None:
                label.setVisible(bool(on))
                return
        for i in range(lay.count()):
            item = lay.itemAt(i)
            if item is not None and item.layout() is not None:
                lays.append(item.layout())


def _takes_over(widget, option, value=True):
    """A box that belongs to an option stays live: using it sets the option (asmpattern)."""
    from .asmpattern import _takes_over as take
    return take(widget, option, value)


def _val(q):
    return float(getattr(q, "Value", q))


def _drafted(face, direction, length, angle, outward):
    """face swept length along direction, its outline growing (outward) or shrinking by the draft angle."""
    import math
    import Part
    if abs(angle) < 1e-9:
        return face.extrude(direction * length)
    grow = length * math.tan(math.radians(angle)) * (1 if outward else -1)
    solids = []
    for w in face.Wires[:1] if len(face.Wires) else []:
        try:
            far = w.makeOffset2D(grow, 2) if abs(grow) > 1e-9 else w.copy()
            far.translate(direction * length)
            solids.append(Part.makeLoft([w, far], True, True))
        except Exception:
            solids.append(face.extrude(direction * length))
    if not solids:
        return face.extrude(direction * length)
    out = solids[0]
    for inner in face.Wires[1:]:
        try:
            hole = Part.Face(inner).extrude(direction * length)
            out = out.cut(hole)
        except Exception as _fw_err:
            _fw_log("asmfeature.py:371", _fw_err)
    return out


def _up_to_next(face, direction, asm):
    """Up To Next: as far as the far side of the first component the cut reaches."""
    big = 2.0 * _span(asm) + 1.0
    probe = face.extrude(direction * big)
    origin = face.CenterOfMass
    best = None
    for comp in ac.components(asm):
        try:
            shape = global_shape(comp)
        except Exception:
            continue
        if shape is None or shape.isNull() or not probe.BoundBox.intersect(shape.BoundBox):
            continue
        try:
            common = probe.common(shape)
        except Exception:
            continue
        if common.isNull() or common.Volume < 1e-6:
            continue
        near = min(direction.dot(v.Point - origin) for v in common.Vertexes)
        far = max(direction.dot(v.Point - origin) for v in common.Vertexes)
        if best is None or near < best[0]:
            best = (near, far)
    return best[1] if best else big


def cut_length(feat, asm, face, direction):
    """Direction 1's length from the end condition (Blind, Through All, Up To ..., Offset From Surface)."""
    end = feat.EndCondition
    asm = asm or ac.assembly_of(feat.Document)
    if end == "Through All":
        return 2.0 * _span(asm) + 1.0
    if end == "Up To Next":
        return _up_to_next(face, direction, asm)
    if end in UP_TO:
        p = V(feat.UpToPoint)
        d = direction.dot(p - face.CenterOfMass)
        if end == "Offset From Surface":
            d += _val(feat.Offset) * (1 if feat.ReverseOffset else -1)
        return max(1e-3, d)
    return _val(feat.Depth)


def tool(feat, asm=None):
    """The cut's solid in the assembly, or None (an edge feature has none)."""
    kind = getattr(feat, FEATURE_PROP)
    if kind in EDGE_KINDS or kind in ("Weld", "Belt"):
        return None
    if kind == "Hole":
        import Part
        normal = V(feat.Normal)
        if normal.Length < 1e-9:
            return None
        normal.normalize()
        direction = normal * (1 if feat.Reversed else -1)
        r = float(getattr(feat.Diameter, "Value", feat.Diameter)) / 2.0
        if r <= 0:
            return None
        if feat.EndCondition == "Up To Next":
            disk = Part.Face(Part.Wire(Part.makeCircle(r, V(feat.Point), direction)))
            return disk.extrude(direction * _up_to_next(disk, direction, asm or ac.assembly_of(feat.Document)))
        return Part.makeCylinder(r, _length(feat, asm), V(feat.Point), direction)
    if kind == "Sweep":
        return sweep_tool(feat.Profile, getattr(feat, "Path", None), getattr(feat, "Orientation", "") or "Follow Path",
                          twist_of(feat))
    if kind == "Wizard":
        return wizard_tool(feat, asm)
    sketch = feat.Profile
    if sketch is None:
        return None
    _extra(feat)
    face = profile_face(sketch, list(getattr(feat, "Contours", []) or []))
    if face is None or face.isNull():
        return None
    kind = getattr(feat, FEATURE_PROP)
    if kind == "Revolve":
        axis = _axis(sketch)
        if axis is None:
            return None
        ax = axis[1] * (-1 if feat.Reversed else 1)
        angle = _val(feat.Angle)
        if getattr(feat, "RevolveType", "") == "Mid-Plane":
            start = face.copy()
            start.rotate(axis[0], ax, -angle / 2.0)
            return start.revolve(axis[0], ax, angle)
        solid = face.revolve(axis[0], ax, angle)
        if feat.Direction2 and _val(feat.Angle2) > 0:
            solid = solid.fuse(face.revolve(axis[0], ax * -1, _val(feat.Angle2)))
        return solid
    normal = sketch.getGlobalPlacement().Rotation.multVec(V(0, 0, 1))
    direction = normal * (1 if feat.Reversed else -1)
    draft = _val(feat.DraftAngle) if feat.Draft else 0.0
    if feat.EndCondition == "Mid Plane":
        L = _val(feat.Depth)
        start = face.copy()
        start.translate(direction * (-L / 2.0))
        return _drafted(start, direction, L, draft, feat.DraftOutward)
    solid = _drafted(face, direction, cut_length(feat, asm, face, direction), draft, feat.DraftOutward)
    if feat.Direction2:
        L2 = 2.0 * _span(asm or ac.assembly_of(feat.Document)) + 1.0 if feat.End2 == "Through All" else _val(feat.Depth2)
        if L2 > 0:
            solid = solid.fuse(face.extrude(direction * -L2))
    return solid


# ---------------------------------------------------------------- mates kept on their faces
def _local_shape(obj):
    try:
        target = obj.getLinkedObject(True) if obj.TypeId == "App::Link" else obj
        return target.Shape
    except Exception as _fw_err:
        _fw_log("asmfeature.py:487", _fw_err)
        return None


def _snap_refs(asm):
    """Each mate reference to a component's plain FaceN/EdgeN, with its geometry in the component's
    own frame: a cut renames the elements (FreeCAD) and the mates would move to other faces."""
    out = []
    for j in ac.mates(asm) + list(ac.parts(asm)):
        for prop in ("Reference1", "Reference2"):
            ref = getattr(j, prop, None)
            if not ref or ref[0] is None or not ref[1]:
                continue
            sub = ref[1][0]
            if "." in sub or not sub.startswith(("Face", "Edge")):
                continue
            sh = _local_shape(ref[0])
            try:
                el = sh.getElement(sub)
            except Exception as _fw_err:
                _fw_log("asmfeature.py:507", _fw_err)
                continue
            out.append((j, prop, ref[0], sub, ac.geometry(el), V(el.CenterOfMass)))
    return out


def _same(g, h):
    if g is None or h is None or g[0] != h[0]:
        return False
    if g[0] == "plane":
        return abs(g[2].dot(h[2])) > 1 - 1e-9 and g[2].dot(h[2]) > 0 and abs(g[2].dot(h[1] - g[1])) < 1e-6
    if g[0] in ("axis", "line"):
        d = V(g[2]).normalize()
        return abs(abs(d.dot(V(h[2]).normalize())) - 1) < 1e-9 and (h[1] - g[1]).cross(d).Length < 1e-6 \
            and (len(g) < 4 or abs(g[3] - h[3]) < 1e-6)
    return (V(g[1]) - V(h[1])).Length < 1e-6


def _restore_refs(asm, snap):
    """Puts each reference back on the face with its old geometry; True when one changed."""
    changed = False
    for j, prop, obj, sub, geo, com in snap:
        sh = _local_shape(obj)
        if sh is None:
            continue
        try:
            if ac.geometry(sh.getElement(sub)) is not None and _same(geo, ac.geometry(sh.getElement(sub))):
                continue
        except Exception as _fw_err:
            _fw_log("asmfeature.py:533", _fw_err)
        kind = sub.rstrip("0123456789")
        items = sh.Faces if kind == "Face" else sh.Edges
        best = None
        for i, el in enumerate(items):
            if _same(geo, ac.geometry(el)):
                d = (V(el.CenterOfMass) - com).Length
                if best is None or d < best[0]:
                    best = (d, "%s%d" % (kind, i + 1))
        if best is not None and best[1] != sub:
            try:
                setattr(j, prop, [obj, [best[1], best[1]]])
                changed = True
            except Exception as error:
                App.Console.PrintLog("FreeCAD: mate reference kept: %s\n" % error)
    return changed


def keeping_mates(asm, fn):
    """Runs fn (an assembly feature made or changed); the mates stay on their faces."""
    snap = _snap_refs(asm)
    keep = {c.Name: App.Placement(c.Placement) for c in ac.components(asm)}
    out = fn()
    try:
        asm.Document.recompute()
        _restore_refs(asm, snap)
        # a cut changes the faces' frames and FreeCAD's solve may slide a part along its mate:

        # does not move parts for an assembly feature)
        moved = [c for c in ac.components(asm) if c.Name in keep and not c.Placement.isSame(keep[c.Name], 1e-9)]
        if moved:
            for c in moved:
                c.Placement = keep[c.Name]
            if not ac.solve(asm):
                App.Console.PrintLog("FreeCAD: assembly feature: mates not solved where the parts were\n")
            for f in features(asm):         # cut again where the parts really are
                try:
                    update(f, True)
                except Exception as error:
                    App.Console.PrintLog("FreeCAD: %s: %s\n" % (f.Label, error))
            asm.Document.recompute()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: mates kept: %s\n" % error)
    return out


_DIMS = {}


def hole_dims(spec):
    """The Hole Wizard spec's sizes, as FreeCAD's PartDesign Hole works them out from its own
    fastener tables: {diameter, cut ("" / "cbore" / "csk"), cut_diameter, cut_depth, csk_angle,
    point_angle, depth, through}."""
    import json
    key = json.dumps(spec, sort_keys=True)
    if key in _DIMS:
        return _DIMS[key]
    from . import holespec
    active = App.ActiveDocument
    # one hidden scratch document, kept: making and closing one at each call while a PropertyManager
    # commits crashed FreeCAD 1.1 (bench, asm_series edit)
    doc = App.listDocuments().get("SWAsmHoleScratch") or App.newDocument("SWAsmHoleScratch", "SWAsmHoleScratch", True, True)
    doc.UndoMode = 0        # pkg301: the scratch work takes no share of the Hole Series / Hole Wizard step
    try:
        body = doc.addObject("PartDesign::Body", "Body")
        body.newObject("PartDesign::AdditiveBox", "Box")     # Through All wants a solid to go through
        doc.recompute()
        hole = body.newObject("PartDesign::Hole", "Hole")
        holespec.apply(hole, spec)
        kind = spec.get("kind")
        out = {"diameter": float(hole.Diameter.Value),
               "cut": "cbore" if kind == "Counterbore" else "csk" if kind == "Countersink" else "",
               "cut_diameter": float(hole.HoleCutDiameter.Value), "cut_depth": float(hole.HoleCutDepth.Value),
               "csk_angle": float(getattr(hole.HoleCutCountersinkAngle, "Value", hole.HoleCutCountersinkAngle)),
               "point_angle": float(getattr(hole.DrillPointAngle, "Value", hole.DrillPointAngle))
               if hole.DrillPoint == "Angled" else 0.0,
               "depth": float(hole.Depth.Value), "through": spec.get("end") == "Through All"}
        for key in ("near", "under", "far"):        # extapps106: the Options' countersinks (diameter, angle)
            out[key] = (float(spec.get(key + "_dia") or 0.0), float(spec.get(key + "_angle") or 90.0)) \
                if spec.get(key) and float(spec.get(key + "_dia") or 0.0) > 0 else None
    finally:
        for o in list(doc.Objects):
            try:
                if o.Name in [x.Name for x in doc.Objects]:
                    doc.removeObject(o.Name)
            except Exception as _fw_err:
                _fw_log("asmfeature.py:615", _fw_err)
        if active is not None and active.Name in App.listDocuments():
            App.setActiveDocument(active.Name)
            if App.GuiUp:
                try:
                    Gui.setActiveDocument(active.Name)
                except Exception as _fw_err:
                    _fw_log("asmfeature.py:622", _fw_err)
    _DIMS[key] = out
    return out


def _widening(big, small, angle, z0, up):
    """A cone that widens to radius big at z0 (up: the cavity goes down from there; else up), narrowing to
    small over the countersink's depth. It starts a little outside z0 so the cut leaves no sliver."""
    import math
    import Part
    half = math.radians(max(1.0, min(angle, 179.0)) / 2.0)
    h = (big - small) / math.tan(half)
    lip = 0.02
    e = lip * math.tan(half)
    if up:
        return Part.makeCone(big + e, small, h + lip, V(0, 0, z0 + lip), V(0, 0, -1))
    return Part.makeCone(big + e, small, h + lip, V(0, 0, z0 - lip), V(0, 0, 1))


def hole_solid(dims, length, exit_depth=None):
    """The hole's cavity, its top centre at the origin, going down -z. The Options' countersinks are in
    it: near side at the top, under head on the counterbore's floor, far side where the hole comes out
    (exit_depth: how far down that is)."""
    import math
    import Part
    r = dims["diameter"] / 2.0
    depth = length if dims["through"] else dims["depth"]
    solid = Part.makeCylinder(r, depth, V(0, 0, -depth))
    if not dims["through"] and dims["point_angle"] > 0:
        tip = r / math.tan(math.radians(dims["point_angle"] / 2.0))
        solid = solid.fuse(Part.makeCone(r, 0, tip, V(0, 0, -depth), V(0, 0, -1)))
    rc = dims["cut_diameter"] / 2.0
    rim = r
    if dims["cut"] == "cbore" and rc > r and dims["cut_depth"] > 0:
        solid = solid.fuse(Part.makeCylinder(rc, dims["cut_depth"], V(0, 0, -dims["cut_depth"])))
        rim = rc
    elif dims["cut"] == "csk" and rc > r and dims["csk_angle"] > 0:
        h = (rc - r) / math.tan(math.radians(dims["csk_angle"] / 2.0))
        solid = solid.fuse(Part.makeCone(rc, r, h, V(0, 0, 0), V(0, 0, -1)))
        rim = rc
    near, under, far = dims.get("near"), dims.get("under"), dims.get("far")
    if near and near[0] / 2.0 > rim:
        solid = solid.fuse(_widening(near[0] / 2.0, rim, near[1], 0.0, True))
    if under and dims["cut"] == "cbore" and dims["cut_depth"] > 0 and under[0] / 2.0 > r:
        solid = solid.fuse(_widening(under[0] / 2.0, r, under[1], -dims["cut_depth"], True))
    if far and exit_depth is not None and far[0] / 2.0 > r:
        solid = solid.fuse(_widening(far[0] / 2.0, r, far[1], -exit_depth, False))
    return solid.removeSplitter()


def _intervals(asm, p, down):
    """Where the line from p along down is inside the components: [(from, to)] distances, nearest first."""
    import Part
    line = Part.LineSegment(p, p + down * (2.0 * _span(asm) + 1.0)).toShape()
    out = []
    for comp in ac.components(asm):
        if comp.TypeId != "App::Link" or _fastener(comp):
            continue
        try:
            common = line.common(global_shape(comp))
        except Exception:
            continue
        for e in common.Edges:
            ds = sorted((v.Point - p).dot(down) for v in e.Vertexes)
            if len(ds) >= 2 and ds[-1] - ds[0] > 1e-6:
                out.append((ds[0], ds[-1]))
    return sorted(out)


def _end_target(asm, spec):
    """The picked vertex point or face of an Up To Vertex / Up To Surface / Offset From Surface end."""
    ref = spec.get("end_ref") or ""
    if not ref or not spec.get("end_target"):       # (the Type tab empties end_target when the end changes)
        return None
    if spec.get("end") == "Up To Vertex":
        name, _bar, xyz = ref.partition("|")
        comp = next((c for c in ac.components(asm) if c.Name == name), None)
        try:
            return comp.Placement.multVec(V(*(float(v) for v in xyz.split(",")))) if comp is not None else None
        except ValueError:
            return None
    faces = _faces_at(asm, [ref])
    return faces[0] if faces else None


def end_depth(asm, spec, p, down):
    """How deep the hole goes from p, for an end condition worked out from the parts, or None (a plain
    Blind or Through All). Up To Next stops where the hole first comes out of its part."""
    end = spec.get("end")
    if end == "Up To Next":
        for a, b in _intervals(asm, p, down):
            if a <= 0.05 and b > 0.05:
                return b
        return None
    target = _end_target(asm, spec) if end in ("Up To Vertex", "Up To Surface", "Offset From Surface") else None
    if target is None:
        return None
    if end == "Up To Vertex":
        depth = (target - p).dot(down)
    else:
        import Part
        depth = None
        try:
            hit = Part.LineSegment(p - down * 1e4, p + down * 1e4).toShape().common(target)
            if hit.Vertexes:
                depth = (hit.Vertexes[0].Point - p).dot(down)
        except Exception:
            depth = None
        if depth is None and target.Surface.TypeId == "Part::GeomPlane":
            u, v = target.Surface.parameter(p)
            q, n = target.Surface.value(u, v), target.normalAt(u, v)
            if abs(down.dot(n)) > 1e-9:
                depth = (q - p).dot(n) / down.dot(n)
        if depth is None:
            return None
        if end == "Offset From Surface":
            off = float(spec.get("end_offset") or 0.0)
            depth = depth + off if spec.get("end_reverse") else depth - off
    return max(depth, 0.1)


def wizard_tool(feat, asm=None):
    import json
    try:
        spec = json.loads(feat.Spec or "{}")
    except ValueError:
        return None
    points = list(getattr(feat, "Points", None) or [])
    normal = V(feat.Normal)
    if not spec or not points or normal.Length < 1e-9:
        return None
    normal.normalize()
    normals = [V(*n) for n in (spec.get("normals") or [])]      # extapps106: each hole its own way (round faces)
    if len(normals) != len(points):
        normals = [normal] * len(points)
    asm = asm or ac.assembly_of(feat.Document)
    dims = hole_dims(spec)
    length = 2.0 * _span(asm) + 1.0
    out = None
    base = {}
    for p, normal in zip(points, normals):
        normal = V(normal)
        normal.normalize()
        if feat.Reversed:
            normal = normal * -1
        rot = App.Rotation(V(0, 0, 1), normal)
        down = normal * -1
        p = V(p)
        depth = end_depth(asm, spec, p, down) if spec.get("end") in ("Up To Next", "Up To Vertex", "Up To Surface", "Offset From Surface") else None
        exit_depth = None
        d = dims
        if depth is not None:       # a depth worked out from the parts: as a hole of that depth
            d = dict(dims, through=True)
            if spec.get("end") == "Up To Next":
                exit_depth = depth
        elif dims["through"] and dims.get("far"):
            ends = [b for _a, b in _intervals(asm, p, down)]
            exit_depth = max(ends) if ends else None
        key = (depth, exit_depth)
        if key not in base:
            base[key] = hole_solid(d, depth if depth is not None else length, exit_depth)
        one = base[key].copy()
        one.Placement = App.Placement(p, rot)
        out = one if out is None else out.fuse(one)
    return out


def _faces_at(asm, items):
    """[global face] for "component|x,y,z" items (a point on the face in the component's frame)."""
    import Part
    comps = {c.Name: c for c in ac.components(asm)}
    out = []
    for item in items or []:
        name, _bar, xyz = item.partition("|")
        comp = comps.get(name)
        try:
            p = V(*(float(v) for v in xyz.split(",")))
        except ValueError:
            continue
        if comp is None:
            continue
        shape = global_shape(comp)
        g = comp.Placement.multVec(p)
        v = Part.Vertex(g)
        best = min(shape.Faces, key=lambda f: f.distToShape(v)[0], default=None)
        if best is not None and best.distToShape(v)[0] < 1e-5:
            out.append(best)
    return out


def weld_path(feat, asm):
    """The edges where the Weld From faces meet the Weld To faces."""
    edges = []
    for a in _faces_at(asm, feat.WeldFrom):
        for b in _faces_at(asm, feat.WeldTo):
            try:
                sec = a.section(b)
            except Exception as _fw_err:
                _fw_log("asmfeature.py:704", _fw_err)
                continue
            edges += [e for e in sec.Edges if e.Length > 1e-6]
    return edges


def bead_shape(edges, size):
    ""
    import Part
    out = None
    for e in edges:
        u = e.FirstParameter
        t = e.tangentAt(u)
        circle = Part.Wire(Part.makeCircle(size / 2.0, e.valueAt(u), t))
        try:
            pipe = Part.Wire([e]).makePipeShell([circle], True, False)
        except Exception:
            continue
        out = pipe if out is None else out.fuse(pipe)
    return out


def _bead_for(feat):
    bead = getattr(feat, "Bead", None)
    if bead is not None:
        return bead
    doc = feat.Document
    bead = doc.addObject("Part::FeaturePython", "WeldBead")
    CutBody(bead)
    if App.GuiUp and bead.ViewObject is not None:
        ViewProviderCutBody(bead.ViewObject)
    bead.addProperty("App::PropertyString", BEAD_PROP, "FreeCAD", "The weld bead of an assembly Weld Bead")
    setattr(bead, BEAD_PROP, feat.Name)
    bead.Label = feat.Label + " bead"
    if App.GuiUp and bead.ViewObject is not None:
        try:
            bead.ViewObject.ShowInTree = False
            bead.ViewObject.ShapeAppearance = [App.Material(DiffuseColor=(0.55, 0.45, 0.35))]
        except Exception as _fw_err:
            _fw_log("asmfeature.py:739", _fw_err)
    feat.Bead = bead
    return bead


def update_weld(feat, asm, structure=False):
    bead = getattr(feat, "Bead", None)
    if bead is None:
        if not structure:
            return
        bead = _bead_for(feat)
    edges = weld_path(feat, asm)
    shape = bead_shape(edges, float(getattr(feat.Radius, "Value", feat.Radius))) if edges else None
    import Part
    bead.Shape = shape if shape is not None else Part.Shape()
    try:
        bead.purgeTouched()
    except Exception as _fw_err:
        _fw_log("asmfeature.py:757", _fw_err)


def _face_ref(asm, item):
    """(component, "FaceN", global face) for a "component|x,y,z" item, or None."""
    import Part
    name, _bar, xyz = item.partition("|")
    comp = next((c for c in ac.components(asm) if c.Name == name), None)
    try:
        p = V(*(float(v) for v in xyz.split(",")))
    except ValueError:
        return None
    if comp is None:
        return None
    shape = global_shape(comp)
    v = Part.Vertex(comp.Placement.multVec(p))
    for i, f in enumerate(shape.Faces):
        if f.distToShape(v)[0] < 1e-5:
            return comp, "Face%d" % (i + 1), f
    return None


def pulleys(asm, items):
    """[(component, "FaceN", centre, axis, radius, face)] for the round faces picked."""
    out = []
    for item in items or []:
        ref = _face_ref(asm, item)
        if ref is None:
            continue
        g = ac.geometry(ref[2])
        if g is None or g[0] != "axis" or len(g) < 4 or g[3] <= 0:
            continue
        axis = V(g[2]).normalize()
        centre = V(g[1]) + axis * (ref[2].CenterOfMass - V(g[1])).dot(axis)    # mid height
        out.append((ref[0], ref[1], centre, axis, g[3], ref[2]))
    return out


def flips_of(items, flipped):
    """[True for each member the belt goes round on the inside] (Flip belt side)."""
    flipped = set(flipped or [])
    return [i in flipped for i in items or []]


def belt_wire(members, offset=0.0, flips=None):
    ""

    import math
    import Part
    if len(members) < 2:
        return None
    c0, n = members[0][2], members[0][3]
    flips = list(flips or [])
    circles = []
    for k, m in enumerate(members):
        c = m[2] - n * (m[2] - c0).dot(n)       # into the first pulley's plane
        r = m[4] + offset
        circles.append((c, -r if k < len(flips) and flips[k] else r))     # inside: a signed radius
    area = V()
    for i in range(len(circles)):
        area += circles[i][0].cross(circles[(i + 1) % len(circles)][0])
    if len(circles) > 2 and area.dot(n) < 0:
        circles.reverse()                       # the belt goes round anticlockwise
    tangents = []
    for i in range(len(circles)):
        (c1, r1), (c2, r2) = circles[i], circles[(i + 1) % len(circles)]
        d = c2 - c1
        L = d.Length
        if L <= abs(r1 - r2) + 1e-9 or (r1 * r2 < 0 and L <= abs(r1) + abs(r2) + 1e-9):
            return None
        d = d * (1.0 / L)
        a = (r1 - r2) / L
        m = d * a + d.cross(n) * math.sqrt(max(0.0, 1 - a * a))
        tangents.append((c1 + m * r1, c2 + m * r2))
    edges = []
    for i, (c, r) in enumerate(circles):
        arrive, leave = tangents[i - 1][1], tangents[i][0]
        circle = Part.Circle(c, n if r > 0 else n * -1, abs(r))     # inside: round the other way
        a1, a2 = circle.parameter(arrive), circle.parameter(leave)
        while a2 <= a1 + 1e-9:
            a2 += 2 * math.pi
        if a2 - a1 > 1e-7:
            edges.append(Part.Edge(circle, a1, a2))
        if (tangents[i][1] - leave).Length > 1e-7:
            edges.append(Part.LineSegment(leave, tangents[i][1]).toShape())
    try:
        return Part.Wire(Part.__sortEdges__(edges))
    except Exception:
        return Part.Wire(edges)


def belt_solid(wire, members, thickness):
    """Create belt part: the belt as a solid, thickness by the first pulley's face width."""
    import Part
    face = members[0][5]
    n = members[0][3]
    heights = [v.Point.dot(n) for v in face.Vertexes] or [0.0]
    width = max(heights) - min(heights) if len(heights) > 1 else 5.0
    width = width if width > 1e-6 else 5.0
    e = wire.OrderedEdges[0]
    u = e.FirstParameter
    p, t = e.valueAt(u), e.tangentAt(u)
    out = t.cross(n).normalize()               # away from the pulley (the belt goes anticlockwise)
    if (p - members[0][2]).dot(out) < 0:
        out = out * -1
    mid = members[0][2] + n * ((max(heights) + min(heights)) / 2.0 - members[0][2].dot(n))
    p = p + n * (mid - p).dot(n)
    th = max(thickness, 0.1)
    corners = [p, p + out * th, p + out * th + n * width, p + n * width]
    corners = [q - n * (width / 2.0) for q in corners]
    section = Part.makePolygon(corners + [corners[0]])
    w = Part.Wire(Part.__sortEdges__([edge.translated(n * 0) for edge in wire.Edges]))
    return w.makePipeShell([section], True, False)


def drive_length(asm, items, flips, offset, target):
    ""

    import FreeCAD as App
    fixed = set(ac.grounded(asm))
    members = pulleys(asm, items)
    k = next((i for i in range(len(members) - 1, 0, -1) if members[i][0] not in fixed), None)
    if k is None or target <= 0:
        return False
    comp = members[k][0]
    start = App.Placement(comp.Placement)
    d = members[k][2] - members[k - 1][2]
    if d.Length < 1e-9:
        return False
    d = d * (1.0 / d.Length)

    def length_at(t):
        comp.Placement = App.Placement(start.Base + d * t, start.Rotation)
        w = belt_wire(pulleys(asm, items), offset, flips)
        return w.Length if w is not None else None

    lo, hi = -0.0, 0.0
    now = length_at(0.0)
    if now is None:
        comp.Placement = start
        return False
    step = max(1.0, abs(target - now))
    if target > now:
        hi = step
        while (length_at(hi) or 0.0) < target and hi < 1e6:
            hi *= 2.0
    else:
        lo = -step
        while True:
            v = length_at(lo)
            if v is None or v <= target or lo < -1e6:
                break
            lo *= 2.0
        if length_at(lo) is None:           # the pulleys would overlap first: as close as they go
            a, b = lo, 0.0
            for _i in range(50):
                m = (a + b) / 2.0
                a, b = (m, b) if length_at(m) is None else (a, m)
            lo = b
    for _i in range(60):
        m = (lo + hi) / 2.0
        v = length_at(m)
        if v is None or v < target:
            lo = m
        else:
            hi = m
    got = length_at(hi)
    if got is None or abs(got - target) > 1e-3:
        comp.Placement = start
        return False
    return True


def _feat_flips(feat, asm):
    return flips_of([i for i in feat.Members if _face_ref(asm, i) is not None], getattr(feat, "FlipSides", []))


def belt_length(feat, asm):
    members = pulleys(asm, feat.Members)
    off = float(getattr(feat.Thickness, "Value", feat.Thickness)) / 2.0 if feat.UseThickness else 0.0
    w = belt_wire(members, off, _feat_flips(feat, asm))
    return w.Length if w is not None else 0.0


def update_belt(feat, asm, structure=False):
    import Part
    shown = getattr(feat, "Bead", None)
    if shown is None:
        if not structure:
            return
        shown = _bead_for(feat)
        if App.GuiUp and shown.ViewObject is not None:
            try:
                shown.ViewObject.LineWidth = 2.0
                shown.ViewObject.LineColor = (0.2, 0.4, 0.9)
                shown.ViewObject.ShapeAppearance = [App.Material(DiffuseColor=(0.15, 0.15, 0.15))]
            except Exception as _fw_err:
                _fw_log("asmfeature.py:884", _fw_err)
    members = pulleys(asm, feat.Members)
    th = float(getattr(feat.Thickness, "Value", feat.Thickness))
    flips = _feat_flips(feat, asm)
    wire = belt_wire(members, th / 2.0 if feat.UseThickness else 0.0, flips)
    shape = Part.Shape()
    if wire is not None:
        shape = wire
        if feat.BeltPart:
            try:
                inner = belt_wire(members, 0.0, flips)
                shape = belt_solid(inner, members, th if feat.UseThickness else 1.0)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: belt part: %s\n" % error)
    shown.Shape = shape
    try:
        shown.purgeTouched()
    except Exception as _fw_err:
        _fw_log("asmfeature.py:901", _fw_err)


def belt_mates(feat):
    asm = ac.assembly_of(feat.Document)
    if asm is None:
        return []
    return [j for j in ac.joint_group(asm).Group if getattr(j, BELT_PROP, "") == feat.Name]


def engage(feat):
    """Engage belt: each pulley turns with the next, as a belt makes them (FreeCAD's Belt joint,
    the ratio from the diameters). Remade on each OK."""
    asm = ac.assembly_of(feat.Document)
    doc = feat.Document
    for j in belt_mates(feat):
        doc.removeObject(j.Name)
    if asm is None or not feat.Engage:
        return []
    members = pulleys(asm, feat.Members)
    flips = _feat_flips(feat, asm)
    out = []
    for k, (a, b) in enumerate(zip(members, members[1:])):
        if a[0] is b[0]:
            continue
        same = (flips[k] if k < len(flips) else False) == (flips[k + 1] if k + 1 < len(flips) else False)
        # a pulley the belt goes round on the inside turns the other way (Flip belt side)
        j = ac.add_mate(asm, "Gear", (a[0], a[1]), (b[0], b[1]), value=(2 * a[4], 2 * b[4], same),
                        name="BeltMate%d" % (len(out) + 1) if len(out) else _belt_name(asm, feat))
        j.addProperty("App::PropertyString", BELT_PROP, "FreeCAD", "Made by this Belt/Chain")
        setattr(j, BELT_PROP, feat.Name)
        out.append(j)
    return out


def _belt_name(asm, feat):
    return "BeltMate" + feat.Label[len("Belt"):] if feat.Label.startswith("Belt") else "BeltMate1"


def _series_json(feat, name):
    import json
    try:
        return json.loads(getattr(feat, name, "") or "{}")
    except ValueError:
        return {}


def series_parts(feat):
    ""

    middle = dict({"auto": True}, **_series_json(feat, "SeriesMiddle"))
    last = _series_json(feat, "SeriesLast")
    if not last:
        last = {"kind": "Straight Tap" if getattr(feat, "Tapped", False) else "Hole", "auto": True, "end": "Through All"}
    last.setdefault("auto", True)
    last.setdefault("end", "Through All")
    return middle, last


def series_tools(feat, asm):
    ""



    import json
    import Part
    try:
        spec = json.loads(feat.Spec or "{}")
    except ValueError:
        return []
    points = list(getattr(feat, "Points", None) or [])
    normal = V(feat.Normal)
    if not spec or not points or normal.Length < 1e-9:
        return []
    normal.normalize()
    down = normal * -1
    span = 2.0 * _span(asm) + 1.0
    first = hole_dims(dict(spec, end="Through All"))
    head = hole_solid(first, span)
    middle, last = series_parts(feat)
    mid_d = first["diameter"]
    if not middle.get("auto"):
        try:
            mid_d = hole_dims(dict(spec, **dict(middle, kind="Hole", end="Through All")))["diameter"]
        except Exception as _fw_err:
            _fw_log("asmfeature.py:983", _fw_err)
    last_d = first["diameter"]          # auto: sized from the start part, as the middle ones
    try:
        if last.get("kind") == "Straight Tap":
            tap = dict(spec, kind="Straight Tap", type="Tapped hole") if last.get("auto") else dict(spec, **last)
            last_d = hole_dims(dict(tap, kind="Straight Tap", end="Through All"))["diameter"]
        elif not last.get("auto"):
            last_d = hole_dims(dict(spec, **dict(last, kind="Hole", end="Through All")))["diameter"]
    except Exception as _fw_err:
        _fw_log("asmfeature.py:992", _fw_err)
    blind = last.get("end") == "Blind"
    depth = float(last.get("depth", 10.0) or 10.0)
    rot = App.Rotation(V(0, 0, 1), normal)
    comps = [c for c in ac.components(asm) if c.TypeId == "App::Link" and not _fastener(c)]
    kept = set(getattr(feat, "Scope", []) or [])
    if kept:
        comps = [c for c in comps if c.Name in kept]
    out = []
    for p in points:
        line = Part.LineSegment(V(p) + normal * 1e-3, V(p) + down * span).toShape()
        hits = []
        for comp in comps:
            try:
                shape = _before_series(feat, comp)
                common = line.common(shape)
            except Exception as _fw_err:
                _fw_log("asmfeature.py:1013", _fw_err)
                continue
            if common.Edges:
                start = min((v.Point - V(p)).dot(down) for e in common.Edges for v in e.Vertexes)
                hits.append((start, comp))
        hits.sort(key=lambda h: h[0])
        for i, (start, comp) in enumerate(hits):
            at = App.Placement(V(p), rot)
            if i == 0:
                solid = head.copy()
            elif i == len(hits) - 1:
                if blind:
                    solid = Part.makeCylinder(last_d / 2.0, depth, V(0, 0, -depth))
                    at = App.Placement(V(p) + down * max(start, 0.0), rot)
                else:
                    solid = Part.makeCylinder(last_d / 2.0, span, V(0, 0, -span))
            else:
                solid = Part.makeCylinder(mid_d / 2.0, span, V(0, 0, -span))
            solid.Placement = at
            out.append((comp, solid))
    return out


def _fastener(comp):
    """A Toolbox fastener (a Smart Fastener in the series' own hole is never drilled)."""
    try:
        from . import toolbox
        return toolbox.is_fastener(comp)
    except Exception:
        return False


def _before_series(feat, comp):
    """The component's shape without this Hole Series' own piece in its part (the part carries it
    as a feature, so the hole would hide where the series goes through)."""
    try:
        body = own_part(comp) if comp.TypeId == "App::Link" else None
        cut = propagated(body.Document).get("%s#%s" % (feat.Document.Name, feat.Name)) if body is not None else None
        base = getattr(cut, "BaseFeature", None) if cut is not None else None
        if base is not None and not base.Shape.isNull():
            shape = base.Shape.copy()
            shape.Placement = _gplacement(comp).multiply(shape.Placement)
            return shape
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Hole Series: %s\n" % error)
    return global_shape(comp)


def series_components(feat, asm):
    """The components the series goes through, first to last, once each."""
    out = []
    for comp, _solid in series_tools(feat, asm):
        if comp not in out:
            out.append(comp)
    return out


def twist_of(feat):
    """(kind, radians or vector) of a Swept Cut's Profile Twist."""
    import math
    kind = getattr(feat, "Twist", "") or "None"
    if kind == "Specify Twist Value":
        v = float(getattr(feat, "TwistValue", 0.0) or 0.0)
        unit = getattr(feat, "TwistUnit", "") or "Degrees"
        return kind, math.radians(v) if unit == "Degrees" else v * 2 * math.pi if unit == "Turns" else v
    if kind == "Specify Direction Vector":
        return kind, V(getattr(feat, "TwistVector", V(0, 0, 1)))
    return "None", None


def _twisted(spine, outline, angle, steps=24):
    """The outline carried along the spine (turning with it) and turned about the path by angle
    (radians) in all, lofted through its copies: Profile Twist, Specify Twist Value."""
    import Part
    edges = spine.OrderedEdges
    length = spine.Length
    start = t0 = None
    sections = []
    for i in range(steps + 1):
        d = length * i / steps
        acc = 0.0
        for e in edges:
            if acc + e.Length >= d - 1e-9 or e is edges[-1]:
                u = e.getParameterByLength(min(max(d - acc, 0.0), e.Length))
                here, tan = e.valueAt(u), e.tangentAt(u)
                break
            acc += e.Length
        if t0 is None:
            t0, start = V(tan), V(here)
        turn = App.Rotation(V(tan), math_deg(angle * i / steps)).multiply(App.Rotation(t0, V(tan)))
        plc = App.Placement(here, turn).multiply(App.Placement(-start, App.Rotation()))
        sections.append(_moved(outline, plc))
    return Part.makeLoft(sections, True, False)


def _moved(wire, plc):
    w = wire.copy()
    w.transformShape(plc.toMatrix())
    return w


def math_deg(rad):
    import math
    return math.degrees(rad)


def sweep_tool(profile, path, orientation="Follow Path", twist=("None", None)):
    """The profile's closed outline swept along the path sketch, a solid in the assembly. Options'
    Orientation: Follow Path (the profile turns with the path) or Keep Normal Constant (it stays
    parallel to where it started). Profile Twist: Specify Twist Value turns the profile about the
    path by the value over its length; Specify Direction Vector keeps the profile's up along it."""
    import Part
    if profile is None or path is None:
        return None
    wires = [w for w in profile.Shape.Wires if w.isClosed()]
    edges = path.Shape.Edges
    if not wires or not edges:
        return None
    try:
        spine = Part.Wire(Part.__sortEdges__(edges))
        outline = max(wires, key=lambda w: w.Length)
        kind, value = twist or ("None", None)
        if kind == "Specify Twist Value" and value:
            pipe = _twisted(spine, outline, value)
            if pipe.ShapeType != "Solid" and pipe.Solids:
                pipe = pipe.Solids[0]
            return pipe if pipe.isValid() and abs(pipe.Volume) > 1e-9 else None
        if kind == "Specify Direction Vector" and value is not None and value.Length > 1e-9:
            mk = Part.BRepOffsetAPI.MakePipeShell(spine)
            mk.setBiNormalMode(value)
            mk.add(outline, False, False)
            mk.build()
            mk.makeSolid()
            pipe = mk.shape()
            if pipe.ShapeType != "Solid" and pipe.Solids:
                pipe = pipe.Solids[0]
            return pipe if pipe.isValid() and abs(pipe.Volume) > 1e-9 else None
        if orientation == "Keep Normal Constant":
            mk = Part.BRepOffsetAPI.MakePipeShell(spine)
            plane = Part.Face(outline)
            n = plane.normalAt(0, 0)
            mk.setTrihedronMode(outline.CenterOfMass, n)
            mk.add(outline, False, False)
            mk.build()
            mk.makeSolid()
            pipe = mk.shape()
            if pipe.ShapeType != "Solid" and pipe.Solids:
                pipe = pipe.Solids[0]
            return pipe if pipe.isValid() and abs(pipe.Volume) > 1e-9 else None
        pipe = spine.makePipeShell([outline], True, True)
        return pipe if pipe.isValid() and pipe.Volume > 1e-9 else None
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Swept Cut: %s\n" % error)
        return None


def _span(asm):
    box = None
    for comp in ac.components(asm):
        try:
            b = global_shape(comp).BoundBox
        except Exception:
            continue
        if box is None:
            box = b
        else:
            box.add(b)
    return box.DiagonalLength if box is not None else 1000.0


def reaches(solid, comp):
    try:
        shape = global_shape(comp)
        if not solid.BoundBox.intersect(shape.BoundBox):
            return False
        return solid.common(shape).Volume > 1e-9
    except Exception:
        return False


def edge_points(feat):
    """{component name: [points on its edges, in the component's own frame]}."""
    out = {}
    for item in getattr(feat, "Edges", None) or []:
        name, _bar, xyz = item.partition("|")
        try:
            x, y, z = (float(v) for v in xyz.split(","))
        except ValueError:
            continue
        out.setdefault(name, []).append(V(x, y, z))
    return out


def edges_at(shape, points, tol=1e-5):
    import Part
    out = []
    for p in points:
        v = Part.Vertex(p)
        best = min(shape.Edges, key=lambda e: e.distToShape(v)[0], default=None)
        if best is not None and best.distToShape(v)[0] < tol and not any(best.isSame(e) for e in out):
            out.append(best)
    return out


def vertex_corner(shape, point, distances, tol=1e-5):
    """Vertex chamfer: the corner at point cut off through the points that far along its edges
    (the first three edges at the vertex, in the shape's order). None when no such vertex."""
    import Part
    vert = min(shape.Vertexes, key=lambda v: (v.Point - point).Length, default=None)
    if vert is None or (vert.Point - point).Length > tol:
        return None
    p0 = vert.Point
    ends = []
    for e in shape.Edges:
        if len(ends) == 3:
            break
        if not any((v.Point - p0).Length < tol for v in e.Vertexes):
            continue
        d = distances[len(ends)]
        if d <= 0 or d >= e.Length:
            return None
        if (e.valueAt(e.FirstParameter) - p0).Length < tol:
            ends.append(e.valueAt(e.getParameterByLength(d)))
        else:
            ends.append(e.valueAt(e.getParameterByLength(e.Length - d)))
    if len(ends) != 3:
        return None
    a, b, c = ends
    faces = [Part.Face(Part.makePolygon([p0, a, b, p0])), Part.Face(Part.makePolygon([p0, b, c, p0])),
             Part.Face(Part.makePolygon([p0, c, a, p0])), Part.Face(Part.makePolygon([a, b, c, a]))]
    try:
        solid = Part.Solid(Part.Shell(faces))
        if solid.Volume < 0:
            solid.reverse()
        return solid
    except Exception as _fw_err:
        _fw_log("asmfeature.py:1249", _fw_err)
        return None


def scope_of(feat, asm, solid=None):
    comps = [c for c in ac.components(asm) if c.TypeId == "App::Link"]
    if getattr(feat, FEATURE_PROP) in EDGE_KINDS:
        names = set(edge_points(feat))
        if not getattr(feat, "AutoSelect", True):
            names &= set(getattr(feat, "Scope", []) or [])
        return [c for c in comps if c.Name in names]
    if feat.AutoSelect:
        solid = solid if solid is not None else tool(feat, asm)
        # a fastener put into the hole is not cut by it (the hole is what it sits in; extapps105)
        return [c for c in comps if solid is not None and not _fastener(c) and reaches(solid, c)]
    names = set(feat.Scope)
    return [c for c in comps if c.Name in names and not _fastener(c)]


# ---------------------------------------------------------------- applying
def _body_for(comp):
    target = comp.LinkedObject
    if is_body(target):
        return target
    doc = comp.Document
    body = doc.addObject("Part::FeaturePython", "AsmCutBody")
    CutBody(body)
    body.addProperty("App::PropertyXLink", BODY_PROP, "FreeCAD", "The part this cut body stands for")
    setattr(body, BODY_PROP, target)
    body.Label = ac.part_name(comp)
    if App.GuiUp and body.ViewObject is not None:
        ViewProviderCutBody(body.ViewObject)
        try:
            body.ViewObject.ShowInTree = False
        except Exception as _fw_err:
            _fw_log("asmfeature.py:1277", _fw_err)
        body.ViewObject.Visibility = False
    comp.LinkedObject = body
    return body


def _release(comp):
    target = comp.LinkedObject
    if not is_body(target):
        return
    own = getattr(target, BODY_PROP)
    asm = ac.assembly_of(comp.Document)
    plan = _plan(asm, comp, _local(target), _local(own)) if asm is not None else []
    names = {j.Name for j, _p, _v in plan}
    try:
        _hush()
    except Exception as _fw_err:
        _fw_log("asmfeature.py:1294", _fw_err)
    _QUIET.update(names)
    try:
        comp.LinkedObject = own
    finally:
        _QUIET.difference_update(names)
    _apply(plan)
    try:
        comp.Document.removeObject(target.Name)
    except Exception as _fw_err:
        _fw_log("asmfeature.py:1304", _fw_err)


def _same_surface(a, b, tol=1e-6):
    sa, sb = a.Surface, b.Surface
    if sa.TypeId != sb.TypeId:
        return False
    if sa.TypeId == "Part::GeomPlane":
        na, nb = a.normalAt(0, 0), b.normalAt(0, 0)
        return na.cross(nb).Length < tol and abs((b.CenterOfMass - a.CenterOfMass).dot(na)) < 1e-5
    if sa.TypeId == "Part::GeomCylinder":
        return abs(sa.Radius - sb.Radius) < tol and sa.Axis.cross(sb.Axis).Length < tol and \
            (sb.Center - sa.Center).cross(sa.Axis).Length < 1e-5
    return a.distToShape(b)[0] < 1e-6 and abs(a.Area - b.Area) < 1e-3 * max(a.Area, 1.0)


def match(old_shape, name, new_shape):
    """The name in new_shape of old_shape's element name (the same face, edge or vertex after a cut
    renumbered them), or None."""
    kind = name.rstrip("0123456789")
    try:
        old = old_shape.getElement(name)
    except Exception:
        return None
    if kind == "Face":
        best, area = None, 1e-9
        for i, f in enumerate(new_shape.Faces):
            if not _same_surface(old, f):
                continue
            common = 0.0
            try:
                common = old.common(f).Area
            except Exception as _fw_err:
                _fw_log("asmfeature.py:1337", _fw_err)
            if common > area:
                best, area = "Face%d" % (i + 1), common
        return best
    items = new_shape.Edges if kind == "Edge" else new_shape.Vertexes if kind == "Vertex" else []
    for i, e in enumerate(items):
        if kind == "Vertex" and (e.Point - old.Point).Length < 1e-6:
            return "Vertex%d" % (i + 1)
        if kind == "Edge" and e.Curve.TypeId == old.Curve.TypeId and abs(e.Length - old.Length) < 1e-6 and \
                (e.CenterOfMass - old.CenterOfMass).Length < 1e-6:
            return "Edge%d" % (i + 1)
    return None


def _plan(asm, comp, old_shape, new_shape):
    """[(joint, property, references)] that keep comp's mates on the same faces when its shape
    changes from old_shape to new_shape. Read before the shape changes, set after (FreeCAD's own
    renaming on a shape change must not run on top of ours)."""
    out = []
    for joint in ac.joint_group(asm).Group:
        for prop in ("Reference1", "Reference2"):
            ref = getattr(joint, prop, None)
            if not ref or ref[0] is None or ref[0].Name != comp.Name:
                continue
            subs = list(ref[1])
            new = []
            for sub in subs:
                head, _dot, elem = sub.rpartition(".")
                got = match(old_shape, elem, new_shape) if elem else None
                new.append((head + "." if head else "") + got if got else sub)
            out.append((joint, prop, (ref[0], new)))
    return out


_QUIET = set()


def _hush():
    """FreeCAD renames a mate's references when the shape under them changes (to "?Face5" when it
    loses track) and solves the mate at once, which posts a "Broken link" error before we name the
    face again. A mate named in _QUIET skips that solve; ours follows once its faces are named."""
    import JointObject
    cls = JointObject.Joint
    if getattr(cls, "_fw_hushed", False):
        return
    original = cls.onChanged

    def onChanged(self, joint, prop):
        if prop in ("Reference1", "Reference2") and getattr(joint, "Name", None) in _QUIET:
            return
        return original(self, joint, prop)
    cls.onChanged = onChanged
    cls._fw_hushed = True


def _set_shape(body, shape, plan):
    """body gets shape; the mates in plan are named again without FreeCAD solving them half way."""
    try:
        _hush()
    except Exception as _fw_err:
        _fw_log("asmfeature.py:1397", _fw_err)
    names = {j.Name for j, _p, _v in plan}
    _QUIET.update(names)
    try:
        body.Shape = shape
    finally:
        _QUIET.difference_update(names)
    _apply(plan)


def _apply(plan):
    for joint, prop, value in plan:
        if list(getattr(joint, prop)[1]) != value[1]:
            setattr(joint, prop, value)


def update(feat, structure=False):
    """Every cut component of the assembly shows its part less the cuts that reach it. structure
    (never while recomputing): also makes the cut bodies a newly cut component needs and gives an
    uncut one its own part back."""
    asm = ac.assembly_of(feat.Document)
    if asm is None:
        return
    cuts = {}       # component name -> [("cut", tool in the assembly) or (kind, size, local points)]
    welds = []      # weld beads go on after the cuts, on the faces the cuts leave
    for f in features(asm):
        kind = getattr(f, FEATURE_PROP)
        if is_suppressed(f):

            bead = getattr(f, "Bead", None)
            if bead is not None and not bead.Shape.isNull():
                import Part
                bead.Shape = Part.Shape()
            continue
        if kind in EDGE_KINDS:
            _extra(f)
            size = float(getattr(f.Radius, "Value", f.Radius))
            other = size
            if kind == "Chamfer":
                import math
                if f.ChamferType == "Distance Distance":
                    other = _val(f.Distance2) or size
                else:
                    other = size * math.tan(math.radians(_val(f.ChamferAngle) or 45.0))
                if f.FlipChamfer:
                    size, other = other, size
            elif (getattr(f, "FilletType", "") or "") == "Variable Size":
                other = _val(f.Radius2) or size
            if kind == "Chamfer" and f.ChamferType == "Vertex":
                d1 = size
                ds = (d1, d1, d1) if f.EqualDistance else (d1, _val(f.Distance2) or d1, _val(f.Distance3) or d1)
                keep = None if getattr(f, "AutoSelect", True) else set(getattr(f, "Scope", []) or [])
                for name, pts in edge_points(f).items():
                    if keep is None or name in keep:
                        cuts.setdefault(name, []).append(("Vertex", d1, pts, ds))
                continue
            keep = None if getattr(f, "AutoSelect", True) else set(getattr(f, "Scope", []) or [])
            for name, pts in edge_points(f).items():
                if keep is not None and name not in keep:
                    continue        # Feature Scope: not one of the selected components
                cuts.setdefault(name, []).append((kind, size, pts, other))
            continue
        if kind in ("Weld", "Belt"):
            welds.append(f)
            continue
        if kind == "Series":

            # gets its own piece as a feature (Hole Series1->), as Propagate does
            pieces = {}
            for comp, solid in series_tools(f, asm):
                cuts.setdefault(comp.Name, []).append(("cut", solid))
                pieces.setdefault(comp.Name, (comp, []))[1].append(solid)
            for comp, solids in pieces.values():
                # one feature per part holds every position's piece (it held only the last one)
                propagate(f, comp, solids[0] if len(solids) == 1 else solids[0].fuse(solids[1:]))
            continue
        solid = tool(f, asm)
        if solid is None:
            continue
        for comp in scope_of(f, asm, solid):
            cuts.setdefault(comp.Name, []).append(("cut", solid))
            if getattr(f, "Propagate", False):
                propagate(f, comp, solid)
    _clear_stale_propagated(asm)
    for comp in [c for c in ac.components(asm) if c.TypeId == "App::Link"]:
        solids = cuts.get(comp.Name)
        if not solids:
            if structure:
                _release(comp)
            elif is_body(comp.LinkedObject):
                # nothing cuts it now (a cut suppressed while recomputing): its part's own shape
                body = comp.LinkedObject
                old = _local(body)
                whole = _local(source(body))
                if abs(old.Volume - whole.Volume) > 1e-9 or len(old.Faces) != len(whole.Faces):
                    _set_shape(body, whole, _plan(asm, comp, old, whole))
                    _redraw(body)
            continue
        if not structure and not is_body(comp.LinkedObject):
            continue
        old = _local(comp.LinkedObject)
        plan0 = _plan(asm, comp, old, old)      # the references as they stand
        body = _body_for(comp)
        _apply(plan0)
        shape = _local(source(body))
        inv = comp.Placement.inverse().toMatrix()
        for op in solids:
            if op[0] == "cut":
                shape = shape.cut(op[1].transformed(inv))
                continue
            if op[0] == "Vertex":
                for pt in op[2]:
                    corner = vertex_corner(shape, pt, op[3])
                    if corner is not None:
                        shape = shape.cut(corner)
                continue
            edges = edges_at(shape, op[2])
            if not edges or op[1] <= 0:
                continue
            try:
                if op[0] == "Fillet" and abs(op[3] - op[1]) > 1e-9:
                    shape = shape.makeFillet(op[1], op[3], edges)      # Variable Size: start to end
                elif op[0] == "Fillet":
                    shape = shape.makeFillet(op[1], edges)
                elif abs(op[3] - op[1]) < 1e-9:
                    shape = shape.makeChamfer(op[1], edges)
                else:
                    shape = shape.makeChamfer(op[1], op[3], edges)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: %s on %s: %s\n" % (op[0], comp.Label, error))
        plan = _plan(asm, comp, old, shape)
        _set_shape(body, shape, plan)
        _redraw(body)
        try:
            body.purgeTouched()
        except Exception as _fw_err:
            _fw_log("asmfeature.py:1533", _fw_err)
    for f in welds:
        if getattr(f, FEATURE_PROP) == "Belt":
            update_belt(f, asm, structure)
        else:
            update_weld(f, asm, structure)
    _FOLLOW[(asm.Document.Name, asm.Name)] = _stamp(asm)      # what follow() compares with


def _redraw(body):
    """A hidden object's picture is not rebuilt when its shape changes, and the component shows
    that picture: shown for a moment, it is rebuilt."""
    vo = getattr(body, "ViewObject", None) if App.GuiUp else None
    if vo is None:
        return
    try:
        vo.Visibility = True
        vo.Visibility = False
    except Exception as _fw_err:
        _fw_log("asmfeature.py:1552", _fw_err)


def _after_delete(doc_name):
    try:
        doc = App.getDocument(doc_name)
    except Exception:
        return
    asm = ac.assembly_of(doc)
    if asm is None:
        return
    rest = features(asm)
    live = {f.Name for f in rest}
    for o in list(doc.Objects):        # beads of deleted Weld Beads (belts, belt mates) go with them
        if getattr(o, BEAD_PROP, None) and getattr(o, BEAD_PROP) not in live:
            doc.removeObject(o.Name)
        elif getattr(o, BELT_PROP, None) and getattr(o, BELT_PROP) not in live:
            doc.removeObject(o.Name)
    if rest:
        update(rest[0], True)
    else:
        for comp in [c for c in ac.components(asm) if c.TypeId == "App::Link"]:
            _release(comp)
    doc.recompute()


def make(asm, kind, sketch, end="Blind", depth=10.0, angle=360.0, reversed_=False, auto=True, scope=(), extras=None):
    feat = asm.newObject("App::FeaturePython", "AsmCut")
    Feature(feat, kind)
    if App.GuiUp and feat.ViewObject is not None:
        ViewProviderFeature(feat.ViewObject)
        feat.ViewObject.Visibility = True
    feat.Label = _next_label(asm, KINDS[kind])
    _set(feat, sketch, end, depth, angle, reversed_, auto, scope)
    if extras:
        set_values(feat, extras)
    update(feat, True)
    asm.Document.recompute()
    return feat


def _set(feat, sketch, end, depth, angle, reversed_, auto, scope):
    feat.Profile = sketch
    feat.EndCondition = end
    feat.Depth = depth
    feat.Angle = angle
    feat.Reversed = bool(reversed_)
    feat.AutoSelect = bool(auto)
    feat.Scope = [c.Name for c in scope]
    if sketch is not None and App.GuiUp and sketch.ViewObject is not None:
        sketch.ViewObject.Visibility = False


def make_feature(asm, kind, values):
    """A Hole, Fillet or Chamfer: values = {property: value}."""
    feat = asm.newObject("App::FeaturePython", "AsmCut")
    Feature(feat, kind)
    if App.GuiUp and feat.ViewObject is not None:
        ViewProviderFeature(feat.ViewObject)
        feat.ViewObject.Visibility = True
    base = KINDS[kind]
    if kind == "Wizard" and values.get("Spec"):
        try:
            import json
            from . import holespec
            base = holespec.tree_name(json.loads(values.get("Spec") or "{}"))
        except Exception as _fw_err:
            _fw_log("asmfeature.py:1619", _fw_err)
    feat.Label = _next_label(asm, base)
    set_values(feat, values)
    update(feat, True)
    asm.Document.recompute()
    return feat


# ----------------------------------------------------------------------------- Propagate feature to parts
PROPAGATED_PROP = "FwPropagatedFrom"


def propagated(part_doc):
    """{assembly feature key: cut feature} in a part document."""
    out = {}
    for o in part_doc.Objects:
        key = getattr(o, PROPAGATED_PROP, "")
        if key:
            out[key] = o
    return out


class PropagatedCut:
    """A cut in the part's body that came from an assembly feature (Propagate feature to parts):
    the body so far, less the tool kept in the part's coordinates."""

    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty("Part::PropertyPartShape", "Tool", "Propagated", "The assembly feature's cut, in the part")
        obj.addProperty("App::PropertyString", PROPAGATED_PROP, "FreeCAD", "The assembly feature this cut comes from")
        obj.setEditorMode(PROPAGATED_PROP, 2)

    def execute(self, obj):
        base = obj.BaseFeature
        shape = base.Shape.copy() if base is not None and not base.Shape.isNull() else None
        if shape is None:
            return
        tool = obj.Tool
        if tool is not None and not tool.isNull():
            try:
                shape = shape.cut(tool)
                solids = shape.Solids
                if len(solids) == 1:
                    shape = solids[0]
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: propagated cut %s: %s\n" % (obj.Label, error))
        obj.Shape = shape
        try:
            obj.AddSubShape = tool
        except Exception as _fw_err:
            _fw_log("asmfeature.py:1669", _fw_err)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _clear_stale_propagated(asm):
    """A part's cut from an assembly feature that is gone (deleted, or no longer propagated): its
    tool is emptied, so the part is whole again (the feature row stays; nothing is deleted)."""
    import Part
    prefix = asm.Document.Name + "#"
    live = set()
    for f in features(asm):
        if is_suppressed(f):
            continue        # a suppressed Hole Series leaves the parts whole
        if getattr(f, FEATURE_PROP, "") == "Series" or getattr(f, "Propagate", False):
            live.add(prefix + f.Name)
    seen = set()
    for comp in ac.components(asm):
        try:
            body = own_part(comp) if comp.TypeId == "App::Link" else None
        except Exception:
            body = None
        if body is None or body.Document.Name in seen:
            continue
        seen.add(body.Document.Name)
        for key, cut in propagated(body.Document).items():
            if key.startswith(prefix) and key not in live:
                try:
                    if not cut.Tool.isNull():
                        cut.Tool = Part.Shape()
                        body.Document.recompute()
                except Exception as error:
                    App.Console.PrintLog("FreeCAD: propagated cut: %s\n" % error)


def propagate(feat, comp, solid):
    """Propagate feature to parts: the cut goes into the part's own body as a feature at the end
    (named after the assembly feature, marked -> as an external reference); it follows the
    assembly feature when that changes (the tool is put again on each update)."""
    body = own_part(comp) if comp.TypeId == "App::Link" else None
    if body is None or body.TypeId != "PartDesign::Body":
        return None
    doc = body.Document
    key = "%s#%s" % (feat.Document.Name, feat.Name)
    local = solid.transformed(comp.Placement.inverse().toMatrix())
    cut = propagated(doc).get(key)
    if cut is None:
        cut = body.newObject("PartDesign::FeaturePython", "PropagatedCut")
        PropagatedCut(cut)
        setattr(cut, PROPAGATED_PROP, key)
        cut.Tool = local
        cut.Label = "%s->" % feat.Label
        try:
            if App.GuiUp and cut.ViewObject is not None:
                cut.ViewObject.Proxy = 0
        except Exception as _fw_err:
            _fw_log("asmfeature.py:1729", _fw_err)
        doc.recompute()
        return cut
    try:
        old = cut.Tool
        if old.isNull() or abs(old.Volume - local.Volume) > 1e-9 or \
                (old.BoundBox.Center - local.BoundBox.Center).Length > 1e-9:
            cut.Tool = local
            doc.recompute()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: propagated cut: %s\n" % error)
    return cut


def _gplacement(comp):
    try:
        from .asmexplode import gplacement
        return gplacement(comp)
    except Exception:
        return comp.Placement


def set_values(feat, values):
    _extra(feat)
    for key, value in values.items():
        if key == "Scope":
            value = [c.Name for c in value]
        setattr(feat, key, value)


def _next_label(asm, base):
    taken = {o.Label for o in asm.Document.Objects}
    n = 1
    while "%s%d" % (base, n) in taken:
        n += 1
    return "%s%d" % (base, n)


# ---------------------------------------------------------------- PropertyManager
class CutPanel:
    def __init__(self, asm, kind, sketch=None, feat=None):
        from . import asmpm
        self.asm, self.kind, self.feat, self.doc = asm, kind, feat, asm.Document
        self.sketch = feat.Profile if feat is not None else sketch
        self.scope = []
        title = "Cut-Extrude" if kind == "Extrude" else "Cut-Revolve"
        icon = "FEATURES_EXTRUDE_CUT" if kind == "Extrude" else "FEATURES_REVOLVED_CUT"
        box, lay = asmpm._box("Direction 1" if kind == "Extrude" else "Revolve Parameters", title, icon)
        lay.addWidget(QtWidgets.QLabel("Sketch:"))
        self.sketch_box = QtWidgets.QLineEdit()
        self.sketch_box.setObjectName("FW_AsmCutSketch")
        self.sketch_box.setReadOnly(True)
        self.sketch_box.setStyleSheet(asmpm.PICK_STYLE.replace("QListWidget", "QLineEdit"))
        lay.addWidget(self.sketch_box)
        form = QtWidgets.QFormLayout()
        self.end = QtWidgets.QComboBox()
        self.end.setObjectName("FW_AsmCutEnd")
        self.end.addItems(list(END))
        self.depth = QtWidgets.QDoubleSpinBox()
        self.depth.setObjectName("FW_AsmCutDepth")
        self.depth.setRange(0.001, 1.0e6)
        self.depth.setDecimals(2)
        self.depth.setSuffix("mm")
        self.depth.setValue(10.0)
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setObjectName("FW_AsmCutAngle")
        self.angle.setRange(0.01, 360.0)
        self.angle.setDecimals(2)
        self.angle.setSuffix("deg")
        self.angle.setValue(360.0)
        def spin(name, lo, hi, val, suffix):
            w = QtWidgets.QDoubleSpinBox()
            w.setObjectName(name)
            w.setRange(lo, hi)
            w.setDecimals(2)
            w.setSuffix(suffix)
            w.setValue(val)
            return w

        self.up_to = QtWidgets.QLineEdit()
        self.up_to.setObjectName("FW_AsmCutUpTo")
        self.up_to.setReadOnly(True)
        self.up_to.setPlaceholderText("Pick a vertex or a face")
        self.up_point = self.up_normal = None
        self.offset = spin("FW_AsmCutOffset", 0.0, 1.0e6, 0.0, "mm")
        self.rev_offset = QtWidgets.QCheckBox("Reverse offset")
        self.rev_offset.setObjectName("FW_AsmCutReverseOffset")
        self.rtype = QtWidgets.QComboBox()
        self.rtype.setObjectName("FW_AsmCutRevolveType")
        self.rtype.addItems(list(REVOLVE_TYPES))
        self.axis_box = QtWidgets.QLineEdit()
        self.axis_box.setObjectName("FW_AsmCutAxis")
        self.axis_box.setReadOnly(True)
        if kind == "Extrude":
            form.addRow("End Condition:", self.end)
            form.addRow("Depth:", self.depth)
            form.addRow("Up to:", self.up_to)
            form.addRow("Offset:", self.offset)
            form.addRow("", self.rev_offset)
        else:
            form.addRow("Axis of Revolution:", self.axis_box)
            form.addRow("Revolve Type:", self.rtype)
            form.addRow("Angle:", self.angle)
        lay.addLayout(form)
        self.flip = QtWidgets.QCheckBox("Reverse Direction" if kind == "Revolve" else "Flip side to cut")
        from . import pmvalues
        self.flip.setIcon(pmvalues.reverse_icon())
        self.flip.setObjectName("FW_AsmCutFlip")
        lay.addWidget(self.flip)
        self.draft = QtWidgets.QCheckBox("Draft On/Off")
        self.draft.setObjectName("FW_AsmCutDraft")
        self.draft_angle = spin("FW_AsmCutDraftAngle", 0.0, 89.0, 1.0, "deg")
        self.draft_out = QtWidgets.QCheckBox("Draft outward")
        self.draft_out.setObjectName("FW_AsmCutDraftOutward")
        if kind == "Extrude":
            drow = QtWidgets.QHBoxLayout()
            drow.addWidget(self.draft)
            drow.addWidget(self.draft_angle)
            lay.addLayout(drow)
            lay.addWidget(self.draft_out)
        _takes_over(self.draft_angle, self.draft, True)      # live: using it turns Draft on
        _takes_over(self.draft_out, self.draft, True)
        d2, d2lay = asmpm._box("Direction 2")
        self._d2box = d2
        self.dir2 = QtWidgets.QCheckBox("Direction 2")
        self.dir2.setObjectName("FW_AsmCutDirection2")
        d2lay.addWidget(self.dir2)
        f2 = QtWidgets.QFormLayout()
        self.end2 = QtWidgets.QComboBox()
        self.end2.setObjectName("FW_AsmCutEnd2")
        self.end2.addItems(list(END2))
        self.depth2 = spin("FW_AsmCutDepth2", 0.001, 1.0e6, 10.0, "mm")
        self.angle2 = spin("FW_AsmCutAngle2", 0.01, 360.0, 360.0, "deg")
        if kind == "Extrude":
            f2.addRow("End Condition:", self.end2)
            f2.addRow("Depth:", self.depth2)
        else:
            f2.addRow("Angle:", self.angle2)
        d2lay.addLayout(f2)
        self.dir2.toggled.connect(self._dir2)
        self.end2.currentTextChanged.connect(lambda *_a: self._dir2(self.dir2.isChecked()))
        cbox, clay = asmpm._box("Selected Contours")
        self.contours = QtWidgets.QListWidget()
        self.contours.setObjectName("FW_AsmCutContours")
        self.contours.setStyleSheet(asmpm.PICK_STYLE)
        self.contours.setFixedHeight(asmpm._rows(self.contours, 3))
        clay.addWidget(self.contours)
        self.end.currentTextChanged.connect(self._end)
        self.rtype.currentTextChanged.connect(lambda t: self._mid(t == "Mid-Plane"))
        sbox, slay = asmpm._box("Feature Scope")
        self.auto = QtWidgets.QCheckBox("Auto-select")
        self.auto.setObjectName("FW_AsmCutAuto")
        self.auto.setChecked(True)
        slay.addWidget(self.auto)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_AsmCutScope")
        self.list.setStyleSheet(asmpm.PICK_STYLE)
        self.list.setFixedHeight(asmpm._rows(self.list, 3))
        slay.addWidget(self.list)
        self.propagate = QtWidgets.QCheckBox("Propagate feature to parts")
        self.propagate.setObjectName("FW_AsmCutPropagate")
        self.propagate.setToolTip("The cut is added to the parts' own files too, as a feature that follows this one")
        slay.addWidget(self.propagate)
        self.auto.toggled.connect(self._auto)
        self.error = QtWidgets.QLabel("")
        self.error.setObjectName("FW_AsmCutError")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #d04040;")
        self.error.hide()
        lay.addWidget(self.error)
        self.form = [box, d2, cbox, sbox]
        if feat is not None:
            _extra(feat)
            self.end.setCurrentText(feat.EndCondition)
            self.offset.setValue(_val(feat.Offset))
            self.rev_offset.setChecked(feat.ReverseOffset)
            if feat.EndCondition in UP_TO:
                self.up_point, self.up_normal = V(feat.UpToPoint), V(feat.UpToNormal)
                self.up_to.setText("(%.1f, %.1f, %.1f)" % tuple(self.up_point))
            self.dir2.setChecked(feat.Direction2)
            self.end2.setCurrentText(feat.End2 or "Blind")
            self.depth2.setValue(_val(feat.Depth2) or 10.0)
            self.angle2.setValue(_val(feat.Angle2) or 360.0)
            self.rtype.setCurrentText(feat.RevolveType or "Blind")
            self.draft.setChecked(feat.Draft)
            self.draft_angle.setValue(_val(feat.DraftAngle) or 1.0)
            self.draft_out.setChecked(feat.DraftOutward)
            self.depth.setValue(float(getattr(feat.Depth, "Value", feat.Depth)))
            self.angle.setValue(float(getattr(feat.Angle, "Value", feat.Angle)))
            self.flip.setChecked(feat.Reversed)
            self.auto.setChecked(feat.AutoSelect)
            self.propagate.setChecked(bool(getattr(feat, "Propagate", False)))
            for c in scope_of(feat, asm):
                self._add(c)
            self.doc.openTransaction("Edit " + feat.Label)
        self._auto(self.auto.isChecked())
        self._show_sketch(list(getattr(feat, "Contours", []) or []) if feat is not None else None)
        self._end(self.end.currentText())
        self._dir2(self.dir2.isChecked())
        if self.kind == "Revolve":
            self._mid(self.rtype.currentText() == "Mid-Plane")
        _takes_over(self.list, self.auto, False)        # picking scope turns Auto-select off
        Gui.Selection.addObserver(self, 0)

    def _mid(self, mid):
        ""
        self._no_dir2 = mid
        self._d2box.setVisible(not mid)
        self._dir2(self.dir2.isChecked())

    def _end(self, text):
        _row_visible(self.depth, text in ("Blind", "Mid Plane"))
        _row_visible(self.up_to, text in UP_TO)
        _row_visible(self.offset, text == "Offset From Surface")
        _row_visible(self.rev_offset, text == "Offset From Surface")
        if self.kind != "Revolve":
            self._mid(text == "Mid Plane")

    def _dir2(self, on):
        on = on and not getattr(self, "_no_dir2", False)
        _row_visible(self.end2, on)
        _row_visible(self.depth2, on and self.end2.currentText() == "Blind")
        _row_visible(self.angle2, on)

    def _show_sketch(self, chosen=None):
        self.sketch_box.setText(self.sketch.Label if self.sketch is not None else "")
        axis = _axis(self.sketch) if self.sketch is not None else None
        self.axis_box.setText("Centerline of %s" % self.sketch.Label if axis else "")
        self.contours.clear()
        for i in range(contour_count(self.sketch)):
            it = QtWidgets.QListWidgetItem("Contour %d" % (i + 1))
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            on = chosen is None or not chosen or i in chosen
            it.setCheckState(QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)
            self.contours.addItem(it)

    def chosen_contours(self):
        """[] = all (every contour ticked)."""
        on = [i for i in range(self.contours.count()) if self.contours.item(i).checkState() == QtCore.Qt.Checked]
        return [] if len(on) == self.contours.count() else on

    def set_up_to(self, point, normal=None):
        self.up_point, self.up_normal = V(point), V(normal) if normal is not None else V()
        self.up_to.setText("(%.1f, %.1f, %.1f)" % tuple(self.up_point))

    def extras(self):
        return {"UpToPoint": self.up_point or V(), "UpToNormal": self.up_normal or V(), "Offset": self.offset.value(),
                "ReverseOffset": self.rev_offset.isChecked(), "Direction2": self.dir2.isChecked() and not getattr(self, "_no_dir2", False),
                "End2": self.end2.currentText(), "Depth2": self.depth2.value(), "Angle2": self.angle2.value(),
                "RevolveType": self.rtype.currentText(), "Draft": self.draft.isChecked(),
                "DraftAngle": self.draft_angle.value(), "DraftOutward": self.draft_out.isChecked(),
                "Contours": self.chosen_contours(), "Propagate": self.propagate.isChecked()}

    def _auto(self, on):
        if on:
            self.list.clear()
            self.scope = []

    def _add(self, comp):
        if comp in self.scope:
            return
        self.scope.append(comp)
        self.list.addItem(comp.Label)

    def addSelection(self, doc, obj, sub, pnt):
        from . import safe_later as _sl; _sl.later(0, self._route, self, "auto")

    def removeSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass

    def setPreselection(self, *args):
        pass

    def _route(self):
        for sel in Gui.Selection.getSelectionEx("", 0):
            obj = sel.Object
            subs = sel.SubElementNames or [""]
            for sub in subs:
                target = obj.getSubObject(sub, 1) if sub else obj
                path = obj.getSubObjectList(sub) if sub else [obj]
                sketch = next((o for o in reversed(path) if o.isDerivedFrom("Sketcher::SketchObject")), None)
                if sketch is not None:
                    if sketch is not self.sketch:
                        self.sketch = sketch
                        self._show_sketch()
                    continue
                el = sub.split(".")[-1] if sub else ""
                if self.end.currentText() in UP_TO and (el.startswith("Vertex") or el.startswith("Face")):
                    try:
                        shp = obj.getSubObject(sub)
                        if el.startswith("Vertex"):
                            self.set_up_to(shp.Point)
                        else:
                            u0, u1, v0, v1 = shp.ParameterRange
                            self.set_up_to(shp.CenterOfMass, shp.normalAt((u0 + u1) / 2, (v0 + v1) / 2))
                    except Exception as _fw_err:
                        _fw_log("asmfeature.py:2019", _fw_err)
                    continue
                if not self.auto.isChecked():
                    ref = ac.reference(self.asm, obj, sub) if sub else None
                    comp = ref[0] if ref else (obj if obj in ac.components(self.asm) else None)
                    if comp is not None:
                        self._add(comp)

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmfeature.py:2031", _fw_err)

    def accept(self):
        if self.sketch is None or profile_face(self.sketch) is None:
            self.error.setText("Pick a sketch with a closed profile.")
            self.error.show()
            return False
        if self.kind == "Revolve" and _axis(self.sketch) is None:
            self.error.setText("The sketch needs a centerline to revolve about.")
            self.error.show()
            return False
        if not self.auto.isChecked() and not self.scope:
            self.error.setText("Pick the components to cut, or use Auto-select.")
            self.error.show()
            return False
        if self.kind == "Extrude" and self.end.currentText() in UP_TO and self.up_point is None:
            self.error.setText("Pick the vertex or face to cut up to.")
            self.error.show()
            return False
        if self.contours.count() and not any(self.contours.item(i).checkState() == QtCore.Qt.Checked
                                             for i in range(self.contours.count())):
            self.error.setText("Tick at least one contour.")
            self.error.show()
            return False
        self._close()
        args = (self.sketch, self.end.currentText(), self.depth.value(), self.angle.value(),
                self.flip.isChecked(), self.auto.isChecked(), list(self.scope))
        if self.feat is None:
            self.doc.openTransaction(KINDS[self.kind])
            self.feat = make(self.asm, self.kind, *args, extras=self.extras())
        else:
            _set(self.feat, *args)
            set_values(self.feat, self.extras())
            update(self.feat, True)
            self.feat.touch()
            self.doc.recompute()
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        _refresh()
        return True

    def reject(self):
        self._close()
        if self.feat is not None:
            self.doc.abortTransaction()
            self.doc.recompute()
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


class _FeaturePanel:
    """Shared by the Simple Hole and Fillet/Chamfer PMs: picks, OK/Cancel, edit transaction."""

    def _start(self, asm, kind, feat):
        self.asm, self.kind, self.feat, self.doc = asm, kind, feat, asm.Document
        if feat is not None:
            _extra(feat)
            self.doc.openTransaction("Edit " + feat.Label)

    def _error_label(self, lay):
        self.error = QtWidgets.QLabel("")
        self.error.setObjectName("FW_AsmFeatError")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #d04040;")
        self.error.hide()
        lay.addWidget(self.error)

    def _fail(self, text):
        self.error.setText(text)
        self.error.show()
        return False

    def addSelection(self, doc, obj, sub, pnt):
        point = V(*pnt) if pnt else None
        self.doc.Name      # its document closed: this raises here and selguard drops the observer
        QtCore.QTimer.singleShot(0, lambda: selguard.quiet(lambda: self._pick(self.doc.getObject(obj), sub, point)))

    def removeSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass

    def setPreselection(self, *args):
        pass

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmfeature.py:2124", _fw_err)

    def _commit(self, values):
        self._close()
        if self.feat is None:
            self.doc.openTransaction(KINDS[self.kind])
            self.feat = keeping_mates(self.asm, lambda: make_feature(self.asm, self.kind, values))
        else:
            set_values(self.feat, values)
            def _again():
                update(self.feat, True)
                self.feat.touch()
                self.doc.recompute()
            keeping_mates(self.asm, _again)
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        _refresh()
        return True

    def reject(self):
        self._close()
        if self.feat is not None:
            self.doc.abortTransaction()
            self.doc.recompute()
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


class HolePanel(_FeaturePanel):
    ""

    def __init__(self, asm, feat=None):
        from . import asmpm
        self._start(asm, "Hole", feat)
        self.point = V(feat.Point) if feat is not None else None
        self.normal = V(feat.Normal) if feat is not None else None
        box, lay = asmpm._box("Direction 1", "Hole", "FEATURES_HOLE_WIZARD")
        lay.addWidget(QtWidgets.QLabel("Placement face:"))
        self.face_box = QtWidgets.QLineEdit()
        self.face_box.setObjectName("FW_AsmHoleFace")
        self.face_box.setReadOnly(True)
        self.face_box.setStyleSheet(asmpm.PICK_STYLE.replace("QListWidget", "QLineEdit"))
        lay.addWidget(self.face_box)
        form = QtWidgets.QFormLayout()
        self.end = QtWidgets.QComboBox()
        self.end.setObjectName("FW_AsmHoleEnd")
        self.end.addItems(list(HOLE_END))
        self.depth = _spin("FW_AsmHoleDepth", 10.0)
        self.diameter = _spin("FW_AsmHoleDiameter", 10.0)
        form.addRow("End Condition:", self.end)
        form.addRow("Depth:", self.depth)
        form.addRow("Diameter:", self.diameter)
        lay.addLayout(form)
        self.flip = QtWidgets.QCheckBox("Reverse Direction")
        from . import pmvalues
        self.flip.setIcon(pmvalues.reverse_icon())
        self.flip.setObjectName("FW_AsmHoleFlip")
        lay.addWidget(self.flip)
        self.end.currentTextChanged.connect(lambda t: _row_visible(self.depth, t == "Blind"))
        sbox, slay = asmpm._box("Feature Scope")
        self.auto = QtWidgets.QCheckBox("Auto-select")
        self.auto.setObjectName("FW_AsmHoleAuto")
        self.auto.setChecked(True)
        slay.addWidget(self.auto)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_AsmHoleScope")
        self.list.setStyleSheet(asmpm.PICK_STYLE)
        self.list.setFixedHeight(asmpm._rows(self.list, 3))
        slay.addWidget(self.list)
        self.auto.toggled.connect(lambda on: on and self._clear_scope())
        _takes_over(self.list, self.auto, False)
        self.scope = []
        self._error_label(lay)
        self.form = [box, sbox]
        if feat is not None:
            self.end.setCurrentText(feat.EndCondition)
            self.depth.setValue(float(getattr(feat.Depth, "Value", feat.Depth)))
            self.diameter.setValue(float(getattr(feat.Diameter, "Value", feat.Diameter)))
            self.flip.setChecked(feat.Reversed)
            self.auto.setChecked(feat.AutoSelect)
            if not feat.AutoSelect:
                for c in scope_of(feat, asm):
                    self._add(c)
            self.face_box.setText("(%.2f, %.2f, %.2f)" % tuple(self.point))
        _row_visible(self.depth, self.end.currentText() == "Blind")
        Gui.Selection.addObserver(self, 0)

    def _clear_scope(self):
        self.list.clear()
        self.scope = []

    def _add(self, comp):
        if comp not in self.scope:
            self.scope.append(comp)
            self.list.addItem(comp.Label)

    def _pick(self, root, sub, point):
        if root is None or not sub:
            return
        ref = ac.reference(self.asm, root, sub)
        if ref is None:
            return
        shape = ac.element(*ref)
        if not self.auto.isChecked() and self.point is not None:
            self._add(ref[0])
            return
        if shape is None or shape.ShapeType != "Face" or shape.Surface.TypeId != "Part::GeomPlane":
            return
        p = point if point is not None else shape.CenterOfMass
        u, v = shape.Surface.parameter(p)
        self.point = shape.Surface.value(u, v)
        self.normal = shape.normalAt(u, v)
        self.face_box.setText("%s@%s" % (ref[1].split(".")[-1], ref[0].Label))
        self.error.hide()

    def accept(self):
        if self.point is None:
            return self._fail("Pick the flat face where the hole goes.")
        if not self.auto.isChecked() and not self.scope:
            return self._fail("Pick the components to cut, or use Auto-select.")
        return self._commit({"Point": self.point, "Normal": self.normal, "Diameter": self.diameter.value(),
                             "EndCondition": self.end.currentText(), "Depth": self.depth.value(),
                             "Reversed": self.flip.isChecked(), "AutoSelect": self.auto.isChecked(),
                             "Scope": list(self.scope)})


def _mid(e):
    return e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))


def shared_edges(f1, f2, tol=1e-6):
    """Edges of face f1 that lie on face f2 (where the two meet)."""
    out = []
    for e in f1.Edges:
        try:
            if f2.distToShape(Part_vertex(_mid(e)))[0] < tol:
                out.append(e)
        except Exception as _fw_err:
            _fw_log("asmfeature.py:2270", _fw_err)
            continue
    return out


def Part_vertex(p):
    import Part
    return Part.Vertex(p)


def face_fillet_edges(set1, set2):
    """Face Fillet: the edges where the faces of set 1 meet those of set 2 (same component)."""
    out = []
    for c1, f1 in set1:
        for c2, f2 in set2:
            if c1 is c2:
                out += [(c1, e) for e in shared_edges(f1, f2)]
    return out


def full_round(side1, center, side2):
    """Full Round Fillet: the edges of the center faces on the side faces and the radius that
    rounds the whole center face (half the distance between the sides)."""
    edges, widths = [], []
    for cc, fc in center:
        for sides in (side1, side2):
            for cs, fs in sides:
                if cs is cc:
                    edges += [(cc, e) for e in shared_edges(fc, fs)]
        for c1, f1 in side1:
            for c2, f2 in side2:
                if c1 is cc and c2 is cc:
                    try:
                        widths.append(f1.distToShape(f2)[0])
                    except Exception as _fw_err:
                        _fw_log("asmfeature.py:2298", _fw_err)
    r = min(widths) / 2.0 * 0.995 if widths else 0.0      # (exactly half leaves OpenCASCADE nothing to keep)
    return edges, r


class EdgePanel(_FeaturePanel):
    ""

    def __init__(self, asm, kind, feat=None):
        from . import asmpm
        self._start(asm, kind, feat)
        fillet = kind == "Fillet"
        box, lay = asmpm._box("Items To Fillet" if fillet else "Chamfer Parameters",
                              "Fillet" if fillet else "Chamfer", "FEATURES_FILLET" if fillet else "FEATURES_CHAMFER")
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_AsmEdgeList")
        self.list.setStyleSheet(asmpm.PICK_STYLE)
        self.list.setFixedHeight(asmpm._rows(self.list, 3))
        lay.addWidget(self.list)
        form = QtWidgets.QFormLayout()
        self.ctype = QtWidgets.QComboBox()
        self.ctype.setObjectName("FW_AsmChamferType")
        self.ctype.addItems(["Angle Distance", "Distance Distance", "Vertex"])
        self.size = _spin("FW_AsmEdgeSize", 2.0)
        self.cangle = QtWidgets.QDoubleSpinBox()
        self.cangle.setObjectName("FW_AsmChamferAngle")
        self.cangle.setRange(0.1, 89.9)
        self.cangle.setDecimals(2)
        self.cangle.setSuffix("deg")
        self.cangle.setValue(45.0)
        self.size2 = _spin("FW_AsmChamferDistance2", 2.0)
        self.flip_c = QtWidgets.QCheckBox("Flip direction")
        self.flip_c.setObjectName("FW_AsmChamferFlip")
        self.ftype = QtWidgets.QComboBox()
        self.ftype.setObjectName("FW_AsmFilletType")
        self.ftype.addItems(list(FILLET_TYPES))
        self.size_end = _spin("FW_AsmFilletRadius2", 4.0)
        self.face_sets = [[], [], []]       # Face Fillet: sets 1, 2; Full Round: side 1, center, side 2
        self.face_lists = []
        self.face_labels = []
        self.active_set = 0
        for i in range(3):
            lbl = QtWidgets.QLabel("")
            fl = QtWidgets.QListWidget()
            fl.setObjectName("FW_AsmFaceSet%d" % (i + 1))
            fl.setStyleSheet(asmpm.PICK_STYLE)
            fl.setFixedHeight(asmpm._rows(fl, 2))
            fl.itemSelectionChanged.connect(lambda i=i: self._activate(i))
            self.face_labels.append(lbl)
            self.face_lists.append(fl)
        if fillet:
            form.addRow("Fillet Type:", self.ftype)
            form.addRow("Radius:", self.size)
            form.addRow("End radius:", self.size_end)
            self.ftype.currentTextChanged.connect(self._ftype)
            for lbl, fl in zip(self.face_labels, self.face_lists):
                lay.addWidget(lbl)
                lay.addWidget(fl)
        else:
            form.addRow("Chamfer Type:", self.ctype)
            form.addRow("Distance:", self.size)
            form.addRow("Angle:", self.cangle)
            form.addRow("Distance 2:", self.size2)
            self.size3 = _spin("FW_AsmChamferDistance3", 2.0)
            form.addRow("Distance 3:", self.size3)
            self.equal = QtWidgets.QCheckBox("Equal distance")
            self.equal.setObjectName("FW_AsmChamferEqual")
            self.equal.toggled.connect(lambda *_a: self._ctype(self.ctype.currentText()))
            form.addRow("", self.equal)
            form.addRow("", self.flip_c)
            self.ctype.currentTextChanged.connect(self._ctype)
        lay.addLayout(form)
        self._error_label(lay)
        sbox, slay = asmpm._box("Feature Scope")
        self.auto = QtWidgets.QCheckBox("Auto-select")
        self.auto.setObjectName("FW_AsmEdgeAuto")
        self.auto.setChecked(getattr(feat, "AutoSelect", True) if feat is not None else True)
        slay.addWidget(self.auto)
        self.scope_list = QtWidgets.QListWidget()
        self.scope_list.setObjectName("FW_AsmEdgeScope")
        self.scope_list.setFixedHeight(asmpm._rows(self.scope_list, 3))
        slay.addWidget(self.scope_list)
        self.auto.toggled.connect(self._scope)
        self.form = [box, sbox]
        self.edges = []        # (component, local point, text)
        self.off = set()       # Feature Scope: components unchecked
        if feat is not None and fillet:
            _extra(feat)
            self.ftype.setCurrentText(feat.FilletType or "Constant Size")
            self.size_end.setValue(_val(feat.Radius2) or 4.0)
        if fillet:
            self._ftype(self.ftype.currentText())
        if feat is not None and not getattr(feat, "AutoSelect", True):
            keep = set(feat.Scope or [])
            self.off = {n for n in edge_points(feat) if n not in keep}
        if feat is not None and not fillet:
            _extra(feat)
            self.ctype.setCurrentText(feat.ChamferType or "Angle Distance")
            self.cangle.setValue(_val(feat.ChamferAngle) or 45.0)
            self.size2.setValue(_val(feat.Distance2) or 2.0)
            self.size3.setValue(_val(feat.Distance3) or 2.0)
            self.equal.setChecked(bool(feat.EqualDistance))
            self.flip_c.setChecked(feat.FlipChamfer)
        if not fillet:
            self._ctype(self.ctype.currentText())
        if feat is not None:
            self.size.setValue(float(getattr(feat.Radius, "Value", feat.Radius)))
            comps = {c.Name: c for c in ac.components(asm)}
            self._loading = True
            for name, pts in edge_points(feat).items():
                for p in pts:
                    if name in comps:
                        self._add(comps[name], p, "Edge@%s" % comps[name].Label)
            self._loading = False
        self._scope()
        Gui.Selection.addObserver(self, 0)

    def _ftype(self, text):
        _row_visible(self.size_end, text == "Variable Size")
        faces = text in FACE_FILLETS
        names = ("Face Set 1:", "Face Set 2:", "") if text == "Face Fillet" else \
            ("Side Face Set 1:", "Center Face Set:", "Side Face Set 2:")
        for i, (lbl, fl) in enumerate(zip(self.face_labels, self.face_lists)):
            on = faces and bool(names[i])
            lbl.setText(names[i])
            lbl.setVisible(on)
            fl.setVisible(on)
        self.list.setVisible(not faces)
        _row_visible(self.size, text != "Full Round Fillet")     # its radius comes from the center face
        self.active_set = 0

    def _activate(self, i):
        self.active_set = i

    def face_mode(self):
        return self.kind == "Fillet" and self.ftype.currentText() in FACE_FILLETS

    def _pick_face(self, comp, elem, shape):
        n = 2 if self.ftype.currentText() == "Face Fillet" else 3
        i = min(self.active_set, n - 1)
        name = elem.split(".")[-1]
        if any(c is comp and e == name for c, e, _s in self.face_sets[i]):
            return
        self.face_sets[i].append((comp, name, shape))
        self.face_lists[i].addItem("%s@%s" % (name, comp.Label))
        if i < n - 1 and len(self.face_sets[i]) == 1 and not self.face_sets[i + 1]:
            self.active_set = i + 1

    def face_edges(self):
        """The edges (and for Full Round the radius) the face sets give."""
        sets = [[(c, sh) for c, _n, sh in fs] for fs in self.face_sets]
        if self.ftype.currentText() == "Face Fillet":
            return face_fillet_edges(sets[0], sets[1]), self.size.value()
        return full_round(sets[0], sets[1], sets[2])

    def _scope(self, *_a):
        """Feature Scope: the components of the picked edges, each with a check (off with Auto-select)."""
        self.scope_list.clear()
        seen = []
        for c, _p, _t in self.edges:
            if c not in seen:
                seen.append(c)
        for c in seen:
            it = QtWidgets.QListWidgetItem(c.Label)
            it.setData(QtCore.Qt.UserRole, c.Name)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Unchecked if c.Name in self.off else QtCore.Qt.Checked)
            self.scope_list.addItem(it)
        if not hasattr(self.scope_list, "_fw_take_over"):
            _takes_over(self.scope_list, self.auto, False)

    def scope_names(self):
        out = []
        for i in range(self.scope_list.count()):
            it = self.scope_list.item(i)
            if it.checkState() == QtCore.Qt.Checked:
                out.append(it.data(QtCore.Qt.UserRole))
        return out

    def _add(self, comp, local, text):
        for c, p, _t in self.edges:
            if c is comp and (p - local).Length < 1e-6:
                return
        self.edges.append((comp, local, text))
        self.list.addItem(text)
        if hasattr(self, "scope_list") and not getattr(self, "_loading", False):
            self.off = {n for n in self.off if n != comp.Name} | set(
                self.scope_list.item(i).data(QtCore.Qt.UserRole) for i in range(self.scope_list.count())
                if self.scope_list.item(i).checkState() != QtCore.Qt.Checked)
            self._scope()

    def _pick(self, root, sub, point):
        if root is None or not sub:
            return
        ref = ac.reference(self.asm, root, sub)
        if ref is None:
            return
        comp, elem = ref
        shape = ac.element(comp, elem)
        if shape is None:
            return
        if self.face_mode():
            if shape.ShapeType == "Face":
                self._pick_face(comp, elem, shape)
                Gui.Selection.clearSelection()
                self.error.hide()
            return
        inv = comp.Placement.inverse()
        if self.kind == "Chamfer" and self.ctype.currentText() == "Vertex":
            if shape.ShapeType == "Vertex":
                self._add(comp, inv.multVec(shape.Point), "%s@%s" % (elem.split(".")[-1], comp.Label))
                Gui.Selection.clearSelection()
                self.error.hide()
            return
        if shape.ShapeType == "Edge":
            edges = [shape]
        elif shape.ShapeType == "Face":
            edges = list(shape.Edges)
        else:
            return
        for e in edges:
            mid = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
            self._add(comp, inv.multVec(mid), "%s@%s" % (elem.split(".")[-1], comp.Label))
        Gui.Selection.clearSelection()
        self.error.hide()

    def accept(self):
        radius = self.size.value()
        ftype = self.ftype.currentText() if self.kind == "Fillet" else ""
        if self.face_mode():
            found, radius = self.face_edges()
            if not found or radius <= 0:
                return self._fail("Pick faces that meet: Face Set 1 and Face Set 2." if ftype == "Face Fillet" else
                                  "Pick the side faces and the center face between them.")
            self.edges = []
            for comp, e in found:
                self._add(comp, comp.Placement.inverse().multVec(_mid(e)), "Edge@%s" % comp.Label)
            ftype = "Constant Size"
        if not self.edges:
            return self._fail("Pick the edges (or faces) of the components.")
        items = ["%s|%.9g,%.9g,%.9g" % (c.Name, p.x, p.y, p.z) for c, p, _t in self.edges]
        values = {"Radius": radius, "Edges": items, "AutoSelect": self.auto.isChecked()}
        if not self.auto.isChecked():
            names = self.scope_names()
            if not names:
                return self._fail("Check the components the feature changes, or use Auto-select.")
            values["Scope"] = [c for c in ac.components(self.asm) if c.Name in names]
        if self.kind == "Fillet":
            values.update({"FilletType": ftype, "Radius2": self.size_end.value()})
        if self.kind == "Chamfer":
            values.update({"ChamferType": self.ctype.currentText(), "ChamferAngle": self.cangle.value(),
                           "Distance2": self.size2.value(), "FlipChamfer": self.flip_c.isChecked(),
                           "Distance3": self.size3.value(), "EqualDistance": self.equal.isChecked()})
        return self._commit(values)

    def _ctype(self, text):
        vertex = text == "Vertex"
        _row_visible(self.cangle, text == "Angle Distance")
        _row_visible(self.size2, text == "Distance Distance" or (vertex and not self.equal.isChecked()))
        _row_visible(self.size3, vertex and not self.equal.isChecked())
        _row_visible(self.equal, vertex)
        _row_visible(self.flip_c, not vertex)


class SweepPanel(_FeaturePanel):
    ""

    def __init__(self, asm, feat=None, profile=None, path=None):
        from . import asmpm
        self._start(asm, "Sweep", feat)
        self.profile = feat.Profile if feat is not None else profile
        self.path = getattr(feat, "Path", None) if feat is not None else path
        box, lay = asmpm._box("Profile and Path", "Cut-Sweep", "FEATURES_SWEPT_CUT")
        self.profile_box = self._line("FW_AsmSweepProfile")
        self.path_box = self._line("FW_AsmSweepPath")
        lay.addWidget(QtWidgets.QLabel("Profile:"))
        lay.addWidget(self.profile_box)
        lay.addWidget(QtWidgets.QLabel("Path:"))
        lay.addWidget(self.path_box)
        obox, olay = asmpm._box("Options")
        oform = QtWidgets.QFormLayout()
        self.orientation = QtWidgets.QComboBox()
        self.orientation.setObjectName("FW_AsmSweepOrientation")
        self.orientation.addItems(list(SWEEP_ORIENTATIONS))
        if feat is not None and getattr(feat, "Orientation", "") in SWEEP_ORIENTATIONS:
            self.orientation.setCurrentText(feat.Orientation)
        oform.addRow("Profile orientation:", self.orientation)
        self.twist = QtWidgets.QComboBox()
        self.twist.setObjectName("FW_AsmSweepTwist")
        self.twist.addItems(list(SWEEP_TWISTS))
        oform.addRow("Profile Twist:", self.twist)
        self.twist_unit = QtWidgets.QComboBox()
        self.twist_unit.setObjectName("FW_AsmSweepTwistUnit")
        self.twist_unit.addItems(list(TWIST_UNITS))
        oform.addRow("Twist control:", self.twist_unit)
        self.twist_value = QtWidgets.QDoubleSpinBox()
        self.twist_value.setObjectName("FW_AsmSweepTwistValue")
        self.twist_value.setRange(-1e5, 1e5)
        self.twist_value.setDecimals(2)
        self.twist_value.setValue(90.0)
        self.twist_value.setToolTip("Direction 1")
        oform.addRow("Direction 1:", self.twist_value)
        self.twist_vector = QtWidgets.QComboBox()
        self.twist_vector.setObjectName("FW_AsmSweepTwistVector")
        self.twist_vector.addItems(["X", "Y", "Z"])
        self.twist_vector.setCurrentText("Z")
        self.twist_vector.setToolTip("Direction Vector: the profile keeps this direction")
        oform.addRow("Direction Vector:", self.twist_vector)
        if feat is not None:
            _extra(feat)
            if feat.Twist in SWEEP_TWISTS:
                self.twist.setCurrentText(feat.Twist)
            if feat.TwistUnit in TWIST_UNITS:
                self.twist_unit.setCurrentText(feat.TwistUnit)
            if feat.TwistValue:
                self.twist_value.setValue(feat.TwistValue)
            tv = feat.TwistVector
            self.twist_vector.setCurrentText("X" if abs(tv.x) > 0.5 else "Y" if abs(tv.y) > 0.5 else "Z")

        def _twist_rows(*_a):
            k = self.twist.currentText()
            for w in (self.twist_unit, self.twist_value):
                _row_visible(w, k == "Specify Twist Value")
            _row_visible(self.twist_vector, k == "Specify Direction Vector")
            _row_visible(self.orientation, k == "None")
        self.twist.currentTextChanged.connect(_twist_rows)
        _twist_rows()
        olay.addLayout(oform)
        sbox, slay = asmpm._box("Feature Scope")
        self.auto = QtWidgets.QCheckBox("Auto-select")
        self.auto.setObjectName("FW_AsmSweepAuto")
        self.auto.setChecked(feat.AutoSelect if feat is not None else True)
        slay.addWidget(self.auto)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_AsmSweepScope")
        self.list.setStyleSheet(asmpm.PICK_STYLE)
        self.list.setFixedHeight(asmpm._rows(self.list, 3))
        slay.addWidget(self.list)
        self.scope = []
        self.auto.toggled.connect(lambda on: on and self._clear_scope())
        _takes_over(self.list, self.auto, False)
        self._error_label(lay)
        self.form = [box, obox, sbox]
        if feat is not None and not feat.AutoSelect:
            for c in scope_of(feat, asm):
                self._add(c)
        self._show()
        Gui.Selection.addObserver(self, 0)

    def _line(self, name):
        from . import asmpm
        box = QtWidgets.QLineEdit()
        box.setObjectName(name)
        box.setReadOnly(True)
        box.setStyleSheet(asmpm.PICK_STYLE.replace("QListWidget", "QLineEdit"))
        return box

    def _show(self):
        self.profile_box.setText(self.profile.Label if self.profile is not None else "")
        self.path_box.setText(self.path.Label if self.path is not None else "")

    def _clear_scope(self):
        self.list.clear()
        self.scope = []

    def _add(self, comp):
        if comp not in self.scope:
            self.scope.append(comp)
            self.list.addItem(comp.Label)

    def take_sketch(self, sketch):
        """The first sketch picked is the profile, the next the path (a closed one is a profile)."""
        if sketch is self.profile or sketch is self.path:
            return
        closed = any(w.isClosed() for w in sketch.Shape.Wires)
        if self.profile is None and closed:
            self.profile = sketch
        elif self.path is None:
            self.path = sketch
        elif closed:
            self.profile = sketch
        else:
            self.path = sketch
        self._show()

    def _pick(self, root, sub, point):
        if root is None:
            return
        try:
            path = root.getSubObjectList(sub) if sub else [root]
        except Exception:
            path = [root]
        sketch = next((o for o in reversed(path) if o.isDerivedFrom("Sketcher::SketchObject")), None)
        if sketch is not None:
            self.take_sketch(sketch)
            return
        if not self.auto.isChecked():
            ref = ac.reference(self.asm, root, sub) if sub else None
            comp = ref[0] if ref else (root if root in ac.components(self.asm) else None)
            if comp is not None:
                self._add(comp)

    def accept(self):
        if self.profile is None or self.path is None:
            return self._fail("Pick a closed profile sketch and a path sketch.")
        if sweep_tool(self.profile, self.path, self.orientation.currentText(), self._twist()) is None:
            return self._fail("The profile cannot be swept along this path.")
        if not self.auto.isChecked() and not self.scope:
            return self._fail("Pick the components to cut, or use Auto-select.")
        for sk in (self.profile, self.path):
            if App.GuiUp and sk.ViewObject is not None:
                sk.ViewObject.Visibility = False
        return self._commit({"Profile": self.profile, "Path": self.path, "AutoSelect": self.auto.isChecked(),
                             "Scope": list(self.scope), "Orientation": self.orientation.currentText(),
                             "Twist": self.twist.currentText(), "TwistUnit": self.twist_unit.currentText(),
                             "TwistValue": self.twist_value.value(), "TwistVector": self._vector()})

    def _vector(self):
        return {"X": V(1, 0, 0), "Y": V(0, 1, 0)}.get(self.twist_vector.currentText(), V(0, 0, 1))

    def _twist(self):
        import math
        k = self.twist.currentText()
        if k == "Specify Twist Value":
            v, unit = self.twist_value.value(), self.twist_unit.currentText()
            return k, math.radians(v) if unit == "Degrees" else v * 2 * math.pi if unit == "Turns" else v
        if k == "Specify Direction Vector":
            return k, self._vector()
        return "None", None


class WizardPositionsPanel(_FeaturePanel):
    """The Hole Wizard's Positions tab in an assembly: each click on a flat face adds a hole there."""

    def __init__(self, asm, spec, first=None, feat=None, kind="Wizard"):
        from . import asmpm, holespec
        kind = getattr(feat, FEATURE_PROP) if feat is not None else kind
        self._start(asm, kind, feat)
        self.spec = dict(spec)
        self.points = [V(p) for p in feat.Points] if feat is not None else []
        self.normal = V(feat.Normal) if feat is not None else None
        # extapps106: a Hole Wizard hole on a round face goes square to it where it was clicked, each its own way
        self.normals = [V(*n) for n in (self.spec.get("normals") or [])] if kind == "Wizard" else []
        if len(self.normals) != len(self.points):
            self.normals = [self.normal] * len(self.points) if self.normal is not None else []
        box, lay = asmpm._box("Hole Position", "Hole Position", holespec.ICON)
        note = QtWidgets.QLabel("Click faces of the components to place the holes (on a round face the hole goes square to it)."
                                if kind == "Wizard" else "Click flat faces of the components to place the holes.")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_AsmWizardPoints")
        self.list.setStyleSheet(asmpm.PICK_STYLE)
        self.list.setFixedHeight(asmpm._rows(self.list, 4))
        lay.addWidget(self.list)
        self.what = QtWidgets.QLabel(holespec.tree_name(self.spec) if hasattr(holespec, "tree_name") else "")
        self.what.setObjectName("FW_AsmWizardSpec")
        lay.addWidget(self.what)
        self.tapped = QtWidgets.QCheckBox("Last Part: tapped hole")
        self.tapped.setObjectName("FW_AsmSeriesTapped")
        self.tapped.setChecked(bool(getattr(feat, "Tapped", True)) if feat is not None else True)
        self.tapped.setVisible(kind == "Series")
        lay.addWidget(self.tapped)
        if kind == "Series":
            hint = QtWidgets.QLabel("First Part: the hole above. Middle Parts: its clearance. Last Part: tapped, or the clearance.")
            hint.setWordWrap(True)
            lay.addWidget(hint)
        sbox, slay = asmpm._box("Feature Scope")
        sbox.setVisible(kind != "Series")
        self.auto = QtWidgets.QCheckBox("Auto-select")
        self.auto.setObjectName("FW_AsmWizardAuto")
        self.auto.setChecked(feat.AutoSelect if feat is not None else True)
        slay.addWidget(self.auto)
        self._error_label(lay)
        self.form = [box, sbox]
        for p in self.points:
            self.list.addItem("(%.2f, %.2f, %.2f)" % tuple(p))
        if first is not None:
            self._pick(*first)
        Gui.Selection.addObserver(self, 0)

    def _pick(self, root, sub, point):
        if root is None or not sub:
            return
        ref = ac.reference(self.asm, root, sub)
        shape = ac.element(*ref) if ref else None
        wizard = self.kind_is_wizard()
        if shape is None or shape.ShapeType != "Face" or (shape.Surface.TypeId != "Part::GeomPlane" and not wizard):
            return
        p = point if point is not None else shape.CenterOfMass
        u, v = shape.Surface.parameter(p)
        n = shape.normalAt(u, v)
        n.normalize()
        if not wizard and self.normal is not None and n.cross(self.normal).Length > 1e-6:
            return self._fail("All the holes of one Hole Series go the same way: pick a face parallel to the first.")
        if self.normal is None:
            self.normal = n
        q = shape.Surface.value(u, v)
        self.points.append(q)
        self.normals.append(n)
        self.list.addItem("%s@%s (%.2f, %.2f, %.2f)" % (ref[1].split(".")[-1], ref[0].Label, q.x, q.y, q.z))
        self.error.hide()
        Gui.Selection.clearSelection()

    def kind_is_wizard(self):
        return not isinstance(self, HoleSeriesPanel)

    def accept(self):
        import json
        if not self.points:
            return self._fail("Click a face to place a hole." if self.kind_is_wizard() else "Click a flat face to place a hole.")
        from . import holeends
        need = holeends.needs(self.spec.get("end"))
        if need and not (self.spec.get("end_target") and self.spec.get("end_ref")):
            return self._fail("Pick the %s the hole goes up to (on the Type tab)." % ("vertex" if need == "Vertex" else "face"))
        spec = dict(self.spec)
        spec.pop("normals", None)
        if self.kind_is_wizard() and len(self.normals) == len(self.points) and \
                any(n.cross(self.normals[0]).Length > 1e-6 for n in self.normals):
            spec["normals"] = [[round(n.x, 9), round(n.y, 9), round(n.z, 9)] for n in self.normals]
        return self._commit({"Spec": json.dumps(spec, sort_keys=True), "Points": self.points,
                             "Normal": self.normals[0] if self.normals else self.normal, "EndCondition": "Through All" if self.spec.get("end") == "Through All" else "Blind",
                             "AutoSelect": self.auto.isChecked(), "Tapped": self.tapped.isChecked()})


class _SpecBox(QtWidgets.QWidget):
    """One part's hole on a Hole Series tab: hole type, Standard, Type, Size, Fit (holespec's tables);
    with auto, "Auto size based on start part" and the size controls off while it is on."""

    def __init__(self, name, kinds, spec, auto=None, end=False):
        from . import holespec
        super().__init__()
        self.setObjectName("FW_Series%s" % name)
        self.hs = holespec
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.auto = None
        if auto is not None:
            self.auto = QtWidgets.QCheckBox("Auto size based on start part")
            self.auto.setObjectName("FW_Series%sAuto" % name)
            self.auto.setChecked(bool(auto))
            lay.addWidget(self.auto)
        form = QtWidgets.QFormLayout()
        lay.addLayout(form)
        self.kind = QtWidgets.QComboBox()
        self.kind.setObjectName("FW_Series%sKind" % name)
        self.kind.addItems(list(kinds))
        self.kind.setVisible(len(kinds) > 1)
        if len(kinds) > 1:
            form.addRow("Hole type:", self.kind)
        self.standard, self.type, self.size, self.fit = (QtWidgets.QComboBox() for _i in range(4))
        for w, label in ((self.standard, "Standard"), (self.type, "Type"), (self.size, "Size"), (self.fit, "Fit")):
            w.setObjectName("FW_Series%s%s" % (name, label))
            form.addRow(label + ":", w)
        self.fit_label = form.labelForField(self.fit)
        self.end = self.depth = None
        if end:
            self.end = QtWidgets.QComboBox()
            self.end.setObjectName("FW_Series%sEnd" % name)
            self.end.addItems(["Through All", "Blind"])
            form.addRow("End Condition:", self.end)
            self.depth = QtWidgets.QDoubleSpinBox()
            self.depth.setObjectName("FW_Series%sDepth" % name)
            self.depth.setRange(0.01, 1e6)
            self.depth.setSuffix(" mm")
            self.depth.setValue(10.0)
            form.addRow("Depth:", self.depth)
            self.end.currentTextChanged.connect(lambda *_a: self._state())
        self._busy = False
        self.set_spec(spec)
        self.kind.currentTextChanged.connect(lambda *_a: self._fill("kind"))
        self.standard.currentTextChanged.connect(lambda *_a: self._fill("standard"))
        self.type.currentTextChanged.connect(lambda *_a: self._fill("type"))
        if self.auto is not None:
            self.auto.toggled.connect(lambda *_a: self._state())
        self._state()

    def set_spec(self, spec):
        spec = dict(self.hs.DEFAULT, **(spec or {}))
        self._busy = True
        if self.kind.findText(spec.get("kind", "")) >= 0:
            self.kind.setCurrentText(spec["kind"])
        self._spec = spec
        self._busy = False
        self._fill(None)
        if self.end is not None:
            self.end.setCurrentText(spec.get("end", "Through All") if spec.get("end") in ("Through All", "Blind") else "Through All")
            self.depth.setValue(float(spec.get("depth", 10.0) or 10.0))

    def _set(self, combo, items, want):
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(list(items))
        if want in items:
            combo.setCurrentText(want)
        combo.blockSignals(False)
        return combo.currentText()

    def _fill(self, changed):
        if self._busy:
            return
        sp = dict(self._spec)
        if changed is not None:
            sp.update(kind=self.kind.currentText(), standard=self.standard.currentText(),
                      type=self.type.currentText(), size=self.size.currentText())
        sp["kind"] = self.kind.currentText()
        sp["standard"] = self._set(self.standard, self.hs.standards(sp["kind"]), sp.get("standard"))
        sp["type"] = self._set(self.type, self.hs.types(sp["kind"], sp["standard"]), sp.get("type"))
        try:
            sizes = self.hs.sizes(sp)
        except Exception:
            sizes = []
        sp["size"] = self._set(self.size, sizes, sp.get("size"))
        self._set(self.fit, self.hs.FIT_NAMES, sp.get("fit", "Normal"))
        has = self.hs.has_fit(sp)
        self.fit.setVisible(has)
        if self.fit_label is not None:
            self.fit_label.setVisible(has)
        self._spec = sp
        self._state()

    def _state(self):
        on = self.auto is None or not self.auto.isChecked()
        for w in (self.standard, self.type, self.size, self.fit):
            if self.auto is not None and not hasattr(w, "_fw_take_over"):
                _takes_over(w, self.auto, False)     # choosing a size turns the automatic size off
        if self.depth is not None:
            _row_visible(self.depth, self.end.currentText() == "Blind")

    def spec(self):
        out = dict(self._spec, kind=self.kind.currentText(), standard=self.standard.currentText(),
                   type=self.type.currentText(), size=self.size.currentText(), fit=self.fit.currentText())
        if self.end is not None:
            out.update(end=self.end.currentText(), depth=self.depth.value())
        if self.auto is not None:
            out["auto"] = self.auto.isChecked()
        return out


class HoleSeriesPanel(WizardPositionsPanel):
    ""




    TABS = ("Hole Position", "Hole Start", "Hole Middle", "Hole End", "Smart Fasteners")

    def __init__(self, asm, spec=None, first=None, feat=None):
        from . import asmpm, holespec
        spec = dict(holespec.DEFAULT, **dict(spec or (json_spec(feat) if feat is not None else {}) or
                                             {"kind": "Counterbore", "type": "Socket Head Cap Screw ISO 4762", "size": "M6"}))
        if spec.get("kind") not in ("Counterbore", "Countersink", "Hole"):
            spec["kind"] = "Counterbore"
        super().__init__(asm, spec, first=None, feat=feat, kind="Series")
        pos_box = self.form[0]
        self.tapped.hide()
        for w in pos_box.findChildren(QtWidgets.QLabel):
            if w.text().startswith("First Part:"):
                w.hide()
        self.what.hide()
        self.existing = False
        mode = QtWidgets.QWidget()
        ml = QtWidgets.QVBoxLayout(mode)
        ml.setContentsMargins(0, 0, 0, 0)
        self.new_hole = QtWidgets.QRadioButton("Create new hole")
        self.new_hole.setObjectName("FW_SeriesNewHole")
        self.old_hole = QtWidgets.QRadioButton("Use existing hole")
        self.old_hole.setObjectName("FW_SeriesExistingHole")
        self.new_hole.setChecked(True)
        ml.addWidget(self.new_hole)
        ml.addWidget(self.old_hole)
        pos_box.layout().insertWidget(0, mode)
        self.new_hole.toggled.connect(self._mode)
        middle, last = series_parts(feat) if feat is not None else ({"auto": True}, {"kind": "Straight Tap", "auto": True, "end": "Through All"})
        self.first_box = _SpecBox("First", ("Counterbore", "Countersink", "Hole"), spec)
        self.middle_box = _SpecBox("Middle", ("Hole",), dict(spec, **dict(middle, kind="Hole", type="Screw Clearances")),
                                   auto=middle.get("auto", True))
        self.last_box = _SpecBox("Last", ("Hole", "Straight Tap"), dict(spec, **dict(
            last, type=last.get("type") or ("Tapped hole" if last.get("kind") == "Straight Tap" else "Screw Clearances"))),
            auto=last.get("auto", True), end=True)
        fbox = QtWidgets.QWidget()
        fl = QtWidgets.QVBoxLayout(fbox)
        self.fasteners = QtWidgets.QCheckBox("Add fasteners (Smart Fasteners)")
        self.fasteners.setObjectName("FW_SeriesFasteners")
        self.fasteners.setChecked(bool(getattr(feat, "SeriesFasteners", False)) if feat is not None else False)
        fl.addWidget(self.fasteners)
        from . import toolbox
        fform = QtWidgets.QFormLayout()
        self.fastener_kind = QtWidgets.QComboBox()
        self.fastener_kind.setObjectName("FW_SeriesFastenerType")
        self.fastener_kind.addItem("Default (from the Hole Start)", None)
        for k in toolbox.SCREWS:
            self.fastener_kind.addItem(toolbox.TYPES[k][1], k)
        fform.addRow("Fastener:", self.fastener_kind)
        self.fastener_top = QtWidgets.QComboBox()
        self.fastener_top.setObjectName("FW_SeriesTopStack")
        self.fastener_top.addItem("None", None)
        for k in toolbox.WASHERS:
            self.fastener_top.addItem(toolbox.TYPES[k][1], k)
        fform.addRow("Top Stack:", self.fastener_top)
        self.fastener_bottom = QtWidgets.QComboBox()
        self.fastener_bottom.setObjectName("FW_SeriesBottomStack")
        for label, stack in (("Washer and nut", ("plain-washer", "hex-nut")), ("Nut", ("hex-nut",)),
                             ("Spring washer and nut", ("spring-washer", "hex-nut")), ("None", ())):
            self.fastener_bottom.addItem(label, stack)
        fform.addRow("Bottom Stack:", self.fastener_bottom)
        self.fastener_auto = QtWidgets.QCheckBox("Auto size to mated geometry")
        self.fastener_auto.setObjectName("FW_SeriesFastenerAuto")
        self.fastener_auto.setChecked(True)
        fform.addRow(self.fastener_auto)
        fl.addLayout(fform)
        for w in (self.fastener_kind, self.fastener_top, self.fastener_bottom, self.fastener_auto):
            _takes_over(w, self.fasteners, True)       # choosing one turns Add fasteners on
        note = QtWidgets.QLabel("A fastener sized from the series goes through every part (a tapped last part takes no nut).")
        note.setWordWrap(True)
        fl.addWidget(note)
        fl.addStretch(1)
        box, lay = asmpm._box("Hole Series", "Hole Series", holespec.ICON)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("FW_HoleSeriesTabs")
        self.tabs.setDocumentMode(True)
        pos_page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(pos_page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(pos_box)
        for title, page in zip(self.TABS, (pos_page, self.first_box, self.middle_box, self.last_box, fbox)):
            wrap = page
            if page is not pos_page:
                wrap = QtWidgets.QWidget()
                wl = QtWidgets.QVBoxLayout(wrap)
                wl.addWidget(page)
                wl.addStretch(1)
            self.tabs.addTab(wrap, title)
            self.tabs.setTabToolTip(self.tabs.count() - 1, title)

        # shows every tab, so they share the width (names shortened, the whole name as a tooltip)
        bar = self.tabs.tabBar()
        bar.setUsesScrollButtons(False)
        bar.setElideMode(QtCore.Qt.ElideRight)
        bar.setExpanding(True)
        lay.addWidget(self.tabs)
        self.form = [box]
        if first is not None:
            self._pick(*first)

    def _mode(self, *_a):
        self.existing = self.old_hole.isChecked()

    def _pick(self, root, sub, point):
        if not getattr(self, "existing", False):
            return super()._pick(root, sub, point)
        if root is None or not sub:
            return
        ref = ac.reference(self.asm, root, sub)
        shape = ac.element(*ref) if ref else None
        if shape is None or shape.ShapeType != "Face" or "Cylinder" not in shape.Surface.TypeId:
            return self._fail("Use existing hole: click the round face of a hole.")
        axis = V(shape.Surface.Axis)
        axis.normalize()
        if self.normal is not None:
            if axis.dot(self.normal) < 0:
                axis = axis * -1
        elif axis.z < 0 or (abs(axis.z) < 1e-9 and axis.x + axis.y < 0):
            axis = axis * -1
        if self.normal is not None and axis.cross(self.normal).Length > 1e-6:
            return self._fail("All the holes of one Hole Series go the same way: pick a hole parallel to the first.")
        c = V(shape.Surface.Center)
        top = max((v.Point - c).dot(axis) for v in shape.Vertexes) if shape.Vertexes else 0.0
        q = c + axis * top
        self.normal = axis
        self.points.append(q)
        self.list.addItem("hole@%s (%.2f, %.2f, %.2f)" % (ref[0].Label, q.x, q.y, q.z))
        self.error.hide()
        Gui.Selection.clearSelection()

    def values(self):
        import json
        first = self.first_box.spec()
        first.pop("auto", None)
        first["end"] = "Through All"
        middle = self.middle_box.spec()
        last = self.last_box.spec()
        keep = ("auto", "standard", "type", "size", "fit")
        return {"Spec": json.dumps(first, sort_keys=True), "Points": self.points, "Normal": self.normal,
                "EndCondition": "Through All", "AutoSelect": False,
                "Tapped": last["kind"] == "Straight Tap",
                "SeriesMiddle": json.dumps({k: middle[k] for k in keep}, sort_keys=True),
                "SeriesLast": json.dumps({k: last[k] for k in keep + ("kind", "end", "depth")}, sort_keys=True),
                "SeriesFasteners": self.fasteners.isChecked(), "Scope": []}

    def accept(self):
        if not self.points:
            self.tabs.setCurrentIndex(0)
            return self._fail("Click a flat face to place a hole (or the round face of an existing hole).")
        add = self.fasteners.isChecked()       # (the PM's widgets go when it closes)
        opts = dict(kind=self.fastener_kind.currentData(), top_stack=self.fastener_top.currentData(),
                    bottom_stack=tuple(self.fastener_bottom.currentData() or ()),
                    auto_length=self.fastener_auto.isChecked())
        out = self._commit(self.values())
        if self.feat is not None:
            try:
                self.feat.Scope = [c.Name for c in series_components(self.feat, self.asm)]
            except Exception as error:
                App.Console.PrintLog("FreeCAD: Hole Series parts: %s\n" % error)
        if add and self.feat is not None:
            add_series_fasteners(self.feat, self.asm, **opts)
        return out


def json_spec(feat):
    import json
    try:
        return json.loads(feat.Spec or "{}")
    except (ValueError, AttributeError):
        return {}


def add_series_fasteners(feat, asm, kind=None, top_stack=None, bottom_stack=("plain-washer", "hex-nut"),
                         auto_length=True):
    ""

    try:
        from . import toolbox
        comps = series_components(feat, asm)
        if comps:
            return toolbox.smart_fasteners(asm, comps, kind=kind, top_stack=top_stack,
                                           bottom_stack=bottom_stack, auto_length=auto_length)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Hole Series fasteners: %s\n" % error)
    return {}


def hole_series(asm, first=None):
    ""
    return _show(HoleSeriesPanel(asm, first=first))


def hole_wizard(asm, first=None, kind="Wizard"):
    ""
    from . import holespec

    class AsmSpecPanel(holespec.HoleSpecPanel):
        def _end_pick(self, sel, sub, ref, shape):
            """extapps106: the vertex or face that Up To Vertex / Up To Surface / Offset From Surface goes up to
            (a vertex or face of a component; its place is kept in the component's own frame)."""
            from . import holeends
            need = holeends.needs(self.spec.get("end"))
            if (self.tabs.currentIndex() != 0 or not need or self.spec.get("end_target") or shape is None
                    or shape.ShapeType != need):
                return False
            comp = ref[0]
            if need == "Vertex":
                point = shape.Point
            else:
                (u0, u1, v0, v1) = shape.ParameterRange
                point = shape.valueAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
            local = comp.Placement.inverse().multVec(point)
            self.spec["end_target"] = "%s:%s" % (comp.Label, ref[1].split(".")[-1])
            self.spec["end_ref"] = "%s|%.6f,%.6f,%.6f" % (comp.Name, local.x, local.y, local.z)
            Gui.Selection.clearSelection()
            self._load()
            return True

        def picked(self):
            if self.done:
                return
            for sel in Gui.Selection.getSelectionEx("", 0):
                for sub, pnt in zip(sel.SubElementNames, sel.PickedPoints):
                    ref = ac.reference(asm, sel.Object, sub) if sub else None
                    shape = ac.element(*ref) if ref else None
                    if self._end_pick(sel, sub, ref, shape):
                        return
                    if shape is not None and shape.ShapeType == "Face" and shape.Surface.TypeId == "Part::GeomPlane":
                        self.first = (sel.Object, sub, V(*pnt))
                        self.face = (ref[0], ref[1].split(".")[-1])
                        self._note_face()
                        if self.tabs.currentIndex() == 1:
                            self._go(*self.face)
                        return

    def positions(obj, sub, spec):
        _show(WizardPositionsPanel(asm, spec, getattr(panel, "first", None), kind=kind))

    panel = AsmSpecPanel(None, None, positions)
    if first is not None:
        panel.first = first
        ref = ac.reference(asm, first[0], first[1])
        if ref is not None:
            panel.face = (ref[0], ref[1].split(".")[-1])
            panel._note_face()
    OPEN[:] = [panel]
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    Gui.Control.showDialog(panel)
    return panel


class WeldPanel(_FeaturePanel):
    ""

    def __init__(self, asm, feat=None):
        from . import asmpm
        self._start(asm, "Weld", feat)
        box, lay = asmpm._box("Weld Path", "Weld Bead", "WELDMENTS_WELD_BEAD")
        lay.addWidget(QtWidgets.QLabel("Weld From:"))
        self.from_list = self._list("FW_AsmWeldFrom")
        lay.addWidget(self.from_list)
        lay.addWidget(QtWidgets.QLabel("Weld To:"))
        self.to_list = self._list("FW_AsmWeldTo")
        lay.addWidget(self.to_list)
        form = QtWidgets.QFormLayout()
        self.size = _spin("FW_AsmWeldSize", 3.0)
        form.addRow("Bead size:", self.size)
        lay.addLayout(form)
        self.length = QtWidgets.QLabel("")
        self.length.setObjectName("FW_AsmWeldLength")
        lay.addWidget(self.length)
        self._error_label(lay)
        self.form = [box]
        self.items = {"from": [], "to": []}
        self.active = "from"
        if feat is not None:
            self.size.setValue(float(getattr(feat.Radius, "Value", feat.Radius)))
            comps = {c.Name: c for c in ac.components(asm)}
            for key, prop, lst in (("from", feat.WeldFrom, self.from_list), ("to", feat.WeldTo, self.to_list)):
                for item in prop:
                    self.items[key].append(item)
                    lst.addItem("Face@%s" % comps.get(item.split("|")[0], feat).Label)
            self.active = "to"
        self._focus()
        self._show_length()
        Gui.Selection.addObserver(self, 0)

    def _list(self, name):
        from . import asmpm
        lst = QtWidgets.QListWidget()
        lst.setObjectName(name)
        lst.setProperty("swpickbox", True)      # a selection box (Weld From / Weld To / edges): its colour strip
        lst.setFixedHeight(asmpm._rows(lst, 2))
        panel = self

        class F(QtCore.QObject):
            def eventFilter(self, w, e):
                if not isinstance(e, QtCore.QEvent):
                    return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
                if e.type() == QtCore.QEvent.MouseButtonPress:
                    panel.active = "from" if w is panel.from_list else "to"
                    panel._focus()
                return False
        lst._fw_filter = F(lst)
        lst.installEventFilter(lst._fw_filter)
        return lst

    def _focus(self):
        from . import asmpm
        self.from_list.setStyleSheet(asmpm.PICK_STYLE if self.active == "from" else "")
        self.to_list.setStyleSheet(asmpm.PICK_STYLE if self.active == "to" else "")

    def _show_length(self):
        class F:
            pass
        f = F()
        f.WeldFrom, f.WeldTo = self.items["from"], self.items["to"]
        try:
            n = sum(e.Length for e in weld_path(f, self.asm))
        except Exception:
            n = 0.0
        self.length.setText("Weld length: %.2fmm" % n if n else "")

    def _pick(self, root, sub, point):
        if root is None or not sub:
            return
        ref = ac.reference(self.asm, root, sub)
        shape = ac.element(*ref) if ref else None
        if shape is None or shape.ShapeType != "Face":
            return
        comp = ref[0]
        p = comp.Placement.inverse().multVec(shape.CenterOfMass if point is None else point)
        item = "%s|%.9g,%.9g,%.9g" % (comp.Name, p.x, p.y, p.z)
        self.items[self.active].append(item)
        (self.from_list if self.active == "from" else self.to_list).addItem(
            "%s@%s" % (ref[1].split(".")[-1], comp.Label))
        if self.active == "from" and not self.items["to"]:
            self.active = "to"
            self._focus()
        self._show_length()
        self.error.hide()
        Gui.Selection.clearSelection()

    def accept(self):
        if not self.items["from"] or not self.items["to"]:
            return self._fail("Pick the Weld From and the Weld To faces.")
        return self._commit({"WeldFrom": list(self.items["from"]), "WeldTo": list(self.items["to"]),
                             "Radius": self.size.value()})


class BeltPanel(_FeaturePanel):
    ""


    def __init__(self, asm, feat=None):
        from . import asmpm
        self._start(asm, "Belt", feat)
        box, lay = asmpm._box("Belt Members", "Belt/Chain", "ASSEMBLIES_BELT_CHAIN")
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_AsmBeltMembers")
        self.list.setStyleSheet(asmpm.PICK_STYLE)
        self.list.setFixedHeight(asmpm._rows(self.list, 4))
        lay.addWidget(self.list)
        row = QtWidgets.QHBoxLayout()
        self.up = QtWidgets.QPushButton("Up")
        self.up.setObjectName("FW_AsmBeltUp")
        self.down = QtWidgets.QPushButton("Down")
        self.down.setObjectName("FW_AsmBeltDown")
        row.addWidget(self.up)
        row.addWidget(self.down)
        lay.addLayout(row)
        self.up.clicked.connect(lambda: self._move(-1))
        self.down.clicked.connect(lambda: self._move(1))

        self.flip_side = QtWidgets.QPushButton("Flip belt side")
        self.flip_side.setObjectName("FW_AsmBeltFlipSide")
        self.flip_side.clicked.connect(self._flip_side)
        lay.addWidget(self.flip_side, 0, QtCore.Qt.AlignLeft)
        self.flipped = set()
        pbox, play = asmpm._box("Properties")
        self.length = QtWidgets.QLabel("")
        self.length.setObjectName("FW_AsmBeltLength")
        play.addWidget(self.length)

        self.driving = QtWidgets.QCheckBox("Driving")
        self.driving.setObjectName("FW_AsmBeltDriving")
        play.addWidget(self.driving)
        dform = QtWidgets.QFormLayout()
        self.drive_length = _spin("FW_AsmBeltDriveLength", 100.0)
        self.drive_length.setRange(0.01, 1.0e7)
        dform.addRow("Belt length:", self.drive_length)
        play.addLayout(dform)
        self.use = QtWidgets.QCheckBox("Use belt thickness")
        self.use.setObjectName("FW_AsmBeltUseThickness")
        play.addWidget(self.use)
        form = QtWidgets.QFormLayout()
        self.thick = _spin("FW_AsmBeltThickness", 1.0)
        form.addRow("Belt thickness:", self.thick)
        play.addLayout(form)
        self.engage = QtWidgets.QCheckBox("Engage belt")
        self.engage.setObjectName("FW_AsmBeltEngage")
        self.engage.setChecked(True)
        play.addWidget(self.engage)
        self.part = QtWidgets.QCheckBox("Create belt part")
        self.part.setObjectName("FW_AsmBeltPart")
        play.addWidget(self.part)
        self._error_label(lay)
        self.form = [box, pbox]
        self.items = []
        if feat is not None:
            self.use.setChecked(feat.UseThickness)
            self.thick.setValue(float(getattr(feat.Thickness, "Value", feat.Thickness)) or 1.0)
            self.engage.setChecked(feat.Engage)
            self.part.setChecked(feat.BeltPart)
            self.flipped = set(getattr(feat, "FlipSides", []) or [])
            self.driving.setChecked(bool(getattr(feat, "Driving", False)))
            bl = getattr(feat, "BeltLength", 0)
            bl = float(getattr(bl, "Value", bl) or 0)
            if bl > 0:
                self.drive_length.setValue(bl)
            for item in feat.Members:
                ref = _face_ref(asm, item)
                self.items.append(item)
                self.list.addItem("%s@%s" % (ref[1], ref[0].Label) if ref else item)
        _takes_over(self.thick, self.use, True)          # typing a thickness turns Use belt thickness on
        _takes_over(self.drive_length, self.driving, True)      # typing a length turns Driving on
        self.use.toggled.connect(lambda on: self._show_length())
        self.thick.valueChanged.connect(lambda *_: self._show_length())
        self._show_length()
        Gui.Selection.addObserver(self, 0)

    def _move(self, step):
        i = self.list.currentRow()
        j = i + step
        if i < 0 or j < 0 or j >= len(self.items):
            return
        self.items[i], self.items[j] = self.items[j], self.items[i]
        a, b = self.list.item(i).text(), self.list.item(j).text()
        self.list.item(i).setText(b)
        self.list.item(j).setText(a)
        self.list.setCurrentRow(j)
        self._show_length()

    def _flip_side(self):
        i = self.list.currentRow()
        if i < 0 or i >= len(self.items):
            i = len(self.items) - 1
        if i < 0:
            return
        item = self.items[i]
        self.flipped.symmetric_difference_update({item})
        text = self.list.item(i).text().replace(" (inside)", "")
        self.list.item(i).setText(text + (" (inside)" if item in self.flipped else ""))
        self._show_length()

    def _flips(self):
        return flips_of([i for i in self.items if _face_ref(self.asm, i) is not None], self.flipped)

    def _show_length(self):
        members = pulleys(self.asm, self.items)
        off = self.thick.value() / 2.0 if self.use.isChecked() else 0.0
        w = belt_wire(members, off, self._flips())
        self.length.setText("Belt length: %.2fmm" % w.Length if w is not None else "Belt length:")
        if w is not None and hasattr(self, "driving") and not self.driving.isChecked():
            self.drive_length.blockSignals(True)
            self.drive_length.setValue(w.Length)     # Driving's box starts at the belt as it is
            self.drive_length.blockSignals(False)

    def _pick(self, root, sub, point):
        if root is None or not sub:
            return
        ref = ac.reference(self.asm, root, sub)
        shape = ac.element(*ref) if ref else None
        g = ac.geometry(shape)
        if shape is None or shape.ShapeType not in ("Face", "Edge") or g is None or g[0] != "axis":
            return
        comp = ref[0]
        if shape.ShapeType == "Edge":       # a round edge: its face
            whole = global_shape(comp)
            face = next((f for f in whole.Faces if f.Surface.TypeId == "Part::GeomCylinder"
                         and any(e.isSame(shape) for e in f.Edges)), None)
            if face is None:
                return
            shape = face
        p = comp.Placement.inverse().multVec(shape.CenterOfMass if point is None else point)
        if shape.ShapeType == "Face":
            # a point ON the face (picked in the tree there is no point: a cylinder's centre of
            # mass is on its axis, not on the face, and the member was lost)
            import Part
            near = shape.distToShape(Part.Vertex(shape.CenterOfMass if point is None else point))[1][0][0]
            p = comp.Placement.inverse().multVec(near)
        item = "%s|%.9g,%.9g,%.9g" % (comp.Name, p.x, p.y, p.z)
        if any(i.split("|")[0] == comp.Name for i in self.items):
            return
        self.items.append(item)
        self.list.addItem("%s@%s" % (ref[1].split(".")[-1], comp.Label))
        self._show_length()
        self.error.hide()
        Gui.Selection.clearSelection()

    def accept(self):
        if len(pulleys(self.asm, self.items)) < 2:
            return self._fail("Pick the round faces of two or more pulleys.")
        if belt_wire(pulleys(self.asm, self.items), 0.0, self._flips()) is None:
            return self._fail("The pulleys overlap: the belt cannot go round them.")
        if self.driving.isChecked():
            off = self.thick.value() / 2.0 if self.use.isChecked() else 0.0
            if not drive_length(self.asm, self.items, self._flips(), off, self.drive_length.value()):
                return self._fail("The belt cannot be %.2fmm: the pulleys would overlap or no pulley is free to move."
                                  % self.drive_length.value())
            self.doc.recompute()
        ok = self._commit({"Members": list(self.items), "UseThickness": self.use.isChecked(),
                           "Driving": self.driving.isChecked(), "BeltLength": self.drive_length.value(),
                           "Thickness": self.thick.value(), "Engage": self.engage.isChecked(),
                           "BeltPart": self.part.isChecked(),
                           "FlipSides": [i for i in self.items if i in self.flipped]})
        if self.feat is not None:
            self.doc.openTransaction("Engage belt")
            try:
                engage(self.feat)
            except BaseException:
                try:
                    self.doc.abortTransaction()
                except Exception:
                    pass
                raise
            self.doc.commitTransaction()
            self.doc.recompute()
            _refresh()
        return ok


def _spin(name, value):
    box = QtWidgets.QDoubleSpinBox()
    box.setObjectName(name)
    box.setRange(0.001, 1.0e6)
    box.setDecimals(2)
    box.setSuffix("mm")
    box.setValue(value)
    return box


def _refresh():
    try:
        from . import asmtools
        asmtools._refresh()
    except Exception as _fw_err:
        _fw_log("asmfeature.py:3379", _fw_err)


OPEN = []


def _show(panel):
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    OPEN[:] = [panel]
    Gui.Control.showDialog(panel)
    return panel


def edit(feat):
    asm = ac.assembly_of(feat.Document)
    if asm is None:
        return None
    kind = getattr(feat, FEATURE_PROP)
    if kind == "Hole":
        return _show(HolePanel(asm, feat=feat))
    if kind in EDGE_KINDS:
        return _show(EdgePanel(asm, kind, feat=feat))
    if kind == "Sweep":
        return _show(SweepPanel(asm, feat=feat))
    if kind == "Weld":
        return _show(WeldPanel(asm, feat=feat))
    if kind == "Belt":
        return _show(BeltPanel(asm, feat=feat))
    if kind == "Series":
        return _show(HoleSeriesPanel(asm, feat=feat))
    if kind == "Wizard":
        import json
        return _show(WizardPositionsPanel(asm, json.loads(feat.Spec or "{}"), feat=feat))
    return _show(CutPanel(asm, kind, feat=feat))


def _picked_sketch():
    for sel in Gui.Selection.getSelectionEx("", 0):
        if sel.Object.isDerivedFrom("Sketcher::SketchObject"):
            return sel.Object
        for sub in sel.SubElementNames:
            try:
                path = sel.Object.getSubObjectList(sub)
            except Exception as _fw_err:
                _fw_log("asmfeature.py:3438", _fw_err)
                continue
            sk = next((o for o in reversed(path) if o.isDerivedFrom("Sketcher::SketchObject")), None)
            if sk is not None:
                return sk
    return None


class _CutCommand:
    KIND = "Extrude"
    RES = {}

    def GetResources(self):
        return dict(self.RES)

    def Activated(self):
        from . import asmtools, asmui
        asm = asmtools._assembly()
        if asm is None:
            return
        sketch = _picked_sketch()
        asmui.activate(asm)
        _show(CutPanel(asm, self.KIND, sketch))

    def IsActive(self):
        return App.ActiveDocument is not None and ac.assembly_of(App.ActiveDocument) is not None


class ExtrudedCutCommand(_CutCommand):
    KIND = "Extrude"
    RES = {"MenuText": "Extruded Cut", "Pixmap": "PartDesign_Pocket",
           "ToolTip": "Cuts the components with an extruded sketch, in the assembly only."}


class RevolvedCutCommand(_CutCommand):
    KIND = "Revolve"
    RES = {"MenuText": "Revolved Cut", "Pixmap": "PartDesign_Groove",
           "ToolTip": "Cuts the components by revolving a sketch about its centerline, in the assembly only."}


class _PanelCommand:
    KIND = "Hole"
    RES = {}

    def GetResources(self):
        return dict(self.RES)

    def Activated(self):
        from . import asmtools, asmui
        asm = asmtools._assembly()
        if asm is None:
            return
        picks = [(s.Object, sub, V(*p) if p else None) for s in Gui.Selection.getSelectionEx("", 0)
                 for sub, p in zip(s.SubElementNames, list(s.PickedPoints) + [None] * len(s.SubElementNames))]
        asmui.activate(asm)
        panel = HolePanel(asm) if self.KIND == "Hole" else SweepPanel(asm) if self.KIND == "Sweep" \
            else WeldPanel(asm) if self.KIND == "Weld" else BeltPanel(asm) if self.KIND == "Belt" \
            else EdgePanel(asm, self.KIND)
        _show(panel)
        for obj, sub, p in picks:       # pick first, tool second
            panel._pick(obj, sub, p)

    def IsActive(self):
        return App.ActiveDocument is not None and ac.assembly_of(App.ActiveDocument) is not None


class HoleWizardCommand:
    def GetResources(self):
        return {"MenuText": "Hole Wizard", "Pixmap": "PartDesign_Hole",
                "ToolTip": "Holes from the Hole Wizard's types and sizes, through the components, in the assembly only."}

    def Activated(self):
        from . import asmtools, asmui
        asm = asmtools._assembly()
        if asm is None:
            return
        first = None
        for sel in Gui.Selection.getSelectionEx("", 0):
            for sub, p in zip(sel.SubElementNames, sel.PickedPoints):
                first = (sel.Object, sub, V(*p))
        asmui.activate(asm)
        hole_wizard(asm, first)

    def IsActive(self):
        return App.ActiveDocument is not None and ac.assembly_of(App.ActiveDocument) is not None


class HoleSeriesCommand(HoleWizardCommand):
    def GetResources(self):
        return {"MenuText": "Hole Series", "Pixmap": "PartDesign_Hole",
                "ToolTip": "One hole through a stack of parts: the head in the first, clearance in the middle, "
                           "tapped in the last."}

    def Activated(self):
        from . import asmtools, asmui
        asm = asmtools._assembly()
        if asm is None:
            return
        first = None
        for sel in Gui.Selection.getSelectionEx("", 0):
            for sub, p in zip(sel.SubElementNames, sel.PickedPoints):
                first = (sel.Object, sub, V(*p))
        asmui.activate(asm)
        hole_series(asm, first)


class SimpleHoleCommand(_PanelCommand):
    KIND = "Hole"
    RES = {"MenuText": "Simple Hole", "Pixmap": "PartDesign_Hole",
           "ToolTip": "A round hole through the components from a picked flat face, in the assembly only."}


class SweptCutCommand(_PanelCommand):
    KIND = "Sweep"
    RES = {"MenuText": "Swept Cut", "Pixmap": "PartDesign_SubtractivePipe",
           "ToolTip": "Cuts the components with a profile swept along a path, in the assembly only."}


class WeldBeadCommand(_PanelCommand):
    KIND = "Weld"
    RES = {"MenuText": "Weld Bead", "Pixmap": "Part_Sweep",
           "ToolTip": "A weld bead where the Weld From faces meet the Weld To faces."}


class BeltChainCommand(_PanelCommand):
    KIND = "Belt"
    RES = {"MenuText": "Belt/Chain", "Pixmap": "Assembly_CreateJointGears",
           "ToolTip": "A belt or chain round the pulleys picked; Engage belt makes them turn together."}


class FilletCommand(_PanelCommand):
    KIND = "Fillet"
    RES = {"MenuText": "Fillet", "Pixmap": "PartDesign_Fillet",
           "ToolTip": "Rounds edges of components, in the assembly only."}


class ChamferCommand(_PanelCommand):
    KIND = "Chamfer"
    RES = {"MenuText": "Chamfer", "Pixmap": "PartDesign_Chamfer",
           "ToolTip": "Bevels edges of components, in the assembly only."}


COMMANDS = (("SWStyle_AsmHoleSeries", HoleSeriesCommand), ("SWStyle_AsmHoleWizard", HoleWizardCommand), ("SWStyle_AsmSimpleHole", SimpleHoleCommand), ("SWStyle_AsmExtrudedCut", ExtrudedCutCommand),
            ("SWStyle_AsmRevolvedCut", RevolvedCutCommand), ("SWStyle_AsmSweptCut", SweptCutCommand),
            ("SWStyle_AsmFillet", FilletCommand),
            ("SWStyle_AsmChamfer", ChamferCommand), ("SWStyle_AsmWeldBead", WeldBeadCommand),
            ("SWStyle_AsmBeltChain", BeltChainCommand))
CATALOG = (("AsmHoleSeries", "Hole Series", "SWStyle_AsmHoleSeries", "FEATURES_HOLE_SERIES",
            "One hole through a stack of parts: the head in the first, clearance in the middle, tapped in the last."),
           ("AsmHoleWizard", "Hole Wizard", "SWStyle_AsmHoleWizard", "FEATURES_HOLE_WIZARD",
            "Holes from the Hole Wizard's types and sizes, through the components, in the assembly only."),
           ("AsmSimpleHole", "Simple Hole", "SWStyle_AsmSimpleHole", "FW_SimpleHole",
            "A round hole through the components from a picked flat face, in the assembly only."),
           ("AsmExtrudedCut", "Extruded Cut", "SWStyle_AsmExtrudedCut", "FEATURES_EXTRUDE_CUT",
            "Cuts the components with an extruded sketch, in the assembly only."),
           ("AsmRevolvedCut", "Revolved Cut", "SWStyle_AsmRevolvedCut", "FEATURES_REVOLVED_CUT",
            "Cuts the components by revolving a sketch about its centerline, in the assembly only."),
           ("AsmSweptCut", "Swept Cut", "SWStyle_AsmSweptCut", "FEATURES_SWEPT_CUT",
            "Cuts the components with a profile swept along a path, in the assembly only."),
           ("AsmFillet", "Fillet", "SWStyle_AsmFillet", "FEATURES_FILLET", "Rounds edges of components, in the assembly only."),
           ("AsmChamfer", "Chamfer", "SWStyle_AsmChamfer", "FEATURES_CHAMFER", "Bevels edges of components, in the assembly only."),
           ("AsmWeldBead", "Weld Bead", "SWStyle_AsmWeldBead", "WELDMENTS_WELD_BEAD",
            "A weld bead where the Weld From faces meet the Weld To faces."),
           ("AsmBeltChain", "Belt/Chain", "SWStyle_AsmBeltChain", "ASSEMBLIES_BELT_CHAIN",
            "A belt or chain round the pulleys picked; Engage belt makes them turn together."))


try:    # before any mate exists: FreeCAD keeps a proxy's methods as they were when it was made
    _hush()
except Exception as _fw_err:
    _fw_log("asmfeature.py:3593", _fw_err)


try:    # Insert > Assembly Feature > Linear / Circular Pattern, Mirror, Table / Sketch Driven Pattern
    from . import asmfpattern as _fpattern
    _fpattern.install()
    COMMANDS = COMMANDS + _fpattern.COMMANDS
    CATALOG = CATALOG + _fpattern.CATALOG
except Exception as _error:
    App.Console.PrintWarning("FreeCAD: assembly feature patterns: %s\n" % _error)


try:    # Weld Bead: the part Weld Bead PM's controls (paths, intermittent, other side, symbol, smart selection)
    from . import asmweld as _weld
    _weld.install()
except Exception as _error:
    App.Console.PrintWarning("FreeCAD: assembly weld bead: %s\n" % _error)
