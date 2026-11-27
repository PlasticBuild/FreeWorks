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
from PySide import QtWidgets

DETAILING = "Detailing"
DIMXPERT = "DimXpert dimensions"      # the Detailing display filter row (MBD size and location dimensions)
FILTER = ("Datums", "Geometric tolerances", "Datum targets", "Notes", "Feature dimensions",
          "Reference dimensions", DIMXPERT, "Display all types")
DEFAULTS = {"Feature dimensions": False, "Display all types": False}


def value(doc, text):
    from . import optionspages
    default = DEFAULTS.get(text, True)
    return bool(optionspages.doc_value(doc, DETAILING, text, default))


def set_value(doc, text, on):
    """A Detailing display filter row, for this document (as the Options box keeps it) and new ones."""
    from . import optionspages
    optionspages.set_stored(DETAILING, text, bool(on))
    if doc is not None:
        meta = dict(doc.Meta)
        meta[optionspages.DOC_META + optionspages._store_key(DETAILING, text)] = "1" if on else "0"
        doc.Meta = meta
    apply(doc)


def apply(doc):
    try:
        from . import optionsextras
        optionsextras.apply_detailing(doc)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: annotations: %s\n" % error)
    try:
        from . import featuredims
        featuredims.refresh(doc)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: feature dimensions: %s\n" % error)


def annotations_shown():
    from . import viewtypes
    return App.ActiveDocument is not None and viewtypes.shown("AllAnnotations")


def set_annotations_shown(on):
    from . import viewtypes
    if App.ActiveDocument is not None:
        viewtypes.set_shown("AllAnnotations", on)


