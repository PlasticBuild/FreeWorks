# -*- coding: utf-8 -*-
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


import math

import FreeCAD as App
from . import geomkeep

V = App.Vector
EDGE, START, END, MID = 0, 1, 2, 3


def _parse(text):
    t = (text or "").strip().replace(",", ".")
    for unit in ("mm", "°", "deg"):
        t = t.replace(unit, "")
    return float(t.strip())


def last_group(tool, sketch):
    """The geo ids of the tool's last placement that are still in the sketch, else []."""
    groups = getattr(tool, "placements", None) or []
    n = len(sketch.Geometry)
    for ids in reversed(groups):
        ids = [g for g in ids if 0 <= g < n]
        if ids:
            return ids
    return []


def _type(geo):
    return type(geo).__name__


def _of(sketch, ids, name, construction=None):
    out = []
    for g in ids:
        if _type(sketch.Geometry[g]) != name:
            continue
        if construction is not None and bool(sketch.getConstruction(g)) != construction:
            continue
        out.append(g)
    return out


def _arc_angles(geo):
    a0, a1 = geo.FirstParameter, geo.LastParameter
    return a0, a1


# --------------------------------------------------------------------------- reading
def read(kind, sketch, ids):
    """The Parameters of the placed entity, by key, or {}."""
    G = sketch.Geometry
    try:
        if kind == "point":
            p = _of(sketch, ids, "Point")
            return {"x": G[p[-1]].X, "y": G[p[-1]].Y} if p else {}
        if kind == "circle":
            c = _of(sketch, ids, "Circle")
            if not c:
                return {}
            g = G[c[-1]]
            return {"cx": g.Center.x, "cy": g.Center.y, "radius": g.Radius}
        if kind == "arc":
            a = _of(sketch, ids, "ArcOfCircle")
            if not a:
                return {}
            g = G[a[-1]]
            a0, a1 = _arc_angles(g)
            return {"cx": g.Center.x, "cy": g.Center.y, "sx": g.StartPoint.x, "sy": g.StartPoint.y,
                    "ex": g.EndPoint.x, "ey": g.EndPoint.y, "radius": g.Radius, "angle": a1 - a0}
        if kind == "ellipse":
            e = _of(sketch, ids, "ArcOfEllipse") or _of(sketch, ids, "Ellipse")
            if not e:
                return {}
            g = G[e[-1]]
            ell = g if _type(g) == "Ellipse" else g.Ellipse
            ax = ell.MajorAxis if hasattr(ell, "MajorAxis") else (ell.XAxis)
            out = {"cx": ell.Center.x, "cy": ell.Center.y, "a": ell.MajorRadius, "b": ell.MinorRadius,
                   "phi": math.degrees(math.atan2(ax.y, ax.x)) % 360.0}
            if _type(g) == "ArcOfEllipse":
                out["sweep"] = math.degrees(abs(g.LastParameter - g.FirstParameter))
            return out
        if kind == "slot":
            caps = _caps(sketch, ids)
            if len(caps) < 2:
                return {}
            c1, c2 = G[caps[0]].Center, G[caps[1]].Center
            return {"sx": c1.x, "sy": c1.y, "ex": c2.x, "ey": c2.y, "length": (c2 - c1).Length,
                    "width": 2.0 * G[caps[0]].Radius}
        if kind == "rect":
            sides = _of(sketch, ids, "LineSegment", False)[:4]
            if len(sides) < 4:
                return {}
            out = {}
            for i, s in enumerate(sides):
                p = G[s].StartPoint
                out["x%d" % (i + 1)], out["y%d" % (i + 1)] = p.x, p.y
            c = _rect_centre(sketch, ids, sides)
            out["cx"], out["cy"] = c.x, c.y
            return out
        if kind == "polygon":
            circle = _of(sketch, ids, "Circle", True)
            lines = _of(sketch, ids, "LineSegment")
            if not circle or not lines:
                return {}
            g = G[circle[-1]]
            v = G[lines[0]].StartPoint - g.Center
            return {"cx": g.Center.x, "cy": g.Center.y, "diameter": 2.0 * g.Radius,
                    "angle": math.degrees(math.atan2(v.y, v.x))}
    except Exception:
        return {}
    return {}


