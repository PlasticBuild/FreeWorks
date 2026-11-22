# SPDX-License-Identifier: LGPL-2.1-or-later
"""A counter that moves whenever what the view draws could have changed.

The floor reflection and the floor shadow poll the document twice a second. Each poll walked every
object (bounding boxes, scene searches, shape hashes): with 200 parts that was about a quarter of a
core while nothing happened. They now ask generation() first and do the walk only when it moved
(or every FULL_MS anyway, so a change no observer reports is still picked up).

The counter moves on any object created, deleted or recomputed, on a change to a property that
places or shows a shape, on undo, redo, document open/close/switch and edit start/end.
"""
import FreeCAD as App

FULL_MS = 4000
# properties that move, reshape or show/hide what is drawn (document and view provider side)
WATCHED = frozenset(("Shape", "Placement", "Visibility", "Group", "Tip", "BaseFeature", "LinkedObject",
                     "ElementList", "PlacementList", "ScaleList", "VisibilityList", "Scale",
                     "DisplayMode", "ShapeAppearance", "ShapeColor", "DiffuseColor", "Transparency",
                     "ShowInTree", "Selectable", "SelectionStyle", "OnTopWhenSelected"))
_s = {"gen": 0, "installed": False, "app": None, "gui": None}


def bump(*_args):
    _s["gen"] += 1


class _AppWatch:
    def slotChangedObject(self, obj, prop):
        if prop not in WATCHED:
            return
        bump()

    slotCreatedObject = slotDeletedObject = slotRecomputedDocument = bump
    slotUndoDocument = slotRedoDocument = bump
    slotCreatedDocument = slotDeletedDocument = slotActivateDocument = slotFinishRestoreDocument = bump


class _GuiWatch:
    def slotChangedObject(self, vp, prop):
        if prop not in WATCHED:
            return
        bump()

    slotInEdit = slotResetEdit = slotActivatedObject = slotDeletedObject = slotCreatedObject = bump
    slotActivateDocument = bump


def install():
    if _s["installed"]:
        return
    _s["installed"] = True
    try:
        _s["app"] = _AppWatch()
        App.addDocumentObserver(_s["app"])
    except Exception as error:
        App.Console.PrintLog("FreeCAD: scene stamp (document): %s\n" % error)
        _s["app"] = None
    try:
        import FreeCADGui as Gui
        _s["gui"] = _GuiWatch()
        Gui.addDocumentObserver(_s["gui"])
    except Exception as error:
        App.Console.PrintLog("FreeCAD: scene stamp (view): %s\n" % error)
        _s["gui"] = None


def generation():
    """The counter, or None when the observers could not be added (then callers walk every time)."""
    install()
    if _s["app"] is None:
        return None
    return _s["gen"]


class Gate:
    """Tells a poller whether to do its full walk: when key (the counter plus what else it reads) moved,
    the first time, or when FULL_MS passed since the last full walk."""

    def __init__(self):
        self.key, self.at = object(), 0.0

    def due(self, extra=()):
        import time
        gen = generation()
        now = time.monotonic()
        key = (gen,) + tuple(extra)
        if gen is None or key != self.key or now - self.at >= FULL_MS / 1000.0:
            self.key, self.at = key, now
            return True
        return False

    def reset(self):
        self.key = object()
