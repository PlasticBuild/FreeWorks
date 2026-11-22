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

import FreeCAD as App

V = App.Vector
KINDS = ("Plane", "Cylinder", "Sphere")
UNRECOGNIZED = "Unrecognized"
COLOURS = {"Plane": (0.25, 0.5, 1.0), "Cylinder": (0.2, 0.75, 0.3), "Sphere": (1.0, 0.6, 0.1),
           UNRECOGNIZED: (0.9, 0.15, 0.15)}


# --------------------------------------------------------------------------- fitting
class Data:
    """The mesh's points, triangles, facet normals and neighbours, read once."""

    def __init__(self, mesh):
        self.mesh = mesh
        self.points, self.tris = mesh.Topology
        facets = mesh.Facets
        self.normals = [f.Normal for f in facets]
        self.neighbours = [[j for j in f.NeighbourIndices if 0 <= j < len(facets)] for f in facets]

    def __len__(self):
        return len(self.tris)


def data(mesh):
    return mesh if isinstance(mesh, Data) else Data(mesh)


def _points(d, facets):
    idx = set()
    for i in facets:
        idx.update(d.tris[i])
    return [d.points[k] for k in idx]


def fit(mesh, facets, kind, deviation, strip=False):
    """Max distance of the facets' points from the best kind (Plane / Cylinder / Sphere), or None."""
    import numpy as np
    d = data(mesh)
    pts = np.array([[p.x, p.y, p.z] for p in _points(d, facets)])
    if len(pts) < 3:
        return None
    normals = np.array([[d.normals[i].x, d.normals[i].y, d.normals[i].z] for i in facets])
    c = pts.mean(axis=0)
    if kind == "Plane":
        _u, _s, vt = np.linalg.svd(pts - c)
        n = vt[-1]
        return float(np.abs((pts - c) @ n).max())
    if kind == "Sphere":
        if len(pts) < 4:
            return None
        a = np.hstack([2 * pts, np.ones((len(pts), 1))])
        b = (pts ** 2).sum(axis=1)
        sol, *_ = np.linalg.lstsq(a, b, rcond=None)
        centre = sol[:3]
        r = math.sqrt(max(sol[3] + centre @ centre, 0.0))
        if r <= 0:
            return None
        return float(np.abs(np.linalg.norm(pts - centre, axis=1) - r).max())
    if kind == "Cylinder":
        # the axis is square to every facet normal: the normals' least direction
        _u, s, vt = np.linalg.svd(normals - 0.0)
        axis = vt[-1] / np.linalg.norm(vt[-1])
        if s[-2] < 0.05 * max(s[0], 1e-12):
            # the normals hardly turn: too narrow a strip to find the axis yet (Facet Shape grows
            # from one facet), so it fits as far as it is flat; a whole region that flat is a plane
            return fit(d, facets, "Plane", deviation) if strip else None
        e1 = np.cross(axis, [1, 0, 0] if abs(axis[0]) < 0.9 else [0, 1, 0])
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(axis, e1)
        q = np.stack([(pts - c) @ e1, (pts - c) @ e2], axis=1)
        a = np.hstack([2 * q, np.ones((len(q), 1))])
        b = (q ** 2).sum(axis=1)
        sol, *_ = np.linalg.lstsq(a, b, rcond=None)
        r = math.sqrt(max(sol[2] + sol[:2] @ sol[:2], 0.0))
        if r <= 0:
            return None
        return float(np.abs(np.linalg.norm(q - sol[:2], axis=1) - r).max())
    return None


def classify(mesh, facets, deviation):
    """The kind the facets fit best within deviation, or Unrecognized."""
    mesh = data(mesh)
    best = None
    for kind in KINDS:
        try:
            d = fit(mesh, facets, kind, deviation)
        except Exception:
            d = None
        if d is not None and d <= deviation:
            return kind          # Plane first, then Cylinder, then Sphere: the simplest that fits
        if d is not None and (best is None or d < best[0]):
            best = (d, kind)
    return UNRECOGNIZED


# --------------------------------------------------------------------------- regions
def _angle(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, a.dot(b)))))


