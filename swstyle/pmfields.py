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

from PySide import QtCore, QtWidgets

DONE = "swstyle_pmfields"
MID_PLANE = "Mid Plane"
ONE, TWO, SYMMETRIC = 0, 1, 2     # FreeCAD's sidesMode entries


def _alive(widget):
    try:
        widget.objectName()
        return True
    except RuntimeError:
        return False


def _forget(item):
    """Drop a QLayoutItem wrapper at once: a stale one aliases later Qt objects
    (random 'QLayoutItem has no attribute' errors in event filters)."""
    if item is None or isinstance(item, QtWidgets.QLayout):
        return      # a QLayout is its own QLayoutItem: invalidating it kills the layout
    try:
        try:
            import shiboken6 as shiboken
        except ImportError:
            import shiboken2 as shiboken
        shiboken.invalidate(item)
    except Exception as _fw_err:
        _fw_log("pmfields.py:57", _fw_err)


def purge_stale(root):
    """Drop stale layout-item wrappers that alias widgets under root: a QWidgetItem or QLayoutItem
    wrapper left alive after Qt deleted its item is handed back by findChildren for a new widget at
    the same address, and every dressing that reads it fails ('QLayoutItem' object has no attribute
    'parentWidget'), leaving FreeCAD's bare page."""
    for _ in range(3):
        try:
            found = root.findChildren(QtCore.QObject)
        except RuntimeError:
            return
        stale = [w for w in found if not isinstance(w, QtCore.QObject)]
        if not stale:
            return
        for w in stale:
            _forget(w)
        del stale, found


def sub_layout(layout, i):
    """layout.itemAt(i).layout() without keeping the item wrapper."""
    item = layout.itemAt(i)
    if item is None:
        return None
    found = item.layout()
    if found is not None and not isinstance(found, QtWidgets.QLayout):
        _forget(found)              # a stale wrapper: ask again for a fresh one
        found = item.layout()
        if not isinstance(found, QtWidgets.QLayout):
            found = None
    if found is None:
        _forget(item)
    del item
    return found


def sub_widget(layout, i):
    """layout.itemAt(i).widget() without keeping the item wrapper."""
    item = layout.itemAt(i)
    if item is None:
        return None
    found = item.widget()
    if found is not None and not isinstance(found, QtWidgets.QWidget):
        _forget(found)
        found = item.widget()
        if not isinstance(found, QtWidgets.QWidget):
            found = None
    _forget(item)
    del item
    return found


def cell_widget(grid, r, c):
    """grid.itemAtPosition(r, c).widget() without keeping the item wrapper."""
    item = grid.itemAtPosition(r, c)
    if item is None:
        return None
    found = item.widget()
    _forget(item)
    del item
    return found


def take_item(layout, i):
    """layout.takeAt(i) as (widget, layout, spacer): the item wrapper is dropped."""
    item = layout.takeAt(i)
    if item is None:
        return None, None, None
    w, l, sp = item.widget(), item.layout(), item.spacerItem()
    if l is None:
        _forget(item)
    del item
    return w, l, sp


def take_grid_rows(grid, keep):
    """Take every cell of grid whose row keep(r) is False, as (widget, layout, r, c, rs, cs)."""
    taken = []
    for i in reversed(range(grid.count())):
        r, c, rs, cs = grid.getItemPosition(i)
        if keep(r):
            continue
        w, l, _sp = take_item(grid, i)
        taken.append((w, l, r, c, rs, cs))
    return taken


def put_grid_rows(grid, taken, shift=1):
    for w, l, r, c, rs, cs in taken:
        if w is not None:
            grid.addWidget(w, r + shift, c, rs, cs)
        elif l is not None:
            grid.addLayout(l, r + shift, c, rs, cs)
    del taken[:]


def _holder(layout, widget):
    """The layout, nested anywhere under layout, that holds widget itself."""
    if layout is None or not isinstance(layout, QtWidgets.QLayout):
        return None
    if layout.indexOf(widget) >= 0:
        return layout
    for i in range(layout.count()):
        found = _holder(sub_layout(layout, i), widget)
        if found is not None:
            return found
    return None


def _grid_cell(grid, widget):
    index = grid.indexOf(widget)
    if index < 0:
        return None
    return grid.getItemPosition(index)


def _layout_holding(grid, widget):
    for i in range(grid.count()):
        layout = sub_layout(grid, i)
        if layout is not None and layout.indexOf(widget) >= 0:
            return layout
    return None



CUT_ITEMS = ["Blind", "Through All", "Through All - Both", "Up To Next", "Up To Vertex", "Up To Surface",
             "Offset From Surface", "Up To Body", MID_PLANE]
BOSS_ITEMS = CUT_ITEMS
FIRST_ITEMS = ["Blind", "Up To Vertex", "Up To Surface", "Offset From Surface", "Up To Body", MID_PLANE]
# FreeCAD's own mode for each (its list as the look words it)
ENGLISH_MODES = ("Blind", "Through All", "Up To Next", "Up To Surface", "Up To Body")


def native_name(combo, index=None, last="Up To Body"):
    """FreeCAD's Type list entry as its English name in any UI language: the list keeps one order
    (Blind, Through All, Up To Next, Up To Surface, then Up To Body, or Two Directions for a revolve)."""
    i = combo.currentIndex() if index is None else index
    if i < 0 or i >= combo.count():
        return ""
    text = combo.itemText(i)
    names = ENGLISH_MODES[:4] + (last,)
    if i >= len(names) or any(combo.itemText(k) in names for k in range(combo.count())):
        return text      # an English list (or an entry past the known ones): as it stands
    return names[i]


def native_index(combo, name, last="Up To Body"):
    """The entry of FreeCAD's Type list that has this English name, in any UI language."""
    names = ENGLISH_MODES[:4] + (last,)
    for i in range(combo.count()):
        if combo.itemText(i) == name:
            return i
    if any(combo.itemText(k) in names for k in range(combo.count())):
        return -1
    if name in names and names.index(name) < combo.count():
        return names.index(name)
    return -1


FREECAD_MODE = {"Blind": "Blind", "Through All": "Through All", "Through All - Both": "Through All",
                "Up To Next": "Up To Next", "Up To Vertex": "Up To Surface", "Up To Surface": "Up To Surface",
                "Offset From Surface": "Up To Surface", "Up To Body": "Up To Body", MID_PLANE: "Blind"}
VERTEX_PLANE = "SWStyle_VertexPlane"


def _edited():
    try:
        import FreeCADGui as Gui
        vp = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument is not None else None
        return editobj.of(vp) if vp is not None else None
    except Exception:
        return None


def _vertex_plane(obj, prop="UpToFace"):
    """The hidden plane through a vertex that an Up To Vertex extrude goes up to, if any."""
    ref = getattr(obj, prop, None)
    if ref and ref[0] is not None and ref[0].Name.startswith(VERTEX_PLANE):
        return ref[0]
    return None


def _drop_vertex_plane(obj, plane):
    """A vertex plane the extrude no longer goes up to is taken out of the tree (ChatGPT EX6-T1:
    "Up To Vertex plane" stayed after Blind was chosen)."""
    try:
        if plane is None or plane.Document is None:
            return
        for prop in ("UpToFace", "UpToFace2"):
            ref = getattr(obj, prop, None)
            if ref and ref[0] is plane:
                return
        users = [o for o in plane.InList if o.TypeId != "PartDesign::Body"]
        if users:
            return
        doc = plane.Document
        body = plane.getParentGeoFeatureGroup() if hasattr(plane, "getParentGeoFeatureGroup") else None
        if body is not None:
            body.removeObject(plane)
        doc.removeObject(plane.Name)
    except Exception as _fw_err:
        _fw_log("pmfields.py:202", _fw_err)


SKETCH_AXES = ("N_Axis", "V_Axis", "H_Axis")


def repair_axis(obj):
    """A direction reference to the profile's own axis (N_Axis, V_Axis, H_Axis) must name the
    profile object itself: FreeCAD reads those names only on the profile and fails on any other
    object with "Invalid shape name N_Axis" (ChatGPT 2B02: a cut on Selected Contours kept its
    sketch as the reference and broke when the base was edited). True when changed."""
    try:
        axis = getattr(obj, "ReferenceAxis", None)
        profile = getattr(obj, "Profile", None)
        if not axis or not axis[1] or not profile:
            return False
        sub = axis[1][0]
        if not (sub in SKETCH_AXES or (sub.startswith("Axis") and sub[4:].isdigit())):
            return False
        target = profile[0]
        if axis[0] is target or target is None:
            return False
        if target.isDerivedFrom("Part::Part2DObject"):
            obj.ReferenceAxis = (target, list(axis[1]))
        else:
            obj.ReferenceAxis = None
        return True
    except Exception:
        return False


