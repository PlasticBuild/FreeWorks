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

TYPE = "PartDesign::FeaturePython"
ICON = "FEATURES_FILLET"


def is_multi_radius(obj):
    try:
        return obj.TypeId == TYPE and isinstance(obj.Proxy, MultiRadiusFeature)
    except Exception:
        return False


def _same_edge(a, b):
    if a.isSame(b):
        return True
    try:
        return (abs(a.Length - b.Length) < 1e-7 and
                (a.valueAt(a.FirstParameter) - b.valueAt(b.FirstParameter)).Length +
                (a.valueAt(a.LastParameter) - b.valueAt(b.LastParameter)).Length < 1e-6 or
                abs(a.Length - b.Length) < 1e-7 and
                (a.CenterOfMass - b.CenterOfMass).Length < 1e-7)
    except Exception:
        return False


def edge_radii(base, source, subs, radii, default):
    """[(edge index in base, 1-based, radius)] for the picked items, a later pick winning."""
    out = {}
    edges = base.Edges
    for k, sub in enumerate(subs):
        r = radii[k] if k < len(radii) else default
        name = sub.split(".")[-1].lstrip("?")
        try:
            if not name:
                picked = list(source.Edges)
            else:
                g = source.getElement(name)
                picked = list(g.Edges) if name.startswith("Face") else [g]
        except Exception:
            continue
        for e in picked:
            i = next((i for i, b in enumerate(edges, 1) if _same_edge(b, e)), None)
            if i is not None:
                out[i] = r
    return sorted(out.items())


_scratch = None


def _scratch_doc():
    """One hidden scratch document for the whole session, kept open: closing a document while
    a feature's page is open ends FreeCAD's open Undo step (its Cancel would undo nothing)."""
    global _scratch
    try:
        if _scratch is not None and _scratch.Name in App.listDocuments():
            return _scratch
    except Exception as _fw_err:
        _fw_log("multiradius.py:81", _fw_err)
    active = App.ActiveDocument
    _scratch = App.newDocument("FreeWorksMultiRadius", hidden=True, temp=True)
    try:
        _scratch.UndoMode = 0
    except Exception as _fw_err:
        _fw_log("multiradius.py:87", _fw_err)
    _scratch.addObject("Part::Feature", "Base")
    _scratch.addObject("Part::Fillet", "Fillet").Base = _scratch.getObject("Base")
    _scratch.addObject("Part::Chamfer", "Chamfer").Base = _scratch.getObject("Base")
    if active is not None:
        try:
            App.setActiveDocument(active.Name)
        except Exception as _fw_err:
            _fw_log("multiradius.py:95", _fw_err)
    return _scratch


def per_edge(shape, kind, edges):
    """shape filleted ("Fillet") or chamfered ("Chamfer") edge by edge: edges = [(edge index
    in shape, 1-based, size 1, size 2)]. A chamfer's size 1 is on the edge's first face
    (shape.ancestorsOfType(edge, Part.Face)[0])."""
    scratch = _scratch_doc()
    b, f = scratch.getObject("Base"), scratch.getObject(kind)
    if f is None:       # a scratch document from before Chamfer was added
        f = scratch.addObject("Part::" + kind, kind)
        f.Base = b
    b.Shape = _plain(shape)
    f.Edges = [(i, float(r1), float(r2)) for i, r1, r2 in edges]
    # this one feature only: the scratch document's other one (a Chamfer for a fillet) would
    # recompute on the new base too and fill the notifier with "There are no suitable edges
    # for chamfer or fillet" (ChatGPT F11-05)
    try:
        scratch.recompute([f])
    except Exception:
        scratch.recompute()
    out = f.Shape.copy()
    ok = f.isValid() and not out.isNull() and out.isValid()
    b.Shape = Part_empty()
    _not_modified(scratch)
    if ok:
        from . import filletrescue
        try:
            ok = filletrescue.plausible(shape, out, [shape.Edges[i - 1] for i, r1, r2 in edges])
        except Exception as _fw_err:
            _fw_log("multiradius.py:126", _fw_err)
    if not ok:
        raise RuntimeError("The %s could not be made at these sizes: try smaller ones." % kind.lower())
    if len(out.Solids) == 1:
        out = out.Solids[0]
    return out


