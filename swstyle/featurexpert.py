# SPDX-License-Identifier: LGPL-2.1-or-later
""







import FreeCAD as App

STEP = 0.8
TRIES = 12


def enabled():
    try:
        from . import optionspages
        return bool(optionspages.stored("General", "Enable FeatureXpert", True))
    except Exception:
        return True


def _plan(obj):
    """The properties FeatureXpert may change on obj, or None when it can't help."""
    t = obj.TypeId
    if t == "PartDesign::Fillet":
        return ["Radius"]
    if t == "PartDesign::Chamfer":
        return [p for p in ("Size", "Size2") if p in obj.PropertiesList]
    if t == "PartDesign::Draft":
        return ["Angle"]
    return None


def can_repair(obj):
    return obj is not None and _plan(obj) is not None


def _ok(obj):
    try:
        return "Invalid" not in obj.State and not obj.Shape.isNull() and obj.Shape.isValid()
    except Exception:
        return False


def _value(obj, prop):
    v = getattr(obj, prop)
    return float(v.Value) if hasattr(v, "Value") else float(v)


def repair_one(obj):
    """Try to make obj rebuild. A text saying what changed, or None when it could not."""
    if _ok(obj):
        return "rebuilds as it is"      # an earlier repair in the same run fixed it: leave its values
    props = _plan(obj)
    if props is None:
        return None
    doc = obj.Document
    start = {p: _value(obj, p) for p in props}
    if obj.TypeId == "PartDesign::Draft" and "Reversed" in obj.PropertiesList:
        obj.Reversed = not obj.Reversed
        doc.recompute()
        if _ok(obj):
            return "Draft direction reversed"
        obj.Reversed = not obj.Reversed
    factor = 1.0
    for _ in range(TRIES):
        factor *= STEP
        for p in props:
            setattr(obj, p, start[p] * factor)
        doc.recompute()
        if _ok(obj):
            return ", ".join("%s %.4g -> %.4g" % (p, start[p], start[p] * factor) for p in props)
    for p in props:
        setattr(obj, p, start[p])
    doc.recompute()
    return None


def repair(doc, names):
    """FeatureXpert on the named features: [(label, what changed or None)]."""
    out = []
    doc.openTransaction("FeatureXpert")
    try:
        for name in names:
            obj = doc.getObject(name)
            if obj is None or not can_repair(obj):
                out.append((obj.Label if obj else name, None))
                continue
            out.append((obj.Label, repair_one(obj)))
    finally:
        doc.commitTransaction()
    return out
