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

import json
import math

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

CONTROL = "FwMeshControl"            # on a MeshRegion made by the Mesh Control PM: JSON {size, ratio, unit, density}
POINTS = ("4 points", "16 points", "29 points", "At Nodes")
DEFAULT_POINTS = "16 points"
QUALITY = ("Aspect Ratio", "Jacobian")
PERFECT = math.sqrt(1.5)             # longest edge / shortest altitude of a regular tetrahedron


# --------------------------------------------------------------------------- mesh controls
def controls(m):
    return [r for r in (getattr(m, "MeshRegionList", None) or []) if CONTROL in r.PropertiesList]


def values_of(r):
    try:
        return json.loads(getattr(r, CONTROL, "") or "{}")
    except ValueError:
        return {}


def _clear(m):
    import Fem
    if m.FemMesh.NodeCount:
        m.FemMesh = Fem.FemMesh()          # the next mesh / run meshes again with the control


def add_mesh_control(a, refs, size, ratio=1.5, unit="mm", density=5, edit=None):
    """A Mesh Control on refs [(obj, (sub, ...))] of study a: element size (in unit) on them, growing by ratio."""
    import ObjectsFem
    from . import simpms
    m = simpms.gmsh_of(a)
    if m is None:
        raise simpms.SetupError("The study has no mesh to control.")
    refs = [(o, tuple(s)) for o, s in refs if s]
    if not refs:
        raise simpms.SetupError("Pick the faces, edges or vertices for the mesh control.")
    k = simpms.LENGTH_UNITS.get(unit, 1.0)
    if not size or size <= 0:
        raise simpms.SetupError("Give the element size.")
    ratio = float(ratio)
    if ratio < 1.0 or ratio > 10.0:
        raise simpms.SetupError("The ratio is from 1 to 10 (each layer that many times the one inside it).")
    r = edit
    if r is None:
        r = ObjectsFem.makeMeshRegion(a.Document, m, 0.0, "MeshControl")
        r.Label = simpms._label(a, "Control")
        r.addProperty("App::PropertyString", CONTROL, "FreeCAD", "The Mesh Control PM's values")
        r.setPropertyStatus(CONTROL, "Hidden")
        if r not in (m.MeshRegionList or []):
            m.MeshRegionList = list(m.MeshRegionList or []) + [r]
    r.CharacteristicLength = "%r mm" % (float(size) * k)
    r.References = refs
    setattr(r, CONTROL, json.dumps({"size": float(size), "ratio": ratio, "unit": unit, "density": int(density)},
                                   sort_keys=True))
    _clear(m)
    a.Document.recompute()
    return r


def _ids(refs, prefix):
    out = []
    for _o, subs in refs:
        for s in subs:
            if s.startswith(prefix):
                out.append(int(s[len(prefix):]))
    return sorted(set(out))


def field_lines(m, clmax):
    """Gmsh fields for the mesh controls: Distance to the entities, Threshold from the control's size (at 0) to the
    global size where the geometric layers (size, size*ratio, ...) reach it. Empty when there is no control."""
    lines, thresholds = [], []
    for i, r in enumerate(controls(m)):
        if getattr(r, "Suppressed", False):
            continue
        v = values_of(r)
        try:
            size = App.Units.Quantity(r.CharacteristicLength).getValueAs("mm").Value
        except Exception:
            continue
        refs = [(o, subs) for o, subs in r.References]
        ratio = max(1.0, float(v.get("ratio", 1.5)))
        top = max(clmax, size)
        if ratio > 1.0 + 1e-9 and top > size:
            n = math.ceil(math.log(top / size) / math.log(ratio))
            reach = size * (ratio ** n - 1.0) / (ratio - 1.0)
        else:
            reach = 1e12                      # ratio 1: the control's size everywhere it can reach
        d, t = 9000 + 2 * i, 9001 + 2 * i
        lines.append("Field[%d] = Distance;" % d)
        for key, prefix in (("SurfacesList", "Face"), ("CurvesList", "Edge"), ("PointsList", "Vertex")):
            ids = _ids(refs, prefix)
            if ids:
                lines.append("Field[%d].%s = {%s};" % (d, key, ", ".join(str(x) for x in ids)))
        lines.append("Field[%d].Sampling = 40;" % d)
        lines += ["Field[%d] = Threshold;" % t, "Field[%d].InField = %d;" % (t, d), "Field[%d].SizeMin = %r;" % (t, size),
                  "Field[%d].SizeMax = %r;" % (t, top), "Field[%d].DistMin = 0;" % t, "Field[%d].DistMax = %r;" % (t, reach)]
        thresholds.append(t)
    if not thresholds:
        return []
    lines += ["Field[9999] = Min;", "Field[9999].FieldsList = {%s};" % ", ".join(str(t) for t in thresholds),
              "Background Field = 9999;"]
    return ["// FreeCAD Mesh Controls (size growing by the ratio)"] + lines


