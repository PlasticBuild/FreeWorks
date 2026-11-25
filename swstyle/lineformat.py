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
from PySide import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt
SKETCH = "Sketcher::SketchObject"
NOT_YET = "Not in FreeCAD yet"


DASHED_DRAWN = True    # linestyles.py draws every style (FreeCAD 1.1 itself draws them all solid)
STYLES = (("Solid", 0), ("Dashed", 1), ("Phantom", 11), ("Chain", 12), ("Center", 13),
          ("Stitch", 14), ("Thin/Thick Chain", 15))
DASH = 0x7E7E      # FreeCAD's dashed layer pattern

THICKNESS = (("Default", None), ("0.18mm", 1.0), ("0.25mm", 2.0), ("0.35mm", 3.0), ("0.5mm", 4.0),
             ("0.7mm", 5.0), ("1mm", 6.0), ("1.4mm", 8.0))


# ---------------------------------------------------------------- what is picked
def editing_sketch():
    doc = Gui.ActiveDocument
    vp = doc.getInEdit() if doc else None
    obj = getattr(vp, "Object", None)
    return obj if obj is not None and obj.isDerivedFrom(SKETCH) else None


def picked():
    """(sketch, [geometry indices]) for each sketch the pick touches. A sketch picked as a whole
    (tree row) gives every entity; entities picked in the sketch being edited give those."""
    out = {}
    edit = editing_sketch()
    for s in Gui.Selection.getSelectionEx("", 0):
        obj = s.Object
        if not obj.isDerivedFrom(SKETCH):
            continue
        subs = [n for n in s.SubElementNames if n]
        if not subs:
            out.setdefault(obj.Name, (obj, set()))[1].update(range(len(obj.Geometry)))
            continue
        for name in subs:
            name = name.split(".")[-1]
            if name.startswith("Edge") and name[4:].isdigit():
                out.setdefault(obj.Name, (obj, set()))[1].add(int(name[4:]) - 1)
    if not out and edit is not None:
        return []
    return [(obj, sorted(ids)) for obj, ids in out.values()]


def picked_sketches():
    return [obj for obj, _ids in picked()]


# ---------------------------------------------------------------- changes
def _undo(label, change):
    doc = App.ActiveDocument
    if doc is None:
        return False
    doc.openTransaction(label)
    try:
        change()
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()
    return True


def set_color(sketches, color):
    """color: QColor or (r, g, b) in 0..1, or None for FreeCAD's own colour."""
    if isinstance(color, QtGui.QColor):
        color = (color.redF(), color.greenF(), color.blueF())

    def change():
        for sk in sketches:
            vo = sk.ViewObject
            if color is None:
                vo.AutoColor = True
            else:
                vo.AutoColor = False
                vo.LineColor = tuple(color)
    return _undo("Line Color", change)


def set_thickness(sketches, width):
    """width in pixels, or None for FreeCAD's default width."""
    if width is None:
        width = float(App.ParamGet("User parameter:BaseApp/Preferences/View").GetInt("DefaultShapeLineWidth", 2))

    def change():
        for sk in sketches:
            sk.ViewObject.LineWidth = float(width)
    return _undo("Line Thickness", change)


def layer_of(sketch, index):
    try:
        return sketch.GeometryFacadeList[index].GeometryLayerId
    except Exception:
        return 0


def set_style(items, layer):
    """items: [(sketch, geometry indices)]; layer: STYLES' number (0 solid, 1 dashed...)."""
    def change():
        for sk, ids in items:
            facades = sk.GeometryFacadeList
            hit = False
            for i in ids:
                if 0 <= i < len(facades) and facades[i].GeometryLayerId != layer:
                    facades[i].GeometryLayerId = layer
                    hit = True
            if hit:
                sk.GeometryFacadeList = facades
                sk.touch()
        App.ActiveDocument.recompute()
        try:
            from . import linestyles
            linestyles.invalidate()
        except Exception as _fw_err:
            _fw_log("lineformat.py:152", _fw_err)
    return _undo("Line Style", change)


