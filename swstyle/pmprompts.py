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

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

FILLET = "Pick a callout to change its values"
SWEEP = ("Pick the sweep profile", "Pick the sweep path", "Pick the guide curves")
SECTION = "Adjust the section settings or drag the section plane"

# one for every open tool); shown while the page has no message of its own in the status bar
FILLET_EMPTY = "Pick the edges, faces, features or loops to round"
PAGES = {
    "Boss-Extrude": "Set the depth here or drag the arrow in the view",
    "Cut-Extrude": "Set the depth here or drag the arrow in the view",
    "Revolve": "Set the angle here or drag the arrow in the view",
    "Cut-Revolve": "Set the angle here or drag the arrow in the view",
    "Chamfer": "Pick the edges, faces or vertices to chamfer",
    "Shell": "Pick the faces to open, then set the wall thickness",
    "Draft": "Pick the neutral plane, then the faces to taper",
    "Mirror": "Pick the face or plane to mirror about, then what to mirror",
    "Linear Pattern": "Pick an edge or axis for the direction, then what to repeat",
    "Circular Pattern": "Pick an axis or round edge to turn about, then what to repeat",
    "Plane": "Pick up to three references the new plane follows",
    "Axis": "Pick the references the axis runs through",
    "Point": "Pick references and the kind of point",
    "Coordinate System": "Pick the origin, then the edges for the axes",
    "Mate Reference": "Pick the faces, edges or vertices the mates will snap to",
    "Interference Detection": "Pick the bodies to check, then press Calculate",
    "Rib": "Set the thickness and which side the rib grows on",
    "Dome": "Pick the face to dome and set its height",
    "Hole Specification": "Set the hole type here, then place it on the Positions tab",
    # pkg244: more pages (Engine Cover 2026 PC shots: the status bar was empty on these)
    "Appearance": "Pick the faces, features or bodies to color, then set the color",
    "Delete Face": "Pick the faces to delete, then choose Delete, Delete and Patch or Delete and Fill",
    "Hole Position": "Click on the faces to place the hole centers",
    "Thread": "Pick the round edge where the thread starts",
    "Split Line": "Pick what splits, then the faces to split",
    "Sweep": "Pick the sweep profile",
    "Loft": "Pick the profiles in order, then any guide curves",
    "Boundary-Surface": "Pick the curves in each direction",
    "Offset Surface": "Pick the faces or surfaces to offset and set the distance",
    "Knit Surface": "Pick the surfaces to knit together",
    "Thicken": "Pick the surface to thicken and set the thickness",
    "Move Face": "Pick the faces to move, then set the distance",
    "Combine": "Pick the bodies to combine",
    "Body-Delete/Keep": "Pick the bodies to delete or keep",
    "Body-Move/Copy": "Pick the bodies, then drag the handle or set the values",
    "Measure": "Pick the items to measure",
    "Edge-Flange": "Pick the edges to put a flange on",
    "Base Flange": "Set the thickness and the bend radius",
    "Hem": "Pick the edges to hem",
    "Structural Member": "Pick the sketch segments the member runs along",
    "Trim/Extend": "Pick the bodies to trim and the bodies to trim to",
    "End Cap": "Pick the end faces of the members to cap",
    "Gusset": "Pick the two faces the gusset joins",
    "Sheet Metal Gusset": "Pick the faces on either side of a bend",      # pkg439
    "Surface Curvature Combs": "Pick one or more faces, then set the curvature comb options",
}

