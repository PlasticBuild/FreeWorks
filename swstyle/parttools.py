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

import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from .widgets import ui_font


# ------------------------------------------------------------------ Invert Selection
def _kind(sub):
    for k in ("Face", "Edge", "Vertex"):
        if sub.startswith(k):
            return k
    return ""


def inverted_selection():
    """[(object, sub)] that Invert Selection picks: the other faces (edges, vertices) of the same
    objects when elements are picked; the other visible objects when whole objects are."""
    sel = Gui.Selection.getSelectionEx()
    out = []
    whole = [s.Object for s in sel if not s.SubElementNames]
    for s in sel:
        if not s.SubElementNames:
            continue
        kinds = {_kind(n) for n in s.SubElementNames} - {""}
        picked = set(s.SubElementNames)
        shape = s.Object.Shape
        for kind in kinds:
            count = len({"Face": shape.Faces, "Edge": shape.Edges, "Vertex": shape.Vertexes}[kind])
            for i in range(1, count + 1):
                name = "%s%d" % (kind, i)
                if name not in picked:
                    out.append((s.Object, name))
    if whole:
        from .evaluate import visible_bodies
        for obj in visible_bodies(whole[0].Document):
            if obj not in whole:
                out.append((obj, ""))
    return out


def invert_selection():
    picks = inverted_selection()
    if not picks and not Gui.Selection.getSelectionEx():
        return
    Gui.Selection.clearSelection()
    for obj, sub in picks:
        Gui.Selection.addSelection(obj.Document.Name, obj.Name, sub)


# ------------------------------------------------------------------ Delete Hole
class DeleteHole:
    ""


    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty("App::PropertyLinkSubList", "Faces", "Delete Hole", "Hole edges, or faces whose holes are removed")

    def execute(self, obj):
        import Part
        out = []
        for link, subs in obj.Faces:
            shape = link.Shape
            whole, loops = set(), []
            for sub in subs:
                name = sub.split(".")[-1].lstrip("?")
                if name.startswith("Face"):
                    whole.add(int(name[4:]) - 1)
                elif name.startswith("Edge"):
                    loops.append(shape.getElement(name))
            out += filled_body(shape, whole, loops)
        if not out:
            obj.Shape = Part.Shape()
            return
        obj.Shape = out[0] if len(out) == 1 else Part.Compound(out)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def filled_body(shape, whole=(), edges=()):
    """[the surface body with holes filled]: every inner loop of the faces whole (indexes), and the inner
    loops holding one of edges."""
    import Part
    faces, changed = [], False
    for i, face in enumerate(shape.Faces):
        outer = face.OuterWire
        inner = [w for w in face.Wires if not w.isSame(outer)]
        keep = [] if i in whole else [w for w in inner if not any(any(e.isSame(x) for x in w.Edges) for e in edges)]
        if len(keep) != len(inner):
            new = Part.Face(face.Surface, [outer] + keep) if keep else fill_holes(face)
            try:
                new.validate()
            except Exception as _fw_err:
                _fw_log("parttools.py:118", _fw_err)
            faces.append(new)
            changed = True
        else:
            faces.append(face)
    if not changed:
        return [shape]
    if len(faces) == 1:
        return faces
    try:
        shell = Part.Shell(faces)
        if shell.isValid():
            return [shell]
    except Exception as _fw_err:
        _fw_log("parttools.py:132", _fw_err)
    return [Part.Compound(faces).sewShape() or Part.Compound(faces)]


def fill_holes(face):
    import Part
    new = Part.Face(face.Surface, face.OuterWire)
    try:
        new.validate()
    except Exception as _fw_err:
        _fw_log("parttools.py:142", _fw_err)
    return new


def delete_hole():
    picks = []
    for s in Gui.Selection.getSelectionEx():
        subs = [n for n in s.SubElementNames if n.startswith(("Face", "Edge"))]
        if subs:
            picks.append((s.Object, subs))
    if not picks:
        from . import pickfirst
        return pickfirst.ask("Delete Hole", "Hole edges (or faces with the holes) to delete", ("Edge", "Face"), delete_hole)
    doc = App.ActiveDocument
    doc.openTransaction("Delete Hole")
    try:
        obj = doc.addObject("Part::FeaturePython", "DeleteHole")
        DeleteHole(obj)
        if App.GuiUp:
            obj.ViewObject.Proxy = 0
        obj.Label = "Delete Hole"
        obj.Faces = picks
        doc.recompute()
        if App.GuiUp and obj.isValid():
            for link, _subs in picks:
                try:
                    link.ViewObject.Visibility = False      # the surface body is now the filled one
                except Exception as _fw_err:
                    _fw_log("parttools.py:169", _fw_err)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()


