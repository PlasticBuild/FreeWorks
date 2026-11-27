# SPDX-License-Identifier: LGPL-2.1-or-later
""




import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import paths

PARAM = "UndoWording"
HOOKED = "swUndoWordingHooked"
TICK = 1000
COMMANDS = (("Std_Undo", "Undo", "UndoNames"), ("Std_Redo", "Redo", "RedoNames"))

_watch = None
_observer = None


def enabled():
    return paths.params().GetBool(PARAM, True)




NAMES = {
    "Create ActiveView": "Active 3D View",
    "Create BIM view": "BIM View",
    "Create DraftView": "Draft Objects View",
    "Lock/Unlock View": "Toggle View Lock",
}


# features-479: FreeCAD's own feature steps say "Make Pad", "Edit Pocket", "Make AdditivePipe": the undo lists and

# name their steps after their title
FEATURE_WORDS = {
    "Pad": "Boss-Extrude", "Pocket": "Cut-Extrude", "Revolution": "Revolve", "Groove": "Cut-Revolve",
    "AdditivePipe": "Sweep", "SubtractivePipe": "Cut-Sweep", "Pipe": "Sweep",
    "AdditiveLoft": "Loft", "SubtractiveLoft": "Cut-Loft",
    "AdditiveHelix": "Helix Boss", "SubtractiveHelix": "Helix Cut", "Helix": "Helix Boss",
    "Thickness": "Shell", "thickness inwards": "Shell", "Draft": "Draft", "Hole": "Hole",
    "Fillet": "Fillet", "Chamfer": "Chamfer",
    "LinearPattern": "Linear Pattern", "Linear Pattern": "Linear Pattern", "PolarPattern": "Circular Pattern",
    "Polar Pattern": "Circular Pattern", "Mirrored": "Mirror", "Mirror": "Mirror", "MultiTransform": "Pattern",
    "Scaled": "Scale", "Scale": "Scale", "Boolean": "Combine",
}


def _feature_words(text):
    for verb, shown in (("Make ", ""), ("Edit ", "Edit ")):
        if text.startswith(verb):
            word = FEATURE_WORDS.get(text[len(verb):].strip())
            if word:
                return shown + word
    return None



# Edit > "Undo Base Extrude" after the first Boss-Extrude1)
BASE_WORDS = {"Pad": "Base Extrude"}


def _base_step(doc, names, index):
    """True when names[index] (FreeCAD's "Make Pad") made the first solid of its body: the feature that step
    made (the newest one of its kind, counting the newer steps of that kind) builds on nothing."""
    try:
        text = str(names[index] or "").strip()
        if doc is None or not text.startswith("Make ") or text[5:].strip() not in BASE_WORDS:
            return False
        kind = "PartDesign::" + text[5:].strip()
        newer = sum(1 for n in names[:index] if str(n or "").strip() == text)
        made = sorted((o for o in doc.Objects if o.TypeId == kind), key=lambda o: o.ID, reverse=True)
        if newer >= len(made):
            return False
        obj = made[newer]
        body = obj.getParentGeoFeatureGroup()
        return body is not None and getattr(obj, "BaseFeature", None) is None \
            and getattr(body, "BaseFeature", None) is None
    except Exception:
        return False


def display(name, doc=None, names=None, index=0):
    """The name the undo lists show for a step FreeCAD named `name` (doc, names, index: the step's place in
    the document's undo list, for the body's first solid)."""
    text = str(name or "").strip()
    if names is not None and _base_step(doc, names, index):
        return BASE_WORDS[text[5:].strip()]
    return NAMES.get(text) or _feature_words(text) or text


def wording(which, names, doc=None):
    """'&Undo Pad' for the step at the top of `names`, or plain '&Undo' when there is none
    (the & keeps the menu's U / R key)."""
    name = display((names or [""])[0], doc, names if which == "Undo" else None).replace("&", "&&")
    return "&%s %s" % (which, name) if name else "&" + which


def _actions(command):
    try:
        return list(Gui.Command.get(command).getAction())
    except Exception:
        return []


def refresh():
    doc = App.ActiveDocument
    for command, which, attr in COMMANDS:
        names = list(getattr(doc, attr, []) or []) if doc is not None and enabled() else []
        text = wording(which, names, doc)
        for action in _actions(command):
            if action.text() != text:
                action.setText(text)


def _hook():
    try:
        for command, _which, _attr in COMMANDS:
            for action in _actions(command):
                for owner in action.associatedObjects():
                    if isinstance(owner, QtWidgets.QMenu) and not owner.property(HOOKED):
                        owner.setProperty(HOOKED, True)
                        owner.aboutToShow.connect(refresh)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Undo wording not hooked: %s\n" % error)


def _in_edit():
    """A PropertyManager or a sketch is open (its own Undo steps); FreeCAD keeps an active assembly
    "in edit" with neither, which does not count."""
    try:
        if Gui.Control.activeDialog():
            return True
        gdoc = Gui.ActiveDocument
        vp = gdoc.getInEdit() if gdoc is not None else None
        if vp is None:
            return False
        if type(vp).__name__ == "ViewProviderAssembly":
            return False
        return getattr(getattr(vp, "Object", None), "TypeId", "") != "Assembly::AssemblyObject"
    except Exception:
        return False


def settle(doc):
    ""



    try:
        if doc is None or _in_edit() or not enabled():
            return False
        if not (doc.isTouched() or any("Touched" in o.State or "Invalid" in o.State for o in doc.Objects)):
            return False
        doc.recompute()
        return True
    except Exception as error:
        App.Console.PrintLog("Rebuild after Undo skipped: %s\n" % error)
        return False


class _Steps:
    """Keeps the Undo / Redo names current as soon as a step is made, undone or redone (the FreeCAD
    style Edit menu reads them as it opens), and rebuilds after Undo / Redo (settle)."""

    def _later(self, doc=None, rebuild=False):
        name = getattr(doc, "Name", None)

        def run():
            if rebuild and name and App.listDocuments().get(name) is not None:
                settle(App.getDocument(name))
            refresh()
        QtCore.QTimer.singleShot(0, run)

    def slotCommitTransaction(self, doc):
        self._later()

    def slotAbortTransaction(self, doc):
        self._later()

    def slotUndoDocument(self, doc):
        self._later(doc, True)

    def slotRedoDocument(self, doc):
        self._later(doc, True)

    def slotActivateDocument(self, doc):
        self._later()

    def slotDeletedDocument(self, doc):
        self._later()


def install():
    global _watch, _observer
    if _observer is None:
        _observer = _Steps()
        try:
            App.addDocumentObserver(_observer)
        except Exception:
            _observer = None
    if _watch is not None:
        return
    _watch = QtCore.QTimer()
    _watch.setInterval(TICK)
    _watch.timeout.connect(_hook)
    _watch.start()
    _hook()


def remove():
    global _watch, _observer
    if _watch is not None:
        _watch.stop()
    _watch = None
    if _observer is not None:
        try:
            App.removeDocumentObserver(_observer)
        except Exception:
            pass
    _observer = None
