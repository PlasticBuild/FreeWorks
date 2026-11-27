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

from . import filletpm
from . import surfacefillet

PARAM = "SurfaceFilletFullPM"


def enabled():
    try:
        return App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks").GetBool(PARAM, True)
    except Exception:
        return True


class _Holder:
    """Stands in for the PartDesign body the Fillet page works in: its Tip is the surface body."""

    def __init__(self, doc, base):
        self.Document = doc
        self.Tip = base
        self.Group = []
        self.Name = base.Name if base is not None else ""
        self.Label = base.Label if base is not None else ""

    def removeObject(self, obj):
        return []

    def isDerivedFrom(self, type_name):
        return False


class SurfaceFilletPanel(filletpm.FilletPanel):
    """filletpm's Fillet page on a surface body."""

    UNDO = "Fillet"

    def __init__(self, doc, base, picks=(), feature=None):
        self.surface_mode = True
        holder = _Holder(doc, base)
        filletpm.FilletPanel.__init__(self, doc, holder, picks=picks, feature=feature)
        self.variable = False
        self.vradii = {}            # vertex key -> its radius (Variable Size)
        self._surface_page()
        self._edit_radii(feature)
        self._edit_variable(feature)

    # --- Variable Size: radii at the vertices of the picked edges
    @staticmethod
    def _key(p):
        return (round(p.x, 6), round(p.y, 6), round(p.z, 6))

    def _edge_names(self):
        """The picked items as the surface's edges (a face gives its edges, "" every edge)."""
        edges = []
        shape = self.base.Shape if self.base is not None else None
        for sub in self.items:
            if not sub and shape is not None:
                names = ["Edge%d" % i for i in range(1, len(shape.Edges) + 1)]
            elif sub.startswith("Face") and shape is not None:
                names = ["Edge%d" % i for e in shape.getElement(sub).Edges
                         for i, own in enumerate(shape.Edges, 1) if own.isSame(e)]
            else:
                names = [sub] if sub else []
            for n in names:
                if n not in edges:
                    edges.append(n)
        return edges

    def _ends(self, name):
        e = self.base.Shape.getElement(name)
        return e.valueAt(e.FirstParameter), e.valueAt(e.LastParameter)

    def _vertices(self):
        out = []
        for n in self._edge_names():
            try:
                for p in self._ends(n):
                    k = self._key(p)
                    if k not in out:
                        out.append(k)
            except Exception as _fw_err:
                _fw_log("surfacefilletpm.py:vertices", _fw_err)
        return out

    def _var_fill(self):
        lst = getattr(self, "var_list", None)
        if lst is None:
            return
        keys = self._vertices()
        r0 = float(self.radius.value())
        for k in keys:
            self.vradii.setdefault(k, r0)
        texts = ["V%d   R %.2f" % (i + 1, self.vradii[k]) for i, k in enumerate(keys)]
        if [lst.item(i).text() for i in range(lst.count())] == texts:
            return
        chosen = [i.row() for i in lst.selectedIndexes()]
        lst.blockSignals(True)
        lst.clear()
        lst.addItems(texts)
        for r in chosen:
            if r < lst.count():
                lst.item(r).setSelected(True)
        lst.blockSignals(False)
        self._var_keys = keys

    def _var_picked(self):
        rows = sorted(i.row() for i in self.var_list.selectedIndexes())
        keys = getattr(self, "_var_keys", [])
        if rows and rows[0] < len(keys):
            self.radius.blockSignals(True)
            self.radius.setValue(self.vradii.get(keys[rows[0]], self.radius.value()))
            self.radius.blockSignals(False)

    def _set_variable(self, on):
        self.variable = bool(on)
        buttons = getattr(self, "type_buttons", [])
        for i, b in enumerate(buttons):
            if i in (0, 1):
                b.setChecked((i == 1) == self.variable)
        if self.variable and self.multi_box.isChecked():
            self.multi_box.setChecked(False)
        self.multi_box.setVisible(not self.variable)
        for w in (getattr(self, "var_list", None), getattr(self, "var_title", None)):
            if w is not None:
                w.setVisible(self.variable)
        self._var_fill()
        self.update()

    def _edit_variable(self, feature):
        """Editing a Variable Size Surface-Fillet: Variable Size chosen and each vertex's radius back."""
        try:
            if feature is None or getattr(feature, "FilletType", "") != "Variable Size":
                return
            ends = list(getattr(feature, "EdgeEnds", None) or [])
            names = self._edge_names()
            if len(ends) == 2 * len(names):
                for k, n in enumerate(names):
                    a, b = self._ends(n)
                    self.vradii[self._key(a)] = float(ends[2 * k])
                    self.vradii[self._key(b)] = float(ends[2 * k + 1])
            self._set_variable(True)
        except Exception as _fw_err:
            _fw_log("surfacefilletpm.py:edit-variable", _fw_err)

    def _radius_changed(self, value):
        if getattr(self, "variable", False):
            rows = sorted(i.row() for i in self.var_list.selectedIndexes())
            keys = getattr(self, "_var_keys", [])
            for r in rows:
                if r < len(keys):
                    self.vradii[keys[r]] = float(value)     # R is the highlighted vertices' radius
            self._var_fill()
            self.update()
            return
        filletpm.FilletPanel._radius_changed(self, value)

    def _edit_radii(self, feature):
        """Editing a Multi Radius Surface-Fillet: the box ticked and each edge's own radius back."""
        try:
            radii = list(getattr(feature, "EdgeRadii", None) or []) if feature is not None else []
            subs = list(feature.Edges[0][1]) if radii and feature.Edges else []
            if radii and len(radii) == len(subs):
                for sub, r in zip(subs, radii):
                    self.radii[sub] = float(r)
                self.multi_box.setChecked(True)
        except Exception as _fw_err:
            _fw_log("surfacefilletpm.py:edit-radii", _fw_err)

    # --- the page: what the surface fillet makes, nothing dead
    def _surface_page(self):
        def gone(w):
            try:
                if w is not None:
                    w.setVisible(False)
                    w.setProperty("swstyle_surface_off", True)
            except Exception as _fw_err:
                _fw_log("surfacefilletpm.py:hide", _fw_err)
        tabs = getattr(self, "tabs", None)
        if tabs is not None:
            try:
                tabs.setTabVisible(1, False)        # FilletXpert works on solid bodies
            except Exception:
                tabs.setTabEnabled(1, False)
        for i, b in enumerate(getattr(self, "type_buttons", [])):
            if i == 3 and not b.property("swstyle_surface_type"):
                # Full Round: the surface Full Round page (three face sets)
                b.setProperty("swstyle_surface_type", True)
                try:
                    b.clicked.disconnect()
                except Exception as _fw_err:
                    _fw_log("surfacefilletpm.py:fr-disconnect", _fw_err)
                b.clicked.connect(lambda checked=False: self._full_round())
            elif i in (0, 1) and not b.property("swstyle_surface_type"):
                # Constant Size and Variable Size are made on this page
                b.setProperty("swstyle_surface_type", True)
                try:
                    b.clicked.disconnect()
                except Exception as _fw_err:
                    _fw_log("surfacefilletpm.py:type-disconnect", _fw_err)
                b.clicked.connect(lambda checked=False, v=(i == 1): self._set_variable(v))
        if getattr(self, "var_list", None) is None:
            group = self.radius.parentWidget()
            lay = group.layout() if group is not None else None
            if lay is not None:
                self.var_title = QtWidgets.QLabel("Variable Radius Parameters", group)
                self.var_title.setObjectName("SWSurfVarTitle")
                font = self.var_title.font()
                font.setBold(True)
                self.var_title.setFont(font)
                self.var_list = QtWidgets.QListWidget(group)
                self.var_list.setObjectName("SWSurfVarPoints")
                self.var_list.setToolTip("Vertices of the picked edges: click one (Ctrl for more) and type its R")
                self.var_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
                self.var_list.setMaximumHeight(90)
                self.var_list.itemSelectionChanged.connect(self._var_picked)
                lay.insertWidget(0, self.var_list) if hasattr(lay, "insertWidget") else lay.addWidget(self.var_list)
                lay.insertWidget(0, self.var_title) if hasattr(lay, "insertWidget") else lay.addWidget(self.var_title)
                self.var_title.setVisible(getattr(self, "variable", False))
                self.var_list.setVisible(getattr(self, "variable", False))
        for w in (self.symmetric, self.fd1, self.fd2, self.fd1_label, self.fd2_label, self.reverse,
                  self.profile, self.rho, self.conic_radius, self.rho_label, self.conic_label,
                  self.tangent, getattr(self, "keep", None), getattr(self, "round", None)):
            gone(w)
        for b in getattr(self, "overflow_buttons", []):
            gone(b)
        for box in self.form:
            for lab in box.findChildren(QtWidgets.QLabel):
                if lab.text() in ("Profile:", "Overflow type:"):
                    gone(lab)
            title = box.windowTitle() if hasattr(box, "windowTitle") else ""
            if title in ("Setback Parameters", "Partial Edge Parameters", "Feature Type"):
                gone(box)
        # whole groups go off the page (a hidden group would leave its title bar in the task pane)
        self.form = [w for w in self.form if not w.property("swstyle_surface_off")]
        self.manual = [w for w in self.manual if not w.property("swstyle_surface_off")]

    def _tab(self, index):
        filletpm.FilletPanel._tab(self, index)
        if getattr(self, "surface_mode", False):
            from . import safe_later as _sl; _sl.later(0, self._surface_page, self, "var_list")


    def _wanted(self):
        return None

    def try_passes(self, f):
        return False

    @staticmethod
    def _module_of(f):
        return None

    def conic(self):
        return False

    def asymmetric(self):
        return False

    def multi_radius(self):
        return self.multi_box.isChecked() and not getattr(self, "variable", False)

    def stops_at_tangent(self):
        return False

    def overflow_needed(self):
        return False

    def setback_rows(self):
        return None

    def rolls_over(self):
        return False

    def rounds_corners(self):
        return False

    def keeps_over(self):
        return False

    def partial_on(self, one_edge=True):
        return False

    def _base_crossing(self):
        return False

    # --- picks: edges of one surface body (the first picked one)
    def _add(self, obj, sub):
        try:
            from . import refplane
            obj, sub = refplane.resolve(obj, sub or "")
        except Exception as _fw_err:
            _fw_log("surfacefilletpm.py:resolve", _fw_err)
        if obj is None or not surfacefillet._is_surface(obj):
            return False
        if self.base is None:
            self.base = obj
            self.body.Tip = obj
        if obj is not self.base:
            return False
        if not sub:
            if "" in self.items:
                self.items.remove("")
            else:
                self.items = [""]
            return True
        if sub.startswith("Face"):
            # a face: its edges, as the solid page takes a face's edges
            name = sub
        elif sub.startswith("Edge"):
            name = sub
        else:
            return False
        if "" in self.items:
            self.items.remove("")
        if name in self.items:
            self.items.remove(name)
        else:
            self.items.append(name)
            if self.multi_radius():
                self.radii[name] = self.radius.value()      # a new item takes the R shown
                self._row = None
        if getattr(self, "variable", False):
            QtCore.QTimer.singleShot(0, self._var_fill)
        return True

    # --- the feature: a Surface-Fillet
    def _make(self):
        if self.feature is None:
            doc = self.doc
            obj = doc.addObject("Part::FeaturePython", "SurfaceFillet")
            surfacefillet.SurfaceFillet(obj)
            if obj.ViewObject is not None:
                surfacefillet.View(obj.ViewObject)
            try:
                from . import naming
                obj.Label = naming.next_label(doc, surfacefillet.LABEL)
            except Exception as _fw_err:
                _fw_log("surfacefilletpm.py:label", _fw_err)
            _base_props(obj)
            self.feature = obj
        return self.feature

    def _drop(self):
        if self.feature is not None and self.edit is None:
            name = self.feature.Name
            self.feature = None
            try:
                self.doc.removeObject(name)
            except Exception as _fw_err:
                _fw_log("surfacefilletpm.py:drop", _fw_err)

    def apply(self, f):
        f.FilletType = "Constant Size"
        f.Radius = self.radius.value()
        edges, radii = [], []
        r0 = float(self.radius.value())
        multi = self.multi_radius()
        shape = self.base.Shape if self.base is not None else None

        def take(name, r):
            if name not in edges:
                edges.append(name)
                radii.append(r)
        for sub in self.items:
            r = float(self.radii.get(sub, r0)) if multi else r0
            if not sub and shape is not None:
                for i in range(1, len(shape.Edges) + 1):
                    take("Edge%d" % i, r)
            elif sub.startswith("Face") and shape is not None:
                face = shape.getElement(sub)
                for e in face.Edges:
                    for i, own in enumerate(shape.Edges, 1):
                        if own.isSame(e):
                            take("Edge%d" % i, r)
            elif sub:
                take(sub, r)
        surfacefillet._radii_prop(f)
        f.EdgeRadii = radii if multi and edges else []
        if getattr(self, "variable", False) and shape is not None:
            ends = []
            for n in edges:
                a, b = self._ends(n)
                ends += [float(self.vradii.get(self._key(a), r0)), float(self.vradii.get(self._key(b), r0))]
            f.EdgeEnds = ends
            f.FilletType = "Variable Size"
        else:
            f.EdgeEnds = []
        f.Edges = [(self.base, edges)] if edges else []

    def unchanged(self, f):
        return False

    # --- shown and hidden
    def _show_base(self):
        try:
            if self.base is not None:
                self.base.ViewObject.Visibility = True
            if self.feature is not None:
                self.feature.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("surfacefilletpm.py:show", _fw_err)

    def _restore(self):
        try:
            done = self.feature is not None and self.ok and not self.closing_cancel
            if done:
                self.feature.ViewObject.Visibility = True
                if self.base is not None:
                    self.base.ViewObject.Visibility = False
            elif self.base is not None:
                self.base.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("surfacefilletpm.py:restore", _fw_err)

    closing_cancel = False

    def reject(self):
        self.closing_cancel = True
        return filletpm.FilletPanel.reject(self)

    def _full_round(self):
        doc, base = self.doc, self.base
        self.reject()
        QtCore.QTimer.singleShot(150, lambda: open_full_round(doc, base))

    def switch(self, command):
        """Face Fillet: the surface Face Fillet page, with the picked surface."""
        self.reject()
        if command != "SWStyle_FaceFillet":
            return

        doc = self.doc

        def start():
            # surfacefillet.make with Face Fillet chosen: its page opens on Face set 1 / Face set 2
            doc.openTransaction(surfacefillet.TITLE)
            obj = doc.addObject("Part::FeaturePython", "SurfaceFillet")
            surfacefillet.SurfaceFillet(obj)
            if obj.ViewObject is not None:
                surfacefillet.View(obj.ViewObject)
            try:
                from . import naming
                obj.Label = naming.next_label(doc, surfacefillet.LABEL)
            except Exception as _fw_err:
                _fw_log("surfacefilletpm.py:face-label", _fw_err)
            obj.FilletType = "Face Fillet"
            doc.recompute()
            Gui.Selection.clearSelection()
            Gui.ActiveDocument.setEdit(obj.Name)
        QtCore.QTimer.singleShot(150, start)


