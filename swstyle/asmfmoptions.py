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

import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import asmcore as ac

PAGE = "FeatureManager"
RENAME = "Allow component files to be renamed from FeatureManager tree"
PREVIEW = "Enable preview of hidden components"
PENDING = {}            # assembly doc name: {component name: new file base}


def rename_files_on():
    from . import optionspages
    return bool(optionspages.stored(PAGE, RENAME, False))


def preview_on():
    from . import optionspages
    try:
        from . import asmlarge
        if asmlarge.preview_blocked():
            return False
    except Exception as _fw_err:
        _fw_log("asmfmoptions.py:48", _fw_err)
    return bool(optionspages.stored(PAGE, PREVIEW, True))


def _base(label):
    return label.rsplit("<", 1)[0].strip()


def _part_doc(comp):
    from . import asmmenu
    return asmmenu.part_document(comp)


# ---------------------------------------------------------------- rename component files
def note_rename(comp):
    """A component's name changed in the tree: its file follows at the next save (option on)."""
    if not rename_files_on():
        return False
    doc = _part_doc(comp)
    if doc is None or not doc.FileName:
        return False
    new = _base(comp.Label)
    old = os.path.splitext(os.path.basename(doc.FileName))[0]
    if not new or new == old or new.startswith("["):
        return False
    PENDING.setdefault(comp.Document.Name, {})[comp.Name] = new
    return True


def _relink(link):
    """A link to a document just saved under another name keeps the old file name in what the
    assembly writes (FreeCAD updates it only when the link is set again), so the assembly opened
    later used the old file. Set again, it names the new file."""
    try:
        target = link.LinkedObject
        if target is not None:
            link.LinkedObject = None
            link.LinkedObject = target
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s keeps its old file: %s\n" % (link.Label, error))


def _follow_open(part_doc, asm_doc):
    ""



    for other in list(App.listDocuments().values()):
        if other is part_doc or other is asm_doc:
            continue
        try:
            if part_doc not in other.getDependentDocuments():
                continue
        except Exception as _fw_err:
            _fw_log("asmfmoptions.py:follow deps", _fw_err)
            continue
        for o in other.Objects:
            try:
                if o.TypeId in ("App::Link", "Assembly::AssemblyLink"):
                    target = getattr(o, "LinkedObject", None)
                    if target is not None and getattr(target, "Document", None) is part_doc:
                        _relink(o)
            except Exception as _fw_err:
                _fw_log("asmfmoptions.py:follow link", _fw_err)
        _mark(other.Name)
        QtCore.QTimer.singleShot(600, lambda n=other.Name: _mark(n))   # after the save's own clean-up


def _mark(name):
    """The open document is marked to save (its window title gets the asterisk; closing it asks)."""
    try:
        from . import saveas
        saveas._SmartSave.dirty.add(name)      # a real change: Save does not take it for a looks-only one
    except Exception as _fw_err:
        _fw_log("asmfmoptions.py:follow dirty", _fw_err)
    try:
        from . import cleanopen          # a file opened a moment ago: not kept "unchanged" any more
        for keeper in Gui.getMainWindow().findChildren(cleanopen.CleanOpen):
            keeper.watch.pop(name, None)
    except Exception as _fw_err:
        _fw_log("asmfmoptions.py:follow opened", _fw_err)
    try:
        if name in App.listDocuments():
            g = Gui.getDocument(name)
            if g is not None:
                g.Modified = True
    except Exception as _fw_err:
        _fw_log("asmfmoptions.py:follow modified", _fw_err)


def apply_renames(asm_doc):
    ""

    todo = PENDING.pop(asm_doc.Name, {})
    done = []
    asm = ac.assembly_of(asm_doc)
    for name, new in todo.items():
        comp = asm_doc.getObject(name)
        if comp is None:
            continue
        doc = _part_doc(comp)
        if doc is None or not doc.FileName:
            continue
        path = os.path.join(os.path.dirname(doc.FileName), new + ".FCStd")
        if os.path.exists(path):
            App.Console.PrintWarning("FreeCAD: %s exists; %s keeps its file name\n" % (path, comp.Label))
            continue
        doc.saveAs(path)
        if asm is not None:
            from . import asmcomp
            for c in asmcomp.instances(asm, comp):
                _relink(c)          # the assembly is being saved now: its links name the new file
                base, _, inst = c.Label.rpartition("<")
                if base and base != new:
                    c.Label = "%s<%s" % (new, inst)
        _follow_open(doc, asm_doc)
        done.append(path)
    if done:
        try:
            asm_doc.recompute()     # the links set again are saved up to date, not marked to rebuild
        except Exception as _fw_err:
            _fw_log("asmfmoptions.py:rename recompute", _fw_err)
    return done


