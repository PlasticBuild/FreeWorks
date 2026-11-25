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

import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from .widgets import alive

Qt = QtCore.Qt


def _shell():
    try:
        from . import shell
        s = shell.shell()
    except Exception:
        return None
    return s if s is not None and s.enabled else None


def _later(func):
    from . import keys
    keys._run_later(func)


# --------------------------------------------------------------------------- the FeatureManager tree
def feature_tree():
    ""
    mw = Gui.getMainWindow()
    if mw is None:
        return None
    for view in mw.findChildren(QtWidgets.QTreeView, "SWFeatureTree"):
        if alive(view) and view.isVisible():
            return view
    for view in mw.findChildren(QtWidgets.QTreeWidget):
        if alive(view) and view.metaObject().className() == "Gui::TreeWidget" and view.isVisible():
            return view
    return None


def _tree_index(view):
    """The picked row of the tree, else its current row."""
    index = view.currentIndex()
    model = view.selectionModel()
    if model is not None:
        rows = model.selectedRows() or model.selectedIndexes()
        if rows:
            index = rows[0]
    return index


def expand_collapse():
    view = feature_tree()
    if view is None:
        return False
    index = _tree_index(view)
    if not index.isValid():
        return False
    view.setExpanded(index, not view.isExpanded(index))
    return True


def collapse_all():
    view = feature_tree()
    if view is None:
        return False
    view.collapseAll()

    model = view.model()
    root = view.rootIndex()
    for row in range(model.rowCount(root) if model is not None else 0):
        view.setExpanded(model.index(row, 0, root), True)
    return True


def scroll_tree(top):
    view = feature_tree()
    if view is None:
        return False
    if top:
        view.scrollToTop()
    else:
        view.scrollToBottom()
    return True


# --------------------------------------------------------------------------- reference geometry (Q)
REFERENCE_TOGGLES = ("SWStyle_ViewPlanes", "SWStyle_ViewAxes", "SWStyle_ViewOrigins", "SWStyle_ViewCoordinateSystems")


def _checked(name):
    from . import checkstate
    try:
        return bool(checkstate.checked(name))
    except Exception:
        return False


def toggle_reference_geometry():
    ""

    have = set(Gui.listCommands())
    names = [n for n in REFERENCE_TOGGLES if n in have]
    if not names:
        return None
    show = not any(_checked(n) for n in names)
    for name in names:
        if _checked(name) != show:
            try:
                Gui.runCommand(name, 1 if show else 0)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: %s: %s\n" % (name, error))
    return show


# --------------------------------------------------------------------------- recent documents (R)
def recent_actions():
    """FreeCAD's recent file entries, newest first: (text, QAction)."""
    try:
        actions = Gui.Command.get("Std_RecentFiles").getAction()
    except Exception:
        return []
    out = []
    for action in actions:
        # FreeCAD numbers its recent files ("&1 Part.FCStd"); Clear Recent Files is no document
        if isinstance(action, QtGui.QAction) and action.isVisible() and re.match(r"&?\d", action.text().strip()):
            data = action.toolTip() or action.text()
            out.append((data, action))
    return out


def browse_recent(pos=None):
    ""
    menu = QtWidgets.QMenu(Gui.getMainWindow())
    menu.setObjectName("SWRecentDocuments")
    menu.setAttribute(Qt.WA_DeleteOnClose, True)
    entries = recent_actions()
    if not entries:
        act = menu.addAction("No recent documents")
        act.setEnabled(False)
    for text, action in entries:
        import os
        name = os.path.basename(text.replace("&", "")) or text
        item = menu.addAction(QtGui.QIcon(), name)
        item.setToolTip(text)
        item.triggered.connect(lambda checked=False, a=action: _later(a.trigger))
    menu.popup(pos or QtGui.QCursor.pos())
    return menu


# --------------------------------------------------------------------------- Quick Snaps on/off (F3)
SNAP_GROUP = "User parameter:BaseApp/Preferences/Mod/Sketcher/Snap"


def snaps_on():
    return App.ParamGet(SNAP_GROUP).GetBool("Snap", True)


def toggle_quick_snaps():
    ""
    try:
        from .fwsketch import snap
        if hasattr(snap, "toggle_snaps"):
            return bool(snap.toggle_snaps())        # fwsketch's own switch (status bar, running tool)
    except Exception as _fw_err:
        _fw_log("swkeys.py:199", _fw_err)
    on = not snaps_on()
    App.ParamGet(SNAP_GROUP).SetBool("Snap", on)
    try:
        from .fwsketch import toolbase
        tool = toolbase.active()
        snapper = getattr(tool, "snapper", None) if tool is not None else None
        params = getattr(snapper, "p", None)
        if params is not None:
            params.snap = on
    except Exception as _fw_err:
        _fw_log("swkeys.py:210", _fw_err)
    App.Console.PrintMessage("Quick Snaps %s\n" % ("on" if on else "off"))
    return on


