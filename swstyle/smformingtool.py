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

from . import naming

COMMAND = "SWStyle_SMFormingTool"
TITLE = "Forming Tool"
APPLY_TITLE = "Form Tool Feature"
GROUP = "Forming Tool"
ICON = "SheetMetal_Forming"
V = App.Vector
STOP_COLOUR = (0.0, 1.0, 1.0)
REMOVE_COLOUR = (1.0, 0.0, 0.0)      # and the faces to remove red
DEFINE_MESSAGE = "Select the stopping face, then the faces to remove (optional)."
APPLY_MESSAGE = "Select the face to place the forming tool on."


# ================================================================ geometry
def _face_at(shape, p, n):
    v = Part.Vertex(p)
    best = None
    for f in shape.Faces:
        if f.Surface.TypeId == "Part::GeomPlane" and abs(abs(f.normalAt(0, 0).dot(n)) - 1) > 1e-7:
            continue
        d = f.distToShape(v)[0]
        if d < 1e-4 and (best is None or d < best[0]):
            best = (d, f)
    return best[1] if best else None


def _halfspace(point, normal, size):
    """The solid on the front of the plane through point (normal pointing into it)."""
    box = Part.makeBox(2 * size, 2 * size, size, V(-size, -size, 0))
    box.Placement = App.Placement(point, App.Rotation(V(0, 0, 1), normal))
    return box


def punch(tool_shape, stop):
    """The part of the tool beyond its stopping face: what presses into the sheet."""
    n = stop.normalAt(0, 0)
    size = tool_shape.BoundBox.DiagonalLength * 2 + 10
    part = tool_shape.common(_halfspace(stop.CenterOfMass, n, size))
    if part.isNull() or part.Volume < 1e-9:
        raise ValueError("Nothing of the tool stands out from its stopping face.")
    return part.Solids[0] if len(part.Solids) == 1 else part


def tool_frame(stop, insertion):
    """The tool's placement frame: origin at the insertion point, z along the stopping face's normal."""
    return insertion, stop.normalAt(0, 0)


def place(shape, insertion, stop_normal, point, face_normal, angle):
    """shape moved from the tool's frame to the sheet: insertion -> point, stopping normal -> into the face."""
    s = shape.copy()
    s.translate(-insertion)
    s.rotate(V(), *_axis_angle(stop_normal, -face_normal))
    if abs(angle) > 1e-12:
        s.rotate(V(), face_normal, angle)
    s.translate(point)
    return s


def _axis_angle(a, b):
    import math
    a, b = V(a).normalize(), V(b).normalize()
    axis = a.cross(b)
    cos = max(-1.0, min(1.0, a.dot(b)))
    if axis.Length < 1e-9:
        if cos > 0:
            return V(0, 0, 1), 0.0
        # opposite: any axis square to a
        axis = a.cross(V(1, 0, 0)) if abs(a.x) < 0.9 else a.cross(V(0, 1, 0))
        return axis.normalize(), 180.0
    return axis.normalize(), math.degrees(math.acos(cos))


def form(sheet, thickness, tool_shape, stop, removed, insertion, point, face_normal, angle):
    """The sheet formed by the tool at point on a face with outward normal face_normal."""
    p = punch(tool_shape, stop)
    n = stop.normalAt(0, 0)
    # the punch's faces on the stopping face's plane and the faces to remove are left open
    open_faces = []
    for f in p.Faces:
        on_stop = f.Surface.TypeId == "Part::GeomPlane" and abs(abs(f.normalAt(0, 0).dot(n)) - 1) < 1e-7 \
            and abs((f.CenterOfMass - stop.CenterOfMass).dot(n)) < 1e-6
        if on_stop or any(_same_face(f, r) for r in removed):
            open_faces.append(f)
    if len(open_faces) == len(p.Faces):
        raise ValueError("The tool has no faces to form the sheet with.")
    skin = p.makeThickness(open_faces, thickness, 1e-4, False, False, 0, 0)
    cut = place(p, insertion, n, point, face_normal, angle)
    wrap = place(skin, insertion, n, point, face_normal, angle)
    out = sheet.cut(cut).fuse(wrap.cut(sheet)).removeSplitter()
    if len(out.Solids) == 1:
        out = out.Solids[0]
    return out


