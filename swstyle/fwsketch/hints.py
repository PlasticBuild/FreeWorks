"""The tool hints in the status bar (FreeCAD 1.1's InputHintWidget: Gui.InputHint and
Gui.getMainWindow().showHint, stock API), the same lines the C++ DrawSketchHandlers show
(DrawSketchHandlerLine.h, ...Circle.h, ...Arc.h, ...Rectangle.h, ...Slot.h, ...ArcSlot.h,
...Polygon.h, ...Trimming.h getToolHints), per tool title and state. A FreeCAD without the API
(older than 1.1) shows nothing."""

_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import FreeCADGui as Gui

LEFT, MOVE, M, U, J, ESC = "MouseLeft", "MouseMove", "KeyM", "KeyU", "KeyJ", "KeyEscape"

PICK = lambda what: ("%%1 pick %s" % what, LEFT)
SIDES = ("%1/%2 increase / decrease number of sides", U, J)

HINTS = {
    "Line": [[PICK("first point")], [PICK("second point")]],
    "Midpoint Line": [[PICK("middle point")], [PICK("end point")]],
    "Tangent Arc": [[PICK("arc start point")], [PICK("arc end point")]],
    "Centerpoint Arc": [[PICK("arc center")], [PICK("arc start point")], [PICK("arc end point")]],
    "3 Point Arc": [[PICK("first arc point")], [PICK("second arc point")], [PICK("third arc point")]],
    "Circle": [[PICK("circle center")], [PICK("rim point")]],
    "Perimeter Circle": [[PICK("first rim point")], [PICK("second rim point")], [PICK("third rim point")]],
    "Corner Rectangle": [[PICK("first corner")], [PICK("opposite corner")]],
    "Center Rectangle": [[PICK("center")], [PICK("corner")]],
    "3 Point Corner Rectangle": [[PICK("first corner")], [PICK("second corner")], [PICK("width")]],
    "3 Point Center Rectangle": [[PICK("center")], [PICK("middle of a side")], [PICK("corner")]],
    "Parallelogram": [[PICK("first corner")], [PICK("second corner")], [PICK("third corner")]],
    "Straight Slot": [[PICK("slot start point")], [PICK("slot end point")], [PICK("slot width")]],
    "Centerpoint Straight Slot": [[PICK("slot center")], [PICK("slot end point")], [PICK("slot width")]],
    "Centerpoint Arc Slot": [[PICK("slot center")], [PICK("slot radius")], [PICK("slot angle")], [PICK("slot width")]],
    "Flat Ends Arc Slot": [[PICK("slot center")], [PICK("slot radius")], [PICK("slot angle")], [PICK("slot width")]],
    "3 Point Arc Slot": [[PICK("first arc point")], [PICK("second arc point")], [PICK("third arc point")],
                         [PICK("slot width")]],
    "Polygon": [[PICK("polygon center"), SIDES],
                [("%1 pick rotation and size", MOVE), ("%1 confirm", LEFT), SIDES]],
    "Point": [[PICK("point position"), ("%1 done", ESC)]],
    "Ellipse": [[PICK("ellipse center")], [PICK("first axis")], [PICK("second axis")]],
    "Partial Ellipse": [[PICK("ellipse center")], [PICK("first axis")], [PICK("second axis and arc start")],
                        [PICK("arc end")]],
    "Trim Entities": [[PICK("edge to trim")]],
    "Extend Entities": [[PICK("a line or arc to extend"), ("%1 done", ESC)]],
    "Spline": [[PICK("first spline point")],
               [PICK("next spline point"), ("%1/%2 end the spline (double-click)", LEFT, ESC)]],
    "Style Spline": [[PICK("first control vertex")],
                     [PICK("next control vertex"), ("%1/%2 end the style spline (double-click)", LEFT, ESC)]],
    "Insert Spline Point": [[PICK("a spline where the new point goes"), ("%1 done", ESC)]],
    "Simplify Spline": [[PICK("a spline")]],
    "Relax Spline": [[PICK("a spline")]],
    "Proportional": [[PICK("a spline")]],
    "Show Curvature Combs": [[PICK("a spline")]],
    "Show Inflection Points": [[PICK("a spline")]],
    "Show Minimum Radius": [[PICK("a spline")]],
    "Smart Dimension": [[PICK("an element to dimension")],
                        [PICK("a second element or place the dimension"), ("%1 switch kind", M)],
                        [("%1 place the dimension", LEFT), ("%1 switch kind", M)]],
}





