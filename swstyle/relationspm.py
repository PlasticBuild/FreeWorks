# SPDX-License-Identifier: LGPL-2.1-or-later
""




























from . import editobj

_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import math
import string

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import contextbar, icons
try:  # Decision 35: stock FreeCAD keeps the automatic part references in fwsketch's record
    from .fwsketch import references as _fw_references
except Exception:
    _fw_references = None
try:
    from .fwsketch import silhouette as _fw_silhouette
except Exception:
    _fw_silhouette = None
try:  # Decision 35: Equal Curve Length's stand-in on stock FreeCAD (line follows the arc)
    from .fwsketch import curvelength as _fw_curvelength
except Exception:
    _fw_curvelength = None
try:  # hidden helper geometry (arc Midpoint, arc slot centre arc): not listed, not counted (review 1119)
    from .fwsketch import helpers as _fw_helpers
except Exception:
    _fw_helpers = None
try:
    from .fwsketch import eqcurv as _fw_eqcurv
except Exception:
    _fw_eqcurv = None
from .widgets import alive, ui_font
from . import geomkeep

Qt = QtCore.Qt

PAGE = "Relations"      # page id in the left pane
PM_TAB = 1              # the PropertyManager tab of the left pane
UNDEF = -2000           # FreeCAD's GeoUndef
NONE, START, END, MID = 0, 1, 2, 3
SKETCH_PARAMS = "User parameter:BaseApp/Preferences/Mod/Sketcher"


ORDER = ("Horizontal", "Vertical", "Collinear", "Coradial", "Perpendicular", "Parallel", "Tangent",
         "Concentric", "Midpoint", "Intersection", "Coincident", "Equal", "Symmetric", "Pierce", "Fix",
         "Merge", "Equal Curve Length", "Equal Curvature")

_equal_curve_length = None


def equal_curve_length():
    ""


    global _equal_curve_length
    forced = App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks/NativeFeatures")
    if forced.GetBool("equal_curve_length", False) or not forced.GetBool("equal_curve_length", True):
        return forced.GetBool("equal_curve_length", False)
    if _equal_curve_length is None:
        try:
            import Part
            import Sketcher
            V = App.Vector
            s = Sketcher.Sketch()
            s.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 0, 0)))
            s.addGeometry(Part.ArcOfCircle(Part.Circle(V(20, 0, 0), V(0, 0, 1), 5), 0, 1.0))
            ok = s.addConstraint(Sketcher.Constraint("Equal", 0, 1)) >= 0 and s.solve() == 0
            line, arc = s.Geometries
            _equal_curve_length = ok and abs(line.length() - arc.length()) < 1e-6
        except Exception:
            _equal_curve_length = False
    return _equal_curve_length



_TYPES = {
    "LineSegment": ("Line", "line"),
    "Circle": ("Arc", "arc"),
    "ArcOfCircle": ("Arc", "arc"),
    "Ellipse": ("Ellipse", "curve"),
    "ArcOfEllipse": ("Ellipse", "curve"),
    "ArcOfParabola": ("Parabola", "curve"),
    "ArcOfHyperbola": ("Conic", "curve"),
    "BSplineCurve": ("Spline", "curve"),
    "Point": ("Point", "point"),
}

_TITLES = {"LineSegment": "Line Properties", "Circle": "Circle", "ArcOfCircle": "Arc",
           "Ellipse": "Ellipse", "ArcOfEllipse": "Ellipse", "ArcOfParabola": "Parabola",
           "ArcOfHyperbola": "Conic", "BSplineCurve": "Spline", "Point": "Point"}


# --------------------------------------------------------------------------- picked items
class Item:
    """One picked sketch element. kind: line (lines and the axes), arc (circles and
    arcs), curve (ellipses, conics, splines) or point. geo/pos follow FreeCAD: own
    geometry from 0, axes -1 and -2, external geometry from -3; pos 0 is the edge."""

    __slots__ = ("sub", "kind", "geo", "pos", "name", "cls", "axis", "root", "construction",
                 "model", "pierce", "refs", "at", "ends")

    def __init__(self, sub, kind, geo, pos, name, cls="", axis=False, root=False, construction=False,
                 model=None, pierce=False):
        self.sub, self.kind, self.geo, self.pos, self.name = sub, kind, geo, pos, name
        self.cls, self.axis, self.root, self.construction = cls, axis, root, construction
        # model: (object name, element) of a part edge or corner, or another sketch's
        # entity, picked while in the sketch; geo is a stand-in until it is referenced.

        self.model, self.pierce = model, pierce
        self.refs = ()      # keys of the sketch's references to that element, for its relations
        self.at = None      # a point's place (x, y); an own element's end and centre places (ends)
        self.ends = ()

    @property
    def own(self):
        """Sketch geometry that can move (not the origin, an axis or external geometry)."""
        return self.geo >= 0

    @property
    def key(self):
        return ("e", self.geo) if self.pos == NONE else ("p", self.geo, self.pos)

    @property
    def standalone_point(self):
        return self.own and self.cls == "Point"

    def __repr__(self):
        return "Item(%s %s %d/%d)" % (self.name, self.kind, self.geo, self.pos)


def _class(geo):
    return geo.__class__.__name__


def _entity_names(geometry):
    ""
    counts, names = {}, []
    for geo in geometry:
        if _fw_helpers is not None and _fw_helpers.is_helper(geo):
            names.append("")
            continue
        base = _TYPES.get(_class(geo), ("Sketch Entity", "curve"))[0]
        counts[base] = counts.get(base, 0) + 1
        names.append("%s%d" % (base, counts[base]))
    return names


def sketch_element(obj, sub, sketch):
    """The sketch's own element named by a selection or preselection entry ('Edge1'), '' for the
    whole sketch, else None. A sketch opened from a picked plane is edited through its Body:
    the entry is then Body with 'Sketch.Edge1', not Sketch with 'Edge1' (spline thread fix09)."""
    try:
        if obj is None or sketch is None or obj.Document.Name != sketch.Document.Name:
            return None
        name = obj.Name
    except Exception:
        return None
    # a mapped element name ('Sketch.;g2;SKT.Edge2') carries its old-style name last
    parts = [p for p in (sub or "").split(".") if not p.startswith(";")] or [""]
    if name == sketch.Name:
        return parts[-1]
    if len(parts) >= 2 and parts[-2] == sketch.Name:
        return parts[-1]
    return None


def preselected_element(sketch):
    """sketch_element() of the preselection, else None."""
    try:
        pre = Gui.Selection.getPreselection()
        doc = App.getDocument(pre.DocumentName) if pre.DocumentName else None
        obj = doc.getObject(pre.ObjectName) if doc is not None else None
        for sub in pre.SubElementNames or ("",):
            element = sketch_element(obj, sub, sketch)
            if element:
                return element, (pre.PickedPoints[0] if pre.PickedPoints else None)
    except Exception as _fw_err:
        _fw_log("relationspm.py:206", _fw_err)
    return None


def picked_subs(sketch):
    """The picked elements of the sketch in edit, in picking order ('Edge1', 'Vertex3'...)."""
    out = []
    try:
        selection = Gui.Selection.getSelectionEx()
    except Exception as _fw_err:
        _fw_log("relationspm.py:217", _fw_err)
        return out
    for entry in selection:
        for sub in entry.SubElementNames:
            element = sketch_element(entry.Object, sub, sketch)
            if element:
                out.append(element)
    return out


def picked_relations(sketch):
    """Constraint indices of the relations picked in the sketch in edit (their glyphs: 'Constraint5'
    is index 4)."""
    out = set()
    try:
        selection = Gui.Selection.getSelectionEx()
    except Exception as _fw_err:
        _fw_log("relationspm.py:234", _fw_err)
        return out
    for entry in selection:
        if getattr(entry, "Object", None) is not sketch:
            continue
        for sub in entry.SubElementNames:
            name = sub.split(".")[-1]
            if name.startswith("Constraint") and name[10:].isdigit():
                out.add(int(name[10:]) - 1)
    return out


MODEL_PREFIX = "@"      # picked_with_model(): "@Pad.Edge3" is Edge3 of Pad
MODEL_GEO = -100000     # stand-in geo of the first model pick (not own, not an axis or external)


def picked_with_model(sketch):
    ""


    out = picked_subs(sketch)
    try:
        selection = Gui.Selection.getSelectionEx()
    except Exception as _fw_err:
        _fw_log("relationspm.py:258", _fw_err)
        return out
    for entry in selection:
        obj = entry.Object
        if obj is None or obj.Document.Name != sketch.Document.Name or obj.Name == sketch.Name:
            continue
        for sub in (entry.SubElementNames or ("",)):
            if sub and sketch_element(obj, sub, sketch) is not None:
                continue        # the sketch's own, picked through its Body
            element = sub.rsplit(".", 1)[-1] if sub else ""
            if element.startswith(("Edge", "Vertex")):
                out.append("%s%s.%s" % (MODEL_PREFIX, obj.Name, element))
                continue
            # a plane, axis or reference point picked as a whole (in the tree, or Body > Origin > Front Plane)
            parts = [p for p in sub.split(".") if p and not p.startswith(";")]
            target = sketch.Document.getObject(parts[-1]) if parts else obj
            key = "%s%s." % (MODEL_PREFIX, target.Name) if target is not None else None
            if key and key not in out and target.Name != sketch.Name and _reference_geometry(target):
                out.append(key)
    return out


def _reference_geometry(obj):
    """'plane', 'line' or 'point' for a plane, axis or reference point (the origin's, a datum), else None."""
    try:
        for kind, types in (("plane", ("App::Plane", "PartDesign::Plane", "Part::DatumPlane")),
                            ("line", ("App::Line", "PartDesign::Line", "Part::DatumLine")),
                            ("point", ("App::Point", "PartDesign::Point", "Part::DatumPoint"))):
            if any(obj.isDerivedFrom(t) for t in types):
                return kind
    except Exception as _fw_err:
        _fw_log("relationspm.py:ref-geometry", _fw_err)
    return None


def _reference_item(sketch, sub, obj, count):
    """Item for a whole plane, axis or reference point picked in the sketch: a plane upright to the sketch is
    the line it is seen as, an axis its line in the sketch (or the point an upright one pierces), a reference
    point a point. A plane parallel to the sketch relates to nothing: None."""
    kind = _reference_geometry(obj)
    if kind is None:
        return None
    _origin, normal = _sketch_frame(sketch)
    rot = obj.getGlobalPlacement().Rotation
    geo = MODEL_GEO - count
    label = obj.Label
    if kind == "plane":
        if abs(rot.multVec(App.Vector(0, 0, 1)).dot(normal)) > 1 - 1e-6:
            return None
        item = Item(sub, "line", geo, NONE, label, "LineSegment", axis=True, model=(obj.Name, ""))
    elif kind == "line":
        local = App.Vector(1, 0, 0) if obj.isDerivedFrom("App::Line") else App.Vector(0, 0, 1)
        along = abs(rot.multVec(local).dot(normal))
        if along > 1 - 1e-6:

            # edge (refpierce-fix01; it was a point offering Coincident / Horizontal / Vertical)
            item = Item(sub, "pierce", geo, NONE, label, "LineSegment", model=(obj.Name, ""), pierce=True)
        else:

            item = Item(sub, "line", geo, NONE, label, "LineSegment", axis=True, model=(obj.Name, ""),
                        pierce=along > 1e-6)
    else:
        item = Item(sub, "point", geo, START, label, "Point", model=(obj.Name, ""))
    item.refs = _references_of(sketch, obj.Name, "")
    return item


def _sketch_frame(sketch):
    """(origin, normal) of the sketch plane in the document."""
    placement = sketch.getGlobalPlacement()
    return placement.Base, placement.Rotation.multVec(App.Vector(0, 0, 1))


def _model_shape(obj, element):
    import Part
    return Part.getShape(obj, element, needSubElement=True, retType=0)


def _model_item(sketch, sub, count):
    """Item for '@Object.Element', or None when it cannot be related."""
    name, element = sub[len(MODEL_PREFIX):].split(".", 1)
    obj = sketch.Document.getObject(name)
    if obj is None:
        return None
    if not element:
        return _reference_item(sketch, sub, obj, count)
    shape = _model_shape(obj, element)
    geo = MODEL_GEO - count
    origin, normal = _sketch_frame(sketch)
    label = obj.Label
    if element.startswith("Vertex"):
        if obj.isDerivedFrom("Sketcher::SketchObject"):
            return None     # another sketch's points are picked as its edges' ends in FreeCAD
        item = Item(sub, "point", geo, START, "Vertex<%s>@%s" % (element[6:], label), "Point",
                    model=(name, element))
        item.refs = _references_of(sketch, name, element)
        return item
    edge = shape
    curve = edge.Curve
    cls = _class(curve)
    across = [abs((v.Point - origin).dot(normal)) for v in edge.Vertexes] or [0.0]
    spread = max(across) - min(across) if len(across) > 1 else 0.0
    flat = True
    if cls in ("Line", "LineSegment"):
        direction = edge.Vertexes[-1].Point - edge.Vertexes[0].Point
        flat = direction.Length < 1e-9 or abs(direction.normalize().dot(normal)) < 1e-6
        upright = not flat and abs(direction.dot(normal)) > 1 - 1e-6
        kind = "pierce" if upright else "line"      # an upright line shows as a point in the sketch
        cls = "LineSegment"
    elif cls in ("Circle", "ArcOfCircle"):
        flat = abs(curve.Axis.normalize().dot(normal)) > 1 - 1e-6
        kind = "arc" if flat else "curve"
        cls = "Circle" if edge.isClosed() else "ArcOfCircle"
    else:
        flat = spread < 1e-7
        kind = "curve"
    pierce = False
    if not flat:

        # plane gets "No intersection found for pierce point." when Pierce is clicked
        pierce = True if _pierce_point(sketch, obj, element) is not None else MISSED
    if obj.isDerivedFrom("Sketcher::SketchObject"):
        try:
            index = int(element[4:]) - 1
            title = _entity_names(obj.Geometry)[index]
        except Exception:
            title = element
        title = "%s@%s" % (title, label)
    else:
        title = "Edge<%s>@%s" % (element[4:], label)
    if _fw_silhouette is not None and _fw_silhouette.is_silhouette(obj):
        title = _fw_silhouette.name_of(obj)
    item = Item(sub, kind, geo, NONE, title, cls, model=(name, element), pierce=pierce)
    item.refs = _references_of(sketch, name, element)
    return item


def _external_ref(sketch, g):
    """(object name, element) an external geometry comes from, and whether it is a hidden
    reference; (None, None, False) when unknown."""
    try:
        ref, automatic = sketch.getExternalReference(g)
    except Exception:
        if _fw_references is None:
            return None, None, False
        name, element = _fw_references.ref_of(sketch, g)
        if name is None:
            return None, None, False
        ref, automatic = "%s.%s" % (name, element), _fw_references.is_automatic(sketch, g)
    if "." not in ref:
        return None, None, bool(automatic)
    name, element = ref.split(".", 1)
    return name, element.rsplit(";", 1)[-1].rsplit(".", 1)[-1], bool(automatic)


def _references_of(sketch, name, element):
    """Keys of the sketch's external geometry made from that element."""
    out = []
    for k in range(2, len(sketch.ExternalGeo)):
        g = -k - 1
        if _external_ref(sketch, g)[:2] == (name, element):
            point = _class(sketch.ExternalGeo[k]) == "Point"
            out.append(("p", g, START) if point else ("e", g))
    return tuple(out)


def _reference_name(sketch, g):
    ""
    name, element, _automatic = _external_ref(sketch, g)
    obj = sketch.Document.getObject(name) if name else None
    if obj is not None and not element and _reference_geometry(obj):
        return obj.Label
    if obj is None or not element:
        return None
    obj = getattr(obj, "FWExtRefOf", None) or obj      # a solid outside the Body: named, not its hidden binder
    if obj.isDerivedFrom("Sketcher::SketchObject") and element.startswith("Edge"):
        try:
            return "%s@%s" % (_entity_names(obj.Geometry)[int(element[4:]) - 1], obj.Label)
        except Exception as _fw_err:
            _fw_log("relationspm.py:377", _fw_err)
    for base in ("Edge", "Vertex"):
        if element.startswith(base):
            if _fw_silhouette is not None and _fw_silhouette.is_silhouette(obj):
                return _fw_silhouette.name_of(obj)
            return "%s<%s>@%s" % (base, element[len(base):], obj.Label)
    return None


MISSED = "missed"      # Item.pierce: off the sketch plane, but it never crosses it
NO_PIERCE = "No intersection found for pierce point."
MESSAGES = []           # tests: a callable taking the text answers the dialog


def no_pierce_dialog():
    ""
    for hook in MESSAGES:
        return hook(NO_PIERCE)
    QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "FreeCAD", NO_PIERCE)


def _pierce_point(sketch, obj, element):
    """Where the edge crosses the sketch plane, in sketch coordinates (nearest the sketch
    origin when it crosses more than once), or None."""
    import Part
    origin, normal = _sketch_frame(sketch)
    if not element and _reference_geometry(obj) == "line":
        # a whole axis (origin or reference): its line, unbounded, meets the plane once (refpierce-fix01)
        try:
            e = Part.getShape(obj).Edges[0]
            p, d = App.Vector(e.Curve.Location), App.Vector(e.Curve.Direction)
            den = d.dot(normal)
            if abs(den) < 1e-12:
                return None
            hit = p + d * ((origin - p).dot(normal) / den)
            return sketch.getGlobalPlacement().inverse().multVec(hit)
        except Exception as _fw_err:
            _fw_log("relationspm.py:pierce-axis", _fw_err)
            return None
    edge = _model_shape(obj, element)
    size = max(edge.BoundBox.DiagonalLength, 1.0) * 4 + origin.distanceToPoint(edge.BoundBox.Center) * 2
    plane = Part.makePlane(size, size, origin - _in_plane(normal, size / 2), normal)
    try:
        points = [v.Point for v in edge.section(plane).Vertexes]
    except Exception:
        return None
    if not points:
        return None
    inverse = sketch.getGlobalPlacement().inverse()
    local = [inverse.multVec(p) for p in points]
    return min(local, key=lambda v: v.Length)


def _in_plane(normal, half):
    """A corner offset that centres a makePlane() square on its origin."""
    rotation = App.Rotation(App.Vector(0, 0, 1), normal)
    return rotation.multVec(App.Vector(half, half, 0))


def items_of(sketch, subs):
    """[Item] for the picked sketch geometry; constraints and anything else are left out."""
    geometry = sketch.Geometry
    names = None
    out = []
    models = 0
    for sub in subs:
        try:
            if sub.startswith(MODEL_PREFIX):
                item = _model_item(sketch, sub, models)
                if item is not None:
                    out.append(item)
                    models += 1
            elif sub.startswith("Edge"):
                g = int(sub[4:]) - 1
                if names is None:
                    names = _entity_names(geometry)
                cls = _class(geometry[g])
                kind = _TYPES.get(cls, ("", "curve"))[1]
                out.append(Item(sub, kind, g, NONE, names[g], cls,
                                construction=bool(sketch.getConstruction(g))))
            elif sub.startswith("ExternalEdge"):
                k = int(sub[12:]) - 1
                cls = _class(sketch.ExternalGeo[k + 2])     # the two axes come first
                kind = _TYPES.get(cls, ("", "curve"))[1]
                out.append(Item(sub, kind, -3 - k, NONE, "Edge<%d>" % (k + 1), cls))
            elif sub.startswith("Vertex"):
                v = int(sub[6:]) - 1
                g, pos = sketch.getGeoVertexIndex(v)
                if g == UNDEF:
                    continue
                if g == -1 and pos == START:
                    out.append(Item(sub, "point", -1, START, "Point1@Origin", "Point", root=True))
                    continue
                cls = _class(geometry[g]) if g >= 0 else ""
                name = "Point%d" % (v + 1) if g >= 0 else "Vertex<%d>" % (v + 1)
                construction = cls == "Point" and bool(sketch.getConstruction(g))
                out.append(Item(sub, "point", g, int(pos), name, cls, construction=construction))
            elif sub == "RootPoint":
                out.append(Item(sub, "point", -1, START, "Point1@Origin", "Point", root=True))
            elif sub == "H_Axis":
                out.append(Item(sub, "line", -1, NONE, "Horizontal axis", "LineSegment", axis=True))
            elif sub == "V_Axis":
                out.append(Item(sub, "line", -2, NONE, "Vertical axis", "LineSegment", axis=True))
        except Exception as _fw_err:
            _fw_log("relationspm.py:472", _fw_err)
            continue
    for item in out:
        # where each own point sits, and where each own element's ends sit (window_items: a box
        # also takes the ends of the unpicked neighbours that meet a picked segment there)
        try:
            if item.own and item.kind == "point":
                v = sketch.getPoint(item.geo, item.pos)
                item.at = (v.x, v.y)
            elif item.own:
                ends = []
                # a line has no centre point: getPoint(line, 3) gives (0, 0), which made any point at
                # the sketch origin count as the line's own end (Add Relations then offered Fix only)
                for p in ((START, END) if item.kind == "line" else (START, END, MID)):
                    try:
                        v = sketch.getPoint(item.geo, p)
                        ends.append((v.x, v.y))
                    except Exception as _fw_err:
                        _fw_log("relationspm.py:485", _fw_err)
                item.ends = tuple(ends)
        except Exception as _fw_err:
            _fw_log("relationspm.py:488", _fw_err)
    seen, unique = set(), []
    for item in out:
        if item.key not in seen:
            seen.add(item.key)
            unique.append(item)
    return unique


def _spline_of_point(sketch, item):
    ""

    from . import splinepm
    from .fwsketch import splineedit
    g = item.geo
    if item.cls == "Point":
        spline = splineedit.spline_of(sketch, g)
        if spline is None or spline == g or not splinepm.is_fw_spline(sketch, spline):
            return None, None
        p = sketch.Geometry[g]
        return spline, (p.X, p.Y)
    if not splinepm.is_fw_spline(sketch, g) or item.pos not in (START, END):
        return None, None
    p = sketch.getPoint(g, item.pos)
    return g, (p.x, p.y)


def title_for(items):
    if len(items) == 1 and items[0].own:
        return "Point" if items[0].kind == "point" else _TITLES.get(items[0].cls, "Properties")
    return "Properties"


# Icon pack picture for the title of one picked element
_TITLE_ICONS = {"LineSegment": "SKETCH_LINE", "Circle": "SKETCH_CIRCLE", "ArcOfCircle": "SKETCH_CPRPT_ARC",
                "Ellipse": "SKETCH_ELLIPSE", "ArcOfEllipse": "SKETCH_PARTIAL_ELLIPSE",
                "ArcOfParabola": "SKETCH_PARABOLA", "BSplineCurve": "SKETCH_SPLINE"}


def title_icon_family(items):
    if len(items) == 1 and items[0].own:
        return "SKETCH_POINT" if items[0].kind == "point" else _TITLE_ICONS.get(items[0].cls, "CMD_PROPERTIES")
    return "CMD_PROPERTIES"


# --------------------------------------------------------------------------- what fits
def _belongs(point, other):
    """A point of the other element itself (its end, its centre), or another segment's end at the
    same place (a box round two lines of a profile also takes the ends of the neighbours there)."""
    if point.root:
        return False
    if point.geo == other.geo:
        return True
    if point.at is None or point.cls == "Point":
        return False
    return any(abs(point.at[0] - q[0]) < 1e-7 and abs(point.at[1] - q[1]) < 1e-7 for q in other.ends)


def _meet_at_ends(a, b):
    """Two own entities with an end of one where an end of the other is (ends: start, end first)."""
    if not (a.own and b.own) or len(a.ends) < 2 or len(b.ends) < 2:
        return False
    if any(len(e.ends) >= 2 and e.cls == "BSplineCurve" and e.ends[0] == e.ends[1] for e in (a, b)):
        return False        # a closed (periodic) spline has no end
    return any(abs(p[0] - q[0]) < 1e-7 and abs(p[1] - q[1]) < 1e-7 for p in a.ends[:2] for q in b.ends[:2])


def _centerline(lines):
    """The one construction line or axis among three lines, the mirror line of Symmetric."""
    mirrors = [e for e in lines if e.axis or e.construction]
    if len(mirrors) != 1:
        return None
    others = [e for e in lines if e is not mirrors[0]]
    return mirrors[0] if any(e.own for e in others) else None


def window_items(items):
    ""

    whole = [e for e in items if e.kind != "point"]
    ends = [e for e in items if e.kind == "point" and any(_belongs(e, o) for o in whole)]
    if len(ends) < 2:
        return items        # a line and one of its own ends, picked by hand: Fix only, as before
    kept = [e for e in items if e not in ends]
    if sum(e.kind == "line" and not e.construction for e in kept) >= 3:
        # a box round a polygon also takes its construction circle and the origin at its centre;

        kept = [e for e in kept if not e.root and not (e.kind == "arc" and e.construction)]
    return kept or items


