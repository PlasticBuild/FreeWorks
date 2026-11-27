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

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import naming, smedgegeom, smunfold
from .smbaseflange import _box, _spin
from .smedgeflange import _radio, error_label
from .smunfold import _DeleteKey, _icon, _kfactor, _list, _sheet_body, bends_of, inside_point, probe

COMMAND = "SWStyle_SMCornerRelief"
TITLE = "Corner Relief"
GROUP = "Corner Relief"
TYPES = ("Rectangular", "Circular", "Tear", "Obround", "Constant Width", "Full Round", "Suitcase")
LISTED = TYPES[:5]
SIZE = 0.75
THREE_TYPES = ("Rectangular", "Circular", "Tear", "Full Round", "Suitcase")   # the 3 Bend Corner reliefs
SUITCASE = ("Default Suitcase", "Extend the gap into the bend area", "Fill in some gap")   # its options
SUITCASE_DEPTH = 0.5            # Default Suitcase: half a middle-bend width deep; Extend / Fill add / take the Distance
SCOPES = ("2 Bend Corner", "3 Bend Corner")
SIZED = ("Rectangular", "Circular", "Obround")         # the types with a size, centring and ratio
TEAR_WIDTH = 0.01
TEAR_NECK, TEAR_REACH, TEAR_DEPTH = 0.3, 0.65, 0.6     # 3 Bend Tear swallowtail, in half middle-bend widths
OPTIONS = ("ReliefType", "CenteredOnBendLines", "RelativeToThickness", "Ratio", "Size", "TangentToBend",
           "AddFilletCorners", "FilletRadius", "SlotWidth", "SuitcaseOption")   # what each corner can have its own of
V = App.Vector

MESSAGE = "Create corner relief by selecting sheet metal body and collect all corners or manually define corner"
PICK_TWO = "Select two bend faces for new corner"
PICK_THREE = "Select three bend faces for new corner"
NO_CORNER = "Unable to create a new corner"
NO_THREE = NO_CORNER
NO_CORNERS = "Unable to identify corners."
TOO_MANY = "Only %d faces are allowed for a new corner"
FAILED = "Unable to create a corner relief feature as specified."
NO_FACES = PICK_TWO
SIZE_NAMES = {"Circular": "Circle Size", "Rectangular": "Rectangle Size", "Obround": "Slot Length"}


# ================================================================ geometry
def corners(shape):
    """Every corner where two bends start from the same flat face: [(face, bend a, bend b, corner point)]."""
    bends = bends_of(shape)
    found = {}
    for f in shape.Faces:
        if f.Surface.TypeId != "Part::GeomPlane":
            continue
        lines = []
        for e in f.Edges:
            if e.Curve.TypeId != "Part::GeomLine":
                continue
            for g in shape.ancestorsOfType(e, Part.Face):
                if g.Surface.TypeId != "Part::GeomCylinder":
                    continue
                for k, (inner, outer) in enumerate(bends):
                    if any(g.isSame(x) for x in inner + outer):
                        lines.append((k, e))
        for i in range(len(lines)):
            for j in range(i + 1, len(lines)):
                (ka, ea), (kb, eb) = lines[i], lines[j]
                if ka == kb or (min(ka, kb), max(ka, kb)) in found:
                    continue
                if abs(ea.tangentAt(ea.FirstParameter).dot(eb.tangentAt(eb.FirstParameter))) > 0.999:
                    continue
                la = Part.Line(ea.Vertexes[0].Point, ea.Vertexes[-1].Point)
                lb = Part.Line(eb.Vertexes[0].Point, eb.Vertexes[-1].Point)
                hit = la.intersect(lb)
                if not hit:
                    continue
                p = V(hit[0].X, hit[0].Y, hit[0].Z)
                reach = 3 * (bends[ka][1][0].Surface.Radius + 1)
                if ea.distToShape(Part.Vertex(p))[0] > reach or eb.distToShape(Part.Vertex(p))[0] > reach:
                    continue
                found[(min(ka, kb), max(ka, kb))] = (f, ka, kb, p)
    return list(found.values())


def three_corners(shape):
    """Every corner where three bends meet: a middle bend k whose end meets bend a, on one side, and bend b,
    on the other. [(face of a, a, k, b, corner point, face of b)]; the point is halfway between the two
    bend-line crossings."""
    found = []
    bends = bends_of(shape)
    cs = corners(shape)
    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            (f1, a1, b1, p1), (f2, a2, b2, p2) = cs[i], cs[j]
            shared = {a1, b1} & {a2, b2}
            if len(shared) != 1 or f1.isSame(f2):
                continue
            k = shared.pop()
            a, b = (b1 if a1 == k else a1), (b2 if a2 == k else a2)
            reach = 2 * (bends[k][1][0].Surface.Radius + 1)
            if (p1 - p2).Length > reach:
                continue
            found.append((f1, a, k, b, (p1 + p2) * 0.5, f2))
    return found


