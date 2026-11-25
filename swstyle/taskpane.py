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

from . import icons
from .widgets import alive, scaled

Qt = QtCore.Qt
WIDTH = 300
ROLE = Qt.UserRole + 1
OPENABLE = (".fcstd", ".step", ".stp", ".iges", ".igs", ".stl", ".obj", ".brep", ".brp", ".dxf", ".svg",
            ".sldprt", ".sldasm", ".fcmacro", ".py", ".3mf", ".ply", ".off", ".dae", ".ifc")
PAGES = {}             # tab index -> function(pane) -> QWidget  (other modules add theirs)
PANE_PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/TaskPane"
GRIP = 5               # the left edge that resizes the docked pane
DRAG = 12              # pixels a title drag goes before the pane comes off as a floating window


def _pp():
    return App.ParamGet(PANE_PARAMS)


def register_page(index, make):
    PAGES[index] = make


# --------------------------------------------------------------------------- shared
def explorer_option(text, default):
    """Options > System Options > File Explorer, "Show in File Explorer view" (kept by optionspages)."""
    try:
        from . import optionspages
        return bool(optionspages.stored("File Explorer", text, default))
    except Exception:
        return default


def _samples_dir():
    for d in (os.path.join(App.getResourceDir(), "examples"), os.path.join(App.getHomePath(), "data", "examples")):
        if os.path.isdir(d):
            return d
    return None


def _is_hidden(path):
    name = os.path.basename(path)
    if name.startswith("."):
        return True
    if os.name == "nt":
        try:
            import ctypes
            attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
            return attrs != -1 and bool(attrs & 2)       # FILE_ATTRIBUTE_HIDDEN
        except Exception:
            return False
    return False


def recent_files():
    p = App.ParamGet("User parameter:BaseApp/Preferences/RecentFiles")
    out = []
    for i in range(p.GetInt("RecentFiles", 12) or 12):
        f = p.GetString("MRU%d" % i, "")
        if f and f not in out:
            out.append(f)
    return out


def open_file(path):
    """What a double-click on a file does: open it (FreeCAD's own importers for other types)."""
    if not path:
        return False
    for doc in App.listDocuments().values():
        if os.path.normcase(os.path.abspath(doc.FileName or "")) == os.path.normcase(os.path.abspath(path)):
            Gui.getDocument(doc.Name) and _activate(doc)
            return True
    # save114: a recent file that moved, or a damaged one, says why it did not open (it used to do nothing: the
    # Welcome box closed and no file came up); FreeCAD files go through Open's own path
    ext = os.path.splitext(path)[1].lower()
    if ext == ".fcstd" or not os.path.isfile(path) or App.getImportType(ext[1:]) or App.getImportType(ext[1:].upper()):
        # (Gui.open said "File type 'step' not supported": Open's path reads STEP / IGES / meshes itself)
        from . import saveas
        return bool(saveas.open_files([path]))
    Gui.open(path)
    return True


def _activate(doc):
    App.setActiveDocument(doc.Name)
    try:
        view = Gui.getDocument(doc.Name).mdiViewsOfType("Gui::View3DInventor")[0]
        Gui.getMainWindow().setActiveWindow(view)
    except Exception as _fw_err:
        _fw_log("taskpane.py:117", _fw_err)


def _button(text, icon=None, run=None):
    b = QtWidgets.QToolButton()
    b.setText(text)
    b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    b.setAutoRaise(True)
    if icon:
        b.setIcon(icons.family(icon))
    if run is not None:
        b.clicked.connect(lambda checked=False: run())
    b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
    return b


# --------------------------------------------------------------------------- Home
def _new(kind):
    from . import newdoc
    return newdoc.make(kind)


def _command_live(name):
    try:
        return Gui.Command.get(name) is not None
    except Exception:
        return False



# collapsible groups of links. Only what FreeCAD can back is listed: Performance Benchmark Test, Compare My Score,
# My Products, Partner Solutions and Subscription Services have nothing behind them and are left out.
RESOURCES = (
    (None, (("Welcome to FreeCAD", "TASKPANE_HOME_TAB", "SWStyle_Welcome"),)),
    ("FreeCAD Tools", (("Property Tab Builder", "FW_PropertyTabBuilder", "SWStyle_PropertyTabBuilder"),
                       ("FreeCAD Rx", "FW_Rx", "SWStyle_Rx"),
                       ("Settings Wizard", "FW_SaveRestoreSettings", "SWStyle_SaveRestoreSettings"))),
    ("Online Resources", (("Add-on Manager", "FW_AddonManager", "Std_AddonMgr"),)),
)