def _same_face(f, g):
    """f (a face of the punch) lies on g (a face of the tool)."""
    if f.Surface.TypeId != g.Surface.TypeId:
        return False
    pts = f.tessellate(0.5)[0][:6] or [f.CenterOfMass]
    return all(g.distToShape(Part.Vertex(q))[0] < 1e-5 for q in pts)


def opposite(sheet, point, normal):
    """The sheet's face on the far side from point (for Flip Tool): (point there, its normal)."""
    line = Part.makeLine(point + normal * 1e-3, point - normal * 1000)
    common = sheet.common(line)
    far = None
    for e in common.Edges:
        for v in e.Vertexes:
            d = (point - v.Point).dot(normal)
            if d > 1e-6 and (far is None or d < far[0] + 1e-9) and (far is None or d < far[0]):
                far = (d, v.Point)
    if far is None:
        raise ValueError("The sheet has no far side here.")
    return far[1], -normal, far[0]


# ================================================================ features
_LAST = None        # the open Forming Tool or Form Tool Feature PropertyManager


def _body_of(obj):
    return next((p for p in obj.InList if p.TypeId == "PartDesign::Body"), None) if obj is not None else None


class SWFormingTool:
    """Marks a part as a forming tool: its stopping face, faces to remove and insertion point."""

    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyVector", "StopPoint", GROUP, "A point on the stopping face")
        add("App::PropertyVector", "StopNormal", GROUP, "The stopping face's normal")
        add("App::PropertyVectorList", "RemovePoints", GROUP, "A point on each face to remove")
        add("App::PropertyVectorList", "RemoveNormals", GROUP, "Each face to remove's normal")
        add("App::PropertyVector", "InsertionPoint", GROUP, "Where the tool is placed from (on the stopping face)")
        add("App::PropertyBool", "InsertionSet", GROUP, "The insertion point was placed (else the face's middle)")
        obj.setEditorMode("InsertionSet", 2)
        obj.Proxy = self

    def parts(self, obj, shape=None):
        """(tool shape, stopping face, faces to remove, insertion point)."""
        from .smnormalcut import baked
        shape = shape if shape is not None else baked(obj.BaseFeature.Shape)
        if obj.StopNormal.Length < 1e-9:
            raise ValueError(DEFINE_MESSAGE)
        stop = _face_at(shape, obj.StopPoint, obj.StopNormal)
        if stop is None or stop.Surface.TypeId != "Part::GeomPlane":
            raise ValueError("The stopping face must be a flat face of the tool.")
        removed = []
        for p, n in zip(obj.RemovePoints, obj.RemoveNormals):
            f = _face_at(shape, p, n)
            if f is None:
                raise ValueError("A face to remove is no longer there.")
            removed.append(f)
        ins = V(obj.InsertionPoint) if obj.InsertionSet else stop.CenterOfMass
        return shape, stop, removed, ins

    def execute(self, obj):
        from .smnormalcut import baked
        base = obj.BaseFeature
        if base is None:
            raise ValueError("Forming Tool: needs a solid part")
        shape = baked(base.Shape)
        if obj.StopNormal.Length > 1e-9:
            _s, stop, removed, _i = self.parts(obj, shape)
            punch(shape, stop)
        obj.Shape = shape
        _colour(obj, shape)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _colour(obj, shape):
    ""
    try:
        vo = obj.ViewObject
        if vo is None:
            return
        look = vo.ShapeAppearance[0] if vo.ShapeAppearance else App.Material()
        base = tuple(look.DiffuseColor[:3]) if vo.ShapeAppearance else (0.8, 0.8, 0.8)
        stop = _face_at(shape, obj.StopPoint, obj.StopNormal) if obj.StopNormal.Length > 1e-9 else None
        removed = [_face_at(shape, p, n) for p, n in zip(obj.RemovePoints, obj.RemoveNormals)]
        colours = []
        for f in shape.Faces:
            if stop is not None and f.isSame(stop):
                colours.append(STOP_COLOUR + (1.0,))
            elif any(r is not None and f.isSame(r) for r in removed):
                colours.append(REMOVE_COLOUR + (1.0,))
            else:
                colours.append(base + (1.0,))
        # per-face materials in ShapeAppearance: every view of a shape has it in FreeCAD 1.1 (stock
        # FreeCAD can give the feature a view without DiffuseColor)
        materials = []
        for c in colours:
            m = App.Material()
            for attr in ("AmbientColor", "SpecularColor", "EmissiveColor", "Shininess", "Transparency"):
                setattr(m, attr, getattr(look, attr))
            m.DiffuseColor = tuple(c[:3])
            materials.append(m)
        vo.ShapeAppearance = materials
    except Exception as _fw_err:
        _fw_log("smformingtool.py:238", _fw_err)