def two_corners(shape):
    """The corners where only two bends meet (those of a 3 Bend Corner are left out)."""
    threes = three_corners(shape)
    inner = {frozenset((c[1], c[2])) for c in threes} | {frozenset((c[2], c[3])) for c in threes}
    return [c for c in corners(shape) if frozenset((c[1], c[2])) not in inner]


def nearest_three(shape, point, reach=None):
    best = None
    for c in three_corners(shape):
        d = (c[4] - point).Length
        if best is None or d < best[0]:
            best = (d, c)
    if best is None or (reach is not None and best[0] > reach):
        return None
    return best[1]


def nearest_corner(shape, point, reach=None, among=None):
    best = None
    for c in (corners(shape) if among is None else among):
        d = (c[3] - point).Length
        if best is None or d < best[0]:
            best = (d, c)
    if best is None or (reach is not None and best[0] > reach):
        return None
    return best[1]


def _solve(rows, rhs):
    m = App.Matrix(rows[0].x, rows[0].y, rows[0].z, 0, rows[1].x, rows[1].y, rows[1].z, 0,
                   rows[2].x, rows[2].y, rows[2].z, 0, 0, 0, 0, 1)
    return m.inverse().multVec(V(*rhs))


def _rounded(pts, r):
    """The closed polygon pts with its corners rounded by r."""
    wire = Part.makePolygon(pts + [pts[0]])
    if r <= 1e-6:
        return Part.Face(wire)
    return Part.Face(Part.Face(wire).makeOffset2D(-r, 0).makeOffset2D(r, 0).OuterWire)


def tool(steps, kind, size, centered=True, tangent=False, fillet=0.0, width=0.0):
    """The relief's cutting body on the flat part (the two bends' steps of an unfold)."""
    a, b = steps[0]["bend"], steps[1]["bend"]
    n = a.e0
    level = (a.C + n * a.Ri).dot(n)
    rows = [a.d0, b.d0, n]
    ua, vb = a.C.dot(a.d0), b.C.dot(b.d0)       # the bend lines on the flat face

    def at(u, v):
        return _solve(rows, [u, v, level])
    if kind in ("Tear", "Constant Width", "Full Round"):
        face = _plain(kind, at, ua, vb, a, b)
        face.translate(n * -a.T)
        return face.extrude(n * (3 * a.T))
    if tangent and kind in ("Rectangular", "Circular"):
        size = max(size, a.L, b.L)
    if centered:
        c = at(ua + a.L / 2, vb + b.L / 2)
    else:
        c = at(ua, vb) + (a.d0 + b.d0) * (size / 2)
    h = size / 2
    if kind == "Circular":
        face = Part.Face(Part.Wire(Part.makeCircle(h, c, n)))
    elif kind == "Obround":
        w = (a.d0 + b.d0).normalize()
        s = n.cross(w).normalize()
        e1, e2 = c + w * h, c - w * h
        r = width / 2 if width > 1e-6 else h
        face = Part.Face(Part.Wire([Part.Arc(e1 + s * r, e1 + w * r, e1 - s * r).toShape(),
                                    Part.makeLine(e1 - s * r, e2 - s * r),
                                    Part.Arc(e2 - s * r, e2 - w * r, e2 + s * r).toShape(),
                                    Part.makeLine(e2 + s * r, e1 + s * r)]))
    else:
        ta, tb = a.ax, b.ax
        pts = [c + ta * h + tb * h, c - ta * h + tb * h, c - ta * h - tb * h, c + ta * h - tb * h]
        face = _rounded(pts, min(fillet, h * 0.999)) if fillet > 0 else Part.Face(Part.makePolygon(pts + [pts[0]]))
    face.translate(n * -a.T)
    return face.extrude(n * (3 * a.T))