def regions(mesh, detail=20.0):
    """Facets grouped into smooth regions: neighbours whose normals bend less than detail degrees."""
    d = data(mesh)
    seen = [False] * len(d)
    out = []
    for start in range(len(d)):
        if seen[start]:
            continue
        seen[start] = True
        group, stack = [start], [start]
        while stack:
            i = stack.pop()
            ni = d.normals[i]
            for j in d.neighbours[i]:
                if seen[j]:
                    continue
                if _angle(ni, d.normals[j]) <= detail:
                    seen[j] = True
                    group.append(j)
                    stack.append(j)
        out.append(group)
    return out


def segment(mesh, detail=20.0, deviation=0.05):
    """[(kind, [facet indices])] for the whole mesh."""
    d = data(mesh)
    return [(classify(d, group, deviation), group) for group in regions(d, detail)]


def grow(mesh, seed, kind, deviation, limit=200000, bend=30.0):
    """Facet Shape: the facets around seed that fit kind within deviation, grown out from it
    (a ring of neighbours at a time; a ring that no longer fits is tried facet by facet)."""
    d = data(mesh)
    group = [seed]
    inside = {seed}
    frontier = [seed]
    while frontier and len(group) < limit:
        ring = []
        for i in frontier:
            for j in d.neighbours[i]:
                # across a sharp bend is another face, whatever it fits
                if j not in inside and j not in ring and _angle(d.normals[i], d.normals[j]) <= bend:
                    ring.append(j)
        if not ring:
            break
        dev = fit(d, group + ring, kind, deviation, True) if len(group) + len(ring) >= 3 else 0.0
        if dev is not None and dev <= deviation:
            ok = ring
        else:
            ok = []
            for j in ring:
                dj = fit(d, group + ok + [j], kind, deviation, True) if len(group) + len(ok) >= 2 else 0.0
                if dj is not None and dj <= deviation:
                    ok.append(j)
        group += ok
        inside.update(ok)
        frontier = ok
    return group


def assign(segments, facets, kind):
    """segments with the facets taken out of their old segments and put in one of kind."""
    taken = set(facets)
    out = []
    for k, group in segments:
        rest = [i for i in group if i not in taken]
        if rest:
            out.append((k, rest))
    out.append((kind, sorted(taken)))
    return out


def legend(segments):
    """{kind: (segments, facets)} for the legend."""
    out = {k: [0, 0] for k in KINDS + (UNRECOGNIZED,)}
    for k, group in segments:
        out[k][0] += 1
        out[k][1] += len(group)
    return {k: tuple(v) for k, v in out.items()}


def all_recognized(segments):
    return bool(segments) and all(k != UNRECOGNIZED for k, _g in segments)


# --------------------------------------------------------------------------- Convert to standard BREP
def to_brep(mesh, tolerance=0.05):
    """A solid (a shell when the mesh is open) from the mesh, planar segments merged into one face each."""
    import Part
    shape = Part.Shape()
    shape.makeShapeFromMesh(mesh.Topology, tolerance)
    try:
        shell = Part.Shell(shape.Faces)
        solid = Part.Solid(shell) if shell.isClosed() else shell
    except Exception:
        solid = shape
    try:
        solid = solid.removeSplitter()
    except Exception as _fw_err:
        _fw_log("segmesh.py:233", _fw_err)
    if solid.ShapeType == "Solid" and solid.Volume < 0:
        solid.reverse()
    return solid


