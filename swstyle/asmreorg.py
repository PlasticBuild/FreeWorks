# -*- coding: utf-8 -*-
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

from PySide import QtCore, QtWidgets

from . import asmcore as ac


def _frame_of(sublink):
    from . import asmexplode as ax
    return ax.gplacement(sublink)


def _source(sublink):
    return getattr(sublink, "LinkedObject", None)


def _source_comp(sublink, inner):
    """The subassembly file's component that inner (this assembly's copy) shows."""
    src = _source(sublink)
    if src is None:
        return None
    pairs = dict(zip([m.Name for m in ac.sub_components(sublink)], ac.components(src)))
    return pairs.get(inner.Name)


def _resync(sublink):
    """FreeCAD's AssemblyLink copies its assembly's components when it recomputes: make it."""
    try:
        sublink.touch()
        src = _source(sublink)
        if src is not None:
            src.touch()
        sublink.Document.recompute()
        sublink.recompute()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: reorganize, subassembly update: %s\n" % error)


def _mates_among(asm, comps):
    inside, across = [], []
    for j in ac.mates(asm):
        owners = [r[0] for r in (getattr(j, "Reference1", None), getattr(j, "Reference2", None)) if r]
        hit = [o in comps for o in owners]
        if owners and all(hit):
            inside.append(j)
        elif any(hit):
            across.append(j)
    return inside, across


def _remake(asm, j, mapping):
    refs = [getattr(j, p) for p in ("Reference1", "Reference2")]
    kind = ac.mate_type(j)
    value = ac.distance_value(j) if kind == "Distance" else (getattr(j, "Angle", None) if kind == "Angle" else None)
    try:
        return ac.add_mate(asm, kind, (mapping[refs[0][0]], refs[0][1][0]), (mapping[refs[1][0]], refs[1][1][0]),
                           value=value, name=j.Label.split(" (")[0],
                           side=ac.distance_side(j) if kind == "Distance" else None)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: reorganize, mate %s: %s\n" % (j.Label, error))
        return None


def _part_of(comp):
    ""


    if comp.TypeId != "App::Link":
        return comp, None
    try:
        from . import asmcfginst
        if asmcfginst.is_copy(comp):
            return asmcfginst.source(comp), asmcfginst.configuration(comp)
    except Exception as _fw_err:
        _fw_log("asmreorg.py:99", _fw_err)
    return comp.LinkedObject, None


def _same_configuration(link, config):
    if not config:
        return
    try:
        from . import asmcfginst
        if asmcfginst.configuration(link) != config:
            asmcfginst.set_configuration(link, config)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: reorganize, configuration: %s\n" % error)


def into_subassembly(asm, comps, sublink):
    """Top-level comps move into sublink's assembly. Returns (moved count, mates removed)."""
    src = _source(sublink)
    comps = [c for c in comps if c in ac.components(asm) and c is not sublink and not ac.is_subassembly(c)]
    if src is None or not comps:
        return 0, 0
    frame = _frame_of(sublink).inverse()
    fixed = ac.grounded(asm)
    mapping = {}
    for c in comps:
        target, config = _part_of(c)
        link = ac.insert(src, target, frame.multiply(c.Placement))
        link.Placement = frame.multiply(c.Placement)
        _same_configuration(link, config)
        mapping[c] = link
        if c in fixed and link not in ac.grounded(src):
            ac.fix(src, link)
    inside, across = _mates_among(asm, comps)
    for j in inside:
        _remake(src, j, mapping)
    doc = asm.Document
    for j in inside + across:
        doc.removeObject(j.Name)
    for c in comps:
        if c in fixed:
            doc.removeObject(fixed[c].Name)
        doc.removeObject(c.Name)
    src.Document.recompute()
    ac.solve(src)
    if src.Document.FileName:
        src.Document.save()
    _resync(sublink)
    doc.recompute()
    ac.solve(asm)
    return len(comps), len(across)


