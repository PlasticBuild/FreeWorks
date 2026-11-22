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

SEEDS = "FwRefSeeds"
COPIES = "FwRefCopies"
DATUMS = ("PartDesign::Plane", "PartDesign::Line", "PartDesign::Point")
V = App.Vector


def is_datum(obj):
    return obj is not None and obj.TypeId in DATUMS


def _skips(obj):
    try:
        from . import patterns
        return patterns.parse_skip(getattr(obj, "Skip", "") or "")
    except Exception:
        return set()


def _dir(link):
    from . import patterns
    o, subs = link[0] if isinstance(link, list) else link
    return patterns.direction_of(o, subs[0] if subs else "")


def _axis(link):
    from . import patterns
    o, subs = link[0] if isinstance(link, list) else link
    return patterns.axis_of(o, subs[0] if subs else "")


def _native_linear(p):
    out = []
    skips = _skips(p)

    def steps(k):
        link = getattr(p, "Direction" if k == 1 else "Direction2", None)
        n = int(getattr(p, "Occurrences" if k == 1 else "Occurrences2", 1) or 1)
        if not link or n < 2:
            return None, 0.0, 1
        d = _dir(link)
        if getattr(p, "Reversed" if k == 1 else "Reversed2", False):
            d = d * -1
        mode = getattr(p, "Mode" if k == 1 else "Mode2", "Extent")
        if mode == "Spacing":
            s = float(getattr(p, "Offset" if k == 1 else "Offset2").Value)
        else:
            s = float(getattr(p, "Length" if k == 1 else "Length2").Value) / (n - 1)
        return d, s, n
    d1, s1, n1 = steps(1)
    d2, s2, n2 = steps(2)
    if d1 is None:
        return []
    for i in range(n1):
        for j in range(n2):
            if (i == 0 and j == 0) or (i + 1, j + 1) in skips:
                continue
            move = d1 * (s1 * i) + (d2 * (s2 * j) if d2 is not None else V())
            out.append(App.Placement(move, App.Rotation()))
    return out


def _native_polar(p):
    if not getattr(p, "Axis", None):
        return []
    point, axis = _axis(p.Axis)
    if p.Reversed:
        axis = axis * -1
    n = int(p.Occurrences)
    if n < 2:
        return []
    if getattr(p, "Mode", "Extent") == "Spacing":
        step = float(p.Offset.Value)
    else:
        total = float(p.Angle.Value)
        step = total / n if abs(total - 360.0) < 1e-6 else total / (n - 1)
    skips = {i for i, _j in _skips(p)}
    return [App.Placement(V(), App.Rotation(axis, step * k), point) for k in range(1, n) if (k + 1) not in skips]


def _plane_of(link):
    from . import patterns
    o, subs = link[0] if isinstance(link, list) else link
    return patterns.mirror_plane(o, subs[0] if subs else "")


def _mirror_matrices(p):
    """The mirror as reflection matrices (one per plane)."""
    out = []
    for name in ("MirrorPlane", "Plane"):
        link = getattr(p, name, None)
        if not link:
            continue
        try:
            point, n = _plane_of(link)
        except Exception:
            continue
        n = V(n).normalize()
        m = App.Matrix(1 - 2 * n.x * n.x, -2 * n.x * n.y, -2 * n.x * n.z, 0,
                       -2 * n.x * n.y, 1 - 2 * n.y * n.y, -2 * n.y * n.z, 0,
                       -2 * n.x * n.z, -2 * n.y * n.z, 1 - 2 * n.z * n.z, 0)
        d = point - m.multVec(point)
        m.A14, m.A24, m.A34 = d.x, d.y, d.z
        out.append(m)
        break
    return out


def moves(p):
    """('place', [Placement]) or ('mirror', [Matrix]) for every instance but the seed."""
    t = p.TypeId
    kind = getattr(p, "SWStyleKind", "")
    from . import patterns
    if t == "PartDesign::LinearPattern":
        return "place", _native_linear(p)
    if t == "PartDesign::PolarPattern":
        return "place", _native_polar(p)
    if t == "PartDesign::Mirrored":
        return "mirror", _mirror_matrices(p)
    if kind == patterns.LINEAR.internal:
        return "place", [pl for _i, _j, pl in patterns._linear_grid(p)]
    if kind == patterns.CIRCULAR.internal:
        return "place", [pl for _k, pl in patterns._circular_ring(p)]
    if kind == patterns.MIRROR.internal:
        return "mirror", _mirror_matrices(p)
    return "place", []


def _mirrored(m, place):
    """A datum's placement reflected: its origin reflected and its frame kept right-handed
    (the reflected Z, which is what a plane's normal and an axis' direction mean)."""
    base = m.multVec(place.Base)
    r = place.Rotation
    lin = App.Matrix(m)
    lin.A14 = lin.A24 = lin.A34 = 0
    z = lin.multVec(r.multVec(V(0, 0, 1)))
    x = lin.multVec(r.multVec(V(1, 0, 0)))
    y = z.cross(x)
    rot = App.Rotation(x, y, z, "ZXY")
    return App.Placement(base, rot)


