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
from PySide import QtCore

DRESS_UPS = {"PartDesign::Fillet", "PartDesign::Chamfer", "PartDesign::Draft",
             "PartDesign::Thickness"}
TOL = 1e-6

_observer = None


def install():
    global _observer
    if _observer is None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)


def uninstall():
    global _observer
    if _observer is not None:
        try:
            App.removeDocumentObserver(_observer)
        except Exception as _fw_err:
            _fw_log("refrepair.py:53", _fw_err)
        _observer = None


def repair(doc):
    """Re-link lost references in doc. Returns the features changed."""
    fixed = []
    for obj in doc.Objects:
        if obj.TypeId not in DRESS_UPS:
            continue
        try:
            base, subs = obj.Base
        except Exception:
            continue
        lost = [s for s in subs if s.startswith("?")]
        if base is None or not lost:
            continue
        mapping = _rematch(base, [s[1:] for s in lost])
        if mapping is None:
            continue
        new = [mapping.get(s[1:], s) if s.startswith("?") else s for s in subs]
        obj.Base = (base, new)
        fixed.append(obj)
    return fixed


# ---------------------------------------------------------------------- after a dimension edit
_SIGS = {}          # (doc name, feature name) -> {sub: signature}


def _unit(v):
    v = App.Vector(v)
    if v.Length < 1e-12:
        return None
    v.normalize()
    # one sign for a direction (an edge runs either way)
    for c in (v.x, v.y, v.z):
        if abs(c) > 1e-9:
            return v if c > 0 else v * -1
    return v


def _where(p, box):
    def f(x, lo, hi):
        return 0.5 if hi - lo < 1e-9 else (x - lo) / (hi - lo)
    return (f(p.x, box.XMin, box.XMax), f(p.y, box.YMin, box.YMax), f(p.z, box.ZMin, box.ZMax))


def _normals_beside(shape, edge):
    out = []
    for face in shape.ancestorsOfType(edge, __import__("Part").Face):
        if face.Surface.__class__.__name__ == "Plane":
            n = _unit(face.normalAt(0, 0))
            out.append((round(n.x, 4), round(n.y, 4), round(n.z, 4)))
        else:
            out.append(face.Surface.__class__.__name__)
    return tuple(sorted(out, key=str))


def signature(shape, name):
    """What the element is like, independent of its size and of its number."""
    try:
        el = shape.getElement(name)
    except Exception:
        return None
    box = shape.BoundBox
    if name.startswith("Edge"):
        curve = el.Curve.__class__.__name__
        first, last = el.ParameterRange
        mid = el.valueAt((first + last) / 2.0)
        d = _unit(el.tangentAt(first)) if curve == "Line" else (_unit(el.Curve.Axis) if hasattr(el.Curve, "Axis") else None)
        return ("Edge", curve, d and (round(d.x, 4), round(d.y, 4), round(d.z, 4)), _normals_beside(shape, el),
                _where(mid, box))
    if name.startswith("Face"):
        surf = el.Surface.__class__.__name__
        n = _unit(el.normalAt(0, 0)) if surf == "Plane" else (_unit(el.Surface.Axis) if hasattr(el.Surface, "Axis") else None)
        return ("Face", surf, n and (round(n.x, 4), round(n.y, 4), round(n.z, 4)), (), _where(el.CenterOfMass, box))
    return None


_SEEN = {}          # (doc, feature) -> (base shape hash, subs) last remembered


def remember(obj):
    try:
        base, subs = obj.Base
        shape = base.Shape
    except Exception:
        return
    stamp = (shape.hashCode(), tuple(subs))
    key = (obj.Document.Name, obj.Name)
    if _SEEN.get(key) == stamp:
        return                      # nothing changed since last time: no work on every rebuild
    _SEEN[key] = stamp
    sigs = {}
    for sub in subs:
        if sub and not sub.startswith("?"):
            sig = signature(shape, sub)
            if sig is not None:
                sigs[sub] = sig
    if sigs:
        _SIGS[(obj.Document.Name, obj.Name)] = sigs


def _lost_link(obj):
    try:
        text = obj.getStatusString()
    except Exception:
        return False
    return "Invalid" in obj.State and ("edge link" in text or "face link" in text or "No edges" in text)


