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

import math
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import naming, smflatten
from . import pmboxes
from .smbaseflange import _box
from .smedgeflange import error_label

UNFOLD = "SWStyle_SMUnfold"
FOLD = "SWStyle_SMFold"
GROUP = "Unfold"
V = App.Vector
TOL = 1e-5

BEND_NAMES = {"SMBaseBend": "BaseBend", "SMBendWall": "EdgeBend", "SMFoldWall": "SketchBend", "SWJog": "JogBend",
              "SMHem": "HemBend", "SWMiterFlange": "MiterBend",
              "SWConvertSolid": "SharpBend", "SWInsertBends": "SharpBend"}


# ================================================================ geometry
def _cylinders(shape):
    return [f for f in shape.Faces if f.Surface.TypeId == "Part::GeomCylinder"]


def _coaxial(f, g):
    a, b = f.Surface, g.Surface
    if abs(abs(a.Axis.dot(b.Axis)) - 1) > 1e-7:
        return False
    d = b.Center - a.Center
    return (d - a.Axis * d.dot(a.Axis)).Length < 1e-5


def _radial(surface, p):
    q = p - surface.Center
    return q - surface.Axis * q.dot(surface.Axis)


def _ends(face):
    """The radial directions of a cylindrical face's two straight ends."""
    s = face.Surface
    u0, u1, _v0, _v1 = face.ParameterRange
    return [_radial(s, s.value(u, 0)).normalize() for u in (u0, u1)]


def _same_ends(f, g):
    a, b = _ends(f), _ends(g)
    return ((a[0] - b[0]).Length < 1e-5 and (a[1] - b[1]).Length < 1e-5) or \
        ((a[0] - b[1]).Length < 1e-5 and (a[1] - b[0]).Length < 1e-5)


def bends_of(shape):
    """Every bend of a sheet metal shape: [(inner faces, outer faces)]. A bend is the coaxial cylinders
    of two radii over the same angle; a cut through it leaves several faces, still one bend."""
    groups = []
    for f in _cylinders(shape):
        for g in groups:
            if _coaxial(g[0], f) and _same_ends(g[0], f):
                g.append(f)
                break
        else:
            groups.append([f])
    out = []
    lines = [e for e in shape.Edges if e.Curve.TypeId == "Part::GeomLine"]
    for g in groups:
        radii = sorted({round(f.Surface.Radius, 6) for f in g})
        if len(radii) >= 2:
            inner = [f for f in g if abs(f.Surface.Radius - radii[0]) < 1e-6]
            outer = [f for f in g if abs(f.Surface.Radius - radii[1]) < 1e-6]
            out.append((inner, outer))
        elif any(all(_radial(g[0].Surface, v.Point).Length < 1e-6 for v in e.Vertexes) for e in lines):
            out.append(([], g))     # a closed hem: no inside radius, the inside is the sharp edge on the axis
    return out
    return out


def probe(inner, outer):
    """A point in the middle of the bend's material (kept on the feature to find the bend again)."""
    f = outer[0]
    u0, u1, v0, v1 = f.ParameterRange
    p = f.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
    ri = inner[0].Surface.Radius if inner else 0.0
    return p - _radial(f.Surface, p).normalize() * ((f.Surface.Radius - ri) / 2)


def find_bend(shape, point):
    """The bend whose material holds point, or a hole cut through it: (inner faces, outer faces)."""
    for inner, outer in bends_of(shape):
        s = outer[0].Surface
        rho = _radial(s, point).Length
        if not ((inner[0].Surface.Radius if inner else 0.0) - TOL <= rho <= s.Radius + TOL):
            continue
        u, _v = s.parameter(point)
        u0, u1, _v0, _v1 = outer[0].ParameterRange
        while u < u0 - 1e-7:
            u += 2 * math.pi
        if u > u1 + 1e-7:
            continue
        ts = [(v.Point - s.Center).dot(s.Axis) for f in inner + outer for v in f.Vertexes]
        t = (point - s.Center).dot(s.Axis)
        if min(ts) - TOL <= t <= max(ts) + TOL:
            return inner, outer
    return None


def bend_of_face(shape, face):
    """The bend a picked face belongs to."""
    if face.Surface.TypeId != "Part::GeomCylinder":
        return None
    for inner, outer in bends_of(shape):
        if any(face.isSame(f) for f in inner + outer):
            return inner, outer
    return None


