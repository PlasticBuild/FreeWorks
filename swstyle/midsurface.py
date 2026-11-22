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
from PySide import QtCore, QtWidgets

from . import naming
from . import pmboxes

COMMAND = "SWStyle_MidSurface"
TITLE = "Mid-Surface"
LABEL = "Surface-MidSurface"
ICON = "FEATURES_MID_SURFACE"
TOL = 1e-7


# --------------------------------------------------------------------------- the geometry
def _normal(face):
    u0, u1, v0, v1 = face.ParameterRange
    n = face.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))
    n.normalize()
    return n


def _kind(face):
    return type(face.Surface).__name__


def _cylinders(a, b):
    """(outer, inner) for two faces of the same cylinder axis that face away from each other."""
    sa, sb = a.Surface, b.Surface
    if abs(abs(App.Vector(sa.Axis).dot(App.Vector(sb.Axis))) - 1) > 1e-9:
        return None
    off = App.Vector(sb.Center) - App.Vector(sa.Center)
    axis = App.Vector(sa.Axis)
    if (off - axis * off.dot(axis)).Length > 1e-6 or abs(sa.Radius - sb.Radius) < 1e-9:
        return None
    outer, inner = (a, b) if sa.Radius > sb.Radius else (b, a)

    def outward(f):
        p = f.CenterOfMass
        u, v = f.Surface.parameter(p)
        q = f.valueAt(u, v)
        c = App.Vector(f.Surface.Center)
        radial = (q - c) - axis * (q - c).dot(axis)
        return _normal_at(f, u, v).dot(radial) > 0
    if not outward(outer) or outward(inner):
        return None
    return outer, inner


def _normal_at(face, u, v):
    n = face.normalAt(u, v)
    n.normalize()
    return n


def thickness(a, b):
    """The gap between the faces of a pair, or None when they are not a pair."""
    if _kind(a) == "Plane" and _kind(b) == "Plane":
        na, nb = _normal(a), _normal(b)
        if na.dot(nb) > -1 + 1e-9:
            return None
        t = -(b.CenterOfMass - a.CenterOfMass).dot(na)
        return t if t > TOL else None
    if _kind(a) == "Cylinder" and _kind(b) == "Cylinder":
        found = _cylinders(a, b)
        if found is None:
            return None
        return found[0].Surface.Radius - found[1].Surface.Radius
    return None


def mid_face(a, b, position=50.0):
    """The face between a and b at position % of the way from a, over what they have in common."""
    t = thickness(a, b)
    if t is None:
        raise RuntimeError("These two faces are not a face pair (parallel and facing away, or a tube)")
    s = position / 100.0
    if _kind(a) == "Plane":
        na, nb = _normal(a), _normal(b)
        ma, mb = a.copy(), b.copy()
        ma.translate(-na * t * s)
        mb.translate(-nb * t * (1 - s))
        common = ma.common(mb)
        if not common.Faces or common.Area < 1e-9:
            raise RuntimeError("The two faces do not overlap")
        return common.Faces[0]
    outer, inner = _cylinders(a, b)
    r = inner.Surface.Radius + (outer.Surface.Radius - inner.Surface.Radius) * (s if a is inner else 1 - s)
    axis, centre = App.Vector(outer.Surface.Axis), App.Vector(outer.Surface.Center)
    along = lambda f: [(v.Point - centre).dot(axis) for v in f.Vertexes] or [0.0]
    lo, hi = max(min(along(outer)), min(along(inner))), min(max(along(outer)), max(along(inner)))
    if hi - lo < 1e-9:
        raise RuntimeError("The two cylinders do not overlap along their axis")
    surface = outer.Surface.copy()
    surface.Radius = r
    u0, u1, _, _ = outer.ParameterRange
    v0 = surface.parameter(centre + axis * lo)[1]
    v1 = surface.parameter(centre + axis * hi)[1]
    return surface.toShape(u0, u1, min(v0, v1), max(v0, v1))


