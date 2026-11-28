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

import os

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

SCHEME = ("Colors", "Current color scheme", "Default")
SCENE = ("Colors", "Default scene", "00 3 point faded")
SHADED_EDGES = ("Fixed", "Use specified color for Shaded With Edges mode", True)
ICON_COLOR = ("Colors", "Icon color", "Default")
EDIT_MACRO = ("Fixed", "Automatically edit macro after recording", False)
STOP_DEBUG = ("General", "Stop VSTA debugger on macro exit", True)
ENGLISH = ("Fixed", "Use English language feature and file names", False)
MOUSE = ("View", "Mouse speed", "Fast")
BACKUP_HERE = ("Fixed", "Save backup files in the same location as the original", True)
INTERCONNECT = ("Import", "Enable 3D Interconnect", True)
SOLIDS = ("Import", "Solid and Surface", "Try forming solid(s)")
INDEXING = ("Search", "Indexing performance", "Index only when computer is idle")


HIGHLIGHTS = {"Default": 0xFF8000FF, "Orange Highlight": 0xFF8000FF, "Blue Highlight": 0x3399FFFF,
              "Green Highlight": 0x2DB84DFF}
SCENES = {"00 3 point faded": 0, "01 3 point white": 2, "02 Plain white": 1, "03 Studio room": 3}
MOUSE_SENSITIVITY = {"Slow": -30, "Medium": -10, "Fast": 0}
_state = {"applied": {}, "files": None, "files_at": 0.0, "idle_at": 0.0, "observer": None, "timer": None}


def _kept(row):
    from . import optionspages
    return optionspages.stored(row[0], row[1], row[2])


def _param(path):
    return App.ParamGet("User parameter:BaseApp/Preferences/" + path)


def _changed(row):
    """The row's value when it differs from the one last acted on (None otherwise)."""
    value = _kept(row)
    store = App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks/OptionsApplied")
    key = "%s__%s" % (row[0], row[1])
    key = "".join(c if c.isalnum() else "_" for c in key)[:120]
    last = store.GetString(key, "")
    if last == str(value):
        return None
    store.SetString(key, str(value))
    return value


STOCK_ICONS = "FreeCAD stock icons (next start)"      # stockicons-1127


def is_classic_icons():
    """Icon color = FreeCAD stock icons: startup leaves FreeCAD's own icons on its commands.
    v2audit-1127: the old "Classic" choice is gone; a saved Classic becomes Default (the V2 pack)."""
    try:
        value = str(_kept(ICON_COLOR))
        if value == "Classic":
            from . import optionspages
            optionspages.set_stored(ICON_COLOR[0], ICON_COLOR[1], "Default")
            App.Console.PrintLog("FreeCAD: Icon color Classic -> Default (V2)\n")
            return False
        return value == STOCK_ICONS
    except Exception:
        return False


def is_stock_icons():
    ""

    try:
        return str(_kept(ICON_COLOR)) == STOCK_ICONS
    except Exception:
        return False


# ---------------------------------------------------------------- colours
def _apply_colours(first=False):
    from . import style
    scheme = _changed(SCHEME)
    if scheme is not None and not first and scheme in HIGHLIGHTS:
        try:
            _param("View").SetUnsigned("HighlightColor", HIGHLIGHTS[scheme])
        except Exception as error:
            App.Console.PrintLog("FreeCAD: colour scheme: %s\n" % error)
    scene = _changed(SCENE)
    if scene is not None and not first and scene in SCENES:
        try:
            style.set_theme(style.theme_name(), scene=SCENES[scene])
        except Exception as error:
            App.Console.PrintLog("FreeCAD: default scene: %s\n" % error)
    if _changed(SHADED_EDGES) is not None and not first:
        for doc in App.listDocuments().values():
            edge_colours(doc)


def _darker(c):
    return tuple(max(0.0, v * 0.45) for v in c[:3])


