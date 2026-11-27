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
import os
import re
import tempfile

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

try:
    import Part
except Exception:   # pragma: no cover - Part is always there in FreeCAD
    Part = None

from . import pickguard
from . import icons

FOLDER_TYPE = "SWStyle::SolidBodies"
ROW_TYPE = "SWStyle::SolidBody"
NOMERGE_TYPE = "SWStyle::NoMerge"
OP_TYPES = ("SWStyle::DeleteKeep", "SWStyle::MoveCopy", "SWStyle::Combine", "SWStyle::MirrorBody")
MERGE_BOX = "SWStyle_MergeResult"

BOSS_TYPES = {
    "PartDesign::Pad", "PartDesign::Revolution", "PartDesign::AdditiveLoft",
    "PartDesign::AdditivePipe", "PartDesign::AdditiveHelix",
    # FreeCAD's additive primitives keep their own solid (AddSubShape) too: Merge result off left them fused
    "PartDesign::AdditiveBox", "PartDesign::AdditiveCylinder", "PartDesign::AdditiveSphere", "PartDesign::AdditiveCone",
    "PartDesign::AdditiveEllipsoid", "PartDesign::AdditiveTorus", "PartDesign::AdditivePrism", "PartDesign::AdditiveWedge",
}
PICKED = (0.0, 2 / 3, 1.0)


# ---- solids of a Body -----------------------------------------------------------------

def _solid_feature(obj):
    try:
        return obj.isDerivedFrom("PartDesign::Feature") and not obj.isDerivedFrom("PartDesign::Body")
    except Exception as _fw_err:
        _fw_log("multibody.py:71", _fw_err)
        return False


def body_of(obj):
    if obj is None:
        return None
    if obj.TypeId == "PartDesign::Body":
        return obj
    try:
        for parent in obj.InList:
            if parent.TypeId == "PartDesign::Body" and obj in parent.Group:
                return parent
    except Exception as _fw_err:
        _fw_log("multibody.py:83", _fw_err)
    return None


def bodies(doc):
    if doc is None:
        return []
    return [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]


def _shown_feature(body):
    """The feature whose shape the view shows for this Body: its Tip."""
    tip = getattr(body, "Tip", None)
    if tip is not None and _solid_feature(tip):
        return tip
    return None


def _listed_feature(body):
    """The feature whose solids the Solid Bodies folder lists: the Tip, or when the Tip failed (no
    solid) the last feature before it that has one."""
    tip = _shown_feature(body)
    if tip is not None:

        # before it left it (Solid Bodies(1) stays), so the last one with a solid stands in
        feature, steps = tip, 0
        while feature is not None and steps < 500 and _failed_or_empty(feature):
            feature = getattr(feature, "BaseFeature", None)
            steps += 1
        if feature is not None and _solid_feature(feature):
            return feature
        return tip
    return None


def _failed_or_empty(feature):
    try:
        return "Invalid" in feature.State or not feature.Shape.Solids
    except Exception:
        return True


def _print(solid):
    """Size and place of a solid, to know it again after a rebuild."""
    try:
        if solid.ShapeType == "Compound" and solid.countElement("Solid") == 1:
            solid = solid.Solids[0]     # extapps/71: a feature's one-solid compound: the solid's own print
        com = solid.CenterOfMass
        return (solid.Volume, com.x, com.y, com.z)
    except Exception:
        bb = solid.BoundBox
        return (bb.XLength * bb.YLength * bb.ZLength, bb.Center.x, bb.Center.y, bb.Center.z)


def _same_print(a, b, tol=1e-6):
    scale = max(1.0, abs(a[0]) ** (1.0 / 3.0))
    if abs(a[0] - b[0]) > tol * max(1.0, abs(a[0])) * 1e3:
        return False
    return all(abs(a[i] - b[i]) <= tol * scale * 1e3 for i in (1, 2, 3))


def _source_label(feature):
    ""

    proxy = getattr(feature, "Proxy", None)
    if getattr(proxy, "Type", None) == NOMERGE_TYPE and getattr(feature, "Source", None) is not None:
        return feature.Source.Label
    return feature.Label


_name_cache = {}


def _chain(body):
    """Solid features from the start of the Body's history up to its Tip."""
    out = []
    tip = getattr(body, "Tip", None)
    for obj in body.Group:
        if _solid_feature(obj) and not getattr(obj, "Suppressed", False):
            out.append(obj)
        if obj == tip:
            break
    return out


def solids(body):
    ""

    tip = _listed_feature(body)
    if tip is None:
        return []
    try:
        shape = tip.Shape
        pieces = shape.Solids
    except Exception:
        return []
    if not pieces:
        return []
    chain = _chain(body)
    if tip in chain:
        chain = chain[:chain.index(tip) + 1]      # a failed Tip: named from the features up to the stand-in
    # the labels are in the key: a feature renamed since (Boss-Extrude1 -> Base) must not bring back the
    # old row name when the rollback bar returns to a shape seen before (tree review AG1)
    key = (body.Document.Name, body.Name, tuple((f.Name, _source_label(f), f.Shape.hashCode()) for f in chain))
    names = _name_cache.get(key)
    if names is None or len(names) != len(pieces):
        names = _history_names(chain, pieces)
        if len(_name_cache) > 200:
            _name_cache.clear()
        _name_cache[key] = names
    return list(zip(names, pieces))


_PRINTS = {}
_QUICK = {}      # solid hashCode -> its bound box print and face count (a solid the rebuild left alone)


class _Lazy:
    """A solid's print made only when needed: the bound box first (cheap), the centre of mass (12 ms on
    a big solid) only when two bound boxes already match. Same answer as _same_print on _print: a solid
    known again has the same bound box too."""
    __slots__ = ("solid", "_quick", "_full", "_faces", "_box")

    def __init__(self, solid):
        self.solid, self._quick, self._full = solid, None, None

    def quick(self):
        if self._quick is None:
            try:
                h = self.solid.hashCode()
            except Exception:
                h = None
            got = _QUICK.get(h) if h is not None else None
            got = got[1] if got is not None else None
            if got is None:
                bb = self.solid.BoundBox
                got = (bb.XLength * bb.YLength * bb.ZLength, bb.Center.x, bb.Center.y, bb.Center.z,
                       self.solid.countElement("Face"),     # extapps/69: no face objects made (40x faster)
                       bb.XLength, bb.YLength, bb.ZLength)
                if h is not None:
                    if len(_QUICK) > 500:        # extapps/63: each entry holds a whole solid
                        _QUICK.clear()
                    _QUICK[h] = (self.solid, got)     # the solid held: its hash is not reused by another
            self._quick = got[:4]
            self._faces = got[4]
            self._box = got[1:4] + got[5:8]
        return self._quick

    def meets(self, other):
        """The two bound boxes overlap. A bound box is only sure to hold its solid: a spline solid's box
        (a sweep along a helix) can be twice as big in one copy as in another, so the same spring rebuilt
        by a later feature failed the box print and became a new body (Split Line1[2] for Sweep1,
        Refgeom usage run 11-27). Boxes that do not even overlap are surely different solids."""
        try:
            self.quick(), other.quick()
            a, b = self._box, other._box
            return all(abs(a[i] - b[i]) <= (a[i + 3] + b[i + 3]) / 2.0 + 1e-6 for i in range(3))
        except Exception:
            return True

    def faces(self):
        try:
            return self._faces
        except AttributeError:
            pass
        try:
            self._faces = self.solid.countElement("Face")     # extapps/69: without the bound box
        except Exception:
            self.quick()
        return self._faces

    def full(self):
        if self._full is None:
            # the same solid again (a feature the rebuild left alone, or the Tip's own pieces): its print
            # from before (the centre of mass is the cost, 12 ms to 40 ms on a big solid)
            try:
                key = (self.solid.hashCode(), self.quick())
            except Exception:
                key = None
            got = _PRINTS.get(key) if key is not None else None
            got = got[1] if got is not None else None
            if got is None:
                got = _print(self.solid)
                if key is not None:
                    if len(_PRINTS) > 500:       # extapps/63: each entry holds a whole solid
                        _PRINTS.clear()
                    _PRINTS[key] = (self.solid, got)
            self._full = got
        return self._full

    def same(self, other):
        try:
            if self.solid.isSame(other.solid):
                return True       # the very same solid (the Tip's piece and its feature's): no mass sums
        except Exception as _fw_err:
            _fw_log("multibody.py:227", _fw_err)
        try:
            # extapps/69: the face count first, it is cheap; the bound box (2 ms to 25 ms on a big solid) only when
            # it matches: a 300-feature part spent 49 s opening on bound boxes of solids a hole had changed
            if self.faces() != other.faces():
                return False      # a fillet, a hole, a boss inside the box: not the same solid (no mass sums)
            if not _same_print(self.quick(), other.quick()) and not self.meets(other):
                return False      # far apart; boxes that overlap are settled by the centre of mass below
        except Exception as _fw_err:
            _fw_log("multibody.py:234", _fw_err)
        return _same_print(self.full(), other.full())


_HISTORY = {}       # extapps/66: history key up to a feature -> (its shape, known after it, after); memtrim empties it


def _now(shape):
    """The solids of a feature's shape to compare: the shape itself when it holds one (extapps/71: a sub-shape
    copy costs ~4 ms on its first use, a 100-feature walk 0.4 s)."""
    return [shape] if shape.countElement("Solid") == 1 else shape.Solids


def _fresh_tip(chain, pieces):
    """extapps/71: the names when the last feature changed every solid it left (the usual case: a pad, pocket or
    fillet on the body): then none of them is known from before it, so the walk through the whole history
    would end the same way. None when that is not so (the walk decides)."""
    try:
        if len(chain) < 2:
            return None
        tip, base = chain[-1], chain[-2]
        if getattr(getattr(tip, "Proxy", None), "Type", None) == NOMERGE_TYPE:
            return None
        now = [_Lazy(s) for s in _now(tip.Shape)]
        before = [_Lazy(s) for s in _now(base.Shape)]
        if not now or len(now) != len(pieces):
            return None
        if any(p.same(q) for p in now for q in before):
            return None
        label = _source_label(tip)
        known = [(now[0], label)] if len(now) == 1 else [(p, "%s[%d]" % (label, i + 1)) for i, p in enumerate(now)]
        sub = tip.Shape.Solids
        if len(sub) != len(pieces) or not all(a.isSame(b) for a, b in zip(pieces, sub)):
            return None         # not the last feature's own solids (a suppressed Tip): the walk decides
        names = [n for _p, n in known]
        seen = {}
        for i, n in enumerate(names):
            if n in seen:
                seen[n] += 1
                names[i] = "%s<%d>" % (n, seen[n])
            else:
                seen[n] = 1
        return names
    except Exception:
        return None


def _history_names(chain, pieces):
    fast = _fresh_tip(chain, pieces)
    if fast is not None:
        return fast
    known = []     # (print, name) of the solids after the feature before
    after = {}     # feature name -> known after it
    hkey = ""      # extapps/66: everything the state after the feature depends on, from the start of the chain
    for feature in chain:
        try:
            shape = feature.Shape
            now = _now(shape)       # extapps/71
        except Exception:
            continue
        label = _source_label(feature)
        lookup = known
        proxy = getattr(feature, "Proxy", None)
        nomerge = getattr(proxy, "Type", None) == NOMERGE_TYPE and feature.Source is not None
        base = getattr(feature.Source, "BaseFeature", None) if nomerge else None
        if hkey is not None:
            try:
                hkey = "%s|%s:%s:%r:%s" % (hkey, feature.Name, shape.hashCode(), label,
                                           (base.Name if base is not None else "-") if nomerge else "")
                got = _HISTORY.get(hkey)
                if got is not None and got[0].isSame(shape):
                    known, after = got[1], got[2]
                    continue        # the same feature, shape and history as before: the same state
            except Exception:
                hkey = None         # not keyed from here on: the rest of the chain is worked out as before
        if nomerge:
            # Merge result off brings back the bodies from before its Extrude.
            lookup = known + after.get(base.Name if base is not None else "", [])
        kept = []
        fresh = []
        for p in (_Lazy(s) for s in now):
            hit = next((n for q, n in lookup if p.same(q)), None)
            if hit is not None:
                kept.append((p, hit))
            else:
                fresh.append(p)
        if len(fresh) == 1:
            kept.append((fresh[0], label))
        else:
            for i, p in enumerate(fresh):
                kept.append((p, "%s[%d]" % (label, i + 1)))
        known = kept
        after = dict(after)      # extapps/66: states are kept, so each one has its own
        after[feature.Name] = kept
        if hkey:
            if len(_HISTORY) > 600:
                _HISTORY.clear()
            _HISTORY[hkey] = (shape, known, after)
    names = []
    for s in pieces:
        p = _Lazy(s)
        names.append(next((n for q, n in known if p.same(q)), "Body"))
    seen = {}
    for i, n in enumerate(names):
        if n in seen:
            seen[n] += 1
            names[i] = "%s<%d>" % (n, seen[n])
        else:
            seen[n] = 1
    return names


def solid_index_of(obj, sub):
    """Which solid of the Body's shown shape the picked face/edge/vertex sub belongs to."""
    body = body_of(obj)
    if body is None or not sub:
        return None, None
    tip = _shown_feature(body)
    if tip is None:
        return body, None
    try:
        element = obj.Shape.getElement(sub.split(".")[-1])
    except Exception as _fw_err:
        _fw_log("multibody.py:295", _fw_err)
        return body, None
    for i, solid in enumerate(tip.Shape.Solids):
        kind = element.ShapeType
        group = solid.Faces if kind == "Face" else solid.Edges if kind == "Edge" else solid.Vertexes
        if any(element.isSame(g) for g in group):
            return body, i
    # The pick may be on an earlier feature's shape (rolled back, or in edit): go by place.
    try:
        point = element.CenterOfMass if kind == "Face" else element.BoundBox.Center
    except Exception:
        return body, None
    best = None
    for i, solid in enumerate(tip.Shape.Solids):
        d = solid.distToShape(Part.Vertex(point))[0]
        if best is None or d < best[0]:
            best = (d, i)
    return body, (best[1] if best else None)


# A body picked for a feature is stored as text: "index:volume:x:y:z"
def ref_text(index, solid):
    v, x, y, z = _print(solid)
    return "%d:%.9g:%.9g:%.9g:%.9g" % (index, v, x, y, z)


def _ref_parse(text):
    try:
        parts = [float(p) for p in text.split(":")]
        return int(parts[0]), tuple(parts[1:5])
    except Exception:
        return None, None


def resolve(text, pieces):
    """Index of the solid in pieces that the stored text means, or None."""
    index, want = _ref_parse(text)
    if want is None:
        return None
    best = None
    for i, s in enumerate(pieces):
        v, x, y, z = _print(s)
        if want[0] > 0 and not 0.5 < v / want[0] < 2.0:
            continue
        d = math.sqrt((x - want[1]) ** 2 + (y - want[2]) ** 2 + (z - want[3]) ** 2)
        if best is None or d < best[0]:
            best = (d, i)
    if best is not None:
        return best[1]
    if index is not None and 0 <= index < len(pieces):
        return index
    return None


def _result(shapes):
    shapes = [s for s in shapes if s is not None and not s.isNull()]
    if not shapes:
        return Part.Shape()
    if len(shapes) == 1:
        return shapes[0]
    return Part.makeCompound(shapes)


def _base_solids(obj):
    base = getattr(obj, "BaseFeature", None)
    if base is None:
        return []
    try:
        return list(base.Shape.Solids)
    except Exception as _fw_err:
        _fw_log("multibody.py:365", _fw_err)
        return []


def _fix_compound(body):
    if body is not None and "AllowCompound" in body.PropertiesList and not body.AllowCompound:
        body.AllowCompound = True


# ---- Merge result off --------------------------------------------------------------------

