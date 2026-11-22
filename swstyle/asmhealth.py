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
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import asmcore as ac

Qt = QtCore.Qt

CIRCULAR_TEXT = ("The assembly cannot be inserted: it would create a circular reference "
                 "(an assembly cannot contain itself).")
MISSING_TEXT = "The file \"%s\" for component %s could not be found."
OVER_TEXT = "This mate is over defining the assembly. Consider deleting some of the over defining mates."
MISSING_REF_TEXT = "The mate's reference is missing (the face, edge or vertex it used is gone)."
VIEW_MATES = "TreeViewMates"        # Tree Display: View Mates and Dependencies
ERRORS_FOLDER = "Mate Errors"

MISSING = {}        # assembly document name -> {component name: file name}
SKIPPED = {}        # assembly document name -> set of component names skipped in File Not Found
LAST_MESSAGE = []   # the last message box text (checks)


# ----------------------------------------------------------------------------- circular references
def documents_in(target, seen=None):
    """Every document target's components come from, all the way down."""
    seen = set() if seen is None else seen
    asm = target if target.TypeId == "Assembly::AssemblyObject" else None
    if asm is None:
        return seen
    for comp in ac.components(asm):
        try:
            linked = comp.LinkedObject
        except Exception:
            linked = None
        if linked is None:
            continue
        d = linked.Document
        if d.Name in seen:
            continue
        seen.add(d.Name)
        if linked.TypeId == "Assembly::AssemblyObject":
            documents_in(linked, seen)
    return seen


def would_circle(asm, target):
    """True when inserting target into asm makes an assembly contain itself."""
    if target is None or target.TypeId != "Assembly::AssemblyObject":
        return False
    if target is asm or target.Document is asm.Document:
        return True
    return asm.Document.Name in documents_in(target)


def circular(asm):
    """The components of asm whose files lead back to asm's own document."""
    out = []
    for comp in ac.components(asm):
        try:
            linked = comp.LinkedObject
        except Exception:
            linked = None
        if linked is not None and linked.TypeId == "Assembly::AssemblyObject" and \
                (linked.Document is asm.Document or asm.Document.Name in documents_in(linked)):
            out.append(comp)
    return out


def _message(title, text, icon=QtWidgets.QMessageBox.Warning):
    LAST_MESSAGE[:] = [text]
    if not App.GuiUp:
        return None
    box = QtWidgets.QMessageBox(icon, title, text, QtWidgets.QMessageBox.Ok, Gui.getMainWindow())
    box.setObjectName("FW_AssemblyMessage")
    box.setWindowModality(Qt.ApplicationModal)
    box.show()
    _boxes[:] = [box]           # kept alive (the auto-dismiss timer of optionsextras2 reads it later)
    return box


_boxes = []


# ----------------------------------------------------------------------------- missing files
def missing(doc):
    """{component name: file name} for components whose part file was not found."""
    return MISSING.get(doc.Name, {}) if doc is not None else {}


def find_missing(doc):
    from . import asmrefopts
    found = {}
    try:
        for link, fname, _obj in asmrefopts.missing_links(doc):
            found[link.Name] = fname
    except Exception as error:
        App.Console.PrintLog("FreeCAD: missing files: %s\n" % error)
    if found:
        MISSING[doc.Name] = found
    else:
        MISSING.pop(doc.Name, None)
    try:
        from . import asmgen
        asmgen.bump(doc)
    except Exception as _fw_err:
        _fw_log("asmhealth.py:142", _fw_err)
    return found


def _target_in(d, objname):
    obj = d.getObject(objname) if objname else None
    if obj is not None:
        return obj
    asm = ac.assembly_of(d)
    if asm is not None:
        return asm
    for o in d.Objects:
        if o.TypeId == "PartDesign::Body":
            return o
    for o in d.RootObjects:
        if hasattr(o, "Shape") and not o.Shape.isNull():
            return o
    return None


def relink(link, path, objname=None):
    """The component points at the file at path (opened if needed). True when it did."""
    try:
        d = next((x for x in App.listDocuments().values()
                  if x.FileName and os.path.exists(x.FileName) and os.path.samefile(x.FileName, path)), None)
        if d is None:
            d = App.openDocument(path)
        obj = _target_in(d, objname)
        if obj is None:
            return False
        # cfg130: an undo step, so the open's settling (it clears "changed" for up to 15 s) leaves the
        # assembly marked changed and Save keeps the new place
        doc = link.Document
        doc.openTransaction("Browse to the component")
        try:
            link.LinkedObject = obj
        finally:
            doc.commitTransaction()
        return True
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s: %s\n" % (path, error))
        return False


