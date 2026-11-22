"""The prime tower on the plate, as the slicers show it: a see-through box on each plate that prints with more than
one filament, where the slicer will put the tower. Drag it to move it (it then stays where it was put, as in the
slicers); left alone, it takes a free corner of the plate, the spot the slice uses too. The slice gets its
position as the slicers' wipe_tower_x / wipe_tower_y."""
import FreeCAD as App

from . import slicer as backend

TOWER_COLOUR = (0.55, 0.55, 0.60)


def _on(value):
    v = value[0] if isinstance(value, list) and value else value
    return str(v).strip().lower() in ("1", "true")


class Tower:
    def __init__(self, panel):
        self.panel = panel
        self.bed = panel.bed
        self.spots = {}             # plate -> (x, y) put there by hand (bed coordinates, the tower's front-left corner)
        self.node = None
        self.parts = {}             # plate -> (separator, translation)
        self.drag = None            # (plate, last bed point) while dragging

    # ------------------------------------------------------------------ where and when
    def process(self):
        from . import slicerobject
        try:
            return slicerobject.effective_process(self.panel)
        except Exception:
            return {}

    def machine(self):
        try:
            m = dict(self.panel.slicer.resolve("machine", self.panel.choice["printer"]))
            m.update(self.panel.choice.get("printer_overrides") or {})
            return m
        except Exception:
            return {}

    def needed(self):
        """The plates whose slice prints more than one filament (and the process has its prime tower on)."""
        from . import slicerpaint, slicercodes
        slots = getattr(self.panel, "slots", None)
        if slots is None or slots.count() < 2 or not _on(self.process().get("enable_prime_tower", "1")):
            return []
        out = []
        for p in range(len(self.bed.plates)):
            items = [it for it in self.bed.items if it.plate == p]
            if not items:
                continue
            used = {it.slot for it in items} | {p["slot"] for it in items for p in (it.parts or []) if p.get("slot")}
            painted = any((slicerpaint.paint_of(it)["color"] or slicerpaint.paint_of(it)["dabs"]["color"]) for it in items
                          if it.paint)
            changes = any(c["type"] == slicercodes.TOOL_CHANGE for c in slicercodes.codes(self.panel, p))
            if len(used) > 1 or painted or changes:
                out.append(p)
        return out

    def size(self):
        proc = self.process()
        width = backend._number(proc.get("prime_tower_width"), 35.0)
        return width, max(width, 60.0)          # the depth the slice keeps free for it (slicer.prime_tower_spots)

    def boxes(self, plate):
        """The plate's objects' boxes, bed coordinates."""
        out = []
        for it in self.bed.items:
            if it.plate == plate:
                m = it.mesh.copy()
                m.transform(self.bed.item_matrix(it))
                out.append(m.BoundBox)
        return out

    def auto_spot(self, plate):
        spots = backend.prime_tower_spots(None, self.machine(), self.process(), self.panel.choice.get("overrides"),
                                          boxes=[self.boxes(plate)])
        return tuple(spots[0]) if spots else None

    def spot(self, plate):
        return self.spots.get(plate) or self.auto_spot(plate)

    def fixed(self, kept):
        """{index among the plates sliced: (x, y)} of the towers put by hand."""
        return {kept.index(p): xy for p, xy in self.spots.items() if p in kept}

    # ------------------------------------------------------------------ on the plate
    def refresh(self):
        from pivy import coin
        root = self.bed.root
        if self.node is not None and root is not None:
            try:
                root.removeChild(self.node)
            except Exception:
                pass
        self.node, self.parts = None, {}
        if root is None:
            return
        plates = self.needed()
        if not plates:
            return
        width, depth = self.size()
        sep = coin.SoSeparator()
        sep.setName("SWStyle_SlicerPrimeTower")
        for p in plates:
            xy = self.spot(p)
            if xy is None:
                continue
            height = max([b.ZMax for b in self.boxes(p)] + [5.0])
            o = self.bed.plate_origin(p)
            one = coin.SoSeparator()
            one.setName("SWStyle_SlicerPrimeTower%d" % p)
            t = coin.SoTranslation()
            t.translation = (o.x + xy[0] + width / 2.0, o.y + xy[1] + depth / 2.0, height / 2.0)
            one.addChild(t)
            mat = coin.SoMaterial()
            mat.diffuseColor = TOWER_COLOUR
            mat.transparency = 0.45
            one.addChild(mat)
            cube = coin.SoCube()
            cube.width, cube.height, cube.depth = width, depth, height
            one.addChild(cube)
            sep.addChild(one)
            self.parts[p] = (one, t)
        root.addChild(sep)
        self.node = sep

    def _hit(self, pos):
        from pivy import coin
        if self.node is None or self.bed.view is None:
            return None
        viewer = self.bed.view.getViewer()
        manager = viewer.getSoRenderManager()
        pick = coin.SoRayPickAction(manager.getViewportRegion())
        if not isinstance(pos, coin.SbVec2s):
            pos = coin.SbVec2s(int(pos[0]), int(pos[1]))
        pick.setPoint(pos)
        pick.setRadius(2)
        pick.apply(manager.getSceneGraph())
        hit = pick.getPickedPoint()
        if hit is None:
            return None
        path = hit.getPath()
        for p, (one, _t) in self.parts.items():
            if path.containsNode(one):
                return p
        return None

    def press(self, pos):
        p = self._hit(pos)
        if p is None:
            return False
        point = self.bed.bed_point(pos, 0.0)
        if point is None:
            return False
        self.spots[p] = self.spot(p)
        self.drag = (p, point)
        return True

    def motion(self, pos):
        if self.drag is None:
            return False
        p, last = self.drag
        point = self.bed.bed_point(pos, 0.0)
        if point is None:
            return True
        self.move(p, point.x - last.x, point.y - last.y)
        self.drag = (p, point)
        return True

    def move(self, plate, dx, dy):
        """Move a plate's tower (kept on the bed)."""
        x0, y0, x1, y1 = self.bed.bed_box()
        width, depth = self.size()
        x, y = self.spot(plate)
        x = max(x0, min(x1 - width, x + dx))
        y = max(y0, min(y1 - depth, y + dy))
        self.spots[plate] = (x, y)
        if plate in self.parts:
            _one, t = self.parts[plate]
            o = self.bed.plate_origin(plate)
            z = t.translation.getValue()[2]
            t.translation = (o.x + x + width / 2.0, o.y + y + depth / 2.0, z)

    def release(self):
        if self.drag is None:
            return False
        self.drag = None
        self.panel._stale()
        return True

    def reset(self, plate=None):
        """Back to its own spot (a free corner)."""
        if plate is None:
            self.spots = {}
        else:
            self.spots.pop(plate, None)
        self.refresh()
