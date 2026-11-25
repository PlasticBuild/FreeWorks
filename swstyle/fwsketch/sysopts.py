# SPDX-License-Identifier: LGPL-2.1-or-later
""



PAGE = "Sketch"
ARC_CENTERPOINTS = ("Display arc centerpoints in part/assembly sketches", True)
ENTITY_POINTS = ("Display entity points in part/assembly sketches", True)
PROMPT_CLOSE = ("Prompt to close sketch", True)
VIRTUAL_SHARPS_3D = ("Line length measured between virtual sharps in 3d", True)
SPLINE_HANDLES = ("Enable spline tangency and curvature handles", True)
GHOST_ON_DRAG = ("Ghost image on drag", True)
COMB_BOUNDING = ("Show curvature comb bounding curve", False)
HIDE_SUPPRESSED_MISSING = ("Hide missing geometry error for suppressed dimensions", False)


def on(row):
    text, default = row
    try:
        from .. import optionspages
        return bool(optionspages.stored(PAGE, text, default))
    except Exception:
        return default


def set_on(row, value):
    from .. import optionspages
    optionspages.set_stored(PAGE, row[0], bool(value))


def snap_points_per_minor():
    """Options > Grid/Snap > Snap points per minor (fix58): the grid snaps that many times per
    minor grid line spacing (1: on the minor lines only)."""
    try:
        from .. import optionspages

        import FreeCAD as App
        n = int(optionspages.doc_value(App.ActiveDocument, "Grid/Snap", "Snap points per minor", 1)) \
            if hasattr(optionspages, "doc_value") else int(optionspages.stored("Grid/Snap", "Snap points per minor", 1))
    except Exception:
        n = 1
    return max(1, n)
