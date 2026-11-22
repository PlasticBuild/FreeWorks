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

PREFIX = "EqualCurveLength"
ARC = "Arc"
TOL = 1e-7


def _names(sketch):
    return {c.Name: i for i, c in enumerate(sketch.Constraints) if c.Name.startswith(PREFIX)}


def _new_name(sketch):
    used = {c.Name for c in sketch.Constraints}
    n = 1
    while "%s%d" % (PREFIX, n) in used or "%s%d%s" % (PREFIX, n, ARC) in used:
        n += 1
    return "%s%d" % (PREFIX, n)


def _hide(sketch, index):
    try:
        sketch.setVirtualSpace(index, True)
    except Exception as _fw_err:
        _fw_log("fwsketch/curvelength.py:52", _fw_err)


def add(sketch, line, arc):
    """Ties line's length to arc's (geometry indices); returns the line dimension's index."""
    import Sketcher
    name = _new_name(sketch)
    mark = sketch.addConstraint(Sketcher.Constraint("Distance", arc, sketch.Geometry[arc].length()))
    sketch.setDriving(mark, False)
    sketch.renameConstraint(mark, name + ARC)
    _hide(sketch, mark)
    index = sketch.addConstraint(Sketcher.Constraint("Distance", line, sketch.Geometry[arc].length()))
    sketch.renameConstraint(index, name)
    _hide(sketch, index)
    return index


def pairs(sketch):
    """[(line index, arc index, line constraint index, arc constraint index)] of the live pairs."""
    names = _names(sketch)
    out = []
    for name, k in names.items():
        if name.endswith(ARC):
            continue
        m = names.get(name + ARC)
        if m is not None:
            out.append((sketch.Constraints[k].First, sketch.Constraints[m].First, k, m))
    return sorted(out, key=lambda p: p[2])


def is_link(sketch, index):
    return any(index in (k, m) for _l, _a, k, m in pairs(sketch))


def pair_of(sketch, index):
    """(line, arc) geometry indices of the pair that constraint index belongs to, or None."""
    for line, arc, k, m in pairs(sketch):
        if index in (k, m):
            return line, arc
    return None


def members(sketch, index):
    """Both constraint indices of the pair that index belongs to (to delete it whole)."""
    for _line, _arc, k, m in pairs(sketch):
        if index in (k, m):
            return (k, m)
    return (index,)


def sync(sketch):
    """Drops half pairs and sets each line length to its arc's; True when something changed."""
    names = _names(sketch)
    if not names:
        return False
    changed = False
    lone = [k for name, k in names.items()
            if (name.endswith(ARC) and name[:-len(ARC)] not in names)
            or (not name.endswith(ARC) and name + ARC not in names)]
    for k in sorted(lone, reverse=True):
        sketch.delConstraint(k)
        changed = True
    for line, arc, k, _m in pairs(sketch):
        want = sketch.Geometry[arc].length()
        if abs(sketch.Constraints[k].Value - want) > TOL:
            try:
                sketch.setDatum(k, App.Units.Quantity(want, App.Units.Length))
                changed = True
            except Exception as _fw_err:
                _fw_log("fwsketch/curvelength.py:121", _fw_err)
    return changed


class Watcher:
    """After each recompute of a sketch with pairs, the lines follow their arcs."""

    def __init__(self):
        self._busy = False
        App.addDocumentObserver(self)

    def stop(self):
        try:
            App.removeDocumentObserver(self)
        except Exception as _fw_err:
            _fw_log("fwsketch/curvelength.py:136", _fw_err)

    def slotRecomputedObject(self, obj):
        if self._busy or not obj.isDerivedFrom("Sketcher::SketchObject"):
            return
        self._busy = True
        try:
            if sync(obj):
                obj.recompute()
        except Exception as _fw_err:
            _fw_log("fwsketch/curvelength.py:146", _fw_err)
        finally:
            self._busy = False


_watcher = None


def start():
    global _watcher
    if _watcher is None:
        _watcher = Watcher()
    return _watcher


def stop():
    global _watcher
    if _watcher is not None:
        _watcher.stop()
        _watcher = None
