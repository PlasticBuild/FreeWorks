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

import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import drawings as D
from . import drawlive as DL

V = App.Vector


# --------------------------------------------------------------------------- view geometry
def view_scale(v):
    try:
        return float(v.getScale())
    except Exception:
        return float(v.Scale)


def view_extent(v):
    """(width, height) of a view on the sheet, mm (its visible lines; 40 x 40 until TechDraw has them)."""
    xs, ys = [], []
    try:
        for e in v.getVisibleEdges() or []:
            bb = e.BoundBox
            xs += [bb.XMin, bb.XMax]
            ys += [bb.YMin, bb.YMax]
    except Exception as _fw_err:
        _fw_log("drawviews.py:53", _fw_err)
    if not xs:
        return 40.0, 40.0
    return max(xs) - min(xs), max(ys) - min(ys)


# --------------------------------------------------------------------------- a model drawn as its parts
# TechDraw cuts a detail view out of its parent view's shape one source object at a time. An assembly given as one
# object (the assembly, or asmdrawing's view model) is cut as one compound, which also splits every part where it
# touches the next: 7.4 s for the excavator's detail. Given as its parts it is 2.7 s, the same lines. So an
# assembly view lists hidden "model parts" (one per child shape of the model) as its XSource, and the drawing code
# reads the model back through xsource() / source_shapes(). Drawings saved before this (XSource = the model)
# still read and draw as they did.
MODEL_PART = "FwModelPart"
_SYNC = set()


def is_model_part(o):
    return getattr(o, "SWKind", "") == MODEL_PART


def unsplit(objs):
    """objs with each model part replaced by its model (once, in order)."""
    out = []
    for o in objs or []:
        if is_model_part(o):
            o = getattr(o, "SWModel", None)
            if o is None:
                continue
        if o not in out:
            out.append(o)
    return out


def xsource(v):
    """The view's XSource as the model(s) it shows (model parts read back as their model)."""
    return unsplit(list(getattr(v, "XSource", []) or []))


def source_shapes(v):
    return xsource(v) + list(getattr(v, "Source", []) or [])


def _weld_slots(doc):
    """{body name: "StructuralMember:k"} for the weldment's member bodies (a frame edit makes them again, under
    new names, in the same slots)."""
    from . import wemember, wetrim
    out = {}
    for sm in wemember.structural_members(doc):
        for k in range(len(sm.Bodies)):
            slot = "%s:%d" % (sm.Name, k)
            tip = wetrim.current_tip(doc, slot)
            if tip is not None:
                out[tip.Name] = slot
    return out


def _same_body(model, entry):
    """True while the body an entry ("slot=name=id") names is still that object (a rebuilt member may come back
    under the same name: its object id differs)."""
    _slot, name, oid = entry.split("=")
    o = model.getObject(name)
    return o is not None and str(getattr(o, "ID", 0)) == oid


def relink_weldment_views(doc):
    ""



    done = []
    try:
        from . import wemember, wetrim
    except Exception:
        return done
    for v in [o for o in doc.Objects if o.isDerivedFrom("TechDraw::DrawViewPart")]:
        try:
            xs = list(getattr(v, "XSource", []) or [])
        except Exception:
            continue
        saved = list(getattr(v, "SWWeldSlots", []) or [])
        model = xs[0].Document if xs else App.listDocuments().get(getattr(v, "SWWeldDoc", "") or "")
        if model is None or model is doc or not wemember.structural_members(model):
            continue
        slots = _weld_slots(model)
        lost = [e for e in saved if e.count("=") == 2 and not _same_body(model, e)]
        if lost:
            whole = bool(getattr(v, "SWWeldWhole", False))
            keep = [o for o in xs if o.Name not in slots]                 # the beads, plates... still there
            want = [e.split("=", 1)[0] for e in saved if e.count("=") == 2]
            if whole:
                want += [sl for sl in sorted(set(slots.values()), key=lambda q: (q.split(":")[0], int(q.split(":")[1])))
                         if sl not in want]
            bodies = []
            for sl in want:
                tip = wetrim.current_tip(model, sl)
                if tip is not None and tip not in bodies:
                    bodies.append(tip)
            v.XSource = bodies + keep
            xs = bodies + keep
            done.append(v)
        mine = ["%s=%s=%s" % (slots[o.Name], o.Name, getattr(o, "ID", 0)) for o in xs if o.Name in slots]
        if mine != saved:
            if "SWWeldSlots" not in v.PropertiesList:
                v.addProperty("App::PropertyStringList", "SWWeldSlots", "FreeCAD", "the weldment members it shows")
                v.addProperty("App::PropertyString", "SWWeldDoc", "FreeCAD", "the weldment it shows")
                v.addProperty("App::PropertyBool", "SWWeldWhole", "FreeCAD", "it shows every member")
                for prop in ("SWWeldSlots", "SWWeldDoc", "SWWeldWhole"):
                    v.setPropertyStatus(prop, ["Hidden"])
            v.SWWeldSlots = mine
            v.SWWeldDoc = model.Name
            v.SWWeldWhole = bool(mine) and len(set(e.split("=")[0] for e in mine)) == len(set(slots.values())) \
                and not getattr(v, "SWCutListItem", "")
    return done


SHAPE_GEN = [0]     # counts model changes (a shape or placement of a model object changed, a model rebuilt)


def same_shape(a, b, gen=None):
    """a and b the same shape: FreeCAD gives a new copy (another hash code) each time a Shape is read, with the
    same inner shape (a partner) where nothing changed. An assembly's compound can keep its inner shape while a
    part in it changed (bench 11-13: the block edited, the assembly view kept the old block): a cached shape is
    taken only while no model changed since (gen, from SHAPE_GEN when it was cached)."""
    try:
        if gen is not None and gen != SHAPE_GEN[0]:
            return False
        return a.isPartner(b) and a.Orientation == b.Orientation and a.Placement.isSame(b.Placement, 1e-12)
    except Exception:
        return False


_KIDS = {}      # (document, model): (model change count, shape, child shapes): every part of a 301-part model
                # asks for them in one recompute


def _children(model):
    try:
        watch_parts()
        sh = model.Shape
        if sh.isNull():
            return []
        key = (model.Document.Name, model.Name)
        got = _KIDS.get(key)
        if got is None or not same_shape(got[1], sh, got[0]):
            if len(_KIDS) > 200:
                _KIDS.clear()
            got = _KIDS[key] = (SHAPE_GEN[0], sh, sh.childShapes())
        return list(got[2])
    except Exception as _fw_err:
        _fw_log("drawviews.py:204", _fw_err)
        return []