def is_forming_tool(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWFormingTool"


def tools(doc=None):
    ""

    docs = [doc] if doc is not None else list(App.listDocuments().values())
    found = [o for d in docs for o in d.Objects if is_forming_tool(o) and "Invalid" not in o.State]
    if doc is None:
        try:
            from . import smformlib
            active = App.ActiveDocument
            found += [t for t in smformlib.tools() if t not in found]
            if App.GuiUp:
                _activate(active)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: forming tool library: %s\n" % error)
    return found


class SWFormFeature:
    """A forming tool pressed into a sheet metal face at one or more positions."""

    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyString", "ToolDocument", GROUP, "The forming tool's document")
        add("App::PropertyString", "ToolFile", GROUP, "The forming tool's file")
        add("App::PropertyString", "ToolName", GROUP, "The forming tool feature in it")
        add("App::PropertyString", "ToolLabel", GROUP, "The forming tool's part")
        add("Part::PropertyPartShape", "ToolShape", GROUP, "A copy of the tool, kept with the part")
        add("App::PropertyVector", "StopPoint", GROUP, "The tool's stopping face (copy)")
        add("App::PropertyVector", "StopNormal", GROUP, "The stopping face's normal (copy)")
        add("App::PropertyVectorList", "RemovePoints", GROUP, "The tool's faces to remove (copy)")
        add("App::PropertyVectorList", "RemoveNormals", GROUP, "Their normals (copy)")
        add("App::PropertyVector", "InsertionPoint", GROUP, "The tool's insertion point (copy)")
        for name in ("ToolDocument", "ToolFile", "ToolName", "ToolLabel"):
            obj.setEditorMode(name, 1)
        for name in ("ToolShape", "StopPoint", "StopNormal", "RemovePoints", "RemoveNormals", "InsertionPoint"):
            obj.setEditorMode(name, 2)
        add("App::PropertyVector", "FacePoint", GROUP, "A point on the placement face")
        add("App::PropertyVector", "FaceNormal", GROUP, "The placement face's normal")
        add("App::PropertyVectorList", "Positions", GROUP, "Where the tool goes on the face")
        add("App::PropertyAngle", "RotationAngle", GROUP, "Rotation angle about the face's normal")
        add("App::PropertyBool", "FlipTool", GROUP, "Form the other way")
        add("App::PropertyLength", "Thickness", GROUP, "The sheet's thickness there")
        obj.setEditorMode("Thickness", 1)
        obj.Proxy = self

    def execute(self, obj):
        from .smnormalcut import baked
        base = obj.BaseFeature
        if base is None:
            raise ValueError("Form Tool Feature: needs a sheet metal part")
        sheet = baked(base.Shape)
        if linked(obj):
            sync(obj)
        if obj.ToolShape.isNull() or not obj.Positions or obj.FaceNormal.Length < 1e-9:
            obj.Shape = sheet
            return
        face = _face_at(sheet, obj.FacePoint, obj.FaceNormal)
        if face is None:
            raise ValueError("The placement face is no longer there.")
        n = face.normalAt(*face.Surface.parameter(obj.FacePoint))
        tool_shape = obj.ToolShape
        stop = _face_at(tool_shape, obj.StopPoint, obj.StopNormal)
        removed = [_face_at(tool_shape, q, m) for q, m in zip(obj.RemovePoints, obj.RemoveNormals)]
        if stop is None or any(f is None for f in removed):
            raise ValueError("The forming tool's faces are no longer there.")
        ins = V(obj.InsertionPoint)
        thickness = None
        out = sheet
        for p in obj.Positions:
            q, m = V(p), V(n)
            far, fn, t = opposite(sheet, q, m)
            thickness = t
            if obj.FlipTool:
                q, m = far, fn
            out = form(out, t, tool_shape, stop, removed, ins, q, m, float(obj.RotationAngle))
        if thickness is not None:
            obj.Thickness = thickness
        obj.Shape = out

    def dumps(self):
        return None

    def loads(self, state):
        return None


def tool_of(obj):
    """The forming tool a Form Tool Feature uses, when its document is open."""
    for d in App.listDocuments().values():
        if (obj.ToolFile and d.FileName == obj.ToolFile) or d.Name == obj.ToolDocument:
            t = d.getObject(obj.ToolName)
            if t is not None and is_forming_tool(t):
                return t
    return None


def use(obj, tool):
    """Points a Form Tool Feature at a forming tool and copies it in."""
    body = _body_of(tool)
    obj.ToolDocument, obj.ToolFile, obj.ToolName = tool.Document.Name, tool.Document.FileName, tool.Name
    obj.ToolLabel = body.Label if body is not None else tool.Label
    sync(obj)


def linked(obj):
    """Link to forming tool: the feature follows the tool's changes (off: it keeps its copy)."""
    if "LinkToTool" not in obj.PropertiesList:
        obj.addProperty("App::PropertyBool", "LinkToTool", GROUP, "Link to forming tool: follow the tool's changes")
        obj.LinkToTool = True
    return bool(obj.LinkToTool)


def sync(obj):
    ""

    tool = tool_of(obj)
    if tool is None or "Invalid" in tool.State:
        return
    shape, stop, _removed, ins = tool.Proxy.parts(tool)
    obj.ToolShape = shape
    obj.StopPoint, obj.StopNormal = tool.StopPoint, tool.StopNormal
    obj.RemovePoints, obj.RemoveNormals = list(tool.RemovePoints), list(tool.RemoveNormals)
    obj.InsertionPoint = ins
    if tool.Document.FileName:
        obj.ToolFile = tool.Document.FileName


def is_form_feature(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWFormFeature"


def without_forms(body, shape):
    """shape (the part's last feature) with its formed features and stamps taken back out, for the flat
    pattern: the material each one added is cut away and what it cut is put back."""
    from .smnormalcut import baked
    out = shape
    for o in body.Group:
        if not (is_form_feature(o) or type(getattr(o, "Proxy", None)).__name__ == "SWStamp") or o.BaseFeature is None or "Invalid" in o.State or o.Shape.isNull():
            continue
        try:
            base, formed = baked(o.BaseFeature.Shape), baked(o.Shape)
            added, removed = formed.cut(base), base.cut(formed)
            if added.Volume > 1e-9:
                out = out.cut(added)
            if removed.Volume > 1e-9:
                out = out.fuse(removed)
            out = out.removeSplitter()
        except Exception as _fw_err:
            _fw_log("smformingtool.py:393", _fw_err)
    if len(out.Solids) == 1:
        out = out.Solids[0]
    return out


class ViewProviderForming:
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
        obj.Document.openTransaction("Edit " + obj.Label)
        try:
            cls = DefinePanel if is_forming_tool(obj) else ApplyPanel
            Gui.Control.showDialog(cls(obj, False))
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


def make(body, kind, name, label):
    doc = body.Document
    base = body.Tip
    obj = doc.addObject("PartDesign::FeaturePython", name)
    kind(obj)
    if App.GuiUp:
        ViewProviderForming(obj.ViewObject)
    body.addObject(obj)
    obj.Label = naming.next_label(doc, label)
    try:
        doc.recompute()         # the new feature shows the part at once (else it is blank till a rebuild)
    except Exception as _fw_err:
        _fw_log("smformingtool.make", _fw_err)
    if base is not None:
        try:
            shown = obj.Shape is not None and not obj.Shape.isNull() and bool(obj.Shape.Faces)
            base.ViewObject.Visibility = not shown
            if shown and obj.ViewObject is not None:
                obj.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("smformingtool.py:446", _fw_err)
    return obj


# ================================================================ PropertyManagers
def _close_transaction(abort):
    try:
        App.closeActiveTransaction(abort)
    except Exception as _fw_err:
        _fw_log("smformingtool.py:455", _fw_err)


def _activate(doc, later=True):
    """Makes doc the active document again: opening a tool's or the library's parts (hidden) makes them the
    active document, and the next command would then work in the wrong part."""
    try:
        if doc is None or doc.Name not in App.listDocuments():
            return
        if App.ActiveDocument is not doc:
            App.setActiveDocument(doc.Name)
        if Gui.ActiveDocument is None or Gui.ActiveDocument.Document is not doc:
            from PySide import QtWidgets
            area = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
            for w in (area.subWindowList() if area is not None else []):
                title = w.windowTitle().replace("[*]", "").rstrip("*").split(" : ")[0].strip()
                if title == doc.Label:
                    area.setActiveSubWindow(w)
                    break
        if later:
            from PySide import QtCore
            QtCore.QTimer.singleShot(0, lambda: _activate(doc, False))
    except Exception as _fw_err:
        _fw_log("smformingtool.py:478", _fw_err)


class _Panel:
    """What both PropertyManagers share: picks, apply, OK and Cancel."""

    def _start(self):
        self.busy = False
        self._fill()
        self._report()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def addSelection(self, doc, name, sub, point):
        from PySide import QtCore
        at = App.Vector(*point) if point else None
        QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub, at))

    def _base_face(self, picked, sub, at):
        """The picked face of the feature's base: (face, point on it)."""
        from .smnormalcut import baked, inside_point
        base = baked(self.obj.BaseFeature.Shape)
        element = picked.Shape.getElement(sub)
        if at is None or element.distToShape(Part.Vertex(at))[0] > 1e-4:
            at = inside_point(element)
        v = Part.Vertex(at)
        near = [f for f in base.Faces if f.distToShape(v)[0] < 1e-4]
        if not near:
            return None, None
        # a point on an edge touches several faces: the one that is the picked face
        best = min(near, key=lambda f: ((f.CenterOfMass - element.CenterOfMass).Length + abs(f.Area - element.Area)))
        if best.distToShape(v)[0] > 1e-4 or not best.isInside(at, 1e-4, True):
            at = inside_point(best)
        return best, at

    def _apply(self):
        from PySide import QtCore
        doc = self.obj.Document
        if doc.Recomputing:
            QtCore.QTimer.singleShot(50, self._apply)
            return
        self.obj.touch()
        doc.recompute()
        self._fill()
        self._report()

    def getStandardButtons(self):
        from PySide import QtWidgets
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self, doc=None):
        if doc is None:
            try:
                doc = self.obj.Document
            except Exception:           # Cancel on a new tool: the abort took the feature away
                doc = None
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smformingtool.py:537", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smformingtool.py:543", _fw_err)
        _activate(doc)

    def accept(self):
        self.pick_error = ""
        if not self._report():
            return False
        try:
            self.obj.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("smformingtool.py:553", _fw_err)
        self.obj.Document.commitTransaction()
        _close_transaction(False)
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        base = self.obj.BaseFeature if self.new else None
        doc.abortTransaction()
        _close_transaction(True)
        doc.recompute()
        if base is not None:
            try:
                base.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("smformingtool.py:569", _fw_err)
        self._close(doc)
        return True

    def _show(self, text):
        self.error.setText(text)
        self.error.setVisible(bool(text))
        return not text


