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

Qt = QtCore.Qt
COMMAND = "SWStyle_ImportDiagnostics"
TOLERANCE = 1e-7           # OpenCascade's working precision
SEW_TOLERANCE = 1e-3       # faces closer than this are sewn together (mm)
IMPORTED = ("Part::Feature", "Part::FeaturePython")


# ---------------------------------------------------------------- what is wrong
def face_problem(face):
    """Why a face is faulty, or None."""
    try:
        if not face.isValid():
            face.check(False)
            return "Invalid face"
    except Exception as error:
        text = str(error).strip().splitlines()
        return text[0] if text and text[0] else "Invalid face"
    if face.Area < TOLERANCE:
        return "Face with no area"
    return None


def _edge_uses(shape):
    """{edge hash: [edge, [face indexes]]}, one index per use (a seam is used twice by its face)."""
    uses = {}
    for i, face in enumerate(shape.Faces):
        for wire in face.Wires:
            for edge in wire.OrderedEdges:
                if not edge.Degenerated:
                    uses.setdefault(edge.hashCode(), [edge, []])[1].append(i)
    return uses


def open_edges(shape):
    """Edges used only once: where the body is open (gaps, or the edge of a surface)."""
    return [e for e, faces in _edge_uses(shape).values() if len(faces) == 1]


def gap_loops(shape):
    """The open edges that are gaps, grouped into connected loops (one per gap). An open edge is
    a gap when its face is joined to other faces, or when another face runs along it (faces not
    sewn together); the edge of a face standing alone is its boundary, not a gap."""
    import Part
    uses = _edge_uses(shape)
    joined = {i for _e, faces in uses.values() if len(faces) > 1 for i in set(faces)}
    free = []
    for edge, faces in uses.values():
        if len(faces) != 1:
            continue
        i = faces[0]
        if i in joined or _beside_other_face(shape, edge, i):
            free.append(edge)
    return Part.sortEdges(free) if free else []


def _beside_other_face(shape, edge, index):
    """True when the middle of the edge lies on another face."""
    import Part
    middle = edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter))
    point = Part.Vertex(middle)
    for j, face in enumerate(shape.Faces):
        if j == index:
            continue
        box = face.BoundBox
        box.enlarge(2 * SEW_TOLERANCE)
        if not box.isInside(middle):
            continue
        try:
            if face.distToShape(point)[0] <= SEW_TOLERANCE:
                return True
        except Exception:
            continue
    return False


def diagnose(shape):
    """{'faces': [(face index, reason)], 'gaps': [[edges]], 'solid': bool}."""
    faces = []
    for i, face in enumerate(shape.Faces):
        reason = face_problem(face)
        if reason:
            faces.append((i, reason))
    return {"faces": faces, "gaps": gap_loops(shape) if shape.Faces else [],
            "solid": bool(shape.Solids) and all(s.isValid() for s in shape.Solids)}


def problems(shape):
    d = diagnose(shape)
    return len(d["faces"]) + len(d["gaps"])


# ---------------------------------------------------------------- healing
def _fixed(shape):
    s = shape.copy()
    try:
        s.fix(TOLERANCE, TOLERANCE, SEW_TOLERANCE)
    except Exception as _fw_err:
        _fw_log("importdiag.py:128", _fw_err)
    return s


def _fuzzy_sewn(faces, fallback):
    """The faces joined where they lie within SEW_TOLERANCE of each other (edges a hair apart, as
    exported by other systems), then sewn; the plain sewing result when that joins no better."""
    import Part
    try:
        joined = faces[0].fuse(list(faces[1:]), SEW_TOLERANCE)
        out = Part.Compound(joined.Faces)
        out.sewShape()
    except Exception as _fw_err:
        _fw_log("importdiag.py:fuzzy", _fw_err)
        return fallback
    closed = lambda sh: sum(1 for x in sh.Shells if x.isClosed())
    free = lambda sh: len(sh.Faces) - sum(len(x.Faces) for x in sh.Shells)
    if (closed(out), -len(out.Shells), -free(out)) > (closed(fallback), -len(fallback.Shells), -free(fallback)):
        return out
    return fallback