def reattach_sketch(sketch):
    """A sketch on a face that is gone after its feature changed shape (AttachEngine "subshape
    not found Pad.?Face6", ChatGPT 2A03) is put back on the face now in the same plane: the
    flat face of the same object whose plane is the sketch's last one, nearest its old place.
    True when reattached."""
    try:
        import FreeCAD as App
        support = sketch.AttachmentSupport
        if not support:
            return False
        obj, subs = support[0]
        sub = (subs[0] if subs else "").lstrip("?")     # FreeCAD marks a lost name "?Face6"
        if obj is None or not sub.startswith("Face"):
            return False
        place = sketch.Placement
        normal = place.Rotation.multVec(App.Vector(0, 0, 1))
        origin = place.Base
        best, best_d = None, None
        for i, face in enumerate(obj.Shape.Faces, 1):
            try:
                if type(face.Surface).__name__ != "Plane":
                    continue
                n = face.normalAt(0, 0)
                if abs(abs(n.dot(normal)) - 1.0) > 1e-6:
                    continue
                c = face.CenterOfMass
                if abs((c - origin).dot(normal)) > 1e-6:
                    continue
                d = (c - origin).Length
                if best is None or d < best_d:
                    best, best_d = "Face%d" % i, d
            except Exception:
                continue
        if best is None or best == sub:
            return False
        sketch.AttachmentSupport = [(obj, best)]
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- Up To Next
# FreeCAD's "To first" aims one line from the profile's centre of mass: a ring round a hole (a pin
# boss over its pin hole) aims down the empty hole and fails ("No faces found in this direction").

# face (FreeCAD "Up to face"), marked SWUpToNext so the PM still shows Up To Next and the face is
# found again whenever the part before it changes.
UP_TO_NEXT = "SWUpToNext"


def _profile_faces(obj):
    import Part
    prof = getattr(obj, "Profile", None)
    src = prof[0] if isinstance(prof, (list, tuple)) else prof
    if src is None or src.Shape.isNull():
        return []
    if src.Shape.Faces:
        return list(src.Shape.Faces)
    wires = [w for w in src.Shape.Wires if w.isClosed()]
    try:
        return list(Part.makeFace(wires, "Part::FaceMakerBullseye").Faces) if wires else []
    except Exception:
        return []


def _direction(obj, faces):
    import FreeCAD as App
    if getattr(obj, "UseCustomVector", False):
        d = App.Vector(obj.Direction)
    else:
        d = faces[0].normalAt(*faces[0].Surface.parameter(faces[0].CenterOfMass)) if faces else App.Vector(0, 0, 1)
        prof = getattr(obj, "Profile", None)
        src = prof[0] if isinstance(prof, (list, tuple)) else prof
        try:
            d = src.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
        except Exception as _fw_err:
            _fw_log("pmfields.py:309", _fw_err)
        if "Pocket" in obj.TypeId:
            d = d * -1
    if getattr(obj, "Reversed", False):
        d = d * -1
    return d.normalize() if d.Length > 1e-12 else None


def _hits(obj):
    """[(point, direction, distance, "Face<n>")]: where each sample of the profile first meets the
    part before obj along the extrude; [] when it meets nothing."""
    import Part
    base = getattr(obj, "BaseFeature", None)
    if base is None or base.Shape.isNull():
        return []
    faces = _profile_faces(obj)
    d = _direction(obj, faces)
    if not faces or d is None:
        return []
    shape = base.Shape
    reach = shape.BoundBox.DiagonalLength * 2 + 1
    out = []
    for f in faces:
        u0, u1, v0, v1 = f.ParameterRange
        for i in range(7):
            for j in range(7):
                p = f.valueAt(u0 + (u1 - u0) * (i + 0.5) / 7, v0 + (v1 - v0) * (j + 0.5) / 7)
                if not f.isInside(p, 1e-7, False):
                    continue
                ray = Part.makeLine(p + d * 1e-4, p + d * reach)
                best = None
                for k, g in enumerate(shape.Faces):
                    if not ray.BoundBox.intersect(g.BoundBox):
                        continue
                    try:
                        dist, pairs, _ = ray.distToShape(g)
                    except Exception:
                        continue
                    if dist > 1e-6:
                        continue
                    along = min((q[0] - p).dot(d) for q in pairs)
                    if along > 1e-4 and (best is None or along < best[0] - 1e-7):
                        best = (along, "Face%d" % (k + 1))
                if best is not None:
                    out.append((p, d, best[0], best[1]))
    return out


def next_face(obj):
    """The face of the part before obj that its profile meets first along the extrude ("Face<n>"), or None."""
    hits = _hits(obj)
    return min(hits, key=lambda h: h[2])[3] if hits else None


def next_depth(obj):
    """A Blind depth that ends the extrude Up To Next: as far as the farthest first meeting, when what
    lies past the nearer meetings up to that depth is all the part's own material (a boss) or all
    empty (a cut), so the result is the same; else None."""
    hits = _hits(obj)
    if not hits:
        return None
    depth = max(h[2] for h in hits)
    shape = obj.BaseFeature.Shape
    cut = "Pocket" in obj.TypeId
    for p, d, along, _ in hits:
        if depth - along < 1e-6:
            continue
        for k in (1, 2, 3):
            q = p + d * (along + (depth - along) * k / 4.0)
            if shape.isInside(q, 1e-6, True) == cut:
                return None
    return depth


def is_up_to_next(obj):
    return obj is not None and bool(getattr(obj, UP_TO_NEXT, False))


def mark_up_to_next(obj, on):
    if on and UP_TO_NEXT not in obj.PropertiesList:
        obj.addProperty("App::PropertyBool", UP_TO_NEXT, "FreeCAD", "Up To Next, done as a depth or Up To Face")
        obj.setPropertyStatus(UP_TO_NEXT, "Hidden")
    if UP_TO_NEXT in obj.PropertiesList:
        setattr(obj, UP_TO_NEXT, bool(on))


def _set_next(obj):
    """Up To Next for the part as it is now: a Blind depth when that gives the same solid, else up to
    the first face met. True when obj changed."""
    depth = next_depth(obj)
    if depth is not None:
        if obj.Type == "Length" and abs(float(obj.Length) - depth) < 1e-6:
            return False
        obj.Type = "Length"
        obj.Length = depth
        return True
    face = next_face(obj)
    if face is None:
        return False
    ref = obj.UpToFace
    if obj.Type == "UpToFace" and ref and ref[0] is obj.BaseFeature and list(ref[1]) == [face]:
        return False
    obj.Type = "UpToFace"
    obj.UpToFace = (obj.BaseFeature, [face])
    return True


def up_to_next(obj):
    ""
    if not _hits(obj):
        return False
    _set_next(obj)
    mark_up_to_next(obj, True)
    return True


def _follow_next(obj):
    """An Up To Next done another way: again for the part as it is now. True when changed."""
    if obj.Type not in ("Length", "UpToFace"):
        mark_up_to_next(obj, False)      # another End Condition was picked
        return False
    return _set_next(obj)


class _AxisWatch:
    """Repairs after a failed recompute: an extrude with a stale profile-axis reference (files
    saved with one) and a sketch whose face is gone, then recomputes again. FreeCAD reports a
    failed object only through the document's recompute, so the document is scanned then."""

    def slotRecomputedDocument(self, doc):
        try:
            fixed = []
            for o in doc.Objects:
                if "Invalid" not in o.State:
                    continue
                status = o.getStatusString()
                if o.TypeId.startswith(("PartDesign::Pad", "PartDesign::Pocket")) and "Invalid shape name" in status:
                    if repair_axis(o):
                        fixed.append(o)
                elif o.TypeId.startswith(("PartDesign::Pad", "PartDesign::Pocket")) and \
                        "No faces found in this direction" in status and getattr(o, "Type", "") == "UpToFirst":
                    if _edited() is o:
                        self._later(doc)            # the PM owns the fields: once it has closed
                    elif up_to_next(o):
                        fixed.append(o)
                elif is_up_to_next(o) and o.Type == "UpToFace":
                    depth = next_depth(o)          # up to the face failed (faces lying on each other)
                    if depth is not None:
                        o.Type = "Length"
                        o.Length = depth
                        fixed.append(o)
                elif o.TypeId == "Sketcher::SketchObject" and "subshape not found" in status:
                    if reattach_sketch(o):
                        fixed.append(o)
            for o in doc.Objects:
                if is_up_to_next(o) and "Invalid" not in o.State and o not in fixed:
                    if _follow_next(o):
                        fixed.append(o)
            if fixed:
                def again():
                    for o in fixed:
                        o.touch()
                    doc.recompute()
                QtCore.QTimer.singleShot(0, again)
        except Exception as _fw_err:
            _fw_log("pmfields.py:474", _fw_err)

    def _later(self, doc, tries=0):
        name = doc.Name

        def look():
            try:
                import FreeCAD as App
                d = App.getDocument(name)
            except Exception:
                return
            if any(_edited() is o for o in d.Objects if getattr(o, "Type", "") == "UpToFirst" and "Invalid" in o.State):
                if tries < 120:
                    self._later(d, tries + 1)
                return
            self.slotRecomputedDocument(d)
        QtCore.QTimer.singleShot(500, look)


