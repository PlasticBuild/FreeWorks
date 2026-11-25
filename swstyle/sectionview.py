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

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

try:
    from pivy import coin
except Exception:          # no Coin bindings: the command stays FreeCAD's clipping toggle
    coin = None

from . import icons

Qt = QtCore.Qt
COMMAND = "SWStyle_SectionView"
TITLE = "Section View"
ICON = "I3DVIEW_SECT_VIEW"
NODE_NAME = "SWSectionView"
SECTION_BLUE = (0.0, 0.0, 1.0)
PLANE_FILL = (0.45, 0.45, 1.0)          # the translucent sheet while the panel is open
PLANE_LINE = (0.1, 0.1, 0.85)
HANDLE_ORANGE = (1.0, 0.55, 0.0)
HANDLE_ARROW = (0.0, 0.65, 0.95)
HANDLE_ACTIVE = (1.0, 0.85, 0.2)


STANDARD = {
    "Front": ("XZ_Plane", App.Rotation(App.Vector(1, 0, 0), 90)),
    "Top": ("XY_Plane", App.Rotation()),
    "Right": ("YZ_Plane", App.Rotation(App.Vector(0, 1, 0), 90).multiply(App.Rotation(App.Vector(0, 0, 1), 90))),
}


# ---- the section's geometry --------------------------------------------------------

class Settings:
    ""

    def __init__(self):
        self.ref = ("std", "Front")       # ("std", name) | ("plane", doc, obj) | ("face", doc, obj, sub)
        self.ref_name = "Front Plane"
        self.ref_place = None             # App.Placement of a picked plane or face (origin on it, Z = normal)
        self.offset = 0.0
        self.rx = 0.0
        self.ry = 0.0
        self.reverse = False
        self.offset_selected = False      # Offset perpendicular to: False = Reference plane, True = Selected plane
        self.show_cap = True
        self.keep_cap_color = False
        self.color = SECTION_BLUE
        # sectionmore.py: Section Method, Graphics-only, cosmetic threads, Selected Bodies (Section 2
        # and 3 are made the first time they are needed)
        self.method = "planar"
        self.graphics_only = False
        self.cosmetic = True
        self.zones = []
        self.by_body = False              # Section by Body (its header check box)
        self.bodies = []
        self.include_bodies = False

    def copy(self):
        import copy as _copy
        other = Settings()
        other.__dict__.update(self.__dict__)
        for key in ("zones", "bodies"):
            setattr(other, key, list(getattr(self, key, [])))
        if hasattr(self, "extra"):
            other.extra = [_copy.copy(e) for e in self.extra]
        return other


def _standard_placement(name):
    """Placement of Front/Top/Right: the active body's origin plane when there is one."""
    feature, rotation = STANDARD[name]
    doc = App.ActiveDocument
    body = None
    try:
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        body = view.getActiveObject("pdbody") if view is not None else None
    except Exception:
        body = None
    if body is None and doc is not None:
        bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
        body = bodies[0] if len(bodies) == 1 else None
    origin = getattr(body, "Origin", None) if body is not None else None
    if origin is not None:
        for item in origin.OriginFeatures:
            if getattr(item, "Role", "") == feature:
                try:
                    return item.getGlobalPlacement()
                except Exception:
                    break
    return App.Placement(App.Vector(), rotation)


def _placement_from_normal(origin, normal):
    rotation = App.Rotation(App.Vector(0, 0, 1), normal)
    return App.Placement(origin, rotation)


def face_placement(obj, sub):
    """Placement on a planar face (centre, outward normal) or None."""
    try:
        import Part
        shape = Part.getShape(obj, sub, needSubElement=True)
    except Exception:
        return None
    if shape is None or shape.isNull() or shape.ShapeType != "Face":
        return None
    try:
        surface = shape.Surface
        if "Plane" not in surface.__class__.__name__ and not shape.isPlanar():
            return None
        u0, u1, v0, v1 = shape.ParameterRange
        normal = shape.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        center = shape.CenterOfMass
    except Exception:
        return None
    return _placement_from_normal(center, normal)


def plane_placement(obj):
    """Placement of a datum or origin plane (App::Plane, PartDesign::Plane, Part::Plane...)."""
    if obj is None:
        return None
    if obj.isDerivedFrom("App::Plane") or obj.TypeId in ("PartDesign::Plane",):
        try:
            return obj.getGlobalPlacement()
        except Exception:
            return obj.Placement
    return None


def frame(settings):
    """(point on the section plane, removed-side normal, u, v, reference normal, reference origin)."""
    if settings.ref[0] == "std":
        place = _standard_placement(settings.ref[1])
    else:
        place = settings.ref_place or _standard_placement("Front")
    base_rot = place.Rotation
    n0 = base_rot.multVec(App.Vector(0, 0, 1))
    rot = base_rot.multiply(App.Rotation(App.Vector(1, 0, 0), settings.rx)).multiply(
        App.Rotation(App.Vector(0, 1, 0), settings.ry))
    normal = rot.multVec(App.Vector(0, 0, 1))
    u = rot.multVec(App.Vector(1, 0, 0))
    v = rot.multVec(App.Vector(0, 1, 0))
    along = normal if settings.offset_selected else n0
    point = place.Base + along * settings.offset
    if settings.reverse:
        normal = normal * -1
    return point, normal, u, v, n0, place


# ---- what gets cut ---------------------------------------------------------------

