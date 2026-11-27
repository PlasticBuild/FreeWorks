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

from . import catalog, macrobuttons

Qt = QtCore.Qt
PARAM = "User parameter:BaseApp/Preferences/Mod/SolidWorksStyle/Customize"
MIME = "application/x-freeworks-command"
COMMAND = "SWStyle_Customize"
SHORTCUT_PREFS = "User parameter:BaseApp/Preferences/Shortcut"

TOOLBAR_DEFAULTS = {
    "LargeButtonsWithText": True, "IconSize": 0, "ShowTooltips": True, "TooltipStyle": 0,
    "ShowOnSelection": True, "QuickConfigurations": True, "QuickMates": True, "FlipAlignment": True,
    "ShowInShortcutMenu": True, "QatShowInMenuBar": True, "LockToolbars": False, "CustomizeMenuItems": True,

    "ShortcutBarSearch": True, "ShortcutBarSearchActivate": True,
}
ICON_SIZES = ((0, "Small", 20), (1, "Medium", 24), (2, "Large", 32))
TOOLTIP_STYLES = ("Large tooltips with images", "Large tooltips without images", "Small tooltips")
MODES = (("part", "Part"), ("assembly", "Assembly"), ("drawing", "Drawing"), ("sketch", "Sketch"))
MENU_TITLES = ("File", "Edit", "View", "Insert", "Tools", "Window", "Help")
MENU_CATEGORIES = ("File", "Edit", "View", "Insert", "Tools", "Simulation", "Window", "Help", "Others", "Search", "Macros")
POSITIONS = ("Default", "At Beginning", "At End", "Hidden")

POSITION_NAMES = (("Auto", "Default"), ("At Top", "At Beginning"), ("At Bottom", "At End"))

_open = []        # the open dialog, for the toolbars' drop test


# --------------------------------------------------------------------------- stored values
def _p():
    return App.ParamGet(PARAM)


def option(name, default=None):
    if default is None:
        default = TOOLBAR_DEFAULTS.get(name)
    g = _p()
    if isinstance(default, bool):
        return g.GetBool(name, default)
    if isinstance(default, int):
        return g.GetInt(name, default)
    if isinstance(default, float):
        return g.GetFloat(name, default)
    got = g.GetString(name, "")
    return got if got else (default or "")


def set_option(name, value):
    g = _p()
    if isinstance(value, bool):
        g.SetBool(name, value)
    elif isinstance(value, int):
        g.SetInt(name, value)
    elif isinstance(value, float):
        g.SetFloat(name, value)
    else:
        g.SetString(name, str(value))


def _list(name):
    text = _p().GetString(name, "")
    return [k for k in text.split("|") if k]


def _set_list(name, keys):
    _p().SetString(name, "|".join(k for k in keys if k))


def is_open():
    return bool(_open) and _open[0].isVisible()


def icon_px():
    return next((px for i, _n, px in ICON_SIZES if i == option("IconSize")), 20)


def _hud_changed(shell, name):
    """The heads-up row shows the commands added to the View (Heads-Up) toolbar."""
    if name == "View (Heads-Up)":
        try:
            from . import chromemenus
            chromemenus.apply_hud(shell)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: heads-up row: %s\n" % error)


# ---- what the owners read
def toolbar_extras(name):
    ""
    return [k for k in _list("ToolbarExtra." + name) if k in catalog.BY_KEY]


def shortcut_extras(mode):
    """Commands added to the S-key shortcut bar of a mode from the Shortcut Bars tab."""
    return [k for k in _list("ShortcutBar." + mode) if k in catalog.BY_KEY]


def shortcut_removed(mode):
    """Stock buttons taken off the S-key shortcut bar of a mode (Shortcut Bars tab, Remove)."""
    return [k for k in _list("ShortcutBarRemoved." + mode) if k]


def shortcut_order(mode):
    """The order the buttons were dragged into on the Shortcut Bars tab (cmorder-1121); empty = stock order."""
    return [k for k in _list("ShortcutBarOrder." + mode) if k]


def shortcut_ordered(mode, entries, key=lambda e: e):
    """entries in the bar's own order: the ones it names first, as named, then the rest as they were."""
    order = shortcut_order(mode)
    if not order:
        return list(entries)
    rank = {k: i for i, k in enumerate(order)}
    first = sorted((e for e in entries if key(e) in rank), key=lambda e: rank[key(e)])
    return first + [e for e in entries if key(e) not in rank]


def menu_override(title, label):
    """(text, position) for a menu entry from the Menus tab, or None."""
    text = _p().GetString("Menu.%s.%s" % (title, label), "")
    if not text:
        return None
    parts = text.split("|")         # text|position|menu (the menu it was moved to, Menus tab)
    return parts[0] or label, (parts[1] if len(parts) > 1 and parts[1] else "Default")


def menu_target(title, label):
    """The menu an entry was moved to on the Menus tab (Menu:), or None when it stays in title."""
    parts = _p().GetString("Menu.%s.%s" % (title, label), "").split("|")
    return parts[2] if len(parts) > 2 and parts[2] and parts[2] != title else None


def others_key(src, label):
    """The catalog key of the command called label in the Others or Macros category (Menus > Add)."""
    for title, keys in menu_categories():
        if title == src:
            for key in keys:
                cmd = catalog.BY_KEY.get(key)
                if cmd is not None and cmd.label == label:
                    return key
    return None


def moves_into(title):
    """[(from menu, label)] of the entries moved into the menu title."""
    out = []
    for name in _p().GetStrings():
        if name.startswith("Menu.") and name.count(".") >= 2:
            _m, src, label = name.split(".", 2)
            if menu_target(src, label) == title:
                out.append((src, label))
    return out


def tooltip_for(label, tip, extra=""):
    """The tooltip a button shows, after the Tooltips rows: none, large (name + help), or small (the name)."""
    if not option("ShowTooltips"):
        return ""
    style = option("TooltipStyle")
    if style == 2:
        return label
    parts = ["<b>%s</b>" % label]
    if tip:
        parts.append(tip)
    if extra:
        parts.append(extra)
    return "<br>".join(parts)


# ---- keyboard

SEARCH_DEFAULTS = {"SWStyle_Rebuild": "r", "Std_Refresh": "r", "SWStyle_ZoomFit": "zf", "Std_ViewFitAll": "zf",
                   "FreeWorks_Line": "l", "Sketcher_CreatePolyline": "l"}


def search_key(native):
    """The Keyboard tab's Search Shortcut of a command: letters that, typed in the command search
    box, put that command at the top of the list."""
    try:
        own = _p().GetString("SearchKey." + native, "")
        if own or _p().GetBool("SearchKeyOff." + native, False):
            return own
    except Exception:
        return ""
    return SEARCH_DEFAULTS.get(native, "")


def set_search_key(native, text):
    text = (text or "").strip()
    if text:
        _p().SetString("SearchKey." + native, text)
        _p().RemBool("SearchKeyOff." + native)
    else:
        _p().RemString("SearchKey." + native)
        if native in SEARCH_DEFAULTS:
            _p().SetBool("SearchKeyOff." + native, True)      # kbpage-1126: a removed default stays removed


def search_keys():
    """{search shortcut, lower case: set of command names} for the command search."""
    out = {}
    try:
        for name in _p().GetStrings():
            if name.startswith("SearchKey."):
                text = _p().GetString(name, "").strip().lower()
                if text:
                    out.setdefault(text, set()).add(name[len("SearchKey."):])
    except Exception as _fw_err:
        _fw_log("customizedlg.py:190", _fw_err)
    for native in SEARCH_DEFAULTS:      # kbpage-1126: the defaults no one changed
        text = search_key(native).strip().lower()
        if text and not _p().GetString("SearchKey." + native, ""):
            out.setdefault(text, set()).add(native)
    return out


def _sw_key_names(text):
    ""
    parts = []
    for k in (text or "").split(", "):
        bits = k.split("+")
        bits[-1] = {"Space": "SpaceBar", "Del": "Delete"}.get(bits[-1], bits[-1])
        parts.append("+".join(bits))
    return ", ".join(parts) if text else ""


def key_overrides():
    """{command name: key} set on the Keyboard tab (an empty key = no shortcut)."""
    out = {}
    g = _p()
    for name in g.GetStrings():
        if name.startswith("Key."):
            out[name[4:]] = g.GetString(name, "")
    return out


def _group_entry(name):
    """The QAction a group button (View Orientation, Selection Filter...) made for an entry command,
    which FreeCAD gives no action of its own: Ctrl+1 to Ctrl+7 sit on those."""
    try:
        from . import keys, swkeys
        groups = tuple(keys.COMMANDS) + tuple(swkeys.COMMANDS)
    except Exception:
        return None
    for group, cls in groups:
        if not hasattr(cls, "GetCommands"):
            continue
        try:
            entries = list(cls().GetCommands())
        except Exception:
            continue
        if name not in entries:
            continue
        try:
            cmd = Gui.Command.get(group)
            acts = [a for a in cmd.getAction() if isinstance(a, QtGui.QAction)] if cmd is not None else []
        except Exception:
            acts = []
        try:
            text = Gui.Command.get(name).getInfo().get("menuText", "").replace("&", "")
        except Exception:
            text = ""
        for a in acts:
            if a.objectName() == name or (text and a.text().replace("&", "") == text and a.objectName() != group):
                return a
    return None


def _actions(name):
    try:
        cmd = Gui.Command.get(name)
        actions = [a for a in cmd.getAction() if isinstance(a, QtGui.QAction)] if cmd is not None else []
    except Exception:
        actions = []
    if not actions:
        entry = _group_entry(name)
        if entry is not None:
            actions = [entry]
    if not actions and name in _KEY_ACTIONS:
        actions = [_KEY_ACTIONS[name]]
    if not actions and name.startswith("SWStyle_ToolbarToggle_"):
        try:
            from . import tbkeys
            tbkeys.attach()
            a = tbkeys.action(name)
            actions = [a] if a is not None else []
        except Exception as _fw_err:
            _fw_log("customizedlg.py:255", _fw_err)
    return actions


_KEY_ACTIONS = {}


def _keep_on_window(actions):
    ""


    mw = Gui.getMainWindow()
    if mw is None:
        return
    for a in actions:
        try:
            if a is not None and mw not in a.associatedObjects():
                mw.addAction(a)
        except Exception as _fw_err:
            _fw_log("customizedlg.py:274", _fw_err)


def _key_action(name):
    """An action for a command that no menu or button made one for yet, so its key has something to run."""
    a = _KEY_ACTIONS.get(name)
    if a is not None:
        return a
    mw = Gui.getMainWindow()
    a = QtGui.QAction(name, mw)
    a.setObjectName("SWKey_" + name)

    def run(_checked=False, name=name):
        try:
            from . import checkstate
            if checkstate.run(name):
                return
        except Exception as _fw_err:
            _fw_log("customizedlg.py:292", _fw_err)
        Gui.runCommand(name, 0)
    a.triggered.connect(run)
    _KEY_ACTIONS[name] = a
    return a


def apply_key(name, key, remember=True):
    """Gives the FreeCAD command its shortcut now and in FreeCAD's Shortcut preferences."""
    if name in _filter_keys():
        # filterkeys-1126: a key the key filters read (Enter, Tab, D, A...): kept here only, never on a QAction
        _APPLIED.add(name)
        if remember:
            set_option("Key." + name, key or "")
        return True
    actions = _actions(name)
    if remember and not _p().GetString("KeyOrig." + name, "") and not _p().GetBool("KeyOrigSet." + name, False):
        # the command's own shortcut, so Reset to Defaults can give it back (FreeCAD natives too)
        _p().SetString("KeyOrig." + name, current_key(name))
        _p().SetBool("KeyOrigSet." + name, True)
    _APPLIED.add(name)
    if not actions and key:
        actions = [_key_action(name)]
    for a in actions:
        a.setShortcut(QtGui.QKeySequence(key) if key else QtGui.QKeySequence())
    _keep_on_window(actions)
    prefs = App.ParamGet(SHORTCUT_PREFS)
    if key:
        prefs.SetString(name, key)
    else:
        prefs.SetString(name, "")
    if remember:
        set_option("Key." + name, key)
    return bool(actions)


def apply_startup():
    """Keys from the Keyboard tab come back after a restart (called when the menus install)."""
    try:
        from . import tbkeys
        tbkeys.attach()
    except Exception as _fw_err:
        _fw_log("customizedlg.py:328", _fw_err)
    for name, key in key_overrides().items():
        try:
            apply_key(name, key, remember=False)
        except Exception as _fw_err:
            _fw_log("customizedlg.py:333", _fw_err)
    apply_qat()


def apply_qat(shell=None):
    """Toolbars > Quick Access Toolbar > Show in the Menu Bar, after a restart too."""
    try:
        if shell is None:
            from . import shell as sh
            shell = sh.shell()
        qat = getattr(getattr(shell, "topbar", None), "qat", None)
    except Exception:
        qat = None
    if qat is None:
        return False
    try:        # extapps89: Show in the Menu Bar or in the CommandManager: the top bar places them
        shell.topbar._place()
        qat.relayout()
    except Exception as _fw_err:
        _fw_log("customizedlg.py:354", _fw_err)
    return True