def edge_colours(doc, objs=None):
    """Shaded With Edges: edges in the set colour, or (row off) in each part's own colour darkened."""
    if Gui is None:
        return
    specified = bool(_kept(SHADED_EDGES))
    u = _param("View").GetUnsigned("DefaultShapeLineColor", 421075455)
    line = ((u >> 24) & 255) / 255.0, ((u >> 16) & 255) / 255.0, ((u >> 8) & 255) / 255.0
    for obj in objs or doc.Objects:
        try:
            vo = obj.ViewObject
            if vo is None or not hasattr(vo, "LineColor") or not hasattr(vo, "ShapeAppearance"):
                continue
            want = line if specified else _darker(vo.ShapeAppearance[0].DiffuseColor)
            if tuple(round(v, 3) for v in vo.LineColor[:3]) != tuple(round(v, 3) for v in want):
                vo.LineColor = want
        except Exception as _fw_err:
            _fw_log("optionsextras4.py:130", _fw_err)


# ---------------------------------------------------------------- macros
def _newest_macro(since):
    folder = App.getUserMacroDir(True)
    best = None
    try:
        for name in os.listdir(folder):
            if not name.lower().endswith((".fcmacro", ".py")):
                continue
            path = os.path.join(folder, name)
            t = os.path.getmtime(path)
            if t >= since and (best is None or t > best[0]):
                best = (t, path)
    except Exception:
        return None
    return best[1] if best else None


def _after_record():
    import time
    if not _kept(EDIT_MACRO):
        return
    started = time.time() - 2         # only a macro written by this stop (not an older one)

    def edit():
        path = _newest_macro(started)
        if path:
            try:
                Gui.open(path)          # FreeCAD's macro editor
            except Exception as error:
                App.Console.PrintLog("FreeCAD: edit macro after recording: %s\n" % error)
    QtCore.QTimer.singleShot(400, edit)


def _after_run():
    if not _kept(STOP_DEBUG):
        return

    def stop():
        try:
            cmd = Gui.Command.get("Std_MacroStopDebug")
            if cmd is not None and cmd.isActive():
                Gui.runCommand("Std_MacroStopDebug", 0)
        except Exception as _fw_err:
            _fw_log("optionsextras4.py:176", _fw_err)
    QtCore.QTimer.singleShot(0, stop)


def _hook_actions():
    hooked = 0
    for name, call in (("Std_MacroStopRecord", _after_record), ("Std_DlgMacroRecord", _after_record),
                       ("Std_DlgMacroExecuteDirect", _after_run),
                       ("Std_DlgMacroExecute", _after_run)):
        try:
            cmd = Gui.Command.get(name)
            action = cmd.getAction()[0] if cmd is not None and cmd.getAction() else None
        except Exception:
            action = None
        if action is None or action.property("fw_opt4"):
            continue
        action.setProperty("fw_opt4", True)
        action.triggered.connect(lambda *a, c=call: c())
        hooked += 1
    return hooked


# ---------------------------------------------------------------- English names, edge colours of new parts
def _translated_ui():
    lang = _param("General").GetString("Language", "English")
    return bool(lang) and lang != "English"


class _DocObserver:
    def slotCreatedObject(self, obj):
        if _kept(ENGLISH) and _translated_ui():
            QtCore.QTimer.singleShot(0, lambda o=obj: _english(o))
        if not _kept(SHADED_EDGES):
            QtCore.QTimer.singleShot(0, lambda o=obj: _new_edges(o))

    def slotFinishSaveDocument(self, doc, path):
        if not _kept(BACKUP_HERE):
            QtCore.QTimer.singleShot(0, lambda p=path: move_backups(p))


def _english(obj):
    try:
        if obj.Label != obj.Name and not obj.Label.isascii():
            obj.Label = obj.Name        # its type's English name, numbered as FreeCAD numbers it
    except Exception as _fw_err:
        _fw_log("optionsextras4.py:221", _fw_err)


def _new_edges(obj):
    try:
        edge_colours(obj.Document, [obj])
    except Exception as _fw_err:
        _fw_log("optionsextras4.py:228", _fw_err)