# ---------------------------------------------------------------- drop-downs
def _sample(pattern, width, color=Qt.black):
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pix = _hidpi.canvas(48, 12)
    pix.fill(Qt.transparent)
    p = QtGui.QPainter(pix)
    pen = QtGui.QPen(QtGui.QColor(color), width)
    if pattern == "dash":
        pen.setDashPattern([4, 2])
    elif pattern == "phantom":
        pen.setDashPattern([8, 2, 1, 2, 1, 2])
    elif pattern == "chain":
        pen.setDashPattern([8, 2, 1, 2])
    elif pattern == "center":
        pen.setDashPattern([12, 2, 2, 2])
    elif pattern == "thickchain":
        pen.setWidthF(width + 1)
        pen.setDashPattern([6, 2, 1, 2])
    elif pattern == "stitch":
        pen.setDashPattern([1, 2])
    p.setPen(pen)
    p.drawLine(2, 6, 46, 6)
    p.end()
    return QtGui.QIcon(pix)


LAST = []      # the last drop-down, for checks


def _popup(menu, at=None):
    LAST[:] = [menu]
    menu.popup(at or QtGui.QCursor.pos())


def style_menu(parent=None):
    menu = QtWidgets.QMenu(parent or Gui.getMainWindow())
    menu.setObjectName("SWLineStyleMenu")
    items = picked()
    current = {layer_of(sk, i) for sk, ids in items for i in ids}
    patterns = {"Solid": "solid", "Dashed": "dash", "Phantom": "phantom", "Chain": "chain", "Center": "center",
                "Stitch": "stitch", "Thin/Thick Chain": "thickchain"}
    for text, layer in STYLES:
        a = menu.addAction(_sample(patterns[text], 1.5), text)
        a.setObjectName("SWLineStyle_" + text.replace("/", ""))
        a.setEnabled(layer is not None and bool(items))
        if layer is None:
            a.setToolTip(NOT_YET)
        a.setCheckable(True)
        a.setChecked(layer is not None and current == {layer})
        if layer is not None:
            a.triggered.connect(lambda _c=False, l=layer: set_style(picked(), l))
    menu.setToolTipsVisible(True)
    return menu


def thickness_menu(parent=None):
    menu = QtWidgets.QMenu(parent or Gui.getMainWindow())
    menu.setObjectName("SWLineThicknessMenu")
    sketches = picked_sketches()
    for text, width in THICKNESS:
        a = menu.addAction(_sample("solid", width or 2.0), text)
        a.setObjectName("SWLineThickness_" + text)
        a.setEnabled(bool(sketches))
        a.triggered.connect(lambda _c=False, w=width: set_thickness(picked_sketches(), w))
    return menu


def pick_color(parent=None):
    sketches = picked_sketches()
    if not sketches:
        return None
    vo = sketches[0].ViewObject
    start = QtGui.QColor.fromRgbF(*vo.LineColor[:3])
    box = QtWidgets.QColorDialog(start, parent or Gui.getMainWindow())
    box.setWindowTitle("Line Color")
    box.setObjectName("SWLineColor")
    default = QtWidgets.QPushButton("Default")
    default.setObjectName("SWLineColorDefault")
    default.clicked.connect(lambda: (set_color(sketches, None), box.reject()))
    box.layout().addWidget(default)
    box.colorSelected.connect(lambda c: set_color(sketches, c))
    LAST[:] = [box]
    box.open()
    return box


# ---------------------------------------------------------------- commands
class _Cmd:
    def __init__(self, text, tip, run):
        self.text, self.tip, self.run = text, tip, run

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip}

    def Activated(self):
        self.run()

    def IsActive(self):
        return App.ActiveDocument is not None and bool(picked())


COMMANDS = {
    "SWStyle_LineColor": _Cmd("Line Color", "Changes the color of the selected sketch or sketch entities",
                              lambda: pick_color()),
    "SWStyle_LineThickness": _Cmd("Line Thickness", "Changes the line thickness of the selected sketch",
                                  lambda: _popup(thickness_menu())),
    "SWStyle_LineStyle": _Cmd("Line Style", "Changes the line style of the selected sketch entities",
                              lambda: _popup(style_menu())),
}


def register():
    try:
        from . import linestyles
        linestyles.install()
    except Exception as _fw_err:
        _fw_log("lineformat.py:271", _fw_err)
    for name, cmd in COMMANDS.items():
        if name not in Gui.listCommands():
            Gui.addCommand(name, cmd)
