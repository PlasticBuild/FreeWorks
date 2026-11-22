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
    add(("InsertAnnotationView", "Insert Annotation View", lambda: _gui("SWStyle_MBDCapture3DView"), ok))
    auto = ok and _flag(doc, AUTO_PLACE, True)
    add(("AutoPlace", tick(auto, "Automatically Place into Annotation Views"), lambda: _set_flag(doc, AUTO_PLACE, not auto), ok))
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
