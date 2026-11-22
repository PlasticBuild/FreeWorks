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

import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import contextbar, paths

PARAM = "FaceHoverOutline"     # addon parameter (default on)
WIDTH = 2.5                    # outline width in pixels
SEEN_PX = 3                    # a boundary point is seen when the model is this close under it
MAX_PICKS = 60                 # picks along one edge at most
SPOT_BUDGET = 0.1              # s: an edge click looks this long for the spot FreeCAD picks the edge at
PICK_BUDGET = 0.12             # s: past it the rest of the outline counts as seen (each pick walks the
                               # whole scene: 13 ms in a 301-part assembly, 4 s per hovered face)
STEP_DEG = 2.0                 # degrees between outline points on a round edge
VIEW = "User parameter:BaseApp/Preferences/View"
EDGE_FIRST = "EdgeBeforeFace"  # addon parameter (default on): an edge near the pointer wins over its face
POINT_PX = 5                   # a hovered corner's dot, in pixels


def enabled():
    return paths.params().GetBool(PARAM, True)


def _colour():
    packed = App.ParamGet(VIEW).GetUnsigned("HighlightColor", 0xFF8C00FF)
    return ((packed >> 24) & 255) / 255.0, ((packed >> 16) & 255) / 255.0, ((packed >> 8) & 255) / 255.0


def _count(edge):
    """Points along an edge: a straight one needs its ends, a round one a point every STEP_DEG
    degrees, so the outline stays on the round edge drawn smooth (a deflection of 1/400 of the
    length gave a 10 mm hole 19 points, a polygon cutting in and out of it: Ati, 2026-10-28)."""
    import math
    curve = getattr(edge, "Curve", None)
    if curve is not None and curve.TypeId == "Part::GeomLine":
        return 2
    radius = getattr(curve, "Radius", None)
    if radius:
        turn = math.degrees(edge.Length / radius)
        return int(min(max(turn / STEP_DEG + 1, 8), 721))
    return 240


def _face_edges(doc, obj, sub):
    """Polylines (lists of App.Vector) along the boundary of the face sub of obj, placed."""
    import Part
    owner = App.getDocument(doc).getObject(obj)
    face = Part.getShape(owner, sub, needSubElement=True)
    lines = []
    for edge in face.Edges:
        try:
            points = edge.discretize(Number=_count(edge))
        except Exception:
            continue
        if len(points) > 1:
            lines.append(points)
    return lines


def _edge_lines(doc, obj, sub):
    """The hovered edge itself as one polyline, placed."""
    import Part
    owner = App.getDocument(doc).getObject(obj)
    edge = Part.getShape(owner, sub, needSubElement=True)
    try:
        points = edge.discretize(Number=_count(edge))
    except Exception:
        return []
    return [points] if len(points) > 1 else []


def _lines(doc, obj, sub):
    element = sub.rsplit(".", 1)[-1]
    return _edge_lines(doc, obj, sub) if element.startswith("Edge") else _face_edges(doc, obj, sub)


def _seen(view, at, p, tol):
    """True when the model under the screen spot at (or a pixel or two beside it) is p itself. On
    a round edge the point sits on the true curve while the faces are drawn as polygons, so the
    spot itself often looks into the hole (Ati, 2026-10-28: the outline broke off on circles)."""
    x, y = at
    try:
        towards = App.Vector(view.getViewDirection())
        towards.normalize()
    except Exception:
        towards = None
    import time
    t0 = time.time()
    for dx, dy in ((0, 0), (SEEN_PX, 0), (-SEEN_PX, 0), (0, SEEN_PX), (0, -SEEN_PX)):
        if time.time() - t0 > SLOW_PICK:
            return True     # a big assembly: one pick took too long, the four beside it would too (vd119)
        try:
            info = view.getObjectInfo((x + dx, y + dy))
        except Exception:
            return True
        if not info:
            if dx == 0 and dy == 0:
                return True          # nothing behind it: the edge is the outline of the model
            continue
        hit = App.Vector(info["x"], info["y"], info["z"])
        if (hit - p).Length <= tol:
            return True
        if dx == 0 and dy == 0 and towards is not None and (hit - p).dot(towards) > -3 * tol:
            # what the spot shows lies behind the point (into a hole, past the edge of a tilted face): nothing
            # hides it. The test above alone dropped bits of a hole's outline seen at a slant (vd113, 11-20)
            return True
    return False


SLOW_PICK = 0.03                # s for one point's picks: past it the view counts as slow to pick
RECHECK = 25                    # hovers between two tries of a slow view (it may have got smaller)
_PICKS = {}                     # document -> [last point's pick time, hovers skipped since]


def _view_key(view):
    try:
        return Gui.ActiveDocument.Document.Name
    except Exception:
        return None


def _picks_slow(view):
    key = _view_key(view)
    got = _PICKS.get(key)
    if got is None or got[0] <= SLOW_PICK:
        return False
    got[1] += 1
    if got[1] >= RECHECK:
        got[1] = 0
        got[0] = 0.0            # try again: the next point's picks are timed afresh
        return False
    return True


