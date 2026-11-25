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

from . import pickguard
from . import parttools

ACTIVE = "QListWidget { border: 2px solid #3399ff; }"
IDLE = ""


def _normal(obj, sub):
    if obj.isDerivedFrom("App::Plane") or obj.TypeId in ("PartDesign::Plane",):
        return obj.Placement.Rotation.multVec(App.Vector(0, 0, 1))
    if sub.startswith("Face"):
        f = obj.Shape.getElement(sub)
        if isinstance(f.Surface, Part.Plane):
            return f.normalAt(0, 0)
    return None


def tangent_chain(obj, subs):
    """The picked edges plus every edge joined to them tangentially (Propagate to tangent faces)."""
    shape = obj.Shape
    edges = list(shape.Edges)
    picked = [int(s[4:]) - 1 for s in subs if s.startswith("Edge")]
    done = set(picked)
    todo = list(picked)
    while todo:
        i = todo.pop()
        e = edges[i]
        for v in e.Vertexes:
            for j, f in enumerate(edges):
                if j in done:
                    continue
                w = next((w for w in f.Vertexes if w.isSame(v)), None)
                if w is None:
                    continue
                try:
                    t1 = e.tangentAt(e.parameterAt(v))
                    t2 = f.tangentAt(f.parameterAt(w))
                except Exception as _fw_err:
                    _fw_log("radiatepm.py:64", _fw_err)
                    continue
                if abs(abs(t1.normalize().dot(t2.normalize())) - 1.0) < 1e-4:
                    done.add(j)
                    todo.append(j)
    return ["Edge%d" % (i + 1) for i in sorted(done)]


class RadiatePanel:
    def __init__(self, obj, new):
        self.obj, self.new = obj, new
        if "Reference" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLinkSubList", "Reference", "Radiate Surface",
                            "Radiate direction reference: the plane the surface runs parallel to")
        if "Propagate" not in obj.PropertiesList:
            obj.addProperty("App::PropertyBool", "Propagate", "Radiate Surface", "Propagate to tangent faces")
        self.picked = [(o, list(s)) for o, s in obj.Edges]
        w = QtWidgets.QWidget()
        w.setWindowTitle("Radiate Parameters")
        w.setProperty("swstyle_pm_title", "Radiate Surface")
        w.setObjectName("SWRadiatePM")
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(QtWidgets.QLabel("Radiate direction reference:"))
        self.ref = QtWidgets.QListWidget()
        self.ref.setObjectName("SWRadiateReference")
        self.ref.setMaximumHeight(26)
        lay.addWidget(self.ref)
        self.reverse = QtWidgets.QCheckBox("Reverse direction")
        self.reverse.setObjectName("SWRadiateReverse")
        self.reverse.setChecked(bool(obj.Flip))
        self.reverse.toggled.connect(self._changed)
        lay.addWidget(self.reverse)
        lay.addWidget(QtWidgets.QLabel("Edges to radiate:"))
        self.edges = QtWidgets.QListWidget()
        self.edges.setObjectName("SWRadiateEdges")
        self.edges.setMaximumHeight(80)
        lay.addWidget(self.edges)
        self.propagate = QtWidgets.QCheckBox("Propagate to tangent faces")
        self.propagate.setObjectName("SWRadiatePropagate")
        self.propagate.setChecked(bool(obj.Propagate))
        self.propagate.toggled.connect(self._changed)
        lay.addWidget(self.propagate)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Radiate distance:"))
        self.distance = QtWidgets.QDoubleSpinBox()
        self.distance.setObjectName("SWRadiateDistance")
        self.distance.setRange(0.001, 1e6)
        self.distance.setDecimals(3)
        self.distance.setSuffix(" mm")
        self.distance.setValue(obj.Distance.Value)
        self.distance.setKeyboardTracking(False)
        self.distance.valueChanged.connect(self._changed)
        row.addWidget(self.distance, 1)
        lay.addLayout(row)
        self.note = QtWidgets.QLabel("")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        for lst, key in ((self.ref, "ref"), (self.edges, "edges")):
            lst.installEventFilter(self._focus(key))

        # Clear Selections) through pmboxes, as every other page
        try:
            from . import pmboxes
            pmboxes.bind(self.ref, lambda row: self._drop_ref(), self._drop_ref)
            pmboxes.bind(self.edges, self._drop_edge, self._drop_edges)
        except Exception as _fw_err:
            _fw_log("radiatepm.py:surflook", _fw_err)
        self.form = w
        self.active = "edges" if obj.Reference else "ref"
        self._fill()
        Gui.Selection.addObserver(self)

    def _focus(self, key):
        panel = self

        class F(QtCore.QObject):
            def eventFilter(self, watched, event):
                if not isinstance(event, QtCore.QEvent):
                    return False
                if event.type() == QtCore.QEvent.FocusIn:
                    panel.active = key
                    panel._fill()
                return False
        f = F(self.form if hasattr(self, "form") else None)
        self._filters = getattr(self, "_filters", []) + [f]
        return f

    def _fill(self):
        self.ref.clear()
        for o, subs in self.obj.Reference:
            self.ref.addItem("%s %s" % (o.Label, ",".join(subs)) if subs and subs[0] else o.Label)
        self.edges.clear()
        for o, subs in self.obj.Edges:
            for sub in subs:
                self.edges.addItem("%s@%s" % (sub, o.Label))
        try:
            from . import pmboxes       # look-audit surflook-1120
            pmboxes.mark(self.ref, self.active == "ref")
            pmboxes.mark(self.edges, self.active == "edges")
        except Exception as _fw_err:
            _fw_log("radiatepm.py:surflook-mark", _fw_err)
            self.ref.setStyleSheet(ACTIVE if self.active == "ref" else IDLE)
            self.edges.setStyleSheet(ACTIVE if self.active == "edges" else IDLE)

    def _drop_ref(self):
        self.obj.Reference = []
        self.active = "ref"
        self._changed()

    def _drop_edge(self, row):
        shown = [(o, sub) for o, subs in self.obj.Edges for sub in subs]
        if 0 <= row < len(shown):
            o, sub = shown[row]
            self.picked = [(p, [x for x in subs if not (p == o and x == sub)]) for p, subs in self.picked]
            self.picked = [(p, subs) for p, subs in self.picked if subs]
            self._changed()

    def _drop_edges(self):
        self.picked = []
        self._changed()

    # ---- picks
    def pick(self, obj, sub):
        if self.active == "ref":
            n = _normal(obj, sub or "")
            if n is None:
                self.note.setText("The direction reference must be a plane or a planar face.")
                return False
            self.obj.Reference = [(obj, [sub] if sub else [""])]
            self.active = "edges"
        else:
            if not sub.startswith("Edge"):
                return False
            for o, subs in self.picked:
                if o == obj:
                    if sub in subs:
                        subs.remove(sub)        # a second click takes it out
                    else:
                        subs.append(sub)
                    break
            else:
                self.picked.append((obj, [sub]))
            self.picked = [(o, s) for o, s in self.picked if s]
        self.note.setText("")
        self._changed()
        return True

    def addSelection(self, doc, name, sub, point):
        if pickguard.stale(self, self.obj):
            return
        obj = App.getDocument(doc).getObject(name)
        if obj is None or obj == self.obj:
            return
        if "." in sub:
            parts = sub.split(".")
            obj = obj.getSubObject(".".join(parts[:-1]) + ".", retType=1) or obj
            sub = parts[-1]
        QtCore.QTimer.singleShot(0, lambda: (self.pick(obj, sub), Gui.Selection.clearSelection()))

    def _changed(self, *args):
        o = self.obj
        o.Flip = self.reverse.isChecked()
        o.Propagate = self.propagate.isChecked()
        o.Distance = self.distance.value()
        if o.Reference:
            src, subs = o.Reference[0]
            n = _normal(src, subs[0] if subs else "")
            if n is not None:
                o.Normal = n
        edges = []
        for src, subs in self.picked:
            edges.append((src, tangent_chain(src, subs) if o.Propagate else list(subs)))
        o.Edges = edges
        o.Document.recompute()
        bad = "Invalid" in o.State
        self.note.setText(o.getStatusString() if bad else "")
        self._fill()

    # ---- OK / Cancel
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("radiatepm.py:217", _fw_err)
        Gui.Control.closeDialog()

    def accept(self):
        self._changed()
        if self.obj.Shape.isNull():
            self.note.setText("Pick the edges to radiate.")
            return False
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc, name = self.obj.Document, self.obj.Name
        self._close()
        doc.abortTransaction()
        if self.new and doc.getObject(name) is not None:
            doc.removeObject(name)
        doc.recompute()
        return True