class MissingFileDialog(QtWidgets.QDialog):
    ""

    def __init__(self, doc, todo, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("FW_MissingFile")
        self.setWindowTitle("File Not Found")
        self.setWindowModality(Qt.ApplicationModal)
        self.doc_name = doc.Name
        self.todo = list(todo)          # [(component name, file name, object name)]
        self.results = []               # [(component name, "found" / "suppressed" / "skipped")] (not "done": that is QDialog.done, which Esc and the close box call)
        lay = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        icon = QtWidgets.QLabel()
        from . import msgicons
        icon.setPixmap(msgicons.pixmap("warning", 32))
        row.addWidget(icon, 0, Qt.AlignTop)
        self.text = QtWidgets.QLabel()
        self.text.setObjectName("FW_MissingText")
        self.text.setWordWrap(True)
        self.text.setMinimumWidth(380)
        row.addWidget(self.text, 1)
        lay.addLayout(row)
        self.browse_button = QtWidgets.QPushButton("Browse...")
        self.browse_button.setObjectName("FW_MissingBrowse")
        self.browse_button.setToolTip("Find the file yourself")
        self.suppress_button = QtWidgets.QPushButton("Suppress this component")
        self.suppress_button.setObjectName("FW_MissingSuppress")
        self.skip_button = QtWidgets.QPushButton("Skip this component")
        self.skip_button.setObjectName("FW_MissingSkip")
        self.skip_button.setToolTip("Open without it: the component stays in the tree with an error")
        for b in (self.browse_button, self.suppress_button, self.skip_button):
            lay.addWidget(b)
        self.all_box = QtWidgets.QCheckBox("Apply to all missing files")
        self.all_box.setObjectName("FW_MissingAll")
        lay.addWidget(self.all_box)
        self.browse_button.clicked.connect(lambda: self.browse())
        self.suppress_button.clicked.connect(lambda: self.suppress())
        self.skip_button.clicked.connect(lambda: self.skip())
        self._show_current()

    def doc(self):
        return App.listDocuments().get(self.doc_name)

    def current(self):
        return self.todo[0] if self.todo else None

    def _show_current(self):
        cur = self.current()
        doc = self.doc()
        if cur is None or doc is None:
            self._finish()
            return
        comp = doc.getObject(cur[0])
        self.text.setText("The file \"%s\" referenced by component %s was not found.\n\n"
                          "Browse to the file, suppress the component or skip it." %
                          (cur[1], comp.Label if comp is not None else cur[0]))

    def _next(self, what):
        cur = self.todo.pop(0)
        self.results.append((cur[0], what))
        self._show_current()

    def browse(self, path=None):
        cur = self.current()
        doc = self.doc()
        if cur is None or doc is None:
            return False
        if path is None:
            path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Open", os.path.dirname(doc.FileName or ""),
                                                             "FreeCAD files (*.FCStd)")
        if not path:
            return False
        link = doc.getObject(cur[0])
        if link is None or not relink(link, path, cur[2]):
            return False
        # the other missing files in the same folder are found too
        folder = os.path.dirname(path)
        rest = []
        for name, fname, objname in self.todo[1:]:
            other = os.path.join(folder, fname)
            lk = doc.getObject(name)
            if lk is not None and os.path.exists(other) and relink(lk, other, objname):
                self.results.append((name, "found"))
            else:
                rest.append((name, fname, objname))
        self.todo = [self.todo[0]] + rest
        doc.recompute()
        self._next("found")
        return True

    def suppress(self):
        from . import asmcomp
        doc = self.doc()
        while self.current() is not None and doc is not None:
            comp = doc.getObject(self.current()[0])
            try:
                if comp is not None:
                    asmcomp.suppress(comp, True)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: suppress %s: %s\n" % (self.current()[0], error))
            self._next("suppressed")
            if not self.all_box.isChecked():
                break

    def skip(self):
        while self.current() is not None:
            SKIPPED.setdefault(self.doc_name, set()).add(self.current()[0])
            self._next("skipped")
            if not self.all_box.isChecked():
                break

    def _finish(self):
        doc = self.doc()
        if doc is not None:
            find_missing(doc)
        self.hide()
        QtCore.QTimer.singleShot(0, lambda n=self.doc_name: _after_missing(n))


