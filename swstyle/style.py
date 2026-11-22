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

import json
import os
import string
import xml.etree.ElementTree as ET

import FreeCAD as App
from PySide import QtCore, QtGui, QtWidgets

from . import keys, paths

VIEW = "User parameter:BaseApp/Preferences/View"
TREE = "User parameter:BaseApp/Preferences/TreeView"
SKETCHER_TOOLS = "User parameter:BaseApp/Preferences/Mod/Sketcher/Tools"
MAINWINDOW = "User parameter:BaseApp/Preferences/MainWindow"
GENERAL = "User parameter:BaseApp/Preferences/General"
LIGHTS = "User parameter:BaseApp/Preferences/View/LightSources"

# draws through the Windows theme API. Qt's default windows11 style picks its
# colours when it is created, so with Windows in dark mode its checkboxes and
# spin arrows stay dark on the light panes. FreeCAD switches styles itself
# when MainWindow/QtStyle changes.
NATIVE_STYLE = "windowsvista"
# FreeCAD's own light theme. On a first start the Start page applies "FreeCAD
# Dark" when Windows is in dark mode, and that theme's style sheet paints every
# label white, so the look applies the light preference pack itself (its
# colours for the tree, report view, spreadsheet, TechDraw and so on) and then

LIGHT_PACK = "FreeCAD Light"
_PACK_KINDS = {"FCBool": "Boolean", "FCInt": "Integer", "FCUInt": "Unsigned Long",
               "FCFloat": "Float", "FCText": "String"}
_PACK_PARSE = {"Boolean": lambda v: v.strip() not in ("", "0", "false"), "Integer": int,
               "Unsigned Long": int, "Float": float, "String": str}
# Pack entries the look decides itself (see SETTINGS and NATIVE_STYLE).
_PACK_SKIP = {(MAINWINDOW, "QtStyle"), (MAINWINDOW, "StyleSheet")}
TOOLBARS = "User parameter:BaseApp/MainWindow/Toolbars"
DOCKS = "User parameter:BaseApp/MainWindow/DockWindows"
# FreeCAD 1.1 floats the docks listed here over the 3D view; with no entry the
# right side defaults to "Tasks,".
OVERLAYS = tuple(DOCKS + "/Overlay" + side for side in ("Left", "Right", "Top", "Bottom"))


# defined black, over defined red, driven dimensions grey, dynamic highlight
# orange, selection blue. FreeCAD's defaults draw sketches white, which
# disappears on the light viewport.
SW_BLUE = 0x0000FFFF
SW_BLACK = 0x000000FF
SKETCH_COLORS = (
    ("EditedEdgeColor", SW_BLUE),
    ("CreateLineColor", SW_BLUE),
    ("ConstructionColor", SW_BLUE),
    ("InternalAlignedGeoColor", SW_BLUE),
    ("FullyConstraintElementColor", SW_BLACK),
    ("FullyConstrainedColor", SW_BLACK),
    ("FullyConstraintConstructionElementColor", SW_BLACK),
    ("FullyConstraintInternalAlignmentColor", SW_BLACK),
    ("FullyConstraintConstructionPointColor", SW_BLACK),

    # model edge colour (DefaultShapeLineColor, FreeCAD's 0x191919) they sit unseen on the edge.
    ("ExternalColor", 0x191919FF),
    ("ExternalDefiningColor", SW_BLACK),
    ("InvalidSketchColor", 0xD7D700FF),
    ("ConstrainedDimColor", SW_BLACK),
    ("ExprBasedConstrDimColor", SW_BLACK),
    ("NonDrivingConstrDimColor", 0x808080FF),
    ("DeactivatedConstrDimColor", 0xA0A0A0FF),
    ("ConstrainedIcoColor", 0x00CC33FF),
    ("CursorTextColor", SW_BLACK),
    ("CursorCrosshairColor", SW_BLACK),
    ("SketchEdgeColor", 0x5A5A5AFF),
    ("SketchVertexColor", 0x5A5A5AFF),
    ("HighlightColor", 0xFF8000FF),

    # preselection above (FreeCAD's default is yellow; 16-min 2025 video 4:20, the hovered circle)
    ("PreselectColor", 0xFF8000FF),

    # edges and lines. FreeCAD adds it to a picked face's lit grey, so flatselect.py draws picked

    ("SelectionColor", 0x53A9FFFF),
)

# The same on a dark viewport: fully defined white, under defined a lighter blue, the rest
# lifted so it reads on the dark gradient and on black (every colour at least 3:1 against the
# Dark gradient's lightest band #3c3f45; Ati 21:55Z: lines must stay readable in Dark and AMOLED).
DARK_SKETCH_COLORS = tuple((name, {
    SW_BLUE: 0x5C9DFFFF, SW_BLACK: 0xF0F0F0FF, 0x404040FF: 0xA0A0A0FF, 0xFF0000FF: 0xFF6B6BFF,
    0x808080FF: 0xA8A8A8FF, 0xA0A0A0FF: 0x8A8A8AFF, 0x00CC33FF: 0x00CC33FF, 0x5A5A5AFF: 0xC8C8C8FF,
}.get(value, value)) for name, value in SKETCH_COLORS)


# default, read live from these entries). Dark viewports get a lighter one. Light viewports get
# the default WRITTEN, not the entry removed: the Sketcher reads every View colour with its
# current value as the fallback (EditModeCoinManager::ParameterObserver::updateColor), so a
# removed entry keeps the old colour until the next start (snapping thread, 21:37Z).

# seen square on (Ati, 2026-10-28). The amber that replaced it was lost in turn on the
# near-white plate face in Dark (Ati's video 04:20Z): the guides are drawn mostly over the part,
# whatever the viewport. So they are mid-tones that read on the light part face and on the dark


DARK_ONLY_COLORS = (
    ("SnapGuideRelationColor", 0x7466F0FF),
    ("SnapGuideSnapColor", 0x7466F0FF),
    ("SnapGuideCandidateColor", 0xE06000FF),
)
LIGHT_ONLY_COLORS = (
    ("SnapGuideRelationColor", 0x695EE3FF),
    ("SnapGuideSnapColor", 0x695EE3FF),
    ("SnapGuideCandidateColor", 0xE06000FF),
)

THEMES = ("Light", "Medium Light", "Medium", "Dark", "AMOLED")      # themes-medium-1120
THEME_SETTING = "Theme"
SCENE_SETTING = "Scene"          # a scene picked by hand: -1 = the theme's own viewport

# 2024 (top #ebedf3, darkest band #dadee9 at mid height, white at the bottom).
THEME_SCENES = {
    "Light": (True, 0xEBEDF3FF, 0xDADEE9FF, 0xFEFEFEFF),

    # view, which stays available as the first hand-picked scene). A dark grey gradient, darkest at
    # mid height like the light one.
    "Dark": (True, 0x33363BFF, 0x26282CFF, 0x3C3F45FF),
    "AMOLED": (False, 0x000000FF, 0x000000FF, 0x000000FF),
}
THEME_SCENES["Medium Light"] = THEME_SCENES["Medium"] = THEME_SCENES["Light"]     # themes-medium-1120: the viewport does not change
THEME_PACKS = {"Light": "FreeCAD Light", "Medium Light": "FreeCAD Light", "Medium": "FreeCAD Light", "Dark": "FreeCAD Dark",
               "AMOLED": "FreeCAD Dark"}
# Dark themes draw the classic controls with Qt's Fusion style, which takes every colour from
# the palette; the Windows style keeps light controls whatever the palette says.
THEME_QT_STYLES = {"Light": None, "Medium Light": None, "Medium": None, "Dark": "Fusion", "AMOLED": "Fusion"}