def _link(text, family, command):
    b = QtWidgets.QPushButton(text)
    b.setFlat(True)
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(lambda checked=False: _run_first((command,)))
    pic = icons.family(family) if family else None
    if pic is None or not icons.paints(pic):
        pic = icons.drawn(command)      # the drawn picture of the command (resources/icons-drawn/FW_<command>.svg)
    if pic is None or not icons.paints(pic):
        try:
            pic = Gui.getIcon((Gui.Command.get(command).getInfo() or {}).get("pixmap") or "")
        except Exception:
            pic = None
    if pic is not None and not pic.isNull():
        b.setIcon(pic)
        b.setIconSize(QtCore.QSize(16, 16))
    b.setStyleSheet("QPushButton { text-align: left; padding: 3px 4px; border: none; }"
                    "QPushButton:hover { text-decoration: underline; }")
    b.setObjectName("SWTaskPaneLink_" + command)
    b.setToolTip(text)
    return b


def _section(title, rows):
    ""

    box = QtWidgets.QWidget()
    box.setObjectName("SWTaskPaneSection_" + title.replace(" ", ""))
    v = QtWidgets.QVBoxLayout(box)
    v.setContentsMargins(0, 8, 0, 0)
    v.setSpacing(0)
    head = QtWidgets.QHBoxLayout()
    label = QtWidgets.QLabel("<b>%s</b>" % title)
    head.addWidget(label, 1)
    fold = QtWidgets.QToolButton()
    fold.setAutoRaise(True)
    fold.setCheckable(True)
    fold.setObjectName("SWTaskPaneFold")
    fold.setToolTip("Collapse")
    head.addWidget(fold)
    v.addLayout(head)
    rule = QtWidgets.QFrame()
    rule.setFrameShape(QtWidgets.QFrame.HLine)
    rule.setFrameShadow(QtWidgets.QFrame.Plain)
    v.addWidget(rule)
    body = QtWidgets.QWidget()
    bl = QtWidgets.QVBoxLayout(body)
    bl.setContentsMargins(0, 2, 0, 0)
    bl.setSpacing(0)
    for row in rows:
        bl.addWidget(row)
    v.addWidget(body)
    key = "Folded." + title

    def apply(folded):
        body.setVisible(not folded)
        fold.setArrowType(Qt.DownArrow if folded else Qt.UpArrow)
        fold.setToolTip("Expand" if folded else "Collapse")
        _pp().SetBool(key, bool(folded))
    fold.toggled.connect(apply)
    folded = _pp().GetBool(key, False)
    fold.blockSignals(True)
    fold.setChecked(folded)
    fold.blockSignals(False)
    apply(folded)
    box.fold = fold
    box.body = body
    return box


def home_page(pane):
    ""
    w = QtWidgets.QWidget()
    w.setObjectName("SWTaskPaneHome")
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(6, 6, 6, 6)
    lay.setSpacing(0)
    w.links = []
    for title, rows in RESOURCES:
        links = [_link(t, f, c) for t, f, c in rows if _command_live(c)]
        w.links += links
        if not links:
            continue
        if title is None:
            for b in links:
                lay.addWidget(b)
        else:
            lay.addWidget(_section(title, links))
    lay.addStretch(1)
    return w


TUTORIALS_URL = "https://wiki.freecad.org/Tutorials"

TIPS = (
    "Hold Shift while sketching a line to snap its length to the grid step; hold Ctrl to place it with no snaps "
    "and no automatic relations.",
    "F3 turns the sketch snaps on and off for the whole sketch.",
    "Press S in the graphics area for the shortcut bar of the current mode.",
    "Middle-click an edge, then drag with the middle button, to rotate about that edge.",
    "Drag an appearance from the Appearances tab onto a face to choose Face, Feature, Body or Part.",
    "Drag a part from the File Explorer tab into an open assembly to insert it where you drop it.",
    "Double-click a dimension to change its value; type = to start an equation.",
    "Right-click a feature and pick Edit Sketch to go straight to its sketch.",
    "Ctrl+Q forces a rebuild of every feature; Ctrl+B rebuilds only what changed.",
    "Right-click the CommandManager tabs to show or hide tabs, including every FreeCAD workbench tab.",
    "The Add-Ins tab's All FreeCAD Tools menu reaches every command of every FreeCAD workbench.",
    "Use the View Palette tab to drag standard views of a part onto a drawing sheet.",
    "Window-select from right to left to pick everything the box touches; left to right picks only what is inside.",
    "Pin the Task Pane to keep it open while you work in the graphics area.",
)


def _tip_index(step=0):
    p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks/TaskPane")
    i = (p.GetInt("TipOfTheDay", 0) + step) % len(TIPS)
    p.SetInt("TipOfTheDay", i)
    return i


