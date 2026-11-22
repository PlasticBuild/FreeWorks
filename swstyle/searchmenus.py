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

try:
    import FreeCADGui as Gui
    from PySide import QtCore
except ImportError:
    Gui = None


def _text(action):
    return action.text().split("\t")[0].replace("&", "").strip()      # not the key shown after a tab


def _fill_ours(menu):
    ""
    if menu is not None and menu.objectName().startswith("SWMenu_"):
        try:
            menu.aboutToShow.emit()
        except Exception as _fw_err:
            _fw_log("searchmenus.py:fill", _fw_err)


def _find(menu, path):
    for act in menu.actions():
        if act.isSeparator() or _text(act) != path[0]:
            continue
        if len(path) == 1:
            return act if act.menu() is None else None
        if act.menu() is not None:
            found = _find(act.menu(), path[1:])
            if found is not None:
                return found
    return None


def _leaves(menu, path, out, depth=0):
    if depth > 6:
        return
    for act in menu.actions():
        if act.isSeparator():
            continue
        text = _text(act)
        sub = act.menu()
        if sub is not None:
            _leaves(sub, path + [text], out, depth + 1)
        elif text:
            out.append((text, path + [text], act))


def _signature(bar):
    sig = []
    for top in bar.actions():
        menu = top.menu()
        sig.append((_text(top), len(menu.actions()) if menu is not None else 0))
    return tuple(sig)


def _norm(text):
    return text.lower().rstrip(".… ")


def install():
    try:
        from . import shell as S
    except ImportError:
        return
    cls = getattr(S, "CommandSearch", None)
    if cls is None or getattr(cls, "_fw_menus", False):
        return
    build, runnable, run_item, where, typed, locate = (cls._build_index, cls._runnable, cls._run_item, cls._where, cls.typed,
                                                       cls._locate_clicked)
    Role = QtCore.Qt.UserRole

    def _bar(self):
        try:
            return self.shell.native_menubar()
        except Exception:
            return None

    def _build_index(self):
        build(self)
        self._menu_actions = {}
        self._menu_paths = {}
        bar = _bar(self)
        if bar is None:
            return
        for top in bar.actions():
            _fill_ours(top.menu())
        self._menu_sig = _signature(bar)
        have = {_norm(e[0]) for e in self._index}
        found = []
        for top in bar.actions():
            menu = top.menu()
            if menu is not None:
                start = len(found)
                _leaves(menu, [_text(top)], found)
                found[start:] = [(t, p, a, menu.objectName()) for t, p, a in found[start:]]
        added = 0
        for text, path, act, top_name in found:
            if _norm(text) in have:
                continue
            have.add(_norm(text))
            name = "menu:" + " > ".join(path)
            self._menu_actions[name] = act
            self._menu_paths[name] = (top_name, path)
            self._index.append((text, name, act.toolTip() or act.statusTip() or "", "", False, ""))
            added += 1
        self._index.sort(key=lambda x: x[0].lower())
        App.Console.PrintLog("FreeCAD: Search Commands also lists %d menu commands\n" % added)

    def _live(self, name):
        ""
        act = getattr(self, "_menu_actions", {}).get(name)
        try:
            if act is not None:
                act.isEnabled()
                return act
        except RuntimeError:
            pass
        top_name, path = getattr(self, "_menu_paths", {}).get(name, (None, None))
        bar = _bar(self)
        if not path or bar is None:
            return None
        for top in bar.actions():
            menu = top.menu()
            if menu is not None and menu.objectName() == top_name and _text(top) == path[0]:
                _fill_ours(menu)
                act = _find(menu, path[1:])
                if act is not None:
                    self._menu_actions[name] = act
                return act
        return None

    def _runnable(self, name):
        if isinstance(name, str) and name.startswith("menu:"):
            act = _live(self, name)
            try:
                return bool(act is not None and act.isEnabled())
            except RuntimeError:
                return False
        return runnable(self, name)

    def _run_item(self, item):
        name = item.data(Role)
        if isinstance(name, str) and name.startswith("menu:"):
            if not item.data(Role + 1):
                return
            act = _live(self, name)
            self.hide()
            box = self.box
            try:
                box.clear()
                box.clearFocus()
            except Exception as _fw_err:
                _fw_log("searchmenus.py:126", _fw_err)
            self.runs += 1
            self.last_run = name
            try:
                if act is not None:
                    act.trigger()
            except Exception as error:
                App.Console.PrintError("%s: %s\n" % (name, error))
            return
        run_item(self, item)

    def _where(self, name):
        if isinstance(name, str) and name.startswith("menu:"):
            return name[5:].rsplit(" > ", 1)[0] if " > " in name else ""
        return where(self, name)

    def _locate_clicked(self):
        item = getattr(self, "_located", None)
        name = item.data(Role) if item is not None else None
        if isinstance(name, str) and name.startswith("menu:"):
            self.hide()
            try:
                self.shell.window.statusBar().showMessage("In the menu: " + name[5:], 8000)
            except Exception as _fw_err:
                _fw_log("searchmenus.py:150", _fw_err)
            return
        locate(self)

    def _typed(self, text, box):
        bar = _bar(self)
        if self._index is not None and bar is not None and getattr(self, "_menu_sig", None) != _signature(bar):
            self._index = None          # another menu set: the index is made again
        return typed(self, text, box)

    cls._build_index, cls._runnable, cls._run_item, cls._where, cls._locate_clicked, cls.typed = (
        _build_index, _runnable, _run_item, _where, _locate_clicked, _typed)
    cls._fw_menus = True
