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

from .widgets import CommandButton, alive

Qt = QtCore.Qt

ARROW_MS = 3500
RED = QtGui.QColor("#e00000")


def glasses_icon(colour, size=16, dpr=1.0):
    ""
    pm = QtGui.QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor(colour))
    pen.setWidthF(1.4)
    p.setPen(pen)
    s = size / 16.0
    p.drawEllipse(QtCore.QPointF(4.5 * s, 9.5 * s), 3.0 * s, 3.0 * s)
    p.drawEllipse(QtCore.QPointF(11.5 * s, 9.5 * s), 3.0 * s, 3.0 * s)
    p.drawLine(QtCore.QPointF(7.4 * s, 9.0 * s), QtCore.QPointF(8.6 * s, 9.0 * s))
    p.drawLine(QtCore.QPointF(1.6 * s, 8.6 * s), QtCore.QPointF(2.6 * s, 5.0 * s))
    p.drawLine(QtCore.QPointF(14.4 * s, 8.6 * s), QtCore.QPointF(13.4 * s, 5.0 * s))
    p.end()
    return QtGui.QIcon(pm)


class RedArrow(QtWidgets.QWidget):
    """A red arrow under a button, pointing up at it, gone after a few seconds or a click."""
    W, H = 34, 46

    def __init__(self, window, target):
        super().__init__(window)
        self.setObjectName("SWCommandLocationArrow")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.target = target
        centre = target.mapTo(window, QtCore.QPoint(target.width() // 2, target.height()))
        self.setGeometry(centre.x() - self.W // 2, centre.y() + 1, self.W, self.H)
        self.show()
        self.raise_()
        QtCore.QTimer.singleShot(ARROW_MS, self.close_arrow)

    def close_arrow(self):
        if alive(self):
            self.hide()
            self.deleteLater()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1.5))
        p.setBrush(RED)
        w, h = self.W, self.H
        path = QtGui.QPainterPath()
        path.moveTo(w / 2.0, 1)
        path.lineTo(w - 2, 18)
        path.lineTo(w / 2.0 + 6, 18)
        path.lineTo(w / 2.0 + 6, h - 2)
        path.lineTo(w / 2.0 - 6, h - 2)
        path.lineTo(w / 2.0 - 6, 18)
        path.lineTo(2, 18)
        path.closeSubpath()
        p.drawPath(path)
        p.end()


def _buttons(widget, key):
    """CommandButtons for key under widget: the button itself first, then a flyout holding it."""
    own, holders = [], []
    for b in widget.findChildren(CommandButton):
        cmd = b.binding.cmd
        if cmd.key == key:
            own.append(b)
        elif key in b.flyout_keys:
            holders.append(b)
    return own + holders


def ribbon_button(shell, key):
    ""
    top = getattr(shell, "topbar", None)
    if top is None or not alive(top):
        return None, None
    qat = getattr(top, "qat", None)
    if qat is not None and alive(qat):
        for b in _buttons(qat, key):
            if b.isVisible():
                return None, b
    current = top.current_page()
    pages = ([current] if current is not None else []) + [p for p in top.pages if p is not current]
    for page in pages:
        found = _buttons(page, key)
        if not found and not getattr(page, "built", True) and repr(key) in repr(getattr(page, "spec", ())):
            page.ensure_built()          # a tab makes its buttons when first shown: this one names the command
            try:
                page.relayout(page.width())
            except Exception as _fw_err:
                _fw_log("cmdlocate.py:relayout", _fw_err)
            found = _buttons(page, key)
        if found:
            return page.title, found[0]
    return None, None


def menu_path(bar, name):
    """[QAction, ...] from the menu bar down to the action of FreeCAD command name, or []."""
    def group_entry(action, sub):
        # a group command's submenu (View > Set Current View As): its entries carry no command name
        try:
            from . import keys
            for group, cls in keys.COMMANDS:
                if group in (action.objectName(), action.data()) or (
                        getattr(cls, "MENU", "") and action.text().replace("&", "") == cls.MENU):
                    names = keys.group_commands(group)
                    if name in names:
                        entries = [a for a in sub.actions() if not a.isSeparator()]
                        i = names.index(name)
                        return [action, entries[i]] if i < len(entries) else []
        except Exception as _fw_err:
            _fw_log("cmdlocate.py:137", _fw_err)
        return []

    def walk(menu, trail):
        if menu.objectName().startswith("SWMenu_"):
            try:
                menu.aboutToShow.emit()
            except Exception as _fw_err:
                _fw_log("cmdlocate.py:fill", _fw_err)
        for action in menu.actions():
            sub = action.menu()
            if sub is not None:
                entry = group_entry(action, sub)
                if entry:
                    return trail + entry
                found = walk(sub, trail + [action])
                if found:
                    return found
            elif action.objectName() == name or action.data() == name:
                return trail + [action]
        return []
    if bar is None:
        return []
    for action in bar.actions():
        if action.menu() is not None:
            found = walk(action.menu(), [action])
            if found:
                return found
    return []


def open_menu_path(shell, path):
    """Opens the menus along path and highlights the last item (non-blocking popups)."""
    if not path:
        return False
    top = getattr(shell, "topbar", None)
    qat = getattr(top, "qat", None)
    anchor = None
    if qat is not None and alive(qat):
        qat.show_menus()
        for b in getattr(qat.menus, "_buttons", []):
            if alive(b) and b.menu() is path[0].menu():
                anchor = b.mapToGlobal(QtCore.QPoint(0, b.height()))
    if anchor is None:
        anchor = QtGui.QCursor.pos()
    menu = path[0].menu()
    def _plain(t):
        return t.split("\t")[0].replace("&", "")      # access marks come and go as the menu opens
    keys = [(a.data(), _plain(a.text())) for a in path[1:]]      # the menu fills itself again as it opens
    menu.popup(anchor)
    for data, text in keys:
        QtWidgets.QApplication.processEvents()
        action = next((a for a in menu.actions() if data and a.data() == data), None) \
            or next((a for a in menu.actions() if _plain(a.text()) == text), None)
        if action is None:
            break
        menu.setActiveAction(action)
        sub = action.menu()
        if sub is None:
            break
        rect = menu.actionGeometry(action)
        sub.popup(menu.mapToGlobal(rect.topRight()))
        menu = sub
    return True


def show(shell, name):
    """Show command location for a search result name ("sw:Key" or a FreeCAD command).
    Returns what was done: "button", "menu" or "none"."""
    key = name[3:] if name.startswith("sw:") else None
    native = None
    if key is None:
        from . import catalog
        native = name
        for cmd in catalog.ALL:
            if name in (cmd.natives or ()):
                key = cmd.key
                break
    if key is not None:
        title, button = ribbon_button(shell, key)
        if button is not None:
            if title is not None:
                shell.topbar.select(title)
            QtWidgets.QApplication.processEvents()
            if button.isVisible():
                shell.last_arrow = RedArrow(shell.window, button)
                return "button"
        if native is None:
            native = shell.binding(key).native
    if native and open_menu_path(shell, menu_path(shell.native_menubar(), native)):
        return "menu"
    shell.window.statusBar().showMessage("This command is not on the CommandManager or in a menu.", 5000)
    return "none"
