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

import FreeCAD as App
import FreeCADGui as Gui
import Part

from . import naming
from . import smlive

COMMAND = "SWStyle_SMTabAndSlot"
TITLE = "Tab and Slot"
GROUP = "Tab and Slot"
ICON = "SheetMetal_ExtendBySketch"
V = App.Vector
MESSAGE = ("Select an edge for the tabs and a corresponding face for the slots. In sheet metal parts, the tab "
           "face is automatically selected after you select the edge.")
HEIGHTS = ["Up To Surface", "Blind", "Offset From Surface"]
EDGES = ["Sharp", "Fillet", "Chamfer"]
CORNERS = ["Sharp", "Fillet", "Chamfer", "Circular"]


DEFAULTS = {
    "UseOffset": False, "StartOffset": 0.0, "EndOffset": 0.0,
    "EqualSpacing": True, "Count": 5, "Spacing": 20.0, "CenterAlign": False,
    "Length": 5.0, "Thickness": 1.0, "Height": "Up To Surface", "HeightValue": 1.0,
    "EdgeType": "Sharp", "EdgeSize": 0.5,
    "NoThroughCut": False, "NormalCut": True, "LengthOffset": 0.1, "WidthOffset": 0.1, "EqualOffset": False,
    "CornerType": "Sharp", "CornerSize": 0.5, "Propagate": False,
}
SELECTIONS = ("Edge", "Start", "End", "SlotFace", "TabFace")


def new_group():
    g = dict(DEFAULTS)
    for key in SELECTIONS:
        g[key] = None           # [object name, sub-element, [points...]]
    g["Skip"] = []              # Instances to Skip (1-based), per group
    return g


# ================================================================ geometry
def _line_of(edge):
    a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
    return a, b


def _thickness(shape, p, direction):
    """How far the solid runs from p (on its face) along direction."""
    line = Part.makeLine(p - direction * 1e-3, p + direction * 1000)
    best = 0.0
    for e in shape.common(line).Edges:
        a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
        if min((a - p).Length, (b - p).Length) < 1e-2:
            best = max(best, e.Length)
    return best


def _through(shape, p, direction):
    """Where the line from p along direction last leaves the solid it first enters (distance from p)."""
    line = Part.makeLine(p, p + direction * 10000)
    spans = []
    for e in shape.common(line).Edges:
        ts = sorted((v.Point - p).dot(direction) for v in e.Vertexes)
        spans.append((ts[0], ts[-1]))
    if not spans:
        return None
    spans.sort()
    return spans[0]


def tab_face(shape, edge, slot_normal=None):
    """The face of shape on edge that the tabs lie in: not the one against the slot face (sheet metal: the
    sheet's broad face)."""
    faces = [f for f in shape.Faces if f.Surface.TypeId == "Part::GeomPlane"
             and any(edge.isSame(e) or _same_line(edge, e) for e in f.Edges)]
    if slot_normal is not None:
        faces = [f for f in faces if abs(abs(f.normalAt(0, 0).dot(slot_normal)) - 1) > 1e-6] or faces
    if not faces:
        return None
    return max(faces, key=lambda f: f.Area)


def _same_line(a, b):
    if a.Curve.TypeId != "Part::GeomLine" or b.Curve.TypeId != "Part::GeomLine":
        return False
    pa, pb = _line_of(a), _line_of(b)
    return ((pa[0] - pb[0]).Length < 1e-6 and (pa[1] - pb[1]).Length < 1e-6) or \
        ((pa[0] - pb[1]).Length < 1e-6 and (pa[1] - pb[0]).Length < 1e-6)


def _rect(origin, u, v, a, b):
    return [origin, origin + u * a, origin + u * a + v * b, origin + v * b]


def _slot_profile(corner, u, v, a, b, kind, size, normal):
    """The slot's outline: an a x b rectangle at corner along u, v with the corner type."""
    pts = _rect(corner, u, v, a, b)
    size = max(0.0, min(size, a / 2 - 1e-3, b / 2 - 1e-3)) if kind != "Circular" else max(0.0, size)
    if kind == "Fillet" and size > 1e-6:
        inner = _rect(corner + u * size + v * size, u, v, a - 2 * size, b - 2 * size)
        return Part.Face(Part.makePolygon(inner + inner[:1])).makeOffset2D(size, 0)
    if kind == "Chamfer" and size > 1e-6:
        c = []
        for k in range(4):
            p, prev, nxt = pts[k], pts[k - 1], pts[(k + 1) % 4]
            c += [p + (prev - p).normalize() * size, p + (nxt - p).normalize() * size]
        return Part.Face(Part.makePolygon(c + c[:1]))
    face = Part.Face(Part.makePolygon(pts + pts[:1]))
    if kind == "Circular" and size > 1e-6:
        holes = [Part.Face(Part.Wire(Part.makeCircle(size, p, normal))) for p in pts]
        face = face.fuse(holes).removeSplitter()
        face = face.Faces[0] if len(face.Faces) == 1 else face
    return face


