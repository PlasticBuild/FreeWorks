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

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except Exception:   # pragma: no cover
    Gui = None

_OPEN = []

# =========================================================================== Beam Calculator
LOAD_TYPES = (
    # key, text, uniform (load per length), needs a distance
    ("cant-end", "Cantilever - load at end", False, False),
    ("cant-uniform", "Cantilever - uniform load", True, False),
    ("cant-moment", "Cantilever - moment at end", False, False),
    ("ss-center", "Simply supported - load at center", False, False),
    ("ss-point", "Simply supported - load at any point", False, True),
    ("ss-uniform", "Simply supported - uniform load", True, False),
    ("fixed-center", "Fixed both ends - load at center", False, False),
    ("fixed-uniform", "Fixed both ends - uniform load", True, False),
)
LOADS = dict((k, (t, u, d)) for k, t, u, d in LOAD_TYPES)


def beam_moment(kind, load, length, distance=None):
    """The largest bending moment (N mm) of a load case: load in N (N/mm when uniform, N mm for a moment)."""
    P, L = float(load), float(length)
    if kind == "cant-end":
        return P * L
    if kind == "cant-uniform":
        return P * L * L / 2.0
    if kind == "cant-moment":
        return P
    if kind == "ss-center":
        return P * L / 4.0
    if kind == "ss-point":
        a = float(distance if distance is not None else L / 2.0)
        return P * a * (L - a) / L
    if kind == "ss-uniform":
        return P * L * L / 8.0
    if kind == "fixed-center":
        return P * L / 8.0
    if kind == "fixed-uniform":
        return P * L * L / 12.0
    raise ValueError(kind)


def beam_deflection(kind, load, length, E, I, distance=None):
    """The largest deflection (mm) of a load case: E in N/mm^2 (MPa), I in mm^4."""
    P, L, E, I = float(load), float(length), float(E), float(I)
    if kind == "cant-end":
        return P * L ** 3 / (3 * E * I)
    if kind == "cant-uniform":
        return P * L ** 4 / (8 * E * I)
    if kind == "cant-moment":
        return P * L ** 2 / (2 * E * I)
    if kind == "ss-center":
        return P * L ** 3 / (48 * E * I)
    if kind == "ss-point":
        a = float(distance if distance is not None else L / 2.0)
        b = min(a, L - a)
        return P * b * (L * L - b * b) ** 1.5 / (9 * math.sqrt(3) * L * E * I)
    if kind == "ss-uniform":
        return 5 * P * L ** 4 / (384 * E * I)
    if kind == "fixed-center":
        return P * L ** 3 / (192 * E * I)
    if kind == "fixed-uniform":
        return P * L ** 4 / (384 * E * I)
    raise ValueError(kind)


def beam_stress(kind, load, length, Z, distance=None):
    """The largest bending stress (MPa) of a load case: Z (section modulus) in mm^3."""
    return beam_moment(kind, load, length, distance) / float(Z)


BEAM_FIELDS = ("load", "length", "section", "result")    # section: I (deflection) or Z (stress)


def beam_solve(kind, calc, values, unknown):
    """Solves the beam for the one unknown of BEAM_FIELDS; values holds the others (and E, distance).
    calc is "Deflection" or "Stress". Returns the unknown's value."""
    v = dict(values)

    def result(vals):
        if calc == "Stress":
            return beam_stress(kind, vals["load"], vals["length"], vals["section"], vals.get("distance"))
        return beam_deflection(kind, vals["load"], vals["length"], vals["E"], vals["section"], vals.get("distance"))
    if unknown == "result":
        return result(v)
    target = float(v["result"])
    if target <= 0:
        raise ValueError("The %s must be more than zero." % calc.lower())
    lo, hi = 1e-9, 1e15
    # the result rises with the load and the length, falls with the section: bisect in log space
    rising = unknown in ("load", "length")
    if unknown == "length" and kind == "ss-point":
        lo = max(lo, float(v.get("distance") or 0) * 1.000001)
    for _i in range(200):
        mid = math.sqrt(lo * hi)
        v[unknown] = mid
        r = result(v)
        if (r < target) == rising:
            lo = mid
        else:
            hi = mid
        if hi / lo < 1 + 1e-12:
            break
    return math.sqrt(lo * hi)


# --------------------------------------------------------------------------- sections
SECTION_STANDARDS = (("ISO", "metal"), ("ANSI Inch", "ansi_inch"))


def section_types(std):
    from . import weprofile
    mat = dict(SECTION_STANDARDS)[std]
    return list(weprofile.tables().get(mat, {}))


def section_sizes(std, family):
    from . import weprofile
    mat = dict(SECTION_STANDARDS)[std]
    return list(weprofile.tables().get(mat, {}).get(family, {}).get("sizes", {}))


def section_face(std, family, size):
    """The section of a standard size as a face in XY, its centroid at the origin."""
    from . import weprofile
    mat = dict(SECTION_STANDARDS)[std]
    spec = weprofile.tables()[mat][family]
    d = spec["sizes"][size]
    g = lambda k: float(d.get(k, 0) or 0)
    face = weprofile.section(family, g("Width"), g("Height"), g("Thickness"), g("Flange Thickness"),
                             g("Radius1"), g("Radius2"), bool(spec.get("fillet", True)))
    face = face.copy()
    face.translate(App.Vector() - face.CenterOfMass)
    return face, g("Weight")


def section_properties(face, weight=0.0):
    """{area, Ix, Iy, Zx, Zy, rx, ry, primary, mass}: mm^2, mm^4, mm^3, mm; about the centroid's X and Y axes.
    primary is "X" or "Y", the axis with the larger moment of inertia."""
    A = face.Area
    c = face.CenterOfMass
    M = face.MatrixOfInertia
    Ix, Iy = M.A11, M.A22
    bb = face.BoundBox
    cy = max(abs(bb.YMax - c.y), abs(bb.YMin - c.y)) or 1.0
    cx = max(abs(bb.XMax - c.x), abs(bb.XMin - c.x)) or 1.0
    return {"area": A, "Ix": Ix, "Iy": Iy, "Zx": Ix / cy, "Zy": Iy / cx, "rx": math.sqrt(Ix / A),
            "ry": math.sqrt(Iy / A), "primary": "X" if Ix >= Iy else "Y", "mass": weight}


def axis_values(props, axis="Primary"):
    """(I, Z) about the Primary (stronger) or Secondary axis."""
    strong = props["primary"]
    use = strong if axis == "Primary" else ("Y" if strong == "X" else "X")
    return props["I" + use.lower()], props["Z" + use.lower()]