def out_of_subassembly(asm, inners, sublink):
    """inners (sublink's components, as this assembly holds them) move up to asm."""
    from . import asmexplode as ax
    src = _source(sublink)
    if src is None:
        return 0, 0, []
    pairs = [(m, _source_comp(sublink, m)) for m in inners if m in ac.sub_components(sublink)]
    pairs = [(m, s) for m, s in pairs if s is not None]
    if not pairs:
        return 0, 0, []
    sources = [s for _m, s in pairs]
    fixed_src = ac.grounded(src)
    mapping = {}
    for m, s in pairs:
        target, config = _part_of(s)
        plc = ax.gplacement(m)
        link = ac.insert(asm, target, plc)
        link.Placement = plc
        _same_configuration(link, config)
        mapping[s] = link
    inside, across = _mates_among(src, sources)
    for j in inside:
        _remake(asm, j, mapping)
    sdoc = src.Document
    for j in inside + across:
        sdoc.removeObject(j.Name)
    for s in sources:
        if s in fixed_src:
            sdoc.removeObject(fixed_src[s].Name)
        sdoc.removeObject(s.Name)
    sdoc.recompute()
    ac.solve(src)
    if sdoc.FileName:
        sdoc.save()
    _resync(sublink)
    asm.Document.recompute()
    ac.solve(asm)
    links = [mapping[s] for s in sources]
    for link in links:                  # the subassembly's copy held the name until now
        want = ac._instance(asm, ac.part_name(link))
        if link.Label != want and not link.Label.startswith(want):
            continue
        link.Label = want
    return len(pairs), len(across), links


def holder(asm, comp):
    """The subassembly component holding comp (this assembly's copy), or None at the top level."""
    for c in ac.components(asm):
        if ac.is_subassembly(c) and comp in ac.sub_components(c):
            return c
    return None


def reorganize(asm, comps, target):
    """Moves comps to target: asm itself (the top level) or a subassembly component of asm.
    Returns (moved, mates removed)."""
    moved = removed = 0
    top = [c for c in comps if c in ac.components(asm)]
    by_holder = {}
    for c in comps:
        h = holder(asm, c)
        if h is not None and h is not target:
            by_holder.setdefault(h, []).append(c)
    for h, inners in by_holder.items():
        n, r, links = out_of_subassembly(asm, inners, h)
        moved, removed = moved + n, removed + r
        top += links
    if target is asm or target is None:
        return moved, removed
    n, r = into_subassembly(asm, [c for c in top if c is not target], target)
    if by_holder:
        moved -= sum(len(v) for v in by_holder.values())     # counted once, at the end
    return moved + n, removed + r


