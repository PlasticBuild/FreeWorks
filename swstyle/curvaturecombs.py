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

V = App.Vector
TITLE = "Surface Curvature Combs"
INK = (0.55, 0.1, 0.75)


def _curves(face, direction, count):
    """[curve] across the face: iso curves at evenly spread parameters (trimmed to the face)."""
    u0, u1, v0, v1 = face.ParameterRange
    s = face.Surface
    out = []
    for i in range(count):
        f = (i + 0.5) / count
        if direction in ("U", "Both"):           # curves running along U: v held
            out.append(("U", v0 + f * (v1 - v0)))
        if direction in ("V", "Both"):
            out.append(("V", u0 + f * (u1 - u0)))
    curves = []
    for kind, at in out:
        try:
            c = s.vIso(at) if kind == "U" else s.uIso(at)
        except Exception:
            continue
        lo, hi = (u0, u1) if kind == "U" else (v0, v1)
        curves.append((kind, at, c, lo, hi))
    return curves


def combs(face, direction="Both", count=5, points=40, scale=1.0):
    """[(base points, tip points)] per curve, in global coordinates, for the face."""
    raw = []
    kmax = 0.0
    for kind, at, curve, lo, hi in _curves(face, direction, count):
        row = []
        for j in range(points + 1):
            t = lo + (hi - lo) * j / points
            u, v = (t, at) if kind == "U" else (at, t)
            try:
                if not face.isPartOfDomain(u, v):
                    row.append(None)
                    continue
                p = curve.value(t)
                k = curve.curvature(t)
            except Exception:
                row.append(None)
                continue
            if k > 1e-9:
                n = curve.normal(t)          # towards the centre of bending
                tooth = n * -1
            else:
                tooth = V(0, 0, 0)
                k = 0.0
            kmax = max(kmax, k)
            row.append((p, tooth, k))
        raw.append(row)
    size = face.BoundBox.DiagonalLength
    factor = (0.25 * size / kmax * scale) if kmax > 1e-9 else 0.0
    out = []
    for row in raw:
        bases, tips = [], []
        for item in row:
            if item is None:
                if len(bases) > 1:
                    out.append((bases, tips))
                bases, tips = [], []
                continue
            p, tooth, k = item
            bases.append(p)
            tips.append(p + tooth * (k * factor))
        if len(bases) > 1:
            out.append((bases, tips))
    return out


class _Shown:
    """The combs on screen: (object name, face name, settings), remade after each recompute."""

    def __init__(self):
        self.items = []
        self.nodes = []
        self.observer = None

    def add(self, doc, picks, settings):
        self.items += [(doc.Name, o.Name, sub, settings) for o, sub in picks]
        self.draw()
        if self.observer is None:
            self.observer = _Recompute(self)
            App.addDocumentObserver(self.observer)

    def remove_last(self, n):
        if n:
            self.items = self.items[:-n]
        self.draw()

    def clear(self):
        self.items = []
        self.draw()

    def draw(self):
        from pivy import coin
        for view, node in self.nodes:
            try:
                view.getSceneGraph().removeChild(node)
            except Exception as _fw_err:
                _fw_log("curvaturecombs.py:131", _fw_err)
        self.nodes = []
        keep = []
        by_view = {}
        for item in self.items:
            dname, oname, sub, settings = item
            try:
                doc = App.getDocument(dname)
                obj = doc.getObject(oname)
                face = obj.Shape.getElement(sub)
                view = Gui.getDocument(dname).ActiveView
            except Exception as _fw_err:
                _fw_log("curvaturecombs.py:144", _fw_err)
                continue
            keep.append(item)
            by_view.setdefault(id(view), (view, []))[1].append((face, settings))
        self.items = keep
        for view, faces in by_view.values():
            root = coin.SoSeparator()
            pick = coin.SoPickStyle()
            pick.style = coin.SoPickStyle.UNPICKABLE
            light = coin.SoLightModel()
            light.model = coin.SoLightModel.BASE_COLOR
            colour = coin.SoBaseColor()
            colour.rgb.setValue(*INK)
            style = coin.SoDrawStyle()
            style.lineWidth.setValue(1.5)
            for n in (pick, light, colour, style):
                root.addChild(n)
            for face, settings in faces:
                for bases, tips in combs(face, *settings):
                    pts, counts = [], []
                    for b, t in zip(bases, tips):
                        if (t - b).Length > 1e-9:
                            pts += [b, t]
                            counts.append(2)
                    pts += tips
                    counts.append(len(tips))
                    c = coin.SoCoordinate3()
                    c.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
                    ls = coin.SoLineSet()
                    ls.numVertices.setValues(0, len(counts), counts)
                    sep = coin.SoSeparator()
                    sep.addChild(c)
                    sep.addChild(ls)
                    root.addChild(sep)
            view.getSceneGraph().addChild(root)
            self.nodes.append((view, root))


class _Recompute:
    def __init__(self, shown):
        self.shown = shown

    def slotRecomputedDocument(self, doc):
        if any(item[0] == doc.Name for item in self.shown.items):
            QtCore.QTimer.singleShot(0, self.shown.draw)

    def slotDeletedDocument(self, doc):
        QtCore.QTimer.singleShot(0, self.shown.draw)


SHOWN = _Shown()