# ---------------------------------------------------------------- backups
def backup_folder():
    """extapps82: Backup/Recover > Backup folder when one is picked, else the add-on's own Backups folder."""
    try:
        from . import optionspages
        picked = str(optionspages.stored("Backup/Recover", "Backup folder", "") or "")
        if picked and os.path.isdir(picked):
            return picked
    except Exception as error:
        App.Console.PrintLog("FreeCAD: backup folder: %s\n" % error)
    return _own_backup_folder()


def _own_backup_folder():
    folder = os.path.join(App.getUserAppDataDir(), "FreeWorks", "Backups")
    os.makedirs(folder, exist_ok=True)
    return folder


def move_backups(path):
    """Row off: the backups FreeCAD left beside the file go to the Backups folder."""
    import shutil
    import time
    folder, name = os.path.split(path)
    stem = os.path.splitext(name)[0]
    try:
        for other in os.listdir(folder or "."):
            full = os.path.join(folder, other)
            low = other.lower()
            if not other.startswith(stem) or other == name:
                continue
            if not (low.endswith(".fcbak") or low[len(stem):].lstrip(".").startswith("fcstd")):
                continue
            if time.time() - os.path.getmtime(full) > 120:
                continue
            target = _free_name(os.path.join(backup_folder(), other))
            shutil.move(full, target)
        _keep_newest(os.path.join(backup_folder(), name))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: backup folder: %s\n" % error)


def _free_name(target):
    """fh230: two saves in one second give FreeCAD's backups the same name, as do same-named files from two folders:
    the one already in the Backup folder is kept and this one is numbered, as FreeCAD numbers them beside the file."""
    if not os.path.exists(target):
        return target
    import re
    stem, ext = os.path.splitext(target)
    m = re.match(r"(\.fcstd)(\d+)$", ext, re.I)
    if m:                       # name.FCStd1: the next free number (the newest is found by its date, not its number)
        n = int(m.group(2)) + 1
        while os.path.exists("%s%s%d" % (stem, m.group(1), n)):
            n += 1
        return "%s%s%d" % (stem, m.group(1), n)
    n = 1
    while os.path.exists("%s-%d%s" % (stem, n, ext)):
        n += 1
    return "%s-%d%s" % (stem, n, ext)


def _keep_newest(path):
    """fh230: Number of backup copies per document holds in the Backup folder too (FreeCAD only counts beside the file)."""
    try:
        from . import optionsextras2
        count = max(1, App.ParamGet("User parameter:BaseApp/Preferences/Document").GetInt("CountBackupFiles", 1))
        found = sorted(optionsextras2.backups_of(path), key=os.path.getmtime, reverse=True)
        for old in found[count:]:
            os.remove(old)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: backup copies: %s\n" % error)


# ---------------------------------------------------------------- import
def apply_import():
    _param("Mod/Import").SetBool("UseLinkGroup", bool(_kept(INTERCONNECT)))


def knit_imported(objs):
    """Solid and Surface: sheets from an import knit into one shell, then a solid where it closes."""
    import Part
    mode = str(_kept(SOLIDS))
    if mode == "Do not knit":
        return 0
    done = 0
    for obj in objs:
        try:
            shape = obj.Shape
            if shape.isNull() or shape.Solids or not shape.Faces:
                continue
            sewn = shape.copy()
            sewn.sewShape()
            if mode.startswith("Try"):
                shells = sewn.Shells
                solids = []
                for sh in shells:
                    if sh.isClosed():
                        solids.append(Part.makeSolid(sh))
                if solids:
                    sewn = solids[0] if len(solids) == 1 else Part.makeCompound(solids)
            obj.Shape = sewn
            done += 1
        except Exception as _fw_err:
            _fw_log("optionsextras4.py:292", _fw_err)
    return done