def _filter_keys():
    try:
        from . import filterkeys
        return filterkeys.DEFAULTS
    except Exception:
        return {}


def current_key(name):
    if name in _filter_keys():
        from . import filterkeys        # filterkeys-1126
        return filterkeys.shown(name)
    for a in _actions(name):
        return a.shortcut().toString(QtGui.QKeySequence.NativeText)
    if name not in _APPLIED:
        # no button or menu entry made the command's action yet: its key is the one FreeCAD will give it
        try:
            cmd = Gui.Command.get(name)
            key = (cmd.getShortcut() if cmd is not None else "") or ""
            if not key and cmd is not None:
                from . import keys
                key = App.ParamGet(SHORTCUT_PREFS).GetString(name, dict(keys.KEYS).get(name, ""))
            return QtGui.QKeySequence(key).toString(QtGui.QKeySequence.NativeText)
        except Exception as _fw_err:
            _fw_log("customizedlg.py:371", _fw_err)
    return ""


_APPLIED = set()


# ---- mouse gestures
GESTURE_COUNTS = (("2v", "2 Gestures (Vertical)"), ("2h", "2 Gestures (Horizontal)"), ("3", "3 Gestures"),
                  ("4", "4 Gestures"), ("8", "8 Gestures"), ("12", "12 Gestures"))

GESTURE_ANGLES = {
    "2v": (90, 270), "2h": (0, 180), "3": (90, 330, 210), "4": (90, 0, 270, 180),
    "8": (90, 45, 0, 315, 270, 225, 180, 135),
    "12": (90, 60, 30, 0, 330, 300, 270, 240, 210, 180, 150, 120),
}
DIRECTION_NAMES = {90: "Up", 0: "Right", 270: "Down", 180: "Left", 45: "Up-Right", 315: "Down-Right",
                   225: "Down-Left", 135: "Up-Left", 60: "Up-Right (steep)", 30: "Right (up)", 330: "Right (down)",
                   300: "Down-Right (steep)", 240: "Down-Left (steep)", 210: "Left (down)", 150: "Left (up)",
                   120: "Up-Left (steep)"}

GESTURE_DEFAULTS = {
    ("4", "part"): ("ViewTop", "ViewRight", "ViewBottom", "ViewLeft"),
    ("4", "assembly"): ("ViewTop", "ViewRight", "ViewBottom", "ViewLeft"),
    ("4", "sketch"): ("SmartDimension", "Circle", "CornerRectangle", "Line"),
    ("4", "drawing"): ("SmartDimension", "DrawDetailView", "DrawNote", "DrawHoleCallout"),   # Interface read 11-20
    ("8", "part"): ("ViewTop", "ViewTrimetric", "ViewRight", "ZoomArea", "ViewBottom", "ViewBack", "ViewLeft", "ViewFront"),
    ("8", "assembly"): ("ViewTop", "ViewTrimetric", "ViewRight", "ZoomArea", "ViewBottom", "ViewBack", "ViewLeft", "ViewFront"),
    ("8", "sketch"): ("SmartDimension", "ExitSketch", "Circle", "SketchFillet", "CornerRectangle", "Trim", "Line", "NormalTo"),
    ("8", "drawing"): ("SmartDimension", "DrawCenterMark", "DrawDetailView", "DrawCenterline", "DrawNote", "DrawSectionView",
                       "DrawHoleCallout", "DrawModelView"),     # Interface read 11-20 (sw-keys-read-1120.md)

    # Mate/Measure, sketch Smart Dimension/exit Sketch, drawing Smart Dimension/Note; 3 adds the Shortcut Bar up.
    ("2v", "part"): ("PM_OK", "PM_Cancel"), ("2v", "assembly"): ("Mate", "Measure"),
    ("2v", "sketch"): ("SmartDimension", "ExitSketch"), ("2v", "drawing"): ("SmartDimension", "DrawNote"),
    ("2h", "part"): ("PM_OK", "PM_Cancel"), ("2h", "assembly"): ("Mate", "Measure"),
    ("2h", "sketch"): ("SmartDimension", "ExitSketch"), ("2h", "drawing"): ("SmartDimension", "DrawNote"),
    ("3", "part"): ("ShortcutBar", "PM_OK", "PM_Cancel"), ("3", "assembly"): ("ShortcutBar", "Mate", "Measure"),
    ("3", "sketch"): ("ShortcutBar", "SmartDimension", "ExitSketch"), ("3", "drawing"): ("ShortcutBar", "SmartDimension", "DrawNote"),
}

GESTURE_DIAGONALS_12 = {
    "part": ("ViewOrientation", "ZoomFit", "Pan", "Redo"), "assembly": ("ViewOrientation", "ZoomFit", "Pan", "Redo"),
    "sketch": ("RelConstruction", "Offset", "Spline", "Slot"),
    "drawing": ("OrdinateDimension", "CornerRectangle", "DrawBalloon", "DrawBOM"),   # Detail View is on the 8 ring now
}
GESTURE_DEFAULTS.update({
    ("12", m): GESTURE_DEFAULTS[("8", m)][:1] + (d[0],) + GESTURE_DEFAULTS[("8", m)][1:3] + (d[1],)
    + GESTURE_DEFAULTS[("8", m)][3:5] + (d[2],) + GESTURE_DEFAULTS[("8", m)][5:7] + (d[3],) + GESTURE_DEFAULTS[("8", m)][7:]
    for m, d in GESTURE_DIAGONALS_12.items()})


def gesture_count():
    got = _p().GetString("GestureCount", "")
    if got in dict(GESTURE_COUNTS):
        return got
    try:
        from . import paths
        return "8" if paths.params().GetInt("MouseGestureCount", 4) == 8 else "4"
    except Exception:
        return "4"


def set_gesture_count(count):
    set_option("GestureCount", count)
    try:
        from . import paths
        paths.params().SetInt("MouseGestureCount", 8 if count == "8" else 4)
    except Exception as _fw_err:
        _fw_log("customizedlg.py:440", _fw_err)


def gesture_keys(count, mode):
    """The command key of each direction (clockwise from the top; '' = nothing there)."""
    default = GESTURE_DEFAULTS.get((count, mode), ())
    text = _p().GetString("Gesture.%s.%s" % (count, mode), "")
    if text:
        keys = text.split("|")
        if len(keys) == len(default):
            return tuple(keys)
    return tuple(default)


def set_gesture_keys(count, mode, keys):
    _p().SetString("Gesture.%s.%s" % (count, mode), "|".join(keys))


def gesture_items(count, mode):
    """[(key, angle)] for gestures.py."""
    return [(k, a) for k, a in zip(gesture_keys(count, mode), GESTURE_ANGLES[count])]


def _label(key):
    cmd = catalog.BY_KEY.get(key)
    return cmd.label if cmd is not None else key


def _icon(shell, key):
    try:
        if shell is not None and key in catalog.BY_KEY:
            return shell.binding(key).icon()
    except Exception as _fw_err:
        _fw_log("customizedlg.py:473", _fw_err)
    return QtGui.QIcon()


# --------------------------------------------------------------------------- command lists
def categories():
    ""
    out = []
    seen = set()
    for title, spec in catalog.TABS:
        keys = []
        for row in spec:
            if not row:
                continue
            if row[0] == "large":
                keys.append(row[1])
                keys += list(row[2] or ())
            elif row[0] == "stack":
                for key, fly in row[1]:
                    keys.append(key)
                    keys += list(fly or ())
        keys = [k for k in dict.fromkeys(keys) if k in catalog.BY_KEY]
        if keys:
            out.append((title, keys))
            seen.update(keys)
    macro = ["MacroRun", "MacroRecord", "MacroStop", "MacroNew", "MacroEdit", macrobuttons.NEW_KEY] + macrobuttons.keys()
    macro = [k for k in macro if k in catalog.BY_KEY]
    out.append(("Macro", macro))
    seen.update(macro)
    hud = [k for k, _f in catalog.HEADS_UP if k in catalog.BY_KEY]
    out.append(("Heads-up View", hud))
    qat = [k for k, _f in catalog.QUICK_ACCESS if k in catalog.BY_KEY]
    out.append(("Quick Access", qat))
    from . import lazycmds          # a command this installation cannot have is not offered for a toolbar
    rest = [k for k in catalog.BY_KEY if k not in seen and k not in hud and k not in qat
            and lazycmds.state(catalog.BY_KEY[k]) != "none"]
    out.append(("Others", rest))
    return out


def toolbar_categories(cats=None):
    ""


    from . import swtoolbars
    cats = cats if cats is not None else categories()
    fly = []
    for _title, spec in catalog.TABS:
        for row in spec:
            if not row:
                continue
            if row[0] == "large" and row[2]:
                fly.append(row[1])
            elif row[0] == "stack":
                fly += [key for key, f in row[1] if f]
    fly = [k for k in dict.fromkeys(fly) if k in catalog.BY_KEY]
    bars, names = [], {}
    for name, keys in sorted(swtoolbars.TOOLBARS, key=lambda t: t[0].lower()):
        ks = [k for k in dict.fromkeys(keys) if k in catalog.BY_KEY]
        if ks:
            names[name.lower()] = len(bars)
            bars.append((name, ks))
    covered = {k for _n, ks in bars for k in ks}
    rest = []
    for title, ks in cats:
        left = [k for k in ks if k not in covered]
        if not left:
            continue
        if title.lower() in names:
            bars[names[title.lower()]][1].extend(left)
        else:
            rest.append((title, left))
        covered.update(left)
    every = list(dict.fromkeys(k for _t, ks in bars + rest for k in ks))
    return [("(All Toolbars)", every), ("Flyout Toolbars", fly)] + bars + rest



# Commands, File, Edit, View, Insert, Tools, Window, Help, then Others and Macros), not by CommandManager tab
MENU_ORDER = ("File", "Edit", "View", "Insert", "Tools", "Window", "Help")


def _menu_of():
    ""
    out = {}
    try:
        from . import swmenus
    except Exception as _fw_err:
        _fw_log("customizedlg.py:menu_of", _fw_err)
        return out

    def walk(title, entries, depth=0):
        if depth > 6 or not isinstance(entries, (tuple, list)):
            return
        for e in entries:
            if isinstance(e, str):
                if e in catalog.BY_KEY:
                    out.setdefault(e, title)
            elif isinstance(e, tuple) and len(e) >= 2:
                if isinstance(e[1], str) and e[1] in catalog.BY_KEY:
                    out.setdefault(e[1], title)
                elif isinstance(e[1], (tuple, list)) and not callable(e[1]):
                    walk(title, e[1], depth + 1)
    for t, entries in swmenus.MENUS:
        walk(t.replace("&", ""), entries)
    return out


SEARCH_KEYS = (("FW_SearchHelp", "Help", "SWStyle_SearchHelp", "Searches the help (H)."),
               ("FW_SearchCommands", "Commands", "SWStyle_SearchCommands", "Finds a command by name and runs it (W)."),
               ("FW_SearchFiles", "Files and Models", "SWStyle_SearchFiles", "Finds files and models (I)."))


def _sim_search_groups(groups):
    ""
    try:
        from . import addintabs
        sim = []
        for row in addintabs.TABS.get("Simulation", ()):
            if row and row[0] == "large":
                sim += [row[1]] + list(row[2] or ())
            elif row and row[0] == "stack":
                for k, fly in row[1]:
                    sim += [k] + list(fly or ())
        sim = [k for k in dict.fromkeys(sim) if k in catalog.BY_KEY]
        if sim:
            groups["Simulation"] = [k for k in sim if k not in [x for t, ks in groups.items() if t not in ("Others", "Simulation") for x in ks]]
            if "Others" in groups:
                groups["Others"] = [k for k in groups["Others"] if k not in groups["Simulation"]]
            if not groups["Simulation"]:
                del groups["Simulation"]
    except Exception as _fw_err:
        _fw_log("customizedlg.py:sim-group", _fw_err)
    have = set(Gui.listCommands())
    search = []
    for key, label, native, tip in SEARCH_KEYS:
        if native not in have:
            continue
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, (native,), None, tip)
        search.append(key)
    if search:
        groups["Search"] = search
    return groups


def menu_categories(cats=None):
    ""
    cats = categories() if cats is None else cats
    where = _menu_of()
    groups = {}
    for title, keys in cats:
        for key in keys:
            if title == "Macro":
                group = "Macros"
            else:
                group = where.get(key, "Others")
            groups.setdefault(group, [])
            if key not in groups[group]:
                groups[group].append(key)
    order = [t for t in MENU_ORDER if t in groups] + [t for t in groups if t not in MENU_ORDER and t not in ("Others", "Macros")]
    _sim_search_groups(groups)
    order = [t for t in order if t != "Simulation"]
    order += [t for t in ("Simulation", "Others", "Search", "Macros") if t in groups]
    return [(t, groups[t]) for t in order]