# ------------------------------------------------------------------ Blend Curve
def _picked_edges():
    out = []
    for s in Gui.Selection.getSelectionEx():
        out += [(s.Object, n) for n in s.SubElementNames if n.startswith("Edge")]
    return out


def blend_curve():
    """FreeCAD's Surface Blend Curve wants its two edges picked first; with fewer, a pick PM asks for them."""
    if len(_picked_edges()) != 2:
        from . import pickfirst
        return pickfirst.ask("Blend Curve", "Two edges to join with a smooth curve", ("Edge",), blend_curve,
                             minimum=2, maximum=2)
    try:
        import SurfaceGui  # noqa: F401  (the Surface workbench's commands)
    except Exception as _fw_err:
        _fw_log("parttools.py:190", _fw_err)
    Gui.runCommand("Surface_BlendCurve", 0)
    doc.recompute()
    for src, _ in picks:

        if not src.Shape.Solids and src.ViewObject is not None:
            src.ViewObject.Visibility = False
    doc.commitTransaction()
    return obj


# ------------------------------------------------------------------ Radiate Surface
class RadiateSurface:
    """Insert > Surface > Radiate: a surface running out from planar edges, in their plane, for
    a set distance (the faces between the edges and their 2D offset)."""

    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty("App::PropertyLinkSubList", "Edges", "Radiate Surface", "Edges to radiate from")
        obj.addProperty("App::PropertyLength", "Distance", "Radiate Surface", "How far the surface runs").Distance = 10.0
        obj.addProperty("App::PropertyBool", "Flip", "Radiate Surface", "Radiate to the other side")
        obj.addProperty("App::PropertyVector", "Normal", "Radiate Surface",
                        "Normal of the plane the surface runs in, for edges that do not set a plane themselves")
        obj.Normal = App.Vector(0, 0, 1)

    def execute(self, obj):
        solids = []
        for link, _subs in obj.Edges:
            try:
                solids += list(link.Shape.Solids)
            except Exception as _fw_err:
                _fw_log("parttools.py:221", _fw_err)
        obj.Shape = radiate(_linked_edges(obj.Edges), obj.Distance.Value * (-1 if obj.Flip else 1), obj.Normal,
                            solids=solids)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _linked_edges(links):
    edges = []
    for link, subs in links:
        for sub in subs:
            try:
                edges.append(link.Shape.getElement(sub))
            except Exception:
                edges.append(link.Shape.getElement(sub.split(".")[-1].lstrip("?")))
    return edges


def _away(edge, out, solids):
    ""
    if not solids:
        return out
    import Part
    mid = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
    step = max(edge.Length * 0.01, 1e-3)
    probe = Part.Vertex(mid + out * step)
    for solid in solids:
        try:
            if solid.isInside(probe.Point, 1e-7, True) and solid.distToShape(probe)[0] < 1e-6:
                return out * -1         # it would lie on one of the part's faces
        except Exception:
            continue
    return out


def radiate(edges, distance, normal=App.Vector(0, 0, 1), solids=None):
    import Part
    if not edges or abs(distance) < 1e-9:
        return Part.Shape()
    faces = []
    for group in Part.sortEdges(edges):
        wire = Part.Wire(group)
        if wire.findPlane() is not None:

            res = wire.makeOffset2D(distance, 2, True, not wire.isClosed(), False)
            faces += res.Faces
            continue
        # straight edges set no plane: run each one out square to it, in the plane of `normal`
        for e in group:
            tangent = e.tangentAt((e.FirstParameter + e.LastParameter) / 2)
            out = normal.cross(tangent)
            if out.Length < 1e-9:
                raise ValueError("an edge runs along the plane's normal: pick edges that lie in the "
                                 "direction reference's plane")
            faces += e.extrude(_away(e, out.normalize(), solids) * distance).Faces
    return faces[0] if len(faces) == 1 else Part.makeShell(faces) if faces else Part.Shape()


