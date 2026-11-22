"""Text: the slicers' Text (emboss) tool on the plate toolbar (T). Click a face of an object to put the text there
(the top of the selected object until then); the text lies on the face, reading along it. Part: raised text, added
to the object as a part of its own (so it can take another filament: right-click the object > Parts). Negative part:
the text engraved into the object. Modifier: the text as a modifier part, reaching the depth into the object, whose own
settings (right-click the object > Parts > the text > Settings...) apply where it is, as in the slicers. A preview shows
on the plate until Add text."""
import glob
import os

import FreeCAD as App
from PySide import QtWidgets

TYPES = (("part", "Part"), ("negative", "Negative part"), ("modifier", "Modifier"))
PREVIEW_COLOUR = (1.0, 0.55, 0.1)


def fonts():
    """{name: font file}: FreeCAD's own fonts, then the computer's TrueType fonts."""
    out = {}
    roots = [os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Resources", "fonts")]
    win = os.environ.get("WINDIR")
    if win:
        roots.append(os.path.join(win, "Fonts"))
    roots += ["/usr/share/fonts", os.path.expanduser("~/.fonts"), "/Library/Fonts", "/System/Library/Fonts"]
    for root in roots:
        for path in sorted(glob.glob(os.path.join(root, "**", "*.ttf"), recursive=True)
                           + glob.glob(os.path.join(root, "**", "*.TTF"), recursive=True))[:400]:
            name = os.path.splitext(os.path.basename(path))[0]
            out.setdefault(name, path)
    return out


def default_font(found):
    for name in ("arial", "Arial", "DejaVuSans", "LiberationSans-Regular", "osifont-lgpl3fe"):
        if name in found:
            return name
    return next(iter(found), None)


def text_solid(text, path, height, depth, angle=0.0):
    """The text as a solid in the XY plane, centred on the origin, z from 0 to depth (None when it has no outline)."""
    import Part
    if not text.strip() or not path:
        return None
    chars = Part.makeWireString(text, os.path.dirname(path) + os.sep, os.path.basename(path), float(height), 0)
    faces = []
    for wires in chars:
        if wires:
            try:
                faces.append(Part.makeFace(wires, "Part::FaceMakerBullseye"))
            except Exception:
                continue
    if not faces:
        return None
    solid = Part.makeCompound(faces).extrude(App.Vector(0, 0, float(depth)))
    b = solid.BoundBox
    solid.translate(App.Vector(-(b.XMin + b.XMax) / 2.0, -(b.YMin + b.YMax) / 2.0, 0))
    if angle:
        solid.rotate(App.Vector(0, 0, 0), App.Vector(0, 0, 1), float(angle))
    return solid


def frame(point, normal):
    """The placement of text lying on a face at point (normal out of the face): reading along the face, upright on a
    side face."""
    n = App.Vector(normal)
    n.normalize()
    up = App.Vector(0, 0, 1) if abs(n.z) < 0.9 else App.Vector(0, 1, 0)
    xa = up.cross(n)
    xa.normalize()
    ya = n.cross(xa)
    m = App.Matrix(xa.x, ya.x, n.x, point.x,
                   xa.y, ya.y, n.y, point.y,
                   xa.z, ya.z, n.z, point.z,
                   0, 0, 0, 1)
    return m


class TextTool:
    def __init__(self, toolbar):
        self.toolbar, self.bed, self.panel = toolbar, toolbar.bed, toolbar.panel
        self.fonts = fonts()
        self.font = default_font(self.fonts)
        self.text, self.height, self.depth, self.angle, self.kind = "Text", 10.0, 1.0, 0.0, "part"
        self.spot = None                 # (item, point, normal) in bed coordinates
        self.callback = None
        self.node = None
        self.default_spot()
        self.start()

    # -------------------------------------------------------------- where
    def default_spot(self):
        """The middle of the top of the selected object (or the only one)."""
        its = self.bed.targets()
        if not its:
            self.spot = None
            return
        it = its[0]
        b = self.bed.placed_mesh(items=[it]).BoundBox
        self.spot = (it, App.Vector((b.XMin + b.XMax) / 2.0, (b.YMin + b.YMax) / 2.0, b.ZMax), App.Vector(0, 0, 1))

    def start(self):
        from pivy import coin
        bed = self.bed
        if bed.view is None:
            return
        bed.stop_pick()
        bed.picking = self

        def button(cb):
            ev = cb.getEvent()
            if ev.getState() == coin.SoButtonEvent.DOWN and ev.getButton() == coin.SoMouseButtonEvent.BUTTON1:
                if self.click(ev.getPosition()):
                    cb.setHandled()
        self.callback = bed.view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), button)

    def stop(self):
        from pivy import coin
        if self.callback is not None and self.bed.view is not None:
            try:
                self.bed.view.removeEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self.callback)
            except Exception as error:
                App.Console.PrintLog("slicer text: %s\n" % error)
        self.callback = None
        if self.bed.picking is self:
            self.bed.picking = None
        self._remove_node()

    def right_click(self, pos):
        return False

    def click(self, pos):
        hit = self.bed._pick(pos)
        if hit is None:
            return False
        index, normal, point = hit
        it = self.bed.items[index]
        o = self.bed.plate_origin(it.plate)
        self.place(it, App.Vector(point.x - o.x, point.y - o.y, point.z), normal)
        return True

    def place(self, item, point, normal):
        """The text on an object's face at a point (bed coordinates)."""
        self.spot = (item, App.Vector(point), App.Vector(normal))
        self.show()

    # -------------------------------------------------------------- the text
    def solid(self):
        """The text in bed coordinates where it goes (None: nothing to add)."""
        if self.spot is None or not self.font:
            return None
        negative = self.kind in ("negative", "modifier")
        # engraved: from the depth below the face to a little above it; raised: from a little into the face
        local = text_solid(self.text, self.fonts.get(self.font), self.height,
                           self.depth + (0.1 if self.kind == "negative" else 0.05), self.angle)
        if local is None:
            return None
        # engraved and modifier: from the depth into the object to a hair above the face (a modifier acts inside it)
        local.translate(App.Vector(0, 0, -float(self.depth) if negative else -0.05))
        _it, point, normal = self.spot
        return local.transformGeometry(frame(point, normal))

    def apply(self):
        """Adds the text to the object. Returns the object, or a message saying why not."""
        import Part
        from . import slicerplate
        if self.spot is None:
            return "Select an object, or click a face of one."
        it = self.spot[0]
        if it not in self.bed.items:
            return "The object is no longer on the plate."
        world = self.solid()
        if world is None:
            return "Type some text first." if not self.text.strip() else "This font has no outline for the text."
        model = world.transformGeometry(self.bed.item_matrix(it).inverse())
        before = it.box()
        solids = list(it.shape.Solids) or [it.shape]
        if self.kind in ("part", "modifier"):
            if it.parts and len(it.parts) == len(solids):
                parts = [dict(p) for p in it.parts]
            else:
                parts = [{"name": it.name, "slot": 0}] if len(solids) == 1 else \
                    [{"name": "%s part %d" % (it.name, k + 1), "slot": 0} for k in range(len(solids))]
            text_solids = model.Solids or [model]
            extra = {"type": "modifier", "settings": {}} if self.kind == "modifier" else {}
            parts += [dict({"name": "Text: %s" % self.text, "slot": 0}, **extra) for _s in text_solids]
            shape = Part.makeCompound(solids + text_solids)
            it.parts = parts
        else:
            shape = it.shape.cut(model)
            if not shape.Solids or shape.Volume < 1e-6:
                return "The text would take the whole object away."
            if it.parts and len(shape.Solids) != len(it.parts):
                it.parts = None
            it.paint = None              # the faces changed
            if len(shape.Solids) == 1:
                shape = shape.Solids[0]
        it.shape = shape
        it.mesh = slicerplate.mesh_of(shape)
        it.layer_profile = None
        # the object stays where it was: the plate places it by its box, which the text may have grown
        after = it.box()
        cx, cy = it.xy if it.xy is not None else self.bed.bed_centre()
        it.xy = (cx + (after.XMin + after.XMax - before.XMin - before.XMax) / 2.0,
                 cy + (after.YMin + after.YMax - before.YMin - before.YMax) / 2.0)
        self._remove_node()
        self.bed._redraw()
        self.bed._changed()
        return it

    # -------------------------------------------------------------- preview
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
        from . import slicerplate
        self._remove_node()
        root = self.bed.root
        if root is None:
            return
        try:
            world = self.solid()
        except Exception:
            world = None
        if world is None:
            return
        o = self.bed.plate_origin(self.spot[0].plate)
        mesh = slicerplate.mesh_of(world, 0.05, 0.3)
        pts, tris = mesh.Topology
        sep = coin.SoSeparator()
        sep.setName("SWStyle_SlicerTextPreview")
        tr = coin.SoTranslation()
        tr.translation.setValue(o.x, o.y, o.z)
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(*PREVIEW_COLOUR)
        mat.transparency.setValue(0.2)
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
        faces = coin.SoIndexedFaceSet()
        idx = []
        for a, b, c in tris:
            idx += [a, b, c, -1]
        faces.coordIndex.setValues(0, len(idx), idx)
        for n in (tr, mat, coords, faces):
            sep.addChild(n)
        root.addChild(sep)
        self.node = sep


