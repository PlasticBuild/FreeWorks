# SPDX-License-Identifier: LGPL-2.1-or-later
""
from PySide import QtCore, QtGui

from . import paths

_ROOT = paths.icon_root()
_cache = {}


def available():
    return _ROOT is not None


def root():
    return _ROOT


def pixmap_path(name, fallback=""):
    """The bundled file for a command Pixmap, or its stock fallback. In a dark theme, a copy
    made light for the dark panes (in FreeCAD's cache folder; remade when the pack's file changes).
    hidpi-1119: the largest file up to 64 px, never the 20 px one when a bigger one exists. FreeCAD
    never enlarges a Pixmap file, so a 20 px file drew at 20 screen px in a 28 px slot at 175 %."""
    path = None
    if name and _ROOT is not None:
        for size in (64, 40, 32, 24, 20, 16):
            cand = _ROOT / "png" / name / ("%d.png" % size)
            if cand.is_file():
                path = cand
                break
    if path is None or not path.is_file():
        return fallback
    if _dark():
        own = dark_folder(name)            # darkpack-1127: the authored dark artwork, as it is
        if own is not None:
            for size in (64, 40, 32, 24, 20, 16):
                cand = own / ("%d.png" % size)
                if cand.is_file():
                    return str(cand)
        try:
            import FreeCAD as App
            import os
            folder = os.path.join(App.getUserCachePath(), "FreeWorksDarkIcons", name)
            out = os.path.join(folder, path.name)
            if not os.path.isfile(out) or os.path.getmtime(out) < os.path.getmtime(str(path)):
                os.makedirs(folder, exist_ok=True)
                img = adapt_for_dark(QtGui.QImage(str(path)))
                if not img.save(out):
                    return str(path)
            return out
        except Exception:
            return str(path)
    return str(path)


def family(name, large=False):
    ""



    if name and name.lower().endswith((".svg", ".png")):
        icon = _cache.get(name)
        if icon is None:
            icon = _cache[name] = QtGui.QIcon(name)
        return icon
    if not name:
        return QtGui.QIcon()
    if _ROOT is None:
        # drawnfb-1127 (Menus): no icon pack (a public install has none): the drawn set straight away. Before, this
        # returned an empty icon, so the drawn <FAMILY>.svg pictures were only ever reached with a pack installed,
        # and 26 CommandManager buttons, about 130 menu rows and every PM_/tab family painted nothing or initials.
        key = "nopack:" + name
        icon = _cache.get(key)
        if icon is None:
            icon = _cache[key] = _family_fallback(name)
        return icon
    dark = _dark()
    key = (name + ("|dark|large" if large else "|dark")) if dark else name
    icon = _cache.get(key)
    if icon is None:
        icon = QtGui.QIcon()
        folder = _ROOT / "png" / name
        own = dark_folder(name) if dark else None
        if own is not None:
            # darkpack-1127: the pack's own dark artwork (icons/dark/png/<family>) is used as drawn, every size;
            # before, Dark always lifted the Light files (adapt_for_dark), so the authored dark pictures (the
            # dark-housing Rebuild traffic light) were never shown
            for item in own.glob("*.png"):
                try:
                    size = int(item.stem)
                except ValueError:
                    continue
                icon.addFile(str(item), QtCore.QSize(size, size))
            if not icon.isNull():
                _authored.add(icon.cacheKey())
                _cache[key] = icon
                return icon
        if folder.is_dir():
            files = []
            for item in folder.glob("*.png"):
                try:
                    files.append((int(item.stem), item))
                except ValueError:
                    continue
            for size, item in sorted(files):
                if dark and (large or size <= DARK_MAX_PX):
                    pix = dark_pixmap(str(item))
                    if pix is not None:
                        icon.addPixmap(pix)
                        continue
                if not dark or large or size <= DARK_MAX_PX:
                    icon.addFile(str(item), QtCore.QSize(size, size))
        if icon.isNull():
            icon = _family_fallback(name)
        _cache[key] = icon
    return icon