class DefinePanel(_Panel):
    """The Forming Tool PropertyManager: Type (Stopping Face, Faces to Remove) and Insertion Point."""

    def __init__(self, obj, new):
        from PySide import QtWidgets
        from .smbaseflange import _box
        from .smedgeflange import error_label
        from .smunfold import _DeleteKey, _list
        global _LAST
        _LAST = self
        self.obj, self.new, self.pick_error, self.busy = obj, new, "", True
        typ = _box("Type")
        f = typ.layout()
        self.error = error_label()
        f.addRow(self.error)
        f.addRow(QtWidgets.QLabel("Stopping Face"))
        self.stop = _list("SWSMFormStop", "#ccffff", "Stopping face: the flat face the sheet stops against")
        f.addRow(self.stop)
        f.addRow(QtWidgets.QLabel("Faces to Remove"))
        self.remove = _list("SWSMFormRemove", "#ffd6d6", "Faces to remove: left open in the sheet", rows=3)
        f.addRow(self.remove)
        ins = _box("Insertion Point")
        f = ins.layout()
        self.insertion = _list("SWSMFormInsertion", "#e6d6ff",
                               "Insertion point: a point on the stopping face (its middle when empty)")
        f.addRow(self.insertion)
        typ.setProperty("swstyle_pm_title", TITLE)
        typ.setProperty("swstyle_pm_icon", ICON)
        self.form = [typ, ins]
        self.active = self.stop
        self.keys = _DeleteKey(self)
        for w in (self.stop, self.remove, self.insertion):
            w.installEventFilter(self.keys)
        self._start()

    def set_active(self, w):
        if w in (self.stop, self.remove, self.insertion):
            self.active = w

    def _fill(self):
        o = self.obj
        self.stop.clear()
        if o.StopNormal.Length > 1e-9:
            self.stop.addItem("Stopping face")
        self.remove.clear()
        for k in range(len(o.RemovePoints)):
            self.remove.addItem("Face to remove %d" % (k + 1))
        self.insertion.clear()
        if o.InsertionSet:
            p = o.InsertionPoint
            self.insertion.addItem("Point (%.2f, %.2f, %.2f)" % (p.x, p.y, p.z))

    def remove_current(self, w):
        o = self.obj
        if w is self.stop:
            o.StopNormal = V()
        elif w is self.remove and w.currentRow() >= 0:
            pts, ns = list(o.RemovePoints), list(o.RemoveNormals)
            del pts[w.currentRow()], ns[w.currentRow()]
            o.RemovePoints, o.RemoveNormals = pts, ns
        elif w is self.insertion:
            o.InsertionSet = False
        self._apply()

    def _picked(self, doc_name, name, sub, at):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smformingtool.py:647", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None or not sub:
            return
        o = self.obj
        self.pick_error = ""
        if sub.startswith("Vertex"):
            o.InsertionPoint = picked.Shape.getElement(sub).Point
            o.InsertionSet = True
        elif sub.startswith("Face"):
            face, p = self._base_face(picked, sub, at)
            if face is None:
                return
            n = face.normalAt(*face.Surface.parameter(p))
            if self.active is self.insertion:
                o.InsertionPoint, o.InsertionSet = p, True
            elif self.active is self.remove or (o.StopNormal.Length > 1e-9 and self.active is not self.stop):
                pts, ns = list(o.RemovePoints), list(o.RemoveNormals)
                pts.append(p)
                ns.append(n)
                o.RemovePoints, o.RemoveNormals = pts, ns
            else:
                if face.Surface.TypeId != "Part::GeomPlane":
                    self.pick_error = "The stopping face must be a flat face."
                    self._report()
                    return
                o.StopPoint, o.StopNormal = p, n
                self.active = self.remove
        self._apply()

    def _report(self):
        o = self.obj
        if self.pick_error:
            return self._show(self.pick_error)
        if o.StopNormal.Length < 1e-9:
            return self._show(DEFINE_MESSAGE)
        if "Invalid" in o.State:
            return self._show(o.getStatusString())
        return self._show("")


