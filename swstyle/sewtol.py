"""Sewing faces with a gap tolerance.

FreeCAD 1.1's Shape.sewShape(tol) ignores the tolerance it is given and always sews at 1e-6 mm, so faces that
are 1e-4 mm apart stay apart. sewn() keeps sewShape's own result when that already closes everything, and
otherwise joins the faces by a fuzzy fuse (fuse with the tolerance), then a plain sewShape.
"""
import Part


def _free(shape):
    """How many open edges shape has (a seam, which one face holds twice, is not open)."""
    n = 0
    for e in shape.Edges:
        owners = shape.ancestorsOfType(e, Part.Face)
        if len(owners) != 1:
            continue
        try:
            if e.isSeam(owners[0]):
                continue
        except Exception:
            pass
        n += 1
    return n


def _plain(faces):
    comp = Part.makeCompound([f.copy() for f in faces])
    try:
        comp.sewShape()
    except Exception:
        pass
    return comp


def _tidy(shape, faces):
    """A Shell when the result is one shell holding every face (as sewShape gives), else a compound."""
    shells = shape.Shells
    if len(shells) == 1 and len(shells[0].Faces) == len(shape.Faces):
        return shells[0]
    return shape


def sewn(shape_or_faces, tol=1e-6):
    """The faces sewn across gaps up to tol, as a Shell or a compound of shells and loose faces."""
    faces = list(shape_or_faces.Faces) if hasattr(shape_or_faces, "Faces") else list(shape_or_faces)
    if not faces:
        return Part.makeCompound([])
    plain = _plain(faces)
    if len(faces) < 2 or tol <= 1e-6:
        return _tidy(plain, faces)
    free0 = _free(plain)
    if free0 == 0:
        return _tidy(plain, faces)
    try:
        fused = faces[0].copy().fuse([f.copy() for f in faces[1:]], tol)
        fused = Part.makeCompound(fused.Faces) if fused.ShapeType not in ("Shell", "Compound") else fused
        fused.sewShape()
    except Exception:
        return _tidy(plain, faces)
    if fused.Faces and _free(fused) < free0:
        return _tidy(fused, faces)
    return _tidy(plain, faces)
