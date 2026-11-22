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

from . import asmcore as ac

KIND = "FwDrawingViewModel"
ERRORS = []         # the last errors (checks read them)
DEFAULT_STATE = "<Default>_Display State 1"
EXPLODED_TEXT = "Show in exploded or model break state"


# ----------------------------------------------------------------------------- what the assembly offers
def assembly_in(doc):
    return ac.assembly_of(doc) if doc is not None else None


def configurations(doc):
    """([names], active) of the assembly document's configurations."""
    from . import configmanager as cm
    t = cm.table(doc) if doc is not None else None
    if t is None or not t.names():
        return ["Default"], "Default"
    return t.names(), t.active()


def display_states(doc, config=None):
    """([names], the one shown: config's own display state when they are linked, else the active one)."""
    from . import displaystates
    try:
        names = displaystates.names(doc)
        act = displaystates.active(doc)
    except Exception:
        names, act = [], None
    if config:
        try:
            from . import asmdisplay
            if asmdisplay.linked(doc) and config != configurations(doc)[1]:
                act = asmdisplay.state_of(doc, config) or act
        except Exception as _fw_err:
            _fw_log("asmdrawing.py:74", _fw_err)
    if not names:
        return [DEFAULT_STATE], DEFAULT_STATE
    return names, act if act in names else names[0]


def exploded_views(asm):
    from . import asmexplode as ax
    try:
        return ax.views(asm) if asm is not None else []
    except Exception:
        return []


def _current_exploded(asm):
    from . import asmexplode as ax
    for v in exploded_views(asm):
        if ax.is_exploded(v):
            return v
    return None


# ----------------------------------------------------------------------------- the view model
def is_model(obj):
    return getattr(obj, "FwKind", "") == KIND


def _raw(view):
    from . import drawviews as DV
    return DV.unsplit(list(getattr(view, "XSource", None) or [])) + list(getattr(view, "Source", None) or [])


def model_of(view):
    for o in _raw(view):
        if is_model(o):
            return o
    return None


def assembly_of_model(vm):
    try:
        return vm.Assembly
    except Exception:
        return None


def assembly_of_view(view):
    vm = model_of(view)
    if vm is not None:
        return assembly_of_model(vm)
    for o in _raw(view):
        if getattr(o, "TypeId", "") == "Assembly::AssemblyObject":
            return o
    return None


class ViewModel:
    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty("App::PropertyString", "FwKind", "FreeCAD", "drawing view model")
        obj.FwKind = KIND
        obj.setEditorMode("FwKind", 2)
        obj.addProperty("App::PropertyXLink", "Assembly", "View Model", "The assembly the view shows")
        obj.addProperty("App::PropertyString", "Configuration", "View Model", "Reference Configuration")
        obj.addProperty("App::PropertyString", "DisplayState", "View Model", "Display State")
        obj.addProperty("App::PropertyString", "ExplodedView", "View Model",
                        "Show in exploded state: the exploded view's name (empty: collapsed)")
        obj.addProperty("App::PropertyStringList", "HiddenComponents", "View Model",
                        "Components hidden in this view (Hide / Show Components)")
        obj.addProperty("App::PropertyStringList", "Components", "View Model",
                        "The components drawn, in the order of the compound")
        obj.setEditorMode("Components", 1)

    def execute(self, obj):
        build(obj, switch=False)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderViewModel:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        try:
            vobj.ShowInTree = False
        except Exception as _fw_err:
            _fw_log("asmdrawing.py:166", _fw_err)

    def getIcon(self):
        return "Assembly_CreateView"

    def dumps(self):
        return None

    def loads(self, state):
        return None


def new_model(drawing_doc, asm, config="", state="", exploded="", hidden=()):
    vm = drawing_doc.addObject("Part::FeaturePython", "ViewModel")
    ViewModel(vm)
    if App.GuiUp and vm.ViewObject is not None:
        ViewProviderViewModel(vm.ViewObject)
        vm.ViewObject.Visibility = False
        vm.ViewObject.ShowInTree = False
    vm.Label = "%s view model" % asm.Label
    vm.Assembly = asm
    set_state(vm, config, state, exploded, hidden)
    return vm


def set_state(vm, config=None, state=None, exploded=None, hidden=None):
    for name, val in (("Configuration", config), ("DisplayState", state), ("ExplodedView", exploded)):
        if val is not None and getattr(vm, name) != val:
            setattr(vm, name, val)
    if hidden is not None and list(vm.HiddenComponents) != list(hidden):
        vm.HiddenComponents = list(hidden)
    build(vm, switch=True)
    return vm


def _visible(comp, look):
    if look is not None and comp.Name in look:
        return bool(look[comp.Name].get("v", True))
    vo = getattr(comp, "ViewObject", None)
    return bool(vo.Visibility) if vo is not None else bool(getattr(comp, "Visibility", True))


