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
import FreeCADGui as Gui
import Part

from . import naming

COMMAND = "SWStyle_SMLoftedBend"
TITLE = "Lofted Bends"
LABEL = "Lofted-Bend"
GROUP = "Lofted Bend"
ICON = "SheetMetal_AddBaseShape"
V = App.Vector
MESSAGE = "Select two open sketches for the profiles."
FACETING = ["Chord Tolerance", "Number of Bends", "Segment Length", "Segment Angle"]
FORMED_ANGLE = 3.0


# ================================================================ geometry
def profile_wire(sketch_shape):
    """The open wire of a profile sketch, else None."""
    wires = sketch_shape.Wires
    if len(wires) != 1 or wires[0].isClosed():
        return None
    return wires[0]


def _breaks(edge, kind, value, from_end):
    """Distances along one edge where the profile is cut into facets (its ends included)."""
    length = edge.Length
    if edge.Curve.TypeId == "Part::GeomLine":
        return [0.0, length]
    if kind == "Chord Tolerance":
        if value <= 0:
            raise ValueError("The chord tolerance must be more than 0.")
        a = edge.FirstParameter
        ds = [abs(edge.Curve.length(a, edge.Curve.parameter(p))) for p in edge.discretize(Deflection=value)]
        ds[0], ds[-1] = 0.0, length
        return sorted(ds)
    if kind == "Number of Bends":
        n = max(1, int(round(value))) + 1
    elif kind == "Segment Length":
        if value <= 0:
            raise ValueError("The segment length must be more than 0.")
        if from_end:
            ds = [k * value for k in range(int(length // value + 1e-9) + 1)]
            if length - ds[-1] > 1e-6:
                ds.append(length)
            return ds
        n = max(1, int(math.ceil(length / value - 1e-9)))
    else:
        if value <= 0:
            raise ValueError("The segment angle must be more than 0.")
        n = max(1, int(math.ceil(math.degrees(_turn(edge)) / value - 1e-9)))
    return [length * k / n for k in range(n + 1)]


def _turn(edge):
    """How far the edge's direction turns from end to end (radians)."""
    if hasattr(edge.Curve, "Radius"):
        return abs(edge.LastParameter - edge.FirstParameter)
    pts = edge.discretize(64)
    total = 0.0
    for p, q, r in zip(pts, pts[1:], pts[2:]):
        u, w = q - p, r - q
        if u.Length > 1e-12 and w.Length > 1e-12:
            total += math.acos(max(-1.0, min(1.0, u.normalize().dot(w.normalize()))))
    return total


def _runs(wire):
    """The wire's edges in order, each with whether it runs forwards."""
    out = []
    end = wire.OrderedVertexes[0].Point
    for e in wire.OrderedEdges:
        a = e.valueAt(e.FirstParameter)
        forward = (a - end).Length < 1e-6
        out.append((e, forward))
        end = e.valueAt(e.LastParameter if forward else e.FirstParameter)
    return out


def polyline(wire, kind, value, from_end):
    """The points where a profile is cut into facets, with their share of its length (0..1)."""
    pts, shares = [], []
    total = wire.Length
    done = 0.0
    for e, forward in _runs(wire):
        length = e.Length
        for d in _breaks(e, kind, value, from_end):
            along = d if forward else length - d
            p = e.valueAt(e.getParameterByLength(d))
            if not forward:
                continue
            if pts and (p - pts[-1]).Length < 1e-7:
                continue
            pts.append(p)
            shares.append((done + along) / total)
        if not forward:
            for d in reversed(_breaks(e, kind, value, from_end)):
                p = e.valueAt(e.getParameterByLength(d))
                if pts and (p - pts[-1]).Length < 1e-7:
                    continue
                pts.append(p)
                shares.append((done + length - d) / total)
        done += length
    shares[0], shares[-1] = 0.0, 1.0
    return pts, shares


def _same_way(p, q):
    """Whether two point rows run the same way (their starts nearer each other than crossed)."""
    return (p[0] - q[0]).Length + (p[-1] - q[-1]).Length <= (p[0] - q[-1]).Length + (p[-1] - q[0]).Length


def _flip(q, sq):
    return list(reversed(q)), [1.0 - s for s in reversed(sq)]


def triangles(p, sp, q, sq):
    """Zip two point rows into triangles by their share of length: [(a, b, c)], and the rulings between."""
    tris = []
    i = j = 0
    rulings = [(p[0], q[0])]
    while i < len(p) - 1 or j < len(q) - 1:
        step_p = j >= len(q) - 1 or (i < len(p) - 1 and sp[i + 1] <= sq[j + 1])
        if step_p:
            tris.append((p[i], p[i + 1], q[j]))
            i += 1
        else:
            tris.append((p[i], q[j + 1], q[j]))
            j += 1
        rulings.append((p[i], q[j]))
    return tris, rulings


def _plane_offset(p, normals, t):
    """The point t off every facet plane through p (as near as can be when more than three)."""
    ns = []
    for n in normals:
        if all(abs(n.dot(m)) < 1 - 1e-9 for m in ns):
            ns.append(n)
    if len(ns) == 1:
        return p + ns[0] * t
    # least squares: n_i . x = t for every plane, x the offset; keep x in the planes' span
    a = [[sum(n[r] * n[c] for n in ns) for c in range(3)] for r in range(3)]
    b = [sum(n[r] * t for n in ns) for r in range(3)]
    if len(ns) == 2:
        # two planes: the offset is in their span, x = u n0 + w n1
        d = ns[0].dot(ns[1])
        u = w = t / (1 + d)
        return p + ns[0] * u + ns[1] * w
    m = App.Matrix(a[0][0], a[0][1], a[0][2], 0, a[1][0], a[1][1], a[1][2], 0, a[2][0], a[2][1], a[2][2], 0)
    try:
        x = m.inverse().multVec(V(*b))
    except Exception:
        avg = sum(ns, V()).normalize()
        x = avg * t
    return p + x


def faceted_solid(tris, thickness, reverse, symmetric):
    """A sheet of flat facets thickened: every facet moved its thickness off along its normal."""
    def key(p):
        return (round(p.x, 6), round(p.y, 6), round(p.z, 6))
    normals = {}
    good = []
    for t in tris:
        n = (t[1] - t[0]).cross(t[2] - t[0])
        if n.Length < 1e-9:
            continue
        n.normalize()
        good.append(t)
        for x in t:
            normals.setdefault(key(x), []).append(n)
    sign = -1.0 if reverse else 1.0
    lo, hi = (-thickness / 2, thickness / 2) if symmetric else (0.0, thickness)
    pts = {}
    for t in good:
        for x in t:
            k = key(x)
            if k not in pts:
                pts[k] = (_plane_offset(x, normals[k], sign * lo) if lo else x,
                          _plane_offset(x, normals[k], sign * hi))
    faces = []
    for a, b, c in good:
        ka, kb, kc = key(a), key(b), key(c)
        faces.append(Part.Face(Part.makePolygon([pts[ka][0], pts[kb][0], pts[kc][0], pts[ka][0]])))
        faces.append(Part.Face(Part.makePolygon([pts[ka][1], pts[kc][1], pts[kb][1], pts[ka][1]])))
    # the sides: along every edge used by one triangle only
    count = {}
    for a, b, c in good:
        for u, w in ((a, b), (b, c), (c, a)):
            e = tuple(sorted((key(u), key(w))))
            count[e] = count.get(e, 0) + 1
    for e, n in count.items():
        if n != 1:
            continue
        (u0, u1), (w0, w1) = pts[e[0]], pts[e[1]]
        for tri in ((u0, w0, w1), (u0, w1, u1)):
            if (tri[1] - tri[0]).cross(tri[2] - tri[0]).Length > 1e-12:
                faces.append(Part.Face(Part.makePolygon(list(tri) + [tri[0]])))
    sh = Part.makeShell(faces)
    sh.sewShape()
    solid = Part.makeSolid(sh)
    if solid.Volume < 0:
        solid.reverse()
    return solid.removeSplitter()


def lofted(w1, w2, method, kind, value, from_end, thickness, reverse, symmetric):
    """The solid, the triangles of the sheet (for the flat pattern), its two point rows and its bend lines."""
    if method == "Formed":
        # one smooth sheet: cut finely enough (every 3 degrees) that its facets cannot be told apart
        kind, value, from_end = "Segment Angle", FORMED_ANGLE, False
    p, sp = polyline(w1, kind, value, from_end)
    q, sq = polyline(w2, kind, value, from_end)
    if not _same_way(p, q):
        q, sq = _flip(q, sq)
    tris, rulings = triangles(p, sp, q, sq)
    bends = [] if method == "Formed" else [r for r in rulings[1:-1] if _is_bend(r, tris)]
    solid = faceted_solid(tris, thickness, reverse, symmetric)
    if solid.isNull() or not solid.Solids:
        raise ValueError("The lofted bend cannot be thickened: try another faceting or a thinner sheet.")
    return solid.Solids[0], tris, (p, q), bends



def _is_bend(ruling, tris):
    """A ruling is a bend line when the facets either side of it are not in one plane."""
    a, b = ruling
    near = [t for t in tris if sum(1 for x in t if (x - a).Length < 1e-7 or (x - b).Length < 1e-7) == 2]
    if len(near) != 2:
        return False
    n = [(t[1] - t[0]).cross(t[2] - t[0]).normalize() for t in near]
    return abs(abs(n[0].dot(n[1])) - 1) > 1e-6


# ---------------------------------------------------------------- flat pattern
def _place(a2, b2, la, lb, side):
    """The point at la from a2 and lb from b2 (2D, as vectors in z = 0), on the given side of a2-b2."""
    d = (b2 - a2).Length
    x = (la * la - lb * lb + d * d) / (2 * d)
    y = math.sqrt(max(0.0, la * la - x * x))
    ex = (b2 - a2).normalize()
    ey = V(-ex.y, ex.x, 0)
    return a2 + ex * x + ey * (y * side)


def develop(tris):
    """Lay the triangle strip flat, each triangle keeping its side lengths. Returns {3D point key: 2D point}."""
    flat = {}

    def key(p):
        return (round(p.x, 6), round(p.y, 6), round(p.z, 6))

    a, b, c = tris[0]
    flat[key(a)] = V(0, 0, 0)
    flat[key(b)] = V((b - a).Length, 0, 0)
    flat[key(c)] = _place(flat[key(a)], flat[key(b)], (c - a).Length, (c - b).Length, 1)
    prev = tris[0]
    for t in tris[1:]:
        known = [x for x in t if key(x) in flat]
        new = [x for x in t if key(x) not in flat]
        if len(known) == 3:
            prev = t
            continue
        if len(known) != 2 or len(new) != 1:
            raise ValueError("The lofted bend cannot be developed flat.")
        u, w = known
        n = new[0]
        # the new point goes on the other side of the shared edge from the triangle before
        old = next(x for x in prev if key(x) not in (key(u), key(w)))
        fu, fw, fo = flat[key(u)], flat[key(w)], flat[key(old)]
        side_old = (fw - fu).cross(fo - fu).z
        flat[key(n)] = _place(fu, fw, (n - u).Length, (n - w).Length, -1 if side_old > 0 else 1)
        prev = t
    return flat, key


def flat_pattern(tris, bends, thickness, reverse, symmetric):
    """The flat sheet and its bend lines, laid in the plane of the first facet, which stays where it is."""
    flat, key = develop(tris)
    a, b, c = tris[0]
    a2, b2, c2 = flat[key(a)], flat[key(b)], flat[key(c)]
    # 2D frame -> the first facet's 3D frame
    x3 = (b - a).normalize()
    n3 = (b - a).cross(c - a).normalize()
    y3 = n3.cross(x3)
    x2 = (b2 - a2).normalize()
    y2 = V(-x2.y, x2.x, 0)
    if (c2 - a2).dot(y2) < 0:
        y2 = -y2

    def to3(p2):
        d = p2 - a2
        return a + x3 * d.dot(x2) + y3 * d.dot(y2)

    edges = {}
    for t in tris:
        for u, w in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            e = tuple(sorted((key(u), key(w))))
            edges[e] = edges.get(e, 0) + 1
    outline = [Part.makeLine(to3(flat[e[0]]), to3(flat[e[1]])) for e, n in edges.items() if n == 1]
    wire = Part.Wire(Part.__sortEdges__(outline))
    face = Part.Face(wire)
    sign = -1.0 if reverse else 1.0
    lo, hi = (-thickness / 2, thickness / 2) if symmetric else (0.0, thickness)
    face.translate(n3 * (sign * lo))
    solid = face.extrude(n3 * (sign * (hi - lo)))
    lines = [Part.makeLine(to3(flat[key(u)]), to3(flat[key(w)])) for u, w in bends]
    return solid, lines, face


# ================================================================ feature
_LAST = None        # the open Lofted Bends PropertyManager


def _defaults():
    from .smbaseflange import _params
    p = _params()
    return p.GetFloat("Thickness", 2.0), p.GetFloat("Radius", 1.0), p.GetFloat("KFactor", 0.5)


class SWLoftedBend:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyLinkList", "Profiles", GROUP, "The two open profile sketches")
        add("App::PropertyEnumeration", "Method", GROUP, "Manufacturing method")
        obj.Method = ["Bent", "Formed"]
        add("App::PropertyEnumeration", "Faceting", GROUP, "Faceting option (Bent)")
        obj.Faceting = FACETING
        add("App::PropertyFloat", "FacetValue", GROUP, "Chord tolerance, number of bends, segment length or angle")
        add("App::PropertyBool", "ReferToEndpoint", GROUP, "Measure segments from the profile's end")
        add("App::PropertyBool", "OverrideParameters", GROUP, "Override default sheet metal parameters")
        add("App::PropertyLength", "Thickness", GROUP, "Sheet thickness")
        add("App::PropertyLength", "Radius", GROUP, "Bend radius")
        add("App::PropertyBool", "Reverse", GROUP, "Thicken the other way")
        add("App::PropertyBool", "Symmetric", GROUP, "Thicken half each way")
        add("App::PropertyBool", "OverrideAllowance", GROUP, "Override default bend allowance")
        add("App::PropertyFloat", "SWKFactor", GROUP, "K-Factor")
        t, r, k = _defaults()
        obj.FacetValue = 0.5
        obj.ReferToEndpoint = True
        obj.Thickness, obj.Radius, obj.SWKFactor = t, r, k
        obj.Proxy = self

    def build(self, obj):
        if len(obj.Profiles) != 2:
            raise ValueError(MESSAGE)
        from .smnormalcut import baked
        wires = []
        for sk in obj.Profiles:
            w = profile_wire(baked(sk.Shape))
            if w is None:
                raise ValueError("A profile must be one open sketch outline.")
            wires.append(w)
        if not obj.OverrideParameters:
            t, r, _k = _defaults()
            obj.Thickness, obj.Radius = t, r
        if not obj.OverrideAllowance:
            obj.SWKFactor = _defaults()[2]
        return lofted(wires[0], wires[1], obj.Method, obj.Faceting, float(obj.FacetValue), bool(obj.ReferToEndpoint),
                      float(obj.Thickness), bool(obj.Reverse), bool(obj.Symmetric))

    def execute(self, obj):
        solid, _tris, _rows, _bends = self.build(obj)
        obj.Shape = solid
        # a formed sheet is one smooth surface: its fine facets' edges are not shown
        try:
            mode = "Shaded" if obj.Method == "Formed" else "Flat Lines"
            if obj.ViewObject is not None and obj.ViewObject.DisplayMode != mode:
                obj.ViewObject.DisplayMode = mode
        except Exception as _fw_err:
            _fw_log("smloftedbend.py:402", _fw_err)

    def flat(self, obj):
        """(flat solid, bend lines, the flat face) of the lofted bend."""
        _solid, tris, _rows, bends = self.build(obj)
        return flat_pattern(tris, bends, float(obj.Thickness), bool(obj.Reverse), bool(obj.Symmetric))

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_lofted_bend(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWLoftedBend"


class ViewProviderLoftedBend:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        from .smunfold import _icon
        return _icon(ICON)

    def claimChildren(self):
        return list(getattr(self.Object, "Profiles", []))

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        obj.Document.openTransaction("Edit " + obj.Label)
        try:
            Gui.Control.showDialog(Panel(obj, False))
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


def make(body):
    doc = body.Document
    obj = doc.addObject("PartDesign::FeaturePython", "LoftedBend")
    SWLoftedBend(obj)
    if App.GuiUp:
        ViewProviderLoftedBend(obj.ViewObject)
    body.addObject(obj)
    obj.Label = naming.next_label(doc, LABEL)
    return obj


# ================================================================ PropertyManager
def _close_transaction(abort):
    try:
        App.closeActiveTransaction(abort)
    except Exception as _fw_err:
        _fw_log("smloftedbend.py:472", _fw_err)


class Panel:
    """The Lofted Bends PropertyManager."""

    def __init__(self, obj, new):
        from PySide import QtWidgets
        from .smbaseflange import _box, _spin
        from .smedgeflange import error_label
        from .smunfold import _DeleteKey, _list
        global _LAST
        _LAST = self
        self.obj = obj
        self.new = new
        self.pick_error = ""
        self.busy = True

        method = _box("Manufacturing Method")
        f = method.layout()
        self.error = error_label()
        f.addRow(self.error)
        self.bent = QtWidgets.QRadioButton("Bent")
        self.bent.setObjectName("SWSMLoftBent")
        self.formed = QtWidgets.QRadioButton("Formed")
        self.formed.setObjectName("SWSMLoftFormed")
        f.addRow(self.bent)
        f.addRow(self.formed)

        prof = _box("Profiles")
        f = prof.layout()
        self.profiles = _list("SWSMLoftProfiles", "#d6ecff", "The two open profile sketches", rows=3)
        f.addRow(self.profiles)
        row = QtWidgets.QHBoxLayout()
        self.up = QtWidgets.QToolButton()
        self.up.setObjectName("SWSMLoftUp")
        self.up.setText("↑")
        self.up.setToolTip("Move up")
        self.down = QtWidgets.QToolButton()
        self.down.setObjectName("SWSMLoftDown")
        self.down.setText("↓")
        self.down.setToolTip("Move down")
        row.addWidget(self.up)
        row.addWidget(self.down)
        row.addStretch(1)
        f.addRow(row)

        fac = _box("Faceting Options")
        f = fac.layout()
        self.facet_buttons = {}
        for name in FACETING:
            b = QtWidgets.QRadioButton(name)
            b.setObjectName("SWSMLoft" + name.replace(" ", ""))
            f.addRow(b)
            self.facet_buttons[name] = b
        val = _box("Facet Value")
        f = val.layout()
        self.value = _spin("SWSMLoftFacetValue", float(obj.FacetValue), 0.0, 100000.0, decimals=3, step=0.1)
        self.value.setToolTip("Facet value")
        f.addRow(self.value)
        self.refer = QtWidgets.QCheckBox("Refer to endpoint")
        self.refer.setObjectName("SWSMLoftReferEnd")
        f.addRow(self.refer)

        smp = _box("Sheet Metal Parameters")
        f = smp.layout()
        self.override = QtWidgets.QCheckBox("Override default parameters")
        self.override.setObjectName("SWSMLoftOverride")
        f.addRow(self.override)
        self.thick = _spin("SWSMLoftThickness", float(obj.Thickness), 0.001, 1000.0, step=0.1)
        self.thick.setToolTip("Thickness")
        f.addRow("T:", self.thick)
        self.reverse = QtWidgets.QCheckBox("Reverse direction")
        self.reverse.setObjectName("SWSMLoftReverse")
        f.addRow(self.reverse)
        self.symmetric = QtWidgets.QCheckBox("Symmetric")
        self.symmetric.setObjectName("SWSMLoftSymmetric")
        f.addRow(self.symmetric)
        self.radius = _spin("SWSMLoftRadius", float(obj.Radius), 0.0, 1000.0, step=0.1)
        self.radius.setToolTip("Bend radius")
        f.addRow("R:", self.radius)

        ba = _box("Bend Allowance")
        f = ba.layout()
        self.allowance = QtWidgets.QCheckBox("Override default parameters")
        self.allowance.setObjectName("SWSMLoftAllowanceOverride")
        f.addRow(self.allowance)
        self.kfactor = _spin("SWSMLoftKFactor", float(obj.SWKFactor), 0.0, 1.0, suffix="", decimals=4, step=0.05)
        # The page reloads on each change: take a typed value once it is finished (Enter, Tab).
        for spin in (self.value, self.thick, self.radius, self.kfactor):
            spin.setKeyboardTracking(False)
        self.kfactor.setToolTip("K-Factor")
        f.addRow("K:", self.kfactor)

        method.setProperty("swstyle_pm_title", TITLE)
        method.setProperty("swstyle_pm_icon", ICON)
        self.form = [method, prof, fac, val, smp, ba]
        self.keys = _DeleteKey(self)
        self.profiles.installEventFilter(self.keys)
        self._load()
        for b in [self.bent, self.formed, self.refer, self.override, self.reverse, self.symmetric, self.allowance] \
                + list(self.facet_buttons.values()):
            b.toggled.connect(self._changed)
        for sp in (self.value, self.thick, self.radius, self.kfactor):
            sp.valueChanged.connect(self._changed)
        self.up.clicked.connect(lambda: self._move(-1))
        self.down.clicked.connect(lambda: self._move(1))
        self.busy = False
        self._fill()
        self._report()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def _load(self):
        o = self.obj
        (self.bent if o.Method == "Bent" else self.formed).setChecked(True)
        self.facet_buttons[o.Faceting].setChecked(True)
        self.refer.setChecked(bool(o.ReferToEndpoint))
        self.override.setChecked(bool(o.OverrideParameters))
        self.reverse.setChecked(bool(o.Reverse))
        self.symmetric.setChecked(bool(o.Symmetric))
        self.allowance.setChecked(bool(o.OverrideAllowance))

    def set_active(self, w):
        pass

    def _fill(self):
        o = self.obj
        self.busy = True
        self.profiles.clear()
        for sk in o.Profiles:
            self.profiles.addItem(sk.Label)
        bent = o.Method == "Bent"
        for b in self.facet_buttons.values():
            b.setEnabled(bent)
        self.value.setEnabled(bent)
        self.refer.setEnabled(bent and o.Faceting == "Segment Length")
        suffix = {"Chord Tolerance": " mm", "Number of Bends": "", "Segment Length": " mm",
                  "Segment Angle": " deg"}[o.Faceting]
        self.value.setSuffix(suffix)
        self.value.setDecimals(0 if o.Faceting == "Number of Bends" else 3)
        self.value.setValue(float(o.FacetValue))
        self.thick.setEnabled(bool(o.OverrideParameters))
        self.radius.setEnabled(bool(o.OverrideParameters))
        self.thick.setValue(float(o.Thickness))
        self.radius.setValue(float(o.Radius))
        self.kfactor.setEnabled(bool(o.OverrideAllowance))
        self.kfactor.setValue(float(o.SWKFactor))
        self.busy = False

    def remove_current(self, w):
        row = w.currentRow()
        if row < 0:
            return
        profiles = list(self.obj.Profiles)
        sk = profiles.pop(row)
        self.obj.Profiles = profiles
        try:
            sk.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("smloftedbend.py:632", _fw_err)
        self._apply()

    def _move(self, step):
        row = self.profiles.currentRow()
        profiles = list(self.obj.Profiles)
        if row < 0 or not 0 <= row + step < len(profiles):
            return
        profiles[row], profiles[row + step] = profiles[row + step], profiles[row]
        self.obj.Profiles = profiles
        self._apply()
        self.profiles.setCurrentRow(row + step)

    # ---------------------------------------------------------------- picks
    def addSelection(self, doc, name, sub, point):
        from PySide import QtCore
        QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name))

    def _picked(self, doc_name, name):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smloftedbend.py:654", _fw_err)
        sk = App.getDocument(doc_name).getObject(name)
        if sk is None or sk.TypeId != "Sketcher::SketchObject":
            return
        if profile_wire(sk.Shape) is None:
            self.pick_error = "A profile must be one open sketch outline."
            self._report()
            return
        self.pick_error = ""
        profiles = [p for p in self.obj.Profiles if p is not sk]
        if len(profiles) >= 2:
            profiles = profiles[:1]
        self.obj.Profiles = profiles + [sk]
        self._apply()

    # ---------------------------------------------------------------- result
    def _changed(self, *_a):
        if self.busy:
            return
        o = self.obj
        old = o.Faceting
        o.Method = "Bent" if self.bent.isChecked() else "Formed"
        o.Faceting = next(n for n, b in self.facet_buttons.items() if b.isChecked())
        if o.Faceting != old:
            o.FacetValue = {"Chord Tolerance": 0.5, "Number of Bends": 4, "Segment Length": 10.0,
                            "Segment Angle": 15.0}[o.Faceting]
        else:
            o.FacetValue = self.value.value()
        o.ReferToEndpoint = self.refer.isChecked()
        o.OverrideParameters = self.override.isChecked()
        if o.OverrideParameters:
            o.Thickness, o.Radius = self.thick.value(), self.radius.value()
        o.Reverse, o.Symmetric = self.reverse.isChecked(), self.symmetric.isChecked()
        o.OverrideAllowance = self.allowance.isChecked()
        if o.OverrideAllowance:
            o.SWKFactor = self.kfactor.value()
        self._apply()

    def _apply(self):
        from PySide import QtCore
        doc = self.obj.Document
        if doc.Recomputing:
            QtCore.QTimer.singleShot(50, self._apply)
            return
        self.obj.touch()
        doc.recompute()
        self._fill()
        self._report()

    def _report(self):
        if self.pick_error:
            text = self.pick_error
        elif len(self.obj.Profiles) != 2:
            text = MESSAGE
        elif "Invalid" in self.obj.State:
            text = self.obj.getStatusString()
        else:
            text = ""
        self.error.setText(text)
        self.error.setVisible(bool(text))
        return not text

    def getStandardButtons(self):
        from PySide import QtWidgets
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smloftedbend.py:724", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smloftedbend.py:730", _fw_err)

    def accept(self):
        self.pick_error = ""
        if not self._report():
            return False
        from . import smflatten
        body = next((p for p in self.obj.InList if p.TypeId == "PartDesign::Body"), None)
        for sk in self.obj.Profiles:
            try:
                sk.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("smloftedbend.py:742", _fw_err)
        if body is not None:
            smflatten.ensure(body)
        self.obj.Document.commitTransaction()
        _close_transaction(False)
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        doc.abortTransaction()
        _close_transaction(True)
        doc.recompute()
        self._close()
        return True


# ================================================================ command
def _empty_body():
    """The active body when it has no solid yet (a lofted bend starts a sheet metal part)."""
    if App.ActiveDocument is None:
        return None
    try:
        if Gui.Control.activeDialog():
            return None
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
    except Exception as _fw_err:
        _fw_log("smloftedbend.py:777", _fw_err)
        return None
    if body is None:
        return None
    if any(o.isDerivedFrom("PartDesign::Feature") for o in body.Group):
        return None
    return body


def start():
    body = _empty_body()
    if body is None:
        return
    doc = body.Document
    sketches = [o.Object for o in Gui.Selection.getSelectionEx() if o.Object.TypeId == "Sketcher::SketchObject"]
    doc.openTransaction(TITLE)
    try:
        obj = make(body)
        panel = Panel(obj, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    for sk in sketches[:2]:
        panel._picked(doc.Name, sk.Name)


class Command:
    def GetResources(self):
        from .smunfold import _icon
        return {"Pixmap": _icon(ICON), "MenuText": "Lofted-Bend",
                "ToolTip": "Makes a sheet metal transition between two open profiles."}

    def IsActive(self):
        return _empty_body() is not None

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