# --------------------------------------------------------------------------- Next Edge / Accept Edge (N, Y)
class EdgeChain:
    """The edge N lit last: (document, object, edge name), and the place in the list of the edges
    joined at the chain's open end."""

    def __init__(self):
        self.lit = None
        self.turn = -1
        self.key = None

    @staticmethod
    def _picked():
        """(document, object, [edge names]) of the picked edges, all on one object, else None."""
        found = None
        for sel in Gui.Selection.getSelectionEx():
            names = [n.split(".")[-1] for n in sel.SubElementNames]
            names = [n for n in names if n.startswith("Edge") and n[4:].isdigit()]
            if not names:
                continue
            if found is not None and (found[0], found[1]) != (sel.DocumentName, sel.ObjectName):
                return None
            found = (sel.DocumentName, sel.ObjectName, (found[2] if found else []) + names)
        return found

    @staticmethod
    def _shape(doc, obj):
        try:
            return App.getDocument(doc).getObject(obj).Shape
        except Exception:
            return None

    def candidates(self):
        """The edges joined to the open end of the picked chain, in the shape's order."""
        picked = self._picked()
        if picked is None:
            return None, []
        doc, obj, names = picked
        shape = self._shape(doc, obj)
        if shape is None:
            return picked, []
        edges = shape.Edges
        chosen = [edges[int(n[4:]) - 1] for n in names if n[4:].isdigit() and int(n[4:]) <= len(edges)]
        if not chosen:
            return picked, []
        last = chosen[-1]
        # the open end: a vertex of the last edge no other picked edge touches
        ends = [v for v in last.Vertexes
                if not any(any(v.isSame(w) for w in e.Vertexes) for e in chosen[:-1])] or list(last.Vertexes)
        end = ends[-1]
        out = []
        for i, e in enumerate(edges):
            name = "Edge%d" % (i + 1)
            if name in names or any(e.isSame(c) for c in chosen):
                continue
            if any(v.isSame(end) for v in e.Vertexes):
                out.append(name)
        return picked, out

    def next_edge(self):
        picked, names = self.candidates()
        if picked is None or not names:
            self.lit = None
            return None
        key = (picked[0], picked[1], tuple(picked[2]))
        self.turn = (self.turn + 1) % len(names) if key == self.key else 0
        self.key = key
        self.lit = (picked[0], picked[1], names[self.turn])
        try:
            Gui.Selection.setPreselection(*self.lit)
        except Exception as _fw_err:
            _fw_log("swkeys.py:285", _fw_err)
        return self.lit

    def accept_edge(self):
        lit = self.lit
        if lit is None:
            return None
        Gui.Selection.addSelection(*lit)
        self.lit, self.turn, self.key = None, -1, None
        return lit


_chain = EdgeChain()


def edge_chain():
    return _chain


# --------------------------------------------------------------------------- Search Files and Models (I)
FILE_TYPES = (".fcstd", ".step", ".stp", ".iges", ".igs", ".sldprt", ".sldasm", ".slddrw", ".stl", ".dxf", ".brep")


def _recent_files():
    p = App.ParamGet("User parameter:BaseApp/Preferences/RecentFiles")
    out = []
    for i in range(p.GetInt("RecentFiles", 4) or 0):
        f = p.GetString("MRU%d" % i, "")
        if f:
            out.append(f)
    return out


def file_candidates():
    """Files to search: the recent ones, then the model files beside them and beside the open documents."""
    import os
    seen, out = set(), []

    def add(path):
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen and os.path.isfile(path):
            seen.add(key)
            out.append(path)
    recent = _recent_files()
    for f in recent:
        add(f)
    folders = []
    for f in recent + [d.FileName for d in App.listDocuments().values() if getattr(d, "FileName", "")]:
        folder = os.path.dirname(f)
        if folder and folder not in folders:
            folders.append(folder)
    for folder in folders[:12]:
        try:
            for name in sorted(os.listdir(folder))[:400]:
                if os.path.splitext(name)[1].lower() in FILE_TYPES:
                    add(os.path.join(folder, name))
        except Exception:
            continue
    return out


def open_file(path):
    import os
    if os.path.splitext(path)[1].lower() == ".fcstd":
        for doc in App.listDocuments().values():
            if os.path.normcase(getattr(doc, "FileName", "")) == os.path.normcase(path):
                Gui.getDocument(doc.Name) and App.setActiveDocument(doc.Name)
                return doc
        return App.openDocument(path)
    Gui.open(path)
    return App.ActiveDocument


class FileSearch(QtWidgets.QFrame):
    ""

    MOST = 20

    @staticmethod
    def option(text, default):
        """Options > System Options > Search (kept by optionspages)."""
        try:
            from . import optionspages
            got = optionspages.stored("Search", text, default)
            return type(default)(got) if got is not None else default
        except Exception:
            return default

    def __init__(self, parent):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("SWFileSearch")
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.box = QtWidgets.QLineEdit(self)
        self.box.setPlaceholderText("Search Files and Models")
        self.list = QtWidgets.QListWidget(self)
        lay.addWidget(self.box)
        lay.addWidget(self.list)
        self.files = file_candidates()
        self.per_page = max(1, self.option("Results per page", 10))
        self.most = max(1, self.option("Maximum results per data source", 100))
        self.online = self.option("Include online content results", False)
        self.page = 0
        if self.option("Search while typing (incremental search)", True):
            self.box.textChanged.connect(self.fill)
        else:
            self.box.returnPressed.connect(lambda: self.fill(self.box.text()))
        self.box.returnPressed.connect(self.open_current)
        self.list.itemActivated.connect(lambda item: self.open_current())
        self.box.installEventFilter(self)
        self.resize(360, 260)
        self.fill("")

    def fill(self, text, page=0):
        import os
        self.list.clear()
        self.page = page
        self.query = text.strip()           # the words searched (the box may be empty on a More results page)
        text = text.strip().lower()
        hits = [f for f in self.files if text in os.path.basename(f).lower()]
        hits.sort(key=lambda f: 0 if os.path.basename(f).lower().startswith(text) else 1)
        hits = hits[:self.most]                                   # Maximum results per data source
        start = page * self.per_page
        for f in hits[start:start + self.per_page]:               # Results per page
            item = QtWidgets.QListWidgetItem(os.path.basename(f))
            item.setToolTip(f)
            item.setData(Qt.UserRole, f)
            self.list.addItem(item)
        if start + self.per_page < len(hits):
            more = QtWidgets.QListWidgetItem("More results...")
            more.setData(Qt.UserRole, ("page", page + 1))
            more.setToolTip("Results %d-%d of %d" % (start + 1, min(len(hits), start + self.per_page), len(hits)))
            self.list.addItem(more)
        if self.online and text:
            web = QtWidgets.QListWidgetItem("Search online for \"%s\"" % self.query)
            web.setData(Qt.UserRole, ("online", self.query))
            web.setToolTip("Online content results (FreeCAD's web help)")
            self.list.addItem(web)
        if self.list.count():
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if obj is self.box and event.type() == QtCore.QEvent.KeyPress and event.key() in (Qt.Key_Down, Qt.Key_Up):
            row = self.list.currentRow() + (1 if event.key() == Qt.Key_Down else -1)
            if 0 <= row < self.list.count():
                self.list.setCurrentRow(row)
            return True
        return False

    def open_current(self):
        item = self.list.currentItem()
        if item is None:
            return None
        path = item.data(Qt.UserRole)
        if isinstance(path, tuple):
            if path[0] == "page":
                self.fill(self.box.text().strip() or getattr(self, "query", ""), path[1])
                return None
            if path[0] == "online":
                self.close()
                from PySide import QtGui
                QtGui.QDesktopServices.openUrl(QtCore.QUrl("https://wiki.freecad.org/index.php?search=" + QtCore.QUrl.toPercentEncoding(path[1]).data().decode()))
                return None
        self.close()
        _later(lambda: open_file(path))
        return path


