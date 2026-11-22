"""Which sketch behaviours the running FreeCAD's Sketcher has built in.

The look add-on runs on stock FreeCAD and on Ati's patched build. Options and
buttons that only mean something with a patch (inference lines, model
snapping, Esc ends the tool...) ask here first and hide or grey themselves
when the running Sketcher lacks them.

There is no Python API for this yet, so the check looks for each patch's
parameter name inside the SketcherGui binary: every name below is new in that
patch (none is in upstream 1.1.4 4fd3bf3). Once a patch is upstream, the same
check finds it in stock FreeCAD with no change here.
"""

import os

import FreeCAD as App

# feature -> parameter name compiled into SketcherGui by the patch that adds it
MARKERS = {
    "snap_points": "SnapToIntersections",       # 01 snap engine
    "escape_ends_tool": "EscapeEndsTool",       # 04
    "drag_relations": "DrivenWhenOverDefining", # 06
    "inference_lines": "SnapToExtensions",      # 07
    "alignment_look": "AlignmentAddsRelation",  # 07c/07d
    "midpoint_guides": "MidpointGuides",        # 07g
    "click_drag": "ClickDragDrawing",           # 08
    "length_snap": "SnapToLength",              # 10
    "driven_prompt": "PromptDrivenState",       # 12b
    "numeric_input": "OnScreenNumericInput",    # 22
    "center_diagonals": "CenterRectangleDiagonals",  # 22
    "line_menu": "LineContextMenu",             # 23
    "typed_dimension": "NumericInputAddsDimension",   # 27
    "centerpoint_slot": "Centerpoint straight slot",   # 30: Sketcher_CreateSlot method 1
    "three_point_arc_slot": "3 point arc slot",        # 30: Sketcher_CreateArcSlot method 2
    "overdefined_color": "OverDefinedColor",          # 28
    "polygon_inscribed": "PolygonInscribedCircle",    # 31
    "trim_construction": "TrimKeepAsConstruction",    # 31
}

# Read on demand: True/False forces a feature (tests, or a build the scan misreads)
OVERRIDE = "User parameter:BaseApp/Preferences/Mod/FreeWorks/NativeFeatures"

_found = None

# relations stock-04: behaviours the add-on's Python sketch tools (swstyle/fwsketch) give on stock
# FreeCAD, by the same feature names, so their Options rows work without the patched build
PYTHON = {
    "snap_points", "escape_ends_tool", "drag_relations", "inference_lines", "alignment_look",
    "midpoint_guides", "click_drag", "length_snap", "driven_prompt", "numeric_input", "line_menu",
    "typed_dimension", "centerpoint_slot", "three_point_arc_slot", "overdefined_color",
    "polygon_inscribed", "trim_construction",
}
# relations stock-06: the Center Rectangle's "Add construction lines", once rectangle.py has it
PYTHON_IF = {"center_diagonals": ("rectangle", "diagonals")}

_in_binary = None


def _python():
    try:
        from . import fwsketch  # noqa: F401
    except Exception:
        return set()
    names = {name for name in PYTHON if name in MARKERS}
    for name, (module, attr) in PYTHON_IF.items():
        try:
            mod = __import__(fwsketch.__name__ + "." + module, fromlist=[attr])
        except Exception:
            continue
        if hasattr(mod, attr):
            names.add(name)
    return names


def _binary():
    try:
        import SketcherGui
    except ImportError:
        return None
    path = getattr(SketcherGui, "__file__", None)
    return path if path and os.path.isfile(path) else None


def _scan():
    path = _binary()
    if path is None:
        return set()
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return set()
    return {name for name, marker in MARKERS.items() if marker.encode("ascii") in data}


def features():
    """Set of feature names from MARKERS that the running Sketcher has."""
    global _found
    if _found is None:
        global _in_binary
        _in_binary = _scan()
        _found = _in_binary | _python()
        App.Console.PrintLog("Sketch features built in: %s\n" % (", ".join(sorted(_found)) or "none"))
    found = set(_found)
    grp = App.ParamGet(OVERRIDE)
    for name in MARKERS:
        if grp.GetBool(name, False):
            found.add(name)
        elif not grp.GetBool(name, True):
            found.discard(name)
    return found


def has(name):
    return name in features()


def is_stock():
    """True when none of the sketch patches are in the running Sketcher (the add-on's Python
    tools may still give their behaviours: see features())."""
    features()
    return not _in_binary

