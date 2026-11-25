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

CHEVRON = "»"
LETTER = "swMnemonic"
# items that run a FreeCAD command without being one of the catalog's (their text says which)
TEXT_COMMANDS = {"Delete": "Std_Delete", "Delete...": "Std_Delete", "Copy": "Std_Copy", "Paste": "Std_Paste",
                 "Cut": "Std_Cut", "Zoom to Fit": "Std_ViewFitAll", "Undo": "Std_Undo", "Redo": "Std_Redo",
                 "Select All": "Std_SelectAll", "Rebuild": "Std_Refresh"}


def plain(text):
    """The text without access-letter marks."""
    return (text or "").replace("&&", "\0").replace("&", "").replace("\0", "&")


def plain_marks(text):
    """text with "&&" (a real ampersand) taken out: what is left of "&" is an access-letter mark."""
    return (text or "").replace("&&", "")


def label_of(text):
    """The item's wording without the key shown after a tab (menu-bar items carry "\tCtrl+N")."""
    return plain(text).split("\t")[0]


def _letters(text):
    text = label_of(text)
    words = [w for w in text.replace("/", " ").replace("-", " ").split() if w]
    firsts = [w[0] for w in words if w[0].isalnum()]
    rest = [c for c in text if c.isalnum()]
    return firsts + rest


def _wanted(a):
    if a.isSeparator() or not a.isVisible() or isinstance(a, QtWidgets.QWidgetAction) or a.property("swHeading"):
        return False
    t = label_of(a.text())
    return bool(t) and t != CHEVRON


def menu_letter(a, menu, kind=None):
    ""

    try:
        from . import swletters
        title = label_of(menu.title()).strip() if menu is not None else ""
        doc = getattr(swletters, "BY_DOC", {}).get(kind or doc_kind(), {}).get(title, {})
        by = getattr(swletters, "BY_MENU", {}).get(title)
    except Exception:
        return None
    if not by and not doc:
        return None
    t = label_of(a.text()).strip()
    bare = " ".join(t.rstrip(". ").split())
    keys = (bare + " >", bare) if a.menu() is not None else (bare,)
    for table in (doc, by or {}):
        for k in keys:
            got = table.get(k)
            if got and got.upper() in t.upper():
                return got
    return None


def doc_kind():
    ""
    try:
        import FreeCAD as App
        if App.ActiveDocument is None:
            return "none"
        from . import swmenus
        if swmenus.drawing_in_front():
            return "drawing"
        from . import asmmenubar
        return "assembly" if asmmenubar._assembly() is not None else "part"
    except Exception:
        return "part"


def sw_letter(a):
    ""
    try:
        from . import swletters
    except ImportError:
        return None
    t = label_of(a.text())
    table = swletters.MENUS if a.menu() is not None else swletters.ITEMS
    got = table.get(t) or (swletters.ITEMS.get(t) if a.menu() is not None else None)
    return got if got and got.upper() in t.upper() else None


def assign(menu):
    ""

    used, out = set(), {}
    wanted = [a for a in menu.actions() if _wanted(a)]
    kind = doc_kind() if wanted else None      # once a menu: it walks every object of the document
    for a in wanted:
        u = menu_letter(a, menu, kind)
        if u is not None:
            used.add(u.upper())
            out[a] = u.upper()
    mine = set(used)
    for a in wanted:
        u = None if a in out else sw_letter(a)
        if u is not None and (not mine or u.upper() not in mine):    # another menu's letter: not over this menu's own
            used.add(u.upper())
            out[a] = u.upper()
    for a in wanted:
        if a in out:
            continue
        for c in _letters(a.text()):
            u = c.upper()
            if u not in used:
                used.add(u)
                out[a] = u
                break
    for a in wanted:
        if a not in out:        # every letter of its words is taken: it shares one (the letter then moves between them)
            first = _letters(a.text())
            if first:
                out[a] = first[0].upper()
    return out


def _with_mark(text, letter):
    text, tab, keys = text.partition("\t")
    return _marked(text, letter) + tab + keys


def _marked(text, letter):
    t = plain(text).replace("&", "&&")
    i = 0
    words_first = [k for k, c in enumerate(t) if c.upper() == letter and (k == 0 or t[k - 1] in " /-")]
    if words_first:
        i = words_first[0]
    else:
        i = next((k for k, c in enumerate(t) if c.upper() == letter), -1)
    return t if i < 0 else t[:i] + "&" + t[i:]