def _sewn(faces):
    """The faces sewn into one shell (or several), and made a solid when they close up."""
    import Part
    if not faces:
        return Part.Shape()
    shell = Part.Shell(faces)
    try:
        shell.sewShape(SEW_TOLERANCE)       # FreeCAD 1.1 sews at its own 1e-6 whatever is passed
    except Exception as _fw_err:
        _fw_log("importdiag.py:141", _fw_err)
    if len(faces) > 1 and not (len(shell.Shells) == 1 and shell.Shells[0].isClosed()):
        shell = _fuzzy_sewn(faces, shell)
    shells = shell.Shells or [shell]
    in_shells = {f.hashCode() for sh in shells for f in sh.Faces}
    loose = [f for f in shell.Faces if f.hashCode() not in in_shells]    # sewing leaves these out of the shells
    out = []
    for sh in shells:
        try:
            if sh.isClosed():
                solid = Part.Solid(sh)
                solid.fix(TOLERANCE, TOLERANCE, SEW_TOLERANCE)
                if solid.isValid() and solid.Volume < 0:
                    solid.complement()
                out.append(solid if solid.isValid() else sh)
                continue
        except Exception as _fw_err:
            _fw_log("importdiag.py:156", _fw_err)
        out.append(sh)
    out += loose
    return out[0] if len(out) == 1 else Part.Compound(out)


def _fill(loops, faces):
    """A face for each gap loop: flat where the loop is flat, else a surface through it, else one
    tangent to the faces round it (a missing fillet corner). Loops that cannot be filled stay open."""
    from . import deleteface
    out = []
    for loop in loops:
        for tangent in (False, True):
            try:
                out += deleteface.fill_faces([loop], keep=faces, tangent=tangent)
                break
            except Exception:
                continue
    return out


def _fixed_faces(faces):
    """(faces fixed and valid, faces still faulty after the fix)."""
    good, bad = [], []
    for face in faces:
        fixed = _fixed(face)
        for f in (fixed.Faces if not fixed.isNull() else []):
            if f.Area <= TOLERANCE:
                continue
            (good if face_problem(f) is None else bad).append(f)
    return good, bad


def _with(healed, bad):
    import Part
    return Part.Compound([healed] + bad) if bad else healed


def heal_all(shape):
    """Fixes the faces, sews them, fills the gaps left and makes a solid. A face the fix cannot
    mend stays as it is, beside the rest, for Remove Face. Returns the new shape."""
    good, bad = _fixed_faces(shape.Faces)
    healed = _sewn(good)
    loops = gap_loops(healed)
    if loops:
        filled = _fill(loops, healed.Faces)
        if filled:
            healed = _sewn(list(healed.Faces) + list(filled))
    return _with(healed, bad)


def heal_face(shape, index):
    """Fixes one faulty face and sews the body again."""
    good, bad = _fixed_faces([shape.Faces[index]])
    if bad or not good:
        raise RuntimeError("the face could not be mended; Remove Face takes it out")
    rest = [f for i, f in enumerate(shape.Faces) if i != index]
    return _sewn(rest + good)


def remove_face(shape, index):
    """Takes one face out: the body is left open there (a gap)."""
    faces = [f for i, f in enumerate(shape.Faces) if i != index]
    return _sewn(faces)


def heal_gap(shape, loop):
    """Sews the faces round one gap, or fills it when sewing does not close it."""
    before = len(gap_loops(shape))
    good, bad = _fixed_faces(shape.Faces)
    healed = _sewn(good)
    left = gap_loops(healed)
    if len(left) < before:
        return _with(healed, bad)
    # sewing did not close it: fill the loop nearest the one picked
    middle = sum((e.CenterOfMass for e in loop), App.Vector()) * (1.0 / len(loop))
    nearest = min(left, key=lambda lp: (sum((e.CenterOfMass for e in lp), App.Vector()) * (1.0 / len(lp)) - middle).Length)
    filled = _fill([nearest], healed.Faces)
    if not filled:
        raise RuntimeError("This gap could not be filled")
    return _with(_sewn(list(healed.Faces) + list(filled)), bad)


# ---------------------------------------------------------------- the body
def imported(obj):
    """True for a body with a plain, stored shape (what an import makes)."""
    return obj is not None and obj.TypeId in IMPORTED and hasattr(obj, "Shape") and not obj.Shape.isNull() \
        and bool(obj.Shape.Faces)


def candidates(doc=None):
    doc = doc or App.ActiveDocument
    return [o for o in (doc.Objects if doc else []) if imported(o) and o.Visibility]


def target_from_selection():
    for sel in Gui.Selection.getSelectionEx():
        obj = sel.Object
        if imported(obj):
            return obj
    found = candidates()
    return found[0] if len(found) == 1 else None


def set_shape(obj, shape):
    obj.Shape = shape
    obj.Document.recompute()