def _extended(face, margin):
    try:
        if _kind(face) == "Plane":
            return face.makeOffset2D(margin)
        if _kind(face) == "Cylinder":
            u0, u1, v0, v1 = face.ParameterRange
            return face.Surface.toShape(u0, u1, v0 - margin, v1 + margin)
    except Exception as _fw_err:
        _fw_log("midsurface.py:136", _fw_err)
    return face


def _half(point, normal, size):
    """The solid on the normal side of the plane through point, size across."""
    square = Part.makePlane(2 * size, 2 * size, App.Vector(), normal)
    square.translate(point - square.CenterOfMass)
    return square.extrude(normal * size)


def knit(mids, solid, margin):
    """The mid faces carried on until they meet inside the solid, cut there, and knitted.

    Each mid face is grown by margin, then cut back to the solid and, for every other flat mid
    face it lies wholly on one side of, to that side of its plane: so two legs' mid faces stop
    where they meet, while a plate's mid face under a rib (on both sides of the rib's plane)
    carries on."""
    if len(mids) < 2:
        return Part.makeShell(mids) if mids else Part.Shape()
    size = solid.BoundBox.DiagonalLength * 2 + margin * 4
    faces = []
    for k, mid in enumerate(mids):
        piece = _extended(mid, margin)
        for j, other in enumerate(mids):
            if j == k or _kind(other) != "Plane":
                continue
            n, p = _normal(other), other.CenterOfMass
            sides = [(v.Point - p).dot(n) for v in mid.Vertexes]
            if min(sides) >= -1e-7:
                keep = n
            elif max(sides) <= 1e-7:
                keep = -n
            else:
                continue
            clipped = piece.common(_half(p, keep, size))
            if clipped.Faces:
                piece = clipped
        faces.extend(piece.common(solid).Faces)
    shell = Part.makeShell(faces)
    shell.sewShape(1e-6)
    return shell


def find_pairs(solid, threshold):
    """[(i, j)] of faces of solid no further apart than threshold that overlap."""
    faces = solid.Faces
    out = []
    for i in range(len(faces)):
        for j in range(i + 1, len(faces)):
            t = thickness(faces[i], faces[j])
            if t is None or t > threshold + 1e-9:
                continue
            try:
                mid_face(faces[i], faces[j])
            except Exception:
                continue
            out.append((i, j))
    return out


def _hint(face):
    return [list(face.CenterOfMass), list(_normal(face))]


def hints_of(solid, names):
    return [[_hint(solid.getElement(n)) for n in pair.split(",")] for pair in names]


def resolve(solid, names, hints):
    """The pairs' face names in solid as it is now: a face whose name now means another face (the
    solid changed) is found again as the face facing the same way nearest to where it was."""
    try:
        hints = json.loads(hints) if hints else []
    except ValueError:
        hints = []
    out = []
    for k, pair in enumerate(names):
        found = []
        for m, name in enumerate(pair.split(",")):
            hint = hints[k][m] if k < len(hints) else None
            try:
                face = solid.getElement(name)
            except Exception:
                face = None
            if hint is None or (face is not None and _close(face, hint)):
                found.append(name)
                continue
            centre, normal = App.Vector(*hint[0]), App.Vector(*hint[1])
            best = min((i for i, f in enumerate(solid.Faces) if _normal(f).dot(normal) > 0.999),
                       key=lambda i: (solid.Faces[i].CenterOfMass - centre).Length, default=None)
            found.append("Face%d" % (best + 1) if best is not None else name)
        out.append(",".join(found))
    return out


def _close(face, hint):
    return (face.CenterOfMass - App.Vector(*hint[0])).Length < 1e-6 and _normal(face).dot(App.Vector(*hint[1])) > 0.999


