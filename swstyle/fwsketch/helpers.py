# SPDX-License-Identifier: LGPL-2.1-or-later
""
















import FreeCAD as App
import Part
import Sketcher

try:
    from PySide6 import QtCore
except ImportError:
    from PySide import QtCore

from . import inference as I

TAG = "fw-helper"
HIDDEN_LAYER = 2            # ViewProviderSketch's hidden visual layer
MIDPOINT_GROUP = "FWMidArc_"    # the arc Midpoint relation's constraints: one row in the relations lists


def _log(where, err):
    try:
        App.Console.PrintLog("FreeCAD sketch helper %s: %s\n" % (where, err))
    except Exception:
        pass


def tag_of(g):
    """(kind, relations it needs) of a helper geometry, else None."""
    try:
        if not g.hasExtensionOfName(TAG):
            return None
        value = g.getExtensionOfName(TAG).Value
        kind, _, n = value.partition(":")
        return kind, int(n or 0)
    except Exception:
        return None


def is_helper(g):
    return tag_of(g) is not None


_IDS = {}       # sketch full name: ((geometry count, constraint count), helper ids)


def helper_ids(sketch, geometry=None):
    """The ids of the sketch's helpers (kept per sketch while its counts stay: the relations lists
    ask once per relation, and sk.Geometry copies every entity on each read)."""
    if geometry is not None:
        return {i for i, g in enumerate(geometry) if is_helper(g)}
    try:
        key, counts = sketch.FullName, (sketch.GeometryCount, sketch.ConstraintCount)
    except Exception:
        key, counts = None, None
    hit = _IDS.get(key)
    if hit is not None and hit[0] == counts:
        return hit[1]
    ids = {i for i, g in enumerate(sketch.Geometry) if is_helper(g)}
    if key is not None:
        if len(_IDS) > 64:
            _IDS.clear()
        _IDS[key] = (counts, ids)
    return ids


def _tagged(g, kind, needs):
    e = Part.GeometryStringExtension("%s:%d" % (kind, needs))
    e.Name = TAG
    g.setExtension(e)
    try:
        import SketcherGui
        v = SketcherGui.ViewProviderSketchGeometryExtension()
        v.VisualLayerId = HIDDEN_LAYER
        g.setExtension(v)
    except Exception as err:            # no GUI: tagged, not hidden
        _log("layer", err)
    return g


def add_helper(sketch, g, kind, needs):
    """Add g as a hidden construction helper of kind held by needs relations; returns its id."""
    watch()
    return sketch.addGeometry(_tagged(g, kind, needs), True)


def _hide_relations(sketch, indices):
    try:
        sketch.setVirtualSpace(list(indices), True)
    except Exception as err:
        _log("virtual space", err)


def _clean(sketch):
    try:
        sketch.solve()
        return not list(sketch.RedundantConstraints) and not list(sketch.ConflictingConstraints) \
            and not list(getattr(sketch, "MalformedConstraints", []) or [])
    except Exception:
        return False


# --- arc midpoint ------------------------------------------------------------------------------
def at_arc_midpoint(sketch, geo, pos, arc, tol=1e-7):
    """True when point (geo, pos) sits on the middle of circular arc arc."""
    try:
        a = sketch.Geometry[arc]
        if type(a) is not Part.ArcOfCircle:
            return False
        m = a.value((a.FirstParameter + a.LastParameter) / 2)
        p = sketch.getPoint(geo, pos)
        return (p - m).Length <= tol * (1.0 + a.Radius + a.Center.Length)
    except Exception:
        return False