def _plane_normal(picks):
    """Normal of a picked planar face or datum plane; else of a planar face next to the first edge."""
    import Part
    for obj, subs in picks:
        if obj.isDerivedFrom("App::Plane") or obj.TypeId == "PartDesign::Plane":
            return obj.Placement.Rotation.multVec(App.Vector(0, 0, 1))
    for obj, subs in picks:
        for sub in subs:
            if sub.startswith("Face"):
                f = obj.Shape.getElement(sub)
                if isinstance(f.Surface, Part.Plane):
                    return f.normalAt(0, 0)
    # the planar face most of the picked edges border (the top face for a picked top loop)
    count = []
    for obj, subs in picks:
        for sub in subs:
            if not sub.startswith("Edge"):
                continue
            e = obj.Shape.getElement(sub)
            for f in obj.Shape.ancestorsOfType(e, Part.Face):
                if not isinstance(f.Surface, Part.Plane):
                    continue
                for entry in count:
                    if entry[0].isSame(f):
                        entry[1] += 1
                        break
                else:
                    count.append([f, 1])
    if count:
        best = max(count, key=lambda entry: entry[1])[0]
        return best.normalAt(0, 0)
    return App.Vector(0, 0, 1)


def radiate_surface(distance=10.0):
    picks, refs = [], []
    for sel in Gui.Selection.getSelectionEx():
        subs = [n for n in sel.SubElementNames if n.startswith("Edge")]
        if subs:
            picks.append((sel.Object, subs))
        refs.append((sel.Object, list(sel.SubElementNames)))
    if not picks:
        from . import pickfirst
        return pickfirst.ask("Radiate Surface", "Edges to Radiate (in one plane)", ("Edge",),
                             lambda: radiate_surface(distance))
    doc = App.ActiveDocument
    doc.openTransaction("Radiate Surface")
    try:
        obj = doc.addObject("Part::FeaturePython", "RadiateSurface")
        RadiateSurface(obj)
        if App.GuiUp:
            obj.ViewObject.Proxy = 0
        obj.Label = "Radiate Surface"
        obj.Edges = picks
        obj.Normal = _plane_normal(refs)
        obj.Distance = distance
        doc.recompute()
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return obj


# ------------------------------------------------------------------ Add Comment
def set_comment(obj, text):
    ""

    if "Comment" not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", "Comment", "Comment", "Comment on this item")
    obj.Comment = text
    obj.Label2 = text


def add_comment():
    picked = [s.Object for s in Gui.Selection.getSelectionEx()]
    if len(picked) != 1:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Add Comment", "Select one feature, then click Add Comment.")
        return
    obj = picked[0]
    text, ok = QtWidgets.QInputDialog.getMultiLineText(Gui.getMainWindow(), "Comment",
                                                       "Comment on %s" % obj.Label, getattr(obj, "Comment", ""))
    if not ok:
        return
    App.ActiveDocument.openTransaction("Add Comment")
    try:
        set_comment(obj, text)
    except BaseException:
        try:
            App.ActiveDocument.abortTransaction()
        except Exception:
            pass
        raise
    App.ActiveDocument.commitTransaction()


# ------------------------------------------------------------------ Save Bodies
FORMATS = {"FreeCAD part (*.FCStd)": ".FCStd", "STEP (*.step)": ".step", "STL (*.stl)": ".stl"}


def save_bodies(bodies, folder, ext=".FCStd"):
    """Writes each body to <folder>/<body label><ext>. Returns the paths written."""
    paths = []
    active = App.ActiveDocument
    try:
        _save_each(bodies, folder, ext, paths)
    finally:
        # closing the hidden file left no active document: the part stays the one worked on
        if active is not None and App.ActiveDocument is not active:
            try:
                App.setActiveDocument(active.Name)
            except Exception as _fw_err:
                _fw_log("parttools.py:384", _fw_err)
    return paths


def _save_each(bodies, folder, ext, paths):
    for b in bodies:
        name = "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in b.Label).strip() or b.Name
        path = os.path.join(folder, name + ext)
        if ext == ".FCStd":
            doc = App.newDocument("SWSaveBody", hidden=True)
            try:
                source = _link_source(b)
                if source is not None:
                    _linked_body(doc, b, source)
                else:
                    feat = doc.addObject("Part::Feature", name.replace(" ", "_") or "Body")
                    feat.Shape = b.Shape.copy()
                    feat.Label = b.Label
                doc.recompute()
                doc.saveAs(path)
            finally:
                App.closeDocument(doc.Name)
        elif ext == ".step":
            b.Shape.exportStep(path)
        else:
            import Mesh
            import MeshPart
            mesh = MeshPart.meshFromShape(Shape=b.Shape, LinearDeflection=0.05, AngularDeflection=0.3)
            Mesh.Mesh(mesh).write(path)
        paths.append(path)


