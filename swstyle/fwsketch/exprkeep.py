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


import re

import FreeCAD as App

_REF = re.compile(r"^\.Constraints\[(\d+)\]$")
_NAMED = re.compile(r"\.Constraints\.([A-Za-z_][A-Za-z0-9_]*)")


def _is_sketch(obj):
    try:
        return obj.TypeId == "Sketcher::SketchObject"
    except Exception:
        return False


def _constraint_keys(obj):
    out = {}
    try:
        engine = obj.ExpressionEngine
    except Exception:
        return out
    for path, expr in engine:
        m = _REF.match(path)
        if m:
            out[int(m.group(1))] = expr
    return out


def _sig(c):
    try:
        value = round(float(c.Value), 9)
    except Exception:
        value = None
    return (c.Type, c.Name, bool(c.Driving), value)


def match(old, new):
    """{old index: new index} for an order-keeping delete from old to new (lists of signatures)."""
    out = {}
    j = 0
    for i, s in enumerate(old):
        if j < len(new) and new[j] == s:
            out[i] = j
            j += 1
    if j != len(new):          # not a plain delete (something changed too): match what still fits
        out = {}
        j = 0
        for i, s in enumerate(old):
            for k in range(j, len(new)):
                if new[k] == s:
                    out[i] = k
                    j = k + 1
                    break
    return out


def plan(old_sigs, new_sigs, keys):
    """(new {index: expr}) for the expressions keyed in keys ({old index: expr})."""
    where = match(old_sigs, new_sigs)
    names = {s[1] for s in new_sigs if s[1]}
    out = {}
    for i, expr in keys.items():
        j = where.get(i)
        if j is None:
            continue
        if any(n not in names for n in _NAMED.findall(expr)):
            continue
        out[j] = expr
    return out


def _clear(obj, index, size):
    """Drop the expression on .Constraints[index]; one past the end needs the list padded first."""
    path = ".Constraints[%d]" % index
    if index < size:
        obj.setExpression(path, None)
        return
    import Part
    import Sketcher
    p = obj.addGeometry(Part.Point(App.Vector(0, 0, 0)), True)
    pads = []
    while len(obj.Constraints) <= index:
        k = obj.addConstraint(Sketcher.Constraint("DistanceX", p, 1, 0.0))
        obj.setDriving(k, False)
        pads.append(k)
    obj.setExpression(path, None)
    obj.delConstraints(pads)
    obj.delGeometries([p])


_FOLLOWER = re.compile(r"^\.Constraints\.(([A-Za-z_][A-Za-z0-9_]*)_t\d+)$")


def _followers(obj, dangling=False):
    """{follower name: its expression path} for hidden followers bound to <name> (with dangling: whose
    <name> is gone). Offset Entities' own FollowerWatch handles its "Offset" ones."""
    out = {}
    try:
        engine = obj.ExpressionEngine
    except Exception:
        return out
    if not engine:
        return out
    names = {c.Name for c in obj.Constraints if c.Name} if dangling else None
    for path, expr in engine:
        m = _FOLLOWER.match(path)
        if not m or m.group(2).startswith("Offset") or expr.strip() != ".Constraints." + m.group(2):
            continue
        if dangling and (m.group(2) in names or m.group(1) not in names):
            continue
        out[m.group(1)] = path
    return out


class Keeper:
    def __init__(self):
        self.before = {}        # sketch -> (signatures, {index: expr}) before the first change
        self.pending = set()
        self.busy = False

    def slotBeforeChangeObject(self, obj, prop):
        if self.busy or prop != "Constraints" or not _is_sketch(obj) or obj in self.before:
            return
        keys = _constraint_keys(obj)
        if keys or _followers(obj):
            self.before[obj] = ([_sig(c) for c in obj.Constraints], keys)

    def slotChangedObject(self, obj, prop):
        if self.busy or prop != "Constraints" or obj not in self.before or obj in self.pending:
            return
        self.pending.add(obj)
        try:
            from PySide import QtCore
            QtCore.QTimer.singleShot(0, lambda o=obj: self._later(o))
        except Exception:
            self._later(obj)

    def _later(self, obj):
        """settle and drop_followers after the change; an error in one is logged, never left to the timer."""
        for step in (self.settle, self.drop_followers):
            try:
                step(obj)
            except Exception as _fw_err:
                self.pending.discard(obj)
                _fw_log("fwsketch/exprkeep.py:later", _fw_err)

    def drop_followers(self, obj):
        ""

        try:
            gone = _followers(obj, dangling=True)
        except Exception:
            return
        if not gone:
            return
        doc = obj.Document
        own = not doc.HasPendingTransaction
        self.busy = True
        try:
            if own:
                doc.openTransaction("Delete")
            for path in gone.values():
                try:
                    obj.setExpression(path, None)
                except Exception as _fw_err:
                    _fw_log("fwsketch/exprkeep.py:followers", _fw_err)
            idx = sorted((i for i, c in enumerate(obj.Constraints) if c.Name in gone), reverse=True)
            if idx:
                obj.delConstraints(idx)
            doc.recompute()
        except Exception as _fw_err:
            _fw_log("fwsketch/exprkeep.py:drop followers", _fw_err)
        finally:
            if own:
                doc.commitTransaction()
            self.busy = False

    def slotDeletedObject(self, obj):
        self.before.pop(obj, None)
        self.pending.discard(obj)

    def settle(self, obj):
        self.pending.discard(obj)
        old = self.before.pop(obj, None)
        if old is None:
            return
        try:
            new_sigs = [_sig(c) for c in obj.Constraints]
        except Exception:
            return              # the sketch went away
        old_sigs, keys = old
        if len(new_sigs) >= len(old_sigs):
            return              # nothing deleted: the keys still point right
        want = plan(old_sigs, new_sigs, keys)
        now = _constraint_keys(obj)
        if now == want:
            return
        doc = obj.Document
        own = not doc.HasPendingTransaction
        self.busy = True
        try:
            if own:
                doc.openTransaction("Delete")
            size = len(obj.Constraints)
            for i in sorted(now, reverse=True):
                _clear(obj, i, size)
            for j, expr in sorted(want.items()):
                obj.setExpression(".Constraints[%d]" % j, expr)
            doc.recompute()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: sketch expressions after a delete: %s\n" % error)
        finally:
            if own:
                doc.commitTransaction()
            self.busy = False


_keeper = None


def start():
    global _keeper
    if _keeper is None:
        _keeper = Keeper()
        App.addDocumentObserver(_keeper)
    return _keeper


def stop():
    global _keeper
    if _keeper is not None:
        try:
            App.removeDocumentObserver(_keeper)
        except Exception as _fw_err:
            _fw_log("fwsketch/exprkeep.py:197", _fw_err)
        _keeper = None
