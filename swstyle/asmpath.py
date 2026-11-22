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

V = App.Vector
KIND = "Path Mate"
PATH_PROP = "FwPath"            # constraint, value, flip, pitch, pitch axis, pitch flip, roll, roll axis, roll flip
UP_PROP = "FwPathUp"            # the Up Vector pick
MODES = ("Free", "Along Path Distance", "Along Path Percent")
PITCH = ("Free", "Follow Path")
ROLL = ("Free", "Up Vector", "Along Path")
LABELS = {"Along Path Distance": "Distance Along Path", "Along Path Percent": "Percent Along Path"}
AXES = ("X", "Y", "Z")
_AXIS = {"X": V(1, 0, 0), "Y": V(0, 1, 0), "Z": V(0, 0, 1)}


def values(joint):
    """{mode, value, flip, pitch, pitch_axis, pitch_flip, roll, roll_axis, roll_flip}."""
    d = list(getattr(joint, PATH_PROP, []) or [])
    d += [""] * (9 - len(d))
    num = lambda s: float(s) if s not in ("", None) else 0.0
    return {"mode": d[0] if d[0] in MODES else "Free", "value": num(d[1]), "flip": d[2] == "1",
            "pitch": d[3] if d[3] in PITCH else "Free", "pitch_axis": d[4] if d[4] in AXES else "X",
            "pitch_flip": d[5] == "1", "roll": d[6] if d[6] in ROLL else "Free",
            "roll_axis": d[7] if d[7] in AXES else "Y", "roll_flip": d[8] == "1"}


def _store(joint, v):
    b = lambda x: "1" if x else "0"
    setattr(joint, PATH_PROP, [v["mode"], repr(float(v["value"])), b(v["flip"]), v["pitch"], v["pitch_axis"],
                               b(v["pitch_flip"]), v["roll"], v["roll_axis"], b(v["roll_flip"])])


def is_vertex(ref):
    s = ac.element(*ref)
    return s is not None and s.ShapeType == "Vertex"


def is_edge(ref):
    s = ac.element(*ref)
    return s is not None and s.ShapeType == "Edge"


def refs_of(joint):
    """(component vertex (comp, element), [path edges (comp, element)])."""
    v = (joint.Reference1[0], joint.Reference1[1][0])
    comp = joint.Reference2[0]
    return v, [(comp, e) for e in joint.Reference2[1] if e]


# ----------------------------------------------------------------------------- the path
def _ends(e):
    """The edge's ends in its parameter's direction (a face's edge can run against its vertexes)."""
    return V(e.valueAt(e.FirstParameter)), V(e.valueAt(e.LastParameter))


def chain(edges):
    """The edges in order, each with its sense: [(edge, reversed)], start to end. The first
    picked edge sets the start (its first end that is not shared with the next edge)."""
    shapes = [ac.element(*e) for e in edges]
    shapes = [s for s in shapes if s is not None]
    if not shapes:
        return []
    tol = 1e-6
    left = shapes[1:]

    def ends(e, rev):
        a, b = _ends(e)
        return (b, a) if rev else (a, b)

    def meets(p):
        return any(min((q - p).Length for q in _ends(x)) < tol for x in left)
    a, b = _ends(shapes[0])
    out = [(shapes[0], bool(left) and meets(a) and not meets(b))]
    grew = True
    while left and grew:
        grew = False
        head = ends(*out[0])[0]
        tail = ends(*out[-1])[1]
        for x in list(left):
            a, b = _ends(x)
            if (a - tail).Length < tol:
                out.append((x, False))
            elif (b - tail).Length < tol:
                out.append((x, True))
            elif (b - head).Length < tol:
                out.insert(0, (x, False))
            elif (a - head).Length < tol:
                out.insert(0, (x, True))
            else:
                continue
            left.remove(x)
            grew = True
            break
    return out


def length(path):
    return sum(e.Length for e, _r in path)


def _tangent(e, u, rev):
    t = V(e.tangentAt(u))
    t = t.normalize() if t.Length > 1e-12 else V(1, 0, 0)
    return -t if rev else t


def at(path, s):
    """(point, tangent) at s along the path (clamped to its ends)."""
    s = max(0.0, min(length(path), s))
    for i, (e, rev) in enumerate(path):
        L = e.Length
        if s <= L + 1e-12 or i == len(path) - 1:
            local = L - s if rev else s
            local = max(0.0, min(L, local))
            u = e.getParameterByLength(local)
            return V(e.valueAt(u)), _tangent(e, u, rev)
        s -= L
    e, rev = path[-1]
    return ends_of(path)[1], _tangent(e, e.FirstParameter if rev else e.LastParameter, rev)