def _after_missing(name):
    doc = App.listDocuments().get(name)
    if doc is None:
        return
    try:
        from . import asmui
        asmui.refresh()
    except Exception as _fw_err:
        _fw_log("asmhealth.py:305", _fw_err)
    if missing(doc):
        try:
            from . import whatswrong
            whatswrong.show(doc)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: What's Wrong: %s\n" % error)


_dialog = []


def open_missing(doc):
    """File Not Found for every missing component of doc; None when nothing is missing."""
    from . import asmrefopts
    todo = [(link.Name, fname, objname) for link, fname, objname in asmrefopts.missing_links(doc)]
    if not todo:
        MISSING.pop(doc.Name, None)
        return None
    find_missing(doc)
    if not App.GuiUp:
        return None
    dlg = MissingFileDialog(doc, todo)
    _dialog[:] = [dlg]
    dlg.show()
    return dlg


def dialog():
    return _dialog[0] if _dialog else None


# ----------------------------------------------------------------------------- the state, cached
_state = {}


def state(doc):
    """{"errors": set of mate names, "warnings": set, "error_mates": [joints], "missing": {...},
    "circular": [...]} for an assembly document; read at most every 0.4 s."""
    if doc is None:
        return None
    from . import asmgen
    now = (asmgen.gen(doc), id(doc))
    got = _state.get(doc.Name)
    if got is not None and (got[0] == now or asmgen.recomputing(doc)) and now[0] >= 0:
        return got[1]       # nothing changed (or a rebuild is running): the last answer
    asm = ac.assembly_of(doc)
    if asm is None:
        _state[doc.Name] = (now, None)
        return None
    from . import asmrefopts
    errors, warnings, error_mates = set(), set(), []
    as_error = asmrefopts.missing_colour() == asmrefopts.MISSING_ERROR
    try:
        for j in ac.mates(asm):
            if _mate_off(j):
                continue
            if ac.mate_error(j):
                errors.add(j.Name)
                error_mates.append(j)
            elif asmrefopts.missing_reference(j):
                (errors if as_error else warnings).add(j.Name)
                if as_error:
                    error_mates.append(j)
    except Exception as _fw_err:
        _fw_log("asmhealth.py:370", _fw_err)
    value = {"errors": errors, "warnings": warnings, "error_mates": error_mates,
             "missing": dict(missing(doc)), "circular": [c.Name for c in circular(asm)]}
    _state[doc.Name] = (now, value)
    return value


def forget(doc=None):
    if doc is None:
        _state.clear()
    else:
        _state.pop(doc.Name, None)


# ----------------------------------------------------------------------------- What's Wrong
def assembly_errors(doc):
    asm = ac.assembly_of(doc) if doc is not None else None
    if asm is None:
        return []
    from . import asmrefopts
    out = []
    for name, fname in missing(doc).items():
        comp = doc.getObject(name)
        if comp is not None and not _suppressed(comp):
            out.append((comp, MISSING_TEXT % (fname, comp.Label)))
    for comp in circular(asm):
        out.append((comp, "Circular reference: %s contains the assembly itself." % comp.Label))
    as_error = asmrefopts.missing_colour() == asmrefopts.MISSING_ERROR
    for j in ac.mates(asm):
        if _mate_off(j):
            continue
        if ac.mate_error(j):
            out.append((j, OVER_TEXT))
        elif as_error and asmrefopts.missing_reference(j):
            out.append((j, MISSING_REF_TEXT))
    return out


def assembly_warnings(doc):
    asm = ac.assembly_of(doc) if doc is not None else None
    if asm is None:
        return []
    from . import asmrefopts
    if asmrefopts.missing_colour() == asmrefopts.MISSING_ERROR:
        return []
    return [(j, MISSING_REF_TEXT) for j in ac.mates(asm)
            if not _mate_off(j) and not ac.mate_error(j) and asmrefopts.missing_reference(j)]


def _mate_off(joint):
    """Suppressed by the user (an over defining mate is also switched off for the solver, but it
    is still an error)."""
    try:
        from . import asmmenu
        return asmmenu.suppressed(joint)
    except Exception:
        return False


def _suppressed(comp):
    try:
        from . import asmcomp
        return asmcomp.is_suppressed(comp)
    except Exception:
        return False


