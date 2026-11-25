"""Brim ears on the plate toolbar, as the slicers' Brim Ears tool: click an object to put a round ear of brim on the
bed where it stands (the ear always lies on the bed, under the point clicked), right-click an ear to take it away.
Auto-generate puts one at each sharp corner of the object's first layer (sharper than Max angle, after smoothing
the outline by Detection radius), as the slicers do. The ears go to the slicer as its own brim ear points
(Metadata/brim_ear_points.txt in the plate's 3MF, written by slicerpaint.write_plate); the slicer prints them when the object's brim type is Painted,
and the panel offers to set that. An ear that touches neither the object nor another ear that does is marked
invalid (red), as the slicers mark it: the slicer leaves it out."""
import math

import FreeCAD as App
from PySide import QtCore, QtWidgets

EAR_COLOUR = (0.88, 0.88, 0.90)
BAD_COLOUR = (0.86, 0.20, 0.18)
MIN_DIAMETER, MAX_DIAMETER = 5.0, 20.0          # the slicers' Head diameter range
DEFAULT_MAX_ANGLE, DEFAULT_DETECTION = 125.0, 1.0
EAR_Z = -0.0001                                  # the slicers put the ear point just under the bed


# ---------------------------------------------------------------------- data
def ears_of(item):
    """The item's ears: [(x, y, z, radius)] in model coordinates (z = the bed under the object)."""
    p = getattr(item, "paint", None)
    if p is None:
        from . import slicerpaint
        p = slicerpaint.paint_of(item)
    return p.setdefault("ears", [])


def default_diameter(panel):
    """The slicers' default ear: 16 first-layer line widths, within the Head diameter range."""
    from . import slicer as backend, slicerobject
    nozzle = 0.4
    try:
        m = dict(panel.slicer.resolve("machine", panel.choice["printer"]))
        m.update(panel.choice.get("printer_overrides") or {})
        nozzle = backend._number(m.get("nozzle_diameter"), 0.4)
    except Exception:
        pass
    width = nozzle
    try:
        raw = str(backend._first(slicerobject.effective_process(panel).get("initial_layer_line_width", "")) or "")
        if raw.endswith("%"):
            width = nozzle * float(raw[:-1]) / 100.0
        elif raw and float(raw) > 0:
            width = float(raw)
    except (ValueError, TypeError):
        pass
    return max(MIN_DIAMETER, min(MAX_DIAMETER, round(width * 16.0, 1)))


def file_text(points_by_object):
    """Metadata/brim_ear_points.txt (the slicers' format): points_by_object = [(object number 1-based,
    [(x, y, z, radius)] in the object's coordinates as the slicer holds them)]."""
    rows = []
    for number, pts in points_by_object:
        if pts:
            rows.append("object_id=%d|%s" % (number, " ".join("%f %f %f %f" % tuple(p) for p in pts)))
    if not rows:
        return ""
    return "brim_points_format_version=0\n" + "\n".join(rows) + "\n"


def placed(ears, matrix):
    """Ears in plate coordinates, on the bed: [(x, y, z, radius)]."""
    m = matrix if isinstance(matrix, App.Matrix) else App.Matrix(*matrix)
    out = []
    for x, y, z, r in ears:
        p = m.multVec(App.Vector(x, y, z))
        out.append((p.x, p.y, EAR_Z, r))
    return out


# ---------------------------------------------------------------------- the first layer
def _area(loop):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(loop, loop[1:] + loop[:1]))


