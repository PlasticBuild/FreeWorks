# SPDX-License-Identifier: LGPL-2.1-or-later
"""ScanRuler, Diotopo and the 3D Slicer as buttons of the Add-Ins tab, not tabs of their own (Ati 2026-11-22).

Each app is one large button at the end of the Add-Ins tab; its menu lists the app's commands (the ones its own tab
used to hold). The menu is made when the button is clicked, so a slicer added or removed in Slicer Apps, a Diotopo
download that finishes or a portable program that turns up is there at once, and a button that cannot do anything
(Diotopo before it is downloaded) is not shown at all: nothing greyed, nothing dead.
"""
import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

_SEEN = set()


def _fw_log(site, err):
    try:
        if site not in _SEEN:
            _SEEN.add(site)
            App.Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return


SEP = ("sep",)
KEYS = {"ScanRuler": "AI_ScanRuler", "Diotopo": "AI_Diotopo", "3D Slicer": "AI_Slicer"}
COMMAND = "SWStyle_AddInApp_"
TITLES = {"ScanRuler": "ScanRuler (3D Scan Inspection)", "Diotopo": "Diotopo (Topology Optimization)",
          "3D Slicer": "3D Slicer"}
TIPS = {"ScanRuler": "ScanRuler's commands: open it, send the selection, check for an update, release notes.",
        "Diotopo": "Diotopo's commands: open it, its portable program, update, its folder, its project page.",
        "3D Slicer": "The slicers: Orca Slicer, Bambu Studio and PrusaSlicer, Slice, Preview, Export G-code, "
                     "Send Part, printers, full programs, updates and Slicer Apps."}


# ---------------------------------------------------------------- which apps are on
def _shown(app):
    """The app has a button in Add-Ins: it is switched on (Tools > Add-Ins) and, for a download, downloaded."""
    try:
        if app == "3D Slicer":
            from . import cmtabs
            return app not in cmtabs.hidden()
        from . import extapps
        return extapps.tab_on(app) and extapps.installed(app)
    except Exception as error:
        _fw_log("addinapps.py:_shown", error)
        return False


def _items(app):
    """[key or None (a separator)] of the app's menu, in the order its tab had."""
    if app == "ScanRuler":
        return ["SR_Open", "SR_Send", None, "SR_Update", "SR_Notes"]
    if app == "Diotopo":
        from . import extapps
        keys = ["DT_Open"] + (["DT_Portable"] if extapps._has_portable() else [])
        return keys + [None, "DT_Update", "DT_Folder", "DT_Page"]
    from . import slicerui, slicerapps
    out = []
    for item in slicerui.LAYOUT:
        out.append(None if item[0] == "sep" else item[1])
    added = [i[1] for i in slicerapps.layout_items(slicerui._icon("other_slicer"))]
    if added:
        at = out.index("SlicerUpdate") if "SlicerUpdate" in out else len(out)
        out[at:at] = added
    return out


# ---------------------------------------------------------------- the buttons
def _icon_of(app):
    if app == "3D Slicer":
        from . import slicerui
        return slicerui._icon("slice")
    from . import extapps
    return extapps._icon("scanruler" if app == "ScanRuler" else "diotopo")


def _icon(path):
    try:
        icon = _v2(path) if isinstance(path, str) and path else QtGui.QIcon()
        if icon.isNull():
            from . import addintabs
            icon = addintabs._safe_icon(path) if path else icon
        return icon
    except Exception:
        return QtGui.QIcon()


class AppMenu:
    """The menu a button of the Add-Ins tab drops down."""

    def __init__(self, app):
        self.app = app

    def GetResources(self):
        return {"MenuText": TITLES[self.app], "ToolTip": TIPS[self.app], "Pixmap": "freecad"}

    def IsActive(self):
        return True

    def Activated(self):
        menu = self.build()
        if not menu.isEmpty():
            menu.popup(QtGui.QCursor.pos())

    def build(self):
        from . import catalog
        menu = QtWidgets.QMenu(Gui.getMainWindow())
        menu.setObjectName("FWAddInApp_" + self.app.replace(" ", ""))
        menu.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        try:
            keys = _items(self.app)
        except Exception as error:
            _fw_log("addinapps.py:build", error)
            keys = []
        pending_sep = False
        for key in keys:
            if key is None:
                pending_sep = not menu.isEmpty()
                continue
            cmd = catalog.BY_KEY.get(key)
            if cmd is None or not cmd.natives:
                continue
            native = cmd.natives[0]
            if native not in Gui.listCommands():
                continue                      # no command, no entry (never a dead one)
            if pending_sep:
                menu.addSeparator()
                pending_sep = False
            act = menu.addAction(_icon(cmd.icon), cmd.label)
            act.setObjectName("FWAddInApp_" + key)
            act.setToolTip(cmd.tip or "")
            try:
                act.setEnabled(bool(Gui.Command.get(native).isActive()))
            except Exception:
                pass
            act.triggered.connect(lambda _c=False, n=native: Gui.runCommand(n, 0))
        return menu