def relations_for(items):
    ""
    n = len(items)
    if not n:
        return []
    if any(e.kind == "pierce" for e in items):
        # an edge upright to the sketch plane only shows as a point: Pierce is all that fits
        if n == 2 and items[0].kind != items[1].kind:
            point = next(e for e in items if e.kind != "pierce")
            if point.kind == "point" and point.own:
                return ["Pierce"]
        return []
    lines = [e for e in items if e.kind == "line"]
    arcs = [e for e in items if e.kind == "arc"]
    curves = [e for e in items if e.kind == "curve"]
    points = [e for e in items if e.kind == "point"]
    keys = []
    if n == 1:
        if lines and lines[0].own:
            keys += ["Horizontal", "Vertical"]
    elif len(lines) == n:
        if all(e.own for e in lines):
            keys += ["Horizontal", "Vertical"]
        if any(e.own for e in lines):
            keys += ["Collinear", "Parallel"]
            if n == 2:
                keys += ["Perpendicular"]
            if not any(e.axis for e in lines):
                keys += ["Equal"]
            if n == 3 and _centerline(lines) is not None:
                keys += ["Symmetric"]
    elif len(points) == n:
        if any(e.own for e in points):
            keys += ["Horizontal", "Vertical"]
            if n == 2 and not (points[0].geo == points[1].geo and not points[0].root and not points[1].root):
                fixed = any(e.root or e.model for e in points)     # the origin, a part corner
                keys += ["Coincident"] if fixed else ["Coincident", "Merge"]
    elif len(arcs) == n:
        if any(e.own for e in arcs):
            if n == 2:
                keys += ["Tangent"]
            keys += ["Concentric", "Coradial", "Equal"]
            # Equal Curve Length for two arcs (stock-05)
            if n == 2 and _fw_curvelength is not None and all(e.cls == "ArcOfCircle" for e in arcs):
                keys += ["Equal Curve Length"]
    elif n == 2 and len(points) == 1:
        point = points[0]
        other = next(e for e in items if e is not point)
        if (point.own or other.own) and not _belongs(point, other):
            if other.kind == "arc":
                keys += ["Concentric"]
            if other.kind == "line" and not other.axis:
                keys += ["Midpoint"]
            keys += ["Coincident"]
            if other.pierce and point.own:
                keys += ["Pierce"]
    elif n == 2 and not points:
        # line and arc/curve, arc and curve, two curves
        if any(e.own for e in items) and len(lines) < 2:
            keys += ["Tangent"]
            if len(lines) == 1 and len(arcs) == 1 and arcs[0].cls == "ArcOfCircle" and not lines[0].axis \
                    and (equal_curve_length() or _fw_curvelength is not None):
                keys += ["Equal Curve Length"]      # the line as long as the arc (studies 06, 07)
        # a spline meeting an arc, a line or a spline at its end: the same curvature there
        if _fw_eqcurv is not None and any(e.cls == "BSplineCurve" for e in items) \
                and all(e.cls in ("BSplineCurve", "ArcOfCircle", "LineSegment") and not e.axis for e in items) \
                and _meet_at_ends(items[0], items[1]):
            keys += ["Equal Curvature"]
    elif n == 3 and len(lines) == 1 and len(arcs) == 2 and (lines[0].construction or lines[0].axis):

        if any(e.own for e in arcs):
            keys += ["Symmetric"]
    elif n == 3 and len(points) == 2 and len(lines) == 1:
        if any(e.own for e in points) and not all(_belongs(p, lines[0]) for p in points):
            keys += ["Symmetric"]
    elif n == 3 and len(lines) == 2 and len(points) == 1:
        if points[0].own:
            keys += ["Intersection"]
    if all(e.own for e in items):
        keys += ["Fix"]
    return sorted(dict.fromkeys(keys), key=ORDER.index)


# --------------------------------------------------------------------------- existing relations
def _ref(g, p):
    return ("e", g) if p == NONE else ("p", g, p)


def _is_point_geo(sketch, g):
    try:
        return g >= 0 and _class(sketch.Geometry[g]) == "Point"
    except Exception:
        return False


def _is_line(sketch, g):
    if g in (-1, -2):
        return True
    try:
        geo = sketch.Geometry[g] if g >= 0 else sketch.ExternalGeo[-g - 1]
        return _class(geo) == "LineSegment"
    except Exception:
        return False


def _is_arc(sketch, g):
    try:
        geo = sketch.Geometry[g] if g >= 0 else sketch.ExternalGeo[-g - 1]
        return _class(geo) in ("Circle", "ArcOfCircle")
    except Exception:
        return False


def _is_spline(sketch, g):
    try:
        geo = sketch.Geometry[g] if g >= 0 else sketch.ExternalGeo[-g - 1]
        return _class(geo) == "BSplineCurve"
    except Exception:
        return False


def _is_round(sketch, g):
    """An arc, circle, ellipse or elliptic arc: its point 3 is a centre."""
    try:
        geo = sketch.Geometry[g] if g >= 0 else sketch.ExternalGeo[-g - 1]
        return _class(geo) in ("Circle", "ArcOfCircle", "Ellipse", "ArcOfEllipse")
    except Exception:
        return False


def constraint_keys(sketch, c):
    ""
    t = c.Type
    f, fp, s, sp, th, tp = c.First, int(c.FirstPos), c.Second, int(c.SecondPos), c.Third, int(c.ThirdPos)
    same_line_ends = f == s and f != UNDEF and {fp, sp} == {START, END}
    if t == "InternalAlignment":
        return None
    if _fw_helpers is not None and _fw_helpers.refers_to_helper(sketch, c):
        return None         # a hidden helper's relation (review 1119)
    if t in ("Horizontal", "Vertical"):
        if s == UNDEF or same_line_ends:
            return [("e", f)]
        return [_ref(f, fp), _ref(s, sp)]
    if t in ("Parallel", "Equal", "Perpendicular", "Tangent", "Angle"):
        return [("e", f)] + ([("e", s)] if s != UNDEF else [])
    if t == "Symmetric":
        if same_line_ends:
            return [("e", f), _ref(th, tp)]
        return [_ref(f, fp), _ref(s, sp), _ref(th, tp)]
    if t == "Block":
        return [("p", f, START) if _is_point_geo(sketch, f) else ("e", f)]
    if t in ("Distance", "DistanceX", "DistanceY"):
        if s == UNDEF:
            return [("e", f)] if fp == NONE else [_ref(f, fp), ("p", -1, START)]
        if same_line_ends:
            return [("e", f)]
        return [_ref(f, fp), _ref(s, sp)]
    if t in ("Radius", "Diameter", "Weight"):
        return [("e", f)]
    out = [_ref(f, fp)]
    if s != UNDEF:
        out.append(_ref(s, sp))
    if th != UNDEF:
        out.append(_ref(th, tp))
    return out


def relation_name(sketch, c):
    ""
    t = c.Type
    f, fp, s, sp, tp = c.First, int(c.FirstPos), c.Second, int(c.SecondPos), int(c.ThirdPos)
    if t == "Coincident":
        if (f == -1 and fp == START) or (s == -1 and sp == START):
            return "Coincident"
        if fp == MID and _is_round(sketch, f) and sp == MID and _is_round(sketch, s):
            return "Concentric"         # the centres of two arcs or circles
        if _is_pierce(sketch, f) or _is_pierce(sketch, s):
            return "Pierce"             # where an edge crosses the sketch plane
        if f <= -3 or s <= -3:
            return "Coincident"         # on a corner of the part (external geometry)
        return "Merged"
    if t == "PointOnObject":
        return "Coincident"
    if t == "Tangent":
        return "Collinear" if _is_line(sketch, f) and _is_line(sketch, s) else "Tangent"
    if t == "Equal" and _is_line(sketch, f) != _is_line(sketch, s):
        return "Equal Curve Length"
    if t == "Symmetric":
        return "Midpoint" if f == s and {fp, sp} == {START, END} and tp != NONE else "Symmetric"
    if t == "Block":
        return "Fix"
    if t == "SnellsLaw":
        return "Refraction"
    return t


DIMENSIONS = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle", "Weight")
_DIMENSION_NAMES = {"DistanceX": "Distance", "DistanceY": "Distance"}


def _locks(sketch):
    """FreeCAD's Lock on a point: a driving DistanceX and DistanceY from the origin.
    {index of the first of the two: (both indices, the point's key)}."""
    found = {}
    for i, c in enumerate(sketch.Constraints):
        if c.Type in ("DistanceX", "DistanceY") and c.Second == UNDEF and int(c.FirstPos) != NONE \
                and getattr(c, "Driving", True):
            found.setdefault((c.First, int(c.FirstPos)), {}).setdefault(c.Type, i)
    out = {}
    for (g, p), pair in found.items():
        if len(pair) == 2:
            both = tuple(sorted(pair.values()))
            out[both[0]] = (both, _ref(g, p))
    return out


def _covering(sketch, items, any_of=False):
    picked = {e.key for e in items} | {k for e in items for k in e.refs}

    def covered(keys):
        hits = [k in picked or (k[0] == "p" and k[2] == MID and ("e", k[1]) in picked and _is_round(sketch, k[1]))
                for k in keys]
        return any(hits) if any_of or len(items) == 1 else all(hits)
    return covered


_HELD_GROUPS = (("FWOffset_", "Offset Entities"), ("FWOnEdge_", "On Edge"), ("FWGroup_", None), ("FWMidArc_", "Midpoint"),
                ("FWMidLnC_", "Coincident"), ("FWMidLnM_", "Midpoint"), ("FWInter_", "Intersection"),
                ("FWEqCurv_", "Equal Curvature"))
GROUP_PREFIX = "FWGroup_"

# group (one row in Existing Relations, deleted as one), not a relation per pair
GROUPED = ("Parallel", "Equal", "Collinear", "Coradial")


def _name_group(sketch, key, items, first):
    """Names the relations just added (from index first) FWGroup_<k>_<j> when they make one
    relation over three or more picked entities."""

    # and Equal) is one row, Symmetric<n>, on the arcs and the centerline
    sym_arcs = key == "Symmetric" and any(getattr(e, "cls", "") in ("Circle", "ArcOfCircle") for e in items)
    if (key not in GROUPED and not sym_arcs) or len([e for e in items if e.kind != "point"]) < 3:
        return
    new = list(range(first, len(sketch.Constraints)))
    if len(new) < 2:
        return
    names = {c.Name for c in sketch.Constraints}
    tag = "C" if key == "Coradial" else ("S" if sym_arcs else "")      # a Coradial group is Coincident + Equal pairs
    k = 0
    while any(n.startswith("%s%s%d_" % (GROUP_PREFIX, tag, k)) for n in names):
        k += 1
    for j, i in enumerate(new):
        try:
            sketch.renameConstraint(i, "%s%s%d_%d" % (GROUP_PREFIX, tag, k, j))
        except Exception as _fw_err:
            _fw_log("relationspm.py:801", _fw_err)


def _midline_keys(sketch, indices):
    ""

    hs = _fw_helpers.helper_ids(sketch) if _fw_helpers is not None else set()
    keys = []
    for j in indices:
        c = sketch.Constraints[j]
        for g, p in ((c.First, int(c.FirstPos)), (c.Second, int(c.SecondPos)), (c.Third, int(c.ThirdPos))):
            if g == UNDEF or g in hs:
                continue
            k = _ref(g, p) if p == MID else ("e", g)     # a centre point, else the entity
            if k not in keys:
                keys.append(k)
    return keys


def _held_group(name):
    ""

    for prefix, base in _HELD_GROUPS:
        if name and name.startswith(prefix):
            if prefix in ("FWOnEdge_", GROUP_PREFIX, "FWMidArc_", "FWMidLnC_", "FWMidLnM_", "FWInter_", "FWEqCurv_"):
                return name.rsplit("_", 1)[0] + "_", base
            return name, base
    return None


def existing_relations(sketch, items, everything=False, any_of=False, where=None, merged=False,
                       dimensions=False):
    ""











    covered = where or ((lambda keys: True) if everything else _covering(sketch, items, any_of))
    locks = _locks(sketch)
    in_locks = {j for indices, _ in locks.values() for j in indices}
    counts = {}
    out = []
    patterns = _patterns(sketch)
    for i, c in enumerate(sketch.Constraints):
        if i in in_locks and i not in locks:
            continue        # the second distance of a Lock: listed with the first, as Fix
        group = _pattern_of(c)
        if group is not None and group in patterns and c.Type != "Tangent":
            # fix275: each side's Tangent to the circle is also its own row, Tangent0.. beside

            indices = patterns[group]
            if i != indices[0]:
                continue        # one Patterned relation for the polygon, at its first member
            base, keys = "Patterned", _pattern_keys(sketch, indices)
        elif i in locks:
            indices, point = locks[i]
            base, keys = "Fix", [point]
        elif _fw_curvelength is not None and c.Name.startswith(_fw_curvelength.PREFIX) \
                and _fw_curvelength.pair_of(sketch, i) is not None:
            if c.Name.endswith(_fw_curvelength.ARC):
                continue        # the arc's half: listed with the line's
            line, arc = _fw_curvelength.pair_of(sketch, i)
            indices, base, keys = _fw_curvelength.members(sketch, i), "Equal Curve Length", [("e", line), ("e", arc)]
        elif _held_group(c.Name) is not None:
            prefix, base = _held_group(c.Name)
            indices = tuple(j for j, o in enumerate(sketch.Constraints) if o.Name.startswith(prefix))
            if base is None:            # a relation group: named as its relation
                base = "Coradial" if prefix.startswith(GROUP_PREFIX + "C") else relation_name(sketch, c)
            if i != indices[0]:
                continue        # one row for the whole group, at its first member
            keys = []
            for j in indices:
                for k in constraint_keys(sketch, sketch.Constraints[j]) or ():
                    if k not in keys:
                        keys.append(k)
            if not keys and prefix.startswith(("FWMidLnC_", "FWMidLnM_")):
                keys = _midline_keys(sketch, indices)
            if prefix.startswith(GROUP_PREFIX + "S"):

                ends = []
                for k in keys:
                    k = ("e", k[1]) if k[0] != "e" and k[1] >= 0 and k[2] in (START, END) else k
                    if k not in ends:
                        ends.append(k)
                keys = ends
            if not keys:
                continue
        elif c.Type in DIMENSIONS:
            if not dimensions or c.Type == "Weight":
                continue
            keys = constraint_keys(sketch, c)
            if keys is None:
                continue
            indices, base = (i,), _DIMENSION_NAMES.get(c.Type, c.Type)
        else:
            keys = constraint_keys(sketch, c)
            if keys is None:
                continue
            indices, base = (i,), relation_name(sketch, c)
            if base == "Merged" and not merged:
                continue
        number = counts.get(base, 0)
        counts[base] = number + 1
        if covered(keys):
            out.append((indices, "%s%d" % (base, number)))
    return out


def entity_names(sketch, keys):
    ""
    names = _entity_names(sketch.Geometry)
    vertices = {}
    for v in range(100000):
        try:
            g, pos = sketch.getGeoVertexIndex(v)
        except Exception:
            break
        if g == UNDEF:
            break
        vertices.setdefault((g, int(pos)), v)
    out = []
    for key in keys:
        g = key[1]
        if key[0] == "e":
            if g >= 0:
                out.append(names[g] if g < len(names) else "Sketch Entity")
            else:
                out.append({-1: "Horizontal axis", -2: "Vertical axis"}.get(g) or _reference_name(sketch, g)
                           or "Edge<%d>" % (-2 - g))
        elif g == -1 and key[2] == START:
            out.append("Point1@Origin")
        elif g <= -3 and _reference_name(sketch, g):
            out.append(_reference_name(sketch, g))
        elif (g, key[2]) in vertices:
            v = vertices[(g, key[2])]
            out.append("Point%d" % (v + 1) if g >= 0 else "Vertex<%d>" % (v + 1))
        else:
            out.append("Point")
    return out


def _pattern_of(c):
    try:
        from .fwsketch.polygon import pattern_group
    except Exception:
        return None
    return pattern_group(c.Name)


def _patterns(sketch):
    """{k: (constraint indices)} of the polygons' Patterned relations (fwsketch/polygon.py)."""
    out = {}
    for i, c in enumerate(sketch.Constraints):
        group = _pattern_of(c)
        if group is not None:
            out.setdefault(group, []).append(i)
    return {k: tuple(v) for k, v in out.items()}


def _pattern_keys(sketch, indices):
    keys = []
    for j in indices:
        for key in constraint_keys(sketch, sketch.Constraints[j]) or []:
            if key not in keys:
                keys.append(key)
    return keys


def relation_keys(sketch, indices):
    """The entity keys of a listed relation (a Fix from FreeCAD's Lock: its point)."""
    if len(indices) > 1 and _pattern_of(sketch.Constraints[indices[0]]) is not None:
        return _pattern_keys(sketch, indices)
    first = indices[0]
    lock = _locks(sketch).get(first)
    if lock is not None and tuple(indices) == lock[0]:
        return [lock[1]]
    return constraint_keys(sketch, sketch.Constraints[first]) or []


def relation_entities(sketch, indices):
    """The names of what a listed relation relates."""
    return entity_names(sketch, relation_keys(sketch, indices))


DATUM_TYPES = ("Distance", "DistanceX", "DistanceY", "Angle", "Radius", "Diameter", "Weight", "SnellsLaw")


def entity_rows(sketch, keys):
    """[(name, status, defined in)] of Display/Delete Relations' Entities table (fix58):
    status Fully Defined / Under Defined (Dangling for a lost model element), defined in
    Current Sketch or the model object an external entity comes from."""
    names = entity_names(sketch, keys)
    try:
        free = {(g, int(p)) for g, p in sketch.getGeometryWithDependentParameters()}
    except Exception:
        free = set()
    free_geo = {g for g, _p in free}
    refs = {}
    try:
        refs = external_references(sketch)
    except Exception as _fw_err:
        _fw_log("relationspm.py:981", _fw_err)
    out = []
    for key, name in zip(keys, names):
        g = key[1]
        if g <= -3:
            ref = refs.get(g)
            # no reference left (its model object deleted) is dangling, as the Dangling filter says
            status = "Fully Defined" if ref is not None and ref[2] else "Dangling"
            owner = getattr(ref[0], "Label", "") if ref is not None and ref[0] is not None else "External"
            out.append((name, status, owner))
            continue
        if g < 0:
            out.append((name, "Fully Defined", "Current Sketch"))
            continue
        if key[0] == "e":
            under = g in free_geo
        else:
            under = (g, int(key[2])) in free or (g, 0) in free
        out.append((name, "Under Defined" if under else "Fully Defined", "Current Sketch"))
    return out


def key_of_sub(sketch, sub):
    """The entity key ("e", geo) / ("p", geo, pos) of a picked sketch element name."""
    if sub.startswith("Edge"):
        return ("e", int(sub[4:]) - 1)
    if sub.startswith("ExternalEdge"):
        return ("e", -3 - (int(sub[12:]) - 1))
    if sub.startswith("Vertex"):
        g, pos = sketch.getGeoVertexIndex(int(sub[6:]) - 1)
        return ("p", g, int(pos))
    if sub == "RootPoint":
        return ("p", -1, START)
    if sub == "H_Axis":
        return ("e", -1)
    if sub == "V_Axis":
        return ("e", -2)
    return None


def replace_entity(sketch, index, old, new):
    """Display/Delete Relations > Replace: relation index relates new in place of old (entity
    keys); returns the new relation's index or None (the sketch as it was)."""
    c = sketch.Constraints[index]
    refs = [(c.First, int(c.FirstPos)), (c.Second, int(c.SecondPos)), (c.Third, int(c.ThirdPos))]
    refs = [r for r in refs if r[0] != UNDEF]
    done = False
    out = []
    for g, p in refs:
        hit = not done and g == old[1] and (old[0] == "e" or p == old[2] or (p == NONE and len(old) > 2))
        if hit:
            if new[0] == "e":
                out.append((new[1], NONE if old[0] == "e" else p))
            else:
                out.append((new[1], new[2]))
            done = True
        else:
            out.append((g, p))
    if not done:
        return None
    args = [c.Type] + _args(out)
    if c.Type in DATUM_TYPES:
        args.append(c.Value)
    doc = sketch.Document
    doc.openTransaction("Replace")
    try:
        new_c = _constraint(*args)
        name, driving, active = c.Name, c.Driving, getattr(c, "IsActive", True)
        sketch.delConstraint(index)
        i = sketch.addConstraint(new_c)
        if name:
            sketch.renameConstraint(i, name)
        if not driving:
            sketch.setDriving(i, False)
        if not active:
            sketch.setActive(i, False)
        if sketch.solve() != 0:
            raise ValueError("the sketch cannot take it")
        doc.commitTransaction()
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintWarning("FreeCAD: Replace: %s\n" % error)
        return None
    doc.recompute()
    return i



DD_ALL, DD_BAD, DD_EXTERNAL, DD_SELECTED = (
    "All in this sketch", "Overdefining/Not Solved", "External", "Selected Entities")
DD_DANGLING, DD_CONTEXT, DD_LOCKED, DD_BROKEN = ("Dangling", "Defined in Context", "Locked", "Broken")
DD_FILTERS = (DD_ALL, DD_DANGLING, DD_BAD, DD_EXTERNAL, DD_CONTEXT, DD_LOCKED, DD_BROKEN,
              DD_SELECTED)


def external_references(sketch):
    ""


    out = {}
    k = 0
    try:
        refs = list(sketch.ExternalGeometry)
    except Exception:
        refs = []
    for obj, subs in refs:
        for sub in (subs if isinstance(subs, (list, tuple)) else [subs]):
            found = True
            try:
                if obj is None or not getattr(obj, "isValid", lambda: True)():
                    found = False
                elif sub:
                    obj.Shape.getElement(sub)
            except Exception:
                found = False
            try:
                other = obj is not None and obj.Document is not sketch.Document
            except Exception:
                other = False
            out[-3 - k] = (obj, sub, found, other)
            k += 1
    return out


def _missing_externals(sketch):
    """[(external index k, object, element, stored geometry)] for external geometry whose model
    element is gone (FreeCAD keeps its last geometry with the Missing flag)."""
    out = []
    geos = list(sketch.ExternalGeo)
    for k, geo in enumerate(geos[2:]):
        for ext in geo.getExtensions():
            if not hasattr(ext, "Ref"):
                continue
            try:
                missing = ext.testFlag("Missing")
            except Exception:
                missing = False
            if missing and ext.Ref and "." in ext.Ref:
                name, element = ext.Ref.split(".", 1)
                out.append((k, sketch.Document.getObject(name), element, geo))
    return out


def _match_score(geo, edge, inverse):
    """How far a model edge, seen in the sketch's plane, is from stored external geometry; None
    when they are not the same kind."""
    kind = type(geo).__name__
    curve = type(edge.Curve).__name__
    pts = [inverse.multVec(v.Point) for v in edge.Vertexes]
    if kind == "LineSegment" and curve == "Line" and len(pts) == 2:
        a, b = geo.StartPoint, geo.EndPoint
        p, q = App.Vector(pts[0].x, pts[0].y, 0), App.Vector(pts[1].x, pts[1].y, 0)
        return min((a - p).Length + (b - q).Length, (a - q).Length + (b - p).Length)
    if kind in ("Circle", "ArcOfCircle") and curve == "Circle":
        c = inverse.multVec(edge.Curve.Center)
        score = (geo.Center - App.Vector(c.x, c.y, 0)).Length + abs(geo.Radius - edge.Curve.Radius)
        if kind == "ArcOfCircle" and len(pts) == 2:
            a, b = geo.StartPoint, geo.EndPoint
            p, q = App.Vector(pts[0].x, pts[0].y, 0), App.Vector(pts[1].x, pts[1].y, 0)
            score += min((a - p).Length + (b - q).Length, (a - q).Length + (b - p).Length)
        elif kind == "ArcOfCircle" or len(pts) > 1:
            return None
        return score
    return None


def _size(geo):
    try:
        return max(geo.length(), 1.0)
    except Exception:
        return max(getattr(geo, "Radius", 1.0), 1.0)


def _remap_external(sketch, old, new):
    """Every relation on external geo id old moved to new (the relation kept, its value too)."""
    import Sketcher
    hits = [i for i, c in enumerate(sketch.Constraints) if old in (c.First, c.Second, c.Third)]
    saved = []
    for i in hits:
        c = sketch.Constraints[i]
        refs = [(c.First, int(c.FirstPos)), (c.Second, int(c.SecondPos)), (c.Third, int(c.ThirdPos))]
        refs = [((new if g == old else g), p) for g, p in refs if g != UNDEF]
        args = [c.Type] + _args(refs)
        if c.Type in DATUM_TYPES:
            args.append(c.Value)
        saved.append((args, c.Name, c.Driving))
    for i in sorted(hits, reverse=True):
        sketch.delConstraint(i)
    for args, name, driving in saved:
        k = sketch.addConstraint(Sketcher.Constraint(*args))
        if name:
            try:
                sketch.renameConstraint(k, name)
            except Exception as _fw_err:
                _fw_log("relationspm.py:1175", _fw_err)
        if not driving:
            try:
                sketch.setDriving(k, False)
            except Exception as _fw_err:
                _fw_log("relationspm.py:1180", _fw_err)


