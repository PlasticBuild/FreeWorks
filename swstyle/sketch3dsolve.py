# SPDX-License-Identifier: LGPL-2.1-or-later
""














































































import math

class _LazyNumpy:
    """numpy on first use: importing it with this module cost about 0.14 s of every FreeCAD start
    (the module is loaded at start for the 3D sketch commands)."""

    def __getattr__(self, name):
        global np
        import numpy
        np = numpy
        return getattr(numpy, name)


np = _LazyNumpy()

ALONG = ("AlongX", "AlongY", "AlongZ")
TWO_LINE = ("Parallel", "Perpendicular", "Equal")

NAMES = {"AlongX": "Along X", "AlongY": "Along Y", "AlongZ": "Along Z", "Fix": "Fix",
         "Coincident": "Coincident", "OnLine": "Coincident", "Midpoint": "Midpoint",
         "Parallel": "Parallel", "Perpendicular": "Perpendicular", "Equal": "Equal",
         "Distance": "Distance", "AtRef": "Coincident", "Angle": "Angle", "OnPlane": "On Plane",
         "OnSurface": "On Surface", "OnEdge": "Coincident", "Diameter": "Diameter", "Radius": "Radius",
         "PlaneDistance": "Distance", "ArcPlane": "Arc", "OnArc": "Coincident", "SymPlane": "Symmetric",
         "OnSketchPlane": "On Plane", "PlaneParallel": "Parallel", "Tangent": "Tangent", "TangentArcs": "Tangent",
         "Concentric": "Concentric", "Coradial": "Coradial", "Collinear": "Collinear", "ArcMidpoint": "Midpoint",
         "PlaneNormal": "Normal", "ParallelYZ": "Parallel YZ", "ParallelZX": "Parallel ZX", "PlaneH": "Horizontal",
         "PlaneV": "Vertical", "AlongDirH": "Horizontal", "AlongDirV": "Vertical", "SplineTangent": "Tangent",
         "SplineTangentArc": "Tangent", "SplineTangentSpline": "Tangent", "CurveLength": "Equal Curve Length", "LineDistance": "Distance",
         "PlaneAngle": "Angle", "AxisDistance": "Distance", "SplineHandle": "Spline handle", "SplineProportional": "Proportional",
         "SplineOnSurface": "Spline on Surface"}
MODEL = ("AtRef", "OnPlane", "OnSurface", "OnEdge", "PlaneDistance", "SymPlane", "PlaneParallel", "PlaneNormal",
         "ParallelYZ", "ParallelZX", "PlaneAngle")   # relations to the model
DIMENSIONS = ("Distance", "Angle", "Diameter", "Radius", "PlaneDistance", "LineDistance", "PlaneAngle",
              "AxisDistance")
ANGLES = ("Angle", "PlaneAngle")
INTERNAL = ("ArcPlane",)       # an entity's own equations: never listed, deleted with the entity
SPLINE_OWN = ("SplineHandle", "SplineProportional", "SplineOnSurface", "SplineLoose", "SplineStyle",
              "SplineGeneric")   # a spline's own settings: never listed, no equations
ENTITY_KINDS = ("L", "S", "P", "C", "A", "Q")
TOL = 1e-7


# ------------------------------------------------------------------ entities
class Entity:
    __slots__ = ("kind", "construction", "points")

    def __init__(self, kind, points, construction=False):
        self.kind = kind
        self.points = list(points)
        self.construction = bool(construction)

    def text(self):
        return " ".join([self.kind, "c" if self.construction else "-"] + [str(p) for p in self.points])

    @staticmethod
    def parse(text):
        parts = text.split()
        if len(parts) < 3 or parts[0] not in ENTITY_KINDS:
            return None
        try:
            return Entity(parts[0], [int(p) for p in parts[2:]], parts[1] == "c")
        except ValueError:
            return None

    def segments(self):
        """(a, b) point pairs along the entity (a spline's through points in order)."""
        return list(zip(self.points[:-1], self.points[1:]))


