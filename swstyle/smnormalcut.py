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

from . import naming, smflatten
from .smbaseflange import _box, _spin
from .smedgeflange import _radio, error_label
from .smunfold import _DeleteKey, _icon, _list

COMMAND = "SWStyle_SMNormalCut"
TITLE = "Normal Cut"
GROUP = "Normal Cut"
ICON = "SheetMetal_AddCutout"
KINDS = ("Extent", "Offset plane")
V = App.Vector
EPS = 1e-3


# ================================================================ geometry
def _plane(f):
    return f.Surface.TypeId == "Part::GeomPlane"


def _square(f, n):
    """A flat face square to the sheet (normal n)."""
    return _plane(f) and abs(f.normalAt(0, 0).dot(n)) < 1e-7


def _side(f, n):
    """A flat face parallel to the sheet: one of its sides."""
    return _plane(f) and abs(abs(f.normalAt(0, 0).dot(n)) - 1) < 1e-7


def neighbours(shape, i):
    """Indexes of the faces sharing an edge with face i."""
    out = set()
    for e in shape.Faces[i].Edges:
        for j, f in enumerate(shape.Faces):
            if j != i and j not in out and any(e.isSame(x) for x in f.Edges):
                out.add(j)
    return out


def face_at(shape, p):
    """The index of the face of shape through point p, else None."""
    vp = Part.Vertex(p)
    best = None
    for i, f in enumerate(shape.Faces):
        d = f.distToShape(vp)[0]
        if d < 1e-4 and (best is None or d < best[0]):
            best = (d, i)
    return best[1] if best else None


def baked(shape):
    """A copy of shape with its placement built into its geometry. A PartDesign feature's shape can
    carry a placement, which a FeaturePython result must not take over."""
    s = shape.copy()
    if not s.Placement.isIdentity():
        m = s.Placement.toMatrix()
        s.Placement = App.Placement()
        s.transformShape(m, True)
    return s


def inside_point(face):
    """A point inside a face (on it, away from its edges). Found from its mesh, not its parameters,
    which do not match a PartDesign feature's placed faces."""
    pts, tris = face.tessellate(0.05)
    if not tris:
        return face.Vertexes[0].Point
    def area(t):
        a, b, c = (pts[k] for k in t)
        return (b - a).cross(c - a).Length
    a, b, c = (pts[k] for k in max(tris, key=area))
    centre = (a + b + c) * (1.0 / 3)
    return face.distToShape(Part.Vertex(centre))[1][0][0]


def outward(shape, f):
    """The outward normal of a flat face of a solid."""
    n = f.normalAt(0, 0)
    return n if not shape.isInside(inside_point(f) + n * EPS, 1e-7, True) else n * -1


UP = V(0.001, 0.01, 1).normalize()


def sheet_face(shape, faces):
    """The biggest flat face next to the cut's faces: the side of the sheet the cut goes through. Of
    the two sides the one facing up (+Z, then +Y, then +X) is taken."""
    near = {}
    for i in faces:
        for j in neighbours(shape, i):
            if j not in faces and _plane(shape.Faces[j]):
                near[j] = shape.Faces[j]
    if not near:
        return None
    big = max(f.Area for f in near.values())
    sides = [j for j, f in near.items() if f.Area > big * 0.5]
    n = near[max(sides, key=lambda j: near[j].Area)].normalAt(0, 0)
    sides = [j for j in sides if abs(abs(near[j].normalAt(0, 0).dot(n)) - 1) < 1e-7]
    return max(sides, key=lambda j: outward(shape, near[j]).dot(UP))


def sheet_normal(shape, i):
    """The sheet's outward normal at the cut face i, else None (a face on no flat wall)."""
    j = sheet_face(shape, [i])
    if j is None:
        return None
    return outward(shape, shape.Faces[j])


def _bend(f, n):
    """A bend of the sheet: a cylinder whose axis lies in the sheet."""
    return f.Surface.TypeId == "Part::GeomCylinder" and abs(f.Surface.Axis.dot(n)) < 1e-6


