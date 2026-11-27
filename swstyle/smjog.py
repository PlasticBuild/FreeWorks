# SPDX-License-Identifier: LGPL-2.1-or-later
""













from . import editobj

_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import math
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import naming, paths, smallowance, smbaseflange, smflatten
from . import smlive
from . import pmboxes
from .smbaseflange import ALLOWANCES, _active_body, _box, _spin
from .smedgeflange import _radio, _root, error_label
from .smsketchedbend import POSITIONS, _line_face, _sheet_under

COMMAND = "SWStyle_SMJog"
TITLE = "Jog"
LABEL = "Jog"
DIMENSIONS = (("Outside offset", "Outside"), ("Inside offset", "Inside"), ("Overall dimension", "Overall"))
END_CONDITIONS = ("Blind", "Up To Vertex", "Up To Surface", "Offset From Surface")
PICK_MESSAGE = "Select a face of the sheet on which to sketch the jog line, or an existing sketch."
GROUP = "Jog"


class _Stub:
    """What smFold reads from its objects: a shape and a name."""

    def __init__(self, shape):
        self.Shape, self.Label, self.Name = shape, "Jog", "SWJogStub"


def _fold(shape, face, line, angle, radius, k, position, flipped, invert):
    import SheetMetalFoldCmd
    return SheetMetalFoldCmd.smFold(bendR=radius, bendA=angle, kfactor=k, invertbend=invert, flipped=flipped,
                                    position=position, bendlinesketch=_Stub(line), selFaceNames=[face],
                                    MainObject=_Stub(shape))


def _holds(shape, point):
    return shape is not None and not shape.isNull() and shape.distToShape(Part.Vertex(point))[0] < 1e-3


def _shares_edge(f, g):
    return any(e.isSame(x) for e in f.Edges for x in g.Edges)


def _plane(face):
    return face.Surface.TypeId == "Part::GeomPlane"


def _cylinders(shape, axis):
    return [f for f in shape.Faces if f.Surface.TypeId == "Part::GeomCylinder"
            and abs(abs(f.Surface.Axis.dot(axis)) - 1) < 1e-7]


def _new_bend(before, after, axis):
    """The cylinder faces of the bend that the fold made."""
    old = [(f.Surface.Center, f.Surface.Radius) for f in _cylinders(before, axis)]

    def known(f):
        c, r = f.Surface.Center, f.Surface.Radius
        for oc, orad in old:
            d = c - oc
            if abs(r - orad) < 1e-6 and (d - axis * d.dot(axis)).Length < 1e-6:
                return True
        return False
    return [f for f in _cylinders(after, axis) if not known(f)]


def _second_line(before, shape, normal, height, axis, s):
    """The second bend line: on the bent flange's face on the sketch side, s from the bend."""
    bend = _new_bend(before, shape, axis)
    faces = shape.Faces
    for c in bend:
        fixed = [f for f in faces if _plane(f) and abs(f.normalAt(0, 0).dot(normal) - 1) < 1e-7
                 and abs(f.CenterOfMass.dot(normal) - height) < 1e-6 and _shares_edge(f, c)]
        if not fixed:
            continue
        moved = [(i, f) for i, f in enumerate(faces, 1) if _plane(f) and not fixed[0].isSame(f) and _shares_edge(f, c)]
        if not moved:
            continue
        index, face = moved[0]
        edge = next(e for e in face.Edges for x in c.Edges if e.isSame(x))
        n = face.normalAt(0, 0)
        u = n.cross(axis).normalize()
        mid = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
        if not face.isInside(mid + u * 0.01, 1e-6, True):
            u = -u
        a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
        d = (b - a).normalize()
        ext = 0.1 * edge.Length + 1.0
        line = Part.LineSegment(a - d * ext + u * s, b + d * ext + u * s).toShape()
        return "Face%d" % index, line, n
    return None, None, None