class MidSurface:
    def __init__(self, obj):
        obj.addProperty("App::PropertyLinkGlobal", "Source", "Mid-Surface", "The thin solid")
        obj.addProperty("App::PropertyStringList", "Pairs", "Mid-Surface", "Face pairs, as \"Face2,Face5\"")
        obj.addProperty("App::PropertyFloat", "Position", "Mid-Surface", "Where the mid face lies, in % from the "
                        "first face of each pair")
        obj.Position = 50.0
        obj.addProperty("App::PropertyLength", "Threshold", "Mid-Surface", "Recognition threshold: the "
                        "thickest gap Find Face Pairs takes")
        obj.Threshold = 5.0
        obj.addProperty("App::PropertyBool", "Knit", "Mid-Surface", "Knit surfaces: carry the mid faces on until "
                        "they meet, and knit them")
        obj.Knit = True
        self.extra(obj)
        obj.Proxy = self

    @staticmethod
    def extra(obj):
        if "FindPairs" not in obj.PropertiesList:
            obj.addProperty("App::PropertyBool", "FindPairs", "Mid-Surface",
                            "The pairs are the ones Find Face Pairs finds, found again after every change")
        if "Hints" not in obj.PropertiesList:
            obj.addProperty("App::PropertyString", "Hints", "Mid-Surface", "Where each pair's faces were (JSON)")
            obj.setEditorMode("Hints", 2)

    def execute(self, obj):
        self.extra(obj)
        if obj.Source is None or (not obj.Pairs and not obj.FindPairs):
            obj.Shape = Part.Shape()
            return
        solid = Part.getShape(obj.Source)
        if obj.FindPairs:
            names = ["Face%d,Face%d" % (i + 1, j + 1) for i, j in find_pairs(solid, obj.Threshold.Value)]
        else:
            names = resolve(solid, list(obj.Pairs), obj.Hints)
        if names != list(obj.Pairs):
            obj.Pairs = names
        hints = json.dumps(hints_of(solid, names))
        if hints != obj.Hints:
            obj.Hints = hints
        if not names:
            raise RuntimeError("No face pairs")
        faces = [(solid.getElement(p.split(",")[0]), solid.getElement(p.split(",")[1])) for p in names]
        mids = [mid_face(a, b, obj.Position) for a, b in faces]
        if obj.Knit:
            margin = max(thickness(a, b) for a, b in faces) * 2 + 1.0
            obj.Shape = knit(mids, solid, margin)
        else:
            obj.Shape = Part.makeCompound(mids)

    def onDocumentRestored(self, obj):
        self.extra(obj)
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


class View:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        try:
            from . import icons
            icon = icons.family(ICON)
            if not icon.isNull():
                return icon         # a QIcon, never a QPixmap
        except Exception as _fw_err:
            _fw_log("midsurface.py:311", _fw_err)
        return "Part_Offset"

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        Gui.Control.showDialog(Panel(vobj.Object))
        return True

    def unsetEdit(self, vobj, mode=0):
        Gui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


# --------------------------------------------------------------------------- PropertyManager
def _solid_of(holder):
    """The feature whose solid a pick is on: a body's pick is its tip."""
    if holder is None:
        return None
    if holder.TypeId == "PartDesign::Body":
        return holder.Tip
    return holder