def find_replacement(sketch, k, entry=None):
    ""


    if entry is None:
        entry = next((m for m in _missing_externals(sketch) if m[0] == k), None)
    if entry is None:
        return None
    _k, obj, element, geo = entry
    shape = getattr(obj, "Shape", None) if obj is not None else None
    if shape is None or shape.isNull():
        return None
    inverse = sketch.getGlobalPlacement().inverse()
    best = None
    for i, edge in enumerate(shape.Edges):
        try:
            score = _match_score(geo, edge, inverse)
        except Exception:
            score = None
        if score is not None and (best is None or score < best[0]):
            best = (score, i)
    if best is None or best[0] > 0.1 * _size(geo):
        return None
    return obj, "Edge%d" % (best[1] + 1)


def _attach(sketch, k, found):
    """The relations on dangling reference k moved onto found's edge (added as external
    geometry); the dead reference itself stays for the caller to drop. True when done."""
    obj, edge = found
    before = len(sketch.ExternalGeo)
    sketch.addExternal(obj.Name, edge)
    if len(sketch.ExternalGeo) <= before:
        return False
    _remap_external(sketch, -3 - k, -(len(sketch.ExternalGeo)))
    return True


def repair_one(sketch, k, found):
    """Replace with the found entity: one dangling reference re-attached and dropped."""
    if not _attach(sketch, k, found):
        return False
    sketch.delExternal(k)
    sketch.solve()
    return True


def repair_dangling(sketch):
    ""


    missing = _missing_externals(sketch)
    if not missing:
        return 0, 0
    repaired, done = 0, []
    for k, obj, element, geo in missing:
        found = find_replacement(sketch, k, (k, obj, element, geo))
        if found is None or not _attach(sketch, k, found):
            continue
        done.append(k)
        repaired += 1
    for k in sorted(done, reverse=True):
        sketch.delExternal(k)
    sketch.solve()
    return repaired, len(missing) - repaired


def listed_relations(sketch, items, dd=None):
    """The relations the panel lists: the picked items' (dd None or Selected Entities), all of
    the sketch's, those that over-define it, or those to entities outside the sketch (the part's
    edges and other external geometry)."""
    if dd == DD_ALL:
        return existing_relations(sketch, items, everything=True)
    if dd == DD_EXTERNAL:
        return existing_relations(sketch, items, where=lambda keys: any(k[1] <= -3 for k in keys))
    if dd in (DD_DANGLING, DD_CONTEXT, DD_LOCKED, DD_BROKEN):
        refs = external_references(sketch)

        def wanted(ref):
            if ref is None:
                return dd == DD_DANGLING       # an external id the sketch no longer has
            _obj, _sub, found, other = ref
            if dd == DD_DANGLING:
                return not found
            if dd == DD_CONTEXT:
                return other
            if dd == DD_BROKEN:
                return other and not found
            return False                        # FreeCAD has no locked external references
        return existing_relations(sketch, items, where=lambda keys: any(
            k[1] <= -3 and wanted(refs.get(k[1])) for k in keys))
    if dd == DD_BAD:
        try:
            bad = set(sketch.ConflictingConstraints) | set(sketch.RedundantConstraints)
        except Exception:
            bad = set()
        # a shared point that over-defines the sketch is listed too: it may be the one to delete
        return [(ix, name) for ix, name in existing_relations(sketch, items, everything=True, merged=True)
                if any(i + 1 in bad for i in ix)]       # FreeCAD counts from 1 there
    if dd == DD_SELECTED and not items:

        # that relation under Selected Entities (sketch right-click hand check 11-12)
        picked = picked_relations(sketch)
        if picked:
            return [(ix, name) for ix, name in existing_relations(sketch, items, everything=True, merged=True)
                    if picked & set(ix)]
    return existing_relations(sketch, items, any_of=dd == DD_SELECTED, dimensions=dd is None)


def invalid_solution(sketch):
    ""

    try:
        return "Invalid" in sketch.State and not (list(sketch.ConflictingConstraints)
                                                  or list(sketch.RedundantConstraints)
                                                  or list(sketch.MalformedConstraints))
    except Exception:
        return False


SATISFIED, OVER_DEFINING, NOT_SOLVED, DANGLING, SUPPRESSED = (
    "Satisfied", "Over Defining", "Not Solved", "Dangling", "Suppressed")


def relation_status(sketch, indices):
    ""


    try:
        if suppressed(sketch, indices):
            return SUPPRESSED
        conflicting = set(sketch.ConflictingConstraints)
        redundant = set(sketch.RedundantConstraints)
    except Exception:
        conflicting, redundant = set(), set()
    if any(i + 1 in conflicting for i in indices):        # FreeCAD counts from 1 there
        return NOT_SOLVED
    if any(i + 1 in redundant for i in indices):
        return OVER_DEFINING
    refs = None
    for i in indices:
        try:
            keys = constraint_keys(sketch, sketch.Constraints[i]) or []
        except Exception:
            keys = []
        for k in keys:
            if k[1] <= -3:
                if refs is None:
                    refs = external_references(sketch)
                ref = refs.get(k[1])
                if ref is None or not ref[2]:
                    return DANGLING
    return SATISFIED


def _relation_kind(name):
    """'Coincident' for 'Coincident3': the kind behind a listed name (its icon)."""
    base = name.rstrip("0123456789")
    return {"Merged": "Merge"}.get(base, base)


def defined_state(sketch, items):
    ""



    if not any(e.own for e in items):
        return ""       # only part edges or the origin: nothing of the sketch to rate
    if invalid_solution(sketch):
        return "Invalid"
    try:
        conflicting = set(sketch.ConflictingConstraints)
        bad = conflicting | set(sketch.RedundantConstraints)
    except Exception:
        conflicting, bad = set(), set()
    covered = _covering(sketch, items)
    state = None
    for i, c in enumerate(sketch.Constraints):
        keys = constraint_keys(sketch, c) if i + 1 in bad else None   # FreeCAD counts from 1 there
        if keys and covered(keys):
            if i + 1 in conflicting:
                return "Not Solved"
            state = "Over Defined"
    if state:
        return state
    try:
        free = {g for g, _ in sketch.getGeometryWithDependentParameters()}
    except Exception as _fw_err:
        _fw_log("relationspm.py:1376", _fw_err)
        return ""
    if any(e.own and e.geo in free for e in items):
        return "Under Defined"
    return "Fully Defined"


# --------------------------------------------------------------------------- adding relations
def _constraint(*args):
    import Sketcher
    return Sketcher.Constraint(*args)


def _same(c, t, refs):
    """c is a constraint of type t on exactly these (geo, pos) references, in any order."""
    if c.Type != t:
        return False
    mine = [(c.First, int(c.FirstPos)), (c.Second, int(c.SecondPos)), (c.Third, int(c.ThirdPos))]
    mine = sorted(r for r in mine if r[0] != UNDEF)
    return mine == sorted(refs)


def _args(refs):
    """Sketcher.Constraint arguments for (geo, pos) references: edges alone by their geo
    ids (Parallel, Equal), points by geo id and position, and a last edge by its id
    (PointOnObject, Symmetric about a line)."""
    if all(p == NONE for _, p in refs):
        return [g for g, _ in refs]
    out = []
    for i, (g, p) in enumerate(refs):
        out.append(g)
        if p != NONE or i < len(refs) - 1:
            out.append(p)
    return out


def _has(sketch, t, refs):
    return any(_same(c, t, refs) for c in sketch.Constraints)


def _find(sketch, t, refs):
    for i, c in enumerate(sketch.Constraints):
        if _same(c, t, refs):
            return i
    return None


def _related(sketch, t, a, b):
    """A constraint of type t joins edges a and b (at any of their points)."""
    return any(c.Type == t and {c.First, c.Second} == {a, b} for c in sketch.Constraints)


def _joint(sketch, a, b):
    """The relation joining an end of edge a to edge b or to one of its ends:
    ((type, refs) of it, the Tangent's arguments at that point), or None."""
    for c in sketch.Constraints:
        f, fp, s, sp = c.First, int(c.FirstPos), c.Second, int(c.SecondPos)
        if f == s or {f, s} != {a, b}:
            continue
        if c.Type == "Coincident" and fp in (START, END) and sp in (START, END):
            return ("Coincident", [(f, fp), (s, sp)]), (f, fp, s, sp)
        if c.Type == "PointOnObject" and fp in (START, END) and sp == NONE:
            return ("PointOnObject", [(f, fp), (s, NONE)]), (f, fp, s)
    return None


def _tangent(sketch, a, b, units, taken):
    """FreeCAD's Tangent between two edges (two lines: collinear). Where the edges
    already meet, the Tangent goes at that point and takes the place of the relation
    that joined them, as FreeCAD's own Tangent command does."""
    if _related(sketch, "Tangent", a, b):
        return
    joint = _joint(sketch, a, b)
    if joint is not None and joint[0] not in taken:
        taken.append(joint[0])
        args = joint[1]
        if len(args) == 4 and _is_spline(sketch, args[2]) and not _is_spline(sketch, args[0]):
            args = (args[2], args[3], args[0], args[1])     # stock's solver takes a spline's end tangency spline first
        units.append(([("Tangent", args)], [joint[0]]))
    else:
        units.append(([("Tangent", (a, b))], []))


# Horizontal/Vertical on the second line that a new relation with the first line already
# gives: (relation, type on the first line) -> type on the second line.
_IMPLIED = {
    ("Collinear", "Horizontal"): "Horizontal", ("Collinear", "Vertical"): "Vertical",
    ("Parallel", "Horizontal"): "Horizontal", ("Parallel", "Vertical"): "Vertical",
    ("Perpendicular", "Horizontal"): "Vertical", ("Perpendicular", "Vertical"): "Horizontal",
}


def _implied(sketch, key, a, b):
    ""



    out = []
    for t in ("Horizontal", "Vertical"):
        other = _IMPLIED.get((key, t))
        if other and _has(sketch, t, [(a, NONE)]) and _has(sketch, other, [(b, NONE)]):
            out.append((other, [(b, NONE)]))
    return out


def _with_implied(sketch, key, a, b, units, count):
    """Let the units added since count also take out what they make redundant."""
    drops = _implied(sketch, key, a, b)
    if drops and len(units) > count:
        adds, old = units[-1]
        units[-1] = (adds, list(old) + drops)


def plan(sketch, key, items):
    """The relation as units [([(type, args) to add], [(type, refs) to delete])]; each
    unit is kept or left out whole. Relations the sketch already has are left out."""
    units, taken = [], []
    lines = [e for e in items if e.kind == "line"]
    arcs = [e for e in items if e.kind == "arc"]
    points = [e for e in items if e.kind == "point"]
    edges = [e for e in items if e.kind != "point"]

    def pt(e):
        return (e.geo, e.pos)

    def once(t, *refs):
        if not _has(sketch, t, list(refs)):
            units.append(([(t, tuple(_args(refs)))], []))

    if key in ("Horizontal", "Vertical"):
        if lines and len(lines) == len(items):
            for e in lines:
                once(key, (e.geo, NONE))
        elif points and len(points) == len(items):
            first = points[0]
            for e in points[1:]:
                if first.geo == e.geo and first.own and {first.pos, e.pos} == {START, END} \
                        and _is_line(sketch, e.geo):
                    once(key, (e.geo, NONE))
                else:
                    once(key, pt(first), pt(e))
    elif key == "Collinear":
        for e in lines[1:]:
            count = len(units)
            _tangent(sketch, lines[0].geo, e.geo, units, taken)
            _with_implied(sketch, key, lines[0].geo, e.geo, units, count)
    elif key == "Parallel":
        for e in lines[1:]:
            count = len(units)
            once("Parallel", (lines[0].geo, NONE), (e.geo, NONE))
            _with_implied(sketch, key, lines[0].geo, e.geo, units, count)
    elif key == "Perpendicular":
        count = len(units)
        once("Perpendicular", (lines[0].geo, NONE), (lines[1].geo, NONE))
        _with_implied(sketch, key, lines[0].geo, lines[1].geo, units, count)
    elif key == "Tangent":
        _tangent(sketch, edges[0].geo, edges[1].geo, units, taken)
    elif key in ("Concentric", "Coradial"):
        if points:
            once("Coincident", pt(points[0]), (arcs[0].geo, MID))
        else:
            for e in arcs[1:]:
                once("Coincident", (arcs[0].geo, MID), (e.geo, MID))
        if key == "Coradial":
            for e in arcs[1:]:
                once("Equal", (arcs[0].geo, NONE), (e.geo, NONE))
    elif key == "Midpoint":
        line = lines[0]
        once("Symmetric", (line.geo, START), (line.geo, END), pt(points[0]))
    elif key == "Intersection":
        for e in lines:
            once("PointOnObject", pt(points[0]), (e.geo, NONE))
    elif key == "Coincident":
        if len(points) == 2:
            a, b = sorted(points, key=lambda e: e.root)     # the movable point first
            once("Coincident", pt(a), pt(b))
        else:
            once("PointOnObject", pt(points[0]), (edges[0].geo, NONE))
    elif key == "Merge":
        once("Coincident", pt(points[0]), pt(points[1]))
    elif key == "Pierce":
        a, b = sorted(points, key=lambda e: not e.own)      # the sketch point, the crossing
        once("Coincident", pt(a), pt(b))
    elif key == "Equal":
        for e in edges[1:]:
            once("Equal", (edges[0].geo, NONE), (e.geo, NONE))
    elif key == "Equal Curve Length":
        once("Equal", (lines[0].geo, NONE), (arcs[0].geo, NONE))
    elif key == "Symmetric":
        if len(points) == 2:
            once("Symmetric", pt(points[0]), pt(points[1]), (lines[0].geo, NONE))
        elif len(arcs) == 2:
            # symcl-01: two arcs about the centerline: mirrored centres and the same radius (a full circle), or
            # the ends mirrored and the same radius (an arc: the centres follow)
            a, b = arcs
            unit = []
            if any(e.geo >= 0 and _class(sketch.Geometry[e.geo]) == "Circle" for e in arcs):
                if not _has(sketch, "Symmetric", [(a.geo, MID), (b.geo, MID), (lines[0].geo, NONE)]):
                    unit.append(("Symmetric", tuple(_args([(a.geo, MID), (b.geo, MID), (lines[0].geo, NONE)]))))
            else:
                for pa, pb in _mirror_pairs(sketch, a.geo, b.geo, lines[0].geo):
                    if not _has(sketch, "Symmetric", [(a.geo, pa), (b.geo, pb), (lines[0].geo, NONE)]):
                        unit.append(("Symmetric", tuple(_args([(a.geo, pa), (b.geo, pb), (lines[0].geo, NONE)]))))
            if not _has(sketch, "Equal", [(a.geo, NONE), (b.geo, NONE)]):
                unit.append(("Equal", tuple(_args([(a.geo, NONE), (b.geo, NONE)]))))
            if unit:
                units.append((unit, []))
        else:
            mirror = _centerline(lines)
            a, b = [e for e in lines if e is not mirror]
            for pa, pb in _mirror_pairs(sketch, a.geo, b.geo, mirror.geo):
                once("Symmetric", (a.geo, pa), (b.geo, pb), (mirror.geo, NONE))
    elif key == "Fix":
        for e in items:
            if e.kind == "point" and not e.standalone_point:
                # FreeCAD's Lock: the point's distances from the origin
                p = sketch.getPoint(e.geo, e.pos)
                fixes = [(t, (e.geo, e.pos, value)) for t, value in (("DistanceX", p.x), ("DistanceY", p.y))
                         if not _has(sketch, t, [pt(e)])]
                if fixes:
                    units.append((fixes, []))
            else:
                once("Block", (e.geo, NONE))
    return units


def _mirror_pairs(sketch, a, b, mirror):
    """Which end of line b mirrors which end of line a across the mirror line."""
    def point(g, p):
        return sketch.getPoint(g, p)
    if mirror >= 0:
        m0, m1 = point(mirror, START), point(mirror, END)
    else:
        geo = sketch.ExternalGeo[-mirror - 1]
        m0, m1 = geo.StartPoint, geo.EndPoint
    d = m1 - m0
    if d.Length < 1e-9:
        return [(START, START), (END, END)]
    d.normalize()

    def reflect(v):
        w = v - m0
        along = d * w.dot(d)
        return m0 + along * 2 - w

    start_image = reflect(point(a, START))
    near_start = (point(b, START) - start_image).Length <= (point(b, END) - start_image).Length
    return [(START, START), (END, END)] if near_start else [(START, END), (END, START)]


def _preplace(sketch, t, args):
    """Horizontal or Vertical on a line: the line is turned level (or upright) first, its start
    kept, so the solver starts beside the answer. From far off (a 45 degree line held Parallel to
    another) FreeCAD's solver could collapse the line to a point instead (PC diag150b V6)."""
    if t not in ("Horizontal", "Vertical") or len(args) != 1:
        return
    try:
        g = int(args[0])
        geo = sketch.Geometry[g]
    except Exception:
        return
    if type(geo).__name__ != "LineSegment":
        return
    a, b = geo.StartPoint, geo.EndPoint
    d = b - a
    n = d.Length
    if n < 1e-9:
        return
    if t == "Horizontal":
        target = a + App.Vector(n if d.x >= 0 else -n, 0, 0)
    else:
        target = a + App.Vector(0, n if d.y >= 0 else -n, 0)
    if (target - b).Length < 1e-9:
        return
    try:
        sketch.moveGeometry(g, 2, target, False)
    except Exception as _fw_err:
        _fw_log("relationspm.py:1628", _fw_err)


def _apply(sketch, units):
    for adds, drops in units:
        for t, refs in drops:
            i = _find(sketch, t, refs)
            if i is not None:
                sketch.delConstraint(i, True)
        for t, args in adds:
            _preplace(sketch, t, args)
        sketch.addConstraint([_constraint(t, *args) for t, args in adds])


def _state(sketch):
    """(solver result, conflicting, redundant, collapsed curves) after a solve.
    FreeCAD finds redundant relations where the geometry is when it solves, so a
    relation only made redundant by the move (Horizontal on the second of two
    collinear lines) shows on a second solve, from the solved geometry."""
    def collapsed():
        try:
            return sketch.detectDegeneratedGeometries(1e-6)
        except Exception:
            return 0
    code = sketch.solve()
    gone = collapsed()
    if code in (0, -2) and not gone:
        code = sketch.solve()
        gone = collapsed()
    try:
        conflicting, redundant = len(sketch.ConflictingConstraints), len(sketch.RedundantConstraints)
    except Exception:
        conflicting = redundant = 0
    return code, conflicting, redundant, gone


def _worse(after, before):
    """Why the sketch is worse off than before (over, redundant, unsolved), or None.
    A line that collapses to a point counts as over-defining: the solver reaches
    Parallel plus Perpendicular, or Horizontal plus Vertical, that way."""
    code, conflicting, redundant, collapsed = after
    if collapsed > before[3] or conflicting > before[1] or (code in (-3, -4) and code != before[0]):
        return "over"
    if redundant > before[2] or (code == -2 and before[0] != -2):
        return "redundant"
    if code != 0 and code != before[0]:
        return "unsolved"
    return None


def _auto_recompute(sketch):
    try:
        if App.ParamGet(SKETCH_PARAMS).GetBool("AutoRecompute", False):
            sketch.Document.recompute()
    except Exception as _fw_err:
        _fw_log("relationspm.py:1683", _fw_err)


def _referenced(sketch, key, items):
    ""


    out = []
    for e in items:
        if not e.model:
            out.append(e)
            continue
        name, element = e.model
        if key == "Pierce":
            point = next((p for p in items if p.own and p.kind == "point"), None)
            g = _pierce_reference(sketch, name, element, point)
            out.append(Item(e.sub, "point", g, START, e.name, "Point", model=e.model))
            continue
        g = _add_reference(sketch, name, element)
        cls = _class(sketch.ExternalGeo[-g - 1])
        kind = "point" if element.startswith("Vertex") or cls == "Point" else \
            _TYPES.get(cls, ("", "curve"))[1]
        out.append(Item(e.sub, kind, g, START if kind == "point" else NONE, e.name, cls,
                        model=e.model))
    return out


def _add_reference(sketch, name, element):
    ""
    if hasattr(sketch, "addAutomaticReference"):
        return sketch.addAutomaticReference(name, element)
    g = _fw_references.add(sketch, name, element) if _fw_references is not None else None
    if g is None:
        raise ValueError("%s of %s cannot be referenced" % (element, name))
    return g


def _external_point_at(sketch, where, before=0):
    """External point geometry at where (sketch coordinates), from index before on."""
    for k, geo in enumerate(sketch.ExternalGeo):
        if k < max(before, 2) or _class(geo) != "Point":
            continue
        if (App.Vector(geo.X, geo.Y, 0) - App.Vector(where.x, where.y, 0)).Length < 1e-6:
            return -k - 1
    return None


def _pierce_reference(sketch, name, element, point):
    """The external point where the edge pierces the sketch plane (FreeCAD's intersection
    reference), nearest the picked sketch point; an existing one is used again."""
    obj = sketch.Document.getObject(name)
    where = _pierce_point(sketch, obj, element)
    if where is None:
        raise ValueError("the edge does not cross the sketch plane")
    g = _external_point_at(sketch, where)
    if g is not None:
        return g
    count = len(sketch.ExternalGeo)
    sketch.addExternal(name, element, False, True)
    near = sketch.getPoint(point.geo, point.pos) if point is not None else where
    found = [(-k - 1, App.Vector(geo.X, geo.Y, 0)) for k, geo in enumerate(sketch.ExternalGeo)
             if k >= count and _class(geo) == "Point"]
    if not found:
        raise ValueError("the edge does not cross the sketch plane")
    return min(found, key=lambda f: (f[1] - App.Vector(near.x, near.y, 0)).Length)[0]


def _is_pierce(sketch, g):
    """External point geometry made where an edge crosses the sketch plane."""
    if g > -3:
        return False
    try:
        if _class(sketch.ExternalGeo[-g - 1]) != "Point":
            return False
    except Exception:
        return False
    name, element = _external_ref(sketch, g)[:2]
    if name and not element:            # an axis's crossing point (refpierce-fix01)
        obj = sketch.Document.getObject(name)
        return obj is not None and _reference_geometry(obj) == "line"
    return bool(element) and element.startswith("Edge")


def add_relation(sketch, key, items):
    """Add one relation as one undo step. Each part of it (Horizontal for one of
    several lines...) is first tried and taken back; a part that would over-define the
    sketch, or that the other relations already give, is left out. (added, message)."""
    doc = sketch.Document
    if key == "Equal Curve Length" and _fw_curvelength is not None \
            and (not equal_curve_length() or not any(e.kind == "line" for e in items)):
        return _add_curve_length_stock(sketch, items)
    if key == "Equal Curvature" and _fw_eqcurv is not None:
        return _add_equal_curvature(sketch, items)
    # Part edges and other sketches' entities are referenced with each try and taken
    # back with it; the references come out the same each time (added at the end).
    picked = items
    models = [e for e in items if e.model]
    trying = bool(models) and bool(doc.UndoMode)
    if trying:
        doc.openTransaction("Check relation")
    try:
        if models:
            items = _referenced(sketch, key, items)
        units = plan(sketch, key, items)
    except Exception as error:
        units, failure = None, "%s could not be added: %s" % (key, error)
    if trying:
        doc.abortTransaction()
        sketch.solve()
    if units is None:
        return False, failure
    if not units:
        return False, "The selection already has the %s relation." % key
    accepted, reasons, clashes = [], [], []
    if doc.UndoMode:
        base = _state(sketch)
        for unit in units:
            doc.openTransaction("Check relation")
            try:
                if models:
                    _referenced(sketch, key, picked)
                existing = len(sketch.Constraints)
                _apply(sketch, accepted + [unit])
                reason = _worse(_state(sketch), base)
                if reason == "over":
                    _add_clashes(sketch, existing, clashes)
            except Exception as error:
                reason = "error: %s" % error
            doc.abortTransaction()
            if reason is None:
                accepted.append(unit)
            else:
                reasons.append(reason)
        sketch.solve()
    else:
        accepted = units     # no undo to try with (FreeCAD without its GUI)
    if not accepted:
        if all(r == "redundant" for r in reasons):
            return False, "Not added: the sketch's other relations already give that."
        if "over" in reasons:
            return False, "Not added: %s would over-define the sketch.%s" % (key, _clash_text(clashes))
        return False, "Not added: %s conflicts with the sketch's other relations." % key
    before = _state(sketch)
    doc.openTransaction("Add %s Relation" % key)
    try:
        if models:
            _referenced(sketch, key, picked)
        existing = len(sketch.Constraints)
        _apply(sketch, accepted)
        reason = _worse(_state(sketch), before) if doc.UndoMode else None
        if reason == "over":
            _add_clashes(sketch, existing, clashes)
    except Exception as error:
        doc.abortTransaction()
        sketch.solve()
        return False, "%s could not be added: %s" % (key, error)
    if reason is not None:          # the parts together do what none did alone
        doc.abortTransaction()
        sketch.solve()
        return False, "Not added: %s would over-define the sketch.%s" % (key, _clash_text(clashes))
    _name_group(sketch, key, picked, len(sketch.Constraints) - sum(len(adds) for adds, _d in accepted))
    if key == "Intersection" and _fw_helpers is not None:      # fix279: one Intersection row
        _fw_helpers.name_intersections(sketch, existing)
    doc.commitTransaction()
    _auto_recompute(sketch)
    if reasons and all(r == "redundant" for r in reasons):
        return True, "%s added where it fits; the other relations already give the rest." % key
    if reasons:
        return True, "%s added where it fits; the rest would over-define the sketch." % key
    return True, ""


