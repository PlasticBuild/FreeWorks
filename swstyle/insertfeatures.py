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
import Part

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

from . import simplefeature as sf
from .simplefeature import Field

V = App.Vector
TINY = 1e-3


def _allow_bodies(obj):
    body = obj.getParentGeoFeatureGroup()
    if body is not None and "AllowCompound" in body.PropertiesList and not body.AllowCompound:
        body.AllowCompound = True


def _big_plane(face, base):
    """A flat face made large enough to cross the whole part."""
    surface = face.Surface
    box = base.BoundBox
    size = max(box.DiagonalLength, 1.0) * 2
    point = surface.projectPoint(box.Center)
    plane = Part.Plane(point, surface.Axis)
    u, v = plane.parameter(point)
    return plane.toShape(u - size, u + size, v - size, v + size)


def _knives(obj, base):
    """Faces that cut the part: planes and flat faces made big, other faces as they are, and the
    wires of sketches swept through the part along the sketch normal."""
    out = []
    reach = max(base.BoundBox.DiagonalLength, 1.0) * 2
    for source, shape in sf.elements(obj, "Tools"):
        if shape.isNull():
            continue
        faces = shape.Faces
        wires = [w for w in shape.Wires if not faces] if not faces else []
        if not faces and not wires and shape.Edges:
            wires = [Part.Wire(Part.__sortEdges__(shape.Edges))] if hasattr(Part, "__sortEdges__") else \
                [Part.Wire(e) for e in shape.Edges]
        for face in faces:
            out.append(_big_plane(face, base) if isinstance(face.Surface, Part.Plane) else face)
        if wires:
            normal = getattr(source, "Placement", App.Placement()).Rotation.multVec(V(0, 0, 1))
            try:
                normal = Part.Face(Part.Wire(wires[0])).normalAt(0, 0) if wires[0].isClosed() else normal
            except Exception as _fw_err:
                _fw_log("insertfeatures.py:73", _fw_err)
            for wire in wires:
                start = wire.copy()
                start.translate(normal * -reach)
                out.extend(start.extrude(normal * (2 * reach)).Faces)
    return out


def _targets(obj, base):
    """Target Bodies: (the solids the trim tools cut, the solids left as they are). All bodies, or
    the bodies picked (a face, edge or vertex of each)."""
    solids = list(base.Solids)
    if getattr(obj, "Target", "All bodies") != "Selected bodies" or "TargetBodies" not in obj.PropertiesList:
        return solids, []
    from .loftsweep import body_holds
    picked = [shape for _o, shape in sf.elements(obj, "TargetBodies")]
    if not picked:
        return solids, []
    cut = [s for s in solids if any(body_holds(s, p) for p in picked)]
    return cut, [s for s in solids if not any(s.isSame(c) for c in cut)]


def _pieces(obj, base):
    """The part split by the trim tools, in a fixed order (by place along X, then Y, then Z)."""
    knives = _knives(obj, base)
    if not knives:
        return []
    from BOPTools import SplitAPI
    cut, _left = _targets(obj, base)
    if not cut:
        return []
    target = cut[0] if len(cut) == 1 else Part.makeCompound(cut)
    solids = SplitAPI.slice(target, knives, "Split", 1e-6).Solids
    return sorted(solids, key=lambda s: tuple(round(c, 4) for c in (s.CenterOfMass.x, s.CenterOfMass.y,
                                                                     s.CenterOfMass.z)))


def _keep_list(text, count):
    text = (text or "").strip().lower()
    if text in ("", "all"):
        return list(range(count))
    out = []
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a) - 1, int(b)))
        elif part:
            out.append(int(part) - 1)
    bad = [i + 1 for i in out if i < 0 or i >= count]
    if bad:
        raise RuntimeError("There are only %d bodies: no body %s" % (count, ", ".join(map(str, bad))))
    return sorted(set(out))