class Panel:
    """Selections: Face Pairs (Find Face Pairs, Recognition threshold, Remove Pair), Position, and
    Options: Knit surfaces."""

    def __init__(self, obj):
        self.obj = obj
        self.busy = False
        self.pending = None
        page = QtWidgets.QWidget()
        page.setWindowTitle("Selections")
        page.setProperty("swstyle_pm_title", TITLE)
        page.setProperty("swstyle_pm_icon", ICON)
        lay = QtWidgets.QVBoxLayout(page)
        lay.addWidget(QtWidgets.QLabel("Face Pairs"))
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWStyle_MidSurfacePairs")
        self.list.setMaximumHeight(90)
        self.list.setToolTip("Click two facing faces to add a pair")
        pmboxes.mark(self.list, True)
        pmboxes.bind(self.list, remove=lambda row: (self.list.setCurrentRow(row), self._remove()))
        lay.addWidget(self.list)
        row = QtWidgets.QHBoxLayout()
        self.remove = QtWidgets.QPushButton("Remove Pair")
        self.remove.clicked.connect(self._remove)
        self.find = QtWidgets.QPushButton("Find Face Pairs")
        self.find.setObjectName("SWStyle_MidSurfaceFind")
        self.find.clicked.connect(self._find)
        row.addWidget(self.find)
        row.addWidget(self.remove)
        lay.addLayout(row)
        form = QtWidgets.QFormLayout()
        self.threshold = QtWidgets.QDoubleSpinBox()
        self.threshold.setObjectName("SWStyle_MidSurfaceThreshold")
        self.threshold.setRange(0.001, 100000.0)
        self.threshold.setSuffix(" mm")
        self.threshold.setKeyboardTracking(False)      # a typed value is taken once it is finished
        self.threshold.valueChanged.connect(self._changed)
        form.addRow("Recognition threshold", self.threshold)
        self.position = QtWidgets.QDoubleSpinBox()
        self.position.setObjectName("SWStyle_MidSurfacePosition")
        self.position.setRange(0.0, 100.0)
        self.position.setSuffix(" %")
        self.position.setKeyboardTracking(False)
        self.position.valueChanged.connect(self._changed)
        form.addRow("Position", self.position)
        lay.addLayout(form)
        options = QtWidgets.QWidget()
        options.setWindowTitle("Options")
        olay = QtWidgets.QVBoxLayout(options)
        self.knit = QtWidgets.QCheckBox("Knit surfaces")
        self.knit.toggled.connect(self._changed)
        olay.addWidget(self.knit)
        self.note = QtWidgets.QLabel("")
        self.note.setWordWrap(True)
        olay.addWidget(self.note)
        self.form = [page, options]
        self._show()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def _begin(self):
        doc = self.obj.Document
        if not doc.HasPendingTransaction:
            doc.openTransaction(TITLE)

    def _show(self):
        obj = self.obj
        self.busy = True
        self.list.clear()
        for pair in obj.Pairs:
            self.list.addItem(pair.replace(",", " - "))
        if self.pending is not None:
            self.list.addItem("%s - ..." % self.pending)
        self.threshold.setValue(obj.Threshold.Value)
        self.position.setValue(obj.Position)
        self.knit.setChecked(obj.Knit)
        self.busy = False
        if "Invalid" in obj.State:
            self.note.setText(obj.getStatusString())
        elif not obj.Pairs:
            self.note.setText("Click Find Face Pairs, or click the two faces of each pair.")
        else:
            self.note.setText("")

    def _changed(self, *args):
        if self.busy:
            return
        obj = self.obj
        values = (self.threshold.value(), self.position.value(), self.knit.isChecked())
        if values == (obj.Threshold.Value, obj.Position, obj.Knit):
            return
        self._begin()
        obj.Threshold, obj.Position, obj.Knit = values
        obj.Document.recompute()
        self._show()

    def _source(self):
        obj = self.obj
        if obj.Source is not None:
            return obj.Source
        solids = [o for o in obj.Document.Objects if o.TypeId == "PartDesign::Body" and o.Tip is not None]
        if len(solids) == 1:
            return solids[0].Tip
        return None

    def _find(self):
        source = self._source()
        if source is None:
            self.note.setText("Click a face of the solid first.")
            return
        self._begin()
        self.obj.Source = source
        pairs = find_pairs(Part.getShape(source), self.obj.Threshold.Value)
        self.obj.FindPairs = True
        self.obj.Pairs = ["Face%d,Face%d" % (i + 1, j + 1) for i, j in pairs]
        self.pending = None
        self.obj.Document.recompute()
        self._show()
        if not pairs:
            self.note.setText("No face pairs within the recognition threshold.")

    def _remove(self):
        row = self.list.currentRow()
        pairs = list(self.obj.Pairs)
        if 0 <= row < len(pairs):
            self._begin()
            del pairs[row]
            try:
                hints = json.loads(self.obj.Hints) if self.obj.Hints else []
            except ValueError:
                hints = []
            if row < len(hints):
                del hints[row]
            self.obj.FindPairs = False
            self.obj.Hints = json.dumps(hints)
            self.obj.Pairs = pairs
            self.obj.Document.recompute()
            self._show()

    def addSelection(self, doc, name, sub, point):
        if doc != self.obj.Document.Name:
            return
        QtCore.QTimer.singleShot(0, lambda: self._picked(name, sub))

    def _picked(self, name, sub):
        if self.busy:
            return
        doc = self.obj.Document
        holder = doc.getObject(name)
        for part in sub.split(".")[:-1]:
            found = doc.getObject(part)
            if found is not None:
                holder = found
        element = sub.split(".")[-1]
        Gui.Selection.clearSelection()
        holder = _solid_of(holder)
        if holder is None or holder is self.obj or not element.startswith("Face"):
            return
        if self.obj.Source is not None and holder is not self.obj.Source:
            self.note.setText("Both faces of every pair must be on the same solid.")
            return
        if self.pending is None:
            self.pending = element
            self._pending_source = holder
            self._show()
            return
        first, self.pending = self.pending, None
        solid = Part.getShape(holder)
        try:
            mid_face(solid.getElement(first), solid.getElement(element))
        except Exception as error:
            self._show()
            self.note.setText(str(error))
            return
        self._begin()
        self.obj.Source = holder
        self.obj.FindPairs = False
        self.obj.Pairs = list(self.obj.Pairs) + ["%s,%s" % (first, element)]
        doc.recompute()
        self._show()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("midsurface.py:533", _fw_err)
        Gui.ActiveDocument.resetEdit()
        Gui.Control.closeDialog()

    def accept(self):
        obj = self.obj
        obj.Document.recompute()
        if obj.Shape.isNull() or "Invalid" in obj.State:
            self.note.setText(obj.getStatusString() if "Invalid" in obj.State else
                              "Find or pick the face pairs first.")
            return False
        if obj.Document.HasPendingTransaction:
            obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("midsurface.py:554", _fw_err)
        if doc.HasPendingTransaction:
            doc.abortTransaction()
        doc.recompute()
        Gui.ActiveDocument.resetEdit()
        Gui.Control.closeDialog()
        return True


