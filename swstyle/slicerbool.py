"""Mesh Boolean: the slicers' Mesh Boolean tool on the plate toolbar (B). Union, Difference or Intersection of an
Object and a Tool, picked from the selected objects or the parts of a selected object (Split to parts), with the
slicers' Delete input. It works on the solids (exact), where the slicers work on meshes; the result keeps the
object's name, filament, own settings and height ranges, and stands on the plate where the two were."""
import FreeCAD as App
from PySide import QtWidgets

OPS = (("union", "Union", "Union"), ("difference", "Difference", "Subtract"),
       ("intersection", "Intersection", "Intersection"))


def entries(bed):
    """What can be an Object or a Tool: [(item, solid index or None, label)] from the selected objects (the parts
    of an object split to parts, one entry each)."""
    out = []
    for it in bed.targets():
        solids = it.shape.Solids if it.shape is not None else []
        if it.parts and len(solids) == len(it.parts) and len(solids) > 1:
            for k, part in enumerate(it.parts):
                out.append((it, k, "%s: %s" % (it.name, part.get("name") or "Part %d" % (k + 1))))
        else:
            out.append((it, None, it.name))
    return out


def _world(bed, it, shape):
    """A shape of the object in plate coordinates (its rotation, scale and place baked in)."""
    m = bed.item_matrix(it)
    if all(abs(v - 1.0) < 1e-9 for v in it.scale):
        s = shape.copy()
        s.transformShape(m)
        return s
    return shape.copy().transformGeometry(m)


def _solid(it, k):
    return it.shape.Solids[k] if k is not None else it.shape


def _rest(it, drop):
    """The parts of an object split to parts, without the ones in drop: [(solid, part dict)]."""
    if not it.parts:
        return []
    return [(s, dict(p)) for k, (s, p) in enumerate(zip(it.shape.Solids, it.parts)) if k not in drop]


def _rebuilt(bed, it, pieces, name=None):
    """A new plate object from [(world solid, part dict or None)], standing where the pieces are."""
    import Part
    from . import slicerplate
    solids = [s for s, _p in pieces]
    shape = solids[0] if len(solids) == 1 else Part.makeCompound(solids)
    new = slicerplate.Item(name or it.name, shape, slicerplate.mesh_of(shape), it.source)
    box = shape.BoundBox
    new.xy = ((box.XMin + box.XMax) / 2.0, (box.YMin + box.YMax) / 2.0)
    new.plate, new.pinned, new.slot = it.plate, it.pinned, it.slot
    new.settings = dict(it.settings)
    new.ranges = [dict(r) for r in it.ranges]
    if len(pieces) > 1:
        new.parts = [p or {"name": "Part %d" % (k + 1), "slot": 0} for k, (_s, p) in enumerate(pieces)]
    return new


def apply(bed, obj, tool, op, delete_input=True):
    """obj and tool: entries. Returns the new object, or a message saying why nothing was done."""
    (oit, ok, _ol), (tit, tk, _tl) = obj, tool
    if oit is tit and ok == tk:
        return "The Object and the Tool are the same: pick two different ones."
    if oit.plate != tit.plate:
        return "The Object and the Tool are on different plates."
    a, b = _world(bed, oit, _solid(oit, ok)), _world(bed, tit, _solid(tit, tk))
    try:
        r = {"union": a.fuse, "difference": a.cut, "intersection": a.common}[op](b)
        r = r.removeSplitter()
    except Exception as error:
        return "The boolean failed: %s" % error
    solids = [s for s in r.Solids if s.Volume > 1e-6]
    if not solids:
        return "The result is empty: the Object and the Tool do not overlap." if op == "intersection" else \
            "The result is empty."
    same = oit is tit
    # the object's other parts stay with it (and the tool, when it is one of them and is kept)
    drop = {ok} | ({tk} if same else set())
    head = (dict(oit.parts[ok]) if oit.parts and ok is not None else None)
    pieces = [(_world(bed, oit, s), p) for s, p in _rest(oit, drop)]
    pieces += [(s, dict(head) if head else ({"name": oit.name, "slot": 0} if pieces else None)) for s in solids]
    if same and not delete_input:
        pieces.append((_world(bed, oit, _solid(oit, tk)), dict(oit.parts[tk])))
    new = _rebuilt(bed, oit, pieces)
    index = bed.items.index(oit)
    bed.items[index] = new
    if not same and delete_input:
        rest = _rest(tit, {tk}) if tk is not None else []
        if rest:
            bed.items[bed.items.index(tit)] = _rebuilt(bed, tit, [(_world(bed, tit, s), p) for s, p in rest])
        else:
            bed.items.remove(tit)
    bed.selected = {bed.items.index(new)}
    bed._redraw()
    bed._changed()
    return new


