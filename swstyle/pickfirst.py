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
from . import pmboxes

_LAST = None


def _kind(sub):
    return sub.split(".")[-1].lstrip("?").rstrip("0123456789")


def _fits(kinds, obj, sub):
    for k in kinds:
        if callable(k):
            if k(obj, sub):
                return True
        elif k == "Object" and not sub:
            return True
        elif k == "Sketch" and obj.isDerivedFrom("Sketcher::SketchObject"):
            return True
        elif sub and _kind(sub) == k:
            return True
    return "Whole" in kinds


def _entry(kinds, obj, sub):
    """The (doc, name, sub) a pick goes in the box as, or None when the box does not take it."""
    if not _fits(kinds, obj, sub):
        return None
    if "Whole" in kinds:
        others = tuple(k for k in kinds if k != "Whole")
        if not (others and _fits(others, obj, sub)):
            sub = ""
    return (obj.Document.Name, obj.Name, sub)


class PickPanel:
    def __init__(self, title, label, kinds, then, minimum=1, maximum=0, box=False):
        global _LAST
        _LAST = self
        self.title, self.kinds, self.then, self.minimum = title, tuple(kinds), then, minimum
        self.maximum = maximum
        self.picks = []
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("SWPickPanel")

        # Surface: Bounding Entities)
        self.form.setWindowTitle(label if box else title)
        self.form.setProperty("swstyle_pm_title", title)
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.setContentsMargins(4, 4, 4, 4)
        head = QtWidgets.QLabel(label)
        f = head.font()
        f.setBold(True)
        head.setFont(f)
        head.setWordWrap(True)
        lay.addWidget(head)
        head.setVisible(not box)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWPickList")
        self.list.setToolTip(label)
        self.list.setMaximumHeight(120)
        pmboxes.mark(self.list, True)
        self.list.installEventFilter(self._keys())
        lay.addWidget(self.list)
        self.message = QtWidgets.QLabel("")
        self.message.setObjectName("SWPickMessage")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c00000;")
        self.message.hide()
        lay.addWidget(self.message)
        lay.addStretch(1)
        # the group is as tall as its rows: the list box must not stretch it into the pane's spare height
        # (a ~170 px blank band under Planar Surface's Bounding Entities box, look audit AA2)
        self.form.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        for sel in Gui.Selection.getSelectionEx():      # picks made before the command go in the box
            for sub in sel.SubElementNames or [""]:
                key = _entry(self.kinds, sel.Object, sub)
                if key is not None and key not in self.picks:
                    self.picks.append(key)
        if self.maximum:
            self.picks = self.picks[-self.maximum:]
        Gui.Selection.clearSelection()
        self._fill()
        Gui.Selection.addObserver(self)

    def _keys(self):
        panel = self

        class Keys(QtCore.QObject):
            def eventFilter(self, watched, event):
                if not isinstance(event, QtCore.QEvent):
                    return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
                if event.type() == QtCore.QEvent.KeyPress and event.key() in (QtCore.Qt.Key_Delete,
                                                                               QtCore.Qt.Key_Backspace):
                    row = panel.list.currentRow()
                    if 0 <= row < len(panel.picks):
                        del panel.picks[row]
                        panel._fill()
                    return True
                return False
        self._filter = Keys()
        return self._filter

    def _fill(self):
        self.list.clear()
        for doc, name, sub in self.picks:
            obj = App.getDocument(doc).getObject(name)
            label = obj.Label if obj is not None else name
            if sub:
                kind = _kind(sub)
                self.list.addItem("%s<%s>@%s" % (kind, sub.split(".")[-1].lstrip("?")[len(kind):], label))
            else:
                self.list.addItem(label)

    def addSelection(self, doc, name, sub, point):
        from . import safe_later as _sl; _sl.later(0, lambda: self.picked(doc, name, sub), self, "message")

    def _gone(self):
        """True when the PM was closed some other way (another dialog took the task panel): stop listening."""
        try:
            import shiboken6 as shiboken
        except ImportError:
            import shiboken2 as shiboken
        if shiboken.isValid(self.list):
            return False
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("pickfirst.py:151", _fw_err)
        App.Console.PrintLog("FreeCAD: %s pick box closed\n" % self.title)
        return True

    def picked(self, doc, name, sub):
        if self._gone():
            return
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("pickfirst.py:161", _fw_err)
        obj = App.getDocument(doc).getObject(name)
        key = _entry(self.kinds, obj, sub) if obj is not None else None
        if key is None:
            return
        if key in self.picks:
            self.picks.remove(key)
        else:
            self.picks.append(key)
            if self.maximum and len(self.picks) > self.maximum:    # a full box: the oldest pick goes
                del self.picks[0]
        self.message.hide()
        self._fill()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("pickfirst.py:182", _fw_err)
        Gui.Control.closeDialog()

    def accept(self):
        if len(self.picks) < self.minimum:
            self.message.setText("Pick what to use in the graphics area.")
            self.message.show()
            return False
        picks = list(self.picks)
        self._close()

        def go():
            Gui.Selection.clearSelection()
            for doc, name, sub in picks:
                try:
                    Gui.Selection.addSelection(doc, name, sub)
                except Exception as _fw_err:
                    _fw_log("pickfirst.py:199", _fw_err)
            self.then()
        QtCore.QTimer.singleShot(0, go)
        return True

    def reject(self):
        self._close()
        return True