class Relation:
    __slots__ = ("kind", "points", "values", "ref")

    def __init__(self, kind, points, values=(), ref=None):
        self.kind = kind
        self.points = list(points)
        self.values = list(values)
        self.ref = ref                  # (object name, element) for AtRef

    def text(self):
        out = [self.kind] + [str(p) for p in self.points]
        if self.ref is not None:
            out += [self.ref[0] or "-", self.ref[1]]
        out += [repr(float(v)) for v in self.values]
        return " ".join(out)

    @staticmethod
    def parse(text):
        p = text.split()
        if not p:
            return None
        kind, rest = p[0], p[1:]
        try:
            if kind in ALONG or kind == "Coincident":
                return Relation(kind, [int(rest[0]), int(rest[1])])
            if kind == "Fix":
                return Relation(kind, [int(rest[0])], [float(v) for v in rest[1:4]])
            if kind in ("OnLine", "Midpoint"):
                return Relation(kind, [int(v) for v in rest[:3]])
            if kind == "OnSketchPlane":
                return Relation(kind, [int(v) for v in rest[:4]])
            if kind in TWO_LINE:
                return Relation(kind, [int(v) for v in rest[:4]])
            if kind in ("Distance", "Diameter", "Radius"):
                return Relation(kind, [int(rest[0]), int(rest[1])], [float(rest[2])])
            if kind in ("SymPlane", "PlaneParallel", "PlaneNormal", "ParallelYZ", "ParallelZX"):
                return Relation(kind, [int(rest[0]), int(rest[1])], [float(v) for v in rest[4:13]],
                                ("" if rest[2] == "-" else rest[2], rest[3]))
            if kind in ("Concentric",):
                return Relation(kind, [int(rest[0]), int(rest[1])])
            if kind in ("Coradial", "Collinear"):
                return Relation(kind, [int(v) for v in rest[:4]])
            if kind == "TangentArcs":
                return Relation(kind, [int(v) for v in rest[:4]], [float(rest[4])])
            if kind in ("Tangent", "ArcMidpoint"):
                return Relation(kind, [int(v) for v in rest[:4]], [float(v) for v in rest[4:7]])
            if kind in ("PlaneH", "PlaneV"):
                return Relation(kind, [int(v) for v in rest[:5]])
            if kind == "LineDistance":
                return Relation(kind, [int(v) for v in rest[:3]], [float(rest[3])])
            if kind == "PlaneAngle":
                return Relation(kind, [int(rest[0]), int(rest[1])], [float(v) for v in rest[4:11]],
                                ("" if rest[2] == "-" else rest[2], rest[3]))
            if kind == "SplineTangent":
                return Relation(kind, [int(v) for v in rest[:4]])
            if kind == "SplineTangentSpline":
                return Relation(kind, [int(v) for v in rest])
            if kind == "SplineTangentArc":
                return Relation(kind, [int(v) for v in rest[:4]], [float(v) for v in rest[4:7]])
            if kind == "AxisDistance":
                return Relation(kind, [int(rest[0]), int(rest[1])], [float(v) for v in rest[2:5]])
            if kind == "SplineHandle":
                return Relation(kind, [int(rest[0]), int(rest[1])], [float(v) for v in rest[2:7]])
            if kind == "SplineOnSurface":
                return Relation(kind, [int(rest[0]), int(rest[1])], [], ("" if rest[2] == "-" else rest[2], rest[3]))
            if kind in ("SplineProportional", "SplineLoose", "SplineStyle", "SplineGeneric"):
                return Relation(kind, [int(rest[0]), int(rest[1])])
            if kind == "CurveLength":
                cut = next(i for i, t in enumerate(rest) if not t.lstrip("-").isdigit())
                return Relation(kind, [int(v) for v in rest[:cut]], [float(v) for v in rest[cut:]])
            if kind in ("AlongDirH", "AlongDirV"):
                return Relation(kind, [int(rest[0]), int(rest[1])], [float(v) for v in rest[2:5]])
            if kind in ("ArcPlane", "OnArc"):
                return Relation(kind, [int(v) for v in rest[:3]], [float(v) for v in rest[3:6]])
            if kind == "Angle":
                return Relation(kind, [int(v) for v in rest[:4]], [float(rest[4])])
            if kind in ("OnPlane", "OnSurface", "OnEdge", "PlaneDistance"):
                return Relation(kind, [int(rest[0])], [float(v) for v in rest[3:]],
                                ("" if rest[1] == "-" else rest[1], rest[2]))
            if kind == "AtRef":
                return Relation(kind, [int(rest[0])], [float(v) for v in rest[3:6]],
                                ("" if rest[1] == "-" else rest[1], rest[2]))
        except (IndexError, ValueError):
            return None
        return None

    def name(self):
        return NAMES.get(self.kind, self.kind)


