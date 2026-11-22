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

Qt = QtCore.Qt
UNINVOLVED = ("Wireframe", "Hidden", "Transparent", "Use current")
IGNORED_PROP = "FwIgnoredClearances"


def _pm():
    from . import asmpm
    return asmpm


def ignored(asm):
    return set(getattr(asm, IGNORED_PROP, []) or [])


def set_ignored(asm, key, on=True):
    if not hasattr(asm, IGNORED_PROP):
        asm.addProperty("App::PropertyStringList", IGNORED_PROP, "FreeCAD", "Ignored clearances")
        asm.setEditorMode(IGNORED_PROP, 2)
    keys = ignored(asm)
    (keys.add if on else keys.discard)(key)
    setattr(asm, IGNORED_PROP, sorted(keys))


def _key(a, b):
    return "%s|%s" % tuple(sorted((a.Name, b.Name)))


class _Picks:
    """A pick box: components picked in the view or the tree while it is the active box."""

    def _pick_list(self, name, rows=3):
        pm = _pm()
        w = QtWidgets.QListWidget()
        w.setObjectName(name)
        w.setStyleSheet(pm.PICK_STYLE)
        w.setFixedHeight(pm._rows(w, rows))
        return w

    def _component_of(self, obj_name, sub):
        """The top-level component a pick lands on (the observer names the assembly or the component)."""
        doc = self.asm.Document
        obj = doc.getObject(obj_name)
        comps = ac.components(self.asm)
        if obj is not None and any(c.Name == obj.Name for c in comps):
            return obj
        head = (sub or "").split(".")[0]
        if obj is self.asm and head:
            return next((c for c in comps if c.Name == head), None)
        return None

    def addSelection(self, doc, name, sub, pnt):
        if doc != self.asm.Document.Name:
            return
        comp = self._component_of(name, sub)
        if comp is not None:
            QtCore.QTimer.singleShot(0, lambda: self.pick(comp))

    def removeSelection(self, *a):
        pass

    def setSelection(self, *a):
        pass

    def clearSelection(self, *a):
        pass

    def setPreselection(self, *a):
        pass

    def _observe(self):
        Gui.Selection.addObserver(self)

    def _unobserve(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmevalpm.py:110", _fw_err)


class _Look:
    """Red marks, see-through failed parts, the chosen look for the rest; undone on close."""

    def _look_init(self):
        self.nodes, self.faded, self.styled = [], {}, {}

    def _mark_line(self, p, q):
        from pivy import coin
        sep = coin.SoSeparator()
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(1.0, 0.0, 0.0)
        mat.emissiveColor.setValue(1.0, 0.0, 0.0)
        sep.addChild(mat)
        style = coin.SoDrawStyle()
        style.lineWidth = 3
        sep.addChild(style)
        co = coin.SoCoordinate3()
        co.point.setValues(0, 2, [(p.x, p.y, p.z), (q.x, q.y, q.z)])
        sep.addChild(co)
        sep.addChild(coin.SoLineSet())
        self._add_node(sep)

    def _add_node(self, sep):
        try:
            Gui.ActiveDocument.ActiveView.getSceneGraph().addChild(sep)
            self.nodes.append(sep)
        except Exception as _fw_err:
            _fw_log("asmevalpm.py:140", _fw_err)

    def _style(self, involved, transparent, mode):
        from . import asmtools
        if transparent:
            for comp in involved:
                try:
                    self.faded[comp] = asmtools._fade(comp, 0.6)
                except Exception as _fw_err:
                    _fw_log("asmevalpm.py:149", _fw_err)
        for comp in ac.components(self.asm):
            if comp in involved or mode == "Use current":
                continue
            vobj = comp.ViewObject
            if mode == "Transparent":
                self.faded[comp] = asmtools._fade(comp, 0.85)
            elif mode == "Hidden":
                self.styled[comp] = ("Visibility", comp.Visibility)
                comp.Visibility = False
            elif mode == "Wireframe" and hasattr(vobj, "DisplayMode"):
                self.styled[comp] = ("DisplayMode", vobj.DisplayMode)
                try:
                    vobj.DisplayMode = "Wireframe"
                except Exception:
                    self.styled.pop(comp, None)

    def _clear(self):
        from . import asmtools
        try:
            root = Gui.ActiveDocument.ActiveView.getSceneGraph()
            for node in self.nodes:
                root.removeChild(node)
        except Exception as _fw_err:
            _fw_log("asmevalpm.py:173", _fw_err)
        self.nodes = []
        for comp, old in self.faded.items():
            asmtools._restore(comp, old)
        self.faded = {}
        for comp, (prop, value) in self.styled.items():
            try:
                if prop == "Visibility":
                    comp.Visibility = value
                else:
                    setattr(comp.ViewObject, prop, value)
            except Exception as _fw_err:
                _fw_log("asmevalpm.py:185", _fw_err)
        self.styled = {}


# ============================================================================= Clearance Verification
def closest(a, b):
    """(gap, point on a, point on b) between two components where the assembly shows them."""
    from . import asmevaluate as ae
    sa, sb = ae._shape(a), ae._shape(b)
    d, pts, _info = sa.distToShape(sb)
    p, q = pts[0]
    return d, p, q


class ClearancePanel(_Picks, _Look):
    def __init__(self, asm):
        pm = _pm()
        self.asm = asm
        self.found = []
        self.picked = []
        self._look_init()
        sel, lay = pm._box("Selected Items", "Clearance Verification", "ASSEMBLIES_CLEARANCE_VERIFICATION")
        self.selected = self._pick_list("FW_ClearanceSelected")
        lay.addWidget(self.selected)
        lay.addWidget(QtWidgets.QLabel("Check clearance between:"))
        self.only = QtWidgets.QRadioButton("Selected items")
        self.only.setObjectName("FW_ClearanceSelectedOnly")
        self.rest = QtWidgets.QRadioButton("Selected items and the rest of the assembly")
        self.rest.setObjectName("FW_ClearanceRest")
        self.only.setChecked(True)
        lay.addWidget(self.only)
        lay.addWidget(self.rest)
        lay.addWidget(QtWidgets.QLabel("Minimum acceptable clearance:"))
        row = QtWidgets.QHBoxLayout()
        self.minimum = QtWidgets.QDoubleSpinBox()
        self.minimum.setObjectName("FW_ClearanceMinimum")
        self.minimum.setRange(0.0, 1e5)
        self.minimum.setDecimals(2)
        self.minimum.setSuffix("mm")
        self.minimum.setValue(1.0)
        row.addWidget(self.minimum)
        lay.addLayout(row)
        self.calculate = QtWidgets.QPushButton("Calculate")
        self.calculate.setObjectName("FW_ClearanceCalculate")
        self.calculate.clicked.connect(self.compute)
        lay.addWidget(self.calculate, 0, Qt.AlignLeft)
        res, lay = pm._box("Results")
        self.results = QtWidgets.QTreeWidget()
        self.results.setObjectName("FW_ClearanceResults")
        self.results.setHeaderHidden(True)
        self.results.setFixedHeight(pm._rows(self.results, 6))
        self.results.itemSelectionChanged.connect(self._picked)
        lay.addWidget(self.results)
        self.summary = QtWidgets.QLabel("")
        self.summary.setObjectName("FW_ClearanceSummary")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.ignore = QtWidgets.QPushButton("Ignore")
        self.ignore.setObjectName("FW_ClearanceIgnore")
        self.ignore.setVisible(False)
        self.ignore.clicked.connect(self.toggle_ignore)
        lay.addWidget(self.ignore, 0, Qt.AlignLeft)
        self.component_view = pm._check("Component view", "ClearanceComponentView", False)
        self.component_view.setObjectName("FW_ClearanceComponentView")
        self.component_view.toggled.connect(lambda *_: self._list())
        lay.addWidget(self.component_view)
        opts, lay = pm._box("Options")
        self.show_ignored = pm._check("Show ignored clearances", "ClearanceShowIgnored", False)
        self.show_ignored.setObjectName("FW_ClearanceShowIgnored")
        self.show_ignored.toggled.connect(lambda *_: self._list())
        self.subassemblies = pm._check("Treat subassemblies as components", "ClearanceSubassemblies", True)
        self.subassemblies.setObjectName("FW_ClearanceSubassemblies")
        self.ignore_equal = pm._check("Ignore clearance equal to specified value", "ClearanceIgnoreEqual", False)
        self.ignore_equal.setObjectName("FW_ClearanceIgnoreEqual")
        self.transparent = pm._check("Make studied parts transparent", "ClearanceTransparent", True)
        self.transparent.toggled.connect(lambda *_: self._show())
        self.fasteners = pm._check("Create fasteners folder", "ClearanceFasteners", True)
        self.fasteners.setObjectName("FW_ClearanceFasteners")
        self.fasteners.toggled.connect(lambda *_: self._list())
        for b in (self.show_ignored, self.subassemblies, self.ignore_equal, self.transparent, self.fasteners):
            lay.addWidget(_wrapped(b) if b is self.ignore_equal else b)
        unv, lay = pm._box("Uninvolved Components")
        self.uninvolved = []
        group = QtWidgets.QButtonGroup(unv)
        for name in UNINVOLVED:
            r = QtWidgets.QRadioButton(name)
            r.setObjectName("FW_Uninvolved_%s" % name.replace(" ", ""))
            r.setChecked(name == "Use current")
            r.toggled.connect(lambda on, *_: on and self._show())
            group.addButton(r)
            lay.addWidget(r)
            self.uninvolved.append(r)
        self.form = [sel, res, opts, unv]
        selection_box_menu(self.selected, lambda: self.picked, self._items, "FW_ClearanceSelectedMenu")
        results_menu(self, self.results, "FW_ClearanceResultsMenu",
                     lambda k: comp_shapes([self.found[k]["a"], self.found[k]["b"]]) if k is not None else [])
        for s in Gui.Selection.getSelectionEx(asm.Document.Name):
            for sub in (s.SubElementNames or ("",)):
                c = self._component_of(s.ObjectName, sub)
                if c is not None:
                    self.pick(c)
        self._items()
        self._observe()

    # ------------------------------------------------------------ picks
    def pick(self, comp):
        if comp in self.picked:
            return
        self.picked.append(comp)
        self._items()

    def _items(self):
        self.selected.clear()
        if not self.picked:
            self.selected.addItem(self.asm.Document.Label)
        for c in self.picked:
            self.selected.addItem(c.Label)
        self.rest.setVisible(bool(self.picked))     # with items picked only (no greyed choice)
        if not self.picked:
            self.only.setChecked(True)

    # ------------------------------------------------------------ results
    def compute(self):
        from . import asmevaluate as ae
        self._clear()
        mode = "rest" if self.rest.isChecked() and self.picked else "all"
        rows = ae.clearances(self.asm, self.picked, self.minimum.value(), mode, self.ignore_equal.isChecked(),
                             self.subassemblies.isChecked())
        from . import asmtools
        self.found = []
        for a, b, d in rows:
            try:
                _d, p, q = closest(a, b)
            except Exception:
                p = q = None
            self.found.append({"a": a, "b": b, "gap": d, "p": p, "q": q, "key": _key(a, b),
                               "labels": (ae._label(a), ae._label(b)),
                               "fastener": asmtools.is_fastener(a) or asmtools.is_fastener(b)})
        self._list()
        return self.found

    def shown_found(self):
        skip = ignored(self.asm)
        return [k for k, f in enumerate(self.found) if self.show_ignored.isChecked() or f["key"] not in skip]

    def _text(self, k):
        f = self.found[k]
        return "Clearance%d - %.2fmm" % (k + 1, f["gap"]) + (" (Ignored)" if f["key"] in ignored(self.asm) else "")

    def _item(self, parent, text, k=None):
        item = QtWidgets.QTreeWidgetItem([text]) if parent is None else QtWidgets.QTreeWidgetItem(parent, [text])
        if k is not None:
            item.setData(0, Qt.UserRole, k)
            if self.found[k]["key"] in ignored(self.asm):
                item.setForeground(0, QtGui.QBrush(QtGui.QColor("#8a8a8a")))
        return item

    def _list(self):
        self.results.clear()
        shown = self.shown_found()
        tops = []
        fasteners = None
        if self.fasteners.isChecked() and any(self.found[k]["fastener"] for k in shown):
            fasteners = self._item(None, "Fasteners")
        if self.component_view.isChecked():
            names = []
            for k in shown:
                for n in self.found[k]["labels"]:
                    if n not in names:
                        names.append(n)
            for n in names:
                ks = [k for k in shown if n in self.found[k]["labels"]]
                parent = fasteners if fasteners is not None and all(self.found[k]["fastener"] for k in ks) else None
                comp = self._item(parent, n)
                for k in ks:
                    self._item(comp, self._text(k), k)
                if parent is None:
                    tops.append(comp)
        else:
            for k in shown:
                f = self.found[k]
                parent = fasteners if fasteners is not None and f["fastener"] else None
                item = self._item(parent, self._text(k), k)
                for n in f["labels"]:
                    self._item(item, n)
                if parent is None:
                    tops.append(item)
        for item in tops:
            self.results.addTopLevelItem(item)
        if fasteners is not None:
            self.results.addTopLevelItem(fasteners)
        self.results.expandAll()
        live = [f for f in self.found if f["key"] not in ignored(self.asm)]
        self.summary.setText("No clearances under %.2fmm" % self.minimum.value() if not live else
                             "%d clearance%s under %.2fmm." % (len(live), "" if len(live) == 1 else "s", self.minimum.value()))
        self.ignore.setVisible(False)
        self._show()

    def picked_index(self):
        items = self.results.selectedItems()
        if not items:
            return None
        k = items[0].data(0, Qt.UserRole)
        if k is None and items[0].parent() is not None:
            k = items[0].parent().data(0, Qt.UserRole)
        return k

    def toggle_ignore(self):
        k = self.picked_index()
        if k is None:
            return
        key = self.found[k]["key"]
        set_ignored(self.asm, key, key not in ignored(self.asm))
        self._list()

    def _picked(self):
        k = self.picked_index()
        self.ignore.setVisible(k is not None)
        if k is not None:
            self.ignore.setText("Un-Ignore" if self.found[k]["key"] in ignored(self.asm) else "Ignore")
        self._show(k)

    def _show(self, only=None):
        from . import asmexplode as ax
        self._clear()
        involved = set()
        skip = ignored(self.asm)
        for k, f in enumerate(self.found):
            if (only is not None and k != only) or (only is None and f["key"] in skip):
                continue
            for u in (f["a"], f["b"]):
                involved.update(ax.movers(u))
            if f["p"] is not None:
                self._mark_line(f["p"], f["q"])
        mode = UNINVOLVED[[r.isChecked() for r in self.uninvolved].index(True)]
        self._style(involved, self.transparent.isChecked(), mode)

    def accept(self):
        self._clear()
        self._unobserve()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        return self.accept()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


# ============================================================================= right-click menus
def zoom_to(shapes):
    """Zoom to Selection on shapes (the view fits their box), without picking anything (a pick
    would land in the PM's selection box)."""
    try:
        from pivy import coin
        box = App.BoundBox()
        for sh in shapes:
            if sh is not None and not sh.isNull():
                box.add(sh.BoundBox)
        if not box.isValid():
            return False
        view = Gui.ActiveDocument.ActiveView
        cam = view.getCameraNode()
        sep = coin.SoSeparator()
        tr = coin.SoTranslation()
        tr.translation.setValue(box.Center.x, box.Center.y, box.Center.z)
        cube = coin.SoCube()
        cube.width, cube.height, cube.depth = max(box.XLength, 1e-3), max(box.YLength, 1e-3), max(box.ZLength, 1e-3)
        sep.addChild(tr)
        sep.addChild(cube)
        w, h = view.getSize()
        cam.viewAll(sep, coin.SbViewportRegion(max(int(w), 1), max(int(h), 1)), 1.1)
        return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: zoom to selection: %s\n" % error)
        return False


def comp_shapes(comps):
    from . import asmevaluate as ae
    out = []
    for c in comps:
        try:
            out.append(ae._shape(c))
        except Exception as _fw_err:
            _fw_log("asmevalpm.py:471", _fw_err)
    return out


def selection_box_menu(widget, entries, changed, name):
    ""

    widget.setContextMenuPolicy(Qt.CustomContextMenu)

    def build(pos):
        menu = QtWidgets.QMenu(widget)
        menu.setObjectName(name)
        lst = entries()
        item = widget.itemAt(pos)
        row = widget.row(item) if item is not None else widget.currentRow()
        delete = menu.addAction("Delete")
        delete.setEnabled(bool(lst) and 0 <= row < len(lst))
        delete.triggered.connect(lambda *_: (lst.pop(row), changed()))
        clear = menu.addAction("Clear Selections")
        clear.setEnabled(bool(lst))
        clear.triggered.connect(lambda *_: (lst.clear(), changed()))
        widget._fw_menu = menu
        return menu

    widget._fw_build_menu = build
    widget.customContextMenuRequested.connect(lambda pos: build(pos).popup(widget.viewport().mapToGlobal(pos)))


def result_components(panel, k):
    """The components a result is about (an interference's, a clearance's, a hole pair's)."""
    if k is None:
        return []
    try:
        f = panel.found[k]
    except Exception:
        return []
    if isinstance(f, dict):
        return [c for c in (f.get("a"), f.get("b")) if c is not None]
    try:
        return [f[0], f[2]]                 # Hole Alignment: (a, face, b, face, deviation)
    except Exception:
        return []


def _isolate(comps):
    """Isolate: only the result's components shown, the Isolate toolbar to go back (asmisolate)."""
    from . import asmisolate
    return asmisolate.isolate(comps)


def open_resolved(comp):
    """Opens a result's component in its own window, resolved: a lightweight component (as in
    Large Design Review) is resolved first."""
    try:
        from . import asmlight
        if asmlight.is_lightweight(comp):
            asmlight.set_lightweight(comp, False)
    except Exception as _fw_err:
        _fw_log("asmevalpm.py:529", _fw_err)
    try:
        from . import asmmenu
        return asmmenu.open_part(comp)
    except Exception as error:
        App.Console.PrintError("FreeCAD: open: %s\n" % error)
        return False


def results_menu(panel, tree, name, zoom_shapes, can_ignore=True):
    ""
    tree.setContextMenuPolicy(Qt.CustomContextMenu)

    def build(pos):
        item = tree.itemAt(pos)
        if item is not None:
            tree.setCurrentItem(item)
        k = panel.picked_index() if hasattr(panel, "picked_index") else None
        menu = QtWidgets.QMenu(tree)
        menu.setObjectName(name)
        zoom = menu.addAction("Zoom to Selection")
        zoom.setEnabled(k is not None)
        zoom.triggered.connect(lambda *_: zoom_to(zoom_shapes(k)))
        comps = result_components(panel, k)
        iso = menu.addAction("Isolate")
        iso.setEnabled(bool(comps))
        iso.triggered.connect(lambda *_: _isolate(comps))
        if can_ignore:
            button = getattr(panel, "ignore", None)
            act = menu.addAction(button.text() if k is not None and button is not None else "Ignore")
            act.setEnabled(k is not None)
            act.triggered.connect(lambda *_: panel.toggle_ignore())

        # resolved in its own window
        if comps:
            menu.addSeparator()
        for comp in comps:
            try:
                label = comp.Label
            except Exception:
                continue
            op = menu.addAction("Open %s" % label)
            op.setObjectName("FW_ResultOpen")
            op.triggered.connect(lambda *_, c=comp: open_resolved(c))
        tree._fw_menu = menu
        return menu

    tree._fw_build_menu = build
    tree.customContextMenuRequested.connect(lambda pos: build(pos).popup(tree.viewport().mapToGlobal(pos)))


# ============================================================================= Hole Alignment
class HoleAlignmentPanel(_Look):
    def __init__(self, asm):
        pm = _pm()
        self.asm = asm
        self.found = []
        self._look_init()
        box, lay = pm._box("Hole Alignment", "Hole Alignment", "ASSEMBLIES_HOLE_ALIGNMENT")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Hole center deviation:"))
        self.deviation = QtWidgets.QDoubleSpinBox()
        self.deviation.setObjectName("FW_HoleAlignmentDeviation")
        self.deviation.setRange(0.0, 1e4)
        self.deviation.setDecimals(3)
        self.deviation.setSuffix("mm")
        self.deviation.setValue(1.0)
        row.addWidget(self.deviation)
        lay.addLayout(row)
        self.calculate = QtWidgets.QPushButton("Calculate")
        self.calculate.setObjectName("FW_HoleAlignmentCalculate")
        self.calculate.clicked.connect(self.compute)
        lay.addWidget(self.calculate, 0, Qt.AlignLeft)
        res, lay = pm._box("Results")
        self.results = QtWidgets.QTreeWidget()
        self.results.setObjectName("FW_HoleAlignmentResults")
        self.results.setHeaderHidden(True)
        self.results.setFixedHeight(pm._rows(self.results, 6))
        self.results.itemSelectionChanged.connect(self._picked)
        lay.addWidget(self.results)
        self.summary = QtWidgets.QLabel("")
        self.summary.setObjectName("FW_HoleAlignmentSummary")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        opts, lay = pm._box("Options")
        self.subassemblies = pm._check("Treat subassemblies as components", "HoleAlignSubassemblies", True)
        self.subassemblies.setObjectName("FW_HoleAlignmentSubassemblies")
        lay.addWidget(self.subassemblies)
        self.form = [box, res, opts]
        results_menu(self, self.results, "FW_HoleAlignmentResultsMenu", self._hole_shapes, can_ignore=False)

    def picked_index(self):
        items = self.results.selectedItems()
        if not items:
            return None
        k = items[0].data(0, Qt.UserRole)
        if k is None and items[0].parent() is not None:
            k = items[0].parent().data(0, Qt.UserRole)
        return k

    def _hole_shapes(self, k):
        if k is None:
            return []
        from . import asmevaluate as ae
        a, fa, b, fb, _d = self.found[k]
        out = []
        for comp, face in ((a, fa), (b, fb)):
            try:
                out.append(ae._shape(comp).getElement(face))
            except Exception as _fw_err:
                _fw_log("asmevalpm.py:639", _fw_err)
        return out

    def compute(self):
        from . import asmevaluate as ae
        self.found = ae.misaligned_holes(self.asm, self.deviation.value(), self.subassemblies.isChecked())
        self.results.clear()
        for k, (a, fa, b, fb, d) in enumerate(self.found):
            item = QtWidgets.QTreeWidgetItem(["Misaligned Hole%d - %.3fmm" % (k + 1, d)])
            item.setData(0, Qt.UserRole, k)
            for comp, face in ((a, fa), (b, fb)):
                QtWidgets.QTreeWidgetItem(item, ["%s@%s" % (face, ae._label(comp))])
            self.results.addTopLevelItem(item)
        self.results.expandAll()
        self.summary.setText("No misaligned holes found" if not self.found else
                             "%d misaligned hole%s." % (len(self.found), "" if len(self.found) == 1 else "s"))
        return self.found

    def _picked(self):
        items = self.results.selectedItems()
        if not items:
            return
        k = items[0].data(0, Qt.UserRole)
        if k is None and items[0].parent() is not None:
            k = items[0].parent().data(0, Qt.UserRole)
        if k is None:
            return
        a, fa, b, fb, _d = self.found[k]
        doc = self.asm.Document
        Gui.Selection.clearSelection()
        for comp, face in ((a, fa), (b, fb)):
            path = _path(self.asm, comp)
            try:
                Gui.Selection.addSelection(doc.Name, self.asm.Name, "%s%s" % (path, face))
            except Exception as _fw_err:
                _fw_log("asmevalpm.py:674", _fw_err)

    def accept(self):
        self._clear()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        return self.accept()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


def _path(asm, comp):
    """The sub-element path from the assembly to comp ("Link." or "Sub.Link.")."""
    if comp in ac.components(asm):
        return comp.Name + "."
    for c in ac.components(asm):
        if ac.is_subassembly(c) and comp in ac.sub_components(c):
            return "%s.%s." % (c.Name, comp.Name)
    return comp.Name + "."


def _open(cls):
    pm = _pm()
    asm = ac.assembly_of(App.ActiveDocument)
    if asm is None or not pm.close_open():
        return None
    panel = cls(asm)
    pm._track(panel)
    Gui.Control.showDialog(panel)
    QtCore.QTimer.singleShot(0, panel.compute)
    return panel


def clearance_verification():
    return _open(ClearancePanel)


def hole_alignment():
    return _open(HoleAlignmentPanel)


# ============================================================================= MateXpert
def diagnose_only(asm):
    ""

    from . import asmevaluate as ae
    before = {j.Name: bool(getattr(j, "Suppressed", False)) for j in ac.mates(asm)}
    try:
        culprits = ae.diagnose(asm)
    finally:
        for j in ac.mates(asm):
            if getattr(j, "Suppressed", False) != before.get(j.Name, False):
                j.Suppressed = before.get(j.Name, False)
        ac.solve(asm)
    from . import asmmenu
    return [j for j in culprits if not asmmenu.suppressed(j)]     # not the ones the user suppressed


class MateXpertPanel(_Picks):
    ""




    def __init__(self, asm):
        pm = _pm()
        self.asm = asm
        self.picked = []
        self.problems = []
        prob, lay = pm._box("Analyze Problem", "MateXpert", "ASSEMBLIES_MATEXPERT")
        self.diagnose_btn = QtWidgets.QPushButton("Diagnose")
        self.diagnose_btn.setObjectName("FW_MateXpertDiagnose")
        self.diagnose_btn.clicked.connect(self.diagnose)
        lay.addWidget(self.diagnose_btn, 0, Qt.AlignLeft)
        lay.addWidget(QtWidgets.QLabel("Not Satisfied Mates:"))
        self.problem_list = QtWidgets.QTreeWidget()
        self.problem_list.setObjectName("FW_MateXpertProblems")
        self.problem_list.setHeaderHidden(True)
        self.problem_list.setFixedHeight(pm._rows(self.problem_list, 5))
        self.problem_list.itemSelectionChanged.connect(lambda: self._pick_mate(self.problem_list))
        lay.addWidget(self.problem_list)
        comp, lay = pm._box("Analyze Components")
        self.components = self._pick_list("FW_MateXpertComponents")
        lay.addWidget(self.components)
        self.analyze_btn = QtWidgets.QPushButton("Analyze")
        self.analyze_btn.setObjectName("FW_MateXpertAnalyze")
        self.analyze_btn.clicked.connect(self.analyze)
        lay.addWidget(self.analyze_btn, 0, Qt.AlignLeft)
        self.mate_tree = QtWidgets.QTreeWidget()
        self.mate_tree.setObjectName("FW_MateXpertMates")
        self.mate_tree.setHeaderHidden(True)
        self.mate_tree.setFixedHeight(pm._rows(self.mate_tree, 6))
        self.mate_tree.itemSelectionChanged.connect(lambda: self._pick_mate(self.mate_tree))
        lay.addWidget(self.mate_tree)
        self.suppress_btn = QtWidgets.QPushButton("Suppress")
        self.suppress_btn.setObjectName("FW_MateXpertSuppress")
        self.suppress_btn.setToolTip("Suppress the mate picked in the results")
        self.suppress_btn.setVisible(False)
        self.suppress_btn.clicked.connect(self.suppress)
        lay.addWidget(self.suppress_btn, 0, Qt.AlignLeft)
        self.summary = QtWidgets.QLabel("")
        self.summary.setObjectName("FW_MateXpertSummary")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.form = [prob, comp]
        self.current = None
        self._items()
        self._observe()

    def pick(self, comp):
        if comp not in self.picked:
            self.picked.append(comp)
            self._items()

    def _items(self):
        self.components.clear()
        for c in self.picked:
            self.components.addItem(c.Label)

    def compute(self):
        ""
        from . import asmevaluate as ae
        from . import asmmenu
        self.problems = [p[0] for p in ae.mate_problems(self.asm) if not asmmenu.suppressed(p[0])]
        self._fill(self.problem_list, [(None, self.problems)])
        self.summary.setText("All mates are satisfied." if not self.problems else
                             "%d mate%s not satisfied." % (len(self.problems), "" if len(self.problems) == 1 else "s"))
        return self.problems

    def diagnose(self):
        self.problems = diagnose_only(self.asm)
        self._fill(self.problem_list, [(None, self.problems)])
        self.summary.setText("No problem mates found." if not self.problems else
                             "Suppress %s to solve the rest." % ", ".join(j.Label for j in self.problems))
        return self.problems

    def analyze(self):
        """The picked components' mates, satisfied and not."""
        from . import asmevaluate as ae
        from . import asmmenu
        bad = {p[0].Name for p in ae.mate_problems(self.asm) if not asmmenu.suppressed(p[0])}
        names = {c.Name for c in (self.picked or ac.components(self.asm))}     # nothing picked: every component
        mine = []
        for j in ac.mates(self.asm):
            refs = [r[0] for r in (getattr(j, "Reference1", None), getattr(j, "Reference2", None)) if r]
            if any(r is not None and r.Name in names for r in refs):
                mine.append(j)
        ok = [j for j in mine if j.Name not in bad and not asmmenu.suppressed(j)]
        ko = [j for j in mine if j.Name in bad]
        self._fill(self.mate_tree, [("Satisfied Mates", ok), ("Not Satisfied Mates", ko)])
        return ok, ko

    def _fill(self, tree, groups):
        tree.clear()
        for title, joints in groups:
            parent = QtWidgets.QTreeWidgetItem([title]) if title else None
            if parent is not None:
                tree.addTopLevelItem(parent)
            for j in joints:
                it = QtWidgets.QTreeWidgetItem([ac.mate_text(j)])
                it.setData(0, Qt.UserRole, j.Name)
                try:
                    it.setIcon(0, j.ViewObject.Icon)
                except Exception as _fw_err:
                    _fw_log("asmevalpm.py:842", _fw_err)
                (parent.addChild(it) if parent is not None else tree.addTopLevelItem(it))
        tree.expandAll()

    def _pick_mate(self, tree):
        items = tree.selectedItems()
        name = items[0].data(0, Qt.UserRole) if items else None
        self.current = self.asm.Document.getObject(name) if name else None
        from . import asmmenu
        self.suppress_btn.setVisible(self.current is not None and not asmmenu.suppressed(self.current))
        if self.current is not None:
            self._unobserve()
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(self.asm.Document.Name, self.current.Name)
            self._observe()

    def suppress(self):
        j = self.current
        if j is None:
            return False
        from . import asmmenu
        asmmenu.suppress(j, True)               # as the mate's own Suppress: greyed in the tree, one Undo
        self.compute()
        if self.picked:
            self.analyze()
        self.suppress_btn.setVisible(False)
        return True

    def accept(self):
        self._unobserve()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        return self.accept()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


def matexpert():
    return _open(MateXpertPanel)


def _wrapped(box):
    ""


    text = box.text()
    holder = QtWidgets.QWidget()
    row = QtWidgets.QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(box.style().pixelMetric(QtWidgets.QStyle.PM_CheckBoxLabelSpacing))
    box.setText("")
    box.setAccessibleName(text)
    box.setToolTip(text)
    label = QtWidgets.QLabel(text)
    label.setObjectName(box.objectName() + "Text")
    label.setWordWrap(True)
    label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
    label.mousePressEvent = lambda e: box.isEnabled() and box.toggle()
    row.addWidget(box, 0, Qt.AlignTop)
    row.addWidget(label, 1)
    return holder
