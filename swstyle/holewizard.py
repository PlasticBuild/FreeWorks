# SPDX-License-Identifier: LGPL-2.1-or-later
""













from . import editobj

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

from . import holespec, sketchstart

NATIVE = "PartDesign_Hole"
SKETCH = "Sketcher::SketchObject"
MESSAGE = ("Select the flat face for the holes.\n"
           "Then click once for each hole, and exit the sketch when done.")

_pending = {}
_own = set()  # sketch name -> document name, sketches whose close starts a Hole
_specs = {}
_timer = None


def handles(native):
    return native == NATIVE


def forget(name):
    """Another feature took the sketch over: no Hole follows its close."""
    _pending.pop(name, None)
    _specs.pop(name, None)


def run(native):
    """Hole Wizard from the model. Returns True when handled here."""
    if native != NATIVE or App.ActiveDocument is None:
        return False
    try:
        if Gui.Control.activeDialog():
            return False
        gdoc = Gui.ActiveDocument
        if gdoc is not None and gdoc.getInEdit() is not None:
            return False
        selection = Gui.Selection.getSelectionEx()
    except Exception:
        return False
    face = None
    if selection:
        entry = selection[-1]
        subs = [s for s in entry.SubElementNames if s]
        sub = subs[-1] if subs else ""
        if sub.startswith("Face") and placeable(entry.Object, sub):
            face = (entry.Object, sub)
            if entry.PickedPoints:
                note_click(entry.Object, sub, entry.PickedPoints[-1])
        elif entry.Object.TypeId == SKETCH and holespec.enabled():
            sketch = entry.Object
            body = sketchstart._body() or holespec._body_of(sketch)
            if body is None:
                return False
            Gui.Selection.clearSelection()
            holespec.show(body, None, start_on_face, sketch=sketch)
            return True
        elif entry.Object.TypeId == SKETCH or not holespec.enabled():
            return False  # The old order: FreeCAD's own Hole.

    body = sketchstart._body()
    if body is None:
        return False
    if holespec.enabled():
        Gui.Selection.clearSelection()
        holespec.show(body, face, start_on_face)
        return True
    if face is not None:
        start_on_face(*face)
        return True
    picker = sketchstart.PlanePicker(
        body, title="Hole Position", icon="FEATURES_HOLE_WIZARD",
        message=MESSAGE, planes=False, on_face=start_on_face)
    Gui.Control.showDialog(picker)
    return True


def placeable(obj, sub):
    ""

    if sketchstart._is_flat(obj, sub):
        return True
    try:
        face = obj.getSubObject(sub)
        return face is not None and type(face.Surface).__name__ in ("Cylinder", "Cone", "Sphere", "Toroid",
                                                                  "BSplineSurface", "SurfaceOfRevolution")
    except Exception as _fw_err:
        _fw_log("holewizard.py:116", _fw_err)
        return False


def _tangent_sketch(obj, sub):
    """A sketch on the plane tangent to a curved face at the middle of the face, its normal out of the
    face, so a Hole drilled on it goes into the face square to it."""
    face = obj.getSubObject(sub)
    u0, u1, v0, v1 = face.ParameterRange
    u, v = (u0 + u1) / 2.0, (v0 + v1) / 2.0
    point = face.valueAt(u, v)
    normal = face.normalAt(u, v)
    body = sketchstart._body()
    try:
        # the face is in the picked object's coordinates (the document's for a pick through the body or
        # its part); the sketch's placement is in the body's: a moved body or part moved the sketch off it
        up = obj.getParentGeoFeatureGroup()
        rel = body.getGlobalPlacement().inverse().multiply(up.getGlobalPlacement() if up is not None else App.Placement())
        point, normal = rel.multVec(point), rel.Rotation.multVec(normal)
    except Exception as _fw_err:
        _fw_log("holewizard.py:tangent-frame", _fw_err)
    doc = obj.Document
    sketch = body.newObject("Sketcher::SketchObject", "Sketch")
    sketch.MapMode = "Deactivated"
    sketch.Placement = App.Placement(point, App.Rotation(App.Vector(0, 0, 1), normal))
    doc.recompute()
    Gui.getDocument(doc.Name).setEdit(sketch.Name, 0)
    return sketch