# drawn set (resources/icons-drawn/<FAMILY>.svg, or the FW_<key> drawing of that command), so a PropertyManager
# header or button asking for it is never empty
PACK_ALIAS = {"REFGEO_MATE_REFERENCE": "REFGEO_MATE_REF", "CURVES_THROUGH_XYZ_POINTS": "FW_CurveThroughXYZPoints",
              "TABLES_BOM": "ASSEMBLIES_BOM", "SURFACES_EXTEND_SURFACE": "FW_ExtendSurface",
              "SURFACES_FILLED_SURFACE": "FW_FilledSurface", "SURFACES_FLATTEN": "FW_SurfaceFlatten",
              "FEATURES_REPLACE_FACE": "FW_ReplaceFace",
              "SKETCH_MIDPOINT_LINE": "SKETCH_MIDPT_LINE"}      # icons-exact-1122b: the pack names this picture MIDPT
DRAWN_ALIAS = {"SURFACES_CHAMFER": "FW_SurfaceChamfer", "SURFACES_EXTEND_SURFACE": "FW_ExtendSurface",
               "SURFACES_FILLED_SURFACE": "FW_FilledSurface", "SURFACES_FLATTEN": "FW_SurfaceFlatten",
               "FEATURES_REPLACE_FACE": "FW_ReplaceFace"}


def _family_fallback(name):
    other = PACK_ALIAS.get(name)
    if other and other != name:
        icon = family(other)
        if not icon.isNull():
            return icon
    path = _DRAWN / ("%s.svg" % DRAWN_ALIAS.get(name, name))
    return QtGui.QIcon(str(path)) if path.is_file() else QtGui.QIcon()


# ---------------------------------------------------------------- the dark themes

# pictures are drawn for a light pane: their near-black outlines and marks vanish on #494949. In a
# dark theme the dark, grey (unsaturated) pixels are turned light; coloured fills stay as they are.
DARK_MAX_PX = 64                  # larger sizes are not used on buttons; leaving them out keeps start-up quick
DARK_LUM = 110                    # pixels darker than this, and grey, are outlines and marks
DARK_SAT = 0.35
DARK_DEEP = 60                    # darker than this, whatever the colour: an outline too


def _dark():
    try:
        from . import style
        return style.dark()
    except Exception:
        return False


# darkpack-1127: the pack's authored dark set (icons/dark/png/<family>/<size>.png, icons/dark/fc/<FreeCAD name>)
_authored = set()


def dark_folder(name):
    """The family's folder in the pack's dark set, or None (then Dark lifts the Light files as before)."""
    if not name or _ROOT is None:
        return None
    folder = _ROOT / "dark" / "png" / name
    return folder if folder.is_dir() else None


def dark_fc_text():
    """The dark set's FreeCAD-name folder, or "" when the pack has none."""
    if _ROOT is None:
        return ""
    folder = _ROOT / "dark" / "fc"
    return folder.as_posix() if folder.is_dir() else ""


def authored(icon):
    """True for an icon family() took from the dark set: it is drawn for the dark panes already, so
    style.readable_pixmap must not lift it again (that turned the near-black housings light)."""
    try:
        return icon is not None and icon.cacheKey() in _authored
    except Exception:
        return False


