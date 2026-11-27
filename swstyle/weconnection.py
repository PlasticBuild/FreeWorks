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

import itertools
import json
import math
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import naming, wemember, wetrim
from . import pmboxes

DEFINE_COMMAND = "SWStyle_WEDefineConnection"
INSERT_COMMAND = "SWStyle_WEInsertConnection"
PATTERN_COMMAND = "SWStyle_WEPatternConnection"
DEFINE_TITLE = "Connection Definition"
INSERT_TITLE = "Insert Connection Element"
PATTERN_TITLE = "Pattern Connection Element"
DEFINITION_LABEL = "Connection Definition"
ELEMENT_LABEL = "Connection Element"
PATTERN_LABEL = "Connection Element Pattern"
GROUP = "Connection Element"
FOLDER = "Structure System - Connection Elements"
PLACEMENTS = ("Generic Connection", "End Connection")
MATES = ("Coincident", "Concentric", "Parallel")
REFERENCES = ("Primary Reference", "Secondary Reference", "Tertiary Reference")
PLANES = ("App::Plane", "PartDesign::Plane", "Part::DatumPlane")
LINES = ("App::Line", "PartDesign::Line", "Part::DatumLine")
DEFAULT_SIZE = "Default"
V = App.Vector
TOL = 1e-6

NO_ORIGIN = "The three planes must meet at one point: it is the connection element's origin."
EXTERNAL = "A part with links to other documents can't hold a connection definition: break them first."
NOT_PLANAR = "The primary reference must be a flat face or a plane."
NO_SIMILAR = "No similar corners found."
NOT_AT_CORNER = "Select a connection element inserted at a corner."
OPEN_ELSEWHERE = "The connection element is open in another window. Close it before you insert it."
NONE_FOUND = "No connection elements found. Define one first."


def _weicon(name, key=None):
    from . import weprofile
    return weprofile.icon(name, key)

def _load(text, default):
    try:
        return json.loads(text or "")
    except Exception:
        return default


def _v(x):
    return V(*x)


def _l(v):
    return [v.x, v.y, v.z]


def _kind(obj):
    return type(getattr(obj, "Proxy", None)).__name__


def library():
    """The Structure System - Connection Elements folder."""
    p = App.ParamGet(wemember.PARAMS)
    folder = p.GetString("ConnectionElements", "")
    return folder or os.path.join(App.getUserAppDataDir(), "FreeWorks", FOLDER)


def standards():
    root = library()
    try:
        return sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    except OSError:
        return []


def types(standard):
    folder = os.path.join(library(), standard)
    try:
        return sorted(os.path.splitext(f)[0] for f in os.listdir(folder) if f.lower().endswith(".fcstd"))
    except OSError:
        return []


def element_path(standard, kind):
    return os.path.join(library(), standard, kind + ".FCStd")


# ================================================================ references
def geom_of(obj, sub=""):
    """The reference an object or sub-element stands for: {"kind": "plane", point, normal} or
    {"kind": "axis", point, dir}, with "center" (where it is, for a first guess)."""
    if not sub:
        pl = obj.getGlobalPlacement()
        z = pl.Rotation.multVec(V(0, 0, 1))
        if obj.TypeId in PLANES:
            return {"kind": "plane", "point": _l(pl.Base), "normal": _l(z), "center": _l(pl.Base)}
        if obj.TypeId in LINES:
            return {"kind": "axis", "point": _l(pl.Base), "dir": _l(z), "center": _l(pl.Base)}
        return None
    try:
        s = Part.getShape(obj, sub, needSubElement=True)
    except Exception as _fw_err:
        _fw_log("weconnection.py:150", _fw_err)
        return None
    return geom_of_shape(s)


def geom_of_shape(s):
    if s.ShapeType == "Face":
        surf = s.Surface
        c = s.CenterOfMass
        if surf.TypeId == "Part::GeomPlane":
            u0, u1, v0, v1 = s.ParameterRange
            n = s.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
            return {"kind": "plane", "point": _l(c), "normal": _l(n), "center": _l(c)}
        if surf.TypeId == "Part::GeomCylinder":
            d = V(surf.Axis).normalize()
            p = V(surf.Center)
            p = p + d * (c - p).dot(d)
            return {"kind": "axis", "point": _l(p), "dir": _l(d), "center": _l(p), "radius": surf.Radius}
        return None
    if s.ShapeType == "Edge":
        curve = s.Curve
        if curve.TypeId in ("Part::GeomCircle", "Part::GeomArcOfCircle") or hasattr(curve, "Radius"):
            try:
                d = V(curve.Axis).normalize()
                return {"kind": "axis", "point": _l(curve.Center), "dir": _l(d), "center": _l(curve.Center),
                        "radius": curve.Radius}
            except Exception:
                return None
        if curve.TypeId in ("Part::GeomLine", "Part::GeomLineSegment"):
            a, b = s.Vertexes[0].Point, s.Vertexes[-1].Point
            d = (b - a).normalize()
            m = (a + b) * 0.5
            return {"kind": "axis", "point": _l(m), "dir": _l(d), "center": _l(m)}
    return None


def target_item(obj, sub):
    """What is stored for a picked target: a member body's face (kept by its geometry, so a rebuilt member
    gives it back), or any face, edge or plane by name."""
    g = geom_of(obj, sub)
    if g is None:
        return None
    ref = wetrim.ref_of(obj) if sub.startswith("Face") else None
    if ref is not None:
        item = dict(g)
        item.update({"kind": "body", "ref": ref, "geom": g["kind"]})
        return item
    return {"kind": "face", "obj": obj.Name, "sub": sub}


def resolve(doc, item, source=None):
    """The geometry a target item stands for, on source (the member body's shape) for a member face."""
    if item is None:
        return None
    if item.get("kind") == "face":
        obj = doc.getObject(item.get("obj", ""))
        return geom_of(obj, item.get("sub", "")) if obj is not None else None
    body = source if source is not None else wetrim.current_tip(doc, item["ref"])
    if body is None or body.Shape.isNull():
        return None
    best, best_d = None, None
    p = _v(item["point"])
    for f in body.Shape.Faces:
        g = geom_of_shape(f)
        if g is None or g["kind"] != item.get("geom"):
            continue
        if g["kind"] == "plane":
            n = _v(item["normal"])
            if _v(g["normal"]).dot(n) < 1 - 1e-6:
                continue
            d = abs((_v(g["point"]) - p).dot(n)) * 1000 + (_v(g["center"]) - p).Length
        else:
            a = _v(item["dir"])
            if abs(abs(_v(g["dir"]).dot(a)) - 1) > 1e-6 or abs(g.get("radius", 0) - item.get("radius", 0)) > 1e-6:
                continue
            w = _v(g["point"]) - p
            d = (w - a * w.dot(a)).Length * 1000 + abs(w.dot(a))
        if best_d is None or d < best_d:
            best, best_d = g, d
    return best


# ================================================================ placement
def _rot_about(axis, a, b):
    """The angle (degrees) about axis turning a onto b, both projected square to axis; None when either has
    no part square to it."""
    a = a - axis * a.dot(axis)
    b = b - axis * b.dot(axis)
    if a.Length < 1e-6 or b.Length < 1e-6:
        return None
    return math.degrees(math.atan2(axis.dot(a.cross(b)), a.dot(b)))


def _meet(planes):
    """The point where three planes meet, else None."""
    if len(planes) != 3:
        return None
    n = [_v(p["normal"]) for p in planes]
    det = n[0].dot(n[1].cross(n[2]))
    if abs(det) < 1e-6:
        return None
    d = [n[k].dot(_v(planes[k]["point"])) for k in range(3)]
    return (n[1].cross(n[2]) * d[0] + n[2].cross(n[0]) * d[1] + n[0].cross(n[1]) * d[2]) * (1.0 / det)


def origin_of(refs):
    """The element's origin: where its three planes meet, else its primary reference's centre."""
    planes = [r for r in refs if r and r["kind"] == "plane"]
    p = _meet(planes) if len(planes) == 3 else None
    if p is not None:
        return p
    return _v(refs[0]["center"]) if refs and refs[0] else V()


def _want(r, t, mate, flip, current):
    """The direction the element's reference must take: a plane's normal against the target's (face to face),
    an axis along the target's (the nearer way); Flip alignment reverses it."""
    if r["kind"] == "plane":
        d = _v(t["normal"]) * -1.0
    else:
        d = _v(t["dir"])
        if current is not None and current.dot(d) < 0:
            d = d * -1.0
    return d * -1.0 if flip else d


