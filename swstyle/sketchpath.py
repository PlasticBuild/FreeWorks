# SPDX-License-Identifier: LGPL-2.1-or-later
""







import FreeCAD as App
import FreeCADGui as Gui

PROP = "SWSketchPaths"
TOL = 1e-6


def _fw_log(site, err):
    try:
        App.Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        pass


def _status(text):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 5000)
    except Exception as _fw_err:
        _fw_log("sketchpath.py:status", _fw_err)


def _sketch():
    from . import contextbar
    return contextbar.sketch_in_edit()


def _in_sketch():
    return App.ActiveDocument is not None and _sketch() is not None


# ---------------------------------------------------------------- the paths a sketch keeps
def _rows(sketch):
    return list(getattr(sketch, PROP, []) or []) if PROP in sketch.PropertiesList else []


def _tag(sketch, index):
    try:
        return str(sketch.Geometry[index].Tag)
    except Exception:
        return None


def _index_by_tag(sketch):
    out = {}
    for i, g in enumerate(sketch.Geometry):
        try:
            out[str(g.Tag)] = i
        except Exception as _fw_err:
            _fw_log("sketchpath.py:tag", _fw_err)
    return out


def paths(sketch):
    """[(name, [geometry indices])] of the sketch's paths, entities that are gone left out."""
    by_tag = _index_by_tag(sketch)
    out = []
    for row in _rows(sketch):
        name, _sep, tags = row.partition("|")
        idx = [by_tag[t] for t in tags.split(",") if t in by_tag]
        if idx:
            out.append((name, idx))
    return out


def path_of(sketch, index):
    for name, idx in paths(sketch):
        if index in idx:
            return name, idx
    return None


def _write(sketch, rows):
    if PROP not in sketch.PropertiesList:
        sketch.addProperty("App::PropertyStringList", PROP, "FreeCAD", "Make Path: the geometry tags of each path")
        try:
            sketch.setEditorMode(PROP, 2)
        except Exception as _fw_err:
            _fw_log("sketchpath.py:hide-prop", _fw_err)
    setattr(sketch, PROP, rows)


# ---------------------------------------------------------------- end to end
def _ends(sketch, index):
    g = sketch.Geometry[index]
    try:
        a, b = g.StartPoint, g.EndPoint
    except Exception:
        return None                   # a circle, ellipse or point has no two ends
    if (a - b).Length < TOL:
        return None
    return a, b


def chained(sketch, indices):
    """True when the entities join end to end in one run (open or closed), as Make Path needs."""
    ends = {}
    for i in indices:
        e = _ends(sketch, i)
        if e is None:
            return len(indices) == 1 and _closed_curve(sketch, i)
        ends[i] = e
    if len(ends) == 1:
        return True
    points = []                       # distinct end points, each with the entities meeting there

    def key(p):
        for k, (q, _who) in enumerate(points):
            if (p - q).Length < 1e-5:
                return k
        points.append((p, []))
        return len(points) - 1
    for i, (a, b) in ends.items():
        points[key(a)][1].append(i)
        points[key(b)][1].append(i)
    degrees = [len(who) for _p, who in points]
    if any(d > 2 for d in degrees) or sum(1 for d in degrees if d == 1) not in (0, 2):
        return False
    # one run: walk from an end (or anywhere on a loop) and reach every entity
    start = next((who[0] for _p, who in points if len(who) == 1), indices[0])
    seen, todo = set(), [start]
    while todo:
        i = todo.pop()
        if i in seen:
            continue
        seen.add(i)
        for _p, who in points:
            if i in who:
                todo += [j for j in who if j not in seen]
    return len(seen) == len(ends)


def _closed_curve(sketch, index):
    name = type(sketch.Geometry[index]).__name__
    return "Circle" in name or "Ellipse" in name or "BSpline" in name


def _picked_indices(sketch):
    from . import relationspm
    out = []
    for sub in relationspm.picked_subs(sketch):
        if sub.startswith("Edge"):
            i = int(sub[4:]) - 1
            if i not in out:
                out.append(i)
    return out


