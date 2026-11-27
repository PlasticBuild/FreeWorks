# SPDX-License-Identifier: LGPL-2.1-or-later
""





import math
import re

import FreeCAD as App
import Part

from . import simplefeature as sf
from .simplefeature import Field

V = App.Vector
TINY = 1e-3      # overlap so new solids fuse with the part instead of touching it


def _normal(face, point):
    u, v = face.Surface.parameter(point)
    return face.normalAt(u, v).normalize()


def _flat_face(obj, name):
    picked = sf.elements(obj, name)
    if not picked:
        return None
    face = picked[0][1]
    if face.ShapeType != "Face" or not isinstance(face.Surface, Part.Plane):
        raise RuntimeError("Pick a flat face")
    return face


def _pick_props(obj):
    if "PickPoint" not in obj.PropertiesList:
        obj.addProperty("App::PropertyVectorList", "PickPoint", "Position",
                        "Where the face was clicked: the feature stands there when no point or edge is picked")
        obj.setEditorMode("PickPoint", 2)


def set_pick(obj, point):
    ""
    _pick_props(obj)
    obj.PickPoint = [V(point)] if point is not None else []


def _clicked(obj, face):
    """The click on the face, put onto its plane, or None (not clicked, or off the face now)."""
    for p in list(getattr(obj, "PickPoint", []) or [])[:1]:
        plane = face.Surface
        q = plane.value(*plane.parameter(p))
        if face.isInside(q, 1e-4, True):
            return q
    return None


def _point(obj, name, face):
    """The picked vertex or circular edge's centre, put onto face; else where the face was clicked;
    else the face's centre."""
    picked = sf.elements(obj, name)
    point = _clicked(obj, face) or face.CenterOfMass
    if picked:
        shape = picked[0][1]
        if shape.ShapeType == "Vertex":
            point = shape.Point
        elif shape.ShapeType == "Edge" and hasattr(shape.Curve, "Center"):
            point = shape.Curve.Center
        elif shape.ShapeType == "Edge":
            point = shape.CenterOfMass
    plane = face.Surface
    return plane.value(*plane.parameter(point))


def _frame(origin, z, x=None):
    """A placement at origin with local Z along z and local X along x (made square to z)."""
    z = V(z).normalize()
    if x is None or abs(V(x).normalize().dot(z)) > 0.999:
        x = V(1, 0, 0) if abs(z.x) < 0.9 else V(0, 1, 0)
    x = V(x) - z * V(x).dot(z)
    x.normalize()
    y = z.cross(x)
    m = App.Matrix(x.x, y.x, z.x, origin.x, x.y, y.y, z.y, origin.y, x.z, y.z, z.z, origin.z, 0, 0, 0, 1)
    return App.Placement(m)


def _xaxis(face):
    try:
        return face.Surface.Rotation.multVec(V(1, 0, 0))
    except Exception:
        return None


def _direction(obj, name):
    picked = sf.elements(obj, name)
    if not picked:
        return None
    shape = picked[0][1]
    if shape.ShapeType == "Edge":
        a, b = shape.Vertexes[0].Point, shape.Vertexes[-1].Point
        return b - a if (b - a).Length > 1e-9 else None
    if shape.ShapeType == "Face":
        return _normal(shape, shape.CenterOfMass)
    return None


def _prism(points, depth):
    """A prism from a closed polygon in local XZ, depth along local Y, centred on Y = 0."""
    wire = Part.makePolygon([V(x, -depth / 2.0, z) for x, z in points] + [V(points[0][0], -depth / 2.0, points[0][1])])
    return Part.Face(wire).extrude(V(0, depth, 0))


