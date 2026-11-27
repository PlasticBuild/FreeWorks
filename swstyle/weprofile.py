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
import Part

from . import profiledata

V = App.Vector
ANCHOR_X = ("Left", "Center", "Right")
ANCHOR_Y = ("Bottom", "Center", "Top")
TAPER = {"UPN": 8.0, "IPN": 14.0}           # inner flange slope, % (EN 10365)
GROUP = "Profile"


_ICONS = {"profile.svg": "WE_STRUCTURAL_MEMBER", "custom_profile.svg": "WE_STRUCTURAL_MEMBER",
          "metalwb.svg": "WE_WELDMENT", "trim_extend.svg": "WE_TRIM_EXTEND", "bom.svg": "WE_WELDMENT_CUT_LIST",
          "box.svg": "WE_END_CAP", "corner.svg": "WE_GUSSET", "joincurve.svg": "WE_WELD_BEAD"}
# drawings-land273: the drawn 32 px SVG of each command (resources/icons-drawn/FW_<key>.svg), sharp at 200 %
_DRAWN_KEYS = {"profile.svg": "WE_StructuralMember", "custom_profile.svg": "WE_PiercePoint", "metalwb.svg": "WE_Weldment",
               "trim_extend.svg": "WE_TrimExtend", "bom.svg": "WE_CutList", "box.svg": "WE_EndCap",
               "corner.svg": "WE_Gusset", "joincurve.svg": "WE_WeldBead", "link.svg": "WE_DefineConnection",
               "list-add.svg": "WE_PatternConnection"}


# ================================================================ FrameForge, when it is there
def frameforge():
    """FrameForge's ff_tools module, or None (it is optional)."""
    try:
        from freecad.frameforge import ff_tools
        return ff_tools
    except Exception:
        return None


def _size(p):
    try:
        return int(p.stem)
    except ValueError:
        return 0


def icon(name, key=None):
    ""
    # drawings-land273, sharp at 200 %: the icon pack's own at 32 px or more, else the drawn SVG of the command
    # (key, or the one for name), else the pack's small one, else FrameForge's
    small = ""
    try:
        from . import icons
        root = icons.root()
        fam = _ICONS.get(name)
        if root is not None and fam:
            folder = root / "png" / fam
            files = sorted(folder.glob("*.png"), key=lambda p: (_size(p), p.stem)) if folder.is_dir() else []
            big = [p for p in files if _size(p) >= 32]
            if big:
                return str(big[0])
            if files:
                small = str(files[0])
        drawn = icons._DRAWN / ("FW_%s.svg" % (key or _DRAWN_KEYS.get(name, "")))
        if (key or name in _DRAWN_KEYS) and drawn.is_file():
            return str(drawn)
        if small:
            return small
    except Exception as _fw_err:
        _fw_log("weprofile.py:69", _fw_err)
    ff = frameforge()
    if ff is not None:
        return os.path.join(ff.ICONPATH, name)
    return ""


def tables():
    """{material: {family: {"fillet": bool, "sizes": {label: dims}}}}: ours, plus FrameForge's other
    tables when it is installed."""
    out = {k: profiledata.table(k) for k in profiledata.TABLES}
    ff = frameforge()
    if ff is not None:
        import json
        try:
            for f in sorted(os.listdir(ff.PROFILESPATH)):
                key = os.path.splitext(f)[0]
                if f.endswith(".json") and key not in out:
                    with open(os.path.join(ff.PROFILESPATH, f)) as fd:
                        out[key] = json.load(fd)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: FrameForge tables: %s\n" % error)
    return out


def _foreign(material):
    """True when this table comes from FrameForge (its members are FrameForge's)."""
    return material.lower().replace(" ", "_") not in profiledata.TABLES


# ================================================================ sections
def _rounded(points, radii):
    """A closed wire through points with corner i rounded by radii[i] (0: sharp)."""
    n = len(points)
    cuts = []
    for i in range(n):
        p, a, b = points[i], points[i - 1], points[(i + 1) % n]
        r = radii[i] if radii else 0.0
        u1, u2 = a - p, b - p
        if r <= 1e-9 or u1.Length < 1e-9 or u2.Length < 1e-9:
            cuts.append((p, None, p))
            continue
        u1.normalize()
        u2.normalize()
        half = u1.getAngle(u2) / 2.0
        if half < 1e-6:
            cuts.append((p, None, p))
            continue
        d = r / math.tan(half)
        d = min(d, (a - p).Length * 0.49, (b - p).Length * 0.49)
        r = d * math.tan(half)
        bis = u1 + u2
        bis.normalize()
        mid = p + bis * (r / math.sin(half) - r)
        cuts.append((p + u1 * d, mid, p + u2 * d))
    edges = []
    for i in range(n):
        t1, mid, t2 = cuts[i]
        if mid is not None:
            edges.append(Part.Arc(t1, mid, t2).toShape())
        nxt = cuts[(i + 1) % n][0]
        if (nxt - t2).Length > 1e-9:
            edges.append(Part.makeLine(t2, nxt))
    return Part.Wire(edges)