def lock_arc_midpoint(sketch, geo, pos, arc, on_edge=None):
    """Hold point (geo, pos), already On edge of arc (constraint on_edge, found when None), at the
    arc's middle. Returns the helper id, or None when it would over-define the sketch (left as it was)."""
    C = Sketcher.Constraint
    if on_edge is None:
        on_edge = next((i for i, c in enumerate(sketch.Constraints) if c.Type == "PointOnObject" and c.First == geo
                        and int(c.FirstPos) == pos and c.Second == arc), None)
        if on_edge is None:
            return None
    a = sketch.Geometry[arc]
    p = sketch.getPoint(geo, pos)
    r = (p - sketch.getPoint(arc, I.START)).Length
    if r <= 1e-9:
        return None
    n0, g0 = len(sketch.Constraints), sketch.GeometryCount
    h = add_helper(sketch, Part.Circle(p, App.Vector(0, 0, 1), r), "arcmid", 3)
    sketch.addConstraint([C("Coincident", h, I.MID, geo, pos),
                          C("PointOnObject", arc, I.START, h), C("PointOnObject", arc, I.END, h)])
    if not _clean(sketch):
        sketch.delGeometry(h)       # its relations go with it
        sketch.solve()
        return None
    names = {c.Name for c in sketch.Constraints}
    k = 0
    while any(nm.startswith("%s%d_" % (MIDPOINT_GROUP, k)) for nm in names):
        k += 1
    for j, i in enumerate([on_edge] + list(range(n0, len(sketch.Constraints)))):
        try:
            sketch.renameConstraint(i, "%s%d_%d" % (MIDPOINT_GROUP, k, j))
        except Exception as err:
            _log("name", err)
    _hide_relations(sketch, range(n0, len(sketch.Constraints)))
    return h


def lock_new_arc_midpoints(sketch, suggestions, geo, pos, first_new):
    ""


    if any(s.type in ("Horizontal", "Vertical") and s.pos == I.MID for s in suggestions):
        return
    for i in range(first_new, len(sketch.Constraints)):
        c = sketch.Constraints[i]
        if c.Type == "PointOnObject" and c.First == geo and int(c.FirstPos) == pos and c.Second >= 0 \
                and at_arc_midpoint(sketch, geo, pos, c.Second):
            lock_arc_midpoint(sketch, geo, pos, c.Second, i)
            return


# --- midpoint line ------------------------------------------------------------------------------
MIDLINE_GROUPS = ("FWMidLnC_", "FWMidLnM_")     # one Coincident / Midpoint row in the relations lists


def lock_line_middle(sketch, line, middle, suggestions, add_relations):
    """Midpoint Line whose middle was placed on a curve, a line's midpoint or a quadrant: the centre
    of a hidden circle held at the line's middle (Symmetric about its ends) takes the relations the middle
    snapped to, listed as one Coincident (Midpoint on a line's midpoint) row. Returns the helper id,
    or None when nothing held or the sketch would be over-defined (left as it was)."""
    C = Sketcher.Constraint
    a, b = sketch.getPoint(line, I.START), sketch.getPoint(line, I.END)
    r = (b - a).Length / 2.0
    if r <= 1e-9:
        return None
    n0 = len(sketch.Constraints)
    # a hidden circle through the line's ends, centred on its middle (a sketch Point loses its
    # tag when added): its centre is the line's midpoint
    h = add_helper(sketch, Part.Circle((a + b) * 0.5, App.Vector(0, 0, 1), r), "midline", 3)
    sketch.addConstraint([C("Symmetric", line, I.START, line, I.END, h, I.MID), C("PointOnObject", line, I.START, h)])
    try:
        add_relations(list(suggestions), h)
    except Exception as err:
        _log("midline relations", err)
    if len(sketch.Constraints) - n0 < 3 or not _clean(sketch):
        sketch.delGeometry(h)       # its relations go with it
        sketch.solve()
        return None
    prefix = MIDLINE_GROUPS[1] if any(s.type == "Symmetric" for s in suggestions) else MIDLINE_GROUPS[0]
    names = {c.Name for c in sketch.Constraints}
    k = 0
    while any(nm.startswith("%s%d_" % (prefix, k)) for nm in names):
        k += 1
    for j, i in enumerate(range(n0, len(sketch.Constraints))):
        try:
            sketch.renameConstraint(i, "%s%d_%d" % (prefix, k, j))
        except Exception as err:
            _log("name", err)
    _hide_relations(sketch, range(n0, len(sketch.Constraints)))
    return h


# --- arc slot ----------------------------------------------------------------------------------
def slot_centre_line(sketch, centre, cap):
    """A hidden line from point centre (geo, pos) to cap's centre, held by two Coincidents.
    Returns its id and the relations added (to hide once the centre arc is on it)."""
    C = Sketcher.Constraint
    a, b = sketch.getPoint(*centre), sketch.getPoint(cap, I.MID)
    if (a - b).Length <= 1e-9:
        return None, []
    n0 = len(sketch.Constraints)
    h = add_helper(sketch, Part.LineSegment(a, b), "arcslot", 3)
    sketch.addConstraint([C("Coincident", h, I.START, centre[0], centre[1]), C("Coincident", h, I.END, cap, I.MID)])
    return h, list(range(n0, len(sketch.Constraints)))


