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

from . import catalog
from .widgets import alive

Qt = QtCore.Qt
FROM = "application/x-freeworks-cm-from"
log = []            # what was done, for checks


def _cz():
    from . import customizedlg
    return customizedlg


def _list(name):
    return _cz()._list(name)


def _set(name, keys):
    if keys:
        _cz()._set_list(name, list(keys))
    else:
        _cz()._p().RemString(name)


def custom_tabs():
    return [t for t in _list("CMTabs") if t]


def doc_kind():
    """The document type whose tabs the CommandManager shows: part, assembly or drawing."""
    try:
        from . import asmui
        kind = getattr(asmui, "_showing", None) or "part"
    except Exception:
        kind = "part"
    return "part" if kind == "edit" else kind


def tab_kind(title):
    ""
    return _cz()._p().GetString("CMTabKind." + title, "")


def tabs_for(kind=None):
    kind = kind or doc_kind()
    return [t for t in custom_tabs() if tab_kind(t) in ("", kind)]


def shown_name(title):
    """The name a tab shows: the one Rename Tab... gave a stock tab, else its title."""
    try:
        return _cz()._p().GetString("CMName." + title, "") or title
    except Exception:
        return title


def tab_keys(title):
    return [k for k in _list("CMTab." + title) if k in catalog.BY_KEY]


def extras(title):
    return [k for k in _list("CMExtra." + title) if k in catalog.BY_KEY]


def removed(title):
    return [k for k in _list("CMRemoved." + title) if k]


def places(title):
    """[(key, before)] where buttons were put on a stock tab; before None = the end of the tab."""
    out = []
    for item in _list("CMPlace." + title):
        key, _s, before = item.partition(">")
        if key in catalog.BY_KEY:
            out.append((key, before or None))
    return out


def set_place(title, key, before):
    keep = [(k, b) for k, b in places(title) if k != key]
    if before != key:
        keep.append((key, before))
    _set("CMPlace." + title, ["%s>%s" % (k, b or "") for k, b in keep])


def _strip_key(spec, key):
    out = []
    for item in spec:
        kind = item[0] if item else None
        if kind == "large" and item[1] == key:
            continue
        if kind == "stack":
            rows = [(k, f) for k, f in item[1] if k != key]
            if not rows:
                continue
            item = ("stack", rows)
        elif kind == "grid":
            rows = [r for r in ([(k, f) for k, f in row if k != key] for row in item[1]) if r]
            if not rows:
                continue
            item = ("grid", rows)
        out.append(item)
    return out


def _item_has(item, key):
    kind = item[0] if item else None
    if kind == "large":
        return item[1] == key
    if kind == "stack":
        return any(k == key for k, _f in item[1])
    if kind == "grid":
        return any(k == key for row in item[1] for k, _f in row)
    return False


def _apply_places(title, spec):
    """Each placed button taken from where it was and put before its anchor (a whole group or stack)."""
    out = list(spec)
    for key, before in places(title):
        flyout = None
        for item in out:
            if item and item[0] == "large" and item[1] == key:
                flyout = item[2] if len(item) > 2 else None
        out = _strip_key(out, key)
        new = ("large", key, flyout or _flyout(key))
        at = next((i for i, item in enumerate(out) if before and _item_has(item, before)), None)
        if at is None:
            out.append(new)
        else:
            out.insert(at, new)
    while out and out[-1][0] == "sep":
        out.pop()
    while out and out[0][0] == "sep":
        out.pop(0)
    return out


def _flyout(key):
    cmd = catalog.BY_KEY.get(key)
    if cmd is not None and cmd.call in ("menu", "scene_menu"):
        return dict((k, f) for k, f in catalog.HEADS_UP).get(key)
    return None


def spec_for(title, spec):
    """A stock tab's layout less the buttons taken off it, plus the ones added to it."""
    gone = set(removed(title))
    out = []
    for item in spec:
        kind = item[0] if item else None
        if kind == "large":
            if item[1] in gone:
                continue
        elif kind == "stack":
            rows = [(k, f) for k, f in item[1] if k not in gone]
            if not rows:
                continue
            item = ("stack", rows)
        elif kind == "grid":
            rows = [[(k, f) for k, f in row if k not in gone] for row in item[1]]
            rows = [r for r in rows if r]
            if not rows:
                continue
            item = ("grid", rows)
        out.append(item)
    while out and out[-1][0] == "sep":
        out.pop()
    have = set()
    for item in out:
        if item[0] == "large":
            have.add(item[1])
        elif item[0] == "stack":
            have.update(k for k, _f in item[1])
        elif item[0] == "grid":
            have.update(k for row in item[1] for k, _f in row)
    placed = {k for k, _b in places(title)}
    added = [k for k in extras(title) if k not in have and k not in placed]
    if added:
        out.append(("sep",))
        out.extend(("large", k, _flyout(k)) for k in added)
    return _apply_places(title, out)