CUT_TYPES = {
    "PartDesign::Pocket", "PartDesign::Groove", "PartDesign::SubtractiveLoft", "PartDesign::SubtractivePipe",
    "PartDesign::SubtractiveHelix", "PartDesign::Hole",
    "PartDesign::SubtractiveBox", "PartDesign::SubtractiveCylinder", "PartDesign::SubtractiveSphere",
    "PartDesign::SubtractiveCone", "PartDesign::SubtractiveEllipsoid", "PartDesign::SubtractiveTorus",
    "PartDesign::SubtractivePrism", "PartDesign::SubtractiveWedge",
}
_clash_cache = {}

PY_BOSS_KINDS = ("BoundaryBoss",)
PY_CUT_KINDS = ("BoundaryCut",)


def is_cut(obj):
    return obj.TypeId in CUT_TYPES or getattr(obj, "SWStyleKind", "") in PY_CUT_KINDS


def _scoped_copies(helper, source, before):
    """The result of a Mirror or pattern whose Feature Scope is Selected bodies: what the copies cut
    away and what they add, put on the bodies picked only; the other bodies stay as they were and
    an added copy that reaches only those stays a body of its own."""
    result = source.Shape
    if getattr(helper, "ScopeAll", True) or getattr(helper, "AutoSelect", True) or len(before) < 2:
        return result.copy()
    try:
        base = Part.makeCompound(before)
        removed = base.cut(result)
        added = result.cut(base)
    except Exception as error:
        _fw_log("multibody.py:scoped copies", error)
        return result.copy()
    out = []                    # [(solid, on a body picked)]
    for b in before:
        if not in_scope(helper, b):
            out.append((b, False))
            continue
        piece = b.cut(removed) if removed.Solids else b
        out.extend((x, True) for x in (_refined(piece, source).Solids if not piece.isNull() else []))
    for p in added.Solids:
        hit = [i for i, (b, picked) in enumerate(out) if picked and _touches(b, p)]
        if hit:
            fused = _refined(p.fuse([out[i][0] for i in hit]), source)
            out = [x for i, x in enumerate(out) if i not in hit] + [(f, True) for f in fused.Solids]
        else:
            out.append((p, False))
    out = [x for x, _picked in out]
    return _result(out)


def is_boss(obj):
    return obj.TypeId in BOSS_TYPES or getattr(obj, "SWStyleKind", "") in PY_BOSS_KINDS


def _interfering(pieces):
    ""

    try:
        key = tuple(p.hashCode() for p in pieces)
    except Exception:
        key = None
    if key is not None and key in _clash_cache:
        return _clash_cache[key]
    clash = False
    for i in range(len(pieces)):
        for j in range(i + 1, len(pieces)):
            a, b = pieces[i], pieces[j]
            if not a.BoundBox.intersect(b.BoundBox):
                continue
            try:
                if a.common(b).Volume > 1e-9 * max(1.0, min(a.Volume, b.Volume)):
                    clash = True
                    break
            except Exception as _fw_err:
                _fw_log("multibody.py:414", _fw_err)
                continue
        if clash:
            break
    if key is not None:
        if len(_clash_cache) > 100:
            _clash_cache.clear()
        _clash_cache[key] = clash
    return clash


def _touches(a, b):
    if not a.BoundBox.intersect(b.BoundBox):
        try:
            return a.distToShape(b)[0] < 1e-7
        except Exception:
            return False
    try:
        return a.distToShape(b)[0] < 1e-7
    except Exception:
        return False


def _placed_tool(source):
    """The boss or cut's own solid where it sits in the body. FreeCAD keeps a feature's AddSubShape
    in the feature's own frame (its Placement applied on top gives the body's): a box placed away from
    the origin, or a pad on an offset sketch, with Merge result off landed in the wrong place."""
    tool = source.AddSubShape.copy()
    try:
        pl = source.Placement
        if not pl.isIdentity() and not tool.isNull():
            tool.Placement = pl.multiply(tool.Placement)
    except Exception as _fw_err:
        _fw_log("multibody.py:placed", _fw_err)
    return tool


class NoMerge:
    ""





    Type = NOMERGE_TYPE

    def __init__(self, obj, source):
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Source", "Merge", "The boss feature whose result is not merged")
        obj.Source = source
        obj.setEditorMode("Source", 1)
        self.setup(obj)

    def setup(self, obj):
        if "Merge" not in obj.PropertiesList:
            obj.addProperty("App::PropertyBool", "Merge", "Merge", "Merge result")
            obj.Merge = False
        # Feature Scope (cuts): all bodies, or the bodies picked (found again by place and size)
        if "ScopeAll" not in obj.PropertiesList:
            obj.addProperty("App::PropertyBool", "ScopeAll", "Feature Scope", "All bodies")
            obj.ScopeAll = True
            obj.addProperty("App::PropertyBool", "AutoSelect", "Feature Scope", "Auto-select the bodies the cut reaches")
            obj.AutoSelect = True
            obj.addProperty("App::PropertyString", "ScopeBodies", "Feature Scope", "The bodies picked (JSON)")

    def execute(self, obj):
        source = obj.Source
        if source is None:
            obj.Shape = obj.BaseFeature.Shape.copy() if obj.BaseFeature is not None else Part.Shape()
            return
        before = _base_solids(source)
        if not is_cut(source) and not is_boss(source):
            # a Mirror or a pattern (no tool of its own): Feature Scope, Selected bodies keeps the
            # bodies not picked as they were (pkg310)
            obj.Shape = _scoped_copies(obj, source, before)
            return
        try:
            tool = [s for s in _placed_tool(source).Solids]
        except Exception:
            tool = []
        cut = is_cut(source)
        if cut and tool and not getattr(obj, "ScopeAll", True) and not getattr(obj, "AutoSelect", True):
            # Feature Scope, Selected bodies: the cut changes the bodies picked only
            out = []
            for b in before:
                out.extend(_refined(b.cut(tool), source).Solids if in_scope(obj, b) else [b])
            obj.Shape = _result(out)
            return
        if obj.Merge or cut:
            scoped = not cut and not getattr(obj, "ScopeAll", True) and not getattr(obj, "AutoSelect", True)
            if len(before) <= 1 or not tool or (not _interfering(before) and not scoped):
                obj.Shape = source.Shape.copy()
                return
            if cut:
                out = []
                for b in before:
                    rest = b.cut(tool)
                    out.extend(_refined(rest, source).Solids)
                obj.Shape = _result(out)
                return
            touched = [b for b in before if any(_touches(b, t) for t in tool)]
            if not getattr(obj, "ScopeAll", True) and not getattr(obj, "AutoSelect", True):
                # Feature Scope, Selected bodies: the boss merges with the bodies picked only
                touched = [b for b in touched if in_scope(obj, b)]
            others = [b for b in before if not any(b is t for t in touched)]
            if touched:
                fused = _refined(tool[0].fuse(touched + tool[1:]), source)
                obj.Shape = _result(others + list(fused.Solids))
            else:
                obj.Shape = _result(before + tool)
            return
        obj.Shape = _result(list(before) + tool)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class NoMergeView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        try:
            vobj.ShowInTree = False
        except Exception as _fw_err:
            _fw_log("multibody.py:522", _fw_err)

    def getIcon(self):
        return _icon("bodies")

    def _source(self):
        return getattr(self.Object, "Source", None)

    def setEdit(self, vobj, mode=0):
        source = self._source()
        if source is not None and mode == 0:
            QtCore.QTimer.singleShot(0, lambda: Gui.ActiveDocument.setEdit(source.Name, 0))
            return False
        return None

    def unsetEdit(self, vobj, mode=0):
        return None

    def doubleClicked(self, vobj):
        source = self._source()
        if source is not None:
            Gui.ActiveDocument.setEdit(source.Name, 0)
        return True

    def onDelete(self, vobj, subelements):
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _scope_prints(helper):
    import json
    try:
        return [tuple(p) for p in json.loads(getattr(helper, "ScopeBodies", "") or "[]")]
    except Exception:
        return []


def in_scope(helper, solid):
    return any(_same_print(_print(solid), p) for p in _scope_prints(helper))


def scope_of(feature):
    """(all bodies, auto-select, [solids picked]) of a cut or a boss."""
    helper = helper_of(feature)
    before = _base_solids(feature)
    if helper is None or "ScopeAll" not in helper.PropertiesList:
        return True, True, []
    return helper.ScopeAll, helper.AutoSelect, [b for b in before if in_scope(helper, b)]


def set_scope(feature, all_bodies, auto, picked):
    """Feature Scope of a cut or a boss: All bodies, or Selected bodies (Auto-select, or the solids picked)."""
    import json
    body = body_of(feature)
    if body is None:
        return
    helper = helper_of(feature)
    if helper is None:
        if all_bodies:
            return
        helper = _add_helper(feature, body, True)
    helper.Proxy.setup(helper)
    helper.ScopeAll = bool(all_bodies)
    helper.AutoSelect = bool(auto)
    helper.ScopeBodies = json.dumps([list(_print(s)) for s in picked])
    if body.Tip == helper and App.GuiUp and Gui.ActiveDocument.getInEdit() is None:
        try:
            feature.Visibility = False
            helper.Visibility = True
        except Exception as _fw_err:
            _fw_log("multibody.py:597", _fw_err)
    helper.touch()
    feature.Document.recompute()


def helper_of(feature):
    if feature is None:
        return None
    for obj in feature.InList:
        if getattr(getattr(obj, "Proxy", None), "Type", None) == NOMERGE_TYPE and obj.Source == feature:
            return obj
    return None


def _refined(shape, source):
    if getattr(source, "Refine", False):
        try:
            return shape.removeSplitter()
        except Exception as _fw_err:
            _fw_log("multibody.py:616", _fw_err)
    return shape


def merged(feature):
    helper = helper_of(feature)
    return helper is None or helper.Merge


def _add_helper(feature, body, merge):
    was_tip = body.Tip == feature
    helper = feature.Document.addObject("PartDesign::FeaturePython", "NoMerge")
    NoMerge(helper, feature)
    helper.Merge = merge
    if App.GuiUp:
        NoMergeView(helper.ViewObject)
    helper.Label = feature.Label + " (Merge result)"
    body.insertObject(helper, feature, True)
    if was_tip:
        body.Tip = helper
    return helper


def scope(doc):
    ""

    added = False
    for body in bodies(doc):
        if not getattr(body, "AllowCompound", False):
            continue
        for feature in _chain(body):
            if not is_boss(feature) and not is_cut(feature):
                continue
            if helper_of(feature) is not None:
                continue
            before = _base_solids(feature)
            if len(before) > 1 and _interfering(before):
                _add_helper(feature, body, True)
                added = True
    return added


def set_merge(feature, merge):
    """Merge result on (FreeCAD's own fuse) or off (the boss stays a separate body).

    The hidden step, once made, stays and is switched: removing it while the feature's panel is
    open would leave FreeCAD's panel holding a deleted object (it crashes on close)."""
    body = body_of(feature)
    if body is None:
        return
    helper = helper_of(feature)
    if helper is not None:
        if helper.Merge != bool(merge):
            helper.Merge = bool(merge)
    elif not merge:
        _fix_compound(body)
        helper = _add_helper(feature, body, False)
    else:
        return
    if body.Tip == helper and App.GuiUp and _editing_sketch() is False and Gui.ActiveDocument.getInEdit() is None:
        try:
            feature.Visibility = False
            helper.Visibility = True
        except Exception as _fw_err:
            _fw_log("multibody.py:680", _fw_err)
    helper.touch()
    feature.Document.recompute()


class MergeBox(QtCore.QObject):
    """The Merge result check box at the bottom of the boss feature's first panel box."""

    def __init__(self, owner, feature):
        super().__init__(owner)
        self.doc = feature.Document.Name
        self.name = feature.Name
        self.box = QtWidgets.QCheckBox("Merge result", owner)
        self.box.setObjectName(MERGE_BOX)
        self.box.setToolTip("Off: the new feature stays a separate solid body (Solid Bodies folder).")
        self.box.setChecked(merged(feature))
        base = getattr(feature, "BaseFeature", None)

        self.box.setVisible(base is not None)
        self.box.toggled.connect(self.toggled)

    def feature(self):
        try:
            return App.getDocument(self.doc).getObject(self.name)
        except Exception:
            return None

    def toggled(self, on):
        feature = self.feature()
        if feature is not None:
            set_merge(feature, on)


SCOPE_BOX = "SWStyle_FeatureScope"


class ScopeBox(QtCore.QObject):
    ""



    def __init__(self, owner, feature):
        super().__init__(owner)
        self.doc, self.name = feature.Document.Name, feature.Name
        self.box = QtWidgets.QGroupBox("Feature Scope", owner)
        self.box.setObjectName(SCOPE_BOX)
        lay = QtWidgets.QVBoxLayout(self.box)
        self.all = QtWidgets.QRadioButton("All bodies", self.box)
        self.some = QtWidgets.QRadioButton("Selected bodies", self.box)
        self.auto = QtWidgets.QCheckBox("Auto-select", self.box)
        self.list = QtWidgets.QListWidget(self.box)
        self.list.setObjectName(SCOPE_BOX + "Bodies")
        self.list.setFixedHeight(80)
        self.list.setToolTip("Bodies the feature changes: tick them, or click them in the graphics area")
        for w in (self.all, self.some, self.auto, self.list):
            lay.addWidget(w)
        everything, auto, picked = scope_of(feature)
        self.solids = _base_solids(feature)
        for i, s in enumerate(self.solids):
            item = QtWidgets.QListWidgetItem("Body %d (%.0f mm\u00b3)" % (i + 1, s.Volume))
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if any(s.isSame(p) for p in picked) else QtCore.Qt.Unchecked)
            self.list.addItem(item)
        (self.all if everything else self.some).setChecked(True)
        self.auto.setChecked(auto)
        self._shown()
        self.all.toggled.connect(self.changed)
        self.auto.toggled.connect(self.changed)
        self.list.itemChanged.connect(lambda item: self.changed())
        Gui.Selection.addObserver(self)
        self.box.destroyed.connect(self._stop)

    def feature(self):
        try:
            return App.getDocument(self.doc).getObject(self.name)
        except Exception:
            return None

    def _shown(self):
        self.auto.setVisible(self.some.isChecked())
        self.list.setVisible(self.some.isChecked() and not self.auto.isChecked())

    def changed(self, *args):
        self._shown()
        feature = self.feature()
        if feature is None:
            return
        picked = [self.solids[i] for i in range(self.list.count())
                  if self.list.item(i).checkState() == QtCore.Qt.Checked and i < len(self.solids)]
        set_scope(feature, self.all.isChecked(), self.auto.isChecked(), picked)

    def addSelection(self, doc, obj, sub, pnt):
        """A click on a body in the view ticks it (Selected bodies, Auto-select off)."""
        if pickguard.stale(self, self.list):
            return
        if not self.list.isVisible() or not sub.startswith("Face"):
            return
        try:
            face = App.getDocument(doc).getObject(obj).Shape.getElement(sub)
        except Exception:
            return
        for i, s in enumerate(self.solids):
            if s.distToShape(face)[0] < 1e-6 and i < self.list.count():
                item = self.list.item(i)
                item.setCheckState(QtCore.Qt.Unchecked if item.checkState() == QtCore.Qt.Checked else QtCore.Qt.Checked)
                QtCore.QTimer.singleShot(0, Gui.Selection.clearSelection)
                return

    def _stop(self, *args):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("multibody.py:791", _fw_err)


