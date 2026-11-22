""


















import math

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

MAX_SECTIONS = 6
REFERENCES = ("Front Plane", "Top Plane", "Right Plane")
NORMALS = {"Front Plane": (0.0, 0.0, 1.0), "Top Plane": (0.0, 1.0, 0.0), "Right Plane": (1.0, 0.0, 0.0)}
TYPES = ("Planar", "Cylindrical", "Spherical")
GREY = (0.78, 0.78, 0.78)
FRAMES = 5
SPEED = 5            # 1 (slow) .. 10 (fast)

CUTS = {}            # a cut frame's node -> its triangles (T, 3, 3) and their values (T, 3), for value_at
STATE = {"a": None, "name": None, "stage": None, "anim": None, "clip": None, "pm": None, "compare": None}


def _fw_log(site, err):
    try:
        App.Console.PrintLog("FreeCAD: %s: %s\n" % (site, err))
    except Exception:
        pass


def _sp():
    from . import simplots
    return simplots


# =========================================================================== the plot's data
class PlotData:
    """The shown plot as arrays: nodes (as they are, and their displacement), the plot's value at every node, the
    mesh's volumes as tetrahedra and its outer triangles, and the plot's colours."""

    def __init__(self, a, name):
        import numpy as np
        sp = _sp()
        self.np = np
        self.a, self.name = a, name
        self.p = p = sp.get_plot(a, name)
        self.s = s = sp.summary(a, p)
        res = s["res"]
        fm = res.Mesh.FemMesh
        every = fm.Nodes                 # (a new dict on each read of the property: read it once)
        nodes = sorted(every.keys())
        at = {n: i for i, n in enumerate(nodes)}
        self.nodes, self.at = nodes, at
        self.base = np.array([(v.x, v.y, v.z) for v in (every[n] for n in nodes)], dtype=float)
        disp = np.zeros_like(self.base)
        for n, d in zip(list(res.NodeNumbers), list(res.DisplacementVectors) or []):
            i = at.get(n)
            if i is not None:
                disp[i] = (d.x, d.y, d.z)
        self.disp = disp
        vals = np.full(len(nodes), float(s["min"]))
        for n, v in s["values"]:
            i = at.get(n)
            if i is not None:
                vals[i] = v
        self.vals = vals
        self.tets = self._tets(fm, at)
        self.tris = np.array([(at[t[0]], at[t[1]], at[t[2]]) for t in sp.sx.surface(res)], dtype=np.int64).reshape(-1, 3)
        self.st = sp.settings_of(p)
        self.chart = sp.chart_of(p)
        self.lo, self.hi = sp.chart_range(p, s)
        self.nc = max(2, int(self.chart.get("ncolours", 10)))
        self.factor = float(sp.SHOWN.get("factor") or 0.0) if p.get("deformed") else 0.0
        if not p.get("show_colors", True):
            self.fringe = "None"
        else:
            self.fringe = self.st.get("fringe", "Continuous")

    def _tets(self, fm, at):
        np = self.np
        out = []
        for v in fm.Volumes:
            n = fm.getElementNodes(v)
            if len(n) in (4, 10):
                out.append(tuple(at[k] for k in n[:4]))
            elif len(n) in (8, 20):
                c = [at[k] for k in n[:8]]
                for t in ((0, 1, 3, 4), (1, 2, 3, 6), (1, 3, 4, 6), (1, 4, 5, 6), (3, 4, 6, 7)):
                    out.append(tuple(c[i] for i in t))
            elif len(n) in (6, 15):
                c = [at[k] for k in n[:6]]
                for t in ((0, 1, 2, 3), (1, 2, 3, 4), (2, 3, 4, 5)):
                    out.append(tuple(c[i] for i in t))
        return np.array(out, dtype=np.int64).reshape(-1, 4)

    def points(self, scale):
        return self.base + self.disp * float(scale)

    def box(self):
        np = self.np
        p = self.points(self.factor)
        return p.min(axis=0), p.max(axis=0)

    def colours(self, values):
        """The plot's colour for each value (its chart, the yield colour, a factor-of-safety plot's two colours)."""
        sp = _sp()
        fake = dict(self.s, values=list(enumerate(float(v) for v in values)))
        try:
            got = sp.node_colours(self.a, self.p, fake)
            return [got[i] for i in range(len(values))]
        except Exception as _fw_err:
            _fw_log("simplotview.py:colours", _fw_err)
            span = (self.hi - self.lo) or 1.0
            return [sp.chart_colour((v - self.lo) / span, self.chart) for v in values]


# =========================================================================== cutting
class Field:
    """Where a section or iso value keeps the model: f(points, values) >= 0 is kept."""

    def __init__(self, kind, flip=False, normal=(0.0, 0.0, 1.0), distance=0.0, axis_point=(0.0, 0.0, 0.0), iso=0.0):
        self.kind, self.flip = kind, bool(flip)
        self.normal, self.distance, self.axis_point, self.iso = normal, float(distance), axis_point, float(iso)

    def __call__(self, np, pts, vals):
        n = np.asarray(self.normal, dtype=float)
        c = np.asarray(self.axis_point, dtype=float)
        if self.kind == "Planar":
            f = pts @ n - self.distance
        elif self.kind == "Cylindrical":
            d = pts - c
            r = d - np.outer(d @ n, n)
            f = np.sqrt((r * r).sum(axis=1)) - self.distance
        elif self.kind == "Spherical":
            d = pts - c
            f = np.sqrt((d * d).sum(axis=1)) - self.distance
        else:                                               # iso: at or above the value kept
            f = vals - self.iso

        if self.kind in ("Planar", "Cylindrical", "Spherical"):
            f = -f
        return -f if self.flip else f


def _lerp(a, b, fa, fb):
    k = fa / (fa - fb)
    return [x + (y - x) * k for x, y in zip(a, b)]


def _clip_poly(poly, k):
    """Sutherland-Hodgman: the part of a polygon (vertex rows [x, y, z, value, f0, f1 ...]) where field k >= 0."""
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        fa, fb = a[4 + k], b[4 + k]
        if fa >= 0:
            out.append(a)
        if (fa >= 0) != (fb >= 0) and fa != fb:
            out.append(_lerp(a, b, fa, fb))
    return out


def cut(data, fields, scale):
    """The model cut by the fields: (surface polygons, cap polygons, cut lines). A polygon is a list of
    [x, y, z, value, ...] rows; a cap is (field index, polygon)."""
    np = data.np
    pts = data.points(scale)
    vals = data.vals
    F = np.array([f(np, pts, vals) for f in fields]).reshape(len(fields), -1) if fields else np.zeros((0, len(pts)))
    rows = np.concatenate([pts, vals[:, None], F.T], axis=1)
    # outer triangles
    surf = []
    tf = F[:, data.tris] if len(fields) else np.zeros((0, len(data.tris), 3))
    keep_all = np.all(tf >= 0, axis=(0, 2)) if len(fields) else np.ones(len(data.tris), bool)
    drop = np.any(np.all(tf < 0, axis=2), axis=0) if len(fields) else np.zeros(len(data.tris), bool)
    whole = data.tris[keep_all]
    for t in data.tris[~keep_all & ~drop]:
        poly = [list(rows[i]) for i in t]
        for k in range(len(fields)):
            poly = _clip_poly(poly, k)
            if len(poly) < 3:
                break
        if len(poly) >= 3:
            surf.append(poly)
    # the cut faces inside: each field's zero surface through the tetrahedra, kept where the other fields keep
    caps = []
    for k in range(len(fields)):
        ft = F[k][data.tets]
        sign = ft >= 0
        crossing = data.tets[sign.any(axis=1) & ~sign.all(axis=1)]
        for t in crossing:
            poly = _tet_cut(rows, t, 4 + k)
            for j in range(len(fields)):
                if j != k and len(poly) >= 3:
                    poly = _clip_poly(poly, j)
            if len(poly) >= 3:
                caps.append((k, poly))
    return whole, surf, caps, rows