class ModelPart:
    """A hidden child shape of a model (FwModelPart): SWModel's child number SWIndex."""

    def __init__(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        import Part
        kids = _children(obj.SWModel) if obj.SWModel is not None else []
        i = int(obj.SWIndex)
        if 0 <= i < len(kids):
            # a solid as it is (TechDraw cuts a compound source the slow way); in a recompute the feature's
            # Placement is put on its shape, so it takes the child's own first
            obj.Placement = kids[i].Placement
            obj.Shape = kids[i]
        else:
            obj.Shape = Part.Shape()
        if obj.SWModel is not None and len(kids) != len(model_parts(obj.Document, obj.SWModel)):
            key = (obj.Document.Name, obj.SWModel.Document.Name, obj.SWModel.Name)
            if key not in _SYNC:
                _SYNC.add(key)
                QtCore.QTimer.singleShot(0, lambda d=obj.Document, m=obj.SWModel, k=key: _resync(d, m, k))

    def dumps(self):
        return None

    def loads(self, state):
        return None


def model_parts(doc, model):
    out = [o for o in doc.Objects if is_model_part(o) and getattr(o, "SWModel", None) is model]
    return sorted(out, key=lambda o: int(o.SWIndex))


def _new_part(doc, model, i):
    o = doc.addObject("Part::FeaturePython", "ModelPart")
    ModelPart(o)
    o.addProperty("App::PropertyString", "SWKind", "FreeCAD", "a part of a drawing view's model")
    o.SWKind = MODEL_PART
    o.addProperty("App::PropertyXLink", "SWModel", "FreeCAD", "the model this is a part of")
    o.SWModel = model
    o.addProperty("App::PropertyInteger", "SWIndex", "FreeCAD", "its child number in the model's shape")
    o.SWIndex = i
    for prop in ("SWKind", "SWModel", "SWIndex"):
        o.setEditorMode(prop, 1)
    o.Label = "%s part %d" % (model.Label, i + 1)
    try:
        o.ViewObject.Visibility = False
        o.ViewObject.ShowInTree = False
    except Exception as _fw_err:
        _fw_log("drawviews.py:257", _fw_err)
    return o


def sync_parts(doc, model):
    """doc's model parts of model, as many as its shape has children (made / removed); the views that list them
    list them all."""
    n = len(_children(model))
    have = model_parts(doc, model)
    for i in range(len(have), n):
        have.append(_new_part(doc, model, i))
    extra = have[n:]
    have = have[:n]
    for v in doc.Objects:
        xs = list(getattr(v, "XSource", []) or []) if v.isDerivedFrom("TechDraw::DrawViewPart") else []
        if any(is_model_part(o) and o.SWModel is model for o in xs):
            keep = [o for o in xs if not (is_model_part(o) and o.SWModel is model)]
            if list(xs) != keep + have:
                v.XSource = keep + have
    for o in extra:
        doc.removeObject(o.Name)
    return have


def drop_unused_parts(doc):
    """Removes doc's model parts no view lists any more."""
    used = set()
    for v in doc.Objects:
        if v.isDerivedFrom("TechDraw::DrawViewPart"):
            used.update(o.Name for o in (getattr(v, "XSource", []) or []) if is_model_part(o))
    for o in [o for o in doc.Objects if is_model_part(o) and o.Name not in used]:
        doc.removeObject(o.Name)


class _PartsObserver:
    """A model's document rebuilt: the drawings' model parts of it read it again at their next recompute (they
    link to it in another document, which FreeCAD does not mark for them)."""

    def slotChangedObject(self, obj, prop):
        if prop in ("Shape", "Placement", "LinkPlacement"):
            try:
                if not is_model_part(obj) and not obj.isDerivedFrom("TechDraw::DrawView"):
                    SHAPE_GEN[0] += 1
            except Exception as _fw_err:
                _fw_log("drawviews.py:301", _fw_err)

    def slotRecomputedDocument(self, doc):
        try:
            if not any(o.TypeId == "TechDraw::DrawPage" for o in doc.findObjects("TechDraw::DrawPage")):
                SHAPE_GEN[0] += 1          # a model rebuilt (a drawing's own recompute leaves the caches)
        except Exception:
            SHAPE_GEN[0] += 1
        try:
            for d in App.listDocuments().values():
                if d is doc:
                    continue
                touched = []
                for o in d.findObjects("Part::FeaturePython"):
                    m = getattr(o, "SWModel", None) if is_model_part(o) else None
                    if m is None:
                        continue
                    # the assembly itself, or a part file its components link to (a part edited and rebuilt)
                    if m.Document is doc or doc in _dependencies(m.Document):
                        o.touch()
                        touched.append(o)
                if touched:
                    # a part file edited: the assembly's shape (its children) is read again only when its own
                    # document recomputes, so recompute that first (engine drawing 11-13: a piston edit left the
                    # section's old piston)
                    for md in {getattr(o.SWModel, "Document", None) for o in touched}:
                        if md is not None and md is not doc and md is not d:
                            QtCore.QTimer.singleShot(0, lambda n=md.Name: _recompute_doc(n))
                    from . import drawmaint
                    drawmaint.update_later(d, touched)     # Automatically update views: the drawing follows
        except Exception as error:
            App.Console.PrintLog("FreeCAD: view model parts: %s\n" % error)


def _recompute_doc(name):
    try:
        App.getDocument(name).recompute()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: model refresh: %s\n" % error)


def _dependencies(doc):
    try:
        return [x for x in doc.getDependentDocuments() if x is not doc]
    except Exception:
        return []


_PARTS_OBS = []


def watch_parts():
    if not _PARTS_OBS:
        _PARTS_OBS.append(_PartsObserver())
        App.addDocumentObserver(_PARTS_OBS[0])


def _resync(doc, model, key):
    _SYNC.discard(key)
    try:
        if doc is None or model is None:
            return
        sync_parts(doc, model)
        doc.recompute()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: view model parts: %s\n" % error)


def splits(model):
    """True for a model drawn as its parts: an assembly or an assembly view model with more than one child."""
    kind = getattr(model, "TypeId", "")
    if kind != "Assembly::AssemblyObject" and getattr(model, "FwKind", "") != "FwDrawingViewModel":
        return False
    return len(_children(model)) > 1


def split_source(view, model):
    """view's XSource: model's parts (model: an assembly or an assembly view model)."""
    watch_parts()
    parts = sync_parts(view.Document, model)
    for o in parts:
        if o.Shape.isNull():
            o.touch()
    view.XSource = parts
    return parts


def model_centre(v):
    """The centre TechDraw centres a view on: the tight box of what the view shows, in the view's own axes
    (TechDraw's findCentroid; the plain BoundBox of a curved part is larger by its tolerance gap)."""
    box, shapes = None, []
    for o in source_shapes(v):
        try:
            b = o.Shape.BoundBox
            shapes.append(o.Shape)
        except Exception as _fw_err:
            _fw_log("drawviews.py:399", _fw_err)
            continue
        if box is None:
            box = App.BoundBox(b)
        else:
            box.add(b)
    if box is None:
        return V(0, 0, 0)
    try:
        if getattr(v, "TypeId", "") == "TechDraw::DrawViewSection":
            kept = _section_kept(v, shapes)      # TechDraw centres a section on the half it keeps
            if kept is not None:
                return _tight_centre(v, [kept])
        return _tight_centre(v, shapes)
    except Exception:
        return box.Center


SECTION_MESSAGE = ("Select Cutting Line and place it on a view.\n\nOptions: Use the Section View popup to add offsets to the Cutting Line.\nOR\nSelect Auto-start section view for immediate preview and placement of the section view.")



DETAIL_MESSAGE = ("Please sketch a circle to continue view creation. If you do not want a circular profile, please "
                  "create the profile before selecting the detail view command.")
SECTION_OK_MESSAGE = ("Select OK to place section view.\nOR\nContinue to modify cutting line by selecting another "
                      "offset from Section View popup.")

_KEPT = {}      # section name: (model change count, origin, normal, shapes, kept half)


def _section_kept(v, shapes):
    """The part of the model a section view keeps: what lies behind its cutting plane (opposite SectionNormal),
    the shape TechDraw projects and centres the section on (PC engine169: the whole model's centre put Model
    Items' points 2.5 mm off in an assembly section). None when it can't be made."""
    import Part
    try:
        n = V(v.SectionNormal)
        o = V(v.SectionOrigin)
    except Exception as _fw_err:
        _fw_log("drawviews.py:429", _fw_err)
        return None
    if n.Length < 1e-12:
        return None
    n.normalize()
    key = (v.Document.Name, v.Name)
    got = _KEPT.get(key)
    if got is not None and got[0] == SHAPE_GEN[0] and got[1].isEqual(o, 1e-9) and got[2].isEqual(n, 1e-12) \
            and len(got[3]) == len(shapes) and all(same_shape(a, b) for a, b in zip(got[3], shapes)):
        return got[4]
    box = App.BoundBox()
    for s in shapes:
        box.add(s.BoundBox)
    big = max(box.DiagonalLength, (box.Center - o).Length) * 4 + 100.0
    half = Part.makeBox(2 * big, 2 * big, big)
    half.Placement = App.Placement(o, App.Rotation(V(0, 0, 1), n)).multiply(
        App.Placement(V(-big, -big, 0), App.Rotation()))
    comp = Part.makeCompound([s.copy() for s in shapes]) if len(shapes) > 1 else shapes[0]
    kept = comp.cut(half)
    if kept.isNull() or not kept.Vertexes:
        kept = None
    if len(_KEPT) > 200:
        _KEPT.clear()
    _KEPT[key] = (SHAPE_GEN[0], o, n, list(shapes), kept)
    return kept


def _tight_centre(v, shapes):
    import Part
    d = V(v.Direction)
    x = V(getattr(v, "XDirection", V(1, 0, 0)))
    if d.Length < 1e-12:
        raise ValueError("no direction")
    d.normalize()
    if x.Length < 1e-12 or abs(abs(x.dot(d)) - 1) < 1e-9:
        raise ValueError("no x direction")
    x = x - d * x.dot(d)
    x.normalize()
    y = d.cross(x)
    m = App.Matrix(x.x, x.y, x.z, 0, y.x, y.y, y.z, 0, d.x, d.y, d.z, 0, 0, 0, 0, 1)   # global -> view axes
    comp = Part.makeCompound([s.copy() for s in shapes]) if len(shapes) > 1 else shapes[0].copy()
    comp.transformShape(m)
    c = comp.optimalBoundingBox(True, False).Center
    return x * c.x + y * c.y + d * c.z


_BOXES = {}


def view_box(v):
    """(xmin, ymin, xmax, ymax) of the view on the sheet, from its visible lines (TechDraw keeps them scaled).
    Kept for a moment for the same view at the same place and scale: one click of a sheet tool asks for every
    view's box several times, and reading a 50-part view's lines took 34 ms each time."""
    import time
    try:
        key = (v.Document.Name, v.Name)
        sig = (D.view_position(v), float(v.Scale), float(getattr(v, "Rotation", 0) or 0), tuple(v.Direction),
               bool(getattr(v, "CoarseView", False)))
    except Exception:
        key = sig = None
    now = time.perf_counter()
    hit = _BOXES.get(key) if key is not None else None
    if hit is not None and hit[0] == sig and now - hit[1] < 0.75:
        return hit[2]
    box = _view_box(v)
    if key is not None:
        if len(_BOXES) > 200:
            _BOXES.clear()
        _BOXES[key] = (sig, now, box)
    return box


def _view_box(v):
    x0, y0 = D.view_position(v)
    k = 1.0
    xs, ys = [], []
    try:
        for e in v.getVisibleEdges():
            for p in e.Vertexes:
                xs.append(p.Point.x)
                ys.append(p.Point.y)
            bb = e.BoundBox
            xs += [bb.XMin, bb.XMax]
            ys += [bb.YMin, bb.YMax]
    except Exception as _fw_err:
        _fw_log("drawviews.py:485", _fw_err)
    if not xs:
        return x0 - 5, y0 - 5, x0 + 5, y0 + 5
    return x0 + min(xs) * k, y0 + min(ys) * k, x0 + max(xs) * k, y0 + max(ys) * k


def view_at(page, p, margin=3.0):
    ""

    vs = views_at(page, p, margin)
    return vs[0] if vs else None


def views_at(page, p, margin=3.0):
    """Every part view whose box holds sheet point p: the one with an edge nearest the pointer (within 2 mm)
    first, then the smallest box."""
    hold = []
    for v in D.views_of(page):
        if v.TypeId == "TechDraw::DrawViewDetail":
            continue
        a, b, c, d = view_box(v)
        if a - margin <= p[0] <= c + margin and b - margin <= p[1] <= d + margin:
            hold.append(((c - a) * (d - b), v))
    if not hold:
        return []
    hold.sort(key=lambda t: t[0])
    out = [v for _, v in hold]
    if len(hold) > 1:
        near = [(_edge_gap(v, p), i, v) for i, (_, v) in enumerate(hold)]
        near = sorted((t for t in near if t[0] <= 2.0), key=lambda t: (round(t[0], 3), t[1]))
        first = [t[2] for t in near]
        out = first + [v for v in out if v not in first]
    return out


def _edge_gap(v, p):
    """How far (sheet mm) sheet point p is from view v's nearest drawn edge (1e9 when none)."""
    best = 1e9
    try:
        import Part
        k = view_scale(v) or 1.0
        g = to_geometry(v, p)
        pt = Part.Vertex(App.Vector(g[0], g[1], 0))
        for e in v.getVisibleEdges():
            best = min(best, e.distToShape(pt)[0] * k)
    except Exception as _fw_err:
        _fw_log("drawviews.py:531", _fw_err)
    return best


def focus_view(page, p, margin=3.0):
    """The view new sketch entities and annotations go into: none while Lock Sheet Focus is on (page
    FWLockSheetFocus), the locked view while Lock View Focus is on (page FWLockViewFocus), else the view under p."""
    if getattr(page, "FWLockSheetFocus", False):
        return None
    name = getattr(page, "FWLockViewFocus", "") or ""
    if name:
        v = page.Document.getObject(name)
        if v is not None and v.isDerivedFrom("TechDraw::DrawView"):
            return v
    return view_at(page, p, margin)


def to_geometry(v, p):
    """Sheet point -> the view's 2D geometry coordinates (unscaled, centred)."""
    x0, y0 = D.view_position(v)
    k = view_scale(v)
    return (p[0] - x0) / k, (p[1] - y0) / k


def to_model(v, p):
    """Sheet point -> the 3D point of the model it is over (on the plane through the model's centre)."""
    u, w = to_geometry(v, p)
    d, x, y = D.view_frame(v)
    return model_centre(v) + x * u + y * w


def _next_letter(text):
    ""
    s = (text or "A").upper()
    chars = list(s)
    i = len(chars) - 1
    while i >= 0:
        if chars[i] != "Z":
            chars[i] = chr(ord(chars[i]) + 1)
            while chars[i] in "IOQ":
                chars[i] = chr(ord(chars[i]) + 1)
            return "".join(chars)
        chars[i] = "A"
        i -= 1
    return "A" + "".join(chars)


def _drawing_option(text, default):
    """extapps83: Tools > Options > System Options > Drawings: that row's kept value."""
    try:
        from . import optionspages
        return optionspages.stored("Drawings", text, default)
    except Exception:
        return default


def _reuse_letters():
    return bool(_drawing_option("Reuse view letters from deleted auxiliary, detail, and section views", False))


def _detail_factor():
    try:
        return float(_drawing_option("Detail view scaling", 2.0) or 2.0)
    except (TypeError, ValueError):
        return 2.0


def take_label(page):
    """The sheet's Next view label, and moves it on."""
    cur = getattr(page, "FreeWorksNextViewLabel", "") if hasattr(page, "FreeWorksNextViewLabel") else ""
    cur = "A" if _reuse_letters() else (cur or "A")    # extapps83: Reuse view letters: the first free one
    used = {getattr(o, "SectionSymbol", "") for o in page.Document.Objects} | \
           {getattr(o, "Reference", "") for o in page.Document.Objects if o.TypeId == "TechDraw::DrawViewDetail"} | \
           {getattr(o, "SWAuxiliary", "") for o in page.Document.Objects} | \
           {getattr(o, "SWViewLetter", "") for o in page.Document.Objects}
    while cur in used:
        cur = _next_letter(cur)
    if not hasattr(page, "FreeWorksNextViewLabel"):
        page.addProperty("App::PropertyString", "FreeWorksNextViewLabel", "FreeCAD", "Next view label")
    page.FreeWorksNextViewLabel = _next_letter(cur)
    return cur


def _peek_label(page):
    """The label take_label would give next (nothing moves on)."""
    cur = (getattr(page, "FreeWorksNextViewLabel", "") if hasattr(page, "FreeWorksNextViewLabel") else "") or "A"
    used = {getattr(o, "SectionSymbol", "") for o in page.Document.Objects} | \
           {getattr(o, "Reference", "") for o in page.Document.Objects if o.TypeId == "TechDraw::DrawViewDetail"} | \
           {getattr(o, "SWAuxiliary", "") for o in page.Document.Objects}
    if _reuse_letters():
        cur = "A"                           # extapps83
    while cur in used:
        cur = _next_letter(cur)
    return cur


# --------------------------------------------------------------------------- Section View
def section_frame(base, kind, line, side, third_angle=True):
    """(direction to the viewer, XDirection, plane normal) of a section of base cut along line (two sheet points)
    and seen from side (a sheet offset from the line)."""
    d, x, y = D.view_frame(base)
    (ax, ay), (bx, by) = line
    if kind == "Vertical":
        ex, ey = 0.0, 1.0
    elif kind == "Horizontal":
        ex, ey = 1.0, 0.0
    else:
        L = math.hypot(bx - ax, by - ay)
        ex, ey = ((bx - ax) / L, (by - ay) / L) if L > 1e-9 else (0.0, 1.0)
    nx, ny = -ey, ex
    if nx * side[0] + ny * side[1] < 0:
        nx, ny = -nx, -ny
    # a section is seen from where it is placed, looking at the cutting line (its arrows point away from it), in

    nd = D._unit(x * nx + y * ny)
    along = D._unit(x * ex + y * ey)
    if kind == "Horizontal":
        xdir = D._unit(d.cross(nd))       # the section keeps the view's X, the side toward its viewer up (seen
                                          # from the other side it is turned left-right, never upside down)
    elif kind == "Vertical":
        xdir = D._unit(y.cross(nd))       # and its up along a vertical cut
    else:
        xdir = along                      # an auxiliary cut: X along the cutting line
    return nd, xdir, nd


def make_section(page, base, kind, line, at, label=None, flip=False, style=None, scale=None, side=None):
    """A section view of base, cut along line, placed at sheet point at; side (a sheet direction) sets which way
    it looks when it is not the side at is on (Auto Flip off)."""
    doc = page.Document
    from . import newdoc
    newdoc._serial_projections()
    bx, by = D.view_position(base)
    mid = ((line[0][0] + line[1][0]) / 2.0, (line[0][1] + line[1][1]) / 2.0)
    side = side or (at[0] - mid[0], at[1] - mid[1])
    nd, xdir, normal = section_frame(base, kind, line, side, D.third_angle(page))
    if flip:
        nd, normal = -nd, -normal
        xdir = -xdir                      # still upright, seen from the other side
    s = doc.addObject("TechDraw::DrawViewSection", "SectionView")
    page.addView(s)
    s.BaseView = base
    D.link_source(s, source_shapes(base))
    s.SectionOrigin = to_model(base, mid)
    s.SectionNormal = normal
    s.Direction = nd
    s.XDirection = xdir
    try:
        s.SectionDirection = "Aligned"
    except Exception as _fw_err:
        _fw_log("drawviews.py:657", _fw_err)
    label = label or take_label(page)
    s.SectionSymbol = label
    s.Label = "Section View %s-%s" % (label, label)
    s.ScaleType = "Custom"
    s.Scale = scale if scale is not None else view_scale(base)
    D.set_display_style(s, style or getattr(base, "SWDisplayStyle", "") or "Hidden Lines Removed")
    s.X, s.Y = at
    doc.recompute()
    hatch_soon(s)
    return s


HALF_SHAPES = ("Top Side Right", "Top Side Left", "Bottom Side Right", "Bottom Side Left",
               "Left Side Up", "Left Side Down", "Right Side Up", "Right Side Down")


def half_profile(base, centre, shape, margin=4.0):
    """The cutting line of a half section (sheet points): in from one side of the view to centre, then out."""
    a, b, c, d = view_box(base)
    cx, cy = centre
    top, bottom, left, right = d + margin, b - margin, a - margin, c + margin
    first, side = shape.split(" Side ")
    start = {"Top": (cx, top), "Bottom": (cx, bottom), "Left": (left, cy), "Right": (right, cy)}[first]
    if first in ("Top", "Bottom"):
        end = (right, cy) if side == "Right" else (left, cy)
    else:
        end = (cx, top) if side == "Up" else (cx, bottom)
    return [start, (cx, cy), end]


def offset_line(base, kind, line, offsets):
    """Section View Assist: the cutting line (Vertical, Horizontal or Auxiliary through line) across the whole of
    base, stepped by offsets: ("Single", start, to) moves the line from start on, to the side of to;
    ("Notch", start, end, to) moves it between start and end only; ("Arc", start, to) as Single, the step an arc
    (a quarter circle as wide as the step is deep). Sheet points; returns the polyline."""
    (ax, ay), (bx, by) = line
    if kind == "Vertical":
        ex, ey = 0.0, 1.0
    elif kind == "Horizontal":
        ex, ey = 1.0, 0.0
    else:
        L = math.hypot(bx - ax, by - ay)
        ex, ey = (bx - ax) / L, (by - ay) / L
    nx, ny = -ey, ex
    a, b, c, e = view_box(base)
    reach = math.hypot(c - a, e - b) + 10.0
    ox, oy = (ax + bx) / 2.0, (ay + by) / 2.0

    def t_of(q):
        return (q[0] - ox) * ex + (q[1] - oy) * ey

    def n_of(q):
        return (q[0] - ox) * nx + (q[1] - oy) * ny
    lo, hi = -reach, reach                    # the far ends of the line, past the view on both sides
    steps = []                                # (start t, normal offset, end t) of each offset
    arcs = []                                 # start t of the Arc Offsets
    for off in offsets:
        if off[0] in ("Single", "Arc"):
            steps.append((t_of(off[1]), n_of(off[2]), hi))
            if off[0] == "Arc":
                arcs.append(t_of(off[1]))
        else:
            t0, t1 = sorted((t_of(off[1]), t_of(off[2])))
            steps.append((t0, n_of(off[3]), t1))
    # the normal offset along the line: later offsets win where they overlap
    cuts = sorted({lo, hi} | {x for st in steps for x in st[::2]})

    def depth(t):
        d = 0.0
        for t0, n, t1 in steps:
            if t0 <= t < t1:
                d = n
        return d
    loc = []                                  # (t, n) along and across the line
    for i in range(len(cuts) - 1):
        t0, t1 = cuts[i], cuts[i + 1]
        n = depth((t0 + t1) / 2.0)
        for t in (t0, t1):
            if not loc or math.hypot(t - loc[-1][0], n - loc[-1][1]) > 1e-9:
                loc.append((t, n))
    for ta in arcs:                           # Arc Offset: the jog at ta becomes a quarter circle
        for i in range(len(loc) - 1):
            (t_a, n_a), (t_b, n_b) = loc[i], loc[i + 1]
            if abs(t_a - ta) < 1e-9 and abs(t_b - ta) < 1e-9 and abs(n_b - n_a) > 1e-9:
                r = abs(n_b - n_a)
                sg = 1.0 if n_b > n_a else -1.0
                arc = [(ta + r - r * math.cos(a), n_a + sg * r * math.sin(a))
                       for a in [math.pi / 2 * k / 8 for k in range(9)]]
                rest = [q for q in loc[i + 2:] if q[0] > ta + r + 1e-9]
                loc = loc[:i] + arc + rest
                break
    return [(ox + ex * t + nx * n, oy + ey * t + ny * n) for t, n in loc]


def settle_section(s):
    """A new complex section is cut once on its own before its base view is recomputed: TechDraw 1.1's base view
    draws the section line from the section's cut (its size is 0 until the section has run), throws
    BRepSweep_Translation, goes Invalid, and the section that depends on it is never recomputed."""
    doc = s.Document
    doc.recompute()
    base = getattr(s, "BaseView", None)
    if "Touched" not in s.State and (base is None or "Invalid" not in base.State):
        return
    try:
        s.recompute()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: section %s: %s\n" % (s.Label, error))
    s.touch()
    if base is not None:
        base.touch()
    doc.recompute()


def make_offset_section(page, base, kind, points, at, label=None, style=None, scale=None, side=None):
    """A section along a stepped cutting line (Section View Assist's Single / Notch Offset): TechDraw's complex
    section with the Offset strategy, seen square to the cutting line's legs from the side of at."""
    import Part
    doc = page.Document
    from . import newdoc
    newdoc._serial_projections()
    leg = (points[0], points[1])
    if kind == "Vertical":
        ex, ey = 0.0, 1.0
    elif kind == "Horizontal":
        ex, ey = 1.0, 0.0
    else:
        L = math.hypot(leg[1][0] - leg[0][0], leg[1][1] - leg[0][1])
        ex, ey = (leg[1][0] - leg[0][0]) / L, (leg[1][1] - leg[0][1]) / L
    cx = sum(q[0] for q in points) / len(points)
    cy = sum(q[1] for q in points) / len(points)
    side = side or (at[0] - cx, at[1] - cy)
    far = ((points[0][0], points[0][1]), (points[0][0] + ex, points[0][1] + ey))
    nd, xdir, normal = section_frame(base, kind, far, side, D.third_angle(page))
    wire = doc.addObject("Part::Feature", "SectionProfile")
    wire.Shape = Part.makePolygon([to_model(base, q) for q in points])
    try:
        wire.ViewObject.Visibility = False
    except Exception as _fw_err:
        _fw_log("drawviews.py:795", _fw_err)
    s = doc.addObject("TechDraw::DrawComplexSection", "SectionView")
    page.addView(s)
    label = label or take_label(page)
    s.SectionSymbol = label
    s.BaseView = base
    D.link_source(s, source_shapes(base))
    s.SectionNormal = normal
    s.Direction = nd
    s.XDirection = xdir
    s.SectionOrigin = to_model(base, points[0])
    s.ScaleType = "Custom"
    s.Scale = scale if scale is not None else view_scale(base)
    s.ProjectionStrategy = "Offset"
    s.X, s.Y = at
    s.CuttingToolWireObject = wire
    s.Label = "Section View %s-%s" % (label, label)
    s.addProperty("App::PropertyString", "SWSectionKind", "FreeCAD", "Aligned / Half Section shape")
    s.SWSectionKind = "%s Offset" % kind
    D.set_display_style(s, style or getattr(base, "SWDisplayStyle", "") or "Hidden Lines Removed")
    settle_section(s)
    return s


class SectionAssist(QtWidgets.QFrame):
    """The Section View Assist pop-up beside the cutting line: Single Offset, Notch Offset, Undo, OK, Cancel."""

    def __init__(self, panel, parent):
        super().__init__(parent)
        self.setObjectName("SWSectionAssistPopup")
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setAutoFillBackground(True)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        self.panel = panel
        for text, name, tip in (("Arc Offset", "SWSectionArcOffset", "Arc Offset"),
                                ("Single Offset", "SWSectionSingleOffset", "Single Offset"),
                                ("Notch Offset", "SWSectionNotchOffset", "Notch Offset"),
                                ("Undo", "SWSectionAssistUndo", "Undo"),
                                ("\u2714", "SWSectionAssistOK", "OK"),
                                ("\u2716", "SWSectionAssistCancel", "Cancel")):
            b = QtWidgets.QToolButton(self)
            b.setText(text)
            b.setObjectName(name)
            b.setToolTip(tip)
            b.setCheckable(name in ("SWSectionArcOffset", "SWSectionSingleOffset", "SWSectionNotchOffset"))
            b.clicked.connect(lambda *_, n=name: panel.assist(n))
            row.addWidget(b)
        self.adjustSize()


def make_complex_section(page, base, points, at, strategy="Offset", label=None, style=None, scale=None):
    """An aligned or half section of base along the cutting line through sheet points, placed at at. The cutting
    line is a wire in the drawing's file (TechDraw's complex section); an aligned view looks square to its last
    leg, a half section along its first leg."""
    import Part
    doc = page.Document
    from . import newdoc
    newdoc._serial_projections()
    leg = (points[-2], points[-1])
    mid = ((leg[0][0] + leg[1][0]) / 2.0, (leg[0][1] + leg[1][1]) / 2.0)
    side = (at[0] - mid[0], at[1] - mid[1])
    nd, xdir, normal = section_frame(base, "Auxiliary", leg, side, D.third_angle(page))
    if strategy == "Offset":
        # TechDraw cuts an offset profile only when its jog comes in from the viewer's side: the half section
        # looks along the jog (from where the cutting line starts) at the half it cuts
        nd = D._unit(to_model(base, points[0]) - to_model(base, points[1]))
        normal = nd
        xdir = D._unit(D.view_frame(base)[0].cross(nd))
    wire = doc.addObject("Part::Feature", "SectionProfile")
    wire.Shape = Part.makePolygon([to_model(base, q) for q in points])
    try:
        wire.ViewObject.Visibility = False
    except Exception as _fw_err:
        _fw_log("drawviews.py:870", _fw_err)
    s = doc.addObject("TechDraw::DrawComplexSection", "SectionView")
    page.addView(s)
    label = label or take_label(page)
    s.SectionSymbol = label                 # first: TechDraw throws when it is set after the cutting wire
    s.BaseView = base
    D.link_source(s, source_shapes(base))
    s.SectionNormal = normal
    s.Direction = nd
    s.XDirection = xdir
    s.SectionOrigin = to_model(base, points[1] if len(points) > 2 else mid)
    s.ScaleType = "Custom"
    s.Scale = scale if scale is not None else view_scale(base)
    s.ProjectionStrategy = strategy
    s.X, s.Y = at
    s.CuttingToolWireObject = wire
    s.Label = "Section View %s-%s" % (label, label)
    s.addProperty("App::PropertyString", "SWSectionKind", "FreeCAD", "Aligned / Half Section shape")
    D.set_display_style(s, style or getattr(base, "SWDisplayStyle", "") or "Hidden Lines Removed")
    settle_section(s)
    return s


def make_half_section(page, base, points, at, shape, label=None, style=None, scale=None):
    """A half section: a view looking along the cutting line's first leg (from where it comes in) with the material
    in front of the cut taken out on the side the line leaves by (TechDraw's own offset cut fails from two sides,
    so the cut is made on the model, as Broken-out Section does)."""
    doc = page.Document
    from . import newdoc
    newdoc._serial_projections()
    start, centre, end = (to_model(base, q) for q in points)
    nd = D._unit(start - centre)
    bd = D.view_frame(base)[0]
    xdir = D._unit(bd.cross(nd))
    ydir = nd.cross(xdir)
    L = 1e4
    side = (end - centre).dot(xdir)
    rect = (0.0, -L, L, L) if side > 0 else (-L, -L, 0.0, L)
    src = source_shapes(base)
    cut = drawing_shape(doc, src, "Half", centre, nd, xdir, ydir, rect, 0.0, label="Half Section of %s" % base.Label)
    label = label or take_label(page)
    v = D.new_view(page, [], nd, xdir, at, scale if scale is not None else view_scale(base),
                   style or getattr(base, "SWDisplayStyle", "") or "Hidden Lines Removed",
                   label="Section View %s-%s" % (label, label))
    v.XSource = []
    v.Source = [cut]
    v.addProperty("App::PropertyString", "SWSectionKind", "FreeCAD", "Aligned / Half Section shape")
    v.SWSectionKind = "Half Section " + shape
    v.addProperty("App::PropertyString", "SectionSymbol", "FreeCAD", "section label")
    v.SectionSymbol = label
    v.addProperty("App::PropertyVectorList", "SWCutLine", "FreeCAD", "the cutting line (model)")
    v.SWCutLine = [start, centre, end]
    D.set_parent(v, base)
    # the cutting line on the parent view, dash-dot as a section line
    try:
        from . import drawannot as DA
        k = view_scale(base)
        x0, y0 = D.view_position(base)
        pts = [(q[0] - x0, -(q[1] - y0)) for q in points]
        body = ('<polyline points="%s" fill="none" stroke="#000" stroke-width="0.5" stroke-dasharray="8 1.5 1.5 1.5"/>'
                % " ".join("%g,%g" % q for q in pts))
        for q, letter_at in ((pts[0], pts[0]), (pts[-1], pts[-1])):
            body += ('<text x="%g" y="%g" font-family="osifont, Arial" font-size="5" text-anchor="middle">%s</text>'
                     % (letter_at[0], letter_at[1] - 2, label))
        reach = max(max(abs(a), abs(b)) for a, b in pts) + 5
        line = DA.svg_symbol(page, "SectionLine", body, reach, (x0, y0), "Section Line %s-%s" % (label, label),
                             "SectionLine")
        line.addProperty("App::PropertyString", "SWSectionView", "FreeCAD", "its section view")
        line.SWSectionView = v.Name
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: half section line: %s\n" % error)
    doc.recompute()
    return v


def section_options(s, only_cut=False, scale_hatch=False, emphasize=False, hatch_scale=1.0, hatch_angle=0.0):
    ""
    for name, val in (("SWOnlyCutFaces", only_cut), ("SWScaleHatch", scale_hatch), ("SWEmphasizeOutline", emphasize)):
        if name not in s.PropertiesList:
            s.addProperty("App::PropertyBool", name, "FreeCAD", "Section View option")
        setattr(s, name, val)
    if hasattr(s, "TrimAfterCut"):
        s.TrimAfterCut = bool(only_cut)
    if hasattr(s, "HatchScale"):
        s.HatchScale = hatch_scale * (view_scale(s) if scale_hatch else 1.0)
        s.HatchRotation = hatch_angle
    try:
        vo = s.ViewObject
        if "SWBaseLineWidth" not in s.PropertiesList:
            s.addProperty("App::PropertyFloat", "SWBaseLineWidth", "FreeCAD", "line width before Emphasize outline")
            s.SWBaseLineWidth = float(vo.LineWidth)
        vo.LineWidth = s.SWBaseLineWidth * (1.8 if emphasize else 1.0)
    except Exception as _fw_err:
        _fw_log("drawviews.py:963", _fw_err)


def hide_shoulders(s, on=True):
    """Hide cutting line shoulders (an offset section): TechDraw's cutting line on the base view gives way to one
    drawn here with only its two end legs and letters; off: TechDraw's line again."""
    from . import drawannot as DA
    doc = s.Document
    page = next((o for o in s.InList if o.TypeId == "TechDraw::DrawPage"), None)
    base = s.BaseView
    if getattr(base, "SWDepthTwinOf", ""):
        base = doc.getObject(base.SWDepthTwinOf)
    if page is None or base is None:
        return None
    for o in list(page.Views):
        if getattr(o, "SWShouldersOf", "") == s.Name:
            doc.removeObject(o.Name)
    if "SWHideShoulders" not in s.PropertiesList:
        s.addProperty("App::PropertyBool", "SWHideShoulders", "FreeCAD", "Hide cutting line shoulders")
    s.SWHideShoulders = bool(on)
    pts = [(q.x, q.y) for q in (getattr(s, "SWCutPoints", None) or [])]
    try:
        base.ViewObject.ShowSectionLine = not on
    except Exception as _fw_err:
        _fw_log("drawviews.py:987", _fw_err)
    if not on or len(pts) < 2:
        doc.recompute()
        return None
    cx = sum(q[0] for q in pts) / len(pts)
    cy = sum(q[1] for q in pts) / len(pts)
    body = ""
    for a, b in ((pts[0], pts[1]), (pts[-1], pts[-2])):
        (x0, y0), (x1, y1) = a, b
        L = math.hypot(x1 - x0, y1 - y0) or 1.0
        x1, y1 = x0 + (x1 - x0) / L * min(L, 8.0), y0 + (y1 - y0) / L * min(L, 8.0)
        body += ('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="0.7"/>'
                 % (x0 - cx, -(y0 - cy), x1 - cx, -(y1 - cy)))
        body += ('<text x="%g" y="%g" font-family="osifont, Arial" font-size="5" text-anchor="middle">%s</text>'
                 % (x0 - cx, -(y0 - cy) - 2, s.SectionSymbol))
    reach = max(math.hypot(q[0] - cx, q[1] - cy) for q in pts) + 6
    line = DA.svg_symbol(page, "SectionLine", body, reach, (cx, cy), "Section Line %s-%s (no shoulders)" % (
        s.SectionSymbol, s.SectionSymbol), "SectionLine")
    line.addProperty("App::PropertyString", "SWShouldersOf", "FreeCAD", "its section view")
    line.SWShouldersOf = s.Name
    doc.recompute()
    return line


class SectionViewPanel(D._Panel):
    TITLE = "Section View"
    PIXMAP = "TechDraw_SectionView"
    GROUP_ORDER = ("Display State", "Display Style", "Scale", "Dimension Type", "Cosmetic Thread Display",
                   "Automatic View Update")
    KINDS = ("Vertical", "Horizontal", "Auxiliary", "Aligned")

    def build(self):
        self.say(SECTION_MESSAGE)
        self.tabs = QtWidgets.QTabBar(self.form)
        self.tabs.setObjectName("SWSectionTabs")
        self.tabs.addTab("Section")
        self.tabs.addTab("Half Section")
        self.lay.addWidget(self.tabs)
        hbox, hlay = D._group("Half Section", self.form)
        self.half = QtWidgets.QComboBox(hbox)
        self.half.setObjectName("SWHalfSectionShape")
        self.half.addItems(HALF_SHAPES)
        hlay.addWidget(self.half)
        self.lay.addWidget(hbox)
        self.half_box = hbox
        hbox.hide()
        self.points = []
        box, lay = D._group("Cutting Line", self.form)
        row = QtWidgets.QGridLayout()           # two by two: the four in one row made the pane wider than 300 px
        self.kind = QtWidgets.QButtonGroup(box)
        for n, k in enumerate(self.KINDS):
            b = QtWidgets.QToolButton(box)
            b.setText(k)
            b.setCheckable(True)
            b.setObjectName("SWSectionCut" + k)
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            self.kind.addButton(b, n)
            row.addWidget(b, n // 2, n % 2)
            if k == "Vertical":
                b.setChecked(True)
        lay.addLayout(row)
        self.cut_box = box
        self.tabs.currentChanged.connect(self.tab_changed)
        self.auto = QtWidgets.QCheckBox("Auto-start section view", box)
        self.auto.setObjectName("SWSectionAutoStart")
        self.auto.setChecked(False)
        lay.addWidget(self.auto)
        self.lay.addWidget(box)
        box, lay = D._group("Section Line", self.form)
        self.line_box = box
        self.flip = QtWidgets.QPushButton("Flip Direction", box)
        self.flip.setObjectName("SWSectionFlip")
        self.flip.clicked.connect(self.flip_direction)
        lay.addWidget(self.flip)
        self.auto_flip = QtWidgets.QCheckBox("Auto Flip", box)
        self.auto_flip.setObjectName("SWSectionAutoFlip")
        self.auto_flip.setToolTip("On: the section looks the way of the side you place it on. Off: it keeps the "
                                  "cutting line's direction wherever it goes.")
        lay.addWidget(self.auto_flip)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Label:", box))
        self.label = QtWidgets.QLineEdit(self._peek_label(), box)
        self.label.setObjectName("SWSectionLabel")
        self.label.editingFinished.connect(self.relabel)
        row.addWidget(self.label)
        lay.addLayout(row)
        D.label_font_row(self, lay, "SWSection")
        self.lay.addWidget(box)
        box, lay = D._group("Section View", self.form)
        self.partial = QtWidgets.QCheckBox("Partial section", box)
        self.partial.setObjectName("SWSectionPartial")
        self.partial.setToolTip("Live when the cutting line is shorter than the model: only what it crosses is cut.")
        self.partial.hide()               # drawings-land274: shown once the cutting line is short (never greyed)
        self.partial.toggled.connect(self.repartial)
        lay.addWidget(self.partial)
        self.only_cut = QtWidgets.QCheckBox("Slice section", box)
        self.only_cut.setObjectName("SWSectionOnlyCut")
        self.auto_hatch_main = QtWidgets.QCheckBox("Auto hatching", box)
        self.auto_hatch_main.setObjectName("SWSectionAutoHatching")
        self.randomize = QtWidgets.QCheckBox("Randomize scale", box)
        self.randomize.setObjectName("SWSectionRandomizeScale")
        self.randomize.hide()             # shown with Auto hatching on
        self.shoulders = QtWidgets.QCheckBox("Hide cutting line shoulders", box)
        self.shoulders.setObjectName("SWSectionHideShoulders")
        self.shoulders.hide()             # shown once the cutting line has offsets
        self.scale_hatch = QtWidgets.QCheckBox("Scale hatch pattern", box)
        self.scale_hatch.setObjectName("SWSectionScaleHatch")
        self.emphasize = QtWidgets.QCheckBox("Emphasize outline", box)
        self.emphasize.setObjectName("SWSectionEmphasize")
        lay.addWidget(self.only_cut)
        lay.addWidget(self.auto_hatch_main)
        lay.addWidget(self.randomize)
        lay.addWidget(self.shoulders)
        for w in (self.only_cut, self.scale_hatch, self.emphasize):
            w.toggled.connect(self.reoption)
        lay.addWidget(self.scale_hatch)
        lay.addWidget(self.emphasize)
        self.auto_hatch_main.toggled.connect(self.main_auto_hatch)
        self.randomize.toggled.connect(self.rerandom)
        self.shoulders.toggled.connect(self.reshoulders)
        self.lay.addWidget(box)
        box, lay = D._group("Surface Bodies", self.form)
        box.setCheckable(True)
        box.setChecked(True)
        box.setObjectName("SWSectionSurfaceBodiesGroup")
        self.surface_bodies = QtWidgets.QCheckBox("Display surface bodies", box)
        self.surface_bodies.setObjectName("SWSectionDisplaySurfaceBodies")
        self.surface_bodies.setChecked(True)
        self.surface_bodies.toggled.connect(self.resurfaces)
        lay.addWidget(self.surface_bodies)
        self.lay.addWidget(box)
        DL.fold(box)
        box, lay = D._group("Hatch", self.form)
        grid = QtWidgets.QGridLayout()
        self.hatch_scale = QtWidgets.QDoubleSpinBox(box)
        self.hatch_scale.setObjectName("SWSectionHatchScale")
        self.hatch_scale.setRange(0.01, 100)
        self.hatch_scale.setValue(1.0)
        self.hatch_angle = QtWidgets.QDoubleSpinBox(box)
        self.hatch_angle.setObjectName("SWSectionHatchAngle")
        self.hatch_angle.setRange(-360, 360)
        self.hatch_angle.setSuffix("\u00b0")
        grid.addWidget(QtWidgets.QLabel("Hatch pattern scale:", box), 0, 0)
        grid.addWidget(self.hatch_scale, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Hatch pattern angle:", box), 1, 0)
        grid.addWidget(self.hatch_angle, 1, 1)
        self.hatch_scale.valueChanged.connect(self.reoption)
        self.hatch_angle.valueChanged.connect(self.reoption)
        lay.addLayout(grid)
        self.lay.addWidget(box)
        box, lay = D._group("Section Depth", self.form)
        self.depth_on = QtWidgets.QCheckBox("Section depth", box)
        self.depth_on.setObjectName("SWSectionDepthOn")
        self.depth = QtWidgets.QDoubleSpinBox(box)
        self.depth.setObjectName("SWSectionDepth")
        self.depth.setRange(0.01, 100000)
        self.depth.setValue(10.0)
        self.depth.setSuffix("mm")
        DL.sets(self.depth_on, True, self.depth)        # a depth typed turns Section depth on
        self.depth_on.toggled.connect(self.redepth)
        self.depth.editingFinished.connect(self.redepth)
        lay.addWidget(self.depth_on)
        lay.addWidget(self.depth)
        self.lay.addWidget(box)

        box, lay = D._group("Section Scope", self.form)
        box.setObjectName("SWSectionScopeGroup")
        lay.addWidget(QtWidgets.QLabel("Excluded components:", box))
        self.scope_list = QtWidgets.QListWidget(box)
        self.scope_list.setObjectName("SWSectionScopeList")
        self.scope_list.setMaximumHeight(140)
        lay.addWidget(self.scope_list)
        self.scope_instances = QtWidgets.QCheckBox("Don't cut all instances", box)
        self.scope_instances.setObjectName("SWSectionScopeAllInstances")
        self.scope_instances.setToolTip("Checked: excluding a component excludes all its instances.")
        self.scope_fasteners = QtWidgets.QCheckBox("Exclude fasteners", box)
        self.scope_fasteners.setObjectName("SWSectionScopeFasteners")
        self.scope_show_fasteners = QtWidgets.QCheckBox("Show excluded fasteners", box)
        self.scope_show_fasteners.setObjectName("SWSectionScopeShowFasteners")
        self.scope_show_fasteners.setChecked(True)
        self.scope_auto_hatch = QtWidgets.QCheckBox("Auto hatching", box)
        self.scope_auto_hatch.setObjectName("SWSectionAutoHatch")
        self.scope_auto_hatch.setToolTip("Each component's cut gets its own hatch (45\u00b0, 135\u00b0, then "
                                         "closer lines).")
        self.scope_auto_hatch.setChecked(True)
        for w in (self.scope_instances, self.scope_fasteners, self.scope_show_fasteners, self.scope_auto_hatch):
            lay.addWidget(w)
        self.scope_box = box
        self.scope_comps = []
        self.scope_busy = False
        self.scope_list.itemChanged.connect(self.scope_item_changed)
        self.scope_fasteners.toggled.connect(self.scope_fasteners_changed)
        self.scope_instances.toggled.connect(lambda *_: self.rescope())
        self.scope_show_fasteners.toggled.connect(lambda *_: self.rescope())
        self.scope_auto_hatch.toggled.connect(self.re_auto_hatch)
        self.scope_auto_hatch.toggled.connect(lambda on: self._sync_hatch(on))
        self.lay.addWidget(box)
        box.hide()

        box, lay = D._group("Excluded Ribs", self.form)
        box.setObjectName("SWSectionRibGroup")
        lay.addWidget(QtWidgets.QLabel("Rib features not cut:", box))
        self.rib_list = QtWidgets.QListWidget(box)
        self.rib_list.setObjectName("SWSectionRibList")
        self.rib_list.setMaximumHeight(120)
        lay.addWidget(self.rib_list)
        self.rib_list.itemChanged.connect(lambda *_: self.rerib())
        self.rib_box = box
        self.lay.addWidget(box)
        box.hide()
        D._import_group(self, "Import annotation from", "SWSection")
        box, lay = D._group("Display Style", self.form)
        self.style = D.StyleButtons(box, "SWDrawDisplayStyle", "Hidden Lines Removed")
        self.style.currentTextChanged.connect(self.restyle)
        lay.addWidget(self.style)
        self.lay.addWidget(box)
        D.extra_groups(self, "Projected", "Draft quality", lay, "SWSection")
        DL.sets(self.parent_style, False, *self.style.buttons.values())   # a style clicked turns Use parent style off
        self.parent_style.toggled.connect(self.parent_style_changed)

        box, lay = D._group("Scale", self.form)
        self.use_parent = QtWidgets.QRadioButton("Use parent scale", box)
        self.use_parent.setObjectName("SWSectionParentScale")
        self.use_parent.setChecked(True)
        self.use_sheet = QtWidgets.QRadioButton("Use sheet scale", box)
        self.use_sheet.setObjectName("SWSectionSheetScale")
        self.use_custom = QtWidgets.QRadioButton("Use custom scale", box)
        self.use_custom.setObjectName("SWSectionCustomScale")
        self.scale_combo = QtWidgets.QComboBox(box)
        self.scale_combo.setObjectName("SWSectionScaleCombo")
        self.scale_combo.setEditable(True)
        self.scale_combo.addItems(D.SCALES)
        self.scale_combo.setCurrentText(D.scale_text(1.0))
        combo = self.scale_combo          # live, as the other view PMs: a scale picked makes it the custom scale
        combo.activated.connect(lambda *_: QtWidgets.QApplication.focusWidget() in (combo, combo.lineEdit(),
                                                                                     combo.view())
                                and self.use_custom.setChecked(True))
        combo.lineEdit().textEdited.connect(lambda *_: self.use_custom.setChecked(True))
        combo.currentTextChanged.connect(lambda *_: self.use_custom.isChecked() and self.rescale())
        for w in (self.use_parent, self.use_sheet, self.use_custom):
            w.toggled.connect(lambda on: on and self.rescale())
        for w in (self.use_parent, self.use_sheet, self.use_custom, self.scale_combo):
            lay.addWidget(w)
        self.lay.addWidget(box)
        self._after.append(lambda: self.set_page(1))
        self.base = None
        self.line = None
        self.first = None
        self.section = None
        self.offsets = []
        self.offset_mode = None
        self.offset_clicks = []
        self.popup = None

    # ---- Section View Assist
    def show_assist(self, p):
        gv = D.page_view(self.page)
        if gv is None:
            return
        if self.popup is None:
            self.popup = SectionAssist(self, gv.viewport())
        vp = gv.mapFromScene(D.to_scene(p[0], p[1]))
        r = gv.viewport().rect()
        x = min(max(4, vp.x() + 20), r.width() - self.popup.width() - 4)
        y = min(max(4, vp.y() - self.popup.height() - 20), r.height() - self.popup.height() - 4)
        self.popup.move(x, y)
        self.popup.show()
        self.popup.raise_()

    def hide_assist(self):
        if self.popup is not None:
            self.popup.hide()

    def assist(self, name):
        modes = {"SWSectionArcOffset": "Arc", "SWSectionSingleOffset": "Single", "SWSectionNotchOffset": "Notch"}
        if name in modes:
            mode = modes[name]
            self.offset_mode = None if self.offset_mode == mode else mode
            self.offset_clicks = []
            for n, m in modes.items():
                b = self.popup.findChild(QtWidgets.QToolButton, n)
                b.setChecked(self.offset_mode == m)
            self.say({"Single": "Single Offset: click where the step starts on the cutting line, then where the line "
                                "goes.",
                      "Arc": "Arc Offset: click where the arc starts on the cutting line, then where the line goes.",
                      "Notch": "Notch Offset: click the notch's start and end on the cutting line, then its depth.",
                      None: SECTION_OK_MESSAGE}[self.offset_mode])
        elif name == "SWSectionAssistUndo":
            if self.offsets:
                self.offsets.pop()
            self.offset_clicks = []
            self.say("Offset undone. %d offset(s) left." % len(self.offsets))
        elif name == "SWSectionAssistOK":
            self.placing()
        elif name == "SWSectionAssistCancel":
            self.hide_assist()
            self.line, self.offsets, self.offset_mode, self.offset_clicks = None, [], None, []
            self.set_page(1)
            self.say("Cutting line canceled. Click in a view to place it again.")

    def _assist_click(self, p):
        """A click while an offset is being added; True when it was used."""
        if self.offset_mode is None or not isinstance(self.line, tuple):
            return False
        self.offset_clicks.append(p)
        need = 3 if self.offset_mode == "Notch" else 2
        if len(self.offset_clicks) < need:
            self.say("Click %d of %d for the %s Offset." % (len(self.offset_clicks) + 1, need, self.offset_mode))
            return True
        self.offsets.append(tuple([self.offset_mode] + self.offset_clicks))
        self.offset_clicks = []
        self.assist({"Arc": "SWSectionArcOffset", "Single": "SWSectionSingleOffset"}.get(self.offset_mode,
                                                                                       "SWSectionNotchOffset"))
        self.say(SECTION_OK_MESSAGE)
        return True

    def tab_changed(self, n):
        half = n == 1
        self.half_box.setVisible(half)
        for b in self.kind.buttons():
            DL.row(b, not half)
        self.say("Click the center of the half section in a view." if half else
                 SECTION_MESSAGE)

    def _peek_label(self):
        cur = getattr(self.page, "FreeWorksNextViewLabel", "") if hasattr(self.page, "FreeWorksNextViewLabel") else ""
        return cur or "A"

    def set_page(self, n):
        ""

        self.page_no = n
        first = n == 1
        keep = ("SWDrawGroup_Message", "SWSectionScopeGroup", "SWSectionRibGroup", "SWDrawGroup_HalfSection",
                "SWDrawGroup_CuttingLine")
        for box in self.form.findChildren(QtWidgets.QGroupBox):
            if box.parent() is self.form and box.objectName() not in keep:
                box.setVisible(not first)
        self.tabs.setVisible(first)
        self.cut_box.setVisible(first)
        self.half_box.setVisible(first and self.tabs.currentIndex() == 1)
        self.line_box.setTitle("Section Line" if first else "Cutting Line")
        if not first:
            label = self.label.text().strip() or "A"
            self.form.setWindowTitle("Section View %s-%s" % (label, label))

    def placing(self):
        """The cutting line is done: page 2, the section view follows the next click."""
        self.hide_assist()
        self.offset_mode = None
        self.set_page(2)
        self.say("Click in the graphics area to place the new view.")

    def parent_scale(self):
        return view_scale(self.base) if self.base is not None else 1.0

    def rescale(self):
        s = self.section
        if s is None or self.base is None:
            return
        mode, factor = D.view_scale_choice(self, self.base)
        if mode == "Parent":
            D.follow_parent_scale(s, self.base)
        elif mode == "Sheet":
            s.ScaleType = "Page"
            D.set_scale_mode(s, "Sheet")
        else:
            s.ScaleType = "Custom"
            s.Scale = factor
            D.set_scale_mode(s, "Custom")
        self.doc.recompute()

    def _style(self):
        if self.parent_style.isChecked() and self.base is not None:
            return getattr(self.base, "SWDisplayStyle", "") or self.style.currentText()
        return self.style.currentText()

    def kind_name(self):
        b = self.kind.checkedButton()
        return b.text() if b is not None else "Vertical"

    def sheet_click(self, p):
        if self.section is not None:
            return False
        if self._assist_click(p):
            return True
        if self.line is None and (self.tabs.currentIndex() == 1 or self.kind_name() == "Aligned"):
            if not self.points:
                v = view_at(self.page, p)
                if v is None:
                    self.say("Click inside a drawing view to place the cutting line.")
                    return True
                self.base = v
            self.points.append(p)
            if self.tabs.currentIndex() == 1:
                self.line = half_profile(self.base, p, self.half.currentText())
            elif len(self.points) == 1:
                self.say("Click the end of the first cutting line.")
                return True
            elif len(self.points) == 2:
                self.say("Click the end of the second cutting line.")
                return True
            else:
                c, p1, p2 = self.points
                self.line = [p1, c, p2]
            self.points = []
            self.placing()             # no offsets for a half / aligned line: no pop-up to wait on
            return True
        if self.line is None:
            if self.first is None:
                v = view_at(self.page, p)
                if v is None:
                    self.say("Click inside a drawing view to place the cutting line.")
                    return True
                self.base = v
                if self.kind_name() == "Auxiliary":
                    self.first = p
                    self.say("Click to set the cutting line's angle.")
                    return True
                if self.kind_name() == "Vertical":
                    self.line = ((p[0], p[1] - 1.0), (p[0], p[1] + 1.0))
                else:
                    self.line = ((p[0] - 1.0, p[1]), (p[0] + 1.0, p[1]))
            else:
                self.line = (self.first, p)
                self.first = None
            if self.auto.isChecked():
                self.placing()
                return True
            self.show_assist(p)
            self.say(SECTION_OK_MESSAGE)
            return True
        self.hide_assist()
        if getattr(self, "page_no", 2) == 1:
            self.set_page(2)
        label = self.label.text().strip() or None
        if label is None or label == self._peek_label():
            label = take_label(self.page)
        if isinstance(self.line, list) and self.tabs.currentIndex() == 1:
            self.section = make_half_section(self.page, self.base, self.line, p, self.half.currentText(), label,
                                             style=self._style())
        elif isinstance(self.line, list):
            self.section = make_complex_section(self.page, self.base, self.line, p, "Aligned", label,
                                                style=self._style())
            self.section.SWSectionKind = "Aligned"
        elif self.offsets:
            pts = offset_line(self.base, self.kind_name(), self.line, self.offsets)
            self.section = make_offset_section(self.page, self.base, self.kind_name(), pts, p, label,
                                               style=self._style(), side=self.fixed_side())
            self.section.addProperty("App::PropertyVectorList", "SWCutPoints", "FreeCAD", "cutting line (sheet)")
            self.section.SWCutPoints = [V(q[0], q[1], 0) for q in pts]
        else:
            self.section = make_section(self.page, self.base, self.kind_name(), self.line, p, label,
                                        style=self._style(), side=self.fixed_side())
        self.label.setText(label)
        self.form.setWindowTitle("Section View %s-%s" % (label, label))
        self.made.append(self.section)
        self._after_place()
        if not self.use_parent.isChecked():
            self.rescale()
        if self.section.TypeId != "TechDraw::DrawViewPart":
            self.reoption()
            if self.depth_on.isChecked():
                self.redepth()
        self.fill_scope()
        self.fill_ribs()
        self.say("Section View %s-%s placed. Flip Direction or change the label, then OK." % (label, label))
        return True

    # ---- Section Scope
    def fill_scope(self):
        s = self.section
        if s is None or s.TypeId == "TechDraw::DrawViewPart" or self.base is None:
            return
        comps = components(source_shapes(self.base))
        if len(comps) < 2:
            return
        self.scope_comps = comps
        self.scope_busy = True
        self.scope_list.clear()
        for c in comps:
            it = QtWidgets.QListWidgetItem(c["label"], self.scope_list)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Unchecked)
            it.setData(QtCore.Qt.UserRole, c["name"])
        self.scope_busy = False
        self.scope_box.show()
        self.re_auto_hatch(self.scope_auto_hatch.isChecked())

    def fill_ribs(self):
        s = self.section
        if s is None or s.TypeId == "TechDraw::DrawViewPart" or self.base is None:
            return
        ribs = ribs_of(source_shapes(self.base))
        if not ribs:
            return
        self.rib_list.blockSignals(True)
        self.rib_list.clear()
        for r in ribs:
            it = QtWidgets.QListWidgetItem(r.Label, self.rib_list)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Unchecked)
            it.setData(QtCore.Qt.UserRole, r.Name)
        self.rib_list.blockSignals(False)
        self.rib_box.show()
        self.rerib()

    def rerib(self):
        if self.section is None:
            return
        names = [self.rib_list.item(i).data(QtCore.Qt.UserRole) for i in range(self.rib_list.count())
                 if self.rib_list.item(i).checkState() == QtCore.Qt.Checked]
        try:
            set_excluded_ribs(self.section, names)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: excluded ribs: %s\n" % error)

    def re_auto_hatch(self, on):
        if self.section is not None and self.scope_comps:
            set_auto_hatch(self.section, on)

    def scope_item_changed(self, item):
        if self.scope_busy:
            return
        if self.scope_instances.isChecked():
            # all instances of the part go together
            n = item.data(QtCore.Qt.UserRole)
            part = next((c["part"] for c in self.scope_comps if c["name"] == n), None)
            self.scope_busy = True
            for i in range(self.scope_list.count()):
                other = self.scope_list.item(i)
                c = self.scope_comps[i]
                if other is not item and c["part"] == part:
                    other.setCheckState(item.checkState())
            self.scope_busy = False
        self.rescope()

    def scope_fasteners_changed(self, on):
        self.scope_busy = True
        for i in range(self.scope_list.count()):
            if is_fastener(self.scope_comps[i]):
                self.scope_list.item(i).setCheckState(QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)
        self.scope_busy = False
        self.rescope()

    def scope_names(self):
        return [self.scope_list.item(i).data(QtCore.Qt.UserRole) for i in range(self.scope_list.count())
                if self.scope_list.item(i).checkState() == QtCore.Qt.Checked]

    def rescope(self):
        if self.section is None or self.scope_busy or not self.scope_comps:
            return
        names = self.scope_names()
        hidden = [] if self.scope_show_fasteners.isChecked() else \
            [c["name"] for c in self.scope_comps if c["name"] in names and is_fastener(c)]
        set_section_scope(self.section, names, hidden)

    def fixed_side(self):
        """Auto Flip off: the cutting line's own direction (to the right of the line as drawn: Vertical, drawn
        upwards, puts the view to its right, Horizontal below), wherever the view is put. On: None (the side
        clicked)."""
        if self.auto_flip.isChecked() or not isinstance(self.line, tuple):
            return None
        kind = self.kind_name()
        if kind == "Vertical":
            return (1.0, 0.0)
        if kind == "Horizontal":
            return (0.0, -1.0)
        (ax, ay), (bx, by) = self.line
        return (by - ay, -(bx - ax))

    def short_line(self):
        """(u0, u1, model axis) of an Auxiliary cutting line that does not cross the whole view, else None."""
        if self.kind_name() != "Auxiliary" or not isinstance(self.line, tuple) or self.offsets or self.base is None:
            return None
        (ax, ay), (bx, by) = self.line
        L = math.hypot(bx - ax, by - ay)
        if L < 1e-6:
            return None
        ex, ey = (bx - ax) / L, (by - ay) / L
        a, b, c, e = view_box(self.base)
        mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
        ts = [(x - mx) * ex + (y - my) * ey for x in (a, c) for y in (b, e)]
        if -L / 2 <= min(ts) + 1e-6 and max(ts) - 1e-6 <= L / 2:
            return None                           # it crosses the whole view
        k = view_scale(self.base)
        axis = D._unit(to_model(self.base, (mx + ex, my + ey)) - to_model(self.base, (mx, my)))
        return (-L / 2 / k, L / 2 / k, axis)

    def _after_place(self):
        s = self.section
        DL.row(self.partial, self.short_line() is not None and s.TypeId == "TechDraw::DrawViewSection")
        DL.row(self.shoulders, bool(self.offsets))
        DL.row(self.randomize, self.auto_hatch_main.isChecked())
        self.annotation_views.clear()
        it = QtWidgets.QListWidgetItem(D.annotation_view_name(self.base), self.annotation_views)
        it.setCheckState(QtCore.Qt.Checked)
        if self.auto_hatch_main.isChecked() and not getattr(s, "SWAutoHatch", False):
            self.main_auto_hatch(True)
        if not self.surface_bodies.isChecked():
            self.resurfaces(False)

    def _sync_hatch(self, on):
        self.auto_hatch_main.blockSignals(True)
        self.auto_hatch_main.setChecked(on)
        self.auto_hatch_main.blockSignals(False)
        DL.row(self.randomize, on)

    def main_auto_hatch(self, on):
        """Section View > Auto hatching (the same as Section Scope's): each cut body its own hatch."""
        DL.row(self.randomize, on)
        self.scope_auto_hatch.blockSignals(True)
        self.scope_auto_hatch.setChecked(on)
        self.scope_auto_hatch.blockSignals(False)
        if self.section is not None and self.section.TypeId != "TechDraw::DrawViewPart":
            self.re_auto_hatch(on)

    def rerandom(self, on):
        s = self.section
        if s is None:
            return
        if "SWAutoHatchRandom" not in s.PropertiesList:
            s.addProperty("App::PropertyBool", "SWAutoHatchRandom", "FreeCAD", "Auto hatching: Randomize scale")
        s.SWAutoHatchRandom = bool(on)
        auto_hatch(s)
        self.doc.recompute()

    def repartial(self, on):
        s = self.section
        span = self.short_line()
        if s is None or span is None:
            return
        for name, kind in (("SWPartialSection", "App::PropertyBool"), ("SWPartialSpan", "App::PropertyFloatList"),
                           ("SWPartialAxis", "App::PropertyVector")):
            if name not in s.PropertiesList:
                s.addProperty(kind, name, "FreeCAD", "Partial section")
        s.SWPartialSection = bool(on)
        s.SWPartialSpan = [span[0], span[1]]
        s.SWPartialAxis = span[2]
        _rebuild_twin(s)

    def resurfaces(self, on):
        s = self.section
        if s is None or s.TypeId == "TechDraw::DrawViewPart":
            return
        if "SWDisplaySurfaceBodies" not in s.PropertiesList:
            s.addProperty("App::PropertyBool", "SWDisplaySurfaceBodies", "FreeCAD", "Section: Display surface bodies")
        s.SWDisplaySurfaceBodies = bool(on)
        _rebuild_twin(s)

    def reshoulders(self, on):
        if self.section is not None:
            hide_shoulders(self.section, on)

    def flip_direction(self):
        s = self.section
        if s is None:
            return
        want = -V(s.Direction)
        s.SectionNormal = -V(s.SectionNormal)
        if (V(s.Direction) - want).Length > 1e-9:     # TechDraw turns the view with the normal; else we do
            s.Direction = want
        s.XDirection = -V(s.XDirection)          # seen from the other side, still upright
        self.doc.recompute()
        if getattr(s, "SWSectionDepth", 0.0) or section_scope(s)[0] or getattr(s, "SWAutoHatch", False):
            _rebuild_twin(s)

    def relabel(self):
        s = self.section
        t = self.label.text().strip()
        if s is None or not t:
            return
        s.SectionSymbol = t
        s.Label = "Section View %s-%s" % (t, t)
        self.doc.recompute()
        if getattr(s, "SWSectionDepth", 0.0) or section_scope(s)[0] or getattr(s, "SWAutoHatch", False):
            _rebuild_twin(s)

    def reoption(self, *_):
        s = self.section
        if s is not None:
            section_options(s, self.only_cut.isChecked(), self.scale_hatch.isChecked(), self.emphasize.isChecked(),
                            self.hatch_scale.value(), self.hatch_angle.value())
            self.doc.recompute()

    def redepth(self, *_):
        if self.section is not None and self.section.TypeId != "TechDraw::DrawViewPart":
            set_section_depth(self.section, self.depth.value() if self.depth_on.isChecked() else 0.0)

    def restyle(self, style):
        if self.section is not None:
            D.set_display_style(self.section, style)
            self.doc.recompute()

    def parent_style_changed(self, on):
        if on and self.base is not None:
            self.style.setCurrentText(getattr(self.base, "SWDisplayStyle", "") or "Hidden Lines Removed")

    def drop_assist(self):
        if self.popup is not None:
            self.popup.hide()
            self.popup.setObjectName("")
            self.popup.deleteLater()
            self.popup = None

    def reject(self):
        self.drop_assist()
        return D._Panel.reject(self)

    def finish(self):
        self.drop_assist()
        if self.section is not None:
            if self.parent_style.isChecked() and self.base is not None:
                D.set_display_style(self.section, getattr(self.base, "SWDisplayStyle", "") or self.style.currentText())
            D.apply_extra(self, self.section)
            if self.base is not None:
                D.set_parent(self.section, self.base)
                if self.use_parent.isChecked():
                    D.set_scale_mode(self.section, "Parent")
            D.apply_label_font(self, self.section)
            D.run_import(self, self.section)


# --------------------------------------------------------------------------- Detail View
def make_detail(page, base, centre, radius, at, label=None, scale=None, outline=False, pin=False):
    """A detail view of base around sheet point centre with sheet radius radius, placed at at."""
    doc = page.Document
    from . import newdoc
    newdoc._serial_projections()
    k = view_scale(base)
    u, w = to_geometry(base, centre)
    dt = doc.addObject("TechDraw::DrawViewDetail", "DetailView")
    page.addView(dt)
    dt.BaseView = base
    D.link_source(dt, source_shapes(base))
    dt.Direction = base.Direction
    dt.XDirection = base.XDirection
    dt.AnchorPoint = V(u, w, 0)
    dt.Radius = radius / k
    label = label or take_label(page)
    dt.Reference = label
    dt.ScaleType = "Custom"
    dt.Scale = scale if scale is not None else _detail_factor() * k      # extapps83: Detail view scaling
    try:
        dt.ShowMatting = outline
    except Exception as _fw_err:
        _fw_log("drawviews.py:1657", _fw_err)
    dt.LockPosition = pin
    a, b = _ratio(float(dt.Scale))
    dt.Label = "Detail View %s (%s : %s)" % (label, a, b)
    dt.X, dt.Y = at
    D.set_display_style(dt, getattr(base, "SWDisplayStyle", "") or "Hidden Lines Removed")
    doc.recompute()
    if getattr(base, "SWAutoHatch", False):
        try:
            auto_hatch(base)                    # the detail gets the section's hatch (drawings-land281)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: detail hatch: %s\n" % error)
    return dt


def _ratio(scale):
    from fractions import Fraction
    f = Fraction(scale).limit_denominator(1000)
    return f.numerator, f.denominator


DETAIL_STYLES = ("Per Standard", "Broken", "With Leader", "No Leader", "Connected")


def detail_style(page, dt, style):
    ""

    from . import drawannot as DA
    if "SWDetailStyle" not in dt.PropertiesList:
        dt.addProperty("App::PropertyString", "SWDetailStyle", "FreeCAD", "detail circle style")
    dt.SWDetailStyle = style
    try:
        dt.ViewObject.HighlightLineStyle = "Break1" if style == "Broken" else "Center"
    except Exception as _fw_err:
        _fw_log("drawviews.py:1686", _fw_err)
    for o in list(page.Views):
        if getattr(o, "SWDetailLeaderOf", "") == dt.Name:
            page.Document.removeObject(o.Name)
    if style not in ("With Leader", "Connected"):
        return
    base = dt.BaseView
    bx, by = D.view_position(base)
    k = view_scale(base)
    cx, cy = bx + dt.AnchorPoint.x * k, by + dt.AnchorPoint.y * k
    r = float(dt.Radius) * k
    if style == "Connected":
        tx, ty = D.view_position(dt)
    else:
        tx, ty = cx + r * 1.6, cy + r * 1.6
    L = math.hypot(tx - cx, ty - cy)
    if L <= r:
        return
    sx, sy = cx + (tx - cx) * r / L, cy + (ty - cy) * r / L
    mx, my = (sx + tx) / 2, (sy + ty) / 2
    body = '<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="0.25"/>' % (
        sx - mx, -(sy - my), tx - mx, -(ty - my))
    s = DA.svg_symbol(page, "DetailLeader", body, L / 2, (mx, my), "Detail Leader %s" % dt.Reference, "DetailLeader")
    s.addProperty("App::PropertyString", "SWDetailLeaderOf", "FreeCAD", "its detail view")
    s.SWDetailLeaderOf = dt.Name


def detail_profile(page, dt, points):
    """The detail's Profile on its parent: the closed profile (sheet points) drawn in place of TechDraw's circle."""
    from . import drawannot as DA
    if "SWDetailProfile" not in dt.PropertiesList:
        dt.addProperty("App::PropertyString", "SWDetailProfile", "FreeCAD", "detail profile corners (sheet)")
    dt.SWDetailProfile = ";".join("%g,%g" % (q[0], q[1]) for q in points)
    try:
        vo = dt.ViewObject
        for name in ("HighlightLineStyle",):
            if hasattr(vo, name):
                try:
                    setattr(vo, name, "NoLine")
                except Exception:
                    setattr(vo, name, 0)
    except Exception as _fw_err:
        _fw_log("drawviews.py:1728", _fw_err)
    cx = sum(q[0] for q in points) / len(points)
    cy = sum(q[1] for q in points) / len(points)
    rel = ["%g,%g" % (q[0] - cx, -(q[1] - cy)) for q in points]
    body = ('<polygon points="%s" fill="none" stroke="#000" stroke-width="0.35" stroke-dasharray="6 1.2 1.2 1.2"/>'
            % " ".join(rel))
    reach = max(math.hypot(q[0] - cx, q[1] - cy) for q in points) + 1
    s = DA.svg_symbol(page, "DetailProfile", body, reach, (cx, cy), "Detail Profile %s" % dt.Reference,
                      "DetailProfile")
    s.addProperty("App::PropertyString", "SWDetailProfileOf", "FreeCAD", "its detail view")
    s.SWDetailProfileOf = dt.Name
    return s


def detail_jagged(page, dt, intensity):
    ""

    from . import drawannot as DA
    for o in list(page.Views):
        if getattr(o, "SWDetailJaggedOf", "") == dt.Name:
            page.Document.removeObject(o.Name)
    if "SWDetailJagged" not in dt.PropertiesList:
        dt.addProperty("App::PropertyInteger", "SWDetailJagged", "FreeCAD", "jagged outline intensity (0 off)")
    dt.SWDetailJagged = int(intensity)
    if not intensity:
        return None
    r = float(dt.Radius) * view_scale(dt)
    n = max(16, int(2 * math.pi * r / 2.5))
    depth = 0.4 * intensity
    pts = []
    for i in range(2 * n):
        a = math.pi * i / n
        rr = r + (depth if i % 2 else 0.0)
        pts.append("%g,%g" % (rr * math.cos(a), rr * math.sin(a)))
    body = '<polygon points="%s" fill="none" stroke="#000" stroke-width="0.35"/>' % " ".join(pts)
    s = DA.svg_symbol(page, "DetailJagged", body, r + depth, D.view_position(dt),
                      "Jagged Outline %s" % dt.Reference, "DetailJagged")
    s.addProperty("App::PropertyString", "SWDetailJaggedOf", "FreeCAD", "its detail view")
    s.SWDetailJaggedOf = dt.Name
    return s


# --------------------------------------------------------------------------- Detail: Display graphic bodies
GRAPHIC_FACETS = 3000            # meshes over this are decimated first (speed)


def graphic_meshes(base):
    """The visible graphic (mesh) bodies of the documents base shows."""
    docs = []
    for o in source_shapes(base):
        d = getattr(getattr(o, "LinkedObject", o), "Document", None) or o.Document
        for dd in (o.Document, d):
            if dd not in docs:
                docs.append(dd)
    out = []
    for d in docs:
        for m in d.Objects:
            if m.isDerivedFrom("Mesh::Feature"):
                try:
                    if not m.ViewObject.Visibility:
                        continue
                except Exception as _fw_err:
                    _fw_log("drawviews.py:1790", _fw_err)
                out.append(m)
    return out


def _mesh_body(m):
    """A hidden Part copy of mesh m (its flat regions merged) that TechDraw can project; made once, kept."""
    import Part
    d = m.Document
    for o in d.Objects:
        if getattr(o, "SWGraphicBodyOf", "") == m.Name:
            return o
    mesh = m.Mesh.copy()
    if mesh.CountFacets > GRAPHIC_FACETS:
        try:
            mesh.decimate(0.5, 1.0 - float(GRAPHIC_FACETS) / mesh.CountFacets)
        except Exception as _fw_err:
            _fw_log("drawviews.py:1807", _fw_err)
    sh = Part.Shape()
    sh.makeShapeFromMesh(mesh.Topology, 0.05)
    try:
        sh = Part.makeShell(sh.Faces).removeSplitter()
    except Exception as _fw_err:
        _fw_log("drawviews.py:1813", _fw_err)
    o = d.addObject("Part::Feature", "GraphicBody")
    o.Shape = sh
    o.Placement = m.Placement
    o.Label = m.Label + " (graphic body)"
    o.addProperty("App::PropertyString", "SWGraphicBodyOf", "FreeCAD", "the mesh it is drawn from")
    o.SWGraphicBodyOf = m.Name
    try:
        o.ViewObject.Visibility = False
    except Exception as _fw_err:
        _fw_log("drawviews.py:1823", _fw_err)
    return o


def graphic_bodies(page, dt, on=True):
    """Display graphic bodies (Detail View): the mesh bodies drawn in the detail too. TechDraw draws no meshes,
    so a Part copy of each is projected by a second detail laid exactly over dt (its base view hidden)."""
    doc = page.Document
    if "SWGraphicBodies" not in dt.PropertiesList:
        dt.addProperty("App::PropertyBool", "SWGraphicBodies", "FreeCAD", "Display graphic bodies")
    dt.SWGraphicBodies = bool(on)
    for o in list(page.Views):
        if getattr(o, "SWGraphicOverlayOf", "") == dt.Name and o.TypeId == "TechDraw::DrawViewDetail":
            doc.removeObject(o.Name)
    for o in list(page.Views):
        if getattr(o, "SWGraphicOverlayOf", "") == dt.Name:
            doc.removeObject(o.Name)
    base = dt.BaseView
    meshes = graphic_meshes(base) if (on and base is not None) else []
    if not meshes:
        doc.recompute()
        return None
    bodies = [_mesh_body(m) for m in meshes]
    twin = doc.addObject("TechDraw::DrawViewPart", "GraphicTwin")
    page.addView(twin)
    D.link_source(twin, bodies)
    twin.Direction = base.Direction
    twin.XDirection = base.XDirection
    twin.ScaleType = "Custom"
    twin.Scale = base.Scale
    twin.X, twin.Y = base.X, base.Y
    twin.LockPosition = True
    over = doc.addObject("TechDraw::DrawViewDetail", "GraphicDetail")
    page.addView(over)
    over.BaseView = twin
    D.link_source(over, bodies)
    over.Direction = base.Direction
    over.XDirection = base.XDirection
    for o in (twin, over):
        o.addProperty("App::PropertyString", "SWGraphicOverlayOf", "FreeCAD", "its detail view")
        o.SWGraphicOverlayOf = dt.Name
    sync_graphic(dt, over, twin)
    try:
        twin.ViewObject.Visibility = False
    except Exception as _fw_err:
        _fw_log("drawviews.py:1868", _fw_err)
    for v in (over,):
        for prop, val in (("KeepLabel", False), ("ShowMatting", False)):
            try:
                setattr(v.ViewObject if prop == "KeepLabel" else v, prop, val)
            except Exception as _fw_err:
                _fw_log("drawviews.py:1874", _fw_err)
    try:
        over.Caption = ""
    except Exception as _fw_err:
        _fw_log("drawviews.py:1878", _fw_err)
    over.Label = dt.Label + " graphic bodies"
    doc.recompute()
    return over


def sync_graphic(dt, over=None, twin=None):
    """Keep the graphic bodies overlay on its detail: same place, scale, circle and (shifted) centre."""
    page = next((o for o in dt.InList if o.TypeId == "TechDraw::DrawPage"), None)
    if page is None:
        return
    for o in page.Views:
        if getattr(o, "SWGraphicOverlayOf", "") == dt.Name:
            if o.TypeId == "TechDraw::DrawViewDetail":
                over = over or o
            else:
                twin = twin or o
    if over is None or twin is None or dt.BaseView is None:
        return
    _d, x, y = D.view_frame(dt.BaseView)
    shift = model_centre(dt.BaseView) - model_centre(twin)
    a = dt.AnchorPoint
    over.AnchorPoint = V(a.x + shift.dot(x), a.y + shift.dot(y), 0)
    over.Radius = dt.Radius
    over.ScaleType = "Custom"
    over.Scale = dt.Scale
    over.X, over.Y = dt.X, dt.Y
    for prop in ("X", "Y", "Scale", "Radius"):
        try:
            over.setExpression(prop, "%s.%s" % (dt.Name, prop))        # follows the detail when it is moved
        except Exception as _fw_err:
            _fw_log("drawviews.py:1909", _fw_err)
    over.LockPosition = True
    try:
        over.ViewObject.LineWidth = dt.ViewObject.LineWidth
    except Exception as _fw_err:
        _fw_log("drawviews.py:1914", _fw_err)


class DetailViewPanel(D._Panel):
    TITLE = "Detail View"
    PIXMAP = "TechDraw_DetailView"
    GROUP_ORDER = ("Display State", "Display Style", "Scale", "Dimension Type", "Cosmetic Thread Display",
                   "Automatic View Update")

    def build(self):
        self.say(DETAIL_MESSAGE)
        box, lay = D._group("Detail Circle", self.form)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Label:", box))
        cur = getattr(self.page, "FreeWorksNextViewLabel", "") if hasattr(self.page, "FreeWorksNextViewLabel") else ""
        self.label = QtWidgets.QLineEdit(cur or "A", box)
        self.label.setObjectName("SWDetailLabel")
        self.label.editingFinished.connect(self.relabel)
        row.addWidget(self.label)
        lay.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Style:", box))
        self.circle_style = QtWidgets.QComboBox(box)
        self.circle_style.setObjectName("SWDetailStyle")
        self.circle_style.addItems(DETAIL_STYLES)
        self.circle_style.currentTextChanged.connect(self.update_detail)
        row.addWidget(self.circle_style)
        lay.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        self.as_circle = QtWidgets.QRadioButton("Circle", box)
        self.as_circle.setObjectName("SWDetailCircle")
        self.as_profile = QtWidgets.QRadioButton("Profile", box)
        self.as_profile.setObjectName("SWDetailProfile")
        self.as_circle.setChecked(True)
        self.as_profile.toggled.connect(lambda on: self.say(
            "Click the corners of the profile in a view; click the first corner again to close it." if on else
            DETAIL_MESSAGE))
        row.addWidget(self.as_circle)
        row.addWidget(self.as_profile)
        lay.addLayout(row)
        D.label_font_row(self, lay, "SWDetail")
        self.profile = []
        self.lay.addWidget(box)
        box, lay = D._group("Detail View", self.form)
        self.no_outline = QtWidgets.QCheckBox("No outline", box)
        self.no_outline.setObjectName("SWDetailNoOutline")
        self.outline = QtWidgets.QCheckBox("Full outline", box)
        self.outline.setObjectName("SWDetailFullOutline")
        self.jagged = QtWidgets.QCheckBox("Jagged outline", box)
        self.jagged.setObjectName("SWDetailJagged")
        self.jag_shape = QtWidgets.QSpinBox(box)
        self.jag_shape.setObjectName("SWDetailJaggedShape")
        self.jag_shape.setRange(1, 5)
        self.jag_shape.setValue(3)
        self.jag_shape.setPrefix("Shape intensity: ")

        trio = (self.no_outline, self.outline, self.jagged)
        for w in trio:
            w.toggled.connect(lambda on, w=w: on and [o.setChecked(False) for o in trio if o is not w])
            w.toggled.connect(self.update_detail)
        DL.sets(self.jagged, True, self.jag_shape)       # a shape intensity typed turns Jagged outline on
        self.jag_shape.valueChanged.connect(self.update_detail)
        self.pin = QtWidgets.QCheckBox("Pin position", box)
        self.pin.setObjectName("SWDetailPin")
        self.pin.setChecked(True)
        self.pin.toggled.connect(self.update_detail)
        lay.addWidget(self.no_outline)
        lay.addWidget(self.outline)
        lay.addWidget(self.jagged)
        lay.addWidget(self.jag_shape)
        lay.addWidget(self.pin)
        self.lay.addWidget(box)
        D._import_group(self, "Options", "SWDetail")
        box, lay = D._group("Display Style", self.form)
        self.style = D.StyleButtons(box, "SWDetailDisplayStyle", "Hidden Lines Removed")
        lay.addWidget(self.style)
        self.graphic_bodies = QtWidgets.QCheckBox("Display graphic bodies", box)
        self.graphic_bodies.setObjectName("SWDetailGraphicBodies")
        # shown only when there are graphic (mesh) bodies to show: a greyed box is a dead control
        self.graphic_bodies.setVisible(any(o.isDerivedFrom("Mesh::Feature") for n in App.listDocuments()
                                           for o in App.getDocument(n).Objects))
        self.graphic_bodies.setToolTip("Show the model's graphic (mesh) bodies in the detail view")
        self.graphic_bodies.toggled.connect(self.update_detail)
        lay.addWidget(self.graphic_bodies)
        self.lay.addWidget(box)
        self.style.currentTextChanged.connect(self.update_detail)
        D.extra_groups(self, "True", "Draft quality", lay, "SWDetail")
        DL.sets(self.parent_style, False, *self.style.buttons.values())   # a style clicked turns Use parent style off
        self.parent_style.toggled.connect(lambda on: self.update_detail())
        box, lay = D._group("Scale", self.form)
        self.use_parent = QtWidgets.QRadioButton("Use parent scale", box)
        self.use_parent.setObjectName("SWDetailParentScale")
        self.use_sheet = QtWidgets.QRadioButton("Use sheet scale", box)
        self.use_sheet.setObjectName("SWDetailSheetScale")
        self.use_custom = QtWidgets.QRadioButton("Use custom scale", box)
        self.use_custom.setObjectName("SWDetailCustomScale")
        self.use_custom.setChecked(True)
        self.scale = QtWidgets.QDoubleSpinBox(box)
        self.scale.setObjectName("SWDetailScale")
        self.scale.setDecimals(3)
        self.scale.setRange(0.001, 1000)
        self.scale.setValue(_detail_factor())
        for w in (self.use_parent, self.use_sheet, self.use_custom, self.scale):
            lay.addWidget(w)
            if isinstance(w, QtWidgets.QRadioButton):
                w.toggled.connect(self.update_detail)
        self.scale.valueChanged.connect(self.update_detail)
        self.lay.addWidget(box)
        self._after.append(lambda: self.set_page(1))
        self.base = None
        self.centre = None
        self.radius = None
        self.detail = None
        self.scale_set = False

    def set_page(self, n):
        ""


        keep = ("SWDrawGroup_Message", "SWDrawGroup_DetailCircle", "SWDrawGroup_DisplayStyle",
                "SWDrawGroup_CosmeticThreadDisplay")
        for box in self.form.findChildren(QtWidgets.QGroupBox):
            if box.parent() is self.form and box.objectName() not in keep:
                box.setVisible(n != 1)
        if n != 1:
            label = self.label.text().strip() or "A"
            self.form.setWindowTitle("Detail View %s" % label)

    def chosen_scale(self):
        if self.use_parent.isChecked() and self.base is not None:
            return view_scale(self.base)
        if self.use_sheet.isChecked():
            return float(self.page.Scale)
        return float(self.scale.value())

    def profile_click(self, p):
        """Profile: the corners of a closed sketched profile; the detail is made of the circle round it (a TechDraw
        detail is round), and the profile is drawn on the parent view in place of the circle."""
        if not self.profile:
            v = view_at(self.page, p)
            if v is None:
                self.say("Click inside a drawing view for the profile's first corner.")
                return True
            self.base = v
            if not self.scale_set:
                self.scale.blockSignals(True)
                self.scale.setValue(_detail_factor() * view_scale(v))
                self.scale.blockSignals(False)
        if len(self.profile) >= 3 and math.hypot(p[0] - self.profile[0][0], p[1] - self.profile[0][1]) < 2.0:
            pts = self.profile
            cx = sum(q[0] for q in pts) / len(pts)
            cy = sum(q[1] for q in pts) / len(pts)
            self.centre = (cx, cy)
            self.radius = max(0.5, max(math.hypot(q[0] - cx, q[1] - cy) for q in pts))
            self.set_page(2)
            self.say("Click in the graphics area to place the new view.")
            return True
        self.profile.append(p)
        self.say("Corner %d. Click the next corner, or the first one to close the profile." % len(self.profile))
        return True

    def sheet_click(self, p):
        if self.detail is not None:
            return False
        if self.as_profile.isChecked() and self.radius is None:
            return self.profile_click(p)
        if self.centre is None:
            v = view_at(self.page, p)
            if v is None:
                self.say("Click inside a drawing view to set the detail circle's center.")
                return True
            self.base = v
            self.centre = p
            if not self.scale_set:
                self.scale.blockSignals(True)
                self.scale.setValue(_detail_factor() * view_scale(v))
                self.scale.blockSignals(False)
            self.say("Click to set the circle's size.")
            return True
        if self.radius is None:
            self.radius = max(0.5, math.hypot(p[0] - self.centre[0], p[1] - self.centre[1]))
            self.set_page(2)
            self.say("Click in the graphics area to place the new view.")
            return True
        label = self.label.text().strip()
        cur = getattr(self.page, "FreeWorksNextViewLabel", "") if hasattr(self.page, "FreeWorksNextViewLabel") else ""
        label = take_label(self.page) if not label or label == (cur or "A") else label
        self.detail = make_detail(self.page, self.base, self.centre, self.radius, p, label, self.chosen_scale(),
                                  self.outline.isChecked(), self.pin.isChecked())
        self.label.setText(label)
        self.made.append(self.detail)
        self.annotation_views.clear()
        it = QtWidgets.QListWidgetItem(D.annotation_view_name(self.base), self.annotation_views)
        it.setCheckState(QtCore.Qt.Checked)
        if self.as_profile.isChecked() and len(self.profile) >= 3:
            detail_profile(self.page, self.detail, self.profile)
        if self.circle_style.currentText() != "Per Standard":
            self.doc.recompute()
            detail_style(self.page, self.detail, self.circle_style.currentText())
        self.update_detail()
        self.say("Detail View %s placed. Change its options, then OK." % label)
        return True

    def relabel(self):
        if self.detail is None:
            return
        t = self.label.text().strip()
        if t:
            self.detail.Reference = t
            a, b = _ratio(float(self.detail.Scale))
            self.detail.Label = "Detail View %s (%s : %s)" % (t, a, b)
            self.doc.recompute()

    def update_detail(self, *_):
        dt = self.detail
        if dt is None:
            return
        dt.Scale = self.chosen_scale()
        scale_hatch = False      # no Scale hatch pattern on a detail: TechDraw's detail has no hatch scale of its own
        if "SWScaleHatch" not in dt.PropertiesList:
            dt.addProperty("App::PropertyBool", "SWScaleHatch", "FreeCAD", "Detail View option")
        dt.SWScaleHatch = scale_hatch
        if self.base is not None and hasattr(dt, "HatchScale"):
            parent_scale = view_scale(self.base) if getattr(self.base, "SWScaleHatch", False) else 1.0
            hatch_scale = float(getattr(self.base, "HatchScale", 1.0)) / (parent_scale or 1.0)
            dt.HatchScale = hatch_scale * (view_scale(dt) if scale_hatch else 1.0)
        try:
            dt.ShowMatting = self.outline.isChecked()
        except Exception as _fw_err:
            _fw_log("drawviews.py:2131", _fw_err)
        dt.LockPosition = self.pin.isChecked()
        if self.parent_style.isChecked() and self.base is not None:
            D.set_display_style(dt, getattr(self.base, "SWDisplayStyle", "") or "Hidden Lines Removed")
        else:
            D.set_display_style(dt, self.style.currentText())
        D.apply_extra(self, dt)
        detail_style(self.page, dt, self.circle_style.currentText())
        self.doc.recompute()
        detail_jagged(self.page, dt, self.jag_shape.value() if self.jagged.isChecked() else 0)
        self.relabel()
        on = self.graphic_bodies.isChecked() and self.graphic_bodies.isEnabled()
        if on or getattr(dt, "SWGraphicBodies", False):
            graphic_bodies(self.page, dt, on)
        self.doc.recompute()

    def finish(self):
        if self.detail is not None:
            D.apply_label_font(self, self.detail)
            D.run_import(self, self.detail)


# --------------------------------------------------------------------------- Break (Broken View)
BREAK_STYLES = ("Straight Cut", "Curve Cut", "Zig Zag Cut", "Small Zig Zag Cut", "Jagged Cut")
_BREAK_TYPE = {"Straight Cut": "Simple", "Curve Cut": "Simple", "Zig Zag Cut": "ZigZag",
               "Small Zig Zag Cut": "ZigZag", "Jagged Cut": "ZigZag"}


_DRAWN = ("Curve Cut", "Small Zig Zag Cut", "Jagged Cut")


def set_break_style(bv, style):
    ""

    try:
        if style in _DRAWN:
            bv.ViewObject.BreakLineType = "None"
        else:
            bv.ViewObject.BreakLineType = _BREAK_TYPE.get(style, "ZigZag")
    except Exception as _fw_err:
        _fw_log("drawviews.py:2171", _fw_err)
    if _clear_break_lines(bv):
        bv.touch()                      # the view's lines are made again without the old break lines
        bv.Document.recompute()
    if style in _DRAWN:
        _break_lines_when_ready(bv)


def _clear_break_lines(bv):
    tags = list(getattr(bv, "SWBreakLines", []) or [])
    for tag in tags:
        try:
            bv.removeCosmeticEdge(tag)
        except Exception as _fw_err:
            _fw_log("drawviews.py:2185", _fw_err)
    if "SWBreakLines" in bv.PropertiesList:
        bv.SWBreakLines = []
    return bool(tags)


def _break_lines_when_ready(bv, tries=60):
    doc_name, name = bv.Document.Name, bv.Name

    def step(n=tries):
        try:
            v = App.getDocument(doc_name).getObject(name)
        except Exception as _fw_err:
            _fw_log("drawviews.py:2198", _fw_err)
            return
        if v is None:
            return
        busy = bool(v.isWaitingForHlr()) if hasattr(v, "isWaitingForHlr") else False
        if (busy or not v.getVisibleEdges()) and n > 0:
            QtCore.QTimer.singleShot(250, lambda: step(n - 1))
            return
        draw_break_lines(v)
    QtCore.QTimer.singleShot(600, step)       # the recompute that drops the old lines has started by then


def break_gap(bv):
    """(g0, g1, lo, hi, vertical): the gap of a broken view in its 2D coordinates as TechDraw gives its lines
    (sheet size, the view's scale applied), along X for vertical break lines, and the extent of the part across
    it. None when no gap is found. Measured while no drawn break line is on the view (they are lines too)."""
    vertical = bool(getattr(bv, "SWBreakVertical", True))
    key = "%g" % float(getattr(bv, "Gap", 0))
    kept = list(getattr(bv, "SWBreakGap", []) or [])
    if len(kept) == 5 and getattr(bv, "SWBreakGapAt", "") == key:
        return tuple(kept[:4]) + (vertical,)
    spans, across = [], []
    for e in bv.getVisibleEdges():
        bb = e.BoundBox
        a, b = (bb.XMin, bb.XMax) if vertical else (bb.YMin, bb.YMax)
        c, d = (bb.YMin, bb.YMax) if vertical else (bb.XMin, bb.XMax)
        spans.append((a, b))
        across += [c, d]
    if not spans:
        return None
    spans.sort()
    best, end = None, spans[0][1]
    for a, b in spans[1:]:
        if a > end + 1e-6 and (best is None or a - end > best[1] - best[0]):
            best = (end, a)
        end = max(end, b)
    if best is None:
        return None
    out = (best[0], best[1], min(across), max(across))
    try:
        if "SWBreakGap" not in bv.PropertiesList:
            bv.addProperty("App::PropertyFloatList", "SWBreakGap", "FreeCAD", "the measured break gap")
            bv.addProperty("App::PropertyString", "SWBreakGapAt", "FreeCAD", "the Gap it was measured at")
        bv.SWBreakGap = list(out) + [1.0]
        bv.SWBreakGapAt = key
    except Exception as _fw_err:
        _fw_log("drawviews.py:2243", _fw_err)
    return out + (vertical,)


def _break_path(style, at, lo, hi, k, intensity=3):
    """The points of one break line at 'at' from lo to hi (view units; k the view scale), as (along, across)."""
    out = []
    span = hi - lo
    if style == "Curve Cut":
        amp = 2.5 / k
        n = 24
        for i in range(n + 1):
            t = i / float(n)
            out.append((at + amp * math.sin(2 * math.pi * t), lo + span * t))
    elif style == "Small Zig Zag Cut":
        pitch = 2.0 / k
        n = max(4, int(span / pitch))
        for i in range(n + 1):
            out.append((at + (0.8 / k if i % 2 else -0.8 / k), lo + span * i / float(n)))
    else:                                       # Jagged Cut: an uneven torn edge (the same every time)
        n = max(6, int(span / (2.5 / k)))
        for i in range(n + 1):
            r = ((i * 7919) % 13) / 13.0 - 0.5
            out.append((at + r * intensity / k, lo + span * i / float(n)))   # Jagged cut shape intensity 1..5
    return out


def draw_break_lines(bv):
    style = getattr(bv, "SWBreakStyle", "")
    _clear_break_lines(bv)
    if style not in _DRAWN:
        return []
    g = break_gap(bv)
    if g is None:
        return []
    k = view_scale(bv)
    g0, g1, lo, hi, vertical = [x / k for x in g[:4]] + [g[4]]      # cosmetic lines take model sizes
    pad = 2.0 / k
    tags = []
    for at in (g0, g1):
        pts = _break_path(style, at, lo - pad, hi + pad, k, int(getattr(bv, "SWBreakJagged", 3) or 3))
        for (a1, c1), (a2, c2) in zip(pts, pts[1:]):
            p1 = V(a1, c1, 0) if vertical else V(c1, a1, 0)
            p2 = V(a2, c2, 0) if vertical else V(c2, a2, 0)
            try:
                tags.append(bv.makeCosmeticLine(p1, p2))
            except Exception as _fw_err:
                _fw_log("drawviews.py:2290", _fw_err)
    if "SWBreakLines" not in bv.PropertiesList:
        bv.addProperty("App::PropertyStringList", "SWBreakLines", "FreeCAD", "the drawn break lines")
    bv.SWBreakLines = tags
    bv.touch()
    bv.Document.recompute()
    return tags


def _across(base, axis):
    """(min, max) of base's model along the view direction axis, measured from the model centre (view geometry)."""
    c = model_centre(base)
    vals = []
    for o in source_shapes(base):
        try:
            bb = o.Shape.BoundBox
            pts = [V(bb.XMax if i & 1 else bb.XMin, bb.YMax if i & 2 else bb.YMin, bb.ZMax if i & 4 else bb.ZMin)
                   for i in range(8)]
            vals += [(p - c).dot(axis) for p in pts]
        except Exception as _fw_err:
            _fw_log("drawviews.py:break across", _fw_err)
    if not vals:
        return -10.0, 10.0
    return min(vals), max(vals)


def make_break(page, base, vertical, a, b, gap=10.0, style="Zig Zag Cut"):
    """Break base between sheet points a and b (vertical break lines at a.x and b.x, else horizontal ones at a.y
    and b.y): the view becomes a broken view, gap mm between the pieces on the sheet."""
    doc = page.Document
    from . import newdoc
    newdoc._serial_projections()
    x0, y0 = D.view_position(base)
    ua, wa = to_geometry(base, a)
    ub, wb = to_geometry(base, b)
    if abs((ub - ua) if vertical else (wb - wa)) < 1e-6:
        raise ValueError("the two break lines are in one place")
    # TechDraw's break: a sketch in the view's plane with two parallel lines across the part
    import Part
    d, x, y = D.view_frame(base)
    m = App.Matrix(x.x, y.x, d.x, 0, x.y, y.y, d.y, 0, x.z, y.z, d.z, 0, 0, 0, 0, 1)
    cut = doc.addObject("Sketcher::SketchObject", "Break")
    cut.Placement = App.Placement(model_centre(base), App.Rotation(m))

    # ways: TechDraw draws them as long as these sketch lines
    lo, hi = _across(base, y if vertical else x)
    k0 = view_scale(base) or 1.0
    lo, hi = lo - 3.0 / k0, hi + 3.0 / k0
    for u, w in ((ua, wa), (ub, wb)):
        if vertical:
            cut.addGeometry(Part.LineSegment(V(u, lo, 0), V(u, hi, 0)))
        else:
            cut.addGeometry(Part.LineSegment(V(lo, w, 0), V(hi, w, 0)))
    cut.Label = "Break%d" % (1 + len([o for o in doc.Objects if o.Label.startswith("Break")]))
    try:
        cut.ViewObject.Visibility = False
    except Exception as _fw_err:
        _fw_log("drawviews.py:2331", _fw_err)
    cut.recompute()
    label = base.Label
    users = [o for o in base.InList if o is not page and o.TypeId != "TechDraw::DrawProjGroup"]
    replace = base.TypeId == "TechDraw::DrawViewPart" and not users
    bv = doc.addObject("TechDraw::DrawBrokenView", "BrokenView")
    if replace:

        # rename of a broken view throws in TechDraw)
        base.Label = label + " (unbroken)"
        bv.Label = label
    else:
        bv.Label = label + " (broken)"
    section = base.isDerivedFrom("TechDraw::DrawViewSection")
    if section:

        base.Label = label + " (unbroken)"
        bv.Label = label
    page.addView(bv)
    cutobj = None
    if section:
        n = D._unit(base.SectionNormal)
        u = D._unit(base.XDirection)
        cutobj = drawing_shape(doc, source_shapes(base), "Cut", base.SectionOrigin, n, u, n.cross(u),
                               label="%s cut" % label)
        bv.XSource = []
        bv.Source = [cutobj]
    else:
        D.link_source(bv, source_shapes(base))
    bv.Breaks = [cut]
    bv.Direction = base.Direction
    bv.XDirection = base.XDirection
    k = view_scale(base)
    bv.ScaleType = "Custom"
    bv.Scale = k
    bv.Gap = gap / k
    bv.X, bv.Y = x0, y0
    D.set_display_style(bv, getattr(base, "SWDisplayStyle", "") or "Hidden Lines Removed")
    try:
        bv.addProperty("App::PropertyString", "SWBreakStyle", "FreeCAD", "Break line style")
        bv.SWBreakStyle = style
        bv.addProperty("App::PropertyBool", "SWBreakVertical", "FreeCAD", "break lines are vertical")
        bv.SWBreakVertical = bool(vertical)
    except Exception as _fw_err:
        _fw_log("drawviews.py:2375", _fw_err)
    set_break_style(bv, style)
    if section:
        try:
            bv.addProperty("App::PropertyString", "SWBrokenSection", "FreeCAD", "the section view this breaks")
            bv.SWBrokenSection = base.Name
            bv.addProperty("App::PropertyFloatList", "SWBreakAt", "FreeCAD", "break lines (view geometry)")
            bv.SWBreakAt = sorted([ua, ub] if vertical else [wa, wb])
        except Exception as _fw_err:
            _fw_log("drawviews.py:2384", _fw_err)
    if replace:
        doc.recompute()
        page.removeView(base)
        doc.removeObject(base.Name)
    else:
        base.ViewObject.Visibility = False     # a view others hang on (sections, details, a group) stays, hidden
    doc.recompute()
    if section:
        hatch_broken_section_later(page, bv)
    return bv


def ribs_of(objs):
    ""
    out = []
    for o in objs or []:
        group = list(getattr(o, "Group", []) or []) if o.TypeId == "PartDesign::Body" else [o]
        for f in group:
            if type(getattr(f, "Proxy", None)).__name__ == "RibFeature" and f not in out:
                out.append(f)
    return out


def _rib_material(rib):
    sh = rib.Shape.copy()
    base = getattr(rib, "BaseFeature", None)
    if base is not None and not base.Shape.isNull():
        sh = sh.cut(base.Shape)
    return sh


def set_excluded_ribs(s, names):
    ""

    import Part
    from . import drawannot as DA
    doc = s.Document
    if "SWExcludedRibs" not in s.PropertiesList:
        s.addProperty("App::PropertyStringList", "SWExcludedRibs", "FreeCAD", "Section View: ribs not cut")
    s.SWExcludedRibs = list(names)
    for o in [o for o in doc.Objects if getattr(o, "SWRibMaskOf", "") == s.Name]:
        doc.removeObject(o.Name)
    page = next((p for p in s.InList if p.isDerivedFrom("TechDraw::DrawPage")), None)
    if page is None or not names:
        doc.recompute()
        return []
    n = D._unit(s.SectionNormal)
    dist = n.dot(s.SectionOrigin)
    srcs = source_shapes(s)
    shapes = [o.Shape for o in srcs if hasattr(o, "Shape") and not o.Shape.isNull()]
    if not shapes:
        return []
    whole = shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes)
    # TechDraw centres a section on the box of the piece it keeps (the side away from the normal)
    L = max(10.0, whole.BoundBox.DiagonalLength) * 2.0
    u = D._unit(s.XDirection)
    w = n.cross(u)
    m = App.Matrix(u.x, w.x, n.x, 0, u.y, w.y, n.y, 0, u.z, w.z, n.z, 0, 0, 0, 0, 1)
    box = Part.makeBox(2 * L, 2 * L, 2 * L)
    box.Placement = App.Placement(s.SectionOrigin + App.Rotation(m).multVec(V(-L, -L, -2 * L)), App.Rotation(m))
    try:
        centre = whole.common(box).BoundBox.Center
    except Exception:
        centre = whole.BoundBox.Center
    d, x, y = D.view_frame(s)
    made = []
    for rib in ribs_of(xsource(s) + list(getattr(s, "Source", []) or [])):
        if rib.Name not in names and rib.Label not in names:
            continue
        try:
            wires = _rib_material(rib).slice(n, dist)
        except Exception:
            wires = []
        for wire in wires:
            try:
                pts = wire.discretize(Deflection=0.02)
                flat = [V((q - centre).dot(x), (q - centre).dot(y), 0) for q in pts]
                face = Part.Face(Part.makePolygon(flat + [flat[0]]))
            except Exception:
                continue
            body, R, at = DA.hatch_svg(face, s, pattern="Solid", color="#ffffff")
            k = view_scale(s)
            fb = face.BoundBox
            cx, cy = (fb.XMin + fb.XMax) / 2, (fb.YMin + fb.YMax) / 2
            outline = "M" + " L".join("%g %g" % ((q.x - cx) * k, -(q.y - cy) * k) for q in flat) + " Z"
            body += '<path d="%s" fill="none" stroke="#000" stroke-width="0.35"/>' % outline
            mk = DA.svg_symbol(page, "RibMask", body, R, at, "%s rib %s" % (s.Label, rib.Label), "SectionRib")
            mk.addProperty("App::PropertyString", "SWRibMaskOf", "FreeCAD", "the section view")
            mk.SWRibMaskOf = s.Name
            mk.addProperty("App::PropertyFloat", "SWRibArea", "FreeCAD", "the rib's cut area")
            mk.SWRibArea = face.Area
            made.append(mk)
    doc.recompute()
    return made