def solve(refs, targets, mates, flips, offsets):
    """The Placement taking an element (its references refs, in its own coordinates) onto targets.
    mates: Coincident for the primary reference, then the secondary and tertiary ones' mates."""
    import numpy as np
    pairs = [(r, t, m, f, o) for r, t, m, f, o in zip(refs, targets, mates, flips, offsets) if r and t]
    if not pairs:
        return App.Placement()
    r0, t0, _m0, f0, _o0 = pairs[0]
    if r0["kind"] != "plane" or t0["kind"] != "plane":
        raise ValueError(NOT_PLANAR)
    w0 = _want(r0, t0, "Coincident", f0, None)
    rot = App.Rotation(_v(r0["normal"]), w0)
    for r, t, m, f, _o in pairs[1:]:
        if r["kind"] != t["kind"]:
            raise ValueError("%s: a %s can't be %s to a %s" % (m, r["kind"], m.lower(), t["kind"]))
        e = rot.multVec(_v(r["normal"] if r["kind"] == "plane" else r["dir"]))
        want = _want(r, t, m, f, e)
        ang = _rot_about(w0, e, want)
        if ang is not None and abs(abs(e.dot(w0)) - 1) > 1e-6:
            rot = App.Rotation(w0, ang).multiply(rot)
            break
    rows, rhs = [], []
    for r, t, m, f, o in pairs:
        pe = rot.multVec(_v(r["point"]))
        pt = _v(t["point"])
        if r["kind"] == "plane" and m == "Coincident":
            n = _v(t["normal"])
            rows.append(_l(n))
            rhs.append(n.dot(pt - pe) + float(o))
        elif r["kind"] == "axis" and m == "Concentric":
            d = _v(t["dir"])
            u = d.cross(V(1, 0, 0)) if abs(d.x) < 0.9 else d.cross(V(0, 1, 0))
            u.normalize()
            w = d.cross(u)
            for k in (u, w):
                rows.append(_l(k))
                rhs.append(k.dot(pt - pe))
        elif m == "Parallel" and r["kind"] == "plane" and abs(float(o)) > TOL:
            n = _v(t["normal"])
            rows.append(_l(n))
            rhs.append(n.dot(pt - pe) + float(o))
    # what the mates leave free: the element's origin goes where the targets meet (else onto the primary's)
    goal = (origin_of(targets) if all(targets) else _v(t0["center"])) - rot.multVec(origin_of(refs))
    g = np.array(_l(goal))
    if rows:
        a = np.array(rows)
        b = np.array(rhs)
        pinv = np.linalg.pinv(a)
        t1 = pinv.dot(b)
        free = np.eye(3) - pinv.dot(a)
        t = t1 + free.dot(g - t1)
    else:
        t = g
    return App.Placement(V(*[float(x) for x in t]), rot)


def end_solve(ref, end_face, base, end, flip, offset):
    """End Connection: the element's primary face on the member's end face, its origin on the member's path
    and its X axis along the profile's."""
    t = geom_of_shape(end_face)
    if t is None or t["kind"] != "plane" or ref is None or ref["kind"] != "plane":
        raise ValueError(NOT_PLANAR)
    nt = _v(t["normal"])
    want = nt * (1.0 if flip else -1.0)
    rot = App.Rotation(_v(ref["normal"]), want)
    px = base.Placement.Rotation.multVec(V(1, 0, 0))
    ang = _rot_about(want, rot.multVec(V(1, 0, 0)), px)
    if ang is not None:
        rot = App.Rotation(want, ang).multiply(rot)
    p0, p1 = wetrim.line_of(base)
    tip = p1 if end == 1 else p0
    tip = tip + nt * (_v(t["point"]) - tip).dot(nt)
    ne, pe = _v(ref["normal"]), _v(ref["point"])
    o = V() - ne * ne.dot(V() - pe)            # the element's origin, on its primary face's plane
    return App.Placement(tip - rot.multVec(o) + nt * float(offset), rot)


# ================================================================ the element's part
def _external(doc):
    for o in doc.Objects:
        for x in o.OutList:
            if x.Document is not doc:
                return True
        if o.TypeId == "App::Link" and getattr(o, "LinkedObject", None) is not None:
            if o.LinkedObject.Document is not doc:
                return True
    return False


def _solids(doc):
    """The part's visible solids, each body once."""
    out = []
    for o in doc.Objects:
        if _kind(o) == "ConnectionDefinition" or not hasattr(o, "Shape") or not getattr(o, "Visibility", True):
            continue
        if any(p.TypeId == "PartDesign::Body" for p in o.InList):
            continue
        if any(hasattr(p, "Shape") and p.TypeId not in ("App::Part", "App::DocumentObjectGroup")
               and o in getattr(p, "OutList", []) and p.Visibility for p in o.InList):
            continue
        try:
            s = o.Shape
        except Exception:
            continue
        if s.isNull() or not s.Solids:
            continue
        out.extend(s.Solids)
    return out


def tool_of(feature):
    """What a propagated feature cuts: a PartDesign cut's removed volume, a Part Cut's tool."""
    sub = getattr(feature, "AddSubShape", None)
    if sub is not None and not sub.isNull():
        s = sub.copy()
        body = next((p for p in feature.InList if p.TypeId == "PartDesign::Body"), None)
        if body is not None:
            s.Placement = body.getGlobalPlacement().multiply(s.Placement)
        return s
    if feature.TypeId == "Part::Cut":
        return feature.Tool.Shape.copy()
    if hasattr(feature, "Shape") and not feature.Shape.isNull() and feature.Shape.Solids:
        return feature.Shape.copy()
    return None


def dimensions(doc):
    """[(key, label, value, unit)] for the part's dimensions: sketch dimensions and features' lengths and
    angles."""
    out = []
    for o in doc.Objects:
        if o.TypeId == "Sketcher::SketchObject":
            for k, c in enumerate(o.Constraints):
                if c.Type not in ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle"):
                    continue
                if not getattr(c, "Driving", True):
                    continue
                name = c.Name or "%s%d" % (c.Type, k + 1)
                unit = "deg" if c.Type == "Angle" else "mm"
                value = math.degrees(c.Value) if c.Type == "Angle" else c.Value
                out.append(("%s:%d" % (o.Name, k), "%s@%s" % (name, o.Label), value, unit))
        elif _kind(o) != "ConnectionDefinition":
            for prop in o.PropertiesList:
                t = o.getTypeIdOfProperty(prop)
                if t not in ("App::PropertyLength", "App::PropertyDistance", "App::PropertyAngle"):
                    continue
                if o.getGroupOfProperty(prop) in ("Base", "Attachment", "") or (o.getEditorMode(prop) or []):
                    continue
                try:
                    q = getattr(o, prop)
                    value = float(q.Value if hasattr(q, "Value") else q)
                except Exception:
                    continue
                unit = "deg" if t == "App::PropertyAngle" else "mm"
                out.append(("%s.%s" % (o.Name, prop), "%s@%s" % (prop, o.Label), value, unit))
    return out


def set_dimension(doc, key, value):
    if ":" in key:
        name, _sep, k = key.rpartition(":")
        sk = doc.getObject(name)
        c = sk.Constraints[int(k)]
        unit = "deg" if c.Type == "Angle" else "mm"
        sk.setDatum(int(k), App.Units.Quantity("%r %s" % (float(value), unit)))
    else:
        name, _sep, prop = key.partition(".")
        setattr(doc.getObject(name), prop, float(value))


def sizes(doc):
    """The part's configurations: the values of a spreadsheet's configuration table."""
    for o in doc.Objects:
        if o.TypeId != "Spreadsheet::Sheet":
            continue
        for prop in o.PropertiesList:
            if o.getTypeIdOfProperty(prop) == "App::PropertyEnumeration":
                try:
                    values = list(o.getEnumerationsOfProperty(prop))
                except Exception:
                    continue
                if values:
                    return o, prop, values
    return None, None, [DEFAULT_SIZE]


def definition(doc):
    return next((o for o in doc.Objects if _kind(o) == "ConnectionDefinition"), None)


def _ref_geom(link):
    if not link:
        return None
    obj, subs = link
    sub = subs[0] if subs else ""
    return geom_of(obj, sub)


def read(path, size=None, values=None):
    """What an element part holds, at a size and with its dimension values: {shape, tools, refs, mates,
    placement, groups: [{name, dims: [[key, label, value, unit]]}], sizes}."""
    for d in App.listDocuments().values():
        if os.path.normcase(os.path.abspath(d.FileName or "")) == os.path.normcase(os.path.abspath(path)):
            raise RuntimeError(OPEN_ELSEWHERE)
    active = App.ActiveDocument
    doc = App.openDocument(path, hidden=True)
    try:
        sheet, prop, names = sizes(doc)
        if sheet is not None and size in names:
            setattr(sheet, prop, size)
        for key, value in (values or {}).items():
            try:
                set_dimension(doc, key, value)
            except Exception as error:
                App.Console.PrintWarning("Connection Element: %s: %s\n" % (key, error))
        doc.recompute()
        d = definition(doc)
        if d is None:
            raise RuntimeError("The part has no connection definition.")
        solids = _solids(doc)
        shape = Part.makeCompound(solids) if solids else Part.Shape()
        tools = [t for t in (tool_of(f) for f in d.Propagate) if t is not None]
        refs = [_ref_geom(d.Primary), _ref_geom(d.Secondary), _ref_geom(d.Tertiary)]
        dims = {k: (lab, val, unit) for k, lab, val, unit in dimensions(doc)}
        groups = []
        for g in _load(d.DimensionGroups, []):
            groups.append({"name": g.get("name", ""),
                           "dims": [[k] + list(dims[k]) for k in g.get("dims", []) if k in dims]})
        return {"shape": shape, "tools": Part.makeCompound(tools) if tools else Part.Shape(), "refs": refs,
                "mates": ["Coincident", d.SecondaryMate, d.TertiaryMate], "placement": d.PlacementType,
                "groups": groups, "sizes": names}
    finally:
        App.closeDocument(doc.Name)
        if active is not None and active.Name in App.listDocuments():
            App.setActiveDocument(active.Name)
            if App.GuiUp:
                try:
                    Gui.setActiveDocument(active.Name)
                except Exception as _fw_err:
                    _fw_log("weconnection.py:513", _fw_err)


