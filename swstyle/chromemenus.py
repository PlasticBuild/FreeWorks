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
from PySide import QtCore, QtWidgets

from . import events
from .widgets import alive

Qt = QtCore.Qt
PARAM = "User parameter:BaseApp/Preferences/Mod/SolidWorksStyle/Customize"
HIDDEN_TABS = "HiddenCommandManagerTabs"
HIDDEN_HUD = "HiddenHeadsUpButtons"
LARGE = "LargeButtonsWithText"

T_LARGE = "Use Large Buttons with Text"
T_DESCRIPTION = "Show Description"
T_TABS = "Tabs"
T_CUSTOMIZE_CM = "Customize CommandManager..."
T_CUSTOMIZE = "Customize..."
T_CM = "Enable CommandManager"
T_TOOLBARS = "Toolbars"
NO_DOC_GREY = ("Structure System", "View (Heads-Up)")

LAST = [None]       # the menu shown last (checks)


def _p():
    return App.ParamGet(PARAM)


def _get_list(name):
    return [x for x in _p().GetString(name, "").split("|") if x]


def _set_list(name, values):
    _p().SetString(name, "|".join(values))


def hidden_tabs():
    return _get_list(HIDDEN_TABS)


def hidden_hud():
    return _get_list(HIDDEN_HUD)


def large_buttons():
    try:
        from . import customizedlg
        return bool(customizedlg.option(LARGE))
    except Exception:
        return _p().GetBool(LARGE, True)


# --------------------------------------------------------------------------- the CommandManager
def _catalog_titles():
    ""

    from . import catalog
    out = [t for t, _spec in catalog.TABS]
    try:
        from . import cmtabs
        every = [t for t, _l in cmtabs.all_tabs()]
        if any(t in every for t in out):
            out = every + [t for t in out if t not in every]
    except Exception as _fw_err:
        _fw_log("chromemenus.py:91", _fw_err)
    return out


def _cm_hidden():
    try:
        from . import cmtabs
        return set(cmtabs.hidden())
    except Exception:
        return set()


def set_tab_shown(shell, title, on):
    hidden = [t for t in hidden_tabs() if t != title]
    off = _cm_hidden()
    if not on:
        shown = [t for t in _catalog_titles() if t not in hidden and t not in off and t != title]
        if not shown:
            return False
        hidden.append(title)
    _set_list(HIDDEN_TABS, hidden)
    try:
        from . import cmtabs
        if title in [t for t, _l in cmtabs.all_tabs()] and (title in off) == bool(on):
            cm = [t for t in cmtabs.hidden() if t != title] + ([] if on else [title])
            cmtabs.set_hidden(cm)   # the CommandManager's own list (Customize Tabs) says the same
            cmtabs.apply()
            return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: CommandManager tabs list: %s\n" % error)
    try:
        shell._build_pages()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: CommandManager tabs: %s\n" % error)
    return True


def set_large_buttons(shell, on):
    try:
        from . import customizedlg
        customizedlg.set_option(LARGE, bool(on))
    except Exception:
        _p().SetBool(LARGE, bool(on))
    apply_large_buttons(shell)


def apply_large_buttons(shell):
    """The ribbon reads LargeButtonsWithText itself (RibbonPage.relayout): lay the pages out again."""
    top = getattr(shell, "topbar", None)
    if top is not None and alive(top):
        try:
            top._layout_pages()
            top._place()
        except Exception:
            top.update()


def _hook_pages():
    from . import ribbon
    bar = ribbon.TopBar
    if getattr(bar, "_fw_hidden_tabs", False):
        return
    original = bar.set_pages

    def set_pages(self, pages, keep_title=None):
        try:
            # Customize: buttons added to or taken off the tabs, and the tabs added (cmcustom.py)
            from . import cmcustom
            pages = cmcustom.adjust_pages(pages[0].shell if pages else None, list(pages))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: CommandManager customize: %s\n" % error)
        hidden = set(hidden_tabs())
        keep = [p for p in pages if p.title not in hidden] or list(pages)
        for p in pages:
            if p not in keep:
                ribbon.park(p)
        if keep_title in hidden:
            keep_title = keep[0].title
        return original(self, keep, keep_title)

    bar.set_pages = set_pages
    bar._fw_hidden_tabs = True


