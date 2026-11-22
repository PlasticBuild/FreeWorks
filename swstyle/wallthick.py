# SPDX-License-Identifier: LGPL-2.1-or-later
""

import FreeCAD as App
import Part

_shells = {}


def _shell(solid):
    key = id(solid)
    got = _shells.get(key)
    if got is None or got[0] is not solid:
        got = _shells[key] = (solid, solid.Shells[0] if len(solid.Shells) == 1 else Part.Compound(solid.Faces))
        if len(_shells) > 16:
            _shells.pop(next(iter(_shells)))
    return got[1]


def thickness_at(solid, point, normal, limit=None, on_surface=False):
    """The diameter of the biggest ball touching the surface at point (normal: the surface's normal
    there, either way) inside solid, at most limit; None off the surface. on_surface: the point is
    known to be on it (a face's own sample), so that is not checked again."""
    try:
        point, n = App.Vector(point), App.Vector(normal)
        if n.Length < 1e-12:
            return None
        n.normalize()
        size = solid.BoundBox.DiagonalLength
        tol = 1e-6 * max(1.0, size)
        shell = _shell(solid)
        if not on_surface and shell.distToShape(Part.Vertex(point))[0] > 1e-4 * max(1.0, size):
            return None
        step = 1e-3 * max(1.0, size)
        if solid.isInside(point - n * step, tol, False):
            inward = n * -1.0
        elif solid.isInside(point + n * step, tol, False):
            inward = n
        else:
            return None
        bb = solid.BoundBox
        hi = min(bb.XLength, bb.YLength, bb.ZLength) / 2.0      # no ball is wider than the part
        if limit is not None:
            hi = min(hi, max(0.0, float(limit)) / 2.0)
        if hi <= 0:
            return 0.0

        def room(r):
            """How far the ball of radius r clears the surface (below zero: it does not fit)."""
            c = point + inward * r
            gap = shell.distToShape(Part.Vertex(c))[0] - r
            if gap >= -tol and not solid.isInside(c, tol, False):
                return -max(1.0, r)
            return gap
        hi_room = room(hi)
        if hi_room >= -tol:
            return 2.0 * hi
        lo, lo_room = 0.0, 0.0
        close = max(5e-4 * hi, tol)     # to 0.05 % of the widest ball the part could hold
        # secant steps on the clearance, halving when they stall (Kimi's search, 2-3x fewer probes)
        for _k in range(40):
            if hi - lo <= close:
                break
            mid = (lo * hi_room - hi * lo_room) / (hi_room - lo_room) if lo_room > 0.0 else (lo + hi) / 2.0
            if not lo < mid < hi:
                mid = (lo + hi) / 2.0
            value = room(mid)
            if value >= -tol:
                lo, lo_room = mid, max(0.0, value)
            else:
                hi, hi_room = mid, value
        return lo + hi
    except Exception:
        return None


def face_thickness(solid, face, n=5, corners_zero=False):
    ""




    try:
        u0, u1, v0, v1 = face.ParameterRange
        edges = Part.Compound(face.Edges)
        margin = 1e-4 * max(1.0, face.BoundBox.DiagonalLength)
        walls, corner = [], []
        for i in range(n):
            for j in range(n):
                u = u0 + (u1 - u0) * (i + 0.5) / n
                v = v0 + (v1 - v0) * (j + 0.5) / n
                if not face.isPartOfDomain(u, v):      # a hole in the face (2D test: quick)
                    continue
                p = face.valueAt(u, v)
                d = edges.distToShape(Part.Vertex(p))[0]
                if d < margin:
                    continue
                w = thickness_at(solid, p, face.normalAt(u, v), on_surface=True)
                if w is None:
                    continue
                (corner if abs(w - 2.0 * d) <= 0.05 * w else walls).append(w)
        if corners_zero:
            every = walls + corner
            return min(every) if every else None
        if walls:
            return min(walls)
        return max(corner) if corner else None
    except Exception:
        return None