# (group, type, name, value) for every theme.
SETTINGS = (
    (VIEW, "Boolean", "RadialGradient", False),
    (VIEW, "Boolean", "ShowNaviCube", False),

    (VIEW, "Boolean", "CornerCoordSystem", False),
    (VIEW, "Boolean", "ShowAxisCross", False),
    (VIEW, "String", "NavigationStyle", "Gui::SolidWorksNavigationStyle"),
    (MAINWINDOW, "String", "StyleSheet", ""),

    # shows its task watcher ("Start Part", "New Body") there. The ribbon has those.
    (GENERAL, "Boolean", "ShowTaskWatcher", False),

    ("User parameter:BaseApp/Preferences/RecentFiles", "Integer", "RecentFiles", 50),
    ("User parameter:BaseApp/Preferences/Document", "Integer", "MaxUndoSize", 50),
    (TREE, "Boolean", "VisibilityIcon", False),

    (TREE, "Integer", "ItemSpacing", 6),
    (TREE, "Boolean", "CheckBoxesSelection", False),

    # 255,255,255); FreeCAD's Light pack tints the page #f1f3f5 and draws lines #212529.
    ("User parameter:BaseApp/Preferences/Mod/TechDraw/Colors", "Unsigned Long", "PageColor", 0xFFFFFFFF),
    ("User parameter:BaseApp/Preferences/Mod/TechDraw/Colors", "Unsigned Long", "NormalColor", 0x000000FF),

    # Drawings Background grey-blue, Visible and Hidden Model Edges black, dimension Text black, Dynamic
    # Highlight orange, Selected Item blue). FreeCAD's Light pack tinted them: views were filled #f1f3f5 over

    # picked items green, the space around the sheet neutral #d3d3d3.
    ("User parameter:BaseApp/Preferences/Mod/TechDraw/Colors", "Unsigned Long", "FaceColor", 0xFFFFFFFF),
    ("User parameter:BaseApp/Preferences/Mod/TechDraw/Colors", "Boolean", "ClearFace", True),
    ("User parameter:BaseApp/Preferences/Mod/TechDraw/Colors", "Unsigned Long", "HiddenColor", 0x000000FF),
    ("User parameter:BaseApp/Preferences/Mod/TechDraw/Colors", "Unsigned Long", "SelectColor", 0x0093FDFF),
    ("User parameter:BaseApp/Preferences/Mod/TechDraw/Colors", "Unsigned Long", "PreSelectColor", 0xFF8C00FF),
    ("User parameter:BaseApp/Preferences/Mod/TechDraw/Colors", "Unsigned Long", "Background", 0xC3CBD6FF),
    ("User parameter:BaseApp/Preferences/Mod/TechDraw/Dimensions", "Unsigned Long", "Color", 0x000000FF),
    ("User parameter:BaseApp/Preferences/Mod/TechDraw/Decorations", "Unsigned Long", "CenterColor", 0x000000FF),
    ("User parameter:BaseApp/Preferences/Mod/TechDraw/Decorations", "Unsigned Long", "SectionColor", 0x000000FF),
    ("User parameter:BaseApp/Preferences/Mod/TechDraw/Decorations", "Unsigned Long", "VertexColor", 0x000000FF),
    ("User parameter:BaseApp/Preferences/Mod/TechDraw/Decorations", "Unsigned Long", "HighlightColor", 0x000000FF),

    (SKETCHER_TOOLS, "Integer", "OnViewParameterVisibility", 0),

    # Dimensions "Show units of dimensions" is off by default (16-min 2025 video, Beginners-1)
    ("User parameter:BaseApp/Preferences/Mod/Sketcher", "Boolean", "HideUnits", True),

    # the isometric view (top face #a0a5bb, lower left #51545f, lower right #7c8092;
    # FreeCAD gives #9fa4ba, #535560, #7b7e8f): one key light from the upper right,

    # parts made while the style is on. The lights follow the camera.
    (VIEW, "Unsigned Long", "DefaultShapeColor", 0x8F94AAFF),

    # face seen square on (Top while sketching) pure white and drowned the sketch lines (Ati,
    # 2026-10-28). Less shine and less fill light: square on #afb4c8, the isometric top #9498ab.
    (VIEW, "Unsigned Long", "DefaultSpecularColor", 0x1A1A1AFF),
    (VIEW, "Integer", "DefaultShapeShininess", 10),
    (LIGHTS, "Boolean", "EnableHeadlight", True),
    (LIGHTS, "String", "HeadlightDirection", "(-0.35,-0.55,-0.76)"),
    (LIGHTS, "Integer", "HeadlightIntensity", 70),
    (LIGHTS, "Unsigned Long", "HeadlightColor", 0xFFFFFFFF),
    (LIGHTS, "Boolean", "EnableBacklight", False),
    (LIGHTS, "Boolean", "EnableFillLight", True),
    (LIGHTS, "String", "FillLightDirection", "(0,0,-1)"),
    (LIGHTS, "Integer", "FillLightIntensity", 38),
    (LIGHTS, "Unsigned Long", "FillLightColor", 0xFFFFFFFF),
) + keys.settings()
SNAPSHOT_GROUPS = (TOOLBARS, DOCKS) + OVERLAYS


def theme_name():
    """The theme in the addon's settings: Light, Dark or AMOLED."""
    try:
        name = paths.params().GetString(THEME_SETTING, "Dark")     # freshdark-1121: a fresh install starts Dark
    except Exception:
        name = "Dark"
    return name if name in THEMES else "Dark"


_applied_theme = None     # the theme whose look is on screen; None before the first switch


def current_theme():
    """The theme the window is drawn in: the setting, unless a switch waits for a sketch or feature
    to be closed (set_theme)."""
    return _applied_theme or theme_name()


def dark():
    return current_theme() in ("Dark", "AMOLED")


def _scene_colours(name=None, scene=None):
    """(gradient, top, mid, bottom) of the viewport: the theme's own, or a hand-picked scene."""
    name = name or current_theme()
    if scene is None:
        try:
            scene = paths.params().GetInt(SCENE_SETTING, -1)
        except Exception:
            scene = -1
    if 0 <= scene < len(SCENES):
        _, (top, mid, bottom), gradient = SCENES[scene]
        return gradient, top, mid, bottom
    return THEME_SCENES[name]


def current_scene():
    """The hand-picked scene's index, or -1 for the theme's own viewport."""
    try:
        scene = paths.params().GetInt(SCENE_SETTING, -1)
    except Exception:
        scene = -1
    return scene if 0 <= scene < len(SCENES) else -1


def _is_dark(value):
    r, g, b = (value >> 24) & 0xFF, (value >> 16) & 0xFF, (value >> 8) & 0xFF
    return (0.299 * r + 0.587 * g + 0.114 * b) < 110


def scene_dark(name=None, scene=None):
    """True when the viewport the theme (or the picked scene) sets is dark: the sketch colours and
    the inference-line colours follow this, not the panes."""
    return _is_dark(_scene_colours(name, scene)[1])


def scene_settings(name=None, scene=None):
    """(group, type, name, value) for the viewport: the theme's own, or a hand-picked scene."""
    gradient, top, mid, bottom = _scene_colours(name, scene)
    picked = current_scene() if scene is None else scene
    radial = picked in RADIAL_SCENES
    if radial:
        # FreeCAD's radial gradient runs from BackgroundColor2 in the middle to BackgroundColor3
        return ((VIEW, "Boolean", "Gradient", False),
                (VIEW, "Boolean", "RadialGradient", True),
                (VIEW, "Boolean", "UseBackgroundColorMid", False),
                (VIEW, "Unsigned Long", "BackgroundColor", top),
                (VIEW, "Unsigned Long", "BackgroundColor2", top),
                (VIEW, "Unsigned Long", "BackgroundColor4", mid),
                (VIEW, "Unsigned Long", "BackgroundColor3", bottom))
    return ((VIEW, "Boolean", "Gradient", gradient),
            (VIEW, "Boolean", "RadialGradient", False),
            (VIEW, "Boolean", "UseBackgroundColorMid", gradient),
            (VIEW, "Unsigned Long", "BackgroundColor", top),
            (VIEW, "Unsigned Long", "BackgroundColor2", top),
            (VIEW, "Unsigned Long", "BackgroundColor4", mid),
            (VIEW, "Unsigned Long", "BackgroundColor3", bottom))