def _picks():
    out = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        doc = sel.Object.Document
        for sub in sel.SubElementNames:
            path = sub.split(".")
            holder = sel.Object
            for part in path[:-1]:
                found = doc.getObject(part)
                if found is not None:
                    holder = found
            if holder.TypeId == "PartDesign::Body":
                holder = holder.Tip
            if path[-1].startswith("Face"):
                out.append((holder, path[-1]))
    return out


class CombPanel:
    def __init__(self, doc, picks):
        self.doc, self.picks = doc, picks
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(TITLE)
        self.form.setProperty("swstyle_pm_title", TITLE)
        lay = QtWidgets.QFormLayout(self.form)
        self.faces = QtWidgets.QLabel("%d face(s)" % len(picks) if picks else "Pick faces first.")
        self.faces.setObjectName("SWCombFaces")
        lay.addRow("Faces", self.faces)
        self.direction = QtWidgets.QComboBox()
        self.direction.setObjectName("SWCombDirection")
        self.direction.addItems(["Both", "U", "V"])
        lay.addRow("Direction", self.direction)
        self.count = QtWidgets.QSpinBox()
        self.count.setObjectName("SWCombCount")
        self.count.setRange(1, 100)
        self.count.setValue(5)
        lay.addRow("Number of curves", self.count)
        self.points = QtWidgets.QSpinBox()
        self.points.setObjectName("SWCombPoints")
        self.points.setRange(4, 500)
        self.points.setValue(40)
        lay.addRow("Points per curve", self.points)
        self.scale = QtWidgets.QDoubleSpinBox()
        self.scale.setObjectName("SWCombScale")
        self.scale.setRange(0.01, 100)
        self.scale.setValue(1.0)
        lay.addRow("Scale", self.scale)
        self.added = 0
        for w in (self.direction, self.count, self.points, self.scale):
            sig = w.currentIndexChanged if isinstance(w, QtWidgets.QComboBox) else w.valueChanged
            sig.connect(self.preview)
        self.preview()
        Gui.Selection.addObserver(self)

    def _remove_observer(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("curvaturecombs.py:253", _fw_err)

    def _selection_open(self):
        try:
            from .widgets import alive
            return bool(Gui.Control.activeDialog() and alive(self.form) and _in_tasks(self.form))
        except Exception:
            return False

    def addSelection(self, doc, name, sub, point):
        # Esc or an external close can leave the selection observer registered.
        if not self._selection_open():
            self._remove_observer()
            return
        if sub.startswith("Face"):
            QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub))

    def _picked(self, doc_name, name, sub):
        if not self._selection_open():
            self._remove_observer()
            return
        try:
            if doc_name != self.doc.Name:
                return
            doc = App.getDocument(doc_name)
            picked = doc.getObject(name)
            if picked is None:
                return
            path = sub.split(".")
            for part in path[:-1]:
                found = doc.getObject(part)
                if found is not None:
                    picked = found
            if picked.TypeId == "PartDesign::Body":
                picked = picked.Tip
            face_name = path[-1]
            if (picked is None or not face_name.startswith("Face")
                    or picked.Shape.getElement(face_name).ShapeType != "Face"):
                return
        except Exception:
            return
        pick = (picked, face_name)
        if pick in self.picks:
            return
        self.picks.append(pick)
        self.faces.setText("%d face(s)" % len(self.picks))
        self.preview()

    def settings(self):
        return (self.direction.currentText(), self.count.value(), self.points.value(), self.scale.value())

    def preview(self, *args):
        SHOWN.remove_last(self.added)
        self.added = len(self.picks)
        if self.picks:
            SHOWN.add(self.doc, self.picks, self.settings())

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        self._remove_observer()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._remove_observer()
        SHOWN.remove_last(self.added)
        Gui.Control.closeDialog()
        return True


class _Show:
    def GetResources(self):
        return {"Pixmap": "Sketcher_BSplineComb", "MenuText": TITLE,
                "ToolTip": "Shows curvature combs across the picked faces"}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        doc = App.ActiveDocument
        picks = _picks()
        QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(CombPanel(doc, picks)))


class _Hide:
    def GetResources(self):
        return {"Pixmap": "Sketcher_BSplineComb", "MenuText": "Hide Curvature Combs",
                "ToolTip": "Takes all the surface curvature combs away"}

    def IsActive(self):
        return App.ActiveDocument is not None      # a42: never a grey button; says so when none are shown

    def Activated(self):
        had = bool(SHOWN.items)
        SHOWN.clear()
        try:
            Gui.getMainWindow().statusBar().showMessage(
                "Curvature combs hidden" if had else "No surface curvature combs are shown", 5000)
        except Exception as _fw_err:
            _fw_log("curvaturecombs.py:354", _fw_err)


def register():
    if "SWStyle_SurfaceCurvatureCombs" not in Gui.listCommands():
        Gui.addCommand("SWStyle_SurfaceCurvatureCombs", _Show())
    if "SWStyle_HideCurvatureCombs" not in Gui.listCommands():
        Gui.addCommand("SWStyle_HideCurvatureCombs", _Hide())


def _in_tasks(w):
    """The form still sits in FreeCAD's task view: shown, or hidden behind the FeatureManager tab."""
    try:
        p = w
        while p is not None:
            if p.metaObject().className() in ("Gui::TaskView::TaskView", "Gui::TaskView::TaskBox"):
                return True
            p = p.parentWidget()
    except (RuntimeError, AttributeError):
        return False
    return False