def _wrap_import():
    import importlib
    for mod_name in ("ImportGui", "Import"):
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        for fn in ("open", "insert"):
            old = getattr(mod, fn, None)
            if old is None or getattr(old, "_fw_opt4", False):
                continue

            def wrapped(*args, _old=old, **kw):
                apply_import()
                before = {d: set(o.Name for o in doc.Objects) for d, doc in App.listDocuments().items()}
                result = _old(*args, **kw)
                try:
                    new = []
                    for d, doc in App.listDocuments().items():
                        known = before.get(d, set())
                        new += [o for o in doc.Objects if o.Name not in known and o.TypeId == "Part::Feature"]
                    if knit_imported(new):
                        for doc in {o.Document for o in new}:
                            doc.recompute()
                except Exception as error:
                    App.Console.PrintLog("FreeCAD: import knit: %s\n" % error)
                return result
            wrapped._fw_opt4 = True
            try:
                setattr(mod, fn, wrapped)
            except Exception as _fw_err:
                _fw_log("optionsextras4.py:327", _fw_err)


# ---------------------------------------------------------------- search index, mouse speed
def _apply_mouse():
    v = _changed(MOUSE)
    if v in MOUSE_SENSITIVITY:
        _param("Spaceball/Motion").SetInt("GlobalSensitivity", MOUSE_SENSITIVITY[v])


def file_list():
    """The search box's file list when it is kept ready (None: build it now)."""
    import time
    if _state["files"] is not None and time.time() - _state["files_at"] < 300:
        return list(_state["files"])
    return None


def _index_now():
    import time
    try:
        from . import swkeys
        old = getattr(swkeys.file_candidates, "_fw_old", swkeys.file_candidates)
        _state["files"] = old()
        _state["files_at"] = time.time()
    except Exception as _fw_err:
        _fw_log("optionsextras4.py:353", _fw_err)


def _tick():
    import time
    mode = str(_kept(INDEXING))
    now = time.time()
    if now - _state["files_at"] < 120:
        return
    if mode == "Always index":
        _index_now()
    elif now - _state["idle_at"] > 30:          # nothing typed or clicked for 30 s
        _index_now()


class _Idle(QtCore.QObject if Gui is not None else object):
    def eventFilter(self, obj, event):
        try:
            if event.type() in (QtCore.QEvent.KeyPress, QtCore.QEvent.MouseButtonPress):
                import time
                _state["idle_at"] = time.time()
        except Exception as _fw_err:
            _fw_log("optionsextras4.py:375", _fw_err)
        return False


def _wrap_search():
    try:
        from . import swkeys
        if getattr(swkeys.file_candidates, "_fw_opt4", False):
            return
        old = swkeys.file_candidates

        def file_candidates(_old=old):
            got = file_list()
            return got if got is not None else _old()
        file_candidates._fw_opt4 = True
        file_candidates._fw_old = old
        swkeys.file_candidates = file_candidates
    except Exception as _fw_err:
        _fw_log("optionsextras4.py:393", _fw_err)


# ---------------------------------------------------------------- entry points
def refresh():
    """After the Options box is saved."""
    _apply_colours()
    _apply_mouse()
    apply_import()


def install():
    if Gui is None or _state["observer"] is not None:
        return
    obs = _DocObserver()
    App.addDocumentObserver(obs)
    _state["observer"] = obs
    _apply_colours(first=True)          # remember the values as they are; act on later changes
    apply_import()
    _wrap_import()
    _wrap_search()
    idle = _Idle()
    try:
        from . import events           # the add-on's one application filter: only key and click events reach it
        events.install()
        events.register("optionsextras4-idle", (QtCore.QEvent.KeyPress, QtCore.QEvent.MouseButtonPress), idle.eventFilter)
    except Exception:
        QtWidgets.QApplication.instance().installEventFilter(idle)
    _state["idle"] = idle
    t = QtCore.QTimer()
    t.setInterval(15000)
    t.timeout.connect(_tick)
    t.start()
    _state["timer"] = t
    QtCore.QTimer.singleShot(3000, _hook_actions)