def theme_settings(name=None):
    """The theme's own entries: FreeCAD's theme name, the viewport and the sketch colours."""
    name = name or current_theme()
    colours = DARK_SKETCH_COLORS + DARK_ONLY_COLORS if scene_dark(name) else SKETCH_COLORS + LIGHT_ONLY_COLORS
    return ((MAINWINDOW, "String", "Theme", THEME_PACKS[name]),) + scene_settings(name) \
        + tuple((VIEW, "Unsigned Long", n, v) for n, v in colours) + view_lights(name)


# A dark 3D view (Dark's own scene, Ati 10-25): the plate's lower left face was #303136, lost in the
# scene's #2e3135..#45484f. A soft light from the left lifts only the faces turned away from the key

# face seen square on keep their Light-theme colours, so sketch lines over them read the same.
DARK_VIEW_LIGHTS = ((LIGHTS, "Boolean", "EnableBacklight", True),
                    (LIGHTS, "String", "BacklightDirection", "(0.85,0.3,-0.2)"),
                    (LIGHTS, "Integer", "BacklightIntensity", 25),
                    (LIGHTS, "Unsigned Long", "BacklightColor", 0xFFFFFFFF))


def view_lights(name=None):
    """The lights that differ with the 3D view: the left light on a dark view only."""
    return DARK_VIEW_LIGHTS if scene_dark(name) else ((LIGHTS, "Boolean", "EnableBacklight", False),)


_applied_style = None     # the Qt style set_theme put in place (Qt hides it behind QStyleSheetStyle)


def _live_style():
    """The Qt style's own name, or "" when a style sheet hides it (Qt wraps the style in a
    QStyleSheetStyle that names nothing)."""
    app = QtWidgets.QApplication.instance()
    if app is None:
        return ""
    try:
        name = app.style().name()
    except Exception:
        name = ""
    return "" if name.lower() == "qstylesheetstyle" else name


def _style_name():
    """The Qt style in use: the one this module set, else Qt's own name, else FreeCAD's QtStyle
    setting (what FreeCAD applied at its start)."""
    return _applied_style or _live_style() or App.ParamGet(MAINWINDOW).GetString("QtStyle", "")


def _pack_file(name):
    for getter in ("getResourceDir", "getUserAppDataDir"):
        fn = getattr(App, getter, None)
        if fn is None:
            continue
        try:
            path = os.path.join(fn(), "Gui", "PreferencePacks", name, name + ".cfg")
        except Exception:
            continue
        if os.path.isfile(path):
            return path
    return None


def pack_settings(name=LIGHT_PACK):
    """(group, type, name, value) for every entry of a FreeCAD preference pack."""
    path = _pack_file(name)
    if path is None:
        App.Console.PrintWarning("FreeCAD: preference pack %r not found\n" % name)
        return ()
    cached = _pack_cache(path)
    if cached is not None:
        return cached
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as error:
        App.Console.PrintWarning("FreeCAD: %s not read: %s\n" % (path, error))
        return ()
    found = []

    def walk(node, parts):
        for child in node:
            if child.tag == "FCParamGroup":
                walk(child, parts + [child.get("Name", "")])
                continue
            kind = _PACK_KINDS.get(child.tag)
            if kind is None or not parts:
                continue
            group = "User parameter:" + "/".join(parts)
            if (group, child.get("Name")) in _PACK_SKIP:
                continue
            raw = (child.text or "") if child.tag == "FCText" else child.get("Value", "")
            try:
                found.append((group, kind, child.get("Name"), _PACK_PARSE[kind](raw)))
            except ValueError as _fw_err:
                _fw_log("style.py:363", _fw_err)

    for top in root:  # the "Root" group is the user parameter root itself
        if top.tag == "FCParamGroup":
            walk(top, [])
    _pack_cache(path, tuple(found))
    return tuple(found)


_PACKS_READ = {}


def _pack_cache(path, value=None):
    """The pack's entries kept from an earlier read while the file is unchanged: in memory, and in
    FreeCAD's cache folder across starts (the XML parse was 83 ms of each start)."""
    import json
    try:
        st = os.stat(path)
        stamp = [path, st.st_mtime, st.st_size]
        store = os.path.join(App.getUserCachePath(), "FreeWorks-pack-%s.json"
                             % os.path.splitext(os.path.basename(path))[0])
    except Exception:
        return None
    if value is not None:
        _PACKS_READ[path] = (stamp, value)
        try:
            with open(store, "w") as f:
                json.dump({"stamp": stamp, "rows": [list(r) for r in value]}, f)
        except Exception as _fw_err:
            _fw_log("style.py:392", _fw_err)
        return value
    hit = _PACKS_READ.get(path)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    try:
        with open(store) as f:
            data = json.load(f)
        if data.get("stamp") == stamp:
            rows = tuple(tuple(r) for r in data["rows"])
            _PACKS_READ[path] = (stamp, rows)
            return rows
    except Exception as _fw_err:
        _fw_log("style.py:405", _fw_err)
    return None


def qt_style_name(name=None):
    """The Qt style the theme draws FreeCAD's own controls with, or None to leave it."""
    name = name or current_theme()
    wanted = THEME_QT_STYLES.get(name)
    available = {key.lower(): key for key in QtWidgets.QStyleFactory.keys()}
    if wanted is None:
        wanted = NATIVE_STYLE
    return available.get(wanted.lower())


def _settings(name=None):
    """FreeCAD's preference pack for the theme (light or dark), then SETTINGS, the theme's own
    entries, then the Qt style: the native Windows controls for Light where Qt has them, Fusion
    for the dark themes."""
    name = name or current_theme()
    settings = pack_settings(THEME_PACKS[name]) + SETTINGS + theme_settings(name) + user_settings()
    style_name = qt_style_name(name)
    if style_name:
        settings += ((MAINWINDOW, "String", "QtStyle", style_name),)
    return settings

# The Options box's own choices for entries the look also sets (the colour scheme, the viewport
# background, the triad): kept here and written after the look's entries, so a colour picked in
# Options survives the next start and a change of look. [[group, type, name, value]]
USER_SETTINGS = "UserSettings"


def user_settings():
    try:
        return tuple(tuple(e) for e in json.loads(paths.params().GetString(USER_SETTINGS, "") or "[]"))
    except (ValueError, TypeError):
        return ()


def managed(path, name):
    """True when the look writes this entry at every start (so Options must keep the user's own)."""
    return any(p == path and n == name for p, _k, n, _v in _settings())


def set_user_setting(path, kind, name, value=None):
    """Keeps the user's own value for one entry the look sets and writes it now; value None drops
    it and puts the look's value back."""
    kept = [e for e in user_settings() if (e[0], e[2]) != (path, name)]
    if value is not None:
        kept.append((path, kind, name, value))
    paths.params().SetString(USER_SETTINGS, json.dumps(kept))
    if value is None:
        value = next((v for p, k, n, v in reversed(_settings()) if p == path and n == name and k == kind), None)
    if value is not None:
        getattr(App.ParamGet(path), _SET[kind])(name, value)


_SET = {"Boolean": "SetBool", "Integer": "SetInt", "Unsigned Long": "SetUnsigned",
        "String": "SetString", "Float": "SetFloat"}
_REM = {"Boolean": "RemBool", "Integer": "RemInt", "Unsigned Long": "RemUnsigned",
        "String": "RemString", "Float": "RemFloat"}


def _contents(path):
    try:
        return App.ParamGet(path).GetContents() or []
    except Exception:
        return []


def _lookup(path, kind, name):
    for k, n, v in _contents(path):
        if k == kind and n == name:
            return True, v
    return False, None