def tip_box():
    box = QtWidgets.QGroupBox("Tip of the Day")
    box.setObjectName("SWTaskPaneTip")
    v = QtWidgets.QVBoxLayout(box)
    text = QtWidgets.QLabel()
    text.setWordWrap(True)
    text.setObjectName("SWTaskPaneTipText")
    v.addWidget(text)
    nxt = QtWidgets.QPushButton("Next Tip")
    nxt.setObjectName("SWTaskPaneNextTip")
    nxt.setFlat(True)
    nxt.clicked.connect(lambda checked=False: text.setText(TIPS[_tip_index(1)]))
    v.addWidget(nxt, 0, Qt.AlignRight)
    text.setText(TIPS[_tip_index(1)])
    box.next_tip = nxt.click
    return box


def _run_first(names):
    for name in names:
        try:
            if Gui.Command.get(name) is not None:
                Gui.runCommand(name, 0)
                return True
        except Exception:
            continue
    return False


# --------------------------------------------------------------------------- File Explorer
class Explorer(QtWidgets.QTreeWidget):
    ""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWTaskPaneExplorer")
        self.setHeaderHidden(True)
        self.itemExpanded.connect(self._expand)
        self.itemDoubleClicked.connect(self._open)
        self.provider = QtWidgets.QFileIconProvider()
        self.setDragEnabled(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: (lambda m: m and m.popup(self.viewport().mapToGlobal(pos)))(self.menu_for(self.itemAt(pos))))
        self.refresh()

    def menu_for(self, item):
        ""


        menu = QtWidgets.QMenu(self)
        menu.setObjectName("SWTaskPaneExplorerMenu")
        if item is None:
            menu.addAction("Refresh", self.refresh)
            return menu
        name = item.data(0, ROLE + 2)
        path = item.data(0, ROLE)
        folder = item.data(0, ROLE + 1) == "folder"
        if name and name in App.listDocuments():
            doc = App.getDocument(name)
            menu.addAction("Show", lambda: _activate(doc))
            menu.addAction("Save", lambda: (_activate(doc), _run_first(("SWStyle_Save", "Std_Save"))))
            menu.addAction("Close", lambda: (_activate(doc), _run_first(("Std_CloseActiveWindow",)),
                                             QtCore.QTimer.singleShot(300, self.refresh)))
        elif path and not folder:
            menu.addAction("Open", lambda: open_file(path))
            if App.ActiveDocument is not None:
                def insert():
                    try:
                        from . import designlib
                        designlib.insert(path)
                    except Exception as error:
                        App.Console.PrintError("FreeCAD: Insert %s: %s\n" % (path, error))
                menu.addAction("Insert into Active Document", insert)
            menu.addAction("Open Containing Folder", lambda: QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(os.path.dirname(path))))
            menu.addAction("Copy Path", lambda: QtWidgets.QApplication.clipboard().setText(path))
        elif path and folder:
            def again():
                item.takeChildren()
                item.setChildIndicatorPolicy(QtWidgets.QTreeWidgetItem.ShowIndicator)
                self._expand(item)
                item.setExpanded(True)
            menu.addAction("Refresh", again)
            menu.addAction("Open in File Browser", lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path)))

            def to_library():
                try:
                    from . import designlib
                    designlib.add_location(path)
                except Exception as error:
                    App.Console.PrintError("FreeCAD: Add File Location: %s\n" % error)
            menu.addAction("Add File Location to Design Library", to_library)
            menu.addAction("Copy Path", lambda: QtWidgets.QApplication.clipboard().setText(path))
        else:
            menu.addAction("Refresh", self.refresh)
        return menu

    def mimeData(self, items):
        data = QtCore.QMimeData()
        path = items[0].data(0, ROLE) if items else None
        if path and items[0].data(0, ROLE + 1) != "folder":
            try:
                from . import designlib
                data.setData(designlib.MIME, QtCore.QByteArray(path.encode()))
            except Exception as _fw_err:
                _fw_log("taskpane.py:323", _fw_err)
            data.setUrls([QtCore.QUrl.fromLocalFile(path)])
        return data

    def mimeTypes(self):
        return ["application/x-freeworks-library", "text/uri-list"]

    def startDrag(self, actions):
        try:
            from . import designlib
            designlib.watch_views()
        except Exception as _fw_err:
            _fw_log("taskpane.py:335", _fw_err)
        super().startDrag(actions)

    def _node(self, parent, text, path, folder, icon=None):
        item = QtWidgets.QTreeWidgetItem([text])
        item.setData(0, ROLE, path)
        item.setToolTip(0, path or text)
        if icon is not None:
            item.setIcon(0, icon)
        elif path:
            item.setIcon(0, self.provider.icon(QtCore.QFileInfo(path)))
        if folder:
            item.setChildIndicatorPolicy(QtWidgets.QTreeWidgetItem.ShowIndicator)
            item.setData(0, ROLE + 1, "folder")
        (parent.addChild(item) if parent is not None else self.addTopLevelItem(item))
        return item

    def refresh(self):
        self.clear()
        folder_icon = self.provider.icon(QtWidgets.QFileIconProvider.Folder)
        opened = self._node(None, "Open in FreeCAD", None, False, folder_icon)
        for doc in App.listDocuments().values():
            item = self._node(opened, doc.Label, doc.FileName or None, False, icons.family("PART"))
            item.setData(0, ROLE + 2, doc.Name)
        recent = self._node(None, "Recent Documents", None, False, folder_icon)
        for f in recent_files():
            self._node(recent, os.path.basename(f), f, False)
        home = os.path.expanduser("~")
        for name in ("Desktop", "Documents"):
            path = os.path.join(home, name)
            if os.path.isdir(path):
                self._node(None, name, path, True)
        self._node(None, os.path.basename(home) or home, home, True)
        for drive in QtCore.QDir.drives():
            path = drive.absoluteFilePath()
            if path not in ("/",) or os.name != "nt":
                self._node(None, QtCore.QDir.toNativeSeparators(path), path, True)
        opened.setExpanded(True)
        self._apply_options()

    def _apply_options(self):
        ""

        home = os.path.expanduser("~")
        wanted = {
            "Recent Documents": explorer_option("Recent Documents", False),
            "Documents": explorer_option("My Documents", True),
        }
        drives = explorer_option("My Computer", True)
        for i in reversed(range(self.topLevelItemCount())):
            item = self.topLevelItem(i)
            text = item.text(0)
            path = item.data(0, ROLE)
            show = True
            if text in wanted:
                show = wanted[text]
            elif path and item.data(0, ROLE + 1) == "folder" and os.path.normcase(path.rstrip("/\\")) in (
                    os.path.normcase(d.absoluteFilePath().rstrip("/\\")) for d in QtCore.QDir.drives()):
                show = drives
            item.setHidden(not show)
        if explorer_option("My Network Places", False) and os.name == "nt":
            self._node(None, "My Network Places", "\\\\", True)
        samples = _samples_dir()
        if explorer_option("Samples", False) and samples:
            self._node(None, "Samples", samples, True)

    def _expand(self, item):
        if item.data(0, ROLE + 1) != "folder" or item.childCount():
            return
        path = item.data(0, ROLE)
        try:
            names = sorted(os.listdir(path), key=str.lower)
        except Exception:
            names = []
        folders, files = [], []
        hidden_ok = explorer_option("Hidden referenced documents", True)
        for n in names:
            full = os.path.join(path, n)
            if not hidden_ok and _is_hidden(full):
                continue
            if os.path.isdir(full):
                folders.append((n, full))
            elif os.path.splitext(n)[1].lower() in OPENABLE:
                files.append((n, full))
        for n, full in folders:
            self._node(item, n, full, True)
        for n, full in files:
            self._node(item, n, full, False)
        if not folders and not files:
            item.setChildIndicatorPolicy(QtWidgets.QTreeWidgetItem.DontShowIndicator)

    def _open(self, item, column=0):
        name = item.data(0, ROLE + 2)
        if name and name in App.listDocuments():
            _activate(App.getDocument(name))
            return True
        path = item.data(0, ROLE)
        if path and item.data(0, ROLE + 1) != "folder":
            return open_file(path)
        return False

    def find(self, path, parent=None):
        """The row of a path, expanding the folders on the way (tests and Back/Forward)."""
        items = [self.topLevelItem(i) for i in range(self.topLevelItemCount())] if parent is None else \
            [parent.child(i) for i in range(parent.childCount())]
        for item in items:
            p = item.data(0, ROLE)
            if p and os.path.normcase(p) == os.path.normcase(path):
                return item
        for item in items:
            p = item.data(0, ROLE)
            if p and item.data(0, ROLE + 1) == "folder" and os.path.normcase(path).startswith(
                    os.path.normcase(p.rstrip("/\\")) + os.sep):
                self._expand(item)
                item.setExpanded(True)
                found = self.find(path, item)
                if found is not None:
                    return found
        return None