def component_shapes(asm, config="", state="", exploded="", hidden=(), switch=True):
    """[(component, shape)] of asm as that configuration / display state / exploded view shows it
    (global coordinates), plus [explode line shapes]. switch: another configuration than the active
    one is shown for a moment (else None is returned for it)."""
    import Part
    from . import asmcomp
    from . import asmexplode as ax
    from . import configmanager as cm
    from . import displaystates
    doc = asm.Document
    t = cm.table(doc)
    old = t.active() if t is not None else None
    other = bool(t is not None and config and config in t.names() and config != old)
    if other and not switch:
        return None
    if other:
        cm.show(t, config)
        _rebuild(doc)       # the configuration's component configurations (their copies) built before reading
    try:
        look = None
        if state:
            data = displaystates._data(doc)
            if state != data.get("active") and state in data.get("states", {}):
                look = data["states"][state]
        comps = ac.components(asm)
        movers = comps + ax.nested_parts(asm)
        target = doc.getObject(exploded) if exploded else None
        cur = _current_exploded(asm)
        saved = {c.Name: App.Placement(c.Placement) for c in movers}
        moved = target is not cur
        lines = []
        pre = {}
        for c in comps:
            try:
                pre[c.Name] = Part.getShape(asm, c.Name + ".")
            except Exception as _fw_err:
                _fw_log("asmdrawing.py:244", _fw_err)
        try:
            gpl = asm.getGlobalPlacement()
        except Exception:
            gpl = App.Placement(asm.Placement)
        try:
            if moved:
                if cur is not None:
                    for name, plc in zip(cur.FwBaseNames, cur.FwBasePlacements):
                        o = doc.getObject(name)
                        if o is not None:
                            o.Placement = plc
                if target is not None:
                    ax.apply_steps(asm, target)
            out = []
            for c in comps:
                if c.Name in hidden or asmcomp.is_suppressed(c) or not _visible(c, look):
                    continue
                s = pre.get(c.Name)
                if s is None or s.isNull():
                    continue
                s = s.copy()
                if moved and c.Name in saved:
                    # where the explode (or collapse) puts it: its move, in global coordinates
                    delta = gpl.multiply(c.Placement).multiply(saved[c.Name].inverse()).multiply(gpl.inverse())
                    if not delta.isIdentity():
                        s.Placement = delta.multiply(s.Placement)
                out.append((c, s))
            if target is not None:
                from . import asmexplines
                for sk in asmexplines.sketches(asm, target):
                    try:
                        if moved:
                            sk.Proxy.execute(sk)
                        if not sk.Shape.isNull():
                            lines.append(sk.Shape.copy())
                    except Exception as _fw_err:
                        _fw_log("asmdrawing.py:281", _fw_err)
        finally:
            if moved:
                for c in movers:
                    if c.Name in saved:
                        c.Placement = saved[c.Name]
                if target is not None:
                    try:
                        ax._clear_lines(target)
                    except Exception as _fw_err:
                        _fw_log("asmdrawing.py:291", _fw_err)
                    from . import asmexplines
                    for sk in asmexplines.sketches(asm, target):
                        try:
                            sk.Proxy.execute(sk)
                            sk.purgeTouched()
                        except Exception as _fw_err:
                            _fw_log("asmdrawing.py:298", _fw_err)
                for o in [asm] + movers:
                    try:
                        o.purgeTouched()
                    except Exception as _fw_err:
                        _fw_log("asmdrawing.py:303", _fw_err)
    finally:
        if other:
            cm.show(t, old)
            _rebuild(doc)
    return out, lines


def _rebuild(doc):
    """Recompute the assembly after a configuration switch made for a view (a component that uses
    another configuration of its part there shows it only once rebuilt). Not while the assembly
    document itself is recomputing."""
    try:
        if not doc.isRecomputing() if hasattr(doc, "isRecomputing") else True:
            doc.recompute()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: view configuration rebuild: %s\n" % error)


def build(vm, switch=False):
    import Part
    asm = assembly_of_model(vm)
    if asm is None:
        return
    got = component_shapes(asm, vm.Configuration, vm.DisplayState, vm.ExplodedView, list(vm.HiddenComponents),
                           switch)
    if got is None:
        return          # another configuration: kept as it was last read
    pairs, lines = got
    shapes = [s for _c, s in pairs] + lines
    vm.Shape = Part.makeCompound(shapes) if shapes else Part.Shape()
    names = [c.Name for c, _s in pairs]
    if list(vm.Components) != names:
        vm.Components = names


def shapes_by_component(vm):
    """{component: its shape in the view model}."""
    asm = assembly_of_model(vm)
    if asm is None or vm.Shape.isNull():
        return {}
    subs = vm.Shape.childShapes(False, False)
    out = {}
    for name, s in zip(vm.Components, subs):
        o = asm.Document.getObject(name)
        if o is not None:
            out[o] = s
    return out