def _far_height(shape, normal, height, mid=None, along=None):
    """The height of the sheet past the jog. With mid and along: the moved face nearest the jog line
    on the moving side, so a flange or a sketched-bend lip standing further on (its end face is
    parallel too, and higher) is not taken for the jogged sheet."""
    faces = [f for f in shape.Faces if _plane(f) and abs(f.normalAt(0, 0).dot(normal) - 1) < 1e-7]
    if mid is not None and along is not None:
        moved = [f for f in faces if abs(f.CenterOfMass.dot(normal) - height) > 1e-6
                 and (f.CenterOfMass - mid).dot(along) > 0]
        if moved:
            return min(moved, key=lambda f: (f.CenterOfMass - mid).dot(along)).CenterOfMass.dot(normal)
    hs = [f.CenterOfMass.dot(normal) for f in faces]
    return max(hs, key=lambda h: abs(h - height)) if hs else height


def _insert(shape, face_name, line, along, amount):
    """The shape with amount of sheet added at the line, the far side moved along (Fix projected
    length)."""
    import BOPTools.SplitAPI
    mid = line.valueAt((line.FirstParameter + line.LastParameter) / 2)
    size = 4 * shape.BoundBox.DiagonalLength + 10
    plane = Part.makePlane(size, size, App.Vector(-size / 2, -size / 2, 0))
    rot = App.Rotation(App.Vector(0, 0, 1), along)
    plane.Placement = App.Placement(mid, rot)
    pieces = BOPTools.SplitAPI.slice(shape, [plane], "Split")
    near, far = [], []
    for solid in pieces.Solids:
        (far if (solid.CenterOfMass - mid).dot(along) > 0 else near).append(solid)
    if not near or not far:
        return None
    fills = []
    for solid in near:
        for f in solid.Faces:
            if _plane(f) and abs(f.normalAt(0, 0).dot(along) - 1) < 1e-7 and abs((f.CenterOfMass - mid).dot(along)) < 1e-6:
                fills.append(f.extrude(along * amount))
    moved = [s.translated(along * amount) for s in far]
    out = near[0].multiFuse(near[1:] + fills + moved).removeSplitter()
    return out


def jog_shape(shape, face_name, line, fixed_point, angle, radius, k, position, reverse, offset, dimension,
              fix_projected):
    import SheetMetalTools
    face = shape.getElement(face_name)
    normal = face.normalAt(0, 0)
    height = face.CenterOfMass.dot(normal)
    thk = SheetMetalTools.smGetThickness(shape, face)
    a = (line.Vertexes[-1].Point - line.Vertexes[0].Point).normalize()
    mid = line.valueAt((line.FirstParameter + line.LastParameter) / 2)
    along = a.cross(normal).normalize()
    if (fixed_point - mid).dot(along) > 0:
        along = -along                      # toward the side that moves
    target = offset + {"Outside": 0.0, "Inside": thk, "Overall": -thk}[dimension]
    if target <= 0:
        raise ValueError("Jog offset is smaller than the sheet thickness")
    sine = math.sin(math.radians(angle))

    choice = {}             # which side moves and which way the second fold goes: found once

    def build(base, s):
        r1 = choice.get("r1")
        if r1 is None:
            for invert in (False, True):
                r1 = _fold(base, face_of(base), line, angle, radius, k, position, reverse, invert)
                if _holds(r1, fixed_point):
                    break
            choice["r1"] = r1           # the first fold doesn't depend on s
        face2, line2, _n2 = _second_line(base, r1, normal, height, a, s)
        if face2 is None:
            raise ValueError("Jog: the second bend was not found")
        combos = [choice["second"]] if "second" in choice else \
            [(flipped, invert) for flipped in (not reverse, reverse) for invert in (False, True)]
        for flipped, invert in combos:
            r2 = _fold(r1, face2, line2, angle, radius, k, "middle", flipped, invert)
            if not _holds(r2, fixed_point):
                continue
            # a Z, not a U: the far part is parallel again and carries on past the jog
            if any(_plane(f) and abs(f.normalAt(0, 0).dot(normal) - 1) < 1e-7
                   and abs(f.CenterOfMass.dot(normal) - height) > 1e-6
                   and (f.CenterOfMass - mid).dot(along) > 0 for f in r2.Faces):
                choice["second"] = (flipped, invert)
                return r2
        raise ValueError("Jog: the second bend did not bring the sheet back parallel")

    def face_of(base):
        """The face holding the jog line (renumbered once Fix projected length adds material)."""
        if base is shape:
            return face_name
        for i, f in enumerate(base.Faces, 1):
            if _plane(f) and abs(f.normalAt(0, 0).dot(normal) - 1) < 1e-7 \
                    and abs(f.CenterOfMass.dot(normal) - height) < 1e-6 and f.isInside(mid, 1e-6, True):
                return "Face%d" % i
        return face_name

    def measured(result):
        return abs(_far_height(result, normal, height, mid, along) - height)

    def far_end(result):
        return max(v.Point.dot(along) for v in result.Vertexes)

    # The offset and the length the jog uses both grow linearly with s (the second line's
    # distance from the first bend): one build measures them, a second one is exact.
    s = max(target / sine - radius, 0.1)
    result = build(shape, s)
    d = measured(result)
    used = far_end(shape) - far_end(result)
    step = (target - d) / sine
    s += step
    if s <= 0:
        raise ValueError("Jog offset is too small for the bend radius")
    used += step * (1 - math.cos(math.radians(angle)))
    base = shape
    if fix_projected and used > 1e-6:
        longer = _insert(shape, face_name, line, along, used)
        if longer is not None:
            base = longer
            choice.clear()          # the longer sheet splits in another order
    if abs(step) > 1e-7 or base is not shape:
        result = build(base, s)
    if abs(measured(result) - target) > 1e-4:
        s += (target - measured(result)) / sine
        result = build(base, s)
    return result