# Keyboard, /mnt/project-files/commands/sw2024-options/menus-and-shortcuts.md); they had landed under Others,
# some by another name
SW_KEY_ROWS = {
    "SWStyle_CloseDocument": ("File", "Close"),
    "SWStyle_BrowseRecentDocuments": ("File", "Browse Recent Documents"),
    "SWStyle_RebuildAllConfigurations": ("Edit", "Rebuild All Configurations"),
    "SWStyle_Redraw": ("View", "Redraw"),
    "SWStyle_ViewOrientation": ("View", "Orientation"),
    "SWStyle_PreviousView": ("View", "Previous View"),
    "SWStyle_QuickSnapsToggle": ("View", "Quick Snaps"),
    "SWStyle_FeatureManagerArea": ("View", "FeatureManager Tree Area"),
    "SWStyle_ToggleCommandManager": ("View", "Toolbars"),
    "SWStyle_TaskPaneKey": ("View", "Task Pane"),
    "Std_MainFullscreen": ("View", "Full Screen"),
    "SWStyle_SelectOverGeometry": ("Tools", "Select over Geometry"),
    "SWStyle_SearchHelp": ("Help", "Help"),
    "SWStyle_SearchCommands": ("Help", "Commands"),
    "SWStyle_SearchFiles": ("Help", "Files and Models"),
    "SWStyle_ForceRebuild": ("Others", "Force Rebuild"),
    "SWStyle_NextCommandManagerTab": ("Others", "Next Command Manager Tab"),
    "SWStyle_PreviousCommandManagerTab": ("Others", "Previous Command Manager Tab"),
}


def _sw_key_rows(rows):
    ""

    out = []
    for title, key, label, native in rows:
        if native in SW_KEY_ROWS:
            title, label = SW_KEY_ROWS[native]
        out.append((title, key, label, native))
    sw_named = {l for _t, _k, l, n in out if not n.startswith("Std_")}
    final = []
    for title, key, label, native in out:
        if native.startswith("Std_") and native not in SW_KEY_ROWS and label in sw_named:
            label += " (FreeCAD)"
        final.append((title, key, label, native))
    return final


_NAV_KEYS = (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right, Qt.Key_PageUp, Qt.Key_PageDown, Qt.Key_Home,
             Qt.Key_End, Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape, Qt.Key_Shift,
             Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr, Qt.Key_CapsLock, Qt.Key_NumLock)


class KeyTable(QtWidgets.QTableWidget):
    ""


    def __init__(self, rows, cols, parent=None):
        super().__init__(rows, cols, parent)
        self.pressed_key = None          # the dialog's set_shortcut for the picked row, set by it

    def keyPressEvent(self, e):
        try:
            seq = self._sequence(e)
        except Exception as _fw_err:
            _fw_log("customizedlg.py:keytable", _fw_err)
            seq = ""
        if not seq:
            return super().keyPressEvent(e)
        self.pressed_key(self.currentRow(), seq)
        e.accept()

    def _sequence(self, e):
        """The shortcut text of the key press, or '' when it is a key that moves about the list."""
        row = self.currentRow()
        key = int(e.key())
        if row < 0 or self.currentColumn() == 3 or self.pressed_key is None or key in [int(k) for k in _NAV_KEYS]:
            return ""
        mods = e.modifiers()
        held = bool(mods & Qt.ControlModifier) or bool(mods & Qt.AltModifier)
        fkey = int(Qt.Key_F1) <= key <= int(Qt.Key_F35)
        if key == int(Qt.Key_unknown) or not (held or fkey or e.text().strip()):
            return ""
        try:
            seq = QtGui.QKeySequence(e.keyCombination())          # Qt 6
        except Exception:
            seq = QtGui.QKeySequence(int(mods) | key)               # Qt 5
        return seq.toString(QtGui.QKeySequence.NativeText)


def _hint(button, text):
    """A button pressed with nothing picked says what to pick next to it (never a silent click)."""
    # customize-1119: NO DEAD CONTROLS, an enabled button never does nothing
    try:
        button = button if isinstance(button, QtWidgets.QWidget) else None
        if button is not None:
            QtWidgets.QToolTip.showText(button.mapToGlobal(QtCore.QPoint(0, button.height())), text, button)
            button.setProperty("swHint", text)
    except Exception as _fw_err:
        _fw_log("customizedlg.py:hint", _fw_err)


class CommandGrid(QtWidgets.QListWidget):
    """The buttons of a category: icons to drag onto a toolbar or the shortcut bar."""

    def __init__(self, shell, parent=None):
        super().__init__(parent)
        self.shell = shell
        self.setViewMode(QtWidgets.QListWidget.IconMode)
        self.setIconSize(QtCore.QSize(24, 24))
        self.setGridSize(QtCore.QSize(34, 34))
        self.setResizeMode(QtWidgets.QListWidget.Adjust)
        self.setMovement(QtWidgets.QListWidget.Static)
        # Static movement turns dragging off in Qt: set it again after, or no button could be dragged out
        self.setDragEnabled(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)
        self.setSelectionMode(QtWidgets.QListWidget.SingleSelection)

    def set_keys(self, keys):
        self.clear()
        for key in keys:
            item = QtWidgets.QListWidgetItem(_icon(self.shell, key), "")
            item.setData(Qt.UserRole, key)
            item.setToolTip(tooltip_for(_label(key), catalog.BY_KEY[key].tip) or _label(key))
            self.addItem(item)

    def mimeData(self, items):
        data = QtCore.QMimeData()
        if items:
            data.setData(MIME, items[0].data(Qt.UserRole).encode())
        return data

    def mimeTypes(self):
        return [MIME]

    def contextMenuEvent(self, e):
        item = self.itemAt(e.pos())
        key = item.data(Qt.UserRole) if item is not None else None
        if not macrobuttons.is_button(key):
            return
        menu = QtWidgets.QMenu(self)
        edit = menu.addAction("Edit Macro Button...")
        delete = menu.addAction("Delete Macro Button")
        chosen = menu.exec(e.globalPos())
        dlg = self.window()
        if chosen is edit and hasattr(dlg, "edit_macro_button"):
            dlg.edit_macro_button(key)
        elif chosen is delete and hasattr(dlg, "delete_macro_button"):
            dlg.delete_macro_button(key)

    def current_key(self):
        item = self.currentItem()
        return item.data(Qt.UserRole) if item is not None else None


class DropList(QtWidgets.QListWidget):
    ""

    dropped = QtCore.Signal(str)
    placed = QtCore.Signal(str, int, bool)      # key, the row it was let go at, moved along the bar (cmorder-1121)
    dragged_off = QtCore.Signal(object)
    delete_pressed = QtCore.Signal()

    def __init__(self, shell, parent=None):
        super().__init__(parent)
        self.shell = shell
        self.setAcceptDrops(True)
        self.setViewMode(QtWidgets.QListWidget.IconMode)
        self.setIconSize(QtCore.QSize(24, 24))
        self.setGridSize(QtCore.QSize(34, 34))
        self.setResizeMode(QtWidgets.QListWidget.Adjust)
        self.setMovement(QtWidgets.QListWidget.Static)
        self.setDragEnabled(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDrop)
        self._dragging = None

    def mimeData(self, items):
        data = QtCore.QMimeData()
        if items:
            data.setData(MIME, items[0].data(Qt.UserRole).encode())
        return data

    def mimeTypes(self):
        return [MIME]

    def startDrag(self, actions):
        item = self.currentItem()
        if item is None:
            return
        drag = QtGui.QDrag(self)
        drag.setMimeData(self.mimeData([item]))
        drag.setPixmap(item.icon().pixmap(24, 24))
        self._dragging = item
        try:
            result = drag.exec_(Qt.MoveAction | Qt.CopyAction, Qt.MoveAction)
        finally:
            self._dragging = None
        if result == Qt.IgnoreAction and self.rect().contains(self.mapFromGlobal(QtGui.QCursor.pos())) is False:
            self.dragged_off.emit(item)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.currentItem() is not None:
            self.delete_pressed.emit()
            return
        super().keyPressEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()

    def drop_row(self, pos):
        """The row a button let go at pos takes: the item under it (after it on its right half), else the end."""
        index = self.indexAt(pos)
        if not index.isValid():
            return self.count()
        rect = self.visualRect(index)
        return index.row() + (1 if pos.x() > rect.center().x() else 0)

    def dropEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            key = bytes(e.mimeData().data(MIME)).decode()
            self.placed.emit(key, self.drop_row(e.position().toPoint()), self._dragging is not None)
            e.acceptProposedAction()


