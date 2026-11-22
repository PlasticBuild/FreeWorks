""


NATIVES = frozenset("FreeWorks_" + k for k in (
    "DrawBreakAlignment", "DrawDefaultAlignment", "DrawAlignHorizontalOrigin", "DrawAlignVerticalOrigin",
    "DrawAlignHorizontalCenter", "DrawAlignVerticalCenter", "DrawAlignHorizontalEdge", "DrawAlignVerticalEdge",
    "DrawRotateClockwise", "DrawRotateCounterclockwise", "DrawSaveSheetFormat", "DrawTangentWithHiddenEnds",
    "DrawTangentVisible", "DrawTangentWithFont", "DrawTangentRemoved",
    "DrawAddSheet", "DrawHideView", "DrawLockViewPosition", "DrawAddRevision"))


def none_for(command):
    """True when the menu row that runs this command shows no picture."""
    return bool(command) and command in NATIVES
