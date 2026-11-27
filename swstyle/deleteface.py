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
from PySide import QtCore, QtWidgets
from . import naming, pmboxes

TYPE = "PartDesign::FeaturePython"
COMMAND = "SWStyle_DeleteFace"
OPTIONS = ["Delete", "Delete and Patch", "Delete and Fill"]


def _same(a, b):
    return a.isSame(b)


def boundary_loops(faces):
    """Edges used by only one of the faces, grouped into connected loops."""
    import Part
    count = []
    for f in faces:
        # OrderedEdges keeps a seam twice (once each way round), so it never counts as free
        for e in (e for w in f.Wires for e in w.OrderedEdges):
            for item in count:
                if _same(item[0], e):
                    item[1] += 1
                    break
            else:
                count.append([e, 1])
    free = [e for e, n in count if n == 1]
    if not free:
        return []
    return Part.sortEdges(free)


def _plane_key(wire):
    try:
        plane = wire.findPlane(1e-6)
    except Exception:
        plane = None
    if plane is None:
        return None
    n = App.Vector(plane.Axis)
    n.normalize()
    if n.x < -1e-9 or (abs(n.x) < 1e-9 and (n.y < -1e-9 or (abs(n.y) < 1e-9 and n.z < 0))):
        n = n * -1
    d = n.dot(App.Vector(plane.Position))
    return n, d


def fill_faces(loops, keep=None, tangent=False):
    """One new face per hole: loops on one plane become one face with holes in it (a deleted
    top face with holes through it comes back as one face with those holes), any other loop gets
    a filling surface. With tangent, a single loop gets a surface tangent to the keep faces round
    it (a loop with holes inside it stays flat, a filling surface can't have holes)."""
    import Part
    groups, others = [], []
    for loop in loops:
        try:
            wire = Part.Wire(Part.__sortEdges__(loop))
        except Exception:
            others.append(loop)
            continue
        key = _plane_key(wire) if wire.isClosed() else None
        if key is None:
            others.append(loop)
            continue
        for g in groups:
            if (g[0][0] - key[0]).Length < 1e-7 and abs(g[0][1] - key[1]) < 1e-6:
                g[1].append(wire)
                break
        else:
            groups.append([key, [wire]])
    out = []
    for key, wires in groups:
        if tangent and keep and len(wires) == 1:
            others.append(wires[0].Edges)
            continue
        face = Part.makeFace(wires, "Part::FaceMakerBullseye")
        out += face.Faces
    for loop in others:
        face = _tangent_filling(loop, keep) if tangent and keep else None
        out.append(face if face is not None else _filling(loop))
    return out


def _same_edge(a, b):
    if a.isSame(b):
        return True
    return abs(a.Length - b.Length) < 1e-7 and (a.CenterOfMass - b.CenterOfMass).Length < 1e-7


def _tangent_filling(loop, keep):
    """A filling surface through the loop, tangent (G1) to the keep face on each edge. Done with
    a Surface Filling in a hidden scratch document, which is how FreeCAD exposes OpenCascade's
    filling with face constraints; None if it fails (the caller falls back to a plain fill)."""
    import Part
    active = App.ActiveDocument
    tmp = None
    try:
        tmp = App.newDocument("SWDeleteFaceFill", hidden=True, temp=True)
        holder = tmp.addObject("Part::Feature", "Keep")
        holder.Shape = Part.Compound(keep)
        held = holder.Shape
        edges, faces = [], []
        for e in loop:
            # sortEdges can hand back rebuilt edges, so match by place as well as by identity
            i = next(k for k, x in enumerate(held.Edges) if _same_edge(x, e))
            j = next(k for k, x in enumerate(held.Faces) if any(y.isSame(held.Edges[i]) for y in x.Edges))
            edges.append((holder, "Edge%d" % (i + 1)))
            faces.append("Face%d" % (j + 1))
        fill = tmp.addObject("Surface::Filling", "Fill")
        fill.BoundaryEdges = edges
        fill.BoundaryFaces = faces
        fill.BoundaryOrder = [1] * len(edges)  # 1 = G1, tangent
        tmp.recompute()
        if not fill.isValid() or fill.Shape.isNull() or not fill.Shape.Faces:
            return None
        return fill.Shape.Faces[0].copy()
    except Exception:
        return None
    finally:
        if tmp is not None:
            App.closeDocument(tmp.Name)
        if active is not None:
            App.setActiveDocument(active.Name)


