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

PROP = "SWFlipSource"
AXIS = "SWFlipAxis"          # Groove: the source sketch's axis name ("Axis1") copied into the helper
LABEL = " Flip side"

_observer = None
_pending = set()


def helper_of(pocket):
    """The helper sketch the pocket's profile is, else None."""
    try:
        prof = pocket.Profile[0] if pocket.Profile else None
    except Exception:
        return None
    return prof if prof is not None and PROP in prof.PropertiesList else None


def source_of(pocket):
    h = helper_of(pocket)
    if h is not None:
        return h.getPropertyByName(PROP)
    try:
        return pocket.Profile[0] if pocket.Profile else None
    except Exception:
        return None


def _contours(pocket):
    """The pocket's Selected Contours profile object, else None."""
    try:
        from . import contours
        return contours.helper_of(pocket)
    except Exception:
        return None


def is_flipped(pocket):
    c = _contours(pocket)
    if c is not None:
        return bool(getattr(c, "FlipSide", False))
    return helper_of(pocket) is not None


def _edges(src):
    """The sketch's profile edges by their shape names: construction lines and points are not in the
    sketch's shape, so Edge<n> counts the other geometry only (a centreline drawn first no longer
    shifts every name by one)."""
    out = []
    for i, g in enumerate(src.Geometry):
        try:
            if src.getConstruction(i):
                continue
        except Exception as _fw_err:
            _fw_log("flipside.py:87", _fw_err)
        if type(g).__name__ == "Point":
            continue
        out.append("Edge%d" % (len(out) + 1))
    return out


def _square(h, base):
    """Corners of a square round the part, in the sketch's own coordinates."""
    V = App.Vector
    size = 100.0
    cx = cy = 0.0
    try:
        inv = h.getGlobalPlacement().inverse()
        shape = base.Shape.copy()
        shape.transformShape(inv.toMatrix())
        bb = shape.BoundBox
        size = max(bb.XLength, bb.YLength, 1.0)
        cx, cy = (bb.XMin + bb.XMax) / 2.0, (bb.YMin + bb.YMax) / 2.0
    except Exception as _fw_err:
        _fw_log("flipside.py:107", _fw_err)
    r = size + 10.0
    return [V(cx - r, cy - r, 0), V(cx + r, cy - r, 0), V(cx + r, cy + r, 0), V(cx - r, cy + r, 0)]


def _sketch_axis(sk, sub):
    """(point, direction) in sk's own coordinates of an axis named by sub, else None."""
    V = App.Vector
    if sub == "H_Axis":
        return V(0, 0, 0), V(1, 0, 0)
    if sub == "V_Axis":
        return V(0, 0, 0), V(0, 1, 0)
    lines = []
    if sub.startswith("Axis"):
        for i, g in enumerate(sk.Geometry):
            try:
                if sk.getConstruction(i) and type(g).__name__ == "LineSegment":
                    lines.append(g)
            except Exception as _fw_err:
                _fw_log("flipside.py:126", _fw_err)
        n = int(sub[4:] or 0)
    elif sub.startswith("Edge"):
        n = int(sub[4:]) - 1
        lines = list(sk.Geometry)
    else:
        return None
    if 0 <= n < len(lines) and type(lines[n]).__name__ == "LineSegment":
        g = lines[n]
        return V(g.StartPoint), V(g.EndPoint) - V(g.StartPoint)
    return None


def _axis_in(h, groove):
    """The groove's axis in the helper's coordinates (point, unit direction), z dropped, else None."""
    V = App.Vector
    try:
        ref = groove.ReferenceAxis
        obj, sub = (ref[0], (ref[1] or [""])[0]) if ref else (None, "")
    except Exception:
        obj, sub = None, ""
    p = d = None
    if obj is not None and obj.TypeId == "Sketcher::SketchObject":
        local = _sketch_axis(obj, sub) if obj is not h else None
        if obj is h and h.getPropertyByName(AXIS):
            local = _sketch_axis(h.getPropertyByName(PROP), h.getPropertyByName(AXIS))
            obj = h.getPropertyByName(PROP)
        elif obj is h:
            local = _sketch_axis(h, sub)
        if local is not None:
            pl = obj.getGlobalPlacement()
            p, d = pl.multVec(local[0]), pl.Rotation.multVec(local[1])
    if p is None:
        try:
            p, d = V(groove.Base), V(groove.Axis)
        except Exception:
            return None
    inv = h.getGlobalPlacement().inverse()
    p, d = inv.multVec(p), inv.Rotation.multVec(d)
    p.z = d.z = 0.0
    if d.Length < 1e-9:
        return None
    return p, d.normalize()