def _slanted(f, n):
    """A face of a cut that is not square to the sheet."""
    return not _side(f, n) and not _square(f, n) and not _bend(f, n)


def propagate(shape, i, n):
    """Auto Propagation: the faces of the cut that face i belongs to. They are the slanted faces joined
    to it, also through a square wall that lies between slanted ones only (the sheet's sides, its bends
    and its square outer edges are left out)."""
    seen, todo = {i}, [i]
    while todo:
        k = todo.pop()
        for j in neighbours(shape, k):
            f = shape.Faces[j]
            if j in seen:
                continue
            if _slanted(f, n):
                seen.add(j)
                todo.append(j)
            elif _square(f, n):
                around = [m for m in neighbours(shape, j) if not _side(shape.Faces[m], n)]
                if all(_slanted(shape.Faces[m], n) for m in around):
                    seen.add(j)
                    todo += [m for m in around if m not in seen]
                    seen.update(around)
    return sorted(seen)


def thickness_at(shape, face, n):
    """The sheet's thickness under a flat face (outward normal n)."""
    p = inside_point(face)
    ray = Part.LineSegment(p + n * EPS, p - n * shape.BoundBox.DiagonalLength).toShape()
    inside = shape.common(ray)
    return inside.Edges[0].Length if inside.Edges else None


def region(shape, point, n):
    """The part's material on the plane through point (normal n), as a face."""
    wires = shape.slice(n, point.dot(n))
    return Part.makeFace(wires, "Part::FaceMakerBullseye") if wires else None


def prism(face, direction, length):
    f = face.copy()
    f.translate(direction * -length)
    return f.extrude(direction * (2 * length))


def normal_cut(shape, faces, thickness=None, extent=True, plane=None, direction=None, optimize=True):
    """The part with one cut's faces made square to the sheet (or along direction).
    extent: what is cut on either side of the sheet goes through. Else the cut follows its outline on
    plane (a point and a normal; by default the sheet's side)."""
    top = sheet_face(shape, faces)
    if top is None:
        raise ValueError("Normal Cut works on the flat walls of the sheet; this cut is not on one.")
    tf = shape.Faces[top]
    n = outward(shape, tf)
    p0 = inside_point(tf)
    t = float(thickness) if thickness else thickness_at(shape, tf, n)
    if not t:
        raise ValueError("Normal Cut: the sheet's thickness cannot be found here.")
    d = n if direction is None or direction.Length < 1e-9 else V(direction).normalize()
    if abs(d.dot(n)) < 1e-3:
        raise ValueError("The cut direction lies in the sheet; pick a face or edge across it.")
    length = 2 * t / abs(d.dot(n)) + 1
    # the wall's slab around the cut only
    x = V(1, 0, 0) - n * n.x if abs(n.x) < 0.9 else V(0, 1, 0) - n * n.y
    x.normalize()
    y = n.cross(x)
    pts = []
    for i in faces:
        for e in shape.Faces[i].Edges:
            pts += e.discretize(16)
    us = [(p - p0).dot(x) for p in pts]
    vs = [(p - p0).dot(y) for p in pts]
    corners = [p0 + x * u + y * v for u, v in ((min(us) - t, min(vs) - t), (max(us) + t, min(vs) - t),
                                                (max(us) + t, max(vs) + t), (min(us) - t, max(vs) + t))]
    rect = Part.Face(Part.makePolygon(corners + corners[:1]))
    zone = prism(rect, d, length).common(rect.extrude(n * -t))
    if extent:
        top_r = region(shape, p0 - n * EPS, n)
        bottom_r = region(shape, p0 - n * (t - EPS), n)
        if top_r is None or bottom_r is None:
            raise ValueError("Normal Cut: the wall does not go through the sheet here.")
        keep = prism(top_r, d, length).common(prism(bottom_r, d, length))
    else:
        point, normal = plane if plane is not None else (p0, n * -1)
        depth = (p0 - point).dot(n)
        if not (-1e-7 <= depth <= t + 1e-7):
            raise ValueError("The offset plane does not cross the sheet.")
        depth = min(max(depth, EPS), t - EPS)        # on a side: just inside it
        r = region(shape, p0 - n * depth, n)
        if r is None:
            raise ValueError("Normal Cut: the offset plane does not cross the sheet here.")
        keep = prism(r, d, length)
    out = shape.cut(zone).fuse(zone.common(keep))
    return out.removeSplitter() if optimize else out