def _split(obj, base):
    if "Files" not in obj.PropertiesList:      # made with the feature: opening its PM changes nothing
        obj.addProperty("App::PropertyString", "Files", "Split", "Bodies saved to files (JSON)")
    pieces = _pieces(obj, base)
    if not pieces:
        return None, None
    if len(pieces) < 2:
        raise RuntimeError("The trim tools do not cut the part")
    keep = _keep_list(obj.Keep, len(pieces))
    if not keep:
        raise RuntimeError("Keep at least one body")
    text = "%d bodies: %s" % (len(pieces), ", ".join(
        "%d (%.0f mm³)" % (i + 1, p.Volume) for i, p in enumerate(pieces)))
    if obj.Bodies != text:
        obj.Bodies = text
    _allow_bodies(obj)
    files = split_files(obj)
    if getattr(obj, "Consume", False):
        keep = [i for i in keep if str(i + 1) not in files]     # Consume cut bodies: saved ones leave
        if not keep:
            raise RuntimeError("Every kept body is saved to a file and consumed: keep one in the part")
    kept = [pieces[i] for i in keep] + _targets(obj, base)[1]
    return Part.makeCompound(kept), None


def split_files(obj):
    ""
    import json
    try:
        return json.loads(getattr(obj, "Files", "") or "{}")
    except Exception:
        return {}


def save_split_bodies(obj):
    """Save the bodies that have a file name, each as its own part (Propagate visual properties gives
    them the part's colour). Returns the paths written."""
    files = split_files(obj)
    if not files:
        return []
    base = obj.BaseFeature.Shape if getattr(obj, "BaseFeature", None) is not None else None
    if base is None:
        return []
    pieces = _pieces(obj, base)
    colour = None
    if getattr(obj, "Propagate", True) and App.GuiUp:
        try:
            colour = obj.BaseFeature.ViewObject.ShapeColor
        except Exception:
            colour = None
    keep_active = App.ActiveDocument
    out = []
    for number, path in sorted(files.items(), key=lambda kv: int(kv[0])):
        i = int(number) - 1
        if not (0 <= i < len(pieces)) or not path:
            continue
        try:
            doc = App.newDocument("SplitBody", hidden=True)
        except TypeError:
            doc = App.newDocument("SplitBody")
        try:
            body = doc.addObject("Part::Feature", "Body%d" % (i + 1))
            body.Shape = pieces[i]
            if colour is not None and App.GuiUp and body.ViewObject is not None:
                body.ViewObject.ShapeColor = colour
            doc.recompute()
            doc.saveAs(path)
            out.append(path)
        finally:
            App.closeDocument(doc.Name)
    if keep_active is not None:
        try:
            App.setActiveDocument(keep_active.Name)
        except Exception as _fw_err:
            _fw_log("insertfeatures.py:202", _fw_err)
    return out