class Bend:
    """One bend and its frame: axis line (C, a), radii, angle; after orient(): the frame at the fixed end."""

    def __init__(self, inner, outer, kfactor):
        s = outer[0].Surface
        self.C, self.a = V(s.Center), V(s.Axis)
        self.surface = s
        self.Ri, self.Ro = (inner[0].Surface.Radius if inner else 0.0), s.Radius
        self.T = self.Ro - self.Ri
        self.Rn = self.Ri + kfactor * self.T
        self.u0, self.u1, _v0, _v1 = outer[0].ParameterRange
        self.theta = self.u1 - self.u0
        ts = [(v.Point - self.C).dot(self.a) for f in inner + outer for v in f.Vertexes]
        self.t0, self.t1 = min(ts), max(ts)
        self.inner, self.outer = inner, outer
        self.ref = outer[0]
        # u turns about the axis or against it (an indirect cylinder): sweep turns e(u0) towards e(u1)
        e0, e1 = self.radial(self.u0), self.radial(self.u0 + min(self.theta, 0.1))
        self.sweep = self.a if e0.cross(e1).dot(self.a) > 0 else self.a * -1

    def radial(self, u):
        p = _radial(self.surface, self.surface.value(u, 0))
        p.normalize()
        return p

    def seam_face(self, u, d=0.01):
        e = self.radial(u)
        pts = [self.C + self.a * t + e * r for t, r in ((self.t0 - d, self.Ri - d), (self.t1 + d, self.Ri - d),
                                                        (self.t1 + d, self.Ro + d), (self.t0 - d, self.Ro + d))]
        return Part.Face(Part.makePolygon(pts + pts[:1]))

    def in_sector(self, p):
        """p lies in the bend's sector (between its two ends, between its radii)."""
        rho = _radial(self.surface, p).Length
        if not (self.Ri - TOL <= rho <= self.Ro + TOL):
            return False
        u, _v = self.surface.parameter(p)
        while u < self.u0 - 1e-7:
            u += 2 * math.pi
        return u <= self.u1 + 1e-7

    def orient(self, fixed_at_u0):
        """ax turns the fixed end onto the moving end; e0 points from the axis to the fixed end;
        d0 runs from the fixed end into the bend (and along the flat strip)."""
        self.ax = V(self.sweep) if fixed_at_u0 else self.sweep * -1
        self.e0 = self.radial(self.u0 if fixed_at_u0 else self.u1)
        self.d0 = self.ax.cross(self.e0)
        self.L = self.theta * self.Rn

    def moving(self):
        """Placement taking the far side from folded to flat."""
        rot = App.Placement(V(), App.Rotation(self.ax, -math.degrees(self.theta)), self.C)
        return App.Placement(self.d0 * self.L, App.Rotation()).multiply(rot)

    def to_flat(self, p):
        q = p - self.C
        t = q.dot(self.ax)
        rad = q - self.ax * t
        phi = math.atan2(rad.dot(self.d0), rad.dot(self.e0))
        if phi < -1e-6:
            phi += 2 * math.pi
        phi = min(max(phi, 0.0), self.theta)
        return self.C + self.e0 * self.Ri + self.d0 * (phi * self.Rn) + self.ax * t

    def to_folded(self, p, r=None):
        """A point of the flat strip -> the bend (at its own depth, or at radius r)."""
        q = p - self.C
        s, t = q.dot(self.d0), q.dot(self.ax)
        depth = q.dot(self.e0) if r is None else r
        return self.C + App.Rotation(self.ax, math.degrees(s / self.Rn)).multVec(self.e0 * depth) + self.ax * t


def _straight(pts):
    a, b = pts[0], pts[-1]
    d = b - a
    if d.Length < 1e-9:
        return False
    d.normalize()
    return all(((p - a) - d * (p - a).dot(d)).Length < 1e-5 for p in pts)


def _map_wire(wire, fn, n=24):
    edges = []
    for e in wire.OrderedEdges:
        pts = [fn(p) for p in e.discretize(n)]
        if _straight(pts):
            edges.append(Part.makeLine(pts[0], pts[-1]))
        else:
            c = Part.BSplineCurve()
            c.interpolate(pts)
            edges.append(c.toShape())
    return Part.Wire(Part.__sortEdges__(edges))


