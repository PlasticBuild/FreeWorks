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

# ExternalGeometry first: the relations may point at external geometry
PROPERTIES = ("ExternalGeometry", "ExternalGeo", "Geometry", "Constraints")


def is_sketch(obj):
    try:
        return obj is not None and obj.isDerivedFrom("Sketcher::SketchObject")
    except Exception as _fw_err:
        _fw_log("sketchexit.py:35", _fw_err)
        return False


def signature(sketch):
    """What the user can change in a sketch, to compare. FreeCAD's saved form carries a time
    stamp, and ExternalGeo is rebuilt from the external references when the sketch opens."""
    return ([g.Content for g in sketch.Geometry], [c.Content for c in sketch.Constraints],
            [(o.Name, tuple(subs)) for o, subs in sketch.ExternalGeometry])


def sketch_in_edit():
    gdoc = Gui.ActiveDocument
    vp = gdoc.getInEdit() if gdoc is not None else None
    obj = getattr(vp, "Object", None)
    return obj if is_sketch(obj) else None


class Snapshot:
    """A sketch's content when its editing began."""

    def __init__(self, sketch):
        self.doc = sketch.Document
        self.name = sketch.Name
        self.properties = [p for p in PROPERTIES if p in sketch.PropertiesList]
        self.saved = {p: sketch.dumpPropertyContent(p) for p in self.properties}
        self.signature = signature(sketch)
        self.empty = not sketch.Geometry and not sketch.Constraints and not sketch.ExternalGeometry

    def sketch(self):
        try:
            return self.doc.getObject(self.name)
        except Exception as _fw_err:  # the document was closed
            _fw_log("sketchexit.py:68", _fw_err)
            return None

    def changed(self):
        obj = self.sketch()
        if obj is None:
            return False
        return signature(obj) != self.signature

    def restore(self):
        obj = self.sketch()
        # No relation may point at geometry that is not back yet
        obj.Constraints = []
        for p in self.properties:
            obj.restorePropertyContent(p, self.saved[p])


class Watcher:
    """A FreeCAD GUI document observer: saves a sketch's content as its editing starts."""

    def __init__(self):
        self.snapshot = None

    def slotInEdit(self, vp):
        obj = getattr(vp, "Object", None)
        if not is_sketch(obj):
            return
        try:
            self.snapshot = Snapshot(obj)
        except Exception as error:
            self.snapshot = None
            App.Console.PrintWarning("FreeCAD: could not save %s for Discard: %s\n" % (obj.Name, error))

    def slotResetEdit(self, vp):
        self.snapshot = None

    def ready(self):
        """The snapshot of the sketch being edited, or None (opened before the style was on)."""
        snap = self.snapshot
        obj = sketch_in_edit()
        if snap is None or obj is None or snap.sketch() is not obj:
            return None
        return snap


def ask(parent, label):
    ""
    box = QtWidgets.QMessageBox(parent)
    box.setObjectName("SWDiscardSketch")
    box.setIcon(QtWidgets.QMessageBox.Warning)
    box.setWindowTitle("Exit Sketch")
    box.setText("Discard the changes to %s and exit the sketch?" % label)
    box.setInformativeText("Undo brings them back.")
    discard = box.addButton("Discard Changes", QtWidgets.QMessageBox.DestructiveRole)
    keep = box.addButton("Keep Editing", QtWidgets.QMessageBox.RejectRole)
    box.setDefaultButton(keep)
    box.setEscapeButton(keep)
    box.exec()
    return box.clickedButton() is discard


def _delete(doc, name):
    obj = doc.getObject(name)
    if obj is None:
        return
    doc.openTransaction("Discard sketch")
    try:
        for parent in obj.InList:
            if parent.TypeId == "PartDesign::Body":
                parent.removeObject(obj)
        doc.removeObject(name)
        doc.commitTransaction()
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintWarning("FreeCAD: could not delete sketch %s: %s\n" % (name, error))


def discard(watcher, parent=None, confirm=True):
    """Exits the sketch being edited without keeping its changes. Returns True when it closed."""
    snap = watcher.ready() if watcher is not None else None
    if snap is None:
        return False
    obj = snap.sketch()
    changed = snap.changed()
    if changed and confirm and not ask(parent or Gui.getMainWindow(), obj.Label):
        return False
    doc, name = snap.doc, snap.name
    try:
        from . import holewizard     # the features thread's Hole Wizard places a Hole when its sketch closes
        holewizard.forget(name)
    except Exception as _fw_err:
        _fw_log("sketchexit.py:156", _fw_err)
    Gui.runCommand("Sketcher_LeaveSketch", 0)
    if sketch_in_edit() is not None:
        return False                 # the sketch refused to close: leave everything as it is
    if snap.empty:
        _delete(doc, name)
    elif changed:
        doc.openTransaction("Discard sketch changes")
        try:
            snap.restore()
            doc.commitTransaction()
        except Exception as error:
            doc.abortTransaction()
            App.Console.PrintError("FreeCAD: could not discard the changes to %s: %s\n" % (name, error))
        doc.recompute()
    return True
