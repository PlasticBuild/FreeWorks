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

SKETCH = "Sketcher::SketchObject"
CONTINUE = "Continue (Ignore Error)"
STOP = "Stop and Repair"
TEXT = ("Feature %s has %s, which may cause subsequent features to fail. Would you like to "
        "repair %s before FreeCAD rebuilds the subsequent features?")
ROLLBACK_TIP = ("The part has been rolled back to the feature with the error. After fixing the "
                "error, right-click this bar and choose 'Roll To End' to rebuild the rest of the part.")

answer = None       # checks: CONTINUE or STOP answers the prompt without showing it
asked = []          # (sketch name, text) of each prompt, for checks
_observer = None


def problem(sketch):
    """'an error', 'a warning' or None for a sketch after its rebuild."""
    try:
        if sketch.ConflictingConstraints or sketch.MalformedConstraints:
            return "an error"
        if sketch.RedundantConstraints:
            return "a warning"
        if "Invalid" in sketch.State:
            return "an error"
    except Exception as _fw_err:
        _fw_log("stoprepair.py:60", _fw_err)
    return None


def feature_problem(obj):
    """'an error' or None for a feature (not a sketch) after its rebuild."""
    try:
        if obj.TypeId == SKETCH:
            return problem(obj)
        if "Invalid" in obj.State or "Error" in obj.State or not obj.isValid():
            return "an error"
    except Exception as _fw_err:
        _fw_log("stoprepair.py:72", _fw_err)
    return None


def _asks(obj):
    """Only model features ask (not groups, origins, datum helpers or document objects)."""
    try:
        if obj.TypeId == SKETCH:
            return True
        if obj.isDerivedFrom("PartDesign::Body") or obj.isDerivedFrom("App::Part") or \
                obj.isDerivedFrom("App::DocumentObjectGroup") or obj.isDerivedFrom("App::Origin") or \
                obj.isDerivedFrom("App::OriginFeature"):
            return False
        return obj.isDerivedFrom("PartDesign::Feature") or obj.isDerivedFrom("Part::Feature")
    except Exception:
        return False


QUIET = frozenset(("Label", "Label2", "Visibility", "Shape", "Placement", "ExpressionEngine", "Group", "_Body"))
_ASKS = {}      # TypeId -> _asks (one answer per type: the observer runs on every property change)


def _asks_cached(obj):
    try:
        kind = obj.TypeId
    except Exception:
        return False
    found = _ASKS.get(kind)
    if found is None:
        found = _ASKS[kind] = _asks(obj)
    return found


def built_on(sketch):
    """The features that use the sketch (not groups such as the body that holds it)."""
    out = []
    for obj in sketch.InList:
        try:
            if obj.isDerivedFrom("PartDesign::Body") or obj.isDerivedFrom("App::Part") \
                    or obj.isDerivedFrom("App::DocumentObjectGroup"):
                continue
        except Exception:
            continue
        out.append(obj)
    return out


def message(sketch, kind):
    return TEXT % (sketch.Label, kind, sketch.Label)


def ask(sketch, kind):
    """True for Stop and Repair."""
    text = message(sketch, kind)
    asked.append((sketch.Name, text))
    if answer is not None:
        return answer == STOP
    box = QtWidgets.QMessageBox(Gui.getMainWindow())
    box.setObjectName("SWStopAndRepair")
    box.setWindowTitle("FreeCAD")
    box.setIcon(QtWidgets.QMessageBox.Warning)
    box.setText(text)
    go = box.addButton(CONTINUE, QtWidgets.QMessageBox.AcceptRole)
    stop = box.addButton(STOP, QtWidgets.QMessageBox.RejectRole)
    box.setDefaultButton(go)
    box.setEscapeButton(go)
    box.exec()
    return box.clickedButton() is stop


def stop_and_repair(sketch):
    """Rolls the part back above the first feature built on the sketch and opens What's Wrong."""
    from . import rollbackbar, whatswrong
    doc = sketch.Document
    rolled = False
    users = built_on(sketch)
    by_order = {obj.Name: i for i, obj in enumerate(doc.Objects)}
    for feature in sorted(users, key=lambda o: by_order.get(o.Name, 0)):
        if rollbackbar.can_roll_back(feature):
            rolled = rollbackbar.roll_back_to(feature)
            if rolled:
                rollbackbar.mark_error_roll(rollbackbar.body_of(feature))
            break
    whatswrong.show(doc)
    return rolled


def _rolled_back(obj):
    ""
    try:
        from . import editguard
        return editguard.rolled_back(obj)
    except Exception:
        return False


def _mend(doc, obj):
    ""


    try:
        from . import rebuildretry, persistrefs
        lost = rebuildretry.lost_names(doc)
        if obj.TypeId == SKETCH or obj not in lost:
            return False
        key = (doc.Name, obj.Name)
        if _tried.get(key) == (rebuildretry._sign(lost), _EDITS[0]):
            return False        # tried on this very model and it did not mend: not again every rebuild
        persistrefs.after_rebuild(doc)
        if obj in rebuildretry.lost_names(doc):
            rebuildretry.retry(doc)
        lost = rebuildretry.lost_names(doc)
        if obj in lost:
            _tried[key] = (rebuildretry._sign(lost), _EDITS[0])
        else:
            _tried.pop(key, None)
        return True
    except Exception:
        return False