def _half(h, base, src, groove):
    """Corners of a rectangle from the groove's axis out past the part, on the profile's side, in the
    helper's coordinates; None when the axis is unknown."""
    V = App.Vector
    axis = _axis_in(h, groove)
    if axis is None:
        return None
    p, d = axis
    n = V(-d.y, d.x, 0)
    size, centre = 100.0, None
    inv = h.getGlobalPlacement().inverse()
    try:
        shape = (base if base is not None else src).Shape.copy()
        shape.transformShape(inv.toMatrix())
        bb = shape.BoundBox
        size = max(bb.XLength, bb.YLength, bb.ZLength, 1.0)
        centre = V((bb.XMin + bb.XMax) / 2.0, (bb.YMin + bb.YMax) / 2.0, 0)
    except Exception as _fw_err:
        _fw_log("flipside.py:189", _fw_err)
    try:
        # the side the profile is on: its edges' middle (src: the person's sketch, own coordinates)
        mids = [e.valueAt((e.FirstParameter + e.LastParameter) / 2.0) for e in src.Shape.Edges]
        if mids:
            m = sum(mids, V()) * (1.0 / len(mids))
            if (m - p).dot(n) < 0:
                n = n * -1
    except Exception as _fw_err:
        _fw_log("flipside.py:198", _fw_err)
    far = (centre - p).Length if centre is not None else 0.0
    r = size + far + 10.0
    a, b = p - d * r, p + d * r
    return [a, b, b + n * r, a + n * r]


def sync(h, pocket=None):
    """Rebuild the helper from its source sketch."""
    import Part
    src = h.getPropertyByName(PROP)
    if src is None:
        return
    for prop in ("AttachmentSupport", "MapMode", "AttachmentOffset", "MapReversed"):
        try:
            if getattr(h, prop) != getattr(src, prop):
                setattr(h, prop, getattr(src, prop))
        except Exception as _fw_err:
            _fw_log("flipside.py:216", _fw_err)
    try:
        h.recompute()
    except Exception as _fw_err:
        _fw_log("flipside.py:220", _fw_err)
    h.deleteAllGeometry()
    for _i in range(len(h.ExternalGeo)):
        if len(h.ExternalGeo) <= 2:      # the two axes come first
            break
        try:
            h.delExternal(len(h.ExternalGeo) - 3)
        except Exception as _fw_err:
            _fw_log("flipside.py:229", _fw_err)
            break
    for sub in _edges(src):
        try:
            h.addExternal(src.Name, sub, True)       # defining: part of the profile
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Flip side to cut: %s %s\n" % (sub, error))
    base = None
    if pocket is not None:
        base = getattr(pocket, "BaseFeature", None)
    if base is None:
        for o in h.InList:
            if PROP not in o.PropertiesList and getattr(o, "BaseFeature", None) is not None:
                base = o.BaseFeature
                break
    pts = None
    if pocket is not None and pocket.TypeId == "PartDesign::Groove":
        name = h.getPropertyByName(AXIS) if AXIS in h.PropertiesList else ""
        if name:
            line = _sketch_axis(src, name)
            if line is not None:
                import Part as _P
                h.addGeometry(_P.LineSegment(line[0], line[0] + line[1]), True)     # the helper's Axis0
        pts = _half(h, base, src, pocket)
    if pts is None:
        pts = _square(h, base) if base is not None else _square(h, src)
    for i in range(4):
        h.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]), False)


def set_flipped(pocket, on):
    """Flip side to cut on or off for a Pocket; True when it changed."""
    if bool(on) == is_flipped(pocket):
        return False
    doc = pocket.Document
    body = pocket.getParentGeoFeatureGroup()
    if _contours(pocket) is not None:

        from . import contours
        contours.set_options(pocket, FlipSide=bool(on))
        install()
        return True
    if on:
        src = pocket.Profile[0] if pocket.Profile else None
        if src is None or src.TypeId != "Sketcher::SketchObject" or body is None:
            raise RuntimeError("Flip side to cut needs a sketch as the profile.")
        h = doc.addObject("Sketcher::SketchObject", "FlipSide")
        body.insertObject(h, src, True)
        h.addProperty("App::PropertyLink", PROP, "FreeCAD", "The sketch this one is made from")
        h.setPropertyStatus(PROP, "Hidden")
        setattr(h, PROP, src)
        h.Label = src.Label + LABEL
        if pocket.TypeId == "PartDesign::Groove":
            h.addProperty("App::PropertyString", AXIS, "FreeCAD", "The source sketch's axis this one copies")
            h.setPropertyStatus(AXIS, "Hidden")
            try:
                ref = pocket.ReferenceAxis
                sub = (ref[1] or [""])[0] if ref and ref[0] is src else ""
            except Exception:
                sub = ""
            if sub.startswith("Axis"):
                setattr(h, AXIS, sub)
        sync(h, pocket)
        pocket.Profile = h
        _move_refs(pocket, src, h)
        try:
            h.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("flipside.py:295", _fw_err)
    else:
        h = helper_of(pocket)
        src = h.getPropertyByName(PROP)
        pocket.Profile = src
        _move_refs(pocket, h, src)
        try:
            body.removeObject(h)
        except Exception as _fw_err:
            _fw_log("flipside.py:304", _fw_err)
        doc.removeObject(h.Name)
    install()
    return True