class PointPanel(sf.Panel):
    ""


    def addSelection(self, doc, name, sub, point):
        try:
            self._fw_point = V(*point) if point else None
        except Exception:
            self._fw_point = None
        return super().addSelection(doc, name, sub, point)

    def _picked(self, doc_name, name, sub):
        field = self.active
        before = list(getattr(self.obj, "Face", None) or [])
        super()._picked(doc_name, name, sub)
        if field != "Face" or not sub.split(".")[-1].startswith("Face"):
            return
        now = list(getattr(self.obj, "Face", None) or [])
        if now != before:
            set_pick(self.obj, getattr(self, "_fw_point", None) if now else None)
            try:
                self._changed()
            except Exception:
                self.obj.Document.recompute()


def _preselected_point():
    """Where a face picked before the command was clicked (global), or None."""
    try:
        import FreeCADGui as Gui
        for sel in Gui.Selection.getSelectionEx("", 0):
            for sub, p in zip(sel.SubElementNames, sel.PickedPoints):
                if sub.split(".")[-1].startswith("Face"):
                    return V(p)
    except Exception:
        return None
    return None


class PointCommand(sf.Command):
    """The command as simplefeature's, keeping where a face picked before it was clicked."""

    def Activated(self):
        point = _preselected_point()
        obj = sf.make(self.spec, picks=sf.preselected(self.spec))
        if obj is not None and point is not None and sf.elements(obj, "Face"):
            set_pick(obj, point)
            obj.Document.recompute()


# --------------------------------------------------------------------------- Mounting Boss
def _boss_shapes(obj):
    face = _flat_face(obj, "Face")
    if face is None:
        return None, None, None
    center = _point(obj, "Position", face)
    normal = _normal(face, center)
    if obj.Reverse:
        normal = normal * -1
    place = _frame(center, normal, _xaxis(face))
    height, radius = float(obj.Height), float(obj.Diameter) / 2.0
    if height <= 0 or radius <= 0:
        raise RuntimeError("Mounting Boss height and diameter must be more than 0")
    top = max(radius - height * math.tan(math.radians(float(obj.DraftAngle))), radius * 0.05)
    add = Part.makeCone(radius, top, height + TINY, V(0, 0, -TINY), V(0, 0, 1)) if top != radius else \
        Part.makeCylinder(radius, height + TINY, V(0, 0, -TINY), V(0, 0, 1))
    count = int(obj.Fins)
    if count > 0 and float(obj.FinLength) > 0 and float(obj.FinThickness) > 0:
        fin_height = min(float(obj.FinHeight), height) if float(obj.FinHeight) > 0 else height
        inner = top * 0.5 + radius * 0.5 - 0.1 * radius
        fin = _prism([(inner, -TINY), (radius + float(obj.FinLength), -TINY), (inner, fin_height)],
                     float(obj.FinThickness))
        for i in range(count):
            copy = fin.copy()
            copy.rotate(V(0, 0, 0), V(0, 0, 1), 360.0 * i / count)
            add = add.fuse(copy)
    cut = None
    hole_d, hole_depth = float(obj.HoleDiameter), float(obj.HoleDepth)
    if hole_d > 0 and hole_depth > 0:
        if hole_d >= 2 * top:
            raise RuntimeError("The hole or pin diameter must be less than the boss diameter")
        if obj.BossType == "Pin":
            add = add.fuse(Part.makeCylinder(hole_d / 2.0, hole_depth + TINY, V(0, 0, height - TINY), V(0, 0, 1)))
        else:
            cut = Part.makeCylinder(hole_d / 2.0, hole_depth + TINY, V(0, 0, height - hole_depth), V(0, 0, 1))
    add = add.removeSplitter()
    add.Placement = place
    if cut is not None:
        cut.Placement = place
    return add, cut, place


def _mounting_boss(obj, base):
    add, cut, _ = _boss_shapes(obj)
    if add is None:
        return None, None
    result = base.fuse(add, 1e-6) if base is not None and not base.isNull() else add
    if cut is not None:
        result = result.cut(cut)
        add = add.cut(cut)
    return result, add