# ---------------------------------------------------------------- the PropertyManager
class ImportDiagnosticsPanel:
    ""

    def __init__(self, obj=None):
        self.obj = obj
        self.doc = App.ActiveDocument
        self.original = {}      # body name -> its shape when the page first showed it
        self._keep(obj)
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("SWImportDiagnostics")
        self.form.setWindowTitle("Import Diagnostics")
        lay = QtWidgets.QVBoxLayout(self.form)
        self.message = QtWidgets.QLabel()
        self.message.setObjectName("SWImportMessage")
        self.message.setWordWrap(True)
        lay.addWidget(self.message)
        box = QtWidgets.QGroupBox("Analysis Problems")
        inner = QtWidgets.QVBoxLayout(box)
        self.list = QtWidgets.QTreeWidget()
        self.list.setObjectName("SWImportProblems")
        self.list.setHeaderHidden(True)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.menu)
        self.list.itemSelectionChanged.connect(self.show_picked)
        inner.addWidget(self.list)
        self.heal_all_button = QtWidgets.QPushButton("Attempt to Heal All")
        self.heal_all_button.setObjectName("SWHealAll")
        self.heal_all_button.clicked.connect(self.heal_all)
        inner.addWidget(self.heal_all_button)
        lay.addWidget(box)
        lay.addStretch(1)
        self.refresh()

    def _keep(self, obj):
        if obj is not None and obj.Name not in self.original:
            self.original[obj.Name] = obj.Shape.copy()

    # ---------------- list
    def refresh(self):
        self.list.clear()
        if self.obj is None:
            self.message.setText("Select an imported body." if candidates(self.doc) else
                                 "The part has no imported bodies: Import Diagnostics checks bodies "
                                 "brought in from STEP, IGES and other neutral files.")
            self.heal_all_button.setVisible(False)       # exportopts-1119: hidden, not greyed
            return
        self.found = diagnose(self.obj.Shape)
        faces, gaps = self.found["faces"], self.found["gaps"]
        top_f = QtWidgets.QTreeWidgetItem(["Faulty Faces (%d)" % len(faces)])
        for i, reason in faces:
            item = QtWidgets.QTreeWidgetItem(["Face%d: %s" % (i + 1, reason)])
            item.setData(0, Qt.UserRole, ("face", i))
            top_f.addChild(item)
        top_g = QtWidgets.QTreeWidgetItem(["Gaps Between Faces (%d)" % len(gaps)])
        for k, loop in enumerate(gaps):
            length = sum(e.Length for e in loop)
            item = QtWidgets.QTreeWidgetItem(["Gap%d: %d edge%s, %.3f mm" % (k + 1, len(loop), "" if len(loop) == 1 else "s", length)])
            item.setData(0, Qt.UserRole, ("gap", k))
            top_g.addChild(item)
        self.list.addTopLevelItem(top_f)
        self.list.addTopLevelItem(top_g)
        self.list.expandAll()
        n = len(faces) + len(gaps)
        if n == 0:
            self.message.setText("%s: no faulty faces or gaps were found." % self.obj.Label +
                                 ("" if self.found["solid"] else " It is not a solid."))
        else:
            self.message.setText("%s: %d faulty face%s and %d gap%s were found." % (
                self.obj.Label, len(faces), "" if len(faces) == 1 else "s", len(gaps), "" if len(gaps) == 1 else "s"))
        self.heal_all_button.setVisible(n > 0 or not self.found["solid"])

    def picked_problem(self, item=None):
        item = item or self.list.currentItem()
        return item.data(0, Qt.UserRole) if item is not None else None

    def show_picked(self):
        what = self.picked_problem()
        if what is None or self.obj is None:
            return
        Gui.Selection.clearSelection()
        kind, k = what
        shape = self.obj.Shape
        if kind == "face":
            Gui.Selection.addSelection(self.doc.Name, self.obj.Name, "Face%d" % (k + 1))
            return
        from .deleteface import _same_edge
        for edge in self.found["gaps"][k]:
            for j, e in enumerate(shape.Edges):
                if _same_edge(e, edge):     # sortEdges can hand back rebuilt edges
                    Gui.Selection.addSelection(self.doc.Name, self.obj.Name, "Edge%d" % (j + 1))
                    break

    def menu(self, pos):
        item = self.list.itemAt(pos)
        what = self.picked_problem(item)
        if what is None:
            return
        self.list.setCurrentItem(item)
        m = QtWidgets.QMenu(self.list)
        m.setObjectName("SWImportMenu")
        m.addAction("Attempt to Heal", lambda: self.heal(what))
        if what[0] == "face":
            m.addAction("Remove Face", lambda: self.remove(what[1]))
        m.addAction("Zoom to Selection", lambda: Gui.SendMsgToActiveView("ViewSelection"))
        m.popup(self.list.viewport().mapToGlobal(pos))
        self._menu = m

    # ---------------- healing
    def _apply(self, change, what):
        try:
            shape = change(self.obj.Shape)
        except Exception as error:
            QtWidgets.QMessageBox.warning(self.form, "Import Diagnostics", "%s could not be healed: %s" % (what, error))
            return False
        if shape is None or shape.isNull():
            return False
        Gui.Selection.clearSelection()
        set_shape(self.obj, shape)
        self.refresh()
        return True

    def heal_all(self):
        return self._apply(heal_all, "The body")

    def heal(self, what):
        kind, k = what
        if kind == "face":
            return self._apply(lambda s: heal_face(s, k), "Face%d" % (k + 1))
        loop = self.found["gaps"][k]
        return self._apply(lambda s: heal_gap(s, loop), "Gap%d" % (k + 1))

    def remove(self, index):
        return self._apply(lambda s: remove_face(s, index), "Face%d" % (index + 1))

    # ---------------- picks while the page is open
    def picked(self, obj):
        if obj is not self.obj and imported(obj):
            self.obj = obj
            self._keep(obj)
            self.refresh()

    # ---------------- task panel
    def getStandardButtons(self):
        buttons = QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        try:
            return int(buttons)
        except TypeError:
            return buttons.value     # PySide6 flags

    # The page changes the shapes as it goes, outside the undo history (healing can make and close
    # a scratch document, which ends an open transaction). The check then records the whole change
    # as one Undo step, Import Diagnostics; the cross puts the shapes back.
    def _changed(self):
        out = []
        for name, shape in self.original.items():
            obj = self.doc.getObject(name)
            if obj is not None and not obj.Shape.isEqual(shape):
                out.append((obj, shape))
        return out

    def accept(self):
        changed = self._changed()
        if changed:
            final = [(obj, obj.Shape.copy()) for obj, _shape in changed]
            for obj, shape in changed:
                obj.Shape = shape
            self.doc.openTransaction("Import Diagnostics")
            try:
                for obj, shape in final:
                    obj.Shape = shape
            except BaseException:
                try:
                    self.doc.abortTransaction()
                except Exception:
                    pass
                raise
            self.doc.commitTransaction()
            self.doc.recompute()
        self._close()
        return True

    def reject(self):
        for obj, shape in self._changed():
            obj.Shape = shape
        self.doc.recompute()
        self._close()
        return True

    def _close(self):
        Gui.Control.closeDialog()
        if _open and _open[0] is self:
            try:
                Gui.Selection.removeObserver(_open[1])
            except Exception as _fw_err:
                _fw_log("importdiag.py:453", _fw_err)
            _open[:] = []


