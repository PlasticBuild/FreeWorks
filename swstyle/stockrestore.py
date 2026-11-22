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

import FreeCAD as App

ROOT = "User parameter:BaseApp/"
GROUPS = (
    "MainWindow/Toolbars",
    "Preferences/Mod/Sketcher",
    "Preferences/Themes/UserParameters",
    "Preferences/Gui/Gizmos",
    "Preferences/Mod/Part",
    "Preferences/Mod/PartDesign",
    "Preferences/Mod/Import",
    "Preferences/Mod/TechDraw",
    "Preferences/Mod/Assembly",
    "Preferences/Shortcut",
    "Preferences/Units",
    "Preferences/Workbenches",
)
TOOLBARS = "MainWindow/Toolbars"
# single settings outside GROUPS, put back one by one
KEYS = (
    ("Preferences/MainWindow", "QuickMeasureEnabled"),
    ("Preferences/MainWindow", "StatusBar"),
    ("Preferences/View", "SketchSelectionColor"),
    ("Preferences/View", "UseVBO"),
)

KNOWN = (
    ("Preferences/Gui/Gizmos", "EnableGizmos"),
    ("Preferences/MainWindow", "QuickMeasureEnabled"),
    ("Preferences/Mod/Sketcher", "LeaveSketchWithEscape"),
    ("Preferences/Mod/Sketcher", "ShowDimensionalName"),
    ("Preferences/Mod/Sketcher/General", "BSplineCombVisible"),
    ("Preferences/Mod/Sketcher/General", "BSplineControlPolygonVisible"),
    ("Preferences/Mod/Sketcher/General", "BSplineDegreeVisible"),
    ("Preferences/Mod/Sketcher/General", "BSplineKnotMultiplicityVisible"),
    ("Preferences/Mod/Sketcher/General", "BSplinePoleWeightVisible"),
    ("Preferences/Mod/Sketcher/General", "CenterRectangleDiagonals"),
    ("Preferences/Mod/Sketcher/General", "LineContextMenu"),
    ("Preferences/Mod/Sketcher/General", "PolygonInscribedCircle"),
    ("Preferences/Mod/Sketcher/General", "SelectNewRectangle"),
    ("Preferences/Mod/Sketcher/General", "SolidWorksGlyphs"),
    ("Preferences/Mod/Sketcher/Snap", "SnapRadiusReset1"),
    ("Preferences/Mod/Sketcher/View", "ConstructionPattern"),
    ("Preferences/Themes/UserParameters", "LinearGizmoActiveColor"),
    ("Preferences/Themes/UserParameters", "LinearGizmoBaseColor"),
    ("Preferences/Themes/UserParameters", "RotationGizmoActiveColor"),
    ("Preferences/Themes/UserParameters", "RotationGizmoBaseColor"),
    ("Preferences/Themes/UserParameters", "PreviewAdditiveColor"),
    ("Preferences/Themes/UserParameters", "PreviewLineWidth"),
    ("Preferences/Themes/UserParameters", "PreviewShapeOpacity"),
    ("Preferences/View", "SketchSelectionColor"),
    ("Preferences/View", "UseVBO"),
    ("Preferences/Mod/Part", "MeshAngularDeflection"),
    ("Preferences/Mod/Import", "UseLinkGroup"),
)
OWN = ("Preferences/Mod/FreeWorks", "Preferences/Mod/SolidWorksStyle", "Preferences/Mod/SWStyle")
OWN_SHORTCUT = ("SWStyle_", "FreeWorks_", "SW_")
_SET = {"Boolean": "SetBool", "Integer": "SetInt", "Unsigned Long": "SetUnsigned",
        "String": "SetString", "Float": "SetFloat"}
_REM = {"Boolean": "RemBool", "Integer": "RemInt", "Unsigned Long": "RemUnsigned",
        "String": "RemString", "Float": "RemFloat"}


def baseline_path():
    return os.path.join(App.getUserAppDataDir(), "FreeWorks", "stock-baseline.json")


def _grp(path):
    return App.ParamGet(ROOT + path)


def _contents(path):
    try:
        return [list(x) for x in (_grp(path).GetContents() or [])]
    except Exception:
        return []


def _subgroups(path):
    try:
        return list(_grp(path).GetGroups())
    except Exception:
        return []


def _tree(path):
    """{group path: [[kind, name, value], ...]} for path and its sub-groups."""
    out = {path: _contents(path)}
    for sub in _subgroups(path):
        out.update(_tree(path + "/" + sub))
    return out


def _has_own_settings():
    root = App.ParamGet(ROOT + "Preferences/Mod")
    try:
        names = set(root.GetGroups())
    except Exception:
        return False
    # a group is made empty as soon as some code asks for it: only one with settings counts
    return any(p.rsplit("/", 1)[1] in names and (_contents(p) or _subgroups(p)) for p in OWN)


