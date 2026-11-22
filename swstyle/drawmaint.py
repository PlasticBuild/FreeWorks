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

import os

import FreeCAD as App
import FreeCADGui as Gui

DANGLING = (0.5, 0.5, 0.0)
DETACHED_META = "FreeWorksDetached"


# --------------------------------------------------------------------------- dangling dimensions
def _ref_ok(dim, view, sub):
    try:
        if sub.startswith("Edge"):
            e = view.getEdgeByIndex(int(sub[4:]))
            if e is None:
                return False
            if dim.Type in ("Diameter", "Radius"):
                return type(e.Curve).__name__ == "Circle"
            return e.Length > 1e-9
        if sub.startswith("Vertex"):
            return view.getVertexByIndex(int(sub[6:])) is not None
    except Exception:
        return False
    return True


def is_dangling(dim):
    refs = list(getattr(dim, "References2D", []) or [])
    if not refs:
        return False                    # a 3D (model) dimension or one still being made
    for view, subs in refs:
        if view is None:
            return True
        try:
            if not view.getVisibleEdges() and not view.getHiddenEdges():
                return False            # the view is not drawn yet: nothing to judge
        except Exception:
            return False
        for sub in (subs if isinstance(subs, (list, tuple)) else (subs,)):
            if sub and not _ref_ok(dim, view, sub):
                return True
    return False


# --------------------------------------------------------------------------- keeping dimensions on their geometry
# TechDraw names a view's edges and points by index, and the indices move when the model changes (a component

# keeps it on its own edge, or shows it dangling. Each reference keeps a print of its geometry; when the geometry
# at the index is no longer it, the same geometry is looked for elsewhere in the view and the dimension moved there.
def _print(view, sub):
    try:
        if sub.startswith("Edge"):
            e = view.getEdgeByIndex(int(sub[4:]))
            if e is None:
                return None
            c = type(e.Curve).__name__
            a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
            if c == "Circle":
                k = (round(e.Curve.Center.x, 3), round(e.Curve.Center.y, 3), round(e.Curve.Radius, 3))
            else:
                k = tuple(sorted([(round(a.x, 3), round(a.y, 3)), (round(b.x, 3), round(b.y, 3))]))
            return "%s|%s|%s" % (c, round(e.Length, 3), k)
        if sub.startswith("Vertex"):
            v = view.getVertexByIndex(int(sub[6:]))
            if v is None:
                return None
            return "Vertex|%s|%s" % (round(v.Point.x, 3), round(v.Point.y, 3))
    except Exception:
        return None
    return None


def _kind(pr):
    return pr.split("|")[0] if pr else ""


def _direction(view, sub):
    try:
        e = view.getEdgeByIndex(int(sub[4:]))
        d = e.Vertexes[-1].Point - e.Vertexes[0].Point
        return (round(abs(d.x) / d.Length, 3), round(abs(d.y) / d.Length, 3)) if d.Length > 1e-9 else None
    except Exception:
        return None


def _find(view, pr, sub):
    """The index name of the view's edge (or point) whose print is pr, else None."""
    kind = "Vertex" if sub.startswith("Vertex") else "Edge"
    i = 0
    while i < 100000:
        name = "%s%d" % (kind, i)
        try:
            ok = (view.getVertexByIndex(i) if kind == "Vertex" else view.getEdgeByIndex(i)) is not None
        except Exception:
            ok = False
        if not ok:
            return None
        if _print(view, name) == pr:
            return name
        i += 1
    return None


def _sources(names):
    """The shapes the referenced views draw (their Source names), to tell a model edit from a shape swap."""
    out = []
    for view, _s in names:
        try:
            out += [o.Name for o in list(view.Source or []) + list(getattr(view, "XSource", []) or [])]
        except Exception as _fw_err:
            _fw_log("drawmaint.py:sources", _fw_err)
    return ",".join(sorted(set(out)))


def shape_swapped(view):
    ""


    for dim in view.Document.Objects:
        if dim.TypeId != "TechDraw::DrawViewDimension" or "SWRefSource" not in dim.PropertiesList:
            continue
        if any(v is view for v, _s in (dim.References2D or [])):
            dim.SWRefSource = ""


def keep_references(dim):
    """Keeps dim on the geometry it was put on (see above). Returns "ok", "moved" or "dangling".
    Only its own bookkeeping (SWRefPrints, SWRefSource) changed: the dimension is left as untouched as it was,
    so a rebuilt drawing does not ask "rebuild before saving?" at every Ctrl+S (it ran after each recompute)."""
    was = "Touched" in (dim.State or [])
    state = _keep_references(dim)
    if state != "moved" and not was and "Touched" in (dim.State or []):
        try:
            dim.purgeTouched()
        except Exception as _fw_err:
            _fw_log("drawmaint.py:keep_references purge", _fw_err)
    return state