class Layout:
    """One group's tabs worked out on the parts: their positions along the edge and their frame."""

    def __init__(self, tab_shape, slot_shape, edge, slot_face, tface, g, start=None, end=None):
        a, b = _line_of(edge)
        t = b - a
        if t.Length < 1e-9:
            raise ValueError("The tab edge must be a straight edge.")
        t.normalize()
        s0, s1 = 0.0, (b - a).Length
        if start is not None:
            s0 = max(s0, min(s1, (start - a).dot(t)))
        if end is not None:
            s1 = min(s1, max(s0, (end - a).dot(t)))
        if g["UseOffset"]:
            s0 += g["StartOffset"]
            s1 -= g["EndOffset"]
        if s1 - s0 < 1e-6:
            raise ValueError("The offsets leave no room for tabs on the edge.")
        nt = tface.normalAt(0, 0)
        # the tabs grow out of the part, away from the tab face's middle
        d = nt.cross(t)
        if (tface.CenterOfMass - a).dot(d) > 0:
            d = -d
        ns = slot_face.normalAt(0, 0)
        self.ps = slot_face.Vertexes[0].Point
        self.a, self.t, self.d, self.nt, self.ns = a, t, d, nt, ns
        self.thick = g["Thickness"]
        self.length = g["Length"]
        span = s1 - s0
        if self.length <= 0 or self.length > span + 1e-9:
            raise ValueError("The tabs are longer than the room on the edge.")
        if g["EqualSpacing"]:
            n = int(g["Count"])
            if n < 1:
                raise ValueError("There must be at least one tab.")
            gap = (span - n * self.length) / (n + 1)
            if gap < -1e-9:
                raise ValueError("%d tabs of %.2f mm do not fit on the edge." % (n, self.length))
            starts = [s0 + gap + k * (self.length + gap) for k in range(n)]
        else:
            pitch = g["Spacing"]
            if pitch < self.length:
                raise ValueError("The spacing must be at least the tab length.")
            n = int((span - self.length) // pitch) + 1
            used = (n - 1) * pitch + self.length
            first = s0 + (span - used) / 2 if g.get("CenterAlign", True) else s0
            starts = [first + k * pitch for k in range(n)]
        self.total = len(starts)
        skip = set(int(k) for k in g.get("Skip") or [])
        self.starts = [x for k, x in enumerate(starts, 1) if k not in skip]
        if not self.starts:
            raise ValueError("All the tabs are skipped.")
        # how far the tabs go: up to the far side of the slot part (or blind)
        mid = a + t * ((s0 + s1) / 2) - nt * (self.thick / 2)
        hit = _through(slot_shape, mid, d)
        if g["Height"] == "Blind":
            self.height = g["HeightValue"]
        else:
            if hit is None:
                raise ValueError("The tabs do not reach the slot face's part.")
            self.height = hit[1] + (g["HeightValue"] if g["Height"] == "Offset From Surface" else 0.0)
        if self.height <= 0:
            raise ValueError("The tab height must be more than 0.")
        self.enter = hit[0] if hit is not None else 0.0

    def tabs(self, g):
        out = []
        for s in self.starts:
            o = self.a + self.t * s
            box = Part.Face(Part.makePolygon(_rect(o, self.t, -self.nt, self.length, self.thick) + [o]))
            solid = box.extrude(self.d * self.height)
            size = g["EdgeSize"]
            if g["EdgeType"] != "Sharp" and size > 1e-6:
                far = [e for e in solid.Edges if e.Curve.TypeId == "Part::GeomLine"
                       and abs(abs(_dir(e).dot(self.nt)) - 1) < 1e-6
                       and abs((e.CenterOfMass - o).dot(self.d) - self.height) < 1e-6]
                size = min(size, self.length / 2 - 1e-3, self.height - 1e-3)
                if far and size > 1e-6:
                    solid = solid.makeFillet(size, far) if g["EdgeType"] == "Fillet" else solid.makeChamfer(size, far)
            out.append(solid)
        return out

    def slots(self, g, slot_shape, margin=0.5):
        lo = g["LengthOffset"]
        wo = lo if g["EqualOffset"] else g["WidthOffset"]
        out = []
        for s in self.starts:
            o = self.a + self.t * (s - lo) + self.nt * wo
            if g["NormalCut"]:
                u = V(self.t)
                v = (self.ns.cross(u)).normalize()
                if v.dot(-self.nt) < 0:
                    v = -v
                axis = -self.ns                 # into the slot part
                o = o - self.ns * (o - self.ps).dot(self.ns)
            else:
                u, v, axis = V(self.t), -self.nt, V(self.d)
                o = o + self.d * self.enter
            wide = self.thick + 2 * wo
            face = _slot_profile(o, u, v, self.length + 2 * lo, wide, g["CornerType"], g["CornerSize"], axis)
            middle = o + u * (self.length / 2 + lo) + v * (wide / 2)
            if g["NoThroughCut"]:
                depth = max(1e-3, (self.height - self.enter) / max(1e-6, abs(axis.dot(self.d))))
            else:
                depth = _thickness(slot_shape, middle, axis)
                if depth <= 0:
                    depth = _thickness(slot_shape, middle + axis * 1e-2, axis) + 1e-2
                depth += margin
            face.translate(axis * -margin)
            out.append(face.extrude(axis * (depth + margin)))
        return out


def _dir(e):
    a, b = _line_of(e)
    return (b - a).normalize()


# ================================================================ parts
def _body_of(obj):
    return next((p for p in obj.InList if p.TypeId == "PartDesign::Body"), None)


def _global(obj):
    """obj's shape in the document's coordinates."""
    from .smnormalcut import baked
    s = baked(obj.Shape)
    body = _body_of(obj)
    if body is not None and not body.Placement.isIdentity():
        s.transformShape(body.Placement.toMatrix(), True)
    return s


def _to_local(shape, body):
    if body is not None and not body.Placement.isIdentity():
        shape = shape.copy()
        shape.transformShape(body.Placement.inverse().toMatrix(), True)
    return shape


def _find_edge(shape, pts):
    a, b = V(*pts[0]), V(*pts[1])
    for e in shape.Edges:
        if e.Curve.TypeId != "Part::GeomLine":
            continue
        p, q = _line_of(e)
        if ((p - a).Length < 1e-5 and (q - b).Length < 1e-5) or ((p - b).Length < 1e-5 and (q - a).Length < 1e-5):
            return e
    # the edge may have been split since: the line through a and b, as far as the shape's edges go along it
    return Part.makeLine(a, b)


def _find_face(shape, pts):
    p, n = V(*pts[0]), V(*pts[1])
    vp = Part.Vertex(p)
    best = None
    for f in shape.Faces:
        if f.Surface.TypeId != "Part::GeomPlane" or abs(abs(f.normalAt(0, 0).dot(n)) - 1) > 1e-7:
            continue
        dist = f.distToShape(vp)[0]
        if dist < 1e-4 and (best is None or dist < best[0]):
            best = (dist, f)
    return best[1] if best else None


def _obj(doc, sel):
    return doc.getObject(sel[0]) if sel else None


def layouts(doc, groups, linked):
    """[(group, Layout, tab object, slot object)] for the groups that have their edge and slot face."""
    out = []
    first = groups[0] if groups else None
    for g in groups:
        if not g.get("Edge") or not g.get("SlotFace"):
            continue
        values = dict(g)
        if linked and first is not None:
            values.update({k: first[k] for k in DEFAULTS})
        tab_obj, slot_obj = _obj(doc, g["Edge"]), _obj(doc, g["SlotFace"])
        if tab_obj is None or slot_obj is None:
            raise ValueError("A part picked for the tabs or slots is no longer there.")
        tab_shape, slot_shape = _global(tab_obj), _global(slot_obj)
        edge = _find_edge(tab_shape, g["Edge"][2])
        sface = _find_face(slot_shape, g["SlotFace"][2])
        if sface is None:
            raise ValueError("The slot face is no longer there.")
        if g.get("TabFace"):
            tface = _find_face(tab_shape, g["TabFace"][2])
        else:
            tface = tab_face(tab_shape, edge, sface.normalAt(0, 0))
        if tface is None:
            raise ValueError("No tab face on the edge: pick the tab face.")
        start = V(*g["Start"][2][0]) if g.get("Start") else None
        end = V(*g["End"][2][0]) if g.get("End") else None
        out.append((values, Layout(tab_shape, slot_shape, edge, sface, tface, values, start, end), tab_obj, slot_obj))
    return out


# ================================================================ features
_LAST = None        # the open Tab and Slot PropertyManager


class SWTabAndSlot:
    """The tabs (in the tab part's body); the slots in the same body when the slot face is on it too."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyString", "Groups", GROUP, "The groups and their settings (JSON)")
        obj.addProperty("App::PropertyBool", "LinkGroups", GROUP, "Link Groups Together")
        obj.addProperty("App::PropertyLinkListGlobal", "Parts", GROUP, "The parts the tabs and slots are worked out on")
        # names, not links: the slot features link here, and a link back would be a dependency loop
        obj.addProperty("App::PropertyStringList", "Slots", GROUP, "The slot features in the other parts")
        obj.setEditorMode("Slots", 1)
        obj.setEditorMode("Groups", 2)
        obj.Groups = json.dumps([new_group()])
        obj.Proxy = self

    def groups(self, obj):
        try:
            out = json.loads(obj.Groups) or [new_group()]
        except Exception:
            return [new_group()]
        for g in out:
            g.setdefault("CenterAlign", True)       # parts made before Center align was added stay centred
            g.setdefault("Skip", [])
            g.setdefault("Propagate", False)
        return out

    def execute(self, obj):
        base = obj.BaseFeature
        if base is None:
            raise ValueError("Tab and Slot: needs a part")
        body = _body_of(obj)
        shape = _global(base)
        tabs, slots = [], []
        for g, lay, tab_obj, slot_obj in layouts(obj.Document, self.groups(obj), obj.LinkGroups):
            if _body_of(tab_obj) is not body:
                raise ValueError("The tabs must all be on one part.")
            tabs += lay.tabs(g)
            if _body_of(slot_obj) is body:
                slots += lay.slots(g, shape)
        if slots:
            shape = shape.cut(slots)
        if tabs:
            shape = shape.fuse(tabs).removeSplitter()
        if len(shape.Solids) == 1:
            shape = shape.Solids[0]
        obj.Shape = _to_local(shape, body)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def copies(body):
    """Copies of a part: (link, placement that takes the part's shape onto the copy) for each
    App::Link to its body in the document."""
    out = []
    if body is None:
        return out
    for o in body.Document.Objects:
        if o.TypeId != "App::Link" or getattr(o, "LinkedObject", None) is not body:
            continue
        try:
            at = o.getGlobalPlacement() if hasattr(o, "getGlobalPlacement") else o.Placement
        except Exception:
            at = o.Placement
        if not getattr(o, "LinkTransform", False):
            at = at.multiply(body.Placement.inverse())
        out.append((o, at))
    return out


def propagated(g, lay, tab_obj, slot_shape):
    """The slots for the copies of the tab part that sit on slot_shape (Propagate Slots)."""
    if not g.get("Propagate"):
        return []
    out = []
    for _link, at in copies(_body_of(tab_obj)):
        m = at.toMatrix()
        moved = []
        for tool in lay.slots(g, _moved(slot_shape, at.inverse())):
            t = tool.copy()
            t.transformShape(m, True)
            moved.append(t)
        out += [t for t in moved if slot_shape.common(t).Volume > 1e-9]
    return out


def _moved(shape, place):
    s = shape.copy()
    s.transformShape(place.toMatrix(), True)
    return s


class SWSlots:
    """The slots of a Tab and Slot in another part's body."""

    def __init__(self, obj, tabslot):
        obj.addProperty("App::PropertyLinkGlobal", "TabAndSlot", GROUP, "The Tab and Slot these slots belong to")
        obj.TabAndSlot = tabslot
        obj.Proxy = self

    def execute(self, obj):
        base, ts = obj.BaseFeature, obj.TabAndSlot
        if base is None or ts is None:
            raise ValueError("Tab and Slot: the slots have lost their part")
        body = _body_of(obj)
        shape = _global(base)
        slots = []
        for g, lay, tab, slot_obj in layouts(obj.Document, ts.Proxy.groups(ts), ts.LinkGroups):
            if _body_of(slot_obj) is body:
                slots += lay.slots(g, shape)
                slots += propagated(g, lay, tab, shape)
        if slots:
            shape = shape.cut(slots)
            if len(shape.Solids) == 1:
                shape = shape.Solids[0]
        obj.Shape = _to_local(shape, body)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def slots_of(ts):
    """The slot features of a Tab and Slot."""
    found = [ts.Document.getObject(n) for n in ts.Slots]
    return [o for o in found if o is not None]


def is_tab_and_slot(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWTabAndSlot"


def is_slots(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWSlots"


class ViewProviderTabAndSlot:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        from .smunfold import _icon
        return _icon(ICON)

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        main = obj.TabAndSlot if is_slots(obj) else obj
        obj.Document.openTransaction("Edit " + main.Label)
        try:
            Gui.Control.showDialog(Panel(main, False))
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

    def onDelete(self, vobj, subelements):
        obj = vobj.Object
        if is_tab_and_slot(obj):
            for s in slots_of(obj):
                try:
                    _remove_feature(s)
                except Exception as _fw_err:
                    _fw_log("smtabslot.py:524", _fw_err)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _remove_feature(obj):
    """Take a feature out of its body, the one before it becoming the Tip again."""
    body = _body_of(obj)
    doc = obj.Document
    if body is not None:
        base = obj.BaseFeature
        if body.Tip is obj:
            body.Tip = base
        body.removeObject(obj)
        if base is not None:
            try:
                base.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("smtabslot.py:547", _fw_err)
    doc.removeObject(obj.Name)


def _add_feature(body, kind, name, label, *args):
    doc = body.Document
    base = body.Tip
    obj = doc.addObject("PartDesign::FeaturePython", name)
    kind(obj, *args)
    if App.GuiUp:
        ViewProviderTabAndSlot(obj.ViewObject)
    body.addObject(obj)
    obj.Label = label
    if base is not None:
        try:
            base.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("smtabslot.py:564", _fw_err)
    return obj


# ================================================================ PropertyManager
def _source(obj):
    """The feature a pick stands for: a body's last feature, never this command's own features."""
    if obj is None:
        return None
    if obj.TypeId == "PartDesign::Body":
        obj = obj.Tip
    while obj is not None and (is_tab_and_slot(obj) or is_slots(obj)):
        obj = obj.BaseFeature
    return obj


def _nearest(items, at):
    v = Part.Vertex(at)
    best = min(((x.distToShape(v)[0], x) for x in items), key=lambda p: p[0], default=None)
    return best[1] if best and best[0] < 1e-3 else None


class Panel:
    """The Tab and Slot PropertyManager."""

    @property
    def active(self):
        return getattr(self, "_active", None)

    @active.setter
    def active(self, w):
        """The box the next pick goes into: drawn light blue, the others white (pmboxes.mark)."""
        self._active = w
        try:
            from . import pmboxes
            for lst in self.lists.values():
                pmboxes.mark(lst, lst is w)
        except Exception as _fw_err:
            _fw_log("smtabslot:active", _fw_err)

    LISTS = (("Edge", "SWSMTabEdge", "#d6ecff", "Edge for the tabs"),
             ("Start", "SWSMTabStart", "#ffd6ec", "Start reference point (the edge's start when empty)"),
             ("End", "SWSMTabEnd", "#e6d6ff", "End reference point (the edge's end when empty)"),
             ("SlotFace", "SWSMTabSlotFace", "#d6ffd6", "Face for the slots"),
             ("TabFace", "SWSMTabFace", "#cdeee6", "Tab face (filled in by itself on sheet metal)"))

    def __init__(self, obj, new, doc=None):
        from PySide import QtWidgets
        from .smbaseflange import _box, _spin
        from .smedgeflange import error_label
        from .smunfold import _DeleteKey, _list
        global _LAST
        _LAST = self
        self.obj = obj
        self.doc = obj.Document if obj is not None else doc
        self.new = new
        self.pick_error = ""
        self.busy = True
        self.groups = obj.Proxy.groups(obj) if obj is not None else [new_group()]
        self.linked = bool(obj.LinkGroups) if obj is not None else False
        self.current = 0

        sel = _box("Selection")
        f = sel.layout()
        self.error = error_label()
        f.addRow(self.error)
        self.group_list = QtWidgets.QListWidget()
        self.group_list.setObjectName("SWSMTabGroups")
        self.group_list.setMaximumHeight(58)
        f.addRow(self.group_list)
        self.link = QtWidgets.QCheckBox("Link Groups Together")
        self.link.setObjectName("SWSMTabLinkGroups")
        f.addRow(self.link)
        self.new_group = QtWidgets.QPushButton("New Group")
        self.new_group.setObjectName("SWSMTabNewGroup")
        f.addRow(self.new_group)
        self.lists = {}
        from PySide import QtCore
        from . import pmpics
        for key, name, colour, tip in self.LISTS:
            w = _list(name, colour, tip)
            w.setStyleSheet("")
            self.lists[key] = w
            icon = QtWidgets.QLabel()
            icon.setObjectName(name + "Icon")
            icon.setPixmap(pmpics.pixmap("pick", key, 20))
            icon.setToolTip(tip)
            icon.setAlignment(QtCore.Qt.AlignTop)
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(icon)
            row.addWidget(w, 1)
            f.addRow(row)

        off = _box("Offset")
        f = off.layout()
        self.use_offset = QtWidgets.QCheckBox("Offset")
        self.use_offset.setObjectName("SWSMTabUseOffset")
        f.addRow(self.use_offset)
        self.start_offset = _spin("SWSMTabStartOffset", 0.0, 0.0, 10000.0, step=1.0)
        self.start_offset.setToolTip("Start offset")
        f.addRow("Start:", self.start_offset)
        self.end_offset = _spin("SWSMTabEndOffset", 0.0, 0.0, 10000.0, step=1.0)
        self.end_offset.setToolTip("End offset")
        f.addRow("End:", self.end_offset)

        sp = _box("Spacing")
        f = sp.layout()
        self.equal = QtWidgets.QRadioButton("Equal Spacing")
        self.equal.setObjectName("SWSMTabEqual")
        self.pitch_mode = QtWidgets.QRadioButton("Spacing Length")
        self.pitch_mode.setObjectName("SWSMTabSpacingLength")
        f.addRow(self.equal)
        f.addRow(self.pitch_mode)
        self.count = QtWidgets.QSpinBox()
        self.count.setObjectName("SWSMTabCount")
        self.count.setRange(1, 1000)
        self.count.setToolTip("Number of tabs")
        f.addRow("Tabs:", self.count)
        self.pitch = _spin("SWSMTabSpacing", 20.0, 0.0, 100000.0, step=1.0)
        self.pitch.setToolTip("Spacing length")
        f.addRow("Spacing:", self.pitch)
        self.center = QtWidgets.QCheckBox("Center align")
        self.center.setObjectName("SWSMTabCenterAlign")
        self.center.setToolTip("Centers the tabs on the edge (else they start at the start point)")
        f.addRow(self.center)
        self.skip = QtWidgets.QListWidget()
        self.skip.setObjectName("SWSMTabSkip")
        self.skip.setMaximumHeight(80)
        self.skip.setToolTip("Instances to Skip: tick the tabs to leave out")
        f.addRow("Instances to Skip:", self.skip)
        self.skip.itemChanged.connect(self._skip_changed)

        tb = _box("Tabs")
        f = tb.layout()
        self.length = _spin("SWSMTabLength", 5.0, 0.0, 100000.0, step=0.5)
        self.length.setToolTip("Length")
        f.addRow("Length:", self.length)
        self.thick = _spin("SWSMTabThickness", 1.0, 0.0, 10000.0, step=0.1)
        self.thick.setToolTip("Thickness")
        f.addRow("Thickness:", self.thick)
        self.height = QtWidgets.QComboBox()
        self.height.setObjectName("SWSMTabHeight")
        self.height.addItems(HEIGHTS)
        self.height.setToolTip("Height")
        f.addRow("Height:", self.height)
        self.height_value = _spin("SWSMTabHeightValue", 1.0, -10000.0, 10000.0, step=0.5)
        f.addRow("", self.height_value)
        self.edge_buttons = self._buttons(f, "SWSMTabEdge", EDGES, "Edges Type")
        self.edge_size = _spin("SWSMTabEdgeSize", 0.5, 0.0, 1000.0, step=0.1)
        self.edge_size.setToolTip("Fillet radius or chamfer distance")
        f.addRow("", self.edge_size)

        sl = _box("Slot")
        f = sl.layout()
        self.no_through = QtWidgets.QCheckBox("No Through Cut")
        self.no_through.setObjectName("SWSMSlotNoThrough")
        f.addRow(self.no_through)
        self.normal = QtWidgets.QCheckBox("Normal Cut")
        self.normal.setObjectName("SWSMSlotNormal")
        f.addRow(self.normal)
        self.length_offset = _spin("SWSMSlotLengthOffset", 0.1, 0.0, 1000.0, decimals=3, step=0.05)
        self.length_offset.setToolTip("Slot length offset")
        f.addRow("Length offset:", self.length_offset)
        self.width_offset = _spin("SWSMSlotWidthOffset", 0.1, 0.0, 1000.0, decimals=3, step=0.05)
        self.width_offset.setToolTip("Slot width offset")
        f.addRow("Width offset:", self.width_offset)
        self.equal_offset = QtWidgets.QCheckBox("Equal offset")
        self.equal_offset.setObjectName("SWSMSlotEqualOffset")
        f.addRow(self.equal_offset)
        self.propagate = QtWidgets.QCheckBox("Propagate Slots")
        self.propagate.setObjectName("SWSMSlotPropagate")
        self.propagate.setToolTip("Cut the slots for every copy of the tab part too (copies made by Copy with "
                                  "Mates, mirror or pattern, as links to the part)")
        f.addRow(self.propagate)
        self.corner_buttons = self._buttons(f, "SWSMSlot", CORNERS, "Corner Type")
        self.corner_size = _spin("SWSMSlotCornerSize", 0.5, 0.0, 1000.0, step=0.1)
        self.corner_size.setToolTip("Fillet radius, chamfer distance or circle radius")
        f.addRow("", self.corner_size)

        sel.setProperty("swstyle_pm_title", TITLE)
        sel.setProperty("swstyle_pm_icon", ICON)
        self.form = [sel, off, sp, tb, sl]
        self.active = self.lists["Edge"]
        self.keys = _DeleteKey(self)
        for w in self.lists.values():
            w.installEventFilter(self.keys)
        self.spins = (self.start_offset, self.end_offset, self.pitch, self.length, self.thick, self.height_value,
                      self.edge_size, self.length_offset, self.width_offset, self.corner_size)
        for s in self.spins + (self.count,):
            s.valueChanged.connect(self._changed)
        for b in (self.use_offset, self.equal, self.pitch_mode, self.center, self.no_through, self.normal, self.equal_offset,
                  self.propagate) \
                + tuple(self.edge_buttons.values()) + tuple(self.corner_buttons.values()):
            b.toggled.connect(self._changed)
        self.height.currentIndexChanged.connect(self._changed)
        self.link.toggled.connect(self._link)
        self.new_group.clicked.connect(self._new_group)
        from . import pmboxes
        pmboxes.bind(self.group_list, remove=self._drop_group)
        self.group_list.currentRowChanged.connect(self._group_picked)
        self.link.setChecked(self.linked)
        self.busy = False
        self._load()
        self._report()
        self._fill_skip()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def _buttons(self, form, prefix, names, tip):
        from PySide import QtWidgets
        row = QtWidgets.QHBoxLayout()
        group = QtWidgets.QButtonGroup(form.parentWidget())
        out = {}
        glyphs = {"Sharp": "▢", "Fillet": "▢̲", "Chamfer": "⬠", "Circular": "◌"}
        for n in names:
            b = QtWidgets.QToolButton()
            b.setObjectName(prefix + n)
            b.setCheckable(True)
            b.setText(glyphs.get(n, n[0]))
            b.setToolTip("%s: %s" % (tip, n.lower()))
            group.addButton(b)
            row.addWidget(b)
            out[n] = b
        row.addStretch(1)
        form.addRow(tip + ":", row)
        return out

    # ---------------------------------------------------------------- groups
    def g(self):
        return self.groups[self.current]

    def _settings(self):
        """The group whose settings the controls show (the first one when the groups are linked)."""
        return self.groups[0] if self.linked else self.g()

    def _load(self):
        self.busy = True
        self.group_list.clear()
        for k, grp in enumerate(self.groups):
            self.group_list.addItem("Group%d" % (k + 1))
        self.group_list.setCurrentRow(self.current)
        s = self._settings()
        self.use_offset.setChecked(s["UseOffset"])
        self.start_offset.setValue(s["StartOffset"])
        self.end_offset.setValue(s["EndOffset"])
        (self.equal if s["EqualSpacing"] else self.pitch_mode).setChecked(True)
        self.count.setValue(int(s["Count"]))
        self.pitch.setValue(s["Spacing"])
        self.center.setChecked(bool(s.get("CenterAlign", True)))
        self.length.setValue(s["Length"])
        self.thick.setValue(s["Thickness"])
        self.height.setCurrentIndex(HEIGHTS.index(s["Height"]))
        self.height_value.setValue(s["HeightValue"])
        self.edge_buttons[s["EdgeType"]].setChecked(True)
        self.edge_size.setValue(s["EdgeSize"])
        self.no_through.setChecked(s["NoThroughCut"])
        self.normal.setChecked(s["NormalCut"])
        self.length_offset.setValue(s["LengthOffset"])
        self.width_offset.setValue(s["WidthOffset"])
        self.equal_offset.setChecked(s["EqualOffset"])
        self.propagate.setChecked(bool(s.get("Propagate", False)))
        self.corner_buttons[s["CornerType"]].setChecked(True)
        self.corner_size.setValue(s["CornerSize"])
        for key, w in self.lists.items():
            w.clear()
            sel = self.g().get(key)
            if sel:
                w.addItem("%s@%s" % (sel[1], self._label(sel[0])))
        self._greys()
        self.busy = False

    def _label(self, name):
        o = self.doc.getObject(name)
        return o.Label if o is not None else name

    def _greys(self):
        s = self._settings()
        # nothing greyed (drawings-land271): rows that don't apply are hidden; the offsets stay live and a value
        # typed there turns Offset on / Equal offset off
        smlive.row(self.count, s["EqualSpacing"])
        smlive.row(self.pitch, not s["EqualSpacing"])
        self.center.setVisible(not s["EqualSpacing"])
        smlive.row(self.height_value, s["Height"] != "Up To Surface")
        smlive.row(self.edge_size, s["EdgeType"] != "Sharp")
        smlive.row(self.corner_size, s["CornerType"] != "Sharp")
        if not getattr(self, "_live_wired", False):
            self._live_wired = True
            for w in (self.start_offset, self.end_offset):
                w.valueChanged.connect(lambda *_: smlive.turn(self, self.use_offset))
            self.width_offset.valueChanged.connect(lambda *_: smlive.turn(self, self.equal_offset, False))

    def _group_picked(self, row):
        if self.busy or row < 0 or row >= len(self.groups):
            return
        self.current = row
        self._load()
        self._report()
        self._fill_skip()

    def _new_group(self):
        grp = new_group()
        grp.update({k: self._settings()[k] for k in DEFAULTS})
        self.groups.append(grp)
        self.current = len(self.groups) - 1
        self.active = self.lists["Edge"]
        self._load()
        self._sync()

    def _drop_group(self, row):
        ""
        if len(self.groups) < 2 or not 0 <= row < len(self.groups):
            return
        del self.groups[row]
        self.current = min(self.current if self.current < row else max(0, self.current - 1), len(self.groups) - 1)
        self._load()
        self._sync()

    def _link(self, on):
        if self.busy:
            return
        self.linked = bool(on)
        self._load()
        self._sync()

    def _changed(self, *_a):
        if self.busy:
            return
        s = self._settings()
        s["UseOffset"] = self.use_offset.isChecked()
        s["StartOffset"], s["EndOffset"] = self.start_offset.value(), self.end_offset.value()
        s["EqualSpacing"] = self.equal.isChecked()
        s["Count"], s["Spacing"] = self.count.value(), self.pitch.value()
        s["CenterAlign"] = self.center.isChecked()
        s["Length"], s["Thickness"] = self.length.value(), self.thick.value()
        s["Height"], s["HeightValue"] = self.height.currentText(), self.height_value.value()
        s["EdgeType"] = next(n for n, b in self.edge_buttons.items() if b.isChecked())
        s["EdgeSize"] = self.edge_size.value()
        s["NoThroughCut"], s["NormalCut"] = self.no_through.isChecked(), self.normal.isChecked()
        s["LengthOffset"], s["WidthOffset"] = self.length_offset.value(), self.width_offset.value()
        s["EqualOffset"] = self.equal_offset.isChecked()
        s["Propagate"] = self.propagate.isChecked()
        s["CornerType"] = next(n for n, b in self.corner_buttons.items() if b.isChecked())
        s["CornerSize"] = self.corner_size.value()
        self._greys()
        self._sync()

    # ---------------------------------------------------------------- lists
    def set_active(self, w):
        if w in self.lists.values():
            self.active = w

    def remove_current(self, w):
        key = next((k for k, lst in self.lists.items() if lst is w), None)
        if key is None:
            return
        self.g()[key] = None
        self._load()
        self._sync()

    # ---------------------------------------------------------------- picks
    def addSelection(self, doc, name, sub, point):
        from PySide import QtCore
        at = App.Vector(*point) if point else None
        QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub, at))

    def _picked(self, doc_name, name, sub, at):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smtabslot.py:904", _fw_err)
        src = _source(App.getDocument(doc_name).getObject(name))
        if src is None or not sub:
            return
        shape = _global(src)
        if at is None:
            at = shape.getElement(sub).CenterOfMass if not sub.startswith("Vertex") else shape.getElement(sub).Point
        self.pick_error = ""
        grp = self.g()
        active = next((k for k, w in self.lists.items() if w is self.active), "Edge")
        kind = sub.rstrip("0123456789")
        if kind == "Edge":
            edge = _nearest([e for e in shape.Edges if e.Curve.TypeId == "Part::GeomLine"], at)
            if edge is None:
                self.pick_error = "The tab edge must be a straight edge."
                self._report()
                return
            a, b = _line_of(edge)
            grp["Edge"] = [src.Name, sub, [tuple(a), tuple(b)]]
            grp["TabFace"] = None
            self._auto_thickness(grp, src, shape, edge)
            self.active = self.lists["SlotFace"] if not grp.get("SlotFace") else self.active
        elif kind == "Vertex":
            v = _nearest(shape.Vertexes, at)
            if v is None:
                return
            key = active if active in ("Start", "End") else ("Start" if not grp.get("Start") else "End")
            grp[key] = [src.Name, sub, [tuple(v.Point)]]
        elif kind == "Face":
            face = _nearest([f for f in shape.Faces if f.Surface.TypeId == "Part::GeomPlane"], at)
            if face is None:
                self.pick_error = "Pick a flat face."
                self._report()
                return
            from .smnormalcut import inside_point
            entry = [src.Name, sub, [tuple(inside_point(face)), tuple(face.normalAt(0, 0))]]
            if active == "TabFace":
                grp["TabFace"] = entry
            else:
                grp["SlotFace"] = entry
                if grp.get("Edge") and (not grp.get("TabFace") or grp["TabFace"][3:] == ["auto"]):
                    tab_obj = self.doc.getObject(grp["Edge"][0])
                    tshape = _global(tab_obj)
                    edge = _find_edge(tshape, grp["Edge"][2])
                    self._auto_thickness(grp, tab_obj, tshape, edge, face.normalAt(0, 0))
        self._load()
        self._sync()

    def _auto_thickness(self, grp, src, shape, edge, slot_normal=None):
        """On sheet metal the tab face is found by itself, and the tabs take the sheet's thickness."""
        if slot_normal is None and grp.get("SlotFace"):
            slot_normal = V(*grp["SlotFace"][2][1])
        tface = tab_face(shape, edge, slot_normal)
        if tface is None:
            return
        from .smnormalcut import inside_point
        p = inside_point(tface)
        k = next((i for i, f in enumerate(shape.Faces, 1) if f.isSame(tface)), 0)
        grp["TabFace"] = [src.Name, "Face%d" % k, [tuple(p), tuple(tface.normalAt(0, 0))], "auto"]
        t = _thickness(shape, p, -tface.normalAt(0, 0))
        if t > 1e-6:
            target = self._settings()
            target["Thickness"] = round(t, 6)

    # ---------------------------------------------------------------- features
    def _sync(self):
        """Make, move or drop the tab and slot features to match the groups, then recompute."""
        doc = self.doc
        if doc.Recomputing:
            from PySide import QtCore
            QtCore.QTimer.singleShot(50, self._sync)
            return
        first = self.groups[0].get("Edge")
        tab_body = _body_of(doc.getObject(first[0])) if first and doc.getObject(first[0]) else None
        ts = self.obj
        if ts is not None and (tab_body is None or _body_of(ts) is not tab_body):
            for s in slots_of(ts):
                _remove_feature(s)
            _remove_feature(ts)
            ts = self.obj = None
        if ts is None and tab_body is not None:
            label = naming.next_label(doc, "Tab and Slot")
            ts = self.obj = _add_feature(tab_body, SWTabAndSlot, "TabAndSlot", label)
        if ts is None:
            self._report()
            return
        ts.Groups = json.dumps(self.groups)
        ts.LinkGroups = self.linked
        parts = []
        bodies = []
        for grp in self.groups:
            for key in ("Edge", "SlotFace"):
                o = _obj(doc, grp.get(key))
                if o is not None and o not in parts and o is not ts.BaseFeature:
                    parts.append(o)
            o = _obj(doc, grp.get("SlotFace"))
            b = _body_of(o) if o is not None else None
            if b is not None and b is not tab_body and b not in bodies:
                bodies.append(b)
        ts.Parts = parts
        slots = slots_of(ts)
        for s in slots[:]:
            if _body_of(s) not in bodies:
                slots.remove(s)
                _remove_feature(s)
        for b in bodies:
            if not any(_body_of(s) is b for s in slots):
                slots.append(_add_feature(b, SWSlots, "Slots", ts.Label + "-Slots", ts))
        ts.Slots = [x.Name for x in slots]
        links = [c[0] for c in copies(tab_body)] if any(grp.get("Propagate") for grp in self.groups) else []
        for x in slots:
            if "Copies" not in x.PropertiesList:
                x.addProperty("App::PropertyLinkListGlobal", "Copies", GROUP, "Copies of the tab part whose slots are cut here")
            x.Copies = links
        ts.touch()
        for s in slots:
            s.touch()
        doc.recompute()
        self._report()
        self._fill_skip()

    def _fill_skip(self):
        """Instances to Skip: one tickable row per tab the current group's spacing makes."""
        from PySide import QtCore, QtWidgets
        values = dict(self.g())
        if self.linked:
            values.update({k: self.groups[0][k] for k in DEFAULTS})
        values["Skip"] = []
        total = 0
        try:
            for _v, lay, _t, _s in layouts(self.doc, [values], False):
                total = lay.total
        except Exception:
            total = 0
        skip = set(int(k) for k in self.g().get("Skip") or [])
        was, self.busy = self.busy, True
        try:
            self.skip.clear()
            for k in range(1, total + 1):
                item = QtWidgets.QListWidgetItem("Instance %d" % k)
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.Checked if k in skip else QtCore.Qt.Unchecked)
                self.skip.addItem(item)
        finally:
            self.busy = was

    def _skip_changed(self, _item=None):
        if self.busy:
            return
        from PySide import QtCore
        self.g()["Skip"] = [k + 1 for k in range(self.skip.count())
                            if self.skip.item(k).checkState() == QtCore.Qt.Checked]
        self._sync()

    def _report(self):
        text = ""
        objs = [self.obj] + slots_of(self.obj) if self.obj is not None else []
        bad = next((o for o in objs if "Invalid" in o.State), None)
        if bad is not None:
            text = bad.getStatusString()
        elif self.pick_error:
            text = self.pick_error
        elif not self.g().get("Edge") or not self.g().get("SlotFace"):
            text = MESSAGE
        self.error.setText(text)
        self.error.setVisible(bool(text))
        return not text

    def getStandardButtons(self):
        from PySide import QtWidgets
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smtabslot.py:1080", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smtabslot.py:1086", _fw_err)

    def accept(self):
        self.pick_error = ""
        if not self._report():
            return False
        for o in [self.obj] + slots_of(self.obj):
            try:
                o.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("smtabslot.py:1096", _fw_err)
        self.doc.commitTransaction()
        _close_transaction(False)
        self._close()
        return True

    def reject(self):
        self.doc.abortTransaction()
        _close_transaction(True)
        self.doc.recompute()
        for b in self.doc.Objects:
            if b.TypeId == "PartDesign::Body" and b.Tip is not None:
                try:
                    b.Tip.ViewObject.Visibility = True
                except Exception as _fw_err:
                    _fw_log("smtabslot.py:1111", _fw_err)
        self._close()
        return True


