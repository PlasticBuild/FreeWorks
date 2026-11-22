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
from . import geomkeep

DEPTH = 8
_pending = {}          # (doc, sketch) -> (key, geometry) just before a Constraints change
_history = {}          # (doc, sketch) -> [(key before, geometry before, geometry after)]
_busy = set()
_last = {}             # (doc, sketch) -> its dimensions after the last change
RESTORED = [0]


def _id(obj):
    return (obj.Document.Name, obj.Name)


def key(sketch):
    out = []
    for c in sketch.Constraints:
        try:
            out.append((c.Type, c.First, c.FirstPos, c.Second, c.SecondPos, c.Third, c.ThirdPos,
                        round(float(c.Value), 9), bool(getattr(c, "Driving", True)), bool(getattr(c, "IsActive", True))))
        except Exception:
            out.append((c.Type,))
    return (len(sketch.Geometry), tuple(out))


def _geom(sketch):
    return [g.clone() for g in geomkeep.read(sketch)]      # clone: the entity's Tag stays


def _same(a, b, tol=1e-7):
    if a is None or b is None or len(a) != len(b):
        return False
    for g, h in zip(a, b):
        if g.TypeId != h.TypeId:
            return False
        for name in ("StartPoint", "EndPoint", "Center", "Radius", "MajorRadius", "MinorRadius"):
            if hasattr(g, name):
                x, y = getattr(g, name), getattr(h, name)
                if isinstance(x, App.Vector):
                    if (x - y).Length > tol:
                        return False
                elif abs(x - y) > tol:
                    return False
        if not hasattr(g, "StartPoint") and not hasattr(g, "Center"):
            try:
                if (g.X - h.X) ** 2 + (g.Y - h.Y) ** 2 > tol * tol:
                    return False
            except Exception as _fw_err:
                _fw_log("sketchmemory.py:74", _fw_err)
    return True


def _free(sketch):
    try:
        return not sketch.FullyConstrained
    except Exception:
        return True


def _dimensioned(sketch):
    """Only a dimension edit has an earlier state to give back: a sketch without dimensions is moved
    by hand or by a script (moveGeometry), and its last shape is the one it keeps."""
    try:
        return any(c.Driving and c.Type in DIMS for c in sketch.Constraints)
    except Exception:
        return False


DIMS = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle")


def _external(sketch):
    """A sketch with external geometry (a layout block, model edges) is moved by what it references,
    with the same dimensions: its old shape is not the right one to put back (Assemblies, top-down)."""
    if getattr(sketch, "FwFromBlock", "") or getattr(sketch, "FwLayout", False):
        return True                       # a part made from a layout block, or the layout itself
    try:
        if sketch.ExternalGeometry:
            return True
        # Convert Entities in context: On Edge relations to the referenced part's edges (FWOnEdge_)
        return any((c.Name or "").startswith("FWOnEdge_") for c in sketch.Constraints)
    except Exception:
        return False


def _undoing(sketch):
    d = sketch.Document
    return bool(getattr(d, "Transacting", False) or getattr(d, "Restoring", False))


def before(sketch):
    if _id(sketch) in _busy:
        return
    if _external(sketch):
        _history.pop(_id(sketch), None)
        _pending.pop(_id(sketch), None)
        return
    if _undoing(sketch):                 # Undo/Redo puts back a whole state: the history is over
        _history.pop(_id(sketch), None)
        _pending.pop(_id(sketch), None)
        return
    i = _id(sketch)
    if i in _solving and i not in _solved:
        # a second change before the first was solved. Two expression-driven dimensions set in one
        # rebuild (a derived sketch, an equation): the geometry here answers neither set of
        # dimensions, and kept as a state it would later be "put back" over the solved sketch. But
        # FreeCAD also writes Constraints again with the same dimensions (a second Constraints
        # signal right after setDatum, some runs only); that one changes nothing here, and after()
        # tells the two apart (coverage bench 11-19: the memory failed about 1 run in 2)
        _pending[i] = (_SECOND, key(sketch))
        return
    _settled(_id(sketch), sketch)          # two changes in a row: the first one's answer is here now
    # FreeCAD's setDatum changes the value before this signal: the dimensions as they were are the
    # ones seen after the last change (or when the file was opened)
    _pending[_id(sketch)] = (_last.get(_id(sketch)) or key(sketch), _geom(sketch))


_SECOND = object()     # marks a second change before the first was solved
_solving = set()       # sketches whose Constraints just changed: their next Geometry changes are the solve
_solved = set()        # ... and whose geometry did change since: the solve has run


