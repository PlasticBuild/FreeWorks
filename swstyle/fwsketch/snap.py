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


import math
import time

import FreeCAD as App
import Part

from PySide import QtCore, QtWidgets

from .vec import sub, add, mul, dot, cross, length, dist, unit
from . import inference as I
from . import guides as G
from . import model as M

SNAP_GROUP = "User parameter:BaseApp/Preferences/Mod/Sketcher/Snap"

# Winners
DISABLED, FREE, SUPPRESSED = "Disabled", "Free", "Suppressed"
SKETCH_POINT, SKETCH_CURVE, AXIS, AXIS_GRID, GRID = "SketchPoint", "SketchCurve", "Axis", "AxisGrid", "Grid"
MIDPOINT, QUADRANT, INTERSECTION = "Midpoint", "Quadrant", "Intersection"
LINE_MIDPOINT = "LineMidpoint"   # the line being drawn has a woken point (or the origin) at its middle
AXIS_ALIGN, AXIS_ALIGN_GRID, ALIGNMENT, EXTENSION = "AxisAlign", "AxisAlignGrid", "Alignment", "Extension"
PARALLEL, PERPENDICULAR = "Parallel", "Perpendicular"
TANGENT_POINT, NORMAL_POINT = "TangentPoint", "NormalPoint"
ARC_TANGENT, ARC_RADIAL, ANGLE_STEP = "ArcTangent", "ArcRadial", "AngleStep"

MODEL_BASE = -1000000  # snap targets on the 3D model: geo ids from here down
MAX_WOKEN = 3
ENTRIES_MAX_AGE = 2.0      # seconds an unchanged sketch's entries are kept between moves (no change watch)
ENTRIES_WATCHED_AGE = 30.0  # the same while the change watch below tells of every geometry change
RECENT_COUNT = 4


def is_model_geo(geo):
    return geo <= MODEL_BASE


# Change watch: an App document observer that counts the writes to any sketch's Geometry or
# ExternalGeo (a solve, a drag, an expression's rebuild, Undo: all of them write the property). With
# it entries() knows an unchanged sketch without reading it, so a dense sketch is not read again
# every ENTRIES_MAX_AGE seconds (3000 entities: a 28 ms pointer move every 2 s, and the shape,
# grid and guide caches built on the list went with it).
_CHANGES = [0]
_change_watch = [None]


class _ChangeWatch:
    def slotChangedObject(self, obj, prop):
        if prop == "Geometry" or prop == "ExternalGeo":
            _CHANGES[0] += 1

    def slotUndoDocument(self, doc):       # Undo and Redo put the properties back without the signal above
        _CHANGES[0] += 1

    def slotRedoDocument(self, doc):
        _CHANGES[0] += 1

    def slotDeletedDocument(self, doc):
        _CHANGES[0] += 1


def watch_changes():
    """Starts the change watch once. False when FreeCAD refuses the observer: entries() then
    keeps its short age."""
    if _change_watch[0] is None:
        try:
            w = _ChangeWatch()
            App.addDocumentObserver(w)
            _change_watch[0] = w
        except Exception as error:
            App.Console.PrintLog("fwsketch: no change watch for the snap entries: %s\n" % error)
            _change_watch[0] = False
    return bool(_change_watch[0])


class Decision:
    def __init__(self, position, winner=FREE):
        self.position = position
        self.winner = winner
        self.geo = I.GEO_UNDEF
        self.pos = I.NONE
        self.geo2 = I.GEO_UNDEF
        self.aligned_points = []   # (geo, pos, horizontal) from alignment guides
        self.length_snapped = False

    def __repr__(self):
        return "Decision(%s at (%.4g, %.4g) geo=%s pos=%s geo2=%s)" % (
            self.winner, self.position[0], self.position[1], self.geo, self.pos, self.geo2)


class Params:
    """The snap preferences, read once per tool start (Mod/Sketcher/Snap)."""

    def __init__(self):
        p = App.ParamGet(SNAP_GROUP)
        self.snap = p.GetBool("Snap", True)
        objects = p.GetBool("SnapToObjects", True)     # the older single switch: the default of each below

        self.endpoints = p.GetBool("SnapToEndPoints", objects)        # End points and sketch points
        self.centers = p.GetBool("SnapToCenterPoints", objects)       # Center Points
        self.nearest = p.GetBool("SnapToNearest", objects)            # Nearest (on the curve)
        self.tangent = p.GetBool("SnapToTangent", objects)            # Tangent
        self.perpendicular = p.GetBool("SnapToPerpendicular", p.GetBool("SnapToParallels", True))
        self.parallel = p.GetBool("SnapToParallel", p.GetBool("SnapToParallels", True))
        self.hv_lines = p.GetBool("SnapToHVLines", True)              # Horizontal/vertical lines
        self.grid_shown_only = p.GetBool("SnapToGridWhenShown", True)  # Snap only when grid is displayed
        self.grid = p.GetBool("SnapToGrid", False)
        self.angle = math.fmod(math.radians(p.GetFloat("SnapAngle", 45.0)), 2 * math.pi)
        self.radius = max(1, p.GetInt("SnapRadius", 5))          # logical pixels
        self.filter = I.Filter(self.endpoints or self.centers, p.GetBool("SnapToMidpoints", True),
                               p.GetBool("SnapToQuadrants", True), p.GetBool("SnapToIntersections", True))
        # fix235: Parallel, Horizontal/Vertical lines, Horizontal/Vertical to points and Angle count
        # too: with one of them alone (its Quick Snap) the pointer must still wake the lines, and
        # the relation it shows must be added
        self.objects = objects and (self.endpoints or self.centers or self.nearest or self.tangent
                                    or self.perpendicular or self.filter.midpoints or self.filter.quadrants
                                    or self.filter.intersections or self.parallel or self.hv_lines
                                    or p.GetBool("SnapToAlignments", True) or p.GetBool("SnapToAngle", True))
        self.model = p.GetBool("SnapToModel", True)
        self.guides = G.GuideFilter(True, self.parallel or self.perpendicular, p.GetBool("SnapToAlignments", True),
                                    p.GetBool("SnapToExtensions", True), p.GetBool("SnapToAngle", True))
        self.extension_adds_relation = p.GetBool("ExtensionAddsRelation", False)
        self.alignment_adds_relation = p.GetBool("AlignmentAddsRelation", False)
        self.length = p.GetBool("SnapToLength", True)
        self.midpoint_guides = p.GetBool("MidpointGuides", True)

        # not; parallel, perpendicular, tangent and the angle steps keep the wider 1.5 degrees
        self.hv_angle = math.radians(p.GetFloat("AxisBandAngle", 0.5))
        self.band_angle = math.radians(p.GetFloat("DirectionBandAngle", 1.5))
        self.band_pixels = p.GetFloat("AxisBandPixels", 1.5)
        self.min_direction_pixels = p.GetFloat("DirectionMinPixels", 20.0)


