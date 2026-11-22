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
import zipfile

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt
GROUP = "User parameter:BaseApp/Preferences/Mod/FreeWorks"
PIN_DOCS, PIN_FOLDERS = "RecentPinned", "RecentPinnedFolders"
TILE = 96
LAST = [None]        # the panel shown last (checks)


def _params():
    return App.ParamGet(GROUP)


def pinned(kind=PIN_DOCS):
    text = _params().GetString(kind, "")
    return [p for p in text.split("\n") if p]


def set_pinned(paths, kind=PIN_DOCS):
    seen, out = set(), []
    for p in paths:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    _params().SetString(kind, "\n".join(out))


def toggle_pin(path, kind=PIN_DOCS):
    """Pins path, or unpins it when it is pinned already. True when it is pinned now."""
    have = pinned(kind)
    if path in have:
        have.remove(path)
        set_pinned(have, kind)
        return False
    set_pinned([path] + have, kind)
    return True


def _freecad_recent():
    """FreeCAD's recent files, newest first, as paths."""
    try:
        group = App.ParamGet("User parameter:BaseApp/Preferences/RecentFiles")
        n = group.GetInt("RecentFiles", 4)
        out = []
        for i in range(max(n, 0) + 20):
            p = group.GetString("MRU%d" % i, "")
            if p:
                out.append(p)
        return out
    except Exception:
        return []


def documents():
    """[(path, pinned)] pinned first (in pin order), then the recent ones; missing pinned files stay listed."""
    pins = pinned(PIN_DOCS)
    out = [(p, True) for p in pins]
    out += [(p, False) for p in _freecad_recent() if p not in pins]
    return out


def folders():
    pins = pinned(PIN_FOLDERS)
    out = [(p, True) for p in pins]
    seen = set(pins)
    for p, _pin in documents():
        d = os.path.dirname(p)
        if d and d not in seen:
            seen.add(d)
            out.append((d, False))
    return out


def open_document(path):
    if not os.path.exists(path):
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Open", "%s\ncould not be found." % path)
        return False
    try:
        for d in App.listDocuments().values():
            if os.path.normcase(os.path.abspath(d.FileName or "")) == os.path.normcase(os.path.abspath(path)):
                App.setActiveDocument(d.Name)
                return True
        # fh162: through File > Open (a STEP, IGES or STL did not open from here; units, damaged files, ...)
        from . import saveas
        return bool([d for d in saveas.open_files([path]) if d is not None])
    except Exception as error:
        App.Console.PrintError("FreeCAD: open %s: %s\n" % (path, error))
        return False


def open_in_folder(folder):
    path, _ = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Open", folder,
                                                    "FreeCAD documents (*.FCStd);;All files (*)")
    if path:
        return open_document(path)
    return False