def command_of(a):
    name = a.property("swCommand")
    if name:
        return name
    return TEXT_COMMANDS.get(plain(a.text()))


def _style_key(name):
    ""
    try:
        from . import keys
        return next((k for n, k in keys.KEYS if n == name), "")
    except Exception:
        return ""


def shortcut_of(name):
    try:
        if not name or name not in Gui.listCommands():
            return ""
        return Gui.Command.get(name).getShortcut() or _style_key(name)
    except Exception:
        return ""


def key_for(a):
    for name in (a.property("swCommand"), TEXT_COMMANDS.get(plain(a.text()))):
        k = shortcut_of(name)
        if k:
            return k
    return ""


KEY = "swKeyText"


def _restore_keys(menu):
    for a in menu.actions():
        k = a.property(KEY)
        if k and a.shortcut().isEmpty():
            a.setShortcut(QtGui.QKeySequence(k))
            a.setShortcutContext(QtCore.Qt.WidgetShortcut)


class _Letters(QtCore.QObject):
    """A mouse-opened menu: its access letters work without being drawn."""

    def eventFilter(self, menu, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if not isinstance(menu, QtWidgets.QMenu):
            return False
        if event.type() in (QtCore.QEvent.Show, QtCore.QEvent.Paint):
            _restore_keys(menu)
            return False
        if event.type() == QtCore.QEvent.ShortcutOverride:
            plain_key = not (event.modifiers() & ~(QtCore.Qt.ShiftModifier | QtCore.Qt.KeypadModifier))
            if plain_key and event.text() and event.text()[0].isalnum():
                event.accept()          # in an open menu a letter is an access letter, not a command's key
                return True
            return False
        if event.type() != QtCore.QEvent.KeyPress:
            return False
        if not menu.property("swLetters"):
            return False
        if event.modifiers() & ~(QtCore.Qt.ShiftModifier | QtCore.Qt.KeypadModifier):
            return False
        text = event.text()
        if not text or not text[0].isalnum():
            return False
        u = text[0].upper()
        hits = [a for a in menu.actions() if a.property(LETTER) == u and a.isVisible() and a.isEnabled()]
        if not hits:
            return False
        if len(hits) > 1:            # Windows: the letter moves between the items that share it
            cur = menu.activeAction()
            i = hits.index(cur) + 1 if cur in hits else 0
            menu.setActiveAction(hits[i % len(hits)])
            return True
        a = hits[0]
        menu.setActiveAction(a)
        if a.menu() is not None:
            QtWidgets.QApplication.sendEvent(menu, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Right,
                                                                   QtCore.Qt.NoModifier))
        else:
            a.trigger()
            top = menu
            while isinstance(top.parentWidget(), QtWidgets.QMenu):
                top = top.parentWidget()
            top.close()
            menu.close()
        return True


_FILTER = []


def _filter():
    if not _FILTER:
        _FILTER.append(_Letters(QtWidgets.QApplication.instance()))
    return _FILTER[0]


def decorate(menu, keyboard=False, depth=0, keys=True):
    """Access letters (drawn when keyboard) and command keys on menu and its submenus. keys=False for the
    menu bar's menus, whose items show their own keys."""
    if depth > 4:
        return
    try:
        _decorate(menu, keyboard, depth, keys)
    except RuntimeError as _fw_err:
        _fw_log("rcaccel.py:229", _fw_err)