def apply_settings():
    store = paths.params()
    try:
        backup = json.loads(store.GetString("Backup", "") or "{}")
    except ValueError:
        backup = {}
    backup.setdefault("settings", [])
    backup.setdefault("groups", {})
    # The Qt style in use, for when FreeCAD's own QtStyle setting is empty.
    backup.setdefault("qt_style", _style_name())
    settings = _settings()
    # A backup written by an older version lacks newer entries; their current
    # values are still the user's own, so add them before changing anything.
    known = {(path, kind, name) for path, kind, name, _, _ in backup["settings"]}
    for path, kind, name, _ in settings:
        if (path, kind, name) not in known:
            exists, old = _lookup(path, kind, name)
            backup["settings"].append([path, kind, name, exists, old])
            known.add((path, kind, name))
    for path in SNAPSHOT_GROUPS:
        if path not in backup["groups"]:
            backup["groups"][path] = [list(item) for item in _contents(path)]
    store.SetString("Backup", json.dumps(backup))
    for path, kind, name, value in settings:
        try:
            getattr(App.ParamGet(path), _SET[kind])(name, value)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s/%s not set: %s\n" % (path, name, error))


def restore_settings():
    store = paths.params()
    raw = store.GetString("Backup", "")
    if not raw:
        return False
    try:
        backup = json.loads(raw)
    except ValueError:
        store.RemString("Backup")
        return False
    for path, kind, name, exists, old in backup.get("settings", []):
        grp = App.ParamGet(path)
        try:
            if exists:
                getattr(grp, _SET[kind])(name, old)
            else:
                getattr(grp, _REM[kind])(name)
        except Exception as _fw_err:
            _fw_log("style.py:529", _fw_err)
    for path, items in backup.get("groups", {}).items():
        grp = App.ParamGet(path)
        saved = {(k, n): v for k, n, v in items}
        for k, n, v in _contents(path):
            if (k, n) not in saved and k in _REM:
                try:
                    getattr(grp, _REM[k])(n)
                except Exception as _fw_err:
                    _fw_log("style.py:538", _fw_err)
        for (k, n), v in saved.items():
            if k in _SET:
                try:
                    getattr(grp, _SET[k])(n, v)
                except Exception as _fw_err:
                    _fw_log("style.py:544", _fw_err)
    store.RemString("Backup")
    # FreeCAD ignores an empty QtStyle, so put the previous Qt style back here.
    name = backup.get("qt_style") or ""
    if name and not App.ParamGet(MAINWINDOW).GetString("QtStyle", "") and _style_name() != name:
        native = QtWidgets.QStyleFactory.create(name)
        if native is not None:
            QtWidgets.QApplication.setStyle(native)
    return True


# --------------------------------------------------------------------------- the themes



# rollback bar) stay the same in every theme.
TOKENS = {
    "Light": {

        # row is the CommandManager's own #f6f6f6 (it was #e6e6e6 here), the tab strip #d4d4d4, a
        # picked FeatureManager row #a6c8e2 (tree_selection)
        "pane": "#f7f7f7", "qat": "#f6f6f6", "tab": "#d4d4d4", "tab_hover": "#e2e2e2",
        "line": "#838383", "line_light": "#c5c5c5", "line_mid": "#a9a9a9",
        "text": "#000000", "text_dim": "#5a5a5a", "text_disabled": "#a0a0a0",
        "arrow": "#404040", "arrow_dim": "#808080", "arrow_disabled": "#b4b4b4",
        "base": "#ffffff", "hover": "#e3e3e3", "hover_line": "#c6c6c6", "down": "#c8c8c8", "down_line": "#939393",
        "menu_hover": "#cce8ff", "selection": "#c9e0f7", "accent": "#2f80ed",
        "arrow_bg": "#fafafa", "arrow_line": "#bcbcbc", "grip_line": "#9a9a9a", "grip_fill": "#dedede",
        "tab_underline": "#bcc4cc", "glyph": "#8a96a3", "field_line": "#b4b4b4",
        "field": "#ffffff", "field_text": "#000000", "tree_selection": "#a6c8e2",
    },

    # study thread (JPEG, +-3 per channel): chrome #494949 (title row, CommandManager, panes, status
    # bar), tab strip #333333 with the active tab #484848, separators #535253, pressed toggles dark
    # teal #3f5c62, text ~#f0f0f0. Its PropertyManager list boxes and edit fields stay white
    # (tokens field / field_text). The 3D view is dark here at Ati's wish (THEME_SCENES).
    "Dark": {
        "pane": "#494949", "qat": "#494949", "tab": "#333333", "tab_hover": "#3e3e3e",
        "line": "#2b2b2b", "line_light": "#535253", "line_mid": "#5e5e5e",
        "text": "#f0f0f0", "text_dim": "#c4c4c4", "text_disabled": "#8c8c8c",
        "arrow": "#e2e2e2", "arrow_dim": "#aaaaaa", "arrow_disabled": "#707070",
        "base": "#3d3d3d", "hover": "#585858", "hover_line": "#6f6f6f", "down": "#3f5c62", "down_line": "#5d8794",
        "menu_hover": "#3b5f8a", "selection": "#35578a", "accent": "#2f80ed",
        "arrow_bg": "#4f4f4f", "arrow_line": "#666666", "grip_line": "#7a7a7a", "grip_fill": "#5a5a5a",
        "tab_underline": "#6b7280", "glyph": "#b4bec9", "field_line": "#6a6a6a",
        "field": "#ffffff", "field_text": "#000000", "tree_selection": "#35578a",
    },
    "AMOLED": {
        "pane": "#000000", "qat": "#000000", "tab": "#161616", "tab_hover": "#242424",
        "line": "#2a2a2a", "line_light": "#262626", "line_mid": "#333333",
        "text": "#f2f2f2", "text_dim": "#b0b0b0", "text_disabled": "#666666",
        "arrow": "#d0d0d0", "arrow_dim": "#8a8a8a", "arrow_disabled": "#4a4a4a",
        "base": "#000000", "hover": "#1f1f1f", "hover_line": "#333333", "down": "#2c2c2c", "down_line": "#444444",
        "menu_hover": "#1e3a5f", "selection": "#1e3a5f", "accent": "#2f80ed",
        "arrow_bg": "#0a0a0a", "arrow_line": "#2e2e2e", "grip_line": "#555555", "grip_fill": "#222222",
        "tab_underline": "#3a4452", "glyph": "#8a94a0", "field_line": "#3a3a3a",
        "field": "#000000", "field_text": "#f2f2f2", "tree_selection": "#1e3a5f",
    },
}



# (RESULTS part 7); the rest is derived from Light and is an estimate (marked "est").
TOKENS["Medium Light"] = dict(TOKENS["Light"], **{
    "pane": "#d6dadd", "qat": "#d6dadd", "tab": "#eaedf1", "tab_hover": "#f2f4f7",              # chrome, tab strip: sampled
    "line": "#7d8286", "line_light": "#b4b9bd", "line_mid": "#a0a6aa",                             # est
    "text_dim": "#4f5458", "text_disabled": "#8f9599",                                              # est
    "arrow_dim": "#767c80", "arrow_disabled": "#a9afb3",
    "hover": "#e4e7ea", "hover_line": "#b8bec4", "down": "#bcc2c8", "down_line": "#8d949a",        # est
    "menu_hover": "#cce8ff", "arrow_bg": "#e6e9ec", "arrow_line": "#b0b6bb",
    "grip_line": "#8f969b", "grip_fill": "#c7ccd1", "tab_underline": "#aab2ba", "glyph": "#7d8993",
    "menu": "#eff0f4",                                                                              # menus: sampled
})
TOKENS["Medium"] = dict(TOKENS["Light"], **{
    "pane": "#b3b5b4", "qat": "#b3b5b4", "tab": "#c4c6c5", "tab_hover": "#cdcfce",                # chrome: sampled; tab strip est
    "line": "#6f7170", "line_light": "#939594", "line_mid": "#8a8c8b",                             # est
    "text_dim": "#3f4140", "text_disabled": "#7d7f7e",
    "arrow_dim": "#5a5c5b", "arrow_disabled": "#8e908f",
    "hover": "#c7c8c7", "hover_line": "#8f9190", "down": "#9fa1a0", "down_line": "#7f8180",
    "menu_hover": "#d2d2d2", "arrow_bg": "#bdbfbe", "arrow_line": "#8e908f",                      # menu hover: sampled
    "grip_line": "#7f8180", "grip_fill": "#a4a6a5", "tab_underline": "#8a8c8b", "glyph": "#585a59",
    "menu": "#b3b5b4",                                                                              # menus: sampled
})
TOKENS["Light"].setdefault("menu", "#ffffff")
TOKENS["Dark"].setdefault("menu", "#3d3d3d")
TOKENS["AMOLED"].setdefault("menu", "#000000")


