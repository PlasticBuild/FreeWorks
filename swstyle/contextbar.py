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

import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import catalog, events, featureflow, freezebar, icons, rollbackbar, style
from .widgets import FlatButton, alive


def _customize_option(name):
    """A Customize > Toolbars > Context toolbar settings row (customizedlg); on when unknown."""
    try:
        from . import customizedlg
        return bool(customizedlg.option(name))
    except Exception:
        return True

Qt = QtCore.Qt

FAR = 150            # px from the bar at which it has faded out completely
SOLID = 6            # px: this close, or over the bar, it is fully opaque
START = 0.75         # opacity just outside SOLID; it falls to 0 at FAR
CLICK_TIME = 0.6     # s: a selection this soon after a click in the view or tree came from it
MENU_TIME = 1.5      # s: a shortcut menu this soon after a right-click in the view or tree came from it
MENU_NEAR = 60       # px: and it opens this close to where the click was
OFFSET = (14, 12)    # lower-left corner of the bar: right of and above the pointer
BUTTON = (26, 24)
ICON = 20
MENU_BUTTON = (22, 20)           # the rows over a right-click menu (rcmenus pkg189)
MENU_ICON = 16
T = style.T          # the theme's colours, read when painting

SKETCH = "Sketcher::SketchObject"
PLANES = ("App::Plane", "PartDesign::Plane")
DATUMS = ("PartDesign::Line", "PartDesign::Point", "PartDesign::CoordinateSystem")


# --------------------------------------------------------------------------- picks
def picks():
    """[(object, element)] for the current selection, '' for a whole object."""
    out = []
    try:
        selection = Gui.Selection.getSelectionEx()
    except Exception:
        return out
    for entry in selection:
        subs = [s for s in entry.SubElementNames if s] or [""]
        for sub in subs:
            out.append((entry.Object, sub.rsplit(".", 1)[-1]))
    return out


def dialog_open():
    try:
        return bool(Gui.Control.activeDialog())
    except Exception:
        return False


def sketch_in_edit():
    """The sketch being edited, or None. Only a sketch counts: FreeCAD 1.1 leaves a
    datum plane 'in edit' after its dialog is cancelled."""
    try:
        gdoc = Gui.ActiveDocument
        edit = gdoc.getInEdit() if gdoc is not None else None
        obj = editobj.of(edit) if edit is not None else None
    except Exception:
        return None
    if obj is not None and obj.TypeId == SKETCH and dialog_open():
        return obj
    return None


def kind_of(obj, sub):
    """face, edge, vertex, plane, datum, sketch, feature or body; None for no toolbar."""
    t = obj.TypeId
    if t == SKETCH:
        return "sketch"
    if t in PLANES:
        return "plane"
    if sub.startswith("Face"):
        return "face"
    if sub.startswith("Edge"):
        return "edge"
    if sub.startswith("Vertex"):
        return "vertex"
    if sub:
        return None
    if t == "PartDesign::Body":
        return "body"
    if t in DATUMS:
        return "datum"
    if t.startswith("App::") or not hasattr(obj, "Shape"):
        return None
    return "feature"


def _solid_feature(obj):
    """A PartDesign feature in a body's solid chain (not the body, a datum or a sketch)."""
    return (obj is not None and hasattr(obj, "TypeId") and obj.TypeId.startswith("PartDesign::")
            and obj.TypeId != "PartDesign::Body" and hasattr(obj, "BaseFeature"))


def _tag(name):
    """Source tag of the last naming step of a mapped element name: '242', '-244' or ''."""
    i = name.rfind(";:H")
    if i < 0:
        return ""
    rest = name[i + 3:]
    for stop in (":", ",", ";"):
        j = rest.find(stop)
        if j >= 0:
            rest = rest[:j]
    return rest


def _created_here(name):
    """True when the feature whose shape holds this mapped name made the element.

    The last naming step ends in ';:H<tag>'. A negative tag means the element
    came from the feature's own tool shape (a Pocket's hole wall); ';:G' before
    it means the feature generated it (a Pad's faces from its sketch, a fillet's
    round face from an edge). A plain copy or a modified base face carries the
    base feature's positive tag and belongs further back.
    """
    if _tag(name).startswith("-"):
        return True
    i = name.rfind(";:H")
    head = name[:i] if i >= 0 else name
    j = head.rfind(";:")
    return j >= 0 and head[j + 2:j + 3] == "G"


def owner_feature(obj, sub):
    ""
    if not sub or not _solid_feature(obj):
        return obj
    try:
        history = obj.getElementHistory(sub)
    except Exception:
        history = None
    if history:
        owner = obj
        for item in history:
            source, name = item[0], item[1]
            if not _solid_feature(source):
                break
            owner = source
            if _created_here(str(name)):
                break
        return owner
    return _owner_by_geometry(obj, sub)


def _samples(shape):
    kind = shape.ShapeType
    if kind == "Vertex":
        return [shape.Point]
    if kind == "Edge":
        a, b = shape.FirstParameter, shape.LastParameter
        return [shape.valueAt(a + (b - a) * f) for f in (0.3, 0.5, 0.7)]
    if kind == "Face":
        u0, u1, v0, v1 = shape.ParameterRange
        out = []
        for fu, fv in ((0.5, 0.5), (0.3, 0.4), (0.7, 0.6), (0.4, 0.7), (0.6, 0.3), (0.2, 0.8), (0.8, 0.2)):
            p = shape.valueAt(u0 + (u1 - u0) * fu, v0 + (v1 - v0) * fv)
            try:
                if shape.isInside(p, 1e-6, True):
                    out.append(p)
            except Exception as _fw_err:
                _fw_log("contextbar.py:206", _fw_err)
            if len(out) == 3:
                break
        return out
    return []


def _all_on(points, elements):
    import Part
    compound = Part.Compound(elements)
    for p in points:
        try:
            if compound.distToShape(Part.Vertex(p))[0] > 1e-4:
                return False
        except Exception:
            return False
    return True


