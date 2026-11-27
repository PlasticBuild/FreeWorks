# SPDX-License-Identifier: LGPL-2.1-or-later
""



















from . import editobj

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

import FreeCAD as App
import Part

from . import simplefeature as sf
from .simplefeature import Field

V = App.Vector
COMMAND = "SWStyle_Flex"
SPACING = 1.5         # mm between control points after refining (a bend of radius R strays by
                      # about SPACING**2 / (8 R) between them)
SEW = (1e-4, 1e-3, 1e-2, 5e-2)   # sewing tolerances tried in turn


# --------------------------------------------------------------------------- the deformations
def bending(angle, length):
    """Bend about an axis parallel to X at y = R (R = length / angle), from z = 0 to z = length."""
    def f(p):
        if abs(angle) < 1e-12 or p.z <= 0:
            return V(p)
        radius = length / angle
        t = min(p.z, length)
        phi = t / radius
        y = radius - (radius - p.y) * math.cos(phi)
        z = (radius - p.y) * math.sin(phi)
        if p.z > length:
            extra = p.z - length
            y += extra * math.sin(angle)
            z += extra * math.cos(angle)
        return V(p.x, y, z)
    return f


def twisting(angle, length):
    def f(p):
        t = max(0.0, min(p.z, length)) / length if length > 0 else 0.0
        a = angle * t
        c, s = math.cos(a), math.sin(a)
        return V(p.x * c - p.y * s, p.x * s + p.y * c, p.z)
    return f


def tapering(factor, length):
    def f(p):
        t = max(0.0, min(p.z, length)) / length if length > 0 else 0.0
        k = 1.0 + (factor - 1.0) * t
        return V(p.x * k, p.y * k, p.z)
    return f


def stretching(distance, length):
    def f(p):
        if p.z <= 0:
            return V(p)
        if p.z >= length:
            return V(p.x, p.y, p.z + distance)
        return V(p.x, p.y, p.z * (length + distance) / length)
    return f


# --------------------------------------------------------------------------- reshaping a solid
def _refined(surface, n):
    s = surface.copy()
    u0, u1, v0, v1 = s.bounds()
    for k in range(1, n):
        try:
            s.insertUKnot(u0 + (u1 - u0) * k / n, 1, 1e-9)
        except Exception as _fw_err:
            _fw_log("flex.py:103", _fw_err)
        try:
            s.insertVKnot(v0 + (v1 - v0) * k / n, 1, 1e-9)
        except Exception as _fw_err:
            _fw_log("flex.py:107", _fw_err)
    if s.UDegree < 2 or s.VDegree < 2:
        s.increaseDegree(max(2, s.UDegree), max(2, s.VDegree))
    return s


def _span(surface, fixed, a, b, along_u):
    """Length of an iso-curve of surface between a and b, from a few points."""
    points = [surface.value(a + (b - a) * k / 8.0, fixed) if along_u else surface.value(fixed, a + (b - a) * k / 8.0)
              for k in range(9)]
    return sum((q - p).Length for p, q in zip(points, points[1:]))


def _rational(surface):
    weights = surface.getWeights()
    return any(abs(w - 1.0) > 1e-12 for row in weights for w in row)


def _polynomial(face, spacing):
    """A B-spline without weights through a grid on face's surface, laid out in the surface's own
    parameters (so the face's edges, its curves in those parameters, still fit). Moving the
    control points of a weighted surface (a cylinder, a sphere) is not moving its points: the
    weighted control points of a circle stand well off it."""
    surface = face.Surface
    u0, u1, v0, v1 = face.ParameterRange
    lu = max(_span(surface, v, u0, u1, True) for v in (v0, 0.5 * (v0 + v1), v1))
    lv = max(_span(surface, u, v0, v1, False) for u in (u0, 0.5 * (u0 + u1), u1))
    # closer than the moved control points: a cubic through points on a circle strays by about
    # (step / radius)^4, so a step of a quarter of the spacing keeps edges within the sewing
    nu = max(24, min(200, int(math.ceil(4 * lu / spacing)) + 1))
    nv = max(8, min(200, int(math.ceil(4 * lv / spacing)) + 1))
    grid = [[surface.value(u0 + (u1 - u0) * i / (nu - 1.0), v0 + (v1 - v0) * j / (nv - 1.0))
             for j in range(nv)] for i in range(nu)]
    plain = Part.BSplineSurface()
    plain.approximate(Points=grid, DegMin=3, DegMax=3, Continuity=2, Tolerance=1e-6, ParamType="Uniform")
    plain.scaleKnotsToBounds(u0, u1, v0, v1)
    # a surface closed round on itself stays exactly closed
    # a surface closed round on itself stays exactly closed, and periodic like the original, so
    # ShapeFix can put its seam back
    if surface.isUClosed() and (grid[0][0] - grid[-1][0]).Length < 1e-7:
        for j in range(1, plain.NbVPoles + 1):
            plain.setPole(plain.NbUPoles, j, plain.getPole(1, j))
        if surface.isUPeriodic():
            try:
                plain.setUPeriodic()
            except Exception as _fw_err:
                _fw_log("flex.py:153", _fw_err)
    if surface.isVClosed() and (grid[0][0] - grid[0][-1]).Length < 1e-7:
        for i in range(1, plain.NbUPoles + 1):
            plain.setPole(i, plain.NbVPoles, plain.getPole(i, 1))
        if surface.isVPeriodic():
            try:
                plain.setVPeriodic()
            except Exception as _fw_err:
                _fw_log("flex.py:161", _fw_err)
    return plain


