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
from PySide import QtCore, QtGui, QtWidgets

from . import asmcore as ac
from . import selguard

NOT_FOR = ("Width", "Symmetric", "Hinge")    # mates made of more than two picks: edit them instead


def can_replace(joint):
    return ac.mate_type(joint) not in NOT_FOR


def refs_of(joint):
    return [(r[0], r[1][0]) for r in (joint.Reference1, joint.Reference2)]


def replace_entity(asm, joint, index, new_ref):
    """The mate's entity number index (0 or 1) becomes new_ref = (component, element).
    Returns None when it solves, else the message to show (the mate is left as it was)."""
    import UtilsAssembly
    kind = ac.mate_type(joint)
    old = refs_of(joint)
    refs = list(old)
    refs[index] = new_ref
    if refs[0][0] is refs[1][0]:
        return "Both entities of a mate must be on different components."
    shapes = [ac.element(c, e) for c, e in refs]
    if kind not in ac.allowed(shapes[0], shapes[1], refs) and kind not in ac.VIRTUAL:
        return "A %s mate cannot use this entity." % kind
    before = UtilsAssembly.saveAssemblyPartsPlacements(asm)
    message = _apply(asm, joint, kind, refs, before)
    if message is not None:
        try:
            _apply(asm, joint, kind, old, before)       # back as it was
        except Exception:
            # the old entity is gone (a mate lost in Replace Components): keep the old names
            joint.Reference1 = (old[0][0], [old[0][1], old[0][1]])
            joint.Reference2 = (old[1][0], [old[1][1], old[1][1]])
        UtilsAssembly.restoreAssemblyPartsPlacements(asm, before)
        ac._mark(joint, True)
    return message


def _apply(asm, joint, kind, refs, before):
    import UtilsAssembly
    if kind == "Slot":
        joint.Reference1 = (refs[0][0], [refs[0][1]])
        joint.Reference2 = (refs[1][0], [refs[1][1]])
        mode, value = ac.slot_values(joint)
        made, problem = ac.make_slot(asm, refs, mode, value, joint=joint)
        return problem if made is not None else (problem or ac.OVER_MESSAGE)
    if kind in ac.LIMITS:
        data = ac.limit_values(joint)
        made, problem = ac.make_limit(asm, kind, refs, data[1], data[2], joint=joint)
        return problem if made is not None else (problem or ac.OVER_MESSAGE)
    offsets = (App.Placement(joint.Offset1), App.Placement(joint.Offset2))
    joint.Proxy.setJointConnectors(joint, [[c, [e, e]] for c, e in refs])
    UtilsAssembly.restoreAssemblyPartsPlacements(asm, before)     # FreeCAD's connect moves parts
    if kind == "Profile Center":
        joint.Offset1, joint.Offset2 = offsets
    if kind == "Universal Joint":
        ac.cross(joint)
    if kind == "Rack Pinion":
        ac.rack_first(joint)
    ok = ac.solve(asm, before)
    if ok and kind in ("Rack Pinion", "Screw"):
        ac.couple(asm, joint)
        ok = ac.solve(asm, before)
    if not ok or not ac.satisfied(joint):
        return ac.OVER_MESSAGE
    return None


def _name(ref):
    from .asmpm import instance_name
    return "%s@%s" % (ref[1], instance_name(ref[0].Label))