def _tet_cut(rows, t, col):
    """The polygon where a tetrahedron's (linear) field crosses 0, its vertices in order around it, facing the cut
    away side (from the kept corners to the cut-away ones)."""
    corners = [rows[i] for i in t]
    f = [c[col] for c in corners]
    pts = []
    for i in range(4):
        for j in range(i + 1, 4):
            if (f[i] >= 0) != (f[j] >= 0) and f[i] != f[j]:
                pts.append(_lerp(list(corners[i]), list(corners[j]), f[i], f[j]))
    if len(pts) < 3:
        return []
    cx = [sum(p[m] for p in pts) / len(pts) for m in range(3)]
    kept = [c for c, v in zip(corners, f) if v >= 0]
    gone = [c for c, v in zip(corners, f) if v < 0]
    out_dir = [sum(c[m] for c in gone) / len(gone) - sum(c[m] for c in kept) / len(kept) for m in range(3)]
    if len(pts) == 4:                           # a quad: order its corners around its centre
        u = [pts[0][m] - cx[m] for m in range(3)]
        v = _cross(out_dir, u)
        pts.sort(key=lambda p: math.atan2(sum((p[m] - cx[m]) * v[m] for m in range(3)),
                                          sum((p[m] - cx[m]) * u[m] for m in range(3))))
    a, b, c = pts[0], pts[1], pts[2]
    nrm = _cross([b[m] - a[m] for m in range(3)], [c[m] - a[m] for m in range(3)])
    if sum(nrm[m] * out_dir[m] for m in range(3)) < 0:
        pts.reverse()
    return pts


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


# =========================================================================== drawing a cut plot
def _fan(polys):
    tris = []
    for poly in polys:
        for i in range(1, len(poly) - 1):
            tris.append((poly[0], poly[i], poly[i + 1]))
    return tris


def draw_cut(data, fields, scale, contour_uncut=True, cut_only=False):
    """The cut plot as a Coin node, in the plot's fringe and boundary settings."""
    from pivy import coin
    sp = _sp()
    whole, surf, caps, rows = cut(data, fields, scale)
    root = coin.SoSeparator()
    root.setName("SWSimPlotCut")
    hints = coin.SoShapeHints()
    hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
    hints.shapeType = coin.SoShapeHints.UNKNOWN_SHAPE_TYPE      # both sides lit
    root.addChild(hints)
    shown_surface = [] if cut_only else [[list(rows[i]) for i in t] for t in whole] + surf
    groups = []
    if shown_surface:
        groups.append((_fan(shown_surface), contour_uncut))
    if caps:
        groups.append((_fan([poly for _k, poly in caps]), True))
    off = coin.SoPolygonOffset()
    root.addChild(off)
    try:
        import numpy as np
        every = [t for tris, _c in groups for t in tris]
        if every:
            arr = np.array([[q[:4] for q in t] for t in every], dtype=float)
            CUTS[int(root.this)] = (arr[:, :, :3], arr[:, :, 3])
    except Exception as _fw_err:
        _fw_log("simplotview.py:cuts", _fw_err)
    for tris, coloured in groups:
        root.addChild(_faces(data, tris, coloured))
    lines = coin.SoSeparator()
    segs = _boundary(data, fields, rows, cut_only)
    if data.fringe == "Line":
        levels = [data.lo + (data.hi - data.lo) * k / float(data.nc) for k in range(1, data.nc)]
        all_tris = [t for tris, coloured in groups if coloured for t in tris]
        flat_pts = [q for t in all_tris for q in t]
        local = [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(all_tris))]
        cs = sp.contours(local, [tuple(q[:3]) for q in flat_pts], [q[3] for q in flat_pts], levels)
        if cs:
            lines.addChild(_line_node([(a, b) for _l, a, b in cs], [sp.chart_colour((lv - data.lo) / ((data.hi - data.lo) or 1.0), data.chart) for lv, _a, _b in cs], 2))
    if segs:
        colour = tuple(data.st.get("boundary_colour") or (0.0, 0.0, 0.5))
        lines.addChild(_line_node(segs, [colour] * len(segs), 1, base_colour=True))
    root.addChild(lines)
    ghost = _superimposed(data, fields, scale)
    if ghost is not None:
        root.addChild(ghost)
    return root


def _superimposed(data, fields, scale):
    """Settings > Superimpose model on the deformed shape: the model as it was, see-through, cut as the plot is."""
    st = data.st
    if not st.get("superimpose") or not scale or not data.p.get("deformed"):
        return None
    from pivy import coin
    sp = _sp()
    whole, surf, _caps, rows = cut(data, fields, 0.0)
    polys = [[list(rows[i]) for i in t] for t in whole] + surf
    if not polys:
        return None
    tris = _fan(polys)
    flat = [tuple(q[:3]) for t in tris for q in t]
    sep = coin.SoSeparator()
    sep.setName("SWSimPlotCutGhost")
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    m = coin.SoMaterial()
    try:
        first = sp.SUPERIMPOSE[0]
        colour = sp._part_colour(data.a) if st.get("super_style", first) == first else (0.6, 0.6, 0.65)
    except Exception as _fw_err:
        _fw_log("simplotview.py:ghost", _fw_err)
        colour = (0.6, 0.6, 0.65)
    m.diffuseColor.setValue(*colour)
    m.transparency = max(0.0, min(0.95, float(st.get("translucency", 0.9))))
    c = coin.SoCoordinate3()
    c.point.setValues(0, len(flat), flat)
    fs = coin.SoFaceSet()
    fs.numVertices.setValues(0, len(tris), [3] * len(tris))
    for n in (pick, m, c, fs):
        sep.addChild(n)
    return sep


def _faces(data, tris, coloured):
    from pivy import coin
    sp = _sp()
    sep = coin.SoSeparator()
    fringe = data.fringe if coloured else "None"
    if fringe == "Discrete":
        cuts = [data.lo + (data.hi - data.lo) * k / float(data.nc) for k in range(1, data.nc)]
        if data.p["quantity"] == "Factor of Safety" and data.p.get("below"):
            cuts = [float(data.p.get("below_value", 1.0))]
        pts, local = [], []
        for t in tris:
            local.append((len(pts), len(pts) + 1, len(pts) + 2))
            pts.extend(t)
        pieces = sp.bands(local, [tuple(q[:3]) for q in pts], [q[3] for q in pts], sorted(cuts))
        allp, fl, cols, probe = [], [], [], {}
        for poly, mid in pieces:
            fl.extend(list(range(len(allp), len(allp) + len(poly))) + [-1])
            allp.extend(poly)
            cols.append(sp._band_colour(data.a, data.p, data.s, mid, data.lo, data.hi, probe, data.nc))
        c = coin.SoCoordinate3()
        c.point.setValues(0, len(allp), allp)
        m = coin.SoMaterial()
        m.diffuseColor.setValues(0, len(cols), cols)
        b = coin.SoMaterialBinding()
        b.value = coin.SoMaterialBinding.PER_FACE
        fs = coin.SoIndexedFaceSet()
        fs.coordIndex.setValues(0, len(fl), fl)
        for n in (c, m, b, fs):
            sep.addChild(n)
        return sep
    flat = [q for t in tris for q in t]
    c = coin.SoCoordinate3()
    c.point.setValues(0, len(flat), [tuple(q[:3]) for q in flat])
    m = coin.SoMaterial()
    if fringe == "Continuous":
        m.diffuseColor.setValues(0, len(flat), data.colours([q[3] for q in flat]))
        b = coin.SoMaterialBinding()
        b.value = coin.SoMaterialBinding.PER_VERTEX
        sep.addChild(m)
        sep.addChild(b)
    else:
        m.diffuseColor.setValue(*GREY)
        sep.addChild(m)
    sep.addChild(c)
    fs = coin.SoFaceSet()
    fs.numVertices.setValues(0, len(tris), [3] * len(tris))
    sep.addChild(fs)
    if fringe == "Point":
        ps = coin.SoSeparator()
        pm = coin.SoMaterial()
        pm.diffuseColor.setValues(0, len(flat), data.colours([q[3] for q in flat]))
        pb = coin.SoMaterialBinding()
        pb.value = coin.SoMaterialBinding.PER_VERTEX
        ds = coin.SoDrawStyle()
        ds.pointSize = 5
        pset = coin.SoPointSet()
        pset.numPoints = len(flat)
        for n in (ds, pm, pb, pset):
            ps.addChild(n)
        sep.addChild(ps)
    return sep


def _boundary(data, fields, rows, cut_only):
    """The plot's boundary (Model: the model's edges, Mesh: every element edge) where the cut keeps the model, and
    the lines where the cuts meet the model's outside."""
    np = data.np
    sp = _sp()
    segs = []
    mode = data.st.get("boundary", "Model")
    k = len(fields)
    if mode in ("Model", "Mesh") and not cut_only:
        pts = [tuple(r[:3]) for r in rows]
        local = [tuple(int(i) for i in t) for t in data.tris]
        try:
            edges = sp.edges_of(local, pts, model=mode == "Model")
        except Exception as _fw_err:
            _fw_log("simplotview.py:edges", _fw_err)
            edges = []
        for i, j in edges:
            a, b = list(rows[i]), list(rows[j])
            ok = True
            for m in range(k):
                fa, fb = a[4 + m], b[4 + m]
                if fa < 0 and fb < 0:
                    ok = False
                    break
                if (fa >= 0) != (fb >= 0) and fa != fb:
                    q = _lerp(a, b, fa, fb)
                    if fa < 0:
                        a = q
                    else:
                        b = q
            if ok:
                segs.append((tuple(a[:3]), tuple(b[:3])))
    # where each cut meets the outside: the zero line of its field on the outer triangles (kept by the others)
    for m in range(k):
        f = rows[:, 4 + m]
        tf = f[data.tris]
        cross = data.tris[(tf >= 0).any(axis=1) & ~(tf >= 0).all(axis=1)]
        for t in cross:
            q = []
            for i, j in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                if (f[i] >= 0) != (f[j] >= 0) and f[i] != f[j]:
                    q.append(_lerp(list(rows[i]), list(rows[j]), f[i], f[j]))
            if len(q) == 2 and all(min(p[4 + o] for p in q) >= -1e-9 or o == m for o in range(k)):
                segs.append((tuple(q[0][:3]), tuple(q[1][:3])))
    return segs