# ----------------------------------------------------------------------------- a view's state
def view_state(view):
    """(configuration, display state, exploded view name, hidden components) of a drawing view."""
    vm = model_of(view)
    if vm is not None:
        return vm.Configuration, vm.DisplayState, vm.ExplodedView, list(vm.HiddenComponents)
    asm = assembly_of_view(view)
    doc = asm.Document if asm is not None else None
    cur = _current_exploded(asm) if asm is not None else None
    return (configurations(doc)[1] if doc else "Default", display_states(doc)[1] if doc else DEFAULT_STATE,
            cur.Name if cur is not None else "", [])


def _family(view):
    """view and the views drawn from it (projected, section, detail...), whose model it shares."""
    from . import drawselect
    out, todo = [], [view]
    while todo:
        v = todo.pop()
        if v in out:
            continue
        out.append(v)
        todo += drawselect.children_of(v)
        for o in v.Document.Objects:
            if getattr(o, "BaseView", None) is v and o not in out:
                todo.append(o)
    return out


def apply_view(view, config=None, state=None, exploded=None, hidden=None):
    """Puts the view (and the views drawn from it) on that configuration / display state / exploded
    view / hidden list. Returns its view model."""
    asm = assembly_of_view(view)
    if asm is None:
        return None
    vm = model_of(view)
    old = list(_raw(view))
    if vm is None:
        c, s, e, h = view_state(view)
        vm = new_model(view.Document, asm, config if config is not None else c, state if state is not None else s,
                       exploded if exploded is not None else e, hidden if hidden is not None else h)
    else:
        set_state(vm, config, state, exploded, hidden)
    for v in _family(view):
        if model_of(v) is vm:
            continue
        if any(getattr(o, "Kind", "") == "Mirror" for o in _raw(v)):
            continue        # a mirrored view keeps its FWDrawingShape source (drawviews.set_mirror)
        if any(o in old for o in _raw(v)) or v is view:
            from . import drawviews as DV
            if DV.splits(vm):
                DV.split_source(v, vm)          # TechDraw gets the parts (fast detail views)
            else:
                v.XSource = [vm]
            try:
                v.Source = []
            except Exception as _fw_err:
                _fw_log("asmdrawing.py:410", _fw_err)
        _mark(v, vm)
    _mark(view, vm)
    try:
        from . import drawviews as DV
        DV.drop_unused_parts(view.Document)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: view model parts: %s\n" % error)
    return vm


def _mark(v, vm):
    for name, val in (("SWConfiguration", vm.Configuration), ("SWDisplayState", vm.DisplayState)):
        if name not in v.PropertiesList:
            v.addProperty("App::PropertyString", name, "FreeCAD", "Drawing View option")
        setattr(v, name, val)
    if "SWExploded" not in v.PropertiesList:
        v.addProperty("App::PropertyString", "SWExploded", "FreeCAD", "Show in exploded state: the exploded view")
    v.SWExploded = vm.ExplodedView


def hide_components(view, comps, hide=True):
    ""
    vm = model_of(view)
    names = list(vm.HiddenComponents) if vm is not None else []
    for c in comps:
        n = c if isinstance(c, str) else c.Name
        if hide and n not in names:
            names.append(n)
        elif not hide and n in names:
            names.remove(n)
    return apply_view(view, hidden=names)


def component_at(view, p):
    """The component of view under sheet point p (the nearest along the line of sight). The
    shapes are kept per view until the model changes; a component whose box is farther from the
    line than the best one so far is not measured."""
    import Part
    from . import drawings as D
    from . import drawviews as DV
    shapes = _cached_components(view)
    if not shapes:
        return None
    d, x, y = D.view_frame(view)
    q = DV.to_model(view, p)
    u = App.Vector(d)
    if u.Length < 1e-12:
        return None
    u.normalize()
    near = []
    for c, s, centre, radius in shapes:
        w = centre - q
        off = (w - u * w.dot(u)).Length      # the box centre's distance from the line of sight
        low = max(0.0, off - radius)
        if low == 0.0:
            # the box itself: the shape is at least as far from the line as its box is
            try:
                low = _line_box_low(s.BoundBox, q, u)
            except Exception as _fw_err:
                _fw_log("asmdrawing.py:470", _fw_err)
        near.append((low, c, s))
    near.sort(key=lambda r: r[0])
    ray = Part.makeLine(q - d * 1e5, q + d * 1e5)
    hits = []
    for low, c, s in near:
        if hits and low > min(h[0] for h in hits) + 1e-6:
            break
        try:
            hits.append((_ray_distance(s, ray, q, u), c, s))
        except Exception:
            continue
    if not hits:
        return None
    try:       # of the ones the line of sight passes through, the one it meets first (a rod inside its tube
        from . import drawannot as DA       # is under the click only where it shows)
        j = DA._front_of(u, q, ray, [(dist, i, s) for i, (dist, _c, s) in enumerate(hits)])
        return hits[j][1]
    except Exception:
        return min(hits, key=lambda h: h[0])[1]


