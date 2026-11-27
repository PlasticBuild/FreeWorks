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
from PySide import QtCore, QtGui, QtWidgets

try:
    from pivy import coin
except ImportError:  # No Coin bindings: fall back to FreeCAD's own origin planes.
    coin = None

NATIVE = "PartDesign_NewSketch"
PLANES = {"App::Plane", "PartDesign::Plane"}
SKETCH = "Sketcher::SketchObject"



DEFAULT_PLANES = (
    ("Front Plane", "XZ_Plane", (0, 2)),
    ("Top Plane", "XY_Plane", (0, 1)),
    ("Right Plane", "YZ_Plane", (1, 2)),
)
PLANE_FILL = (0.62, 0.72, 0.86)
PLANE_EDGE = (0.30, 0.42, 0.62)
HOVER_FILL = (1.00, 0.62, 0.20)
HOVER_EDGE = (0.95, 0.45, 0.05)

_active = None


# Sketch tools that draw: clicked with no sketch open they ask for a plane or

DRAW_EXCLUDE = {"Sketcher_CreateFillet", "Sketcher_CreateChamfer"}

FEATURE_MESSAGE = ("Select:\n"
                   "1) A plane or a planar face on which to sketch the feature cross-section.\n"
                   "2) An existing sketch to use for the feature.")

FEATURES = {
    "PartDesign_Pad": ("Boss-Extrude", "FEATURES_EXTRUDE_BOSS"),
    "PartDesign_Pocket": ("Cut-Extrude", "FEATURES_EXTRUDE_CUT"),
    "PartDesign_Revolution": ("Revolve", "FEATURES_REVOLVED_BOSS_BASE"),
    "PartDesign_Groove": ("Cut-Revolve", "FEATURES_REVOLVED_CUT"),
    "PartDesign_AdditiveHelix": ("Helix Boss", "FEATURES_SWEPT_BOSS"),      # sweep: pkg92
    "PartDesign_SubtractiveHelix": ("Helix Cut", "FEATURES_SWEPT_CUT"),
}
DRAW_MESSAGE = ("Select a plane or a flat face on which to create a sketch "
                "for the entity, or an existing sketch.")


def handles(native):
    return native == NATIVE



FREEWORKS_NOT_DRAWN = ("FreeWorks_Trim", "FreeWorks_Extend", "FreeWorks_Split", "FreeWorks_Fillet", "FreeWorks_Chamfer", "FreeWorks_Offset",
                       "FreeWorks_Mirror", "FreeWorks_Convert", "FreeWorks_Sketch")


def _sheet_in_front():
    """A drawing sheet (TechDraw page) window is the active one."""
    try:
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        sw = mdi.activeSubWindow() if mdi is not None else None
        w = sw.widget() if sw is not None else None
        return w is not None and "MDIViewPage" in w.metaObject().className()
    except Exception as _fw_err:
        _fw_log("sketchstart.py:95", _fw_err)
        return False


def is_draw_tool(native):
    if not native or native in DRAW_EXCLUDE:
        return False
    if native.startswith(("FreeWorks_Draw", "FreeWorks_TDX_")):
        return False            # drawing commands (sheet tools, BOM, Note, tables, Drawing Tools): no part sketch

    if native.startswith("FreeWorks_"):
        return not native.startswith(FREEWORKS_NOT_DRAWN)
    return native.startswith("Sketcher_Create")


def draw_enabled(native):
    """A drawing tool with no sketch open: live, it starts a sketch first."""
    if not is_draw_tool(native) or App.ActiveDocument is None or _sheet_in_front():
        return False
    try:
        if Gui.Control.activeDialog():
            return False
        gdoc = Gui.ActiveDocument
        return gdoc is not None and gdoc.getInEdit() is None
    except Exception as _fw_err:
        _fw_log("sketchstart.py:119", _fw_err)
        return False