def _line_node(segs, colours, width, base_colour=False):
    from pivy import coin
    sep = coin.SoSeparator()
    if base_colour:
        lm = coin.SoLightModel()
        lm.model = coin.SoLightModel.BASE_COLOR
        sep.addChild(lm)
    ds = coin.SoDrawStyle()
    ds.lineWidth = width
    c = coin.SoCoordinate3()
    c.point.setValues(0, 2 * len(segs), [q for s in segs for q in s])
    m = coin.SoMaterial()
    if len(set(colours)) == 1:
        m.diffuseColor.setValue(*colours[0])
        bind = None
    else:
        m.diffuseColor.setValues(0, len(colours), colours)
        bind = coin.SoMaterialBinding()
        bind.value = coin.SoMaterialBinding.PER_PART
    ls = coin.SoLineSet()
    ls.numVertices.setValues(0, len(segs), [2] * len(segs))
    for n in (ds, c, m, bind, ls):
        if n is not None:
            sep.addChild(n)
    return sep


# =========================================================================== the stage: the plot under our control
class Stage:
    """Holds the shown plot's node in a switch of frames (the animation) under clip-free control: the node simplots
    drew is taken out of the scene and put back as it was when we are done."""

    def __init__(self, a, name):
        from pivy import coin
        sp = _sp()
        node = sp.SHOWN.get("node")
        if node is None:
            raise RuntimeError("Show the plot first.")
        self.a, self.name = a, name
        self.view, self.root = node[0], node[1]
        self.graph = self.view.getSceneGraph()
        self.sep = coin.SoSeparator()
        self.sep.setName("SWSimPlotStage")
        self.frames = coin.SoSwitch()
        self.frames.setName("SWSimPlotFrames")
        self.extra = coin.SoSeparator()             # the section planes as you see them while you place them
        self.sep.addChild(self.frames)
        self.sep.addChild(self.extra)
        self.scales = []
        self.data = None
        i = self.graph.findChild(self.root)
        if i < 0:
            raise RuntimeError("The plot is not in the view.")
        self.graph.replaceChild(i, self.sep)
        self.set_frames(None)

    def _data(self):
        if self.data is None:
            self.data = PlotData(self.a, self.name)
        return self.data

    def full_scale(self):
        sp = _sp()
        p = sp.get_plot(self.a, self.name)
        return float(sp.SHOWN.get("factor") or 0.0) if p is not None and p.get("deformed") else 0.0

    def _plain(self, scale):
        """simplots' own drawing at another deformation scale (taken back out of the scene)."""
        sp = _sp()
        if abs(scale - self.full_scale()) < 1e-12:
            return self.root
        keep = (sp.SHOWN.get("node"), sp.SHOWN.get("drawn"))
        p = sp.get_plot(self.a, self.name)
        s = sp.summary(self.a, p)
        cols = sp.node_colours(self.a, p, s)
        try:
            sp._draw(self.a, s["res"], cols, scale, p, s)
            made = sp.SHOWN["node"][1]
            self.graph.removeChild(made)
        finally:
            sp.SHOWN["node"], sp.SHOWN["drawn"] = keep
        return made

    def set_frames(self, scales, cut=None):
        """The frames at these deformation scales (None: the plot as shown), each cut as cut says
        (fields, contour on uncut, cut only) or drawn by simplots."""
        self.frames.removeAllChildren()
        CUTS.clear()
        full = self.full_scale()
        self.scales = list(scales) if scales else [full]
        for sc in self.scales:
            if cut is not None and cut[3]:
                node = draw_cut(self._data(), cut[0], sc, cut[1], cut[2])
            else:
                node = self._plain(sc)
            self.frames.addChild(node)
        self.show_frame(len(self.scales) - 1)

    def show_frame(self, i):
        self.frames.whichChild = max(0, min(i, self.frames.getNumChildren() - 1))

    def release(self):
        try:
            i = self.graph.findChild(self.sep)
            if i >= 0:
                self.graph.replaceChild(i, self.root)
        except Exception as _fw_err:
            _fw_log("simplotview.py:release", _fw_err)


def stage(a, name):
    st = STATE.get("stage")
    if st is not None and (st.a is not a or st.name != name):
        teardown()
        st = None
    if st is None:
        st = STATE["stage"] = Stage(a, name)
        STATE["a"], STATE["name"] = a, name
    return st


def _refresh():
    """The frames again from what the animation and the clipping ask."""
    st = STATE.get("stage")
    if st is None:
        return
    anim, clip = STATE.get("anim"), STATE.get("clip")
    full = st.full_scale()
    scales = anim.scales(full) if anim is not None else [full]
    cut = clip.cut_args() if clip is not None else None
    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
    try:
        st.set_frames(scales, cut)
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()
    if anim is not None:
        anim.frame_count_changed()
    else:
        st.show_frame(len(scales) - 1)
    st.extra.removeAllChildren()
    if clip is not None and isinstance(STATE.get("pm"), ClipPM):
        clip.draw_planes(st.extra)


def teardown():
    """Animation and clipping off, the plot's own node back in the scene."""
    anim = STATE.get("anim")
    if anim is not None:
        anim.stop(final=False)
    STATE["anim"] = None
    STATE["clip"] = None
    st = STATE.get("stage")
    STATE["stage"] = None
    if st is not None:
        st.release()
    pm = STATE.get("pm")
    STATE["pm"] = None
    if pm is not None:
        try:
            if Gui.Control.activeDialog() and pm in getattr(_sp(), "OPEN", []):
                Gui.Control.closeDialog()
        except Exception as _fw_err:
            _fw_log("simplotview.py:close", _fw_err)


def value_at(point):
    """The plot's value at a point on the shown cut plot (a cut face or the cut model's outside), interpolated in the
    triangle nearest the point; None when the plot is not cut. For Probe (simplots.pick_drawn)."""
    st = STATE.get("stage")
    if st is None:
        return None
    try:
        import numpy as np
        i = st.frames.whichChild.getValue()
        node = st.frames.getChild(i) if 0 <= i < st.frames.getNumChildren() else None
        got = CUTS.get(int(node.this)) if node is not None else None
        if got is None:
            return None
        tri, vals = got
        p = np.array([float(point[0]), float(point[1]), float(point[2])])
        a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
        ab, ac, ap = b - a, c - a, p - a
        d00 = (ab * ab).sum(1)
        d01 = (ab * ac).sum(1)
        d11 = (ac * ac).sum(1)
        d20 = (ap * ab).sum(1)
        d21 = (ap * ac).sum(1)
        den = d00 * d11 - d01 * d01
        den[den == 0] = 1e-30
        v = np.clip((d11 * d20 - d01 * d21) / den, 0.0, 1.0)
        w = np.clip((d00 * d21 - d01 * d20) / den, 0.0, 1.0)
        over = v + w > 1.0
        v[over], w[over] = v[over] / (v + w)[over], w[over] / (v + w)[over]
        u = 1.0 - v - w
        q = a * u[:, None] + b * v[:, None] + c * w[:, None]
        k = int(((q - p) ** 2).sum(1).argmin())
        return float(vals[k, 0] * u[k] + vals[k, 1] * v[k] + vals[k, 2] * w[k])
    except Exception as _fw_err:
        _fw_log("simplotview.py:value_at", _fw_err)
        return None