class ReplacePanel:
    def __init__(self, asm, joint):
        from . import asmpm
        self.asm, self.joint, self.doc = asm, joint, asm.Document
        box, lay = asmpm._box("Mate Entities", "Replace Mate Entities", "ASSEMBLIES_MATE")
        lay.addWidget(QtWidgets.QLabel(joint.Label))
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_ReplaceEntities")
        self.list.setStyleSheet(asmpm.PICK_STYLE)
        self.list.setFixedHeight(asmpm._rows(self.list, 2))
        lay.addWidget(self.list)
        hint = QtWidgets.QLabel("Select an entity, then select its replacement in the graphics area.")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.flip = QtWidgets.QPushButton("Flip Mate Alignment")
        self.flip.setObjectName("FW_ReplaceFlip")
        # no greyed controls: a mechanical mate has no alignment to flip, so the button is not there
        self.flip.setVisible(ac.mate_type(joint) not in ac.MECHANICAL + ac.VIRTUAL)
        self.flip.clicked.connect(self._flip)
        lay.addWidget(self.flip)
        self.error = QtWidgets.QLabel("")
        self.error.setObjectName("FW_ReplaceError")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #d04040;")
        self.error.hide()
        lay.addWidget(self.error)
        self.form = [box]
        self._fill()
        self.list.setCurrentRow(0)
        self.doc.openTransaction("Replace Mate Entities")
        try:
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self, 0)
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise

    def _fill(self):
        row = max(0, self.list.currentRow())
        self.list.clear()
        for ref in refs_of(self.joint):
            self.list.addItem(_name(ref))
        self.list.setCurrentRow(row)

    def addSelection(self, doc, obj, sub, pnt):
        if doc != self.doc.Name:
            return
        self.doc.Name      # its document closed: this raises here and selguard drops the observer
        QtCore.QTimer.singleShot(0, lambda: selguard.quiet(lambda: self._pick(self.doc.getObject(obj), sub)))

    def removeSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass

    def _pick(self, root, sub):
        if root is None or not sub:
            return
        ref = ac.reference(self.asm, root, sub)
        if ref is None:
            return
        problem = replace_entity(self.asm, self.joint, max(0, self.list.currentRow()), ref)
        self._show(problem)
        self._fill()
        Gui.Selection.clearSelection()

    def _flip(self):
        ac.flip(self.asm, self.joint)
        self._show(None if not ac.mate_error(self.joint) else ac.OVER_MESSAGE)

    def _show(self, text):
        self.error.setText(text or "")
        self.error.setVisible(bool(text))

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmreplace.py:171", _fw_err)

    def accept(self):
        self._close()
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        _refresh()
        return True

    def reject(self):
        self._close()
        self.doc.abortTransaction()
        ac.solve(self.asm)
        Gui.Control.closeDialog()
        _refresh()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