# ---------------------------------------------------------------- end conditions
def _end_props(obj):
    if "EndCondition" not in obj.PropertiesList:
        obj.addProperty("App::PropertyEnumeration", "EndCondition", GROUP, "Jog Offset end condition")
        obj.EndCondition = list(END_CONDITIONS)
    if "EndReference" not in obj.PropertiesList:
        obj.addProperty("App::PropertyLinkSub", "EndReference", GROUP, "Vertex or face the jog goes up to")


def end_offset(obj, shape, face_name):
    """The offset and direction Up To Vertex, Up To Surface or Offset From Surface give: the jogged sheet's
    face that faces the same way as the jog line's face lands on the vertex or surface (or the offset
    distance past the surface)."""
    import SheetMetalTools
    ref = obj.EndReference
    plane = ref is not None and ref[0] is not None and "Plane" in ref[0].TypeId
    if ref is None or ref[0] is None or not (plane or (ref[1] and ref[1][0])):
        raise ValueError("Jog: pick the %s for %s." % (
            "vertex" if obj.EndCondition == "Up To Vertex" else "surface", obj.EndCondition))
    face = shape.getElement(face_name)
    normal = face.normalAt(0, 0)
    height = face.CenterOfMass.dot(normal)
    item = ref[0].Shape.Faces[0] if plane and not (ref[1] and ref[1][0]) else ref[0].Shape.getElement(ref[1][0])
    if obj.EndCondition == "Up To Vertex":
        level = item.Point.dot(normal)
    else:
        if not _plane(item) or abs(abs(item.normalAt(0, 0).dot(normal)) - 1) > 1e-7:
            raise ValueError("Jog: the surface must be a flat face parallel to the sheet.")
        level = item.CenterOfMass.dot(normal)
    h = level - height
    if obj.EndCondition == "Offset From Surface":
        h += obj.Offset.Value * (-1.0 if obj.Reverse else 1.0)
    thk = SheetMetalTools.smGetThickness(shape, face)
    offset = abs(h) - {"Outside": 0.0, "Inside": thk, "Overall": -thk}[obj.Dimension]
    if abs(h) < 1e-7:
        raise ValueError("Jog: the vertex or surface is level with the sheet.")
    return offset, h < 0