if Gui is not None:
    class SplitPanel(sf.Panel):
        ""


        def __init__(self, obj):
            if "Files" not in obj.PropertiesList:
                obj.addProperty("App::PropertyString", "Files", "Split", "Bodies saved to files (JSON)")
            super().__init__(obj)
            keep = self.widgets["Keep"]
            form = keep.parentWidget().layout()
            row, _role = form.getWidgetPosition(keep)
            for r in (row - 1, row):
                item = form.itemAt(r, QtWidgets.QFormLayout.SpanningRole)
                if item is not None and item.widget() is not None:
                    item.widget().hide()
            self.cut = QtWidgets.QPushButton("Cut Part")
            self.cut.setObjectName("SWSplitCutPart")
            self.cut.clicked.connect(self.cut_part)
            self.table = QtWidgets.QTableWidget(0, 3)
            self.table.setObjectName("SWSplitBodies")
            self.table.setHorizontalHeaderLabels(["", "Body", "File"])
            self.table.verticalHeader().hide()

            head = self.table.horizontalHeader()
            head.setMinimumSectionSize(22)
            head.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
            head.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
            head.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
            self.table.setMinimumHeight(110)
            self.table.itemChanged.connect(self._ticked)
            self.table.cellDoubleClicked.connect(self._file_for)
            form.insertRow(row + 1, self.cut)
            form.insertRow(row + 2, self.table)
            self.auto = QtWidgets.QPushButton("Auto-assign Names")
            self.auto.setObjectName("SWSplitAutoNames")
            self.auto.setToolTip("Gives every resulting body a file name next to the part")
            self.auto.clicked.connect(self.auto_names)
            form.insertRow(row + 3, self.auto)
            self.fill()

        def auto_names(self):
            import json
            import os
            doc = self.obj.Document
            folder = os.path.dirname(doc.FileName) if doc.FileName else App.getUserAppDataDir()
            part = os.path.splitext(os.path.basename(doc.FileName))[0] if doc.FileName else doc.Label
            files = split_files(self.obj)
            for r in range(self.table.rowCount()):
                files[str(r + 1)] = os.path.join(folder, "%s-Body%d.FCStd" % (part, r + 1))
            self.obj.Files = json.dumps(files)
            self.obj.Document.recompute()
            self.fill()

        def cut_part(self):
            self.obj.touch()
            self.obj.Document.recompute()
            self.fill()
            self._show()

        def fill(self):
            base = self.obj.BaseFeature.Shape if self.obj.BaseFeature is not None else None
            try:
                pieces = _pieces(self.obj, base) if base is not None else []
            except Exception:
                pieces = []
            try:
                keep = set(_keep_list(self.obj.Keep, len(pieces)))
            except Exception:
                keep = set(range(len(pieces)))
            files = split_files(self.obj)
            self.table.blockSignals(True)
            self.table.setRowCount(len(pieces))
            for i, p in enumerate(pieces):
                tick = QtWidgets.QTableWidgetItem()
                tick.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
                tick.setCheckState(QtCore.Qt.Checked if i in keep else QtCore.Qt.Unchecked)
                self.table.setItem(i, 0, tick)
                name = QtWidgets.QTableWidgetItem("Body %d (%.0f mm³)" % (i + 1, p.Volume))
                name.setFlags(QtCore.Qt.ItemIsEnabled)
                self.table.setItem(i, 1, name)
                f = QtWidgets.QTableWidgetItem(files.get(str(i + 1), "<None>"))
                f.setToolTip("Double-click to save this body to its own part file")
                f.setFlags(QtCore.Qt.ItemIsEnabled)
                self.table.setItem(i, 2, f)
            self.table.blockSignals(False)

        def set_keep(self, numbers):
            n = self.table.rowCount()
            self.obj.Keep = "all" if sorted(numbers) == list(range(1, n + 1)) else ",".join(str(k) for k in sorted(numbers))
            self.obj.Document.recompute()
            self.fill()
            self._show()

        def _ticked(self, item):
            if item.column() != 0:
                return
            ticked = [r + 1 for r in range(self.table.rowCount())
                      if self.table.item(r, 0).checkState() == QtCore.Qt.Checked]
            if not ticked:
                self.fill()
                return
            self.set_keep(ticked)

        def set_file(self, number, path):
            import json
            files = split_files(self.obj)
            if path:
                files[str(number)] = path
            else:
                files.pop(str(number), None)
            self.obj.Files = json.dumps(files)
            self.obj.Document.recompute()
            self.fill()

        def _file_for(self, row, col):
            if col != 2:
                return
            path, _ = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save Body",
                                                            "Body%d.FCStd" % (row + 1), "FreeCAD part (*.FCStd)")
            self.set_file(row + 1, path)

        def accept(self):
            ok = super().accept()
            if ok:
                try:
                    save_split_bodies(self.obj)
                except Exception as error:
                    App.Console.PrintWarning("FreeCAD: Split: saving bodies: %s\n" % error)
            return ok
else:
    SplitPanel = None


SPLIT = sf.Spec(
    "SWStyle_Split", "Split", "Split", "Splits the part into several bodies with planes, faces or sketches.",
    "FEATURES_SPLIT", "Part_SliceApart",
    [Field("Tools", "pick", "Trim Tools", tip="Planes, faces, surfaces or sketches that cut the part",
           what=("Face", ""), many=True),
     Field("Target", "radio", "Target Bodies", "All bodies", values=["All bodies", "Selected bodies"],
           box="Target Bodies"),
     Field("TargetBodies", "pick", "Bodies to split", tip="Pick a face of each body the trim tools cut",
           what=("Face", "Edge", "Vertex"), many=True, optional=True,
           shown=lambda o: getattr(o, "Target", "") == "Selected bodies", box="Target Bodies"),
     Field("Bodies", "info", "Resulting bodies", ""),
     Field("Keep", "text", "Bodies to keep", "all",
           tip="Which of the resulting bodies stay: all, or their numbers from the list above"),
     Field("Consume", "bool", "Consume cut bodies", False),
     Field("Propagate", "bool", "Propagate visual properties", True)],
    _split, refine=False, panel=SplitPanel)


