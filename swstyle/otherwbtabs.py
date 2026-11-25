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

import FreeCAD as App

try:
    import FreeCADGui as Gui
except ImportError:
    Gui = None

from . import paths

CACHE = paths.PARAM_PATH + "/OtherWorkbenchTabs"
SKIP = ("NoneWorkbench", "StartWorkbench", "AssemblyWorkbench")     # Assembly: the add-on's own assembly mode
_TABS = {}          # workbench name -> tab title
STOCK_PREFIXES = {"Std", "Part", "PartDesign", "Sketcher", "Draft", "TechDraw", "Assembly", "FEM", "CAM", "Mesh",
                  "Spreadsheet", "Measure", "Materials", "Points", "Surface", "BIM", "Arch", "OpenSCAD"}


def _src(wb):
    return "OWB_" + "".join(ch for ch in wb if ch.isalnum())


def _all_key(wb):
    return "OWB_All_" + "".join(ch for ch in wb if ch.isalnum())


def _key(wb, command):
    return "OWB_%s_%s" % ("".join(ch for ch in wb if ch.isalnum()), "".join(ch for ch in command if ch.isalnum() or ch == "_"))


def others():
    """{workbench name: title} of the installed workbenches the add-on has no tab or button for."""
    if Gui is None:
        return {}
    from . import catalog
    covered = {cmd.call[3:] for cmd in catalog.BY_KEY.values() if isinstance(cmd.call, str) and cmd.call.startswith("wb:")}
    try:
        from . import addintabs
        for rows in addintabs.SOURCES.values():
            covered.update(row[0] for row in rows if not str(row[0]).startswith("OWB_"))
    except Exception as _fw_err:
        _fw_log("otherwbtabs.py:covered", _fw_err)
    out = {}
    for name, wb in Gui.listWorkbenches().items():
        if name in covered or name in SKIP:
            continue
        title = str(getattr(wb, "MenuText", "") or name).replace("&", "").strip() or name
        out[name] = title
    return out


def _cached(wb):
    try:
        raw = App.ParamGet(CACHE).GetString(wb, "")
        return json.loads(raw) if raw else []
    except Exception:
        return []


def _read_toolbars(wb):
    """[(toolbar, [(command, label, tip)])] of a started workbench, or [] when its commands are not made yet."""
    try:
        items = Gui.getWorkbench(wb).getToolbarItems()
    except Exception:
        return []
    out = []
    for bar, names in items.items():
        row = []
        for n in names:
            if n == "Separator" or n.startswith("Std_"):
                continue        # FreeCAD's own File / Edit / View / Workbench / Macro bars: the add-on has those
            try:
                cmd = Gui.Command.get(n)
                info = cmd.getInfo() if cmd is not None else None
            except Exception:
                info = None
            if not info:
                continue
            label = str(info.get("menuText") or n).replace("&", "").replace("...", "").strip() or n
            row.append((n, label, str(info.get("toolTip") or "")))
        # a bar made only of FreeCAD's own part tools (the selection filter and datum bars FreeCAD adds to
        # every workbench) is not this workbench's: the add-on has those
        if row and any(n.split("_", 1)[0] not in STOCK_PREFIXES for n, _l, _t in row):
            out.append((str(bar), row))
    return out


def _layout(wb, title, toolbars):
    from . import catalog
    first = _all_key(wb)
    if first not in catalog.BY_KEY:
        catalog.BY_KEY[first] = catalog.c(first, "All %s Tools" % title, ("SWStyle_AllTools_" + _src(wb),), "FLYOUT_ADD_INS",
                  "Every command of %s, by toolbar." % title, caption="All\nTools")
    layout = [("large", first, None)]
    seen = set()
    for _bar, row in toolbars:
        group = []
        for command, label, tip in row:
            if command in seen:
                continue
            seen.add(command)
            key = _key(wb, command)
            if key not in catalog.BY_KEY:
                catalog.BY_KEY[key] = catalog.c(key, label, (command,), None, tip or label)
            group.append(("large", key, None))
        if group:
            layout.append(("sep",))
            layout.extend(group)
    catalog.ALL = tuple(catalog._ALL)       # command search finds them too
    return tuple(layout)


def _register(wb, title, toolbars):
    """The tab's source (its workbench is started on first show), its All Tools command and its layout."""
    from . import addintabs, cmtabs
    src = _src(wb)
    probe = toolbars[0][1][0][0] if toolbars else "__fw_owb_probe_" + wb     # a probe never made: start it once
    addintabs.SOURCES[src] = ((wb, (), probe),)
    addintabs.PREFIXES[src] = ("\0",)       # its commands are found through its toolbars only
    addintabs.TAB_SOURCE[title] = src
    name = "SWStyle_AllTools_" + src
    if name not in Gui.listCommands():
        Gui.addCommand(name, addintabs.AllTools(src, "All %s Tools" % title))
    layout = _layout(wb, title, toolbars)
    addintabs.TABS[title] = layout
    cmtabs.TABS[title] = layout
    if title not in cmtabs.ORDER:
        cmtabs.ORDER = tuple(cmtabs.ORDER) + (title,)
    _TABS[wb] = title


