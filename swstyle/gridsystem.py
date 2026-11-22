# SPDX-License-Identifier: LGPL-2.1-or-later
""









import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

V = App.Vector
TITLE = "Grid System"


def parse(text):
    """'3000, 3000, 4000' -> [3000.0, 3000.0, 4000.0]; '3 x 3000' or '3*3000' repeat."""
    out = []
    for part in text.replace(";", ",").split(","):
        part = part.strip().lower().replace("*", "x")
        if not part:
            continue
        if "x" in part:
            n, v = part.split("x", 1)
            out += [float(v)] * int(float(n))
        else:
            out.append(float(part))
    return out


def positions(spacings):
    out, at = [0.0], 0.0
    for s in spacings:
        at += s
        out.append(at)
    return out


def letter(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def lines(xs, ys, extension):
    """[(name, start, end)] of the grid lines in the level's plane."""
    px, py = positions(xs), positions(ys)
    out = []
    for i, x in enumerate(px):
        out.append((letter(i), V(x, py[0] - extension, 0), V(x, py[-1] + extension, 0)))
    for j, y in enumerate(py):
        out.append((str(j + 1), V(px[0] - extension, y, 0), V(px[-1] + extension, y, 0)))
    return out


class GridSystem:
    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty("App::PropertyString", "XSpacing", TITLE, "Spacings across (grid A, B, C...)")
        obj.addProperty("App::PropertyString", "YSpacing", TITLE, "Spacings along (grid 1, 2, 3...)")
        obj.addProperty("App::PropertyString", "Levels", TITLE, "Floor level heights")
        obj.addProperty("App::PropertyLength", "Extension", TITLE, "How far lines run past the outer ones")

    def execute(self, obj):
        return

    def dumps(self):
        return None

    def loads(self, state):
        return None


class GridView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return "Sketcher_CreateRectangle"

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_grid(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "GridSystem"


def build(grid):
    """(Re)makes grid's level planes and sketches from its values."""
    doc = grid.Document
    xs, ys, levels = parse(grid.XSpacing), parse(grid.YSpacing), parse(grid.Levels) or [0.0]
    made = []
    for n, z in enumerate(levels, 1):
        plane = doc.addObject("Part::DatumPlane", "Level")
        plane.Label = "%s Level%d" % (grid.Label, n)
        plane.Placement = App.Placement(V(0, 0, z), App.Rotation())
        sketch = doc.addObject("Sketcher::SketchObject", "GridSketch")
        sketch.Label = "%s Level%d Grid" % (grid.Label, n)
        sketch.AttachmentSupport = [(plane, "")]
        sketch.MapMode = "FlatFace"
        for _name, a, b in lines(xs, ys, float(grid.Extension)):
            sketch.addGeometry(Part.LineSegment(a, b))
        made += [plane, sketch]
    grid.Group = made
    doc.recompute()
    return made


def make(doc, xs="3x3000", ys="2x4000", levels="0, 3000", extension=1000.0):
    grid = doc.addObject("App::DocumentObjectGroupPython", "GridSystem")
    GridSystem(grid)
    if App.GuiUp:
        GridView(grid.ViewObject)
    grid.Label = "Grid System%d" % (1 + sum(1 for o in doc.Objects if is_grid(o) and o is not grid))
    grid.XSpacing, grid.YSpacing, grid.Levels, grid.Extension = xs, ys, levels, extension
    build(grid)
    return grid


def rebuild(grid):
    """Deletes grid's planes and sketches and makes them again."""
    doc = grid.Document
    children = list(grid.Group)
    grid.Group = []
    for child in children:
        if doc.getObject(child.Name) is not None:
            doc.removeObject(child.Name)
    build(grid)


class GridPanel:
    def __init__(self, doc, grid=None):
        self.doc, self.grid = doc, grid
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(TITLE)
        self.form.setProperty("swstyle_pm_title", TITLE)
        lay = QtWidgets.QFormLayout(self.form)
        self.xs = QtWidgets.QLineEdit(grid.XSpacing if grid else "3x3000")
        self.xs.setObjectName("SWGridX")
        self.ys = QtWidgets.QLineEdit(grid.YSpacing if grid else "2x4000")
        self.ys.setObjectName("SWGridY")
        self.levels = QtWidgets.QLineEdit(grid.Levels if grid else "0, 3000")
        self.levels.setObjectName("SWGridLevels")
        self.ext = QtWidgets.QDoubleSpinBox()
        self.ext.setObjectName("SWGridExtension")
        self.ext.setRange(0.0, 1e7)
        self.ext.setSuffix(" mm")
        self.ext.setValue(float(grid.Extension) if grid else 1000.0)
        lay.addRow("Spacings across (A, B, C...)", self.xs)
        lay.addRow("Spacings along (1, 2, 3...)", self.ys)
        lay.addRow("Level heights", self.levels)
        lay.addRow("Line extension", self.ext)
        self.info = QtWidgets.QLabel("Spacings as a list (3000, 4000) or repeats (3x3000).")
        self.info.setObjectName("SWGridInfo")
        self.info.setWordWrap(True)
        lay.addRow(self.info)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        try:
            xs, ys, lv = parse(self.xs.text()), parse(self.ys.text()), parse(self.levels.text())
        except Exception:
            self.info.setText("Use numbers: 3000, 4000 or 3x3000.")
            return False
        if not xs or not ys or any(v <= 0 for v in xs + ys):
            self.info.setText("Give at least one spacing each way, all above 0.")
            return False
        doc = self.doc
        doc.openTransaction(TITLE)
        try:
            if self.grid is None:
                self.grid = make(doc, self.xs.text(), self.ys.text(), self.levels.text() or "0", self.ext.value())
            else:
                g = self.grid
                g.XSpacing, g.YSpacing, g.Levels, g.Extension = (self.xs.text(), self.ys.text(),
                                                                 self.levels.text() or "0", self.ext.value())
                rebuild(g)
        finally:
            doc.commitTransaction()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


class _Command:
    def GetResources(self):
        return {"Pixmap": "Sketcher_CreateRectangle", "MenuText": TITLE,
                "ToolTip": "Lays out a structure's grid lines and floor levels as planes and sketches"}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        doc = App.ActiveDocument
        picked = [o for o in Gui.Selection.getSelection() if is_grid(o)]
        grid = picked[0] if picked else None
        QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(GridPanel(doc, grid)))


def register():
    if "SWStyle_GridSystem" not in Gui.listCommands():
        Gui.addCommand("SWStyle_GridSystem", _Command())