def _poly(xy, radii=None):
    return _rounded([V(x, y, 0) for x, y in xy], radii or [0.0] * len(xy))


def section(family, W, H, T, TF, R1, R2, fillet=True):
    """The section face of a standard family, its corner at the origin (x: 0..W, y: 0..H)."""
    if not fillet:
        R1 = R2 = 0.0
    family = profiledata.ANSI_FAMILIES.get(family, family)
    if family.startswith("T-Slot "):
        return tslot(int(family.split()[1]), W, H)
    if family in ("Equal Leg Angles", "Unequal Leg Angles"):
        pts = [(0, 0), (0, H), (T, H), (T, T), (W, T), (W, 0)]
        return Part.Face(_poly(pts, [0, 0, R2, R1, R2, 0]))
    if family in ("Flat Sections", "Square"):
        return Part.Face(_poly([(0, 0), (0, H), (W, H), (W, 0)]))
    if family in ("Square Hollow", "Rectangular Hollow"):
        outer = Part.Face(_poly([(0, 0), (0, H), (W, H), (W, 0)], [R1] * 4))
        inner = Part.Face(_poly([(T, T), (T, H - T), (W - T, H - T), (W - T, T)], [R2] * 4))
        return outer.cut(inner).Faces[0]
    if family in ("UPN", "UPE"):
        # web along the top (thickness T), flanges hanging down (thickness TF)
        yd = (H - T) / 2.0 * TAPER.get(family, 0.0) / 100.0
        pts = [(0, 0), (0, H), (W, H), (W, 0), (W - TF + yd, 0), (W - TF - yd, H - T), (TF + yd, H - T),
               (TF - yd, 0)]
        return Part.Face(_poly(pts, [0, 0, 0, 0, R2, R1, R1, R2]))
    if family in ("IPE", "IPN", "HEA", "HEB", "HEM"):
        x1, x2 = W / 2.0 - T / 2.0, W / 2.0 + T / 2.0
        yd = (x1 / 2.0) * TAPER.get(family, 0.0) / 100.0
        pts = [(0, 0), (0, TF - yd), (x1, TF + yd), (x1, H - TF - yd), (0, H - TF + yd), (0, H), (W, H),
               (W, H - TF + yd), (x2, H - TF - yd), (x2, TF + yd), (W, TF - yd), (W, 0)]
        toe = R2 if family == "IPN" else 0.0
        return Part.Face(_poly(pts, [0, toe, R1, R1, toe, 0, 0, toe, R1, R1, toe, 0]))
    if family == "Round Bar":
        return Part.Face(Part.Wire([Part.makeCircle(H / 2.0, V(H / 2.0, H / 2.0, 0))]))
    if family == "Pipe":
        c = V(H / 2.0, H / 2.0, 0)
        outer = Part.Face(Part.Wire([Part.makeCircle(H / 2.0, c)]))
        inner = Part.Face(Part.Wire([Part.makeCircle(H / 2.0 - T, c)]))
        return outer.cut(inner).Faces[0]
    raise ValueError("No section for the profile family %s" % family)