def _owner_by_geometry(obj, sub):
    """For shapes without element history: walk back while the element still
    lies on the same kind of element of the feature before."""
    try:
        points = _samples(obj.Shape.getElement(sub))
    except Exception:
        return obj
    if not points:
        return obj
    kind = sub.rstrip("0123456789")
    attr = {"Face": "Faces", "Edge": "Edges", "Vertex": "Vertexes"}.get(kind)
    owner, seen = obj, set()
    while attr:
        base = getattr(owner, "BaseFeature", None)
        if not _solid_feature(base) or base.Name in seen:
            break
        seen.add(base.Name)
        try:
            elements = getattr(base.Shape, attr)
        except Exception:
            break
        if not elements or len(elements) > 5000 or not _all_on(points, elements):
            break
        owner = base
    return owner


def sketch_of(feature):
    """The sketch a feature was made from (its Profile), or the sketch itself."""
    if feature is None:
        return None
    if feature.TypeId == SKETCH:
        return feature
    profile = getattr(feature, "Profile", None)
    if isinstance(profile, (tuple, list)):
        profile = profile[0] if profile else None
    if profile is not None and getattr(profile, "TypeId", "") == SKETCH:
        return profile
    return None


def editable(obj):
    if obj is None or obj.TypeId == SKETCH:
        return False
    if _solid_feature(obj) or obj.TypeId in DATUMS or obj.TypeId == "PartDesign::Plane":
        return True
    try:
        return obj.isDerivedFrom("Part::Primitive")
    except Exception:
        return False


def _single():
    p = picks()
    return p[0] if len(p) == 1 else (None, "")


def feature_to_edit():
    obj, sub = _single()
    if obj is None or obj.TypeId == SKETCH or dialog_open():
        return None
    owner = owner_feature(obj, sub)
    return owner if editable(owner) else None


def feature_to_roll_back():
    """The one feature picked that Rollback applies to: a solid feature after its body's first."""
    obj, sub = _single()
    if obj is None or sub or not _solid_feature(obj):
        return None
    return obj if rollbackbar.can_roll_back(obj) else None


def sketch_to_edit():
    obj, sub = _single()
    if obj is None or dialog_open():
        return None
    if obj.TypeId == SKETCH:
        return obj
    return sketch_of(owner_feature(obj, sub))


def _view_object(obj):
    try:
        return Gui.getDocument(obj.Document.Name).getObject(obj.Name)
    except Exception:
        return None


def _open(obj):
    """Open obj the way a double click in the tree does (with its undo step)."""
    vobj = _view_object(obj)
    if vobj is None:
        return False
    try:
        from . import equations
        if equations.is_sheet(obj):
            equations.show(obj.Document)
            return True
        from . import treevirtual
        if treevirtual.is_sensor(obj):
            treevirtual.edit_sensor(obj)
            return True
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Equations not opened: %s\n" % error)
    try:
        from . import refedit
        if refedit.edit(obj):
            return True
    except Exception as _fw_err:
        _fw_log("contextbar.py:refedit", _fw_err)
    try:
        if hasattr(vobj, "doubleClicked") and vobj.doubleClicked():
            return True
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: could not open %s: %s\n" % (obj.Label, error))
    try:
        Gui.getDocument(obj.Document.Name).setEdit(obj.Name, 0)
        return True
    except Exception as error:
        App.Console.PrintError("FreeCAD: could not edit %s: %s\n" % (obj.Label, error))
        return False


def edit_feature(obj=None):
    target = obj if obj is not None else feature_to_edit()
    return target is not None and _open(target)


def edit_feature_sketch(sketch=None):
    target = sketch if sketch is not None else sketch_to_edit()
    if target is None:
        return False
    Gui.Selection.clearSelection()
    return _open(target)


def _origin_of(obj):
    """The App::Origin holding a default plane, axis or point, or None."""
    if obj.TypeId not in ("App::Plane", "App::Line", "App::Point"):
        return None
    for parent in obj.InList:
        if parent.TypeId == "App::Origin":
            return parent
    return None


def _visible(obj):
    try:
        shown = bool(obj.ViewObject.Visibility)
    except Exception:
        return True
    origin = _origin_of(obj)
    if shown and origin is not None:
        try:
            shown = bool(origin.ViewObject.Visibility)
        except Exception as _fw_err:
            _fw_log("contextbar.py:376", _fw_err)
    return shown


def show_origin_feature(obj, on):
    """FreeCAD draws a default plane only while its Origin is shown, so its Show and
    Hide do nothing visible. Showing one plane shows the Origin with just that plane;
    hiding the last one hides the Origin again and leaves it as FreeCAD had it."""
    origin = _origin_of(obj)
    if origin is None:
        return False
    features = list(getattr(origin, "OriginFeatures", []) or [])
    if on:
        if not origin.ViewObject.Visibility:
            for f in features:
                f.ViewObject.Visibility = f is obj
            origin.ViewObject.Visibility = True
        obj.ViewObject.Visibility = True
    else:
        obj.ViewObject.Visibility = False
        if not any(f.ViewObject.Visibility for f in features):
            origin.ViewObject.Visibility = False
            for f in features:
                f.ViewObject.Visibility = True
    return True


def _planar(obj, sub):
    try:
        face = obj.Shape.getElement(sub)
        if face.Surface.__class__.__name__ == "Plane":
            return True
        return face.findPlane() is not None
    except Exception:
        return False


def _feature_icon(obj):
    icon = QtGui.QIcon()
    try:
        from . import propertymanager
        title = propertymanager.TITLES.get(obj.TypeId)
        if title:
            icon = icons.family(title[1])
    except Exception as _fw_err:
        _fw_log("contextbar.py:421", _fw_err)
    if icon.isNull():
        try:
            native = obj.ViewObject.Icon
            if isinstance(native, QtGui.QIcon):
                icon = native
        except Exception as _fw_err:
            _fw_log("contextbar.py:428", _fw_err)
    return icon