def toggle_snaps():
    ""

    p = App.ParamGet(SNAP_GROUP)
    on = not p.GetBool("Snap", True)
    p.SetBool("Snap", on)
    try:
        from . import toolbase
        running = toolbase.active()
        snapper = getattr(running, "snapper", None) if running is not None else None
        if snapper is not None:
            snapper.p.snap = on
    except Exception as _fw_err:
        _fw_log("fwsketch/snap.py:165", _fw_err)
    try:
        import FreeCADGui as Gui
        Gui.getMainWindow().statusBar().showMessage("Sketch snaps %s" % ("on" if on else "off"), 3000)
    except Exception as _fw_err:
        _fw_log("fwsketch/snap.py:170", _fw_err)
    return on


def refresh_params():
    ""

    try:
        from . import toolbase
        running = toolbase.active()
        snapper = getattr(running, "snapper", None) if running is not None else None
        if snapper is not None:
            snapper.p = Params()
            snapper._entries_cache = None
    except Exception as _fw_err:
        _fw_log("fwsketch/snap.py:refresh_params", _fw_err)


def grid_shown():
    """The sketch's grid is on screen (Snap only when grid is displayed)."""
    try:
        import FreeCADGui as Gui
        vp = Gui.ActiveDocument.getInEdit()
        return bool(getattr(vp, "ShowGrid", True))
    except Exception:
        return True


def modifiers():
    return QtWidgets.QApplication.queryKeyboardModifiers()


FORCED = [0]     # >0: a typed (numeric input) point is being placed: no snaps, no relations (fix65)


def inference_suppressed():
    return bool(FORCED[0]) or bool(modifiers() & QtCore.Qt.ControlModifier)


def shift_held():
    return bool(modifiers() & QtCore.Qt.ShiftModifier)


SHOWN_SOLIDS_MAX = 12


def _shown_solids(sketch):
    ""



    out = []
    try:
        objects = sketch.Document.Objects
    except Exception:
        return out
    for obj in objects:
        try:
            if obj == sketch or not obj.Visibility or not hasattr(obj, "Shape") \
                    or obj.isDerivedFrom("Sketcher::SketchObject") or obj.isDerivedFrom("Part::Part2DObject") \
                    or obj.isDerivedFrom("Part::Datum") or obj.isDerivedFrom("App::Origin") \
                    or obj.isDerivedFrom("App::OriginFeature"):
                continue
            if any(not p.isDerivedFrom("App::DocumentObjectGroup") and not hasattr(p, "FWExtRefOf")
                   for p in obj.InList if p != sketch):
                continue           # used by a later feature: that one is the solid shown
            if obj.getParentGeoFeatureGroup() is not None:
                continue
            shape = obj.Shape
            if shape.isNull() or not shape.Faces:
                continue
        except Exception:
            continue
        out.append(obj)
        if len(out) >= SHOWN_SOLIDS_MAX:
            break
    return out