def _patch_gmsh():
    """GmshTools.write_geo also writes the Mesh PM's tolerance (before the geometry is read) and the mesh controls'
    fields (before meshing)."""
    try:
        from femmesh.gmshtools import GmshTools
    except ImportError:
        return False
    if getattr(GmshTools, "_fw_meshq", False):
        return True
    write0 = GmshTools.write_geo

    def write_geo(self):
        r = write0(self)
        try:
            from . import simpms
            m = self.mesh_obj
            k = simpms.kept(m) or {}
            text = open(self.temp_file_geo).read()
            changed = False
            tol = k.get("tolerance")
            if tol:
                tol_mm = float(tol) * simpms.LENGTH_UNITS.get(k.get("unit") or "mm", 1.0)
                i = text.find("Merge \"")
                if i >= 0:
                    text = text[:i] + "Geometry.Tolerance = %r; // the Mesh PM's tolerance\n" % tol_mm + text[i:]
                    changed = True
            try:
                clmax = float(self.clmax)
            except (TypeError, ValueError):
                clmax = 1e22
            if clmax >= 1e21:
                clmax = m.Shape.Shape.BoundBox.DiagonalLength / 10.0 if getattr(m, "Shape", None) else 10.0
            lines = field_lines(m, clmax)
            if lines:
                j = text.find("\nMesh  ")
                if j < 0:
                    raise ValueError("no Mesh line in the .geo")
                text = text[:j + 1] + "\n".join(lines) + "\n" + text[j + 1:]
                changed = True
            if changed:
                with open(self.temp_file_geo, "w") as f:
                    f.write(text)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: mesh controls not written (%s)\n" % error)
        return r

    GmshTools.write_geo = write_geo
    GmshTools._fw_meshq = True
    return True


# --------------------------------------------------------------------------- element quality
def _natural_points(which):
    """Points (L1, L2, L3, L4) inside a tetrahedron where the Jacobian is looked at."""
    def orbit31(a):
        b = 1.0 - 3.0 * a
        return [tuple(b if i == j else a for i in range(4)) for j in range(4)]

    def orbit211(a, b):
        c = 1.0 - 2.0 * a - b
        out = set()
        for i in range(4):
            for j in range(4):
                if i == j:
                    continue
                p = [a] * 4
                p[i], p[j] = b, c
                out.add(tuple(p))
        return sorted(out)
    if which == "At Nodes":
        corners = [tuple(1.0 if i == j else 0.0 for i in range(4)) for j in range(4)]
        mids = []
        for i, j in ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3)):
            p = [0.0] * 4
            p[i] = p[j] = 0.5
            mids.append(tuple(p))
        return corners + mids
    pts = orbit31(0.1381966011250105)                          # the 4-point Gauss rule
    if which in ("16 points", "29 points"):
        pts += orbit211(0.1, 0.2)
    if which == "29 points":
        pts += [(0.25, 0.25, 0.25, 0.25)] + orbit211(0.05, 0.35)
    return pts


_DL = ((-1.0, -1.0, -1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))   # dLi / d(r, s, t)