def tokens(name=None):
    return TOKENS[name or current_theme()]


class _Tokens:
    """T.pane, T.text, ... as QColor for the current theme, read when painting."""

    def __getattr__(self, name):
        try:
            return QtGui.QColor(tokens()[name])
        except KeyError:
            raise AttributeError(name)

    def hex(self, name):
        return tokens()[name]

    def rgba(self, name, alpha):
        c = QtGui.QColor(tokens()[name])
        c.setAlpha(alpha)
        return c


T = _Tokens()


class _Signals(QtCore.QObject):
    theme_changed = QtCore.Signal(str)


signals = _Signals()


def set_theme(name, scene=-1):
    """Switches the look: the settings (viewport, sketch colours, FreeCAD's pack, the Qt style),
    the palette, then theme_changed for the style sheets. scene: a hand-picked viewport scene, -1
    for the theme's own. While a sketch or feature is being edited only the setting is written:
    FreeCAD 1.1.4 crashes when the window is restyled with the sketcher's task panel open, so the
    look follows when the panel closes (apply_pending, from the shell's poll)."""
    global _pending_theme
    if name not in THEMES:
        raise ValueError(name)
    store = paths.params()
    store.SetString(THEME_SETTING, name)
    store.SetInt(SCENE_SETTING, int(scene))
    if _edit_open():
        _pending_theme = name
        App.Console.PrintMessage("FreeCAD: the %s look is applied when the sketch or feature is closed\n" % name)
        return name
    _apply_theme(name)
    return name


def mark_applied():
    """The look puts the stored theme on screen (the shell's install at start or style on): from
    here on current_theme() is that theme, so a set_theme() held back during a sketch edit does
    not flip dark() and the tokens before the switch really happens (relations thread, 22:50Z)."""
    global _applied_theme, _pending_theme
    _applied_theme = theme_name()
    _pending_theme = None
    return _applied_theme


def _apply_theme(name):
    global _pending_theme, _applied_theme
    _pending_theme = None
    _applied_theme = name
    apply_settings()
    apply_palette()
    _switch_style(qt_style_name(name))
    signals.theme_changed.emit(name)


def apply_pending():
    """Called from the shell's poll: a theme switch, or just a Qt style change, that waited for the
    task panel to close."""
    if _edit_open():
        return False
    if _pending_theme:
        _apply_theme(_pending_theme)
        return True
    if _pending_style:
        return _switch_style(_pending_style)
    return False


apply_pending_style = apply_pending


_pending_theme = None     # a theme switch held back while a sketch or feature is edited
_pending_style = None     # a Qt style change held back while a sketch is edited


def _edit_open():
    """True while a task panel is up or a document has something in edit."""
    try:
        import FreeCADGui as Gui
        if Gui.Control.activeDialog():      # a bool in FreeCAD 1.1
            return True
        for doc in App.listDocuments().values():
            gd = Gui.getDocument(doc.Name)
            if gd is not None and gd.getInEdit() is not None:
                return True
    except Exception as _fw_err:
        _fw_log("style.py:705", _fw_err)
    return False


def _switch_style(style_name):
    """Puts the theme's Qt style in place, or holds it back until no task panel is open: FreeCAD
    1.1.4 crashes (StatefulLabel under the sketcher's solver messages) when the application style
    changes while a sketch is edited; the shell's poll applies it then (apply_pending_style)."""
    global _applied_style, _pending_style
    app = QtWidgets.QApplication.instance()
    # only a style this module set, or one Qt names, counts as in place: FreeCAD's QtStyle setting
    # was just written for this theme and says nothing about the style running now
    live = _applied_style or _live_style()
    if not style_name or app is None or (live and live.lower() == style_name.lower()):
        _pending_style = None
        return False
    if _edit_open():
        _pending_style = style_name
        return False
    created = QtWidgets.QStyleFactory.create(style_name)
    _pending_style = None
    if created is None:
        return False
    app.setStyle(created)
    _applied_style = style_name
    apply_palette()      # a new style brings its own palette along
    return True


def viewport_dark():
    """True when the 3D view's background is dark (the theme's own or a hand-picked scene)."""
    try:
        grp = App.ParamGet(VIEW)
        value = grp.GetUnsigned("BackgroundColor2" if grp.GetBool("Gradient", False) else "BackgroundColor", 0xEBEDF3FF)
    except Exception:
        return dark()
    return _is_dark(value)


def viewport_ink():
    """Ink for marks drawn over the 3D view: near black on a light viewport, near white on a dark one."""
    return QtGui.QColor("#e6e6e6" if viewport_dark() else "#191919")


def fill(template, **extra):
    """A style sheet template with ${pane}, ${text}, ... filled from the current theme. ${ink} and
    ${ink_hover} are for text and hover marks drawn over the 3D view: they follow the viewport's
    brightness, not the panes'."""
    values = dict(tokens())
    values["ink"] = viewport_ink().name()
    values["ink_hover"] = "rgba(255, 255, 255, 45)" if viewport_dark() else "rgba(255, 255, 255, 110)"
    values.update(extra)
    return string.Template(template).safe_substitute(values)


# Windows 10/11 light colours. With Windows in dark mode Qt hands FreeCAD a dark

_LIGHT = {
    "Window": "#f0f0f0", "WindowText": "#000000", "Base": "#ffffff", "AlternateBase": "#f7f7f7",
    "ToolTipBase": "#ffffff", "ToolTipText": "#000000", "PlaceholderText": "#767676",
    "Text": "#000000", "Button": "#f0f0f0", "ButtonText": "#000000", "BrightText": "#ffffff",
    "Light": "#ffffff", "Midlight": "#e3e3e3", "Mid": "#a0a0a0", "Dark": "#a0a0a0",
    "Shadow": "#696969", "Highlight": "#0078d7", "HighlightedText": "#ffffff",
    "Link": "#0066cc", "LinkVisited": "#800080",
}
_LIGHT_DISABLED = {
    "WindowText": "#a0a0a0", "Text": "#a0a0a0", "ButtonText": "#a0a0a0",
    "Base": "#f0f0f0", "Highlight": "#cccccc", "HighlightedText": "#ffffff",
}
# The dark themes' palettes, for Fusion: panes, fields, buttons and text from the tokens.
_DARK = {
    "Window": "#494949", "WindowText": "#f0f0f0", "Base": "#3d3d3d", "AlternateBase": "#444444",
    "ToolTipBase": "#333333", "ToolTipText": "#f0f0f0", "PlaceholderText": "#a0a0a0",
    "Text": "#f0f0f0", "Button": "#4f4f4f", "ButtonText": "#f0f0f0", "BrightText": "#ffffff",
    "Light": "#5e5e5e", "Midlight": "#535253", "Mid": "#333333", "Dark": "#262626",
    "Shadow": "#1a1a1a", "Highlight": "#35578a", "HighlightedText": "#ffffff",
    "Link": "#6ea8ff", "LinkVisited": "#c08fe0",
}
_DARK_DISABLED = {
    "WindowText": "#8c8c8c", "Text": "#8c8c8c", "ButtonText": "#8c8c8c",
    "Base": "#424242", "Highlight": "#4a4a4a", "HighlightedText": "#9a9a9a",
}
_AMOLED = dict(_DARK, **{
    "Window": "#000000", "Base": "#000000", "AlternateBase": "#0e0e0e", "ToolTipBase": "#0a0a0a",
    "Button": "#161616", "Light": "#333333", "Midlight": "#242424", "Mid": "#161616", "Dark": "#0a0a0a",
    "Shadow": "#000000", "Highlight": "#1e3a5f", "Text": "#f2f2f2", "WindowText": "#f2f2f2", "ButtonText": "#f2f2f2",
})
_AMOLED_DISABLED = dict(_DARK_DISABLED, **{"WindowText": "#666666", "Text": "#666666", "ButtonText": "#666666",
                                           "Base": "#0e0e0e", "Highlight": "#222222"})