_clicks = {}


def note_click(obj, sub, point):
    ""
    _clicks[(obj.Document.Name, obj.Name, sub)] = App.Vector(point)


def _first_point(obj, sub, sketch):
    point = _clicks.pop((obj.Document.Name, obj.Name, sub), None)
    if point is None or sketch is None or sketch.Name not in _own:
        return
    try:
        import Part
        local = sketch.getGlobalPlacement().inverse().multVec(point)
        sketch.addGeometry(Part.Point(App.Vector(local.x, local.y, 0)))
        sketch.Document.recompute()
    except Exception as error:
        App.Console.PrintLog("Hole Wizard first point: %s\n" % error)


def start_on_face(obj, sub, spec=None):
    doc = obj.Document
    if spec is not None:
        _start[doc.Name] = len(doc.UndoNames)   # pkg463: the wizard's steps from here undo as one
    Gui.Selection.clearSelection()
    if obj.TypeId == SKETCH and not sub:
        # Positions with a sketch picked first: that sketch opens (its points are the holes)
        Gui.getDocument(doc.Name).setEdit(obj.Name, 0)
    elif sketchstart._is_flat(obj, sub):
        Gui.Selection.addSelection(doc.Name, obj.Name, sub)
        Gui.runCommand("PartDesign_NewSketch", 0)
    else:
        try:
            _tangent_sketch(obj, sub)
        except Exception as error:
            App.Console.PrintError("Hole Wizard: %s\n" % error)
            return
    sketch = _editing()
    if sketch is None:
        return
    if sketch.Name != obj.Name:
        _own.add(sketch.Name)   # made here: an empty one is discarded on exit
        _first_point(obj, sub, sketch)
    _pending[sketch.Name] = doc.Name
    if spec is not None:
        _specs[sketch.Name] = spec
        Gui.getMainWindow().statusBar().showMessage(
            "Hole Position: click once for each hole, then exit the sketch.", 8000)
    QtCore.QTimer.singleShot(300, lambda: Gui.runCommand("Sketcher_CreatePoint", 0))
    _watch()
    if spec is not None:

        def page(s=sketch, sp=spec):
            try:
                from . import holeposition
                if _editing() is s:
                    holeposition.open_for(s, sp)


                    Gui.runCommand("FreeWorks_Point", 0)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: Hole Position page: %s\n" % error)
        QtCore.QTimer.singleShot(500, page)


_start = {}     # pkg463: document name -> undo depth when the Hole Wizard's position sketch started
_groups = {}    # document name -> {"hole", "extra", "state"}: the last Hole Wizard and its sketch steps


def _one_step(doc, hole, extra):
    ""


    if extra <= 0 or not doc.UndoNames or doc.UndoNames[0] != "Hole Wizard":
        _groups.pop(doc.Name, None)
        return
    _groups[doc.Name] = {"hole": hole.Name, "extra": extra, "state": "done"}
    if not _observer:
        _observer.append(_UndoWatch())
        App.addDocumentObserver(_observer[0])


_observer = []
_busy = []


def _steps(doc_name, kind, count):
    doc = App.listDocuments().get(doc_name)
    if doc is None:
        return
    _busy.append(1)
    try:
        for _i in range(count):
            names = doc.UndoNames if kind == "undo" else doc.RedoNames
            if not names:
                break
            doc.undo() if kind == "undo" else doc.redo()
    except Exception as _fw_err:
        _fw_log("holewizard.py:one-step", _fw_err)
    finally:
        _busy.pop()
    try:
        doc.recompute()
    except Exception as _fw_err:
        _fw_log("holewizard.py:one-step-recompute", _fw_err)