_axis_watch = []


def watch_axes():
    if _axis_watch:
        return
    try:
        import FreeCAD as App
        watcher = _AxisWatch()
        App.addDocumentObserver(watcher)
        _axis_watch.append(watcher)
    except Exception as _fw_err:
        _fw_log("pmfields.py:505", _fw_err)


class ExtrudeFields(QtCore.QObject):
    def __init__(self, owner, sides, mode, side2_label):
        super().__init__(owner)
        self.sides = sides
        self.mode = mode
        self.obj = _edited()
        self.cut = self.obj is not None and "Pocket" in self.obj.TypeId
        self.first = self.obj is not None and getattr(self.obj, "BaseFeature", None) is None
        self.choice = None
        self.watching = False
        try:
            # the Face/Plane box takes faces: a click by a face's edge stays on the face
            from . import facehover
            facehover.faces_only(self, lambda me: bool(getattr(me, "face_active", False)) and me.face_box is not None and _alive(me.face_box)
                                 and me.current() in ("Up To Surface", "Offset From Surface"))
        except Exception as _fw_err:
            _fw_log("pmfields.py:524", _fw_err)
        self.vertex_plane = _vertex_plane(self.obj) if self.obj is not None else None
        if self.obj is not None:
            repair_axis(self.obj)
        panel = mode.parentWidget()
        grid = _holder(panel.layout(), mode)
        self.end = QtWidgets.QComboBox(panel)
        self.end.setObjectName("SWStyle_EndCondition")
        row, column, _, _ = _grid_cell(grid, mode)
        grid.addWidget(self.end, row, column)
        mode.hide()
        self.end.setSizePolicy(mode.sizePolicy())
        for widget in (sides, panel.findChild(QtWidgets.QLabel, "sidesLabel")):
            if widget is not None:
                widget.hide()
                widget.setMaximumHeight(0)
        self.second = QtWidgets.QCheckBox("Direction 2", panel)
        self.second.setObjectName("SWStyle_Direction2")
        holder = _holder(grid, side2_label) if side2_label is not None else None
        if holder is not None:
            holder.insertWidget(0, self.second)
            side2_label.setMaximumWidth(0)
        else:
            grid.addWidget(self.second, grid.rowCount(), 0, 1, 2)
        view = panel.window()
        self.offset = view.findChild(QtWidgets.QAbstractSpinBox, "offsetEdit")
        self.offset_label = view.findChild(QtWidgets.QLabel, "labelOffset")
        self.face_line = view.findChild(QtWidgets.QLineEdit, "lineFaceName")
        self._face_box(view)
        self.body_box = BodyBox(self, view, "")
        self.offset_row = OffsetRow(self, self.offset, self.offset_label, 1.0, "")
        self.side2 = None
        try:
            self.side2 = Side2Fields(self, view)
        except Exception as _fw_err:
            _fw_log("pmfields.py:side2", _fw_err)
        self.sync()
        self.end.activated.connect(self._end_picked)
        self.second.toggled.connect(self._second_toggled)
        sides.currentIndexChanged.connect(self.sync)
        mode.currentIndexChanged.connect(self.sync)

    def items(self):
        if self.cut:
            wanted = CUT_ITEMS
        elif self.first:
            wanted = FIRST_ITEMS
        else:
            wanted = BOSS_ITEMS
        have = [native_name(self.mode, i) for i in range(self.mode.count())]
        return [item for item in wanted if FREECAD_MODE[item] in have]

    def current(self):
        text = native_name(self.mode)
        symmetric = self.sides.currentIndex() == SYMMETRIC
        if symmetric and text == "Blind":
            return MID_PLANE
        if text == "Blind" and self.choice in (None, "Up To Next") and is_up_to_next(self.obj):
            return "Up To Next"
        if symmetric and text == "Through All":
            return "Through All - Both"
        if text == "Up To Surface":
            if self.choice in (None, "Up To Next") and is_up_to_next(self.obj):
                return "Up To Next"
            if self.choice == "Up To Vertex" or (self.obj is not None and _vertex_plane(self.obj) is not None):
                return "Up To Vertex"
            if self.choice == "Offset From Surface" or (self.obj is not None and abs(float(getattr(self.obj, "Offset", 0))) > 1e-9):
                return "Offset From Surface"
            return "Up To Surface"
        return text

    def sync(self, *args):
        if not (_alive(self.mode) and _alive(self.end)):
            return
        items = self.items()
        current = self.current()
        self.end.blockSignals(True)
        if [self.end.itemText(i) for i in range(self.end.count())] != items:
            self.end.clear()
            self.end.addItems(items)
        if current in items:
            self.end.setCurrentIndex(items.index(current))
        self.end.blockSignals(False)
        symmetric = self.sides.currentIndex() == SYMMETRIC
        self.second.blockSignals(True)
        self.second.setChecked(self.sides.currentIndex() == TWO)
        self.second.setEnabled(True)
        self.second.setVisible(not symmetric)
        self.second.blockSignals(False)
        show_offset = current == "Offset From Surface"
        row = getattr(self, "offset_row", None)
        if row is not None and row.holder is not None:
            row.sync(show_offset)
        else:
            for widget in (self.offset, self.offset_label):
                if widget is not None and _alive(widget):
                    widget.setVisible(show_offset)
        if native_name(self.mode) == "Blind" and not symmetric:
            view = self.mode.window()
            for kind, name in ((QtWidgets.QAbstractSpinBox, "lengthEdit"), (QtWidgets.QLabel, "labelLength")):
                widget = view.findChild(kind, name)
                if widget is not None and _alive(widget):
                    widget.setVisible(current != "Up To Next")     # Up To Next has no depth
        self._sync_face_box(current)
        body_box = getattr(self, "body_box", None)
        if body_box is not None:
            body_box.sync(current == "Up To Body")
        side2 = getattr(self, "side2", None)
        if side2 is not None:
            side2.sync()

    def _set_mode(self, text):
        index = native_index(self.mode, text)
        if index >= 0 and index != self.mode.currentIndex():
            self.mode.setCurrentIndex(index)

    def _end_picked(self, index):
        item = self.end.itemText(index)
        self.choice = item
        if self.obj is not None and item != "Up To Next" and is_up_to_next(self.obj):
            mark_up_to_next(self.obj, False)
        symmetric = item in (MID_PLANE, "Through All - Both")
        if symmetric:
            self._set_mode(FREECAD_MODE[item])
            self.sides.setCurrentIndex(SYMMETRIC)
        else:
            if self.sides.currentIndex() == SYMMETRIC:
                self.sides.setCurrentIndex(TWO if self.second.isChecked() else ONE)
            self._set_mode(FREECAD_MODE[item])
        if item == "Up To Surface" and self.offset is not None and _alive(self.offset):
            try:
                self.offset.setProperty("rawValue", 0.0)
            except Exception as _fw_err:
                _fw_log("pmfields.py:639", _fw_err)
        if item == "Up To Next":
            QtCore.QTimer.singleShot(300, self._check_next)
        if item == "Up To Body" and getattr(self, "body_box", None) is not None:
            QtCore.QTimer.singleShot(0, self.body_box.arm_if_empty)
        if item == "Up To Vertex":
            self._watch_vertex()
        else:
            self._stop_watching()
            if self.obj is not None and self.vertex_plane is not None:
                ref = getattr(self.obj, "UpToFace", None)
                if ref and ref[0] is self.vertex_plane:
                    self.obj.UpToFace = None
                QtCore.QTimer.singleShot(0, lambda: self._drop_plane())
        self.sync()

    def _check_next(self):
        """FreeCAD's "To first" found nothing (a ring over a hole): Up To Next as the depth that ends
        at the next face, set through the PM's own fields so OK keeps it."""
        try:
            obj = self.obj
            if obj is None or not _alive(self.mode) or native_name(self.mode) != "Up To Next":
                return
            if "Invalid" not in obj.State or "No faces found" not in obj.getStatusString():
                return
            depth = next_depth(obj)
            if depth is None:
                return
            mark_up_to_next(obj, True)
            self.choice = "Up To Next"
            self._set_mode("Blind")
            length = self.mode.window().findChild(QtWidgets.QAbstractSpinBox, "lengthEdit")
            if length is not None and _alive(length):
                if isinstance(length, QtWidgets.QDoubleSpinBox):
                    length.setValue(depth)
                else:
                    length.setProperty("rawValue", depth)
            else:
                obj.Length = depth
            obj.Document.recompute()
            self.sync()
        except Exception as error:
            try:
                import FreeCAD as App
                App.Console.PrintWarning("FreeCAD: Up To Next: %s\n" % error)
            except Exception as _fw_err:
                _fw_log("pmfields.py:683", _fw_err)

    def _drop_plane(self):
        plane, self.vertex_plane = self.vertex_plane, None
        if self.obj is not None and self.current() != "Up To Vertex":
            _drop_vertex_plane(self.obj, plane)
            try:
                self.obj.Document.recompute()
            except Exception as _fw_err:
                _fw_log("pmfields.py:692", _fw_err)
        else:
            self.vertex_plane = plane

    # Up To Vertex: the next vertex picked makes a hidden plane through it, parallel to the
    # sketch, and the extrude goes up to that plane (it follows the vertex when the part changes)
    def _watch_vertex(self):
        side2 = getattr(self, "side2", None)
        if side2 is not None:
            side2.face_active = False
            side2.watching = False
        self.face_hold = False
        if self.watching:
            return
        try:
            import FreeCADGui as Gui
            Gui.Selection.addObserver(self)
            self.watching = True
        except Exception as _fw_err:
            _fw_log("pmfields.py:706", _fw_err)
        if self.face_line is not None and _alive(self.face_line):
            self.face_line.setPlaceholderText("Pick a vertex")
        # FreeCAD's "Select Face" pick puts up a gate that lets only faces through: take it down
        # (after FreeCAD has put it up). A Python gate is no use: FreeCAD 1.1 calls it without
        # the GIL during preselection and crashes.
        from . import safe_later as _sl; _sl.later(300, self._vertex_gate, self, "end")

    def _vertex_gate(self):
        if not self.watching or not _alive(self.end):
            return
        button = self.end.window().findChild(QtWidgets.QToolButton, "buttonFace")
        if button is not None and button.isCheckable() and button.isChecked():
            button.click()           # FreeCAD leaves its face pick and drops its gate
        try:
            import FreeCADGui as Gui
            Gui.Selection.removeSelectionGate()
        except Exception as _fw_err:
            _fw_log("pmfields.py:724", _fw_err)

    def _stop_watching(self):
        if self.watching:
            try:
                import FreeCADGui as Gui
                Gui.Selection.removeSelectionGate()
            except Exception as _fw_err:
                _fw_log("pmfields.py:732", _fw_err)
            try:
                import FreeCADGui as Gui
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("pmfields.py:737", _fw_err)
            self.watching = False

    def addSelection(self, doc, name, sub, point):
        element = sub.split(".")[-1]
        if not _alive(self.end):
            self._stop_watching()
            return

        if not element.startswith(("Vertex", "Edge")):
            return
        QtCore.QTimer.singleShot(0, lambda: self._vertex_picked(doc, name, sub, point))

    def _vertex_picked(self, doc_name, name, sub, click=None):
        import FreeCAD as App
        import FreeCADGui as Gui
        obj = self.obj
        if obj is None or self.current() != "Up To Vertex":
            return
        doc = obj.Document
        holder = doc.getObject(name)
        for part in sub.split(".")[:-1]:
            found = doc.getObject(part)
            if found is not None:
                holder = found
        element = sub.split(".")[-1]
        try:
            shape = holder.Shape.getElement(element)
            if shape.ShapeType == "Edge":
                ends = [v.Point for v in shape.Vertexes]
                if not ends:
                    return
                near = App.Vector(*click) if click is not None else ends[0]
                point = min(ends, key=lambda p: p.distanceToPoint(near))
            else:
                point = shape.Point
        except Exception:
            return
        source = holder
        body = obj.getParentGeoFeatureGroup()
        if holder == obj or holder.TypeId == "PartDesign::Body" or (body is not None and holder in body.Group and
                                                                   body.Group.index(holder) >= body.Group.index(obj)):
            source = obj.BaseFeature
        if source is None:
            return
        match = [i for i, v in enumerate(source.Shape.Vertexes) if v.Point.distanceToPoint(point) < 1e-6]
        if not match:
            return
        sketch = obj.Profile[0] if isinstance(obj.Profile, (list, tuple)) else obj.Profile
        rotation = sketch.getGlobalPlacement().Rotation if sketch is not None else App.Rotation()
        plane = _vertex_plane(obj)
        if plane is None:
            plane = doc.addObject("PartDesign::Plane", VERTEX_PLANE)
            body.insertObject(plane, obj, False)
            plane.Label = "Up To Vertex plane"
        plane.MapMode = "Translate"
        plane.AttachmentSupport = [(source, "Vertex%d" % (match[0] + 1))]
        plane.AttachmentOffset = App.Placement(App.Vector(0, 0, 0), rotation)
        plane.recompute()
        try:
            plane.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("pmfields.py:799", _fw_err)
        obj.UpToFace = (plane, [""])
        self.vertex_plane = plane
        if self.face_line is not None and _alive(self.face_line):
            self.face_line.setText(plane.Label)
            self.face_line.setProperty("FeatureName", plane.Name)
            self.face_line.setProperty("FaceName", "")
        Gui.Selection.clearSelection()
        doc.recompute()
        self._stop_watching()
        self.sync()

    def _second_toggled(self, on):
        self.sides.setCurrentIndex(TWO if on else ONE)
        self.sync()


    # Up To Vertex, in place of FreeCAD's face name line and its Select Face button
    FACE_ITEMS = ("Up To Surface", "Offset From Surface", "Up To Vertex")

    def _face_box(self, view):
        self.face_box = None
        self.face_active = False
        line = self.face_line
        if line is None or not _alive(line):
            return
        holder = line.parentWidget()
        box = QtWidgets.QListWidget(holder)
        box.setObjectName("SWStyle_UpToFaceBox")
        box.setFixedHeight(26)
        box.setToolTip("Face/Plane: click the face or plane the extrude goes up to")
        lay = holder.layout()
        placed = False
        if lay is not None:
            for i in range(lay.count()):
                item = lay.itemAt(i)
                sub = item.layout() if item is not None else None
                if item is not None and (item.widget() is line or (sub is not None and sub.indexOf(line) >= 0)):
                    if isinstance(lay, QtWidgets.QBoxLayout):
                        lay.insertWidget(i, box)
                        placed = True
                    break
            if not placed and isinstance(lay, QtWidgets.QGridLayout):
                idx = lay.indexOf(line)
                if idx >= 0:
                    r, c, _rs, _cs = lay.getItemPosition(idx)
                    lay.addWidget(box, r, 0, 1, max(lay.columnCount(), 1))
                    placed = True
            if not placed and isinstance(lay, QtWidgets.QBoxLayout):
                lay.addWidget(box)
                placed = True
        self.face_box = box
        for w in (line, view.findChild(QtWidgets.QToolButton, "buttonFace"), view.findChild(QtWidgets.QPushButton, "buttonFace"),
                  view.findChild(QtWidgets.QLabel, "labelFace")):
            if w is not None and _alive(w):
                w.hide()
                w.setMaximumHeight(0)
        try:
            from . import pmboxes
            pmboxes.bind(box, lambda row: self._clear_face(), self._clear_face)
        except Exception as _fw_err:
            _fw_log("pmfields.py:860", _fw_err)
        box.viewport().installEventFilter(self)
        try:
            import FreeCADGui as Gui
            Gui.Selection.addObserver(self._FacePicks(self))
        except Exception as _fw_err:
            _fw_log("pmfields.py:866", _fw_err)

    class _FacePicks:
        def __init__(self, owner):
            self.owner = owner

        def addSelection(self, doc, name, sub, point):
            owner = self.owner
            if owner.face_box is None or not _alive(owner.face_box):
                try:
                    import FreeCADGui as Gui
                    Gui.Selection.removeObserver(self)
                except Exception as _fw_err:
                    _fw_log("pmfields.py:879", _fw_err)
                return
            if owner.face_active and owner.current() in ("Up To Surface", "Offset From Surface"):
                QtCore.QTimer.singleShot(0, lambda: owner._face_picked(doc, name, sub))

    def eventFilter(self, watched, event):
        try:
            if self.face_box is not None and _alive(self.face_box) and watched is self.face_box.viewport() and \
                    event.type() == QtCore.QEvent.MouseButtonPress:
                self.face_active = True
                self.face_hold = False
                side2 = getattr(self, "side2", None)
                if side2 is not None:
                    side2.face_active = False
                    side2.watching = False
                self._sync_face_box(self.current())
        except RuntimeError as _fw_err:
            _fw_log("pmfields.py:891", _fw_err)
        return False

    def _face_picked(self, doc_name, name, sub):
        import FreeCADGui as Gui
        obj = self.obj
        if obj is None:
            return
        doc = obj.Document
        holder = doc.getObject(name)
        for part in sub.split(".")[:-1]:
            found = doc.getObject(part)
            if found is not None:
                holder = found
        element = sub.split(".")[-1]
        if holder is None or holder is obj:
            return
        plane = holder.TypeId in ("PartDesign::Plane", "App::Plane") or holder.isDerivedFrom("App::Plane")
        if not plane and not element.startswith("Face"):
            return
        body = obj.getParentGeoFeatureGroup()
        if holder.TypeId == "PartDesign::Body" or (body is not None and holder in body.Group and holder.isDerivedFrom("PartDesign::Feature")
                                                   and body.Group.index(holder) >= body.Group.index(obj)):
            holder = obj.BaseFeature or holder
        obj.UpToFace = (holder, ["" if plane else element])
        if self.face_line is not None and _alive(self.face_line):
            from . import pmboxes
            self.face_line.setText(pmboxes.sw_name(holder.Label + ("" if plane else ":" + element)))
            self.face_line.setProperty("FeatureName", holder.Name)
            self.face_line.setProperty("FaceName", "" if plane else element)
        self.face_active = False
        Gui.Selection.clearSelection()
        doc.recompute()
        self.sync()

    def _clear_face(self):
        if self.obj is None:
            return
        self.obj.UpToFace = None
        if self.face_line is not None and _alive(self.face_line):
            self.face_line.setText("")
            self.face_line.setProperty("FeatureName", "")
            self.face_line.setProperty("FaceName", "")
        self.face_active = True
        self.sync()

    def _sync_face_box(self, current):
        box = self.face_box
        if box is None or not _alive(box):
            return
        view = box.window()
        for w in (self.face_line, view.findChild(QtWidgets.QToolButton, "buttonFace"),
                  view.findChild(QtWidgets.QPushButton, "buttonFace"), view.findChild(QtWidgets.QLabel, "labelFace")):
            if w is not None and _alive(w) and not w.isHidden():
                w.hide()            # FreeCAD shows them again on every end condition change
        shown = current in self.FACE_ITEMS
        box.setVisible(shown)
        if not shown:
            self.face_active = False
            return
        text = _ref_text(getattr(self.obj, "UpToFace", None) if self.obj is not None else None)
        if [box.item(i).text() for i in range(box.count())] != ([text] if text else []):
            box.clear()
            if text:
                box.addItem(text)
        if current == "Up To Vertex":
            box.setToolTip("Vertex: click the vertex the extrude goes up to")
            active = self.watching
        else:
            box.setToolTip("Face/Plane: click the face or plane the extrude goes up to")
            if not text and not getattr(self, "face_hold", False):
                self.face_active = True          # an empty required box takes the next pick
            active = self.face_active
        try:
            from . import pmboxes
            pmboxes.mark(box, active, need=not text)
        except Exception as _fw_err:
            _fw_log("pmfields.py:971", _fw_err)