def reshape(shape, f, spacing=SPACING):
    """shape with every point p moved to f(p), as a solid."""
    faces = moved_faces(shape, f, spacing)
    # the faces share their moved edges, so a plain sew (0.1 s) usually closes them already; the gap
    # tolerances below fall back to a fuzzy fuse, which took over 15 minutes on a 35-face plastic part
    # whose plain sew was closed (plastic real-click run 11-27)
    for tolerance in (1e-6,) + tuple(SEW):
        from . import sewtol
        sewn = sewtol.sewn(faces, tolerance)
        shells = sewn.Shells
        if len(shells) == len(shape.Shells) and all(sh.isClosed() for sh in shells) and \
                sum(len(sh.Faces) for sh in shells) == len(faces):
            break
    else:
        raise RuntimeError("Flex could not close the reshaped part: try a gentler flex")
    solids = []
    for shell in shells:
        solid = Part.Solid(shell)
        fixer = Part.ShapeFix.Shape(solid)      # faces come back facing either way: turn them out
        fixer.perform()
        solid = fixer.shape()
        if solid.ShapeType != "Solid" and solid.Solids:
            solid = solid.Solids[0]
        if solid.Volume < 0:
            solid.reverse()
        solids.append(solid)
    return solids[0] if len(solids) == 1 else Part.makeCompound(solids)


def _seam_edges(face):
    seen, twice = set(), set()
    for wire in face.Wires:
        for edge in wire.OrderedEdges:
            key = edge.hashCode()
            (twice if key in seen else seen).add(key)
    return twice


def split_closed(shape):
    """shape with every face that closes round on itself (a hole, a shaft) cut in two along the
    middle, so no face keeps a seam: each half then rebuilds like any other face."""
    cuts = []
    for face in shape.Faces:
        if not _seam_edges(face):
            continue
        try:
            surface = face.Surface
        except Exception:
            continue                  # a surface Python cannot read is not one that closes round
        u0, u1, v0, v1 = face.ParameterRange
        if surface.isUPeriodic() or surface.isUClosed():
            cuts.append(surface.uIso(0.5 * (u0 + u1)).toShape(v0, v1))
        elif surface.isVPeriodic() or surface.isVClosed():
            cuts.append(surface.vIso(0.5 * (v0 + v1)).toShape(u0, u1))
    if not cuts:
        return shape
    result, _ = shape.generalFuse(cuts, 1e-7)
    return result.Solids[0] if len(result.Solids) == 1 else shape


def _surface(face):
    """face's surface as a B-spline."""
    try:
        surface = face.Surface
    except Exception:
        # a face with no surface Python can read: touching it further can crash FreeCAD
        raise RuntimeError("Flex could not read a face of the part")
    if not isinstance(surface, Part.BSplineSurface):
        surface = face.toNurbs().Faces[0].Surface
    if isinstance(surface, Part.BezierSurface):
        surface = _bezier_surface(surface)
    return surface


def _bezier_surface(surface):
    """A Bezier patch (a ruled loft's face stays one after toNurbs) as the same B-spline, so knots
    can be put in and its points moved."""
    du, dv = surface.UDegree, surface.VDegree
    out = Part.BSplineSurface()
    out.buildFromPolesMultsKnots(surface.getPoles(), [du + 1, du + 1], [dv + 1, dv + 1], [0.0, 1.0], [0.0, 1.0],
                                 False, False, du, dv, surface.getWeights())
    return out


def _plain_curve(edge, spacing):
    """edge as a polynomial B-spline over exactly its own length, with knots every spacing mm,
    so moving its poles moves its points."""
    curve = edge.Curve
    if not isinstance(curve, Part.BSplineCurve):
        curve = edge.toNurbs().Edges[0].Curve
    if not isinstance(curve, Part.BSplineCurve):
        # a loft's straight side edges stay Bezier lines after toNurbs: no knots go in, so only
        # their two end points moved and a bent part came out with straight edges (volume lost)
        curve = curve.toBSpline(curve.FirstParameter, curve.LastParameter)
    a, b = edge.FirstParameter, edge.LastParameter
    rational = any(abs(w - 1) > 1e-12 for w in curve.getWeights())
    if rational or abs(curve.FirstParameter - a) > 1e-9 or abs(curve.LastParameter - b) > 1e-9:
        n = max(16, min(300, int(math.ceil(4 * edge.Length / spacing)) + 1))
        points = [edge.valueAt(a + (b - a) * k / (n - 1.0)) for k in range(n)]
        curve = Part.BSplineCurve()
        curve.approximate(Points=points, DegMin=3, DegMax=3, Tolerance=1e-7, ParamType="Uniform")
    else:
        curve = curve.copy()
    m = max(4, int(math.ceil(edge.Length / spacing)))
    k0, k1 = curve.FirstParameter, curve.LastParameter
    for k in range(1, m):
        try:
            curve.insertKnot(k0 + (k1 - k0) * k / m, 1, 1e-9)
        except Exception as _fw_err:
            _fw_log("flex.py:255", _fw_err)
    return curve


def _point_edge(edge):
    """An edge that is only a point: degenerated (a sphere's or cone's pole) or of no length."""
    try:
        if edge.isDegenerated():
            return True
    except Exception as _fw_err:
        _fw_log("flex.py:point edge", _fw_err)
    try:
        return edge.Length < 1e-9
    except Exception:
        return True


def moved_faces(shape, f, spacing=SPACING):
    """The faces of shape, each rebuilt with its points moved by f. Each edge is moved once and
    shared by the faces on both sides of it, so the faces sew back together."""
    # toNurbs on a feature's own shape (with FreeCAD's element names) can give faces without
    # surfaces in 1.1 (a Flex on another Flex did): a plain copy converts cleanly
    nurbs = split_closed(shape).copy().toNurbs()
    edges = {}

    def moved_edge(edge):
        key = edge.hashCode()
        if key not in edges:
            curve = _plain_curve(edge, spacing)
            for i in range(1, curve.NbPoles + 1):
                curve.setPole(i, f(curve.getPole(i)))
            edges[key] = curve.toShape()
        return edges[key]

    faces = []
    for face in nurbs.Faces:
        surface = _surface(face)
        if _rational(surface):
            surface = _polynomial(face, spacing)
        size = face.BoundBox.DiagonalLength
        surface = _refined(surface, max(8, min(120, int(math.ceil(size / spacing)))))
        for i in range(1, surface.NbUPoles + 1):
            for j in range(1, surface.NbVPoles + 1):
                surface.setPole(i, j, f(surface.getPole(i, j)))
        fix = Part.ShapeFix.Face(surface, 1e-6, True)
        for wire in face.Wires:
            try:
                # a point-like edge (the pole of a dome, the tip of a drill point: no curve, no
                # length) is left out: the face closes there by itself
                fix.add(Part.Wire(Part.__sortEdges__([moved_edge(e) for e in wire.Edges if not _point_edge(e)])))
            except Exception:
                raise RuntimeError("Flex could not follow an edge of the part")
        fix.perform()
        faces.append(fix.face())
    return faces


