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

import json
import math

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import naming, smflatten

COMMAND = "SWStyle_SMBendNotch"
TITLE = "Bend Notch"
LABEL = "Bend-Notch"
GROUP = "Bend Notch"
SHAPES = ("Triangular", "Circular", "Rectangular")
V = App.Vector
TOL = 1e-6


def _load(text):
    try:
        return [V(*p) for p in json.loads(text or "[]")]
    except Exception:
        return []


def _dump(points):
    return json.dumps([[p.x, p.y, p.z] for p in points])


def bend_lines(fp):
    from . import smcornertrim
    return smcornertrim.bend_lines(fp)


def _mid(e):
    return e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))


def chosen(notch, fp):
    """The bend lines the notch uses: all of them (Collect All Bends) or those through the picked points."""
    lines = bend_lines(fp)
    if notch.AllBends:
        return lines
    out = []
    for p in _load(notch.BendPoints):
        best = min(lines, key=lambda l: l.distToShape(Part.Vertex(p))[0], default=None)
        if best is not None and best.distToShape(Part.Vertex(p))[0] < 0.5 and best not in out:
            out.append(best)
    return out


def tool(p, inward, n, kind, width, depth, height):
    """The notch solid at the outline point p, cutting inward along the bend line, through the sheet."""
    u = inward.normalize()
    w = n.cross(u).normalize()
    base = p - n * height
    if kind == "Circular":
        return Part.makeCylinder(width / 2.0, 2 * height, base, n)
    if kind == "Rectangular":
        pts = [p - w * (width / 2), p + w * (width / 2), p + w * (width / 2) + u * depth, p - w * (width / 2) + u * depth]
    else:
        pts = [p - w * (width / 2), p + w * (width / 2), p + u * depth]
    pts = [q - n * height for q in pts]
    face = Part.Face(Part.makePolygon(pts + [pts[0]]))
    return face.extrude(n * (2 * height))


def apply(notch, shape, fp):
    from . import smcornertrim
    n, _f = smcornertrim.flat_normal(shape)
    height = shape.BoundBox.DiagonalLength + 10
    width, depth = float(notch.Width), float(notch.Depth)
    tools = []
    outline = Part.makeCompound([e for e in shape.Edges])
    for line in chosen(notch, fp):
        a, b = line.Vertexes[0].Point, line.Vertexes[-1].Point
        for p, q in ((a, b), (b, a)):
            # the line's end on the outline: where it leaves the sheet
            if outline.distToShape(Part.Vertex(p))[0] > max(1.0, depth):
                continue
            tools.append(tool(p, q - p, n, notch.NotchShape, width, depth, height))
    if not tools:
        return shape
    cut = shape.cut(Part.makeCompound(tools))
    try:
        cut = cut.removeSplitter()
    except Exception as _fw_err:
        _fw_log("smbendnotch.py:110", _fw_err)
    return cut.Solids[0] if len(cut.Solids) == 1 else cut


