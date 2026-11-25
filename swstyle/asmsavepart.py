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

Qt = QtCore.Qt
OPEN = []


def _part_name(comp):
    """[Part1^Assem1]<1> -> Part1"""
    label = comp.Label.split("<")[0].strip("[]")
    return label.split("^")[0] or "Part1"


def _new_doc(path):
    """The new part file's document. pkg300: made before the Save Part step opens (a document made
    inside an Undo step takes a share of it), with no Undo of its own until it holds the part."""
    name = os.path.splitext(os.path.basename(path))[0]
    new = App.newDocument(name.replace(" ", "_"))
    new.UndoMode = 0
    return new


def save_external(asm, comp, path, new=None):
    """The virtual component's part into its own file at path; the component then links it.
    new: an empty document made for it before the step opened (else one is made here)."""
    from . import asminsert
    if not asminsert.is_virtual(comp):
        return None
    inner = comp.LinkedObject
    name = os.path.splitext(os.path.basename(path))[0]
    if new is None or App.listDocuments().get(new.Name) is not new:
        new = _new_doc(path)
    new.UndoMode = 0        # pkg300: the new part file keeps no share of the assembly's Save Part step
    new.saveAs(path)            # FreeCAD copies only into a saved document when links come along
    copies = new.copyObject(inner, True)
    copy = copies[0] if isinstance(copies, (list, tuple)) else copies
    copy.Label = name
    if copy.ViewObject is not None:
        copy.ViewObject.Visibility = True
    new.recompute()
    try:
        from . import asmextref
        asmextref._remember_refs(new)       # the copies have names of their own
    except Exception:
        pass
    new.saveAs(path)
    from . import asmpattern
    asmpattern.own_undo_after_step(new)     # pkg300
    comp.LinkedObject = copy
    setattr(comp, asminsert.VIRTUAL_PROP, False)
    base, _, inst = comp.Label.rpartition("<")
    comp.Label = "%s<%s" % (name, inst) if base else name
    doc = asm.Document
    # the virtual copy left in the assembly goes, with what it held
    leftovers = [inner] + [o for o in getattr(inner, "OutListRecursive", []) if o.Document is doc]
    names = [o.Name for o in leftovers if o.Document is doc]
    grew = True
    while grew:         # what hangs only on them goes too (a sketch's centerlines keep it otherwise)
        grew = False
        for o in doc.Objects:
            if o is comp or o.Name in names or not o.OutList or o.hasExtension("App::GroupExtension"):
                continue        # a folder that held only the part stays: it is the user's
            if all(x.Name in names for x in o.OutList):
                names.insert(0, o.Name)
                grew = True
    for name in names:
        o = doc.getObject(name)     # a body's removal takes its Origin with it
        if o is None or any(p is comp for p in o.InList):
            continue
        try:
            if not [p for p in o.InList if p.Name not in names]:
                doc.removeObject(name)
        except Exception as _fw_err:
            _fw_log("asmsavepart.py:67", _fw_err)
    doc.recompute()
    return new