MOUNTING_BOSS = sf.Spec(
    "SWStyle_MountingBoss", "Mounting Boss", "Mounting Boss",
    "A boss for a screw or a pin, with fins, on a flat face.", "FEATURES_MOUNTING_BOSS", "PartDesign_AdditiveCylinder",
    [Field("Face", "pick", "Face to put the boss on", tip="A flat face", what=("Face",), box="Position"),
     Field("Reverse", "bool", "Reverse direction", False, box="Position", flip=True),
     Field("Position", "pick", "Circular edge or point for the boss center", what=("Edge", "Vertex"), optional=True,
           tip="The boss center: a circular edge's center or a point (the face's center when empty)", box="Position"),
     Field("BossType", "radio", "Boss type", "Hole", values=["Hole", "Pin"],
           tip="Hole: a hole down the boss for a screw. Pin: a pin on top of the boss", box="Boss Type"),
     Field("Height", "length", "Boss height", 10.0, box="Boss"),
     Field("Diameter", "length", "Boss diameter", 8.0, box="Boss"),
     Field("DraftAngle", "angle", "Draft angle", 0.0, low=0.0, high=30.0, box="Boss"),
     Field("HoleDiameter", "length", "Hole / pin diameter", 3.0, box="Boss"),
     Field("HoleDepth", "length", "Hole depth / pin height", 8.0, box="Boss"),
     Field("Fins", "int", "Number of fins", 4, low=0, high=12, box="Fins"),
     Field("FinHeight", "length", "Fin height", 6.0, shown=lambda obj: obj.Fins > 0, box="Fins"),
     Field("FinLength", "length", "Fin length", 4.0, shown=lambda obj: obj.Fins > 0, box="Fins"),
     Field("FinThickness", "length", "Fin thickness", 1.0, shown=lambda obj: obj.Fins > 0, box="Fins")],
    _mounting_boss, panel=PointPanel)


# --------------------------------------------------------------------------- Snap Hook
def _hook_shapes(obj):
    """(beam, lip, placement) of a Snap Hook in global coordinates, or (None, None, None)."""
    face = _flat_face(obj, "Face")
    if face is None:
        return None, None, None
    origin = _point(obj, "Position", face)
    normal = _normal(face, origin)
    lip_dir = _direction(obj, "Direction")
    if lip_dir is None:
        lip_dir = _xaxis(face)
    place = _frame(origin, normal, lip_dir)
    height, thick, width = float(obj.Height), float(obj.Thickness), float(obj.Width)
    over, lip_h = float(obj.LipDepth), float(obj.LipHeight)
    if min(height, thick, width) <= 0:
        raise RuntimeError("Snap Hook height, thickness and width must be more than 0")
    if lip_h >= height:
        raise RuntimeError("The lip must be shorter than the hook")
    sign = -1.0 if obj.FlipLip else 1.0
    beam = Part.makeBox(thick, width, height + TINY, V(-thick / 2.0, -width / 2.0, -TINY))
    lip = None
    if over > 0 and lip_h > 0:
        x0 = sign * thick / 4.0
        x1 = sign * (thick / 2.0 + over)
        pts = [(x0, height - lip_h), (x1, height - lip_h), (sign * thick / 2.0, height), (x0, height)]
        if sign < 0:
            pts.reverse()
        lip = _prism(pts, width)
        lip.Placement = place
    beam.Placement = place
    return beam, lip, place


def _snap_hook(obj, base):
    beam, lip, _ = _hook_shapes(obj)
    if beam is None:
        return None, None
    tool = beam.fuse(lip).removeSplitter() if lip is not None else beam
    result = base.fuse(tool, 1e-6) if base is not None and not base.isNull() else tool
    return result, tool


