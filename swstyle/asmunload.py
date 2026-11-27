# SPDX-License-Identifier: LGPL-2.1-or-later
""














_FW_SEEN = set()


def _fw_log(site, err):
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return


import os

import FreeCAD as App

try:
    import FreeCADGui as Gui
except ImportError:  # pragma: no cover
    Gui = None

KEY = "UnloadHidden"
TEXT = "Unload Hidden Components"
PROP, FILE_PROP, MATES_PROP = "FwUnloaded", "FwUnloadedFile", "FwUnloadedMates"
_pending = set()        # (doc name, component name) waiting to load again
_observer = None


def _ac():
    from . import asmcore
    return asmcore


def is_unloaded(comp):
    try:
        on = bool(getattr(comp, PROP, False))
    except Exception:
        return False
    if on and _part_doc(comp) is not None:
        # loaded after all (an assembly saved with it unloaded and opened again: FreeCAD loads every file

        key = (comp.Document.Name, comp.Name)
        if key not in _pending:
            _pending.add(key)
            from PySide import QtCore
            QtCore.QTimer.singleShot(0, lambda k=key: _restore_later(k))
        return False
    if on and _observer is None:
        _watch()            # showing one loads it
    return on


def _part_doc(comp):
    try:
        linked = comp.LinkedObject
        d = getattr(linked, "Document", None)
        return d if d is not None and d is not comp.Document else None
    except Exception:
        return None


def _shown(comp):
    return comp.ViewObject is not None and bool(comp.ViewObject.Visibility)


def candidates(asm):
    """The hidden, loaded components whose document is another file."""
    out = []
    for c in _ac().components(asm) if asm is not None else []:
        if getattr(c, "TypeId", "") != "App::Link" or is_unloaded(c) or _shown(c):
            continue
        d = _part_doc(c)
        if d is not None and d.FileName:
            out.append(c)
    return out


def _users(d):
    """Every object in an open document that links into d."""
    out = []
    for other in App.listDocuments().values():
        if other is d:
            continue
        for o in other.Objects:
            try:
                linked = getattr(o, "LinkedObject", None)
                if linked is not None and getattr(linked, "Document", None) is d:
                    out.append(o)
            except Exception:
                continue
    return out


def _held_open(d, going):
    """Why d must stay open (None when it can close): something other than the components unloading needs it."""
    names = {(c.Document.Name, c.Name) for c in going}
    for o in _users(d):
        if (o.Document.Name, o.Name) not in names:
            return "used by %s" % o.Label
    if Gui is not None:
        try:
            g = Gui.getDocument(d.Name)
            if g is not None and g.Modified:
                return "unsaved changes"
            if g is not None and _has_window(d):
                return "open in its own window"
        except Exception as _fw_err:
            _fw_log("asmunload.py:held", _fw_err)
    return None


def _has_window(d):
    """d shows in a window of its own (a document opened only for an assembly has none on screen)."""
    from PySide import QtWidgets
    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    if mdi is None:
        return False
    for sw in mdi.subWindowList():
        w = sw.widget()
        title = (w.windowTitle() if w is not None else "") or sw.windowTitle()
        if sw.isVisible() and title.replace("[*]", "").startswith(d.Label + " : "):
            return True
    return False


def unload_hidden(asm):
    """Unloads the hidden components' documents. Returns (unloaded component names, {file: why kept})."""
    from . import asmmenu
    comps = candidates(asm)
    by_doc = {}
    for c in comps:
        by_doc.setdefault(_part_doc(c).Name, []).append(c)
    done, kept = [], {}
    for name, group in by_doc.items():
        d = App.getDocument(name)
        why = _held_open(d, group)
        if why:
            kept[os.path.basename(d.FileName)] = why
            continue
        path = d.FileName
        for c in group:
            mates = [j for j in asmmenu.mates_of(c) if not getattr(j, "Suppressed", False)]
            for j in mates:
                j.Suppressed = True
            for prop, kind in ((PROP, "App::PropertyBool"), (FILE_PROP, "App::PropertyString"),
                               (MATES_PROP, "App::PropertyStringList")):
                if not hasattr(c, prop):
                    c.addProperty(kind, prop, "FreeCAD", "Unload Hidden Components (hidden)")
                    c.setEditorMode(prop, 2)
            setattr(c, FILE_PROP, path)
            setattr(c, MATES_PROP, [j.Name for j in mates])
            setattr(c, PROP, True)
        try:
            App.closeDocument(name)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s not unloaded: %s\n" % (os.path.basename(path), error))
            for c in group:
                _restore(c, solve=False)
            continue
        for c in group:
            try:
                c.purgeTouched()            # nothing to recompute while it is unloaded
            except Exception as _fw_err:
                _fw_log("asmunload.py:purge", _fw_err)
            done.append(c.Name)
    _watch()
    _status("%d component%s unloaded" % (len(done), "" if len(done) == 1 else "s")
            + ("; kept: " + ", ".join("%s (%s)" % kv for kv in kept.items()) if kept else ""))
    _refresh()
    return done, kept