class ApplyPanel(_Panel):
    """The Form Tool Feature PropertyManager: the tool, the placement face, rotation, Flip Tool, positions."""

    def __init__(self, obj, new):
        from PySide import QtWidgets
        from .smbaseflange import _box, _spin
        from .smedgeflange import error_label
        from .smunfold import _DeleteKey, _list
        global _LAST
        _LAST = self
        self.obj, self.new, self.pick_error, self.busy = obj, new, "", True
        typ = _box("Type")
        f = typ.layout()
        self.error = error_label()
        f.addRow(self.error)
        self.tool = QtWidgets.QComboBox()
        self.tool.setObjectName("SWSMFormTool")
        self.tools = tools()
        for k, t in enumerate(self.tools):
            self.tool.addItem("%s (%s)" % (_body_of(t).Label if _body_of(t) else t.Label, t.Document.Label))
        f.addRow("Forming tool:", self.tool)
        f.addRow(QtWidgets.QLabel("Placement Face"))
        self.face = _list("SWSMFormFace", "#d6ecff", "The sheet metal face the tool goes on")
        f.addRow(self.face)
        self.angle = _spin("SWSMFormAngle", float(obj.RotationAngle), -360.0, 360.0, suffix=" deg", step=5.0)
        self.angle.setToolTip("Rotation angle")
        f.addRow("Rotation angle:", self.angle)
        self.flip = QtWidgets.QPushButton("Flip Tool")
        self.flip.setObjectName("SWSMFormFlip")
        self.flip.setCheckable(True)
        self.flip.setChecked(bool(obj.FlipTool))
        f.addRow(self.flip)
        link = _box("Link")
        self.link = QtWidgets.QCheckBox("Link to forming tool")
        self.link.setObjectName("SWSMFormLink")
        self.link.setToolTip("Follow the forming tool's changes; off, the feature keeps the copy it has")
        self.link.setChecked(linked(obj))
        self.replace = QtWidgets.QPushButton("Replace Tool")
        self.replace.setObjectName("SWSMFormReplace")
        self.replace.setToolTip("Use another forming tool for this feature")
        self.replace.clicked.connect(self._replace_menu)
        link.layout().addRow(self.link)
        link.layout().addRow(self.replace)
        pos = _box("Position")
        f = pos.layout()
        self.positions = _list("SWSMFormPositions", "#e6d6ff",
                               "Where the tool goes: pick points on the placement face", rows=3)
        f.addRow(self.positions)
        typ.setProperty("swstyle_pm_title", APPLY_TITLE)
        typ.setProperty("swstyle_pm_icon", ICON)
        self.form = [typ, link, pos]
        self.active = self.face
        self.keys = _DeleteKey(self)
        for w in (self.face, self.positions):
            w.installEventFilter(self.keys)
        current = tool_of(obj)
        if current is not None and current in self.tools:
            self.tool.setCurrentIndex(self.tools.index(current))
        elif self.tools and not obj.ToolName:
            use(obj, self.tools[0])
        elif obj.ToolName:
            # the tool's document is closed: the copy kept with the part is used
            self.tool.insertItem(0, "%s (copy kept with the part)" % obj.ToolLabel)
            self.tools.insert(0, None)
            self.tool.setCurrentIndex(0)
        self.tool.currentIndexChanged.connect(self._changed)
        self.angle.valueChanged.connect(self._changed)
        self.flip.toggled.connect(self._changed)
        self.link.toggled.connect(self._changed)
        self._start()

    def set_active(self, w):
        if w in (self.face, self.positions):
            self.active = w

    def _fill(self):
        o = self.obj
        self.face.clear()
        if o.FaceNormal.Length > 1e-9:
            self.face.addItem("Placement face")
        self.positions.clear()
        for p in o.Positions:
            self.positions.addItem("Point (%.2f, %.2f, %.2f)" % (p.x, p.y, p.z))

    def remove_current(self, w):
        o = self.obj
        if w is self.face:
            o.FaceNormal, o.Positions = V(), []
        elif w is self.positions and w.currentRow() >= 0:
            pts = list(o.Positions)
            del pts[w.currentRow()]
            o.Positions = pts
        self._apply()

    def _picked(self, doc_name, name, sub, at):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smformingtool.py:786", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None or not sub.startswith("Face"):
            return
        o = self.obj
        self.pick_error = ""
        face, p = self._base_face(picked, sub, at)
        if face is None:
            return
        if face.Surface.TypeId != "Part::GeomPlane":
            self.pick_error = "The placement face must be a flat face."
            self._report()
            return
        n = face.normalAt(*face.Surface.parameter(p))
        same = o.FaceNormal.Length > 1e-9 and abs(abs(n.dot(o.FaceNormal)) - 1) < 1e-7 and \
            abs((p - o.FacePoint).dot(n)) < 1e-6
        if not same:
            # a new placement face: the tool goes where it was picked
            o.FacePoint, o.FaceNormal, o.Positions = p, n, [p]
        else:
            o.Positions = list(o.Positions) + [p]
        self._apply()

    def _changed(self, *_a):
        if self.busy:
            return
        o = self.obj
        k = self.tool.currentIndex()
        if 0 <= k < len(self.tools) and self.tools[k] is not None and (tool_of(o) is not self.tools[k] or not o.ToolName):
            use(o, self.tools[k])       # a tool picked (or Replace Tool): copied in, linked or not
        linked(o)
        o.LinkToTool = self.link.isChecked()
        o.RotationAngle = self.angle.value()
        o.FlipTool = self.flip.isChecked()
        self._apply()

    def _replace_menu(self):
        from PySide import QtWidgets
        menu = QtWidgets.QMenu(self.replace)
        menu.setObjectName("SWSMFormReplaceMenu")
        for k in range(self.tool.count()):
            if self.tools[k] is None:
                continue
            a = menu.addAction(self.tool.itemText(k))
            a.triggered.connect(lambda _c=False, k=k: self.tool.setCurrentIndex(k))
        self.replace_menu = menu
        menu.popup(self.replace.mapToGlobal(self.replace.rect().bottomLeft()))
        return menu

    def _report(self):
        o = self.obj
        if not self.tools:
            return self._show("No forming tool is open: make a part a forming tool with Forming Tool first.")
        if self.pick_error:
            return self._show(self.pick_error)
        if o.FaceNormal.Length < 1e-9 or not o.Positions:
            return self._show(APPLY_MESSAGE)
        if "Invalid" in o.State:
            return self._show(o.getStatusString())
        return self._show("")