def _insert_before(anchor, new):
    """Puts new in anchor's place in its parent's layout (a grid cell, or the slot before it)."""
    holder = anchor.parentWidget()
    lay = holder.layout() if holder is not None else None
    if lay is None:
        return False
    where = _holder(lay, anchor)
    if isinstance(where, QtWidgets.QBoxLayout):
        where.insertWidget(where.indexOf(anchor), new)
        return True
    if isinstance(where, QtWidgets.QGridLayout):
        r, _c, _rs, _cs = where.getItemPosition(where.indexOf(anchor))
        where.addWidget(new, r, 0, 1, max(where.columnCount(), 1))
        return True
    lay.addWidget(new)
    return True


def _face_ref(obj, name, sub):
    """(feature, element, is_plane) a face or plane click stands for, as Up To Surface takes it."""
    doc = obj.Document
    holder = doc.getObject(name)
    for part in sub.split(".")[:-1]:
        found = doc.getObject(part)
        if found is not None:
            holder = found
    element = sub.split(".")[-1]
    if holder is None or holder is obj:
        return None
    plane = holder.TypeId in ("PartDesign::Plane", "App::Plane") or holder.isDerivedFrom("App::Plane")
    if not plane and not element.startswith("Face"):
        return None
    body = obj.getParentGeoFeatureGroup()
    if holder.TypeId == "PartDesign::Body" or (body is not None and holder in body.Group and holder.isDerivedFrom("PartDesign::Feature")
                                               and body.Group.index(holder) >= body.Group.index(obj)):
        holder = obj.BaseFeature or holder
    return holder, ("" if plane else element), plane