def _decorate(menu, keyboard, depth, keys=True):
    menu.setProperty("swDecorated", True)
    # a menu with its own marks keeps them, except the menu bar's (its marks come from here, and the
    # Window list's "&1 name" is not a mark of ours), which are worked out afresh each time
    own = keys and any("&" in plain_marks(a.text()) for a in menu.actions())
    for a, letter in ({} if own else assign(menu)).items():
        a.setProperty(LETTER, letter)
        if keyboard:
            a.setText(_with_mark(a.text(), letter))
    for a in menu.actions():
        if a.menu() is not None:
            sub = a.menu()
            if not sub.property("swKeysHooked"):
                # a submenu gets its letters and keys as it opens, not with the menu (most are never
                # opened: about 8 ms of every right-click); again a moment later for one filled as it opens
                sub.setProperty("swKeysHooked", True)
                sub.aboutToShow.connect(lambda m=sub, k=keyboard, d=depth + 1, y=keys: decorate(m, k, d, y))
                sub.aboutToShow.connect(lambda m=sub, k=keyboard, d=depth + 1, y=keys:
                                        QtCore.QTimer.singleShot(0, lambda: decorate(m, k, d, y)))
            continue
        if not keys or not _wanted(a) or not a.shortcut().isEmpty():
            continue
        key = key_for(a)
        if key:
            a.setProperty(KEY, key)
            a.setShortcut(QtGui.QKeySequence(key))
            a.setShortcutContext(QtCore.Qt.WidgetShortcut)      # shown beside it; works while the menu is open
    menu.setProperty("swLetters", not keyboard)      # drawn underlines: Qt itself takes the letters
    try:
        from . import rctips
        rctips.apply(menu)
    except Exception as _fw_err:
        _fw_log("rcaccel.py:264", _fw_err)
    menu.installEventFilter(_filter())


# --------------------------------------------------------------------------- Shift+F10 and the Menu key
def _menu_key(event):
    if event.type() == QtCore.QEvent.ContextMenu:
        return event.reason() == QtGui.QContextMenuEvent.Keyboard
    if event.type() != QtCore.QEvent.KeyPress:
        return False
    k, mods = event.key(), event.modifiers() & ~QtCore.Qt.KeypadModifier
    return k == QtCore.Qt.Key_Menu and not mods or k == QtCore.Qt.Key_F10 and mods == QtCore.Qt.ShiftModifier


def _spot(widget):
    """Where the keyboard menu opens: at the pointer when it is over widget, else at its middle."""
    g = QtGui.QCursor.pos()
    local = widget.mapFromGlobal(g)
    if widget.rect().contains(local):
        return g, local
    local = widget.rect().center()
    return widget.mapToGlobal(local), local


def _graphics_view(w):
    while w is not None:
        if isinstance(w, QtWidgets.QGraphicsView):
            return w
        w = w.parentWidget()
    return None


def open_from_keyboard(widget):
    """Opens the right-click menu for the area widget is in. True when one of ours opened."""
    from . import rcmenus
    rcmenus.KEYBOARD[0] = True
    try:
        gv = _graphics_view(widget)
        if gv is not None:
            from . import drawmenu
            if drawmenu._page() is None:
                return False
            g, _local = _spot(gv.viewport())
            p = gv.viewport().mapFromGlobal(g)
            h = drawmenu.hits(gv, p)
            kind, obj, extra = h[0] if h else (None, None, None)
            try:
                drawmenu._LAST.update(view=gv, pos=p)
            except Exception as _fw_err:
                _fw_log("rcaccel.py:313", _fw_err)
            return drawmenu.show_menu(g, kind, obj, extra) is not None
        from . import contextbar, partmenu, sketchtoolmenu
        view = widget
        g, _local = _spot(view)
        # the menus hit-test in the 3D view's coordinates (origin bottom left, device pixels, as
        # view.getCursorPos() gives them), not Qt's: None = under the pointer, read by the menu itself
        if QtGui.QCursor.pos() == g:
            at = None
        else:
            try:
                ratio = float(view.devicePixelRatioF())
            except Exception:
                ratio = 1.0
            at = (int(round(_local.x() * ratio)), int(round((view.height() - _local.y()) * ratio)) - 1)
        if contextbar.sketch_in_edit() is not None and sketchtoolmenu._menu:
            return sketchtoolmenu._menu[0].show_menu(g, at) is not None
        if partmenu._here():
            return partmenu.show_menu(g, at) is not None
        return False
    finally:
        rcmenus.KEYBOARD[0] = False


def _in_3d_view(w):
    while w is not None:
        if w.metaObject().className() in ("Gui::View3DInventorViewer", "Gui::View3DInventor", "QuarterWidget",
                                          "SIM::Coin3D::Quarter::QuarterWidget"):
            return True
        w = w.parentWidget()
    return False