def _note_pick(view, seconds):
    got = _PICKS.setdefault(_view_key(view), [0.0, 0])
    got[0] = seconds


def _seen_parts(view, lines):
    """The polylines cut down to the stretches the model doesn't hide: a point counts as seen
    when the model point under it on screen is the point itself (FreeCAD draws its own scene
    after anything added to it, so the outline is drawn without depth and hidden parts are
    left out here)."""
    def screen(p):
        x, y = view.getPointOnScreen(p)
        return x, y
    x0, y0 = screen(lines[0][0])
    tol = max((view.getPoint(int(x0) + SEEN_PX, int(y0)) - view.getPoint(int(x0), int(y0))).Length, 1e-6)
    parts = []
    import time
    t0 = time.time()
    if _picks_slow(view):
        # a big assembly: one pick walks every component (70 ms on 300 parts), so the outline is drawn
        # whole, as it was past the budget anyway (vd119, 11-21: hover 590 ms against stock's 118)
        return [[(p.x, p.y, p.z) for p in line] for line in lines if len(line) > 1]
    for line in lines:
        step = max(1, len(line) // MAX_PICKS)
        run = []
        for i, p in enumerate(line):
            if i % step == 0 or i == len(line) - 1:
                if time.time() - t0 > PICK_BUDGET:
                    seen = True
                else:
                    t1 = time.time()
                    seen = _seen(view, screen(p), p, tol)
                    _note_pick(view, time.time() - t1)
            if seen:
                run.append((p.x, p.y, p.z))
            else:
                if len(run) > 1:
                    parts.append(run)
                run = []
        if len(run) > 1:
            parts.append(run)
    return parts


def _near_px():
    """How close (device pixels) the pointer must be to an edge for the edge to win: FreeCAD's
    pick radius (Options > Display > Selection)."""
    try:
        r = float(App.ParamGet(VIEW).GetFloat("PickRadius", 5.0))
    except Exception:
        r = 5.0
    try:
        dpr = Gui.getMainWindow().devicePixelRatioF() or 1.0
    except Exception:
        dpr = 1.0
    return max(2.0, r) * dpr


def _to_segment(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    n = dx * dx + dy * dy
    u = 0.0 if n < 1e-12 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / n))
    cx, cy = ax + u * dx, ay + u * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5, (cx, cy)


_FACES_ONLY = None


def faces_only(owner, check):
    """A PropertyManager whose box takes faces only at times says so: check(owner) -> True while it
    does (Up To Surface's Face/Plane box). Kept only as long as owner lives."""
    global _FACES_ONLY
    import weakref
    if _FACES_ONLY is None:
        _FACES_ONLY = weakref.WeakKeyDictionary()
    try:
        _FACES_ONLY[owner] = check
    except TypeError as _fw_err:
        _fw_log("facehover.py:193", _fw_err)


def _faces_only_now():
    for owner, check in list((_FACES_ONLY or {}).items()):
        try:
            if check(owner):
                return True
        except Exception:
            continue                # a page already gone
    return False


def _edges_wanted(doc, obj, edge_sub):
    """False when the open PropertyManager box takes faces only, or the selection filter has no edges."""
    if _faces_only_now():
        return False
    try:
        from . import selfilter
        if not selfilter.allows(App.getDocument(doc).getObject(obj), edge_sub):
            return False
    except Exception as _fw_err:
        _fw_log("facehover.py:215", _fw_err)
    try:
        from . import filletpm
        page = filletpm.current()
        if page is not None and getattr(page, "FACES_ONLY", False):
            return False
    except Exception as _fw_err:
        _fw_log("facehover.py:222", _fw_err)
    panel = None
    try:
        if Gui.Control.activeDialog() and hasattr(Gui.Control, "activeTaskDialog"):
            panel = Gui.Control.activeTaskDialog()
    except Exception:
        panel = None
    if panel is None:
        return True
    kinds = getattr(panel, "pick_kinds", None)
    if callable(kinds):
        try:
            k = kinds()
            if k is not None:
                return "Edge" in k
        except Exception as _fw_err:
            _fw_log("facehover.py:238", _fw_err)
    if getattr(panel, "FACES_ONLY", False):
        return False
    kinds = getattr(panel, "kinds", None)          # pickfirst's tool-first pick page
    if isinstance(kinds, (tuple, list)) and "Face" in kinds and "Edge" not in kinds:
        return False
    spec, active = getattr(panel, "spec", None), getattr(panel, "active", None)
    if spec is not None and isinstance(active, str):
        field = next((f for f in getattr(spec, "fields", ()) if getattr(f, "name", None) == active), None)
        what = getattr(field, "what", None)
        if isinstance(what, (tuple, list)) and what and "Edge" not in what:
            return False            # a "pick" box of faces (or vertices) only
    return True


