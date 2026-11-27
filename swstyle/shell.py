# SPDX-License-Identifier: LGPL-2.1-or-later
""







from . import editobj

_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import (breadcrumbs, catalog, chrome, cleanopen, cmdlocate, contextbar, facehover, flyouttree, fmtree, freezeview, gestures, icons, keys, leftpane, massprops,
               orientation, paths, pencil, planes, relationspm, ribbon, rollbackbar, sketchexit, sketchorigin, sketchstatus,
               style, viewkeys, viewselector)
from .widgets import Binding, alive, popup_menu, scaled, ui_font
from .widgets import FLYOUT_LAST   # cmtabs-1120

Qt = QtCore.Qt
NATIVE_COVERED = ("PartDesignWorkbench", "SketcherWorkbench", "NoneWorkbench", "StartWorkbench")


def _class(widget):
    try:
        return widget.metaObject().className()
    except Exception as _fw_err:
        _fw_log("shell.py:42", _fw_err)
        return ""


def _propertymanager():
    """The PropertyManager look for task panels (swstyle/propertymanager.py), when present."""
    try:
        from . import propertymanager
    except ImportError:
        return None
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: propertymanager.py did not load: %s\n" % error)
        return None
    return propertymanager


def _in_overlay(dock, mw):
    """True for a dock FreeCAD floats over the 3D view (its overlay mode)."""
    w = dock.parentWidget()
    while w is not None and w is not mw:
        if "Overlay" in _class(w):
            return True
        w = w.parentWidget()
    return False


# Boxes of FreeCAD's sketch dialog that a sketch tool's PropertyManager leaves out.
SKETCH_EXTRAS = ("SketcherGui::TaskSketcherMessages", "SketcherGui::TaskSketcherConstraints",
                 "SketcherGui::TaskSketcherElements", "SketcherGui::TaskSketcherSolverAdvanced")


# --------------------------------------------------------------------------- frameless

def _tangent_snap_tool():
    """qssnaps-1121: the running sketch tool draws lines or arcs (Line, Centerline, Midpoint Line, the arcs)."""
    try:
        from .fwsketch import toolbase
        tool = toolbase.active()
        if tool is None:
            return False
        names = [c.__name__ for c in type(tool).__mro__]
        return any(n in ("LineTool", "ArcTool", "MidpointLineTool") for n in names)
    except Exception:
        return False


