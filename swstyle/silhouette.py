# SPDX-License-Identifier: LGPL-2.1-or-later
""











_FW_SEEN = set()



def _alive(obj):
    """False for None or an object deleted under its wrapper (teardown.alive, review 1119)."""
    from . import teardown
    return teardown.alive(obj)


def _doc_alive(doc):
    from . import teardown
    return teardown.doc_alive(doc)


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore

from . import paths

PARAM = "SilhouetteEdges"
POLL = 150
MAX_FACES = 400
SAMPLES = 32
STYLES_WITH_EDGES = (2, 4, 6)      # Std_DrawStyle: Wireframe, No shading (HLR/HLV base), Flat lines
NODE = "SWSilhouetteEdges"
_state = {}


_GEN = [0]     # bumped by any document change: the tick's cue to look at the shapes again


class _Changes:
    def _bump(self, *args):
        _GEN[0] += 1
    slotChangedObject = slotCreatedObject = slotDeletedObject = slotRecomputedDocument = _bump
    slotActivateDocument = slotDeletedDocument = _bump


_OBSERVER = []


_VIEW_LOOK = [0.0]
VIEW_LOOK = 0.5      # s: how often a view-only change (Display Mode, Visibility) is looked for


def _view_look():
    """A view property change touches no document. A GUI document observer with slotChangedObject would
    see it, but such an observer breaks FEM's mesh view providers ("Cannot add static property"), so the
    tick looks again twice a second instead."""
    import time
    now = time.monotonic()
    if now - _VIEW_LOOK[0] >= VIEW_LOOK:
        _VIEW_LOOK[0] = now
        # only a real change counts: bumping every time made each tick read every shape again, twice a
        # second, forever (a whole core on a 144-part model)
        sig = _view_signature()
        if sig != _VIEW_SIG[0]:
            _VIEW_SIG[0] = sig
            _GEN[0] += 1


_VIEW_SIG = [None]


def _view_signature():
    """What the view shows of each object: shown or not, and its display mode (cheap: no shapes)."""
    gdoc = Gui.ActiveDocument
    if gdoc is None:
        return None
    out = [gdoc.Document.Name]
    for obj in gdoc.Document.Objects:
        vo = obj.ViewObject
        if vo is None:
            continue
        try:
            out.append((obj.Name, bool(vo.Visibility), getattr(vo, "DisplayMode", "")))
        except Exception:
            pass
    return tuple(out)


def _watch():
    if not _OBSERVER:
        _OBSERVER.append(_Changes())
        App.addDocumentObserver(_OBSERVER[0])


def enabled():
    return paths.params().GetBool(PARAM, True)


def set_enabled(on):
    paths.params().SetBool(PARAM, bool(on))
    SILHOUETTE.redraw()


def _edge_colour():
    try:        # HLR, HLV and Wireframe draw their edges in the theme's colour (light on Dark): the outlines too
        from . import hlv
        if hlv.HIDDEN.mode in ("hlr", "hlv", "wf"):
            return hlv._edge_rgb()
    except Exception as _fw_err:
        _fw_log("silhouette.py:hlvcolour", _fw_err)
    try:
        grp = App.ParamGet("User parameter:BaseApp/Preferences/View")
        value = grp.GetUnsigned("DefaultShapeLineColor", 0x191919FF)
        return ((value >> 24) & 255) / 255.0, ((value >> 16) & 255) / 255.0, ((value >> 8) & 255) / 255.0
    except Exception:
        return 0.1, 0.1, 0.1


def _style_shows_edges():
    try:
        from . import viewsettings
        index = viewsettings.draw_style_index()
    except Exception:
        index = None
    if index in STYLES_WITH_EDGES:
        return True
    if index in (None, 0):
        # As is: the objects' own display mode (FreeCAD's default is Flat Lines)
        gdoc = Gui.ActiveDocument
        if gdoc is None:
            return False
        # every object's display mode, 7 times a second: kept while no document changes (_GEN)
        key = (gdoc.Document.Name, _GEN[0])
        if _EDGES_KEPT and _EDGES_KEPT[0][0] == key:
            return _EDGES_KEPT[0][1]
        found = False
        for obj in gdoc.Document.Objects:
            vo = obj.ViewObject
            if vo is not None and vo.Visibility and getattr(vo, "DisplayMode", "") in ("Flat Lines", "Wireframe"):
                found = True
                break
        _EDGES_KEPT[:] = [(key, found)]
        return found
    return False