def tslot(series, W, H):
    """An aluminium T-slot extrusion of that series (20, 30, 40), W x H: a slot in the middle of every
    outside cell face and a bore in every cell."""
    o, neck, cavity, depth, bore, rc = profiledata.TSLOT_SERIES.get(series, profiledata.TSLOT_SERIES[20])
    nx, ny = max(1, int(round(W / series))), max(1, int(round(H / series)))
    face = Part.Face(_poly([(0, 0), (0, H), (W, H), (W, 0)], [rc] * 4))
    cuts = []

    def slot(cx, cy, ux, uy):
        """A slot opening at (cx, cy) on the outside, going in along (ux, uy)."""
        vx, vy = -uy, ux
        def at(a, b):
            return V(cx + ux * a + vx * b, cy + uy * a + vy * b, 0)
        pts = [at(-0.1, -o / 2), at(neck, -o / 2), at(neck, -cavity / 2), at(depth - 1.5, -cavity / 2),
               at(depth, -o / 2), at(depth, o / 2), at(depth - 1.5, cavity / 2), at(neck, cavity / 2),
               at(neck, o / 2), at(-0.1, o / 2)]
        cuts.append(Part.Face(Part.makePolygon(pts + [pts[0]])))

    for i in range(nx):
        cx = series * (i + 0.5)
        slot(cx, 0, 0, 1)
        slot(cx, H, 0, -1)
    for j in range(ny):
        cy = series * (j + 0.5)
        slot(0, cy, 1, 0)
        slot(W, cy, -1, 0)
    # hollows where two cells meet (inside a wide extrusion, as the real sections are)
    def hollow(cx, cy, along_x):
        a, b = (series * 0.30, series * 0.50) if along_x else (series * 0.50, series * 0.30)
        pts = [V(cx - a / 2, cy - b / 2, 0), V(cx + a / 2, cy - b / 2, 0), V(cx + a / 2, cy + b / 2, 0),
               V(cx - a / 2, cy + b / 2, 0)]
        cuts.append(Part.Face(_rounded(pts, [min(a, b) * 0.2] * 4)))

    for i in range(1, nx):
        for j in range(ny):
            hollow(series * i, series * (j + 0.5), True)
    for i in range(nx):
        for j in range(1, ny):
            hollow(series * (i + 0.5), series * j, False)
    for i in range(nx):
        for j in range(ny):
            cuts.append(Part.Face(Part.Wire([Part.makeCircle(bore / 2.0, V(series * (i + 0.5), series * (j + 0.5), 0))])))
    for c in cuts:
        face = face.cut(c)
    return face.Faces[0] if len(face.Faces) == 1 else face


