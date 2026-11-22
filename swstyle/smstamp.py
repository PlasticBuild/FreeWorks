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

import math

import FreeCAD as App
import FreeCADGui as Gui
import Part

from . import naming

COMMAND = "SWStyle_SMStamp"
TITLE = "Sheet Metal Stamp"
LABEL = "Stamp"
GROUP = "Stamp"
ICON = "SheetMetal_Forming"
V = App.Vector
PICK_MESSAGE = ("Select:\n1) a plane, a planar face or an edge on which to sketch the feature cross-section\n\nor\n\n"
                "2) an existing sketch to use for the feature.")
NOT_CLOSED = "The stamp sketch must hold closed outlines."
NOT_ON_FACE = "The stamp sketch must lie on a flat face of the sheet."


# ================================================================ geometry
def drafted(w0, w1):
    """The solid between outline w0 and its drafted copy w1; its sides are planes and cones."""
    faces = [Part.Face(w0), Part.Face(w1)]
    e0s, e1s = w0.OrderedEdges, w1.OrderedEdges
    if len(e0s) != len(e1s):
        raise ValueError("The draft angle is too big for the sketch.")
    for a, b in zip(e0s, e1s):
        if a.Curve.TypeId == "Part::GeomLine":
            pa, pb = a.Vertexes[0].Point, a.Vertexes[-1].Point
            qa = min((v.Point for v in b.Vertexes), key=lambda q: (q - pa).Length)
            qb = min((v.Point for v in b.Vertexes), key=lambda q: (q - pb).Length)
            faces.append(Part.Face(Part.makePolygon([pa, pb, qb, qa, pa])))
        else:
            faces.append(Part.makeLoft([Part.Wire(a), Part.Wire(b)], False, True).Faces[0])
    s = Part.Solid(Part.Shell(faces))
    if s.Volume < 0:
        s.reverse()
    return s


def _on(edge, wire, tol=1e-6):
    span = edge.LastParameter - edge.FirstParameter
    return all(wire.distToShape(Part.Vertex(edge.valueAt(edge.FirstParameter + k * span / 4)))[0] < tol
               for k in range(5))


def _end(f, n, at):
    return f.Surface.TypeId == "Part::GeomPlane" and abs(abs(f.normalAt(0, 0).dot(n)) - 1) < 1e-7 \
        and abs((f.CenterOfMass - at).dot(n)) < 1e-6


def stamp(sheet, wire, n, t, depth, reverse=False, draft=0.0, die_r=0.0, punch_r=0.0, corner_r=0.0):
    """sheet with the closed outline wire (on a face with outward normal n) pressed depth into it."""
    w0 = wire.copy()
    d = n * -1.0
    if reverse:
        # from the other side: the stamp stands up on the sketched side
        w0.translate(n * -t)
        d = V(n)
    if draft > 1e-9:
        w1 = w0.makeOffset2D(-depth * math.tan(math.radians(draft)), 2)
        w1.translate(d * depth)
        p = drafted(w0, w1)
    else:
        p = Part.Face(w0).extrude(d * depth)
    if p.Volume < 0:
        p.reverse()
    q0 = w0.Vertexes[0].Point
    q1 = q0 + d * depth
    try:
        if corner_r > 1e-9:
            sides = [e for e in p.Edges if not _end_edge(e, n, q0) and not _end_edge(e, n, q1)]
            if sides:
                p = p.makeFillet(corner_r, sides)
        if punch_r > 1e-9:
            bottom = next(f for f in p.Faces if _end(f, n, q1))
            p = p.makeFillet(punch_r, bottom.Edges)
    except Exception:
        raise ValueError("The punch radii are too big for the sketch.")
    top = next(f for f in p.Faces if _end(f, n, q0))
    skin = p.makeThickness([top], t, 1e-4, False, False, 0, 0)
    # only what lies past the mouth's plane: a drafted wall would reach out of the sheet
    size = sheet.BoundBox.DiagonalLength + depth + 10
    half = Part.makeBox(2 * size, 2 * size, size, V(-size, -size, 0))
    half.Placement = App.Placement(q0, App.Rotation(V(0, 0, 1), d))
    skin = skin.common(half)
    out = sheet.cut(p).fuse(skin.cut(sheet)).removeSplitter()
    if die_r > 1e-9:
        rim = [e for e in out.Edges if _on(e, w0)]
        try:
            out = out.makeFillet(die_r, rim)
        except Exception:
            raise ValueError("The die radius is too big for the stamp.")
    if len(out.Solids) == 1:
        out = out.Solids[0]
    return out


