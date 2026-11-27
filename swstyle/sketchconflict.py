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
import FreeCADGui as Gui
from PySide import QtCore

VIEW = "User parameter:BaseApp/Preferences/View"
SETTING = "SketchKeepColoursOnConflict"
TOL = 0.004             # colour match (Coin keeps floats)
POLL_MS = 400

_state = {"timer": None, "sketch": None, "sensors": [], "busy": False, "mats": {}, "fields": {}, "coords": {},
          "turn": None}


def _enabled():
    try:
        from . import paths
        return paths.params().GetBool(SETTING, True)
    except Exception:
        return True


def _colour(key, default):
    u = App.ParamGet(VIEW).GetUnsigned(key, default)
    return (((u >> 24) & 255) / 255.0, ((u >> 16) & 255) / 255.0, ((u >> 8) & 255) / 255.0)


def _same(a, b):
    return all(abs(x - y) <= TOL for x, y in zip(a, b))


def _editing():
    """The sketch open for editing, else None."""
    try:
        gdoc = Gui.ActiveDocument
        vp = gdoc.getInEdit() if gdoc is not None else None
        obj = getattr(vp, "Object", None)
        if obj is not None and obj.isDerivedFrom("Sketcher::SketchObject"):
            return obj
    except Exception:
        return None
    return None


def _free_geometry(sketch):
    """Ids of the geometry that is not fully defined (the solver's free parameters); None when unknown."""
    try:
        return {g for g, _pos in sketch.getGeometryWithDependentParameters()}
    except Exception:
        return None


def _materials(root):
    """{name: (SoMaterial, SoCoordinate3 or None)} of the edit root's curve and point colour lists."""
    from pivy import coin
    out = {}
    sa = coin.SoSearchAction()
    sa.setType(coin.SoMaterial.getClassTypeId())
    sa.setInterest(coin.SoSearchAction.ALL)
    sa.setSearchingAll(True)
    sa.apply(root)
    paths = sa.getPaths()
    for i in range(paths.getLength()):
        node = paths.get(i).getTail()
        name = node.getName().getString()
        if name.startswith("CurvesMaterials") or name.startswith("PointsMaterials"):
            out[name] = coin.cast(node, "SoMaterial")
    return out


def _curve_ids(sketch, construction):
    """The ids of the sketch's own curves FreeCAD draws in one layer list, in its order (normal or
    construction; points are drawn as points, not curves)."""
    out = []
    for i, g in enumerate(sketch.Geometry):
        if g.TypeId == "Part::GeomPoint":
            continue
        try:
            is_con = bool(sketch.getConstruction(i))
        except Exception:
            is_con = False
        if is_con == construction:
            out.append(i)
    return out


def _coords_for(name, root):
    """The point list drawn with the colour list `name` (PointsMaterials_0 -> PointsCoordinate0)."""
    from pivy import coin
    node = _state["coords"].get(name)
    if node is not None:
        return [tuple(c.getValue()) for c in node.point.getValues()]
    want = "PointsCoordinate" + name.split("_")[-1]
    sa = coin.SoSearchAction()
    sa.setName(coin.SbName(want))
    sa.setInterest(coin.SoSearchAction.FIRST)
    sa.setSearchingAll(True)
    sa.apply(root)
    path = sa.getPath()
    if path is None:
        return None
    node = coin.cast(path.getTail(), "SoCoordinate3")
    if name in _state["mats"]:
        _state["coords"][name] = node           # kept with the watched lists (dropped by _detach)
    return [tuple(c.getValue()) for c in node.point.getValues()]


def _fixed_vertices(sketch, free):
    """Sketch-plane (x, y) of every end, centre or point of geometry the solver says is fully defined."""
    out = []
    for i in range(len(sketch.Geometry)):
        if i in free:
            continue
        for pos in (1, 2, 3):
            try:
                p = sketch.getPoint(i, pos)
            except Exception:
                continue
            out.append((p.x, p.y))
    return out


def _has_invalid(mat, invalid, field=None):
    """True when the colour list has an entry in the clash colour (field: the list's diffuseColor, kept at
    attach: pivy's field lookup by name costs more than the scan)."""
    try:
        values = (field if field is not None else mat.diffuseColor).getValues()
        return any(_same(c.getValue(), invalid) for c in values)
    except Exception:
        return False


def _turn_facts(sketch):
    """The colours and the sketch's facts, read once per event-loop turn (a solve writes the lists many
    times in one turn); the sketch facts only when a clash is there to fix."""
    turn = _state.get("turn")
    if turn is not None and turn["sketch"] is sketch:
        return turn
    memo = {}

    def once(key, fn):
        def get(*args):
            k = (key,) + args
            if k not in memo:
                memo[k] = fn(*args)
            return memo[k]
        return get

    turn = {"sketch": sketch,
            "invalid": _colour("InvalidSketchColor", 0xD7D700FF),
            "under": _colour("EditedEdgeColor", 0x5C9DFFFF),
            "full": _colour("FullyConstraintElementColor", 0x000000FF),
            "con": _colour("ConstructionColor", 0x5C9DFFFF),
            "free": once("free", lambda: _free_geometry(sketch)),
            "ids": once("ids", lambda construction: _curve_ids(sketch, construction)),
            "fixed": lambda free: memo.setdefault(("fixed",), _fixed_vertices(sketch, free))}
    _state["turn"] = turn
    QtCore.QTimer.singleShot(0, _end_turn)
    return turn