def show_file_search():
    mw = Gui.getMainWindow()
    pop = FileSearch(mw)
    pop.setAttribute(Qt.WA_DeleteOnClose, True)
    anchor = None
    s = _shell()
    try:
        anchor = s.topbar.qat.search if s is not None else None
    except Exception:
        anchor = None
    if anchor is not None and alive(anchor) and anchor.isVisible():
        pos = anchor.mapToGlobal(QtCore.QPoint(anchor.width() - pop.width(), 0))
    else:
        pos = mw.mapToGlobal(QtCore.QPoint(mw.width() - pop.width() - 20, 40))
    pop.move(pos)
    pop.show()
    pop.box.setFocus(Qt.ShortcutFocusReason)
    return pop


# --------------------------------------------------------------------------- flat tree (Ctrl+T), Display Pane (F8)
def rebuild_trees():
    mw = Gui.getMainWindow()
    for view in mw.findChildren(QtWidgets.QTreeView, "SWFeatureTree") if mw is not None else ():
        model = getattr(view, "fm", None)
        if model is not None and alive(view):
            model.rebuild()


def toggle_flat_tree():
    from . import paths
    p = paths.params()
    flat = not p.GetBool("TreeFlat", False)
    p.SetBool("TreeFlat", flat)
    rebuild_trees()
    return flat


class DisplayPane(QtWidgets.QWidget):
    ""

    WIDTH = 46

    def __init__(self, view):
        # on the tree's right edge, over its rows (QTreeView resets its own viewport margins)
        super().__init__(view.viewport())
        self.setObjectName("SWDisplayPane")
        self.setAutoFillBackground(True)
        self.view = view
        self.setMouseTracking(True)
        self.setToolTip("Display Pane: Hide/Show, Appearance")
        view.verticalScrollBar().valueChanged.connect(self.update)
        view.expanded.connect(lambda i: self.update())
        view.collapsed.connect(lambda i: self.update())
        model = getattr(view, "fm", None)
        if model is not None:
            model.rebuilt.connect(self.update)
            model.dataChanged.connect(lambda *a: self.update())
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(500)        # visibility changes from elsewhere
        self._timer.timeout.connect(self.update)
        self._timer.start()
        view.viewport().installEventFilter(self)
        self.place()

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if obj is self.view.viewport() and event.type() == QtCore.QEvent.Resize:
            self.place()
        return False

    def place(self):
        vp = self.view.viewport()
        self.setGeometry(vp.width() - self.WIDTH, 0, self.WIDTH, vp.height())

    def _obj(self, index):
        model = getattr(self.view, "fm", None)
        node = model.node(index) if model is not None else None
        obj = getattr(node, "obj", None) if node is not None else None
        try:
            if obj is None or not hasattr(obj, "ViewObject") or obj.ViewObject is None:
                return None
        except ReferenceError:
            return None             # the object was deleted while the row was still drawn
        return obj

    def rows(self):
        """(rect in the pane, object) for each row of the tree in sight that has a document object."""
        v = self.view
        out = []
        index = v.indexAt(QtCore.QPoint(4, 1))
        while index.isValid():
            r = v.visualRect(index)
            if r.top() > v.viewport().height():
                break
            obj = self._obj(index)
            if obj is not None:
                out.append((QtCore.QRect(0, r.top(), self.WIDTH, r.height()), obj))
            index = v.indexBelow(index)
        return out

    @staticmethod
    def colour(obj):
        vo = obj.ViewObject
        try:
            c = vo.ShapeAppearance[0].DiffuseColor
        except Exception:
            c = getattr(vo, "ShapeColor", None) or getattr(vo, "LineColor", None)
        if not c:
            return None
        return QtGui.QColor.fromRgbF(c[0], c[1], c[2])

    def paintEvent(self, event):
        from . import style
        p = QtGui.QPainter(self)
        try:
            p.fillRect(self.rect(), self.palette().color(QtGui.QPalette.Base))
            p.setPen(QtGui.QPen(self.palette().color(QtGui.QPalette.Mid)))
            p.drawLine(0, 0, 0, self.height())
            p.setRenderHint(QtGui.QPainter.Antialiasing, True)
            text = self.palette().color(QtGui.QPalette.Text)
            for rect, obj in self.rows():
                cy = rect.center().y()
                shown = bool(obj.ViewObject.Visibility)
                eye = QtCore.QRectF(5, cy - 4, 14, 8)
                p.setPen(QtGui.QPen(text if shown else self.palette().color(QtGui.QPalette.Mid), 1.2))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(eye)
                if shown:
                    p.setBrush(text)
                    p.drawEllipse(QtCore.QPointF(eye.center()), 2.2, 2.2)
                else:
                    p.drawLine(QtCore.QPointF(5, cy + 5), QtCore.QPointF(19, cy - 5))
                c = self.colour(obj)
                if c is not None:
                    p.setPen(QtGui.QPen(self.palette().color(QtGui.QPalette.Mid), 1))
                    p.setBrush(c)
                    p.drawRect(QtCore.QRectF(26, cy - 5, 11, 10))
        finally:
            p.end()

    def obj_at(self, pos):
        for rect, obj in self.rows():
            if rect.contains(pos):
                return obj
        return None

    def mousePressEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        obj = self.obj_at(pos)
        if obj is None:
            return
        if pos.x() < 22:
            obj.ViewObject.Visibility = not obj.ViewObject.Visibility
        else:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(obj.Document.Name, obj.Name)
            s = _shell()
            if s is not None:
                try:
                    s.binding("EditAppearance").run()
                except Exception as _fw_err:
                    _fw_log("swkeys.py:620", _fw_err)
        self.update()
        event.accept()