# =========================================================================== Animate
class Animation:
    """The frames from the model as it is to the deformed shape (and back, when it reciprocates)."""

    def __init__(self):
        self.frames = FRAMES
        self.speed = SPEED
        self.reciprocate = True
        self.at = 0
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.tick)
        self.order = []
        self.record = None              # [path, images] while saving an AVI

    def scales(self, full):
        n = max(2, int(self.frames))
        return [full * k / float(n - 1) for k in range(n)]

    def frame_count_changed(self):
        n = max(2, int(self.frames))
        self.order = list(range(n)) + (list(range(n - 2, 0, -1)) if self.reciprocate else [])
        self.at = min(self.at, len(self.order) - 1)
        st = STATE.get("stage")
        if st is not None:
            st.show_frame(self.order[self.at])

    def interval(self):
        return int(1000.0 / (1.5 + 2.0 * self.speed))       # 1: about 3 frames a second .. 10: about 20

    def play(self):
        if not self.order:
            self.frame_count_changed()
        self.timer.start(self.interval())

    def pause(self):
        self.timer.stop()

    def restart(self):
        self.at = 0
        self.frame_count_changed()

    def stop(self, final=True):
        """Stopped: the plot back on its deformed shape."""
        self.timer.stop()
        if self.record is not None:
            self._finish_record()
        if final:
            self.at = 0
            st = STATE.get("stage")
            if st is not None:
                st.show_frame(st.frames.getNumChildren() - 1)

    def tick(self):
        st = STATE.get("stage")
        if st is None or not self.order:
            self.timer.stop()
            return
        self.at = (self.at + 1) % len(self.order)
        st.show_frame(self.order[self.at])
        if self.record is not None:
            self._grab()
            if self.at == 0:                  # one full cycle written
                self.timer.stop()
                self._finish_record()

    # -- Save as AVI file
    def start_record(self, path):
        self.record = [path, []]
        self.at = 0
        self.frame_count_changed()
        self._grab()

    def _grab(self):
        try:
            img = grab_view()
            if img is not None:
                self.record[1].append(img)
        except Exception as _fw_err:
            _fw_log("simplotview.py:grab", _fw_err)

    def _finish_record(self):
        path, images = self.record
        self.record = None
        if images:
            try:
                write_avi(path, images, max(1, int(round(1000.0 / self.interval()))))
                App.Console.PrintMessage("FreeCAD: animation saved: %s\n" % path)
            except Exception as error:
                App.Console.PrintError("FreeCAD: the animation could not be saved: %s\n" % error)


def grab_view():
    """The 3D view as you see it (with the legend and title), as a QImage."""
    try:
        from . import simxpress as sx
        host = sx._host()
    except Exception:
        host = None
    QtWidgets.QApplication.processEvents()
    if host is not None:
        img = host.grab().toImage()
        if not img.isNull():
            return img
    view = Gui.ActiveDocument.ActiveView
    import tempfile
    import os
    path = os.path.join(tempfile.gettempdir(), "fw_anim_frame_%d.png" % os.getpid())     # pkg321: per session
    view.saveImage(path, 0, 0, "Current")
    img = QtGui.QImage(path)
    return None if img.isNull() else img