def _patch_whatswrong():
    from . import whatswrong
    if getattr(whatswrong, "_fw_asm", False):
        return
    errors0, warnings0 = whatswrong.errors, whatswrong.warnings

    def errors(doc):
        out = errors0(doc)
        try:
            mine = assembly_errors(doc)
            missing_objs = [o for o, t in mine if t.startswith('The file "')]

            out = [r for r in out if r[0] not in missing_objs]
            out = out + [r for r in mine if r[0] not in [o for o, _t in out]]
        except Exception as error:
            App.Console.PrintLog("FreeCAD: What's Wrong (assembly): %s\n" % error)
        return out

    def warnings(doc):
        out = warnings0(doc)
        try:
            out = out + assembly_warnings(doc)
        except Exception as _fw_err:
            _fw_log("asmhealth.py:456", _fw_err)
        return out

    whatswrong.errors, whatswrong.warnings = errors, warnings
    cls = whatswrong.WhatsWrongDialog
    sync0, xpert0 = cls._sync_xpert, cls.feature_xpert

    def _mate_mode(self):
        doc = App.listDocuments().get(self.doc_name)
        st = state(doc) if doc is not None else None
        return bool(st and st["error_mates"])

    def _sync_xpert(self):
        if _mate_mode(self):
            self.xpert.setText("MateXpert")
            self.xpert.setToolTip("Find the mates that keep the assembly from solving")
            self.xpert.setEnabled(True)
            return
        self.xpert.setText("FeatureXpert")
        self.xpert.setToolTip("Repair failed fillets, chamfers and drafts")
        return sync0(self)

    def feature_xpert(self, quiet=False):
        if _mate_mode(self):
            return run_matexpert(App.listDocuments().get(self.doc_name))
        return xpert0(self, quiet)

    cls._sync_xpert, cls.feature_xpert = _sync_xpert, feature_xpert
    whatswrong._fw_asm = True


def run_matexpert(doc=None):
    doc = doc or App.ActiveDocument
    try:
        if doc is not None:
            App.setActiveDocument(doc.Name)
            Gui.ActiveDocument = Gui.getDocument(doc.Name)
    except Exception as _fw_err:
        _fw_log("asmhealth.py:494", _fw_err)
    from . import asmevaluate
    if Gui.Control.activeDialog():
        try:
            Gui.Control.closeDialog()
        except Exception as _fw_err:
            _fw_log("asmhealth.py:500", _fw_err)
    return asmevaluate._show_matexpert()


# ----------------------------------------------------------------------------- the tree
def view_mates_on():
    from . import paths
    return paths.params().GetBool(VIEW_MATES, False)


def set_view_mates(on):
    from . import paths
    paths.params().SetBool(VIEW_MATES, bool(on))
    _rebuild_tree()


def _rebuild_tree():
    try:
        mw = Gui.getMainWindow()
        for t in mw.findChildren(QtWidgets.QTreeView, "SWFeatureTree"):
            m = t.model()
            if hasattr(m, "rebuild"):
                m.rebuild()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: tree rebuild: %s\n" % error)


def _renumber(node):
    for i, c in enumerate(node.children):
        c.row = i
        c.parent = node


def _mates_node(model):
    part = model.part
    if part is None:
        return None
    for c in part.children:
        o = getattr(c, "obj", None)
        if o is not None and getattr(o, "TypeId", "") == "Assembly::JointGroup":
            return c
    return None


def _mate_rows(node, out):
    """{joint name: node} under the Mates folder (its own folders too)."""
    for c in node.children:
        o = getattr(c, "obj", None)
        if o is not None and ac.mate_type(o):
            out.setdefault(o.Name, c)
        _mate_rows(c, out)
    return out


def _icon_of(node):
    from PySide import QtCore as _qc
    if node.src is not None:
        src = _qc.QModelIndex(node.src)
        if src.isValid():
            return src.data(Qt.DecorationRole)
    return node.icon


