"""The slicer's build plate in FreeCAD's 3D view, like the slicers' Prepare view: the printer's bed
with its grid, the part on it as it will print, and the tools to place it: rotate, lay a face on
the bed, auto orient, move, arrange. The FreeCAD model itself is not changed: while the plate shows,
the model is hidden and a mesh of it stands on the bed; closing the panel brings the model back.

Bed coordinates are the printer's own (printable_area, origin at its corner), so the mesh written
for the slicer is already where it prints (the slicer's --arrange 0)."""

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

BED_COLOUR = (0.24, 0.25, 0.27)      # the slicers' dark textured plate
GRID_COLOUR = (0.45, 0.46, 0.50)
PART_COLOUR = (0.30, 0.60, 0.90)       # an object on the plate
SELECTED_COLOUR = (0.98, 0.62, 0.20)
OVERHANG = math.cos(math.radians(45.0))  # faces steeper down than 45 degrees need support


def parse_points(value):
    """["0x0", "256x0", ...] -> [(x, y), ...]"""
    if isinstance(value, str):
        value = value.split(",")
    out = []
    for item in value or []:
        try:
            x, y = str(item).lower().split("x")
            out.append((float(x), float(y)))
        except ValueError as _fw_err:
            _fw_log("slicerplate.py:42", _fw_err)
    return out


def _highlighting():
    """Support painting's Highlight overhang areas is on (every object is drawn with it, painted or not)."""
    try:
        from . import slicerpaint
        return slicerpaint.HIGHLIGHT.get("angle") is not None
    except Exception:
        return False


class Item:
    """One object on the plate: its shape and mesh in model coordinates, and how it is placed."""

    def __init__(self, name, shape, mesh, source=None):
        self.name = name
        self._shape = shape         # Part shape, model coordinates (sliced from this, as STEP);
                                    # None for a mesh read from a project 3MF (sliced as that mesh)
        self.mesh = mesh            # display / orientation mesh of the shape
        self.source = source        # (doc, object name) of a FreeCAD object, or a file path
        self.rotation = App.Rotation()
        self.scale = App.Vector(1, 1, 1)
        self.xy = None              # centre on its plate (plate coordinates); None = the plate's centre
        self.plate = 0              # which build plate
        self.slot = 1               # which filament slot prints it (1 = the first filament)
        self.settings = {}          # its own process settings (the slicers' object Add Settings)
        self.ranges = []            # height range modifiers: [{"min_z", "max_z", "params"}]
        self.paint = None           # support / seam / colour paint per CAD face (slicerpaint)
        self.parts = None           # Split to parts: [{"name", "slot"}], one per solid (slot 0 = the object's own)
        self.layer_profile = None   # variable layer height [z, h, z, h ...] (slicerlayers), for its placement:
        self.layer_profile_sig = None
        self.pinned = False         # added by hand (another document's part, a file): stays
        self.switch = None
        self.transform = None
        self.material = None

    @property
    def shape(self):
        """The solid (made from the mesh when the object came as a mesh: cut and split need one)."""
        if self._shape is None and self.mesh is not None:
            import Part
            sh = Part.Shape()
            sh.makeShapeFromMesh(self.mesh.Topology, 0.05)
            try:
                sh = Part.makeSolid(sh)
            except Exception as _fw_err:
                _fw_log("slicerplate.py:75", _fw_err)
            self._shape = sh
        return self._shape

    @shape.setter
    def shape(self, value):
        self._shape = value

    def copy(self):
        it = Item(self.name, self._shape, self.mesh, self.source)
        it.rotation = App.Rotation(self.rotation)
        it.scale = App.Vector(self.scale)
        it.xy = self.xy
        it.plate = self.plate
        it.pinned = self.pinned
        it.slot = self.slot
        it.settings = dict(self.settings)
        it.ranges = [dict(r) for r in self.ranges]
        if self.paint is not None:
            # an instance is painted as its object (and has its brim ears)
            it.paint = {k: (dict(v) if isinstance(v, dict) else list(v)) for k, v in self.paint.items()}
        it.layer_profile = list(self.layer_profile) if self.layer_profile else None
        it.layer_profile_sig = self.layer_profile_sig
        it.parts = [dict(p) for p in self.parts] if self.parts else None
        return it

    def linear(self):
        """Rotation and scale (no move) as a matrix."""
        sc = App.Matrix()
        sc.scale(self.scale)
        return App.Placement(App.Vector(), self.rotation).toMatrix().multiply(sc)

    def box(self):
        m = self.mesh.copy()
        m.transform(self.linear())
        return m.BoundBox


def mesh_of(shape, linear=0.05, angular=0.5):
    import MeshPart
    return MeshPart.meshFromShape(Shape=shape, LinearDeflection=linear, AngularDeflection=angular, Relative=False)


def alive_object(obj):
    """False for an object whose document was closed (or that was deleted)."""
    try:
        return obj.Document is not None and bool(obj.Name)
    except Exception:
        return False


def item_of(obj, linear=0.05, angular=0.5):
    """A FreeCAD object as a plate object: a body or solid by its shape; a mesh object (an imported STL, OBJ or
    3MF) by its triangles, sliced as they are."""
    from . import slicer as backend
    key = (obj.Document.Name, obj.Name)
    if backend.is_mesh(obj):
        return Item(obj.Label, None, backend.mesh_object(obj), key)
    shape = obj.Shape.copy()
    return Item(obj.Label, shape, mesh_of(shape, linear, angular), key)


