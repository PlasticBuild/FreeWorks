# SPDX-License-Identifier: LGPL-2.1-or-later
"""Hole callouts and the Hole Table for holes made by assembly features (Hole Wizard, Simple Hole, Hole Series).

A hole of a part reads its callout from the Hole Wizard's own choices on the hole (drawannot.wizard_callout). An assembly feature
keeps the same choices as its Spec (Hole Wizard, Hole Series) or its Diameter (Simple Hole): this reads them the same way, so a
drawing of the assembly calls out "4X ⌀6.60 THRU ALL" / "⌴ ⌀11.00 ↧ 6.40" / "M6x1 - 6H ↧ 12.00" for them as it does for a part.
"""
import json

import FreeCAD as App

KINDS = ("Wizard", "Hole", "Series")


class _Q:
    def __init__(self, v):
        self.Value = float(v)


class _Shim:
    """What holespec.callout_lines reads from a hole: its HoleWizardSpec and the sizes the hole has."""

    def __init__(self, spec):
        from . import asmfeature as af
        self.HoleWizardSpec = json.dumps(spec)
        try:
            d = af.hole_dims(dict(spec))
            self.Diameter = _Q(d["diameter"])
            self.HoleCutDiameter = _Q(d["cut_diameter"])
            self.HoleCutDepth = _Q(d["cut_depth"])
            self.HoleCutCountersinkAngle = _Q(d["csk_angle"])
            if not d["through"]:
                self.Depth = _Q(d["depth"])
        except Exception as error:
            App.Console.PrintLog("FreeCAD: assembly hole sizes: %s\n" % error)


def _features(doc):
    from . import asmfeature as af
    return [o for o in doc.Objects if getattr(o, af.FEATURE_PROP, "") in KINDS and not _suppressed(o)]


def _suppressed(o):
    try:
        return bool(getattr(o, "Suppressed", False))
    except Exception:
        return False


def _spec_dims(spec):
    """(through hole radius, rim radius) of one Hole Wizard choice: the circles its holes show in a view."""
    from . import asmfeature as af
    d = af.hole_dims(dict(spec))      # (a copy: the Hole Wizard's apply may touch the choices it is given)
    rs = [d["diameter"] / 2.0]
    if d["cut"] and d["cut_diameter"] > d["diameter"]:
        rs.append(d["cut_diameter"] / 2.0)
    for key in ("near", "far"):
        if d.get(key):
            rs.append(d[key][0] / 2.0)
    return rs


def _parts(feat):
    """[(spec, circles' radii)] of the feature: one for a Wizard, the parts of a Series (first, middle, last)."""
    from . import asmfeature as af
    kind = getattr(feat, af.FEATURE_PROP)
    if kind == "Wizard":
        spec = json.loads(feat.Spec or "{}")
        return [(spec, _spec_dims(spec))] if spec else []
    if kind == "Series":
        spec = json.loads(feat.Spec or "{}")
        if not spec:
            return []
        middle, last = af.series_parts(feat)
        parts = [spec]
        parts.append(dict(spec, **dict(middle, kind="Hole", type="Screw Clearances", end="Through All")))
        if last.get("kind") == "Straight Tap":
            parts.append(dict(spec, **dict(last, kind="Straight Tap", type=last.get("type") or "Tapped hole")))
        else:
            parts.append(dict(spec, **dict(last, kind="Hole", type=last.get("type") or "Screw Clearances")))
        return [(p, _spec_dims(p)) for p in parts]
    return []


def _points(feat):
    from . import asmfeature as af
    if getattr(feat, af.FEATURE_PROP) == "Hole":
        return [(App.Vector(feat.Point), App.Vector(feat.Normal))]
    spec = json.loads(feat.Spec or "{}")
    pts = [App.Vector(p) for p in (feat.Points or [])]
    normals = [App.Vector(*n) for n in (spec.get("normals") or [])]
    if len(normals) != len(pts):
        normals = [App.Vector(feat.Normal)] * len(pts)
    return list(zip(pts, normals))


def radii(doc_objects_doc):
    """The radii of the circles the assembly features' holes show (drawannot._wizard_radii)."""
    out = []
    for feat in _features(doc_objects_doc):
        try:
            if feat.PropertiesList and getattr(feat, "FwAsmFeature") == "Hole":
                out.append(float(getattr(feat.Diameter, "Value", feat.Diameter)) / 2.0)
            else:
                for _spec, rs in _parts(feat):
                    out += rs
        except Exception:
            continue
    return out


def _simple_lines(feat):
    d = float(getattr(feat.Diameter, "Value", feat.Diameter))
    through = (feat.EndCondition or "Through All") != "Blind"
    depth = float(getattr(getattr(feat, "Depth", 0), "Value", getattr(feat, "Depth", 0)) or 0)
    return ["⌀%.2f %s" % (d, "THRU ALL" if through or depth <= 0 else "↧ %.2f" % depth)]


def callout(view, centre, radius, D, DV):
    """The hole callout text of the assembly feature hole behind a view circle, or None."""
    from . import asmfeature as af
    from . import holespec
    d, x, y = D.view_frame(view)
    c3 = DV.model_centre(view) + x * centre.x + y * centre.y
    docs = []
    for o in DV.source_shapes(view):
        if o.Document not in docs:
            docs.append(o.Document)
    for doc in docs:
        for feat in _features(doc):
            try:
                kind = getattr(feat, af.FEATURE_PROP)
                pts = _points(feat)
                here = [p for p, n in pts if abs(abs(D._unit(n).dot(d)) - 1) < 1e-4 and
                        ((p - c3) - D._unit(n) * (p - c3).dot(D._unit(n))).Length < 1e-3]
                if not here:
                    continue
                if kind == "Hole":
                    if abs(float(getattr(feat.Diameter, "Value", feat.Diameter)) / 2.0 - radius) > 1e-4:
                        continue
                    lines = _simple_lines(feat)
                else:
                    lines = None
                    for spec, rs in _parts(feat):
                        if any(abs(r - radius) < 1e-4 for r in rs):
                            lines = holespec.callout_lines(_Shim(dict(spec)))
                            if lines:
                                break
                    if not lines:
                        continue
                count = len(pts)
                if count > 1:
                    lines = list(lines)
                    lines[0] = "%dX %s" % (count, lines[0])
                return "\n".join(lines).replace("%", "%%")
            except Exception as error:
                App.Console.PrintLog("FreeCAD: assembly hole callout: %s\n" % error)
    return None


def owner(view, centre, radius, D, DV):
    """The assembly feature whose hole shows the circle (a drill circle or a counterbore / countersink rim), or None."""
    from . import asmfeature as af
    d, x, y = D.view_frame(view)
    c3 = DV.model_centre(view) + x * centre.x + y * centre.y
    docs = []
    for o in DV.source_shapes(view):
        if o.Document not in docs:
            docs.append(o.Document)
    for doc in docs:
        for feat in _features(doc):
            try:
                if getattr(feat, af.FEATURE_PROP) == "Hole":
                    rs = [float(getattr(feat.Diameter, "Value", feat.Diameter)) / 2.0]
                else:
                    rs = [r for _spec, rr in _parts(feat) for r in rr]
                if not any(abs(r - radius) < 1e-4 for r in rs):
                    continue
                for p, n in _points(feat):
                    n = D._unit(n)
                    if abs(abs(n.dot(d)) - 1) < 1e-4 and ((p - c3) - n * (p - c3).dot(n)).Length < 1e-3:
                        return feat
            except Exception:
                continue
    return None