def _keep_references(dim):
    refs = list(getattr(dim, "References2D", []) or [])
    if not refs:
        return "ok"
    if "SWRefPrints" not in dim.PropertiesList:
        dim.addProperty("App::PropertyStringList", "SWRefPrints", "FreeCAD", "the geometry each reference is on")
        dim.setPropertyStatus("SWRefPrints", "Hidden")
    old = list(dim.SWRefPrints or [])
    names = []
    for view, subs in refs:
        for sub in (subs if isinstance(subs, (list, tuple)) else (subs,)):
            names.append((view, sub))
    src = _sources(names)
    if "SWRefSource" not in dim.PropertiesList:
        dim.addProperty("App::PropertyString", "SWRefSource", "FreeCAD", "what the referenced views show")
        dim.setPropertyStatus("SWRefSource", "Hidden")
        dim.SWRefSource = src
    swapped = dim.SWRefSource != src            # another shape in the view (a broken-out section): no model edit
    if len(old) != len(names):                  # first look (or references changed): remember what they are on
        dim.SWRefPrints = [_print(v, s) or "" for v, s in names]
        dim.SWRefSource = src
        return "ok"
    new_names, prints, state = [], [], "ok"
    for (view, sub), pr in zip(names, old):
        now = _print(view, sub) if view is not None and sub else None
        if not pr or now == pr:
            new_names.append(sub)
            prints.append(now or pr)
            continue
        there = _find(view, pr, sub) if view is not None else None
        if there is not None:                   # the same geometry under another index: follow it
            new_names.append(there)
            prints.append(pr)
            state = "moved"
            continue
        if not swapped and now and _kind(now) == _kind(pr) and (not sub.startswith("Edge") or _kind(pr) != "Line" or
                                                                _direction(view, sub) is not None):
            new_names.append(sub)               # the model edited (a length, a radius): the same edge changed
            prints.append(now)
            continue
        new_names.append(sub)
        prints.append(pr)
        state = "dangling"
    if state == "moved":
        it = iter(new_names)
        fixed = []
        for view, subs in refs:
            if isinstance(subs, (list, tuple)):
                fixed.append((view, [next(it) for _s in subs]))
            else:
                fixed.append((view, next(it)))
        dim.References2D = fixed
    if list(dim.SWRefPrints or []) != list(prints):      # the same again: no write (it set the drawing modified)
        dim.SWRefPrints = prints
    if state != "dangling" and dim.SWRefSource != src:
        dim.SWRefSource = src                   # on its geometry again: later changes are model edits
    return state


def dangling_color():
    """Options > Colors > Dimensions, Dangling (when set), else olive."""
    try:
        from . import paths
        u = paths.params().GetUnsigned("DanglingColor", 0)
    except Exception:
        u = 0
    if not u:
        return DANGLING
    return (round(((u >> 24) & 255) / 255.0, 3), round(((u >> 16) & 255) / 255.0, 3), round(((u >> 8) & 255) / 255.0, 3))


OVERRIDDEN = (0.0, 0.5, 0.5)        # dimensions whose value is overridden (Options > Colors > Dimensions, Overridden)


def overridden_color():
    ""
    try:
        from . import paths
        u = paths.params().GetUnsigned("OverriddenColor", 0)
    except Exception:
        u = 0
    if not u:
        return OVERRIDDEN
    return (round(((u >> 24) & 255) / 255.0, 3), round(((u >> 16) & 255) / 255.0, 3), round(((u >> 8) & 255) / 255.0, 3))


def paint_overridden(dim):
    ""


    vo = getattr(dim, "ViewObject", None)
    if vo is None or "Color" not in vo.PropertiesList:
        return
    on = bool(getattr(dim, "SWOverride", ""))
    if on:
        try:
            from . import drawdocprops
            on = bool(drawdocprops.row(dim.Document, "Dimensions",
                                       "Highlight overridden dimensions in a different color", True))
        except Exception as _fw_err:
            _fw_log("drawmaint.py:214", _fw_err)
    if on and "SWDangleColor" in dim.PropertiesList:
        return                       # dangling wins: its colour says the reference is gone
    if on:
        if "SWOverColor" not in dim.PropertiesList:
            dim.addProperty("App::PropertyString", "SWOverColor", "FreeCAD", "colour before the override")
            dim.setPropertyStatus("SWOverColor", "Hidden")
            dim.SWOverColor = ",".join("%g" % c for c in tuple(vo.Color)[:3])
        vo.Color = overridden_color()
    elif "SWOverColor" in dim.PropertiesList:
        try:
            vo.Color = tuple(float(c) for c in dim.SWOverColor.split(","))
        except Exception as _fw_err:
            _fw_log("drawmaint.py:227", _fw_err)
        dim.removeProperty("SWOverColor")


def paint_all_overridden(doc):
    for o in doc.Objects:
        if o.TypeId == "TechDraw::DrawViewDimension" and (getattr(o, "SWOverride", "") or "SWOverColor" in o.PropertiesList):
            paint_overridden(o)