def lay_out_extra(model, doc):
    """After asmui's layout: the Mate Errors folder and View Mates and Dependencies."""
    from . import fmtree
    asm = ac.assembly_of(doc)
    folder = _mates_node(model)
    if asm is None or folder is None:
        return
    forget(doc)
    st = state(doc)
    rows = _mate_rows(folder, {})
    if st and st["error_mates"]:
        icon = _icon_of(folder)
        if isinstance(icon, QtGui.QIcon):
            icon = fmtree._with_error_mark(icon)
        ef = fmtree.Node(text=ERRORS_FOLDER, icon=icon,
                         tip="%d mate(s) in error: they keep the assembly from solving" % len(st["error_mates"]))
        for j in st["error_mates"]:
            n = rows.get(j.Name)
            if n is not None and n.src is not None:
                model._mirror(ef, QtCore.QModelIndex(n.src), doc, link=True)
        folder.children.insert(0, ef)
        _renumber(folder)
    if view_mates_on():
        from . import asmmenu
        icon = _icon_of(folder)
        for c in list(model.part.children):
            comp = getattr(c, "obj", None)
            if comp is None or comp not in ac.components(asm):
                continue
            mates = [j for j in asmmenu.mates_of(comp) if j.Name in rows]
            if not mates:
                continue
            mf = fmtree.Node(text="Mates", icon=icon, tip="The mates of %s" % comp.Label)
            for j in mates:
                n = rows[j.Name]
                if n.src is not None:
                    model._mirror(mf, QtCore.QModelIndex(n.src), doc, link=True)
            c.children.insert(0, mf)
            _renumber(c)


def _patch_layout():
    from . import asmui
    if getattr(asmui, "_fw_health", False):
        return
    layout0 = asmui.assembly_layout

    def assembly_layout(model, doc):
        done = layout0(model, doc)
        if done:
            try:
                lay_out_extra(model, doc)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: assembly tree (mate errors): %s\n" % error)
        return done

    asmui.assembly_layout = assembly_layout
    asmui._fw_health = True


def _patch_icons():
    from . import fmtree
    if getattr(fmtree.Model, "_fw_health", False):
        return
    data0 = fmtree.Model.data

    def data(self, index, role=Qt.DisplayRole):
        try:
            value = data0(self, index, role)
        except Exception as error:      # an error out of a Qt override would crash FreeCAD
            if role == Qt.DisplayRole and not isinstance(error, ReferenceError):
                App.Console.PrintWarning("FreeCAD: tree row: %r\n" % (error,))
            return None
        if role not in (Qt.DecorationRole, Qt.ToolTipRole) or not index.isValid():
            return value
        try:
            doc = getattr(self, "doc", None)
            st = state(doc) if doc is not None and doc.Name in App.listDocuments() else None
            if not st:
                return value
            node = self.node(index)
            obj = getattr(node, "obj", None)
            mark = None
            tip = None
            if node is self.part:
                if st["errors"] or st["missing"] or st["circular"]:
                    mark = "error"
                elif st["warnings"]:
                    mark = "warning"
            elif obj is not None and getattr(obj, "TypeId", "") == "Assembly::JointGroup":
                mark = "error" if st["errors"] else "warning" if st["warnings"] else None
            elif obj is not None and obj.Name in st["errors"]:
                mark, tip = "error", OVER_TEXT if ac.mate_error(obj) else MISSING_REF_TEXT
            elif obj is not None and obj.Name in st["warnings"]:
                mark, tip = "warning", MISSING_REF_TEXT
            elif obj is not None and (obj.Name in st["missing"] or obj.Name in st["circular"]):
                if obj.Name in st["missing"] and _suppressed(obj):
                    return value
                mark = "error"
                tip = (MISSING_TEXT % (st["missing"][obj.Name], obj.Label)) if obj.Name in st["missing"] \
                    else "Circular reference"
            if role == Qt.ToolTipRole:
                return tip or value
            if mark and isinstance(value, QtGui.QIcon):
                return fmtree._with_error_mark(value, warning=(mark == "warning"))
        except ReferenceError:
            pass                    # a row of an object deleted while the tree repaints (document closing)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: mate marks: %s\n" % error)
        return value

    fmtree.Model.data = data
    fmtree.Model._fw_health = True


