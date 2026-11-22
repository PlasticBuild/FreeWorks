# SPDX-License-Identifier: LGPL-2.1-or-later
""







import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import paths

PARAM = "ViewMenuGrouped"
SORTED = "swViewMenuSorted"
TICK = 1000


GROUPS = (
    ("Display",
     ("Std_OrthographicCamera", "Std_PerspectiveCamera", "SWStyle_SectionView", "Std_ToggleClipPlane",
      "SWStyle_ModelBreakView", "SWStyle_ToggleModelBreak", "SWStyle_ChangeDisplayStates", "SWStyle_AddDisplayState",
      "SWStyle_TangentEdgesVisible", "SWStyle_TangentEdgesPhantom", "SWStyle_TangentEdgesRemoved", "SWStyle_ShadowsInShadedMode", "SWStyle_Cartoon", "SWStyle_DraftQualityHLR",
      "Std_ToggleTransparency", "Std_SetMaterial", "Std_SetAppearance", "Std_RandomColor", "Part_ColorPerFace",
      "Std_TextureMapping"),
     ("Draw Style", "Freeze Display", "Stereo")),
    ("Modify",
     ("SWStyle_ViewOrientation", "SWStyle_NormalTo", "SWStyle_PreviousView", "SWStyle_ZoomFit", "SWStyle_GoToMarkupView",
      "SWStyle_RotateAboutSceneFloor", "SWStyle_TurnCamera", "SWStyle_ZoomAboutScreenCenter"),
     ("Orientation", "Zoom", "Set Current View As", "Standard Views")),
    ("Lights and Cameras",
     ("SWStyle_AddCamera", "SWStyle_CameraView", "SWStyle_AddWalkThrough", "SWStyle_PlayWalkThrough"),
     ()),
    ("Hide / Show",
     ("Std_AxisCross", "Std_SelBoundingBox"),
     ("Visibility",)),
    ("User Interface",
     ("Std_ViewCreate", "Std_ToggleNavigation", "Std_ViewStatusBar"),
     ("Selection Filter", "Document Window", "Workbench", "Panels", "Overlay Docked Panel", "Link Navigation",
      "Tree View Actions")),
)
TOOLBARS = "Std_ToolBarMenu"
FULL_SCREEN = "Std_MainFullscreen"

_watch = None
sorts = []            # (top-level titles) after each sort, for checks


def _title(action):
    return action.text().replace("&", "").strip()


def view_menu():
    mw = Gui.getMainWindow()
    bar = mw.menuBar() if mw is not None else None
    if bar is None:
        return None
    # by FreeCAD's own name for it (untranslated). FreeCAD makes a new View menu on every
    # workbench change and the old ones stay behind, out of the bar: the one in the bar counts
    shown = bar.actions()
    for menu in bar.findChildren(QtWidgets.QMenu, "&View"):
        if menu.menuAction() in shown:
            return menu
    return None


def _ours(menu):
    ""

    subs = {}
    for sub in menu.findChildren(QtWidgets.QMenu):
        if sub.parent() is menu and sub.objectName().startswith("SWViewMenu_"):
            subs[sub.title()] = sub
    for title, _names, _menus_in in GROUPS:
        if title not in subs:
            sub = QtWidgets.QMenu(title, menu)
            sub.setObjectName("SWViewMenu_" + title.replace(" / ", "").replace(" ", ""))
            subs[title] = sub
    return subs


def _alive(obj):
    try:
        obj.objectName()
        return True
    except RuntimeError:
        return False


def _group_of(action):
    name = action.objectName()
    title = _title(action)
    for group, names, submenus in GROUPS:
        if name in names or (action.menu() is not None and title in submenus):
            return group
    return None


def sort(menu=None):
    ""
    menu = menu or view_menu()
    store = paths.params()
    if menu is None or not store.GetBool(PARAM, True) or not store.GetBool("Enabled", True):
        return False
    subs = _ours(menu)
    mine = set(id(s.menuAction()) for s in subs.values())
    entries = [a for a in menu.actions() if id(a) not in mine]
    for sub in subs.values():
        entries += sub.actions()
        for a in list(sub.actions()):
            sub.removeAction(a)
    for a in list(menu.actions()):
        menu.removeAction(a)
    seen = set()
    entries = [a for a in entries if not (id(a) in seen or seen.add(id(a)))]
    grouped = {title: [] for title in subs}
    toolbars, full, other = [], [], []
    for a in entries:
        if a.isSeparator():
            continue
        if a.objectName() == TOOLBARS:
            toolbars.append(a)
        elif a.objectName() == FULL_SCREEN:
            full.append(a)
        else:
            group = _group_of(a)
            (grouped[group] if group else other).append(a)
    for title, names, submenus in GROUPS:
        # each submenu in the order above: commands first, then FreeCAD's submenus
        order = {n: i for i, n in enumerate(names)}
        order.update({t: len(names) + i for i, t in enumerate(submenus)})
        grouped[title].sort(key=lambda a: order.get(a.objectName() if a.menu() is None else _title(a), 99))
    top = []
    for title, _names, _submenus in GROUPS[:-1]:
        if grouped[title]:
            subs[title].addActions(grouped[title])
            menu.addMenu(subs[title])
            top.append(title)
    for a in other:
        menu.addAction(a)
        top.append(_title(a))
    if toolbars or grouped["User Interface"]:
        menu.addSeparator()
    for a in toolbars:
        menu.addAction(a)
        top.append(_title(a))
    if grouped["User Interface"]:
        subs["User Interface"].addActions(grouped["User Interface"])
        menu.addMenu(subs["User Interface"])
        top.append("User Interface")
    if full:
        menu.addSeparator()
        menu.addActions(full)
        top.append(_title(full[0]))
    menu.setProperty(SORTED, True)
    sorts.append(tuple(top))
    return True


def _showing():
    sort(view_menu())


def _hook():
    try:
        menu = view_menu()
        if menu is None or menu.property("swViewMenuHooked"):
            return
        menu.setProperty("swViewMenuHooked", True)
        # no reference to the menu kept here: PySide hands out a dead copy of a menu it still
        # holds once FreeCAD has deleted it and made the next View menu at the same address
        menu.aboutToShow.connect(_showing)
        sort(menu)
    except Exception as error:
        import FreeCAD as App
        App.Console.PrintLog("View menu not grouped: %s\n" % error)


def install():
    global _watch
    if _watch is not None:
        return
    _watch = QtCore.QTimer()
    _watch.setInterval(TICK)
    _watch.timeout.connect(_hook)
    _watch.start()


def remove():
    global _watch
    if _watch is not None:
        _watch.stop()
    _watch = None