def run_draw(native):
    """Line, Rectangle... with no sketch open. Returns True when handled here."""
    if not draw_enabled(native):
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
        if obj.TypeId == SKETCH and not sub:
            Gui.Selection.clearSelection()
            Gui.ActiveDocument.setEdit(obj.Name)
            _then_tool(native)
            return True
        if (obj.TypeId in PLANES and not sub) or (sub.startswith("Face") and _is_flat(obj, sub)):
            _sketch_on(obj, sub, native)
            return True
        Gui.Selection.clearSelection()  # Not something to sketch on: ask.
    body = _body()
    if body is None:
        return False
    Gui.Control.showDialog(PlanePicker(body, message=DRAW_MESSAGE, tool=native))
    return True


def run_feature(native):
    ""



    if native not in FEATURES or App.ActiveDocument is None:
        return False
    try:
        if Gui.Control.activeDialog():
            return False
        gdoc = Gui.ActiveDocument
        if gdoc is None or gdoc.getInEdit() is not None:
            return False
        selection = Gui.Selection.getSelectionEx()
    except Exception:
        return False
    if selection:

        # and follows when the sketch closes (FreeCAD would take the whole face as the profile:
        # ChatGPT 2A02, E12 mounting hole). Anything else picked is FreeCAD's own start.
        entry = selection[-1]
        obj = entry.Object
        subs = [s for s in entry.SubElementNames if s]
        sub = subs[-1] if subs else ""
        if len(selection) == 1 and len(subs) <= 1 and \
                ((obj.TypeId in PLANES and not sub) or (sub.startswith("Face") and _is_flat(obj, sub))):
            _sketch_on(obj, sub)
            _then_feature(native)
            return True
        return False
    body = _body()
    if body is None:
        return False
    title, icon = FEATURES[native]
    Gui.Control.showDialog(PlanePicker(body, title=title, icon=icon, message=FEATURE_MESSAGE, feature=native))
    return True


def forget_resume(doc_name, name):
    """The feature was started by hand while the sketch was open: nothing to go on with."""
    if _empty is not None:
        _empty.resume.pop((doc_name, name), None)


def _feature_on(sketch, feature):
    """The feature on a sketch, as FreeCAD starts it on a picked sketch."""
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(sketch.Document.Name, sketch.Name)
    Gui.runCommand(feature, 0)


def _then_feature(feature):
    """Once the new sketch is open, remember to start feature when it is closed."""
    def go(tries=[0]):
        gdoc = Gui.ActiveDocument
        edit = gdoc.getInEdit() if gdoc is not None else None
        if edit is not None and editobj.type_id(edit) == SKETCH:
            if _empty is not None:
                _empty.resume[(editobj.of(edit).Document.Name, getattr(editobj.of(edit), "Name", None))] = feature
        elif tries[0] < 20:
            tries[0] += 1
            QtCore.QTimer.singleShot(100, go)
    QtCore.QTimer.singleShot(100, go)


def _sketch_on(obj, sub, tool=None):
    """New sketch on a plane or flat face, then the tool if one is given."""
    doc = obj.Document.Name
    Gui.Selection.clearSelection()
    if sub:
        Gui.Selection.addSelection(doc, obj.Name, sub)
    else:
        Gui.Selection.addSelection(doc, obj.Name)
    Gui.runCommand(NATIVE, 0)
    if tool:
        _then_tool(tool)


def _then_tool(tool):
    """Start tool once the sketch is open (the edit starts a moment later)."""
    def go(tries=[0]):
        gdoc = Gui.ActiveDocument
        edit = gdoc.getInEdit() if gdoc is not None else None
        if edit is not None and editobj.type_id(edit) == SKETCH:
            Gui.runCommand(tool, 0)
        elif tries[0] < 20:
            tries[0] += 1
            QtCore.QTimer.singleShot(100, go)
    QtCore.QTimer.singleShot(100, go)


