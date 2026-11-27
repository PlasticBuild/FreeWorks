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
from PySide import QtCore, QtWidgets

from . import chrome, paths
from .widgets import alive

Qt = QtCore.Qt

PARAM = "TreeSketchStatus"   # addon parameter (default on)
SKETCH = "Sketcher::SketchObject"
UNDER, OVER, UNSOLVED = "(-) ", "(+) ", "(?) "
PREFIXES = (UNDER, OVER, UNSOLVED)
MARKS = {"Under Defined": UNDER, "Over Defined": OVER, "No Solution Found": UNSOLVED}
DEPTH = 12                   # rows nested deeper than this are left alone
SOON = 120                   # ms from a change to the next look at the rows
LATER_MAX = 20000            # more rows rewritten in one recompute than this: one whole pass instead


def enabled():
    return paths.params().GetBool(PARAM, True)


def label_of(text):
    """The label behind a tree row's text: the text without the state this module puts first."""
    if text:
        for mark in PREFIXES:
            if text.startswith(mark):
                return text[len(mark):]
    return text or ""


def mark(sketch):
    ""
    return MARKS.get(chrome.sketch_state(sketch), "")


def wanted(sketch, on=True):
    """The text the sketch's rows should show."""
    return (mark(sketch) if on else "") + sketch.Label


def rows(model, parent=QtCore.QModelIndex(), depth=0):
    """Every row of the tree under parent, nested ones included, as model indexes."""
    for row in range(model.rowCount(parent)):
        index = model.index(row, 0, parent)
        yield index
        if depth < DEPTH and model.rowCount(index):
            yield from rows(model, index, depth + 1)


def _documents():
    return {doc.Label: doc for doc in App.listDocuments().values()}


def _sketches(doc):
    """Label -> the document's sketch with it; a label shared with another object is left out
    (FreeCAD can be set to allow duplicate labels), the tree showing labels only."""
    by_label, shared = {}, set()
    for obj in doc.Objects:
        if obj.Label in by_label or obj.Label in shared:
            shared.add(obj.Label)
            by_label.pop(obj.Label, None)
        elif obj.TypeId == SKETCH:
            by_label[obj.Label] = obj
        else:
            shared.add(obj.Label)
    return by_label


def _by_label(doc, text):
    """The sketch with the row's label (as _sketches: a label shared with another object is none)."""
    for label in (text, label_of(text)):
        try:
            objs = doc.getObjectsByLabel(label)
        except Exception:
            return _sketches(doc).get(text) or _sketches(doc).get(label_of(text))
        if len(objs) == 1:
            return objs[0] if objs[0].TypeId == SKETCH else None
        if objs:
            return None
    return None


def _document_of(index, docs):
    top = index
    while top.parent().isValid():
        top = top.parent()
    return docs.get(top.data(Qt.DisplayRole))


def _editing_sketch():
    try:
        import FreeCADGui as Gui
        doc = Gui.ActiveDocument
        obj = doc.getInEdit() if doc is not None else None
        obj = getattr(obj, "Object", obj)
        return getattr(obj, "TypeId", "") == SKETCH
    except Exception:
        return False


def _recomputing():
    try:
        from . import asmgen
        if asmgen._busy:
            return True
    except Exception as _fw_err:
        _fw_log("sketchstatus.py:128", _fw_err)
    try:
        # FreeCAD 1.1 documents have no State: their Recomputing flag says it
        return any(getattr(doc, "Recomputing", False) for doc in App.listDocuments().values())
    except Exception:
        return False


def sketch_of(index, docs=None, sketches=None):
    """The sketch a tree row stands for, or None."""
    text = index.data(Qt.DisplayRole)
    if not text:
        return None
    doc = _document_of(index, _documents() if docs is None else docs)
    if doc is None:
        return None
    if sketches is None:
        return _by_label(doc, text)      # one row: FreeCAD's label lookup, not a pass over every object
    found = sketches.get(doc.Name)
    if found is None:
        found = sketches[doc.Name] = _sketches(doc)
    return found.get(text) or found.get(label_of(text))


class _Observer:
    """A sketch changed, was made or recomputed: its rows are looked at again."""

    def __init__(self, owner):
        self.owner = owner

    def slotChangedObject(self, obj, prop):
        if getattr(obj, "TypeId", "") == SKETCH:
            self.owner._soon()

    def slotRecomputedDocument(self, doc):
        self.owner.recomputed(doc)

    # a part, a drawing view or a mate made or deleted changes no sketch row: no tree walk
    def slotCreatedObject(self, obj):
        if getattr(obj, "TypeId", "") == SKETCH:
            self.owner._soon()

    def slotDeletedObject(self, obj):
        if getattr(obj, "TypeId", "") == SKETCH:
            self.owner._soon()