def _filling(loop):
    """A surface through a loop that isn't flat: a filling surface on the ordered edges, or for
    two curves joined by two straight edges (a deleted fillet) the ruled surface between them."""
    import Part
    edges = Part.__sortEdges__(loop)
    try:
        face = Part.makeFilledFace(edges)
        if face.isValid() and face.Area > 1e-9:
            return face
    except Exception as _fw_err:
        _fw_log("deleteface.py:165", _fw_err)
    curved = [e for e in edges if not isinstance(e.Curve, Part.Line)]
    if len(edges) == 4 and len(curved) == 2:
        return Part.makeRuledSurface(curved[0], curved[1])
    raise RuntimeError("The gap left by these faces could not be filled")


def delete_faces(base, faces, option, tangent=False):
    ""
    import Part
    if not faces:
        return base
    if option == "Delete and Patch":
        result = base.defeaturing(faces)
        unchanged = len(result.Faces) == len(base.Faces) and abs(result.Volume - base.Volume) < 1e-9
        if result.isNull() or unchanged:
            raise RuntimeError("These faces can't be patched: the faces round them don't meet when grown. "
                               "Try Delete and Fill.")
        try:
            result = result.removeSplitter()
        except Exception as _fw_err:
            _fw_log("deleteface.py:186", _fw_err)
        return result
    keep = [f for f in base.Faces if not any(_same(f, g) for g in faces)]
    if not keep:
        raise RuntimeError("Every face would be deleted")
    if option == "Delete":
        shell = Part.Shell(keep) if len(keep) > 1 else keep[0]
        try:
            sewn = Part.Shape(shell).copy()
            sewn.sewShape()
            return sewn
        except Exception:
            return shell
    # Delete and Fill
    fills = fill_faces(boundary_loops(keep), keep, tangent)
    sewn = Part.Compound(keep + fills)
    sewn.sewShape()
    shells = [sh for sh in sewn.Shells if sh.isClosed()]
    if not shells:
        raise RuntimeError("The gap left by these faces could not be filled")
    solid = Part.Solid(shells[0])
    if solid.Volume < 0:
        solid.reverse()
    try:
        solid = solid.removeSplitter()
    except Exception as _fw_err:
        _fw_log("deleteface.py:212", _fw_err)
    if not solid.isValid():
        solid.fix(1e-6, 1e-6, 1e-6)
    return solid