def _pick(sketch, indices):
    try:
        for i in indices:
            Gui.Selection.addSelection(sketch.Document.Name, sketch.Name, "Edge%d" % (i + 1))
    except Exception as _fw_err:
        _fw_log("sketchpath.py:pick", _fw_err)


# ---------------------------------------------------------------- the commands
def make_path():
    sketch = _sketch()
    if sketch is None:
        return None
    picked = [i for i in _picked_indices(sketch) if 0 <= i < len(sketch.Geometry)]
    if not picked:
        _status("Make Path: pick the sketch entities for the path first")
        return None
    if not chained(sketch, picked):
        _status("Make Path: the picked entities must join end to end")
        return None
    taken = [n for n, idx in paths(sketch) if set(idx) & set(picked)]
    rows = [r for r in _rows(sketch) if r.partition("|")[0] not in taken]
    used = {r.partition("|")[0] for r in _rows(sketch)}
    k = 1
    while "Path%d" % k in used and "Path%d" % k not in taken:
        k += 1
    name = "Path%d" % k
    tags = [t for t in (_tag(sketch, i) for i in picked) if t]
    doc = sketch.Document
    doc.openTransaction("Make Path")
    try:
        _write(sketch, rows + ["%s|%s" % (name, ",".join(tags))])
    finally:
        doc.commitTransaction()
    _status("Make Path: %s (%d entities)" % (name, len(picked)))
    return name


def dissolve_path():
    sketch = _sketch()
    if sketch is None:
        return None
    names = []
    for i in _picked_indices(sketch):
        got = path_of(sketch, i)
        if got is not None and got[0] not in names:
            names.append(got[0])
    if not names:
        _status("Dissolve Path: pick an entity of a path")
        return None
    doc = sketch.Document
    doc.openTransaction("Dissolve Path")
    try:
        _write(sketch, [r for r in _rows(sketch) if r.partition("|")[0] not in names])
    finally:
        doc.commitTransaction()
    _status("Dissolve Path: %s" % ", ".join(names))
    return names


def _can_make():
    sketch = _sketch() if App.ActiveDocument is not None else None
    return sketch is not None


def _has_path_pick():
    sketch = _sketch() if App.ActiveDocument is not None else None
    if sketch is None:
        return False
    return any(path_of(sketch, i) is not None for i in _picked_indices(sketch))


# ---------------------------------------------------------------- a pick takes the whole path
class _Observer:
    def __init__(self):
        self.busy = False

    def addSelection(self, doc, obj, sub, pnt):
        if self.busy or not sub or not sub.split(".")[-1].startswith("Edge"):
            return
        sketch = _sketch()
        if sketch is None or sketch.Name != obj or sketch.Document.Name != doc or PROP not in sketch.PropertiesList:
            return
        try:
            index = int(sub.split(".")[-1][4:]) - 1
        except ValueError:
            return
        got = path_of(sketch, index)
        if got is None:
            return
        have = set(_picked_indices(sketch))
        rest = [i for i in got[1] if i not in have]
        if not rest:
            return
        self.busy = True
        try:
            _pick(sketch, rest)
        finally:
            self.busy = False


OBSERVER = None


class _Cmd:
    def __init__(self, text, tip, run, active):
        self.text, self.tip, self.run, self.active = text, tip, run, active

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "CmdType": "ForEdit"}

    def Activated(self):
        self.run()

    def IsActive(self):
        try:
            return self.active()
        except Exception:
            return False


COMMANDS = {
    "SWStyle_MakePath": _Cmd("Make Path", "Makes one path of the picked sketch entities, joined end to end",
                             make_path, _can_make),
    "SWStyle_DissolvePath": _Cmd("Dissolve Path", "Breaks the picked path into its sketch entities",
                                 dissolve_path, _has_path_pick),
}


def register():
    global OBSERVER
    for name, cmd in COMMANDS.items():
        if name not in Gui.listCommands():
            Gui.addCommand(name, cmd)
    if OBSERVER is None:
        OBSERVER = _Observer()
        Gui.Selection.addObserver(OBSERVER)