# ---------------------------------------------------------------- feature
class SWJog:
    def __init__(self, obj, base, face, sketch):
        add = obj.addProperty
        add("App::PropertyLinkSub", "baseObject", GROUP, "The sheet and the face that holds the jog line")
        add("App::PropertyLink", "BendLine", GROUP, "Sketch with the jog line")
        add("App::PropertyVector", "FixedPoint", GROUP, "A point on the fixed face")
        add("App::PropertyString", "FixedFace", GROUP, "Fixed face as picked")
        add("App::PropertyLength", "Offset", GROUP, "Jog offset")
        add("App::PropertyEnumeration", "Dimension", GROUP, "How the offset is measured")
        add("App::PropertyBool", "Reverse", GROUP, "Jog the other way")
        add("App::PropertyBool", "FixProjectedLength", GROUP, "Add the material the jog uses")
        add("App::PropertyEnumeration", "Position", GROUP, "Jog position")
        add("App::PropertyAngle", "Angle", GROUP, "Jog angle")
        add("App::PropertyLength", "Radius", GROUP, "Bend radius")
        add("App::PropertyFloat", "KFactor", GROUP, "K-Factor")
        _end_props(obj)
        obj.Dimension = [v for _t, v in DIMENSIONS]
        obj.Position = [v for _t, v in POSITIONS]
        obj.baseObject = (base, [face])
        obj.BendLine = sketch
        obj.Offset = 10.0
        obj.Angle = 90.0
        obj.FixProjectedLength = True
        obj.Position = "middle"
        obj.Proxy = self

    def execute(self, obj):
        base, subs = obj.baseObject
        sketch = obj.BendLine
        if base is None or not subs or sketch is None or not sketch.Shape.Edges:
            raise ValueError("Jog: needs a sketch line on a face of the sheet")
        line = sketch.Shape.Edges[0]
        offset, reverse = obj.Offset.Value, obj.Reverse
        if getattr(obj, "EndCondition", "Blind") != "Blind":
            offset, reverse = end_offset(obj, base.Shape, subs[0])
        obj.Shape = jog_shape(base.Shape, subs[0], line, obj.FixedPoint, obj.Angle.Value, obj.Radius.Value,
                              obj.KFactor, obj.Position, reverse, offset, obj.Dimension,
                              obj.FixProjectedLength)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderJog:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        try:
            import SheetMetalTools
            return os.path.join(SheetMetalTools.icons_path, "SheetMetal_AddFoldWall.svg")
        except Exception:
            return ""

    def claimChildren(self):
        return [self.Object.BendLine] if self.Object.BendLine is not None else []

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


