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


import math

import FreeCAD as App

LINEAR, FORESHORTEN = "DisplayAsLinear", "Foreshorten"
T_LINEAR, T_FORESHORTEN = "Display As Linear", "Foreshorten"
JOG_NODE = "FWDimJogs"
painted = {}            # {constraint index: "linear" | "foreshorten"} of the last paint, for checks


def _rcx():
    from . import rcextras
    return rcextras


def _rc():
    from . import rcmenus
    return rcmenus


def flag(sketch, index, name):
    try:
        return _rcx().display_flag(sketch, index, name)
    except Exception:
        return False


def _set_flag(sketch, index, name, on):
    """Inside a history step: the flag on or off (the dimension gets its stable name first)."""
    x = _rcx()
    key = "%s:%s" % (_rc().stable_key(sketch, index), name)
    now = x._flags(sketch, x.DISPLAY_PROP)
    if on and key not in now:
        x._set_flags(sketch, x.DISPLAY_PROP, now + [key])
    elif not on and key in now:
        x._set_flags(sketch, x.DISPLAY_PROP, [k for k in now if k != key])


def set_kind(sketch, index, kind):
    """Display As Radius / Diameter / Linear, as one history step. Linear on a radius makes it a diameter first."""
    import Sketcher
    rc = _rc()
    c = sketch.Constraints[index]
    want = "Diameter" if kind == "Linear" else kind
    text = {"Radius": rc.T_AS_RADIUS, "Diameter": rc.T_AS_DIAMETER, "Linear": T_LINEAR}[kind]
    if c.Type == want and flag(sketch, index, LINEAR) == (kind == "Linear"):
        return          # already shown that way: no history step

    def body():
        at = index
        if c.Type != want:
            value = c.Value * 2.0 if want == "Diameter" else c.Value / 2.0
            name = rc.stable_key(sketch, index)
            driving = sketch.getDriving(index)
            sketch.delConstraint(index)
            at = sketch.addConstraint(Sketcher.Constraint(want, c.First, value))
            sketch.renameConstraint(at, name)
            if not driving:
                sketch.setDriving(at, False)
        _set_flag(sketch, at, LINEAR, kind == "Linear")
    rc._sketch_transaction(sketch, text, body)


def toggle_linear(sketch, index):
    set_kind(sketch, index, "Diameter" if flag(sketch, index, LINEAR) else "Linear")


def toggle_foreshorten(sketch, index):
    on = not flag(sketch, index, FORESHORTEN)
    _rc()._sketch_transaction(sketch, T_FORESHORTEN, lambda: _set_flag(sketch, index, FORESHORTEN, on))


def display_options(sketch, index, items):
    ""
    rc = _rc()
    try:
        c = sketch.Constraints[index]
    except Exception:
        return items
    if c.Type not in ("Radius", "Diameter"):
        return items
    out = list(items)
    at = next((k for k, it in enumerate(out) if getattr(it, "key", "") == "DisplayAsDiameter"), None)
    if at is not None:
        other = "Radius" if c.Type == "Diameter" else "Diameter"
        out[at].run = lambda: set_kind(sketch, index, other)
        if c.Type == "Diameter":
            out.insert(at + 1, rc.action(LINEAR, T_LINEAR, lambda: toggle_linear(sketch, index),
                                         checked=flag(sketch, index, LINEAR)))
    fore = rc.action(FORESHORTEN, T_FORESHORTEN, lambda: toggle_foreshorten(sketch, index),
                     checked=flag(sketch, index, FORESHORTEN))
    at = next((k for k, it in enumerate(out) if getattr(it, "key", "") == "ShowAsInspection"), len(out))
    out.insert(at, fore)
    return out


def icon_row(sketch, index, out, pressed, icon, tip):
    """The radius / diameter / linear icon set over a radius or diameter dimension."""
    from . import contextbar
    rc = _rc()
    linear = flag(sketch, index, LINEAR) and sketch.Constraints[index].Type == "Diameter"
    for e in out:
        if e.key == "DisplayAsRadius":
            e.run = lambda: set_kind(sketch, index, "Radius")
        elif e.key == "DisplayAsDiameter":
            e.run = lambda: set_kind(sketch, index, "Diameter")
    out = list(out) + [contextbar.Entry("DisplayAsLinear", T_LINEAR, icon(T_LINEAR, "DIMENSIONS_LINEAR", "DIMENSIONS_HORIZ"),
                                        tip(T_LINEAR), lambda: set_kind(sketch, index, "Linear"))]
    if linear:
        pressed = (set(pressed) - {"DisplayAsDiameter"}) | {"DisplayAsLinear"}
    return out, pressed