def custom_spec(title):
    return [("large", k, _flyout(k)) for k in tab_keys(title)]


def adjust_pages(shell, pages):
    """The pages as Customize left them: stock tabs with their changes, then the added tabs."""
    from . import ribbon
    out = []
    titles = set()
    for p in pages:
        base = getattr(p, "_fw_base_spec", None)
        if base is None:
            base = p.spec
            p._fw_base_spec = base
        if removed(p.title) or extras(p.title) or places(p.title) or getattr(p, "_fw_changed", False):
            spec = spec_for(p.title, base)
            if p.built:
                ribbon.park(p)
                p = ribbon.RibbonPage(shell, p.title, spec)
                p._fw_base_spec = base
            else:
                p.spec = spec
            p._fw_changed = True
        out.append(p)
        titles.add(p.title)
    for title in tabs_for():
        if title in titles:
            continue
        p = ribbon.RibbonPage(shell, title, custom_spec(title))
        p._fw_custom = True
        out.append(p)
    for p in out:
        p.setAcceptDrops(True)
    return out


def _rebuild(shell, select=None):
    def later():
        try:
            top = shell.topbar
            current = select or (top.current_page().title if top.current_page() is not None else None)
            shell._build_pages()
            if current:
                top.select(current)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: CommandManager customize: %s\n" % error)
    QtCore.QTimer.singleShot(0, later)


def add_key(shell, title, key, before=None, moving=False):
    """The button on the tab, before the button `before` (None: at the end). A button already on the tab is
    moved there when it was dragged along the tab (moving), else left where it is."""
    if key not in catalog.BY_KEY or key == before:
        return False
    if title in custom_tabs():
        keys = tab_keys(title)
        if key in keys and not moving:
            return False
        keys = [k for k in keys if k != key]
        at = keys.index(before) if before in keys else len(keys)
        _set("CMTab." + title, keys[:at] + [key] + keys[at:])
    else:
        on_tab = key in page_keys(shell, title)
        if on_tab and not moving:
            return False
        gone = removed(title)
        if key in gone:
            _set("CMRemoved." + title, [k for k in gone if k != key])
        elif not on_tab:
            ex = extras(title)
            if key not in ex:
                _set("CMExtra." + title, ex + [key])
        if before is not None or on_tab:
            set_place(title, key, before)
    log.append(("move" if moving else "add", title, key, before))
    _rebuild(shell, title)
    return True


def remove_key(shell, title, key):
    if title in custom_tabs():
        _set("CMTab." + title, [k for k in tab_keys(title) if k != key])
    elif key in extras(title):
        _set("CMExtra." + title, [k for k in extras(title) if k != key])
        _set("CMPlace." + title, ["%s>%s" % (k, b or "") for k, b in places(title) if k != key])
    else:
        gone = removed(title)
        if key not in gone:
            _set("CMRemoved." + title, gone + [key])
    log.append(("remove", title, key))
    _rebuild(shell, title)
    return True


def _unique(title):
    have = set(custom_tabs()) | set(t for t, _s in catalog.TABS)
    name, n = title, 1
    while name in have:
        n += 1
        name = "%s %d" % (title, n)
    return name


def add_tab(shell, title="New Tab", keys=()):
    title = _unique(title)
    _set("CMTabs", custom_tabs() + [title])
    _set("CMTab." + title, [k for k in keys if k in catalog.BY_KEY])
    _cz()._p().SetString("CMTabKind." + title, doc_kind())
    log.append(("add_tab", title))
    _rebuild(shell, title)
    return title


def rename_tab(shell, old, new):
    new = (new or "").strip()
    if not new or new == shown_name(old):
        return False
    if old not in custom_tabs():
        # a stock tab: its buttons, ticks and changes stay under its title, only the shown name changes
        g = _cz()._p()
        if new == old:
            g.RemString("CMName." + old)
        else:
            g.SetString("CMName." + old, new)
        log.append(("rename_tab", old, new))
        _rebuild(shell, old)
        return True
    new = _unique(new)
    keys = tab_keys(old)
    _set("CMTabs", [new if t == old else t for t in custom_tabs()])
    _set("CMTab." + new, keys)
    kind = tab_kind(old)
    _cz()._p().RemString("CMTab." + old)
    _cz()._p().RemString("CMTabKind." + old)
    if kind:
        _cz()._p().SetString("CMTabKind." + new, kind)
    log.append(("rename_tab", old, new))
    _rebuild(shell, new)
    return True