def is_jog(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWJog"


def make(base, face, sketch, at, recompute=True):
    doc = base.Document
    body = next((p for p in base.InList if p.TypeId == "PartDesign::Body"), None) or _active_body(doc)
    doc.openTransaction(TITLE)
    try:
        obj = doc.addObject("PartDesign::FeaturePython", "Jog")
        SWJog(obj, base, face, sketch)
        if App.GuiUp:
            ViewProviderJog(obj.ViewObject)
        if body is not None:
            body.addObject(obj)
        root = _root(base)
        obj.Radius = root.Radius.Value if root is not None and hasattr(root, "Radius") else 1.0
        obj.KFactor = getattr(root, "SWKFactor", 0.5) if root is not None else 0.5
        obj.FixedPoint = at
        obj.Label = naming.next_label(doc, LABEL)
        for o in (base, sketch):
            try:
                o.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("smjog.py:387", _fw_err)
        if recompute:
            doc.recompute()
        return obj
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise


# ---------------------------------------------------------------- PropertyManager
class Panel:
    """The Jog PropertyManager; obj is None until the Fixed face is picked."""

    def __init__(self, obj, new, sketch=None):
        self.obj = obj
        self.new = new
        self.sketch = obj.BendLine if obj is not None else sketch
        self.base = obj.baseObject[0] if obj is not None else _sheet_under(self.sketch)
        self.busy = True
        root = _root(self.base) if self.base is not None else None
        self.root_radius = root.Radius.Value if root is not None and hasattr(root, "Radius") else None
        self.root_k = getattr(root, "SWKFactor", 0.5) if root is not None else 0.5

        selections = _box("Selections")
        f = selections.layout()
        self.face = QtWidgets.QListWidget()
        self.face.setObjectName("SWSMJogFixedFace")
        self.face.setMaximumHeight(40)
        self.face.setToolTip("Fixed face: the side of the sheet that stays where it is")
        pmboxes.mark(self.face, True)

        pmboxes.bind(self.face, remove=lambda row: self._drop_face(), clear=self._drop_face)
        f.addRow(self.face)
        self.default_radius = QtWidgets.QCheckBox("Use default radius")
        self.default_radius.setObjectName("SWSMDefaultRadius")
        radius = obj.Radius.Value if obj else (self.root_radius or 1.0)
        self.radius = _spin("SWSMRadius", radius, 0.0, 10000.0)
        self.radius.setToolTip("Bend radius")
        self.default_radius.setChecked(self.root_radius is None or abs(radius - self.root_radius) < 1e-9)
        f.addRow(self.default_radius)
        f.addRow(self.radius)
        self.error = error_label()
        f.addRow(self.error)

        offset_box = _box("Jog Offset")
        f = offset_box.layout()
        row = QtWidgets.QHBoxLayout()
        self.reverse = QtWidgets.QCheckBox("")
        self.reverse.setObjectName("SWSMJogReverse")
        self.reverse.setToolTip("Reverse Direction")
        from . import pmvalues
        self.reverse.setIcon(pmvalues.reverse_icon())
        self.reverse.setChecked(bool(obj.Reverse) if obj else False)
        self.end = QtWidgets.QComboBox()
        self.end.setObjectName("SWSMJogEnd")
        self.end.addItems(END_CONDITIONS)
        self.end.setCurrentText(getattr(obj, "EndCondition", "Blind") if obj is not None else "Blind")
        row.addWidget(self.reverse)
        row.addWidget(self.end, 1)
        f.addRow(row)
        self.end_ref = QtWidgets.QListWidget()
        self.end_ref.setObjectName("SWSMJogEndRef")
        self.end_ref.setMaximumHeight(28)
        self.end_ref.setStyleSheet("QListWidget { background: #ffd6ec; }")
        self.end_ref.setToolTip("The vertex or face the jog goes up to")
        ref = getattr(obj, "EndReference", None) if obj is not None else None
        if ref is not None and ref[0] is not None:
            self.end_ref.addItem("%s of %s" % (ref[1][0], ref[0].Label) if ref[1] and ref[1][0] else ref[0].Label)
        f.addRow(self.end_ref)
        self.offset = _spin("SWSMJogOffset", obj.Offset.Value if obj else 10.0, 0.01, 100000.0)
        self.offset.setToolTip("Offset Distance")
        f.addRow(self.offset)
        f.addRow(QtWidgets.QLabel("Dimension position:"))
        self.dimensions = QtWidgets.QButtonGroup(offset_box)
        current = obj.Dimension if obj else "Outside"
        for i, (text, value) in enumerate(DIMENSIONS):
            b = _radio("SWSMJogDim" + value, text)
            b.setChecked(value == current)
            self.dimensions.addButton(b, i)
            f.addRow(b)
        self.fix_length = QtWidgets.QCheckBox("Fix projected length")
        self.fix_length.setObjectName("SWSMJogFixLength")
        self.fix_length.setChecked(bool(obj.FixProjectedLength) if obj else True)
        f.addRow(self.fix_length)

        position_box = _box("Jog Position")
        f = position_box.layout()
        self.positions = QtWidgets.QButtonGroup(position_box)
        current = obj.Position if obj else "middle"
        for i, (text, value) in enumerate(POSITIONS):
            b = _radio("SWSMJogPosition" + text.replace(" ", ""), text)
            b.setChecked(value == current)
            self.positions.addButton(b, i)
            f.addRow(b)

        angle_box = _box("Jog Angle")
        self.angle = _spin("SWSMJogAngle", obj.Angle.Value if obj else 90.0, 0.01, 179.0, suffix=" deg")
        angle_box.layout().addRow(self.angle)

        allowance = _box("Custom Bend Allowance")
        f = allowance.layout()
        self.custom_k = QtWidgets.QCheckBox("Custom Bend Allowance")
        self.custom_k.setObjectName("SWSMCustomAllowance")
        self.allowance = QtWidgets.QComboBox()
        self.allowance.setObjectName("SWSMAllowance")
        self.allowance.addItems(ALLOWANCES)
        k = float(obj.KFactor) if obj is not None else self.root_k
        self.custom_k.setChecked(abs(k - self.root_k) > 1e-9)
        self.kfactor = _spin("SWSMKFactor", k, 0.0, 1.0, suffix="", decimals=4, step=0.05)
        f.addRow(self.custom_k)
        f.addRow(self.allowance)
        f.addRow("K", self.kfactor)
        self.custom = smallowance.CustomAllowance(self.allowance, self.kfactor, f, obj, self._changed)
        self.custom_k.setChecked(self.custom_k.isChecked() or self.custom.kind() != "K-Factor")

        selections.setProperty("swstyle_pm_title", TITLE)
        selections.setProperty("swstyle_pm_icon", "SheetMetal_AddFoldWall")
        self.form = [selections, offset_box, position_box, angle_box, allowance]
        if obj is not None:
            self.face.addItem(obj.FixedFace or obj.baseObject[1][0])
        else:
            self.error.setText("Please specify the planar face to be fixed when creating the bend.")
            self.error.show()
        smlive.live(self)          # before _changed: using a box turns its option on first
        for w in (self.angle, self.radius, self.kfactor, self.offset):
            w.valueChanged.connect(self._changed)
        for w in (self.reverse, self.default_radius, self.custom_k, self.fix_length):
            w.toggled.connect(self._changed)
        self.positions.buttonClicked.connect(self._changed)
        self.dimensions.buttonClicked.connect(self._changed)
        self.end.currentIndexChanged.connect(self._changed)
        self._show()
        self.busy = False
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    # ---------------------------------------------------------------- selection
    def _drop_face(self):
        self.face.clear()
        pmboxes.mark(self.face, True, need=True)       # OK waits for a fixed face again

    def addSelection(self, doc, name, sub, point):
        end = self.end.currentText()
        to_end = self.obj is not None and end != "Blind" and not self.face.hasFocus()
        obj = App.getDocument(doc).getObject(name)
        plane = not sub and obj is not None and "Plane" in obj.TypeId
        if to_end and (sub.startswith("Vertex") if end == "Up To Vertex" else (sub.startswith("Face") or plane)):
            from . import safe_later as _sl; _sl.later(0, lambda: self._picked_end(doc, name, sub), self, "end_ref")
        elif sub.startswith("Face"):
            at = App.Vector(*point) if point else None
            from . import safe_later as _sl; _sl.later(0, lambda: self._picked(doc, name, sub, at), self, "face")

    def _picked_end(self, doc_name, name, sub):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smjog.py:539", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None or self.obj is None:
            return
        if picked is self.obj and sub:  # a pick on the jog itself: the part's matching vertex or face before it
            item = picked.Shape.getElement(sub)
            sub, picked = None, self.base
            for i, x in enumerate(getattr(self.base.Shape, "Vertexes" if item.ShapeType == "Vertex" else "Faces"), 1):
                same = x.Point.distanceToPoint(item.Point) < 1e-6 if item.ShapeType == "Vertex" else (
                    abs(x.Area - item.Area) < 1e-6 and x.CenterOfMass.distanceToPoint(item.CenterOfMass) < 1e-6)
                if same:
                    sub = "%s%d" % (item.ShapeType, i)
                    break
            if sub is None:
                self.error.setText("Pick a vertex or face of the part before the jog.")
                self.error.show()
                return
        _end_props(self.obj)
        self.obj.EndReference = (picked, [sub])
        self.end_ref.clear()
        self.end_ref.addItem("%s of %s" % (sub, picked.Label) if sub else picked.Label)
        self._changed()

    def _picked(self, doc_name, name, sub, at=None):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smjog.py:566", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None:
            return
        base = self.base
        if base is None:
            base = self.base = picked
        face = picked.Shape.getElement(sub)
        if at is None:
            at = face.CenterOfMass
        line_face = _line_face(base, self.sketch)
        if line_face is None:
            self.error.setText("The jog line must be a sketch on a flat face of the sheet.")
            self.error.show()
            return
        self.face.clear()
        self.face.addItem(sub)
        pmboxes.mark(self.face, True)          # picked: no longer waiting
        if self.obj is None:
            self.obj = make(base, line_face, self.sketch, at, recompute=False)
            self.obj.FixedFace = sub
            self.busy = True
            self._changed_values()
            self.busy = False
        else:
            self.obj.FixedPoint = at
            self.obj.FixedFace = sub
            self.obj.Document.recompute()
        self._report()

    # ---------------------------------------------------------------- values
    def _show(self):
        end = self.end.currentText()
        self.end_ref.setVisible(end != "Blind")
        self.offset.setVisible(end in ("Blind", "Offset From Surface"))
        smlive.show(self)                  # nothing greyed: using a box turns its option on

    def _changed(self, *args):
        if self.busy:
            return
        self._changed_values()

    def _changed_values(self):
        if self.default_radius.isChecked() and self.root_radius is not None:
            busy, self.busy = self.busy, True
            self.radius.setValue(self.root_radius)
            self.busy = busy
        self._show()
        obj = self.obj
        if obj is None:
            return
        obj.Position = POSITIONS[max(0, self.positions.checkedId())][1]
        obj.Dimension = DIMENSIONS[max(0, self.dimensions.checkedId())][1]
        obj.Reverse = self.reverse.isChecked()
        obj.Offset = self.offset.value()
        _end_props(obj)
        if obj.EndCondition != self.end.currentText():
            if self.end.currentText() == "Blind" or obj.EndCondition == "Blind" or \
                    (obj.EndCondition == "Up To Vertex") != (self.end.currentText() == "Up To Vertex"):
                obj.EndReference = None         # a vertex doesn't do for a surface, nor the other way
                self.end_ref.clear()
            obj.EndCondition = self.end.currentText()
        obj.FixProjectedLength = self.fix_length.isChecked()
        obj.Angle = self.angle.value()
        obj.Radius = self.radius.value()
        obj.KFactor = smallowance.k_for(self, obj, self.angle.value()) if self.custom_k.isChecked() else self.root_k
        self.custom.save(obj)
        obj.Document.recompute()
        self._report()
        smallowance.report(self)

    def _report(self):
        if self.obj is None:
            self.error.setVisible(True)
            return False
        invalid = "Invalid" in self.obj.State
        self.error.setText(naming.status_text(self.obj, "The jog") if invalid else "")
        self.error.setVisible(invalid)
        return not invalid

    # ---------------------------------------------------------------- closing
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smjog.py:657", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smjog.py:663", _fw_err)

    def accept(self):
        self._changed()
        if not self._report():
            return False
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        if self.obj is not None:
            doc = self.obj.Document
            shown = (self.base, self.sketch) if self.new else ()
            doc.abortTransaction()
            doc.recompute()
            for o in shown:
                try:
                    o.ViewObject.Visibility = True
                except Exception as _fw_err:
                    _fw_log("smjog.py:683", _fw_err)
        self._close()
        return True