def _add_curve_length_stock(sketch, items):
    """Equal Curve Length on stock FreeCAD (fwsketch/curvelength.py), one undo step."""
    doc = sketch.Document
    lines = [e for e in items if e.kind == "line"]
    arcs = [e for e in items if e.kind == "arc"]
    # the line follows the arc; of two arcs, the second picked follows the first
    line, arc = (lines[0].geo, arcs[0].geo) if lines else (arcs[1].geo, arcs[0].geo)
    if any({l, a} == {line, arc} for l, a, _k, _m in _fw_curvelength.pairs(sketch)):
        return False, "The selection already has the Equal Curve Length relation."
    before = _state(sketch)
    doc.openTransaction("Add Equal Curve Length Relation")
    try:
        existing = len(sketch.Constraints)
        _fw_curvelength.add(sketch, line, arc)
        reason = _worse(_state(sketch), before)
    except Exception as error:
        doc.abortTransaction()
        sketch.solve()
        return False, "Equal Curve Length could not be added: %s" % error
    if reason is not None:
        clashes = []
        if reason == "over":
            _add_clashes(sketch, existing, clashes)
        doc.abortTransaction()
        sketch.solve()
        return False, "Not added: Equal Curve Length would over-define the sketch.%s" % _clash_text(clashes)
    doc.commitTransaction()
    _fw_curvelength.start()
    _auto_recompute(sketch)
    return True, ""


def _add_equal_curvature(sketch, items):
    """Equal Curvature (fwsketch/eqcurv.py): the shared end's Tangent plus hidden helpers, one undo step."""
    doc = sketch.Document
    edges = [e for e in items if e.kind != "point"]
    if len(edges) != 2 or not _fw_eqcurv.offer(sketch, edges[0].geo, edges[1].geo):
        if len(edges) == 2 and _fw_eqcurv._has(sketch, edges[0].geo, edges[1].geo):
            return False, "The selection already has the Equal Curvature relation."
        return False, "Equal Curvature needs a spline and an arc, a line or a spline that meet at an end."
    before = _state(sketch)
    doc.openTransaction("Add Equal Curvature Relation")
    try:
        existing, removed = len(sketch.Constraints), []
        _fw_eqcurv.add(sketch, edges[0].geo, edges[1].geo, removed)
        existing -= len(removed)    # the joint's Coincident goes first: the clash list counts without it
        reason = _worse(_state(sketch), before)
    except Exception as error:
        doc.abortTransaction()
        sketch.solve()
        return False, "Equal Curvature could not be added: %s" % error
    if reason is not None:
        clashes = []
        if reason == "over":
            _add_clashes(sketch, existing, clashes)
        doc.abortTransaction()
        sketch.solve()
        return False, "Not added: Equal Curvature would over-define the sketch.%s" % _clash_text(clashes)
    doc.commitTransaction()
    _auto_recompute(sketch)
    return True, ""


def _add_clashes(sketch, existing, clashes):
    ""

    try:
        listed = sketch.ConflictingConstraints     # FreeCAD counts from 1 there
    except Exception:
        return
    for number in listed:
        i = number - 1
        if not 0 <= i < existing:
            continue
        c = sketch.Constraints[i]
        keys = constraint_keys(sketch, c)
        if not keys:
            continue
        name = relation_name(sketch, c)
        name = _DIMENSION_NAMES.get(name, name)
        try:
            text = "%s(%s)" % (name, ", ".join(entity_names(sketch, keys)))
        except Exception:
            text = name
        if text not in clashes:
            clashes.append(text)


def _clash_text(clashes):
    return " It clashes with: %s." % ", ".join(clashes) if clashes else ""


RELATION_STEPS = ("Delete Relation", "Delete Relations", "Suppress Relation", "Unsuppress Relation", "Replace",
                  "Repair Dangling Relations", "Add Equal Curve Length Relation",
                  "Auto Repair Sketch Relation or Dimension")


def last_relation_change(sketch):
    """The name of the newest undo step of the sketch's document when it changed relations, else None."""
    try:
        names = list(sketch.Document.UndoNames)
    except Exception:
        return None
    if not names:
        return None
    name = names[0]
    if name in RELATION_STEPS or (name.startswith("Add ") and name.endswith(" Relation")):
        return name
    return None


# The "?" of the sketch PropertyManagers: our own words
SKETCH_HELP = {
    "Properties": ("The properties of the picked sketch geometry.",
                   ["Existing Relations lists the relations of what is picked and whether it is under, fully or "
                    "over defined; right-click one to delete it.",
                    "Add Relations offers only the relations that fit the pick; a click adds one.",
                    "Options: For construction turns the geometry into construction geometry.",
                    "Parameters: type exact values for the picked geometry."]),
    "Line Properties": ("The properties of the picked line.",
                        ["Existing Relations: the line's relations and its state (under, fully or over defined).",
                         "Add Relations: Horizontal, Vertical or Fix for one line.",
                         "Options: For construction, Infinite length (the line runs on past both ends).",
                         "Parameters: the length and angle; Additional Parameters: the coordinates of both ends "
                         "and Delta X / Delta Y."]),
    "Point": ("The properties of the picked sketch point.",
              ["Existing Relations: the point's relations. Add Relations: Fix. Parameters: X and Y of the point."]),
    "Display/Delete Relations": ("Lists the relations of the sketch so you can check, suppress or delete them.",
                                 ["Relations: the filter picks which relations are listed (all in this sketch, "
                                  "dangling, over-defining, external, selected entities...). A click on a relation "
                                  "shows its entities in pink; Suppressed keeps it without solving it.",
                                  "Undo last relation change takes back the newest relation step; Delete removes "
                                  "the picked relation, Delete All every listed one.",
                                  "Entities: what the picked relation relates and where it is defined. Pick an "
                                  "entity in the graphics area and Replace puts it in the place of the one picked "
                                  "in the table."]),
    "Add Relations": ("Adds relations between the picked sketch entities.",
                      ["Selected Entities: what the relation will relate. Add Relations: only the relations that fit "
                       "the pick are offered; a click adds one."]),
}


def delete_relations(sketch, indices):
    indices = sorted(set(indices))
    if not indices:
        return
    doc = sketch.Document
    doc.openTransaction("Delete Relation" if len(indices) == 1 else "Delete Relations")
    try:
        # Equal Curvature deleted: a Tangent the user had at the joint before stays (eqcurv.own_tangents)
        # (and the joint of one that made its own Tangent keeps its Coincident: eqcurv.joints)
        own = _fw_eqcurv.own_tangents(sketch, indices) if _fw_eqcurv is not None else []
        joints = _fw_eqcurv.joints(sketch, indices) if _fw_eqcurv is not None else []
        indices = [i for i in indices if i not in own]
        if indices:
            sketch.delConstraints(indices, True, False)
        if own:
            _fw_eqcurv.restore(sketch, [o - sum(1 for i in indices if i < o) for o in own])
        if joints:
            sketch.addConstraint(joints)
        if _fw_references is not None and not hasattr(sketch, "addAutomaticReference"):
            _fw_references.prune(sketch)
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintWarning("FreeCAD: relation not deleted: %s\n" % error)
        return
    doc.commitTransaction()
    _auto_recompute(sketch)


def set_suppressed(sketch, indices, suppressed):
    ""
    indices = [i for i in sorted(set(indices)) if bool(sketch.getActive(i)) == suppressed]
    if not indices:
        return
    doc = sketch.Document
    doc.openTransaction("Suppress Relation" if suppressed else "Unsuppress Relation")
    try:
        for i in indices:
            sketch.setActive(i, not suppressed)
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintWarning("FreeCAD: relation not changed: %s\n" % error)
        return
    doc.commitTransaction()
    _auto_recompute(sketch)


def suppressed(sketch, indices):
    try:
        return bool(indices) and not any(sketch.getActive(i) for i in indices)
    except Exception as _fw_err:
        _fw_log("relationspm.py:1955", _fw_err)
        return False


def set_construction(sketch, items, on):
    targets = [e.geo for e in items if e.own and e.kind != "point"]
    targets = [g for g in dict.fromkeys(targets) if bool(sketch.getConstruction(g)) != on]
    if not targets:
        return
    doc = sketch.Document
    doc.openTransaction("For Construction")
    try:
        for g in targets:
            sketch.setConstruction(g, on)
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintWarning("FreeCAD: construction not changed: %s\n" % error)
        return
    doc.commitTransaction()
    _auto_recompute(sketch)


INFINITE_REACH = 5000.0     # fwsketch.line: how far an infinite line runs past its clicks


def is_infinite(sketch, geo):
    ""

    try:
        g = sketch.Geometry[geo]
        return type(g).__name__ == "LineSegment" and g.length() >= 2 * INFINITE_REACH * 0.99
    except Exception as _fw_err:
        _fw_log("relationspm.py:1987", _fw_err)
        return False


def set_infinite(sketch, geo, on):
    """Line Properties > Infinite length: on runs the line on far past both ends; off brings it
    back to the span of the points that sit on it (its clicks), else 50 mm round its middle."""
    import Part
    import Sketcher
    g = sketch.Geometry[geo]
    if type(g).__name__ != "LineSegment" or is_infinite(sketch, geo) == bool(on):
        return False
    a, b = App.Vector(g.StartPoint), App.Vector(g.EndPoint)
    d = b - a
    if d.Length < 1e-9:
        return False
    d.normalize()
    if on:
        a, b = a - d * INFINITE_REACH, b + d * INFINITE_REACH
    else:
        ts = []
        for c in sketch.Constraints:
            if c.Type == "PointOnObject" and c.Second == geo and c.First is not None and c.First != geo:
                try:
                    ts.append((App.Vector(sketch.getPoint(c.First, c.FirstPos)) - a).dot(d))
                except Exception as _fw_err:
                    _fw_log("relationspm.py:2005", _fw_err)
        mid = (g.length() / 2.0)
        lo, hi = (min(ts), max(ts)) if len(ts) >= 2 and max(ts) - min(ts) > 1e-6 else (mid - 25.0, mid + 25.0)
        a, b = a + d * lo, a + d * hi
    doc = sketch.Document
    doc.openTransaction("Infinite Length")
    try:
        sketch.moveGeometry(geo, 1, a, False)
        sketch.moveGeometry(geo, 2, b, False)
        sketch.solve()
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintWarning("FreeCAD: Infinite length not changed: %s\n" % error)
        return False
    doc.commitTransaction()
    _auto_recompute(sketch)
    return True


# --------------------------------------------------------------------------- parameters

# Line Properties has Length and Angle, and the folded Additional Parameters group the ends
# and deltas; Circle, Arc and Point have one group.
_NAMES = {"length": "Length", "angle": "Angle", "x1": "Start X Coordinate", "y1": "Start Y Coordinate",
          "x2": "End X Coordinate", "y2": "End Y Coordinate", "dx": "Delta X", "dy": "Delta Y",
          "cx": "Center X Coordinate", "cy": "Center Y Coordinate", "radius": "Radius", "sweep": "Angle",
          "x": "X Coordinate", "y": "Y Coordinate"}
ANGLES = ("angle", "sweep")
_PARAMETERS = {
    "LineSegment": (("length", "angle"), ("x1", "y1", "x2", "y2", "dx", "dy")),
    "Circle": (("cx", "cy", "radius"), ()),
    "ArcOfCircle": (("cx", "cy", "x1", "y1", "x2", "y2", "radius", "sweep"), ()),
    "point": (("x", "y"), ()),
}
_POINT_OWNERS = ("LineSegment", "Circle", "ArcOfCircle", "Point")
_LENGTH_TOLERANCE = 1e-6        # mm
_ANGLE_TOLERANCE = 1e-6         # degrees


def parameter_keys(sketch, items):
    """(Parameters, Additional Parameters) keys for the pick, or None: one element of the
    sketch's own lines, circles, arcs or points."""
    if len(items) != 1 or not items[0].own:
        return None
    item = items[0]
    try:
        cls = _class(sketch.Geometry[item.geo])
    except IndexError:
        return None
    if item.kind == "point":
        return _PARAMETERS["point"] if cls in _POINT_OWNERS else None
    return _PARAMETERS.get(cls)


def _degrees(vector):
    angle = math.degrees(math.atan2(vector.y, vector.x)) % 360.0
    return 0.0 if angle > 360.0 - 1e-9 else angle


def parameter_values(sketch, item):
    ""

    g = item.geo
    if item.kind == "point":
        p = sketch.getPoint(g, item.pos)
        return {"x": p.x, "y": p.y}
    geo = sketch.Geometry[g]
    cls = _class(geo)
    if cls == "LineSegment":
        s, e = geo.StartPoint, geo.EndPoint
        d = e - s
        return {"length": d.Length, "angle": _degrees(d), "x1": s.x, "y1": s.y, "x2": e.x, "y2": e.y,
                "dx": d.x, "dy": d.y}
    if cls == "Circle":
        return {"cx": geo.Center.x, "cy": geo.Center.y, "radius": geo.Radius}
    if cls == "ArcOfCircle":
        c, s, e = geo.Center, geo.StartPoint, geo.EndPoint
        return {"cx": c.x, "cy": c.y, "x1": s.x, "y1": s.y, "x2": e.x, "y2": e.y, "radius": geo.Radius,
                "sweep": math.degrees(geo.LastParameter - geo.FirstParameter)}
    return {}


def _same_value(key, a, b):
    if key in ANGLES:
        return abs((a - b + 180.0) % 360.0 - 180.0) <= _ANGLE_TOLERANCE
    return abs(a - b) <= _LENGTH_TOLERANCE * max(1.0, abs(b))


def _steps(distance, size, most=36):
    """How many steps a move takes: a quarter of the element's size at most each, so the
    solver follows the way it follows the pointer."""
    return max(1, min(most, int(math.ceil(distance / max(0.25 * size, 1e-6)))))


def _towards(a, b, i, n):
    return a + (b - a) * (float(i) / n)


def _round(c, r, angle):
    return c + App.Vector(math.cos(angle), math.sin(angle), 0) * r


def _plans(sketch, item, key, value):
    """Ways to give the parameter its value, best first. A plan is a list of frames; a frame
    lists (geo, pos, point) the solver drags those points to, all held at once. The frames go
    there in steps, the way the pointer would drag, and the rest of the sketch follows as its
    relations say. A line keeps its start, an arc its centre and start, a circle its centre;
    when that is held, the other end is the second choice. pos 0 on a circle is its top point."""
    V = App.Vector
    g = item.geo
    geo = sketch.Geometry[g]
    cls = _class(geo)
    if item.kind == "point":
        p = sketch.getPoint(g, item.pos)
        to = V(value, p.y, 0) if key == "x" else V(p.x, value, 0)
        whole = Item(item.sub, "line" if cls == "LineSegment" else "arc", g, NONE, item.name, cls)
        if item.pos == MID and cls in ("Circle", "ArcOfCircle"):    # the centre: the whole curve moves
            return _plans(sketch, whole, "c" + key, value)
        if item.pos in (START, END) and cls in ("LineSegment", "ArcOfCircle"):
            return _plans(sketch, whole, key + ("1" if item.pos == START else "2"), value)
        n = _steps((to - p).Length, 10.0)
        return [[[(g, item.pos, _towards(p, to, i, n))] for i in range(1, n + 1)]]
    if cls == "LineSegment":
        s, e = V(geo.StartPoint), V(geo.EndPoint)
        d = e - s
        length = d.Length
        if key in ("x1", "y1", "x2", "y2"):
            here, other, fixed = (START, END, e) if key[1] == "1" else (END, START, s)
            p = s if key[1] == "1" else e
            to = V(value, p.y, 0) if key[0] == "x" else V(p.x, value, 0)
            n = _steps((to - p).Length, max(length, 1.0))
            return [[[(g, here, _towards(p, to, i, n)), (g, other, fixed)] for i in range(1, n + 1)]]
        if length <= _LENGTH_TOLERANCE:
            return []
        if key == "angle":      # round the start, the shorter way; second choice round the end
            a0 = math.atan2(d.y, d.x)
            turn = math.radians((value - math.degrees(a0) + 180.0) % 360.0 - 180.0)
            n = max(1, int(math.ceil(abs(turn) / math.radians(5.0))))
            return [[[(g, END, _round(s, length, a0 + turn * i / n)), (g, START, s)] for i in range(1, n + 1)],
                    [[(g, START, _round(e, length, a0 + math.pi + turn * i / n)), (g, END, e)]
                     for i in range(1, n + 1)]]
        if key == "length":
            if value <= _LENGTH_TOLERANCE:
                return []
            new = V(d).normalize() * value
        elif key == "dx":
            new = V(value, d.y, 0)
        elif key == "dy":
            new = V(d.x, value, 0)
        else:
            return []
        if new.Length <= _LENGTH_TOLERANCE:
            return []           # the line would shrink to a point
        n = _steps((new - d).Length, max(length, new.Length))
        return [[[(g, END, _towards(e, s + new, i, n)), (g, START, s)] for i in range(1, n + 1)],
                [[(g, START, _towards(s, e - new, i, n)), (g, END, e)] for i in range(1, n + 1)]]
    if cls not in ("Circle", "ArcOfCircle"):
        return []
    c, r = V(geo.Center), geo.Radius
    if key in ("cx", "cy"):
        to = V(value, c.y, 0) if key == "cx" else V(c.x, value, 0)
        shift = to - c
        n = _steps(shift.Length, r)
        if cls == "Circle":
            top = c + V(0, r, 0)
            return [[[(g, MID, c + shift * (float(i) / n)), (g, NONE, top + shift * (float(i) / n))]
                     for i in range(1, n + 1)]]
        s, e = V(geo.StartPoint), V(geo.EndPoint)
        return [[[(g, MID, c + shift * (float(i) / n)), (g, START, s + shift * (float(i) / n)),
                  (g, END, e + shift * (float(i) / n))] for i in range(1, n + 1)]]
    if key == "radius":
        if value <= _LENGTH_TOLERANCE:
            return []
        n = _steps(abs(value - r), max(r, value))
        if cls == "Circle":
            return [[[(g, NONE, c + V(0, r + (value - r) * i / n, 0)), (g, MID, c)] for i in range(1, n + 1)]]
        us, ue = (V(geo.StartPoint) - c).normalize(), (V(geo.EndPoint) - c).normalize()
        return [[[(g, START, c + us * (r + (value - r) * i / n)), (g, END, c + ue * (r + (value - r) * i / n)),
                  (g, MID, c)] for i in range(1, n + 1)]]
    if cls != "ArcOfCircle":
        return []
    s, e = V(geo.StartPoint), V(geo.EndPoint)
    if key in ("x1", "y1", "x2", "y2"):
        here, other, fixed = (START, END, e) if key[1] == "1" else (END, START, s)
        p = s if key[1] == "1" else e
        to = V(value, p.y, 0) if key[0] == "x" else V(p.x, value, 0)
        if (to - fixed).Length <= _LENGTH_TOLERANCE:
            return []

        def centre(moved):
            """The point nearest the old centre that is as far from both ends."""
            middle = (moved + fixed) * 0.5
            across = V(-(moved - fixed).y, (moved - fixed).x, 0).normalize()
            return middle + across * (c - middle).dot(across)
        n = _steps((to - p).Length, r)
        return [[[(g, here, _towards(p, to, i, n)), (g, other, fixed), (g, MID, centre(_towards(p, to, i, n)))]
                 for i in range(1, n + 1)]]
    if key == "sweep":
        if not _ANGLE_TOLERANCE < value < 360.0 - _ANGLE_TOLERANCE:
            return []
        first, last = geo.FirstParameter, geo.LastParameter
        sweep, want = last - first, math.radians(value)
        n = max(1, int(math.ceil(abs(want - sweep) / math.radians(10.0))))
        return [[[(g, END, _round(c, r, first + sweep + (want - sweep) * i / n)), (g, START, s), (g, MID, c)]
                 for i in range(1, n + 1)],
                [[(g, START, _round(c, r, last - sweep - (want - sweep) * i / n)), (g, END, e), (g, MID, c)]
                 for i in range(1, n + 1)]]
    return []


def _at(sketch, g, pos):
    if pos == NONE:             # a circle's top point
        geo = sketch.Geometry[g]
        return geo.Center + App.Vector(0, geo.Radius, 0)
    return sketch.getPoint(g, pos)


def _settle(sketch, frame, tolerance, rounds):
    """Drag each point of the frame to its place in turn until all of them are there (dragging
    one lets the others slide a little). False when the sketch's relations keep them away."""
    worst = None
    for _ in range(rounds):
        for g, pos, point in frame:
            if (_at(sketch, g, pos) - point).Length > tolerance:
                sketch.moveGeometry(g, pos, point, False)
        now = max((_at(sketch, g, pos) - point).Length for g, pos, point in frame)
        if now <= tolerance:
            return True
        if worst is not None and now > 0.99 * worst:
            return False        # no longer getting closer
        worst = now
    return False


def set_parameter(sketch, item, key, value):
    """Give one of the Parameters a typed value as one undo step. (changed, message): a value
    the sketch's relations or dimensions hold is not changed, and the message says so."""
    try:
        before = parameter_values(sketch, item)
        plans = _plans(sketch, item, key, value) if key in before else []
    except Exception as error:
        return False, "Not changed: %s" % error
    name = _NAMES.get(key, key)
    if key in before and _same_value(key, before[key], value):
        return False, ""
    if not plans:
        if key == "sweep":
            return False, "Not changed: an arc's angle is more than 0 and less than 360 degrees."
        if key in ("length", "radius", "dx", "dy", "angle"):
            return False, "Not changed: the %s would shrink the entity to a point." % name.lower()
        return False, ""
    doc = sketch.Document
    saved = None if doc.UndoMode else geomkeep.read(sketch)
    for plan in plans:
        doc.openTransaction("Change %s" % name)
        try:
            for frame in plan[:-1]:
                _settle(sketch, frame, 1e-6, 4)
            _settle(sketch, plan[-1], 1e-9, 30)
            done = _same_value(key, parameter_values(sketch, item)[key], value)
        except Exception:
            done = False
        if done:
            doc.commitTransaction()
            _auto_recompute(sketch)
            return True, ""
        doc.abortTransaction()
        if saved is not None:       # no undo to take the try back with (FreeCAD without its GUI)
            sketch.Geometry = saved
        sketch.solve()
    return False, "Not changed: the sketch's relations or dimensions hold the %s." % name.lower()


# --------------------------------------------------------------------------- highlight

# those of a relation whose glyph is under the pointer in magenta.
PINK = (1.0, 0.41, 0.71)
MAGENTA = (1.0, 0.0, 1.0)
HIGHLIGHT = "SWRelationEntities"    # the overlay's node name in the view's scene graph
HOVER = "SWRelationHover"           # the same for the relation whose glyph is under the pointer


def _outline(sketch, key):
    """('point' or 'edge', sketch-plane points) drawing one entity of a relation, or None."""
    g = key[1]
    try:
        if key[0] == "p":
            return "point", [sketch.getPoint(g, int(key[2]))]
        if g in (-1, -2):           # the sketch's axes: a stretch through the origin
            box = sketch.Shape.BoundBox
            size = max(10.0, 0.6 * box.DiagonalLength) if box.isValid() else 50.0
            return "edge", ([App.Vector(-size, 0, 0), App.Vector(size, 0, 0)] if g == -1
                            else [App.Vector(0, -size, 0), App.Vector(0, size, 0)])
        geo = sketch.Geometry[g] if g >= 0 else sketch.ExternalGeo[-g - 1]
        kind = type(geo).__name__
        if kind == "Point":
            return "point", [App.Vector(geo.X, geo.Y, geo.Z)]
        return "edge", geo.toShape().discretize(Number=2 if kind == "LineSegment" else 73)
    except Exception:
        return None


def _drawn_at(sketch):
    """What takes the sketch's own coordinates to where FreeCAD draws them: while the sketch is
    in edit, the edit's transform (it holds the Body or Part the sketch was opened through, and
    only those); otherwise the sketch's global placement."""
    try:
        gdoc = Gui.getDocument(sketch.Document.Name)
        vp = gdoc.getInEdit()
        if vp is not None and getattr(editobj.of(vp), "Name", None) == sketch.Name:
            return gdoc.EditingTransform
    except Exception as _fw_err:
        _fw_log("relationspm.py:2317", _fw_err)
    return sketch.getGlobalPlacement()


