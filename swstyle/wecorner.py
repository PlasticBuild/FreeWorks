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
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import naming, wemember, wetrim
from . import pmboxes

LABEL = "Corner Management"
TITLE = "Corner Management"
GROUP = "Corner Management"
KINDS = ("Simple", "Two Member", "Complex")
TRIMS = ("Miter trim", "Planar trim", "Body trim", "Open corner")
DEFAULT = {"Simple": "Miter trim", "Two Member": "Planar trim", "Complex": "Planar trim"}
CONTACTS = ("First contact", "Full contact")
TOL = 1e-4

NODE_COLORS = {"Simple": "#2fa84f", "Two Member": "#2f7de1", "Complex": "#e8862a"}
NODE_PICK_PX = 14


def _swatch(color, size=12):
    from PySide import QtGui
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pm = _hidpi.canvas(size, size)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor("#202020"), 1))
    p.setBrush(QtGui.QColor(color))
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return QtGui.QIcon(pm)


class CornerNodes:
    """The corner nodes: a ball at every corner of the system, coloured by its kind, the picked one larger;
    a click on a node picks that corner in the PropertyManager."""

    def __init__(self, panel):
        self.panel = panel
        self.root = None
        self.view = None
        self.cb = None
        self.points = []           # (kind, index in its kind, point)
        self.callout = []          # the picked corner's callout lines

    def show(self, items, current=None):
        self.hide_nodes()
        try:
            from pivy import coin
            self.view = Gui.ActiveDocument.ActiveView
            sg = self.view.getSceneGraph()
        except Exception:
            return
        root = coin.SoSeparator()
        root.setName("SWCornerNodes")
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        root.addChild(pick)
        top = coin.SoAnnotation()
        root.addChild(top)
        self.points = []
        size = self._size()
        for kind, k, c in items:
            col = NODE_COLORS[kind]
            sep = coin.SoSeparator()
            mat = coin.SoMaterial()
            r, g, b = (int(col[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
            mat.diffuseColor = (r, g, b)
            mat.emissiveColor = (r * 0.6, g * 0.6, b * 0.6)
            tr = coin.SoTranslation()
            p = c["point"]
            tr.translation = (p.x, p.y, p.z)
            ball = coin.SoSphere()
            picked = current is not None and (c is current or c.get("key") == current.get("key"))
            ball.radius = size * (1.8 if picked else 1.0)
            for n in (mat, tr, ball):
                sep.addChild(n)
            if picked:
                sep.addChild(self._callout(coin, c, size))
            top.addChild(sep)
            self.points.append((kind, k, p))
        sg.addChild(root)
        self.root = root
        if self.cb is None:
            try:
                self.cb = self.view.addEventCallback("SoMouseButtonEvent", self._click)
            except Exception:
                self.cb = None

    def callout_lines(self, c):
        ""
        t = treatment(self.panel.obj, c)
        lines = [t["trim"]]
        if t["gap"] > 0:
            lines.append("Gap %.2f mm" % t["gap"])
        if len(c["members"]) > 2:
            letters = {r: chr(65 + i) for i, r in enumerate(c["members"])}
            lines.append("Order " + " \u25b8 ".join(letters[r] for r in t["order"]))
        return lines

    def _callout(self, coin, c, size):
        sep = coin.SoSeparator()
        sep.setName("SWCornerCallout")
        tr = coin.SoTranslation()
        tr.translation = (size * 2.5, size * 2.5, 0)
        col = coin.SoBaseColor()
        col.rgb = (0.12, 0.31, 0.55)
        font = coin.SoFont()
        font.size = 13
        text = coin.SoText2()
        text.string.setValues(0, 0, [])
        lines = self.callout_lines(c)
        text.string.setValues(0, len(lines), lines)
        self.callout = lines
        for n in (tr, col, font, text):
            sep.addChild(n)
        return sep

    def _size(self):
        """A ball about as big as the members' profile allows: a fifth of the smallest member's width."""
        try:
            system = self.panel.obj.System
            best = None
            for ref, (a, b) in _members(system):
                body = wetrim.current_tip(self.panel.obj.Document, ref)
                if body is None:
                    continue
                bb = body.Shape.BoundBox
                w = sorted((bb.XLength, bb.YLength, bb.ZLength))[0]
                best = w if best is None else min(best, w)
            return max(0.5, (best or 10.0) * 0.35)
        except Exception:
            return 2.0

    def _click(self, info):
        if info.get("State") != "DOWN" or info.get("Button") != "BUTTON1" or not self.points:
            return
        try:
            x, y = info["Position"]
            best, hit = NODE_PICK_PX, None
            for kind, k, p in self.points:
                sx, sy = self.view.getPointOnViewport(p)
                d = math.hypot(sx - x, sy - y)
                if d < best:
                    best, hit = d, (kind, k)
            if hit is not None:
                QtCore.QTimer.singleShot(0, lambda hit=hit: self.panel.pick_node(*hit))
        except Exception as _fw_err:
            _fw_log("wecorner.py:185", _fw_err)

    def hide_nodes(self):
        if self.root is not None and self.view is not None:
            try:
                self.view.getSceneGraph().removeChild(self.root)
            except Exception as _fw_err:
                _fw_log("wecorner.py:192", _fw_err)
        self.root = None

    def close(self):
        self.hide_nodes()
        if self.cb is not None and self.view is not None:
            try:
                self.view.removeEventCallback("SoMouseButtonEvent", self.cb)
            except Exception as _fw_err:
                _fw_log("wecorner.py:201", _fw_err)
        self.cb = None


def orders_of(c):
    """The trimming orders a complex corner can take: the members' orders, the current first."""
    import itertools
    return [list(o) for o in itertools.permutations(c["members"])]


class OrderPicker(QtWidgets.QFrame):
    ""



    def __init__(self, panel, c):
        super().__init__(Gui.getMainWindow(), QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
        self.setObjectName("SWCMOrderPicker")
        self.setFrameShape(QtWidgets.QFrame.Box)
        self.panel, self.c = panel, c
        self.start = list(treatment(panel.obj, c)["order"])
        self.orders = orders_of(c)
        self.k = next((i for i, o in enumerate(self.orders) if o == self.start), 0)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        self.prev = QtWidgets.QToolButton()
        self.prev.setObjectName("SWCMOrderPrev")
        self.prev.setArrowType(QtCore.Qt.LeftArrow)
        self.symbols = QtWidgets.QLabel()
        self.symbols.setObjectName("SWCMOrderSymbols")
        self.symbols.setToolTip("Trimming order: each member is trimmed by the members before it")
        self.next = QtWidgets.QToolButton()
        self.next.setObjectName("SWCMOrderNext")
        self.next.setArrowType(QtCore.Qt.RightArrow)
        self.ok = QtWidgets.QToolButton()
        self.ok.setObjectName("SWCMOrderOK")
        self.ok.setText("\u2714")
        self.ok.setStyleSheet("QToolButton { color: #1e9e3a; font-weight: bold; }")
        self.ok.setToolTip("Keep this trimming order")
        self.cancel = QtWidgets.QToolButton()
        self.cancel.setObjectName("SWCMOrderCancel")
        self.cancel.setText("\u2716")
        self.cancel.setStyleSheet("QToolButton { color: #c03030; }")
        self.cancel.setToolTip("Back to the order the corner had")
        for w in (self.prev, self.symbols, self.next, self.ok, self.cancel):
            lay.addWidget(w)
        self.prev.clicked.connect(lambda: self.step(-1))
        self.next.clicked.connect(lambda: self.step(1))
        self.ok.clicked.connect(self.keep)
        self.cancel.clicked.connect(self.back)
        self._label()

    def _label(self):
        order = self.orders[self.k]
        letters = {r: chr(65 + i) for i, r in enumerate(self.c["members"])}
        self.symbols.setText(" \u25b8 ".join("%s %s" % (letters[r], self.panel._label(r)) for r in order))

    def step(self, d):
        self.k = (self.k + d) % len(self.orders)
        self._label()
        self.panel._store(self.c, order=list(self.orders[self.k]))      # the preview follows

    def keep(self):
        self.close()
        self.panel.picker = None

    def back(self):
        self.panel._store(self.c, order=list(self.start))
        self.close()
        self.panel.picker = None

    def place(self, point):
        try:
            view = Gui.ActiveDocument.ActiveView
            x, y = view.getPointOnViewport(point)
            gl = view.graphicsView() if hasattr(view, "graphicsView") else None
            w = gl.viewport() if gl is not None else Gui.getMainWindow()
            at = w.mapToGlobal(QtCore.QPoint(int(x) + 16, int(w.height() - y) - 16))
            self.adjustSize()
            self.move(at)
        except Exception as _fw_err:
            _fw_log("wecorner.py:282", _fw_err)


def _weicon(name):
    from . import weprofile
    return weprofile.icon(name)


# ================================================================ corners
def _members(system):
    """[(ref, (start, end))] of the system's member bodies, as their paths run."""
    doc = system.Document
    out = []
    for sm in system.Primaries:
        for k, body in enumerate(sm.Bodies):
            base = wetrim.base_of(body)
            if base is None:
                continue
            try:
                out.append(("%s:%d" % (sm.Name, k), wetrim.line_of(base)))
            except Exception:
                continue
    return out


def _on(p, a, b):
    """True when p lies inside segment a-b (not at its ends)."""
    d = b - a
    t = (p - a).dot(d) / d.dot(d)
    if t <= TOL / d.Length or t >= 1 - TOL / d.Length:
        return False
    return (a + d * t - p).Length < TOL


def corners(system):
    """The system's corners, in a steady order: [{kind, members, ends, point, key}]. members: for Simple the
    two members in tree order, for Two Member [through, ending], for Complex the members passing through
    first; ends: {ref: 0 or 1} of the members that end there."""
    members = _members(system)
    points = []
    for _ref, (a, b) in members:
        for p in (a, b):
            if not any((p - q).Length < TOL for q in points):
                points.append(p)
    out = []
    for p in points:
        ending, ends, through = [], {}, []
        for ref, (a, b) in members:
            if (a - p).Length < TOL or (b - p).Length < TOL:
                ending.append(ref)
                ends[ref] = 1 if (b - p).Length < TOL else 0
            elif _on(p, a, b):
                through.append(ref)
        lines = dict(members)
        if len(ending) == 2 and not through:
            a0, a1 = lines[ending[0]]
            b0, b1 = lines[ending[1]]
            da, db = (a1 - a0).normalize(), (b1 - b0).normalize()
            if abs(abs(da.dot(db)) - 1) < 1e-9:
                continue                # members running on in line: no corner
            kind, refs = "Simple", ending
        elif len(ending) == 1 and len(through) == 1:
            kind, refs = "Two Member", through + ending
        elif len(ending) + len(through) >= 3 and ending:
            kind, refs = "Complex", through + ending
        else:
            continue
        out.append({"kind": kind, "members": refs, "ends": ends, "point": p,
                    "key": kind + "|" + ",".join(sorted(refs))})
    return out


def _profile(doc, ref):
    sm = doc.getObject(ref.split(":")[0])
    return tuple(str(getattr(sm, k, "")) for k in ("Standard", "Type", "Size")) if sm is not None else ("", "", "")


def signature(system, corner):
    ""

    doc = system.Document
    lines = dict(_members(system))
    dirs = []
    for r in corner["members"]:
        a, b = lines[r]
        d = (b - a).normalize()
        if corner["ends"].get(r) == 1:
            d = d * -1                           # pointing away from the corner
        dirs.append(d)
    angles = []
    for i in range(len(dirs)):
        for j in range(i + 1, len(dirs)):
            dot = max(-1.0, min(1.0, dirs[i].dot(dirs[j])))
            ang = math.degrees(math.acos(dot))
            if corner["members"][i] not in corner["ends"] or corner["members"][j] not in corner["ends"]:
                ang = min(ang, 180.0 - ang)      # a member running through has no direction of its own
            angles.append(round(ang, 1))
    roles = [_profile(doc, r) for r in corner["members"]]
    if corner["kind"] == "Simple":
        roles, angles = sorted(roles), sorted(angles)
    return (corner["kind"], tuple(roles), tuple(angles))


def similar(system, corner):
    """The other corners of the system alike to corner."""
    sig = signature(system, corner)
    return [c for c in corners(system) if c["key"] != corner["key"] and signature(system, c) == sig]


def apply_to_similar(cm, corner):
    """Gives corner's treatment to each similar corner (the trimming order by role). Returns how many."""
    system = cm.System
    t = treatment(cm, corner)
    pos = [corner["members"].index(r) for r in t["order"]]
    data = _load(cm.Treatments, {})
    n = 0
    for c in similar(system, corner):
        order = [c["members"][k] for k in pos if k < len(c["members"])]
        data[c["key"]] = {"trim": t["trim"], "order": order, "contact": t["contact"], "gap": t["gap"]}
        n += 1
    if n:
        cm.Treatments = json.dumps(data)
    return n


def treatment(cm, corner):
    """The corner's treatment {trim, order, contact, gap}: the stored one, else the default for its kind."""
    stored = _load(cm.Treatments, {}).get(corner["key"], {})
    order = [r for r in stored.get("order", []) if r in corner["members"]]
    order += [r for r in corner["members"] if r not in order]
    trim = stored.get("trim", DEFAULT[corner["kind"]])
    if trim == "Miter trim" and not can_miter(corner, order):
        trim = "Planar trim"
    if trim == "Open corner" and corner["kind"] != "Simple":
        trim = "Planar trim"
    if trim not in TRIMS:
        trim = DEFAULT[corner["kind"]]
    contact = stored.get("contact", "Full contact")
    if contact not in CONTACTS:
        contact = "Full contact"
    point = stored.get("point")
    point = [float(x) for x in point] if isinstance(point, (list, tuple)) and len(point) == 3 else None
    return {"trim": trim, "order": order, "contact": contact, "gap": max(0.0, float(stored.get("gap", 0.0) or 0.0)),
            "point": point}


def can_miter(corner, order):
    ""

    if corner["kind"] == "Simple":
        return True
    return corner["kind"] == "Complex" and len(order) >= 2 and all(r in corner["ends"] for r in order[:2])


def base_normal(cm):
    """The normal of the Corner Management's base plane, else None."""
    ref = _load(getattr(cm, "BasePlane", "") or "", None)
    if not ref:
        return None
    obj = cm.Document.getObject(ref[0])
    if obj is None:
        return None
    try:
        plane = wetrim.source_plane(obj, ref[1] if len(ref) > 1 else "")
    except Exception:
        plane = None
    return App.Vector(plane[1]).normalize() if plane else None


def automatic_order(system, corner, normal):
    """Automatic mode: the members crossing the base plane first (they run through), then the ones lying
    along it; ties keep the corner's own order."""
    lines = dict(_members(system))

    def along(ref):
        a, b = lines[ref]
        return abs((b - a).normalize().dot(normal))
    return sorted(corner["members"], key=lambda r: -round(along(r), 6))


def apply_automatic(cm):
    """Automatic: every corner its kind's default treatment, the trimming order from the base plane."""
    system = cm.System
    if system is None:
        return 0
    normal = base_normal(cm)
    data = {}
    for c in corners(system):
        t = {"trim": DEFAULT[c["kind"]], "contact": "Full contact", "gap": 0.0}
        t["order"] = automatic_order(system, c, normal) if normal is not None else list(c["members"])
        if c["kind"] == "Two Member" and t["order"][0] in c["ends"]:
            t["order"] = list(c["members"])          # the through member always stays whole
        data[c["key"]] = t
    cm.Treatments = json.dumps(data)
    return len(data)


def reset_all(cm):
    """Reset All Corners: every stored treatment goes; the defaults again."""
    cm.Treatments = "{}"


def _props(obj):
    if "Mode" not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", "Mode", GROUP, "Automatic or Manual")
        obj.Mode = "Automatic"
    if "BasePlane" not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", "BasePlane", GROUP, "The base plane: [object, element] (JSON)")
        obj.setEditorMode("BasePlane", 2)


def _load(text, default):
    try:
        return json.loads(text or "")
    except Exception:
        return default


# ================================================================ the feature
class CornerManagement:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyLink", "System", GROUP, "The Structure System")
        add("App::PropertyString", "Treatments", GROUP, "Treatment of each corner (JSON)")
        add("App::PropertyLinkList", "Created", GROUP, "Objects made by this feature")
        add("App::PropertyString", "Outputs", GROUP, "Newest shape of each trimmed body (JSON)")
        for name in ("Treatments", "Created", "Outputs"):
            obj.setEditorMode(name, 2)
        obj.Treatments = "{}"
        obj.Outputs = "{}"
        _props(obj)
        obj.Proxy = self

    def onDocumentRestored(self, obj):
        _props(obj)

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_corner_management(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "CornerManagement"


def of_system(system):
    for o in system.Document.Objects:
        if is_corner_management(o) and o.System is system:
            return o
    return None


def build(cm):
    """Treats every corner of cm's system on the bodies' current shapes (wetrim.build_all calls it)."""
    doc = cm.Document
    created, outputs = [], {}

    def tip(ref):
        return doc.getObject(outputs[ref]) if ref in outputs else wetrim.current_tip(doc, ref, cm)

    def add(ref, obj):
        created.append(obj)
        outputs[ref] = obj.Name

    system = cm.System
    for c in corners(system) if system is not None else []:
        t = treatment(cm, c)
        order, trim, contact = t["order"], t["trim"], t["contact"]
        gap = t["gap"] if trim != "Body trim" else 0.0
        try:
            if c["kind"] == "Simple":
                a, b = order
                if trim == "Open corner":
                    # each member stops at the other's face; the other is taken as it was before this corner
                    before = {a: tip(a), b: tip(b)}
                    for mine, other in ((a, b), (b, a)):
                        wetrim.apply(doc, lambda r, mine=mine: tip(r) if r == mine else before[r], add, created,
                                     "End Trim", [mine], [{"kind": "body", "ref": other}], extend_boundary=False,
                                     ends={mine: c["ends"][mine]}, gap=gap, contact=contact)
                elif trim == "Miter trim":
                    wetrim.apply(doc, tip, add, created, "End Miter", [a], [{"kind": "body", "ref": b}], gap=gap)
                else:
                    wetrim.apply(doc, tip, add, created, "End Butt1", [a], [{"kind": "body", "ref": b}],
                                 butt_cut="Coped cut" if trim == "Body trim" else "Simple cut", gap=gap,
                                 contact=contact)
            else:
                first = 1
                if trim == "Miter trim":    # Complex miter: the first two members mitered, through the point if one is set
                    wetrim.apply(doc, tip, add, created, "End Miter", [order[0]], [{"kind": "body", "ref": order[1]}],
                                 gap=gap, through=App.Vector(*t["point"]) if t["point"] else None)
                    first = 2
                for i, ref in enumerate(order):
                    if i < first or ref not in c["ends"]:
                        continue            # the first member(s) and members passing through are not cut
                    wetrim.apply(doc, tip, add, created, "End Trim", [ref],
                                 [{"kind": "body", "ref": r} for r in order[:i]], extend_boundary=False,
                                 cut="Coped cut" if trim == "Body trim" else "Simple cut",
                                 ends={ref: c["ends"][ref]}, gap=gap, contact=contact)
        except Exception as error:
            App.Console.PrintWarning("Corner Management: %s\n" % error)
        doc.recompute()
    cm.Created = created
    cm.Outputs = json.dumps(outputs)
    if App.GuiUp:
        for o in created:
            try:
                o.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("wecorner.py:595", _fw_err)


def ensure(system):
    ""

    cm = of_system(system)
    if cm is not None or not system.Primaries:
        return cm
    doc = system.Document
    cm = doc.addObject("App::FeaturePython", "CornerManagement")
    CornerManagement(cm)
    if App.GuiUp:
        ViewProviderCornerManagement(cm.ViewObject)
    cm.System = system
    cm.Label = naming.next_label(doc, LABEL)
    return cm


def _icon():
    try:
        return _weicon("trim_extend.svg")
    except Exception:
        return ""


class ViewProviderCornerManagement:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        wemember._empty_mode(vobj)

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        return _icon()

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        obj.Document.openTransaction("Edit " + TITLE)
        try:
            Gui.Control.showDialog(Panel(obj))
        except BaseException:
            try:
                obj.Document.abortTransaction()
            except Exception:
                pass
            raise
        return True

    def unsetEdit(self, vobj, mode=0):
        # closed from outside (another command, Esc, a closed document): the page lets go, so its
        # corner highlight does not land in the next PropertyManager as a pick
        panel = _LAST
        if panel is not None and getattr(panel, "obj", None) is vobj.Object and not panel.closed:
            panel.closed = True
            try:
                Gui.Selection.clearSelection()
            except Exception as _fw_err:
                _fw_log("wecorner.py:655", _fw_err)
        return False

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def onDelete(self, vobj, subelements):
        obj = vobj.Object
        doc = obj.Document
        wetrim.clear(obj)
        QtCore.QTimer.singleShot(0, lambda: wetrim._refresh_later(doc))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


# ================================================================ PropertyManager
_LAST = None


def _bold(text):
    label = QtWidgets.QLabel(text)
    f = label.font()
    f.setBold(True)
    label.setFont(f)
    return label


class Panel:
    """Corner Management: tabs Simple / Two Member / Complex, the corners of that kind and the picked
    corner's treatment."""

    def __init__(self, obj):
        global _LAST
        _LAST = self
        self.obj, self.busy = obj, True
        self.closed = False
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("SWCMPanel")
        self.form.setWindowTitle(TITLE)
        self.form.setProperty("swstyle_pm_title", TITLE)
        self.form.setProperty("swstyle_pm_icon", wetrim.COMMAND)
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.setContentsMargins(4, 4, 4, 4)
        _props(obj)
        mode_row = QtWidgets.QHBoxLayout()
        self.auto = QtWidgets.QRadioButton("Automatic")
        self.auto.setObjectName("SWCMAutomatic")
        self.auto.setToolTip("Every corner gets its kind's treatment; the base plane sets the trimming order")
        self.manual = QtWidgets.QRadioButton("Manual")
        self.manual.setObjectName("SWCMManual")
        self.manual.setToolTip("Treat the corners one by one")
        self.mode_box = QtWidgets.QWidget()
        ml = QtWidgets.QHBoxLayout(self.mode_box)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addWidget(self.auto)
        ml.addWidget(self.manual)
        ml.addStretch(1)
        (self.auto if obj.Mode != "Manual" else self.manual).setChecked(True)
        self.auto.toggled.connect(self._set_mode)
        mode_row.addWidget(self.mode_box)
        lay.addLayout(mode_row)
        self.base_label = _bold("Base Plane")
        lay.addWidget(self.base_label)
        self.base = QtWidgets.QListWidget()
        self.base.setObjectName("SWCMBasePlane")
        self.base.setMaximumHeight(24)
        self.base.setToolTip("A plane or flat face: members crossing it run through, members along it are trimmed")
        lay.addWidget(self.base)
        self.base_pick = QtWidgets.QPushButton("Use Selected Plane")
        self.base_pick.setObjectName("SWCMBasePick")
        self.base_pick.setToolTip("Select a plane or a flat face, then click")
        self.base_pick.clicked.connect(self._pick_base)
        lay.addWidget(self.base_pick)
        self.reset = QtWidgets.QPushButton("Reset All Corners")
        self.reset.setObjectName("SWCMResetAll")
        self.reset.setToolTip("Clears every corner's treatment: the defaults again")
        self.reset.clicked.connect(self._reset_all)
        lay.addWidget(self.reset)
        self._show_base()
        self.tabs = QtWidgets.QTabBar()
        self.tabs.setObjectName("SWCMTabs")
        for kind in KINDS:
            self.tabs.addTab(_swatch(NODE_COLORS[kind]), kind)
        self.tabs.setExpanding(True)
        lay.addWidget(self.tabs)
        lay.addWidget(_bold("Corners"))
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWCMCorners")
        self.list.setToolTip("The corners of this kind: pick one to treat it")
        self.list.setMaximumHeight(100)
        pmboxes.mark(self.list, True)
        lay.addWidget(self.list)

        lay.addWidget(_bold("Corner Treatment"))
        row = QtWidgets.QHBoxLayout()
        self.trim_buttons = {}
        for k, trim in enumerate(TRIMS):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWCMTrim%d" % k)
            b.setText(trim.split()[0])
            b.setToolTip(trim)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.clicked.connect(lambda _c=False, trim=trim: self._set_trim(trim))
            self.trim_buttons[trim] = b
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.first = QtWidgets.QRadioButton("First contact")
        self.first.setObjectName("SWCMFirstContact")
        self.first.setToolTip("Trims the member when it first comes into contact with the other: a square cut")
        self.full = QtWidgets.QRadioButton("Full contact")
        self.full.setObjectName("SWCMFullContact")
        self.full.setChecked(True)
        self.full.setToolTip("Trims the member flush with the other member's face")
        self.full.toggled.connect(self._set_contact)
        self.contact = QtWidgets.QWidget()        # its own parent: the trim buttons are auto-exclusive too
        cl = QtWidgets.QVBoxLayout(self.contact)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.first)
        cl.addWidget(self.full)
        lay.addWidget(self.contact)

        lay.addWidget(_bold("Trimming Order"))
        self.order = QtWidgets.QListWidget()
        self.order.setObjectName("SWCMOrder")
        self.order.setToolTip("Each member is trimmed by the members above it")
        self.order.setMaximumHeight(90)
        lay.addWidget(self.order)
        row = QtWidgets.QHBoxLayout()
        self.up = QtWidgets.QPushButton("Move Up")
        self.up.setObjectName("SWCMUp")
        self.down = QtWidgets.QPushButton("Move Down")
        self.down.setObjectName("SWCMDown")
        self.up.clicked.connect(lambda: self._move(-1))
        self.down.clicked.connect(lambda: self._move(1))
        row.addWidget(self.up)
        row.addWidget(self.down)
        lay.addLayout(row)
        self.point_row = QtWidgets.QWidget()
        pl = QtWidgets.QHBoxLayout(self.point_row)
        pl.setContentsMargins(0, 0, 0, 0)
        self.point_label = QtWidgets.QLabel("Trim plane point: corner")
        self.point_label.setObjectName("SWCMMiterPoint")
        self.point_label.setToolTip("The miter plane of a complex corner passes through this point")
        self.point_pick = QtWidgets.QPushButton("Use Picked Point")
        self.point_pick.setObjectName("SWCMMiterPointPick")
        self.point_pick.setToolTip("Pick a vertex, or a point on the model, then click: the miter plane passes through it")
        self.point_pick.clicked.connect(self._pick_point)
        self.point_clear = QtWidgets.QToolButton()
        self.point_clear.setObjectName("SWCMMiterPointClear")
        self.point_clear.setText("x")
        self.point_clear.setToolTip("Back to the corner point")
        self.point_clear.clicked.connect(lambda: self._set_point(None))
        pl.addWidget(self.point_label, 1)
        pl.addWidget(self.point_pick)
        pl.addWidget(self.point_clear)
        lay.addWidget(self.point_row)
        self.gap_label = QtWidgets.QLabel("Weld gap")
        self.gap = QtWidgets.QDoubleSpinBox()
        self.gap.setObjectName("SWCMWeldGap")
        self.gap.setSuffix(" mm")
        self.gap.setRange(0.0, 1000.0)
        self.gap.setDecimals(2)
        self.gap.setToolTip("Adds a gap between the members at this corner")
        self.gap.valueChanged.connect(self._set_gap)
        lay.addWidget(self.gap_label)
        lay.addWidget(self.gap)
        self.similar = QtWidgets.QPushButton("Apply to similar corners")
        self.similar.setObjectName("SWCMApplySimilar")
        self.similar.setToolTip("Gives this corner's treatment to every corner of the same kind with the same "
                                "profiles meeting at the same angles")
        self.similar.clicked.connect(self._apply_similar)
        lay.addWidget(self.similar)
        lay.addStretch(1)

        self.tabs.currentChanged.connect(self._fill)
        self.list.currentRowChanged.connect(self._show)
        self.nodes = CornerNodes(self)
        self.picker = None
        self.busy = False
        first = next((k for k, kind in enumerate(KINDS) if self._of_kind(kind)), 0)
        self.tabs.setCurrentIndex(first)
        self._fill()

    # ------------------------------------------------------------- state
    def kind(self):
        return KINDS[self.tabs.currentIndex()]

    def _of_kind(self, kind):
        system = self.obj.System
        return [c for c in corners(system) if c["kind"] == kind] if system is not None else []

    def _label(self, ref):
        name, k = ref.split(":")
        sm = self.obj.Document.getObject(name)
        return "%s[%d]" % (sm.Label if sm is not None else name, int(k) + 1)

    def _fill(self, *_a):
        self.busy = True
        self.items = self._of_kind(self.kind())
        self.list.clear()
        for k, c in enumerate(self.items, 1):
            self.list.addItem("Corner%d: %s" % (k, ", ".join(self._label(r) for r in c["members"])))
        self.busy = False
        if self.items:
            self.list.setCurrentRow(0)
        self._show()

    def current(self):
        row = self.list.currentRow()
        return self.items[row] if 0 <= row < len(self.items) else None

    def _show(self, *_a):
        if self.busy:
            return
        self.busy = True
        c = self.current()
        kind = self.kind()
        self.trim_buttons["Miter trim"].setVisible(kind in ("Simple", "Complex"))
        self.trim_buttons["Open corner"].setVisible(kind == "Simple")
        for b in self.trim_buttons.values():
            b.setEnabled(c is not None)
        self.order.clear()
        miter_point = False
        if c is not None:
            t = treatment(self.obj, c)
            self.trim_buttons["Miter trim"].setEnabled(can_miter(c, t["order"]))
            miter_point = kind == "Complex" and t["trim"] == "Miter trim"
            self.point_label.setText("Trim plane point: %s" % ("(%.4g, %.4g, %.4g)" % tuple(t["point"])
                                                                if t["point"] else "corner"))
            self.point_clear.setEnabled(bool(t["point"]))
            self.trim_buttons[t["trim"]].setChecked(True)
            for r in t["order"]:
                self.order.addItem(self._label(r))
            planar = t["trim"] in ("Planar trim", "Open corner")
            ordered = t["trim"] != "Miter trim"
            (self.full if t["contact"] == "Full contact" else self.first).setChecked(True)
            self.gap.setValue(t["gap"])
            gapped = t["trim"] != "Body trim"
        else:
            planar = ordered = gapped = False
        self.contact.setVisible(planar)
        self.order.setEnabled(ordered)
        self.up.setEnabled(ordered)
        self.down.setEnabled(ordered)
        self.gap.setEnabled(gapped)
        self.gap_label.setEnabled(gapped)
        self.similar.setEnabled(c is not None)
        self.point_row.setVisible(miter_point)
        self.busy = False
        self._highlight(c)
        self._show_nodes(c)

    def _all_corners(self):
        system = self.obj.System
        out = []
        if system is None:
            return out
        counts = {}
        for c in corners(system):
            k = counts.get(c["kind"], 0)
            counts[c["kind"]] = k + 1
            out.append((c["kind"], k, c))
        return out

    def _show_nodes(self, current=None):
        if self.closed:
            return
        try:
            self.nodes.show(self._all_corners(), current)
        except Exception as _fw_err:
            _fw_log("wecorner.py:933", _fw_err)

    def pick_node(self, kind, k):
        """A click on a corner node: its tab and row; a complex corner opens the trim-order picker."""
        if self.closed:
            return
        self.tabs.setCurrentIndex(KINDS.index(kind))
        if 0 <= k < self.list.count():
            self.list.setCurrentRow(k)
        c = self.current()
        if self.picker is not None:
            self.picker.close()
            self.picker = None
        if c is not None and kind == "Complex":
            t = treatment(self.obj, c)
            if t["trim"] != "Miter trim":
                self.picker = OrderPicker(self, c)
                self.picker.place(c["point"])
                self.picker.show()
        return c

    def _highlight(self, c):
        if self.closed:
            return
        try:
            Gui.Selection.clearSelection()
            if c is None:
                return
            doc = self.obj.Document
            for r in c["members"]:
                body = wetrim.current_tip(doc, r)
                if body is not None:
                    Gui.Selection.addSelection(doc.Name, body.Name)
        except Exception as _fw_err:
            _fw_log("wecorner.py:967", _fw_err)

    def _store(self, c, **change):
        data = _load(self.obj.Treatments, {})
        t = treatment(self.obj, c)
        t.update(change)
        data[c["key"]] = t
        self.obj.Treatments = json.dumps(data)
        self._apply()
        self._show()


    def _show_base(self):
        self.base.clear()
        ref = _load(self.obj.BasePlane or "", None)
        if ref:
            o = self.obj.Document.getObject(ref[0])
            self.base.addItem("%s%s" % (o.Label if o is not None else ref[0], ("@" + ref[1]) if len(ref) > 1 and ref[1] else ""))
        on = self.auto.isChecked()
        for w in (self.base_label, self.base, self.base_pick):
            w.setVisible(on)
        pmboxes.mark(self.base, on and not ref)

    def _set_mode(self, *_a):
        self.obj.Mode = "Automatic" if self.auto.isChecked() else "Manual"
        if self.auto.isChecked():
            apply_automatic(self.obj)
            self._apply()
        self._show_base()
        self._fill()

    def set_base(self, obj, sub=""):
        self.obj.BasePlane = json.dumps([obj.Name, sub])
        if self.auto.isChecked():
            apply_automatic(self.obj)
            self._apply()
        self._show_base()
        self._fill()

    def _pick_base(self):
        try:
            for sel in Gui.Selection.getSelectionEx():
                subs = [x for x in sel.SubElementNames if x.startswith("Face")] or [""]
                if wetrim.source_plane(sel.Object, subs[0]) is not None:
                    self.set_base(sel.Object, subs[0])
                    return True
        except Exception as _fw_err:
            _fw_log("wecorner.py:1014", _fw_err)
        try:
            Gui.getMainWindow().statusBar().showMessage("Select a plane or a flat face first.", 4000)
        except Exception as _fw_err:
            _fw_log("wecorner.py:1018", _fw_err)
        return False

    def _reset_all(self):
        reset_all(self.obj)
        if self.auto.isChecked():
            apply_automatic(self.obj)
        self._apply()
        self._fill()

    def _set_trim(self, trim):
        c = self.current()
        if self.busy or c is None:
            return
        self._store(c, trim=trim)

    def _set_contact(self, *_a):
        c = self.current()
        if self.busy or c is None:
            return
        self._store(c, contact="Full contact" if self.full.isChecked() else "First contact")

    def _set_gap(self, value):
        c = self.current()
        if self.busy or c is None:
            return
        self._store(c, gap=float(value))

    def _move(self, step):
        c = self.current()
        row = self.order.currentRow()
        if c is None or row < 0:
            return
        order = treatment(self.obj, c)["order"]
        new = row + step
        if not 0 <= new < len(order):
            return
        order[row], order[new] = order[new], order[row]
        self._store(c, order=order)
        self.order.setCurrentRow(new)

    def _set_point(self, point):
        c = self.current()
        if self.busy or c is None:
            return
        self._store(c, point=[point.x, point.y, point.z] if point is not None else None)

    def _pick_point(self):
        """The picked vertex, or where the pick landed on the model."""
        point = None
        try:
            for sel in Gui.Selection.getSelectionEx("", 0):
                for name, obj, pp in zip(sel.SubElementNames, sel.SubObjects, sel.PickedPoints):
                    if name.split(".")[-1].startswith("Vertex"):
                        point = obj.Point
                    elif point is None:
                        point = pp
                if point is not None:
                    break
        except Exception:
            point = None
        if point is None:
            try:
                Gui.getMainWindow().statusBar().showMessage("Pick a vertex or a point on the model first.", 4000)
            except Exception as _fw_err:
                _fw_log("wecorner.py:1083", _fw_err)
            return False
        self._set_point(App.Vector(point))
        return True

    def _apply_similar(self):
        c = self.current()
        if self.busy or c is None or self.obj.System is None:
            return 0
        n = apply_to_similar(self.obj, c)
        try:
            Gui.getMainWindow().statusBar().showMessage(
                "Treatment given to %d similar corner%s." % (n, "" if n == 1 else "s") if n
                else "No other corner is like this one.", 4000)
        except Exception as _fw_err:
            _fw_log("wecorner.py:1098", _fw_err)
        if n:
            self._apply()
        return n

    def _apply(self):
        if self.closed:
            return
        doc = self.obj.Document
        if doc.Recomputing:
            QtCore.QTimer.singleShot(50, self._apply)
            return
        wemember.refresh(doc)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        self.closed = True
        try:
            if self.picker is not None:
                self.picker.close()
            self.picker = None
            self.nodes.close()
        except Exception as _fw_err:
            _fw_log("wecorner.py:1123", _fw_err)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("wecorner.py:1127", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("wecorner.py:1133", _fw_err)

    def accept(self):
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        doc.abortTransaction()
        try:
            App.closeActiveTransaction(True)
        except Exception as _fw_err:
            _fw_log("wecorner.py:1146", _fw_err)
        wemember.refresh(doc)
        self._close()
        return True