# ------------------------------------------------------------------ residuals
def _v(X, i):
    return X[3 * i:3 * i + 3]


def _unit(v):
    n = math.sqrt(float(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]))
    if n < 1e-12:
        return v * 0.0, 0.0
    return v / n, n


def residual(rel, X, ref_point=None):
    """The relation's equations at point coordinates X (flat x0 y0 z0 x1 ...): all zero when it holds."""
    k, p = rel.kind, rel.points
    if k in ALONG:
        a, b = _v(X, p[0]), _v(X, p[1])
        keep = {"AlongX": (1, 2), "AlongY": (0, 2), "AlongZ": (0, 1)}[k]
        return [a[keep[0]] - b[keep[0]], a[keep[1]] - b[keep[1]]]
    if k == "Fix":
        a = _v(X, p[0])
        return [a[0] - rel.values[0], a[1] - rel.values[1], a[2] - rel.values[2]]
    if k == "AtRef":
        t = ref_point if ref_point is not None else rel.values
        a = _v(X, p[0])
        return [a[0] - t[0], a[1] - t[1], a[2] - t[2]]
    if k == "Coincident":
        d = _v(X, p[0]) - _v(X, p[1])
        return [d[0], d[1], d[2]]
    if k == "OnLine":
        q, a, b = _v(X, p[0]), _v(X, p[1]), _v(X, p[2])
        u, n = _unit(b - a)
        if n == 0.0:
            d = q - a
            return [d[0], d[1], d[2]]
        w = q - a
        c = np.cross(w, u)
        return [c[0], c[1], c[2]]
    if k == "Midpoint":
        d = _v(X, p[0]) - 0.5 * (_v(X, p[1]) + _v(X, p[2]))
        return [d[0], d[1], d[2]]
    if k in TWO_LINE:
        u, nu = _unit(_v(X, p[1]) - _v(X, p[0]))
        w, nw = _unit(_v(X, p[3]) - _v(X, p[2]))
        if k == "Equal":
            return [nu - nw]
        if k == "Perpendicular":
            return [float(np.dot(u, w))]
        c = np.cross(u, w)
        return [c[0], c[1], c[2]]
    if k == "Distance":
        _, n = _unit(_v(X, p[1]) - _v(X, p[0]))
        return [n - rel.values[0]]
    if k == "AxisDistance":
        d = _v(X, p[1]) - _v(X, p[0])
        return [float(d[int(rel.values[2])]) - rel.values[1] * rel.values[0]]
    if k == "Angle":
        u, _ = _unit(_v(X, p[1]) - _v(X, p[0]))
        w, _ = _unit(_v(X, p[3]) - _v(X, p[2]))
        c = np.cross(u, w)
        a = math.atan2(math.sqrt(float(np.dot(c, c))), float(np.dot(u, w)))
        return [a - math.radians(rel.values[0])]
    if k in ("Diameter", "Radius"):
        _, n = _unit(_v(X, p[1]) - _v(X, p[0]))
        return [(2.0 * n if k == "Diameter" else n) - rel.values[0]]
    if k == "OnArc":
        c, a, q = _v(X, p[0]), _v(X, p[1]), _v(X, p[2])
        n = np.array(rel.values[:3], dtype=float)
        _, ra = _unit(a - c)
        _, rq = _unit(q - c)
        return [float(np.dot(q - c, n)), rq - ra]
    if k == "SymPlane":
        a, b = _v(X, p[0]), _v(X, p[1])
        if isinstance(ref_point, tuple) and len(ref_point) == 2:
            base, n = np.array(ref_point[0], dtype=float), np.array(ref_point[1], dtype=float)
        elif len(rel.values) >= 6:
            base, n = np.array(rel.values[:3]), np.array(rel.values[3:6])
        else:
            return []
        n, _ = _unit(n)
        c = np.cross(b - a, n)
        return [float(np.dot(0.5 * (a + b) - base, n)), c[0], c[1], c[2]]
    if k == "Tangent":
        c, r, a, b = _v(X, p[0]), _v(X, p[1]), _v(X, p[2]), _v(X, p[3])
        u, nu = _unit(b - a)
        if p[1] in (p[2], p[3]):
            w, _ = _unit(r - c)
            return [float(np.dot(w, u))]
        n = np.array(rel.values[:3], dtype=float)
        _, rad = _unit(r - c)
        _, dist = _unit(np.cross(c - a, u))
        return [dist - rad, float(np.dot(b - a, n)), float(np.dot(a - c, n))]
    if k == "TangentArcs":
        c1, a1, c2, a2 = _v(X, p[0]), _v(X, p[1]), _v(X, p[2]), _v(X, p[3])
        _, r1 = _unit(a1 - c1)
        _, r2 = _unit(a2 - c2)
        _, d = _unit(c2 - c1)
        return [d - abs(r1 + rel.values[0] * r2)]
    if k == "Concentric":
        d = _v(X, p[0]) - _v(X, p[1])
        return [d[0], d[1], d[2]]
    if k == "Coradial":
        c1, a1, c2, a2 = _v(X, p[0]), _v(X, p[1]), _v(X, p[2]), _v(X, p[3])
        d = c1 - c2
        _, r1 = _unit(a1 - c1)
        _, r2 = _unit(a2 - c2)
        return [d[0], d[1], d[2], r1 - r2]
    if k == "Collinear":
        a, b, c, d = _v(X, p[0]), _v(X, p[1]), _v(X, p[2]), _v(X, p[3])
        u, nu = _unit(b - a)
        if nu == 0.0:
            return []
        e, f = np.cross(c - a, u), np.cross(d - a, u)
        return [e[0], e[1], e[2], f[0], f[1], f[2]]
    if k == "ArcMidpoint":
        q, c, a, b = _v(X, p[0]), _v(X, p[1]), _v(X, p[2]), _v(X, p[3])
        n = np.array(rel.values[:3], dtype=float)
        _, rq = _unit(q - c)
        _, ra = _unit(a - c)
        _, da = _unit(q - a)
        _, db = _unit(q - b)
        return [float(np.dot(q - c, n)), rq - ra, da - db]
    if k in ("PlaneNormal", "ParallelYZ", "ParallelZX"):
        a, b = _v(X, p[0]), _v(X, p[1])
        if k == "PlaneNormal":
            if isinstance(ref_point, tuple) and len(ref_point) == 2:
                n = np.array(ref_point[1], dtype=float)
            elif len(rel.values) >= 6:
                n = np.array(rel.values[3:6])
            else:
                return []
            n, _ = _unit(n)
            c = np.cross(b - a, n)
            return [c[0], c[1], c[2]]
        if len(rel.values) < 9:
            return []
        axis, _ = _unit(np.array(rel.values[6:9], dtype=float))
        return [float(np.dot(b - a, axis))]
    if k in ("PlaneH", "PlaneV"):
        a, b, qa, qb, qc = (_v(X, i) for i in p[:5])
        side = qb - qa
        if k == "PlaneH":
            c = np.cross(b - a, side)
            return [c[0], c[1], c[2]]
        n, _ = _unit(np.cross(side, qc - qa))
        return [float(np.dot(b - a, side)), float(np.dot(b - a, n))]
    if k == "LineDistance":
        q, a, b = _v(X, p[0]), _v(X, p[1]), _v(X, p[2])
        u, nu = _unit(b - a)
        if nu == 0.0:
            return []
        _, dist = _unit(np.cross(q - a, u))
        return [dist - rel.values[0]]
    if k == "PlaneAngle":
        a, b = _v(X, p[0]), _v(X, p[1])
        if isinstance(ref_point, tuple) and len(ref_point) == 2:
            n = np.array(ref_point[1], dtype=float)
        elif len(rel.values) >= 7:
            n = np.array(rel.values[4:7])
        else:
            return []
        n, _ = _unit(n)
        u, nu = _unit(b - a)
        if nu == 0.0:
            return []
        s = min(1.0, abs(float(np.dot(u, n))))
        return [math.asin(s) - math.radians(rel.values[0])]
    if k == "CurveLength":
        na = int(rel.values[0])
        codes = (int(rel.values[1]), int(rel.values[2]))
        normals = (rel.values[3:6], rel.values[6:9])
        parts = (p[:na], p[na:])
        lengths = []
        for which, (idx, code, n) in enumerate(zip(parts, codes, normals)):
            q = [_v(X, i) for i in idx]
            f = ref_point[which] if isinstance(ref_point, tuple) else None
            # FreeCAD's spline (its Tangent ends too) through these points, given all the points now
            spline = (lambda pts, f=f, idx=tuple(idx): f(idx, X)) if f is not None else None
            lengths.append(curve_length(code, q, n, spline))
        return [lengths[0] - lengths[1]]
    if k in ("AlongDirH", "AlongDirV"):
        a, b = _v(X, p[0]), _v(X, p[1])
        c = np.cross(b - a, np.array(rel.values[:3], dtype=float))
        return [c[0], c[1], c[2]]
    if k == "PlaneParallel":
        a, b = _v(X, p[0]), _v(X, p[1])
        if isinstance(ref_point, tuple) and len(ref_point) == 2:
            n = np.array(ref_point[1], dtype=float)
        elif len(rel.values) >= 6:
            n = np.array(rel.values[3:6])
        else:
            return []
        n, _ = _unit(n)
        return [float(np.dot(b - a, n))]
    if k == "OnSketchPlane":
        q, a, b, c = _v(X, p[0]), _v(X, p[1]), _v(X, p[2]), _v(X, p[3])
        n, size = _unit(np.cross(b - a, c - a))
        if size == 0.0:
            return [0.0]
        return [float(np.dot(q - a, n))]
    if k == "ArcPlane":
        c, a, b = _v(X, p[0]), _v(X, p[1]), _v(X, p[2])
        n = np.array(rel.values[:3], dtype=float)
        out = [float(np.dot(a - c, n))]
        if p[2] != p[1]:
            _, ra = _unit(a - c)
            _, rb = _unit(b - c)
            out += [float(np.dot(b - c, n)), ra - rb]
        return out
    if k == "PlaneDistance":
        q = _v(X, p[0])
        if callable(ref_point):
            signed = ref_point(q)[0]
        elif len(rel.values) >= 8:
            b, n = np.array(rel.values[2:5]), np.array(rel.values[5:8])
            signed = float(np.dot(q - b, n))
        else:
            return []
        return [signed - rel.values[1] * rel.values[0]]
    if k in ("OnPlane", "OnSurface", "OnEdge"):
        q = _v(X, p[0])
        if callable(ref_point):
            return list(ref_point(q))           # the model's face or edge, read now (see sketch3d.ref_residual)
        if k == "OnPlane" and len(rel.values) >= 6:
            b, n = np.array(rel.values[:3]), np.array(rel.values[3:6])
            return [float(np.dot(q - b, n))]
        return []                               # the model's face is gone: the relation holds nothing
    return []


