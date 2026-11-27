# SPDX-License-Identifier: LGPL-2.1-or-later
""









_FW_SEEN = set()


def _fw_log(site, err):
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return


import re

import FreeCAD as App

DIMS = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle")
SIGMA = "Σ"
DIAMETER = "Ø"
_MARK = re.compile(r"\s*\(\s*ƒ\s*\U0001D465\s*\)|\s*\(\s*ƒx\s*\)")
_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
painted = {}            # {constraint index: text} written on the last pass, for checks


def decimals():
    try:
        return max(0, App.ParamGet("User parameter:BaseApp/Preferences/Units").GetInt("Decimals", 2))
    except Exception:
        return 2


def _driven_by_expression(sketch):
    out = set()
    try:
        names = {c.Name: i for i, c in enumerate(sketch.Constraints) if c.Name}
        for path, _expr in sketch.ExpressionEngine:
            m = re.match(r"\.?Constraints\[(\d+)\]$", path)
            if m:
                out.add(int(m.group(1)))
                continue
            m = re.match(r"\.?Constraints\.(.+)$", path)
            if m and m.group(1) in names:
                out.add(names[m.group(1)])
    except Exception as _fw_err:
        _fw_log("dimtext.py:expressions", _fw_err)
    return out


def text_for(old, kind, equation, places=None):
    ""
    if not old or "=" in old:
        return ""          # FreeCAD's "name = value" display: the user asked for names
    new = old
    if equation or _MARK.search(new):
        new = _MARK.sub("", new)
        places = decimals() if places is None else places
        m = _NUMBER.search(new)
        if m is not None:
            try:
                value = float(m.group(0).replace(",", "."))
                new = new[:m.start()] + ("%.*f" % (places, value)) + new[m.end():]
            except ValueError:
                pass
        if not new.lstrip("(").startswith(SIGMA):
            lead = "(" if new.startswith("(") else ""
            new = lead + SIGMA + new[len(lead):]
    if kind == "Diameter":
        new = new.replace("⌀", DIAMETER)
    return new if new != old else ""


def paint(view, sketch):
    painted.clear()
    try:
        from . import dimdisplay
        _parent, group = dimdisplay._parent_and_group(view)
    except Exception as _fw_err:
        _fw_log("dimtext.py:group", _fw_err)
        return painted
    if group is None:
        return painted
    eq = _driven_by_expression(sketch)
    places = decimals()
    for i, c in enumerate(sketch.Constraints):
        if c.Type not in DIMS or i >= group.getNumChildren():
            continue
        try:
            sep = group.getChild(i)
            if sep.getNumChildren() < 1:
                continue
            label = sep.getChild(0)
            if label.getTypeId().getName().getString() != "SoDatumLabel":
                continue
            old = label.string.getValues()[0] if label.string.getNum() else ""
            old = getattr(old, "getString", lambda: str(old))()
            new = text_for(old, c.Type, i in eq, places)
            if new:
                label.string.setValue(new)
                painted[i] = new
        except Exception as _fw_err:
            _fw_log("dimtext.py:label", _fw_err)
    return painted


_DONE = []


def install():
    """Runs after dimdisplay.paint, which fwsketch/glyphs.paint calls after each redraw of an open sketch."""
    if _DONE:
        return
    _DONE.append(True)
    from . import dimdisplay
    paint0 = dimdisplay.paint

    def paint_then_text(view, sketch, *a, **k):
        try:
            return paint0(view, sketch, *a, **k)
        finally:
            try:
                paint(view, sketch)
            except Exception as _fw_err:
                _fw_log("dimtext.py:paint", _fw_err)
    paint_then_text.__wrapped__ = paint0
    dimdisplay.paint = paint_then_text