def display_pane(create=False):
    view = feature_tree()
    if view is None or view.objectName() != "SWFeatureTree":
        return None
    pane = view.viewport().findChild(QtWidgets.QWidget, "SWDisplayPane")
    if pane is None and create:
        pane = DisplayPane(view)
        pane.hide()
    return pane


def toggle_display_pane():
    pane = display_pane(create=True)
    if pane is None:
        return None
    show = not pane.isVisible()
    pane.place()
    pane.setVisible(show)
    if show:
        pane.raise_()
    return show


# --------------------------------------------------------------------------- commands
class _Command:
    MENU, TIP = "", ""
    FOR_EDIT = True

    def GetResources(self):
        res = {"MenuText": self.MENU, "ToolTip": self.TIP}
        if self.FOR_EDIT:
            res["CmdType"] = "ForEdit"
        return res

    def IsActive(self):
        return _shell() is not None


class BrowseRecentCommand(_Command):
    MENU, TIP = "Browse Recent Documents", "The recent documents at the pointer (R)"

    def Activated(self):
        browse_recent()


class RepeatLastCommand(_Command):
    MENU, TIP = "Repeat Last Command", "Runs the last command again (Enter)"

    def _last(self):
        s = _shell()
        keys = getattr(s, "viewkeys", None) if s is not None else None
        return getattr(keys, "last", None)

    def Activated(self):
        last = self._last()
        if last is not None:
            _later(last.run)

    def IsActive(self):
        last = self._last()
        return last is not None and last.ready() is not None


class RebuildAllCommand(_Command):
    MENU, TIP = "Rebuild All Configurations", "Rebuilds the part (Ctrl+Shift+B)"
    FORCE = False

    def Activated(self):
        from . import keys
        keys.rebuild(force=self.FORCE)

    def IsActive(self):
        return App.ActiveDocument is not None


class ForceRebuildAllCommand(RebuildAllCommand):
    MENU, TIP = "Force Rebuild All Configurations", "Rebuilds every feature of the part (Ctrl+Shift+Q)"
    FORCE = True

    def IsActive(self):
        # as Ctrl+Q: inside a sketch it exits the sketch and rebuilds every feature; in any other edit it stays grey
        from . import keys
        return keys.ForceRebuildCommand().IsActive()


class RedrawCommand(_Command):
    MENU, TIP = "Redraw", "Draws the graphics area again (Ctrl+R)"

    def Activated(self):
        try:
            Gui.ActiveDocument.ActiveView.redraw()
        except Exception:
            Gui.updateGui()

    def IsActive(self):
        return Gui.ActiveDocument is not None


class SearchCommandsCommand(_Command):
    MENU, TIP = "Search Commands", "Puts the cursor in the Search Commands box (W)"

    def Activated(self):
        s = _shell()
        if s is not None:
            s.show_command_search()


class SearchHelpCommand(_Command):
    MENU, TIP = "Help", "Opens the help (H)"

    def Activated(self):
        try:
            from . import helpmenu
            helpmenu.show()
            return
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Help: %s\n" % error)
        for name in ("Std_FreeCADUserHub", "Std_OnlineHelp", "Std_WhatsThis"):
            try:
                if Gui.Command.get(name) is not None:
                    Gui.runCommand(name, 0)
                    return
            except Exception:
                continue

    def IsActive(self):
        return True


class _DocCommand(_Command):
    ""

    def IsActive(self):
        return _shell() is not None and App.ActiveDocument is not None


class ExpandCollapseTreeCommand(_DocCommand):
    MENU, TIP = "Expand/Collapse Tree", "Opens or closes the picked item of the FeatureManager tree (C)"

    def Activated(self):
        expand_collapse()


class CollapseAllCommand(_DocCommand):
    MENU, TIP = "Collapse All Items", "Closes every item of the FeatureManager tree (Shift+C)"

    def Activated(self):
        collapse_all()