def _pointer(view, doc):
    """The pointer in the view's pixels (y up): where FreeCAD's preselection hit the model."""
    try:
        pre = Gui.Selection.getPreselection()
        pts = list(getattr(pre, "PickedPoints", ()) or ())
        if pre is not None and pre.DocumentName == doc and pts:
            x, y = view.getPointOnScreen(pts[0])
            return float(x), float(y)
    except Exception as _fw_err:
        _fw_log("facehover.py:262", _fw_err)
    return None


_NEAR_CACHE = {}
_EDGE_LIST = {}     # parent shape hash -> (parent, parent.Edges): one list per body shape; the shape held


def _edge_name(parent, edge):
    """parent's "EdgeN" for edge. vd108 (11-20): looking each face edge up by isSame over a fresh list of all
    the body's edges took seconds per hover on a 200-feature part (a plate face with 150 hole edges x 2000
    edges). FreeCAD's own findSubShape does it in C++; the isSame search is the fallback, on a cached list."""
    try:
        kind, index = parent.findSubShape(edge)
        if kind == "Edge" and index > 0:
            return "Edge%d" % index
    except Exception as _fw_err:
        _fw_log("facehover.py:find-sub", _fw_err)
    try:
        h = parent.hashCode()
    except Exception:
        h = None
    hit = _EDGE_LIST.get(h) if h is not None else None
    edges = hit[1] if hit is not None and hit[0].isSame(parent) else None
    if edges is None:
        edges = parent.Edges
        if h is not None:
            if len(_EDGE_LIST) > 4:
                _EDGE_LIST.clear()
            _EDGE_LIST[h] = (parent, edges)
    for i, e in enumerate(edges, 1):
        if e.isSame(edge):
            return "Edge%d" % i
    return None


def near_edge(doc, obj, sub, at=None, any_box=False):
    """The subname of the edge of face sub that the pointer (at, view pixels with y up; None: where
    the preselection hit) is within the pick radius of, or None. None too while edges are not
    wanted (a box of faces only), unless any_box."""
    import Part
    element = sub.rsplit(".", 1)[-1]
    prefix = sub[:len(sub) - len(element)]
    try:
        view = Gui.getDocument(doc).ActiveView
        owner = App.getDocument(doc).getObject(obj)
        at = at if at is not None else _pointer(view, doc)
        if at is None or owner is None:
            return None
        parent = Part.getShape(owner, prefix) if prefix else Part.getShape(owner)
        key = (doc, obj, sub, parent.hashCode())
        lines = _NEAR_CACHE.get(key)
        if lines is None:
            face = parent.getElement(element)
            lines = []
            for edge in face.Edges:
                if edge.isDegenerated() if hasattr(edge, "isDegenerated") else False:
                    continue
                name = _edge_name(parent, edge)
                if name is None:
                    continue
                try:
                    bb = edge.BoundBox
                    corners = [App.Vector(x, y, z) for x in (bb.XMin, bb.XMax) for y in (bb.YMin, bb.YMax)
                               for z in (bb.ZMin, bb.ZMax)]
                except Exception:
                    continue
                lines.append([name, edge, corners, None])   # points made when the pointer comes near
            if len(_NEAR_CACHE) > 24:
                _NEAR_CACHE.clear()
            _NEAR_CACHE[key] = lines
    except Exception:
        return None
    px, py = at
    best, best_d, spot = None, _near_px(), None
    for line in lines:
        name, edge, corners, points = line
        try:
            # vd108: the edge's box on screen first, so only edges by the pointer are walked (a plate
            # face with 150 holes had 2000 edges discretized and projected on every move)
            box = [view.getPointOnScreen(c) for c in corners]
            if px < min(c[0] for c in box) - best_d or px > max(c[0] for c in box) + best_d \
                    or py < min(c[1] for c in box) - best_d or py > max(c[1] for c in box) + best_d:
                continue
            if points is None:
                points = line[3] = edge.discretize(Number=_count(edge))
            if len(points) < 2:
                continue
            scr = [view.getPointOnScreen(p) for p in points]
        except Exception:
            continue
        for a, b in zip(scr, scr[1:]):
            d, c = _to_segment(px, py, a, b)
            if d <= best_d:
                best, best_d, spot = name, d, c
    if best is None:
        return None
    edge_sub = prefix + best
    if not any_box and not _edges_wanted(doc, obj, edge_sub):
        return None
    LAST_NEAR[:] = [edge_sub, spot, (px, py)]
    return edge_sub


LAST_NEAR = []      # [edge subname, nearest screen point on it, pointer] from the last near_edge()


def ray_edge(doc, at):
    ""






    try:
        view = Gui.ActiveDocument.ActiveView
        # one pick along the whole ray: its first record is what getObjectInfo gives
        many = view.getObjectsInfo((int(round(at[0])), int(round(at[1])))) or []
    except Exception:
        return None
    if not many:
        return None
    info = many[0]
    hit = _hit(info)
    if hit is None:
        return None
    if hit[2].rsplit(".", 1)[-1].startswith("Face"):
        hit = _edge_on_face(view, at, many, hit)
    if hit is None or not hit[2].rsplit(".", 1)[-1].startswith("Edge"):
        return None
    return hit