# ================================================================ the member body
class Profile:
    """A structural member body: the section run along a path edge. Same arguments as FrameForge's."""

    def __init__(self, obj, init_w, init_h, init_mt, init_ft, init_r1, init_r2, init_len, init_wg, init_unitprice,
                 init_mf, init_hc, init_wc, material, fam, size_name, bevels_combined, link_sub,
                 custom_profile=None, init_mirror_h=False, init_mirror_v=False, init_rotation=0.0,
                 init_offset_a=0.0, init_offset_b=0.0):
        add = obj.addProperty
        add("App::PropertyString", "Material", GROUP, "Profile table").Material = material
        add("App::PropertyString", "Family", GROUP, "Profile family").Family = fam
        add("App::PropertyString", "SizeName", GROUP, "Profile size").SizeName = size_name
        # global links from the start: a member sits outside the Body that holds its path sketch, and a plain
        # link set here printed "Link(s) to object(s) 'Sketch' go out of the allowed scope" on every rebuild
        # (pkg123: 35 times in one session) before globalize_links could change it
        add("App::PropertyLinkGlobal", "CustomProfile", GROUP, "A custom profile's face").CustomProfile = custom_profile
        add("App::PropertyFloat", "ProfileWidth", GROUP, "").ProfileWidth = float(init_w)
        add("App::PropertyFloat", "ProfileHeight", GROUP, "").ProfileHeight = float(init_h)
        add("App::PropertyFloat", "ProfileLength", GROUP, "").ProfileLength = float(init_len)
        add("App::PropertyFloat", "Thickness", GROUP, "Web or wall thickness").Thickness = float(init_mt)
        add("App::PropertyFloat", "ThicknessFlange", GROUP, "Flange thickness").ThicknessFlange = float(init_ft)
        add("App::PropertyFloat", "RadiusLarge", GROUP, "Root radius").RadiusLarge = float(init_r1)
        add("App::PropertyFloat", "RadiusSmall", GROUP, "Toe or inner radius").RadiusSmall = float(init_r2)
        add("App::PropertyBool", "MakeFillet", GROUP, "Rounded corners").MakeFillet = bool(init_mf)
        add("App::PropertyFloat", "OffsetA", GROUP, "Length past the path's end").OffsetA = float(init_offset_a)
        add("App::PropertyFloat", "OffsetB", GROUP, "Length past the path's start").OffsetB = float(init_offset_b)
        add("App::PropertyFloat", "LinearWeight", "Base", "kg/m").LinearWeight = float(init_wg)
        add("App::PropertyFloat", "ApproxWeight", "Base", "kg")
        add("App::PropertyEnumeration", "AnchorX", GROUP, "Pierce point across").AnchorX = list(ANCHOR_X)
        obj.AnchorX = ANCHOR_X[int(init_hc)] if isinstance(init_hc, int) else str(init_hc)
        add("App::PropertyEnumeration", "AnchorY", GROUP, "Pierce point up").AnchorY = list(ANCHOR_Y)
        obj.AnchorY = ANCHOR_Y[int(init_wc)] if isinstance(init_wc, int) else str(init_wc)
        add("App::PropertyBool", "MirrorH", GROUP, "Mirror the section across").MirrorH = bool(init_mirror_h)
        add("App::PropertyBool", "MirrorV", GROUP, "Mirror the section up").MirrorV = bool(init_mirror_v)
        add("App::PropertyFloat", "RotationAngle", GROUP, "Turn of the section about the path (degrees)")
        obj.RotationAngle = float(init_rotation)
        add("App::PropertyLinkSubGlobal", "Target", "Base", "The path edge").Target = link_sub
        add("App::PropertyLength", "Width", "Structure", "").Width = float(init_w)
        add("App::PropertyLength", "Height", "Structure", "").Height = float(init_h)
        add("App::PropertyLength", "Length", "Structure", "")
        for p in ("Material", "Family", "SizeName", "Width", "Height", "Length", "ApproxWeight"):
            obj.setEditorMode(p, 1)
        try:
            obj.setExpression(".AttachmentOffset.Rotation.Angle", "RotationAngle")
        except Exception as _fw_err:
            _fw_log("weprofile.py:270", _fw_err)
        obj.Proxy = self

    def _face(self, obj):
        if obj.Family == "Custom Profile" or obj.CustomProfile is not None:
            src = obj.CustomProfile
            if src is None or src.Shape.isNull():
                raise ValueError("The custom profile is gone")
            shape = src.Shape
            face = shape.Faces[0].copy() if shape.Faces else Part.Face(shape.Wires[0])
            return face, False
        face = section(obj.Family, obj.ProfileWidth, obj.ProfileHeight, obj.Thickness, obj.ThicknessFlange,
                       obj.RadiusLarge, obj.RadiusSmall, obj.MakeFillet)
        return face, True

    def execute(self, obj):
        try:
            edge = obj.Target[0].getSubObject(obj.Target[1][0])
            obj.ProfileLength = edge.Length
        except Exception as _fw_err:
            _fw_log("weprofile.py:290", _fw_err)
        L = obj.ProfileLength + obj.OffsetA + obj.OffsetB
        W, H = obj.ProfileWidth, obj.ProfileHeight
        if profiledata.ANSI_FAMILIES.get(obj.Family, obj.Family) in ("Round Bar", "Pipe"):
            W = H
        face, standard = self._face(obj)
        if standard:
            ax = ANCHOR_X.index(obj.AnchorX) if obj.AnchorX in ANCHOR_X else 1
            ay = ANCHOR_Y.index(obj.AnchorY) if obj.AnchorY in ANCHOR_Y else 1
            face.translate(V(-W * ax / 2.0, -H * ay / 2.0, 0))
            centre = V(W / 2.0 - W * ax / 2.0, H / 2.0 - H * ay / 2.0, 0)
        else:
            centre = V()
        if obj.MirrorH:
            face = face.mirror(centre, V(1, 0, 0))
        if obj.MirrorV:
            face = face.mirror(centre, V(0, 1, 0))
        pl = obj.Placement
        if L > 1e-9:
            face.translate(V(0, 0, -obj.OffsetA))
            obj.Shape = _outward(face.extrude(V(0, 0, L)))
        else:
            obj.Shape = face
        obj.Placement = pl
        try:
            obj.positionBySupport()
        except Exception as _fw_err:
            _fw_log("weprofile.py:317", _fw_err)
        obj.Length = max(L, 0.0)
        obj.ApproxWeight = obj.LinearWeight * L / 1000.0

    def onDocumentRestored(self, obj):
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderProfile:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return icon("profile.svg")

    def getDisplayModes(self, vobj):
        return []

    def getDefaultDisplayMode(self):
        return "Flat Lines"

    def setDisplayMode(self, mode):
        return mode

    def dumps(self):
        return None

    def loads(self, state):
        return None


