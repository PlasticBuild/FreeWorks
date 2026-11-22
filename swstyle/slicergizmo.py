"""The slicers' gizmos on the part while Move, Rotate or Scale is on: arrows to drag along X / Y,
rings to turn about X / Y / Z, handles to stretch along X / Y / Z or (the corner) all ways at once.
Drawn in the plate's scene, over the part; dragged through the plate's own mouse callbacks."""

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

COLOURS = {"x": (0.89, 0.18, 0.15), "y": (0.25, 0.70, 0.22), "z": (0.20, 0.45, 0.95), "all": (0.35, 0.35, 0.35)}
HOVER = (1.0, 0.62, 0.1)
AXES = {"x": App.Vector(1, 0, 0), "y": App.Vector(0, 1, 0), "z": App.Vector(0, 0, 1)}


class Gizmo:
    def __init__(self, bed):
        self.bed = bed
        self.mode = None          # "move" | "rotate" | "scale"
        self.sep = None
        self.handles = {}         # (kind, axis) -> SoSeparator
        self.anchors = {}         # (kind, axis) -> a world point on the handle (for tests and tips)
        self.drag = None          # what a drag started from
        self.centre = App.Vector()
        self.box = None

    # ------------------------------------------------------------------ drawing
    def set_mode(self, mode):
        self.mode = mode
        self.drag = None
        self.update()

    def clear(self):
        if self.sep is not None and self.bed.root is not None:
            try:
                self.bed.root.removeChild(self.sep)
            except Exception as _fw_err:
                _fw_log("slicergizmo.py:47", _fw_err)
        self.sep = None
        self.handles = {}
        self.anchors = {}

    def world_box(self):
        import Mesh
        out = Mesh.Mesh()
        for it in self.bed.targets():
            m = it.mesh.copy()
            m.transform(self.bed.world_matrix(it))
            out.addMesh(m)
        return out.BoundBox if out.CountFacets else None

    def update(self):
        """Redraw around the selection (or every object): called when objects move or the
        selection changes."""
        from pivy import coin
        self.clear()
        if self.mode is None or self.bed.root is None or not self.bed.items:
            return
        box = self.world_box()
        if box is None:
            return
        self.box = box
        self.centre = App.Vector(box.Center)
        size = max(box.XLength, box.YLength, box.ZLength, 10.0)
        self.sep = coin.SoSeparator()
        self.sep.setName("SWStyle_SlicerGizmo")
        try:
            # over the part, as the slicers draw their gizmos
            depth = coin.SoDepthBuffer()
            depth.test.setValue(False)
            self.sep.addChild(depth)
        except AttributeError as _fw_err:
            _fw_log("slicergizmo.py:82", _fw_err)
        light = coin.SoLightModel()
        light.model.setValue(coin.SoLightModel.BASE_COLOR)
        self.sep.addChild(light)
        getattr(self, "_draw_" + self.mode)(coin, box, size)
        if self.drag is not None and self.drag["key"] in self.handles:
            self.handles[self.drag["key"]].getChild(0).rgb.setValue(*HOVER)
        self.bed.root.addChild(self.sep)

    def _handle(self, coin, kind, axis, colour=None):
        h = coin.SoSeparator()
        h.setName("SWStyle_Gizmo_%s_%s" % (kind, axis))
        mat = coin.SoBaseColor()
        mat.rgb.setValue(*(colour or COLOURS[axis]))
        h.addChild(mat)
        self.handles[(kind, axis)] = h
        self.sep.addChild(h)
        return h

    @staticmethod
    def _xf(coin, pos, rot=None):
        t = coin.SoTransform()
        t.translation.setValue(pos.x, pos.y, pos.z)
        if rot is not None:
            q = rot.Q
            t.rotation.setValue(q[0], q[1], q[2], q[3])
        return t

    def _draw_move(self, coin, box, size):
        c = self.centre
        reach = max(box.XLength, box.YLength) / 2.0 + max(15.0, size * 0.4)
        thick = max(1.0, size * 0.025)
        for axis in ("x", "y"):
            h = self._handle(coin, "move", axis)
            # Coin's cylinder and cone stand along +Y: turn them onto the axis
            rot = App.Rotation(App.Vector(0, 1, 0), AXES[axis])
            h.addChild(self._xf(coin, c + AXES[axis] * (reach / 2.0), rot))
            self.anchors[("move", axis)] = c + AXES[axis] * (reach * 0.8)
            shaft = coin.SoCylinder()
            shaft.radius.setValue(thick)
            shaft.height.setValue(reach)
            h.addChild(shaft)
            tip = coin.SoTransform()
            tip.translation.setValue(0, reach / 2.0 + thick * 3, 0)
            h.addChild(tip)
            cone = coin.SoCone()
            cone.bottomRadius.setValue(thick * 3)
            cone.height.setValue(thick * 6)
            h.addChild(cone)

    def _draw_rotate(self, coin, box, size):
        c = self.centre
        radius = math.sqrt(box.XLength ** 2 + box.YLength ** 2 + box.ZLength ** 2) / 2.0 + 4
        for axis in ("x", "y", "z"):
            h = self._handle(coin, "rotate", axis)
            style = coin.SoDrawStyle()
            style.lineWidth.setValue(3)
            h.addChild(style)
            rot = App.Rotation(App.Vector(0, 0, 1), AXES[axis])
            pts = []
            for k in range(73):
                a = 2 * math.pi * k / 72
                p = c + rot.multVec(App.Vector(radius * math.cos(a), radius * math.sin(a), 0))
                pts.append((p.x, p.y, p.z))
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, len(pts), pts)
            h.addChild(coords)
            line = coin.SoLineSet()
            line.numVertices.setValue(len(pts))
            h.addChild(line)
            self.anchors[("rotate", axis)] = App.Vector(*pts[9])
        self.radius = radius

    def _scale_points(self, box):
        c = self.centre
        return {"x": App.Vector(box.XMax, c.y, c.z), "y": App.Vector(c.x, box.YMax, c.z),
                "z": App.Vector(c.x, c.y, box.ZMax), "all": App.Vector(box.XMax, box.YMax, box.ZMax)}

    def _draw_scale(self, coin, box, size):
        s = max(2.5, size * 0.07)
        # the box outline, as the slicers show it while scaling
        out = coin.SoSeparator()
        col = coin.SoBaseColor()
        col.rgb.setValue(0.6, 0.6, 0.6)
        out.addChild(col)
        x0, y0, z0, x1, y1, z1 = box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax
        corners = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z0),
                   (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1), (x0, y0, z1)]
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(corners), corners)
        out.addChild(coords)
        line = coin.SoLineSet()
        line.numVertices.setValue(len(corners))
        out.addChild(line)
        self.sep.addChild(out)
        for axis, p in self._scale_points(box).items():
            h = self._handle(coin, "scale", axis)
            h.addChild(self._xf(coin, p))
            self.anchors[("scale", axis)] = App.Vector(p)
            cube = coin.SoCube()
            cube.width.setValue(s)
            cube.height.setValue(s)
            cube.depth.setValue(s)
            h.addChild(cube)

    # ------------------------------------------------------------------ dragging
    def _hit(self, pos):
        from pivy import coin
        if not self.handles or self.bed.view is None:
            return None
        manager = self.bed.view.getViewer().getSoRenderManager()
        pick = coin.SoRayPickAction(manager.getViewportRegion())
        pick.setPoint(coin.SbVec2s(int(pos[0]), int(pos[1])))
        pick.setRadius(5)
        pick.setPickAll(True)
        pick.apply(manager.getSceneGraph())
        # where handles overlap on screen, the one whose picked point is nearest the cursor wins
        best, best_d = None, None
        for hit in pick.getPickedPointList():
            path = hit.getPath()
            for key, node in self.handles.items():
                if path.containsNode(node):
                    p = hit.getPoint()
                    try:
                        sx, sy = self.bed.view.getPointOnScreen(App.Vector(p[0], p[1], p[2]))
                        d = (sx - pos[0]) ** 2 + (sy - pos[1]) ** 2
                    except Exception:
                        d = 0.0
                    if best_d is None or d < best_d:
                        best, best_d = key, d
        return best

    def press(self, pos):
        """A press on a handle starts a drag (True); anything else is the plate's."""
        key = self._hit(pos)
        if key is None:
            return False
        kind, axis = key
        targets = self.bed.targets()
        start = {"key": key, "items": [(it, App.Rotation(it.rotation), App.Vector(it.scale),
                                        it.xy if it.xy is not None else self.bed.bed_centre()) for it in targets],
                 "centre": App.Vector(self.centre), "box": self.box}
        point = self._drag_point(pos, key, start)
        if point is None:
            return False
        start["point"] = point
        self.drag = start
        node = self.handles.get(key)
        if node is not None:
            node.getChild(0).rgb.setValue(*HOVER)
        return True

    def _drag_point(self, pos, key, start):
        kind, axis = key
        ray = self.bed.ray(pos)
        if ray is None:
            return None
        p, d = ray
        c = start["centre"]
        if kind == "rotate":
            return _plane_hit(p, d, c, AXES[axis])
        if kind == "move":
            return _plane_hit(p, d, c, AXES["z"])
        u = (self._scale_points(start["box"])["all"] - c) if axis == "all" else AXES[axis]
        return _closest_on_line(p, d, c, u)

    def motion(self, pos):
        if self.drag is None:
            return False
        key = self.drag["key"]
        kind, axis = key
        point = self._drag_point(pos, key, self.drag)
        if point is None:
            return True
        c = self.drag["centre"]
        if kind == "move":
            delta = point - self.drag["point"]
            dist = delta.dot(AXES[axis])
            for it, _, _, xy in self.drag["items"]:
                it.xy = (xy[0] + (dist if axis == "x" else 0.0), xy[1] + (dist if axis == "y" else 0.0))
        elif kind == "rotate":
            a, b = self.drag["point"] - c, point - c
            if a.Length < 1e-6 or b.Length < 1e-6:
                return True
            n = AXES[axis]
            angle = math.degrees(math.atan2(a.cross(b).dot(n), a.dot(b)))
            if abs(angle) > 0.5:
                # whole degrees, as the slicers' ring snaps
                angle = round(angle)
            for it, rot, _, _ in self.drag["items"]:
                it.rotation = App.Rotation(n, angle).multiply(rot)
        else:
            u = (self._scale_points(self.drag["box"])["all"] - c) if axis == "all" else AXES[axis]
            u = App.Vector(u)
            u.normalize()
            d0 = (self.drag["point"] - c).dot(u)
            d1 = (point - c).dot(u)
            if abs(d0) < 1e-6:
                return True
            f = max(0.01, d1 / d0)
            for it, _, scale, _ in self.drag["items"]:
                if axis == "all":
                    it.scale = App.Vector(scale.x * f, scale.y * f, scale.z * f)
                else:
                    # per axis in the object's own frame, as the slicers' handles
                    local = it.rotation.inverted().multVec(AXES[axis])
                    k = max(range(3), key=lambda i: abs(local[i]))
                    v = [scale.x, scale.y, scale.z]
                    v[k] *= f
                    it.scale = App.Vector(*v)
        self.bed._changed_quiet()
        return True

    def release(self):
        if self.drag is None:
            return False
        self.drag = None
        self.bed._replate()
        self.bed._changed()
        return True


def _plane_hit(p, d, c, n):
    den = d.dot(n)
    if abs(den) < 1e-9:
        return None
    t = (c - p).dot(n) / den
    return p + d * t


def _closest_on_line(p, d, c, u):
    """The point on the line c + s·u nearest the ray p + t·d."""
    u = App.Vector(u)
    if u.Length < 1e-9:
        return None
    u.normalize()
    d = App.Vector(d)
    d.normalize()
    w = c - p
    b = u.dot(d)
    den = 1 - b * b
    if abs(den) < 1e-9:
        return None
    s = (b * w.dot(d) - w.dot(u)) / den
    return c + u * s