def _plain(shape):
    """shape without the element names of the feature that made it: Part::Fillet looks its
    edges up by those names and finds none for a shape filleted once already (Corner tab)."""
    import Part
    try:
        out = Part.Shape()
        out.importBrepFromString(shape.exportBrepToString())
        return out
    except Exception:
        return shape


def multi_fillet(shape, pairs):
    """shape with a fillet of radius r on edge i for every (i, r)."""
    if not pairs:
        raise RuntimeError("Select items to fillet.")
    if min(r for i, r in pairs) <= 0:
        raise RuntimeError("Radii must be more than zero.")
    try:
        return per_edge(shape, "Fillet", [(i, r, r) for i, r in pairs])
    except RuntimeError:

        # Keep surface / Keep edge), three or more edges into one corner (filletrescue.py)
        from . import filletrescue
        try:
            return filletrescue.rescue(shape, pairs)[0]
        except Exception as _fw_err:
            _fw_log("multiradius.py:161", _fw_err)
        raise


def _chains(shape, idx):
    """idx (1-based edge indices) in groups of edges that touch end to end: a loop or a tangent
    chain is rounded in one go."""
    groups = []
    for i in idx:
        pts = [v.Point for v in shape.Edges[i - 1].Vertexes]
        hit = [g for g in groups if any(p.distanceToPoint(q) < 1e-6 for p in pts for q in g[1])]
        new = ([i], list(pts))
        for g in hit:
            new[0].extend(g[0])
            new[1].extend(g[1])
            groups.remove(g)
        groups.append(new)
    return [sorted(g[0]) for g in groups]


def _mid(e):
    return e.valueAt((e.FirstParameter + e.LastParameter) / 2)


def _find(shape, point):
    """The 1-based index of shape's edge through point (an earlier round trims edges, never
    moves their middles), or None."""
    import Part
    v, best = Part.Vertex(point), None
    for j, e in enumerate(shape.Edges, 1):
        bb = e.BoundBox
        if (bb.Center - point).Length > bb.DiagonalLength / 2 + 1e-4:
            continue
        d = e.distToShape(v)[0]
        if d < 1e-5 and (best is None or d < best[0]):
            best = (d, j)
    return best and best[1]


def _pass(shape, found):
    """One pass: OpenCascade's own fillet straight on the shape when the radii are the same (no
    scratch document: inside a recompute its later rounds came back refused), else multi_fillet."""
    radii = set(r for j, r in found)
    if len(radii) > 1:
        return multi_fillet(shape, found)
    edges = [shape.Edges[j - 1] for j, r in found]
    out = shape.makeFillet(radii.pop(), edges)
    if out.isNull() or not out.isValid() or not out.Solids:
        raise RuntimeError("refused")
    from . import filletrescue
    if not filletrescue.plausible(shape, out, edges):
        raise RuntimeError("refused")
    return out.Solids[0] if len(out.Solids) == 1 else out


def _healed(shape):
    ""


    try:
        if shape.isValid():
            return shape
        fixed = shape.copy()
        fixed.fix(1e-7, 1e-7, 1e-7)
        if fixed.isValid():
            return fixed
    except Exception as _fw_err:
        _fw_log("multiradius.py:228", _fw_err)
    return shape