_FACE_BOXES = {}        # id of a component shape -> (shape, [(face, its box)]) for the shapes kept per view


def _line_box_low(bb, q, u):
    """A lower bound of the distance from the line (q, u) to anything in box bb: the distance, seen
    along the line, from the line to the outline of the box's corners."""
    import math
    a = App.Vector(1, 0, 0) if abs(u.x) < 0.9 else App.Vector(0, 1, 0)
    e1 = u.cross(a)
    e1.normalize()
    e2 = u.cross(e1)
    pts = []
    for x in (bb.XMin, bb.XMax):
        for y in (bb.YMin, bb.YMax):
            for z in (bb.ZMin, bb.ZMax):
                w = App.Vector(x, y, z) - q
                pts.append((w.dot(e1), w.dot(e2)))
    pts = sorted(set(pts))
    if len(pts) < 3:
        return 0.0

    def cross(o, a_, b):
        return (a_[0] - o[0]) * (b[1] - o[1]) - (a_[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p_ in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p_) <= 0:
            lower.pop()
        lower.append(p_)
    for p_ in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p_) <= 0:
            upper.pop()
        upper.append(p_)
    hull = lower[:-1] + upper[:-1]
    if len(hull) < 3:
        return 0.0
    inside = all(cross(hull[k], hull[(k + 1) % len(hull)], (0.0, 0.0)) >= 0 for k in range(len(hull)))
    if inside:
        return 0.0
    best = None
    for k in range(len(hull)):
        (x1, y1), (x2, y2) = hull[k], hull[(k + 1) % len(hull)]
        dx, dy = x2 - x1, y2 - y1
        ll = dx * dx + dy * dy
        t = 0.0 if ll < 1e-30 else max(0.0, min(1.0, -(x1 * dx + y1 * dy) / ll))
        d = math.hypot(x1 + t * dx, y1 + t * dy)
        best = d if best is None or d < best else best
    return max(0.0, best - 1e-9)


def _ray_distance(s, ray, q, u):
    """s.distToShape(ray)[0] measured face by face, nearest box first, stopping once the next
    face's box is farther from the line than the nearest face found (a plate with a hundred holes
    took 7 ms a measure; a few faces are quick). Each face's box is kept with the view's shapes."""
    got = _FACE_BOXES.get(id(s))
    if got is None or got[0] is not s:
        boxes = []
        for f in s.Faces:
            bb = f.BoundBox
            bb.enlarge(_BOX_PAD)
            boxes.append((f, bb))
        if len(_FACE_BOXES) > 4000:
            _FACE_BOXES.clear()
        got = _FACE_BOXES[id(s)] = (s, boxes)
    if not got[1]:
        return s.distToShape(ray)[0]
    order = sorted(((_line_box_low(bb, q, u), k) for k, (f, bb) in enumerate(got[1])), key=lambda r: r[0])
    best = None
    for low, k in order:
        if best is not None and low > best:
            break
        d = got[1][k][0].distToShape(ray)[0]
        if best is None or d < best:
            best = d
            if best <= 1e-9:
                break
    return best


_BOX_PAD = 1e-4         # mm: a box the line of sight misses by this much holds nothing on it
_VIEW_SHAPES = {}       # (document, view): (model stamp, [(component, shape, box centre, box half diagonal)])


def _model_stamp(view):
    vm = model_of(view)
    asm = assembly_of_view(view) if vm is None else assembly_of_model(vm)
    try:
        from . import asmgen
        gen = asmgen.gen(asm.Document) if asm is not None else 0
    except Exception:
        gen = None
    shape = vm.Shape.hashCode() if vm is not None and not vm.Shape.isNull() else 0
    return (gen, shape, getattr(asm, "Name", ""))


def _cached_components(view):
    key = (view.Document.Name, view.Name)
    stamp = _model_stamp(view)
    got = _VIEW_SHAPES.get(key)
    if got is not None and got[0] == stamp and stamp[0] is not None:
        return got[1]
    out = []
    for c, s in view_components(view):
        bb = s.BoundBox
        out.append((c, s, bb.Center, bb.DiagonalLength / 2.0))
    if len(_VIEW_SHAPES) > 64:
        _VIEW_SHAPES.clear()
    _VIEW_SHAPES[key] = (stamp, out)
    return out