SKETCH_TOOLS = {
    "Make Block": "Select the sketch entities for the block",
    "Insert Block": "Pick a block, then click in the graphics area to place it",
    "Trim": "Click an entity to trim it, or drag across the entities to trim",
    "Extend Entities": "Click the entity to extend",
    "Offset Entities": "Pick the entities to offset and set the distance",
    "Mirror": "Pick the entities to mirror, then the line to mirror about",
    "Convert Entities": "Pick the model edges or faces to bring into the sketch",
    "Linear Pattern": "Pick the entities to repeat and set the spacing",
    "Circular Pattern": "Pick the entities to repeat and set the count",
    "Move": "Pick the entities, then the base point and where it goes",
    "Copy": "Pick the entities, then the base point and where the copy goes",
    "Rotate": "Pick the entities, then the center and the angle",
    "Scale": "Pick the entities, then the base point and the factor",
    "Stretch": "Pick the entities, then the base point and where it goes",
    "Hole Position": "Click on the faces to place the hole centers",
}
# fix293: the drawing tools' pages (no Message group since pkg434) say how to draw, by the type picked on the page
DRAW_TYPES = {
    "Circle": "Click the center, then click to set the radius",
    "Perimeter Circle": "Click three points the circle passes through",
    "Centerpoint Arc": "Click the center, then where the arc starts and where it ends",
    "Tangent Arc": "Click the end of a line or arc, then where the arc ends",
    "3 Point Arc": "Click where the arc starts and ends, then a point on it",
    "Corner Rectangle": "Click one corner, then the opposite corner",
    "Center Rectangle": "Click the center, then a corner",
    "3 Point Corner Rectangle": "Click two corners along one side, then a point on the opposite side",
    "3 Point Center Rectangle": "Click the center, then the middle of one side, then a corner",
    "Parallelogram": "Click two corners along one side, then a point on the opposite side",
    "Straight Slot": "Click the start and end of the slot, then set its width",
    "Centerpoint Straight Slot": "Click the center of the slot, then one end, then set its width",
    "3 Point Arc Slot": "Click where the arc starts and ends, then a point on it, then set the width",
    "Centerpoint Arc Slot": "Click the arc's center, then where it starts and ends, then set the width",
    "Flat Ends Arc Slot": "Click the arc's center, then where it starts and ends, then set the width",
    "Line": "Click where the line starts, then where it ends",
    "Midpoint Line": "Click the middle of the line, then one of its ends",
}
DRAW_PAGES = {
    "Insert Line": "Click where the line starts, then where it ends",
    "Polygon": "Click the center, then click to set the size",
    "Point": "Click where the point goes",
    "Ellipse": "Click the center, then the end of one axis, then a point for the other",
    "Partial Ellipse": "Click the center, the end of one axis, a point for the other, then where it starts and ends",
    "Parabola": "Click the focus, then the vertex, then where the parabola starts and ends",
    "Spline": "Click the points the spline passes through; double-click to finish",
    "Style Spline": "Click the corners of the control polygon; double-click to finish",
}
SKETCH_IDLE = "Pick sketch entities to edit them, or choose a sketch tool"
IDLE = "Pick a face, edge or feature, or choose a command"     # pkg248: nothing open (own words)
OURS = (FILLET, SECTION, FILLET_EMPTY, SKETCH_IDLE, IDLE) + SWEEP + tuple(PAGES.values()) + tuple(SKETCH_TOOLS.values())
# pkg450 (Assemblies 11-27): the assembly tool works on components, not bodies
ASM_PAGES = {"Interference Detection": "Pick the components to check, then press Calculate"}
OURS = OURS + tuple(ASM_PAGES.values())
OURS = OURS + tuple(DRAW_TYPES.values()) + tuple(DRAW_PAGES.values())
MEASURE_IN_SECTION = ("A graphics-only section does not cut the model, so these measurements are of the whole model; "
                      "make a real section cut to measure the cut faces and edges.")
SWEEP_TITLES = ("Sweep", "Cut-Sweep", "Swept Boss/Base", "Swept Cut")
_state = {"timer": None}


def _shown(mw, name):
    w = mw.findChild(QtWidgets.QListWidget, name)
    try:
        return w if w is not None and w.isVisible() else None
    except RuntimeError:
        return None


def _section_open():
    try:
        from . import sectionview
        c = sectionview._controller
        if c is not None and c.panel is not None and not Gui.Control.activeDialog():
            # pkg244: the page was closed from outside (another command, closeDialog): finish it as
            # Cancel, or its prompt stayed under every later page and sketch
            c.finish(False)
        return c is not None and c.panel is not None
    except Exception:
        return False


# pkg439: pages that show only their Message group until the first pick (Base Flange, Miter Flange, Jog, Sketched Bend)
PICK_FIRST = {
    "Base Flange": "Pick a plane or a flat face to sketch on, or an existing sketch",
    "Miter Flange": "Pick a linear edge of the sheet",
    "Jog": "Pick a face of the sheet to sketch the jog line on, or an existing sketch",
    "Sketched Bend": "Pick a face of the sheet to sketch the bend line on, or an existing sketch",
}