def offset_plane(ref_point, ref_normal, offset):
    """The plane at offset from the picked face or plane, toward its normal."""
    return V(ref_point) + V(ref_normal) * float(offset), V(ref_normal)


# ================================================================ feature
_LAST = None        # the open Normal Cut PropertyManager


class SWNormalCut:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyStringList", "Faces", GROUP, "Faces For Normal Cut, as picked")
        add("App::PropertyVectorList", "FacePoints", GROUP, "A point on each face")
        add("App::PropertyIntegerList", "FaceGroups", GROUP, "The group of each face (0 = Group1)")
        add("App::PropertyInteger", "GroupCount", GROUP, "Number of groups")
        add("App::PropertyBool", "AutoPropagation", GROUP, "One pick collects the whole cut")
        add("App::PropertyString", "DirectionRef", GROUP, "Cut Direction: the face or edge picked")
        add("App::PropertyVector", "Direction", GROUP, "Cut Direction (zero: square to the sheet)")
        add("App::PropertyBool", "OptimizeGeometry", GROUP, "Merge the faces the new cut leaves")
        add("App::PropertyEnumeration", "Parameter", GROUP, "Extent or Offset plane")
        add("App::PropertyString", "PlaneRef", GROUP, "Offset plane: the face or plane picked")
        add("App::PropertyVector", "PlanePoint", GROUP, "A point on the picked plane")
        add("App::PropertyVector", "PlaneNormal", GROUP, "The picked plane's normal, into the sheet")
        add("App::PropertyDistance", "Offset", GROUP, "Offset from the picked plane, into the sheet")
        obj.Parameter = list(KINDS)
        obj.AutoPropagation = True
        obj.OptimizeGeometry = True
        obj.GroupCount = 1
        obj.Proxy = self

    def execute(self, obj):
        base = obj.BaseFeature
        if base is None:
            raise ValueError("Normal Cut: needs a sheet metal part")
        shape = baked(base.Shape)
        cut = owner(obj)
        if not obj.FacePoints or (cut is not None and getattr(cut, "Suppressed", False)):
            obj.Shape = shape   # the Extruded Cut it squares is suppressed: nothing to square
            return
        groups = {}
        for p, g in zip(obj.FacePoints, list(obj.FaceGroups) + [0] * len(obj.FacePoints)):
            groups.setdefault(g, []).append(p)
        t = _thickness(obj)
        out = shape
        for g in sorted(groups):
            faces = []
            for p in groups[g]:
                i = face_at(out, p)
                if i is None:
                    raise ValueError("Normal Cut: a picked face is gone; edit the feature and pick it again")
                faces.append(i)
            plane = None
            if obj.Parameter == "Offset plane" and obj.PlaneNormal.Length > 1e-9:
                plane = offset_plane(obj.PlanePoint, obj.PlaneNormal, obj.Offset)
            elif obj.Parameter == "Offset plane":
                top = sheet_face(out, faces)
                if top is not None:
                    tf = out.Faces[top]
                    n = outward(out, tf)
                    plane = offset_plane(inside_point(tf), n * -1, obj.Offset)
            out = normal_cut(out, faces, t, obj.Parameter == "Extent", plane, obj.Direction, obj.OptimizeGeometry)
        obj.Shape = out

    def onDocumentRestored(self, obj):
        if App.GuiUp:
            name, doc = obj.Name, obj.Document.Name
            QtCore.QTimer.singleShot(0, lambda: _hide_later(doc, name))     # once the part has opened

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _thickness(obj):
    body = next((p for p in obj.InList if p.TypeId == "PartDesign::Body"), None)
    base = smflatten.root(body) if body is not None else None
    t = getattr(base, "Thickness", None)
    return float(t) if t else None