class TreeTopCommand(_DocCommand):
    MENU, TIP = "Scroll to FeatureManager Tree Top", "Scrolls the FeatureManager tree to its top (Home)"
    TOP = True

    def Activated(self):
        scroll_tree(self.TOP)


class TreeBottomCommand(TreeTopCommand):
    MENU, TIP = "Scroll to FeatureManager Tree Bottom", "Scrolls the FeatureManager tree to its bottom (End)"
    TOP = False


class ReferenceGeometryCommand(_Command):
    MENU, TIP = "Primary and Reference Planes, Coordinates and Origins", \
        "Shows or hides the planes, axes, origins and coordinate systems together (Q)"

    def Activated(self):
        toggle_reference_geometry()

    def IsActive(self):
        return Gui.ActiveDocument is not None


class FeatureManagerAreaCommand(_DocCommand):
    MENU, TIP = "FeatureManager Tree Area", "Shows or hides the FeatureManager tree area (F9)"

    def Activated(self):
        s = _shell()
        dock = getattr(s, "left_dock", None) if s is not None else None
        if dock is not None and alive(dock):
            dock.setVisible(not dock.isVisible())


class CommandManagerCommand(_Command):
    MENU, TIP = "Toolbars", "Shows or hides the CommandManager (F10)"

    def Activated(self):
        s = _shell()
        bar = getattr(s, "topbar", None) if s is not None else None
        if bar is not None and alive(bar) and hasattr(bar, "toggle_collapsed"):
            bar.toggle_collapsed()


class CommandManagerTabCommand(_Command):
    MENU, TIP = "Next CommandManager Tab", "The next CommandManager tab to the right (Ctrl+Page Down)"
    STEP = 1

    def Activated(self):
        s = _shell()
        bar = getattr(s, "topbar", None) if s is not None else None
        if bar is not None and alive(bar):
            bar.step_tab(self.STEP)


class PreviousCommandManagerTabCommand(CommandManagerTabCommand):
    MENU, TIP = "Previous CommandManager Tab", "The next CommandManager tab to the left (Ctrl+Page Up)"
    STEP = -1


class ViewSelectorCommand(_Command):
    MENU, TIP = "View Selector", "The View Selector around the model (Ctrl+Space)"

    def Activated(self):
        s = _shell()
        if s is not None:
            s.binding("ViewSelector").run()

    def IsActive(self):
        return _shell() is not None and Gui.ActiveDocument is not None


class QuickSnapsCommand(_Command):
    """Tools > Sketch Settings > Enable Snapping (F3): ticked while sketch snapping is on."""
    MENU, TIP = "Quick Snaps", "Switches all sketch snapping off and on (F3)"

    def GetResources(self):
        res = _Command.GetResources(self)
        res["Checkable"] = snaps_on()
        return res

    def Activated(self, checked=None):
        if checked is None or bool(checked) != snaps_on():
            toggle_quick_snaps()
        self._sync()

    def _sync(self):
        on = snaps_on()
        try:
            for action in Gui.Command.get("SWStyle_QuickSnapsToggle").getAction():
                if action.isCheckable() and action.isChecked() != on:
                    blocked = action.blockSignals(True)
                    action.setChecked(on)
                    action.blockSignals(blocked)
        except Exception as _fw_err:
            _fw_log("swkeys.py:866", _fw_err)

    def IsActive(self):
        self._sync()        # follows F3, the status bar and the Options page
        return True


class NextEdgeCommand(_Command):
    MENU, TIP = "Next Edge", "Lights up the next edge joined to the picked chain (N)"

    def Activated(self):
        _chain.next_edge()

    def IsActive(self):
        return Gui.ActiveDocument is not None


class AcceptEdgeCommand(_Command):
    MENU, TIP = "Accept Edge", "Adds the edge N lit to the selection (Y)"

    def Activated(self):
        _chain.accept_edge()

    def IsActive(self):
        return Gui.ActiveDocument is not None


class SearchFilesCommand(_Command):
    MENU, TIP = "Search Files and Models", "Finds a file by name and opens it (I)"

    def Activated(self):
        show_file_search()

    def IsActive(self):
        return True


class FlatTreeCommand(_DocCommand):
    MENU, TIP = "Show Flat Tree View", "Lists the FeatureManager tree flat, in the order of creation (Ctrl+T)"

    def Activated(self):
        toggle_flat_tree()


class DisplayPaneCommand(_DocCommand):
    MENU, TIP = "Hide/Show Display Pane", "The Display Pane beside the FeatureManager tree (F8)"

    def Activated(self):
        toggle_display_pane()


class TaskPaneCommand(_Command):
    MENU, TIP = "Task Pane", "Shows or hides the Task Pane (Ctrl+F1)"

    def Activated(self):
        from . import uiextras
        uiextras.set_task_pane(not uiextras.task_pane_shown())

    def IsActive(self):
        try:
            from . import uiextras
            return uiextras._tasks_widget() is not None
        except Exception:
            return False


class NotesUpperCaseCommand(_Command):
    MENU, TIP = "Toggle Notes Upper Case", "The picked notes all uppercase, or back as typed (Shift+F3)"

    def Activated(self):
        from . import drawextras
        drawextras.toggle_notes_upper_case()

    def IsActive(self):
        try:
            from . import drawextras
            return bool(drawextras.picked_notes())
        except Exception:
            return False