def _plain(kind, at, ua, vb, a, b):
    """The flat outline of the reliefs without options, from the bend lines' crossing (ua, vb) into the
    corner where the two bends cross."""
    if kind == "Tear":
        k = TEAR_WIDTH / 2 + 1e-3       # just inside the bend, off the bend line itself
        w = TEAR_WIDTH / 2
        out = None
        for pts in ([at(ua + k - w, vb), at(ua + k + w, vb), at(ua + k + w, vb + b.L), at(ua + k - w, vb + b.L)],
                    [at(ua, vb + k - w), at(ua, vb + k + w), at(ua + a.L, vb + k + w), at(ua + a.L, vb + k - w)]):
            f = Part.Face(Part.makePolygon(pts + [pts[0]]))
            out = f if out is None else out.fuse(f)
        return out.removeSplitter()
    if kind == "Constant Width":
        t = a.T / 2
        p0, p1 = at(ua, vb), at(ua + a.L, vb + b.L)
        d = (p1 - p0).normalize()
        s = a.e0.cross(d).normalize() * t
        p0, p1 = p0 - d * t, p1 + d * t
        return Part.Face(Part.makePolygon([p0 + s, p1 + s, p1 - s, p0 - s, p0 + s]))
    # Full Round
    r = max(a.L, b.L)
    c = at(ua, vb)
    disc = Part.Face(Part.Wire(Part.makeCircle(r, c, a.e0)))
    pts = [c, at(ua + r, vb), at(ua + r, vb + r), at(ua, vb + r)]
    return disc.common(Part.Face(Part.makePolygon(pts + [pts[0]])))


def tool3(steps, kind, size, tangent=False, fillet=0.0, near=None, suitcase=SUITCASE[0]):
    """The 3 Bend Corner relief's cutting body: centred on the middle bend's end (the end near `near`), halfway
    across its flat strip."""
    k = steps[1]["bend"]
    ends = (k.t0, k.t1)
    t = min(ends, key=lambda x: abs(x - (near - k.C).dot(k.a))) if near is not None else k.t1
    n = k.e0
    c = k.C + k.a * t + n * k.Ri + k.d0 * (k.L / 2)
    u, v = V(k.a).normalize(), V(k.d0).normalize()
    if kind in ("Tear", "Full Round", "Suitcase"):
        out = u * (1 if t == k.t1 else -1)          # from the end, away from the middle bend
        side = max([s["bend"].L for s in steps[:1] + steps[2:]] + [k.L]) + k.T     # across the side bends
        face = _plain3(kind, lambda du, dv: c + out * du + v * dv, k, side, suitcase, size)
    else:
        if tangent:
            size = max(size, k.L)
        h = size / 2
        if kind == "Circular":
            face = Part.Face(Part.Wire(Part.makeCircle(h, c, n)))
        else:
            pts = [c + u * h + v * h, c - u * h + v * h, c - u * h - v * h, c + u * h - v * h]
            face = _rounded(pts, min(fillet, h * 0.999)) if fillet > 0 else Part.Face(Part.makePolygon(pts + [pts[0]]))
    face.translate(n * -k.T)
    return face.extrude(n * (3 * k.T))


def _plain3(kind, at, k, side, suitcase, size=0.0):
    """The flat outline of the 3 Bend Corner reliefs without a size: at(du, dv) is the point du out from the
    middle bend's end (negative: into the middle bend) and dv across it from its middle line."""
    h = k.L / 2
    if kind == "Tear":

        # the middle bend out to its bend lines, with the notch's point at the middle of the bend's end.
        m = h - 1e-3                                # just inside the middle bend's bend lines
        n = TEAR_NECK * h
        pts = [at(side, -n), at(TEAR_REACH * h, -n), at(-TEAR_DEPTH * h, -m), at(0, 0),
               at(-TEAR_DEPTH * h, m), at(TEAR_REACH * h, n), at(side, n)]
        return Part.Face(Part.makePolygon(pts + [pts[0]]))
    if kind == "Full Round":
        return Part.Face(Part.Wire([Part.Arc(at(0, -h), at(-h, 0), at(0, h)).toShape(),
                                    Part.makeLine(at(0, h), at(side, h)), Part.makeLine(at(side, h), at(side, -h)),
                                    Part.makeLine(at(side, -h), at(0, -h))]))
    # Suitcase

    # area goes the Distance deeper, Fill in some gap the Distance less deep.
    i = SUITCASE.index(suitcase) if suitcase in SUITCASE else 0
    depth = SUITCASE_DEPTH * k.L + (0.0, size, -size)[i]
    depth = min(max(depth, 0.05 * k.L), k.L)
    pts = [at(-depth, -h), at(side, -h), at(side, h), at(-depth, h)]
    return Part.Face(Part.makePolygon(pts + [pts[0]]))


def relieve3(shape, corner, kind, size, kfactor, tangent=False, fillet=0.0, suitcase=SUITCASE[0]):
    """shape with a 3 Bend Corner relief cut at corner (from three_corners)."""
    f, ka, kk, kb, _p, _f2 = corner
    bends = bends_of(shape)
    p1 = next(c[3] for c in corners(shape) if {c[1], c[2]} == {ka, kk})
    flat, steps = smunfold.unfold(shape, [probe(*bends[ka]), probe(*bends[kk]), probe(*bends[kb])],
                                  inside_point(f), kfactor)
    cut = flat.cut(tool3(steps, kind, size, tangent, fillet, p1, suitcase))
    return smunfold.fold(shape, flat, cut, steps)