def _shown_solids(doc, components=True, surfaces=False):
    ""



    out = []
    if doc is None:
        return out
    gdoc = Gui.getDocument(doc.Name)
    if components:
        try:
            from . import sectionmore
            if sectionmore._assembly(doc) is not None:
                return [(shape, colour) for _name, shape, colour in sectionmore.shown_with_names(doc, gdoc)]
        except Exception as _fw_err:
            _fw_log("sectionview.py:components", _fw_err)
    for obj in doc.Objects:
        try:
            vobj = gdoc.getObject(obj.Name)
            if vobj is None or not vobj.Visibility or not obj.Visibility:
                continue
        except Exception:
            continue
        if obj.isDerivedFrom("PartDesign::Feature"):
            body = obj.getParentGeoFeatureGroup()
            if body is not None and body.TypeId == "PartDesign::Body" and body.Visibility:
                continue  # the Body shows it
        if obj.TypeId in ("App::Plane", "App::Line", "App::Point", "PartDesign::Plane", "PartDesign::Line",
                          "PartDesign::Point", "Sketcher::SketchObject"):
            continue
        shape = getattr(obj, "Shape", None)
        if shape is None:
            continue
        try:
            if shape.isNull() or not (shape.Solids or surfaces and _surface_body(obj, shape)):
                continue
            # Shape carries the object's own placement; add the containers' (App::Part...). obj.Shape
            # is already a copy of its own, so only a moved one is copied (a deep copy of every part
            # of a big model on each change cost 0.13 s on 144 parts)
            extra = obj.getGlobalPlacement().multiply(obj.Placement.inverse())
            if not extra.isIdentity():
                shape = shape.copy()
                shape.Placement = extra.multiply(shape.Placement)
        except Exception:
            continue
        out.append((shape, _object_color(vobj)))
    return out


def _surface_body(obj, shape):
    """A surface body: faces and no solid, and not a sketch or other 2D object."""
    try:
        return bool(shape.Faces) and not shape.Solids and not obj.isDerivedFrom("Part::Part2DObject")
    except Exception:
        return False


def _object_color(vobj):
    try:
        appearance = vobj.ShapeAppearance
        if appearance:
            c = appearance[0].DiffuseColor
            return (c[0], c[1], c[2])
    except Exception as _fw_err:
        _fw_log("sectionview.py:233", _fw_err)
    try:
        c = vobj.ShapeColor
        return (c[0], c[1], c[2])
    except Exception:
        return (0.8, 0.8, 0.8)


def crosses(box, normal, distance, tol=1e-6):
    """Whether the plane normal . x = distance passes through the bound box (a part away from the
    plane needs no slice: on a big model most parts are)."""
    try:
        if not box.isValid():
            return True
        ds = [normal.dot(box.getPoint(i)) - distance for i in range(8)]
    except Exception:
        return True
    return min(ds) <= tol and max(ds) >= -tol


_CAPS = {}       # plane in a shape's own axes -> [(shape, its cap faces there)]: a big model's copies of one part cut once


def cap_faces(shape, normal, distance):
    """Faces where the plane normal . x = distance cuts the solids of shape."""
    if not crosses(shape.BoundBox, normal, distance):
        return []
    try:
        place = shape.Placement
        inv = place.inverse()
        n = inv.Rotation.multVec(normal)
        d = distance - normal.dot(place.Base)
        key = (tuple(round(x, 9) for x in (n.x, n.y, n.z)), round(d, 7))
        same = _CAPS.setdefault(key, [])
        faces = next((f for rep, f in same if rep.isPartner(shape)), None)   # partner: one geometry, placed elsewhere
    except Exception:
        return _cap_faces(shape, normal, distance)
    if faces is None:
        local = shape.copy()
        local.Placement = App.Placement()
        faces = _cap_faces(local, n, d)
        if sum(len(v) for v in _CAPS.values()) > 400:
            _CAPS.clear()
            same = _CAPS.setdefault(key, [])
        same.append((shape, faces))
    out = []
    for face in faces:
        f = face.copy()
        f.Placement = place.multiply(f.Placement)
        out.append(f)
    return out


def _cap_faces(shape, normal, distance):
    import Part
    faces = []
    for solid in shape.Solids:
        if not crosses(solid.BoundBox, normal, distance):
            continue
        try:
            wires = solid.slice(normal, distance)
        except Exception:
            continue
        wires = [w for w in wires if w.isClosed()]
        if not wires:
            continue
        try:
            face = Part.makeFace(wires, "Part::FaceMakerBullseye")
        except Exception:
            try:
                face = Part.makeFace(wires, "Part::FaceMakerCheese")
            except Exception:
                continue
        faces.extend(face.Faces)
    return faces


# ---- scene nodes ---------------------------------------------------------------------

def _vec(v):
    return coin.SbVec3f(float(v.x), float(v.y), float(v.z))


def _material(color, transparency=0.0):
    material = coin.SoMaterial()
    material.diffuseColor.setValue(*color)
    material.ambientColor.setValue(*color)
    material.emissiveColor.setValue(*[c * 0.35 for c in color])
    material.transparency.setValue(transparency)
    return material


def _base_color(color, transparency=0.0):
    sep = coin.SoSeparator()
    model = coin.SoLightModel()
    model.model = coin.SoLightModel.BASE_COLOR
    sep.addChild(model)
    sep.addChild(_material(color, transparency))
    return sep


def _arrow_geometry(color, length=1.0):
    """An arrow along +X in its own space, for the offset handle."""
    sep = coin.SoSeparator()
    sep.addChild(_material(color))
    shaft = coin.SoSeparator()
    t = coin.SoTransform()
    t.rotation.setValue(coin.SbVec3f(0, 0, 1), -math.pi / 2)
    t.translation.setValue(length * 0.4, 0, 0)
    shaft.addChild(t)
    cyl = coin.SoCylinder()
    cyl.radius = 0.035 * length
    cyl.height = 0.8 * length
    shaft.addChild(cyl)
    sep.addChild(shaft)
    head = coin.SoSeparator()
    t2 = coin.SoTransform()
    t2.rotation.setValue(coin.SbVec3f(0, 0, 1), -math.pi / 2)
    t2.translation.setValue(length * 0.9, 0, 0)
    head.addChild(t2)
    cone = coin.SoCone()
    cone.bottomRadius = 0.1 * length
    cone.height = 0.25 * length
    head.addChild(cone)
    sep.addChild(head)
    return sep


