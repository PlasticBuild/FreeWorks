# SPDX-License-Identifier: LGPL-2.1-or-later
"""drawnotready-1127: what to do first, for a drawing menu row that cannot act yet.

greyrows-1126 keeps every menu bar row live and opens a Message page when its command cannot act. Its words are
general ("Pick what it works on in the FeatureManager design tree..."), which reads wrong on a drawing sheet. With a
drawing sheet in front, menunotready.text_for asks text() here first: the words name what the row needs on the
sheet (a view, an edge in a view, dimensions, notes, sketch entities, a block, another sheet). None: not a drawing
row, or nothing to add (the general words stay)."""

_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return


VIEW = "Pick a drawing view on the sheet first, then use %s again."
EDGE = "Pick a straight edge in a drawing view first, then use %s again."
ALIGNED = "Pick a projected, section or auxiliary view first (a view that is lined up with its parent view)."
ANNOTS = "Pick two or more notes, dimensions or balloons on the sheet first, then use %s again."
DIMS = "Pick two or more dimensions on the sheet first, then use %s again."
DIM_ONE = "Pick a dimension on the sheet first, then use %s again."
ENTS = "Pick the sketch entities on the sheet first, then use %s again."
SPLINE = "Pick a spline on the sheet first (Tools > Sketch Entities > Spline sketches one), then use %s again."
BLOCK = "Pick a block on the sheet first (Tools > Block > Make makes one, Insert > Block places a saved one)."
PART_SKETCH = ("%s works in a sketch of the part, not on a drawing sheet. Open the part (right-click a view > "
               "Open Part) and use it there.")

