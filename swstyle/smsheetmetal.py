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

from . import naming

LABEL = "Sheet-Metal"
FOLDER = "Sheet-Metal"
GROUP = "Sheet Metal"
ICON = "SheetMetal_AddBase"


def _root(body):
    from . import smbaseflange
    return next((o for o in body.Group if smbaseflange.is_base_flange(o)), None)


def feature_of(body):
    return next((o for o in body.Document.Objects if type(getattr(o, "Proxy", None)).__name__ == "SWSheetMetal"
                 and o.Body is body), None)


class SWSheetMetal:
    def __init__(self, obj, body):
        obj.addProperty("App::PropertyLink", "Body", GROUP, "The sheet metal part")
        obj.setEditorMode("Body", 1)
        obj.Body = body
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderSheetMetal:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        from .smunfold import _icon
        return _icon(ICON)

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        return edit(vobj.Object)

    def unsetEdit(self, vobj, mode=0):
        return False

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def setupContextMenu(self, vobj, menu):
        a = menu.addAction("Edit Feature")
        a.triggered.connect(lambda: Gui.ActiveDocument.setEdit(vobj.Object.Name, 0))

    def dumps(self):
        return None

    def loads(self, state):
        return None


def ensure(body):
    """The part's Sheet-Metal folder and Sheet-Metal1, made when missing."""
    if _root(body) is None:
        return None
    obj = feature_of(body)
    if obj is not None:
        return obj
    doc = body.Document
    folder = doc.addObject("App::DocumentObjectGroup", "SheetMetalFolder")
    folder.Label = naming.next_label(doc, FOLDER) if any(o.Label == FOLDER for o in doc.Objects) else FOLDER
    obj = doc.addObject("App::FeaturePython", "SheetMetal")
    SWSheetMetal(obj, body)
    obj.Label = naming.next_label(doc, LABEL)
    if App.GuiUp:
        ViewProviderSheetMetal(obj.ViewObject)
    folder.addObject(obj)
    try:
        from . import smcutlist
        smcutlist.update(doc, compute=False)        # Cut list(1) with Sheet<1>, filled when flattened
    except Exception as e:
        App.Console.PrintWarning("Sheet metal cut list: %s\n" % e)
    return obj


def _bends(body, root):
    return [o for o in body.Group if o is not root]


def carry(body, root, old, new):
    """Bends and Tabs still on the old defaults take the new ones."""
    from . import smbaseflange
    from .smedgeflange import RELIEF_TYPES
    exprs = lambda o: {p for p, _e in o.ExpressionEngine}
    for o in _bends(body, root):
        if smbaseflange.is_base_flange(o) and abs(o.Thickness.Value - old["t"]) < 1e-9:
            o.Thickness = new["t"]
        if "radius" in o.PropertiesList and "radius" not in exprs(o) and abs(o.radius.Value - old["r"]) < 1e-9:
            o.radius = new["r"]
        if "reliefType" in o.PropertiesList and old["relief"] != new["relief"]:
            was = RELIEF_TYPES.get(old["relief"])
            if was and o.reliefType == was and RELIEF_TYPES.get(new["relief"]):
                o.reliefType = RELIEF_TYPES[new["relief"]]
        if "ReliefFactor" in o.PropertiesList and abs(o.ReliefFactor - old["ratio"]) < 1e-9:
            o.ReliefFactor = new["ratio"]


def _values(root):
    return {"t": root.Thickness.Value, "r": root.Radius.Value, "relief": root.SWAutoRelief,
            "ratio": root.SWReliefRatio}


def panel_class():
    from . import smbaseflange

    class Panel(smbaseflange.Panel):
        """The Sheet-Metal PropertyManager: the Base Flange's sheet metal boxes, for the whole part."""

        def __init__(self, feature):
            self.feature = feature
            root = _root(feature.Body)
            smbaseflange._add_sw_props(root)
            self.old = _values(root)
            root.Document.openTransaction("Edit " + feature.Label)
            try:
                super().__init__(root, False)
                self.part_thickness = None              # the part's own thickness: never greyed here
                self.busy = True
                self._show()
                self.busy = False
                self.radius.setVisible(True)
                self.radius_label.setVisible(True)
                boxes = [b for b in self._all_boxes if b.windowTitle() in (
                    "Sheet Metal Parameters From Material", "Sheet Metal Gauges", "Sheet Metal Parameters",
                    "Bend Allowance", "Auto Relief")]
                for b in boxes:
                    if b.windowTitle() == "Sheet Metal Parameters":
                        b.setWindowTitle("Bend Parameters")
                        self._fixed_row(b)
                for b in self._all_boxes:
                    b.setProperty("swstyle_pm_title", None)
                boxes[0].setProperty("swstyle_pm_title", feature.Label)
                boxes[0].setProperty("swstyle_pm_icon", ICON)
                self.form = boxes
            except BaseException:
                try:
                    root.Document.abortTransaction()
                except Exception:
                    pass
                raise

        def _fixed_row(self, box):
            from .smunfold import _list
            self.fixed = _list("SWSMSheetFixed", "#d6ecff", "Fixed face or edge: stays where it is in the flat pattern")
            if "FixedNormal" in self.obj.PropertiesList and self.obj.FixedNormal.Length > 1e-9:
                self.fixed.addItem("Face <1>")
            box.layout().insertRow(0, QtWidgets.QLabel("Fixed face or edge:"))
            box.layout().insertRow(1, self.fixed)

        def _picked(self, doc_name, name, sub):
            o = App.getDocument(doc_name).getObject(name)
            if o is None or not sub.startswith("Face"):
                return
            f = o.Shape.getElement(sub)
            if f.Surface.TypeId != "Part::GeomPlane":
                return
            from .smnormalcut import inside_point
            root = self.obj
            if "FixedNormal" not in root.PropertiesList:
                root.addProperty("App::PropertyVector", "FixedNormal", GROUP, "Fixed face normal")
                root.addProperty("App::PropertyVector", "FixedPoint", GROUP, "A point on the fixed face")
            root.FixedNormal, root.FixedPoint = f.normalAt(0, 0), inside_point(f)
            self.fixed.clear()
            self.fixed.addItem("Face <1>")
            try:
                Gui.Selection.clearSelection()
            except Exception as _fw_err:
                _fw_log("smsheetmetal.py:205", _fw_err)

        def _changed(self, *args):
            super()._changed(*args)
            if not self.busy and not self.open_profile and abs(self.obj.Radius.Value - self.radius.value()) > 1e-12:
                self.obj.Radius = self.radius.value()      # a flat plate keeps the part's bend radius too
                self.obj.Document.recompute()

        def accept(self):
            root = self.obj
            self._changed()
            if not self._report():
                return False
            carry(self.feature.Body, root, self.old, _values(root))
            root.Document.recompute()
            root.Document.commitTransaction()
            self._close()
            return True

    return Panel


def edit(feature):
    if feature.Body is None or _root(feature.Body) is None:
        return None
    Gui.Control.closeDialog()
    Gui.Control.showDialog(panel_class()(feature))
    return True