class _Watch:
    """Selection observer: a pick of another imported body while the page is open."""

    def __init__(self, panel):
        self.panel = panel

    def addSelection(self, doc, obj, sub, pnt):
        try:
            if Gui.Control.activeDialog() and _open and _open[0] is self.panel:
                self.panel.picked(App.getDocument(doc).getObject(obj))
        except Exception as _fw_err:
            _fw_log("importdiag.py:468", _fw_err)


_open = []


def run(obj=None):
    if App.ActiveDocument is None or Gui.Control.activeDialog():
        return None
    obj = obj or target_from_selection()
    if obj is not None and not imported(obj):
        obj = None
    panel = ImportDiagnosticsPanel(obj)
    if _open:
        try:
            Gui.Selection.removeObserver(_open[1])
        except Exception as _fw_err:
            _fw_log("importdiag.py:485", _fw_err)
    watch = _Watch(panel)
    _open[:] = [panel, watch]
    Gui.Selection.addObserver(watch)
    Gui.Control.showDialog(panel)
    return panel


class _Cmd:
    def GetResources(self):
        return {"MenuText": "Import Diagnostics...",
                "ToolTip": "Finds faulty faces and gaps in an imported body and heals them.",
                "Pixmap": "Part_CheckGeometry", "CmdType": "ForEdit"}

    def Activated(self):
        run()

    def IsActive(self):

        return App.ActiveDocument is not None and not Gui.Control.activeDialog()


def install():
    if Gui.Command.get(COMMAND) is None:
        Gui.addCommand(COMMAND, _Cmd())
