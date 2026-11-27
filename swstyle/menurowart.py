""



LABELS = {"Exit": "MENU_Exit", "Touch Mode": "MENU_TouchMode", "Exit Sketch without Saving Changes": "MENU_ExitSketchNoSave",
          # toolsins-1126: assembly and drawing rows that run no catalog command, the picture of their CommandManager button
          "Check Active Document": "CheckActiveDocument", "Check Against Existing File": "DesignCheckFile",
          "Build Checks": "DesignCheckBuild", "Learn Checks Wizard": "DesignCheckLearn",
          "New Assembly": "NewAssemblyInAssembly", "Coordinate System": "AsmRefCS", "Point": "AsmRefPoint",
          "Mate Reference": "MateReference", "Ground Plane": "AsmGroundPlane"}
_by = {}


def _maps():
    if _by:
        return _by
    from . import catalog
    native, label = {}, {}
    for cmd in catalog.ALL:
        for n in cmd.natives:
            native.setdefault(n, cmd.key)
        label.setdefault(cmd.label.replace("&", "").rstrip("."), cmd.key)
    _by["native"], _by["label"] = native, label
    return _by


def _strip(command):
    for prefix in ("FreeWorks_", "SWStyle_"):
        if command.startswith(prefix):
            return command[len(prefix):]
    return command


def icon(command, label=None):
    """The drawn QIcon for this row, or None."""
    try:
        from . import icons
        keys = []
        if command:
            keys += [command, _strip(command)]
            k = _maps()["native"].get(command)
            if k:
                keys.append(k)
        clean = (label or "").replace("&", "").split("\t")[0].rstrip(".")
        if clean in LABELS:
            keys.append(LABELS[clean])
        for key in keys:
            for pic in (icons.family("FW_" + key), icons.drawn(key)):     # icons-exact-1122: the pack first, our drawing only where it has none
                if icons.paints(pic):
                    return pic
    except Exception:
        pass
    return None