# --------------------------------------------------------------------------- Cavity
def _cavity(obj, base):
    tools = obj.Tools or []
    if not tools:
        return None, None
    cutters = []
    frame = App.Placement()
    if obj.About == "Coordinate System":

        cs = getattr(obj, "CoordinateSystem", None)
        if cs is None:
            raise RuntimeError("Pick the coordinate system to scale about")
        frame = cs.getGlobalPlacement() if hasattr(cs, "getGlobalPlacement") else cs.Placement
        body = obj.getParentGeoFeatureGroup() if hasattr(obj, "getParentGeoFeatureGroup") else None
        if body is not None:
            frame = body.getGlobalPlacement().inverse().multiply(frame)
    for tool in tools:
        shape = Part.getShape(tool)
        if shape.isNull() or not shape.Solids:
            raise RuntimeError("%s has no solid" % tool.Label)
        for solid in shape.Solids:
            if obj.About == "Centroid":
                centre = solid.CenterOfMass
            elif obj.About == "Coordinate System":
                centre = frame.Base
            else:
                centre = V(0, 0, 0)
            if obj.Uniform:
                fx = fy = fz = 1.0 + float(obj.Scale) / 100.0
            else:
                fx, fy, fz = (1.0 + float(obj.ScaleX) / 100.0, 1.0 + float(obj.ScaleY) / 100.0,
                              1.0 + float(obj.ScaleZ) / 100.0)
            if min(fx, fy, fz) <= 0:
                raise RuntimeError("The scale must leave the tool bigger than nothing")
            m = App.Matrix()
            m.move(centre * -1)
            s = App.Matrix()
            s.scale(fx, fy, fz)
            back = App.Matrix()
            back.move(centre)
            if obj.About == "Coordinate System":
                rot = App.Placement(V(), frame.Rotation).toMatrix()
                s = rot.multiply(s.multiply(rot.inverse()))     # X, Y, Z along the coordinate system's axes
            cutters.append(solid.transformGeometry(back.multiply(s.multiply(m))))
    cutter = cutters[0] if len(cutters) == 1 else cutters[0].fuse(cutters[1:])
    common = base.common(cutter)
    if common.isNull() or common.Volume < 1e-9:
        raise RuntimeError("The design part does not overlap this part")
    return base.cut(cutter), common


CAVITY = sf.Spec(
    "SWStyle_Cavity", "Cavity", "Cavity",
    "Cuts the shape of another body out of the part, scaled for shrinkage.", "FEATURES_CAVITY", "Part_Cut",
    [Field("Tools", "pick", "Design Component", tip="The body (or bodies) whose shape is cut out", what="Object",
           many=True),
     Field("About", "enum", "Scale about", "Centroid", values=["Centroid", "Origin", "Coordinate System"]),
     Field("CoordinateSystem", "pick", "Coordinate system", what="Feature", optional=True,
           shown=lambda o: o.About == "Coordinate System"),
     Field("Uniform", "bool", "Uniform scaling", True),
     Field("Scale", "float", "Scale factor (%)", 0.0, low=-50.0, high=50.0, shown=lambda o: o.Uniform),
     Field("ScaleX", "float", "X scale (%)", 0.0, low=-50.0, high=50.0, shown=lambda o: not o.Uniform),
     Field("ScaleY", "float", "Y scale (%)", 0.0, low=-50.0, high=50.0, shown=lambda o: not o.Uniform),
     Field("ScaleZ", "float", "Z scale (%)", 0.0, low=-50.0, high=50.0, shown=lambda o: not o.Uniform)],
    _cavity, subtractive=True)