# status bar or one of its own prompts, so it never covers another message.
PROMPTS = {
    "3 Point Corner Rectangle": "Click first, second and then third corner to complete.",
    "Parallelogram": "Click first, second and then third corner to complete.",
    "3 Point Center Rectangle": "Click the center, the middle of a side and then a corner to complete.",

    # video: once the spline has its first point
    "Spline": (None, "Double click to end the spline at the cursor or escape to end it at the last point"),
}
_prompt = {"text": "", "timer": None}


def _bar():
    try:
        return Gui.getMainWindow().statusBar()
    except Exception:
        return None


def _write_prompt():
    bar = _bar()
    text = _prompt["text"]
    if bar is None or not text:
        return
    try:
        if bar.currentMessage() in ("", text):
            if bar.currentMessage() != text:
                bar.showMessage(text)
    except RuntimeError as _fw_err:
        _fw_log("fwsketch/hints.py:101", _fw_err)


def show_prompt(title, state=0):
    """The tool's status bar prompt (PROMPTS), kept up while the tool runs."""
    text = PROMPTS.get(title, "")
    if isinstance(text, tuple):
        text = text[min(max(int(state), 0), len(text) - 1)] if text else ""
    text = text or ""
    if text == _prompt["text"]:
        return
    clear_prompt()
    if not text:
        return
    _prompt["text"] = text
    try:
        from PySide import QtCore
        timer = QtCore.QTimer()
        timer.setInterval(400)
        timer.timeout.connect(_write_prompt)
        timer.start()
        _prompt["timer"] = timer
    except Exception as _fw_err:
        _fw_log("fwsketch/hints.py:124", _fw_err)
    _write_prompt()


def clear_prompt():
    text, timer = _prompt["text"], _prompt["timer"]
    _prompt["text"], _prompt["timer"] = "", None
    if timer is not None:
        try:
            timer.stop()
        except RuntimeError as _fw_err:
            _fw_log("fwsketch/hints.py:135", _fw_err)
    bar = _bar()
    if bar is not None and text:
        try:
            if bar.currentMessage() == text:
                bar.clearMessage()
        except RuntimeError as _fw_err:
            _fw_log("fwsketch/hints.py:142", _fw_err)


def available():
    return hasattr(Gui, "InputHint") and hasattr(Gui, "UserInput") and hasattr(Gui.getMainWindow(), "showHint")


def lines(title, state):
    """The (message, input names...) tuples for a tool title in a state (the last state's when
    the state runs past the table), [] for an unknown title."""
    table = HINTS.get(title) or []
    if not table:
        return []
    return list(table[min(max(int(state), 0), len(table) - 1)])


def to_hints(entries):
    out = []
    for message, *inputs in entries:
        keys = [getattr(Gui.UserInput, name) for name in inputs]
        out.append(Gui.InputHint(message, *keys))
    return out


def show(title, state):
    """Show the tool's hints for this state; True when something was shown."""
    show_prompt(title, state)
    if not available():
        return False
    entries = lines(title, state)
    try:
        if entries:
            Gui.getMainWindow().showHint(*to_hints(entries))
        else:
            Gui.getMainWindow().hideHint()
    except Exception:
        return False
    return bool(entries)


def hide():
    clear_prompt()
    if not available():
        return
    try:
        Gui.getMainWindow().hideHint()
    except Exception as _fw_err:
        _fw_log("fwsketch/hints.py:189", _fw_err)