def adapt_for_dark(image):
    """A copy of the QImage with its dark grey ink made light (alpha and colours kept)."""
    try:
        import numpy as np
    except Exception:
        return image
    img = image.convertToFormat(QtGui.QImage.Format_ARGB32)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    if w == 0 or h == 0:
        return img
    a = np.frombuffer(img.constBits(), np.uint8, count=img.sizeInBytes()).reshape(h, bpl // 4, 4)[:, :w, :].copy()
    b, g, r, alpha = (a[:, :, i].astype(np.int32) for i in range(4))
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    lum = (r * 30 + g * 59 + b * 11) // 100
    sat = (mx - mn) / np.maximum(mx, 1)
    ink = (alpha > 0) & (lum < DARK_LUM) & (sat < DARK_SAT)
    light = np.clip(235 - lum * 6 // 10, 0, 255)
    # very dark coloured outlines (navy, dark red) keep their hue, lifted three quarters to white
    deep = (alpha > 0) & (lum < DARK_DEEP) & ~ink
    for i, c in enumerate((b, g, r)):
        lifted = c + (255 - c) * 3 // 4
        a[:, :, i] = np.where(ink, light, np.where(deep, lifted, a[:, :, i]))
    out = QtGui.QImage(a.tobytes(), w, h, w * 4, QtGui.QImage.Format_ARGB32)
    return out.copy()


def dark_pixmap(path):
    try:
        img = QtGui.QImage(path)
        if img.isNull():
            return None
        return QtGui.QPixmap.fromImage(adapt_for_dark(img))
    except Exception:
        return None


_DRAWN = __import__("pathlib").Path(__file__).resolve().parent / "resources" / "icons-drawn"


def drawn(key):
    ""

    name = "drawn:" + str(key)
    icon = _cache.get(name)
    if icon is None:
        path = _DRAWN / ("FW_%s.svg" % key)
        icon = _cache[name] = QtGui.QIcon(str(path)) if path.is_file() else QtGui.QIcon()
    return icon


_painted = {}


def paints(icon):
    """True when the icon draws something (a QIcon from a missing file is not null but empty)."""
    if icon is None or icon.isNull():
        return False
    key = icon.cacheKey()
    if key not in _painted:
        if len(_painted) > 4000:
            _painted.clear()
        img = icon.pixmap(24, 24).toImage()
        _painted[key] = any(img.pixelColor(x, y).alpha() > 0
                            for y in range(0, img.height(), 2) for x in range(0, img.width(), 2))
    return _painted[key]


def initials(label):
    """Neutral stand-in picture: a rounded grey tile with up to two initials of the command's name."""
    words = [w for w in label.replace("/", " ").replace("-", " ").split() if w[:1].isalnum()]
    text = "".join(w[0] for w in words[:2]).upper() or "?"
    key = "initials:" + text
    icon = _cache.get(key)
    if icon is None:
        icon = QtGui.QIcon()
        for size in (16, 20, 24, 32, 40, 64):
            pix = QtGui.QPixmap(size, size)
            pix.fill(QtCore.Qt.transparent)
            p = QtGui.QPainter(pix)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            p.setPen(QtGui.QPen(QtGui.QColor("#5a6470"), max(1.0, size / 20.0)))
            p.setBrush(QtGui.QColor("#d9dee4"))
            r = QtCore.QRectF(0.5, 0.5, size - 1, size - 1).adjusted(size * .08, size * .08, -size * .08, -size * .08)
            p.drawRoundedRect(r, size * .15, size * .15)
            font = p.font()
            font.setBold(True)
            font.setPixelSize(max(6, int(size * (.42 if len(text) > 1 else .55))))
            p.setFont(font)
            p.setPen(QtGui.QColor("#2b3540"))
            p.drawText(r, QtCore.Qt.AlignCenter, text)
            p.end()
            icon.addPixmap(pix)
        _cache[key] = icon
    return icon


def has(name):
    return not family(name).isNull()


def command_icon(cmd, native_action=None):
    icon = family(cmd.icon) if cmd.icon else QtGui.QIcon()
    if icon.isNull() and native_action is not None:
        icon = native_action.icon()
    return icon


def install_freecad_overrides():
    """Put the private FreeCAD-name overrides first on the 'icons' search path.

    FreeCAD's BitmapFactory tries 'icons:<name>' (no extension) and then
    'icons:<name>.svg' before its built-in resources, so files in this folder
    replace command, tree and view icons by name. It must run before the icons
    are first loaded, i.e. from InitGui.
    """
    _schedule_command_icons()         # icons-exact-1122b; pkg172: also with no pack, so our drawn pictures reach the buttons
    if _ROOT is None:
        return False
    folder = _ROOT / "fc"
    if not folder.is_dir():
        return False
    text = folder.as_posix()
    first = [text]
    if _dark():
        dark = dark_names_folder()
        if dark:
            build_dark_names(pack_only=True)        # the pack's own names now, FreeCAD's in the background
            first = [dark, text]
            _later_dark_names()
        own = dark_fc_text()                # darkpack-1127: the authored dark FreeCAD names come first
        if own:
            first = [own] + first
    if not _dark_names.get("follows"):
        try:
            from . import style
            style.signals.theme_changed.connect(lambda *_a: None if _cmd_icons.get("classic") else install_freecad_overrides())
            # icons-refresh-1126: after the search path above, the pictures already on our command actions
            # (and their copies) are put on again in the new theme's ink (family() keys by theme)
            style.signals.theme_changed.connect(lambda *_a: QtCore.QTimer.singleShot(0, refresh_command_icons))
            _dark_names["follows"] = True
        except Exception:
            pass
    paths = list(QtCore.QDir.searchPaths("icons"))
    ours = {_dark_dir_text(), dark_fc_text()} - {""}
    if paths[:len(first)] == first and not ((ours - set(first)) & set(paths)):
        return True
    current = [item for item in paths if item not in first and item not in ours]
    QtCore.QDir.setSearchPaths("icons", first + current)
    return True


# ---------------------------------------------------------------- icons FreeCAD loads by name, in dark
# FreeCAD's BitmapFactory looks for "icons:<name>" before its built-in pictures, so a folder first on
# that search path replaces the tree, view and command icons FreeCAD itself loads. In a dark theme
# that folder holds light-ink copies (adapt_for_dark) of the pack's fc/ icons and of FreeCAD's own
# built-in icons (:/icons), as 64 px PNG files named like the icon. The pack's are made at start;
# FreeCAD's in small batches once the window is idle (and again after a workbench brings new ones).
DARK_NAMES_PX = 64
_dark_names = {"queue": None, "timer": None}


def _dark_dir_text():
    try:
        import FreeCAD as App
        import os
        return os.path.join(App.getUserCachePath(), "FreeWorksDarkIcons", "_names").replace("\\", "/")
    except Exception:
        return ""


# look audit VC-1 (11-26): FreeCAD loads its 3D view cursors by name too (cursor-pan, cursor-zoom ...).
# A light copy of one is a PNG that FreeCAD's cursor loader reads as an empty picture, so in a dark
# theme the Ctrl/Shift + middle-drag pan and zoom cursors were invisible. Cursors keep FreeCAD's own
# drawing (a white arrow with a black rim reads on any background): no copies, old ones removed.
def _dark_skip(name):
    return name.lower().startswith("cursor-")


def _drop_dark_cursors(folder):
    import os
    if _dark_names.get("cursors_dropped") == folder:
        return
    _dark_names["cursors_dropped"] = folder
    try:
        for f in os.listdir(folder):
            if _dark_skip(f):
                os.remove(os.path.join(folder, f))
    except OSError:
        pass


def dark_names_folder():
    import os
    text = _dark_dir_text()
    if not text:
        return ""
    try:
        os.makedirs(text, exist_ok=True)
    except OSError:
        return ""
    _drop_dark_cursors(text)
    return text


def _write_dark(name, image, folder):
    import os
    if image.isNull() or _dark_skip(name):
        return False
    out = os.path.join(folder, name)
    return adapt_for_dark(image).save(out, "PNG")


def _stamp(folder):
    """The FreeCAD version and the pack's newest fc/ file: when either changes the copies are remade."""
    import os
    try:
        import FreeCAD as App
        version = ".".join(App.Version()[:4])
    except Exception:
        version = "?"
    newest = 0
    pack = _ROOT / "fc" if _ROOT is not None else None
    if pack is not None and pack.is_dir():
        newest = max([int(f.stat().st_mtime) for f in pack.iterdir()] or [0])
    return "%s|%d" % (version, newest)


def build_dark_names(pack_only=False):
    """Writes the light copies; returns how many were written (the pack's names always, FreeCAD's
    built-in ones unless pack_only). Copies already there and current are kept."""
    import os
    folder = dark_names_folder()
    if not folder:
        return 0
    stamp_file = os.path.join(folder, ".stamp")
    stamp = _stamp(folder)
    try:
        old = open(stamp_file).read()
    except OSError:
        old = ""
    fresh = old != stamp
    written = 0
    pack = _ROOT / "fc" if _ROOT is not None else None
    if pack is not None and pack.is_dir():
        for f in sorted(pack.iterdir()):
            name = f.name[:-4] if f.name.lower().endswith((".svg", ".png")) else f.name
            if not name or name.startswith("."):
                continue
            if not fresh and os.path.isfile(os.path.join(folder, name)):
                continue
            image = QtGui.QIcon(str(f)).pixmap(DARK_NAMES_PX, DARK_NAMES_PX).toImage()
            written += bool(_write_dark(name, image, folder))
    if fresh:
        try:
            with open(stamp_file, "w") as fh:
                fh.write(stamp)
        except OSError:
            pass
        _dark_names["fresh"] = True
    if not pack_only:
        written += _queue_builtin(folder, run_all=True)
    return written


def _builtin_names():
    """(name, resource path) of FreeCAD's built-in icons, the top folder first (as the search path)."""
    seen = {}
    it = QtCore.QDirIterator(":/icons", QtCore.QDirIterator.Subdirectories)
    paths = []
    while it.hasNext():
        paths.append(it.next())
    paths.sort(key=lambda p: (p.count("/"), p))
    for p in paths:
        base = p.rsplit("/", 1)[-1]
        if not base.lower().endswith((".svg", ".png")):
            continue
        name = base[:-4]
        if name not in seen:
            seen[name] = p
    return list(seen.items())


def _queue_builtin(folder, run_all=False):
    """FreeCAD's built-in icons that have no light copy yet: all now (run_all) or 60 per idle tick."""
    import os
    pack = _ROOT / "fc" if _ROOT is not None else None
    have_pack = set()
    if pack is not None and pack.is_dir():
        have_pack = {f.name[:-4] if f.name.lower().endswith((".svg", ".png")) else f.name for f in pack.iterdir()}
    todo = [(n, p) for n, p in _builtin_names()
            if n not in have_pack and not _dark_skip(n) and not os.path.isfile(os.path.join(folder, n))]
    if run_all:
        n = 0
        for name, path in todo:
            n += bool(_write_dark(name, QtGui.QIcon(path).pixmap(DARK_NAMES_PX, DARK_NAMES_PX).toImage(), folder))
        return n
    _dark_names["queue"] = todo
    return len(todo)


def _tick():
    queue = _dark_names.get("queue") or []
    folder = dark_names_folder()
    for _ in range(60):
        if not queue:
            break
        name, path = queue.pop()
        try:
            _write_dark(name, QtGui.QIcon(path).pixmap(DARK_NAMES_PX, DARK_NAMES_PX).toImage(), folder)
        except Exception:
            continue
    if not queue and _dark_names.get("timer") is not None:
        _dark_names["timer"].stop()


def _later_dark_names():
    """FreeCAD's own icons, in batches once the window is up; again when a workbench is activated
    (its icons are registered then)."""
    def start(*_args):
        if not _dark():
            return
        folder = dark_names_folder()
        if not folder or not _queue_builtin(folder):
            return
        timer = _dark_names.get("timer")
        if timer is None:
            timer = _dark_names["timer"] = QtCore.QTimer()
            timer.setInterval(30)
            timer.timeout.connect(_tick)
        timer.start()
    QtCore.QTimer.singleShot(4000, start)
    try:
        import FreeCADGui as Gui
        mw = Gui.getMainWindow()
        if mw is not None and not _dark_names.get("hooked"):
            mw.workbenchActivated.connect(lambda *_a: QtCore.QTimer.singleShot(1500, start))
            _dark_names["hooked"] = True
    except Exception:
        pass



# (Insert Spline Point and other spline tools in drawsketchmore.py / sketch3d.py); once every command is there the picture
# the catalog gives (pack, else FW_<key>, else our drawn one) is put on their actions, as drawings.drawn_command_icons does for Draw*.
_cmd_icons = {"timer": False, "hooked": False, "ticks": 0, "logged": 0}
NATIVE_OWNER = {"Sketcher_BSplineInsertKnot": "InsertSplinePoint"}


def _command_pictures():
    ""

    from . import catalog
    out = {}
    owners = {}
    for cmd in catalog.ALL:
        for x in cmd.natives:
            owners.setdefault(x, []).append(cmd.key)
    for cmd in catalog.ALL:
        try:
            pic = family(cmd.icon) if cmd.icon else QtGui.QIcon()
            if not paints(pic):
                pic = family("FW_" + cmd.key)
            if not paints(pic):
                pic = drawn(cmd.key)
            if not paints(pic):
                continue
            names = [x for x in cmd.natives if x.startswith(("FreeWorks_", "SWStyle_"))]
            names += ["FreeWorks_" + cmd.key, "FreeWorks_Draw" + cmd.key, "FreeWorks_Sketch3D" + cmd.key]
            # icons-exact-1122f: FreeCAD's own command (menus) shows this command's picture, pack first. A native that several
            # catalog commands list (Sketcher_BSplineInsertKnot) goes to the owner named in NATIVE_OWNER, else it is left alone.
            for x in cmd.natives:
                if x in names or x.startswith(("FreeWorks_", "SWStyle_")):
                    continue
                boss = NATIVE_OWNER.get(x)
                if (boss == cmd.key) or (boss is None and len(owners.get(x, ())) == 1):
                    names.append(x)
            for name in names:
                out.setdefault(name, pic)
        except Exception:
            continue
    return out


MENU_TITLES = ("Spline Tools", "Sketch Tools", "Sketch Entities")


def _label_pictures():
    """{catalog label: QIcon} for the commands that have a picture, pack first."""
    from . import catalog
    out = {}
    for cmd in catalog.ALL:
        try:
            pic = family(cmd.icon) if cmd.icon else QtGui.QIcon()
            if not paints(pic):
                pic = family("FW_" + cmd.key)
            if not paints(pic):
                pic = drawn(cmd.key)
            if paints(pic):
                out.setdefault(cmd.label.replace("&", "").rstrip("."), pic)
        except Exception:
            continue
    return out


def _menu_icons_once():
    ""


    import os
    if os.environ.get("FREEWORKS_NO_MENUICONS") or _cmd_icons.get("menus_busy"):
        return 0
    _cmd_icons["menus_busy"] = True
    n = 0
    try:
        import FreeCADGui as Gui
        mw = Gui.getMainWindow()
        bar = mw.menuBar() if mw is not None else None
        if bar is None:
            return 0
        labels = _label_pictures()
        stack = [(a.menu(), False) for a in bar.actions() if a.menu() is not None]
        seen = 0
        while stack and seen < 400:
            menu, inside = stack.pop()
            seen += 1
            for a in list(menu.actions()):
                sub = a.menu()
                text = a.text().split("\t")[0].replace("&", "").rstrip(".").strip()
                if sub is not None:
                    stack.append((sub, inside or text in MENU_TITLES))
                elif inside:
                    pic = labels.get(text)
                    if pic is not None:
                        a.setIcon(pic)
                        n += 1
    except Exception:
        pass
    finally:
        _cmd_icons["menus_busy"] = False
    return n


def apply_command_icons():
    """icons-exact-1122d: puts those pictures on the commands' actions, and on every action of that object name in the window
    (menus hold the command's own action, a copy keeps its object name). Retried a few times while the workbenches load."""
    n, found, missing = 0, 0, []
    try:
        import FreeCADGui as Gui
        pics = _command_pictures()
    except Exception:
        return 0
    action_type = getattr(QtGui, "QAction", None)
    if action_type is None:
        from PySide import QtWidgets
        action_type = QtWidgets.QAction
    by_name = {}
    try:
        mw = Gui.getMainWindow()
        for a in (mw.findChildren(action_type) if mw is not None else ()):
            by_name.setdefault(a.objectName(), []).append(a)
    except Exception:
        pass
    for name, pic in pics.items():
        try:
            acts = list(by_name.get(name, ()))
            c = Gui.Command.get(name)
            if c is not None:
                for a in (c.getAction() or ()):
                    if a not in acts:
                        acts.append(a)
            if not acts:
                missing.append(name)
                continue
            found += 1
            for a in acts:
                a.setIcon(pic)
                n += 1
        except Exception:
            continue
    if _cmd_icons["logged"] < 3:
        _cmd_icons["logged"] += 1
        try:
            import FreeCAD as App
            from . import catalog
            probe = "Sketcher_BSplineInsertKnot"
            owners = []
            for cmd in catalog.ALL:
                if probe in cmd.natives:
                    owners.append("%s icon=%s pack=%s fw=%s drawn=%s" % (
                        cmd.key, cmd.icon, paints(family(cmd.icon)) if cmd.icon else "-",
                        paints(family("FW_" + cmd.key)), paints(drawn(cmd.key))))
            state = ("in pictures" if probe in pics else "NOT in pictures") + (", action missing" if probe in missing else
                                                                              ", action found" if probe in pics else "")
            App.Console.PrintMessage("FreeCAD icons: %d of %d command names got our picture (%d actions); %s %s; owners: %s; "
                                     "action objects named so: %d\n" % (found, len(pics), n, probe, state,
                                                                        " | ".join(owners) or "none in catalog",
                                                                        len(by_name.get(probe, ()))))
        except Exception as err:
            try:
                import FreeCAD as App
                App.Console.PrintMessage("FreeCAD icons: diagnostics failed: %s\n" % err)
            except Exception:
                pass
    return n


def _cmd_tick():
    # icons-refresh-1126: was a second _tick, which replaced the dark-names one above, so the 30 ms dark-names timer ran
    # this (a full apply every 30 ms, for ever, in Dark) and the dark FreeCAD icons were never written.
    _cmd_icons["ticks"] += 1
    if not _cmd_icons.get("classic"):
        _capture_originals()
        apply_command_icons()
    if _cmd_icons["ticks"] < 12:
        QtCore.QTimer.singleShot(5000, _cmd_tick)


# icons-refresh-1126: FreeCAD's own picture of each action we give ours, kept the first time it is seen (before ours goes
# on), so the classic FreeCAD interface gets them back; and the pictures put on again after a live Light/Dark switch.
_originals = {"by_ptr": {}}


def _pointer(action):
    try:
        import shiboken6
        return shiboken6.getCppPointer(action)[0]
    except Exception:
        try:
            import shiboken2
            return shiboken2.getCppPointer(action)[0]
        except Exception:
            return id(action)


def _actions_for(names):
    """The actions apply_command_icons() gives a picture to: the command's own and every action of that object name."""
    import FreeCADGui as Gui
    action_type = getattr(QtGui, "QAction", None)
    if action_type is None:
        from PySide import QtWidgets
        action_type = QtWidgets.QAction
    by_name = {}
    try:
        mw = Gui.getMainWindow()
        for a in (mw.findChildren(action_type) if mw is not None else ()):
            by_name.setdefault(a.objectName(), []).append(a)
    except Exception:
        pass
    out = []
    for name in names:
        acts = list(by_name.get(name, ()))
        try:
            c = Gui.Command.get(name)
            if c is not None:
                for a in (c.getAction() or ()):
                    if a not in acts:
                        acts.append(a)
        except Exception:
            pass
        out.extend((name, a) for a in acts)
    return out


def _capture_originals():
    try:
        kept = _originals["by_ptr"]
        for name, a in _actions_for(list(_command_pictures().keys())):
            key = _pointer(a)
            if key not in kept:
                kept[key] = (name, a, a.icon())
    except Exception:
        pass


def _apply_later():
    if not _cmd_icons.get("classic"):
        _capture_originals()
        apply_command_icons()


def refresh_command_icons():
    """A live theme switch: our pictures again, in the new theme's ink (nothing new is scanned beyond the actions)."""
    if _ROOT is None or not _cmd_icons["timer"] or _cmd_icons.get("classic"):
        return 0
    _capture_originals()
    return apply_command_icons()


def classic_icons():
    """The classic FreeCAD interface (Feature-based interface off): FreeCAD's own pictures back on the actions we changed,
    and our name overrides off the search path. Menu entries renamed by the Tools menu pass keep ours until a restart."""
    _cmd_icons["classic"] = True
    n = _named_to_stock()
    remove_freecad_overrides()
    for key, (name, action, icon) in list(_originals["by_ptr"].items()):
        try:
            stock = _stock_icon(name)
            action.setIcon(stock if stock is not None else icon)
            n += 1
        except Exception:
            _originals["by_ptr"].pop(key, None)       # an action Qt has deleted
    return n


def _override_names():
    """The FreeCAD icon names our 'icons' search-path folders replace."""
    names = set()
    folders = [_ROOT / "fc", _ROOT / "dark" / "fc"]
    dark = _dark_dir_text()
    if dark:
        from pathlib import Path
        folders.append(Path(dark))
    for folder in folders:
        try:
            names.update(p.stem for p in folder.iterdir())
        except Exception:
            pass
    return names


def _named_to_stock():
    """Actions that got our picture through the search path (view, display and standard commands): FreeCAD's resource
    picture back on them; ours is kept to put back when the Feature-based interface comes on again."""
    n = 0
    try:
        import FreeCADGui as Gui
        action_type = getattr(QtGui, "QAction", None)
        if action_type is None:
            from PySide import QtWidgets
            action_type = QtWidgets.QAction
        replaced = _override_names()
        kept = _originals.setdefault("named", {})
        mw = Gui.getMainWindow()
        for a in (mw.findChildren(action_type) if mw is not None else ()):
            name = a.objectName()
            if not name or name.startswith(("FreeWorks_", "SWStyle_")):
                continue
            try:
                c = Gui.Command.get(name)
                pixmap = (c.getInfo() or {}).get("pixmap", "") if c is not None else ""
            except Exception:
                continue
            if not pixmap or pixmap not in replaced:
                continue
            stock = _stock_icon(name)
            if stock is None:
                continue
            kept[_pointer(a)] = (a, a.icon())
            a.setIcon(stock)
            n += 1
    except Exception:
        pass
    return n


def _named_back():
    for key, (action, icon) in list(_originals.get("named", {}).items()):
        try:
            action.setIcon(icon)
        except Exception:
            pass
    _originals["named"] = {}


def _stock_icon(name):
    """FreeCAD's built-in picture of one of its own commands (its resource, not the search path our override held when the
    action was first drawn), or None for our own commands and anything not found."""
    if name.startswith(("FreeWorks_", "SWStyle_")):
        return None
    try:
        import FreeCADGui as Gui
        c = Gui.Command.get(name)
        pixmap = (c.getInfo() or {}).get("pixmap", "") if c is not None else ""
        for path in (":/icons/%s.svg" % pixmap, ":/icons/%s.png" % pixmap, ":/icons/%s" % pixmap):
            if pixmap and QtCore.QFile.exists(path):
                icon = QtGui.QIcon(path)
                if not icon.isNull():
                    return icon
    except Exception:
        pass
    return None


def freeworks_icons():
    """Feature-based interface on again: the overrides and our pictures back."""
    if not _cmd_icons.get("classic"):
        return 0
    _cmd_icons["classic"] = False
    install_freecad_overrides()
    _named_back()
    return refresh_command_icons()


def _menu_pass():
    if _cmd_icons.get("classic"):
        return
    n = _menu_icons_once()
    if _cmd_icons["logged"] < 8:
        _cmd_icons["logged"] += 1
        try:
            import FreeCAD as App
            App.Console.PrintMessage("FreeCAD icons: menu entries changed: %d\n" % n)
        except Exception:
            pass


def _schedule_command_icons():
    if _cmd_icons["timer"]:
        return
    _cmd_icons["timer"] = True
    QtCore.QTimer.singleShot(6000, _cmd_tick)
    QtCore.QTimer.singleShot(15000, _menu_pass)
    QtCore.QTimer.singleShot(40000, _menu_pass)
    try:
        import FreeCADGui as Gui
        mw = Gui.getMainWindow()
        if mw is not None and not _cmd_icons["hooked"]:
            mw.workbenchActivated.connect(lambda *_a: QtCore.QTimer.singleShot(2500, _apply_later))
            _cmd_icons["hooked"] = True
    except Exception:
        pass


def remove_freecad_overrides():
    if _ROOT is None:
        return
    text = (_ROOT / "fc").as_posix()
    dark = _dark_dir_text()
    own = dark_fc_text()
    current = [item for item in QtCore.QDir.searchPaths("icons") if item not in (text, dark, own)]
    QtCore.QDir.setSearchPaths("icons", current)