def _strip(bend, pieces):
    """The bend's material laid flat: its outer faces unrolled, thickened by the sheet thickness."""
    faces = []
    for piece in pieces:
        for f in piece.Faces:
            if f.Surface.TypeId == "Part::GeomCylinder" and abs(f.Surface.Radius - bend.Ro) < 1e-6 \
                    and _coaxial(f, bend.ref):
                faces.append(Part.makeFace([_map_wire(w, bend.to_flat) for w in f.Wires], "Part::FaceMakerBullseye"))
    solids = [f.extrude(bend.e0 * bend.T) for f in faces]
    return solids[0].fuse(solids[1:]).removeSplitter() if len(solids) > 1 else solids[0]


def wrap(bend, face):
    """A face of the flat strip, wrapped round the bend through the whole thickness."""
    ri = max(bend.Ri, 1e-4)        # a closed hem has no inside radius
    cyl = Part.Cylinder()
    cyl.Center, cyl.Axis, cyl.Radius = bend.C, bend.ax, ri
    wires = [_map_wire(w, lambda p: bend.to_folded(p, ri)) for w in face.Wires]
    f = Part.Face(cyl, wires[0])
    f.validate()
    for w in wires[1:]:
        f = f.cut(Part.Face(cyl, w)).Faces[0]
    inside = bend.to_folded(face.CenterOfMass, bend.Ri + bend.T / 2)
    solid = f.makeOffsetShape(bend.Ro - ri, 1e-7, fill=True)
    if not solid.isInside(inside, TOL, True):
        solid = f.makeOffsetShape(ri - bend.Ro, 1e-7, fill=True)
    return solid


def _holding(pieces, point):
    return next((i for i, s in enumerate(pieces) if s.isInside(point, TOL, True)), None)


def _contact(solid, seam):
    """solid sits on the seam face (shares material across it), not just touching it at an edge."""
    n, p = seam.normalAt(0, 0), seam.CenterOfMass
    area = 0.0
    for f in solid.Faces:
        if f.Surface.TypeId == "Part::GeomPlane" and abs(abs(f.normalAt(0, 0).dot(n)) - 1) < 1e-7 \
                and abs((f.CenterOfMass - p).dot(n)) < TOL:
            area += f.common(seam).Area
    return area > 1e-6


def unfold_bend(shape, bend, fixed_point):
    """Lay one bend flat. Returns the new shape and the step (bend, zones) that Fold reverses."""
    res, _map = shape.generalFuse([bend.seam_face(bend.u0), bend.seam_face(bend.u1)])
    pieces = res.Solids
    ia = _holding(pieces, fixed_point)
    if ia is None:
        raise ValueError("The fixed face is not on the part")
    A = pieces[ia]

    def in_bend(piece):
        return any(f.Surface.TypeId == "Part::GeomCylinder" and _coaxial(f, bend.ref)
                   and min(abs(f.Surface.Radius - bend.Ro), abs(f.Surface.Radius - bend.Ri)) < 1e-6 for f in piece.Faces)
    inbend = [s for i, s in enumerate(pieces) if i != ia and in_bend(s)]
    rest = [s for i, s in enumerate(pieces) if i != ia and not in_bend(s)]
    seams = [_contact(A, bend.seam_face(u)) for u in (bend.u0, bend.u1)]
    if not inbend or all(seams):
        # the fixed side holds both ends: the part closes round this bend
        raise ValueError("This bend cannot be unfolded from the fixed face")
    bend.orient(seams[0])
    strip = _strip(bend, inbend)
    M = bend.moving()
    moved = []
    for s in rest:
        c = s.copy()
        c.transformShape(M.toMatrix())
        moved.append(c)
    out = A.fuse([strip] + moved).removeSplitter()
    if len(out.Solids) == 1:
        out = out.Solids[0]
    return out, {"bend": bend, "A": A, "strip": strip, "B": moved, "far": rest, "M": M}


def unfold(shape, probes, fixed_point, kfactor):
    """Unfold the bends at probes (points in their material) keeping fixed_point's side still."""
    steps = []
    probes = list(probes)
    for i in range(len(probes)):
        found = find_bend(shape, probes[i])
        if found is None:
            raise ValueError("A bend to unfold is no longer there")
        bend = Bend(found[0], found[1], kfactor)
        shape, step = unfold_bend(shape, bend, fixed_point)
        for j in range(i + 1, len(probes)):
            if any(s.isInside(probes[j], TOL, True) for s in step["far"]):
                probes[j] = step["M"].multVec(probes[j])
        steps.append(step)
    return shape, steps


def _solids(shape):
    return [s for s in shape.Solids if s.Volume > 1e-9]