_EDGES_KEPT = []


def _recomputing():
    try:
        from . import asmgen
        if asmgen._busy:
            return True
    except Exception as _fw_err:
        _fw_log("silhouette.py:131", _fw_err)
    return _files_busy()      # (Document has no State: the old "Recomputing" in doc.State test always failed)


def _files_busy():
    """A file is opening or a document rebuilding (FreeCAD lets timers run between features then): the pass
    waits, the next tick after does it once (File handling perf-1127)."""
    try:
        if App.isRestoring():
            return True
        for d in App.listDocuments().values():
            if getattr(d, "Restoring", False) or getattr(d, "Recomputing", False):
                return True
    except Exception:
        return False
    return False


def _quick_too_big(doc):
    """extapps/68: True when the shown solids have more than MAX_FACES faces, counted on each object's own shape
    (no global copies, no face lists) with the same filters as hlv._shapes. A 200-part assembly read every shape
    on each drag step only to find it too big. Says False (ask the slow way) when a Solid Bodies row hides a
    solid, since those faces are left out there."""
    try:
        from . import hlv, multibody
        if multibody.rows(doc):
            return False
        n = 0
        for obj in doc.Objects:
            try:
                if obj.TypeId in ("PartDesign::Body", "App::Part") or not obj.isDerivedFrom("Part::Feature"):
                    continue
                if any(obj.isDerivedFrom(t) for t in hlv.SKIP):
                    continue
                if obj.ViewObject is None or not obj.ViewObject.isVisible() or not hlv._parents_shown(obj):
                    continue
                n += obj.Shape.countElement("Face")
            except Exception:
                continue
            if n > MAX_FACES:
                return True
    except Exception:
        return False
    return False


def _shapes(doc):
    """(object, shape) for the shown solids, as hlv does."""
    try:
        from . import hlv
        # hlv._shapes now gives the shapes alone (it gave (object, shape)): the tick's unpacking failed
        # on every tick, so no silhouette was ever drawn
        found = [(None, s) if not isinstance(s, tuple) else s for s in hlv._shapes(doc)]
        try:
            # a body hidden on its Solid Bodies row has no silhouette edges either
            from . import multibody
            if "gone" in multibody.without_hidden.__code__.co_varnames:      # extapps/68: read once
                gone = multibody.hidden_solids(doc)
                found = [(o, multibody.without_hidden(doc, s, gone)) for o, s in found]
            else:
                found = [(o, multibody.without_hidden(doc, s)) for o, s in found]
            found = [(o, s) for o, s in found if s is not None]
        except Exception as _fw_err:
            _fw_log("silhouette.py:152", _fw_err)
        return found
    except Exception:
        out = []
        for obj in doc.Objects:
            try:
                if obj.ViewObject is not None and obj.ViewObject.Visibility and hasattr(obj, "Shape") \
                        and obj.TypeId not in ("Sketcher::SketchObject",) and not obj.Shape.isNull():
                    out.append((obj, obj.Shape))
            except Exception as _fw_err:
                _fw_log("silhouette.py:162", _fw_err)
        return out


def _camera_dir(view):
    """(view direction, orthographic?, eye) from the camera."""
    from pivy import coin
    cam = view.getCameraNode()
    v = cam.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1))
    ortho = cam.getTypeId() == coin.SoOrthographicCamera.getClassTypeId()
    return App.Vector(v[0], v[1], v[2]), ortho, App.Vector(*cam.position.getValue().getValue())


def _inside(face, point):
    _BUDGET[0] -= 1
    try:
        return face.isInside(point, 1e-4, True)
    except Exception:
        return True


def _runs(face, points):
    """Polylines of the points that lie on the face (a line clipped to the face's trimmed part)."""
    lines, run = [], []
    for p in points:
        if _inside(face, p):
            run.append(p)
        else:
            if len(run) > 1:
                lines.append(run)
            run = []
    if len(run) > 1:
        lines.append(run)
    return lines