# --------------------------------------------------------------------------- the feature
AXES = {"X": V(1, 0, 0), "Y": V(0, 1, 0), "Z": V(0, 0, 1)}


def frame(base, axis, turn, shift=None, tilt=(0.0, 0.0), centre=None):
    ""


    z = AXES[axis]
    x = {"X": V(0, 1, 0), "Y": V(0, 0, 1), "Z": V(1, 0, 0)}[axis]
    y = z.cross(x)
    rotation = App.Rotation(x, y, z, "ZXY")
    rotation = rotation.multiply(App.Rotation(V(0, 0, 1), turn))
    rx, ry = tilt
    if ry:
        rotation = rotation.multiply(App.Rotation(V(0, 1, 0), ry))
    if rx:
        rotation = rotation.multiply(App.Rotation(V(1, 0, 0), rx))
    origin = V(centre) if centre is not None else base.BoundBox.Center
    return App.Placement(origin + (shift if shift is not None else V(0, 0, 0)), rotation)


def _extent(shape, placement):
    inverse = placement.inverse()
    local = shape.copy()
    local.Placement = inverse.multiply(local.Placement)
    box = local.BoundBox
    return box.ZMin, box.ZMax


PREVIEW_COARSER = 4.0
_FULL = set()           # features being finished (OK): built at the accuracy asked for


def previewing(obj):
    """While the Flex is being made or edited its preview is built coarser (the fine one on a
    40 mm part took over half a minute before the PropertyManager showed)."""
    if obj.Name in _FULL or not App.GuiUp:
        return False
    try:
        import FreeCADGui as Gui
        gdoc = Gui.getDocument(obj.Document.Name)
        editing = gdoc is not None and gdoc.getInEdit() is not None and editobj.of(gdoc.getInEdit()) == obj
    except Exception:
        editing = False
    try:
        new = obj.Shape.isNull()
    except Exception:
        new = True
    if new and not editing:
        # made before its PropertyManager opens (coarse, so the page comes up fast); made with no
        # page at all (a macro), it is built again at full accuracy once the event loop runs
        try:
            from PySide import QtCore
            QtCore.QTimer.singleShot(0, lambda d=obj.Document.Name, n=obj.Name: _finish_unedited(d, n))
        except Exception:
            return False
    return editing or new


def _finish_unedited(doc_name, name):
    try:
        doc = App.getDocument(doc_name)
        obj = doc.getObject(name)
    except Exception:
        return
    if obj is None:
        return
    try:
        import FreeCADGui as Gui
        gdoc = Gui.getDocument(doc_name)
        vp = gdoc.getInEdit() if gdoc is not None else None
        if vp is not None and editobj.of(vp) == obj:
            return              # its page is open: OK builds it fine
    except Exception as _fw_err:
        _fw_log("flex.py:365", _fw_err)
    _FULL.add(name)
    try:
        obj.touch()
        doc.recompute()
    finally:
        _FULL.discard(name)


# --------------------------------------------------------------------------- in the view

# the triad at the part's centre and, for Bending, the bend axis as a blue dash-dot line.
PLANE_COLOURS = ((0.9, 0.15, 0.15), (0.15, 0.75, 0.2))
AXIS_COLOURS = ((0.9, 0.1, 0.1), (0.1, 0.7, 0.1), (0.1, 0.2, 0.9))


def overlay_geometry(obj):
    """{"planes": [(colour, [4 corners])], "triad": (origin, [(colour, tip)]), "bend": (a, b) or None}"""
    base = obj.BaseFeature.Shape if obj.BaseFeature is not None else Part.Shape()
    if base.isNull():
        return None
    triad, start, end = trim_range(obj, base)
    local = base.copy()
    local.Placement = triad.inverse().multiply(local.Placement)
    box = local.BoundBox
    m = max(box.XLength, box.YLength, 1.0) * 0.15
    x0, x1, y0, y1 = box.XMin - m, box.XMax + m, box.YMin - m, box.YMax + m
    planes = []
    for colour, z in zip(PLANE_COLOURS, (start, end)):
        planes.append((colour, [triad.multVec(V(x, y, z)) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]))
    size = max(box.XLength, box.YLength, box.ZLength, 1.0) * 0.25
    origin = triad.Base
    axes = [(c, triad.multVec(d * size)) for c, d in zip(AXIS_COLOURS, (V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)))]
    bend = None
    if obj.FlexType == "Bending" and end - start > 1e-6:
        angle = math.radians(obj.BendAngle.Value)
        if obj.BendBy == "Radius" and obj.BendRadius.Value > 0:
            angle = (end - start) / obj.BendRadius.Value
        if abs(angle) > 1e-9:
            r = (end - start) / angle
            bend = (triad.multVec(V(x0, r, start)), triad.multVec(V(x1, r, start)))
    return {"planes": planes, "triad": (origin, axes), "bend": bend}