def curve_length(code, q, n, spline=None):
    """Length of a line (code 0), arc (1: centre, start, end, counterclockwise about n), spline (2: through
    the points; spline(points) when FreeCAD can build it, else the polyline) or circle (3)."""
    if code == 0:
        return float(np.linalg.norm(q[1] - q[0]))
    if code in (1, 3):
        c, a = q[0], q[1]
        r = float(np.linalg.norm(a - c))
        if code == 3:
            return 2.0 * math.pi * r
        nn, _ = _unit(np.array(n, dtype=float))
        u, _ = _unit(a - c)
        w, _ = _unit(q[2] - c)
        ang = math.atan2(float(np.dot(np.cross(u, w), nn)), float(np.dot(u, w)))
        if ang <= 1e-12:
            ang += 2.0 * math.pi
        return r * ang
    if spline is not None:
        return float(spline([tuple(v) for v in q]))
    return float(sum(np.linalg.norm(q[i + 1] - q[i]) for i in range(len(q) - 1)))


class Solver:
    """Solves a set of relations over n points. refs: {relation index: (x, y, z)} for AtRef targets
    read from the model now."""

    def __init__(self, n, relations, refs=None):
        self.n = n
        self.relations = list(relations)
        self.refs = refs or {}

    def _rows(self, X):
        out = []
        for i, rel in enumerate(self.relations):
            out.extend(residual(rel, X, self.refs.get(i)))
        return np.array(out, dtype=float)

    def jacobian(self, X):
        rows, cols = [], []
        r0_all = []
        for i, rel in enumerate(self.relations):
            r0 = np.array(residual(rel, X, self.refs.get(i)), dtype=float)
            r0_all.append(r0)
            block = np.zeros((len(r0), 3 * self.n))
            for pt in set(rel.points):
                for c in range(3):
                    j = 3 * pt + c
                    h = 1e-6 * max(1.0, abs(X[j]))
                    Xp = X.copy()
                    Xp[j] += h
                    Xm = X.copy()
                    Xm[j] -= h
                    rp = np.array(residual(rel, Xp, self.refs.get(i)), dtype=float)
                    rm = np.array(residual(rel, Xm, self.refs.get(i)), dtype=float)
                    block[:, j] = (rp - rm) / (2 * h)
            rows.append(block)
        if not rows:
            return np.zeros((0, 3 * self.n)), np.zeros(0)
        return np.vstack(rows), np.concatenate(r0_all) if r0_all else np.zeros(0)

    def solve(self, X, iterations=60):
        """(solved X, True when every relation holds)."""
        X = np.array(X, dtype=float)
        if not self.relations:
            return X, True
        scale = max(1.0, float(np.max(np.abs(X))) if X.size else 1.0)
        for _ in range(iterations):
            J, r = self.jacobian(X)
            err = float(np.max(np.abs(r))) if r.size else 0.0
            if err < TOL * scale:
                return X, True
            step, *_ = np.linalg.lstsq(J, -r, rcond=None)
            # damp huge jumps (a relation far from holding): keep the sketch's shape readable
            big = float(np.max(np.abs(step))) if step.size else 0.0
            if big > 10 * scale:
                step *= 10 * scale / big
            X = X + step
        J, r = self.jacobian(X)
        err = float(np.max(np.abs(r))) if r.size else 0.0
        return X, err < 1e-5 * scale

    def freedom(self, X):
        """(degrees of freedom left, set of points that can no longer move)."""
        X = np.array(X, dtype=float)
        total = 3 * self.n
        if total == 0:
            return 0, set()
        J, _ = self.jacobian(X)
        if J.shape[0] == 0:
            return total, set()
        _, s, vt = np.linalg.svd(J, full_matrices=True)
        tol = max(J.shape) * (s[0] if s.size else 0.0) * 1e-9
        rank = int(np.sum(s > max(tol, 1e-10)))
        null = vt[rank:]
        fixed = set()
        for i in range(self.n):
            if null.shape[0] == 0 or float(np.max(np.abs(null[:, 3 * i:3 * i + 3]))) < 1e-7:
                fixed.add(i)
        return total - rank, fixed

    def rank(self, X):
        J, _ = self.jacobian(np.array(X, dtype=float))
        if J.shape[0] == 0:
            return 0
        return int(np.linalg.matrix_rank(J, tol=1e-9 * max(1.0, float(np.max(np.abs(J))))))