class MatedEntitiesPanel:
    ""




    def __init__(self, asm, comps, lost=()):
        from . import asmpm, whatswrong
        self.asm, self.doc = asm, asm.Document
        self.comps = list(comps)
        self.lost = {j.Name for j in lost}
        self.rows = []          # (joint, index of the entity on the replaced component)
        for j in ac.mates(asm):
            for i, prop in enumerate(("Reference1", "Reference2")):
                ref = getattr(j, prop, None)
                if ref and ref[0] in self.comps:
                    self.rows.append((j, i))
                    break
        box, lay = asmpm._box("Mated Entities", "Mated Entities", "ASSEMBLIES_MATE")
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setObjectName("FW_MatedEntities")
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setFixedHeight(asmpm._rows(self.tree, 6))
        lay.addWidget(self.tree)
        rbox, rl = asmpm._box("Replacement Mate Entity")
        self.replacement = QtWidgets.QListWidget()
        self.replacement.setObjectName("FW_MatedReplacement")
        self.replacement.setStyleSheet(asmpm.PICK_STYLE)
        self.replacement.setFixedHeight(asmpm._rows(self.replacement, 1))
        rl.addWidget(self.replacement)
        hint = QtWidgets.QLabel("Select a mated entity above, then its replacement in the graphics area.")
        hint.setWordWrap(True)
        rl.addWidget(hint)
        self.flip = QtWidgets.QPushButton("Flip Mate Alignment")
        self.flip.setObjectName("FW_MatedFlip")
        self.flip.clicked.connect(self._flip)
        rl.addWidget(self.flip)
        self.error = QtWidgets.QLabel("")
        self.error.setObjectName("FW_MatedError")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #d04040;")
        self.error.hide()
        rl.addWidget(self.error)
        self._ok_icon = QtGui.QIcon(":/icons/edit_OK.svg")
        self._bad_icon = whatswrong.error_icon()
        self.form = [box, rbox]
        self._fill()
        self.tree.currentItemChanged.connect(lambda *_a: self._picked_row())
        first = next((k for k, (j, _i) in enumerate(self.rows) if j.Name in self.lost), 0)
        self.select(first)
        self.doc.openTransaction("Mated Entities")
        try:
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self, 0)
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise

    def _fill(self):
        keep = self.current_row()
        self.tree.blockSignals(True)
        self.tree.clear()
        for k, (j, i) in enumerate(self.rows):
            it = QtWidgets.QTreeWidgetItem([j.Label.split(" (")[0]])
            it.setIcon(0, self._bad_icon if j.Name in self.lost else self._ok_icon)
            it.setData(0, QtCore.Qt.UserRole, k)
            ref = refs_of(j)[i]
            text = _name(ref)
            lost_name = getattr(j, "FwLostEntity", "") or ""
            if j.Name in self.lost and lost_name.startswith("%d:" % i):
                text = "%s (missing)" % _name((ref[0], lost_name.split(":", 1)[1]))
            ch = QtWidgets.QTreeWidgetItem([text])
            ch.setData(0, QtCore.Qt.UserRole, k)
            it.addChild(ch)
            self.tree.addTopLevelItem(it)
            it.setExpanded(True)
        self.tree.blockSignals(False)
        if keep is not None:
            self.select(keep)

    def current_row(self):
        it = self.tree.currentItem() if hasattr(self, "tree") else None
        return it.data(0, QtCore.Qt.UserRole) if it is not None else None

    def select(self, k):
        if 0 <= k < self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(k))
            self._picked_row()

    def _picked_row(self):
        k = self.current_row()
        self.replacement.clear()
        if k is None:
            return
        j, _i = self.rows[k]
        self.flip.setVisible(ac.mate_type(j) not in ac.MECHANICAL + ac.VIRTUAL)     # not greyed: not there

    def status(self):
        """[(mate label, "ok" / "error")] in the list's order (checks)."""
        return [(j.Label.split(" (")[0], "error" if j.Name in self.lost else "ok") for j, _i in self.rows]

    def addSelection(self, doc, obj, sub, pnt):
        if doc != self.doc.Name:
            return
        self.doc.Name      # its document closed: this raises here and selguard drops the observer
        QtCore.QTimer.singleShot(0, lambda: selguard.quiet(lambda: self._pick(self.doc.getObject(obj), sub)))

    def removeSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass

    def _pick(self, root, sub):
        if root is None or not sub:
            return
        ref = ac.reference(self.asm, root, sub)
        if ref is not None:
            self.replace(ref)
        Gui.Selection.clearSelection()

    def replace(self, ref, k=None):
        """The picked row's entity becomes ref = (component, element). None when it solved."""
        k = self.current_row() if k is None else k
        if k is None:
            return "Select a mated entity first."
        j, i = self.rows[k]
        was = bool(getattr(j, "Suppressed", False))
        if hasattr(j, "Suppressed") and j.Name in self.lost:
            j.Suppressed = False
        try:
            problem = replace_entity(self.asm, j, i, ref)
        except Exception as error:
            problem = "The mate cannot use this entity (%s)." % error
        if problem is None:
            self.lost.discard(j.Name)
            if "FwLostEntity" in j.PropertiesList:
                j.FwLostEntity = ""
            self.replacement.clear()
            self.replacement.addItem(_name(ref))
        elif hasattr(j, "Suppressed"):
            j.Suppressed = was
        self._show(problem)
        self._fill()
        return problem

    def _flip(self):
        k = self.current_row()
        if k is None:
            return
        j, _i = self.rows[k]
        ac.flip(self.asm, j)
        self._show(None if not ac.mate_error(j) else ac.OVER_MESSAGE)

    def _show(self, text):
        self.error.setText(text or "")
        self.error.setVisible(bool(text))

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmreplace.py:351", _fw_err)

    def accept(self):
        self._close()
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        _refresh()
        return True

    def reject(self):
        self._close()
        self.doc.abortTransaction()
        ac.solve(self.asm)
        Gui.Control.closeDialog()
        _refresh()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


def mated_entities(asm, comps, lost=()):
    """The Mated Entities PM for the replaced components."""
    from . import asmui
    try:
        App.closeActiveTransaction(True)
    except Exception as _fw_err:
        _fw_log("asmreplace.py:378", _fw_err)
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    asmui.activate(asm)
    panel = MatedEntitiesPanel(asm, comps, lost)
    Gui.Control.showDialog(panel)
    return panel


def _refresh():
    try:
        from . import asmmenu
        asmmenu._refresh()
    except Exception as _fw_err:
        _fw_log("asmreplace.py:392", _fw_err)


def replace_entities(joint):
    from . import asmui
    asm = ac.assembly_of(joint.Document)
    if asm is None:
        return None
    try:
        App.closeActiveTransaction(True)
    except Exception as _fw_err:
        _fw_log("asmreplace.py:403", _fw_err)
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    asmui.activate(asm)
    panel = ReplacePanel(asm, joint)
    Gui.Control.showDialog(panel)
    return panel