class _Highlight:
    """A coloured overlay in the sketch's view: drawn after everything (SoAnnotation), never
    picked, rebuilt only when what it shows moves."""

    def __init__(self, name=HIGHLIGHT, colour=PINK):
        self.name = name
        self.colour = colour
        self.node = None
        self.graph = None
        self.signature = None

    def show(self, sketch, keys):
        shapes = [o for o in (_outline(sketch, k) for k in keys) if o]
        if not shapes:
            self.clear()
            return
        place = _drawn_at(sketch)
        shapes = [(kind, [place.multVec(p) for p in points]) for kind, points in shapes]
        signature = (sketch.Document.Name, sketch.Name,
                     tuple((kind, tuple((round(p.x, 6), round(p.y, 6), round(p.z, 6)) for p in points))
                           for kind, points in shapes))
        try:
            from pivy import coin
            graph = Gui.getDocument(sketch.Document.Name).ActiveView.getSceneGraph()
        except Exception:
            self.clear()
            return
        if signature == self.signature and self.graph is graph and graph.findChild(self.node) >= 0:
            return
        self.clear()
        try:
            ratio = Gui.getMainWindow().devicePixelRatioF()
        except Exception:
            ratio = 1.0
        root = coin.SoAnnotation()
        root.setName(self.name)
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        colour = coin.SoBaseColor()
        colour.rgb = self.colour
        style = coin.SoDrawStyle()
        style.lineWidth = 3 * ratio
        for node in (pick, light, colour, style):
            root.addChild(node)
        size = App.ParamGet("User parameter:BaseApp/Preferences/View").GetInt("MarkerSize", 9) + 2
        for kind, points in shapes:
            part = coin.SoSeparator()
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, len(points), [(p.x, p.y, p.z) for p in points])
            part.addChild(coords)
            if kind == "edge":
                part.addChild(coin.SoLineSet())
            else:
                marker = coin.SoMarkerSet()
                marker.markerIndex = Gui.getMarkerIndex("CIRCLE_FILLED", size)
                part.addChild(marker)
            root.addChild(part)
        graph.addChild(root)
        self.node, self.graph, self.signature = root, graph, signature

    def clear(self):
        if self.node is not None and self.graph is not None:
            try:
                if self.graph.findChild(self.node) >= 0:
                    self.graph.removeChild(self.node)
            except Exception as _fw_err:
                _fw_log("relationspm.py:2389", _fw_err)
        self.node = self.graph = self.signature = None


def _constraint_group(sketch):
    """FreeCAD's node holding one child per constraint of the sketch in edit, or None."""
    try:
        from pivy import coin
        graph = Gui.getDocument(sketch.Document.Name).ActiveView.getSceneGraph()
        search = coin.SoSearchAction()
        search.setName("ConstraintGroup")
        search.setInterest(coin.SoSearchAction.FIRST)
        search.setSearchingAll(True)
        search.apply(graph)
        path = search.getPath()
        return path.getTail() if path is not None else None
    except Exception as _fw_err:
        _fw_log("relationspm.py:2414", _fw_err)
        return None


def _glyph_colour(group, index):
    """The colour FreeCAD's sketcher gives constraint index's glyph (its preselection colour while
    the pointer is on it), as text; None when it can't be read."""
    try:
        if group is None or index >= group.getNumChildren():
            return None
        node = group.getChild(index).getChild(0)
        field = node.getField("diffuseColor") or node.getField("textColor")
        value = field.get() if field is not None else None     # pivy: an SbString
        return value.getString() if hasattr(value, "getString") else value
    except Exception as _fw_err:
        _fw_log("relationspm.py:2429", _fw_err)
        return None


# --------------------------------------------------------------------------- theme

# written here; the dark ones take the look's tokens. A look without themes is light.
def _dark():
    try:
        from . import style
        return bool(style.dark())
    except Exception:
        return False


def _tok(name, light):
    """QColor of the theme token `name`, or `light` in the light theme (and without themes)."""
    if _dark():
        try:
            from . import style
            return QtGui.QColor(getattr(style.T, name))
        except Exception as _fw_err:
            _fw_log("relationspm.py:2441", _fw_err)
    return QtGui.QColor(light)


_FIELD_FALLBACK = {"field": "base", "field_text": "text", "field_line": "line_mid"}


def _field(name, light):
    ""


    if _dark():
        try:
            from . import style
            return QtGui.QColor(getattr(style.T, name))
        except Exception:
            return _tok(_FIELD_FALLBACK[name], light)
    return QtGui.QColor(light)


def _light_field():
    return _field("field", "#ffffff").lightness() >= 128


def _list_ink(kind):
    """List text: 'text', 'dim' (suppressed) or 'red' (over-defining), readable on the list's
    own colour, which stays white in the Dark theme."""
    if kind == "text":
        return _field("field_text", "#000000")
    if _light_field():
        return QtGui.QColor("#8c8c8c" if kind == "dim" else "#c00000")
    return _tok("text_dim", "#8c8c8c") if kind == "dim" else QtGui.QColor("#ff6b6b")


# --------------------------------------------------------------------------- pictures
def _ink():
    return _tok("glyph", "#3c3c3c")


def _blue():
    return QtGui.QColor("#5c9dff" if _dark() else "#2f6db5")


def _icon(draw, size=16):
    """A crisp QIcon from a drawing function painting a 16 x 16 box."""
    icon = QtGui.QIcon()
    for scale in (1, 2, 3):
        image = QtGui.QImage(size * scale, size * scale, QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        p = QtGui.QPainter(image)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.scale(scale * size / 16.0, scale * size / 16.0)
        draw(p)
        p.end()
        image.setDevicePixelRatio(scale)
        icon.addPixmap(QtGui.QPixmap.fromImage(image))
    return icon


def _pen(p, color=None, width=1.3, dash=False):
    pen = QtGui.QPen(_ink() if color is None else color, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    if dash:
        pen.setDashPattern([2.5, 1.8])
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)


def _dot(p, x, y, r=1.7, color=None):
    p.setPen(Qt.NoPen)
    p.setBrush(_ink() if color is None else color)
    p.drawEllipse(QtCore.QPointF(x, y), r, r)


def _line(p, x1, y1, x2, y2):
    p.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))


def _draw_relation(key, p):
    if key == "Horizontal":
        _pen(p, width=1.6)
        _line(p, 2.5, 8, 13.5, 8)
    elif key == "Vertical":
        _pen(p, width=1.6)
        _line(p, 8, 2.5, 8, 13.5)
    elif key == "Collinear":
        _pen(p)
        _line(p, 2, 14, 7, 9)
        _line(p, 9, 7, 14, 2)
    elif key == "Coradial":
        _pen(p, _blue())
        p.drawEllipse(QtCore.QPointF(8, 8), 5.5, 5.5)
        _pen(p)
        p.drawArc(QtCore.QRectF(2.5, 2.5, 11, 11), 30 * 16, 120 * 16)
        _dot(p, 8, 8, 1.3)
    elif key == "Perpendicular":
        _pen(p)
        _line(p, 8, 2.5, 8, 13)
        _line(p, 2.5, 13, 13.5, 13)
    elif key == "Parallel":
        _pen(p, _blue())
        _line(p, 2.5, 12, 9, 3)
        _line(p, 7, 13, 13.5, 4)
    elif key == "Tangent":
        _pen(p, _blue())
        p.drawEllipse(QtCore.QPointF(7, 9.5), 4.5, 4.5)
        _pen(p)
        _line(p, 1.5, 5, 14.5, 5)
    elif key == "Concentric":
        _pen(p, _blue())
        p.drawEllipse(QtCore.QPointF(8, 8), 6, 6)
        p.drawEllipse(QtCore.QPointF(8, 8), 3, 3)
        _dot(p, 8, 8, 1.1)
    elif key == "Midpoint":
        _pen(p)
        _line(p, 2, 13, 14, 3)
        _dot(p, 8, 8, 2.0, _blue())
    elif key == "Intersection":
        _pen(p)
        _line(p, 2.5, 3, 13.5, 13)
        _line(p, 2.5, 13, 13.5, 3)
        _dot(p, 8, 8, 2.0, _blue())
    elif key == "Coincident":
        _pen(p)
        p.drawArc(QtCore.QRectF(1.5, 5, 13, 16), 20 * 16, 140 * 16)
        _dot(p, 8, 5.2, 2.0, _blue())
    elif key == "Merge":
        _pen(p)
        p.drawEllipse(QtCore.QPointF(6, 8), 3.2, 3.2)
        p.drawEllipse(QtCore.QPointF(10, 8), 3.2, 3.2)
        _dot(p, 8, 8, 1.2, _blue())
    elif key == "Equal":
        _pen(p, width=1.6)
        _line(p, 3.5, 6, 12.5, 6)
        _line(p, 3.5, 10, 12.5, 10)
    elif key == "Equal Curvature":
        _pen(p, _blue(), 1.4)
        p.drawArc(QtCore.QRectF(1.5, 4, 10, 10), 90 * 16, 90 * 16)
        path = QtGui.QPainterPath(QtCore.QPointF(6.5, 4))
        path.cubicTo(QtCore.QPointF(10, 4), QtCore.QPointF(12, 6), QtCore.QPointF(14.5, 10))
        p.drawPath(path)
        _pen(p, width=1.4)
        _line(p, 5.5, 11, 10.5, 11)
        _line(p, 5.5, 13.5, 10.5, 13.5)
    elif key == "Equal Curve Length":
        _pen(p, width=1.4)
        _line(p, 2.5, 12.5, 13.5, 12.5)
        p.drawArc(QtCore.QRectF(2.5, 3, 11, 11), 20 * 16, 140 * 16)
        _line(p, 6.5, 10, 9.5, 10)
        _line(p, 6.5, 8, 9.5, 8)
    elif key == "Symmetric":
        _pen(p, dash=True)
        _line(p, 8, 1.5, 8, 14.5)
        _dot(p, 3.5, 8, 1.8)
        _dot(p, 12.5, 8, 1.8)
    elif key == "Pierce":
        _pen(p, _blue())
        p.drawEllipse(QtCore.QPointF(8, 9.5), 6, 2.6)
        _pen(p)
        _line(p, 8, 1.5, 8, 14.5)
        _dot(p, 8, 9.5, 2.0, _blue())
    elif key == "Fix":
        _pen(p)
        _line(p, 8, 2.5, 8, 13)
        _line(p, 5, 5.5, 11, 5.5)
        p.drawArc(QtCore.QRectF(3, 7, 10, 7), 180 * 16, 180 * 16)
        p.drawEllipse(QtCore.QPointF(8, 2.2), 1.1, 1.1)


_icons = {}


def relation_icon(key):
    icon = _icons.get((key, _dark()))
    if icon is None:
        icon = _icons[(key, _dark())] = _icon(lambda p, k=key: _draw_relation(k, p))
    return icon


def _draw_relations_group(p):
    """The Display/Delete Relations picture beside the Existing Relations box."""
    _pen(p, None, 1.2)
    _line(p, 8, 3, 8, 12)
    _line(p, 3, 12, 13, 12)
    _line(p, 2, 14.5, 14, 14.5)


def _draw_info(p):
    grey = _tok("glyph", "#5b5b5b")
    _pen(p, grey, 1.1)
    p.drawEllipse(QtCore.QPointF(8, 8), 6.3, 6.3)
    _dot(p, 8, 4.9, 0.9, grey)
    _pen(p, grey, 1.4)
    _line(p, 8, 7.2, 8, 11.6)


def _draw_properties(p):
    _pen(p, None, 1.1)
    p.drawRect(QtCore.QRectF(2.5, 1.5, 11, 13))
    p.fillRect(QtCore.QRectF(3, 2, 10, 2.5), _blue())
    for y in (7, 9.5, 12):
        _line(p, 4.5, y, 11.5, y)


def _draw_check(p):
    _pen(p, QtGui.QColor("#74a257"), 2.2)
    p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(3, 8.5), QtCore.QPointF(6.5, 12), QtCore.QPointF(13, 4.5)]))


def _letter(p, text, x, y, size=7.5):
    """A small letter (x, y, the Delta sign) in the ink colour, its baseline at (x, y)."""
    font = QtGui.QFont(ui_font())
    font.setPixelSize(int(round(size)))
    font.setBold(True)
    p.setFont(font)
    p.setPen(_ink())
    p.drawText(QtCore.QPointF(x, y), text)


def _draw_parameter(key, p):
    """The picture beside each Parameters field: the measured thing in blue, a letter for the
    coordinate it gives."""
    blue = _blue()
    if key in ("length", "dx", "dy", "x1", "y1", "x2", "y2"):
        _pen(p, blue, 1.4)
        _line(p, 2.5, 12.5, 11.5, 3.5)
        if key == "length":
            _pen(p, None, 1.0)
            _line(p, 1, 10, 4.5, 13.5)
            _line(p, 9.5, 1.5, 13, 5)
        elif key in ("dx", "dy"):
            _pen(p, None, 1.0, dash=True)
            if key == "dx":
                _line(p, 2.5, 14.5, 11.5, 14.5)
            else:
                _line(p, 13.5, 12.5, 13.5, 3.5)
        else:
            x, y = (2.5, 12.5) if key[1] == "1" else (11.5, 3.5)
            _dot(p, x, y, 2.0)
            _letter(p, key[0], 10.5 if key[1] == "1" else 2, 15.5 if key[1] == "1" else 15.5)
        if key in ("dx", "dy"):
            _letter(p, "Δ" + key[1], 0.5 if key == "dy" else 4, 8 if key == "dy" else 9.5, 7)
    elif key == "angle":
        _pen(p, blue, 1.4)
        _line(p, 2, 13.5, 14.5, 13.5)
        _line(p, 2, 13.5, 11, 3)
        _pen(p, None, 1.0)
        p.drawArc(QtCore.QRectF(-5, 6.5, 14, 14), 0, 50 * 16)
    elif key in ("cx", "cy", "radius"):
        _pen(p, blue, 1.3)
        p.drawEllipse(QtCore.QPointF(7, 8), 5.5, 5.5)
        _dot(p, 7, 8, 1.4)
        if key == "radius":
            _pen(p, None, 1.1)
            _line(p, 7, 8, 11, 4.2)
        else:
            _letter(p, key[1], 11, 15.5)
    elif key == "sweep":
        _pen(p, blue, 1.4)
        p.drawArc(QtCore.QRectF(2, 3, 12, 12), 0, 150 * 16)
        _pen(p, None, 1.0, dash=True)
        _line(p, 8, 9, 14, 9)
        _line(p, 8, 9, 2.8, 6)
        _dot(p, 8, 9, 1.3)
    elif key in ("x", "y"):
        _dot(p, 5.5, 7, 2.4, blue)
        _letter(p, key, 9.5, 15.5)
    elif key == "diameter":         # toolglyph-1121: a circle and its diameter
        _pen(p, blue, 1.3)
        p.drawEllipse(QtCore.QPointF(8, 8), 6, 6)
        _pen(p, None, 1.1)
        _line(p, 3.8, 12.2, 12.2, 3.8)
    elif key == "sides":            # toolglyph-1121: a hexagon and the number sign
        _pen(p, blue, 1.3)
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(8 + 6.5 * math.cos(math.radians(a)),
                                                      8 + 6.5 * math.sin(math.radians(a))) for a in range(30, 390, 60)]))
        _letter(p, "#", 5, 11.5, 7)
    elif key == "width":            # toolglyph-1121: a slot's width between two lines
        _pen(p, blue, 1.3)
        _line(p, 2, 4, 14, 4)
        _line(p, 2, 12, 14, 12)
        _pen(p, None, 1.0)
        _line(p, 8, 5, 8, 11)


def _parameter_icon(key):
    icon = _icons.get(("parameter", key, _dark()))
    if icon is None:
        icon = _icons[("parameter", key, _dark())] = _icon(lambda p, k=key: _draw_parameter(k, p))
    return icon


def _arrow_images():
    """The spin boxes' up and down arrows, dark on a light field and light on a dark one
    (Qt's style sheets take images from files)."""
    import tempfile
    from pathlib import Path
    colour = "#404040" if _light_field() else "#d0d0d0"
    folder = Path(tempfile.gettempdir()) / "swstyle-relpm"
    folder.mkdir(exist_ok=True)
    paths = {}
    for name, points in (("up", [(0, 4), (3.5, 0), (7, 4)]), ("down", [(0, 0), (3.5, 4), (7, 0)])):
        path = folder / ("%s-%s.png" % (name, colour[1:]))
        if not path.exists():
            image = QtGui.QImage(14, 8, QtGui.QImage.Format_ARGB32)
            image.fill(Qt.transparent)
            painter = QtGui.QPainter(image)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.scale(2, 2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QtGui.QColor(colour))
            painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in points]))
            painter.end()
            image.setDevicePixelRatio(2)
            image.save(str(path))
        paths[name] = path.as_posix()
    return paths


def _draw_fold(up):
    def draw(p):
        _pen(p, _tok("arrow", "#505050"), 1.2)
        if up:
            p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(4.5, 10), QtCore.QPointF(8, 6.5), QtCore.QPointF(11.5, 10)]))
        else:
            p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(4.5, 6.5), QtCore.QPointF(8, 10), QtCore.QPointF(11.5, 6.5)]))
    return draw


def _pack_or(family, draw, tint=None):
    icon = icons.family(family)
    if icon.isNull():
        return _icon(draw)
    if tint:
        try:
            from . import propertymanager
            return propertymanager._tinted(icon, tint)
        except Exception as _fw_err:
            _fw_log("relationspm.py:2755", _fw_err)
    return icon


# --------------------------------------------------------------------------- widgets
_QSS = string.Template("""
QWidget#SWRelationsPM { background: $pane; }
QWidget#SWRelationsPM QScrollArea, QWidget#SWRelationsPM QWidget#SWRelationsBody { background: $pane; border: none; }
QWidget#SWRelationsPM QLabel { background: transparent; color: $text; }
QWidget#SWRelationsPM QLabel#SWStyle_PMTitle { font-weight: bold; }
QWidget#SWRelationsPM QWidget[swGroupHeader="true"] { border-top: 1px solid $line_light; background: transparent; }
QWidget#SWRelationsPM QLabel[swGroupTitle="true"] { font-weight: bold; }
QWidget#SWRelationsPM QListWidget {
    background: $field; color: $field_text; border: 1px solid $field_line;
    selection-background-color: $selection; selection-color: $field_text; outline: none;
}
QWidget#SWRelationsPM QListWidget#SWSelectedEntities { background: $entities; border: 1px solid $accent; }
QWidget#SWRelationsPM QListWidget#SWSelectedEntities::item { border: 1px solid $entity_line; margin: 1px 1px 0px 1px; }
QWidget#SWRelationsPM QToolButton { background: transparent; border: 1px solid transparent; border-radius: 2px; padding: 0px; }
QWidget#SWRelationsPM QToolButton:hover { background: $hover; border-color: $hover_line; }
QWidget#SWRelationsPM QToolButton:pressed { background: $down; border-color: $accent; }
QWidget#SWRelationsPM QCheckBox { background: transparent; color: $text; }
QWidget#SWRelationsPM QLabel#SWRelationsNote, QWidget#SWRelationsPM QLabel#SWParametersNote { color: $note; }
QWidget#SWRelationsPM QAbstractSpinBox {
    background: $field; color: $field_text; border: 1px solid $field_line; min-height: 20px; padding: 0px 3px;
    selection-background-color: #0078d7; selection-color: #ffffff;
}
QWidget#SWRelationsPM QAbstractSpinBox:focus { border: 1px solid $accent; }
QWidget#SWRelationsPM QLineEdit[swParamField="true"] {
    background: $field; color: $field_text; border: 1px solid $field_line; min-height: 20px; padding: 0px 3px;
    selection-background-color: #0078d7; selection-color: #ffffff;
}
QWidget#SWRelationsPM QLineEdit[swParamField="true"]:focus { border: 1px solid $accent; }
QWidget#SWRelationsPM QLineEdit[swParamField="true"]:disabled { background: $field_off; color: $field_off_text; }
QWidget#SWRelationsPM QAbstractSpinBox:disabled { background: $field_off; color: $field_off_text; }
QWidget#SWRelationsPM QAbstractSpinBox::up-button, QWidget#SWRelationsPM QAbstractSpinBox::down-button {
    background: transparent; border: none; width: 14px;
}
QWidget#SWRelationsPM QAbstractSpinBox::up-button:hover, QWidget#SWRelationsPM QAbstractSpinBox::down-button:hover {
    background: $hover;
}
QWidget#SWRelationsPM QAbstractSpinBox::up-arrow { image: url($up); width: 7px; height: 4px; }
QWidget#SWRelationsPM QAbstractSpinBox::down-arrow { image: url($down); width: 7px; height: 4px; }
QWidget#SWRelationsPM QAbstractSpinBox::up-arrow:disabled, QWidget#SWRelationsPM QAbstractSpinBox::down-arrow:disabled {
    image: none;
}
""")


def _qss():
    ""
    colours = {"pane": ("pane", "#f7f7f7"), "text": ("text", "#000000"), "line_light": ("line_light", "#d5d5d5"),
               "base": ("base", "#ffffff"), "line_mid": ("line_mid", "#a9a9a9"),
               "selection": ("selection", "#cce4f7"), "entities": ("selection", "#cfe6fb"),
               "accent": ("accent", "#5a9bd5"), "entity_line": ("line_mid", "#9cc3e8"),
               "hover": ("hover", "#e5f1fb"), "hover_line": ("line_mid", "#9cc8ee"), "down": ("down", "#cce4f7")}
    values = {key: _tok(name, light).name() for key, (name, light) in colours.items()}
    values["note"] = "#ff6b6b" if _dark() else "#b00000"
    values.update(field=_field("field", "#ffffff").name(), field_text=_field("field_text", "#000000").name(),
                  field_line=_field("field_line", "#a9a9a9").name())
    if _light_field():
        values.update(selection="#cce4f7", entities="#cfe6fb", entity_line="#9cc3e8",
                      field_off="#f0f0f0", field_off_text="#8a8a8a")
    else:
        values.update(field_off=values["pane"], field_off_text=_tok("text_dim", "#8a8a8a").name())
    try:
        values.update(_arrow_images())
    except Exception:
        values.update(up="", down="")
    return _QSS.substitute(values)


def _checkbox_qss():
    """The PropertyManager's check box, shared with the dressed FreeCAD panels."""
    try:
        from . import propertymanager
        images = propertymanager._images()
        base, frame, accent = (_tok("base", "#ffffff").name(), _tok("text_dim", "#333333").name(),
                               _tok("accent", "#0078d7").name())
        return ("QWidget#SWRelationsPM QCheckBox::indicator { width: 13px; height: 13px; background: %s;"
                " border: 1px solid %s; border-radius: 2px; }\n"
                "QWidget#SWRelationsPM QCheckBox::indicator:hover { border-color: %s; }\n"
                "QWidget#SWRelationsPM QCheckBox::indicator:checked { background: %s; border-color: %s;"
                " image: url(%s); }\n" % (base, frame, accent, accent, accent, images["CHECK"]))
    except Exception:
        return ""


