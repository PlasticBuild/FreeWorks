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
import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import drawings as D

BLOCK_EXT = "FreeCAD block (*.fwblock);;SVG (*.svg)"


# --------------------------------------------------------------------------- SVG helpers
def _num(s, default=0.0):
    m = re.match(r"\s*(-?[0-9.]+(?:e-?[0-9]+)?)\s*([a-z%]*)", s or "")
    if not m:
        return default
    v = float(m.group(1))
    unit = m.group(2)
    return {"in": v * 25.4, "cm": v * 10.0, "pt": v * 25.4 / 72.0, "px": v * 25.4 / 96.0}.get(unit, v)


def svg_parts(svg):
    """(width mm, height mm, viewBox (x, y, w, h), inner body) of an SVG string."""
    m = re.search(r"<svg\b([^>]*)>", svg or "", re.S)
    if not m:
        return 10.0, 10.0, (-5.0, -5.0, 10.0, 10.0), ""
    head = m.group(1)

    def attr(name):
        a = re.search(r'\b%s\s*=\s*"([^"]*)"' % name, head)
        return a.group(1) if a else None

    vb = attr("viewBox")
    w, h = _num(attr("width"), 0.0), _num(attr("height"), 0.0)
    if vb:
        box = tuple(float(x) for x in re.split(r"[\s,]+", vb.strip())[:4])
    else:
        box = (0.0, 0.0, w or 10.0, h or 10.0)
    if not w:
        w = box[2]
    if not h:
        h = box[3]
    end = svg.rfind("</svg>")
    body = svg[m.end():end if end > m.end() else len(svg)]
    return w, h, box, body


def symbol_box(o):
    """The symbol's half width and half height on the sheet (mm)."""
    w, h, _, _ = svg_parts(getattr(o, "Symbol", ""))
    s = float(getattr(o, "Scale", 1.0) or 1.0)
    return w * s / 2.0, h * s / 2.0


def symbols_of(page):
    return [o for o in page.Views if o.TypeId == "TechDraw::DrawViewSymbol"]


def symbol_at(page, p, exclude=()):
    """The symbol whose box holds sheet point p (the smallest one), else None."""
    best = None
    for o in symbols_of(page):
        if o in exclude:
            continue
        hw, hh = symbol_box(o)
        pad = 5.0 * float(getattr(o, "Scale", 1.0) or 1.0) if getattr(o, "SWAnnotation", "") else 0.0
        hw, hh = max(1.5, hw - pad), max(1.5, hh - pad)
        x, y = float(o.X), float(o.Y)
        if abs(p[0] - x) <= hw and abs(p[1] - y) <= hh:
            a = hw * hh
            if best is None or a < best[0]:
                best = (a, o)
    return best[1] if best else None


def _member_svg(m):
    """One member's body placed in block coordinates (mm, y down, insertion point at 0, 0)."""
    w, h, (bx, by, bw, bh), body = svg_parts(m["symbol"])
    sx = (w / bw) if bw else 1.0
    sy = (h / bh) if bh else 1.0
    s = float(m.get("scale", 1.0))
    return ('<g transform="translate(%g,%g) rotate(%g) scale(%g,%g) translate(%g,%g)">%s</g>'
            % (m["dx"], -m["dy"], -float(m.get("rotation", 0.0)), s * sx, s * sy, -(bx + bw / 2.0),
               -(by + bh / 2.0), body))


def block_svg(members):
    reach = 5.0
    for m in members:
        w, h, _, _ = svg_parts(m["symbol"])
        s = float(m.get("scale", 1.0))
        reach = max(reach, math.hypot(m["dx"], m["dy"]) + math.hypot(w, h) * s / 2.0)
    R = reach + 2.0
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="%g %g %g %g">%s</svg>'
            % (2 * R, 2 * R, -R, -R, 2 * R, 2 * R, "".join(_member_svg(m) for m in members)))


def _sw_props(o):
    out = {}
    for name in o.PropertiesList:
        if not name.startswith("SW") or name in ("SWBlockName", "SWBlockData", "SWBlockMember"):
            continue
        try:
            v = getattr(o, name)
            t = o.getTypeIdOfProperty(name)
            if isinstance(v, App.Vector):
                v = [v.x, v.y, v.z]
            json.dumps(v)
            out[name] = [t, v]
        except Exception as _fw_err:
            _fw_log("drawblocks.py:133", _fw_err)
    return out


