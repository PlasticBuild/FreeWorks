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

import json
import math
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets
from . import geomkeep

Qt = QtCore.Qt
PROP = "SWBlocks"
PREFIX = "SWBlock:"
EXT = "fwblock"
SUPPORTED = ("LineSegment", "Circle", "ArcOfCircle", "Point", "Ellipse", "ArcOfEllipse", "BSplineCurve")
COPIED = ("Coincident", "Tangent", "Horizontal", "Vertical", "Parallel", "Perpendicular", "Equal", "PointOnObject")
DIMENSIONS = ("Distance", "Radius", "Diameter", "Angle")     # kept by a block (not the sketch-axis ones)
LENGTHS = ("Distance", "Radius", "Diameter")
UNDEF = -2000
PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Blocks"


# ---------------------------------------------------------------- records
def _type(g):
    return type(g).__name__


def records(sketch):
    """The sketch's blocks: [{"name", "definition", "geos": [stable ids], "base": stable id}]. A
    block held by a frame reads its angle as it is now (relations may have turned it)."""
    try:
        recs = json.loads(getattr(sketch, PROP, "") or "[]")
    except Exception:
        return []
    if recs:
        # a block whose entities were all deleted (Delete of a picked block) is gone: read, not
        # written, so Undo of the delete brings the block back with its entities (reviewer 11-19)
        have = set(_ids(sketch))
        recs = [r for r in recs if r.get("kind") == "belt" or any(g in have for g in r.get("geos", []))]
    if any(r.get("frame") for r in recs):
        ids = None
        for r in recs:
            if r.get("frame"):
                ids = ids if ids is not None else _ids(sketch)
                live = _frame_angle(sketch, r, ids)
                if live is not None:
                    old = float(r.get("angle", 0.0))
                    r["angle"] = old + ((live - old + 180.0) % 360.0 - 180.0)
    return recs


def _frame_angle(sketch, rec, ids=None):
    """The block's angle now (degrees), from its insertion point and its frame point."""
    ids = ids if ids is not None else _ids(sketch)
    fr = rec.get("frame")
    base, g = ids.get(rec.get("base")), ids.get(fr[0]) if fr else None
    if base is None or g is None:
        return None
    try:
        b = sketch.Geometry[base]
        d = sketch.getPoint(g, int(fr[1])) - App.Vector(b.X, b.Y, 0)
    except Exception:
        return None
    if d.Length < 1e-9:
        return None
    return math.degrees(math.atan2(d.y, d.x)) - fr[2]


def _store(sketch, recs):
    if PROP not in sketch.PropertiesList:
        sketch.addProperty("App::PropertyString", PROP, "FreeCAD", "Sketch blocks")
        sketch.setEditorMode(PROP, 2)
    setattr(sketch, PROP, json.dumps(recs))
    try:
        from . import sketchblocktree
        sketchblocktree.changed(sketch)     # the block rows in the feature tree follow
    except Exception as _fw_err:
        _fw_log("blocks.py:125", _fw_err)


def _ids(sketch):
    """{stable id: geometry index} for the sketch's geometry."""
    return {sketch.getGeometryId(i): i for i in range(len(sketch.Geometry))}


def indices(sketch, rec):
    """(entity indices, insertion point index) of a block now; missing ones are left out."""
    ids = _ids(sketch)
    return [ids[g] for g in rec["geos"] if g in ids], ids.get(rec["base"])


def block_of(sketch, index, within=None):
    """The block holding geometry index (an entity or its insertion point), else None: the
    outermost one (a pick picks it), or with within (a block's name) the one right inside that
    block."""
    gid = sketch.getGeometryId(index)
    recs = records(sketch)
    names = {r["name"] for r in recs}
    for rec in recs:
        if gid in rec["geos"] or gid == rec["base"]:
            parent = rec.get("parent")
            if parent not in names:
                parent = None
            if parent == within:
                return rec
    return None


def children(sketch, name, recs=None):
    """The blocks right inside block name."""
    recs = records(sketch) if recs is None else recs
    return [r for r in recs if r.get("parent") == name]


def descendants(sketch, name, recs=None):
    """Every block inside block name, the innermost first (the order they hold in)."""
    recs = records(sketch) if recs is None else recs
    out = []
    for r in children(sketch, name, recs):
        out += descendants(sketch, r["name"], recs) + [r]
    return out


def _depth(rec, recs):
    by = {r["name"]: r for r in recs}
    n, seen = 0, set()
    while rec.get("parent") in by and rec["name"] not in seen:
        seen.add(rec["name"])
        rec = by[rec["parent"]]
        n += 1
    return n


def _members(sketch, rec):
    """Geometry indices of a block's whole: its entities and its insertion point."""
    geos, base = indices(sketch, rec)
    return geos + ([base] if base is not None else [])


def _unparent(sketch, name):
    """The blocks right inside block name go up to its own parent (or the sketch)."""
    recs = records(sketch)
    rec = next((r for r in recs if r["name"] == name), None)
    up = rec.get("parent") if rec else None
    changed = False
    for r in recs:
        if r.get("parent") == name:
            if up:
                r["parent"] = up
            else:
                r.pop("parent", None)
            changed = True
    if changed:
        _store(sketch, recs)


def _find(sketch, name):
    return next((r for r in records(sketch) if r["name"] == name), None)


def _replace(sketch, rec):
    recs = [r for r in records(sketch) if r["name"] != rec["name"]] + [rec]
    _store(sketch, recs)


def _definitions(sketch):
    return sorted({r["definition"] for r in records(sketch)})


def _next_definition(sketch, stem="Block"):
    used = {r["definition"] for r in records(sketch)}
    n = 1
    while "%s%d" % (stem, n) in used:
        n += 1
    return "%s%d" % (stem, n)


def make_belt(sketch, geos, member, transaction=False):
    ""

    import Sketcher
    geos = sorted(set(geos))
    g = sketch.Geometry[member]
    c = getattr(g, "Center", None)
    at = App.Vector(c.x, c.y, 0) if c is not None else None

    def change():
        base = sketch.addGeometry(__import__("Part").Point(App.Vector(at.x, at.y, 0) if at else App.Vector()), True)
        if c is not None:
            sketch.addConstraint(Sketcher.Constraint("Coincident", base, 1, member, 3))
        name_def = _next_definition(sketch, "Belt")
        rec = {"name": _instance_name(sketch, name_def), "definition": name_def, "kind": "belt",
               "geos": [sketch.getGeometryId(i) for i in geos], "base": sketch.getGeometryId(base)}
        _store(sketch, records(sketch) + [rec])
        return rec
    return _undo(sketch, "Belt/Chain", change) if transaction else change()


def _instance_name(sketch, definition):
    used = {r["name"] for r in records(sketch)}
    n = 1
    while "%s-%d" % (definition, n) in used:
        n += 1
    return "%s-%d" % (definition, n)


# ---------------------------------------------------------------- holding a block's shape
def _held(sketch, name):
    return [i for i, c in enumerate(sketch.Constraints) if (c.Name or "").startswith(PREFIX + name + ":")]


def release(sketch, rec, restore=True):
    """Takes away the block's hidden relations: its entities move freely. restore: the block's own
    Horizontal and Vertical come back on its entities (where its angle lets them)."""
    for i in reversed(_held(sketch, rec["name"])):
        sketch.delConstraint(i)
    if restore and rec.get("hv"):
        import Sketcher
        ids, keep = _ids(sketch), []
        angle = float(rec.get("angle", 0.0))
        for h in rec["hv"]:
            t = _hv_at(h[0], angle - h[5])
            f, s = ids.get(h[1]), ids.get(h[3]) if h[3] is not None else None
            if f is None or (h[3] is not None and s is None):
                continue
            if t is None:
                keep.append(h)                   # turned off the axes: stays in the record
                continue
            try:
                sketch.addConstraint(Sketcher.Constraint(t, f) if s is None else
                                     Sketcher.Constraint(t, f, h[2], s, h[4]))
            except Exception as _fw_err:
                _fw_log("blocks.py:280", _fw_err)
        rec["hv"] = keep
        _replace(sketch, rec)


def _hv_at(kind, turn):
    """Horizontal or Vertical of a block turned by turn degrees since: as it reads now (swapped at
    90 and 270), None off the axes."""
    q = turn / 90.0
    if abs(q - round(q)) > 1e-6:
        return None
    if int(round(q)) % 2:
        return "Vertical" if kind == "Horizontal" else "Horizontal"
    return kind