def install_pm(view):
    """Adds Merge result to the boss feature being edited (idempotent; called on each refresh
    of the PropertyManager)."""
    try:
        gdoc = Gui.ActiveDocument
        edit = gdoc.getInEdit() if gdoc is not None else None
        feature = editobj.of(edit) if edit is not None else None
    except Exception:
        feature = None
    if feature is None or body_of(feature) is None:
        return
    cut = feature.TypeId in CUT_TYPES
    if not cut and feature.TypeId not in BOSS_TYPES:
        return
    if cut and (view.findChild(QtWidgets.QGroupBox, SCOPE_BOX) is not None or len(_base_solids(feature)) < 2):
        return
    if not cut and view.findChild(QtWidgets.QCheckBox, MERGE_BOX) is not None:
        if view.findChild(QtWidgets.QGroupBox, SCOPE_BOX) is None and len(_base_solids(feature)) > 1:
            _add_scope(view, feature)       # the boss's Feature Scope (multibody parts), features/164
        return
    if not cut and not _base_solids(feature):
        return
    boxes = [w for w in view.findChildren(QtWidgets.QWidget) if w.inherits("QSint::ActionGroup")]
    target = None
    for group in boxes:
        if group.isVisible() or target is None:
            target = group
            break
    if target is None:
        return
    # The panel's own form: box > frame > form.
    forms = [w for w in target.findChildren(QtWidgets.QWidget) if w.layout() is not None
             and w.parentWidget() is not None and w.parentWidget().parentWidget() is target]
    form = forms[0] if forms else None
    if form is None:
        return
    if cut:
        scope = ScopeBox(form, feature)
        form.layout().addWidget(scope.box)
        return
    merge = MergeBox(form, feature)
    form.layout().addWidget(merge.box)
    if len(_base_solids(feature)) > 1:
        scope = ScopeBox(form, feature)
        form.layout().addWidget(scope.box)


def _add_scope(view, feature):
    merge = view.findChild(QtWidgets.QCheckBox, MERGE_BOX)
    form = merge.parentWidget() if merge is not None else None
    if form is None or form.layout() is None:
        return
    scope = ScopeBox(form, feature)
    form.layout().addWidget(scope.box)


# ---- hide and colour one body ------------------------------------------------------------

class _Look:
    """Per body: which solids are hidden or coloured; drawn on the Tip feature's view."""

    def __init__(self):
        self.orig = {}       # (node address) -> (field values at our last write, originals)
        self.colours = {}    # vobj object name -> original ShapeAppearance


_look = _Look()


def _nodes(vobj, type_name):
    """Every node of one type under the view provider, each once."""
    from pivy import coin
    search = coin.SoSearchAction()
    search.setType(coin.SoType.fromName(type_name))
    search.setInterest(coin.SoSearchAction.ALL)
    search.setSearchingAll(True)
    search.apply(vobj.RootNode)
    paths = search.getPaths()
    out = {}
    for i in range(paths.getLength()):
        node = paths.get(i).getTail()
        out[_addr(node)] = node
    return list(out.values())


def _addr(node):
    try:
        return int(node.this)
    except Exception:
        return repr(node)


def _element_indices(shape, solid):
    faces = [i for i, f in enumerate(shape.Faces) if any(f.isSame(g) for g in solid.Faces)]
    edges = [i for i, e in enumerate(shape.Edges) if any(e.isSame(g) for g in solid.Edges)]
    verts = [i for i, v in enumerate(shape.Vertexes) if any(v.isSame(g) for g in solid.Vertexes)]
    return faces, edges, verts


def _hide_faces(node, faces, spot=None):
    parts = list(node.partIndex.getValues()) if node.partIndex.getNum() else []
    index = list(node.coordIndex.getValues()) if node.coordIndex.getNum() else []
    if not parts or not index:
        return
    hide = set(faces)
    pos = 0
    out = list(index)
    for face, tris in enumerate(parts):
        for _ in range(tris):
            if pos + 3 >= len(out):
                break
            if face in hide:
                k = out[pos] if spot is None else spot
                out[pos] = k
                out[pos + 1] = k
                out[pos + 2] = k
            pos += 4
    node.coordIndex.setValues(0, len(out), out)


def _hide_edges(node, edges, spot=None):
    index = list(node.coordIndex.getValues()) if node.coordIndex.getNum() else []
    if not index:
        return
    hide = set(edges)
    out = list(index)
    edge = 0
    first = None
    for i, k in enumerate(out):
        if k < 0:
            edge += 1
            first = None
            continue
        if first is None:
            first = k if spot is None else spot
        if edge in hide:
            out[i] = first
    node.coordIndex.setValues(0, len(out), out)


def _hide_points(coords, start, verts, keep):
    if keep is None:
        return
    for v in verts:
        i = start + v
        if i < coords.point.getNum():
            coords.point.set1Value(i, keep)


def _restore(node, field):
    key = _addr(node)
    saved = _look.orig.get((key, field))
    if saved is None:
        return
    written, original = saved
    current = list(getattr(node, field).getValues())
    if current == written:
        getattr(node, field).setValues(0, len(original), original)
        getattr(node, field).setNum(len(original))
    _look.orig.pop((key, field), None)


def _remember(node, field):
    """Keeps FreeCAD's own values once, so showing the body again can put them back."""
    key = _addr(node)
    values = list(getattr(node, field).getValues())
    saved = _look.orig.get((key, field))
    if saved is None or values != saved[0]:
        _look.orig[(key, field)] = (None, values)
    return _look.orig[(key, field)][1]


def _written(node, field):
    key = _addr(node)
    saved = _look.orig.get((key, field))
    if saved is not None:
        _look.orig[(key, field)] = (list(getattr(node, field).getValues()), saved[1])


def _face_triangles(vobj):
    try:
        return [list(node.coordIndex.getValues()) for node in _nodes(vobj, "SoBrepFaceSet")]
    except Exception:
        return None


def _redraw_faces(vobj):
    """FreeCAD 1.1 draws a feature's faces from a buffer on the graphics card that it fills from
    the triangle list only when the number of triangles or the colours change: triangles hidden
    (or put back) in the list alone stay on screen as they were. Setting the appearance again, to
    what it is, makes FreeCAD fill the buffer from the list. It is not a change of the document."""
    try:
        gdoc = vobj.Object.Document and Gui.getDocument(vobj.Object.Document.Name)
    except Exception:
        gdoc = None
    try:
        modified = gdoc.Modified if gdoc is not None else None
    except Exception:
        modified = None
    try:
        vobj.ShapeAppearance = list(vobj.ShapeAppearance)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: hidden body not redrawn: %s\n" % error)
    if modified is False:
        try:
            gdoc.Modified = False
        except Exception as _fw_err:
            _fw_log("multibody.py:1001", _fw_err)


def apply_hidden(body, hidden):
    """Draws the Body without the solids at the indices in hidden (they stay in the model)."""
    tip = _shown_feature(body)
    if tip is None or not App.GuiUp:
        return
    vobj = tip.ViewObject
    if vobj is None:
        return
    before = _face_triangles(vobj)
    try:
        _apply_hidden(tip, vobj, hidden)
    finally:
        if before is not None and _face_triangles(vobj) != before:
            _redraw_faces(vobj)


def _apply_hidden(tip, vobj, hidden):
    try:
        faces_nodes = _nodes(vobj, "SoBrepFaceSet")
        edge_nodes = _nodes(vobj, "SoBrepEdgeSet")
        point_nodes = _nodes(vobj, "SoBrepPointSet")
        coord_nodes = _nodes(vobj, "SoCoordinate3")
    except Exception:
        return
    # Put FreeCAD's own drawing back first, then hide what is hidden now.
    for node in faces_nodes + edge_nodes:
        _restore(node, "coordIndex")
    for node in coord_nodes:
        _restore(node, "point")
    if not hidden:
        return
    shape = tip.Shape
    pieces = shape.Solids
    faces, edges, verts = set(), set(), set()
    for i in hidden:
        if 0 <= i < len(pieces):
            f, e, v = _element_indices(shape, pieces[i])
            faces.update(f)
            edges.update(e)
            verts.update(v)
    # Hidden faces and edges shrink onto one shown vertex, the hidden vertex dots move onto it
    # too: nothing of the body is drawn and nothing of it can be picked.
    shown_verts = [i for i in range(len(shape.Vertexes)) if i not in verts]
    start = point_nodes[0].startIndex.getValue() if point_nodes else None
    spot = start + shown_verts[0] if (start is not None and shown_verts) else None
    for node in faces_nodes:
        _remember(node, "coordIndex")
        _hide_faces(node, faces, spot)
        _written(node, "coordIndex")
    for node in edge_nodes:
        _remember(node, "coordIndex")
        _hide_edges(node, edges, spot)
        _written(node, "coordIndex")
    if start is None:
        return
    for coords in coord_nodes:
        if coords.point.getNum() >= start + len(shape.Vertexes):
            _remember(coords, "point")
            keep = coords.point[spot].getValue() if spot is not None else None
            _hide_points(coords, start, verts, keep)
            _written(coords, "point")


_without = {}       # (shape hash, hidden solids' hashes) -> the shape without them


def hidden_solids(doc):
    """The solids hidden on their Solid Bodies rows (Hide), as they are in each body's shown
    feature."""
    out = []
    try:
        hidden = {}
        for r in rows(doc):
            if r.ViewObject is None or not r.ViewObject.ShowInTree or r.ViewObject.Visibility:
                continue
            hidden.setdefault(r.Body, []).append(r.Index)
        if not hidden:
            return out
        for body in bodies(doc):
            if body.Name not in hidden:
                continue
            tip = _shown_feature(body)
            if tip is None:
                continue
            pieces = tip.Shape.Solids
            out += [pieces[i] for i in hidden[body.Name] if 0 <= i < len(pieces)]
    except Exception as _fw_err:
        _fw_log("multibody.py:1091", _fw_err)
    return out


def without_hidden(doc, shape, gone=None):
    """shape without the solids that are hidden on their Solid Bodies rows: what the screen shows
    of it. The shape itself when none of its solids is hidden; None when all are. For the drawings
    made beside FreeCAD's own (silhouette edges, hidden lines), which must leave a hidden body out
    as the model's faces and edges do (apply_hidden)."""
    try:
        if gone is None:        # extapps/68: callers walking every shape read it once and hand it in
            gone = hidden_solids(doc)
        if not gone:
            return shape
        solids = shape.Solids
        keep = [s for s in solids if not any(s.isPartner(g) for g in gone)]
        if len(keep) == len(solids):
            return shape
        if not keep:
            return None
        key = (shape.hashCode(), tuple(sorted(g.hashCode() for g in gone)))
        got = _without.get(key)
        if got is None:
            import Part
            if len(_without) > 200:
                _without.clear()
            got = _without[key] = Part.Compound(keep)
        return got
    except Exception:
        return shape


def apply_colours(body, colours):
    """colours: {solid index: (r, g, b)}; other faces keep the feature's own appearance."""
    tip = _shown_feature(body)
    if tip is None or not App.GuiUp or tip.ViewObject is None:
        return
    vobj = tip.ViewObject
    key = (tip.Document.Name, tip.Name)
    if not colours:
        original = _look.colours.pop(key, None)
        if original is not None:
            vobj.ShapeAppearance = original
        return
    if key not in _look.colours:
        _look.colours[key] = list(vobj.ShapeAppearance)
    base = _look.colours[key][0]
    shape = tip.Shape
    pieces = shape.Solids
    face_colour = {}
    for i, rgb in colours.items():
        if 0 <= i < len(pieces):
            for f in _element_indices(shape, pieces[i])[0]:
                face_colour[f] = rgb
    if len(_look.colours[key]) == len(shape.Faces):
        start = list(_look.colours[key])
    else:
        start = [base] * len(shape.Faces)
    out = []
    for i in range(len(shape.Faces)):
        m = App.Material()
        src = start[i]
        for attr in ("AmbientColor", "SpecularColor", "EmissiveColor", "Shininess", "Transparency", "DiffuseColor"):
            try:
                setattr(m, attr, getattr(src, attr))
            except Exception as _fw_err:
                _fw_log("multibody.py:1156", _fw_err)
        if i in face_colour:
            r, g, b = face_colour[i]
            m.DiffuseColor = (r, g, b)
            m.AmbientColor = (r * 0.3, g * 0.3, b * 0.3)
        out.append(m)
    vobj.ShapeAppearance = out


# ---- the Solid Bodies folder -------------------------------------------------------------

def folder(doc):
    if doc is None:
        return None
    for obj in doc.Objects:
        if getattr(getattr(obj, "Proxy", None), "Type", None) == FOLDER_TYPE:
            return obj
    return None


def rows(doc):
    if doc is None:
        return []
    return [o for o in doc.Objects if getattr(getattr(o, "Proxy", None), "Type", None) == ROW_TYPE]


class SolidBodiesFolder:
    Type = FOLDER_TYPE

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        if "Count" not in obj.PropertiesList:
            obj.addProperty("App::PropertyInteger", "Count", "Solid Bodies", "Number of solid bodies")
            obj.setEditorMode("Count", 1)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class SolidBodiesFolderView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        from pivy import coin
        vobj.addDisplayMode(coin.SoGroup(), "Default")

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        return _icon("folder")

    def claimChildren(self):
        obj = getattr(self, "Object", None)     # a saved part opening: asked before attach()
        if obj is None:
            return []
        try:
            doc = obj.Document
        except (ReferenceError, RuntimeError):
            return []
        out = []
        for r in rows(doc):
            try:
                if r.ViewObject is not None and r.ViewObject.ShowInTree:
                    out.append(r)
            except Exception:
                out.append(r)
        return out

    def setupContextMenu(self, vobj, menu):
        _body_menu(menu, vobj.Object.Document, [])
        return True

    def onDelete(self, vobj, subelements):
        return False

    def canDragObjects(self):
        return False

    def canDropObjects(self):
        return False

    def dumps(self):
        return None

    def loads(self, state):
        return None


class SolidBodyRow:
    """One solid body. The row keeps what the user set on it (hidden, colour)."""
    Type = ROW_TYPE

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        props = obj.PropertiesList
        if "Body" not in props:
            obj.addProperty("App::PropertyString", "Body", "Solid Body", "The FreeCAD Body that holds this solid")
        if "SolidName" not in props:
            obj.addProperty("App::PropertyString", "SolidName", "Solid Body", "Name of the body in the Solid Bodies folder")
        if "Index" not in props:
            obj.addProperty("App::PropertyInteger", "Index", "Solid Body", "Place of the solid in the Body's shape")
        if "Colour" not in props:
            obj.addProperty("App::PropertyColor", "Colour", "Solid Body", "Body colour (with UseColour)")
        if "UseColour" not in props:
            obj.addProperty("App::PropertyBool", "UseColour", "Solid Body", "Draw the body in Color")
        for p in ("Body", "SolidName", "Index"):
            obj.setEditorMode(p, 1)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def onChanged(self, obj, prop):
        if prop in ("Colour", "UseColour"):
            later(obj.Document)

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class SolidBodyRowView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        from pivy import coin
        vobj.addDisplayMode(coin.SoGroup(), "Default")

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        return _icon("body")

    def onChanged(self, vobj, prop):
        if prop == "Visibility":
            later(vobj.Object.Document)

    def setupContextMenu(self, vobj, menu):
        obj = vobj.Object
        hide = menu.addAction("Show Body" if not vobj.Visibility else "Hide Body")
        hide.triggered.connect(lambda: _toggle(obj))
        look = menu.addAction("Appearance...")
        look.triggered.connect(lambda: pick_colour(obj))
        if obj.UseColour:
            clear = menu.addAction("Remove Appearance")
            clear.triggered.connect(lambda: _clear_colour(obj))
        menu.addSeparator()
        _body_menu(menu, obj.Document, [obj])
        return True

    def doubleClicked(self, vobj):
        return True

    def onDelete(self, vobj, subelements):

        obj = vobj.Object
        QtCore.QTimer.singleShot(0, lambda: start_op("DeleteKeep", obj.Document, [obj]))
        return False

    def canDragObjects(self):
        return False

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _toggle(row_obj):
    row_obj.ViewObject.Visibility = not row_obj.ViewObject.Visibility