def broken_point(bv, g):
    """Where geometry point g of the unbroken model lands in broken view bv (None if a break takes it out)."""
    at = list(getattr(bv, "SWBreakAt", []) or [])
    if len(at) != 2:
        return g
    lo, hi = at
    shrink = (hi - lo) - float(bv.Gap)
    i = 0 if getattr(bv, "SWBreakVertical", True) else 1
    q = list(g)
    if q[i] <= lo:
        q[i] += shrink / 2.0
    elif q[i] >= hi:
        q[i] -= shrink / 2.0
    else:
        return None
    return tuple(q)


def hatch_broken_section(page, bv):
    """The section hatch on the cut faces of broken section view bv (TechDraw hatches only section views):
    one area hatch per piece of each cut face. Returns the hatch symbols made."""
    import Part
    from . import drawannot as DA
    doc = page.Document
    sec = doc.getObject(getattr(bv, "SWBrokenSection", "") or "")
    src = list(bv.Source or [])
    if sec is None or not src:
        return []
    for o in [o for o in doc.Objects if getattr(o, "SWHatchView", "") == bv.Name and
              getattr(o, "SWSectionHatch", False)]:
        doc.removeObject(o.Name)
    n = D._unit(sec.SectionNormal)
    faces = [f for f in src[0].Shape.Faces if f.Surface.__class__.__name__ == "Plane" and
             abs(abs(f.normalAt(0, 0).dot(n)) - 1) < 1e-6 and abs((f.CenterOfMass - sec.SectionOrigin).dot(n)) < 1e-6]
    centre = bv.projectPoint(model_centre(bv))
    at = list(getattr(bv, "SWBreakAt", []) or [])
    i = 0 if getattr(bv, "SWBreakVertical", True) else 1
    made, seen = [], []
    pattern = "ANSI31 (Iron BrickStone)"
    for f in faces:
        # sample points inside the face, a few on each side of the break
        bb = f.BoundBox
        pts = []
        u0, u1 = f.ParameterRange[0], f.ParameterRange[1]
        v0, v1 = f.ParameterRange[2], f.ParameterRange[3]
        for a in range(1, 12):
            for b in range(1, 6):
                q = f.valueAt(u0 + (u1 - u0) * a / 12.0, v0 + (v1 - v0) * b / 6.0)
                if f.isInside(q, 1e-6, True):
                    pts.append(q)
        for q in pts:
            p2 = bv.projectPoint(q)
            g = broken_point(bv, (p2.x - centre.x, p2.y - centre.y))
            if g is None:
                continue
            if any(r.isInside(V(g[0], g[1], 0), 1e-6, True) for r in seen):
                continue
            region = DA.region_at(bv, g)
            if region is None:
                continue
            seen.append(region)
            body, R, where = DA.hatch_svg(region, bv, pattern=pattern)
            h = DA.svg_symbol(page, "AreaHatch", body, R, where, "%s hatch" % bv.Label, "AreaHatch")
            for name, kind, val in (("SWHatchArea", "App::PropertyFloat", region.Area),
                                    ("SWHatchPattern", "App::PropertyString", pattern),
                                    ("SWHatchView", "App::PropertyString", bv.Name),
                                    ("SWHatchCentre", "App::PropertyVector", region.CenterOfMass),
                                    ("SWSectionHatch", "App::PropertyBool", True)):
                h.addProperty(kind, name, "FreeCAD", "broken section hatch")
                setattr(h, name, val)
            made.append(h)
    if made:
        doc.recompute()
    return made