def after(sketch):
    """After a Constraints change: put back the geometry of an earlier state with these dimensions.
    FreeCAD solves right after this signal, starting from what is here, so the solver keeps it."""
    i = _id(sketch)
    if i in _busy:
        return False
    got = _pending.pop(i, None)
    if got is not None and got[0] is _SECOND:
        k_now = key(sketch)
        if k_now != got[1]:
            _history.pop(i, None)         # a second dimension changed before the solve: no old state holds
        _last[i] = k_now
        return False
    if got is None or _undoing(sketch):
        _last[i] = key(sketch)
        if got is not None:
            _history.pop(i, None)
        return False
    if _external(sketch):
        _history.pop(i, None)
        _last[i] = key(sketch)
        return False
    k_before, g_before = got
    k_now = key(sketch)
    if k_before[0] != k_now[0] or len(k_before[1]) != len(k_now[1]) or len(g_before) != len(sketch.Geometry):
        # geometry or constraints added or taken away (a layout rebuilding the sketch, a new relation):
        # not a dimension edit, so the old states don't hold
        _history.pop(i, None)
        _last[i] = k_now
        return False
    hist = _history.setdefault(i, [])
    if hist and not _same(hist[-1][2], g_before, 1e-6):
        hist[:] = []                      # something moved in between: the old states don't hold
    hist.append((k_before, g_before, None))
    del hist[:-DEPTH]
    _solving.add(i)
    try:                                  # the solve runs inside this call: what moves later is a drag
        from PySide import QtCore
        QtCore.QTimer.singleShot(0, lambda i=i, s=sketch: _settled(i, s))
    except Exception as _fw_err:
        _fw_log("sketchmemory.py:179", _fw_err)
    k = key(sketch)
    _last[i] = k
    if not _free(sketch) or not _dimensioned(sketch):
        return False
    for kb, gb, _ga in reversed(hist):
        if kb == k and len(gb) == len(sketch.Geometry) and not _same(gb, g_before):
            _busy.add(i)
            try:
                sketch.Geometry = [g.clone() for g in gb]
                RESTORED[0] += 1
                return True
            except Exception:
                return False
            finally:
                _busy.discard(i)
    return False


def _settled(i, sketch):
    """The solve after a change is over: its answer is the state after the change."""
    if i not in _solving:
        return
    _solving.discard(i)
    _solved.discard(i)
    hist = _history.get(i)
    try:
        if hist and hist[-1][2] is None:
            kb, gb, _ga = hist[-1]
            hist[-1] = (kb, gb, _geom(sketch))
    except Exception as _fw_err:
        _fw_log("sketchmemory.py:210", _fw_err)


def geometry_changed(sketch):
    i = _id(sketch)
    if i in _solving:
        _solved.add(i)
    if i in _busy or i in _solving:
        return
    if _undoing(sketch):
        _history.pop(i, None)
        return
    hist = _history.get(i)
    if not hist:
        return
    if hist[-1][2] is None:
        return
    if not _same(hist[-1][2], _geom(sketch), 1e-6):
        hist[:] = []                              # moved by hand: the old states don't hold
    # else: a rebuild solved the sketch again where it was


class _Watch:
    def slotBeforeChangeObject(self, obj, prop):
        if prop == "Constraints" and getattr(obj, "TypeId", "") == "Sketcher::SketchObject":
            try:
                before(obj)
            except Exception as _fw_err:
                _fw_log("sketchmemory.py:238", _fw_err)

    def slotChangedObject(self, obj, prop):
        if prop == "Constraints" and getattr(obj, "TypeId", "") == "Sketcher::SketchObject":
            try:
                after(obj)
            except Exception as _fw_err:
                _fw_log("sketchmemory.py:245", _fw_err)

        elif prop == "Geometry" and getattr(obj, "TypeId", "") == "Sketcher::SketchObject":
            try:
                geometry_changed(obj)
            except Exception as _fw_err:
                _fw_log("sketchmemory.py:251", _fw_err)

    def slotFinishRestoreDocument(self, doc):
        for o in doc.Objects:
            if o.TypeId == "Sketcher::SketchObject":
                try:
                    _last[_id(o)] = key(o)
                except Exception as _fw_err:
                    _fw_log("sketchmemory.py:259", _fw_err)

    def slotRecomputedDocument(self, doc):
        for k in [k for k in _solving if k[0] == doc.Name]:
            o = doc.getObject(k[1])
            if o is not None:
                _settled(k, o)
            _solving.discard(k)
            _solved.discard(k)

    def slotDeletedDocument(self, doc):
        for d in (_pending, _history, _last):
            for k in [k for k in d if k[0] == doc.Name]:
                d.pop(k, None)


_watch = []


def install():
    if not _watch:
        _watch.append(_Watch())
        App.addDocumentObserver(_watch[0])
        try:        # the dimensions an opened file starts from (FreeCAD 1.1 never sends slotFinishRestoreDocument)
            from . import restorehook
            restorehook.on_restored(_watch[0].slotFinishRestoreDocument)
        except Exception as _fw_err:
            _fw_log("sketchmemory.py:restorehook", _fw_err)
