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

import hashlib
import FreeCAD as App

_CACHE = {}
_MAX = 64
_SKIP = {"Shape", "AddSubShape", "SuppressedShape", "Placement", "Label", "Label2", "Visibility",
         "ExpressionEngine", "Proxy", "Tip", "_Body", "MapMode", "AttachmentOffset", "Support",
         "AttachmentSupport", "MapReversed", "MapPathParameter", "AttacherType", "AttacherEngine",
         "Content", "Refine", "PreviewShape", "ShapeMaterial", "State"}


def shape_sig(shape, h):
    if shape is None or shape.isNull():
        h.update(b"null")
        return
    h.update(("%d %d %d" % (len(shape.Faces), len(shape.Edges), len(shape.Vertexes))).encode())
    # no BoundBox: OCC's box of a curved shape grows once the view has meshed it. Area, volume and
    # the vertex points (1e-5 mm: booleans move a point in the last digits) are exact enough
    try:
        h.update(("%.4f" % shape.Area).encode())
        if shape.Solids:
            h.update(("%.4f" % shape.Volume).encode())
        h.update(("%.4f" % sum(e.Length for e in shape.Edges)).encode())
    except Exception as _fw_err:
        _fw_log("fcache.py:44", _fw_err)
    pts = sorted("%.5f,%.5f,%.5f" % (v.Point.x, v.Point.y, v.Point.z) for v in shape.Vertexes)
    h.update(";".join(pts).replace("-0.00000", "0.00000").encode())
    pl = shape.Placement
    h.update(("%.6f %.6f %.6f %s" % (pl.Base.x, pl.Base.y, pl.Base.z,
                                     " ".join("%.6f" % q for q in pl.Rotation.Q))).encode())


def _value(value, h, depth=0):
    if isinstance(value, App.DocumentObject):
        h.update(value.FullName.encode())
        shape = getattr(value, "Shape", None)
        if shape is not None and hasattr(shape, "isNull"):
            shape_sig(shape, h)
        try:
            h.update(repr(value.getGlobalPlacement()).encode())
        except Exception:
            h.update(repr(getattr(value, "Placement", "")).encode())
    elif isinstance(value, (list, tuple)) and depth < 3:
        h.update(b"[")
        for item in value:
            _value(item, h, depth + 1)
        h.update(b"]")
    else:
        h.update(repr(value).encode())


def key(obj, base, skip=()):
    h = hashlib.sha1()
    h.update(obj.FullName.encode())
    shape_sig(base, h)
    for name in sorted(obj.PropertiesList):
        if name in _SKIP or name in skip:
            continue
        try:
            _value(getattr(obj, name), h)
        except Exception:
            h.update(name.encode())
    return h.hexdigest()



# this for its recompute (results are still stored, so the next Ctrl+B can use them)
BYPASS = [False]


def get(k):
    if BYPASS[0]:
        return None
    hit = _CACHE.get(k)
    if hit is None:
        return None
    return tuple(s.copy() if s is not None else None for s in hit)


def put(k, *shapes):
    if len(_CACHE) >= _MAX:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[k] = tuple(s.copy() if s is not None else None for s in shapes)


def clear():
    _CACHE.clear()