_MEDIUM_LIGHT = dict(_LIGHT, **{"Window": "#d6dadd", "Button": "#e4e7ea", "AlternateBase": "#eaedf1", "Midlight": "#c5cace"})
_MEDIUM = dict(_LIGHT, **{"Window": "#b3b5b4", "Button": "#c7c8c7", "AlternateBase": "#bdbfbe", "Midlight": "#a4a6a5",
                         "Mid": "#8a8c8b", "Dark": "#8a8c8b"})
_PALETTES = {"Light": (_LIGHT, _LIGHT_DISABLED), "Medium Light": (_MEDIUM_LIGHT, _LIGHT_DISABLED), "Medium": (_MEDIUM, _LIGHT_DISABLED),
             "Dark": (_DARK, _DARK_DISABLED), "AMOLED": (_AMOLED, _AMOLED_DISABLED)}
_saved_palette = None
_scheme_forced = False


def theme_palette(name=None):
    colours, disabled = _PALETTES[name or current_theme()]
    palette = QtGui.QPalette()
    roles = QtGui.QPalette.ColorRole
    groups = QtGui.QPalette.ColorGroup
    for role_name, value in colours.items():
        role = getattr(roles, role_name, None)
        if role is None:
            continue
        for group in (groups.Active, groups.Inactive, groups.Disabled):
            palette.setColor(group, role, QtGui.QColor(value))
    for role_name, value in disabled.items():
        palette.setColor(groups.Disabled, getattr(roles, role_name), QtGui.QColor(value))
    return palette


def light_palette():
    return theme_palette("Light")


def apply_palette():
    """The theme's colours for the whole application while the style is on."""
    global _saved_palette, _scheme_forced
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    if _saved_palette is None:
        _saved_palette = QtGui.QPalette(app.palette())
    hints = QtGui.QGuiApplication.styleHints()
    scheme = getattr(QtCore.Qt, "ColorScheme", None)
    wanted = scheme.Dark if (scheme is not None and dark()) else (scheme.Light if scheme is not None else None)
    if wanted is not None and hasattr(hints, "setColorScheme") and hints.colorScheme() != wanted:
        # Qt 6.8: tells the Windows style itself which controls to draw.
        hints.setColorScheme(wanted)
        _scheme_forced = True
    palette = theme_palette()
    app.setPalette(palette)
    QtWidgets.QToolTip.setPalette(palette)
    _watch_links(app)
    QtCore.QTimer.singleShot(800, _fix_links)        # after FreeCAD's own palette for the new style sheet


class _LinkWatch(QtCore.QObject):
    """FreeCAD hands the application a palette of its own after a theme switch with only the link
    colour left at Qt's #0000ff: pure blue on the dark panes ("Open Appearance Library", vd111 11-20).
    The theme's link colours go back whenever the application palette changes and they differ."""

    def eventFilter(self, obj, event):
        try:
            if event.type() == QtCore.QEvent.ApplicationPaletteChange and obj is QtWidgets.QApplication.instance() \
                    and _saved_palette is not None:
                QtCore.QTimer.singleShot(0, _fix_links)
        except Exception as _fw_err:
            _fw_log("style.py:linkwatch", _fw_err)
        return False


_link_watch = []


def _watch_links(app):
    if not _link_watch:
        _link_watch.append(_LinkWatch(app))
        app.installEventFilter(_link_watch[0])


def _fix_links():
    """The theme's Link and LinkVisited back on the application palette, when something reset them."""
    app = QtWidgets.QApplication.instance()
    if app is None or _saved_palette is None:
        return False
    want = theme_palette()
    palette = QtGui.QPalette(app.palette())
    roles = QtGui.QPalette.ColorRole
    groups = QtGui.QPalette.ColorGroup
    links = [(group, role, want.color(group, role)) for role in (roles.Link, roles.LinkVisited)
             for group in (groups.Active, groups.Inactive, groups.Disabled)]

    qt_default = {roles.Link: QtGui.QColor("#0000ff"), roles.LinkVisited: QtGui.QColor("#ff00ff")}

    def off(pal):
        # only Qt's own default colours count: a pane given a palette of its own on purpose (a light
        # PropertyManager in Dark) keeps its links
        return any(pal.color(group, role) == qt_default[role] != colour for group, role, colour in links)

    def put(pal):
        for group, role, colour in links:
            if pal.color(group, role) == qt_default[role]:
                pal.setColor(group, role, colour)
        return pal

    changed = off(palette)
    if changed:
        app.setPalette(put(palette))
    # widgets under the main window's style sheet keep the palette they were polished with: those polished
    # while the link colour was reset keep it until polished again (about 20 ms for the whole window)
    fixed = 0
    for widget in QtWidgets.QApplication.allWidgets():
        try:
            if not off(widget.palette()):
                continue
            if widget.testAttribute(QtCore.Qt.WA_SetPalette):
                widget.setPalette(put(QtGui.QPalette(widget.palette())))
            else:
                widget.style().unpolish(widget)
                widget.style().polish(widget)
            fixed += 1
        except Exception as _fw_err:
            _fw_log("style.py:linkpolish", _fw_err)
    return changed or bool(fixed)


def restore_palette():
    global _saved_palette, _scheme_forced
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    if _scheme_forced:
        hints = QtGui.QGuiApplication.styleHints()
        if hasattr(hints, "unsetColorScheme"):
            hints.unsetColorScheme()
        else:
            hints.setColorScheme(QtCore.Qt.ColorScheme.Unknown)
        _scheme_forced = False
    if _saved_palette is not None:
        app.setPalette(_saved_palette)
        QtWidgets.QToolTip.setPalette(_saved_palette)
        _saved_palette = None


# The Apply Scene choices. The first three and the two dark ones keep their places (the setting is

# 9dc0e21e: 3 Point Faded (Default), Plain White, Backdrop - Grey with Overhead Light, Soft
# Spotlight, Rooftop, Courtyard Background, Urban 5 Background). FreeCAD draws backgrounds as
# gradients only, so the photo scenes are their sky-to-ground colours.
SCENES = (
    ("3 Point Faded", (0xEBEDF3FF, 0xDADEE9FF, 0xFEFEFEFF), True),
    ("Plain White", (0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF), False),
    ("Backdrop - Grey with Overhead Light", (0xF4F4F4FF, 0xDCDCDCFF, 0xC4C4C4FF), True),
    ("Studio Dark", (0x4A4E57FF, 0x2F3238FF, 0x6B7080FF), True),
    ("Black", (0x000000FF, 0x000000FF, 0x000000FF), False),
    ("Soft Spotlight", (0x8A8A8AFF, 0x8A8A8AFF, 0x262626FF), True),
    ("Rooftop", (0x8FB3D9FF, 0xD3DDE7FF, 0xE6E2DAFF), True),
    ("Courtyard Background", (0xA9C4DDFF, 0xDCE1E4FF, 0xB8AF9CFF), True),
    ("Urban 5 Background", (0x9AA6B2FF, 0xC9CCCFFF, 0x8C8A86FF), True),

    # because the picked scene is kept by its number)
    ("Retail Store", (0xF4F1ECFF, 0xE6E0D7FF, 0xCFC6BAFF), True),
    ("Villa Interior", (0xEDE5D8FF, 0xDACDB7FF, 0xB8A688FF), True),
    ("Warehouse", (0xC3C7CCFF, 0xA5AAB0FF, 0x80848AFF), True),
    ("Factory Background", (0xAEB4BAFF, 0x8E949AFF, 0x5F6368FF), True),
    ("Modern Garage", (0xDADDE1FF, 0xBABFC5FF, 0x6E7379FF), True),
    ("Fall Street", (0xC9D6E3FF, 0xE3D2B8FF, 0xA7774AFF), True),

    ("Urban 5 Image 6", (0x8E9BAAFF, 0xB9BEC2FF, 0x5E5B57FF), True),
    ("Backdrop - Black with Fill Lights", (0x3A3A3CFF, 0x1C1C1EFF, 0x0E0E0FFF), True),
    ("Reflective Floor Black", (0x000000FF, 0x050505FF, 0x1A1A1AFF), True),
    ("Landscape 2 Image 4", (0x9DB9D6FF, 0xDCE3E6FF, 0x7D8A5CFF), True),
)
RADIAL_SCENES = (5,)                 # drawn as a radial gradient: light in the middle, dark around

