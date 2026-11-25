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

from .toolbase import GENERAL_GROUP, param_bool
from .. import geomkeep

EPS = 1e-9
LENGTH_TYPES = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Weight")


def enabled():
    return param_bool(GENERAL_GROUP, "ScaleOnFirstDimension", True)


def scale_defining(sketch):
    """The index of the only driving length dimension, or -1 (getSingleScaleDefiningConstraint)."""
    found = -1
    for i, c in enumerate(sketch.Constraints):
        if c.Type in LENGTH_TYPES and c.Driving:
            if found != -1:
                return -1
            found = i
    return found


def has_block(sketch):
    return any(c.Type == "Block" for c in sketch.Constraints)


def references_model(sketch):
    """True when the sketch uses model geometry (the two axes are always there)."""
    try:
        return len(sketch.ExternalGeo) > 2
    except Exception:
        try:
            return bool(sketch.ExternalGeometry)
        except Exception:
            return False


def applies(sketch, index):
    if not enabled() or has_block(sketch) or references_model(sketch):
        return False
    return scale_defining(sketch) == index


def scaled(geo, f):
    """geo scaled about the origin in place (the copy keeps its id, construction and internal
    type); ValueError for a kind that cannot be scaled."""
    t = geo.TypeId
    if t == "Part::GeomLineSegment":
        s, e = geo.StartPoint * f, geo.EndPoint * f
        geo.StartPoint, geo.EndPoint = s, e
    elif t in ("Part::GeomCircle", "Part::GeomArcOfCircle"):
        geo.Center = geo.Center * f
        geo.Radius = geo.Radius * f
    elif t == "Part::GeomPoint":
        geo.X, geo.Y = geo.X * f, geo.Y * f
    elif t in ("Part::GeomEllipse", "Part::GeomArcOfEllipse"):
        c = geo.Center * f
        if f >= 1.0:
            geo.MajorRadius = geo.MajorRadius * f
            geo.MinorRadius = geo.MinorRadius * f
        else:
            geo.MinorRadius = geo.MinorRadius * f
            geo.MajorRadius = geo.MajorRadius * f
        geo.Center = c
    elif t == "Part::GeomBSplineCurve":
        for i, p in enumerate(geo.getPoles()):
            geo.setPole(i + 1, p * f)
    else:
        raise ValueError("cannot scale a %s" % t)
    return geo


def scale_sketch(sketch, f):
    """Every geometry of the sketch scaled about the origin; dimension labels keep their distance
    in proportion. Raises when a geometry cannot be scaled (nothing is changed then)."""
    geos = geomkeep.read(sketch)
    flags = [sketch.getConstruction(i) for i in range(len(geos))]
    for g in geos:
        scaled(g, f)
    sketch.Geometry = geos
    for i, flag in enumerate(flags):   # a Part::GeomPoint drops its flag on the way
        try:
            if sketch.getConstruction(i) != flag:
                sketch.setConstruction(i, flag)
        except Exception as _fw_err:
            _fw_log("fwsketch/firstdim.py:108", _fw_err)
    for i, c in enumerate(sketch.Constraints):
        if c.Type in LENGTH_TYPES or c.Type == "Angle":
            try:
                sketch.setLabelDistance(i, c.LabelDistance * f)
            except Exception as _fw_err:
                _fw_log("fwsketch/firstdim.py:114", _fw_err)


def scale_for(sketch, index, new_value):
    """The factor the first dimension asks for, or None when nothing is to be scaled."""
    if not applies(sketch, index):
        return None
    try:
        old = float(sketch.Constraints[index].Value)
    except Exception:
        return None
    if old <= EPS or new_value <= EPS:
        return None
    f = new_value / old
    if abs(f - 1.0) < 1e-7:
        return None
    return f


def on_first_dimension(sketch, index, new_value):
    """Scale the sketch for the first dimension's new value (mm); the factor used, or None."""
    f = scale_for(sketch, index, new_value)
    if f is None:
        return None
    try:
        scale_sketch(sketch, f)
    except Exception as e:
        App.Console.PrintLog("FreeCAD: sketch not scaled on the first dimension: %s\n" % e)
        return None
    App.Console.PrintLog("FreeCAD: sketch scaled by %.6g on its first dimension\n" % f)
    return f