def _customize(shell, tab=None):
    from . import customizedlg
    box = customizedlg.show(shell)
    try:
        if tab and box is not None:
            box.tabs.setCurrentIndex(list(customizedlg.CustomizeDialog.TABS).index(tab))
    except Exception as _fw_err:
        _fw_log("chromemenus.py:182", _fw_err)
    return box


def _check(menu, label, on, run, name=None):
    a = menu.addAction(label)
    a.setCheckable(True)
    a.setChecked(bool(on))
    if name:
        a.setObjectName(name)
    a.triggered.connect(lambda checked=False: QtCore.QTimer.singleShot(0, lambda: run(checked)))
    return a


def _plain(menu, label, run):
    a = menu.addAction(label)
    a.triggered.connect(lambda checked=False: QtCore.QTimer.singleShot(0, run))
    return a


def _cm_hidden_titles():
    """Tabs the CommandManager knows but does not show now (cmtabs: Mold Tools, the FreeCAD extra tabs
    2D Drafting, Part Tools, Mesh Tools, FreeCAD Utilities ...): listed unticked, so a tick brings them back."""
    try:
        from . import cmtabs
        shown = set(_catalog_titles())
        return [t for t, _layout in cmtabs.all_tabs() if t not in shown]
    except Exception:
        return []


def _show_cm_tab(title):
    try:
        from . import cmtabs
        cmtabs.toggle(title, True)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: CommandManager tab %s: %s\n" % (title, error))


def _label(title):
    """A tab's name in the tab list: the one Rename Tab... gave it (cmgr-1119)."""
    try:
        from . import cmcustom
        return cmcustom.shown_name(title)
    except Exception:
        return title


def _fill_tab_ticks(shell, menu):
    hidden = set(hidden_tabs()) | _cm_hidden()
    for title in _catalog_titles():
        _check(menu, _label(title), title not in hidden, lambda on, t=title: set_tab_shown(shell, t, on))
    for title in _cm_hidden_titles():
        _check(menu, _label(title), False, lambda on, t=title: on and _show_cm_tab(t))
    top = getattr(shell, "topbar", None)
    for p in (top.pages if top is not None else []):
        if p.title not in _catalog_titles():
            _check(menu, _label(p.title), True, lambda on, page=p: (not on) and _drop_page(shell, page))


def show_description():
    """Show Description: the buttons' tooltips carry the command's description (a large tooltip); off, the
    name alone (Customize > Toolbars > Small tooltips)."""
    try:
        from . import customizedlg
        return bool(customizedlg.option("ShowTooltips")) and customizedlg.option("TooltipStyle") != 2
    except Exception:
        return True


def set_show_description(on):
    from . import customizedlg
    if on:
        customizedlg.set_option("ShowTooltips", True)
        customizedlg.set_option("TooltipStyle", int(_p().GetInt("LargeTooltipStyle", 0)))
    else:
        style = customizedlg.option("TooltipStyle")
        if style != 2:
            _p().SetInt("LargeTooltipStyle", int(style or 0))     # the large style comes back with the tick
        customizedlg.set_option("TooltipStyle", 2)
    refresh_tooltips()


def refresh_tooltips():
    """The buttons made already take the new tooltip setting (CommandManager, toolbars, flyouts)."""
    mw = Gui.getMainWindow()
    for b in mw.findChildren(QtWidgets.QWidget) if mw is not None else ():
        try:
            binding = getattr(b, "binding", None)
            if binding is not None and hasattr(binding, "tooltip"):
                b.setToolTip(binding.tooltip())
            elif getattr(b, "refresh_tooltip", None) is not None:
                b.refresh_tooltip()
        except Exception as _fw_err:
            _fw_log("chromemenus.py:description", _fw_err)