def run(native):
    """Returns True when the pick mode was started here."""
    if native != NATIVE or App.ActiveDocument is None:
        return False
    try:        # assemblies: a part edited in context with another component's face picked
        from . import asmextref
        if asmextref.toolbar_sketch():
            return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: in-context sketch: %s\n" % error)
    try:
        if Gui.Control.activeDialog():
            return False
        gdoc = Gui.ActiveDocument
        if gdoc is not None and gdoc.getInEdit() is not None:
            return False
        if Gui.Selection.getSelectionEx():
            if not _only_curved_faces():
                return False  # Something picked first: FreeCAD starts on it directly.

            # for a plane or planar face (no "No planar support" error box).
            Gui.Selection.clearSelection()
    except Exception:
        return False
    body = _body()
    if body is None:
        return False
    panel = PlanePicker(body)
    Gui.Control.showDialog(panel)
    return True


def _only_curved_faces():
    """The selection is faces only, and none of them is flat (a cylinder's side, a fillet...)."""
    faces = 0
    for sel in Gui.Selection.getSelectionEx():
        names = sel.SubElementNames
        if not names:
            return False
        for name in names:
            if not name.startswith("Face"):
                return False
            try:
                face = sel.Object.getSubObject(name)
                if face.findPlane() is not None:
                    return False
            except Exception:
                return False
            faces += 1
    return faces > 0


def waiting():
    """The plane/face picker PropertyManager while it is still waiting (nothing started yet)."""
    p = _active
    try:
        if p is not None and not p.done and p._alive() and Gui.Control.activeDialog():
            return p
    except Exception as _fw_err:
        _fw_log("sketchstart.py:275", _fw_err)
    return None


def view3d():
    """The active document's 3D view: its active view, or its first 3D view when the active one is
    not (a command started from a menu while a drawing or another window has the focus)."""
    gdoc = Gui.ActiveDocument
    if gdoc is None:
        return None
    view = gdoc.ActiveView
    if view is not None and hasattr(view, "getSceneGraph"):
        return view
    try:
        for v in gdoc.mdiViewsOfType("Gui::View3DInventor"):
            if hasattr(v, "getSceneGraph"):
                return v
    except Exception as _fw_err:
        _fw_log("sketchstart.py:293", _fw_err)
    return None


def _body():
    """The active body; the only body is made active, a part with none gets one."""
    doc = App.ActiveDocument
    view = view3d()
    try:
        body = view.getActiveObject("pdbody") if view is not None else None
    except Exception:
        body = None
    if body is not None:
        return body
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    if len(bodies) == 1:
        try:
            view.setActiveObject("pdbody", bodies[0])
        except Exception as _fw_err:
            _fw_log("sketchstart.py:312", _fw_err)
        return bodies[0]
    if not bodies:
        _BEFORE[doc.Name] = {o.Name for o in doc.Objects}
        Gui.runCommand("PartDesign_Body", 0)
        try:
            body = view.getActiveObject("pdbody")
            if body is not None:
                _FRESH_BODIES.add((doc.Name, body.Name))     # pkg432: made only for this sketch
            return body
        except Exception as _fw_err:
            _fw_log("sketchstart.py:322", _fw_err)
            return None
    return None  # Several bodies and none active: let FreeCAD ask.


def _is_flat(obj, sub):
    try:
        face = obj.Shape.getElement(sub)
    except Exception as _fw_err:
        _fw_log("sketchstart.py:331", _fw_err)
        return False
    if face.ShapeType != "Face":
        return False
    if type(face.Surface).__name__ == "Plane":
        return True
    try:
        return face.findPlane() is not None
    except Exception as _fw_err:
        _fw_log("sketchstart.py:340", _fw_err)
        return False


_FRESH_BODIES = set()       # (document, body) made by _body() for a new sketch (pkg432)
_BEFORE = {}                # document -> its objects before that body was made