# ================================================================ Connection Definition (in the element)
class ConnectionDefinition:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyEnumeration", "PlacementType", GROUP, "Generic Connection or End Connection")
        obj.PlacementType = list(PLACEMENTS)
        add("App::PropertyLinkSub", "Primary", GROUP, "Primary Reference: decides the element's orientation")
        add("App::PropertyLinkSub", "Secondary", GROUP, "Secondary Reference")
        add("App::PropertyEnumeration", "SecondaryMate", GROUP, "Secondary Reference mate")
        obj.SecondaryMate = list(MATES)
        add("App::PropertyLinkSub", "Tertiary", GROUP, "Tertiary Reference")
        add("App::PropertyEnumeration", "TertiaryMate", GROUP, "Tertiary Reference mate")
        obj.TertiaryMate = list(MATES)
        add("App::PropertyLinkList", "Propagate", GROUP, "Feature Propagation: features that cut the members")
        add("App::PropertyString", "DimensionGroups", GROUP, "Dimension Groups (JSON)")
        obj.setEditorMode("DimensionGroups", 2)
        obj.DimensionGroups = "[]"
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _ff_icon(name, key=None):
    try:
        return _weicon(name, key)
    except Exception:
        return ""


class _View:
    ICON = "link.svg"
    PANEL = None

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return _ff_icon(self.ICON)

    def claimChildren(self):
        return []

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        panel = self.panel(obj)
        if panel is None:
            return False
        obj.Document.openTransaction("Edit " + panel.TITLE)
        try:
            Gui.Control.showDialog(panel)
        except BaseException:
            try:
                obj.Document.abortTransaction()
            except Exception:
                pass
            raise
        return True

    def unsetEdit(self, vobj, mode=0):
        return False

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderDefinition(_View):
    ICON = "link.svg"

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def attach(self, vobj):
        self.Object = vobj.Object
        wemember._empty_mode(vobj)

    def panel(self, obj):
        return DefinePanel(obj, False)


def make_definition(doc):
    obj = doc.addObject("App::FeaturePython", "ConnectionDefinition")
    ConnectionDefinition(obj)
    if App.GuiUp:
        ViewProviderDefinition(obj.ViewObject)
    obj.Label = naming.next_label(doc, DEFINITION_LABEL)
    return obj


def check_definition(obj):
    """Why the definition can't be kept, else None."""
    doc = obj.Document
    if _external(doc):
        return EXTERNAL
    refs = [_ref_geom(obj.Primary), _ref_geom(obj.Secondary), _ref_geom(obj.Tertiary)]
    if refs[0] is None:
        return "Select the primary reference."
    if refs[0]["kind"] != "plane":
        return NOT_PLANAR
    if obj.PlacementType == "End Connection":
        return None
    for r, mate, name in ((refs[1], obj.SecondaryMate, "secondary"), (refs[2], obj.TertiaryMate, "tertiary")):
        if r is None:
            continue
        if mate == "Concentric" and r["kind"] != "axis":
            return "Concentric: the %s reference must be a cylindrical face, a circular edge or an axis." % name
        if mate != "Concentric" and r["kind"] != "plane":
            return "%s: the %s reference must be a flat face or a plane." % (mate, name)
    if all(r is not None and r["kind"] == "plane" for r in refs) and _meet(refs) is None:
        return NO_ORIGIN
    return None


# ================================================================ Connection Element (inserted)
class ConnectionElement:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyString", "Source", GROUP, "The connection element's part")
        add("App::PropertyString", "Standard", GROUP, "Standard")
        add("App::PropertyString", "ElementType", GROUP, "Type")
        add("App::PropertyString", "Size", GROUP, "Size (configuration)")
        add("App::PropertyString", "PlacementType", GROUP, "Generic Connection or End Connection")
        add("Part::PropertyPartShape", "ElementShape", GROUP, "The element, in its own coordinates")
        add("Part::PropertyPartShape", "ToolShape", GROUP, "The propagated features, in its own coordinates")
        add("Part::PropertyPartShape", "CutShape", GROUP, "The propagated features where the element is", 8)
        add("App::PropertyString", "References", GROUP, "The element's references (JSON)")
        add("App::PropertyString", "Mates", GROUP, "Primary, secondary and tertiary mates (JSON)")
        add("App::PropertyString", "Targets", GROUP, "What each reference sits on (JSON)")
        add("App::PropertyString", "Flips", GROUP, "Flip alignment per reference (JSON)")
        add("App::PropertyString", "Offsets", GROUP, "Offset per reference (JSON)")
        add("App::PropertyString", "Groups", GROUP, "Dimension Groups with their values (JSON)")
        add("App::PropertyString", "CutMembers", GROUP, "Cut Scope: the members the features cut (JSON)")
        add("App::PropertyString", "CornerKey", GROUP, "The corner the element is at")
        add("App::PropertyBool", "TrimMembers", GROUP, "The element also trims the Cut Scope members")
        add("App::PropertyLinkList", "Sources", GROUP, "The member shapes the targets are on")
        add("App::PropertyLinkListHidden", "Created", GROUP, "Objects made by this feature")
        add("App::PropertyString", "Outputs", GROUP, "Newest shape of each cut body (JSON)")
        for name in ("ElementShape", "ToolShape", "CutShape", "References", "Mates", "Targets", "Flips", "Offsets",
                     "Groups", "CutMembers", "CornerKey", "Sources", "Created", "Outputs", "Source"):
            obj.setEditorMode(name, 2)
        obj.References = obj.Targets = obj.Groups = obj.CutMembers = "[]"
        obj.Mates = json.dumps(["Coincident", "Coincident", "Coincident"])
        obj.Flips = json.dumps([False, False, False])
        obj.Offsets = json.dumps([0.0, 0.0, 0.0])
        obj.Outputs = "{}"
        obj.Size = DEFAULT_SIZE
        obj.PlacementType = PLACEMENTS[0]
        obj.Proxy = self

    def execute(self, obj):
        pl = placement_of(obj)
        shape = obj.ElementShape
        if pl is None or shape.isNull():
            obj.Shape = Part.Shape()
            obj.CutShape = Part.Shape()
            return
        s = shape.copy()
        s.transformShape(pl.toMatrix())
        obj.Shape = Part.makeCompound([s])        # (a feature puts its own Placement on a shape it is given)
        tools = obj.ToolShape
        cut = []
        if not tools.isNull():
            t = tools.copy()
            t.transformShape(pl.toMatrix())
            cut.append(t)
        if getattr(obj, "TrimMembers", False) and s.Solids:
            cut.append(s)                         # the element's own body trims the members too
        obj.CutShape = Part.makeCompound([Part.makeCompound(cut)]) if cut else Part.Shape()

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _targets_geom(obj):
    doc = obj.Document
    sources = list(obj.Sources)
    out = []
    for item in _load(obj.Targets, []):
        if not item:
            out.append(None)
            continue
        src = None
        if item.get("kind") == "body":
            src = next((s for s in sources if wetrim.ref_of(s) == item["ref"]), None)
        out.append(resolve(doc, item, src))
    return out


def placement_of(obj):
    """Where the element goes, from its references and their targets (None while the primary has none)."""
    refs = _load(obj.References, [])
    targets = _targets_geom(obj)
    flips = _load(obj.Flips, [False] * 3)
    offsets = _load(obj.Offsets, [0.0] * 3)
    if not refs or not targets or targets[0] is None or refs[0] is None:
        return None
    if obj.PlacementType == "End Connection":
        item = _load(obj.Targets, [])[0]
        doc = obj.Document
        body = None
        if item.get("kind") == "body":
            body = next((s for s in obj.Sources if wetrim.ref_of(s) == item["ref"]), None) or \
                wetrim.current_tip(doc, item["ref"])
        base = wetrim.base_of(body)
        if base is None:
            raise ValueError("End Connection: pick a member's end face.")
        face, end = _end_face_of(body, base, targets[0])
        return end_solve(refs[0], face, base, end, flips[0], offsets[0])
    mates = _load(obj.Mates, ["Coincident"] * 3)
    refs = (refs + [None] * 3)[:3]
    targets = (targets + [None] * 3)[:3]
    return solve(refs, targets, mates, flips, offsets)


def _end_face_of(body, base, g):
    """The member's end face the target stands for, and which end it is."""
    p0, p1 = wetrim.line_of(base)
    c = _v(g["center"])
    end = 1 if (c - p1).Length < (c - p0).Length else 0
    face = None
    n = _v(g["normal"])
    for f in body.Shape.Faces:
        h = geom_of_shape(f)
        if h and h["kind"] == "plane" and _v(h["normal"]).dot(n) > 1 - 1e-6 and \
                abs((_v(h["point"]) - c).dot(n)) < 1e-6:
            face = f
            break
    if face is None:
        raise ValueError("End Connection: the member's end face is gone.")
    return face, end


