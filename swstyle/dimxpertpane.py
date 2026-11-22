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

from .widgets import alive

Qt = QtCore.Qt
ROLE = Qt.UserRole + 1
TOOLS = (("Auto Dimension Scheme", "SWStyle_MBDAutoScheme"), ("Location Dimension", "SWStyle_MBDLocation"),
         ("Size Dimension", "SWStyle_MBDSize"), ("Datum", "SWStyle_MBDDatum"),
         ("Geometric Tolerance", "SWStyle_MBDGeometricTolerance"),
         ("Show Tolerance Status", "SWStyle_MBDToleranceStatus"), ("TolAnalyst Study", "SWStyle_MBDStackUp"),
         ("DimXpert from Sketch Dimensions", "SWStyle_MBDSketchDimensions"),
         ("Hide/Show Annotations", "SWStyle_MBDHideShow"))


def annotations(doc):
    from . import mbd
    return [o for o in doc.Objects if mbd.is_pmi(o)] if doc is not None else []


def delete_all(doc):
    items = annotations(doc)
    if not items:
        return 0
    doc.openTransaction("Delete All")
    try:
        for o in items:
            doc.removeObject(o.Name)
        folder = doc.getObject("Annotations")
        if folder is not None and folder.TypeId == "App::DocumentObjectGroup" and not folder.Group:
            doc.removeObject(folder.Name)
    finally:
        doc.commitTransaction()
    doc.recompute()
    return len(items)


def _face_kind(shape, i):
    from . import mbd
    f = shape.Faces[i]
    t = f.Surface.TypeId
    if t == "Part::GeomPlane":
        return "Plane"
    if t == "Part::GeomCylinder":
        full = abs(f.ParameterRange[1] - f.ParameterRange[0]) >= 6.0
        if not full:
            return "Fillet"
        return "Simple Hole" if mbd._is_hole(shape, f) else "Boss"
    if t == "Part::GeomCone":
        return "Cone"
    return "Surface"


def _faces(o, obj=None):
    out = []
    for ref, subs in o.References:
        if obj is not None and ref is not obj:
            continue
        for sub in subs:
            if "Face" in sub:
                out.append((ref, int(sub.split("Face")[-1]) - 1))
    return out


def features(doc):
    ""
    groups, kinds = {}, {}
    for o in annotations(doc):
        faces = _faces(o)
        if not faces:
            key = None
        elif o.Kind == "Pattern" or (o.Kind in ("Location", "BasicLocation") and len(faces) > 2):
            key = (faces[0][0].Name, tuple(sorted(i for _r, i in faces)))
        elif o.Kind in ("Location", "BasicLocation", "Angle"):
            key = (faces[-1][0].Name, (faces[-1][1],))
        else:
            key = (faces[0][0].Name, (faces[0][1],))
        groups.setdefault(key, []).append(o)
    # a hole sized once and patterned: its single-hole key joins the pattern
    patterns = {k: v for k, v in groups.items() if k is not None and len(k[1]) > 1}
    for pk in list(patterns):
        for k in list(groups):
            if k is not None and len(k[1]) == 1 and k[0] == pk[0] and k[1][0] in pk[1] and k in groups:
                groups[pk] += groups.pop(k)
    out = []
    counts = {}
    for key in sorted((k for k in groups if k is not None), key=lambda k: (k[0], k[1])):
        obj = doc.getObject(key[0])
        try:
            kind = "Hole Pattern" if len(key[1]) > 1 else _face_kind(obj.Shape, key[1][0])
        except Exception:
            kind = "Surface"
        counts[kind] = counts.get(kind, 0) + 1
        named = next((getattr(o, "DimXpertFeature", "") for o in groups[key] if getattr(o, "DimXpertFeature", "")), "")
        out.append((named or "%s%d" % (kind, counts[kind]), key, groups[key]))     # Rename tree item
    if None in groups:
        out.append(("Annotations", None, groups[None]))
    return out


class _Observer:
    def __init__(self, page):
        self.page = page

    def _later(self, *_a):
        if alive(self.page):
            self.page.later()

    slotCreatedObject = slotDeletedObject = slotActivateDocument = slotDeletedDocument = _later

    def slotChangedObject(self, obj, prop):
        if prop in ("Text", "Label", "Kind") and getattr(obj, "SWStyleKind", "") == "PMI":
            self._later()