_told = {}       # (document, feature) -> the trouble the question was last asked about

# of a failed feature): no edit by the user, so no reason to ask the same question once more
OWN = frozenset(("Base", "Profile", "AttachmentSupport", "Support", "AddSubShape", "SuppressedShape", "PreviewShape"))


def _trouble(obj, kind):
    try:
        return "%s: %s" % (kind, obj.getStatusString())
    except Exception:
        return kind


def _still_wrong(doc):
    """Forget the features that rebuild again: when one fails later, that is a new error."""
    for key in [k for k in _told if k[0] == doc.Name]:
        obj = doc.getObject(key[1])
        if obj is None or not feature_problem(obj):
            _told.pop(key, None)


_tried = {}      # (document, feature) -> (the failures, the edit count) a mend was tried on
_EDITS = [0]     # property changes outside a rebuild (an edit can make a mend work that did not before)


def after_recompute(doc, names):
    """The prompt for the first rebuilt sketch with a problem that other features are built on."""
    from . import whatswrong
    if not whatswrong.show_every_rebuild():
        return None
    try:
        gdoc = Gui.getDocument(doc.Name)
        if gdoc is not None and gdoc.getInEdit() is not None:
            return None
    except Exception as _fw_err:
        _fw_log("stoprepair.py:207", _fw_err)
    _still_wrong(doc)
    order = {o.Name: i for i, o in enumerate(doc.Objects)}
    for name in sorted(names, key=lambda n: order.get(n, 0)):     # the first error in the tree asks
        sketch = doc.getObject(name)
        if sketch is None or _rolled_back(sketch):
            continue
        kind = feature_problem(sketch)
        if kind and _mend(doc, sketch):
            kind = feature_problem(sketch)
        if kind and built_on(sketch):

            # feature stays as it is (What's Wrong still lists it). A change of the feature itself
            # that leaves it failing asks again (the observer forgets it then).
            trouble = _trouble(sketch, kind)
            if _told.get((doc.Name, name)) == trouble:
                continue
            _told[(doc.Name, name)] = trouble
            if ask(sketch, kind):
                stop_and_repair(sketch)
            return sketch
    return None


EDITS = frozenset(("Geometry", "Constraints", "ExternalGeometry", "AttachmentSupport", "MapMode", "AttachmentOffset"))


class _Observer:
    """Asks about a sketch once per change of it: a sketch that fails stays due for a rebuild, and
    the rollback's own rebuild would otherwise ask again."""

    def __init__(self):
        self.touched = {}
        self.changed = set()        # (document, sketch) edited since the last question
        self.busy = False
        self.computing = set()      # documents in a recompute: a sketch's solver rewrites its own geometry

    def slotChangedObject(self, obj, prop):
        # runs on every property change of every object (70k calls in a 301-part build): the cheap
        # tests first, then one answer per type
        if prop in QUIET:
            return
        try:
            doc = obj.Document.Name
            if doc in self.computing:
                return
            if not self.busy:
                _EDITS[0] += 1
            if obj.TypeId == SKETCH:
                if prop in EDITS:
                    self.changed.add((doc, obj.Name))
                    if not self.busy and prop not in OWN:
                        _told.pop((doc, obj.Name), None)
            elif _asks_cached(obj):
                self.changed.add((doc, obj.Name))
                if not self.busy and prop not in OWN:
                    _told.pop((doc, obj.Name), None)        # the user's own change: a failure asks again
        except Exception as _fw_err:
            _fw_log("stoprepair.py:252", _fw_err)

    def slotDeletedDocument(self, doc):
        for key in [k for k in _told if k[0] == doc.Name]:
            _told.pop(key, None)

    def slotStartRestoreDocument(self, doc):
        self.computing.add(doc.Name)        # opening a file is no edit of its sketches

    def slotFinishRestoreDocument(self, doc):
        self.computing.discard(doc.Name)

    def slotBeforeRecomputeDocument(self, doc):
        self.computing.add(doc.Name)
        if self.busy:
            return
        try:
            self.touched[doc.Name] = [o.Name for o in doc.Objects if (doc.Name, o.Name) in self.changed]
        except Exception:
            self.touched[doc.Name] = []
        for name in self.touched[doc.Name]:
            self.changed.discard((doc.Name, name))

    def slotRecomputedDocument(self, doc):
        self.computing.discard(doc.Name)
        names = self.touched.pop(doc.Name, [])
        if names:
            # after FreeCAD has finished: a dialog inside its recompute would run it again
            QtCore.QTimer.singleShot(0, lambda d=doc.Name, n=names: _later(d, n))


def _later(doc_name, names):
    _observer.busy = True           # the rollback rebuilds the part: not a new question
    try:
        if doc_name in App.listDocuments():
            after_recompute(App.getDocument(doc_name), names)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Stop and Repair: %s\n" % error)
    finally:
        _observer.busy = False


def install():
    global _observer
    if _observer is None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)
        # FreeCAD 1.1 sends no restore signals to Python: restorehook reports opened files instead
        from . import restorehook
        restorehook.on_restored(_observer.slotFinishRestoreDocument)