def _ref_text(ref):
    ""


    if ref and ref[0] is not None:
        subs = ref[1] if isinstance(ref[1], (list, tuple)) else [ref[1]]
        sub = subs[0] if subs and subs[0] else ""
        if not sub and str(getattr(ref[0], "Name", "")).startswith(VERTEX_PLANE):
            support = getattr(ref[0], "AttachmentSupport", None) or []
            names = [n for _o, ns in support for n in (ns if isinstance(ns, (list, tuple)) else [ns]) if n]
            if names and names[0].startswith("Vertex"):
                return names[0]
        return sub.split(".")[-1] if sub else ref[0].Label
    return ""


def first_face(obj, target, side2=False):
    ""


    import FreeCAD as App
    import Part
    sketch = obj.Profile[0] if isinstance(obj.Profile, (list, tuple)) else obj.Profile
    wires = sketch.Shape.Wires
    face = Part.makeFace(wires, "Part::FaceMakerBullseye") if wires else None
    if face is None or face.isNull():
        return None
    if getattr(obj, "UseCustomVector", False) and App.Vector(obj.Direction).Length > 1e-9:
        d = App.Vector(obj.Direction)
    else:
        d = sketch.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
    d.normalize()
    if getattr(obj, "Reversed", False):
        d = d * -1
    if side2:
        d = d * -1
    body = obj.getParentGeoFeatureGroup()
    shape = target.Shape
    try:
        if body is not None and target.getParentGeoFeatureGroup() is not body:
            shape = target.getPropertyByName("Shape").copy()
            shape.Placement = target.getGlobalPlacement()
            inv = body.getGlobalPlacement().inverse()
            shape.transformShape(inv.toMatrix(), True)
    except Exception as _fw_err:
        _fw_log("pmfields.py:first_face placement", _fw_err)
    reach = shape.BoundBox.DiagonalLength + face.BoundBox.DiagonalLength + abs(face.CenterOfMass.dot(d)) + 1000.0
    prism = face.extrude(d * reach)
    origin = face.CenterOfMass
    best = None
    for i, f in enumerate(shape.Faces, 1):
        try:
            if f.BoundBox.intersect(prism.BoundBox) is False:
                continue
            hit = prism.common(f)
            if hit.isNull() or hit.Area < 1e-7:
                continue
            gap = (hit.CenterOfMass - origin).dot(d)
        except Exception:
            continue
        if gap > 1e-7 and (best is None or gap < best[0]):
            best = (gap, "Face%d" % i)
    return best[1] if best else None


class OffsetRow(QtCore.QObject):
    ""



    def __init__(self, owner, native, label, sign, suffix):
        super().__init__(owner)
        self.native, self.label, self.sign = native, label, sign
        self.holder = None
        if native is None:
            return
        holder = QtWidgets.QWidget(native.parentWidget())
        holder.setObjectName("SWStyle_OffsetRow" + suffix)
        lay = QtWidgets.QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.spin = QtWidgets.QDoubleSpinBox(holder)
        self.spin.setObjectName("SWStyle_OffsetDistance" + suffix)
        self.spin.setRange(0.0, 1e5)
        self.spin.setDecimals(2)
        self.spin.setSuffix(" mm")
        self.spin.setToolTip("Offset Distance from the face or plane")
        self.reverse = QtWidgets.QCheckBox("Reverse offset", holder)
        self.reverse.setObjectName("SWStyle_ReverseOffset" + suffix)
        self.reverse.setToolTip("Offset past the face instead of short of it")
        lay.addWidget(self.spin)
        lay.addWidget(self.reverse)
        if not _insert_before(native, holder):
            holder.deleteLater()
            return
        self.holder = holder
        self.read()
        self.spin.valueChanged.connect(lambda *a: self.write())
        self.reverse.toggled.connect(lambda *a: self.write())
        holder.hide()

    def _value(self):
        try:
            v = self.native.property("rawValue")
            if v is None:
                v = self.native.value()
            return float(v)
        except Exception:
            return 0.0

    def read(self):
        v = self._value() * self.sign
        for w, val in ((self.spin, abs(v)), (self.reverse, v < -1e-12)):
            w.blockSignals(True)
            if w is self.spin:
                w.setValue(val)
            else:
                w.setChecked(val)
            w.blockSignals(False)

    def write(self):
        want = self.sign * self.spin.value() * (-1.0 if self.reverse.isChecked() else 1.0)
        if abs(self._value() - want) > 1e-9:
            if isinstance(self.native, QtWidgets.QDoubleSpinBox):
                self.native.setValue(want)
            else:
                self.native.setProperty("rawValue", want)

    def sync(self, shown):
        if self.holder is None or not _alive(self.holder):
            return
        for w in (self.native, self.label):
            if w is not None and _alive(w) and not w.isHidden():
                w.hide()
        if shown and not (self.spin.hasFocus() or self.holder.isVisible()):
            self.read()
        set_shown(self.holder, shown)       # also before the PM is first shown (look audit Z1)