def _inside(pt, loop):
    x, y = pt
    inside = False
    for (x1, y1), (x2, y2) in zip(loop, loop[1:] + loop[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def first_layer(mesh, height=0.1):
    """The outline of a mesh standing on the bed at the first layer: [(outer loop, [hole loops])], each loop
    counter-clockwise [(x, y)], as the slicers' outline at 0.1 mm."""
    z = mesh.BoundBox.ZMin + height
    loops = []
    for poly in mesh.crossSections([((0, 0, z), (0, 0, 1))], 1e-4)[0]:
        pts = [(p.x, p.y) for p in poly]
        if len(pts) > 1 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-6:
            pts = pts[:-1]
        if len(pts) >= 3 and abs(_area(pts)) > 1e-6:
            if _area(pts) < 0:
                pts.reverse()
            loops.append(pts)
    depth = [sum(1 for j, other in enumerate(loops) if j != i and _inside(loop[0], other))
             for i, loop in enumerate(loops)]
    out = []
    for i, loop in enumerate(loops):
        if depth[i] % 2 == 0:
            holes = [h for j, h in enumerate(loops) if depth[j] == depth[i] + 1 and _inside(h[0], loop)]
            out.append((loop, holes))
    return out


def _seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 <= 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / l2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def _simplify(points, tol):
    """Douglas-Peucker on an open polyline."""
    if len(points) < 3:
        return list(points)
    a, b = points[0], points[-1]
    k, best = 0, -1.0
    for i in range(1, len(points) - 1):
        d = _seg_dist(points[i], a, b)
        if d > best:
            k, best = i, d
    if best <= tol:
        return [a, b]
    return _simplify(points[:k + 1], tol)[:-1] + _simplify(points[k:], tol)


def corners(loop, max_angle=DEFAULT_MAX_ANGLE, detection=DEFAULT_DETECTION, outer=True):
    """The slicers' auto ears of one counter-clockwise loop: after smoothing by detection (mm), the corners whose
    angle is under max_angle (degrees) - convex ones of an outline, the other turn of a hole."""
    pts = list(loop)
    if pts:
        # start at a sure corner (the point farthest from the middle): the smoothing keeps the start point
        mx, my = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        k = max(range(len(pts)), key=lambda i: (pts[i][0] - mx) ** 2 + (pts[i][1] - my) ** 2)
        pts = pts[k:] + pts[:k]
    if detection > 0:
        closed = _simplify(pts + pts[:1], detection)
        pts = closed[:-1] if len(closed) > 4 else closed
    threshold = math.radians(180.0 - max_angle)
    cos_t = math.cos(threshold + 1e-12)
    out = []
    n = len(pts)
    for i in range(n):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
        v1 = (p1[0] - p0[0], p1[1] - p0[1])
        v2 = (p2[0] - p1[0], p2[1] - p1[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 < 1e-9 or l2 < 1e-9:
            continue
        cross = v1[0] * v2[1] - v1[1] * v2[0]
        if (cross > 0) != outer or cross == 0:
            continue
        if (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2) < cos_t:
            out.append(p1)
    return out


def _dist_to_region(pt, layer):
    """0 inside the first layer, else the distance to its outline."""
    for outer, holes in layer:
        if _inside(pt, outer) and not any(_inside(pt, h) for h in holes):
            return 0.0
    best = float("inf")
    for outer, holes in layer:
        for loop in [outer] + holes:
            for a, b in zip(loop, loop[1:] + loop[:1]):
                best = min(best, _seg_dist(pt, a, b))
    return best


def invalid(points, layer):
    """Indexes of the ears (x, y, radius on the bed) that touch neither the first layer nor an ear that does."""
    good = set()
    for i, (x, y, r) in enumerate(points):
        if _dist_to_region((x, y), layer) < r:
            good.add(i)
    grew = True
    while grew:
        grew = False
        for i, (x, y, r) in enumerate(points):
            if i in good:
                continue
            if any(math.hypot(x - points[j][0], y - points[j][1]) < r + points[j][2] for j in good):
                good.add(i)
                grew = True
    return [i for i in range(len(points)) if i not in good]


# ---------------------------------------------------------------------- the tool
class EarTool:
    """The Brim Ears tool's clicks on the plate: left click adds, right click takes away."""

    def __init__(self, toolbar):
        self.toolbar, self.bed, self.panel = toolbar, toolbar.bed, toolbar.panel
        self.diameter = default_diameter(self.panel)
        self.max_angle, self.detection = DEFAULT_MAX_ANGLE, DEFAULT_DETECTION
        self.callback = None
        self.node = None
        self.bad = []                    # (item, index) of the invalid ears
        self.start()
        self.show()

    def start(self):
        from pivy import coin
        bed = self.bed
        if bed.view is None:
            return
        bed.stop_pick()
        bed.picking = self

        def button(cb):
            ev = cb.getEvent()
            if ev.getState() != coin.SoButtonEvent.DOWN:
                return
            if ev.getButton() == coin.SoMouseButtonEvent.BUTTON1:
                if self.click(ev.getPosition()):
                    cb.setHandled()
            elif ev.getButton() == coin.SoMouseButtonEvent.BUTTON2:
                if self.right_click(ev.getPosition()):
                    cb.setHandled()
        self.callback = bed.view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), button)

    def stop(self):
        from pivy import coin
        if self.callback is not None and self.bed.view is not None:
            try:
                self.bed.view.removeEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self.callback)
            except Exception as error:
                App.Console.PrintLog("slicer brim ears: %s\n" % error)
        self.callback = None
        if self.bed.picking is self:
            self.bed.picking = None
        self._remove_node()

    # -------------------------------------------------------------- edits
    def click(self, pos):
        hit = self.bed._pick(pos)
        if hit is None:
            return False
        item = self.bed.items[hit[0]]
        return self.add(item, hit[2])

    def add(self, item, world_point, diameter=None):
        """An ear under a point (world coordinates) for an object."""
        o = self.bed.plate_origin(item.plate)
        inv = self.bed.item_matrix(item).inverse()
        p = inv.multVec(App.Vector(world_point.x - o.x, world_point.y - o.y, 0.0))
        ear = (round(p.x, 4), round(p.y, 4), round(p.z, 4), float(diameter or self.diameter) / 2.0)
        ears = ears_of(item)
        if ear in ears:
            return True
        ears.append(ear)
        self._changed()
        return True

    def right_click(self, pos):
        """Take away the ear under a screen position; False when there is none."""
        found = self.ear_at(pos)
        if found is None:
            return False
        item, k = found
        del ears_of(item)[k]
        self._changed()
        return True

    def ear_at(self, pos):
        point = self.bed.bed_point(pos, 0.0)
        if point is None:
            return None
        best = None
        for item in self.bed.items:
            o = self.bed.plate_origin(item.plate)
            for k, (x, y, _z, r) in enumerate(placed(ears_of(item), self.bed.item_matrix(item))):
                d = math.hypot(point.x - o.x - x, point.y - o.y - y)
                if d <= r and (best is None or d < best[0]):
                    best = (d, item, k)
        return None if best is None else (best[1], best[2])

    def auto(self, items=None):
        """Auto-generate: an ear at each sharp corner of the objects' first layer (the selected ones, or all)."""
        added = 0
        for item in (items if items is not None else self._targets()):
            mesh = item.mesh.copy()
            m = self.bed.item_matrix(item)
            mesh.transform(m)
            inv = m.inverse()
            ears = ears_of(item)
            for outer, holes in first_layer(mesh):
                pts = corners(outer, self.max_angle, self.detection, True)
                for h in holes:
                    pts += corners(h, self.max_angle, self.detection, False)
                for x, y in pts:
                    p = inv.multVec(App.Vector(x, y, 0.0))
                    ear = (round(p.x, 4), round(p.y, 4), round(p.z, 4), self.diameter / 2.0)
                    if ear not in ears:
                        ears.append(ear)
                        added += 1
        if added:
            self._changed()
        return added

    def remove_all(self, items=None):
        changed = False
        for item in (items if items is not None else self._targets()):
            if ears_of(item):
                ears_of(item)[:] = []
                changed = True
        if changed:
            self._changed()
        return changed

    def set_diameter(self, value):
        """The Head diameter: for new ears, and for every ear of the objects the tool acts on (as the slicers' slider
        sets the selected ears, all of them when none is picked)."""
        self.diameter = max(MIN_DIAMETER, min(MAX_DIAMETER, float(value)))
        changed = False
        for item in self._targets():
            ears = ears_of(item)
            new = [(x, y, z, self.diameter / 2.0) for x, y, z, _r in ears]
            if new != ears:
                ears[:] = new
                changed = True
        if changed:
            self._changed()

    def _targets(self):
        its = self.bed.targets()
        return its if its else list(self.bed.items)

    def _changed(self):
        self.show()
        self.panel._stale()
        p = self.toolbar.tool_panel
        if p is not None and hasattr(p, "fill"):
            p.fill(self)

    # -------------------------------------------------------------- brim type
    def brim_type(self, item):
        from . import slicer as backend, slicerobject
        own = (getattr(item, "settings", None) or {}).get("brim_type")
        if own:
            return str(backend._first(own))
        return str(backend._first(slicerobject.effective_process(self.panel).get("brim_type", "auto_brim"))
                   or "auto_brim")

    def not_painted(self):
        """The objects with ears whose brim type is not Painted (their ears would not print)."""
        return [it for it in self.bed.items if ears_of(it) and self.brim_type(it) != "painted"]

    def set_painted(self):
        """Set the brim type of the objects with ears to Painted (their own setting, as the slicers' button does)."""
        its = self.not_painted()
        for it in its:
            it.settings["brim_type"] = "painted"
        if its:
            self.panel._object_changed(True)
            p = self.toolbar.tool_panel
            if p is not None and hasattr(p, "fill"):
                p.fill(self)
        return len(its)

    # -------------------------------------------------------------- on the plate
    def _remove_node(self):
        root = self.bed.root
        if self.node is not None and root is not None:
            try:
                root.removeChild(self.node)
            except Exception:
                pass
        self.node = None

    def show(self):
        from pivy import coin
        self._remove_node()
        self.bad = []
        root = self.bed.root
        if root is None:
            return
        sep = coin.SoSeparator()
        sep.setName("SWStyle_SlicerBrimEars")
        for item in self.bed.items:
            ears = placed(ears_of(item), self.bed.item_matrix(item))
            if not ears:
                continue
            mesh = item.mesh.copy()
            mesh.transform(self.bed.item_matrix(item))
            bad = set(invalid([(x, y, r) for x, y, _z, r in ears], first_layer(mesh)))
            self.bad += [(item, k) for k in sorted(bad)]
            o = self.bed.plate_origin(item.plate)
            for k, (x, y, _z, r) in enumerate(ears):
                one = coin.SoSeparator()
                t = coin.SoTranslation()
                t.translation = (o.x + x, o.y + y, 0.15)
                one.addChild(t)
                turn = coin.SoRotationXYZ()
                turn.axis = coin.SoRotationXYZ.X
                turn.angle = math.pi / 2.0
                one.addChild(turn)
                mat = coin.SoMaterial()
                mat.diffuseColor = BAD_COLOUR if k in bad else EAR_COLOUR
                mat.transparency = 0.35
                one.addChild(mat)
                disc = coin.SoCylinder()
                disc.radius = r
                disc.height = 0.3
                one.addChild(disc)
                sep.addChild(one)
        if sep.getNumChildren():
            root.addChild(sep)
            self.node = sep


def panel(toolbar, ToolPanel):
    """The Brim Ears tool panel."""
    tool = toolbar.ears
    p = ToolPanel("Brim Ears", toolbar.parentWidget())
    p.setObjectName("SWSlicerToolPanel")
    hint = QtWidgets.QLabel("Click an object to put an ear on the bed there. Right-click an ear to remove it.")
    hint.setWordWrap(True)
    p.lay.addWidget(hint, p.lay.rowCount(), 0, 1, 4)
    p.diameter = QtWidgets.QDoubleSpinBox()
    p.diameter.setObjectName("SWStyle_SlicerEarDiameter")
    p.diameter.setRange(MIN_DIAMETER, MAX_DIAMETER)
    p.diameter.setDecimals(1)
    p.diameter.setSingleStep(0.5)
    p.diameter.setSuffix(" mm")
    p.diameter.setValue(tool.diameter)
    p.diameter.setToolTip("The size of the ears (new ones, and the ones of the selected objects)")
    p.diameter.valueChanged.connect(tool.set_diameter)
    p.row("Head diameter", p.diameter)
    p.angle = QtWidgets.QDoubleSpinBox()
    p.angle.setObjectName("SWStyle_SlicerEarAngle")
    p.angle.setRange(0.0, 180.0)
    p.angle.setDecimals(0)
    p.angle.setSuffix(" °")
    p.angle.setValue(tool.max_angle)
    p.angle.setToolTip("Auto-generate puts ears at corners sharper than this")
    p.angle.valueChanged.connect(lambda v: setattr(tool, "max_angle", float(v)))
    p.row("Max angle", p.angle)
    p.detection = QtWidgets.QDoubleSpinBox()
    p.detection.setObjectName("SWStyle_SlicerEarDetection")
    p.detection.setRange(0.0, 100.0)
    p.detection.setDecimals(1)
    p.detection.setSingleStep(0.5)
    p.detection.setSuffix(" mm")
    p.detection.setValue(tool.detection)
    p.detection.setToolTip("How much small steps of the outline are smoothed out before looking for corners")
    p.detection.valueChanged.connect(lambda v: setattr(tool, "detection", float(v)))
    p.row("Detection radius", p.detection)
    auto = QtWidgets.QPushButton("Auto-generate")
    auto.setObjectName("SWStyle_SlicerEarAuto")
    auto.setToolTip("Generate brim ears using Max angle and Detection radius")
    auto.clicked.connect(lambda: tool.auto())
    remove = QtWidgets.QPushButton("Remove all")
    remove.setObjectName("SWStyle_SlicerEarRemoveAll")
    remove.setToolTip("Remove the ears of the selected objects (all objects when none is selected)")
    remove.clicked.connect(lambda: tool.remove_all())
    r = p.lay.rowCount()
    p.lay.addWidget(auto, r, 0, 1, 2)
    p.lay.addWidget(remove, r, 2, 1, 2)
    p.count = QtWidgets.QLabel("")
    p.lay.addWidget(p.count, p.lay.rowCount(), 0, 1, 4)
    p.warn = QtWidgets.QLabel("")
    p.warn.setObjectName("SWStyle_SlicerEarWarning")
    p.warn.setWordWrap(True)
    p.warn.setStyleSheet("color: #d9822b;")
    p.lay.addWidget(p.warn, p.lay.rowCount(), 0, 1, 4)
    p.set_painted = QtWidgets.QPushButton("Set the brim type to Painted")
    p.set_painted.setObjectName("SWStyle_SlicerEarSetPainted")
    p.set_painted.setToolTip("The objects with ears get Brim type: Painted in their own settings")
    p.set_painted.clicked.connect(lambda: tool.set_painted())
    p.lay.addWidget(p.set_painted, p.lay.rowCount(), 0, 1, 4)

    def fill(t):
        n = sum(len(ears_of(it)) for it in toolbar.bed.items)
        p.count.setText("%d ear%s on the plate" % (n, "" if n == 1 else "s") if n else "No ears yet")
        rows = []
        off = t.not_painted()
        if off:
            rows.append('The brim type is not set to "Painted", so these ears will not print.')
        if t.bad:
            rows.append("%d invalid brim ear%s (red): %s the object, so the slicer leaves %s out." % (
                len(t.bad), "" if len(t.bad) == 1 else "s", "it does not touch" if len(t.bad) == 1 else
                "they do not touch", "it" if len(t.bad) == 1 else "them"))
        p.warn.setText("\n".join(rows))
        p.warn.setVisible(bool(rows))
        p.set_painted.setVisible(bool(off))
        toolbar.place()
    p.fill = fill
    p.setMinimumWidth(300)
    fill(tool)
    return p