# --------------------------------------------------------------------------- the dialog
class CustomizeDialog(QtWidgets.QDialog):
    TABS = ("Toolbars", "Shortcut Bars", "Commands", "Menus", "Keyboard", "Mouse Gestures")

    RESETS = ("SWCustomizeToolbarsReset", "SWCustomizeShortcutReset", "SWCustomizeCommandsReset", "SWCustomizeMenusReset",
              "SWCustomizeKeysReset", "SWCustomizeGesturesReset")

    def __init__(self, shell=None, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.shell = shell
        self.setObjectName("SWCustomize")
        self.setWindowTitle("Customize")
        self.resize(760, 560)
        lay = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget(self)
        self.tabs.setObjectName("SWCustomizeTabs")
        lay.addWidget(self.tabs, 1)
        self.tabs.addTab(self._toolbars_tab(), "Toolbars")
        self.tabs.addTab(self._shortcut_bars_tab(), "Shortcut Bars")
        self.tabs.addTab(self._commands_tab(), "Commands")
        self.tabs.addTab(self._menus_tab(), "Menus")
        self.tabs.addTab(self._keyboard_tab(), "Keyboard")
        self.tabs.addTab(self._gestures_tab(), "Mouse Gestures")
        row = QtWidgets.QHBoxLayout()
        reset = QtWidgets.QPushButton("Reset to Defaults", self)
        reset.setObjectName("SWCustomizeReset")
        reset.clicked.connect(self._reset_current)
        row.addWidget(reset)
        for name in self.RESETS:
            b = self.findChild(QtWidgets.QPushButton, name)
            if b is not None:
                b.setVisible(False)         # job 81: the one at the foot runs it
        row.addStretch(1)
        for text, slot in (("OK", self.accept), ("Cancel", self.reject), ("Help", self.help)):
            b = QtWidgets.QPushButton(text, self)
            b.setObjectName("SWCustomize" + text)
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)
        _open[:] = [self]
        try:

            from . import cmcustom
            cmcustom.start(shell)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: CommandManager customize: %s\n" % error)

    def _reset_current(self):
        ""
        b = self.findChild(QtWidgets.QPushButton, self.RESETS[self.tabs.currentIndex()])
        if b is not None:
            b.click()

    def _shortcut_window(self):
        ""

        win = getattr(self, "sb_window", None)
        if win is None:
            return
        on = self.tabs.currentIndex() == 1 and self.isVisible()
        if on:
            mode = self.sb_mode.currentData()
            win.setWindowTitle("%s Shortcuts toolbar" % dict(MODES).get(mode, "Part"))
            if not win.isVisible():
                g = self.frameGeometry()
                win.move(g.right() + 8, g.top() + 60)
                win.show()
        else:
            win.hide()

    def showEvent(self, e):
        super().showEvent(e)
        from . import safe_later as _sl; _sl.later(0, self._shortcut_window, self, "sb_mode")

    def _stop_cm(self):
        win = getattr(self, "sb_window", None)
        if win is not None:
            win.hide()
        try:
            from . import cmcustom
            cmcustom.stop()
        except Exception as _fw_err:
            _fw_log("customizedlg.py:633", _fw_err)

    def closeEvent(self, e):
        _open[:] = []
        self._stop_cm()
        super().closeEvent(e)

    def done(self, r):
        _open[:] = []
        self._stop_cm()
        super().done(r)

    def help(self):
        try:
            from . import helpmenu
            from . import helpguide
            if helpguide.show_topic("customize") is None:
                helpmenu.show("home", search="customize")
        except Exception as _fw_err:
            _fw_log("customizedlg.py:650", _fw_err)

    # ---- Toolbars
    def _toolbars_tab(self):
        from . import swtoolbars
        w = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(w)
        left = QtWidgets.QVBoxLayout()
        kind = {"part": "Part", "assembly": "Assembly", "drawing": "Drawing"}.get(swtoolbars.doc_kind(), "Part")
        left.addWidget(QtWidgets.QLabel("Toolbars"))
        self.toolbar_list = QtWidgets.QListWidget(w)
        self.toolbar_list.setObjectName("SWCustomizeToolbars")
        for name, _keys in swtoolbars.TOOLBARS:
            item = QtWidgets.QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if swtoolbars.listed_shown(name) else Qt.Unchecked)    # cmmenu-1126
            self.toolbar_list.addItem(item)
            # no greyed rows (NO DEAD CONTROLS): a toolbar with no buttons and no window is left off the list
            item.setHidden(not swtoolbars.keys_of(name) and swtoolbars.find(name) is None
                           and name not in swtoolbars.PANES)
        self.toolbar_list.itemChanged.connect(self._toolbar_ticked)
        left.addWidget(self.toolbar_list, 1)
        lay.addLayout(left, 1)
        right = QtWidgets.QVBoxLayout()
        self.cm_check = QtWidgets.QCheckBox("Enable CommandManager", w)
        self.cm_check.setObjectName("SWCustomizeEnableCM")
        self.cm_check.setChecked(swtoolbars.command_manager_enabled(self.shell))
        self.cm_check.toggled.connect(lambda on: swtoolbars.command_manager_enabled(self.shell) != on and swtoolbars.toggle_command_manager(self.shell))
        right.addWidget(self.cm_check)
        self.large_check = self._bool_check(w, "Use large buttons with text", "LargeButtonsWithText", self._relayout)
        right.addWidget(self.large_check)
        size = QtWidgets.QGroupBox("Icon size", w)
        sl = QtWidgets.QHBoxLayout(size)
        self.size_radios = []
        for index, name, _px in ICON_SIZES:
            r = QtWidgets.QRadioButton(name, size)
            r.setChecked(option("IconSize") == index)
            r.toggled.connect(lambda on, i=index: on and (set_option("IconSize", i), self._icon_size()))
            sl.addWidget(r)
            self.size_radios.append(r)
        right.addWidget(size)
        tips = QtWidgets.QGroupBox("Tooltips", w)
        tl = QtWidgets.QVBoxLayout(tips)
        self.tip_check = self._bool_check(tips, "Show tooltips", "ShowTooltips", self._tooltips)
        tl.addWidget(self.tip_check)
        self.tip_radios = []
        for i, name in enumerate(TOOLTIP_STYLES):
            r = QtWidgets.QRadioButton(name, tips)
            r.setChecked(option("TooltipStyle") == i)
            r.toggled.connect(lambda on, i=i: on and (set_option("TooltipStyle", i), self._tooltips()))
            tl.addWidget(r)
            self.tip_radios.append(r)
        right.addWidget(tips)
        ctx = QtWidgets.QGroupBox("Context toolbar", w)
        cl = QtWidgets.QVBoxLayout(ctx)
        for text, name in (("Show on selection", "ShowOnSelection"), ("Show quick configurations", "QuickConfigurations"),
                           ("Show quick mates", "QuickMates"), ("Show flip alignment and lock rotation after quick mates", "FlipAlignment"),
                           ("Show in shortcut menu", "ShowInShortcutMenu")):
            cl.addWidget(self._bool_check(ctx, text, name))
        right.addWidget(ctx)
        qat = QtWidgets.QGroupBox("Quick Access Tools", w)
        ql = QtWidgets.QVBoxLayout(qat)

        self.qat_menu = QtWidgets.QRadioButton("Show in the Menu Bar", qat)
        self.qat_menu.setObjectName("SWCustomize_QatShowInMenuBar")
        self.qat_cm = QtWidgets.QRadioButton("Show in the CommandManager", qat)
        self.qat_cm.setObjectName("SWCustomize_QatShowInCommandManager")
        on_menu = bool(option("QatShowInMenuBar"))
        self.qat_menu.setChecked(on_menu)
        self.qat_cm.setChecked(not on_menu)
        self.qat_menu.toggled.connect(lambda on: (set_option("QatShowInMenuBar", bool(on)), self._qat()))
        ql.addWidget(self.qat_menu)
        ql.addWidget(self.qat_cm)
        right.addWidget(qat)

        right.addWidget(self._bool_check(w, "Lock CommandManager and toolbars", "LockToolbars", self._lock))
        right.addStretch(1)
        reset = QtWidgets.QPushButton("Reset to Defaults", w)
        reset.setObjectName("SWCustomizeToolbarsReset")
        reset.clicked.connect(lambda: self._reset_ask("SWCustomizeToolbarsResetAsk", (
            ("Toolbars tab options", self._reset_toolbars),
            ("CommandManager", self._reset_cm),
            ("All customizations", lambda: self._reset_all(ask=False)))))
        right.addWidget(reset, 0, Qt.AlignRight)
        lay.addLayout(right, 1)
        return w

    def _reset_ask(self, name, choices):
        ""
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question, "Customize", "What do you want to reset to the defaults?",
                                    QtWidgets.QMessageBox.NoButton, self)
        box.setObjectName(name)
        buttons = []
        for i, (text, slot) in enumerate(choices):
            role = QtWidgets.QMessageBox.DestructiveRole if text == "All customizations" else QtWidgets.QMessageBox.AcceptRole
            buttons.append((box.addButton(text, role), slot))
        box.addButton(QtWidgets.QMessageBox.Cancel)
        box.setDefaultButton(buttons[0][0])
        box.exec_()
        for b, slot in buttons:
            if box.clickedButton() is b:
                slot()
                return True
        return False

    def _reset_cm(self):
        """Reset to Defaults > CommandManager: its tabs and buttons as they came."""
        try:
            from . import cmcustom
            cmcustom.reset(self.shell)
        except Exception as _fw_err:
            _fw_log("customizedlg.py:reset_cm", _fw_err)

    def _bool_check(self, parent, text, name, after=None):
        c = QtWidgets.QCheckBox(text, parent)
        c.setObjectName("SWCustomize_" + name)
        c.setChecked(option(name))

        def changed(on):
            set_option(name, bool(on))
            if after is not None:
                after()
        c.toggled.connect(changed)
        return c

    def _toolbar_ticked(self, item):
        from . import swtoolbars
        swtoolbars.listed_show(self.shell, item.text(), item.checkState() == Qt.Checked)     # cmmenu-1126

    def _relayout(self):
        top = getattr(self.shell, "topbar", None) if self.shell is not None else None
        if top is not None:
            try:
                top._place()
            except Exception:
                top.update()

    def _icon_size(self):
        from . import swtoolbars
        swtoolbars.apply_icon_size()

    def _tooltips(self):
        mw = Gui.getMainWindow()
        for b in mw.findChildren(QtWidgets.QWidget) if mw is not None else ():
            refresh = getattr(b, "refresh_tooltip", None)
            if refresh is not None:
                try:
                    refresh()
                except Exception as _fw_err:
                    _fw_log("customizedlg.py:756", _fw_err)

    def _qat(self):
        apply_qat(self.shell)

    def _reset_toolbars(self):
        for name in ("LargeButtonsWithText", "IconSize", "ShowTooltips", "TooltipStyle", "ShowOnSelection",
                     "QuickConfigurations", "QuickMates", "FlipAlignment", "ShowInShortcutMenu", "QatShowInMenuBar"):
            _p().RemString(name)
        self.large_check.setChecked(True)
        self.size_radios[0].setChecked(True)
        self.tip_check.setChecked(True)
        self.tip_radios[0].setChecked(True)
        for c in self.findChildren(QtWidgets.QCheckBox):
            if c.objectName() in ("SWCustomize_ShowOnSelection", "SWCustomize_QuickConfigurations", "SWCustomize_QuickMates",
                                  "SWCustomize_FlipAlignment", "SWCustomize_ShowInShortcutMenu"):
                c.setChecked(True)
        self.qat_menu.setChecked(True)
        self._relayout(); self._icon_size(); self._tooltips(); self._qat()

    # ---- Shortcut Bars
    def _shortcut_bars_tab(self):
        ""



        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(QtWidgets.QLabel("Select a Toolbar or search, then drag a button to a Shortcut Bar", w))
        self.sb_search = self._search_box(w, "SWCustomizeShortcutSearch", lambda: self.sb_grid, lambda: self.sb_cats)
        find = QtWidgets.QHBoxLayout()
        find.addWidget(QtWidgets.QLabel("Search for:", w))
        find.addWidget(self.sb_search, 1)
        lay.addLayout(find)
        mid = QtWidgets.QHBoxLayout()
        self.sb_cats = QtWidgets.QListWidget(w)
        self.sb_cats.setObjectName("SWCustomizeShortcutCategories")
        self.sb_grid = CommandGrid(self.shell, w)
        self.sb_grid.setObjectName("SWCustomizeShortcutGrid")
        self._cats = categories()
        self._tcats = toolbar_categories(self._cats)
        for title, _keys in self._tcats:
            self.sb_cats.addItem(title)
        self.sb_cats.currentRowChanged.connect(lambda row: self.sb_grid.set_keys(self._tcats[row][1]) if row >= 0 else None)
        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("Toolbars:", w))
        left.addWidget(self.sb_cats, 1)
        mid.addLayout(left, 1)
        buttons = QtWidgets.QGroupBox("Buttons", w)
        QtWidgets.QVBoxLayout(buttons).addWidget(self.sb_grid)
        mid.addWidget(buttons, 2)
        lay.addLayout(mid, 1)

        self.sb_mode = QtWidgets.QComboBox(w)
        self.sb_mode.setObjectName("SWCustomizeShortcutMode")
        for mode, name in MODES:
            self.sb_mode.addItem(name, mode)
        self.sb_mode.setVisible(False)
        pick = QtWidgets.QGroupBox("Select a Shortcut Toolbar to Customize", w)
        pl = QtWidgets.QHBoxLayout(pick)
        self.sb_pick = QtWidgets.QButtonGroup(pick)
        pictures = {"part": "BossExtrude", "assembly": "InsertComponents", "drawing": "DrawModelView", "sketch": "Sketch"}
        for i, (mode, name) in enumerate(MODES):
            b = QtWidgets.QToolButton(pick)
            b.setObjectName("SWCustomizeShortcutPick_" + mode)
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setToolTip(name)
            b.setIconSize(QtCore.QSize(32, 32))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setText(name)
            try:
                b.setIcon(_icon(self.shell, pictures[mode]))
            except Exception as _fw_err:
                _fw_log("customizedlg.py:sb-pick", _fw_err)
            self.sb_pick.addButton(b, i)
            pl.addWidget(b)
        pl.addStretch(1)
        self.sb_pick.button(0).setChecked(True)
        self.sb_pick.idClicked.connect(self.sb_mode.setCurrentIndex)
        self.sb_mode.currentIndexChanged.connect(lambda i: (self.sb_pick.button(i).setChecked(True), self._fill_shortcut_bar(),
                                                            self._shortcut_window()))
        lay.addWidget(pick)
        desc = QtWidgets.QGroupBox("Description", w)
        dl = QtWidgets.QVBoxLayout(desc)
        self.sb_desc = QtWidgets.QLabel("Click or hover over a button to see its description", desc)
        self.sb_desc.setWordWrap(True)
        dl.addWidget(self.sb_desc)
        self.sb_grid.currentItemChanged.connect(lambda cur, _p: self._describe(self.sb_desc, cur))
        self.sb_grid.setMouseTracking(True)
        self.sb_grid.itemEntered.connect(lambda item: self._describe(self.sb_desc, item))
        lay.addWidget(desc)
        self.sb_search_on = self._bool_check(w, "Show Command Search in the shortcut bars", "ShortcutBarSearch")
        self.sb_search_go = self._bool_check(w, "Activate Command Search when the shortcut bar is launched",
                                             "ShortcutBarSearchActivate")
        self.sb_search_go.setContentsMargins(20, 0, 0, 0)
        self.sb_search_go.setEnabled(self.sb_search_on.isChecked())
        self.sb_search_on.toggled.connect(self.sb_search_go.setEnabled)
        lay.addWidget(self.sb_search_on)
        lay.addWidget(self.sb_search_go)
        # the bar itself, in a small tool window beside the dialog
        self.sb_window = QtWidgets.QWidget(self, Qt.Tool)
        self.sb_window.setObjectName("SWCustomizeShortcutWindow")
        wl = QtWidgets.QVBoxLayout(self.sb_window)
        wl.setContentsMargins(4, 4, 4, 4)
        self.sb_list = DropList(self.shell, self.sb_window)
        self.sb_list.setObjectName("SWCustomizeShortcutBar")
        self.sb_list.setFixedSize(6 * 34 + 12, 4 * 34 + 8)
        self.sb_list.dropped.connect(self._shortcut_dropped)
        self.sb_list.placed.connect(self._shortcut_placed)
        self.sb_list.dragged_off.connect(self._shortcut_dragged_off)
        wl.addWidget(self.sb_list)
        self.tabs.currentChanged.connect(lambda _i: self._shortcut_window())

        remove = QtWidgets.QPushButton("Remove", w)
        remove.setObjectName("SWCustomizeShortcutRemove")
        remove.clicked.connect(self._shortcut_remove)
        remove.setVisible(False)
        self.sb_list.delete_pressed.connect(remove.click)
        reset = QtWidgets.QPushButton("Reset to Defaults", w)
        reset.setObjectName("SWCustomizeShortcutReset")
        reset.clicked.connect(self._shortcut_reset)
        reset.setVisible(False)
        lay.addWidget(remove)
        lay.addWidget(reset)
        self.sb_cats.setCurrentRow(0)
        self._fill_shortcut_bar()
        return w

    def _shortcut_dragged_off(self, item):
        ""
        self.sb_list.setCurrentItem(item)
        self._shortcut_remove()

    def _describe(self, label, item):
        key = item.data(Qt.UserRole) if item is not None else None
        cmd = catalog.BY_KEY.get(key) if key else None
        label.setText("<b>%s</b>: %s" % (cmd.label, cmd.tip) if cmd is not None else "")

    def _describe_row(self, label, table, row):
        """The Description box under the Keyboard and Mouse Gestures lists: the picked row's command help."""
        item = table.item(row, 1) if row >= 0 else None
        text = ""
        if item is not None:
            key = item.data(Qt.UserRole + 1) if table is self.key_table else item.data(Qt.UserRole)
            cmd = catalog.BY_KEY.get(key) if key else None
            if cmd is not None:
                text = "<b>%s</b>: %s" % (cmd.label, cmd.tip)
            elif table is self.key_table:
                native = item.data(Qt.UserRole)
                try:
                    info = Gui.Command.get(native).getInfo()
                    tip = (info.get("toolTip", "") or info.get("statusTip", "")).split("\n")[0]
                    text = "<b>%s</b>: %s" % (item.text(), tip) if tip else "<b>%s</b>" % item.text()
                except Exception as _fw_err:
                    _fw_log("customizedlg.py:describe-row", _fw_err)
        label.setText(text)

    def _sb_keys(self, mode):
        from . import keys
        # rcmenus pkg45 added keys.BARS (part, assembly, drawing, sketch); older keys.py has no drawing bar
        bars = getattr(keys, "BARS", None) or {"sketch": keys.SKETCH_BAR, "assembly": keys.ASSEMBLY_BAR}
        entries, _rows = bars.get(mode, keys.PART_BAR)
        out = []
        for e in entries:
            out.append(e if isinstance(e, str) else e[0])
        return [k for k in out if k in catalog.BY_KEY]

    def _fill_shortcut_bar(self):
        mode = self.sb_mode.currentData()
        self.sb_list.clear()
        gone = shortcut_removed(mode)
        rows = [(key, "default") for key in self._sb_keys(mode) if key not in gone]
        rows += [(key, "extra") for key in shortcut_extras(mode)]
        for key, kind in shortcut_ordered(mode, rows, lambda r: r[0]):
            item = QtWidgets.QListWidgetItem(_icon(self.shell, key), "")
            item.setData(Qt.UserRole, key)
            item.setData(Qt.UserRole + 1, kind)
            item.setToolTip(_label(key) + (" (added)" if kind == "extra" else ""))
            self.sb_list.addItem(item)

    def _shortcut_placed(self, key, row, moving):
        ""
        before = [self.sb_list.item(i).data(Qt.UserRole) for i in range(self.sb_list.count())]
        if not moving:
            self._shortcut_dropped(key)
        keys = [k for k in before if k != key]
        at = row - sum(1 for k in before[:row] if k == key)
        if key in [self.sb_list.item(i).data(Qt.UserRole) for i in range(self.sb_list.count())]:
            keys.insert(max(0, min(at, len(keys))), key)
            _set_list("ShortcutBarOrder." + self.sb_mode.currentData(), keys)
        self._fill_shortcut_bar()

    def _shortcut_dropped(self, key):
        mode = self.sb_mode.currentData()
        extras = shortcut_extras(mode)
        gone = shortcut_removed(mode)
        if key in gone:                 # a stock button put back
            _set_list("ShortcutBarRemoved." + mode, [k for k in gone if k != key])
        elif key not in extras and key not in self._sb_keys(mode):
            extras.append(key)
            _set_list("ShortcutBar." + mode, extras)
        self._fill_shortcut_bar()

    def _shortcut_remove(self):
        item = self.sb_list.currentItem()
        if item is None:
            _hint(self.sender(), "Pick a button on the shortcut bar above, then Remove.")
            return
        mode = self.sb_mode.currentData()
        key = item.data(Qt.UserRole)
        if item.data(Qt.UserRole + 1) == "extra":
            _set_list("ShortcutBar." + mode, [k for k in shortcut_extras(mode) if k != key])
        else:

            _set_list("ShortcutBarRemoved." + mode, shortcut_removed(mode) + [key])
        self._fill_shortcut_bar()

    def _shortcut_reset(self):
        for mode, _n in MODES:
            _p().RemString("ShortcutBar." + mode)
            _p().RemString("ShortcutBarRemoved." + mode)
            _p().RemString("ShortcutBarOrder." + mode)
        self._fill_shortcut_bar()

    # ---- Commands
    def _search_box(self, parent, name, grid, cats):
        ""


        box = QtWidgets.QLineEdit(parent)
        box.setObjectName(name)
        box.setPlaceholderText("")
        box.setClearButtonEnabled(True)

        def find(text):
            text = text.strip().lower()
            g, c = grid(), cats()
            if not text:
                row = c.currentRow()
                if row >= 0:
                    g.set_keys(self._tcats[row][1])
                return
            seen, keys = set(), []
            for _title, ks in self._tcats:
                for k in ks:
                    if k not in seen and text in _label(k).lower():
                        seen.add(k)
                        keys.append(k)
            g.set_keys(keys)
        box.textChanged.connect(find)
        return box

    def _commands_tab(self):
        from . import swtoolbars
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)

        lay.addWidget(QtWidgets.QLabel("Select a category or search, click a button to see its description. "
                                       "Drag the button to any toolbar", w))
        self.cmd_search = self._search_box(w, "SWCustomizeCommandSearch", lambda: self.cmd_grid, lambda: self.cmd_cats)
        find = QtWidgets.QHBoxLayout()
        find.addWidget(QtWidgets.QLabel("Search for:", w))
        find.addWidget(self.cmd_search, 1)
        lay.addLayout(find)
        mid = QtWidgets.QHBoxLayout()
        self.cmd_cats = QtWidgets.QListWidget(w)
        self.cmd_cats.setObjectName("SWCustomizeCommandCategories")
        for title, _keys in self._tcats:
            self.cmd_cats.addItem(title)
        self.cmd_grid = CommandGrid(self.shell, w)
        self.cmd_grid.setObjectName("SWCustomizeCommandGrid")
        self.cmd_cats.currentRowChanged.connect(lambda row: self.cmd_grid.set_keys(self._tcats[row][1]) if row >= 0 else None)
        desc = QtWidgets.QGroupBox("Description", w)
        self.cmd_desc = QtWidgets.QLabel("", desc)
        self.cmd_desc.setWordWrap(True)
        QtWidgets.QVBoxLayout(desc).addWidget(self.cmd_desc)
        self.cmd_grid.currentItemChanged.connect(lambda cur, _p: self._describe(self.cmd_desc, cur))
        self.cmd_grid.setMouseTracking(True)
        self.cmd_grid.itemEntered.connect(lambda item: self._describe(self.cmd_desc, item))
        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("Toolbars:", w))
        left.addWidget(self.cmd_cats, 1)
        mid.addLayout(left, 1)
        buttons = QtWidgets.QGroupBox("Buttons", w)
        QtWidgets.QVBoxLayout(buttons).addWidget(self.cmd_grid)
        mid.addWidget(buttons, 2)
        lay.addLayout(mid, 1)
        lay.addWidget(desc)


        extra = QtWidgets.QWidget(w)
        extra.setObjectName("SWCustomizeCommandExtrasRow")
        extra.setVisible(False)
        row = QtWidgets.QHBoxLayout(extra)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QtWidgets.QLabel("Added to toolbar:"))
        self.cmd_toolbar = QtWidgets.QComboBox(w)
        self.cmd_toolbar.setObjectName("SWCustomizeCommandToolbar")
        for name, _k in swtoolbars.TOOLBARS:
            self.cmd_toolbar.addItem(name)
        self.cmd_toolbar.currentIndexChanged.connect(lambda _i: self._fill_toolbar_extras())
        row.addWidget(self.cmd_toolbar)
        self.cmd_extras = QtWidgets.QListWidget(w)
        self.cmd_extras.setObjectName("SWCustomizeCommandExtras")
        self.cmd_extras.setFixedHeight(60)
        self.cmd_extras.setViewMode(QtWidgets.QListWidget.IconMode)
        row.addWidget(self.cmd_extras, 1)
        add = QtWidgets.QPushButton("Add", w)
        add.setObjectName("SWCustomizeCommandAdd")
        add.clicked.connect(self._add_clicked)
        row.addWidget(add)
        remove = QtWidgets.QPushButton("Remove", w)
        remove.setObjectName("SWCustomizeCommandRemove")
        remove.clicked.connect(self._remove_extra)
        row.addWidget(remove)
        reset = QtWidgets.QPushButton("Reset to Defaults", w)
        reset.setObjectName("SWCustomizeCommandsReset")
        reset.clicked.connect(self._commands_reset)
        lay.addWidget(reset)
        lay.addWidget(extra)
        self.cmd_cats.setCurrentRow(0)
        self._fill_toolbar_extras()
        return w

    def _fill_toolbar_extras(self):
        self.cmd_extras.clear()
        for key in toolbar_extras(self.cmd_toolbar.currentText()):
            item = QtWidgets.QListWidgetItem(_icon(self.shell, key), "")
            item.setData(Qt.UserRole, key)
            item.setToolTip(_label(key))
            self.cmd_extras.addItem(item)

    def _add_clicked(self):
        key = self.cmd_grid.current_key()
        if not key:
            _hint(self.sender(), "Pick a button in the list above, then Add.")
            return
        if not self.add_to_toolbar(self.cmd_toolbar.currentText(), key):
            _hint(self.sender(), "%s is already on the %s toolbar." % (_label(key), self.cmd_toolbar.currentText()))

    def add_to_toolbar(self, name, key):
        ""
        from . import swtoolbars
        if key == macrobuttons.NEW_KEY:
            key = macrobuttons.new_button(self)
            self.refresh_macro_category()
        if not key or key not in catalog.BY_KEY or not name:
            return False
        extras = toolbar_extras(name)
        if key in extras or key in swtoolbars.keys_of(name, extras=False):
            return False
        extras.append(key)
        _set_list("ToolbarExtra." + name, extras)
        swtoolbars.rebuild(self.shell, name); _hud_changed(self.shell, name)
        if name == self.cmd_toolbar.currentText():
            self._fill_toolbar_extras()
        return True

    def _remove_extra(self):
        from . import swtoolbars
        item = self.cmd_extras.currentItem()
        if item is None:
            _hint(self.sender(), "Pick a button you added to this toolbar (the box to the left), then Remove.")
            return
        name = self.cmd_toolbar.currentText()
        _set_list("ToolbarExtra." + name, [k for k in toolbar_extras(name) if k != item.data(Qt.UserRole)])
        swtoolbars.rebuild(self.shell, name); _hud_changed(self.shell, name)
        self._fill_toolbar_extras()

    def refresh_macro_category(self):
        """The Macro category lists the macro buttons made so far."""
        self._cats = categories()
        self._tcats = toolbar_categories(self._cats)
        row = self.cmd_cats.currentRow()
        if 0 <= row < len(self._tcats):
            self.cmd_grid.set_keys(self._tcats[row][1])

    def edit_macro_button(self, key):
        if macrobuttons.edit_button(key, self):
            self.refresh_macro_category()
            self._relayout_toolbars()

    def delete_macro_button(self, key):
        if macrobuttons.is_button(key):
            macrobuttons.remove(key[len(macrobuttons.KEY_PREFIX):])
            self.refresh_macro_category()
            self._relayout_toolbars()
            self._fill_toolbar_extras()

    def _relayout_toolbars(self):
        from . import swtoolbars
        for name, _k in swtoolbars.TOOLBARS:
            swtoolbars.rebuild(self.shell, name)
            _hud_changed(self.shell, name)

    def _commands_reset(self):
        from . import swtoolbars
        for name, _k in swtoolbars.TOOLBARS:
            if _p().GetString("ToolbarExtra." + name, ""):
                _p().RemString("ToolbarExtra." + name)
                swtoolbars.rebuild(self.shell, name); _hud_changed(self.shell, name)
        self._fill_toolbar_extras()

    # ---- Menus
    def _menus_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(w)
        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("Categories:"))
        self.menu_cats = QtWidgets.QListWidget(w)
        self.menu_cats.setObjectName("SWCustomizeMenuCategories")
        have = {t for t, _k in menu_categories(getattr(self, "_cats", None))}
        for title in MENU_CATEGORIES:
            if title in MENU_TITLES or title in have:      # an empty category is left off (NO DEAD CONTROLS)
                self.menu_cats.addItem(title)
        left.addWidget(self.menu_cats, 1)
        lay.addLayout(left, 1)
        mid = QtWidgets.QVBoxLayout()
        mid.addWidget(QtWidgets.QLabel("Commands:"))
        self.menu_cmds = QtWidgets.QListWidget(w)
        self.menu_cmds.setObjectName("SWCustomizeMenuCommands")
        mid.addWidget(self.menu_cmds, 1)
        lay.addLayout(mid, 2)
        right = QtWidgets.QVBoxLayout()
        box = QtWidgets.QGroupBox(w)
        form = QtWidgets.QFormLayout(box)
        self.menu_menu = QtWidgets.QComboBox(box)
        self.menu_menu.setObjectName("SWCustomizeMenuMenu")
        self.menu_menu.addItems(MENU_TITLES)
        self.menu_pos = QtWidgets.QComboBox(box)
        self.menu_pos.setObjectName("SWCustomizeMenuPosition")
        for shown, stored in POSITION_NAMES:
            self.menu_pos.addItem(shown, stored)
        self._pos_hidden = False
        self.menu_pos.activated.connect(lambda _i: setattr(self, "_pos_hidden", False))
        self.menu_text = QtWidgets.QLineEdit(box)
        self.menu_text.setObjectName("SWCustomizeMenuText")

        # Description, with Rename and Remove under them
        form.addRow("Change what menu:", self.menu_menu)
        form.addRow("Position on menu:", self.menu_pos)
        form.addRow("Name of command:", self.menu_text)
        self.menu_desc = QtWidgets.QLabel(box)
        self.menu_desc.setObjectName("SWCustomizeMenuDescription")
        self.menu_desc.setWordWrap(True)
        self.menu_desc.setMinimumHeight(40)
        self.menu_desc.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.menu_desc.setFrameShape(QtWidgets.QFrame.StyledPanel)
        form.addRow("Description:", self.menu_desc)
        buttons = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton("Add", box)
        add.setObjectName("SWCustomizeMenuAdd")
        add.setToolTip("Puts the command on the chosen menu and position, with the name typed above")
        add.clicked.connect(self._menu_apply)
        apply = QtWidgets.QPushButton("Rename", box)
        apply.setObjectName("SWCustomizeMenuApply")
        apply.setToolTip("Gives the command the name typed above, where it is now")
        apply.clicked.connect(self._menu_rename)
        remove = QtWidgets.QPushButton("Remove", box)
        remove.setObjectName("SWCustomizeMenuRemove")
        remove.setToolTip("Takes the command off its menu (Position on menu: Hidden); Reset to Defaults brings it back")
        remove.clicked.connect(self._menu_remove)
        buttons.addWidget(add)
        buttons.addWidget(apply)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        form.addRow("", buttons)
        right.addWidget(box)

        right.addWidget(self._bool_check(w, "Show Customize Menu in shortcut menus", "CustomizeMenuItems"))
        right.addStretch(1)
        reset = QtWidgets.QPushButton("Reset to Defaults", w)
        reset.setObjectName("SWCustomizeMenusReset")
        reset.clicked.connect(lambda: self._reset_ask("SWCustomizeMenusResetAsk", (
            ("All menus", self._menus_reset),
            ("All shortcut menus", self._shortcut_menus_reset),
            ("All customizations", lambda: self._reset_all(ask=False)))))
        right.addWidget(reset, 0, Qt.AlignRight)
        lay.addLayout(right, 1)
        self.menu_cats.currentRowChanged.connect(lambda _r: self._fill_menu_commands())
        self.menu_cmds.currentItemChanged.connect(lambda cur, _p: self._menu_picked(cur))
        self.menu_cats.setCurrentRow(0)
        return w

    def _menu_labels(self, title):
        ""
        from . import swmenus
        out = []

        def walk(entries, depth=0):
            for e in entries:
                if e is swmenus.S or e is None:
                    continue
                if isinstance(e, str):
                    cmd = catalog.BY_KEY.get(e)
                    if cmd is not None:
                        out.append(("  " * depth) + cmd.label)
                        self._menu_cmds_by_label[cmd.label] = cmd
                    continue
                if isinstance(e, tuple) and len(e) == 2 and isinstance(e[0], str) and e[0].startswith("when:"):
                    walk(e[1], depth)
                    continue
                if isinstance(e, tuple) and len(e) >= 2 and isinstance(e[0], str):
                    out.append(("  " * depth) + e[0].replace("&", ""))
                    if isinstance(e[1], str):           # its command: a catalog key, "cmd:Name" or "fn:name"
                        self._menu_cmds_by_label.setdefault(e[0].replace("&", ""), e[1])
                    sub = e[1]
                    if isinstance(sub, (tuple, list)) and sub and not callable(sub) \
                            and any(isinstance(x, (str, tuple)) for x in sub):
                        walk(sub, depth + 1)
        if not hasattr(self, "_menu_cmds_by_label"):
            self._menu_cmds_by_label = {}
        if title in ("Others", "Macros", "Simulation", "Search"):       # extapps89: the commands no menu has (Add puts one on a menu)
            for t, keys in menu_categories(self._cats):
                if t == title:
                    for key in keys:
                        cmd = catalog.BY_KEY.get(key)
                        if cmd is not None and cmd.label not in out:
                            out.append(cmd.label)
                            self._menu_cmds_by_label[cmd.label] = cmd
            return out
        for t, entries in swmenus.MENUS:
            if t.replace("&", "") == title:
                walk(entries)
        return out

    def _fill_menu_commands(self):
        item = self.menu_cats.currentItem()
        title = item.text() if item is not None else ""
        self.menu_cmds.clear()
        for label in self._menu_labels(title):
            row = QtWidgets.QListWidgetItem(label)
            over = menu_override(title, label.strip())
            if over is not None:
                moved = menu_target(title, label.strip())
                row.setText("%s  ->  %s (%s)%s" % (label, over[0], over[1], " in " + moved if moved else ""))
            row.setData(Qt.UserRole, label.strip())
            self.menu_cmds.addItem(row)

    def _menu_picked(self, item):
        if item is None:
            return
        title = self.menu_cats.currentItem().text()
        label = item.data(Qt.UserRole)
        over = menu_override(title, label)
        self.menu_menu.setCurrentText(menu_target(title, label) or title)
        self._set_pos(over[1] if over else "Default")
        self.menu_text.setText(over[0] if over else label)
        if hasattr(self, "menu_desc"):
            self.menu_desc.setText(self._menu_description(item))

    def _menu_description(self, item):
        ""
        label = item.data(Qt.UserRole)
        cmd = getattr(self, "_menu_cmds_by_label", {}).get(label)
        tip = ""
        if isinstance(cmd, str):
            if cmd.startswith("cmd:"):
                cmd = type("Native", (), {"tip": "", "natives": (cmd[4:],)})
            else:
                cmd = catalog.BY_KEY.get(cmd)
        if cmd is not None:
            tip = cmd.tip or ""
            for native in cmd.natives:
                if tip:
                    break
                try:
                    info = Gui.Command.get(native).getInfo()
                    tip = info.get("toolTip", "") or info.get("statusTip", "")
                except Exception as _fw_err:
                    _fw_log("customizedlg.py:1190", _fw_err)
        if not tip:
            tip = ""
        return tip.split("\n")[0][:200]

    def _menu_remove(self):
        if self.menu_cmds.currentItem() is None:
            _hint(self.sender(), "Pick a command in the Commands list, then Remove.")
            return
        self._set_pos("Hidden")
        self._menu_apply()

    def _menu_rename(self):
        """Rename: the new name only; the menu and position the command has now stay."""
        item = self.menu_cmds.currentItem()
        if item is None:
            _hint(self.sender(), "Pick a command in the Commands list, type its new name, then Rename.")
            return
        title = self.menu_cats.currentItem().text()
        label = item.data(Qt.UserRole)
        over = menu_override(title, label)
        self.menu_menu.setCurrentText(menu_target(title, label) or title)
        self._set_pos(over[1] if over else "Default")
        self._menu_apply()

    def _set_pos(self, stored):
        ""
        self._pos_hidden = stored == "Hidden"
        i = self.menu_pos.findData(stored)
        self.menu_pos.setCurrentIndex(i if i >= 0 else 0)

    def _pos_value(self):
        return "Hidden" if getattr(self, "_pos_hidden", False) else (self.menu_pos.currentData() or "Default")

    def _menu_apply(self):
        item = self.menu_cmds.currentItem()
        if item is None:
            _hint(self.sender(), "Pick a command in the Commands list, choose its menu and position, then Add.")
            return
        title = self.menu_cats.currentItem().text()
        label = item.data(Qt.UserRole)
        text = self.menu_text.text().strip() or label
        pos = self._pos_value()
        where = self.menu_menu.currentText()        # Menu: the menu the entry is shown in
        where = "" if where == title else where
        if text == label and pos == "Default" and not where:
            _p().RemString("Menu.%s.%s" % (title, label))
        else:
            _p().SetString("Menu.%s.%s" % (title, label), "%s|%s|%s" % (text, pos, where))
        self._fill_menu_commands()

    def _menus_reset(self):
        g = _p()
        for name in g.GetStrings():
            if name.startswith("Menu."):
                g.RemString(name)
        self._fill_menu_commands()

    def _shortcut_menus_reset(self):
        """Reset to Defaults > All shortcut menus: every right-click menu shows all its entries again."""
        from . import paths
        g = paths.params()
        for name in g.GetStrings():
            if name.startswith("FMMenuHidden."):
                g.RemString(name)

    # ---- Keyboard
    def _keyboard_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)

        # Copy List and Remove Shortcut beside them on the right
        top = QtWidgets.QGridLayout()
        top.addWidget(QtWidgets.QLabel("Category:"), 0, 0)
        self.key_cat = QtWidgets.QComboBox(w)
        self.key_cat.setObjectName("SWCustomizeKeyCategory")
        self.key_cat.addItem("All Commands")
        self._mcats = menu_categories(self._cats)
        for title, _k in self._mcats:
            self.key_cat.addItem(title)
        for title in ("View", "Selection", "Others"):
            if self.key_cat.findText(title) < 0:
                self.key_cat.addItem(title)
        top.addWidget(self.key_cat, 0, 1)
        top.addWidget(QtWidgets.QLabel("Show:"), 1, 0)
        self.key_show = QtWidgets.QComboBox(w)
        self.key_show.setObjectName("SWCustomizeKeyShow")

        self.key_show.addItems(["All Commands", "Commands with Keyboard Shortcuts", "Commands with Search Shortcuts",
                                "Commands with Keyboard or Search Shortcuts"])
        top.addWidget(self.key_show, 1, 1)
        top.addWidget(QtWidgets.QLabel("Search for:"), 2, 0)
        self.key_search = QtWidgets.QLineEdit(w)
        self.key_search.setObjectName("SWCustomizeKeySearch")
        top.addWidget(self.key_search, 2, 1)
        top.setColumnStretch(1, 1)
        lay.addLayout(top)
        self.key_table = KeyTable(0, 4, w)
        self.key_table.pressed_key = self._pressed_key
        self.key_table.setObjectName("SWCustomizeKeyTable")
        self.key_table.setHorizontalHeaderLabels(["Category", "Command", "Shortcut(s)", "Search Shortcut"])
        self.key_table.horizontalHeader().setStretchLastSection(True)
        self.key_table.setSelectionBehavior(QtWidgets.QTableWidget.SelectRows)
        self.key_table.setEditTriggers(QtWidgets.QTableWidget.NoEditTriggers)
        self.key_table.cellDoubleClicked.connect(self._key_edit)
        self.key_table.cellClicked.connect(self._key_clicked)
        self.key_table.setSortingEnabled(True)          # a column heading sorts by that column
        lay.addWidget(self.key_table, 1)
        kdesc = QtWidgets.QGroupBox("Description", w)
        self.key_desc = QtWidgets.QLabel("", kdesc)
        self.key_desc.setObjectName("SWCustomizeKeyDescription")
        self.key_desc.setWordWrap(True)
        QtWidgets.QVBoxLayout(kdesc).addWidget(self.key_desc)
        self.key_table.currentCellChanged.connect(lambda r, _c, _pr, _pc: self._describe_row(self.key_desc, self.key_table, r))
        lay.addWidget(kdesc)
        lay.addWidget(QtWidgets.QLabel("Pick a command and press the keys, or click its Shortcut(s) cell and press them; click a "
                                       "Search Shortcut cell and type letters for the command search. Enter keeps them, Esc leaves them."))
        row = QtWidgets.QHBoxLayout()
        for text, name, slot in (("Reset to Defaults", "SWCustomizeKeysReset", lambda: self._reset_ask(
                                     "SWCustomizeKeysResetAsk", (("Keyboard shortcuts", self._keys_reset),
                                                                 ("All customizations", lambda: self._reset_all(ask=False))))),
                                 ("Print List...", "SWCustomizeKeysPrint", lambda: self._print(self.key_table)),
                                 ("Copy List", "SWCustomizeKeysCopy", lambda: self._copy(self.key_table)),
                                 ("Remove Shortcut", "SWCustomizeKeysRemove", self._key_remove)):
            b = QtWidgets.QPushButton(text, w)
            b.setObjectName(name)
            b.clicked.connect(slot)
            side = ("SWCustomizeKeysPrint", "SWCustomizeKeysCopy", "SWCustomizeKeysRemove")
            if name in side:
                top.addWidget(b, side.index(name), 2)
            else:
                row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        for sig in (self.key_cat.currentIndexChanged, self.key_show.currentIndexChanged):
            sig.connect(lambda _i: self._fill_keys())
        self.key_search.textChanged.connect(lambda _t: self._fill_keys())
        self._fill_keys()
        return w

    def _key_rows(self):
        """(category, key, label, native) for every command that has a FreeCAD action."""
        rows = []
        seen = set()
        for title, keys in getattr(self, "_mcats", None) or menu_categories(self._cats):
            for key in keys:
                cmd = catalog.BY_KEY[key]
                native = None
                for n in cmd.natives:
                    try:
                        if Gui.Command.get(n) is not None:
                            native = n
                            break
                    except Exception:
                        continue
                if native is None or native in seen:
                    continue
                seen.add(native)
                rows.append((title, key, cmd.label, native))
        # View > Toolbars > each toolbar: a key shows or hides it (tbkeys.py)
        try:
            from . import tbkeys
            tbkeys.attach()
            for native_name, tb in tbkeys.names():
                if native_name not in seen and Gui.Command.get(native_name) is not None:
                    seen.add(native_name)
                    rows.append(("View", None, tb + " toolbar", native_name))
        except Exception as _fw_err:
            _fw_log("customizedlg.py:1302", _fw_err)

        # Solid Bodies, Midpoints, Center Marks, Centerlines...), so each one can take a key
        try:
            from . import selfilter
            selfilter.install()
            for native in selfilter.COMMANDS:
                if native in seen or Gui.Command.get(native) is None:
                    continue
                label = Gui.Command.get(native).getInfo().get("menuText", "").replace("&", "")
                if label:
                    seen.add(native)
                    rows.append(("Selection", None, label, native))
        except Exception as _fw_err:
            _fw_log("customizedlg.py:1316", _fw_err)

        # toolbar here has (Normal To, the selection filters, Previous View...) go under Others
        from . import keys
        for native, _k in keys.KEYS:
            if native in seen:
                continue
            try:
                cmd = Gui.Command.get(native)
                label = cmd.getInfo().get("menuText", "").replace("&", "") if cmd is not None else ""
            except Exception:
                continue
            if label:
                seen.add(native)
                rows.append(("Others", None, label, native))

        try:
            from . import filterkeys
            for native, title, label, _k in filterkeys.COMMANDS:
                if native not in seen and Gui.Command.get(native) is not None:
                    seen.add(native)
                    rows.append((title, None, label, native))
        except Exception as _fw_err:
            _fw_log("customizedlg.py:filterkeys", _fw_err)

        for label, native in (("Cut", "Std_Cut"), ("Copy", "Std_Copy"), ("Paste", "Std_Paste"), ("Delete", "Std_Delete")):
            try:
                ok = native not in seen and Gui.Command.get(native) is not None
            except Exception:
                ok = False
            if ok:
                seen.add(native)
                rows.append(("Edit", None, label, native))
        return _sw_key_rows(rows)

    def _fill_keys(self):
        cat = self.key_cat.currentText()
        show = self.key_show.currentIndex()
        text = self.key_search.text().strip().lower()
        sorting = self.key_table.isSortingEnabled()
        self.key_table.setSortingEnabled(False)
        self.key_table.setRowCount(0)
        for title, key, label, native in self._key_rows():
            if cat != "All Commands" and title != cat:
                continue
            short = current_key(native)
            found = search_key(native)
            if show == 1 and not short or show == 2 and not found or show == 3 and not (short or found):
                continue
            if text and text not in label.lower() and text not in short.lower() and text not in found.lower():
                continue
            r = self.key_table.rowCount()
            self.key_table.insertRow(r)
            for c, value in enumerate((title, label, _sw_key_names(short), found)):
                item = QtWidgets.QTableWidgetItem(value)
                item.setData(Qt.UserRole, native)
                item.setData(Qt.UserRole + 1, key)
                self.key_table.setItem(r, c, item)
        self.key_table.setSortingEnabled(sorting)
        self.key_table.resizeColumnsToContents()

    def _select_native(self, native):
        """Picks the row of native again after the list was filled (Remove Shortcut acts on it)."""
        for r in range(self.key_table.rowCount()):
            item = self.key_table.item(r, 1)
            if item is not None and item.data(Qt.UserRole) == native:
                self.key_table.setCurrentCell(r, 1)
                return r
        return -1

    def _key_clicked(self, row, column):
        ""
        if column in (2, 3):
            self._key_edit(row, column)

    def _pressed_key(self, row, seq):
        item = self.key_table.item(row, 1)
        if item is None:
            return
        native = item.data(Qt.UserRole)
        self.set_shortcut(native, seq)
        self._fill_keys()
        self._select_native(native)

    def _key_edit(self, row, column):
        if column == 3:
            self._search_key_edit(row)
            return
        if column != 2:
            return
        item = self.key_table.item(row, 2)
        native = item.data(Qt.UserRole)
        if isinstance(self.key_table.cellWidget(row, 2), QtWidgets.QKeySequenceEdit):
            return                                   # already typing there
        editor = QtWidgets.QKeySequenceEdit(self.key_table)
        editor.setObjectName("SWCustomizeKeyEditor")
        editor.setKeySequence(QtGui.QKeySequence(item.text()))
        self.key_table.setCellWidget(row, 2, editor)
        editor.setFocus()

        done = []

        def finish(keep=True):
            if done:
                return
            done.append(1)
            if keep:
                seq = editor.keySequence().toString(QtGui.QKeySequence.NativeText)
                self.set_shortcut(native, seq)
            self.key_table.removeCellWidget(row, 2)
            self._fill_keys()
            self._select_native(native)
        editor.editingFinished.connect(lambda: finish(True))
        esc = QtGui.QShortcut(QtGui.QKeySequence(Qt.Key_Escape), editor)
        esc.activated.connect(lambda: finish(False))

    def set_shortcut(self, native, key, ask=True):
        ""


        if key and key == current_key(native):
            return key
        if key:
            for _t, _k, label, other in self._key_rows():
                if other != native and current_key(other) == key:
                    if ask:
                        mine = next((l for _t2, _k2, l, n in self._key_rows() if n == native), native)
                        answer = QtWidgets.QMessageBox.question(
                            self, "Customize",
                            "The shortcut %s is already assigned to %s.\nDo you want to remove it from %s and assign it to %s?"
                            % (key, label, label, mine),
                            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
                        if answer != QtWidgets.QMessageBox.Yes:
                            return current_key(native)
                    apply_key(other, "")
        apply_key(native, key)
        return current_key(native)

    def _search_key_edit(self, row):
        item = self.key_table.item(row, 3)
        native = item.data(Qt.UserRole)
        if isinstance(self.key_table.cellWidget(row, 3), QtWidgets.QLineEdit):
            return
        editor = QtWidgets.QLineEdit(item.text(), self.key_table)
        editor.setObjectName("SWCustomizeSearchKeyEditor")
        self.key_table.setCellWidget(row, 3, editor)
        editor.setFocus()
        editor.selectAll()
        done = []

        def finish(keep=True):
            if done:
                return
            done.append(1)
            if keep:
                set_search_key(native, editor.text())
            self.key_table.removeCellWidget(row, 3)
            self._fill_keys()
            self._select_native(native)
        editor.editingFinished.connect(lambda: finish(True))
        esc = QtGui.QShortcut(QtGui.QKeySequence(Qt.Key_Escape), editor)
        esc.activated.connect(lambda: finish(False))

    def _key_remove(self):
        """Takes the picked row's shortcut off, or its search shortcut when that cell is the one picked."""
        row = self.key_table.currentRow()
        if row < 0:
            _hint(self.sender(), "Pick a command's row in the list, then Remove Shortcut.")
            return
        native = self.key_table.item(row, 2).data(Qt.UserRole)
        if self.key_table.currentColumn() == 3:
            set_search_key(native, "")
        else:
            apply_key(native, "")
        self._fill_keys()

    def _keys_reset(self):
        from . import keys
        g = _p()
        defaults = dict(keys.KEYS)
        for name in g.GetBools():
            if name.startswith("SearchKeyOff."):
                g.RemBool(name)         # kbpage-1126: the default search shortcuts come back
        for name in g.GetStrings():
            if name.startswith("SearchKey."):
                g.RemString(name)
                continue
            if name.startswith("Key."):
                native = name[4:]
                g.RemString(name)
                if native not in defaults:
                    # a FreeCAD native: back to the shortcut it had before the Keyboard tab changed it
                    orig = g.GetString("KeyOrig." + native, "")
                    apply_key(native, orig, remember=False)
                g.RemString("KeyOrig." + native)
                g.RemBool("KeyOrigSet." + native)
        for _t, _k, _l, native in self._key_rows():
            if native in defaults:
                apply_key(native, defaults[native], remember=False)
        self._fill_keys()

    def _table_text(self, table):
        lines = ["\t".join(table.horizontalHeaderItem(c).text() for c in range(table.columnCount()))]
        for r in range(table.rowCount()):
            lines.append("\t".join((table.item(r, c).text() if table.item(r, c) else "") for c in range(table.columnCount())))
        return "\n".join(lines)

    def _copy(self, table):
        QtWidgets.QApplication.clipboard().setText(self._table_text(table))

        QtWidgets.QMessageBox.information(self, "Customize", "The list is on the clipboard.")

    def _print(self, table):
        try:
            from .drawprint import print_support      # FreeCAD's PySide shim leaves QtPrintSupport out
            QtPrintSupport = print_support()
            printer = QtPrintSupport.QPrinter()
            box = QtPrintSupport.QPrintDialog(printer, self)
            if box.exec_() != QtWidgets.QDialog.Accepted:
                return
            doc = QtGui.QTextDocument()
            doc.setPlainText(self._table_text(table))
            doc.print_(printer)
        except Exception as error:
            QtWidgets.QMessageBox.information(self, "Print List", "Printing is not available: %s" % error)

    # ---- Mouse Gestures
    def _gestures_tab(self):
        from . import paths
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        top = QtWidgets.QHBoxLayout()
        self.g_enable = QtWidgets.QCheckBox("Enable mouse gestures", w)
        self.g_enable.setObjectName("SWCustomizeGesturesEnable")
        self.g_enable.setChecked(paths.params().GetBool("MouseGestures", True))
        self.g_enable.toggled.connect(lambda on: paths.params().SetBool("MouseGestures", bool(on)))
        top.addWidget(self.g_enable)
        self.g_count = QtWidgets.QComboBox(w)
        self.g_count.setObjectName("SWCustomizeGesturesCount")
        for value, name in GESTURE_COUNTS:
            self.g_count.addItem(name, value)
        self.g_count.setCurrentIndex([v for v, _n in GESTURE_COUNTS].index(gesture_count()))
        self.g_count.currentIndexChanged.connect(lambda _i: (set_gesture_count(self.g_count.currentData()), self._fill_gestures()))
        top.addWidget(self.g_count)
        top.addStretch(1)
        lay.addLayout(top)
        guide = QtWidgets.QGroupBox("Mouse Gesture Guide", w)
        gl = QtWidgets.QHBoxLayout(guide)
        self.g_rings = []
        for mode, name in MODES:
            ring = GestureRing(self.shell, mode, name, guide)
            ring.changed = self._fill_gestures
            gl.addWidget(ring)
            self.g_rings.append(ring)
        lay.addWidget(guide)
        mid = QtWidgets.QHBoxLayout()
        mid.addWidget(QtWidgets.QLabel("Category:"))
        self.g_cat = QtWidgets.QComboBox(w)
        self.g_cat.setObjectName("SWCustomizeGesturesCategory")
        self.g_cat.addItem("All Commands")
        self._mcats = getattr(self, "_mcats", None) or menu_categories(self._cats)   # customkeys-1119
        for title, _k in self._mcats:
            self.g_cat.addItem(title)
        mid.addWidget(self.g_cat)
        mid.addWidget(QtWidgets.QLabel("Show:"))
        self.g_show = QtWidgets.QComboBox(w)
        self.g_show.setObjectName("SWCustomizeGesturesShow")
        self.g_show.addItems(["All Commands", "Commands with gestures assigned", "Commands without gestures"])
        self.g_show.setVisible(False)
        mid.itemAt(mid.count() - 1).widget().setVisible(False)      # its "Show:" label
        mid.addWidget(self.g_show)
        mid.addWidget(QtWidgets.QLabel("Search for:"))
        self.g_search = QtWidgets.QLineEdit(w)
        self.g_search.setObjectName("SWCustomizeGesturesSearch")
        mid.addWidget(self.g_search, 1)
        lay.addLayout(mid)
        self.g_table = GestureTable(w)
        self.g_table.setObjectName("SWCustomizeGesturesTable")
        self.g_table.setHorizontalHeaderLabels(["Category", "Command", "Part", "Assembly", "Drawing", "Sketch"])
        self.g_table.horizontalHeader().setStretchLastSection(True)
        self.g_table.setSelectionBehavior(QtWidgets.QTableWidget.SelectRows)
        self.g_table.setEditTriggers(QtWidgets.QTableWidget.NoEditTriggers)
        self.g_table.cellDoubleClicked.connect(self._gesture_edit)
        self.g_table.cellClicked.connect(self._gesture_edit)
        self.g_table.setSortingEnabled(True)
        lay.addWidget(self.g_table, 1)
        gdesc = QtWidgets.QGroupBox("Description", w)
        self.g_desc = QtWidgets.QLabel("", gdesc)
        self.g_desc.setObjectName("SWCustomizeGestureDescription")
        self.g_desc.setWordWrap(True)
        QtWidgets.QVBoxLayout(gdesc).addWidget(self.g_desc)
        self.g_table.currentCellChanged.connect(lambda r, _c, _pr, _pc: self._describe_row(self.g_desc, self.g_table, r))
        lay.addWidget(gdesc)
        hint = QtWidgets.QLabel("Drag a command to any mouse gesture guide.", w)
        hint.setToolTip("Drag it off a guide to remove it, or click a Part, Assembly, Drawing or Sketch cell to choose its direction.")
        lay.addWidget(hint)
        self._guide = guide
        row = QtWidgets.QHBoxLayout()
        for text, name, slot in (("Reset to Defaults", "SWCustomizeGesturesReset", self._gestures_reset_ask),
                                 ("Print Gesture Guides...", "SWCustomizeGesturesPrint", self._print_guides),
                                 ("Copy List", "SWCustomizeGesturesCopy", lambda: self._copy(self.g_table))):
            b = QtWidgets.QPushButton(text, w)
            b.setObjectName(name)
            b.clicked.connect(slot)
            b.setVisible(name != "SWCustomizeGesturesCopy")
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        for sig in (self.g_cat.currentIndexChanged, self.g_show.currentIndexChanged):
            sig.connect(lambda _i: self._fill_gestures())
        self.g_search.textChanged.connect(lambda _t: self._fill_gestures())
        self._fill_gestures()
        return w

    def _fill_gestures(self):
        count = gesture_count()
        for ring in self.g_rings:
            ring.refresh(count)
        cat = self.g_cat.currentText()
        show = self.g_show.currentIndex()
        text = self.g_search.text().strip().lower()
        assigned = {mode: gesture_keys(count, mode) for mode, _n in MODES}
        sorting = self.g_table.isSortingEnabled()
        self.g_table.setSortingEnabled(False)
        self.g_table.setRowCount(0)
        for title, keys in getattr(self, "_mcats", None) or menu_categories(self._cats):
            if cat != "All Commands" and title != cat:
                continue
            for key in keys:
                label = _label(key)
                cells = []
                for mode, _n in MODES:
                    keys_ = assigned[mode]
                    cells.append(DIRECTION_NAMES.get(GESTURE_ANGLES[count][keys_.index(key)], "") if key in keys_ else "")
                has = any(cells)
                if show == 1 and not has or show == 2 and has:
                    continue
                if text and text not in label.lower():
                    continue
                r = self.g_table.rowCount()
                self.g_table.insertRow(r)
                for c, value in enumerate([title, label] + cells):
                    item = QtWidgets.QTableWidgetItem(value)
                    item.setData(Qt.UserRole, key)
                    self.g_table.setItem(r, c, item)
        self.g_table.setSortingEnabled(sorting)
        self.g_table.resizeColumnsToContents()

    def _gesture_edit(self, row, column):
        if column < 2 or isinstance(self.g_table.cellWidget(row, column), QtWidgets.QComboBox):
            return
        mode = MODES[column - 2][0]
        key = self.g_table.item(row, 1).data(Qt.UserRole)
        count = gesture_count()
        box = QtWidgets.QComboBox(self.g_table)
        box.setObjectName("SWCustomizeGestureEditor")
        box.addItem("(none)", -1)
        for i, angle in enumerate(GESTURE_ANGLES[count]):
            box.addItem(DIRECTION_NAMES.get(angle, str(angle)), i)
        keys = list(gesture_keys(count, mode))
        box.setCurrentIndex(keys.index(key) + 1 if key in keys else 0)
        self.g_table.setCellWidget(row, column, box)
        box.showPopup()

        def chosen(_i):
            self.assign_gesture(count, mode, key, box.currentData())
            self.g_table.removeCellWidget(row, column)
            self._fill_gestures()
        box.activated.connect(chosen)

    def assign_gesture(self, count, mode, key, index):
        """Puts key in the direction index (-1 takes it off), one direction per command."""
        keys = list(gesture_keys(count, mode))
        keys = [k if k != key else "" for k in keys]
        if 0 <= index < len(keys):
            keys[index] = key
        set_gesture_keys(count, mode, keys)
        return tuple(keys)

    def _gestures_reset_ask(self):
        ""
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question, "Customize", "What do you want to reset to the defaults?",
                                    QtWidgets.QMessageBox.NoButton, self)
        box.setObjectName("SWCustomizeGesturesResetAsk")
        guides = box.addButton("Mouse gesture guides", QtWidgets.QMessageBox.AcceptRole)
        everything = box.addButton("All customizations", QtWidgets.QMessageBox.DestructiveRole)
        box.addButton(QtWidgets.QMessageBox.Cancel)
        box.setDefaultButton(guides)
        box.exec_()
        if box.clickedButton() is guides:
            self._gestures_reset()
        elif box.clickedButton() is everything:
            self._reset_all(ask=False)

    def guide_image(self):
        """The four Mouse Gesture Guide rings as one picture."""
        guide = getattr(self, "_guide", None)
        return guide.grab().toImage() if guide is not None else QtGui.QImage()

    def _print_guides(self):
        ""
        try:
            from .drawprint import print_support
            QtPrintSupport = print_support()
            printer = QtPrintSupport.QPrinter()
            box = QtPrintSupport.QPrintDialog(printer, self)
            if box.exec_() != QtWidgets.QDialog.Accepted:
                return
            doc = QtGui.QTextDocument()
            doc.addResource(QtGui.QTextDocument.ImageResource, QtCore.QUrl("fw://guides.png"), self.guide_image())
            rows = self._table_text(self.g_table).replace("&", "&amp;").replace("<", "&lt;")
            doc.setHtml("<h3>Mouse Gesture Guides (%s)</h3><img src='fw://guides.png'><pre>%s</pre>"
                        % (self.g_count.currentText(), rows))
            doc.print_(printer)
        except Exception as error:
            QtWidgets.QMessageBox.information(self, "Print Gestures Guides", "Printing is not available: %s" % error)

    def _gestures_reset(self):
        g = _p()
        for name in g.GetStrings():
            if name.startswith("Gesture."):
                g.RemString(name)
        self._fill_gestures()

    # ---- Customization
    def _customization_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(self._bool_check(w, "Lock CommandManager and toolbars", "LockToolbars", self._lock))
        lay.addWidget(self._bool_check(w, "Show Customize Menu in shortcut menus", "CustomizeMenuItems"))
        lay.addWidget(QtWidgets.QLabel("While this box is open, buttons from the Commands tab can be dragged onto any toolbar, "
                                       "and the CommandManager shows every tab."))
        lay.addStretch(1)
        reset = QtWidgets.QPushButton("Reset to Defaults", w)
        reset.setObjectName("SWCustomizeResetAll")
        reset.clicked.connect(self._reset_all)
        lay.addWidget(reset, 0, Qt.AlignRight)
        return w

    def _lock(self):
        from . import swtoolbars
        swtoolbars.apply_lock()

    def _reset_all(self, ask=True):
        if ask and QtWidgets.QMessageBox.question(self, "Customize", "Reset every customization to its default?") != QtWidgets.QMessageBox.Yes:
            return
        self._keys_reset()
        self._shortcut_menus_reset()
        g = _p()
        for name in list(g.GetStrings()) + list(g.GetBools()) + list(g.GetInts()):
            g.RemString(name); g.RemBool(name); g.RemInt(name)
        from . import swtoolbars
        for name, _k in swtoolbars.TOOLBARS:
            swtoolbars.rebuild(self.shell, name); _hud_changed(self.shell, name)
        self._reset_toolbars(); self._fill_shortcut_bar(); self._fill_toolbar_extras(); self._fill_menu_commands(); self._fill_gestures()
        try:
            from . import cmcustom
            cmcustom._rebuild(self.shell)      # the CommandManager tabs and buttons Customize changed
        except Exception as _fw_err:
            _fw_log("customizedlg.py:1657", _fw_err)