# --------------------------------------------------------------------------- entries
class Entry:
    __slots__ = ("key", "label", "icon", "tip", "run", "enabled")

    def __init__(self, key, label, icon, tip, run, enabled=True):
        self.key, self.label, self.icon, self.tip, self.run = key, label, icon, tip, run
        self.enabled = enabled


def active_native(cmd):
    for name in cmd.natives:
        if name == "Std_AlignToSelection" and not _anything_picked():
            continue    # FreeCAD calls it active with nothing picked, where it does nothing
        try:
            command = Gui.Command.get(name)
        except Exception:
            command = None
        if command is None:
            continue
        try:
            return name if command.isActive() else None
        except Exception:
            return None
    return None


def _anything_picked():
    try:
        return bool(Gui.Selection.getSelectionEx())
    except Exception:
        return False


def _toggle_checkable(native):
    """A command with a tick (Detach Segment On Drag, Sketch Numeric Input...): runCommand(name, 0)
    hands Activated(checked=False), so from a menu or bar it could only ever turn the setting off. Its
    own action is triggered instead, which flips the tick and runs it with the new state."""
    try:
        command = Gui.Command.get(native)
        acts = [a for a in (command.getAction() if command is not None else []) if isinstance(a, QtGui.QAction)]
    except Exception:
        return False
    if not acts:
        try:
            from . import checkstate
            return checkstate.run(native)       # a toggle with no QAction (Automatic Solve, Pen Settings)
        except Exception:
            return False
    if len(acts) != 1 or not acts[0].isCheckable():
        return False
    try:
        acts[0].trigger()
        return True
    except Exception as error:
        App.Console.PrintError("FreeCAD: %s failed: %s\n" % (native, error))
        return True


def run_key(shell, key):
    """Run a catalog command now, without waiting for FreeCAD's delayed enable state."""
    binding = shell.binding(key)
    call = binding.cmd.call
    if call and shell.special(call, binding):
        return
    native = active_native(binding.cmd)
    if native is None:
        return
    shell.note_command(native)
    if featureflow.run(native):
        return
    if key in _CHECKED_RELATIONS and _add_checked(shell, _CHECKED_RELATIONS[key]):
        return
    keep = _sketch_picks() if key.startswith("Rel") else None
    if _toggle_checkable(native):
        return
    try:
        Gui.runCommand(native, 0)
    except Exception as error:
        App.Console.PrintError("FreeCAD: %s failed: %s\n" % (native, error))
    if keep:
        _restore_picks(keep)


# Pop-up toolbar relations added the way the Properties panel adds them: checked first, and
# what the new relation makes redundant (Horizontal on the second of two lines made

_CHECKED_RELATIONS = {
    "RelHorizontal": "Horizontal", "RelVertical": "Vertical", "RelCollinear": "Collinear",
    "RelParallel": "Parallel", "RelPerpendicular": "Perpendicular", "RelEqual": "Equal",
    "RelTangent": "Tangent", "RelCoradial": "Coradial", "RelEqualCurvature": "Equal Curvature",
}


_PREFIX = "FreeCAD"


def _add_checked(shell, key):
    """Add the relation with the Properties panel's checked add. False: not handled here
    (no sketch, or the picks are not plain sketch entities), FreeCAD's command runs."""
    sketch = sketch_in_edit()
    if sketch is None:
        return False
    try:
        from . import relationspm
        items = relationspm.items_of(sketch, relationspm.picked_subs(sketch))
        if not items:
            return False
        ok, message = relationspm.add_relation(sketch, key, items)
    except Exception as error:
        App.Console.PrintWarning("%s: %s relation: %s\n" % (_PREFIX, key, error))
        return False
    if message:
        try:
            shell.window.statusBar().showMessage(message, 8000)
        except Exception as _fw_err:
            _fw_log("contextbar.py:547", _fw_err)
    return True


def _sketch_picks():
    """The sketch entities picked now, inside a sketch, else None."""
    if sketch_in_edit() is None:
        return None
    try:
        return [(s.DocumentName, s.ObjectName, sub) for s in Gui.Selection.getSelectionEx("", 0)
                for sub in s.SubElementNames]
    except Exception:
        return None


def _restore_picks(picks):
    ""

    if Gui.Selection.getSelectionEx("", 0):
        return
    for doc, name, sub in picks:
        try:
            Gui.Selection.addSelection(doc, name, sub)
        except Exception as _fw_err:
            _fw_log("contextbar.py:571", _fw_err)


def _tip(label, detail=""):
    text = "<b>%s</b>" % label
    return text + ("<br>%s" % detail if detail else "")


def _command_entry(shell, key, detail=""):
    binding = shell.binding(key)
    cmd = binding.cmd
    if cmd.natives and active_native(cmd) is None:
        return None
    if not cmd.natives and not (cmd.call and shell.special_enabled(cmd.call)):
        return None
    icon = binding.icon()
    if key in ("RelCoradial", "RelEqualCurvature") and not icons.paints(icons.family("FW_" + key)):     # coradial-1127; v2audit-1127: the V2 pack's first
        try:
            from . import relationspm
            icon = relationspm.relation_icon("Coradial" if key == "RelCoradial" else "Equal Curvature")
        except Exception as _fw_err:
            _fw_log("contextbar.py:coradial", _fw_err)
    return Entry(key, cmd.label, icon, _tip(cmd.label, detail or (cmd.tip or "")),
                 lambda shell=shell, key=key: run_key(shell, key))