def _stash_hv(sketch, rec, geos, base):
    """The block's own Horizontal and Vertical go into its record: [type, first id, pos, second id
    or None, pos, the block's angle then]; held, the block keeps them in its own frame."""
    inside = set(geos) | {base}
    gid = sketch.getGeometryId
    ids = _ids(sketch)
    out = [h for h in rec.get("hv", []) if h[1] in ids and (h[3] is None or h[3] in ids)]
    angle = float(rec.get("angle", 0.0))
    for i in reversed(range(len(sketch.Constraints))):
        c = sketch.Constraints[i]
        if c.Type not in ("Horizontal", "Vertical") or (c.Name or "").startswith(PREFIX):
            continue
        if c.First not in inside or (c.Second != UNDEF and c.Second not in inside):
            continue
        out.append([c.Type, gid(c.First), int(c.FirstPos), gid(c.Second) if c.Second != UNDEF else None,
                    int(c.SecondPos), angle])
        sketch.delConstraint(i)
    rec["hv"] = out


def _internal(sketch, i, kind):
    """Internal geometry of kind belonging to entity i, in FreeCAD's internal order."""
    found = []
    for c in sketch.Constraints:
        if c.Type != "InternalAlignment" or c.Second != i or not (0 <= c.First < len(sketch.Geometry)):
            continue
        if _type(sketch.Geometry[c.First]) == kind:
            found.append((getattr(c, "InternalAlignmentIndex", 0), c.First))
    return [j for _n, j in sorted(found)]


def _expose(sketch, i, kind):
    found = _internal(sketch, i, kind)
    if not found:
        try:
            sketch.exposeInternalGeometry(i)
        except Exception as _fw_err:
            _fw_log("blocks.py:333", _fw_err)
        found = _internal(sketch, i, kind)
    return found


def _major_axis(sketch, i):
    lines = _expose(sketch, i, "LineSegment")
    if not lines:
        return None
    return max(lines, key=lambda j: (sketch.Geometry[j].EndPoint - sketch.Geometry[j].StartPoint).Length)


def _top(sketch, geos):
    """geos without the internal geometry of their ellipses and splines (axes, poles): a block's
    definition holds the curves, the insert exposes their internal geometry again."""
    inside = set(geos)
    internal = {c.First for c in sketch.Constraints if c.Type == "InternalAlignment" and c.Second in inside}
    return [i for i in geos if i not in internal]


def _internal_geos(sketch, i):
    t = _type(sketch.Geometry[i])
    if t in ("Ellipse", "ArcOfEllipse"):
        return _expose(sketch, i, "LineSegment")   # both axes: the major one turns, the minor one keeps the width
    if t == "BSplineCurve":
        return _expose(sketch, i, "Circle")
    return []


def _points(sketch, i):
    """The points that fix entity i's shape: [(pos, vector)] (1 start, 2 end, 3 centre)."""
    g = sketch.Geometry[i]
    t = _type(g)
    if t == "LineSegment":
        return [(1, g.StartPoint), (2, g.EndPoint)]
    if t == "ArcOfCircle":
        return [(3, g.Center), (1, g.StartPoint), (2, g.EndPoint)]
    if t == "Circle":
        return [(3, g.Center)]
    if t == "Point":
        return [(1, App.Vector(g.X, g.Y, 0))]
    if t == "Ellipse":
        return [(3, g.Center)]               # its major axis line (internal, in the block) fixes the turn
    if t == "ArcOfEllipse":
        return [(3, g.Center), (1, g.StartPoint), (2, g.EndPoint)]
    if t == "BSplineCurve":                  # its poles (internal circles, in the block) fix the shape
        return [] if g.isPeriodic() else [(1, g.StartPoint), (2, g.EndPoint)]
    return []


def hold(sketch, rec):
    """Adds the hidden relations that keep the block's shape around its insertion point. A belt
    block (Belt/Chain) keeps none: its own relations tie it to the pulleys, which it follows."""
    import Sketcher
    from . import dimtools
    if rec.get("kind") == "belt":
        return 0
    geos, base = indices(sketch, rec)
    if base is None:
        return 0
    internal = [j for i in list(geos) for j in _internal_geos(sketch, i)]
    if internal:
        geos = list(dict.fromkeys(geos + internal))
        rec["geos"] = [sketch.getGeometryId(i) for i in geos]
        _replace(sketch, rec)
    b = sketch.Geometry[base]
    origin = App.Vector(b.X, b.Y, 0)
    added = 0

    def keep(constraint):
        nonlocal added
        index = dimtools.attempt(sketch, constraint)
        if index is not None:
            sketch.renameConstraint(index, "%s%s:%d" % (PREFIX, rec["name"], added))
            sketch.setVirtualSpace(index, True)
            added += 1
    pts = [(i, pos, App.Vector(p.x, p.y, 0)) for i in geos for pos, p in _points(sketch, i)]
    far = max(pts, key=lambda q: (q[2] - origin).Length, default=None)
    ab = (far[2] - origin) if far else App.Vector()

    def spread(q):
        d = q[2] - origin
        return abs(ab.x * d.y - ab.y * d.x) / max(ab.Length * d.Length, 1e-12)
    third = max(pts, key=spread, default=None)
    if far is None or ab.Length < 1e-7 or spread(third) < 1e-3:
        # all on one line through the insertion point: no frame, the block slides only
        rec.pop("frame", None)
        for i in geos:
            for pos, p in _points(sketch, i):
                keep(Sketcher.Constraint("DistanceX", base, 1, i, pos, p.x - origin.x))
                keep(Sketcher.Constraint("DistanceY", base, 1, i, pos, p.y - origin.y))
            if _type(sketch.Geometry[i]) == "Circle":
                keep(Sketcher.Constraint("Radius", i, sketch.Geometry[i].Radius))
        _replace(sketch, rec)
        return added
    _stash_hv(sketch, rec, geos, base)
    anchors = [(base, 1, origin), far, third]

    def tie(a, q):
        d = (q[2] - a[2]).Length
        if d < 1e-9:
            keep(Sketcher.Constraint("Coincident", a[0], a[1], q[0], q[1]))
        else:
            keep(Sketcher.Constraint("Distance", a[0], a[1], q[0], q[1], d))
    tie(anchors[0], far)
    tie(anchors[0], third)
    tie(far, third)
    for q in pts:
        if q is far or q is third:
            continue
        same = next((a for a in anchors if (a[2] - q[2]).Length < 1e-9), None)
        if same is not None:
            tie(same, q)
            continue
        pairs = [(anchors[0], far), (anchors[0], third), (far, third)]

        def area(pr):
            u, v = pr[0][2] - q[2], pr[1][2] - q[2]
            return abs(u.x * v.y - u.y * v.x) / max(u.Length * v.Length, 1e-12)
        x, y = max(pairs, key=area)
        tie(x, q)
        tie(y, q)
    for i in geos:
        if _type(sketch.Geometry[i]) == "Circle":
            keep(Sketcher.Constraint("Radius", i, sketch.Geometry[i].Radius))
    rec["frame"] = [sketch.getGeometryId(far[0]), far[1],
                    math.degrees(math.atan2(ab.y, ab.x)) - float(rec.get("angle", 0.0))]
    _replace(sketch, rec)
    return added


def _undo(sketch, label, change):
    doc = sketch.Document
    doc.openTransaction(label)
    try:
        result = change()
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()
    sketch.solve()
    doc.recompute()
    return result


# ---------------------------------------------------------------- the commands' work
def unsupported(sketch, geos):
    return [i for i in geos if _type(sketch.Geometry[i]) not in SUPPORTED]


def make(sketch, geos, at=None, definition=None, transaction=True, base=None):
    """Make Block: entities geos become one block, its insertion point at at (sketch
    coordinates; the middle of the entities when None), or the point base (a geometry index) when
    given. Whole blocks among geos go inside the new one (nested blocks). Returns the block's
    record."""
    import Part
    geos = sorted(set(geos) - {base})
    if not geos:
        raise ValueError("Select the sketch entities for the block.")
    bad = unsupported(sketch, geos)
    if bad:
        raise ValueError("Blocks hold lines, arcs, circles, ellipses, splines and points only.")
    inner = []
    for i in geos:
        r = block_of(sketch, i)
        if r is not None and all(x["name"] != r["name"] for x in inner):
            inner.append(r)
    if any(r.get("kind") == "belt" for r in inner):
        raise ValueError("A belt cannot go inside a block.")
    if base is not None and block_of(sketch, base) is not None:
        raise ValueError("The insertion point is in a block already.")
    for r in inner:
        geos = sorted(set(geos) | set(_members(sketch, r)))
    shapes = [i for i in geos if not any(i == indices(sketch, r)[1] for r in inner)]

    def change():
        nonlocal at
        if base is not None:
            p = sketch.Geometry[base]
            at, point = App.Vector(p.X, p.Y, 0), base
        else:
            if at is None:
                box = Part.Compound([sketch.Geometry[i].toShape() for i in shapes]).BoundBox
                at = App.Vector(box.Center.x, box.Center.y, 0)
            point = sketch.addGeometry(Part.Point(App.Vector(at.x, at.y, 0)), True)
        name_def = definition or _next_definition(sketch)
        rec = {"name": _instance_name(sketch, name_def), "definition": name_def,
               "geos": [sketch.getGeometryId(i) for i in geos], "base": sketch.getGeometryId(point)}
        recs = records(sketch)
        for r in recs:
            if any(r["name"] == x["name"] for x in inner):
                r["parent"] = rec["name"]
        _store(sketch, recs + [rec])
        hold(sketch, rec)
        return rec
    return _undo(sketch, "Make Block", change) if transaction else change()