# Copy Tab (cmgr-1119): the document types a tab can be copied to
KIND_NAMES = (("part", "Part"), ("assembly", "Assembly"), ("drawing", "Drawing"))


def page_keys(shell, title):
    """The buttons a tab shows now, in order (for Copy Tab)."""
    top = getattr(shell, "topbar", None)
    for p in (top.pages if top is not None else []):
        if p.title == title:
            keys = []
            for item in p.spec:
                if item[0] == "large":
                    keys.append(item[1])
                elif item[0] == "stack":
                    keys.extend(k for k, _f in item[1])
                elif item[0] == "grid":
                    keys.extend(k for row in item[1] for k, _f in row)
            return [k for k in keys if k in catalog.BY_KEY]
    return tab_keys(title)


def copy_tab(shell, title, kind):
    ""
    if kind not in dict(KIND_NAMES):
        return None
    keys = page_keys(shell, title)
    new = _unique(shown_name(title))
    _set("CMTabs", custom_tabs() + [new])
    _set("CMTab." + new, keys)
    _cz()._p().SetString("CMTabKind." + new, kind)
    log.append(("copy_tab", title, kind, new))
    _rebuild(shell)
    return new


def delete_tab(shell, title):
    if title in custom_tabs():
        _set("CMTabs", [t for t in custom_tabs() if t != title])
        _cz()._p().RemString("CMTab." + title)
        _cz()._p().RemString("CMTabKind." + title)
        log.append(("delete_tab", title))
        _rebuild(shell)
        return True
    from . import chromemenus
    log.append(("hide_tab", title))
    return chromemenus.set_tab_shown(shell, title, False)


def reset(shell):
    g = _cz()._p()
    for name in g.GetStrings():
        if name == "CMTabs" or name.startswith(("CMTab.", "CMTabKind.", "CMExtra.", "CMRemoved.", "CMName.", "CMPlace.")):
            g.RemString(name)
    try:
        from . import cmtabs
        App.ParamGet(cmtabs.PREFS).RemString("TabOrder")        # tabdrag-1126: the dragged order goes too
    except Exception as _fw_err:
        _fw_log("cmcustom.py:taborder", _fw_err)
    _rebuild(shell)


def fill_tab_menu(shell, menu, title):
    """Add Tab >, Rename Tab..., Delete Tab on a tab's right-click while Customize is open."""
    from . import swtoolbars
    menu.addSeparator()
    add = menu.addMenu("Add Tab")
    add.setObjectName("SWCMAddTab")
    a = add.addAction("Empty Tab")
    a.triggered.connect(lambda _c=False: QtCore.QTimer.singleShot(0, lambda: add_tab(shell)))
    add.addSeparator()
    for name, _k in swtoolbars.TOOLBARS:
        keys = swtoolbars.keys_of(name)
        if not keys:
            continue
        act = add.addAction(name)
        act.triggered.connect(lambda _c=False, n=name, k=tuple(keys):
                              QtCore.QTimer.singleShot(0, lambda: add_tab(shell, n, k)))
    if title:
        copy = menu.addMenu("Copy Tab")
        copy.setObjectName("SWCMCopyTab")
        here = doc_kind()
        for kind, label in KIND_NAMES:
            if kind == here:
                continue
            c = copy.addAction(label)
            c.triggered.connect(lambda _c=False, k=kind: QtCore.QTimer.singleShot(0, lambda: copy_tab(shell, title, k)))
        r = menu.addAction("Rename Tab...")
        r.triggered.connect(lambda _c=False: QtCore.QTimer.singleShot(0, lambda: _ask_rename(shell, title)))
        d = menu.addAction("Delete Tab")
        d.triggered.connect(lambda _c=False: QtCore.QTimer.singleShot(0, lambda: delete_tab(shell, title)))


def _ask_rename(shell, title):
    text, ok = QtWidgets.QInputDialog.getText(shell.window, "Rename Tab", "Tab name:", text=shown_name(title))
    if ok:
        rename_tab(shell, title, text)


# --------------------------------------------------------------------------- drags while Customize is open
def _page_of(w):
    from . import ribbon
    while w is not None:
        if isinstance(w, ribbon.RibbonPage):
            return w
        w = w.parentWidget()
    return None