def _move_refs(pocket, old, new):
    """The Pocket's direction (its sketch normal, an axis of the sketch) follows the profile."""
    for prop in ("ReferenceAxis",):
        try:
            ref = getattr(pocket, prop)
            if not ref or ref[0] is not old:
                continue
            subs = list(ref[1])
            sub = subs[0] if subs else ""
            if sub.startswith("Edge"):
                continue        # a line of the person's sketch: the groove keeps it there
            if sub.startswith("Axis"):
                if AXIS in new.PropertiesList:
                    subs = ["Axis0"]            # the copied centreline is the helper's only one
                elif AXIS in old.PropertiesList and old.getPropertyByName(AXIS):
                    subs = [old.getPropertyByName(AXIS)]
            setattr(pocket, prop, (new, subs))
        except Exception as _fw_err:
            _fw_log("flipside.py:328", _fw_err)


class _Observer:
    """The person's sketch changed: its helpers follow."""

    def slotChangedObject(self, obj, prop):
        if prop == "ReferenceAxis":
            self._axis_moved(obj)
            return
        try:
            if prop not in ("Geometry", "AttachmentSupport", "AttachmentOffset", "MapMode") or \
                    obj.TypeId != "Sketcher::SketchObject" or PROP in obj.PropertiesList:
                return
            if obj.Document.Restoring:
                return
        except Exception:
            return
        helpers = [o for o in obj.InList if PROP in o.PropertiesList and o.getPropertyByName(PROP) is obj]
        if not helpers:
            return
        key = (obj.Document.Name, obj.Name)
        if key in _pending:
            return
        _pending.add(key)
        try:
            from PySide import QtCore
            QtCore.QTimer.singleShot(0, lambda: _resync(key))
        except Exception:
            _pending.discard(key)

    def _axis_moved(self, obj):
        """A flipped Cut-Revolve got another axis: its outside rectangle follows."""
        try:
            if obj.TypeId != "PartDesign::Groove" or obj.Document.Restoring or helper_of(obj) is None:
                return
        except Exception:
            return
        key = ("axis", obj.Document.Name, obj.Name)
        if key in _pending:
            return
        _pending.add(key)
        try:
            from PySide import QtCore
            QtCore.QTimer.singleShot(0, lambda: _resync_axis(key))
        except Exception:
            _pending.discard(key)


def _resync_axis(key):
    _pending.discard(key)
    try:
        groove = App.getDocument(key[1]).getObject(key[2])
        h = helper_of(groove)
    except Exception:
        return
    if h is None:
        return
    try:
        ref = groove.ReferenceAxis
        src = h.getPropertyByName(PROP)
        if ref and ref[0] is src and (ref[1] or [""])[0].startswith("Axis"):
            setattr(h, AXIS, ref[1][0])         # a centreline of the person's sketch: copy that one
            sync(h, groove)
            groove.ReferenceAxis = (h, ["Axis0"])
        else:
            if ref and ref[0] is not h:
                setattr(h, AXIS, "")
            sync(h, groove)
        groove.Document.recompute()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Flip side to cut axis: %s\n" % error)


def _resync(key):
    _pending.discard(key)
    try:
        doc = App.getDocument(key[0])
        src = doc.getObject(key[1])
    except Exception as _fw_err:
        _fw_log("flipside.py:410", _fw_err)
        return
    if src is None:
        return
    changed = False
    for h in [o for o in src.InList if PROP in o.PropertiesList and o.getPropertyByName(PROP) is src]:
        if len(_edges(src)) != len(h.ExternalGeo) - 2:
            pocket = next((o for o in h.InList if getattr(o, "Profile", None) and o.Profile[0] is h), None)
            sync(h, pocket)
            changed = True
    if changed:
        doc.recompute()


def install():
    global _observer
    if _observer is None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)
