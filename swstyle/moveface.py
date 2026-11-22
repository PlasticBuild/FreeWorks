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
import Part
from PySide import QtCore, QtWidgets

from . import pickguard
from . import naming
from . import simplefeature as sf

TYPE = "PartDesign::FeatureAdditivePython"
COMMAND = "SWStyle_MoveFace"
ICON = "FEATURES_MOVE_FACE"
MODES = ["Offset", "Translate", "Rotate"]
V = App.Vector


def _outside(base, tool):
    try:
        return base.common(tool, 1e-6).Volume < 0.5 * tool.Volume
    except Exception:
        return not base.isInside(tool.CenterOfMass, 1e-6, False)


def axis_of(link):
    """(point, direction) of a picked straight edge, axis or cylindrical face, else None."""
    if not link:
        return None
    src, subs = link
    sub = subs[0] if subs else ""
    if src.isDerivedFrom("App::Line") or src.TypeId == "PartDesign::Line":
        return src.Placement.Base, src.Placement.Rotation.multVec(V(1, 0, 0) if src.isDerivedFrom("App::Line") else V(0, 0, 1))
    try:
        el = src.Shape.getElement(sub)
    except Exception:
        return None
    if el.ShapeType == "Edge" and type(el.Curve).__name__ in ("Line", "LineSegment"):
        a, b = el.Vertexes[0].Point, el.Vertexes[-1].Point
        return a, (b - a)
    if el.ShapeType == "Edge" and type(el.Curve).__name__ == "Circle":
        return el.Curve.Center, el.Curve.Axis
    if el.ShapeType == "Face" and type(el.Surface).__name__ == "Cylinder":
        return el.Surface.Center, el.Surface.Axis
    return None


def slab(base, face, mode, distance=0.0, delta=V(0, 0, 0), axis=None, angle=0.0):
    """(tool, add) for one face: the solid between the face and where it moves to."""
    if mode == "Rotate":
        if axis is None or abs(angle) < 1e-9:
            return None, True
        tool = face.revolve(axis[0], axis[1], angle)       # the wedge the face sweeps as it turns
        if tool.ShapeType != "Solid" and tool.Solids:
            tool = tool.Solids[0]
        return tool, _outside(base, tool)
    if mode == "Offset":
        if abs(distance) < 1e-9:
            return None, True
        grow = distance > 0
        tool = face.makeOffsetShape(abs(distance), 1e-6, False, False, 0, 0, True)
        if _outside(base, tool) != grow:
            tool = face.makeOffsetShape(-abs(distance), 1e-6, False, False, 0, 0, True)
        return tool, grow
    if delta.Length < 1e-9:
        return None, True
    tool = face.extrude(delta)
    return tool, _outside(base, tool)


def _tube(face):
    """(plug solid, its axis) when face is a whole cylinder (a hole wall or a round boss), else None."""
    import math
    surf = face.Surface
    if type(surf).__name__ != "Cylinder":
        return None
    u0, u1, _v0, _v1 = face.ParameterRange
    if abs((u1 - u0) - 2 * math.pi) > 1e-6:
        return None
    d = App.Vector(surf.Axis).normalize()
    ts = [(v.Point - surf.Center).dot(d) for v in face.Vertexes] or [0.0]
    lo, hi = min(ts), max(ts)
    if hi - lo < 1e-9:
        return None
    return Part.makeCylinder(surf.Radius, hi - lo, surf.Center + d * lo, d)


def _rigid(base, face, mode, delta, axis, angle):
    ""
    plug = _tube(face)
    if plug is None:
        return None
    to = plug.copy()
    if mode == "Translate":
        if delta.Length < 1e-9:
            return [], []
        to.translate(delta)
    else:
        if axis is None or abs(angle) < 1e-9:
            return [], []
        to.rotate(axis[0], axis[1], angle)
    hole = not base.isInside(plug.CenterOfMass, 1e-6, False)
    left = plug.cut(to)        # the old place, less where the new one overlaps it
    return ([left], [to]) if hole else ([to], [left])


