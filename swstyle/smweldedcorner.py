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
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import naming, smedgegeom
from .smbaseflange import _box, _spin
from .smclosedcorner import _plane, face_at, face_normal, inside_point
from .smedgeflange import error_label
from .smunfold import _DeleteKey, _list, _sheet_body

COMMAND = "SWStyle_SMWeldedCorner"
TITLE = "Welded Corner"
GROUP = "Welded Corner"
V = App.Vector
NOT_GAP = "Select a side face of a closed corner: a flat face with the other flange a small gap across from it."


def _icon():
    try:
        from freecad.frameforge import ff_tools
        return os.path.join(ff_tools.ICONPATH, "joincurve.svg")
    except Exception:
        try:
            import SheetMetalTools
            return os.path.join(SheetMetalTools.icons_path, "SheetMetal_AddJunction.svg")
        except Exception:
            return ""


# ================================================================ geometry
def gap_across(shape, face, widest=None):
    """The face across the corner's gap from face: parallel, facing it, the nearest one. (face, width)"""
    n, c = face_normal(face), face.CenterOfMass
    widest = widest if widest is not None else 5.0
    best = None
    for g in shape.Faces:
        if not _plane(g) or g.isSame(face) or face_normal(g).dot(n) > -1 + 1e-6:
            continue
        w = (g.CenterOfMass - c).dot(n)
        if w <= 1e-7 or w > widest:
            continue
        # the two faces must overlap seen along the normal
        moved = g.copy()
        moved.translate(n * -w)
        if face.common(moved).Area < 1e-6:
            continue
        if best is None or w < best[1]:
            best = (g, w)
    return best


def fill(shape, face, stop_point=None, keep_point=None):
    """The weld filling the gap in front of face (and stopping at stop_point's plane)."""
    found = gap_across(shape, face)
    if found is None:
        raise ValueError(NOT_GAP)
    other, w = found
    n = face_normal(face)
    a = face.extrude(n * w)
    moved = other.copy()
    moved.translate(n * -w)
    weld = a.common(moved.extrude(n * w))
    if weld.Volume < 1e-9:
        raise ValueError(NOT_GAP)
    if stop_point is not None:
        # the corner runs along the gap face's longest straight edge
        lines = [e for e in face.Edges if e.Curve.TypeId == "Part::GeomLine"]
        along = max(lines, key=lambda e: e.Length).tangentAt(0) if lines else None
        if along is not None:
            keep = keep_point if keep_point is not None else face.CenterOfMass
            k = along if (keep - stop_point).dot(along) > 0 else along * -1
            size = shape.BoundBox.DiagonalLength * 4 + 100
            box = Part.makeBox(2 * size, 2 * size, size, V(-size, -size, 0))
            box.Placement = App.Placement(stop_point, App.Rotation(V(0, 0, 1), k))
            weld = weld.common(box)
    return weld


def inside_edge(shape, weld):
    """The corner's inside edge along the weld: straight, along the weld, nearest the part's middle."""
    lines = [e for e in weld.Edges if e.Curve.TypeId == "Part::GeomLine"]
    if not lines:
        return None
    along = max(lines, key=lambda e: e.Length).tangentAt(0)
    mid = shape.BoundBox.Center
    box = weld.BoundBox
    box.enlarge(1e-3)
    best = None
    for i, e in enumerate(shape.Edges, 1):
        if e.Curve.TypeId != "Part::GeomLine" or abs(abs(e.tangentAt(0).dot(along)) - 1) > 1e-6:
            continue
        p = e.CenterOfMass
        if not box.isInside(p):
            continue
        d = ((p - mid) - along * (p - mid).dot(along)).Length
        if best is None or d < best[0]:
            best = (d, i)
    return best[1] if best else None


# ================================================================ feature
_LAST = None        # the open Welded Corner PropertyManager