def _close_transaction(abort):
    """Also end FreeCAD's application-wide transaction, which an edit with no change leaves open."""
    try:
        App.closeActiveTransaction(abort)
    except Exception as _fw_err:
        _fw_log("smtabslot.py:1121", _fw_err)


# ================================================================ command
def _has_part():
    if App.ActiveDocument is None:
        return False
    try:
        if Gui.Control.activeDialog():
            return False
    except Exception as _fw_err:
        _fw_log("smtabslot.py:1140", _fw_err)
        return False
    return any(o.TypeId == "PartDesign::Body" and o.Tip is not None and not o.Tip.Shape.isNull()
               for o in App.ActiveDocument.Objects)


def start():
    if not _has_part():
        return
    doc = App.ActiveDocument
    picked = [(o.Document.Name, o.Object.Name, sub, App.Vector(p)) for o in Gui.Selection.getSelectionEx()
              for sub, p in zip(o.SubElementNames, o.PickedPoints) if sub.startswith(("Edge", "Face"))]
    doc.openTransaction(TITLE)
    try:
        panel = Panel(None, True, doc)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    for doc_name, name, sub, at in sorted(picked, key=lambda p: not p[2].startswith("Edge"))[:2]:
        panel._picked(doc_name, name, sub, at)


class Command:
    def GetResources(self):
        from .smunfold import _icon
        return {"Pixmap": _icon(ICON), "MenuText": "Tab and Slot",
                "ToolTip": "Adds tabs along an edge of one part and matching slots in the face of another."}

    def IsActive(self):
        return _has_part()

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