def hatch_broken_section_later(page, bv, tries=40):
    """Once TechDraw has drawn the broken view (it projects in the background)."""
    try:
        ready = bool(bv.getVisibleEdges())
    except Exception:
        ready = False
    if not ready and tries > 0:
        QtCore.QTimer.singleShot(250, lambda: hatch_broken_section_later(page, bv, tries - 1))
        return
    try:
        hatch_broken_section(page, bv)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: broken section hatch: %s\n" % error)


class BreakPanel(D._Panel):
    TITLE = "Broken View"
    PIXMAP = "TechDraw_BrokenView"

    def build(self):
        self.say("Click in a view to place the first break line, then click to place the second.")
        box, lay = D._group("Broken View Settings", self.form)
        row = QtWidgets.QVBoxLayout()           # one above the other: side by side made the pane 397 px wide
        self.dir = QtWidgets.QButtonGroup(box)
        for n, (name, text) in enumerate((("Vertical", "Add vertical break line"),
                                          ("Horizontal", "Add horizontal break line"))):
            b = QtWidgets.QToolButton(box)
            b.setText(text)
            b.setCheckable(True)
            b.setObjectName("SWBreak" + name)
            self.dir.addButton(b, n)
            row.addWidget(b)
            if n == 0:
                b.setChecked(True)
        lay.addLayout(row)
        g = QtWidgets.QHBoxLayout()
        g.addWidget(QtWidgets.QLabel("Gap size:", box))
        self.gap = QtWidgets.QDoubleSpinBox(box)
        self.gap.setObjectName("SWBreakGap")
        self.gap.setRange(0.1, 1000)
        self.gap.setValue(10.0)
        self.gap.setSuffix("mm")
        self.gap.valueChanged.connect(self.update_break)
        g.addWidget(self.gap)
        lay.addLayout(g)
        lay.addWidget(QtWidgets.QLabel("Break line style:", box))
        self.style = QtWidgets.QComboBox(box)
        self.style.setObjectName("SWBreakStyle")
        self.style.addItems(BREAK_STYLES)
        self.style.setCurrentText("Zig Zag Cut")
        self.style.currentTextChanged.connect(self.update_break)
        lay.addWidget(self.style)

        self.jagged = QtWidgets.QSpinBox(box)
        self.jagged.setObjectName("SWBreakJagged")
        self.jagged.setRange(1, 5)
        self.jagged.setValue(3)
        self.jagged.setPrefix("Shape intensity: ")
        self.jagged.valueChanged.connect(self.update_break)
        lay.addWidget(self.jagged)
        self.style.currentTextChanged.connect(lambda t: self.jagged.setVisible(t == "Jagged Cut"))
        self.jagged.setVisible(False)
        self.lay.addWidget(box)
        self.base = None
        self.first = None
        self.broken = None

    def sheet_click(self, p):
        if self.broken is not None:
            return False
        if self.first is None:
            v = view_at(self.page, p)
            if v is None:
                self.say("Click inside a drawing view to place the first break line.")
                return True
            self.base, self.first = v, p
            self.say("Click to place the second break line.")
            return True
        vertical = self.dir.checkedId() == 0
        a, b = (self.first, p) if (p[0] > self.first[0] if vertical else p[1] > self.first[1]) else (p, self.first)
        try:
            self.broken = make_break(self.page, self.base, vertical, a, b, self.gap.value(), self.style.currentText())
        except ValueError as error:
            self.first = None
            self.say("%s. Click in a view to place the first break line." % str(error).capitalize())
            return True
        self.made.append(self.broken)
        if self.style.currentText() == "Jagged Cut" and self.jagged.value() != 3:
            self.update_break()
        self.say("The view is broken. Change the gap or the line style, then OK.")
        return True

    def update_break(self, *_):
        bv = self.broken
        if bv is None:
            return
        bv.Gap = self.gap.value() / view_scale(bv)
        try:
            bv.SWBreakStyle = self.style.currentText()
            if "SWBreakJagged" not in bv.PropertiesList:
                bv.addProperty("App::PropertyInteger", "SWBreakJagged", "FreeCAD", "jagged cut shape intensity")
            bv.SWBreakJagged = self.jagged.value()
        except Exception as _fw_err:
            _fw_log("drawviews.py:2660", _fw_err)
        self.doc.recompute()
        set_break_style(bv, self.style.currentText())