# --- drawing ------------------------------------------------------------------------------------------
def _parent_and_group(view):
    from pivy import coin
    sa = coin.SoSearchAction()
    sa.setName("ConstraintGroup")
    sa.setInterest(coin.SoSearchAction.FIRST)
    sa.apply(view.getSceneGraph())
    path = sa.getPath()
    if path is None or path.getLength() < 2:
        return None, None
    return path.getNodeFromTail(1), path.getTail()


def _drop_jogs(parent):
    for k in range(parent.getNumChildren() - 1, -1, -1):
        try:
            if parent.getChild(k).getName().getString() == JOG_NODE:
                parent.removeChild(k)
        except Exception as _fw_err:
            _fw_log("dimdisplay.py:drop", _fw_err)


def _pixel(view):
    """Model length of one screen pixel (the sketch faces the screen while it is edited)."""
    try:
        a, b = view.getPoint(0, 0), view.getPoint(100, 0)
        return max((a - b).Length / 100.0, 1e-9)
    except Exception:
        return 0.05


def _zigzag(j, d, px):
    ""
    n = (-d[1], d[0])
    step, side = 5.0 * px, 6.0 * px
    return [(j[0], j[1]),
            (j[0] - d[0] * step + n[0] * side, j[1] - d[1] * step + n[1] * side),
            (j[0] - d[0] * 2 * step - n[0] * side, j[1] - d[1] * 2 * step - n[1] * side),
            (j[0] - d[0] * 3 * step, j[1] - d[1] * 3 * step)]


def paint(view, sketch):
    """Reshapes FreeCAD's label of each flagged radius or diameter dimension (after each redraw)."""
    painted.clear()
    parent, group = _parent_and_group(view)
    if parent is None:
        return painted
    _drop_jogs(parent)
    x = _rcx()
    flags = x._flags(sketch, x.DISPLAY_PROP)
    if not any(f.endswith(":" + LINEAR) or f.endswith(":" + FORESHORTEN) for f in flags):
        return painted
    rc = _rc()
    px = _pixel(view)
    jogs, z = [], 0.0
    for i, c in enumerate(sketch.Constraints):
        if c.Type not in ("Radius", "Diameter") or i >= group.getNumChildren():
            continue
        key = rc._mark_key(sketch, i) + ":"
        linear = c.Type == "Diameter" and key + LINEAR in flags
        fore = key + FORESHORTEN in flags
        if not (linear or fore):
            continue
        sep = group.getChild(i)
        try:
            if sep.getNumChildren() < 1 or sep.getChild(0).getTypeId().getName().getString() != "SoDatumLabel":
                continue
            label = sep.getChild(0)
            if label.pnts.getNum() < 2:
                continue
            p0, p1 = tuple(label.pnts[0]), tuple(label.pnts[1])
            length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if length < 1e-9:
                continue
            d = ((p1[0] - p0[0]) / length, (p1[1] - p0[1]) / length)
            z = p0[2]
            if linear:
                label.set("datumtype DISTANCE")
                label.param1.setValue(0.5 * length + max(0.2 * length, 25 * px))
                label.param2.setValue(0.0)
                painted[i] = "linear"
                continue
            if c.Type == "Radius":
                keep = min(0.6 * length, 60 * px)
                j = (p1[0] - d[0] * keep, p1[1] - d[1] * keep)
            else:
                label.set("datumtype RADIUS")
                past = min(0.25 * length, 25 * px)
                m = (0.5 * (p0[0] + p1[0]), 0.5 * (p0[1] + p1[1]))
                j = (m[0] - d[0] * past, m[1] - d[1] * past)
            label.pnts.set1Value(0, j[0], j[1], z)
            jogs.append((_zigzag(j, d, px), tuple(label.textColor.getValue()), label.lineWidth.getValue()))
            painted[i] = "foreshorten"
        except Exception as _fw_err:
            _fw_log("dimdisplay.py:paint", _fw_err)
    if jogs:
        from pivy import coin
        node = coin.SoSeparator()
        node.setName(JOG_NODE)
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        node.addChild(pick)
        node.addChild(light)
        for jog, colour, width in jogs:        # each in its dimension's colour (picked, clashing ...)
            sep = coin.SoSeparator()
            col = coin.SoBaseColor()
            col.rgb = colour
            style = coin.SoDrawStyle()
            style.lineWidth = width
            co = coin.SoCoordinate3()
            co.point.setValues(0, len(jog), [(p[0], p[1], z) for p in jog])
            ls = coin.SoLineSet()
            ls.numVertices.setValue(len(jog))
            for n in (col, style, co, ls):
                sep.addChild(n)
            node.addChild(sep)
        parent.addChild(node)
    return painted