class Overlay:
    """The trim planes, triad and bend axis drawn while the Flex PropertyManager is open."""

    def __init__(self, obj):
        self.doc, self.name = obj.Document.Name, obj.Name
        self.node = None
        self.key = None
        import time
        self.born = time.time()
        from PySide import QtCore
        self.timer = QtCore.QTimer()
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def obj(self):
        try:
            return App.getDocument(self.doc).getObject(self.name)
        except Exception:
            return None

    def refresh(self):
        obj = self.obj()
        if obj is None:
            self.stop()
            return
        if not self._editing(obj):
            import time
            if time.time() - self.born > 3.0:      # the page is still opening for the first moments
                self.stop()
            return
        try:
            key = tuple(str(getattr(obj, p)) for p in ("FlexType", "BendBy", "BendAngle", "BendRadius", "TrimPlane1",
                                                       "TrimPlane2", "TrimRef1", "TrimRef2", "FlexAxis", "TriadRotation", "TriadX", "TriadY", "TriadZ",
                                                       "TriadRotX", "TriadRotY", "TriadRef") if hasattr(obj, p))
        except Exception:
            key = None
        if key == self.key and self.node is not None:
            return
        self.key = key
        self._remove()
        try:
            geo = overlay_geometry(obj)
        except Exception as error:
            App.Console.PrintLog("FreeCAD Flex planes: %s\n" % error)
            geo = None
        if geo is None:
            return
        from pivy import coin
        import FreeCADGui as Gui
        sep = coin.SoSeparator()
        sep.setName("SWStyle_FlexOverlay")
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        sep.addChild(pick)
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
        sep.addChild(hints)
        for colour, corners in geo["planes"]:
            g = coin.SoSeparator()
            mat = coin.SoMaterial()
            mat.diffuseColor = colour
            mat.emissiveColor = colour
            mat.transparency = 0.7
            g.addChild(mat)
            co = coin.SoCoordinate3()
            co.point.setValues(0, 4, [tuple(c) for c in corners])
            g.addChild(co)
            face = coin.SoFaceSet()
            face.numVertices.setValue(4)
            g.addChild(face)
            line_mat = coin.SoMaterial()
            line_mat.diffuseColor = colour
            line_mat.emissiveColor = colour
            g.addChild(line_mat)
            co2 = coin.SoCoordinate3()
            co2.point.setValues(0, 5, [tuple(c) for c in corners + corners[:1]])
            g.addChild(co2)
            g.addChild(coin.SoLineSet())
            sep.addChild(g)
        origin, axes = geo["triad"]
        for colour, tip in axes:
            g = coin.SoSeparator()
            mat = coin.SoMaterial()
            mat.diffuseColor = colour
            mat.emissiveColor = colour
            g.addChild(mat)
            style = coin.SoDrawStyle()
            style.lineWidth = 3
            g.addChild(style)
            co = coin.SoCoordinate3()
            co.point.setValues(0, 2, [tuple(origin), tuple(tip)])
            g.addChild(co)
            g.addChild(coin.SoLineSet())
            sep.addChild(g)
        if geo["bend"] is not None:
            g = coin.SoSeparator()
            mat = coin.SoMaterial()
            mat.diffuseColor = (0.1, 0.3, 0.9)
            mat.emissiveColor = (0.1, 0.3, 0.9)
            g.addChild(mat)
            style = coin.SoDrawStyle()
            style.linePattern = 0xF18F       # dash-dot
            style.lineWidth = 2
            g.addChild(style)
            co = coin.SoCoordinate3()
            co.point.setValues(0, 2, [tuple(p) for p in geo["bend"]])
            g.addChild(co)
            g.addChild(coin.SoLineSet())
            sep.addChild(g)
        try:
            root = Gui.getDocument(self.doc).ActiveView.getSceneGraph()
            root.addChild(sep)
            self.node = (root, sep)
        except Exception as error:
            App.Console.PrintLog("FreeCAD Flex planes: %s\n" % error)

    def _editing(self, obj):
        try:
            import FreeCADGui as Gui
            vp = Gui.getDocument(self.doc).getInEdit()
            return vp is not None and editobj.of(vp) == obj and Gui.Control.activeDialog()
        except Exception:
            return False

    def _remove(self):
        if self.node is not None:
            try:
                self.node[0].removeChild(self.node[1])
            except Exception as _fw_err:
                _fw_log("flex.py:539", _fw_err)
            self.node = None

    def stop(self):
        try:
            self.timer.stop()
        except Exception as _fw_err:
            _fw_log("flex.py:546", _fw_err)
        self._remove()


_DRAGS = []


def on_trim_plane(widget, event):
    """True when a Qt mouse press on the view is on a Flex trim plane (so a box selection does not
    start there: the plane is dragged)."""
    for d in list(_DRAGS):
        try:
            pos = event.position()
            # coin's pixels are device pixels: on a scaled Windows screen (125 %, 150 %) Qt's are not
            dpr = widget.devicePixelRatioF() or 1.0
            point = (int(pos.x() * dpr), int((widget.height() - pos.y()) * dpr))
            if d.plane_at(*d._ray(point)) is not None:
                return True
        except Exception:
            continue
    return False