_UNLINKED = set()        # ids of bodies saved with Consume cut bodies on (saved as copies)


def _link_source(b):
    ""

    b = getattr(b, "source_row", b)
    if id(b) in _UNLINKED:
        return None
    if isinstance(b, _SolidRow):
        return (b.body, b.Label, b.index)
    if getattr(b, "TypeId", "") == "PartDesign::Body":
        return (b, "", 0)
    return None


def _linked_body(doc, b, source):
    """The new part: a Body whose base feature is a linked stock of the original body (createassembly.LinkedStock,
    as Insert into New Part makes)."""
    from . import createassembly
    body, solid_name, index = source
    stock = doc.addObject("Part::FeaturePython", "Stock")
    createassembly.LinkedStock(stock)
    stock.SourceDocument = body.Document.Name
    stock.SourceBody = body.Name
    if body.Document.FileName:
        try:
            stock.Source = body            # an external link, kept in the file
        except Exception as _fw_err:
            _fw_log("parttools.py:save link", _fw_err)
    createassembly.watch_sources()
    stock.SolidName = solid_name or ""
    stock.Index = int(index or 0)
    stock.BreakLink = False
    stock.Shape = b.Shape.copy()
    stock.Label = "Stock-" + b.Label
    try:
        if stock.ViewObject is not None:
            stock.ViewObject.Proxy = 0
            stock.ViewObject.Visibility = False
    except Exception as _fw_err:
        _fw_log("parttools.py:save link view", _fw_err)
    new = doc.addObject("PartDesign::Body", "Body")
    new.BaseFeature = stock
    new.Label = b.Label
    return new