# --------------------------------------------------------------------------- Crop
def make_crop(page, base, a, b):
    """Crop base to the sheet rectangle between corners a and b (a TechDraw clip frame round it)."""
    doc = page.Document
    x0, y0 = D.view_position(base)
    cx, cy = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
    w, h = abs(b[0] - a[0]), abs(b[1] - a[1])
    if w < 1 or h < 1:
        raise ValueError("the crop area has no size")
    clip = doc.addObject("TechDraw::DrawViewClip", "Crop")
    page.addView(clip)
    clip.X, clip.Y = cx, cy
    clip.Width, clip.Height = w, h
    clip.ShowFrame = False
    clip.Label = base.Label + " Crop"
    clip.addView(base)                    # (the view stays on the sheet's list too, as TechDraw keeps it)
    base.X, base.Y = x0 - cx, y0 - cy     # the view stays where it was on the sheet
    doc.recompute()
    return clip


def _is_rectangle(ring):
    if len(ring) != 4:
        return False
    xs = sorted(round(q[0], 6) for q in ring)
    ys = sorted(round(q[1], 6) for q in ring)
    return xs[0] == xs[1] and xs[2] == xs[3] and ys[0] == ys[1] and ys[2] == ys[3]


def crop_mask(page, clip, ring):
    ""


    import json
    if "SWCropProfile" not in clip.PropertiesList:
        clip.addProperty("App::PropertyString", "SWCropProfile", "FreeCAD", "the closed profile it crops to")
    clip.SWCropProfile = json.dumps(ring)
    if _is_rectangle(ring):
        return None
    doc = page.Document
    cx, cy = float(clip.X), float(clip.Y)
    w, h = float(clip.Width) / 2 + 0.6, float(clip.Height) / 2 + 0.6
    inner = " ".join("%s%g %g" % ("M" if i == 0 else "L", x - cx, -(y - cy)) for i, (x, y) in enumerate(ring))
    body = ('<path d="M%g %g L%g %g L%g %g L%g %g Z %s Z" fill="#fff" fill-rule="evenodd" stroke="none"/>'
            % (-w, -h, w, -h, w, h, -w, h, inner))
    R = max(w, h) + 1
    mask = doc.addObject("TechDraw::DrawViewSymbol", "CropMask")
    page.addView(mask)
    mask.addProperty("App::PropertyString", "SWCropMaskOf", "FreeCAD", "the crop it shapes")
    mask.SWCropMaskOf = clip.Name
    mask.Symbol = ('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="%g %g %g %g">'
                   '%s</svg>' % (2 * R, 2 * R, -R, -R, 2 * R, 2 * R, body))
    mask.Label = clip.Label + " (profile)"
    mask.X, mask.Y = cx, cy
    for prop in ("X", "Y"):
        try:
            mask.setExpression(prop, "%s.%s" % (clip.Name, prop))
        except Exception as _fw_err:
            _fw_log("drawviews.py:2723", _fw_err)
    try:
        mask.ViewObject.StackOrder = 50
        mask.ViewObject.KeepLabel = False
    except Exception as _fw_err:
        _fw_log("drawviews.py:2728", _fw_err)
    doc.recompute()
    return mask


def remove_crop(clip):
    """Crop View > Remove Crop: the view back on the sheet, whole."""
    page = clip.findParentPage()
    doc = clip.Document
    for o in list(page.Views):
        if getattr(o, "SWCropMaskOf", "") == clip.Name:
            doc.removeObject(o.Name)
    cx, cy = float(clip.X), float(clip.Y)
    for v in list(clip.Views):
        x, y = float(v.X) + cx, float(v.Y) + cy
        clip.removeView(v)
        if v not in page.Views:
            page.addView(v)
        v.X, v.Y = x, y
    page.removeView(clip)
    doc.removeObject(clip.Name)
    doc.recompute()


class CropPanel(D._Panel):
    TITLE = "Crop View"
    PIXMAP = "TechDraw_ClipGroup"

    def build(self):
        self.say("Click one corner of the area of the view to keep, then the opposite corner.")
        self.first = None
        self.base = None
        self.clip = None

    def sheet_click(self, p):
        if self.clip is not None:
            return False
        if self.first is None:
            v = view_at(self.page, p)
            if v is None:
                self.say("Click inside a drawing view for the first corner.")
                return True
            self.base, self.first = v, p
            self.say("Click the opposite corner.")
            return True
        try:
            self.clip = make_crop(self.page, self.base, self.first, p)
        except ValueError as error:
            self.first = None
            self.say("%s. Click a first corner again." % str(error).capitalize())
            return True
        self.made.append(self.clip)
        QtCore.QTimer.singleShot(0, self.accept)
        return True


def picked_crop():
    for sel in Gui.Selection.getSelectionEx("", 0):
        o = sel.Object
        if o.TypeId == "TechDraw::DrawViewClip":
            return o
        for i in o.InList:
            if i.TypeId == "TechDraw::DrawViewClip":
                return i
    return None


# --------------------------------------------------------------------------- Empty, Predefined, Relative To Model
def make_empty(page, at, size=(50.0, 40.0)):
    """Empty View: an empty frameless view to sketch or put things in, named Drawing ViewN."""
    doc = page.Document
    v = doc.addObject("TechDraw::DrawViewClip", "EmptyView")
    page.addView(v)
    v.Width, v.Height = size
    v.ShowFrame = False
    v.X, v.Y = at
    v.Label = D._next_label(page)
    doc.recompute()
    return v


class EmptyViewPanel(D._Panel):
    TITLE = "Empty View"
    PIXMAP = "TechDraw_ClipGroup"

    def build(self):
        self.say("Click on the sheet to place the empty view.")
        self.view = None

    def sheet_click(self, p):
        if self.view is None:
            self.view = make_empty(self.page, p)
            self.made.append(self.view)
            QtCore.QTimer.singleShot(0, self.accept)
        return True