def discard(doc, name):
    ""


    obj = doc.getObject(name)
    bodies = [p.Name for p in obj.InList if p.TypeId == "PartDesign::Body"] if obj is not None else []
    _discard_sketch(doc, name)
    for body in bodies:
        _drop_fresh_body(doc, body)


def _drop_fresh_body(doc, name):
    key = (doc.Name, name)
    body = doc.getObject(name)
    if key not in _FRESH_BODIES or body is None:
        return
    if body.Group:
        _FRESH_BODIES.discard(key)          # something was made in it: a real body now
        return
    _FRESH_BODIES.discard(key)
    keep = sorted(o.Name for o in doc.Objects if o.Name != name and o not in body.OutListRecursive)
    try:
        if doc.UndoCount and not getattr(doc, "HasPendingTransaction", False):
            doc.undo()                      # the newest step made the body: take it back
            if doc.getObject(name) is None and sorted(o.Name for o in doc.Objects) == keep:
                _drop_folders(doc)
                return
            doc.redo()
    except Exception as _fw_err:
        _fw_log("sketchstart.py:body-undo", _fw_err)
    body = doc.getObject(name)
    if body is None:
        _drop_folders(doc)
        return
    doc.openTransaction("Delete empty body")
    try:
        body.removeObjectsFromDocument()
        doc.removeObject(name)
        _drop_folders(doc)
        doc.commitTransaction()
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintWarning("FreeCAD: could not delete empty body %s (%s)\n" % (name, error))


def _drop_folders(doc):
    """The tree's own rows made with the body (Solid Bodies, Material: App::FeaturePython, used by
    nothing) go with it; a document that had no body before shows none of them."""
    before = _BEFORE.pop(doc.Name, None)
    if before is None:
        return
    for obj in list(doc.Objects):
        try:
            if obj.Name not in before and obj.TypeId == "App::FeaturePython" and not obj.InList:
                doc.removeObject(obj.Name)
        except Exception as _fw_err:
            _fw_log("sketchstart.py:drop-folders", _fw_err)


def _discard_sketch(doc, name):
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
        _fw_log("sketchstart.py:discard-undo", _fw_err)
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


def _blank(sketch):
    if sketch.Geometry or sketch.ExternalGeometry or sketch.Constraints:
        return False
    if any(getattr(o, "SWSketch", None) is sketch for o in sketch.Document.Objects
           if o.TypeId == "Image::ImagePlane"):
        return False
    return all(parent.TypeId == "PartDesign::Body" for parent in sketch.InList)


class _EmptySketches:
    """Sketches made in this session that may still be thrown away when their edit ends."""

    def __init__(self):
        self.fresh = set()      # (document, name)
        self.resume = {}        # (document, name) -> feature to start once the sketch closes

    # App observer
    def slotCreatedObject(self, obj):
        if obj.TypeId == SKETCH and not getattr(obj.Document, "Restoring", False):
            self.fresh.add((obj.Document.Name, obj.Name))

    def slotDeletedObject(self, obj):
        try:
            # the Gui side passes a view provider (its Document is a Gui.Document with no Name); the App side the object
            doc = obj.Document
            name = getattr(doc, "Name", None) or getattr(getattr(doc, "Document", None), "Name", None)
            if name:
                self.fresh.discard((name, obj.Name))
        except Exception as _fw_err:
            _fw_log("sketchstart.py:380", _fw_err)

    # Gui observer
    def slotResetEdit(self, view_provider):
        try:
            obj = view_provider.Object
            key = (obj.Document.Name, obj.Name)
        except Exception:
            return
        if key in self.fresh or key in self.resume:
            # Not while FreeCAD is still closing the edit
            QtCore.QTimer.singleShot(0, lambda: self._check(*key))

    def _check(self, doc_name, name):
        doc = App.listDocuments().get(doc_name)
        sketch = doc.getObject(name) if doc is not None else None
        if sketch is None:
            self.fresh.discard((doc_name, name))
            self.resume.pop((doc_name, name), None)
            return
        try:
            gdoc = Gui.getDocument(doc_name)
            edit = gdoc.getInEdit() if gdoc is not None else None
            if edit is not None and editobj.of(edit) == sketch:
                return
        except Exception as _fw_err:
            _fw_log("sketchstart.py:406", _fw_err)
        feature = self.resume.pop((doc_name, name), None)
        if _blank(sketch):
            if (doc_name, name) in self.fresh:
                discard(doc, name)
        else:
            self.fresh.discard((doc_name, name))   # it has content: a real sketch from now on
            if feature and not Gui.Control.activeDialog():
                _feature_on(sketch, feature)