class SketchStatus(QtCore.QObject):
    """Keeps the sketch rows of FreeCAD's tree marked while the style is on."""

    def __init__(self, shell):
        super().__init__(shell.window)
        self.shell = shell
        self.tree = None
        self._applying = False
        self._due = False
        self.applied = 0             # rows set, for checks
        self.walks = 0               # whole-tree passes, for checks
        self._marks = {}             # (document, sketch) -> its text at the last recompute
        self._later = []             # rows rewritten during a recompute, set after it
        self._later_due = False
        self._last_on = None
        self.observer = _Observer(self)
        try:
            App.addDocumentObserver(self.observer)
        except Exception:
            self.observer = None
        self._soon()

    # ------------------------------------------------------------ the tree
    def _find_tree(self):
        if self.tree is not None and alive(self.tree):
            return self.tree
        pane = getattr(self.shell, "left_pane", None)
        return pane.tree_widget() if pane is not None and alive(pane) else None

    def _signals(self, tree):
        model = tree.model()
        return ((model.dataChanged, self._data_changed), (model.rowsInserted, self._rows_changed),
                (model.rowsRemoved, self._rows_changed))

    def attach(self, tree):
        if tree is self.tree:
            return
        self.detach()
        self.tree = tree
        tree.viewport().installEventFilter(self)
        for signal, slot in self._signals(tree):
            signal.connect(slot)

    def detach(self):
        tree, self.tree = self.tree, None
        if tree is not None and alive(tree):
            tree.viewport().removeEventFilter(self)
            for signal, slot in self._signals(tree):
                try:
                    signal.disconnect(slot)
                except Exception as _fw_err:
                    _fw_log("sketchstatus.py:225", _fw_err)

    # ------------------------------------------------------------ the rows
    def on(self):
        return bool(self.shell.enabled and enabled())

    def soon(self):
        """The shell's tick (about every second): a whole pass only when it can show something new:
        the tree was made again, the style was switched on or off, or a sketch is being edited
        (its state changes with every drag). Otherwise the document observer and the tree's own
        signals keep the rows set (a drawing of a 300-part assembly walked 9000 rows a second)."""
        tree = self._find_tree()
        if tree is not self.tree or self.on() != self._last_on or _editing_sketch():
            self._soon()

    def _soon(self):
        """A look at every row shortly: one look for a burst of changes (a document opening, a
        sketch being dragged), so that the tree walk never slows the mouse down. A row FreeCAD
        rewrote is set again at once in _data_changed, this is for everything else."""
        if not self._due:
            self._due = True
            QtCore.QTimer.singleShot(SOON, self.refresh)

    def refresh(self):
        self._due = False
        if _recomputing():
            self._soon()
            return
        tree = self._find_tree()
        if tree is None or not alive(tree):
            self.detach()
            return
        self.attach(tree)
        try:
            self._last_on = self.on()
            self.apply(self._last_on)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: sketch status: %s\n" % error)

    def recomputed(self, doc):
        """A pass after a recompute only when one of the document's sketches shows another state
        (a drawing or an assembly of hundreds of parts recomputes often, its sketches mostly not)."""
        try:
            on = self.on()
            changed = False
            for sketch in doc.findObjects(Type=SKETCH):
                key = (doc.Name, sketch.Name)
                text = wanted(sketch, on)
                if self._marks.get(key) != text:
                    self._marks[key] = text
                    changed = True
        except Exception:
            changed = True
        if changed:
            self._soon()

    def apply(self, on=True):
        """Every sketch row's text as it should be: marked while on, the plain label otherwise.
        A document with no sketch is not walked."""
        tree = self.tree
        if tree is None or not alive(tree):
            return
        model = tree.model()
        docs, sketches = _documents(), {}
        self.walks += 1
        self._applying = True
        try:
            for row in range(model.rowCount()):
                top = model.index(row, 0)
                doc = docs.get(top.data(Qt.DisplayRole))
                if doc is not None:
                    try:
                        if not doc.findObjects(Type=SKETCH):
                            continue
                    except Exception as _fw_err:
                        _fw_log("sketchstatus.py:300", _fw_err)
                self._fix(top, on, docs, sketches)
                for index in rows(model, top, 1):
                    self._fix(index, on, docs, sketches)
        finally:
            self._applying = False

    def _fix(self, index, on, docs=None, sketches=None):
        sketch = sketch_of(index, docs, sketches)
        if sketch is None:
            return False
        text = wanted(sketch, on)
        if index.data(Qt.DisplayRole) == text:
            return False
        index.model().setData(index, text, Qt.DisplayRole)
        self.applied += 1
        return True

    def _data_changed(self, first, last, roles=()):
        """FreeCAD writes a row's plain label when the Label changes (also right after a rename):
        the row is set again at once, before anything is painted; a status change elsewhere is
        looked at soon."""
        if self._applying or self.tree is None:
            return
        if roles and Qt.DisplayRole not in roles and Qt.EditRole not in roles:
            return              # a row's colour, icon or font: its text (all this looks at) is as it was
        if _recomputing():
            # thousands of rows change during a big rebuild: those rows are set once it is over
            if first.column() == 0:
                model, parent = first.model(), first.parent()
                for row in range(first.row(), last.row() + 1):
                    self._later.append(QtCore.QPersistentModelIndex(model.index(row, 0, parent)))
                if len(self._later) > LATER_MAX:
                    self._later = []
                    self._soon()
                elif not self._later_due:
                    self._later_due = True
                    QtCore.QTimer.singleShot(SOON, self._fix_later)
            return
        if first.column() == 0:
            model, parent = first.model(), first.parent()
            self._applying = True
            try:
                docs, on = _documents(), self.on()
                for row in range(first.row(), last.row() + 1):
                    self._fix(model.index(row, 0, parent), on, docs)
            except Exception as _fw_err:
                _fw_log("sketchstatus.py:347", _fw_err)
            finally:
                self._applying = False
        # a sketch's state change comes through the document observer: no whole-tree pass here

    def _fix_later(self):
        """The rows FreeCAD rewrote during a recompute, set now that it is over."""
        self._later_due = False
        if _recomputing():
            self._later_due = True
            QtCore.QTimer.singleShot(SOON, self._fix_later)
            return
        later, self._later = self._later, []
        if self.tree is None or not alive(self.tree):
            return
        self._applying = True
        try:
            docs, on, sketches = _documents(), self.on(), {}
            for p in later:
                if p.isValid():
                    self._fix(self.tree.model().index(p.row(), 0, p.parent()), on, docs, sketches)
        except Exception as _fw_err:
            _fw_log("sketchstatus.py:369", _fw_err)
        finally:
            self._applying = False

    def _rows_changed(self, parent=QtCore.QModelIndex(), first=0, last=-1):
        """New rows (a document opened, a body expanded, an object made) are set where they are;
        removed rows leave nothing to set."""
        if self._applying or self.tree is None or last < first:
            return
        model = self.tree.model()
        if model.rowCount(parent) <= last:
            return              # rowsRemoved: the rows are gone
        self._applying = True
        try:
            docs, on, sketches = _documents(), self.on(), {}
            depth = 0
            p = parent
            while p.isValid():
                depth, p = depth + 1, p.parent()
            for row in range(first, last + 1):
                index = model.index(row, 0, parent)
                if not index.isValid():
                    continue
                self._fix(index, on, docs, sketches)
                for sub in rows(model, index, depth + 1):
                    self._fix(sub, on, docs, sketches)
        except Exception as _fw_err:
            _fw_log("sketchstatus.py:396", _fw_err)
        finally:
            self._applying = False

    # ------------------------------------------------------------ the rename editor
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.ChildAdded and self.tree is not None and alive(self.tree) \
                and obj is self.tree.viewport():
            QtCore.QTimer.singleShot(0, self._editor_opened)
        return False

    def _editor_opened(self):
        """The rename editor FreeCAD's tree opens on a row (F2, or a click on the picked row) is
        given the plain label, so that nothing but a name the user types renames the sketch."""
        tree = self.tree
        if tree is None or not alive(tree):
            return
        for editor in tree.viewport().findChildren(QtWidgets.QLineEdit):
            index = tree.indexAt(editor.geometry().center())
            if not index.isValid():
                continue
            sketch = sketch_of(index)
            if sketch is not None and editor.text() == index.data(Qt.DisplayRole) and editor.text() != sketch.Label:
                editor.setText(sketch.Label)
                editor.selectAll()

    def remove(self):
        if self.observer is not None:
            try:
                App.removeDocumentObserver(self.observer)
            except Exception as _fw_err:
                _fw_log("sketchstatus.py:429", _fw_err)
            self.observer = None
        tree = self.tree
        try:
            if tree is not None and alive(tree):
                self.apply(False)
        except Exception as _fw_err:
            _fw_log("sketchstatus.py:436", _fw_err)
        self.detach()