# ----------------------------------------------------------------------------- menus
def _patch_menus():
    from . import asmmenu, fmmenu
    if getattr(asmmenu, "_fw_health", False):
        return
    entries0 = asmmenu.menu_entries

    def _has_errors(doc):
        try:
            asm = ac.assembly_of(doc)
            return asm is not None and any(ac.mate_error(j) for j in ac.mates(asm))
        except Exception:
            return True

    def menu_entries(original, shell, target, view):
        items = entries0(original, shell, target, view)
        try:
            k = asmmenu.kind(target)
            if k == "matesfolder" and _has_errors(target.Document):

                # fine; it is offered once a mate is in error
                items = list(items)
                items.insert(1, ("MateXpert", "MateXpert...", lambda: run_matexpert(target.Document), True))
            elif k == "mate" and ac.mate_error(target):
                items = list(items)
                items.insert(1, ("MateXpert", "MateXpert...", lambda: run_matexpert(target.Document), True))
            elif k == "component":
                items = list(items)
                sub = ac.is_subassembly(target)
                label = "Rename Assembly" if sub else "Rename Part"
                at = next((i + 1 for i, it in enumerate(items) if it[0] == "ComponentProperties"), len(items))
                if not any(it[0] == "RenamePart" for it in items):
                    items.insert(at, ("RenamePart", label, lambda: rename(target), True))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: assembly menu (MateXpert/Rename): %s\n" % error)
        return items

    asmmenu.menu_entries = menu_entries
    tdm0 = fmmenu._tree_display_menu

    def _tree_display_menu(menu):
        doc = App.ActiveDocument
        if doc is not None and ac.assembly_of(doc) is not None:
            on = view_mates_on()
            group = QtGui.QActionGroup(menu)
            group.setExclusive(True)
            for label, value in (("View Features", False), ("View Mates and Dependencies", True)):
                a = menu.addAction(label)
                a.setCheckable(True)
                a.setChecked(on == value)
                a.setObjectName("FW_TreeView" + ("Mates" if value else "Features"))
                group.addAction(a)
                a.triggered.connect(lambda _c=False, v=value: set_view_mates(v))
            menu._fw_group = group
            menu.addSeparator()
        return tdm0(menu)

    fmmenu._tree_display_menu = _tree_display_menu
    try:
        from . import rcpanes      # the right-click panes add MateXpert to every Mates folder
        additions0 = rcpanes.tree_additions

        def tree_additions(target, *more, **named):
            add = additions0(target, *more, **named)
            try:
                if asmmenu.kind(target) == "matesfolder" and not _has_errors(target.Document):
                    add = [e for e in add if e[0] != "MateXpert"]
            except Exception as _fw_err:
                _fw_log("asmhealth.py:746", _fw_err)
            return add

        rcpanes.tree_additions = tree_additions
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Mates folder MateXpert: %s\n" % error)
    asmmenu._fw_health = True


def rename(comp):
    """Rename Part: the component's row edited in place (the file follows with the option on)."""
    try:
        for t in Gui.getMainWindow().findChildren(QtWidgets.QTreeView, "SWFeatureTree"):
            if t.isVisible() and hasattr(t, "fm_rename"):
                t.fm_rename(comp)
                return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: rename: %s\n" % error)
    from . import fmmenu
    fmmenu.rename(None, comp)
    return True


# ----------------------------------------------------------------------------- Insert Components
def _patch_insert():
    from . import asmpm
    cls = asmpm.InsertComponentPanel
    if getattr(cls, "_fw_health", False):
        return
    saved0 = cls._saved

    def _saved(self, target):
        if would_circle(self.asm, target):
            _message("Insert Components", CIRCULAR_TEXT)
            return False
        return saved0(self, target)

    cls._saved = _saved
    cls._fw_health = True


def _patch_open():
    from . import asmrefopts
    if getattr(asmrefopts, "_fw_health", False):
        return
    after0 = asmrefopts.after_restore

    def after_restore(doc):
        out = after0(doc)
        try:
            if ac.assembly_of(doc) is not None:
                open_missing(doc)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: missing files: %s\n" % error)
        return out

    asmrefopts.after_restore = after_restore
    asmrefopts._fw_health = True


class _FeatureWatch:
    """A deleted Hole Series (or propagated assembly feature): its pieces in the parts go too
    (their cuts emptied; nothing is deleted from the part files)."""

    def slotDeletedObject(self, obj):
        try:
            from . import asmfeature as af
            if not af.is_feature(obj):
                return
            if getattr(obj, af.FEATURE_PROP, "") != "Series" and not getattr(obj, "Propagate", False):
                return
            name = obj.Document.Name
        except Exception:
            return
        QtCore.QTimer.singleShot(0, lambda: _clear(name))


def _clear(name):
    doc = App.listDocuments().get(name)
    asm = ac.assembly_of(doc) if doc is not None else None
    if asm is None:
        return
    try:
        from . import asmfeature as af
        af._clear_stale_propagated(asm)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: propagated cuts: %s\n" % error)


_watch = []


def _patch_features():
    if not _watch:
        _watch.append(_FeatureWatch())
        App.addDocumentObserver(_watch[0])


def install():
    for fn in (_patch_whatswrong, _patch_layout, _patch_icons, _patch_menus, _patch_insert, _patch_open,
               _patch_features):
        try:
            fn()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: assembly problems (%s): %s\n" % (fn.__name__, error))