def _end_turn():
    _state["turn"] = None


def recolour(sketch=None, mats=None):
    """Puts back the colour of each entry FreeCAD painted yellow only because of a clash elsewhere.
    Returns the number of entries changed."""
    sketch = sketch or _editing()
    if sketch is None or not _enabled():
        return 0
    if mats is None:
        try:
            mats = _state["mats"] if _state["sketch"] is sketch and _state["mats"] else \
                _materials(Gui.ActiveDocument.ActiveView.getSceneGraph())
        except Exception:
            return 0
    facts = _turn_facts(sketch)
    invalid = facts["invalid"]
    if not any(_has_invalid(m, invalid) for m in mats.values()):
        return 0                    # no clash: nothing yellow, nothing more to read
    under, full, con, free = facts["under"], facts["full"], facts["con"], facts["free"]()
    changed = 0
    layers = {"CurvesMaterials0": (facts["ids"](False), under),
              "CurvesMaterials1": (facts["ids"](True), con)}
    _state["busy"] = True
    try:
        for name, mat in mats.items():
            n = mat.diffuseColor.getNum()
            if not n:
                continue
            cols = [tuple(c.getValue()) for c in mat.diffuseColor.getValues()]
            if not any(_same(c, invalid) for c in cols):
                continue
            ids, plain = layers.get(name, (None, under))
            fixed = None
            if name.startswith("PointsMaterials") and free is not None:
                try:
                    pts = _coords_for(name, Gui.ActiveDocument.ActiveView.getSceneGraph())
                    if pts is not None and len(pts) == n:
                        fixed = (pts, facts["fixed"](free))
                except Exception as _fw_err:
                    _fw_log("sketchconflict.py:points", _fw_err)
            out = list(cols)
            for k, c in enumerate(cols):
                if not _same(c, invalid):
                    continue
                colour = plain
                if ids is not None and len(ids) == n and free is not None and name == "CurvesMaterials0":
                    colour = under if ids[k] in free else full
                elif fixed is not None:
                    x, y = fixed[0][k][0], fixed[0][k][1]
                    if any(abs(x - fx) < 1e-6 and abs(y - fy) < 1e-6 for fx, fy in fixed[1]):
                        colour = full
                out[k] = colour
                changed += 1
            if changed:
                mat.diffuseColor.setValues(0, len(out), out)
    finally:
        _state["busy"] = False
    return changed


def _on_change(name):
    """One colour list changed: fix that list only, and only when something in it is yellow."""
    if _state["busy"]:
        return
    mat = _state["mats"].get(name)
    sketch = _state["sketch"]
    if mat is None or sketch is None:
        return
    try:
        if not _has_invalid(mat, _turn_facts(sketch)["invalid"], _state["fields"].get(name)):
            return
        recolour(sketch, {name: mat})
    except Exception as _fw_err:
        _fw_log("sketchconflict.py:sensor", _fw_err)


def _detach():
    for s in _state["sensors"]:
        try:
            s.detach()
        except Exception as _fw_err:
            _fw_log("sketchconflict.py:detach", _fw_err)
    _state["sensors"] = []
    _state["sketch"] = None
    _state["key"] = None
    _state["mats"] = {}
    _state["fields"] = {}
    _state["coords"] = {}
    _state["turn"] = None


def _poll():
    try:
        sketch = _editing() if _enabled() else None
        if sketch is None:
            if _state["sketch"] is not None:
                _detach()
            return
        from pivy import coin
        mats = _materials(Gui.ActiveDocument.ActiveView.getSceneGraph())
        key = sorted((name, int(m.this) if hasattr(m, "this") else id(m)) for name, m in mats.items())
        if _state["sketch"] is sketch and _state["sensors"] and key == _state.get("key"):
            return                  # the same lists watched already
        _detach()
        if not mats:
            return
        _state["sketch"] = sketch
        _state["key"] = key
        _state["mats"] = dict(mats)
        _state["fields"] = {name: mat.diffuseColor for name, mat in mats.items()}
        for name, mat in mats.items():
            sensor = coin.SoFieldSensor(lambda _data, _sensor, name=name: _on_change(name), None)
            sensor.setPriority(0)           # at once, before the view draws: no yellow flash
            sensor.attach(mat.diffuseColor)
            _state["sensors"].append(sensor)
        recolour(sketch, mats)
    except Exception as _fw_err:
        _fw_log("sketchconflict.py:poll", _fw_err)


def install():
    if _state["timer"] is not None:
        return
    t = QtCore.QTimer(Gui.getMainWindow())
    t.setInterval(POLL_MS)
    t.timeout.connect(_poll)
    t.start()
    _state["timer"] = t


def remove():
    if _state["timer"] is not None:
        _state["timer"].stop()
        _state["timer"] = None
    _detach()