def owner(obj):
    """The Extruded Cut whose Normal cut option this feature does (its row is that cut's), or None."""
    for o in obj.Document.Objects:
        if getattr(o, "SWNormalCutName", "") == obj.Name or getattr(o, "SWNormalCutFeature", None) is obj:
            return o
    return None


def hide_row(obj):
    ""
    try:
        shown = owner(obj) is None
        if obj.ViewObject is not None and obj.ViewObject.ShowInTree != shown:
            obj.ViewObject.ShowInTree = shown
            for view in Gui.getMainWindow().findChildren(QtWidgets.QTreeView, "SWFeatureTree"):
                model = view.model()
                if hasattr(model, "soon"):
                    model.soon()        # the feature tree mirrors FreeCAD's: build it again
    except Exception as _fw_err:
        _fw_log("smnormalcut.hide_row", _fw_err)


def is_normal_cut(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWNormalCut"


class ViewProviderNormalCut:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        name, doc = vobj.Object.Name, vobj.Object.Document.Name
        QtCore.QTimer.singleShot(0, lambda: _hide_later(doc, name))     # once the part has loaded

    def getIcon(self):
        return _icon(ICON)

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


def _hide_later(doc, name, tries=0):
    try:
        obj = App.getDocument(doc).getObject(name)
    except Exception:
        return
    if obj is not None:
        cut = owner(obj)
        if cut is None and tries < 6:
            # the part is still opening (its cut not read yet): look again shortly
            QtCore.QTimer.singleShot(500, lambda: _hide_later(doc, name, tries + 1))
            return
        if cut is not None and "SWNormalCutFeature" in cut.PropertiesList:
            from . import smextrude
            smextrude.set_normal_cut(cut, obj)      # an older part: the link becomes a name
            cut.purgeTouched()                      # nothing about its shape changed
        hide_row(obj)


def make(body):
    doc = body.Document
    base = body.Tip
    obj = doc.addObject("PartDesign::FeaturePython", "NormalCut")
    SWNormalCut(obj)
    if App.GuiUp:
        ViewProviderNormalCut(obj.ViewObject)
    body.addObject(obj)
    obj.Label = naming.next_label(doc, "Normal Cut")
    if base is not None:
        try:
            base.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("smnormalcut.py:371", _fw_err)
    return obj


# ================================================================ PropertyManager
class Panel:
    """The Normal Cut PropertyManager."""
    HINT = "Select a face of the cut to make normal."

    def __init__(self, obj, new):
        global _LAST
        _LAST = self
        self.obj = obj
        self.new = new
        self.pick_error = ""
        self.group = 0
        sel = _box("Selections")
        f = sel.layout()
        f.addRow(QtWidgets.QLabel("Groups:"))
        self.groups = QtWidgets.QListWidget()
        self.groups.setObjectName("SWSMNormalGroups")
        self.groups.setMaximumHeight(58)
        f.addRow(self.groups)
        self.new_group = QtWidgets.QPushButton("New Group")
        self.new_group.setObjectName("SWSMNormalNewGroup")
        self.new_group.clicked.connect(self.add_group)
        f.addRow(self.new_group)

        faces = _box("Faces For Normal Cut")
        f = faces.layout()
        self.faces = _list("SWSMNormalFaces", "#d6ecff", "Faces of the cut to make normal", rows=4)
        f.addRow(self.faces)
        self.auto = QtWidgets.QCheckBox("Auto Propagation")
        self.auto.setObjectName("SWSMNormalAuto")
        self.auto.setChecked(bool(obj.AutoPropagation))
        f.addRow(self.auto)
        f.addRow(QtWidgets.QLabel("Cut Direction"))
        self.direction = _list("SWSMNormalDirection", "#ffd6ec", "Cut Direction: a face or a straight edge "
                               "(empty: square to the sheet)")
        f.addRow(self.direction)
        self.optimize = QtWidgets.QCheckBox("Optimize Geometry")
        self.optimize.setObjectName("SWSMNormalOptimize")
        self.optimize.setChecked(bool(obj.OptimizeGeometry))
        f.addRow(self.optimize)

        params = _box("Normal Cut Parameters")
        f = params.layout()
        self.extent = _radio("SWSMNormalExtent", "Extent")
        self.offset_plane = _radio("SWSMNormalOffsetPlane", "Offset plane")
        (self.extent if obj.Parameter == "Extent" else self.offset_plane).setChecked(True)
        f.addRow(self.extent)
        f.addRow(self.offset_plane)
        self.plane = _list("SWSMNormalPlane", "#e3d6ff", "Offset plane: a face or plane (empty: the sheet's side)")
        f.addRow(self.plane)
        self.offset = _spin("SWSMNormalOffset", float(obj.Offset), -1000.0, 1000.0, step=0.1)
        self.offset.setToolTip("Offset distance into the sheet")
        f.addRow(self.offset)
        self.preview = QtWidgets.QCheckBox("Show Preview Graphics")
        self.preview.setObjectName("SWSMNormalPreview")
        self.preview.setChecked(True)
        f.addRow(self.preview)
        self.error = error_label()
        f.addRow(self.error)

        sel.setProperty("swstyle_pm_title", TITLE)
        sel.setProperty("swstyle_pm_icon", ICON)
        self.form = [sel, faces, params]
        self.lists = [self.faces, self.direction, self.plane]
        self.active = self.faces
        self.keys = _DeleteKey(self)
        for w in self.lists + [self.groups]:
            w.installEventFilter(self.keys)
        self.groups.currentRowChanged.connect(self._group_changed)
        self.auto.toggled.connect(self._changed)
        self.optimize.toggled.connect(self._changed)
        self.extent.toggled.connect(self._changed)
        self.offset.valueChanged.connect(self._changed)
        self.preview.toggled.connect(self._show_preview)
        self._fill()
        self._show()
        self._report()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    # ---------------------------------------------------------------- lists
    def set_active(self, w):
        if w in self.lists:
            self.active = w

    def _groups(self):
        return list(self.obj.FaceGroups) + [0] * (len(self.obj.FacePoints) - len(self.obj.FaceGroups))

    def _fill(self):
        groups = self._groups()
        self.groups.blockSignals(True)
        self.groups.clear()
        for g in range(max(1, int(self.obj.GroupCount))):
            self.groups.addItem("Group%d , <%d>" % (g + 1, groups.count(g)))
        self.groups.setCurrentRow(self.group)
        self.groups.blockSignals(False)
        self.faces.clear()
        for name, g in zip(self.obj.Faces, groups):
            if g == self.group:
                self.faces.addItem(name)
        self.direction.clear()
        if self.obj.DirectionRef:
            self.direction.addItem(self.obj.DirectionRef)
        self.plane.clear()
        if self.obj.PlaneRef:
            self.plane.addItem(self.obj.PlaneRef)

    def _show(self):
        offset = self.offset_plane.isChecked()
        self.plane.setEnabled(offset)
        self.offset.setEnabled(offset)

    def _group_changed(self, row):
        if row >= 0:
            self.group = row
            self._fill()
            self.set_active(self.faces)

    def add_group(self):
        groups = self._groups()
        if groups.count(int(self.obj.GroupCount) - 1) == 0 and int(self.obj.GroupCount) > 1:
            self.group = int(self.obj.GroupCount) - 1       # the last group is still empty
        else:
            self.obj.GroupCount = int(self.obj.GroupCount) + 1
            self.group = int(self.obj.GroupCount) - 1
        self._fill()
        self.set_active(self.faces)
        self._report()

    def remove_current(self, w):
        if w is self.faces and w.currentRow() >= 0:
            mine = [k for k, g in enumerate(self._groups()) if g == self.group]
            self._drop([mine[w.currentRow()]])
        elif w is self.groups and w.currentRow() >= 0:
            self._drop_group(w.currentRow())
        elif w is self.direction:
            self.obj.DirectionRef = ""
            self.obj.Direction = V()
            self._apply()
        elif w is self.plane:
            self.obj.PlaneRef = ""
            self.obj.PlaneNormal = V()
            self._apply()

    def _drop_group(self, g):
        ""
        groups = self._groups()
        count = max(1, int(self.obj.GroupCount))
        keep = [k for k, x in enumerate(groups) if x != g]
        if count > 1:
            self.obj.Faces = [self.obj.Faces[k] for k in keep]
            self.obj.FacePoints = [self.obj.FacePoints[k] for k in keep]
            self.obj.FaceGroups = [groups[k] - (1 if groups[k] > g else 0) for k in keep]
            self.obj.GroupCount = count - 1
            self.group = min(self.group if self.group < g else max(0, self.group - 1), count - 2)
            self._apply()
        else:
            self._drop([k for k, x in enumerate(groups) if x == g])

    def _drop(self, rows):
        names, points, groups = list(self.obj.Faces), list(self.obj.FacePoints), self._groups()
        for k in sorted(rows, reverse=True):
            del names[k], points[k], groups[k]
        self.obj.Faces, self.obj.FacePoints, self.obj.FaceGroups = names, points, groups
        self._apply()

    # ---------------------------------------------------------------- picks
    def addSelection(self, doc, name, sub, point):
        if sub.startswith(("Face", "Edge")) or not sub:
            at = App.Vector(*point) if point else None
            QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub, at))

    def _picked(self, doc_name, name, sub, at):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smnormalcut.py:551", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None:
            return
        self.pick_error = ""
        if self.active is self.direction:
            self._pick_direction(picked, sub)
        elif self.active is self.plane:
            self._pick_plane(picked, sub, at)
        elif sub.startswith("Face"):
            self._pick_face(picked, sub, at)
        self._apply()

    def _pick_face(self, picked, sub, at):
        face = picked.Shape.getElement(sub)
        if at is None or face.distToShape(Part.Vertex(at))[0] > 1e-4:
            at = inside_point(face)
        base = baked(self.obj.BaseFeature.Shape)
        i = face_at(base, at)
        if i is None:
            self.pick_error = "Select a face of the part."
            return
        f = base.Faces[i]
        n = sheet_normal(base, i)
        if n is None or _side(f, n):
            self.pick_error = "Select a face of a cut through the sheet."
            return
        names, points, groups = list(self.obj.Faces), list(self.obj.FacePoints), self._groups()
        found = ["Face%d" % (i + 1)]
        if self.auto.isChecked():
            found = ["Face%d" % (k + 1) for k in propagate(base, i, n)]
        if "Face%d" % (i + 1) in names and groups[names.index("Face%d" % (i + 1))] == self.group:
            for name in found:      # a second pick takes the cut out again
                if name in names:
                    k = names.index(name)
                    del names[k], points[k], groups[k]
        else:
            for name in found:
                if name in names:
                    continue
                names.append(name)
                points.append(inside_point(base.getElement(name)) if name != "Face%d" % (i + 1) else at)
                groups.append(self.group)
        self.obj.Faces, self.obj.FacePoints, self.obj.FaceGroups = names, points, groups

    def _pick_direction(self, picked, sub):
        item = picked.Shape.getElement(sub) if sub else None
        if item is not None and sub.startswith("Face") and _plane(item):
            d = item.normalAt(0, 0)
        elif item is not None and sub.startswith("Edge") and item.Curve.TypeId == "Part::GeomLine":
            d = item.Vertexes[-1].Point - item.Vertexes[0].Point
        else:
            self.pick_error = "Select a flat face or a straight edge for the cut direction."
            return
        self.obj.Direction = d.normalize()
        self.obj.DirectionRef = sub
        self.set_active(self.faces)

    def _pick_plane(self, picked, sub, at):
        shape = picked.Shape
        if sub.startswith("Face") and _plane(shape.getElement(sub)):
            f = shape.getElement(sub)
            point, n = inside_point(f), f.normalAt(0, 0)
            base = self.obj.BaseFeature.Shape
            if base.isInside(point - n * EPS * 2, 1e-7, True) and not base.isInside(point + n * EPS * 2, 1e-7, True):
                n = n * -1          # a side of the sheet: the offset goes into it
            label = sub
        elif not sub and picked.TypeId in ("PartDesign::Plane", "App::Plane"):
            pl = picked.getGlobalPlacement() if hasattr(picked, "getGlobalPlacement") else picked.Placement
            point, n = pl.Base, pl.Rotation.multVec(V(0, 0, 1))
            label = picked.Label
        else:
            self.pick_error = "Select a flat face or a plane for the offset plane."
            return
        self.obj.PlanePoint, self.obj.PlaneNormal, self.obj.PlaneRef = point, n, label
        self.set_active(self.faces)

    # ---------------------------------------------------------------- result
    def _changed(self, *_a):
        self.obj.AutoPropagation = self.auto.isChecked()
        self.obj.OptimizeGeometry = self.optimize.isChecked()
        self.obj.Parameter = "Extent" if self.extent.isChecked() else "Offset plane"
        self.obj.Offset = self.offset.value()
        self._show()
        self._apply()

    def _apply(self):
        doc = self.obj.Document
        if doc.Recomputing:
            QtCore.QTimer.singleShot(50, self._apply)
            return
        self.obj.touch()
        doc.recompute()
        self._fill()
        self._report()

    def _show_preview(self, on):
        try:
            self.obj.ViewObject.Visibility = on
            self.obj.BaseFeature.ViewObject.Visibility = not on
        except Exception as _fw_err:
            _fw_log("smnormalcut.py:652", _fw_err)

    def _report(self):
        if "Invalid" in self.obj.State:
            text = self.obj.getStatusString()
        elif self.pick_error:
            text = self.pick_error
        elif not self.obj.FacePoints:
            text = self.HINT
        else:
            text = ""
        self.error.setText(text)
        self.error.setVisible(bool(text))
        return not text

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smnormalcut.py:674", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smnormalcut.py:680", _fw_err)

    def accept(self):
        self.pick_error = ""
        if not self._report():
            return False
        self._show_preview(True)
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        base = self.obj.BaseFeature if self.new else None
        doc.abortTransaction()
        doc.recompute()
        if base is not None:
            try:
                base.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("smnormalcut.py:700", _fw_err)
        self._close()
        return True