def _base_props(obj):
    """The Fillet page sets Base and UseAllEdges on the feature it builds: the surface fillet keeps
    them hidden (its Edges hold the picks)."""
    for kind, name in (("App::PropertyLinkSub", "Base"), ("App::PropertyBool", "UseAllEdges")):
        if name not in obj.PropertiesList:
            obj.addProperty(kind, name, "Fillet", "Used by the Fillet PropertyManager")
            obj.setEditorMode(name, 2)


def open_new(doc=None, edges=()):
    """The Fillet page on surfaces; edges: [(surface object, "EdgeN")] picked before the command."""
    doc = doc or App.ActiveDocument
    if doc is None:
        return False
    base = edges[0][0] if edges else None
    Gui.Selection.clearSelection()
    Gui.Control.showDialog(SurfaceFilletPanel(doc, base, picks=list(edges)))
    return True


def open_edit(obj):
    """Edit Feature on a Constant Size Surface-Fillet: the Fillet page on its surface."""
    links = list(obj.Edges or [])
    if not links:
        return False
    base, subs = links[0][0], links[0][1]
    _base_props(obj)
    obj.Base = (base, list(subs))
    Gui.Control.showDialog(SurfaceFilletPanel(obj.Document, base, feature=obj))
    return True


class FullRoundPanel(QtCore.QObject):
    ""


    SLOTS = ("Side Face Set 1", "Center Face Set", "Side Face Set 2")
    PROPS = ("Face1", "CenterFace", "Face2")

    def __init__(self, doc, base=None, feature=None):
        super().__init__()
        from . import pmboxes
        self.doc, self.base, self.feature, self.edit = doc, base, feature, feature
        self.picks = [None, None, None]             # (object, "FaceN")
        if feature is not None:
            for k, name in enumerate(self.PROPS):
                link = getattr(feature, name, None)
                if link is not None:
                    sub = link[1][0] if isinstance(link[1], (list, tuple)) else link[1]
                    self.picks[k] = (link[0], sub)
            self.base = self.picks[0][0] if self.picks[0] else base
        doc.openTransaction(surfacefillet.TITLE)
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Items To Fillet")
        self.form.setProperty("swstyle_pm_title", "Fillet")
        self.form.setProperty("swstyle_pm_icon", "FEATURES_FULL_ROUND_FILLET")
        lay = QtWidgets.QVBoxLayout(self.form)
        self.boxes = []
        for k, slot in enumerate(self.SLOTS):
            lab = QtWidgets.QLabel(slot, self.form)
            lay.addWidget(lab)
            box = QtWidgets.QListWidget(self.form)
            box.setObjectName("SWSurfFullRound%d" % k)
            box.setMaximumHeight(28)
            box.setToolTip("Pick a flat face of the surface")
            box.viewport().installEventFilter(self)
            pmboxes.bind(box, remove=lambda row, k=k: self._drop(k))
            lay.addWidget(box)
            self.boxes.append(box)
        self.message = QtWidgets.QLabel("", self.form)
        self.message.setWordWrap(True)
        lay.addWidget(self.message)
        self.active = next((k for k in range(3) if self.picks[k] is None), 0)
        self._fill()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)
        if all(self.picks) and self.feature is None:
            self._build()

    # --- the boxes
    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.MouseButtonPress:
            for k, box in enumerate(self.boxes):
                if watched is box.viewport():
                    self.active = k
                    self._fill()
        return False

    def _fill(self):
        from . import pmboxes
        for k, box in enumerate(self.boxes):
            box.clear()
            if self.picks[k] is not None:
                box.addItem("%s<1>" % "Face")
            pmboxes.mark(box, k == self.active)

    def _drop(self, k):
        self.picks[k] = None
        self.active = k
        self._fill()
        self._build()

    def addSelection(self, doc, name, sub, _pnt):
        try:
            obj = App.getDocument(doc).getObject(name)
            from . import refplane
            obj, sub = refplane.resolve(obj, sub or "")
        except Exception as _fw_err:
            _fw_log("surfacefilletpm.py:fr-resolve", _fw_err)
            return
        if obj is None or not sub or not sub.startswith("Face") or not surfacefillet._is_surface(obj):
            return
        if self.base is not None and obj is not self.base and any(self.picks):
            return
        self.base = obj
        self.picks[self.active] = (obj, sub)
        empty = [k for k in range(3) if self.picks[k] is None]
        self.active = empty[0] if empty else self.active
        QtCore.QTimer.singleShot(0, self._picked)

    def _picked(self):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("surfacefilletpm.py:fr-clear", _fw_err)
        self._fill()
        self._build()

    # --- the feature
    def _build(self):
        if not all(self.picks):
            self.message.setText("")
            return
        f = self.feature
        if f is None:
            f = self.doc.addObject("Part::FeaturePython", "SurfaceFillet")
            surfacefillet.SurfaceFillet(f)
            if f.ViewObject is not None:
                surfacefillet.View(f.ViewObject)
            try:
                from . import naming
                f.Label = naming.next_label(self.doc, surfacefillet.LABEL)
            except Exception as _fw_err:
                _fw_log("surfacefilletpm.py:fr-label", _fw_err)
            self.feature = f
        surfacefillet._radii_prop(f)
        f.FilletType = "Full Round"
        for name, (obj, sub) in zip(self.PROPS, self.picks):
            setattr(f, name, (obj, [sub]))
        self.doc.recompute()
        bad = "Invalid" in f.State or f.Shape.isNull()
        self.message.setText("The full round could not be made on these faces: pick flat side faces that face each other "
                             "and a center face between them." if bad else "")
        self.message.setStyleSheet("color: #c00000;" if bad else "")
        try:
            if not bad:
                f.ViewObject.Visibility = True
                self.base.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("surfacefilletpm.py:fr-show", _fw_err)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("surfacefilletpm.py:fr-observer", _fw_err)
        Gui.Control.closeDialog()

    def accept(self):
        if not all(self.picks) or self.feature is None or "Invalid" in self.feature.State or self.feature.Shape.isNull():
            self.message.setText("Pick the side faces and the center face of one surface.")
            self.message.setStyleSheet("color: #c00000;")
            return False
        self.doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        self.doc.abortTransaction()
        try:        # FreeCAD's application-wide step can stay open after the abort (features-437)
            App.closeActiveTransaction(True)
        except Exception as _fw_err:
            _fw_log("surfacefilletpm.py:fr-close", _fw_err)
        if self.edit is not None and "Touched" in self.edit.State:
            self.doc.recompute()        # the edit's own faces back: built as it was
        try:
            if self.base is not None and self.edit is None:
                self.base.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("surfacefilletpm.py:fr-restore", _fw_err)
        self._close()
        return True


def open_full_round(doc=None, base=None, feature=None):
    """The surface Full Round page (Fillet > Full Round on a surface, or Edit Feature on one)."""
    doc = doc or App.ActiveDocument
    if doc is None or Gui.Control.activeDialog():
        return False
    Gui.Control.showDialog(FullRoundPanel(doc, base, feature))
    return True