def relieve(shape, corner, kind, size, centered, kfactor, tangent=False, fillet=0.0, width=0.0):
    """shape with a relief cut at corner."""
    f, ka, kb, _p = corner
    bends = bends_of(shape)
    flat, steps = smunfold.unfold(shape, [probe(*bends[ka]), probe(*bends[kb])], inside_point(f), kfactor)
    cut = flat.cut(tool(steps, kind, size, centered, tangent, fillet, width))
    return smunfold.fold(shape, flat, cut, steps)


# ================================================================ feature
_LAST = None        # the open Corner Relief PropertyManager


class SWCornerRelief:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyEnumeration", "Scope", GROUP, "2 Bend Corner or 3 Bend Corner")
        add("App::PropertyVectorList", "Corners", GROUP, "The corner point of each corner")
        add("App::PropertyEnumeration", "ReliefType", GROUP, "Relief type")
        add("App::PropertyBool", "CenteredOnBendLines", GROUP, "Center the relief on the bends' center lines")
        add("App::PropertyBool", "RelativeToThickness", GROUP, "The size is a ratio of the thickness")
        add("App::PropertyFloat", "Ratio", GROUP, "Size / thickness")
        add("App::PropertyLength", "Size", GROUP, "Side length or diameter")
        add("App::PropertyFloat", "KFactor", GROUP, "K-Factor")
        obj.Scope = list(SCOPES)
        obj.ReliefType = list(TYPES)
        obj.ReliefType = "Rectangular"
        obj.CenteredOnBendLines = False
        obj.RelativeToThickness = False
        obj.Ratio = 1.5
        obj.Size = SIZE
        obj.KFactor = 0.5
        _more_props(obj)
        obj.Proxy = self

    def execute(self, obj):
        base = obj.BaseFeature
        if base is None:
            raise ValueError("Corner Relief: needs a sheet metal part")
        shape, kept = smedgegeom.corner_base(base)
        trimmed = shape
        _more_props(obj)
        three = obj.Scope == "3 Bend Corner"
        for i, p in enumerate(obj.Corners):
            corner = nearest_three(shape, p, reach=1e-3) if three else nearest_corner(shape, p, reach=1e-3)
            if corner is None:
                raise ValueError("Corner Relief: a corner is gone; edit the feature and pick it again")
            o = corner_options(obj, i)
            size = o["Ratio"] * thickness(shape, corner) if o["RelativeToThickness"] else o["Size"]
            fillet = o["FilletRadius"] if o["AddFilletCorners"] else 0.0
            if three:
                kind = o["ReliefType"] if o["ReliefType"] in THREE_TYPES else "Rectangular"
                shape = relieve3(shape, corner, kind, size, obj.KFactor, o["TangentToBend"], fillet,
                                 o["SuitcaseOption"])
                continue
            shape = relieve(shape, corner, o["ReliefType"], size, o["CenteredOnBendLines"], obj.KFactor,
                            o["TangentToBend"], fillet, o["SlotWidth"])
        obj.Shape = smedgegeom.corner_result(obj, trimmed, shape, kept)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _more_props(obj):
    """Tangent to bend, Add fillet corners, the Obround's slot width and the Suitcase option (older reliefs had
    none), and the type list with Suitcase."""
    for name, kind, tip, default in (
            ("TangentToBend", "App::PropertyBool", "The relief reaches at least the far bend lines", False),
            ("AddFilletCorners", "App::PropertyBool", "Rounds the rectangular relief's corners", False),
            ("FilletRadius", "App::PropertyLength", "Fillet radius of the corners", 1.0),
            ("SlotWidth", "App::PropertyLength", "Obround slot width (0 = the slot length)", 0.0),
            ("CornerOptions", "App::PropertyStringList", "Each corner's own relief options (JSON)", []),
            ("SuitcaseOption", "App::PropertyString", "Suitcase: " + " / ".join(SUITCASE), SUITCASE[0])):
        if name not in obj.PropertiesList:
            obj.addProperty(kind, name, GROUP, tip)
            setattr(obj, name, default)
    if "ReliefType" in obj.PropertiesList and list(obj.getEnumerationsOfProperty("ReliefType")) != list(TYPES):
        current = obj.ReliefType            # reliefs made before Suitcase was listed
        obj.ReliefType = list(TYPES)
        obj.ReliefType = current


def _value(v):
    return float(v.Value) if hasattr(v, "Value") else v


def feature_options(obj):
    """The feature's relief options: what a corner has unless it has its own."""
    return {k: _value(getattr(obj, k)) for k in OPTIONS}