class BodyBox(QtCore.QObject):
    ""

    NATIVE = ("upToShapeList", "upToShapeFaces", "buttonShape", "buttonShapeFace", "checkBoxAllFaces",
              "lineShapeName", "listWidgetReferences")

    def __init__(self, owner, view, suffix):
        super().__init__(owner)
        self.owner, self.view, self.suffix = owner, view, suffix
        self.prop = "UpToShape" + suffix
        self.box = None
        self.armed = False
        self.line = view.findChild(QtWidgets.QLineEdit, "lineShapeName" + suffix)
        self.list = view.findChild(QtWidgets.QListWidget, "listWidgetReferences" + suffix)
        self.button = view.findChild(QtWidgets.QAbstractButton, "buttonShape" + suffix)
        anchor = view.findChild(QtWidgets.QWidget, "upToShapeList" + suffix) or self.line
        if anchor is None or self.line is None:
            return
        box = QtWidgets.QListWidget(anchor.parentWidget())
        box.setObjectName("SWStyle_UpToBodyBox" + suffix)
        box.setFixedHeight(26)
        box.setToolTip("Solid/Surface Body: click the body the extrude goes up to")
        if not _insert_before(anchor, box):
            box.deleteLater()
            return
        self.box = box
        try:
            from . import pmboxes
            pmboxes.bind(box, lambda row: self.clear(), self.clear)
        except Exception as _fw_err:
            _fw_log("pmfields.py:bodybox bind", _fw_err)
        box.viewport().installEventFilter(self)
        try:
            import FreeCADGui as Gui
            self.picks = self._Picks(self)
            Gui.Selection.addObserver(self.picks)
        except Exception as _fw_err:
            _fw_log("pmfields.py:bodybox observer", _fw_err)
        self._hide_natives()
        box.hide()

    def _alive(self):
        return self.box is not None and _alive(self.box)

    def _hide_natives(self):
        for n in self.NATIVE:
            w = self.view.findChild(QtWidgets.QWidget, n + self.suffix)
            if w is not None and _alive(w) and not w.isHidden():
                w.hide()          # FreeCAD shows them again on every end condition change
        try:
            if self.button is not None and _alive(self.button) and self.button.isCheckable() and self.button.isChecked():
                self.button.click()     # FreeCAD's own shape pick would take the click too
        except RuntimeError as _fw_err:
            _fw_log("pmfields.py:bodybox native pick", _fw_err)

    def target(self):
        obj = getattr(self.owner, "obj", None)
        refs = getattr(obj, self.prop, None) if obj is not None else None
        for ref in refs or []:
            if ref and ref[0] is not None:
                return ref[0]
        return None

    def text(self):
        t = self.target()
        return t.Label if t is not None else ""

    def arm(self):
        self.armed = True
        for other in self._others():
            other.armed = False
        try:
            import FreeCADGui as Gui
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("pmfields.py:bodybox clear sel", _fw_err)

    def _others(self):
        out = []
        for o in (getattr(self.owner, "body_box", None), getattr(getattr(self.owner, "owner", None), "body_box", None),
                  getattr(getattr(self.owner, "side2", None), "body_box", None)):
            if o is not None and o is not self:
                out.append(o)
        return out

    def arm_if_empty(self):
        if self._alive() and self.box.isVisible() and self.target() is None:
            self.arm()
        self._resync()

    def put(self, target):
        """target in the box: FreeCAD's line and face list hold it as its Up to shape pick does."""
        obj = self.owner.obj
        face = first_face(obj, target, side2=bool(self.suffix))
        if face is None:
            import FreeCAD as App
            App.Console.PrintWarning("FreeCAD: Up To Body: the extrude does not reach %s\n" % target.Label)
            return False
        setattr(obj, self.prop, [(target, [face])])
        if self.line is not None and _alive(self.line):
            self.line.setText("%s#%s" % (target.Document.Name, target.Name))
        if self.list is not None and _alive(self.list):
            self.list.clear()
            self.list.addItem(face)
        self.armed = False
        obj.Document.recompute()
        return True

    def clear(self):
        obj = getattr(self.owner, "obj", None)
        try:
            if obj is not None:
                setattr(obj, self.prop, [])
            if self.line is not None and _alive(self.line):
                self.line.setText("")
            if self.list is not None and _alive(self.list):
                self.list.clear()
        except Exception as _fw_err:
            _fw_log("pmfields.py:bodybox clear", _fw_err)
        self.arm()
        self._resync()

    class _Picks:
        def __init__(self, owner):
            self.owner = owner

        def addSelection(self, doc, name, sub, point):
            me = self.owner
            if not me._alive():
                try:
                    import FreeCADGui as Gui
                    Gui.Selection.removeObserver(self)
                except Exception as _fw_err:
                    _fw_log("pmfields.py:bodybox unobserve", _fw_err)
                return
            if me.armed and me.box.isVisible():
                QtCore.QTimer.singleShot(0, lambda: me._picked(name, sub))

    def _picked(self, name, sub):
        import FreeCADGui as Gui
        obj = self.owner.obj
        doc = obj.Document
        holder = doc.getObject(name)
        for part in sub.split(".")[:-1]:
            found = doc.getObject(part)
            if found is not None:
                holder = found
        if holder is None or holder is obj or not hasattr(holder, "Shape") or holder.Shape.isNull() or not holder.Shape.Faces:
            return
        body = obj.getParentGeoFeatureGroup()
        if holder.TypeId == "PartDesign::Body":
            holder = holder.Tip or holder
        elif body is not None and holder in body.Group and body.Group.index(holder) >= body.Group.index(obj):
            holder = obj.BaseFeature or holder
        try:
            self.put(holder)
        except Exception as error:
            import FreeCAD as App
            App.Console.PrintWarning("FreeCAD: Up To Body: %s\n" % error)
        Gui.Selection.clearSelection()
        self._resync()

    def eventFilter(self, watched, event):
        try:
            if self._alive() and watched is self.box.viewport() and event.type() == QtCore.QEvent.MouseButtonPress:
                self.arm()
                self._resync()
        except RuntimeError as _fw_err:
            _fw_log("pmfields.py:bodybox press", _fw_err)
        return False

    def _resync(self):
        if self._alive():
            self.sync(self.box.isVisible())

    def sync(self, shown):
        if not self._alive():
            return
        self._hide_natives()
        set_shown(self.box, shown)
        if not shown:
            self.armed = False
            return
        text = self.text()
        if [self.box.item(i).text() for i in range(self.box.count())] != ([text] if text else []):
            self.box.clear()
            if text:
                self.box.addItem(text)
        try:
            from . import pmboxes
            pmboxes.mark(self.box, self.armed, need=not text)
        except Exception as _fw_err:
            _fw_log("pmfields.py:bodybox mark", _fw_err)



# to go through or up to next
ITEMS2 = ["Blind", "Through All", "Up To Next", "Up To Vertex", "Up To Surface", "Offset From Surface", "Up To Body"]
FIRST_ITEMS2 = ["Blind", "Up To Vertex", "Up To Surface", "Offset From Surface", "Up To Body"]
VERTEX_PLANE2 = VERTEX_PLANE + "2"


def set_shown(w, on):
    """Show or hide w for good: also a widget the page has not shown yet (isVisible() is False for every
    row until the page is on screen, and a row never hidden by hand is shown with its parent)."""
    if w is None or not _alive(w):
        return
    if w.isHidden() == on or not w.testAttribute(QtCore.Qt.WA_WState_ExplicitShowHide):
        w.setVisible(on)