def _turned_plane(base, face, axis, angle):
    """Rotate a flat face: the faces round it carry on to meet it where it turns out, and are cut
    short where it turns in (the region between the face's old and new planes, over the face)."""
    n = App.Vector(face.normalAt(*face.Surface.parameter(face.CenterOfMass))).normalize()
    rot = App.Rotation(App.Vector(axis[1]).normalize(), angle)
    centre = face.CenterOfMass
    c1 = axis[0] + rot.multVec(centre - axis[0])
    n1 = rot.multVec(n)
    size = base.BoundBox.DiagonalLength * 4 + 10
    inner = Part.makeBox(size, size, size, V(-size / 2, -size / 2, -size))
    inner.Placement = App.Placement(c1, App.Rotation(V(0, 0, 1), n1)).multiply(inner.Placement)
    outer = Part.makeBox(size, size, size, V(-size / 2, -size / 2, 0))
    outer.Placement = App.Placement(c1, App.Rotation(V(0, 0, 1), n1)).multiply(outer.Placement)
    adds = face.extrude(n * size).common(inner)
    cuts = face.extrude(n * -size).common(outer)
    return ([adds] if adds.Volume > 1e-9 else []), ([cuts] if cuts.Volume > 1e-9 else [])


def moved(base, faces, mode, distance=0.0, delta=V(0, 0, 0), axis=None, angle=0.0):
    adds, cuts = [], []
    for face in faces:
        if mode in ("Translate", "Rotate"):
            got = _rigid(base, face, mode, delta, axis, angle)
            if got is None and mode == "Rotate" and type(face.Surface).__name__ == "Plane" and axis is not None \
                    and abs(angle) > 1e-9:
                got = _turned_plane(base, face, axis, angle)
            if got is not None:
                adds += got[0]
                cuts += got[1]
                continue
        tool, add = slab(base, face, mode, distance, delta, axis, angle)
        if tool is None or tool.isNull() or tool.Volume < 1e-9:
            continue
        (adds if add else cuts).append(tool)
    result = base
    if adds:
        result = result.fuse(adds, 1e-6)
    if cuts:
        result = result.cut(cuts, 1e-6)
    try:
        result = result.removeSplitter()
    except Exception as _fw_err:
        _fw_log("moveface.py:170", _fw_err)
    if not result.isValid() or not result.Solids:
        raise RuntimeError("The faces could not be moved this far")
    return result, adds + cuts