def explorer_page(pane):
    w = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    tree = Explorer(w)
    lay.addWidget(tree)
    w.tree = tree
    w.refresh = tree.refresh
    return w


# --------------------------------------------------------------------------- pages still to come
def launcher_page(index):
    def make(pane):
        from .chrome import TaskPaneTabs
        family, tip, target = TaskPaneTabs.ITEMS[index]
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        label = QtWidgets.QLabel(tip)
        label.setWordWrap(True)
        lay.addWidget(label)
        if isinstance(target, tuple):
            b = _button("Open", family, lambda: _run_first(target))
            lay.addWidget(b)
        lay.addStretch(1)
        return w
    return make


def _own(module, index):
    """A page that lives in its own module (loaded the first time its tab opens)."""
    def make(pane):
        try:
            import importlib
            return importlib.import_module("." + module, __package__).page(pane)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Task Pane %s: %s\n" % (module, error))
            return launcher_page(index)(pane)
    return make


register_page(0, home_page)
register_page(1, _own("designlib", 1))
register_page(2, explorer_page)
register_page(3, _own("viewpalette", 3))
register_page(4, _own("appearpane", 4))
register_page(5, _own("customprops", 5))

# --------------------------------------------------------------------------- Forum
FORUM_URL = "https://forum.freecad.org"
FORUM_FEED = "https://forum.freecad.org/app.php/feed?mode=topics"