def _radial_picks():
    """(kind, object, index): picked radius/diameter dimensions, in an open sketch or on a drawing."""
    out = []
    try:
        edit = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument else None
        sk = edit.Object if edit is not None and getattr(edit.Object, "TypeId", "") == "Sketcher::SketchObject" else None
    except Exception:
        sk = None
    for e in Gui.Selection.getSelectionEx():
        o = e.Object
        if sk is not None and o == sk:
            for sub in e.SubElementNames:
                if sub.startswith("Constraint"):
                    i = int(sub[10:]) - 1
                    if 0 <= i < len(sk.Constraints) and sk.Constraints[i].Type in ("Radius", "Diameter"):
                        out.append(("sketch", sk, i))
        elif getattr(o, "TypeId", "") == "TechDraw::DrawViewDimension" and o.Type in ("Radius", "Diameter"):
            out.append(("drawing", o, None))
    return out


def toggle_radial(picks=None):
    ""
    import Sketcher
    picks = _radial_picks() if picks is None else picks
    for kind, o, i in picks:
        if kind == "drawing":
            o.Type = "Diameter" if o.Type == "Radius" else "Radius"
            o.recompute()
            continue
        c = o.Constraints[i]
        value = float(c.Value)
        new = "Diameter" if c.Type == "Radius" else "Radius"
        value = value * 2 if new == "Diameter" else value / 2
        o.Document.openTransaction("Toggle radial dimension display")
        try:
            name = c.Name
            o.delConstraint(i)
            j = o.addConstraint(Sketcher.Constraint(new, c.First, value))
            if name:
                o.renameConstraint(j, name)
            o.recompute()
        finally:
            o.Document.commitTransaction()
    return len(picks)


class RadialDisplayCommand(_Command):
    MENU, TIP = "Toggle radial dimension display", "A radius dimension shows the diameter, and back (Ctrl+D)"

    def Activated(self):
        toggle_radial()

    def IsActive(self):
        try:
            return bool(_radial_picks())
        except Exception:
            return False


DIMENSION_TYPES = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle")


def _dimension_picks():
    """(sketch, index) of the picked dimensions in the open sketch (driving or driven)."""
    out = []
    try:
        edit = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument else None
        sk = edit.Object if edit is not None and getattr(edit.Object, "TypeId", "") == "Sketcher::SketchObject" else None
    except Exception:
        sk = None
    if sk is None:
        return out
    for e in Gui.Selection.getSelectionEx():
        if e.Object != sk:
            continue
        for sub in e.SubElementNames:
            if sub.startswith("Constraint"):
                i = int(sub[10:]) - 1
                if 0 <= i < len(sk.Constraints) and sk.Constraints[i].Type in DIMENSION_TYPES:
                    out.append((sk, i))
    return out


class AnnotationViewCommand(_Command):
    ""

    MENU, TIP = "Select Annotation View", "Puts the picked dimensions in an annotation view (')"

    def Activated(self):
        picks = _dimension_picks()
        if not picks:
            return
        from . import rcextras
        sk, first = picks[0]
        before = rcextras._flags(sk, rcextras.VIEW_PROP)
        rcextras.select_annotation_view(sk, first)
        chosen = rcextras.annotation_view(sk, first)
        if len(picks) > 1 and rcextras._flags(sk, rcextras.VIEW_PROP) != before:
            rc = rcextras._rc()
            keys = [rc._mark_key(sk, i) + ":" for _s, i in picks[1:]]

            def body():
                values = [v for v in rcextras._flags(sk, rcextras.VIEW_PROP) if not any(v.startswith(k) for k in keys)]
                if chosen != rcextras.UNASSIGNED:
                    values += [k + chosen for k in keys]
                rcextras._set_flags(sk, rcextras.VIEW_PROP, values)
            rc._sketch_transaction(sk, "Select Annotation View", body)

    def IsActive(self):
        try:
            return bool(_dimension_picks())
        except Exception:
            return False


COMMANDS = (
    ("SWStyle_TaskPaneKey", TaskPaneCommand),
    ("SWStyle_ToggleNotesUpperCase", NotesUpperCaseCommand),
    ("SWStyle_ToggleRadialDisplay", RadialDisplayCommand),
    ("SWStyle_SelectAnnotationView", AnnotationViewCommand),
    ("SWStyle_BrowseRecentDocuments", BrowseRecentCommand),
    ("SWStyle_RepeatLastCommand", RepeatLastCommand),
    ("SWStyle_RebuildAllConfigurations", RebuildAllCommand),
    ("SWStyle_ForceRebuildAllConfigurations", ForceRebuildAllCommand),
    ("SWStyle_Redraw", RedrawCommand),
    ("SWStyle_SearchCommands", SearchCommandsCommand),
    ("SWStyle_SearchHelp", SearchHelpCommand),
    ("SWStyle_ExpandCollapseTree", ExpandCollapseTreeCommand),
    ("SWStyle_CollapseAllItems", CollapseAllCommand),
    ("SWStyle_TreeTop", TreeTopCommand),
    ("SWStyle_TreeBottom", TreeBottomCommand),
    ("SWStyle_ToggleReferenceGeometry", ReferenceGeometryCommand),
    ("SWStyle_FeatureManagerArea", FeatureManagerAreaCommand),
    ("SWStyle_ToggleCommandManager", CommandManagerCommand),
    ("SWStyle_NextCommandManagerTab", CommandManagerTabCommand),
    ("SWStyle_PreviousCommandManagerTab", PreviousCommandManagerTabCommand),
    ("SWStyle_ViewSelectorKey", ViewSelectorCommand),
    ("SWStyle_QuickSnapsToggle", QuickSnapsCommand),
    ("SWStyle_NextEdge", NextEdgeCommand),
    ("SWStyle_AcceptEdge", AcceptEdgeCommand),
    ("SWStyle_SearchFiles", SearchFilesCommand),
    ("SWStyle_FlatTreeView", FlatTreeCommand),
    ("SWStyle_DisplayPane", DisplayPaneCommand),
)