def hide_dangling(doc):
    """Document Properties > Detailing: Hide dangling dimensions and annotations."""
    try:
        from . import optionspages
        return bool(optionspages.doc_value(doc, "Detailing", "Hide dangling dimensions and annotations", False))
    except Exception:
        return False


def _hide(obj, on, why="SWHiddenDangling"):
    """Hides obj for a reason (dangling, its component suppressed) and shows it again when the reason goes."""
    vo = getattr(obj, "ViewObject", None)
    if vo is None:
        return
    if on:
        if why not in obj.PropertiesList:
            obj.addProperty("App::PropertyBool", why, "FreeCAD", "hidden by FreeCAD while this holds")
            obj.setPropertyStatus(why, "Hidden")
        if not getattr(obj, why):
            setattr(obj, why, True)
            vo.Visibility = False
    elif getattr(obj, why, False):
        setattr(obj, why, False)
        vo.Visibility = True


def _paint(dim, on):
    vo = getattr(dim, "ViewObject", None)
    if vo is None or "Color" not in vo.PropertiesList:
        return
    colour = dangling_color()
    if on:
        if "SWDangleColor" not in dim.PropertiesList:
            dim.addProperty("App::PropertyString", "SWDangleColor", "FreeCAD", "colour before it dangled")
            dim.setPropertyStatus("SWDangleColor", "Hidden")
            dim.SWDangleColor = ",".join("%g" % c for c in tuple(vo.Color)[:3])
        if tuple(round(c, 3) for c in tuple(vo.Color)[:3]) != colour:
            vo.Color = colour
    elif "SWDangleColor" in dim.PropertiesList:
        try:
            vo.Color = tuple(float(c) for c in dim.SWDangleColor.split(","))
        except Exception as _fw_err:
            _fw_log("drawmaint.py:279", _fw_err)
        dim.removeProperty("SWDangleColor")


def _keep_value(dim, bad):
    ""


    try:
        frozen = getattr(dim, "SWFrozenSpec", None)
        if not bad:
            if frozen is not None and getattr(dim, "SWFrozen", False):
                dim.FormatSpec = frozen             # FormatSpec first, then Arbitrary off (TechDraw warns otherwise)
                dim.Arbitrary = bool(getattr(dim, "SWFrozenArbitrary", False))
                dim.SWFrozen = False
            if not dim.Arbitrary:
                v = dim.getRawValue()
                if abs(v) > 1e-9:
                    if "SWLastValue" not in dim.PropertiesList:
                        dim.addProperty("App::PropertyFloat", "SWLastValue", "FreeCAD", "last value on its geometry")
                        dim.setPropertyStatus("SWLastValue", "Hidden")
                    if abs(dim.SWLastValue - v) > 1e-9:
                        dim.SWLastValue = v
            return
        if getattr(dim, "SWFrozen", False) or "SWLastValue" not in dim.PropertiesList:
            return
        spec = dim.FormatSpec
        import re
        m = re.search(r"%[-+0#]*\d*(?:\.(\d+))?[wfgWFG]", spec)
        if not m:
            return
        prec = int(m.group(1)) if m.group(1) is not None else 2
        text = ("%." + str(prec) + "f") % dim.SWLastValue
        if "w" in m.group(0).lower():
            text = text.rstrip("0").rstrip(".") if "." in text else text
        for n, t in (("SWFrozenSpec", "App::PropertyString"), ("SWFrozen", "App::PropertyBool"),
                     ("SWFrozenArbitrary", "App::PropertyBool")):
            if n not in dim.PropertiesList:
                dim.addProperty(t, n, "FreeCAD", "dangling dimension text")
                dim.setPropertyStatus(n, "Hidden")
        dim.SWFrozenSpec = spec
        dim.SWFrozenArbitrary = bool(dim.Arbitrary)
        dim.FormatSpec = spec[:m.start()] + text + spec[m.end():]
        dim.Arbitrary = True
        dim.SWFrozen = True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: dangling value: %s\n" % error)


def _remember_last(dim):
    """Keep a good dimension's value (SWLastValue) at each recompute, for _keep_value."""
    if dim.Arbitrary or is_dangling(dim):
        return
    v = dim.getRawValue()
    if abs(v) > 1e-9:
        if "SWLastValue" not in dim.PropertiesList:
            dim.addProperty("App::PropertyFloat", "SWLastValue", "FreeCAD", "last value on its geometry")
            dim.setPropertyStatus("SWLastValue", "Hidden")
        if abs(dim.SWLastValue - v) > 1e-9:
            dim.SWLastValue = v