# --------------------------------------------------------------------------- Join
def _join(obj, base):
    tools = obj.Parts or []
    if not tools:
        return None, None
    shapes = []
    for tool in tools:
        shape = Part.getShape(tool)
        if shape.isNull() or not shape.Solids:
            raise RuntimeError("%s has no solid" % tool.Label)
        shapes.extend(shape.Solids)
    added = shapes[0] if len(shapes) == 1 else shapes[0].fuse(shapes[1:])
    if float(obj.Gap) > 0:
        try:
            added = added.makeOffsetShape(float(obj.Gap), 1e-6, False, False, 0, 0, False)
        except Exception:
            raise RuntimeError("The gap closure could not grow these parts")
    result = base.fuse(added, 1e-6) if base is not None and not base.isNull() else added
    if obj.ForceToSame is False and len(result.Solids) > 1:
        _allow_bodies(obj)
    return result, added


JOIN = sf.Spec(
    "SWStyle_Join", "Join", "Join", "Joins other bodies or parts into this part.", "FEATURES_JOIN", "Part_Fuse",
    [Field("Parts", "pick", "Parts to join", tip="Bodies or parts to join into this one", what="Object", many=True),
     Field("ForceToSame", "bool", "Force to same surface", False),
     Field("Gap", "length", "Gap closure", 0.0)],
    _join, needs_body=False)


# --------------------------------------------------------------------------- Stud Wizard
def _stud_sizes():
    from . import thread
    return thread.SIZES


STUD_TYPES = ["Stud on surface", "Stud on shaft"]


def _stud_on_shaft(obj, base):
    ""

    where = sf.elements(obj, "Position")
    if not where:
        return None, None
    edge = where[0][1]
    if edge.ShapeType != "Edge" or not hasattr(edge.Curve, "Center") or not hasattr(edge.Curve, "Radius"):
        raise RuntimeError("Pick the circular edge at the end of the shaft")
    if base is None or base.isNull():
        raise RuntimeError("Stud on shaft needs the shaft's body")
    centre, radius = V(edge.Curve.Center), float(edge.Curve.Radius)
    axis = V(edge.Curve.Axis).normalize()
    probe = min(radius * 0.5, 0.5)
    inward = axis if base.isInside(centre + axis * probe, 1e-6, True) else axis * -1
    if not base.isInside(centre + inward * probe, 1e-6, True):
        raise RuntimeError("The edge is not at the end of a solid shaft")
    diameter = 2.0 * radius
    sizes = _stud_sizes()
    name, _d, pitch = min(sizes, key=lambda s: abs(s[1] - diameter))
    length = float(obj.Length)
    if length <= 0:
        raise RuntimeError("Thread length must be more than 0")
    tool = Part.Shape()
    pieces = []
    chamfer = min(float(obj.Chamfer), radius / 2.0, length / 2.0)
    if chamfer > 0:
        pieces.append(Part.makeCylinder(diameter, chamfer, V(0, 0, 0), V(0, 0, 1)).cut(
            Part.makeCone(radius - chamfer, radius, chamfer, V(0, 0, 0), V(0, 0, 1))))
    if obj.Undercut and float(obj.UndercutLength) > 0:
        under = float(obj.UndercutLength)
        inner = _undercut_radius(obj, radius, pitch)
        pieces.append(Part.makeCylinder(diameter, under, V(0, 0, length), V(0, 0, 1)).cut(
            Part.makeCylinder(inner, under, V(0, 0, length), V(0, 0, 1))))
    if obj.Thread == "Modeled":
        from . import thread
        pieces.append(thread.groove(radius, pitch, length, False, False))
    place = App.Placement(centre, App.Rotation(V(0, 0, 1), inward))
    result = base
    for piece in pieces:
        piece = piece.copy()
        piece.Placement = place.multiply(piece.Placement)
        result = result.cut(piece)
    try:
        if obj.Size != name:
            obj.Size = name
    except Exception as _fw_err:
        _fw_log("insertfeatures.py:506", _fw_err)
    marker = Part.makeCylinder(radius, length, V(0, 0, 0), V(0, 0, 1))
    marker.Placement = place
    return result, marker


def _undercut_radius(obj, radius, pitch):
    ""
    d = float(getattr(obj, "UndercutDiameter", 0.0) or 0.0)
    r = d / 2.0 if d > 0 else radius - 0.61343 * pitch
    return max(min(r, radius - 1e-3), 0.05)


