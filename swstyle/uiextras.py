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

from . import events
from .widgets import alive, scaled

Qt = QtCore.Qt
PARAM = "User parameter:BaseApp/Preferences/Mod/SolidWorksStyle/Interface"
WORKSPACES = ("Default", "Widescreen", "Dual Monitor")
STATE = {"touch_bar": None, "span_geometry": None, "span_maximized": False, "tasks_filter": None,
         "ref_vis": None, "rotation_lock": None, "motion_dock": None}


def _param():
    return App.ParamGet(PARAM)


def _shell():
    try:
        from . import shell
        s = shell.shell()
    except Exception:
        return None
    return s if s is not None and getattr(s, "enabled", False) else None


def _mw():
    return Gui.getMainWindow()


# --------------------------------------------------------------------------- Workspace
def workspace():
    name = _param().GetString("Workspace", "Default")
    return name if name in WORKSPACES else "Default"


def _second_screen():
    screens = QtGui.QGuiApplication.screens()
    mw = _mw()
    own = mw.screen() if mw is not None else QtGui.QGuiApplication.primaryScreen()
    for s in screens:
        if s is not own:
            return s
    return None


def set_workspace(name):
    ""



    if name not in WORKSPACES:
        name = "Default"
    _param().SetString("Workspace", name)
    s = _shell()
    mw = _mw()
    dock = getattr(s, "left_dock", None) if s is not None else None
    if dock is None or not alive(dock) or mw is None:
        return name
    try:
        from . import leftpane
        width = scaled(getattr(leftpane, "PANE_WIDTH", 300))
    except Exception:
        width = scaled(300)
    second = _second_screen() if name == "Dual Monitor" else None
    if dock.isFloating() and second is None:
        dock.setFloating(False)
        dock.setFeatures(QtWidgets.QDockWidget.NoDockWidgetFeatures)
    if name == "Default":
        mw.resizeDocks([dock], [width], Qt.Horizontal)
        _pin_tasks(False)
    elif name == "Widescreen" or second is None:
        mw.resizeDocks([dock], [width * 2], Qt.Horizontal)
        _pin_tasks(True)
    else:
        dock.setFeatures(QtWidgets.QDockWidget.DockWidgetFloatable | QtWidgets.QDockWidget.DockWidgetMovable)
        dock.setFloating(True)
        g = second.availableGeometry()
        dock.setGeometry(g.x(), g.y(), width * 2, g.height())
        dock.show()
        _pin_tasks(True)
    return name


def _pin_tasks(on):
    """Keeps the Task Pane open (its pin) for the wide workspaces."""
    try:
        from . import taskpane
        s = _shell()
        tabs = s.overlay.tasks if s is not None and s.overlay is not None else None
        if tabs is None or not alive(tabs):
            return
        pane = taskpane.pane_of(tabs)
        if on:
            if not pane.isVisible():
                pane.show_tab(0)
            pane.pin.setChecked(True)
        else:
            pane.pin.setChecked(False)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: task pane pin: %s\n" % error)


def fill_workspace(menu):
    group = QtGui.QActionGroup(menu)
    current = workspace()
    for name in WORKSPACES:
        act = menu.addAction(name)
        act.setCheckable(True)
        act.setChecked(name == current)
        group.addAction(act)
        act.triggered.connect(lambda checked=False, n=name: set_workspace(n))
    return True


# --------------------------------------------------------------------------- Task Pane tick
class _KeepHidden(QtCore.QObject):
    """The overlay shows the Task Pane tabs again whenever the view changes; while the tick is off
    they go straight back out of sight."""

    def eventFilter(self, obj, event):
        if isinstance(event, QtCore.QEvent) and event.type() == QtCore.QEvent.Show:
            QtCore.QTimer.singleShot(0, lambda o=obj: alive(o) and o.hide())
        return False


def task_pane_shown():
    return _param().GetBool("TaskPane", True)


def _tasks_widget():
    s = _shell()
    overlay = getattr(s, "overlay", None) if s is not None else None
    tabs = getattr(overlay, "tasks", None) if overlay is not None else None
    return tabs if tabs is not None and alive(tabs) else None


