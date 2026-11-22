# SPDX-License-Identifier: LGPL-2.1-or-later
"""Commands of workbenches that are not loaded yet, for Search Commands and Customize > Commands.

The add-in tabs (addintabs.py, fcextratabs.py) name FreeCAD commands of workbenches that load the
first time their tab is shown (Draft, Points, Reverse Engineering, Inspection, CAM, FEM ...). Until
then those commands do not exist, so their rows in Search Commands were greyed and ran nothing, also
for tabs that start hidden; and a command of a workbench this installation does not have (CfdOF, the
3D CAM operations without OpenCamLib) was a row that could never run. Here:

- state(cmd): "ready" (one of its commands exists, or it runs a call of ours), "load" (its
  workbench is installed and not loaded yet: the row is live, and running it loads the workbench
  first, as showing its tab does), "none" (this installation has no such command: the row is left
  out) or "" (nothing known about it: as before);
- load(cmd, shell): loads the workbench the way its tab does (addintabs._after_load, which also
  drops the tab buttons this installation lacks) and returns "ready", "busy" (a sketch or a command
  is open and FreeCAD cannot switch workbench under it) or "none".
"""
import FreeCAD as App

try:
    import FreeCADGui as Gui
except Exception:   # pragma: no cover
    Gui = None

MESSAGES = {"busy": "Finish the sketch or the open command first, then run %s again.",
            "none": "%s is not available in this FreeCAD installation."}


def _has(name):
    try:
        return Gui.Command.get(name) is not None
    except Exception:
        return False


def _prefix(name):
    return name.split("_", 1)[0] + "_" if "_" in name else ""


def _candidates(cmd):
    """[(source, workbench, probe)]: the add-in sources whose commands are named like cmd's."""
    try:
        from . import addintabs
        sources = dict(addintabs.SOURCES)
    except Exception:
        return []
    want = {_prefix(n) for n in (cmd.natives or ()) if _prefix(n)}
    out = []
    for source, rows in sources.items():
        for row in rows:
            try:
                wb, _modules, probe = row
            except Exception:
                continue
            if _prefix(probe) in want:
                out.append((source, wb, probe))
    return out


def state(cmd):
    if Gui is None or not cmd.natives or cmd.call:
        return "ready"
    if any(_has(n) for n in cmd.natives):
        return "ready"
    rows = _candidates(cmd)
    if not rows:
        return ""
    try:
        from . import addintabs
        installed = set(Gui.listWorkbenches())
        loaded = set(addintabs._loaded)
    except Exception:
        return ""
    for source, wb, probe in rows:
        if wb in installed and source not in loaded and not _has(probe):
            return "load"
    return "none"


def load(cmd, shell=None):
    """Loads the workbench behind cmd; "ready", "busy" or "none"."""
    try:
        from . import addintabs
    except Exception:
        return "none"
    title = ""
    try:
        title = shell.topbar.current_page().title
    except Exception as error:
        App.Console.PrintLog("Search Commands: current tab not read: %s\n" % error)
    for source, wb, probe in _candidates(cmd):
        if _has(probe) or source in addintabs._loaded:
            continue
        try:
            addintabs._after_load(source, title)
        except Exception as error:
            App.Console.PrintLog("Search Commands: %s did not load: %s\n" % (source, error))
        if any(_has(n) for n in cmd.natives):
            return "ready"
    if any(_has(n) for n in cmd.natives):
        return "ready"
    try:
        if addintabs._editing():
            return "busy"
    except Exception as error:
        App.Console.PrintLog("Search Commands: edit state not read: %s\n" % error)
    return "none"