def pick_colour(row_obj):
    start = QtGui.QColor.fromRgbF(*row_obj.Colour[:3]) if row_obj.UseColour else QtGui.QColor("#b0b8c0")
    colour = QtWidgets.QColorDialog.getColor(start, Gui.getMainWindow(), "Appearance: " + row_obj.SolidName)
    if not colour.isValid():
        return
    doc = row_obj.Document
    doc.openTransaction("Appearance")
    try:
        row_obj.Colour = (colour.redF(), colour.greenF(), colour.blueF())
        row_obj.UseColour = True
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    refresh(doc)


def _clear_colour(row_obj):
    doc = row_obj.Document
    doc.openTransaction("Remove Appearance")
    try:
        row_obj.UseColour = False
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    refresh(doc)


def _body_menu(menu, doc, picked_rows):
    for key, label in (("DeleteKeep", "Delete/Keep Body..."), ("MoveCopy", "Move/Copy Body..."),
                       ("Combine", "Combine..."), ("MirrorBody", "Mirror Body...")):
        action = menu.addAction(label)
        action.triggered.connect(lambda checked=False, k=key: start_op(k, doc, list(picked_rows)))
    menu.addSeparator()
    rows = list(picked_rows)
    if rows:
        new_part = menu.addAction("Insert into New Part...")
        new_part.triggered.connect(lambda checked=False: insert_rows_into_new_part(rows))
        if _ISOLATED.get(doc.Name) is None:
            iso = menu.addAction("Isolate")
            iso.triggered.connect(lambda checked=False: isolate(doc, rows))
    if _ISOLATED.get(doc.Name) is not None:
        leave = menu.addAction("Exit Isolate")
        leave.triggered.connect(lambda checked=False: exit_isolate(doc))
    save = menu.addAction("Save Bodies...")
    save.triggered.connect(lambda checked=False: save_bodies_page(doc, rows))


# --------------------------------------------------------------------------- body menu extras
_ISOLATED = {}          # document name -> {row name: Visibility before Isolate}


def _row_solid(row_obj):
    body = row_obj.Document.getObject(row_obj.Body)
    if body is None:
        return None
    for i, (name, solid) in enumerate(solids(body)):
        if name == row_obj.SolidName or i == row_obj.Index:
            s = solid.copy()
            s.Placement = body.Placement.multiply(s.Placement)
            return s
    return None


def insert_rows_into_new_part(rows):
    ""


    from . import createassembly
    made = []
    for row in rows:
        solid = _row_solid(row)
        if solid is not None:
            body = row.Document.getObject(row.Body)
            source = (body, row.SolidName, row.Index) if body is not None else None
            made.append(createassembly.insert_into_new_part(solid, row.SolidName or row.Label, source=source))
    return made


def isolate(doc, rows):
    """Only the picked bodies show, until Exit Isolate (the Solid Bodies rows' menu)."""
    if doc.Name in _ISOLATED:
        exit_isolate(doc)       # a second Isolate starts from the look before the first one
    keep = {r.Name for r in rows}
    before = {}
    for row in _rows_of(doc):
        try:
            before[row.Name] = bool(row.ViewObject.Visibility)
            row.ViewObject.Visibility = row.Name in keep
        except Exception as _fw_err:
            _fw_log("multibody.py:1441", _fw_err)
    _ISOLATED[doc.Name] = before
    refresh(doc)
    _isolate_bar(doc)


def exit_isolate(doc):
    _drop_isolate_bar(doc)
    before = _ISOLATED.pop(doc.Name, None) or {}
    for name, shown in before.items():
        row = doc.getObject(name)
        if row is not None:
            try:
                row.ViewObject.Visibility = shown
            except Exception as _fw_err:
                _fw_log("multibody.py:1454", _fw_err)
    refresh(doc)


_ISO_BARS = {}          # doc name -> the Isolate bar shown for its isolated bodies


def _isolate_bar(doc):
    ""


    _drop_isolate_bar(doc)
    try:
        mw = Gui.getMainWindow()
        gl = [w for w in mw.findChildren(QtWidgets.QWidget) if w.inherits("QOpenGLWidget") and w.isVisible()]
        view = max(gl, key=lambda w: w.width() * w.height()) if gl else None
        bar = QtWidgets.QFrame(view.parentWidget() if view is not None else mw)
        bar.setObjectName("SWIsolateBar")
        bar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 4, 4)
        lay.addWidget(QtWidgets.QLabel("Isolate"))
        name = doc.Name
        save = QtWidgets.QPushButton("Save as Display State")
        save.setObjectName("SWIsolateSaveDisplayState")
        save.clicked.connect(lambda _c=False, n=name: _save_isolated(n))
        lay.addWidget(save)
        out = QtWidgets.QPushButton("Exit Isolate")
        out.setObjectName("SWExitIsolate")
        out.clicked.connect(lambda _c=False, n=name: n in App.listDocuments() and exit_isolate(App.getDocument(n)))
        lay.addWidget(out)
        bar.adjustSize()
        bar.move(12, 48)
        bar.show()
        bar.raise_()
        _ISO_BARS[name] = bar
    except Exception as _fw_err:
        _fw_log("multibody.py:isolate-bar", _fw_err)


def _drop_isolate_bar(doc):
    bar = _ISO_BARS.pop(getattr(doc, "Name", doc), None)
    if bar is None:
        return
    try:
        bar.hide()
        bar.deleteLater()
    except Exception as _fw_err:
        _fw_log("multibody.py:isolate-bar-drop", _fw_err)


def _save_isolated(doc_name):
    """Save as Display State: the isolated look becomes a new display state; the one shown before stays
    the active one (Exit Isolate goes back to it), as asmisolate does for components."""
    if doc_name not in App.listDocuments():
        return None
    doc = App.getDocument(doc_name)
    from . import displaystates as ds
    try:
        if not ds.names(doc):
            # the look from before Isolate is Display State 1, the isolated look the next one
            now = {r.Name: bool(r.ViewObject.Visibility) for r in _rows_of(doc)}
            for name, shown in (_ISOLATED.get(doc.Name) or {}).items():
                row = doc.getObject(name)
                if row is not None:
                    row.ViewObject.Visibility = shown
            refresh(doc)
            ds.ensure_default(doc)
            for name, shown in now.items():
                doc.getObject(name).ViewObject.Visibility = shown
            refresh(doc)
        data = ds._data(doc)
        data.setdefault("order", [])
        data.setdefault("states", {})
        name = ds._next_name(doc)
        data["states"][name] = ds.capture(doc)
        data["order"].append(name)
        data.setdefault("cfg", {})[name] = ds._config(doc)
        ds._save(doc, data)
        try:
            ds.refresh_panes()
        except Exception as _fw_err:
            _fw_log("multibody.py:isolate-panes", _fw_err)
        return name
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Save as Display State: %s\n" % error)
        return None


def _rows_of(doc):
    return [o for o in doc.Objects if getattr(getattr(o, "Proxy", None), "Type", "") == ROW_TYPE]


def save_bodies_page(doc, rows=()):
    ""
    from . import createassembly
    if Gui.Control.activeDialog():
        return None
    only = {(r.SolidName or "").replace("\u200b", "") for r in rows} or None
    panel = createassembly.CreateAssemblyPanel(doc, save_only=True, only=only)
    Gui.Control.showDialog(panel)
    return panel


def ensure_folder(doc):
    ""

    box = folder(doc)
    if box is None:
        box = _make_folder(doc)
        if App.GuiUp:
            box.ViewObject.ShowInTree = False
        box.purgeTouched()
    return box


def _make_folder(doc):
    obj = doc.addObject("App::FeaturePython", "SolidBodies")
    SolidBodiesFolder(obj)
    if App.GuiUp:
        SolidBodiesFolderView(obj.ViewObject)
    obj.Label = "Solid Bodies"
    return obj


def _make_row(doc):
    obj = doc.addObject("App::FeaturePython", "SolidBody")
    SolidBodyRow(obj)
    if App.GuiUp:
        SolidBodyRowView(obj.ViewObject)
    return obj


_selected_rows = set()
_GAP = "\u200b"   # zero-width space


def is_helper(obj):
    """The add-on's own rows and folders (Solid Bodies and its rows, Material), and anything named
    with the invisible zero-width space: never listed as features (Select Other, Parent/Child, ...)."""
    try:
        if getattr(getattr(obj, "Proxy", None), "Type", None) == NOMERGE_TYPE:
            return True          # the hidden step of Merge result off: part of its feature
        return _GAP in obj.Label or type(getattr(obj, "Proxy", None)).__name__.endswith(("Row", "Folder"))
    except Exception:
        return False


def _set_label(obj, text):
    ""

    if obj.Label.replace(_GAP, "") == text and obj.Label.startswith(text):
        return
    taken = {o.Label for o in obj.Document.Objects if o != obj}
    label = text
    while label in taken:
        label += _GAP
    obj.Label = label


def _drop_extra_folders(doc, box):
    """A second Solid Bodies folder (left by an older file or a lost class) took the label, so
    FreeCAD named the real one "Solid Bodies(1)001" (ChatGPT F11-13): only one folder is kept."""
    try:
        if App.GuiUp and Gui.Control.activeDialog():
            return          # never delete while a PropertyManager is open
    except Exception as _fw_err:
        _fw_log("multibody.py:1536", _fw_err)
    for obj in list(doc.Objects):
        if obj is box or obj.TypeId != "App::FeaturePython":
            continue
        kind = getattr(getattr(obj, "Proxy", None), "Type", None)
        stray = kind == FOLDER_TYPE or (kind is None and obj.Name.startswith("SolidBodies")
                                        and "Count" in obj.PropertiesList)
        if stray:
            try:
                doc.removeObject(obj.Name)
            except Exception as _fw_err:
                _fw_log("multibody.py:1547", _fw_err)


def sync(doc):
    """Brings the folder and its rows up to date with the solids, then draws hide/colour."""
    if doc is None or _restoring(doc):
        return
    body_list = bodies(doc)
    if not body_list and folder(doc) is None:
        return
    if _editing_sketch() is False and scope(doc):
        doc.recompute()
        return   # the recompute brings us back
    found = []   # (body, index, name)
    for body in body_list:
        for i, (name, _) in enumerate(solids(body)):
            found.append((body, i, name))
    box = folder(doc)
    if box is None:
        box = _make_folder(doc)
    _drop_extra_folders(doc, box)
    existing = rows(doc)
    by_key = {}
    for r in existing:
        by_key.setdefault((r.Body, r.SolidName), []).append(r)
    used = set()
    ordered = []
    spare = [r for r in existing]
    for body, i, name in found:
        match = None
        for r in by_key.get((body.Name, name), []):
            if r.Name not in used:
                match = r
                break
        if match is None:
            # A body renamed by a later feature keeps its row when it sits at the same place.
            match = next((r for r in spare if r.Name not in used and r.Body == body.Name and r.Index == i
                          and not any(n == r.SolidName for _, _, n in found)), None)
        if match is None:
            match = _make_row(doc)
            match.Body = body.Name
        used.add(match.Name)
        ordered.append(match)
        if match.SolidName != name:
            match.SolidName = name
        _set_label(match, name)
        if match.Index != i:
            match.Index = i
        if App.GuiUp and match.ViewObject is not None and not match.ViewObject.ShowInTree:
            match.ViewObject.ShowInTree = True
    body_names = {b.Name for b in body_list}
    for r in existing:
        if r.Name in used:
            continue
        if r.Body not in body_names:
            doc.removeObject(r.Name)
        elif App.GuiUp and r.ViewObject is not None and r.ViewObject.ShowInTree:
            # Gone for now (rolled back, or in edit); its settings come back with it.
            r.ViewObject.ShowInTree = False
    count = len(found)
    if box.Count != count:
        box.Count = count
    _set_label(box, "Solid Bodies(%d)" % count)
    if App.GuiUp and box.ViewObject is not None and box.ViewObject.ShowInTree != bool(count):
        box.ViewObject.ShowInTree = bool(count)
    # The folder and rows only hold settings: they never need a rebuild.
    for obj in [box] + rows(doc):
        try:
            obj.purgeTouched()
        except Exception as _fw_err:
            _fw_log("multibody.py:1617", _fw_err)
    if App.GuiUp:
        draw(doc)


def draw(doc):
    for body in bodies(doc):
        hidden = []
        colours = {}
        for r in rows(doc):
            if r.Body != body.Name or r.ViewObject is None or not r.ViewObject.ShowInTree:
                continue
            if not r.ViewObject.Visibility:
                hidden.append(r.Index)
            if r.Name in _selected_rows:
                colours[r.Index] = PICKED
            elif r.UseColour:
                colours[r.Index] = tuple(r.Colour[:3])
        try:
            apply_colours(body, colours)
            apply_hidden(body, hidden)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: body look not drawn: %s\n" % error)


def _editing_sketch():
    """None when unknown; False when no sketch is open."""
    try:
        gdoc = Gui.ActiveDocument if App.GuiUp else None
        edit = gdoc.getInEdit() if gdoc is not None else None
        return edit is not None and editobj.type_id(edit) == "Sketcher::SketchObject"
    except Exception as _fw_err:
        _fw_log("multibody.py:1668", _fw_err)
        return None


def _restoring(doc):
    try:
        return bool(doc.Restoring) or bool(getattr(doc, "Recomputing", False))
    except Exception:
        return True


_pending = set()


def later(doc):
    """Sync once, after FreeCAD has finished what it is doing."""
    if doc is None:
        return
    name = doc.Name
    if name in _pending:
        return
    _pending.add(name)

    def run():
        _pending.discard(name)
        try:
            d = App.getDocument(name)
        except Exception as _fw_err:
            _fw_log("multibody.py:1696", _fw_err)
            return
        try:
            from . import cleanfiles
            cleanfiles.restore(d)
        except Exception as _fw_err:
            _fw_log("multibody.py:1681", _fw_err)
        try:
            _keeping_units(d, lambda: sync(d))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Solid Bodies not updated: %s\n" % error)
    QtCore.QTimer.singleShot(0, run)


def _keeping_units(doc, work):
    """Stock FreeCAD 1.1: adding objects to a document that is not the active one switches the
    ACTIVE document's unit system to that document's (File handling, 11-26). The deferred sync can
    run after the user switched documents, so the active document's units are put back after it."""
    active = App.ActiveDocument
    keep = None
    if active is not None and active is not doc and "UnitSystem" in active.PropertiesList:
        keep = (active.UnitSystem, App.Units.getSchema())
    try:
        work()
    finally:
        if keep is not None:
            try:
                if active.UnitSystem != keep[0]:
                    active.UnitSystem = keep[0]
                if App.Units.getSchema() != keep[1]:
                    App.Units.setSchema(keep[1])
            except Exception as _fw_err:
                _fw_log("multibody.py:keep_units", _fw_err)


def refresh(doc):
    later(doc)


# ---- body features (Delete/Keep, Move/Copy, Combine, Mirror) -----------------------------

class _BodyOp:
    Type = None

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        if "Bodies" not in obj.PropertiesList:
            obj.addProperty("App::PropertyStringList", "Bodies", "Bodies", "Picked bodies (index:volume:x:y:z)")

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def picked(self, obj, pieces, texts=None):
        out = []
        for text in (obj.Bodies if texts is None else texts):
            i = resolve(text, pieces)
            if i is not None and i not in out:
                out.append(i)
        return out

    def dumps(self):
        return None

    def loads(self, state):
        return None