def _only_message(view):
    """True when the page's only shown group is its Message."""
    titles = []
    try:
        for box in view.findChildren(QtWidgets.QWidget):
            if box.metaObject().className() != "Gui::TaskView::TaskBox" or not box.isVisible():
                continue
            hdr = next((w for w in box.findChildren(QtWidgets.QToolButton)), None)
            titles.append((hdr.text() if hdr is not None else "").replace("&", "").strip())
    except RuntimeError:
        return False
    return titles == ["Message"]


def _generic(title):
    return "Set the %s options, then click OK" % title if title else None


def _sketch_prompt():
    try:
        from . import sketchtoolpm, contextbar
        page = sketchtoolpm.current()
        if page is not None:
            try:
                from .fwsketch import hints
                if hints._prompt.get("text"):
                    # a sketch tool with its own prompt is running (3 Point Corner Rectangle, Spline):

                    return hints._prompt["text"]
            except Exception as _fw_err:
                _fw_log("pmprompts.py:tool prompt", _fw_err)
            t = getattr(page, "TITLE", "")
            kind = getattr(page, "kind_type", None) or getattr(page, "kind", None)
            try:
                from .fwsketch import toolbase
                running = toolbase.active()
                if running is not None and running.title() in DRAW_TYPES:
                    kind = running.title()
            except Exception as _fw_err:
                _fw_log("pmprompts.py:tool title", _fw_err)
            return (SKETCH_TOOLS.get(t) or (DRAW_TYPES.get(kind) if isinstance(kind, str) else None)
                    or DRAW_PAGES.get(t) or _generic(t))
        if contextbar.sketch_in_edit() is not None:
            return SKETCH_IDLE
    except Exception as _fw_err:
        _fw_log("pmprompts.py:145", _fw_err)
    return None


def graphics_section():
    """A graphics-only section is cutting the view now (Measure warns that it measures the whole model)."""
    try:
        from . import sectionview
        c = sectionview._controller
        return c is not None and c.active() and bool(getattr(c.settings, "graphics_only", False))
    except Exception:
        return False


TASK_TOOLS = (("dfmxpress", "Set the rules with Settings, then click Run in the Task Pane"),
              ("sustainability", "Pick the material and how and where it is made in the Task Pane"),
              ("costing", "Set the material, method and quantity in the Task Pane to see the cost"))
OURS = OURS + tuple(t for _m, t in TASK_TOOLS)


def _task_tool():
    """a42: Manufacturability Check, Sustainability and Costing open on the Task Pane: their prompt."""
    import sys
    for mod, text in TASK_TOOLS:
        m = sys.modules.get("%s.%s" % (__package__, mod))
        st = getattr(m, "_state", None) if m is not None else None
        if not isinstance(st, dict):
            continue
        for key in ("page", "dock"):
            w = st.get(key)
            try:
                if w is not None and w.isVisible():
                    return text
            except RuntimeError as _fw_err:
                _fw_log("pmprompts.py:179", _fw_err)
    return None


def prompt():
    """The prompt for the page open now, or None."""
    if _section_open():
        return SECTION
    sketch = _sketch_prompt()
    if sketch is not None:
        if sketch == SKETCH_IDLE:
            try:
                from . import contextbar, sketchtoolpm
                shell = sketchtoolpm._shell()
                if shell is not None and contextbar.tool_running(shell):
                    return None     # a drawing tool keeps its own hints
            except Exception as _fw_err:
                _fw_log("pmprompts.py:196", _fw_err)
        return sketch
    if not Gui.Control.activeDialog():
        try:
            return (_task_tool() or IDLE) if App.ActiveDocument is not None else None
        except Exception:
            return None
    mw = Gui.getMainWindow()
    title = ""
    try:
        from . import propertymanager
        views = [w for w in _task_views(mw) if w.isVisible()]
        if views:
            title = propertymanager._title(views[0])[0]
    except Exception:
        title = ""
    if title == "Fillet":
        items = _shown(mw, "SWFilletItems")
        return FILLET if items is not None and items.count() else FILLET_EMPTY
    if title in SWEEP_TITLES:
        profile = _shown(mw, "SWStyle_SweepProfile") or _shown(mw, "SWStyle_Profile")
        path = _shown(mw, "SWStyle_SweepPath") or _shown(mw, "SWStyle_Path")
        if profile is not None and not profile.count():
            return SWEEP[0]
        if path is not None and not path.count():
            return SWEEP[1]
        return SWEEP[2]
    if title in PICK_FIRST and views and _only_message(views[0]):      # pkg439: the page still waits for its first pick
        return PICK_FIRST[title]
    light = mw.findChild(QtWidgets.QWidget, "SWLightProperties")
    if light is not None and light.isVisible():      # a light's page: "Point1" is a point light, not Point
        return _generic(title)

    if title in ASM_PAGES:
        try:
            from . import asmcore
            if asmcore.is_assembly(App.ActiveDocument):
                return ASM_PAGES[title]
        except Exception as _fw_err:
            _fw_log("pmprompts:asm", _fw_err)
    return PAGES.get(title) or PAGES.get((title or "").rstrip("0123456789")) or _generic(title)