def fold_back(steps, pieces):
    """Material in the flat shape -> folded, through the steps in reverse."""
    for step in reversed(steps):
        bend, inv = step["bend"], step["M"].inverse().toMatrix()
        out = []
        for r in pieces:
            out.extend(_solids(r.common(step["A"])))
            for b in step["B"]:
                for c in _solids(r.common(b)):
                    c.transformShape(inv)
                    out.append(c)
            for s in _solids(r.common(step["strip"])):
                level = (bend.C + bend.e0 * (bend.Ri + bend.T / 2)).dot(bend.e0)
                wires = s.slice(bend.e0, level)
                if not wires:
                    continue
                face = Part.makeFace(wires, "Part::FaceMakerBullseye")
                face.translate(bend.e0 * -(bend.T / 2))
                for f in face.Faces:
                    out.extend(_solids(wrap(bend, f)))
        pieces = out
    return pieces


def fold_back_added(steps, pieces):
    """Material added on the flat shape moves with the side it stands on (on a strip it is left out)."""
    for step in reversed(steps):
        inv = step["M"].inverse().toMatrix()
        out = []
        for r in pieces:
            zones = [("A", step["A"]), ("strip", step["strip"])] + [("B", b) for b in step["B"]]
            kind, _z = min(zones, key=lambda z: r.distToShape(z[1])[0])
            if kind == "B":
                r = r.copy()
                r.transformShape(inv)
            if kind != "strip":
                out.append(r)
        pieces = out
    return pieces


def fold(folded, flat, current, steps):
    """The folded part with what changed between the flat shape and current taken back through the bends."""
    removed = _solids(flat.cut(current))
    added = _solids(current.cut(flat))
    out = folded
    if removed:
        out = out.cut(fold_back(steps, removed), 1e-5)
    if added:
        back = fold_back_added(steps, added)
        if back:
            out = out.fuse(back, 1e-5)
    out = out.removeSplitter()
    return out.Solids[0] if len(out.Solids) == 1 else out


def point_back(steps, p):
    """A point of the flat shape -> folded."""
    for step in reversed(steps):
        bend = step["bend"]
        if step["A"].isInside(p, TOL, True):
            continue
        if step["strip"].isInside(p, TOL, True):
            p = bend.to_folded(p)
            continue
        p = step["M"].inverse().multVec(p)
    return p


def inside_point(face):
    """A point on face (its centre when that lies on it)."""
    p = face.CenterOfMass
    if face.isInside(p, 1e-6, True):
        return p
    mesh = face.tessellate(0.1)
    a, b, c = (mesh[0][i] for i in mesh[1][0])
    return (a + b + c) * (1.0 / 3)


# ================================================================ naming
def _maker(body, before, point):
    """The feature that made the bend at point (the first one in the body's history that has it)."""
    for o in body.Group:
        if o is before:
            break
        if not o.isDerivedFrom("PartDesign::Feature") or o.Shape.isNull():
            continue
        try:
            if find_bend(o.Shape, point) is not None:
                return o
        except Exception:
            continue
    return None


def _axis_key(inner, outer):
    """Where a bend's axis lies (its point nearest the origin), unchanged by cuts through the bend."""
    s = outer[0].Surface
    c = s.Center - s.Axis * s.Center.dot(s.Axis)
    return tuple(round(x, 3) + 0.0 for x in (c.x, c.y, c.z))


def bend_names(body, feature, shape):
    """[(name, probe)] for every bend of shape (the shape before feature): EdgeBend1, SketchBend1..."""
    found = []
    for inner, outer in bends_of(shape):
        p = probe(inner, outer)
        maker = _maker(body, feature, p) if body is not None else None
        kind = BEND_NAMES.get(type(getattr(maker, "Proxy", None)).__name__, "Bend")
        order = body.Group.index(maker) if maker is not None and maker in body.Group else 10 ** 6
        found.append((order, _axis_key(inner, outer), kind, p))
    found.sort(key=lambda x: (x[0], x[1]))
    counts, out = {}, []
    for _o, _k, kind, p in found:
        counts[kind] = counts.get(kind, 0) + 1
        out.append(("%s%d" % (kind, counts[kind]), p))
    return out


# ================================================================ features
def _body_of(obj):
    return next((p for p in obj.InList if p.TypeId == "PartDesign::Body"), None)


def _kfactor(body):
    root = smflatten.root(body) if body is not None else None
    from . import smbendtable
    try:
        return smbendtable.k_of(root, body.Shape) if root is not None else 0.5
    except ValueError:
        return float(getattr(root, "SWKFactor", 0.5))