def wanted(p):
    """[(seed, placement)] of every copy the pattern should have, in order."""
    seeds = [s for s in (getattr(p, SEEDS, None) or []) if is_datum(s)]
    if not seeds:
        return []
    try:
        kind, ms = moves(p)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: patterned reference geometry: %s\n" % error)
        return []
    out = []
    for s in seeds:
        for m in ms:
            out.append((s, _mirrored(m, s.Placement) if kind == "mirror" else m.multiply(s.Placement)))
    return out


def set_seeds(p, seeds):
    if SEEDS not in p.PropertiesList:
        p.addProperty("App::PropertyLinkListHidden", SEEDS, "FreeCAD", "Reference geometry patterned")
        p.addProperty("App::PropertyLinkListHidden", COPIES, "FreeCAD", "The patterned reference geometry")
    if list(getattr(p, SEEDS)) != list(seeds):
        setattr(p, SEEDS, list(seeds))


def _body(p):
    try:
        return p.getParentGeoFeatureGroup()
    except Exception:
        return None


def sync(p):
    """Makes, moves or removes the copies so they match the pattern. Returns the copies."""
    if SEEDS not in p.PropertiesList:
        return []
    want = wanted(p)
    have = [c for c in (getattr(p, COPIES) or []) if c is not None]
    body = _body(p)
    doc = p.Document
    out = []
    for k, (seed, place) in enumerate(want):
        c = have[k] if k < len(have) and have[k].TypeId == seed.TypeId else None
        if c is None:
            if body is None:
                break
            c = body.newObject(seed.TypeId, seed.Name + "_Pattern")
            c.MapMode = "Deactivated"
            c.Label = "%s (%s)" % (seed.Label, p.Label)
            for prop in ("ResizeMode", "Length", "Width"):
                try:
                    setattr(c, prop, getattr(seed, prop))
                except Exception as _fw_err:
                    _fw_log("refpattern.py:221", _fw_err)
            try:
                c.ViewObject.Visibility = seed.ViewObject.Visibility
            except Exception as _fw_err:
                _fw_log("refpattern.py:225", _fw_err)
        if not c.Placement.isSame(place, 1e-9):
            c.Placement = place
        out.append(c)
    for c in have:
        if c not in out:
            try:
                doc.removeObject(c.Name)
            except Exception as _fw_err:
                _fw_log("refpattern.py:234", _fw_err)
    if list(getattr(p, COPIES)) != out:
        setattr(p, COPIES, out)
    return out


def remove_copies(p):
    for c in list(getattr(p, COPIES, []) or []):
        try:
            p.Document.removeObject(c.Name)
        except Exception as _fw_err:
            _fw_log("refpattern.py:245", _fw_err)


class _Watch:
    """After each recompute of a document its patterns' copies follow (made, moved, removed);
    a deleted pattern's copies go. Done after the recompute, not inside it (objects are made)."""

    def __init__(self):
        self.busy = False
        self.orphans = []       # (document name, copy names) of deleted patterns

    def slotRecomputedDocument(self, doc):
        if self.busy:
            return
        self.busy = True
        moved = False
        try:
            for doc_name, names in self.orphans:
                if doc_name == doc.Name:
                    for n in names:
                        if doc.getObject(n) is not None:
                            doc.removeObject(n)
            self.orphans = [o for o in self.orphans if o[0] != doc.Name]
            for p in [o for o in doc.Objects if SEEDS in o.PropertiesList]:
                before = [(c.Name, App.Placement(c.Placement)) for c in (getattr(p, COPIES) or []) if c is not None]
                after = [(c.Name, c.Placement) for c in sync(p)]
                if len(before) != len(after) or any(a[0] != b[0] or not a[1].isSame(b[1], 1e-9) for a, b in zip(before, after)):
                    moved = True
        except Exception as error:
            App.Console.PrintLog("FreeCAD: patterned reference geometry: %s\n" % error)
        finally:
            self.busy = False
        if moved and App.GuiUp:
            try:
                from PySide import QtCore      # what sits on the copies follows them
                QtCore.QTimer.singleShot(0, lambda d=doc: d.recompute() if d.Name in App.listDocuments() else None)
            except Exception as _fw_err:
                _fw_log("refpattern.py:282", _fw_err)

    def slotDeletedObject(self, obj):
        try:
            if SEEDS in obj.PropertiesList:
                names = [c.Name for c in (getattr(obj, COPIES) or []) if c is not None]
                if names:
                    self.orphans.append((obj.Document.Name, names))
                    if App.GuiUp:
                        from PySide import QtCore
                        doc = obj.Document
                        QtCore.QTimer.singleShot(0, lambda d=doc: self.slotRecomputedDocument(d)
                                                 if d.Name in App.listDocuments() else None)
        except Exception as _fw_err:
            _fw_log("refpattern.py:296", _fw_err)


_watch = []


def install():
    if not _watch:
        _watch.append(_Watch())
        App.addDocumentObserver(_watch[0])