class SaveBodiesPage:
    ""



    def __init__(self):
        from .evaluate import _solids_of
        doc = App.ActiveDocument
        self.doc = doc
        self.bodies = _save_rows(doc, [o for o in doc.Objects if _solids_of(o)
                                       and not any(p.isDerivedFrom("PartDesign::Body") for p in o.InList)])
        form = QtWidgets.QWidget()
        form.setWindowTitle("Save Bodies")
        form.setObjectName("SWSaveBodiesPM")
        lay = QtWidgets.QVBoxLayout(form)
        lay.addWidget(QtWidgets.QLabel("Resulting Parts"))
        start = os.path.dirname(doc.FileName) if doc.FileName else os.path.expanduser("~")
        self.table = QtWidgets.QTableWidget(len(self.bodies), 2)
        self.table.setObjectName("SWSaveBodiesParts")
        self.table.setHorizontalHeaderLabels(["Body", "File"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        for r, b in enumerate(self.bodies):
            it = QtWidgets.QTableWidgetItem(b.Label)
            it.setFlags((it.flags() | QtCore.Qt.ItemIsUserCheckable) & ~QtCore.Qt.ItemIsEditable)
            it.setCheckState(QtCore.Qt.Checked)
            self.table.setItem(r, 0, it)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(os.path.join(start, _file_name(b) + ".FCStd")))
        self.table.cellDoubleClicked.connect(self._browse)
        lay.addWidget(self.table, 1)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Save as"))
        self.fmt = QtWidgets.QComboBox()
        self.fmt.setObjectName("SWSaveBodiesFormat")
        self.fmt.addItems(list(FORMATS))
        self.fmt.currentTextChanged.connect(self._format)
        row.addWidget(self.fmt, 1)
        lay.addLayout(row)
        self.hide = QtWidgets.QCheckBox("Hide bodies")
        self.hide.setObjectName("SWSaveBodiesHide")
        self.hide.setToolTip("Hide the saved bodies in this part")
        self.consume = QtWidgets.QCheckBox("Consume cut bodies")
        self.consume.setObjectName("SWSaveBodiesConsume")
        self.consume.setToolTip("Take the saved bodies out of this part (Undo brings them back)")
        lay.addWidget(self.hide)
        lay.addWidget(self.consume)
        self.assembly = QtWidgets.QGroupBox("Create Assembly")
        self.assembly.setObjectName("SWSaveBodiesAssembly")
        self.assembly.setCheckable(True)
        self.assembly.setChecked(False)
        alay = QtWidgets.QHBoxLayout(self.assembly)
        self.asm_path = QtWidgets.QLineEdit(os.path.join(start, (doc.Label or "Part") + "_Assembly.FCStd"))
        self.asm_path.setObjectName("SWSaveBodiesAssemblyPath")
        browse = QtWidgets.QPushButton("Browse...")
        browse.clicked.connect(self._browse_assembly)
        alay.addWidget(self.asm_path, 1)
        alay.addWidget(browse)
        lay.addWidget(self.assembly)
        self.note = QtWidgets.QLabel("")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self.form = form

    # ---- table
    def _format(self, text):
        ext = FORMATS.get(text, ".FCStd")
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 1)
            it.setText(os.path.splitext(it.text())[0] + ext)

    def _browse(self, row, col):
        if col != 1:
            return
        it = self.table.item(row, 1)
        path, _f = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save Body", it.text())
        if path:
            it.setText(path)

    def _browse_assembly(self):
        path, _f = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Assembly", self.asm_path.text(),
                                                         "FreeCAD (*.FCStd)")
        if path:
            self.asm_path.setText(path)

    def chosen(self):
        return [(b, self.table.item(r, 1).text()) for r, b in enumerate(self.bodies)
                if self.table.item(r, 0).checkState() == QtCore.Qt.Checked]

    # ---- task panel
    def getStandardButtons(self):
        both = QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        return int(getattr(both, "value", both))

    def accept(self):
        picked = self.chosen()
        if not picked:
            self.note.setText("Tick at least one body under Resulting Parts.")
            return False
        _UNLINKED.clear()
        if self.consume.isChecked():        # the bodies leave this part: the new parts keep them as they are
            _UNLINKED.update(id(b) for b, _p in picked)
        try:
            paths = save_bodies_to(picked)
            if self.assembly.isChecked():
                make_assembly(self.asm_path.text(), paths)
        except Exception as error:
            self.note.setText("Could not save: %s" % error)
            return False
        bodies = [b for b, _p in picked]
        if self.consume.isChecked():
            self.doc.openTransaction("Save Bodies")
            try:
                gone = {}
                for b in bodies:
                    if isinstance(b, _SolidRow):
                        gone.setdefault(b.body.Name, (b.body, []))[1].append(b.index)
                    else:
                        self.doc.removeObject(b.Name)
                for body, indices in gone.values():
                    _delete_solids(body, indices)
            finally:
                self.doc.commitTransaction()
            self.doc.recompute()
        elif self.hide.isChecked():
            for b in bodies:
                try:
                    if isinstance(b, _SolidRow):
                        if b.row is not None:
                            b.row.ViewObject.Visibility = False
                    else:
                        b.ViewObject.Visibility = False
                except Exception as _fw_err:
                    _fw_log("parttools.py:541", _fw_err)
        Gui.getMainWindow().statusBar().showMessage("Saved %d bodies" % len(paths), 6000)
        Gui.Control.closeDialog()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


class _SolidRow:
    """One solid body of a PartDesign Body (Solid Bodies folder), as Save Bodies lists it."""

    def __init__(self, body, index, name, shape, row):
        self.body, self.index, self.row = body, index, row
        self.Label = name
        self.Name = "%s_%d" % (body.Name, index + 1)
        self.Shape = shape


def _save_rows(doc, objects):
    ""

    out = []
    try:
        from . import multibody as MB
    except Exception:
        MB = None
    for o in objects:
        if MB is None or o.TypeId != "PartDesign::Body":
            out.append(o)
            continue
        try:
            found = MB.solids(o)
        except Exception:
            found = []
        if len(found) < 2:
            out.append(o)
            continue
        rows = {}
        for r in MB.rows(doc):
            if r.Body == o.Name:
                rows.setdefault(r.Index, r)
        for i, (name, solid) in enumerate(found):
            s = solid.copy()
            s.Placement = o.Placement.multiply(s.Placement)
            out.append(_SolidRow(o, i, name.replace("\u200b", "") or "Body%d" % (i + 1), s, rows.get(i)))
    return out


