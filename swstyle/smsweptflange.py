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

COMMAND = "SWStyle_SMSweptFlange"
TITLE = "Swept Flange"
LABEL = "Swept-Flange"
GROUP = "Swept Flange"
ICON = "SheetMetal_AddWall"
V = App.Vector
MESSAGE = ("1. Select an open sketch for the profile\n\n2. Select a sketch or a series of edges of an existing "
           "sheetmetal body as the path.")


# ================================================================ geometry
def _dir_at(e, forward, start):
    """The edge's direction where the chain enters (start) or leaves it, along the chain."""
    u = e.FirstParameter if (start == forward) else e.LastParameter
    t = e.tangentAt(u)
    return t if forward else -t


def _chain(wire):
    """The wire's edges in order: [(edge, runs forwards)]."""
    out = []
    end = wire.OrderedVertexes[0].Point
    for e in wire.OrderedEdges:
        forward = (e.valueAt(e.FirstParameter) - end).Length < 1e-6
        out.append((e, forward))
        end = e.valueAt(e.LastParameter if forward else e.FirstParameter)
    return out


def _plane_normal(wire):
    """The normal of a flat open wire."""
    pts = wire.discretize(64)
    best = V()
    for i in range(1, len(pts) - 1):
        n = (pts[i] - pts[0]).cross(pts[-1] - pts[0])
        if n.Length > best.Length:
            best = n
    if best.Length < 1e-9:
        # a straight profile: any normal will do; the caller gives the sweep direction
        return None
    return best.normalize()


def _points(wire):
    """The open polyline-with-arcs as segments: [("line", a, b)] or [("arc", a, mid, b)]."""
    segs = []
    for e, fw in _chain(wire):
        a, b = e.valueAt(e.FirstParameter), e.valueAt(e.LastParameter)
        if not fw:
            a, b = b, a
        if e.Curve.TypeId == "Part::GeomLine":
            segs.append(("line", a, b))
        elif e.Curve.TypeId == "Part::GeomCircle":
            segs.append(("arc", a, e.valueAt((e.FirstParameter + e.LastParameter) / 2), b))
        else:
            raise ValueError("A profile can have lines and arcs only.")
    return segs


def rounded(wire, normal, side, radius, thickness):
    """The profile with its sharp corners rounded: the inside of each bend gets the bend radius."""
    segs = _points(wire)
    # round sharp line-line corners only (arcs in the profile are kept as drawn)
    res = [segs[0]]
    for s in segs[1:]:
        prev = res[-1]
        if prev[0] == "line" and s[0] == "line":
            d0 = (prev[2] - prev[1]).normalize()
            d1 = (s[2] - s[1]).normalize()
            turn = d0.cross(d1).dot(normal)
            if abs(turn) > 1e-9 and d0.dot(d1) < 1 - 1e-9:
                # the material lies on 'side' of the line (+1: left, normal x direction). A corner turning
                # towards the material has the inside of the bend on the far side: the line gets radius + T
                towards = (turn > 0) == (side > 0)
                r = radius + thickness if towards else radius
                angle = math.acos(max(-1.0, min(1.0, d0.dot(d1))))
                cut = r * math.tan(angle / 2)
                if cut > min((prev[2] - prev[1]).Length, (s[2] - s[1]).Length) - 1e-6:
                    raise ValueError("The bend radius is too big for the profile.")
                p0 = prev[2] - d0 * cut
                p1 = s[1] + d1 * cut
                # the arc's middle
                bis = (d1 - d0).normalize()
                centre = prev[2] + bis * (r / math.cos(angle / 2))
                mid = centre + (prev[2] - centre).normalize() * r
                res[-1] = ("line", prev[1], p0)
                res.append(("arc", p0, mid, p1))
                res.append(("line", p1, s[2]))
                continue
        res.append(s)
    return res


def _edge(seg):
    if seg[0] == "line":
        return Part.makeLine(seg[1], seg[2])
    return Part.Arc(seg[1], seg[2], seg[3]).toShape()


def _offset_seg(seg, normal, d):
    """The segment moved d to its left (normal x direction)."""
    if seg[0] == "line":
        n = normal.cross(seg[2] - seg[1]).normalize()
        return ("line", seg[1] + n * d, seg[2] + n * d)
    c = Part.Arc(seg[1], seg[2], seg[3]).toShape().Curve.Center
    out = []
    for p in seg[1:]:
        r = p - c
        # the left of travel: towards the centre when the arc turns left
        turn_left = (seg[3] - seg[1]).cross(seg[2] - seg[1]).dot(normal) < 0
        left = -r.normalize() if turn_left else r.normalize()
        out.append(p + left * d)
    return ("arc", out[0], out[1], out[2])