SNAP_HOOK = sf.Spec(
    "SWStyle_SnapHook", "Snap Hook", "Snap Hook", "A flexible hook with a catch lip, on a flat face.",
    "FEATURES_SNAP_HOOK", "PartDesign_AdditiveBox",
    [Field("Face", "pick", "Face for the hook's base", tip="A flat face", what=("Face",), box="Selections"),
     Field("Position", "pick", "Point or edge for the hook position", what=("Vertex", "Edge"), optional=True,
           tip="Where the hook stands (the face's center when empty)", box="Selections"),
     Field("Direction", "pick", "Direction of the hook's lip", what=("Edge", "Face"), optional=True,
           tip="An edge or a face the lip points along (the face's own X direction when empty)", box="Selections"),
     Field("FlipLip", "bool", "Flip lip", False, box="Selections", flip=True),
     Field("Height", "length", "Total height", 12.0, box="Hook Data"),
     Field("Thickness", "length", "Hook thickness", 1.5, box="Hook Data"),
     Field("Width", "length", "Hook width", 5.0, box="Hook Data"),
     Field("LipDepth", "length", "Lip overhang", 1.2, box="Hook Lip Data"),
     Field("LipHeight", "length", "Lip height", 2.5, box="Hook Lip Data")],
    _snap_hook, panel=PointPanel)


# --------------------------------------------------------------------------- Snap Hook Groove
def _is_hook(o):
    return o is not None and getattr(o, "SWStyleKind", "") == SNAP_HOOK.internal


def _hook_in(o):
    """The Snap Hook a pick stands for: the feature itself, or the one Snap Hook in a picked body."""
    if _is_hook(o):
        return o
    if o is not None and o.TypeId == "PartDesign::Body":
        hooks = [g for g in o.Group if _is_hook(g)]
        if len(hooks) == 1:
            return hooks[0]
    return None


class GroovePanel(sf.Panel):
    ""


    def _picked(self, doc_name, name, sub):
        field = self.active
        was = getattr(self.obj, "Hook", None)
        super()._picked(doc_name, name, sub)
        if field != "Hook":
            return
        doc = self.obj.Document
        picked = [doc.getObject(name)] + [doc.getObject(p) for p in sub.split(".")[:-1]]
        hook = next((o for o in reversed(picked) if _is_hook(o)), None)
        if hook is None and self.obj.Hook is not None and not _is_hook(self.obj.Hook):
            hook = _hook_in(self.obj.Hook)
        if hook is not None and hook is was:
            hook = None             # the same hook picked again comes out of the box
            if self.obj.Hook is None:
                return
        if self.obj.Hook is not hook and (hook is not None or was is not None):
            self.obj.Hook = hook
            try:
                self._changed()
            except Exception:
                self.obj.Document.recompute()


def _hook_groove(obj, base):
    hook = _hook_in(obj.Hook) or obj.Hook
    if hook is None:
        return None, None
    if getattr(hook, "SWStyleKind", "") != SNAP_HOOK.internal:
        raise RuntimeError("Pick a Snap Hook feature")
    beam, lip, place = _hook_shapes(hook)
    if beam is None:
        raise RuntimeError("The Snap Hook has no face")
    gap = max(float(obj.Gap), 0.0)
    tool = lip if lip is not None else beam
    if obj.WholeHook and lip is not None:
        tool = beam.fuse(lip)
    # the groove is the hook's (or lip's) box in the hook's own axes, grown by the gap
    local = tool.transformed(place.inverse().toMatrix())
    bb = local.BoundBox
    tool = Part.makeBox(bb.XLength + 2 * gap, bb.YLength + 2 * gap, bb.ZLength + 2 * gap,
                        V(bb.XMin - gap, bb.YMin - gap, bb.ZMin - gap))
    tool.Placement = place
    if base is None or base.isNull():
        raise RuntimeError("Snap Hook Groove needs a part to cut")
    common = base.common(tool)
    if common.isNull() or common.Volume < 1e-9:
        raise RuntimeError("The snap hook does not reach this part")
    return base.cut(tool), common