class GestureTable(QtWidgets.QTableWidget):
    """The Mouse Gestures command list: its rows can be dragged onto the rings."""

    def __init__(self, parent=None):
        super().__init__(0, 6, parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)

    def mimeData(self, items):
        data = QtCore.QMimeData()
        if items:
            key = items[0].data(Qt.UserRole)
            if key:
                data.setData(MIME, str(key).encode())
        return data

    def mimeTypes(self):
        return [MIME]

    def supportedDropActions(self):
        return Qt.CopyAction | Qt.MoveAction


class GestureRing(QtWidgets.QWidget):
    """One ring of the Mouse Gesture Guide: the commands of a mode around a circle; hovering one
    shows its name in bold and its help line."""
    SIZE = 150

    def __init__(self, shell, mode, title, parent=None):
        super().__init__(parent)
        self.shell = shell
        self.mode = mode
        self.title = title
        self.items = []
        self.setObjectName("SWGestureRing_" + mode)
        self.setFixedSize(self.SIZE, self.SIZE + 18)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.count = "4"
        self.changed = None              # the dialog's refresh, set by it
        self.highlight = None            # direction index under a drag

    def refresh(self, count):
        self.count = count
        self.items = [(k, a) for k, a in gesture_items(count, self.mode)]
        self.update()

    def direction_at(self, pos):
        """The index of the nearest direction to pos (around the ring), or None at the centre."""
        import math
        c = self.SIZE / 2
        dx, dy = pos.x() - c, c - pos.y()
        if math.hypot(dx, dy) < 18:
            return None
        angle = math.degrees(math.atan2(dy, dx)) % 360
        angles = GESTURE_ANGLES[self.count]
        best = min(range(len(angles)), key=lambda i: min(abs(angles[i] - angle), 360 - abs(angles[i] - angle)))
        return best

    def _assign(self, key, index, keep=False):
        ""

        keys = list(gesture_keys(self.count, self.mode))
        if not keep:
            keys = [k if k != key else "" for k in keys]
        if index is not None and 0 <= index < len(keys):
            keys[index] = key
        set_gesture_keys(self.count, self.mode, keys)
        if self.changed is not None:
            self.changed()
        else:
            self.refresh(self.count)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            self.highlight = self.direction_at(e.pos())
            self.update()
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.highlight = None
        self.update()

    def dropEvent(self, e):
        self.highlight = None
        if not e.mimeData().hasFormat(MIME):
            return
        key = bytes(e.mimeData().data(MIME)).decode()
        index = self.direction_at(e.pos())
        if index is not None and key in catalog.BY_KEY:
            copy = bool(e.keyboardModifiers() & Qt.ControlModifier)
            self._assign(key, index, keep=copy)
            if copy:
                e.setDropAction(Qt.CopyAction)   # the ring it came from keeps it
                e.accept()
            else:
                e.acceptProposedAction()
        self.update()

    def mousePressEvent(self, e):
        """Dragging a command off its direction: onto another direction or ring moves it, elsewhere removes it.
        Ctrl held at the drop copies it instead (it stays on its first direction too)."""
        key = self.item_at(e.pos()) if e.button() == Qt.LeftButton else None
        if not key:
            return super().mousePressEvent(e)
        data = QtCore.QMimeData()
        data.setData(MIME, key.encode())
        drag = QtGui.QDrag(self)
        drag.setMimeData(data)
        icon = _icon(self.shell, key)
        if not icon.isNull():
            drag.setPixmap(icon.pixmap(20, 20))
        result = drag.exec_(Qt.MoveAction | Qt.CopyAction)
        if result == Qt.CopyAction and isinstance(drag.target(), GestureRing):
            return                           # Ctrl+drag: copied, the source keeps it
        if drag.target() is None or result == Qt.IgnoreAction:
            self._assign(key, None)          # dropped outside: taken off this ring
        elif drag.target() is not self and isinstance(drag.target(), GestureRing):
            self._assign(key, None)          # moved to another ring: off this one

    def _centre(self, angle):
        import math
        r = self.SIZE / 2 - 20
        c = self.SIZE / 2
        return QtCore.QPointF(c + r * math.cos(math.radians(angle)), c - r * math.sin(math.radians(angle)))

    def item_at(self, pos):
        for key, angle in self.items:
            if key and (self._centre(angle) - QtCore.QPointF(pos)).manhattanLength() < 20:
                return key
        return None

    def event(self, e):
        if e.type() == QtCore.QEvent.ToolTip:
            key = self.item_at(e.pos())
            if key:
                QtWidgets.QToolTip.showText(e.globalPos(), "<b>%s</b><br>%s" % (_label(key), catalog.BY_KEY[key].tip), self)
            else:
                QtWidgets.QToolTip.hideText()
            return True
        return super().event(e)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        c = QtCore.QPointF(self.SIZE / 2, self.SIZE / 2)
        p.setPen(QtGui.QPen(QtGui.QColor(140, 148, 160), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, self.SIZE / 2 - 4, self.SIZE / 2 - 4)
        p.drawEllipse(c, 10, 10)
        for i, (key, angle) in enumerate(self.items):
            m = self._centre(angle)
            box = QtCore.QRectF(m.x() - 14, m.y() - 14, 28, 28)
            lit = self.highlight == i
            p.setPen(QtGui.QPen(QtGui.QColor(255, 140, 0) if lit else QtGui.QColor(140, 148, 160), 2 if lit else 1))
            p.setBrush(QtGui.QColor(255, 236, 200) if lit else QtGui.QColor(255, 255, 255, 200))
            p.drawRoundedRect(box, 3, 3)
            if key:
                icon = _icon(self.shell, key)
                if not icon.isNull():
                    icon.paint(p, QtCore.QRect(int(m.x() - 10), int(m.y() - 10), 20, 20))
        p.setPen(self.palette().color(QtGui.QPalette.WindowText))
        p.drawText(QtCore.QRect(0, self.SIZE, self.SIZE, 18), Qt.AlignCenter, self.title)
        p.end()


# --------------------------------------------------------------------------- open it
def show(shell=None):
    if shell is None:
        try:
            from . import shell as sh
            shell = sh.shell()
        except Exception:
            shell = None
    if _open and _open[0].isVisible():
        _open[0].raise_()
        _open[0].activateWindow()
        return _open[0]
    box = CustomizeDialog(shell)
    box.setAttribute(Qt.WA_DeleteOnClose, True)
    box.show()
    return box


class CustomizeCommand:
    def GetResources(self):
        return {"MenuText": "Customize...", "ToolTip": "Sets up toolbars, shortcut bars, menus, keys and mouse gestures",
                "Pixmap": "preferences-system"}

    def IsActive(self):
        return True

    def Activated(self):
        show()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, CustomizeCommand())


macrobuttons.load()      # the macro buttons made in Customize, before any toolbar is built