def part_entries(shell, obj, sub):
    kind = kind_of(obj, sub)
    if kind is None:
        return []
    owner = owner_feature(obj, sub) if kind in ("face", "edge", "vertex") else obj
    sketch = obj if kind == "sketch" else sketch_of(owner)
    out = []
    for key in catalog.CONTEXT.get(kind, ()):
        entry = None
        if key == "EditFeature":
            if editable(owner):
                entry = Entry(key, "Edit Feature", _feature_icon(owner), _tip("Edit Feature", owner.Label),
                              lambda owner=owner: edit_feature(owner), freezebar.can_edit(owner))
        elif key == "EditFeatureSketch":
            if sketch is not None:
                icon = shell.binding(key).icon()
                if icon.isNull():
                    icon = shell.binding("EditSketch").icon()   # FreeCAD's Edit Sketch icon
                entry = Entry(key, "Edit Sketch", icon, _tip("Edit Sketch", sketch.Label),
                              lambda sketch=sketch: edit_feature_sketch(sketch), freezebar.can_edit(sketch))
        elif key == "Rollback":
            if _solid_feature(owner) and rollbackbar.can_roll_back(owner):
                entry = Entry(key, "Rollback", shell.binding(key).icon(),
                              _tip("Rollback", "Roll back to before %s" % owner.Label),
                              lambda owner=owner: rollbackbar.roll_back_to(owner))
        elif key == "HideSelection":
            shown = _visible(obj)
            entry = _command_entry(shell, key if shown else "ShowSelection")
            if entry is not None and _origin_of(obj) is not None:
                entry.run = lambda obj=obj, on=not shown: show_origin_feature(obj, on)
        elif key == "Sketch":
            if kind == "plane" or (kind == "face" and _planar(obj, sub)):
                entry = _command_entry(shell, key)
        elif key == "NormalTo":
            if kind in ("plane", "sketch") or (kind == "face" and _planar(obj, sub)):
                entry = _command_entry(shell, key)
        else:
            entry = _command_entry(shell, key)
        if entry is not None:
            out.append(entry)
    return out


def _curve(geo):
    name = geo.__class__.__name__
    if name in ("LineSegment", "Line"):
        return "line"
    if name in ("Circle", "ArcOfCircle"):
        return "circle"
    if name == "Point":
        return "point"
    return "curve"


H_AXIS, V_AXIS = -1, -2      # FreeCAD's geometry ids; external geometry counts down from -3


def sketch_items(sketch, subs):
    """[(kind, geo_id)] for the picked sketch elements; None if anything else is picked.
    kind: line, circle (circles and arcs), curve (conics, splines) or point.
    geo_id follows FreeCAD: own geometry from 0, axes -1 and -2, external from -3."""
    items = []
    geometry = sketch.Geometry
    for sub in subs:
        try:
            if sub.startswith("Edge"):
                i = int(sub[4:]) - 1
                items.append((_curve(geometry[i]), i))
            elif sub.startswith("ExternalEdge"):
                i = int(sub[12:]) - 1
                items.append((_curve(sketch.ExternalGeo[i + 2]), -3 - i))
            elif sub.startswith("Vertex"):
                geo_id, _pos = sketch.getGeoVertexIndex(int(sub[6:]) - 1)
                items.append(("point", geo_id))
            elif sub == "H_Axis":
                items.append(("line", H_AXIS))
            elif sub == "V_Axis":
                items.append(("line", V_AXIS))
            elif sub == "RootPoint":
                items.append(("point", H_AXIS))
            else:
                return None
        except Exception:
            return None
    return items


def _external_is_line(sketch, index):
    try:
        geo = sketch.ExternalGeo[index + 2]   # the two axes come first
        return _curve(geo) == "line"
    except Exception:
        return False


def relation_keys(items):
    ""
    if not items:
        return []
    kinds = [k for k, _ in items]
    ids = [g for _, g in items]
    own = all(g >= 0 for g in ids)
    axis = any(g in (H_AXIS, V_AXIS) for k, g in items if k == "line")
    n = len(items)
    lines, points, circles = kinds.count("line"), kinds.count("point"), kinds.count("circle")
    curves = kinds.count("curve")
    keys = []
    if n == 1:
        if lines and own:
            keys += ["RelHorizontal", "RelVertical"]
        if points:
            keys += ["RelFixPoint"] if own else []
        elif own:
            keys += ["RelFix", "RelConstruction"]
    elif lines == n:
        if own:
            keys += ["RelHorizontal", "RelVertical"]
        if n == 2:
            keys += ["RelCollinear", "RelParallel", "RelPerpendicular"]
        else:
            keys += ["RelParallel"]
        if own:
            keys += ["RelEqual", "RelFix", "RelConstruction"]
    elif points == n:
        if n == 2:
            keys += ["RelHorizontal", "RelVertical"]
            if ids[0] < 0 or ids[0] != ids[1]:
                keys += ["RelMerge"]
    elif n == 2 and points == 1:
        point = next(g for k, g in items if k == "point")
        other = next(g for k, g in items if k != "point")
        if point < 0 or point != other:
            keys += ["RelOnEdge"]
            if lines == 1 and not axis:
                keys += ["RelMidpoint"]
    elif n == 3 and points == 2 and lines == 1:
        keys += ["RelSymmetric"]
    elif n == 2 and lines == 1 and (circles == 1 or curves == 1):
        keys += ["RelTangent"]
    elif n == 2 and curves >= 1 and circles + curves == 2:
        keys += ["RelTangent"]          # an arc and a spline, two splines (as Add Relations offers)
    elif circles == n:
        if n == 2:
            keys += ["RelTangent", "RelConcentric", "RelCoradial"]     # coradial-1127
        if own:
            keys += ["RelEqual"]
    order = {k: i for i, k in enumerate(catalog.RELATIONS)}
    return sorted(dict.fromkeys(keys), key=lambda k: order.get(k, 99))


# relation key -> FreeCAD constraint types that already give it
_SAME = {
    "RelHorizontal": ("Horizontal", "Vertical"), "RelVertical": ("Horizontal", "Vertical"),
    "RelParallel": ("Parallel",), "RelPerpendicular": ("Perpendicular",), "RelEqual": ("Equal",),
    "RelTangent": ("Tangent",), "RelCollinear": ("Tangent",), "RelFix": ("Block",),
}