def explode(sketch, name):
    """Explode Block: the block's entities stay as plain entities."""
    rec = _find(sketch, name)
    if rec is None:
        return False

    def change():
        release(sketch, rec)
        _unparent(sketch, name)
        _geos, base = indices(sketch, rec)
        if base is not None:
            sketch.delGeometries([base])
        _store(sketch, [r for r in records(sketch) if r["name"] != name])
        return True
    return _undo(sketch, "Explode Block", change)


def rebuild(sketch):
    """Rebuild: every block holds its shape again as it is now (drops what was deleted)."""
    def change():
        for rec in [r for r in records(sketch) if r.get("file")]:
            try:
                relink(sketch, rec["name"])
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: block %s: its file: %s\n" % (rec["name"], error))
        recs = []
        for rec in records(sketch):
            ids = _ids(sketch)
            rec["geos"] = [g for g in rec["geos"] if g in ids]
            if rec["base"] not in ids or not rec["geos"]:
                release(sketch, rec)
                if rec["base"] in ids:
                    sketch.delGeometries([ids[rec["base"]]])
                continue
            release(sketch, rec, restore=False)
            recs.append(rec)
        names = {r["name"] for r in recs}
        for rec in recs:
            if rec.get("parent") not in names:
                rec.pop("parent", None)
        _store(sketch, recs)
        for rec in sorted(recs, key=lambda r: -_depth(r, recs)):   # inner blocks hold first
            hold(sketch, _find(sketch, rec["name"]))
        return len(recs)
    return _undo(sketch, "Rebuild Blocks", change)


def transform(sketch, name, at=None, angle=None, scale=None):
    """The Block PropertyManager's Parameters: puts the block's insertion point at at, turns it to
    angle (degrees) and scales it to scale, about the insertion point (from the angle and scale it
    has now). Returns the record."""
    rec = _find(sketch, name)
    if rec is None:
        return None
    old_a, old_s = rec.get("angle", 0.0), rec.get("scale", 1.0)
    turn = (angle - old_a) if angle is not None else 0.0
    k = (scale / old_s) if scale is not None and old_s > 1e-12 else 1.0
    geos, base = indices(sketch, rec)
    if base is None:
        return rec
    inner = descendants(sketch, name) if abs(k - 1.0) > 1e-12 else []
    for r in inner:
        release(sketch, r, restore=False)
    release(sketch, rec, restore=False)
    rec = _find(sketch, name)
    gs = geomkeep.read(sketch)
    b = gs[base]
    centre = App.Vector(b.X, b.Y, 0)
    if at is not None:
        shift = App.Vector(at.x, at.y, 0) - centre
    else:
        shift = App.Vector(0, 0, 0)
    if abs(turn) > 1e-12 or abs(k - 1.0) > 1e-12 or shift.Length > 1e-12:
        if abs(turn) > 1e-12 and abs(turn / 90.0 - round(turn / 90.0)) > 1e-9:
            # off the axes: the block's own Horizontal and Vertical cannot hold
            inside = set(geos)
            for i in reversed(range(len(sketch.Constraints))):
                c = sketch.Constraints[i]
                if c.Type in ("Horizontal", "Vertical") and c.First in inside and c.Second == UNDEF:
                    sketch.delConstraint(i)
            gs = geomkeep.read(sketch)
        turn_pl = App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), turn), centre)
        # the block's own horizontal and vertical dimensions turn with it (a quarter turn swaps
        # them, another angle makes them aligned), as Rotate Entities does: kept as they were, they
        # pulled the turned block out of shape (reviewer 11-19)
        turned, own = [], []
        if abs(turn) > 1e-12:
            from . import sketchmove
            inside = set(geos) | {base}
            own = [i for i, c in enumerate(sketch.Constraints) if c.Type in ("DistanceX", "DistanceY", "Angle")
                   and not (c.Name or "").startswith(PREFIX)
                   and [x for x in (c.First, c.Second, c.Third) if x is not None and x > -2000]
                   and all(x in inside for x in (c.First, c.Second, c.Third) if x is not None and x > -2000)]
            items = [(sketch.Constraints[i], sketch.Constraints[i].Driving, sketch.Constraints[i].Name) for i in own]
        for i in geos + [base]:
            g = gs[i]
            if abs(k - 1.0) > 1e-12:
                g.scale(centre, k)
            if abs(turn) > 1e-12:
                g.transform(turn_pl.toMatrix())    # Geometry.rotate(Placement) ignores its centre
            if shift.Length > 1e-12:
                g.translate(shift)
        if own:
            turned = sketchmove._turned_relations(items, turn_pl, lambda g, pos: sketchmove._geo_point(gs[g], pos))
            for i in reversed(own):
                sketch.delConstraint(i)
        assign_geometry(sketch, gs)
        if turned:
            sketchmove._add_relations(sketch, turned)
        rec = _find(sketch, name)
    rec["angle"] = angle if angle is not None else old_a
    rec["scale"] = scale if scale is not None else old_s
    _replace(sketch, rec)
    for r in inner:                          # innermost first, at their new size
        r = _find(sketch, r["name"])
        r["scale"] = float(r.get("scale", 1.0)) * k
        _replace(sketch, r)
        hold(sketch, r)
    rec = _find(sketch, name)
    hold(sketch, rec)
    sketch.solve()
    return rec


def assign_geometry(sketch, gs):
    """sketch.Geometry = gs, keeping every block's record: FreeCAD gives the geometry new stable
    ids when the whole list is set."""
    before = {i: sketch.getGeometryId(i) for i in range(len(sketch.Geometry))}
    sketch.Geometry = gs
    # in an open sketch, after relations were deleted (release), the next solve put the old
    # geometry back: the Block page's X, Y and Angle did nothing (reviewer 11-19). A recompute
    # makes the solver take the new geometry
    try:
        sketch.recompute()
    except Exception as _fw_err:
        _fw_log("blocks.py:assign recompute", _fw_err)
    new = {before[i]: sketch.getGeometryId(i) for i in range(min(len(gs), len(before)))}
    # fix269: records() leaves out a block none of whose ids are in the sketch, and every id is
    # new here: read the stored list as it is, or every block lost its record (Edit Block OK with
    # two instances: TypeError in _reshape, the copies stopped being blocks)
    try:
        recs = json.loads(getattr(sketch, PROP, "") or "[]")
    except Exception:
        recs = []
    for rec in recs:
        rec["geos"] = [new.get(g, g) for g in rec["geos"]]
        rec["base"] = new.get(rec["base"], rec["base"])
    if recs:
        _store(sketch, recs)


def relink(sketch, name):
    """A block linked to a file takes the file's entities again (Link to file). Returns the new
    record (same name), or None when the block has no link or the file cannot be read."""
    rec = _find(sketch, name)
    path = (rec or {}).get("file")
    if not path or not os.path.isfile(path):
        return None
    data = load(path)
    geos, base = indices(sketch, rec)
    if base is None:
        return None
    b = sketch.Geometry[base]
    at = App.Vector(b.X, b.Y, 0)
    release(sketch, rec, restore=False)
    sketch.delGeometries(sorted(set(geos + [base])))
    gone = {name} | {r["name"] for r in descendants(sketch, name)}
    _store(sketch, [r for r in records(sketch) if r["name"] not in gone])
    new = insert(sketch, data, at, rec.get("angle", 0.0), rec.get("scale", 1.0),
                 definition=rec["definition"], transaction=False)
    for r in children(sketch, new["name"]):
        r["parent"] = name
        _replace(sketch, r)
    new = next((r for r in records(sketch) if r["base"] == new["base"]), new)
    new["name"] = name
    new["file"] = path
    recs = [r for r in records(sketch) if r["name"] != new["name"] and r is not new]
    recs = [r for r in recs if r.get("base") != new["base"]] + [new]
    _store(sketch, recs)
    return new


