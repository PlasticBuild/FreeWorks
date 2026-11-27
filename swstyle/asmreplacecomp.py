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


# ---------------------------------------------------------------- the work
def _kind(shape):
    if shape is None:
        return None
    if shape.ShapeType == "Face":
        return ("Face", shape.Surface.TypeId)
    if shape.ShapeType == "Edge":
        return ("Edge", shape.Curve.TypeId)
    if shape.ShapeType == "Vertex":
        return ("Vertex", None)
    return (shape.ShapeType, None)


def _where(shape):
    try:
        return App.Vector(shape.CenterOfMass)
    except Exception:
        try:
            return App.Vector(shape.Point)
        except Exception:
            return shape.BoundBox.Center


def _dir(shape):
    """A plane's normal or an axis's direction (None for other entities)."""
    try:
        if shape.ShapeType == "Face":
            surf = shape.Surface
            if "Plane" in surf.TypeId:
                u0, u1, v0, v1 = shape.ParameterRange
                return App.Vector(shape.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0))
            if hasattr(surf, "Axis"):
                return App.Vector(surf.Axis)
        if shape.ShapeType == "Edge" and hasattr(shape.Curve, "Direction"):
            return App.Vector(shape.Curve.Direction)
        if shape.ShapeType == "Edge" and hasattr(shape.Curve, "Axis"):
            return App.Vector(shape.Curve.Axis)
    except Exception as _fw_err:
        _fw_log("asmreplacecomp.py:74", _fw_err)
    return None


def _same_way(a, b, axis):
    """Planes face the same way; axes and lines are parallel (either way)."""
    if a is None or b is None:
        return True
    d = a.normalize().dot(App.Vector(b).normalize())
    return abs(d) > 0.99 if axis else d > 0.99


def remember(asm, comps):
    """{(mate name, index): (kind, where)} of the mate entities on the components to replace."""
    out = {}
    for j in ac.mates(asm):
        for i, prop in enumerate(("Reference1", "Reference2")):
            ref = getattr(j, prop, None)
            if not ref or ref[0] not in comps:
                continue
            sub = ref[1][0] if ref[1] else ""
            s = ac.element(ref[0], sub) if sub else None
            if s is not None:
                out[(j.Name, i)] = (_kind(s), _where(s), _dir(s))
    return out


def _elements(comp, kind):
    shape = comp.Shape
    name, items = {"Face": ("Face", shape.Faces), "Edge": ("Edge", shape.Edges),
                   "Vertex": ("Vertex", shape.Vertexes)}.get(kind[0], (None, []))
    for n, _ in enumerate(items, 1):
        sub = "%s%d" % (name, n)
        s = ac.element(comp, sub)
        if s is not None and _kind(s) == kind:
            yield sub, s


def match(comp, kind, where, way=None):
    ""


    best = None
    axis = not (kind[0] == "Face" and "Plane" in str(kind[1]))
    for sub, s in _elements(comp, kind):
        if not _same_way(way, _dir(s), axis):
            continue
        d = (_where(s) - where).Length
        if best is None or d < best[0]:
            best = (d, sub)
    return best[1] if best else None


def reattach(asm, before):
    """Each remembered mate entity that is gone or changed kind is put on its match (before the
    mates are recomputed, so none looks for an element that is gone). Returns the mates that could
    not be put back (they are left suppressed for Mate Entities)."""
    lost = []
    joints = {j.Name: j for j in ac.mates(asm)}
    for (name, i), (kind, where, *more) in before.items():
        way = more[0] if more else None
        j = joints.get(name)
        if j is None:
            continue
        prop = ("Reference1", "Reference2")[i]
        ref = getattr(j, prop)
        comp, sub = ref[0], (ref[1][0] if ref[1] else "")
        try:
            s = ac.element(comp, sub) if sub else None
        except Exception:
            s = None
        if s is not None and _kind(s) == kind and (_where(s) - where).Length < 1e-6:
            continue
        new = match(comp, kind, where, way)
        if new is None:
            lost.append(j)
            if hasattr(j, "Suppressed"):
                j.Suppressed = True
            # the old entity's name kept for Mated Entities; the reference itself no longer names an
            # element the new part lacks (FreeCAD's joint would fail on every rebuild)
            if "FwLostEntity" not in j.PropertiesList:
                j.addProperty("App::PropertyString", "FwLostEntity", "FreeCAD", "The mate entity lost in Replace Components")
                j.setEditorMode("FwLostEntity", 2)
            j.FwLostEntity = "%d:%s" % (i, sub)
            setattr(j, prop, (comp, ["", ""]))
            continue
        if new != sub:
            setattr(j, prop, (comp, [new, new]))
    return lost