def _ours(text):
    return text in OURS or text == _state.get("last")


def _stale_note(text):
    """fix293: the note a tool left when it could not start in this sketch ("Plane: Open a 3D sketch first.")
    stayed under the next sketch tool's page; once a sketch tool page is open, its prompt may write over it."""
    try:
        from . import toolfirst, sketchtoolpm
        return text == toolfirst._said.get("text") and sketchtoolpm.current() is not None
    except Exception:
        return False


def _tips():
    ""

    try:
        mw = Gui.getMainWindow()
        try:
            from . import ribbon
            pages = [w for w in mw.findChildren(QtWidgets.QWidget) if isinstance(w, (ribbon.RibbonPage, ribbon.QatRow))]
        except Exception:
            pages = []
        found = list(mw.findChildren(QtWidgets.QToolButton))
        for page in pages:
            found += [w for w in page.findChildren(QtWidgets.QWidget) if w.toolTip()]
        for b in found:
            if b.statusTip() or not b.isVisible():
                continue
            a = b.defaultAction() if isinstance(b, QtWidgets.QToolButton) else None
            tip = (a.statusTip() or a.toolTip()) if a is not None else b.toolTip()
            lines = [x.strip() for x in (tip or "").replace("<br>", "\n").replace("<br/>", "\n").splitlines() if x.strip()]

            line = lines[1] if len(lines) > 1 and lines[0].startswith("<b>") else (lines[0] if lines else "")
            if "<" in line:
                import re
                line = re.sub(r"<[^>]+>", "", line).strip()
            if line and line != (b.text() if hasattr(b, "text") else ""):
                b.setStatusTip(line)
    except Exception as _fw_err:
        _fw_log("pmprompts.py:257", _fw_err)


def _tick():
    _state["n"] = _state.get("n", 0) + 1
    if _state["n"] % 10 == 1:
        _tips()
    try:
        bar = Gui.getMainWindow().statusBar()
        now = bar.currentMessage()
        try:
            from . import statusmsg     # statusbar-1119
            if statusmsg.busy():      # FreeCAD's own line (the item under the pointer) is showing: one line only
                if now and _ours(now):
                    bar.clearMessage()
                return
        except Exception as _fw_err:
            _fw_log("pmprompts.py:statusmsg", _fw_err)
        want = prompt()
        if want:
            if now != want and (not now or _ours(now) or _stale_note(now)):
                bar.showMessage(want, 0)
                _state["last"] = want
        elif now and _ours(now):
            bar.clearMessage()
    except Exception as _fw_err:
        _fw_log("pmprompts.py:275", _fw_err)


def install():
    if Gui is None or _state["timer"] is not None:
        return
    t = QtCore.QTimer()
    t.setInterval(400)
    t.timeout.connect(_tick)
    t.start()
    try:
        from . import ticks as _ticks
        _ticks.slow_when_idle(t)
    except Exception as _fw_err:
        __import__("FreeCAD").Console.PrintLog("FreeCAD ticks: %s\n" % _fw_err)
    _state["timer"] = t


def _task_views(mw):
    """FreeCAD's task view widgets, found once and kept while they live (the prompt timer asks every 400 ms)."""
    kept = _state.get("views") or []
    try:
        for w in kept:
            w.objectName()
        if kept:
            return kept
    except RuntimeError as _fw_err:
        _fw_log("pmprompts.py:297", _fw_err)
    kept = [w for w in mw.findChildren(QtWidgets.QWidget) if w.metaObject().className() == "Gui::TaskView::TaskView"]
    _state["views"] = kept
    return kept