class AnnotationProperties(QtWidgets.QDialog):
    ""

    def __init__(self, doc, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc
        self.setObjectName("SWAnnotationProperties")
        self.setWindowTitle("Annotation Properties")
        lay = QtWidgets.QVBoxLayout(self)
        box = QtWidgets.QGroupBox("Display filter")
        grid = QtWidgets.QGridLayout(box)
        self.checks = {}
        for i, text in enumerate(FILTER):
            c = QtWidgets.QCheckBox(text)
            c.setObjectName("SWAnnotFilter" + text.replace(" ", ""))
            c.setChecked(value(doc, text))
            self.checks[text] = c
            grid.addWidget(c, i // 2, i % 2)
        lay.addWidget(box)
        self.display = QtWidgets.QCheckBox("Display annotations")
        self.display.setChecked(annotations_shown())
        lay.addWidget(self.display)
        self.same = QtWidgets.QCheckBox("Text scale: always display text at the same size")
        from . import optionspages
        self.same.setChecked(bool(optionspages.doc_value(doc, DETAILING, "Always display text at the same size", True)))
        lay.addWidget(self.same)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def accept(self):
        for text, c in self.checks.items():
            if c.isChecked() != value(self.doc, text):
                set_value(self.doc, text, c.isChecked())
        if self.display.isChecked() != annotations_shown():
            set_annotations_shown(self.display.isChecked())
        from . import optionspages
        optionspages.set_stored(DETAILING, "Always display text at the same size", self.same.isChecked())
        meta = dict(self.doc.Meta)
        meta[optionspages.DOC_META + optionspages._store_key(DETAILING, "Always display text at the same size")] = \
            "1" if self.same.isChecked() else "0"
        self.doc.Meta = meta
        super().accept()


_OPEN = []


def details(doc=None):
    box = AnnotationProperties(doc or App.ActiveDocument)
    _OPEN[:] = [box]
    box.show()
    return box


# ------------------------------------------------------------------ sensors
def is_sensor(obj):
    try:
        return type(getattr(obj, "Proxy", None)).__name__ == "Sensor" and "Alerting" in obj.PropertiesList
    except Exception:
        return False


def add_sensor():
    from . import evaluate2
    evaluate2.install()
    Gui.runCommand("SWStyle_Sensor", 0)


def edit_sensor(obj):
    ""
    try:
        from . import sensorpm
        return sensorpm.open_page(obj.Document, obj)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: sensor page: %s\n" % error)
    from . import evaluate2
    box = evaluate2._SensorDialog()
    box.setWindowTitle("Sensor - %s" % obj.Label.lstrip("⚠ "))
    box.prop.setCurrentText(obj.Property)
    box.op.setCurrentText(obj.Operator)
    box.l1.setValue(obj.Limit1)
    box.l2.setValue(obj.Limit2)
    alert = QtWidgets.QCheckBox("Alert")
    alert.setChecked(bool(obj.Alert))
    box.layout().insertRow(3, "", alert)

    def done():
        doc = obj.Document
        doc.openTransaction("Edit Sensor")
        try:
            obj.Property = box.prop.currentText()
            obj.Operator = box.op.currentText()
            obj.Limit1, obj.Limit2 = box.l1.value(), box.l2.value()
            obj.Alert = alert.isChecked()
            obj.touch()
            doc.recompute()
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
    box.accepted.connect(done)
    _OPEN[:] = [box]
    box.show()
    return box


# ------------------------------------------------------------------ Annotations folder (R9 bonus read)
GROUP = "FWAnnotations"
AUTO_PLACE = "Automatically place into annotation views"
VIEW_VISIBILITY = "Enable annotation view visibility"
ALL_VIEWS = "Show all views in dynamic view mode"


def _labels(doc):
    g = doc.getObject(GROUP) if doc is not None else None
    return list(g.Group) if g is not None else []


def reference_annotations_shown(doc):
    return not any(getattr(o, "Visibility", True) is False for o in _labels(doc))


def set_reference_annotations_shown(doc, on):
    for o in _labels(doc):
        try:
            o.Visibility = bool(on)
        except Exception as _fw_err:
            _fw_log("treevirtual.py:205", _fw_err)


def listed_in_tree(doc):
    g = doc.getObject(GROUP) if doc is not None else None
    try:
        return g is None or g.ViewObject.ShowInTree
    except Exception:
        return True


def set_listed_in_tree(doc, on):
    g = doc.getObject(GROUP) if doc is not None else None
    if g is not None:
        try:
            g.ViewObject.ShowInTree = bool(on)
        except Exception as _fw_err:
            _fw_log("treevirtual.py:222", _fw_err)


def _flag(doc, row, default):
    from . import optionspages
    return bool(optionspages.doc_value(doc, DETAILING, row, default))


def _set_flag(doc, row, on):
    from . import optionspages
    optionspages._doc_set(DETAILING, row, bool(on))


def _gui(name):
    try:
        Gui.runCommand(name)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s: %s\n" % (name, error))


def _rename_folder(doc):
    from . import fmmenu
    g = doc.getObject(GROUP) if doc is not None else None
    if g is None:
        g = doc.addObject("App::DocumentObjectGroup", GROUP)
        g.Label = "Annotations"
    fmmenu.rename(None, g)


def _annotation_tail(doc, view):
    ""




    from . import fmmenu
    ok = doc is not None
    tick = lambda on, t: ("✓ " if on else "") + t
    out = []
    add = out.append
    ref = ok and reference_annotations_shown(doc)
    add(("ShowReferenceAnnotations", tick(ref, "Show Reference Annotations"),
         lambda: set_reference_annotations_shown(doc, not ref), ok))
    listed = ok and listed_in_tree(doc)
    add(("ListAnnotations", tick(listed, "List Annotations in Tree View"), lambda: set_listed_in_tree(doc, not listed), ok))
    add(("-", None, None, False))
    add(("DynamicAnnotationViews", "Dynamic Annotation Views", lambda: _gui("SWStyle_MBDDynamicViews"), ok))
    allv = ok and _flag(doc, ALL_VIEWS, False)
    add(("ShowAllViews", tick(allv, "Show All Views in Dynamic View Mode"),
         lambda: (_set_flag(doc, ALL_VIEWS, not allv), (not allv) and _gui("SWStyle_MBD3DViews")), ok))
    add(("-", None, None, False))
    add(("InsertAnnotationView", "Insert Annotation View", lambda: fmmenu._later(lambda: insert_annotation_view(doc)), ok))
    auto = ok and _flag(doc, AUTO_PLACE, True)
    add(("AutoPlace", tick(auto, "Automatically Place into Annotation Views"), lambda: set_auto_place(doc, not auto), ok))
    vis = ok and _flag(doc, VIEW_VISIBILITY, False)
    add(("ViewVisibility", tick(vis, "Enable Annotation View Visibility"), lambda: _set_flag(doc, VIEW_VISIBILITY, not vis), ok))
    add(("-", None, None, False))
    add(("GoTo", "Go To...", lambda: fmmenu.go_to(view, doc), True))
    add(("Collapse", "Collapse Items", lambda: fmmenu.collapse(view), True))
    add(("-", None, None, False))
    add(("Rename", "Rename tree item", lambda: _rename_folder(doc), ok))
    add(("TreeItems", "Hide/Show Tree Items...", fmmenu.tree_items, True))
    add(("Customize", "Customize Menu", None, True))
    return out


# ------------------------------------------------------------------ menus
def entries(kind, doc, view=None):
    """[(key, label, run, enabled)] for a top folder's menu (fmmenu's form)."""
    from . import fmmenu
    out = []
    add = out.append
    if kind == "sensors":

        # tree items, Customize Menu after a line
        add(("AddSensor", "Add Sensor...", lambda: fmmenu._later(add_sensor), doc is not None))
        add(("-", None, None, False))
        add(("TreeItems", "Hide/Show Tree Items...", fmmenu.tree_items, True))
        add(("Collapse", "Collapse Items", lambda: fmmenu.collapse(view), True))
        add(("-", None, None, False))
        add(("Customize", "Customize Menu", None, True))
        return out
    elif kind == "annotations":
        add(("AnnotationDetails", "Details...", lambda: fmmenu._later(lambda: details(doc)), doc is not None))
        add(("-", None, None, False))
        add(("DisplayAnnotations", ("✓ " if annotations_shown() else "") + "Display Annotations",
             lambda: set_annotations_shown(not annotations_shown()), doc is not None))
        for key, text, row in (("ShowFeatureDimensions", "Show Feature Dimensions", "Feature dimensions"),
                               ("ShowReferenceDimensions", "Show Reference Dimensions", "Reference dimensions"),
                               ("ShowDimXpert", "Show DimXpert Annotations", DIMXPERT)):
            on = value(doc, row)
            add((key, ("✓ " if on else "") + text, (lambda r=row, o=on: set_value(doc, r, not o)), doc is not None))
        return out + _annotation_tail(doc, view)
    add((None, {"history": "History", "sensors": "Sensors", "annotations": "Annotations"}[kind], None, False))
    add(("-", None, None, False))
    add(("TreeItems", "Hide/Show Tree Items...", fmmenu.tree_items, True))
    add(("Collapse", "Collapse Items", lambda: fmmenu.collapse(view), True))
    add(("Customize", "Customize Menu", None, True))
    return out



NOTES_AREA = "Notes Area"
UNASSIGNED_ITEMS = "Unassigned Items"
# the standard annotation views and the face normal each one looks at (FreeCAD's Front looks along +Y)
STANDARD_VIEWS = (("*Front", (0, -1, 0)), ("*Top", (0, 0, 1)), ("*Right", (1, 0, 0)),
                  ("*Back", (0, 1, 0)), ("*Bottom", (0, 0, -1)), ("*Left", (-1, 0, 0)))
VIEW_ORDER = (NOTES_AREA,) + tuple(n for n, _d in STANDARD_VIEWS) + (UNASSIGNED_ITEMS,)
VIEW_PROP = "SWAnnotationView"          # on an annotation: the view it was put in
VIEWS_PROP = "SWAnnotationViews"        # on the Annotations group: the views inserted (shown when empty too)


def _std_view(normal):
    """The standard view looking at a face with this normal, or None (not square to the model)."""
    try:
        n = App.Vector(normal)
        if n.Length < 1e-9:
            return None
        n.normalize()
        for name, d in STANDARD_VIEWS:
            if n.dot(App.Vector(*d)) >= 0.999:
                return name
    except Exception as _fw_err:
        _fw_log("treevirtual.py:std-view", _fw_err)
    return None


def _face_normal(obj):
    for ref in list(getattr(obj, "References", []) or []):
        try:
            src, subs = ref
            for sub in (subs if isinstance(subs, (list, tuple)) else [subs]):
                if not str(sub).startswith("Face"):
                    continue
                face = src.Shape.getElement(str(sub))
                if face.Surface.TypeId == "Part::GeomPlane":
                    u0, u1, v0, v1 = face.ParameterRange
                    return face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        except Exception as _fw_err:
            _fw_log("treevirtual.py:face-normal", _fw_err)
    return None


def view_of(obj):
    ""



    if obj is None or not hasattr(obj, "Kind") or "References" not in getattr(obj, "PropertiesList", []):
        return None
    put = str(getattr(obj, VIEW_PROP, "") or "")
    if put:
        return put
    if not _flag(obj.Document, AUTO_PLACE, True):
        return UNASSIGNED_ITEMS
    if obj.Kind == "Note" and not list(obj.References or []):
        return NOTES_AREA
    n = _face_normal(obj)
    if n is None:
        made = getattr(obj, "CreatedView", None)
        n = -App.Vector(made) if made is not None and App.Vector(made).Length > 1e-9 else None
    return (_std_view(n) if n is not None else None) or UNASSIGNED_ITEMS


def set_auto_place(doc, on):
    ""

    if not on and doc is not None:
        for o in list(doc.Objects):
            name = view_of(o)
            if name not in (None, UNASSIGNED_ITEMS) and not str(getattr(o, VIEW_PROP, "") or ""):
                if VIEW_PROP not in o.PropertiesList:
                    o.addProperty("App::PropertyString", VIEW_PROP, "PMI", "The annotation view it is in")
                    try:
                        o.setEditorMode(VIEW_PROP, 2)
                    except Exception as _fw_err:
                        _fw_log("treevirtual.py:auto-hide", _fw_err)
                setattr(o, VIEW_PROP, name)
    _set_flag(doc, AUTO_PLACE, on)
    _trees_soon()


def _views_folder(doc, make=False):
    """The part's Annotations group (mbd.py's), which keeps the inserted views."""
    if doc is None:
        return None
    for o in doc.Objects:
        if o.TypeId == "App::DocumentObjectGroup" and o.Label == "Annotations":
            return o
    if make:
        from . import mbd
        return mbd._folder(doc)
    return None


def inserted_views(doc):
    g = _views_folder(doc)
    return [str(v) for v in (getattr(g, VIEWS_PROP, []) or [])] if g is not None else []


def view_key(name):
    return VIEW_ORDER.index(name) if name in VIEW_ORDER else len(VIEW_ORDER) - 1


def _trees_soon():
    try:
        from PySide import QtWidgets as _W
        for tree in Gui.getMainWindow().findChildren(_W.QTreeView, "SWFeatureTree"):
            m = tree.model()
            if hasattr(m, "soon"):
                m.soon()
    except Exception as _fw_err:
        _fw_log("treevirtual.py:trees-soon", _fw_err)


def put_in_view(doc, name, annotations):
    """Insert Annotation View's OK: the view is kept in the Annotations folder, the picked annotations move in."""
    g = _views_folder(doc, make=True)
    if VIEWS_PROP not in g.PropertiesList:
        g.addProperty("App::PropertyStringList", VIEWS_PROP, "Annotations", "Annotation views inserted in the part")
        try:
            g.setEditorMode(VIEWS_PROP, 2)
        except Exception as _fw_err:
            _fw_log("treevirtual.py:views-hide", _fw_err)
    have = inserted_views(doc)
    if name not in have:
        g.SWAnnotationViews = have + [name]
    for a in annotations:
        if VIEW_PROP not in a.PropertiesList:
            a.addProperty("App::PropertyString", VIEW_PROP, "PMI", "The annotation view it is in")
            try:
                a.setEditorMode(VIEW_PROP, 2)
            except Exception as _fw_err:
                _fw_log("treevirtual.py:view-hide", _fw_err)
        setattr(a, VIEW_PROP, name)
    _trees_soon()


class AnnotationViewPanel:
    ""


    def __init__(self, doc):
        from PySide import QtCore, QtWidgets as W
        self.doc = doc
        box = W.QWidget()
        box.setWindowTitle("Orientation")
        box.setObjectName("SWAnnotationViewOrientation")
        box.setProperty("swstyle_pm_title", "Annotation View")
        lay = W.QVBoxLayout(box)
        self.std = W.QRadioButton("Standard views")
        self.std.setChecked(True)
        lay.addWidget(self.std)
        self.views = W.QListWidget()
        self.views.setObjectName("SWAnnotationViewList")
        self.views.addItems([n for n, _d in STANDARD_VIEWS])
        self.views.setCurrentRow(0)
        self.views.setMaximumHeight(120)
        lay.addWidget(self.views)
        pick = W.QWidget()
        pick.setWindowTitle("Annotations")
        pick.setObjectName("SWAnnotationViewAnnotations")
        lay2 = W.QVBoxLayout(pick)
        lay2.addWidget(W.QLabel("Annotations to move into the view"))
        self.picked = W.QListWidget()
        self.picked.setObjectName("SWAnnotationViewPicked")
        self.picked.setProperty("swpickbox", True)
        self.picked.setMaximumHeight(90)
        lay2.addWidget(self.picked)
        self.form = [box, pick]
        self.items = []
        for o in Gui.Selection.getSelection(doc.Name):
            self._add(o)
        Gui.Selection.addObserver(self)

    def _add(self, o):
        if view_of(o) is not None and o not in self.items:
            self.items.append(o)
            self.picked.addItem(o.Label)

    def addSelection(self, doc, name, sub, pnt):
        if doc == self.doc.Name:
            self._add(self.doc.getObject(name))

    def getStandardButtons(self):
        from PySide import QtWidgets as W
        return W.QDialogButtonBox.Ok | W.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("treevirtual.py:view-panel-close", _fw_err)
        Gui.Control.closeDialog()

    def accept(self):
        item = self.views.currentItem()
        name = item.text() if item is not None else STANDARD_VIEWS[0][0]
        self.doc.openTransaction("Annotation View")
        try:
            put_in_view(self.doc, name, self.items)
        finally:
            self.doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        self._close()
        return True


def insert_annotation_view(doc):
    if doc is None:
        return None
    panel = AnnotationViewPanel(doc)
    Gui.Control.showDialog(panel)
    return panel