class SWWeldedCorner:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyStringList", "CornerToWeld", GROUP, "Side faces of the corners, as picked")
        add("App::PropertyVectorList", "CornerPoints", GROUP, "A point on each picked face")
        add("App::PropertyString", "StoppingPoint", GROUP, "Where the weld stops, as picked")
        add("App::PropertyVector", "StopPoint", GROUP, "A point where the weld stops")
        add("App::PropertyBool", "HasStop", GROUP, "The weld has a stopping point")
        add("App::PropertyBool", "AddFillet", GROUP, "A fillet weld in the corner's inside edge")
        add("App::PropertyLength", "FilletRadius", GROUP, "Fillet radius")
        add("App::PropertyBool", "AddTexture", GROUP, "Weld texture")
        add("App::PropertyBool", "AddWeldSymbol", GROUP, "Weld symbol")
        obj.FilletRadius = 1.0
        _more_props(obj)
        obj.Proxy = self

    def execute(self, obj):
        base = obj.BaseFeature
        if base is None:
            raise ValueError("Welded Corner: needs a sheet metal part")
        shape, kept = smedgegeom.corner_base(base)
        _more_props(obj)
        welds = welds_of(obj, shape)
        text = symbol_text(obj) if obj.AddWeldSymbol and welds else ""
        if obj.SymbolText != text:
            obj.SymbolText = text
        obj.WeldShape = Part.makeCompound(welds) if welds else Part.Shape()
        if not welds:
            obj.Shape = smedgegeom.corner_result(obj, shape, shape, kept)
            return
        out = shape.fuse(welds)
        out = out.removeSplitter()
        if obj.AddFillet and float(obj.FilletRadius) > 0:
            edges = [inside_edge(out, w) for w in welds]
            edges = [out.Edges[i - 1] for i in edges if i]
            if edges:
                try:
                    out = out.makeFillet(float(obj.FilletRadius), edges)
                except Exception:
                    raise ValueError("Welded Corner: the fillet radius does not fit the corner")
        obj.Shape = smedgegeom.corner_result(obj, shape, out, kept)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _more_props(obj):
    """The weld's own shape (for the texture) and the weld symbol."""
    for name, kind, tip in (("WeldShape", "Part::PropertyPartShape", "The welds alone (drawn with the texture)"),
                            ("SymbolData", "App::PropertyString", "The weld symbol (JSON, from Weld Symbol...)"),
                            ("SymbolText", "App::PropertyString", "The weld symbol, as shown in the 3D view")):
        if name not in obj.PropertiesList:
            obj.addProperty(kind, name, GROUP, tip)
            obj.setEditorMode(name, 2 if name != "SymbolText" else 1)


def _symbol_path(obj):
    """The weld symbol as Weld Bead keeps it (weweld.symbol_of takes it)."""
    try:
        stored = json.loads(obj.SymbolData) if obj.SymbolData else {}
    except ValueError:
        stored = {}
    if not stored:
        if obj.AddFillet:
            stored = {"arrow": {"symbol": "Fillet", "size": "%g" % float(obj.FilletRadius)}}
        else:
            stored = {"arrow": {"symbol": "Square Groove", "size": ""}}
    return {"size": float(obj.FilletRadius), "type": "Continuous", "symbol": stored}


def symbol_of(obj):
    from .weweld import symbol_of as of
    return of(_symbol_path(obj))


def symbol_text(obj):
    from .weweld import symbol_text as text
    return text(_symbol_path(obj))


def welds_of(obj, shape):
    """The weld solids of a Welded Corner on its base shape."""
    welds = []
    stop = obj.StopPoint if obj.HasStop else None
    for p in obj.CornerPoints:
        name = face_at(shape, p)
        if name is None:
            raise ValueError("Welded Corner: a picked face is gone; edit the feature and pick it again")
        welds.append(fill(shape, shape.getElement(name), stop, p))
    return welds