def _cyl_cone(face, surf, d, eye, ortho):
    """Silhouette generators of a cylinder or cone face for view direction d."""
    axis = App.Vector(surf.Axis).normalize()
    centre = App.Vector(surf.Center)
    u0, u1, v0, v1 = face.ParameterRange
    if ortho:
        dd = d
    else:
        dd = (centre - eye)
        if dd.Length < 1e-9:
            dd = d
        dd.normalize()
    side = dd - axis * dd.dot(axis)
    if side.Length < 1e-9:
        return []           # looking down the axis: no silhouette line
    side.normalize()
    perp = axis.cross(side)
    lines = []
    for sign in (1, -1):
        normal = perp * sign
        # the angle u where the surface normal is perpendicular to the view: the generator there
        try:
            p_ref = surf.value(u0, v0)
        except Exception:
            return []
        # find u by sampling the parameter range for the smallest |normal(u) . dd| with correct sign
        best, best_u = None, None
        n = 72
        for i in range(n + 1):
            u = u0 + (u1 - u0) * i / n
            try:
                nrm = surf.normal(u, (v0 + v1) / 2.0)
            except Exception:
                continue
            nrm = App.Vector(nrm)
            score = abs(nrm.dot(dd))
            if nrm.dot(normal) > 0 and (best is None or score < best):
                best, best_u = score, u
        if best_u is None or best > 0.2:
            continue
        pts = []
        for i in range(SAMPLES + 1):
            v = v0 + (v1 - v0) * i / SAMPLES
            try:
                pts.append(App.Vector(surf.value(best_u, v)))
            except Exception:
                break
        lines += _runs(face, pts)
    return lines


def _sphere(face, surf, d, eye, ortho):
    centre = App.Vector(surf.Center)
    r = surf.Radius
    dd = d if ortho else (centre - eye).normalize()
    a = dd.cross(App.Vector(0, 0, 1))
    if a.Length < 1e-6:
        a = dd.cross(App.Vector(1, 0, 0))
    a.normalize()
    b = dd.cross(a).normalize()
    pts = [centre + (a * math.cos(t) + b * math.sin(t)) * r for t in [2 * math.pi * i / 64 for i in range(65)]]
    return _runs(face, pts)


BUDGET = 3000      # face.isInside samples one drawing may spend on trimmed faces (about 0.4 s)
_BUDGET = [BUDGET]
_INFO = {}         # shape hashCode -> its faces sorted for the silhouette (kept across camera moves)


def _full_cylinder(face, surf):
    """A cylinder face trimmed only across its axis (a drilled hole, a boss): its silhouette lines
    run the full height, no point needs face.isInside."""
    try:
        u0, u1, v0, v1 = face.ParameterRange
        if u1 - u0 < 2 * math.pi - 1e-6:
            return False
        axis = App.Vector(surf.Axis).normalize()
        for e in face.Edges:
            curve = type(e.Curve).__name__
            if curve == "Circle":
                if abs(abs(App.Vector(e.Curve.Axis).normalize().dot(axis)) - 1.0) > 1e-6:
                    return False
            elif curve in ("Line", "LineSegment"):
                t = e.tangentAt(e.FirstParameter)
                if abs(abs(t.dot(axis)) - 1.0) > 1e-6 or abs(e.Length - (v1 - v0)) > 1e-6:
                    return False          # a cut along the axis, not the seam
            else:
                return False
        return True
    except Exception:
        return False


def _info(shape):
    key = shape.hashCode()
    got = _INFO.get(key)
    if got is not None:
        return got
    out = []
    for face in shape.Faces:
        try:
            surf = face.Surface
            kind = type(surf).__name__
        except Exception:
            continue
        if kind == "Cylinder" and _full_cylinder(face, surf):
            _u0, _u1, v0, v1 = face.ParameterRange
            out.append(("full", face, App.Vector(surf.Center), App.Vector(surf.Axis).normalize(), surf.Radius, v0, v1))
        elif kind in ("Cylinder", "Cone"):
            out.append(("cyl_cone", face, surf))
        elif kind == "Sphere":
            out.append(("sphere", face, surf))
    if len(_INFO) > 64:
        _INFO.clear()
    _INFO[key] = out
    return out


def _full_lines(centre, axis, r, v0, v1, d, eye, ortho):
    dd = d if ortho else (centre - eye)
    if dd.Length < 1e-9:
        dd = d
    dd = App.Vector(dd).normalize()
    side = dd - axis * dd.dot(axis)
    if side.Length < 1e-9:
        return []
    side.normalize()
    perp = axis.cross(side)
    return [[centre + axis * v0 + perp * (sign * r), centre + axis * v1 + perp * (sign * r)] for sign in (1, -1)]