def in_passes(shape, pairs):
    ""



    radius = dict(pairs)
    chains = [[(_mid(shape.Edges[i - 1]), radius[i], i) for i in c] for c in _chains(shape, [i for i, r in pairs])]
    state = {"shape": _healed(shape), "passes": 0, "bad": []}

    def run(groups):
        cur = state["shape"]
        items = [x for g in groups for x in g]
        found = [(_find(cur, p), r) for p, r, i in items]
        if all(j is not None for j, r in found):
            try:
                state["shape"] = _pass(cur, found)
                state["passes"] += 1
                return
            except Exception as _fw_err:
                _fw_log("multiradius.py:251", _fw_err)
        if len(groups) == 1:
            if all(j is not None for j, r in found):
                from . import filletrescue
                try:
                    state["shape"] = filletrescue.rescue(cur, found)[0]
                    state["passes"] += 1
                    return
                except Exception as _fw_err:
                    _fw_log("multiradius.py:260", _fw_err)
            state["bad"] += [i for p, r, i in items]
            return
        h = len(groups) // 2
        run(groups[:h])
        run(groups[h:])

    run(chains)
    if state["bad"]:
        bad = ["Edge%d" % i for i in sorted(state["bad"])]
        names = ", ".join(bad[:8]) + (" and %d more" % (len(bad) - 8) if len(bad) > 8 else "")
        one = len(bad) == 1
        raise RuntimeError("The fillet could not be made at this size on %s: try a smaller value, or leave %s out."
                           % (names, "it" if one else "them"))
    return state["shape"], state["passes"]


def _not_modified(doc):
    """The scratch document never asks to be saved (the close prompt lists modified ones)."""
    try:
        import FreeCADGui as Gui
        g = Gui.getDocument(doc.Name)
        if g is not None:
            g.Modified = False
    except Exception as _fw_err:
        _fw_log("multiradius.py:285", _fw_err)


def Part_empty():
    import Part
    return Part.Shape()


class MultiRadiusFeature:
    def __init__(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def setup(self, obj):
        props = obj.PropertiesList
        if "Base" not in props:
            obj.addProperty("App::PropertyLinkSub", "Base", "Fillet", "Items to fillet")
        if "Radius" not in props:
            obj.addProperty("App::PropertyLength", "Radius", "Fillet", "Radius of a new item")
            obj.Radius = 1.0
        if "ItemRadii" not in props:
            obj.addProperty("App::PropertyFloatList", "ItemRadii", "Fillet",
                            "Each item's radius, in mm, in the order of Base")
        if "InPasses" not in props:
            obj.addProperty("App::PropertyBool", "InPasses", "Fillet",
                            "A plain fillet FreeCAD makes a few chains at a time where OpenCascade "
                            "refuses all the edges in one go")
            obj.setEditorMode("InPasses", 2)

    def execute(self, obj):
        base = obj.BaseFeature.Shape if obj.BaseFeature is not None else None
        if base is None or base.isNull():
            raise RuntimeError("Fillet needs a part")
        source = obj.Base[0] if obj.Base else obj.BaseFeature
        subs = list(obj.Base[1]) if obj.Base else []
        if obj.Base and not subs:
            subs = [""]
        pairs = edge_radii(base, source.Shape, subs, list(obj.ItemRadii), obj.Radius.Value)
        self.passes = 1
        try:
            obj.Shape = multi_fillet(base, pairs)
        except RuntimeError:
            if len(pairs) < 2:
                raise
            shape, self.passes = in_passes(base, pairs)
            obj.Shape = shape

    def onDocumentRestored(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


class MultiRadiusView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        try:
            from . import icons
            icon = icons.family(ICON)
            if not icon.isNull():
                return icon
        except Exception as _fw_err:
            _fw_log("multiradius.py:357", _fw_err)
        return ""

    def claimChildren(self):
        return []

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        import FreeCADGui as Gui
        from . import filletpm
        if Gui.Control.activeDialog():
            return False
        return bool(filletpm.open_page(vobj.Object))

    def unsetEdit(self, vobj, mode=0):
        return True

    def doubleClicked(self, vobj):
        import FreeCADGui as Gui
        from . import filletpm
        if not Gui.Control.activeDialog():
            filletpm.open_page(vobj.Object)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def setup_new(obj):
    MultiRadiusFeature(obj)
    if App.GuiUp:
        MultiRadiusView(obj.ViewObject)
    return obj


def new(body, name="Fillet"):
    label = None
    try:
        from . import naming
        # counted before the object exists: its own FreeCAD label ("Fillet001" once a removed
        # one held "Fillet") read as Fillet1 and made it Fillet2
        label = naming.next_label(body.Document, "Fillet")
    except Exception as _fw_err:
        _fw_log("multiradius.py:404", _fw_err)
    obj = body.newObject(TYPE, name)
    setup_new(obj)
    if label:
        obj.Label = label
    return obj