def set_link(sketch, name, path):
    """Link to file on (path) or off (None)."""
    rec = _find(sketch, name)
    if rec is None:
        return None
    if path:
        rec["file"] = path
    else:
        rec.pop("file", None)
    _replace(sketch, rec)
    return rec


def set_entities(sketch, name, geos):
    """Add/Remove Entities: the block holds geos (indices) from now on."""
    rec = _find(sketch, name)
    geos = set(geos)
    recs = records(sketch)
    names = {r["name"] for r in recs}
    for r in recs:
        if r["name"] == name or r.get("kind") == "belt":
            continue
        inside = r.get("parent") == name
        if not inside and r.get("parent") in names:
            continue                         # inside another block
        whole = set(_members(sketch, r))
        if whole & geos:
            geos |= whole                    # a block goes in or out whole
            r["parent"] = name
        elif inside:
            r.pop("parent", None)            # taken out: a block of the sketch again
    _store(sketch, recs)
    rec = _find(sketch, name)
    rec["geos"] = [sketch.getGeometryId(i) for i in sorted(geos)]
    _replace(sketch, rec)
    return rec


# ---------------------------------------------------------------- saving and inserting
def _serial(sketch, geos, base, angle=0.0, scale=1.0):
    """The block's entities relative to its insertion point and the relations between them; angle
    and scale (the block's own) are taken off, so the definition is the block as made."""
    b = sketch.Geometry[base]
    ox, oy = b.X, b.Y
    a = math.radians(angle)
    ca, sa = math.cos(-a), math.sin(-a)
    k = 1.0 / scale if scale > 1e-12 else 1.0

    def at(x, y):
        x, y = x - ox, y - oy
        return (x * ca - y * sa) * k, (x * sa + y * ca) * k
    geos = _top(sketch, geos)
    local = {g: n for n, g in enumerate(geos)}
    out = []
    for i in geos:
        g = sketch.Geometry[i]
        t = _type(g)
        c = bool(sketch.getConstruction(i))
        if t == "LineSegment":
            out.append(["Line"] + list(at(g.StartPoint.x, g.StartPoint.y)) + list(at(g.EndPoint.x, g.EndPoint.y)) + [c])
        elif t == "Circle":
            out.append(["Circle"] + list(at(g.Center.x, g.Center.y)) + [g.Radius * k, c])
        elif t == "ArcOfCircle":
            out.append(["Arc"] + list(at(g.Center.x, g.Center.y)) + [g.Radius * k, g.FirstParameter - a,
                                                                       g.LastParameter - a, c])
        elif t in ("Ellipse", "ArcOfEllipse"):
            major = g.Center + g.XAxis * g.MajorRadius
            values = list(at(g.Center.x, g.Center.y)) + list(at(major.x, major.y)) + [g.MinorRadius * k]
            if t == "Ellipse":
                out.append(["Ellipse"] + values + [c])
            else:
                # parameters are measured from the ellipse's own major axis, which turns with it
                out.append(["EArc"] + values + [g.FirstParameter, g.LastParameter, c])
        elif t == "BSplineCurve":
            poles = [list(at(p.x, p.y)) for p in g.getPoles()]
            out.append(["Spline", poles, int(g.Degree), bool(g.isPeriodic()), list(g.getWeights()), c,
                        list(g.getKnots()), list(g.getMultiplicities())])
        elif t == "Point":
            out.append(["Point"] + list(at(g.X, g.Y)) + [c])
    rels = []
    for c in sketch.Constraints:
        if c.Type not in COPIED + DIMENSIONS or (c.Name or "").startswith(PREFIX):
            continue
        if c.First not in local or (c.Second != UNDEF and c.Second not in local):
            continue
        if c.Type == "Angle" and c.Second == UNDEF:
            continue                         # a line's angle to the sketch's axis is not the block's
        row = [c.Type, local[c.First], c.FirstPos, local.get(c.Second, UNDEF), c.SecondPos]
        if c.Type in DIMENSIONS:
            v = c.Value
            row.append(v * k if c.Type in LENGTHS else v)
        rels.append(row)
    # the block's own Horizontal and Vertical (and those of the blocks inside it), held in their
    # records: as they read unturned
    gid = sketch.getGeometryId(base)
    recs = records(sketch)
    rec = next((r for r in recs if r["base"] == gid), None)
    inner = descendants(sketch, rec["name"], recs) if rec else []
    ids = _ids(sketch)
    for r in ([rec] if rec else []) + inner:
        own = float(r.get("angle", 0.0)) - angle if r is not rec else 0.0
        for h in r.get("hv", []):
            t = _hv_at(h[0], own - h[5])
            f, s2 = ids.get(h[1]), ids.get(h[3]) if h[3] is not None else None
            if t is None or f not in local or (h[3] is not None and s2 not in local):
                continue
            rels.append([t, local[f], h[2], local[s2] if s2 is not None else UNDEF, h[4]])
    nested = []
    for r in inner:                          # innermost first, as Insert Block makes them
        g, b = indices(sketch, r)
        if b not in local or any(i not in local for i in g):
            continue
        nested.append({"definition": r["definition"], "geos": [local[i] for i in g], "base": local[b],
                       "angle": float(r.get("angle", 0.0)) - angle, "scale": float(r.get("scale", 1.0)) * k})
    data = {"entities": out, "relations": rels}
    if nested:
        data["blocks"] = nested
    return data


def definition_data(sketch, definition):
    """A definition's entities and relations, from its first block in the sketch."""
    rec = next((r for r in records(sketch) if r["definition"] == definition), None)
    if rec is None:
        return None
    geos, base = indices(sketch, rec)
    data = _serial(sketch, geos, base, rec.get("angle", 0.0), rec.get("scale", 1.0))
    data["name"] = definition
    return data


def save(sketch, name, path):
    """Save Block: writes the block as a .fwblock file (JSON)."""
    rec = _find(sketch, name)
    geos, base = indices(sketch, rec)
    data = _serial(sketch, geos, base, rec.get("angle", 0.0), rec.get("scale", 1.0))
    data["name"] = rec["definition"]
    data["format"] = "FreeWorks block 1"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    return path


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "entities" not in data:
        raise ValueError("Not a block file")
    data.setdefault("name", os.path.splitext(os.path.basename(path))[0])
    return data


def insert(sketch, data, at, angle=0.0, scale=1.0, definition=None, transaction=True):
    """Insert Block: places data's entities with their insertion point at at (sketch
    coordinates), turned by angle (degrees) and scaled. Returns the new block's record."""

    def change():
        new = [sketch.addGeometry(geo, bool(c)) for geo, c in _entities(data, at, angle, scale)]
        skipped = _relations(sketch, data, new, angle, scale)
        for spec in data.get("blocks", []):          # nested blocks, innermost first
            try:
                inner = make(sketch, [new[j] for j in spec["geos"]], base=new[spec["base"]],
                             definition=spec.get("definition"), transaction=False)
                _placed(sketch, inner, float(spec.get("angle", 0.0)) + angle,
                        float(spec.get("scale", 1.0)) * scale, new, [])
            except (ValueError, IndexError, KeyError) as error:
                App.Console.PrintWarning("FreeCAD: a block inside %s: %s\n" % (data.get("name"), error))
        rec = make(sketch, new, at=App.Vector(at.x, at.y, 0), definition=definition or data.get("name"),
                   transaction=False)
        _placed(sketch, rec, angle, scale, new, skipped)
        return rec
    return _undo(sketch, "Insert Block", change) if transaction else change()


def _placed(sketch, rec, angle, scale, new, skipped):
    """A block just held at angle: its record says so (frame, own Horizontal and Vertical)."""
    rec["angle"], rec["scale"] = float(angle), float(scale)
    if rec.get("frame"):
        rec["frame"][2] -= float(angle)
    gid = sketch.getGeometryId
    for h in rec.get("hv", []):
        h[5] = float(angle)                 # added as they read at the block's angle
    for t, f, fp, s, sp in skipped:         # off the axes: as they read unturned
        rec.setdefault("hv", []).append([t, gid(new[f]), int(fp), gid(new[s]) if s != UNDEF else None, int(sp), 0.0])
    _replace(sketch, rec)