def view_components(view):
    """[(component, shape where the view shows it)] of an assembly view."""
    vm = model_of(view)
    if vm is not None:
        return list(shapes_by_component(vm).items())
    asm = assembly_of_view(view)
    if asm is None:
        return []
    import Part
    from . import asmcomp
    out = []
    for c in ac.components(asm):
        if asmcomp.is_suppressed(c):
            continue
        try:
            s = Part.getShape(asm, c.Name + ".")
        except Exception as _fw_err:
            _fw_log("asmdrawing.py:620", _fw_err)
            continue
        if not s.isNull() and s.Volume > 1e-9:
            out.append((c, s))
    return out


# ----------------------------------------------------------------------------- item numbers from the BOM
def part_number(comp, asm):
    """The BOM's PART NUMBER of a component (drawtables' naming: the file, in its configuration)."""
    from . import drawtables
    base = getattr(comp, "LinkedObject", None) or comp
    config = drawtables.configuration(comp)
    if base.Document is asm.Document:
        name = base.Label
    else:
        name = drawtables._part_number(base.Document, config, base)
    if config != "Default" and name != config:
        name = "%s (%s)" % (name, config)
    return name


def _bom_tables(page):
    return [o for o in page.Document.Objects if getattr(o, "SWTable", "") == "BOM" and o in getattr(page, "Views", [])] \
        or [o for o in page.Document.Objects if getattr(o, "SWTable", "") == "BOM"]


def _page_of(view):
    for o in view.InListRecursive:
        if o.TypeId == "TechDraw::DrawPage":
            return o
    return None


def bom_numbers(view):
    ""
    from . import drawtables
    asm = assembly_of_view(view)
    if asm is None:
        return {}
    page = _page_of(view)
    rows = None
    ident = {}
    if page is not None:
        doc = view.Document
        mine = []
        for t in _bom_tables(page):
            src = doc.getObject(getattr(t, "SWBomView", "") or "")
            if src is not None and assembly_of_view(src) is asm:
                mine.append((src is view or view in _family(src), t))
        mine.sort(key=lambda it: not it[0])
        if mine:
            try:
                rows = drawtables.rows_of(mine[0][1])
                ident = drawtables.bom_ident(mine[0][1])
            except Exception:
                rows = None
    if rows is None:
        for o in asm.Document.Objects:
            if getattr(o, "FwKind", "") == "FwAssemblyBom":
                try:
                    import json
                    rows = json.loads(o.FwRows or "[]")
                except Exception:
                    rows = None
                break
    if not rows:
        try:
            rows = drawtables.bom_rows(view)
            ident = dict(drawtables.LAST_IDENT)
        except Exception:
            rows = []
    out = {}
    for r in rows[1:]:
        if len(r) > 1 and r[1] and r[1] not in out:
            out[drawtables.unstrike(r[1]) if hasattr(drawtables, "unstrike") else r[1]] = r[0]

    for key, item in ident.items():
        if key not in out:          # only the configurations' own identities: a shown part number keeps its row
            out[key] = item
    return out


def item_number(view, p):
    """(item number, component) of the component under sheet point p, numbered as the BOM."""
    asm = assembly_of_view(view)
    if asm is None:
        return None
    comp = component_at(view, p)
    if comp is None:
        return "1", None
    nums = bom_numbers(view)
    name = part_number(comp, asm)
    if name in nums:
        return str(nums[name]), comp
    order = _part_order(asm)
    return str(order.index(name) + 1 if name in order else 1), comp


_ORDER = {}     # (document, assembly) -> (change count, part numbers in tree order)


def _part_order(asm):
    """The part numbers in tree order, kept while the assembly's document is unchanged (an auto
    balloon asked for them five times per balloon: 31,000 part numbers on a 301-part set)."""
    try:
        from . import asmgen
        g = asmgen.gen(asm.Document)
    except Exception:
        g = -1
    key = (asm.Document.Name, asm.Name)
    got = _ORDER.get(key)
    if got is not None and got[0] == g and g >= 0:
        return got[1]
    order = []
    for c in ac.components(asm):
        n = part_number(c, asm)
        if n not in order:
            order.append(n)
    _ORDER[key] = (g, order)
    return order


# ----------------------------------------------------------------------------- patches
class _Mapped(list):
    """drawviews.source_shapes of a view model's view: the assembly, keeping the view model in .raw
    so a view made from it (section, detail, break...) draws the same model."""
    raw = ()