class DeleteKeep(_BodyOp):
    Type = "SWStyle::DeleteKeep"
    TITLE = "Body-Delete/Keep"

    def setup(self, obj):
        super().setup(obj)
        if "Keep" not in obj.PropertiesList:
            obj.addProperty("App::PropertyBool", "Keep", "Bodies", "Keep the picked bodies (off: delete them)")

    def execute(self, obj):
        pieces = _base_solids(obj)
        picked = set(self.picked(obj, pieces))
        if obj.Keep:
            out = [s for i, s in enumerate(pieces) if i in picked]
        else:
            out = [s for i, s in enumerate(pieces) if i not in picked]
        obj.Shape = _result(out)


class MoveCopy(_BodyOp):
    Type = "SWStyle::MoveCopy"
    TITLE = "Body-Move/Copy"

    def setup(self, obj):
        super().setup(obj)
        props = obj.PropertiesList
        if "Copy" not in props:
            obj.addProperty("App::PropertyBool", "Copy", "Bodies", "Copy the bodies (off: move them)")
        if "Copies" not in props:
            obj.addProperty("App::PropertyIntegerConstraint", "Copies", "Bodies", "Number of copies")
            obj.Copies = (1, 1, 1000, 1)
        if "Translate" not in props:
            obj.addProperty("App::PropertyVector", "Translate", "Translate", "Delta X, Y, Z")
        if "RotateCenter" not in props:
            obj.addProperty("App::PropertyVector", "RotateCenter", "Rotate", "Rotation origin")
        if "RotateAngles" not in props:
            obj.addProperty("App::PropertyVector", "RotateAngles", "Rotate", "Angles about X, Y, Z in degrees")

        for name, kind, group, tip in (
                ("TranslateMode", "App::PropertyEnumeration", "Translate", "Delta XYZ, along a picked edge, or from one vertex to another"),
                ("TranslateDir", "App::PropertyVector", "Translate", "The picked edge's direction"),
                ("TranslateDistance", "App::PropertyFloat", "Translate", "Distance along the edge"),
                ("TranslateFrom", "App::PropertyVector", "Translate", "First picked vertex"),
                ("TranslateTo", "App::PropertyVector", "Translate", "Second picked vertex"),
                ("TranslateRef", "App::PropertyString", "Translate", "What the Translate reference box shows"),
                ("RotateMode", "App::PropertyEnumeration", "Rotate", "X/Y/Z angles, or about a picked edge"),
                ("RotateAxis", "App::PropertyVector", "Rotate", "The picked edge's direction"),
                ("RotateAngle", "App::PropertyFloat", "Rotate", "Angle about the edge in degrees"),
                ("RotateRef", "App::PropertyString", "Rotate", "What the Rotate reference box shows"),
                ("EulerRotation", "App::PropertyBool", "Rotate", "Euler's angular rotation: the three angles are yaw, pitch and roll, each about the axes the turn before it left"),
                ("UseConstraints", "App::PropertyBool", "Constraints", "Place the bodies with mates"),
                ("Mates", "App::PropertyStringList", "Constraints", "The mates, one per line")):
            if name not in props:
                obj.addProperty(kind, name, group, tip)
                if name == "TranslateMode":
                    obj.TranslateMode = list(TRANSLATE_MODES)
                elif name == "RotateMode":
                    obj.RotateMode = list(ROTATE_MODES)

    def transform(self, obj):
        if getattr(obj, "UseConstraints", False) and getattr(obj, "Mates", None):
            return mate_placement(obj.Mates)
        mode = getattr(obj, "TranslateMode", "Delta XYZ")
        if mode == "Along edge":
            d = App.Vector(obj.TranslateDir)
            if d.Length > 1e-12:
                d.normalize()
            shift = d * float(obj.TranslateDistance)
        elif mode == "Vertex to vertex":
            shift = App.Vector(obj.TranslateTo) - App.Vector(obj.TranslateFrom)
        else:
            shift = App.Vector(obj.Translate)
        c = obj.RotateCenter
        if getattr(obj, "RotateMode", "X/Y/Z angles") == "About edge" and App.Vector(obj.RotateAxis).Length > 1e-12:
            rot = App.Rotation(App.Vector(obj.RotateAxis), float(obj.RotateAngle))
        elif getattr(obj, "EulerRotation", False):
            rot = euler_rotation(obj.RotateAngles)
        else:
            a = obj.RotateAngles
            rot = App.Rotation(App.Vector(0, 0, 1), a.z).multiply(
                App.Rotation(App.Vector(0, 1, 0), a.y)).multiply(App.Rotation(App.Vector(1, 0, 0), a.x))
        return App.Placement(shift, App.Rotation()).multiply(
            App.Placement(c, rot).multiply(App.Placement(-c, App.Rotation())))

    def execute(self, obj):
        pieces = _base_solids(obj)
        picked = self.picked(obj, pieces)
        step = self.transform(obj)
        out = []
        for i, s in enumerate(pieces):
            if i not in picked:
                out.append(s)
                continue
            if obj.Copy:
                out.append(s)
                place = App.Placement()
                for _ in range(max(1, obj.Copies)):
                    place = step.multiply(place)
                    out.append(_placed(s, place))
            else:
                out.append(_placed(s, step))
        # a lone moved solid would hand its move to the feature's Placement, which the body then
        # puts back: keep it inside a compound so the move stays in the shape
        obj.Shape = Part.makeCompound(out) if len(out) == 1 and not step.isIdentity() else _result(out)


def euler_rotation(angles):
    ""

    yaw, pitch, roll = angles.x, angles.y, angles.z
    return App.Rotation(App.Vector(0, 1, 0), yaw).multiply(
        App.Rotation(App.Vector(1, 0, 0), pitch)).multiply(App.Rotation(App.Vector(0, 0, 1), roll))


EULER_LABELS = ("Yaw", "Pitch", "Roll")
XYZ_LABELS = ("X Rotation Angle", "Y Rotation Angle", "Z Rotation Angle")


TRANSLATE_MODES = ("Delta XYZ", "Along edge", "Vertex to vertex")
ROTATE_MODES = ("X/Y/Z angles", "About edge")
MATES = ("Coincident", "Parallel", "Perpendicular", "Tangent", "Concentric", "Distance", "Angle")


def entity(shape):
    """A picked face, edge or vertex as mate geometry: ("plane", point, normal), ("axis", point,
    direction, radius) or ("point", point)."""
    V = App.Vector
    if shape.ShapeType == "Vertex":
        return ("point", V(shape.Point))
    if shape.ShapeType == "Edge":
        c = shape.Curve
        if isinstance(c, (Part.Line, Part.LineSegment)) or type(c).__name__ in ("Line", "LineSegment"):
            a, b = shape.Vertexes[0].Point, shape.Vertexes[-1].Point
            d = b - a
            d.normalize()
            return ("axis", V(a), d, 0.0)
        if type(c).__name__ in ("Circle", "ArcOfCircle"):
            return ("axis", V(c.Center), V(c.Axis), float(c.Radius))
        raise RuntimeError("Pick a straight or circular edge")
    if shape.ShapeType == "Face":
        surf = shape.Surface
        name = type(surf).__name__
        if name == "Plane":
            u, v = surf.parameter(shape.CenterOfMass)
            n = shape.normalAt(u, v)
            return ("plane", V(shape.CenterOfMass), V(n))
        if name in ("Cylinder", "Cone"):
            return ("axis", V(surf.Center), V(surf.Axis), float(getattr(surf, "Radius", 0.0)))
        if name == "Sphere":
            return ("point", V(surf.Center))
        raise RuntimeError("Pick a flat or round face")
    raise RuntimeError("Pick a face, edge or vertex")


def mate_text(kind, moving, fixed, value=0.0):
    def enc(e):
        return ";".join([e[0]] + ["%.9g,%.9g,%.9g" % (x.x, x.y, x.z) if isinstance(x, App.Vector) else "%.9g" % x
                                  for x in e[1:]])
    return "|".join((kind, enc(moving), enc(fixed), "%.9g" % value))


def _dec(text):
    parts = text.split(";")
    out = [parts[0]]
    for p in parts[1:]:
        nums = [float(x) for x in p.split(",")]
        out.append(App.Vector(*nums) if len(nums) == 3 else nums[0])
    return tuple(out)


def _moved(e, place):
    if e[0] == "point":
        return ("point", place.multVec(e[1]))
    if e[0] == "plane":
        return ("plane", place.multVec(e[1]), place.Rotation.multVec(e[2]))
    return ("axis", place.multVec(e[1]), place.Rotation.multVec(e[2]), e[3])


def _turn(place, frm, to, about):
    """place followed by the shortest turn of direction frm onto to, about the point."""
    rot = App.Rotation(frm, to)
    return App.Placement(about, rot).multiply(App.Placement(-about, App.Rotation())).multiply(place)


def _shift(place, d):
    return App.Placement(d, App.Rotation()).multiply(place)


def mate_placement(lines):
    """The moving bodies' placement that meets each mate in turn (each later mate keeps what it can
    of the earlier ones, as a simple sequential solve)."""
    import math
    place = App.Placement()
    for line in lines:
        try:
            kind, a, b, value = line.split("|")
            mov, fix, value = _dec(a), _dec(b), float(value)
        except Exception as _fw_err:
            _fw_log("multibody.py:1943", _fw_err)
            continue
        m = _moved(mov, place)
        if kind in ("Coincident", "Distance") and m[0] == "plane" and fix[0] == "plane":
            place = _turn(place, m[2], fix[2] * -1, m[1])
            m = _moved(mov, place)
            gap = (m[1] - fix[1]).dot(fix[2])
            want = value if kind == "Distance" else 0.0
            place = _shift(place, fix[2] * (want - gap))
        elif kind in ("Coincident", "Distance") and m[0] == "point" and fix[0] == "plane":
            gap = (m[1] - fix[1]).dot(fix[2])
            place = _shift(place, fix[2] * ((value if kind == "Distance" else 0.0) - gap))
        elif kind in ("Coincident", "Distance") and m[0] == "plane" and fix[0] == "point":
            gap = (fix[1] - m[1]).dot(m[2])
            place = _shift(place, m[2] * (gap - (value if kind == "Distance" else 0.0)))
        elif kind in ("Coincident", "Distance") and m[0] == "point" and fix[0] == "point":
            d = fix[1] - m[1]
            if kind == "Distance" and d.Length > 1e-12:
                place = _shift(place, d * ((d.Length - value) / d.Length))
            else:
                place = _shift(place, d)
        elif kind == "Parallel" and m[0] != "point" and fix[0] != "point":
            n = fix[2] if m[2].dot(fix[2]) >= 0 else fix[2] * -1
            place = _turn(place, m[2], n, m[1])
        elif kind == "Perpendicular" and m[0] != "point" and fix[0] != "point":
            t = m[2] - fix[2] * m[2].dot(fix[2])
            if t.Length < 1e-9:
                t = fix[2].cross(App.Vector(1, 0, 0) if abs(fix[2].x) < 0.9 else App.Vector(0, 1, 0))
            t.normalize()
            place = _turn(place, m[2], t, m[1])
        elif kind == "Angle" and m[0] != "point" and fix[0] != "point":
            axis = m[2].cross(fix[2])
            if axis.Length < 1e-9:
                axis = fix[2].cross(App.Vector(1, 0, 0) if abs(fix[2].x) < 0.9 else App.Vector(0, 1, 0))
            axis.normalize()
            target = App.Rotation(axis, value).multVec(fix[2])
            place = _turn(place, m[2], target, m[1])
        elif kind == "Concentric" and m[0] == "axis" and fix[0] == "axis":
            d = fix[2] if m[2].dot(fix[2]) >= 0 else fix[2] * -1
            place = _turn(place, m[2], d, m[1])
            m = _moved(mov, place)
            off = m[1] - fix[1]
            off = off - fix[2] * off.dot(fix[2])
            place = _shift(place, off * -1)
        elif kind == "Tangent" and {m[0], fix[0]} == {"plane", "axis"}:
            plane, axis = (fix, m) if fix[0] == "plane" else (m, fix)
            sign = 1 if fix[0] == "plane" else -1     # move the moving one
            gap = (axis[1] - plane[1]).dot(plane[2])
            want = axis[3] if gap >= 0 else -axis[3]
            place = _shift(place, plane[2] * ((want - gap) * sign))
        elif kind == "Tangent" and m[0] == "axis" and fix[0] == "axis":
            off = m[1] - fix[1]
            off = off - fix[2] * off.dot(fix[2])
            if off.Length > 1e-9:
                place = _shift(place, off * ((m[3] + fix[3] - off.Length) / off.Length))
        else:
            raise RuntimeError("A %s mate cannot join those two picks" % kind)
    return place


def _placed(solid, place):
    copy = solid.copy()
    copy.transformShape(place.toMatrix())
    return copy


class Combine(_BodyOp):
    Type = "SWStyle::Combine"
    TITLE = "Combine"
    OPERATIONS = ["Add", "Subtract", "Common"]

    def setup(self, obj):
        super().setup(obj)
        props = obj.PropertiesList
        if "Operation" not in props:
            obj.addProperty("App::PropertyEnumeration", "Operation", "Combine", "Add, Subtract or Common")
            obj.Operation = self.OPERATIONS
        if "MainBody" not in props:
            obj.addProperty("App::PropertyString", "MainBody", "Combine", "Main body (Subtract)")

    def execute(self, obj):
        pieces = _base_solids(obj)
        picked = self.picked(obj, pieces)
        if obj.Operation == "Subtract":
            main = self.picked(obj, pieces, [obj.MainBody]) if obj.MainBody else []
            main = main[0] if main else None
            tools = [i for i in picked if i != main]
            if main is None or not tools:
                obj.Shape = _result(pieces)
                return
            result = pieces[main].cut([pieces[i] for i in tools])
            used = {main} | set(tools)
        else:
            if len(picked) < 2:
                obj.Shape = _result(pieces)
                return
            first = pieces[picked[0]]
            rest = [pieces[i] for i in picked[1:]]
            if obj.Operation == "Add":
                result = first.fuse(rest)
                try:
                    result = result.removeSplitter()
                except Exception as _fw_err:
                    _fw_log("multibody.py:2024", _fw_err)
            else:
                result = first
                for other in rest:
                    result = result.common(other)
            used = set(picked)
        out = [s for i, s in enumerate(pieces) if i not in used]
        out.extend(result.Solids)
        obj.Shape = _result(out)


class MirrorBody(_BodyOp):
    Type = "SWStyle::MirrorBody"
    TITLE = "Mirror"

    def setup(self, obj):
        super().setup(obj)
        props = obj.PropertiesList
        if "MirrorPlane" not in props:
            obj.addProperty("App::PropertyLinkSub", "MirrorPlane", "Mirror", "Mirror face or plane")
        if "Merge" not in props:
            obj.addProperty("App::PropertyBool", "Merge", "Mirror", "Merge solids")
            obj.Merge = True

    def plane(self, obj):
        link = obj.MirrorPlane
        if not link:
            return None
        target, subs = link[0], link[1]
        try:
            if subs and subs[0]:
                face = target.Shape.getElement(subs[0])
                surface = face.Surface
                u0, u1, v0, v1 = face.ParameterRange
                point = face.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
                normal = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
                return point, normal
            place = target.Placement
            body = body_of(obj)
            # Origin planes are placed in the Body's coordinates already.
            normal = place.Rotation.multVec(App.Vector(0, 0, 1))
            return place.Base, normal
        except Exception:
            return None

    def execute(self, obj):
        pieces = _base_solids(obj)
        picked = self.picked(obj, pieces)
        plane = self.plane(obj)
        if plane is None or not picked:
            obj.Shape = _result(pieces)
            return
        point, normal = plane
        out = list(pieces)
        copies = [pieces[i].mirror(point, normal) for i in picked]
        if obj.Merge:
            merged_out = []
            touched = set()
            for k, i in enumerate(picked):
                fused = pieces[i].fuse(copies[k])
                try:
                    fused = fused.removeSplitter()
                except Exception as _fw_err:
                    _fw_log("multibody.py:2087", _fw_err)
                merged_out.extend(fused.Solids)
                touched.add(i)
            out = [s for i, s in enumerate(pieces) if i not in touched] + merged_out
        else:
            for c in copies:
                out.extend(c.Solids)
        obj.Shape = _result(out)