def _arc_geometry(color, radius=1.0):
    """A half ring in its own XY plane on the +Y side, for a rotation handle."""
    sep = coin.SoSeparator()
    sep.addChild(_material(color))
    style = coin.SoDrawStyle()
    style.lineWidth = 5
    sep.addChild(style)
    pts = []
    steps = 32
    for i in range(steps + 1):
        a = math.pi * i / steps
        pts.append((radius * math.cos(a), radius * math.sin(a), 0.0))
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, len(pts), pts)
    sep.addChild(coords)
    line = coin.SoLineSet()
    line.numVertices.setValue(len(pts))
    sep.addChild(line)
    # a fat invisible band along the arc so the handle is easy to grab
    pick = coin.SoSeparator()
    pick.addChild(_material(color, 1.0))
    pick_pts = []
    for i in range(steps + 1):
        a = math.pi * i / steps
        for r in (radius * 0.85, radius * 1.15):
            pick_pts.append((r * math.cos(a), r * math.sin(a), 0.0))
    pc = coin.SoCoordinate3()
    pc.point.setValues(0, len(pick_pts), pick_pts)
    pick.addChild(pc)
    strip = coin.SoTriangleStripSet()
    strip.numVertices.setValue(len(pick_pts))
    pick.addChild(strip)
    sep.addChild(pick)
    return sep


def _coin_rotation(rot):
    q = rot.Q
    return coin.SbRotation(q[0], q[1], q[2], q[3])


def _hidden_lines_again():
    """HLR / HLV / Wireframe draw the edges of what the section shows: drawn again after each cut."""
    try:
        from . import hlv
        hlv.HIDDEN.later()
    except Exception as _fw_err:
        _fw_log("sectionview.py:hlv", _fw_err)