class _DocWatch:
    def slotChangedObject(self, obj, prop):
        if prop != "Label":
            return
        try:
            if not rename_files_on():       # (checked first: a 300-component build renamed each one)
                return
            asm = ac.assembly_of(obj.Document)
            if asm is not None and obj in ac.components(asm):
                note_rename(obj)
        except Exception as _fw_err:
            _fw_log("asmfmoptions.py:116", _fw_err)

    def slotStartSaveDocument(self, doc, path):
        if doc.Name in PENDING:
            try:
                apply_renames(doc)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: rename component files: %s\n" % error)


# ---------------------------------------------------------------- preview hidden components
class _Hover(QtCore.QObject):
    """The pointer over a hidden component's row: it shows see-through until the pointer leaves."""

    def __init__(self):
        super().__init__()
        self.shown = None       # (component, saved look)
        self.tree = None
        self.viewports = []

    def attach(self, tree):
        if tree is None:
            return
        try:
            viewport = tree.viewport()
        except Exception as _fw_err:
            _fw_log("asmfmoptions.py:143", _fw_err)
            return
        if any(v is viewport for v in self.viewports):
            return
        self.tree = tree
        self.viewports.append(viewport)
        tree.setMouseTracking(True)
        viewport.setMouseTracking(True)
        viewport.installEventFilter(self)
        viewport.destroyed.connect(lambda *a, v=viewport: self._gone(v))

    def _gone(self, viewport):
        self.viewports = [v for v in self.viewports if v is not viewport]

    def comp_at(self, pos, viewport=None):
        from . import asmui
        asm = ac.assembly_of(App.ActiveDocument)
        tree = viewport.parent() if viewport is not None else self.tree
        if asm is None or tree is None:
            return None
        index = tree.indexAt(pos)
        if not index.isValid():
            return None
        comps = ac.components(asm)
        node = getattr(tree.model(), "node", None)
        if node is not None:            # the FeatureManager tree (fmtree): its rows carry the object
            n = node(index)
            obj = getattr(n, "obj", None)
            if obj is not None:
                return obj if any(c is obj for c in comps) else None
        text = asmui.plain(index.data(QtCore.Qt.DisplayRole) or "")
        for c in comps:
            if c.Label == text:
                return c
        return None

    def show(self, comp):
        if self.shown is not None and self.shown[0] is comp:
            return
        self.hide()
        vo = getattr(comp, "ViewObject", None)
        if vo is None or vo.Visibility or not preview_on():
            return
        saved = (getattr(vo, "OverrideMaterial", None), getattr(vo, "ShapeMaterial", None))
        try:
            vo.Visibility = True
            if hasattr(vo, "OverrideMaterial"):
                from . import asmtools
                asmtools._fade(comp, 0.6)
        except Exception as _fw_err:
            _fw_log("asmfmoptions.py:191", _fw_err)
        self.shown = (comp, saved)

    def hide(self):
        if self.shown is None:
            return
        comp, (override, mat) = self.shown
        self.shown = None
        try:
            vo = comp.ViewObject
            if mat is not None:
                vo.ShapeMaterial = mat
            if override is not None:
                vo.OverrideMaterial = override
            vo.Visibility = False
        except Exception as _fw_err:
            _fw_log("asmfmoptions.py:207", _fw_err)

    def eventFilter(self, obj, ev):
        if not isinstance(ev, QtCore.QEvent):
            return False
        t = ev.type()
        try:
            if t == QtCore.QEvent.MouseMove:
                comp = self.comp_at(ev.position().toPoint() if hasattr(ev, "position") else ev.pos(), obj)
                if comp is None:
                    self.hide()
                elif self.shown is None or self.shown[0] is not comp:
                    self.show(comp)
            elif t in (QtCore.QEvent.Leave, QtCore.QEvent.MouseButtonPress):
                self.hide()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: hidden preview: %s\n" % error)
        return False


HOVER = _Hover()
_WATCH = None


def attach_tree():
    """FreeCAD's tree and the FeatureManager tree (SWFeatureTree) both preview."""
    from . import asmui
    try:
        HOVER.attach(asmui._tree())
    except Exception as _fw_err:
        _fw_log("asmfmoptions.py:237", _fw_err)
    try:
        for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeView, "SWFeatureTree"):
            HOVER.attach(tree)
    except Exception as _fw_err:
        _fw_log("asmfmoptions.py:242", _fw_err)


def install():
    global _WATCH
    if _WATCH is None:
        _WATCH = _DocWatch()
        App.addDocumentObserver(_WATCH)