class _MenuKey(QtCore.QObject):
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        if t == QtCore.QEvent.Show and isinstance(obj, QtWidgets.QMenu):
            try:
                if not obj.property("swDecorated") and _house(obj):
                    decorate(obj, keyboard=keyboard_recent())
                elif obj.objectName() == "SWWindowMenu":
                    decorate_bar(obj)       # windowmenu.py's Window menu (the other menu-bar menus: swmenus)
            except Exception as _fw_err:
                _fw_log("rcaccel.py:348", _fw_err)
            return False
        if t not in (QtCore.QEvent.KeyPress, QtCore.QEvent.ContextMenu) or not isinstance(obj, QtWidgets.QWidget):
            return False
        try:
            if not _menu_key(event):
                return False
            if not (_in_3d_view(obj) or _graphics_view(obj) is not None):
                view = _tree_view(obj)
                if view is None:
                    return False
                if t == QtCore.QEvent.ContextMenu:
                    _note_keyboard()        # the menu it opens gets drawn access letters
                    return False
                if event.key() == QtCore.Qt.Key_F10:
                    return tree_from_keyboard(view)
                _note_keyboard()
                return False        # the Menu key: Qt sends the tree a keyboard ContextMenu of its own
            if t == QtCore.QEvent.ContextMenu and getattr(self, "_just", False):
                self._just = False
                return True         # the key already opened ours
            if open_from_keyboard(obj):
                self._just = t == QtCore.QEvent.KeyPress
                return True
        except Exception:
            return False
        return False


_KEYS = []


def install_keys():
    if _KEYS:
        return _KEYS[0]
    f = _MenuKey(QtWidgets.QApplication.instance())
    try:
        from . import events      # the add-on's one application filter (interface land263)
        events.register("rcaccel.keys", (QtCore.QEvent.KeyPress, QtCore.QEvent.ContextMenu, QtCore.QEvent.Show), f.eventFilter)
    except ImportError:          # only without the shared dispatcher: never both (each event would run twice)
        QtWidgets.QApplication.instance().installEventFilter(f)
    _KEYS.append(f)
    try:
        from . import keyfallback
        keyfallback.install()
    except Exception as error:
        import FreeCAD
        FreeCAD.Console.PrintLog("FreeCAD: key fallback: %s\n" % error)
    return f


# --------------------------------------------------------------------------- the other house menus

HOUSE = ("SWFeatureMenu", "SWRollbackMenu", "SWSheetTabMenu", "SWDisplayManagerMenu", "SWConfigurationMenu",
         "SWAppearanceMenu", "SWDisplayModeMenu", "SWConfigScopeMenu", "SWOrientationMenu")
_RECENT = {"at": 0.0}


def _house(menu):
    n = menu.objectName()
    if n in HOUSE or n.startswith("SWToolMenu_") and not isinstance(menu.parentWidget(), QtWidgets.QMenu):
        return True
    return n.startswith("FW_") and n.endswith("Menu")


def keyboard_recent():
    import time
    return time.monotonic() - _RECENT["at"] < 0.6


def decorate_bar(menu):
    ""

    try:
        keyboard = keyboard_recent() or QtWidgets.QApplication.mouseButtons() == QtCore.Qt.NoButton
        decorate(menu, keyboard=keyboard, keys=False)
        # items other hooks add to the menu as it opens come after this call
        QtCore.QTimer.singleShot(0, lambda m=menu, k=keyboard: decorate(m, keyboard=k, keys=False))
    except Exception as _fw_err:
        _fw_log("rcaccel.py:427", _fw_err)


def _note_keyboard():
    import time
    _RECENT["at"] = time.monotonic()


def _tree_view(w):
    while w is not None:
        if isinstance(w, QtWidgets.QAbstractItemView):
            return w
        w = w.parentWidget()
    return None


def tree_from_keyboard(view):
    """Shift+F10 in a list or tree: its menu for the current row. The tree takes Shift held for "FreeCAD's
    own menu", so Shift is not passed on (Shift+F10 is the keyboard's right-click, not Shift+right-click)."""
    index = view.currentIndex()
    vp = view.viewport()
    local = view.visualRect(index).center() if index.isValid() else QtCore.QPoint(8, 8)
    ev = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Keyboard, local, vp.mapToGlobal(local),
                                 QtCore.Qt.NoModifier)
    real = QtWidgets.QApplication.keyboardModifiers
    QtWidgets.QApplication.keyboardModifiers = staticmethod(lambda: QtCore.Qt.NoModifier)
    try:
        _note_keyboard()
        QtWidgets.QApplication.sendEvent(vp, ev)
    finally:
        QtWidgets.QApplication.keyboardModifiers = real
    return True
