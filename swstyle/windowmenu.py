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

from . import paths

PARAM = "WindowMenu"
NAME = "SWWindowMenu"
TICK = 1000
FOUR = ("viewFront", "viewTop", "viewRight", "viewIsometric")

_watch = None


def enabled():
    return paths.params().GetBool(PARAM, True)


def mdi():
    mw = Gui.getMainWindow()
    return mw.findChild(QtWidgets.QMdiArea) if mw is not None else None


def _windows():
    area = mdi()
    return list(area.subWindowList()) if area is not None else []


def _split_class(sub):
    try:
        return sub.widget().metaObject().className() == "Gui::AbstractSplitView"
    except Exception as _fw_err:
        _fw_log("windowmenu.py:61", _fw_err)
        return False


_VIEWPORT = []          # the 3D views of the last Two / Four View, for Link Views
EXTRA = "swViewportExtra"       # property on the sub-windows Two/Four View added
_was_tabbed = []


def _extra_windows(area):
    return [s for s in area.subWindowList() if s.property(EXTRA)]


def _sub_of_view(area, view):
    """The MDI sub-window holding a Gui view."""
    try:
        w = view.graphicsView() if hasattr(view, "graphicsView") else None
    except Exception:
        w = None
    for sub in area.subWindowList():
        try:
            if w is not None and (sub.widget() is w or sub.widget().isAncestorOf(w)):
                return sub
        except Exception as _fw_err:
            _fw_log("windowmenu.py:85", _fw_err)
            continue
    return area.activeSubWindow()


def _new_view(area):
    """Another 3D window of the active document, as Window > New Window."""
    before = set(area.subWindowList())
    gdoc = Gui.ActiveDocument
    _run("Std_ViewCreate")
    new = [s for s in area.subWindowList() if s not in before]
    sub = new[0] if new else None
    view = gdoc.ActiveView if gdoc is not None else None
    if sub is None and view is not None:
        sub = _sub_of_view(area, view)
    if sub is not None:
        sub.setProperty(EXTRA, True)
    return sub, view


def _room(area):
    """darktitle-1121: the part of the work area a restored window may use: below the CommandManager tabs,
    which sit over the work area's top on the strip, so every title bar stays visible."""
    rect = area.viewport().rect()
    try:
        from . import docbuttons
        top = docbuttons._under_tabs(area)
    except Exception:
        top = 0
    if 0 < top < rect.height() // 2:
        rect.setTop(rect.top() + top)
    return rect