def ends_of(path):
    """The path's start and end points."""
    e0, r0 = path[0]
    e1, r1 = path[-1]
    return _ends(e0)[1 if r0 else 0], _ends(e1)[0 if r1 else 1]


def nearest(path, p):
    """(point, tangent, s) on the path nearest to p."""
    import Part
    best = None
    start = 0.0
    for e, rev in path:
        d, pts, _info = e.distToShape(Part.Vertex(p))
        q = V(pts[0][0])
        if best is None or d < best[0] - 1e-12:
            u = e.Curve.parameter(q)
            u = max(e.FirstParameter, min(e.LastParameter, u))
            try:
                run = e.Curve.length(e.FirstParameter, u)
            except Exception:
                run = (q - _ends(e)[0]).Length
            s = start + (e.Length - run if rev else run)
            best = (d, q, _tangent(e, u, rev), s)
        start += e.Length
    return best[1], best[2], best[3]


def target(path, v):
    """The point (and tangent) the vertex is held at, None for Free."""
    L = length(path)
    if v["mode"] == "Along Path Distance":
        s = float(v["value"])
    elif v["mode"] == "Along Path Percent":
        s = L * float(v["value"]) / 100.0
    else:
        return None
    return at(path, L - s if v["flip"] else s)


# ----------------------------------------------------------------------------- the mate
def make(asm, vertex, edges, settings=None, joint=None, up=None):
    """Path Mate: vertex (comp, element) on the chain of edges (comp, element) of another
    component. Returns (mate, message)."""
    import UtilsAssembly
    if not is_vertex(vertex) or not edges or not all(is_edge(e) for e in edges):
        return None, "Pick a vertex of the component and the edges of the path."
    if any(e[0] is vertex[0] for e in edges) or len({e[0].Name for e in edges}) != 1:
        return None, "The path's edges must all be on one other component."
    v = dict(values(joint)) if joint is not None else values(None)
    v.update(settings or {})
    if joint is None:
        joint = ac.joint_group(asm).newObject("App::FeaturePython", "PathMate")
        for prop, t, doc in ((ac.MATE_PROP, "App::PropertyString", "Mate type"),
                             (ac.ERROR_PROP, "App::PropertyBool", "The mate over defines the assembly"),
                             (PATH_PROP, "App::PropertyStringList", "Path Mate settings"),
                             ("Suppressed", "App::PropertyBool", "Suppressed"),
                             ("Reference1", "App::PropertyXLinkSubHidden", "Component vertex"),
                             ("Reference2", "App::PropertyXLinkSubHidden", "Path selection"),
                             (UP_PROP, "App::PropertyXLinkSubHidden", "Up vector")):
            joint.addProperty(t, prop, "FreeCAD", doc)
        setattr(joint, ac.MATE_PROP, KIND)
        joint.Label = ac._next_mate_name(asm, KIND)
        if App.GuiUp and joint.ViewObject is not None:
            joint.ViewObject.Proxy = 0
    joint.Reference1 = (vertex[0], [vertex[1]])
    joint.Reference2 = (edges[0][0], [e[1] for e in edges])
    if up is not None:
        setattr(joint, UP_PROP, (up[0], [up[1]]) if up else None)
    _store(joint, v)
    before = UtilsAssembly.saveAssemblyPartsPlacements(asm)
    _hold(asm, joint)
    ok = ac.solve(asm, before) and holds(joint)
    return joint, (None if ac._mark(joint, ok) else ac.OVER_MESSAGE)


def _hold(asm, joint):
    """No FreeCAD joint holds a Path Mate: FreeCAD's solver crashes (OndselSolver,
    removeRedundantConstraints) when a hidden Ball meets another mate on the same vertex, so the
    component is put on its point after each solve instead. Hidden joints of an older
    Path Mate go."""
    for o in ac._part_for(asm, joint):
        asm.Document.removeObject(o.Name)
    return None


def path_mates(asm):
    return [j for j in ac.mates(asm) if ac.mate_type(j) == KIND and not getattr(j, "Suppressed", False)]


def sync(asm):
    """Before a solve: no hidden joints left under a Path Mate."""
    for joint in path_mates(asm):
        try:
            _hold(asm, joint)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: path mate: %s\n" % error)