class ConnectionCut:
    """A member body with the propagated features of the connection elements on it cut away."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyLink", "TrimmedBody", GROUP, "The member body cut")
        obj.addProperty("App::PropertyLink", "Element", GROUP, "The connection element (or its pattern)")
        obj.addProperty("App::PropertyIntegerList", "Pieces", GROUP, "Which of the element's instances cut it")
        obj.Proxy = self

    def execute(self, obj):
        body, el = obj.TrimmedBody, obj.Element
        if body is None or body.Shape.isNull():
            obj.Shape = Part.Shape()
            return
        shape = body.Shape.copy()
        tools = [] if el is None or el.CutShape.isNull() else el.CutShape.childShapes()
        cuts = []
        for k in obj.Pieces:
            if 0 <= k < len(tools) and not tools[k].isNull():
                cuts.extend(tools[k].Solids or [tools[k]])
        for t in cuts:
            if shape.BoundBox.intersect(t.BoundBox):
                try:
                    shape = shape.cut(t)
                except Exception as _fw_err:
                    _fw_log("weconnection.py:790", _fw_err)
        try:
            shape = shape.removeSplitter()
        except Exception as _fw_err:
            _fw_log("weconnection.py:794", _fw_err)
        obj.Shape = shape

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _cut(doc, tip, element, pieces):
    obj = doc.addObject("Part::FeaturePython", "ConnectionCut")
    ConnectionCut(obj)
    if App.GuiUp:
        obj.ViewObject.Proxy = 0
    obj.TrimmedBody = tip
    obj.Element = element
    obj.Pieces = list(pieces)
    return obj


def _upgrade(obj):
    """Made before pkg165: Created no longer counts as a dependency (the cuts link back to the element) and
    CutShape is an output (setting it in execute leaves the feature up to date)."""
    if obj.getTypeIdOfProperty("Created") != "App::PropertyLinkListHidden":
        keep = list(obj.Created)
        obj.removeProperty("Created")
        obj.addProperty("App::PropertyLinkListHidden", "Created", GROUP, "Objects made by this feature")
        obj.setEditorMode("Created", 2)
        obj.Created = keep
    if "Output" not in obj.getPropertyStatus("CutShape"):
        obj.setPropertyStatus("CutShape", "Output")
    if "TrimMembers" not in obj.PropertiesList and "ElementShape" in obj.PropertiesList:
        obj.addProperty("App::PropertyBool", "TrimMembers", GROUP, "The element also trims the Cut Scope members")


def _hide(objs):
    if App.GuiUp:
        for o in objs:
            try:
                o.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("weconnection.py:836", _fw_err)


def build(obj):
    """Links the element to the members' current shapes and cuts the members in its Cut Scope."""
    doc = obj.Document
    _upgrade(obj)
    sources = []
    for item in _load(obj.Targets, []):
        if item and item.get("kind") == "body":
            tip = wetrim.current_tip(doc, item["ref"], obj)
            if tip is not None and tip not in sources:
                sources.append(tip)
    obj.Sources = sources
    obj.touch()
    doc.recompute([obj])
    obj.CornerKey = corner_key(obj)
    created, outputs = [], {}
    if not obj.CutShape.isNull():
        for ref in _load(obj.CutMembers, []):
            tip = wetrim.current_tip(doc, ref, obj)
            if tip is None:
                continue
            cut = _cut(doc, tip, obj, [0])
            created.append(cut)
            outputs[ref] = cut.Name
    obj.Created = created
    obj.Outputs = json.dumps(outputs)
    _hide(created)
    obj.touch()


class ViewProviderElement(_View):
    ICON = "box.svg"

    def panel(self, obj):
        return InsertPanel(obj, False)


def make_element(doc):
    obj = doc.addObject("Part::FeaturePython", "ConnectionElement")
    ConnectionElement(obj)
    if App.GuiUp:
        ViewProviderElement(obj.ViewObject)
        obj.ViewObject.ShapeColor = (0.62, 0.65, 0.70)
    obj.Label = naming.next_label(doc, ELEMENT_LABEL)
    return obj


def elements(doc):
    return [o for o in doc.Objects if _kind(o) == "ConnectionElement"]


def load_into(obj, info):
    """Puts what the element's part holds into the inserted feature."""
    obj.ElementShape = info["shape"]
    obj.ToolShape = info["tools"]
    obj.References = json.dumps(info["refs"])
    obj.Mates = json.dumps(info["mates"])
    obj.PlacementType = info["placement"]


# ================================================================ corners
def systems(doc):
    return [o for o in doc.Objects if _kind(o) == "StructureSystem"]


def all_corners(doc):
    from . import wecorner
    out = []
    for s in systems(doc):
        try:
            out.extend(wecorner.corners(s))
        except Exception:
            continue
    return out


def _target_refs(obj):
    return [i["ref"] for i in _load(obj.Targets, []) if i and i.get("kind") == "body"]


def corner_key(obj):
    """The corner the element sits at: one whose members hold its targets, the nearest."""
    refs = set(_target_refs(obj))
    if not refs or obj.Shape.isNull():
        return ""
    c0 = obj.Shape.BoundBox.Center
    best, best_d = "", None
    for c in all_corners(obj.Document):
        if not refs <= set(c["members"]):
            continue
        d = (c["point"] - c0).Length
        if best_d is None or d < best_d:
            best, best_d = c["key"], d
    return best


def _away(doc, ref, corner):
    """The member's direction away from the corner (None for a member passing through)."""
    base = wetrim.base_of(wetrim.current_tip(doc, ref))
    a, b = wetrim.line_of(base)
    if ref in corner["ends"]:
        far = a if corner["ends"][ref] == 1 else b
        return (far - corner["point"]).normalize()
    return None


def _line_dir(doc, ref):
    a, b = wetrim.line_of(wetrim.base_of(wetrim.current_tip(doc, ref)))
    return (b - a).normalize()


def _profile_of(doc, ref):
    sm = doc.getObject(ref.rpartition(":")[0])
    return getattr(sm, "Standard", ""), getattr(sm, "Type", ""), getattr(sm, "Size", "")


def _frame(d1, d2):
    x = V(d1).normalize()
    z = x.cross(d2)
    if z.Length < 1e-6:
        return None
    z.normalize()
    y = z.cross(x)
    m = App.Matrix(x.x, y.x, z.x, 0, x.y, y.y, z.y, 0, x.z, y.z, z.z, 0, 0, 0, 0, 1)
    return App.Rotation(m)


def _near(doc, ref, point, radius, before):
    tip = wetrim.current_tip(doc, ref, before)
    return tip.Shape.common(Part.makeSphere(radius, point))


def _alike(a, b, pl):
    """True when shape a, moved by pl, is shape b."""
    a = a.copy()
    a.transformShape(pl.toMatrix())
    va, vb = a.Volume, b.Volume
    if abs(va - vb) > 1e-3 * max(vb, 1.0):
        return False
    return a.common(b).Volume > vb * (1 - 1e-4) - 1e-6


def corner_map(doc, seed, other, radius, before=None):
    """(Placement, {seed member: other member}) taking the seed corner onto the other, when the corners are
    alike: the same kind, the same profiles, and the members' shapes within radius of the corner the same
    once moved (as they are before the feature `before`: the seed's own cuts left out)."""
    if seed["kind"] != other["kind"] or len(seed["members"]) != len(other["members"]):
        return None
    m0 = seed["members"]
    near0 = {r: _near(doc, r, seed["point"], radius, before) for r in m0}
    near1 = {}
    best = None
    for perm in itertools.permutations(other["members"]):
        pairs = list(zip(m0, perm))
        if any(_profile_of(doc, a) != _profile_of(doc, b) for a, b in pairs):
            continue
        if any((a in seed["ends"]) != (b in other["ends"]) for a, b in pairs):
            continue
        through = [k for k, (a, _b) in enumerate(pairs) if a not in seed["ends"]]
        for signs in itertools.product((1.0, -1.0), repeat=len(through)):
            d0, d1 = [], []
            for k, (a, b) in enumerate(pairs):
                if k in through:
                    d0.append(_line_dir(doc, a))
                    d1.append(_line_dir(doc, b) * signs[through.index(k)])
                else:
                    d0.append(_away(doc, a, seed))
                    d1.append(_away(doc, b, other))
            i = next((k for k in range(1, len(d0)) if d0[0].cross(d0[k]).Length > 1e-6), None)
            if i is None:
                continue
            f0, f1 = _frame(d0[0], d0[i]), _frame(d1[0], d1[i])
            if f0 is None or f1 is None:
                continue
            rot = f1.multiply(f0.inverted())
            if any((rot.multVec(x) - y).Length > 1e-4 for x, y in zip(d0, d1)):
                continue
            pl = App.Placement(other["point"] - rot.multVec(seed["point"]), rot)
            ok = True
            for a, b in pairs:
                if b not in near1:
                    near1[b] = _near(doc, b, other["point"], radius, before)
                if not _alike(near0[a], near1[b], pl):
                    ok = False
                    break
            if ok:
                # symmetric members fit more than one way: keep the copy on the same side of the members
                # (the seed corner's plane kept facing the same way), then the least turn
                n0 = d0[0].cross(d0[i]).normalize()
                score = (round(-rot.multVec(n0).dot(n0), 6), round(abs(rot.Angle), 6))
                if best is None or score < best[0]:
                    best = (score, pl, dict(pairs))
    return None if best is None else (best[1], best[2])


def corner_name(doc, key):
    for k, c in enumerate(all_corners(doc), 1):
        if c["key"] == key:
            return "Corner%d" % k
    return key