def _end_edge(e, n, at):
    return all(abs((v.Point - at).dot(n)) < 1e-6 for v in e.Vertexes) and \
        abs((e.valueAt((e.FirstParameter + e.LastParameter) / 2) - at).dot(n)) < 1e-6


def sketch_face(sheet, sketch_shape, normal):
    """The flat face of the sheet the sketch lies on, and its outward normal."""
    p = sketch_shape.Vertexes[0].Point
    for f in sheet.Faces:
        if f.Surface.TypeId != "Part::GeomPlane":
            continue
        fn = f.normalAt(0, 0)
        if abs(abs(fn.dot(normal)) - 1) > 1e-7 or abs((p - f.CenterOfMass).dot(fn)) > 1e-6:
            continue
        if all(f.isInside(v.Point, 1e-4, True) for v in sketch_shape.Vertexes):
            return f, fn
    return None, None


# ================================================================ feature
_LAST = None        # the open Sheet Metal Stamp PropertyManager


def _defaults():
    return App.ParamGet("User parameter:BaseApp/Preferences/Mod/SWStyle/SheetMetal")


class SWStamp:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyLink", "Profile", GROUP, "The closed sketch on the sheet")
        add("App::PropertyLength", "Depth", GROUP, "Stamp depth")
        add("App::PropertyBool", "Reverse", GROUP, "Stamp from the other side")
        add("App::PropertyBool", "Draft", GROUP, "Draft the stamp's walls")
        add("App::PropertyAngle", "DraftAngle", GROUP, "Draft angle")
        add("App::PropertyLength", "DieRadius", GROUP, "Die Radius (R1): the rim")
        add("App::PropertyLength", "PunchRadius", GROUP, "Punch Radius (R2): the floor")
        add("App::PropertyBool", "PunchCorner", GROUP, "Round the punch's side corners")
        add("App::PropertyLength", "PunchCornerRadius", GROUP, "Punch Side Corner Radius")
        obj.Depth = 10.0
        obj.Proxy = self

    def execute(self, obj):
        from .smformingtool import opposite
        from .smnormalcut import baked, inside_point
        base = obj.BaseFeature
        if base is None or base.Shape.isNull():
            raise ValueError("Stamp: needs a sheet metal part")
        sheet = baked(base.Shape)
        if obj.Profile is None:
            obj.Shape = sheet
            return
        shape = baked(obj.Profile.Shape)
        wires = shape.Wires
        if not wires or not all(w.isClosed() for w in wires):
            raise ValueError(NOT_CLOSED)
        normal = obj.Profile.getGlobalPlacement().Rotation.multVec(V(0, 0, 1))
        face, n = sketch_face(sheet, shape, normal)
        if face is None:
            raise ValueError(NOT_ON_FACE)
        _p, _m, t = opposite(sheet, inside_point(face), n)
        # outer outlines only: one inside another is a hole of the same stamp
        faces = [Part.Face(w) for w in wires]
        outer = [w for w, f in zip(wires, faces)
                 if not any(g is not f and g.isInside(f.CenterOfMass, 1e-6, True) and g.Area > f.Area for g in faces)]
        out = sheet
        for w in outer:
            out = stamp(out, w, n, t, float(obj.Depth), bool(obj.Reverse),
                        float(obj.DraftAngle) if obj.Draft else 0.0, float(obj.DieRadius), float(obj.PunchRadius),
                        float(obj.PunchCornerRadius) if obj.PunchCorner else 0.0)
        obj.Shape = out

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_stamp(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWStamp"


class ViewProviderStamp:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        from .smunfold import _icon
        return _icon(ICON)

    def claimChildren(self):
        p = getattr(self.Object, "Profile", None)
        return [p] if p is not None else []

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


def make(body, sketch):
    doc = body.Document
    base = body.Tip
    obj = doc.addObject("PartDesign::FeaturePython", "Stamp")
    SWStamp(obj)
    if App.GuiUp:
        ViewProviderStamp(obj.ViewObject)
    body.addObject(obj)
    obj.Label = naming.next_label(doc, LABEL)
    obj.Profile = sketch
    for o in (base, sketch):
        try:
            o.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("smstamp.py:259", _fw_err)
    return obj


# ================================================================ PropertyManager
def _close_transaction(abort):
    try:
        App.closeActiveTransaction(abort)
    except Exception as _fw_err:
        _fw_log("smstamp.py:268", _fw_err)


class Panel:
    """The Sheet Metal Stamp PropertyManager: Stamp Parameters and Fillet."""

    def __init__(self, obj, new):
        from PySide import QtWidgets
        from .smbaseflange import _box, _spin
        from .smedgeflange import error_label
        global _LAST
        _LAST = self
        self.obj, self.new, self.busy = obj, new, True

        params = _box("Stamp Parameters")
        f = params.layout()
        self.error = error_label()
        f.addRow(self.error)
        self.reverse = QtWidgets.QPushButton("Reverse Direction")
        from . import pmvalues
        self.reverse.setIcon(pmvalues.reverse_icon())
        self.reverse.setObjectName("SWSMStampReverse")
        self.reverse.setCheckable(True)
        self.reverse.setChecked(bool(obj.Reverse))
        self.depth = _spin("SWSMStampDepth", float(obj.Depth), 0.01, 10000.0)
        self.depth.setToolTip("Depth")
        f.addRow(self.reverse, self.depth)
        self.draft = QtWidgets.QPushButton("Draft")
        self.draft.setObjectName("SWSMStampDraftOn")
        self.draft.setCheckable(True)
        self.draft.setChecked(bool(obj.Draft))
        self.draft.setToolTip("Draft On/Off")
        self.angle = _spin("SWSMStampDraft", float(obj.DraftAngle), 0.0, 89.0, suffix=" deg")
        self.angle.setToolTip("Draft angle")
        f.addRow(self.draft, self.angle)

        fillet = _box("Fillet")
        f = fillet.layout()
        f.addRow(QtWidgets.QLabel("Die Radius (R1)"))
        self.die = _spin("SWSMStampDieRadius", float(obj.DieRadius), 0.0, 1000.0, step=0.5)
        self.die.setToolTip("Die Radius (R1)")
        f.addRow(self.die)
        f.addRow(QtWidgets.QLabel("Punch Radius (R2)"))
        self.punch = _spin("SWSMStampPunchRadius", float(obj.PunchRadius), 0.0, 1000.0, step=0.5)
        self.punch.setToolTip("Punch Radius (R2)")
        f.addRow(self.punch)
        self.corner_on = QtWidgets.QCheckBox("Punch Side Corner Radius")
        self.corner_on.setObjectName("SWSMStampCornerOn")
        self.corner_on.setChecked(bool(obj.PunchCorner))
        f.addRow(self.corner_on)
        self.corner = _spin("SWSMStampCornerRadius", float(obj.PunchCornerRadius), 0.0, 1000.0, step=0.5)
        self.corner.setToolTip("Punch Side Corner Radius")
        f.addRow(self.corner)

        params.setProperty("swstyle_pm_title", TITLE)
        params.setProperty("swstyle_pm_icon", ICON)
        self.form = [params, fillet]
        for b in (self.reverse, self.draft, self.corner_on):
            b.toggled.connect(self._changed)
        for sp in (self.depth, self.angle, self.die, self.punch, self.corner):
            sp.valueChanged.connect(self._changed)
        self.busy = False
        self._enable()
        self._report()

    def _enable(self):
        self.angle.setEnabled(self.draft.isChecked())
        self.corner.setEnabled(self.corner_on.isChecked())

    def _changed(self, *_a):
        if self.busy:
            return
        o = self.obj
        o.Depth, o.Reverse = self.depth.value(), self.reverse.isChecked()
        o.Draft, o.DraftAngle = self.draft.isChecked(), self.angle.value()
        o.DieRadius, o.PunchRadius = self.die.value(), self.punch.value()
        o.PunchCorner, o.PunchCornerRadius = self.corner_on.isChecked(), self.corner.value()
        self._enable()
        self._apply()

    def _apply(self):
        from PySide import QtCore
        doc = self.obj.Document
        if doc.Recomputing:
            QtCore.QTimer.singleShot(50, self._apply)
            return
        self.obj.touch()
        doc.recompute()
        self._report()

    def _report(self):
        o = self.obj
        text = o.getStatusString() if "Invalid" in o.State else ""
        self.error.setText(text)
        self.error.setVisible(bool(text))
        return not text

    def getStandardButtons(self):
        from PySide import QtWidgets
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smstamp.py:375", _fw_err)

    def accept(self):
        if not self._report():
            return False
        self.obj.Document.commitTransaction()
        _close_transaction(False)
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        shown = (self.obj.BaseFeature, self.obj.Profile) if self.new else ()
        doc.abortTransaction()
        _close_transaction(True)
        doc.recompute()
        for o in shown:
            try:
                if o is not None:
                    o.ViewObject.Visibility = o is not shown[1]
            except Exception as _fw_err:
                _fw_log("smstamp.py:396", _fw_err)
        self._close()
        return True


# ================================================================ command
def _sheet_body(doc=None):
    from . import smflatten
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    try:
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody") or smflatten._body()
    except Exception:
        body = None
    if body is None or smflatten.root(body) is None:
        return None
    return body


def _body_of(obj):
    return next((p for p in obj.InList if p.TypeId == "PartDesign::Body"), None)


def open_on(sketch):
    body = _body_of(sketch)
    from . import smflatten
    if body is None or smflatten.root(body) is None:
        return
    doc = body.Document
    Gui.Selection.clearSelection()
    doc.openTransaction(TITLE)
    try:
        obj = make(body, sketch)
        doc.recompute()
        Gui.Control.showDialog(Panel(obj, True))
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise


def start():
    from PySide import QtCore
    from . import smbaseflange
    doc = App.ActiveDocument
    if doc is None:
        return
    gdoc = Gui.ActiveDocument
    edit = gdoc.getInEdit() if gdoc is not None else None
    if edit is not None and edit.Object.TypeId == "Sketcher::SketchObject":
        sketch = edit.Object
        Gui.runCommand("Sketcher_LeaveSketch", 0)
        if sketch.Geometry:
            QtCore.QTimer.singleShot(0, lambda: open_on(sketch))
        return
    sketches = [s.Object for s in Gui.Selection.getSelectionEx() if s.Object.TypeId == "Sketcher::SketchObject"]
    if len(sketches) == 1:
        open_on(sketches[0])
        return
    smbaseflange._pick_plane(doc, then=open_on, title=TITLE, icon=ICON, message=PICK_MESSAGE)


class Command:
    def GetResources(self):
        from .smunfold import _icon
        return {"Pixmap": _icon(ICON), "MenuText": "Stamp",
                "ToolTip": "Presses a sketched outline into the sheet to a depth."}

    def IsActive(self):
        from . import smflatten
        try:
            edit = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument else None
            sketching = edit is not None and edit.Object.TypeId == "Sketcher::SketchObject"
            if Gui.Control.activeDialog() and not sketching:
                return False
        except Exception:
            return False
        return _sheet_body() is not None and not smflatten.blocked()

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