class FrameHelper(QtCore.QObject):
    ""

    MARGIN = 5

    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self.mw = shell.window
        self.active = False
        self._cursor = None
        self._poll = QtCore.QTimer(self)
        self._poll.setInterval(60)
        self._poll.timeout.connect(self._update_cursor)

    def enable(self):
        mw = self.mw
        if not (mw.windowFlags() & Qt.FramelessWindowHint):
            visible = mw.isVisible()
            maxed = mw.isMaximized()
            geo = mw.geometry()
            mw.setWindowFlag(Qt.FramelessWindowHint, True)
            if visible:
                if maxed:
                    mw.showMaximized()
                else:
                    mw.setGeometry(geo)
                    mw.show()
        self.active = True
        from . import events
        events.register("shell", (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick,     # titledrag-1127
                                  QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonRelease), self.eventFilter)
        self._poll.start()
        try:
            from . import workarea      # maximized stops at the taskbar (land192)
            workarea.install(mw)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: work area not kept: %s\n" % error)

    def disable(self, reframe=True):
        if not self.active:
            return
        self.active = False
        self._poll.stop()
        from . import events
        events.unregister("shell")
        try:
            from . import workarea
            workarea.uninstall()
        except Exception as _fw_err:
            _fw_log("shell.py:121", _fw_err)
        self._set_cursor(None)
        mw = self.mw
        if reframe and (mw.windowFlags() & Qt.FramelessWindowHint):
            visible = mw.isVisible()
            maxed = mw.isMaximized()
            geo = mw.geometry()
            mw.setWindowFlag(Qt.FramelessWindowHint, False)
            if visible:
                if maxed:
                    mw.showMaximized()
                else:
                    mw.setGeometry(geo)
                    mw.show()

    def _edges(self, gp):
        mw = self.mw
        if not mw.isVisible() or mw.isMaximized() or mw.isFullScreen():
            return Qt.Edges()
        r = mw.frameGeometry()
        if not r.adjusted(-1, -1, 1, 1).contains(gp):
            return Qt.Edges()
        m = self.MARGIN
        edges = Qt.Edges()
        if gp.x() - r.left() < m:
            edges |= Qt.LeftEdge
        elif r.right() - gp.x() < m:
            edges |= Qt.RightEdge
        if gp.y() - r.top() < m:
            edges |= Qt.TopEdge
        elif r.bottom() - gp.y() < m:
            edges |= Qt.BottomEdge
        return edges

    @staticmethod
    def _shape(edges):
        if edges in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge):
            return Qt.SizeFDiagCursor
        if edges in (Qt.RightEdge | Qt.TopEdge, Qt.LeftEdge | Qt.BottomEdge):
            return Qt.SizeBDiagCursor
        if edges & (Qt.LeftEdge | Qt.RightEdge):
            return Qt.SizeHorCursor
        if edges & (Qt.TopEdge | Qt.BottomEdge):
            return Qt.SizeVerCursor
        return None

    def _set_cursor(self, shape):
        if shape == self._cursor:
            return
        if self._cursor is not None:
            QtWidgets.QApplication.restoreOverrideCursor()
        if shape is not None:
            QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(shape))
        self._cursor = shape

    def _update_cursor(self):
        if QtWidgets.QApplication.mouseButtons() != Qt.NoButton:
            return
        if QtWidgets.QApplication.activePopupWidget() is not None:
            self._set_cursor(None)
            return
        self._set_cursor(self._shape(self._edges(QtGui.QCursor.pos())))

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter170(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter shell.py: %s\n" % exc)
            return False

    def _fw_filter170(self, obj, event):
        t = event.type()
        if t == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            # Unbound call: a pane widget keeps the main window in an attribute called window.
            if isinstance(obj, QtWidgets.QWidget) and QtWidgets.QWidget.window(obj) is self.mw:
                edges = self._edges(event.globalPosition().toPoint())
                if edges:
                    handle = self.mw.windowHandle()
                    if handle is not None and handle.startSystemResize(edges):
                        return True
                if self._caption(obj):
                    return self._caption_press(obj, event)
        elif t == QtCore.QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            if self._caption(obj):
                # titledrag-1127: a double-click on the title row maximizes or restores, as Windows' own title bar
                self._press = None
                try:
                    self.shell.toggle_maximized()
                except Exception as _fw_err:
                    _fw_log("shell.py:title-dblclick", _fw_err)
                return True
        elif t == QtCore.QEvent.MouseMove and self._press is not None:
            if not (event.buttons() & Qt.LeftButton):
                self._press = None
                return False
            gp = event.globalPosition().toPoint()
            if (gp - self._press[0]).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                return self._caption_drag(gp)
            return True
        elif t == QtCore.QEvent.MouseButtonRelease and self._press is not None:
            self._press = None
            return True
        return False

    # ------------------------------------------------------------------ titledrag-1127
    # Ati 11-27: grabbing a blank spot of the top bar did not move the window (0.3.3 had no move either: the

    # maximizes or restores, and dragging a maximized window down restores it under the pointer.
    CAPTION = ("QatRow",)
    _press = None

    def _caption(self, obj):
        """True for a press on the title row's blank space (its buttons, search box and logo are their own widgets)."""
        try:
            return isinstance(obj, QtWidgets.QWidget) and type(obj).__name__ in self.CAPTION and \
                QtWidgets.QWidget.window(obj) is self.mw and not self.mw.isFullScreen()
        except Exception:
            return False

    def _maxed(self):
        mw = self.mw
        try:
            return mw.isMaximized() or self.shell._fills(mw.geometry())
        except Exception:
            return mw.isMaximized()

    def _caption_press(self, obj, event):
        gp = event.globalPosition().toPoint()
        if self._maxed():
            self._press = (gp, event.position().toPoint().y())      # moved only once it is dragged (restores first)
            return True
        self._press = None
        handle = self.mw.windowHandle()
        if handle is not None and handle.startSystemMove():
            return True
        self._press = (gp, event.position().toPoint().y())          # no system move: moved by hand
        return True

    def _caption_drag(self, gp):
        press, self._press = self._press, None
        mw = self.mw
        if self._maxed():
            full = mw.frameGeometry()
            ratio = (press[0].x() - full.x()) / float(max(1, full.width()))
            self.shell.restore_down()
            normal = mw.frameGeometry()
            mw.move(int(gp.x() - ratio * normal.width()), max(0, gp.y() - press[1]))
        handle = mw.windowHandle()
        if handle is not None and handle.startSystemMove():
            return True
        mw.move(mw.pos() + (gp - press[0]))
        return True


# --------------------------------------------------------------------------- search
SEARCH_LIST_QSS = ("QListWidget#SWCommandSearchList { background: ${base}; border: 1px solid ${field_line}; color: ${text}; }"
                   "QListWidget#SWCommandSearchList::item { padding: 2px 4px; }"
                   "QListWidget#SWCommandSearchList::item:selected { background: ${selection}; color: ${text}; }")


class CommandSearch(QtCore.QObject):
    ""






    NO_RESULTS = "No results found"

    ROWS = 10
    WIDTH = 330
    MOST = 40

    def __init__(self, shell):
        super().__init__(shell.window)
        self.shell = shell
        self.setObjectName("SWCommandSearch")
        self.list = QtWidgets.QListWidget(shell.window)
        self.list.setObjectName("SWCommandSearchList")
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setIconSize(QtCore.QSize(20, 20))
        self.list.setFont(ui_font())
        self.list.setFrameShape(QtWidgets.QFrame.Box)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setStyleSheet(style.fill(SEARCH_LIST_QSS))
        self.list.itemClicked.connect(self._run_item)
        self.list.setMouseTracking(True)
        self.list.itemEntered.connect(self._hovered)
        self.list.viewport().installEventFilter(self)
        self._press = None
        self.dragged = []            # (catalog key, drop action) of results dragged, for checks
        self.locate = QtWidgets.QToolButton(self.list.viewport())
        self.locate.setObjectName("SWShowCommandLocation")
        self.locate.setAutoRaise(True)
        self.locate.setFocusPolicy(Qt.NoFocus)
        self.locate.setToolTip("Show command location")
        self.locate.clicked.connect(self._locate_clicked)
        self.locate.hide()
        self._located = None
        self.located = []            # what Show command location did, for checks
        self.list.hide()
        self.box = None
        self._index = None
        self.runs = 0                # commands run from here, for checks
        self.last_run = None

    def retheme(self):
        """A theme change: the result list's colours follow."""
        if alive(self.list):
            self.list.setStyleSheet(style.fill(SEARCH_LIST_QSS))

    def _runnable(self, name):
        """Whether the command can run now. Read from its QAction, which FreeCAD keeps up to
        date: Command.isActive() on a command whose action was never made crashes FreeCAD 1.1."""
        if name.startswith("sw:"):
            binding = self.shell.binding(name[3:])
            binding.resolve()
            if (binding.action is not None and alive(binding.action)) or (binding.cmd.call and not binding.cmd.natives):
                binding.update_state()
                return binding.enabled
            name = binding.native
            if not name:
                # a workbench that loads when its add-in tab is first shown: the row is live, running it loads it
                from . import lazycmds
                return lazycmds.state(binding.cmd) == "load"
        try:
            actions = [a for a in Gui.Command.get(name).getAction() if isinstance(a, QtGui.QAction)]
        except Exception:
            return False
        return actions[0].isEnabled() if actions else True

    def _hovered(self, item):
        name = item.data(Qt.UserRole) if item is not None else None
        if not name:
            self.locate.hide()
            return
        tip = item.data(Qt.UserRole + 2) or ""
        if tip:
            self.shell.window.statusBar().showMessage(tip, 6000)
        rect = self.list.visualItemRect(item)
        size = max(16, rect.height() - 2)
        self.locate.setIcon(cmdlocate.glasses_icon(style.T.hex("text"), 16, self.list.devicePixelRatioF()))
        self.locate.setIconSize(QtCore.QSize(16, 16))
        self.locate.setGeometry(rect.right() - size - 2, rect.top() + 1, size, size)
        self._located = item
        self.locate.show()
        self.locate.raise_()

    def drag_key(self, item):
        """The catalog key a result adds to the CommandManager when dragged onto a tab: its own, or the catalog
        entry that runs the FreeCAD command it names; None for menu-only results."""
        name = item.data(Qt.UserRole) if item is not None else None
        if not name or ":" in name and not name.startswith("sw:"):
            return None
        if name.startswith("sw:"):
            return name[3:] if name[3:] in catalog.BY_KEY else None
        for cmd in catalog._ALL:
            if name in (cmd.natives or ()):
                return cmd.key
        return None

    def eventFilter(self, obj, event):
        ""


        try:
            t = event.type()
            if t == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._press = (self.list.itemAt(event.position().toPoint()), event.globalPosition().toPoint())
            elif t == QtCore.QEvent.MouseMove and self._press is not None and event.buttons() & Qt.LeftButton:
                item, start = self._press
                if (event.globalPosition().toPoint() - start).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                    self._press = None
                    key = self.drag_key(item)
                    if key:
                        self._drag(item, key)
                        return True
            elif t == QtCore.QEvent.MouseButtonRelease:
                self._press = None
        except Exception as _fw_err:
            _fw_log("shell.py:search-drag", _fw_err)
        return False

    def _drag(self, item, key):
        from . import cmcustom, customizedlg
        started = not cmcustom._FILTER
        if started:
            cmcustom.start(self.shell)
        try:
            data = QtCore.QMimeData()
            data.setData(customizedlg.MIME, key.encode())
            drag = QtGui.QDrag(self.list)
            drag.setMimeData(data)
            if not item.icon().isNull():
                drag.setPixmap(item.icon().pixmap(24, 24))
            result = drag.exec(Qt.CopyAction)
            self.dragged.append((key, int(result.value) if hasattr(result, "value") else int(result)))
        finally:
            if started:
                cmcustom.stop()
        self.hide()

    def _locate_clicked(self):
        item = self._located
        if item is None:
            return
        name = item.data(Qt.UserRole)
        self.hide()
        self.located.append((name, cmdlocate.show(self.shell, name)))

    def _build_index(self):
        ""


        infos = {}
        for name in Gui.listCommands():
            try:
                info = Gui.Command.get(name).getInfo()
            except Exception:
                continue
            infos[name] = ((info.get("menuText") or name).replace("&", ""), info.get("toolTip") or "",
                           info.get("pixmap") or "")
        index = []
        natives = set()
        from . import lazycmds
        for cmd in catalog.ALL:
            natives.update(cmd.natives or ())
            if lazycmds.state(cmd) == "none":
                continue             # this installation has no such command (its workbench is not installed): no dead row
            also = " ".join(infos[n][0].lower() for n in (cmd.natives or ()) if n in infos)
            index.append((cmd.label, "sw:" + cmd.key, cmd.tip or "", "", True, also))
        labels = {e[0].lower() for e in index}
        for name, (text, tip, pixmap) in infos.items():
            # searchdup-1121: the sketch-first / tool-first wrappers are the CommandManager command itself
            # (listed above under its own name), not a second "3 Point Center Rectangle"; searchdup2-1121: a
            # wrapper whose name nothing else carries (Elliptical Arc, Ellipse From Center, External
            # Intersection) stays findable
            if name not in natives and not (name.startswith(("SWStyle_SF_", "SWStyle_TF_")) and text.lower() in labels):
                index.append((text, name, tip, pixmap, False, ""))
        index.sort(key=lambda x: x[0].lower())
        self._index = index
        self._tabs = None

    def _tab_of(self, name):
        ""

        if getattr(self, "_tabs", None) is None:
            self._tabs = {}
            try:
                from . import cmdhelp
                for mode, title, keys in cmdhelp.tab_rows():
                    for key in keys:
                        where = title if mode == "part" else "%s > %s" % (mode.capitalize(), title)
                        self._tabs.setdefault(key, where)
            except Exception as _fw_err:
                _fw_log("shell.py:search-tabs", _fw_err)
        if name.startswith("sw:"):
            return self._tabs.get(name[3:], "")
        group = name.split("_", 1)[0]
        return "" if group in ("SWStyle", "FreeWorks", "FW", "Std") or group == name else group

    def _where(self, name):
        """The menu a search result sits in, as "View > Set Current View As", or ""."""
        try:
            native = self.shell.binding(name[3:]).native if name.startswith("sw:") else name
            path = cmdlocate.menu_path(self.shell.native_menubar(), native) if native else []
            return " > ".join(a.text().replace("&", "") for a in path[:-1])
        except Exception:
            return ""

    def _icon(self, name, pixmap, sw):
        try:
            if sw:
                cmd = catalog.BY_KEY[name[3:]]
                return icons.command_icon(cmd, self.shell.binding(cmd.key).action)
            if pixmap:
                return Gui.getIcon(pixmap)
        except Exception as _fw_err:
            _fw_log("shell.py:345", _fw_err)
        return QtGui.QIcon()

    def typed(self, text, box):
        ""

        self.box = box
        if self._index is None:
            try:
                self.shell.ensure_command_modules()
            except Exception as _fw_err:
                _fw_log("shell.py:356", _fw_err)
            self._build_index()
        self.list.clear()
        text = text.strip().lower()
        if not text:
            self.hide()
            return
        starts, within = [], []
        # Customize > Keyboard's Search Shortcut: the commands given these letters come first
        try:
            from . import customizedlg
            pinned_names = customizedlg.search_keys().get(text, set())
        except Exception:
            pinned_names = set()
        pinned = []
        for entry in self._index:
            if pinned_names and (entry[1] in pinned_names or (entry[1].startswith("sw:") and entry[1][3:] in catalog.BY_KEY
                                 and set(catalog.BY_KEY[entry[1][3:]].natives or ()) & pinned_names)):
                pinned.append(entry)
                continue
            low = entry[0].lower()
            if low.startswith(text):
                starts.append(entry)
            elif text in low or text in entry[1].lower() or text in entry[5]:
                within.append(entry)
        hits = (pinned + [e for e in starts if e[4]] + [e for e in starts if not e[4]]
                + [e for e in within if e[4]] + [e for e in within if not e[4]])
        preferred = {
            "rectangle": "sw:CornerRectangle",
            "arc": "sw:CenterArc",
            "slot": "sw:Slot",
            "table": "sw:DrawGeneralTable",
            "surface": "sw:WB_Surface",
            "speedpak": "FW_Comp_AddSpeedPak",
            "flatten": "sw:SM_Flatten",
        }.get(text)
        sketch_preferences = {
            "point": "sw:SketchPoint",
            "line": "sw:Line",
            "corner rectangle": "sw:CornerRectangle",
            "center rectangle": "sw:CenterRectangle",
            "circle": "sw:Circle",
            "perimeter circle": "sw:PerimeterCircle",
            "centerpoint arc": "sw:CenterArc",
            "3 point arc": "sw:ThreePointArc",
            "ellipse": "sw:Ellipse",
            "spline": "sw:Spline",
            "polygon": "sw:Polygon",
            "straight slot": "sw:Slot",
            "text": "sw:Text",
            "sketch fillet": "sw:SketchFillet",
            "sketch chamfer": "sw:SketchChamfer",
            "trim entities": "sw:Trim",
            "convert entities": "sw:Convert",
            "offset entities": "sw:Offset",
            "mirror entities": "sw:MirrorEntities",
            "linear sketch pattern": "sw:LinearSketchPattern",
            "circular sketch pattern": "sw:CircularSketchPattern",
            "move entities": "sw:MoveEntities",
            "copy entities": "sw:CopyEntities",
            "rotate entities": "sw:RotateEntities",
            "scale entities": "sw:ScaleEntities",
            "display/delete relations": "sw:Relations",
            "add relation": "sw:AddRelation",
            "ordinate dimension": "sw:OrdinateDimension",
            "baseline dimension": "sw:BaselineDimension",
            "centerline": "sw:Centerline",
            "angle dimension": "sw:AngularDimension",
            "radius dimension": "sw:RadiusDimension",
            "diameter dimension": "sw:RadiusDimension",
        }
        if preferred is None and (text == "exit sketch" or text in sketch_preferences):
            in_3d_sketch = False
            if text == "exit sketch":
                try:
                    from . import sketch3d
                    in_3d_sketch = bool(sketch3d.editing())
                except Exception as _fw_err:
                    _fw_log("shell.py:434", _fw_err)
            try:
                from .fwsketch import commands as fwsketch_commands
                in_part_sketch = bool(fwsketch_commands.sketch_in_edit())
            except Exception:
                in_part_sketch = False
            if text == "exit sketch":
                if in_3d_sketch:
                    preferred = "sw:Exit3DSketch"
                elif in_part_sketch:
                    preferred = "sw:ExitSketch"
            elif in_part_sketch:
                preferred = sketch_preferences[text]
        if preferred is None and text == "display style":
            try:
                if flyouttree.is_drawing(App.ActiveDocument):
                    preferred = "sw:DrawDisplayStyle"
                elif App.ActiveDocument is not None:
                    preferred = "sw:DisplayStyle"
            except Exception as _fw_err:
                _fw_log("shell.py:454", _fw_err)
        if preferred is None and text == "centerline":
            try:
                if flyouttree.is_drawing(App.ActiveDocument):
                    from . import drawsketchedit
                    preferred = ("sw:DrawSketchCenterline" if drawsketchedit.sketch_panel_open() is not None
                                 else "sw:DrawCenterline")
            except Exception as _fw_err:
                _fw_log("shell.py:462", _fw_err)
        if preferred is not None:
            target = next((e for e in hits if e[1] == preferred), None)
            if target is None:
                # AngularDimension and RadiusDimension need not naturally match the exact query text.
                target = next((e for e in self._index if e[1] == preferred), None)
            if target is not None:
                # the user's own Search Shortcut picks (Customize > Keyboard) stay first
                rest = [e for e in hits if e[1] != preferred and e not in pinned]
                hits = pinned + ([] if target in pinned else [target]) + rest
        hits = hits[:self.MOST]
        dim = QtGui.QBrush(style.T.text_disabled)
        seen = {}
        for entry in hits:
            seen[entry[0].lower()] = seen.get(entry[0].lower(), 0) + 1
        for label, name, tip, pixmap, sw, _also in hits:
            item = QtWidgets.QListWidgetItem(label)
            if seen[label.lower()] > 1:
                # two commands of one name (Front, and Set Current View As > Front): the menu says which
                where = self._where(name) or self._tab_of(name)     # searchdup-1121: else the tab it is on
                if where:
                    item.setText("%s  (%s)" % (label, where))
            item.setData(Qt.UserRole, name)
            runnable = self._runnable(name)
            item.setData(Qt.UserRole + 1, runnable)
            item.setData(Qt.UserRole + 2, QtGui.QTextDocumentFragment.fromHtml(tip).toPlainText() if tip else "")
            item.setToolTip(tip or name)
            icon = self._icon(name, pixmap, sw)
            if not icon.isNull():
                item.setIcon(icon)
            if not runnable:

                item.setForeground(dim)
            self.list.addItem(item)
        if not self.list.count():
            item = QtWidgets.QListWidgetItem(self.NO_RESULTS)
            item.setFlags(Qt.NoItemFlags)
            item.setForeground(dim)
            self.list.addItem(item)


            words = text
            for label, key in (("Search Help for \"%s\"" % words, "help:"), ("Search Community for \"%s\"" % words, "community:")):
                row = QtWidgets.QListWidgetItem(label)
                row.setData(Qt.UserRole, key + words)
                row.setData(Qt.UserRole + 1, True)
                self.list.addItem(row)
            self.list.setCurrentRow(1)
        else:
            self.list.setCurrentRow(0)
        self.locate.hide()
        self.place()
        self.list.raise_()
        self.list.show()

    def place(self):
        box, mw = self.box, self.shell.window
        if box is None or not alive(box):
            return
        pos = box.mapTo(mw, QtCore.QPoint(0, box.height() + 2))
        width = max(self.WIDTH, box.width())
        x = max(2, min(pos.x() + box.width() - width, mw.width() - width - 2))     # its right edge on the box's
        rows = min(self.list.count(), self.ROWS)
        row_h = self.list.sizeHintForRow(0) if self.list.count() else 22
        self.list.setGeometry(x, pos.y(), width, rows * row_h + 4)

    def list_shown(self):
        return alive(self.list) and self.list.isVisible()

    def labels(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def move_current(self, delta):
        if not self.list.count():
            return
        row = max(0, min(self.list.currentRow() + delta, self.list.count() - 1))
        self.list.setCurrentRow(row)

    def run_current(self):
        item = self.list.currentItem() if self.list_shown() else None
        if item is not None:
            self._run_item(item)

    def _run_item(self, item):
        name = item.data(Qt.UserRole)
        if not name or not item.data(Qt.UserRole + 1):
            return                   # "No results found", or greyed: nothing runs
        self.hide()
        box = self.box
        if box is not None and alive(box):
            box.clear()
            box.clearFocus()
        self.runs += 1
        self.last_run = name
        if name.startswith("help:") or name.startswith("community:"):
            from . import helpmenu
            kind, words = name.split(":", 1)
            if kind == "help":
                helpmenu.show("home", search=words)
            else:
                helpmenu.search_community(words)
        elif name.startswith("sw:"):
            from . import lazycmds
            binding = self.shell.binding(name[3:])
            if not binding.native and lazycmds.state(binding.cmd) == "load":
                # its workbench loads now, as it does when its add-in tab is first shown
                got = lazycmds.load(binding.cmd, self.shell)
                self._index = None
                binding = self.shell.binding(name[3:])
                binding.resolve()
                binding.update_state()
                if got != "ready":
                    self.shell.window.statusBar().showMessage(lazycmds.MESSAGES[got] % binding.cmd.label, 6000)
                    return
            binding.run()
        else:
            # Gui.runCommand goes round the command's action: Enter must still repeat it
            self.shell.note_command(name)
            try:
                Gui.runCommand(name, 0)
            except Exception as error:
                App.Console.PrintError("%s: %s\n" % (name, error))

    def hide(self):
        if alive(self.list) and not self.list.isHidden():
            self.list.hide()

    def hide_if_unfocused(self):
        box = self.box
        if box is None or not alive(box) or not box.hasFocus():
            self.hide()

    def remove(self):
        if alive(self.list):
            self.list.hide()
            self.list.setParent(None)
            self.list.deleteLater()


# --------------------------------------------------------------------------- shell
# tools that work only in a 3D sketch (they start one from the part): left out of flyouts in a 2D sketch
# cmfly-1126: flyout groups (first flyout key -> {key: group}); a separator where the group changes
FLYOUT_GROUPS = {"SplitLine": {"SplitLine": 0, "*": 1},
                 "QuickSnaps": {"QSTangent": 1, "QSHVPoint": 1, "QSGrid": 2, "*": 0}}
SKETCH3D_ONLY = ("OffsetOnSurface", "SplineOnSurface", "Sketch3D", "Sketch3DOnPlane")   # nodead-1126: 3D Sketch cannot start in a 2D sketch


class Shell(QtCore.QObject):
    def __init__(self, window=None):
        window = window or Gui.getMainWindow()
        super().__init__(window)
        self.window = window
        self.enabled = False
        self.bindings = {}
        self.views = viewkeys.ViewHistory()
        self.frame = FrameHelper(self)
        self.search = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.refresh)
        try:
            from . import ticks as _ticks
            _ticks.slow_when_idle(self.timer)
        except Exception as _fw_err:
            __import__("FreeCAD").Console.PrintLog("FreeCAD ticks: %s\n" % _fw_err)
        # Page and ribbon switching for dialogs and sketches reacts faster than
        # the rest of the refresh.
        self.watch = QtCore.QTimer(self)
        self.watch.setInterval(150)
        self.watch.timeout.connect(self._watch)
        try:
            from . import ticks as _ticks
            _ticks.slow_when_idle(self.watch)
        except Exception as _fw_err:
            __import__("FreeCAD").Console.PrintLog("FreeCAD ticks: %s\n" % _fw_err)
        self._signals = []
        self._was_dialog = False
        self._sketch_tool_box = None
        self._tool_hidden = []
        self._was_sketch = None
        self._native_sig = None
        self._native_page = None
        self._toolbar_filtered = []
        self._hidden_toolbars = []
        self._tick = 0
        self.context = None
        self.gestures = None
        self.viewkeys = None
        self.view_selector = None
        self.orientation = None
        self.sketch_exit = None
        self.flyout = None
        self.rollback = None
        self.pencil = None
        self.planes = None
        self.sketch_status = None
        self.relations_pm = None
        self.breadcrumbs = None
        self.face_hover = None
        self.sketch_origin = None
        self.feature_manager = None
        self.clean_open = None

    # ------------------------------------------------------------------ bindings
    def binding(self, key):
        b = self.bindings.get(key)
        if b is None:
            b = Binding(catalog.BY_KEY[key], self)
            run = b.run

            def run_and_note(run=run, b=b):
                was_enabled = b._enabled
                run()
                if was_enabled:
                    self.note_command(b.native)
            b.run = run_and_note
            self.bindings[key] = b
        return b

    def note_command(self, name):
        """A command just ran (for Enter, Repeat Last Command). FreeCAD's own menus and keys are
        noticed through their actions; this covers runs that go round them."""
        if name and self.viewkeys is not None:
            self.viewkeys.last.note(name)

    def special_enabled(self, call):
        if call == "clear_selection":
            return True
        if call == "edit_feature":
            return contextbar.feature_to_edit() is not None
        if call == "edit_feature_sketch":
            return contextbar.sketch_to_edit() is not None
        if call == "rollback":
            return contextbar.feature_to_roll_back() is not None or rollbackbar.step_back_feature() is not None
        if call == "mass_properties":
            return App.ActiveDocument is not None
        if call in ("pm_ok", "pm_cancel"):
            return self.pm_button(call) is not None
        if call == "previous_view":

            # earlier view a click does nothing
            return self._view() is not None
        if call in ("scene_menu", "menu", "view_selector", "orientation", "redraw"):
            return self._view() is not None
        if call.startswith("viewport:") or call == "link_views":
            return Gui.ActiveDocument is not None
        if call.startswith("draw_style:"):
            return self._view() is not None or drawing_display_style(None, probe=True)
        if call.startswith("wb:"):
            return call[3:] in Gui.listWorkbenches()
        return False

    def pm_button(self, call):
        """The open task panel's enabled OK (pm_ok) or Cancel/Close (pm_cancel) button, or None:
        the PropertyManager's through pmconfirm (the PM thread's one place), else any task panel's."""
        role = "ok" if call == "pm_ok" else "cancel"
        try:
            from . import pmconfirm
            button = pmconfirm._button(role) if pmconfirm.open() else None
            if button is not None and button.isEnabled():
                return button
        except Exception as _fw_err:
            _fw_log("shell.py:693", _fw_err)
        try:
            if not Gui.Control.activeDialog():
                return None
        except Exception as _fw_err:
            _fw_log("shell.py:729", _fw_err)
            return None
        roles = QtWidgets.QDialogButtonBox
        want = (roles.AcceptRole, roles.YesRole) if role == "ok" else (roles.RejectRole, roles.NoRole)
        try:
            for box in self.window.findChildren(QtWidgets.QDialogButtonBox):
                if not box.isVisible():
                    continue
                for button in box.buttons():
                    if box.buttonRole(button) in want and button.isEnabled():
                        return button
        except Exception as _fw_err:
            _fw_log("shell.py:709", _fw_err)
        return None

    def draw_style_index(self):
        """The index of the view's draw style in FreeCAD's Std_DrawStyle list (6 = Flat lines), or None."""
        try:
            actions = Gui.Command.get("Std_DrawStyle").getAction()
        except Exception as _fw_err:
            _fw_log("shell.py:749", _fw_err)
            return None
        for i, act in enumerate(actions):
            try:
                if act.isChecked():
                    if i == 0:
                        i = 6
                    if i == 6:
                        try:
                            from . import hlv
                            if hlv.shaded():
                                return 5
                        except Exception as _fw_err:
                            _fw_log("shell.py:shaded", _fw_err)
                    return i
            except Exception as _fw_err:
                _fw_log("shell.py:723", _fw_err)
        return None

    def special_checked(self, call):
        if call == "link_views":
            from . import windowmenu
            return windowmenu.LINK.on
        if call == "view_selector":
            return self.view_selector is not None and self.view_selector.visible
        if call.startswith("draw_style:"):
            index = int(call[len("draw_style:"):])
            if index == 3:
                try:
                    from . import hlv
                    if hlv.active():
                        return False  # Hidden Lines Visible is drawn over Hidden line: only it shows pressed
                except Exception as _fw_err:
                    _fw_log("shell.py:740", _fw_err)
            return self.draw_style_index() == index
        if call == "clear_selection":
            try:
                return not Gui.Control.activeDialog()
            except Exception as _fw_err:
                _fw_log("shell.py:779", _fw_err)
                return False
        if call.startswith("wb:"):
            try:
                return Gui.activeWorkbench().name() == call[3:]
            except Exception as _fw_err:
                _fw_log("shell.py:785", _fw_err)
                return False
        return False

    def special(self, call, binding):
        """Addon-side actions. Returns True when the call was fully handled."""
        if call == "clear_selection":
            Gui.Selection.clearSelection()
            return True
        if call == "mass_properties":
            massprops.show(self.window)
            return True
        if call in ("pm_ok", "pm_cancel"):
            # the mouse gesture / shortcut bar OK and Cancel: the open PropertyManager's buttons
            button = self.pm_button(call)
            if button is not None:
                if call == "pm_ok":
                    from . import pmkeys
                    pmkeys.accept(button)
                else:
                    button.click()
            return True
        if call == "edit_feature":
            contextbar.edit_feature()
            return True
        if call == "edit_feature_sketch":
            contextbar.edit_feature_sketch()
            return True
        if call == "rollback":
            feature = contextbar.feature_to_roll_back() or rollbackbar.step_back_feature()
            if feature is not None:
                rollbackbar.roll_back_to(feature)
            return True
        if call == "push_view":
            self.push_view()
            if binding.cmd.key == "NormalTo" and "SWStyle_NormalTo" not in Gui.listCommands() \
                    and self._normal_to_datum():    # SWStyle_NormalTo (keys.py) does datums itself
                return True
            return False
        if call == "previous_view":
            self.previous_view()
            return True
        if call == "view_selector":
            if self.view_selector is not None:
                self.view_selector.toggle()
            return True
        if call == "orientation" or (call == "menu" and binding.cmd.key == "ViewOrientation"):
            # Search Commands or a key: the Orientation box, as Space
            self.toggle_orientation()
            return True
        if call.startswith("viewport:") or call == "link_views":
            # the View Orientation flyout's viewport layouts and Link Views (windowmenu)
            from . import windowmenu
            try:
                if call == "link_views":
                    windowmenu.LINK.toggle()
                else:
                    windowmenu.viewport(call[len("viewport:"):])
            except Exception as error:
                App.Console.PrintError("FreeCAD: viewport: %s\n" % error)
            return True
        if call.startswith("draw_style:"):

            # group action is triggered itself: runCommand("Std_DrawStyle", n) leaves the view as is.
            index = int(call[len("draw_style:"):])
            if drawing_display_style(DRAW_STYLE_NAMES.get(index)):
                return True          # on a drawing: the picked views (drawings-land23, D19)
            try:
                Gui.Command.get("Std_DrawStyle").getAction()[index].trigger()
            except Exception as error:
                App.Console.PrintError("FreeCAD: draw style %d: %s\n" % (index, error))
            return True
        if call == "redraw":
            view = self._view()
            try:
                view.redraw()
            except Exception:
                Gui.updateGui()
            return True
        if call.startswith("wb:"):
            try:
                Gui.activateWorkbench(call[3:])
            except Exception as error:
                App.Console.PrintError("%s\n" % error)
            return True
        if call in ("menu", "scene_menu"):
            # a flyout-only button run without its own click (Search Commands, a shortcut, a check):
            # its flyout opens under it, as a click on it does
            from .widgets import CommandButton
            for b in Gui.getMainWindow().findChildren(CommandButton):
                if b.binding is binding and b.isVisible():
                    b.show_flyout()
                    return True
        return False


    def toggle_orientation(self):
        """Space: the Orientation box at the top left of the 3D view with the View Selector in the
        view; Space again takes both away."""
        if self.orientation is None:
            return False
        if self.orientation.isVisible() or (self.view_selector is not None and self.view_selector.visible):
            self.hide_orientation("space")
            return False
        return self.show_orientation()

    def show_orientation(self):
        if self.orientation is None or not self.orientation.show_box():
            return False
        if self.view_selector is not None and viewselector.enabled():
            self.view_selector.show()
        return True

    def hide_orientation(self, reason="close"):
        if self.view_selector is not None:
            self.view_selector.hide(reason)
        if self.orientation is not None:
            self.orientation.hide_box(reason)

    def _selector_toggled(self, on):
        if self.view_selector is None:
            return
        if on and self.orientation is not None and self.orientation.isVisible():
            self.view_selector.show()
        elif not on:
            self.view_selector.hide("off")

    def _view(self):
        try:
            doc = Gui.ActiveDocument
            view = doc.ActiveView if doc is not None else None
            return view if view is not None and hasattr(view, "getCamera") else None
        except Exception:
            return None

    def _view_key(self):
        """Each document keeps its own views for Previous View."""
        try:
            doc = Gui.ActiveDocument.Document
            return getattr(doc, "Uid", "") or doc.Name
        except Exception:
            return None

    def _normal_to_datum(self):
        ""

        try:
            sel = Gui.Selection.getSelectionEx()
            if len(sel) != 1 or sel[0].SubElementNames and any(sel[0].SubElementNames):
                return False
            obj = sel[0].Object
            if obj.TypeId not in ("Sketcher::SketchObject", "PartDesign::Plane", "App::Plane"):
                return False
            view = self._view()
            if view is None:
                return False
            view.setCameraOrientation(obj.getGlobalPlacement().Rotation.Q)
            return True
        except Exception:
            return False

    def push_view(self):
        """Keeps the view a command is about to leave (the view history also notices views that
        stay put, so this only matters when the next change comes quickly)."""
        view, key = self._view(), self._view_key()
        if view is not None and key:
            try:
                self.views.push(key, view.getCamera())
            except Exception as _fw_err:
                _fw_log("shell.py:919", _fw_err)

    def previous_view(self):
        ""
        view, key = self._view(), self._view_key()
        if view is None or not key:
            return
        try:
            text = self.views.previous(key, view.getCamera())
            if text:
                try:
                    from . import camanim
                    if camanim.animate_change(lambda v: v.setCamera(text), view):
                        return
                except Exception as _fw_err:
                    _fw_log("shell.py:prev-anim", _fw_err)
                view.setCamera(text)
        except Exception as error:
            App.Console.PrintWarning("Previous View: %s\n" % error)

    def _sample_view(self):
        view, key = self._view(), self._view_key()
        if view is None or not key:
            return
        try:
            self.views.sample(key, view.getCamera(), time.monotonic())
            docs = App.listDocuments()                  # perf-1126: a closed document's views go
            self.views.prune({getattr(d, "Uid", "") or d.Name for d in docs.values()})
        except Exception as _fw_err:
            _fw_log("shell.py:940", _fw_err)

    # ------------------------------------------------------------------ menus
    def _menu(self, parent=None):
        from .widgets import FlyoutMenu
        menu = FlyoutMenu(parent or self.window)
        menu.setFont(ui_font())
        menu.setToolTipsVisible(True)
        return menu

    def _add_binding_action(self, menu, key, on_chosen=None):
        b = self.binding(key)
        b.resolve()
        b.update_state()
        instead = None
        try:
            from . import flyoutpick        # never greyed: a row that needs a pick asks for it; one with nothing to do is left out
            keep, instead = flyoutpick.fix_action(None, getattr(b, "native", None), b.enabled)
            if not keep:
                return None
        except Exception as _fw_err:
            _fw_log("shell.py:flyoutpick", _fw_err)
        if instead is None and not b.enabled:
            def instead(b=b, key=key):          # nogrey-1126 (rcmenus): live, a click says what to do first
                b.update_state()
                if b.enabled:
                    if on_chosen is not None:
                        on_chosen(key)
                    b.run()
                    return
                from . import menunotready
                menunotready.tell(b.cmd.label, menunotready.text_for(getattr(b, "native", None), b.cmd.label))
        act = menu.addAction(b.icon(), b.cmd.label)
        act.setEnabled(b.enabled or instead is not None)
        act.setToolTip(b.tooltip().replace("<br>", "\n").replace("<b>", "").replace("</b>", ""))
        if b.checked:
            act.setCheckable(True)
            act.setChecked(True)

        def run(checked=False, b=b, key=key):
            if on_chosen is not None:
                on_chosen(key)
            b.run()
        act.triggered.connect(run if instead is None else (lambda checked=False, f=instead: f()))
        return act

    def build_flyout(self, button):
        call = button.binding.cmd.call
        menu = self._menu(button)
        if button.binding.cmd.key in ("Undo", "Redo") and button.kind == "qat":
            return self._history_menu(menu, button.binding.cmd.key)
        if call == "scene_menu":

            from . import scenemenu
            return scenemenu.fill(menu)
        if button.binding.cmd.key == "ViewOrientation" and button.kind == "hud":

            from . import orientation
            return orientation.fill_flyout(self, menu)
        if button.binding.cmd.key == "HideShowItems" and button.kind == "hud":

            from . import hideshow
            return hideshow.fill_flyout(self, menu, button.flyout_keys)
        if button.binding.cmd.key in ("DisplayStyle", "ViewSettings") and button.kind == "hud" and button.flyout_keys:

            from . import hudstrip
            return hudstrip.fill_flyout(self, menu, button.flyout_keys)
        if button.binding.cmd.key == "ViewSettings":

            from . import viewsettings
            for text, is_on, turn in viewsettings.entries():
                act = menu.addAction(text)
                act.setCheckable(True)
                act.setChecked(bool(is_on()))
                act.triggered.connect(lambda checked=False, turn=turn: turn(bool(checked)))
            return menu
        swap = button.kind in ("grid", "large", "hud") and button.flyout_keys \
            and button.flyout_keys[0] == button.binding.cmd.key or \
            (button.kind in ("grid", "large", "hud") and button.binding.cmd.key in button.flyout_keys)

        def chosen(key, button=button):
            if swap and key != button.binding.cmd.key and button.kind in ("grid", "hud") and alive(button):
                self.rebind(button, key)
                if button.kind == "grid":

                    try:
                        App.ParamGet(FLYOUT_LAST).SetString(button.flyout_keys[0], key)
                    except Exception as _fw_err:
                        _fw_log("shell.py:flyoutlast", _fw_err)
        in_2d = self.in_sketch()
        groups = FLYOUT_GROUPS.get(button.flyout_keys[0] if button.flyout_keys else None)    # cmfly-1126
        last = None
        for key in button.flyout_keys:
            if key == "QuickSnaps":
                continue
            if in_2d and key in SKETCH3D_ONLY:
                continue        # fix230: a 3D-sketch-only tool, greyed in a 2D sketch: left out
            if key == "QSTangent" and not _tangent_snap_tool():
                continue
            if button.binding.cmd.key == "SmartDimension" and key != "SmartDimension" and not in_2d:
                continue
            if groups:
                group = groups.get(key, groups["*"])
                if last is not None and group != last:
                    menu.addSeparator()
                last = group
            act = self._add_binding_action(menu, key, chosen)
            if act is not None and key == "ProjectedCurve" and button.binding.cmd.key == "Curves":
                act.setText("Project Curve")
        return menu

    def _history_menu(self, menu, which):
        ""
        doc = App.ActiveDocument
        names = list(getattr(doc, "UndoNames" if which == "Undo" else "RedoNames", []) or []) if doc else []
        command = "Std_" + which
        if not names:
            act = menu.addAction("Nothing to %s" % which.lower())
            act.setEnabled(False)
            return menu
        try:
            from .undowording import display as _shown
        except Exception:
            def _shown(name, *_args):
                return str(name)
        for i, name in enumerate(names[:20]):
            # features-480: the list's step that made the body's first solid says "Base Extrude", as Edit > Undo
            act = menu.addAction("%d  %s" % (i + 1, _shown(name, doc, names if which == "Undo" else None, i)))
            act.triggered.connect(lambda checked=False, n=i + 1: [Gui.runCommand(command, 0) for _ in range(n)])
        return menu

    def rebind(self, button, key):
        try:
            button.binding.changed.disconnect(button.update)
        except Exception as _fw_err:
            _fw_log("shell.py:1015", _fw_err)
        button.binding = self.binding(key)
        button.binding.changed.connect(button.update)
        button._lines = [button.binding.cmd.label]
        button.setToolTip(button.binding.tooltip())
        button.update()

    def menu_for_keys(self, keys):
        menu = self._menu()
        for key in keys:
            self._add_binding_action(menu, key)
        return menu

    def native_menubar(self):
        return self.window.menuBar()

    def command_search(self):
        if self.search is None or not alive(self.search.list):
            self.search = CommandSearch(self)
        return self.search

    def show_command_search(self):
        """The search box takes the keys (a menu entry or key for it)."""
        box = self.topbar.qat.search
        if getattr(box, "kind", None) not in (None, "SWStyle_SearchCommands"):
            box.set_kind("SWStyle_SearchCommands")      # searchkind-1119: Search Commands (W) searches commands
        box.setFocus(Qt.ShortcutFocusReason)
        box.selectAll()

    def show_help_menu(self, button):
        menu = self._menu(button)
        for name in ("Std_OnlineHelp", "Std_WhatsThis", "Std_FreeCADUserHub", "Std_FreeCADForum",
                     "Std_ReportBug", "Std_About"):
            try:
                cmd = Gui.Command.get(name)
            except Exception:
                cmd = None
            if cmd is None:
                continue
            info = cmd.getInfo()
            act = menu.addAction((info.get("menuText") or name).replace("&", ""))
            act.triggered.connect(lambda checked=False, n=name: Gui.runCommand(n, 0))
        menu.addSeparator()
        act = menu.addAction("Switch to the classic FreeCAD interface")
        act.triggered.connect(lambda: QtCore.QTimer.singleShot(0, lambda: set_enabled(False)))
        popup_menu(menu, button.mapToGlobal(QtCore.QPoint(0, button.height())))

    def show_recent_menu(self, pos):
        menu = self._menu()
        try:
            actions = Gui.Command.get("Std_RecentFiles").getAction()
        except Exception:
            actions = []
        for action in actions:
            if isinstance(action, QtGui.QAction) and action.isVisible() and action.text():
                menu.addAction(action)
        if menu.actions():
            menu.addSeparator()
        open_act = menu.addAction(icons.family("STANDARD_OPEN"), "Open...")
        open_act.triggered.connect(lambda: Gui.runCommand("Std_Open", 0))
        popup_menu(menu, pos)

    # -- the window buttons left of Close ------------------------------------------------
    # FreeCAD starts maximized, so Qt's "normal" size is often the whole screen too and
    # Restore Down then changes nothing (Ati 03:07Z: "the two buttons ... don't seem to do
    # anything"). The shell keeps its own normal size: the last one that did not fill the
    # screen, else three quarters of it, centred, as Windows gives a window that never had one.
    def _area(self):
        mw = self.window
        screen = mw.screen() if hasattr(mw, "screen") else QtGui.QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _fills(self, geo, area=None):
        area = area or self._area()
        return geo.width() >= area.width() - 16 and geo.height() >= area.height() - 16

    def _normal_geometry(self):
        area = self._area()
        geo = getattr(self, "_normal_geo", None)
        if geo is None or self._fills(geo, area) or not area.intersects(geo):
            w, h = int(area.width() * 0.75), int(area.height() * 0.75)
            geo = QtCore.QRect(area.x() + (area.width() - w) // 2, area.y() + (area.height() - h) // 2, w, h)
        return QtCore.QRect(geo)

    def remember_normal(self):
        mw = self.window
        if not mw.isMaximized() and not mw.isFullScreen() and not self._fills(mw.geometry()):
            self._normal_geo = QtCore.QRect(mw.geometry())

    def restore_down(self, then=None):
        """Out of maximized to the shell's normal size; then(geometry) runs once it is there."""
        mw = self.window
        geo = self._normal_geometry()
        mw.showNormal()

        def place():
            mw.setGeometry(geo)
            if then is not None:
                then(geo)
            self.qat_relayout()
        # Windows applies showNormal's own size a moment later: place after it
        QtCore.QTimer.singleShot(60, place)

    def span_rect(self):
        ""


        mw = self.window
        here = self._area()
        others = []
        for scr in QtGui.QGuiApplication.screens():
            g = scr.availableGeometry()
            if g != here:
                others.append(g)
        if not others:
            return None
        def gap(g):        # the display next to this one: touching edges first, then the nearest
            return min(abs(g.left() - here.right() - 1), abs(here.left() - g.right() - 1),
                       abs(g.top() - here.bottom() - 1), abs(here.top() - g.bottom() - 1))
        other = sorted(others, key=gap)[0]
        side_by_side = other.left() > here.right() - 8 or other.right() < here.left() + 8
        if side_by_side:
            top = max(here.top(), other.top())
            bottom = min(here.bottom(), other.bottom())
            left = min(here.left(), other.left())
            right = max(here.right(), other.right())
        else:
            left = max(here.left(), other.left())
            right = min(here.right(), other.right())
            top = min(here.top(), other.top())
            bottom = max(here.bottom(), other.bottom())
        return QtCore.QRect(left, top, right - left + 1, bottom - top + 1)

    def spanned(self):
        r = self.span_rect()
        g = self.window.geometry()
        return r is not None and not self.window.isMaximized() and abs(g.x() - r.x()) <= 8 and abs(g.y() - r.y()) <= 8 \
            and abs(g.width() - r.width()) <= 16 and abs(g.height() - r.height()) <= 16

    def span_displays(self):
        ""

        mw = self.window
        rect = self.span_rect()
        if rect is None:
            self.toggle_maximized()
            return
        if self.spanned():
            back = getattr(self, "_before_span", None) or self._normal_geometry()
            self._before_span = None
            mw.setGeometry(back)
            self.qat_relayout()
            return
        if not mw.isMaximized() and not self._fills(mw.geometry()):
            self._before_span = QtCore.QRect(mw.geometry())
        else:
            self._before_span = None
        def place():
            mw.setGeometry(rect)
            self.qat_relayout()
        if mw.isMaximized() or mw.isFullScreen():
            mw.showNormal()
            QtCore.QTimer.singleShot(60, place)     # Windows applies showNormal's own size a moment later
        else:
            place()

    span_height = span_displays     # the old name (ribbon.py connects it)

    def toggle_maximized(self):
        mw = self.window
        if mw.isMaximized() or self._fills(mw.geometry()):
            self.restore_down()
        else:
            self.remember_normal()
            mw.showMaximized()

    def frame_active(self):
        return self.frame.active

    def qat_relayout(self):
        if alive(getattr(self, "topbar", None)):
            self.topbar.qat.relayout()
            self.topbar.qat.update_maximize_icon()      # spandisp-1127: Span Displays / Restore tooltip

    # ------------------------------------------------------------------ pages
    def _build_pages(self):
        pages = [ribbon.RibbonPage(self, title, spec) for title, spec in catalog.TABS]
        self.topbar.set_pages(pages, keep_title="Features")
        self._native_sig = None
        self._update_native_page(force=True)

    def page_shown(self, page):
        if not self._modules_loaded and page.title in self.LAZY_PAGES:
            self.ensure_command_modules()
        for b in page.buttons():
            b.binding.resolve()
            b.binding.update_state()

    def _native_toolbars(self):
        mw = self.window
        bars = []
        for tb in mw.findChildren(QtWidgets.QToolBar):
            if _class(tb) != "Gui::ToolBar" or tb.parentWidget() is not mw:
                continue
            if not tb.toggleViewAction().isVisible():
                continue
            bars.append(tb)
        bars.sort(key=lambda t: (t.geometry().y(), t.geometry().x()))
        return bars

    def _update_native_page(self, force=False):
        ""





        try:
            wb = Gui.activeWorkbench()
            name = wb.name()
            title = getattr(wb, "MenuText", "") or name
        except Exception:
            name, title = "", None
        if name in NATIVE_COVERED:
            bars = []
        else:
            bars = self._native_toolbars()
        sig = (title, tuple(tb.objectName() for tb in bars))
        if not force and sig == self._native_sig:
            return
        self._native_sig = sig
        current = self.topbar.current_page()
        current_title = current.title if current is not None else None
        if self._native_page is not None and alive(self._native_page):
            self.topbar.remove_page(self._native_page)
        self._native_page = None
        spec = []
        for tb in bars:
            actions = [a for a in tb.actions() if not a.isSeparator() and a.isVisible()
                       and not isinstance(a, QtWidgets.QWidgetAction)]
            if not actions:
                continue
            if spec:
                spec.append(("sep",))
            spec.append(("native", actions))
        if title and spec:
            page = ribbon.RibbonPage(self, title, spec)
            self._native_page = page
            self.topbar.add_page(page)
        if current_title is not None and not self.topbar.select(current_title):
            self.topbar.select("Features")

    # ------------------------------------------------------------------ toolbars
    def _hide_native_toolbars(self):
        mw = self.window
        for tb in mw.findChildren(QtWidgets.QToolBar):
            self._watch_toolbar(tb)

    def _watch_toolbar(self, tb):
        if _class(tb) != "Gui::ToolBar" or tb.parentWidget() is not self.window:
            return
        if tb not in self._toolbar_filtered:
            tb.installEventFilter(self)
            self._toolbar_filtered.append(tb)
        if tb.isVisible():
            tb.hide()

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter1016(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter shell.py: %s\n" % exc)
            return False

    def _fw_filter1016(self, obj, event):
        t = event.type()
        if obj is self.window:
            if t == QtCore.QEvent.ChildAdded:
                child = event.child()
                if isinstance(child, QtWidgets.QToolBar):
                    QtCore.QTimer.singleShot(0, lambda c=child: alive(c) and self._watch_toolbar(c))
            elif t == QtCore.QEvent.WindowStateChange:
                if alive(getattr(self, "topbar", None)):
                    self.topbar.qat.update_maximize_icon()
            elif t == QtCore.QEvent.Close and self.enabled and not self._close_pending:
                self._stock_toolbars_for_close()
            return False
        if self._close_pending:
            return False     # swtoolbars-1120: FreeCAD is saving its toolbars as they are without the look
        if t == QtCore.QEvent.Show and isinstance(obj, QtWidgets.QToolBar) and self.enabled:
            QtCore.QTimer.singleShot(0, lambda o=obj: alive(o) and o.isVisible() and o.hide())
        return False

    # swtoolbars-1120: the look hides FreeCAD's toolbars only while it runs. FreeCAD saves every
    # toolbar's state (and the window layout) when its window closes, so just before that the stock
    # toolbars are shown again as FreeCAD had them without the look (the stock settings baseline). A
    # FreeCAD that starts without the add-on (folder deleted, switched off in the Addon Manager) then
    # has its toolbars; with the add-on they are hidden again at start. Nothing is painted meanwhile.
    _close_pending = False
    _close_level = 0

    def _stock_toolbars_for_close(self):
        mw = self.window
        try:
            from . import stockrestore
            data = stockrestore.load()
            if data is None:
                return
            self._close_pending = True
            try:
                self._close_level = QtCore.QThread.currentThread().loopLevel()
            except Exception:
                self._close_level = 1
            mw.setUpdatesEnabled(False)
            stockrestore._show_stock_toolbars(data)
        except Exception as exc:
            _fw_log("shell.py:closebars", exc)
        if self._close_pending:
            QtCore.QTimer.singleShot(0, self._close_settled)

    def _close_settled(self):
        """Back in the event loop that got the close: the window closed, or the close was cancelled
        (a Save prompt answered Cancel, a PropertyManager still open): then the look again."""
        mw = self.window
        if not alive(mw):
            return
        try:
            nested = QtCore.QThread.currentThread().loopLevel() > self._close_level
        except Exception:
            nested = False
        if nested or QtWidgets.QApplication.activeModalWidget() is not None:
            QtCore.QTimer.singleShot(50, self._close_settled)
            return
        self._close_pending = False
        if mw.isVisible() and self.enabled:
            self._hide_native_toolbars()
        mw.setUpdatesEnabled(True)

    # ------------------------------------------------------------------ enable
    def enable(self):
        if self.enabled:
            return
        mw = self.window
        self._ensure_workbench()
        self._state = mw.saveState()
        self._qss = mw.styleSheet()
        self._first_toolbar = None
        self.enabled = True
        try:
            self._install()
        except Exception:
            import traceback
            App.Console.PrintError("FreeCAD: could not install:\n%s\n" % traceback.format_exc())
            self.disable()
            return
        self._build_pages()
        self.timer.start()
        self.watch.start()
        self.refresh()
        App.Console.PrintLog("FreeCAD: enabled\n")

    LAZY_PAGES = ("Surfaces", "Mesh Modeling", "Evaluate", "Direct Editing", "Data Migration", "Tools")
    _modules_loaded = False

    def _load_command_modules(self):
        """The Surfaces tab, Curves, Split and Search Commands use commands of FreeCAD's Part,
        Surface, Mesh and Spreadsheet modules, which exist only once those are loaded; Part's
        Python commands (Slice, Boolean fragments) are added as its workbench adds them.
        Loading them took ~1 s of the start-up, so enable() defers it: a timer after the window
        is up, or earlier when a page that needs them is shown or Search Commands is opened
        (ensure_command_modules)."""
        if self._modules_loaded:
            return
        self._modules_loaded = True
        for name in ("PartGui", "SurfaceGui", "MeshGui", "MeshPartGui", "SpreadsheetGui"):
            try:
                __import__(name)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: %s not loaded: %s\n" % (name, error))
        if "Part_SliceApart" not in Gui.listCommands():
            try:
                import BOPTools
                BOPTools.importAll()
                BOPTools.addCommands()
            except Exception as error:
                App.Console.PrintLog("FreeCAD: Part's split commands not added: %s\n" % error)

    def ensure_command_modules(self):
        """Loads the lazily loaded modules now (if not yet) and re-resolves the buttons that waited."""
        if self._modules_loaded or not self.enabled:
            return False
        self._load_command_modules()
        try:
            page = self.topbar.current_page()
            if page is not None:
                self.page_shown(page)
            self.topbar.qat.relayout()
            if self.search is not None:
                self.search._index = None
        except Exception as _fw_err:
            _fw_log("shell.py:1317", _fw_err)
        return True

    def _install(self):
        mw = self.window
        try:
            import PartGui  # noqa: F401  (Part's commands are on every tab; the rest wait)
        except Exception as _fw_err:
            _fw_log("shell.py:1325", _fw_err)
        QtCore.QTimer.singleShot(1500, self.ensure_command_modules)
        style.mark_applied()
        style.apply_settings()
        style.apply_palette()
        QtCore.QTimer.singleShot(1500, keys.drop_group_copies)

        # top: quick access + CommandManager + tabs, alone on the first toolbar row
        self.top_tb = QtWidgets.QToolBar("CommandManager", mw)
        self.top_tb.setObjectName("SWTopToolBar")
        self._plain_toolbar(self.top_tb)
        self.topbar = ribbon.TopBar(self)
        self.top_tb.addWidget(self.topbar)
        first = None
        for tb in mw.findChildren(QtWidgets.QToolBar):
            if tb is self.top_tb or tb.parentWidget() is not mw or mw.toolBarArea(tb) != Qt.TopToolBarArea:
                continue
            if tb.isHidden():
                continue
            g = tb.geometry()
            if first is None or (g.y(), g.x()) < (first.geometry().y(), first.geometry().x()):
                first = tb
        if first is not None:
            mw.insertToolBar(first, self.top_tb)
            mw.insertToolBarBreak(first)
            self._first_toolbar = first
        else:
            mw.addToolBar(Qt.TopToolBarArea, self.top_tb)

        # left: FeatureManager pane holding the native panels
        self.left_dock = QtWidgets.QDockWidget("FeatureManager", mw)
        self.left_dock.setObjectName("SWLeftDock")
        self.left_dock.setTitleBarWidget(QtWidgets.QWidget(self.left_dock))
        self.left_dock.setFeatures(QtWidgets.QDockWidget.NoDockWidgetFeatures)
        self.left_dock.toggleViewAction().setVisible(False)
        self.left_pane = leftpane.LeftPane(self)
        self.left_dock.setWidget(self.left_pane)
        mw.addDockWidget(Qt.LeftDockWidgetArea, self.left_dock)
        self._leave_overlay()
        self.left_pane.adopt()

        # wide enough for a PropertyManager, so opening a feature does not make it jump.
        mw.resizeDocks([self.left_dock], [scaled(getattr(leftpane, "start_width", lambda: leftpane.PANE_WIDTH)())], Qt.Horizontal)
        getattr(leftpane, "watch_width", lambda d: None)(self.left_dock)    # pkg445: pane width kept between sessions

        # bottom: model tabs across the full width
        self.bottom_tb = QtWidgets.QToolBar("Model tabs", mw)
        self.bottom_tb.setObjectName("SWBottomToolBar")
        self._plain_toolbar(self.bottom_tb)
        self.model_tabs = chrome.ModelTabs(self)
        self.model_tabs.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.bottom_tb.addWidget(self.model_tabs)
        # a bottom row already there (the Selection Filter toolbar, kept while the look was off)
        # stays its own row under the tabs
        if any(mw.toolBarArea(tb) == Qt.BottomToolBarArea and tb is not self.bottom_tb
               for tb in mw.findChildren(QtWidgets.QToolBar)):
            mw.addToolBarBreak(Qt.BottomToolBarArea)
        mw.addToolBar(Qt.BottomToolBarArea, self.bottom_tb)



        self.status_info = chrome.StatusInfo()
        mw.statusBar().addPermanentWidget(self.status_info)
        self.status_units = chrome.UnitsButton()
        mw.statusBar().addPermanentWidget(self.status_units)

        self.status_rebuild = chrome.RebuildIndicator()
        mw.statusBar().addPermanentWidget(self.status_rebuild)
        self._status_hidden = []
        self._hide_status_extras()

        mb = mw.menuBar()
        self._menubar_heights = (mb.minimumHeight(), mb.maximumHeight())
        mb.setMinimumHeight(0)
        mb.setMaximumHeight(0)

        self._hide_native_toolbars()
        mw.installEventFilter(self)
        mw.setStyleSheet((self._qss or "") + style.qss())
        style.signals.theme_changed.connect(self._retheme)
        self._mdi_bar = mw.findChild(QtWidgets.QTabBar, "mdiAreaTabBar")
        if self._mdi_bar is not None:
            self._mdi_bar.hide()

        self.overlay = chrome.ViewOverlay(self)

        try:
            from . import tabstrip
            QtCore.QTimer.singleShot(0, lambda: tabstrip.install(self))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: tab row on the graphics area: %s\n" % error)

        try:
            from . import docbuttons
            QtCore.QTimer.singleShot(0, lambda: docbuttons.install(self))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: document window buttons: %s\n" % error)

        self.flyout = flyouttree.FlyoutTree(self)


        # before the rollback bar, which goes on it
        self.feature_manager = fmtree.FeatureManager(self)
        self.rollback = rollbackbar.RollbackBar(self)

        # its pointer is asked first
        self.freeze = freezeview.FreezeBar(self)

        self.context = contextbar.ContextBar(self)

        self.gestures = gestures.Gestures(self)

        # on the gestures' right-button replay
        try:
            from . import sketchtoolmenu
            sketchtoolmenu.install(self)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: sketch tool menu not added: %s\n" % error)

        self.viewkeys = viewkeys.ViewKeys(self)
        self.view_selector = viewselector.ViewSelector(self)
        self.orientation = orientation.OrientationBox(self)
        self.view_selector.hidden.connect(self.orientation.selector_hidden)
        self.orientation.selector_toggled.connect(self._selector_toggled)

        self.pencil = pencil.PencilCursor(self)
        # the picked plane shown in the 3D view
        self.planes = planes.PickedPlane(self)
        # "(-) Sketch1" / "(+) Sketch1" in the feature tree
        self.sketch_status = sketchstatus.SketchStatus(self)

        self.relations_pm = relationspm.RelationsPM(self)

        self.breadcrumbs = breadcrumbs.Breadcrumbs(self)

        self.face_hover = facehover.FaceHover(self)

        from . import multipick
        self.multi_pick = multipick.MultiPick(self)

        try:
            from . import flatselect
            self.flat_select = flatselect.FlatSelection(self)
        except Exception as error:
            self.flat_select = None
            App.Console.PrintWarning("FreeCAD: flat selection fill not set up: %s\n" % error)

        try:
            from . import scenebg
            self.scene_background = scenebg.SceneBackground(self)
        except Exception as error:
            self.scene_background = None
            App.Console.PrintWarning("FreeCAD: scene background not set up: %s\n" % error)
        self.sketch_origin = sketchorigin.SketchOrigin(self)
        # a file opened and not edited closes without asking to save it
        self.clean_open = cleanopen.CleanOpen(self)

        try:
            watcher = sketchexit.Watcher()
            Gui.addDocumentObserver(watcher)
            self.sketch_exit = watcher
        except Exception as error:
            self.sketch_exit = None
            App.Console.PrintWarning("FreeCAD: exit sketch without saving is off: %s\n" % error)
        if paths.params().GetBool("Frameless", True):
            self.frame.enable()
        self.topbar.qat.set_frameless_controls(self.frame.active)
        self.topbar.qat.update_maximize_icon()

        for owner, name, slot in ((mw, "workbenchActivated", self._workbench_changed),
                                  (mw, "mainWindowClosed", self._closing)):
            signal = getattr(owner, name, None)
            if signal is not None:
                signal.connect(slot)
                self._signals.append((signal, slot))

    def _leave_overlay(self):
        ""


        mw = self.window
        if not any(_in_overlay(d, mw) for d in mw.findChildren(QtWidgets.QDockWidget)):
            return
        try:
            # With any panel in overlay mode this command takes every panel out.
            Gui.runCommand("Std_DockOverlayAll", 0)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: panels left over the 3D view: %s\n" % error)
        left = [d.objectName() for d in mw.findChildren(QtWidgets.QDockWidget) if _in_overlay(d, mw)]
        if left:
            App.Console.PrintWarning("FreeCAD: still over the 3D view: %s\n" % ", ".join(left))

    def view_widget(self):
        """The active 3D view's GL widget, which takes the keys while sketching."""
        mdi = self.window.findChild(QtWidgets.QMdiArea)
        sub = (mdi.activeSubWindow() or mdi.currentSubWindow()) if mdi is not None else None
        view = sub.widget() if sub is not None else None
        if view is None:
            return None
        for w in view.findChildren(QtWidgets.QWidget):
            if _class(w) == "Gui::View3DInventorViewer":
                return w
        return view

    def _plain_toolbar(self, tb):
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setContextMenuPolicy(Qt.PreventContextMenu)
        tb.toggleViewAction().setVisible(False)
        tb.layout().setContentsMargins(0, 0, 0, 0)
        tb.layout().setSpacing(0)

    def _ensure_workbench(self):
        try:
            name = Gui.activeWorkbench().name()
        except Exception:
            name = ""
        if name in ("", "NoneWorkbench", "StartWorkbench"):
            try:
                Gui.activateWorkbench("PartDesignWorkbench")
            except Exception as _fw_err:
                _fw_log("shell.py:1522", _fw_err)

    # ------------------------------------------------------------------ disable
    def disable(self, closing=False):
        if not self.enabled:
            return
        self.enabled = False
        mw = self.window
        self.timer.stop()
        self.watch.stop()
        steps = (self._undo_signals, self._undo_filters, self._undo_gestures, self._undo_orientation, self._undo_viewkeys,
                 self._undo_pencil,
                 self._undo_planes, self._undo_sketch_status, self._undo_relations_pm, self._undo_breadcrumbs, self._undo_face_hover, self._undo_sketch_origin, self._undo_feature_manager, self._undo_clean_open,
                 self._undo_sketch_exit,
                 self._undo_rollback, self._undo_flyout, self._undo_context,
                 self._undo_overlay, self._undo_left, self._undo_toolbars, self._undo_status, self._undo_menubar,
                 self._undo_style)
        if closing:
            # FreeCAD is closing its main window (mainWindowClosed): release the hooks, observers and
            # filters and leave every widget to Qt. Rebuilding the stock window inside closeEvent
            # (toolbars, docks, status bar, menu bar, style sheet) ended 112 of 140 PC check runs in
            # an access violation after "disabled", before FreeCAD saved its parameters.
            steps = (self._undo_signals, self._undo_filters, self._undo_sketch_exit, self._undo_face_hover,
                     self._undo_clean_open)
        for step in steps:
            try:
                step()
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: %s: %s\n" % (step.__name__, error))
        try:
            style.restore_settings()
            from . import swkeys        # kbpage-1126: FreeCAD's V, F (fit all) and its other key sequences
            swkeys.restore_sequences()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: settings not restored: %s\n" % error)
        if closing:
            try:
                from . import events
                events.unregister("shell")
            except Exception as _fw_err:
                _fw_log("shell.py:1560", _fw_err)
            self.frame.disable(reframe=False)
            self.bindings = {}
            App.Console.PrintLog("FreeCAD: disabled (closing: widgets left to Qt)\n")
            return
        try:
            mw.restoreState(self._state)
            prefs = App.ParamGet(style.TOOLBARS)
            for tb in mw.findChildren(QtWidgets.QToolBar):
                if _class(tb) == "Gui::ToolBar" and tb.parentWidget() is mw and tb.toggleViewAction().isVisible():
                    tb.setVisible(prefs.GetBool(tb.objectName(), True))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: toolbars not restored: %s\n" % error)
        self.frame.disable(reframe=not closing)
        self.bindings = {}
        self._native_page = None
        self._was_dialog = False
        self._was_sketch = None
        App.Console.PrintLog("FreeCAD: disabled\n")

    def _undo_signals(self):
        for signal, slot in self._signals:
            try:
                signal.disconnect(slot)
            except Exception as _fw_err:
                _fw_log("shell.py:1585", _fw_err)
        self._signals = []

    def _undo_filters(self):
        self.window.removeEventFilter(self)
        for tb in self._toolbar_filtered:
            if alive(tb):
                tb.removeEventFilter(self)
        self._toolbar_filtered = []
        if self.search is not None:
            try:
                self.search.remove()
            except Exception as _fw_err:
                _fw_log("shell.py:1598", _fw_err)
            self.search = None

    def _undo_gestures(self):
        try:
            from . import sketchtoolmenu
            sketchtoolmenu.remove()
        except Exception as _fw_err:
            _fw_log("shell.py:1606", _fw_err)
        g = getattr(self, "gestures", None)
        if g is not None:
            g.remove()
            g.deleteLater()
        self.gestures = None

    def _undo_orientation(self):
        for name in ("view_selector", "orientation"):
            obj = getattr(self, name, None)
            if obj is not None:
                try:
                    obj.remove()
                except Exception as _fw_err:
                    _fw_log("shell.py:1620", _fw_err)
                setattr(self, name, None)

    def _undo_viewkeys(self):
        k = getattr(self, "viewkeys", None)
        if k is not None:
            k.remove()
            k.deleteLater()
        self.viewkeys = None

    def _undo_pencil(self):
        p = getattr(self, "pencil", None)
        if p is not None:
            p.remove()
            p.deleteLater()
        self.pencil = None

    def _undo_planes(self):
        p = getattr(self, "planes", None)
        if p is not None:
            p.remove()
            p.deleteLater()
        self.planes = None

    def _undo_sketch_status(self):
        p = getattr(self, "sketch_status", None)
        if p is not None:
            p.remove()
            p.deleteLater()
        self.sketch_status = None

    def _undo_relations_pm(self):
        p = getattr(self, "relations_pm", None)
        if p is not None:
            p.remove()
            p.deleteLater()
        self.relations_pm = None

    def _undo_breadcrumbs(self):
        p = getattr(self, "breadcrumbs", None)
        if p is not None:
            p.remove()
            p.deleteLater()
        self.breadcrumbs = None

    def _undo_sketch_origin(self):
        p = getattr(self, "sketch_origin", None)
        if p is not None:
            p.remove()
            p.deleteLater()
        self.sketch_origin = None

    def _undo_clean_open(self):
        p = getattr(self, "clean_open", None)
        if p is not None:
            p.remove()
            p.deleteLater()
        self.clean_open = None

    def _undo_feature_manager(self):
        p = getattr(self, "feature_manager", None)
        if p is not None:
            p.remove()
            p.deleteLater()
        self.feature_manager = None

    def _undo_face_hover(self):
        flat = getattr(self, "flat_select", None)
        if flat is not None:
            flat.remove()
            flat.deleteLater()
        self.flat_select = None
        bg = getattr(self, "scene_background", None)
        if bg is not None:
            bg.remove()
            bg.deleteLater()
        self.scene_background = None
        p = getattr(self, "face_hover", None)
        if p is not None:
            p.remove()
            p.deleteLater()
        self.face_hover = None
        p = getattr(self, "multi_pick", None)
        if p is not None:
            p.remove()
            p.deleteLater()
        self.multi_pick = None

    def _undo_sketch_exit(self):
        watcher = getattr(self, "sketch_exit", None)
        if watcher is not None:
            Gui.removeDocumentObserver(watcher)
        self.sketch_exit = None

    def _undo_rollback(self):
        freeze = getattr(self, "freeze", None)
        if freeze is not None:
            freeze.remove()
            freeze.deleteLater()
        self.freeze = None
        bar = getattr(self, "rollback", None)
        if bar is not None:
            bar.remove()
            bar.deleteLater()
        self.rollback = None

    def _undo_flyout(self):
        # first of the panes: FreeCAD's tree must be home before the left pane gives its panels back
        flyout = getattr(self, "flyout", None)
        if flyout is not None and alive(flyout):
            flyout.remove()
        self.flyout = None

    def _undo_context(self):
        context = getattr(self, "context", None)
        if context is not None:
            context.remove()
            context.deleteLater()
        self.context = None

    def _undo_overlay(self):
        overlay = getattr(self, "overlay", None)
        if overlay is not None:
            overlay.remove()
            overlay.deleteLater()
        self.overlay = None

    def _undo_left(self):
        pane = getattr(self, "left_pane", None)
        if pane is not None and alive(pane):
            self._tool_only(False)
            page = pane.pages.get("Tasks")
            pm = _propertymanager()
            if page is not None and pm is not None and alive(page):
                try:
                    pm.unstyle(page)
                except Exception as error:
                    App.Console.PrintWarning("FreeCAD: PropertyManager look not removed: %s\n" % error)
            pane.release()
        dock = getattr(self, "left_dock", None)
        if dock is not None and alive(dock):
            self.window.removeDockWidget(dock)
            dock.deleteLater()
        self.left_pane = self.left_dock = None

    def _undo_toolbars(self):
        mw = self.window
        try:
            from . import tabstrip
            tabstrip.release(self)          # the tab row floats on the main window: home before the CommandManager goes
        except Exception as _fw_err:
            _fw_log("shell.py:1756", _fw_err)
        for name in ("top_tb", "bottom_tb"):
            tb = getattr(self, name, None)
            if tb is not None and alive(tb):
                mw.removeToolBar(tb)
                tb.deleteLater()
            setattr(self, name, None)
        first = getattr(self, "_first_toolbar", None)
        if first is not None and alive(first):
            mw.removeToolBarBreak(first)
        self._first_toolbar = None
        self.topbar = None

    def _hide_status_extras(self):
        ""

        for widget in chrome.freecad_status_items(self.window.statusBar()):
            if widget not in self._status_hidden:
                self._status_hidden.append(widget)
                widget.hide()

    def _undo_status(self):
        for name in ("status_info", "status_units", "status_rebuild"):
            widget = getattr(self, name, None)
            if widget is not None and alive(widget):
                self.window.statusBar().removeWidget(widget)
                widget.deleteLater()
            setattr(self, name, None)
        for widget in getattr(self, "_status_hidden", []):
            if alive(widget):
                widget.show()
        self._status_hidden = []

    def _undo_menubar(self):
        heights = getattr(self, "_menubar_heights", None)
        if heights is not None:
            mb = self.window.menuBar()
            mb.setMinimumHeight(heights[0])
            mb.setMaximumHeight(heights[1])
        self._menubar_heights = None

    def _retheme(self, name=None):
        """A theme change (style.set_theme): the main window's style sheet again, then every widget of
        the look takes its new colours: those with a retheme() re-apply their style sheets, the rest
        repaint from the tokens."""
        if not self.enabled:
            return
        mw = self.window
        mw.setStyleSheet((self._qss or "") + style.qss())
        for w in mw.findChildren(QtWidgets.QWidget):
            if not alive(w):
                continue
            hook = getattr(w, "retheme", None)
            try:
                if callable(hook):
                    hook()
                # item views shadow QWidget.update() with update(index): call the widget's one
                QtWidgets.QWidget.update(w)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: retheme %s: %s\n" % (w.objectName(), error))
        if self.view_selector is not None:
            self.view_selector.retheme()
        search = getattr(self, "search", None)
        if search is not None:
            search.retheme()

    def _undo_style(self):
        try:
            style.signals.theme_changed.disconnect(self._retheme)
        except (RuntimeError, TypeError) as _fw_err:
            _fw_log("shell.py:1826", _fw_err)
        style.restore_palette()
        self.window.setStyleSheet(self._qss or "")
        bar = getattr(self, "_mdi_bar", None)
        if bar is not None and alive(bar):
            bar.show()
        self._mdi_bar = None

    def _closing(self):
        self.disable(closing=True)

    # ------------------------------------------------------------------ live updates
    def _workbench_changed(self, name=None):
        QtCore.QTimer.singleShot(0, self._after_workbench)

    def _after_workbench(self):
        if not self.enabled:
            return
        if self.viewkeys is not None:
            self.viewkeys.last.hook()
        self._hide_native_toolbars()
        self.left_pane.restore_user_page()
        self._update_native_page()
        for b in self.bindings.values():
            b.resolve()
            b.update_state()

    def refresh(self):
        if not self.enabled:
            return
        if _docs_busy():      # busyrefresh-1127: no passes while a document opens or rebuilds
            return
        self._tick += 1
        page = self.topbar.current_page()
        if page is not None:
            for b in page.buttons():
                b.binding.poll()
        for b in self.topbar.qat.left:
            b.binding.poll()
        if alive(self.overlay.hud):
            for b in self.overlay.hud.buttons:
                b.binding.poll()
        hud_sheet = getattr(self.overlay, "hud_sheet", None)
        if hud_sheet is not None and alive(hud_sheet) and hud_sheet.isVisible():
            for b in hud_sheet.buttons:
                b.binding.poll()
        self.model_tabs.refresh()
        self.status_info.refresh()
        self.status_units.refresh()
        self.topbar.qat.set_document(chrome.document_title())
        if self._tick % 3 == 0:
            self._hide_status_extras()
            try:
                from . import nodocstate
                nodocstate.sync(self)
            except Exception as _fw_err:
                _fw_log("shell.py:nodocstate", _fw_err)
            self._update_native_page()
            self._fix_document_icons()
            self.overlay.attach()
            if self.context is not None:
                self.context.attach()
            if self.gestures is not None:
                self.gestures.attach()
            if self.viewkeys is not None:
                self.viewkeys.attach()
            if self.pencil is not None:
                self.pencil.attach()
            if self.planes is not None:
                self.planes.soon()
            if self.sketch_status is not None:
                self.sketch_status.soon()
            if self.relations_pm is not None:
                self.relations_pm.soon()
            if self.breadcrumbs is not None:
                self.breadcrumbs.soon()

    def _watch(self):
        if style._pending_theme or style._pending_style:
            try:
                style.apply_pending()
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: Qt style: %s\n" % error)
        if not self.enabled:
            return
        self._track_dialog()
        self._track_sketch()
        self.left_pane._refresh_title_bars()
        self.left_pane.settle_width()
        self._sample_view()

    def in_sketch(self):
        try:
            gdoc = Gui.ActiveDocument
            edit = gdoc.getInEdit() if gdoc is not None else None
            return edit is not None and editobj.type_id(edit) == "Sketcher::SketchObject"
        except Exception as _fw_err:
            _fw_log("shell.py:1951", _fw_err)
            return False

    def _sketch_tool(self):
        """FreeCAD's 'Tool Parameters' box in the sketch dialog; FreeCAD shows it
        only while a sketch tool with options runs."""
        box = self._sketch_tool_box
        if box is not None and alive(box):
            return box
        self._sketch_tool_box = None
        page = self.left_pane.pages.get("Tasks")
        if page is None:
            return None
        for w in page.findChildren(QtWidgets.QWidget):
            if _class(w) == "SketcherGui::TaskSketcherTool":
                self._sketch_tool_box = w
                return w
        return None

    def tasks_wanted(self):
        ""


        try:
            if not Gui.Control.activeDialog():
                return False
        except Exception as _fw_err:
            _fw_log("shell.py:1978", _fw_err)
            return False
        if not self.in_sketch():
            return True
        box = self._sketch_tool()
        return box is not None and not box.isHidden()

    @staticmethod
    def _auto_show_pm():
        try:
            from . import optionsextras3      # Options > General > Auto-show PropertyManager
            return optionsextras3.auto_show_pm()
        except Exception:
            return True

    def _track_dialog(self):
        want = self.tasks_wanted()
        if want and not self._was_dialog:
            if self.in_sketch():
                self._tool_only(True)
            if self._auto_show_pm():
                self.left_pane.select_name("Tasks")
            QtCore.QTimer.singleShot(50, self._style_task_buttons)
        elif not want and self._was_dialog:
            self.left_pane.dialog_closed()
            self._tool_only(False)
        self._was_dialog = want

    def _tool_only(self, on):
        ""




        page = self.left_pane.pages.get("Tasks") if self.left_pane is not None else None
        if on:
            if page is None or not alive(page):
                return
            for w in page.findChildren(QtWidgets.QWidget):
                if _class(w) in SKETCH_EXTRAS and not w.isHidden():
                    w.hide()
                    self._tool_hidden.append(w)
        elif self._tool_hidden:
            for w in self._tool_hidden:
                if alive(w):
                    w.show()
            self._tool_hidden = []
        else:
            return
        view = page.widget() if page is not None and alive(page) and hasattr(page, "widget") else None
        if view is not None and alive(view) and _class(view).endswith("TaskView"):

            # (PM pkg90 makes the pages fit); uncapped, the pane grew 300 -> 365 over a session and never shrank
            view.setMinimumWidth(min(view.minimumSizeHint().width(), scaled(leftpane.PANE_WIDTH)))

    def _track_sketch(self):
        in_sketch = self.in_sketch()
        if in_sketch == self._was_sketch:
            return
        first = self._was_sketch is None
        self._was_sketch = in_sketch
        sketch_buttons = []
        for page in self.topbar.pages:
            if page.title not in ("Sketch", "Sketch Ink"):      # the Sketch Ink tab starts with it too
                continue
            if hasattr(page, "ensure_built"):
                page.ensure_built()     # look-audit skflow-1120: a tab never shown yet has no buttons to swap
            for b in page.buttons():
                if b.binding.cmd.key in ("Sketch", "ExitSketch"):
                    b._fw_page_title = page.title       # skflyout-1127: each tab keeps its own flyout
                    sketch_buttons.append(b)
        for sketch_button in sketch_buttons:
            target = "ExitSketch" if in_sketch else "Sketch"
            if sketch_button.binding.cmd.key != target:
                self.rebind(sketch_button, target)
                sketch_button._lines = self.binding(target).cmd.caption.split("\n")
                sketch_button.flyout_keys = () if in_sketch else (
                    ("Sketch", "Sketch3D", "EditSketch") if getattr(sketch_button, "_fw_page_title", "") == "Sketch Ink"
                    else ("Sketch", "Sketch3D", "Sketch3DOnPlane"))
                sketch_button.resize(sketch_button.sizeHint())
                sketch_button.update()
                self.topbar._layout_pages()
        if not first:
            if in_sketch:
                self.topbar.select("Sketch")
            else:
                # sketchexit-1126: out of the sketch the row goes back to Features in a part, and to the
                # document's first tab (Assembly, Drawing) where there is no Features tab
                titles = [p.title for p in self.topbar.pages]
                self.topbar.select("Features" if "Features" in titles else (titles[0] if titles else "Features"))

    def _style_task_buttons(self):
        page = self.left_pane.pages.get("Tasks") if self.left_pane is not None else None
        if page is None:
            return
        pm = _propertymanager()
        if pm is not None:
            try:
                pm.style(page)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: PropertyManager look: %s\n" % error)
        ok_icon = icons.family("CHECK_MARK")
        cancel_icon = icons.family("STANDARD_CANCEL")
        for box in page.findChildren(QtWidgets.QDialogButtonBox):
            for button in box.buttons():
                role = box.buttonRole(button)
                if role == QtWidgets.QDialogButtonBox.AcceptRole and not ok_icon.isNull():
                    button.setIcon(ok_icon)
                elif role == QtWidgets.QDialogButtonBox.RejectRole and not cancel_icon.isNull():
                    button.setIcon(cancel_icon)

    def _fix_document_icons(self):
        tree = self.left_pane.tree_widget()
        icon = _flat_icon(icons.family("PART"))
        if tree is None or icon.isNull():
            return
        if not icon.availableSizes():
            # look-audit docicon-1120: without the icon pack this is an SVG file icon; setting it on FreeCAD's
            # tree item made Qt paint into a null pixmap on every document open, and the notification area
            # showed "QPainter ... Painter not active" warnings over the view. A pixmap copy does not.
            cached = getattr(self, "_doc_icon_pixmaps", None)
            if cached is None or cached[0] != icon.cacheKey():
                copy = QtGui.QIcon()
                for size in (16, 20, 24, 32, 48, 64):
                    pixmap = icon.pixmap(size)
                    if not pixmap.isNull():
                        copy.addPixmap(pixmap)
                cached = self._doc_icon_pixmaps = (icon.cacheKey(), copy if not copy.isNull() else icon)
            icon = cached[1]
        key = icon.cacheKey()
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            if item.icon(0).cacheKey() != key:
                item.setIcon(0, icon)


_FLAT_ICONS = {}


def _flat_icon(icon):
    """icon as ready-drawn pictures: the tree draws a document row's picture at size 0 while it is being laid
    out, and an SVG icon drawn at size 0 fills the Notifications with "QPainter::begin: Paint device returned
    engine == 0" warnings (71 at each start, vd113, 11-20)."""
    if icon.isNull():
        return icon
    key = icon.cacheKey()
    flat = _FLAT_ICONS.get(key)
    if flat is None:
        flat = QtGui.QIcon()
        for size in (16, 20, 24, 32, 48, 64):
            pm = icon.pixmap(size, size)
            if not pm.isNull():
                flat.addPixmap(pm)
        if flat.isNull():
            flat = icon
        _FLAT_ICONS.clear()
        _FLAT_ICONS[key] = flat
    return flat


_shell = None


DRAW_STYLE_NAMES = {2: "Wireframe", 3: "Hidden Lines Removed", 4: "Shaded", 5: "Shaded", 6: "Shaded With Edges"}


def drawing_display_style(name, probe=False):
    ""

    try:
        from . import drawings
        if not drawings.in_drawing():
            return False
        if probe:
            return True
        from . import drawselect
        if name:
            drawselect.display_style(name)
        return True
    except Exception as error:
        if not probe:
            App.Console.PrintWarning("FreeCAD: drawing display style: %s\n" % error)
        return False


def shell():
    return _shell


def set_enabled(on):
    global _shell
    params = paths.params()
    params.SetBool("Enabled", bool(on))
    if on:
        if _shell is None:
            _shell = Shell()
        _shell.enable()
        try:
            from . import icons             # icons-refresh-1126: our pictures back after the classic interface
            icons.freeworks_icons()
        except Exception as _fw_err:
            _fw_log("shell.py:icons-on", _fw_err)
    elif _shell is not None:
        _shell.disable()
        try:
            from . import icons             # FreeCAD's own pictures back (not on close: disable(closing=True) is not this path)
            icons.classic_icons()
        except Exception as _fw_err:
            _fw_log("shell.py:icons-off", _fw_err)


def toggle():
    set_enabled(not (_shell is not None and _shell.enabled))


def _docs_busy():
    """busyrefresh-1127: a document is opening or rebuilding (FreeCAD takes no input then)."""
    try:
        if App.isRestoring():
            return True
        for d in App.listDocuments().values():
            if d.Restoring or d.Recomputing:
                return True
    except Exception:
        return False
    return False