def _hud_of(w):
    while w is not None:
        if w.objectName() == "SWHeadsUp":
            return w
        w = w.parentWidget()
    return None


def _button_of(w):
    from .widgets import CommandButton
    while w is not None:
        if isinstance(w, CommandButton):
            return w
        if _page_of(w) is None and _hud_of(w) is None:
            return None
        w = w.parentWidget()
    return None


def drop_anchor(page, global_pos):
    """The key a button let go at global_pos goes before: the button under the pointer (or the next one when the
    pointer is on its right half); None past the last button."""
    from .widgets import CommandButton
    buttons = [b for b in page.findChildren(CommandButton) if b.isVisible() and getattr(b, "binding", None) is not None]
    if not buttons:
        return None
    local = page.mapFromGlobal(global_pos)

    def box(b):
        return QtCore.QRect(b.mapTo(page, QtCore.QPoint(0, 0)), b.size())
    order = sorted(buttons, key=lambda b: (box(b).left(), box(b).top()))
    for i, b in enumerate(order):
        r = box(b)
        if r.contains(local):
            if local.x() > r.center().x():
                return order[i + 1].binding.cmd.key if i + 1 < len(order) else None
            return b.binding.cmd.key
    for b in order:                         # between groups: before the first button to the right
        if box(b).left() > local.x():
            return b.binding.cmd.key
    return None


class Filter(QtCore.QObject):
    def __init__(self, shell):
        super().__init__(shell.window)
        self.shell = shell
        self._press = None

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent) or not isinstance(obj, QtWidgets.QWidget):
            return False
        t = event.type()
        if t in (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove, QtCore.QEvent.Drop):
            page = _page_of(obj)
            hud = _hud_of(obj) if page is None else None
            if (page is None and hud is None) or not event.mimeData().hasFormat(_cz().MIME):
                return False
            if t == QtCore.QEvent.Drop:
                key = bytes(event.mimeData().data(_cz().MIME)).decode()
                if page is not None:
                    source = bytes(event.mimeData().data(FROM)).decode() if event.mimeData().hasFormat(FROM) else ""
                    at = obj.mapToGlobal(event.position().toPoint())
                    add_key(self.shell, page.title, key, drop_anchor(page, at), moving=source == page.title)
                else:
                    from . import chromemenus      # the heads-up row takes commands too
                    chromemenus.add_hud_extra(self.shell, key)
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return True
        if t not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonRelease,
                     QtCore.QEvent.MouseButtonDblClick):
            return False
        b = _button_of(obj)
        if b is None:
            return False
        if t == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._press = (b, event.globalPosition().toPoint())
            return True
        if t == QtCore.QEvent.MouseMove and self._press is not None and self._press[0] is b:
            d = event.globalPosition().toPoint() - self._press[1]
            if d.manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                self._press = None
                self._drag(b)
            return True
        if t in (QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseButtonDblClick):
            self._press = None
            return event.button() == Qt.LeftButton
        return False

    def _drag(self, b):
        page = _page_of(b)
        key = getattr(getattr(b, "binding", None), "cmd", None)
        key = getattr(key, "key", None)
        if page is None and _hud_of(b) is not None and key:
            data = QtCore.QMimeData()
            data.setData(_cz().MIME, key.encode())
            data.setData(FROM, b"heads-up")
            drag = QtGui.QDrag(b)
            drag.setMimeData(data)
            if drag.exec(Qt.CopyAction | Qt.MoveAction) == Qt.IgnoreAction:
                from . import chromemenus
                chromemenus.remove_hud_button(self.shell, key)
            return
        if page is None or not key:
            return
        data = QtCore.QMimeData()
        data.setData(_cz().MIME, key.encode())
        data.setData(FROM, page.title.encode())
        drag = QtGui.QDrag(b)
        drag.setMimeData(data)
        try:
            drag.setPixmap(b.grab())
        except Exception as _fw_err:
            _fw_log("cmcustom.py:405", _fw_err)
        title = page.title
        result = drag.exec(Qt.CopyAction | Qt.MoveAction)
        if result == Qt.IgnoreAction:

            remove_key(self.shell, title, key)


_FILTER = []


def start(shell):
    if shell is None or _FILTER:
        return
    f = Filter(shell)
    QtWidgets.QApplication.instance().installEventFilter(f)
    _FILTER.append(f)


def stop():
    for f in _FILTER:
        try:
            QtWidgets.QApplication.instance().removeEventFilter(f)
            f.deleteLater()
        except Exception as _fw_err:
            _fw_log("cmcustom.py:430", _fw_err)
    _FILTER[:] = []