def dangling(doc):
    """The drawing's dangling dimensions (drawn in the dangling colour, or hidden with Hide dangling dimensions
    and annotations; the others back as they were). Dimensions follow their geometry first (keep_references),
    and balloons of suppressed components are hidden (component_annotations)."""
    out = []
    hide = hide_dangling(doc)
    for o in doc.Objects:
        if o.TypeId != "TechDraw::DrawViewDimension":
            continue
        try:
            drawn = all(v is not None and (v.getVisibleEdges() or v.getHiddenEdges())
                        for v, _s in (o.References2D or []))
        except Exception:
            drawn = False
        state = keep_references(o) if drawn else "ok"
        bad = state == "dangling" or is_dangling(o)
        _keep_value(o, bad)
        _paint(o, bad and not hide)
        _hide(o, bad and hide)
        if bad:
            out.append(o)
    try:
        component_annotations(doc)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: balloons of suppressed components: %s\n" % error)
    return out


def component_annotations(doc):
    ""

    hidden = []
    colour = dangling_color()
    for b in doc.Objects:
        name = getattr(b, "SWBalloonComponent", "") or ""
        if not name or getattr(b, "SWAnnotation", "") != "Balloon":
            continue
        view = doc.getObject(getattr(b, "SWView", "") or "")
        comp = None
        try:
            from . import asmdrawing as AD
            asm = AD.assembly_of_view(view) if view is not None else None
            comp = asm.Document.getObject(name) if asm is not None else None
        except Exception:
            asm = None
        if asm is None:
            continue
        try:
            from . import asmcomp
            off = comp is not None and asmcomp.is_suppressed(comp)
        except Exception:
            off = False
        _hide(b, off, "SWHiddenSuppressed")
        if off:
            hidden.append(b)
        gone = comp is None
        try:
            if gone and "SWDangling" not in b.PropertiesList:
                b.addProperty("App::PropertyBool", "SWDangling", "FreeCAD", "its component is gone")
                b.setPropertyStatus("SWDangling", "Hidden")
            if gone and not b.SWDangling:
                b.SWDangling = True
                hexc = "#%02x%02x%02x" % tuple(int(c * 255) for c in colour)
                import re
                b.Symbol = re.sub(r'(stroke|fill)="#(?:000|000000)"', r'\1="%s"' % hexc, b.Symbol)
        except Exception as _fw_err:
            _fw_log("drawmaint.py:407", _fw_err)
    return hidden


# --------------------------------------------------------------------------- Detached drawing
def is_detached(doc):
    try:
        return dict(doc.Meta).get(DETACHED_META) == "1"
    except Exception:
        return False


def save_detached(doc, path):
    """Save As > Detached Drawing: a copy at path whose views show copies of their models' shapes kept in the
    drawing file itself, so it opens (and prints) without the models. The open drawing stays as it is."""
    doc.saveCopy(path)
    det = App.openDocument(path, hidden=True)
    try:
        copies = {}
        for v in det.Objects:
            if not v.isDerivedFrom("TechDraw::DrawViewPart"):
                continue
            src = list(getattr(v, "XSource", []) or [])
            if not src:
                continue
            mine = []
            for o in src:
                key = (o.Document.Name, o.Name)
                if key not in copies:
                    try:
                        shape = o.Shape.copy()
                    except Exception:
                        continue
                    f = det.addObject("Part::Feature", "Detached_" + o.Name)
                    f.Label = "%s (detached)" % o.Label
                    f.Shape = shape
                    f.addProperty("App::PropertyString", "SWDetachedFrom", "FreeCAD", "the model it came from")
                    f.SWDetachedFrom = "%s#%s" % (getattr(o.Document, "FileName", "") or o.Document.Name, o.Name)
                    copies[key] = f
                mine.append(copies[key])
            if mine:
                v.XSource = []
                v.Source = mine
        meta = dict(det.Meta)
        meta[DETACHED_META] = "1"
        det.Meta = meta
        det.recompute()
        det.save()
    finally:
        App.closeDocument(det.Name)
    return path


# --------------------------------------------------------------------------- changed dimensions on open
CHANGED_ROW = ("Colors", "Use specified color for changed drawing dimensions on open")
CHANGED = (0.0, 0.33, 1.0)          # Drawings, Changed dimensions (blue)


def changed_on_open():
    """Options > System Options > Colors: Use specified color for changed drawing dimensions on open (on)."""
    try:
        from . import optionspages
        return bool(optionspages.stored(CHANGED_ROW[0], CHANGED_ROW[1], False))
    except Exception:
        return True


def _value(dim):
    try:
        return float(dim.getRawValue())
    except Exception:
        return None


def remember_values(doc):
    """At save: each dimension's value, so the next open can tell which ones the model changed."""
    for o in doc.Objects:
        if o.TypeId != "TechDraw::DrawViewDimension":
            continue
        v = _value(o)
        if v is None:
            continue
        if "SWSavedValue" not in o.PropertiesList:
            o.addProperty("App::PropertyFloat", "SWSavedValue", "FreeCAD", "the value when the drawing was saved")
            o.setPropertyStatus("SWSavedValue", "Hidden")
        o.SWSavedValue = v
        _mark(o, "SWChangedColor", CHANGED, False)