def write_avi(path, images, fps):
    """A Motion JPEG AVI of the images (all made the size of the first)."""
    import struct
    w, h = images[0].width(), images[0].height()
    w -= w % 2
    h -= h % 2
    frames = []
    for img in images:
        if img.width() != w or img.height() != h:
            img = img.scaled(w, h, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
        buf = QtCore.QBuffer()
        buf.open(QtCore.QIODevice.WriteOnly)
        img.convertToFormat(QtGui.QImage.Format_RGB888).save(buf, "JPG", 90)
        frames.append(bytes(buf.data()))
    big = max(len(f) for f in frames)

    def chunk(tag, data):
        pad = b"\0" if len(data) % 2 else b""
        return tag + struct.pack("<I", len(data)) + data + pad

    def lst(tag, data):
        return b"LIST" + struct.pack("<I", len(data) + 4) + tag + data
    avih = struct.pack("<IIIIIIIIII4I", int(1000000 / fps), big * fps, 0, 0x10, len(frames), 0, 1, big, w, h, 0, 0, 0, 0)
    strh = struct.pack("<4s4sIHHIIIIIIIIhhhh", b"vids", b"MJPG", 0, 0, 0, 0, 1, fps, 0, len(frames), big, 0xFFFFFFFF, 0,
                       0, 0, w, h)
    strf = struct.pack("<IiiHH4sIiiII", 40, w, h, 1, 24, b"MJPG", w * h * 3, 0, 0, 0, 0)
    hdrl = lst(b"hdrl", chunk(b"avih", avih) + lst(b"strl", chunk(b"strh", strh) + chunk(b"strf", strf)))
    movi_data = b""
    index = b""
    for f in frames:
        offset = 4 + len(movi_data)                 # from the start of the 'movi' tag
        movi_data += chunk(b"00dc", f)
        index += struct.pack("<4sIII", b"00dc", 0x10, offset, len(f))
    body = b"AVI " + hdrl + lst(b"movi", movi_data) + chunk(b"idx1", index)
    with open(path, "wb") as out:
        out.write(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


# =========================================================================== clipping
class Section:
    def __init__(self):
        self.on = False
        self.kind = "Planar"
        self.reference = "Front Plane"
        self.distance = 0.0
        self.rot_x = 0.0
        self.rot_y = 0.0
        self.flip = False

    def normal(self):
        n = NORMALS[self.reference]
        # the plane turned about its own two in-plane directions (Rotation X then Rotation Y)
        u = (1.0, 0.0, 0.0) if self.reference != "Right Plane" else (0.0, 0.0, 1.0)
        v = _cross(n, u)
        ax, ay = math.radians(self.rot_x), math.radians(self.rot_y)
        n = _rot(n, u, ax)
        v = _rot(v, u, ax)
        n = _rot(n, v, ay)
        return n

    def field(self):
        return Field(self.kind, self.flip, self.normal(), self.distance)


def _rot(p, axis, ang):
    """p turned by ang about the unit axis (Rodrigues)."""
    c, s = math.cos(ang), math.sin(ang)
    d = sum(p[i] * axis[i] for i in range(3))
    x = _cross(axis, p)
    return [p[i] * c + x[i] * s + axis[i] * d * (1 - c) for i in range(3)]


class Iso:
    def __init__(self, value=0.0):
        self.on = False
        self.value = float(value)
        self.flip = False

    def field(self):
        return Field("Iso", self.flip, iso=self.value)


class Clipping:
    ""

    def __init__(self, kind, data):
        self.kind = kind
        self.enabled = True
        self.show_plane = True
        self.contour_uncut = True
        self.cut_only = False
        if kind == "section":
            self.items = [Section() for _i in range(MAX_SECTIONS)]
            self.items[0].on = True
        else:
            mid = 0.5 * (data.lo + data.hi)
            self.items = [Iso(mid) for _i in range(MAX_SECTIONS)]
            self.items[0].on = True

    def fields(self):
        return [it.field() for it in self.items if it.on]

    def cut_args(self):
        f = self.fields() if self.enabled else []
        return (f, self.contour_uncut, self.cut_only, bool(f))

    def draw_planes(self, parent):
        """Show section plane: each section's plane (or cylinder, sphere), see-through, while clipping is on."""
        if self.kind != "section" or not self.show_plane or not self.enabled:
            return
        from pivy import coin
        st = STATE.get("stage")
        if st is None:
            return
        lo, hi = st._data().box()
        centre = [(lo[i] + hi[i]) * 0.5 for i in range(3)]
        size = max(hi[i] - lo[i] for i in range(3)) * 1.3 or 1.0
        for it in self.items:
            if not it.on:
                continue
            sep = coin.SoSeparator()
            sep.setName("SWSimSectionPlane")
            pick = coin.SoPickStyle()
            pick.style = coin.SoPickStyle.UNPICKABLE
            m = coin.SoMaterial()
            m.diffuseColor.setValue(0.55, 0.65, 0.8)
            m.transparency = 0.75
            sep.addChild(pick)
            sep.addChild(m)
            n = it.normal()
            xf = coin.SoTransform()
            rot = coin.SbRotation(coin.SbVec3f(0, 1, 0) if it.kind == "Cylindrical" else coin.SbVec3f(0, 0, 1),
                                  coin.SbVec3f(*n))
            xf.rotation = rot
            if it.kind == "Planar":
                d = sum(centre[i] * n[i] for i in range(3)) - it.distance
                xf.translation = coin.SbVec3f(*[centre[i] - n[i] * d for i in range(3)])
                sep.addChild(xf)
                c = coin.SoCoordinate3()
                hu, hv = plane_half_sizes(lo, hi, rot)
                c.point.setValues(0, 4, [(-hu, -hv, 0), (hu, -hv, 0), (hu, hv, 0), (-hu, hv, 0)])
                sep.addChild(c)
                hints = coin.SoShapeHints()
                hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
                sep.addChild(hints)
                fs = coin.SoFaceSet()
                fs.numVertices = 4
                sep.addChild(fs)
                lm = coin.SoLightModel()
                lm.model = coin.SoLightModel.BASE_COLOR
                ec = coin.SoMaterial()
                ec.diffuseColor.setValue(0.2, 0.3, 0.55)
                ls = coin.SoLineSet()
                c2 = coin.SoCoordinate3()
                c2.point.setValues(0, 5, [(-hu, -hv, 0), (hu, -hv, 0), (hu, hv, 0), (-hu, hv, 0), (-hu, -hv, 0)])
                for x in (lm, ec, c2, ls):
                    sep.addChild(x)
            elif it.kind == "Cylindrical":
                sep.addChild(xf)
                cyl = coin.SoCylinder()
                cyl.radius = max(1e-6, it.distance)
                cyl.height = size * 1.2
                cyl.parts = coin.SoCylinder.SIDES
                sep.addChild(cyl)
            else:
                sph = coin.SoSphere()
                sph.radius = max(1e-6, it.distance)
                sep.addChild(sph)
            parent.addChild(sep)


PLANE_MARGIN = 0.08      # Show section plane: the plane is this much (of the model's size) past the model on each side


def plane_half_sizes(lo, hi, rot):
    ""

    from pivy import coin
    axes = []
    for a in ((1, 0, 0), (0, 1, 0)):
        axes.append(rot.multVec(coin.SbVec3f(*a)).getValue())     # pivy returns the turned vector
    span = max(hi[i] - lo[i] for i in range(3)) or 1.0
    out = []
    for ax in axes:
        half = sum(abs(ax[i]) * (hi[i] - lo[i]) for i in range(3)) * 0.5
        out.append(max(half, span * 0.02) + span * PLANE_MARGIN)
    return tuple(out)


def type_icon(kind, px=22):
    """Planar / Cylindrical / Spherical: our own small drawings for the Section Clipping type buttons."""
    pix = QtGui.QPixmap(px, px)
    pix.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    k = px / 22.0
    line = QtGui.QPen(QtGui.QColor(40, 70, 130), 1.4 * k)
    fill = QtGui.QColor(120, 160, 225, 150)
    p.setPen(line)
    p.setBrush(fill)
    if kind == "Planar":
        poly = QtGui.QPolygonF([QtCore.QPointF(x * k, y * k) for x, y in ((3, 15), (8, 5), (19, 5), (14, 15))])
        p.drawPolygon(poly)
        p.setPen(QtGui.QPen(QtGui.QColor(200, 60, 40), 1.6 * k))
        p.drawLine(QtCore.QPointF(11 * k, 10 * k), QtCore.QPointF(11 * k, 19 * k))
    elif kind == "Cylindrical":
        p.drawRect(QtCore.QRectF(5 * k, 5 * k, 12 * k, 12 * k))
        p.setPen(QtCore.Qt.NoPen)
        p.drawEllipse(QtCore.QRectF(5 * k, 14 * k, 12 * k, 5 * k))
        p.setPen(line)
        p.setBrush(QtGui.QColor(170, 200, 240))
        p.drawEllipse(QtCore.QRectF(5 * k, 3 * k, 12 * k, 5 * k))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawArc(QtCore.QRectF(5 * k, 14 * k, 12 * k, 5 * k), 180 * 16, 180 * 16)
    else:
        p.drawEllipse(QtCore.QRectF(3 * k, 3 * k, 16 * k, 16 * k))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawEllipse(QtCore.QRectF(3 * k, 8.5 * k, 16 * k, 5 * k))
        p.drawEllipse(QtCore.QRectF(8.5 * k, 3 * k, 5 * k, 16 * k))
    p.end()
    return QtGui.QIcon(pix)


# =========================================================================== PMs
def _box(title, pm_title=None):
    w = QtWidgets.QWidget()
    w.setWindowTitle(title)
    if pm_title:
        w.setProperty("swstyle_pm_title", pm_title)
    return w


def _spin(lo, hi, value, step, suffix, name, decimals=2):
    s = QtWidgets.QDoubleSpinBox()
    s.setObjectName(name)
    s.setDecimals(decimals)
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setSuffix(suffix)
    s.setValue(value)
    return s


class AnimatePM:
    ""

    def __init__(self, a, name):
        self.a, self.name = a, name
        stage(a, name)
        anim = STATE.get("anim") or Animation()
        STATE["anim"] = anim
        self.anim = anim
        basics = _box("Basics", "Animation")
        v = QtWidgets.QVBoxLayout(basics)
        row = QtWidgets.QHBoxLayout()
        style = QtWidgets.QApplication.style()
        self.buttons = {}
        for key, icon, tip, fn in (("restart", QtWidgets.QStyle.SP_MediaSkipBackward, "Restart", self._restart),
                                   ("play", QtWidgets.QStyle.SP_MediaPlay, "Play", self._play),
                                   ("pause", QtWidgets.QStyle.SP_MediaPause, "Pause", self._pause),
                                   ("stop", QtWidgets.QStyle.SP_MediaStop, "Stop", self._stop)):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWSimAnim_" + key)
            b.setIcon(style.standardIcon(icon))
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.clicked.connect(fn)
            row.addWidget(b)
            self.buttons[key] = b
        row.addStretch(1)
        v.addLayout(row)
        form = QtWidgets.QFormLayout()
        self.frames = QtWidgets.QSpinBox()
        self.frames.setObjectName("SWSimAnimFrames")
        self.frames.setRange(2, 100)
        self.frames.setValue(anim.frames)
        self.frames.valueChanged.connect(self._frames)
        form.addRow("Frames:", self.frames)
        self.speed = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.speed.setObjectName("SWSimAnimSpeed")
        self.speed.setRange(1, 10)
        self.speed.setValue(anim.speed)
        self.speed.valueChanged.connect(self._speed)
        sl = QtWidgets.QHBoxLayout()
        sl.addWidget(QtWidgets.QLabel("Slow"))
        sl.addWidget(self.speed, 1)
        sl.addWidget(QtWidgets.QLabel("Fast"))
        form.addRow("Speed:", sl)
        v.addLayout(form)
        self.recip = QtWidgets.QCheckBox("Animate in both directions")
        self.recip.setObjectName("SWSimAnimReciprocate")
        self.recip.setChecked(anim.reciprocate)
        self.recip.toggled.connect(self._recip)
        v.addWidget(self.recip)
        avi = _box("Save as AVI file")
        av = QtWidgets.QVBoxLayout(avi)
        self.save = QtWidgets.QCheckBox("Save as AVI file")
        self.save.setObjectName("SWSimAnimSave")
        av.addWidget(self.save)
        prow = QtWidgets.QHBoxLayout()
        self.path = QtWidgets.QLineEdit(self._default_path())
        self.path.setObjectName("SWSimAnimPath")
        browse = QtWidgets.QPushButton("...")
        browse.setObjectName("SWSimAnimBrowse")
        browse.setFixedWidth(28)
        browse.clicked.connect(self._browse)
        prow.addWidget(self.path, 1)
        prow.addWidget(browse)
        av.addLayout(prow)
        self.viewer = QtWidgets.QCheckBox("View with AVI viewer")
        self.viewer.setObjectName("SWSimAnimViewer")
        av.addWidget(self.viewer)
        self.save.toggled.connect(self._save_enable)
        self._save_enable()
        self.form = [basics, avi]
        _refresh()
        anim.restart()
        anim.play()
        STATE["pm"] = self

    def _default_path(self):
        import os
        doc = self.a.Document
        folder = os.path.dirname(doc.FileName) if doc.FileName else os.path.expanduser("~")
        return os.path.join(folder, "%s-%s-%s.avi" % (doc.Label or doc.Name, self.a.Label, self.name))

    def _save_enable(self, *_a):
        on = self.save.isChecked()
        for w in (self.path, self.viewer):
            w.setEnabled(on)
        self.path.parentWidget().findChild(QtWidgets.QPushButton, "SWSimAnimBrowse").setEnabled(on)

    def _browse(self):
        path, _f = QtWidgets.QFileDialog.getSaveFileName(None, "Save as AVI file", self.path.text(), "AVI files (*.avi)")
        if path:
            self.path.setText(path if path.lower().endswith(".avi") else path + ".avi")

    def _play(self):
        if self.save.isChecked() and self.anim.record is None:
            self.anim.start_record(self.path.text())
        self.anim.play()

    def _pause(self):
        self.anim.pause()

    def _stop(self):
        self.anim.stop()
        self._after_record()

    def _restart(self):
        self.anim.restart()

    def _after_record(self):
        if self.save.isChecked() and self.viewer.isChecked():
            import os
            if os.path.isfile(self.path.text()):
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self.path.text()))

    def _frames(self, n):
        self.anim.frames = int(n)
        running = self.anim.timer.isActive()
        _refresh()
        if running:
            self.anim.play()

    def _speed(self, n):
        self.anim.speed = int(n)
        if self.anim.timer.isActive():
            self.anim.timer.start(self.anim.interval())

    def _recip(self, on):
        self.anim.reciprocate = bool(on)
        self.anim.frame_count_changed()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok

    def _close(self):
        anim = STATE.get("anim")
        if anim is not None:
            anim.stop()
            if anim.record is not None:
                anim._finish_record()
        STATE["anim"] = None
        STATE["pm"] = None
        if STATE.get("clip") is None:
            teardown()
        else:
            _refresh()

    def accept(self):
        self._close()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        return self.accept()