class Section:
    """One section on one 3D view: the clip plane, the caps and (while editing) the handles."""

    def __init__(self, view, settings):
        self.view = view
        self.settings = settings
        self.editing = False
        self.on_drag = None              # called with the settings after a handle moved
        self.root = coin.SoSeparator()
        self.root.setName(NODE_NAME)
        self.caps = coin.SoSeparator()
        self.handles = coin.SoSwitch()
        self.root.addChild(self.caps)
        self.root.addChild(self.handles)
        self.clip = coin.SoClipPlane()
        self.clip.setName(NODE_NAME + "Clip")
        self._drag = None
        self._last = None
        # Coin's dragger callbacks run without Python's lock in FreeCAD 1.1 (a pivy callback there
        # crashes FreeCAD), so the handles are watched from a Qt timer instead.
        self._watch = QtCore.QTimer()
        self._watch.setInterval(30)
        self._watch.timeout.connect(self._poll_handles)
        self._cap_timer = QtCore.QTimer()
        self._cap_timer.setSingleShot(True)
        self._cap_timer.setInterval(40)
        self._cap_timer.timeout.connect(self.update_caps)
        self._attached = False
        self._size = 100.0
        self._center = App.Vector()
        self._build_handles()

    # -- life cycle
    def attach(self):
        if self._attached:
            return
        graph = self.view.getSceneGraph()
        graph.insertChild(self.root, 0)
        graph.insertChild(self.clip, 1)
        self._attached = True
        self.update()

    def detach(self):
        if not self._attached:
            return
        _CAPS.clear()
        self._whole = None
        self._cap_timer.stop()
        self._watch.stop()
        try:
            graph = self.view.getSceneGraph()
            for node in (self.clip, self.root):
                index = graph.findChild(node)
                if index >= 0:
                    graph.removeChild(index)
        except Exception as _fw_err:
            _fw_log("sectionview.py:410", _fw_err)
        self._attached = False
        _hidden_lines_again()

    @property
    def attached(self):
        return self._attached

    def set_editing(self, on):
        self.editing = on
        if on and self._attached:
            self._watch.start()
        else:
            self._watch.stop()
        self.update()

    # -- geometry
    def _measure(self):
        doc = App.ActiveDocument
        box = App.BoundBox()
        if doc is not None:
            for shape, _ in _shown_solids(doc):
                box.add(shape.BoundBox)
        if box.isValid() and box.DiagonalLength > 1e-6:
            self._size = box.DiagonalLength
            self._center = box.Center
        else:
            self._size, self._center = 100.0, App.Vector()

    def update(self, caps_now=True):
        """Settings changed: move the clip plane, the sheet and the handles; rebuild the caps."""
        if not self._attached:
            return
        point, normal, u, v, n0, place = frame(self.settings)
        self._frame = (point, normal, u, v)
        keep = normal * -1
        from . import sectionmore
        if sectionmore.solid_mode(self.settings):
            sectionmore.clip_all(self.clip)          # the cut solids are drawn in self.caps
        else:
            self.clip.plane.setValue(coin.SbPlane(_vec(keep), float(keep.dot(point))))
            self.clip.on.setValue(True)
        if caps_now:
            self._measure()
            self.update_caps()
        else:
            self._cap_timer.start()
        self._place_handles()

    def update_caps(self):
        self.caps.removeAllChildren()
        _hidden_lines_again()
        if not self._attached:
            return
        from . import sectionmore
        if getattr(self.settings, "cosmetic", False):
            edges = sectionmore.thread_edges(App.ActiveDocument, sectionmore.active_frames(self.settings))
            if edges:
                sectionmore.lines(self.caps, edges, (0.15, 0.15, 0.15), max(self._size / 2000.0, 0.01), 2.0)
        if sectionmore.solid_mode(self.settings):
            sectionmore.solid_caps(self)
            return
        if not self.settings.show_cap:
            return
        point, normal, u, v = self._frame
        distance = normal.dot(point)
        doc = App.ActiveDocument
        tol = max(self._size / 2000.0, 0.01)
        for shape, color in _shown_solids(doc):
            faces = cap_faces(shape, normal, distance)
            if not faces:
                continue

            # open; Keep cap color gives it the section colour (Edit Color)
            use = self.settings.color if self.settings.keep_cap_color else color
            node = _base_color(use)
            # a hair towards the kept side so the cap never fights the clip plane
            shift = coin.SoTranslation()
            shift.translation.setValue(_vec(normal * (-tol * 0.05)))
            node.addChild(shift)
            hints = coin.SoShapeHints()
            hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
            hints.shapeType = coin.SoShapeHints.UNKNOWN_SHAPE_TYPE
            node.addChild(hints)
            points, index = [], []
            for face in faces:
                try:
                    pts, tris = face.tessellate(tol)
                except Exception as _fw_err:
                    _fw_log("sectionview.py:496", _fw_err)
                    continue
                start = len(points)
                points.extend((p.x, p.y, p.z) for p in pts)
                for a, b, c in tris:
                    index.extend((start + a, start + b, start + c, -1))
            if not index:
                continue
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, len(points), points)
            node.addChild(coords)
            faceset = coin.SoIndexedFaceSet()
            faceset.coordIndex.setValues(0, len(index), index)
            node.addChild(faceset)
            # the cut outline, drawn dark like the model's edges
            edges = coin.SoSeparator()
            edges.addChild(_material((0.1, 0.1, 0.1)))
            style = coin.SoDrawStyle()
            style.lineWidth = 1.5
            edges.addChild(style)
            for face in faces:
                for edge in face.Edges:
                    try:
                        pts = edge.discretize(Deflection=tol)
                    except Exception as _fw_err:
                        _fw_log("sectionview.py:521", _fw_err)
                        continue
                    lc = coin.SoCoordinate3()
                    lc.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
                    edges.addChild(lc)
                    ls = coin.SoLineSet()
                    ls.numVertices.setValue(len(pts))
                    edges.addChild(ls)
            node.addChild(edges)
            self.caps.addChild(node)

    # -- the sheet and the handles (shown while the panel is open)
    def _build_handles(self):
        group = coin.SoSeparator()
        self.handles.addChild(group)
        self.handles.whichChild = coin.SO_SWITCH_NONE
        # the translucent sheet with a solid outline and two solid centre lines
        self.sheet_coords = coin.SoCoordinate3()
        sheet = _base_color(PLANE_FILL, 0.65)
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
        sheet.addChild(hints)
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE      # clicks go through to faces behind it
        sheet.addChild(pick)
        sheet.addChild(self.sheet_coords)
        quad = coin.SoFaceSet()
        quad.numVertices.setValue(4)
        sheet.addChild(quad)
        group.addChild(sheet)
        lines = _base_color(PLANE_LINE)
        lines.addChild(pick)
        dashed = coin.SoDrawStyle()
        dashed.linePattern = 0xFFFF
        dashed.lineWidth = 1.5
        lines.addChild(dashed)
        self.outline_coords = coin.SoCoordinate3()
        lines.addChild(self.outline_coords)
        outline = coin.SoLineSet()
        outline.numVertices.setValue(5)
        lines.addChild(outline)
        solid = coin.SoDrawStyle()
        solid.linePattern = 0xFFFF
        lines.addChild(solid)
        self.cross_coords = coin.SoCoordinate3()
        lines.addChild(self.cross_coords)
        cross = coin.SoLineSet()
        cross.numVertices.setValues(0, 2, [2, 2])
        lines.addChild(cross)
        group.addChild(lines)
        # the sheets of Section 2 and Section 3 while they are on (sectionmore.extra_sheets)
        self.extra_sheets = coin.SoSeparator()
        group.addChild(self.extra_sheets)
        # the handles: an arrow for the offset, two arcs for the X and Y rotations
        self.handle_xf = coin.SoTransform()
        self.handle_scale = coin.SoScale()
        handle_group = coin.SoSeparator()
        handle_group.addChild(self.handle_xf)
        handle_group.addChild(self.handle_scale)
        self.arrow = coin.SoTranslate1Dragger()
        self.arrow.setPart("translator", _arrow_geometry(HANDLE_ARROW))
        self.arrow.setPart("translatorActive", _arrow_geometry(HANDLE_ACTIVE))
        self.arrow.setPart("feedback", coin.SoSeparator())
        self.arrow.setPart("feedbackActive", coin.SoSeparator())
        arrow_sep = coin.SoSeparator()
        arrow_rot = coin.SoRotation()
        arrow_rot.rotation.setValue(coin.SbRotation(coin.SbVec3f(1, 0, 0), coin.SbVec3f(0, 0, 1)))  # X -> normal
        arrow_sep.addChild(arrow_rot)
        arrow_sep.addChild(self.arrow)
        handle_group.addChild(arrow_sep)
        self.discs = {}
        # Each disc turns about its local Z; its arc lies in its local XY on the +Y side. Local Y is the

        # X Rotation: local (X, Y, Z) -> plane (Y, normal, X). Y Rotation: -> plane (X, normal, -Y).
        frames = (("rx", App.Rotation(App.Matrix(0, 0, 1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1))),
                  ("ry", App.Rotation(App.Vector(1, 0, 0), 90)))
        for key, axis in frames:
            disc = coin.SoRotateDiscDragger()
            disc.setPart("rotator", _arc_geometry(HANDLE_ORANGE, 0.75))
            disc.setPart("rotatorActive", _arc_geometry(HANDLE_ACTIVE, 0.75))
            disc.setPart("feedback", coin.SoSeparator())
            disc.setPart("feedbackActive", coin.SoSeparator())
            sep = coin.SoSeparator()
            orient = coin.SoRotation()
            orient.rotation.setValue(_coin_rotation(axis))
            sep.addChild(orient)
            sep.addChild(disc)
            handle_group.addChild(sep)
            self.discs[key] = (disc, orient)
        group.addChild(handle_group)

    def _place_sheet(self, centre):
        """The translucent sheet, its dashed outline and centre lines, on the current plane."""
        point, normal, u, v = self._frame
        half = self._size * 0.42
        corners = [centre + u * su * half + v * sv * half for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        self.sheet_coords.point.setValues(0, 4, [(c.x, c.y, c.z) for c in corners])
        ring = corners + [corners[0]]
        self.outline_coords.point.setValues(0, 5, [(c.x, c.y, c.z) for c in ring])
        cross = [centre - u * half, centre + u * half, centre - v * half, centre + v * half]
        self.cross_coords.point.setValues(0, 4, [(c.x, c.y, c.z) for c in cross])

    def _place_handles(self):
        if not self.editing:
            self.handles.whichChild = coin.SO_SWITCH_NONE
            return
        self.handles.whichChild = coin.SO_SWITCH_ALL
        point, normal, u, v = self._frame
        # the sheet: centred on the model's centre projected onto the plane
        centre = self._center - normal * normal.dot(self._center - point)
        self._place_sheet(centre)
        from . import sectionmore
        sectionmore.extra_sheets(self)
        # handles: local frame X = u, Y = v, Z = normal (the side that is cut away)
        settings = self.settings
        place = frame(settings)[5]
        rot = place.Rotation.multiply(App.Rotation(App.Vector(1, 0, 0), settings.rx)).multiply(
            App.Rotation(App.Vector(0, 1, 0), settings.ry))
        if settings.reverse:
            rot = rot.multiply(App.Rotation(App.Vector(1, 0, 0), 180))
        self.handle_xf.translation.setValue(_vec(centre))
        self.handle_xf.rotation.setValue(_coin_rotation(rot))
        scale = self._size * 0.16
        self.handle_scale.scaleFactor.setValue(scale, scale, scale)
        self._handle_scale = scale
        self._centre = centre
        if self._drag is None:
            self.arrow.translation.setValue(0, 0, 0)
            for disc, _ in self.discs.values():
                disc.rotation.setValue(coin.SbRotation())

    # -- dragging
    def _draggers(self):
        yield "offset", self.arrow
        for key, (disc, _) in self.discs.items():
            yield key, disc

    def _poll_handles(self):
        if not self._attached or not self.editing:
            return
        active = None
        for key, dragger in self._draggers():
            if dragger.isActive.getValue():
                active = (key, dragger)
                break
        if active is not None:
            key, dragger = active
            if self._drag is None or self._drag[0] != key:
                self._start(key, dragger)
                self._last = None
            value = tuple(dragger.translation.getValue()) if key == "offset" else \
                tuple(dragger.rotation.getValue().getValue())
            if value != self._last:         # the pointer moved the handle
                self._last = value
                self._motion(key, dragger)
        elif self._drag is not None:
            key = self._drag[0]
            self._finish(key, dict(self._draggers())[key])

    def _start(self, key, dragger):
        s = self.settings
        self._drag = (key, s.offset, s.rx, s.ry)

    def _motion(self, key, dragger):
        if self._drag is None:
            return
        _, offset, rx, ry = self._drag
        s = self.settings
        if key == "offset":
            t = dragger.translation.getValue()[0] * self._handle_scale
            point, normal, u, v, n0, place = frame(s)
            if s.reverse:
                t = -t
            if s.offset_selected:
                s.offset = offset + t
            else:
                n = normal * (-1 if s.reverse else 1)
                along = n.dot(n0)
                s.offset = offset + (t / along if abs(along) > 0.2 else t)
        else:
            # the disc turns about its own Z: the angle is 2 atan2(qz, qw)
            q = dragger.rotation.getValue().getValue()
            degrees = math.degrees(2.0 * math.atan2(q[2], q[3]))
            if key == "rx":
                s.rx = _wrap(rx + degrees)
            else:
                # the Y disc turns about -Y; Reverse turns the handles half a turn about X, flipping Y again
                s.ry = _wrap(ry + degrees if s.reverse else ry - degrees)
            # the arcs turn about the handle centre: keep the plane through it, as the arcs show it
            point, normal, u, v, n0, place = frame(s)
            n = normal * (-1 if s.reverse else 1)
            c0 = self._centre
            if s.offset_selected:
                s.offset = n.dot(c0 - place.Base)
            elif abs(n.dot(n0)) > 1e-6:
                s.offset = n.dot(c0 - place.Base) / n.dot(n0)
        # move the cut and the sheet live; the handles move themselves (they are under the pointer)
        point, normal, u, v, n0, place = frame(s)
        self._frame = (point, normal, u, v)
        keep = normal * -1
        self.clip.plane.setValue(coin.SbPlane(_vec(keep), float(keep.dot(point))))
        c0 = self._centre
        self._place_sheet(c0 - normal * normal.dot(c0 - point))
        if not self._cap_timer.isActive():      # a restart on every move would hold the caps back until the drag ends
            self._cap_timer.start()
        if self.on_drag is not None:
            self.on_drag()

    def _finish(self, key, dragger):
        self._drag = None
        self.update(caps_now=True)
        if self.on_drag is not None:
            self.on_drag()


def _wrap(degrees):
    degrees = math.fmod(degrees, 360.0)
    if degrees > 180:
        degrees -= 360
    elif degrees < -180:
        degrees += 360
    return degrees


# ---- the PropertyManager -------------------------------------------------------------

def _ink():
    """Line colour for the drawn icons: the look's text colour (dark on Light, light on Dark/AMOLED)."""
    try:
        from . import style
        return QtGui.QColor(style.T.hex("text"))
    except Exception:
        return QtGui.QColor("#303030")


def _painted(kind, color=QtGui.QColor("#1f5fbf")):
    ""
    ink = _ink()
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pixmap = _hidpi.canvas(32, 32)
    pixmap.fill(Qt.transparent)
    p = QtGui.QPainter(pixmap)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    pen = QtGui.QPen(ink, 1.6)
    fill = QtGui.QColor(90, 130, 230, 170)
    box = QtGui.QPen(QtGui.QColor("#606060"), 1.2)
    if kind in ("Front", "Top", "Right"):
        # a grey cube with the named plane in blue
        p.setPen(box)
        p.setBrush(QtGui.QColor("#e8e8e8"))
        p.drawRect(6, 10, 16, 16)
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(6, 10), QtCore.QPointF(12, 4), QtCore.QPointF(28, 4),
                                       QtCore.QPointF(22, 10)]))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(22, 10), QtCore.QPointF(28, 4), QtCore.QPointF(28, 20),
                                       QtCore.QPointF(22, 26)]))
        p.setPen(QtGui.QPen(color.darker(130), 1.4))
        p.setBrush(fill)
        if kind == "Front":
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(9, 7), QtCore.QPointF(25, 7), QtCore.QPointF(25, 23),
                                           QtCore.QPointF(9, 23)]))
        elif kind == "Top":
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(3, 19), QtCore.QPointF(10, 12), QtCore.QPointF(30, 12),
                                           QtCore.QPointF(23, 19)]))
        else:
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(14, 9), QtCore.QPointF(20, 3), QtCore.QPointF(20, 23),
                                           QtCore.QPointF(14, 29)]))
    elif kind == "reverse":
        p.setPen(QtGui.QPen(ink, 2))
        p.drawLine(7, 25, 25, 7)
        p.setBrush(ink)
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(25, 7), QtCore.QPointF(16, 9), QtCore.QPointF(23, 16)]))
        p.setPen(QtGui.QPen(QtGui.QColor("#909090"), 2))
        p.setBrush(QtGui.QColor("#909090"))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(7, 25), QtCore.QPointF(16, 23), QtCore.QPointF(9, 16)]))
    elif kind == "offset":
        p.setPen(pen)
        p.setBrush(fill)
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(4, 22), QtCore.QPointF(12, 14), QtCore.QPointF(28, 14),
                                       QtCore.QPointF(20, 22)]))
        p.drawLine(16, 18, 16, 4)
        p.drawLine(16, 4, 12, 8)
        p.drawLine(16, 4, 20, 8)
        p.setFont(QtGui.QFont("Arial", 9, QtGui.QFont.Bold))
        p.drawText(QtCore.QRectF(18, 18, 14, 14), Qt.AlignCenter, "D")
    elif kind in ("rx", "ry"):
        p.setPen(QtGui.QPen(ink, 1.8))
        p.drawLine(6, 26, 6, 8)
        p.drawLine(6, 26, 24, 26)
        p.setPen(QtGui.QPen(QtGui.QColor("#1f5fbf"), 2))
        p.drawArc(QtCore.QRectF(4, 6, 20, 20), 0, 90 * 16)
        p.drawLine(24, 16, 21, 12)
        p.drawLine(24, 16, 27, 12)
        p.setPen(QtGui.QPen(ink, 1))
        p.setFont(QtGui.QFont("Arial", 8, QtGui.QFont.Bold))
        p.drawText(QtCore.QRectF(18, 0, 14, 12), Qt.AlignCenter, "X" if kind == "rx" else "Y")
    p.end()
    return QtGui.QIcon(pixmap)