_empty = None


def install():
    """Start throwing away new sketches that are left empty. Safe to call more than once."""
    global _empty
    if not getattr(App, "GuiUp", False) or not hasattr(Gui, "addDocumentObserver"):
        return      # FreeCADCmd (console mode): no sketches to edit, and a headless import must not fail
    if _empty is None:
        _empty = _EmptySketches()
        App.addDocumentObserver(_empty)
        Gui.addDocumentObserver(_empty)


class _Observer:
    def __init__(self, picker):
        self.picker = picker

    def addSelection(self, doc, obj, sub, pnt):
        QtCore.QTimer.singleShot(0, self.picker.picked)


MESSAGE = ("Select:\n"
           "1) A plane or a flat face on which to create a sketch.\n"
           "2) An existing sketch to edit.")


class PlanePicker:
    """The "Edit Sketch" PropertyManager that waits for a plane or face.

    Other features reuse it (the Hole Wizard asks for a face): planes=False
    takes flat faces only, and on_face(obj, sub) replaces the sketch start.
    """

    def __init__(self, body, title="Edit Sketch", icon="SKETCH_SKETCH",
                 message=MESSAGE, planes=True, on_face=None, tool=None, feature=None):
        self.body = body
        self.feature = feature  # feature to start on the picked sketch, or after the new one closes
        self.planes = planes
        self.on_face = on_face
        self.tool = tool  # sketch tool to start once the sketch is open
        self.done = False
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Message")
        # Read by propertymanager.py for the title row.
        self.form.setProperty("swstyle_pm_title", title)
        self.form.setProperty("swstyle_pm_icon", icon)
        layout = QtWidgets.QVBoxLayout(self.form)
        layout.setContentsMargins(4, 4, 4, 4)
        text = QtWidgets.QLabel(message)
        text.setWordWrap(True)
        layout.addWidget(text)
        self.error = QtWidgets.QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c00000;")
        self.error.hide()
        layout.addWidget(self.error)
        self._saved = []
        self._show_planes()
        self.observer = _Observer(self)
        Gui.Selection.addObserver(self.observer)
        self._cleaned = False
        # closed from outside (Gui.Control.closeDialog() by another command or a script) runs neither
        # reject() nor accept(): the planes would stay drawn and the origin shown, so the next Zoom to
        # Fit zooms out to them
        self.form.destroyed.connect(lambda *args: self._cleanup())
        global _active
        _active = self

    # ---------------------------------------------------------------- planes
    def _show_planes(self):
        self.overlay = None
        if not self.planes:
            return
        if coin is None:
            self._show_origin()
            return
        try:
            self.overlay = PlaneOverlay(self.body, self._plane_picked)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: plane display failed (%s)\n" % error)
            self.overlay = None
            self._show_origin()
        self._frame_planes()

    def _frame_planes(self):
        ""


        try:
            shape = self.body.Shape
            if not shape.isNull() and shape.Volume > 1e-9:
                return
            view3d().fitAll()
        except Exception as _fw_err:
            _fw_log("sketchstart.py:510", _fw_err)

    def _show_origin(self):
        origin = getattr(self.body, "Origin", None)
        if origin is None:
            return
        for obj in [origin] + list(getattr(origin, "OriginFeatures", []) or []):
            vobj = getattr(obj, "ViewObject", None)
            if vobj is None:
                continue
            self._saved.append((obj, vobj.Visibility))
            try:
                vobj.Visibility = obj is origin or obj.TypeId in PLANES
            except Exception as _fw_err:
                _fw_log("sketchstart.py:524", _fw_err)

    def _restore_planes(self):
        if getattr(self, "overlay", None) is not None:
            self.overlay.remove()
            self.overlay = None
        for obj, visible in reversed(self._saved):
            try:
                obj.ViewObject.Visibility = visible
            except Exception as _fw_err:
                _fw_log("sketchstart.py:534", _fw_err)
        self._saved = []

    def _plane_picked(self, plane):
        if not self.done:
            self._start(plane, "")

    # ---------------------------------------------------------------- picks
    def _alive(self):
        """False once the page's widgets are gone (closed any way, document closed)."""
        try:
            import shiboken6 as shiboken
        except ImportError:
            import shiboken2 as shiboken
        try:
            return shiboken.isValid(self.form) and shiboken.isValid(self.error)
        except Exception:
            return False

    def picked(self):
        if self.done:
            return
        if not self._alive():
            # The page went without _finish (its panel was closed from outside): stop listening.
            self.done = True
            self._cleanup()
            return
        try:
            selection = Gui.Selection.getSelectionEx()
        except Exception:
            return
        if not selection:
            return
        entry = selection[-1]
        obj = entry.Object
        subs = [s for s in entry.SubElementNames if s]
        sub = subs[-1] if subs else ""
        if self.planes and obj.TypeId == SKETCH and not sub.startswith("Face") and self.feature:
            feature = self.feature
            self._finish(lambda: _feature_on(obj, feature))
            return
        if self.planes and obj.TypeId == SKETCH and not sub.startswith("Face"):
            tool = self.tool

            def edit():
                Gui.Selection.clearSelection()
                Gui.ActiveDocument.setEdit(obj.Name)
                if tool:
                    _then_tool(tool)
            self._finish(edit)
            return
        if self.planes and obj.TypeId in PLANES and not sub:
            self._start(obj, "")
            return
        if sub.startswith("Face") and _is_flat(obj, sub):
            self._start(obj, sub)
            return
        Gui.Selection.clearSelection()
        self.error.setText("That is not flat. Pick a plane, a flat face or a sketch."
                           if self.planes else "That is not flat. Pick a flat face.")
        self.error.show()

    def _start(self, obj, sub):
        if self.on_face is not None:
            self._finish(lambda: self.on_face(obj, sub))
            return
        tool, feature = self.tool, self.feature

        def start():
            _sketch_on(obj, sub, tool)
            if feature:
                _then_feature(feature)
        self._finish(start)

    def _finish(self, then):
        self.done = True
        self._cleanup()
        Gui.Control.closeDialog()
        QtCore.QTimer.singleShot(0, then)

    def _cleanup(self):
        global _active
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("sketchstart.py:622", _fw_err)
        self._restore_planes()
        if _active is self:
            _active = None

    # ---------------------------------------------------------------- dialog
    def getStandardButtons(self):
        cancel = QtWidgets.QDialogButtonBox.Cancel
        try:
            return int(cancel)
        except TypeError:
            return cancel.value

    def reject(self):
        self.done = True
        self._cleanup()
        Gui.Control.closeDialog()
        # pkg432: Cancel / Esc before a plane was picked: a body made only for this sketch goes too
        try:
            body = self.body
            doc = body.Document if body is not None else None
            if doc is not None:
                name = body.Name
                QtCore.QTimer.singleShot(0, lambda: _drop_fresh_body(doc, name))
        except Exception as _fw_err:
            _fw_log("sketchstart.py:reject-body", _fw_err)
        return True

    def accept(self):
        return self.reject()