class Side2Fields(QtCore.QObject):
    ""


    FACE_ITEMS = ("Up To Surface", "Offset From Surface", "Up To Vertex")

    def __init__(self, owner, view):
        super().__init__(owner.end)
        self.owner = owner
        self.obj = owner.obj
        self.view = view
        self.mode = view.findChild(QtWidgets.QComboBox, "changeMode2")
        if self.mode is None or self.obj is None or not hasattr(self.obj, "Type2"):
            raise RuntimeError("no second side here")
        panel = self.mode.parentWidget()
        grid = _holder(panel.layout(), self.mode)
        self.end = QtWidgets.QComboBox(panel)
        self.end.setObjectName("SWStyle_EndCondition2")
        self.end.setSizePolicy(self.mode.sizePolicy())
        if isinstance(grid, QtWidgets.QGridLayout):
            r, c, _rs, _cs = _grid_cell(grid, self.mode)
            grid.addWidget(self.end, r, c)
        elif isinstance(grid, QtWidgets.QBoxLayout):
            grid.insertWidget(grid.indexOf(self.mode), self.end)
        else:
            panel.layout().addWidget(self.end)
        self.mode.hide()
        self.offset = view.findChild(QtWidgets.QAbstractSpinBox, "offsetEdit2")
        self.offset_label = view.findChild(QtWidgets.QLabel, "labelOffset2")
        self.face_line = view.findChild(QtWidgets.QLineEdit, "lineFaceName2")
        self.choice = None
        self.watching = False
        self.face_active = False
        self.vertex_plane = _vertex_plane(self.obj, "UpToFace2")
        self.face_box = None
        if self.face_line is not None:
            box = QtWidgets.QListWidget(self.face_line.parentWidget())
            box.setObjectName("SWStyle_UpToFaceBox2")
            box.setFixedHeight(26)
            if _insert_before(self.face_line, box):
                self.face_box = box
                box.hide()
                box.viewport().installEventFilter(self)
                try:
                    from . import pmboxes
                    pmboxes.bind(box, lambda row: self._clear_face(), self._clear_face)
                except Exception as _fw_err:
                    _fw_log("pmfields.py:side2 bind", _fw_err)
            else:
                box.deleteLater()
        self.body_box = BodyBox(self, view, "2")
        self.offset_row = OffsetRow(self, self.offset, self.offset_label, -1.0, "2")
        try:
            from . import facehover
            facehover.faces_only(self, lambda me: me.face_active and me.face_box is not None and _alive(me.face_box)
                                 and me.face_box.isVisible() and me.current() in ("Up To Surface", "Offset From Surface"))
        except Exception as _fw_err:
            _fw_log("pmfields.py:side2 facehover", _fw_err)
        try:
            import FreeCADGui as Gui
            self.picks = self._Picks(self)
            Gui.Selection.addObserver(self.picks)
        except Exception as _fw_err:
            _fw_log("pmfields.py:side2 observer", _fw_err)
        self.end.activated.connect(self._picked)
        self.mode.currentIndexChanged.connect(lambda *a: self.sync())

    def _on(self):
        return _alive(self.owner.sides) and self.owner.sides.currentIndex() == TWO

    def items(self):
        wanted = FIRST_ITEMS2 if (self.owner.first and not self.owner.cut) else ITEMS2
        have = [native_name(self.mode, i) for i in range(self.mode.count())]
        return [item for item in wanted if FREECAD_MODE[item] in have]

    def current(self):
        text = native_name(self.mode)
        if text != "Up To Surface":
            return text
        if self.choice in self.FACE_ITEMS:
            return self.choice
        if _vertex_plane(self.obj, "UpToFace2") is not None:
            return "Up To Vertex"
        if abs(float(getattr(self.obj, "Offset2", 0))) > 1e-9:
            return "Offset From Surface"
        return "Up To Surface"

    def _set_mode(self, text):
        index = native_index(self.mode, text)
        if index >= 0 and index != self.mode.currentIndex():
            self.mode.setCurrentIndex(index)

    def _picked(self, index):
        item = self.end.itemText(index)
        self.choice = item
        self._set_mode(FREECAD_MODE[item])
        if item != "Offset From Surface" and self.offset is not None and _alive(self.offset):
            try:
                self.offset.setProperty("rawValue", 0.0)
            except Exception as _fw_err:
                _fw_log("pmfields.py:side2 offset", _fw_err)
        if item == "Up To Vertex":
            self._watch()
        else:
            self.watching = False
            plane = self.vertex_plane
            if plane is not None:
                ref = getattr(self.obj, "UpToFace2", None)
                if ref and ref[0] is plane:
                    self.obj.UpToFace2 = None
                    self._line("", "", "")
                QtCore.QTimer.singleShot(0, self._drop_plane)
        if item in ("Up To Surface", "Offset From Surface"):
            self._claim()
        if item == "Up To Body":
            QtCore.QTimer.singleShot(0, self.body_box.arm_if_empty)
        self.sync()

    def _claim(self):
        ""
        self.face_active = True
        self.owner.face_active = False
        self.owner.face_hold = True
        try:
            self.owner._stop_watching()
        except Exception as _fw_err:
            _fw_log("pmfields.py:side2 claim", _fw_err)

    def _drop_plane(self):
        plane, self.vertex_plane = self.vertex_plane, None
        if self.current() != "Up To Vertex":
            _drop_vertex_plane(self.obj, plane)
            try:
                self.obj.Document.recompute()
            except Exception as _fw_err:
                _fw_log("pmfields.py:side2 drop", _fw_err)
        else:
            self.vertex_plane = plane

    def _watch(self):
        self._claim()
        self.face_active = False
        self.watching = True
        button = self.view.findChild(QtWidgets.QToolButton, "buttonFace2")

        def gate():
            try:
                if button is not None and _alive(button) and button.isCheckable() and button.isChecked():
                    button.click()       # FreeCAD leaves its face pick and drops its gate
                import FreeCADGui as Gui
                Gui.Selection.removeSelectionGate()
            except Exception as _fw_err:
                _fw_log("pmfields.py:side2 gate", _fw_err)
        QtCore.QTimer.singleShot(300, gate)

    def _line(self, text, feature, face):
        if self.face_line is not None and _alive(self.face_line):
            self.face_line.setText(text)
            self.face_line.setProperty("FeatureName", feature)
            self.face_line.setProperty("FaceName", face)

    class _Picks:
        def __init__(self, owner):
            self.owner = owner

        def addSelection(self, doc, name, sub, point):
            me = self.owner
            if me.face_box is None or not _alive(me.face_box) or not _alive(me.end):
                try:
                    import FreeCADGui as Gui
                    Gui.Selection.removeObserver(self)
                except Exception as _fw_err:
                    _fw_log("pmfields.py:side2 unobserve", _fw_err)
                return
            if not me._on():
                return
            cur = me.current()
            element = sub.split(".")[-1]
            if cur == "Up To Vertex" and me.watching and element.startswith(("Vertex", "Edge")):
                QtCore.QTimer.singleShot(0, lambda: me._vertex_picked(name, sub, point))
            elif cur in ("Up To Surface", "Offset From Surface") and me.face_active:
                QtCore.QTimer.singleShot(0, lambda: me._face_picked(name, sub))

    def _face_picked(self, name, sub):
        import FreeCADGui as Gui
        ref = _face_ref(self.obj, name, sub)
        if ref is None:
            return
        holder, element, plane = ref
        self.obj.UpToFace2 = (holder, [element])
        self._line(holder.Label + (":" + element if element else ""), holder.Name, element)
        self.face_active = False
        self.owner.face_hold = False
        Gui.Selection.clearSelection()
        self.obj.Document.recompute()
        self.sync()

    def _vertex_picked(self, name, sub, click=None):
        import FreeCAD as App
        import FreeCADGui as Gui
        obj = self.obj
        if self.current() != "Up To Vertex" or not self.watching:
            return
        doc = obj.Document
        holder = doc.getObject(name)
        for part in sub.split(".")[:-1]:
            found = doc.getObject(part)
            if found is not None:
                holder = found
        try:
            shape = holder.Shape.getElement(sub.split(".")[-1])
            if shape.ShapeType == "Edge":
                ends = [v.Point for v in shape.Vertexes]
                near = App.Vector(*click) if click is not None else ends[0]
                point = min(ends, key=lambda p: p.distanceToPoint(near))
            else:
                point = shape.Point
        except Exception:
            return
        body = obj.getParentGeoFeatureGroup()
        source = holder
        if holder == obj or holder.TypeId == "PartDesign::Body" or (body is not None and holder in body.Group and
                                                                   body.Group.index(holder) >= body.Group.index(obj)):
            source = obj.BaseFeature
        if source is None:
            return
        match = [i for i, v in enumerate(source.Shape.Vertexes) if v.Point.distanceToPoint(point) < 1e-6]
        if not match:
            return
        sketch = obj.Profile[0] if isinstance(obj.Profile, (list, tuple)) else obj.Profile
        rotation = sketch.getGlobalPlacement().Rotation if sketch is not None else App.Rotation()
        plane = _vertex_plane(obj, "UpToFace2")
        if plane is None:
            plane = doc.addObject("PartDesign::Plane", VERTEX_PLANE2)
            body.insertObject(plane, obj, False)
            plane.Label = "Up To Vertex plane"
        plane.MapMode = "Translate"
        plane.AttachmentSupport = [(source, "Vertex%d" % (match[0] + 1))]
        plane.AttachmentOffset = App.Placement(App.Vector(0, 0, 0), rotation)
        plane.recompute()
        try:
            plane.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("pmfields.py:side2 plane", _fw_err)
        obj.UpToFace2 = (plane, [""])
        self.vertex_plane = plane
        self._line(plane.Label, plane.Name, "")
        self.watching = False
        self.owner.face_hold = False
        Gui.Selection.clearSelection()
        doc.recompute()
        self.sync()

    def _clear_face(self):
        self.obj.UpToFace2 = None
        self._line("", "", "")
        if self.current() == "Up To Vertex":
            self._watch()
        else:
            self._claim()
        self.sync()

    def eventFilter(self, watched, event):
        try:
            if self.face_box is not None and _alive(self.face_box) and watched is self.face_box.viewport() and \
                    event.type() == QtCore.QEvent.MouseButtonPress:
                if self.current() == "Up To Vertex":
                    self._watch()
                else:
                    self._claim()
                self.sync()
        except RuntimeError as _fw_err:
            _fw_log("pmfields.py:side2 press", _fw_err)
        return False

    def sync(self):
        if not (_alive(self.end) and _alive(self.mode)):
            return
        on = self._on()
        items = self.items()
        cur = self.current()
        self.end.blockSignals(True)
        if [self.end.itemText(i) for i in range(self.end.count())] != items:
            self.end.clear()
            self.end.addItems(items)
        if cur in items:
            self.end.setCurrentIndex(items.index(cur))
        self.end.blockSignals(False)
        # while the PM is being built nothing is visible yet, so a Direction 2 list that should be hidden
        # was never hidden and the layout showed "Blind" under the unticked title (look audit Z1)
        set_shown(self.end, on)
        for name in ("changeMode2", "typeLabel2", "lineFaceName2", "buttonFace2"):
            w = self.view.findChild(QtWidgets.QWidget, name)
            if w is not None and _alive(w) and not w.isHidden():
                w.hide()
        if self.offset_row.holder is not None:
            self.offset_row.sync(on and cur == "Offset From Surface")
        else:
            for w in (self.offset, self.offset_label):
                if w is not None and _alive(w):
                    w.setVisible(on and cur == "Offset From Surface")
        box = self.face_box
        if box is not None and _alive(box):
            shown = on and cur in self.FACE_ITEMS
            box.setVisible(shown)
            if shown:
                text = _ref_text(getattr(self.obj, "UpToFace2", None))
                if [box.item(i).text() for i in range(box.count())] != ([text] if text else []):
                    box.clear()
                    if text:
                        box.addItem(text)
                if cur == "Up To Vertex":
                    box.setToolTip("Vertex: click the vertex Direction 2 goes up to")
                    active = self.watching
                else:
                    box.setToolTip("Face/Plane: click the face or plane Direction 2 goes up to")
                    active = self.face_active
                try:
                    from . import pmboxes
                    pmboxes.mark(box, active, need=not text)
                except Exception as _fw_err:
                    _fw_log("pmfields.py:side2 mark", _fw_err)
            else:
                self.face_active = False
                self.watching = False
        self.body_box.sync(on and cur == "Up To Body")