def _entities(data, at, angle=0.0, scale=1.0):
    """[(geometry, construction)] of a block's data placed at at, turned by angle and scaled."""
    import Part
    a = math.radians(angle)
    ca, sa = math.cos(a), math.sin(a)

    def place(x, y):
        return App.Vector(at.x + scale * (x * ca - y * sa), at.y + scale * (x * sa + y * ca), 0)

    def ellipse(e):
        centre = place(e[1], e[2])
        major = place(e[3], e[4])
        direction = major - centre
        if direction.Length < 1e-12:
            direction = App.Vector(1, 0, 0)
        else:
            direction.normalize()
        minor = centre + App.Vector(-direction.y, direction.x, 0) * (e[5] * scale)
        return Part.Ellipse(major, minor, centre)

    out = []
    for e in data["entities"]:
        kind = e[0]
        if kind == "Line":
            out.append((Part.LineSegment(place(e[1], e[2]), place(e[3], e[4])), e[5]))
        elif kind == "Circle":
            out.append((Part.Circle(place(e[1], e[2]), App.Vector(0, 0, 1), e[3] * scale), e[4]))
        elif kind == "Arc":
            out.append((Part.ArcOfCircle(Part.Circle(place(e[1], e[2]), App.Vector(0, 0, 1), e[3] * scale),
                                         e[4] + a, e[5] + a), e[6]))
        elif kind == "Ellipse":
            out.append((ellipse(e), e[6]))
        elif kind == "EArc":
            out.append((Part.ArcOfEllipse(ellipse(e), e[6], e[7]), e[8]))
        elif kind == "Spline":
            poles = [place(x, y) for x, y in e[1]]
            if len(e) > 7:                   # knots and multiplicities kept: the same curve back
                curve = Part.BSplineCurve(poles, e[7], e[6], bool(e[3]), int(e[2]), e[4])
            else:
                curve = Part.BSplineCurve()
                curve.buildFromPoles(poles, bool(e[3]), int(e[2]))
                for n, weight in enumerate(e[4], 1):
                    curve.setWeight(n, weight)
            out.append((curve, e[5]))
        elif kind == "Point":
            out.append((Part.Point(place(e[1], e[2])), e[3]))
    return out


def _relations(sketch, data, new, angle=0.0, scale=1.0):
    """Adds data's relations and dimensions between the entities new (sketch indices, in data's
    order). Returns the Horizontal and Vertical rows left out (the block turned off the axes)."""
    import Sketcher
    turn = round(angle / 90.0) if abs(angle / 90.0 - round(angle / 90.0)) < 1e-9 else None
    skipped = []
    for row in data.get("relations", []):
        t, f, fp, s, sp = row[:5]
        value = row[5] if len(row) > 5 else None
        if f >= len(new) or (s != UNDEF and s >= len(new)):
            continue
        if t in ("Horizontal", "Vertical"):
            if turn is None:
                skipped.append([t, f, fp, s, sp])
                continue
            if turn % 2:
                t = "Vertical" if t == "Horizontal" else "Horizontal"
        try:
            if t in DIMENSIONS:
                if value is None:
                    continue
                if t in LENGTHS:
                    value *= scale
                if s == UNDEF:
                    con = Sketcher.Constraint(t, new[f], value)
                elif t == "Distance" and int(sp) == 0:
                    con = Sketcher.Constraint(t, new[f], fp, new[s], value)
                elif int(fp) == 0 and int(sp) == 0:
                    con = Sketcher.Constraint(t, new[f], new[s], value)
                else:
                    con = Sketcher.Constraint(t, new[f], fp, new[s], sp, value)
            elif t in ("Horizontal", "Vertical") and s == UNDEF:
                con = Sketcher.Constraint(t, new[f])
            elif t in ("Parallel", "Perpendicular", "Equal") or (t == "Tangent" and fp == 0 and sp == 0):
                con = Sketcher.Constraint(t, new[f], new[s])
            elif t == "PointOnObject":
                con = Sketcher.Constraint(t, new[f], fp, new[s])
            else:
                con = Sketcher.Constraint(t, new[f], fp, new[s], sp)
            sketch.addConstraint(con)
        except Exception as _fw_err:
            _fw_log("blocks.py:959", _fw_err)
    return skipped


def sync_definition(sketch, name):
    ""


    rec = _find(sketch, name)
    if rec is None or rec.get("kind") == "belt":
        return []
    others = [r for r in records(sketch) if r["definition"] == rec["definition"] and r["name"] != name
              and r.get("kind") != "belt"]
    if not others:
        return []
    geos, base = indices(sketch, rec)
    if base is None or not geos:
        return []
    data = _serial(sketch, geos, base, rec.get("angle", 0.0), rec.get("scale", 1.0))
    data["name"] = rec["definition"]
    return [o["name"] for o in others if _reshape(sketch, o["name"], data)]


_KINDS = {"Line": "LineSegment", "Circle": "Circle", "Arc": "ArcOfCircle", "Point": "Point",
          "Ellipse": "Ellipse", "EArc": "ArcOfEllipse", "Spline": "BSplineCurve"}


def _reshape(sketch, name, data):
    """The block takes data's shape about its own insertion point, angle and scale. The same
    entities change in place, so relations to the rest of the sketch stay; a block whose entities
    differ in number or kind is put in again."""
    rec = _find(sketch, name)
    geos, base = indices(sketch, rec)
    if base is None:
        return False
    b = sketch.Geometry[base]
    at = App.Vector(b.X, b.Y, 0)
    angle, scale = float(rec.get("angle", 0.0)), float(rec.get("scale", 1.0))
    placed = _entities(data, at, angle, scale)
    all_geos, geos = geos, _top(sketch, geos)
    same = len(placed) == len(geos) and all(_type(sketch.Geometry[i]) == _type(g) for i, (g, _c) in zip(geos, placed))
    inner = descendants(sketch, name)
    for r in inner:
        release(sketch, r, restore=False)
    release(sketch, rec, restore=False)
    if not same:
        link = rec.get("file")
        sketch.delGeometries(sorted(set(all_geos + [base])))
        gone = {name} | {r["name"] for r in inner}
        _store(sketch, [r for r in records(sketch) if r["name"] not in gone])
        new = insert(sketch, data, at, angle, scale, definition=rec["definition"], transaction=False)
        recs = [r for r in records(sketch) if r["name"] != new["name"]]
        for r in recs:
            if r.get("parent") == new["name"]:
                r["parent"] = name
        new["name"] = name
        if link:
            new["file"] = link
        _store(sketch, recs + [new])
        return True
    inside = set(all_geos)
    for i in reversed(range(len(sketch.Constraints))):
        c = sketch.Constraints[i]
        if c.Type not in COPIED + DIMENSIONS or (c.Name or "").startswith(PREFIX):
            continue
        if c.First in inside and (c.Second == UNDEF or c.Second in inside):
            sketch.delConstraint(i)          # the instance's own: the definition's come instead
    gs = geomkeep.read(sketch)
    for i, (g, c) in zip(geos, placed):
        gs[i] = g
    flags = {i: bool(c) for i, (g, c) in zip(geos, placed)}
    assign_geometry(sketch, gs)              # new stable ids: the records follow
    for i, c in flags.items():
        if bool(sketch.getConstruction(i)) != c:
            sketch.setConstruction(i, c)
    rec = _find(sketch, name)
    rec["hv"] = []
    _replace(sketch, rec)
    for r in inner:
        r = _find(sketch, r["name"])
        r["hv"] = []                         # the definition's Horizontal and Vertical come again
        _replace(sketch, r)
    skipped = _relations(sketch, data, geos, angle, scale)
    sketch.solve()
    for r in inner:                          # the blocks inside hold first, innermost first
        hold(sketch, _find(sketch, r["name"]))
    rec = _find(sketch, name)
    hold(sketch, rec)
    rec = _find(sketch, name)
    _placed(sketch, rec, angle, scale, geos, skipped)
    return True


# ---------------------------------------------------------------- PropertyManager pages
def _sketch():
    from . import contextbar
    return contextbar.sketch_in_edit()


def _picked_indices(sketch):
    """Geometry indices picked in the sketch being edited."""
    from . import relationspm
    out = []
    for sub in relationspm.picked_subs(sketch):
        if sub.startswith("Edge"):
            out.append(int(sub[4:]) - 1)
        elif sub.startswith("Vertex"):
            try:
                geo, _pos = sketch.getGeoVertexIndex(int(sub[6:]) - 1)
                if geo >= 0:
                    out.append(geo)
            except Exception as _fw_err:
                _fw_log("blocks.py:1071", _fw_err)
    return out


def picked_block(sketch):
    """The block of the picked entities, or the sketch's only block."""
    for i in _picked_indices(sketch):
        rec = block_of(sketch, i)
        if rec is not None:
            return rec
    recs = records(sketch)
    return recs[0] if len(recs) == 1 else None