def section(wire, normal, side, thickness, radius):
    """The closed face of the profile thickened to one side (side +1: left of the profile's run)."""
    segs = rounded(wire, normal, side, radius, thickness)
    inner = [_edge(s) for s in segs]
    outer = [_edge(_offset_seg(s, normal, side * thickness)) for s in segs]
    a0, a1 = inner[0].Vertexes[0].Point, inner[-1].Vertexes[-1].Point
    b0, b1 = outer[0].Vertexes[0].Point, outer[-1].Vertexes[-1].Point
    edges = inner + [Part.makeLine(a1, b1)] + [e.reversed() for e in reversed(outer)] + [Part.makeLine(b0, a0)]
    w = Part.Wire(Part.__sortEdges__(edges))
    return Part.Face(w)


def swept(profile, path, thickness, radius, reverse):
    """The swept flange solid: the profile's thickened section swept along the path."""
    normal = _plane_normal(profile)
    if normal is None:
        # a straight profile: its plane holds the path's start tangent
        e0, fw = _chain(path)[0]
        t = _dir_at(e0, fw, True)
        line = profile.Edges[0]
        normal = (line.Vertexes[-1].Point - line.Vertexes[0].Point).cross(t)
        if normal.Length < 1e-9:
            raise ValueError("The profile must not run along the path.")
        normal.normalize()
    face = section(profile, normal, -1 if reverse else 1, thickness, radius)
    spine = path if isinstance(path, Part.Wire) else Part.Wire(path)
    sweep = Part.BRepOffsetAPI.MakePipeShell(spine)
    sweep.setFrenetMode(True)
    sweep.setTransitionMode(1)
    sweep.add(face.OuterWire, False, False)
    if not sweep.isReady():
        raise ValueError("The profile cannot be swept along the path.")
    sweep.build()
    sweep.makeSolid()
    solid = sweep.shape()
    if not solid.Solids:
        raise ValueError("The profile cannot be swept along the path.")
    s = solid.Solids[0]
    if s.Volume < 0:
        s.reverse()
    return s


def path_wire(edges):
    """One wire from the path's edges, in order."""
    sorted_edges = Part.__sortEdges__(edges)
    w = Part.Wire(sorted_edges)
    if len(w.Edges) != len(edges):
        raise ValueError("The path's edges must join end to end.")
    return w


def _orient_path(path, profile):
    """The path run from the end nearest the profile."""
    start, end = path.OrderedVertexes[0].Point, path.OrderedVertexes[-1].Point
    if path.isClosed():
        return path
    near = min(profile.distToShape(Part.Vertex(start))[0], profile.distToShape(Part.Vertex(end))[0])
    if profile.distToShape(Part.Vertex(end))[0] < profile.distToShape(Part.Vertex(start))[0] - 1e-9 and near < 1e-3:
        return Part.Wire([e.reversed() for e in reversed(path.OrderedEdges)])
    return path


def developed(segs, normal, side, thickness, radius, k):
    """The profile laid flat at the neutral fibre: [(length, is_bend)] in order."""
    out = []
    for seg in segs:
        if seg[0] == "line":
            out.append(((seg[2] - seg[1]).Length, False))
            continue
        arc = Part.Arc(seg[1], seg[2], seg[3]).toShape()
        c, rr = arc.Curve.Center, arc.Curve.Radius
        angle = arc.Length / rr
        turn_left = (seg[3] - seg[1]).cross(seg[2] - seg[1]).dot(normal) < 0
        # the material lies towards the centre: the sketch line is the outside of the bend
        outside = turn_left == (side > 0)
        neutral = rr - thickness + k * thickness if outside else rr + k * thickness
        out.append((angle * max(neutral, 0.0), True))
    return out


def strip(widths, length, thickness):
    """(flat solid, bend lines, flat face) of a strip: across, the developed profile; along, length."""
    total = sum(w for w, _b in widths)
    face = Part.Face(Part.makePolygon([V(0, 0, 0), V(total, 0, 0), V(total, length, 0), V(0, length, 0),
                                       V(0, 0, 0)]))
    solid = face.extrude(V(0, 0, thickness))
    lines, x = [], 0.0
    for w, bend in widths:
        if bend:

            mid = x + w / 2
            lines.append(Part.makeLine(V(mid, 0, thickness), V(mid, length, thickness)))
        x += w
    top = next(f for f in solid.Faces if abs(f.CenterOfMass.z - thickness) < 1e-9)
    return solid, lines, top