def panel(toolbar, ToolPanel):
    """The Text tool panel."""
    tool = toolbar.texter
    p = ToolPanel("Text", toolbar.parentWidget())
    p.setObjectName("SWSlicerToolPanel")
    hint = QtWidgets.QLabel("Click a face of an object to put the text there.")
    hint.setWordWrap(True)
    p.lay.addWidget(hint, p.lay.rowCount(), 0, 1, 4)
    p.kind = QtWidgets.QComboBox()
    p.kind.setObjectName("SWStyle_SlicerTextType")
    for key, label in TYPES:
        p.kind.addItem(label, key)
    p.kind.setToolTip("Part: raised text, a part of its own (it can take another filament). Negative part: engraved. "
                      "Modifier: the text changes the object's settings where it is (its Settings... under Parts).")
    p.row("Type", p.kind)
    p.text = QtWidgets.QLineEdit(tool.text)
    p.text.setObjectName("SWStyle_SlicerTextText")
    p.row("Text", p.text)
    p.font = QtWidgets.QComboBox()
    p.font.setObjectName("SWStyle_SlicerTextFont")
    for name in sorted(tool.fonts, key=str.lower):
        p.font.addItem(name)
    if tool.font:
        p.font.setCurrentText(tool.font)
    p.row("Font", p.font)
    spins = {}
    for key, label, value, lo, hi, suffix in (("height", "Height", tool.height, 1.0, 200.0, " mm"),
                                               ("depth", "Depth", tool.depth, 0.1, 50.0, " mm"),
                                               ("angle", "Rotation", tool.angle, -360.0, 360.0, " °")):
        s = QtWidgets.QDoubleSpinBox()
        s.setObjectName("SWStyle_SlicerText_" + key)
        s.setRange(lo, hi)
        s.setDecimals(1)
        s.setSuffix(suffix)
        s.setValue(value)
        p.row(label, s)
        spins[key] = s
    p.height, p.depth, p.angle = spins["height"], spins["depth"], spins["angle"]
    p.add = QtWidgets.QPushButton("Add text")
    p.add.setObjectName("SWStyle_SlicerTextAdd")
    p.lay.addWidget(p.add, p.lay.rowCount(), 0, 1, 4)
    p.note = QtWidgets.QLabel("")
    p.note.setObjectName("SWStyle_SlicerTextNote")
    p.note.setWordWrap(True)
    p.note.setMinimumWidth(240)
    _set = p.note.setText
    # the panel grows with its message (a wrapped message would be cut off at the panel's first height)
    p.note.setText = lambda text, _set=_set: (_set(text), p.layout().activate(), p.adjustSize())
    p.lay.addWidget(p.note, p.lay.rowCount(), 0, 1, 4)

    def changed(*_):
        tool.kind = p.kind.currentData()
        tool.text = p.text.text()
        tool.font = p.font.currentText() or None
        tool.height, tool.depth, tool.angle = p.height.value(), p.depth.value(), p.angle.value()
        tool.show()

    def add():
        changed()
        out = tool.apply()
        if isinstance(out, str):
            p.note.setText("<span style='color:#e53935'>%s</span>" % out)
            return None
        p.note.setText("Text added to %s%s." % (out.name, {
            "part": " as a part (right-click the object > Parts for its filament)",
            "modifier": " as a modifier (right-click the object > Parts > the text > Settings... for what it changes)"}
            .get(tool.kind, "")))
        if hasattr(toolbar.panel, "_object_changed"):
            toolbar.panel._object_changed(True)
        return out

    p.kind.currentIndexChanged.connect(changed)
    p.text.textChanged.connect(changed)
    p.font.currentIndexChanged.connect(changed)
    for s in spins.values():
        s.valueChanged.connect(changed)
    p.add.clicked.connect(add)
    p.changed, p.run = changed, add
    changed()
    return p