# --------------------------------------------------------------------------- making
def make(doc=None, source=None, pairs=(), edit=True):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    doc.openTransaction(TITLE)
    obj = doc.addObject("Part::FeaturePython", "MidSurface")
    MidSurface(obj)
    if App.GuiUp and obj.ViewObject is not None:
        View(obj.ViewObject)
    obj.Label = naming.next_label(doc, LABEL)
    if source is not None:
        obj.Source = source
    if pairs:
        obj.Pairs = list(pairs)
    doc.recompute()
    if edit and App.GuiUp:
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(obj.Name)
    else:
        doc.commitTransaction()
    return obj


def _preselected():
    """(source, [pair]) from two faces picked before the command."""
    picks = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        obj = sel.Object
        doc = obj.Document
        for sub in sel.SubElementNames:
            holder = obj
            for part in sub.split(".")[:-1]:
                found = doc.getObject(part)
                if found is not None:
                    holder = found
            element = sub.split(".")[-1]
            if element.startswith("Face"):
                picks.append((_solid_of(holder), element))
    if not picks:
        return None, ()
    source = picks[0][0]
    if len(picks) == 2 and picks[1][0] is source:
        return source, ["%s,%s" % (picks[0][1], picks[1][1])]
    return source, ()


class Command:
    def GetResources(self):
        return {"MenuText": TITLE, "Pixmap": "Part_Offset",
                "ToolTip": "The surface halfway between facing faces of a thin solid."}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        source, pairs = _preselected()
        make(source=source, pairs=pairs)


def register():
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, Command())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Mid-Surface command not added (%s)\n" % error)
