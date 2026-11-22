# SPDX-License-Identifier: LGPL-2.1-or-later
"""Breadcrumbs for crash hunting: with the environment variable FWSKETCH_TRACE set to a file path,
note(what) appends one line per step and flushes it to disk at once, so a crash in FreeCAD's C++
(an access violation Python cannot catch) still leaves the last step on record. Off (nothing
written, nearly no cost) without the variable."""

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
import time

_PATH = os.environ.get("FWSKETCH_TRACE") or None


def note(what):
    if _PATH is None:
        return
    try:
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write("%.3f %s\n" % (time.time(), what))
            f.flush()
            os.fsync(f.fileno())
    except OSError as _fw_err:
        _fw_log("fwsketch/trace.py:33", _fw_err)