class ClipPM:
    ""


    def __init__(self, a, name, kind):
        self.a, self.name, self.kind = a, name, kind
        st = stage(a, name)
        clip = STATE.get("clip")
        if clip is None or clip.kind != kind:
            clip = STATE["clip"] = Clipping(kind, st._data())
        self.clip = clip
        self.data = st._data()
        self.current = 0
        word = "Section" if kind == "section" else "Iso"
        opts = _box("Options", "Section Clipping" if kind == "section" else "Iso Clipping")
        try:
            from . import simicons          # the PM's title icon: the ribbon button's own picture
            opts.setProperty("swstyle_pm_icon", simicons.family_or_drawing("SIM_Section" if kind == "section" else "SIM_IsoClip"))
        except Exception as _fw_err:
            _fw_log("simplotview.py:pmicon", _fw_err)
        ov = QtWidgets.QVBoxLayout(opts)
        row = QtWidgets.QHBoxLayout()
        self.toggles = []
        for i in range(MAX_SECTIONS):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWSimClipToggle%d" % (i + 1))
            b.setText(str(i + 1))
            b.setToolTip("%s %d" % (word, i + 1))
            b.setCheckable(True)
            b.setChecked(clip.items[i].on)
            b.clicked.connect(lambda checked=False, i=i: self._toggle(i, checked))
            row.addWidget(b)
            self.toggles.append(b)
        row.addStretch(1)
        ov.addLayout(row)
        if kind == "section":
            self.show_plane = QtWidgets.QCheckBox("Show section plane")
            self.show_plane.setObjectName("SWSimClipShowPlane")
            self.show_plane.setChecked(clip.show_plane)
            self.show_plane.toggled.connect(self._options)
            ov.addWidget(self.show_plane)
        self.cut_only = QtWidgets.QCheckBox("Plot on section only" if kind == "section" else "Plot on iso surface only")
        self.cut_only.setObjectName("SWSimClipCutOnly")
        self.cut_only.setChecked(clip.cut_only)
        self.cut_only.toggled.connect(self._options)
        ov.addWidget(self.cut_only)
        self.contour = QtWidgets.QCheckBox("Show contour on uncut portion of the model")
        self.contour.setObjectName("SWSimClipContour")
        self.contour.setChecked(clip.contour_uncut)
        self.contour.toggled.connect(self._options)
        ov.addWidget(self.contour)
        brow = QtWidgets.QHBoxLayout()
        self.onoff = QtWidgets.QPushButton("Clipping on/off")
        self.onoff.setObjectName("SWSimClipOnOff")
        self.onoff.setCheckable(True)
        self.onoff.setChecked(clip.enabled)
        self.onoff.toggled.connect(self._onoff)
        reset = QtWidgets.QPushButton("Reset")
        reset.setObjectName("SWSimClipReset")
        reset.clicked.connect(self._reset)
        brow.addWidget(self.onoff)
        brow.addWidget(reset)
        ov.addLayout(brow)
        self.item_box = _box("%s 1" % word)
        form = QtWidgets.QFormLayout(self.item_box)
        if kind == "section":
            trow = QtWidgets.QHBoxLayout()
            self.types = {}
            for t in TYPES:
                b = QtWidgets.QToolButton()
                b.setObjectName("SWSimClipType_" + t)
                b.setText(t)
                b.setIcon(type_icon(t))
                b.setIconSize(QtCore.QSize(22, 22))
                b.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
                b.setAutoRaise(True)
                b.setToolTip(t)
                b.setCheckable(True)
                b.setAutoExclusive(True)
                b.clicked.connect(lambda checked=False, t=t: self._edit(kind=t))
                trow.addWidget(b)
                self.types[t] = b
            form.addRow(trow)
            self.reference = QtWidgets.QComboBox()
            self.reference.setObjectName("SWSimClipReference")
            self.reference.addItems(list(REFERENCES))
            self.reference.currentTextChanged.connect(lambda t: self._edit(reference=t))
            form.addRow("Reference:", self.reference)
            lo, hi = self.data.box()
            span = float(max(hi - lo)) or 1.0
            self.distance = _spin(-1e6, 1e6, 0.0, span / 50.0, " mm", "SWSimClipDistance")
            self.distance.valueChanged.connect(lambda v: self._edit(distance=v))
            self.dlabel = QtWidgets.QLabel("Distance:")
            form.addRow(self.dlabel, self.distance)
            self.rot_x = _spin(-360.0, 360.0, 0.0, 5.0, " deg", "SWSimClipRotX")
            self.rot_x.valueChanged.connect(lambda v: self._edit(rot_x=v))
            self.rot_y = _spin(-360.0, 360.0, 0.0, 5.0, " deg", "SWSimClipRotY")
            self.rot_y.valueChanged.connect(lambda v: self._edit(rot_y=v))
            self.rx_label, self.ry_label = QtWidgets.QLabel("Rotation X:"), QtWidgets.QLabel("Rotation Y:")
            form.addRow(self.rx_label, self.rot_x)
            form.addRow(self.ry_label, self.rot_y)
        else:
            lo, hi = self.data.lo, self.data.hi
            self.value = _spin(-1e30, 1e30, 0.5 * (lo + hi), (hi - lo) / 50.0 or 1.0, " " + str(self.data.p.get("unit", "")),
                               "SWSimClipIso", 4)
            self.value.valueChanged.connect(lambda v: self._edit(value=v))
            form.addRow("Iso value:", self.value)
            self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            self.slider.setObjectName("SWSimClipIsoSlider")
            self.slider.setRange(0, 1000)
            self.slider.valueChanged.connect(self._slide)
            form.addRow(self.slider)
        self.flip = QtWidgets.QCheckBox("Flip")
        self.flip.setObjectName("SWSimClipFlip")
        self.flip.toggled.connect(lambda on: self._edit(flip=on))
        form.addRow(self.flip)
        self.form = [opts, self.item_box]
        self.timer = QtCore.QTimer()
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)          # a spin held down redraws once it settles
        self.timer.timeout.connect(_refresh)
        self._load(0)
        self._enable()
        STATE["pm"] = self
        _refresh()

    # -- the PM <-> the clipping
    def _load(self, i):
        self.current = i
        it = self.clip.items[i]
        word = "Section" if self.kind == "section" else "Iso"
        self.item_box.setWindowTitle("%s %d" % (word, i + 1))
        self._loading = True
        try:
            if self.kind == "section":
                self.types[it.kind].setChecked(True)
                self.reference.setCurrentText(it.reference)
                self.distance.setValue(it.distance)
                self.rot_x.setValue(it.rot_x)
                self.rot_y.setValue(it.rot_y)
                self._kind_rows(it.kind)
            else:
                self.value.setValue(it.value)
                self._slider_from(it.value)
            self.flip.setChecked(it.flip)
        finally:
            self._loading = False

    def _kind_rows(self, kind):
        self.dlabel.setText("Distance:" if kind == "Planar" else "Radius:")
        for w in (self.rot_x, self.rot_y, self.rx_label, self.ry_label):
            w.setVisible(kind == "Planar")

    def _slider_from(self, v):
        span = (self.data.hi - self.data.lo) or 1.0
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(1000 * (v - self.data.lo) / span)))
        self.slider.blockSignals(False)

    def _slide(self, k):
        self.value.setValue(self.data.lo + (self.data.hi - self.data.lo) * k / 1000.0)

    def _edit(self, **values):
        if getattr(self, "_loading", False):
            return
        it = self.clip.items[self.current]
        for k, v in values.items():
            setattr(it, k, v)
        if "kind" in values:
            self._kind_rows(values["kind"])
            if values["kind"] != "Planar" and it.distance <= 0:
                lo, hi = self.data.box()
                it.distance = 0.25 * float(max(hi - lo))
                self._load(self.current)
        if "value" in values:
            self._slider_from(values["value"])
        if not it.on:
            it.on = True
            self.toggles[self.current].setChecked(True)
        self.timer.start()

    def _toggle(self, i, checked):
        it = self.clip.items[i]
        if self.current != i:
            # a click on another section: pick it to edit, and turn it on
            it.on = True
            self.toggles[i].setChecked(True)
            self._load(i)
        else:
            it.on = checked
        if not any(x.on for x in self.clip.items):
            it.on = True
            self.toggles[i].setChecked(True)
        self.timer.start()

    def _options(self, *_a):
        if self.kind == "section":
            self.clip.show_plane = self.show_plane.isChecked()
        self.clip.cut_only = self.cut_only.isChecked()
        self.clip.contour_uncut = self.contour.isChecked()
        self._enable()
        self.timer.start()

    def _enable(self):
        self.contour.setEnabled(not self.cut_only.isChecked())

    def _onoff(self, on):
        self.clip.enabled = bool(on)
        self.timer.start()

    def _reset(self):
        fresh = Clipping(self.kind, self.data)
        fresh.enabled = self.clip.enabled
        self.clip.items = fresh.items
        for i, b in enumerate(self.toggles):
            b.setChecked(self.clip.items[i].on)
        self._load(0)
        self.timer.start()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        """OK: the clipping stays on the plot (Clipping on/off and Reset as you left them), its planes go."""
        self.timer.stop()
        STATE["pm"] = None
        st = STATE.get("stage")
        if st is not None:
            st.extra.removeAllChildren()
        _refresh()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self.timer.stop()
        STATE["pm"] = None
        STATE["clip"] = None
        if STATE.get("anim") is None:
            teardown()
        else:
            _refresh()
        Gui.Control.closeDialog()
        return True