class SaveAsDialog(QtWidgets.QDialog):
    def __init__(self, asm, comps, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        OPEN.append(self)
        self.asm, self.comps = asm, list(comps)
        self.setObjectName("FW_SavePartExternal")
        self.setWindowTitle("Save As")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Save the virtual parts to their own files:"))
        self.table = QtWidgets.QTableWidget(len(self.comps), 2)
        self.table.setObjectName("FW_SavePartTable")
        self.table.setHorizontalHeaderLabels(["File Name", "Path"])
        self.table.horizontalHeader().setStretchLastSection(True)
        start = os.path.dirname(asm.Document.FileName or "") or os.path.expanduser("~")
        for r, c in enumerate(self.comps):
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(_part_name(c) + ".FCStd"))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(start))
        lay.addWidget(self.table)
        row = QtWidgets.QHBoxLayout()
        same = QtWidgets.QPushButton("Same As Assembly")
        same.setObjectName("FW_SavePartSameAsAssembly")
        same.clicked.connect(self.same_as_assembly)
        row.addWidget(same)
        browse = QtWidgets.QPushButton("Specify Folder...")
        browse.setObjectName("FW_SavePartFolder")
        browse.clicked.connect(self._folder)
        row.addWidget(browse)
        row.addStretch(1)
        lay.addLayout(row)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def same_as_assembly(self):
        folder = os.path.dirname(self.asm.Document.FileName or "")
        for r in range(self.table.rowCount()):
            self.table.item(r, 1).setText(folder)

    def _folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Specify Folder")
        if folder:
            for r in range(self.table.rowCount()):
                self.table.item(r, 1).setText(folder)

    def _paths(self):
        """[(component, path)] as typed, or None when the user keeps the box to change a name."""
        try:        # a name still being typed in its cell counts (OK clicked straight after typing)
            ed = self.table.focusWidget()
            if isinstance(ed, QtWidgets.QLineEdit) and self.table.state() == QtWidgets.QAbstractItemView.EditingState:
                self.table.commitData(ed)
        except Exception as _fw_err:
            _fw_log("asmsavepart.py:_paths", _fw_err)
        out = []
        for r, c in enumerate(self.comps):
            name = self.table.item(r, 0).text().strip()
            if not name:
                name = _part_name(c)
            if not name.lower().endswith(".fcstd"):
                name += ".FCStd"
            folder = self.table.item(r, 1).text().strip() or os.path.dirname(self.asm.Document.FileName or "")
            path = os.path.normpath(os.path.join(folder, name))
            open_doc = [d for d in App.listDocuments().values()
                        if d.FileName and os.path.normcase(os.path.normpath(d.FileName)) == os.path.normcase(path)]
            if open_doc:
                QtWidgets.QMessageBox.warning(self, "Save As", "%s is open in FreeCAD. Close it, or type another "
                                              "name for the part." % os.path.basename(path))
                return None
            if os.path.exists(path):
                ask = QtWidgets.QMessageBox.question(self, "Save As", "%s already exists.\nDo you want to replace it?"
                                                     % os.path.basename(path),
                                                     QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                if ask != QtWidgets.QMessageBox.Yes:
                    return None
            if not os.path.isdir(folder):
                QtWidgets.QMessageBox.warning(self, "Save As", "The folder %s does not exist." % folder)
                return None
            out.append((c, path))
        return out

    def save(self):
        doc = self.asm.Document
        paths = self._paths()
        if paths is None:
            return
        made = {path: _new_doc(path) for c, path in paths}      # pkg300: before the step opens
        App.setActiveDocument(doc.Name)
        Gui.setActiveDocument(doc.Name)
        doc.openTransaction("Save Part (in External File)")
        try:
            for c, path in paths:
                try:
                    save_external(self.asm, c, path, made.pop(path))
                except Exception as error:
                    # never a silent OK: say what stopped it, the box stays for another name
                    QtWidgets.QMessageBox.warning(self, "Save As", "%s could not be saved:\n%s"
                                                  % (os.path.basename(path), error))
                    return
        finally:
            doc.commitTransaction()
            for d in made.values():         # not reached: an error stopped the loop
                if App.listDocuments().get(d.Name) is d and not d.Objects and not d.FileName:
                    App.closeDocument(d.Name)
        Gui.setActiveDocument(doc.Name)
        App.setActiveDocument(doc.Name)
        self.accept()

    def done(self, r):
        if self in OPEN:
            OPEN.remove(self)
        super().done(r)


def open_dialog(comps):
    from . import asminsert
    comps = [c for c in comps if asminsert.is_virtual(c)]
    if not comps:
        return None
    asm = ac.assembly_of(comps[0].Document)
    box = SaveAsDialog(asm, comps)
    box.open()
    return box