# ================================================================ Connection Element Pattern
class ConnectionPattern:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyLink", "Seed", GROUP, "Selected Connection Element")
        add("App::PropertyBool", "IgnoreExisting", GROUP, "Ignore corners that have connection elements")
        add("App::PropertyString", "Skipped", GROUP, "Instances to Skip: corner keys (JSON)")
        add("App::PropertyString", "Instances", GROUP, "The similar corners: key, placement, cut members (JSON)")
        add("Part::PropertyPartShape", "CutShape", GROUP, "The propagated features at each instance", 8)
        add("App::PropertyLinkListHidden", "Created", GROUP, "Objects made by this feature")
        add("App::PropertyString", "Outputs", GROUP, "Newest shape of each cut body (JSON)")
        for name in ("Skipped", "Instances", "CutShape", "Created", "Outputs"):
            obj.setEditorMode(name, 2)
        obj.Skipped = obj.Instances = "[]"
        obj.Outputs = "{}"
        obj.IgnoreExisting = True
        obj.Proxy = self

    def execute(self, obj):
        seed = obj.Seed
        if seed is None or seed.Shape.isNull():
            obj.Shape = Part.Shape()
            obj.CutShape = Part.Shape()
            return
        shapes, tools = [], []
        for inst in _load(obj.Instances, []):
            m = App.Placement(App.Matrix(*inst["matrix"])).toMatrix()
            s = seed.Shape.copy()
            s.transformShape(m)
            shapes.append(s)
            if seed.CutShape.isNull():
                tools.append(Part.Compound([]))
            else:
                t = seed.CutShape.copy()
                t.transformShape(m)
                tools.append(t)
        obj.Shape = Part.makeCompound(shapes) if shapes else Part.Shape()
        obj.CutShape = Part.makeCompound(tools) if tools else Part.Shape()

    def dumps(self):
        return None

    def loads(self, state):
        return None


def similar(obj, seed=None, ignore=None):
    """[(corner, Placement, member map)] of the corners like the seed element's."""
    seed = seed if seed is not None else obj.Seed
    if seed is None or not seed.CornerKey:
        return []
    doc = seed.Document
    corners = all_corners(doc)
    c0 = next((c for c in corners if c["key"] == seed.CornerKey), None)
    if c0 is None:
        return []
    ignore = obj.IgnoreExisting if ignore is None else ignore
    taken = set()
    if ignore:
        taken = {e.CornerKey for e in elements(doc) if e.CornerKey}
        for p in patterns(doc):
            if p is not obj:
                taken.update(i["key"] for i in _load(p.Instances, []))
    b = seed.Shape.BoundBox
    radius = max(b.DiagonalLength, 1.0)
    out = []
    for c in corners:
        if c["key"] == c0["key"] or c["key"] in taken:
            continue
        found = corner_map(doc, c0, c, radius, seed)
        if found is not None:
            out.append((c, found[0], found[1]))
    return out


def build_pattern(obj):
    doc = obj.Document
    _upgrade(obj)
    skipped = set(_load(obj.Skipped, []))
    seed = obj.Seed
    instances = []
    if seed is not None:
        cut0 = _load(seed.CutMembers, [])
        for c, pl, mapping in similar(obj):
            if c["key"] in skipped:
                continue
            m = pl.toMatrix()
            instances.append({"key": c["key"], "matrix": list(m.A),
                              "cuts": [mapping[r] for r in cut0 if r in mapping]})
    obj.Instances = json.dumps(instances)
    obj.touch()
    doc.recompute([obj])
    created, outputs, pieces = [], {}, {}
    for k, inst in enumerate(instances):
        for ref in inst["cuts"]:
            pieces.setdefault(ref, []).append(k)
    if not obj.CutShape.isNull():
        for ref, ks in pieces.items():
            tip = wetrim.current_tip(doc, ref, obj)
            if tip is None:
                continue
            cut = _cut(doc, tip, obj, ks)
            created.append(cut)
            outputs[ref] = cut.Name
    obj.Created = created
    obj.Outputs = json.dumps(outputs)
    _hide(created)
    obj.touch()


class ViewProviderPattern(_View):
    ICON = "list-add.svg"

    def panel(self, obj):
        return PatternPanel(obj, False)


def make_pattern(doc):
    obj = doc.addObject("Part::FeaturePython", "ConnectionPattern")
    ConnectionPattern(obj)
    if App.GuiUp:
        ViewProviderPattern(obj.ViewObject)
        obj.ViewObject.ShapeColor = (0.62, 0.65, 0.70)
    obj.Label = naming.next_label(doc, PATTERN_LABEL)
    return obj


def patterns(doc):
    return [o for o in doc.Objects if _kind(o) == "ConnectionPattern"]


def _refresh(doc):
    wemember.refresh(doc)


# ================================================================ PropertyManagers
def _bold(text):
    lab = QtWidgets.QLabel(text)
    f = lab.font()
    f.setBold(True)
    lab.setFont(f)
    return lab


def _list(name, colour, tip, height=26):
    w = QtWidgets.QListWidget()
    w.setObjectName(name)
    w.setToolTip(tip)
    w.setMaximumHeight(height)
    if colour == "#d6ecff":
        pmboxes.mark(w, True)
    else:
        w.setStyleSheet("QListWidget { background: %s; }" % colour)
    return w


def _spin(name, value, lo=-100000.0, hi=100000.0, suffix=" mm"):
    w = QtWidgets.QDoubleSpinBox()
    w.setObjectName(name)
    w.setRange(lo, hi)
    w.setDecimals(2)
    w.setSuffix(suffix)
    w.setValue(value)
    return w


def _error_label(name):
    e = QtWidgets.QLabel("")
    e.setObjectName(name)
    e.setWordWrap(True)
    e.setStyleSheet("color: #c00000;")
    from . import pickprompt
    pickprompt.style(e)     # look audit AI1: the start prompt in the yellow box
    e.hide()
    return e


