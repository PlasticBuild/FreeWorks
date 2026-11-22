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
from PySide import QtCore

from . import paths

PARAM = "KeepOpenedFilesClean"
SETTLE_MS = (400, 1500, 4000, 8000, 15000)   # the updates run from timers after the file opens,
                                             # later ones while FreeCAD is still starting up
RETRIES = 25                    # x 200 ms: waits for the opened file's view document


def enabled():
    return paths.params().GetBool(PARAM, True)


def include_referenced():
    """Options > General > Include documents opened from other documents (in the recent list)."""
    try:
        from . import optionspages
        return bool(optionspages.stored("General", "Include documents opened from other documents", False))
    except Exception:
        return False


def recent_add(path):
    """Puts path first in FreeCAD's recent files (what File > Open Recent and Std_RecentFiles show)."""
    if not path:
        return False
    p = App.ParamGet("User parameter:BaseApp/Preferences/RecentFiles")
    most = p.GetInt("RecentFiles", 12) or 12
    files = []
    for i in range(most):
        fn = p.GetString("MRU%d" % i, "")
        if fn and fn not in files:
            files.append(fn)
    norm = lambda s: s.replace("\\", "/").lower()
    files = [path] + [fn for fn in files if norm(fn) != norm(path)]
    for i, fn in enumerate(files[:most]):
        p.SetString("MRU%d" % i, fn)
    # File > Open Recent keeps its own copy of the list, read at start-up, and writes that copy back at exit
    # (so a file added here was missing from the menu and lost at exit). FreeCAD re-reads the list when the
    # RecentFiles count changes: change it and put it back.
    try:
        p.SetInt("RecentFiles", most + 1)
        p.SetInt("RecentFiles", most)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: recent files menu not refreshed: %s\n" % error)
    return True


def _referenced_elsewhere(doc):
    """True when another open document links to this one (it was opened as a reference)."""
    for other in App.listDocuments().values():
        if other.Name == doc.Name:
            continue
        for obj in other.Objects:
            try:
                for dep in obj.OutList:
                    if dep.Document.Name == doc.Name:
                        return True
            except Exception:
                continue
    return False


def _gui(name):
    try:
        return Gui.getDocument(name)
    except Exception:
        return None


class _Observer:
    def __init__(self, owner):
        self.owner = owner

    def slotFinishRestoreDocument(self, doc):
        self.owner.opened(doc)

    def slotActivateDocument(self, doc):
        self.owner.activated(doc.Name)
        # FreeCAD 1.1 may make the file the active one before it has finished opening
        if doc.FileName:
            self.owner.opened(doc)

    def slotCreatedDocument(self, doc):
        # FreeCAD names an opened file only after it creates the document, in the same call: a
        # document still unnamed once events run again was made in this session (New, or a part
        # an assembly build makes and saves), not opened, so it needs no fit and no clean-up
        name = doc.Name
        QtCore.QTimer.singleShot(0, lambda: self.owner.created_here(name))

    def slotDeletedDocument(self, doc):
        self.owner.closed(doc.Name)


def model_box(doc):
    """The bounding box of what is shown, or None."""
    box = None
    for obj in doc.Objects:
        try:
            if not obj.isDerivedFrom("Part::Feature"):
                continue
            if obj.ViewObject is None or not obj.ViewObject.isVisible() or obj.isDerivedFrom("Part::Part2DObject"):
                continue
            shape = obj.Shape
            if shape.isNull() or not shape.Faces:
                continue
            b = shape.BoundBox
            if not b.isValid():
                continue
            box = b if box is None else box.united(b)
        except Exception:
            continue
    return box


def off_screen(view, box):
    """True when none of the box's corners lands inside the view, or the model is a speck."""
    try:
        w, h = view.getSize()
    except Exception:
        return False
    xs, ys, inside = [], [], 0
    for cx in (box.XMin, box.XMax):
        for cy in (box.YMin, box.YMax):
            for cz in (box.ZMin, box.ZMax):
                try:
                    px, py = view.getPointOnScreen(App.Vector(cx, cy, cz))
                except Exception:
                    return False
                xs.append(px); ys.append(py)
                if 0 <= px <= w and 0 <= py <= h:
                    inside += 1
    if inside == 0:
        return True
    extent = max(max(xs) - min(xs), max(ys) - min(ys))
    return extent < 0.02 * max(w, h, 1)


def view_alive(view):
    """rcmenus pkg270: True while view is a live, shown 3D view. A fit that waited on a timer (a turn, a
    viewport layout, a file settling) checks this first: a long chain of clicks can close or replace the
    view in the meantime, and fitAll on such a view crashed FreeCAD (bench sweep, assembly)."""
    try:
        if view is None or not hasattr(view, "fitAll"):
            return False
        w = view.graphicsView()
        if w is None:
            return False
        try:
            import shiboken6
            if not shiboken6.isValid(w):
                return False
        except ImportError:
            pass
        return w.isVisible() and w.width() > 1 and w.height() > 1
    except Exception:
        return False


