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

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

V = App.Vector
TITLE = "Model Break View"
DIRECTIONS = ("Longest", "X", "Y", "Z")


def _axis(name, shape):
    if name == "X":
        return V(1, 0, 0)
    if name == "Y":
        return V(0, 1, 0)
    if name == "Z":
        return V(0, 0, 1)
    bb = shape.BoundBox
    sizes = [(bb.XLength, V(1, 0, 0)), (bb.YLength, V(0, 1, 0)), (bb.ZLength, V(0, 0, 1))]
    return max(sizes, key=lambda s: s[0])[1]


def extent(shape, direction):
    """(start, end) of shape along direction."""
    bb = shape.BoundBox
    corners = [V(x, y, z) for x in (bb.XMin, bb.XMax) for y in (bb.YMin, bb.YMax) for z in (bb.ZMin, bb.ZMax)]
    ds = [c.dot(direction) for c in corners]
    return min(ds), max(ds)


def _merged(breaks, lo, hi):
    out = []
    for a, b in sorted((min(a, b), max(a, b)) for a, b in breaks):
        a, b = max(a, lo), min(b, hi)
        if b - a <= 1e-6:
            continue
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def broken(shape, direction, breaks, gap):
    """shape with each break (from, to), measured along direction from its start, taken out and
    the pieces after it slid back so that gap is left."""
    import Part
    d = V(direction)
    d.normalize()
    start, end = extent(shape, d)
    cuts = _merged([(start + a, start + b) for a, b in breaks], start, end)
    if not cuts:
        return shape.copy()
    size = shape.BoundBox.DiagonalLength * 2 + 10
    rot = App.Rotation(V(0, 0, 1), d)
    pieces, edges = [], [start] + [x for c in cuts for x in c] + [end]
    shift = 0.0
    for i in range(0, len(edges), 2):
        lo, hi = edges[i], edges[i + 1]
        if i > 0:
            a, b = edges[i - 1], edges[i]
            shift += (b - a) - gap
        if hi - lo <= 1e-6:
            continue
        slab = Part.makeBox(size, size, hi - lo, V(-size / 2, -size / 2, lo))
        slab.Placement = App.Placement(V(0, 0, 0), rot).multiply(slab.Placement)
        piece = shape.common(slab)
        piece.translate(d * -shift)
        pieces.append(piece)
    return Part.makeCompound(pieces)


class ModelBreak:
    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Source", TITLE, "The part shown broken")
        obj.addProperty("App::PropertyEnumeration", "BreakDirection", TITLE, "Along which the breaks lie")
        obj.BreakDirection = list(DIRECTIONS)
        obj.addProperty("App::PropertyLength", "Gap", TITLE, "Space left between the pieces")
        obj.Gap = 10.0
        obj.addProperty("App::PropertyPythonObject", "Breaks", TITLE, "(from, to) along the direction")
        obj.Breaks = []
        obj.addProperty("App::PropertyBool", "Active", TITLE, "Shown broken")
        obj.Active = True
        obj.addProperty("Part::PropertyPartShape", "BrokenShape", TITLE, "What is shown")
        obj.setPropertyStatus("BrokenShape", ["Output", "Transient", "Hidden"])

    def execute(self, obj):
        src = obj.Source
        shape = getattr(src, "Shape", None)
        if shape is None or shape.isNull():
            return
        obj.BrokenShape = broken(shape, _axis(obj.BreakDirection, shape), obj.Breaks or [], float(obj.Gap))

    def onDocumentRestored(self, obj):
        obj.touch()

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _ink(src):
    try:
        m = src.ViewObject.ShapeAppearance[0]
        return tuple(m.DiffuseColor[:3])
    except Exception:
        return (0.8, 0.8, 0.8)


