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

from . import advancedhole, directfeatures, holelegacy, holeoptions, holeslot, holewizard, material, moveface, naming, paths, patterns, previewstyle, refrepair, rib
from . import sketchstart, suppress, thread



naming.install()
sketchstart.install()
previewstyle.install()
refrepair.install()
material.install()
rib.register()
suppress.register()
thread.register()
moveface.register()
directfeatures.register()
patterns.register()
advancedhole.register()
holeoptions.register()
holeslot.register()
holelegacy.register()
from . import liveplane
liveplane.register()

# Features that consume the sketch that was open when they were started.
SKETCH_FEATURES = {
    "PartDesign_Pad", "PartDesign_Pocket", "PartDesign_Revolution", "PartDesign_Groove",
    "PartDesign_AdditivePipe", "PartDesign_SubtractivePipe",
    "PartDesign_AdditiveLoft", "PartDesign_SubtractiveLoft",
    "PartDesign_AdditiveHelix", "PartDesign_SubtractiveHelix", "PartDesign_Hole",
    rib.COMMAND,
}
# Sketch features that "Use fully defined sketches" applies to (the Hole Wizard places its own points)
FULLY_DEFINED_PARAM = "UseFullyDefinedSketches"
NEEDS_DEFINED = SKETCH_FEATURES - {"PartDesign_Hole"}
# Features that work on the solid and start from the current selection or none.
SOLID_FEATURES = {
    "PartDesign_Fillet", "PartDesign_Chamfer", "PartDesign_Draft", "PartDesign_Thickness",
    "PartDesign_Mirrored", "PartDesign_LinearPattern", "PartDesign_PolarPattern",
    "PartDesign_MultiTransform", "PartDesign_Scaled", "PartDesign_Boolean",
    "PartDesign_Plane", "PartDesign_Line", "PartDesign_Point", "PartDesign_CoordinateSystem",
}
FEATURES = SKETCH_FEATURES | SOLID_FEATURES
ALL_EDGES = {"PartDesign_Fillet", "PartDesign_Chamfer"}
# Dress-ups that need faces picked inside the command; a whole body means "start empty".
FACE_DRESSUPS = {"PartDesign_Draft", "PartDesign_Thickness"}



# open and a click exits that sketch, the same as Exit Sketch; FreeCAD greys PartDesign_NewSketch there.
SKETCH_TOGGLE = ("PartDesign_NewSketch", "Sketcher_NewSketch")


def handles(native):
    return native in FEATURES or sketchstart.handles(native) or sketchstart.is_draw_tool(native)


def editing_sketch():
    try:
        gdoc = Gui.ActiveDocument
        edit = gdoc.getInEdit() if gdoc is not None else None
        if edit is not None and edit.Object.TypeId == "Sketcher::SketchObject":
            return edit.Object
    except Exception as _fw_err:
        _fw_log("featureflow.py:96", _fw_err)
    return None


def enabled(native):
    """True when only an open sketch stops the native command from running,
    or for a drawing tool that will start its own sketch."""
    if native in SKETCH_TOGGLE and editing_sketch() is not None:
        return True
    if sketchstart.draw_enabled(native):
        return True
    if sketchstart.waiting() is not None and _takes_over(native):
        return True
    if native not in FEATURES and editing_sketch() is not None and leaves_sketch(native):
        return True
    if native not in FEATURES or editing_sketch() is None:
        return False
    try:
        return bool(Gui.Command.get(native).isActive())
    except Exception:
        return False


def _is_empty(sketch):
    return not sketch.Geometry and not sketch.ExternalGeometry


def _discard(doc, name):
    obj = doc.getObject(name)
    if obj is None:
        return

    # two steps (make, delete) and Ctrl+Z brought the empty sketch back: when the newest step is the
    # one that made it (taking it back leaves everything else as it is), that step is taken back.
    try:
        others = sorted(o.Name for o in doc.Objects if o.Name != name)
        if doc.UndoCount and not getattr(doc, "HasPendingTransaction", False):
            doc.undo()
            if doc.getObject(name) is None and sorted(o.Name for o in doc.Objects) == others:
                return
            doc.redo()
    except Exception as _fw_err:
        _fw_log("featureflow.py:discard-undo", _fw_err)
    if doc.getObject(name) is None:
        return
    obj = doc.getObject(name)
    doc.openTransaction("Delete empty sketch")
    try:
        for parent in obj.InList:
            if parent.TypeId == "PartDesign::Body":
                parent.removeObject(obj)
        doc.removeObject(name)
        doc.commitTransaction()
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintWarning("FreeCAD: could not delete empty sketch %s (%s)\n" % (name, error))