def set_task_pane(on):
    _param().SetBool("TaskPane", bool(on))
    tabs = _tasks_widget()
    if tabs is None:
        return
    f = STATE["tasks_filter"]
    if on:
        if f is not None:
            tabs.removeEventFilter(f)
            STATE["tasks_filter"] = None
        tabs.show()
        if hasattr(tabs, "place"):
            tabs.place()
    else:
        if f is None:
            f = STATE["tasks_filter"] = _KeepHidden(tabs)
            tabs.installEventFilter(f)
        try:
            from . import taskpane
            pane = getattr(tabs, "_pane", None)
            if pane is not None and alive(pane) and pane.isVisible():
                pane.hide()
        except Exception as _fw_err:
            _fw_log("uiextras.py:178", _fw_err)
        tabs.hide()


# --------------------------------------------------------------------------- MotionManager tick
def _tab_row():
    """The Model / Motion Study tab row under the graphics area (the look's bottom toolbar), else None."""
    s = _shell()
    tb = getattr(s, "bottom_tb", None) if s is not None else None
    return tb if tb is not None and alive(tb) else None


def tab_row_shown():
    tb = _tab_row()
    return tb is not None and not tb.isHidden()


def set_tab_row(on):
    ""

    _param().SetBool("ModelTabsHidden", not on)
    tb = _tab_row()
    if tb is not None:
        tb.setVisible(bool(on))


def motion_manager_shown():
    if tab_row_shown():
        return True
    try:
        from . import asmmotion
        dock = asmmotion.PANE.get("dock")
        if dock is not None and alive(dock) and dock.isVisible():
            return True
    except Exception as _fw_err:
        _fw_log("uiextras.py:213", _fw_err)
    dock = STATE["motion_dock"]
    return dock is not None and alive(dock) and dock.isVisible()


def set_motion_manager(on):
    ""


    _param().SetBool("MotionManager", bool(on))
    if _tab_row() is not None:
        if on and not tab_row_shown():
            set_tab_row(True)
            _param().SetBool("MotionManager", False)
            return
        if not on:
            set_tab_row(False)
    mw = _mw()
    try:
        from . import asmmotion
        dock = asmmotion.PANE.get("dock")
    except Exception:
        asmmotion, dock = None, None
    if dock is not None and alive(dock):
        dock.setVisible(bool(on))
        if on:
            dock.raise_()
        return
    if asmmotion is not None and on:
        try:
            asm = asmmotion._assembly()
            studies = asmmotion.studies(asm) if asm is not None else []
            if asm is not None and studies:
                asmmotion.show_pane(asm, studies[0])
                return
        except Exception as error:
            App.Console.PrintLog("FreeCAD: motion study pane: %s\n" % error)
    dock = STATE["motion_dock"]
    if not on:
        if dock is not None and alive(dock):
            dock.hide()
        return
    if dock is None or not alive(dock):
        dock = QtWidgets.QDockWidget("Motion Study 1", mw)
        dock.setObjectName("FW_MotionManagerEmpty")
        box = QtWidgets.QWidget(dock)
        lay = QtWidgets.QHBoxLayout(box)
        lay.setContentsMargins(scaled(8), scaled(4), scaled(8), scaled(4))
        label = QtWidgets.QLabel("No motion study yet: Insert > New Motion Study starts one in an assembly.", box)
        lay.addWidget(label)
        button = QtWidgets.QPushButton("New Motion Study", box)

        button.clicked.connect(lambda: Gui.runCommand("SWStyle_NewMotionStudy", 0)
                               if "SWStyle_NewMotionStudy" in Gui.listCommands() else None)
        button.setEnabled("SWStyle_NewMotionStudy" in Gui.listCommands())
        lay.addWidget(button)
        lay.addStretch(1)
        dock.setWidget(box)
        mw.addDockWidget(Qt.BottomDockWidgetArea, dock)
        STATE["motion_dock"] = dock
    dock.show()
    dock.raise_()