def _swatch(color):
    pixmap = QtGui.QPixmap(18, 22)
    pixmap.fill(QtGui.QColor.fromRgbF(*color))
    return QtGui.QIcon(pixmap)


class SectionPanel:
    ""

    def __init__(self, controller, settings):
        self.controller = controller
        self.settings = settings
        self._quiet = False
        self.options = QtWidgets.QWidget()
        self.options.setObjectName("SWSectionOptions")
        self.options.setWindowTitle("Section Options")
        self.options.setProperty("swstyle_pm_title", TITLE)
        self.options.setProperty("swstyle_pm_icon", ICON)
        lay = QtWidgets.QVBoxLayout(self.options)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(QtWidgets.QLabel("Offset perpendicular to:"))
        self.ref_radio = QtWidgets.QRadioButton("Reference plane")
        self.sel_radio = QtWidgets.QRadioButton("Selected plane")
        for radio in (self.ref_radio, self.sel_radio):
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(24, 0, 0, 0)
            row.addWidget(radio)
            lay.addLayout(row)
        self.ref_radio.setToolTip("The offset moves the plane along the reference plane's normal.")
        self.sel_radio.setToolTip("The offset moves the plane along its own (rotated) normal.")
        self.cap_box = QtWidgets.QCheckBox("Show section cap")
        self.cap_box.setToolTip("Fills the cut faces, so the cut looks solid.")
        self.keep_box = QtWidgets.QCheckBox("Keep cap color")
        self.keep_box.setToolTip("The cut faces take the section colour (Edit Color) instead of the part's colour.")
        lay.addWidget(self.cap_box)
        lay.addWidget(self.keep_box)

        self.section = QtWidgets.QWidget()
        self.section.setObjectName("SWSection1")
        self.section.setWindowTitle("Section 1")
        grid = QtWidgets.QVBoxLayout(self.section)
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setSpacing(5)
        planes = QtWidgets.QHBoxLayout()
        planes.setContentsMargins(26, 0, 0, 0)
        planes.setSpacing(2)
        self.plane_buttons = {}
        for name in ("Front", "Top", "Right"):
            button = QtWidgets.QToolButton()
            button.setObjectName("SWSection" + name)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setIcon(_painted(name))
            button.setIconSize(QtCore.QSize(22, 22))
            button.setToolTip(name)
            button.clicked.connect(lambda checked=False, n=name: self.pick_standard(n))
            planes.addWidget(button)
            self.plane_buttons[name] = button
        planes.addStretch(1)
        grid.addLayout(planes)
        ref_row = QtWidgets.QHBoxLayout()
        ref_row.setSpacing(6)
        self.reverse_button = QtWidgets.QToolButton()
        self.reverse_button.setObjectName("SWSectionReverse")
        self.reverse_button.setIcon(_painted("reverse"))
        self.reverse_button.setIconSize(QtCore.QSize(18, 18))
        self.reverse_button.setToolTip("Reverse Section Direction")
        self.reverse_button.setCheckable(True)
        self.reverse_button.clicked.connect(self.toggle_reverse)
        self.ref_field = QtWidgets.QLineEdit()
        self.ref_field.setObjectName("SWSectionReference")
        self.ref_field.setReadOnly(True)
        self.ref_field.setToolTip("Reference Section Plane/Face: click a plane or a flat face in the view or the tree")
        self.ref_field.setStyleSheet("QLineEdit { background: #cce4f7; color: black; border: 1px solid #7eb4ea; }")
        ref_row.addWidget(self.reverse_button)
        ref_row.addWidget(self.ref_field, 1)
        grid.addLayout(ref_row)
        self.offset_box = self._quantity(grid, "offset", "Offset Distance", "mm")
        self.rx_box = self._quantity(grid, "rx", "X Rotation", "deg")
        self.ry_box = self._quantity(grid, "ry", "Y Rotation", "deg")
        color_row = QtWidgets.QHBoxLayout()
        color_row.setSpacing(8)
        self.swatch = QtWidgets.QLabel()
        self.swatch.setObjectName("SWSectionSwatch")
        self.swatch.setFixedSize(18, 22)
        self.color_button = QtWidgets.QPushButton("Edit Color")
        self.color_button.setObjectName("SWSectionEditColor")
        self.color_button.clicked.connect(self.edit_color)
        color_row.addWidget(self.swatch)
        color_row.addSpacing(30)
        color_row.addWidget(self.color_button)
        color_row.addStretch(1)
        grid.addLayout(color_row)

        self.form = [self.options, self.section]
        from . import sectionmore
        self.extra_boxes = sectionmore.ExtraBoxes(self)
        self.ref_radio.toggled.connect(self._options_changed)
        self.cap_box.toggled.connect(self._options_changed)
        self.keep_box.toggled.connect(self._options_changed)
        self.show()

    def _quantity(self, layout, key, tip, unit):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        picture = QtWidgets.QLabel()
        picture.setFixedSize(22, 22)
        picture.setPixmap(_painted(key).pixmap(20, 20))
        picture.setToolTip(tip)
        box = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
        box.setObjectName("SWSection_" + key)
        box.setToolTip(tip)
        box.setProperty("unit", unit)
        box.setProperty("minimum", -1e7 if unit == "mm" else -360.0)
        box.setProperty("maximum", 1e7 if unit == "mm" else 360.0)
        box.setProperty("singleStep", 1.0)
        box.setKeyboardTracking(False)      # the section moves once a typed value is finished
        try:
            from . import optionsextras
            optionsextras.apply_step(box)
        except Exception as _fw_err:
            _fw_log("sectionview.py:933", _fw_err)
        box.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        QtCore.QObject.connect(box, QtCore.SIGNAL("valueChanged(double)"),
                               lambda value, k=key: self._value_changed(k, value))
        row.addWidget(picture)
        row.addWidget(box, 1)
        layout.addLayout(row)
        return box

    # -- show the settings
    def show(self):
        s = self.settings
        self._quiet = True
        try:
            self.ref_radio.setChecked(not s.offset_selected)
            self.sel_radio.setChecked(s.offset_selected)
            self.cap_box.setChecked(s.show_cap)
            self.keep_box.setChecked(s.keep_cap_color)
            self.keep_box.setEnabled(s.show_cap)
            for name, button in self.plane_buttons.items():
                button.setChecked(s.ref == ("std", name))
            self.reverse_button.setChecked(s.reverse)
            self.ref_field.setText(s.ref_name)
            for box, value in ((self.offset_box, s.offset), (self.rx_box, s.rx), (self.ry_box, s.ry)):
                if abs((box.property("rawValue") or 0.0) - value) > 1e-9:
                    box.setProperty("rawValue", value)
            self.swatch.setPixmap(_swatch(s.color).pixmap(18, 22))
            if getattr(self, "extra_boxes", None) is not None:
                self.extra_boxes.show()
        finally:
            self._quiet = False

    # -- user input
    def pick_standard(self, name):
        s = self.settings
        s.ref, s.ref_name, s.ref_place = ("std", name), name + " Plane", None
        s.offset = s.rx = s.ry = 0.0
        self.show()
        self.controller.changed()

    def pick_reference(self, ref, name, place):
        s = self.settings
        s.ref, s.ref_name, s.ref_place = ref, name, place
        s.offset = s.rx = s.ry = 0.0
        self.show()
        self.controller.changed()

    def toggle_reverse(self):
        self.settings.reverse = self.reverse_button.isChecked()
        self.controller.changed()

    def edit_color(self):
        start = QtGui.QColor.fromRgbF(*self.settings.color)
        color = QtWidgets.QColorDialog.getColor(start, Gui.getMainWindow(), "Section Color")
        if color.isValid():
            self.settings.color = (color.redF(), color.greenF(), color.blueF())
            self.show()
            self.controller.changed()

    def _options_changed(self, *args):
        if self._quiet:
            return
        s = self.settings
        if s.offset_selected != self.sel_radio.isChecked():
            # keep the plane where it is: convert the offset to the other measure
            point, normal, u, v, n0, place = frame(s)
            n = normal * (-1 if s.reverse else 1)
            along = n.dot(n0)
            if self.sel_radio.isChecked():
                s.offset = s.offset * along
            elif abs(along) > 1e-6:
                s.offset = s.offset / along
            s.offset_selected = self.sel_radio.isChecked()
        s.show_cap = self.cap_box.isChecked()
        s.keep_cap_color = self.keep_box.isChecked()
        self.show()
        self.controller.changed()

    def _value_changed(self, key, value):
        if self._quiet:
            return
        box = {"offset": self.offset_box, "rx": self.rx_box, "ry": self.ry_box}[key]
        raw = box.property("rawValue")
        setattr(self.settings, key, float(raw if raw is not None else value))
        self.controller.changed(caps_now=False)

    # -- FreeCAD's task dialog
    def accept(self):
        self.controller.finish(True)
        return True

    def reject(self):
        self.controller.finish(False)
        return True

    def isAllowedAlterSelection(self):
        return True

    def isAllowedAlterView(self):
        return True

    def isAllowedAlterDocument(self):
        return True