def _caps(sketch, ids):
    arcs = _of(sketch, ids, "ArcOfCircle", False)
    arcs.sort(key=lambda g: sketch.Geometry[g].Radius)
    caps = arcs[:2]
    caps.sort()
    return caps


def _rect_centre(sketch, ids, sides):
    pts = _of(sketch, ids, "Point")
    if pts:
        p = sketch.Geometry[pts[-1]]
        return V(p.X, p.Y, 0)
    c = V()
    for s in sides:
        c = c + sketch.Geometry[s].StartPoint
    return c * 0.25


# --------------------------------------------------------------------------- writing
def _solve_with(sketch, extra):
    """_try_with, and again without the pins that hold a coordinate where it already is (a
    relation may hold it there already: an end on an axis, a centre on the origin)."""
    if _try_with(sketch, extra):
        return True
    keep = []
    for a in extra:
        if a[0] in ("DistanceX", "DistanceY") and len(a) == 4:
            p = sketch.getPoint(a[1], a[2])
            now = p.x if a[0] == "DistanceX" else p.y
            if abs(now - a[3]) < 1e-7:
                continue
        keep.append(a)
    if len(keep) == len(extra) or not keep:
        return False
    return _try_with(sketch, keep)


def _try_with(sketch, extra):
    """Solve the sketch with the temporary constraints extra, then take them off: the geometry
    stays where the solver put it and keeps its own relations. False (nothing changed) when the
    sketch cannot take them (a dimension already holds that value)."""
    import Sketcher
    saved = [g.clone() for g in geomkeep.read(sketch)]
    n = len(sketch.Constraints)
    try:
        sketch.addConstraint([Sketcher.Constraint(*a) for a in extra])
        r = sketch.solve()
    except Exception:
        r = -1
    for k in range(len(sketch.Constraints) - 1, n - 1, -1):
        sketch.delConstraint(k)
    if r != 0:
        sketch.Geometry = saved
    sketch.solve()
    return r == 0


def _pins(points):
    out = []
    for geo, pos, x, y in points:
        out += [("DistanceX", geo, pos, float(x)), ("DistanceY", geo, pos, float(y))]
    return out


def _move(sketch, geo, pos, x, y):
    return _solve_with(sketch, _pins([(geo, pos, x, y)]))


def _set_radius(sketch, geo, r):
    """A circle's or arc's radius (its centre stays put when it can)."""
    if r <= 1e-9:
        return False
    c = sketch.Geometry[geo].Center
    return (_solve_with(sketch, [("Radius", geo, float(r))] + _pins([(geo, MID, c.x, c.y)]))
            or _solve_with(sketch, [("Radius", geo, float(r))]))