OPS = {"DeleteKeep": DeleteKeep, "MoveCopy": MoveCopy, "Combine": Combine, "MirrorBody": MirrorBody}


def _weak(method):
    """A PM box menu callback that does not keep its closed PropertyManager alive."""
    import weakref
    ref = weakref.WeakMethod(method)

    def call(*args):
        bound = ref()
        return bound(*args) if bound is not None else None
    return call


class BodyOpView:
    def __init__(self, vobj):
        self.Object = vobj.Object
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        obj = getattr(self, "Object", None)       # FreeCAD can ask for the icon before attach after a reopen
        kind = getattr(getattr(obj, "Proxy", None), "Type", "")
        return _icon({"SWStyle::DeleteKeep": "delete", "SWStyle::MoveCopy": "move",
                      "SWStyle::Combine": "combine", "SWStyle::MirrorBody": "mirror"}.get(kind, "bodies"))

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        Gui.Control.showDialog(BodyOpPanel(vobj.Object, new=False))
        return True

    def unsetEdit(self, vobj, mode=0):
        Gui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def onDelete(self, vobj, subelements):
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _active_body(doc, picked_rows):
    for r in picked_rows:
        b = doc.getObject(r.Body)
        if b is not None:
            return b
    try:
        for sel in Gui.Selection.getSelectionEx(doc.Name):
            b = body_of(sel.Object)
            if b is not None:
                return b
    except Exception as _fw_err:
        _fw_log("multibody.py:2160", _fw_err)
    try:
        view = Gui.ActiveDocument.ActiveView
        b = view.getActiveObject("pdbody")
        if b is not None:
            return b
    except Exception as _fw_err:
        _fw_log("multibody.py:2167", _fw_err)
    found = bodies(doc)
    return found[0] if found else None


def _picked_refs(doc, body, picked_rows):
    """Bodies the user had picked before starting: rows of the folder and faces in the view."""
    pieces = [s for _, s in solids(body)]
    out = []
    for r in picked_rows:
        if r.Body == body.Name and 0 <= r.Index < len(pieces):
            out.append(ref_text(r.Index, pieces[r.Index]))
    try:
        for sel in Gui.Selection.getSelectionEx(doc.Name):
            if getattr(getattr(sel.Object, "Proxy", None), "Type", None) == ROW_TYPE:
                r = sel.Object
                if r.Body == body.Name and 0 <= r.Index < len(pieces):
                    out.append(ref_text(r.Index, pieces[r.Index]))
                continue
            for sub in sel.SubElementNames:
                b, i = solid_index_of(sel.Object, sub)
                if b == body and i is not None:
                    out.append(ref_text(i, pieces[i]))
    except Exception as _fw_err:
        _fw_log("multibody.py:2191", _fw_err)
    unique = []
    for t in out:
        if t not in unique:
            unique.append(t)
    return unique


def start_op(kind, doc=None, picked_rows=()):
    """Inserts a body feature at the end of the Body's history (the rollback bar) and opens
    its PropertyManager."""
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    body = _active_body(doc, list(picked_rows))
    if body is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Solid Bodies", "The part has no solid body yet.")
        return None
    refs = _picked_refs(doc, body, list(picked_rows))
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    doc.openTransaction(OPS[kind].TITLE)
    try:
        _fix_compound(body)
        obj = doc.addObject("PartDesign::FeaturePython", kind)
        OPS[kind](obj)
        if App.GuiUp:
            BodyOpView(obj.ViewObject)
        try:
            from . import naming
            obj.Label = naming.next_label(doc, OPS[kind].TITLE)
        except Exception:
            obj.Label = OPS[kind].TITLE + "1"
        body.addObject(obj)
        obj.Bodies = refs
        if kind == "MirrorBody":
            try:
                planes = [f for f in body.Origin.OriginFeatures if f.TypeId == "App::Plane"]
                front = next((p for p in planes if p.Role == "XZ_Plane"), planes[0] if planes else None)
                if front is not None:
                    obj.MirrorPlane = (front, [""])
            except Exception as _fw_err:
                _fw_log("multibody.py:2232", _fw_err)
        doc.recompute()
        Gui.Selection.clearSelection()
        if App.GuiUp:
            Gui.Control.showDialog(BodyOpPanel(obj, new=True))
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    return obj


def _in_task_view(w):
    """True for the task pane's own OK/Cancel box (Gui::TaskView::TaskView ancestor)."""
    while w is not None:
        if "TaskView" in w.metaObject().className():
            return True
        w = w.parentWidget()
    return False


ACTIVE_PANEL = []       # the open body-feature PM (bodysize.py fills its Bodies box)


def _box_visible(w, on):
    """Show or hide a form widget and the task panel box that wraps it (title bar included)."""
    w.setVisible(on)
    box = w.parentWidget()
    while box is not None and not box.inherits("Gui::TaskView::TaskBox"):
        box = box.parentWidget()
    if box is not None:
        box.setVisible(on)