def _mid_pairs(fm, nodes):
    """Which two corners each mid-side node of a 10-node tetrahedron sits between (FreeCAD's node order)."""
    c = [fm.getNodeById(n) for n in nodes[:4]]
    pairs = []
    for n in nodes[4:10]:
        p = fm.getNodeById(n)
        best = min(((i, j) for i in range(4) for j in range(i + 1, 4)), key=lambda ij: ((c[ij[0]] + c[ij[1]]) * 0.5 - p).Length)
        pairs.append(best)
    return pairs


def _det_at(xyz, pairs, L):  # one element (kept for checks); quality() does all of them at once
    """The Jacobian determinant of a 10-node tetrahedron at natural point L."""
    J = [[0.0] * 3 for _ in range(3)]
    for i in range(4):                                  # corners: N = L (2L - 1)
        g = 4.0 * L[i] - 1.0
        for col in range(3):
            d = g * _DL[i][col]
            for row in range(3):
                J[row][col] += xyz[i][row] * d
    for k, (i, j) in enumerate(pairs):                  # mid-side: N = 4 Li Lj
        for col in range(3):
            d = 4.0 * (L[i] * _DL[j][col] + L[j] * _DL[i][col])
            for row in range(3):
                J[row][col] += xyz[4 + k][row] * d
    return (J[0][0] * (J[1][1] * J[2][2] - J[1][2] * J[2][1]) - J[0][1] * (J[1][0] * J[2][2] - J[1][2] * J[2][0])
            + J[0][2] * (J[1][0] * J[2][1] - J[1][1] * J[2][0]))


def aspect_ratio(p):
    """Longest edge over the shortest altitude of the tetrahedron p (4 corner vectors), 1 for a regular one."""
    edges = [(p[i] - p[j]).Length for i in range(4) for j in range(i + 1, 4)]
    vol6 = abs((p[1] - p[0]).dot((p[2] - p[0]).cross(p[3] - p[0])))
    if vol6 <= 1e-30:
        return 1e6
    h = []
    for i in range(4):
        o = [p[k] for k in range(4) if k != i]
        area2 = (o[1] - o[0]).cross(o[2] - o[0]).Length
        h.append(vol6 / area2 if area2 > 0 else 0.0)
    hmin = min(h)
    return max(edges) / hmin / PERFECT if hmin > 0 else 1e6


def _dshape(pairs, L):
    """dN/d(r, s, t) of the 10 nodes at natural point L (10 x 3)."""
    rows = []
    for i in range(4):
        g = 4.0 * L[i] - 1.0
        rows.append([g * c for c in _DL[i]])
    for i, j in pairs:
        rows.append([4.0 * (L[i] * _DL[j][c] + L[j] * _DL[i][c]) for c in range(3)])
    return rows