def _same(a, b):
    """Two (document, object, subname) name the same element (FreeCAD's hover may give the element's
    mapped name, ';g3;SKT.Edge3', where the view's pick gives Edge3)."""
    if a is None or b is None or a[0] != b[0] or a[1] != b[1]:
        return False

    def plain(sub):
        parts = str(sub).split(".")
        return [p for p in parts[:-1] if p and not p.startswith(";")] + [parts[-1]]
    return plain(a[2]) == plain(b[2])


def _hit(info):
    """(document, top object, subname, (x, y, z)) of one pick record, or None."""
    parent = info.get("ParentObject")
    doc = info.get("Document")
    if parent is not None and info.get("SubName"):
        # a component kept in its own file: info names that file, the path starts at the assembly's
        top, sub, doc = parent.Name, info["SubName"], parent.Document.Name
    else:
        top, sub = info.get("Object"), info.get("Component") or ""
    if not top or not doc:
        return None
    return doc, top, sub, (info.get("x", 0.0), info.get("y", 0.0), info.get("z", 0.0))


def _edge_on_face(view, at, many, face):
    ""

    try:
        d = App.Vector(*view.getViewDirection())
        mm = (App.Vector(*view.getPoint(int(at[0]) + 1, int(at[1]))) - App.Vector(*view.getPoint(int(at[0]), int(at[1])))).Length
    except Exception:
        return None
    depth = App.Vector(*face[3]).dot(d)
    tol = max(mm, 1e-4)
    owner = (face[0], face[1], face[2].rsplit(".", 1)[0])
    for item in many:
        hit = _hit(item)
        if hit is None or not hit[2].rsplit(".", 1)[-1].startswith("Edge"):
            continue
        if abs(App.Vector(*hit[3]).dot(d) - depth) > tol:
            continue                    # in front of or behind the face: FreeCAD's own pick stands
        if (hit[0], hit[1], hit[2].rsplit(".", 1)[0]) == owner:
            continue                    # the face's own edge: near_edge's business
        return hit
    return None


def face_under(doc, obj, edge_sub, at):
    ""


    import Part
    element = edge_sub.rsplit(".", 1)[-1]
    prefix = edge_sub[:len(edge_sub) - len(element)]
    try:
        view = Gui.getDocument(doc).ActiveView
        info = view.getObjectInfo((int(round(at[0])), int(round(at[1]))))
        leaf = (info.get("SubName") or info.get("Component") or "").rsplit(".", 1)[-1] if info else ""
        if not leaf.startswith("Face"):
            return None
        owner = App.getDocument(doc).getObject(obj)
        parent = Part.getShape(owner, prefix) if prefix else Part.getShape(owner)
        edge = parent.getElement(element)
        if not any(e.isSame(edge) for e in parent.getElement(leaf).Edges):
            return None             # another object's face, or one not by this edge
    except Exception:
        return None
    return prefix + leaf


def face_spot(doc, obj, face_sub, at):
    """A spot in the view (pixels, y up) by the pointer, out of the pick radius of the face's edges,
    where FreeCAD's own pick gives face_sub. None when there is none close by."""
    leaf = face_sub.rsplit(".", 1)[-1]
    x, y = at
    for _ in range(3):
        if near_edge(doc, obj, face_sub, (x, y), any_box=True) is None:
            break
        cx, cy = LAST_NEAR[1]
        dx, dy = x - cx, y - cy
        n = (dx * dx + dy * dy) ** 0.5
        if n < 0.5:
            return None             # right on the edge's line: no telling which side the face is
        r = _near_px() + 3.0     # FreeCAD's pick reaches past its radius by half the drawn line and a
                                 # pixel: 6 px in from an edge still picked it with the radius at 5
        x, y = cx + dx / n * r, cy + dy / n * r
    else:
        return None
    try:
        info = Gui.getDocument(doc).ActiveView.getObjectInfo((int(round(x)), int(round(y))))
    except Exception:
        info = None
    if not info or (info.get("SubName") or info.get("Component") or "").rsplit(".", 1)[-1] != leaf:
        return None
    return x, y