# --------------------------------------------------------------------------- Dynamic Reference Visualization
class _ReferenceArrows(QtWidgets.QWidget):
    ""

    PARENT = QtGui.QColor(0, 102, 204)
    CHILD = QtGui.QColor(128, 0, 160)

    def __init__(self, tree):
        super().__init__(tree.viewport())
        self.tree = tree
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.item = None
        tree.viewport().installEventFilter(self)
        tree.installEventFilter(self)
        self.resize(tree.viewport().size())
        self.show()

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        if obj is self.tree.viewport():
            if t == QtCore.QEvent.Resize:
                self.resize(event.size())
            elif t in (QtCore.QEvent.MouseMove, QtCore.QEvent.HoverMove):
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                item = self.tree.itemAt(pos)
                if item is not self.item:
                    self.item = item
                    self.update()
            elif t == QtCore.QEvent.Leave:
                self.item = None
                self.update()
        return False

    def _object(self, item):
        try:
            from . import swkeys
            doc, obj = swkeys.tree_object(item) if hasattr(swkeys, "tree_object") else (None, None)
            if obj is not None:
                return obj
        except Exception as _fw_err:
            _fw_log("uiextras.py:320", _fw_err)
        try:
            text = item.text(0)
            doc = App.ActiveDocument
            if doc is None:
                return None
            for o in doc.Objects:
                if o.Label == text:
                    return o
        except Exception:
            return None
        return None

    def _rows(self, objects):
        out = []
        labels = {o.Label for o in objects}
        # a QTreeWidgetItemIterator left alive crashes FreeCAD on the tree's next clear(): release it
        # before returning, whatever happens inside
        it = QtWidgets.QTreeWidgetItemIterator(self.tree)
        try:
            while it.value():
                item = it.value()
                if item.text(0) in labels and not item.isHidden():
                    r = self.tree.visualItemRect(item)
                    if r.isValid() and r.height():
                        out.append(r)
                it += 1
        finally:
            del it
        return out

    def paintEvent(self, e):
        item = self.item
        if item is None:
            return
        obj = self._object(item)
        if obj is None:
            return
        # each kind only while it is on (drv-1120 made both off by default: Parent on alone drew children too)
        parents = list(getattr(obj, "OutList", [])) if reference_visualization("Parent") else []
        children = list(getattr(obj, "InList", [])) if reference_visualization("Child") else []
        here = self.tree.visualItemRect(item)
        if not here.isValid():
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        x = scaled(6)
        y0 = here.center().y()
        for rects, color in ((self._rows(parents), self.PARENT), (self._rows(children), self.CHILD)):
            pen = QtGui.QPen(color, scaled(2))
            p.setPen(pen)
            for r in rects:
                y1 = r.center().y()
                path = QtGui.QPainterPath(QtCore.QPointF(x + scaled(2), y0))
                path.cubicTo(x - scaled(10), y0, x - scaled(10), y1, x + scaled(2), y1)
                p.drawPath(path)
                # the arrow head at the referenced row
                head = QtGui.QPolygonF([QtCore.QPointF(x + scaled(2), y1), QtCore.QPointF(x - scaled(4), y1 - scaled(4)),
                                        QtCore.QPointF(x - scaled(4), y1 + scaled(4))])
                p.setBrush(color)
                p.drawPolygon(head)
                p.setBrush(Qt.NoBrush)
        p.end()


def reference_visualization(kind):
    return _param().GetBool("RefVis" + kind, False)


def set_reference_visualization(kind, on):
    _param().SetBool("RefVis" + kind, bool(on))
    _refresh_reference_arrows()


def _tree():
    try:
        from . import swkeys
        return swkeys.feature_tree()
    except Exception:
        return None


def _refresh_reference_arrows():
    want = reference_visualization("Parent") or reference_visualization("Child")
    arrows = STATE["ref_vis"]
    if arrows is not None and not alive(arrows):
        arrows = STATE["ref_vis"] = None
    if want and arrows is None:
        tree = _tree()
        if tree is not None and isinstance(tree, QtWidgets.QTreeWidget):
            tree.viewport().setMouseTracking(True)
            STATE["ref_vis"] = _ReferenceArrows(tree)
    elif not want and arrows is not None:
        arrows.hide()
        arrows.deleteLater()
        STATE["ref_vis"] = None
    elif arrows is not None:
        arrows.update()


# --------------------------------------------------------------------------- Touch Mode
class _RotationLock(QtCore.QObject):
    """Lock 3D Rotation on the touch bar: drags with the rotate button no longer turn the model."""

    def eventFilter(self, obj, event):
        if isinstance(event, QtCore.QEvent) and event.type() == QtCore.QEvent.MouseMove:
            buttons = event.buttons()
            if buttons & Qt.MiddleButton or (buttons & Qt.LeftButton and event.modifiers() == Qt.NoModifier):
                return True
        return False