def ask(title, label, kinds, then, minimum=1, maximum=0, box=False):
    """Opens the pick PM (tool first). Returns None, so a command can `return ask(...)`."""
    if Gui.Control.activeDialog():
        return None
    Gui.Control.showDialog(PickPanel(title, label, kinds, then, minimum, maximum, box))
    return None


def ask_in_sketch(sketch, title, label, then, single=False, bodies=False, options=()):
    """The same for tools used inside a sketch: a page in the sketch's PropertyManager with one box for
    sketch entities (the sketch's own PM stays as the sketch tools' PMs do). The check puts the picks back as
    the selection and calls then(). bodies: the box takes other objects (bodies) instead of sketch entities.
    options: (key, text, default) check boxes under the box; then({key: checked}) when there are any."""
    from . import relationspm, sketchtoolpm

    class Observer:
        def __init__(self, page):
            self.page = page

        def addSelection(self, doc, obj, sub, pnt):
            page = self.page
            if page is None:
                return
            if bodies:
                if obj != page.sketch.Name:
                    QtCore.QTimer.singleShot(0, lambda o=obj: page.picked(o))
                return
            if obj != page.sketch.Name or not sub:
                return
            QtCore.QTimer.singleShot(0, lambda s=sub.rsplit(".", 1)[-1]: page.picked(s))

    class PickPage(sketchtoolpm.ToolPage):
        TITLE = title
        TRANSACTION = title

        def build(self):
            g = self.group(label)
            self.box = QtWidgets.QListWidget(g.body)
            self.box.setObjectName("SWSketchPickList")
            self.box.setToolTip(label)
            self.box.setMaximumHeight(110)
            pmboxes.mark(self.box, True)
            g.content.addWidget(self.box)
            self.options = {}
            for key, text, default in options:
                cb = QtWidgets.QCheckBox(text, g.body)
                cb.setChecked(bool(default))
                cb.toggled.connect(lambda _on: None)
                g.content.addWidget(cb)
                self.options[key] = cb
            self.geos = []
            for sel in Gui.Selection.getSelectionEx():
                if bodies and sel.Object != self.sketch:
                    self.geos.append(sel.Object.Name)
                elif not bodies and sel.Object == self.sketch:
                    for sub in sel.SubElementNames:
                        if sub.startswith("Edge"):
                            self.geos.append(int(sub[4:]) - 1)
            if single:
                self.geos = self.geos[:1]
            self.observer = Observer(self)
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self.observer)
            self._fill()

        def _fill(self):
            self.box.clear()
            if bodies:
                for g in self.geos:
                    o = self.doc.getObject(g)
                    self.box.addItem(o.Label if o is not None else g)
                return
            names = relationspm._entity_names(self.sketch.Geometry)
            for g in self.geos:
                self.box.addItem(names[g] if 0 <= g < len(names) else "Edge%d" % (g + 1))

        def picked(self, sub):
            try:
                Gui.Selection.clearSelection()
            except Exception as _fw_err:
                _fw_log("pickfirst.py:289", _fw_err)
            if bodies:
                geo = sub
            elif not sub.startswith("Edge"):
                return
            else:
                geo = int(sub[4:]) - 1
            if geo in self.geos:
                self.geos.remove(geo)
            elif single:
                self.geos = [geo]
            else:
                self.geos.append(geo)
            self.show_note("")
            self._fill()

        def accept(self):
            if not self.geos:
                self.show_note("Pick the sketch entities in the graphics area.", True)
                return
            geos, sketch = list(self.geos), self.sketch
            chosen = {k: cb.isChecked() for k, cb in self.options.items()}
            super().accept()

            def go():
                Gui.Selection.clearSelection()
                for g in geos:
                    if bodies:
                        Gui.Selection.addSelection(sketch.Document.Name, g)
                    else:
                        Gui.Selection.addSelection(sketch.Document.Name, sketch.Name, "Edge%d" % (g + 1))
                then(chosen) if options else then()
            QtCore.QTimer.singleShot(0, go)

        def closing(self):
            try:
                Gui.Selection.removeObserver(self.observer)
            except Exception as _fw_err:
                _fw_log("pickfirst.py:327", _fw_err)
            self.observer.page = None

    sketchtoolpm.open_page(PickPage(sketch))
    return None