class DeleteFaceFeature:
    def __init__(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def setup(self, obj):
        if "Faces" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLinkSub", "Faces", "Delete Face", "Faces to delete")
        if "Option" not in obj.PropertiesList:
            obj.addProperty("App::PropertyEnumeration", "Option", "Delete Face",
                            "Delete (leaves a surface body), Delete and Patch, or Delete and Fill")
            obj.Option = OPTIONS
            obj.Option = "Delete and Patch"
        if "TangentFill" not in obj.PropertiesList:
            obj.addProperty("App::PropertyBool", "TangentFill", "Delete Face",
                            "Delete and Fill: make the new face tangent to the faces round the hole")

    def execute(self, obj):
        import Part
        if getattr(obj, "BaseFeature", None) is not None:
            base = obj.BaseFeature.Shape
        else:

            base = obj.Faces[0].Shape if obj.Faces is not None and obj.Faces[0] is not None else None
        if base is None or base.isNull():
            raise RuntimeError("Delete Face needs a part")
        if obj.Faces is None or not obj.Faces[1]:
            obj.Shape = base
            return
        source, subs = obj.Faces
        faces = []
        for sub in subs:
            try:
                faces.append(source.Shape.getElement(sub.split(".")[-1].lstrip("?")))
            except Exception as _fw_err:
                _fw_log("deleteface.py:253", _fw_err)
        # faces found by the base shape's own faces (the link may be to an earlier feature)
        faces = [f for f in base.Faces if any(_same(f, g) or _close(f, g) for g in faces)]
        obj.Shape = delete_faces(base, faces, obj.Option, obj.TangentFill)

    def onDocumentRestored(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _close(a, b):
    """Same face by place and size, for a link to a face of a feature with the same geometry."""
    try:
        return abs(a.Area - b.Area) < 1e-7 and (a.CenterOfMass - b.CenterOfMass).Length < 1e-7
    except Exception:
        return False


class DeleteFaceView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return ""

    def claimChildren(self):
        return []

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _body(doc):
    try:
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
    except Exception:
        body = None
    if body is None:
        for sel in Gui.Selection.getSelectionEx():
            for parent in [sel.Object] + list(sel.Object.InList):
                if parent.TypeId == "PartDesign::Body":
                    return parent
        bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
        body = bodies[0] if len(bodies) == 1 else None
    return body


def free_source(obj):
    """The object itself when it is a body outside PartDesign with faces (a surface body)."""
    try:
        if obj is None or obj.TypeId.startswith(("Sketcher::", "App::", "PartDesign::")) or obj.Shape.isNull() \
                or not obj.Shape.Faces:
            return None
        if any(p.TypeId == "PartDesign::Body" for p in obj.InList):
            return None
        return obj
    except Exception as _fw_err:
        _fw_log("deleteface.py:323", _fw_err)
        return None


def make_free(source, faces, option="Delete", tangent=False):
    """Delete Face on a surface body: a new body without the faces; the original is hidden."""
    doc = source.Document
    doc.openTransaction("Delete Face")
    obj = doc.addObject("Part::FeaturePython", "DeleteFace")
    DeleteFaceFeature(obj)
    if App.GuiUp:
        DeleteFaceView(obj.ViewObject)
    obj.Label = naming.next_label(doc, "DeleteFace")
    obj.Option = option
    obj.TangentFill = bool(tangent)
    obj.Faces = (source, list(faces))
    doc.recompute()
    if not obj.isValid() or obj.Shape.isNull():
        msg = obj.getStatusString()
        doc.abortTransaction()
        doc.recompute()
        raise RuntimeError(msg)
    if App.GuiUp and source.ViewObject is not None:
        source.ViewObject.Visibility = False
    doc.commitTransaction()
    return obj


def make(body, faces, option="Delete and Patch", tangent=False):
    """Delete Face after the body's tip. faces = ["Face3", ...] of the tip."""
    doc = body.Document
    doc.openTransaction("Delete Face")
    obj = body.newObject(TYPE, "DeleteFace")
    DeleteFaceFeature(obj)
    if App.GuiUp:
        DeleteFaceView(obj.ViewObject)
    obj.Label = naming.next_label(doc, "DeleteFace")
    obj.Option = option
    obj.TangentFill = bool(tangent)
    obj.Faces = (obj.BaseFeature, list(faces))
    doc.recompute()
    if not obj.isValid():
        msg = obj.getStatusString()
        doc.abortTransaction()
        doc.recompute()
        raise RuntimeError(msg)
    doc.commitTransaction()
    return obj


class DeleteFaceForm(QtWidgets.QDialog):
    def __init__(self, count):
        super().__init__(Gui.getMainWindow())
        self.setWindowTitle("Delete Face")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("%d face%s to delete" % (count, "" if count == 1 else "s")))
        box = QtWidgets.QGroupBox("Options")
        inner = QtWidgets.QVBoxLayout(box)
        self.buttons = []
        for name in OPTIONS:
            b = QtWidgets.QRadioButton(name)
            inner.addWidget(b)
            self.buttons.append(b)
        self.tangent = QtWidgets.QCheckBox("Tangent fill")
        self.tangent.setContentsMargins(18, 0, 0, 0)
        inner.addWidget(self.tangent)
        for b in self.buttons:
            b.toggled.connect(self._options)
        self.buttons[1].setChecked(True)
        self._options()
        lay.addWidget(box)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _options(self, *args):

        self.tangent.setVisible(self.buttons[2].isChecked())
        if hasattr(self, "preview_box"):
            self._preview()

    def option(self):
        return next(b.text() for b in self.buttons if b.isChecked())


def _params():
    return App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks")


def _view_widget():
    try:
        from . import shell
        return shell.shell().view_widget()
    except Exception:
        return None


def _smooth(fa, fb, edge):
    """The two faces meet tangent along the edge (their normals agree at its middle)."""
    try:
        mid = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)
        na = fa.normalAt(*fa.Surface.parameter(mid))
        nb = fb.normalAt(*fb.Surface.parameter(mid))
        return abs(abs(na.dot(nb)) - 1.0) < 1e-3
    except Exception:
        return False