class BodyOpPanel:
    ""

    def __init__(self, obj, new):
        ACTIVE_PANEL[:] = [self]
        self.doc = obj.Document
        self.name = obj.Name
        self.new = new
        self.kind = obj.Proxy.Type
        self.body = body_of(obj)
        if not new:
            self.doc.openTransaction("Edit " + obj.Label)
        self.form = QtWidgets.QWidget()
        title = {"SWStyle::DeleteKeep": "Body-Delete/Keep", "SWStyle::MoveCopy": "Move/Copy Body",
                 "SWStyle::Combine": "Combine", "SWStyle::MirrorBody": "Mirror"}[self.kind]
        self.form.setWindowTitle(title)
        self.form.setProperty("swstyle_pm_title", title)
        self.form.setProperty("swstyle_pm_icon", {"SWStyle::Combine": "FEATURES_COMBINE",
                                                  "SWStyle::MirrorBody": "FEATURES_MIRROR"}.get(self.kind, ""))
        layout = QtWidgets.QVBoxLayout(self.form)
        self.target = "Bodies"
        if self.kind == "SWStyle::DeleteKeep":
            layout.addWidget(self._title("Type"))
            self.delete = QtWidgets.QRadioButton("Delete Bodies")
            self.keep = QtWidgets.QRadioButton("Keep Bodies")
            (self.keep if obj.Keep else self.delete).setChecked(True)
            self.keep.toggled.connect(self._set_keep)
            layout.addWidget(self.delete)
            layout.addWidget(self.keep)
            layout.addWidget(self._title("Bodies to Delete/Keep"))
        elif self.kind == "SWStyle::MoveCopy":

            # task panel's boxes, titled by each form); the first box's title names the bodies list
            self.form.setWindowTitle("Bodies to Move/Copy")
        elif self.kind == "SWStyle::Combine":
            layout.addWidget(self._title("Operation Type"))
            self.ops = []
            for name in Combine.OPERATIONS:
                button = QtWidgets.QRadioButton(name)
                button.setChecked(obj.Operation == name)
                button.toggled.connect(lambda on, n=name: on and self._set_op(n))
                layout.addWidget(button)
                self.ops.append(button)
            self.main_title = self._title("Main Body")
            layout.addWidget(self.main_title)
            self.main = QtWidgets.QListWidget()
            self.main.setMaximumHeight(28)
            self.main.setObjectName("SWStyle_MainBody")
            self.main.installEventFilter(_Focus(self, "MainBody", self.main))
            from . import pmboxes
            pmboxes.bind(self.main, _weak(self._clear_main), _weak(self._clear_main))
            layout.addWidget(self.main)
            self.bodies_title = self._title("Bodies to Combine")
            layout.addWidget(self.bodies_title)
        else:
            layout.addWidget(self._title("Mirror Face/Plane"))
            self.plane = QtWidgets.QLineEdit()
            self.plane.setReadOnly(True)
            self.plane.setObjectName("SWStyle_MirrorPlane")
            self.plane.installEventFilter(_Focus(self, "MirrorPlane", self.plane))
            layout.addWidget(self.plane)
            layout.addWidget(self._title("Bodies to Mirror"))
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWStyle_BodiesList")
        self.list.setMinimumHeight(70)
        self.list.setMaximumHeight(90)   # pkg447: a selection box, not the rest of the page (190 px before); the dot drags it taller
        self.list.installEventFilter(_Focus(self, "Bodies", self.list))
        from . import pmboxes
        pmboxes.bind(self.list, _weak(self._remove_body), _weak(self._clear_bodies))
        if self.kind in ("SWStyle::DeleteKeep", "SWStyle::MoveCopy"):

            self.list.setProperty("swNeed", True)
            self.list.setToolTip("Bodies to delete or keep" if self.kind == "SWStyle::DeleteKeep" else "Bodies to move or copy")
        layout.addWidget(self.list)
        if self.kind == "SWStyle::DeleteKeep":

            self.by_size = QtWidgets.QPushButton("Select Bodies by Size...")
            self.by_size.setObjectName("SWStyle_BodiesBySize")
            self.by_size.setToolTip("Picks the bodies no bigger than a percent of the part")
            self.by_size.clicked.connect(self._bodies_by_size)
            layout.addWidget(self.by_size)
        self._preview_node = None
        if self.kind == "SWStyle::Combine":

            self.preview_button = QtWidgets.QPushButton("Show Preview")
            self.preview_button.setObjectName("SWStyle_CombinePreview")
            self.preview_button.setToolTip("Shows the combined body")
            self.preview_button.clicked.connect(self._show_preview)
            layout.addWidget(self.preview_button)

            # pick bodies inside or behind others; they are opaque again when it closes
            self.see_through = QtWidgets.QCheckBox("Body transparency")
            self.see_through.setObjectName("SWStyle_CombineTransparency")
            self.see_through.setToolTip("Shows the bodies see-through while picking them")
            self.see_through.toggled.connect(self._set_see_through)
            layout.addWidget(self.see_through)
            self._was_clear = {}
        if self.kind == "SWStyle::MoveCopy":
            self.copy = QtWidgets.QCheckBox("Copy")
            self.copy.setChecked(obj.Copy)
            self.copies = QtWidgets.QSpinBox()
            self.copies.setRange(1, 1000)
            self.copies.setObjectName("SWStyle_Copies")
            self.copies.setToolTip("Number of Copies")
            self.copies.setValue(obj.Copies)
            self.copies.setEnabled(obj.Copy)
            self.copy.toggled.connect(self._set_copy)
            self.copies.valueChanged.connect(lambda v: self._set("Copies", v))
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self.copy)
            row.addWidget(self.copies)
            layout.addLayout(row)
            self.trans_form = QtWidgets.QWidget()
            self.trans_form.setWindowTitle("Translate")
            free = QtWidgets.QVBoxLayout(self.trans_form)
            self.trans_ref = self._ref_box(free, "SWStyle_TranslateRef", "TranslateRef",
                                           "Translate reference: an edge (then a distance) or two vertices")
            self.trans_dist = self._number(free, "Distance", "TranslateDistance", "mm")
            self.delta = self._vector(free, ("Delta X", "Delta Y", "Delta Z"), obj.Translate, "Translate", "mm")
            self.rot_form = QtWidgets.QWidget()
            self.rot_form.setWindowTitle("Rotate")
            free = QtWidgets.QVBoxLayout(self.rot_form)
            self.rot_ref = self._ref_box(free, "SWStyle_RotateRef", "RotateRef",
                                         "Rotation reference: an edge to turn about, or a vertex as the origin")
            self.rot_angle = self._number(free, "Angle", "RotateAngle", "deg")
            self.center = self._vector(free, ("X Rotation Origin", "Y Rotation Origin", "Z Rotation Origin"),
                                       obj.RotateCenter, "RotateCenter", "mm")
            self.euler = QtWidgets.QCheckBox("Euler's angular rotation")
            self.euler.setObjectName("SWStyle_EulerRotation")
            self.euler.setToolTip("Rotate by yaw, pitch and roll, each about the axes the turn before it left")
            self.euler.setChecked(bool(getattr(obj, "EulerRotation", False)))
            self.euler.toggled.connect(self._euler_toggled)
            free.addWidget(self.euler)
            self.angles = self._vector(free, XYZ_LABELS, obj.RotateAngles, "RotateAngles", "deg")
            self._euler_labels()
            self.free = [self.trans_form, self.rot_form]
            self.mates_page = QtWidgets.QWidget()
            self.mates_page.setWindowTitle("Mate Selections")
            mlay = QtWidgets.QVBoxLayout(self.mates_page)
            self.mate_picks = []
            self.mate_box = QtWidgets.QListWidget()
            self.mate_box.setObjectName("SWStyle_MateSelections")
            self.mate_box.setMaximumHeight(46)
            self.mate_box.installEventFilter(_Focus(self, "Mate", self.mate_box))
            mlay.addWidget(self.mate_box)
            mlay.addWidget(self._title("Standard Mates"))
            self.mate_kind = {}
            group = QtWidgets.QButtonGroup(self.mates_page)
            for name in MATES:
                b = QtWidgets.QRadioButton(name)
                b.setObjectName("SWStyle_Mate_" + name)
                group.addButton(b)
                mlay.addWidget(b)
                self.mate_kind[name] = b
                b.toggled.connect(lambda on: self._mate_value_shown())
            self.mate_kind["Coincident"].setChecked(True)
            self._mate_group = group
            self.mate_value = QtWidgets.QDoubleSpinBox()
            self.mate_value.setObjectName("SWStyle_MateValue")
            self.mate_value.setRange(-1e6, 1e6)
            self.mate_value.setDecimals(3)
            mlay.addWidget(self.mate_value)
            add = QtWidgets.QPushButton("Add Mate")
            add.setObjectName("SWStyle_MateAdd")
            add.clicked.connect(self._add_mate)
            mlay.addWidget(add)
            mlay.addWidget(self._title("Mates"))
            self.mate_list = QtWidgets.QListWidget()
            self.mate_list.setObjectName("SWStyle_MateList")
            self.mate_list.setMaximumHeight(80)
            self.mate_list.setContextMenuPolicy(QtCore.Qt.ActionsContextMenu)
            drop = QtGui.QAction("Delete", self.mate_list)
            drop.triggered.connect(self._delete_mate)
            self.mate_list.addAction(drop)
            mlay.addWidget(self.mate_list)
            self.mode_button = QtWidgets.QPushButton()
            self.mode_button.setObjectName("SWStyle_MoveCopyMode")
            self.mode_button.clicked.connect(self._toggle_mode)

            # Rotate group, or under the mates in Constraints mode (_show_mode moves it)
            self._mate_value_shown()
            self._show_mode()

            from . import bodytriad
            self.triad = bodytriad.show(self)
        if self.kind == "SWStyle::MirrorBody":
            layout.addWidget(self._title("Options"))
            self.merge = QtWidgets.QCheckBox("Merge solids")
            self.merge.setChecked(obj.Merge)
            self.merge.toggled.connect(lambda on: self._set("Merge", on))
            layout.addWidget(self.merge)
        layout.addStretch(1)
        if self.kind == "SWStyle::MoveCopy":
            self.form.setProperty("swstyle_pm_title", "Move/Copy Body")
            self.form = [self.form, self.trans_form, self.rot_form, self.mates_page]
        self._fill()
        Gui.Selection.addObserver(self)
        if self.kind == "SWStyle::MoveCopy":
            QtCore.QTimer.singleShot(0, _weak(self._show_mode))     # the boxes exist once the panel shows
        self._sync_op_fields()

    # -- widgets --
    def _title(self, text):
        label = QtWidgets.QLabel(text)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        return label

    def _vector(self, layout, labels, value, prop, unit):
        boxes = []
        for i, text in enumerate(labels):
            row = QtWidgets.QHBoxLayout()
            row_label = QtWidgets.QLabel(text)
            row.addWidget(row_label)
            box = QtWidgets.QDoubleSpinBox()
            box.row_label = row_label
            box.setRange(-1e6, 1e6)
            box.setDecimals(3)
            box.setSuffix(" " + unit)
            box.setValue((value.x, value.y, value.z)[i])
            box.setObjectName("SWStyle_%s_%d" % (prop, i))
            box.valueChanged.connect(lambda v, p=prop, k=i: self._set_axis(p, k, v))
            row.addWidget(box)
            layout.addLayout(row)
            boxes.append(box)
        return boxes

    def obj(self):
        return self.doc.getObject(self.name)

    def _pieces(self):
        obj = self.obj()
        return _base_solids(obj) if obj is not None else []

    def _names(self):
        """Names of the bodies as they were before this feature."""
        obj = self.obj()
        base = getattr(obj, "BaseFeature", None)
        if base is None or self.body is None:
            return []
        chain = []
        for f in self.body.Group:
            if _solid_feature(f) and not getattr(f, "Suppressed", False):
                chain.append(f)
            if f == base:
                break
        return _history_names(chain, base.Shape.Solids)

    def _fill(self):
        obj = self.obj()
        if obj is None:
            return
        pieces = self._pieces()
        names = self._names()
        self.list.clear()
        for text in obj.Bodies:
            i = resolve(text, pieces)
            self.list.addItem(names[i] if i is not None and i < len(names) else "(missing body)")
        if self.kind == "SWStyle::Combine":
            self.main.clear()
            if obj.MainBody:
                i = resolve(obj.MainBody, pieces)
                self.main.addItem(names[i] if i is not None and i < len(names) else "(missing body)")
        if self.kind == "SWStyle::MirrorBody":
            link = obj.MirrorPlane
            if link:
                text = link[0].Label + ("." + link[1][0] if link[1] and link[1][0] else "")
            else:
                text = ""
            self.plane.setText(text)
        self._gate_ok()

    def _nothing_picked(self):
        ""


        why = {"SWStyle::DeleteKeep": "Select the bodies to delete or keep first.",
               "SWStyle::MoveCopy": "Select the bodies to move or copy first."}.get(self.kind)
        obj = self.obj() if why else None
        if obj is None or list(getattr(obj, "Bodies", []) or []):
            return False
        try:
            from . import pmmessage
            Gui.getMainWindow().statusBar().showMessage(why, 4000)
            pmmessage.notice(self.form.window(), why)
        except Exception as _fw_err:
            _fw_log("multibody.py:nothing-picked", _fw_err)
        return True

    def _ready(self):
        ""

        if self.kind != "SWStyle::Combine":
            return True
        obj = self.obj()
        if obj is None:
            return False
        if obj.Operation == "Subtract":
            return bool(obj.MainBody) and len(obj.Bodies) >= 1
        return len(obj.Bodies) >= 2

    def _gate_ok(self):
        ready = self._ready()
        try:
            for box in Gui.getMainWindow().findChildren(QtWidgets.QDialogButtonBox):
                ok = box.button(QtWidgets.QDialogButtonBox.Ok)
                if ok is not None and _in_task_view(box):
                    ok.setEnabled(ready)
        except Exception as _fw_err:
            _fw_log("multibody.py:2528", _fw_err)
        if not ready:
            QtCore.QTimer.singleShot(300, self._gate_later)

    def _gate_later(self):
        try:
            if Gui.Control.activeDialog() and self.obj() is not None:
                self._gate_ok()
        except Exception as _fw_err:
            _fw_log("multibody.py:2537", _fw_err)

    def _sync_op_fields(self):
        if self.kind != "SWStyle::Combine":
            return
        subtract = self.obj().Operation == "Subtract"
        self.main_title.setVisible(subtract)
        self.main.setVisible(subtract)
        self.bodies_title.setText("Bodies to Subtract" if subtract else "Bodies to Combine")

    # -- Combine: Show Preview --
    def _set_see_through(self, on):
        """Body transparency: every shown solid of the part at 70 % transparency (restored after)."""
        if on:
            for o in self.doc.Objects:
                vo = getattr(o, "ViewObject", None)
                try:
                    if vo is None or not vo.Visibility or "Transparency" not in vo.PropertiesList:
                        continue
                    if o.TypeId.startswith("Sketcher") or o.TypeId.startswith("App::") or o.TypeId == "PartDesign::Body":
                        continue
                    self._was_clear.setdefault(o.Name, vo.Transparency)
                    vo.Transparency = 70
                except Exception:
                    continue
        else:
            self._restore_clear()

    def _restore_clear(self):
        for name, value in list(getattr(self, "_was_clear", {}).items()):
            o = self.doc.getObject(name)
            try:
                if o is not None and o.ViewObject is not None:
                    o.ViewObject.Transparency = value
            except Exception as _fw_err:
                _fw_log("multibody.py:2572", _fw_err)
        self._was_clear = {}

    def _clear_preview(self):
        got, self._preview_node = getattr(self, "_preview_node", None), None
        if got is not None:
            try:
                got[0].removeChild(got[1])
            except Exception as _fw_err:
                _fw_log("multibody.py:2581", _fw_err)

    def _show_preview(self):
        self._rebuild()
        obj = self.obj()
        if obj is None or obj.Shape.isNull() or "Invalid" in obj.State:
            return
        try:
            from pivy import coin
            inp = coin.SoInput()
            inp.setBuffer(obj.Shape.writeInventor())
            geo = coin.SoDB.readAll(inp)
            if geo is None:
                return
            sep = coin.SoSeparator()
            pick = coin.SoPickStyle()
            pick.style = coin.SoPickStyle.UNPICKABLE
            sep.addChild(pick)
            mat = coin.SoMaterial()
            mat.diffuseColor = (0.0, 0.85, 0.95)
            mat.emissiveColor = (0.0, 0.25, 0.3)
            mat.transparency = 0.45
            mat.setOverride(True)
            sep.addChild(mat)
            sep.addChild(geo)
            root = Gui.getDocument(self.doc.Name).ActiveView.getSceneGraph()
            root.addChild(sep)
            self._preview_node = (root, sep)
        except Exception as error:
            App.Console.PrintLog("FreeCAD Combine preview: %s\n" % error)

    # -- changes --
    def _rebuild(self):
        self._clear_preview()
        obj = self.obj()
        if obj is not None:
            obj.touch()
            self.doc.recompute()
        self._fill()

    def _set(self, prop, value):
        obj = self.obj()
        if obj is not None:
            setattr(obj, prop, value)
            self._rebuild()

    def _set_axis(self, prop, k, value):
        obj = self.obj()
        if obj is None:
            return
        v = App.Vector(getattr(obj, prop))
        if k == 0:
            v.x = value
        elif k == 1:
            v.y = value
        else:
            v.z = value
        self._set(prop, v)

    def _set_keep(self, keep):
        self._set("Keep", keep)

    def _bodies_by_size(self):
        from . import bodysize
        return bodysize.open_box(self.doc)

    # -- Move/Copy references and Constraints --
    def _ref_box(self, layout, name, prop, tip):
        box = QtWidgets.QListWidget()
        box.setObjectName(name)
        box.setMaximumHeight(28)
        box.setToolTip(tip)
        box.installEventFilter(_Focus(self, prop, box))
        from . import pmboxes
        clear = _weak(self._clear_ref)
        pmboxes.bind(box, lambda row, p=prop: clear(p), lambda p=prop: clear(p))
        layout.addWidget(box)
        return box

    def _number(self, layout, label, prop, unit):
        row = QtWidgets.QHBoxLayout()
        text = QtWidgets.QLabel(label)
        row.addWidget(text)
        box = QtWidgets.QDoubleSpinBox()
        box.setRange(-1e6, 1e6)
        box.setDecimals(3)
        box.setSuffix(" " + unit)
        box.setObjectName("SWStyle_%s" % prop)
        box.setValue(float(getattr(self.obj(), prop)))
        box.valueChanged.connect(lambda v, p=prop: self._set(p, v))
        row.addWidget(box)
        layout.addLayout(row)
        box.label = text
        return box

    def _clear_ref(self, prop):
        obj = self.obj()
        if prop == "TranslateRef":
            obj.TranslateMode, obj.TranslateRef = "Delta XYZ", ""
        else:
            obj.RotateMode, obj.RotateRef = "X/Y/Z angles", ""
        self._rebuild()
        self._show_refs()

    def _show_refs(self):
        if self.kind != "SWStyle::MoveCopy":
            return
        obj = self.obj()
        for box, text in ((self.trans_ref, obj.TranslateRef), (self.rot_ref, obj.RotateRef)):
            box.clear()
            if text:
                box.addItem(text)
        tmode, rmode = obj.TranslateMode, obj.RotateMode
        for w in self.delta:
            w.setVisible(tmode == "Delta XYZ")
        for w, on in ((self.trans_dist, tmode == "Along edge"), (self.rot_angle, rmode == "About edge")):
            w.setVisible(on)
            w.label.setVisible(on)
        for w in self.angles:
            w.setVisible(rmode != "About edge")
        self.euler.setVisible(rmode != "About edge")
        self._labels_follow()

    def _euler_toggled(self, on):
        obj = self.obj()
        if obj is None:
            return
        obj.EulerRotation = bool(on)
        self._euler_labels()
        self._rebuild()

    def _euler_labels(self):
        on = self.euler.isChecked()
        for box, text in zip(self.angles, EULER_LABELS if on else XYZ_LABELS):
            box.row_label.setText(text)
            box.label = text

    def _labels_follow(self):
        """The labels in the vector rows show and hide with their boxes."""
        for box in self.delta + self.angles + self.center:
            row = getattr(box, "row_label", None)
            if row is not None:
                row.setVisible(not box.isHidden())

    def _ref_pick(self, prop, element, text):
        obj = self.obj()
        if prop == "TranslateRef":
            if element.ShapeType == "Edge" and element.Vertexes:
                d = element.Vertexes[-1].Point - element.Vertexes[0].Point
                if d.Length < 1e-9:
                    return
                obj.TranslateMode, obj.TranslateDir, obj.TranslateRef = "Along edge", d, text
                if abs(obj.TranslateDistance) < 1e-12:
                    obj.TranslateDistance = 10.0
            elif element.ShapeType == "Vertex":
                if obj.TranslateMode == "Vertex to vertex" and obj.TranslateRef.count(",") == 0 and obj.TranslateRef:
                    obj.TranslateTo, obj.TranslateRef = element.Point, obj.TranslateRef + ", " + text
                else:
                    obj.TranslateMode, obj.TranslateFrom, obj.TranslateTo = "Vertex to vertex", element.Point, element.Point
                    obj.TranslateRef = text
            else:
                return
        else:
            if element.ShapeType == "Edge" and element.Vertexes:
                e = entity(element)
                obj.RotateMode, obj.RotateAxis, obj.RotateCenter, obj.RotateRef = "About edge", e[2], e[1], text
                if abs(obj.RotateAngle) < 1e-12:
                    obj.RotateAngle = 90.0
            elif element.ShapeType == "Vertex":
                obj.RotateMode, obj.RotateCenter, obj.RotateRef = "X/Y/Z angles", element.Point, text
            else:
                return
        self._rebuild()
        for box, v in zip(self.center, (obj.RotateCenter.x, obj.RotateCenter.y, obj.RotateCenter.z)):
            box.blockSignals(True)
            box.setValue(v)
            box.blockSignals(False)
        for box, p in ((self.trans_dist, "TranslateDistance"), (self.rot_angle, "RotateAngle")):
            box.blockSignals(True)
            box.setValue(float(getattr(obj, p)))
            box.blockSignals(False)
        self._show_refs()

    def _toggle_mode(self):
        obj = self.obj()
        obj.UseConstraints = not obj.UseConstraints
        self.target = "Mate" if obj.UseConstraints else "Bodies"
        self._rebuild()
        self._show_mode()

    def _show_mode(self):
        on = bool(self.obj().UseConstraints)
        for w, shown in ((self.trans_form, not on), (self.rot_form, not on), (self.mates_page, on)):
            _box_visible(w, shown)
        home = (self.mates_page if on else self.rot_form).layout()
        if home.indexOf(self.mode_button) < 0:
            home.addWidget(self.mode_button)
        self.mode_button.show()

        self.mode_button.setText("Translate/Rotate" if on else "Constraints")
        self.mate_list.clear()
        for line in self.obj().Mates:
            kind, _a, _b, value = (line.split("|") + ["", "", "", "0"])[:4]
            self.mate_list.addItem(kind + ("  %s" % value if kind in ("Distance", "Angle") else ""))
        self._show_refs()

    def _mate_value_shown(self):
        if not hasattr(self, "mate_value"):
            return                  # still building the page
        kind = next((n for n, b in self.mate_kind.items() if b.isChecked()), "Coincident")
        self.mate_value.setVisible(kind in ("Distance", "Angle"))
        self.mate_value.setSuffix(" deg" if kind == "Angle" else " mm")

    def _mate_pick(self, element, text, moving):
        try:
            geo = entity(element)
        except Exception as error:
            App.Console.PrintWarning("Move/Copy Body: %s\n" % error)
            return
        self.mate_picks.append((geo, text, moving))
        self.mate_picks = self.mate_picks[-2:]
        self.mate_box.clear()
        for _g, t, _m in self.mate_picks:
            self.mate_box.addItem(t)

    def _add_mate(self):
        if len(self.mate_picks) < 2:
            return
        (ga, ta, ma), (gb, tb, mb) = self.mate_picks
        if mb and not ma:
            ga, gb = gb, ga
        kind = next((n for n, b in self.mate_kind.items() if b.isChecked()), "Coincident")
        obj = self.obj()
        obj.Mates = list(obj.Mates) + [mate_text(kind, ga, gb, self.mate_value.value())]
        self.mate_picks = []
        self.mate_box.clear()
        self._rebuild()
        self._show_mode()

    def _delete_mate(self):
        row = self.mate_list.currentRow()
        obj = self.obj()
        mates = list(obj.Mates)
        if 0 <= row < len(mates):
            mates.pop(row)
            obj.Mates = mates
            self._rebuild()
            self._show_mode()

    def _set_copy(self, on):
        self.copies.setEnabled(on)
        self._set("Copy", on)

    def _set_op(self, name):
        self._set("Operation", name)
        self._sync_op_fields()

    def _remove_body(self, row):
        obj = self.obj()
        if obj is not None and 0 <= row < len(obj.Bodies):
            current = list(obj.Bodies)
            current.pop(row)
            self._set("Bodies", current)

    def _clear_main(self, *_row):
        self._set("MainBody", "")

    def _clear_bodies(self):
        self._set("Bodies", [])

    def _clear(self):
        if self.target == "MainBody":
            self._set("MainBody", "")
        else:
            self._set("Bodies", [])

    # -- picking in the view or the tree --
    def addSelection(self, doc, obj_name, sub, pos):
        if pickguard.stale(self, self.doc):
            return
        if doc != self.doc.Name:
            return
        QtCore.QTimer.singleShot(0, lambda: self._picked(obj_name, sub, pos))

    def _picked(self, obj_name, sub, pos=None):
        obj = self.obj()
        picked = self.doc.getObject(obj_name)
        if obj is None or picked is None:
            return
        if self.kind == "SWStyle::DeleteKeep" and not list(getattr(obj, "Bodies", None) or []):
            from . import surfdelkeep
            if picked in surfdelkeep.surface_bodies(self.doc):

                # that also has a solid body goes to the surface Delete/Keep Body (Body-Delete/Keep<n>)
                self.reject()
                Gui.Selection.clearSelection()
                Gui.Selection.addSelection(self.doc.Name, picked.Name)
                surfdelkeep.start(self.doc)
                return
        if self.kind == "SWStyle::MoveCopy" and self.target in ("TranslateRef", "RotateRef", "Mate") and sub:
            name = sub.split(".")[-1]
            holder = picked
            for part in sub.split(".")[:-1]:
                found = self.doc.getObject(part)
                if found is not None:
                    holder = found
            try:
                element = holder.Shape.getElement(name)
            except Exception:
                element = None
            Gui.Selection.clearSelection()
            if element is None:
                return
            text = "%s@%s" % (name, holder.Label)
            if self.target == "Mate":
                pieces = self._pieces()
                i = self._index_in_base(holder, name, pieces)
                moving = i is not None and i in self.picked_indices(pieces)
                self._mate_pick(element, text, moving)
            else:
                self._ref_pick(self.target, element, text)
            return
        if self.target == "MirrorPlane":
            if picked.TypeId == "App::Plane" or (sub and sub.startswith("Face")):
                self._set("MirrorPlane", (picked, [sub] if sub else [""]))
            Gui.Selection.clearSelection()
            self.target = "Bodies"
            return
        pieces = self._pieces()
        index = None
        if getattr(getattr(picked, "Proxy", None), "Type", None) == ROW_TYPE:
            if picked.Body == self.body.Name:
                index = picked.Index
        elif sub:
            index = self._index_in_base(picked, sub, pieces, pos)
        Gui.Selection.clearSelection()
        if index is None or index >= len(pieces):
            return
        text = ref_text(index, pieces[index])
        if self.target == "MainBody":
            self._set("MainBody", text)
            self.target = "Bodies"
            return
        current = list(obj.Bodies)
        now = [resolve(t, pieces) for t in current]
        if index in now:
            current.pop(now.index(index))   # a second click on a picked body takes it off
        else:
            current.append(text)
        self._set("Bodies", current)

    def picked_indices(self, pieces):
        obj = self.obj()
        return [i for i in (resolve(t, pieces) for t in obj.Bodies) if i is not None]

    def _index_in_base(self, picked, sub, pieces, pos=None):
        try:
            element = picked.Shape.getElement(sub.split(".")[-1])
        except Exception:
            return None
        for i, solid in enumerate(pieces):
            group = solid.Faces if element.ShapeType == "Face" else solid.Edges if element.ShapeType == "Edge" else solid.Vertexes
            if any(element.isSame(g) for g in group):
                return i
        try:
            # a click on this feature's own preview (its faces are copies): the body under the clicked point.
            # A revolved face's centre of mass lies on its axis, so the rim's face went to the hub there and
            # the second click took the hub off again (alloy wheel walk, features-432)
            if pos is not None and len(pos) >= 3:
                at = Part.Vertex(App.Vector(pos[0], pos[1], pos[2]))
                d = [pieces[i].distToShape(at)[0] for i in range(len(pieces))]
                if d and min(d) < 1e-3 + 1e-6 * max(1.0, pieces[0].BoundBox.DiagonalLength):
                    return d.index(min(d))
        except Exception as _fw_err:
            _fw_log("multibody.py:index_at_point", _fw_err)
        try:
            point = element.CenterOfMass if element.ShapeType == "Face" else element.BoundBox.Center
            best = min(range(len(pieces)), key=lambda i: pieces[i].distToShape(Part.Vertex(point))[0])
            return best
        except Exception:
            return None

    # -- Task dialog --
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _done(self):
        if ACTIVE_PANEL and ACTIVE_PANEL[0] is self:
            ACTIVE_PANEL[:] = []
        triad = getattr(self, "triad", None)
        if triad is not None:
            triad.remove()
            self.triad = None
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("multibody.py:2948", _fw_err)
        self._restore_clear()

    def accept(self):
        if self._nothing_picked():
            return False
        if not self._ready():
            return False                 # OK is grey until the bodies are picked (Enter too)
        self._clear_preview()
        self._done()
        self.doc.recompute()
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        try:
            Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("multibody.py:2962", _fw_err)
        later(self.doc)
        return True

    def reject(self):
        self._clear_preview()
        self._done()
        self.doc.abortTransaction()
        Gui.Control.closeDialog()
        try:
            Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("multibody.py:2974", _fw_err)
        self.doc.recompute()
        later(self.doc)
        return True