def refind(obj):
    """New element names for a dress feature whose links broke after an edit, or None."""
    sigs = _SIGS.get((obj.Document.Name, obj.Name))
    if not sigs:
        return None
    try:
        base, subs = obj.Base
        shape = base.Shape
    except Exception:
        return None
    new = []
    for sub in subs:
        key = sub.lstrip("?")
        sig = sigs.get(key)
        if sig is None:
            return None
        kind = sig[0]
        pool = shape.Edges if kind == "Edge" else shape.Faces
        scored = []
        for i in range(1, len(pool) + 1):
            name = "%s%d" % (kind, i)
            other = signature(shape, name)
            if other is None or other[:4] != sig[:4]:
                continue
            dist = sum((a - b) ** 2 for a, b in zip(other[4], sig[4])) ** 0.5
            scored.append((dist, name))
        scored.sort()
        if not scored or scored[0][0] > 0.25 or (len(scored) > 1 and scored[1][0] - scored[0][0] < 0.02):
            return None          # nothing like it, or two equally likely: left for the user
        new.append(scored[0][1])
    return base, new


def repair_moved(doc):
    fixed = []
    for obj in doc.Objects:
        if obj.TypeId in DRESS_UPS and _lost_link(obj):
            got = refind(obj)
            if got is not None:
                obj.Base = got
                fixed.append(obj)
    return fixed


def _rematch(base, names):
    """Find each old element name again in base's shape, by geometry.

    The name is its number in an earlier shape: try base's ancestors (the
    features it was built on) until one gives an exact match for all of them.
    """
    try:
        target = base.Shape
    except Exception:
        return None
    seen = set()
    old = getattr(base, "BaseFeature", None)
    while old is not None and old.Name not in seen:
        seen.add(old.Name)
        mapping = {}
        for name in names:
            found = _find(old.Shape, name, target)
            if found is None:
                break
            mapping[name] = found
        else:
            return mapping
        old = getattr(old, "BaseFeature", None)
    return None


def _find(source, name, target):
    try:
        element = source.getElement(name)
    except Exception:
        return None
    kind = "Edge" if name.startswith("Edge") else "Face" if name.startswith("Face") else None
    if kind is None:
        return None
    pool = target.Edges if kind == "Edge" else target.Faces
    key = _key(element)
    hits = [i for i, e in enumerate(pool, 1) if _same(_key(e), key)]
    return "%s%d" % (kind, hits[0]) if len(hits) == 1 else None


def _key(element):
    box = element.BoundBox
    if hasattr(element, "Area") and element.ShapeType == "Face":
        size = element.Area
        centre = element.CenterOfMass
    else:
        size = element.Length
        first, last = element.ParameterRange
        centre = element.valueAt((first + last) / 2.0)
    return (round(size, 6), centre, box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax)


def _same(a, b):
    if abs(a[0] - b[0]) > TOL * max(1.0, abs(a[0])) * 10:
        return False
    if a[1].distanceToPoint(b[1]) > 1e-5:
        return False
    return all(abs(x - y) < 1e-5 for x, y in zip(a[2:], b[2:]))


class _Observer:
    def __init__(self):
        self.pending = set()

    def slotRecomputedDocument(self, doc):
        if doc.Name in self.pending:
            return
        try:
            from . import persistrefs
            if persistrefs._watch:
                return      # persistrefs keeps every pick (these and sketch, plane and other faces)
        except Exception as _fw_err:
            _fw_log("refrepair.py:281", _fw_err)
        for o in doc.Objects:
            if o.TypeId in DRESS_UPS and "Invalid" not in o.State and "Touched" not in o.State:
                remember(o)
        if not any(o.TypeId in DRESS_UPS and (_has_lost(o) or _lost_link(o)) for o in doc.Objects):
            return
        self.pending.add(doc.Name)
        QtCore.QTimer.singleShot(0, lambda: self._run(doc.Name))

    def _run(self, name):
        try:
            doc = App.getDocument(name)
        except Exception:
            doc = None
        try:
            if doc is not None and not doc.Restoring:
                # one at a time down the tree: a fillet built on a re-linked one is found once
                # its base has rebuilt
                for _round in range(12):
                    fixed = repair(doc)
                    fixed += [o for o in repair_moved(doc) if o not in fixed]
                    if not fixed:
                        break
                    App.Console.PrintMessage("FreeCAD: re-linked %s\n"
                                             % ", ".join(o.Label for o in fixed))
                    doc.recompute()
        finally:
            self.pending.discard(name)


def _has_lost(obj):
    try:
        return any(s.startswith("?") for s in obj.Base[1])
    except Exception:
        return False