def _status(text):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 5000)
    except Exception as _fw_err:
        _fw_log("blocks.py:1089", _fw_err)
    App.Console.PrintMessage("FreeCAD: %s\n" % text)


def _page_base():
    from . import sketchtoolpm
    return sketchtoolpm.ToolPage


class _EntityList:
    """A Block Entities box: picks in the sketch add an entity or take it out again."""

    def _build_list(self, title, geos):
        from . import sketchtoolpm
        g = self.group(title)
        self.list = QtWidgets.QListWidget(g.body)
        self.list.setObjectName("SWBlockEntities")
        self.list.setProperty("swpickbox", True)
        self.list.setFixedHeight(100)
        g.content.addWidget(self.list)
        self.geos = list(dict.fromkeys(geos))
        self._fill()
        self.observer = sketchtoolpm.PickObserver(self)
        Gui.Selection.addObserver(self.observer)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("blocks.py:1115", _fw_err)

    def _fill(self):
        from . import relationspm
        names = relationspm._entity_names(self.sketch.Geometry)
        self.list.clear()
        for i in self.geos:
            if 0 <= i < len(names):
                self.list.addItem(names[i])

    def picked(self, sub):
        from . import sketchtoolpm
        item = sketchtoolpm.item_of(self.sketch, sub)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("blocks.py:1131", _fw_err)
        if item is None or item.geo < 0 or not self.allowed(item.geo):
            return
        group = self.whole(item.geo)
        if item.geo in self.geos:
            self.geos = [g for g in self.geos if g not in group]
        else:
            self.geos += [g for g in group if g not in self.geos]
        self._fill()
        self.changed()

    def allowed(self, geo):
        return True

    def whole(self, geo):
        """What a pick of geo adds or takes out: a block goes in or out whole (nested blocks)."""
        return [geo]

    def changed(self):
        pass

    def selection_changed(self):
        pass

    def _drop_observer(self):
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("blocks.py:1159", _fw_err)
        self.observer.page = None


def _make_page_class():
    Base = _page_base()

    class MakeBlockPage(_EntityList, Base):
        TITLE = "Make Block"
        ICON = "BLOCK_MAKE"
        PIXMAP = "Sketcher_CreateRegularPolygon"

        def build(self):
            self.setProperty("swstyle_pm_title", self.TITLE)

            picked = []
            for i in _picked_indices(self.sketch):
                if self._nestable(i):
                    picked += [g for g in self.whole(i) if g not in picked]
            self._build_list("Block Entities", picked)
            g = self.group("Insertion Point")
            # one box a row (fix231): side by side the two boxes made the page wider than the pane
            # and cut the message and the Y box off
            row = QtWidgets.QFormLayout()
            self.x = QtWidgets.QDoubleSpinBox(g.body)
            self.y = QtWidgets.QDoubleSpinBox(g.body)
            for box, name in ((self.x, "X"), (self.y, "Y")):
                box.setObjectName("SWBlockInsertion" + name)
                box.setRange(-1e9, 1e9)
                box.setDecimals(3)
                box.setSuffix(" mm")
                row.addRow("%s:" % name, box)
            g.content.addLayout(row)
            g.body.setHidden(True)
            g._update_fold()
            self.moved = False
            self.x.valueChanged.connect(self._typed)
            self.y.valueChanged.connect(self._typed)
            self.changed()

        def allowed(self, geo):
            ok = self._nestable(geo)
            if not ok:
                self.show_note("Blocks hold lines, arcs, circles, ellipses, splines, points and other blocks.", True)
            return ok

        def _nestable(self, geo):
            r = block_of(self.sketch, geo)
            if r is not None:
                return r.get("kind") != "belt"     # a whole block goes inside (nested blocks)
            return _type(self.sketch.Geometry[geo]) in SUPPORTED

        def whole(self, geo):
            r = block_of(self.sketch, geo)
            return _members(self.sketch, r) if r is not None else [geo]

        def _typed(self, *args):
            if not getattr(self, "_setting", False):
                self.moved = True

        def changed(self):
            """The insertion point follows the middle of the entities until it is typed."""
            self.show_note("")
            if self.moved or not self.geos:
                return
            import Part
            box = Part.Compound([self.sketch.Geometry[i].toShape() for i in self.geos]).BoundBox
            self._setting = True
            self.x.setValue(box.Center.x)
            self.y.setValue(box.Center.y)
            self._setting = False

        def accept(self):
            try:
                rec = make(self.sketch, self.geos, App.Vector(self.x.value(), self.y.value(), 0))
            except ValueError as error:
                self.show_note(str(error), True)
                return
            _status("%s made" % rec["name"])
            Base.accept(self)

        def closing(self):
            self._drop_observer()

    return MakeBlockPage


def _edit_page_class():
    Base = _page_base()

    class EditBlockPage(_EntityList, Base):
        """Edit Block and Add/Remove Entities: the block lets go while the page is open; picks add
        entities or take them out; the check holds the block again as it now is."""
        TITLE = "Edit Block"
        ICON = "BLOCK_EDIT"
        PIXMAP = "Sketcher_EditSketch"

        def __init__(self, sketch, rec, title=None, parent=None):
            self.rec = rec
            if title:
                self.TITLE = title
            super().__init__(sketch, parent)

        def build(self):
            self.setProperty("swstyle_pm_title", self.TITLE)
            g = self.group("Message")
            label = QtWidgets.QLabel("%s: drag or change its entities, and pick entities to add them to "
                                     "the block or take them out." % self.rec["name"], g.body)
            label.setWordWrap(True)
            g.content.addWidget(label)
            geos, _base = indices(self.sketch, self.rec)
            _undo(self.sketch, "Edit Block", lambda: release(self.sketch, self.rec))
            self._build_list("Block Entities", geos)

        def allowed(self, geo):
            other = block_of(self.sketch, geo)
            inner = block_of(self.sketch, geo, within=self.rec["name"])
            if other is not None and other["name"] != self.rec["name"] and other.get("kind") != "belt":
                inner = other                # a whole block of the sketch goes inside this one
            ok = (other is None or other["name"] == self.rec["name"] or inner is other) and \
                (inner is not None or _type(self.sketch.Geometry[geo]) in SUPPORTED) and \
                geo != indices(self.sketch, self.rec)[1]
            if not ok:
                self.show_note("Only lines, arcs, circles, ellipses, splines and points that are in no other block can be added.", True)
            return ok

        def whole(self, geo):
            inner = block_of(self.sketch, geo, within=self.rec["name"])
            other = block_of(self.sketch, geo)
            if other is not None and other["name"] != self.rec["name"]:
                inner = other
            return _members(self.sketch, inner) if inner is not None else [geo]

        def changed(self):
            self.show_note("")

        def _hold(self, geos, sync=True):
            def change():
                rec = set_entities(self.sketch, self.rec["name"], geos)
                hold(self.sketch, rec)
                if sync:
                    sync_definition(self.sketch, rec["name"])    # every instance of the definition
            _undo(self.sketch, "Edit Block", change)

        def accept(self):
            if not self.geos:
                self.show_note("A block needs an entity. Explode Block takes a block apart.", True)
                return
            self._hold(self.geos)
            Base.accept(self)

        def reject(self):

            geos, _base = indices(self.sketch, self.rec)
            self._hold(geos)
            Base.reject(self)

        def leave(self):
            self._hold(self.geos or indices(self.sketch, self.rec)[0])
            Base.leave(self)

        def closing(self):
            self._drop_observer()

    return EditBlockPage