def _sketch_from_face(sketch, face, placement=None):
    """The face's edges as sketch geometry (lines, circles and arcs), in the sketch's own plane."""
    import Part
    n = 0
    for e in face.Edges:
        c = e.Curve
        if placement is not None:
            e = e.copy()
            e.transformShape(placement.Matrix)
            c = e.Curve
        if isinstance(c, Part.Circle):
            if e.isClosed():
                sketch.addGeometry(Part.Circle(App.Vector(c.Center.x, c.Center.y, 0), App.Vector(0, 0, 1), c.Radius))
            else:
                arc = Part.ArcOfCircle(Part.Circle(App.Vector(c.Center.x, c.Center.y, 0), App.Vector(0, 0, 1),
                                                   c.Radius), 0, 1)
                a1 = math.atan2(e.Vertexes[0].Point.y - c.Center.y, e.Vertexes[0].Point.x - c.Center.x)
                a2 = math.atan2(e.Vertexes[-1].Point.y - c.Center.y, e.Vertexes[-1].Point.x - c.Center.x)
                mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2.0)
                am = math.atan2(mid.y - c.Center.y, mid.x - c.Center.x)
                s, t = a1, a2
                while t <= s:
                    t += 2 * math.pi
                m = am
                while m < s:
                    m += 2 * math.pi
                if m > t:        # the arc runs the other way round
                    s, t = a2, a1
                    while t <= s:
                        t += 2 * math.pi
                arc = Part.ArcOfCircle(Part.Circle(App.Vector(c.Center.x, c.Center.y, 0), App.Vector(0, 0, 1),
                                                   c.Radius), s, t)
                sketch.addGeometry(arc)
        else:
            p, q = e.Vertexes[0].Point, e.Vertexes[-1].Point
            sketch.addGeometry(Part.LineSegment(App.Vector(p.x, p.y, 0), App.Vector(q.x, q.y, 0)))
        n += 1
    return n


def _body_of(obj):
    if obj is None:
        return None
    if obj.TypeId == "PartDesign::Body":
        return obj
    try:
        import PartDesign  # noqa: F401
        body = obj.getParentGeoFeatureGroup()
        if body is not None and body.TypeId == "PartDesign::Body":
            return body
    except Exception as _fw_err:
        _fw_log("toolboxtools.py:body", _fw_err)
    return next((o for o in obj.InList if o.TypeId == "PartDesign::Body"), None)