# command: words ("%s" is the row's name)
BY_COMMAND = {
    "FreeWorks_DrawCut": "Pick the views, annotations or sketch entities on the sheet first, then use %s again.",
    "FreeWorks_DrawCopy": "Pick the views, annotations or sketch entities on the sheet first, then use %s again.",
    "FreeWorks_DrawDelete": "Pick the views, annotations or sketch entities on the sheet first, then use %s again.",
    "FreeWorks_DrawPaste": ("Nothing is copied yet. Pick views, annotations or sketch entities on the sheet and "
                            "Copy them (Ctrl+C) first."),
    "FreeWorks_DrawEditSheet": ("You are editing the sheet already. Edit Sheet brings you back here from Edit Sheet "
                                "Format (right-click the sheet > Edit Sheet Format)."),
    "Std_ViewFitSelection": "Pick a view, annotation or sketch entity on the sheet first, then use %s again.",
    "FreeWorks_DrawResolveDrawing": ("This drawing is resolved already. %s works on a drawing opened lightweight or "
                                     "in Detailing mode."),
    "FreeWorks_DrawResolve": "Pick a lightweight view on the sheet first, then use %s again.",
    "FreeWorks_DrawViewProperties": VIEW,
    "FreeWorks_DrawTangentVisible": VIEW,
    "FreeWorks_DrawTangentWithFont": VIEW,
    "FreeWorks_DrawTangentRemoved": VIEW,
    "FreeWorks_DrawTangentWithHiddenEnds": VIEW,
    "FreeWorks_DrawZoomToMarkup": ("This drawing has no markup view yet. Add markup first (Markup tab), then use %s "
                                   "again."),
    "FreeWorks_DrawShowHiddenViews": "No view on this sheet is hidden. Hide a view first (right-click a view > Hide).",
    "FreeWorks_DrawWeldmentCutList": ("Insert a view of a weldment part first (a part with structural members), then "
                                      "pick the view and use %s again."),
    "FreeWorks_TDX_ClipAdd": "Pick a drawing view and a clip group on the sheet first, then use %s again.",
    "FreeWorks_TDX_HoleShaftFit": "Pick a diameter or linear dimension on the sheet first, then use %s again.",
    "FreeWorks_DrawAlignHorizontalEdge": EDGE,
    "FreeWorks_DrawAlignVerticalEdge": EDGE,
    "FreeWorks_DrawRotateClockwise": EDGE,
    "FreeWorks_DrawRotateCounterclockwise": EDGE,
    "FreeWorks_DrawProjectedAngle": VIEW,
    "FreeWorks_DrawAlignHorizontalCenter": "Pick the drawing view to move first; %s then asks for the view to line it up with.",
    "FreeWorks_DrawAlignVerticalCenter": "Pick the drawing view to move first; %s then asks for the view to line it up with.",
    "FreeWorks_DrawBreakAlignment": ALIGNED,
    "FreeWorks_DrawDefaultAlignment": "Pick a view whose alignment was broken first (Break Alignment), then use %s again.",
    "FreeWorks_DrawAlignBetweenLines": "Pick the notes or balloons to place, and the two lines to centre them between, first.",
    "FreeWorks_DrawDimAlignCollinear": DIMS,
    "FreeWorks_DrawDimAlignParallel": DIMS,
    "FreeWorks_DrawDimAutoArrange": DIMS,
    "FreeWorks_DrawDimSpaceEvenly": DIMS,
    "FreeWorks_DrawStagger": DIMS,
    "FreeWorks_DrawDimBreakAlignment": "Pick a dimension that is aligned or grouped with others first, then use %s again.",
    "FreeWorks_DrawAlignDimTextTop": DIM_ONE,
    "FreeWorks_DrawAlignDimTextBottom": DIM_ONE,
    "FreeWorks_DrawAlignDimTextLeft": DIM_ONE,
    "FreeWorks_DrawAlignDimTextRight": DIM_ONE,
    "FreeWorks_DrawConvertEntities": "Pick model edges in a drawing view first, then use %s again.",
    "FreeWorks_DrawSketchTangentArc": ("%s starts at the end of a line or arc. Sketch a line on the sheet first "
                                       "(Tools > Sketch Entities > Line), then use %s again."),
    "FreeWorks_DrawConstructionGeometry": ENTS,
    "FreeWorks_DrawMakePath": ENTS,
    "FreeWorks_DrawDissolve": "Pick a rectangle, polygon, slot or other closed outline on the sheet first, then use %s again.",
    "FreeWorks_DrawDynamicMirror": "Pick a centerline on the sheet first, then use %s again.",
    "FreeWorks_DrawMoveEntities": ENTS,
    "FreeWorks_DrawRotateEntities": ENTS,
    "FreeWorks_DrawScaleEntities": ENTS,
    "FreeWorks_DrawCopyEntities": ENTS,
    "SWStyle_ReplaceEntity": "Pick the sketch entity to replace on the sheet first, then use %s again.",
    "SWStyle_FitSpline": "Pick the sketch lines and arcs on the sheet to fit first, then use %s again.",
    "SWStyle_SketchXpert": ("%s works on a sketch whose relations clash. The sketch on this sheet has none to "
                            "resolve."),
    "FreeWorks_DrawInsertSplinePoint": SPLINE,
    "FreeWorks_Sketch3DAddTangencyControl": SPLINE,
    "FreeWorks_Sketch3DAddCurvatureControl": SPLINE,
    "FreeWorks_Sketch3DInsertControlVertex": SPLINE,
    "FreeWorks_Sketch3DSimplifySpline": SPLINE,
    "FreeWorks_Sketch3DConvertStyleSpline": SPLINE,
    "FreeWorks_Sketch3DConvertGenericSpline": SPLINE,
    "FreeWorks_Sketch3DShowHandles": SPLINE,
    "FreeWorks_Sketch3DShowControlPolygon": SPLINE,
    "FreeWorks_Sketch3DShowInflection": SPLINE,
    "FreeWorks_Sketch3DShowMinimumRadius": SPLINE,
    "FreeWorks_Sketch3DShowCurvature": SPLINE,
    "FreeWorks_Sketch3DConvertSpline": "Pick the sketch lines and arcs on the sheet to turn into a spline first.",
    "FreeWorks_Sketch3DIntersectionCurve": PART_SKETCH,
    "FreeWorks_Sketch3DAlignSketch": PART_SKETCH.replace("%s", "Align Sketch", 1),
    "SWStyle_AlignGridOrigin": PART_SKETCH,
    "SWStyle_CloseSketchToModel": PART_SKETCH,
    "FreeWorks_DrawQuickSnaps": ("Quick Snaps work while you sketch. Start a sketch tool on the sheet first "
                                 "(Tools > Sketch Entities > Line), then use %s again."),
    "FreeWorks_DrawEditBlock": BLOCK,
    "FreeWorks_DrawBlockAddRemove": BLOCK,
    "FreeWorks_DrawRebuildBlock": BLOCK,
    "FreeWorks_DrawSaveBlock": BLOCK,
    "FreeWorks_DrawExplodeBlock": BLOCK,
    "SWStyle_InvertSelection": "Pick something on the sheet first; %s then picks everything else on the sheet.",
}