_LINES = {}        # a trimmed round face's geometry + the camera -> its clipped lines (a rebuild that gives
                   # the same faces back draws again without asking face.isInside, 0.25 ms a sample)


def _face_key(face, surf, d, eye, ortho):
    try:
        r = lambda v: (round(v.x, 5), round(v.y, 5), round(v.z, 5))
        bb = face.BoundBox
        geo = (type(surf).__name__, r(App.Vector(surf.Center)), r(App.Vector(getattr(surf, "Axis", App.Vector()))),
               round(getattr(surf, "Radius", 0.0), 6), round(getattr(surf, "SemiAngle", 0.0), 6),
               tuple(round(x, 6) for x in face.ParameterRange),
               tuple(round(x, 5) for x in (bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)),
               len(face.Edges))      # (no Area: a surface integral per face per draw)
    except Exception:
        return None
    return geo + (r(d), ortho, () if ortho else r(eye))


def silhouettes(shape, d, eye, ortho):
    lines = []
    for item in _info(shape):
        kind = item[0]
        if kind == "full":
            lines += _full_lines(*item[2:], d, eye, ortho)
            continue
        key = _face_key(item[1], item[2], d, eye, ortho)
        got = _LINES.get(key) if key is not None else None
        if got is not None:
            lines += got
            continue
        if _BUDGET[0] <= 0:
            continue        # a part with hundreds of trimmed round faces: the rest go without, as above the face cap
        if kind == "cyl_cone":
            got = _cyl_cone(item[1], item[2], d, eye, ortho)
        else:
            got = _sphere(item[1], item[2], d, eye, ortho)
        if key is not None and _BUDGET[0] > 0:
            if len(_LINES) > 4000:
                _LINES.clear()
            _LINES[key] = got
        lines += got
    return lines


LIFT_PX = 8          # pixels' worth of depth a silhouette is drawn in front of its own surface


def _lifted(lines, obj, shape, d, eye, ortho, pixel=0.0):
    """The lines moved toward the viewer: a silhouette lies on the true round surface, and the facet
    beside it, seen almost edge-on, is far nearer the viewer a fraction of a pixel inward. In Hidden
    Lines Removed (faces drawn into depth without the Shaded With Edges offset) it hid the line: one side
    of a cylinder had no outline (vd115, 11-20). The lift is the mesh tolerance plus a few pixels."""
    if not lines:
        return lines
    try:
        dev = float(getattr(getattr(obj, "ViewObject", None), "Deviation", 0.5) or 0.5)
    except Exception:
        dev = 0.5
    try:
        eps = max(1e-4, dev / 100.0 * shape.BoundBox.DiagonalLength + LIFT_PX * pixel)
    except Exception:
        return lines
    out = []
    for line in lines:
        moved = []
        for p in line:
            towards = (eye - p) if not ortho else (-d)
            if towards.Length < 1e-12:
                moved.append(p)
                continue
            towards = App.Vector(towards)
            towards.normalize()
            moved.append(p + towards * eps)
        out.append(moved)
    return out