def is_welded_corner(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWWeldedCorner"


def without_welds(body, shape):
    """shape (the part's last feature) with the welds of the body's Welded Corners taken out, for the
    flat pattern."""
    welds = []
    for o in body.Group:
        if is_welded_corner(o) and o.BaseFeature is not None and "Invalid" not in o.State:
            try:
                # all the material the feature added: the welds and their fillet welds
                added = o.Shape.cut(o.BaseFeature.Shape)
                welds += added.Solids or welds_of(o, smedgegeom.trimmed_shape(o.BaseFeature))
            except Exception as _fw_err:
                _fw_log("smweldedcorner.py:245", _fw_err)
    if not welds:
        return shape
    return shape.cut(welds).removeSplitter()


TEXTURE_COLOR = (0.62, 0.55, 0.45)     # weld metal


def _ripples():
    """A small weld bead texture: rounded ripples across the bead."""
    from pivy import coin
    w, h = 16, 16
    data = bytearray()
    for y in range(h):
        for x in range(w):
            import math
            v = 0.5 + 0.5 * math.cos(2 * math.pi * (x + 0.35 * abs(y - h / 2)) / 8.0)
            g = int(120 + 110 * v)
            data += bytes((g, g, g))
    img = coin.SoSFImage()
    img.setValue(coin.SbVec2s(w, h), 3, bytes(data))
    return img


class ViewProviderWeldedCorner:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        self.texture = self.label = None
        try:
            from pivy import coin
            self.texture = coin.SoSeparator()
            offset = coin.SoPolygonOffset()
            offset.factor, offset.units = -1.0, -1.0
            mat = coin.SoMaterial()
            mat.diffuseColor = TEXTURE_COLOR
            tex = coin.SoTexture2()
            tex.image = _ripples()
            tex.model = coin.SoTexture2.MODULATE
            self.tex_coords = coin.SoTextureCoordinateDefault()
            self.tex_points = coin.SoCoordinate3()
            self.tex_faces = coin.SoIndexedFaceSet()
            for n in (offset, mat, tex, self.tex_coords, self.tex_points, self.tex_faces):
                self.texture.addChild(n)
            vobj.RootNode.addChild(self.texture)
            self.label = coin.SoSeparator()
            color = coin.SoBaseColor()
            color.rgb = (0.1, 0.2, 0.75)
            self.leader = coin.SoCoordinate3()
            lines = coin.SoLineSet()
            text_sep = coin.SoSeparator()
            self.label_at = coin.SoTranslation()
            font = coin.SoFont()
            font.size = 12
            self.text = coin.SoText2()
            for n in (self.label_at, font, self.text):
                text_sep.addChild(n)
            for n in (color, self.leader, lines, text_sep):
                self.label.addChild(n)
            vobj.RootNode.addChild(self.label)
            self._show(vobj.Object)
        except Exception:
            self.texture = self.label = None

    def updateData(self, obj, prop):
        if prop in ("Shape", "WeldShape", "SymbolText", "AddTexture"):
            self._show(obj)

    def _show(self, obj):
        """The weld texture (over the weld's faces) and the weld symbol (a leader up from the weld)."""
        if getattr(self, "texture", None) is None:
            return
        welds = getattr(obj, "WeldShape", None)
        has = welds is not None and not welds.isNull() and bool(welds.Solids)
        if has and obj.AddTexture:
            pts, tris = welds.tessellate(0.05)
            self.tex_points.point.setValues(0, len(pts), [tuple(p) for p in pts])
            index = []
            for t in tris:
                index += [t[0], t[1], t[2], -1]
            self.tex_faces.coordIndex.setValues(0, len(index), index)
        else:
            self.tex_faces.coordIndex.setNum(0)
            self.tex_points.point.setNum(0)
        text = getattr(obj, "SymbolText", "") or ""
        if not text or not has:
            self.text.string.setNum(0)
            self.leader.point.setNum(0)
            return
        start = welds.Solids[0].BoundBox.Center
        size = max(obj.Shape.BoundBox.DiagonalLength if not obj.Shape.isNull() else 0, 20.0)
        end = start + V(1, 1, 1).normalize() * size * 0.3
        self.leader.point.setValues(0, 2, [tuple(start), tuple(end)])
        self.label_at.translation = tuple(end)
        self.text.string.setValues(0, 1, [text])

    def texture_triangles(self):
        return self.tex_faces.coordIndex.getNum() // 4 if getattr(self, "texture", None) is not None else 0

    def symbol_shown(self):
        return [self.text.string[i] for i in range(self.text.string.getNum())] if getattr(self, "label", None) else []

    def getIcon(self):
        return _icon()

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        obj.Document.openTransaction("Edit " + obj.Label)
        try:
            Gui.Control.showDialog(Panel(obj, False))
        except BaseException:
            try:
                obj.Document.abortTransaction()
            except Exception:
                pass
            raise
        return True

    def unsetEdit(self, vobj, mode=0):
        return False

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make(body):
    doc = body.Document
    base = body.Tip
    obj = doc.addObject("PartDesign::FeaturePython", "WeldedCorner")
    SWWeldedCorner(obj)
    if App.GuiUp:
        ViewProviderWeldedCorner(obj.ViewObject)
    body.addObject(obj)
    obj.Label = naming.next_label(doc, "Welded Corner")
    if base is not None:
        try:
            base.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("smweldedcorner.py:388", _fw_err)
    return obj


# ================================================================ PropertyManager
class Panel:
    """The Welded Corner PropertyManager."""
    HINT = "Select a side face of the corner to weld."

    def __init__(self, obj, new):
        global _LAST
        _LAST = self
        self.obj = obj
        self.new = new
        box = _box("Corner to Weld")
        f = box.layout()
        self.corner = _list("SWSMWeldCorner", "#ffd6ec", "Corner to Weld: a side face of the corner", rows=2)
        f.addRow(self.corner)
        self.stop = _list("SWSMWeldStop", "#d6ecff", "Stopping Point (optional): where the weld stops")
        f.addRow(QtWidgets.QLabel("Stopping point (optional):"))
        f.addRow(self.stop)
        self.fillet = QtWidgets.QCheckBox("Add fillet")
        self.fillet.setObjectName("SWSMWeldFillet")
        f.addRow(self.fillet)
        self.radius = _spin("SWSMWeldFilletRadius", float(obj.FilletRadius), 0.0, 1000.0)
        self.radius.setToolTip("Fillet radius")
        f.addRow("Fillet radius:", self.radius)
        _more_props(obj)
        self.texture = QtWidgets.QCheckBox("Add texture")
        self.texture.setObjectName("SWSMWeldTexture")
        self.texture.setToolTip("Draws the weld with a weld bead texture")
        self.symbol = QtWidgets.QCheckBox("Add weld symbol")
        self.symbol.setObjectName("SWSMWeldSymbol")
        self.symbol.setToolTip("Shows a weld symbol on a leader from the weld")
        self.define = QtWidgets.QPushButton("Weld Symbol...")
        self.define.setObjectName("SWSMWeldSymbolDefine")
        self.define.setToolTip("Sets the weld symbol")
        for w in (self.texture, self.symbol, self.define):
            f.addRow(w)
        self.texture.setChecked(bool(obj.AddTexture))
        self.symbol.setChecked(bool(obj.AddWeldSymbol))
        self.define.setEnabled(bool(obj.AddWeldSymbol))
        self.symbol_dialog = None
        for w in (self.texture, self.symbol):
            w.toggled.connect(self._changed)
        self.define.clicked.connect(self.define_symbol)
        self.error = error_label()
        f.addRow(self.error)
        box.setProperty("swstyle_pm_title", TITLE)
        box.setProperty("swstyle_pm_icon", _icon())
        self.form = [box]
        self.fillet.setChecked(bool(obj.AddFillet))
        self.radius.setEnabled(bool(obj.AddFillet))
        self.fillet.toggled.connect(self._changed)
        self.radius.valueChanged.connect(self._changed)
        self.keys = _DeleteKey(self)
        for w in (self.corner, self.stop):
            w.installEventFilter(self.keys)
        self.active = self.corner
        self._mark()
        self._fill()
        self._report()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def set_active(self, w):
        if w in (self.corner, self.stop):
            self.active = w
            self._mark()

    def _mark(self):
        for w in (self.corner, self.stop):
            w.setProperty("swstyle_active", w is self.active)
            w.setFrameShape(QtWidgets.QFrame.Box if w is self.active else QtWidgets.QFrame.StyledPanel)

    def remove_current(self, w):
        row = w.currentRow()
        if row < 0:
            return
        if w is self.corner:
            names, points = list(self.obj.CornerToWeld), list(self.obj.CornerPoints)
            del names[row], points[row]
            self.obj.CornerToWeld, self.obj.CornerPoints = names, points
        else:
            self.obj.HasStop = False
            self.obj.StoppingPoint = ""
        self._apply()

    def _fill(self):
        self.corner.clear()
        for n in self.obj.CornerToWeld:
            self.corner.addItem(n)
        self.stop.clear()
        if self.obj.HasStop:
            self.stop.addItem(self.obj.StoppingPoint)

    # ---------------------------------------------------------------- picks
    def addSelection(self, doc, name, sub, point):
        if sub.startswith(("Face", "Edge", "Vertex")):
            at = App.Vector(*point) if point else None
            QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub, at))

    def _picked(self, doc_name, name, sub, at):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smweldedcorner.py:494", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None or picked.Shape.isNull():
            return
        element = picked.Shape.getElement(sub)
        if self.active is self.stop:
            if at is None:
                at = element.Vertexes[0].Point if sub.startswith(("Vertex", "Edge")) else inside_point(element)
            self.obj.StoppingPoint = sub
            self.obj.StopPoint = at
            self.obj.HasStop = True
            self.set_active(self.corner)
            self._apply()
            return
        if not sub.startswith("Face") or not _plane(element):
            self.error.setText(NOT_GAP)
            self.error.show()
            return
        if at is None:
            at = inside_point(element)
        base = smedgegeom.trimmed_shape(self.obj.BaseFeature)
        fname = face_at(base, at, face_normal(element))
        if fname is None:
            return
        p = at if base.getElement(fname).isInside(at, 1e-5, True) else inside_point(base.getElement(fname))
        names, points = list(self.obj.CornerToWeld), list(self.obj.CornerPoints)
        if fname in names:
            i = names.index(fname)
            del names[i], points[i]
        else:
            names.append(fname)
            points.append(p)
        self.obj.CornerToWeld, self.obj.CornerPoints = names, points
        self._apply()

    # ---------------------------------------------------------------- result
    def define_symbol(self):
        """Weld Symbol...: the Weld Symbol dialog Weld Bead uses."""
        from .weweld import WeldSymbolDialog
        dlg = WeldSymbolDialog(symbol_of(self.obj), Gui.getMainWindow())
        self.symbol_dialog = dlg
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.obj.SymbolData = json.dumps(dlg.value())
            self._changed()
        self.symbol_dialog = None

    def _changed(self, *_a):
        self.obj.AddTexture = self.texture.isChecked()
        self.obj.AddWeldSymbol = self.symbol.isChecked()
        self.define.setEnabled(self.symbol.isChecked())
        self.obj.AddFillet = self.fillet.isChecked()
        self.obj.FilletRadius = self.radius.value()
        self.radius.setEnabled(self.fillet.isChecked())
        self._apply()

    def _apply(self):
        self.obj.touch()
        self.obj.Document.recompute()
        self._fill()
        self._report()

    def _report(self):
        if "Invalid" in self.obj.State:
            self.error.setText(self.obj.getStatusString())
        elif not self.obj.CornerPoints:
            self.error.setText(self.HINT)
        else:
            self.error.setText("")
        self.error.setVisible(bool(self.error.text()))
        return not self.error.text()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smweldedcorner.py:572", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smweldedcorner.py:578", _fw_err)

    def accept(self):
        if not self._report():
            return False
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        base = self.obj.BaseFeature if self.new else None
        doc.abortTransaction()
        doc.recompute()
        if base is not None:
            try:
                base.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("smweldedcorner.py:596", _fw_err)
        self._close()
        return True


# ================================================================ command
def start():
    body = _sheet_body()
    if body is None:
        return
    picked = [(o.Document.Name, o.Object.Name, sub, App.Vector(p)) for o in Gui.Selection.getSelectionEx()
              for sub, p in zip(o.SubElementNames, o.PickedPoints) if sub.startswith("Face")]
    doc = body.Document
    doc.openTransaction(TITLE)
    try:
        obj = make(body)
        doc.recompute()
        panel = Panel(obj, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    for doc_name, name, sub, at in picked:
        panel._picked(doc_name, name, sub, at)


class Command:
    def GetResources(self):
        return {"Pixmap": _icon(), "MenuText": TITLE,
                "ToolTip": "Welds a closed corner: fills the gap between the flanges."}

    def IsActive(self):
        return _sheet_body() is not None

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