class PlaneDrag:
    ""



    def __init__(self, panel):
        self.panel = panel
        self.which = None           # 0 or 1 while a plane is dragged
        self.last = 0.0
        self.view = None
        self.cbs = []
        try:
            import FreeCADGui as Gui
            from pivy import coin
            self.view = Gui.getDocument(panel.obj.Document.Name).ActiveView
            self.cbs = [(coin.SoMouseButtonEvent.getClassTypeId(),
                         self.view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self._button)),
                        (coin.SoLocation2Event.getClassTypeId(),
                         self.view.addEventCallbackPivy(coin.SoLocation2Event.getClassTypeId(), self._move))]
        except Exception as error:
            App.Console.PrintLog("FreeCAD Flex drag: %s\n" % error)
        _DRAGS.append(self)

    def stop(self):
        if self in _DRAGS:
            _DRAGS.remove(self)
        for kind, cb in self.cbs:
            try:
                self.view.removeEventCallbackPivy(kind, cb)
            except Exception as _fw_err:
                _fw_log("flex.py:599", _fw_err)
        self.cbs = []

    def _ray(self, pos):
        point = V(self.view.getPoint(pos[0], pos[1]))
        return point, V(self.view.getViewDirection()).normalize()

    def frame(self):
        obj = self.panel.obj
        base = obj.BaseFeature.Shape
        triad, start, end = trim_range(obj, base)
        geo = overlay_geometry(obj)
        return triad, start, end, geo

    def plane_at(self, point, direction):
        """0 / 1 for the trim plane the ray hits (inside its square), else None (nearest hit first)."""
        triad, start, end, geo = self.frame()
        inv = triad.inverse()
        o = inv.multVec(point)
        d = inv.Rotation.multVec(direction)
        if abs(d.z) < 1e-9:
            return None
        hits = []
        for k, (z, (_c, corners)) in enumerate(zip((start, end), geo["planes"])):
            t = (z - o.z) / d.z
            hit = o + d * t
            local = [inv.multVec(c) for c in corners]
            xs, ys = [c.x for c in local], [c.y for c in local]
            if min(xs) <= hit.x <= max(xs) and min(ys) <= hit.y <= max(ys):
                hits.append((t, k))
        return min(hits)[1] if hits else None

    def z_at(self, point, direction):
        """The triad-Z height under the cursor: where the ray passes nearest the triad's Z axis."""
        triad = self.frame()[0]
        inv = triad.inverse()
        o = inv.multVec(point)
        d = inv.Rotation.multVec(direction)
        a = V(0, 0, 1)
        w = V(o)                        # from the axis origin to the ray origin
        b = a.dot(d)
        denom = 1 - b * b
        if denom < 1e-9:
            return None
        return (a.dot(w) - b * d.dot(w)) / denom

    def _button(self, cb):
        event = cb.getEvent()
        from pivy import coin
        if event.getButton() != coin.SoMouseButtonEvent.BUTTON1:
            return
        pos = event.getPosition().getValue()
        try:
            if event.getState() == coin.SoButtonEvent.DOWN:
                self.which = self.plane_at(*self._ray(pos))
                if self.which is not None:
                    _t, start, end, _g = self.frame()
                    here = self.z_at(*self._ray(pos))
                    self.grab = ((start, end)[self.which] - here) if here is not None else 0.0
                    self.at = pos
                    self._watch_release()
                    cb.setHandled()
            elif self.which is not None:
                self._release(pos)
                cb.setHandled()
        except Exception as error:
            self.which = None
            App.Console.PrintLog("FreeCAD Flex drag: %s\n" % error)

    def _watch_release(self):
        """The navigation style can keep the button's release from the view's callbacks, so the
        drag ends when the left button is seen up."""
        from PySide import QtCore, QtWidgets

        def check():
            if self.which is None:
                return
            if QtWidgets.QApplication.mouseButtons() & QtCore.Qt.LeftButton:
                QtCore.QTimer.singleShot(40, check)
            else:
                self._release(self.at)
        QtCore.QTimer.singleShot(40, check)

    def _release(self, pos):
        if self.which is None:
            return
        try:
            self.drag_to(self.z_at(*self._ray(pos)), final=True)
        finally:
            self.which = None

    def _move(self, cb):
        if self.which is None:
            return
        try:
            from PySide import QtCore, QtWidgets
            if not QtWidgets.QApplication.mouseButtons() & QtCore.Qt.LeftButton:
                self._release(self.at)
                return
            self.at = cb.getEvent().getPosition().getValue()
            self.drag_to(self.z_at(*self._ray(self.at)))
            cb.setHandled()
        except Exception as error:
            App.Console.PrintLog("FreeCAD Flex drag: %s\n" % error)

    def drag_to(self, z, final=False):
        """Puts the dragged plane at triad height z (kept inside the part and short of the other plane)."""
        if z is None:
            return
        z += getattr(self, "grab", 0.0)
        obj = self.panel.obj
        triad, start, end = trim_range(obj, obj.BaseFeature.Shape)
        lo = start - obj.TrimPlane1.Value         # where the plane is with no offset
        hi = end + obj.TrimPlane2.Value
        gap = max((hi - lo) * 1e-3, 1e-3)
        if self.which == 0:
            name, value = "TrimPlane1", min(max(z, lo), end - gap) - lo
        else:
            name, value = "TrimPlane2", hi - max(min(z, hi), start + gap)
        value = max(value, 0.0)
        widget = self.panel.widgets.get(name)
        if widget is not None:
            widget.blockSignals(True)
            widget.setValue(value)          # the box follows
            widget.blockSignals(False)
        setattr(obj, name, value)           # the plane moves at once
        import time
        now = time.time()
        if final or now - self.last > 0.35:     # the part bends live, a few rebuilds a second
            self.last = now
            obj.Document.recompute()
            try:
                self.panel._preview()
            except Exception as _fw_err:
                _fw_log("flex.py:733", _fw_err)
        o = _OVERLAYS.get(obj.Name)
        if o is not None:
            o.refresh()


# --------------------------------------------------------------------------- right-click items
DEFAULTS = {f.name: f.default for f in ()}      # filled after SPEC below


def reset(obj):
    """Reset Flex: the flex amounts, trim planes and triad back to where a new Flex starts."""
    for name in ("BendAngle", "BendRadius", "TwistAngle", "TaperFactor", "StretchDistance", "TrimPlane1", "TrimPlane2",
                 "TriadRotation", "FlexAxis", "TriadX", "TriadY", "TriadZ", "TriadRotX", "TriadRotY"):
        if name in DEFAULTS and name in obj.PropertiesList:
            setattr(obj, name, DEFAULTS[name])
    for name in ("TrimRef1", "TrimRef2", "TriadRef"):
        if name in obj.PropertiesList:
            try:
                setattr(obj, name, [])
            except Exception as _fw_err:
                _fw_log("flex.py:754", _fw_err)
    obj.Document.recompute()


def _picked_direction():
    import FreeCADGui as Gui
    for s in Gui.Selection.getSelectionEx("", 0):
        for sub, shape in zip(s.SubElementNames, s.SubObjects):
            try:
                if shape.ShapeType == "Edge":
                    d = shape.Vertexes[-1].Point - shape.Vertexes[0].Point
                    if d.Length > 1e-9:
                        return d.normalize()
                elif shape.ShapeType == "Face":
                    u0, u1, v0, v1 = shape.ParameterRange
                    return shape.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
            except Exception:
                continue
    return None