def load():
    try:
        with open(baseline_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def snapshot():
    ""
    if load() is not None:
        return False
    data = {"clean": not _has_own_settings(), "groups": {}, "keys": {}}
    for path in GROUPS:
        data["groups"].update(_tree(path))
    for path, name in KEYS:
        data["keys"]["%s:%s" % (path, name)] = [x for x in _contents(path) if x[1] == name]
    if not data["clean"]:

        # start, still has FreeCAD's toolbars as they were
        try:
            from . import paths
            backup = json.loads(paths.params().GetString("Backup", "") or "{}")
            items = backup.get("groups", {}).get(ROOT + TOOLBARS)
            if items:
                data["groups"][TOOLBARS] = [list(x) for x in items]
                data["toolbars_clean"] = True
        except Exception as _fw_err:
            _fw_log("stockrestore.py:167", _fw_err)
    try:
        os.makedirs(os.path.dirname(baseline_path()), exist_ok=True)
        with open(baseline_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=0)
    except OSError as error:
        App.Console.PrintWarning("FreeCAD: stock settings baseline not saved: %s\n" % error)
        return False
    return True


def _put(path, items):
    """Group path holds exactly items afterwards (sub-groups are not touched)."""
    grp = _grp(path)
    want = {(k, n): v for k, n, v in items}
    for k, n, v in _contents(path):
        if (k, n) not in want and k in _REM:
            try:
                getattr(grp, _REM[k])(n)
            except Exception as _fw_err:
                _fw_log("stockrestore.py:187", _fw_err)
    for (k, n), v in want.items():
        if k in _SET and [k, n, v] not in _contents(path):
            try:
                getattr(grp, _SET[k])(n, v)
            except Exception as _fw_err:
                _fw_log("stockrestore.py:193", _fw_err)


def _remove(path, name):
    grp = _grp(path)
    for k, n, _v in _contents(path):
        if n == name and k in _REM:
            try:
                getattr(grp, _REM[k])(n)
            except Exception as _fw_err:
                _fw_log("stockrestore.py:203", _fw_err)


def restore_toolbars(data=None):
    """FreeCAD's toolbar settings as in the baseline (all showing when the baseline is not clean)."""
    data = data if data is not None else load()
    if data is None:
        return False
    if data.get("clean") or data.get("toolbars_clean"):
        base = data["groups"].get(TOOLBARS, [])
        _put(TOOLBARS, base)
        named = {n for _k, n, _v in base}
        for n in STOCK_HIDDEN:      # extapps158: an emptied group made FreeCAD show these three; a fresh FreeCAD profile hides them
            if n not in named:
                _grp(TOOLBARS).SetBool(n, False)
    else:
        # set, not removed: FreeCAD's saved window state would keep a toolbar with no setting hidden
        grp = _grp(TOOLBARS)
        for k, n, v in _contents(TOOLBARS):
            if k == "Boolean" and not n.startswith("SW"):
                want = n not in STOCK_HIDDEN
                if bool(v) != want:
                    grp.SetBool(n, want)
    return True


def restore(data=None):
    """Every group in GROUPS and the KEYS back as in the baseline."""
    data = data if data is not None else load()
    if data is None:
        return False
    if data.get("clean"):
        for path in GROUPS:
            saved = {p: items for p, items in data["groups"].items() if p == path or p.startswith(path + "/")}
            for p in _tree(path):
                _put(p, saved.get(p, []))
        for key, items in data.get("keys", {}).items():
            path, name = key.split(":", 1)
            _remove(path, name)
            if items:
                _put_one(path, items[0])
    else:
        for path, name in KNOWN:
            _remove(path, name)
        restore_toolbars(data)
    grp = _grp("Preferences/Shortcut")
    for k, n, _v in _contents("Preferences/Shortcut"):
        if n.startswith(OWN_SHORTCUT) and k in _REM:
            getattr(grp, _REM[k])(n)
    pri = _grp("Preferences/Shortcut/Priorities")
    for k, n, _v in _contents("Preferences/Shortcut/Priorities"):
        if n.startswith(OWN_SHORTCUT) and k in _REM:
            getattr(pri, _REM[k])(n)
    return True


def _put_one(path, item):
    k, n, v = item
    if k in _SET:
        getattr(_grp(path), _SET[k])(n, v)


def remove_own_settings():
    mod = App.ParamGet(ROOT + "Preferences/Mod")
    for path in OWN:
        try:
            mod.RemGroup(path.rsplit("/", 1)[1])
        except Exception as _fw_err:
            _fw_log("stockrestore.py:266", _fw_err)

    for path, name in OWN_KEYS:
        _remove(path, name)



OWN_KEYS = (("Preferences/View", "FreeWorksSelectionColorOutsideSketch"),
            ("Preferences/View", "FreeWorksSelectionColorOutsideSketchSet"))

# decals, textures and the baseline stay). (folder: "data" or "cache", path inside it, glob pattern or None)
OWN_FILES = (("data", "FreeWorks-commands.log", None), ("data", "FreeWorks-toolbars.log", None),
             ("data", "SolidWorksStyle/slicer", "*-presets.pickle"),
             ("cache", "SWStyleTips", "*.png"), ("cache", ".", "FreeWorks-pack-*.json"),
             ("cache", "swstyle-warning.png", None), ("cache", "FreeWorksDarkIcons", "**/*.png"),
            ("cache", "FreeCAD-icons-ahead", "*.svg"))     # cleaninstall2-1120: drawings._ahead stand-ins


def uninstalled():
    ""
    return bool(_uninstalled[0])


def remove_own_files():
    ""
    import glob
    roots = {"data": App.getUserAppDataDir()}
    try:
        roots["cache"] = App.getUserCachePath()
    except Exception:
        roots["cache"] = None
    gone = 0
    for where, rel, pattern in OWN_FILES:
        root = roots.get(where)
        if not root:
            continue
        path = os.path.normpath(os.path.join(root, rel))
        files = [path] if pattern is None else glob.glob(os.path.join(path, pattern), recursive=True)
        for f in files:
            try:
                if os.path.isfile(f):
                    os.remove(f)
                    gone += 1
            except OSError as _fw_err:
                _fw_log("stockrestore.py:files", _fw_err)
        if pattern is not None and rel != ".":
            for folder in sorted({os.path.dirname(f) for f in files} | {path}, key=len, reverse=True):
                try:
                    os.rmdir(folder)            # only when empty
                except OSError:
                    pass
    for folder in (os.path.join(roots["data"], "SolidWorksStyle"),):
        try:
            os.rmdir(folder)
        except OSError:
            pass
    return gone


_uninstalled = [False]


STOCK_HIDDEN = ("Clipboard", "Macro", "Individual Views")     # hidden on a new FreeCAD 1.1 profile


def _wanted_toolbars(data):
    """{toolbar name: showing} as FreeCAD should save them at close."""
    if data.get("clean") or data.get("toolbars_clean"):
        wanted = {n: bool(v) for k, n, v in data["groups"].get(TOOLBARS, []) if k == "Boolean"}
        for n in STOCK_HIDDEN:      # extapps158: a fresh profile's baseline names none of them: FreeCAD hides these three until they are asked for
            wanted.setdefault(n, False)
        return wanted, True
    return {n: False for n in STOCK_HIDDEN}, True      # not clean: FreeCAD's defaults


def _show_stock_toolbars(data):
    """FreeCAD saves its toolbars' states from the window after this hook, so the window's own
    toolbars are put as the baseline has them (the window is closed already: nothing flashes)."""
    try:
        import FreeCADGui as Gui
        from PySide import QtWidgets
        mw = Gui.getMainWindow()
        wanted, default = _wanted_toolbars(data)
        for tb in mw.findChildren(QtWidgets.QToolBar):
            try:
                if tb.metaObject().className() != "Gui::ToolBar" or tb.parentWidget() is not mw:
                    continue
                name = tb.objectName()
                if not name or name.startswith("SW"):
                    continue
                if not (data.get("clean") or data.get("toolbars_clean")) and name not in wanted:
                    pass
                elif name not in wanted and not tb.toggleViewAction().isVisible():
                    continue
                tb.setHidden(not wanted.get(name, default))
            except RuntimeError:
                continue
    except Exception as error:
        App.Console.PrintLog("FreeCAD: toolbars at close: %s\n" % error)


def _at_quit():
    App.Console.PrintLog("FreeCAD: stock settings at close\n")
    try:
        data = load()
        if data is None:
            return
        _show_stock_toolbars(data)
        try:
            # the look's own settings (theme colours, Quick Measure, status bar...) go back too:
            # the look writes them again at the next start, after a fresh backup
            from . import style
            style.restore_settings()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: look settings at close: %s\n" % error)
        if _uninstalled[0]:
            restore(data)
            remove_own_settings()
            remove_own_files()          # cleaninstall-1120
        else:
            restore_toolbars(data)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: stock settings at close: %s\n" % error)


_installed = [False]


def install():
    """At start-up, first thing: the baseline, and the toolbars put back at every close."""
    try:
        snapshot()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: stock settings baseline: %s\n" % error)
    if _installed[0]:
        return
    try:
        from PySide import QtWidgets
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(_at_quit)
            _installed[0] = True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: close hook: %s\n" % error)


def _main_thread():
    try:
        from PySide import QtCore, QtWidgets
        app = QtWidgets.QApplication.instance()
        return app is not None and QtCore.QThread.currentThread() == app.thread()
    except Exception:
        return False


def uninstall():
    ""


    _uninstalled[0] = True              # the close hook finishes the job after FreeCAD saved its toolbars
    if _main_thread():
        try:
            from . import shell
            shell.set_enabled(False)    # FreeCAD's own window back now (toolbars, menus, style)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: interface not switched off: %s\n" % error)
    restore()
    try:
        remove_own_settings()           # cleaninstall-1120: again at close, after the add-on's last writes
        remove_own_files()
    except Exception as _fw_err:
        _fw_log("stockrestore.py:uninstall", _fw_err)
    App.Console.PrintMessage("FreeCAD removed: FreeCAD's settings go back as they were before FreeCAD. "
                             "Restart FreeCAD to finish.\n")
    return True