def register():
    for name, cls in COMMANDS:
        Gui.addCommand(name, cls())


# keyed commands of other files that may sit in no FreeCAD menu or toolbar
KEYED_ELSEWHERE = ("FreeWorks_Line", "SWStyle_SelectOverGeometry", "SWStyle_CopyAppearance", "SWStyle_PasteAppearance",
                   "SWStyle_BrowseOpenDocuments", "SWStyle_Save",
                   "SWStyle_FindModify", "SWStyle_Print", "SWStyle_SpeedPakGraphicsCircle", "SWStyle_TakeSnapshot")


def menu_items(have):
    """FreeCAD gives a command its key only once a menu holds it: all of these go in the Edit menu
    (swmenus.py hides FreeCAD's menus and keeps their keys working)."""
    names = [name for name, _ in COMMANDS] + list(KEYED_ELSEWHERE)
    return [{"append": name, "menuItem": "Std_DlgPreferences"} for name in names if name in have]


# --------------------------------------------------------------------------- FreeCAD's key sequences

OWN_KEYS = ("A", "D", "N", "Y")


def single_keys():
    from . import keys
    out = set(OWN_KEYS)
    for _, key in keys.KEYS:
        if key and "," not in key:
            out.add(QtGui.QKeySequence(key).toString())
    return out


def drop_copies(widget=None):
    """FreeCAD's group entries (Tools > Sketch Entities > Line...) copy the key of the command they
    stand for, and two actions on one key make Qt run neither. Takes the key off every action that is
    not the command's own, when the command has one. Returns the texts of the actions cleared."""
    from . import keys
    widget = widget or Gui.getMainWindow()
    if widget is None:
        return []
    owners = {}
    for name, key in keys.KEYS:
        if not key:
            continue
        try:
            command = Gui.Command.get(name)
            own = [a for a in command.getAction() if isinstance(a, QtGui.QAction)] if command is not None else []
        except Exception:
            own = []
        if own:
            owners[QtGui.QKeySequence(key).toString()] = own[0]
    cleared = []
    for action in widget.findChildren(QtGui.QAction):
        owner = owners.get(action.shortcut().toString())
        if owner is not None and action is not owner:
            action.setShortcut(QtGui.QKeySequence())
            cleared.append(action.objectName() or action.text())
    return cleared


def drop_sequences(widget=None):
    ""


    widget = widget or Gui.getMainWindow()
    if widget is None:
        return []
    singles = single_keys()
    cleared = []
    for action in widget.findChildren(QtGui.QAction):
        seq = action.shortcut()
        if seq.count() < 2:
            continue
        first = QtGui.QKeySequence(seq[0]).toString()
        if first in singles:
            action.setShortcut(QtGui.QKeySequence())
            cleared.append(action.objectName() or action.text())
    return cleared


# --------------------------------------------------------------------------- Tab in the 3D view
def _view():
    try:
        view = Gui.ActiveDocument.ActiveView
        return view if hasattr(view, "getObjectInfo") else None
    except Exception:
        return None


def _is_component(obj):
    """An assembly component (a link or part directly in an assembly): the unit Tab hides."""
    try:
        if obj is None or obj.TypeId not in ("App::Link", "App::Part", "App::LinkElement"):
            return False
        return any(o.TypeId == "Assembly::AssemblyObject" for o in (obj.InList or []))
    except Exception:
        return False


def _component_of(info):
    """The top-level component the pick went through ({'ParentObject': assembly, 'SubName':
    'Component.Body.Face6'}), else None (FreeCAD names the innermost feature and its own document)."""
    parent = info.get("ParentObject")
    sub = info.get("SubName") or ""
    if parent is None or "." not in sub:
        return None
    try:
        obj = parent.Document.getObject(sub.split(".")[0])
    except Exception:
        return None
    return obj if _is_component(obj) else None


def top_body(obj):
    """The body (or other top-level shape) a picked feature belongs to."""
    if obj is None:
        return None
    try:
        body = obj.getParentGeoFeatureGroup() if hasattr(obj, "getParentGeoFeatureGroup") else None
    except Exception:
        body = None

    for _ in range(20):
        try:
            parent = body.getParentGeoFeatureGroup() if body is not None else None
        except Exception:
            parent = None
        if parent is None:
            break
        body = parent
    return body or obj


def _ray(view, pos):
    """The pointer's line of sight in model space: (point, direction)."""
    point = view.getPoint(int(pos.x()), int(pos.y()))
    direction = view.getViewDirection()
    return App.Vector(point), App.Vector(direction)


def hidden_body_at(view, pos, candidates):
    """The hidden body whose shape the pointer's line of sight crosses, nearest first."""
    import Part
    try:
        point, direction = _ray(view, pos)
    except Exception:
        return None
    if direction.Length < 1e-9:
        return None
    direction.normalize()
    far = 1e6
    line = Part.LineSegment(point - direction * far, point + direction * far).toShape()
    best = None
    for obj in candidates:
        shape = getattr(obj, "Shape", None)
        if shape is None and _is_component(obj):
            try:
                shape = Part.getShape(obj)          # a link component: its part's shape where it is placed
            except Exception:
                shape = None
        if shape is None or shape.isNull():
            continue
        try:
            dist, pairs, _ = shape.distToShape(line)
        except Exception:
            continue
        if dist > 1e-6 or not pairs:
            continue
        depth = (pairs[0][0] - (point - direction * far)).dot(direction)
        if best is None or depth < best[0]:
            best = (depth, obj)
    return best[1] if best else None