def surface_of(mesh, facets, kind):
    """The fitted Part surface (Plane / Cylinder / Sphere) of the facets, facing out as they do."""
    import numpy as np
    import Part
    d = data(mesh)
    pts = np.array([[p.x, p.y, p.z] for p in _points(d, facets)])
    normals = np.array([[d.normals[i].x, d.normals[i].y, d.normals[i].z] for i in facets])
    c = pts.mean(axis=0)
    if kind == "Plane":
        n = np.linalg.svd(pts - c)[2][-1]
        if n @ normals.sum(axis=0) < 0:
            n = -n
        return Part.Plane(V(*c), V(*n))
    if kind == "Sphere":
        a = np.hstack([2 * pts, np.ones((len(pts), 1))])
        sol = np.linalg.lstsq(a, (pts ** 2).sum(axis=1), rcond=None)[0]
        centre = sol[:3]
        r = math.sqrt(max(sol[3] + centre @ centre, 1e-12))
        sph = Part.Sphere()
        sph.Center, sph.Radius = V(*centre), r
        return sph
    if kind == "Cylinder":
        axis = np.linalg.svd(normals)[2][-1]
        axis /= np.linalg.norm(axis)
        e1 = np.cross(axis, [1, 0, 0] if abs(axis[0]) < 0.9 else [0, 1, 0])
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(axis, e1)
        q = np.stack([(pts - c) @ e1, (pts - c) @ e2], axis=1)
        a = np.hstack([2 * q, np.ones((len(q), 1))])
        sol = np.linalg.lstsq(a, (q ** 2).sum(axis=1), rcond=None)[0]
        r = math.sqrt(max(sol[2] + sol[:2] @ sol[:2], 1e-12))
        centre = c + sol[0] * e1 + sol[1] * e2
        # the axis runs over the segment: start the surface at its lowest point
        h = (pts - centre) @ axis
        cyl = Part.Cylinder()
        cyl.Radius, cyl.Center, cyl.Axis = r, V(*(centre + axis * h.min())), V(*axis)
        return cyl
    return None


def _project(surface, p):
    try:
        u, v = surface.parameter(p)
        return surface.value(u, v)
    except Exception as _fw_err:
        _fw_log("segmesh.py:285", _fw_err)
        return p


def _on_all(surfaces, p, rounds=60):
    """p moved onto where the surfaces meet (alternating projection)."""
    for _ in range(rounds):
        before = V(p)
        for s in surfaces:
            p = _project(s, p)
        if (p - before).Length < 1e-9:
            break
    return p


def _chains(edges):
    """Boundary edges (i, j) linked into point paths: [[i, j, k, ...]] (closed ones repeat the first)."""
    nbr = {}
    for i, j in edges:
        nbr.setdefault(i, []).append(j)
        nbr.setdefault(j, []).append(i)
    used = set()
    out = []

    def walk(start, nxt):
        path = [start]
        prev, cur = start, nxt
        used.add((min(start, nxt), max(start, nxt)))
        while True:
            path.append(cur)
            if cur == start or len(nbr[cur]) != 2:
                return path
            a, b = nbr[cur]
            step = b if a == prev else a
            key = (min(cur, step), max(cur, step))
            if key in used:
                return path
            used.add(key)
            prev, cur = cur, step
    for v, ns in nbr.items():                 # open paths start at their ends
        if len(ns) != 2:
            for n in ns:
                if (min(v, n), max(v, n)) not in used:
                    out.append(walk(v, n))
    for v, ns in nbr.items():                 # then closed loops
        for n in ns:
            if (min(v, n), max(v, n)) not in used:
                out.append(walk(v, n))
    return out


def exact_or_facets(mesh, segments, tolerance=0.05):
    """The exact body (to_exact_brep) when it closes up and keeps the mesh's volume; otherwise the
    faceted one (to_brep), with a note in the report view."""
    d = data(mesh)
    try:
        solid = to_exact_brep(d, segments, tolerance)
    except Exception as error:
        App.Console.PrintLog("FreeCAD Segment Mesh: exact BREP: %s\n" % error)
        solid = None
    vol = abs(getattr(d.mesh, "Volume", 0.0) or 0.0)
    if solid is not None and (vol <= 0 or abs(solid.Volume - vol) <= 0.02 * vol):
        return solid
    App.Console.PrintMessage("Segment Mesh Body: the segments did not close up into exact surfaces; "
                             "the body keeps the mesh facets (planar segments merged).\n")
    return to_brep(d.mesh, tolerance)