class RelationButton(QtWidgets.QAbstractButton):
    ""


    def __init__(self, key, parent=None):
        super().__init__(parent)
        self.key = key
        self.setText(key)
        self.setObjectName("SWAddRelation_" + key)
        self.setIcon(relation_icon(key))
        self.setStatusTip("Adds %s %s relation to the selection(s)." % ("an" if key[0] in "AEIOU" else "a", key.lower()))
        self.setToolTip(key)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self._hover = False

    def sizeHint(self):
        fm = QtGui.QFontMetrics(ui_font(bold=True))
        return QtCore.QSize(30 + fm.horizontalAdvance(self.text()) + 8, 26)

    def minimumSizeHint(self):
        return QtCore.QSize(60, 26)

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        box = QtCore.QRectF(1.5, (self.height() - 22) / 2.0 + 0.5, 22, 22)
        p.setPen(QtGui.QPen(_tok("accent", "#5a9bd5") if self.isDown() else _tok("line_light", "#c3c3c3"), 1))
        p.setBrush(_tok("down", "#cce4f7") if self.isDown()
                   else (_tok("hover", "#e5f1fb") if self._hover else _tok("base", "#fdfdfd")))
        p.drawRect(box)
        self.icon().paint(p, box.adjusted(3, 3, -3, -3).toRect())
        p.setFont(ui_font(bold=self._hover))
        p.setPen(_tok("text", "#000000") if self._hover else _tok("text_dim", "#5f5f5f"))
        text = QtCore.QRectF(box.right() + 7, 0, self.width() - box.right() - 8, self.height())
        p.drawText(text, Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()


class Group(QtWidgets.QWidget):
    """A PropertyManager group: bold title, fold arrow, then its content."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("SWGroup_" + title.replace(" ", ""))
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = QtWidgets.QWidget(self)
        self.header.setProperty("swGroupHeader", True)
        self.header.setAttribute(Qt.WA_StyledBackground, True)
        self.header.setCursor(Qt.ArrowCursor)
        row = QtWidgets.QHBoxLayout(self.header)
        row.setContentsMargins(8, 5, 6, 4)
        self.title = QtWidgets.QLabel(title, self.header)
        self.title.setProperty("swGroupTitle", True)
        self.title.setWordWrap(True)    # "Additional Parameters" takes two lines in a narrow pane
        self.fold = QtWidgets.QToolButton(self.header)
        self.fold.setAutoRaise(True)
        self.fold.setFixedSize(18, 18)
        self.fold.setIconSize(QtCore.QSize(16, 16))
        self.fold.setFocusPolicy(Qt.NoFocus)
        self.fold.clicked.connect(self.toggle)
        row.addWidget(self.title, 1)
        row.addWidget(self.fold)
        self.body = QtWidgets.QWidget(self)
        self.content = QtWidgets.QVBoxLayout(self.body)
        self.content.setContentsMargins(8, 2, 8, 4)
        self.content.setSpacing(4)
        outer.addWidget(self.header)
        outer.addWidget(self.body)
        self.header.installEventFilter(self)
        self._update_fold()

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter2551(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter relationspm.py: %s\n" % exc)
            return False

    def _fw_filter2551(self, obj, event):
        if obj is self.header and event.type() == QtCore.QEvent.MouseButtonRelease \
                and event.button() == Qt.LeftButton:
            self.toggle()
            return True
        return False

    def toggle(self):
        self.body.setVisible(not self.body.isVisible())
        self._update_fold()

    def _update_fold(self):
        self.fold.setIcon(_icon(_draw_fold(not self.body.isHidden())))


class _Keys(QtCore.QObject):
    """Delete and Esc for the panel's own boxes, ahead of FreeCAD's shortcuts."""

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter2573(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter relationspm.py: %s\n" % exc)
            return False

    def _fw_filter2573(self, obj, event):
        t = event.type()
        if t == QtCore.QEvent.ShortcutOverride and event.key() in (Qt.Key_Delete, Qt.Key_Escape):
            event.accept()
            return True
        if t == QtCore.QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self.panel.escape()
                return True
            if event.key() == Qt.Key_Delete:
                if obj is self.panel.relations:
                    self.panel.delete_current_relation()
                    return True
                if obj is self.panel.entities:
                    self.panel.drop_current_entity()
                    return True
        return False


class _FieldWheel(QtCore.QObject):
    """The wheel over a Parameters field that is not being edited scrolls the pane, so scrolling
    down the PropertyManager never changes the sketch on the way."""

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter2600(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter relationspm.py: %s\n" % exc)
            return False

    def _fw_filter2600(self, obj, event):
        if event.type() == QtCore.QEvent.Wheel and not obj.hasFocus():
            QtWidgets.QApplication.sendEvent(self.panel.scroll.verticalScrollBar(), event)
            return True
        return False


class Panel(QtWidgets.QWidget):
    """The PropertyManager page; RelationsPM fills it."""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.setObjectName("SWRelationsPM")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._apply_theme()
        self.setFont(ui_font())
        self.sketch = None
        self.items = []
        self.dd = None              # Display/Delete Relations: the list's filter, else None
        self._listed = []
        self._keys = []
        self._parameter_keys = None     # (Parameters, Additional Parameters) the fields are for
        self._filling = False           # fill() writes the fields: not the user's input
        self._typed = set()             # fields the user typed in and has not entered yet
        self.fields = {}                # key -> (row, picture, spin box)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.scroll = QtWidgets.QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(self.scroll)
        body = QtWidgets.QWidget()
        body.setObjectName("SWRelationsBody")
        self.scroll.setWidget(body)
        self.column = QtWidgets.QVBoxLayout(body)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(0)
        self._keyfilter = _Keys(self)
        self._build_header(body)
        self._build_entities(body)
        self._build_relations(body)
        self._build_add(body)
        self._build_options(body)
        self._build_parameters(body)
        self.column.addStretch(1)

    def _apply_theme(self):
        self.setStyleSheet(_qss() + _checkbox_qss())
        if _dark():
            self.setPalette(QtGui.QPalette())  # the look's dark application palette
        else:
            try:
                from . import propertymanager
                self.setPalette(propertymanager._light_palette(QtWidgets.QApplication.palette()))
            except Exception as _fw_err:
                _fw_log("relationspm.py:3059", _fw_err)
        self._theme_fields()

    def _theme_fields(self):
        """The filter box is a field as well: white in the Dark theme, like the lists."""
        box = getattr(self, "filter_box", None)
        if box is not None:
            palette = QtGui.QPalette(self.palette())
            for role, colour in ((QtGui.QPalette.Button, _field("field", "#ffffff")),
                                 (QtGui.QPalette.Base, _field("field", "#ffffff")),
                                 (QtGui.QPalette.Window, _field("field", "#ffffff")),
                                 (QtGui.QPalette.ButtonText, _field("field_text", "#000000")),
                                 (QtGui.QPalette.Text, _field("field_text", "#000000")),
                                 (QtGui.QPalette.WindowText, _field("field_text", "#000000"))):
                palette.setColor(QtGui.QPalette.Active, role, colour)
                palette.setColor(QtGui.QPalette.Inactive, role, colour)
            box.setPalette(palette)

    def retheme(self):
        """The look switched theme: style sheet, palette, pictures and list colours again."""
        _icons.clear()
        self._apply_theme()
        self.relations_picture.setPixmap(
            _pack_or("LAYOUT_DISPLAY_DEL_RELATION", _draw_relations_group).pixmap(16, 16))
        self.info_icon.setPixmap(_icon(_draw_info).pixmap(16, 16))
        for group in (self.entities_group, self.relations_group, self.add_group, self.options_group,
                      self.parameters_group, self.more_group):
            group._update_fold()
        for key, (row, picture, box) in self.fields.items():
            picture.setPixmap(_parameter_icon(key).pixmap(16, 16))
        for b in self.buttons:
            b.setIcon(relation_icon(b.key))
        if self.sketch is not None:
            try:
                self.fill(self.sketch, self.items)
            except Exception as _fw_err:
                _fw_log("relationspm.py:3095", _fw_err)
        self.update()

    # ------------------------------------------------------------------ build
    def _build_header(self, body):
        header = QtWidgets.QWidget(body)
        header.setObjectName("SWStyle_PMHeader")
        outer = QtWidgets.QVBoxLayout(header)
        outer.setContentsMargins(8, 8, 8, 6)
        outer.setSpacing(6)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(6)
        self.title_icon = QtWidgets.QLabel(header)
        self.title_icon.setFixedSize(20, 20)
        self.title = QtWidgets.QLabel("Properties", header)
        self.title.setObjectName("SWStyle_PMTitle")
        self.title.setWordWrap(True)    # "Display/Delete Relations" takes two lines in a narrow pane
        top.addWidget(self.title_icon, 0, Qt.AlignTop)
        top.addWidget(self.title, 1)

        self.help = QtWidgets.QToolButton(header)
        self.help.setObjectName("SWRelationsHelp")
        self.help.setAutoRaise(True)
        self.help.setIconSize(QtCore.QSize(20, 20))
        self.help.setToolTip("Help")
        self.help.setFocusPolicy(Qt.NoFocus)
        try:
            from . import propertymanager
            help_icon = icons.family("PM_HELP")
            if help_icon.isNull():
                help_icon = propertymanager._drawn("PM_HELP")
            self.help.setIcon(help_icon)
        except Exception:
            self.help.setText("?")
        self.help.clicked.connect(self.show_help)
        top.addWidget(self.help, 0, Qt.AlignTop)
        outer.addLayout(top)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(2)
        self.ok = QtWidgets.QToolButton(header)
        self.ok.setObjectName("SWRelationsOK")
        self.ok.setAutoRaise(True)
        self.ok.setIconSize(QtCore.QSize(16, 16))
        self.ok.setFixedSize(24, 22)
        self.ok.setToolTip("OK")
        self.ok.setFocusPolicy(Qt.NoFocus)
        try:
            from . import propertymanager
            green = propertymanager.OK_GREEN
        except Exception:
            green = "#74a257"
        self.ok.setIcon(_pack_or("CHECK_MARK", _draw_check, green))
        self.ok.clicked.connect(self._ok_clicked)
        row.addWidget(self.ok)
        row.addStretch(1)
        outer.addLayout(row)
        self.column.addWidget(header)

    def _list(self, name, parent):
        box = QtWidgets.QListWidget(parent)
        box.setObjectName(name)
        box.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        box.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        box.setContextMenuPolicy(Qt.CustomContextMenu)
        box.installEventFilter(self._keyfilter)
        return box

    def _build_entities(self, body):
        self.entities_group = Group("Selected Entities", body)
        row = self._entities_row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(28, 0, 0, 0)
        self.entities = self._list("SWSelectedEntities", self.entities_group.body)
        self.entities.customContextMenuRequested.connect(self._entities_menu)
        row.addWidget(self.entities)
        self.entities_group.content.addLayout(row)

        # Replace: the picked row's entity swapped for the entity picked in the graphics area
        self.dd_table = QtWidgets.QTreeWidget(self.entities_group.body)
        self.dd_table.setObjectName("SWRelationEntitiesTable")
        self.dd_table.setHeaderLabels(["Entity", "Status", "Defined In"])
        self.dd_table.setRootIsDecorated(False)
        self.dd_table.setFixedHeight(84)
        self.dd_table.currentItemChanged.connect(lambda *a: self._replace_state())
        self.entities_group.content.addWidget(self.dd_table)
        self.dd_replace_row = QtWidgets.QWidget(self.entities_group.body)
        rr = QtWidgets.QHBoxLayout(self.dd_replace_row)
        rr.setContentsMargins(0, 0, 0, 0)
        self.dd_replace_with = QtWidgets.QLineEdit(self.dd_replace_row)
        self.dd_replace_with.setObjectName("SWRelationsReplaceWith")
        self.dd_replace_with.setReadOnly(True)
        self.dd_replace_with.setPlaceholderText("Entity to replace the one selected above")

        self.dd_find = QtWidgets.QPushButton("Find Replacement", self.entities_group.body)
        self.dd_find.setObjectName("SWRelationsFindReplacement")
        self.dd_find.setToolTip("Looks for the model edge now in the place of the dangling entity picked above")
        self.dd_find.clicked.connect(self.find_current)
        self._found = None
        self.dd_replace = QtWidgets.QPushButton("Replace", self.dd_replace_row)
        self.dd_replace.setObjectName("SWRelationsReplace")
        self.dd_replace.setToolTip("The picked entity takes the place of the one picked in the table")
        self.dd_replace.clicked.connect(self.replace_current)
        rr.addWidget(self.dd_replace_with, 1)
        rr.addWidget(self.dd_replace)
        self.entities_group.content.addWidget(self.dd_find)
        self.entities_group.content.addWidget(self.dd_replace_row)
        self.dd_table.hide()
        self.dd_find.hide()
        self.dd_replace_row.hide()
        self._replace_key = None
        self.column.addWidget(self.entities_group)

    def _build_relations(self, body):
        self.relations_group = Group("Existing Relations", body)
        grid = QtWidgets.QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        # Display/Delete Relations only: the filter above the list, Delete and Delete All below it
        self.filter_box = QtWidgets.QComboBox(self.relations_group.body)
        self.filter_box.setObjectName("SWRelationsFilter")
        self.filter_box.addItems(DD_FILTERS)
        self.filter_box.setFocusPolicy(Qt.NoFocus)
        # narrow enough for the look's narrow pane: long names are cut, the list shows them whole
        self.filter_box.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.filter_box.setMinimumContentsLength(8)
        self.filter_box.activated.connect(lambda index: self.owner.set_dd_filter(DD_FILTERS[index]))
        self._theme_fields()
        self.dd_suppressed = QtWidgets.QCheckBox("Suppressed", self.relations_group.body)
        self.dd_suppressed.setObjectName("SWRelationsSuppressed")
        self.dd_suppressed.setFocusPolicy(Qt.NoFocus)
        self.dd_suppressed.clicked.connect(self._suppressed_clicked)
        self.dd_buttons = QtWidgets.QWidget(self.relations_group.body)
        row = QtWidgets.QHBoxLayout(self.dd_buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self.dd_undo = QtWidgets.QToolButton(self.dd_buttons)
        self.dd_undo.setObjectName("SWRelationsUndo")
        self.dd_undo.setToolTip("Undo last relation change")
        self.dd_undo.setFocusPolicy(Qt.NoFocus)
        self.dd_undo.setIconSize(QtCore.QSize(16, 16))
        undo_icon = icons.family("STANDARD_UNDO")
        if undo_icon.isNull():
            undo_icon = QtGui.QIcon(":/icons/edit-undo.svg")
        if undo_icon.isNull():
            self.dd_undo.setText("Undo")
        else:
            self.dd_undo.setIcon(undo_icon)
        self.dd_undo.clicked.connect(lambda: self.owner.undo_relation_change())
        row.addWidget(self.dd_undo)
        self.dd_delete = QtWidgets.QPushButton("Delete", self.dd_buttons)
        self.dd_delete.setObjectName("SWRelationsDelete")
        self.dd_delete.setFocusPolicy(Qt.NoFocus)
        self.dd_delete.clicked.connect(self.delete_current_relation)
        self.dd_delete_all = QtWidgets.QPushButton("Delete All", self.dd_buttons)
        self.dd_delete_all.setObjectName("SWRelationsDeleteAll")
        self.dd_delete_all.setFocusPolicy(Qt.NoFocus)
        self.dd_delete_all.clicked.connect(self.delete_all_listed)
        for button in (self.dd_delete, self.dd_delete_all):
            button.setMinimumWidth(10)
            button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
            row.addWidget(button)

        self.dd_repair = QtWidgets.QPushButton("Repair All Dangling", self.relations_group.body)
        self.dd_repair.setObjectName("SWRelationsRepairDangling")
        self.dd_repair.setFocusPolicy(Qt.NoFocus)
        self.dd_repair.setToolTip("Re-attaches every dangling relation to the model edge now in its place")
        self.dd_repair.clicked.connect(lambda: self.owner.repair_all())
        grid.addWidget(self.filter_box, 0, 1)
        grid.addWidget(self.dd_suppressed, 2, 1)
        grid.addWidget(self.dd_buttons, 3, 1)
        grid.addWidget(self.dd_repair, 5, 1)
        picture = self.relations_picture = QtWidgets.QLabel(self.relations_group.body)
        picture.setFixedSize(20, 20)
        picture.setPixmap(_pack_or("LAYOUT_DISPLAY_DEL_RELATION", _draw_relations_group).pixmap(16, 16))
        picture.setAlignment(Qt.AlignCenter)
        self.relations = self._list("SWExistingRelations", self.relations_group.body)
        self.relations.customContextMenuRequested.connect(self._relations_menu)
        self.relations.currentRowChanged.connect(lambda row: self._current_relation_changed())
        info_icon = self.info_icon = QtWidgets.QLabel(self.relations_group.body)
        info_icon.setFixedSize(20, 20)
        info_icon.setPixmap(_icon(_draw_info).pixmap(16, 16))
        info_icon.setAlignment(Qt.AlignCenter)
        self.state = QtWidgets.QLabel("", self.relations_group.body)
        self.state.setObjectName("SWRelationsState")
        grid.addWidget(picture, 1, 0, Qt.AlignTop)
        grid.addWidget(self.relations, 1, 1)
        grid.addWidget(info_icon, 4, 0)
        grid.addWidget(self.state, 4, 1)
        self.relations_group.content.addLayout(grid)
        self.column.addWidget(self.relations_group)

    def _build_add(self, body):
        self.add_group = Group("Add Relations", body)
        self.add_box = QtWidgets.QVBoxLayout()
        self.add_box.setContentsMargins(0, 0, 0, 0)
        self.add_box.setSpacing(2)
        self.add_group.content.addLayout(self.add_box)
        self.note = QtWidgets.QLabel("", self.add_group.body)
        self.note.setObjectName("SWRelationsNote")
        self.note.setWordWrap(True)
        self.note.hide()
        self.add_group.content.addWidget(self.note)
        self.buttons = []
        self.column.addWidget(self.add_group)

    def _build_options(self, body):
        self.options_group = Group("Options", body)
        self.construction = QtWidgets.QCheckBox("For construction", self.options_group.body)
        self.construction.setObjectName("SWForConstruction")
        self.construction.setFocusPolicy(Qt.NoFocus)
        self.construction.clicked.connect(self._construction_clicked)
        self.options_group.content.addWidget(self.construction)

        self.infinite = QtWidgets.QCheckBox("Infinite length", self.options_group.body)
        self.infinite.setObjectName("SWLineInfinite")
        self.infinite.setFocusPolicy(Qt.NoFocus)
        self.infinite.clicked.connect(lambda on: self.owner.infinite(bool(on)))
        self.infinite.hide()
        self.options_group.content.addWidget(self.infinite)
        self.column.addWidget(self.options_group)

    def _build_parameters(self, body):
        ""

        self.parameters_group = Group("Parameters", body)
        self.more_group = Group("Additional Parameters", body)
        self.more_group.body.setVisible(False)
        self.more_group._update_fold()
        self.parameter_note = QtWidgets.QLabel("", self.parameters_group.body)
        self.parameter_note.setObjectName("SWParametersNote")
        self.parameter_note.setWordWrap(True)
        self.parameter_note.hide()
        self.parameters_group.content.addWidget(self.parameter_note)
        self._wheel = _FieldWheel(self)
        self.column.addWidget(self.parameters_group)
        self.column.addWidget(self.more_group)

        self.spline_group = Group("Parameters", body)
        self.spline_group.setObjectName("SWGroup_SplineParameters")
        self.spline_group.hide()
        self.column.addWidget(self.spline_group)
        self.spline_fields = {}         # style flag -> (SplineFields, options box, parameters box)

    def _field(self, group, key):
        row = QtWidgets.QWidget(group.body)
        line = QtWidgets.QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        picture = QtWidgets.QLabel(row)
        picture.setFixedSize(20, 20)
        picture.setAlignment(Qt.AlignCenter)
        picture.setPixmap(_parameter_icon(key).pixmap(16, 16))
        picture.setToolTip(_NAMES[key])
        box = Gui.UiLoader().createWidget("Gui::QuantitySpinBox", row)
        box.setObjectName("SWParameter_" + key)
        box.setToolTip(_NAMES[key])
        box.setFocusPolicy(Qt.StrongFocus)          # the wheel scrolls the pane, not the value
        box.setProperty("unit", "deg" if key in ANGLES else "mm")

        box.setProperty("fw_bare_units", True)
        box.setProperty("minimum", -1e7)
        box.setProperty("maximum", 1e7)
        # as wide as the pane gives (its size hint is the width of the range's longest number)
        box.setMinimumWidth(60)
        box.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        box.installEventFilter(self._wheel)
        box.installEventFilter(self._keyfilter)
        edit = box.findChild(QtWidgets.QLineEdit)
        if edit is not None:        # textEdited: the user's typing only, never a value set by code
            edit.textEdited.connect(lambda text, k=key: self._typed.add(k))
        QtCore.QObject.connect(box, QtCore.SIGNAL("valueChanged(double)"),
                               lambda value, k=key: self._parameter_stepped(k))
        box.editingFinished.connect(lambda k=key: self._parameter_typed(k))
        QtCore.QObject.connect(box, QtCore.SIGNAL("returnPressed()"), lambda k=key: self._parameter_typed(k))
        line.addWidget(picture)
        line.addWidget(box, 1)
        group.content.insertWidget(group.content.count() - (1 if group is self.parameters_group else 0), row)
        return row, picture, box

    def _layout_parameters(self, keys):
        """Fields for these (Parameters, Additional Parameters) keys; the old ones go."""
        if keys == self._parameter_keys:
            return
        for row, picture, box in self.fields.values():
            row.hide()
            row.setParent(None)
            row.deleteLater()
        self.fields = {}
        self._typed.clear()
        self._parameter_keys = keys
        if keys is None:
            return
        main, more = keys
        for group, group_keys in ((self.parameters_group, main), (self.more_group, more)):
            for key in group_keys:
                self.fields[key] = self._field(group, key)

    def _fill_parameters(self, sketch, items):
        keys = None if self.dd or not items else parameter_keys(sketch, items)
        values = {}
        if keys is not None:
            try:
                values = parameter_values(sketch, items[0])
            except Exception:
                keys = None
        self._layout_parameters(keys)
        self.parameters_group.setVisible(keys is not None)
        self.more_group.setVisible(keys is not None and bool(keys[1]))
        if keys is None:
            return
        try:
            free = items[0].geo in {g for g, _ in sketch.getGeometryWithDependentParameters()}
        except Exception:
            free = True
        self._filling = True
        try:
            for key, (row, picture, box) in self.fields.items():
                box.setEnabled(free)
                if key in self._typed and box.hasFocus():
                    continue                # the user is typing there
                self._typed.discard(key)
                value = values.get(key)
                if value is not None:
                    self._show_value(box, key, value)
        finally:
            self._filling = False

    def _show_value(self, box, key, value):
        ""


        exact, value = value, round(value, 8) + 0.0
        quantity = App.Units.Quantity(value, App.Units.Unit("deg" if key in ANGLES else "mm"))
        try:
            shown = value / quantity.getUserPreferred()[1]
        except Exception:
            shown = value
        least = App.ParamGet("User parameter:BaseApp/Preferences/Units").GetInt("Decimals", 2)
        decimals = next((places for places in range(least, 7) if abs(shown - round(shown, places)) <= 2e-8), None)
        if decimals is None:
            text = ("%.8f" % shown).rstrip("0")
            decimals = max(least, min(8, len(text.split(".")[1]) if "." in text else 0))
        style = quantity.Format
        style["Precision"] = decimals
        quantity.Format = style
        if box.property("rawValue") != value or box.property("swShown") != box.text():
            box.setProperty("value", quantity)
            box.setProperty("swShown", box.text())
        box.setProperty("swValue", exact)

    def _parameter_typed(self, key):
        """Enter, or the field lost the focus: a typed value goes to the sketch."""
        field = self.fields.get(key)
        if self._filling or field is None or key not in self._typed:
            return
        self._typed.discard(key)
        self.owner.parameter(key, field[2].property("rawValue"))

    def _parameter_stepped(self, key):
        """The spin arrows or the arrow keys changed the value: it goes to the sketch at once."""
        field = self.fields.get(key)
        if self._filling or field is None or key in self._typed:
            return                  # typing: Enter or leaving the field applies it
        box = field[2]
        value, shown = box.property("rawValue"), box.property("swValue")
        if value is None:
            return
        step = box.property("singleStep") or 1.0
        if shown is not None and abs(value - shown) <= 1e-9 * (1.0 + abs(shown)):
            # fix281: no step, the value shown: nothing to apply. The box re-sends its value when the
            # page goes (taken off the pane after the sketch changed); applying it then gave the
            # old entity's length to whatever entity has that number now
            return
        if shown is not None:
            # FreeCAD's spin box steps from its text, rounded to the user's decimals: step from

            least = App.ParamGet("User parameter:BaseApp/Preferences/Units").GetInt("Decimals", 2)
            count = round((value - shown) / step)
            if count and abs(value - (shown + count * step)) <= 0.5 * 10 ** -least + 1e-9:
                value = shown + count * step
        self.owner.parameter(key, value)

    def apply_typed(self):
        """A value typed but not entered yet (the check mark was clicked)."""
        for key in list(self._typed):
            self._parameter_typed(key)

    def _ok_clicked(self):
        self.apply_typed()
        self.owner.close_and_clear()

    def show_parameter_note(self, text):
        self.parameter_note.setText(text)
        self.parameter_note.setVisible(bool(text))

    # ------------------------------------------------------------------ fill
    def fill(self, sketch, items, dd=None):
        ""


        self.sketch = sketch
        if not dd:
            items = window_items(items)     # a box's corner points are not listed (tester 2026-10-30)
        self.items = items
        self.dd = dd
        adding = getattr(self.owner, "_add", None) is not None and not dd
        title = "Display/Delete Relations" if dd else "Add Relations" if adding else title_for(items)
        if self.title.text() != title:
            self.title.setText(title)
        if dd:
            icon = _pack_or("LAYOUT_DISPLAY_DEL_RELATION", _draw_relations_group)
        else:
            icon = icons.family(title_icon_family(items))
            if icon.isNull():
                icon = _icon(_draw_properties)
        self.title_icon.setPixmap(icon.pixmap(20, 20))
        self.entities_group.title.setText("Entities" if dd else "Selected Entities")
        self.relations_group.title.setText("Relations" if dd else "Existing Relations")
        self.filter_box.setVisible(bool(dd))
        self.dd_suppressed.setVisible(bool(dd))
        self.dd_buttons.setVisible(bool(dd))
        try:
            self.dd_repair.setVisible(bool(dd) and sketch is not None and bool(_missing_externals(sketch)))
        except Exception:
            self.dd_repair.hide()
        self.relations_picture.setVisible(not dd)   # the title has it; the list takes the width
        self.info_icon.setVisible(not dd)
        self.state.setVisible(True)     # Display/Delete Relations: the picked relation's status (fix66)
        self._order_groups(bool(dd))
        self._plain_entities(bool(dd))
        self.entities.setVisible(not dd)
        self.dd_table.setVisible(bool(dd))
        self.dd_replace_row.setVisible(bool(dd))
        if not dd:
            self.dd_find.hide()
        if dd and self.filter_box.currentText() != dd:
            self.filter_box.setCurrentIndex(DD_FILTERS.index(dd))

        several = len(items) > 1
        self.entities_group.setVisible(bool(dd) or several or adding)
        if not dd:
            names = [e.name for e in items]
            if [self.entities.item(i).text() for i in range(self.entities.count())] != names:
                self.entities.clear()
                self.entities.addItems(names)
            self._fit(self.entities, len(names), 2, 6)

        listed = listed_relations(sketch, items, dd)
        if listed != self._listed:
            current = self.relations.currentRow()
            self.relations.clear()
            for indices, name in listed:
                entry = QtWidgets.QListWidgetItem(name)
                entry.setData(Qt.UserRole, list(indices))
                kind = _relation_kind(name)
                if kind not in DIMENSIONS and kind != "Distance":
                    try:
                        entry.setIcon(relation_icon(kind))     # each row with its relation's icon (fix66)
                    except Exception as _fw_err:
                        _fw_log("relationspm.py:3516", _fw_err)
                self.relations.addItem(entry)
            if 0 <= current < self.relations.count() and [n for _, n in listed] == [n for _, n in self._listed]:
                self.relations.setCurrentRow(current)
            self._listed = listed
        self._fit(self.relations, len(listed), 6 if dd else 4, 14 if dd else 8)
        if dd:
            self._show_relation_entities()
            self.dd_delete.setEnabled(self.relations.currentItem() is not None)
            self.dd_delete_all.setEnabled(self.relations.count() > 0)
            self.dd_undo.setEnabled(last_relation_change(sketch) is not None)
        bad = defined_state(sketch, items)
        try:
            unsolvable_set = set(sketch.ConflictingConstraints)
            bad_set = unsolvable_set | set(sketch.RedundantConstraints)
        except Exception:
            unsolvable_set, bad_set = set(), set()
        invalid = bad == "Invalid"
        for row in range(self.relations.count()):
            entry = self.relations.item(row)
            wrong = any(i + 1 in bad_set for i in entry.data(Qt.UserRole))

            # the newest, and the others show as conflicting (yellow)
            unsolvable = bool(unsolvable_set) and max(unsolvable_set) - 1 in entry.data(Qt.UserRole)

            wrong = wrong or (invalid and len(sketch.Constraints) - 1 in entry.data(Qt.UserRole))
            off = suppressed(sketch, entry.data(Qt.UserRole))

            # and one that only over-defines with a yellow row
            entry.setBackground(QtGui.QBrush(UNSOLVABLE_RED) if unsolvable
                                else QtGui.QBrush(conflict_yellow()) if wrong else QtGui.QBrush())
            dangling = not wrong and not off and dd and relation_status(sketch, entry.data(Qt.UserRole)) == DANGLING
            entry.setForeground(QtGui.QBrush(QtGui.QColor("#000000") if wrong
                                             else DANGLING_BROWN if dangling
                                             else _list_ink("dim" if off else "text")))
        if dd:
            # Display/Delete Relations: the status of the relation picked in the list
            current = self.relations.currentItem()
            bad = relation_status(sketch, current.data(Qt.UserRole)) if current is not None else ""
        if self.state.text() != bad:
            self.state.setText(bad)
        self._highlight_current()
        if dd:
            self.add_group.setVisible(False)
            self.options_group.setVisible(False)
            self._fill_parameters(sketch, items)
            self.spline_group.hide()
            return

        keys = relations_for(window_items(items))
        if keys != self._keys:
            for b in self.buttons:
                self.add_box.removeWidget(b)
                b.setParent(None)
                b.deleteLater()
            self.buttons = []
            for key in keys:
                b = RelationButton(key, self.add_group.body)
                b.clicked.connect(lambda checked=False, k=key: self.owner.add(k))
                self.add_box.addWidget(b)
                self.buttons.append(b)
            self._keys = keys
        self.add_group.setVisible(bool(keys))


        # Relations, Add Relations; Options and Parameters belong to the entity's Properties page
        adding = getattr(self.owner, "_add", None) is not None and not self.dd
        targets = [] if adding else [e for e in items if e.own and e.kind != "point"]
        self.options_group.setVisible(bool(targets))
        if targets:
            on = [e.construction for e in targets]
            state = Qt.Checked if all(on) else (Qt.PartiallyChecked if any(on) else Qt.Unchecked)
            self.construction.setTristate(state == Qt.PartiallyChecked)
            if self.construction.checkState() != state:
                self.construction.setCheckState(state)
        one_line = len(targets) == 1 and len(items) == 1 and targets[0].kind == "line"
        self.infinite.setVisible(one_line)
        if one_line:
            on = is_infinite(sketch, targets[0].geo)
            if self.infinite.isChecked() != on:
                self.infinite.setChecked(on)
        self._fill_parameters(sketch, [] if adding else items)
        self._fill_spline(sketch, [] if adding else items)

    def _fill_spline(self, sketch, items):
        ""

        geo = None
        style = False
        at = None
        try:
            from . import splinepm
            if len(items) == 1 and items[0].own and items[0].kind == "curve" and \
                    splinepm.is_fw_spline(sketch, items[0].geo):
                geo = items[0].geo
            elif len(items) == 1 and items[0].own and items[0].kind == "point":
                geo, at = _spline_of_point(sketch, items[0])
            if geo is not None:
                from .fwsketch import splineedit
                style = bool(getattr(splineedit, "is_style", lambda s, g: False)(sketch, geo))
        except Exception:
            geo = None
        for key, (fields, options, parameters) in self.spline_fields.items():
            if geo is None or key != style:
                options.setVisible(False)
                parameters.setVisible(False)
        if geo is None:
            self.spline_group.hide()
            return
        if style not in self.spline_fields:
            from . import splinepm
            options = splinepm.Box(self.options_group)
            parameters = splinepm.Box(self.spline_group)
            fields = splinepm.SplineFields(self, options, parameters, style=style)
            self.spline_fields[style] = (fields, options, parameters)
        fields, options, parameters = self.spline_fields[style]
        options.setVisible(True)
        parameters.setVisible(True)
        self.options_group.setVisible(True)
        self.parameters_group.setVisible(False)
        self.more_group.setVisible(False)
        self.spline_group.show()
        if fields.geo != geo:
            fields.set_spline(geo)
        else:
            fields.fill()
        if at is not None:
            info = fields.info()
            points = info["points"] if info else []
            if points:
                near = min(range(len(points)), key=lambda i: (points[i][0] - at[0]) ** 2 + (points[i][1] - at[1]) ** 2)
                if (points[near][0] - at[0]) ** 2 + (points[near][1] - at[1]) ** 2 < 1e-8:
                    fields.index.setValue(near + 1)

    def _fit(self, box, rows, low, high):
        rows = max(low, min(high, rows))
        height = box.sizeHintForRow(0) if box.count() else QtGui.QFontMetrics(box.font()).height() + 4
        box.setFixedHeight(rows * max(16, height) + 2 * box.frameWidth() + 4)

    def show_note(self, text):
        self.note.setText(text)
        self.note.setVisible(bool(text))

    # ------------------------------------------------------------------ actions
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.escape()
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()          # a field took its value; nothing else acts on it
            return
        super().keyPressEvent(event)

    def escape(self):
        self.owner.close_and_clear()

    def show_help(self):
        ""
        title = self.title.text()
        try:
            from . import pmhelp
            if title not in pmhelp.HELP:
                pmhelp.HELP[title] = SKETCH_HELP.get(title, SKETCH_HELP["Properties"])
            return pmhelp.show(self, title)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: no help for %s (%s)\n" % (title, error))
            return None

    def delete_current_relation(self):
        entry = self.relations.currentItem()
        if entry is not None:
            self.owner.delete(entry.data(Qt.UserRole))

    def delete_all_listed(self):
        self.owner.delete([i for row in range(self.relations.count())
                           for i in self.relations.item(row).data(Qt.UserRole)])

    def _order_groups(self, dd):
        """Display/Delete Relations has Relations above Entities; the properties of several
        picked entities have Selected Entities above Existing Relations."""
        above = self.column.indexOf(self.entities_group) < self.column.indexOf(self.relations_group)
        if above == dd:
            self.column.removeWidget(self.entities_group)
            at = self.column.indexOf(self.relations_group)
            self.column.insertWidget(at + 1 if dd else at, self.entities_group)

    def _plain_entities(self, plain):
        ""

        name = "SWRelationEntities" if plain else "SWSelectedEntities"
        if self.entities.objectName() != name:
            self.entities.setObjectName(name)
            self.entities.style().unpolish(self.entities)
            self.entities.style().polish(self.entities)
            self._entities_row.setContentsMargins(0 if plain else 28, 0, 0, 0)

    def _current_relation_changed(self):
        self._show_relation_entities()
        self._highlight_current()
        if self.dd and self.sketch is not None:
            current = self.relations.currentItem()
            text = relation_status(self.sketch, current.data(Qt.UserRole)) if current is not None else ""
            if self.state.text() != text:
                self.state.setText(text)

    def _highlight_current(self):
        """The entities of the relation picked in the list, in pink on the sketch."""
        entry = self.relations.currentItem()
        keys = []
        if entry is not None and self.sketch is not None and self.isVisible():
            try:
                keys = relation_keys(self.sketch, entry.data(Qt.UserRole))
            except Exception:
                keys = []
        self.owner.highlight(self.sketch, keys)

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._highlight_current)

    def hideEvent(self, event):
        self.owner.highlight(None, [])
        super().hideEvent(event)

    def _suppressed_clicked(self, checked):
        entry = self.relations.currentItem()
        if entry is not None:
            self.owner.suppress(entry.data(Qt.UserRole), checked)

    def _show_relation_entities(self):
        """Display/Delete Relations: the Entities box lists what the current relation relates."""
        if not self.dd or self.sketch is None:
            return
        entry = self.relations.currentItem()
        self.dd_suppressed.setEnabled(entry is not None)
        self.dd_suppressed.setChecked(entry is not None and suppressed(self.sketch, entry.data(Qt.UserRole)))
        try:
            names = relation_entities(self.sketch, entry.data(Qt.UserRole)) if entry is not None else []
        except Exception:
            names = []
        if [self.entities.item(i).text() for i in range(self.entities.count())] != names:
            self.entities.clear()
            self.entities.addItems(names)
        self._fit(self.entities, len(names), 2, 6)
        self.dd_delete.setEnabled(entry is not None)
        try:
            keys = relation_keys(self.sketch, entry.data(Qt.UserRole)) if entry is not None else []
            rows = entity_rows(self.sketch, keys)
        except Exception:
            keys, rows = [], []
        now = [tuple(self.dd_table.topLevelItem(i).text(k) for k in range(3))
               for i in range(self.dd_table.topLevelItemCount())]
        if now != rows or getattr(self, "_table_keys", None) != keys:
            keep = self.dd_table.currentIndex().row() if self.dd_table.currentItem() is not None else -1
            self.dd_table.clear()
            for key, row in zip(keys, rows):
                it = QtWidgets.QTreeWidgetItem(list(row))
                self.dd_table.addTopLevelItem(it)
            self._table_keys = keys
            if 0 <= keep < len(rows):
                self.dd_table.setCurrentItem(self.dd_table.topLevelItem(keep))
        self._replace_state()

    def _dangling_row(self):
        """External index k of the table row picked when it is a dangling model reference."""
        row = self.dd_table.currentIndex().row() if self.dd_table.currentItem() is not None else -1
        keys = getattr(self, "_table_keys", [])
        if self.sketch is None or not 0 <= row < len(keys):
            return None
        key = keys[row]
        g = key[1] if len(key) > 1 else None
        if not isinstance(g, int) or g > -3:
            return None
        k = -3 - g
        return k if any(m[0] == k for m in _missing_externals(self.sketch)) else None

    def find_current(self):
        """Find Replacement: the edge found goes into the box, Replace re-attaches to it."""
        k = self._dangling_row()
        self._found = None
        found = find_replacement(self.sketch, k) if k is not None else None
        if found is None:
            self.dd_replace_with.setText("")
            self.state.setText("No replacement found: pick one in the graphics area")
            self.dd_replace.setEnabled(False)
            return None
        self._found = (k, found)
        self.dd_replace_with.setText("%s@%s" % (found[1], found[0].Label))
        self.state.setText("")
        self.dd_replace.setEnabled(True)
        return found

    def _replace_state(self):
        """The Replace box shows the entity picked in the graphics area."""
        try:
            self.dd_find.setVisible(bool(self.dd) and self._dangling_row() is not None)
        except Exception as _fw_err:
            _fw_log("relationspm.py:3801", _fw_err)
        if self._found is not None and self._found[0] == self._dangling_row():
            try:
                picked = picked_subs(self.sketch) if self.sketch is not None else []
            except Exception:
                picked = []
            if not picked:
                return                  # the found edge stays in the box until something is picked
        self._found = None
        key, text = None, ""
        try:
            # picked_subs reads the picks resolved to the sketch's own names (Edge3, Vertex2):
            # unresolved, a pick in edit reads ";g4.edge3", which no key matched (Replace stayed grey)
            subs = picked_subs(self.sketch) if self.sketch is not None else []
            if subs:
                key = key_of_sub(self.sketch, subs[-1])
                if key is not None:
                    text = entity_names(self.sketch, [key])[0]
        except Exception:
            key = None
        self._replace_key = key
        if self.dd_replace_with.text() != text:
            self.dd_replace_with.setText(text)
        self.dd_replace.setEnabled(key is not None and self.dd_table.currentItem() is not None)

    def replace_current(self):
        if self._found is not None and self._found[0] == self._dangling_row():
            k, found = self._found
            self._found = None
            doc = self.sketch.Document
            doc.openTransaction("Replace")
            try:
                ok = repair_one(self.sketch, k, found)
            except Exception as error:
                ok = False
                App.Console.PrintWarning("FreeCAD: Replace: %s\n" % error)
            if ok:
                doc.commitTransaction()
                doc.recompute()
            else:
                doc.abortTransaction()
            try:
                self.owner.refresh()
            except Exception as _fw_err:
                _fw_log("relationspm.py:3845", _fw_err)
            return ok
        entry = self.relations.currentItem()
        row = self.dd_table.currentIndex().row() if self.dd_table.currentItem() is not None else -1
        keys = getattr(self, "_table_keys", [])
        if entry is None or not 0 <= row < len(keys) or self._replace_key is None:
            return None
        indices = entry.data(Qt.UserRole)
        made = replace_entity(self.sketch, indices[0], keys[row], self._replace_key)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("relationspm.py:3857", _fw_err)
        try:
            self.owner.refresh()
        except Exception as _fw_err:
            _fw_log("relationspm.py:3861", _fw_err)
        return made

    def drop_current_entity(self):
        if self.dd:
            return              # the Entities box of Display/Delete Relations is not the pick
        row = self.entities.currentRow()
        if 0 <= row < len(self.items):
            self.owner.unpick(self.items[row])

    def _relations_menu(self, pos):
        entry = self.relations.itemAt(pos)
        if entry is not None:
            self.relations.setCurrentItem(entry)
        menu = QtWidgets.QMenu(self.relations)
        delete = menu.addAction("Delete")
        delete.setEnabled(entry is not None)
        delete_all = menu.addAction("Delete All")
        delete_all.setEnabled(self.relations.count() > 0)
        if entry is not None:
            data = entry.data(Qt.UserRole)
            delete.triggered.connect(lambda checked=False, d=data: self.owner.delete(d))
        delete_all.triggered.connect(lambda checked=False: self.delete_all_listed())
        _popup(menu, self.relations.viewport().mapToGlobal(pos))

    def _entities_menu(self, pos):
        if self.dd:
            return
        entry = self.entities.itemAt(pos)
        if entry is not None:
            self.entities.setCurrentItem(entry)
        menu = QtWidgets.QMenu(self.entities)
        delete = menu.addAction("Delete")
        delete.setEnabled(entry is not None)
        clear = menu.addAction("Clear Selections")
        if entry is not None:
            delete.triggered.connect(lambda checked=False: self.drop_current_entity())
        clear.triggered.connect(lambda checked=False: self.owner.close_and_clear())
        _popup(menu, self.entities.viewport().mapToGlobal(pos))

    def _construction_clicked(self):
        on = self.construction.checkState() != Qt.Unchecked
        self.construction.setTristate(False)
        self.owner.construction(on)


def _popup(menu, pos):
    """The look's non-blocking menu (an exec() menu held FreeCAD's event loop on the PC)."""
    try:
        from . import widgets
        if hasattr(widgets, "popup_menu"):
            return widgets.popup_menu(menu, pos)
    except Exception as _fw_err:
        _fw_log("relationspm.py:3914", _fw_err)
    menu.aboutToHide.connect(lambda: QtCore.QTimer.singleShot(0, menu.deleteLater))
    menu.popup(pos)
    return menu


# --------------------------------------------------------------------------- observers
class _SelectionObserver:
    def __init__(self, owner):
        self.owner = owner

    def addSelection(self, doc, obj, sub, pnt):
        self.owner.soon()

    def removeSelection(self, doc, obj, sub):
        self.owner.soon()

    def setSelection(self, doc):
        self.owner.soon()

    def clearSelection(self, doc):
        self.owner.soon()

    def setPreselection(self, doc, obj, sub):
        self.owner.preselected(doc, obj, sub)

    def removePreselection(self, doc, obj, sub):
        self.owner.preselected(None, None, None)


class _DocumentObserver:
    def __init__(self, owner):
        self.owner = owner

    def slotChangedObject(self, obj, prop):
        if prop in ("Constraints", "Geometry", "ExternalGeometry"):
            self.owner.soon()

    def slotUndoDocument(self, doc):
        self.owner.soon()

    def slotRedoDocument(self, doc):
        self.owner.soon()


class _ViewEscape(QtCore.QObject):
    ""


    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.widgets = []

    def watch(self, on):
        view = self.owner.shell.view_widget() if on else None
        widgets = []
        if view is not None and alive(view):
            widgets = [view] + ([view.viewport()] if hasattr(view, "viewport") and view.viewport() is not None else [])
        if widgets == self.widgets:
            return
        for widget in self.widgets:
            if alive(widget):
                widget.removeEventFilter(self)
        self.widgets = widgets
        for widget in widgets:
            widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter3477(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter relationspm.py: %s\n" % exc)
            return False

    def _fw_filter3477(self, obj, event):
        t = event.type()
        if t in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress) and event.key() == Qt.Key_Escape \
                and (self.owner.dd_filter() is not None or getattr(self.owner, "_add", None) is not None) \
                and not contextbar.tool_running(self.owner.shell):
            if t == QtCore.QEvent.KeyPress:
                self.owner.close_and_clear()
            event.accept()
            return True
        return False


class _HoverWatch(QtCore.QObject):
    """While a glyph hover shows: after each pointer move in the 3D view (once FreeCAD has handled
    it), the owner checks that the sketcher still preselects the glyph."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.widget = None
        self.pending = False
        self.left = False

    def watch(self, on):
        view = self.owner.shell.view_widget() if on else None
        widget = view.viewport() if view is not None and alive(view) and hasattr(view, "viewport") else view
        if widget is self.widget:
            return
        if self.widget is not None and alive(self.widget):
            self.widget.removeEventFilter(self)
        self.widget = widget
        if widget is not None:
            widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter3511(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter relationspm.py: %s\n" % exc)
            return False

    def _fw_filter3511(self, obj, event):
        t = event.type()
        if t in (QtCore.QEvent.MouseMove, QtCore.QEvent.Leave):
            self.left = self.left or t == QtCore.QEvent.Leave
            if not self.pending:
                self.pending = True
                QtCore.QTimer.singleShot(0, self._check)
        return False

    def _check(self):
        left, self.pending, self.left = self.left, False, False
        self.owner.check_hover(left)


# --------------------------------------------------------------------------- controller

# items that cannot be solved red
CONFLICT_YELLOW = QtGui.QColor(214, 228, 12)
OVERDEFINED_PARAM = "OverDefinedColor"   # View group, packed RGBA as FreeCAD's sketch colours


def conflict_yellow():
    ""

    try:
        grp = App.ParamGet("User parameter:BaseApp/Preferences/View")
        packed = grp.GetUnsigned(OVERDEFINED_PARAM, 0xD6E40CFF)
        return QtGui.QColor((packed >> 24) & 0xFF, (packed >> 16) & 0xFF, (packed >> 8) & 0xFF)
    except Exception:
        return QtGui.QColor(CONFLICT_YELLOW)
UNSOLVABLE_RED = QtGui.QColor(235, 0, 8)
DANGLING_BROWN = QtGui.QColor(150, 100, 30)
LEGEND_PARAM = "ConflictLegend"


def sketch_trouble(sketch):
    """(over defined, unsolvable) for the sketch's last solve."""
    try:
        malformed = bool(list(sketch.MalformedConstraints))
        clashing = bool(list(sketch.ConflictingConstraints) or list(sketch.RedundantConstraints))
        invalid = "Invalid" in sketch.State
    except Exception:
        return False, False
    return clashing, malformed or (invalid and not clashing)


SHADING_PARAM = "ShadeSketchContours"
SHADING_NAME = "SWSketchShading"
SHADING_COLOUR = (0.43, 0.44, 0.59)


def _stop(timer):
    """Stops a Qt timer that Qt may already have deleted with its parent (FreeCAD closing)."""
    if timer is None or not alive(timer):
        return
    try:
        timer.stop()
    except RuntimeError as _fw_err:
        _fw_log("relationspm.py:4094", _fw_err)



def _tessellate(face):
    """(points, triangles) of face at a three-hundredth of its size. OpenCASCADE takes very long on
    a small absolute deflection (a 0.008 mm circle: 17 s), so a face far from 100 mm is meshed
    scaled to 100 mm and its points scaled back (fix65)."""
    size = max(face.BoundBox.DiagonalLength, 1e-9)
    if 1.0 <= size <= 10000.0:
        return face.tessellate(size / 300.0)
    k = 100.0 / size
    big = face.copy()
    big.scale(k, App.Vector(0, 0, 0))
    points, triangles = big.tessellate(100.0 / 300.0)
    return [p * (1.0 / k) for p in points], triangles

def _node_key(node):
    """The Coin node behind a pivy wrapper (wrappers differ call to call)."""
    try:
        return int(node.this)
    except Exception:
        return id(node)


class SketchShading(QtCore.QObject):
    ""


    def __init__(self):
        super().__init__(None)
        self.node = self.graph = self.signature = None
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    @staticmethod
    def enabled():
        try:
            from . import paths
            return paths.params().GetBool(SHADING_PARAM, True)
        except Exception:
            return True

    @staticmethod
    def _signature(sketch):
        try:
            return (sketch.Document.Name, sketch.Name,
                    tuple((str(g), sketch.getConstruction(i)) for i, g in enumerate(sketch.Geometry)))
        except Exception:
            return None

    @staticmethod
    def faces(sketch):
        """The closed regions of the sketch's normal (not construction) geometry, in its own
        coordinates; inner loops are holes."""
        return [f for group in SketchShading._closed_groups(sketch) for f in SketchShading._bullseye(group)]

    @staticmethod
    def _closed_groups(sketch):
        """The closed wires of the sketch's normal geometry, in groups faced on their own."""
        import Part
        edges = []
        for i, g in enumerate(sketch.Geometry):
            try:
                if sketch.getConstruction(i) or g.TypeId == "Part::GeomPoint":
                    continue
                edges.append(g.toShape())
            except Exception:
                continue
        if not edges:
            return []
        wires = []
        for group in Part.sortEdges(edges):
            try:
                wire = Part.Wire(group)
            except Exception:
                continue
            if wire.isClosed():
                wires.append(wire)
        if not wires:
            return []
        return SketchShading._clusters(wires)

    @staticmethod
    def _group_key(group):
        """What a group of wires looks like (edge count, length, box and centre of each wire):
        the same key, the same faces. Cheap on purpose: it runs for every wire on every change."""
        def wire(w):
            b, c = w.BoundBox, w.CenterOfMass
            return (len(w.Edges), round(w.Length, 9), round(b.XMin, 9), round(b.YMin, 9),
                    round(b.XMax, 9), round(b.YMax, 9), round(c.x, 9), round(c.y, 9))
        return tuple(sorted(wire(w) for w in group))

    def _meshes(self, sketch):
        """(points, triangles) of every closed region. A group of wires that did not change keeps
        its mesh from the last rebuild: re-facing and re-meshing all of them on every change cost
        about 90 ms a change in a 320-line sketch (review 1119 perf1)."""
        old = getattr(self, "_mesh_cache", {})
        new = {}
        out = []
        for group in self._closed_groups(sketch):
            try:
                key = self._group_key(group)
            except Exception:
                key = None
            meshes = old.get(key) if key is not None else None
            if meshes is None:
                meshes = []
                for face in self._bullseye(group):
                    points, triangles = _tessellate(face)
                    if triangles:
                        meshes.append((points, triangles))
            if key is not None:
                new[key] = meshes
            out += meshes
        self._mesh_cache = new
        return out

    @staticmethod
    def _bullseye(wires):
        import Part
        try:
            return list(Part.makeFace(wires, "Part::FaceMakerBullseye").Faces)
        except Exception:
            out = []
            for wire in wires:
                try:
                    out.append(Part.Face(wire))
                except Exception as _fw_err:
                    _fw_log("relationspm.py:4188", _fw_err)
            return out

    @staticmethod
    def _clusters(wires):
        """The wires in groups whose boxes touch (a hole sits inside its outer loop's box): each group
        is faced on its own, the same faces as all at once, without Bullseye nesting 500 circles
        against each other (3.5 s on entering a DXF sketch, fix152)."""
        if len(wires) < 8:
            return [wires]
        boxes = [w.BoundBox for w in wires]
        parent = list(range(len(wires)))

        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        eps = 1e-7
        order = sorted(range(len(wires)), key=lambda i: boxes[i].XMin)
        live = []
        for i in order:
            b = boxes[i]
            live = [j for j in live if boxes[j].XMax >= b.XMin - eps]
            for j in live:
                c = boxes[j]
                if c.YMax >= b.YMin - eps and b.YMax >= c.YMin - eps and c.ZMax >= b.ZMin - eps and b.ZMax >= c.ZMin - eps:
                    parent[root(i)] = root(j)
            live.append(i)
        groups = {}
        for i in range(len(wires)):
            groups.setdefault(root(i), []).append(wires[i])
        first = {}
        for i in range(len(wires)):
            first.setdefault(root(i), i)
        return [groups[r] for r in sorted(groups, key=lambda r: first[r])]

    def refresh(self):
        sketch = contextbar.sketch_in_edit() if self.enabled() else None
        if sketch is None:
            self.clear()
            return
        if QtWidgets.QApplication.mouseButtons() & QtCore.Qt.LeftButton:
            return      # a drag: the shading follows when the button comes up (1000-entity drags lagged)
        signature = self._signature(sketch)
        try:
            graph = Gui.getDocument(sketch.Document.Name).ActiveView.getSceneGraph()
        except Exception:
            self.clear()
            return
        # pivy hands out a new wrapper for the same scene graph on every call: compare the nodes
        # (==), not the wrappers (is), or every 300 ms tick rebuilt all regions (3 s a pointer
        # move in a 600-entity sketch)
        if signature == self.signature and self.graph is not None and self.graph == graph \
                and self.node is not None and graph.findChild(self.node) >= 0:
            return
        if self.node is None and getattr(self, "_none_for", None) == (signature, _node_key(graph)):
            return      # no closed region last time and nothing changed: don't search again
        self.clear()
        self.signature = signature
        faces = self._meshes(sketch)
        if not faces:
            self._none_for = (signature, _node_key(graph))
            return
        from pivy import coin
        place = _drawn_at(sketch)
        root = coin.SoSeparator()
        root.setName(SHADING_NAME)
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        material = coin.SoMaterial()
        material.diffuseColor = SHADING_COLOUR
        material.transparency = 0.5
        for node in (pick, light, material):
            root.addChild(node)
        lift = App.Vector(0, 0, 0.001)   # under FreeCAD's sketch lines (0.002 and up)
        for points, triangles in faces:
            coords = coin.SoCoordinate3()
            drawn = [place.multVec(p + lift) for p in points]
            coords.point.setValues(0, len(drawn), [(p.x, p.y, p.z) for p in drawn])
            faceset = coin.SoIndexedFaceSet()
            index = []
            for a, b, c in triangles:
                index += [a, b, c, -1]
            faceset.coordIndex.setValues(0, len(index), index)
            part = coin.SoSeparator()
            part.addChild(coords)
            part.addChild(faceset)
            root.addChild(part)
        graph.insertChild(root, 0)
        self.node, self.graph = root, graph

    def clear(self):
        if self.node is not None and self.graph is not None:
            try:
                if self.graph.findChild(self.node) >= 0:
                    self.graph.removeChild(self.node)
            except Exception as _fw_err:
                _fw_log("relationspm.py:4291", _fw_err)
        self.node = self.graph = self.signature = None

    def remove(self):
        _stop(self._timer)
        self.clear()
        if alive(self):
            self.deleteLater()


class ConflictLegend(QtWidgets.QWidget):
    ""

    @property
    def LINES(self):
        return ((UNSOLVABLE_RED, "Item is Unsolvable"), (conflict_yellow(), "Item Conflicts"))
    MARGIN = 6

    def __init__(self, shell):
        super().__init__(None)
        self.shell = shell
        self.setObjectName("SWConflictLegend")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFont(ui_font())
        self.hide()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    @staticmethod
    def enabled():
        try:
            from . import paths
            return paths.params().GetBool(LEGEND_PARAM, True)
        except Exception:
            return True

    def _host(self):
        try:
            view = self.shell.view_widget()
        except Exception:
            return None
        if view is None or not alive(view):
            return None
        host = view.viewport() if hasattr(view, "viewport") else view
        return host if host is not None and alive(host) else None

    def sizeHint(self):
        fm = self.fontMetrics()
        box = fm.height() - 2
        width = max(fm.horizontalAdvance(text) for _c, text in self.LINES)
        return QtCore.QSize(box + width + 3 * 4, 2 * fm.height() + 2 * 3)

    def refresh(self):
        sketch = contextbar.sketch_in_edit() if self.enabled() else None
        show = sketch is not None and any(sketch_trouble(sketch))
        host = self._host() if show else None
        if host is None:
            if self.isVisible():
                self.hide()
            return
        if self.parent() is not host:
            self.setParent(host)
        size = self.sizeHint()
        self.setGeometry(host.width() - size.width() - self.MARGIN, host.height() - size.height() - self.MARGIN,
                         size.width(), size.height())
        if not self.isVisible():
            self.show()
        self.raise_()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, False)
        p.fillRect(self.rect(), QtGui.QColor(215, 215, 227, 235))
        fm = self.fontMetrics()
        box = fm.height() - 2
        for row, (colour, text) in enumerate(self.LINES):
            top = 3 + row * fm.height()
            p.setPen(QtGui.QColor("#5a5a5a"))
            p.setBrush(colour)
            p.drawRect(QtCore.QRect(4, top + 1, box - 1, box - 1))
            p.setPen(QtGui.QColor("#000000"))
            flags = Qt.AlignLeft | Qt.AlignVCenter
            try:
                flags = int(flags)
            except TypeError:       # PySide 6 on FreeCAD 1.1.4: a Qt flag will not int()
                flags = flags.value
            p.drawText(QtCore.QRect(4 + box + 4, top, self.width(), fm.height()), flags, text)
        p.end()

    def remove(self):
        _stop(self._timer)
        if not alive(self):
            return
        self.hide()
        self.setParent(None)
        self.deleteLater()