class ModelBreakView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        from pivy import coin
        self.Object = vobj.Object
        self.node = coin.SoSeparator()
        vobj.addDisplayMode(self.node, "Broken")
        self.rebuild()

    def getDisplayModes(self, vobj):
        return ["Broken"]

    def getDefaultDisplayMode(self):
        return "Broken"

    def setDisplayMode(self, mode):
        return mode

    def getIcon(self):
        return "Part_Section"

    def updateData(self, obj, prop):
        if prop in ("BrokenShape", "Active"):
            self.rebuild()

    def onChanged(self, vobj, prop):
        return

    def rebuild(self):
        from pivy import coin
        obj = self.Object
        self.node.removeAllChildren()
        shape = obj.BrokenShape
        if shape is None or shape.isNull():
            return
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
        hints.shapeType = coin.SoShapeHints.UNKNOWN_SHAPE_TYPE
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(*_ink(obj.Source))
        faces = coin.SoInput()
        faces.setBuffer(shape.writeInventor())
        body = coin.SoDB.readAll(faces)
        solid = coin.SoSeparator()
        offset = coin.SoPolygonOffset()     # edges drawn over the faces, as in the part's own view
        solid.addChild(offset)
        solid.addChild(hints)
        solid.addChild(mat)
        if body is not None:
            solid.addChild(body)
        self.node.addChild(solid)
        lines = coin.SoSeparator()
        style = coin.SoDrawStyle()
        style.lineWidth.setValue(1.5)
        black = coin.SoBaseColor()
        black.rgb.setValue(0.05, 0.05, 0.05)
        lines.addChild(style)
        lines.addChild(black)
        for edge in shape.Edges:
            pts = edge.discretize(Deflection=0.05) if edge.Length > 1e-9 else []
            if len(pts) < 2:
                continue
            c = coin.SoCoordinate3()
            c.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
            ls = coin.SoLineSet()
            ls.numVertices.setValues(0, 1, [len(pts)])
            sep = coin.SoSeparator()
            sep.addChild(c)
            sep.addChild(ls)
            lines.addChild(sep)
        self.node.addChild(lines)

    def onDelete(self, vobj, subelements):
        show(vobj.Object, False)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_break(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "ModelBreak"


def breaks(doc):
    return [o for o in doc.Objects if is_break(o)] if doc else []


def show(obj, on):
    """Shows obj's part broken (on) or whole."""
    obj.Active = bool(on)
    src = obj.Source
    if not App.GuiUp:
        return
    try:
        obj.ViewObject.Visibility = bool(on)
        if src is not None:
            src.ViewObject.Visibility = not on
    except Exception as _fw_err:
        _fw_log("modelbreak.py:239", _fw_err)


def _source(doc):
    from . import evaluate
    picked = [s.Object for s in Gui.Selection.getSelectionEx()] if App.GuiUp else []
    for obj in picked:
        body = obj.getParentGeoFeatureGroup() if hasattr(obj, "getParentGeoFeatureGroup") else None
        target = body if body is not None and body.isDerivedFrom("PartDesign::Body") else obj
        if getattr(target, "Shape", None) is not None and not target.Shape.isNull() and target.Shape.Solids:
            return target
    bodies = evaluate.visible_bodies(doc)
    return bodies[0] if bodies else None


def make(doc, source, direction="Longest", gap=10.0, cuts=()):
    obj = doc.addObject("App::FeaturePython", "ModelBreakView")
    ModelBreak(obj)
    obj.Label = TITLE
    obj.Source = source
    obj.BreakDirection = direction
    obj.Gap = gap
    obj.Breaks = [tuple(c) for c in cuts]
    if App.GuiUp:
        ModelBreakView(obj.ViewObject)
    doc.recompute()
    show(obj, True)
    return obj


class BreakPanel:
    def __init__(self, doc, obj=None):
        self.doc = doc
        self.obj = obj
        self.new = obj is None
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(TITLE)
        self.form.setProperty("swstyle_pm_title", TITLE)
        lay = QtWidgets.QVBoxLayout(self.form)
        form = QtWidgets.QFormLayout()
        self.direction = QtWidgets.QComboBox()
        self.direction.setObjectName("SWBreakDirection")
        self.direction.addItems(["Longest direction", "Along X", "Along Y", "Along Z"])
        self.gap = QtWidgets.QDoubleSpinBox()
        self.gap.setObjectName("SWBreakGap")
        self.gap.setRange(0.0, 1e6)
        self.gap.setSuffix(" mm")
        self.gap.setValue(10.0)
        form.addRow("Break Direction", self.direction)
        form.addRow("Gap", self.gap)
        lay.addLayout(form)
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setObjectName("SWBreakTable")
        self.table.setHorizontalHeaderLabels(["From (mm)", "To (mm)"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setFixedHeight(130)
        lay.addWidget(self.table)
        row = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton("Add Break")
        add.setObjectName("SWBreakAdd")
        add.clicked.connect(self.add_break)
        remove = QtWidgets.QPushButton("Remove Break")
        remove.setObjectName("SWBreakRemove")
        remove.clicked.connect(self.remove_break)
        row.addWidget(add)
        row.addWidget(remove)
        lay.addLayout(row)
        self.info = QtWidgets.QLabel("")
        self.info.setObjectName("SWBreakInfo")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        doc.openTransaction(TITLE)
        try:
            if self.obj is None:
                source = _source(doc)
                if source is None:
                    self.info.setText("There is no part to break.")
                    return
                length = self._length(source, "Longest")
                self.obj = make(doc, source, "Longest", 10.0, [(length / 3.0, 2.0 * length / 3.0)])
            else:
                show(self.obj, True)
            self._load()
            self.direction.currentIndexChanged.connect(self.changed)
            self.gap.valueChanged.connect(self.changed)
            self.table.itemChanged.connect(self.changed)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise

    def _length(self, source, name):
        shape = source.Shape
        a, b = extent(shape, _axis(name, shape))
        return b - a

    def _load(self):
        obj = self.obj
        self.direction.setCurrentIndex(DIRECTIONS.index(obj.BreakDirection))
        self.gap.setValue(float(obj.Gap))
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for a, b in obj.Breaks or []:
            self._row(a, b)
        self.table.blockSignals(False)
        self._say()

    def _row(self, a, b):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QtWidgets.QTableWidgetItem("%g" % a))
        self.table.setItem(r, 1, QtWidgets.QTableWidgetItem("%g" % b))

    def _say(self):
        if self.obj is None or self.obj.Source is None:
            return
        length = self._length(self.obj.Source, self.obj.BreakDirection)
        self.info.setText("The part is %.1f mm long along the break direction; breaks are measured from its start."
                          % length)

    def _cuts(self):
        out = []
        for r in range(self.table.rowCount()):
            try:
                out.append((float(self.table.item(r, 0).text()), float(self.table.item(r, 1).text())))
            except Exception as _fw_err:
                _fw_log("modelbreak.py:368", _fw_err)
                continue
        return out

    def add_break(self):
        if self.obj is None:
            return
        length = self._length(self.obj.Source, self.obj.BreakDirection)
        self.table.blockSignals(True)
        self._row(length * 0.4, length * 0.6)
        self.table.blockSignals(False)
        self.changed()

    def remove_break(self):
        r = self.table.currentRow()
        if r < 0:
            r = self.table.rowCount() - 1
        if r >= 0:
            self.table.removeRow(r)
            self.changed()

    def changed(self, *args):
        obj = self.obj
        if obj is None:
            return
        obj.BreakDirection = DIRECTIONS[self.direction.currentIndex()]
        obj.Gap = self.gap.value()
        obj.Breaks = self._cuts()
        self.doc.recompute()
        self._say()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        if self.obj is not None:
            self.changed()
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        if self.new and self.obj is not None:
            try:
                src = self.obj.Source
                if src is not None:
                    src.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("modelbreak.py:407", _fw_err)
        self.doc.abortTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True


class _Command:
    def GetResources(self):
        return {"Pixmap": "Part_Section", "MenuText": TITLE,
                "ToolTip": "Shows a long part shortened, with stretches taken out (the part itself is unchanged)"}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        doc = App.ActiveDocument
        have = breaks(doc)
        QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(BreakPanel(doc, have[0] if have else None)))


class _Toggle:
    def GetResources(self):
        return {"Pixmap": "Part_Section", "MenuText": "Toggle Model Break View",
                "ToolTip": "Shows the part whole, or broken again"}

    def IsActive(self):
        return bool(breaks(App.ActiveDocument))

    def Activated(self):
        for obj in breaks(App.ActiveDocument):
            show(obj, not obj.Active)


class _Watch:
    """Undo and Redo add and remove the break without its view provider being told: put the part's
    own display back (or hide it again) when that happens."""

    def slotDeletedObject(self, obj):
        if is_break(obj) and obj.Source is not None:
            name, doc = obj.Source.Name, obj.Document
            QtCore.QTimer.singleShot(0, lambda: _reshow(doc, name))

    def slotCreatedObject(self, obj):
        if is_break(obj):
            doc, name = obj.Document, obj.Name
            QtCore.QTimer.singleShot(0, lambda: _rehide(doc, name))


def _reshow(doc, name):
    try:
        src = doc.getObject(name)
        if src is not None and not any(o.Source == src and o.Active for o in breaks(doc)):
            src.ViewObject.Visibility = True
    except Exception as _fw_err:
        _fw_log("modelbreak.py:462", _fw_err)


def _rehide(doc, name):
    try:
        obj = doc.getObject(name)
        if obj is not None and obj.Source is not None:
            show(obj, obj.Active)
    except Exception as _fw_err:
        _fw_log("modelbreak.py:471", _fw_err)


_watch = None


def register():
    global _watch
    if _watch is None:
        _watch = _Watch()
        App.addDocumentObserver(_watch)
    if "SWStyle_ModelBreakView" not in Gui.listCommands():
        Gui.addCommand("SWStyle_ModelBreakView", _Command())
    if "SWStyle_ToggleModelBreak" not in Gui.listCommands():
        Gui.addCommand("SWStyle_ToggleModelBreak", _Toggle())