SNAP_HOOK_GROOVE = sf.Spec(
    "SWStyle_SnapHookGroove", "Snap Hook Groove", "Snap Hook Groove",
    "Cuts the groove a snap hook catches in, with a gap.", "FEATURES_SNAP_HOOK_GROOVE", "PartDesign_SubtractiveBox",
    [Field("Hook", "pick", "Snap Hook feature", tip="The Snap Hook (in another body) that catches here",
           what="Object", box="Feature and Body Selection"),
     Field("Gap", "length", "Gap", 0.2, box="Groove Data"),
     Field("WholeHook", "bool", "Clear the whole hook", False, box="Groove Data")],
    _hook_groove, subtractive=True, panel=GroovePanel)


# --------------------------------------------------------------------------- Lip/Groove
def _band(face, width, inside):
    """The strip of face, width wide, along its outer edge (or along its holes when inside)."""
    outer = Part.Face(face.OuterWire)
    holes = [w for w in face.Wires if not w.isSame(face.OuterWire)]
    if inside and holes:
        band = None
        for wire in holes:
            hole = Part.Face(wire)
            ring = hole.makeOffset2D(width, 0, False, False, False).cut(hole)
            band = ring if band is None else band.fuse(ring)
    else:
        band = outer.cut(outer.makeOffset2D(-width, 0, False, False, False))
    band = band.common(face)
    if band.isNull() or band.Area < 1e-9:
        raise RuntimeError("The lip or groove width does not fit the face")
    return band


def _name_side(obj, groove):
    """A Lip/Groove still carrying the other side's automatic name (Lip2 set to Groove) takes its own."""
    word, other = ("Groove", "Lip") if groove else ("Lip", "Groove")
    if re.match(r"^%s\d+$" % other, obj.Label or "") and obj.Document is not None:
        from . import naming
        obj.Label = naming.next_label(obj.Document, word)


def _body(obj):
    try:
        return obj.getParentGeoFeatureGroup() if obj is not None else None
    except Exception:
        return None


def _tools(picked, width, height, inside, groove):
    tools = []
    for _, face in picked:
        if face.ShapeType != "Face" or not isinstance(face.Surface, Part.Plane):
            raise RuntimeError("Lip/Groove needs flat faces (the top of a wall)")
        normal = _normal(face, face.CenterOfMass)
        for band in _band(face, width, inside).Faces:
            if groove:
                tools.append(band.extrude(normal * -height))
            else:
                start = band.copy()
                start.translate(normal * -TINY)
                tools.append(start.extrude(normal * (height + TINY)))
    return tools[0] if len(tools) == 1 else tools[0].fuse(tools[1:])


def _own_lip_faces(obj):
    """The Lip Selection faces on this feature's own body (the others are made by that body's lip)."""
    if "LipFaces" not in obj.PropertiesList:
        return []
    mine = _body(obj)
    return [(o, f) for o, f in sf.elements(obj, "LipFaces") if _body(o) is mine]


def _lip_groove(obj, base):
    groove = obj.Type == "Groove"
    picked = sf.elements(obj, "Faces")
    lips = _own_lip_faces(obj)
    _name_side(obj, groove and bool(picked or not lips))
    if not picked and not lips:
        return None, None
    width, height, gap = float(obj.Width), float(obj.Height), float(obj.Gap)
    if width <= 0 or height <= 0:
        raise RuntimeError("Lip/Groove width and height must be more than 0")
    inside = obj.Side == "Inside"
    out, made = base, []
    if picked:
        tool = _tools(picked, width + gap if groove else width, height + gap if groove else height, inside, groove)
        if groove:
            made.append(tool.common(base))
            out = base.cut(tool)
        else:
            made.append(tool)
            out = base.fuse(tool, 1e-6)
    if lips:
        tool = _tools(lips, width, height, inside, False)
        made.append(tool)
        out = out.fuse(tool, 1e-6)
    return out, (made[0] if len(made) == 1 else Part.makeCompound(made))


def _master_of(lip):
    """The Lip/Groove whose Lip Selection made this lip (None for a lip of its own)."""
    return getattr(lip, "LipGrooveOf", None) if "LipGrooveOf" in getattr(lip, "PropertiesList", ()) else None