_LAST = None        # the open Unfold/Fold PropertyManager
_STEPS = {}         # (document, Unfold name) -> the steps of its last unfold, for Fold


class SWUnfold:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyString", "FixedFace", GROUP, "Fixed face as picked")
        add("App::PropertyVector", "FixedPoint", GROUP, "A point on the fixed face")
        add("App::PropertyStringList", "Bends", GROUP, "Bends to unfold")
        add("App::PropertyVectorList", "BendPoints", GROUP, "A point in each bend's material")
        add("App::PropertyFloat", "KFactor", GROUP, "K-Factor")
        obj.KFactor = 0.5
        obj.Proxy = self

    def execute(self, obj):
        base = obj.BaseFeature
        if base is None:
            raise ValueError("Unfold: needs a sheet metal part")
        from . import pointrefs        # the fixed face and the bends follow an edit before the unfold
        pointrefs.follow(obj, base, "FixedPoint", "face")
        pointrefs.follow(obj, base, "BendPoints", "bend")
        shape = base.Shape.copy()
        if not obj.BendPoints:
            _STEPS[(obj.Document.Name, obj.Name)] = []
            obj.Shape = shape
            return
        flat, steps = unfold(shape, obj.BendPoints, obj.FixedPoint, obj.KFactor)
        _STEPS[(obj.Document.Name, obj.Name)] = steps
        obj.Shape = flat

    def steps(self, obj):
        key = (obj.Document.Name, obj.Name)
        if key not in _STEPS:
            self.execute(obj)
        return _STEPS[key]

    def dumps(self):
        return None

    def loads(self, state):
        return None


class SWFold:
    def __init__(self, obj, unfold_obj):
        add = obj.addProperty
        add("App::PropertyLink", "Unfold", GROUP, "The Unfold this folds back")
        add("App::PropertyString", "FixedFace", GROUP, "Fixed face as picked")
        add("App::PropertyVector", "FixedPoint", GROUP, "A point on the fixed face")
        add("App::PropertyStringList", "Bends", GROUP, "Bends to fold")
        obj.Unfold = unfold_obj
        obj.Proxy = self

    def execute(self, obj):
        unf, base = obj.Unfold, obj.BaseFeature
        if unf is None or base is None or unf.BaseFeature is None:
            raise ValueError("Fold: needs an Unfold before it")
        from . import pointrefs
        pointrefs.follow(obj, base, "FixedPoint", "face")
        current = base.Shape.copy()
        if not obj.Bends:
            obj.Shape = current
            return
        steps = unf.Proxy.steps(unf)
        result = fold(unf.BaseFeature.Shape.copy(), unf.Shape.copy(), current, steps)
        # bends of the Unfold left out stay flat
        keep = [p for n, p in zip(unf.Bends, unf.BendPoints) if n not in obj.Bends]
        if keep:
            result, _steps = unfold(result, keep, unf.FixedPoint, unf.KFactor)
        # a different fixed face: that face stays where it is in the flat shape
        if obj.FixedFace and obj.FixedFace != unf.FixedFace and keep == []:
            # the face at the fixed point (the name was the flat shape's when picked: an edit renumbers it)
            from .smnormalcut import face_at
            i = face_at(current, obj.FixedPoint) if obj.FixedPoint.Length > 1e-12 else None
            result = _hold(result, current, "Face%d" % (i + 1) if i is not None else obj.FixedFace, steps)
        obj.Shape = result

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _hold(result, flat, face_name, steps):
    """result moved so that the face picked on the flat shape stays where it is."""
    try:
        face = flat.getElement(face_name)
    except Exception:
        return result
    if face.Surface.TypeId != "Part::GeomPlane":
        return result
    p = inside_point(face)
    q = next((p + (v.Point - p) * 0.5 for v in face.Vertexes
              if (v.Point - p).Length > 1e-3 and face.isInside(p + (v.Point - p) * 0.5, 1e-6, True)), None)
    if q is None:
        return result
    n = face.normalAt(0, 0)
    a, b = point_back(steps, p), point_back(steps, q)
    folded = next((f for f in result.Faces if f.Surface.TypeId == "Part::GeomPlane"
                   and f.isInside(a, 1e-5, True) and f.isInside(b, 1e-5, True)), None)
    if folded is None:
        return result
    m = folded.normalAt(0, 0)
    x1, x2 = (b - a).normalize(), (q - p).normalize()
    rot = App.Rotation(x2, n.cross(x2), n, "ZXY").multiply(App.Rotation(x1, m.cross(x1), m, "ZXY").inverted())
    out = result.copy()
    out.transformShape(App.Placement(p - rot.multVec(a), rot).toMatrix())
    return out