class _UndoWatch:
    def slotUndoDocument(self, doc):
        g = _groups.get(doc.Name)
        if _busy or g is None or g["state"] != "done":
            return
        if not doc.RedoNames or doc.RedoNames[0] != "Hole Wizard" or doc.getObject(g["hole"]) is not None:
            _groups.pop(doc.Name, None)     # another step was undone: the group is gone
            return
        g["state"] = "undone"
        QtCore.QTimer.singleShot(0, lambda n=doc.Name, k=g["extra"]: _steps(n, "undo", k))

    def slotRedoDocument(self, doc):
        g = _groups.get(doc.Name)
        if _busy or g is None or g["state"] != "undone":
            return
        g["state"] = "done"
        QtCore.QTimer.singleShot(0, lambda n=doc.Name, k=g["extra"]: _steps(n, "redo", k))

    def slotDeletedDocument(self, doc):
        _groups.pop(doc.Name, None)
        _start.pop(doc.Name, None)


def _editing():
    try:
        gdoc = Gui.ActiveDocument
        edit = gdoc.getInEdit() if gdoc is not None else None
        if edit is not None and editobj.type_id(edit) == SKETCH:
            return editobj.of(edit)
    except Exception as _fw_err:
        _fw_log("holewizard.py:204", _fw_err)
    return None


def _watch():
    global _timer
    if _timer is None:
        _timer = QtCore.QTimer()
        _timer.setInterval(250)
        _timer.timeout.connect(_tick)
    _timer.start()


def _tick():
    if not _pending:
        _timer.stop()
        return
    editing = _editing()
    editing_name = editing.Name if editing is not None else None
    for name in list(_pending):
        if name == editing_name:
            continue
        doc = App.getDocument(_pending.pop(name))
        spec = _specs.pop(name, None)
        sketch = doc.getObject(name) if doc is not None else None
        if sketch is None:
            continue
        if not sketch.Geometry:
            if name in _own:
                sketchstart.discard(doc, name)
            _own.discard(name)
            continue
        own = name in _own
        _own.discard(name)
        if own and spec is not None:
            endpoint_positions(sketch)
        try:
            if Gui.Control.activeDialog():
                continue  # Something else opened on the sketch already.
        except Exception as _fw_err:
            _fw_log("holewizard.py:244", _fw_err)
        if spec is not None:
            hole = holespec.make(sketch, spec)
            base = _start.pop(doc.Name, None)
            if hole is not None and base is not None:
                _one_step(doc, hole, len(doc.UndoNames) - 1 - base)
            if hole is not None:
                Gui.Selection.clearSelection()
                Gui.Selection.addSelection(hole)
            continue
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(sketch)
        QtCore.QTimer.singleShot(0, lambda: Gui.runCommand(NATIVE, 0))


def endpoint_positions(sketch, tol=1e-6):
    ""



    import Part
    geos = list(sketch.Geometry)
    taken = [App.Vector(g.X, g.Y, 0) for i, g in enumerate(geos)
             if isinstance(g, Part.Point) and not sketch.getConstruction(i)]
    taken += [App.Vector(g.Center) for i, g in enumerate(geos)
              if isinstance(g, Part.Circle) and not sketch.getConstruction(i)]
    arcs, curves = [], []
    for i, g in enumerate(geos):
        if sketch.getConstruction(i) or isinstance(g, (Part.Point, Part.Circle)):
            continue
        if isinstance(g, Part.ArcOfCircle):
            arcs.append(i)
        elif hasattr(g, "StartPoint") and hasattr(g, "EndPoint"):
            curves.append(i)
    arc_ends = []
    for i in arcs:
        arc_ends += [App.Vector(geos[i].StartPoint), App.Vector(geos[i].EndPoint)]
    wanted = [App.Vector(geos[i].Center) for i in arcs]
    for i in curves:
        for p in (App.Vector(geos[i].StartPoint), App.Vector(geos[i].EndPoint)):
            if any((p - q).Length < tol for q in arc_ends):
                continue            # a slot's side meets its end arc there: the arc's centre drills
            wanted.append(p)
    added = 0
    for p in wanted:
        if any((p - q).Length < tol for q in taken):
            continue
        sketch.addGeometry(Part.Point(App.Vector(p.x, p.y, 0)))
        taken.append(p)
        added += 1
    for i in arcs + curves:
        try:
            sketch.setConstruction(i, True)
        except Exception:
            try:
                sketch.toggleConstruction(i)
            except Exception as _fw_err:
                _fw_log("holewizard.py:298", _fw_err)
    if arcs or curves:
        sketch.Document.recompute()
    return added