def tabs_menu(shell):
    ""

    menu = QtWidgets.QMenu(shell.window)
    menu.setObjectName("SWToolMenu_CommandManagerTabs")
    tabs = menu.addMenu(T_TABS)
    tabs.setObjectName("SWToolMenu_CommandManagerTabsList")
    hidden = set(hidden_tabs()) | _cm_hidden()
    for title in _catalog_titles():
        _check(tabs, _label(title), title not in hidden, lambda on, t=title: set_tab_shown(shell, t, on))
    for title in _cm_hidden_titles():
        _check(tabs, _label(title), False, lambda on, t=title: on and _show_cm_tab(t))
    top = getattr(shell, "topbar", None)
    for p in (top.pages if top is not None else []):
        if p.title not in _catalog_titles() and p.title not in _cm_hidden_titles():

            _check(tabs, _label(p.title), True, lambda on, page=p: (not on) and _drop_page(shell, page))
    _check(menu, T_LARGE, large_buttons(), lambda on: set_large_buttons(shell, on), "SWToolMenu_TabLargeButtons")
    _check(menu, T_DESCRIPTION, show_description(), set_show_description, "SWToolMenu_TabShowDescription")
    try:
        from . import cmcustom, customizedlg
        if customizedlg.is_open():
            cmcustom.fill_tab_menu(shell, menu, tab_under_pointer(shell))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: CommandManager tab menu: %s\n" % error)
    menu.addSeparator()
    c = _plain(menu, T_CUSTOMIZE_CM, lambda: _customize(shell, "Toolbars"))
    c.setObjectName("SWToolMenu_TabCustomizeCM")
    return menu


def tab_under_pointer(shell):
    """The title of the CommandManager tab under the pointer, or None."""
    from PySide import QtGui
    row = getattr(getattr(shell, "topbar", None), "tabs", None)
    if row is None or not alive(row):
        return None
    try:
        i = row._index_at(row.mapFromGlobal(QtGui.QCursor.pos()))
    except Exception:
        return None
    pages = getattr(shell.topbar, "pages", [])
    if i is None or not 0 <= i < len(row.titles):
        return None
    # the page's own title (a renamed tab shows another name on the row)
    return pages[i].title if i < len(pages) else row.titles[i]


def _drop_page(shell, page):
    try:
        shell.topbar.remove_page(page)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: CommandManager tab: %s\n" % error)


# --------------------------------------------------------------------------- toolbars
def _toolbars(shell):
    mw = shell.window
    out = []
    for tb in mw.findChildren(QtWidgets.QToolBar):
        if tb.parentWidget() is not mw or tb.objectName() in ("SWTopToolBar", "SWBottomToolBar"):
            continue
        a = tb.toggleViewAction()
        if not a.isVisible() or not tb.windowTitle():
            continue
        out.append(tb)
    out.sort(key=lambda t: t.windowTitle().lower())
    return out


def set_command_manager_shown(shell, on):
    top = getattr(shell, "topbar", None)
    if top is None:
        return

    for w in (top.tabs, top.stack, top.chevron, top.collapse_button):
        if alive(w):
            w.setVisible(on)
    top.setProperty("swCommandManagerOff", not on)
    _p().SetBool("CommandManagerOff", not on)
    try:
        if on:
            top._layout_pages()
        top._place()
    except Exception as _fw_err:
        _fw_log("chromemenus.py:310", _fw_err)


def command_manager_shown():
    return not _p().GetBool("CommandManagerOff", False)