class _SelectionWatch:
    """While the panel is open a picked plane or flat face becomes the section plane."""

    def __init__(self, controller):
        self.controller = controller

    def addSelection(self, doc, obj, sub, pnt):
        QtCore.QTimer.singleShot(0, lambda: self.controller.picked(doc, obj, sub, pnt))


class _DocWatch:
    """The model changed (rebuild, shown/hidden): cut it again."""

    def __init__(self, controller):
        self.controller = controller

    def slotRecomputedDocument(self, doc):
        self.controller.model_changed()

    def slotChangedObject(self, obj, prop):
        if prop in ("Visibility", "Placement"):
            self.controller.model_changed()


class Controller:
    """Holds the one live section of the session and the open PropertyManager."""

    def __init__(self):
        self.settings = Settings()
        self.section = None
        self.panel = None
        self.saved = None
        self.sel_watch = None
        self.doc_watch = _DocWatch(self)
        self.doc_watching = False
        self._syncing = False
        self._model_timer = QtCore.QTimer()
        self._model_timer.setSingleShot(True)
        self._model_timer.setInterval(150)
        self._model_timer.timeout.connect(self._model_update)

    # -- state shown on the button
    def active(self):
        return self.section is not None and self.section.attached and self._view_alive()

    def _view_alive(self):
        try:
            self.section.view.getSceneGraph()
            return True
        except Exception:
            return False

    def sync_button(self):
        try:
            actions = Gui.Command.get(COMMAND).getAction()
        except Exception as _fw_err:
            _fw_log("sectionview.py:1102", _fw_err)
            return
        on = self.active() or self.panel is not None
        for action in actions:
            if action.isCheckable() and action.isChecked() != on:
                self._syncing = True
                try:
                    action.setChecked(on)
                finally:
                    self._syncing = False

    # -- the command
    def button(self, checked=None):
        if self._syncing:
            return
        if self.panel is not None:
            # a click on the pressed button while the panel is open closes it, as Cancel does
            Gui.Control.closeDialog()
            self.finish(False)
            return
        if self.active():
            self.turn_off()
            return
        self.start()

    def start(self):
        view = _active_3d_view()
        if view is None:
            self.sync_button()
            return
        if Gui.Control.activeDialog():
            # another PropertyManager is open (a sketch, a feature): toggle the last section without a panel
            self._attach(view, self.settings)
            self.section.set_editing(False)
            self.sync_button()
            return
        from . import sectionmore
        sectionmore.defaults(self.settings)    # Section 2 / 3 exist before the copy, so Cancel puts them back too
        self.saved = self.settings.copy()
        self._preselected()
        self._attach(view, self.settings)
        self.section.set_editing(True)
        self.panel = SectionPanel(self, self.settings)
        self.section.on_drag = self.panel.show
        Gui.Control.showDialog(self.panel)
        Gui.Selection.clearSelection()
        self.sel_watch = _SelectionWatch(self)
        Gui.Selection.addObserver(self.sel_watch)
        self.sync_button()

    def _attach(self, view, settings):
        if self.section is not None and (self.section.view is not view or not self._view_alive()):
            self.section.detach()
            self.section = None
        if self.section is None:
            self.section = Section(view, settings)
        self.section.settings = settings
        self.section.attach()
        if not self.doc_watching:
            App.addDocumentObserver(self.doc_watch)
            self.doc_watching = True

    def _preselected(self):
        for sel in Gui.Selection.getSelectionEx("", 0):
            obj = sel.Object
            subs = sel.SubElementNames or ("",)
            for sub in subs:
                found = self._reference(sel.DocumentName, obj, sub)
                if found is not None:
                    ref, name, place = found
                    s = self.settings
                    s.ref, s.ref_name, s.ref_place = ref, name, place
                    s.offset = s.rx = s.ry = 0.0
                    return True
        return False

    def _reference(self, doc_name, obj, sub):
        """(ref, shown name, placement) for a picked plane or flat face, else None."""
        target, element = obj, sub
        if sub and "." in sub:
            try:
                target = obj.getSubObject(sub.rsplit(".", 1)[0] + ".", retType=1) or obj
            except Exception:
                target = obj
            element = sub.rsplit(".", 1)[1]
        place = plane_placement(target)
        if place is not None and not element.startswith("Face"):
            role = getattr(target, "Role", "")
            names = {"XZ_Plane": "Front Plane", "XY_Plane": "Top Plane", "YZ_Plane": "Right Plane"}
            if role in names:
                return ("std", names[role].split()[0]), names[role], None
            return ("plane", doc_name, target.Name), target.Label, place
        if element.startswith("Face"):
            place = face_placement(obj, sub)
            if place is not None:
                return ("face", doc_name, obj.Name, sub), "Face<%s>" % element[4:], place
        return None

    def picked(self, doc, obj_name, sub, pnt=None):
        if self.panel is None:
            return
        try:
            obj = App.getDocument(doc).getObject(obj_name)
        except Exception:
            obj = None
        if obj is not None:
            from . import sectionmore
            if sectionmore.picked(self, doc, obj, sub, pnt):
                Gui.Selection.clearSelection()
                return
        found = self._reference(doc, obj, sub) if obj is not None else None
        Gui.Selection.clearSelection()
        if found is None:
            return
        ref, name, place = found
        if ref[0] == "std":
            self.panel.pick_standard(ref[1])
        else:
            self.panel.pick_reference(ref, name, place)

    def changed(self, caps_now=True):
        if self.section is not None:
            self.section.update(caps_now=caps_now)

    def model_changed(self):
        if self.section is not None and self.section.attached:
            self._model_timer.start()

    def _model_update(self):
        if self.section is not None and self.section.attached and self._view_alive():
            self.section.update()

    def finish(self, ok):
        if self.panel is None:
            return
        self.panel = None
        if self.sel_watch is not None:
            try:
                Gui.Selection.removeObserver(self.sel_watch)
            except Exception as _fw_err:
                _fw_log("sectionview.py:1231", _fw_err)
            self.sel_watch = None
        if ok:
            if self.section is not None:
                self.section.on_drag = None
                self.section.set_editing(False)
        else:
            if self.saved is not None:
                self.settings.__dict__.update(self.saved.__dict__)
            self.turn_off()
        self.saved = None
        QtCore.QTimer.singleShot(0, self.sync_button)

    def turn_off(self):
        if self.section is not None:
            self.section.detach()
            self.section = None
        if self.doc_watching:
            try:
                App.removeDocumentObserver(self.doc_watch)
            except Exception as _fw_err:
                _fw_log("sectionview.py:1252", _fw_err)
            self.doc_watching = False
        self.sync_button()


def _active_3d_view():
    try:
        gdoc = Gui.ActiveDocument
        view = gdoc.ActiveView if gdoc is not None else None
        view.getSceneGraph()
        return view
    except Exception:
        return None


_controller = None


def controller():
    global _controller
    if _controller is None:
        _controller = Controller()
    return _controller


class SectionViewCommand:
    def GetResources(self):
        # The key makes the button checkable (pressed while a section is shown); False = not pressed at start.
        return {"MenuText": TITLE,
                "ToolTip": "Cuts the model open along planes or faces to look inside.",
                "Pixmap": "Std_ToggleClipPlane",
                # usable inside a sketch or another PropertyManager; no undo step (it changes no feature)
                "CmdType": "Alter3DView|ForEdit|NoTransaction",
                "Checkable": False}

    def IsActive(self):
        return coin is not None and _active_3d_view() is not None

    def Activated(self, checked=None):
        controller().button(checked)


def menu_items(have):
    ""

    if COMMAND not in have:
        return []
    return [{"insert": COMMAND, "menuItem": "Std_ToggleClipPlane"}]


def register():
    """Adds the Section View command (once)."""
    if coin is None:
        return
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, SectionViewCommand())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (COMMAND, error))


register()