class Page(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWDimXpertManager")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QtWidgets.QToolBar(self)
        bar.setObjectName("SWDimXpertTools")
        bar.setIconSize(QtCore.QSize(16, 16))
        for text, cmd in TOOLS:
            act = bar.addAction(text)
            act.setToolTip(text)
            try:
                from . import icons
                icon = icons.family({"SWStyle_MBDAutoScheme": "MBD_AUTO_SCHEME",
                                     "SWStyle_MBDToleranceStatus": "MBD_TOLERANCE_STATUS"}.get(cmd, ""))
                if icon is not None and not icon.isNull():
                    act.setIcon(icon)
            except Exception as _fw_err:
                _fw_log("dimxpertpane.py:165", _fw_err)
            act.triggered.connect(lambda _c=False, cmd=cmd: self._run(cmd))
        act = bar.addAction("Delete All")
        act.triggered.connect(lambda _c=False: (delete_all(App.ActiveDocument), self.refresh()))
        bar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        lay.addWidget(bar)

        self.filter = QtWidgets.QLineEdit(self)
        self.filter.setObjectName("SWDimXpertFilter")
        self.filter.setPlaceholderText("Filter")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(lambda _t: self.apply_filter())
        lay.addWidget(self.filter)
        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setObjectName("SWDimXpertTree")
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu_at)
        self.tree.itemClicked.connect(lambda item, _c: self.select(item))
        self.tree.itemDoubleClicked.connect(lambda item, _c: self.edit(item))
        lay.addWidget(self.tree, 1)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.refresh)
        self._observer = _Observer(self)
        App.addDocumentObserver(self._observer)
        self.destroyed.connect(lambda *_a, o=self._observer: _forget(o))

    def later(self):
        if alive(self):
            self._timer.start()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def _run(self, cmd):
        try:
            Gui.runCommand(cmd, 0)
        except Exception as error:
            App.Console.PrintWarning("DimXpertManager: %s: %s\n" % (cmd, error))
        self.later()

    def refresh(self):
        if not alive(self):
            return
        self.tree.clear()
        doc = App.ActiveDocument
        if doc is None:
            return
        try:
            from . import configmanager
            t = configmanager.table(doc)
            config = t.active() if t else "Default"
        except Exception:
            config = "Default"
        root = QtWidgets.QTreeWidgetItem(["%s (%s)" % (doc.Label, config), ""])
        root.setData(0, ROLE, ("part",))
        self.tree.addTopLevelItem(root)
        order = ("Datum", "DatumTarget", "GTol", "Size", "Location", "BasicSize", "BasicLocation", "Angle", "Pattern")
        items = annotations(doc)
        for name, key, group in features(doc):
            node = QtWidgets.QTreeWidgetItem([name, ""])
            node.setData(0, ROLE, ("feature", key[0], list(key[1])) if key else ("none",))
            root.addChild(node)
            for o in sorted(group, key=lambda o: (order.index(o.Kind) if o.Kind in order else 99, o.Label)):
                item = QtWidgets.QTreeWidgetItem([o.Label, o.Text])
                item.setData(0, ROLE, ("pmi", o.Name))
                if o.ViewObject is not None and not o.ViewObject.Visibility:
                    item.setForeground(0, QtGui.QBrush(QtGui.QColor(Qt.gray)))
                node.addChild(item)
        if not items:
            empty = QtWidgets.QTreeWidgetItem(["(no annotations: Auto Dimension Scheme makes them)", ""])
            empty.setFlags(Qt.ItemIsEnabled)
            root.addChild(empty)
        self.tree.expandAll()
        self.tree.resizeColumnToContents(0)
        self.apply_filter()

    def apply_filter(self):
        """Rows whose name or text holds the filter text stay, with the features above them."""
        want = self.filter.text().strip().lower() if hasattr(self, "filter") else ""

        def visit(item):
            own = not want or want in item.text(0).lower() or want in item.text(1).lower()
            kids = [visit(item.child(i)) for i in range(item.childCount())]
            show = own or any(kids)
            if own and want:
                for i in range(item.childCount()):        # a feature that matches keeps its annotations
                    _show_all(item.child(i))
                show = True
            item.setHidden(not show)
            return show

        def _show_all(item):
            item.setHidden(False)
            for i in range(item.childCount()):
                _show_all(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for k in range(top.childCount()):
                visit(top.child(k))
            top.setHidden(False)

    def _obj(self, item):
        d = (item.data(0, ROLE) if item is not None else None) or ("none",)
        if d[0] != "pmi" or App.ActiveDocument is None:
            return None
        return App.ActiveDocument.getObject(d[1])

    def select(self, item):
        d = (item.data(0, ROLE) if item is not None else None) or ("none",)
        if d[0] == "feature" and App.ActiveDocument is not None:
            Gui.Selection.clearSelection()      # a DimXpert feature: its faces
            for i in d[2]:
                Gui.Selection.addSelection(App.ActiveDocument.Name, d[1], "Face%d" % (i + 1))
            return
        o = self._obj(item)
        if o is None:
            return
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(o)
        for ref, subs in o.References:
            for sub in subs:
                Gui.Selection.addSelection(ref, sub)

    def edit(self, item):
        o = self._obj(item)
        if o is None:
            return False
        text, ok = QtWidgets.QInputDialog.getText(self, "Edit Text", o.Label, text=o.Text)
        if ok:
            o.Document.openTransaction("Edit Text")
            try:
                o.Text = text
            except BaseException:
                try:
                    o.Document.abortTransaction()
                except Exception:
                    pass
                raise
            o.Document.commitTransaction()
            o.Document.recompute()
        return ok

    def _rows(self, item):
        ""



        from . import fmmenu
        doc = App.ActiveDocument
        d = (item.data(0, ROLE) if item is not None else None) or ("none",)
        o = self._obj(item)
        collapse = ("Collapse", "Collapse Items", lambda: (self.tree.collapseAll(), self.tree.expandToDepth(0)), True)
        rename = ("Rename", "Rename tree item", lambda: self.rename(item), True)
        if o is not None:
            shown = o.ViewObject.Visibility if o.ViewObject is not None else True
            return [(None, "Feature (%s)" % o.Label, None, False),
                    ("Suppress", "Suppress" if shown else "Unsuppress", lambda: self.suppress([o], shown), True),
                    ("Delete", "Delete...", lambda: self.delete([o]), True),
                    ("Comment", "Comment", fmmenu.Sub(lambda m: fmmenu._comment_menu(m, None, o, doc)), True),
                    collapse, rename,
                    ("EditText", "Edit Text...", lambda: self.edit(item), True),
                    ("-", None, None, False), ("Customize", "Customize Menu", None, True)]
        if d[0] == "feature":
            group = self._group(item)
            shown = any(g.ViewObject is None or g.ViewObject.Visibility for g in group)
            return [(None, "Feature (%s)" % item.text(0), None, False),
                    ("Suppress", "Suppress" if shown else "Unsuppress", lambda: self.suppress(group, shown), bool(group)),
                    ("EditFeature", "Edit Feature", lambda: (self.select(item), self._run("SWStyle_MBDAutoScheme")), True),
                    ("Delete", "Delete...", lambda: self.delete(group), bool(group)),
                    ("Comment", "Comment", fmmenu.Sub(lambda m: fmmenu._comment_menu(m, None, group[0] if group else None, doc)),
                     bool(group)),
                    rename, collapse, ("-", None, None, False), ("Customize", "Customize Menu", None, True)]
        return [("AutoScheme", "Auto Dimension Scheme", lambda: self._run("SWStyle_MBDAutoScheme"), True),
                ("DeleteAll", "Delete All", lambda: (delete_all(doc), self.refresh()), doc is not None),
                collapse]

    def _group(self, item):
        doc = App.ActiveDocument
        out = []
        for i in range(item.childCount() if item is not None else 0):
            d = item.child(i).data(0, ROLE) or ("none",)
            if d[0] == "pmi" and doc is not None and doc.getObject(d[1]) is not None:
                out.append(doc.getObject(d[1]))
        return out

    def suppress(self, objs, on):
        for o in objs:
            if o.ViewObject is not None:
                o.ViewObject.Visibility = not on
        self.refresh()

    def delete(self, objs):
        if not objs:
            return
        names = ", ".join(o.Label for o in objs[:5])
        if QtWidgets.QMessageBox.question(self, "Confirm Delete", "Delete %s?" % names) != QtWidgets.QMessageBox.Yes:
            return
        doc = objs[0].Document
        doc.openTransaction("Delete")
        try:
            for o in objs:
                doc.removeObject(o.Name)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        doc.recompute()
        self.refresh()

    def rename(self, item):
        o = self._obj(item)
        objs = [o] if o is not None else self._group(item)
        if not objs:
            return
        text, ok = QtWidgets.QInputDialog.getText(self, "Rename", "Name:", text=item.text(0))
        if ok and text.strip():
            doc = objs[0].Document
            doc.openTransaction("Rename")
            try:
                if o is not None:
                    o.Label = text.strip()
                else:
                    for g in objs:          # a DimXpert feature's name lives on its annotations
                        if "DimXpertFeature" not in g.PropertiesList:
                            g.addProperty("App::PropertyString", "DimXpertFeature", "DimXpert", "The DimXpert feature's name")
                        g.DimXpertFeature = text.strip()
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
            self.refresh()

    def _menu_at(self, pos):
        from . import fmmenu
        item = self.tree.itemAt(pos)
        rows = self._rows(item)
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("SWDimXpertMenu")
        for key, label, run, enabled in rows:
            if key not in (None, "-") and not enabled:
                continue        # left out, not greyed (NO DEAD CONTROLS; pkg216)
            if key == "-":
                menu.addSeparator()
            elif key is None:
                a = menu.addAction(label)
                f = a.font()
                f.setBold(True)
                a.setFont(f)
                a.setProperty("swHeading", True)
            elif isinstance(run, fmmenu.Sub):
                sub = menu.addMenu(label)
                run.fill(sub)
                sub.setEnabled(enabled)
            else:
                a = menu.addAction(label)
                a.setProperty("swKey", key)
                a.setEnabled(bool(enabled))
                if key == "Customize":
                    choices = [(k, l) for k, l, r, e in rows if k not in (None, "-", "Customize")]
                    a.triggered.connect(lambda _c=False, c=choices: fmmenu._later(lambda: fmmenu._run_dialog(
                        fmmenu.CustomizeDialog("dimxpert", c), lambda box: box.apply())))
                elif run is not None:
                    a.triggered.connect(lambda _c=False, r=run: fmmenu._later(r))
        self._last_menu = menu
        menu.exec_(self.tree.viewport().mapToGlobal(pos))


def _forget(observer):
    try:
        App.removeDocumentObserver(observer)
    except Exception as _fw_err:
        _fw_log("dimxpertpane.py:424", _fw_err)