def _patch_drawviews():
    from . import drawings as D
    from . import drawviews as DV
    if getattr(DV, "_fw_asmdrawing", False):
        return
    DV._fw_asmdrawing = True
    src0, centre0, link0 = DV.source_shapes, DV.model_centre, D.link_source

    def source_shapes(v):
        got = src0(v)
        if not any(is_model(o) for o in got):
            return got
        out = _Mapped([assembly_of_model(o) if is_model(o) else o for o in got])
        out = _Mapped([o for o in out if o is not None])
        out.raw = list(got)
        return out

    def model_centre(v):
        if model_of(v) is None:
            return centre0(v)
        box = None
        for o in _raw(v):
            try:
                b = o.Shape.BoundBox
            except Exception:
                continue
            if box is None:
                box = App.BoundBox(b)
            else:
                box.add(b)
        return box.Center if box is not None else App.Vector()

    def link_source(view, shapes):
        if isinstance(shapes, _Mapped):
            shapes = shapes.raw
        shapes = DV.unsplit(list(shapes))
        if len(shapes) == 1 and DV.splits(shapes[0]):
            return DV.split_source(view, shapes[0])     # an assembly is drawn as its parts (fast detail views)
        return link0(view, shapes)

    DV.source_shapes, DV.model_centre, D.link_source = source_shapes, model_centre, link_source


def _patch_balloons():
    from . import drawannot as DA
    from . import drawviews as DV
    if getattr(DA, "_fw_asmdrawing", False):
        return
    DA._fw_asmdrawing = True
    item0, auto0 = DA.item_number, DA.auto_balloon

    def item_number(view, p):
        got = None
        try:
            got = item_number_asm(view, p)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: balloon item number: %s\n" % error)
        return got if got is not None else item0(view, p)

    def auto_balloon(page, view, *args, **kwargs):
        asm = assembly_of_view(view)
        if asm is None:
            return auto0(page, view, *args, **kwargs)
        # the components where the view draws them (exploded, configured), one per BOM item for
        # Ignore multiple instances (two parts whose bodies have the same name stay two)
        stand = _Stand(asm, view_components(view))
        src0 = DV.source_shapes
        DV.source_shapes = lambda v: [stand] if v is view else src0(v)
        try:
            return auto0(page, view, *args, **kwargs)
        finally:
            DV.source_shapes = src0

    DA.item_number, DA.auto_balloon = item_number, auto_balloon


def item_number_asm(view, p):
    if assembly_of_view(view) is None:
        return None
    return item_number(view, p)


class _Key:
    def __init__(self, name):
        self.Name = name


class _Comp:
    def __init__(self, comp, shape, asm):
        self.Name = comp.Name
        self.Label = comp.Label
        try:
            self.LinkedObject = _Key(part_number(comp, asm))
        except Exception:
            self.LinkedObject = _Key(comp.Name)
        self.Shape = shape
        self.TypeId = comp.TypeId


class _Stand:
    """Auto Balloon's look at an exploded / configured view's assembly: its components as drawn."""
    TypeId = "Assembly::AssemblyObject"

    def __init__(self, asm, pairs):
        self.Document = asm.Document
        self.Name = asm.Name
        self.Label = asm.Label
        self.OutList = [_Comp(c, s, asm) for c, s in pairs]


def _combo_fill(combo, names, current):
    combo.blockSignals(True)
    combo.clear()
    combo.addItems(list(names))
    if current in names:
        combo.setCurrentIndex(list(names).index(current))
    combo.blockSignals(False)


def _exploded_widgets(panel, combo_parent_lay, prefix):
    from PySide import QtWidgets
    panel.exploded = QtWidgets.QCheckBox(EXPLODED_TEXT, panel.config.parentWidget())
    panel.exploded.setObjectName(prefix + "Exploded")
    panel.exploded_view = QtWidgets.QComboBox(panel.config.parentWidget())
    panel.exploded_view.setObjectName(prefix + "ExplodedView")
    combo_parent_lay.addWidget(panel.exploded)
    combo_parent_lay.addWidget(panel.exploded_view)
    panel.exploded_view.setVisible(False)
    panel.exploded.toggled.connect(lambda on: panel.exploded_view.setEnabled(bool(on)))


def _fill_assembly(panel, doc, asm, config=None, state=None, exploded=None):
    names, act = configurations(doc)
    _combo_fill(panel.config, names, config or act)
    snames, sact = display_states(doc)
    _combo_fill(panel.display_state, snames, state or sact)
    views = exploded_views(asm) if asm is not None else []
    if hasattr(panel, "exploded"):
        panel.exploded.blockSignals(True)
        panel.exploded.setEnabled(bool(views))
        panel.exploded.setChecked(bool(views) and bool(exploded))
        panel.exploded.blockSignals(False)
        _combo_fill(panel.exploded_view, [v.Label for v in views],
                    next((v.Label for v in views if v.Name == exploded), views[0].Label if views else ""))
        panel.exploded_view.setVisible(len(views) > 1)
        panel.exploded_view.setEnabled(panel.exploded.isChecked())
        panel._fw_views = views


def _config_changed(panel, doc):
    ""
    names, cur = display_states(doc, panel.config.currentText().replace(" <Link to parent>", ""))
    if cur in names:
        panel.display_state.blockSignals(True)
        panel.display_state.setCurrentIndex(names.index(cur))
        panel.display_state.blockSignals(False)