# ------------------------------------------------------------------ editing helpers
def flat(points):
    out = []
    for p in points:
        out += [float(p[0]), float(p[1]), float(p[2])]
    return out


def unflat(X):
    return [(float(X[3 * i]), float(X[3 * i + 1]), float(X[3 * i + 2])) for i in range(len(X) // 3)]


def relation_adds_freedom_loss(n, relations, new, X, refs=None):
    ""

    before = Solver(n, relations, refs).rank(X)
    s = Solver(n, list(relations) + [new], refs)
    Y, ok = s.solve(X)
    if not ok:
        return "conflict", Y
    if s.rank(Y) <= before:
        return "redundant", Y
    return "ok", Y


def compact(points, entities, relations):
    """Drops points no entity uses (and the relations on them) and renumbers the rest.
    Returns (points, entities, relations)."""
    used = set()
    for e in entities:
        used.update(e.points)
    order = sorted(used)
    new_index = {old: i for i, old in enumerate(order)}
    pts = [points[i] for i in order]
    ents = [Entity(e.kind, [new_index[p] for p in e.points], e.construction) for e in entities]
    rels = []
    for r in relations:
        if all(p in new_index for p in r.points):
            rels.append(Relation(r.kind, [new_index[p] for p in r.points], r.values, r.ref))
    return pts, ents, rels


def merge_points(points, entities, relations, keep, drop):
    """Point drop becomes point keep (Merge Points / a click on an existing point)."""
    if keep == drop:
        return points, entities, relations
    ents = [Entity(e.kind, [keep if p == drop else p for p in e.points], e.construction) for e in entities]
    rels = []
    for r in relations:
        pts = [keep if p == drop else p for p in r.points]
        if r.kind in ALONG + ("Coincident", "Concentric") and pts[0] == pts[1]:
            continue
        rels.append(Relation(r.kind, pts, r.values, r.ref))
    # drop is unused now: compact renumbers
    return compact(points, ents, rels)