def shape_of_file(path):
    """A file added to the plate: STEP/IGES as solids, meshes (STL/OBJ/3MF/PLY) as a solid of facets."""
    import Mesh
    import Part
    low = str(path).lower()
    if low.endswith((".step", ".stp", ".iges", ".igs", ".brep")):
        return Part.read(str(path))
    mesh = Mesh.Mesh(str(path))
    shell = Part.Shape()
    shell.makeShapeFromMesh(mesh.Topology, 0.05)
    try:
        solid = Part.makeSolid(shell)
        if solid.isValid():
            return solid
    except Exception as _fw_err:
        _fw_log("slicerplate.py:124", _fw_err)
    return shell


class Plate:
    """The objects on the printer's bed (the slicers' Prepare plate). Tools act on the selected
    objects, or on every object when none is selected."""

    SPACING = 6.0               # mm between objects when arranging (the slicers' default)

    GAP = 1.0 / 5.0             # between plates, a fifth of the plate (the slicers' LOGICAL_PART_PLATE_GAP)

    def __init__(self):
        self.items = []
        self.plates = [""]      # plate names ("" = unnamed), as the slicers' plate list
        self.current = 0        # the plate new objects go on and Slice/Arrange plate act on
        self.selected = set()   # indices into items
        self.bed = [(0, 0), (256, 0), (256, 256), (0, 256)]
        self.height = 250.0
        self.printer_name = ""
        self.plate_type = "Textured PEI Plate"
        self.root = None
        self.view = None
        self.part_switch = None
        self.hidden = []
        self.objects = []
        self._objects_initialized = False
        self._deleted_sources = set()  # sources removed from the plate, suppressed until deselected
        self.picking = None         # event callback while "lay on face" waits for a click
        self.clicking = None        # event callback: click to select, drag to move
        self.drag = None
        self.on_change = None
        self.on_select = None
        from .slicergizmo import Gizmo
        self.gizmo = Gizmo(self)    # arrows / rings / handles while Move, Rotate or Scale is on
        self.tower = None           # the prime tower shown on the plates (slicertower), dragged as the objects are
        self.nav = None             # the slicers' mouse (turn about the plate) while the plate shows
        self.section = None         # painting's Section view: (normal, point) of the cut, picks skip what it cuts
        self.locked = set()         # locked plates (the slicers' plate lock): arrange and orient leave them alone
        self.on_plate_icon = None   # the panel's handler of the icons beside each plate (slicerplatebar)

    # ------------------------------------------------------------------ compatibility: one part
    def _first(self):
        targets = self.targets()
        return targets[0] if targets else None

    @property
    def mesh(self):
        it = self._first()
        return it.mesh if it is not None else None

    @property
    def rotation(self):
        it = self._first()
        return it.rotation if it is not None else App.Rotation()

    @rotation.setter
    def rotation(self, rot):
        for it in self.targets():
            it.rotation = rot

    @property
    def xy(self):
        it = self._first()
        return it.xy if it is not None else None

    # ------------------------------------------------------------------ data
    def set_plate_type(self, plate_type):
        """Smooth or textured finish and its colour, as the slicers' plate types."""
        if plate_type and plate_type != self.plate_type:
            self.plate_type = plate_type
            self._redraw()

    def set_printer(self, data):
        self.printer_name = str(data.get("name") or data.get("printer_model") or "")
        pts = parse_points(data.get("printable_area"))
        if len(pts) >= 3:
            self.bed = pts
        try:
            self.height = float(data.get("printable_height") or 250.0)
        except (TypeError, ValueError):
            self.height = 250.0
        self._redraw()

    def set_objects(self, objects, linear=0.05, angular=0.5):
        """The FreeCAD objects to print. Objects already on the plate keep their placement; files
        added to the plate stay."""
        objects = [o for o in objects if alive_object(o)]          # a closed document's objects are gone
        self.objects = [o for o in self.objects if alive_object(o)]
        deleted = getattr(self, "_deleted_sources", set())
        if deleted:
            selected = {(o.Document.Name, o.Name) for o in objects}
            if selected & deleted:
                objects = [o for o in objects if (o.Document.Name, o.Name) not in deleted]
            else:
                self._deleted_sources.clear()  # the old selection is gone; later picks may be added again
        names = [(o.Document.Name, o.Name) for o in objects]
        if self._objects_initialized and names == [(o.Document.Name, o.Name) for o in self.objects]:
            return False
        self._objects_initialized = True
        self.objects = list(objects)
        keep = [it for it in self.items if it.pinned or not isinstance(it.source, tuple) or it.source in names]
        have = {it.source for it in keep}
        for obj in objects:
            key = (obj.Document.Name, obj.Name)
            if key in have:
                continue
            it = item_of(obj, linear, angular)
            it.plate = self.current
            keep.append(it)
        self.items = keep
        self.selected = set()
        if len(self.items) > 1 and any(it.xy is None for it in self.items):
            self._pack()
        self._redraw()
        return True

    def add_file(self, path):
        import os
        shape = shape_of_file(path)
        it = Item(os.path.splitext(os.path.basename(str(path)))[0], shape, mesh_of(shape), str(path))
        it.plate = self.current
        it.pinned = True
        self.items.append(it)
        self.selected = {len(self.items) - 1}
        self._pack()
        self._redraw()
        self._changed()
        return it

    def add_part(self, obj, linear=0.05, angular=0.5):
        """A FreeCAD object (any open document) onto the current plate."""
        it = item_of(obj, linear, angular)
        it.plate = self.current
        it.pinned = True
        self.items.append(it)
        self.selected = {len(self.items) - 1}
        self._pack()
        self._redraw()
        self._changed()
        return it

    # ------------------------------------------------------------------ plates
    def plate_origin(self, i):
        """Where plate i sits (the slicers' layout: a square-ish grid, rows going -Y)."""
        import math as _m
        cols = max(1, int(_m.ceil(_m.sqrt(len(self.plates)))))
        x0, y0, x1, y1 = self.bed_box()
        w, d = x1 - x0, y1 - y0
        return App.Vector((i % cols) * w * (1 + self.GAP), -(i // cols) * d * (1 + self.GAP), 0)

    def plate_at(self, point):
        """The plate a world point lies on, or None."""
        x0, y0, x1, y1 = self.bed_box()
        for i in range(len(self.plates)):
            o = self.plate_origin(i)
            if x0 + o.x <= point.x <= x1 + o.x and y0 + o.y <= point.y <= y1 + o.y:
                return i
        return None

    def add_plate(self, name=""):
        self.plates.append(name)
        self.current = len(self.plates) - 1
        self._redraw()
        self._changed()
        return self.current

    def delete_plate(self, i=None):
        """Delete a plate and the objects on it (never the last plate)."""
        i = self.current if i is None else i
        if len(self.plates) <= 1 or not 0 <= i < len(self.plates):
            return False
        self.items = [it for it in self.items if it.plate != i]
        for it in self.items:
            if it.plate > i:
                it.plate -= 1
        del self.plates[i]
        self.locked = {k - 1 if k > i else k for k in self.locked if k != i}
        self.current = min(self.current, len(self.plates) - 1)
        self.selected = set()
        self._redraw()
        self._changed()
        return True

    def set_current(self, i):
        if 0 <= i < len(self.plates) and i != self.current:
            self.current = i
            self._redraw()
            if self.on_select:
                self.on_select()

    def plate_items(self, i=None):
        i = self.current if i is None else i
        return [it for it in self.items if it.plate == i]

    def targets(self):
        """The objects the tools act on: the selected ones, else all."""
        picked = [self.items[i] for i in sorted(self.selected) if i < len(self.items)]
        return picked or list(self.items)

    def select(self, index, add=False):
        if index is None:
            self.selected = set()
        elif add:
            self.selected ^= {index}
        else:
            self.selected = {index}
        self._colour()
        if self.on_select:
            self.on_select()

    def bed_box(self):
        xs = [p[0] for p in self.bed]
        ys = [p[1] for p in self.bed]
        return min(xs), min(ys), max(xs), max(ys)

    def bed_centre(self):
        x0, y0, x1, y1 = self.bed_box()
        return (x0 + x1) / 2.0, (y0 + y1) / 2.0

    def item_matrix(self, it):
        """Model coordinates -> bed coordinates: scale, rotate, stand on the bed, move to xy."""
        box = it.box()
        cx, cy = it.xy if it.xy is not None else self.bed_centre()
        move = App.Matrix()
        move.move(App.Vector(cx - (box.XMin + box.XMax) / 2.0, cy - (box.YMin + box.YMax) / 2.0, -box.ZMin))
        return move.multiply(it.linear())

    def world_matrix(self, it):
        """item_matrix moved to the item's plate (how it shows in the 3D view)."""
        o = self.plate_origin(it.plate)
        move = App.Matrix()
        move.move(o)
        return move.multiply(self.item_matrix(it))

    def matrix(self):
        it = self._first()
        return self.item_matrix(it) if it is not None else App.Matrix()

    def placed_mesh(self, mesh=None, items=None):
        """The objects (default: the ones the tools act on) as they stand on the bed, one mesh."""
        import Mesh
        out = Mesh.Mesh()
        for it in (items if items is not None else self.targets()):
            m = it.mesh.copy()
            m.transform(self.item_matrix(it))
            out.addMesh(m)
        return out

    def slice_items(self, plate=None):
        """[(name, shape in model coordinates, matrix as 16 numbers, plate)] for every object
        (plate given: on that plate only), in plate coordinates."""
        return [(it.name, it._shape if it._shape is not None else it.mesh, list(self.item_matrix(it).A), it.plate)
                for it in self.items
                if plate is None or it.plate == plate]

    def fits(self):
        """(fits the bed, fits the height), all objects"""
        items = self.plate_items() or self.items
        if not items:
            return True, True
        box = self.placed_mesh(items=items).BoundBox
        x0, y0, x1, y1 = self.bed_box()
        return (box.XMin >= x0 - 1e-6 and box.XMax <= x1 + 1e-6 and box.YMin >= y0 - 1e-6
                and box.YMax <= y1 + 1e-6), box.ZMax <= self.height + 1e-6

    # ------------------------------------------------------------------ tools
    def rotate(self, axis, degrees):
        axes = {"x": App.Vector(1, 0, 0), "y": App.Vector(0, 1, 0), "z": App.Vector(0, 0, 1)}
        for it in self.targets():
            it.rotation = App.Rotation(axes[axis], degrees).multiply(it.rotation)
        self._changed()

    def set_rotation(self, rot):
        for it in self.targets():
            it.rotation = rot
        self._changed()

    def set_scale(self, factors):
        for it in self.targets():
            it.scale = App.Vector(*factors)
        self._changed()

    def lay_on(self, normal, item=None):
        """Turn an object so a face with this normal (bed coordinates) lies on the bed."""
        n = App.Vector(normal)
        if n.Length < 1e-9:
            return
        n.normalize()
        for it in ([item] if item is not None else self.targets()):
            it.rotation = App.Rotation(n, App.Vector(0, 0, -1)).multiply(it.rotation)
        self._changed()

    def auto_orient(self):
        """The slicers' idea: of the orientations that put a large flat area on the bed, take the one
        with the least overhang needing support, then the lowest."""
        picked = [self.items[i] for i in sorted(self.selected) if i < len(self.items)]
        for it in picked or [it for it in self.items if it.plate not in self.locked]:
            best = self._orient(it)
            if best is not None:
                it.rotation = best
        self._changed()

    def orient_plate(self, i):
        """The plate icon's Auto orient: the objects on plate i."""
        for it in self.plate_items(i):
            best = self._orient(it)
            if best is not None:
                it.rotation = best
        self._changed()

    def arrange_plate(self, i):
        """The plate icon's Arrange: the objects on plate i only."""
        self._pack_plate(self.plate_items(i))
        self._changed()

    @staticmethod
    def _orient(it):
        sc = App.Matrix()
        sc.scale(it.scale)
        base = it.mesh.copy()
        base.transform(sc)
        groups = {}
        for f in base.Facets:
            n = f.Normal
            if n.Length < 1e-9:
                continue
            key = (round(n.x, 2), round(n.y, 2), round(n.z, 2))
            groups[key] = groups.get(key, 0.0) + f.Area
        candidates = sorted(groups.items(), key=lambda kv: -kv[1])[:24]
        best, best_score = None, None
        for (nx, ny, nz), area in candidates:
            rot = App.Rotation(App.Vector(nx, ny, nz), App.Vector(0, 0, -1))
            m = base.copy()
            m.transform(App.Placement(App.Vector(), rot).toMatrix())
            zmin = m.BoundBox.ZMin
            overhang = 0.0
            for f in m.Facets:
                if f.Normal.z < -OVERHANG and min(p[2] for p in f.Points) > zmin + 0.2:
                    overhang += f.Area * -f.Normal.z
            score = (round(overhang, 1), -round(area, 1), round(m.BoundBox.ZLength, 2))
            if best_score is None or score < best_score:
                best, best_score = rot, score
        return best

    def arrange(self):
        """One object: centred. Several: packed in rows from the bed's front-left corner, centred."""
        self._pack()
        self._changed()

    def _pack(self):
        for i in range(len(self.plates)):
            if i not in self.locked:
                self._pack_plate([it for it in self.items if it.plate == i])

    def _pack_plate(self, items):
        if len(items) <= 1:
            for it in items:
                it.xy = None
            return
        x0, y0, x1, y1 = self.bed_box()
        width = x1 - x0
        boxes = sorted(((it, it.box()) for it in items), key=lambda p: -p[1].YLength)
        rows, row, x, depth = [], [], 0.0, 0.0
        for it, b in boxes:
            if row and x + b.XLength > width:
                rows.append((row, depth))
                row, x, depth = [], 0.0, 0.0
            row.append((it, x, b))
            x += b.XLength + self.SPACING
            depth = max(depth, b.YLength)
        if row:
            rows.append((row, depth))
        total_y = sum(d for _, d in rows) + self.SPACING * (len(rows) - 1)
        y = (y0 + y1) / 2.0 - total_y / 2.0
        for row, depth in rows:
            row_w = row[-1][1] + row[-1][2].XLength
            off = (x0 + x1) / 2.0 - row_w / 2.0
            for it, x, b in row:
                it.xy = (off + x + b.XLength / 2.0, y + depth / 2.0)
            y += depth + self.SPACING

    def move_to(self, x, y):
        for it in self.targets()[:1]:
            it.xy = (x, y)
        self._changed()

    def move_by(self, dx, dy, items=None):
        for it in (items if items is not None else self.targets()):
            cx, cy = it.xy if it.xy is not None else self.bed_centre()
            it.xy = (cx + dx, cy + dy)
        self._changed()

    def reset(self):
        for it in self.targets():
            it.rotation = App.Rotation()
            it.scale = App.Vector(1, 1, 1)
        self._pack()
        self._changed()

    # ------------------------------------------------------------------ object tools
    def add_instance(self):
        for it in self.targets():
            self.items.append(it.copy())
        self._pack()
        self._redraw()
        self._changed()

    def remove_instance(self):
        """Take away the last copy of each selected object (never its last one)."""
        for it in self.targets():
            same = [x for x in self.items if x.mesh is it.mesh]
            if len(same) > 1:
                self.items.remove(same[-1])
        self.selected = set()
        self._pack()
        self._redraw()
        self._changed()

    def delete(self):
        if not self.selected:
            return
        deleted = {it.source for i, it in enumerate(self.items)
                   if i in self.selected and isinstance(it.source, tuple)}
        self._deleted_sources = getattr(self, "_deleted_sources", set()) | deleted
        self.items = [it for i, it in enumerate(self.items) if i not in self.selected]
        sources = {it.source for it in self.items if isinstance(it.source, tuple)}
        self.objects = [o for o in self.objects if alive_object(o) and (o.Document.Name, o.Name) in sources]
        self.selected = set()
        self._redraw()
        self._changed()

    def split(self):
        """Split each selected object into its separate solids (the slicers' Split to objects)."""
        out, changed = [], False
        for i, it in enumerate(self.items):
            solids = it.shape.Solids if (not self.selected or i in self.selected) else []
            if len(solids) > 1:
                changed = True
                for k, solid in enumerate(solids):
                    had = it.parts[k] if it.parts and k < len(it.parts) else None
                    part = Item(had["name"] if had else "%s %d" % (it.name, k + 1), solid, mesh_of(solid), it.source)
                    part.rotation, part.scale = App.Rotation(it.rotation), App.Vector(it.scale)
                    part.plate, part.pinned = it.plate, it.pinned
                    part.slot = (had or {}).get("slot") or it.slot      # a part's filament stays with it
                    out.append(part)
            else:
                out.append(it)
        if changed:
            self.items = out
            self.selected = set()
            self._pack()
            self._redraw()
            self._changed()
        return changed

    def split_parts(self):
        """Split each selected object into parts, one per solid (the slicers' Split to parts): it stays one object
        that moves as one, and each part can print with a filament of its own."""
        changed = False
        for i, it in enumerate(self.items):
            if self.selected and i not in self.selected:
                continue
            n = len(it.shape.Solids)
            if n > 1 and not it.parts:
                it.parts = [{"name": "%s part %d" % (it.name, k + 1), "slot": 0} for k in range(n)]
                changed = True
        if changed:
            self._redraw()
            self._changed()
        return changed

    def merge_parts(self, it):
        """Back to one part (the object's filament for all of it)."""
        if not it.parts:
            return False
        it.parts = None
        self._redraw()
        self._changed()
        return True

    def cut(self, height, keep="both", flip_upper=True):
        """Cut the selected object (or the only one) level with the bed at this height above it:
        two objects, the cut faces closed. flip_upper turns the top part over onto its cut face."""
        import Part
        targets = self.targets()
        if len(targets) != 1:
            return False
        it = targets[0]
        # bake rotation and scale into the shape, so the cut is level in bed coordinates
        if all(abs(v - 1.0) < 1e-9 for v in it.scale):
            shape = it.shape.copy()
            shape.transformShape(it.linear())          # exact: a rotation keeps the geometry
        else:
            shape = it.shape.copy().transformGeometry(it.linear())
        box = shape.BoundBox
        z = box.ZMin + height
        if not box.ZMin < z < box.ZMax:
            return False
        big = max(box.XLength, box.YLength, box.ZLength) * 4 + 10
        lower_box = Part.makeBox(big, big, z - box.ZMin + 1, App.Vector(box.Center.x - big / 2, box.Center.y - big / 2, box.ZMin - 1))
        upper_box = Part.makeBox(big, big, box.ZMax - z + 1, App.Vector(box.Center.x - big / 2, box.Center.y - big / 2, z))
        parts = []
        if keep in ("both", "lower"):
            parts.append(("lower", shape.common(lower_box)))
        if keep in ("both", "upper"):
            parts.append(("upper", shape.common(upper_box)))
        index = self.items.index(it)
        new = []
        for label, part in parts:
            if part.isNull() or part.Volume < 1e-6:
                continue
            p = Item("%s (%s)" % (it.name, label), part, mesh_of(part), it.source)
            if label == "upper" and flip_upper:
                p.rotation = App.Rotation(App.Vector(1, 0, 0), 180)
            p.xy = it.xy
            p.plate, p.pinned = it.plate, it.pinned
            new.append(p)
        if not new:
            return False
        self.items[index:index + 1] = new
        self.selected = set()
        self._pack()
        self._redraw()
        self._changed()
        return True

    def _changed(self):
        self._update_transform()
        if self.on_change:
            self.on_change()

    # ------------------------------------------------------------------ 3D view
    def show(self, view=None):
        from pivy import coin
        view = view or (Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None)
        if view is None:
            return False
        self.hide()
        self.view = view
        self.root = coin.SoSeparator()
        self.root.setName("SWStyle_SlicerPlate")
        self.bed_sep = coin.SoSeparator()
        self.root.addChild(self.bed_sep)
        self.part_switch = coin.SoSwitch()
        self.part_switch.whichChild = coin.SO_SWITCH_ALL
        self.root.addChild(self.part_switch)
        view.getSceneGraph().addChild(self.root)
        for obj in self.objects:
            vobj = getattr(obj, "ViewObject", None)
            if vobj is not None and vobj.Visibility:
                vobj.Visibility = False
                self.hidden.append((obj.Document.Name, obj.Name))
        self._redraw()
        self.start_select()
        from . import slicernav
        self.nav = slicernav.SlicerNavigation(self)
        self.nav.start()
        return True

    def shown(self):
        return self.root is not None

    def hide(self):
        if self.nav is not None:
            self.nav.stop()
            self.nav = None
        self.stop_pick()
        self.stop_select()
        self.gizmo.clear()
        if self.root is not None and self.view is not None:
            try:
                self.view.getSceneGraph().removeChild(self.root)
            except Exception as _fw_err:
                _fw_log("slicerplate.py:651", _fw_err)
        self.root = None
        self.view = None
        self.cut_sep = None
        for docname, name in self.hidden:
            try:
                obj = App.getDocument(docname).getObject(name)
                if obj is not None and obj.ViewObject is not None:
                    obj.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("slicerplate.py:661", _fw_err)
        self.hidden = []

    def show_part(self, on):
        from pivy import coin
        if self.part_switch is not None:
            self.part_switch.whichChild = coin.SO_SWITCH_ALL if on else coin.SO_SWITCH_NONE

    def _redraw(self):
        from pivy import coin
        if self.root is None:
            return
        self.bed_sep.removeAllChildren()
        for i in range(len(self.plates)):
            self.bed_sep.addChild(self._bed_node(self.plate_origin(i), i == self.current and len(self.plates) > 1, i))
        # the objects
        self.part_switch.removeAllChildren()
        for it in self.items:
            it.switch = coin.SoSeparator()
            it.transform = coin.SoMatrixTransform()
            it.switch.addChild(it.transform)
            it.material = coin.SoMaterial()
            it.switch.addChild(it.material)
            hints = coin.SoShapeHints()
            hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
            hints.creaseAngle = 0.5
            it.switch.addChild(hints)
            points, faces = it.mesh.Topology
            mc = coin.SoCoordinate3()
            mc.point.setValues(0, len(points), [(p.x, p.y, p.z) for p in points])
            it.switch.addChild(mc)
            fs = coin.SoIndexedFaceSet()
            idx = []
            for f in faces:
                idx += [f[0], f[1], f[2], -1]
            fs.coordIndex.setValues(0, len(idx), idx)
            it.switch.addChild(fs)
            if it.paint or it.parts or _highlighting():
                try:
                    from . import slicerpaint
                    it._up = slicerpaint.model_up(it, self)
                    slicerpaint.decorate(it, self.paint_colours() if hasattr(self, "paint_colours") else None)
                except Exception as error:
                    App.Console.PrintLog("slicer plate: paint not shown (%s)\n" % error)
            self.part_switch.addChild(it.switch)
        self.part_transform = self.items[0].transform if self.items else None
        self._colour()
        self._update_transform()

    def _bed_node(self, origin, current, index):
        """One plate: a flat face a hair under z=0, the grid every 10 mm, the outline (heavier and
        orange on the current plate when there are several), its number at the front right."""
        from pivy import coin
        sep = coin.SoSeparator()
        move = coin.SoTranslation()
        move.translation = (origin.x, origin.y, origin.z)
        sep.addChild(move)
        x0, y0, x1, y1 = self.bed_box()
        from . import slicerbed
        colour, kind = slicerbed.finish(self.plate_type)
        sep.addChild(slicerbed.art_node(self.bed, self.height, self.printer_name))      # the rim, under the face
        mat = coin.SoMaterial()
        mat.diffuseColor = colour
        mat.transparency = 0.0
        sep.addChild(mat)
        # the plate's finish (our own patterns, repeat every 6 mm): diamond grain for textured PEI, dots for
        # the supertack plate, smooth for the others
        grain = slicerbed.grain_image(kind)
        if grain is not None:
            tex = coin.SoTexture2()
            tex.image.setValue(coin.SbVec2s(grain[0], grain[0]), 1, grain[1])
            tex.setName("SWStyle_BedGrain")
            sep.addChild(tex)
        else:
            sep.addChild(coin.SoTexture2())
        coords = coin.SoCoordinate3()
        pts = [(x, y, -0.05) for x, y in self.bed]
        coords.point.setValues(0, len(pts), pts)
        tcoords = coin.SoTextureCoordinate2()
        tcoords.point.setValues(0, len(pts), [(x / 6.0, y / 6.0) for x, y in self.bed])
        sep.addChild(tcoords)
        sep.addChild(coords)
        face = coin.SoFaceSet()
        face.numVertices.setValue(len(pts))
        sep.addChild(face)
        grid = coin.SoSeparator()
        grid.addChild(coin.SoTexture2())             # no texture on the lines and text
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        grid.addChild(light)
        gm = coin.SoMaterial()
        gm.diffuseColor = GRID_COLOUR
        grid.addChild(gm)
        grid.addChild(slicerbed.art_node(self.bed, self.height, self.printer_name, over=True))
        lines = []
        step = 10.0
        x = math.ceil(x0 / step) * step
        while x <= x1 + 1e-6:
            lines += [(x, y0, 0.0), (x, y1, 0.0)]
            x += step
        y = math.ceil(y0 / step) * step
        while y <= y1 + 1e-6:
            lines += [(x0, y, 0.0), (x1, y, 0.0)]
            y += step
        gc = coin.SoCoordinate3()
        gc.point.setValues(0, len(lines), lines)
        grid.addChild(gc)
        ls = coin.SoLineSet()
        ls.numVertices.setValues(0, len(lines) // 2, [2] * (len(lines) // 2))
        grid.addChild(ls)
        om = coin.SoMaterial()
        om.diffuseColor = SELECTED_COLOUR if current else GRID_COLOUR
        grid.addChild(om)
        outline = coin.SoCoordinate3()
        out = [(x, y, 0.01) for x, y in self.bed] + [(self.bed[0][0], self.bed[0][1], 0.01)]
        outline.point.setValues(0, len(out), out)
        style = coin.SoDrawStyle()
        style.lineWidth = 3.0 if current else 2.0
        grid.addChild(style)
        grid.addChild(outline)
        ol = coin.SoLineSet()
        ol.numVertices.setValue(len(out))
        grid.addChild(ol)
        if len(self.plates) > 1:
            tsep = coin.SoSeparator()
            tm = coin.SoTranslation()
            tm.translation = (x1 + 4, y0, 0.0)
            tsep.addChild(tm)
            tc = coin.SoMaterial()
            tc.diffuseColor = SELECTED_COLOUR
            tsep.addChild(tc)
            font = coin.SoFont()
            font.size = 16
            tsep.addChild(font)
            text = coin.SoText2()
            name = self.plates[index]
            text.string = "%02d%s" % (index + 1, ("  " + name) if name else "")
            tsep.addChild(text)
            grid.addChild(tsep)
        try:
            from . import slicerplatebar
            grid.addChild(slicerplatebar.node(self, index))
        except Exception as error:
            App.Console.PrintLog("slicer plate: plate icons not shown (%s)\n" % error)
        sep.addChild(grid)
        return sep

    def show_cut(self, height, box=None):
        """The cut plane at this height above the plate (None: away)."""
        from pivy import coin
        if self.root is None:
            return
        if getattr(self, "cut_sep", None) is not None:
            self.root.removeChild(self.cut_sep)
            self.cut_sep = None
        if height is None or box is None:
            return
        self.cut_sep = coin.SoSeparator()
        mat = coin.SoMaterial()
        mat.diffuseColor = (0.93, 0.33, 0.20)
        mat.transparency = 0.55
        self.cut_sep.addChild(mat)
        hints = coin.SoShapeHints()
        hints.shapeType = coin.SoShapeHints.UNKNOWN_SHAPE_TYPE
        self.cut_sep.addChild(hints)
        m = max(box.XLength, box.YLength) * 0.25 + 5
        z = box.ZMin + height
        pts = [(box.XMin - m, box.YMin - m, z), (box.XMax + m, box.YMin - m, z),
               (box.XMax + m, box.YMax + m, z), (box.XMin - m, box.YMax + m, z)]
        c = coin.SoCoordinate3()
        c.point.setValues(0, 4, pts)
        self.cut_sep.addChild(c)
        f = coin.SoFaceSet()
        f.numVertices.setValue(4)
        self.cut_sep.addChild(f)
        self.root.addChild(self.cut_sep)

    def _colour(self):
        for i, it in enumerate(self.items):
            if it.material is not None:
                it.material.diffuseColor = SELECTED_COLOUR if i in self.selected else PART_COLOUR
        self.gizmo.update()

    def _update_transform(self):
        from pivy import coin
        for it in self.items:
            if it.transform is None:
                continue
            m = self.world_matrix(it)
            # Coin matrices are row-major with the translation in the last row
            it.transform.matrix.setValue(coin.SbMatrix(
                m.A11, m.A21, m.A31, m.A41,
                m.A12, m.A22, m.A32, m.A42,
                m.A13, m.A23, m.A33, m.A43,
                m.A14, m.A24, m.A34, m.A44))
        self.gizmo.update()

    def _changed_quiet(self):
        """While a gizmo drags: the objects and the gizmo follow; the panel hears at the end."""
        self._update_transform()

    def fit(self):
        if self.view is None:
            return
        try:
            self.view.viewIsometric()
            self.view.fitAll()
        except Exception as _fw_err:
            _fw_log("slicerplate.py:857", _fw_err)
        if self.nav is not None:
            self.nav.aim()          # turn about the plate's middle, as the slicers do

    # ------------------------------------------------------------------ lay on face: pick
    def start_pick(self, done=None):
        """Next click on the part: that face goes down onto the bed."""
        from pivy import coin
        if self.view is None or self.picking is not None:
            return
        self._pick_done = done

        def clicked(cb):
            ev = cb.getEvent()
            if ev.getButton() != coin.SoMouseButtonEvent.BUTTON1 or ev.getState() != coin.SoButtonEvent.DOWN:
                return
            hit = self._pick(ev.getPosition())
            if hit is None:
                return
            cb.setHandled()
            self.stop_pick()
            self.lay_on(hit[1], self.items[hit[0]])
            if self._pick_done:
                self._pick_done(True)

        self.picking = self.view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), clicked)

    def stop_pick(self):
        from pivy import coin
        if self.picking is not None and self.view is not None:
            try:
                self.view.removeEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self.picking)
            except Exception as _fw_err:
                _fw_log("slicerplate.py:890", _fw_err)
        self.picking = None

    def _pick(self, pos):
        """(item index, normal in bed coordinates, point) of the object under a screen position."""
        from pivy import coin
        if self.root is None or self.view is None:
            return None
        viewer = self.view.getViewer()
        manager = viewer.getSoRenderManager()
        region = manager.getViewportRegion()
        pick = coin.SoRayPickAction(region)
        if not isinstance(pos, coin.SbVec2s):
            pos = coin.SbVec2s(int(pos[0]), int(pos[1]))
        pick.setPoint(pos)
        pick.setRadius(2)
        pick.setPickAll(True)
        pick.apply(manager.getSceneGraph())
        cut = getattr(self, "section", None)          # painting's Section view: (normal, point) of the cut
        for hit in pick.getPickedPointList():
            path = hit.getPath()
            if cut is not None:
                q = hit.getPoint()
                if (App.Vector(q[0], q[1], q[2]) - cut[1]).dot(cut[0]) < 0:
                    continue                  # cut away: not there
            if path.containsNode(self.part_switch):
                for i, it in enumerate(self.items):
                    if it.switch is not None and path.containsNode(it.switch):
                        n = hit.getNormal()       # world (bed) coordinates
                        p = hit.getPoint()
                        return i, App.Vector(n[0], n[1], n[2]), App.Vector(p[0], p[1], p[2])
            if not path.containsNode(self.root):
                return None               # something of the model's in front
        return None

    def pick_normal(self, pos):
        """The normal (bed coordinates) of the object's face under a screen position."""
        hit = self._pick(pos)
        return hit[1] if hit else None

    # ------------------------------------------------------------------ click to select, drag to move
    def start_select(self):
        """Clicks on the plate select objects (Ctrl adds); dragging an object moves it on the bed."""
        from pivy import coin
        if self.view is None or self.clicking is not None:
            return

        def button(cb):
            if self.picking is not None:
                return
            ev = cb.getEvent()
            if ev.getButton() != coin.SoMouseButtonEvent.BUTTON1:
                return
            if ev.getState() == coin.SoButtonEvent.DOWN:
                if self.gizmo.press(ev.getPosition()):
                    cb.setHandled()
                    return
                if self.tower is not None and self.tower.press(ev.getPosition()):
                    cb.setHandled()
                    return
                if self.plate_icon(ev.getPosition(), run=True):
                    cb.setHandled()
                    return
                hit = self._pick(ev.getPosition())
                if hit is None:
                    if not ev.wasCtrlDown():
                        self.select(None)
                    if len(self.plates) > 1:
                        p = self.bed_point(ev.getPosition(), 0.0)
                        i = self.plate_at(p) if p is not None else None
                        if i is not None:
                            self.set_current(i)
                    return
                i, _, point = hit
                if ev.wasCtrlDown():
                    self.select(i, add=True)
                    return
                if i not in self.selected:
                    self.select(i)
                self.drag = App.Vector(point)
                cb.setHandled()
            elif self.gizmo.release():
                cb.setHandled()
            elif self.tower is not None and self.tower.release():
                cb.setHandled()
            elif self.drag is not None:
                self.drag = None
                self._replate()
                cb.setHandled()

        def motion(cb):
            if self.gizmo.motion(cb.getEvent().getPosition()):
                cb.setHandled()
                return
            if self.tower is not None and self.tower.motion(cb.getEvent().getPosition()):
                cb.setHandled()
                return
            if self.drag is None:
                self.plate_icon(cb.getEvent().getPosition(), run=False)
                return
            point = self.bed_point(cb.getEvent().getPosition(), self.drag.z)
            if point is None:
                return
            self.move_by(point.x - self.drag.x, point.y - self.drag.y)
            self.drag = App.Vector(point.x, point.y, self.drag.z)
            cb.setHandled()

        self.clicking = (self.view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), button),
                         self.view.addEventCallbackPivy(coin.SoLocation2Event.getClassTypeId(), motion))

    def plate_icon(self, pos, run=False):
        """The icon beside a plate under a screen position: run=True runs it (a click), else its tooltip shows (the
        pointer over it). True when there is one."""
        from . import slicerplatebar
        h = slicerplatebar.hit(self, self.bed_point(pos, 0.02))
        if run:
            return bool(h) and (slicerplatebar.run(self, *h) or True)
        try:
            from PySide import QtGui, QtWidgets
            tip = dict((k, t) for k, _ic, t in slicerplatebar.icons(self, h[0])).get(h[1]) if h else None
            if tip:
                QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), tip)
            elif getattr(self, "_icon_tip", None):
                QtWidgets.QToolTip.hideText()
            self._icon_tip = tip
        except Exception as error:
            App.Console.PrintLog("slicer plate: no icon tip (%s)\n" % error)
        return bool(h)

    def _replate(self):
        """An object dragged onto another plate belongs to that plate now (as in the slicers)."""
        moved = False
        for it in self.targets():
            m = it.mesh.copy()
            m.transform(self.world_matrix(it))
            c = m.BoundBox.Center
            i = self.plate_at(c)
            if i is not None and i != it.plate:
                o_old, o_new = self.plate_origin(it.plate), self.plate_origin(i)
                cx, cy = it.xy if it.xy is not None else self.bed_centre()
                it.xy = (cx + o_old.x - o_new.x, cy + o_old.y - o_new.y)
                it.plate = i
                self.current = i
                moved = True
        if moved:
            self._redraw()
            self._changed()

    def stop_select(self):
        from pivy import coin
        if self.clicking is not None and self.view is not None:
            try:
                self.view.removeEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self.clicking[0])
                self.view.removeEventCallbackPivy(coin.SoLocation2Event.getClassTypeId(), self.clicking[1])
            except Exception as _fw_err:
                _fw_log("slicerplate.py:1009", _fw_err)
        self.clicking = None
        self.drag = None

    def ray(self, pos):
        """(point, direction) of the ray through a screen position (Inventor pixels)."""
        try:
            view = self.view
            p = view.getPointOnFocalPlane(int(pos[0]), int(pos[1]))
            cam = view.getCameraNode()
            if cam.getTypeId().getName().getString() == "PerspectiveCamera":
                c = cam.position.getValue()
                d = p - App.Vector(c[0], c[1], c[2])
            else:
                d = App.Vector(view.getViewDirection())
            return App.Vector(p), d
        except Exception:
            return None

    def bed_point(self, pos, z=0.0):
        """Where the ray through a screen position (Inventor pixels, origin bottom left, as mouse
        events and getPointOnScreen give them) meets the plane at height z."""
        try:
            view = self.view
            x, y = int(pos[0]), int(pos[1])
            p = view.getPointOnFocalPlane(x, y)
            cam = view.getCameraNode()
            if cam.getTypeId().getName().getString() == "PerspectiveCamera":
                c = cam.position.getValue()
                d = p - App.Vector(c[0], c[1], c[2])
            else:
                d = App.Vector(view.getViewDirection())
            if abs(d.z) < 1e-9:
                return None
            t = (z - p.z) / d.z
            return App.Vector(p.x + t * d.x, p.y + t * d.y, z)
        except Exception as error:
            App.Console.PrintLog("slicer plate: no bed point (%s)\n" % error)
            return None