class _Keys(QtCore.QObject):
    """Delete removes the picked item from a selection box; clicking a box makes it the one picks go to."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Delete:
            self.panel.remove_current(watched)
            return True
        if event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
            self.panel.activate(watched)
        return False


def _label_of(doc, link):
    if not link:
        return ""
    obj, subs = link
    return "%s@%s" % (subs[0], obj.Label) if subs and subs[0] else obj.Label


class _Closing:
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("weconnection.py:1248", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("weconnection.py:1254", _fw_err)

    def _gone(self):
        """cmsweep-1119: the panel's object went with its document (closed with the PropertyManager open):
        stop listening to picks instead of failing on each one."""
        try:
            self.obj.Document
            return False
        except Exception:
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("weconnection.py:gone", _fw_err)
            return True

    def reject(self):
        doc = self.obj.Document
        doc.abortTransaction()
        doc.recompute()
        self._close()
        return True

    def show_error(self, text):
        self.error.setText(text or "")
        self.error.setVisible(bool(text))


_LAST = None


class DefinePanel(_Closing):
    """Connection Definition: References and Dimensions tabs."""
    TITLE = DEFINE_TITLE

    def __init__(self, obj, new):
        global _LAST
        _LAST = self
        self.obj, self.new, self.busy = obj, new, True
        self.keys = _Keys(self)
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("SWCEDefinePanel")
        self.form.setWindowTitle(DEFINE_TITLE)
        self.form.setProperty("swstyle_pm_title", DEFINE_TITLE)
        self.form.setProperty("swstyle_pm_icon", DEFINE_COMMAND)
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.setContentsMargins(4, 4, 4, 4)
        self.error = _error_label("SWCEError")
        lay.addWidget(self.error)
        self.tabs = QtWidgets.QTabBar()
        self.tabs.setObjectName("SWCETabs")
        self.tabs.addTab("References")
        self.tabs.addTab("Dimensions")
        self.tabs.setExpanding(True)
        lay.addWidget(self.tabs)
        self.pages = QtWidgets.QStackedWidget()
        lay.addWidget(self.pages)
        self.pages.addWidget(self._references_page())
        self.pages.addWidget(self._dimensions_page())
        self.tabs.currentChanged.connect(self.pages.setCurrentIndex)
        self.active = self.boxes[0]
        self.busy = False
        self._show()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def _references_page(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        msg = QtWidgets.QLabel("Pick the faces or planes that place the element, then the features that also "
                               "cut the members.")
        msg.setWordWrap(True)
        msg.setObjectName("SWCEMessage")
        lay.addWidget(msg)
        lay.addWidget(_bold("Placement Type"))
        self.placements = QtWidgets.QButtonGroup(page)
        for k, text in enumerate(PLACEMENTS):
            b = QtWidgets.QRadioButton(text)
            b.setObjectName("SWCE" + text.replace(" ", ""))
            b.setChecked(self.obj.PlacementType == text)
            self.placements.addButton(b, k)
            lay.addWidget(b)
        self.placements.buttonClicked.connect(self._changed)
        self.boxes, self.mates, self.ref_widgets = [], [], []
        colours = ("#d6ecff", "#ffd6ec", "#e6d6ff")
        for k, title in enumerate(REFERENCES):
            w = QtWidgets.QWidget()
            wl = QtWidgets.QVBoxLayout(w)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.addWidget(_bold(title))
            box = _list("SWCE" + title.replace(" ", ""), colours[k], title + ": a face, edge or plane")
            box.installEventFilter(self.keys)
            wl.addWidget(box)
            self.boxes.append(box)
            if k:
                mate = QtWidgets.QComboBox()
                mate.setObjectName("SWCE%sMate" % title.split()[0])
                mate.addItems(list(MATES))
                mate.setCurrentText(getattr(self.obj, ("SecondaryMate", "TertiaryMate")[k - 1]))
                mate.currentIndexChanged.connect(self._changed)
                wl.addWidget(mate)
                self.mates.append(mate)
            self.ref_widgets.append(w)
            lay.addWidget(w)
        lay.addWidget(_bold("Feature Propagation"))
        self.features = _list("SWCEFeatures", "#d6f5d6", "Features that also cut the members", 80)
        self.features.installEventFilter(self.keys)
        self.boxes.append(self.features)
        lay.addWidget(self.features)
        lay.addStretch(1)
        return page

    def _dimensions_page(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        msg = QtWidgets.QLabel("Tick the dimensions that can be changed when the element is inserted.")
        msg.setWordWrap(True)
        lay.addWidget(msg)
        lay.addWidget(_bold("Dimension Groups"))
        self.groups = _load(self.obj.DimensionGroups, [])
        self.group_box = QtWidgets.QComboBox()
        self.group_box.setObjectName("SWCEDimensionGroup")
        self.group_box.setEditable(True)
        self.group_box.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        lay.addWidget(self.group_box)
        self.new_group = QtWidgets.QPushButton("New Dimension Group")
        self.new_group.setObjectName("SWCENewDimensionGroup")
        self.new_group.clicked.connect(self._add_group)
        lay.addWidget(self.new_group)
        self.dims = QtWidgets.QListWidget()
        self.dims.setObjectName("SWCEDimensions")
        lay.addWidget(self.dims)
        self.group_box.currentIndexChanged.connect(self._show_group)
        self.group_box.lineEdit().editingFinished.connect(self._rename_group)
        self.dims.itemChanged.connect(self._dim_ticked)
        self._fill_groups()
        return page

    # ---------------------------------------------------------------- dimension groups
    def _fill_groups(self, row=None):
        busy, self.busy = self.busy, True
        self.group_box.clear()
        for g in self.groups:
            self.group_box.addItem(g["name"])
        if self.groups:
            self.group_box.setCurrentIndex(len(self.groups) - 1 if row is None else row)
        self.busy = busy
        self._show_group()

    def _add_group(self):
        names = {g["name"] for g in self.groups}
        k = 1
        while "Dimension Group%d" % k in names:
            k += 1
        self.groups.append({"name": "Dimension Group%d" % k, "dims": []})
        self._fill_groups()
        self._store_groups()

    def _rename_group(self):
        row = self.group_box.currentIndex()
        text = self.group_box.currentText().strip()
        if 0 <= row < len(self.groups) and text:
            self.groups[row]["name"] = text
            self.group_box.setItemText(row, text)
            self._store_groups()

    def _show_group(self, *_a):
        busy, self.busy = self.busy, True
        self.dims.clear()
        row = self.group_box.currentIndex()
        g = self.groups[row] if 0 <= row < len(self.groups) else None
        self.dims.setEnabled(g is not None)
        for key, label, value, unit in dimensions(self.obj.Document):
            it = QtWidgets.QListWidgetItem("%s  (%g %s)" % (label, round(value, 4), unit))
            it.setData(QtCore.Qt.UserRole, key)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if g and key in g["dims"] else QtCore.Qt.Unchecked)
            self.dims.addItem(it)
        self.busy = busy

    def _dim_ticked(self, item):
        if self.busy:
            return
        row = self.group_box.currentIndex()
        if not 0 <= row < len(self.groups):
            return
        key = item.data(QtCore.Qt.UserRole)
        dims = self.groups[row]["dims"]
        if item.checkState() == QtCore.Qt.Checked and key not in dims:
            dims.append(key)
        elif item.checkState() != QtCore.Qt.Checked and key in dims:
            dims.remove(key)
        self._store_groups()

    def _store_groups(self):
        self.obj.DimensionGroups = json.dumps(self.groups)

    # ---------------------------------------------------------------- references
    def _links(self):
        return [self.obj.Primary, self.obj.Secondary, self.obj.Tertiary]

    def _show(self):
        busy, self.busy = self.busy, True
        o = self.obj
        for box, link in zip(self.boxes, self._links()):
            box.clear()
            if link:
                box.addItem(_label_of(o.Document, link))
        self.features.clear()
        for f in o.Propagate:
            self.features.addItem(f.Label)
        end = o.PlacementType == "End Connection"
        for w in self.ref_widgets[1:]:
            w.setVisible(not end)
        self.ref_widgets[0].findChild(QtWidgets.QLabel).setText(REFERENCES[0])
        for b in self.boxes:
            b.setStyleSheet(b.styleSheet().replace("border: 2px solid #3874d8;", ""))
        self.active.setStyleSheet(self.active.styleSheet() + "border: 2px solid #3874d8;")
        self.busy = busy

    def activate(self, box):
        if box in self.boxes:
            self.active = box
            self._show()

    def _changed(self, *_a):
        if self.busy:
            return
        o = self.obj
        o.PlacementType = PLACEMENTS[max(0, self.placements.checkedId())]
        o.SecondaryMate = self.mates[0].currentText()
        o.TertiaryMate = self.mates[1].currentText()
        if o.PlacementType == "End Connection":
            o.Secondary = None
            o.Tertiary = None
            if self.active in self.boxes[1:3]:
                self.active = self.boxes[0]
        self._show()
        self.show_error(None)

    def remove_current(self, w):
        o = self.obj
        if w is self.features:
            row = w.currentRow()
            if 0 <= row < len(o.Propagate):
                feats = list(o.Propagate)
                del feats[row]
                o.Propagate = feats
        elif w in self.boxes[:3]:
            setattr(o, ("Primary", "Secondary", "Tertiary")[self.boxes.index(w)], None)
        self._show()

    def addSelection(self, doc, name, sub, point):
        QtCore.QTimer.singleShot(0, lambda: self._gone() or self.picked(doc, name, sub))

    def picked(self, doc_name, name, sub):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("weconnection.py:1501", _fw_err)
        o = self.obj
        if doc_name != o.Document.Name:
            return
        target = o.Document.getObject(name)
        if target is None or target is o:
            return
        if self.active is self.features:
            feat = target
            if sub and target.TypeId == "PartDesign::Body":
                feat = target.Tip
            if tool_of(feat) is None or feat in o.Propagate:
                return
            o.Propagate = list(o.Propagate) + [feat]
            self._show()
            return
        k = self.boxes.index(self.active)
        if target.TypeId == "PartDesign::Body" and not sub:
            return
        if geom_of(target, sub) is None:
            self.show_error("Pick a flat face, a cylindrical face, a circular or straight edge, or a plane.")
            return
        setattr(o, ("Primary", "Secondary", "Tertiary")[k], (target, [sub] if sub else []))
        self.show_error(None)
        last = 0 if o.PlacementType == "End Connection" else 2
        self.active = self.boxes[k + 1] if k < last else self.features
        self._show()

    def accept(self):
        problem = check_definition(self.obj)
        if problem:
            self.show_error(problem)
            return False
        self._rename_group()
        doc = self.obj.Document
        doc.recompute()
        doc.commitTransaction()
        self._close()
        return True


def define():
    doc = App.ActiveDocument
    if doc is None:
        return
    found = definition(doc)
    if found is not None:
        Gui.ActiveDocument.setEdit(found.Name, 0)
        return
    doc.openTransaction(DEFINE_TITLE)
    try:
        obj = make_definition(doc)
        panel = DefinePanel(obj, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    sel = [(s.Object, sub) for s in Gui.Selection.getSelectionEx() for sub in (s.SubElementNames or [""])]
    for target, sub in sel[:3]:
        panel.picked(doc.Name, target.Name, sub)


class InsertPanel(_Closing):
    """Insert Connection Element: Connection and Placement tabs."""
    TITLE = INSERT_TITLE

    def __init__(self, obj, new):
        global _LAST
        _LAST = self
        self.obj, self.new, self.busy = obj, new, True
        self.keys = _Keys(self)
        self.targets = (_load(obj.Targets, []) + [None] * 3)[:3]
        self.cut_members = _load(obj.CutMembers, [])
        self.values = {}
        for g in _load(obj.Groups, []):
            for key, _label, value, _unit in g.get("dims", []):
                self.values[key] = value
        self.info = None
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("SWCEInsertPanel")
        self.form.setWindowTitle(INSERT_TITLE)
        self.form.setProperty("swstyle_pm_title", INSERT_TITLE)
        self.form.setProperty("swstyle_pm_icon", INSERT_COMMAND)
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.setContentsMargins(4, 4, 4, 4)
        self.error = _error_label("SWCEError")
        lay.addWidget(self.error)
        self.tabs = QtWidgets.QTabBar()
        self.tabs.setObjectName("SWCETabs")
        self.tabs.addTab("Connection")
        self.tabs.addTab("Placement")
        self.tabs.setExpanding(True)
        lay.addWidget(self.tabs)
        self.pages = QtWidgets.QStackedWidget()
        lay.addWidget(self.pages)
        self.pages.addWidget(self._connection_page())
        self.pages.addWidget(self._placement_page())
        self.tabs.currentChanged.connect(self.pages.setCurrentIndex)
        self.active = self.boxes[0]
        self.busy = False
        if obj.Source and os.path.exists(obj.Source):
            self._load_element(keep=True)
            self.tabs.setCurrentIndex(1)
        elif not standards() or not any(types(s) for s in standards()):

            self.show_error(NONE_FOUND)
            self.error.setToolTip("Connection elements are saved in %s" % library())
        self._show()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def _connection_page(self):
        page = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(page)
        self.standard = QtWidgets.QComboBox()
        self.standard.setObjectName("SWCEStandard")
        self.kind = QtWidgets.QComboBox()
        self.kind.setObjectName("SWCEType")
        self.size = QtWidgets.QComboBox()
        self.size.setObjectName("SWCESize")
        f.addRow(_bold("Connection Element"))
        f.addRow(QtWidgets.QLabel("Standard:"))
        f.addRow(self.standard)
        f.addRow(QtWidgets.QLabel("Type:"))
        f.addRow(self.kind)
        f.addRow(QtWidgets.QLabel("Size:"))
        f.addRow(self.size)
        self.standard.addItems(standards())
        if self.obj.Standard:
            self.standard.setCurrentText(self.obj.Standard)
        self._fill_types()
        self.standard.currentIndexChanged.connect(self._standard_changed)
        self.kind.activated.connect(self._type_picked)
        self.size.activated.connect(self._size_picked)
        return page

    def _placement_page(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        msg = QtWidgets.QLabel("Change the dimensions if needed, pick where each reference goes, then the "
                               "members the element's cuts go through.")
        msg.setWordWrap(True)
        lay.addWidget(msg)
        self.dim_box = QtWidgets.QWidget()
        self.dim_box.setObjectName("SWCEDimensionsBox")
        QtWidgets.QFormLayout(self.dim_box)
        lay.addWidget(self.dim_box)
        self.boxes, self.flips, self.offsets, self.ref_widgets, self.mate_labels = [], [], [], [], []
        colours = ("#d6ecff", "#ffd6ec", "#e6d6ff")
        flips = _load(self.obj.Flips, [False] * 3)
        offsets = _load(self.obj.Offsets, [0.0] * 3)
        for k, title in enumerate(REFERENCES):
            w = QtWidgets.QWidget()
            wl = QtWidgets.QVBoxLayout(w)
            wl.setContentsMargins(0, 0, 0, 0)
            head = _bold(title)
            wl.addWidget(head)
            self.mate_labels.append(head)
            box = _list("SWCETarget%d" % (k + 1), colours[k], title + ": a member face or a plane")
            box.installEventFilter(self.keys)
            wl.addWidget(box)
            flip = QtWidgets.QCheckBox("Flip alignment")
            flip.setObjectName("SWCEFlip%d" % (k + 1))
            flip.setChecked(bool(flips[k]))
            flip.toggled.connect(self._changed)
            wl.addWidget(flip)
            off = _spin("SWCEOffset%d" % (k + 1), float(offsets[k]))
            off.setToolTip("Offset")
            off.valueChanged.connect(self._changed)
            wl.addWidget(off)
            self.boxes.append(box)
            self.flips.append(flip)
            self.offsets.append(off)
            self.ref_widgets.append(w)
            lay.addWidget(w)
        lay.addWidget(_bold("Cut Scope"))
        self.members = _list("SWCECutMembers", "#d6f5d6", "The members the element's cut features go through", 80)
        self.members.installEventFilter(self.keys)
        self.boxes.append(self.members)
        lay.addWidget(self.members)
        self.trim = QtWidgets.QCheckBox("Trim members with the element")
        self.trim.setObjectName("SWCETrimMembers")
        self.trim.setToolTip("The element's own body also trims the members in the Cut Scope")
        self.trim.setChecked(bool(getattr(self.obj, "TrimMembers", False)))
        self.trim.toggled.connect(self._changed)
        lay.addWidget(self.trim)
        lay.addStretch(1)
        return page

    # ---------------------------------------------------------------- the element
    def _fill_types(self):
        busy, self.busy = self.busy, True
        self.kind.clear()
        self.kind.addItems(types(self.standard.currentText()))
        if self.obj.ElementType:
            self.kind.setCurrentText(self.obj.ElementType)
        self.busy = busy

    def _standard_changed(self, *_a):
        if not self.busy:
            self._fill_types()

    def _type_picked(self, *_a):
        if self.busy:
            return
        self.values = {}
        self.obj.Size = DEFAULT_SIZE
        if self._load_element():
            self.tabs.setCurrentIndex(1)

    def _size_picked(self, *_a):
        if self.busy:
            return
        self.obj.Size = self.size.currentText()
        self._load_element(keep=True)

    def _load_element(self, keep=False):
        o = self.obj
        if not keep or not o.Source:
            o.Standard = self.standard.currentText()
            o.ElementType = self.kind.currentText()
            o.Source = element_path(o.Standard, o.ElementType) if o.ElementType else ""
        if not o.Source:
            return False
        try:
            info = read(o.Source, o.Size, self.values)
        except Exception as error:
            self.show_error(str(error))
            return False
        self.info = info
        load_into(o, info)
        self._fill_sizes(info["sizes"])
        self._fill_dims(info["groups"])
        self.show_error(None)
        self._changed()
        return True

    def _fill_sizes(self, names):
        busy, self.busy = self.busy, True
        self.size.clear()
        self.size.addItems(names)
        self.size.setCurrentText(self.obj.Size if self.obj.Size in names else names[0])
        self.obj.Size = self.size.currentText()
        self.busy = busy

    def _fill_dims(self, groups):
        f = self.dim_box.layout()
        while f.rowCount():
            f.removeRow(0)
        self.dim_spins = {}
        for g in groups:
            f.addRow(_bold(g["name"]))
            for key, label, value, unit in g["dims"]:
                s = _spin("SWCEDim_" + key.replace(".", "_").replace(":", "_"), float(value), -1e6, 1e6,
                          " deg" if unit == "deg" else " mm")
                s.setKeyboardTracking(False)
                s.valueChanged.connect(lambda v, key=key: self._dim_changed(key, v))
                f.addRow(QtWidgets.QLabel(label.split("@")[0]), s)
                self.dim_spins[key] = s
        self.dim_box.setVisible(bool(groups))
        self.obj.Groups = json.dumps(groups)

    def _dim_changed(self, key, value):
        if self.busy:
            return
        self.values[key] = value
        self._load_element(keep=True)

    # ---------------------------------------------------------------- placement
    def _target_label(self, item):
        doc = self.obj.Document
        if item is None:
            return None
        if item.get("kind") == "body":
            tip = wetrim.current_tip(doc, item["ref"])
            return "Face@%s" % (tip.Label if tip is not None else item["ref"])
        o = doc.getObject(item.get("obj", ""))
        label = o.Label if o is not None else item.get("obj", "")
        return "%s@%s" % (item["sub"], label) if item.get("sub") else label

    def _show(self):
        busy, self.busy = self.busy, True
        o = self.obj
        doc = o.Document
        end = o.PlacementType == "End Connection"
        refs = _load(o.References, [])
        mates = _load(o.Mates, ["Coincident"] * 3)
        for k, (box, item) in enumerate(zip(self.boxes[:3], self.targets)):
            box.clear()
            lab = self._target_label(item)
            if lab:
                box.addItem(lab)
            has = k < len(refs) and refs[k] is not None
            self.ref_widgets[k].setVisible(has and (k == 0 or not end))
            mate = "Coincident" if k == 0 else mates[k]
            self.mate_labels[k].setText("%s (%s)" % (REFERENCES[k], mate))
            self.offsets[k].setEnabled(mate != "Concentric")
        self.members.clear()
        for ref in self.cut_members:
            tip = wetrim.current_tip(doc, ref)
            self.members.addItem(tip.Label if tip is not None else ref)
        for b in self.boxes:
            b.setStyleSheet(b.styleSheet().replace("border: 2px solid #3874d8;", ""))
        self.active.setStyleSheet(self.active.styleSheet() + "border: 2px solid #3874d8;")
        self.busy = busy

    def activate(self, box):
        if box in self.boxes:
            self.active = box
            self._show()

    def _changed(self, *_a):
        if self.busy:
            return
        o = self.obj
        o.Targets = json.dumps(self.targets)
        o.Flips = json.dumps([f.isChecked() for f in self.flips])
        o.Offsets = json.dumps([s.value() for s in self.offsets])
        o.CutMembers = json.dumps(self.cut_members)
        if hasattr(self, "trim") and "TrimMembers" in o.PropertiesList:
            o.TrimMembers = self.trim.isChecked()
        self._show()
        try:
            _refresh(o.Document)
            if "Invalid" in o.State:
                raise RuntimeError(o.getStatusString())
            self.show_error(None)
        except Exception as error:
            self.show_error(str(error))

    def remove_current(self, w):
        if w is self.members:
            row = w.currentRow()
            if 0 <= row < len(self.cut_members):
                del self.cut_members[row]
        elif w in self.boxes[:3]:
            self.targets[self.boxes.index(w)] = None
        self._changed()

    def addSelection(self, doc, name, sub, point):
        QtCore.QTimer.singleShot(0, lambda: self._gone() or self.picked(doc, name, sub))

    def picked(self, doc_name, name, sub):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("weconnection.py:1842", _fw_err)
        o = self.obj
        if doc_name != o.Document.Name:
            return
        target = o.Document.getObject(name)
        if target is None or target is o or _kind(target) in ("ConnectionElement", "ConnectionPattern"):
            return
        if self.active is self.members:
            ref = wetrim.ref_of(target)
            if ref is None:
                self.show_error("Pick a member.")
                return
            if ref not in self.cut_members:
                self.cut_members.append(ref)
            self._changed()
            return
        item = target_item(target, sub)
        if item is None:
            self.show_error("Pick a member face, or a plane.")
            return
        k = self.boxes.index(self.active)
        self.targets[k] = item
        refs = _load(o.References, [])
        last = 0 if o.PlacementType == "End Connection" else max(0, len([r for r in refs if r]) - 1)
        self.active = self.boxes[k + 1] if k < last else self.members
        self._changed()

    def accept(self):
        o = self.obj
        if not o.Source:
            self.show_error("Select a connection element (Standard, Type, Size).")
            return False
        if self.targets[0] is None:
            self.show_error("Select the primary reference's target.")
            return False
        if "Invalid" in o.State or o.Shape.isNull():
            self.show_error(o.getStatusString() if "Invalid" in o.State else "The element can't be placed.")
            return False
        o.Document.commitTransaction()
        self._close()
        return True


def insert():
    doc = App.ActiveDocument
    if doc is None:
        return
    doc.openTransaction(INSERT_TITLE)
    try:
        obj = make_element(doc)
        panel = InsertPanel(obj, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise


class PatternPanel(_Closing):
    TITLE = PATTERN_TITLE

    def __init__(self, obj, new):
        global _LAST
        _LAST = self
        self.obj, self.new, self.busy = obj, new, True
        self.keys = _Keys(self)
        self.skipped = _load(obj.Skipped, [])
        self.found = []
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("SWCEPatternPanel")
        self.form.setWindowTitle(PATTERN_TITLE)
        self.form.setProperty("swstyle_pm_title", PATTERN_TITLE)
        self.form.setProperty("swstyle_pm_icon", PATTERN_COMMAND)
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.setContentsMargins(4, 4, 4, 4)
        msg = QtWidgets.QLabel("Select a connection element inserted at a corner: it is copied to the similar "
                               "corners.")
        msg.setWordWrap(True)
        lay.addWidget(msg)
        self.error = _error_label("SWCEError")
        lay.addWidget(self.error)
        lay.addWidget(_bold("Selected Connection Element"))
        self.seed = _list("SWCESeed", "#d6ecff", "The connection element to pattern")
        self.seed.installEventFilter(self.keys)
        lay.addWidget(self.seed)
        lay.addWidget(_bold("Identified Similar Corners"))
        self.corners = _list("SWCECorners", "#ffffff", "Where the connection element is copied", 120)
        self.corners.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.corners.customContextMenuRequested.connect(self._corner_menu)
        lay.addWidget(self.corners)
        self.ignore = QtWidgets.QCheckBox("Ignore corners that have connection elements")
        self.ignore.setObjectName("SWCEIgnore")
        self.ignore.setChecked(bool(obj.IgnoreExisting))
        self.ignore.toggled.connect(self._changed)
        lay.addWidget(self.ignore)
        lay.addWidget(_bold("Instances to Skip"))
        self.skip = _list("SWCESkip", "#ffd6ec", "Pick corners in the graphics area to leave them out", 80)
        self.skip.installEventFilter(self.keys)
        self.skip.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.skip.customContextMenuRequested.connect(self._skip_menu)
        lay.addWidget(self.skip)
        lay.addStretch(1)
        self.boxes = [self.seed, self.skip]
        self.active = self.seed if obj.Seed is None else self.skip
        self.busy = False
        self._changed()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def _show(self):
        busy, self.busy = self.busy, True
        doc = self.obj.Document
        self.seed.clear()
        if self.obj.Seed is not None:
            self.seed.addItem(self.obj.Seed.Label)
        self.corners.clear()
        for c, _pl, _m in self.found:
            if c["key"] not in self.skipped:
                it = QtWidgets.QListWidgetItem(corner_name(doc, c["key"]))
                it.setData(QtCore.Qt.UserRole, c["key"])
                self.corners.addItem(it)
        self.skip.clear()
        for key in self.skipped:
            it = QtWidgets.QListWidgetItem(corner_name(doc, key))
            it.setData(QtCore.Qt.UserRole, key)
            self.skip.addItem(it)
        for b in self.boxes:
            b.setStyleSheet(b.styleSheet().replace("border: 2px solid #3874d8;", ""))
        self.active.setStyleSheet(self.active.styleSheet() + "border: 2px solid #3874d8;")
        self.busy = busy

    def activate(self, box):
        if box in self.boxes:
            self.active = box
            self._show()

    def _changed(self, *_a):
        if self.busy:
            return
        o = self.obj
        o.IgnoreExisting = self.ignore.isChecked()
        o.Skipped = json.dumps(self.skipped)
        self.found = similar(o) if o.Seed is not None else []
        problem = None
        if o.Seed is not None and not o.Seed.CornerKey:
            problem = NOT_AT_CORNER
        elif o.Seed is not None and not self.found:
            problem = NO_SIMILAR
        try:
            _refresh(o.Document)
        except Exception as error:
            problem = str(error)
        self.found = similar(o) if o.Seed is not None else []
        self.show_error(problem)
        self._show()

    def skip_corner(self, key, on=True):
        if on and key not in self.skipped:
            self.skipped.append(key)
        elif not on and key in self.skipped:
            self.skipped.remove(key)
        self._changed()

    def _corner_menu(self, pos):
        it = self.corners.itemAt(pos)
        if it is None:
            return
        menu = QtWidgets.QMenu(self.corners)
        act = menu.addAction("Skip Instance")
        if menu.exec_(self.corners.mapToGlobal(pos)) is act:
            self.skip_corner(it.data(QtCore.Qt.UserRole), True)

    def _skip_menu(self, pos):
        it = self.skip.itemAt(pos)
        if it is None:
            return
        menu = QtWidgets.QMenu(self.skip)
        act = menu.addAction("Unskip Instance")
        if menu.exec_(self.skip.mapToGlobal(pos)) is act:
            self.skip_corner(it.data(QtCore.Qt.UserRole), False)

    def remove_current(self, w):
        if w is self.skip:
            row = w.currentRow()
            if 0 <= row < len(self.skipped):
                del self.skipped[row]
        elif w is self.seed:
            self.obj.Seed = None
        self._changed()

    def addSelection(self, doc, name, sub, point):
        p = V(*point) if point else None
        QtCore.QTimer.singleShot(0, lambda: self._gone() or self.picked(doc, name, sub, p))

    def picked(self, doc_name, name, sub, point=None):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("weconnection.py:2035", _fw_err)
        o = self.obj
        if doc_name != o.Document.Name:
            return
        target = o.Document.getObject(name)
        if target is None or target is o:
            return
        if _kind(target) == "ConnectionElement" and (self.active is self.seed or o.Seed is None):
            o.Seed = target
            self.skipped = []
            self.active = self.skip
            self._changed()
            return
        if self.active is self.skip:
            if point is None:
                point = target.Shape.BoundBox.Center if hasattr(target, "Shape") else None
            if point is None:
                return
            best, best_d = None, None
            for c, _pl, _m in self.found:
                d = (c["point"] - point).Length
                if best_d is None or d < best_d:
                    best, best_d = c, d
            if best is not None:
                self.skip_corner(best["key"], best["key"] not in self.skipped)

    def accept(self):
        o = self.obj
        if o.Seed is None:
            self.show_error("Select the connection element to pattern.")
            return False
        if not _load(o.Instances, []):
            self.show_error(NOT_AT_CORNER if not o.Seed.CornerKey else NO_SIMILAR)
            return False
        o.Document.commitTransaction()
        self._close()
        return True


def pattern():
    doc = App.ActiveDocument
    if doc is None:
        return
    seed = next((s.Object for s in Gui.Selection.getSelectionEx() if _kind(s.Object) == "ConnectionElement"), None)
    doc.openTransaction(PATTERN_TITLE)
    try:
        obj = make_pattern(doc)
        obj.Seed = seed
        Gui.Control.showDialog(PatternPanel(obj, True))
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise


# ================================================================ commands
def _idle():
    try:
        return not Gui.Control.activeDialog()
    except Exception:
        return True


def _has_system(doc):
    return doc is not None and any(s.Primaries for s in systems(doc))


class DefineCommand:
    def GetResources(self):
        return {"Pixmap": _ff_icon("link.svg"), "MenuText": "Define Connection Element",
                "ToolTip": "Makes this part a connection element: the references that place it and the features "
                           "that cut the members."}

    def IsActive(self):
        doc = App.ActiveDocument
        return doc is not None and not systems(doc) and _idle()

    def Activated(self):
        define()


class InsertCommand:
    def GetResources(self):
        return {"Pixmap": _ff_icon("box.svg", "WE_InsertConnection"), "MenuText": "Insert Connection Element",
                "ToolTip": "Places a connection element on the Structure System's members."}

    def IsActive(self):
        return _has_system(App.ActiveDocument) and _idle()

    def Activated(self):
        insert()


class PatternCommand:
    def GetResources(self):
        return {"Pixmap": _ff_icon("list-add.svg"), "MenuText": "Pattern Connection Element",
                "ToolTip": "Copies a connection element at a corner to the similar corners."}

    def IsActive(self):
        doc = App.ActiveDocument
        return doc is not None and bool(elements(doc)) and _idle()

    def Activated(self):
        pattern()


def register():
    for name, cmd in ((DEFINE_COMMAND, DefineCommand()), (INSERT_COMMAND, InsertCommand()),
                      (PATTERN_COMMAND, PatternCommand())):
        if name not in Gui.listCommands():
            Gui.addCommand(name, cmd)