def panel(toolbar, ToolPanel):
    """The Mesh Boolean tool panel."""
    bed = toolbar.bed
    p = ToolPanel("Mesh Boolean", toolbar.parentWidget())
    p.setObjectName("SWSlicerToolPanel")
    tabs = QtWidgets.QHBoxLayout()
    p.op_buttons = {}
    group = QtWidgets.QButtonGroup(p)
    for key, text, _verb in OPS:
        b = QtWidgets.QPushButton(text)
        b.setObjectName("SWStyle_SlicerBool_" + key)
        b.setCheckable(True)
        group.addButton(b)
        tabs.addWidget(b)
        p.op_buttons[key] = b
    p.lay.addLayout(tabs, p.lay.rowCount(), 0, 1, 4)
    p.object = QtWidgets.QComboBox()
    p.object.setObjectName("SWStyle_SlicerBoolObject")
    p.tool = QtWidgets.QComboBox()
    p.tool.setObjectName("SWStyle_SlicerBoolTool")
    p.row("Object", p.object)
    p.row("Tool", p.tool)
    p.delete_input = QtWidgets.QCheckBox("Delete input")
    p.delete_input.setObjectName("SWStyle_SlicerBoolDelete")
    p.delete_input.setChecked(True)
    p.delete_input.setToolTip("Take the Tool away after the operation (off: the Tool stays as it was)")
    p.lay.addWidget(p.delete_input, p.lay.rowCount(), 0, 1, 4)
    p.go = QtWidgets.QPushButton("Union")
    p.go.setObjectName("SWStyle_SlicerBoolGo")
    p.lay.addWidget(p.go, p.lay.rowCount(), 0, 1, 4)
    p.note = QtWidgets.QLabel("")
    p.note.setObjectName("SWStyle_SlicerBoolNote")
    p.note.setWordWrap(True)
    p.note.setMinimumWidth(240)
    _set = p.note.setText
    # the panel grows with its message (a wrapped message would be cut off at the panel's first height)
    p.note.setText = lambda text, _set=_set: (_set(text), p.layout().activate(), p.adjustSize())
    p.lay.addWidget(p.note, p.lay.rowCount(), 0, 1, 4)
    p.op = "union"

    def set_op(key):
        p.op = key
        p.op_buttons[key].setChecked(True)
        p.go.setText(dict((k, v) for k, _t, v in OPS)[key])

    def fill():
        p.entries = entries(bed)
        for combo, pick in ((p.object, 0), (p.tool, 1)):
            combo.blockSignals(True)
            combo.clear()
            for _it, _k, label in p.entries:
                combo.addItem(label)
            combo.setCurrentIndex(pick if pick < combo.count() else -1)     # one entry: no Tool yet
            combo.blockSignals(False)
        if len(p.entries) < 2:
            p.note.setText("Select two objects on the plate (Ctrl+click), or an object split to parts.")
        else:
            p.note.setText("")

    def go():
        if len(p.entries) < 2:
            fill()
            if len(p.entries) < 2:
                return None
        obj, tool = p.entries[p.object.currentIndex()], p.entries[p.tool.currentIndex()]
        out = apply(bed, obj, tool, p.op, p.delete_input.isChecked())
        if isinstance(out, str):
            p.note.setText("<span style='color:#e53935'>%s</span>" % out)
            return None
        fill()
        p.note.setText("%s done: %s." % (p.go.text(), out.name))
        return out

    for key, b in p.op_buttons.items():
        b.clicked.connect(lambda _=False, k=key: set_op(k))
    p.go.clicked.connect(go)
    p.set_op, p.fill, p.run = set_op, fill, go
    set_op("union")
    fill()
    return p
