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
import Part
from PySide import QtCore, QtWidgets

from . import naming, wetrim
from . import pmboxes

COMMAND = "SWStyle_WEGusset"
TITLE = "Gusset"
LABEL = "Gusset"
GROUP = "Gusset"
PROFILES = ("Polygonal", "Triangular")
SIDES = ("Inner side", "Both sides", "Outer side")
LOCATIONS = ("Start", "Mid point", "End")
HINT = "Select two planar faces that meet at an angle."
TOL = 1e-6


def _weicon(name):
    from . import weprofile
    return weprofile.icon(name)

def is_gusset(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "Gusset"


def _load(text, default):
    try:
        return json.loads(text or "")
    except Exception:
        return default


def _v(x):
    return App.Vector(*x)


# ---------------------------------------------------------------- faces
def face_ref(obj, sub):
    """What is stored for a picked face: a member body with the face's normal and a point on it,
    or any object's face by name."""
    try:
        face = obj.Shape.getElement(sub)
    except Exception as _fw_err:
        _fw_log("wegusset.py:76", _fw_err)
        return None
    if face.ShapeType != "Face" or face.Surface.TypeId != "Part::GeomPlane":
        return None
    ref = wetrim.ref_of(obj)
    if ref is not None:
        n, p = face.normalAt(0, 0), face.CenterOfMass
        return {"kind": "body", "ref": ref, "normal": [n.x, n.y, n.z], "point": [p.x, p.y, p.z]}
    return {"kind": "face", "obj": obj.Name, "sub": sub}


def resolve(doc, item, source=None):
    """The planar face an item stands for (on source, the body's shape, for a member face)."""
    if item.get("kind") == "face":
        obj = doc.getObject(item.get("obj", ""))
        try:
            return obj.Shape.getElement(item["sub"])
        except Exception:
            return None
    body = source if source is not None else wetrim.current_tip(doc, item["ref"])
    if body is None:
        return None
    n, p = _v(item["normal"]), _v(item["point"])
    best, best_d = None, None
    for f in body.Shape.Faces:
        if f.Surface.TypeId != "Part::GeomPlane" or f.normalAt(0, 0).dot(n) < 1 - 1e-6:
            continue
        d = abs((f.CenterOfMass - p).dot(n)) * 1000 + (f.CenterOfMass - p).Length
        if best_d is None or d < best_d:
            best, best_d = f, d
    return best


# ---------------------------------------------------------------- geometry
def gusset_shape(obj, f1, f2):
    n1, n2 = f1.normalAt(0, 0), f2.normalAt(0, 0)
    axis = n1.cross(n2)
    if axis.Length < 1e-6:
        raise RuntimeError("Gusset: the supporting faces are parallel")
    axis.normalize()
    # a point on the line where the two planes meet
    c1, c2 = f1.CenterOfMass, f2.CenterOfMass
    d1, d2 = n1.dot(c1), n2.dot(c2)
    origin = (n2.cross(axis) * d1 + axis.cross(n1) * d2) * (1.0 / axis.dot(n1.cross(n2)))
    # in each face, the direction away from the corner line, into the open corner: along face 1 the
    # way face 2 looks (its outward normal), and the other way about. The faces' centres can lie
    # across the line (a rail's top face runs on past the cross bar on both sides), which put the
    # plate inside the member (video follow-along WE5); the centres decide only when the corner is flat
    v1 = axis.cross(n1)
    if abs(v1.dot(n2)) > 1e-6:
        if v1.dot(n2) < 0:
            v1 = -v1
    elif v1.dot(c1 - origin) < 0:
        v1 = -v1
    v2 = axis.cross(n2)
    if abs(v2.dot(n1)) > 1e-6:
        if v2.dot(n1) < 0:
            v2 = -v2
    elif v2.dot(c2 - origin) < 0:
        v2 = -v2
    v1.normalize()
    v2.normalize()
    # the faces' common length along the line
    spans = []
    for f in (f1, f2):
        ts = [(v.Point - origin).dot(axis) for v in f.Vertexes]
        for e in f.Edges:
            ts += [(p - origin).dot(axis) for p in e.discretize(8)]
        spans.append((min(ts), max(ts)))
    lo, hi = max(spans[0][0], spans[1][0]), min(spans[0][1], spans[1][1])
    if hi - lo < TOL:
        raise RuntimeError("Gusset: the supporting faces do not overlap along their corner")
    t = float(obj.Thickness)
    at = {"Start": lo, "Mid point": (lo + hi) / 2, "End": hi}[obj.Location]
    inward = 1.0 if obj.Location != "End" else -1.0
    if obj.UseOffset and obj.Location != "Mid point":
        at += inward * float(obj.Offset)
    # the plate starts at `start` along the line and runs t in `inward`
    start = {"Inner side": at, "Both sides": at - inward * t / 2, "Outer side": at - inward * t}[obj.Side]
    a, b = float(obj.D1), float(obj.D2)
    if obj.Reverse:
        a, b = b, a
    corner = origin + axis * start
    p1, p2 = corner + v1 * a, corner + v2 * b
    if obj.Profile == "Polygonal" and getattr(obj, "UseAngle", False):
        e = float(obj.D3)
        top = p2 + v1 * e
        w = v1.cross(v2).cross(v1)              # square to v1 in the plate's plane, toward v2's side
        w.normalize()
        ang = math.radians(float(obj.ProfileAngle))
        d = v1 * math.cos(ang) - w * math.sin(ang)
        # the slanted edge from top meets the d1 end edge (p1 + v2 s)
        s_, k = _meet(top, d, p1, v2, w, v1)
        if k is None or k < TOL or k > b + TOL or s_ < -TOL:
            raise RuntimeError("Gusset: the profile angle a1 doesn't fit d1, d2 and d3")
        pts = [corner, p1, p1 + v2 * k, top, p2]
    elif obj.Profile == "Polygonal":
        e = float(obj.D3)
        pts = [corner, p1, p1 + v2 * e, p2 + v1 * e, p2]
    else:
        pts = [corner, p1, p2]
    if obj.Profile == "Polygonal" and getattr(obj, "UseD4", False):
        pts = _chamfer_corner(pts, 2, float(obj.D4))       # the free corner: at the end of the d1 end edge
    if obj.Chamfer:
        pts = [corner + v1 * float(obj.D5)] + pts[1:] + [corner + v2 * float(obj.D6)]
    face = Part.Face(Part.makePolygon(pts + pts[:1]))
    return face.extrude(axis * inward * t)


def _meet(a, da, b, db, w, v1):
    """(s, t) with a + da s = b + db t, solved in the plate's plane (axes v1, w)."""
    ax, ay = da.dot(v1), da.dot(w)
    bx, by = db.dot(v1), db.dot(w)
    rx, ry = (b - a).dot(v1), (b - a).dot(w)
    det = ax * (-by) - (-bx) * ay
    if abs(det) < 1e-12:
        return None, None
    s = (rx * (-by) - (-bx) * ry) / det
    t = (ax * ry - ay * rx) / det
    return s, t


def _angle_props(obj):
    if "UseAngle" not in obj.PropertiesList:
        obj.addProperty("App::PropertyBool", "UseAngle", GROUP, "Polygonal: the profile angle a1 instead of d3 at the d1 end")
        obj.addProperty("App::PropertyAngle", "ProfileAngle", GROUP, "Profile angle (a1)")
        obj.ProfileAngle = 45.0
    if "UseD4" not in obj.PropertiesList:
        obj.addProperty("App::PropertyBool", "UseD4", GROUP, "Polygonal: chamfer the free corner by d4")
        obj.addProperty("App::PropertyDistance", "D4", GROUP, "Profile distance 4: the free corner's chamfer")
        obj.D4 = 5.0


def _chamfer_corner(pts, k, d):
    """pts with corner k cut back d along both its edges."""
    a, c, b = pts[k - 1], pts[k], pts[(k + 1) % len(pts)]
    la, lb = (a - c).Length, (b - c).Length
    if d <= TOL or d >= la - TOL or d >= lb - TOL:
        raise RuntimeError("Gusset: d4 doesn't fit the profile's free corner")
    return pts[:k] + [c + (a - c).normalize() * d, c + (b - c).normalize() * d] + pts[k + 1:]


class Gusset:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyString", "Faces", GROUP, "Supporting faces (JSON)")
        add("App::PropertyLinkList", "Sources", GROUP, "The member shapes the faces are on")
        add("App::PropertyString", "Profile", GROUP, "Polygonal or Triangular")
        add("App::PropertyDistance", "D1", GROUP, "Profile distance 1")
        add("App::PropertyDistance", "D2", GROUP, "Profile distance 2")
        add("App::PropertyDistance", "D3", GROUP, "Profile distance 3 (Polygonal)")
        add("App::PropertyBool", "Reverse", GROUP, "Reverse profile d1 and d2 parameters")
        add("App::PropertyBool", "Chamfer", GROUP, "Chamfer the inside corner")
        add("App::PropertyDistance", "D5", GROUP, "Chamfer distance 1")
        add("App::PropertyDistance", "D6", GROUP, "Chamfer distance 2")
        add("App::PropertyString", "Side", GROUP, "Inner side, Both sides or Outer side")
        add("App::PropertyDistance", "Thickness", GROUP, "Gusset thickness")
        add("App::PropertyString", "Location", GROUP, "Start, Mid point or End")
        add("App::PropertyBool", "UseOffset", GROUP, "Offset the gusset from the location")
        add("App::PropertyDistance", "Offset", GROUP, "Offset")
        add("App::PropertyLinkList", "Created", GROUP, "Objects made by this feature")
        add("App::PropertyString", "Outputs", GROUP, "Unused: a gusset changes no member")
        for name in ("Faces", "Sources", "Created", "Outputs"):
            obj.setEditorMode(name, 2)
        obj.Faces = "[]"
        obj.Outputs = "{}"
        obj.Profile = "Triangular"
        obj.D1 = obj.D2 = 50.0
        obj.D3 = 15.0
        obj.D5 = obj.D6 = 5.0
        obj.Side = "Both sides"
        obj.Thickness = 10.0
        obj.Location = "Mid point"
        obj.Offset = 10.0
        _angle_props(obj)
        obj.Proxy = self

    def execute(self, obj):
        items = _load(obj.Faces, [])
        if len(items) != 2:
            obj.Shape = Part.Shape()
            return
        from . import wemember
        sources = [s for s in obj.Sources if _alive(s)]
        faces = []
        for item in items:
            src = None
            if item.get("kind") == "body":
                src = next((s for s in sources if wetrim.ref_of(s) == item["ref"]), None)
                if src is None:
                    src = wetrim.current_tip(obj.Document, item["ref"], obj)
            try:
                faces.append(resolve(obj.Document, item, src))
            except Exception:
                faces.append(None)
        if None in faces:
            if wemember.refreshing():
                return          # the members are being rebuilt: build() links the new ones next
            raise RuntimeError("Gusset: a supporting face is gone")
        obj.Shape = gusset_shape(obj, *faces)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _alive(o):
    try:
        return o is not None and bool(o.Name) and o.Document is not None
    except Exception:
        return False


def build(obj):
    """Links the gusset to the members' current shapes, so it rebuilds after them."""
    doc = obj.Document
    sources = []
    for item in _load(obj.Faces, []):
        if item.get("kind") == "body":
            tip = wetrim.current_tip(doc, item["ref"], obj)
            if tip is not None and tip not in sources:
                sources.append(tip)
        else:
            o = doc.getObject(item.get("obj", ""))
            if o is not None and o not in sources:
                sources.append(o)
    obj.Sources = sources
    obj.touch()


class ViewProviderGusset:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        try:
            return _weicon("corner.svg")
        except Exception:
            return ""

    def claimChildren(self):
        return []

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        obj.Document.openTransaction("Edit " + TITLE)
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


def make(doc):
    obj = doc.addObject("Part::FeaturePython", "Gusset")
    Gusset(obj)
    if App.GuiUp:
        ViewProviderGusset(obj.ViewObject)
        obj.ViewObject.ShapeColor = (0.62, 0.65, 0.70)
    obj.Label = naming.next_label(doc, LABEL)
    return obj


# ---------------------------------------------------------------- PropertyManager
def _box(title):
    box = QtWidgets.QWidget()
    box.setWindowTitle(title)
    QtWidgets.QFormLayout(box)
    return box


def _spin(name, value, lo=0.0, hi=10000.0, suffix=" mm"):
    w = QtWidgets.QDoubleSpinBox()
    w.setObjectName(name)
    w.setRange(lo, hi)
    w.setDecimals(2)
    w.setSuffix(suffix)
    w.setValue(value)
    return w


def _buttons(parent, layout, prefix, texts, current):
    group = QtWidgets.QButtonGroup(parent)
    row = QtWidgets.QHBoxLayout()
    for i, text in enumerate(texts):
        b = QtWidgets.QToolButton()
        b.setObjectName(prefix + text.replace(" ", ""))
        b.setText(text)
        b.setToolTip(text)
        b.setCheckable(True)
        b.setAutoRaise(True)
        b.setChecked(text == current)
        from . import pmpics
        pmpics.picture(b, "gusset", text)
        group.addButton(b, i)
        row.addWidget(b)
    row.addStretch(1)
    layout.addRow(row)
    return group


class _Keys(QtCore.QObject):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Delete:
            self.panel.remove_current()
            return True
        return False


class Panel:
    def __init__(self, obj, new):
        self.obj = obj
        self.new = new
        self.busy = True
        self.items = _load(obj.Faces, [])

        faces = _box("Supporting Faces")
        f = faces.layout()
        self.faces = QtWidgets.QListWidget()
        self.faces.setObjectName("SWWEGussetFaces")
        self.faces.setMaximumHeight(52)
        pmboxes.mark(self.faces, True)
        self._keys = _Keys(self)
        self.faces.installEventFilter(self._keys)
        f.addRow(self.faces)

        profile = _box("Profile")
        f = profile.layout()
        self.profiles = _buttons(profile, f, "SWWEGusset", PROFILES, obj.Profile)
        self.d1 = _spin("SWWEGussetD1", float(obj.D1), 0.01)
        f.addRow("d1", self.d1)
        self.reverse = QtWidgets.QPushButton("Reverse profile d1 and d2 parameters")
        self.reverse.setObjectName("SWWEGussetReverse")
        self.reverse.setCheckable(True)
        self.reverse.setChecked(obj.Reverse)
        f.addRow(self.reverse)
        self.d2 = _spin("SWWEGussetD2", float(obj.D2), 0.01)
        f.addRow("d2", self.d2)
        self.d3 = _spin("SWWEGussetD3", float(obj.D3), 0.0)
        self.d3_label = QtWidgets.QLabel("d3")
        f.addRow(self.d3_label, self.d3)
        _angle_props(obj)
        self.use_d3 = QtWidgets.QRadioButton("d3")
        self.use_d3.setObjectName("SWWEGussetUseD3")
        self.use_d3.setToolTip("Profile distance 3: the ends of the polygonal profile")
        self.use_a1 = QtWidgets.QRadioButton("a1")
        self.use_a1.setObjectName("SWWEGussetUseA1")
        self.use_a1.setToolTip("Profile angle: the slanted edge's angle to the d1 leg")
        (self.use_a1 if obj.UseAngle else self.use_d3).setChecked(True)
        self.ends = QtWidgets.QWidget()           # its own parent: exclusive only with each other
        el = QtWidgets.QHBoxLayout(self.ends)
        el.setContentsMargins(0, 0, 0, 0)
        el.addWidget(self.use_d3)
        el.addWidget(self.use_a1)
        el.addStretch(1)
        f.addRow(self.ends)
        self.a1 = _spin("SWWEGussetA1", float(obj.ProfileAngle), 0.1, 89.9, " deg")
        self.a1.setToolTip("Profile angle (a1)")
        self.a1_label = QtWidgets.QLabel("a1")
        f.addRow(self.a1_label, self.a1)
        self.use_d4 = QtWidgets.QCheckBox("d4")
        self.use_d4.setObjectName("SWWEGussetUseD4")
        self.use_d4.setToolTip("Profile distance 4: chamfers the polygonal profile's free corner")
        self.use_d4.setChecked(bool(obj.UseD4))
        self.d4 = _spin("SWWEGussetD4", float(obj.D4), 0.0)
        f.addRow(self.use_d4, self.d4)
        self.chamfer = QtWidgets.QCheckBox("Chamfer")
        self.chamfer.setObjectName("SWWEGussetChamfer")
        self.chamfer.setChecked(obj.Chamfer)
        f.addRow(self.chamfer)
        self.d5 = _spin("SWWEGussetD5", float(obj.D5), 0.01)
        f.addRow("d5", self.d5)
        self.d6 = _spin("SWWEGussetD6", float(obj.D6), 0.01)
        f.addRow("d6", self.d6)

        thickness = _box("Thickness")
        f = thickness.layout()
        self.sides = _buttons(thickness, f, "SWWEGusset", SIDES, obj.Side)
        self.thickness = _spin("SWWEGussetThickness", float(obj.Thickness), 0.01)
        f.addRow("Gusset thickness", self.thickness)

        params = _box("Parameters")
        f = params.layout()
        f.addRow(QtWidgets.QLabel("Location:"))
        self.locations = _buttons(params, f, "SWWEGusset", LOCATIONS, obj.Location)
        self.use_offset = QtWidgets.QCheckBox("Offset")
        self.use_offset.setObjectName("SWWEGussetUseOffset")
        self.use_offset.setChecked(obj.UseOffset)
        f.addRow(self.use_offset)
        self.offset = _spin("SWWEGussetOffset", float(obj.Offset), 0.0)
        f.addRow(self.offset)
        self.error = QtWidgets.QLabel("")
        self.error.setObjectName("SWWEGussetError")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c00000;")
        from . import pickprompt
        pickprompt.style(self.error)     # look audit AI1: the start prompt in the yellow box
        f.addRow(self.error)

        for w in (faces, profile, thickness, params):
            w.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        faces.setProperty("swstyle_pm_title", TITLE)
        faces.setProperty("swstyle_pm_icon", "SWStyle_WEGusset")
        self.form = [faces, profile, thickness, params]
        self._show()

        for g in (self.profiles, self.sides, self.locations):
            g.buttonClicked.connect(self._changed)
        for w in (self.d1, self.d2, self.d3, self.d5, self.d6, self.thickness, self.offset, self.a1):
            w.valueChanged.connect(self._changed)
        self.use_a1.toggled.connect(self._changed)
        self.use_d4.toggled.connect(self._changed)
        self.d4.valueChanged.connect(self._changed)
        for w in (self.reverse, self.chamfer, self.use_offset):
            w.toggled.connect(self._changed)
        self.busy = False
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def _show(self):
        busy, self.busy = self.busy, True
        doc = self.obj.Document
        self.faces.clear()
        for k, item in enumerate(self.items, 1):
            if item.get("kind") == "body":
                tip = wetrim.current_tip(doc, item["ref"])
                label = tip.Label if tip is not None else item["ref"]
            else:
                o = doc.getObject(item.get("obj", ""))
                label = o.Label if o is not None else item.get("obj", "")
            self.faces.addItem("Face<%d>@%s" % (k, label))
        polygon = PROFILES[max(0, self.profiles.checkedId())] == "Polygonal"
        for w in (self.d3, self.d3_label, self.a1, self.a1_label, self.ends, self.use_d4, self.d4):
            w.setVisible(polygon)
        from . import smlive            # nothing greyed: the boxes that do not apply are hidden (drawings-land281)
        self.d4.setVisible(polygon and self.use_d4.isChecked())
        if polygon:                     # d3 or a1, whichever is picked
            smlive.row(self.d3, not self.use_a1.isChecked())
            smlive.row(self.a1, self.use_a1.isChecked())
        for w in (self.d5, self.d6):
            smlive.row(w, self.chamfer.isChecked())
        mid = LOCATIONS[max(0, self.locations.checkedId())] == "Mid point"
        smlive.row(self.use_offset, not mid)
        smlive.row(self.offset, self.use_offset.isChecked() and not mid)
        if len(self.items) < 2:
            self.error.setText(HINT)
            self.error.setVisible(True)
        self.busy = busy

    def _changed(self, *args):
        if self.busy:
            return
        obj = self.obj
        obj.Faces = json.dumps(self.items)
        obj.Profile = PROFILES[max(0, self.profiles.checkedId())]
        obj.D1, obj.D2, obj.D3 = self.d1.value(), self.d2.value(), self.d3.value()
        obj.UseAngle = self.use_a1.isChecked()
        obj.ProfileAngle = self.a1.value()
        obj.UseD4, obj.D4 = self.use_d4.isChecked(), self.d4.value()
        obj.Reverse = self.reverse.isChecked()
        obj.Chamfer = self.chamfer.isChecked()
        obj.D5, obj.D6 = self.d5.value(), self.d6.value()
        obj.Side = SIDES[max(0, self.sides.checkedId())]
        obj.Thickness = self.thickness.value()
        obj.Location = LOCATIONS[max(0, self.locations.checkedId())]
        obj.UseOffset = self.use_offset.isChecked()
        obj.Offset = self.offset.value()
        self.error.hide()
        self._show()
        try:
            build(obj)
            obj.Document.recompute()
            if "Invalid" in obj.State:
                raise RuntimeError(obj.getStatusString())
            from . import wecutlist
            wecutlist.update(obj.Document)
        except Exception as error:
            self.error.setText(str(error))
            self.error.show()

    # ---------------------------------------------------------------- selection
    def addSelection(self, doc, name, sub, point):
        # a PropertyManager closed without its own close (Esc through the PM keys) must not keep
        # clearing every pick in the view
        try:
            from .widgets import alive
            forms = self.form if isinstance(self.form, (list, tuple)) else [self.form]
            if not (Gui.Control.activeDialog() and any(alive(f) and _in_tasks(f) for f in forms)):
                Gui.Selection.removeObserver(self)
                return
        except Exception:
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("wegusset.py:575", _fw_err)
            return
        if sub.startswith("Face"):
            from . import safe_later as _sl; _sl.later(0, lambda: self._picked(doc, name, sub), self, "error")

    def _picked(self, doc_name, name, sub):
        # The panel can close between addSelection and this queued callback. Recheck before touching
        # selection or the model, and fail closed if the Qt wrapper is already gone.
        try:
            from .widgets import alive
            forms = self.form if isinstance(self.form, (list, tuple)) else [self.form]
            if not (Gui.Control.activeDialog() and any(alive(f) and _in_tasks(f) for f in forms)):
                Gui.Selection.removeObserver(self)
                return
        except Exception:
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("wegusset.py:593", _fw_err)
            return
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("wegusset.py:598", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None or picked is self.obj:
            return
        item = face_ref(picked, sub)
        if item is None:
            self.error.setText(HINT)
            self.error.show()
            return
        if item in self.items:
            return
        self.items = (self.items + [item])[-2:]
        self._changed()

    def remove_current(self):
        row = self.faces.currentRow()
        if row < 0:
            return
        del self.items[row]
        self._changed()

    # ---------------------------------------------------------------- closing
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("wegusset.py:627", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("wegusset.py:633", _fw_err)

    def accept(self):
        if len(self.items) != 2 or "Invalid" in self.obj.State:
            if len(self.items) != 2:
                self.error.setText(HINT)
            self.error.show()
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
    doc = App.ActiveDocument
    if doc is None:
        return
    picked = []
    for s in Gui.Selection.getSelectionEx():
        for sub in s.SubElementNames:
            item = face_ref(s.Object, sub)
            if item is not None and item not in picked:
                picked.append(item)
    doc.openTransaction(TITLE)
    try:
        obj = make(doc)
        panel = Panel(obj, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    if picked:
        panel.items = picked[-2:]
        panel._changed()


class Command:
    def GetResources(self):
        try:
            pixmap = _weicon("corner.svg")
        except Exception:
            pixmap = ""
        return {"Pixmap": pixmap, "MenuText": "Gusset", "ToolTip": "Adds a plate between two faces of members."}

    def IsActive(self):
        if not wetrim.weldment_ready():
            return False
        try:
            return not Gui.Control.activeDialog()
        except Exception:
            return True

    def Activated(self):
        if not wetrim.need_members("Gusset"):
            return
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())


def _in_tasks(w):
    """The form still sits in FreeCAD's task view: shown, or hidden behind the FeatureManager tab."""
    try:
        p = w
        while p is not None:
            if p.metaObject().className() in ("Gui::TaskView::TaskView", "Gui::TaskView::TaskBox"):
                return True
            p = p.parentWidget()
    except (RuntimeError, AttributeError):
        return False
    return False