class _ToolbarRow(QtWidgets.QCheckBox):
    """One toolbar of the Toolbars submenu: a tick in the gutter, highlighted under the pointer."""
    QSS = ("QCheckBox { padding: 3px 14px 3px 6px; spacing: 8px; background: transparent; }"
           "QCheckBox:hover { background: palette(highlight); color: palette(highlighted-text); }"
           "QCheckBox:disabled { color: palette(mid); }")

    def __init__(self, name, on, parent=None):
        super().__init__(name, parent)
        self.name = name
        self.setChecked(bool(on))
        self.setStyleSheet(self.QSS)
        self.setCursor(Qt.ArrowCursor)


def toolbar_rows(shell):
    ""

    from . import swtoolbars
    has_doc = App.ActiveDocument is not None
    names = sorted((title for title, _keys in swtoolbars.TOOLBARS), key=lambda t: t.lower())
    return [(name, swtoolbars.is_shown(name), has_doc or name not in NO_DOC_GREY) for name in names]


def _fill_toolbar_columns(shell, menu):
    ""
    from . import swtoolbars
    rows = toolbar_rows(shell)
    widget = QtWidgets.QWidget(menu)
    grid = QtWidgets.QGridLayout(widget)
    grid.setContentsMargins(2, 2, 2, 2)
    grid.setHorizontalSpacing(0)
    grid.setVerticalSpacing(0)
    half = (len(rows) + 1) // 2
    menu.rows = []
    for i, (name, on, enabled) in enumerate(rows):
        row = _ToolbarRow(name, on, widget)
        row.setEnabled(enabled)
        row.toggled.connect(lambda checked, n=name, m=menu: (m.close(), QtCore.QTimer.singleShot(
            0, lambda: swtoolbars.show(shell, n, checked))))
        grid.addWidget(row, i % half, 0 if i < half else 2)      # column 1 is the divider
        menu.rows.append((name, row))
    line = QtWidgets.QFrame(widget)
    line.setFrameShape(QtWidgets.QFrame.VLine)
    grid.addWidget(line, 0, 1, half, 1)
    act = QtWidgets.QWidgetAction(menu)
    act.setDefaultWidget(widget)
    menu.addAction(act)
    return menu


def toolbars_menu(shell):
    ""


    menu = QtWidgets.QMenu(shell.window)
    menu.setObjectName("SWToolMenu_Toolbars")
    has_doc = App.ActiveDocument is not None
    a = _check(menu, T_CM, command_manager_shown(), lambda on: set_command_manager_shown(shell, on), "SWToolMenu_EnableCM")
    a.setEnabled(has_doc)
    if has_doc:
        # open-document variant (seen in the Four-Cylinder video, assembly): Enable CommandManager,
        # Use Large Buttons with Text | Tabs > | Toolbars > | Customize...
        _check(menu, T_LARGE, large_buttons(), lambda on: set_large_buttons(shell, on), "SWToolMenu_LargeButtons")
    menu.addSeparator()
    if has_doc:
        tabs = menu.addMenu("Tabs")
        tabs.setObjectName("SWToolMenu_TabsList")
        _fill_tab_ticks(shell, tabs)
    sub = menu.addMenu(T_TOOLBARS)
    sub.setObjectName("SWToolMenu_ToolbarsList")
    _fill_toolbar_columns(shell, sub)
    menu.addSeparator()
    c = _plain(menu, T_CUSTOMIZE, lambda: _customize(shell))
    c.setObjectName("SWToolMenu_Customize")
    c.setEnabled(has_doc)
    return menu


# --------------------------------------------------------------------------- heads-up toolbar
def _hud(shell):
    overlay = getattr(shell, "overlay", None)
    hud = getattr(overlay, "hud", None)
    return hud if hud is not None and alive(hud) else None


def _hud_label(b):
    try:
        return b.binding.cmd.label
    except Exception:
        return b.toolTip() or "?"


def _hud_key(b):
    try:
        return b.binding.cmd.key
    except Exception:
        return _hud_label(b)


HUD_TOOLBAR = "View (Heads-Up)"     # Customize's toolbar name for the heads-up row