class BendNotch:
    def __init__(self, obj, fp):
        add = obj.addProperty
        add("App::PropertyLink", "FlatPattern", GROUP, "The flat pattern it notches")
        add("App::PropertyBool", "AllBends", GROUP, "Collect All Bends")
        add("App::PropertyString", "BendPoints", GROUP, "Points on the picked bend lines (JSON)")
        add("App::PropertyEnumeration", "NotchShape", GROUP, "Triangular, Circular or Rectangular")
        obj.NotchShape = list(SHAPES)
        add("App::PropertyLength", "Width", GROUP, "Notch width (Circular: diameter)")
        add("App::PropertyLength", "Depth", GROUP, "Notch depth into the sheet")
        obj.setEditorMode("BendPoints", 2)
        obj.FlatPattern = fp
        obj.BendPoints = "[]"
        obj.Width, obj.Depth = 2.0, 2.0
        obj.Proxy = self

    def execute(self, obj):
        pass        # the Flat-Pattern applies it (smcornertrim.apply_all)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderBendNotch:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        try:
            import os
            import SheetMetalTools
            return os.path.join(SheetMetalTools.icons_path, "SheetMetal_AddRelief.svg")
        except Exception:
            return ""

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        fp = vobj.Object.FlatPattern
        if fp is None:
            return False
        if not fp.SWFlattened:
            smflatten.set_flat(fp.Body, True)
        vobj.Object.Document.openTransaction("Edit " + TITLE)
        try:
            Gui.Control.showDialog(Panel(vobj.Object, False))
        except BaseException:
            try:
                vobj.Object.Document.abortTransaction()
            except Exception:
                pass
            raise
        return True

    def unsetEdit(self, vobj, mode=0):
        return False

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def onDelete(self, vobj, subelements):
        fp = vobj.Object.FlatPattern
        if fp is not None:
            QtCore.QTimer.singleShot(0, lambda: (fp.touch(), fp.Document.recompute()))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_bend_notch(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "BendNotch"


def make(fp):
    doc = fp.Document
    obj = doc.addObject("App::FeaturePython", "BendNotch")
    BendNotch(obj, fp)
    if App.GuiUp:
        ViewProviderBendNotch(obj.ViewObject)
    obj.Label = naming.next_label(doc, LABEL)
    return obj


# ================================================================ PropertyManager
_LAST = None


class Panel:
    def __init__(self, obj, new):
        global _LAST
        _LAST = self
        from .smbaseflange import _box, _spin
        self.obj, self.new, self.busy = obj, new, True
        self.points = _load(obj.BendPoints)
        bends = _box("Bends")
        f = bends.layout()
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWSMNotchBends")
        self.list.setMaximumHeight(56)
        self.list.setProperty("swpickbox", True)       # a selection box: its colour strip, as the other pick boxes
        self.list.setToolTip("Bends: pick bend lines of the flat pattern")
        f.addRow(self.list)
        self.collect = QtWidgets.QPushButton("Collect All Bends")
        self.collect.setObjectName("SWSMNotchCollect")
        self.collect.clicked.connect(self._collect)
        f.addRow(self.collect)
        params = _box("Notch Parameters")
        g = params.layout()
        row = QtWidgets.QVBoxLayout()       # one under the other: the page fits the 300 px pane
        self.shapes = QtWidgets.QButtonGroup(params)
        for k, s in enumerate(SHAPES):
            b = QtWidgets.QRadioButton(s)
            b.setObjectName("SWSMNotch" + s)
            b.setChecked(obj.NotchShape == s)
            self.shapes.addButton(b, k)
            row.addWidget(b)
        g.addRow(row)
        self.width = _spin("SWSMNotchWidth", float(obj.Width), 0.01, 1000.0)
        self.depth = _spin("SWSMNotchDepth", float(obj.Depth), 0.01, 1000.0)
        g.addRow("Width:", self.width)
        g.addRow("Depth:", self.depth)
        self.error = QtWidgets.QLabel("Select bend lines, or click Collect All Bends.")
        self.error.setWordWrap(True)
        g.addRow(self.error)
        bends.setProperty("swstyle_pm_title", TITLE)
        bends.setProperty("swstyle_pm_icon", "SheetMetal_AddRelief")
        self.form = [bends, params]
        self.shapes.buttonClicked.connect(self._changed)
        self.width.valueChanged.connect(self._changed)
        self.depth.valueChanged.connect(self._changed)
        self.busy = False
        self._fill()
        Gui.Selection.addObserver(self)

    def _fill(self):
        self.list.clear()
        if self.obj.AllBends:
            for k, _l in enumerate(bend_lines(self.obj.FlatPattern), 1):
                self.list.addItem("Bend line %d" % k)
        else:
            for k, _p in enumerate(self.points, 1):
                self.list.addItem("Bend line <%d>" % k)
        circ = self.shapes.checkedId() == 1
        self.depth.setEnabled(not circ)

    def _collect(self):
        self.obj.AllBends = True
        self._changed()

    def picked(self, name, sub, at=None):
        fp = self.obj.FlatPattern
        o = fp.Document.getObject(name)
        if o is None or not sub.startswith("Edge"):
            return
        try:
            e = o.Shape.getElement(sub)
        except Exception as _fw_err:
            _fw_log("smbendnotch.py:288", _fw_err)
            return
        p = _mid(e)
        lines = bend_lines(fp)
        if not lines or min(l.distToShape(Part.Vertex(p))[0] for l in lines) > 0.5:
            return
        self.obj.AllBends = False
        self.points.append(p)
        self._changed()

    def addSelection(self, doc, name, sub, point):
        QtCore.QTimer.singleShot(0, lambda: (self.picked(name, sub), Gui.Selection.clearSelection()))

    def _changed(self, *_a):
        if self.busy:
            return
        o = self.obj
        o.BendPoints = _dump(self.points)
        o.NotchShape = SHAPES[max(0, self.shapes.checkedId())]
        o.Width = self.width.value()
        o.Depth = self.depth.value()
        self._fill()
        fp = o.FlatPattern
        fp.touch()
        fp.Document.recompute()
        self.error.setText("" if self.list.count() else "Select bend lines, or click Collect All Bends.")

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smbendnotch.py:313", _fw_err)
        Gui.Control.closeDialog()

    def accept(self):
        if not self.list.count():
            self.error.setText("Select bend lines, or click Collect All Bends.")
            return False
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        doc.abortTransaction()
        doc.recompute()
        self._close()
        return True


def start():
    body = smflatten._body()
    if body is None or smflatten.root(body) is None:
        return
    picked = [(s.ObjectName, n) for s in Gui.Selection.getSelectionEx() for n in s.SubElementNames]
    if not smflatten.is_flat():
        smflatten.set_flat(body, True)       # the notches are cut in the flat pattern
    fp = smflatten.flat_pattern(body)
    if fp is None:
        return
    doc = fp.Document
    doc.openTransaction(TITLE)
    try:
        obj = make(fp)
        panel = Panel(obj, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    for name, sub in picked:
        panel.picked(name, sub)


class Command:
    def GetResources(self):
        return {"Pixmap": "SheetMetal_AddRelief", "MenuText": TITLE,
                "ToolTip": "Cuts small notches in the flat pattern where the bend lines meet its edge, to line up bends."}

    def IsActive(self):
        try:
            body = smflatten._body()
            return body is not None and smflatten.root(body) is not None and not Gui.Control.activeDialog()
        except Exception:
            return False

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