def _refresh_loaded():
    """Tabs whose workbench started since: their buttons from its toolbars (kept for the next start)."""
    from . import addintabs, cmtabs
    changed = False
    for wb, title in list(_TABS.items()):
        bars = _read_toolbars(wb)
        if not bars:
            continue
        try:
            App.ParamGet(CACHE).SetString(wb, json.dumps(bars))
        except Exception as _fw_err:
            _fw_log("otherwbtabs.py:cache", _fw_err)
        layout = _layout(wb, title, bars)
        if tuple(cmtabs.TABS.get(title, ())) != layout:
            addintabs.TABS[title] = layout
            cmtabs.TABS[title] = layout
            cmtabs._ALL_TABS[:] = [t for t in cmtabs._ALL_TABS if t[0] != title]
            from . import catalog
            catalog.TABS = tuple(t for t in catalog.TABS if t[0] != title)
            changed = True
    return changed


def off_titles():
    """Tabs of workbenches unticked in Tools > Add-Ins > Other Add-ins."""
    try:
        from . import addins
        return [title for wb, title in _TABS.items() if not addins.workbench_enabled(wb)]
    except Exception as _fw_err:
        _fw_log("otherwbtabs.py:off", _fw_err)
        return []


def rescan():
    ""

    added = False
    for wb, title in others().items():
        if wb in _TABS:
            continue
        try:
            _register(wb, title, _cached(wb))
            added = True
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: no tab for %s (%s)\n" % (title, error))
    if added:
        try:
            from . import cmtabs
            cmtabs.apply(rebuild=True)
        except Exception as _fw_err:
            _fw_log("otherwbtabs.py:rescan", _fw_err)
    return added


def _quiet_rescan():
    try:
        rescan()
    except Exception as _fw_err:
        _fw_log("otherwbtabs.py:late", _fw_err)


def _hook_search():
    """Command search: typing a workbench's name (or part of it) starts that workbench once, so its commands are there to
    be found by name (they only exist once it has started; the tab keeps them for later starts)."""
    try:
        from . import shell as shell_mod
        cls = shell_mod.CommandSearch
        if getattr(cls.typed, "_fw_owb", False):
            return
        original = cls.typed

        def typed(self, text, box):
            try:
                needle = (text or "").strip().lower()
                if len(needle) >= 3:
                    from . import addintabs
                    for wb, title in list(_TABS.items()):
                        src = _src(wb)
                        if src in addintabs._loaded or not (needle in title.lower() or title.lower() in needle
                                                            or needle in wb.lower()):
                            continue
                        addintabs.load(src)
                        if _refresh_loaded():
                            from . import cmtabs
                            cmtabs.apply(rebuild=True)
                        self._index = None          # rebuilt with the workbench's commands
            except Exception as _fw_err:
                _fw_log("otherwbtabs.py:search", _fw_err)
            return original(self, text, box)

        typed._fw_owb = True
        cls.typed = typed
    except Exception as _fw_err:
        _fw_log("otherwbtabs.py:hook-search", _fw_err)


def install():
    """After addintabs: a tab for each other workbench, and the hooks that keep them right."""
    if Gui is None:
        return
    from . import cmtabs
    rescan_quietly = lambda: _quiet_rescan()
    for wb, title in others().items():
        try:
            _register(wb, title, _cached(wb))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: no tab for %s (%s)\n" % (title, error))
    try:
        from PySide import QtCore
        for ms in (1500, 6000, 20000):       # the Mod folders after this one register their workbenches meanwhile
            QtCore.QTimer.singleShot(ms, rescan_quietly)
    except Exception as _fw_err:
        _fw_log("otherwbtabs.py:timers", _fw_err)
    _hook_search()
    if getattr(cmtabs.addin_off, "_fw_owb", False):
        return
    original_off, original_apply = cmtabs.addin_off, cmtabs.apply

    def addin_off():
        return list(original_off()) + off_titles()

    def apply(rebuild=True):
        try:
            _refresh_loaded()
        except Exception as _fw_err:
            _fw_log("otherwbtabs.py:apply", _fw_err)
        return original_apply(rebuild)

    addin_off._fw_owb = apply._fw_owb = True
    cmtabs.addin_off, cmtabs.apply = addin_off, apply
    try:
        from . import addintabs
        if not getattr(addintabs._after_load, "_fw_owb", False):
            original_after = addintabs._after_load

            def _after_load(source, shown_title):
                original_after(source, shown_title)
                if str(source).startswith("OWB_") and _refresh_loaded():
                    cmtabs.apply(rebuild=True)
                    try:
                        sh = addintabs._shell()
                        titles = [p.title for p in sh.topbar.pages]
                        if shown_title in titles:
                            sh.topbar.tabs.set_current(titles.index(shown_title))
                    except Exception as _fw_err:
                        _fw_log("otherwbtabs.py:reselect", _fw_err)

            _after_load._fw_owb = True
            addintabs._after_load = _after_load
    except Exception as _fw_err:
        _fw_log("otherwbtabs.py:hook", _fw_err)