def write(kind, sketch, ids, key, value, values=None):
    """Type value into box key of the placed entity ids; returns True when it changed."""
    G = geomkeep.read(sketch)
    vals = values if values is not None else read(kind, sketch, ids)
    if not vals:
        return False
    if kind == "point":
        p = _of(sketch, ids, "Point")[-1]
        x, y = (value, vals["y"]) if key == "x" else (vals["x"], value)
        return _move(sketch, p, START, x, y)
    if kind == "circle":
        c = _of(sketch, ids, "Circle")[-1]
        if key == "radius":
            return _set_radius(sketch, c, value)
        x, y = (value, vals["cy"]) if key == "cx" else (vals["cx"], value)
        return _move(sketch, c, MID, x, y)
    if kind == "arc":
        a = _of(sketch, ids, "ArcOfCircle")[-1]
        if key in ("cx", "cy"):
            x, y = (value, vals["cy"]) if key == "cx" else (vals["cx"], value)
            return _move(sketch, a, MID, x, y)
        if key in ("sx", "sy"):
            x, y = (value, vals["sy"]) if key == "sx" else (vals["sx"], value)
            return _move(sketch, a, START, x, y)
        if key in ("ex", "ey"):
            x, y = (value, vals["ey"]) if key == "ex" else (vals["ex"], value)
            return _move(sketch, a, END, x, y)
        if key == "radius":
            return _set_radius(sketch, a, value)
        if key == "angle":
            g = G[a]
            if not 0.0 < value < 360.0:
                return False
            # the start and the centre stay, the end goes round
            return (_solve_with(sketch, [("Angle", a, math.radians(value))] +
                                _pins([(a, MID, g.Center.x, g.Center.y), (a, START, g.StartPoint.x, g.StartPoint.y)])[:3])
                    or _solve_with(sketch, [("Angle", a, math.radians(value))]))
        return False
    if kind == "ellipse":
        e = (_of(sketch, ids, "ArcOfEllipse") or _of(sketch, ids, "Ellipse"))[-1]
        if key in ("cx", "cy"):
            x, y = (value, vals["cy"]) if key == "cx" else (vals["cx"], value)
            return _move(sketch, e, MID, x, y)
        geos = list(G)
        g = geos[e].clone()
        ell = g if _type(g) == "Ellipse" else g.Ellipse
        a, b, phi = vals["a"], vals["b"], math.radians(vals["phi"])
        if key == "a":
            a = value
        elif key == "b":
            b = value
        elif key == "phi":
            phi = math.radians(value)
        elif key == "sweep" and _type(g) == "ArcOfEllipse":
            a0 = g.FirstParameter
            return _move(sketch, e, END, *_ellipse_at(ell, a0 + math.radians(value)))
        else:
            return False
        if b > a or b <= 1e-9:
            return False
        import Part
        c = ell.Center
        new = Part.Ellipse(c + V(math.cos(phi), math.sin(phi), 0) * a,
                           c + V(-math.sin(phi), math.cos(phi), 0) * b, c)
        if _type(g) == "ArcOfEllipse":
            new = Part.ArcOfEllipse(new, g.FirstParameter, g.LastParameter)
        geos[e] = geomkeep.like(geos[e], new)
        sketch.Geometry = geos
        sketch.solve()
        return True
    if kind == "slot":
        caps = _caps(sketch, ids)
        c1, c2 = G[caps[0]].Center, G[caps[1]].Center
        if key in ("sx", "sy"):
            x, y = (value, vals["sy"]) if key == "sx" else (vals["sx"], value)
            return _move(sketch, caps[0], MID, x, y)
        if key in ("ex", "ey"):
            x, y = (value, vals["ey"]) if key == "ex" else (vals["ex"], value)
            return _move(sketch, caps[1], MID, x, y)
        if key == "length":
            d = c2 - c1
            if d.Length < 1e-9 or value <= 1e-9:
                return False
            p = c1 + d * (value / d.Length)
            return (_solve_with(sketch, _pins([(caps[1], MID, p.x, p.y), (caps[0], MID, c1.x, c1.y)]))
                    or _move(sketch, caps[1], MID, p.x, p.y))
        if key == "width":
            return _set_radius(sketch, caps[0], 0.5 * value)
        return False
    if kind == "rect":
        sides = _of(sketch, ids, "LineSegment", False)[:4]
        if key in ("cx", "cy"):
            c = _rect_centre(sketch, ids, sides)
            dx, dy = (value - c.x, 0.0) if key == "cx" else (0.0, value - c.y)
            def corner(i):
                p = G[sides[i]].StartPoint
                return (sides[i], START, p.x + dx, p.y + dy)
            # the whole rectangle moves (relations kept): three corners pinned, or two
            # across for one held square by Horizontal and Vertical
            return (_solve_with(sketch, _pins([corner(0), corner(1), corner(2)]))
                    or _solve_with(sketch, _pins([corner(0), corner(2)])))
        i = int(key[1:]) - 1
        p = G[sides[i]].StartPoint
        q = G[sides[(i + 2) % 4]].StartPoint
        x, y = (value, p.y) if key[0] == "x" else (p.x, value)
        # the opposite corner stays where it is
        return (_solve_with(sketch, _pins([(sides[i], START, x, y), (sides[(i + 2) % 4], START, q.x, q.y)]))
                or _move(sketch, sides[i], START, x, y))
    if kind == "polygon":
        circle = _of(sketch, ids, "Circle", True)[-1]
        lines = _of(sketch, ids, "LineSegment")
        g = G[circle]
        if key in ("cx", "cy"):
            x, y = (value, vals["cy"]) if key == "cx" else (vals["cx"], value)
            return _move(sketch, circle, MID, x, y)
        if key == "diameter":
            return _set_radius(sketch, circle, 0.5 * value)
        if key == "angle":
            v = G[lines[0]].StartPoint - g.Center
            t = math.radians(value)
            return _move(sketch, lines[0], START, g.Center.x + v.Length * math.cos(t),
                         g.Center.y + v.Length * math.sin(t))
    return False