def _open(pm):
    sp = _sp()
    return sp._open(pm)


def animate(a, name):
    return _open(AnimatePM(a, name))


def section_clipping(a, name):
    return _open(ClipPM(a, name, "section"))


def iso_clipping(a, name):
    return _open(ClipPM(a, name, "iso"))


def plot_menu(a, name):
    """simtree: a shown plot's right-click items after Settings..."""
    install()
    return [("Animate...", lambda: animate(a, name)),
            ("Section Clipping...", lambda: section_clipping(a, name)),
            ("Iso Clipping...", lambda: iso_clipping(a, name))]


# =========================================================================== Compare Results
MAX_COMPARE = 4


def comparable(doc):
    """[(study, plot name)] of every study of the document that has results."""
    sp = _sp()
    try:
        from . import simtree
        studies = simtree.studies(doc)
    except Exception as _fw_err:
        _fw_log("simplotview.py:studies", _fw_err)
        studies = []
    out = []
    for a in studies:
        try:
            if sp.result(a) is None:
                continue
            sp.defaults(a)
            out.extend((a, p["name"]) for p in sp.plots(a))
        except Exception as _fw_err:
            _fw_log("simplotview.py:comparable", _fw_err)
    return out


class Comparison:
    ""


    def __init__(self, items):
        self.timer, self.exit_btn, self.nodes, self.overlays, self.made, self.hidden = None, None, [], [], [], []
        self.mode0 = None
        try:
            self._start(items)
        except Exception:
            self.exit()                 # half made: put everything back
            raise

    def _start(self, items):
        sp = _sp()
        items = list(items)[:MAX_COMPARE]
        if not items:
            raise RuntimeError("Pick the results to compare.")
        teardown()
        sp.clear()
        self.items = items
        self.doc = doc = items[0][0].Document
        mw = Gui.getMainWindow()
        self.mdi = mw.findChild(QtWidgets.QMdiArea)
        self.mode0 = self.mdi.viewMode()
        self.subs0 = list(self.mdi.subWindowList())
        self.active0 = self.mdi.activeSubWindow()
        self.geom0 = {id(w): (w.geometry(), w.isMaximized(), w.isMinimized()) for w in self.subs0}
        gd = Gui.getDocument(doc.Name)
        base = gd.ActiveView
        before = set(int(id(w)) for w in self.mdi.subWindowList())
        for _i in range(len(items) - 1):
            self._activate(base)
            Gui.runCommand("Std_ViewCreate")
        self.views = [base] + [v for v in gd.mdiViewsOfType("Gui::View3DInventor") if v is not base][-(len(items) - 1):] \
            if len(items) > 1 else [base]
        self.made = [w for w in self.mdi.subWindowList() if int(id(w)) not in before]
        for a, _n in items:
            keep = list(sp.SHOWN.get("hidden") or [])
            sp.SHOWN["hidden"] = []
            sp._hide_model(a)
            self.hidden.extend(n for n in sp.SHOWN["hidden"] if n not in self.hidden)
            sp.SHOWN["hidden"] = keep
        self.mdi.setViewMode(QtWidgets.QMdiArea.SubWindowView)
        self.windows = [self._window(v) for v in self.views]
        self._layout()
        for view, win, (a, name) in zip(self.views, self.windows, items):
            self._draw(view, win, a, name)
        self.exit_btn = QtWidgets.QPushButton("Exit Compare", Gui.getMainWindow())     # over the views, above all
        self.exit_btn.setObjectName("SWSimExitCompare")
        self.exit_btn.clicked.connect(self.exit)
        self.exit_btn.adjustSize()
        self._place_exit()
        self.exit_btn.show()
        self.exit_btn.raise_()
        self.last = {}
        self._fit()
        QtCore.QTimer.singleShot(150, self._fit)      # again once the windows have their new sizes
        self.timer = QtCore.QTimer()
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._sync)
        self.timer.start()
        STATE["compare"] = self

    def _activate(self, view):
        w = self._window(view)
        if w is not None:
            self.mdi.setActiveSubWindow(w)

    def _window(self, view):
        """The MDI window that holds a view."""
        try:
            gv = view.graphicsView()
            for w in self.mdi.subWindowList():
                if w.isAncestorOf(gv):
                    return w
        except Exception as _fw_err:
            _fw_log("simplotview.py:window", _fw_err)
        gd = Gui.getDocument(self.doc.Name)              # else: FreeCAD's views and their windows in one order
        mine = gd.mdiViewsOfType("Gui::View3DInventor")
        titled = [w for w in self.mdi.subWindowList() if w.windowTitle().split(" : ")[0] == (self.doc.Label or self.doc.Name)]
        try:
            return titled[mine.index(view)]
        except (ValueError, IndexError):
            return None

    def _layout(self):
        rect = self.mdi.viewport().rect()
        n = len(self.windows)
        cols = 1 if n == 1 else 2
        rows = 1 if n <= 2 else 2
        w, h = rect.width() // cols, rect.height() // rows
        for i, win in enumerate(self.windows):
            if win is None:
                continue
            win.showNormal()
            win.setGeometry(QtCore.QRect((i % cols) * w, (i // cols) * h, w, h))
            win.show()
            win.raise_()
        for win in self.mdi.subWindowList():
            if win not in self.windows:
                win.showMinimized()

    def _draw(self, view, win, a, name):
        try:
            self._draw_plot(view, win, a, name)
        except Exception as error:          # this result has no values for the plot: say so in its view
            _fw_log("simplotview.py:compare", error)
            host = win.widget() if win is not None else None
            if host is not None:
                title = QtWidgets.QLabel("%s: %s (%s)" % (a.Label, name, error), host)
                title.setObjectName("SWSimCompareTitle")
                title.setStyleSheet("QLabel { color: #202020; background: rgba(255,255,255,170); padding: 2px 6px; }")
                title.adjustSize()
                lg = QtWidgets.QWidget(host)
                lg.resize(1, 1)
                self.overlays.append((host, lg, title))
                self._place(host, lg, title)
                title.show()

    def _draw_plot(self, view, win, a, name):
        sp = _sp()
        p = sp.get_plot(a, name)
        res = sp.result_for(a, p)
        s = sp.summary(a, p)
        factor = sp.factor_of(a, res, p)
        cols = sp.node_colours(a, p, s)
        keep = (sp.SHOWN.get("node"), sp.SHOWN.get("drawn"))
        self._activate(view)
        try:
            sp._draw(a, res, cols, factor, p, s)
            node = sp.SHOWN["node"]
            if node[0] is not view:              # drawn in another view: move it to this one
                node[0].getSceneGraph().removeChild(node[1])
                view.getSceneGraph().addChild(node[1])
            self.nodes.append((view, node[1]))
        finally:
            sp.SHOWN["node"], sp.SHOWN["drawn"] = keep
        host = win.widget() if win is not None else None
        if host is None:
            return
        lo, hi = sp.chart_range(p, s)
        chart = sp.chart_of(p)
        yield_ = sp.yield_strength(a, p) if p["quantity"] == "Stress" and p["comp"] == "VON" else None
        below = float(p.get("below_value", 1.0)) if p["quantity"] == "Factor of Safety" and p.get("below") else None
        lg = sp.Legend(host, sp.legend_head(p), lo, hi, chart, yield_ if chart.get("show_yield", True) else None, below)
        lg.discrete = sp.settings_of(p)["fringe"] == "Discrete"
        title = QtWidgets.QLabel("%s: %s" % (a.Label, name), host)
        title.setObjectName("SWSimCompareTitle")
        title.setStyleSheet("QLabel { color: #202020; background: rgba(255,255,255,170); padding: 2px 6px; }")
        title.adjustSize()
        self.overlays.append((host, lg, title))
        self._place(host, lg, title)
        lg.show()
        title.show()

    @staticmethod
    def _place(host, lg, title):
        top = 30
        lg.move(max(4, host.width() - lg.width() - 12), top)
        title.move(10, top)
        lg.raise_()
        title.raise_()

    def _place_exit(self):
        if self.exit_btn is None:
            return
        vp = self.mdi.viewport()
        at = vp.mapTo(Gui.getMainWindow(), QtCore.QPoint((vp.width() - self.exit_btn.width()) // 2, 34))
        self.exit_btn.move(at)
        self.exit_btn.raise_()

    def _fit(self):
        """Isometric, the plot filling the first view; the others take its camera."""
        try:
            if STATE.get("compare") not in (None, self):
                return
            v = self.views[0]
            v.viewIsometric()
            v.fitAll()
            self._sync(force=v)
        except Exception as _fw_err:
            _fw_log("simplotview.py:fit", _fw_err)

    @staticmethod
    def _cam(view):
        """The camera as numbers: position, orientation, focal distance and height (or angle)."""
        c = view.getCameraNode()
        h = c.height.getValue() if hasattr(c, "height") else c.heightAngle.getValue()
        return (tuple(round(x, 6) for x in c.position.getValue().getValue()),
                tuple(round(x, 6) for x in c.orientation.getValue().getValue()),
                round(c.focalDistance.getValue(), 6), round(h, 6), c.getTypeId().getName().getString())

    @staticmethod
    def _copy_cam(src, dst):
        a, b = src.getCameraNode(), dst.getCameraNode()
        if a.getTypeId() != b.getTypeId():
            dst.setCamera(src.getCamera())
            return
        b.position.setValue(a.position.getValue())
        b.orientation.setValue(a.orientation.getValue())
        b.focalDistance.setValue(a.focalDistance.getValue())
        b.nearDistance.setValue(a.nearDistance.getValue())
        b.farDistance.setValue(a.farDistance.getValue())
        if hasattr(a, "height"):
            b.height.setValue(a.height.getValue())
        else:
            b.heightAngle.setValue(a.heightAngle.getValue())

    def _sync(self, force=None):
        """The view that moved leads: its camera goes to the others."""
        try:
            cams = {id(v): self._cam(v) for v in self.views}
            lead = force
            if lead is None:
                for v in self.views:
                    if self.last.get(id(v)) is not None and cams[id(v)] != self.last[id(v)]:
                        lead = v
                        break
            if lead is not None:
                for v in self.views:
                    if v is not lead and cams[id(v)] != cams[id(lead)]:
                        self._copy_cam(lead, v)
                cams = {id(v): self._cam(v) for v in self.views}
            self.last = cams
        except Exception as _fw_err:
            _fw_log("simplotview.py:sync", _fw_err)
        for host, lg, title in self.overlays:
            try:
                self._place(host, lg, title)
            except RuntimeError:
                pass
        try:
            self._place_exit()
        except RuntimeError:
            pass

    def exit(self):
        """Exit Compare: the one view back as it was, the model shown again."""
        if STATE.get("compare") is self:
            STATE["compare"] = None
        try:
            if self.timer is not None:
                self.timer.stop()
        except Exception:
            pass
        for view, node in self.nodes:
            try:
                view.getSceneGraph().removeChild(node)
            except Exception as _fw_err:
                _fw_log("simplotview.py:exitnode", _fw_err)
        for _host, lg, title in self.overlays:
            for w in (lg, title):
                try:
                    w.hide()
                    w.deleteLater()
                except RuntimeError:
                    pass
        try:
            if self.exit_btn is not None:
                self.exit_btn.hide()
                self.exit_btn.deleteLater()
        except RuntimeError:
            pass
        for w in self.made:
            try:
                w.close()
            except RuntimeError:
                pass
        QtWidgets.QApplication.processEvents()
        for name in self.hidden:
            o = self.doc.getObject(name)
            if o is not None:
                try:
                    o.ViewObject.Visibility = True
                except Exception as _fw_err:
                    _fw_log("simplotview.py:show", _fw_err)
        if self.mode0 is None:
            return
        try:
            self.mdi.setViewMode(self.mode0)
            for w in self.mdi.subWindowList():
                g = self.geom0.get(id(w))
                if g is not None and self.mode0 == QtWidgets.QMdiArea.SubWindowView:
                    w.setGeometry(g[0])
                    if g[1]:
                        w.showMaximized()
                    elif g[2]:
                        w.showMinimized()
                    else:
                        w.showNormal()
            if self.active0 is not None:
                self.mdi.setActiveSubWindow(self.active0)
        except RuntimeError as _fw_err:
            _fw_log("simplotview.py:mdi", _fw_err)


class ComparePM:
    """Compare Results: All studies with this mesh (the shown plot's kind in every study) or Define (up to 4
    results picked from every study's plots). OK splits the graphics area."""

    def __init__(self, a, name=None):
        sp = _sp()
        self.a = a
        self.all = comparable(a.Document)
        opts = _box("Options", "Compare Results")
        ov = QtWidgets.QVBoxLayout(opts)
        self.same = QtWidgets.QRadioButton("All studies with this mesh")
        self.same.setObjectName("SWSimCompareAll")
        self.define = QtWidgets.QRadioButton("Define")
        self.define.setObjectName("SWSimCompareDefine")
        ov.addWidget(self.same)
        ov.addWidget(self.define)
        pick = _box("Results")
        pv = QtWidgets.QVBoxLayout(pick)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWSimCompareList")
        for st, pn in self.all:
            it = QtWidgets.QListWidgetItem("%s: %s" % (st.Label, pn))
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Unchecked)
            self.list.addItem(it)
        self.list.itemChanged.connect(self._limit)
        pv.addWidget(self.list)
        self.note = QtWidgets.QLabel("Up to 4 results.")
        pv.addWidget(self.note)
        self.form = [opts, pick]
        shown = sp.SHOWN.get("name") if sp.SHOWN.get("a") is a else None
        self.name = name or shown or (sp.plots(a)[0]["name"] if sp.plots(a) else None)
        self.same.toggled.connect(self._mode)
        self.same.setChecked(True)
        self._mode()

    def _quantity(self, st, pn):
        p = _sp().get_plot(st, pn)
        return (p["quantity"], p["comp"]) if p else None

    def _mode(self, *_a):
        """All studies with this mesh: the shown plot's kind (quantity and component) in each study, ticked for you."""
        if not self.same.isChecked():
            self.list.setEnabled(True)
            return
        want = self._quantity(self.a, self.name) if self.name else None
        taken = set()
        self.list.blockSignals(True)
        n = 0
        for i, (st, pn) in enumerate(self.all):
            on = want is not None and self._quantity(st, pn) == want and id(st) not in taken and n < MAX_COMPARE
            if on:
                taken.add(id(st))
                n += 1
            self.list.item(i).setCheckState(QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)
        self.list.blockSignals(False)
        self.list.setEnabled(False)

    def _limit(self, item):
        if item.checkState() == QtCore.Qt.Checked and len(self.picked()) > MAX_COMPARE:
            self.list.blockSignals(True)
            item.setCheckState(QtCore.Qt.Unchecked)
            self.list.blockSignals(False)

    def picked(self):
        return [self.all[i] for i in range(self.list.count()) if self.list.item(i).checkState() == QtCore.Qt.Checked]

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        items = self.picked()
        Gui.Control.closeDialog()
        if items:
            QtCore.QTimer.singleShot(0, lambda: _start_compare(items))
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


def _start_compare(items):
    try:
        return Comparison(items)
    except Exception as error:
        import traceback
        App.Console.PrintError("FreeCAD: Compare Results: %s\n%s" % (error, traceback.format_exc()))
        return None


def compare(a, name=None):
    """Compare Results (the Simulation thread's Results folder, shown plot and tab entries call this)."""
    install()
    old = STATE.get("compare")
    if old is not None:
        old.exit()
    return _open(ComparePM(a, name))


# =========================================================================== show / clear
_installed = []


def install():
    """show() and clear() first take the animation and clipping off (another plot, Hide, the report's walk)."""
    if _installed or Gui is None:
        return
    sp = _sp()
    show0, clear0 = sp.show, sp.clear

    def show(a, name):
        teardown()
        cmp = STATE.get("compare")
        if cmp is not None:
            cmp.exit()
        return show0(a, name)

    def clear():
        teardown()
        return clear0()
    show.__doc__, clear.__doc__ = show0.__doc__, clear0.__doc__
    sp.show, sp.clear = show, clear
    _installed.append((show0, clear0))
