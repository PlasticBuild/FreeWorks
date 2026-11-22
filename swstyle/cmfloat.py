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
from PySide import QtCore, QtGui, QtWidgets

from .widgets import alive

Qt = QtCore.Qt
DRAG = 24              # pixels down off the row before a tab comes away


class FloatingTab(QtWidgets.QWidget):
    def __init__(self, owner, page, index):
        super().__init__(owner.shell.window, Qt.Tool)
        self.owner, self.title, self.index = owner, page.title, index
        self.setObjectName("SWFloatingTab")
        self.setWindowTitle(page.title)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        from . import ribbon
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        self.page = ribbon.RibbonPage(owner.shell, page.title, page.spec, self)
        self.page.ensure_built()
        lay.addWidget(self.page)
        w = max(260, self.page.needed_width() + 8)
        self.resize(w, self.page.height() + 8)
        self.page.relayout(w - 4)
        try:
            owner.shell.page_shown(self.page)      # its buttons take their commands and states
        except Exception as _fw_err:
            _fw_log("cmfloat.py:47", _fw_err)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if alive(self.page):
            self.page.relayout(self.width() - 4)

    def closeEvent(self, e):
        self.owner.dock(self)
        super().closeEvent(e)


class TabFloat(QtCore.QObject):
    def __init__(self, shell):
        super().__init__(shell.window)
        self.shell = shell
        self.start = None
        self.floating = {}          # title: FloatingTab
        self.parked = {}            # title: (page, index)
        bar = self.bar()
        if bar is not None:
            bar.tabs.installEventFilter(self)

    def bar(self):
        return getattr(self.shell, "topbar", None)

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            i = obj._index_at(event.position())
            self.start = (i, event.position().toPoint()) if i >= 0 else None
        elif t == QtCore.QEvent.MouseMove and self.start is not None and event.buttons() & Qt.LeftButton:
            i, p0 = self.start
            p = event.position().toPoint()
            if p.y() - obj.height() > DRAG or p.y() - p0.y() > DRAG + obj.height():
                self.start = None
                self.float_tab(i, event.globalPosition().toPoint())
                return True
        elif t == QtCore.QEvent.MouseButtonRelease:
            self.start = None
        return False

    def float_tab(self, index, at=None):
        bar = self.bar()
        if bar is None or not (0 <= index < len(bar.pages)) or len(bar.pages) < 2:
            return None
        page = bar.pages[index]
        win = FloatingTab(self, page, index)
        self.floating[page.title] = win
        self.parked[page.title] = (page.spec, index)
        bar.remove_page(page)
        page.hide()
        at = at or QtGui.QCursor.pos()
        win.move(at - QtCore.QPoint(win.width() // 2, 10))
        win.show()
        win.raise_()
        return win

    def dock(self, win):
        """The tab goes back in its place (a new page from the same layout: the CommandManager
        throws away pages it no longer shows)."""
        title = win.title
        self.floating.pop(title, None)
        spec, index = self.parked.pop(title, (None, None))
        bar = self.bar()
        if spec is None or bar is None or any(p.title == title for p in bar.pages):
            return                  # the tabs were made again meanwhile (another document type)
        try:
            from . import ribbon
            page = ribbon.RibbonPage(self.shell, title, spec)
            at = min(index, len(bar.pages))
            bar.pages.insert(at, page)
            bar.stack.insertWidget(at, page)
            bar.tabs.set_titles([p.title for p in bar.pages])
            bar.tabs.current = -1
            bar.tabs.set_current(at)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: floating tab: %s\n" % error)


_state = {}


def install(shell):
    if shell is None or "f" in _state or getattr(shell, "topbar", None) is None:
        return _state.get("f")
    _state["f"] = TabFloat(shell)
    return _state["f"]


def current():
    return _state.get("f")