class DeleteFacePanel:
    ""


    def __init__(self, body, faces=(), source=None):
        self.body = body
        self.source = source            # a surface body (no PartDesign tip): its faces are deleted
        self.doc = body.Document if body is not None else (source.Document if source is not None else App.ActiveDocument)
        self.faces = list(faces)
        page = QtWidgets.QWidget()
        page.setWindowTitle("Selections")
        page.setProperty("swstyle_pm_title", "Delete Face")
        page.setProperty("swstyle_pm_icon", "FEATURES_DELETE_FACE")
        lay = QtWidgets.QVBoxLayout(page)

        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWStyle_DeleteFaces")
        self.list.setToolTip("Faces to delete")
        self.list.setMaximumHeight(80)
        pmboxes.mark(self.list, True)
        pmboxes.bind(self.list, remove=self._drop_face)
        lay.addWidget(self.list)
        self.toolbar_box = QtWidgets.QCheckBox("Show selection toolbar")
        self.toolbar_box.setObjectName("SWStyle_DeleteFace_SelectionToolbar")
        self.toolbar_box.setChecked(_params().GetBool("DeleteFaceSelectionToolbar", True))
        self.toolbar_box.toggled.connect(self._toolbar_toggled)
        lay.addWidget(self.toolbar_box)
        lay.addStretch(1)
        options = QtWidgets.QWidget()
        options.setWindowTitle("Options")
        inner = QtWidgets.QVBoxLayout(options)
        self.buttons = []
        for name in OPTIONS:
            b = QtWidgets.QRadioButton(name)
            b.setObjectName("SWStyle_DeleteFace_" + name.replace(" ", ""))
            inner.addWidget(b)
            self.buttons.append(b)
        self.tangent = QtWidgets.QCheckBox("Tangent fill")
        self.tangent.setObjectName("SWStyle_DeleteFace_TangentFill")
        inner.addWidget(self.tangent)
        self.preview_box = QtWidgets.QCheckBox("Show preview")
        self.preview_box.setObjectName("SWStyle_DeleteFace_ShowPreview")
        self.preview_box.setChecked(_params().GetBool("DeleteFaceShowPreview", False))
        self.preview_box.toggled.connect(self._preview_toggled)
        inner.addWidget(self.preview_box)

        self.message = QtWidgets.QLabel("")
        self.message.setWordWrap(True)
        self.message.setVisible(False)
        inner.addWidget(self.message)
        self._preview_node = None
        self.strip = None
        for b in self.buttons:
            b.toggled.connect(self._options)
        self.tangent.toggled.connect(lambda _on: self._preview())

        self.buttons[0 if body is None or body.Tip is None else 1].setChecked(True)
        self.form = [page, options]
        try:
            from . import selectiontoolbar
            view = _view_widget()
            self.strip = selectiontoolbar.Strip(self, view) if view is not None else None
        except Exception:
            self.strip = None
        self._show()
        Gui.Selection.addObserver(self)
        try:
            # Faces to delete: a click by a face's edge stays on the face
            from . import facehover

            def faces_page(me):
                f = me.form[0] if isinstance(me.form, list) else me.form
                return f.isVisible()
            facehover.faces_only(self, faces_page)
        except Exception:
            pass

    # -------------------------------------------------------------- selection toolbar
    # selectiontoolbar.Strip talks to its panel through base / items / update() / selection_sets()
    @property
    def base(self):
        return self.source if self.source is not None else (self.body.Tip or self.body)

    @property
    def items(self):
        return self.faces

    def update(self):
        self._show()

    set_unit = "Faces"

    def selection_sets(self, sub):
        ""
        shape = self.base.Shape
        try:
            face = shape.getElement(sub)
        except Exception:
            return []
        index = {i: f for i, f in enumerate(shape.Faces)}
        start = next((i for i, f in index.items() if f.isSame(face)), None)
        if start is None:
            return []
        import Part
        neighbours, tangent_to = {}, {}
        for e in shape.Edges:
            owners = [i for i, f in index.items() if any(e.isSame(x) for x in f.Edges)]
            if len(owners) != 2:
                continue
            a, b = owners
            neighbours.setdefault(a, set()).add(b)
            neighbours.setdefault(b, set()).add(a)
            if _smooth(index[a], index[b], e):
                tangent_to.setdefault(a, set()).add(b)
                tangent_to.setdefault(b, set()).add(a)
        seen, todo = {start}, [start]
        while todo:
            for n in tangent_to.get(todo.pop(), ()):
                if n not in seen:
                    seen.add(n)
                    todo.append(n)
        out = []
        tangent = sorted(seen - {start})
        if tangent:
            out.append(("feature", "Tangent faces", ["Face%d" % (i + 1) for i in [start] + tangent]))
        near = sorted(neighbours.get(start, ()))
        if near:
            out.append(("outside", "Adjacent faces", ["Face%d" % (i + 1) for i in near]))
        return out

    def _toolbar_toggled(self, on):
        _params().SetBool("DeleteFaceSelectionToolbar", on)
        if self.strip is not None:
            if on and self.faces:
                self.strip.show_for(self.faces[-1])
            else:
                self.strip.close_strip()

    # -------------------------------------------------------------- preview
    def _preview_toggled(self, on):
        _params().SetBool("DeleteFaceShowPreview", on)
        self._preview()

    def _clear_preview(self):
        node, self._preview_node = self._preview_node, None
        if node is None:
            return
        try:
            Gui.ActiveDocument.ActiveView.getSceneGraph().removeChild(node)
        except Exception as _fw_err:
            _fw_log("deleteface.py:570", _fw_err)

    def _preview(self):
        """Show preview: the part as it will be, drawn over the model in yellow."""
        self._clear_preview()
        self.message.setVisible(False)
        if not self.preview_box.isChecked() or not self.faces:
            return
        try:
            base = self.base.Shape
            picked = []
            for f in self.faces:
                try:
                    picked.append(base.getElement(f))
                except Exception as _fw_err:
                    _fw_log("deleteface.py:585", _fw_err)
            tangent = self.option() == OPTIONS[2] and self.tangent.isChecked()
            shape = delete_faces(base, picked, self.option(), tangent)
            from pivy import coin
            inp = coin.SoInput()
            inp.setBuffer(shape.writeInventor())
            geo = coin.SoDB.readAll(inp)
            if geo is None:
                return
            sep = coin.SoSeparator()
            pick = coin.SoPickStyle()
            pick.style = coin.SoPickStyle.UNPICKABLE
            sep.addChild(pick)
            mat = coin.SoMaterial()
            mat.diffuseColor = (0.95, 0.85, 0.2)
            mat.transparency = 0.35
            mat.setOverride(True)
            sep.addChild(mat)
            sep.addChild(geo)
            Gui.ActiveDocument.ActiveView.getSceneGraph().addChild(sep)
            self._preview_node = sep
        except Exception as error:
            self.message.setText(str(error))
            self.message.setStyleSheet("color: #c00000;")
            self.message.setVisible(True)

    def _options(self, *args):

        self.tangent.setVisible(self.buttons[2].isChecked())
        if hasattr(self, "preview_box"):
            self._preview()

    def option(self):
        return next(b.text() for b in self.buttons if b.isChecked())

    def _drop_face(self, row):
        ""
        if 0 <= row < len(self.faces):
            del self.faces[row]
            self._show()
            if self.faces:
                self.list.setCurrentRow(min(row, len(self.faces) - 1))

    def _show(self):
        self.list.clear()
        holder = self.base
        for i, f in enumerate(self.faces):
            item = QtWidgets.QListWidgetItem("Face<%d>" % (i + 1))
            item.setToolTip("%s@%s" % (f, holder.Label))
            self.list.addItem(item)
        if hasattr(self, "preview_box"):
            self._preview()

    def _gone(self):
        """The PM was closed some other way: stop listening."""
        if Gui.Control.activeDialog():
            return False
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("deleteface.py:645", _fw_err)
        return True

    def addSelection(self, doc, name, sub, pnt):
        if doc != self.doc.Name or self._gone():
            return
        if self.body is None or self.body.Tip is None:
            picked = free_source(self.doc.getObject(name))
            if picked is None or (self.source is not None and picked is not self.source and self.faces):
                return
            self.source = picked
        face = sub.split(".")[-1]
        if face.startswith("Face"):
            from . import safe_later as _sl; _sl.later(0, lambda: self._picked(face, True), self, "toolbar_box")

    def removeSelection(self, doc, name, sub):
        if doc != self.doc.Name or self._gone():
            return
        face = sub.split(".")[-1]
        if face.startswith("Face"):
            from . import safe_later as _sl; _sl.later(0, lambda: self._picked(face, False), self, "toolbar_box")

    def _picked(self, face, add):
        if add and face not in self.faces:
            self.faces.append(face)
        elif not add and face in self.faces:
            self.faces.remove(face)         # a second click on a picked face takes it out
        self._show()
        if self.strip is not None:
            if add and self.toolbar_box.isChecked():
                self.strip.show_for(face)
            else:
                self.strip.close_strip()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("deleteface.py:686", _fw_err)
        self._clear_preview()
        if self.strip is not None:
            try:
                self.strip.remove()
            except Exception as _fw_err:
                _fw_log("deleteface.py:692", _fw_err)
            self.strip = None
        Gui.Control.closeDialog()

    def accept(self):
        if not self.faces:
            self.message.setText("Select the faces to delete.")
            self.message.setStyleSheet("color: #c00000;")
            self.message.setVisible(True)
            return False
        self._clear_preview()
        try:
            tangent = self.option() == OPTIONS[2] and self.tangent.isChecked()
            if self.source is not None:
                make_free(self.source, self.faces, self.option(), tangent)
            else:
                make(self.body, self.faces, self.option(), tangent)
        except Exception as error:
            self.message.setText(str(error))
            self.message.setStyleSheet("color: #c00000;")
            self.message.setVisible(True)
            return False
        self._close()
        return True

    def reject(self):
        self._close()
        return True