def _choice(panel):
    views = getattr(panel, "_fw_views", [])
    ex = ""
    if getattr(panel, "exploded", None) is not None and panel.exploded.isChecked() and views:
        i = panel.exploded_view.currentIndex()
        ex = views[i if 0 <= i < len(views) else 0].Name
    return (panel.config.currentText().replace(" <Link to parent>", ""), panel.display_state.currentText(), ex)


def _patch_model_view():
    from . import drawings as D
    cls = D.ModelViewPanel
    if getattr(cls, "_fw_asmdrawing", False):
        return
    cls._fw_asmdrawing = True
    build0, go0, place0, dress0 = cls.build, cls.go_page, cls._place, cls.dress

    def build(self):
        build0(self)
        _exploded_widgets(self, self.config.parentWidget().layout(), "SWDraw")

    def go_page(self, n):
        go0(self, n)
        if n == 2 and self.source() is not None:
            src = self.source()
            asm = assembly_in(src)
            cur = _current_exploded(asm) if asm is not None else None
            _fill_assembly(self, src, asm, exploded=cur.Name if cur is not None else "")
            if not getattr(self, "_fw_cfg_hook", False):
                self._fw_cfg_hook = True
                self.config.currentIndexChanged.connect(
                    lambda *_: self.source() is not None and _config_changed(self, self.source()))
            self.exploded.setVisible(asm is not None)
            self.exploded_view.setVisible(asm is not None and len(getattr(self, "_fw_views", [])) > 1)

    def _wanted(self):
        """The view model the picked choices need (None: the assembly as it is shown now will do)."""
        src = self.source()
        asm = assembly_in(src) if src is not None else None
        if asm is None:
            return None
        config, state, ex = _choice(self)
        _names, act = configurations(src)
        _snames, sact = display_states(src)
        cur = _current_exploded(asm)
        if config == act and state == sact and ex == (cur.Name if cur is not None else ""):
            return None
        key = (src.Name, config, state, ex)
        cache = getattr(self, "_fw_models", {})
        vm = cache.get(key)
        if vm is None or vm.Document is None:
            vm = new_model(self.doc, asm, config, state, ex)
            cache[key] = vm
            self._fw_models = cache
            self.made.append(vm)
        return vm

    def _place(self, p):
        vm = None
        try:
            vm = _wanted(self)
        except Exception as error:
            import traceback
            ERRORS.append(traceback.format_exc())
            App.Console.PrintWarning("FreeCAD: assembly drawing view: %s\n" % error)
        if vm is None:
            return place0(self, p)
        ms0 = D.model_shapes
        name = self.source().Name
        D.model_shapes = lambda doc: [vm] if getattr(doc, "Name", None) == name else ms0(doc)
        try:
            return place0(self, p)
        finally:
            D.model_shapes = ms0

    def dress(self, v):
        dress0(self, v)
        vm = model_of(v)
        if vm is not None:
            _mark(v, vm)

    cls.build, cls.go_page, cls._place, cls.dress = build, go_page, _place, dress


def _patch_view_pm():
    from . import drawselect as DS
    cls = DS.DrawingViewPanel
    if getattr(cls, "_fw_asmdrawing", False):
        return
    cls._fw_asmdrawing = True
    build0 = cls.build

    def build(self):
        build0(self)
        v = self.view
        asm = assembly_of_view(v)
        if asm is None:
            return
        _exploded_widgets(self, self.config.parentWidget().layout(), "SWViewPM")
        config, state, ex, _h = view_state(v)
        _fill_assembly(self, asm.Document, asm, config, state, ex)
        linked = DS.parent_of(v) is not None or v.TypeId in (
            "TechDraw::DrawViewSection", "TechDraw::DrawViewDetail", "TechDraw::DrawComplexSection")
        if linked:

            self.config.setItemText(self.config.currentIndex(), self.config.currentText() + " <Link to parent>")

            # group); the one entry is the parent's configuration, so the combo can't pick another
            cur = self.config.currentText()
            self.config.blockSignals(True)
            self.config.clear()
            self.config.addItem(cur)
            self.config.blockSignals(False)
            for w in (self.exploded, self.exploded_view):
                w.setVisible(False)       # the parent's exploded state rules (no greyed boxes)
        else:
            self.config.currentIndexChanged.connect(lambda *_: (_config_changed(self, asm.Document),
                                                                 self.change(lambda: _apply_pm(self))))
            self.exploded.toggled.connect(lambda *_: self.change(lambda: _apply_pm(self)))
            self.exploded_view.currentIndexChanged.connect(lambda *_: self.change(lambda: _apply_pm(self)))
        self.display_state.currentIndexChanged.connect(lambda *_: self.change(lambda: _apply_pm(self)))

    cls.build = build