# Tools, Freeshape, Sketch Ink, Surfaces, Sheet Metal, Structure System, Weldments, Mold Tools, ... and the Addon
# Manager workbenches' own tabs) start hidden; the Add-Ins tab has a "More Tabs" button that lists them with a tick,

TABS_KEY = "AI_MoreTabs"
TABS_COMMAND = "SWStyle_AddInMoreTabs"
TABS_TIP = "Turns the extra CommandManager tabs on and off (Sheet Metal, Weldments, Surfaces, Mold Tools, Freeshape, " \
           "the Addon Manager workbenches...). The choice is kept."


def optional_tabs():
    ""
    from . import cmtabs
    try:
        every = [t[0] for t in cmtabs.all_tabs()]
    except Exception as error:
        _fw_log("addinapps.py:all_tabs", error)
        return []
    optional = list(cmtabs.DEFAULT_HIDDEN)
    try:
        from . import otherwbtabs
        optional += [t for t in otherwbtabs.others().values() if t not in optional]
    except Exception as error:
        _fw_log("addinapps.py:other tabs", error)
    try:
        from . import addintabs
        have_wb = Gui.listWorkbenches()
        missing = {t for t in every if addintabs.tab_missing(t, have_wb)}
    except Exception:
        missing = set()
    off = set(cmtabs.hidden())
    return [(t, t not in off) for t in every if t in optional and t not in missing and t != "3D Slicer"]


class MoreTabs:
    """The Add-Ins tab's "More Tabs" button: a menu of the extra tabs, ticked when shown."""

    def GetResources(self):
        return {"MenuText": "More Tabs", "ToolTip": TABS_TIP, "Pixmap": "freecad"}

    def IsActive(self):
        return True

    def Activated(self):
        menu = self.build()
        menu.popup(QtGui.QCursor.pos())

    def build(self):
        from . import cmtabs
        menu = QtWidgets.QMenu(Gui.getMainWindow())
        menu.setObjectName("FWAddInMoreTabs")
        menu.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        for title, shown in optional_tabs():
            act = menu.addAction(title)
            act.setObjectName("FWAddInTab_" + "".join(ch for ch in title if ch.isalnum()))
            act.setCheckable(True)
            act.setChecked(shown)
            act.setToolTip(("Hides" if shown else "Shows") + " the %s tab." % title)
            act.toggled.connect(lambda on, t=title: QtCore.QTimer.singleShot(0, lambda: set_tab(t, on)))
        if not menu.isEmpty():
            menu.addSeparator()
        try:
            menu.addAction("Customize Tabs...", lambda: cmtabs.TabsDialog().exec_())
        except Exception as error:
            _fw_log("addinapps.py:customize tabs", error)
        return menu


def set_tab(title, on):
    """Shows or hides one CommandManager tab and keeps the choice (right-click > Tabs does the same)."""
    from . import cmtabs
    off = [t for t in cmtabs.hidden() if t != title]
    if not on:
        off.append(title)
    cmtabs.set_hidden(off)
    cmtabs.apply()


def register():
    """Our three commands and catalog keys (once)."""
    from . import catalog
    have = set(Gui.listCommands()) if Gui is not None else set()
    if TABS_COMMAND not in have:
        Gui.addCommand(TABS_COMMAND, MoreTabs())
    if TABS_KEY not in catalog.BY_KEY:
        catalog.BY_KEY[TABS_KEY] = catalog.c(TABS_KEY, "More Tabs", (TABS_COMMAND,), "FLYOUT_ADD_INS", TABS_TIP,
                                             caption="More\nTabs")
    for app, key in KEYS.items():
        name = COMMAND + app.replace(" ", "")
        if name not in have:
            Gui.addCommand(name, AppMenu(app))
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, TITLES[app], (name,), _icon_of(app), TIPS[app],
                                            caption=app.replace("3D ", "3D\n") if app == "3D Slicer" else app)
    catalog.ALL = tuple(catalog._ALL)


def extend(layout):
    """The Add-Ins tab's layout with the apps that are on after it. Safe to call again on its own result."""
    layout = list(layout)
    mine = set(KEYS.values()) | {TABS_KEY}
    layout = [i for i in layout if not (len(i) > 1 and i[1] in mine)]
    while layout and layout[-1] == SEP:
        layout.pop()
    register()
    add = [("large", KEYS[app], None) for app in KEYS if _shown(app)]
    if add:
        layout += [SEP] + add
    layout += [SEP, ("large", TABS_KEY, None)]          # addintabs2-1127: the extra tabs, on and off
    return tuple(layout)


def _v2(path):
    """v2last-1127: the V2 pack's themed picture for one of the add-on's own drawings, else the file itself."""
    from . import icons
    return icons.family(str(path))
