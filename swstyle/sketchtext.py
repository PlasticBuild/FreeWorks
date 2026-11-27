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

import glob
import json
import math
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from . import paths
from .sketchextras import _Form, picked_geo_ids, sketch_in_edit, _tell

PROP = "SWTextBlocks"
FONT_PARAM = "SketchTextFont"
FONT_DIRS = (os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts"),
             "/usr/share/fonts", os.path.expanduser("~/.fonts"), "/Library/Fonts", "/System/Library/Fonts")
DEFAULT_FONTS = ("arial.ttf", "Arial.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf", "FreeSans.ttf",
                 "osifont-lgpl3fe.ttf")


# ------------------------------------------------------------------ fonts
def font_files():
    """Font files on this computer: {file name: path}."""
    out = {}
    for d in FONT_DIRS:
        if not os.path.isdir(d):
            continue
        for pattern in ("*.ttf", "*.otf", "*.TTF", "*.OTF"):
            for path in glob.glob(os.path.join(d, "**", pattern), recursive=True):
                out.setdefault(os.path.basename(path), path)
    techdraw = os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Resources", "fonts")
    for path in glob.glob(os.path.join(techdraw, "*.ttf")):
        out.setdefault(os.path.basename(path), path)
    return out


def default_font():
    saved = paths.params().GetString(FONT_PARAM, "")
    if saved and os.path.isfile(saved):
        return saved
    files = font_files()
    for name in DEFAULT_FONTS:
        if name in files:
            return files[name]
    return next(iter(files.values()), "")


# ------------------------------------------------------------------ the record on the sketch
def blocks(sketch):
    if PROP not in sketch.PropertiesList:
        return []
    out = []
    for item in sketch.getPropertyByName(PROP):
        try:
            out.append(json.loads(item))
        except ValueError as _fw_err:
            _fw_log("sketchtext.py:83", _fw_err)
    return out


def _save_blocks(sketch, items):
    if PROP not in sketch.PropertiesList:
        sketch.addProperty("App::PropertyStringList", PROP, "FreeCAD", "Sketch texts (Text tool)")
        sketch.setEditorMode(PROP, 2)
    setattr(sketch, PROP, [json.dumps(b, sort_keys=True) for b in items])


def _tag_index(sketch):
    return {g.Tag: i for i, g in enumerate(sketch.Geometry)}


def geo_ids(sketch, indices):
    """The sketch's saved geometry ids of indices. A geometry's Tag is new after save and reopen,
    its id is kept (and stays with it when earlier entities are deleted)."""
    try:
        return [sketch.getGeometryId(i) for i in indices]
    except Exception as _fw_err:
        _fw_log("sketchtext.py:geo_ids", _fw_err)
        return []


def _id_index(sketch):
    out = {}
    for i in range(len(sketch.Geometry)):
        try:
            out[sketch.getGeometryId(i)] = i
        except Exception:
            pass
    return out


def indices_of(sketch, tags, ids):
    """Geometry indices for a record's ids (or its tags, for records made before ids were kept)."""
    if ids:
        index = _id_index(sketch)
        return [index[g] for g in ids if g in index]
    index = _tag_index(sketch)
    return [index[t] for t in tags or [] if t in index]


def block_of(sketch, geo_id):
    """The text a geometry index belongs to, or None."""
    tag = sketch.Geometry[geo_id].Tag
    gid = (geo_ids(sketch, [geo_id]) or [None])[0]
    for b in blocks(sketch):
        if (gid in b["ids"]) if b.get("ids") else (tag in b["tags"]):
            return b
    return None


def block_ids(sketch, block):
    return sorted(indices_of(sketch, block.get("tags"), block.get("ids")))


# ------------------------------------------------------------------ outlines
def text_edges(text, font, height, spacing=0.0, angle=0.0, x=0.0, y=0.0):
    """The text's outline edges in sketch coordinates, as [[edges of one closed loop], ...]."""
    import Part
    if not text.strip() or not font or height <= 0:
        return []
    chars = Part.makeWireString(text, font, height, spacing)
    rot = App.Rotation(App.Vector(0, 0, 1), angle)
    pl = App.Placement(App.Vector(x, y, 0), rot)
    loops = []
    for char in chars:
        for wire in char:
            w = wire.copy()
            w.Placement = pl.multiply(w.Placement)
            loops.append([e for e in w.Edges if e.Length > 1e-9])
    return loops


def _sketch_curve(edge):
    import Part
    c = edge.Curve
    if isinstance(c, Part.Line):
        return Part.LineSegment(edge.Vertexes[0].Point, edge.Vertexes[-1].Point)
    try:
        if isinstance(c, Part.BSplineCurve):
            c = c.copy()
            if abs(edge.FirstParameter - c.FirstParameter) > 1e-12 or abs(edge.LastParameter - c.LastParameter) > 1e-12:
                c.segment(edge.FirstParameter, edge.LastParameter)
            return c
    except Exception as _fw_err:
        _fw_log("sketchtext.py:142", _fw_err)
    return edge.toNurbs().Edges[0].Curve