def active_body(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    if App.GuiUp:
        try:
            b = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
            if b is not None:
                return b
        except Exception as _fw_err:
            _fw_log("toolboxtools.py:pdbody", _fw_err)
    return next((o for o in doc.Objects if o.TypeId == "PartDesign::Body"), None)


def _front_plane(body):
    return next(o for o in body.Origin.OriginFeatures if getattr(o, "Role", "") == "XZ_Plane")


def insert_section(std, family, size, doc=None, support=None, sketch=None):
    """Structural Steel's Create: the section's sketch in the part (on support = (object, "FaceN") or a plane,
    else the Front Plane; or into sketch when one is given). Returns the sketch."""
    face, _w = section_face(std, family, size)
    if sketch is not None:
        _sketch_from_face(sketch, face)
        sketch.Document.recompute()
        return sketch
    doc = doc or App.ActiveDocument
    body = active_body(doc)
    if body is None:
        body = doc.addObject("PartDesign::Body", "Body")
    sk = body.newObject("Sketcher::SketchObject", "Sketch")
    if support is not None:
        sk.AttachmentSupport = [support] if isinstance(support, tuple) else [(support, "")]
    else:
        sk.AttachmentSupport = [(_front_plane(body), "")]
    sk.MapMode = "FlatFace"
    _sketch_from_face(sk, face)
    sk.Label = "%s %s" % (family, size)
    doc.recompute()
    return sk


# =========================================================================== Bearing Calculator
RELIABILITY = ((90, 1.0), (95, 0.64), (96, 0.55), (97, 0.47), (98, 0.37), (99, 0.25))    # ISO 281 a1


def bearing_life(C_kN, P_N, rpm=None, reliability=90, roller=False):
    """(L in millions of revolutions, hours or None): ISO 281, L = a1 (C / P)^p, p = 3 (ball), 10/3 (roller)."""
    if P_N <= 0:
        raise ValueError("The equivalent load must be more than zero.")
    a1 = dict(RELIABILITY).get(int(reliability), 1.0)
    p = 10.0 / 3.0 if roller else 3.0
    L = a1 * (C_kN * 1000.0 / P_N) ** p
    hours = L * 1e6 / (60.0 * rpm) if rpm else None
    return L, hours


# =========================================================================== Cams
MOTIONS = ("Dwell", "Harmonic", "Cycloidal", "Uniform", "3-4-5 Polynomial")


def _ease(kind, u):
    if kind == "Harmonic":
        return (1 - math.cos(math.pi * u)) / 2.0
    if kind == "Cycloidal":
        return u - math.sin(2 * math.pi * u) / (2 * math.pi)
    if kind == "Uniform":
        return u
    if kind == "3-4-5 Polynomial":
        return 10 * u ** 3 - 15 * u ** 4 + 6 * u ** 5
    return 0.0


def cam_radius(start, rows, angle):
    """The follower's (pitch) radius at a cam angle (degrees from the start): rows are
    (motion, ending radius, degrees)."""
    r, at = float(start), 0.0
    a = angle % 360.0
    for motion, end, deg in rows:
        deg = float(deg)
        if a <= at + deg + 1e-12 and deg > 0:
            u = (a - at) / deg
            if motion == "Dwell":
                return r
            return r + (float(end) - r) * _ease(motion, u)
        if motion != "Dwell":
            r = float(end)
        at += deg
    return r


def cam_check(start, rows):
    """None when the motion is complete (360 degrees, back to the start), else what is wrong."""
    total = sum(float(d) for _m, _e, d in rows)
    if abs(total - 360.0) > 1e-6:
        return "The motions add up to %g degrees; they must add up to 360." % total
    end = float(start)
    for m, e, _d in rows:
        if m != "Dwell":
            end = float(e)
    if abs(end - float(start)) > 1e-6:
        return "The last motion must end at the starting radius (%g)." % float(start)
    return None


CAM_TYPES = ("Circular", "Linear")
FOLLOWERS = ("Translating", "Left Swinging", "Right Swinging")


def swing_angle(r, pivot, arm, side):
    """A swinging follower: the roller rides an arc of the arm's length about the pivot, so at pitch radius r it
    sits off the line to the pivot by this angle (degrees; side +1 left, -1 right)."""
    c = (pivot * pivot + r * r - arm * arm) / (2.0 * pivot * r)
    if c < -1.0 - 1e-9 or c > 1.0 + 1e-9:
        raise ValueError("A follower arm of %g on a pivot %g from the cam center cannot reach radius %g." % (arm, pivot, r))
    return side * math.degrees(math.acos(max(-1.0, min(1.0, c))))


def cam_points(start, rows, follower_d, clockwise=False, start_angle=0.0, n=720, follower="Translating",
               pivot=0.0, arm=0.0):
    """The cam's outline: the roller centre's (pitch) curve offset in by the roller's radius. A translating
    follower moves along a line through the cam centre; a swinging one on its arm about the pivot."""
    rf = float(follower_d) / 2.0
    sgn = -1.0 if clockwise else 1.0
    side = {"Left Swinging": 1.0, "Right Swinging": -1.0}.get(follower, 0.0)
    pitch = []
    for i in range(n):
        th = 360.0 * i / n
        r = cam_radius(start, rows, th)
        off = swing_angle(r, float(pivot), float(arm), side) if side else 0.0
        a = math.radians(start_angle + sgn * th + off)
        pitch.append(App.Vector(r * math.cos(a), r * math.sin(a), 0))
    out = []
    for i in range(n):
        t = pitch[(i + 1) % n] - pitch[i - 1]
        nrm = App.Vector(t.y, -t.x, 0) * sgn     # outward for a counterclockwise pitch curve
        if nrm.Length < 1e-12:
            nrm = App.Vector(pitch[i])
        nrm.normalize()
        if nrm.dot(pitch[i]) < 0:
            nrm = nrm * -1
        out.append(pitch[i] - nrm * rf)
    return out


def linear_rows_check(rows):
    total = sum(float(d) for _m, _e, d in rows)
    if total <= 0:
        return "The motions must add up to more than zero length."
    return None


def linear_cam_radius(start, rows, x):
    """A linear cam: the follower's height at x along the cam (rows are motion, ending height, length)."""
    r, at = float(start), 0.0
    for motion, end, length in rows:
        length = float(length)
        if x <= at + length + 1e-12 and length > 0:
            u = (x - at) / length
            return r if motion == "Dwell" else r + (float(end) - r) * _ease(motion, u)
        if motion != "Dwell":
            r = float(end)
        at += length
    return r


def linear_cam_points(start, rows, follower_d, n=400):
    """The linear cam's top edge: the follower's pitch line offset down by the roller's radius."""
    rf = float(follower_d) / 2.0
    total = sum(float(d) for _m, _e, d in rows)
    pitch = [App.Vector(total * i / n, linear_cam_radius(start, rows, total * i / n), 0) for i in range(n + 1)]
    out = []
    for i, p in enumerate(pitch):
        t = pitch[min(n, i + 1)] - pitch[max(0, i - 1)]
        nrm = App.Vector(-t.y, t.x, 0)
        nrm.normalize()
        out.append(p - nrm * rf)
    return out


def make_cam(setup, rows, creation, doc=None):
    """The cam as a new part: a sketch of its outline, padded to the blank thickness, with the hub and the bore.
    Returns the body."""
    import Part
    linear = setup.get("type", "Circular") == "Linear"
    msg = linear_rows_check(rows) if linear else cam_check(setup["start"], rows)
    if msg:
        raise ValueError(msg)
    if doc is None:
        from . import newdoc
        try:
            doc = newdoc.make("Part")
        except Exception:
            doc = App.newDocument("Cam")
    body = active_body(doc) or doc.addObject("PartDesign::Body", "Body")
    sk = body.newObject("Sketcher::SketchObject", "CamProfile")
    sk.AttachmentSupport = [(_front_plane(body), "")]
    sk.MapMode = "FlatFace"
    if linear:                      # a plate: the cam edge on top, flat below
        pts = linear_cam_points(setup["start"], rows, setup["follower"])
        if min(p.y for p in pts) <= 1e-6:
            raise ValueError("The follower's starting height must clear the roller: make the heights more than %g."
                             % (setup["follower"] / 2.0))
        top = Part.BSplineCurve()
        top.interpolate(pts)
        a, b = pts[0], pts[-1]
        sk.addGeometry([top, Part.LineSegment(b, App.Vector(b.x, 0, 0)), Part.LineSegment(App.Vector(b.x, 0, 0), App.Vector(a.x, 0, 0)),
                        Part.LineSegment(App.Vector(a.x, 0, 0), a)])
    else:
        pts = cam_points(setup["start"], rows, setup["follower"], setup.get("clockwise", False),
                         setup.get("start_angle", 0.0), follower=setup.get("follower_type", "Translating"),
                         pivot=setup.get("pivot", 0.0), arm=setup.get("arm", 0.0))
        spline = Part.BSplineCurve()
        spline.interpolate(pts, PeriodicFlag=True)
        sk.addGeometry(spline)
    doc.recompute()
    pad = body.newObject("PartDesign::Pad", "Cam")
    pad.Profile = sk
    pad.Length = float(creation["thickness"])
    doc.recompute()
    last = pad
    hub_d, hub_l = float(creation.get("hub_d", 0)), float(creation.get("hub_l", 0))
    if hub_d > 0 and hub_l > 0 and not linear:
        hs = body.newObject("Sketcher::SketchObject", "Hub")
        hs.AttachmentSupport = [(_front_plane(body), "")]
        hs.MapMode = "FlatFace"
        hs.AttachmentOffset = App.Placement(App.Vector(0, 0, float(creation["thickness"])), App.Rotation())
        hs.addGeometry(Part.Circle(App.Vector(), App.Vector(0, 0, 1), hub_d / 2.0))
        doc.recompute()
        hp = body.newObject("PartDesign::Pad", "Hub")
        hp.Profile = hs
        hp.Length = hub_l
        doc.recompute()
        last = hp
    bore = float(creation.get("bore", 0))
    if bore > 0 and not linear:
        bs = body.newObject("Sketcher::SketchObject", "Bore")
        bs.AttachmentSupport = [(_front_plane(body), "")]
        bs.MapMode = "FlatFace"
        bs.addGeometry(Part.Circle(App.Vector(), App.Vector(0, 0, 1), bore / 2.0))
        doc.recompute()
        pk = body.newObject("PartDesign::Pocket", "Bore")
        pk.Profile = bs
        pk.Type = "ThroughAll"
        pk.Midplane = True
        doc.recompute()
        last = pk
    body.Tip = last
    body.Label = "Cam"
    doc.recompute()
    return body


# =========================================================================== Grooves
GROOVE_TYPES = ("O-Ring Groove - external (on a shaft)", "O-Ring Groove - internal (in a bore)",
                "Retaining Ring Groove - external (DIN 471)", "Retaining Ring Groove - internal (DIN 472)")


def groove_sizes(gtype, dia):
    """[(size text, groove diameter, groove width)] for a groove type on a face of diameter dia, the fitting
    one first."""
    from . import toolboxparts as T
    out = []
    if gtype.startswith("Retaining") and "external" in gtype:
        for d, (_s, d2, m) in T.EXTERNAL.items():
            out.append(("%g" % d, d2, m, abs(d - dia)))
    elif gtype.startswith("Retaining"):
        for d, (_s, d2, m) in T.INTERNAL.items():
            out.append(("%g" % d, d2, m, abs(d - dia)))
    else:
        external = "external" in gtype
        # the usual cross section for the diameter comes first (ISO 3601-2 grooves for a static radial seal)
        prefer = 1.78 if dia < 15 else 2.62 if dia < 40 else 3.53 if dia < 80 else 5.33
        for cs, ids in T.O_RINGS.items():
            depth, width = round(0.8 * cs, 2), round(1.4 * cs, 2)
            for d1 in ids:
                gd = dia - 2 * depth if external else dia + 2 * depth
                # on a shaft the ring's inside sits on the groove root (stretched up to 5 %);
                # in a bore its outside presses on the groove root (up to 3 % over)
                fit = (gd - d1) / gd if external else ((d1 + 2 * cs) - gd) / gd
                if not (-0.01 <= fit <= (0.05 if external else 0.03)):
                    continue
                out.append(("%g x %g" % (d1, cs), gd, width, (0 if cs == prefer else 1) + abs(fit)))
    out.sort(key=lambda r: r[3])
    return [r[:3] for r in out]


def groove_face(obj, face_name):
    """(centre, axis, radius, on a shaft, face) of a cylindrical face of a part's feature, global frame."""
    shp = obj.Shape.copy()
    try:
        shp.Placement = obj.getGlobalPlacement()
    except Exception as _fw_err:
        _fw_log("toolboxtools.py:gpl", _fw_err)
    f = shp.getElement(face_name)
    if f.Surface.TypeId != "Part::GeomCylinder":
        raise ValueError("Pick a cylindrical face (a shaft or a bore).")
    s = f.Surface
    c, a, r = App.Vector(s.Center), App.Vector(s.Axis).normalize(), s.Radius
    u0, u1, v0, v1 = f.ParameterRange
    p = f.valueAt(u0, (v0 + v1) / 2.0)
    n = f.normalAt(u0, (v0 + v1) / 2.0)
    to_axis = (c + a * (p - c).dot(a)) - p
    shaft = not (to_axis.Length > 1e-9 and n.dot(to_axis) > 0)
    return c, a, r, shaft, f


def make_groove(obj, face_name, gtype, size=None, distance=None, end=None):
    """Adds the groove to the part: the cylindrical face picked, the groove type, its size (the fitting one when
    None) and the distance (mm) of its near edge from the end face end = (object, "FaceN") or from the
    cylinder's lower end. Returns the Groove feature."""
    import Part
    c, a, r, shaft, f = groove_face(obj, face_name)
    if ("external" in gtype) != shaft:
        raise ValueError("An external groove goes on a shaft, an internal one in a bore.")
    rows = groove_sizes(gtype, 2 * r)
    if not rows:
        raise ValueError("No standard size fits a %g mm diameter." % (2 * r))
    row = next((x for x in rows if x[0] == size), rows[0]) if size else rows[0]
    _txt, gd, width = row
    zs = [v.Point.dot(a) for v in f.Vertexes] or [c.dot(a)]
    lo, hi = min(zs), max(zs)
    if end is not None:
        ef = end[0].Shape.copy()
        try:
            ef.Placement = end[0].getGlobalPlacement()
        except Exception as _fw_err:
            _fw_log("toolboxtools.py:epl", _fw_err)
        level = ef.getElement(end[1]).CenterOfMass.dot(a)
    else:
        level = lo
    inward = 1.0 if abs(level - lo) <= abs(level - hi) else -1.0
    d = float(distance if distance is not None else 2.0)
    y0 = level + inward * d
    y1 = y0 + inward * width
    y0, y1 = min(y0, y1), max(y0, y1)
    if y0 < lo - 1e-6 or y1 > hi + 1e-6:
        raise ValueError("The groove does not fit on the face at that distance.")
    body = _body_of(obj)
    if body is None:
        raise ValueError("Grooves go on a part's body.")
    # the sketch plane holds the axis: its X axis points out of the axis, its Y axis along it
    u = a.cross(App.Vector(0, 0, 1))
    if u.Length < 1e-6:
        u = a.cross(App.Vector(1, 0, 0))
    u.normalize()
    base = c + a * (0.0 - c.dot(a))
    glob = App.Placement(base, App.Rotation(u, a, u.cross(a), "ZXY"))
    sk = body.newObject("Sketcher::SketchObject", "GrooveSketch")
    sk.MapMode = "Deactivated"
    sk.Placement = body.getGlobalPlacement().inverse().multiply(glob)
    if shaft:
        x0, x1 = gd / 2.0, r + 0.5
    else:
        x0, x1 = r - 0.5, gd / 2.0
    pts = [App.Vector(x0, y0, 0), App.Vector(x1, y0, 0), App.Vector(x1, y1, 0), App.Vector(x0, y1, 0)]
    for i in range(4):
        sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]))
    doc = obj.Document
    doc.recompute()
    g = body.newObject("PartDesign::Groove", "Groove")
    g.Profile = sk
    g.ReferenceAxis = (sk, ["V_Axis"])
    g.Angle = 360.0
    g.Label = ("O-Ring Groove" if gtype.startswith("O-Ring") else "Retaining Ring Groove")
    sk.Visibility = False
    doc.recompute()
    return g