def _icon(name):
    try:
        import SheetMetalTools
        return os.path.join(SheetMetalTools.icons_path, name + ".svg")
    except Exception:
        return ""


class ViewProviderUnfold:
    ICON = "SheetMetal_UnfoldUnattended"

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return _icon(self.ICON)

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        obj.Document.openTransaction("Edit " + obj.Label)
        try:
            Gui.Control.showDialog((FoldPanel if is_fold(obj) else UnfoldPanel)(obj, False))
        except BaseException:
            try:
                obj.Document.abortTransaction()
            except Exception:
                pass
            raise
        return True

    def unsetEdit(self, vobj, mode=0):
        return False

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderFold(ViewProviderUnfold):
    ICON = "SheetMetal_Refold"


def is_unfold(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWUnfold"


def is_fold(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWFold"


def open_unfold(body):
    """The last Unfold of body not yet folded back, else None."""
    folded = {o.Unfold for o in body.Group if is_fold(o) and o.Unfold is not None}
    return next((o for o in reversed(body.Group) if is_unfold(o) and o not in folded), None)


def _new(body, name, proxy, vp):
    doc = body.Document
    base = body.Tip
    obj = doc.addObject("PartDesign::FeaturePython", name)
    proxy(obj)
    if App.GuiUp:
        vp(obj.ViewObject)
    body.addObject(obj)
    obj.Label = naming.next_label(doc, name)
    if base is not None:
        try:
            base.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("smunfold.py:650", _fw_err)
    return obj


def make_unfold(body):
    obj = _new(body, "Unfold", SWUnfold, ViewProviderUnfold)
    obj.KFactor = _kfactor(body)
    return obj


def make_fold(body, unfold_obj):
    obj = _new(body, "Fold", lambda o: SWFold(o, unfold_obj), ViewProviderFold)
    obj.FixedFace = unfold_obj.FixedFace
    obj.FixedPoint = unfold_obj.FixedPoint
    return obj


# ================================================================ PropertyManagers
def _list(name, color, tip, rows=1):
    w = QtWidgets.QListWidget()
    w.setObjectName(name)
    w.setToolTip(tip)
    w.setMaximumHeight(22 + 18 * rows)
    if color == "#d6ecff":
        pmboxes.mark(w, True)
    else:
        w.setStyleSheet("QListWidget { background: %s; }" % color)
    return w


class _DeleteKey(QtCore.QObject):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.KeyPress and event.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            self.panel.remove_current(watched)
            return True
        if event.type() == QtCore.QEvent.FocusIn:
            self.panel.set_active(watched)
        return False


class UnfoldPanel:
    """The Unfold PropertyManager: Fixed face, Bends to unfold, Collect All Bends."""
    TITLE = "Unfold"
    ICON = "SheetMetal_UnfoldUnattended"
    BENDS = "Bends to unfold:"
    PREFIX = "SWSMUnfold"
    HINT_FACE = "Select a face that stays fixed when the bends are unfolded."
    HINT_BENDS = "Select the bends to unfold, or click Collect All Bends."

    def __init__(self, obj, new):
        global _LAST
        _LAST = self
        self.obj = obj
        self.new = new
        self.body = _body_of(obj)
        box = _box("Selections")
        f = box.layout()
        f.addRow(QtWidgets.QLabel("Fixed face:"))
        self.face = _list(self.PREFIX + "FixedFace", "#d6ecff", "Fixed face: the face that stays where it is")
        f.addRow(self.face)
        f.addRow(QtWidgets.QLabel(self.BENDS))
        self.bends = _list(self.PREFIX + "Bends", "#ffd6ec", self.BENDS.rstrip(":"), rows=4)
        f.addRow(self.bends)
        self.collect = QtWidgets.QPushButton("Collect All Bends")
        self.collect.setObjectName("SWSMCollectBends")
        self.collect.clicked.connect(self.collect_all)
        f.addRow(self.collect)
        self.error = error_label()
        f.addRow(self.error)
        box.setProperty("swstyle_pm_title", self.TITLE)
        box.setProperty("swstyle_pm_icon", self.ICON)
        self.form = [box]
        self.keys = _DeleteKey(self)
        for w in (self.face, self.bends):
            w.installEventFilter(self.keys)
        if obj.FixedFace:
            self.face.addItem(obj.FixedFace)
        for n in obj.Bends:
            self.bends.addItem(n)
        self.active = self.bends if obj.FixedFace else self.face
        self._mark()
        self._report()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    # ---------------------------------------------------------------- lists
    def set_active(self, w):
        if w in (self.face, self.bends):
            self.active = w
            self._mark()

    def _mark(self):
        for w in (self.face, self.bends):
            w.setProperty("swstyle_active", w is self.active)
            w.setFrameShape(QtWidgets.QFrame.Box if w is self.active else QtWidgets.QFrame.StyledPanel)

    def remove_current(self, w):
        row = w.currentRow()
        if row < 0:
            return
        if w is self.face:
            self.face.clear()
            self.obj.FixedFace = ""
        else:
            names, points = list(self.obj.Bends), list(self._points())
            del names[row], points[row]
            self._set_bends(names, points)
        self._apply()

    # ---------------------------------------------------------------- picks
    def addSelection(self, doc, name, sub, point):
        if sub.startswith("Face"):
            at = App.Vector(*point) if point else None
            QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub, at))

    def _base_shape(self):
        return self.obj.BaseFeature.Shape

    def _points(self):
        return self.obj.BendPoints

    def _set_bends(self, names, points):
        self.obj.Bends = names
        self.obj.BendPoints = points

    def _steps(self):
        return _STEPS.get((self.obj.Document.Name, self.obj.Name), [])

    def _to_base(self, p):
        """A point picked on the preview -> the part before this feature."""
        return point_back(self._steps(), p)

    def _picked(self, doc_name, name, sub, at):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smunfold.py:792", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None or picked.Shape.isNull():
            return
        face = picked.Shape.getElement(sub)
        if at is None:
            at = inside_point(face)
        p = self._to_base(at) if picked is self.obj else at
        if self.active is self.face:
            if face.Surface.TypeId != "Part::GeomPlane":
                self.error.setText("The fixed face must be a flat face.")
                self.error.show()
                return
            self._fixed(p)
        else:
            self._toggle_bend(picked, face, at, p)
        self._apply()

    def _fixed(self, p):
        base = self._base_shape()
        name = next(("Face%d" % i for i, f in enumerate(base.Faces, 1)
                     if f.Surface.TypeId == "Part::GeomPlane" and f.isInside(p, 1e-5, True)), "")
        self.obj.FixedFace = name
        self.obj.FixedPoint = p
        self.face.clear()
        self.face.addItem(name)
        self.set_active(self.bends)

    def _toggle_bend(self, picked, face, at, p):
        names, points = list(self.obj.Bends), list(self._points())
        # a bend already flat in the preview: pick it again to take it out
        for i, step in enumerate(self._steps()):
            if picked is self.obj and step["strip"].isInside(at, TOL, True):
                del names[i], points[i]
                self._set_bends(names, points)
                return
        base = self._base_shape()
        found = find_bend(base, p) if face.Surface.TypeId == "Part::GeomCylinder" else None
        if found is None:
            self.error.setText("Select a bend.")
            self.error.show()
            return
        for n, q in bend_names(self.body, self.obj, base):
            hit = find_bend(base, q)
            if hit is not None and any(f.isSame(g) for f in hit[1] for g in found[1]):
                if n in names:
                    i = names.index(n)
                    del names[i], points[i]
                else:
                    names.append(n)
                    points.append(q)
                break
        self._set_bends(names, points)

    def collect_all(self):
        allb = bend_names(self.body, self.obj, self._base_shape())
        self._set_bends([n for n, _p in allb], [p for _n, p in allb])
        self._apply()

    # ---------------------------------------------------------------- result
    def _apply(self):
        self.bends.clear()
        for n in self.obj.Bends:
            self.bends.addItem(n)
        self.obj.touch()
        self.obj.Document.recompute()
        self._report()

    def _report(self):
        if "Invalid" in self.obj.State:
            self.error.setText(self.obj.getStatusString())
        elif not self.obj.FixedFace:
            self.error.setText(self.HINT_FACE)
        elif not self.obj.Bends:
            self.error.setText(self.HINT_BENDS)
        else:
            self.error.setText("")
        self.error.setVisible(bool(self.error.text()))
        return not self.error.text()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smunfold.py:879", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smunfold.py:885", _fw_err)

    def accept(self):
        if not self._report():
            return False
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        base = self.obj.BaseFeature if self.new else None
        doc.abortTransaction()
        doc.recompute()
        if base is not None:
            try:
                base.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("smunfold.py:903", _fw_err)
        self._close()
        return True