def _stud(obj, base):
    if getattr(obj, "Type", STUD_TYPES[0]) == "Stud on shaft":
        return _stud_on_shaft(obj, base)
    picked = sf.elements(obj, "Face")
    if not picked:
        return None, None
    face = picked[0][1]
    if face.ShapeType != "Face":
        raise RuntimeError("Pick a flat face or a circular edge")
    centre = face.CenterOfMass
    where = sf.elements(obj, "Position")
    if where:
        shape = where[0][1]
        if shape.ShapeType == "Edge" and hasattr(shape.Curve, "Center"):
            centre = shape.Curve.Center
        elif shape.ShapeType == "Vertex":
            centre = shape.Point
    if not isinstance(face.Surface, Part.Plane):
        raise RuntimeError("Stud Wizard needs a flat face")
    centre = face.Surface.value(*face.Surface.parameter(centre))
    u, v = face.Surface.parameter(centre)
    normal = face.normalAt(u, v).normalize()
    size = dict((s[0], (s[1], s[2])) for s in _stud_sizes())[obj.Size]
    diameter, pitch = size
    length = float(obj.Length)
    if length <= 0:
        raise RuntimeError("Stud length must be more than 0")
    stud = Part.makeCylinder(diameter / 2.0, length + TINY, V(0, 0, -TINY), V(0, 0, 1))
    chamfer = min(float(obj.Chamfer), diameter / 4.0, length / 2.0)
    if chamfer > 0:
        ring = Part.makeCylinder(diameter, chamfer, V(0, 0, length - chamfer), V(0, 0, 1)).cut(
            Part.makeCone(diameter / 2.0, diameter / 2.0 - chamfer, chamfer, V(0, 0, length - chamfer), V(0, 0, 1)))
        stud = stud.cut(ring)
    if obj.Undercut and float(obj.UndercutLength) > 0:
        under = float(obj.UndercutLength)
        neck = Part.makeCylinder(diameter, under, V(0, 0, 0), V(0, 0, 1)).cut(
            Part.makeCylinder(_undercut_radius(obj, diameter / 2.0, pitch), under, V(0, 0, 0), V(0, 0, 1)))
        stud = stud.cut(neck)
    if obj.Thread == "Modeled":
        from . import thread
        start = float(obj.UndercutLength) if obj.Undercut else 0.0
        stud = stud.cut(thread.groove(diameter / 2.0, pitch, max(length - start, pitch), False, False)
                        .translated(V(0, 0, start)))
    rot = App.Rotation(V(0, 0, 1), normal)
    stud.Placement = App.Placement(centre, rot)
    result = base.fuse(stud, 1e-6) if base is not None and not base.isNull() else stud
    return result, stud


STUD = sf.Spec(
    "SWStyle_StudWizard", "Stud Wizard", "Stud", "A threaded stud standing on a flat face.",
    "FEATURES_STUD_WIZARD", "PartDesign_AdditiveCylinder",
    [Field("Type", "radio", "Stud", "Stud on surface", values=STUD_TYPES, legacy="Stud on surface",
           tip="On surface: a new stud stands on a flat face. On shaft: the thread goes on a shaft already there"),
     Field("Face", "pick", "Face for the stud", tip="A flat face", what=("Face",),
           shown=lambda o: getattr(o, "Type", STUD_TYPES[0]) != "Stud on shaft"),
     Field("Position", "pick", "Circular edge or point for the stud center", what=("Edge", "Vertex"),
           optional=True),
     Field("Size", "enum", "Size (ISO metric)", "M6", values=[s[0] for s in _stud_sizes()]),
     Field("Length", "length", "Length", 20.0, tip="Stud length; on a shaft, how far the thread runs from the end"),
     Field("Thread", "enum", "Thread", "Cosmetic", values=["Cosmetic", "Modeled"],
           tip="Cosmetic: a plain cylinder at the thread's size. Modeled: a real helical thread"),
     Field("Chamfer", "length", "End chamfer", 0.5),
     Field("Undercut", "bool", "Undercut", False),
     Field("UndercutLength", "length", "Undercut length", 2.0, shown=lambda o: o.Undercut),
     Field("UndercutDiameter", "length", "Undercut diameter", 0.0, shown=lambda o: o.Undercut,
           tip="The neck's diameter; 0 takes the thread's root diameter")],
    _stud)


ALL = [SPLIT, CAVITY, JOIN, STUD]


def register():
    for spec in ALL:
        sf.register(spec)