class RelationsPM(QtCore.QObject):
    """Shows the page while sketch geometry is picked and no sketch tool runs, and for
    Display/Delete Relations until it is closed."""

    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self.panel = None
        self._pane = None
        self._dd = None             # Display/Delete Relations: (document, sketch) it is open for
        self._add = None            # Add Relations (the command): (document, sketch) it is open for
        self._dd_filter = DD_ALL
        self._escape = _ViewEscape(self)
        self._highlight = _Highlight()
        self._hover = _Highlight(HOVER, MAGENTA)
        self._hover_want = None     # (document, object, sub-element) FreeCAD preselects
        self._hover_pending = False
        self._hover_tip = False
        self._hover_glyph = (None, 0)   # (FreeCAD's constraint node group, constraint index)
        self._hover_colour = None       # the glyph's colour when the hover started
        self._hover_watch = _HoverWatch(self)
        self._legend = ConflictLegend(shell)
        self._shading = SketchShading()
        self._dismissed = None      # the pick the user turned away from with another tab
        self._signature = None
        self._note_count = None     # constraint count when the last note was shown
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self.update)
        self._selection = _SelectionObserver(self)
        self._document = _DocumentObserver(self)
        try:
            Gui.Selection.addObserver(self._selection)
        except Exception:
            self._selection = None
        try:
            App.addDocumentObserver(self._document)
        except Exception:
            self._document = None

    # ------------------------------------------------------------------ shell hooks
    def soon(self):
        if alive(self._timer) and not self._timer.isActive():
            self._timer.start()

    def remove(self):
        _stop(self._timer)
        self._dd = self._add = None
        self._escape.watch(False)
        self._highlight.clear()
        self._hover.clear()
        self._hover_watch.watch(False)
        if getattr(self, "_legend", None) is not None:
            self._legend.remove()
            self._legend = None
        if getattr(self, "_shading", None) is not None:
            self._shading.remove()
            self._shading = None
        if self._selection is not None:
            try:
                Gui.Selection.removeObserver(self._selection)
            except Exception as _fw_err:
                _fw_log("relationspm.py:4454", _fw_err)
            self._selection = None
        if self._document is not None:
            try:
                App.removeDocumentObserver(self._document)
            except Exception as _fw_err:
                _fw_log("relationspm.py:4460", _fw_err)
            self._document = None
        pane = self._pane
        if pane is not None and alive(pane):
            try:
                pane.header.tab_clicked.disconnect(self._tab_clicked)
            except Exception as _fw_err:
                _fw_log("relationspm.py:4467", _fw_err)
            if pane.current_name() == PAGE:
                pane.select_name("Model")
            pane.pages.pop(PAGE, None)
            if self.panel is not None and alive(self.panel):
                pane.stack.removeWidget(self.panel)
        if self.panel is not None and alive(self.panel):
            self.panel.setParent(None)
            self.panel.deleteLater()
        self.panel = None
        self._pane = None

    # ------------------------------------------------------------------ page
    def _left_pane(self):
        pane = getattr(self.shell, "left_pane", None)
        return pane if pane is not None and alive(pane) else None

    def _ensure_page(self, pane):
        if self.panel is not None and alive(self.panel) and self._pane is pane:
            return self.panel
        self.panel = Panel(self)
        pane._add_page(PAGE, self.panel)
        self.panel.hide()
        pane.header.tab_clicked.connect(self._tab_clicked)
        self._pane = pane
        return self.panel

    def _tab_clicked(self, index):
        pane = self._left_pane()
        if pane is None:
            return
        if index == PM_TAB:
            # After the pane's own switch to FreeCAD's task panel.
            self._dismissed = None
            QtCore.QTimer.singleShot(0, self.update)
        elif self._signature is not None:
            self._dismissed = self._signature

    def wanted(self):
        """(sketch, items) when the page should show, else (None, [])."""
        if not getattr(self.shell, "enabled", False):
            self._dd = self._add = None
            return None, []
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            self._dd = self._add = None
            return None, []
        if getattr(self.shell, "sketch_tool_page", None) is not None:
            self._dd = self._add = None     # Fully Define Sketch and the like have the pane
            return None, []
        try:
            if self.shell.tasks_wanted() or contextbar.tool_running(self.shell):
                self._dd = self._add = None
                return None, []
        except Exception as _fw_err:
            _fw_log("relationspm.py:4532", _fw_err)
            return None, []
        items = items_of(sketch, picked_with_model(sketch))
        if self._dd is not None:
            if self._dd == (sketch.Document.Name, sketch.Name):
                return sketch, items
            self._dd = self._add = None
        if self._add is not None:
            if self._add == (sketch.Document.Name, sketch.Name):
                return sketch, items
            self._add = None
        return (sketch, items) if items else (None, [])

    def add_relations(self):
        ""

        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            return False
        self._dd = None
        self._add = (sketch.Document.Name, sketch.Name)
        self._dismissed = None
        self.update()
        return True

    def dd_filter(self):
        """The Display/Delete Relations filter while it is open, else None."""
        return self._dd_filter if self._dd is not None else None

    def display_delete(self, dd=None):
        ""



        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            return False
        self._dd = (sketch.Document.Name, sketch.Name)
        if dd in DD_FILTERS:
            self._dd_filter = dd
        else:
            self._dd_filter = DD_SELECTED if items_of(sketch, picked_subs(sketch)) or picked_relations(sketch) else DD_ALL
        self._dismissed = None
        self.update()
        return True

    def set_dd_filter(self, name):
        if self._dd is not None and name in DD_FILTERS:
            self._dd_filter = name
            self.update()

    def update(self):
        pane = self._left_pane()
        if pane is None:
            return
        try:
            sketch, items = self.wanted()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: relations panel: %s\n" % error)
            sketch, items = None, []
        self._escape.watch(self._dd is not None or self._add is not None)
        if sketch is not None and items and self._dd is None and self._add is None:
            try:
                from . import blocks
                if blocks.show_block_pm(sketch, items):
                    return
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: Block PropertyManager: %s\n" % error)
        if sketch is None:
            self._highlight.clear()
            if self._hover.node is not None and contextbar.sketch_in_edit() is None:
                self._hover_want = None
                self._apply_hover()
            self._signature = None
            self._dismissed = None
            if self.panel is not None and pane.current_name() == PAGE:
                pane.restore_user_page()
            return
        panel = self._ensure_page(pane)
        signature = (sketch.Name, tuple(e.sub for e in items), self.dd_filter())
        if signature != self._signature or len(sketch.Constraints) != self._note_count:
            panel.show_note("")
        if signature != self._signature:
            panel.show_parameter_note("")
        self._signature = signature
        try:
            panel.fill(sketch, items, self.dd_filter())
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: relations panel: %s\n" % error)
        if pane.current_name() != PAGE and signature != self._dismissed:
            pane.select_name(PAGE)
            pane.header.set_current(PM_TAB)

    # ------------------------------------------------------------------ actions
    def _view_focus(self):
        view = self.shell.view_widget()
        if view is not None and alive(view):
            view.setFocus(Qt.OtherFocusReason)

    def add(self, key):
        sketch, items = self.wanted()
        if sketch is None:
            return
        if key == "Pierce" and any(getattr(e, "pierce", False) == MISSED for e in items):
            no_pierce_dialog()
            self._view_focus()
            return
        ok, message = add_relation(sketch, key, window_items(items))
        self._note_count = len(sketch.Constraints)
        if self.panel is not None:
            self.panel.show_note(message)
        if message:
            self.shell.window.statusBar().showMessage(message, 8000)
        self._view_focus()
        self.update()

    def delete(self, indices):
        sketch, items = self.wanted()
        if sketch is None:
            return
        delete_relations(sketch, indices)
        self.update()

    def undo_relation_change(self):
        """Display/Delete Relations' Undo last relation change: takes back the newest step when it
        is a relation step (add, delete, suppress, replace, repair), nothing else."""
        sketch, items = self.wanted()
        if sketch is None or last_relation_change(sketch) is None:
            return False
        try:
            sketch.Document.undo()
            sketch.recompute()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Undo last relation change: %s\n" % error)
            return False
        self.update()
        return True

    def repair_all(self):
        ""
        sketch, items = self.wanted()
        if sketch is None:
            return
        doc = sketch.Document
        doc.openTransaction("Repair Dangling Relations")
        try:
            repaired, left = repair_dangling(sketch)
        except Exception as error:
            doc.abortTransaction()
            App.Console.PrintWarning("FreeCAD: Repair Dangling Relations: %s\n" % error)
            return
        doc.commitTransaction()
        try:
            doc.recompute()
        except Exception as _fw_err:
            _fw_log("relationspm.py:4661", _fw_err)
        self.update()

    def highlight(self, sketch, keys):
        try:
            if sketch is None or not keys:
                self._highlight.clear()
            else:
                self._highlight.show(sketch, keys)
        except Exception as error:
            self._highlight.clear()
            App.Console.PrintWarning("FreeCAD: relation highlight: %s\n" % error)

    def preselected(self, doc, obj, sub):
        ""


        self._hover_want = (doc, obj, sub) if sub else None
        if not self._hover_pending:
            self._hover_pending = True
            QtCore.QTimer.singleShot(0, self._apply_hover)

    def _hovered_relation(self):
        want = self._hover_want
        sketch = contextbar.sketch_in_edit() if getattr(self.shell, "enabled", False) else None
        if not want or sketch is None or contextbar.tool_running(self.shell):
            return None
        doc, obj, sub = want
        last = sub.split(".")[-1]
        if doc != sketch.Document.Name or not last.startswith("Constraint") \
                or not (obj == sketch.Name or ("%s." % sketch.Name) in sub):
            return None
        try:
            index = int(last[len("Constraint"):]) - 1
            c = sketch.Constraints[index]
        except (ValueError, IndexError):
            return None
        keys = constraint_keys(sketch, c) if c.Type not in DIMENSIONS else None
        if index < 0 or not keys:
            return None
        return sketch, index, keys, "%s(%s)" % (relation_name(sketch, c), ", ".join(entity_names(sketch, keys)))

    def _apply_hover(self):
        self._hover_pending = False
        try:
            found = self._hovered_relation()
        except Exception:
            found = None
        if found is None:
            self._hover.clear()
            self._hover_watch.watch(False)
            self._hover_glyph, self._hover_colour = (None, 0), None
            if self._hover_tip:
                QtWidgets.QToolTip.hideText()
                self._hover_tip = False
            return
        sketch, index, keys, text = found
        try:
            self._hover.show(sketch, keys)
        except Exception as error:
            self._hover.clear()
            App.Console.PrintWarning("FreeCAD: relation highlight: %s\n" % error)
        group = _constraint_group(sketch)
        self._hover_glyph, self._hover_colour = (group, index), _glyph_colour(group, index)
        self._hover_watch.watch(True)
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), text, self.shell.view_widget())
        self._hover_tip = True

    def check_hover(self, left=False):
        """The sketcher lets go of a glyph without telling the selection (the pointer moved on into
        empty space): what changes is the glyph's colour. Then, or when the pointer leaves the
        view, the hover ends, and the stale preselection goes so the glyph can be hovered again."""
        if self._hover.node is None:
            self._hover_watch.watch(False)
            return
        if self._hover_pending:
            return      # a newer preselection is on its way and decides
        group, index = self._hover_glyph
        if not left and (self._hover_colour is None or _glyph_colour(group, index) == self._hover_colour):
            return
        self._hover_want = None
        self._apply_hover()
        try:
            pre = Gui.Selection.getPreselection()
            subs = [sub.split(".")[-1] for sub in getattr(pre, "SubElementNames", ())]
            if "Constraint%d" % (index + 1) in subs:
                Gui.Selection.clearPreselection()
        except Exception as _fw_err:
            _fw_log("relationspm.py:4749", _fw_err)

    def suppress(self, indices, on):
        sketch, items = self.wanted()
        if sketch is None:
            return
        set_suppressed(sketch, indices, on)
        self.update()

    def construction(self, on):
        sketch, items = self.wanted()
        if sketch is None:
            return
        set_construction(sketch, items, on)
        self._view_focus()
        self.update()

    def infinite(self, on):
        sketch, items = self.wanted()
        if sketch is None or len(items) != 1 or not items[0].own:
            return
        set_infinite(sketch, items[0].geo, on)
        self._view_focus()
        self.update()

    def parameter(self, key, value):
        """A value typed or stepped in the Parameters: the picked element takes it, or the
        panel says why not and shows the value the sketch keeps."""
        sketch, items = self.wanted()
        if sketch is None or len(items) != 1 or value is None:
            return
        changed, message = set_parameter(sketch, items[0], key, float(value))
        if self.panel is not None:
            self.panel.show_parameter_note(message)
        if message:
            self.shell.window.statusBar().showMessage(message, 8000)
        self.update()

    def unpick(self, item):
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            return
        if item.model:
            try:
                Gui.Selection.removeSelection(sketch.Document.Name, item.model[0], item.model[1])
            except Exception as _fw_err:
                _fw_log("relationspm.py:4795", _fw_err)
            self.soon()
            return
        try:
            Gui.Selection.removeSelection(sketch.Document.Name, sketch.Name, item.sub)
        except Exception:
            try:
                Gui.Selection.removeSelection(sketch, item.sub)
            except Exception as _fw_err:
                _fw_log("relationspm.py:4804", _fw_err)
        self.soon()

    def close_and_clear(self):
        self._dd = self._add = None
        self._escape.watch(False)
        self._highlight.clear()
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("relationspm.py:4814", _fw_err)
        self._view_focus()
        self.soon()