class FoldPanel(UnfoldPanel):
    """The Fold PropertyManager: Fixed face, Bends to fold, Collect All Bends (the Unfold's bends)."""
    TITLE = "Fold"
    ICON = "SheetMetal_Refold"
    BENDS = "Bends to fold:"
    PREFIX = "SWSMFold"
    HINT_FACE = "Select a face that stays fixed when the bends are folded."
    HINT_BENDS = "Select the bends to fold, or click Collect All Bends."

    def _points(self):
        unf = self.obj.Unfold
        return [dict(zip(unf.Bends, unf.BendPoints))[n] for n in self.obj.Bends]

    def _set_bends(self, names, points):
        self.obj.Bends = names

    def _to_base(self, p):
        return p

    def _toggle_bend(self, picked, face, at, p):
        unf = self.obj.Unfold
        names = list(self.obj.Bends)
        hit = None
        for n, q, step in zip(unf.Bends, unf.BendPoints, unf.Proxy.steps(unf)):
            if n not in names and step["strip"].isInside(at, TOL, True):
                hit = n             # a bend still flat
                break
            if n in names and face.Surface.TypeId == "Part::GeomCylinder":
                found = find_bend(unf.BaseFeature.Shape, q)
                if found is not None and _coaxial(face, found[1][0]) and \
                        any(abs(face.Surface.Radius - f.Surface.Radius) < 1e-6 for f in found[0] + found[1]):
                    hit = n         # a bend folded again: pick it to leave it flat
                    break
        if hit is None:
            self.error.setText("Select a bend of %s." % unf.Label)
            self.error.show()
            return
        if hit in names:
            names.remove(hit)
        else:
            names.append(hit)
        self.obj.Bends = [n for n in unf.Bends if n in names]

    def collect_all(self):
        self.obj.Bends = list(self.obj.Unfold.Bends)
        self._apply()