# ---- tool first for FreeCAD commands that are greyed, or ask for a selection, when nothing is picked

def _ready(kinds, minimum, maximum):
    n = 0
    for sel in Gui.Selection.getSelectionEx():
        for sub in sel.SubElementNames or [""]:
            if _entry(kinds, sel.Object, sub) is None:
                return False
            n += 1
    return n >= minimum and (not maximum or n <= maximum)


class DefeaturePanel(PickPanel):
    ""




    def __init__(self, title, label, kinds, then, minimum=1, maximum=0):
        from . import defeatsil
        PickPanel.__init__(self, title, label, kinds, then, minimum, maximum)
        lay = self.form.layout()
        box = QtWidgets.QGroupBox("Method")
        box.setObjectName("SWDefeatureMethod")
        v = QtWidgets.QVBoxLayout(box)
        self.remove = QtWidgets.QRadioButton("Remove details")
        self.remove.setObjectName("SWDefeatureRemove")
        self.silhouette = QtWidgets.QRadioButton("Silhouette")
        self.silhouette.setObjectName("SWDefeatureSilhouette")
        self.remove.setChecked(True)
        v.addWidget(self.remove)
        v.addWidget(self.silhouette)
        lay.insertWidget(0, box)
        self._pick_widgets = [lay.itemAt(i).widget() for i in range(1, 3)]
        sil = QtWidgets.QGroupBox("Silhouette")
        sil.setObjectName("SWDefeatureSilhouetteBox")
        sv = QtWidgets.QVBoxLayout(sil)
        self.kind_buttons = {}
        for kind in defeatsil.KINDS:
            b = QtWidgets.QRadioButton(kind)
            b.setObjectName("SWDefeatureKind_" + kind.replace(" ", ""))
            b.toggled.connect(self._method)
            sv.addWidget(b)
            self.kind_buttons[kind] = b
        self.kind_buttons["Bounding box"].setChecked(True)
        self.plane_label = QtWidgets.QLabel("Outline plane (pick a plane or a flat face):")
        sv.addWidget(self.plane_label)
        self.plane = QtWidgets.QLineEdit("Top Plane")
        self.plane.setObjectName("SWDefeaturePlane")
        self.plane.setReadOnly(True)
        sv.addWidget(self.plane)
        self.normal = App.Vector(0, 0, 1)
        self.loops = QtWidgets.QCheckBox("Keep internal loops")
        self.loops.setObjectName("SWDefeatureKeepLoops")
        self.loops.setToolTip("Holes through the outline stay in the silhouette")
        self.loops.setChecked(True)
        sv.addWidget(self.loops)
        lay.insertWidget(lay.count() - 1, sil)
        out = QtWidgets.QGroupBox("Output")
        out.setObjectName("SWDefeatureOutput")
        ov = QtWidgets.QVBoxLayout(out)
        self.outputs = {}
        for name in defeatsil.OUTPUTS:
            b = QtWidgets.QRadioButton(name)
            b.setObjectName("SWDefeatureOutput_" + name.replace(" ", ""))
            ov.addWidget(b)
            self.outputs[name] = b
        self.outputs[defeatsil.OUTPUTS[0]].setChecked(True)
        lay.insertWidget(lay.count() - 1, out)
        self.sil_box, self.out_box = sil, out
        # the box made for the shape before (a list in older checks): the chosen kind's text
        self.shape = _KindProxy(self)
        self.silhouette.toggled.connect(self._method)
        self._method()

    def kind(self):
        return next((k for k, b in self.kind_buttons.items() if b.isChecked()), "Bounding box")

    def output(self):
        return next((k for k, b in self.outputs.items() if b.isChecked()), "Save as New Document")

    def _method(self, *_):
        if not hasattr(self, "out_box"):
            return      # cmsweep-1119: a radio button set while the panel is still being built
        sil = self.silhouette.isChecked()
        for w in self._pick_widgets:
            if w is not None:
                w.setVisible(not sil)
        self.sil_box.setVisible(sil)
        self.out_box.setVisible(sil)
        outline = self.kind() in ("Polygon outline", "Tight fit outline")
        self.plane_label.setVisible(outline)
        self.plane.setVisible(outline)
        self.loops.setVisible(outline)
        self.loops.setEnabled(self.kind() == "Tight fit outline")

    def picked(self, doc, name, sub):
        if not self.silhouette.isChecked():
            return PickPanel.picked(self, doc, name, sub)
        if self._gone():
            return
        obj = App.getDocument(doc).getObject(name)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("pickfirst.py:437", _fw_err)
        n = _plane_normal(obj, sub)
        if n is None:
            return
        self.normal = n
        self.plane.setText(pmboxes.sw_name(("%s@%s" % (sub.split(".")[-1], obj.Label)) if sub else obj.Label))

    def _body(self):
        doc = App.ActiveDocument
        try:
            body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
        except Exception:
            body = None
        if body is None and doc is not None:
            for d, name, sub in self.picks:
                o = App.getDocument(d).getObject(name)
                if o is not None:
                    body = next((b for b in o.InList if b.TypeId == "PartDesign::Body"), o)
                    break
        if body is None and doc is not None:
            shown = [o for o in doc.Objects if o.TypeId in ("PartDesign::Body", "Part::Feature")
                     and getattr(o, "Shape", None) is not None and not o.Shape.isNull() and o.Shape.Solids
                     and o.ViewObject is not None and o.ViewObject.Visibility]
            body = shown[0] if shown else None
        return body

    def accept(self):
        if not self.silhouette.isChecked():
            return PickPanel.accept(self)
        body = self._body()
        if body is None:
            self.message.setText("The part has no solid body.")
            self.message.show()
            return False
        kind, output = self.kind(), self.output()
        normal, loops = App.Vector(self.normal), self.loops.isChecked()
        if output == "Create New Configuration" and body.TypeId != "PartDesign::Body":
            self.message.setText("Create New Configuration needs a part Body.")
            self.message.show()
            return False
        self._close()
        from . import defeatsil
        if output == "Create New Configuration":
            return defeatsil.to_new_configuration(body, kind, normal, loops)
        return defeatsil.to_new_document(body, kind, normal, loops)


