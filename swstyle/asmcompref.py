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
    from PySide import QtCore, QtWidgets
except ImportError:  # pragma: no cover
    Gui = None

KEY = "EditComponentReferences"
TEXT = "Edit Component References..."
TITLE = "Edit Component References"
NOT_FOUND = "(not found)"


def _ac():
    from . import asmcore
    return asmcore


def file_of(comp):
    """The file a component references, or "" when it cannot be told."""
    try:
        from . import asmunload
        if asmunload.is_unloaded(comp):
            return getattr(comp, asmunload.FILE_PROP, "") or ""
    except Exception as _fw_err:
        _fw_log("asmcompref.py:unloaded", _fw_err)
    try:
        d = getattr(comp.LinkedObject, "Document", None)
        if d is not None and d is not comp.Document:
            return d.FileName or ""
    except Exception as _fw_err:
        _fw_log("asmcompref.py:file", _fw_err)
    return ""


def references(asm):
    """[(file, [components])], in tree order of each file's first component."""
    out, at = [], {}
    for c in _ac().components(asm) if asm is not None else []:
        if getattr(c, "TypeId", "") not in ("App::Link", "Assembly::AssemblyLink"):
            continue
        f = file_of(c)
        if not f:
            continue
        key = os.path.normcase(f)
        if key not in at:
            at[key] = len(out)
            out.append((f, []))
        out[at[key]][1].append(c)
    return out


def _open(path):
    for d in App.listDocuments().values():
        if os.path.normcase(d.FileName or "") == os.path.normcase(path):
            return d
    return App.openDocument(path, hidden=True)


def apply_changes(asm, changes):
    """changes: {old file: new file}. Points every component of each old file at the new one, re-attaching
    its mates, in one undo step. Returns (components changed, mates not put back)."""
    from . import asmreplacecomp, asmspconfig
    todo = []
    for old, comps in references(asm):
        new = changes.get(old)
        if new and os.path.normcase(new) != os.path.normcase(old):
            todo.append((new, comps))
    if not todo:
        return [], []
    try:
        from . import asmunload
        for _new, comps in todo:
            for c in comps:
                if asmunload.is_unloaded(c):
                    asmunload.load(c, solve=False)
    except Exception as _fw_err:
        _fw_log("asmcompref.py:load", _fw_err)
    doc = asm.Document
    changed, lost = [], []
    doc.openTransaction(TITLE)
    try:
        for new, comps in todo:
            target = asmspconfig.main_object(_open(new))
            if target is None:
                App.Console.PrintWarning("FreeCAD: %s: nothing in %s to show\n" % (TITLE, os.path.basename(new)))
                continue
            done, gone = asmreplacecomp.replace(asm, comps, target, all_instances=False, reattach_mates=True)
            changed += list(done)
            lost += list(gone)
    finally:
        doc.commitTransaction()
    try:
        from . import asmui
        asmui.refresh()
    except Exception as _fw_err:
        _fw_log("asmcompref.py:refresh", _fw_err)
    return changed, lost


class Box(QtWidgets.QDialog if Gui is not None else object):
    COLUMNS = ("Component", "File name", "In folder")

    def __init__(self, asm, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.asm = asm
        self.setObjectName("FW_EditComponentReferences")
        self.setWindowTitle(TITLE)
        self.refs = references(asm)
        self.changes = {}
        lay = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTreeWidget(self)
        self.table.setObjectName("FW_ComponentReferences")
        self.table.setHeaderLabels(list(self.COLUMNS))
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        for f, comps in self.refs:
            names = ", ".join(c.Label for c in comps)
            row = QtWidgets.QTreeWidgetItem([names, os.path.basename(f) + ("" if os.path.exists(f) else " " + NOT_FOUND),
                                             os.path.dirname(f)])
            row.setData(0, QtCore.Qt.UserRole, f)
            row.setToolTip(0, names)
            self.table.addTopLevelItem(row)
        for k in range(len(self.COLUMNS)):
            self.table.resizeColumnToContents(k)
        self.table.itemDoubleClicked.connect(lambda *_: self.browse())
        if self.table.topLevelItemCount():
            self.table.setCurrentItem(self.table.topLevelItem(0))
        lay.addWidget(self.table)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        self.browse_button = buttons.addButton("Browse...", QtWidgets.QDialogButtonBox.ActionRole)
        self.browse_button.setObjectName("FW_ComponentReferencesBrowse")
        self.browse_button.clicked.connect(self.browse)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.resize(640, 320)

    def current_file(self):
        row = self.table.currentItem()
        return row.data(0, QtCore.Qt.UserRole) if row is not None else None

    def choose(self, old, new):
        """The row of file old now points at new (shown in bold until OK)."""
        self.changes[old] = new
        for k in range(self.table.topLevelItemCount()):
            row = self.table.topLevelItem(k)
            if row.data(0, QtCore.Qt.UserRole) == old:
                row.setText(1, os.path.basename(new))
                row.setText(2, os.path.dirname(new))
                f = row.font(1)
                f.setBold(True)
                row.setFont(1, f)
                row.setFont(2, f)

    def browse(self):
        old = self.current_file()
        if not old:
            return
        start = os.path.dirname(old) if os.path.isdir(os.path.dirname(old)) else ""
        new, _ = QtWidgets.QFileDialog.getOpenFileName(self, TITLE, start, "FreeCAD documents (*.FCStd *.fcstd)")
        if new:
            self.choose(old, new)

    def accept(self):
        changed, lost = apply_changes(self.asm, self.changes)
        if lost:
            try:
                Gui.getMainWindow().statusBar().showMessage(
                    "%s: %d mate%s could not be put back" % (TITLE, len(lost), "" if len(lost) == 1 else "s"), 8000)
            except Exception as _fw_err:
                _fw_log("asmcompref.py:status", _fw_err)
        super().accept()


_box = None


def open_box(asm):
    global _box
    _box = Box(asm)
    _box.show()
    return _box


def menu_item(asm):
    """(key, text, run, enabled), or None when no component references another file (no dead row)."""
    if not references(asm):
        return None
    return (KEY, TEXT, lambda: open_box(asm), True)