def edge_spot(doc, edge_sub, at):
    """A spot in the view (pixels, y up) by the pointer where FreeCAD's own pick gives edge_sub: on
    the way from the pointer to the edge's line and a few pixels past it (the edge is drawn on
    one side of its line). None when no spot there gives the edge."""
    leaf = edge_sub.rsplit(".", 1)[-1]
    try:
        view = Gui.getDocument(doc).ActiveView
    except Exception:
        return None
    px, py = at
    if LAST_NEAR and LAST_NEAR[0] == edge_sub:
        cx, cy = LAST_NEAR[1]
    else:
        cx, cy = px, py
    dx, dy = cx - px, cy - py
    n = (dx * dx + dy * dy) ** 0.5
    tried = set()
    if n > 0.5:
        ux, uy = dx / n, dy / n
        tracks = [(ux, uy)]
    else:
        tracks = [(1, 0), (-1, 0), (0, 1), (0, -1), (0.7, 0.7), (-0.7, 0.7), (0.7, -0.7), (-0.7, -0.7)]
    reach = n + 3.0
    # nearest the edge's line first: each pick is a render of the scene (11 ms on a 200-feature part), and
    # walking out from the pointer took up to 40 of them per click (vd109, 11-20)
    steps = [k * 0.75 for k in range(int(reach / 0.75) + 1)]
    steps.sort(key=lambda s: abs(s - n))
    t0 = time.perf_counter()
    for ux, uy in tracks:
        for step in steps:
            if len(tried) > 4 and time.perf_counter() - t0 > SPOT_BUDGET:
                return None
            for side in (0.0, 1.0, -1.0):
                x = int(round(px + ux * step - uy * side))
                y = int(round(py + uy * step + ux * side))
                if (x, y) in tried:
                    continue
                tried.add((x, y))
                try:
                    info = view.getObjectInfo((x, y))
                except Exception:
                    info = None
                if info and (info.get("Component") or "").rsplit(".", 1)[-1] == leaf:
                    return x, y
                if len(tried) > 40:
                    return None
    return None


class _Observer:
    def __init__(self, owner):
        self.owner = owner

    def setPreselection(self, doc, obj, sub):
        self.owner.preselected(doc, obj, sub)