class PredefinedViewPanel(D._SourcePick, D._Panel):
    """Predefined View: a view with an orientation and scale, the model put in now or later (Insert Model)."""
    TITLE = "Drawing View"
    PIXMAP = "TechDraw_View"

    def build(self):
        self.say("Set the orientation, then click on the sheet to place the predefined view.")
        box, lay = D._group("Orientation", self.form)
        grid = QtWidgets.QGridLayout()
        self.orient = QtWidgets.QButtonGroup(box)
        for n, name in enumerate(D.ORIENTATIONS):
            b = QtWidgets.QToolButton(box)
            b.setText(name)
            b.setCheckable(True)
            b.setObjectName("SWDrawOrient" + name)
            self.orient.addButton(b, n)
            grid.addWidget(b, n // 3, n % 3)
            b.setChecked(name == "Front")
        lay.addLayout(grid)
        self.lay.addWidget(box)
        box, lay = D._group("Insert Model", self.form)
        self.insert = QtWidgets.QCheckBox("Insert a model now", box)
        self.insert.setObjectName("SWPredefinedInsert")
        lay.addWidget(self.insert)
        self.lay.addWidget(box)
        self.source_group()
        self.view = None

    def sheet_click(self, p):
        if self.view is not None:
            return False
        d, x = D.ORIENTATIONS[self.orient.checkedButton().text()]
        shapes = []
        if self.insert.isChecked():
            src = self.source()
            if src is None or not D.saved_source(src, self.doc):
                return True
            shapes = D.model_shapes(src)
        doc = self.doc
        from . import newdoc
        newdoc._serial_projections()
        v = doc.addObject("TechDraw::DrawViewPart", "View")
        self.page.addView(v)
        if shapes:
            D.link_source(v, shapes)
        v.Direction, v.XDirection = D._unit(d), D._unit(x)
        v.X, v.Y = p
        v.Label = D._next_label(self.page)
        v.addProperty("App::PropertyBool", "SWPredefined", "FreeCAD", "Predefined view")
        v.SWPredefined = True
        doc.recompute()
        self.view = v
        self.made.append(v)
        QtCore.QTimer.singleShot(0, self.accept)
        return True


def insert_model(view, source):
    """Insert Model into a predefined (empty) view."""
    D.link_source(view, D.model_shapes(source))
    view.Document.recompute()


FACE_ORIENTS = ("Front", "Back", "Top", "Bottom", "Left", "Right")


def relative_frame(first, n1, second, n2):
    """(direction to the viewer, XDirection) from two faces' normals and the orientations given to them."""
    n1, n2 = D._unit(n1), D._unit(n2)
    d = x = up = None

    def put(name, n):
        nonlocal d, x, up
        if name in ("Front", "Back"):
            d = n if name == "Front" else -n
        elif name in ("Right", "Left"):
            x = n if name == "Right" else -n
        else:
            up = n if name == "Top" else -n
    put(first, n1)
    put(second, n2)
    if d is None:
        if x is None or up is None:
            raise ValueError("pick two faces for two different kinds of orientation")
        d = D._unit(x.cross(up))
    if x is None:
        if up is None:
            raise ValueError("the two faces give the same orientation")
        x = D._unit(up.cross(d))
    x = D._unit(x - d * x.dot(d))
    if x.Length < 1e-9:
        raise ValueError("the faces are parallel")
    return d, x


def face_normal(obj, sub):
    f = obj.getSubObject(sub)
    u0, u1, v0, v1 = f.ParameterRange
    n = f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    return n


class RelativeViewPanel(D._SourcePick, D._Panel):
    """Relative To Model: two faces of the model and the orientation each one faces, then a click places the view."""
    TITLE = "Relative View"
    PIXMAP = "TechDraw_View"

    def build(self):
        self.say("In the model's window select a face for the First orientation and one for the Second, "
                 "then OK and click on the sheet to place the view.")
        self.source_group()
        box, lay = D._group("Orientation", self.form)
        grid = QtWidgets.QGridLayout()
        self.first = QtWidgets.QComboBox(box)
        self.first.setObjectName("SWRelativeFirst")
        self.first.addItems(FACE_ORIENTS)
        self.second = QtWidgets.QComboBox(box)
        self.second.setObjectName("SWRelativeSecond")
        self.second.addItems(FACE_ORIENTS)
        self.second.setCurrentText("Right")
        self.face1 = QtWidgets.QLineEdit(box)
        self.face1.setObjectName("SWRelativeFace1")
        self.face1.setReadOnly(True)
        self.face2 = QtWidgets.QLineEdit(box)
        self.face2.setObjectName("SWRelativeFace2")
        self.face2.setReadOnly(True)
        grid.addWidget(QtWidgets.QLabel("First:", box), 0, 0)
        grid.addWidget(self.first, 0, 1)
        grid.addWidget(self.face1, 1, 0, 1, 2)
        grid.addWidget(QtWidgets.QLabel("Second:", box), 2, 0)
        grid.addWidget(self.second, 2, 1)
        grid.addWidget(self.face2, 3, 0, 1, 2)
        lay.addLayout(grid)
        self.lay.addWidget(box)

        bbox, blay = D._group("Bodies", self.form)
        self.only_bodies = QtWidgets.QCheckBox("Selected bodies only", bbox)
        self.only_bodies.setObjectName("SWRelativeOnlyBodies")
        self.only_bodies.setToolTip("The view shows only the bodies the picked faces are on")
        self.bodies = QtWidgets.QListWidget(bbox)
        self.bodies.setObjectName("SWRelativeBodies")
        self.bodies.setProperty("swpickbox", True)
        self.bodies.setMaximumHeight(60)
        blay.addWidget(self.only_bodies)
        blay.addWidget(self.bodies)
        self.lay.addWidget(bbox)
        self.picked_bodies = []
        self.faces = []
        Gui.Selection.addObserver(self)
        QtCore.QTimer.singleShot(200, self.show_model)

    def show_model(self):
        ""
        src = self.source()
        if src is None:
            return
        try:
            gd = Gui.getDocument(src.Name)
            views = gd.mdiViewsOfType("Gui::View3DInventor")
            if not views:
                gd.ActiveView  # noqa
                views = gd.mdiViewsOfType("Gui::View3DInventor")
            mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
            for sub in mdi.subWindowList():
                if src.Label in sub.windowTitle() and sub.widget() is not None:
                    mdi.setActiveSubWindow(sub)
                    break
        except Exception as _fw_err:
            _fw_log("drawviews.py:2992", _fw_err)

    def addSelection(self, doc, obj, sub, pos):
        if not sub or not sub.split(".")[-1].startswith("Face"):
            return
        try:
            o = App.getDocument(doc).getObject(obj)
            n = face_normal(o, sub)
        except Exception:
            return
        if len(self.faces) >= 2:
            self.faces = []
        self.faces.append((o.Label + "." + sub.split(".")[-1], n))
        self.add_body(o)
        self.face1.setText(self.faces[0][0])
        self.face2.setText(self.faces[1][0] if len(self.faces) > 1 else "")
        if len(self.faces) == 2:
            self.say("Click OK, then click on the sheet to place the view.")

    def add_body(self, o):
        """The body a picked face is on (a member body, or a part's Body) goes in Bodies."""
        body = next((p for p in o.InList if p.TypeId == "PartDesign::Body"), None) or o
        if body not in self.picked_bodies:
            self.picked_bodies.append(body)
            self.bodies.addItem(body.Label)

    def shapes(self, src):
        if self.only_bodies.isChecked() and self.picked_bodies:
            return list(self.picked_bodies)
        return D.model_shapes(src)

    def _stop(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("drawviews.py:3027", _fw_err)

    def reject(self):
        self._stop()
        out = super().reject()
        try:
            from . import drawsheet
            drawsheet.show_page(self.page)
        except Exception as _fw_err:
            _fw_log("drawviews.py:3036", _fw_err)
        return out

    def finish(self):
        self._stop()
        src = self.source()
        if src is None or len(self.faces) < 2:
            raise ValueError("pick two faces of the model")
        d, x = relative_frame(self.first.currentText(), self.faces[0][1], self.second.currentText(),
                              self.faces[1][1])
        if not D.saved_source(src, self.doc):
            return
        _Placer.start(self.page, self.shapes(src), d, x)


class _Placer:
    ""

    me = None

    @classmethod
    def start(cls, page, shapes, d, x):
        cls.me = cls(page, shapes, d, x)

    def __init__(self, page, shapes, d, x):
        self.page, self.shapes, self.d, self.x = page, shapes, d, x
        try:
            from . import drawsheet
            drawsheet.show_page(page)
        except Exception as _fw_err:
            _fw_log("drawviews.py:3066", _fw_err)
        QtCore.QTimer.singleShot(300, self._hook)
        self.view = None

    def _hook(self):
        self.clicks = D.SheetClicks(self.page, self)

    def sheet_click(self, p):
        doc = self.page.Document
        doc.openTransaction("Relative View")
        try:
            self.view = D.new_view(self.page, self.shapes, self.d, self.x, p)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        doc.recompute()
        self.clicks.stop()
        _Placer.me = None
        return True

    def sheet_move(self, p):
        pass


# --------------------------------------------------------------------------- Section Scope (components)
FASTENER_WORDS = ("bolt", "screw", "nut", "washer", "pin", "rivet", "stud", "fastener", "iso 4", "iso 7", "din 9",
                  "din 1", "ansi b18")


def _is_container(o):
    return o.TypeId in ("App::Part", "Assembly::AssemblyObject") or (
        o.isDerivedFrom("App::DocumentObjectGroup") and o.TypeId != "App::DocumentObjectGroup") or \
        getattr(o, "FwKind", "") == "FwAssembly"


def components(objs):
    ""


    import Part
    out = []
    for o in objs:
        if o is None:
            continue
        kids = []
        if _is_container(o) or (o.TypeId == "App::Link" and _is_container(getattr(o, "LinkedObject", None) or o)):
            root = o
            group = o.Group if hasattr(o, "Group") else getattr(o.LinkedObject, "Group", [])
            for c in group:
                if c.TypeId.startswith("Assembly::") and "Joint" in c.TypeId or c.TypeId in (
                        "Assembly::JointGroup", "Assembly::ViewGroup", "Assembly::BomGroup", "App::Origin"):
                    continue
                if not hasattr(c, "Shape") and c.TypeId != "App::Link":
                    continue
                try:
                    sh = Part.getShape(root, c.Name + ".", transform=True)
                except Exception:
                    sh = None
                if sh is None or sh.isNull():
                    continue
                kids.append(c)
                linked = getattr(c, "LinkedObject", None) if c.TypeId == "App::Link" else None
                part = linked.Name if linked is not None else c.Name
                out.append({"name": c.Name, "label": c.Label, "part": part, "shape": sh})
        if not kids:
            try:
                sh = o.Shape.copy()
            except Exception:
                continue
            if sh.isNull():
                continue
            out.append({"name": o.Name, "label": o.Label, "part": o.Name, "shape": sh})
    return out


def is_fastener(c):
    t = (c.get("label", "") + " " + c.get("part", "")).lower()
    return any(w in t for w in FASTENER_WORDS)


# --------------------------------------------------------------------------- Removed Section, Broken-out Section
class DrawingShape:
    """A shape the drawing makes from the model, kept up to date with it: a Removed Section's slice, or the model
    with a Broken-out Section's pocket taken out."""

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        props = (("App::PropertyXLinkList", "Base", "the model"), ("App::PropertyString", "Kind", "Slice or BrokenOut"),
                 ("App::PropertyVector", "Origin", "plane point"), ("App::PropertyVector", "Normal", "plane normal"),
                 ("App::PropertyVector", "AxisU", "view X"), ("App::PropertyVector", "AxisV", "view Y"),
                 ("App::PropertyFloatList", "Rect", "u0 v0 u1 v1 about Origin"),
                 ("App::PropertyFloat", "Depth", "broken-out depth"),
                 ("App::PropertyVectorList", "Profile", "closed sketch (u v about Origin) instead of Rect"),
                 ("App::PropertyStringList", "Names", "Section Scope: the components left out (ScopeOut: the only "
                                                      "ones kept)"),
                 ("App::PropertyStringList", "Hidden", "Broken-out Section Scope: excluded components not drawn"))
        for kind, name, tip in props:
            if not hasattr(obj, name):
                obj.addProperty(kind, name, "FreeCAD", tip)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def execute(self, obj):
        import Part
        shapes = []
        names = set(getattr(obj, "Names", []) or [])
        kept = []                  # Broken-out Section Scope: the excluded components, drawn whole
        if names or obj.Kind in ("ScopeIn", "ScopeOut"):
            # Section Scope: the model by component, the excluded ones left out (or, for ScopeOut, kept alone)
            keep_out = obj.Kind == "ScopeOut"
            hidden = set(getattr(obj, "Hidden", []) or [])
            for c in components(obj.Base or []):
                if (c["name"] in names) == keep_out:
                    shapes.append(c["shape"])
                elif obj.Kind == "BrokenOut" and c["name"] not in hidden:
                    kept.append(c["shape"])
        else:
            for o in obj.Base or []:
                try:
                    shapes.append(o.Shape.copy())
                except Exception as _fw_err:
                    _fw_log("drawviews.py:3194", _fw_err)
        shapes = [x for x in shapes if not x.isNull()]
        if not shapes:
            obj.Shape = Part.makeCompound(kept) if kept else Part.Shape()
            return
        if obj.Kind in ("ScopeIn", "ScopeOut"):
            obj.Shape = shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes)
            return
        if obj.Kind == "Solids":
            # Section View > Surface Bodies off: the surface bodies left out of the section
            solids = [so for sh in shapes for so in sh.Solids]
            obj.Shape = Part.makeCompound(solids) if solids else Part.Shape()
            return
        try:
            whole = shapes[0] if len(shapes) == 1 else shapes[0].fuse(shapes[1:])
        except Exception:
            whole = Part.makeCompound(shapes)         # a solid with surface bodies need not fuse
        L = max(10.0, whole.BoundBox.DiagonalLength) * 2.0
        n = D._unit(obj.Normal)
        a, b = D._unit(obj.AxisU), D._unit(obj.AxisV)
        m = App.Matrix(a.x, b.x, n.x, 0, a.y, b.y, n.y, 0, a.z, b.z, n.z, 0, 0, 0, 0, 1)
        rot = App.Rotation(m)
        if obj.Kind == "Mirror":
            # Mirror view: the model mirrored in the plane through Origin square to Normal
            obj.Shape = whole.mirror(obj.Origin, n)
            return
        if obj.Kind == "Partial":
            # Partial section: only the material across from the cutting line's own length (Rect u0 u1 along AxisU)
            u0, u1 = sorted(list(obj.Rect)[:2])
            box = Part.makeBox(max(0.01, u1 - u0), 2 * L, 2 * L)
            box.Placement = App.Placement(obj.Origin + rot.multVec(V(u0, -L, -L)), rot)
            obj.Shape = whole.common(box)
            return
        if obj.Kind == "Depth":
            # Section Depth: only the material from the cut plane back by Depth (Normal looks at the viewer)
            # TechDraw takes away what lies towards the viewer: keep the cut plane (a sliver past it) back by Depth
            d = max(0.01, obj.Depth)
            box = Part.makeBox(2 * L, 2 * L, d + 0.05)
            box.Placement = App.Placement(obj.Origin + rot.multVec(V(-L, -L, -d)), rot)
            obj.Shape = whole.common(box)
            return
        if obj.Kind == "Cut":
            # a broken section view: the model as its section cuts it (the side away from Normal kept)
            box = Part.makeBox(2 * L, 2 * L, 2 * L)
            box.Placement = App.Placement(obj.Origin + rot.multVec(V(-L, -L, -2 * L)), rot)
            obj.Shape = whole.common(box)
            return
        if obj.Kind == "Slice":
            t = 0.02
            box = Part.makeBox(2 * L, 2 * L, t)
            box.Placement = App.Placement(obj.Origin + rot.multVec(V(-L, -L, -t / 2)), rot)
            obj.Shape = whole.common(box)
        elif obj.Kind == "Half":
            # a half section: the quarter towards the viewer on the cut side taken out back to the plane at Origin
            u0, v0, u1, v1 = list(obj.Rect)[:4]
            front = max(n.dot(v.Point - obj.Origin) for v in whole.Vertexes) + 0.01
            box = Part.makeBox(abs(u1 - u0), abs(v1 - v0), front)
            box.Placement = App.Placement(obj.Origin + rot.multVec(V(min(u0, u1), min(v0, v1), 0)), rot)
            obj.Shape = whole.cut(box)
        else:
            u0, v0, u1, v1 = list(obj.Rect)[:4]
            depth = max(0.01, obj.Depth)
            # from the front of the model (towards the viewer) back by depth
            front = max(n.dot(v.Point - obj.Origin) for v in whole.Vertexes) + 0.01
            prof = list(getattr(obj, "Profile", []) or [])
            if len(prof) >= 3:
                wire = Part.makePolygon([V(q.x, q.y, 0) for q in prof] + [V(prof[0].x, prof[0].y, 0)])
                box = Part.Face(wire).extrude(V(0, 0, depth + 0.01))
            else:
                box = Part.makeBox(abs(u1 - u0), abs(v1 - v0), depth + 0.01)
                box.translate(V(min(u0, u1), min(v0, v1), 0))
            box.Placement = App.Placement(obj.Origin + rot.multVec(V(0, 0, front - depth)), rot).multiply(box.Placement)
            cut = whole.cut(box)
            obj.Shape = Part.makeCompound([cut] + [k for k in kept if not k.isNull()]) if kept else cut


MIRRORS = ("Horizontal", "Vertical")


def mirror_of(v):
    return getattr(v, "SWMirror", "") or ""


def set_mirror(v, how):
    """Mirror view: how "Horizontal" (left to right) or "Vertical" (top to bottom), "" for none. The view shows a
    mirrored copy of its model that follows it (a drawing shape), in place of the model."""
    doc = v.Document
    cur = mirror_of(v)
    if cur == (how or ""):
        return
    old = next((o for o in list(getattr(v, "Source", []) or []) if getattr(o, "Kind", "") == "Mirror"), None)
    model = list(old.Base) if old is not None else source_shapes(v)
    if old is not None:
        v.Source = [o for o in v.Source if o is not old]
        D.link_source(v, model)
        doc.removeObject(old.Name)
    if "SWMirror" not in v.PropertiesList:
        v.addProperty("App::PropertyString", "SWMirror", "FreeCAD", "Mirror view")
    v.SWMirror = how or ""
    if how:
        d, x, y = D.view_frame(v)
        bb = None
        for o in model:
            try:
                b = o.Shape.BoundBox
                bb = b if bb is None else bb.united(b)
            except Exception as _fw_err:
                _fw_log("drawviews.py:3301", _fw_err)
        centre = bb.Center if bb is not None else V(0, 0, 0)
        m = drawing_shape(doc, model, "Mirror", centre, x if how == "Horizontal" else y, x, y,
                          label="%s mirrored" % v.Label)
        v.XSource = []
        v.Source = [m]
    # TechDraw skips a view's projection while its page is not kept updated (the PC's drawings: Update
    # View off), so the mirrored copy is projected with KeepUpdated on for this one recompute
    page = None
    try:
        page = v.findParentPage() if hasattr(v, "findParentPage") else None
    except Exception:
        page = None
    if page is None:
        page = next((p for p in v.InListRecursive if p.isDerivedFrom("TechDraw::DrawPage")), None)
    keep = getattr(page, "KeepUpdated", True) if page is not None else True
    try:
        if page is not None and not keep:
            page.KeepUpdated = True
        doc.recompute()
        v.touch()
        v.recompute()
        doc.recompute()
    except Exception as _fw_err:
        _fw_log("drawviews.py:3325", _fw_err)
    finally:
        if page is not None and not keep:
            _keep_off_later(page, v)
    _reproject_when_idle(v)


def _reproject_when_idle(v, tries=60):
    """TechDraw skips a view's projection while an earlier one is still running in the background (its execute
    returns at once when waiting for HLR, and the view shows as up to date with the old lines: PC views6, the
    mirrored copy right but the hole not moved). Once the view is idle the projection is run once more."""
    def waiting():
        try:
            return bool(v.isWaitingForHlr()) if hasattr(v, "isWaitingForHlr") else False
        except Exception:
            return False

    try:
        name, dname = v.Name, v.Document.Name
    except Exception:
        return

    def alive():
        """The view and its drawing still there (a drawing closed meanwhile: PC smwuser aborted in close())."""
        try:
            d = App.listDocuments().get(dname)
            return d is not None and d.getObject(name) is not None
        except Exception:
            return False

    def step(n=tries):
        if not alive():
            return
        if waiting() and n > 0:
            QtCore.QTimer.singleShot(250, lambda: step(n - 1))
            return
        try:
            v.touch()
            v.recompute()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: re-projecting %s: %s\n" % (getattr(v, "Name", "?"), error))
    QtCore.QTimer.singleShot(500, step)


def project_now(page, views, doc=None):
    """Recompute with the views projected even on a page that is not kept updated (Update View off): the page
    is kept updated for this, and turned back once the views are projected."""
    doc = doc or (views[0].Document if views else page.Document)
    keep = getattr(page, "KeepUpdated", True) if page is not None else True
    try:
        if page is not None and not keep:
            page.KeepUpdated = True
            for v in views:
                v.touch()
        doc.recompute()
    finally:
        if page is not None and not keep and views:
            _keep_off_later(page, views[-1])


def _keep_off_later(page, v, tries=60):
    """Turns the page's KeepUpdated off again once the view's lines are back. TechDraw projects in the
    background with the GUI up (the PC), and turning it off at once dropped the mirrored projection; on the PC
    isWaitingForHlr was still False at the first look (the projection had not started), so the page stays kept
    updated for at least 3 s and until the view has been idle for 3 looks in a row (15 s at most)."""
    idle = [0]
    try:
        names = (page.Document.Name, page.Name, v.Name)
    except Exception:
        return

    def alive():                # the drawing closed meanwhile: leave it alone
        try:
            d = App.listDocuments().get(names[0])
            return d is not None and d.getObject(names[1]) is not None and d.getObject(names[2]) is not None
        except Exception:
            return False

    def busy():
        try:
            if hasattr(v, "isWaitingForHlr") and v.isWaitingForHlr():
                return True
            return "Touched" in list(getattr(v, "State", []) or [])
        except Exception as _fw_err:
            _fw_log("drawviews.py:3391", _fw_err)
            return False

    def step(n=tries):
        if not alive():
            return
        idle[0] = 0 if busy() else idle[0] + 1
        if n > 0 and (tries - n < 12 or idle[0] < 3):
            QtCore.QTimer.singleShot(250, lambda: step(n - 1))
            return
        try:
            if not busy():
                page.KeepUpdated = False
            else:
                App.Console.PrintLog("FreeCAD: mirror view: page left kept updated (view still projecting)\n")
        except Exception as _fw_err:
            _fw_log("drawviews.py:3396", _fw_err)
    QtCore.QTimer.singleShot(250, step)


def set_section_depth(s, depth):
    """Section Depth: the section shows only what lies within depth (model mm) behind its cut plane; 0 or None
    shows all of it. TechDraw cuts its base view's model, so the section is cut from a hidden twin of the base
    view that shows only that slab; the cutting line is drawn on the real base view."""
    if "SWSectionDepth" not in s.PropertiesList:
        s.addProperty("App::PropertyFloat", "SWSectionDepth", "FreeCAD", "Section Depth (0: all)")
    s.SWSectionDepth = float(depth or 0.0)
    _rebuild_twin(s)


def section_scope(s):
    """(excluded component names, the excluded ones not drawn) of a section view."""
    return (list(getattr(s, "SWSectionScope", []) or []), list(getattr(s, "SWSectionScopeHidden", []) or []))


def set_section_scope(s, excluded, hidden=()):
    ""



    for name, tip in (("SWSectionScope", "Section Scope: components excluded from the section"),
                      ("SWSectionScopeHidden", "excluded components not shown (Show excluded fasteners off)")):
        if name not in s.PropertiesList:
            s.addProperty("App::PropertyStringList", name, "FreeCAD", tip)
    s.SWSectionScope = list(excluded or [])
    s.SWSectionScopeHidden = [n for n in (hidden or ()) if n in (excluded or [])]
    _rebuild_twin(s)


def scope_overlay(s):
    page = next((o for o in s.InList if o.TypeId == "TechDraw::DrawPage"), None)
    for o in (list(page.Views) if page is not None else []):
        if getattr(o, "SWScopeOverlayOf", "") == s.Name:
            return o
    return None


def _cut_piece_centre(shape, origin, normal):
    """The box centre of what a section keeps of shape (TechDraw centres a section on it): the side of the plane
    away from the normal."""
    import Part
    bb = shape.BoundBox
    L = max(10.0, bb.DiagonalLength) * 2.0
    n = D._unit(normal)
    a = D._unit(n.cross(V(0, 0, 1)) if abs(n.z) < 0.9 else n.cross(V(1, 0, 0)))
    b = n.cross(a)
    m = App.Matrix(a.x, b.x, n.x, 0, a.y, b.y, n.y, 0, a.z, b.z, n.z, 0, 0, 0, 0, 1)
    box = Part.makeBox(2 * L, 2 * L, L)
    box.Placement = App.Placement(V(origin) + App.Rotation(m).multVec(V(-L, -L, -L)), App.Rotation(m))
    try:
        piece = shape.common(box)
        if not piece.isNull() and piece.BoundBox.isValid():
            return piece.BoundBox.Center
    except Exception as _fw_err:
        _fw_log("drawviews.py:3454", _fw_err)
    return bb.Center


def _rebuild_twin(s):
    """The hidden twin base view a section is cut from (Section Depth, Section Scope), its cutting line on the
    real base view and the Section Scope overlay: made again from the section's settings."""
    from . import drawannot as DA
    doc = s.Document
    page = next((o for o in s.InList if o.TypeId == "TechDraw::DrawPage"), None)
    twin = s.BaseView if getattr(s.BaseView, "SWDepthTwinOf", "") else None
    real = doc.getObject(twin.SWDepthTwinOf) if twin is not None else s.BaseView
    if twin is not None:
        s.BaseView = real
        olds, todo = [], [o for o in list(twin.Source)]
        while todo:                               # the chain of drawing shapes the twin shows (Depth, Partial...)
            o = todo.pop()
            if getattr(o, "Kind", "") in ("Depth", "ScopeIn", "Partial", "Solids") and o not in olds:
                olds.append(o)
                todo += [b for b in (getattr(o, "Base", None) or [])]
        twin.Source = []
        doc.removeObject(twin.Name)
        for o in olds:
            try:
                o.Base = []
            except Exception as _fw_err:
                _fw_log("drawviews.py:3480", _fw_err)
        for o in olds:
            doc.removeObject(o.Name)
    if page is not None:
        for o in list(page.Views):
            if getattr(o, "SWDepthLineOf", "") == s.Name:
                doc.removeObject(o.Name)
        ov = scope_overlay(s)
        if ov is not None:
            olds = [o for o in list(ov.Source) if getattr(o, "Kind", "") == "ScopeOut"]
            ov.Source = []
            doc.removeObject(ov.Name)
            for o in olds:
                doc.removeObject(o.Name)
    depth = float(getattr(s, "SWSectionDepth", 0.0) or 0.0)
    excluded, hidden = section_scope(s)
    span = list(getattr(s, "SWPartialSpan", []) or [])
    partial = bool(getattr(s, "SWPartialSection", False)) and len(span) == 2
    solids_only = not bool(getattr(s, "SWDisplaySurfaceBodies", True))
    if (not depth and not excluded and not partial and not solids_only) or real is None or page is None:
        project_now(page, [s], doc) if page is not None else doc.recompute()
        auto_hatch(s)
        return
    n = D._unit(V(s.SectionNormal))
    d, x, y = D.view_frame(s)
    model = source_shapes(real)
    m = None
    if depth:
        m = drawing_shape(doc, model, "Depth", V(s.SectionOrigin), n, x, y, depth=depth,
                          label="%s depth" % s.Label)
        if excluded:
            m.Names = excluded
            m.recompute()
    elif excluded:
        m = drawing_shape(doc, model, "ScopeIn", V(s.SectionOrigin), n, x, y, label="%s scope" % s.Label)
        m.Names = excluded
        m.recompute()
    if solids_only:
        m = drawing_shape(doc, [m] if m is not None else model, "Solids", V(s.SectionOrigin), n, x, y,
                          label="%s solids" % s.Label)
    if partial:
        along = D._unit(V(s.SWPartialAxis)) if "SWPartialAxis" in s.PropertiesList else x
        side = D._unit(n.cross(along))
        m = drawing_shape(doc, [m] if m is not None else model, "Partial", V(s.SectionOrigin), n, along, side,
                          rect=span, label="%s partial" % s.Label)
    tw = doc.addObject("TechDraw::DrawViewPart", "SectionDepthBase")
    page.addView(tw)
    tw.Source = [m]
    tw.Direction, tw.XDirection = real.Direction, real.XDirection
    tw.ScaleType = "Custom"
    tw.Scale = view_scale(real)
    tw.X, tw.Y = real.X, real.Y
    tw.addProperty("App::PropertyString", "SWDepthTwinOf", "FreeCAD", "the base view this hidden twin stands for")
    tw.SWDepthTwinOf = real.Name
    try:
        tw.ViewObject.Visibility = False
    except Exception as _fw_err:
        _fw_log("drawviews.py:3537", _fw_err)
    s.BaseView = tw
    # the excluded components, whole, where the section draws the model
    shown = [c for c in excluded if c not in hidden]
    if excluded and shown:
        try:
            out = drawing_shape(doc, model, "ScopeOut", V(s.SectionOrigin), n, x, y,
                                label="%s excluded" % s.Label)
            out.Names = shown
            out.recompute()
            if not out.Shape.isNull():
                from . import newdoc
                newdoc._serial_projections()
                ov = doc.addObject("TechDraw::DrawViewPart", "SectionScopeView")
                page.addView(ov)
                ov.Source = [out]
                ov.Direction, ov.XDirection = V(s.Direction), V(s.XDirection)
                ov.ScaleType = "Custom"
                ov.Scale = float(s.Scale)
                ov.Label = "%s excluded components" % s.Label
                ov.addProperty("App::PropertyString", "SWScopeOverlayOf", "FreeCAD", "its section view")
                ov.SWScopeOverlayOf = s.Name
                try:
                    D.set_display_style(ov, getattr(s, "SWDisplayStyle", "") or "Hidden Lines Removed")
                except Exception as _fw_err:
                    _fw_log("drawviews.py:3562", _fw_err)
                c_in = _cut_piece_centre(m.Shape, V(s.SectionOrigin), n) if not m.Shape.isNull() else V()
                c_out = out.Shape.BoundBox.Center
                vd, vx = D._unit(V(s.Direction)), D._unit(V(s.XDirection))
                vy = vd.cross(vx)
                k = float(s.Scale)
                dx, dy = (c_out - c_in).dot(vx) * k, (c_out - c_in).dot(vy) * k
                ov.setExpression("X", "%s.X + %r mm" % (s.Name, round(dx, 6)))
                ov.setExpression("Y", "%s.Y + %r mm" % (s.Name, round(dy, 6)))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: section scope: %s\n" % error)
    # the cutting line on the real base view
    try:
        k = view_scale(real)
        o2 = DA._project(real, V(s.SectionOrigin))
        a, b, c, e = view_box(real)
        dn = DA._project(real, V(s.SectionOrigin) + n)
        nx, ny = dn.x - o2.x, dn.y - o2.y
        L = math.hypot(nx, ny) or 1.0
        ux, uy = -ny / L, nx / L
        half = math.hypot(c - a, e - b) / 2 + 3
        x0, y0 = D.view_position(real)
        cx, cy = x0 + o2.x * k, y0 + o2.y * k
        body = ('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="0.5" '
                'stroke-dasharray="8 1.5 1.5 1.5"/>' % (-ux * half, uy * half, ux * half, -uy * half))
        for sg in (1, -1):
            body += ('<text x="%g" y="%g" font-family="osifont, Arial" font-size="5" text-anchor="middle">%s</text>'
                     % (sg * ux * (half + 3), -sg * uy * (half + 3), s.SectionSymbol))
        line = DA.svg_symbol(page, "SectionLine", body, half + 6, (cx, cy), "Section Line %s-%s" % (
            s.SectionSymbol, s.SectionSymbol), "SectionLine")
        line.addProperty("App::PropertyString", "SWDepthLineOf", "FreeCAD", "its section view")
        line.SWDepthLineOf = s.Name
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: section depth line: %s\n" % error)
    project_now(page, [tw, s], doc)       # the twin and the section, also on a page with Update View off
    auto_hatch(s)



AUTO_HATCH_STEPS = ((45.0, 1.0), (135.0, 1.0), (45.0, 0.5), (135.0, 0.5), (45.0, 0.25), (135.0, 0.25),
                    (45.0, 2.0), (135.0, 2.0))
AUTO_HATCH_GAP = 2.5          # mm between hatch lines on the sheet at step scale 1


def auto_hatch_of(s):
    page = next((o for o in s.InList if o.TypeId == "TechDraw::DrawPage"), None)
    return [o for o in (list(page.Views) if page is not None else []) if getattr(o, "SWAutoHatchOf", "") == s.Name]


def set_auto_hatch(s, on):
    if "SWAutoHatch" not in s.PropertiesList:
        s.addProperty("App::PropertyBool", "SWAutoHatch", "FreeCAD", "Auto hatching (per component)")
    s.SWAutoHatch = bool(on)
    auto_hatch(s)


def _cut_faces(shape, origin, n):
    """The faces a section cuts out of shape: on the cut plane, of the part it keeps."""
    import Part
    bb = shape.BoundBox
    L = max(10.0, bb.DiagonalLength) * 2.0
    a = D._unit(n.cross(V(0, 0, 1)) if abs(n.z) < 0.9 else n.cross(V(1, 0, 0)))
    b = n.cross(a)
    m = App.Matrix(a.x, b.x, n.x, 0, a.y, b.y, n.y, 0, a.z, b.z, n.z, 0, 0, 0, 0, 1)
    box = Part.makeBox(2 * L, 2 * L, L)
    box.Placement = App.Placement(V(origin) + App.Rotation(m).multVec(V(-L, -L, -L)), App.Rotation(m))
    try:
        piece = shape.common(box)
    except Exception:
        return []
    out = []
    for f in piece.Faces:
        try:
            if type(f.Surface).__name__ != "Plane":
                continue
            if abs(abs(D._unit(f.Surface.Axis).dot(n)) - 1.0) > 1e-6:
                continue
            if abs((f.Vertexes[0].Point - V(origin)).dot(n)) > 1e-4:
                continue
            out.append(f)
        except Exception as _fw_err:
            _fw_log("drawviews.py:3643", _fw_err)
    return out


def hatch_segments(polys, angle, gap, shift=0.0):
    """Hatch lines at angle (degrees), gap apart (moved on by shift gaps), cut to the area inside polys (even-odd):
    [((x0, y0), (x1, y1))]."""
    a = math.radians(angle)
    ux, uy = math.cos(a), math.sin(a)
    nx, ny = -uy, ux
    edges = []
    for pts in polys:
        for i in range(len(pts)):
            p, q = pts[i], pts[(i + 1) % len(pts)]
            if p != q:
                edges.append((p, q))
    if not edges:
        return []
    offs = [p[0] * nx + p[1] * ny for e in edges for p in e]
    lo, hi = min(offs), max(offs)
    out = []
    j = math.floor(lo / gap)
    while j * gap <= hi:
        o = (j + shift) * gap + gap * 1e-3
        ts = []
        for p, q in edges:
            dp, dq = p[0] * nx + p[1] * ny - o, q[0] * nx + q[1] * ny - o
            if (dp < 0) != (dq < 0):
                t = dp / (dp - dq)
                x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
                ts.append(x * ux + y * uy)
        ts.sort()
        for t0, t1 in zip(ts[0::2], ts[1::2]):
            out.append(((nx * o + ux * t0, ny * o + uy * t0), (nx * o + ux * t1, ny * o + uy * t1)))
        j += 1
    return out


def _keep_hatch_off(dname, name):
    try:
        s = App.getDocument(dname).getObject(name)
    except Exception:
        return
    if s is not None and getattr(s, "SWAutoHatch", False) and s.CutSurfaceDisplay != "Hide":
        if not getattr(s, "SWCutSurfaceBefore", ""):
            s.SWCutSurfaceBefore = s.CutSurfaceDisplay
        s.CutSurfaceDisplay = "Hide"
        s.Document.recompute()


def auto_hatch(s):
    """Auto hatching on a section: the section's own hatch is turned off and each cut component gets a hatch of
    its own (by component order: 45°, 135°, then closer lines), drawn on the sheet where TechDraw draws the cut
    and following the section (X/Y expressions). Off: the section's own hatch again."""
    doc = s.Document
    for o in auto_hatch_of(s):
        doc.removeObject(o.Name)
    on = bool(getattr(s, "SWAutoHatch", False))
    if not on:
        before = getattr(s, "SWCutSurfaceBefore", "")
        if before and s.CutSurfaceDisplay != before:
            s.CutSurfaceDisplay = before
        return
    page = next((o for o in s.InList if o.TypeId == "TechDraw::DrawPage"), None)
    twin = s.BaseView if getattr(s.BaseView, "SWDepthTwinOf", "") else None
    real = doc.getObject(twin.SWDepthTwinOf) if twin is not None else s.BaseView
    if page is None or real is None:
        return
    import Part
    excluded = set(section_scope(s)[0])
    comps = [c for c in components(source_shapes(real)) if c["name"] not in excluded]
    if not comps:
        return
    origin, n = V(s.SectionOrigin), D._unit(V(s.SectionNormal))
    depth = float(getattr(s, "SWSectionDepth", 0.0) or 0.0)
    whole = twin.Source[0].Shape if twin is not None and twin.Source else Part.makeCompound([c["shape"] for c in comps])
    centre = _cut_piece_centre(whole, origin, n)
    vd, vx = D._unit(V(s.Direction)), D._unit(V(s.XDirection))
    vy = vd.cross(vx)
    k = float(s.Scale)
    if "SWCutSurfaceBefore" not in s.PropertiesList:
        s.addProperty("App::PropertyString", "SWCutSurfaceBefore", "FreeCAD", "the hatch before Auto hatching")
    if s.CutSurfaceDisplay != "Hide":
        s.SWCutSurfaceBefore = s.CutSurfaceDisplay
        s.CutSurfaceDisplay = "Hide"
    # a new section gets System Options' Area Hatch/Fill just after it is made: the section's own hatch stays off
    QtCore.QTimer.singleShot(60, lambda n=s.Name, d=doc.Name: _keep_hatch_off(d, n))
    from . import drawannot as DA
    for i, c in enumerate(comps):
        faces = _cut_faces(c["shape"], origin, n)
        if not faces:
            continue
        angle, step = AUTO_HATCH_STEPS[i % len(AUTO_HATCH_STEPS)]
        if bool(getattr(s, "SWAutoHatchRandom", False)):
            import random                         # Randomize scale: each component's lines a little closer or wider
            step *= random.Random(c["label"]).uniform(0.6, 1.6)
        polys, xs, ys = [], [], []
        for f in faces:
            for w in f.Wires:
                pts = [((q - centre).dot(vx) * k, (q - centre).dot(vy) * k) for q in w.discretize(Deflection=0.02)]
                xs += [p[0] for p in pts]
                ys += [p[1] for p in pts]
                polys.append(pts)
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        R = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 * 1.5 + 1
        gap = AUTO_HATCH_GAP * step
        segs = hatch_segments(polys, angle, gap)
        # SVG Tiny (TechDraw's symbols) has no clipPath: the lines are cut to the faces here (y down in SVG)
        body = ('<path d="%s" stroke="#000" stroke-width="0.18" fill="none"/>' % " ".join(
            "M%g %g L%g %g" % (p0[0] - cx, -(p0[1] - cy), p1[0] - cx, -(p1[1] - cy)) for p0, p1 in segs))
        h = DA.svg_symbol(page, "AutoHatch", body, R, (float(s.X) + cx, float(s.Y) + cy),
                          "%s hatch %s" % (s.Label, c["label"]), "AutoHatch")
        h.addProperty("App::PropertyString", "SWAutoHatchOf", "FreeCAD", "its section view")
        h.SWAutoHatchOf = s.Name
        h.addProperty("App::PropertyString", "SWAutoHatchComponent", "FreeCAD", "the component it hatches")
        h.SWAutoHatchComponent = c["name"]
        h.addProperty("App::PropertyFloat", "SWAutoHatchAngle", "FreeCAD", "hatch angle")
        h.SWAutoHatchAngle = angle
        h.addProperty("App::PropertyFloat", "SWAutoHatchGap", "FreeCAD", "hatch line spacing (sheet mm)")
        h.SWAutoHatchGap = gap
        h.setExpression("X", "%s.X + %r mm" % (s.Name, round(cx, 6)))
        h.setExpression("Y", "%s.Y + %r mm" % (s.Name, round(cy, 6)))
    for dt in [o for o in list(page.Views) if o.TypeId == "TechDraw::DrawViewDetail" and o.BaseView == s]:
        _hatch_detail(dt, s, comps, origin, n, centre, vx, vy, page)
    doc.recompute()


def _hatch_detail(dt, s, comps, origin, n, centre, vx, vy, page):
    ""


    import Part
    from . import drawannot as DA
    doc = s.Document
    for o in auto_hatch_of(dt):
        doc.removeObject(o.Name)
    ax, ay = float(dt.AnchorPoint.x), float(dt.AnchorPoint.y)
    r = float(getattr(dt.Radius, "Value", dt.Radius))
    kd = float(dt.Scale)
    if r <= 0 or kd <= 0:
        return
    at = V(centre) + vx * ax + vy * ay
    for i, c in enumerate(comps):
        faces = _cut_faces(c["shape"], origin, n)
        if not faces:
            continue
        L = max(10.0, c["shape"].BoundBox.DiagonalLength) * 4.0
        cyl = Part.makeCylinder(r, L, V(at) - n * (L / 2.0), n)
        polys, xs, ys = [], [], []
        for f in faces:
            try:
                part = f.common(cyl)
            except Exception:
                continue
            for g in part.Faces:
                for w in g.Wires:
                    pts = [((q - at).dot(vx) * kd, (q - at).dot(vy) * kd) for q in w.discretize(Deflection=0.01)]
                    xs += [p[0] for p in pts]
                    ys += [p[1] for p in pts]
                    polys.append(pts)
        if not polys:
            continue
        angle, step = AUTO_HATCH_STEPS[i % len(AUTO_HATCH_STEPS)]
        if bool(getattr(s, "SWAutoHatchRandom", False)):
            import random
            step *= random.Random(c["label"]).uniform(0.6, 1.6)
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        R = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 * 1.5 + 1
        gap = AUTO_HATCH_GAP * step
        segs = hatch_segments(polys, angle, gap)
        body = ('<path d="%s" stroke="#000" stroke-width="0.18" fill="none"/>' % " ".join(
            "M%g %g L%g %g" % (p0[0] - cx, -(p0[1] - cy), p1[0] - cx, -(p1[1] - cy)) for p0, p1 in segs))
        h = DA.svg_symbol(page, "AutoHatch", body, R, (float(dt.X) + cx, float(dt.Y) + cy),
                          "%s hatch %s" % (dt.Label, c["label"]), "AutoHatch")
        h.addProperty("App::PropertyString", "SWAutoHatchOf", "FreeCAD", "its section view")
        h.SWAutoHatchOf = dt.Name
        h.addProperty("App::PropertyString", "SWAutoHatchComponent", "FreeCAD", "the component it hatches")
        h.SWAutoHatchComponent = c["name"]
        h.addProperty("App::PropertyFloat", "SWAutoHatchAngle", "FreeCAD", "hatch angle")
        h.SWAutoHatchAngle = angle
        h.addProperty("App::PropertyFloat", "SWAutoHatchGap", "FreeCAD", "hatch line spacing (sheet mm)")
        h.SWAutoHatchGap = gap
        h.setExpression("X", "%s.X + %r mm" % (dt.Name, round(cx, 6)))
        h.setExpression("Y", "%s.Y + %r mm" % (dt.Name, round(cy, 6)))


def drawing_shape(doc, base_shapes, kind, origin, normal, u, v, rect=(), depth=0.0, label=""):
    o = doc.addObject("Part::FeaturePython", "FWDrawingShape")
    DrawingShape(o)
    o.Base = list(base_shapes)
    o.Kind = kind
    o.Origin, o.Normal, o.AxisU, o.AxisV = origin, normal, u, v
    o.Rect = list(rect)
    o.Depth = depth
    o.Label = label or kind
    try:
        o.ViewObject.Proxy = 0
        o.ViewObject.Visibility = False
    except Exception as _fw_err:
        _fw_log("drawviews.py:3781", _fw_err)
    o.recompute()
    return o


def make_removed_section(page, base, line, at, label=None):
    """Removed Section: the slice of base along the cutting line between two picked points, square to it."""
    doc = page.Document
    mid = ((line[0][0] + line[1][0]) / 2.0, (line[0][1] + line[1][1]) / 2.0)
    side = (at[0] - mid[0], at[1] - mid[1])
    nd, xdir, normal = section_frame(base, "Auxiliary", line, side, D.third_angle(page))
    label = label or take_label(page)
    origin = to_model(base, mid)
    up = D._unit(nd.cross(xdir))
    sl = drawing_shape(doc, source_shapes(base), "Slice", origin, nd, xdir, up, label="Removed Section %s" % label)
    from . import newdoc
    newdoc._serial_projections()
    v = doc.addObject("TechDraw::DrawViewPart", "RemovedSection")
    page.addView(v)
    v.Source = [sl]
    v.Direction, v.XDirection = nd, xdir
    v.ScaleType = "Custom"
    v.Scale = view_scale(base)
    v.X, v.Y = at
    v.Label = "Section View %s-%s" % (label, label)
    v.addProperty("App::PropertyString", "SectionSymbol", "FreeCAD", "Section label")
    v.SectionSymbol = label
    doc.recompute()
    return v


class RemovedSectionPanel(D._Panel):
    ""


    TITLE = "Removed Section"
    PIXMAP = "TechDraw_SectionView"

    def build(self):
        self.say("Click on one edge of the view, then on the opposite edge, then click to place the section.")
        box, lay = D._group("Edges", self.form)
        self.edge1 = QtWidgets.QLineEdit("", box)
        self.edge1.setObjectName("SWRemovedEdge")
        self.edge1.setReadOnly(True)
        self.edge1.setPlaceholderText("Edge")
        self.edge2 = QtWidgets.QLineEdit("", box)
        self.edge2.setObjectName("SWRemovedOppositeEdge")
        self.edge2.setReadOnly(True)
        self.edge2.setPlaceholderText("Opposite edge")
        lay.addWidget(self.edge1)
        lay.addWidget(self.edge2)
        self.lay.addWidget(box)
        box, lay = D._group("Cutting Line Placement", self.form)
        row = QtWidgets.QHBoxLayout()
        self.auto = QtWidgets.QRadioButton("Auto", box)
        self.auto.setObjectName("SWRemovedAuto")
        self.manual = QtWidgets.QRadioButton("Manual", box)
        self.manual.setObjectName("SWRemovedManual")
        self.auto.setChecked(True)
        row.addWidget(self.auto)
        row.addWidget(self.manual)
        lay.addLayout(row)
        self.lay.addWidget(box)
        box, lay = D._group("Section View", self.form)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Label:", box))
        self.label = QtWidgets.QLineEdit(_peek_label(self.page), box)
        self.label.setObjectName("SWRemovedLabel")
        row.addWidget(self.label)
        lay.addLayout(row)
        self.lay.addWidget(box)
        self.points = []
        self.hits = []
        self.base = None
        self.view = None

    def _edge(self, v, p):
        from . import drawannot as DA
        k = view_scale(v)
        try:
            return DA.edge_at(v, to_geometry(v, p), 3.0 / k)
        except Exception:
            return None

    def auto_line(self):
        """Auto: from the first click square to its edge, to where that line meets the opposite edge (sheet)."""
        import Part
        v = self.base
        (i1, e1), (i2, e2) = self.hits
        g1 = to_geometry(v, self.points[0])
        q = V(g1[0], g1[1], 0)
        try:
            prm = e1.Curve.parameter(q)
            t = e1.tangentAt(prm)
        except Exception:
            t = e1.Vertexes[-1].Point - e1.Vertexes[0].Point
        if t.Length < 1e-12:
            return None
        n = V(-t.y, t.x, 0)
        n.normalize()
        L = 1e4
        ray = Part.makeLine(q - n * L, q + n * L)
        try:
            dist, pts, _info = ray.distToShape(e2)
        except Exception:
            return None
        if dist > 1e-3 * max(1.0, e2.Length):
            return None
        b = pts[0][0]
        a = e1.Curve.value(prm) if hasattr(e1.Curve, "value") else q
        x0, y0 = D.view_position(v)
        k = view_scale(v)
        return (x0 + a.x * k, y0 + a.y * k), (x0 + b.x * k, y0 + b.y * k)

    def sheet_click(self, p):
        if self.view is not None:
            return False
        if not self.points:
            v = view_at(self.page, p)
            if v is None:
                self.say("Click on an edge inside a drawing view.")
                return True
            hit = self._edge(v, p)
            if hit is None and self.auto.isChecked():
                self.say("Click on an edge of the view.")
                return True
            self.base = v
            self.points = [p]
            self.hits = [hit]
            self.edge1.setText("Edge%d of %s" % (hit[0], v.Label) if hit else "%s (%.1f, %.1f)" % (v.Label, p[0], p[1]))
            self.say("Click on the opposite edge.")
            return True
        if len(self.points) == 1:
            if math.hypot(p[0] - self.points[0][0], p[1] - self.points[0][1]) < 0.5:
                return True
            hit = self._edge(self.base, p)
            if self.auto.isChecked() and hit is None:
                self.say("Click on the opposite edge.")
                return True
            self.points.append(p)
            self.hits.append(hit)
            self.edge2.setText("Edge%d of %s" % (hit[0], self.base.Label) if hit else "(%.1f, %.1f)" % p)
            if self.auto.isChecked():
                line = self.auto_line()
                if line is None:
                    self.points, self.hits = self.points[:1], self.hits[:1]
                    self.edge2.setText("")
                    self.say("A line square to the first edge does not reach that edge. Click another opposite edge.")
                    return True
                self.points = list(line)
            self.say("Click to place the section.")
            return True
        label = self.label.text().strip() or None
        if label and label == _peek_label(self.page):
            label = None                      # the sheet's next letter: taken as usual
        self.view = make_removed_section(self.page, self.base, tuple(self.points), p, label)
        self.made.append(self.view)
        QtCore.QTimer.singleShot(0, self.accept)
        return True


def make_broken_out_profile(page, base, poly, depth):
    """Broken-out Section of a closed sketch: poly in view geometry."""
    xs, ys = [q[0] for q in poly], [q[1] for q in poly]
    x0, y0 = D.view_position(base)
    k = view_scale(base)
    bo = make_broken_out(page, base, (x0 + min(xs) * k, y0 + min(ys) * k), (x0 + max(xs) * k, y0 + max(ys) * k), depth)
    bo.Profile = [V(q[0], q[1], 0) for q in poly]
    bo.recompute()
    page.Document.recompute()
    return bo


def _shape_swapped(view):
    try:
        from . import drawmaint
        drawmaint.shape_swapped(view)
    except Exception as _fw_err:
        _fw_log("drawviews.py:shape swapped", _fw_err)


def make_broken_out(page, base, a, b, depth):
    """Broken-out Section: the model's material inside the picked rectangle taken out to depth (from the front)."""
    doc = page.Document
    d, x, y = D.view_frame(base)
    ua, va = to_geometry(base, a)
    ub, vb = to_geometry(base, b)
    origin = model_centre(base)
    src = source_shapes(base)
    bo = drawing_shape(doc, src, "BrokenOut", origin, d, x, y, (ua, va, ub, vb), depth,
                       label="Broken-out Section of %s" % base.Label)
    if not hasattr(base, "SWOriginalSource"):
        base.addProperty("App::PropertyXLinkList", "SWOriginalSource", "FreeCAD", "the model before the break-out")
        base.SWOriginalSource = src
    try:
        before = len(base.getVisibleEdges() or [])
    except Exception:
        before = -1
    _shape_swapped(base)
    base.XSource = []
    base.Source = [bo]
    doc.recompute()
    hatch_broken_out_later(page, base, bo, before)
    return bo


def hatch_broken_out(page, base, bo):
    ""

    from . import drawannot as DA
    doc = page.Document
    for o in [o for o in doc.Objects if getattr(o, "SWHatchView", "") == base.Name and
              getattr(o, "SWBrokenOutHatch", "") == bo.Name]:
        doc.removeObject(o.Name)
    n = D._unit(bo.Normal)
    whole = [o.Shape for o in (bo.Base or []) if hasattr(o, "Shape")]
    if not whole or bo.Shape.isNull():
        return []
    front = max(n.dot(v.Point - bo.Origin) for sh in whole for v in sh.Vertexes) + 0.01
    level = front - max(0.01, bo.Depth)
    faces = [f for f in bo.Shape.Faces if f.Surface.__class__.__name__ == "Plane" and
             abs(abs(f.normalAt(0, 0).dot(n)) - 1) < 1e-6 and abs((f.CenterOfMass - bo.Origin).dot(n) - level) < 1e-4]
    centre = base.projectPoint(model_centre(base))
    pattern = "ANSI31 (Iron BrickStone)"
    made, seen = [], []
    for f in faces:
        u0, u1, v0, v1 = f.ParameterRange
        for a in range(1, 10):
            for b in range(1, 10):
                q = f.valueAt(u0 + (u1 - u0) * a / 10.0, v0 + (v1 - v0) * b / 10.0)
                if not f.isInside(q, 1e-6, True):
                    continue
                p2 = base.projectPoint(q)
                g = (p2.x - centre.x, p2.y - centre.y)
                if any(r.isInside(V(g[0], g[1], 0), 1e-6, True) for r in seen):
                    continue
                region = DA.region_at(base, g)
                if region is None:
                    continue
                seen.append(region)
                body, R, where = DA.hatch_svg(region, base, pattern=pattern)
                h = DA.svg_symbol(page, "AreaHatch", body, R, where, "%s hatch" % bo.Label, "AreaHatch")
                for name, kind, val in (("SWHatchArea", "App::PropertyFloat", region.Area),
                                        ("SWHatchPattern", "App::PropertyString", pattern),
                                        ("SWHatchView", "App::PropertyString", base.Name),
                                        ("SWHatchCentre", "App::PropertyVector", region.CenterOfMass),
                                        ("SWBrokenOutHatch", "App::PropertyString", bo.Name)):
                    h.addProperty(kind, name, "FreeCAD", "broken-out section hatch")
                    setattr(h, name, val)
                made.append(h)
    if made:
        doc.recompute()
    return made


def hatch_broken_out_later(page, base, bo, before=-1, tries=40):
    """Once TechDraw has drawn the view with the break-out (it projects in the background: its lines change)."""
    try:
        now = len(base.getVisibleEdges() or [])
        ready = now > 0 and now != before
    except Exception:
        ready = False
    if not ready and tries > 0:
        QtCore.QTimer.singleShot(250, lambda: hatch_broken_out_later(page, base, bo, before, tries - 1))
        return
    try:
        hatch_broken_out(page, base, bo)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: broken-out hatch: %s\n" % error)


def broken_out_scope(bo):
    return list(getattr(bo, "Names", []) or []), list(getattr(bo, "Hidden", []) or [])


def set_broken_out_scope(bo, excluded, hidden=()):
    ""

    bo.Names = list(excluded or [])
    bo.Hidden = [n for n in (hidden or ()) if n in (excluded or [])]
    bo.recompute()
    views = [v for v in bo.InList if v.isDerivedFrom("TechDraw::DrawViewPart")]
    page = next((p for v in views for p in v.InList if p.TypeId == "TechDraw::DrawPage"), None)
    if page is not None and views:
        project_now(page, views, bo.Document)
    else:
        bo.Document.recompute()
    return bo


class BrokenOutPanel(D._Panel):
    TITLE = "Broken-out Section"
    PIXMAP = "TechDraw_SectionView"

    def build(self):
        self.say("Click two corners of the area to break out, set the Depth, then OK.")
        box, lay = D._group("Depth", self.form)
        self.depth = QtWidgets.QDoubleSpinBox(box)
        self.depth.setObjectName("SWBrokenOutDepth")
        self.depth.setRange(0.01, 100000)
        self.depth.setValue(10.0)
        self.depth.setSuffix("mm")
        self.depth.valueChanged.connect(self.update_depth)
        row = QtWidgets.QHBoxLayout()
        self.ref = QtWidgets.QLineEdit("", box)
        self.ref.setObjectName("SWBrokenOutDepthRef")
        self.ref.setReadOnly(True)
        self.ref.setPlaceholderText("Depth reference: click an edge in another view")
        row.addWidget(self.ref)
        lay.addLayout(row)
        lay.addWidget(self.depth)
        self.preview = QtWidgets.QCheckBox("Preview", box)
        self.preview.setObjectName("SWBrokenOutPreview")
        self.preview.toggled.connect(self.show_preview)
        lay.addWidget(self.preview)
        self.lay.addWidget(box)

        box, lay = D._group("Section Scope", self.form)
        box.setObjectName("SWBrokenOutScopeGroup")
        lay.addWidget(QtWidgets.QLabel("Excluded components:", box))
        self.scope_list = QtWidgets.QListWidget(box)
        self.scope_list.setObjectName("SWBrokenOutScopeList")
        self.scope_list.setMaximumHeight(140)
        lay.addWidget(self.scope_list)
        self.scope_instances = QtWidgets.QCheckBox("Don't cut all instances", box)
        self.scope_instances.setObjectName("SWBrokenOutScopeAllInstances")
        self.scope_fasteners = QtWidgets.QCheckBox("Exclude fasteners", box)
        self.scope_fasteners.setObjectName("SWBrokenOutScopeFasteners")
        self.scope_show_fasteners = QtWidgets.QCheckBox("Show excluded fasteners", box)
        self.scope_show_fasteners.setObjectName("SWBrokenOutScopeShowFasteners")
        self.scope_show_fasteners.setChecked(True)
        for w in (self.scope_instances, self.scope_fasteners, self.scope_show_fasteners):
            lay.addWidget(w)
        self.scope_box = box
        self.scope_comps = []
        self.scope_busy = False
        self.scope_list.itemChanged.connect(self.scope_item_changed)
        self.scope_fasteners.toggled.connect(self.scope_fasteners_changed)
        self.scope_instances.toggled.connect(lambda *_: self.rescope())
        self.scope_show_fasteners.toggled.connect(lambda *_: self.rescope())
        self.lay.addWidget(box)
        box.hide()
        self.first = None
        self.base = None
        self.shape = None

    def show_preview(self, *_):
        ""
        if self.shape is None or self.base is None:
            return
        _shape_swapped(self.base)
        if self.preview.isChecked():
            self.base.XSource = []
            self.base.Source = [self.shape]
        else:
            self.base.Source = []
            D.link_source(self.base, list(getattr(self.base, "SWOriginalSource", []) or []))
        self.doc.recompute()

    def depth_reference(self, p):
        """A click on an edge of another view: the Depth runs from the front of the model to that point."""
        from . import drawannot as DA
        v = view_at(self.page, p)
        if v is None or v is self.base:
            return False
        d, _, _ = D.view_frame(self.base)
        dv, x, y = D.view_frame(v)
        if abs(abs(d.dot(dv)) - 1) < 1e-6:
            self.say("That view looks the same way; click an edge in a view from the side.")
            return True
        g = to_geometry(v, p)
        k = view_scale(v)
        hit = DA.edge_at(v, g, 3.0 / k)
        if hit is not None:
            i, e = hit
            import Part
            pt = Part.Vertex(V(g[0], g[1], 0))
            ends = sorted(e.Vertexes, key=lambda q: (q.Point - pt.Point).Length)
            near = ends[0].Point if ends and (ends[0].Point - pt.Point).Length < 3.0 / k else \
                e.distToShape(pt)[1][0][0]
            g = (near.x, near.y)
            self.ref.setText("Edge%d@%s" % (i, v.Label))
        else:
            self.ref.setText("Point@%s" % v.Label)
        P = model_centre(v) + x * g[0] + y * g[1]
        verts = []
        for o in list(getattr(self.base, "SWOriginalSource", []) or source_shapes(self.base)):
            try:
                verts += [q.Point for q in o.Shape.Vertexes]
            except Exception as _fw_err:
                _fw_log("drawviews.py:4091", _fw_err)
        if not verts:
            return True
        front = max(d.dot(q) for q in verts)
        self.depth.setValue(max(0.01, front - d.dot(P)))
        self.say("Depth %.2f mm from %s. OK when done." % (self.depth.value(), self.ref.text()))
        return True

    def finish(self):
        if self.shape is not None and not self.preview.isChecked():
            self.preview.setChecked(True)

    def sheet_click(self, p):
        if self.shape is not None:
            return self.depth_reference(p)
        if self.first is None:

            # outside the part, inside the view's frame, starts on that view
            v = view_at(self.page, p, 8.0)
            if v is None:
                self.say("Click inside a drawing view for the first corner.")
                return True
            self.base, self.first = v, p
            self.say("Click the opposite corner.")
            return True
        if abs(p[0] - self.first[0]) < 0.5 or abs(p[1] - self.first[1]) < 0.5:
            return True
        self.shape = make_broken_out(self.page, self.base, self.first, p, self.depth.value())
        self.made.append(self.shape)
        self.fill_scope()
        self.show_preview()
        self.say("Set the Depth, or click an edge in another view for the depth reference, then OK.")
        return True

    def fill_scope(self):
        comps = components(list(self.shape.Base or [])) if self.shape is not None else []
        if len(comps) < 2:
            return
        self.scope_comps = comps
        self.scope_busy = True
        self.scope_list.clear()
        for c in comps:
            it = QtWidgets.QListWidgetItem(c["label"], self.scope_list)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Unchecked)
            it.setData(QtCore.Qt.UserRole, c["name"])
        self.scope_busy = False
        self.scope_box.show()

    # the Section View PM's scope list, on the broken-out section
    scope_item_changed = SectionViewPanel.scope_item_changed
    scope_fasteners_changed = SectionViewPanel.scope_fasteners_changed
    scope_names = SectionViewPanel.scope_names

    def rescope(self):
        if self.shape is None or self.scope_busy or not self.scope_comps:
            return
        names = self.scope_names()
        hidden = [] if self.scope_show_fasteners.isChecked() else \
            [c["name"] for c in self.scope_comps if c["name"] in names and is_fastener(c)]
        set_broken_out_scope(self.shape, names, hidden)

    def update_depth(self, *_):
        if self.shape is not None:
            self.shape.Depth = self.depth.value()
            self.shape.recompute()
            self.doc.recompute()