def _mark(dim, prop, colour, on):
    vo = getattr(dim, "ViewObject", None)
    if vo is None or "Color" not in vo.PropertiesList:
        return
    if on:
        if prop not in dim.PropertiesList:
            dim.addProperty("App::PropertyString", prop, "FreeCAD", "colour before it was marked")
            dim.setPropertyStatus(prop, "Hidden")
            dim.setPropertyStatus(prop, "Transient")
            setattr(dim, prop, ",".join("%g" % c for c in tuple(vo.Color)[:3]))
        vo.Color = colour
    elif prop in dim.PropertiesList:
        try:
            vo.Color = tuple(float(c) for c in getattr(dim, prop).split(","))
        except Exception as _fw_err:
            _fw_log("drawmaint.py:511", _fw_err)
        dim.removeProperty(prop)


def mark_changed(doc):
    """On open: the dimensions whose value differs from the one kept at the last save, in the changed colour
    (when the Colors option is on). Returns them."""
    out = []
    if not changed_on_open():
        return out
    for o in doc.Objects:
        if o.TypeId != "TechDraw::DrawViewDimension" or "SWSavedValue" not in o.PropertiesList:
            continue
        v = _value(o)
        if v is None or is_dangling(o):
            continue
        if abs(v - float(o.SWSavedValue)) > 1e-6:
            _mark(o, "SWChangedColor", CHANGED, True)
            out.append(o)
    return out


def _after_open(name, tries=0):
    from PySide import QtCore
    try:
        doc = App.getDocument(name)
    except Exception:
        return
    dims = [o for o in doc.Objects if o.TypeId == "TechDraw::DrawViewDimension" and "SWSavedValue" in o.PropertiesList]
    if not dims:
        return
    views = {r[0].Name: r[0] for o in dims for r in (o.References2D or []) if r[0] is not None}
    if any(not (v.getVisibleEdges() or v.getHiddenEdges()) for v in views.values()) and tries < 30:
        QtCore.QTimer.singleShot(300, lambda: _after_open(name, tries + 1))     # the views are still being drawn
        return
    doc.recompute()
    mark_changed(doc)


def _marks_later(name, vname):
    try:
        from . import drawannot
        v = App.getDocument(name).getObject(vname)
        if v is not None and getattr(v, "SWCenterMarkAnchors", None) and drawannot.follow_center_marks(v):
            v.Document.recompute([v])
    except Exception as _fw_err:
        _fw_log("drawmaint.py:557", _fw_err)
    try:
        from . import drawannot
        doc = App.getDocument(name)
        # placed hole callouts follow their holes when the view redraws (a signature per callout: no loop)
        if any(getattr(o, "SWHoleCallout", False) for o in doc.Objects):
            drawannot.refresh_hole_callouts(doc)
    except Exception as _fw_err:
        _fw_log("drawmaint.py:_marks_later callouts", _fw_err)


_CHAMFERS_PENDING = set()


def _chamfers_later(name):
    _CHAMFERS_PENDING.discard(name)
    try:
        from . import drawdimtools
        drawdimtools.refresh_chamfers(App.getDocument(name))
        drawdimtools.refresh_arc_lengths(App.getDocument(name))
        drawdimtools.refresh_angular_running(App.getDocument(name))
        drawdimtools.refresh_linear_rounds(App.getDocument(name))
    except Exception as _fw_err:
        _fw_log("drawmaint.py:567", _fw_err)


class _Observer:
    def slotRecomputedObject(self, obj):
        try:
            if obj.isDerivedFrom("TechDraw::DrawViewPart"):
                page = _page_of(obj)
                if page is not None and getattr(page, "KeepUpdated", True):
                    _store(obj)
                name = obj.Document.Name
                from PySide import QtCore
                if name not in _CHAMFERS_PENDING:       # one pass for all the views of this recompute
                    _CHAMFERS_PENDING.add(name)
                    QtCore.QTimer.singleShot(0, lambda: _chamfers_later(name))
                vname = obj.Name
                QtCore.QTimer.singleShot(0, lambda: _marks_later(name, vname))
            elif obj.TypeId == "TechDraw::DrawViewDimension" and not getattr(obj, "SWFrozen", False):
                _remember_last(obj)     # the last value is known before a model edit takes its geometry away
        except Exception as _fw_err:
            _fw_log("drawmaint.py:585", _fw_err)

    def slotRecomputedDocument(self, doc):
        try:
            if not any(o.TypeId == "TechDraw::DrawPage" for o in doc.findObjects("TechDraw::DrawPage")):
                check_models(doc)
        except Exception as _fw_err:
            _fw_log("drawmaint.py:592", _fw_err)

    def slotStartSaveDocument(self, doc, path):
        try:
            if any(o.TypeId == "TechDraw::DrawPage" for o in doc.Objects):
                try:
                    from . import drawsheet
                    drawsheet.fields_current(doc)       # sheets behind the front one saved up to date
                except Exception as _fw_err:
                    _fw_log("drawmaint.py:601", _fw_err)
                remember_values(doc)
                keep_edge_tags(doc)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: dimension values at save: %s\n" % error)