# ================================================================ command
def _active_body():
    if App.ActiveDocument is None:
        return None
    try:
        if Gui.Control.activeDialog():
            return None
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
    except Exception as _fw_err:
        _fw_log("smformingtool.py:865", _fw_err)
        return None
    return body


NO_SOLID = "The part has no solid bodies. Only solid bodies are supported."


def _has_solid(body):
    return body.Tip is not None and not body.Tip.Shape.isNull() and bool(body.Tip.Shape.Solids)


def _is_sheet(body):
    from . import smflatten
    return smflatten.root(body) is not None


def start():
    body = _active_body()
    if body is None:
        return
    if not _has_solid(body):

        from PySide import QtWidgets
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), TITLE, NO_SOLID)
        return
    doc = body.Document
    picked = [(o.Document.Name, o.Object.Name, sub, App.Vector(p)) for o in Gui.Selection.getSelectionEx()
              for sub, p in zip(o.SubElementNames, o.PickedPoints) if sub.startswith("Face")]
    if _is_sheet(body):
        from . import smflatten
        if smflatten.blocked():
            return
        doc.openTransaction(APPLY_TITLE)
        obj = make(body, SWFormFeature, "FormTool", "Form Tool")
        panel = ApplyPanel(obj, True)
    else:
        existing = next((o for o in body.Group if is_forming_tool(o)), None)
        if existing is not None:
            Gui.ActiveDocument.setEdit(existing.Name, 0)
            return
        doc.openTransaction(TITLE)
        obj = make(body, SWFormingTool, "FormingTool", "Forming Tool")
        panel = DefinePanel(obj, True)
    Gui.Control.showDialog(panel)
    for doc_name, name, sub, at in picked[:1]:
        panel._picked(doc_name, name, sub, at)


class Command:
    def GetResources(self):
        from .smunfold import _icon
        return {"Pixmap": _icon(ICON), "MenuText": "Forming Tool",
                "ToolTip": "Makes a part a forming tool, or presses a forming tool into a sheet metal face."}

    def IsActive(self):
        return _active_body() is not None

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