def _ellipse_at(ell, t):
    p = ell.value(t)
    return p.x, p.y


# --------------------------------------------------------------------------- the boxes
def wire(page, fields, kind):
    """Make the page's Parameters boxes (key -> QLineEdit) editable: Enter or leaving a box
    changes the tool's last placed entity."""
    page._param_kind = kind
    for key, f in fields.items():
        f.setReadOnly(False)
        f.setToolTip("Type a value to change the last %s placed" % _NAMES.get(kind, kind))
        f.editingFinished.connect(lambda k=key, w=f: _typed(page, k, w))


_NAMES = {"rect": "rectangle", "arc": "arc", "circle": "circle", "point": "point", "slot": "slot",
          "ellipse": "ellipse", "polygon": "polygon"}


def _tool(page):
    try:
        t = page._own_tool()
    except Exception:
        t = None
    if t is None:
        from .fwsketch import toolbase
        t = toolbase.active()
    return t


def _typed(page, key, widget):
    if not widget.isModified():
        return
    widget.setModified(False)
    try:
        value = _parse(widget.text())
    except ValueError:
        return
    tool = _tool(page)
    sketch = getattr(page, "sketch", None) or getattr(tool, "sketch", None)
    if tool is None or sketch is None:
        return
    ids = last_group(tool, sketch)
    if not ids:
        return
    kind = page._param_kind
    doc = sketch.Document
    doc.openTransaction("Edit %s" % _NAMES.get(kind, kind))
    try:
        changed = write(kind, sketch, ids, key, value)
        doc.commitTransaction()
    except Exception as e:
        doc.abortTransaction()
        App.Console.PrintWarning("FreeCAD: %s %s not changed (%s)\n" % (kind, key, e))
        return
    doc.recompute()
    try:
        tool.snapper.sketch_changed()
    except Exception as _fw_err:
        _fw_log("paramedit.py:400", _fw_err)
    page._param_edited = True
    if not changed:
        App.Console.PrintMessage("FreeCAD: the %s's %s is held by its relations\n" % (_NAMES.get(kind, kind), key))


def editing(fields):
    """True while a box has the keyboard (the live values then wait)."""
    for f in fields.values():
        w = f[0] if isinstance(f, tuple) else f
        try:
            if w.hasFocus() and w.isModified():
                return True
        except RuntimeError as _fw_err:
            _fw_log("paramedit.py:414", _fw_err)
    return False


def placed_values(page, kind):
    ""
    tool = _tool(page)
    sketch = getattr(page, "sketch", None) or getattr(tool, "sketch", None)
    if tool is None or sketch is None:
        return {}
    ids = last_group(tool, sketch)
    return read(kind, sketch, ids) if ids else {}
