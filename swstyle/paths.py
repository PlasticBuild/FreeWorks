# SPDX-License-Identifier: LGPL-2.1-or-later
"""Where the addon and the private icon copy live."""

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
from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parent.parent
PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/FreeWorks"


def params():
    import FreeCAD as App
    return App.ParamGet(PARAM_PATH)


def icon_root():
    ""




    candidates = []
    env = os.environ.get("SWSTYLE_ICONS")
    if env:
        candidates.append(Path(env))
    try:
        saved = params().GetString("IconRoot", "")
        if saved:
            candidates.append(Path(saved))
    except Exception as _fw_err:
        _fw_log("paths.py:43", _fw_err)
    candidates.append(ADDON_DIR / "swstyle" / "resources" / "icons")
    # iconroot-1120: no built-in path to a private pack (release check); point SWSTYLE_ICONS or IconRoot at it
    for path in candidates:
        if (path / "png").is_dir():
            return path
    return None