def _lips_of(master):
    """The lips this Lip/Groove made on other bodies. Only the lip links to it: a link from the groove
    into the other body would make that body and this one depend on each other."""
    out = []
    for o in master.InList:            # InList names a lip once per link (expressions, LipGrooveOf)
        if _master_of(o) is master and o not in out:
            out.append(o)
    return out


def _lip_bodies(obj):
    """{body: [(object, sub)]} of the Lip Selection picks on other bodies than the feature's."""
    out = {}
    if "LipFaces" not in obj.PropertiesList:
        return out
    mine = _body(obj)
    lips = _lips_of(obj)
    for source, subs in obj.LipFaces or []:
        body = _body(source)
        if body is None or body is mine:
            continue
        for sub in (subs if isinstance(subs, (list, tuple)) else [subs]):
            if source in lips:
                # a face picked on the lip this feature made: the same face before the lip
                mapped = sf.base_element(source, sub)
                if mapped is None:
                    App.Console.PrintWarning("Lip/Groove: pick the lip's wall face again\n")
                    continue
                source, sub = source.BaseFeature, mapped
            if (source, sub) not in out.get(body, []):
                out.setdefault(body, []).append((source, sub))
    return out


PARAMS = ("Width", "Height", "Gap")


def _bind(lip, master):
    for prop in PARAMS:
        try:
            lip.setExpression(prop, "%s.%s" % (master.Name, prop))
        except Exception as err:
            App.Console.PrintLog("FreeCAD: lip/groove bind %s: %r\n" % (prop, err))
            setattr(lip, prop, getattr(master, prop))
    if lip.Side != master.Side:
        lip.Side = master.Side


def open_lips(master):
    """The page opens on a Lip/Groove: its lips' faces come back into its Lip Selection, and the lips
    stop following it while it is edited (they would depend on each other through the picks)."""
    lips = _lips_of(master)
    if not lips or "LipFaces" not in master.PropertiesList:
        return
    picks = list(master.LipFaces or [])
    for lip in lips:
        for prop in PARAMS:
            try:
                lip.setExpression(prop, None)
            except Exception as err:
                App.Console.PrintLog("FreeCAD: lip/groove unbind %s: %r\n" % (prop, err))
        lip.LipGrooveOf = None
        if "LipGrooveWas" not in lip.PropertiesList:
            lip.addProperty("App::PropertyString", "LipGrooveWas", "Lip/Groove", "The Lip/Groove being edited")
            lip.setEditorMode("LipGrooveWas", 2)
        lip.LipGrooveWas = master.Name
        for source, subs in lip.Faces or []:
            picks.append((source, subs))
    master.LipFaces = picks
    master.Document.recompute()


def _edited_lips(master):
    """The lips open_lips set loose for this edit."""
    return [o for o in master.Document.Objects if getattr(o, "LipGrooveWas", "") == master.Name
            and _master_of(o) is None and o.Type == "Lip"]


def sync_lips(master):
    ""


    doc = master.Document
    from . import naming
    wanted = _lip_bodies(master) if _master_of(master) is None else {}
    mine = _body(master)
    # the other bodies' picks go to their lips: this feature keeps only its own body's
    own = [(o, subs) for o, subs in (master.LipFaces or []) if _body(o) is mine]
    if len(own) != len(master.LipFaces or []):
        master.LipFaces = own
    keep = []
    for lip in _lips_of(master) + _edited_lips(master):
        body = _body(lip)
        if body in wanted:
            lip.Faces = [(o, [sub]) for o, sub in wanted.pop(body)]
            keep.append(lip)
        else:
            try:
                if body is not None:
                    body.removeObject(lip)
                doc.removeObject(lip.Name)
            except Exception as err:
                App.Console.PrintLog("FreeCAD: lip/groove drop: %r\n" % (err,))
    for body, picks in wanted.items():
        lip = body.newObject(LIP_GROOVE.type, LIP_GROOVE.internal)
        sf.Feature(lip, LIP_GROOVE)
        if App.GuiUp:
            try:
                sf.View(lip.ViewObject)
            except Exception as err:
                App.Console.PrintLog("FreeCAD: lip/groove view: %r\n" % (err,))
        lip.Type = "Lip"
        lip.Label = naming.next_label(doc, "Lip")
        lip.Faces = [(o, [sub]) for o, sub in picks]
        keep.append(lip)
    for lip in keep:
        if "LipGrooveOf" not in lip.PropertiesList:
            lip.addProperty("App::PropertyLinkGlobal", "LipGrooveOf", "Lip/Groove", "The Lip/Groove that made this lip")
            lip.setEditorMode("LipGrooveOf", 2)
        lip.LipGrooveOf = master
        if "LipGrooveWas" in lip.PropertiesList:
            lip.LipGrooveWas = ""
        _bind(lip, master)
    doc.recompute()
    return keep