class TouchBar(QtWidgets.QToolBar):
    ""


    NAME = "SWTouchBar"

    def __init__(self, parent):
        super().__init__("Touch Mode", parent)
        self.setObjectName(self.NAME)
        self.setOrientation(Qt.Vertical)
        self.setMovable(False)
        self.setIconSize(QtCore.QSize(scaled(28), scaled(28)))
        self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.setStyleSheet("QToolButton { min-width: %dpx; min-height: %dpx; font-size: %dpt; }"
                           % (scaled(44), scaled(44), 10))
        self.escape = self._button("Esc", "Escape: ends the tool", lambda: self._key(Qt.Key_Escape))
        self.shift = self._button("Shift", "Shift held while on", None, latch=Qt.ShiftModifier)
        self.ctrl = self._button("Ctrl", "Ctrl held while on", None, latch=Qt.ControlModifier)
        self.delete = self._button("Del", "Delete", lambda: self._key(Qt.Key_Delete))
        self.multi = self._button("Multi", "Multi-select mode: taps add to the selection", None, latch=Qt.ControlModifier)
        self.undo = self._button("Undo", "Undo (Ctrl+Z)", lambda: Gui.runCommand("Std_Undo", 0))
        self.lock = self._button("Lock", "Lock 3D Rotation", None, checkable=True)
        self.lock.toggled.connect(self._lock)
        self.latched = set()
        self._filter = _Latch(self)
        from . import events
        events.register("uiextras.latch", (QtCore.QEvent.MouseButtonPress,), self._filter.eventFilter)

    def _button(self, text, tip, run, latch=None, checkable=False):
        act = self.addAction(text)
        act.setToolTip(tip)
        if run is not None:
            act.triggered.connect(lambda checked=False: run())
        if latch is not None or checkable:
            act.setCheckable(True)
        if latch is not None:
            act.latch = latch
            act.toggled.connect(lambda on, a=act: self._latched(a, on))
        return act

    def _latched(self, act, on):
        if on:
            self.latched.add(act.latch)
        else:
            self.latched.discard(act.latch)

    def modifiers(self):
        m = Qt.NoModifier
        for latch in self.latched:
            m |= latch
        return m

    def _key(self, key):
        mw = Gui.getMainWindow()
        target = QtWidgets.QApplication.focusWidget() or mw
        for kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.postEvent(target, QtGui.QKeyEvent(kind, key, Qt.NoModifier))

    def _lock(self, on):
        s = _shell()
        view = s._view() if s is not None and hasattr(s, "_view") else None
        widget = None
        try:
            widget = view.getViewer().getWidget() if view is not None else None
        except Exception:
            widget = None
        old = STATE["rotation_lock"]
        if old is not None:
            events.unregister("uiextras.rotationlock")
            STATE["rotation_lock"] = None
        if on:
            f = _RotationLock(self)
            events.register("uiextras.rotationlock", (QtCore.QEvent.MouseButtonPress,), f.eventFilter)
            STATE["rotation_lock"] = (f, widget)


class _Latch(QtCore.QObject):
    """Adds the latched Shift/Ctrl to mouse presses in the 3D view (and keyboard-less taps)."""

    def __init__(self, bar):
        super().__init__(bar)
        self.bar = bar

    def eventFilter(self, obj, event):
        bar = self.bar
        if not alive(bar) or not bar.latched or not isinstance(event, QtCore.QEvent):
            return False
        if event.type() == QtCore.QEvent.MouseButtonPress and isinstance(obj, QtWidgets.QWidget) \
                and "QuarterWidget" in obj.metaObject().className() and not getattr(event, "_relatched", False):
            try:
                copy = QtGui.QMouseEvent(event.type(), event.position(), event.globalPosition(), event.button(),
                                         event.buttons(), event.modifiers() | bar.modifiers())
                copy._relatched = True
                QtWidgets.QApplication.postEvent(obj, copy)
                return True
            except Exception:
                return False
        return False


def touch_mode():
    return _param().GetBool("TouchMode", False)


def set_touch_mode(on):
    _param().SetBool("TouchMode", bool(on))
    mw = _mw()
    bar = STATE["touch_bar"]
    if bar is not None and not alive(bar):
        bar = STATE["touch_bar"] = None
    if on:
        if bar is None:
            bar = TouchBar(mw)
            mw.addToolBar(Qt.RightToolBarArea, bar)
            STATE["touch_bar"] = bar
        bar.show()
    elif bar is not None:
        bar.hide()
        if bar.lock.isChecked():
            bar.lock.setChecked(False)


# --------------------------------------------------------------------------- Span Displays
def can_span():
    return len(QtGui.QGuiApplication.screens()) > 1


def spanning():
    return STATE["span_geometry"] is not None