class _KindProxy:
    """currentText() / setCurrentText() over the Silhouette kind buttons ("Cylinder" means Cylindrical)."""

    def __init__(self, panel):
        self.panel = panel

    def currentText(self):
        return self.panel.kind()

    def setCurrentText(self, text):
        text = "Cylindrical" if text == "Cylinder" else text
        b = self.panel.kind_buttons.get(text)
        if b is not None:
            b.setChecked(True)


def _plane_normal(obj, sub):
    """The normal of a picked flat face or a plane, in the model, or None."""
    if obj is None:
        return None
    try:
        if sub:
            face = obj.Shape.getElement(sub.split(".")[-1])
            if face.ShapeType != "Face" or face.Surface.TypeId != "Part::GeomPlane":
                return None
            uv = face.Surface.parameter(face.CenterOfMass)
            return App.Vector(face.normalAt(*uv)).normalize()
        if obj.TypeId in ("App::Plane", "PartDesign::Plane"):
            pl = obj.getGlobalPlacement() if hasattr(obj, "getGlobalPlacement") else obj.Placement
            return pl.Rotation.multVec(App.Vector(0, 0, 1))
    except Exception as _fw_err:
        _fw_log("pickfirst.py:516", _fw_err)
        return None
    return None


def make_silhouette(body, kind="Bounding box"):
    """The body's silhouette in a new part document (Save as New Document)."""
    from . import defeatsil
    return defeatsil.to_new_document(body, "Cylindrical" if kind == "Cylinder" else kind, App.Vector(0, 0, 1), True)[1]


