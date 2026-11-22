# SPDX-License-Identifier: LGPL-2.1-or-later
""










import FreeCAD as App

try:
    from PySide import QtCore
except ImportError:
    QtCore = None

TYPES = ("PartDesign::Pad", "PartDesign::Pocket")
V = App.Vector
_busy = set()


def direction(feature):
    """The way the extrude goes, in global coordinates."""
    try:
        if getattr(feature, "UseCustomVector", False):
            d = V(feature.Direction)
        else:
            profile = feature.Profile[0] if isinstance(feature.Profile, tuple) else feature.Profile
            d = profile.getGlobalPlacement().Rotation.multVec(V(0, 0, 1))
        if feature.TypeId == "PartDesign::Pocket":
            d = -d
        if getattr(feature, "Reversed", False):
            d = -d
        return d.normalize() if d.Length > 1e-12 else None
    except Exception:
        return None


def _normal(face):
    u0, u1, v0, v1 = face.ParameterRange
    return face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)


def solids_picked(obj, subs):
    shape = obj.Shape
    if not subs:
        return list(shape.Solids)
    out = []
    for sub in subs:
        try:
            el = shape.getElement(sub)
        except Exception:
            continue
        for s in shape.Solids:
            if any(el.isSame(f) for f in s.Faces) or any(el.isSame(e) for e in s.Edges) or \
                    any(el.isSame(v) for v in s.Vertexes):
                if not any(s.isSame(o) for o in out):
                    out.append(s)
    return out


def _start(feature):
    try:
        profile = feature.Profile[0] if isinstance(feature.Profile, tuple) else feature.Profile
        return profile.Shape.BoundBox.Center
    except Exception:
        return None


def facing_faces(obj, solids, d, start=None):
    """Face names of obj on these solids whose outside looks against d (the near side), ahead of
    the profile (start) when it is known."""
    names = []
    for i, f in enumerate(obj.Shape.Faces):
        if not any(any(f.isSame(g) for g in s.Faces) for s in solids):
            continue
        try:
            if _normal(f).dot(d) < -1e-6 and (start is None or (f.CenterOfMass - start).dot(d) > 1e-6):
                names.append("Face%d" % (i + 1))
        except Exception:
            continue
    return names


def _body_of(obj):
    for b in getattr(obj, "InList", []) or []:
        if b.TypeId == "PartDesign::Body" and obj in b.Group:
            return b
    return None


def _current(obj, feature):
    ""
    b = _body_of(obj)
    if b is None or b is _body_of(feature) or b.Tip is None or b.Tip is obj or not b.Tip.Shape.Solids:
        return obj
    return b.Tip


def normalised(feature):
    ""
    if feature.TypeId not in TYPES or getattr(feature, "Type", "") != "UpToShape":
        return None
    d = direction(feature)
    if d is None:
        return None
    refs = list(getattr(feature, "UpToShape", []) or [])
    out = []
    for obj, subs in refs:
        if obj is None or obj.Shape.isNull() or not obj.Shape.Solids:
            out.append((obj, subs))
            continue
        now = _current(obj, feature)
        if now is not obj:
            names = facing_faces(now, solids_picked(now, []), d, _start(feature))
            out.append((now, names) if names else (obj, subs))
            continue
        names = facing_faces(obj, solids_picked(obj, list(subs)), d, _start(feature))
        out.append((obj, names or list(subs)))
    same = len(out) == len(refs) and all(a[0] is b[0] and sorted(a[1]) == sorted(b[1]) for a, b in zip(out, refs))
    return None if same else out


def fix(feature):
    key = (feature.Document.Name, feature.Name)
    if key in _busy:
        return False
    value = normalised(feature)
    if value is None:
        return False
    _busy.add(key)
    try:
        feature.UpToShape = value
        feature.Document.recompute()
    finally:
        _busy.discard(key)
    return True


class _Watch:
    def slotChangedObject(self, obj, prop):     # an App observer: FreeCAD allows this one
        if prop not in ("UpToShape", "Type") or getattr(obj, "TypeId", "") not in TYPES:
            return
        try:
            key = (obj.Document.Name, obj.Name)
        except Exception:
            return
        if key in _busy or QtCore is None:
            return
        QtCore.QTimer.singleShot(0, lambda d=key[0], n=key[1]: _later(d, n))

    def slotRecomputedObject(self, obj):
        """The body an extrude goes up to changed (a feature added, or edited so its faces are numbered again):
        its near faces are found again."""
        try:
            if QtCore is None or getattr(obj, "TypeId", "") == "PartDesign::Body":
                return
            body = _body_of(obj)
            if body is None:
                return
            doc = obj.Document
            for x in doc.Objects:
                if x.TypeId not in TYPES or getattr(x, "Type", "") != "UpToShape" or (doc.Name, x.Name) in _busy:
                    continue
                if any(o is not None and _body_of(o) is body for o, _s in (x.UpToShape or [])) and _body_of(x) is not body:
                    QtCore.QTimer.singleShot(0, lambda d=doc.Name, n=x.Name: _later(d, n))
        except Exception:
            return

    def slotDeletedObject(self, obj):
        """A feature of that body deleted (or its making undone): the extrude goes up to the body's tip then."""
        try:
            if QtCore is None:
                return
            body = _body_of(obj)
            if body is None:
                return
            names = [x.Name for x in obj.InList if x.TypeId in TYPES and getattr(x, "Type", "") == "UpToShape"
                     and any(o is obj for o, _s in (x.UpToShape or []))]
            if names:
                QtCore.QTimer.singleShot(0, lambda d=obj.Document.Name, b=body.Name, ns=names: _refill(d, b, ns))
        except Exception:
            return


def _refill(doc_name, body_name, names):
    try:
        doc = App.getDocument(doc_name)
        body = doc.getObject(body_name)
    except Exception:
        return
    tip = getattr(body, "Tip", None) if body is not None else None
    if tip is None or tip.Shape.isNull() or not tip.Shape.Solids:
        return
    for n in names:
        x = doc.getObject(n)
        if x is None or getattr(x, "Type", "") != "UpToShape":
            continue
        refs = [(o, s) for o, s in (x.UpToShape or []) if o is not None]
        if any(_body_of(o) is body for o, _s in refs):
            continue
        d = direction(x)
        faces = facing_faces(tip, list(tip.Shape.Solids), d, _start(x)) if d is not None else []
        if not faces:
            continue
        key = (doc.Name, x.Name)
        _busy.add(key)
        try:
            x.UpToShape = refs + [(tip, faces)]
            doc.recompute()
        finally:
            _busy.discard(key)


def _later(doc_name, name):
    try:
        feature = App.getDocument(doc_name).getObject(name)
    except Exception:
        return
    if feature is not None:
        fix(feature)


WATCH = [None]


def install():
    if WATCH[0] is None:
        WATCH[0] = _Watch()
        App.addDocumentObserver(WATCH[0])