# --------------------------------------------------------------------------- commands
COMMANDS = {
    "FreeWorks_DrawSectionView": ("Section View", "TechDraw_SectionView",
                                  "Adds a section view by cutting the parent view with a cutting line."),
    "FreeWorks_DrawDetailView": ("Detail View", "TechDraw_DetailView",
                                 "Adds a detail view of a circled portion of a view, usually at a larger scale."),
    "FreeWorks_DrawBreak": ("Break View", "TechDraw_BrokenView",
                            "Adds a break line to a selected view."),
    "FreeWorks_DrawCrop": ("Crop View", "TechDraw_ClipGroup",
                           "Crops a view to the area you pick."),
    "FreeWorks_DrawRemoveCrop": ("Remove Crop", "TechDraw_ClipGroupRemove",
                                 "Shows the whole of a cropped view again."),
    "FreeWorks_DrawRemovedSection": ("Removed Section", "TechDraw_SectionView",
                                     "Adds a slice of a view between two opposite edges you pick."),
    "FreeWorks_DrawBrokenOut": ("Broken-out Section", "TechDraw_SectionView",
                                "Removes material to a depth inside an area of a view, to show what is inside."),
    "FreeWorks_DrawEmptyView": ("Empty View", "TechDraw_ClipGroup", "Adds an empty view."),
    "FreeWorks_DrawPredefinedView": ("Predefined View", "TechDraw_View",
                                     "Adds a view with an orientation, its model put in now or later."),
    "FreeWorks_DrawRelativeView": ("Relative View", "TechDraw_View",
                                   "Adds a view oriented by two faces you pick in the model."),
}