class FaceHover(QtCore.QObject):
    def __init__(self, shell):
        super().__init__(shell.window)
        self.shell = shell
        self.key = None            # (doc, obj, sub) outlined now
        self.node = None           # the outline's SoSeparator
        self.root = None           # the scene graph holding it
        self.seen = False          # a face preselection came with the last pointer move
        self.outlined = 0          # faces outlined, for checks
        self.restoring = False     # putting FreeCAD's preselection back for a click
        self.held = False          # left button down in the 3D view: a click or a drag
        self.pressed = False       # any button down in the 3D view: no outline while the view turns or pans
        self.edge_first = 0        # hovers where an edge by the pointer won over its face, for checks
        self.won = None            # (doc, obj, face, edge) when the hovered edge won over that face
        self.shift = None          # (widget, dx, dy): a click moved onto the edge that won, until release
        self.sending = False
        self.clicks_moved = 0      # clicks moved onto an edge, for checks
        self.faces_kept = 0        # hovers where a faces-only box got the face under the pointer, for checks
        self.kept = None           # (doc, obj, face) when a faces-only box kept the face over its edge
        self.at = None             # the pointer at the last move in the 3D view (pixels, y up)
        self.direct = None         # (doc, obj, edge, point): an edge FreeCAD's own hover missed, picked by us
        self.pending = None        # (widget, press event copy, direct) while a click on that edge is down
        self.direct_picks = 0      # clicks that picked such an edge, for checks
        self.observer = _Observer(self)
        try:
            Gui.Selection.addObserver(self.observer)
        except Exception:
            self.observer = None
        from . import events
        events.register("facehover", (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease,
                                      QtCore.QEvent.MouseMove, QtCore.QEvent.Leave), self.eventFilter)

    def on(self):
        return bool(self.shell.enabled and enabled() and contextbar.sketch_in_edit() is None)

    def preselected(self, doc, obj, sub):
        if self.restoring or self.held:
            return                              # a drag starts from FreeCAD's preselection
        element = sub.rsplit(".", 1)[-1]
        if not element.startswith(("Face", "Edge", "Vertex")) or not self.on():
            if self.key is not None:
                self.hide()
            return
        if element.startswith("Edge") and self.at is not None and not _edges_wanted(doc, obj, sub):
            face = face_under(doc, obj, sub, self.at)
            if face is not None:
                sub, element = face, face.rsplit(".", 1)[-1]   # the face under the pointer, not its edge
                self.faces_kept += 1
                self.kept = (doc, obj, face)
            else:
                self.kept = None
        else:
            self.kept = None
        self.direct = None
        if element.startswith("Face") and paths.params().GetBool(EDGE_FIRST, True):
            edge = near_edge(doc, obj, sub)
            if edge is not None:
                self.won = (doc, obj, sub, edge)
                sub = edge
                self.edge_first += 1
            else:
                self.won = None
                ray = ray_edge(doc, self.at) if self.at is not None and self.kept is None else None
                if ray is not None and (ray[0], ray[1], ray[2].rsplit(".", 1)[0]) != (doc, obj, sub.rsplit(".", 1)[0]) \
                        and _edges_wanted(ray[0], ray[1], ray[2]):
                    # another part's edge at the pointer (a hole's edge with a shaft in it): the edge
                    doc, obj, sub = ray[0], ray[1], ray[2]
                    self.direct = (doc, obj, sub, ray[3])
                    self.edge_first += 1
        else:
            self.won = None
        self.seen = True
        Gui.Selection.clearPreselection()       # no fill; FreeCAD sets it again on the next move
        if self.key != (doc, obj, sub):
            self.key = (doc, obj, sub)
            QtCore.QTimer.singleShot(0, lambda: self.show(doc, obj, sub))

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent) or not isinstance(obj, QtCore.QObject):
            return False            # PySide hands a split view's layout items here (Four View)
        if self.sending:
            return False
        t = event.type()
        if t == QtCore.QEvent.MouseMove and obj.inherits("QOpenGLWidget"):
            try:
                dpr = obj.devicePixelRatioF() or 1.0
                pos = event.position()
                self.at = (pos.x() * dpr, (obj.height() - pos.y()) * dpr)
            except Exception:
                self.at = None
        t = event.type()
        if t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease) and obj.inherits("QOpenGLWidget"):
            try:
                self.pressed = event.buttons() != QtCore.Qt.NoButton
            except Exception:
                self.pressed = False
        if t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseMove) \
                and obj.inherits("QOpenGLWidget") and self._move_click(obj, event):
            return True
        if t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease) \
                and event.button() == QtCore.Qt.LeftButton and obj.inherits("QOpenGLWidget"):
            # an assembly drags the component under the pointer (FreeCAD's preselection), so the
            # outline leaves the preselection alone until the button comes up
            self.held = t == QtCore.QEvent.MouseButtonPress
        if event.type() == QtCore.QEvent.MouseMove and self.key is not None \
                and obj.inherits("QOpenGLWidget"):
            self.seen = False
            QtCore.QTimer.singleShot(0, self._after_move)
        elif event.type() in (QtCore.QEvent.Leave, QtCore.QEvent.MouseButtonPress) and self.key is not None \
                and obj.inherits("QOpenGLWidget"):
            if event.type() == QtCore.QEvent.MouseButtonPress:
                # FreeCAD picks what is preselected when the button goes down; the outline cleared
                # that preselection, so put it back first or a real click selects nothing
                self.restore()
            # a click picks: the picked edge or face shows FreeCAD's selection colour, not the outline
            QtCore.QTimer.singleShot(0, self.hide)
        return False

    def _move_click(self, widget, event):
        """FreeCAD picks from the pointer, and there the face wins: a click on an edge that won its
        hover goes to the spot a pixel or two away where FreeCAD's pick gives that edge. The release
        (and any move while the button is down) moves with it, so a click stays a click."""
        t = event.type()
        if self.pending is not None or (t == QtCore.QEvent.MouseButtonPress and self.direct is not None):
            done = self._direct_click(widget, event)
            if done is not None:
                return done
        if t == QtCore.QEvent.MouseButtonPress:
            self.shift = None
            if event.button() != QtCore.Qt.LeftButton or event.buttons() != QtCore.Qt.LeftButton:
                return False
            won, kept = self.won, self.kept
            if self.key is None or not self.on():
                return False
            dpr = widget.devicePixelRatioF() or 1.0
            pos = event.position()
            at = (pos.x() * dpr, (widget.height() - pos.y()) * dpr)
            if kept is not None and self.key == kept:
                # a box of faces only kept the face: the click goes out of the edge's pick radius,
                # where FreeCAD's pick gives that face
                spot = face_spot(kept[0], kept[1], kept[2], at)
            else:
                if won is None or self.key[2] != won[3]:
                    return False
                doc, name, face, edge = won
                if near_edge(doc, name, face, at) != edge:
                    return False
                spot = edge_spot(doc, edge, at)
            if spot is None:
                return False
            dx, dy = spot[0] / dpr - pos.x(), (widget.height() - spot[1] / dpr) - pos.y()
            if abs(dx) < 1e-6 and abs(dy) < 1e-6:
                return False
            self.shift = (widget, dx, dy)
            self.clicks_moved += 1
        elif self.shift is None or self.shift[0] is not widget:
            return False
        _w, dx, dy = self.shift
        if t == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
            self.shift = None
        elif t == QtCore.QEvent.MouseMove and not event.buttons() & QtCore.Qt.LeftButton:
            self.shift = None
            return False
        from PySide import QtGui
        d = QtCore.QPointF(dx, dy)
        moved = QtGui.QMouseEvent(t, QtCore.QPointF(event.position()) + d, QtCore.QPointF(event.globalPosition()) + d,
                                  event.button(), event.buttons(), event.modifiers())
        self.sending = True
        try:
            if t == QtCore.QEvent.MouseButtonPress:
                self.held = True
                self.restore()
                QtCore.QTimer.singleShot(0, self.hide)
            QtWidgets.QApplication.sendEvent(widget, moved)
            if t == QtCore.QEvent.MouseButtonRelease:
                self.held = False
        finally:
            self.sending = False
        return True

    def _direct_click(self, widget, event):
        """A click on an edge that FreeCAD's own click would miss (see ray_edge) picks that edge, as
        FreeCAD's click picks: the pick is cleared first unless Ctrl (Shift) is held, and Ctrl on a
        picked edge takes it off. A drag from there is FreeCAD's own. None: not handled here."""
        from PySide import QtGui
        t = event.type()
        if t == QtCore.QEvent.MouseButtonPress:
            self.pending = None
            direct = self.direct
            mods = event.modifiers() & (QtCore.Qt.ShiftModifier | QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier)
            if direct is None or event.button() != QtCore.Qt.LeftButton or event.buttons() != QtCore.Qt.LeftButton \
                    or mods & QtCore.Qt.AltModifier or not self.on() or (self.key is not None and not _same(self.key, direct)):
                return None
            dpr = widget.devicePixelRatioF() or 1.0
            pos = event.position()
            ray = ray_edge(direct[0], (pos.x() * dpr, (widget.height() - pos.y()) * dpr))
            if ray is None or not _same(ray, direct):
                return None
            copy = QtGui.QMouseEvent(t, QtCore.QPointF(pos), QtCore.QPointF(event.globalPosition()),
                                     event.button(), event.buttons(), event.modifiers())
            self.pending = (widget, copy, tuple(ray))
            return True
        if self.pending is None or self.pending[0] is not widget:
            return None
        _w, press, direct = self.pending
        if t == QtCore.QEvent.MouseMove:
            if not event.buttons() & QtCore.Qt.LeftButton:
                self.pending = None
                return None
            if (event.position() - press.position()).manhattanLength() <= 4:
                return True
            self.pending = None                 # a drag: FreeCAD's, from where the button went down
            self.sending = True
            try:
                if self.key is not None:
                    self.restore()
                QtWidgets.QApplication.sendEvent(widget, press)
            finally:
                self.sending = False
            return None
        if t == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
            self.pending = None
            doc, obj, sub, pnt = direct
            add = bool(press.modifiers() & (QtCore.Qt.ShiftModifier | QtCore.Qt.ControlModifier))
            try:
                owner = App.getDocument(doc).getObject(obj)
                self.restoring = True           # FreeCAD's click has the clicked entity preselected
                try:
                    Gui.Selection.setPreselection(owner, sub, *pnt)
                finally:
                    self.restoring = False
                if add and Gui.Selection.isSelected(owner, sub, 0):
                    Gui.Selection.removeSelection(owner, sub)
                else:
                    if not add:
                        Gui.Selection.clearSelection()
                    Gui.Selection.addSelection(doc, obj, sub, *pnt)
                self.direct_picks += 1
            except Exception as _fw_err:
                _fw_log("facehover.py:direct", _fw_err)
            QtCore.QTimer.singleShot(0, self.hide)
            return True
        return None

    def restore(self):
        doc, obj, sub = self.key
        self.restoring = True
        try:
            Gui.Selection.setPreselection(App.getDocument(doc).getObject(obj), sub)
        except Exception as _fw_err:
            _fw_log("facehover.py:519", _fw_err)
        finally:
            self.restoring = False

    def _after_move(self):
        if not self.seen or self.key is None:
            if self._ray_hover():
                return
        if not self.seen:
            self.hide()

    def _ray_hover(self):
        """FreeCAD's hover found nothing, yet its view's pick finds an edge at the pointer (a hole's
        edge with a shaft in it, in an assembly): outline that edge; a click picks it."""
        if self.at is None or self.held or not self.on() or not paths.params().GetBool(EDGE_FIRST, True):
            return False
        ray = ray_edge(None, self.at)
        if ray is None or not _edges_wanted(*ray[:3]):
            return False
        self.won = self.kept = None
        self.direct = tuple(ray)
        self.seen = True
        if self.key != tuple(ray[:3]):
            self.key = tuple(ray[:3])
            self.show(*ray[:3])
        return True

    def show(self, doc, obj, sub):
        if self.key != (doc, obj, sub):
            return                              # the pointer moved on already
        if self.pressed and not self.held:

            # finding the outline's seen stretches cost 0.2 s at each turn's start on a 150-part assembly
            self.key = None
            return
        self.hide()
        corner = sub.rsplit(".", 1)[-1].startswith("Vertex")
        try:
            from pivy import coin
            view = Gui.getDocument(doc).ActiveView
            if corner:
                # FreeCAD lights a preselected corner too, so orange came out yellow (#ffb50a):
                # the corner is drawn as an unlit dot in the exact colour, as edges are
                import Part
                lines = [[Part.getShape(App.getDocument(doc).getObject(obj), sub, needSubElement=True).Point]]
            else:
                lines = _seen_parts(view, _lines(doc, obj, sub))
                if not lines and sub.rsplit(".", 1)[-1].startswith("Edge") and self.at is not None:
                    # a curve lying on a face: the face's pick hides it, the ray's records show it
                    ray = self.direct if self.direct is not None and _same(self.direct, (doc, obj, sub)) \
                        else ray_edge(doc, self.at)
                    if ray is not None and _same(ray, (doc, obj, sub)):
                        self.direct = tuple(ray)
                        lines = _lines(doc, obj, sub)
            root = view.getSceneGraph()
        except Exception:
            return
        if not lines:
            return
        node = coin.SoSeparator()
        node.setName("SWFaceHoverOutline")
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        colour = coin.SoBaseColor()
        colour.rgb.setValue(*_colour())
        draw = coin.SoDrawStyle()
        draw.lineWidth = WIDTH * Gui.getMainWindow().devicePixelRatioF()
        draw.pointSize = POINT_PX * Gui.getMainWindow().devicePixelRatioF()
        depth = coin.SoDepthBuffer()
        depth.test = False
        coords = coin.SoCoordinate3()
        points = [p for line in lines for p in line]
        coords.point.setValues(0, len(points), points)
        if corner:
            strips = coin.SoPointSet()
            strips.numPoints.setValue(len(points))
        else:
            strips = coin.SoLineSet()
            strips.numVertices.setValues(0, len(lines), [len(line) for line in lines])
        for child in (pick, light, colour, draw, depth, coords, strips):
            node.addChild(child)
        root.addChild(node)
        self.node, self.root, self.key = node, root, (doc, obj, sub)
        self.outlined += 1
        self._watch_pointer()

    def _watch_pointer(self):
        """While an outline shows, a light check that the pointer is still on that face or edge. Mouse moves
        do not always reach the view (Windows, a pointer that jumps off the window), and then nothing else
        would take the outline away."""
        t = getattr(self, "_pointer_timer", None)
        if t is None:
            t = QtCore.QTimer(Gui.getMainWindow())
            t.setObjectName("FW_FaceHoverPointer")
            t.setInterval(150)
            t.timeout.connect(self._check_pointer)
            self._pointer_timer = t
        if not t.isActive():
            t.start()

    def _check_pointer(self):
        if self.key is None or self.held:
            if self.key is None:
                self._pointer_timer.stop()
            return
        from PySide import QtGui
        pos = QtGui.QCursor.pos()
        w = QtWidgets.QApplication.widgetAt(pos)
        while w is not None and not w.inherits("QOpenGLWidget"):
            w = w.parentWidget() if not w.isWindow() else None
        if w is None:
            self.hide()                          # off the 3D view
            return
        try:
            doc = self.key[0]
            view = Gui.getDocument(doc).ActiveView
            local = w.mapFromGlobal(pos)
            dpr = w.devicePixelRatioF()
            info = view.getObjectInfo((int(local.x() * dpr), int((w.height() - local.y()) * dpr)))
        except Exception:
            return
        if not info:
            self.hide()                          # off the model
            return
        leaf = (info.get("SubName") or info.get("Component") or "").rsplit(".", 1)[-1]
        mine = str(self.key[2]).rsplit(".", 1)[-1]
        if mine.startswith("Edge") and not leaf.startswith("Edge"):
            # an edge FreeCAD's one pick misses (a hole's edge with a shaft in it, a sketch curve on a face)
            ray = ray_edge(doc, (local.x() * dpr, (w.height() - local.y()) * dpr))
            if ray is not None and _same(ray, self.key):
                return
        if leaf.startswith("Face") and mine.startswith("Edge"):
            # an edge that won over its face: still the one while the pointer stays by it
            sub = str(self.key[2])[:len(str(self.key[2])) - len(mine)] + leaf
            try:
                again = near_edge(doc, self.key[1], sub, (local.x() * dpr, (w.height() - local.y()) * dpr))
            except Exception:
                again = None
            if again == self.key[2]:
                return
        if leaf.startswith("Edge") and mine.startswith("Face"):
            # a Selection Filter that refuses the edge FreeCAD finds there: the face behind it stays

            try:
                from . import selfilter
                top = App.getDocument(doc).getObject(self.key[1])
                path = str(self.key[2])[:len(str(self.key[2])) - len(mine)]
                if selfilter.state().filtering() and not selfilter.allows(top, path + leaf):
                    return
            except Exception as _fw_err:
                _fw_log("facehover.py:filter", _fw_err)
        if leaf and leaf != mine:
            self.hide()                          # on another face or edge: FreeCAD's preselection outlines that one

    def hide(self):
        t = getattr(self, "_pointer_timer", None)
        if t is not None and self.node is not None and not self.held:
            t.stop()
        if self.node is not None and self.root is not None:
            try:
                self.root.removeChild(self.node)
            except Exception as _fw_err:
                _fw_log("facehover.py:624", _fw_err)
        had = self.key is not None
        self.node = self.root = self.key = None
        if had:
            QtCore.QTimer.singleShot(0, self._tip_follows)

    def _tip_follows(self):
        if self.key is None:
            try:
                from . import edgetip
                if edgetip._tip is not None:
                    edgetip._tip.outline_gone()
            except Exception as _fw_err:
                _fw_log("facehover.py:tip", _fw_err)

    def remove(self):
        self.hide()
        t = getattr(self, "_pointer_timer", None)
        if t is not None:
            t.stop()
        from . import events
        events.unregister("facehover")
        if self.observer is not None:
            try:
                Gui.Selection.removeObserver(self.observer)
            except Exception as _fw_err:
                _fw_log("facehover.py:638", _fw_err)
            self.observer = None