# ================================================================ command
def _sheet_body():
    """The active body when it is sheet metal, folded and not in a dialog."""
    if App.ActiveDocument is None or smflatten.blocked():
        return None
    try:
        if Gui.Control.activeDialog():
            return None
        body = smflatten._body()    # the active body when it is sheet metal, else the part's sheet metal body
    except Exception as _fw_err:
        _fw_log("smnormalcut.py:723", _fw_err)
        return None
    if body is None or smflatten.root(body) is None or body.Tip is None or body.Tip.Shape.isNull():
        return None
    return body


def start():
    body = _sheet_body()
    if body is None:
        return
    picked = [(o.Document.Name, o.Object.Name, sub, App.Vector(p)) for o in Gui.Selection.getSelectionEx()
              for sub, p in zip(o.SubElementNames, o.PickedPoints) if sub.startswith("Face")]
    doc = body.Document
    doc.openTransaction(TITLE)
    try:
        obj = make(body)
        doc.recompute()
        panel = Panel(obj, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    for doc_name, name, sub, at in picked:
        panel._picked(doc_name, name, sub, at)


class Command:
    def GetResources(self):
        return {"Pixmap": _icon(ICON), "MenuText": TITLE,
                "ToolTip": "Makes the walls of a cut square to the sheet."}

    def IsActive(self):
        return _sheet_body() is not None

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