def path_length(path, thickness, inside):
    """The path's length, or with inside, the length of the material's inside along a planar path."""
    if not inside or thickness <= 0:
        return path.Length
    try:
        shorter = [path.makeOffset2D(d, 2, False, True, False).Length for d in (thickness, -thickness)]
        return min(shorter)
    except Exception:
        return path.Length


# ================================================================ feature
_LAST = None        # the open Swept Flange PropertyManager


def _defaults():
    from .smbaseflange import _params
    p = _params()
    return p.GetFloat("Thickness", 2.0), p.GetFloat("Radius", 1.0), p.GetFloat("KFactor", 0.5)


def _part_values(base):
    """Thickness, radius and K-Factor of the sheet metal part a flange is added to."""
    from . import smflatten
    body = next((p for p in base.InList if p.TypeId == "PartDesign::Body"), None) if base is not None else None
    root = smflatten.root(body) if body is not None else None
    t, r, k = _defaults()
    if root is not None:
        t = float(getattr(root, "Thickness", t))
        r = float(getattr(root, "Radius", r))
        k = float(getattr(root, "SWKFactor", k))
    return t, r, k


class SWSweptFlange:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyLink", "Profile", GROUP, "The open profile sketch")
        add("App::PropertyLink", "PathSketch", GROUP, "The path, when it is a sketch")
        add("App::PropertyStringList", "PathEdges", GROUP, "The path's edges of the part, as picked")
        add("App::PropertyVectorList", "PathPoints", GROUP, "A point on each path edge")
        add("App::PropertyLength", "Thickness", GROUP, "Sheet thickness")
        add("App::PropertyLength", "Radius", GROUP, "Bend radius")
        add("App::PropertyBool", "Reverse", GROUP, "Thicken to the other side of the profile")
        add("App::PropertyFloat", "SWKFactor", GROUP, "K-Factor")
        add("App::PropertyBool", "FlattenAlongPath", GROUP, "Flatten the flange along its path")
        add("App::PropertyBool", "MaterialInside", GROUP, "Flatten along the material's inside")
        add("App::PropertyBool", "CylindricalBodies", GROUP, "Keep the picked edge fixed when flattening")
        add("App::PropertyVector", "CylindricalPoint", GROUP, "A point on the fixed edge")
        add("App::PropertyEnumeration", "SWAutoRelief", GROUP, "Auto Relief type")
        add("App::PropertyBool", "SWUseReliefRatio", GROUP, "Use relief ratio")
        add("App::PropertyFloat", "SWReliefRatio", GROUP, "Relief ratio")
        add("App::PropertyVector", "FixedNormal", GROUP, "Fixed face normal (flat pattern)")
        add("App::PropertyVector", "FixedPoint", GROUP, "Fixed face point (flat pattern)")
        for name in ("FixedNormal", "FixedPoint"):
            obj.setEditorMode(name, 2)
        from .smbaseflange import RELIEFS, _params
        obj.SWAutoRelief = list(RELIEFS)
        p = _params()
        obj.SWAutoRelief = p.GetString("AutoRelief", "Rectangular")
        obj.SWUseReliefRatio = p.GetBool("UseReliefRatio", True)
        obj.SWReliefRatio = p.GetFloat("ReliefRatio", 0.5)
        t, r, k = _defaults()
        obj.Thickness, obj.Radius, obj.SWKFactor = t, r, k
        obj.Proxy = self

    def path(self, obj, base_shape):
        if obj.PathSketch is not None:
            from .smnormalcut import baked
            wires = baked(obj.PathSketch.Shape).Wires
            if len(wires) != 1:
                raise ValueError("The path sketch must be one outline.")
            return wires[0]
        if not obj.PathPoints:
            raise ValueError(MESSAGE)
        edges = []
        for p in obj.PathPoints:
            v = Part.Vertex(p)
            e = min(base_shape.Edges, key=lambda x: x.distToShape(v)[0], default=None)
            if e is None or e.distToShape(v)[0] > 1e-4:
                raise ValueError("A path edge is no longer there.")
            edges.append(e)
        return path_wire(edges)

    def execute(self, obj):
        from .smnormalcut import baked
        if obj.Profile is None or (obj.PathSketch is None and not obj.PathPoints):
            # still being picked: the PropertyManager's message asks for them, nothing to report
            base = obj.BaseFeature
            if base is not None and not base.Shape.isNull():
                obj.Shape = baked(base.Shape)
            return
        profile = [w for w in baked(obj.Profile.Shape).Wires]
        if len(profile) != 1 or profile[0].isClosed():
            raise ValueError("The profile must be one open sketch outline.")
        profile = profile[0]
        base = obj.BaseFeature
        base_shape = baked(base.Shape) if base is not None and not base.Shape.isNull() else None
        if base_shape is not None:
            t, r, k = _part_values(base)
            obj.Thickness, obj.Radius, obj.SWKFactor = t, r, k
        path = _orient_path(self.path(obj, base_shape), profile)
        solid = swept(profile, path, float(obj.Thickness), float(obj.Radius), bool(obj.Reverse))
        if base_shape is not None:
            out = base_shape.fuse(solid).removeSplitter()
            if len(out.Solids) == 1:
                out = out.Solids[0]
        else:
            out = solid
            flat = self._fixed_face(obj, solid)
            if flat is not None:
                obj.FixedNormal = flat.normalAt(0, 0)
                from .smnormalcut import inside_point
                obj.FixedPoint = inside_point(flat)
        obj.Shape = out

    @staticmethod
    def _fixed_face(obj, solid):
        """The face that stays put when the part is flattened: next to the Cylindrical/Conical Bodies edge
        when one is picked, else the biggest flat face."""
        planar = [f for f in solid.Faces if f.Surface.TypeId == "Part::GeomPlane" and f.Area > 1e-6]
        if obj.CylindricalBodies and obj.CylindricalPoint.Length > 0:
            v = Part.Vertex(obj.CylindricalPoint)
            near = [f for f in planar if f.distToShape(v)[0] < 1e-4]
            if near:
                return max(near, key=lambda f: f.Area)
        return max(planar, key=lambda f: f.Area, default=None)

    def flat(self, obj):
        """(flat solid, bend lines, flat face) with Flatten along path, else None (the part is unfolded
        bend by bend)."""
        if not obj.FlattenAlongPath:
            return None
        from .smnormalcut import baked
        profile = baked(obj.Profile.Shape).Wires[0]
        path = _orient_path(self.path(obj, None if obj.PathSketch is not None else baked(obj.BaseFeature.Shape)),
                            profile)
        normal = _plane_normal(profile)
        if normal is None:
            e0, fw = _chain(path)[0]
            line = profile.Edges[0]
            normal = (line.Vertexes[-1].Point - line.Vertexes[0].Point).cross(_dir_at(e0, fw, True)).normalize()
        side = -1 if obj.Reverse else 1
        t, r, k = float(obj.Thickness), float(obj.Radius), float(obj.SWKFactor)
        widths = developed(rounded(profile, normal, side, r, t), normal, side, t, r, k)
        return strip(widths, path_length(path, t, bool(obj.MaterialInside)), t)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_swept_flange(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWSweptFlange"


class ViewProviderSweptFlange:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        from .smunfold import _icon
        return _icon(ICON)

    def claimChildren(self):
        o = self.Object
        return [x for x in (getattr(o, "Profile", None), getattr(o, "PathSketch", None)) if x is not None]

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
    base = body.Tip if body.Tip is not None and body.Tip.isDerivedFrom("PartDesign::Feature") else None
    obj = doc.addObject("PartDesign::FeaturePython", "SweptFlange")
    SWSweptFlange(obj)
    if App.GuiUp:
        ViewProviderSweptFlange(obj.ViewObject)
    body.addObject(obj)
    obj.Label = naming.next_label(doc, LABEL)
    if base is not None:
        try:
            base.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("smsweptflange.py:461", _fw_err)
    return obj


# ================================================================ PropertyManager
def _close_transaction(abort):
    try:
        App.closeActiveTransaction(abort)
    except Exception as _fw_err:
        _fw_log("smsweptflange.py:470", _fw_err)


class Panel:
    """The Swept Flange PropertyManager."""

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
        self.first = obj.BaseFeature is None
        from .smbaseflange import ALLOWANCES, RELIEFS

        material = _box("Sheet Metal Parameters From Material")
        self.from_material = QtWidgets.QCheckBox("Use material sheet metal parameters")
        self.from_material.setObjectName("SWSMFromMaterial")
        material.layout().addRow(self.from_material)

        pp = _box("Profile and Path")
        f = pp.layout()
        self.error = error_label()
        f.addRow(self.error)
        self.profile = _list("SWSMSweptProfile", "#d6ecff", "Profile: an open sketch")
        f.addRow(self.profile)
        self.path = _list("SWSMSweptPath", "#ffd6ec", "Path: a sketch or edges of the sheet metal part", rows=3)
        f.addRow(self.path)
        self.along = QtWidgets.QCheckBox("Flatten along path")
        self.along.setObjectName("SWSMSweptAlongPath")
        f.addRow(self.along)
        self.inside = QtWidgets.QCheckBox("Material inside")
        self.inside.setObjectName("SWSMSweptMaterialInside")
        f.addRow(self.inside)

        cyl = _box("Cylindrical/Conical Bodies")
        f = cyl.layout()
        self.cyl_on = QtWidgets.QCheckBox("Cylindrical/Conical Bodies")
        self.cyl_on.setObjectName("SWSMSweptCylindrical")
        f.addRow(self.cyl_on)
        self.cyl = _list("SWSMSweptCylEdge", "#e6d6ff", "The edge that stays fixed when the part is flattened")
        f.addRow(self.cyl)

        gauges = _box("Sheet Metal Gauges")
        self.gauge = QtWidgets.QCheckBox("Use gauge table")
        self.gauge.setObjectName("SWSMGauge")
        gauges.layout().addRow(self.gauge)

        smp = _box("Sheet Metal Parameters")
        f = smp.layout()
        self.thick = _spin("SWSMSweptThickness", float(obj.Thickness), 0.001, 1000.0, decimals=3, step=0.1)
        self.thick.setToolTip("Thickness")
        f.addRow("T:", self.thick)
        self.reverse = QtWidgets.QCheckBox("Reverse direction")
        self.reverse.setObjectName("SWSMSweptReverse")
        f.addRow(self.reverse)
        self.radius = _spin("SWSMSweptRadius", float(obj.Radius), 0.0, 1000.0, decimals=3, step=0.1)
        self.radius.setToolTip("Bend radius")
        f.addRow("R:", self.radius)

        ba = _box("Bend Allowance")
        f = ba.layout()
        self.allowance = QtWidgets.QComboBox()
        self.allowance.setObjectName("SWSMAllowance")
        self.allowance.addItems(ALLOWANCES)
        f.addRow(self.allowance)
        self.kfactor = _spin("SWSMSweptKFactor", float(obj.SWKFactor), 0.0, 1.0, suffix="", decimals=4, step=0.05)
        self.kfactor.setToolTip("K-Factor")
        f.addRow("K", self.kfactor)
        from . import smallowance, smgauge
        self.allowance_problem = self.gauge_problem = ""
        self.custom = smallowance.CustomAllowance(self.allowance, self.kfactor, f, obj, self._changed)
        self.gauges = smgauge.GaugeRows(obj, self.from_material, self.gauge, gauges.layout(), smp.layout(),
                                        self.thick, self.radius, self.kfactor, self._changed)

        relief = _box("Auto Relief")
        f = relief.layout()
        self.relief = QtWidgets.QComboBox()
        self.relief.setObjectName("SWSMRelief")
        self.relief.addItems(RELIEFS)
        self.ratio_on = QtWidgets.QCheckBox("Use relief ratio")
        self.ratio_on.setObjectName("SWSMReliefRatioOn")
        self.ratio = _spin("SWSMReliefRatio", float(obj.SWReliefRatio), 0.05, 2.0, suffix="", decimals=2, step=0.05)
        self.ratio.setToolTip("Relief ratio")
        f.addRow(self.relief)
        f.addRow(self.ratio_on)
        f.addRow("Ratio:", self.ratio)

        material.setProperty("swstyle_pm_title", TITLE)
        material.setProperty("swstyle_pm_icon", ICON)
        self.form = [material, pp, cyl, gauges, smp, ba, relief]
        self.active = self.profile
        self.keys = _DeleteKey(self)
        for w in (self.profile, self.path, self.cyl):
            w.installEventFilter(self.keys)
        self.reverse.setChecked(bool(obj.Reverse))
        self.along.setChecked(bool(obj.FlattenAlongPath))
        self.inside.setChecked(bool(obj.MaterialInside))
        self.cyl_on.setChecked(bool(obj.CylindricalBodies))
        self.relief.setCurrentText(obj.SWAutoRelief)
        self.ratio_on.setChecked(bool(obj.SWUseReliefRatio))
        for w in (self.reverse, self.along, self.inside, self.ratio_on):
            w.toggled.connect(self._changed)
        self.cyl_on.toggled.connect(self._cylindrical)
        self.relief.currentIndexChanged.connect(self._changed)
        for sp in (self.thick, self.radius, self.kfactor, self.ratio):
            sp.valueChanged.connect(self._changed)
        self.busy = False
        self._fill()
        self._report()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def set_active(self, w):
        if w in (self.profile, self.path, self.cyl):
            self.active = w

    def _fill(self):
        o = self.obj
        self.busy = True
        self.profile.clear()
        if o.Profile is not None:
            self.profile.addItem(o.Profile.Label)
        self.path.clear()
        if o.PathSketch is not None:
            self.path.addItem(o.PathSketch.Label)
        for name in o.PathEdges:
            self.path.addItem(name)
        self.cyl.clear()
        if o.CylindricalBodies and o.CylindricalPoint.Length > 0:
            self.cyl.addItem("Fixed edge")
        # on a sheet metal part the flange takes the part's thickness, radius, K-Factor and relief
        for w in (self.thick, self.radius, self.kfactor, self.relief, self.ratio_on, self.along, self.cyl_on):
            w.setEnabled(self.first)
        self.inside.setEnabled(self.first and self.along.isChecked())
        self.ratio.setEnabled(self.first and self.ratio_on.isChecked())
        self.cyl.setEnabled(self.first and self.cyl_on.isChecked())
        self.thick.setValue(float(o.Thickness))
        self.radius.setValue(float(o.Radius))
        self.kfactor.setValue(float(o.SWKFactor))
        self.custom.show(self.first)
        self.gauges.show(self.first)
        self.busy = False

    def remove_current(self, w):
        o = self.obj
        if w is self.cyl:
            o.CylindricalPoint = V()
        elif w is self.profile:
            o.Profile = None
        elif w is self.path:
            row = w.currentRow()
            if o.PathSketch is not None:
                o.PathSketch = None
            elif 0 <= row < len(o.PathEdges):
                names, pts = list(o.PathEdges), list(o.PathPoints)
                del names[row], pts[row]
                o.PathEdges, o.PathPoints = names, pts
        self._apply()

    # ---------------------------------------------------------------- picks
    def addSelection(self, doc, name, sub, point):
        from PySide import QtCore
        at = App.Vector(*point) if point else None
        QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub, at))

    def _picked(self, doc_name, name, sub, at):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smsweptflange.py:645", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None:
            return
        o = self.obj
        self.pick_error = ""
        if self.active is self.cyl and sub.startswith("Edge") and picked is o:
            edge = picked.Shape.getElement(sub)
            o.CylindricalPoint = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
            o.CylindricalBodies = True
            self.active = self.profile
        elif picked.TypeId == "Sketcher::SketchObject":
            wires = picked.Shape.Wires
            as_profile = self.active is self.profile or o.Profile is None
            if as_profile and len(wires) == 1 and not wires[0].isClosed() and picked is not o.PathSketch:
                o.Profile = picked
                self.active = self.path
            elif picked is not o.Profile and len(wires) == 1:
                o.PathSketch = picked
                o.PathEdges, o.PathPoints = [], []
            else:
                self.pick_error = "The profile must be one open sketch outline."
                self._report()
                return
            try:
                picked.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("smsweptflange.py:672", _fw_err)
        elif sub.startswith("Edge") and o.BaseFeature is not None:
            from .smnormalcut import baked
            base = baked(o.BaseFeature.Shape)
            edge = picked.Shape.getElement(sub)
            mid = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
            k = min(range(len(base.Edges)), key=lambda i: base.Edges[i].distToShape(Part.Vertex(mid))[0])
            if base.Edges[k].distToShape(Part.Vertex(mid))[0] > 1e-4:
                return
            label = "Edge%d" % (k + 1)
            names, pts = list(o.PathEdges), list(o.PathPoints)
            if label in names:
                i = names.index(label)
                del names[i], pts[i]
            else:
                e = base.Edges[k]
                names.append(label)
                pts.append(e.valueAt((e.FirstParameter + e.LastParameter) / 2))
            o.PathSketch = None
            o.PathEdges, o.PathPoints = names, pts
        else:
            return
        self._apply()

    # ---------------------------------------------------------------- result
    def _cylindrical(self, on):
        if on:
            self.active = self.cyl      # the next edge picked is the fixed edge
        self._changed()

    def _changed(self, *_a):
        if self.busy:
            return
        o = self.obj
        o.Reverse = self.reverse.isChecked()
        if self.first:
            from . import smallowance
            self.gauge_problem = self.gauges.apply()
            o.Thickness, o.Radius = self.thick.value(), self.radius.value()
            self.allowance_problem = ""
            try:
                o.SWKFactor = self.custom.k(self.thick.value(), self.radius.value(), 90.0)
            except ValueError as e:
                self.allowance_problem = str(e)
            self.custom.save(o)
            smallowance.add_props(o)
            o.FlattenAlongPath = self.along.isChecked()
            o.MaterialInside = self.along.isChecked() and self.inside.isChecked()
            o.CylindricalBodies = self.cyl_on.isChecked()
            o.SWAutoRelief = self.relief.currentText()
            o.SWUseReliefRatio = self.ratio_on.isChecked()
            o.SWReliefRatio = self.ratio.value()
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
        o = self.obj
        if self.pick_error:
            text = self.pick_error
        elif self.first and (self.gauge_problem or self.allowance_problem):
            text = self.gauge_problem or self.allowance_problem
        elif o.Profile is None or (o.PathSketch is None and not o.PathEdges):
            text = MESSAGE
        elif "Invalid" in o.State:
            text = o.getStatusString()
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
            _fw_log("smsweptflange.py:761", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smsweptflange.py:767", _fw_err)

    def accept(self):
        self.pick_error = ""
        if not self._report():
            return False
        from . import smflatten
        o = self.obj
        for sk in (o.Profile, o.PathSketch):
            if sk is not None:
                try:
                    sk.ViewObject.Visibility = False
                except Exception as _fw_err:
                    _fw_log("smsweptflange.py:780", _fw_err)
        body = next((p for p in o.InList if p.TypeId == "PartDesign::Body"), None)
        if body is not None and self.first:
            from .smbaseflange import _params
            p = _params()
            p.SetFloat("Thickness", float(o.Thickness))
            p.SetFloat("Radius", float(o.Radius))
            p.SetFloat("KFactor", float(o.SWKFactor))
            p.SetString("AutoRelief", o.SWAutoRelief)
            p.SetBool("UseReliefRatio", bool(o.SWUseReliefRatio))
            p.SetFloat("ReliefRatio", float(o.SWReliefRatio))
            smflatten.ensure(body)      # the part's first sheet metal feature brings Flat-Pattern1
        o.Document.commitTransaction()
        _close_transaction(False)
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        base = self.obj.BaseFeature if self.new else None
        doc.abortTransaction()
        _close_transaction(True)
        doc.recompute()
        if base is not None:
            try:
                base.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("smsweptflange.py:807", _fw_err)
        self._close()
        return True


# ================================================================ command
def _body():
    """The active body: a sheet metal part, or one with no solid yet (the swept flange starts it)."""
    if App.ActiveDocument is None:
        return None
    from . import smflatten
    if smflatten.blocked():
        return None
    try:
        if Gui.Control.activeDialog():
            return None
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
        if body is None:
            from . import smflatten as _sf
            body = _sf._body()
    except Exception as _fw_err:
        _fw_log("smsweptflange.py:836", _fw_err)
        return None
    if body is None:
        return None
    solid = any(o.isDerivedFrom("PartDesign::Feature") for o in body.Group)
    if solid and smflatten.root(body) is None:
        return None
    return body


def start():
    body = _body()
    if body is None:
        return
    doc = body.Document
    picked = [(o.Document.Name, o.Object.Name, sub, App.Vector(p)) for o in Gui.Selection.getSelectionEx()
              for sub, p in (zip(o.SubElementNames, o.PickedPoints) if o.SubElementNames else [("", (0, 0, 0))])]
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
    for doc_name, name, sub, at in picked:
        panel._picked(doc_name, name, sub, at)


class Command:
    def GetResources(self):
        from .smunfold import _icon
        return {"Pixmap": _icon(ICON), "MenuText": "Swept Flange",
                "ToolTip": "Sweeps a flange profile along a path."}

    def IsActive(self):
        return _body() is not None

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