class ShellOutward(QtCore.QObject):
    def __init__(self, owner, inward):
        super().__init__(owner)
        self.inward = inward
        self.box = QtWidgets.QCheckBox("Shell outward", inward.parentWidget())
        self.box.setObjectName("SWStyle_ShellOutward")
        layout = _holder(inward.parentWidget().layout(), inward)
        if isinstance(layout, QtWidgets.QGridLayout):
            row, column, rows, columns = _grid_cell(layout, inward)
            layout.addWidget(self.box, row, column, rows, columns)
        else:
            layout.insertWidget(layout.indexOf(inward), self.box)
        inward.hide()
        self.box.setChecked(not inward.isChecked())
        self.box.toggled.connect(lambda on: inward.setChecked(not on))
        inward.toggled.connect(self._follow)

    def _follow(self, on):
        if _alive(self.box) and self.box.isChecked() == on:
            self.box.blockSignals(True)
            self.box.setChecked(not on)
            self.box.blockSignals(False)


class ShellFields(QtCore.QObject):
    ""

    DEFAULTS = (("modeComboBox", "label_2"), ("joinComboBox", "label_3"))

    def __init__(self, view, panel):
        super().__init__(panel)
        layout = panel.layout()
        value = panel.findChild(QtWidgets.QWidget, "Value")
        label = panel.findChild(QtWidgets.QLabel, "label")
        refs = panel.findChild(QtWidgets.QListWidget, "listWidgetReferences")
        self.pick = panel.findChild(QtWidgets.QToolButton, "buttonRefSel")
        if not isinstance(layout, QtWidgets.QVBoxLayout) or value is None or refs is None:
            return
        grid = _holder(layout, value)
        row = QtWidgets.QHBoxLayout()
        for widget in (label, value):
            if widget is not None:
                if grid is not None:
                    grid.removeWidget(widget)
                row.addWidget(widget, 0 if widget is label else 1)
        layout.insertLayout(0, row)
        refs.setToolTip("Faces to Remove")
        refs.setMaximumHeight(110)

        if self.pick is not None:
            self.pick.hide()
            refs.viewport().installEventFilter(self)
        for combo_name, label_name in self.DEFAULTS:
            combo = panel.findChild(QtWidgets.QComboBox, combo_name)
            if combo is not None and combo.currentIndex() == 0:
                combo.hide()
                text = panel.findChild(QtWidgets.QLabel, label_name)
                if text is not None:
                    text.hide()
        crossing = panel.findChild(QtWidgets.QCheckBox, "checkIntersection")
        if crossing is not None and not crossing.isChecked():
            crossing.hide()
        self._preview(view, layout)

    def _preview(self, view, layout):
        final = view.findChild(QtWidgets.QCheckBox, "showFinalCheckBox")
        if final is None:
            return
        box = final.parentWidget()
        while box is not None and "TaskPreviewParameters" not in box.metaObject().className():
            box = box.parentWidget()
        self.show = QtWidgets.QCheckBox("Show preview")
        self.show.setObjectName("SWStyle_ShowPreview")
        self.show.setChecked(final.isChecked())
        layout.addWidget(self.show)
        self.show.toggled.connect(final.setChecked)
        final.toggled.connect(lambda on: _alive(self.show) and self.show.isChecked() != on and self.show.setChecked(on))
        if box is not None:
            box.hide()

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.MouseButtonPress and _alive(self.pick) and not self.pick.isChecked():
            self.pick.setChecked(True)
        return False


OWN = ("SWStyle_EndCondition", "SWStyle_EndCondition2", "SWStyle_Direction2", "SWStyle_UpToFaceBox",
       "SWStyle_UpToFaceBox2", "SWStyle_UpToBodyBox", "SWStyle_UpToBodyBox2", "SWStyle_OffsetRow", "SWStyle_OffsetRow2")


def _undo_partial(view, sides, mode):
    """ExtrudeFields failed part way: its widgets go, FreeCAD's come back (so nothing shows twice)."""
    try:
        purge_stale(view)
        for name in OWN:
            for w in view.findChildren(QtWidgets.QWidget, name):
                if isinstance(w, QtWidgets.QWidget):
                    w.hide()
                    w.setObjectName("")
                    w.deleteLater()
        for w in (sides, mode, view.findChild(QtWidgets.QLabel, "sidesLabel"), view.findChild(QtWidgets.QComboBox, "changeMode2"),
                  view.findChild(QtWidgets.QLabel, "side2Label")):
            if isinstance(w, QtWidgets.QWidget):
                w.setMaximumHeight(16777215)
                w.setMaximumWidth(16777215)
        for w in (mode, sides, view.findChild(QtWidgets.QLabel, "sidesLabel")):
            if isinstance(w, QtWidgets.QWidget):
                w.show()
    except Exception as _fw_err:
        _fw_log("pmfields.py:undo partial", _fw_err)


def install(view):
    """Marks FreeCAD's own widget, not the view: the Tasks view outlives each panel."""
    sides = view.findChild(QtWidgets.QComboBox, "sidesMode")
    mode = view.findChild(QtWidgets.QComboBox, "changeMode")
    if sides is not None and mode is not None and sides.count() == 3 and not sides.property(DONE):
        sides.setProperty(DONE, True)
        for attempt in (1, 2):
            try:
                purge_stale(view)
                ExtrudeFields(sides, sides, mode, view.findChild(QtWidgets.QLabel, "side2Label"))
                break
            except Exception as error:
                _undo_partial(view, sides, mode)        # a stale wrapper mid-way: take ours out, FreeCAD's back, try again
                if attempt == 2:
                    raise
    inward = view.findChild(QtWidgets.QCheckBox, "checkReverse")
    if inward is not None and not inward.property(DONE):
        inward.setProperty(DONE, True)
        ShellOutward(inward, inward)
        panel = inward.parentWidget()
        if panel is not None and panel.findChild(QtWidgets.QWidget, "listWidgetReferences") is not None:
            ShellFields(view, panel)
    try:
        from . import extrudepm
        purge_stale(view)
        extrudepm.install(view)
    except Exception as error:
        import FreeCAD as App
        App.Console.PrintLog("FreeCAD: extrude rows: %s\n" % error)