def delete_face_command():
    doc = App.ActiveDocument
    body = _body(doc) if doc is not None else None
    faces, source = [], None
    for sel in Gui.Selection.getSelectionEx():
        found = [s.split(".")[-1] for s in sel.SubElementNames if s.split(".")[-1].startswith("Face")]
        free = free_source(sel.Object)
        if free is not None and found and (body is None or body.Tip is None):
            source = source or free
            if free is not source:
                continue
        faces += found
    if source is not None or (doc is not None and (body is None or body.Tip is None)
                              and any(free_source(o) for o in doc.Objects)):

        panel = DeleteFacePanel(body, faces if source is not None else [], source)
        Gui.Control.showDialog(panel)
        return panel
    if body is None or body.Tip is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Delete Face",
                                          "Delete Face works on a part body: make or open a part first.")
        return None
    panel = DeleteFacePanel(body, faces)
    Gui.Control.showDialog(panel)
    return panel


class _Cmd:
    def GetResources(self):
        return {"MenuText": "Delete Face",
                "ToolTip": "Deletes faces of the part: leave it open, patch the gap, or fill it."}

    def Activated(self):
        delete_face_command()

    def IsActive(self):
        doc = App.ActiveDocument
        return doc is not None and not Gui.Control.activeDialog() and \
            any(o.TypeId == "PartDesign::Body" or free_source(o) is not None for o in doc.Objects)


_installed = False


def install():
    global _installed
    if _installed:
        return
    if Gui.Command.get(COMMAND) is None:
        Gui.addCommand(COMMAND, _Cmd())
    _installed = True