# (Automatically update views off, or held on open) until the view is updated. A view keeps what it was
# projected from (SWModelSig: bounding box, faces and vertices of its sources); a sheet with Update View off shows
# a light hatch over each view whose models no longer match, drawn from the sheet's 1 s tick.
OUT_OF_DATE = {}        # (doc name, view name) -> (xmin, ymin, xmax, ymax) on the sheet


def _page_of(v):
    try:
        p = v.findParentPage()
        if p is not None:
            return p
    except Exception as _fw_err:
        _fw_log("drawmaint.py:621", _fw_err)
    return next((p for p in v.InListRecursive if p.isDerivedFrom("TechDraw::DrawPage")), None)


_SIG_CACHE = {}      # (document, object) -> (its shape, its part of the signature): counting faces is slow


def model_signature(v):
    from . import drawviews as DV
    out = []
    for o in DV.source_shapes(v):
        try:
            sh = o.Shape
            key = (o.Document.Name, o.Name)
            got = _SIG_CACHE.get(key)
            if got is None or not DV.same_shape(got[1], sh, got[0]):    # a Shape read is a new copy each time
                bb = sh.BoundBox
                got = (DV.SHAPE_GEN[0], sh, "%s:%.4g,%.4g,%.4g,%.4g,%.4g,%.4g:%d:%d" % (
                    o.Name, bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax, len(sh.Faces), len(sh.Vertexes)))
                if len(_SIG_CACHE) > 5000:     # a 301-part drawing has 4 x 301 sources
                    _SIG_CACHE.clear()
                _SIG_CACHE[key] = got
            out.append(got[2])
        except Exception:
            out.append(getattr(o, "Name", "?"))
    return "|".join(out)


def _store(v):
    sig = model_signature(v)
    if "SWModelSig" not in v.PropertiesList:
        v.addProperty("App::PropertyString", "SWModelSig", "FreeCAD", "what the view was projected from",
                      8 | 16, False, True)      # output, no recompute, hidden
    if v.SWModelSig != sig:
        v.SWModelSig = sig
    OUT_OF_DATE.pop((v.Document.Name, v.Name), None)


def is_out_of_date(v):
    sig = getattr(v, "SWModelSig", "")
    return bool(sig) and sig != model_signature(v)


_LATER = set()


def _shows(v, model_doc):
    """True when view v shows something of model_doc (directly, or through an assembly that uses it)."""
    from . import drawviews as DV
    for o in DV.source_shapes(v):
        d = getattr(o, "Document", None)
        if d is None:
            continue
        if d is model_doc:
            return True
        m = getattr(o, "SWModel", None)          # an assembly view's model part: the assembly and its parts
        md = getattr(m, "Document", None)
        if md is model_doc:
            return True
        if d is v.Document:
            continue
        try:
            if model_doc in d.getDependentDocuments():
                return True
        except Exception as _fw_err:
            _fw_log("drawmaint.py:686", _fw_err)
    return False


_TOUCH = {}


def update_later(doc, views=()):
    """Recompute drawing doc once, after the model's rebuild has finished (never inside it). views are touched
    then, not now: touched inside the model's rebuild they were drawn again from its shape as it was (bench 11-13)."""
    _TOUCH.setdefault(doc.Name, set()).update(v.Name for v in views)
    if doc.Name in _LATER:
        return
    _LATER.add(doc.Name)
    from PySide import QtCore

    def go(name=doc.Name):
        _LATER.discard(name)
        try:
            d = App.getDocument(name)
        except Exception:
            return
        try:
            objs = [d.getObject(n) for n in _TOUCH.pop(name, ())]
            objs = [o for o in objs if o is not None]
            for o in objs:
                o.touch()
            d.recompute()
            # the views drawn from them: projected once more when idle, as TechDraw skips a view's projection
            # while the one started by the model's own rebuild still runs (and keeps its old lines)
            from . import drawviews as DV
            views = [o for o in objs if o.isDerivedFrom("TechDraw::DrawViewPart")]
            parts = set(o.Name for o in objs if not o.isDerivedFrom("TechDraw::DrawViewPart"))
            if parts:
                views += [v for v in d.Objects if v.isDerivedFrom("TechDraw::DrawViewPart") and v not in views and
                          any(getattr(x, "Name", "") in parts for x in (getattr(v, "XSource", []) or []))]
            for v in views:
                DV._reproject_when_idle(v)
            names = [v.Name for v in views]
            # and once more a little later: without isWaitingForHlr (bench) the idle test above cannot tell that
            # the first projection still runs, and that one was made from the model as it was
            QtCore.QTimer.singleShot(AGAIN_MS, lambda: _again(name, names))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: drawing update: %s\n" % error)
    QtCore.QTimer.singleShot(0, go)


