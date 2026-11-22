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
from PySide import QtCore, QtGui, QtWidgets

LAST = [None]


def _page(widget):
    w = widget
    while w is not None and w.objectName() != "SWTaskPaneDesignLibrary":
        w = w.parentWidget()
    return w


def _later(run):
    return lambda checked=False: QtCore.QTimer.singleShot(0, run)


def _add(menu, text, run, enabled=True):
    a = menu.addAction(text)
    a.setEnabled(bool(enabled))
    a.triggered.connect(_later(run))
    return a


def _explore(path):
    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path if os.path.isdir(path) else os.path.dirname(path)))


def _rename(page, path):
    old = os.path.basename(path.rstrip("/\\"))
    base, ext = os.path.splitext(old) if os.path.isfile(path) else (old, "")
    text, ok = QtWidgets.QInputDialog.getText(page, "Rename", "Name:", text=base)
    text = (text or "").strip()
    if not ok or not text or text == base or any(c in text for c in '\\/:*?"<>|'):
        return False
    new = os.path.join(os.path.dirname(path.rstrip("/\\")), text + ext)
    if os.path.exists(new):
        return False
    os.rename(path, new)
    _refresh(page, new if os.path.isdir(new) else os.path.dirname(new))
    return True


def _trash(page, path):
    name = os.path.basename(path.rstrip("/\\"))
    ask = QtWidgets.QMessageBox.question(page, "Delete", "Move \"%s\" to the Recycle Bin?" % name,
                                         QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
    if ask != QtWidgets.QMessageBox.Yes:
        return False
    ok = QtCore.QFile.moveToTrash(path)
    ok = ok[0] if isinstance(ok, tuple) else ok
    _refresh(page, os.path.dirname(path.rstrip("/\\")))
    return bool(ok)


def _refresh(page, select=None):
    try:
        page.refresh()
        if select:
            page.select(select)
        page.show_files()
    except Exception as _fw_err:
        _fw_log("panemenus.py:88", _fw_err)


def _fixed(path):
    from . import designlib, toolbox
    roots = [designlib.library_root(), designlib.parts_library() or ""]
    return toolbox.is_toolbox(path or "") or any(r and os.path.normcase(path) == os.path.normcase(r) for r in roots)


MARKS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/DesignLibrary"


def _marked(kind):
    raw = App.ParamGet(MARKS).GetString(kind, "")
    return [p for p in raw.split("|") if p]


def is_marked(path, kind):
    """kind "FormingToolsFolders" or "AssembliesFolders": the folder or one above it is ticked."""
    n = os.path.normcase(os.path.abspath(path or ""))
    for p in _marked(kind):
        q = os.path.normcase(os.path.abspath(p))
        if n == q or n.startswith(q.rstrip("\\/") + os.sep):
            return True
    return False


def set_marked(path, kind, on):
    have = [p for p in _marked(kind) if os.path.normcase(p) != os.path.normcase(path)]
    if on:
        have.append(path)
    App.ParamGet(MARKS).SetString(kind, "|".join(have))


def _delete_folder(page, path):
    from . import designlib
    if path in designlib.locations():
        designlib.remove_location(path)        # an added folder: off the list, the files stay
        _refresh(page)
        return True
    return _trash(page, path)


def folder_properties(page, path):
    files = dirs = size = 0
    for root, ds, fs in os.walk(path):
        dirs += len(ds)
        for f in fs:
            files += 1
            try:
                size += os.path.getsize(os.path.join(root, f))
            except OSError as _fw_err:
                _fw_log("panemenus.py:140", _fw_err)
    box = QtWidgets.QMessageBox(page)
    box.setObjectName("SWDesignLibraryFolderProperties")
    box.setWindowTitle("Properties")
    marks = [t for t, k in (("Forming Tools Folder", "FormingToolsFolders"), ("Assemblies Folder", "AssembliesFolders"))
             if is_marked(path, k)]
    box.setText("%s\n\nLocation: %s\nContains: %d files, %d folders\nSize: %.1f KB%s" % (
        os.path.basename(path.rstrip("/\\")) or path, path, files, dirs, size / 1024.0,
        ("\nUsed as: " + ", ".join(marks)) if marks else ""))
    box.exec_() if hasattr(box, "exec_") else box.exec()
    return box


def _check(menu, text, on, run, enabled=True):
    a = menu.addAction(text)
    a.setCheckable(True)
    a.setChecked(bool(on))
    a.setEnabled(bool(enabled))
    a.triggered.connect(lambda checked=False: QtCore.QTimer.singleShot(0, lambda: run(checked)))
    return a


def folder_menu(page, item):
    from . import designlib
    path = item.data(0, designlib.ROLE) if item is not None else None
    menu = QtWidgets.QMenu(page)
    menu.setObjectName("SWToolMenu_DesignLibraryFolder")
    if item is not None:
        page.tree.setCurrentItem(item)
    local = bool(path) and os.path.isdir(path)
    _add(menu, "Add Existing Folder...", lambda: page.do_location())
    menu.addSeparator()
    _add(menu, "Open Folder...", lambda: _explore(path), local)
    menu.addSeparator()
    for text, kind in (("Forming Tools Folder", "FormingToolsFolders"), ("Assemblies Folder", "AssembliesFolders")):
        _check(menu, text, local and path in _marked(kind),
               lambda on, kind=kind: set_marked(path, kind, on), local)
    menu.addSeparator()
    _add(menu, "New Folder", page.do_folder, local)
    menu.addSeparator()
    added = path in designlib.locations()
    _add(menu, "Delete", lambda: _delete_folder(page, path), local and (added or not _fixed(path)))
    _add(menu, "Rename", lambda: _rename(page, path), local and not _fixed(path) and not added)
    menu.addSeparator()
    _add(menu, "Properties", lambda: folder_properties(page, path), local)
    return menu


def file_menu(page, files, pos):
    from . import designlib, toolbox
    it = files.itemAt(pos)
    path = it.data(designlib.ROLE) if it is not None else None
    if path and toolbox.is_toolbox(path):
        build = getattr(files, "_fw_build_menu", None)
        return build(pos) if build is not None else None
    menu = QtWidgets.QMenu(files)
    menu.setObjectName("SWToolMenu_DesignLibraryFile")
    if not path:
        _add(menu, "Add to Library", page.do_add, App.ActiveDocument is not None)
        return menu
    _add(menu, "Open", lambda: App.openDocument(path) if path.lower().endswith(".fcstd") else Gui.open(path))
    _add(menu, "Insert", lambda: designlib.insert(path), App.ActiveDocument is not None)
    menu.addSeparator()
    _add(menu, "Rename", lambda: _rename(page, path))
    _add(menu, "Delete", lambda: _trash(page, path))
    menu.addSeparator()
    _add(menu, "Explore", lambda: _explore(path))
    return menu


class _Filter(QtCore.QObject):
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() != QtCore.QEvent.ContextMenu or not isinstance(obj, QtWidgets.QWidget):
            return False
        view = obj if isinstance(obj, QtWidgets.QAbstractItemView) else obj.parentWidget()
        if not isinstance(view, QtWidgets.QAbstractItemView) or view.objectName() not in (
                "SWDesignLibraryFolders", "SWDesignLibraryFiles"):
            return False
        try:
            page = _page(view)
            if page is None:
                return False
            pos = event.pos() if obj is view.viewport() else view.viewport().mapFrom(obj, event.pos())
            if view.objectName() == "SWDesignLibraryFolders":
                menu = folder_menu(page, view.itemAt(pos))
            else:
                menu = file_menu(page, view, pos)
            if menu is None:
                return True
            LAST[0] = menu
            menu.popup(event.globalPos())
            return True
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Design Library menu: %s\n" % error)
            return False


_FILTER = []


def install():
    if _FILTER:
        return _FILTER[0]
    f = _Filter(QtWidgets.QApplication.instance())
    try:
        from . import events      # the add-on's one application filter (interface land263)
        events.register("panemenus", (QtCore.QEvent.ContextMenu,), f.eventFilter)
    except ImportError:          # only without the shared dispatcher: never both (each event would run twice)
        QtWidgets.QApplication.instance().installEventFilter(f)
    _FILTER.append(f)
    return f