def place_text(sketch, text, font, height, spacing=0.0, angle=0.0, x=0.0, y=0.0, replace=None):
    """Adds a text to the sketch (replacing the text `replace`) and records it. Returns the
    new block."""
    import Sketcher
    items = blocks(sketch)
    if replace is not None:
        ids = block_ids(sketch, replace)
        if ids:
            sketch.delGeometries(ids)
        items = [b for b in items if b["tags"] != replace["tags"]]
    loops = text_edges(text, font, height, spacing, angle, x, y)
    curves = [_sketch_curve(e) for loop in loops for e in loop]
    first = len(sketch.Geometry)
    if curves:
        sketch.addGeometry(curves, False)
    ids = list(range(first, first + len(curves)))


    if ids:
        first_con = len(sketch.Constraints)
        sketch.addConstraint([Sketcher.Constraint("Block", i) for i in ids])
        try:
            sketch.setVirtualSpace(list(range(first_con, len(sketch.Constraints))), True)
        except Exception as _fw_err:
            _fw_log("sketchtext.py:170", _fw_err)
    tags = [sketch.Geometry[i].Tag for i in ids]
    block = {"text": text, "font": font, "height": height, "spacing": spacing, "angle": angle, "x": x, "y": y,
             "tags": tags, "ids": geo_ids(sketch, ids), "loops": [len(loop) for loop in loops]}
    items.append(block)
    _save_blocks(sketch, items)
    return block


def dissolve(sketch, block):
    """The text becomes plain entities: Block relations off, letters' pieces joined."""
    import Sketcher
    ids = block_ids(sketch, block)
    idset = set(ids)
    blocked = [k for k, c in enumerate(sketch.Constraints) if c.Type == "Block" and c.First in idset]
    for k in reversed(blocked):
        sketch.delConstraint(k)
    # join each loop's pieces end to end (ids are in the order they were added, loop by loop)
    cons, k = [], 0
    for n in block.get("loops", []):
        loop = ids[k:k + n]
        k += n
        for a, b in zip(loop, loop[1:] + loop[:1]):
            if a == b:
                continue
            # pieces of a font outline may run either way: join whichever ends meet
            for ea, eb in ((2, 1), (2, 2), (1, 1), (1, 2)):
                if (sketch.getPoint(a, ea) - sketch.getPoint(b, eb)).Length < 1e-6:
                    cons.append(Sketcher.Constraint("Coincident", a, ea, b, eb))
                    break
    if cons:
        sketch.addConstraint(cons)
    _save_blocks(sketch, [b for b in blocks(sketch) if b["tags"] != block["tags"]])