def existing_relations(sketch):
    """{(constraint type, frozenset of geometry ids)} for the edge-to-edge relations."""
    out = set()
    for c in sketch.Constraints:
        if c.Type in ("Horizontal", "Vertical", "Block") and c.FirstPos == 0 and c.Second == -2000:
            out.add((c.Type, frozenset((c.First,))))
        elif c.Type in ("Parallel", "Perpendicular", "Equal", "Tangent") and c.FirstPos == 0 \
                and c.SecondPos == 0 and c.Third == -2000:
            out.add((c.Type, frozenset((c.First, c.Second))))
    return out


def drop_existing(keys, items, existing):
    """Leave out relations the picked geometry already has."""
    edges = [g for k, g in items if k != "point"]
    if len(edges) != len(items) or not existing:
        return keys
    out = []
    for key in keys:
        types = _SAME.get(key)
        if types:
            if key in ("RelHorizontal", "RelVertical", "RelFix"):
                if any((t, frozenset((g,))) in existing for t in types for g in edges):
                    continue
            elif len(edges) == 2 and any((t, frozenset(edges)) in existing for t in types):
                continue
        out.append(key)
    return out


def sketch_entries(shell, sketch, subs):
    items = sketch_items(sketch, subs)
    if items is None:

        return [e for e in (_command_entry(shell, k) for k in dangling_keys(sketch, subs)) if e is not None]
    try:
        existing = existing_relations(sketch)
    except Exception:
        existing = set()
    out = []
    for key in drop_existing(relation_keys(items) + curvature_keys(sketch, items), items, existing) + \
            spline_end_keys(sketch, subs) + dangling_keys(sketch, subs):
        entry = _command_entry(shell, key)
        if entry is not None:
            out.append(entry)
    return out


def curvature_keys(sketch, items):
    """A spline and an arc, a line or a spline that meet at an end: Make Equal Curvature."""
    if len(items) != 2 or any(k == "point" for k, _g in items):
        return []
    try:
        from .fwsketch import eqcurv
        return ["RelEqualCurvature"] if eqcurv.offer(sketch, items[0][1], items[1][1]) else []
    except Exception as _fw_err:
        _fw_log("contextbar.py:curvature_keys", _fw_err)
        return []


def dangling_keys(sketch, subs):
    ""
    try:
        from . import relationspm
        return ["AutoRepairRelation"] if relationspm.picked_dangling(sketch, subs) else []
    except Exception:
        return []


def spline_end_keys(sketch, subs):
    ""
    if len(subs) != 1 or not subs[0].startswith("Vertex"):
        return []
    try:
        geo_id, pos = sketch.getGeoVertexIndex(int(subs[0][6:]) - 1)
        if geo_id >= 0 and pos in (1, 2) and sketch.Geometry[geo_id].TypeId == "Part::GeomBSplineCurve":
            return ["ReverseEndpointTangent"]

        if geo_id >= 0 and pos in (1, 2) and sketch.Geometry[geo_id].TypeId == "Part::GeomArcOfCircle" and any(
                c.Type == "Tangent" and ((c.First, c.FirstPos) == (geo_id, pos) or (c.Second, c.SecondPos) == (geo_id, pos))
                for c in sketch.Constraints):
            return ["ReverseEndpointTangent"]
    except Exception as _fw_err:
        _fw_log("contextbar.py:817", _fw_err)
    return []


def tool_running(shell):
    """A FreeCAD tool that picks with the mouse (a sketch tool, Smart Dimension...) is
    active: it puts its own picture cursor on the 3D view."""
    view = shell.view_widget()
    if view is None or not alive(view):
        return False
    widget = view.viewport() if hasattr(view, "viewport") else view
    return widget.cursor().shape() == Qt.BitmapCursor


def entries_for_selection(shell):
    """(mode, entries) for what is picked now; mode is 'part' or 'sketch'."""
    p = picks()
    if not p or tool_running(shell):
        return None, []
    sketch = sketch_in_edit()
    if sketch is not None:
        if any(obj is not sketch for obj, _ in p):
            return "sketch", []
        return "sketch", sketch_entries(shell, sketch, [sub for _, sub in p])
    if len(p) != 1:
        if dialog_open():
            return "part", []

        return "part", [e for e in (_command_entry(shell, key) for key in ("HideSelection", "ZoomSelection"))
                        if e is not None]
    if dialog_open():
        return "part", []
    obj, sub = p[0]
    if not sub and getattr(obj, "TypeId", "") == "PartDesign::Body":
        try:      # a body row picked: the same bar as its right-click icon row (R9 read 53, pkg207)
            from . import fmmenu
            return "part", fmmenu._body_tree_row(shell, obj, part_entries(shell, obj, sub))
        except Exception as _fw_err:
            _fw_log("contextbar.py:body-bar", _fw_err)
    return "part", part_entries(shell, obj, sub)


def under_pointer():
    """(document, object, element path) that FreeCAD highlights under the pointer, or None."""
    try:
        pre = Gui.Selection.getPreselection()
    except Exception:
        return None
    if pre is None or not getattr(pre, "ObjectName", ""):
        # a face under the pointer has its preselection cleared by the face hover (no fill, the

        try:
            from . import shell
            hover = getattr(shell.shell(), "face_hover", None)
            return hover.key if hover is not None and hover.key is not None else None
        except Exception:
            return None
    subs = tuple(pre.SubElementNames) or ("",)
    return pre.DocumentName, pre.ObjectName, subs[0]


def _leaf(name, sub):
    """(object, element) a selection path ends in: Body + 'Pocket.Face5' is ('Pocket', 'Face5'),
    the same as Pocket + 'Face5'. Mapped names (';...') are not object names."""
    parts = sub.split(".") if sub else [""]
    owners = [p for p in parts[:-1] if p and not p.startswith(";")]
    return (owners[-1] if owners else name), parts[-1]


def select_on_right_click(shell, item):
    ""



    if item is None or sketch_in_edit() is not None or dialog_open() or tool_running(shell):
        return False
    doc, name, sub = item
    target = _leaf(name, sub)
    for sel in Gui.Selection.getSelectionEx(doc, 0):
        if any(_leaf(sel.ObjectName, s) == target for s in (tuple(sel.SubElementNames) or ("",))):
            return False
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc, name, sub)
    return True