class _Silhouette(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.node = None
        self.view = None
        self.key = None
        self.pre = None      # the camera and document state the drawing was last checked for
        self.too_big = None  # (document, _GEN) when the shown model had more than MAX_FACES faces
        self.settle = None   # the camera and document state seen on the last tick (drawn once it holds a tick)
        _watch()
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(POLL)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.lines = 0

    def _view(self):
        gdoc = Gui.ActiveDocument
        view = gdoc.ActiveView if gdoc is not None else None
        return view if view is not None and hasattr(view, "getSceneGraph") else None

    def tick(self):
        if _recomputing():
            return          # the drawing stands till the rebuild ends; the next tick redraws
        _view_look()
        view = self._view()
        if view is None or not enabled() or not _style_shows_edges():
            self.clear()
            return
        try:
            d, ortho, eye = _camera_dir(view)
            doc = Gui.ActiveDocument.Document
            # Same camera and nothing in any document changed: the drawing stands, without asking every
            # object for its shape (9 ms a tick on a 200-feature part, about 7 ticks a second)
            pre = (id(view), tuple(round(c, 4) for c in (d.x, d.y, d.z)), ortho,
                   tuple(round(c, 2) for c in (eye.x, eye.y, eye.z)) if not ortho else (),
                   doc.Name, _GEN[0], _edge_colour())
            if pre == self.pre:
                return
            if pre != self.settle:
                # the camera (or the model) is still changing: wait for one tick with nothing new, so an orbit,
                # a pan or a view change does not work the outlines out again on every step (350 ms a step on
                # a 200-feature part with 190 round faces, 16:20Z 11-20); lines from another camera go at once
                if self.node is not None and self.settle is not None and pre[:4] != self.settle[:4]:
                    self.clear()
                self.settle = pre
                return
            from . import ticks as _ticks
            if _ticks.dragging():
                self.clear()
                return          # the camera moves under a held button: no lines until it stops (drawn after release)
            if self.too_big == (doc.Name, _GEN[0]):
                # nothing changed but the camera, and the model was already too big to draw silhouettes on:
                # don't read every shape again on each turn of the view (120 ms a tick on 144 parts)
                self.pre = pre
                return
            if _quick_too_big(doc):         # extapps/68
                self.clear()
                self.too_big = (doc.Name, _GEN[0])
                self.pre = pre
                return
            shapes = _shapes(doc)
            if sum(s.countElement("Face") for _o, s in shapes) > MAX_FACES:
                self.clear()
                self.too_big = (doc.Name, _GEN[0])
                self.pre = pre
                return
            self.too_big = None
            key = (id(view), tuple(round(c, 4) for c in (d.x, d.y, d.z)), ortho,
                   tuple(round(c, 2) for c in (eye.x, eye.y, eye.z)) if not ortho else (),
                   tuple(s.hashCode() for _o, s in shapes), _edge_colour())
        except Exception:
            self.clear()
            return
        if key == self.key and self.node is not None and self.view is view:
            self.pre = pre
            return
        self.draw(view, shapes, d, eye, ortho, key)
        self.pre = pre

    def draw(self, view, shapes, d, eye, ortho, key):
        from pivy import coin
        self.clear()
        lines = []
        _BUDGET[0] = BUDGET
        try:
            pixel = (App.Vector(view.getPoint(0, 0)) - App.Vector(view.getPoint(1, 0))).Length
        except Exception:
            pixel = 0.0
        for obj, shape in shapes:
            try:
                lines += _lifted(silhouettes(shape, d, eye, ortho), obj, shape, d, eye, ortho, pixel)
            except Exception as _fw_err:
                _fw_log("silhouette.py:435", _fw_err)
        self.key = key
        self.lines = len(lines)
        if not lines:
            return
        root = coin.SoSeparator()
        root.setName(NODE)
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        root.addChild(pick)
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        root.addChild(light)
        depth = coin.SoDepthBuffer()
        depth.function = coin.SoDepthBuffer.LEQUAL
        depth.write = False
        root.addChild(depth)
        offset = coin.SoPolygonOffset()
        offset.factor = -1.0
        offset.units = -1.0
        root.addChild(offset)
        style = coin.SoDrawStyle()
        style.lineWidth = 1.0 * Gui.getMainWindow().devicePixelRatioF()
        root.addChild(style)
        colour = coin.SoBaseColor()
        colour.rgb.setValue(*_edge_colour())
        root.addChild(colour)
        coords = coin.SoCoordinate3()
        pts = [(p.x, p.y, p.z) for line in lines for p in line]
        coords.point.setValues(0, len(pts), pts)
        root.addChild(coords)
        ls = coin.SoLineSet()
        ls.numVertices.setValues(0, len(lines), [len(line) for line in lines])
        root.addChild(ls)
        view.getSceneGraph().addChild(root)
        self.node, self.view = root, view

    def clear(self):
        if self.node is not None and self.view is not None and _alive(self.view):
            try:
                root = self.view.getSceneGraph()        # None while FreeCAD closes the view
                if root is not None:
                    root.removeChild(self.node)
            except Exception as _fw_err:
                _fw_log("silhouette.py:477", _fw_err)
        self.node = self.view = self.key = self.pre = None
        self.lines = 0

    def redraw(self):
        self.key = self.pre = None
        self.tick()

    def remove(self):
        self.timer.stop()
        self.clear()


SILHOUETTE = _Silhouette()


def install():
    if not SILHOUETTE.timer.isActive():
        SILHOUETTE.timer.start()


def remove():
    SILHOUETTE.remove()