class ReorganizeBox(QtWidgets.QDialog):
    """Reorganize Components: Components to Move, Target Assembly, Move."""

    def __init__(self, asm, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.asm = asm
        self.setObjectName("SWReorganizeComponents")
        self.setWindowTitle("Reorganize Components")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Components to Move:"))
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setObjectName("SWReorganizeTree")
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        lay.addWidget(self.tree)
        lay.addWidget(QtWidgets.QLabel("Target Assembly:"))
        self.target = QtWidgets.QComboBox()
        self.target.setObjectName("SWReorganizeTarget")
        lay.addWidget(self.target)
        self.result = QtWidgets.QLabel()
        self.result.setObjectName("SWReorganizeResult")
        lay.addWidget(self.result)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        self.move_button = bb.addButton("Move", QtWidgets.QDialogButtonBox.ApplyRole)
        self.move_button.setObjectName("SWReorganizeMove")
        self.move_button.clicked.connect(self.move)
        bb.rejected.connect(self.reject)
        bb.button(QtWidgets.QDialogButtonBox.Close).clicked.connect(self.reject)
        lay.addWidget(bb)
        self.fill()

    def fill(self, keep=()):
        self.tree.clear()
        self.items = {}
        self.target.clear()
        self.target.addItem(self.asm.Label + " (top level)", None)
        for c in ac.components(self.asm):
            it = QtWidgets.QTreeWidgetItem([c.Label])
            self.tree.addTopLevelItem(it)
            self.items[id(it)] = c
            if c in keep:
                it.setSelected(True)
            if ac.is_subassembly(c):
                self.target.addItem(c.Label, c.Name)
                for m in ac.sub_components(c):
                    sub = QtWidgets.QTreeWidgetItem([m.Label])
                    it.addChild(sub)
                    self.items[id(sub)] = m
                it.setExpanded(True)

    def picked(self):
        return [self.items[id(it)] for it in self.tree.selectedItems() if id(it) in self.items]

    def pick(self, comps):
        # a plain walk: a QTreeWidgetItemIterator left alive crashes FreeCAD on the next clear()
        todo = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while todo:
            item = todo.pop()
            item.setSelected(self.items.get(id(item)) in comps)
            todo += [item.child(i) for i in range(item.childCount())]

    def move(self):
        comps = self.picked()
        name = self.target.currentData()
        target = self.asm.Document.getObject(name) if name else self.asm
        if not comps:
            self.result.setText("Select the components to move.")
            return None
        doc = self.asm.Document
        doc.openTransaction("Reorganize Components")
        try:
            moved, removed = reorganize(self.asm, comps, target)
        except Exception as error:
            doc.abortTransaction()
            self.result.setText("Could not move: %s" % error)
            return None
        doc.commitTransaction()
        text = "%d component(s) moved to %s." % (moved, target.Label)
        if removed:
            text += " %d mate(s) between the levels were removed." % removed
        self.result.setText(text)
        self.fill()
        return moved, removed


class ReorganizePanel:
    ""



    def __init__(self, asm):
        from . import asmpm
        self.asm = asm
        self.box = ReorganizeBox(asm)
        b1, lay1 = asmpm._box("Components to Move", "Reorganize Components")
        self.message = QtWidgets.QLabel("Select the components to move, then the assembly they go into.")
        self.message.setWordWrap(True)
        lay1.addWidget(self.message)
        self.tree = self.box.tree
        self.tree.setStyleSheet(asmpm.PICK_STYLE)
        lay1.addWidget(self.tree)
        b2, lay2 = asmpm._box("Target Assembly")
        self.target = self.box.target
        lay2.addWidget(self.target)
        self.result = self.box.result
        self.result.setWordWrap(True)
        lay2.addWidget(self.result)
        b1.setObjectName("SWReorganizeComponents")
        self.form = [b1, b2]
        self.closed = False
        Gui.Selection.addObserver(self)

    def objectName(self):
        return "SWReorganizeComponents"

    def picked(self):
        return self.box.picked()

    def pick(self, comps):
        self.box.pick(comps)

    def move(self):
        return self.box.move()

    def fill(self, keep=()):
        self.box.fill(keep)

    # the FeatureManager or graphics area picks the components to move
    def _sync(self):
        if self.closed:
            return
        names = set()
        for s in Gui.Selection.getSelectionEx("", 0):
            if s.Object is None:
                continue
            for sub in (s.SubElementNames or [""]):
                names.add(sub.split(".")[0] if s.Object is self.asm and sub else s.Object.Name)
        comps = [c for c in ac.components(self.asm) if c.Name in names]
        for c in ac.components(self.asm):
            if ac.is_subassembly(c):
                comps += [m for m in ac.sub_components(c) if m.Name in names]
        if comps:
            try:
                self.box.pick(comps)
            except RuntimeError as _fw_err:
                _fw_log("asmreorg.py:372", _fw_err)

    def addSelection(self, *a):
        QtCore.QTimer.singleShot(0, self._sync)

    def removeSelection(self, *a):
        pass

    def setSelection(self, *a):
        QtCore.QTimer.singleShot(0, self._sync)

    def clearSelection(self, *a):
        pass

    def _close(self):
        if self.closed:
            return
        self.closed = True
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmreorg.py:393", _fw_err)
        Gui.Control.closeDialog()

    def accept(self):
        if self.picked():
            done = self.move()
            if done is None:
                return False        # the message says why; the PropertyManager stays
        self._close()
        return True

    def reject(self):
        self._close()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


# ----------------------------------------------------------------------------- Advanced Select
PROPERTIES = ("Component name", "Part name", "Hidden", "Suppressed", "Lightweight", "Fixed", "Toolbox",
              "Subassembly", "Volume (mm^3)", "Size (mm)")
CONDITIONS = ("is (exactly)", "is not", "contains", "does not contain", "=", "<", ">")
YESNO = ("Hidden", "Suppressed", "Lightweight", "Fixed", "Toolbox", "Subassembly")


def value_of(asm, comp, prop):
    from . import asmcomp, toolbox, asmtools
    if prop == "Component name":
        return comp.Label
    if prop == "Part name":
        return ac.part_name(comp)
    if prop == "Hidden":
        return comp.ViewObject is not None and not comp.ViewObject.Visibility
    if prop == "Suppressed":
        return asmcomp.is_suppressed(comp)
    if prop == "Lightweight":
        return asmcomp.is_lightweight(comp)
    if prop == "Fixed":
        return comp in ac.grounded(asm)
    if prop == "Toolbox":
        return toolbox.is_fastener(comp) or asmtools.is_fastener(comp)
    if prop == "Subassembly":
        return ac.is_subassembly(comp)
    try:
        shape = asmtools._global_shape(comp)
    except Exception:
        return None
    if shape is None or shape.isNull():
        return None
    return shape.Volume if prop.startswith("Volume") else shape.BoundBox.DiagonalLength


def _yes(text):
    return str(text).strip().lower() in ("yes", "true", "1", "y")


def test(asm, comp, prop, cond, value):
    have = value_of(asm, comp, prop)
    if have is None:
        return False
    if prop in YESNO:
        want = _yes(value)
        return (have == want) if cond != "is not" else (have != want)
    if isinstance(have, float):
        try:
            v = float(str(value).replace(",", "."))
        except ValueError:
            return False
        return {"=": abs(have - v) < 1e-6 * max(1.0, abs(v)), "<": have < v, ">": have > v,
                "is (exactly)": abs(have - v) < 1e-6 * max(1.0, abs(v)), "is not": abs(have - v) >= 1e-6 * max(1.0, abs(v))}.get(cond, False)
    h, v = str(have).lower(), str(value).lower()
    return {"is (exactly)": h == v, "=": h == v, "is not": h != v, "contains": v in h,
            "does not contain": v not in h}.get(cond, False)


def matches(asm, rows):
    """rows: [(property, condition, value, "And"/"Or")], the join read before each row (the first's is ignored)."""
    out = []
    for c in ac.components(asm):
        ok = None
        for prop, cond, value, join in rows:
            r = test(asm, c, prop, cond, value)
            ok = r if ok is None else ((ok and r) if join == "And" else (ok or r))
        if ok:
            out.append(c)
    return out


class AdvancedSelectBox(QtWidgets.QDialog):
    """Advanced Component Selection: a table of criteria; Apply selects the matching components."""

    def __init__(self, asm, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.asm = asm
        self.setObjectName("SWAdvancedSelect")
        self.setWindowTitle("Advanced Component Selection")
        lay = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setObjectName("SWAdvancedSelectTable")
        self.table.setHorizontalHeaderLabels(["And/Or", "Property", "Condition", "Value"])
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table)
        row = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton("Add Row")
        add.setObjectName("SWAdvancedSelectAdd")
        add.clicked.connect(lambda: self.add_row())
        row.addWidget(add)
        rem = QtWidgets.QPushButton("Delete Row")
        rem.setObjectName("SWAdvancedSelectDelete")
        rem.clicked.connect(self.delete_row)
        row.addWidget(rem)
        row.addStretch(1)
        lay.addLayout(row)
        self.count = QtWidgets.QLabel()
        self.count.setObjectName("SWAdvancedSelectCount")
        lay.addWidget(self.count)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        self.apply_button = bb.addButton("Apply", QtWidgets.QDialogButtonBox.ApplyRole)
        self.apply_button.setObjectName("SWAdvancedSelectApply")
        self.apply_button.clicked.connect(self.apply)
        bb.button(QtWidgets.QDialogButtonBox.Close).clicked.connect(self.reject)
        lay.addWidget(bb)
        self.resize(560, 300)
        self.add_row()

    def add_row(self, prop="Component name", cond="contains", value="", join="And"):
        r = self.table.rowCount()
        self.table.insertRow(r)
        j = QtWidgets.QComboBox()
        j.addItems(["And", "Or"])
        j.setCurrentText(join)
        j.setEnabled(r > 0)
        p = QtWidgets.QComboBox()
        p.addItems(PROPERTIES)
        p.setCurrentText(prop)
        c = QtWidgets.QComboBox()
        c.addItems(CONDITIONS)
        c.setCurrentText(cond)
        v = QtWidgets.QLineEdit(str(value))
        for col, w in enumerate((j, p, c, v)):
            self.table.setCellWidget(r, col, w)
        return r

    def delete_row(self):
        r = self.table.currentRow()
        if r < 0:
            r = self.table.rowCount() - 1
        if r >= 0 and self.table.rowCount() > 1:
            self.table.removeRow(r)
            self.table.cellWidget(0, 0).setEnabled(False)

    def rows(self):
        out = []
        for r in range(self.table.rowCount()):
            j, p, c, v = (self.table.cellWidget(r, k) for k in range(4))
            out.append((p.currentText(), c.currentText(), v.text(), j.currentText()))
        return out

    def apply(self):
        picked = matches(self.asm, self.rows())
        Gui.Selection.clearSelection()
        for c in picked:
            Gui.Selection.addSelection(c.Document.Name, c.Name)
        self.count.setText("%d component(s) selected" % len(picked))
        return picked