def _device_pos(view_widget, global_pos):
    """FreeCAD's getPoint takes pixels counted from the viewport's bottom-left."""
    local = view_widget.mapFromGlobal(global_pos)
    ratio = view_widget.devicePixelRatioF() if hasattr(view_widget, "devicePixelRatioF") else 1.0
    return QtCore.QPoint(int(local.x() * ratio), int((view_widget.height() - local.y()) * ratio))


class HoverKeys(QtCore.QObject):
    """Tab, Shift+Tab and Ctrl+Shift+Tab over the 3D view."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hidden = []            # (document name, object name) Tab hid, oldest first
        self.log = []               # for checks

    def _over_view(self):
        s = _shell()
        if s is None or _view() is None:
            return None
        if QtWidgets.QApplication.activePopupWidget() is not None or QtWidgets.QApplication.activeModalWidget():
            return None
        widget = s.view_widget()
        if widget is None or not alive(widget):
            return None
        target = widget.viewport() if hasattr(widget, "viewport") and widget.viewport() is not None else widget
        local = target.mapFromGlobal(QtGui.QCursor.pos())
        if not target.rect().contains(local):
            return None
        focus = QtWidgets.QApplication.focusWidget()
        if isinstance(focus, (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox, QtWidgets.QTextEdit,
                              QtWidgets.QPlainTextEdit)):
            return None
        # the keyboard in a PropertyManager (or another pane: tree, task panel): Tab moves between its

        w = focus
        while w is not None:
            if isinstance(w, QtWidgets.QDockWidget) or w.metaObject().className() == "Gui::TaskView::TaskView":
                return None
            w = w.parentWidget()
        return target

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        if t not in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride):
            return False
        key = event.key()
        if key not in (Qt.Key_Tab, Qt.Key_Backtab):
            return False
        mods = event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier)
        if mods & Qt.AltModifier:
            return False
        if mods & Qt.ControlModifier and not mods & Qt.ShiftModifier and key == Qt.Key_Tab:
            return False        # Ctrl+Tab is Browse Open Documents (the key was taken here and did nothing)
        target = self._over_view()
        if target is None:
            return False
        if t == QtCore.QEvent.ShortcutOverride:
            event.accept()
            return True
        if event.isAutoRepeat():
            return True
        shift = bool(mods & Qt.ShiftModifier) or key == Qt.Key_Backtab
        ctrl = bool(mods & Qt.ControlModifier)
        if ctrl and shift:
            self.show_all()
        elif shift:
            self.show_under(target)
        elif not ctrl:
            self.hide_under()
        else:
            return False
        return True

    def object_under_pointer(self):
        """What the pointer is over in the 3D view (FreeCAD's pick at the cursor), else the preselection."""
        view = _view()
        obj = None
        try:
            info = view.getObjectInfo(view.getCursorPos()) if view is not None else None
        except Exception:
            info = None
        if info:
            comp = _component_of(info)
            if comp is not None:
                return comp
            doc = App.getDocument(info.get("Document")) if info.get("Document") else App.ActiveDocument
            obj = doc.getObject(info.get("Object", "")) if doc is not None else None
        if obj is None:
            try:
                pre = Gui.Selection.getPreselection()
                obj = pre.Object if pre is not None and pre.ObjectName else None
            except Exception:
                obj = None
        return obj

    def hide_under(self):
        obj = self.object_under_pointer()
        body = obj if _is_component(obj) else top_body(obj)
        if body is None or not hasattr(body, "ViewObject") or body.ViewObject is None:
            self.log.append(("hide", None))
            return None
        doc = body.Document
        doc.openTransaction("Hide")
        try:
            body.ViewObject.Visibility = False
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self.hidden.append((doc.Name, body.Name))
        Gui.Selection.removeSelection(body)
        self.log.append(("hide", body.Name))
        return body

    def _candidates(self):
        doc = App.ActiveDocument
        if doc is None:
            return []
        out = []
        for obj in doc.Objects:
            vo = getattr(obj, "ViewObject", None)
            if vo is None or vo.Visibility or not (hasattr(obj, "Shape") or _is_component(obj)):
                continue
            if _is_component(obj) or obj.TypeId in ("PartDesign::Body", "App::Part") or (
                    obj.isDerivedFrom("Part::Feature") and obj.getParentGeoFeatureGroup() is None):
                out.append(obj)
        return out

    def show_under(self, target):
        view = _view()
        try:
            x, y = view.getCursorPos()
            pos = QtCore.QPoint(int(x), int(y))
        except Exception:
            pos = _device_pos(target, QtGui.QCursor.pos())
        body = hidden_body_at(view, pos, self._candidates()) if view else None
        if body is None:
            self.log.append(("show", None))
            return None
        doc = body.Document
        doc.openTransaction("Show")
        try:
            body.ViewObject.Visibility = True
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        self.hidden = [h for h in self.hidden if h != (doc.Name, body.Name)]
        self.log.append(("show", body.Name))
        return body

    def show_all(self):
        shown = []
        for doc_name, name in self.hidden:
            doc = App.listDocuments().get(doc_name)
            obj = doc.getObject(name) if doc is not None else None
            if obj is not None and obj.ViewObject is not None and not obj.ViewObject.Visibility:
                obj.ViewObject.Visibility = True
                shown.append(name)
        self.hidden = []
        self.log.append(("show all", tuple(shown)))
        return shown


_hover = None


def install():
    global _hover
    if _hover is None:
        _hover = HoverKeys(QtWidgets.QApplication.instance())
        from . import events
        events.register("swkeys.hover", (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride), _hover.eventFilter)
    return _hover


def remove():
    global _hover
    if _hover is not None:
        from . import events
        events.unregister("swkeys.hover")
    _hover = None