def _body_to_tip(native):
    ""




    if native not in ALL_EDGES and native not in FACE_DRESSUPS:
        return
    try:
        selection = Gui.Selection.getSelectionEx()
    except Exception:
        return
    if len(selection) != 1 or selection[0].SubElementNames:
        return
    body = selection[0].Object
    if body.TypeId != "PartDesign::Body" or body.Tip is None:
        return
    Gui.Selection.clearSelection()
    if native in ALL_EDGES:
        Gui.Selection.addSelection(body.Tip)


def _selected_sketches():
    try:
        return [s.Object for s in Gui.Selection.getSelectionEx()
                if s.Object.TypeId == "Sketcher::SketchObject"]
    except Exception:
        return []


def _under_defined(sketches):
    out = []
    for sketch in sketches:
        try:
            sketch.solve()
            if not sketch.FullyConstrained:
                out.append(sketch)
        except Exception as _fw_err:
            _fw_log("featureflow.py:173", _fw_err)
    return out


def refuses(native, sketches):
    """Use fully defined sketches: tell why and return True when a sketch is under defined."""
    if native not in NEEDS_DEFINED or not paths.params().GetBool(FULLY_DEFINED_PARAM, False):
        return False
    loose = _under_defined(sketches)
    if not loose:
        return False
    names = ", ".join(s.Label for s in loose)
    QtWidgets.QMessageBox.warning(
        Gui.getMainWindow(), "Sketch not fully defined",
        "%s is under defined. Features can only use fully defined sketches.\n\n"
        "Add dimensions or relations until the sketch is fully defined, or turn off "
        "Options > Sketch > Use fully defined sketches." % names)
    return True


def _takes_over(native):
    return native in FEATURES or sketchstart.handles(native) or sketchstart.is_draw_tool(native)


def _replace_picker(native):
    ""

    picker = sketchstart.waiting()
    if picker is None or not _takes_over(native):
        return False
    same = picker.feature == native or (sketchstart.handles(native) and picker.feature is None and
                                       picker.on_face is None and picker.tool is None)
    if same:
        return True             # that very command is already waiting for its plane
    picker.reject()

    def go(tries=[20]):
        try:
            busy = bool(Gui.Control.activeDialog())
        except Exception:
            busy = False
        if busy and tries[0] > 0:
            tries[0] -= 1
            QtCore.QTimer.singleShot(100, go)
            return
        if not run(native):
            Gui.runCommand(native, 0)
    QtCore.QTimer.singleShot(100, go)
    return True


def run(native):
    ""
    if native in SKETCH_TOGGLE and editing_sketch() is not None:
        Gui.runCommand("Sketcher_LeaveSketch", 0)       # rcmenus pkg269: the Sketch button toggles the sketch off
        return True
    if _replace_picker(native):
        return True
    if sketchstart.handles(native):
        return sketchstart.run(native)
    if native == "PartDesign_Pocket":
        from . import wecut     # a weldment: the cut goes through the members (commands pkg185)
        if wecut.run():
            return True
    if native == "PartDesign_Chamfer":
        from . import wechamfer     # a weldment: member edges (commands pkg186)
        if wechamfer.run():
            return True
    if sketchstart.is_draw_tool(native):
        return sketchstart.run_draw(native)
    if native not in FEATURES and editing_sketch() is not None and leaves_sketch(native):
        return _leave_sketch_then(native)       # extapps78
    if native not in FEATURES:
        return False
    sketch = editing_sketch()
    used = [sketch] if sketch is not None and not _is_empty(sketch) else _selected_sketches()
    try:        # Options > Sketch > Prompt to close sketch (fwsketch thread, fix57)
        from .fwsketch import sketchclose
        sketchclose.ask(native, used)
    except Exception as _fw_err:
        _fw_log("featureflow.py:248", _fw_err)
    if refuses(native, used):
        return True
    if sketch is None:
        if holewizard.handles(native) and holewizard.run(native):
            return True
        if sketchstart.run_feature(native):
            return True
        from . import sweeploftpm
        if sweeploftpm.run_first(native):
            return True
        _body_to_tip(native)
        return False
    doc, name, empty = sketch.Document, sketch.Name, _is_empty(sketch)
    holewizard.forget(name)
    rib.forget_sketch(name)
    sketchstart.forget_resume(doc.Name, name)
    Gui.runCommand("Sketcher_LeaveSketch", 0)
    if editing_sketch() is not None:
        return True  # The sketch refused to close; leave everything as it is.
    Gui.Selection.clearSelection()
    if empty:
        _discard(doc, name)
    elif native in SKETCH_FEATURES:
        Gui.Selection.addSelection(doc.getObject(name))
    # Let the closed sketch's task panel go before the feature opens its own.
    _start_when_free(native)
    return True