# --------------------------------------------------------------------------- widgets
class Button(FlatButton):
    def __init__(self, entry, parent):
        super().__init__(entry.icon, entry.tip, BUTTON, ICON, parent)
        self.entry = entry
        # the description in the status bar while the pointer is on it ("Adds a merge relation to

        detail = (entry.tip or "").split("<br>", 1)
        if len(detail) == 2 and detail[1]:
            self.setStatusTip(detail[1])
        self.setAccessibleName(entry.label)
        self.setFocusPolicy(Qt.NoFocus)
        self.setEnabled(entry.enabled)      # Edit Feature on a frozen feature (freeze bar)


class Bar(QtWidgets.QWidget):
    """The painted row of buttons; a child of the main window over the view and tree."""

    chosen = QtCore.Signal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("SWContextBar")
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.effect = QtWidgets.QGraphicsOpacityEffect(self)
        self.effect.setOpacity(1.0)
        self.setGraphicsEffect(self.effect)
        self.buttons = []
        self.hide()

    def fill(self, entries):
        for b in self.buttons:
            b.hide()
            b.setParent(None)
            b.deleteLater()
        self.buttons = []
        x = 2
        for entry in entries:
            b = (getattr(entry, "make", None) or Button)(entry, self)     # an entry may bring its own button (a named drop-down)
            b.move(x, 2)
            b.clicked.connect(lambda checked=False, e=entry: self.chosen.emit(e))
            b.show()
            self.buttons.append(b)
            x += b.width()
        self.resize(x + 2, BUTTON[1] + 4)

    def keys(self):
        return [b.entry.key for b in self.buttons]

    def button(self, key):
        for b in self.buttons:
            if b.entry.key == key:
                return b
        return None

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        pen = QtGui.QPen(T.line_mid)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(T.pane)
        painter.drawRect(r)
        painter.end()


class MenuRow(QtWidgets.QWidget):
    ""



    chosen = QtCore.Signal(object)

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setObjectName("SWContextMenuRow")
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(0)
        self.buttons = []
        for entry in entries:
            b = (getattr(entry, "make", None) or Button)(entry, self)

            b._icon_size = max(1, int(round(MENU_ICON * b.k)))
            b.setFixedSize(int(round(getattr(b, "row_width", lambda w: w)(MENU_BUTTON[0]) * b.k)),
                           int(round(MENU_BUTTON[1] * b.k)))
            b.clicked.connect(lambda checked=False, e=entry: self.chosen.emit(e))
            layout.addWidget(b)
            self.buttons.append(b)
        layout.addStretch(1)

    def keys(self):
        return [b.entry.key for b in self.buttons]

    def button(self, key):
        for b in self.buttons:
            if b.entry.key == key:
                return b
        return None


class _MenuSpy(QtCore.QObject):
    """Application-wide filter, installed only for a moment after a right-click: FreeCAD makes a
    new menu for every right-click and shows it at once."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.Show and isinstance(obj, QtWidgets.QMenu):
            try:
                self.owner.menu_shown(obj)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: shortcut menu toolbar: %s\n" % error)
        return False


class _Observer:
    """FreeCAD selection observer; every change asks for one later look."""

    def __init__(self, owner):
        self.owner = owner

    def addSelection(self, doc, obj, sub, pnt):
        self.owner.selection_changed()

    def removeSelection(self, doc, obj, sub):
        self.owner.selection_changed()

    def setSelection(self, doc):
        self.owner.selection_changed()

    def clearSelection(self, doc):
        self.owner.selection_changed()


# ctrlpick-1127: modifier keys pressed (or auto-repeating) while picking more do not dismiss the bar
_MODIFIER_KEYS = (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta)


class _Dismiss(QtCore.QObject):
    """Application-wide filter, installed only while the bar shows."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        if t in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride) and event.key() in _MODIFIER_KEYS:
            return False        # ctrlpick-1127: Ctrl/Shift/Alt held for a multi-pick keep the bar
        if t in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride, QtCore.QEvent.Wheel):
            self.owner.dismiss()
        elif t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick):
            # Qt 6 hands a real click to the window first and then to the widget under the
            # pointer: judge the click by where it is, or a click on the bar hides it first.
            if not self.owner.on_bar(obj) and not self.owner.over_bar(event):
                if t == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton \
                        and obj not in self.owner._trees and sketch_in_edit() is not None:
                    # ctrlpick-1127: a Ctrl+click in a sketch is taken by a sketch filter before the view's
                    # own filter sees it; this press is the click the next pick's bar is shown for
                    self.owner._click = (time.monotonic(), event.globalPosition().toPoint(), "view")
                self.owner.dismiss()
        elif t == QtCore.QEvent.WindowDeactivate and obj is self.owner.mw:
            self.owner.dismiss()
        return False


_DISMISS_TYPES = (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride, QtCore.QEvent.Wheel,
                  QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.WindowDeactivate)