def _in_front(gui):
    """True when gui is the document the user is looking at. A file opened in the background (a
    part an assembly loads, a referenced document) is fitted only when it is brought to the front:
    fitting every component of a 300-part assembly as it loaded cost 3.9 s (pkg179 profile)."""
    try:
        active = Gui.ActiveDocument
        return active is not None and active.Document.Name == gui.Document.Name
    except Exception:
        return True


def fit_if_off_screen(gui):
    ""

    global _fitting
    if _fitting or _recomputing():
        return None             # inside another fit or a rebuild: tried again later (settle)
    _fitting = True
    try:
        doc = gui.Document
        box = model_box(doc)
        view = gui.ActiveView
        if box is None or view is None or not hasattr(view, "getPointOnScreen"):
            return False
        if not view_alive(view):
            return False
        if off_screen(view, box):
            view.fitAll()
            return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: fit after open: %s\n" % error)
    finally:
        _fitting = False
    return False


_fitting = False        # a fit is running: fitAll runs events, which can start another settle


def _recomputing():
    """A document is being rebuilt now (a fit then would draw a half-built model)."""
    try:
        from . import asmgen
        return bool(asmgen._busy)
    except Exception:
        return False


class CleanOpen(QtCore.QObject):
    def __init__(self, shell):
        super().__init__(shell.window)
        self.seen = set()
        self.fitted = set()        # document names whose view was checked after opening
        self.made = set()          # documents made in this session (not opened from a file)
        self.pending = set()       # opened in the background: fitted when first brought to the front
        self.watch = {}            # document name -> undo count when it opened
        self.observer = _Observer(self)
        App.addDocumentObserver(self.observer)
        from . import restorehook       # the one working "file opened" signal (FreeCAD 1.1 sends none)
        restorehook.on_restored(self.opened)
        # a file opened while FreeCAD starts (a start-up macro, a file given to FreeCAD) is
        # open before this exists
        for doc in App.listDocuments().values():
            if doc.FileName:
                self.opened(doc)

    def created_here(self, name):
        doc = App.listDocuments().get(name)
        if doc is not None and not doc.FileName and name not in self.seen:
            self.made.add(name)

    def opened(self, doc, tries=0):
        name = doc.Name
        if name in self.seen or name in self.made or not enabled():
            return
        gui = _gui(name)
        if gui is None:
            if tries < RETRIES:
                QtCore.QTimer.singleShot(200, lambda: self._retry(name, tries + 1))
            return
        self.seen.add(name)
        if include_referenced() and doc.FileName:
            QtCore.QTimer.singleShot(400, lambda name=name: self._recent(name))
        if gui.Modified and doc.UndoCount:
            return                 # already changed by the user
        self.watch[name] = doc.UndoCount
        for delay in SETTLE_MS:
            QtCore.QTimer.singleShot(delay, lambda name=name: self.settle(name))
        QtCore.QTimer.singleShot(SETTLE_MS[-1] + 50, lambda name=name: self.watch.pop(name, None))

    def activated(self, name):
        """A file opened in the background gets its one fit when it first comes to the front."""
        if name not in self.pending:
            return
        self.pending.discard(name)

        def later(name=name):
            gui = _gui(name)
            if gui is None or name in self.fitted or not _in_front(gui):
                return
            self.fitted.add(name)
            fit_if_off_screen(gui)
        QtCore.QTimer.singleShot(0, later)

    def _recent(self, name):
        doc = App.listDocuments().get(name)
        if doc is not None and doc.FileName and _referenced_elsewhere(doc):
            recent_add(doc.FileName)

    def _retry(self, name, tries):
        doc = App.listDocuments().get(name)
        if doc is not None:
            self.opened(doc, tries)

    def closed(self, name):
        self.seen.discard(name)        # the same file opened again is watched again
        self.made.discard(name)
        self.fitted.discard(name)
        self.pending.discard(name)
        self.watch.pop(name, None)

    def settle(self, name):
        doc = App.listDocuments().get(name)
        gui = _gui(name)
        if doc is None or gui is None or name not in self.watch:
            return
        if name not in self.fitted:
            if _in_front(gui):
                if fit_if_off_screen(gui) is None:
                    self.pending.add(name)          # busy: fitted when next brought to the front
                else:
                    self.fitted.add(name)
                    self.pending.discard(name)
            else:
                self.pending.add(name)
        if not doc.FileName:
            self.watch.pop(name, None)     # a new document (a file's name is set once it has opened)
            return
        if name not in self.watch:         # fitting the view let the document close or settle
            return
        if doc.UndoCount != self.watch[name]:
            self.watch.pop(name, None)     # the user did something: leave it modified
            return
        if gui.Modified:
            try:
                gui.Modified = False
            except Exception as error:
                App.Console.PrintLog("FreeCAD: %s left modified: %s\n" % (name, error))

    def remove(self):
        try:
            App.removeDocumentObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("cleanopen.py:308", _fw_err)
        self.watch.clear()
        self.pending.clear()