# =========================================================================== GUI
if Gui is not None:
    def _spin(lo, hi, dec, value, suffix=""):
        s = QtWidgets.QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(dec)
        s.setValue(value)
        if suffix:
            s.setSuffix(suffix)
        return s

    class SectionPicker(QtWidgets.QWidget):
        """Standard, Type and Size combos of the Structural Steel tables."""

        def __init__(self, parent=None, changed=None):
            super().__init__(parent)
            f = QtWidgets.QFormLayout(self)
            f.setContentsMargins(0, 0, 0, 0)
            self.std = QtWidgets.QComboBox()
            self.std.setObjectName("SWSteel_std")
            self.std.addItems([s for s, _m in SECTION_STANDARDS])
            self.type = QtWidgets.QComboBox()
            self.type.setObjectName("SWSteel_type")
            self.size = QtWidgets.QComboBox()
            self.size.setObjectName("SWSteel_size")
            f.addRow("Standard:", self.std)
            f.addRow("Type:", self.type)
            f.addRow("Size:", self.size)
            self._changed = changed
            self.std.currentIndexChanged.connect(self._types)
            self.type.currentIndexChanged.connect(self._sizes)
            self.size.currentIndexChanged.connect(lambda *_: self._changed and self._changed())
            self._types()

        def _types(self, *_):
            self.type.blockSignals(True)
            self.type.clear()
            self.type.addItems(section_types(self.std.currentText()))
            if self.type.findText("IPE") >= 0:
                self.type.setCurrentText("IPE")
            self.type.blockSignals(False)
            self._sizes()

        def _sizes(self, *_):
            self.size.blockSignals(True)
            self.size.clear()
            self.size.addItems(section_sizes(self.std.currentText(), self.type.currentText()))
            self.size.blockSignals(False)
            if self._changed:
                self._changed()

        def value(self):
            return self.std.currentText(), self.type.currentText(), self.size.currentText()

        def properties(self):
            std, fam, size = self.value()
            if not size:
                return None
            face, w = section_face(std, fam, size)
            return section_properties(face, w)

    class StructuralSteel(QtWidgets.QDialog):
        ""

        def __init__(self, parent=None, pick=None):
            super().__init__(parent or Gui.getMainWindow())
            self.setObjectName("SWStructuralSteel")
            self.setWindowTitle("Structural Steel")
            self.picked = None
            lay = QtWidgets.QVBoxLayout(self)
            self.picker = SectionPicker(self, self._show)
            lay.addWidget(self.picker)
            box = QtWidgets.QGroupBox("Section Properties")
            self.props = QtWidgets.QLabel()
            self.props.setObjectName("SWSteel_props")
            QtWidgets.QVBoxLayout(box).addWidget(self.props)
            lay.addWidget(box)
            row = QtWidgets.QHBoxLayout()
            self.create = QtWidgets.QPushButton("Create" if pick is None else "OK")
            self.create.setObjectName("SWSteel_create")
            self.create.clicked.connect(self._create if pick is None else self._pick)
            done = QtWidgets.QPushButton("Done" if pick is None else "Cancel")
            done.clicked.connect(self.reject)
            row.addStretch(1)
            row.addWidget(self.create)
            row.addWidget(done)
            lay.addLayout(row)
            self._show()

        def _show(self):
            if not hasattr(self, "props"):
                return
            try:
                p = self.picker.properties()
            except Exception as error:
                self.props.setText(str(error))
                return
            if p is None:
                self.props.setText("")
                return
            self.props.setText(
                "Area: %.1f mm^2\nMoment of inertia: Ix %.4g mm^4, Iy %.4g mm^4\nSection modulus: Zx %.4g mm^3, "
                "Zy %.4g mm^3\nRadius of gyration: rx %.2f mm, ry %.2f mm\nPrimary axis: %s%s" % (
                    p["area"], p["Ix"], p["Iy"], p["Zx"], p["Zy"], p["rx"], p["ry"], p["primary"],
                    ("\nMass per length: %g kg/m" % p["mass"]) if p["mass"] else ""))

        def _pick(self):
            self.picked = self.picker.properties()
            self.accept()

        def _create(self):
            std, fam, size = self.picker.value()
            doc = App.ActiveDocument
            if doc is None:
                QtWidgets.QMessageBox.information(self, "Structural Steel", "Open a part first.")
                return None
            sketch, support = None, None
            try:
                edit = Gui.ActiveDocument.getInEdit()
                obj = editobj.of(edit) if edit is not None else None
                if obj is not None and obj.TypeId == "Sketcher::SketchObject":
                    sketch = obj
            except Exception as _fw_err:
                _fw_log("toolboxtools.py:inedit", _fw_err)
            if sketch is None:
                sel = Gui.Selection.getSelectionEx()
                for s in sel:
                    names = [n for n in s.SubElementNames if n.startswith("Face")]
                    if names:
                        support = (s.Object, names[0])
                        break
                    if s.Object.TypeId in ("App::Plane", "PartDesign::Plane"):
                        support = s.Object
                        break
            doc.openTransaction("Structural Steel")
            try:
                made = insert_section(std, fam, size, doc, support, sketch)
            finally:
                doc.commitTransaction()
            self.made = made
            return made

    class BeamCalculator(QtWidgets.QDialog):
        ""

        def __init__(self, parent=None):
            super().__init__(parent or Gui.getMainWindow())
            self.setObjectName("SWBeamCalculator")
            self.setWindowTitle("Beam Calculator")
            lay = QtWidgets.QHBoxLayout(self)
            left = QtWidgets.QVBoxLayout()
            left.addWidget(QtWidgets.QLabel("Load type:"))
            self.load_type = QtWidgets.QListWidget()
            self.load_type.setObjectName("SWBeam_loadtype")
            for k, t, _u, _d in LOAD_TYPES:
                it = QtWidgets.QListWidgetItem(t)
                it.setData(QtCore.Qt.UserRole, k)
                self.load_type.addItem(it)
            self.load_type.setCurrentRow(0)
            left.addWidget(self.load_type, 1)
            calc = QtWidgets.QGroupBox("Type of calculation")
            cl = QtWidgets.QHBoxLayout(calc)
            self.deflection = QtWidgets.QRadioButton("Deflection")
            self.stress = QtWidgets.QRadioButton("Stress")
            self.deflection.setChecked(True)
            cl.addWidget(self.deflection)
            cl.addWidget(self.stress)
            left.addWidget(calc)
            lay.addLayout(left)
            right = QtWidgets.QVBoxLayout()
            beam = QtWidgets.QGroupBox("Beam")
            bl = QtWidgets.QFormLayout(beam)
            self.pick = QtWidgets.QPushButton("Beam...")
            self.pick.setObjectName("SWBeam_pick")
            self.pick.clicked.connect(self._beam)
            self.beam_name = QtWidgets.QLabel("(typed in)")
            self.axis = QtWidgets.QComboBox()
            self.axis.setObjectName("SWBeam_axis")
            self.axis.addItems(["Primary", "Secondary"])
            self.axis.currentIndexChanged.connect(self._axis)
            bl.addRow(self.pick, self.beam_name)
            bl.addRow("Axis:", self.axis)
            right.addWidget(beam)
            box = QtWidgets.QGroupBox("Input / Output (solve for the one ticked)")
            g = QtWidgets.QGridLayout(box)
            self.E = _spin(1, 1e7, 1, 210000.0, " MPa")
            self.E.setObjectName("SWBeam_E")
            self.fields, self.solve_for = {}, {}
            rows = (("load", "Load:", _spin(0, 1e12, 4, 1000.0)), ("length", "Length:", _spin(0, 1e9, 3, 1000.0, " mm")),
                    ("distance", "Distance:", _spin(0, 1e9, 3, 500.0, " mm")),
                    ("section", "Moment of inertia:", _spin(0, 1e15, 2, 8.36e6, " mm^4")),
                    ("result", "Deflection:", _spin(0, 1e12, 6, 0.0, " mm")))
            g.addWidget(QtWidgets.QLabel("Modulus of elasticity:"), 0, 1)
            g.addWidget(self.E, 0, 2)
            self.labels = {}
            for i, (key, text, w) in enumerate(rows, 1):
                w.setObjectName("SWBeam_" + key)
                lab = QtWidgets.QLabel(text)
                self.labels[key] = lab
                self.fields[key] = w
                if key != "distance":
                    rb = QtWidgets.QRadioButton()
                    rb.setObjectName("SWBeam_solve_" + key)
                    self.solve_for[key] = rb
                    g.addWidget(rb, i, 0)
                g.addWidget(lab, i, 1)
                g.addWidget(w, i, 2)
            self.solve_for["result"].setChecked(True)
            right.addWidget(box)
            self.note = QtWidgets.QLabel()
            self.note.setObjectName("SWBeam_note")
            self.note.setWordWrap(True)
            right.addWidget(self.note)
            row = QtWidgets.QHBoxLayout()
            solve = QtWidgets.QPushButton("Solve")
            solve.setObjectName("SWBeam_solve")
            solve.clicked.connect(self.solve)
            done = QtWidgets.QPushButton("Done")
            done.clicked.connect(self.accept)
            row.addStretch(1)
            row.addWidget(solve)
            row.addWidget(done)
            right.addLayout(row)
            lay.addLayout(right, 1)
            self.props = None
            self.load_type.currentRowChanged.connect(lambda *_: self._labels())
            self.deflection.toggled.connect(lambda *_: (self._labels(), self._axis()))
            self._labels()

        def kind(self):
            return self.load_type.currentItem().data(QtCore.Qt.UserRole)

        def calc(self):
            return "Stress" if self.stress.isChecked() else "Deflection"

        def _labels(self):
            _t, uniform, distance = LOADS[self.kind()]
            moment = self.kind() == "cant-moment"
            self.labels["load"].setText("Moment:" if moment else ("Load per length:" if uniform else "Load:"))
            self.fields["load"].setSuffix(" N mm" if moment else (" N/mm" if uniform else " N"))
            self.fields["distance"].setEnabled(distance)
            self.labels["distance"].setVisible(distance)
            self.fields["distance"].setVisible(distance)
            stress = self.calc() == "Stress"
            self.labels["section"].setText("Section modulus:" if stress else "Moment of inertia:")
            self.fields["section"].setSuffix(" mm^3" if stress else " mm^4")
            self.labels["result"].setText("Stress:" if stress else "Deflection:")
            self.fields["result"].setSuffix(" MPa" if stress else " mm")
            self.E.setEnabled(not stress)

        def _beam(self):
            box = StructuralSteel(self, pick=True)
            if box.exec() and box.picked:
                self.props = box.picked
                self.beam_name.setText(" ".join(box.picker.value()[1:]))
                self._axis()

        def _axis(self, *_):
            if not self.props:
                return
            I, Z = axis_values(self.props, self.axis.currentText())
            self.fields["section"].setValue(Z if self.calc() == "Stress" else I)

        def values(self):
            return dict((k, w.value()) for k, w in self.fields.items()), self.E.value()

        def solve(self):
            unknown = next(k for k, rb in self.solve_for.items() if rb.isChecked())
            vals, E = self.values()
            vals["E"] = E
            if not LOADS[self.kind()][2]:
                vals.pop("distance", None)
            try:
                for k in ("load", "length", "section", "result"):
                    if k != unknown and vals[k] <= 0:
                        raise ValueError("Type a value more than zero for every input except the one to solve for.")
                if vals.get("distance") is not None and vals["distance"] > vals["length"] and unknown != "length":
                    raise ValueError("The distance must be within the length.")
                got = beam_solve(self.kind(), self.calc(), vals, unknown)
            except Exception as error:
                self.note.setText(str(error))
                return None
            self.fields[unknown].setValue(got)
            self.note.setText("")
            return got

    class BearingCalculator(QtWidgets.QDialog):
        ""

        def __init__(self, parent=None):
            super().__init__(parent or Gui.getMainWindow())
            from . import toolboxparts as T
            self.T = T
            self.setObjectName("SWBearingCalculator")
            self.setWindowTitle("Bearing Calculator")
            lay = QtWidgets.QVBoxLayout(self)
            box = QtWidgets.QGroupBox("Bearing")
            f = QtWidgets.QFormLayout(box)
            self.type = QtWidgets.QComboBox()
            self.type.setObjectName("SWBearing_type")
            for k in T.BEARINGS:
                self.type.addItem(T.KINDS[k][1], k)
            self.size = QtWidgets.QComboBox()
            self.size.setObjectName("SWBearing_size")
            self.rating = QtWidgets.QLabel()
            self.rating.setObjectName("SWBearing_rating")
            f.addRow("Type:", self.type)
            f.addRow("Size:", self.size)
            f.addRow("Basic load rating:", self.rating)
            lay.addWidget(box)
            box = QtWidgets.QGroupBox("Input")
            f = QtWidgets.QFormLayout(box)
            self.load = _spin(0.001, 1e9, 1, 1000.0, " N")
            self.load.setObjectName("SWBearing_load")
            self.speed = _spin(0, 1e7, 1, 1500.0, " RPM")
            self.speed.setObjectName("SWBearing_speed")
            self.rel = QtWidgets.QComboBox()
            self.rel.setObjectName("SWBearing_reliability")
            self.rel.addItems(["%d %%" % r for r, _a in RELIABILITY])
            f.addRow("Equivalent load:", self.load)
            f.addRow("Speed:", self.speed)
            f.addRow("Reliability:", self.rel)
            lay.addWidget(box)
            self.out = QtWidgets.QLabel()
            self.out.setObjectName("SWBearing_life")
            lay.addWidget(self.out)
            row = QtWidgets.QHBoxLayout()
            solve = QtWidgets.QPushButton("Solve")
            solve.setObjectName("SWBearing_solve")
            solve.clicked.connect(self.solve)
            done = QtWidgets.QPushButton("Done")
            done.clicked.connect(self.accept)
            row.addStretch(1)
            row.addWidget(solve)
            row.addWidget(done)
            lay.addLayout(row)
            self.type.currentIndexChanged.connect(self._sizes)
            self.size.currentIndexChanged.connect(self._rating)
            self._sizes()

        def _sizes(self, *_):
            self.size.blockSignals(True)
            self.size.clear()
            self.size.addItems(self.T.sizes(self.type.currentData()))
            self.size.blockSignals(False)
            self._rating()

        def spec(self):
            return {"kind": self.type.currentData(), "size": self.size.currentText()}

        def _rating(self, *_):
            C, C0 = self.T.ratings(self.spec())
            self.rating.setText("C %g kN (C0 %g kN)" % (C, C0))

        def solve(self):
            s = self.spec()
            C, _C0 = self.T.ratings(s)
            rel = RELIABILITY[self.rel.currentIndex()][0]
            L, h = bearing_life(C, self.load.value(), self.speed.value() or None, rel,
                                roller=s["kind"] == "cylindrical-roller-bearing")
            self.out.setText("Rating life: %.4g million revolutions%s" % (L, ("\n%.4g hours" % h) if h else ""))
            return L, h

    class Cams(QtWidgets.QDialog):
        ""

        def __init__(self, parent=None):
            super().__init__(parent or Gui.getMainWindow())
            self.setObjectName("SWCams")
            self.setWindowTitle("Cam - Circular")
            lay = QtWidgets.QVBoxLayout(self)
            tabs = QtWidgets.QTabWidget()
            lay.addWidget(tabs, 1)
            setup = QtWidgets.QWidget()
            f = QtWidgets.QFormLayout(setup)
            self.ctype = QtWidgets.QComboBox()
            self.ctype.setObjectName("SWCam_type")
            self.ctype.addItems(list(CAM_TYPES))
            self.follower_type = QtWidgets.QComboBox()
            self.follower_type.setObjectName("SWCam_follower_type")
            self.follower_type.addItems(list(FOLLOWERS))
            self.pivot = _spin(0.1, 10000, 3, 80.0, " mm")
            self.pivot.setObjectName("SWCam_pivot")
            self.arm = _spin(0.1, 10000, 3, 60.0, " mm")
            self.arm.setObjectName("SWCam_arm")
            self.follower = _spin(0.1, 1000, 3, 10.0, " mm")
            self.follower.setObjectName("SWCam_follower")
            self.start = _spin(0.1, 10000, 3, 40.0, " mm")
            self.start.setObjectName("SWCam_start")
            self.start_angle = _spin(-360, 360, 2, 0.0, " deg")
            self.direction = QtWidgets.QComboBox()
            self.direction.setObjectName("SWCam_direction")
            self.direction.addItems(["Counterclockwise", "Clockwise"])
            f.addRow("Cam type:", self.ctype)
            f.addRow("Follower type:", self.follower_type)
            f.addRow("Pivot distance:", self.pivot)
            f.addRow("Follower arm length:", self.arm)
            f.addRow("Follower diameter:", self.follower)
            f.addRow("Starting radius:", self.start)
            f.addRow("Starting angle:", self.start_angle)
            f.addRow("Cam rotation direction:", self.direction)
            self.setup_form = f
            tabs.addTab(setup, "Setup")
            motion = QtWidgets.QWidget()
            ml = QtWidgets.QVBoxLayout(motion)
            self.table = QtWidgets.QTableWidget(0, 3)
            self.table.setObjectName("SWCam_motion")
            self.table.setHorizontalHeaderLabels(["Motion type", "Ending radius (mm)", "Degree motion"])
            self.table.horizontalHeader().setStretchLastSection(True)
            ml.addWidget(self.table, 1)
            br = QtWidgets.QHBoxLayout()
            for text, fn in (("Add", self.add_row), ("Remove", self.remove_row)):
                b = QtWidgets.QPushButton(text)
                b.setObjectName("SWCam_" + text.lower())
                b.clicked.connect(lambda *_a, fn=fn: fn())
                br.addWidget(b)
            br.addStretch(1)
            self.total = QtWidgets.QLabel()
            self.total.setObjectName("SWCam_total")
            br.addWidget(self.total)
            ml.addLayout(br)
            tabs.addTab(motion, "Motion")
            creation = QtWidgets.QWidget()
            f = QtWidgets.QFormLayout(creation)
            self.thickness = _spin(0.1, 1000, 3, 10.0, " mm")
            self.thickness.setObjectName("SWCam_thickness")
            self.hub_d = _spin(0, 1000, 3, 30.0, " mm")
            self.hub_l = _spin(0, 1000, 3, 10.0, " mm")
            self.bore = _spin(0, 1000, 3, 12.0, " mm")
            self.bore.setObjectName("SWCam_bore")
            f.addRow("Blank thickness:", self.thickness)
            f.addRow("Near hub diameter:", self.hub_d)
            f.addRow("Near hub length:", self.hub_l)
            f.addRow("Bore diameter:", self.bore)
            tabs.addTab(creation, "Creation")
            self.note = QtWidgets.QLabel()
            self.note.setObjectName("SWCam_note")
            self.note.setWordWrap(True)
            lay.addWidget(self.note)
            row = QtWidgets.QHBoxLayout()
            create = QtWidgets.QPushButton("Create")
            create.setObjectName("SWCam_create")
            create.clicked.connect(self.create)
            done = QtWidgets.QPushButton("Done")
            done.clicked.connect(self.accept)
            row.addStretch(1)
            row.addWidget(create)
            row.addWidget(done)
            lay.addLayout(row)
            for m, e, d in (("Harmonic", 55.0, 120.0), ("Dwell", 55.0, 60.0), ("Cycloidal", 40.0, 120.0),
                            ("Dwell", 40.0, 60.0)):
                self.add_row(m, e, d)
            self.table.itemChanged.connect(lambda *_: self._total())
            self.ctype.currentIndexChanged.connect(lambda *_: self._kind())
            self.follower_type.currentIndexChanged.connect(lambda *_: self._kind())
            self._kind()

        def _kind(self):
            ""
            linear = self.ctype.currentText() == "Linear"
            self.setWindowTitle("Cam - " + self.ctype.currentText())
            model = self.follower_type.model()
            for i in (1, 2):                   # a linear cam drives a translating follower
                model.item(i).setEnabled(not linear)
            if linear and self.follower_type.currentIndex():
                self.follower_type.setCurrentIndex(0)
            swing = not linear and self.follower_type.currentIndex() > 0
            f = self.setup_form
            for w in (self.pivot, self.arm):
                f.labelForField(w).setVisible(swing)
                w.setVisible(swing)
            for w in (self.start_angle, self.direction, self.hub_d, self.hub_l, self.bore):
                if f.labelForField(w) is not None:
                    f.labelForField(w).setVisible(not linear)
                elif w.parentWidget() is not None and w.parentWidget().layout() is not None:
                    lab = w.parentWidget().layout().labelForField(w)
                    if lab is not None:
                        lab.setVisible(not linear)
                w.setVisible(not linear)
            f.labelForField(self.start).setText("Starting height:" if linear else "Starting radius:")
            self.table.setHorizontalHeaderLabels(["Motion type", "Ending height (mm)" if linear else "Ending radius (mm)",
                                                  "Distance motion (mm)" if linear else "Degree motion"])
            self._total()

        def add_row(self, motion="Dwell", end=None, deg=0.0):
            r = self.table.rowCount()
            self.table.insertRow(r)
            c = QtWidgets.QComboBox()
            c.addItems(MOTIONS)
            c.setCurrentText(motion)
            self.table.setCellWidget(r, 0, c)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem("%g" % (end if end is not None else self.start.value())))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem("%g" % deg))
            self._total()
            return r

        def remove_row(self):
            r = self.table.currentRow()
            if r < 0:
                r = self.table.rowCount() - 1
            if r >= 0:
                self.table.removeRow(r)
            self._total()

        def rows(self):
            out = []
            for r in range(self.table.rowCount()):
                m = self.table.cellWidget(r, 0).currentText()
                try:
                    e = float(self.table.item(r, 1).text())
                    d = float(self.table.item(r, 2).text())
                except (AttributeError, ValueError):
                    raise ValueError("Row %d: type numbers for the ending radius and the degrees." % (r + 1))
                out.append((m, e, d))
            return out

        def _total(self):
            try:
                unit = "mm" if self.ctype.currentText() == "Linear" else "deg"
                self.total.setText("Total: %g %s" % (sum(d for _m, _e, d in self.rows()), unit))
            except Exception:
                self.total.setText("")

        def specs(self):
            setup = {"follower": self.follower.value(), "start": self.start.value(),
                     "start_angle": self.start_angle.value(), "clockwise": self.direction.currentIndex() == 1,
                     "type": self.ctype.currentText(), "follower_type": self.follower_type.currentText(),
                     "pivot": self.pivot.value(), "arm": self.arm.value()}
            creation = {"thickness": self.thickness.value(), "hub_d": self.hub_d.value(), "hub_l": self.hub_l.value(),
                        "bore": self.bore.value()}
            return setup, self.rows(), creation

        def create(self):
            try:
                setup, rows, creation = self.specs()
                body = make_cam(setup, rows, creation)
            except Exception as error:
                self.note.setText(str(error))
                return None
            self.note.setText("Cam made: %s" % body.Document.Label)
            self.made = body
            return body

    class Grooves(QtWidgets.QDialog):
        ""

        def __init__(self, parent=None):
            super().__init__(parent or Gui.getMainWindow())
            self.setObjectName("SWGrooves")
            self.setWindowTitle("Grooves")
            self.face = self.end = None
            lay = QtWidgets.QVBoxLayout(self)
            f = QtWidgets.QFormLayout()
            self.gtype = QtWidgets.QComboBox()
            self.gtype.setObjectName("SWGroove_type")
            self.gtype.addItems(GROOVE_TYPES)
            self.face_label = QtWidgets.QLabel("Pick a cylindrical face, then Use Selection.")
            self.face_label.setObjectName("SWGroove_face")
            use = QtWidgets.QPushButton("Use Selection")
            use.setObjectName("SWGroove_use")
            use.clicked.connect(self.use_selection)
            self.size = QtWidgets.QComboBox()
            self.size.setObjectName("SWGroove_size")
            self.distance = _spin(0, 10000, 3, 2.0, " mm")
            self.distance.setObjectName("SWGroove_distance")
            self.dims = QtWidgets.QLabel()
            self.dims.setObjectName("SWGroove_dims")
            f.addRow("Groove type:", self.gtype)
            f.addRow(use, self.face_label)
            f.addRow("Available sizes:", self.size)
            f.addRow("Distance from end face:", self.distance)
            f.addRow("", self.dims)
            lay.addLayout(f)
            self.note = QtWidgets.QLabel()
            self.note.setWordWrap(True)
            self.note.setObjectName("SWGroove_note")
            lay.addWidget(self.note)
            row = QtWidgets.QHBoxLayout()
            create = QtWidgets.QPushButton("Create")
            create.setObjectName("SWGroove_create")
            create.clicked.connect(self.create)
            done = QtWidgets.QPushButton("Done")
            done.clicked.connect(self.accept)
            row.addStretch(1)
            row.addWidget(create)
            row.addWidget(done)
            lay.addLayout(row)
            self.gtype.currentIndexChanged.connect(lambda *_: self._sizes())
            self.size.currentIndexChanged.connect(lambda *_: self._dims())
            self.use_selection()

        def use_selection(self, sel=None):
            sel = Gui.Selection.getSelectionEx() if sel is None else sel
            self.face = self.end = None
            for s in sel:
                for n in s.SubElementNames:
                    if not n.startswith("Face"):
                        continue
                    f = s.Object.Shape.getElement(n)
                    if f.Surface.TypeId == "Part::GeomCylinder" and self.face is None:
                        self.face = (s.Object, n)
                    elif f.Surface.TypeId == "Part::GeomPlane" and self.end is None:
                        self.end = (s.Object, n)
            if self.face is None:
                self.face_label.setText("Pick a cylindrical face, then Use Selection.")
            else:
                try:
                    _c, _a, r, shaft, _f = groove_face(*self.face)
                    self.face_label.setText("%s %s: %s, diameter %g mm%s" % (
                        self.face[0].Label, self.face[1], "shaft" if shaft else "bore", 2 * r,
                        (", from %s" % self.end[1]) if self.end else ""))
                    want = 0 if shaft else 1
                    if ("external" in self.gtype.currentText()) != shaft:
                        self.gtype.setCurrentIndex(want if self.gtype.currentIndex() < 2 else want + 2)
                except Exception as error:
                    self.face_label.setText(str(error))
            self._sizes()

        def _sizes(self):
            self.size.blockSignals(True)
            self.size.clear()
            self.rows = []
            if self.face is not None:
                try:
                    _c, _a, r, _s, _f = groove_face(*self.face)
                    self.rows = groove_sizes(self.gtype.currentText(), 2 * r)
                except Exception as _fw_err:
                    _fw_log("toolboxtools.py:gsizes", _fw_err)
            self.size.addItems([r[0] for r in self.rows])
            self.size.blockSignals(False)
            self._dims()

        def _dims(self):
            row = next((r for r in self.rows if r[0] == self.size.currentText()), None)
            self.dims.setText("Groove diameter %.3g mm, width %.3g mm" % (row[1], row[2]) if row else "")

        def create(self):
            if self.face is None:
                self.note.setText("Pick the cylindrical face the groove goes on.")
                return None
            doc = self.face[0].Document
            doc.openTransaction("Grooves")
            try:
                g = make_groove(self.face[0], self.face[1], self.gtype.currentText(), self.size.currentText() or None,
                                self.distance.value(), self.end)
            except Exception as error:
                doc.abortTransaction()
                self.note.setText(str(error))
                return None
            doc.commitTransaction()
            self.note.setText("%s added." % g.Label)
            self.made = g
            return g

    def _show(box):
        _OPEN[:] = [box]
        box.show()
        return box

    def _configure():
        from . import toolboxconfig
        return toolboxconfig.show(Gui.getMainWindow())

    def _part_open():
        doc = App.ActiveDocument
        if doc is None:
            return False
        try:
            from . import asmcore
            return not asmcore.is_assembly(doc)
        except Exception:
            return True

    class _Cmd:
        def __init__(self, text, tip, run, active=None):
            self.text, self.tip, self.run, self.active = text, tip, run, active

        def GetResources(self):
            return {"MenuText": self.text, "ToolTip": self.tip}

        def IsActive(self):
            try:
                return True if self.active is None else bool(self.active())
            except Exception:
                return False

        def Activated(self):
            try:
                return self.run()
            except Exception as error:
                App.Console.PrintError("Toolbox: %s\n" % error)

    COMMANDS = (
        ("SWStyle_BeamCalculator", "Beam Calculator...", "Deflection and stress of a beam for the usual load cases.",
         lambda: _show(BeamCalculator()), None),
        ("SWStyle_BearingCalculator", "Bearing Calculator...", "The rating life of a bearing.",
         lambda: _show(BearingCalculator()), None),
        ("SWStyle_Cams", "Cams...", "Makes a circular plate cam from a motion table.", lambda: _show(Cams()), None),
        ("SWStyle_Grooves", "Grooves...", "O-ring and retaining ring grooves on a cylindrical face of the part.",
         lambda: _show(Grooves()), _part_open),
        ("SWStyle_StructuralSteel", "Structural Steel...", "A standard steel section's sketch and its section properties.",
         lambda: _show(StructuralSteel()), _part_open),
        ("SWStyle_ToolboxConfigure", "Configure...", "Toolbox Settings: sizes, Smart Fasteners, permissions.",
         _configure, None),
    )



def register():
    """The Toolbox commands, and the Toolbox parts (bearings, rings, keys, bushings) in the Design Library."""
    try:
        from . import toolboxparts
        toolboxparts.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Toolbox parts: %s\n" % error)
    if Gui is None:
        return
    have = Gui.listCommands()
    for name, text, tip, run, active in COMMANDS:
        if name not in have:
            Gui.addCommand(name, _Cmd(text, tip, run, active))