def _insert_page_class():
    Base = _page_base()

    class InsertBlockPage(Base):
        TITLE = "Insert Block"
        ICON = "BLOCK_INSERT"
        PIXMAP = "Sketcher_Clone"

        def build(self):
            self.setProperty("swstyle_pm_title", self.TITLE)
            self.sources = {}       # list text -> block data

            # (codex-receipts sw-reads/insert-and-edit-block-1.md); the placing hint is in the status bar
            g = self.group("Blocks to Insert")
            g.content.addWidget(QtWidgets.QLabel("Open Blocks", g.body))
            self.list = QtWidgets.QListWidget(g.body)
            self.list.setObjectName("SWBlockOpenBlocks")
            self.list.setFixedHeight(90)
            g.content.addWidget(self.list)
            browse = QtWidgets.QPushButton("Browse...", g.body)
            browse.setObjectName("SWBlockBrowse")
            browse.clicked.connect(self.browse)
            g.content.addWidget(browse)
            self.paths = {}         # list text -> the block file it came from
            self.link = QtWidgets.QCheckBox("Link to file:", g.body)
            self.link.setObjectName("SWBlockLinkToFile")
            self.link.setToolTip("The placed blocks stay tied to the block file: Rebuild brings in its changes")
            self.link.setEnabled(False)
            g.content.addWidget(self.link)
            self.list.currentTextChanged.connect(lambda t: self.link.setEnabled(t in self.paths))
            for sketch in [o for o in self.doc.Objects if o.isDerivedFrom("Sketcher::SketchObject")]:
                for name in _definitions(sketch):
                    data = definition_data(sketch, name)
                    if data is not None and name not in self.sources:
                        self.add_source(name, data)
            g = self.group("Parameters")
            form = QtWidgets.QFormLayout()
            self.angle = QtWidgets.QDoubleSpinBox(g.body)
            self.angle.setObjectName("SWBlockAngle")
            self.angle.setRange(-360, 360)
            self.angle.setSuffix("°")
            self.scale = QtWidgets.QDoubleSpinBox(g.body)
            self.scale.setObjectName("SWBlockScale")
            self.scale.setRange(0.001, 1000)
            self.scale.setDecimals(3)
            self.scale.setValue(1.0)
            form.addRow("Block Scale", self.scale)
            form.addRow("Block Rotation", self.angle)
            g.content.addLayout(form)
            self.inserted = []
            self.view = None
            from . import sketchtoolpm
            shell = sketchtoolpm._shell()
            view = shell.view_widget() if shell is not None else None
            if view is not None:
                self.view = view.viewport() if hasattr(view, "viewport") and view.viewport() else view
                self.view.installEventFilter(self)

        def add_source(self, text, data):
            self.sources[text] = data
            self.list.addItem(text)
            self.list.setCurrentRow(self.list.count() - 1)

        def browse(self):
            folder = App.ParamGet(PARAMS).GetString("Folder", os.path.expanduser("~"))
            path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Insert Block", folder,
                                                             "Blocks (*.%s)" % EXT)
            if path:
                self.add_file(path)

        def add_file(self, path):
            try:
                data = load(path)
            except Exception as error:
                self.show_note("Could not read the block: %s" % error, True)
                return
            App.ParamGet(PARAMS).SetString("Folder", os.path.dirname(path))
            self.paths[os.path.basename(path)] = path
            self.add_source(os.path.basename(path), data)

        def chosen(self):
            item = self.list.currentItem()
            return self.sources.get(item.text()) if item is not None else None

        def place(self, at):
            """Inserts the chosen block with its insertion point at at (sketch coordinates)."""
            data = self.chosen()
            if data is None:
                self.show_note("Pick a block to insert first.", True)
                return None
            rec = insert(self.sketch, data, at, self.angle.value(), self.scale.value())
            item = self.list.currentItem()
            path = self.paths.get(item.text()) if item is not None else None
            if path and self.link.isChecked():
                rec = set_link(self.sketch, rec["name"], path)
            self.inserted.append(rec["name"])
            self.show_note("%s placed" % rec["name"])
            return rec

        def eventFilter(self, obj, event):
            if not isinstance(event, QtCore.QEvent):
                return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
            try:
                return self._fw_filter838(obj, event)
            except Exception as exc:
                import FreeCAD
                FreeCAD.Console.PrintWarning("FreeCAD event filter blocks.py: %s\n" % exc)
                return False

        def _fw_filter838(self, obj, event):
            if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton \
                    and self.chosen() is not None:
                QtCore.QTimer.singleShot(0, self._place_at_cursor)
                return True
            if event.type() == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.LeftButton \
                    and self.chosen() is not None:
                return True
            return False

        def _place_at_cursor(self):
            try:
                view = Gui.ActiveDocument.ActiveView
                pos = view.getCursorPos()
                p = view.getPoint(*pos)
                local = self.sketch.getGlobalPlacement().inverse().multVec(p)
            except Exception as error:
                self.show_note("Could not place the block: %s" % error, True)
                return
            self.place(App.Vector(local.x, local.y, 0))

        def reject(self):

            for name in reversed(self.inserted):
                try:
                    self.doc.undo()
                except Exception as _fw_err:
                    _fw_log("blocks.py:1465", _fw_err)
            self.inserted = []
            Base.reject(self)

        def closing(self):
            if self.view is not None:
                try:
                    self.view.removeEventFilter(self)
                except Exception as _fw_err:
                    _fw_log("blocks.py:1474", _fw_err)

    return InsertBlockPage


def _block_page_class():
    Base = _page_base()

    class BlockPage(Base):
        ""

        TITLE = "Block"
        ICON = "BLOCK_EDIT"
        PIXMAP = "Sketcher_Clone"
        TRANSACTION = "Block"

        def __init__(self, sketch, rec, parent=None):
            self.rec = rec
            self._filling = True
            super().__init__(sketch, parent)
            self._filling = False

        def build(self):
            from . import sketchtoolpm
            self.setProperty("swstyle_pm_title", self.TITLE)
            rec = self.rec
            g = self.group("Block")
            self.name = QtWidgets.QLabel(rec["name"], g.body)
            self.name.setObjectName("SWBlockName")
            g.content.addWidget(self.name)
            self.link = QtWidgets.QCheckBox("Link to file", g.body)
            self.link.setObjectName("SWBlockLinkToFile")
            self.link.setChecked(bool(rec.get("file")))
            g.content.addWidget(self.link)
            self.path = QtWidgets.QLabel(rec.get("file") or "", g.body)
            self.path.setObjectName("SWBlockFile")
            self.path.setWordWrap(True)
            g.content.addWidget(self.path)
            self.link.toggled.connect(self._link)
            g = self.group("Parameters")
            form = QtWidgets.QFormLayout()
            _geos, base = indices(self.sketch, rec)
            b = self.sketch.Geometry[base] if base is not None else None
            self.fields = {}
            for key, label, lo, hi, dec, suffix, value in (
                    ("X", "Insertion point X", -1e9, 1e9, 3, " mm", b.X if b is not None else 0.0),
                    ("Y", "Insertion point Y", -1e9, 1e9, 3, " mm", b.Y if b is not None else 0.0),
                    ("Angle", "Angle", -360.0, 360.0, 2, "°", rec.get("angle", 0.0)),
                    ("Scale", "Scale", 0.001, 1000.0, 3, "", rec.get("scale", 1.0))):
                box = QtWidgets.QDoubleSpinBox(g.body)
                box.setObjectName("SWBlock" + key)
                box.setRange(lo, hi)
                box.setDecimals(dec)
                box.setSuffix(suffix)
                box.setKeyboardTracking(False)
                box.setValue(value)
                box.valueChanged.connect(self.changed)
                form.addRow(label, box)
                self.fields[key] = box
            g.content.addLayout(form)
            self.observer = sketchtoolpm.PickObserver(self)
            Gui.Selection.addObserver(self.observer)

        def _link(self, on):
            if self._filling:
                return
            path = self.rec.get("file") or ""
            if on and not path:
                folder = App.ParamGet(PARAMS).GetString("Folder", os.path.expanduser("~"))
                path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Link to file", folder, "Blocks (*.%s)" % EXT)
                if not path:
                    self._filling = True
                    self.link.setChecked(False)
                    self._filling = False
                    return
            self.set_link(path if on else None)

        def set_link(self, path):
            self.begin()
            self.rec = set_link(self.sketch, self.rec["name"], path) or self.rec
            if path:
                try:
                    self.rec = relink(self.sketch, self.rec["name"]) or self.rec
                except Exception as error:
                    self.show_note("The block file: %s" % error, True)
            self.path.setText(path or "")
            self.sketch.solve()
            self._refresh()

        def changed(self, *args):
            if self._filling:
                return
            self.begin()
            f = self.fields
            try:
                self.rec = transform(self.sketch, self.rec["name"], App.Vector(f["X"].value(), f["Y"].value(), 0),
                                     f["Angle"].value(), f["Scale"].value()) or self.rec
                self.show_note("")
            except Exception as error:
                self.show_note(str(error), True)
            self._refresh()

        def _refresh(self):
            from . import sketchtoolpm
            sketchtoolpm._refresh(self.sketch)

        def picked(self, sub):
            ""
            from . import sketchtoolpm
            item = sketchtoolpm.item_of(self.sketch, sub)
            rec = block_of(self.sketch, item.geo) if item is not None and item.geo >= 0 else None
            if rec is None or rec["name"] != self.rec["name"]:
                self.accept()

        def selection_changed(self):
            try:
                if not Gui.Selection.getSelectionEx():
                    self.accept()
            except Exception as _fw_err:
                _fw_log("blocks.py:1593", _fw_err)

        def closing(self):
            try:
                Gui.Selection.removeObserver(self.observer)
            except Exception as _fw_err:
                _fw_log("blocks.py:1599", _fw_err)
            self.observer.page = None

    return BlockPage