def _mates_of(asm, comps):
    out = []
    for j in ac.mates(asm):
        for prop in ("Reference1", "Reference2"):
            ref = getattr(j, prop, None)
            if ref and ref[0] in comps and j not in out:
                out.append(j)
    return out


def set_configuration(target, name):
    """The new part shows the configuration name (if it has it)."""
    try:
        from . import configmanager
        t = configmanager.table(target.Document)
        if t is not None and name in t.names():
            configmanager.show(t, name)
            return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Replace configuration: %s\n" % error)
    return False


def configurations(doc):
    from . import fileprops
    return fileprops.configurations(doc)


def active_configuration(doc):
    from . import fileprops
    try:
        return fileprops.active_configuration(doc)
    except Exception as _fw_err:
        _fw_log("asmreplacecomp.py:199", _fw_err)
        return "Default"


def _pattern_instances(asm, seeds):
    ""


    out = []
    try:
        from . import asmcpattern as cp
        for feat in cp.patterns(asm):
            for link in cp.instances(feat):
                seed = getattr(link, cp.SEED_PROP, None)
                if seed in seeds and link not in seeds and link not in out \
                        and getattr(link, "LinkedObject", None) is getattr(seed, "LinkedObject", None):
                    out.append(link)
    except Exception as _fw_err:
        _fw_log("asmreplacecomp.py:pattern instances", _fw_err)
    return out


def replace(asm, comps, target, all_instances=False, reattach_mates=True, configuration=None):
    """Replace these component(s) with this one. Returns (replaced, mates not put back)."""
    from . import asmcomp
    todo = []
    for c in comps:
        for x in (asmcomp.instances(asm, c) if all_instances else [c]):
            if x not in todo:
                todo.append(x)
    before = remember(asm, todo)
    old_config = None
    if todo:
        try:
            old_config = active_configuration(todo[0].LinkedObject.Document)
        except Exception:
            old_config = None
    from . import asmrefopts
    rename = asmrefopts.on(asmrefopts.REPLACE_NAMES)    # Update component names when documents are replaced
    todo += _pattern_instances(asm, todo)
    for c in todo:
        c.LinkedObject = target
        if rename:

            # replaced by Bracket, with Bracket<1> and <2> there, is Bracket<3> (the old number gave
            # "Bracket<1>001")
            base, _, inst = c.Label.rpartition("<")
            c.Label = "FwReplacing"
            c.Label = ac._instance(asm, ac.part_name(c)) if base else ac.part_name(c)
    want = configuration if configuration else old_config        # Manually select / Match name
    if want:
        set_configuration(target, want)
    lost = []
    if reattach_mates:
        lost = reattach(asm, before)
    else:
        for j in _mates_of(asm, todo):
            if hasattr(j, "Suppressed"):
                j.Suppressed = True
    asm.Document.recompute()
    ac.solve(asm)
    asm.Document.recompute()
    return todo, lost


# ---------------------------------------------------------------- the PM
def _part_docs(asm):
    out = []
    for d in App.listDocuments().values():
        if d is asm.Document or ac.assembly_of(d) is not None:
            continue
        if ac.part_object(d) is not None:
            out.append(d)
    return out