def set_span_displays(on):
    ""

    mw = _mw()
    if mw is None:
        return
    if on and not spanning():
        STATE["span_maximized"] = mw.isMaximized()
        STATE["span_geometry"] = mw.geometry()
        rect = QtCore.QRect()
        for s in QtGui.QGuiApplication.screens():
            rect = rect.united(s.availableGeometry())
        mw.showNormal()
        mw.setGeometry(rect)
    elif not on and spanning():
        geometry, maximized = STATE["span_geometry"], STATE["span_maximized"]
        STATE["span_geometry"] = None
        mw.setGeometry(geometry)
        if maximized:
            mw.showMaximized()


def add_span_action(menu):
    act = menu.addAction("Span Displays")
    act.setCheckable(True)
    act.setChecked(spanning())
    act.setEnabled(can_span() or spanning())
    act.triggered.connect(lambda checked=False: set_span_displays(not spanning()))
    return act


# --------------------------------------------------------------------------- the User Interface submenu
def fill_user_interface(menu, shell, drawing=False):
    ""


    from . import swmenus
    for name, label in (("SWStyle_FeatureManagerArea", "FeatureManager Tree Area"),):
        item = swmenus._command_item(name, label)
        if item is not None:
            swmenus._add_item(menu, item)
    for kind in (() if drawing else ("Parent", "Child")):
        act = menu.addAction("Dynamic Reference Visualization (%s)" % kind)
        act.setCheckable(True)
        act.setChecked(reference_visualization(kind))
        act.triggered.connect(lambda checked=False, k=kind: set_reference_visualization(k, not reference_visualization(k)))
    item = swmenus._command_item("SWStyle_ToggleCommandManager", "Toolbars")
    if item is not None:
        from . import swtoolbars
        item.checked = swtoolbars.command_manager_enabled(shell)
        swmenus._add_item(menu, item)
    act = menu.addAction("Task Pane")
    act.setCheckable(True)
    act.setChecked(task_pane_shown() and _tasks_widget() is not None)
    act.setEnabled(_tasks_widget() is not None)
    act.triggered.connect(lambda checked=False: set_task_pane(not task_pane_shown()))
    act = menu.addAction("MotionManager")
    act.setCheckable(True)
    act.setChecked(motion_manager_shown())
    act.triggered.connect(lambda checked=False: set_motion_manager(not motion_manager_shown()))
    item = swmenus._command_item("Std_ViewStatusBar", "Status Bar")
    if item is not None:
        swmenus._add_item(menu, item)
    if drawing:
        for name, label in (("FreeWorks_DrawRulers", "Rulers"), ("FreeWorks_DrawZoneLines", "Zone Lines")):
            item = swmenus._command_item(name, label)
            if item is not None:
                swmenus._add_item(menu, item)
    from . import notifarea
    swmenus._add_item(menu, notifarea.item())       # extapps95: FreeCAD's notification counter, off by default
    return True


def touch_mode_item(label):
    from . import swmenus
    return swmenus.Item(label, True, lambda: set_touch_mode(not touch_mode()), None, "", touch_mode())


# --------------------------------------------------------------------------- start / stop
def install():
    ""

    try:
        s = _shell()
        if s is not None:
            from . import swtoolbars
            swtoolbars.restore(s)
        if workspace() != "Default":
            set_workspace(workspace())
        if not task_pane_shown():
            set_task_pane(False)
        from . import notifarea
        notifarea.install()
        if touch_mode():
            set_touch_mode(True)
        if _param().GetBool("MotionManager", False):
            set_motion_manager(True)
        if _param().GetBool("ModelTabsHidden", False):
            QtCore.QTimer.singleShot(0, lambda: set_tab_row(False))
        _refresh_reference_arrows()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: interface extras not restored: %s\n" % error)


def remove():
    for key in ("touch_bar", "motion_dock"):
        w = STATE[key]
        if w is not None and alive(w):
            w.hide()
            w.deleteLater()
        STATE[key] = None
    arrows = STATE["ref_vis"]
    if arrows is not None and alive(arrows):
        arrows.deleteLater()
    STATE["ref_vis"] = None
    lock = STATE["rotation_lock"]
    if lock is not None:
        events.unregister("uiextras.rotationlock")
        STATE["rotation_lock"] = None
    if spanning():
        set_span_displays(False)
    try:
        from . import swtoolbars
        swtoolbars.remove()
    except Exception as _fw_err:
        _fw_log("uiextras.py:683", _fw_err)