def forum_page(pane):
    ""

    from PySide import QtNetwork
    w = QtWidgets.QWidget()
    w.setObjectName("SWTaskPaneForum")
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(6, 6, 6, 6)
    row = QtWidgets.QHBoxLayout()
    b = _button("Open the forum", None, lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl(FORUM_URL)))
    b.setObjectName("SWTaskPaneForumOpen")
    row.addWidget(b)
    refresh = _button("Refresh", None, None)
    refresh.setObjectName("SWTaskPaneForumRefresh")
    row.addWidget(refresh)
    row.addStretch(1)
    lay.addLayout(row)
    search = QtWidgets.QLineEdit()
    search.setObjectName("SWTaskPaneForumSearch")
    search.setPlaceholderText("Search the forum")
    search.setClearButtonEnabled(True)
    lay.addWidget(search)
    lay.addWidget(QtWidgets.QLabel("<b>Latest Topics</b>"))
    topics = QtWidgets.QListWidget()
    topics.setObjectName("SWTaskPaneForumTopics")
    topics.setWordWrap(True)
    topics.itemDoubleClicked.connect(lambda item: QtGui.QDesktopServices.openUrl(QtCore.QUrl(item.data(ROLE))))
    lay.addWidget(topics, 1)
    status = QtWidgets.QLabel("")
    status.setObjectName("SWTaskPaneForumStatus")
    status.setWordWrap(True)
    lay.addWidget(status)
    w.topics = topics
    w.net = QtNetwork.QNetworkAccessManager(w)

    def do_search():
        text = search.text().strip()
        if text:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(FORUM_URL + "/search.php?keywords=" + QtCore.QUrl.toPercentEncoding(text).data().decode()))
    search.returnPressed.connect(do_search)

    def parse(data):
        import xml.etree.ElementTree as ET
        ns = {"a": "http://www.w3.org/2005/Atom"}
        out = []
        root = ET.fromstring(data)
        for entry in root.findall("a:entry", ns):
            title = entry.findtext("a:title", "", ns).strip()
            link = ""
            for l in entry.findall("a:link", ns):
                if l.get("rel", "alternate") == "alternate":
                    link = l.get("href", "")
                    break
            author = entry.findtext("a:author/a:name", "", ns).strip()
            when = entry.findtext("a:updated", "", ns)[:10]
            out.append((title, link, author, when))
        return out

    def done(reply):
        try:
            if reply.error() != QtNetwork.QNetworkReply.NoError:
                from .helpmenu import net_words
                status.setText(net_words(reply, "the forum"))
                return
            entries = parse(bytes(reply.readAll().data()))
        except Exception as error:
            status.setText("The forum's feed could not be read (%s)." % error)
            return
        finally:
            reply.deleteLater()
        topics.clear()
        for title, link, author, when in entries:
            item = QtWidgets.QListWidgetItem(title)
            item.setToolTip("%s, %s\n%s" % (author, when, link))
            item.setData(ROLE, link)
            topics.addItem(item)
        status.setText("%d topics. Double-click one to read it in the browser." % len(entries))
    w.net.finished.connect(done)

    def fetch():
        status.setText("Reading the forum...")
        req = QtNetwork.QNetworkRequest(QtCore.QUrl(FORUM_FEED))
        try:
            req.setAttribute(QtNetwork.QNetworkRequest.RedirectPolicyAttribute, QtNetwork.QNetworkRequest.NoLessSafeRedirectPolicy)
        except Exception as _fw_err:
            _fw_log("taskpane.py:595", _fw_err)
        w.net.get(req)
    refresh.clicked.connect(fetch)
    w.refresh = fetch
    fetch()
    return w


register_page(6, _own("importpane", 6))