class ReplacePanel:
    def __init__(self, asm, comps=None):
        from . import asmpm
        OPEN.append(self)
        self.asm = asm
        self.doc = asm.Document
        self.target = None
        self.comps = list(comps or [])
        sel, lay = asmpm._box("Selection", "Replace", "ASSEMBLIES_REPLACE_COMPONENTS")
        lay.addWidget(QtWidgets.QLabel("Replace these component(s):"))
        self.these = QtWidgets.QListWidget()
        self.these.setObjectName("FW_ReplaceThese")
        self.these.setStyleSheet(asmpm.PICK_STYLE)
        self.these.setFixedHeight(asmpm._rows(self.these, 3))
        lay.addWidget(self.these)
        lay.addWidget(QtWidgets.QLabel("With this one:"))
        self.with_list = QtWidgets.QListWidget()
        self.with_list.setObjectName("FW_ReplaceWith")
        self.with_list.setFixedHeight(asmpm._rows(self.with_list, 4))
        self.with_list.currentItemChanged.connect(self._with_changed)
        lay.addWidget(self.with_list)
        self.browse = QtWidgets.QPushButton("Browse...")
        self.browse.setObjectName("FW_ReplaceBrowse")
        self.browse.clicked.connect(self._browse)
        lay.addWidget(self.browse, 0, Qt.AlignLeft)
        self.all = QtWidgets.QCheckBox("All instances")
        self.all.setObjectName("FW_ReplaceAllInstances")
        lay.addWidget(self.all)

        opts, lay = asmpm._box("Options")
        lay.addWidget(QtWidgets.QLabel("Configuration:"))
        self.match_name = QtWidgets.QRadioButton("Match name")
        self.match_name.setObjectName("FW_ReplaceMatchName")
        self.match_name.setChecked(True)
        self.manual = QtWidgets.QRadioButton("Manually select")
        self.manual.setObjectName("FW_ReplaceManual")
        self.config = QtWidgets.QComboBox()
        self.config.setObjectName("FW_ReplaceConfiguration")
        from .asmpattern import _takes_over
        _takes_over(self.config, self.manual, True)       # choosing a configuration picks Manually select
        for w in (self.match_name, self.manual, self.config):
            lay.addWidget(w)
        self.reattach = QtWidgets.QCheckBox("Re-attach mates")
        self.reattach.setObjectName("FW_ReplaceReattach")
        self.reattach.setChecked(True)
        lay.addWidget(self.reattach)
        self.form = [sel, opts]
        self._fill_docs()
        self._show_comps()
        Gui.Selection.addObserver(self, 0)
        if not self.comps:
            QtCore.QTimer.singleShot(0, self._from_selection)

    # selection
    def _from_selection(self):
        comps = []
        comp_set = ac.components(self.asm)
        for sel in Gui.Selection.getSelectionEx("", 0):
            subs = sel.SubElementNames or [""]
            for sub in subs:
                comp = None
                if sub:
                    ref = ac.reference(self.asm, sel.Object, sub)
                    comp = ref[0] if ref else None
                elif sel.Object in comp_set:
                    comp = sel.Object
                if comp is not None and comp not in comps:
                    comps.append(comp)
        if comps:
            self.comps = comps
            self._show_comps()

    def _show_comps(self):
        self.these.clear()
        for c in self.comps:
            self.these.addItem(c.Label)

    def addSelection(self, *a):
        QtCore.QTimer.singleShot(0, self._from_selection)

    def removeSelection(self, *a):
        pass

    def clearSelection(self, *a):
        pass

    # with this one
    def _fill_docs(self):
        self.with_list.clear()
        self.docs = _part_docs(self.asm)
        for d in self.docs:
            item = QtWidgets.QListWidgetItem(d.Label)
            item.setData(Qt.UserRole, d.Name)
            self.with_list.addItem(item)

    def _with_changed(self, item, _prev=None):
        if item is None:
            return
        d = App.getDocument(item.data(Qt.UserRole))
        self.set_target(ac.part_object(d))

    def set_target(self, target):
        self.target = target
        self.config.clear()
        if target is not None:
            self.config.addItems(configurations(target.Document))
            for i in range(self.with_list.count()):
                it = self.with_list.item(i)
                if it.data(Qt.UserRole) == target.Document.Name and self.with_list.currentRow() != i:
                    self.with_list.blockSignals(True)
                    self.with_list.setCurrentRow(i)
                    self.with_list.blockSignals(False)

    def open_file(self, path):
        doc = None
        for d in App.listDocuments().values():
            if os.path.normcase(d.FileName or "") == os.path.normcase(path):
                doc = d
        doc = doc or App.openDocument(path)
        try:
            Gui.setActiveDocument(self.doc.Name)
            App.setActiveDocument(self.doc.Name)
        except Exception as _fw_err:
            _fw_log("asmreplacecomp.py:373", _fw_err)
        self._fill_docs()
        self.set_target(ac.part_object(doc))
        return self.target

    def _browse(self):
        start = os.path.dirname(self.doc.FileName or "")
        path, _ = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Open", start, "FreeCAD (*.FCStd)")
        if path:
            self.open_file(path)

    # OK
    def accept(self):
        if not self.comps or self.target is None:
            QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Replace",
                                              "Select the component(s) to replace and the one to replace them with.")
            return False
        config = self.config.currentText() if self.manual.isChecked() else None
        self.doc.openTransaction("Replace Components")
        try:
            self.replaced, self.lost = replace(self.asm, self.comps, self.target, self.all.isChecked(),
                                               self.reattach.isChecked(), config)
        finally:
            self.doc.commitTransaction()
        self._close()
        if self.lost:
            from . import asmreplace
            QtCore.QTimer.singleShot(0, lambda: asmreplace.mated_entities(self.asm, list(self.replaced), list(self.lost)))
        return True

    def reject(self):
        self._close()
        return True

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmreplacecomp.py:411", _fw_err)
        if self in OPEN:
            OPEN.remove(self)
        Gui.Control.closeDialog()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


def start(comp=None):
    asm = ac.assembly_of(comp.Document if comp is not None else App.ActiveDocument)
    if asm is None:
        return None
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    panel = ReplacePanel(asm, [comp] if comp is not None else None)
    Gui.Control.showDialog(panel)
    return panel