def _set_props(o, props):
    for name, (t, v) in props.items():
        try:
            if name not in o.PropertiesList:
                o.addProperty(t, name, "FreeCAD", "")
            if t == "App::PropertyVector":
                v = App.Vector(*v)
            setattr(o, name, v)
        except Exception as _fw_err:
            _fw_log("drawblocks.py:146", _fw_err)


def member_of(o, at):
    return {"label": o.Label, "name": o.Name.rstrip("0123456789") or "Symbol", "symbol": o.Symbol,
            "dx": float(o.X) - at[0], "dy": float(o.Y) - at[1], "scale": float(getattr(o, "Scale", 1.0) or 1.0),
            "rotation": float(getattr(o, "Rotation", 0.0) or 0.0), "props": _sw_props(o)}


def blocks_in(doc):
    """{block name: definition members} of the blocks in doc."""
    out = {}
    for o in doc.Objects:
        if getattr(o, "SWAnnotation", "") == "Block" and getattr(o, "SWBlockName", ""):
            try:
                out.setdefault(o.SWBlockName, json.loads(o.SWBlockData))
            except Exception as _fw_err:
                _fw_log("drawblocks.py:163", _fw_err)
    return out


def next_block_name(doc):
    names = set(blocks_in(doc))
    n = 1
    while "Block%d" % n in names:
        n += 1
    return "Block%d" % n


def instances(doc, name):
    return [o for o in doc.Objects if getattr(o, "SWAnnotation", "") == "Block" and getattr(o, "SWBlockName", "") == name]


def place_block(page, name, members, at, scale=1.0, angle=0.0):
    """A block instance at sheet point at."""
    doc = page.Document
    s = doc.addObject("TechDraw::DrawViewSymbol", "Block")
    s.Symbol = block_svg(members)
    page.addView(s)
    s.X, s.Y = at
    s.Scale = scale
    s.Rotation = angle
    s.addProperty("App::PropertyString", "SWAnnotation", "FreeCAD", "Annotation kind")
    s.SWAnnotation = "Block"
    s.addProperty("App::PropertyString", "SWBlockName", "FreeCAD", "block definition name")
    s.SWBlockName = name
    s.addProperty("App::PropertyString", "SWBlockData", "FreeCAD", "block definition (members)")
    s.SWBlockData = json.dumps(members)
    s.Label = "%s-%d" % (name, len(instances(doc, name)))
    return s


def make_block(page, objs, at=None, name=None):
    """Make Block: objs (sheet symbols) become one block instance; at is the insertion point (default the
    middle of the objects)."""
    objs = [o for o in objs if o.TypeId == "TechDraw::DrawViewSymbol"]
    if not objs:
        return None
    if at is None:
        at = (sum(float(o.X) for o in objs) / len(objs), sum(float(o.Y) for o in objs) / len(objs))
    members = [member_of(o, at) for o in objs]
    name = name or next_block_name(page.Document)
    for o in objs:
        _remove(page, o)
    return place_block(page, name, members, at)


def _remove(page, o):
    try:
        page.removeView(o)
    except Exception as _fw_err:
        _fw_log("drawblocks.py:217", _fw_err)
    try:
        page.Document.removeObject(o.Name)
    except Exception as _fw_err:
        _fw_log("drawblocks.py:221", _fw_err)


def explode_block(page, inst):
    """Explode: the block instance is replaced by its members, in place."""
    members = json.loads(inst.SWBlockData)
    bx, by = float(inst.X), float(inst.Y)
    s = float(inst.Scale or 1.0)
    a = math.radians(float(inst.Rotation or 0.0))
    ca, sa = math.cos(a), math.sin(a)
    out = []
    doc = page.Document
    for m in members:
        o = doc.addObject("TechDraw::DrawViewSymbol", m.get("name", "Symbol"))
        o.Symbol = m["symbol"]
        page.addView(o)
        o.X = bx + s * (m["dx"] * ca - m["dy"] * sa)
        o.Y = by + s * (m["dx"] * sa + m["dy"] * ca)
        o.Scale = float(m.get("scale", 1.0)) * s
        o.Rotation = float(m.get("rotation", 0.0)) + float(inst.Rotation or 0.0)
        o.Label = m.get("label", o.Name)
        _set_props(o, m.get("props", {}))
        out.append(o)
    _remove(page, inst)
    return out