def picked_only_block(sketch, items):
    """The block when every picked item is an entity (or point) of that one block, else None."""
    rec = None
    for item in items:
        geo = getattr(item, "geo", None)
        if geo is None or geo < 0:
            return None
        r = block_of(sketch, geo)
        if r is None or (rec is not None and r["name"] != rec["name"]):
            return None
        rec = r
    return rec


def show_block_pm(sketch, items):
    ""

    if not items or not records(sketch):
        return False
    rec = picked_only_block(sketch, items)
    if rec is None:
        return False
    global _pending
    if _pending:
        return True

    def go():
        global _pending
        _pending = False
        from . import contextbar
        if contextbar.sketch_in_edit() is sketch:
            _select_whole(sketch, rec)
            _open(page_class("block")(sketch, rec))
    _pending = True
    QtCore.QTimer.singleShot(0, go)
    return True


_pending = False


def _vertex_of(sketch, geo, pos):
    """The sketch vertex index of point (geo, pos), or None."""
    for v in range(4 * len(sketch.Geometry) + 4):
        try:
            g, p = sketch.getGeoVertexIndex(v)
        except Exception:
            return None
        if g == geo and int(p) == pos:
            return v
        if g < -2 and v > 2:
            break
    return None


def _select_whole(sketch, rec):
    ""

    try:
        geos, _base = indices(sketch, rec)
        have = set()
        for o in Gui.Selection.getSelectionEx(sketch.Document.Name, 0):
            have.update(o.SubElementNames)
        for g in geos:
            sub = "Edge%d" % (g + 1)
            if sub not in have and not any(h.endswith("." + sub) for h in have):
                Gui.Selection.addSelection(sketch.Document.Name, sketch.Name, sub)
        # its insertion point too: Delete of a picked block left the point behind (reviewer 11-19)
        v = _vertex_of(sketch, _base, 1) if _base is not None else None
        if v is not None:
            sub = "Vertex%d" % (v + 1)
            if sub not in have and not any(h.endswith("." + sub) for h in have):
                Gui.Selection.addSelection(sketch.Document.Name, sketch.Name, sub)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: block pick: %s\n" % error)


_classes = {}


def page_class(kind):
    if kind not in _classes:
        _classes[kind] = {"make": _make_page_class, "edit": _edit_page_class, "insert": _insert_page_class,
                          "block": _block_page_class}[kind]()
    return _classes[kind]


def _open(page):
    from . import sketchtoolpm
    sketchtoolpm.open_page(page)
    return page


# ---------------------------------------------------------------- commands
def make_block():
    sketch = _sketch()
    return _open(page_class("make")(sketch)) if sketch is not None else None


def edit_block(title="Edit Block"):
    sketch = _sketch()
    rec = picked_block(sketch) if sketch is not None else None
    if rec is None:
        _status("Select an entity of the block to edit.")
        return None
    return _open(page_class("edit")(sketch, rec, title))


def insert_block():
    sketch = _sketch()
    return _open(page_class("insert")(sketch)) if sketch is not None else None


def save_block(path=None):
    sketch = _sketch()
    rec = picked_block(sketch) if sketch is not None else None
    if rec is None:
        _status("Select an entity of the block to save.")
        return None
    if path is None:
        folder = App.ParamGet(PARAMS).GetString("Folder", os.path.expanduser("~"))
        path, _f = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save Block",
                                                         os.path.join(folder, rec["definition"] + "." + EXT),
                                                         "Blocks (*.%s)" % EXT)
        if not path:
            return None
        if not path.endswith("." + EXT):
            path += "." + EXT
        App.ParamGet(PARAMS).SetString("Folder", os.path.dirname(path))
    save(sketch, rec["name"], path)
    _status("%s saved to %s" % (rec["definition"], path))
    return path


def explode_block():
    sketch = _sketch()
    rec = picked_block(sketch) if sketch is not None else None
    if rec is None:
        _status("Select an entity of the block to explode.")
        return False
    explode(sketch, rec["name"])
    _status("%s exploded" % rec["name"])
    return True


def rebuild_blocks():
    sketch = _sketch()
    return rebuild(sketch) if sketch is not None else 0


def _in_sketch():
    return App.ActiveDocument is not None and _sketch() is not None


def _has_blocks():
    sketch = _sketch() if App.ActiveDocument is not None else None
    return sketch is not None and bool(records(sketch))



HIDDEN_LAYER = 2     # ViewProviderSketch's hidden visual layer (the Elements list's eye)


def is_hidden(rec):
    return bool(rec and rec.get("hidden"))


def _block_geos(sketch, rec, recs):
    """Entity and insertion point indices of a block and of the blocks inside it."""
    out = set()
    for r in [rec] + descendants(sketch, rec["name"], recs):
        geos, base = indices(sketch, r)
        out.update(geos)
        if base is not None:
            out.add(base)
    return out


def set_hidden(sketch, name, hidden=True, transaction=True):
    ""

    try:
        import SketcherGui
    except ImportError:
        return False
    recs = records(sketch)
    rec = next((r for r in recs if r["name"] == name), None)
    if rec is None:
        return False
    targets = _block_geos(sketch, rec, recs)
    names = {rec["name"]} | {r["name"] for r in descendants(sketch, name, recs)}

    def change():
        geos = geomkeep.read(sketch)
        for i in targets:
            e = SketcherGui.ViewProviderSketchGeometryExtension()
            e.VisualLayerId = HIDDEN_LAYER if hidden else 0
            geos[i].setExtension(e)
        sketch.Geometry = geos
        for r in recs:
            if r["name"] in names:
                if hidden:
                    r["hidden"] = True
                else:
                    r.pop("hidden", None)
        _store(sketch, recs)
        return True
    if transaction:
        return _undo(sketch, "Hide Block" if hidden else "Show Block", change)
    return change()


def under_defined(sketch, rec):
    ""

    try:
        dep = sketch.getGeometryWithDependentParameters()
    except Exception:
        return None
    geos, base = indices(sketch, rec)
    mine = set(geos) | ({base} if base is not None else set())
    return any(g in mine for g, _p in dep)


def hide_show_block():
    sketch = _sketch()
    rec = picked_block(sketch) if sketch is not None else None
    if rec is None:
        _status("Pick an entity of the block to hide")
        return
    set_hidden(sketch, rec["name"], not is_hidden(rec))
    try:
        Gui.Selection.clearSelection()
    except Exception as _fw_err:
        _fw_log("blocks.py:1819", _fw_err)


class _Cmd:
    def __init__(self, text, tip, run, active):
        self.text, self.tip, self.run, self.active = text, tip, run, active

    def GetResources(self):
        resources = {"MenuText": self.text, "ToolTip": self.tip, "CmdType": "ForEdit"}
        if self.run is hide_show_block:
            from . import icons
            resources["Pixmap"] = icons.pixmap_path("I3DVIEW_HIDE_SHOW_ITEMS")
        return resources

    def Activated(self):
        self.run()

    def IsActive(self):
        try:
            return self.active()
        except Exception:
            return False


COMMANDS = {
    "SWStyle_MakeBlock": _Cmd("Make Block", "Makes a block from the selected sketch entities", make_block, _in_sketch),
    "SWStyle_EditBlock": _Cmd("Edit Block", "Edits the selected block", edit_block, _has_blocks),
    "SWStyle_InsertBlock": _Cmd("Insert Block", "Inserts a block of this document or of a block file",
                                insert_block, _in_sketch),
    "SWStyle_AddRemoveBlockEntities": _Cmd("Add/Remove Entities", "Adds entities to the selected block or takes "
                                           "them out", lambda: edit_block("Add/Remove Entities"), _has_blocks),
    "SWStyle_RebuildBlocks": _Cmd("Rebuild", "Rebuilds the blocks of the sketch", rebuild_blocks, _has_blocks),
    "SWStyle_SaveBlock": _Cmd("Save Block", "Saves the selected block to a file", save_block, _has_blocks),
    "SWStyle_ExplodeBlock": _Cmd("Explode Block", "Breaks the selected block into its sketch entities",
                                 explode_block, _has_blocks),
    "SWStyle_HideShowBlock": _Cmd("Hide Block", "Hides the selected block's entities (Show brings them back)",
                                  hide_show_block, _has_blocks),
}


def register():
    for name, cmd in COMMANDS.items():
        if name not in Gui.listCommands():
            Gui.addCommand(name, cmd)