def open_on(sketch):
    Gui.Selection.clearSelection()
    Gui.Control.showDialog(Panel(None, True, sketch=sketch))


def start():
    doc = App.ActiveDocument
    if doc is None:
        return
    gdoc = Gui.ActiveDocument
    edit = gdoc.getInEdit() if gdoc is not None else None
    if edit is not None and editobj.type_id(edit) == "Sketcher::SketchObject":
        sketch = editobj.of(edit)
        Gui.runCommand("Sketcher_LeaveSketch", 0)
        if sketch.Geometry:
            QtCore.QTimer.singleShot(0, lambda: open_on(sketch))
        return
    picked = [s.Object for s in Gui.Selection.getSelectionEx()]
    sketches = [o for o in picked if o.TypeId == "Sketcher::SketchObject"]
    if len(sketches) == 1:
        open_on(sketches[0])
        return
    smbaseflange._pick_plane(doc, then=open_on, title=TITLE, icon="SheetMetal_AddFoldWall", message=PICK_MESSAGE)


class Command:
    def GetResources(self):
        try:
            import SheetMetalTools
            pixmap = os.path.join(SheetMetalTools.icons_path, "SheetMetal_AddFoldWall.svg")
        except Exception:
            pixmap = ""
        return {"Pixmap": pixmap, "MenuText": "Jog", "ToolTip": "Adds two bends from one sketch line, offsetting the sheet."}

    def IsActive(self):
        return smbaseflange.Command().IsActive()

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