def _up(joint):
    ref = getattr(joint, UP_PROP, None)
    if ref and ref[0] is not None and ref[1]:
        g = ac.geometry(ac.element(ref[0], ref[1][0]))
        if g is not None and g[0] in ("plane", "line", "axis"):
            return V(g[2]).normalize()
    return V(0, 0, 1)


def _roll_up(joint, v, path, q, t, h=None):
    """The direction the roll axis is turned to: the Up Vector, or (Along Path) the path's normal
    at q, from the turn of its tangent a little either side."""
    if v["roll"] == "Along Path":
        try:
            h = h or max(length(path) * 1e-3, 1e-3)
            t1 = nearest(path, q - t * h)[1]
            t2 = nearest(path, q + t * h)[1]
            n = V(t2) - V(t1)
            n = n - t * n.dot(t)
            if n.Length > 1e-6:
                return n.normalize()
        except Exception as _fw_err:
            _fw_log("asmpath.py:275", _fw_err)
    return _up(joint)


def place(asm):
    """After a solve: Free mates slide their component back onto the path; Follow Path and Up
    Vector turn it about the vertex. True when something moved."""
    fixed = set(ac.grounded(asm))
    moved = False
    for joint in path_mates(asm):
        try:
            moved |= _place(joint, fixed)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: path mate: %s\n" % error)
    return moved


def _place(joint, fixed):
    v = values(joint)
    vertex, edges = refs_of(joint)
    comp = vertex[0]
    path = chain(edges)
    if comp in fixed or not path:
        return False
    p = V(ac.element(*vertex).Point)
    held = target(path, v)
    q, t = held if held is not None else nearest(path, p)[:2]
    pl = App.Placement(comp.Placement)
    pl.Base = pl.Base + (q - p)
    if v["pitch"] == "Follow Path":
        rot = pl.Rotation
        a = rot.multVec(_AXIS[v["pitch_axis"]] * (-1 if v["pitch_flip"] else 1))
        r1 = App.Rotation(a, t)
        rot = r1.multiply(rot)
        if v["roll"] in ("Up Vector", "Along Path") and v["roll_axis"] != v["pitch_axis"]:
            u = _roll_up(joint, v, path, q, t)
            u = u - t * u.dot(t)
            b = rot.multVec(_AXIS[v["roll_axis"]] * (-1 if v["roll_flip"] else 1))
            b = b - t * b.dot(t)
            if u.Length > 1e-9 and b.Length > 1e-9:
                u.normalize()
                b.normalize()
                if b.dot(u) < -1 + 1e-12:
                    r2 = App.Rotation(t, 180)
                else:
                    r2 = App.Rotation(b, u)
                rot = r2.multiply(rot)
        turn = App.Placement(V(), rot.multiply(pl.Rotation.inverted()), q)
        pl = turn.multiply(pl)
    if (pl.Base - comp.Placement.Base).Length < 1e-9 and pl.Rotation.isSame(comp.Placement.Rotation, 1e-12):
        return False
    comp.Placement = pl
    return True


def holds(joint, tol=1e-3):
    """The vertex on the path (at its point for Distance/Percent), its axis along the tangent
    (Follow Path) and turned to the up vector (Up Vector)."""
    try:
        v = values(joint)
        vertex, edges = refs_of(joint)
        path = chain(edges)
        if not path:
            return False
        p = V(ac.element(*vertex).Point)
        held = target(path, v)
        if held is not None:
            q, t = held
            if (p - q).Length > tol * 10:
                return False
        else:
            q, t, _s = nearest(path, p)
            if (p - q).Length > tol * 10:
                return False
        rot = vertex[0].Placement.Rotation
        if v["pitch"] == "Follow Path":
            a = rot.multVec(_AXIS[v["pitch_axis"]] * (-1 if v["pitch_flip"] else 1))
            if (a - t).Length > tol * 10:
                return False
            if v["roll"] in ("Up Vector", "Along Path") and v["roll_axis"] != v["pitch_axis"]:
                u = _roll_up(joint, v, path, q, t)
                u = u - t * u.dot(t)
                if u.Length > 1e-9:
                    b = rot.multVec(_AXIS[v["roll_axis"]] * (-1 if v["roll_flip"] else 1))
                    b = b - t * b.dot(t)
                    if b.Length < 1e-9 or b.normalize().dot(u.normalize()) < 1 - tol:
                        return False
        return True
    except Exception:
        return True