def load(comp, solve=True):
    """Loads an unloaded component's file again (its link finds it), puts its mates back, solves."""
    if not getattr(comp, PROP, False):
        return False
    path = getattr(comp, FILE_PROP, "")
    if _part_doc(comp) is None and path:
        have = [d for d in App.listDocuments().values()
                if os.path.normcase(d.FileName or "") == os.path.normcase(path)]
        if not have:
            if not os.path.exists(path):
                _status("%s: file not found (%s)" % (comp.Label, path))
                return False
            _open_quietly(path)
    _restore(comp, solve)
    return True


def _open_quietly(path):
    """Opens the file for the assembly only: the document that was active stays active, so the part gets no window."""
    was = App.ActiveDocument
    gwas = Gui.ActiveDocument if Gui is not None else None
    d = App.openDocument(path, hidden=True)
    try:
        if was is not None:
            App.setActiveDocument(was.Name)
        if gwas is not None:
            Gui.setActiveDocument(gwas.Document.Name)
    except Exception as _fw_err:
        _fw_log("asmunload.py:active", _fw_err)
    return d


def _restore(comp, solve=True):
    doc = comp.Document
    for name in getattr(comp, MATES_PROP, []) or []:
        j = doc.getObject(name)
        if j is not None:
            j.Suppressed = False
    setattr(comp, MATES_PROP, [])
    setattr(comp, PROP, False)
    try:
        comp.touch()
        doc.recompute()
        if solve:
            asm = _ac().assembly_of(doc)
            if asm is not None:
                _ac().solve(asm)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: loading %s: %s\n" % (comp.Label, error))
    _refresh()


def load_all(asm):
    """Loads every unloaded component (before a whole-assembly step that needs every shape)."""
    out = [c for c in (_ac().components(asm) if asm is not None else []) if is_unloaded(c)]
    for c in out:
        load(c, solve=False)
    if out:
        _ac().solve(asm)
    return out


def unloadable(asm):
    """The hidden components whose documents can close now."""
    by_doc = {}
    for c in candidates(asm):
        by_doc.setdefault(_part_doc(c).Name, []).append(c)
    out = []
    for name, group in by_doc.items():
        if _held_open(App.getDocument(name), group) is None:
            out += group
    return out


def menu_item(asm):
    """(key, text, run, enabled) for the top assembly row, or None when no hidden component can unload
    (no dead row)."""
    if not unloadable(asm):
        return None
    return (KEY, TEXT, lambda: unload_hidden(asm), True)


# --- loading again when shown ------------------------------------------------------------------
class _Observer:
    """App side only (a Gui observer with slotChangedObject breaks FEM mesh objects): a component's
    Visibility turned on while unloaded loads it, a moment later (never inside the change itself)."""

    def slotChangedObject(self, obj, prop):
        if prop != "Visibility":
            return
        try:
            if is_unloaded(obj) and obj.Visibility:
                key = (obj.Document.Name, obj.Name)
                if key not in _pending:
                    _pending.add(key)
                    from PySide import QtCore
                    QtCore.QTimer.singleShot(0, lambda k=key: _load_later(k))
        except Exception as _fw_err:
            _fw_log("asmunload.py:observer", _fw_err)


def _load_later(key):
    _pending.discard(key)
    try:
        doc = App.getDocument(key[0])
        comp = doc.getObject(key[1])
    except Exception:
        return
    if comp is not None and getattr(comp, PROP, False):
        load(comp)


def _restore_later(key):
    _pending.discard(key)
    try:
        comp = App.getDocument(key[0]).getObject(key[1])
    except Exception:
        return
    if comp is not None and getattr(comp, PROP, False) and _part_doc(comp) is not None:
        _restore(comp, solve=True)


def _watch():
    global _observer
    if _observer is None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)


def watch_document(doc):
    """An assembly opened with unloaded components (saved that way) loads them when they are shown."""
    try:
        if any(is_unloaded(o) for o in doc.Objects):
            _watch()
    except Exception as _fw_err:
        _fw_log("asmunload.py:watch doc", _fw_err)


# --- the tree mark ----------------------------------------------------------------------------------
_ICONS = {}


def unloaded_icon(base):
    ""
    from PySide import QtCore, QtGui
    if not isinstance(base, QtGui.QIcon) or base.isNull():
        return base
    key = base.cacheKey()
    if key in _ICONS:
        return _ICONS[key]
    icon = QtGui.QIcon()
    for size in (16, 24, 32):
        src = base.pixmap(size, size)
        if src.isNull():
            continue
        pm = QtGui.QPixmap(size, size)
        pm.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setOpacity(0.35)
        p.drawPixmap(QtCore.QRect(0, 0, size, size), src)
        p.end()
        icon.addPixmap(pm)
    _ICONS[key] = icon
    return icon


def _status(text):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 6000)
    except Exception as _fw_err:
        _fw_log("asmunload.py:status", _fw_err)


def _refresh():
    try:
        from . import asmui
        asmui.refresh()
    except Exception as _fw_err:
        _fw_log("asmunload.py:refresh", _fw_err)