def hide_helper_relations(sketch, h):
    _hide_relations(sketch, [i for i, c in enumerate(sketch.Constraints) if h in (c.First, c.Second, c.Third)])


# --- moved, copied, mirrored and patterned with their owner ------------------------------------
def with_helpers(sketch, entities):
    """entities plus the hidden helpers that belong to them (reviewer 11-19): a helper whose relations
    reach only entities (the arc slot's centre line) moves and is copied with them, or Move dropped it
    and loosened the slot, and a copy came without one. A helper that also reaches the rest of the
    sketch (a Midpoint Line's middle on a curve) stays: that relation is to an entity not picked."""
    ents = set(int(g) for g in entities)
    out = list(entities)
    try:
        hs = helper_ids(sketch, sketch.Geometry)
    except Exception:
        return out
    if not hs:
        return out
    cons = sketch.Constraints
    for h in sorted(hs):
        if h in ents:
            continue
        refs = set()
        for c in cons:
            r = [x for x in (c.First, c.Second, c.Third) if x is not None and x > -2000]
            if h in r:
                refs |= {x for x in r if x != h}
        if refs & ents and refs <= ents:
            out.append(h)
    return out


def hide_new(sketch, first_geo):
    """Hides the relations of the helpers from first_geo on (copies), as their originals' are."""
    try:
        for h in sorted(helper_ids(sketch, sketch.Geometry)):
            if h >= first_geo:
                hide_helper_relations(sketch, h)
    except Exception as err:
        _log("hide new", err)


# --- the relations lists -----------------------------------------------------------------------
def refers_to_helper(sketch, c, helpers=None):
    hs = helper_ids(sketch) if helpers is None else helpers
    return bool(hs) and any(g in hs for g in (c.First, c.Second, c.Third) if g is not None and g >= 0)


# --- deleted with their owner ------------------------------------------------------------------
def orphans(sketch):
    """Helpers held by fewer relations than they need (their owner was deleted)."""
    geos = sketch.Geometry
    out = []
    for i, g in enumerate(geos):
        t = tag_of(g)
        if t is None:
            continue
        held = sum(1 for c in sketch.Constraints if i in (c.First, c.Second, c.Third))
        if held < t[1]:
            out.append(i)
    return out


def prune(sketch):
    """Delete orphaned helpers. Outside any undo step: Undo of the delete that orphaned them puts
    back the sketch as it was, helpers included."""
    try:
        gone = orphans(sketch)
        if gone:
            sketch.delGeometries(sorted(gone))
            sketch.solve()
        return gone
    except Exception as err:
        _log("prune", err)
        return []


_COUNTS = {}        # sketch full name: (geometry count, constraint count) last seen
_HAS = {}           # sketch full name: True once it had a helper


class _Watch:
    def slotChangedObject(self, obj, prop):
        if prop not in ("Constraints", "Geometry"):
            return
        try:
            if obj.TypeId != "Sketcher::SketchObject":
                return
            key = obj.FullName
            now = (obj.GeometryCount, obj.ConstraintCount)
        except Exception:
            return
        last = _COUNTS.get(key)
        _COUNTS[key] = now
        if last is None or (now[0] >= last[0] and now[1] >= last[1]):
            return          # nothing deleted
        if not _HAS.get(key):
            try:
                if not helper_ids(obj):
                    return
            except Exception:
                return
            _HAS[key] = True
        QtCore.QTimer.singleShot(0, lambda o=obj: _later(o))

    def slotDeletedDocument(self, doc):
        for k in [k for k in _COUNTS if k.startswith(doc.Name + "#")]:
            _COUNTS.pop(k, None)
            _HAS.pop(k, None)


def _later(obj):
    from .. import teardown
    if teardown.closing() or not teardown.alive(obj):
        return
    try:
        if App.getActiveTransaction():
            QtCore.QTimer.singleShot(50, lambda: _later(obj))       # still inside an undo step
            return
    except Exception:
        pass
    if prune(obj):
        try:
            _COUNTS[obj.FullName] = (obj.GeometryCount, obj.ConstraintCount)
        except Exception:
            pass


_WATCH = []


def watch():
    if not _WATCH:
        _WATCH.append(_Watch())
        App.addDocumentObserver(_WATCH[0])