def hud_extras():
    """Commands added to the heads-up row in Customize (Commands tab, or a drop on the row)."""
    try:
        from . import customizedlg
        return customizedlg.toolbar_extras(HUD_TOOLBAR)
    except Exception:
        return []


def _sync_hud_extras(shell, hud):
    ""
    from . import catalog
    from .widgets import CommandButton
    want = [k for k in hud_extras() if k in catalog.BY_KEY]
    have = {}
    for b in list(hud.buttons):
        if getattr(b, "_fw_extra", False):
            if not alive(b) or _hud_key(b) not in want:
                hud.buttons.remove(b)
                if alive(b):
                    b.hide()
                    b.deleteLater()
            else:
                have[_hud_key(b)] = b
    stock = {_hud_key(b) for b in hud.buttons if not getattr(b, "_fw_extra", False)}
    for key in want:
        if key in have or key in stock:
            continue
        b = CommandButton(shell, key, None, "hud", hud)
        b.resize(b.sizeHint())
        b._fw_extra = True
        b.show()
        hud.buttons.append(b)


def add_hud_extra(shell, key):
    from . import catalog, customizedlg
    extras = hud_extras()
    if key in extras or key not in catalog.BY_KEY:
        return False
    hud = _hud(shell)
    if hud is not None and key in {_hud_key(b) for b in hud.buttons}:
        set_hud_shown(shell, key, True)       # a stock button hidden before: shown again
        return True
    customizedlg._set_list("ToolbarExtra." + HUD_TOOLBAR, extras + [key])
    apply_hud(shell)
    return True


def remove_hud_button(shell, key):
    """A button dragged off the heads-up row: an added one goes, a stock one is hidden."""
    from . import customizedlg
    extras = hud_extras()
    if key in extras:
        customizedlg._set_list("ToolbarExtra." + HUD_TOOLBAR, [k for k in extras if k != key])
        apply_hud(shell)
    else:
        set_hud_shown(shell, key, False)
    return True


def apply_hud(shell):
    hud = _hud(shell)
    if hud is None:
        return
    try:
        _sync_hud_extras(shell, hud)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: heads-up extras: %s\n" % error)
    hidden = set(hidden_hud())
    x = 0
    for b in hud.buttons:
        if not alive(b):
            continue
        on = _hud_key(b) not in hidden
        b.setVisible(on)
        if on:
            b.move(x, 0)
            x += b.width() + 1
    hud.resize(max(x, 1), hud.height())
    try:
        if hasattr(hud, "_relayout"):
            hud._relayout()         # Dynamic Annotation Views only while the part has 3D annotations
        hud.place()
    except Exception as _fw_err:
        _fw_log("chromemenus.py:502", _fw_err)


def set_hud_shown(shell, key, on):
    hidden = [k for k in hidden_hud() if k != key]
    if not on:
        hidden.append(key)
    _set_list(HIDDEN_HUD, hidden)
    apply_hud(shell)


def hud_menu(shell):
    menu = QtWidgets.QMenu(shell.window)
    menu.setObjectName("SWToolMenu_HeadsUp")
    hud = _hud(shell)
    hidden = set(hidden_hud())
    for b in (hud.buttons if hud is not None else []):
        key = _hud_key(b)
        _check(menu, _hud_label(b), key not in hidden, lambda on, k=key: set_hud_shown(shell, k, on))
    return menu


# --------------------------------------------------------------------------- Task Pane and PM title
def _task_tabs(shell):
    overlay = getattr(shell, "overlay", None)
    tabs = getattr(overlay, "tasks", None)
    return tabs if tabs is not None and alive(tabs) else None


def task_pane_menu(shell):
    ""
    menu = QtWidgets.QMenu(shell.window)
    menu.setObjectName("SWToolMenu_TaskPane")
    _plain(menu, "Customize", lambda: _customize(shell))
    return menu