# --------------------------------------------------------------------------- the pane
class Pane(QtWidgets.QFrame):
    """The sliding pane, a child of the 3D view next to the tabs."""

    def __init__(self, tabs):
        super().__init__(tabs.parentWidget())
        self.tabs = tabs
        self.setObjectName("SWTaskPane")
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setAutoFillBackground(True)
        self.index = -1
        self.pages = {}
        self.history, self.at = [], -1
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(2, 2, 2, 2)
        self.back = self._tool("Back", "ARROW_BACK", self.go_back)
        self.forward = self._tool("Forward", "ARROW_FORWARD", self.go_forward)
        self.home = self._tool("Home", "TASKPANE_HOME_TAB", lambda: self.show_tab(0))

        # page's name in bold in the middle, Options (gear) and Keep Visible (pin) at the right; the
        # tabs at the edge are the way between pages (back, forward and home kept for the code, unshown)
        for w in (self.back, self.forward, self.home):
            w.hide()
        self.fold = QtWidgets.QToolButton(self)
        self.fold.setObjectName("SWTaskPaneFold")
        self.fold.setAutoRaise(True)
        self.fold.setText("\u00ab")
        self.fold.setToolTip("Collapse the Task Pane")
        self.fold.clicked.connect(lambda checked=False: self.close_pane())
        self.title = QtWidgets.QLabel()
        self.title.setObjectName("SWTaskPaneTitle")
        self.title.setAlignment(Qt.AlignCenter)
        bold = self.title.font()
        bold.setBold(True)
        self.title.setFont(bold)
        self.gear = self._tool("Options", "STANDARD_OPTIONS", self._options)
        self.gear.setObjectName("SWTaskPaneOptions")
        self.pin = self._tool("Pin", "PIN_NORMAL", None)
        self.pin.setObjectName("SWTaskPanePin")
        self.pin.setCheckable(True)
        self.pin.setToolTip("Keep Visible")
        self.pin.toggled.connect(self._pinned)
        row.addWidget(self.fold)
        row.addWidget(self.title, 1)
        self.dock_button = QtWidgets.QToolButton(self)
        self.dock_button.setAutoRaise(True)
        self.dock_button.setText("Dock")
        self.dock_button.setToolTip("Dock Task Pane")
        self.dock_button.clicked.connect(lambda checked=False: self.dock())
        self.dock_button.setObjectName("SWTaskPaneDock")
        self.dock_button.hide()
        row.addWidget(self.dock_button)
        row.addWidget(self.gear)
        row.addWidget(self.pin)
        lay.addLayout(row)
        self.stack = QtWidgets.QStackedWidget(self)
        lay.addWidget(self.stack, 1)
        self.hide()
        self._filtered = None

        # double-click on it docks it again; the left edge sets the docked width (kept)
        self.floating = False
        self._press = None
        self.pin.blockSignals(True)
        self.pin.setChecked(_pp().GetBool("Pinned", False))
        self.pin.blockSignals(False)
        self._pinned(self.pin.isChecked())
        self.title.setToolTip("Drag to float the Task Pane; double-click to dock it")
        self.title.installEventFilter(self)
        self.grip = QtWidgets.QWidget(self)
        self.grip.setObjectName("SWTaskPaneGrip")
        self.grip.setCursor(Qt.SizeHorCursor)
        self.grip.setToolTip("Drag to change the Task Pane's width")
        self.grip.installEventFilter(self)
        self._grip_from = None

    def _tool(self, tip, family, run):
        b = QtWidgets.QToolButton(self)
        b.setAutoRaise(True)
        b.setToolTip(tip)
        icon = icons.family(family)
        if icon.isNull():
            b.setText({"Back": "<", "Forward": ">", "Home": "H", "Pin": "P"}.get(tip, tip[:1]))
        else:
            b.setIcon(icon)
        if run is not None:
            b.clicked.connect(lambda checked=False: run())
        return b

    def _options(self):
        ""
        try:
            from . import shell
            shell.shell().binding("Options").run()
        except Exception as _fw_err:
            _fw_log("taskpane.py:options", _fw_err)
            Gui.runCommand("Std_DlgPreferences", 0)

    def _pinned(self, on):
        icon = icons.family("PIN_ACTIVE" if on else "PIN_NORMAL")
        if not icon.isNull():
            self.pin.setIcon(icon)
        _pp().SetBool("Pinned", bool(on))
        self.reserve()

    # -- floating and docking ---------------------------------------------------------------
    def float_pane(self, at=None):
        ""
        if self.floating:
            return
        geo = self.geometry()
        top_left = self.mapToGlobal(QtCore.QPoint(0, 0)) if at is None else at
        self._watch(False)
        self.floating = True
        self.reserve()
        self.setParent(Gui.getMainWindow(), Qt.Tool)
        self.setWindowTitle("Task Pane")
        self.grip.hide()
        self.dock_button.show()
        self.resize(geo.width(), geo.height())
        self.move(top_left)
        self.show()
        self.raise_()

    def dock(self):
        """Back at the right edge of the graphics area (a double-click on the title)."""
        if not self.floating:
            return
        self.floating = False
        self.setParent(self.tabs.parentWidget(), Qt.Widget)
        self.grip.show()
        self.dock_button.hide()
        self.setMinimumSize(0, 0)       # a window's layout set its minimum; docked, place() decides
        self.place()
        self.show()
        self.raise_()
        if alive(self.tabs):
            self.tabs.raise_()
        self._watch(True)
        self.reserve()


    def reserve(self):
        """Pinned and docked and open: the 3D view (or sheet) shrinks so the pane sits beside it;
        otherwise the pane slides over the view and the view keeps its full width."""
        want = self.pinned() and not self.floating and self.isVisible()
        host = self.parentWidget() if want else None
        old = getattr(self, "_reserved", None)
        if old is not None and alive(old) and old is not host:
            try:
                old.setContentsMargins(0, 0, 0, 0)
            except Exception as _fw_err:
                _fw_log("taskpane.py:736", _fw_err)
            self._replace_chrome()
        self._reserved = None
        if host is None or not alive(host):
            return 0
        right = self.width() + (self.tabs.width() if alive(self.tabs) else 0) - 1
        try:
            m = host.contentsMargins()
            changed = m.right() != right
            if changed:
                host.setContentsMargins(0, 0, right, 0)
        except Exception:
            return 0
        self._reserved = host
        if changed:
            self._replace_chrome()
        return right

    def _replace_chrome(self):
        """The heads-up bar and the confirmation corner follow the graphics area's new width."""
        try:
            from . import shell as sh
            overlay = getattr(sh.shell(), "overlay", None)
            for w in (getattr(overlay, "hud", None), getattr(overlay, "confirm", None)):
                if w is not None and alive(w):
                    w.place()
        except Exception as _fw_err:
            _fw_log("taskpane.py:763", _fw_err)

    def _width(self):
        return max(160, _pp().GetInt("Width", 0) or scaled(WIDTH))

    def pinned(self):
        return self.pin.isChecked()

    def page(self, index):
        w = self.pages.get(index)
        if w is None or not alive(w):
            make = PAGES.get(index) or launcher_page(index)
            w = make(self)
            self.pages[index] = w
            self.stack.addWidget(w)
        return w

    def show_tab(self, index, record=True):
        from .chrome import TaskPaneTabs
        w = self.page(index)
        if hasattr(w, "refresh"):
            try:
                w.refresh()
            except Exception as _fw_err:
                _fw_log("taskpane.py:787", _fw_err)
        self.stack.setCurrentWidget(w)
        self.index = index
        items = getattr(self.tabs, "ITEMS", TaskPaneTabs.ITEMS)      # recovery.py adds Document Recovery
        self.title.setText(items[index][1].split(" (")[0] if index < len(items) else "")
        if record:
            del self.history[self.at + 1:]
            if not self.history or self.history[-1] != index:
                self.history.append(index)
            self.at = len(self.history) - 1
        self.tabs.active = index
        self.tabs.update()
        self.place()
        self.show()
        self.raise_()
        self.tabs.raise_()
        self._watch(True)
        self.reserve()

    def go_back(self):
        if self.at > 0:
            self.at -= 1
            self.show_tab(self.history[self.at], record=False)

    def go_forward(self):
        if self.at < len(self.history) - 1:
            self.at += 1
            self.show_tab(self.history[self.at], record=False)

    def close_pane(self):
        self.hide()
        self._watch(False)
        self.reserve()

    def toggle(self, index):
        """A click on a tab: open it; the open tab again closes the pane (unless pinned or floating)."""
        if self.isVisible() and self.index == index:
            if not self.pinned() and not self.floating:
                self.close_pane()
            return
        self.show_tab(index)

    def place(self):
        if self.floating:
            return
        host = self.parentWidget()
        if host is None:
            return
        w = min(self._width(), max(120, host.width() - self.tabs.width() - 40))
        top = self.tabs.y()
        self.setGeometry(host.width() - self.tabs.width() - w + 1, top, w, max(100, host.height() - top - 4))
        self.grip.setGeometry(0, 0, GRIP, self.height())
        self.grip.raise_()
        if getattr(self, "_reserved", None) is not None:
            self.reserve()

    # a click in the view slides an unpinned pane shut
    def _watch(self, on):
        host = self.parentWidget()
        if self._filtered is not None and alive(self._filtered):
            self._filtered.removeEventFilter(self)
        self._filtered = None
        if on and host is not None:
            host.installEventFilter(self)
            self._filtered = host
            # a 3D view's viewer is a QGraphicsView too (Quarter): only a drawing sheet's view gets
            # its viewport watched (land178b: watching the 3D viewer's viewport crashed a run)
            sheet = "MDIViewPage" in host.metaObject().className()
            for child in host.findChildren(QtWidgets.QWidget):
                if child.metaObject().className() in ("QOpenGLWidget", "QtGLWidget", "Gui::View3DInventorViewer") or \
                        child.inherits("QOpenGLWidget"):
                    child.installEventFilter(self)
                elif sheet and isinstance(child, QtWidgets.QGraphicsView) and not self.isAncestorOf(child):
                    child.viewport().installEventFilter(self)       # a drawing sheet's window

    def _title_event(self, event):
        QE = QtCore.QEvent
        t = event.type()
        if t == QE.MouseButtonDblClick and event.button() == Qt.LeftButton:
            self._press = None
            self.dock() if self.floating else self.float_pane()
            return True
        if t == QE.MouseButtonPress and event.button() == Qt.LeftButton:
            self._press = (event.globalPosition().toPoint(), self.mapToGlobal(QtCore.QPoint(0, 0)))
            return False
        if t == QE.MouseMove and self._press is not None and event.buttons() & Qt.LeftButton:
            g = event.globalPosition().toPoint()
            start, origin = self._press
            if not self.floating and (g - start).manhattanLength() >= DRAG:
                self.float_pane(origin + (g - start))
            elif self.floating:
                self.move(origin + (g - start))
            return True
        if t == QE.MouseButtonRelease:
            moved = self._press is not None
            self._press = None
            if moved and self.floating and self._near_edge(event.globalPosition().toPoint()):
                self.dock()             # let go by the graphics area's right edge: docked again
                return True
        return False

    def _near_edge(self, g):
        host = self.tabs.parentWidget() if alive(self.tabs) else None
        if host is None or not host.isVisible():
            return False
        p = host.mapFromGlobal(g)
        return 0 <= p.y() <= host.height() and host.width() - 40 <= p.x() <= host.width() + 10

    def _grip_event(self, event):
        QE = QtCore.QEvent
        t = event.type()
        if t == QE.MouseButtonPress and event.button() == Qt.LeftButton:
            self._grip_from = (event.globalPosition().toPoint().x(), self.width())
            return True
        if t == QE.MouseMove and self._grip_from is not None:
            if not event.buttons() & Qt.LeftButton:
                self._grip_from = None      # the release went elsewhere
                return False
            x0, w0 = self._grip_from
            _pp().SetInt("Width", int(max(160, w0 - (event.globalPosition().toPoint().x() - x0))))
            self.place()
            return True
        if t == QE.MouseButtonRelease and self._grip_from is not None:
            self._grip_from = None
            return True
        return False

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if obj is getattr(self, "title", None):
            return self._title_event(event)
        if obj is getattr(self, "grip", None):
            return self._grip_event(event)
        if event.type() == QtCore.QEvent.MouseButtonPress and self.isVisible() and not self.pinned() \
                and not self.floating:
            try:
                g = event.globalPosition().toPoint()
            except Exception:
                g = event.globalPos()
            inside = self.rect().contains(self.mapFromGlobal(g)) or \
                (alive(self.tabs) and self.tabs.rect().contains(self.tabs.mapFromGlobal(g)))
            if not inside:
                self.close_pane()
        return False