AGAIN_MS = 2500


def _again(name, names):
    try:
        d = App.getDocument(name)
        for n in names:
            v = d.getObject(n)
            if v is not None:
                v.touch()
        d.recompute()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: drawing update: %s\n" % error)


def check_models(model_doc=None):
    ""


    from . import drawviews as DV
    for doc in App.listDocuments().values():
        stale = []
        for page in [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage"]:
            held = not getattr(page, "KeepUpdated", True)
            for v in page.Views:
                if not v.isDerivedFrom("TechDraw::DrawViewPart"):
                    continue
                key = (doc.Name, v.Name)
                if not held:
                    OUT_OF_DATE.pop(key, None)
                    # TechDraw re-projects a view only when it is touched itself, not when its model in another
                    # document is rebuilt (bench 11-13: a part edit left the view's old lines, re-centred)
                    if model_doc is not None and _shows(v, model_doc):
                        stale.append(v)
                    continue
                src = DV.source_shapes(v)
                if model_doc is not None and not any(getattr(o, "Document", None) is model_doc for o in src):
                    continue
                if is_out_of_date(v):
                    try:
                        OUT_OF_DATE[key] = DV.view_box(v)
                    except Exception as _fw_err:
                        _fw_log("drawmaint.py:775", _fw_err)
                else:
                    OUT_OF_DATE.pop(key, None)
        if stale:
            update_later(doc, stale)


_HATCH = {}             # id(scene) -> {view name: our QGraphicsRectItem}


def paint_out_of_date(page):
    """The crosshatch over the out-of-date views of page's open sheet (our own items, not TechDraw's)."""
    from PySide import QtCore, QtGui, QtWidgets
    from . import drawings as D
    try:
        import TechDrawGui
        scene = TechDrawGui.getSceneForPage(page)
    except Exception:
        scene = None
    if scene is None:
        return
    try:
        import shiboken6 as shiboken
    except Exception:
        try:
            import shiboken2 as shiboken
        except Exception:
            shiboken = None
    mine = _HATCH.setdefault(id(scene), {})
    doc = page.Document
    want = {}
    if not getattr(page, "KeepUpdated", True):
        for v in page.Views:
            box = OUT_OF_DATE.get((doc.Name, v.Name))
            if box is not None:
                want[v.Name] = box
    for name in list(mine):
        it = mine[name]
        alive = shiboken is None or shiboken.isValid(it)
        if not alive or name not in want or it.data(3) != repr(want[name]):
            if alive:
                try:
                    scene.removeItem(it)
                except Exception as _fw_err:
                    _fw_log("drawmaint.py:819", _fw_err)
            del mine[name]
    for name, (a, b, c, d) in want.items():
        if name in mine:
            continue
        p0, p1 = D.to_scene(a - 2, d + 2), D.to_scene(c + 2, b - 2)
        it = QtWidgets.QGraphicsRectItem(QtCore.QRectF(p0, p1).normalized())
        brush = QtGui.QBrush(QtGui.QColor(120, 120, 120, 110), QtCore.Qt.DiagCrossPattern)
        brush.setTransform(QtGui.QTransform().scale(6, 6))
        it.setBrush(brush)
        pen = QtGui.QPen(QtGui.QColor(120, 120, 120, 160))
        pen.setCosmetic(True)
        it.setPen(pen)
        it.setZValue(1e6)
        it.setAcceptedMouseButtons(QtCore.Qt.NoButton)
        it.setAcceptHoverEvents(False)
        it.setData(0, "SWOutOfDate")
        it.setData(3, repr((a, b, c, d)))
        it.setToolTip("View out of date: Update View brings it up to date")
        scene.addItem(it)
        mine[name] = it
    detailing_notice(page, bool(want))


NOTICE = "SWOutOfDateNotice"
NOTICE_TEXT = "The drawing is out of date: a model has changed since its views were made. Resolve the drawing " \
              "to update it."


def detailing_notice(page, stale=None):
    """Detailing mode: the out-of-date notice across the top of the sheet while a model has changed, with a
    Resolve Drawing button; none otherwise."""
    from PySide import QtWidgets
    from . import drawings as D
    gv = D.page_view(page)
    if gv is None:
        return None
    doc = page.Document
    if stale is None:
        stale = any((doc.Name, v.Name) in OUT_OF_DATE for v in page.Views)
    on = bool(getattr(page, "SWDetailing", False)) and bool(stale)
    bar = gv.findChild(QtWidgets.QFrame, NOTICE)
    if not on:
        if bar is not None:
            bar.hide()
        return None
    if bar is None:
        bar = QtWidgets.QFrame(gv)
        bar.setObjectName(NOTICE)
        bar.setStyleSheet("QFrame#%s { background: #fff4c2; border: 1px solid #d9b100; }"
                          "QLabel { color: #3a3000; }" % NOTICE)
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(8, 3, 4, 3)
        label = QtWidgets.QLabel(NOTICE_TEXT, bar)
        label.setObjectName("SWOutOfDateText")
        lay.addWidget(label, 1)
        b = QtWidgets.QPushButton("Resolve Drawing", bar)
        b.setObjectName("SWOutOfDateResolve")
        dname = doc.Name

        def resolve():
            try:
                from . import drawdocprops
                drawdocprops.resolve_drawing(App.getDocument(dname))
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: Resolve Drawing: %s\n" % error)
        b.clicked.connect(resolve)
        lay.addWidget(b)
    bar.setGeometry(0, 0, gv.viewport().width(), bar.sizeHint().height())
    bar.show()
    bar.raise_()
    return bar


# FreeCAD 1.1 does not keep a cosmetic edge's tag in the file: every cosmetic line and circle comes back from an
# opened file with a new tag, so what the add-on keeps by tag (center marks, their anchors, centerlines, sketch
# entities on drawings...) no longer finds its edges. The tags in order are kept at save (SWEdgeTags) and every

_UUID = None


def keep_edge_tags(doc):
    for v in doc.Objects:
        try:
            if not v.isDerivedFrom("TechDraw::DrawViewPart"):
                continue
            tags = [e.Tag for e in v.CosmeticEdges]
            if not tags and "SWEdgeTags" not in v.PropertiesList:
                continue
            if "SWEdgeTags" not in v.PropertiesList:
                v.addProperty("App::PropertyStringList", "SWEdgeTags", "FreeCAD", "cosmetic edge tags at save")
                v.setPropertyStatus("SWEdgeTags", ["Hidden"])
            if list(v.SWEdgeTags) != tags:
                v.SWEdgeTags = tags
        except Exception as _fw_err:
            _fw_log("drawmaint.py:edgetags", _fw_err)


def restore_edge_tags(doc):
    ""
    import re
    global _UUID
    _UUID = _UUID or re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    remap = {}
    for v in doc.Objects:
        try:
            old = list(getattr(v, "SWEdgeTags", []) or [])
            if not old or not v.isDerivedFrom("TechDraw::DrawViewPart"):
                continue
            new = [e.Tag for e in v.CosmeticEdges]
            if len(new) == len(old):
                remap.update({a: b for a, b in zip(old, new) if a != b})
        except Exception as _fw_err:
            _fw_log("drawmaint.py:edgetags", _fw_err)
    if not remap:
        return 0
    sub = lambda text: _UUID.sub(lambda m: remap.get(m.group(0), m.group(0)), text)
    n = 0
    for o in doc.Objects:
        for p in o.PropertiesList:
            try:
                t = o.getTypeIdOfProperty(p)
                if t not in ("App::PropertyString", "App::PropertyStringList"):
                    continue
                val = getattr(o, p)
                if t == "App::PropertyString":
                    if _UUID.search(val or "") and sub(val) != val:
                        setattr(o, p, sub(val))
                        n += 1
                elif any(_UUID.search(x) for x in val):
                    out = [sub(x) for x in val]
                    if out != list(val):
                        setattr(o, p, out)
                        n += 1
            except Exception as _fw_err:
                _fw_log("drawmaint.py:edgetags", _fw_err)
    return n


def _restored(doc):
    from PySide import QtCore
    name = doc.Name
    try:
        restore_edge_tags(doc)      # before anything looks an edge up by its tag
    except Exception as _fw_err:
        _fw_log("drawmaint.py:edgetags", _fw_err)
    QtCore.QTimer.singleShot(1500, lambda: check_models())     # held sheets: which views are out of date
    QtCore.QTimer.singleShot(300, lambda: _after_open(name))


_INSTALLED = []


def _wrap_colors():
    try:
        from . import optionspages as OP
    except Exception:
        return
    old = OP._colors

    def _colors():
        groups = old()
        try:
            rows = groups[0][1]
            if not any(getattr(r, "text", None) == CHANGED_ROW[1] for r in rows):
                at = next((i + 1 for i, r in enumerate(rows) if getattr(r, "text", "") ==
                           "Use specified color for Shaded With Edges mode"), len(rows))
                rows.insert(at, OP.Later(CHANGED_ROW[1], True, CHANGED_ROW[0]))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Colors option: %s\n" % error)
        return groups
    OP._colors = _colors


def install():
    if _INSTALLED:
        return
    _INSTALLED.append(_Observer())
    App.addDocumentObserver(_INSTALLED[0])
    try:
        from . import restorehook            # the file has opened (FreeCAD 1.1 has no finish-restore slot)
        restorehook.on_restored(_restored)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: changed dimensions on open: %s\n" % error)
    _wrap_colors()
    try:
        from . import drawselfilter              # the Selection Filter toolbar on drawing sheets
        drawselfilter.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: drawing selection filters: %s\n" % error)
    try:
        from . import drawattach                 # annotations attached to views, Hide/Show Annotations
        drawattach.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: annotation attach: %s\n" % error)