# ------------------------------------------------------------------ commands
class TextForm(_Form):
    def __init__(self, block=None, at=None):
        super().__init__("Sketch Text")
        b = block or {}
        self.text = self.add("text", "Text", QtWidgets.QLineEdit(b.get("text", "")))
        self.font = self.add("font", "Font", QtWidgets.QComboBox())
        self.font.setEditable(True)
        files = font_files()
        for name in sorted(files, key=str.lower):
            self.font.addItem(name, files[name])
        current = b.get("font") or default_font()
        i = self.font.findData(current)
        if i < 0:
            self.font.addItem(os.path.basename(current), current)
            i = self.font.count() - 1
        self.font.setCurrentIndex(i)
        browse = QtWidgets.QPushButton("Font file...")
        browse.clicked.connect(self._browse)
        self.form.addRow("", browse)
        self.height = self._num("height", "Height", b.get("height", 5.0), 0.01, " mm")
        self.spacing = self._num("spacing", "Spacing", b.get("spacing", 0.0), -1000, " mm")
        self.angle = self._num("angle", "Rotation", b.get("angle", 0.0), -360, " °")
        x, y = (at or (b.get("x", 0.0), b.get("y", 0.0)))
        self.x = self._num("x", "X", x, -1e6, " mm")
        self.y = self._num("y", "Y", y, -1e6, " mm")
        self.finish()

    def _num(self, key, label, value, low, suffix):
        box = QtWidgets.QDoubleSpinBox()
        box.setRange(low, 1e6)
        box.setDecimals(3)
        box.setSuffix(suffix)
        box.setValue(value)
        return self.add(key, label, box)

    def _browse(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Font file", "", "Fonts (*.ttf *.otf)")
        if path:
            self.font.addItem(os.path.basename(path), path)
            self.font.setCurrentIndex(self.font.count() - 1)

    def font_path(self):
        data = self.font.currentData()
        if data and self.font.currentText() == os.path.basename(data):
            return data
        typed = self.font.currentText()
        return typed if os.path.isfile(typed) else (data or "")

    def values(self):
        return dict(text=self.text.text(), font=self.font_path(), height=self.height.value(),
                    spacing=self.spacing.value(), angle=self.angle.value(), x=self.x.value(), y=self.y.value())


def _picked_point(sketch):
    """A picked sketch point or vertex, as where the text starts."""
    for sel in Gui.Selection.getSelectionEx():
        if sel.Object != sketch:
            continue
        for sub in sel.SubElementNames:
            if sub.startswith("Vertex"):
                try:
                    v = sketch.Shape.getElement(sub).Point
                    p = sketch.getGlobalPlacement().inverse().multVec(v)
                    return p.x, p.y
                except Exception as _fw_err:
                    _fw_log("sketchtext.py:271", _fw_err)
    return None


def _text_picks(sketch):
    ""

    out = list(picked_geo_ids(sketch))
    for sel in Gui.Selection.getSelectionEx():
        if sel.Object != sketch:
            continue
        for sub in sel.SubElementNames:
            if sub.startswith("Vertex"):
                try:
                    g, _pos = sketch.getGeoVertexIndex(int(sub[6:]) - 1)
                except Exception:
                    continue
                if 0 <= g and g not in out:
                    out.append(g)
    return out


def sketch_text():
    sketch = sketch_in_edit()
    if sketch is None:
        return None
    picked = [block_of(sketch, i) for i in _text_picks(sketch) if i < len(sketch.Geometry)]
    block = next((b for b in picked if b is not None), None)

    try:
        from . import sketchtextpm
        return sketchtextpm.open_page(sketch, block, None if block else _picked_point(sketch))
    except ImportError:
        pass
    form = TextForm(block, None if block else _picked_point(sketch))
    if not form.exec():
        return None
    v = form.values()
    if not v["font"] or not os.path.isfile(v["font"]):
        _tell("Sketch Text", "Pick a font file.")
        return None
    paths.params().SetString(FONT_PARAM, v["font"])
    doc = sketch.Document
    doc.openTransaction("Edit Sketch Text" if block else "Sketch Text")
    try:
        made = place_text(sketch, replace=block, **v)
        sketch.solve()
        doc.recompute()
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    Gui.Selection.clearSelection()
    return made


def dissolve_command():
    sketch = sketch_in_edit()
    if sketch is None:
        return 0
    picked = [block_of(sketch, i) for i in _text_picks(sketch) if i < len(sketch.Geometry)]
    todo = []
    for b in picked:
        if b is not None and b not in todo:
            todo.append(b)
    if not todo:
        from . import pickfirst
        return pickfirst.ask_in_sketch(sketch, "Dissolve Sketch Text", "Sketch Text", dissolve_command) or 0
    doc = sketch.Document
    doc.openTransaction("Dissolve Sketch Text")
    try:
        for b in todo:
            dissolve(sketch, b)
        sketch.solve()
        doc.recompute()
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return len(todo)


def _in_sketch():
    return sketch_in_edit() is not None


COMMANDS = {
    "SWStyle_SketchText": ("Text", "Sketches text whose outlines can be extruded; pick a text and click again to edit it.",
                           sketch_text),
    "SWStyle_DissolveSketchText": ("Dissolve Sketch Text", "Turns the selected sketch text into plain sketch entities.",
                                   dissolve_command),
}


class _Cmd:
    def __init__(self, name):
        self.name = name

    def GetResources(self):
        menu, tip, _ = COMMANDS[self.name]
        return {"MenuText": menu, "ToolTip": tip, "CmdType": "ForEdit"}

    def Activated(self):
        COMMANDS[self.name][2]()

    def IsActive(self):
        return _in_sketch()



# knot numbers or control polygon until asked (Show Curvature Combs, picking the spline); FreeCAD
# 1.1 shows them all. Set only where the user has not chosen.
SPLINE_INFO = ("BSplineCombVisible", "BSplineDegreeVisible", "BSplinePoleWeightVisible",
               "BSplineKnotMultiplicityVisible", "BSplineControlPolygonVisible")
SKETCHER_GENERAL = "User parameter:BaseApp/Preferences/Mod/Sketcher/General"


def quiet_splines():
    g = App.ParamGet(SKETCHER_GENERAL)
    have = set(g.GetBools())
    for key in SPLINE_INFO:
        if key not in have:
            g.SetBool(key, False)


_installed = False


def install():
    global _installed
    if _installed:
        return
    quiet_splines()
    for name in COMMANDS:
        if Gui.Command.get(name) is None:
            Gui.addCommand(name, _Cmd(name))
    _installed = True