def open_tab(index):
    ""
    try:
        from . import shell as sh
        s = sh.shell()
        tabs = s.overlay.tasks if s is not None and getattr(s, "enabled", False) and s.overlay is not None else None
    except Exception:
        tabs = None
    if tabs is None or not alive(tabs):
        return None
    pane = pane_of(tabs)
    pane.show_tab(index)
    return pane.page(index)


def shut_on_drag_out(widget):
    ""



    pane = widget
    while pane is not None and not isinstance(pane, Pane):
        pane = pane.parentWidget()
    if pane is None or pane.pinned() or pane.floating:
        return lambda: None
    timer = QtCore.QTimer(pane)
    timer.setInterval(40)

    def check():
        if not alive(pane) or not pane.isVisible():
            timer.stop()
            return
        g = QtGui.QCursor.pos()
        if not QtCore.QRect(pane.mapToGlobal(QtCore.QPoint(0, 0)), pane.size()).contains(g):
            timer.stop()
            pane.close_pane()
    timer.timeout.connect(check)
    timer.start()

    def done():
        timer.stop()
        timer.deleteLater()
    return done


def pane_of(tabs):
    p = getattr(tabs, "_pane", None)
    if p is None or not alive(p):
        p = tabs._pane = Pane(tabs)
    if p.parentWidget() is not tabs.parentWidget() and not p.floating:
        visible = p.isVisible()
        p.setParent(tabs.parentWidget())
        if visible:
            p.show()
            p._watch(True)
        p.reserve()                 # the old view gets its width back, the new one makes room
    return p