# ================================================================ commands
def _sheet_body():
    if App.ActiveDocument is None or smflatten.blocked():
        return None
    try:
        if Gui.Control.activeDialog():
            return None
    except Exception as _fw_err:
        _fw_log("smunfold.py:964", _fw_err)
    return smflatten._body()


def _prepicked():
    ""

    out = []
    for s in Gui.Selection.getSelectionEx():
        for sub, p in zip(s.SubElementNames, s.PickedPoints or [None] * len(s.SubElementNames)):
            if sub.startswith("Face"):
                out.append((s.Object.Document.Name, s.Object.Name, sub, App.Vector(p) if p is not None else None))
    return out


def _feed(panel, picks):
    for doc_name, name, sub, at in picks:
        try:
            panel._picked(doc_name, name, sub, at)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: pre-pick %s not taken: %s\n" % (sub, error))


def start_unfold():
    body = _sheet_body()
    if body is None:
        return
    picks = _prepicked()
    doc = body.Document
    doc.openTransaction("Unfold")
    try:
        obj = make_unfold(body)
        doc.recompute()
        panel = UnfoldPanel(obj, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    _feed(panel, picks)


def start_fold():
    body = _sheet_body()
    unf = open_unfold(body) if body is not None else None
    if unf is None:
        return
    doc = body.Document
    doc.openTransaction("Fold")
    try:
        picks = _prepicked()
        obj = make_fold(body, unf)
        doc.recompute()
        panel = FoldPanel(obj, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    _feed(panel, picks)


class UnfoldCommand:
    def GetResources(self):
        return {"Pixmap": _icon("SheetMetal_UnfoldUnattended"), "MenuText": "Unfold",
                "ToolTip": "Flattens the bends you pick, to add cuts across them."}

    def IsActive(self):
        return _sheet_body() is not None

    def Activated(self):
        start_unfold()


class FoldCommand:
    def GetResources(self):
        return {"Pixmap": _icon("SheetMetal_Refold"), "MenuText": "Fold",
                "ToolTip": "Folds back bends that were unfolded."}

    def IsActive(self):
        body = _sheet_body()
        return body is not None and open_unfold(body) is not None

    def Activated(self):
        start_fold()


def register():
    if UNFOLD not in Gui.listCommands():
        Gui.addCommand(UNFOLD, UnfoldCommand())
        Gui.addCommand(FOLD, FoldCommand())