try:
    _PanelBase = sf.Panel
except AttributeError:
    _PanelBase = None


if _PanelBase is not None:
    class LipGroovePanel(_PanelBase):
        """The page also makes the lips on the other bodies before OK closes it."""

        def __init__(self, obj, *args, **kwargs):
            super().__init__(obj, *args, **kwargs)
            try:
                open_lips(obj)
                self._show()
            except Exception as err:
                App.Console.PrintLog("FreeCAD: lip/groove open: %r\n" % (err,))

        def accept(self):
            obj = self.obj
            if not obj.Faces and not ("LipFaces" in obj.PropertiesList and obj.LipFaces):
                self.error.setText("Pick: the faces for the groove or the lip")
                self.error.setVisible(True)
                return False
            try:
                lips = sync_lips(obj)
            except Exception as err:
                self.error.setText("The lip could not be made: %s" % err)
                self.error.setVisible(True)
                return False
            bad = [l for l in lips if "Invalid" in l.State]
            if bad:
                self.error.setText("%s: %s" % (bad[0].Label, bad[0].getStatusString()))
                self.error.setVisible(True)
                return False
            return super().accept()
else:
    LipGroovePanel = None


LIP_GROOVE = sf.Spec(
    "SWStyle_LipGroove", "Lip/Groove", "Groove",
    "A groove along the top of a wall and the matching lip on the mating body, for parts that close together.",
    "FEATURES_LIP_GROOVE", "PartDesign_Thickness",
    [Field("Faces", "pick", "Faces for the groove", tip="Flat faces on top of the wall that gets the groove",
           what=("Face",), many=True, box="Groove Selection", optional=True),
     Field("LipFaces", "pick", "Faces for the lip",
           tip="Flat faces on top of the mating wall (this body or another one) that gets the lip",
           what=("Face",), many=True, box="Lip Selection", optional=True),
     # Type stays a property (the lip made for another body, and older parts' lips, whose Faces are the
     # lip's); the page shows it only on an older lip of its own
     Field("Type", "radio", "Lip or groove", "Groove", values=["Lip", "Groove"], box="Parameters",
           shown=lambda obj: obj.Type == "Lip" and _master_of(obj) is None),
     Field("Side", "radio", "Side of the wall", "Inside", values=["Inside", "Outside"], box="Parameters"),
     Field("Width", "length", "Width", 1.0, box="Parameters"),
     Field("Height", "length", "Height", 1.5, box="Parameters"),
     Field("Gap", "length", "Gap", 0.1, shown=lambda obj: obj.Type == "Groove", box="Parameters")],
    _lip_groove, panel=LipGroovePanel)


ALL = [MOUNTING_BOSS, SNAP_HOOK, SNAP_HOOK_GROOVE, LIP_GROOVE]


def register():
    import FreeCADGui as Gui
    for spec in (MOUNTING_BOSS, SNAP_HOOK):
        try:
            if spec.command not in Gui.listCommands():
                Gui.addCommand(spec.command, PointCommand(spec))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s command not added (%s)\n" % (spec.title, error))
    for spec in ALL:
        sf.register(spec)
