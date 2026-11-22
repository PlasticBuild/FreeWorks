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

import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import contextbar, rcmenus
from .widgets import alive

Qt = QtCore.Qt

PARAM = rcmenus.PARAM
LAST = rcmenus.LAST      # the last menu shown, for checks


def enabled():
    return rcmenus.enabled()


def fw_tool():
    ""
    for name in ("swstyle.fwsketch.toolbase", "fwsketch.toolbase"):
        try:
            module = __import__(name, fromlist=["active"])
            tool = module.active()
            if tool is not None:
                return tool
        except Exception:
            continue
    return None


class SketchToolMenu(QtCore.QObject):
    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self._pending = False
        self._watched = []
        self._shown_at = 0.0
        self.mdi = shell.window.findChild(QtWidgets.QMdiArea)
        if self.mdi is not None:
            self.mdi.subWindowActivated.connect(self.attach)
        QtCore.QTimer.singleShot(0, self.attach)

    def attach(self, *args):
        self._watched = [w for w in self._watched if alive(w)]
        view = self.shell.view_widget()
        if view is None or not alive(view) or not hasattr(view, "viewport"):
            return
        widget = view.viewport()
        if widget is None or widget in self._watched:
            return
        widget.installEventFilter(self)
        self._watched.append(widget)

    def remove(self):
        for widget in self._watched:
            if alive(widget):
                widget.removeEventFilter(self)
        self._watched = []
        if self.mdi is not None and alive(self.mdi):
            try:
                self.mdi.subWindowActivated.disconnect(self.attach)
            except Exception as _fw_err:
                _fw_log("sketchtoolmenu.py:88", _fw_err)

    # ---------------------------------------------------------------- events
    def _gestures(self):
        return getattr(self.shell, "gestures", None)

    def _here(self):
        if not (getattr(self.shell, "enabled", True) and enabled()):
            return False
        return contextbar.sketch_in_edit() is not None and fw_tool() is None

    def _wanted(self, event):
        try:
            if event.button() != Qt.RightButton or event.modifiers() != Qt.NoModifier:
                return False
        except Exception:
            return False
        return self._here()

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        try:
            t = event.type()
            if t == QtCore.QEvent.MouseButtonPress:
                if not self._wanted(event):
                    return False
                g = self._gestures()
                if g is not None and not getattr(g, "_replaying", False):
                    try:
                        from .gestures import enabled_here
                        if enabled_here():
                            return False        # gestures holds the press; its replay comes back here
                    except Exception as _fw_err:
                        _fw_log("sketchtoolmenu.py:122", _fw_err)
                self._hover(obj, event)
                self._pending = True
                return True
            if t == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.RightButton and self._pending:
                self._pending = False
                pos = event.globalPosition().toPoint()
                QtCore.QTimer.singleShot(0, lambda: self.show_menu(pos))
                return True
            if t == QtCore.QEvent.ContextMenu and self._here():
                return True         # FreeCAD's sketch menu stays shut while ours is used
        except Exception:
            return False
        return False

    @staticmethod
    def _hover(widget, event):
        """FreeCAD finds what is under the pointer only when the mouse moves; a move on the spot
        has it look again (after a menu closed, the pointer has not moved)."""
        try:
            move = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, event.position(), event.globalPosition(),
                                     Qt.NoButton, Qt.NoButton, Qt.NoModifier)
            QtWidgets.QApplication.sendEvent(widget, move)
        except Exception as _fw_err:
            _fw_log("sketchtoolmenu.py:146", _fw_err)

    def _trimming(self):
        """FreeCAD's own Trim Entities runs (its page is open)."""
        try:
            from . import nativepms, sketchtoolpm
            return isinstance(sketchtoolpm.current(), nativepms.TrimPage)
        except Exception:
            return False

    def build(self, widget=None):
        """The menu a right-click would open now, without showing it (checks use it)."""
        sketch = contextbar.sketch_in_edit()
        tool = fw_tool()
        if tool is not None or self._trimming() or contextbar.tool_running(self.shell):
            name, items = rcmenus.tool_items(tool, sketch, trimming=self._trimming())
            row = []
        else:
            name, items, row = rcmenus.sketch_items(sketch, None)
        menu = rcmenus.Builder(name, items, row=row).build()
        LAST[:] = [menu, name, None]
        return menu

    def show_menu(self, pos, at=None):
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            return None
        if self._trimming() or contextbar.tool_running(self.shell):
            name, items = rcmenus.tool_items(None, sketch, trimming=self._trimming())   # FreeCAD's own tool
            rcmenus.show(rcmenus.Builder(name, items, row=rcmenus.sketch_rows(sketch)), pos)
        else:
            rcmenus.sketch_menu(sketch, rcmenus.under_pointer(sketch, at), pos)
        return LAST[0] if LAST else None


_menu = []


def install(shell=None, tries=30):
    """Watches the 3D views once the look's shell is up (also the feature PropertyManager menu)."""
    if shell is None:
        try:
            from . import shell as shell_module
            shell = shell_module.shell()
        except Exception:
            shell = None
    if shell is None:
        if tries > 0:
            QtCore.QTimer.singleShot(1000, lambda: install(None, tries - 1))
        return None
    try:
        rcmenus.install(shell)
    except Exception as _fw_err:
        _fw_log("sketchtoolmenu.py:199", _fw_err)
    try:
        from . import featuremenu
        featuremenu.install(shell)
    except Exception as _fw_err:
        _fw_log("sketchtoolmenu.py:204", _fw_err)
    try:
        from . import partmenu
        partmenu.install(shell)
    except Exception as _fw_err:
        _fw_log("sketchtoolmenu.py:209", _fw_err)
    if _menu and _menu[0].shell is shell:
        return _menu[0]
    while _menu:                # an old shell's menu only (remove() would undo the two above)
        _menu.pop().remove()
    _menu.append(SketchToolMenu(shell))
    return _menu[0]


def remove():
    while _menu:
        _menu.pop().remove()
    try:
        from . import featuremenu
        featuremenu.remove()
    except Exception as _fw_err:
        _fw_log("sketchtoolmenu.py:225", _fw_err)
    try:
        from . import partmenu
        partmenu.remove()
    except Exception as _fw_err:
        _fw_log("sketchtoolmenu.py:230", _fw_err)
