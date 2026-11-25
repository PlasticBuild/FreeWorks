"""Assembly view: the slicers' Assembly View on the plate toolbar. A look at the objects on the plate and their parts
(Split to parts, Text) pulled apart by the Explosion ratio, and cut level by the Section view to see inside. It only
changes the view: the objects stay as they are, and closing the tool shows the plate again."""
import FreeCAD as App
from PySide import QtCore, QtWidgets

Qt = QtCore.Qt
PALETTE = ((0.95, 0.60, 0.20), (0.25, 0.55, 0.85), (0.40, 0.75, 0.40), (0.85, 0.35, 0.35), (0.65, 0.50, 0.85),
           (0.90, 0.80, 0.30))


def _hex(c):
    c = (c or "").lstrip("#")
    try:
        return tuple(int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return None


class AssemblyView:
    def __init__(self, toolbar):
        self.toolbar, self.bed, self.panel = toolbar, toolbar.bed, toolbar.panel
        self.ratio, self.section = 1.0, 1.0
        self.node = self.clip = None
        self.pieces = []                  # [(name, centre, translation node, colour)]
        self.centre = App.Vector()
        self.zmin = self.zmax = 0.0
        self.build()

    def items(self):
        return [it for it in self.bed.items if it.plate == self.bed.current]

    def build(self):
        """The plate's objects and their parts, as separate pieces (bed coordinates)."""
        from pivy import coin
        from . import slicerplate
        self.remove()
        root = self.bed.root
        if root is None:
            return
        colours = []
        try:
            colours = [_hex(c) for c in self.panel.slots.colours]
        except Exception:
            colours = []
        sep = coin.SoSeparator()
        sep.setName("SWStyle_SlicerAssemblyView")
        self.clip = coin.SoClipPlane()
        self.clip.on = False
        sep.addChild(self.clip)
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
        hints.creaseAngle = 0.5
        sep.addChild(hints)
        self.pieces = []
        boxes = []
        for it in self.items():
            m = self.bed.world_matrix(it)
            solids = it.shape.Solids if it.shape is not None else []
            parts = it.parts if it.parts and len(it.parts) == len(solids) else None
            pieces = [(p.get("name") or it.name, s, int(p.get("slot") or 0) or it.slot) for s, p in zip(solids, parts)] \
                if parts else [(it.name, None, it.slot)]
            for k, (name, solid, slot) in enumerate(pieces):
                mesh = slicerplate.mesh_of(solid) if solid is not None else it.mesh
                mesh = mesh.copy()
                mesh.transform(m)
                box = mesh.BoundBox
                boxes.append(box)
                piece = coin.SoSeparator()
                move = coin.SoTranslation()
                piece.addChild(move)
                mat = coin.SoMaterial()
                # in its filament's colour, as the slicers show it (another colour each when there are none)
                colour = colours[slot - 1] if 0 < slot <= len(colours) and colours[slot - 1] else None
                colour = colour or PALETTE[len(self.pieces) % len(PALETTE)]
                mat.diffuseColor.setValue(*colour)
                piece.addChild(mat)
                pts, tris = mesh.Topology
                coords = coin.SoCoordinate3()
                coords.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
                piece.addChild(coords)
                faces = coin.SoIndexedFaceSet()
                idx = []
                for a, b, c in tris:
                    idx += [a, b, c, -1]
                faces.coordIndex.setValues(0, len(idx), idx)
                piece.addChild(faces)
                sep.addChild(piece)
                self.pieces.append((name, box.Center, move, colour))
        if boxes:
            whole = App.BoundBox()
            for b in boxes:
                whole.add(b)
            self.centre = whole.Center
            self.zmin, self.zmax = whole.ZMin, whole.ZMax
        root.addChild(sep)
        self.node = sep
        self.bed.show_part(False)
        self.update()

    def update(self):
        """Moves the pieces apart by the explosion ratio and sets the section height."""
        from pivy import coin
        f = self.ratio - 1.0
        for _name, centre, move, _colour in self.pieces:
            # apart from the middle across the plate, up from the plate's level (nothing goes under the plate)
            move.translation.setValue((centre.x - self.centre.x) * f, (centre.y - self.centre.y) * f,
                                      (centre.z - self.zmin) * f)
        if self.clip is not None:
            top = self.zmin + self.section * (self.zmax - self.zmin) * self.ratio
            self.clip.on = self.section < 1.0
            # the plane looks down: what is above the section height is cut away
            self.clip.plane.setValue(coin.SbPlane(coin.SbVec3f(0, 0, -1), coin.SbVec3f(0, 0, top)))

    def set_ratio(self, v):
        self.ratio = max(1.0, float(v))
        self.update()

    def set_section(self, v):
        self.section = min(1.0, max(0.0, float(v)))
        self.update()

    def remove(self):
        root = self.bed.root
        if self.node is not None and root is not None:
            try:
                root.removeChild(self.node)
            except Exception:
                pass
        self.node = None

    def stop(self):
        self.remove()
        self.bed.show_part(True)


def panel(toolbar, ToolPanel):
    """The Assembly View tool panel."""
    view = toolbar.assembly
    p = ToolPanel("Assembly View", toolbar.parentWidget())
    p.setObjectName("SWSlicerToolPanel")

    def slider_row(label, name, lo, hi, value, decimals, step):
        s = QtWidgets.QSlider(Qt.Horizontal)
        s.setObjectName("SWStyle_SlicerAssembly_" + name)
        scale = 10 ** decimals
        s.setRange(int(lo * scale), int(hi * scale))
        s.setValue(int(round(value * scale)))
        box = QtWidgets.QDoubleSpinBox()
        box.setObjectName("SWStyle_SlicerAssemblyValue_" + name)
        box.setRange(lo, hi)
        box.setDecimals(decimals)
        box.setSingleStep(step)
        box.setValue(value)
        s.valueChanged.connect(lambda v: box.setValue(v / float(scale)))
        box.valueChanged.connect(lambda v: (s.blockSignals(True), s.setValue(int(round(v * scale))), s.blockSignals(False)))
        row = p.lay.rowCount()
        p.lay.addWidget(QtWidgets.QLabel(label), row, 0)
        p.lay.addWidget(s, row, 1, 1, 2)
        p.lay.addWidget(box, row, 3)
        return box

    p.ratio = slider_row("Explosion ratio", "ratio", 1.0, 3.0, view.ratio, 2, 0.05)
    p.section = slider_row("Section view", "section", 0.0, 1.0, view.section, 2, 0.05)
    p.ratio.valueChanged.connect(view.set_ratio)
    p.section.valueChanged.connect(view.set_section)
    p.info = QtWidgets.QLabel("")
    p.info.setObjectName("SWStyle_SlicerAssemblyInfo")
    p.info.setWordWrap(True)
    p.lay.addWidget(p.info, p.lay.rowCount(), 0, 1, 4)
    names = [n for n, _c, _m, _k in view.pieces]
    its = view.items()
    vol = sum((it.shape.Volume * abs(it.scale.x * it.scale.y * it.scale.z)) for it in its if it.shape is not None)
    p.info.setText("%d object%s, %d piece%s  ·  volume %.0f mm³" % (
        len(its), "" if len(its) == 1 else "s", len(names), "" if len(names) == 1 else "s", vol))
    return p