# rows whose words depend on whether the sheet has sketch entities yet
NEEDS_ENTITIES = ("FreeWorks_DrawSegment", "FreeWorks_DrawExtend", "FreeWorks_DrawSplitEntities",
                  "FreeWorks_DrawJogLine", "FreeWorks_DrawStretchEntities", "FreeWorks_DrawEditPolygon",
                  "FreeWorks_DrawScanEqual", "FreeWorks_DrawConstrainAll", "FreeWorks_DrawConstructionGeometry",
                  "FreeWorks_DrawMakePath", "FreeWorks_DrawDissolve", "FreeWorks_DrawDynamicMirror",
                  "FreeWorks_DrawMoveEntities", "FreeWorks_DrawRotateEntities", "FreeWorks_DrawScaleEntities",
                  "FreeWorks_DrawCopyEntities", "SWStyle_ReplaceEntity", "SWStyle_FitSpline",
                  "FreeWorks_DrawSketchTangentArc", "FreeWorks_Sketch3DConvertSpline")
NO_ENTITIES = ("%s works on the sketch entities on the sheet, and there are none yet. Sketch a line, arc or circle on "
               "the sheet first (Tools > Sketch Entities), then use %s again.")
HAS_ENTITIES = {
    "FreeWorks_DrawSegment": "Pick the line or arc to divide on the sheet first, then use %s again.",
    "FreeWorks_DrawExtend": "Pick a line on the sheet first; %s then runs it on to the next entity.",
    "FreeWorks_DrawSplitEntities": "Pick the entity to split on the sheet first, then use %s again.",
    "FreeWorks_DrawJogLine": "Pick a line on the sheet first, then use %s again.",
    "FreeWorks_DrawStretchEntities": ENTS,
    "FreeWorks_DrawEditPolygon": "Pick a polygon on the sheet first, then use %s again.",
    "FreeWorks_DrawScanEqual": "Pick a view whose sketch has lines or circles first, then use %s again.",
    "FreeWorks_DrawConstrainAll": ENTS,
}


def _page():
    try:
        from . import drawings as D
        page = D.active_page()
        if page is not None and D.sheet_shown(page):
            return page
    except Exception as _fw_err:
        _fw_log("drawnotready.py:page", _fw_err)
    return None


def _has_entities(page):
    try:
        from . import drawsketchedit as SE
        return bool(SE.views_with_sketch(page))
    except Exception as _fw_err:
        _fw_log("drawnotready.py:entities", _fw_err)
        return True


def _sheets(page):
    try:
        return [o for o in page.Document.Objects if o.isDerivedFrom("TechDraw::DrawPage")]
    except Exception:
        return [page]


def _fill(words, what):
    return words.replace("%s", what)


def text(command, label):
    """The words for a drawing menu row that cannot act; None: not a drawing row (the general words stay)."""
    if not command:
        return None
    page = _page()
    if page is None:
        return None
    what = " ".join(label.replace("&", "").split("\t")[0].rstrip(". …").split()) or command
    try:
        if command in ("FreeWorks_DrawPreviousSheet", "FreeWorks_DrawNextSheet"):
            pages = _sheets(page)
            if len(pages) < 2:
                return ("This drawing has one sheet. Add a sheet first (the Add Sheet tab below the sheet, or "
                        "Insert > Sheet), then use %s again." % what)
            return ("This is the first sheet." if command.endswith("PreviousSheet") else "This is the last sheet.")
        if command in NEEDS_ENTITIES:
            if not _has_entities(page):
                return _fill(NO_ENTITIES, what)
            words = HAS_ENTITIES.get(command) or BY_COMMAND.get(command)
            return _fill(words, what) if words else None
        if command.startswith(("FreeWorks_DrawAlign", "FreeWorks_DrawSpace")) and command not in BY_COMMAND:
            return _fill(ANNOTS, what)
        words = BY_COMMAND.get(command)
        return _fill(words, what) if words else None
    except Exception as _fw_err:
        _fw_log("drawnotready.py:text", _fw_err)
        return None