# --------------------------------------------------------------------------- pictures
def _thumbnail(path):
    pm = QtGui.QPixmap()
    try:
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.lower().endswith("thumbnail.png")), None)
            if name:
                pm.loadFromData(z.read(name))
    except Exception as _fw_err:
        _fw_log("recentdocs.py:134", _fw_err)
    if pm.isNull():
        from . import simicons
        icon = simicons.picture("FW_Document")
        pm = icon.pixmap(TILE - 32, TILE - 32)
    return pm.scaled(TILE - 16, TILE - 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def pin_glyph(on, size=14):
    """A pushpin: upright and filled when pinned, tilted and hollow when not."""
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pm = _hidpi.canvas(size, size)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    col = QtGui.QColor("#2f6fd6") if on else QtGui.QColor("#808080")
    p.translate(size / 2.0, size / 2.0)
    if not on:
        p.rotate(45)
    p.setPen(QtGui.QPen(col, 1.4))
    p.setBrush(col if on else Qt.NoBrush)
    s = size / 14.0
    p.drawRect(QtCore.QRectF(-3 * s, -6 * s, 6 * s, 5 * s))
    p.drawLine(QtCore.QPointF(-5 * s, -1 * s), QtCore.QPointF(5 * s, -1 * s))
    p.drawLine(QtCore.QPointF(0, -1 * s), QtCore.QPointF(0, 6 * s))
    p.end()
    return pm


# --------------------------------------------------------------------------- the panel
class RecentPanel(QtWidgets.QFrame):
    def __init__(self, tab=0, parent=None):
        super().__init__(parent or Gui.getMainWindow(), Qt.Popup)
        self.setObjectName("SWRecentDocuments")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.tabs = QtWidgets.QTabBar(self)
        self.tabs.setObjectName("SWRecentTabs")
        self.tabs.addTab("Documents")
        self.tabs.addTab("Folders")
        lay.addWidget(self.tabs)
        self.list = QtWidgets.QListWidget(self)
        self.list.setObjectName("SWRecentList")
        self.list.setMouseTracking(True)
        lay.addWidget(self.list)
        self.list.viewport().installEventFilter(self)
        self.list.itemActivated.connect(self._open)
        self.tabs.currentChanged.connect(self.fill)
        self.resize(4 * (TILE + 12) + 24, 2 * (TILE + 24) + 60)
        self.tabs.setCurrentIndex(tab)
        self.fill()

    def kind(self):
        return PIN_FOLDERS if self.tabs.currentIndex() == 1 else PIN_DOCS

    def fill(self, *args):
        self.list.clear()
        folders_tab = self.tabs.currentIndex() == 1
        if folders_tab:
            self.list.setViewMode(QtWidgets.QListView.ListMode)
            self.list.setIconSize(QtCore.QSize(16, 16))
            entries = folders()
        else:
            self.list.setViewMode(QtWidgets.QListView.IconMode)
            self.list.setIconSize(QtCore.QSize(TILE - 16, TILE - 24))
            self.list.setGridSize(QtCore.QSize(TILE + 12, TILE + 24))
            self.list.setResizeMode(QtWidgets.QListView.Adjust)
            self.list.setMovement(QtWidgets.QListView.Static)
            entries = documents()
        if not entries:
            it = QtWidgets.QListWidgetItem("No recent folders" if folders_tab else "No recent documents")
            it.setFlags(Qt.NoItemFlags)
            self.list.addItem(it)
            return
        for path, pin in entries:
            name = os.path.basename(path.rstrip("/\\")) or path
            if folders_tab:
                from . import simicons
                icon = simicons.picture("FW_Folder")
            else:
                icon = QtGui.QIcon(self._with_pin(_thumbnail(path), pin))
            it = QtWidgets.QListWidgetItem(icon, name)
            it.setToolTip(path)
            it.setData(Qt.UserRole, path)
            it.setData(Qt.UserRole + 1, pin)
            if folders_tab and pin:
                it.setText(name + "  (pinned)")
            self.list.addItem(it)

    @staticmethod
    def _with_pin(pm, pin):
        out = QtGui.QPixmap(TILE - 16, TILE - 24)
        out.fill(Qt.transparent)
        p = QtGui.QPainter(out)
        p.drawPixmap((out.width() - pm.width()) // 2, (out.height() - pm.height()) // 2, pm)
        p.drawPixmap(out.width() - 16, 2, pin_glyph(pin))
        p.end()
        return out

    def pin_rect(self, item):
        r = self.list.visualItemRect(item)
        if self.tabs.currentIndex() == 1:
            return QtCore.QRect(r.right() - 20, r.top(), 20, r.height())
        icon = self.list.iconSize()
        left = r.left() + (r.width() - icon.width()) // 2
        return QtCore.QRect(left + icon.width() - 18, r.top() + 2, 18, 18)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper can arrive here
        if obj is self.list.viewport() and event.type() == QtCore.QEvent.MouseButtonRelease \
                and event.button() == Qt.LeftButton:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            item = self.list.itemAt(pos)
            if item is not None and item.data(Qt.UserRole):
                if self.pin_rect(item).contains(pos):
                    toggle_pin(item.data(Qt.UserRole), self.kind())
                    self.fill()
                    return True
                self._open(item)
                return True
        return super().eventFilter(obj, event)

    def _open(self, item):
        path = item.data(Qt.UserRole)
        if not path:
            return
        folders_tab = self.tabs.currentIndex() == 1
        self.close()
        QtCore.QTimer.singleShot(0, lambda: open_in_folder(path) if folders_tab else open_document(path))


def show(pos=None, tab=0):
    panel = RecentPanel(tab)
    pos = pos or QtGui.QCursor.pos()
    screen = QtWidgets.QApplication.screenAt(pos) or QtWidgets.QApplication.primaryScreen()
    g = screen.availableGeometry()
    x = min(max(pos.x(), g.left()), g.right() - panel.width())
    y = min(max(pos.y(), g.top()), g.bottom() - panel.height())
    panel.move(x, y)
    panel.show()
    LAST[0] = panel
    return panel


# --------------------------------------------------------------------------- commands and hooks
class _FoldersCommand:
    def GetResources(self):
        return {"MenuText": "Browse Recent Folders...", "ToolTip": "The folders of the recent documents"}

    def IsActive(self):
        return True

    def Activated(self):
        show(tab=1)


def _recent_actions_pinned(original):
    """swkeys.recent_actions with the pinned documents first (File > Open Recent)."""
    def recent_actions():
        out = []
        try:
            base = original()
        except Exception:
            base = []
        by_path = {}
        for text, action in base:
            by_path[os.path.normcase(text.replace("&", ""))] = (text, action)
        holder = _HOLDER
        for p in pinned(PIN_DOCS):
            key = os.path.normcase(p)
            if key in by_path:
                out.append(by_path.pop(key))
            else:
                a = QtGui.QAction(os.path.basename(p), holder)
                a.setToolTip(p)
                a.triggered.connect(lambda checked=False, p=p: open_document(p))
                out.append((p, a))
        return out + [v for k, v in by_path.items()]
    recent_actions._fw_pinned = True
    return recent_actions


_HOLDER = None


def install():
    global _HOLDER
    try:
        if "SWStyle_BrowseRecentFolders" not in Gui.listCommands():
            Gui.addCommand("SWStyle_BrowseRecentFolders", _FoldersCommand())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Browse Recent Folders: %s\n" % error)
    try:
        from . import swkeys
        if _HOLDER is None:
            _HOLDER = QtCore.QObject(QtWidgets.QApplication.instance())
        if not getattr(swkeys.browse_recent, "_fw_recentdocs", False):
            def browse_recent(pos=None):
                return show(pos)
            browse_recent._fw_recentdocs = True
            swkeys.browse_recent = browse_recent
        if not getattr(swkeys.recent_actions, "_fw_pinned", False):
            swkeys.recent_actions = _recent_actions_pinned(swkeys.recent_actions)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: recent documents: %s\n" % error)
    return True