# --------------------------------------------------------------------------- command
class DisplayDeleteRelationsCommand:
    """The Sketch tab's Display/Delete Relations button: the relations panel lists all of the
    sketch's relations, or those of the picked entities, to review or delete."""

    def GetResources(self):
        return {
            "Pixmap": "Sketcher_SelectConstraints",
            "MenuText": "Display/Delete Relations",
            "ToolTip": "Lists geometric relations so they can be removed",
            # Without it FreeCAD greys the command out while the sketch's task panel is open
            "CmdType": "ForEdit",
        }

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        try:
            from . import shell as shell_module
            owner = getattr(shell_module.shell(), "relations_pm", None)
        except Exception:
            owner = None
        if owner is None:
            App.Console.PrintWarning("FreeCAD: Display/Delete Relations needs the look switched on\n")
            return
        owner.display_delete()


COMMAND = "SWStyle_DisplayDeleteRelations"
ADD_COMMAND = "SWStyle_AddRelations"


class AddRelationsCommand:
    ""


    def GetResources(self):
        return {"Pixmap": "Constraint_Coincident", "MenuText": "Add Relation",
                "ToolTip": "Ties the picked entities together with a relation", "CmdType": "ForEdit"}

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        try:
            from . import shell as shell_module
            owner = getattr(shell_module.shell(), "relations_pm", None)
        except Exception:
            owner = None
        if owner is None:
            Gui.runCommand("Sketcher_ConstrainCoincidentUnified", 0)
            return
        owner.add_relations()


REPAIR_COMMAND = "SWStyle_RepairDanglingRelations"


class RepairDanglingCommand:
    ""

    def GetResources(self):
        return {"MenuText": "Repair Dangling Relations", "Pixmap": "Sketcher_ValidateSketch",
                "ToolTip": "Re-attaches the sketch's dangling relations to the model edges now in their place",
                "CmdType": "ForEdit"}

    def IsActive(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            sel = [o for o in Gui.Selection.getSelection() if o.TypeId == "Sketcher::SketchObject"]
            sketch = sel[0] if len(sel) == 1 else None
        try:
            return sketch is not None and bool(_missing_externals(sketch))
        except Exception:
            return False

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            sel = [o for o in Gui.Selection.getSelection() if o.TypeId == "Sketcher::SketchObject"]
            sketch = sel[0] if len(sel) == 1 else None
        if sketch is None:
            return
        doc = sketch.Document
        doc.openTransaction("Repair Dangling Relations")
        try:
            repaired, left = repair_dangling(sketch)
        except Exception as error:
            doc.abortTransaction()
            App.Console.PrintWarning("FreeCAD: Repair Dangling Relations: %s\n" % error)
            return
        doc.commitTransaction()
        doc.recompute()
        text = "%d dangling relation reference(s) repaired" % repaired
        if left:
            text += "; %d left: no model edge in their place (Display/Delete Relations > Replace)" % left
        try:
            Gui.getMainWindow().statusBar().showMessage(text + ".", 6000)
        except Exception as _fw_err:
            _fw_log("relationspm.py:4919", _fw_err)


AUTO_REPAIR_COMMAND = "SWStyle_AutoRepairRelation"


def picked_dangling(sketch, subs):
    """The dangling external references (k) behind the picked relation(s) or external edge(s)."""
    missing = {m[0]: m for m in _missing_externals(sketch)}
    out = []
    for sub in subs:
        geos = []
        if sub.startswith("Constraint"):
            try:
                c = sketch.Constraints[int(sub[10:]) - 1]
                geos = [c.First, c.Second, c.Third]
            except Exception:
                continue
        elif sub.startswith("ExternalEdge"):
            try:
                geos = [-int(sub[12:]) - 2]
            except ValueError:
                continue
        for g in geos:
            if g is not None and g <= -3 and (-3 - g) in missing and (-3 - g) not in out:
                out.append(-3 - g)
    return out


def _edited_picks():
    sketch = contextbar.sketch_in_edit()
    if sketch is None:
        return None, []
    subs = [n for s in Gui.Selection.getSelectionEx() if s.Object is sketch for n in s.SubElementNames]
    return sketch, subs


class AutoRepairCommand:
    ""


    def GetResources(self):
        return {"MenuText": "Auto Repair Sketch Relation or Dimension", "Pixmap": "Sketcher_ValidateSketch",
                "ToolTip": "Re-attaches the picked dangling relation to the model edge now in its place",
                "CmdType": "ForEdit"}

    def IsActive(self):
        try:
            sketch, subs = _edited_picks()
            return sketch is not None and bool(picked_dangling(sketch, subs))
        except Exception:
            return False

    def Activated(self):
        sketch, subs = _edited_picks()
        if sketch is None:
            return
        ks = picked_dangling(sketch, subs)
        doc = sketch.Document
        doc.openTransaction("Auto Repair Sketch Relation or Dimension")
        done, left = [], 0
        try:
            for k in ks:
                found = find_replacement(sketch, k)
                if found is not None and _attach(sketch, k, found):
                    done.append(k)
                else:
                    left += 1
            for k in sorted(done, reverse=True):
                sketch.delExternal(k)
            sketch.solve()
        except Exception as error:
            doc.abortTransaction()
            App.Console.PrintWarning("FreeCAD: Auto Repair: %s\n" % error)
            return
        doc.commitTransaction()
        doc.recompute()
        text = "Repaired" if done and not left else ("Unable to find a replacement" if not done else
                                                      "%d repaired, %d without a replacement" % (len(done), left))
        try:
            Gui.getMainWindow().statusBar().showMessage(text + ".", 6000)
        except Exception as _fw_err:
            _fw_log("relationspm.py:5001", _fw_err)
        Gui.Selection.clearSelection()

def register():
    """Adds the Display/Delete Relations command (once)."""
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, DisplayDeleteRelationsCommand())
        if ADD_COMMAND not in Gui.listCommands():
            Gui.addCommand(ADD_COMMAND, AddRelationsCommand())
        if REPAIR_COMMAND not in Gui.listCommands():
            Gui.addCommand(REPAIR_COMMAND, RepairDanglingCommand())
        if AUTO_REPAIR_COMMAND not in Gui.listCommands():
            Gui.addCommand(AUTO_REPAIR_COMMAND, AutoRepairCommand())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (COMMAND, error))


register()