def pm_header_menu(shell, header):
    menu = QtWidgets.QMenu(shell.window)
    menu.setObjectName("SWToolMenu_PMTitle")
    for native, mine in list(getattr(header, "buttons", [])):
        if mine is header.help:
            continue
        try:
            text = (mine.toolTip() or native.text()).replace("&", "")
            a = _plain(menu, text, mine.click)
            a.setEnabled(mine.isEnabled())
        except RuntimeError:
            continue
    menu.addSeparator()
    _check(menu, "Keep Visible", header.pin.isChecked(), lambda on: header.pin.setChecked(on))
    _plain(menu, "Help", header.show_help)
    return menu


# --------------------------------------------------------------------------- where the click is
def area_of(shell, widget):
    """'tabs', 'commandmanager', 'toolbar', 'statusbar', 'headsup' or None for the widget clicked."""
    top = getattr(shell, "topbar", None)
    hud = _hud(shell)
    tasks = _task_tabs(shell)
    w = widget
    while w is not None:
        if hud is not None and w is hud:
            return "headsup"
        if tasks is not None and w is tasks:
            return "taskpane"
        if w.objectName() == "SWTaskPane":
            row = widget is w or (widget.parentWidget() is w and widget is not getattr(w, "stack", None))
            return "taskpane" if row else None      # its title row only; the pages keep their own menus
        if w.objectName() == "SWStyle_PMHeader":
            S_HEADER[0] = w
            return "pmtitle"
        if top is not None and w is getattr(top, "tabs", None):
            return "tabs"
        if top is not None and w is top:
            return "commandmanager"
        if isinstance(w, QtWidgets.QStatusBar):
            return "statusbar"
        if isinstance(w, QtWidgets.QToolBar) and w.parentWidget() is shell.window \
                and w.objectName() not in ("SWTopToolBar", "SWBottomToolBar"):
            return "toolbar"
        if isinstance(w, (QtWidgets.QMenu, QtWidgets.QDockWidget, QtWidgets.QAbstractItemView)) \
                or w.inherits("QGraphicsView") or w.inherits("Gui::View3DInventorViewer"):
            return None
        w = w.parentWidget()
    return None


def menu_for(shell, area):
    if area == "tabs":
        return tabs_menu(shell)
    if area in ("commandmanager", "toolbar", "statusbar"):
        return toolbars_menu(shell)
    if area == "headsup":
        return hud_menu(shell)
    if area == "taskpane":
        return task_pane_menu(shell)
    if area == "pmtitle" and S_HEADER[0] is not None and alive(S_HEADER[0]):
        return pm_header_menu(shell, S_HEADER[0])
    return None


S_HEADER = [None]


class _Filter(QtCore.QObject):
    def __init__(self, shell):
        super().__init__(shell.window)
        self.shell = shell

    def eventFilter(self, obj, event):
        if event.type() != QtCore.QEvent.ContextMenu or not isinstance(obj, QtWidgets.QWidget):
            return False
        try:
            if not getattr(self.shell, "enabled", True) or obj.window() is not self.shell.window:
                return False
            area = area_of(self.shell, obj)
            if area is None:
                return False
            menu = menu_for(self.shell, area)
            if menu is None:
                return False
            LAST[0] = menu
            menu.popup(event.globalPos())
            return True
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: chrome menu: %s\n" % error)
            return False


_FILTER = []


def install(shell=None):
    if shell is None:
        from . import rcmenus
        shell = rcmenus.shell()
    if shell is None or _FILTER:
        return _FILTER[0] if _FILTER else None
    _hook_pages()
    f = _Filter(shell)
    events.register("chromemenus", (QtCore.QEvent.ContextMenu,), f.eventFilter)
    _FILTER.append(f)
    try:
        if hidden_tabs():
            shell._build_pages()
        if not command_manager_shown():
            set_command_manager_shown(shell, False)
        apply_hud(shell)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: chrome menus: %s\n" % error)
    return f


def remove():
    while _FILTER:
        f = _FILTER.pop()
        events.unregister("chromemenus")