def align_trim_axis(obj, direction=None):
    """Align Trim Plane Axis to Selection: the triad's Z (the axis the trim planes are square to)
    goes along the part axis nearest the picked edge or face normal."""
    direction = direction or _picked_direction()
    if direction is None:
        return False
    axis = max(AXES, key=lambda k: abs(AXES[k].dot(direction)))
    obj.FlexAxis = axis
    obj.Document.recompute()
    return True


def align_bend_axis(obj, direction=None):
    """Align Bend Axis to Selection: the triad turns about Z so the bend axis (its X) runs along
    the picked edge, as far as it can square to Z."""
    direction = direction or _picked_direction()
    base = obj.BaseFeature.Shape if obj.BaseFeature is not None else None
    if direction is None or base is None:
        return False
    plain = frame(base, obj.FlexAxis, 0.0)        # the bend axis turns about Z only
    d = plain.Rotation.inverted().multVec(direction)
    if abs(d.x) < 1e-9 and abs(d.y) < 1e-9:
        return False
    obj.TriadRotation = math.degrees(math.atan2(d.y, d.x))
    obj.Document.recompute()
    return True


def align_principal(obj):
    """Center and Align to Principle: the triad at the part's centre with Z along its longest side."""
    base = obj.BaseFeature.Shape if obj.BaseFeature is not None else None
    if base is None:
        return False
    box = base.BoundBox
    obj.FlexAxis = max((("X", box.XLength), ("Y", box.YLength), ("Z", box.ZLength)), key=lambda t: t[1])[0]
    obj.TriadRotation = 0.0
    for name in ("TriadRotX", "TriadRotY"):
        if name in obj.PropertiesList:
            setattr(obj, name, 0.0)
    if "TriadRef" in obj.PropertiesList:
        obj.TriadRef = []
    obj.Document.recompute()
    return True


def menu_entries(obj):
    """(key, text, run, enabled) for the right-click menu while the Flex PropertyManager is open."""
    picked = _picked_direction() is not None
    return [("ResetFlex", "Reset Flex", lambda: reset(obj), True),
            ("AlignTrimPlaneAxis", "Align Trim Plane Axis to Selection", lambda: align_trim_axis(obj), picked),
            ("AlignBendAxis", "Align Bend Axis to Selection", lambda: align_bend_axis(obj),
             picked and obj.FlexType == "Bending"),
            ("CenterAlignPrinciple", "Center and Align to Principle", lambda: align_principal(obj), True)]


_OVERLAYS = {}


class FlexPanel(sf.Panel):
    def __init__(self, obj, *args, **kw):
        super().__init__(obj, *args, **kw)
        try:
            if _drop_whole_bodies(obj):
                self._changed()        # the boxes show it and the preview rebuilds
        except Exception as error:
            App.Console.PrintLog("FreeCAD Flex: %s\n" % error)
        try:
            self.follow()
        except Exception as _fw_err:
            _fw_log("flex.py:839", _fw_err)
        try:
            _OVERLAYS[obj.Name] = Overlay(obj)
        except Exception as error:
            App.Console.PrintLog("FreeCAD Flex planes: %s\n" % error)
        self.drag = PlaneDrag(self)

    def _changed(self, *args):
        ""

        if self.busy:
            return super()._changed(*args)
        obj = self.obj
        wa, wr, wb = self.widgets["BendAngle"], self.widgets["BendRadius"], self.widgets["BendBy"]
        by = None

        def moved(w, value):
            # the field shows the driven value rounded to its decimals (26.74 for 26.7399...): only a
            # change past that rounding is a typed one (else a typed Angle 30 was taken as Radius 26.74
            # and the bend went back to 90)
            # (the box keeps the 2-decimal value it was given even when its decimals are raised later, as
            # the document's precision is: 4 decimals made 25.46 against 25.4648 read as typed, and a
            # typed Angle 30 went back to 90 on OK. pf386 step 16; a typed change under 0.005 mm/deg is none)
            try:
                tol = max(0.51 * 10 ** -w.decimals(), 0.0051)
            except Exception:
                tol = 0.0051
            return abs(w.value() - value) > tol
        if moved(wr, obj.BendRadius.Value):
            by = "Radius"
        elif moved(wa, obj.BendAngle.Value):
            by = "Angle"
        if by is not None:
            wb.blockSignals(True)
            wb.setCurrentText(by)
            wb.blockSignals(False)
        super()._changed(*args)
        self.follow()

    def follow(self):
        """The bend's other value, from the one that drives it."""
        obj = self.obj
        if obj.FlexType != "Bending" or getattr(obj, "BaseFeature", None) is None:
            return
        try:
            _triad, start, end = trim_range(obj, obj.BaseFeature.Shape)
        except Exception:
            return
        length = end - start
        if length <= 1e-6:
            return
        wa, wr = self.widgets["BendAngle"], self.widgets["BendRadius"]
        if obj.BendBy == "Radius" and obj.BendRadius.Value > 0:
            angle = math.degrees(length / obj.BendRadius.Value)
            if abs(angle - obj.BendAngle.Value) > 1e-6 and abs(angle) <= 360.0:
                obj.BendAngle = angle
            spin, value = wa, obj.BendAngle.Value
        elif obj.BendBy == "Angle" and abs(obj.BendAngle.Value) > 1e-9:
            radius = abs(length / math.radians(obj.BendAngle.Value))
            if abs(radius - obj.BendRadius.Value) > 1e-6:
                obj.BendRadius = radius
            spin, value = wr, obj.BendRadius.Value
        else:
            return
        try:
            obj.purgeTouched()      # the driven value does not change the shape
        except Exception as _fw_err:
            _fw_log("flex.py:893", _fw_err)
        spin.blockSignals(True)
        spin.setValue(value)
        spin.blockSignals(False)

    def _stop_overlay(self):
        o = _OVERLAYS.pop(getattr(self.obj, "Name", ""), None)
        if o is not None:
            o.stop()
        d = getattr(self, "drag", None)
        if d is not None:
            d.stop()

    def reject(self):
        self._stop_overlay()
        return super().reject()

    def accept(self):
        self._stop_overlay()
        _FULL.add(self.obj.Name)
        try:
            self.obj.touch()
            return super().accept()
        finally:
            _FULL.discard(self.obj.Name)