class MoveFaceFeature:
    def __init__(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def setup(self, obj):
        def add(kind, name, tip):
            if name not in obj.PropertiesList:
                obj.addProperty(kind, name, "Move Face", tip)
        add("App::PropertyLinkSub", "Faces", "Faces to move")
        add("App::PropertyEnumeration", "Mode", "Offset along each face's normal, or Translate by Delta X/Y/Z")
        add("App::PropertyDistance", "Distance", "Offset distance (positive moves the face out of the material)")
        add("App::PropertyBool", "Reverse", "Offset the other way")
        add("App::PropertyVector", "Delta", "Translate by this vector")
        add("App::PropertyLinkSub", "Axis", "Rotate: the axis (an edge, axis or cylindrical face)")
        add("App::PropertyAngle", "Angle", "Rotate: the angle")
        current = getattr(obj, "Mode", None)
        obj.Mode = MODES
        if current in MODES:
            obj.Mode = current
        if float(obj.Distance) == 0 and obj.Delta.Length == 0:
            obj.Distance = 5.0

    def execute(self, obj):
        base = obj.BaseFeature.Shape if obj.BaseFeature is not None else None
        if base is None or base.isNull():
            raise RuntimeError("Move Face needs a part")
        if obj.Faces is None or not obj.Faces[1]:
            sf.store(obj, base)
            return
        source, subs = obj.Faces
        faces = [source.Shape.getElement(sub) for sub in subs if sub.startswith("Face")]
        distance = -float(obj.Distance) if obj.Reverse else float(obj.Distance)
        axis = axis_of(obj.Axis) if obj.Mode == "Rotate" else None
        if obj.Mode == "Rotate" and axis is None:
            raise RuntimeError("Pick the axis to rotate about: an edge, an axis or a cylindrical face")
        angle = float(obj.Angle) * (-1 if obj.Reverse else 1)
        result, tools = moved(base, faces, obj.Mode, distance, obj.Delta, axis, angle)
        solids = result.Solids
        sf.store(obj, solids[0] if len(solids) == 1 else Part.makeCompound(solids),
                 Part.makeCompound(tools) if tools else None)

    def onDocumentRestored(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


class MoveFaceView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        try:
            from . import icons
            icon = icons.family(ICON)
            if not icon.isNull():
                return icon         # a QIcon: FreeCAD reads a returned QPixmap as a QIcon
        except Exception as _fw_err:
            _fw_log("moveface.py:243", _fw_err)
        return ":/icons/Part_Offset.svg"

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        Gui.Control.showDialog(MoveFacePanel(vobj.Object))
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


class MoveFacePanel:
    """The Move Face PropertyManager."""

    def __init__(self, obj):
        self.obj = obj
        self.box = QtWidgets.QWidget()
        self.box.setWindowTitle("Move Face")
        self.box.setProperty("swstyle_pm_title", "Move Face")
        self.box.setProperty("swstyle_pm_icon", ICON)
        form = QtWidgets.QFormLayout(self.box)
        self.offset = QtWidgets.QRadioButton("Offset")
        self.translate = QtWidgets.QRadioButton("Translate")
        self.rotate = QtWidgets.QRadioButton("Rotate")
        {"Translate": self.translate, "Rotate": self.rotate}.get(obj.Mode, self.offset).setChecked(True)
        row = QtWidgets.QVBoxLayout()           # one under the other: the page fits the 300 px pane (look audit AO2)
        row.addWidget(self.offset)
        row.addWidget(self.translate)
        row.addWidget(self.rotate)
        form.addRow(row)
        self.faces = QtWidgets.QListWidget()
        self.faces.setMaximumHeight(64)
        self.faces.setToolTip("Faces to move: pick them in the graphics area (pick again to remove)")
        form.addRow(self.faces)
        self.distance = self._spin(abs(float(obj.Distance)))
        form.addRow("Distance", self.distance)
        self.reverse = QtWidgets.QCheckBox("Reverse direction")
        self.reverse.setChecked(obj.Reverse or float(obj.Distance) < 0)
        form.addRow(self.reverse)
        self.axis = QtWidgets.QListWidget()
        self.axis.setObjectName("SWMoveFaceAxis")
        self.axis.setMaximumHeight(26)
        self.axis.setToolTip("Axis: pick an edge, an axis or a cylindrical face (Ctrl+pick when the faces box is filling)")
        form.addRow("Axis", self.axis)
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setObjectName("SWMoveFaceAngle")
        self.angle.setRange(0.0, 360.0)
        self.angle.setDecimals(2)
        self.angle.setSuffix(" °")
        self.angle.setValue(abs(float(obj.Angle)) or 10.0)
        form.addRow("Angle", self.angle)
        self.dx, self.dy, self.dz = (self._spin(value, -100000.0) for value in (obj.Delta.x, obj.Delta.y, obj.Delta.z))
        self.delta_rows = []
        for label, spin in (("Delta X", self.dx), ("Delta Y", self.dy), ("Delta Z", self.dz)):
            form.addRow(label, spin)
            self.delta_rows.append((form.labelForField(spin), spin))
        self.error = QtWidgets.QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c00000;")
        form.addRow(self.error)
        self.form = self.box
        for spin in (self.distance, self.dx, self.dy, self.dz, self.angle):
            spin.valueChanged.connect(self._changed)
        self.reverse.toggled.connect(self._changed)
        self.translate.toggled.connect(self._changed)
        self.rotate.toggled.connect(self._changed)
        self._show()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)
        try:
            # Faces to move: a click by a face's edge stays on the face (not while a Rotate still waits
            # for its axis, which may be an edge)
            from . import facehover
            facehover.faces_only(self, lambda me: me.box.isVisible() and not (me.obj.Mode == "Rotate" and not me.obj.Axis))
        except Exception:
            pass

    def _spin(self, value, low=0.0):
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(low, 100000.0)
        spin.setDecimals(2)
        spin.setSuffix(" mm")
        spin.setValue(float(value))
        return spin

    def addSelection(self, doc, name, sub, point):
        if pickguard.stale(self, self.obj):
            return
        if doc != self.obj.Document.Name:
            return
        face = sub.split(".")[-1]
        rotate = self.obj.Mode == "Rotate"
        if rotate and (not face.startswith("Face") or not self.obj.Axis):
            target = App.getDocument(doc).getObject(name)
            if face.startswith("Face") or face.startswith("Edge") or (target is not None and (
                    target.isDerivedFrom("App::Line") or target.TypeId == "PartDesign::Line")):
                if not face.startswith("Face") or self._cylinder(face):
                    QtCore.QTimer.singleShot(0, lambda: self.set_axis(name, face, doc))
                    return
        if face.startswith("Face"):
            QtCore.QTimer.singleShot(0, lambda: self.toggle(face))

    def _cylinder(self, face):
        try:
            return type(self.obj.BaseFeature.Shape.getElement(face).Surface).__name__ == "Cylinder"
        except Exception:
            return False

    def set_axis(self, name, sub, doc=None):
        target = App.getDocument(doc or self.obj.Document.Name).getObject(name)
        if target is None or target.TypeId == "PartDesign::Body":
            target = self.obj.BaseFeature
        if target is None:
            return
        self.obj.Axis = (target, [sub] if sub else [])
        Gui.Selection.clearSelection()
        self._changed()

    def toggle(self, face):
        source = self.obj.BaseFeature
        if source is None:
            return
        subs = list(self.obj.Faces[1]) if self.obj.Faces is not None else []
        if face in subs:
            subs.remove(face)
        else:
            subs.append(face)
        self.obj.Faces = (source, subs) if subs else None
        Gui.Selection.clearSelection()
        self._changed()

    def _changed(self, *args):
        obj = self.obj
        obj.Mode = "Rotate" if self.rotate.isChecked() else "Translate" if self.translate.isChecked() else "Offset"
        obj.Angle = self.angle.value()
        obj.Distance = self.distance.value()
        obj.Reverse = self.reverse.isChecked()
        obj.Delta = V(self.dx.value(), self.dy.value(), self.dz.value())
        obj.Document.recompute()
        self._show()

    def _show(self):
        obj = self.obj
        self.faces.clear()
        if obj.Faces is not None:
            self.faces.addItems(list(obj.Faces[1]))
        offset, rotate = obj.Mode == "Offset", obj.Mode == "Rotate"
        lay = self.box.layout()
        for widget in (self.distance, lay.labelForField(self.distance)):
            widget.setVisible(offset)
        self.reverse.setVisible(offset or rotate)
        for widget in (self.axis, lay.labelForField(self.axis), self.angle, lay.labelForField(self.angle)):
            widget.setVisible(rotate)
        self.axis.clear()
        if obj.Axis:
            self.axis.addItem("%s %s" % (obj.Axis[0].Label, ",".join(obj.Axis[1])))
        for label, spin in self.delta_rows:
            label.setVisible(obj.Mode == "Translate")
            spin.setVisible(obj.Mode == "Translate")
        bad = "Invalid" in obj.State
        self.error.setText(obj.getStatusString() if bad else "")
        self.error.setVisible(bad)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("moveface.py:419", _fw_err)
        Gui.ActiveDocument.resetEdit()
        Gui.Control.closeDialog()

    def accept(self):
        doc = self.obj.Document
        doc.recompute()
        if "Invalid" in self.obj.State or self.obj.Faces is None:
            self.error.setText(self.obj.getStatusString() if "Invalid" in self.obj.State else "Pick the faces to move")
            self.error.setVisible(True)
            return False
        doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        doc.abortTransaction()
        doc.recompute()
        self._close()
        return True


def _body(doc):
    try:
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
    except Exception:
        body = None
    if body is None:
        bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
        body = bodies[0] if len(bodies) == 1 else None
    return body


def make(doc=None, faces=None):
    """A Move Face in the active body with its PropertyManager open; faces = ["Face3", ...] of the tip."""
    doc = doc or App.ActiveDocument
    body = _body(doc) if doc is not None else None
    if body is None or body.Tip is None:
        App.Console.PrintWarning("FreeCAD: Move Face needs a body with a solid\n")
        return None
    doc.openTransaction("Move Face")
    try:
        obj = body.newObject(TYPE, "MoveFace")
        MoveFaceFeature(obj)
        if Gui.ActiveDocument is not None:
            MoveFaceView(obj.ViewObject)
        obj.Label = naming.next_label(doc, "Move Face")
        if faces:
            obj.Faces = (obj.BaseFeature, list(faces))
        doc.recompute()
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(obj.Name)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    return obj


def _picked_faces():
    out = []
    for sel in Gui.Selection.getSelectionEx():
        out += [sub.split(".")[-1] for sub in sel.SubElementNames if sub.split(".")[-1].startswith("Face")]
    return out


class _Command:
    def GetResources(self):
        return {"MenuText": "Move Face",
                "ToolTip": "Offsets or translates faces of the part; the faces around them follow.",
                "Pixmap": "Part_Offset"}

    def IsActive(self):
        doc = App.ActiveDocument
        if doc is None or Gui.Control.activeDialog():
            return False
        from . import simplefeature as _sf
        body = _sf.body_of(doc)
        return body is not None and _sf.has_solid(body)

    def Activated(self):
        make(faces=_picked_faces())


def register():
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, _Command())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Move Face command not added (%s)\n" % error)