def to_exact_brep(mesh, segments, tolerance=0.05):
    ""


    import Part
    d = data(mesh)
    owner = {}
    for k, (_kind, group) in enumerate(segments):
        for i in group:
            owner[i] = k
    surfaces = [surface_of(d, group, kind) for kind, group in segments]
    if any(s is None for s in surfaces):
        return None
    # mesh edges between two segments, by segment pair
    count = {}
    for i, tri in enumerate(d.tris):
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            count.setdefault((min(a, b), max(a, b)), []).append(owner.get(i, -1))
    pairs = {}
    vert_segs = {}
    for key, owners in count.items():
        segs = tuple(sorted(set(owners)))
        if len(segs) == 1 and len(owners) == 2:
            continue                           # inside one segment
        if len(owners) != 2:
            return None                        # an open or non-manifold mesh: not a solid
        pairs.setdefault(segs, []).append(key)
        for v in key:
            vert_segs.setdefault(v, set()).update(segs)
    # corner vertices (three or more segments) split the paths
    edges_of = {k: [] for k in range(len(segments))}
    for (sa, sb), keys in pairs.items():
        for path in _chains_split(keys, vert_segs):
            pts = [_on_all([surfaces[s] for s in sorted(vert_segs[v])] if len(vert_segs[v]) > 2 else
                           [surfaces[sa], surfaces[sb]], V(d.points[v])) for v in path]
            closed = path[0] == path[-1]
            edge = _edge_through(pts, closed, surfaces[sa], surfaces[sb], tolerance)
            if edge is None:
                return None
            try:
                edge.fixTolerance(tolerance)       # corners met by three surfaces: close enough
            except Exception as _fw_err:
                _fw_log("segmesh.py:393", _fw_err)
            edges_of[sa].append(edge)
            edges_of[sb].append(edge)
    faces = []
    for k, (kind, group) in enumerate(segments):
        area = sum(_tri_area(d, i) for i in group)
        face = _face(surfaces[k], edges_of[k], tolerance, area)
        if face is None:
            return None
        faces.append(face)
    try:
        shell = Part.Shell(faces)
        sewn = shell.copy()
        sewn.sewShape()
        shells = sewn.Shells if sewn.ShapeType != "Shell" else [sewn]
        solid = Part.Solid(shells[0])
        solid.fix(tolerance, tolerance, tolerance)
        if solid.Volume < 0:
            solid.reverse()
        return solid if solid.isValid() else None
    except Exception as _fw_err:
        _fw_log("segmesh.py:416", _fw_err)
        return None


def _chains_split(keys, vert_segs):
    """The pair's edges as paths, cut at corner vertices (where three or more segments meet)."""
    out = []
    for path in _chains(keys):
        piece = [path[0]]
        for v in path[1:]:
            piece.append(v)
            if len(vert_segs.get(v, ())) > 2 and v != path[-1]:
                out.append(piece)
                piece = [v]
        if len(piece) > 1:
            out.append(piece)
    return out