def trim_ref_ok(shape):
    ""

    try:
        if shape is None or shape.isNull():
            return False
        if shape.ShapeType in ("Vertex", "Face"):
            return True
        return not shape.Solids and len(shape.Faces) == 1
    except Exception:
        return False


def _drop_whole_bodies(obj):
    ""

    changed = False
    for name in ("TrimRef1", "TrimRef2"):
        if name not in obj.PropertiesList:
            continue
        value = getattr(obj, name)
        if not value:
            continue
        keep = []
        for item in value:
            source, subs = (item, ("",)) if isinstance(item, App.DocumentObject) else item
            subs = subs if isinstance(subs, (list, tuple)) else [subs]
            try:
                shape = Part.getShape(source)
                good = [s for s in subs if trim_ref_ok(shape.getElement(s) if s else shape)]
            except Exception:
                good = []
            if good:
                keep.append((source, tuple(good)))
        if len(keep) != len(value) or any(len(k[1]) != len(v[1] if isinstance(v[1], (list, tuple)) else [v[1]])
                                          for k, v in zip(keep, value) if not isinstance(v, App.DocumentObject)):
            setattr(obj, name, keep)
            changed = True
    return changed


def triad_shift(obj):
    ""
    try:
        return V(*(float(getattr(obj, n, 0.0)) for n in ("TriadX", "TriadY", "TriadZ")))
    except Exception:
        return V(0, 0, 0)


def triad_centre(obj):
    ""

    if "TriadRef" not in obj.PropertiesList:
        return None
    for _o, shape in sf.elements(obj, "TriadRef"):
        try:
            if shape.ShapeType == "Vertex":
                return V(shape.Point)
            if shape.ShapeType in ("Edge", "Face"):
                return V(shape.CenterOfMass)
        except Exception as _fw_err:
            _fw_log("flex.py:triad-centre", _fw_err)
    return None


def triad_tilt(obj):
    ""
    def deg(name):
        v = getattr(obj, name, 0.0)
        return float(getattr(v, "Value", v))
    return deg("TriadRotX"), deg("TriadRotY")


def trim_range(obj, base):
    """(triad placement, start z, end z) of the region the flex works on, in the triad's frame."""
    triad = frame(base, obj.FlexAxis, obj.TriadRotation.Value, triad_shift(obj), triad_tilt(obj), triad_centre(obj))
    z0, z1 = _extent(base, triad)
    start, end = z0, z1
    # a trim plane put on a vertex, face or plane picked (else at the part's end), then offset
    for i, name in enumerate(("TrimRef1", "TrimRef2")):
        picked = [p for p in (sf.elements(obj, name) if name in obj.PropertiesList else []) if trim_ref_ok(p[1])]
        if picked:
            shape = picked[0][1]
            if shape.ShapeType == "Vertex":
                point = shape.Point
            elif shape.ShapeType != "Face" and len(shape.Faces) == 1:
                point = shape.Faces[0].CenterOfMass      # a datum plane comes as a compound of its face
            else:
                point = getattr(shape, "CenterOfMass", None) or shape.BoundBox.Center
            z = triad.inverse().multVec(point).z
            if i == 0:
                start = z
            else:
                end = z
    start += obj.TrimPlane1.Value
    end -= obj.TrimPlane2.Value
    return triad, start, end


def _split_at(solid, triad, heights):
    """The solid with its faces split where the trim planes (square to the triad's Z at these
    heights) cross it; one solid still, or the solid as it was when the split fails."""
    try:
        size = solid.BoundBox.DiagonalLength * 2.0 + 10.0
        z = triad.Rotation.multVec(V(0, 0, 1))
        lo = min(triad.inverse().multVec(v.Point).z for v in solid.Vertexes)
        hi = max(triad.inverse().multVec(v.Point).z for v in solid.Vertexes)
        tools = []
        for h in heights:
            if lo + 1e-6 < h < hi - 1e-6:
                tools.append(Part.Plane(triad.multVec(V(0, 0, h)), z).toShape(-size, size, -size, size))
        if not tools:
            return solid
        from BOPTools import SplitAPI
        pieces = SplitAPI.slice(solid, tools, "Split").Solids
        if len(pieces) < 2:
            return solid
        joined = pieces[0].fuse(pieces[1:])
        if len(joined.Solids) != 1 or abs(joined.Volume - solid.Volume) > 1e-6 * max(solid.Volume, 1.0):
            return solid
        return joined.Solids[0]
    except Exception:
        return solid


def _bend_fits(base, triad, angle, length, start=None):
    """A bend whose axis lies inside the bent material would fold the part through itself (the far
    side comes back inverted and the volume collapses): stop with a message instead, as a rebuild
    error, so the part is not silently replaced by a folded one. Only the material between the trim
    planes is bent; what lies past them only turns or stays, so it may reach past the axis."""
    if abs(angle) < 1e-12:
        return
    radius = length / angle
    local = base.copy()
    local.Placement = triad.inverse().multiply(local.Placement)
    box = local.BoundBox
    if start is not None:
        try:
            big = max(box.DiagonalLength, 1.0) * 4
            slab = Part.makeBox(2 * big, 2 * big, length, V(-big, -big, start))
            cut = local.common(slab)
            if cut.Solids or cut.Faces:
                box = cut.BoundBox
        except Exception as _fw_err:
            _fw_log("flex.py:bend_fits", _fw_err)
    if (radius > 0 and box.YMax >= radius - 1e-6) or (radius < 0 and box.YMin <= radius + 1e-6):
        raise RuntimeError("The bend is too tight: its axis (bend radius %.2f mm) falls inside the part, which "
                           "reaches %.2f mm from the triad. Use a smaller bend angle, a larger radius, or "
                           "turn the triad." % (abs(radius), box.YMax if radius > 0 else -box.YMin))