def radiate_surface(distance=10.0):
    """The command: the PropertyManager with what was picked before it (pick first or tool first)."""
    doc = App.ActiveDocument
    if doc is None:
        return None
    sel = Gui.Selection.getSelectionEx()
    doc.openTransaction("Radiate Surface")
    try:
        obj = doc.addObject("Part::FeaturePython", "RadiateSurface")
        parttools.RadiateSurface(obj)
        if App.GuiUp:
            obj.ViewObject.Proxy = 0
        obj.Label = "Radiate Surface"
        obj.Distance = distance
        panel = RadiatePanel(obj, True)
        for s in sel:
            for sub in s.SubElementNames or [""]:
                if sub.startswith("Edge"):
                    panel.active = "edges"
                    panel.pick(s.Object, sub)
        for s in sel:
            for sub in s.SubElementNames or [""]:
                if not sub.startswith("Edge") and _normal(s.Object, sub) is not None and not obj.Reference:
                    panel.active = "ref"
                    panel.pick(s.Object, sub)
        if not obj.Reference and obj.Edges:
            obj.Normal = parttools._plane_normal([(s.Object, list(s.SubElementNames)) for s in sel])
            doc.recompute()
        panel.active = "ref" if not obj.Reference and not obj.Edges else "edges"
        panel._fill()
        Gui.Selection.clearSelection()
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    return panel


def install():
    if "SWStyle_RadiateSurface" in parttools.COMMANDS:
        m, t, _f, ok = parttools.COMMANDS["SWStyle_RadiateSurface"]
        parttools.COMMANDS["SWStyle_RadiateSurface"] = (m, t, radiate_surface, ok)