def redefine(doc, name, members):
    """Every instance of block name draws the new members."""
    svg = block_svg(members)
    data = json.dumps(members)
    for o in instances(doc, name):
        o.Symbol = svg
        o.SWBlockData = data


def link_file(inst, path):
    """Insert Block > Link to file: the instance follows the block file (made again when the file changes)."""
    import os
    for prop, kind, doc in (("SWBlockFile", "App::PropertyString", "the block file it is linked to"),
                            ("SWBlockStamp", "App::PropertyFloat", "the block file's time when last read")):
        if prop not in inst.PropertiesList:
            inst.addProperty(kind, prop, "FreeCAD", doc)
    inst.SWBlockFile = path
    inst.SWBlockStamp = os.path.getmtime(path) if os.path.isfile(path) else 0.0


def update_linked(doc):
    """Blocks linked to a file that changed since it was read: every instance of them draws the file's block.
    Returns the block names updated."""
    import os
    done = []
    for o in list(doc.Objects):
        path = getattr(o, "SWBlockFile", "")
        if not path or not os.path.isfile(path) or o.SWBlockName in done:
            continue
        t = os.path.getmtime(path)
        if abs(t - float(getattr(o, "SWBlockStamp", 0.0))) < 1e-6:
            continue
        try:
            _name, members = load_block(path)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: linked block %s: %s\n" % (path, error))
            continue
        redefine(doc, o.SWBlockName, members)
        for i in instances(doc, o.SWBlockName):
            if getattr(i, "SWBlockFile", "") == path:
                i.SWBlockStamp = t
        done.append(o.SWBlockName)
    if done:
        doc.recompute()
    return done


def _restored(doc):
    try:
        name = doc.Name
    except Exception:
        return
    QtCore.QTimer.singleShot(200, lambda: _update_later(name))


def _update_later(name):
    try:
        update_linked(App.getDocument(name))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: linked blocks: %s\n" % error)


def save_block(inst, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"FreeWorksBlock": 1, "name": inst.SWBlockName, "members": json.loads(inst.SWBlockData)}, f)
    return path


def load_block(path):
    """(name, members) from a .fwblock file, or a plain SVG file as a one-member block."""
    import os
    with open(path, encoding="utf-8") as f:
        text = f.read()
    name = os.path.splitext(os.path.basename(path))[0]
    if text.lstrip().startswith("{"):
        data = json.loads(text)
        return data.get("name", name), data["members"]
    return name, [{"label": name, "name": "Symbol", "symbol": text, "dx": 0.0, "dy": 0.0, "scale": 1.0,
                   "rotation": 0.0, "props": {}}]


def picked_symbols(page):
    return [o for o in Gui.Selection.getSelection() if o.TypeId == "TechDraw::DrawViewSymbol" and o in page.Views]


def picked_block(page):
    return next((o for o in picked_symbols(page) if getattr(o, "SWAnnotation", "") == "Block"), None)


# --------------------------------------------------------------------------- note text (Edit Block, Spell Checker)
def set_note_text(o, text):
    ""
    old = getattr(o, "SWText", None)
    if old is None or old == text:
        return False
    fmt = (getattr(o, "SWNoteFormat", "") or "").split("|")
    if getattr(o, "SWAnnotation", "") == "Note" and len(fmt) == 4:
        from . import drawannot as DA
        tip = None
        t = getattr(o, "SWTip", None)
        if t is not None and t.z >= 0:
            tip = (t.x, t.y)
        body, reach = DA.note_svg(text, (float(o.X), float(o.Y)), tip, align=fmt[0], angle=float(fmt[1]),
                                  size=float(fmt[2]), border=fmt[3])
        R = max(5.0, reach + 5.0)
        o.Symbol = ('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="%g %g %g %g">%s</svg>'
                    % (2 * R, 2 * R, -R, -R, 2 * R, 2 * R, body))
    else:
        o.Symbol = o.Symbol.replace(_xml(old), _xml(text))
    o.SWText = text
    return True