def _compute(obj, base):
    triad, start, end = trim_range(obj, base)
    length = end - start
    if length <= 1e-6:
        raise RuntimeError("The trim planes overlap: the region to flex has no length")
    kind = obj.FlexType
    if kind == "Bending":
        angle = math.radians(obj.BendAngle.Value)
        if obj.BendBy == "Radius":
            if obj.BendRadius.Value <= 0:
                raise RuntimeError("The bend radius must be more than 0")
            angle = length / obj.BendRadius.Value
        _bend_fits(base, triad, angle, length, start)
        deform = bending(angle, length)
    elif kind == "Twisting":
        deform = twisting(math.radians(obj.TwistAngle.Value), length)
    elif kind == "Tapering":
        if obj.TaperFactor <= 0:
            raise RuntimeError("The taper factor must be more than 0")
        deform = tapering(obj.TaperFactor, length)
    else:
        if obj.StretchDistance.Value <= -length:
            raise RuntimeError("The stretch would squash the region to nothing")
        deform = stretching(obj.StretchDistance.Value, length)
    # the flex runs from the first trim plane, in the triad's frame
    local = triad.multiply(App.Placement(V(0, 0, start), App.Rotation()))
    to_local, to_global = local.inverse(), local

    def f(p):
        return to_global.multVec(deform(to_local.multVec(p)))
    solids = base.Solids or [base]
    if getattr(obj, "HardEdges", True):

        # those edges through the flex (off: smooth faces right across)
        solids = [_split_at(s, triad, (start, end)) for s in solids]
    # Flex accuracy: 1 (coarse, fast) to 10 (fine): the control point spacing
    accuracy = min(max(int(getattr(obj, "Accuracy", 5)), 1), 10)
    spacing = SPACING * 5.0 / accuracy
    if previewing(obj):
        spacing *= PREVIEW_COARSER      # the PropertyManager's live preview: OK builds it fine
    shapes = []
    for solid in solids:
        shapes.append(reshape(solid, f, spacing))
    result = shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes)
    if not result.isValid():
        result.fix(1e-6, 1e-6, 1e-4)
    if not getattr(obj, "HardEdges", True):
        # Hard edges off: the faces split for the flex are joined again into smooth ones
        try:
            result = result.removeSplitter()
        except Exception as _fw_err:
            _fw_log("flex.py:1071", _fw_err)
    return result, None


def _is(*kinds):
    return lambda obj: obj.FlexType in kinds


SPEC = sf.Spec(
    COMMAND, "Flex", "Flex",
    "Bends, twists, tapers or stretches the part between two trim planes.",
    "FEATURES_FLEX", "Part_Shapebuilder",
    [Field("FlexType", "radio", "Flex type", "Bending", values=["Bending", "Twisting", "Tapering", "Stretching"],
           box="Flex Input"),

     # drives (BendBy, kept off the page)
     Field("BendBy", "enum", "Bend by", "Angle", values=["Angle", "Radius"], shown=lambda o: False, box="Flex Input"),
     Field("BendAngle", "angle", "Angle", 0.0,
           low=-360.0, high=360.0, shown=_is("Bending"), box="Flex Input"),
     Field("BendRadius", "length", "Radius", 1000000.0, high=1e7, shown=_is("Bending"), box="Flex Input"),
     Field("TwistAngle", "angle", "Angle", 0.0, low=-3600.0, high=3600.0, shown=_is("Twisting"), box="Flex Input"),
     Field("TaperFactor", "float", "Taper factor", 0.5, low=0.01, high=100.0, shown=_is("Tapering"),
           box="Flex Input"),
     Field("StretchDistance", "distance", "Distance", 20.0, shown=_is("Stretching"), box="Flex Input"),
     Field("HardEdges", "bool", "Hard edges", True, box="Flex Input"),
     Field("TrimRef1", "pick", "Trim plane 1: reference entity", what=("Vertex", "Face", ""), optional=True,
           tip="A vertex, face or plane the first trim plane goes through", box="Trim Plane 1"),
     Field("TrimPlane1", "length", "Trim plane 1: trim distance", 0.0,
           tip="How far in from the part's first end the flex starts", box="Trim Plane 1"),
     Field("TrimRef2", "pick", "Trim plane 2: reference entity", what=("Vertex", "Face", ""), optional=True,
           tip="A vertex, face or plane the second trim plane goes through", box="Trim Plane 2"),
     Field("TrimPlane2", "length", "Trim plane 2: trim distance", 0.0,
           tip="How far in from the part's other end the flex stops", box="Trim Plane 2"),
     Field("TriadRef", "pick", "Selection for triad", what=("Vertex", "Edge", "Face"), optional=True,
           tip="A vertex, or an edge or face whose center the triad sits on; empty: the part's center",
           box="Triad"),
     Field("TriadX", "distance", "X", 0.0, tip="Moves the triad along X from where it sits", box="Triad"),
     Field("TriadY", "distance", "Y", 0.0, tip="Moves the triad along Y from where it sits", box="Triad"),
     Field("TriadZ", "distance", "Z", 0.0, tip="Moves the triad along Z from where it sits", box="Triad"),

     # Front Plane, which is FreeCAD's Y (a loft out from the Front Plane flexes along its length)
     Field("FlexAxis", "enum", "Flex axis", "Y", tip="The triad's Z axis", values=["X", "Y", "Z"], box="Triad"),
     Field("TriadRotX", "angle", "X rotation angle", 0.0, low=-360.0, high=360.0,
           tip="Tilts the triad about its X axis", box="Triad"),
     Field("TriadRotY", "angle", "Y rotation angle", 0.0, low=-360.0, high=360.0,
           tip="Tilts the triad about its Y axis", box="Triad"),
     Field("TriadRotation", "angle", "Z rotation angle", 0.0, low=-360.0, high=360.0,
           tip="Turns the triad about its Z axis: sets which way the part bends", box="Triad"),
     Field("Accuracy", "int", "Flex accuracy (1 coarse - 10 fine)", 5, low=1, high=10, box="Flex Options")],
    _compute, needs_body=True, refine=False, panel=FlexPanel)


def register():
    sf.register(SPEC)

DEFAULTS.update({f.name: f.default for f in SPEC.fields})