# ================================================================ trims
def target_of(obj):
    """The path edge (object, [sub]) under a member body, through its trims."""
    while obj is not None:
        if hasattr(obj, "Target"):
            return obj.Target
        obj = getattr(obj, "TrimmedBody", None)
    return None


def _edge(obj):
    t = target_of(obj)
    return t[0].getSubObject(t[1][0]) if t else None


def _half_space(point, normal, size):
    """A solid on the side of the plane (point, normal) normal points to."""
    n = V(normal)
    n.normalize()
    u = n.cross(V(0, 0, 1))
    if u.Length < 1e-6:
        u = n.cross(V(1, 0, 0))
    u.normalize()
    w = n.cross(u)
    corner = point - u * size - w * size
    face = Part.Face(Part.makePolygon([corner, corner + u * 2 * size, corner + u * 2 * size + w * 2 * size,
                                       corner + w * 2 * size, corner]))
    return face.extrude(n * size)


def _keep(shape, near):
    """The solid of shape nearest the point (the body's own side)."""
    solids = shape.Solids
    if len(solids) <= 1:
        return shape
    inside = [s for s in solids if s.isInside(near, 1e-3, True)]
    pick = inside[0] if inside else min(solids, key=lambda s: s.CenterOfMass.distanceToPoint(near))
    return pick


def miter_plane(e1, e2, tol=1e-3):
    """(point, normal) of the plane halving the corner where edges e1 and e2 meet; normal points away
    from e1's member."""
    a0, a1 = e1.Vertexes[0].Point, e1.Vertexes[-1].Point
    b0, b1 = e2.Vertexes[0].Point, e2.Vertexes[-1].Point
    for p, q, r, s in ((a0, a1, b0, b1), (a0, a1, b1, b0), (a1, a0, b0, b1), (a1, a0, b1, b0)):
        if p.distanceToPoint(r) < tol:
            d1, d2 = q - p, s - r
            d1.normalize()
            d2.normalize()
            n = d2 - d1
            if n.Length < 1e-9:
                return None
            n.normalize()
            return p, n
    raise RuntimeError("End Miter: the members' paths do not meet at a common end.")


def _path_ends(body):
    """The two ends of a member's path, or None (a body that is not a member)."""
    try:
        from . import wetrim
        base = wetrim.base_of(body)
        return wetrim.line_of(base) if base is not None else None
    except Exception:
        return None


def _keep_point(cog, ends, p, n):
    """A point on the side of the cutting plane (p, n) that the trim keeps. The member's centre of mass moves
    when Trim/Extend lengthens a short member past the plane (it can end up beyond it, and the trim kept the
    wrong piece); the end of the path farther from the plane stays on the kept side."""
    if ends is not None:
        a, b = ends
        da, db = abs((a - p).dot(n)), abs((b - p).dot(n))
        if abs(da - db) > 1e-6:
            return a if da > db else b
    return cog