class NativeCommand:
    """Runs a FreeCAD command on the picks: straight away when what is picked fits, otherwise after the
    pick PM (the tool clicked first)."""

    def __init__(self, native, title, label, kinds, tip, minimum=1, maximum=0, feature=None):
        self.native, self.title, self.label, self.kinds = native, title, label, tuple(kinds)
        self.tip, self.minimum, self.maximum, self.feature = tip, minimum, maximum, feature
        self.pixmap = native

    def GetResources(self):
        return {"MenuText": self.title, "ToolTip": self.tip, "Pixmap": self.pixmap}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def _run(self):
        doc = App.ActiveDocument
        if self.native == "Part_MakeFace":

            from . import planarsurface
            return planarsurface.from_selection()
        before = set(o.Name for o in doc.Objects) if doc is not None else set()
        Gui.runCommand(self.native, 0)
        new = [o for o in doc.Objects if o.Name not in before and hasattr(o, "Shape")] if doc is not None else []
        if new and self.feature:
            from . import naming
            new[-1].Label = naming.next_label(doc, self.feature)

    def Activated(self):
        if _ready(self.kinds, self.minimum, self.maximum):
            if self.native == "Part_MakeFace":

                from . import planarsurface
                return planarsurface.open_page()
            return self._run()
        if self.native == "Part_Defeaturing":
            if not Gui.Control.activeDialog():
                Gui.Control.showDialog(DefeaturePanel(self.title, self.label, self.kinds, self._run,
                                                      self.minimum, self.maximum))
            return None
        ask(self.title, self.label, self.kinds, self._run, self.minimum, self.maximum,
            box=self.native == "Part_MakeFace")


class EditMaterialCommand:
    ""

    def GetResources(self):
        return {"MenuText": "Edit Material", "ToolTip": "Sets the part's material.", "Pixmap": "Std_SetMaterial"}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        from . import material      # the part's Material dialog (library tree, Apply / Close)
        material.edit(App.ActiveDocument)


NATIVES = (
    ("SWStyle_PlanarSurface", "Part_MakeFace", "Planar Surface", "Bounding Entities", ("Sketch", "Edge"),
     "A flat face from a closed sketch or closed edges.", 1, 0, "Surface-Plane"),
    ("SWStyle_RuledSurface", "Part_RuledSurface", "Ruled Surface", "Edge Selection (two edges)", ("Edge",),
     "A ruled surface between two edges.", 2, 2, "Ruled Surface"),
    ("SWStyle_Defeature", "Part_Defeaturing", "Defeature", "Faces to remove", ("Face",),
     "Removes details such as fillets and holes from a body.", 1, 0, "Defeature"),
)


def register():
    for name, native, title, label, kinds, tip, minimum, maximum, feature in NATIVES:
        Gui.addCommand(name, NativeCommand(native, title, label, kinds, tip, minimum, maximum, feature))
    Gui.addCommand("SWStyle_EditMaterial", EditMaterialCommand())