def _delete_solids(body, indices):
    """Consume cut bodies for solids of a multibody Body: a Body-Delete/Keep at the end of its history."""
    from . import multibody as MB
    doc = body.Document
    MB._fix_compound(body)
    pieces = [s for _n, s in MB.solids(body)]
    obj = doc.addObject("PartDesign::FeaturePython", "DeleteKeep")
    MB.DeleteKeep(obj)
    if App.GuiUp:
        MB.BodyOpView(obj.ViewObject)
    try:
        from . import naming
        obj.Label = naming.next_label(doc, MB.DeleteKeep.TITLE)
    except Exception:
        obj.Label = MB.DeleteKeep.TITLE + "1"
    body.addObject(obj)
    obj.Bodies = [MB.ref_text(i, pieces[i]) for i in indices if 0 <= i < len(pieces)]
    obj.Keep = False
    doc.recompute()
    return obj


def _file_name(b):
    return "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in b.Label).strip() or b.Name


def save_bodies_to(picked):
    """[(body, path)]: each body written to its own path (the extension picks the format)."""
    paths = []
    for b, path in picked:
        folder, base = os.path.split(path)
        name, ext = os.path.splitext(base)
        ext = ext if ext in FORMATS.values() else ".FCStd"
        renamed = type("B", (), {"Label": name, "Name": b.Name, "Shape": b.Shape, "source_row": b})()
        paths += save_bodies([renamed], folder or ".", ext)
    return paths


def make_assembly(path, parts):
    """Create Assembly: a FreeCAD file linking each saved part file in place."""
    asm = App.newDocument("SWSaveBodiesAsm", hidden=True)
    opened = []
    try:
        asm.saveAs(path)  # a link to another file needs its owner saved first
        for p in parts:
            if not p.lower().endswith(".fcstd"):
                continue
            src = App.openDocument(p, hidden=True)
            opened.append(src.Name)
            # the part's Body (a derived part also holds its hidden linked stock), else its first object
            obj = next((o for o in src.Objects if o.TypeId == "PartDesign::Body"), src.Objects[0] if src.Objects else None)
            if obj is not None:
                link = asm.addObject("App::Link", obj.Name)
                link.LinkedObject = obj
                link.Label = obj.Label
        asm.recompute()
        asm.save()
    finally:
        App.closeDocument(asm.Name)
        for name in opened:
            try:
                App.closeDocument(name)
            except Exception as _fw_err:
                _fw_log("parttools.py:653", _fw_err)
    return path


def save_bodies_command():
    if Gui.Control.activeDialog():
        return None
    page = SaveBodiesPage()
    if not page.bodies:
        Gui.getMainWindow().statusBar().showMessage("Save Bodies: there are no bodies to save.", 6000)
        return None
    Gui.Control.showDialog(page)
    return page


# ------------------------------------------------------------------ commands
COMMANDS = {
    "SWStyle_InvertSelection": ("Invert Selection", "Selects every other face, edge or body of the same kind instead.",
                                invert_selection, lambda: bool(Gui.Selection.getSelectionEx())),
    "SWStyle_DeleteHole": ("Delete Hole", "Fills the holes of a surface face.", delete_hole,
                           lambda: App.ActiveDocument is not None),
    "SWStyle_BlendCurve": ("Blend Curve", "A smooth curve joining two edges.", blend_curve,
                           lambda: App.ActiveDocument is not None),
    "SWStyle_SaveBodies": ("Save Bodies", "Saves the part's bodies as separate files.", save_bodies_command,
                           lambda: App.ActiveDocument is not None),
    "SWStyle_RadiateSurface": ("Radiate Surface", "Makes a surface running out from planar edges, in their plane.",
                               radiate_surface, lambda: App.ActiveDocument is not None),
    "SWStyle_AddComment": ("Add Comment", "Adds a comment to the selected feature.", add_comment,
                           lambda: len(Gui.Selection.getSelectionEx()) == 1),
}


class _Cmd:
    def __init__(self, name):
        self.name = name

    def GetResources(self):
        menu, tip, _, _ = COMMANDS[self.name]
        resources = {"MenuText": menu, "ToolTip": tip}
        if self.name == "SWStyle_BlendCurve":
            from . import icons
            resources["Pixmap"] = icons.pixmap_path("SKETCH_SPLINE")
        return resources

    def Activated(self):
        COMMANDS[self.name][2]()

    def IsActive(self):
        try:
            return bool(COMMANDS[self.name][3]()) and not Gui.Control.activeDialog()
        except Exception:
            return False


_installed = False


def install():
    global _installed
    if _installed:
        return
    try:
        from . import comments
        comments.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: comments: %s\n" % error)
    for name in COMMANDS:
        if Gui.Command.get(name) is None:
            Gui.addCommand(name, _Cmd(name))
    _installed = True