class _Focus(QtCore.QObject):
    ""

    def __init__(self, panel, target, widget):
        super().__init__(widget)
        self.panel = panel
        self.target = target

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
            self.panel.target = self.target
        return False


# ---- observers ---------------------------------------------------------------------------

class _Observer:
    def slotRecomputedDocument(self, doc):
        for body in bodies(doc):
            if not body.AllowCompound:
                for f in body.Group:
                    _check_compound(f)
        later(doc)

    def slotRecomputedObject(self, obj):
        _check_compound(obj)

    def slotChangedObject(self, obj, prop):
        if prop == "Tip" and obj.TypeId == "PartDesign::Body":
            later(obj.Document)

    def slotDeletedObject(self, obj):
        try:
            if obj.TypeId == "PartDesign::Body" or _solid_feature(obj):
                doc_name = obj.Document.Name        # the name, not the document: it may be closed before the timer runs
                name = obj.Name
                QtCore.QTimer.singleShot(0, lambda: _drop_orphans(doc_name, name))
        except Exception as _fw_err:
            _fw_log("multibody.py:3020", _fw_err)

    def slotFinishRestoreDocument(self, doc):
        later(doc)

    def slotUndoDocument(self, doc):
        later(doc)

    def slotRedoDocument(self, doc):
        later(doc)


_compound_fixing = set()


def _check_compound(obj):
    ""

    try:
        if obj.isValid() or not _solid_feature(obj):
            return
        body = body_of(obj)
        if body is None or body.AllowCompound:
            return
        status = obj.getStatusString() if hasattr(obj, "getStatusString") else ""
    except Exception:
        return
    if "multiple solids" not in status:
        return
    key = (obj.Document.Name, body.Name)
    if key in _compound_fixing:
        return
    _compound_fixing.add(key)

    def again():
        _compound_fixing.discard(key)
        try:
            d = App.getDocument(key[0])
            b = d.getObject(key[1])
        except Exception:
            return
        if b is None or b.AllowCompound:
            return
        b.AllowCompound = True
        for f in b.Group:
            if _solid_feature(f):
                f.touch()
        d.recompute()
    QtCore.QTimer.singleShot(0, again)


def _drop_orphans(doc_name, gone):
    try:
        doc = App.getDocument(doc_name)
    except Exception:
        return
    for obj in list(doc.Objects):
        if getattr(getattr(obj, "Proxy", None), "Type", None) == NOMERGE_TYPE and obj.Source is None:
            body = body_of(obj)
            if body is not None and body.Tip == obj:
                body.Tip = obj.BaseFeature
            if body is not None:
                body.removeObject(obj)
            doc.removeObject(obj.Name)
    later(doc)


class _SelectionWatch:
    ""

    def _changed(self, doc_name):
        now = set()
        try:
            for sel in Gui.Selection.getSelectionEx(doc_name):
                if getattr(getattr(sel.Object, "Proxy", None), "Type", None) == ROW_TYPE:
                    now.add(sel.Object.Name)
        except Exception as _fw_err:
            _fw_log("multibody.py:3097", _fw_err)
        global _selected_rows
        if now != _selected_rows:
            _selected_rows = now
            try:
                draw(App.getDocument(doc_name))
            except Exception as _fw_err:
                _fw_log("multibody.py:3104", _fw_err)

    @staticmethod
    def _is_row(doc, obj):
        try:
            o = App.getDocument(doc).getObject(obj)
        except Exception:
            return True         # can't tell: read the selection as before
        return o is None or getattr(getattr(o, "Proxy", None), "Type", None) == ROW_TYPE

    def addSelection(self, doc, obj, sub, pos):
        # only a folder row changes the rows shown picked (Select All of 300 components read the
        # whole selection 300 times)
        if self._is_row(doc, obj):
            self._changed(doc)

    def removeSelection(self, doc, obj, sub):
        if obj in _selected_rows or self._is_row(doc, obj):
            self._changed(doc)

    def setSelection(self, doc):
        self._changed(doc)

    def clearSelection(self, doc):
        if doc:
            self._changed(doc)
        elif _selected_rows and App.ActiveDocument is not None:
            self._changed(App.ActiveDocument.Name)


class _Redraw(QtCore.QObject):
    """FreeCAD rebuilds a feature's drawing when its look changes (display mode, deviation...);
    hidden bodies are hidden again on the next tick."""

    def __init__(self):
        super().__init__()
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(700)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def tick(self):
        doc = App.ActiveDocument
        if doc is None or not _look.orig:
            return
        try:
            for body in bodies(doc):
                tip = _shown_feature(body)
                if tip is None or tip.ViewObject is None:
                    continue
                for node in _nodes(tip.ViewObject, "SoBrepFaceSet"):
                    saved = _look.orig.get((_addr(node), "coordIndex"))
                    if saved is not None and saved[0] is not None and list(node.coordIndex.getValues()) != saved[0]:
                        _look.orig.pop((_addr(node), "coordIndex"), None)
                        draw(doc)
                        return
        except Exception as _fw_err:
            _fw_log("multibody.py:3161", _fw_err)


# ---- commands ----------------------------------------------------------------------------

class _OpCommand:
    def __init__(self, kind, text, tip, icon):
        self.kind = kind
        self.text = text
        self.tip = tip
        self.icon = icon

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": _icon(self.icon)}

    def IsActive(self):
        doc = App.ActiveDocument
        if doc is not None and self.kind == "DeleteKeep" and not bodies(doc):
            from . import surfdelkeep
            return surfdelkeep.applies(doc)
        return doc is not None      # bodyfirst-1126: no Body in the part opens a page that says what to do (no grey button)

    def Activated(self):
        doc = App.ActiveDocument
        if self.kind == "DeleteKeep" and not bodies(doc):
            from . import surfdelkeep
            if surfdelkeep.applies(doc):
                surfdelkeep.start(doc)
                return
        if doc is not None and not bodies(doc):
            from . import solidfirstlive        # bodyfirst-1126: a part with only Part-workbench solids or nothing
            if solidfirstlive.body_first(self.text):
                return
        start_op(self.kind, doc, [])


COMMANDS = {
    "SWStyle_DeleteKeepBody": ("DeleteKeep", "Delete/Keep Body", "Deletes or keeps solid bodies.", "delete"),
    "SWStyle_MoveCopyBody": ("MoveCopy", "Move/Copy Body", "Moves, rotates or copies solid bodies.", "move"),
    "SWStyle_CombineBodies": ("Combine", "Combine", "Adds, subtracts or intersects solid bodies.", "combine"),
    "SWStyle_MirrorBody": ("MirrorBody", "Mirror Body", "Mirrors solid bodies about a face or plane.", "mirror"),
}

_observer = None
_selection = None
_redraw = None


def install():
    """Idempotent: observers, commands, and the folder for parts already open."""
    global _observer, _selection, _redraw
    if _observer is None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)
        # FreeCAD 1.1 sends no restore signals to Python: restorehook reports opened files instead
        from . import restorehook
        restorehook.on_restored(_observer.slotFinishRestoreDocument)
        from . import cleanfiles
        cleanfiles.install()
    if App.GuiUp:
        for name, (kind, text, tip, icon) in COMMANDS.items():
            try:
                Gui.addCommand(name, _OpCommand(kind, text, tip, icon))
            except Exception as _fw_err:
                _fw_log("multibody.py:3212", _fw_err)
        if _selection is None:
            _selection = _SelectionWatch()
            Gui.Selection.addObserver(_selection)
        if _redraw is None:
            _redraw = _Redraw()
    for doc in App.listDocuments().values():
        later(doc)


# ---- icons -------------------------------------------------------------------------------

_icon_paths = {}
_FAMILIES = {"folder": "ASSEM_SOLID_BODY_FOLDER", "body": "TREE_SOLID_BODY", "combine": "FEATURES_COMBINE",
             "mirror": "FEATURES_MIRROR", "move": "FEATURES_MOVE_COPY_BODY", "delete": "FEATURES_DELETE_BODY"}


def _icon(kind):
    path = _icon_paths.get(kind)
    if path and os.path.exists(path):
        return path
    icon = icons.family(_FAMILIES.get(kind, ""))
    # tree-1119: 64 px, never 16: Windows draws a 16 px file at 16 screen pixels on a 150-200 % screen,
    # half the size of the other rows' icons and with the name shifted left (Look audit row 8)
    pixmap = icon.pixmap(64, 64) if not icon.isNull() else None
    if pixmap is None or pixmap.isNull():
        pixmap = _draw(kind, 64)
    path = os.path.join(tempfile.gettempdir(), "swstyle-bodies-%s.png" % kind)
    pixmap.save(path)
    _icon_paths[kind] = path
    return path


def _cube(painter, x, y, s, top, side, front):
    pen = QtGui.QPen(QtGui.QColor("#3b4a5a"), 1)
    painter.setPen(pen)
    d = s * 0.35
    painter.setBrush(QtGui.QColor(front))
    painter.drawRect(QtCore.QRectF(x, y + d, s, s))
    painter.setBrush(QtGui.QColor(top))
    painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x, y + d), QtCore.QPointF(x + d, y),
                                         QtCore.QPointF(x + s + d, y), QtCore.QPointF(x + s, y + d)]))
    painter.setBrush(QtGui.QColor(side))
    painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x + s, y + d), QtCore.QPointF(x + s + d, y),
                                         QtCore.QPointF(x + s + d, y + s), QtCore.QPointF(x + s, y + s + d)]))


def _draw(kind, side=16):
    pixmap = QtGui.QPixmap(side, side)
    pixmap.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pixmap)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.scale(side / 16.0, side / 16.0)       # drawn on a 16 px grid
    grey = ("#d9dee4", "#9aa6b2", "#c2cad3")
    if kind == "folder":
        p.setPen(QtGui.QPen(QtGui.QColor("#8a6d1f"), 1))
        p.setBrush(QtGui.QColor("#f1cf6b"))
        p.drawRect(QtCore.QRectF(1.5, 4.5, 13, 9))
        _cube(p, 6, 6, 5, *grey)
    elif kind == "body":
        _cube(p, 2.5, 3.5, 8, *grey)
    elif kind == "combine":
        _cube(p, 1.5, 5.5, 7, *grey)
        _cube(p, 5.5, 2.5, 7, "#ffe08a", "#d4a92a", "#f0c54a")
    elif kind == "mirror":
        _cube(p, 1, 5, 5, *grey)
        _cube(p, 9, 5, 5, *grey)
        p.setPen(QtGui.QPen(QtGui.QColor("#1e6fd9"), 1.5))
        p.drawLine(QtCore.QPointF(8, 1), QtCore.QPointF(8, 15))
    elif kind == "move":
        _cube(p, 1.5, 6.5, 6, *grey)
        p.setPen(QtGui.QPen(QtGui.QColor("#1e6fd9"), 1.5))
        p.drawLine(QtCore.QPointF(8, 8), QtCore.QPointF(14, 2))
        p.drawLine(QtCore.QPointF(14, 2), QtCore.QPointF(10, 2))
        p.drawLine(QtCore.QPointF(14, 2), QtCore.QPointF(14, 6))
    elif kind == "delete":
        _cube(p, 2.5, 4.5, 7, *grey)
        p.setPen(QtGui.QPen(QtGui.QColor("#d22"), 2))
        p.drawLine(QtCore.QPointF(9, 9), QtCore.QPointF(15, 15))
        p.drawLine(QtCore.QPointF(15, 9), QtCore.QPointF(9, 15))
    else:
        _cube(p, 1.5, 6.5, 6, *grey)
        _cube(p, 7.5, 2.5, 6, *grey)
    p.end()
    return pixmap