class ContextBar(QtCore.QObject):
    """Shows the bar after a click in the 3D view or the tree selected something."""

    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self.mw = shell.window
        self.active = True
        self.bar = Bar(self.mw)
        self.bar.chosen.connect(self._chosen)
        self.mode = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._tick)
        self._dismiss = _Dismiss(self)
        self._dismissing = False
        self._watched = []
        self._trees = []
        self._attach_count = 0
        self._press_pos = None
        self._click = None
        self._pending = False
        self._right = None          # (time, global pos, 'view' or 'tree', on an item) of a right-click
        self._right_press = None
        self._menu_spy = _MenuSpy(self)
        self._spying = False
        self.menu_row = None        # the row in the last shortcut menu, for checks
        self._observer = _Observer(self)
        try:
            Gui.Selection.addObserver(self._observer)
        except Exception:
            self._observer = None
        self.mdi = self.mw.findChild(QtWidgets.QMdiArea)
        if self.mdi is not None:
            self.mdi.subWindowActivated.connect(self.attach)
        QtCore.QTimer.singleShot(0, self.attach)

    # ------------------------------------------------------------------ clicks
    def attach(self, *args):
        """Watch clicks on the active 3D view and on FreeCAD's tree."""
        if not self.active:
            return
        self._watched = [w for w in self._watched if alive(w)]
        self._trees = [w for w in self._trees if alive(w)]
        targets = []
        view = self.shell.view_widget()
        if view is not None and alive(view) and hasattr(view, "viewport"):
            targets.append((view.viewport(), False))
        # FreeCAD's tree lives as long as the window; look for it now and then only.
        if not self._trees or self._attach_count % 8 == 0:
            for tree in self.mw.findChildren(QtWidgets.QTreeWidget):
                if tree.metaObject().className() == "Gui::TreeWidget":
                    targets.append((tree.viewport(), True))
            for tree in self.mw.findChildren(QtWidgets.QTreeView, "SWFeatureTree"):
                targets.append((tree.viewport(), True))
        self._attach_count += 1
        for widget, is_tree in targets:
            if widget is None or widget in self._watched:
                continue
            widget.installEventFilter(self)
            self._watched.append(widget)
            if is_tree:
                self._trees.append(widget)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        if t == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            # The tree and the sketcher select on the press...
            where = "tree" if obj in self._trees else "view"
            pos = event.globalPosition().toPoint()
            self._click = (time.monotonic(), pos, where)
            self._press_pos = pos
            if where == "tree":
                # A click on the item that is already picked brings the bar back.
                QtCore.QTimer.singleShot(0, self.selection_changed)
        elif t == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            # ...the 3D view outside a sketch on the release.
            if obj not in self._trees:
                pos = event.globalPosition().toPoint()
                self._click = (time.monotonic(), pos, "view")
                start = self._press_pos
                if start is not None and (pos - start).manhattanLength() <= 4:
                    # A click, not a drag that turned the view.
                    QtCore.QTimer.singleShot(0, self.selection_changed)
        elif t == QtCore.QEvent.MouseButtonPress and event.button() == Qt.RightButton:
            # The tree picks on the press and may open its menu right away.
            pos = event.globalPosition().toPoint()
            self._right_press = pos
            if obj not in self._trees and self.shell.enabled and under_pointer() is None:
                self._hover(obj, event)
            self._arm_menu(pos, "tree" if obj in self._trees else "view", True)
        elif t == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.RightButton:
            pos = event.globalPosition().toPoint()
            if obj in self._trees:
                self._arm_menu(pos, "tree", True)
            else:
                # The 3D view opens its menu on the release, after this filter: pick first.
                start = self._right_press
                item = under_pointer()
                if self.shell.enabled and item is not None and start is not None \
                        and (pos - start).manhattanLength() <= 4:
                    select_on_right_click(self.shell, item)
                self._arm_menu(pos, "view", item is not None)
        return False

    # ------------------------------------------------------------------ shortcut menus
    @staticmethod
    def _hover(widget, event):
        """FreeCAD finds what is under the pointer only when the mouse moves. After a menu closes,
        or a sketch opens, a right-click without moving would find nothing; a move on the spot,
        before the view sees the press, has it look again (the sketcher picks from it too)."""
        move = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, event.position(), event.globalPosition(),
                                 Qt.NoButton, Qt.NoButton, event.modifiers())
        QtWidgets.QApplication.sendEvent(widget, move)

    def _arm_menu(self, pos, where, on_item):
        self._right = (time.monotonic(), pos, where, on_item)
        if not self._spying and self.active:
            events.register("contextbar.menu", (QtCore.QEvent.Show,), self._menu_spy.eventFilter)
            self._spying = True
        QtCore.QTimer.singleShot(int(MENU_TIME * 1000) + 100, self._disarm_menu)

    def _disarm_menu(self):
        right = self._right
        if right is not None and time.monotonic() - right[0] < MENU_TIME:
            return     # a later right-click armed it again
        self._right = None
        if self._spying:
            self._spying = False
            events.unregister("contextbar.menu")

    def menu_shown(self, menu):
        """Puts the toolbar row at the top of the shortcut menu FreeCAD is opening."""
        right = self._right
        if right is None or not self.active or not self.shell.enabled:
            return
        if not _customize_option("ShowInShortcutMenu"):
            return     # Customize > Toolbars > Context toolbar settings > Show in shortcut menu off
        if menu.property("swContextRow") or isinstance(menu.parent(), QtWidgets.QMenu):
            return     # done already, or a submenu
        when, pos, where, on_item = right
        if time.monotonic() - when > MENU_TIME:
            return
        if not menu.geometry().adjusted(-MENU_NEAR, -MENU_NEAR, MENU_NEAR, MENU_NEAR).contains(pos):
            return
        self._right = None
        QtCore.QTimer.singleShot(0, self._disarm_menu)
        if not on_item:
            return     # a right-click on empty space: FreeCAD's menu only
        try:
            mode, entries = entries_for_selection(self.shell)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: shortcut menu toolbar: %s\n" % error)
            return
        if entries:
            self.add_row(menu, entries)

    def add_row(self, menu, entries):
        row = MenuRow(entries)
        row.chosen.connect(lambda entry, m=menu: self._menu_chosen(m, entry))
        action = QtWidgets.QWidgetAction(menu)
        action.setDefaultWidget(row)
        actions = menu.actions()
        first = actions[0] if actions else None
        before = menu.geometry()
        menu.insertAction(first, action)
        if first is not None:
            menu.insertSeparator(first)
        menu.setProperty("swContextRow", True)
        menu.resize(menu.sizeHint())

        grown = menu.height() - before.height()
        top = before.y() - grown
        screen = menu.screen().availableGeometry() if menu.screen() is not None else None
        if screen is not None:
            top = max(screen.top(), top)
        menu.move(before.x(), top)
        self.menu_row = row

    def _menu_chosen(self, menu, entry):
        if alive(menu):
            menu.close()
        self._run_after_menu(entry)

    def _run_after_menu(self, entry, tries=0):
        # Run once the menu's own event loop has ended, not inside it.
        if QtWidgets.QApplication.activePopupWidget() is not None and tries < 50:
            QtCore.QTimer.singleShot(10, lambda: self._run_after_menu(entry, tries + 1))
            return
        QtCore.QTimer.singleShot(0, lambda: self._run(entry))

    # ------------------------------------------------------------------ selection
    def selection_changed(self):
        if self.active and not self._pending:
            self._pending = True
            QtCore.QTimer.singleShot(0, self._evaluate)

    def _evaluate(self):
        self._pending = False
        if not self.active or not alive(self.bar):
            return
        click = self._click
        if (click is None or time.monotonic() - click[0] > CLICK_TIME) and sketch_in_edit() is not None \
                and QtGui.QGuiApplication.queryKeyboardModifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
            # ctrlpick-1127-v3: a Ctrl/Shift+click on a spline is eaten by the spline handles' filter before
            # any of ours sees the press; a pick added with Ctrl/Shift held in a sketch came from a click
            click = self._click = (time.monotonic(), QtGui.QCursor.pos(), "view")
        if not self.shell.enabled or click is None or time.monotonic() - click[0] > CLICK_TIME:
            self.dismiss()
            return
        if not _customize_option("ShowOnSelection"):
            self.dismiss()      # Customize > Toolbars > Context toolbar settings > Show on selection off
            return
        try:
            mode, entries = entries_for_selection(self.shell)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: context toolbar: %s\n" % error)
            mode, entries = None, []
        if not entries:
            self.dismiss()
            return
        self.popup(mode, entries, click[1])

    # ------------------------------------------------------------------ showing
    def popup(self, mode, entries, global_pos):
        self.mode = mode
        self.bar.fill(entries)
        pos = self.mw.mapFromGlobal(global_pos)
        w, h = self.bar.width(), self.bar.height()
        x = pos.x() + OFFSET[0]
        y = pos.y() - OFFSET[1] - h
        if y < 2:
            y = pos.y() + 2 * OFFSET[1]
        x = max(2, min(x, self.mw.width() - w - 2))
        y = max(2, min(y, self.mw.height() - h - 2))
        self.bar.move(x, y)
        self.bar.raise_()
        self.bar.show()
        self._update_opacity()
        self.timer.start()
        if not self._dismissing:
            events.register("contextbar.dismiss", _DISMISS_TYPES, self._dismiss.eventFilter)
            self._dismissing = True

    def on_bar(self, obj):
        return isinstance(obj, QtWidgets.QWidget) and alive(self.bar) and (obj is self.bar or self.bar.isAncestorOf(obj))

    def over_bar(self, event):
        """The click is on the visible bar, whichever object sees it first."""
        try:
            p = event.globalPosition().toPoint()
        except Exception:
            return False
        if not alive(self.bar) or not self.bar.isVisible():
            return False
        return QtCore.QRect(self.bar.mapToGlobal(QtCore.QPoint(0, 0)), self.bar.size()).contains(p)

    def distance(self):
        top_left = self.bar.mapToGlobal(QtCore.QPoint(0, 0))
        r = QtCore.QRect(top_left, self.bar.size())
        p = QtGui.QCursor.pos()
        dx = max(r.left() - p.x(), 0, p.x() - r.right())
        dy = max(r.top() - p.y(), 0, p.y() - r.bottom())
        return (dx * dx + dy * dy) ** 0.5

    def _update_opacity(self):
        d = self.distance()
        if d <= SOLID:
            opacity = 1.0
        else:
            opacity = START * max(0.0, 1.0 - (d - SOLID) / float(FAR - SOLID))
        self.bar.effect.setOpacity(opacity)
        return d

    def _tick(self):
        if not alive(self.bar) or not self.bar.isVisible():
            self.dismiss()
            return
        if not self.shell.enabled:
            self.dismiss()
            return
        if self.mode == "sketch":
            if sketch_in_edit() is None:
                self.dismiss()
                return
        elif self.mode != "drawing" and dialog_open():

            # the view's context toolbar up with it, read 3 RC2)
            self.dismiss()
            return
        if self._update_opacity() >= FAR:
            self.dismiss()

    def _chosen(self, entry):
        self._click = None
        self.dismiss()
        QtCore.QTimer.singleShot(0, lambda: self._run(entry))

    @staticmethod
    def _run(entry):
        try:
            entry.run()
        except Exception as error:
            App.Console.PrintError("FreeCAD: %s failed: %s\n" % (entry.label, error))

    def dismiss(self):
        self.timer.stop()
        if alive(self.bar):
            self.bar.hide()
        if self._dismissing:
            self._dismissing = False
            QtCore.QTimer.singleShot(0, self._drop_dismiss_filter)

    def _drop_dismiss_filter(self):
        if not self._dismissing:
            events.unregister("contextbar.dismiss")

    # ------------------------------------------------------------------ removal
    def remove(self):
        self.active = False
        self.dismiss()
        events.unregister("contextbar.dismiss")
        events.unregister("contextbar.menu")
        self._spying = False
        self._right = None
        if self._observer is not None:
            try:
                Gui.Selection.removeObserver(self._observer)
            except Exception as _fw_err:
                _fw_log("contextbar.py:1385", _fw_err)
            self._observer = None
        if self.mdi is not None and alive(self.mdi):
            try:
                self.mdi.subWindowActivated.disconnect(self.attach)
            except Exception as _fw_err:
                _fw_log("contextbar.py:1391", _fw_err)
        for widget in self._watched:
            if alive(widget):
                widget.removeEventFilter(self)
        self._watched, self._trees = [], []
        if alive(self.bar):
            self.bar.hide()
            self.bar.setParent(None)
            self.bar.deleteLater()