# Faded, Plain White, Backdrop - Grey with Overhead Light, Soft Spotlight, Rooftop, Courtyard Background,
# Urban 5 Background. (The E1 2024 video's list had 5 more: its author's own favourites.)
SCENE_MENU = (0, 1, 2, 5, 6, 7, 8)
SCENE_EXTRAS = (12, 15, 16, 17, 18, 9, 10, 11, 13, 14, 3, 4)  # the other scenes (Task Pane Scenes, Manage Favorites)


def apply_scene(index):
    """A viewport scene picked by hand (Apply Scene); -1 puts the theme's own back. The choice
    is kept until the next theme change. The scene's floor reflects the model or not, as the scene
    keeps it (Edit Scene's Floor reflections)."""
    out = set_theme(theme_name(), scene=int(index))
    if _pending_theme and _pending_theme == current_theme():
        # a sketch or feature is open: the window's restyle waits for it to close (set_theme), but the

        try:
            own = {(u[0], u[2]) for u in user_settings()}
            for path, kind, name, value in scene_settings():
                if (path, name) not in own:
                    getattr(App.ParamGet(path), _SET[kind])(name, value)
        except Exception as _fw_err:
            _fw_log("style.py:scene-in-edit", _fw_err)
    try:
        from . import scenepm
        scenepm.scene_changed(int(index))
    except Exception as _fw_err:
        _fw_log("style.py:scene_reflections", _fw_err)
    return out


def ui_scale():
    ""



    app = QtWidgets.QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return 1.0
    return max(1.0, round(screen.logicalDotsPerInch() / 96.0 * 4) / 4.0)


# Device-pixel lines: a 1 logical px separator is 2 device px at 200 %, so the
# half that faces the pane is painted in the pane colour.
QSS_TEMPLATE = """
QMainWindow::separator:horizontal {
    width: 1px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 ${pane}, stop:0.5 ${pane}, stop:0.5001 ${line}, stop:1 ${line});
}
QMainWindow::separator:vertical {
    height: 1px;
    background: ${line};
}
QToolBar#SWTopToolBar, QToolBar#SWBottomToolBar {
    border: none; margin: 0px; padding: 0px; spacing: 0px; background: transparent;
}
QDockWidget#SWLeftDock { border: none; }
QDockWidget#SWLeftDock > QWidget { background: ${pane}; }
#SWLeftStack, #SWLeftStack QDockWidget { background: ${pane}; border: none; }
#SWLeftStack QTreeView, #SWLeftStack QTreeWidget {
    background: ${pane}; alternate-background-color: ${pane}; border: none;
    selection-background-color: ${tree_selection}; selection-color: ${text};
    show-decoration-selected: 0;
    outline: 0;
}
#SWLeftStack QHeaderView::section { background: ${pane}; border: none; }
QLineEdit#SWTreeFilter { background: transparent; border: none; padding: 0px 2px; }
QStatusBar {
    background: ${pane}; color: ${text}; border: none;
    min-height: ${status_h}; max-height: ${status_h};
}
QStatusBar::item { border: none; }
QStatusBar QLabel { padding: 0px 6px; margin: 0px; background: transparent; }
QStatusBar QToolButton, QStatusBar QPushButton {
    padding: 0px 4px; margin: 0px; border: none; background: transparent; min-height: 0px;
}
QStatusBar QComboBox { padding: 0px 4px; margin: 0px; border: none; background: transparent; min-height: 0px; }
QTabBar#mdiAreaTabBar { max-height: 0px; }
QTabBar#mdiAreaTabBar::tab { height: 0px; min-height: 0px; max-height: 0px; padding: 0px; margin: 0px; border: none; font-size: 1px; }
QMenu#SWFlyout {
    background: ${menu}; border: 1px solid ${line_mid}; padding: 2px 0px;
}
QMenu#SWFlyout::item {
    padding: 2px 20px 2px 32px; min-height: 20px; color: ${text}; background: transparent;
}
QMenu#SWFlyout::item:selected { background: ${menu_hover}; }
QMenu#SWFlyout::item:disabled { color: ${text_disabled}; }
QMenu#SWFlyout::icon { padding-left: 4px; }
QMenu#SWFlyout::separator { height: 1px; background: ${tab}; margin: 3px 4px; }
QToolButton#SWMenuStripButton {
    border: none; padding: 3px 7px; background: transparent; color: ${text};
}
QToolButton#SWMenuStripButton:hover, QToolButton#SWMenuStripButton:pressed { background: ${hover}; }
QToolButton#SWMenuStripButton::menu-indicator { image: none; width: 0px; }
/* dialogs */
QDialog { background: ${pane}; color: ${text}; }
QDialog QLabel { color: ${text}; background: transparent; }
QDialog QCheckBox, QDialog QRadioButton { color: ${text}; }   /* look-audit dlgcheck-1120: no background here, it emptied the box and circle */
QDialog QLabel:disabled, QDialog QCheckBox:disabled, QDialog QRadioButton:disabled { color: ${text_disabled}; }
QDialog QGroupBox { border: 1px solid ${line_mid}; margin-top: 8px; padding-top: 6px; color: ${text}; }
QDialog QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0px 3px; color: ${text}; }
QDialog QTreeView, QDialog QTreeWidget, QDialog QListView, QDialog QListWidget, QDialog QTableView, QDialog QTableWidget,
QDialog QTextEdit, QDialog QPlainTextEdit {
    background: ${base}; alternate-background-color: ${base}; color: ${text}; border: 1px solid ${line_mid};
    selection-background-color: ${selection}; selection-color: ${text};
}
QDialog QHeaderView::section { background: ${tab}; color: ${text}; border: none; border-right: 1px solid ${line_mid}; padding: 2px 4px; }
QDialog QTabWidget::pane { border: 1px solid ${line_mid}; background: ${pane}; }
QDialog QTabBar::tab { background: ${tab}; color: ${text}; padding: 4px 10px; border: 1px solid ${line_mid}; }
QDialog QTabBar::tab:selected { background: ${pane}; }
QDialog QTabBar::tab:hover { background: ${tab_hover}; }
QDialog QLineEdit {
    background: ${base}; color: ${text}; border: 1px solid ${line_mid}; selection-background-color: ${selection}; selection-color: ${text};
}
QDialog QSpinBox, QDialog QDoubleSpinBox, QDialog QComboBox { background: ${base}; color: ${text}; }
QDialog QComboBox QAbstractItemView { background: ${base}; color: ${text}; selection-background-color: ${menu_hover}; }
QDialog QPushButton { background: ${tab}; color: ${text}; border: 1px solid ${line_mid}; padding: 3px 12px; }
QDialog QPushButton:hover { background: ${tab_hover}; }
QDialog QPushButton:disabled { color: ${text_disabled}; }
QDialog QScrollArea { background: ${pane}; border: none; }
"""


# Dark and AMOLED: Qt's Fusion draws a radio button as a disc in the pane's own dark grey with a grey
# dot, so in a dark pane neither the button nor which one is picked can be seen (the sketch tools'
# Orientation boxes: #3d3d3d on #494949). The PropertyManager's own ring look (propertymanager.py),
# for every radio button of the window.
DARK_QSS = """
QRadioButton::indicator {
    width: 13px; height: 13px;
    background: ${base};
    border: 1px solid ${arrow};
    border-radius: 7px;
}
QRadioButton::indicator:hover { border-color: #0078d7; }
QRadioButton::indicator:checked { background: ${base}; border: 4px solid #0078d7; width: 7px; height: 7px; }
QRadioButton::indicator:disabled { background: ${hover}; border-color: ${text_disabled}; }
"""