def _xml(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------------- PropertyManagers
class MakeBlockPanel(D._Panel):
    """Make Block: Block Entities (picked first, or clicked), Insertion Point (a click on empty sheet)."""
    TITLE = "Make Block"
    PIXMAP = "TechDraw_Symbol"

    def build(self):
        self.say("Select the sketch entities and annotations for the block. Click on empty sheet to set the "
                 "insertion point, then OK.")
        box, lay = D._group("Block Entities", self.form)
        self.list = QtWidgets.QListWidget(box)
        self.list.setObjectName("SWBlockEntities")
        self.list.setMaximumHeight(110)
        lay.addWidget(self.list)
        self.lay.addWidget(box)
        box, lay = D._group("Insertion Point", self.form)
        self.at_label = QtWidgets.QLabel("Middle of the entities", box)
        self.at_label.setObjectName("SWBlockInsertionPoint")
        lay.addWidget(self.at_label)
        self.lay.addWidget(box)
        self.members = []
        self.at = None
        for o in picked_symbols(self.page):
            if getattr(o, "SWAnnotation", "") != "Block":
                self.add(o)

    def add(self, o):
        if o in self.members:
            self.members.remove(o)
        else:
            self.members.append(o)
        self.list.clear()
        for m in self.members:
            self.list.addItem(m.Label)

    def sheet_click(self, p):
        o = symbol_at(self.page, p)
        if o is not None and getattr(o, "SWAnnotation", "") != "Block":
            self.add(o)
        else:
            self.at = p
            self.at_label.setText("X %.2f mm, Y %.2f mm" % p)
        return True

    def finish(self):
        if self.members:
            self.made = [make_block(self.page, self.members, self.at)]


class InsertBlockPanel(D._Panel):
    """Insert Block: Blocks to Insert (this drawing's blocks, Browse...), Parameters (Scale, Angle); each
    click on the sheet places one."""
    TITLE = "Insert Block"
    PIXMAP = "TechDraw_Symbol"

    def build(self):
        self.say("Select a block, or Browse... for a block file, then click on the sheet to place it.")
        box, lay = D._group("Blocks to Insert", self.form)
        self.list = QtWidgets.QListWidget(box)
        self.list.setObjectName("SWBlockList")
        self.list.setMaximumHeight(110)
        lay.addWidget(self.list)
        self.browse = QtWidgets.QPushButton("Browse...", box)
        self.browse.setObjectName("SWBlockBrowse")
        self.browse.clicked.connect(self.browse_file)
        lay.addWidget(self.browse)
        self.link = QtWidgets.QCheckBox("Link to file", box)
        self.link.setObjectName("SWBlockLink")
        self.link.setToolTip("The placed block follows its file: it updates when the file changes.")
        self.link.setVisible(False)                  # shown for a block from a file (never greyed)
        lay.addWidget(self.link)
        self.files = {}
        self.lay.addWidget(box)
        box, lay = D._group("Parameters", self.form)
        grid = QtWidgets.QFormLayout()
        self.scale = QtWidgets.QDoubleSpinBox(box)
        self.scale.setObjectName("SWBlockScale")
        self.scale.setRange(0.01, 100.0)
        self.scale.setDecimals(3)
        self.scale.setValue(1.0)
        self.angle = QtWidgets.QDoubleSpinBox(box)
        self.angle.setObjectName("SWBlockAngle")
        self.angle.setRange(-360.0, 360.0)
        self.angle.setSuffix(" deg")
        grid.addRow("Scale", self.scale)
        grid.addRow("Angle", self.angle)
        lay.addLayout(grid)
        self.lay.addWidget(box)
        self.defs = dict(blocks_in(self.doc))
        self.list.currentItemChanged.connect(lambda it, _old: self.link.setVisible(
            it is not None and it.text() in self.files))
        for name in sorted(self.defs):
            self.list.addItem(name)
        if self.list.count():
            self.list.setCurrentRow(0)

    def add_file(self, path):
        name, members = load_block(path)
        base, n = name, 1
        while name in self.defs and self.defs[name] != members:
            n += 1
            name = "%s-%d" % (base, n)
        self.defs[name] = members
        self.files[name] = path
        if not self.list.findItems(name, QtCore.Qt.MatchExactly):
            self.list.addItem(name)
        found = self.list.findItems(name, QtCore.Qt.MatchExactly)
        self.list.setCurrentItem(found[0] if found else self.list.item(self.list.count() - 1))
        self.link.setEnabled(True)               # a block from a file can be linked to it
        return name

    def browse_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Insert Block", "", BLOCK_EXT)
        if path:
            self.add_file(path)

    def sheet_click(self, p):
        it = self.list.currentItem()
        if it is None:
            self.say("Select a block first.")
            return True
        name = it.text()
        inst = place_block(self.page, name, self.defs[name], p, self.scale.value(), self.angle.value())
        if self.link.isChecked() and name in self.files:
            link_file(inst, self.files[name])
        self.made.append(inst)
        self.doc.recompute()
        self.say("Block placed. Click to place another, or OK.")
        return True


class EditBlockPanel(D._Panel):
    """Edit Block: the block's entities come apart for editing (move them, change a note's text, click to add
    or remove entities); OK rebuilds the block and every instance of it."""
    TITLE = "Edit Block"
    PIXMAP = "TechDraw_Symbol"

    def __init__(self, page, inst):
        self.inst = inst
        super().__init__(page)          # opens the PM's transaction: Cancel puts the block back
        self.members = explode_block(self.page, inst)
        self.doc.recompute()
        self.fill()

    def build(self):
        inst = self.inst
        self.name = inst.SWBlockName
        self.at = (float(inst.X), float(inst.Y))
        self.scale_angle = (float(inst.Scale or 1.0), float(inst.Rotation or 0.0))
        self.say("Editing %s. Drag the entities, change a note's text, or click entities to add or remove "
                 "them; OK to finish." % self.name)
        box, lay = D._group("Block Entities", self.form)
        self.list = QtWidgets.QListWidget(box)
        self.list.setObjectName("SWBlockEntities")
        self.list.setMaximumHeight(110)
        self.list.currentRowChanged.connect(self.show_text)
        lay.addWidget(self.list)
        self.text = QtWidgets.QLineEdit(box)
        self.text.setObjectName("SWBlockEntityText")
        self.text.setVisible(False)                  # shown for a text entity (never greyed)
        self.text.editingFinished.connect(self.apply_text)
        self.text_label = QtWidgets.QLabel("Text:", box)
        self.text_label.setVisible(False)
        lay.addWidget(self.text_label)
        lay.addWidget(self.text)
        self.lay.addWidget(box)
        self.members = []

    def fill(self):
        self.list.clear()
        for m in self.members:
            self.list.addItem(m.Label)

    def show_text(self, row):
        o = self.members[row] if 0 <= row < len(self.members) else None
        t = getattr(o, "SWText", None) if o is not None else None
        self.text.setVisible(t is not None)
        self.text_label.setVisible(t is not None)
        self.text.setText((t or "").replace("\n", " / "))

    def apply_text(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.members):
            o = self.members[row]
            if set_note_text(o, self.text.text().replace(" / ", "\n")):
                self.doc.recompute()

    def sheet_click(self, p):
        o = symbol_at(self.page, p)
        if o is None or getattr(o, "SWAnnotation", "") == "Block":
            return False
        if o in self.members:
            self.members.remove(o)
        else:
            self.members.append(o)
        self.fill()
        return False            # let TechDraw drag it too

    def finish(self):
        self.apply_text()
        if not self.members:
            return
        s, a = self.scale_angle
        ca, sa = math.cos(math.radians(-a)), math.sin(math.radians(-a))
        members = []
        for o in self.members:
            dx, dy = (float(o.X) - self.at[0]) / s, (float(o.Y) - self.at[1]) / s
            m = member_of(o, (0.0, 0.0))
            m["dx"], m["dy"] = dx * ca - dy * sa, dx * sa + dy * ca
            m["scale"] = float(getattr(o, "Scale", 1.0) or 1.0) / s
            m["rotation"] = float(getattr(o, "Rotation", 0.0) or 0.0) - a
            members.append(m)
        for o in list(self.members):
            _remove(self.page, o)
        inst = place_block(self.page, self.name, members, self.at, s, a)
        redefine(self.doc, self.name, members)
        self.made = [inst]


# --------------------------------------------------------------------------- commands
COMMANDS = {
    "FreeWorks_DrawMakeBlock": ("Make Block", "TechDraw_Symbol",
                                "Makes a block from the selected sketch entities and annotations."),
    "FreeWorks_DrawInsertBlock": ("Insert Block", "TechDraw_Symbol", "Inserts a block or a block file."),
    "FreeWorks_DrawEditBlock": ("Edit Block", "TechDraw_Symbol", "Edits the selected block."),
    "FreeWorks_DrawExplodeBlock": ("Explode Block", "TechDraw_Symbol",
                                   "Breaks the selected block back into its entities."),
    "FreeWorks_DrawSaveBlock": ("Save Block", "TechDraw_Symbol", "Saves the selected block to a block file."),
    "FreeWorks_DrawBlockAddRemove": ("Add/Remove Entities", "TechDraw_Symbol",
                                     "Adds sheet entities to the selected block, or takes them out of it."),
    "FreeWorks_DrawRebuildBlock": ("Rebuild Block", "TechDraw_Symbol",
                                   "Draws every instance of the drawing's blocks again from their definitions."),
}


class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.pixmap, self.tip = COMMANDS[name]

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": D.pixmap(self.pixmap)}

    def IsActive(self):
        page = D.active_page()
        if page is None or D.busy() or not D.sheet_shown(page):
            return False
        if self.name == "FreeWorks_DrawBlockAddRemove":
            return _editing() is not None or picked_block(page) is not None
        if self.name == "FreeWorks_DrawRebuildBlock":
            return bool(blocks_in(page.Document))
        if self.name in ("FreeWorks_DrawEditBlock", "FreeWorks_DrawExplodeBlock", "FreeWorks_DrawSaveBlock"):
            return picked_block(page) is not None
        return True

    def Activated(self):
        page = D.active_page()
        if page is None:
            return
        doc = page.Document
        if self.name == "FreeWorks_DrawMakeBlock":
            D._show(MakeBlockPanel(page))
        elif self.name == "FreeWorks_DrawInsertBlock":
            D._show(InsertBlockPanel(page))
        elif self.name == "FreeWorks_DrawEditBlock":
            inst = picked_block(page)
            if inst is not None:
                Gui.Selection.clearSelection()
                D._show(EditBlockPanel(page, inst))
        elif self.name == "FreeWorks_DrawExplodeBlock":
            inst = picked_block(page)
            if inst is not None:
                Gui.Selection.clearSelection()
                doc.openTransaction("Explode Block")
                try:
                    explode_block(page, inst)
                except BaseException:
                    try:
                        doc.abortTransaction()
                    except Exception:
                        pass
                    raise
                doc.commitTransaction()
                doc.recompute()
        elif self.name == "FreeWorks_DrawBlockAddRemove":

            # PM does that, so from outside it the picked block is opened for it
            panel = _editing()
            if panel is not None:
                panel.say("Add/Remove Entities: click entities on the sheet to add them to %s or take them out; "
                          "OK to finish." % panel.name)
                return
            inst = picked_block(page)
            if inst is not None:
                Gui.Selection.clearSelection()
                D._show(EditBlockPanel(page, inst))
                p = _editing()
                if p is not None:
                    p.say("Add/Remove Entities: click entities on the sheet to add them to %s or take them out; "
                          "OK to finish." % p.name)
        elif self.name == "FreeWorks_DrawRebuildBlock":
            doc.openTransaction("Rebuild Block")
            try:
                for name, members in blocks_in(doc).items():
                    redefine(doc, name, members)
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
            doc.recompute()
        elif self.name == "FreeWorks_DrawSaveBlock":
            inst = picked_block(page)
            if inst is not None:
                path, _ = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save Block",
                                                                inst.SWBlockName + ".fwblock",
                                                                "FreeCAD block (*.fwblock)")
                if path:
                    save_block(inst, path)


def _editing():
    """The Edit Block PM when it is open."""
    for p in list(getattr(D, "SHOWN", []) or []):
        if isinstance(p, EditBlockPanel):
            return p
    return None


_HOOKED = []


def register():
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
    if not _HOOKED:
        _HOOKED.append(True)
        try:
            from . import restorehook          # a drawing opened: its linked blocks read their files again
            restorehook.on_restored(_restored)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: linked blocks on open: %s\n" % error)