def corner_options(obj, i):
    out = feature_options(obj)
    own = list(getattr(obj, "CornerOptions", []))
    if i < len(own):
        try:
            out.update({k: v for k, v in json.loads(own[i]).items() if k in OPTIONS})
        except ValueError as _fw_err:
            _fw_log("smcornerrelief.py:426", _fw_err)
    return out


def set_corners(obj, points, options=None):
    """obj's corners: points, each keeping the options it had (a new one takes the feature's)."""
    old = [(p, corner_options(obj, i)) for i, p in enumerate(obj.Corners)]
    opts = []
    for j, p in enumerate(points):
        o = options[j] if options is not None else next((q for r, q in old if (r - p).Length < 1e-3),
                                                         feature_options(obj))
        opts.append(json.dumps(o, sort_keys=True))
    obj.Corners = list(points)
    obj.CornerOptions = opts


def thickness(shape, corner):
    inner, outer = bends_of(shape)[corner[1]]
    return outer[0].Surface.Radius - (inner[0].Surface.Radius if inner else 0.0)


def is_corner_relief(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWCornerRelief"


class ViewProviderCornerRelief:
    ICON = "SheetMetal_AddCornerRelief"

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
    base = body.Tip
    obj = doc.addObject("PartDesign::FeaturePython", "CornerRelief")
    SWCornerRelief(obj)
    if App.GuiUp:
        ViewProviderCornerRelief(obj.ViewObject)
    body.addObject(obj)
    obj.Label = naming.next_label(doc, "Corner Relief")
    obj.KFactor = _kfactor(body)
    if base is not None:
        try:
            base.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("smcornerrelief.py:499", _fw_err)
    return obj


def _corner_name(i, kind=None):
    return "Corner%d" % (i + 1) + (" [%s]" % kind if kind else "")


# ================================================================ PropertyManager
class Panel:
    """The Corner Relief PropertyManager."""
    HINT = PICK_TWO
    HINT3 = PICK_THREE

    def __init__(self, obj, new):
        global _LAST
        _LAST = self
        self.obj = obj
        self.new = new
        message = _box("Message")
        self.message = QtWidgets.QLabel(MESSAGE)
        self.message.setObjectName("SWSMReliefMessage")
        self.message.setWordWrap(True)
        message.layout().addRow(self.message)
        message.setProperty("swstyle_pm_title", TITLE)
        message.setProperty("swstyle_pm_icon", "SheetMetal_AddCornerRelief")
        kind_box = _box("Corner Type")
        row = QtWidgets.QHBoxLayout()
        self.two = _radio("SWSMReliefTwoBend", "2 Bend Corner")
        self.three = _radio("SWSMReliefThreeBend", "3 Bend Corner")
        (self.three if obj.Scope == "3 Bend Corner" else self.two).setChecked(True)
        row.addWidget(self.two)
        row.addWidget(self.three)
        for w in (self.two, self.three):
            w.setEnabled(bool(new))
        kind_box.layout().addRow(row)
        scope = _box("Scope")
        f = scope.layout()
        self.body = _list("SWSMReliefBody", "#d6ecff", "Select sheet metal body to apply corner relief")
        f.addRow(self.body)
        f.addRow(QtWidgets.QLabel("Corners:"))
        self.corners = _list("SWSMReliefCorners", "#ffd6ec", "Select a corner to set or change relief type.", rows=3)
        f.addRow(self.corners)
        self.collect = QtWidgets.QPushButton("Collect all corners")
        self.collect.setObjectName("SWSMReliefCollect")
        self.collect.setToolTip("Collect all corners on sheet metal body")
        self.collect.clicked.connect(self.collect_all)
        f.addRow(self.collect)
        self.error = error_label()
        f.addRow(self.error)
        define = _box("Define Corner")
        d = define.layout()

        self.face_list = _list("SWSMReliefFaces", "#d6ecff", PICK_TWO, rows=3)
        from . import pmboxes
        pmboxes.mark(self.body, False)      # the body fills itself; the picks go to the faces box (one pink box)
        self.body.setProperty("swFixedScope", True)   # the relief lives in this body: it shows, it is not a pick
        d.addRow(self.face_list)
        self.new_button = QtWidgets.QPushButton("New Corner")
        self.new_button.setObjectName("SWSMReliefNewCorner")
        self.new_button.setToolTip("Create New Corner")
        self.new_button.clicked.connect(self.new_corner)
        d.addRow(self.new_button)
        self.faces = []             # [(doc, object, sub, point)] for Face<1>, Face<2> (and Face<3>)
        options = _box("Relief Options")
        g = options.layout()
        self.kind = QtWidgets.QComboBox()
        self.kind.setObjectName("SWSMReliefType")
        self.kind.setToolTip("Relief type")
        g.addRow(self.kind)
        _more_props(obj)
        self.suitcase_row = QtWidgets.QWidget()
        self.suitcase_row.setObjectName("SWSMReliefSuitcaseOptions")
        row = QtWidgets.QHBoxLayout(self.suitcase_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.suitcase = QtWidgets.QButtonGroup(self.suitcase_row)
        self.suitcase.setExclusive(True)
        for i, (name, text) in enumerate(zip(("Default", "Extend", "Fill"), SUITCASE)):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWSMReliefSuitcase" + name)
            b.setText(("Default", "Extend gap", "Fill gap")[i])
            b.setToolTip(text)
            b.setCheckable(True)
            b.setAutoRaise(False)
            self.suitcase.addButton(b, i)
            row.addWidget(b)
        row.addStretch(1)
        self._set_suitcase(obj.SuitcaseOption)
        g.addRow(self.suitcase_row)
        self.centered = QtWidgets.QCheckBox("Centered on bend lines")
        self.centered.setObjectName("SWSMReliefCentered")
        g.addRow(self.centered)
        self.relative = QtWidgets.QCheckBox("Ratio to thickness")
        self.relative.setObjectName("SWSMReliefRelative")
        g.addRow(self.relative)
        self.ratio = _spin("SWSMReliefRatio", obj.Ratio, 0.01, 100.0, suffix="", step=0.1)
        self.ratio.setToolTip("Ratio")
        g.addRow("Ratio:", self.ratio)
        self.size = _spin("SWSMReliefSize", float(obj.Size), 0.01, 1000.0)
        self.size.setToolTip("Rectangle Size")
        self.size_label = QtWidgets.QLabel("Size:")
        g.addRow(self.size_label, self.size)
        self.width = _spin("SWSMReliefSlotWidth", float(obj.SlotWidth), 0.0, 1000.0)
        self.width.setToolTip("Slot Width")
        self.width_label = QtWidgets.QLabel("Slot width:")
        g.addRow(self.width_label, self.width)
        self.tangent = QtWidgets.QCheckBox("Tangent to bend")
        self.tangent.setObjectName("SWSMReliefTangent")
        self.tangent.setChecked(bool(obj.TangentToBend))
        g.addRow(self.tangent)
        self.fillet = QtWidgets.QCheckBox("Add filleted corners")
        self.fillet.setObjectName("SWSMReliefFillet")
        self.fillet.setChecked(bool(obj.AddFilletCorners))
        g.addRow(self.fillet)
        self.radius = _spin("SWSMReliefFilletRadius", float(obj.FilletRadius), 0.01, 1000.0)
        self.radius.setToolTip("Corner Fillets")
        self.radius_label = QtWidgets.QLabel("Fillet radius:")
        g.addRow(self.radius_label, self.radius)
        self.form = [message, kind_box, scope, define, options]
        self._types(obj.ReliefType)
        self.centered.setChecked(bool(obj.CenteredOnBendLines))
        self.relative.setChecked(bool(obj.RelativeToThickness))
        self._enable()
        self.kind.currentIndexChanged.connect(self._changed)
        for w in (self.centered, self.relative, self.tangent, self.fillet):
            w.toggled.connect(self._changed)
        self.three.toggled.connect(self._scope)
        for w in (self.ratio, self.size, self.width, self.radius):
            w.valueChanged.connect(self._changed)
        self.suitcase.buttonClicked.connect(self._changed)
        self.keys = _DeleteKey(self)
        for w in (self.corners, self.face_list):
            w.installEventFilter(self.keys)
        self.corners.itemSelectionChanged.connect(self._row)
        self._fill_body()
        self._fill()
        self._report()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def set_active(self, w):
        pass

    def kind_now(self):
        return self.kind.currentText() or "Rectangular"

    def suitcase_now(self):
        i = self.suitcase.checkedId()
        return SUITCASE[i] if 0 <= i < len(SUITCASE) else SUITCASE[0]

    def _set_suitcase(self, option):
        i = SUITCASE.index(option) if option in SUITCASE else 0
        self.suitcase.button(i).setChecked(True)

    def _types(self, current):
        ""

        listed = list(THREE_TYPES if self.is_three() else LISTED)
        if current == "Full Round" and not self.is_three():
            listed.append(current)
        self.kind.blockSignals(True)
        self.kind.clear()
        self.kind.addItems(listed)
        self.kind.setCurrentIndex(listed.index(current) if current in listed else 0)
        self.kind.blockSignals(False)

    def remove_current(self, w):
        if w is self.face_list:
            i = w.currentRow()
            if 0 <= i < len(self.faces):
                del self.faces[i]
            self._show_faces()
            return
        row = self.corners.currentRow()
        if row < 0:
            return
        pts = list(self.obj.Corners)
        del pts[row]
        set_corners(self.obj, pts)
        self.corners.clearSelection()
        self._apply()

    def _fill(self):
        row = self.selected()
        self.corners.blockSignals(True)
        self.corners.clear()
        for i in range(len(self.obj.Corners)):
            self.corners.addItem(_corner_name(i, corner_options(self.obj, i)["ReliefType"]))
        if row is not None and row < self.corners.count():
            self.corners.setCurrentRow(row)
        self.corners.blockSignals(False)

    def selected(self):
        """The corner selected in the list, or None (then Relief Options are every corner's)."""
        items = self.corners.selectedItems()
        return self.corners.row(items[0]) if items else None

    def _row(self):
        """A corner selected (or none): Relief Options show its options."""
        row = self.selected()
        o = corner_options(self.obj, row) if row is not None else feature_options(self.obj)
        self._show(o)

    def _show(self, o):
        widgets = (self.kind, self.centered, self.relative, self.ratio, self.size, self.tangent, self.fillet,
                   self.radius, self.width, self.suitcase)
        for w in widgets:
            w.blockSignals(True)
        self._types(o["ReliefType"])
        self.centered.setChecked(bool(o["CenteredOnBendLines"]))
        self.relative.setChecked(bool(o["RelativeToThickness"]))
        self.ratio.setValue(o["Ratio"])
        self.size.setValue(o["Size"])
        self.tangent.setChecked(bool(o["TangentToBend"]))
        self.fillet.setChecked(bool(o["AddFilletCorners"]))
        self.radius.setValue(o["FilletRadius"])
        self.width.setValue(o["SlotWidth"])
        self._set_suitcase(o.get("SuitcaseOption", SUITCASE[0]))
        for w in widgets:
            w.blockSignals(False)
        self._enable()

    def is_three(self):
        return self.three.isChecked()

    def _scope(self, *_a):
        """Switching between 2 and 3 Bend Corner: the corners are different ones, so the list starts again."""
        self.obj.Scope = SCOPES[1] if self.is_three() else SCOPES[0]
        set_corners(self.obj, [])
        self.faces = []
        self._show_faces()
        self._types(self.obj.ReliefType)
        self.obj.ReliefType = self.kind_now()
        self._enable()
        self._apply()

    def _enable(self):
        kind = self.kind_now()
        sized = kind in SIZED
        three = self.is_three()

        self.centered.setVisible(sized)
        self.centered.setEnabled(not three)
        if three:
            self.centered.blockSignals(True)
            self.centered.setChecked(kind == "Circular")
            self.centered.blockSignals(False)
        self.relative.setVisible(sized)
        self.ratio.setEnabled(self.relative.isChecked())
        self.size.setEnabled(not self.relative.isChecked())
        for w in (self.ratio, self.size):
            w.setVisible(sized)
            label = w.parentWidget().layout().labelForField(w) if w.parentWidget() else None
            if label is not None:
                label.setVisible(sized)
        name = SIZE_NAMES.get(kind, "Rectangle Size")
        self.size.setToolTip(name)
        self.size_label.setText(name + ":")
        self.face_list.setToolTip(PICK_THREE if three else PICK_TWO)
        self.tangent.setVisible(kind in ("Rectangular", "Circular"))
        self.tangent.setEnabled(not three)
        for w in (self.width, self.width_label):
            w.setVisible(kind == "Obround")
        self.suitcase_row.setVisible(kind == "Suitcase")
        if kind == "Suitcase":      # Extend the gap / Fill in some gap: one distance box; Default Suitcase: none
            deep = self.suitcase_now() != SUITCASE[0]
            self.size.setVisible(deep)
            self.size.setEnabled(True)
            self.size_label.setVisible(deep)
            self.size.setToolTip("Distance")
            self.size_label.setText("Distance:")
        self.fillet.setVisible(kind == "Rectangular")
        for w in (self.radius, self.radius_label):
            w.setVisible(kind == "Rectangular" and self.fillet.isChecked())

    # ---------------------------------------------------------------- picks
    def collect_all(self):
        shape = smedgegeom.trimmed_shape(self.obj.BaseFeature)
        found = [c[4] for c in three_corners(shape)] if self.is_three() else [c[3] for c in two_corners(shape)]
        set_corners(self.obj, found)
        self._apply()
        if not found:
            self.error.setText(NO_CORNERS)
            self.error.show()

    def _fill_body(self):
        """Scope: the sheet metal body the relief goes on."""
        self.body.clear()
        base = self.obj.BaseFeature
        body = next((o for o in self.obj.InList if o.TypeId == "PartDesign::Body"), None)
        if base is not None:
            self.body.addItem(body.Label if body is not None else base.Label)

    def addSelection(self, doc, name, sub, point):
        if sub.startswith(("Face", "Edge", "Vertex")):
            at = App.Vector(*point) if point else None
            QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub, at))

    def _picked(self, doc_name, name, sub, at):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smcornerrelief.py:801", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None or picked.Shape.isNull():
            return
        if at is None:
            element = picked.Shape.getElement(sub)
            at = element.CenterOfMass
        pick = (doc_name, name, sub, at)
        hit = next((i for i, q in enumerate(self.faces) if q[1:3] == pick[1:3]), None)
        most = 3 if self.is_three() else 2
        if hit is not None:         # picked again: take it out
            del self.faces[hit]
        elif len(self.faces) < most:
            self.faces.append(pick)
        else:
            self.error.setText(TOO_MANY % most)
            self.error.show()
        self._show_faces()

    def _show_faces(self):
        self.face_list.clear()
        for q in self.faces:
            self.face_list.addItem(q[2].replace("Face", "Face<") + ">" if q[2].startswith("Face") else q[2])

    def new_corner(self):
        """New Corner: the corner at the faces in Face<1> and Face<2> joins the list."""
        if not self.faces:
            self.error.setText(PICK_THREE if self.is_three() else PICK_TWO)
            self.error.show()
            return
        at = sum((q[3] for q in self.faces), V()) * (1.0 / len(self.faces))
        shape = smedgegeom.trimmed_shape(self.obj.BaseFeature)
        if self.is_three():
            corner = nearest_three(shape, at)
            point = corner[4] if corner is not None else None
        else:
            corner = nearest_corner(shape, at, among=two_corners(shape))
            point = corner[3] if corner is not None else None
        if corner is None:
            self.error.setText(NO_THREE if self.is_three() else NO_CORNER)
            self.error.show()
            return
        self.faces = []
        self._show_faces()
        pts = list(self.obj.Corners)
        if any((q - point).Length < 1e-3 for q in pts):
            return                  # listed already
        pts.append(point)
        set_corners(self.obj, pts)
        self._apply()

    # ---------------------------------------------------------------- result
    def _changed(self, *_a):
        obj = self.obj
        o = {"ReliefType": self.kind_now(), "CenteredOnBendLines": self.centered.isChecked(),
             "RelativeToThickness": self.relative.isChecked(), "Ratio": self.ratio.value(),
             "Size": self.size.value(), "TangentToBend": self.tangent.isChecked(),
             "AddFilletCorners": self.fillet.isChecked(), "FilletRadius": self.radius.value(),
             "SlotWidth": self.width.value(), "SuitcaseOption": self.suitcase_now()}
        row = self.selected()
        n = len(obj.Corners)
        if row is None:             # what changed goes to every corner, and to the ones added after
            was = feature_options(obj)
            new = {k: v for k, v in o.items() if v != was[k]}
            for k, v in o.items():
                setattr(obj, k, v)
            set_corners(obj, list(obj.Corners), [dict(corner_options(obj, i), **new) for i in range(n)])
        else:                       # the selected corner only
            opts = [corner_options(obj, i) for i in range(n)]
            opts[row] = o
            set_corners(obj, list(obj.Corners), opts)
        self._enable()
        self._apply()

    def _apply(self):
        self.obj.touch()
        self.obj.Document.recompute()
        self._fill()
        self._report()

    def _report(self):
        ""

        if "Invalid" in self.obj.State:
            why = self.obj.getStatusString()
            self.error.setText(FAILED + ("\n" + why if why and why != FAILED else ""))
        else:
            self.error.setText("")
        self.error.setVisible(bool(self.error.text()))
        return not self.error.text() and bool(self.obj.Corners)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smcornerrelief.py:899", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smcornerrelief.py:905", _fw_err)

    def accept(self):
        if not self._report():
            if not self.obj.Corners and not self.error.text():
                self.error.setText(NO_CORNERS)
                self.error.show()
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
                _fw_log("smcornerrelief.py:926", _fw_err)
        self._close()
        return True


# ================================================================ command
def start():
    body = _sheet_body()
    if body is None:
        return
    picked = [(o.Document.Name, o.Object.Name, sub, App.Vector(p)) for o in Gui.Selection.getSelectionEx()
              for sub, p in zip(o.SubElementNames, o.PickedPoints)]
    doc = body.Document
    doc.openTransaction(TITLE)
    try:
        obj = make(body)
        doc.recompute()
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
    if picked:
        panel.new_corner()


class Command:
    def GetResources(self):
        return {"Pixmap": _icon("SheetMetal_AddCornerRelief"), "MenuText": TITLE,
                "ToolTip": "Cuts a relief where two bends meet."}

    def IsActive(self):
        return _sheet_body() is not None

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