def _apply_pm(panel):
    config, state, ex = _choice(panel)
    target = panel.view
    from . import drawselect as DS
    while DS.parent_of(target) is not None:
        target = DS.parent_of(target)
    apply_view(target, config, state, ex)


# ----------------------------------------------------------------------------- Show/Hide on a view's right-click
PICKED = {}         # the component under the last right-click on an assembly view


def edge_point(view, edge):
    """Sheet point of the middle of the view's edge (an index, as the right-click finds it)."""
    from . import drawmenu
    e = view.getEdgeByIndex(edge)
    q = e.valueAt((e.FirstParameter + e.LastParameter) / 2.0)
    x0, y0 = drawmenu._place(view)
    return x0 + q.x, y0 - q.y


def _patch_menus():
    from . import drawextras as X
    from . import drawmenu
    if getattr(drawmenu, "_fw_asmdrawing", False):
        return
    drawmenu._fw_asmdrawing = True
    items0 = drawmenu.view_items
    name0, hide0, hidden0, show0 = X.component_name, X.hide_component, X.hidden_components, X.show_components

    def view_items(v, edge=None):
        PICKED.clear()
        if assembly_of_view(v) is not None and edge is not None:
            try:
                PICKED[v.Name] = component_at(v, edge_point(v, edge))
            except Exception as error:
                App.Console.PrintLog("FreeCAD: component under the pointer: %s\n" % error)
        return items0(v, edge)

    def component_name(v):
        if assembly_of_view(v) is None:
            return name0(v)
        c = PICKED.get(v.Name)
        return c.Label if c is not None else None

    def hidden_components(v):
        asm = assembly_of_view(v)
        if asm is None:
            return hidden0(v)
        vm = model_of(v)
        out = [asm.Document.getObject(n) for n in (vm.HiddenComponents if vm is not None else [])]
        return [o for o in out if o is not None]

    def _in(doc, name, run):
        doc.openTransaction(name)
        try:
            run()
            # inside the step: the view's model parts (drawviews draws an assembly as its parts) made
            # or dropped for the new component count now. Left to drawviews' deferred resync, the
            # removal came after the step as a separate "Delete", so one Undo did not undo the hide
            doc.recompute()
            try:
                from . import drawviews as DV
                for vm in [o for o in doc.Objects if getattr(o, "FwKind", "") == "FwDrawingViewModel"]:
                    if DV.splits(vm):
                        DV.sync_parts(doc, vm)
                doc.recompute()
            except Exception as error:
                App.Console.PrintLog("FreeCAD: view model parts: %s\n" % error)
        finally:
            doc.commitTransaction()
        doc.recompute()

    def hide_component(v):
        if assembly_of_view(v) is None:
            return hide0(v)
        c = PICKED.get(v.Name)
        if c is None:
            return False
        _in(v.Document, "Hide Component", lambda: hide_components(_top(v), [c]))
        return True

    def show_components(v):
        if assembly_of_view(v) is None:
            return show0(v)
        if not hidden_components(v):
            return False
        _in(v.Document, "Show Components", lambda: apply_view(_top(v), hidden=[]))
        return True

    drawmenu.view_items = view_items
    X.component_name, X.hide_component, X.hidden_components, X.show_components = \
        component_name, hide_component, hidden_components, show_components


def _top(v):
    from . import drawselect as DS
    while DS.parent_of(v) is not None:
        v = DS.parent_of(v)
    return v


def _patch_first_save():
    """A new drawing's first Save moves it from its holding file to the place chosen. FreeCAD keeps a
    link to another file as a path relative to the file it was saved in, so the view models' links to
    the assembly kept the holding file's path, and the drawing opened again with the assembly not
    found ("Link not restored"). The drawings module sets its views' links again; the view models'
    links are set again the same way."""
    from . import drawings as D
    if getattr(D, "_fw_asmdrawing_save", False):
        return
    D._fw_asmdrawing_save = True
    ask0 = D._ask_first

    def ask_first(doc):
        ok = ask0(doc)
        if not ok:
            return ok
        try:
            models = [o for o in doc.Objects if is_model(o) and getattr(o, "Assembly", None) is not None]
            for vm in models:
                asm = vm.Assembly
                vm.Assembly = None
                vm.Assembly = asm
            if models:
                D._SAVING.append(doc.Name)
                try:
                    doc.save()
                finally:
                    D._SAVING.remove(doc.Name)
                __import__("FreeCADGui").getDocument(doc.Name).Modified = False
        except Exception as error:
            App.Console.PrintLog("assembly view models after the first Save: %s\n" % error)
        return ok
    D._ask_first = ask_first


def install():
    for fn in (_patch_drawviews, _patch_balloons, _patch_model_view, _patch_view_pm, _patch_menus, _patch_first_save):
        try:
            fn()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: assembly drawings: %s\n" % error)