def quality(fm, points=DEFAULT_POINTS):
    """{volume id: (aspect ratio, Jacobian ratio)}; the Jacobian ratio is 1 for straight (first-order) elements and
    0 or less for a distorted one (a determinant at or below zero at one of the points)."""
    import numpy as np
    vols = [v for v in fm.Volumes]
    conn = {}
    for v in vols:
        n = fm.getElementNodes(v)
        if len(n) in (4, 10):
            conn[v] = n
    if not conn:
        return {}
    ids = list(conn)
    node_ids = sorted({n for c in conn.values() for n in c})
    where = {n: k for k, n in enumerate(node_ids)}
    P = np.array([tuple(fm.getNodeById(n)) for n in node_ids], dtype=float)
    out = {}
    for size in (4, 10):
        sel = [v for v in ids if len(conn[v]) == size]
        if not sel:
            continue
        idx = np.array([[where[n] for n in conn[v]] for v in sel])
        X = P[idx]                                            # E x size x 3
        c = X[:, :4, :]
        e = [np.linalg.norm(c[:, i] - c[:, j], axis=1) for i in range(4) for j in range(i + 1, 4)]
        longest = np.max(np.stack(e, axis=1), axis=1)
        vol6 = np.abs(np.einsum("ij,ij->i", c[:, 1] - c[:, 0], np.cross(c[:, 2] - c[:, 0], c[:, 3] - c[:, 0])))
        alts = []
        for i in range(4):
            o = [k for k in range(4) if k != i]
            a2 = np.linalg.norm(np.cross(c[:, o[1]] - c[:, o[0]], c[:, o[2]] - c[:, o[0]]), axis=1)
            alts.append(np.where(a2 > 0, vol6 / np.where(a2 > 0, a2, 1.0), 0.0))
        hmin = np.min(np.stack(alts, axis=1), axis=1)
        ar = np.where((hmin > 0) & (vol6 > 1e-30), longest / np.where(hmin > 0, hmin, 1.0) / PERFECT, 1e6)
        jr = np.ones(len(sel))
        if size == 10:
            pairs = _mid_pairs(fm, conn[sel[0]])
            dets = []
            for L in _natural_points(points):
                D = np.array(_dshape(pairs, L))                    # 10 x 3
                J = np.einsum("eni,nj->eij", X, D)
                dets.append(np.linalg.det(J))
            dets = np.stack(dets, axis=1)
            lo, hi = dets.min(axis=1), dets.max(axis=1)
            flip = hi < 0                                         # inside out as a whole: the same quality, mirrored
            lo2, hi2 = np.where(flip, -hi, lo), np.where(flip, -lo, hi)
            safe = np.where(lo2 > 0, lo2, 1.0)
            jr = np.where(lo2 > 0, hi2 / safe, np.where(hi2 > 0, -1.0, -1.0))
            jr = np.where(lo2 == 0, 0.0, jr)
        for v, x, y in zip(sel, ar.tolist(), jr.tolist()):
            out[v] = (x, y)
    return out


def points_of(m):
    from . import simpms
    p = (simpms.kept(m) or {}).get("jacobian") or DEFAULT_POINTS
    return p if p in POINTS else DEFAULT_POINTS


def summary(m, q=None):
    """Mesh Details' quality rows."""
    fm = m.FemMesh
    q = q if q is not None else quality(fm, points_of(m))
    ars = [v[0] for v in q.values()]
    jrs = [v[1] for v in q.values()]
    n = len(ars) or 1
    return {"elements": len(ars), "max_aspect": max(ars) if ars else 0.0,
            "pct_below_3": 100.0 * sum(1 for x in ars if x < 3.0) / n,
            "pct_above_10": 100.0 * sum(1 for x in ars if x > 10.0) / n,
            "distorted": sum(1 for x in jrs if x <= 0.0), "pct_distorted": 100.0 * sum(1 for x in jrs if x <= 0.0) / n,
            "max_jacobian": max((x for x in jrs if x > 0), default=0.0), "points": points_of(m)}


def outer_faces(fm):
    """[(volume id, (node, node, node))]: the corner triangles no two volumes share, outward."""
    seen = {}
    for v in fm.Volumes:
        n = fm.getElementNodes(v)
        if len(n) not in (4, 10):
            continue
        for tri, other in (((n[0], n[2], n[1]), n[3]), ((n[0], n[1], n[3]), n[2]), ((n[0], n[3], n[2]), n[1]),
                           ((n[1], n[2], n[3]), n[0])):
            key = tuple(sorted(tri))
            if key in seen:
                seen[key] = None
            else:
                seen[key] = (v, tri, other)
    out = []
    for item in seen.values():
        if item is None:
            continue
        v, tri, other = item
        p = [fm.getNodeById(x) for x in tri]
        if (p[1] - p[0]).cross(p[2] - p[0]).dot(fm.getNodeById(other) - p[0]) > 0:
            tri = (tri[0], tri[2], tri[1])
        out.append((v, tri))
    return out


def plot_values(m, kind):
    q = quality(m.FemMesh, points_of(m))
    i = QUALITY.index(kind)
    return {v: vals[i] for v, vals in q.items()}, q