class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.pixmap, self.tip = COMMANDS[name]

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": D.pixmap(self.pixmap)}

    def IsActive(self):
        page = D.active_page()
        if page is None or D.busy() or not D.sheet_shown(page):
            return False
        if self.name == "FreeWorks_DrawRemoveCrop":
            return picked_crop() is not None
        if self.name in ("FreeWorks_DrawEmptyView", "FreeWorks_DrawPredefinedView", "FreeWorks_DrawRelativeView",
                         "FreeWorks_DrawBreak", "FreeWorks_DrawCrop"):
            return True
        return bool(D.views_of(page))

    def Activated(self):
        page = D.active_page()
        if page is None:
            return
        D.sheet_defaults(page)
        if self.name == "FreeWorks_DrawRemoveCrop":
            c = picked_crop()
            if c is not None:
                doc = c.Document
                doc.openTransaction("Remove Crop")
                try:
                    remove_crop(c)
                except BaseException:
                    try:
                        doc.abortTransaction()
                    except Exception:
                        pass
                    raise
                doc.commitTransaction()
            return
        if self.name in ("FreeWorks_DrawBreak", "FreeWorks_DrawCrop") and not D.views_of(page):
            D._status("%s: the sheet has no drawing view yet. Add a view first." % COMMANDS[self.name][0])
            return
        if self.name in ("FreeWorks_DrawCrop", "FreeWorks_DrawBrokenOut"):

            try:
                from . import drawsketch
                hit = drawsketch.picked_closed_profile()
            except Exception:
                hit = None
            if hit is not None:
                view, index, poly = hit
                doc = page.Document
                if self.name == "FreeWorks_DrawCrop":
                    xs, ys = [q[0] for q in poly], [q[1] for q in poly]
                    x0, y0 = D.view_position(view)
                    k = view_scale(view)
                    doc.openTransaction("Crop View")
                    try:
                        drawsketch.consume(view, index)
                        clip = make_crop(page, view, (x0 + min(xs) * k, y0 + min(ys) * k),
                                         (x0 + max(xs) * k, y0 + max(ys) * k))
                        crop_mask(page, clip, [(x0 + q[0] * k, y0 + q[1] * k) for q in poly])
                    except BaseException:
                        try:
                            doc.abortTransaction()
                        except Exception:
                            pass
                        raise
                    doc.commitTransaction()
                    doc.recompute()
                    return
                panel = BrokenOutPanel(page)
                drawsketch.consume(view, index)
                panel.base = view
                panel.shape = make_broken_out_profile(page, view, poly, panel.depth.value())
                panel.made.append(panel.shape)
                panel.show_preview()
                panel.say("Set the Depth, then OK.")
                D._show(panel)
                return
        panel = {"FreeWorks_DrawSectionView": SectionViewPanel, "FreeWorks_DrawDetailView": DetailViewPanel,
                 "FreeWorks_DrawBreak": BreakPanel, "FreeWorks_DrawCrop": CropPanel,
                 "FreeWorks_DrawEmptyView": EmptyViewPanel, "FreeWorks_DrawPredefinedView": PredefinedViewPanel,
                 "FreeWorks_DrawRelativeView": RelativeViewPanel,
                 "FreeWorks_DrawRemovedSection": RemovedSectionPanel,
                 "FreeWorks_DrawBrokenOut": BrokenOutPanel}[self.name]
        D._show(panel(page))



# FCPAT.pat has none of them, so a section set to ansi31 drew no hatch at all (first-hour pass, 11-20). Written
# once, in mm (the standard inch definitions times 25.4), into the user's FreeCAD folder.
ANSI_PAT = """;; ANSI hatch patterns (mm), written by FreeCAD drawings
*ansi31, ANSI Iron, Brick, Stone masonry
45, 0,0, 0,3.175
*ansi32, ANSI Steel
45, 0,0, 0,9.525
45, 4.490128,0, 0,9.525, 3.175,-1.5875
*ansi33, ANSI Bronze, Brass, Copper
45, 0,0, 0,6.35
45, 4.490128,0, 0,6.35, 3.175,-1.5875
*ansi34, ANSI Plastic, Rubber
45, 0,0, 0,19.05
45, 4.490128,0, 0,19.05
45, 8.980256,0, 0,19.05
45, 13.470384,0, 0,19.05
*ansi35, ANSI Fire brick, Refractory material
45, 0,0, 0,6.35
45, 4.490128,0, 0,6.35, 7.9375,-1.5875,0,-1.5875
*ansi36, ANSI Marble, Slate, Glass
45, 0,0, 5.55625,3.175, 7.9375,-1.5875,0,-1.5875
*ansi37, ANSI Lead, Zinc, Magnesium, Sound/Heat/Elec Insulation
45, 0,0, 0,3.175
135, 0,0, 0,3.175
*ansi38, ANSI Aluminum
45, 0,0, 0,3.175
135, 0,0, 6.35,3.175, 7.9375,-4.7625
"""
SECTION_TYPES = ("TechDraw::DrawViewSection", "TechDraw::DrawComplexSection")


def ansi_pat_file():
    import os
    path = os.path.join(App.getUserAppDataDir(), "FreeCAD-hatch", "ANSI.pat")
    try:
        old = open(path, encoding="utf-8").read() if os.path.isfile(path) else None
        if old != ANSI_PAT:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(ANSI_PAT)
    except Exception as _fw_err:
        _fw_log("drawviews.py:ansi pat", _fw_err)
        return None
    return path


def ansi_hatch(s):
    """A section hatched with an ANSI pattern reads it from ANSI.pat. Returns True when the file was changed."""
    try:
        if s is None or s.TypeId not in SECTION_TYPES or str(getattr(s, "CutSurfaceDisplay", "")) != "PatHatch":
            return False
        name = str(getattr(s, "NameGeomPattern", "") or "").strip().lower()
        if not name.startswith("ansi"):
            return False
        f = ansi_pat_file()
        if not f or str(getattr(s, "FileGeomPattern", "")) == f:
            return False
        s.FileGeomPattern = f
        if str(s.NameGeomPattern) != name:
            s.NameGeomPattern = name
        return True
    except Exception as _fw_err:
        _fw_log("drawviews.py:ansi hatch", _fw_err)
        return False


def fix_hatch_files(dname):
    """An open drawing's ANSI-hatched sections pointed at ANSI.pat (drawings saved before it), Modified kept."""
    doc = App.listDocuments().get(dname)
    if doc is None:
        return
    gdoc = Gui.getDocument(dname) if App.GuiUp else None
    was = gdoc.Modified if gdoc is not None else None
    hit = [s for s in doc.Objects if s.TypeId in SECTION_TYPES and ansi_hatch(s)]
    if hit:
        doc.recompute([s for s in hit])
        if gdoc is not None and was is False:
            gdoc.Modified = False


def material_hatch_of(s):
    """The crosshatch of the cut part's material (Edit Material > Crosshatch: pattern, angle, scale), or None."""
    import json
    from . import material
    srcs = list(getattr(s, "Source", []) or []) + list(getattr(s, "XSource", []) or [])
    base = getattr(s, "BaseView", None)
    if not srcs and base is not None:
        srcs = list(getattr(base, "Source", []) or []) + list(getattr(base, "XSource", []) or [])
    for o in srcs:
        try:
            r = material.row(o.Document)
            data = json.loads(getattr(r, "MaterialData", "") or "{}") if r is not None else {}
        except Exception:
            continue
        h = data.get("hatch") if isinstance(data, dict) else None
        if isinstance(h, dict) and h.get("pattern"):
            return h
    return None


def material_hatch(s):
    ""

    if s is None or s.TypeId not in SECTION_TYPES or getattr(s, "SWAutoHatch", False):
        return False
    if "SWMaterialHatch" in s.PropertiesList:
        return False
    h = material_hatch_of(s)
    if h is None:
        return False
    s.addProperty("App::PropertyString", "SWMaterialHatch", "FreeCAD", "The material crosshatch the section took")
    s.setEditorMode("SWMaterialHatch", 2)
    pattern = str(h.get("pattern"))
    s.SWMaterialHatch = pattern
    if pattern == "None":
        s.CutSurfaceDisplay = "Hide"
        return True
    s.CutSurfaceDisplay = "PatHatch"
    s.NameGeomPattern = pattern.split(" ")[0].lower()
    for prop, key in (("HatchScale", "scale"), ("HatchRotation", "angle")):
        try:
            if key in h and prop in s.PropertiesList:
                setattr(s, prop, float(h[key]))
        except Exception as _fw_err:
            _fw_log("drawviews.py:material hatch", _fw_err)
    return True


def _hatch_later(dname, name):
    doc = App.listDocuments().get(dname)
    s = doc.getObject(name) if doc is not None else None
    try:
        mat = material_hatch(s)
    except Exception as _fw_err:
        _fw_log("drawviews.py:material hatch later", _fw_err)
        mat = False
    if s is not None and (ansi_hatch(s) or mat):
        s.Document.recompute([s])


def hatch_soon(s):
    """After a new section takes System Options' Area Hatch/Fill (a moment after it is made): its ANSI file."""
    try:
        dname, name = s.Document.Name, s.Name
    except Exception:
        return
    for ms in (150, 800, 2000):
        QtCore.QTimer.singleShot(ms, lambda: _hatch_later(dname, name))




def register():
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
    watch_parts()                          # assembly views' model parts follow their model
    try:
        from . import drawpalette          # View Palette and Alternate Position (no startup.py change needed)
        drawpalette.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: View Palette not added: %s\n" % error)
    try:
        from . import drawviewcmds         # the drawing view right-click commands
        drawviewcmds.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: drawing view commands not added: %s\n" % error)
    try:
        from . import drawsketch           # the drawing Sketch tab and Make Section Line
        from . import drawdocprops         # Document Properties, Virtual Sharp, Detailing Mode
        drawdocprops.register()
        drawsketch.register()
        from . import drawkeys
        drawkeys.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: drawing sketch tools not added: %s\n" % error)
    try:
        from . import drawselect           # the Drawing View PM on a picked view; sketch buttons on a sheet
        drawselect.start()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Drawing View PM not added: %s\n" % error)
    try:
        from . import drawlayout           # Update View, Replace Model, Format Painter, Title Block Fields
        drawlayout.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: drawing layout commands not added: %s\n" % error)
    try:
        from . import drawblocks           # Blocks: Make, Insert, Edit, Explode, Save
        drawblocks.register()
        from . import drawflagnotes        # Flag Note (bank and flags)
        drawflagnotes.register()
        from . import drawmarkup           # Spell Checker, Automatic Border, Markup tab
        drawmarkup.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: blocks / markup commands not added: %s\n" % error)
    try:
        from . import drawtdtools
        drawtdtools.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Drawing Tools not added: %s\n" % error)
    try:
        from . import drawclose            # a sheet closed with the mouse on a dimension: TechDraw's hover crash
        drawclose.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: sheet close guard not added: %s\n" % error)
    try:
        from . import drawreattach         # dangling dimensions: drag onto an edge, Dangling Annotations...
        drawreattach.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: dangling annotations not added: %s\n" % error)
    try:
        from . import drawfamily           # Family Table (a tabulated drawing)
        drawfamily.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Family Table not added: %s\n" % error)
    try:
        from . import drawmenus            # the drawing menus (File ... Tools) and their extra commands
        drawmenus.register()
        from . import drawpmparts          # Layer Properties (the PMs' Style and Layer groups)
        drawpmparts.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: drawing menu commands not added: %s\n" % error)



# projection of every view on a page that is not kept updated (the PC's held sheets), so a new section, detail,
# break, crop or model view came out empty there until the next Update. Each view maker projects the views it
# made once (project_now), and leaves the page as it was.
_HELD = {}       # id(page) -> the views a page with Update View off is kept updated for, until they are drawn


def _hold_page(page, views, doc):
    """Keeps a page with Update View off updated until its new views are projected (TechDraw projects in the
    background: the page stays kept updated for at least 3 s and until every view has been idle for 3 looks in
    a row, 30 s at most), then turns it off again. Views made meanwhile join the same hold."""
    h = _HELD.get(id(page))
    if h is None:
        if getattr(page, "KeepUpdated", True):
            doc.recompute()
            return
        h = _HELD[id(page)] = {"views": [], "n": 0, "idle": 0}
        page.KeepUpdated = True
    h["views"].extend(views)
    h["n"] = h["idle"] = 0
    for v in views:
        v.touch()
    doc.recompute()

    def live():
        out = []
        for v in h["views"]:
            try:
                v.Name
                out.append(v)
            except Exception as _fw_err:
                _fw_log("drawviews.py:4360", _fw_err)
        return out

    def step():
        if _HELD.get(id(page)) is not h:
            return
        vs = live()
        waiting = any(hasattr(v, "isWaitingForHlr") and v.isWaitingForHlr() for v in vs)
        touched = any("Touched" in list(getattr(v, "State", []) or []) for v in vs)
        if touched and not waiting:
            try:
                doc.recompute()
            except Exception as _fw_err:
                _fw_log("drawviews.py:4373", _fw_err)
        h["n"] += 1
        h["idle"] = 0 if waiting or touched else h["idle"] + 1
        if h["n"] < 12 or (h["idle"] < 3 and h["n"] < 120):
            QtCore.QTimer.singleShot(250, step)
            return
        _HELD.pop(id(page), None)
        try:
            page.KeepUpdated = False
        except Exception as _fw_err:
            _fw_log("drawviews.py:4383", _fw_err)
    if h["n"] == 0 and not h.get("running"):
        h["running"] = True
        QtCore.QTimer.singleShot(250, step)


def _projects_new(fn):
    def maker(*args, **kwargs):
        page = args[0] if args and hasattr(args[0], "KeepUpdated") else kwargs.get("page")
        before = set()
        doc = getattr(page, "Document", None)
        if doc is not None:
            before = {o.Name for o in doc.Objects}
        out = fn(*args, **kwargs)
        try:
            if page is not None and doc is not None and (not getattr(page, "KeepUpdated", True) or
                                                         _HELD.get(id(page)) is not None):
                new = [o for o in doc.Objects if o.Name not in before and o.isDerivedFrom("TechDraw::DrawView")
                       and o.TypeId not in ("TechDraw::DrawViewDimension", "TechDraw::DrawViewBalloon")]
                if new:
                    _hold_page(page, new, doc)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: projecting new views: %s\n" % error)
        return out
    maker.__name__ = fn.__name__
    maker.__doc__ = fn.__doc__
    maker.__wrapped__ = fn
    return maker


for _name in ("make_section", "make_offset_section", "make_complex_section", "make_half_section", "make_detail",
              "make_break", "make_crop", "make_removed_section", "make_broken_out_profile", "make_broken_out"):
    if _name in globals() and not hasattr(globals()[_name], "__wrapped__"):
        globals()[_name] = _projects_new(globals()[_name])
if not hasattr(D.new_view, "__wrapped__"):
    D.new_view = _projects_new(D.new_view)
del _name