class Snapper:
    def __init__(self, sketch, params=None, grid_size=None, view_box=None):
        self.sketch = sketch
        self.p = params or Params()
        self.grid_size = grid_size      # callable -> sketch units, or None
        self.view_box = view_box        # callable -> (xmin, ymin, xmax, ymax) or None
        self.reference = None           # the tool's anchor (previous click) or None
        self.excluded = set()           # geo ids (and axes) that are no snap target
        self.pixel_size = 0.0           # sketch units per logical pixel
        self.reset()

    # --- state ----------------------------------------------------------------------------
    def reset(self):
        self.woken = []
        self.near_curve = I.GEO_UNDEF
        self.last = None
        self.last_input = None
        self.current_geometry = []
        self.current_direction = G.Guide()
        self.current_candidates = []
        self.last_guides = G.GuideResult((0.0, 0.0))
        self._model_found = False
        self._model_targets = []        # (source object, ModelElement)

    def set_reference(self, point):
        self.reference = point
        self.mirror_midpoint = False    # the line tool turns it on for a free line's second point

    def sketch_changed(self):
        """Geometry or references were added: the model targets are read again."""
        self._model_found = False

    # --- geometry ---------------------------------------------------------------------------
    def model_targets(self):
        if self._model_found:
            return self._model_targets
        self._model_found = True
        self._model_targets = []
        sk = self.sketch
        if not self.p.model or sk is None:
            return self._model_targets
        candidates = [link[0] for link in (sk.AttachmentSupport or [])]
        body = sk.getParentGeoFeatureGroup() if hasattr(sk, "getParentGeoFeatureGroup") else None
        if body is not None and body.TypeId == "PartDesign::Body" and body.Tip is not None:
            candidates.append(body.Tip)
        outside = []
        if body is None:
            candidates += _shown_solids(sk)
        elif body.TypeId == "PartDesign::Body":

            # hidden ExtRef binder (convertentities.binder_for), so the relation still follows it
            outside = [o for o in _shown_solids(sk) if o is not body]
            candidates += outside
        placement = sk.Placement
        sources = []
        for obj in candidates:
            if obj is None or obj == sk or obj in sources or not hasattr(obj, "Shape") \
                    or obj.isDerivedFrom("Part::Datum") or obj.isDerivedFrom("App::Origin") \
                    or obj.isDerivedFrom("App::OriginFeature"):
                continue
            sources.append(obj)
            try:
                elements = M.model_elements(obj.Shape, sk.getGlobalPlacement() if obj in outside else placement)
            except Exception as e:  # a shape the kernel cannot walk: no targets from it
                App.Console.PrintLog("fwsketch: no snap targets on %s: %s\n" % (obj.Name, e))
                continue
            for el in elements:
                if not any(M.same_geometry(t[1].geometry, el.geometry) for t in self._model_targets):
                    self._model_targets.append((obj, el))
        return self._model_targets

    def entries(self):
        """(geo id, geometry) the inference engine sees: sketch geometry, externals, the model last.
        Kept between pointer moves while the sketch is unchanged (sk.Geometry copies every
        entity on each read: a dense sketch would cost a frame per move); read again after any
        change (the change watch counts them) and at least every ENTRIES_WATCHED_AGE seconds;
        without the watch every ENTRIES_MAX_AGE seconds."""
        sk = self.sketch
        watched = watch_changes()
        try:
            doc = sk.Document
            if watched:
                key = (_CHANGES[0], sk.GeometryCount, sk.ConstraintCount, doc.UndoCount, doc.RedoCount,
                       tuple(sorted(self.excluded)), id(sk), len(self.model_targets()))
            else:
                key = (sk.GeometryCount, sk.ConstraintCount, len(sk.ExternalGeo), doc.UndoCount, doc.RedoCount,
                       tuple(sorted(self.excluded)), id(sk), len(self.model_targets()))
        except Exception:
            key = None
        cached = getattr(self, "_entries_cache", None)
        now = time.monotonic()
        if key is not None and cached is not None and cached[0] == key \
                and now - cached[1] < (ENTRIES_WATCHED_AGE if watched else ENTRIES_MAX_AGE):
            return cached[2]
        out = self._read_entries()
        self._entries_cache = (key, now, out)
        return out

    def _read_entries(self):
        sk = self.sketch
        out = []
        hidden = self._spline_poles()
        for i, g in enumerate(sk.Geometry):
            if i not in self.excluded and i not in hidden:
                out.append((i, g))
        ext = sk.ExternalGeo
        for i in range(2, len(ext)):
            if -i - 1 not in self.excluded:
                out.append((-i - 1, ext[i]))
        for i, t in enumerate(self.model_targets()):
            out.append((MODEL_BASE - i, t[1].geometry))
        return out

    def _spline_poles(self):
        ""

        sk = self.sketch
        key = (sk.GeometryCount, sk.ConstraintCount)
        cached = getattr(self, "_poles_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        poles = set()
        try:
            geos = sk.Geometry
            for c in sk.Constraints:
                if c.Type == "InternalAlignment" and 0 <= c.First < len(geos) and 0 <= c.Second < len(geos) \
                        and isinstance(geos[c.First], Part.Circle) and isinstance(geos[c.Second], Part.BSplineCurve):
                    poles.add(c.First)
            from . import splineedit
            for i, g in enumerate(geos):
                if i not in poles and isinstance(g, Part.LineSegment) and splineedit._is_hidden(g):
                    poles.add(i)
                elif i not in poles and g.hasExtensionOfName("fw-helper"):
                    poles.add(i)        # a hidden helper (fwsketch/helpers.py, review 1119)
        except Exception as _fw_err:
            _fw_log("fwsketch/snap.py:368", _fw_err)
        self._poles_cache = (key, poles)
        return poles

    def geometry(self, geo):
        if is_model_geo(geo):
            i = MODEL_BASE - geo
            t = self.model_targets()
            return t[i][1].geometry if 0 <= i < len(t) else None
        if geo == I.GEO_UNDEF or geo in (I.H_AXIS, I.V_AXIS):
            return None
        if geo >= 0:
            return self.sketch.Geometry[geo] if geo < len(self.sketch.Geometry) else None
        ext = self.sketch.ExternalGeo
        i = -geo - 1
        return ext[i] if i < len(ext) else None

    def resolve_model_reference(self, geo, pos):
        """(sketch geo id, pos) of the external reference for point pos of model target geo,
        adding the reference when missing. None when it cannot be referenced."""
        if not is_model_geo(geo):
            return None
        i = MODEL_BASE - geo
        t = self.model_targets()
        if not 0 <= i < len(t):
            return None
        obj, el = t[i]
        if M.is_silhouette(el):

            # (silhouette.py, as Add Relations uses) stands in for it
            return self._silhouette_reference(obj, el, pos)
        name, rpos = M.reference_target(el, pos)
        ref = M.add_reference(self.sketch, obj, name)
        return None if ref is None else (ref, rpos)

    def _silhouette_reference(self, obj, el, pos):
        try:
            from . import silhouette
            head = el.name[len(M.SILHOUETTE):]
            face = int(head.split("_")[0]) - 1
            g = el.geometry
            sk = self.sketch
            normal = silhouette._sketch_normal(sk)
            kind = type(obj.Shape.Faces[face].Surface).__name__
            to_sketch = sk.Placement.inverse()
            # the outline (side 0 or 1) that is this element: the one lying on it in the sketch
            probe = I.point_of(g, I.MID) if type(g) is Part.Circle else \
                ((g.StartPoint.x + g.EndPoint.x) / 2.0, (g.StartPoint.y + g.EndPoint.y) / 2.0)
            side = None
            for k in (0, 1):
                e = silhouette.outline(obj.Shape.Faces[face], kind, k, normal)
                if e is None:
                    continue
                m = to_sketch.multVec(e.valueAt(0.5 * (e.FirstParameter + e.LastParameter)))
                c = to_sketch.multVec(e.Curve.Center) if kind == "Sphere" else m
                if dist((c.x, c.y), probe) <= 1e-6 * (1.0 + length(probe)):
                    side = k
                    break
            if side is None:
                return None
            sil = silhouette.make(sk, obj, face, side)
            ref = M.add_reference(sk, sil, "Edge1")
            if ref is None:
                return None
            if pos in (I.START, I.END) and type(g) is not Part.Circle:
                want = g.StartPoint if pos == I.START else g.EndPoint
                ext = self.geometry(ref)
                if ext is not None and hasattr(ext, "StartPoint"):
                    a, b = ext.StartPoint, ext.EndPoint
                    pos = I.START if (a - want).Length <= (b - want).Length else I.END
            return ref, pos
        except Exception as _fw_err:
            _fw_log("fwsketch/snap.py:silhouette", _fw_err)
            return None

    def wake(self, geo):
        if geo in self.woken:
            self.woken.remove(geo)
        self.woken.insert(0, geo)
        del self.woken[MAX_WOKEN:]

    def recent(self):
        entries = self.current_geometry
        kept = getattr(self, "_recent_kept", None)
        if kept is not None and kept[0] is entries and kept[1] == len(entries):
            return list(kept[2])        # the same entries list (held here, so it cannot be another one): the same answer
        ids = sorted((e[0] for e in entries if e[0] >= 0 and e[1] is not None), reverse=True)
        out = ids[:RECENT_COUNT]
        self._recent_kept = (entries, len(entries), out)
        return list(out)

    # --- the band -----------------------------------------------------------------------------
    def axis_band(self, direction):
        """'Horizontal', 'Vertical' or None for a drawing direction, as the snap and the H/V
        relation share it."""
        n = length(direction)
        if not n > 0.0 or not self.p.hv_lines:
            return None          # Horizontal/vertical lines off: no H/V snap and no H/V relation
        screen = self.pixel_size > 0.0
        if screen and n < self.p.min_direction_pixels * self.pixel_size:
            return None
        band = self.p.band_pixels * self.pixel_size if screen else 0.0
        tol = self.p.hv_angle
        angle = math.atan2(abs(direction[1]), abs(direction[0]))
        nearer_h = abs(direction[1]) <= abs(direction[0])
        if angle <= tol or (nearer_h and abs(direction[1]) <= band):
            return "Horizontal"
        if math.pi / 2 - angle <= tol or (not nearer_h and abs(direction[0]) <= band):
            return "Vertical"
        return None

    # --- queries ----------------------------------------------------------------------------
    def guide_query(self, cursor, allow_point=True, allow_edge=True, allow_angle=True):
        p = self.p
        q = G.GuideQuery(cursor, p.radius * self.pixel_size, angle_tolerance=p.band_angle,
                         anchor=self.reference if allow_angle else None, woken=self.woken,
                         align_all_points=False, recent=self.recent(),
                         filter=G.GuideFilter(p.guides.directions, p.guides.parallels, p.guides.alignments,
                                              p.guides.extensions, p.guides.angles),
                         point_filter=p.filter, axis_band=p.band_pixels * self.pixel_size,
                         min_direction_length=p.min_direction_pixels * self.pixel_size,
                         angle_step=p.angle if p.guides.angles else 0.0)
        q.hv_tolerance = p.hv_angle
        if not q.has_anchor:
            q.filter.directions = False
        if not p.objects:
            q.filter.parallels = q.filter.alignments = q.filter.extensions = False
        if not allow_point:
            q.filter.alignments = False
        if not allow_edge:
            q.filter.extensions = False
        return q

    # --- the decision -----------------------------------------------------------------------
    def snap(self, cursor, pixel_size, allow_point=True, allow_edge=True, allow_angle=True, allow_grid=True):
        self.pixel_size = pixel_size
        self.last_input = cursor
        d = self._find(cursor, allow_point, allow_edge, allow_angle, allow_grid)
        if allow_point and d.winner not in (SKETCH_POINT, MIDPOINT, QUADRANT, INTERSECTION, TANGENT_POINT, NORMAL_POINT,
                                            DISABLED, SUPPRESSED):
            self._on_a_point(d)
        self.last = d
        return d

    def _on_a_point(self, d):
        ""


        try:
            tiny = max(1e-7, 1e-3 * self.pixel_size)
            q = I.Query(d.position, tiny, filter=self.p.filter)
            q.woken = list(self.woken)
            c = I.find_point_candidate(self.current_geometry, q)
            if c is None or not c.valid() or dist(c.position, d.position) > tiny:
                return False
            if c.kind == I.VERTEX and not (self.p.centers if c.pos == I.MID else self.p.endpoints):
                return False
            d.winner = {I.VERTEX: SKETCH_POINT, I.MIDPOINT: MIDPOINT, I.QUADRANT: QUADRANT,
                        I.INTERSECTION: INTERSECTION}[c.kind]
            d.geo, d.pos, d.geo2 = c.geo, c.pos, c.geo2
            d.position = c.position
            d.aligned_points = []
            return True
        except Exception as _fw_err:
            _fw_log("fwsketch/snap.py:on a point", _fw_err)
            return False

    def _find(self, cursor, allow_point, allow_edge, allow_angle, allow_grid):
        p = self.p
        self.near_curve = I.GEO_UNDEF
        self.current_geometry = []
        self.current_direction = G.Guide()
        self.current_candidates = []
        self.last_guides = G.GuideResult(cursor)
        if not p.snap:
            return Decision(cursor, DISABLED)
        if inference_suppressed():
            return Decision(cursor, SUPPRESSED)

        self.current_geometry = self.entries()
        anchored = allow_angle and self.reference is not None
        if anchored:
            q = self.guide_query(cursor, allow_point, allow_edge, allow_angle)
            self.current_direction = G.find_direction_guide(self.current_geometry, q)
            if self.current_direction.valid() and not self._kind_allowed(self.current_direction):
                self.current_direction = G.Guide()
            self.current_candidates = [c for c in G.candidate_directions(self.current_geometry, q)
                                       if self._kind_allowed(c)]

        d = Decision(cursor, FREE)
        if (allow_point or allow_edge) and p.objects:
            found = self._snap_to_object(cursor, d, allow_point, allow_edge)
            if anchored and allow_point and self._mirror_midpoint(cursor, d):
                return d
            if found:
                return d

        lock_x = lock_y = False
        if d.winner == FREE:
            guides = G.find_guides(self.current_geometry, self.guide_query(cursor, allow_point, allow_edge, allow_angle))
            if guides.valid() and not self._kind_allowed(guides.direction()):
                guides = G.GuideResult(cursor)
            if guides.valid():
                self.last_guides = guides
                pos = guides.position
                for g in guides.guides:
                    if g.kind in (G.ALIGN_H, G.ALIGN_V) and g.pos != I.NONE:
                        d.aligned_points.append((g.geo, g.pos, g.kind == G.ALIGN_H))
                first = guides.guides[0]
                full = guides.crossing
                direction = guides.direction()
                if direction is not None:
                    k = direction.kind
                    if k in (G.PARALLEL, G.PERPENDICULAR, G.ARC_TANGENT, G.ARC_RADIAL, G.ANGLE_STEP):
                        d.winner = {G.PARALLEL: PARALLEL, G.PERPENDICULAR: PERPENDICULAR, G.ARC_TANGENT: ARC_TANGENT,
                                    G.ARC_RADIAL: ARC_RADIAL, G.ANGLE_STEP: ANGLE_STEP}[k]
                        d.geo, d.pos = direction.geo, direction.pos
                        full = True
                    else:
                        d.winner = AXIS_ALIGN
                else:
                    d.winner = EXTENSION if first.kind == G.EXTENSION else ALIGNMENT
                    d.geo, d.pos = first.geo, first.pos
                    if len(guides.guides) > 1:
                        d.geo2 = guides.guides[1].geo
                    full = full or first.kind == G.EXTENSION
                if full and allow_point and self._aligned_on_point(guides, d, pos):
                    return d      # level with and plumb to the same point: that point (Coincident)
                if full:
                    d.position = pos
                    self._snap_length(d, allow_angle)
                    return d
                if abs(first.direction[0]) <= abs(first.direction[1]):
                    lock_x = True
                else:
                    lock_y = True
                d.position = pos

        if self._snap_length(d, allow_angle):
            return d

        if allow_grid and p.grid and self.grid_size and (not p.grid_shown_only or grid_shown()):
            step = self.grid_size()
            if step and step > 0.0:
                from . import sysopts
                step = step / sysopts.snap_points_per_minor()
                x, y = d.position
                gx, gy = round(x / step) * step, round(y / step) * step
                tol = step / 5
                snapped = False
                if abs(x - gx) < tol and not lock_x:
                    x, snapped = gx, True
                if abs(y - gy) < tol and not lock_y:
                    y, snapped = gy, True
                if snapped:
                    d.winner = {AXIS: AXIS_GRID, AXIS_ALIGN: AXIS_ALIGN_GRID, ALIGNMENT: ALIGNMENT}.get(d.winner, GRID)
                    d.position = (x, y)
        return d

    def _aligned_on_point(self, guides, d, pos):
        ""


        h = [(g.geo, g.pos) for g in guides.guides if g.kind == G.ALIGN_H and g.pos != I.NONE]
        v = [(g.geo, g.pos) for g in guides.guides if g.kind == G.ALIGN_V and g.pos != I.NONE]
        both = [k for k in h if k in v]
        if not both or not self.p.endpoints:
            return False
        geo, ppos = both[0]
        try:
            q = I.point_of(self.geometry(geo), ppos)
        except Exception:
            return False
        if q is None or dist(q, pos) > 1e-6 * (1.0 + length(q)) + 1e-9:
            return False
        d.winner, d.geo, d.pos, d.geo2 = SKETCH_POINT, geo, ppos, I.GEO_UNDEF
        d.position = q
        d.aligned_points = []
        return True

    def _kind_allowed(self, direction):
        """False for a direction guide whose snap is switched off (Parallel, Perpendicular, Tangent,
        Horizontal/vertical lines) in Options > Relations/Snaps."""
        if direction is None:
            return True
        k = direction.kind
        if k == G.PARALLEL:
            return self.p.parallel
        if k == G.PERPENDICULAR:
            return self.p.perpendicular
        if k == G.ARC_TANGENT:
            return self.p.tangent
        if k in (G.HORIZONTAL, G.VERTICAL):
            return self.p.hv_lines
        return True

    def _snap_length(self, d, allow_angle):
        p = self.p
        if not allow_angle or not p.length or self.reference is None or not shift_held():
            return False
        if d.winner not in (FREE, AXIS, AXIS_ALIGN, PARALLEL, PERPENDICULAR, ARC_TANGENT, ARC_RADIAL, ANGLE_STEP):
            return False
        if self.last_guides.crossing:
            return False
        step = self.grid_size() if self.grid_size else 0.0
        along = sub(d.position, self.reference)
        n = length(along)
        if d.winner == AXIS and min(abs(along[0]), abs(along[1])) > 1e-9:
            return False          # extapps162: a line along a sketch axis is snapped to a length (its start is on that axis); one that only meets the axis keeps it
        if not step or not step > 0.0 or not n > 0.0:
            return False
        rounded = max(step, round(n / step) * step)
        d.position = add(self.reference, mul(along, rounded / n))
        d.length_snapped = True
        return True

    def _snap_to_object(self, cursor, d, allow_point, allow_edge):
        p = self.p
        if not self.pixel_size > 0.0:
            return False
        geometry = self.current_geometry
        radius = p.radius * self.pixel_size
        q = I.Query(cursor, radius, filter=p.filter)

        near = I.find_curve_candidate(geometry, q)
        if near.valid():
            self.near_curve = near.geo
            self.wake(near.geo)

        if allow_point and near.valid() and self._quick_jump(cursor, near, d):
            return True

        if allow_point:
            q.woken = list(self.woken)
            c = I.find_point_candidate(geometry, q)
            if c.valid() and c.kind == I.VERTEX and not (self.p.centers if c.pos == I.MID else self.p.endpoints):
                c = None         # End points / Center Points switched off
            if c is not None and c.valid():
                d.winner = {I.VERTEX: SKETCH_POINT, I.MIDPOINT: MIDPOINT, I.QUADRANT: QUADRANT,
                            I.INTERSECTION: INTERSECTION}[c.kind]
                d.geo, d.pos, d.geo2 = c.geo, c.pos, c.geo2
                d.position = c.position
                return True

        if not allow_edge:
            return False

        axis_distance = min(abs(cursor[0]), abs(cursor[1]))
        if near.valid() and near.distance <= axis_distance:
            entry = (near.geo, self.geometry(near.geo))
            pos = self._circle_point(cursor, entry, d)
            if pos is not None:
                d.position = pos
                return True
            if not self.p.nearest:
                return False         # Nearest off: no snap onto the curve itself
            pos = self._direction_crossing(cursor, entry)
            d.position = pos if pos is not None else near.position
            d.winner, d.geo, d.pos, d.geo2 = SKETCH_CURVE, near.geo, I.NONE, I.GEO_UNDEF
            if pos is None or self._is_line(entry):
                self._align_nearer(cursor, entry, d, pos)
            return True
        axis = I.H_AXIS if abs(cursor[1]) <= abs(cursor[0]) else I.V_AXIS
        if axis_distance <= radius and axis not in self.excluded:
            pos = self._direction_crossing(cursor, (axis, None))
            if pos is not None:
                d.position = pos
                d.winner, d.geo = SKETCH_CURVE, axis
                self._align_nearer(cursor, (axis, None), d, pos)
                return True
            d.position = (cursor[0], 0.0) if axis == I.H_AXIS else (0.0, cursor[1])
            d.winner, d.geo = AXIS, axis
            if self._align_on_curve(cursor, (axis, None), d):
                return True   # level with (or plumb to) a woken point: that crossing, not the grid
            return False  # the grid may take the other coordinate
        return False

    def _quick_jump(self, cursor, near, d):
        ""


        try:
            from .. import quicksnaps
            key = quicksnaps.ONE_SHOT.key
        except Exception:
            key = None
        if key not in ("Midpoint", "CenterPoint", "Quadrant", "Tangent", "Perpendicular", "Intersection"):
            return False
        entry = (near.geo, self.geometry(near.geo))
        if entry[1] is None or I.is_axis(near.geo):
            return False
        if key in ("Tangent", "Perpendicular", "Intersection"):
            return self._quick_jump_to(key, cursor, entry, d)
        if key == "CenterPoint":
            g = entry[1]
            c = getattr(g, "Center", None)
            if c is None or isinstance(g, Part.LineSegment):
                return False
            d.winner, d.geo, d.pos, d.geo2 = SKETCH_POINT, near.geo, I.MID, I.GEO_UNDEF
            d.position = (c.x, c.y)
            return True
        kind = I.MIDPOINT if key == "Midpoint" else I.QUADRANT
        cands = [c for c in I.virtual_points(entry, I.Filter()) if c.kind == kind]
        if not cands:
            return False
        c = min(cands, key=lambda c: dist(c.position, cursor))
        d.winner = MIDPOINT if kind == I.MIDPOINT else QUADRANT
        d.geo, d.pos, d.geo2 = c.geo, c.pos, c.geo2
        d.position = c.position
        return True

    def _quick_jump_to(self, key, cursor, entry, d):
        """fix235: the Tangent, Perpendicular and Intersection Quick Snaps, as Midpoint's: the
        pointer anywhere over a curve takes the end to that curve's tangent point (from the line's
        start), the foot of the perpendicular, or the nearest crossing with another sketch curve."""
        g = entry[1]
        if key == "Intersection":
            best = None
            for other in self.current_geometry:
                if other[0] == entry[0] or other[1] is None or I.is_axis(other[0]) or is_model_geo(other[0]):
                    continue
                try:
                    crossings = I.intersections(entry, other)
                except Exception:
                    continue
                for x in crossings:
                    dd = dist(x, cursor)
                    if best is None or dd < best[0]:
                        best = (dd, x, other[0])
            if best is None:
                return False
            d.winner, d.geo, d.pos, d.geo2 = INTERSECTION, entry[0], I.NONE, best[2]
            d.position = best[1]
            return True
        if self.reference is None or is_model_geo(entry[0]):
            return False
        if type(g) in (Part.Circle, Part.ArcOfCircle):
            want = G.CirclePoint.TANGENT if key == "Tangent" else G.CirclePoint.NORMAL
            cands = [cp for cp in G.circle_points(self.reference, entry) if cp.kind == want]
            if not cands:
                return False
            cp = min(cands, key=lambda cp: dist(cp.position, cursor))
            d.winner = TANGENT_POINT if key == "Tangent" else NORMAL_POINT
            d.geo, d.pos, d.geo2 = entry[0], I.NONE, I.GEO_UNDEF
            d.position = cp.position
            return True
        if key == "Perpendicular" and type(g) is Part.LineSegment:
            a, b = (g.StartPoint.x, g.StartPoint.y), (g.EndPoint.x, g.EndPoint.y)
            along = sub(b, a)
            n2 = dot(along, along)
            if not n2 > 0.0:
                return False
            t = dot(sub(self.reference, a), along) / n2
            if not -1e-9 <= t <= 1.0 + 1e-9:
                return False       # the foot is off the line
            foot = add(a, mul(along, t))
            if dist(foot, self.reference) <= 1e-9 * (1.0 + length(foot)):
                return False       # the line starts on it
            d.winner, d.geo, d.pos, d.geo2 = NORMAL_POINT, entry[0], I.NONE, I.GEO_UNDEF
            d.position = foot
            return True
        return False

    def _mirror_points(self):
        """Points a drawn line may have at its middle: the origin, and the ends and centres of the
        curves the pointer woke."""
        pts = [((0.0, 0.0), -1, I.START)]
        for geo in self.woken:
            g = self.geometry(geo)
            if g is None:
                continue
            for pos in ((I.MID,) if not isinstance(g, Part.LineSegment) else (I.START, I.END)):
                try:
                    v = I.point_of(g, pos)
                except Exception:
                    v = None
                if v is not None:
                    pts.append(((v[0], v[1]), geo, pos))
        return pts

    def _mirror_midpoint(self, cursor, d):
        ""


        if not getattr(self, "mirror_midpoint", False) or self.reference is None or not self.pixel_size > 0.0:
            return False
        if d.winner not in (FREE, AXIS, AXIS_GRID, GRID) and not (d.winner == SKETCH_CURVE and d.geo in (I.H_AXIS, I.V_AXIS)):
            return False
        a = self.reference
        tol = self.p.radius * self.pixel_size
        best = None
        for (px, py), geo, pos in self._mirror_points():
            if dist((px, py), a) <= tol:
                continue
            m = (2.0 * px - a[0], 2.0 * py - a[1])
            dd = dist(m, cursor)
            if dd <= tol and (best is None or dd < best[0]):
                best = (dd, m, geo, pos)
        if best is None:
            return False
        d.position = best[1]
        d.winner, d.geo, d.pos, d.geo2 = LINE_MIDPOINT, best[2], best[3], I.GEO_UNDEF
        d.aligned_points = []
        return True

    def _is_line(self, entry):
        try:
            return type(entry[1]) is Part.LineSegment
        except Exception:
            return False

    def _align_on_curve(self, cursor, entry, d):
        ""


        if not self.p.guides.alignments or not self.pixel_size > 0.0:
            return False
        q = self.guide_query(cursor)
        q.filter.directions = q.filter.parallels = q.filter.extensions = q.filter.angles = False
        try:
            res = G.find_guides(self.current_geometry, q)
        except Exception:
            return False
        best, found, guide = self.p.radius * self.pixel_size * G.SQRT2, None, None
        for g in res.guides:
            if g.kind not in (G.ALIGN_H, G.ALIGN_V):
                continue
            for x in I.intersect_line(g.origin, g.direction, entry):
                dd = dist(x, cursor)
                if dd <= best:
                    best, found, guide = dd, x, g
        if found is None:
            return False
        d.position = found
        if guide.pos != I.NONE:
            d.aligned_points.append((guide.geo, guide.pos, guide.kind == G.ALIGN_H))
        self.last_guides = G.GuideResult(cursor)
        self.last_guides.guides = [guide]
        self.last_guides.position = found
        return True

    def _align_nearer(self, cursor, entry, d, along):
        """fix274: where the drawing direction (level or upright from the last point) crosses the curve,
        a woken point's dotted line moves the end only when its crossing is nearer the pointer: the
        level line beat a midpoint 5 px below (Beginners-1 3:50, top line onto the origin's plumb line)."""
        if along is None:
            return self._align_on_curve(cursor, entry, d)
        kept, marks = d.position, len(d.aligned_points)
        if self._align_on_curve(cursor, entry, d) and dist(d.position, cursor) > dist(kept, cursor) + 1e-12:
            d.position = kept
            del d.aligned_points[marks:]
            self.last_guides = G.GuideResult(cursor)
            return False
        return True

    def _direction_crossing(self, cursor, entry):
        if not self.current_direction.valid() or not self.pixel_size > 0.0:
            return None
        best, found = self.p.radius * self.pixel_size, None
        for x in I.intersect_line(self.current_direction.origin, self.current_direction.direction, entry):
            dd = dist(x, cursor)
            if dd <= best:
                best, found = dd, x
        return found

    def _circle_point(self, cursor, entry, d):
        if self.reference is None or not self.p.guides.directions or not self.pixel_size > 0.0:
            return None
        if is_model_geo(entry[0]):

            # ending on a part's round edge gets Coincident there (tester E14B-03: toe to crown)
            return None
        best, found = self.p.radius * self.pixel_size, None
        for cp in G.circle_points(self.reference, entry):
            dd = dist(cp.position, cursor)
            if dd <= best:
                best, found = dd, cp
        if found is None:
            return None
        if not (self.p.tangent if found.kind == G.CirclePoint.TANGENT else self.p.perpendicular):
            return None
        d.winner = TANGENT_POINT if found.kind == G.CirclePoint.TANGENT else NORMAL_POINT
        d.geo, d.pos, d.geo2 = entry[0], I.NONE, I.GEO_UNDEF
        return found.position

    # --- what the click uses -------------------------------------------------------------------
    def last_decision_at(self, position):
        if self.last is None:
            return None
        tol = 1e-9 * (1.0 + length(position))
        return self.last if dist(self.last.position, position) <= tol else None

    def last_direction_guide_along(self, direction):
        if self.last is None or not self.current_direction.valid():
            return None
        n = length(direction)
        if not n > 0.0:
            return None
        u = mul(direction, 1.0 / n)
        sine = u[0] * self.current_direction.direction[1] - u[1] * self.current_direction.direction[0]
        return self.current_direction if abs(sine) <= 1e-9 else None

    def last_alignments_at(self, position):
        """(horizontal, vertical): alignments that only placed the point, for the white glyphs."""
        if self.p.alignment_adds_relation or self.last_decision_at(position) is None \
                or self.last.winner in (SUPPRESSED, DISABLED):
            return False, False
        h = any(g.kind == G.ALIGN_H for g in self.last_guides.guides)
        v = any(g.kind == G.ALIGN_V for g in self.last_guides.guides)
        return h, v

    # --- what is drawn -----------------------------------------------------------------------
    def markers(self, d):
        """(hints, active): hollow markers for the midpoint/quadrants of the curve near the
        pointer, a filled one where the point will go."""
        hints, active = [], []
        self.quadrant_marks = []
        if d.winner in (SUPPRESSED, DISABLED):
            return hints, active
        w = d.winner
        if w in (MIDPOINT, QUADRANT, INTERSECTION, SKETCH_POINT, TANGENT_POINT, NORMAL_POINT, SKETCH_CURVE, AXIS, AXIS_GRID):
            active.append(d.position)
        elif w == LINE_MIDPOINT and self.reference is not None:

            active.append(((d.position[0] + self.reference[0]) / 2.0, (d.position[1] + self.reference[1]) / 2.0))
        elif w in (ALIGNMENT, EXTENSION, PARALLEL, PERPENDICULAR, ARC_TANGENT, ARC_RADIAL, ANGLE_STEP,
                   AXIS_ALIGN, AXIS_ALIGN_GRID) and self.last_guides.crossing:
            active.append(d.position)

        # diamonds while a tool runs (triple clamp 2:20, 13:44); the other hints stay hollow dots
        quads = []
        if self.pixel_size > 0.0:
            seen = []
            for geo in [self.near_curve] + list(self.woken):
                if geo == I.GEO_UNDEF or geo in seen:
                    continue
                seen.append(geo)
                g = self.geometry(geo)
                if g is None:
                    continue
                for pt in I.virtual_points((geo, g), self.p.filter):
                    if active and dist(pt.position, active[0]) <= 1e-9 * (1.0 + length(pt.position)):
                        continue
                    if pt.kind == I.QUADRANT:
                        quads.append(pt.position)
                    elif geo == self.near_curve:
                        hints.append(pt.position)
        self.quadrant_marks = quads
        return hints, active

    def guide_lines(self, d):
        """(candidate_lines, relation_lines, snap_lines), each a list of ((x, y), (x, y))."""
        candidates, relations, snaps = [], [], []
        if not self.pixel_size > 0.0 or d.winner in (SUPPRESSED, DISABLED):
            return candidates, relations, snaps
        box = self.view_box() if self.view_box else None
        overhang = 40.0 * self.pixel_size
        locked = [None]

        def across(a, b, lines):

            # pointer, never across the whole view (tester E13-13 on the dark floor)
            along = sub(b, a)
            n = length(along)
            if n <= 0.0:
                return
            lines.append((a, add(b, mul(along, overhang / n))))

        def toward(origin, direction, lines):
            """A short line along direction from origin to the pointer's foot on it, and a little past."""
            n = length(direction)
            if n <= 0.0:
                return
            u = mul(direction, 1.0 / n)
            t = dot(sub(d.position, origin), u)
            if abs(t) <= overhang:
                t = overhang if t >= 0.0 else -overhang
            across(origin, add(origin, mul(u, t)), lines)

        def relation(a, b):
            # the relation in use runs on past the point it comes from too (shot 35: the
            # horizontal line passes its start), not only past the pointer
            along = sub(b, a)
            n = length(along)
            if n > 0.0:
                relations.append((sub(a, mul(along, overhang / n)), add(b, mul(along, overhang / n))))
            locked[0] = along

        def segment(a, b):
            if dist(a, b) > 0.0:
                snaps.append((a, b))

        if d.winner in (TANGENT_POINT, NORMAL_POINT) and self.reference is not None:
            relation(self.reference, d.position)
        elif d.winner in (SKETCH_CURVE, AXIS, AXIS_GRID) and self.current_direction.valid():
            cd = self.current_direction
            along = sub(d.position, cd.origin)
            off = abs(along[0] * cd.direction[1] - along[1] * cd.direction[0])
            if off <= 1e-9 * (1.0 + length(along)) and dot(along, cd.direction) > 0.0:
                relation(cd.origin, d.position)
        for g in self.last_guides.guides:
            if g.is_direction():
                if g.adds_relation():
                    relation(g.origin, d.position)
                else:
                    across(g.origin, d.position, snaps)
            elif g.kind == G.EXTENSION:
                if self.p.extension_adds_relation:
                    relation(g.origin, d.position)
                else:
                    segment(g.origin, d.position)
            elif self.p.alignment_adds_relation and g.pos != I.NONE:
                relation(g.origin, d.position)
            else:
                segment(g.origin, d.position)
        if d.winner in (SKETCH_CURVE, AXIS, AXIS_GRID) and d.geo in (I.H_AXIS, I.V_AXIS) \
                and dist(d.position, (0.0, 0.0)) > 2.0 * self.p.radius * self.pixel_size \
                and not any(dist(a, (0.0, 0.0)) <= 1e-9 for a, _ in snaps):

            # the dotted line from the origin to the pointer (Beginners-1 0:24, Engine Cover 2:41)
            segment((0.0, 0.0), d.position)

        # candidate directions; after it, each one a short line to the pointer's foot on it
        for c in (self.current_candidates if self.reference is not None else ()):
            if locked[0] is not None:
                sine = abs(c.direction[0] * locked[0][1] - c.direction[1] * locked[0][0])
                if sine <= 1e-9 * (1.0 + length(locked[0])):
                    continue
            toward(c.origin, c.direction, candidates)
        if d.winner == MIDPOINT and self.p.midpoint_guides:
            g = self.geometry(d.geo)
            if type(g) is Part.LineSegment:
                a, b = (g.StartPoint.x, g.StartPoint.y), (g.EndPoint.x, g.EndPoint.y)
                along = sub(b, a)
                if length(along) > 0.0:
                    across(a, b, candidates)
                    toward(d.position, (-along[1], along[0]), candidates)
        return candidates, relations, snaps