class PlaneOverlay:
    ""






    def __init__(self, body, on_pick):
        self.body = body
        self.on_pick = on_pick
        self.view = view3d()
        if self.view is None:
            raise RuntimeError("no 3D view")
        self.hover = None
        self.planes = []  # (name, origin feature, corners, normal axis, fill mat, edge mat)
        features = {}
        for obj in getattr(body.Origin, "OriginFeatures", []) or []:
            features[getattr(obj, "Role", obj.Name)] = obj
        self.root = coin.SoSeparator()
        style = coin.SoPickStyle()
        style.style = coin.SoPickStyle.UNPICKABLE
        self.root.addChild(style)
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        self.root.addChild(light)
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
        hints.shapeType = coin.SoShapeHints.UNKNOWN_SHAPE_TYPE
        self.root.addChild(hints)
        lo, hi = self._extent()
        for name, role, (u, v) in DEFAULT_PLANES:
            feature = features.get(role)
            if feature is None:
                continue
            corners = []
            for a, b in ((lo[u], lo[v]), (hi[u], lo[v]), (hi[u], hi[v]), (lo[u], hi[v])):
                point = [0.0, 0.0, 0.0]
                point[u], point[v] = a, b
                corners.append(tuple(point))
            normal = 3 - u - v
            fill, edge = self._node(corners, name)
            self.planes.append((name, feature, corners, normal, (u, v), fill, edge))
        self.view.getSceneGraph().addChild(self.root)
        self.callbacks = [
            (coin.SoMouseButtonEvent.getClassTypeId(), self._click),
            (coin.SoLocation2Event.getClassTypeId(), self._move),
        ]
        for kind, callback in self.callbacks:
            self.view.addEventCallbackPivy(kind, callback)

    # ------------------------------------------------------------ geometry
    def _extent(self):
        """Box the planes span: the part plus a margin, always around the origin."""
        lo, hi = [-25.0] * 3, [25.0] * 3
        try:
            box = self.body.Shape.BoundBox
            if box.isValid() and box.DiagonalLength > 1e-6:
                margin = 0.12 * box.DiagonalLength
                lo = [min(box.XMin, 0.0) - margin, min(box.YMin, 0.0) - margin, min(box.ZMin, 0.0) - margin]
                hi = [max(box.XMax, 0.0) + margin, max(box.YMax, 0.0) + margin, max(box.ZMax, 0.0) + margin]
        except Exception as _fw_err:
            _fw_log("sketchstart.py:707", _fw_err)
        return lo, hi

    def _node(self, corners, name=""):
        sep = coin.SoSeparator()
        fill = coin.SoMaterial()
        fill.diffuseColor.setValue(*PLANE_FILL)
        fill.transparency.setValue(0.78)
        sep.addChild(fill)
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, 4, corners)
        sep.addChild(coords)
        face = coin.SoFaceSet()
        face.numVertices.setValue(4)
        sep.addChild(face)
        edge = coin.SoMaterial()
        edge.diffuseColor.setValue(*PLANE_EDGE)
        sep.addChild(edge)
        draw = coin.SoDrawStyle()
        draw.lineWidth.setValue(1.5)
        sep.addChild(draw)
        outline = coin.SoCoordinate3()
        outline.point.setValues(0, 5, corners + [corners[0]])
        sep.addChild(outline)
        line = coin.SoLineSet()
        line.numVertices.setValue(5)
        sep.addChild(line)
        if name:

            label = coin.SoSeparator()
            move = coin.SoTranslation()
            move.translation.setValue(*corners[3])
            label.addChild(move)
            font = coin.SoFont()
            font.size.setValue(14)
            label.addChild(font)
            text = coin.SoText2()
            text.string.setValue("  " + name)
            label.addChild(text)
            sep.addChild(label)
        self.root.addChild(sep)
        return fill, edge

    def _ray(self, pos):
        """(origin, direction) of the line of sight under a view position."""
        point = self.view.getPoint(pos[0], pos[1])
        if self.view.getCameraType() == "Perspective":
            cam = self.view.getCameraNode().position.getValue().getValue()
            start = App.Vector(*cam)
            direction = point - start
        else:
            direction = self.view.getViewDirection()
            start = point - direction * 1e6
        if direction.Length < 1e-12:
            return None
        direction.normalize()
        return start, direction

    def _plane_at(self, pos):
        """(distance, plane) of the nearest default plane under the mouse."""
        ray = self._ray(pos)
        if ray is None:
            return None
        start, direction = ray
        best = None
        for plane in self.planes:
            corners, n, (u, v) = plane[2], plane[3], plane[4]
            if abs(direction[n]) < 1e-9:
                continue
            t = -start[n] / direction[n]
            if t <= 0:
                continue
            hit = start + direction * t
            if not (corners[0][u] <= hit[u] <= corners[2][u] and corners[0][v] <= hit[v] <= corners[2][v]):
                continue
            if best is None or t < best[0]:
                best = (t, plane, start)
        return best

    def _model_under(self, pos):
        """True when the part is under the mouse (FreeCAD's own ray pick).

        The planes are unpickable, so a hit here is the part itself; a face
        the mouse is on wins over any plane, in front or behind.
        """
        try:
            viewer = self.view.getViewer()
            region = viewer.getSoRenderManager().getViewportRegion()
            action = coin.SoRayPickAction(region)
            action.setPoint(coin.SbVec2s(int(pos[0]), int(pos[1])))
            action.setRadius(2)
            action.apply(viewer.getSceneGraph())
            if action.getPickedPoint() is not None:
                return True
        except Exception as _fw_err:
            _fw_log("sketchstart.py:802", _fw_err)
        try:
            info = self.view.getObjectInfo((pos[0], pos[1]))
        except Exception:
            info = None
        return bool(info and "x" in info)

    def _target(self, pos):
        """The plane under the mouse, unless the part is there."""
        if self._model_under(pos):
            return None
        found = self._plane_at(pos)
        return found[1] if found is not None else None

    # ------------------------------------------------------------ events
    def _set_hover(self, plane):
        if plane is self.hover:
            return
        for item in self.planes:
            lit = item is plane
            item[5].diffuseColor.setValue(*(HOVER_FILL if lit else PLANE_FILL))
            item[5].transparency.setValue(0.70 if lit else 0.78)
            item[6].diffuseColor.setValue(*(HOVER_EDGE if lit else PLANE_EDGE))
        self.hover = plane
        if plane is not None:
            QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), plane[0])
        else:
            QtWidgets.QToolTip.hideText()

    def _move(self, node):
        try:
            self._set_hover(self._target(node.getEvent().getPosition().getValue()))
        except Exception as _fw_err:
            _fw_log("sketchstart.py:835", _fw_err)

    def _click(self, node):
        event = node.getEvent()
        if not coin.SoMouseButtonEvent.isButtonPressEvent(event, coin.SoMouseButtonEvent.BUTTON1):
            return
        try:
            plane = self._target(event.getPosition().getValue())
        except Exception:
            plane = None
        if plane is None:
            return  # The model is under the mouse: FreeCAD selects the face.
        node.setHandled()
        QtCore.QTimer.singleShot(0, lambda: self.on_pick(plane[1]))

    def remove(self):
        for kind, callback in self.callbacks:
            try:
                self.view.removeEventCallbackPivy(kind, callback)
            except Exception as _fw_err:
                _fw_log("sketchstart.py:855", _fw_err)
        self.callbacks = []
        try:
            self.view.getSceneGraph().removeChild(self.root)
        except Exception as _fw_err:
            _fw_log("sketchstart.py:860", _fw_err)
        QtWidgets.QToolTip.hideText()