# --------------------------------------------------------------- extapps78: Insert features from a sketch

# and starts the feature. Our feature commands refuse while any task dialog is open, and the sketch is one.
_INSERT = {}
_NOT_FROM_SKETCH = {"Sketch", "Sketch3D", "Sketch3DOnPlane", "DerivedSketch", "cmd:SWStyle_SketchFromDrawing",
                    "cmd:SWStyle_ExplodeLineSketch"}
# features that take the closed sketch as their input: it stays picked, as for Extrude
_SKETCH_INPUT = {"SM_SketchedBend", "Wrap", "SketchDrivenPattern", "SplitLine", "ProjectedCurve", "WE_StructuralMember"}


def _insert_natives():
    """{command: catalog key} of the part's Insert menu, without the sketch entries."""
    if "all" in _INSERT:
        return _INSERT["all"]
    found = {}
    try:
        from . import catalog, swmenus

        def walk(entries):
            for entry in entries:
                if entry == swmenus.S:
                    continue
                target = entry if isinstance(entry, str) else entry[1]
                if isinstance(target, (tuple, list)):
                    walk(target)
                    continue
                if target in _NOT_FROM_SKETCH or target.startswith("fn:") or target.startswith("when:"):
                    continue
                if target.startswith("cmd:"):
                    for name in target[4:].split("|"):
                        found.setdefault(name, target)
                elif target in catalog.BY_KEY:
                    for name in catalog.BY_KEY[target].natives:
                        found.setdefault(name, target)
        for entry in swmenus.INSERT[1]:
            if not isinstance(entry, str) and entry[0] == "when:part":
                walk(entry[1])
    except Exception as _fw_err:
        _fw_log("featureflow.py:insert", _fw_err)
    found = dict((n, k) for n, k in found.items() if not n.startswith("Sketcher_") and n not in FEATURES)
    _INSERT["all"] = found
    return found


class _NoDialog:
    """Gui.Control as a command sees it once the sketch is closed: no task dialog open."""

    def __init__(self, real):
        self._real = real

    def activeDialog(self):
        return False

    def __getattr__(self, name):
        return getattr(self._real, name)


def _active(native):
    try:
        c = Gui.Command.get(native)
        return c is not None and bool(c.isActive())
    except Exception:
        return False


def _active_without_sketch(native):
    """The command's own IsActive with the sketch's task dialog out of the way. Anything else it checks (a solid
    to act on, a picked face...) still counts, so a feature with nothing to act on stays greyed."""
    real = Gui.Control
    try:
        Gui.Control = _NoDialog(real)
        return _active(native)
    finally:
        Gui.Control = real


def leaves_sketch(native):
    """True for a part Insert command that only the open sketch keeps from running."""
    if not native or native not in _insert_natives():
        return False
    try:
        dialog = Gui.Control.activeDialog()
    except Exception:
        dialog = False
    if not dialog or _active(native):
        return False
    return _active_without_sketch(native)


def _leave_sketch_then(native):
    """Closes the open sketch the way a featureflow feature does (Prompt to close sketch, an empty sketch left
    out), then starts native. True: handled here."""
    sketch = editing_sketch()
    if sketch is None:
        return False
    used = [sketch] if not _is_empty(sketch) else []
    try:
        from .fwsketch import sketchclose
        sketchclose.ask(native, used)
    except Exception as _fw_err:
        _fw_log("featureflow.py:leave-ask", _fw_err)
    doc, name, empty = sketch.Document, sketch.Name, _is_empty(sketch)
    holewizard.forget(name)
    rib.forget_sketch(name)
    sketchstart.forget_resume(doc.Name, name)
    Gui.runCommand("Sketcher_LeaveSketch", 0)
    if editing_sketch() is not None:
        return True  # The sketch refused to close; leave everything as it is.
    Gui.Selection.clearSelection()
    if empty:
        _discard(doc, name)
    elif _insert_natives().get(native) in _SKETCH_INPUT:
        Gui.Selection.addSelection(doc.getObject(name))
    _start_when_free(native)
    return True


def _start_when_free(native, tries=20):
    """pkg108: the feature command runs once the sketch's task panel is really gone (on the PC a
    0 ms timer still found it there and FreeCAD crashed in the new command, pmsw2 Helix Boss);
    checked every 100 ms, two seconds at most."""
    def go():
        try:
            busy = bool(Gui.Control.activeDialog()) or editing_sketch() is not None
        except Exception:
            busy = False
        if busy and tries > 0:
            _start_when_free(native, tries - 1)
            return
        Gui.runCommand(native, 0)
    QtCore.QTimer.singleShot(100, go)
