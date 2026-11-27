# SPDX-License-Identifier: LGPL-2.1-or-later
""




from .. import editobj

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
from PySide import QtCore

SKETCH = "Sketcher::SketchObject"
PLANES = ("App::Plane", "PartDesign::Plane", "App::Origin")


def can_start():
    """Whether a tool button should be live with no sketch open."""
    if App.ActiveDocument is None or Gui.ActiveDocument is None:
        return False
    try:
        return not Gui.Control.activeDialog()   # a bool in FreeCAD 1.1
    except Exception as _fw_err:
        _fw_log("fwsketch/sketchfirst.py:36", _fw_err)
        return False


def flat_face(obj, sub):
    if not sub.startswith("Face"):
        return False
    try:
        face = obj.Shape.getElement(sub)
        return face.Surface.TypeId == "Part::GeomPlane" if hasattr(face.Surface, "TypeId") \
            else type(face.Surface).__name__ == "Plane"
    except Exception as _fw_err:
        _fw_log("fwsketch/sketchfirst.py:48", _fw_err)
        return False


def then_command(command, tries=600):
    ""


    def go(left=[tries], idle=[0]):
        gdoc = Gui.ActiveDocument
        try:
            edit = gdoc.getInEdit() if gdoc is not None else None
        except Exception:
            edit = None
        if edit is not None and editobj.type_id(edit) == SKETCH:
            Gui.runCommand(command, 0)
            return
        try:
            asking = bool(Gui.Control.activeDialog())
        except Exception:
            asking = False
        idle[0] = 0 if asking else idle[0] + 1
        if idle[0] >= 3:
            App.Console.PrintLog("FreeCAD: %s dropped, the plane pick was closed\n" % command)
            return
        if left[0] > 0:
            left[0] -= 1
            QtCore.QTimer.singleShot(100, go)
    QtCore.QTimer.singleShot(100, go)


def sketch_on(obj, sub):
    """A new sketch on plane obj or flat face (obj, sub), opened for editing."""
    doc = obj.Document
    body = None
    try:
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
    except Exception as _fw_err:
        _fw_log("fwsketch/sketchfirst.py:83", _fw_err)
    if body is None:
        for parent in obj.InList:
            if parent.TypeId == "PartDesign::Body":
                body = parent
                break

    # and PartDesign's New Sketch do (PC undo check 11-19: it was made outside any step and stayed)
    doc.openTransaction("Sketch on Face" if sub else "Create a new sketch")
    try:
        if body is not None:
            sketch = body.newObject(SKETCH, "Sketch")
        else:
            sketch = doc.addObject(SKETCH, "Sketch")
        sketch.AttachmentSupport = [(obj, sub)] if sub else [(obj, "")]
        sketch.MapMode = "FlatFace"
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        raise
    doc.recompute()
    Gui.Selection.clearSelection()
    Gui.ActiveDocument.setEdit(sketch.Name)
    return sketch


def start_sketch_then(command):
    """Returns True when something was started for command."""
    if not can_start():
        return False
    try:
        selection = Gui.Selection.getSelectionEx()
    except Exception:
        selection = []
    if selection:
        entry = selection[-1]
        obj = entry.Object
        subs = [s for s in entry.SubElementNames if s]
        sub = subs[-1] if subs else ""
        if obj.TypeId == SKETCH and not sub:          # a sketch picked: edit it
            Gui.Selection.clearSelection()
            Gui.ActiveDocument.setEdit(obj.Name)
            then_command(command)
            return True
        if (obj.TypeId in PLANES and not sub) or flat_face(obj, sub):
            sketch_on(obj, sub)
            then_command(command)
            return True
    # ask for the plane: the add-on's picker when it is there, else FreeCAD's own flow
    try:
        from swstyle import sketchstart
        body = sketchstart._body()
        if body is not None:
            Gui.Selection.clearSelection()
            Gui.Control.showDialog(sketchstart.PlanePicker(body, message=getattr(sketchstart, "DRAW_MESSAGE", None),
                                                           tool=command))
            then_command(command)
            return True
    except Exception as _fw_err:
        _fw_log("fwsketch/sketchfirst.py:134", _fw_err)
    Gui.Selection.clearSelection()
    body = None
    try:
        view = Gui.ActiveDocument.ActiveView
        body = view.getActiveObject("pdbody")
        if body is None:   # the document's only Body becomes the active one, as PartDesign does
            bodies = [o for o in App.ActiveDocument.Objects if o.TypeId == "PartDesign::Body"]
            if len(bodies) == 1:
                view.setActiveObject("pdbody", bodies[0])
                body = bodies[0]
    except Exception as _fw_err:
        _fw_log("fwsketch/sketchfirst.py:146", _fw_err)
    # with a Body, PartDesign's new sketch lists the planes to pick in the task panel; without one
    # the Sketcher's orientation box asks
    Gui.runCommand("PartDesign_NewSketch" if body is not None else "Sketcher_NewSketch", 0)
    then_command(command)
    return True