# Dialogs: "QDialog QCheckBox { background: transparent }" above hands the check box to Qt's style sheet
# drawing, which then draws no box round an unticked one (Pack and Go's "Include drawings" showed only its
# text, Light and Dark, File handling 11-20). The PropertyManager's own box (propertymanager.py) for every
# check box and radio button in a dialog.
DIALOG_QSS = """
QDialog QCheckBox::indicator {
    width: 13px; height: 13px;
    background: ${base};
    border: 1px solid ${arrow};
    border-radius: 2px;
}
QDialog QCheckBox::indicator:hover { border-color: #0078d7; }
QDialog QCheckBox::indicator:checked { background: #0078d7; border-color: #0078d7; image: url(@CHECK@); }
QDialog QCheckBox::indicator:indeterminate { background: ${base}; border-color: #0078d7; }
QDialog QCheckBox::indicator:disabled { background: ${hover}; border-color: ${text_disabled}; }
QDialog QCheckBox::indicator:checked:disabled { background: ${text_disabled}; border-color: ${text_disabled}; }
QDialog QRadioButton::indicator {
    width: 13px; height: 13px;
    background: ${base};
    border: 1px solid ${arrow};
    border-radius: 7px;
}
QDialog QRadioButton::indicator:hover { border-color: #0078d7; }
QDialog QRadioButton::indicator:checked { background: ${base}; border: 4px solid #0078d7; width: 7px; height: 7px; }
QDialog QRadioButton::indicator:disabled { background: ${hover}; border-color: ${text_disabled}; }
"""


# Simulation 11-20: a table in a task pane PropertyManager kept the left pane's dark header row (the
# "#SWLeftStack QHeaderView::section" rule is for the FeatureManager tree) over its white body in Dark.

# with black text, like the Light look; on AMOLED (black fields) the dark tab colour. Every QTableView (QTableWidget
# too): the PM sheet gives both the field colour (PM pkg376).
PM_TABLE_QSS = """
#SWLeftStack QTableView QHeaderView::section, Gui--TaskView--TaskView QTableView QHeaderView::section {
    background: ${field_head}; color: ${field_text}; border: none;
    border-right: 1px solid ${field_line}; border-bottom: 1px solid ${field_line}; padding: 2px 4px;
}
#SWLeftStack QTableView QTableCornerButton::section, Gui--TaskView--TaskView QTableView QTableCornerButton::section {
    background: ${field_head}; border: none; border-right: 1px solid ${field_line}; border-bottom: 1px solid ${field_line};
}
"""


def _pm_table_qss():
    field = QtGui.QColor(T.hex("field"))
    head = "#f0f0f0" if field.lightness() > 128 else T.hex("tab")
    return fill(PM_TABLE_QSS, field_head=head)


def _dialog_qss():
    try:
        from . import propertymanager
        check = propertymanager._images()["CHECK"]
    except Exception as _fw_err:
        _fw_log("style.py:dialog-check", _fw_err)
        check = ""
    return fill(DIALOG_QSS).replace("@CHECK@", check)


def qss():
    ""

    sheet = fill(QSS_TEMPLATE, status_h="%dpx" % int(round(22 * ui_scale())))
    try:
        if dark():
            sheet += fill(DARK_QSS)
    except Exception as _fw_err:
        _fw_log("style.py:dark-qss", _fw_err)
    try:
        sheet += _dialog_qss()
    except Exception as _fw_err:
        _fw_log("style.py:dialog-qss", _fw_err)
    try:
        sheet += _pm_table_qss()
    except Exception as _fw_err:
        _fw_log("style.py:pm-table-qss", _fw_err)
    try:
        from . import optionspages      # optioncolors-1119: Options > Colors > FeatureManager Design Tree Text
        ink = optionspages.kept_hex("FeatureManager Design Tree Text")
        if ink:
            sheet += "\n#SWLeftStack QTreeView, #SWLeftStack QTreeWidget { color: %s; }\n" % ink
    except Exception as _fw_err:
        _fw_log("style.py:tree-text", _fw_err)
    return sheet


# --------------------------------------------------------------------------- icons on dark panes

# arrows, outlines. On the Dark and AMOLED panes those parts vanish (Ati 23:12Z: "some buttons are

# pixels of an icon are turned light (lightness mirrored), coloured pixels stay as they are.
_INK_CACHE = {}
_INK_LIGHTNESS = 0.42      # neutral pixels darker than this are lifted
_INK_SATURATION = 0.30     # ... when they are this grey (blue handles etc. stay)


def _lifted(image):
    image = image.convertToFormat(QtGui.QImage.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if c.alpha() == 0:
                continue
            h, s, l, a = c.getHslF()
            if l < _INK_LIGHTNESS and s < _INK_SATURATION:
                image.setPixelColor(x, y, QtGui.QColor.fromHslF(max(h, 0.0), s, 0.90 - l * 0.9, a))
    return image


def readable_pixmap(icon, size, mode=QtGui.QIcon.Normal, state=QtGui.QIcon.Off, dpr=1.0):
    """The icon's pixmap for size logical px at the device pixel ratio dpr, its dark grey parts
    lifted on dark themes. Qt 6 scales QIcon.pixmap(QSize) by the application's ratio itself, so
    the ratio is passed to Qt and the pixmap keeps its own devicePixelRatio."""
    try:
        pixmap = icon.pixmap(QtCore.QSize(size, size), float(dpr), mode, state)
    except TypeError:
        pixmap = icon.pixmap(QtCore.QSize(size, size), mode, state)
    if not dark() or pixmap.isNull():
        return pixmap
    key = (pixmap.cacheKey(), size, round(float(dpr), 3), getattr(mode, "value", mode), getattr(state, "value", state), current_theme())
    done = _INK_CACHE.get(key)
    if done is None:
        if len(_INK_CACHE) > 2000:
            _INK_CACHE.clear()
        done = QtGui.QPixmap.fromImage(_lifted(pixmap.toImage()))
        done.setDevicePixelRatio(pixmap.devicePixelRatio())
        _INK_CACHE[key] = done
    return done


def paint_icon(painter, icon, rect, align=QtCore.Qt.AlignCenter, mode=QtGui.QIcon.Normal, state=QtGui.QIcon.Off):
    """QIcon.paint, but readable on dark panes: use it for every icon the addon paints itself.
    Never raises: an exception inside a paintEvent takes FreeCAD down."""
    try:
        _paint_icon(painter, icon, rect, align, mode, state)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: icon not lifted: %s\n" % error)
        try:
            icon.paint(painter, rect, align, mode, state)
        except Exception as _fw_err:
            _fw_log("style.py:1043", _fw_err)


def _paint_icon(painter, icon, rect, align, mode, state):
    if icon is None or icon.isNull():
        return
    if not dark():
        icon.paint(painter, rect, align, mode, state)
        return
    rect = QtCore.QRect(rect)
    side = min(rect.width(), rect.height())
    try:
        dpr = painter.device().devicePixelRatioF()
    except Exception:
        dpr = 1.0
    pixmap = readable_pixmap(icon, side, mode, state, dpr)
    if pixmap.isNull():
        return
    # the logical size of what Qt handed back, never larger than the rect (Ati 00:03Z: icons
    # drawn twice their size on the 200 % screen when the ratio was applied twice)
    ratio = pixmap.devicePixelRatio() or 1.0
    w, h = pixmap.width() / ratio, pixmap.height() / ratio
    fit = min(1.0, side / max(w, 1e-6), side / max(h, 1e-6))
    w, h = w * fit, h * fit
    target = QtCore.QRectF(rect.x() + (rect.width() - w) / 2.0, rect.y() + (rect.height() - h) / 2.0, w, h)
    painter.drawPixmap(target, pixmap, QtCore.QRectF(pixmap.rect()))