def _layout(area, subs, kind):
    rect = _room(area)                      # darktitle-1121
    n = len(subs)
    for i, sub in enumerate(subs):
        sub.showNormal()
        if kind == "four":
            w, h = rect.width() // 2, rect.height() // 2
            sub.setGeometry(rect.x() + (i % 2) * w, rect.y() + (i // 2) * h, w, h)
        elif kind == "two-h":
            h = rect.height() // n
            sub.setGeometry(rect.x(), rect.y() + i * h, rect.width(), h)
        else:
            w = rect.width() // n
            sub.setGeometry(rect.x() + i * w, rect.y(), w, rect.height())


def viewport(kind):
    """'single', 'two-h' (one above the other), 'two-v' (side by side) or 'four'."""
    area = mdi()
    if Gui.ActiveDocument is None or area is None:
        return None
    active = area.activeSubWindow()
    if kind == "single":
        if active is not None and _split_class(active):
            active.close()
        for sub in _extra_windows(area):
            sub.close()
        LINK.stop()
        _VIEWPORT[:] = []
        if _was_tabbed and _was_tabbed.pop():
            area.setViewMode(QtWidgets.QMdiArea.TabbedView)
        keep = area.activeSubWindow()
        if keep is not None:
            keep.showMaximized()
        return None
    for sub in _extra_windows(area):
        sub.close()                 # Two then Four: start again from the one window
    if not _was_tabbed:
        _was_tabbed.append(area.viewMode() == QtWidgets.QMdiArea.TabbedView)
    _as_windows(area)
    gdoc = Gui.ActiveDocument
    base_view = gdoc.ActiveView
    base = _sub_of_view(area, base_view) or active
    subs, views = [base], [base_view]
    for _ in range(3 if kind == "four" else 1):
        sub, view = _new_view(area)
        if sub is None:
            break
        subs.append(sub)
        views.append(view)
    _layout(area, subs, kind)
    LINK.stop()
    _VIEWPORT[:] = views
    if kind == "four":
        turns = FOUR
        try:
            from . import optionsextras3      # Options > Display > Projection type for four view viewport
            turns = optionsextras3.four_turns()
        except Exception as _fw_err:
            _fw_log("windowmenu.py:161", _fw_err)
        for view, turn in zip(views, turns):
            try:
                getattr(view, turn)()
            except Exception as _fw_err:
                _fw_log("windowmenu.py:166", _fw_err)
    for view in views:
        _fit_later(view)
    try:
        area.setActiveSubWindow(base)
    except Exception as _fw_err:
        _fw_log("windowmenu.py:172", _fw_err)
    return views[-1]


def _fit_later(view):
    def fit():
        try:
            from .cleanopen import view_alive      # rcmenus pkg270: the view may be gone or hidden by now
            if not view_alive(view):
                return
            view.fitAll()
        except Exception as _fw_err:
            _fw_log("windowmenu.py:181", _fw_err)
    QtCore.QTimer.singleShot(0, fit)


def _as_windows(area):
    if area.viewMode() != QtWidgets.QMdiArea.SubWindowView:
        area.setViewMode(QtWidgets.QMdiArea.SubWindowView)


def _shown(area):
    return [s for s in area.subWindowList() if s.isVisible() and not s.isMinimized()]


def cascade():
    ""

    # winmenu-1119
    area = mdi()
    if area is None:
        return
    _as_windows(area)
    subs = _shown(area)
    if not subs:
        return
    active = area.activeSubWindow()
    if active in subs:                      # the active window last, so it ends in front
        subs.remove(active)
        subs.append(active)
    rect = _room(area)                      # darktitle-1121
    try:
        step = subs[0].style().pixelMetric(QtWidgets.QStyle.PM_TitleBarHeight, None, subs[0]) + 4
    except Exception:
        step = 26
    step = max(18, step)
    n = len(subs)
    w = max(rect.width() * 2 // 3, rect.width() - step * (n - 1))
    h = max(rect.height() * 2 // 3, rect.height() - step * (n - 1))
    room_x = max(0, rect.width() - w)
    room_y = max(0, rect.height() - h)
    for i, sub in enumerate(subs):
        sub.showNormal()
        x = min(i * step, room_x) if room_x else 0
        y = min(i * step, room_y) if room_y else 0
        sub.setGeometry(rect.x() + x, rect.y() + y, w, h)
        sub.raise_()
    if active is not None:
        area.setActiveSubWindow(active)


ACROSS = "TileAcrossMonitors"


def _screens():
    """The usable area of every monitor, the one holding the main window first."""
    mwin = Gui.getMainWindow()
    screens = list(QtGui.QGuiApplication.screens())
    own = mwin.screen() if mwin is not None and hasattr(mwin, "screen") else None
    if own is None:
        own = QtGui.QGuiApplication.primaryScreen()
    screens.sort(key=lambda s: (s != own, s.geometry().x(), s.geometry().y()))
    return [s.availableGeometry() for s in screens]


def _floating():
    """Document windows that float outside the main window (Window > Undock, or an earlier tile
    over the other monitors)."""
    seen, out = set(), []
    mwin = Gui.getMainWindow()
    pool = list(QtWidgets.QApplication.topLevelWidgets())
    if mwin is not None:
        pool += mwin.findChildren(QtWidgets.QWidget)
    for w in pool:
        try:
            if w.inherits("Gui::MDIView") and w.isWindow() and w.isVisible() and id(w) not in seen:
                seen.add(id(w))
                out.append(w)
        except RuntimeError:
            continue
    return out


def _view_mode(mode):
    """0 dock, 1 undock (Std_ViewDockUndockFullscreen) for the active document window."""
    try:
        Gui.runCommand("Std_ViewDockUndockFullscreen", mode)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: window could not be (un)docked: %s\n" % error)


def _key(w):
    try:
        try:
            import shiboken6 as shiboken
        except ImportError:
            import shiboken2 as shiboken
        return shiboken.getCppPointer(w)[0]
    except Exception:
        return w.windowTitle()


def _undock(area, sub):
    """Float one document window; the floating window found again afresh, as the old Python
    handle goes with the sub-window."""
    before = set(_key(w) for w in _floating())
    mwin = Gui.getMainWindow()
    mwin.activateWindow()           # a floating window may hold the activation
    area.setActiveSubWindow(sub)
    if sub.widget() is not None:
        sub.widget().setFocus()
    QtWidgets.QApplication.processEvents()
    if area.activeSubWindow() is not sub:
        return None
    _view_mode(1)
    QtWidgets.QApplication.processEvents()
    new = [w for w in _floating() if _key(w) not in before]
    return new[0] if new else None


def _dock(area, view):
    """Bring a floating window back into the main window; its new sub-window, or None."""
    before = set(_key(s) for s in area.subWindowList())
    view.activateWindow()
    view.setFocus()
    QtWidgets.QApplication.processEvents()
    if not view.isActiveWindow():
        return None
    _view_mode(0)
    QtWidgets.QApplication.processEvents()
    new = [s for s in area.subWindowList() if _key(s) not in before]
    return new[0] if new else None


def _cells(rect, n, horizontally):
    out = []
    for i in range(n):
        if horizontally:
            h = rect.height() // n
            out.append(QtCore.QRect(rect.x(), rect.y() + i * h, rect.width(), h))
        else:
            w = rect.width() // n
            out.append(QtCore.QRect(rect.x() + i * w, rect.y(), w, rect.height()))
    return out


def _chunks(items, k):
    """items split into k runs in order, the first runs one longer when they do not divide."""
    k = max(1, min(k, len(items)))
    size, extra = divmod(len(items), k)
    out, at = [], 0
    for i in range(k):
        n = size + (1 if i < extra else 0)
        out.append(items[at:at + n])
        at += n
    return out


def _tile_in_area(area, subs, horizontally):
    rect = _room(area)                      # darktitle-1121
    for sub, cell in zip(subs, _cells(rect, len(subs), horizontally)):
        sub.showNormal()
        sub.setGeometry(cell)


def tile(horizontally):
    ""



    area = mdi()
    if area is None:
        return
    _as_windows(area)
    subs = _shown(area)
    floating = _floating()
    screens = _screens() if paths.params().GetBool(ACROSS, True) else []
    if len(screens) < 2:
        if subs:
            _tile_in_area(area, subs, horizontally)
        return
    windows = subs + floating
    if not windows:
        return
    groups = _chunks(windows, len(screens))
    home = []
    for w in groups[0]:
        if isinstance(w, QtWidgets.QMdiSubWindow):
            home.append(w)
        else:                       # a floating window whose share is the main window comes back
            sub = _dock(area, w)
            if sub is not None:
                home.append(sub)
    if home:
        _tile_in_area(area, home, horizontally)
    for rect, group in zip(screens[1:], groups[1:]):
        tops = []
        for w in group:
            top = _undock(area, w) if isinstance(w, QtWidgets.QMdiSubWindow) else w
            if top is not None:
                tops.append(top)
        for top, cell in zip(tops, _cells(rect, len(tops), horizontally)):
            _place(top, cell)


def _place(top, cell):
    """Size a floating window; again a moment later, as undocking puts the window back where it
    last floated once the event loop runs."""
    def put():
        try:
            if top.isWindow():
                top.showNormal()
                top.setGeometry(cell)
        except RuntimeError as _fw_err:
            _fw_log("windowmenu.py:364", _fw_err)
    put()
    for ms in (50, 300):
        QtCore.QTimer.singleShot(ms, put)


def arrange_icons():
    area = mdi()
    if area is None:
        return
    _as_windows(area)
    x = 0
    for sub in area.subWindowList():
        if sub.isMinimized():
            sub.move(x, area.viewport().height() - sub.height())
            x += sub.width()


def document_of(sub):
    """The App document shown in an MDI sub-window, or None (a start page, a browser)."""
    try:
        w = sub.widget()
        title = (w.windowTitle() if w is not None else sub.windowTitle()) or ""
    except Exception:
        return None
    head = title.replace("[*]", "").split(" : ")[0].strip()
    for doc in App.listDocuments().values():
        if doc.Label == head or doc.Name == head:
            return doc
    return None


def window_name(sub, subs=None):
    ""

    title = sub.windowTitle().replace("[*]", "").strip()
    doc = document_of(sub)
    if doc is None:
        return title.replace(" : 1", "")
    import os
    name = os.path.basename(doc.FileName) if doc.FileName else doc.Label
    subs = subs if subs is not None else _windows()
    same = [s for s in subs if document_of(s) is doc]
    if len(same) > 1:
        name += ":%d" % (same.index(sub) + 1)
    try:
        if Gui.getDocument(doc.Name).Modified:
            name += " *"
    except Exception as _fw_err:
        _fw_log("windowmenu.py:name", _fw_err)
    return name


def _run(command):
    try:
        Gui.runCommand(command, 0)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s did not run: %s\n" % (command, error))


def fill(menu):
    for old in menu.findChildren(QtWidgets.QMenu):
        old.deleteLater()           # last time's Viewport submenu
    menu.clear()
    has_doc = Gui.ActiveDocument is not None
    try:
        from . import uiextras
        span = uiextras.add_span_action(menu)
        if span is not None and not span.isEnabled():
            menu.removeAction(span)                 # one monitor: nothing to span, so not shown
        else:
            menu.addSeparator()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Span Displays not added: %s\n" % error)
    ports = QtWidgets.QMenu("Viewport", menu)    # parented, so Python does not delete it
    try:
        from . import swmenus
        on_sheet = swmenus.drawing_in_front()
    except Exception:
        on_sheet = False
    if not on_sheet and has_doc:
        menu.addMenu(ports)
    for text, kind in (("Single View", "single"), ("Two View - Horizontal", "two-h"),
                       ("Two View - Vertical", "two-v"), ("Four View", "four")):
        act = ports.addAction(text)
        act.setEnabled(has_doc)
        act.triggered.connect(lambda checked=False, k=kind: viewport(k))
    if LINK.on or _split_viewers() is not None:     # only with two or four views to link
        act = ports.addAction("Link Views")
        act.setCheckable(True)
        act.setChecked(LINK.on)
        act.triggered.connect(lambda checked=False: LINK.toggle())
    if has_doc:
        act = menu.addAction("New Window")
        act.triggered.connect(lambda: _run("Std_ViewCreate"))
    subs = _windows()
    for text, slot in (("Cascade", cascade), ("Tile Horizontally", lambda: tile(True)),
                       ("Tile Vertically", lambda: tile(False)), ("Arrange Icons", arrange_icons)):
        if not subs:
            continue
        act = menu.addAction(text)
        act.triggered.connect(slot)
    if subs:
        act = menu.addAction("Close All")
        act.triggered.connect(_close_all)
    if App.listDocuments():
        act = menu.addAction("Browse Open Documents...")
        act.setShortcut(QtGui.QKeySequence("Ctrl+Tab"))      # shown only; the key is the command's (keys.py)
        act.setShortcutContext(QtCore.Qt.WidgetShortcut)
        act.triggered.connect(browse_open_documents)
    try:
        from . import swmenus
        for a in menu.actions():
            pic = None if a.isSeparator() or not a.icon().isNull() else swmenus._menu_icon(a.text())
            if pic is not None:
                a.setIcon(pic)
    except Exception as _fw_err:
        App.Console.PrintLog("FreeWorks: Window menu pictures: %s\n" % _fw_err)
    if subs:
        menu.addSeparator()
        area = mdi()
        current = area.activeSubWindow() if area is not None else None
        for i, sub in enumerate(subs):
            title = window_name(sub, subs)
            act = menu.addAction("&%d %s" % (i + 1, title.replace("&", "&&")))
            act.setCheckable(True)
            act.setChecked(sub is current)
            act.setStatusTip("Makes this window the active one.")       # pkg231: its status bar line
            act.triggered.connect(lambda checked=False, s=sub: mdi() and mdi().setActiveSubWindow(s))
    try:
        from . import rcaccel
        rcaccel.decorate_bar(menu)
    except Exception as _fw_err:
        App.Console.PrintLog("FreeCAD: Window menu letters: %s\n" % _fw_err)


# ------------------------------------------------------------------ Link Views
def _split_viewers(sub=None):
    """The viewers of the active document's viewport windows (Two / Four View), or None."""
    views = [v for v in _VIEWPORT if _alive_view(v)]
    _VIEWPORT[:] = views
    if len(views) < 2:
        return None
    try:
        doc = Gui.ActiveDocument
        if doc is None or any(v.getViewer() is None for v in views):
            return None
        return [v.getViewer() for v in views]
    except Exception:
        return None


def _alive_view(view):
    try:
        view.getCameraNode()
        return True
    except Exception:
        return False


def _safe_viewer(view, i):
    try:
        return view.getViewer(i)
    except Exception:
        return None


def _camera_state(cam):
    return (tuple(cam.orientation.getValue().getValue()), tuple(cam.position.getValue().getValue()),
            cam.focalDistance.getValue(),
            cam.height.getValue() if hasattr(cam, "height") else cam.heightAngle.getValue())


class _Link:
    ""


    def __init__(self):
        self.timer = None
        self.viewers = []
        self.last = []

    @property
    def on(self):
        return self.timer is not None

    def toggle(self):
        if self.on:
            self.stop()
        else:
            self.start()

    def start(self, viewers=None):
        viewers = viewers or _split_viewers()
        if not viewers:
            return False
        self.viewers = viewers
        self.last = [self._state(v) for v in viewers]
        self.timer = QtCore.QTimer()
        self.timer.setInterval(60)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        return True

    def stop(self):
        if self.timer is not None:
            self.timer.stop()
        self.timer = None
        self.viewers = []

    def _state(self, viewer):
        try:
            return _camera_state(viewer.getSoRenderManager().getCamera())
        except Exception:
            return None

    def tick(self):
        try:
            states = [self._state(v) for v in self.viewers]
        except Exception:
            self.stop()
            return
        if any(s is None for s in states):
            self.stop()
            return
        moved = [i for i, (a, b) in enumerate(zip(states, self.last)) if a != b]
        if moved:
            self.follow(moved[0], states)
        self.last = [self._state(v) for v in self.viewers]

    def follow(self, i, states):
        """The others take viewer i's zoom and pan; they keep their own direction."""
        from pivy import coin
        src = self.viewers[i].getSoRenderManager().getCamera()
        old = self.last[i]
        shift = None
        if old is not None and len(self.viewers) > 2:
            # the point viewer i looks at moved: the model moves the same way in the others (on a

            def aim(q, p, f):
                d = q.multVec(coin.SbVec3f(0, 0, -1))
                return [p[n] + d[n] * f for n in range(3)]
            a = aim(coin.SbRotation(*old[0]), old[1], old[2])
            b = aim(src.orientation.getValue(), src.position.getValue().getValue(), src.focalDistance.getValue())
            shift = [b[n] - a[n] for n in range(3)]
        for k, v in enumerate(self.viewers):
            if k == i:
                continue
            cam = v.getSoRenderManager().getCamera()
            if hasattr(cam, "height") and hasattr(src, "height") and old is not None and old[3]:
                cam.height.setValue(cam.height.getValue() * src.height.getValue() / old[3])
            if shift is not None and max(abs(x) for x in shift) > 1e-9:
                p = cam.position.getValue()
                cam.position.setValue(p[0] + shift[0], p[1] + shift[1], p[2] + shift[2])
            if old is not None:
                dq = coin.SbRotation(*old[0]).inverse() * src.orientation.getValue()
                if len(self.viewers) <= 2:
                    # two views look the same way: they turn together too
                    cam.orientation.setValue(cam.orientation.getValue() * dq)
                    cam.position.setValue(src.position.getValue())
                    cam.focalDistance.setValue(src.focalDistance.getValue())


LINK = _Link()


# ------------------------------------------------------------------ Browse Open Documents
THUMB = QtCore.QSize(160, 120)


def _thumbnail(doc):
    """A picture of the document's 3D view (rendered off screen at the screen's scale), or the drawn
    document icon when there is no 3D view."""
    try:
        ratio = max(1.0, QtWidgets.QApplication.primaryScreen().devicePixelRatio())
    except Exception:
        ratio = 1.0
    try:
        gdoc = Gui.getDocument(doc.Name)
        views = gdoc.mdiViewsOfType("Gui::View3DInventor") if gdoc is not None else []
        if views:
            import tempfile, os
            path = os.path.join(tempfile.gettempdir(), "fw_browse_thumb_%d.png" % os.getpid())    # one file per session, written over (pkg321)
            views[0].saveImage(path, int(THUMB.width() * ratio), int(THUMB.height() * ratio), "Current")
            pix = QtGui.QPixmap(path)
            if not pix.isNull():
                pix.setDevicePixelRatio(ratio)
                return pix
    except Exception as _fw_err:
        _fw_log("windowmenu.py:thumb", _fw_err)
    pix = QtGui.QPixmap(int(THUMB.width() * ratio), int(THUMB.height() * ratio))
    pix.setDevicePixelRatio(ratio)
    pix.fill(QtGui.QColor("#ffffff"))
    p = QtGui.QPainter(pix)
    QtGui.QIcon(":/icons/Document.svg").paint(p, QtCore.QRect(THUMB.width() // 2 - 24, THUMB.height() // 2 - 24, 48, 48))
    p.end()
    return pix


class BrowseDocuments(QtWidgets.QDialog):
    ""



    # winmenu-1119

    def __init__(self, from_key=None):
        super().__init__(Gui.getMainWindow(), QtCore.Qt.Dialog | QtCore.Qt.FramelessWindowHint)
        self.setWindowTitle("Browse Open Documents")
        self.setObjectName("SWBrowseOpenDocuments")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 10)
        head = QtWidgets.QLabel("Browse Open Documents")
        head.setObjectName("SWBrowseOpenTitle")
        f = head.font()
        f.setBold(True)
        head.setFont(f)
        lay.addWidget(head)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWBrowseOpenList")
        self.list.setViewMode(QtWidgets.QListView.IconMode)
        self.list.setIconSize(THUMB)
        self.list.setGridSize(QtCore.QSize(THUMB.width() + 24, THUMB.height() + 40))
        self.list.setMovement(QtWidgets.QListView.Static)
        self.list.setResizeMode(QtWidgets.QListView.Adjust)
        self.list.setWrapping(True)
        self.list.setUniformItemSizes(True)
        self.list.setWordWrap(True)
        self.list.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.list.setFocusPolicy(QtCore.Qt.NoFocus)          # the box keeps the keys (Tab, Ctrl)
        self.setStyleSheet("QDialog#SWBrowseOpenDocuments { border: 1px solid palette(mid); }")
        import os
        docs = list(App.listDocuments().values())
        for doc in docs:
            name = os.path.basename(doc.FileName) if doc.FileName else doc.Label
            try:
                if Gui.getDocument(doc.Name).Modified:
                    name += " *"
            except Exception as _fw_err:
                _fw_log("windowmenu.py:browse", _fw_err)
            item = QtWidgets.QListWidgetItem(QtGui.QIcon(_thumbnail(doc)), name)
            item.setToolTip(doc.FileName or "(not saved)")
            item.setData(QtCore.Qt.UserRole, doc.Name)
            self.list.addItem(item)
            if App.ActiveDocument is doc:
                self.list.setCurrentItem(item)
        if from_key is None:
            from_key = bool(QtWidgets.QApplication.queryKeyboardModifiers() & QtCore.Qt.ControlModifier)
        self.from_key = from_key
        if from_key and self.list.count() > 1:           # Ctrl+Tab: the next document is picked first
            self.list.setCurrentRow((self.list.currentRow() + 1) % self.list.count())
        self.list.itemClicked.connect(lambda _i: self.accept())
        self.list.itemActivated.connect(lambda _i: self.accept())
        lay.addWidget(self.list, 1)
        cols = max(1, min(len(docs), 5))
        rows = (len(docs) + cols - 1) // cols
        grid = self.list.gridSize()
        bar = self.list.style().pixelMetric(QtWidgets.QStyle.PM_ScrollBarExtent) if rows > 3 else 0
        self.list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        if not bar:
            self.list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.list.setFixedSize(cols * grid.width() + 2 * self.list.frameWidth() + bar + 8,
                               min(3, rows) * grid.height() + 2 * self.list.frameWidth() + 8)
        self.adjustSize()
        mw = Gui.getMainWindow()
        if mw is not None:
            self.move(mw.geometry().center() - self.rect().center())

    def step(self, by):
        n = self.list.count()
        if n:
            self.list.setCurrentRow((self.list.currentRow() + by) % n)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab):
            self.step(-1 if key == QtCore.Qt.Key_Backtab or event.modifiers() & QtCore.Qt.ShiftModifier else 1)
            return
        if key in (QtCore.Qt.Key_Right, QtCore.Qt.Key_Down):
            self.step(1)
            return
        if key in (QtCore.Qt.Key_Left, QtCore.Qt.Key_Up):
            self.step(-1)
            return
        if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == QtCore.Qt.Key_Control and self.from_key:
            self.accept()
            return
        super().keyReleaseEvent(event)

    def accept(self):
        item = self.list.currentItem()
        if item is not None:
            show_document(item.data(QtCore.Qt.UserRole))
        super().accept()


def show_document(name):
    gdoc = Gui.getDocument(name) if name in App.listDocuments() else None
    if gdoc is None:
        return
    area = mdi()
    for sub in _windows():
        try:
            if sub.windowTitle().startswith(App.getDocument(name).Label + " :"):
                area.setActiveSubWindow(sub)
                break
        except Exception as _fw_err:
            _fw_log("windowmenu.py:622", _fw_err)
    try:
        Gui.ActiveDocument = gdoc
        App.setActiveDocument(name)
    except Exception as _fw_err:
        _fw_log("windowmenu.py:627", _fw_err)


def browse_open_documents(from_key=None):
    box = BrowseDocuments(from_key)
    box.exec_()
    return box


class BrowseOpenDocumentsCommand:
    ""

    def GetResources(self):
        return {"MenuText": "Browse Open Documents...", "ToolTip": "Picks one of the open documents (Ctrl+Tab)",
                "Accel": "Ctrl+Tab", "CmdType": "ForEdit"}

    def IsActive(self):
        return bool(App.listDocuments())

    def Activated(self):
        browse_open_documents(True)


COMMAND = "SWStyle_BrowseOpenDocuments"


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, BrowseOpenDocumentsCommand())


def _ours(bar):
    for action in bar.actions():
        menu = action.menu()
        if menu is not None and menu.objectName() == NAME:
            return action
    return None


def _hook():
    try:
        mw = Gui.getMainWindow()
        bar = mw.menuBar()
        native = [a for a in bar.actions() if a.menu() is not None and a.menu().objectName() == "&Windows"]
        mine = _ours(bar)
        if not enabled():
            if mine is not None:
                bar.removeAction(mine)
            for a in native:
                a.setVisible(True)
            return
        if not native:
            return
        for a in native:
            a.setVisible(False)
        if mine is None:
            menu = None
            try:
                from . import swmenus       # the one a workbench change took out of the bar goes back in
                menu = swmenus._left_out(bar, NAME)
            except Exception as _fw_err:
                _fw_log("windowmenu.py:spare", _fw_err)
            if menu is None:
                menu = QtWidgets.QMenu("&Window", bar)
                menu.setObjectName(NAME)
                menu.aboutToShow.connect(lambda m=menu: fill(m))
            bar.insertMenu(native[0], menu)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Window menu not added: %s\n" % error)


def _close_all():
    try:
        from . import closeprompt
        closeprompt.close_all()
    except Exception:
        _run("Std_CloseAllWindows")


def install():
    global _watch
    if _watch is not None:
        return
    _watch = QtCore.QTimer()
    _watch.setInterval(TICK)
    _watch.timeout.connect(_hook)
    _watch.start()
    try:
        register()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Browse Open Documents command: %s\n" % error)
    _hook()


def remove():
    global _watch
    if _watch is not None:
        _watch.stop()
    _watch = None