class TrimmedProfile:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyLink", "TrimmedBody", "TrimmedProfile", "The body that is trimmed")
        add("App::PropertyLinkSubList", "TrimmingBoundary", "TrimmedProfile", "What it is trimmed against")
        add("App::PropertyEnumeration", "TrimmedProfileType", "TrimmedProfile", "End Trim or End Miter")
        obj.TrimmedProfileType = ["End Trim", "End Miter"]
        add("App::PropertyEnumeration", "CutType", "TrimmedProfile", "Perfect fit or Simple fit")
        obj.CutType = ["Perfect fit", "Simple fit"]
        add("App::PropertyString", "Family", GROUP, "")
        add("App::PropertyLink", "CustomProfile", GROUP, "")
        add("App::PropertyString", "SizeName", GROUP, "")
        add("App::PropertyString", "Material", GROUP, "")
        add("App::PropertyFloat", "ApproxWeight", "Base", "kg")
        add("App::PropertyLength", "Width", "Structure", "")
        add("App::PropertyLength", "Height", "Structure", "")
        add("App::PropertyLength", "Length", "Structure", "")
        for p in ("Family", "CustomProfile", "SizeName", "Material", "ApproxWeight", "Width", "Height", "Length"):
            obj.setEditorMode(p, 1)
        obj.Proxy = self

    def execute(self, obj):
        body = obj.TrimmedBody
        if body is None or body.Shape.isNull():
            return
        shape = body.Shape
        cog = shape.Solids[0].CenterOfMass if shape.Solids else shape.BoundBox.Center
        size = 4 * shape.BoundBox.DiagonalLength + 100.0
        result = shape
        ends = _path_ends(body)
        if obj.TrimmedProfileType == "End Miter":
            mine = _edge(body)
            for other, _subs in obj.TrimmingBoundary or []:
                theirs = _edge(other)
                if mine is None or theirs is None:
                    continue
                plane = miter_plane(mine, theirs)
                if plane is None:
                    continue
                p, n = plane
                if (_keep_point(cog, ends, p, n) - p).dot(n) > 0:
                    n = -n
                result = result.cut(_half_space(p, n, size))
        elif obj.CutType == "Simple fit":
            for other, subs in obj.TrimmingBoundary or []:
                for sub in subs or [""]:
                    try:
                        f = other.getSubObject(sub) if sub else other.Shape.Faces[0]
                    except Exception:
                        continue
                    faces = f.Faces if hasattr(f, "Faces") else []
                    if not faces or faces[0].Surface.TypeId != "Part::GeomPlane":
                        continue
                    face = faces[0]
                    p, n = face.CenterOfMass, face.normalAt(0, 0)
                    if (_keep_point(cog, ends, p, n) - p).dot(n) > 0:
                        n = -n
                    result = result.cut(_half_space(p, n, size))
        else:                       # Perfect fit: cut to the other bodies' shape, keep this body's side
            tools = [o.Shape for o, _s in obj.TrimmingBoundary or [] if not o.Shape.isNull()]
            for t in tools:
                result = result.cut(t)
        result = _outward(_keep(result, cog))
        obj.Shape = result
        self._data(obj)
        if App.GuiUp:
            b = body
            while b is not None:
                try:
                    b.ViewObject.Visibility = False
                except Exception as _fw_err:
                    _fw_log("weprofile.py:485", _fw_err)
                b = getattr(b, "TrimmedBody", None)

    def _data(self, obj):
        base = obj.TrimmedBody
        while base is not None and not hasattr(base, "Target"):
            base = getattr(base, "TrimmedBody", None)
        if base is None:
            return
        obj.Family, obj.SizeName, obj.Material = base.Family, base.SizeName, base.Material
        obj.CustomProfile = base.CustomProfile
        obj.Width, obj.Height = base.ProfileWidth, base.ProfileHeight
        e = _edge(base)
        if e is not None and not obj.Shape.isNull():
            u = e.Vertexes[-1].Point - e.Vertexes[0].Point
            if u.Length > 1e-9:
                u.normalize()
                proj = [v.Point.dot(u) for v in obj.Shape.Vertexes]
                obj.Length = max(proj) - min(proj)
        obj.ApproxWeight = getattr(base, "LinearWeight", 0.0) * float(obj.Length) / 1000.0

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderTrimmedProfile:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def updateData(self, obj, prop):
        if prop == "TrimmedBody" and obj.TrimmedBody is not None:
            try:
                obj.ViewObject.ShapeColor = obj.TrimmedBody.ViewObject.ShapeColor
            except Exception as _fw_err:
                _fw_log("weprofile.py:525", _fw_err)

    def claimChildren(self):
        if not hasattr(self, "Object"):     # asked before attach() on a reopened file (pkg123)
            return []
        body = getattr(self.Object, "TrimmedBody", None)
        return [body] if body is not None else []

    def onDelete(self, vobj, subs):
        body = getattr(self.Object, "TrimmedBody", None)
        if body is not None:
            try:
                body.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("weprofile.py:539", _fw_err)
        return True

    def getIcon(self):
        return icon("trim_extend.svg")

    def getDisplayModes(self, vobj):
        return []

    def getDefaultDisplayMode(self):
        return "Flat Lines"

    def setDisplayMode(self, mode):
        return mode

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _outward(shape):
    """The solids with their faces facing out. A mirrored profile face (and some cuts) gave a solid turned
    inside out: negative volume, drawn near black because the light falls on the faces' backs."""
    try:
        solids = shape.Solids
        if not solids or all(x.Volume >= 0 for x in solids):
            return shape
        import Part
        fixed = [x.reversed() if x.Volume < 0 else x for x in solids]
        return fixed[0] if len(fixed) == 1 else Part.makeCompound(fixed)
    except Exception:
        return shape


def profile_classes(material):
    """(Profile, ViewProviderProfile) for a row's table: FrameForge's for its own tables (aluminium
    extrusions), ours otherwise."""
    if _foreign(material):
        from freecad.frameforge.profile import Profile as P, ViewProviderProfile as VP
        return P, VP
    return Profile, ViewProviderProfile