def _edge_through(pts, closed, sa, sb, tolerance):
    import Part
    if len(pts) < 2:
        return None
    if sa.TypeId == "Part::GeomPlane" and sb.TypeId == "Part::GeomPlane" and not closed:
        return Part.LineSegment(pts[0], pts[-1]).toShape()
    # a plane cut through a cylinder square to its axis, or any plane through a sphere: a circle
    for plane, other in ((sa, sb), (sb, sa)):
        if plane.TypeId == "Part::GeomPlane" and other.TypeId in ("Part::GeomCylinder", "Part::GeomSphere"):
            try:
                cut = plane.intersect(other)
            except Exception:
                cut = None
            for c in cut or []:
                try:
                    if not hasattr(c, "parameter"):
                        continue
                    if closed:
                        return c.toShape()
                    if len(pts) >= 3 and c.TypeId == "Part::GeomCircle":
                        # the arc through its two ends and its middle, on the intersection circle
                        on = [_project_curve(c, q) for q in (pts[0], pts[len(pts) // 2], pts[-1])]
                        return Part.Arc(*on).toShape()
                except Exception as _fw_err:
                    _fw_log("segmesh.py:459", _fw_err)
                    continue
    try:
        bs = Part.BSplineCurve()
        if closed:
            bs.interpolate(pts[:-1], PeriodicFlag=True)
        else:
            bs.interpolate(pts)
        return bs.toShape()
    except Exception as _fw_err:
        _fw_log("segmesh.py:469", _fw_err)
        return None


def _project_curve(curve, p):
    try:
        return curve.value(curve.parameter(p))
    except Exception as _fw_err:
        _fw_log("segmesh.py:477", _fw_err)
        return p


def _tri_area(d, i):
    a, b, c = (V(d.points[k]) for k in d.tris[i])
    return (b - a).cross(c - a).Length / 2.0


def _face(surface, edges, tolerance, area=None):
    """The face of surface inside the edges; on a curved surface, of the two sides a loop leaves
    the one whose area is nearest the segment's own."""
    face = _face_one(surface, edges, tolerance)
    if face is None or surface.TypeId == "Part::GeomPlane" or area is None:
        return face
    import Part
    try:
        try:
            groups = Part.sortEdges(edges, tolerance)
        except TypeError:
            groups = Part.sortEdges(edges)
        loops = [Part.Wire(g) for g in groups]
        flipped = [w.reversed() for w in loops]
        other = Part.Face(surface, flipped[0])
        for w in flipped[1:]:
            other.cutHoles([w])
        other.fix(tolerance, tolerance, tolerance)
        if other.isValid() and other.Area > 0 and abs(other.Area - area) < abs(face.Area - area):
            return other
    except Exception as _fw_err:
        _fw_log("segmesh.py:501", _fw_err)
    return face


def _face_one(surface, edges, tolerance):
    import Part
    if not edges:
        return Part.Face(surface) if surface.TypeId == "Part::GeomSphere" else None
    try:
        try:
            groups = Part.sortEdges(edges, tolerance)
        except TypeError:
            groups = Part.sortEdges(edges)
        loops = [Part.Wire(group) for group in groups]
    except Exception as _fw_err:
        _fw_log("segmesh.py:522", _fw_err)
        return None
    try:
        if surface.TypeId == "Part::GeomPlane":
            face = Part.makeFace(loops, "Part::FaceMakerBullseye")
        else:
            face = Part.Face(surface, loops[0])
            for w in loops[1:]:
                face.cutHoles([w])
            face.fix(tolerance, tolerance, tolerance)
        return face if face.Area > 0 else None
    except Exception:
        try:
            face = Part.Face(surface, loops)
            face.fix(tolerance, tolerance, tolerance)
            return face
        except Exception as _fw_err:
            _fw_log("segmesh.py:539", _fw_err)
            return None


def mesh_of(obj):
    """The mesh of a picked body: a mesh object's own, or one made from a shape's faces."""
    m = getattr(obj, "Mesh", None)
    if m is not None:
        return m
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull():
        return None
    import MeshPart
    return MeshPart.meshFromShape(Shape=shape, LinearDeflection=0.05, AngularDeflection=0.2)


# --------------------------------------------------------------------------- the PropertyManager
TITLE = "Segment Mesh Body"
COMMAND = "SWStyle_SegmentMesh"

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None


def _is_mesh(obj):
    return obj is not None and getattr(obj, "Mesh", None) is not None and obj.isDerivedFrom("Mesh::Feature")


def _facet_of(sub):
    """The 0-based facet index of a picked 'Facet12' (FreeCAD names mesh facets from 0)."""
    name = (sub or "").split(".")[-1]
    if name.startswith("Facet"):
        try:
            return int(name[5:])
        except ValueError:
            return None
    return None


if Gui is not None:
    class SegmentPanel:
        def __init__(self, doc, obj=None):
            self.doc = doc
            self.name = obj.Name if obj is not None else None
            self.original = obj.Mesh.copy() if obj is not None else None
            self.data = None
            self.segments = []
            self.doc.openTransaction(TITLE)
            page = QtWidgets.QWidget()
            page.setWindowTitle("Mesh Body")
            page.setProperty("swstyle_pm_title", TITLE)
            page.setProperty("swstyle_pm_icon", "FEATURES_SEGMENT_MESH")
            lay = QtWidgets.QVBoxLayout(page)
            self.body_box = QtWidgets.QListWidget(page)
            self.body_box.setObjectName("SWSegmentMeshBody")
            self.body_box.setMaximumHeight(28)
            self.body_box.setToolTip("The mesh body to segment: pick it in the graphics area")
            lay.addWidget(self.body_box)
            seg = QtWidgets.QWidget()
            seg.setWindowTitle("Segmentation")
            form = QtWidgets.QFormLayout(seg)
            self.detail = QtWidgets.QSlider(QtCore.Qt.Horizontal, seg)
            self.detail.setObjectName("SWSegmentMeshDetail")
            self.detail.setRange(5, 60)
            self.detail.setValue(20)
            self.detail.setToolTip("Bend (degrees) that starts a new region: lower finds more regions")
            form.addRow("Detail", self.detail)
            self.deviation = QtWidgets.QDoubleSpinBox(seg)
            self.deviation.setObjectName("SWSegmentMeshDeviation")
            self.deviation.setDecimals(4)
            self.deviation.setRange(0.0001, 100.0)
            self.deviation.setSuffix(" mm")
            self.deviation.setToolTip("How far a region may stray from the plane, cylinder or sphere it is matched to")
            form.addRow("Deviation", self.deviation)
            leg = QtWidgets.QWidget()
            leg.setWindowTitle("Legend")
            lgrid = QtWidgets.QGridLayout(leg)
            self.legend_rows = {}
            for r, kind in enumerate(KINDS + (UNRECOGNIZED,)):
                swatch = QtWidgets.QLabel(leg)
                swatch.setFixedSize(14, 14)
                c = QtGui.QColor.fromRgbF(*COLOURS[kind])
                swatch.setStyleSheet("background: %s; border: 1px solid #555;" % c.name())
                name = QtWidgets.QLabel(kind, leg)
                count = QtWidgets.QLabel("", leg)
                count.setObjectName("SWSegmentMeshLegend_" + kind)
                lgrid.addWidget(swatch, r, 0)
                lgrid.addWidget(name, r, 1)
                lgrid.addWidget(count, r, 2)
                self.legend_rows[kind] = count
            fs = QtWidgets.QGroupBox("Facet Shape")
            fs.setObjectName("SWSegmentMeshFacetShape")
            fs.setCheckable(True)
            fs.setChecked(False)
            fs.setToolTip("On: click a facet and the facets around it that fit the shape become one segment")
            fl = QtWidgets.QVBoxLayout(fs)
            self.shape_buttons = {}
            for kind in KINDS:
                b = QtWidgets.QRadioButton(kind, fs)
                b.setObjectName("SWSegmentMeshShape_" + kind)
                fl.addWidget(b)
                self.shape_buttons[kind] = b
            self.shape_buttons["Plane"].setChecked(True)
            self.facet_shape = fs
            out = QtWidgets.QWidget()
            out.setWindowTitle("Output")
            ol = QtWidgets.QVBoxLayout(out)
            self.convert = QtWidgets.QCheckBox("Convert to standard BREP", out)
            self.convert.setObjectName("SWSegmentMeshConvert")
            self.convert.setToolTip("Every segment recognized: OK makes a solid body from the mesh, each "
                                    "segment one true plane, cylinder or sphere")
            ol.addWidget(self.convert)
            self.note = QtWidgets.QLabel("", out)
            self.note.setObjectName("SWSegmentMeshNote")
            self.note.setWordWrap(True)
            ol.addWidget(self.note)
            page2 = QtWidgets.QWidget()
            page2.setWindowTitle("Facet Shape")
            QtWidgets.QVBoxLayout(page2).addWidget(fs)
            self.form = [page, seg, leg, page2, out]
            self.detail.valueChanged.connect(lambda _v: self.update())
            self.deviation.valueChanged.connect(lambda _v: self.update())
            if obj is not None:
                self._set_body(obj)
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)

        # ---- the body and the segments
        def obj(self):
            return self.doc.getObject(self.name) if self.name else None

        def _set_body(self, obj):
            if self.obj() is not None and self.obj() is not obj and self.original is not None:
                self.obj().Mesh = self.original
            self.name = obj.Name
            self.original = obj.Mesh.copy()
            self.data = Data(self.original)
            self.body_box.clear()
            self.body_box.addItem(obj.Label)
            size = self.original.BoundBox.DiagonalLength
            self.deviation.blockSignals(True)
            self.deviation.setValue(max(round(size * 0.002, 4), 0.0001))
            self.deviation.blockSignals(False)
            self.update()

        def update(self):
            if self.data is None:
                return
            self.segments = segment(self.data, float(self.detail.value()), self.deviation.value())
            self.show()

        def show(self):
            leg = legend(self.segments)
            for kind, (n, f) in leg.items():
                self.legend_rows[kind].setText("%d (%d facets)" % (n, f) if n else "0")
            ok = all_recognized(self.segments)
            self.convert.setEnabled(ok)
            if not ok:
                self.convert.setChecked(False)
            self.note.setText("" if ok else "Unrecognized segments are left: use Facet Shape on them "
                                            "to convert to standard BREP.")
            obj = self.obj()
            if obj is None:
                return
            m = self.original.copy()
            colours = []
            for kind, group in self.segments:
                m.addSegment(group)
                colours.append(COLOURS[kind])
            obj.Mesh = m
            try:
                obj.ViewObject.highlightSegments(colours)
            except Exception as _fw_err:
                _fw_log("segmesh.py:707", _fw_err)

        # ---- picking
        def addSelection(self, doc, name, sub, pos):
            if doc != self.doc.Name:
                return
            QtCore.QTimer.singleShot(0, lambda: self._picked(name, sub))

        def _picked(self, name, sub):
            picked = self.doc.getObject(name)
            try:
                Gui.Selection.clearSelection()
            except Exception as _fw_err:
                _fw_log("segmesh.py:720", _fw_err)
            if not _is_mesh(picked):
                return
            if picked.Name != self.name:
                self._set_body(picked)
                return
            i = _facet_of(sub)
            if i is not None and self.facet_shape.isChecked():
                self.facet_pick(i)

        def facet_kind(self):
            return next(k for k, b in self.shape_buttons.items() if b.isChecked())

        def facet_pick(self, i, kind=None):
            """Facet Shape: the facets around facet i that fit the shape become one segment."""
            if self.data is None or not 0 <= i < len(self.data):
                return []
            kind = kind or self.facet_kind()
            group = grow(self.data, i, kind, self.deviation.value())
            self.segments = assign(self.segments, group, kind)
            self.show()
            return group

        # ---- OK / Cancel
        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def _done(self):
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("segmesh.py:751", _fw_err)

        def accept(self):
            obj = self.obj()
            if obj is None:
                self.note.setText("Pick a mesh body.")
                return False
            self._done()
            if self.convert.isChecked() and all_recognized(self.segments):
                shape = exact_or_facets(self.data, self.segments, self.deviation.value())
                feat = self.doc.addObject("Part::Feature", "SegmentMeshBody")
                try:
                    from . import naming
                    feat.Label = naming.next_label(self.doc, "Segment Mesh Body")
                except Exception:
                    feat.Label = "Segment Mesh Body1"
                feat.Shape = shape
                try:
                    obj.ViewObject.Visibility = False
                except Exception as _fw_err:
                    _fw_log("segmesh.py:771", _fw_err)
            self.doc.recompute()
            self.doc.commitTransaction()
            Gui.Control.closeDialog()
            return True

        def reject(self):
            self._done()
            obj = self.obj()
            if obj is not None and self.original is not None:
                obj.Mesh = self.original
            self.doc.abortTransaction()
            self.doc.recompute()
            Gui.Control.closeDialog()
            return True

    class Command:
        def GetResources(self):
            return {"MenuText": "Segment Imported Mesh Body...", "Pixmap": "Mesh_Segmentation",
                    "ToolTip": "Splits a mesh body into planes, cylinders and spheres; it can become a standard body."}

        def IsActive(self):
            doc = App.ActiveDocument
            return doc is not None and not Gui.Control.activeDialog() and any(_is_mesh(o) for o in doc.Objects)

        def Activated(self):
            doc = App.ActiveDocument
            picked = next((s.Object for s in Gui.Selection.getSelectionEx(doc.Name) if _is_mesh(s.Object)), None)
            if picked is None:
                meshes = [o for o in doc.Objects if _is_mesh(o)]
                picked = meshes[0] if len(meshes) == 1 else None
            panel = SegmentPanel(doc, picked)
            Gui.Control.showDialog(panel)
            return panel


def register():
    if Gui is None:
        return
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