# =========================================================================== GUI
if Gui is not None:
    from . import simpms
    from . import simxpress as sx

    SHOWN = {"kind": None}

    def show_plot(a, kind="Aspect Ratio"):
        """Colours the mesh's outer faces by element quality, with the colour bar and title. Returns summary()."""
        from pivy import coin
        from . import simplots as sp
        if kind not in QUALITY:
            raise simpms.SetupError("Unknown mesh quality %r." % kind)
        m = simpms.gmsh_of(a)
        if m is None or not m.FemMesh.VolumeCount:
            raise simpms.SetupError("Mesh the study first (Create Mesh).")
        vals, q = plot_values(m, kind)
        s = summary(m, q)
        good = [x for x in vals.values() if x > 0]
        lo = min(good) if good else 0.0
        hi = max(good) if good else 1.0
        if kind == "Jacobian" and s["distorted"]:
            lo = 0.0
        span = (hi - lo) or 1.0
        sp.clear()
        sp._hide_model(a)
        fm = m.FemMesh
        faces = outer_faces(fm)
        ids = sorted({n for _v, t in faces for n in t})
        index = {n: i for i, n in enumerate(ids)}
        root = coin.SoSeparator()
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
        root.addChild(hints)
        mat = coin.SoMaterial()
        cols = []
        for v, _t in faces:
            x = vals.get(v, lo)
            cols.append(sp.colour(1.0 if x <= 0 else (x - lo) / span, "Default"))   # a distorted element shows red
        mat.diffuseColor.setValues(0, len(cols), cols)
        bind = coin.SoMaterialBinding()
        bind.value = coin.SoMaterialBinding.PER_FACE
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(ids), [tuple(fm.getNodeById(n)) for n in ids])
        fs = coin.SoIndexedFaceSet()
        flat = []
        for _v, t in faces:
            flat.extend((index[t[0]], index[t[1]], index[t[2]], -1))
        fs.coordIndex.setValues(0, len(flat), flat)
        for n in (mat, bind, coords, fs):
            root.addChild(n)
        edges = coin.SoSeparator()
        style = coin.SoDrawStyle()
        style.style = coin.SoDrawStyle.LINES
        style.lineWidth = 1
        ecol = coin.SoBaseColor()
        ecol.rgb = (0.1, 0.1, 0.1)
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        for n in (pick, style, ecol, coords, fs):
            edges.addChild(n)
        root.addChild(edges)
        view = sp._view(a.Document)
        view.getSceneGraph().addChild(root)
        sp.SHOWN["node"] = (view, root, coords, ids)
        host = sx._host()
        if host is not None:
            chart = {"colours": "Default", "format": "Floating", "decimals": 3}
            sp.SHOWN["legend"] = sp.Legend(host, kind, lo, hi, chart)
            lines = ["Model name: %s" % (a.Document.Label or a.Document.Name),
                     "Study name: %s(-%s-)" % (a.Label, sp._config(a)),
                     "Plot type: Mesh Quality Plot %s" % kind]
            if kind == "Jacobian":
                lines.append("Jacobian points: %s" % s["points"])
                if s["distorted"]:
                    lines.append("Distorted elements (red): %d" % s["distorted"])
            sp.SHOWN["title"] = sx.TitleBlock(host, lines)
            sx.PLOT["legend"], sx.PLOT["title"] = sp.SHOWN["legend"], sp.SHOWN["title"]
            sx._place_overlays()
            sx.PLOT["legend"] = sx.PLOT["title"] = None
        sp.SHOWN.update(a=a, name="Mesh Quality %s" % kind, factor=1.0)
        SHOWN["kind"] = kind
        s.update(lo=lo, hi=hi, faces=len(faces), kind=kind)
        return s

    class MeshQualityPM(simpms._PM):
        """Mesh Quality Plot: Display Aspect Ratio or Jacobian."""
        PM = "Mesh Quality Plot"

        def __init__(self, doc, edit=None):
            super().__init__(doc, edit)
            msg = sx._box("Message", None, self.PM)
            self.hint = QtWidgets.QLabel("")
            self.hint.setWordWrap(True)
            QtWidgets.QVBoxLayout(msg).addWidget(self.hint)
            disp = sx._box("Display")
            dl = QtWidgets.QVBoxLayout(disp)
            self.kind = QtWidgets.QComboBox()
            self.kind.setObjectName("SWSimMeshQualityKind")
            self.kind.addItems(list(QUALITY))
            if SHOWN.get("kind") in QUALITY:
                self.kind.setCurrentText(SHOWN["kind"])
            dl.addWidget(self.kind)
            self.form = [msg, disp]
            self.kind.currentTextChanged.connect(lambda *_: self._hint())
            self._hint()

        def _hint(self):
            m = simpms.gmsh_of(self.a) if self.a is not None else None
            self.hint.setText({"Aspect Ratio": "Longest edge over the shortest altitude of each element: 1 is perfect; "
                                               "above 10 is poor.",
                               "Jacobian": "Largest over smallest Jacobian of each curved element at the %s (Mesh PM, "
                                           "Advanced); 0 or less (red) is distorted." % (points_of(m) if m else
                                                                                         DEFAULT_POINTS)}
                              [self.kind.currentText()])

        def _start(self):
            return

        def accept(self):
            try:
                show_plot(self.a, self.kind.currentText())
            except (simpms.SetupError, RuntimeError) as e:
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), self.PM, str(e))
                return False
            Gui.Control.closeDialog()
            return True

    class MeshControlPM(simpms._PM):
        """Mesh Control: Selected Entities, Mesh Density, Mesh Parameters (units, element size, ratio)."""
        PM = "Mesh Control"

        def __init__(self, doc, edit=None):
            super().__init__(doc, edit)
            v = values_of(edit) if edit is not None else {}
            shape = self.obj.Shape if self.obj is not None else None
            self.base = simpms.default_size(shape) if shape is not None else 5.0
            m = simpms.gmsh_of(self.a) if self.a is not None else None
            if m is not None:                                 # the study's global element size, in mm
                try:
                    g = App.Units.Quantity(m.CharacteristicLengthMax).getValueAs("mm").Value
                    self.base = g if g > 0 else self.base
                except Exception as _fw_err:
                    _fw_log("simmeshq.py:global", _fw_err)
            sel = sx._box("Selected Entities", None, self.PM)
            sl = QtWidgets.QVBoxLayout(sel)
            self.ents = sx._PickList("SWSimMeshControlEntities")
            self.ents.setToolTip("Faces, edges or vertices: click them; a second click takes one out")
            sl.addWidget(self.ents)
            dens = sx._box("Mesh Density")
            dl = QtWidgets.QVBoxLayout(dens)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel("Coarse"))
            self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            self.slider.setObjectName("SWSimMeshControlDensity")
            self.slider.setRange(0, 10)
            self.slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
            row.addWidget(self.slider, 1)
            row.addWidget(QtWidgets.QLabel("Fine"))
            dl.addLayout(row)
            self.reset = QtWidgets.QPushButton("Reset")
            self.reset.setObjectName("SWSimMeshControlReset")
            dl.addWidget(self.reset)
            par = sx._box("Mesh Parameters")
            pl = QtWidgets.QFormLayout(par)
            self.unit = QtWidgets.QComboBox()
            self.unit.setObjectName("SWSimMeshControlUnit")
            self.unit.addItems(["mm", "in"])
            pl.addRow("Units:", self.unit)
            self.size = QtWidgets.QDoubleSpinBox()
            self.size.setObjectName("SWSimMeshControlSize")
            self.size.setRange(0.001, 1e6)
            self.size.setDecimals(3)
            pl.addRow("Element size:", self.size)
            self.ratio = QtWidgets.QDoubleSpinBox()
            self.ratio.setObjectName("SWSimMeshControlRatio")
            self.ratio.setRange(1.0, 10.0)
            self.ratio.setDecimals(2)
            self.ratio.setSingleStep(0.1)
            self.ratio.setToolTip("Each layer of elements away from the entities is this many times the one inside it")
            pl.addRow("Ratio:", self.ratio)
            self.boxes = [self.ents]
            self.form = [sel, dens, par]
            self.unit.setCurrentText(v.get("unit", "mm"))
            self.slider.setValue(int(v.get("density", 7)))
            self.size.setValue(float(v.get("size", self._size_at(self.slider.value()))))
            self.ratio.setValue(float(v.get("ratio", 1.5)))
            if edit is not None:
                self.ents.addItems([s for _o, subs in edit.References for s in subs])
            self.slider.valueChanged.connect(lambda d: self.size.setValue(self._size_at(d)))
            self.reset.clicked.connect(lambda: self.slider.setValue(7) if self.slider.value() != 7 else
                                       self.size.setValue(self._size_at(7)))
            self._start()

        def _size_at(self, d):
            """The control's density slider: half the study's global element size at its default (7), twice it at
            Coarse, about a quarter at Fine."""
            k = 1.0 / simpms.LENGTH_UNITS.get(self.unit.currentText(), 1.0)
            return round(self.base * 2.0 ** (1.0 - 2.0 * max(0, min(10, int(d))) / 7.0) * k, 3)

        def _start(self):
            first = self.ents
            if self.edit is None:
                for sel in Gui.Selection.getSelectionEx(self.doc.Name, 0):
                    for sub in sel.SubElementNames:
                        last = sub.split(".")[-1]
                        if last.startswith(("Face", "Edge", "Vertex")) and not first.findItems(last, QtCore.Qt.MatchExactly):
                            first.addItem(last)
            first.activated_box.connect(self._activate)
            self._activate(first)
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)

        def _picked(self, name, sub):
            last = (sub or "").split(".")[-1]
            if last.startswith(("Face", "Edge", "Vertex")):
                self.ents.toggle(last)
            try:
                Gui.Selection.clearSelection()
            except Exception as _fw_err:
                _fw_log("simmeshq.py:pick", _fw_err)

        def apply(self):
            subs = self.ents.values()
            if self.obj is None:
                raise simpms.SetupError("The study has no part.")
            return add_mesh_control(self.a, [(self.obj, tuple(subs))], self.size.value(), self.ratio.value(),
                                    self.unit.currentText(), self.slider.value(), self.edit)

    def open_quality(a=None):
        return simpms.show(MeshQualityPM(App.ActiveDocument))

    def open_control(edit=None):
        return simpms.show(MeshControlPM(App.ActiveDocument if edit is None else edit.Document, edit))

    def edit_definition(o):
        """The Mesh Control PM for a control it made, else None."""
        if o is not None and CONTROL in o.PropertiesList:
            return open_control(o)
        return None

    class _Cmd:
        def __init__(self, text, tip, run, need_mesh):
            self.text, self.tip, self.run, self.need_mesh = text, tip, run, need_mesh

        def GetResources(self):
            return {"MenuText": self.text, "ToolTip": self.tip}

        def IsActive(self):
            doc = App.ActiveDocument
            if doc is None or Gui.Control.activeDialog():
                return False
            a = simpms.active_study(doc)
            m = simpms.gmsh_of(a) if a is not None else None
            return m is not None and (not self.need_mesh or m.FemMesh.VolumeCount > 0)

        def Activated(self):
            self.run()

    COMMANDS = {
        "SWStyle_SimMeshControl": _Cmd("Apply Mesh Control", "A finer mesh on chosen faces, edges or vertices, growing "
                                       "by a ratio to the global size.", lambda: open_control(), False),
        "SWStyle_SimMeshQuality": _Cmd("Create Mesh Quality Plot", "The mesh colored by element aspect ratio or "
                                       "Jacobian.", lambda: open_quality(), True),
    }


def install():
    _patch_gmsh()
    if Gui is None:
        return
    have = set(Gui.listCommands())
    for name, cmd in COMMANDS.items():
        if name not in have:
            Gui.addCommand(name, cmd)
