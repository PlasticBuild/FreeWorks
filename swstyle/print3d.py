""


















import math
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import paths

Qt = QtCore.Qt

_SEEN = set()


def _fw_log(site, err):
    if site not in _SEEN:
        _SEEN.add(site)
        try:
            App.Console.PrintLog("FreeCAD print3d %s: %s\n" % (site, err))
        except Exception:
            return


# the same settings as Save As > STL > Options (saveas.py)
STL_RESOLUTION = "STLResolution"
STL_DEVIATION = "STLDeviation"
STL_ANGLE = "STLAngle"
RESOLUTIONS = {"Coarse": (0.5, 30.0), "Fine": (0.05, 10.0)}

P_BED = "Print3DBed"                 # "x,y,z" of Custom size
P_PRINTER = "Print3DPrinter"         # "custom" or a slicer key
P_OVERHANG = "Print3DOverhangAngle"
P_THIN = "Print3DMinThickness"
P_SEND_SOLIDS = "Print3DSendSolids"
P_PROFILES = "Print3DProfiles"       # JSON list of printer profiles (Options > Export > Print3D Printers)
P_SHOW_BED = "Print3DShowBed"

SUPPORT_COLOUR = (0.86, 0.16, 0.16)
THIN_COLOUR = (0.98, 0.70, 0.10)
BOTH_COLOUR = (0.75, 0.10, 0.75)
DOWN = App.Vector(0, 0, -1)


def params():
    return paths.params()


def resolution():
    """(name, deviation mm, angle degrees) of Export Options."""
    p = params()
    name = p.GetString(STL_RESOLUTION, "Fine")
    if name in RESOLUTIONS:
        dev, ang = RESOLUTIONS[name]
    else:
        name = "Custom"
        dev, ang = p.GetFloat(STL_DEVIATION, 0.05), p.GetFloat(STL_ANGLE, 10.0)
    return name, dev, ang


# ---------------------------------------------------------------------- the part
def targets(doc=None):
    """The objects to print (the 3D Slicer's choice: picked bodies, the active body, else every visible solid)."""
    from . import slicer
    try:
        return slicer.printable(doc)
    except Exception as error:
        _fw_log("targets", error)
        return []


def object_shape(obj):
    from . import slicer
    return slicer.object_shape(obj)


def mesh_of(shape, deviation, angle_deg):
    import MeshPart
    return MeshPart.meshFromShape(Shape=shape, LinearDeflection=deviation, AngularDeflection=math.radians(angle_deg),
                                  Relative=False)


def triangles(mesh):
    """numpy (points, facets) of a mesh."""
    import numpy as np
    pts, tris = mesh.Topology
    return np.array([(p.x, p.y, p.z) for p in pts], dtype=float), np.array(tris, dtype=int).reshape(-1, 3)


def rot_matrix(rot):
    import numpy as np
    m = rot.toMatrix()
    return np.array([[m.A11, m.A12, m.A13], [m.A21, m.A22, m.A23], [m.A31, m.A32, m.A33]], dtype=float)


def support_area(pts, tris, rot, threshold):
    """(area needing support mm2, height mm, area on the bed mm2) with the part turned by rot: downward triangles
    flatter than threshold degrees from the horizontal, the ones lying on the bed left out."""
    import numpy as np
    p = pts.dot(rot_matrix(rot).T)
    a, b, c = p[tris[:, 0]], p[tris[:, 1]], p[tris[:, 2]]
    cross = np.cross(b - a, c - a)
    area2 = np.linalg.norm(cross, axis=1)
    ok = area2 > 1e-12
    nz = np.zeros(len(tris))
    nz[ok] = cross[ok, 2] / area2[ok]
    zmin = p[:, 2].min()
    low = np.maximum(np.maximum(a[:, 2], b[:, 2]), c[:, 2]) <= zmin + 0.05
    flat = -nz >= math.cos(math.radians(threshold))
    support = (~low) & flat & (nz < 0)
    bed = low & (nz < -0.999)
    return float(area2[support].sum() / 2), float(p[:, 2].max() - zmin), float(area2[bed].sum() / 2)


def candidates(shape, limit=14):
    """Down directions worth trying: the outward normals of the largest flat faces, and the six axis directions."""
    out = []
    faces = []
    for f in shape.Faces:
        try:
            if f.Surface.__class__.__name__ == "Plane" or "Plane" in str(f.Surface):
                faces.append((f.Area, f))
        except Exception as error:
            _fw_log("candidates", error)
    faces.sort(key=lambda t: -t[0])
    for _a, f in faces[:limit]:
        u0, u1, v0, v1 = f.ParameterRange
        n = f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        out.append(App.Vector(n))
    for v in ((0, 0, -1), (0, 0, 1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)):
        out.append(App.Vector(*v))
    uniq = []
    for n in out:
        if n.Length < 1e-9:
            continue
        n = App.Vector(n).normalize()
        if not any((n - m).Length < 1e-3 for m in uniq):
            uniq.append(n)
    return uniq


def rotation_down(normal):
    """The turn that puts a face with this outward normal on the bed."""
    n = App.Vector(normal)
    if n.Length < 1e-9:
        return App.Rotation()
    n.normalize()
    if (n - DOWN).Length < 1e-9:
        return App.Rotation()
    if (n + DOWN).Length < 1e-9:
        return App.Rotation(App.Vector(1, 0, 0), 180)
    return App.Rotation(n, DOWN)


def suggest(shape, threshold=45.0, count=4):
    """The best orientations: [{"normal", "rotation", "support", "height", "contact"}], least support first (then
    the most area on the bed, then the lowest), as the slicers' auto orient."""
    mesh = mesh_of(shape, max(0.2, 0.01 * shape.BoundBox.DiagonalLength), 20.0)
    pts, tris = triangles(mesh)
    rows = []
    for n in candidates(shape):
        rot = rotation_down(n)
        s, h, c = support_area(pts, tris, rot, threshold)
        rows.append({"normal": n, "rotation": rot, "support": s, "height": h, "contact": c})
    rows.sort(key=lambda r: (round(r["support"], 0), -round(r["contact"], 0), round(r["height"], 1)))
    return rows[:count]


def describe(normal):
    names = {(0, 0, -1): "As modelled (bottom down)", (0, 0, 1): "Top down", (1, 0, 0): "Right side down",
             (-1, 0, 0): "Left side down", (0, 1, 0): "Back down", (0, -1, 0): "Front down"}
    key = tuple(int(round(c)) if abs(abs(c) - round(abs(c))) < 1e-6 else None for c in (normal.x, normal.y, normal.z))
    return names.get(key, "Face (%.2f, %.2f, %.2f) down" % (normal.x, normal.y, normal.z))


def posed(shapes, rotation, scale, bed=None):
    """The shapes turned, scaled and set on the bed together (their middle at the bed's middle, the lowest on z 0)."""
    m = App.Matrix()
    m.scale(scale, scale, scale)
    m = rotation.toMatrix().multiply(m)
    out = [s.transformGeometry(m) if abs(scale - 1.0) > 1e-9 else s.transformed(m) for s in shapes]
    box = None
    for s in out:
        box = App.BoundBox(s.BoundBox) if box is None else box.united(s.BoundBox)
    cx, cy = (bed[0] / 2.0, bed[1] / 2.0) if bed else (0.0, 0.0)
    shift = App.Vector(cx - box.Center.x, cy - box.Center.y, -box.ZMin)
    return [s.translated(shift) for s in out], m, shift


def pieces_needed(size, bed, margin=2.0):
    """How many pieces along each axis so that every piece fits the bed (with a margin, mm)."""
    return [max(1, int(math.ceil(size[i] / max(1.0, bed[i] - margin)))) for i in range(3)]


def split(shapes, counts):
    """Cut posed shapes on a grid: [(name, piece)] where every piece fits within its grid cell."""
    import Part
    box = None
    for s in shapes:
        box = App.BoundBox(s.BoundBox) if box is None else box.united(s.BoundBox)
    nx, ny, nz = counts
    dx, dy, dz = box.XLength / nx, box.YLength / ny, box.ZLength / nz
    out = []
    pad = 1.0
    for k, s in enumerate(shapes):
        n = 0
        for i in range(nx):
            for j in range(ny):
                for l in range(nz):
                    x0 = box.XMin + i * dx - (pad if i == 0 else 0)
                    y0 = box.YMin + j * dy - (pad if j == 0 else 0)
                    z0 = box.ZMin + l * dz - (pad if l == 0 else 0)
                    x1 = box.XMin + (i + 1) * dx + (pad if i == nx - 1 else 0)
                    y1 = box.YMin + (j + 1) * dy + (pad if j == ny - 1 else 0)
                    z1 = box.ZMin + (l + 1) * dz + (pad if l == nz - 1 else 0)
                    cell = Part.makeBox(x1 - x0, y1 - y0, z1 - z0, App.Vector(x0, y0, z0))
                    piece = s.common(cell)
                    if piece.isNull() or piece.Volume < 1e-6:
                        continue
                    n += 1
                    out.append((k, n, piece))
    return out


def cut_planes(box, counts):
    """[(axis, value)] of the cut planes of a grid over a box."""
    out = []
    for axis, (lo, length, n) in enumerate(((box.XMin, box.XLength, counts[0]), (box.YMin, box.YLength, counts[1]),
                                            (box.ZMin, box.ZLength, counts[2]))):
        for i in range(1, n):
            out.append((axis, lo + length * i / n))
    return out


def face_overhang(shape, rotation, threshold, deviation=0.2):
    """{face index: area needing support} with the part turned by rotation (faces lying on the bed left out)."""
    import numpy as np
    import MeshPart
    mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=deviation, AngularDeflection=0.35, Relative=False,
                                  Segments=True)
    pts, tris = triangles(mesh)
    p = pts.dot(rot_matrix(rotation).T)
    zmin = p[:, 2].min()
    out = {}
    cos_t = math.cos(math.radians(threshold))
    for seg in range(mesh.countSegments()):
        idx = np.array(list(mesh.getSegment(seg)), dtype=int)
        if not len(idx):
            continue
        t = tris[idx]
        a, b, c = p[t[:, 0]], p[t[:, 1]], p[t[:, 2]]
        cross = np.cross(b - a, c - a)
        area2 = np.linalg.norm(cross, axis=1)
        ok = area2 > 1e-12
        nz = np.zeros(len(t))
        nz[ok] = cross[ok, 2] / area2[ok]
        low = np.maximum(np.maximum(a[:, 2], b[:, 2]), c[:, 2]) <= zmin + 0.05
        need = (~low) & (nz < 0) & (-nz >= cos_t)
        area = float(area2[need].sum() / 2)
        if area > 0.01:
            out[seg] = area
    return out


def face_thin(shape, minimum, samples=3, budget=4000):
    """{face index: thinnest sampled wall (mm)} of faces thinner than minimum: from points inside each face, a step
    of up to minimum straight into the solid leaves it again."""
    if not shape.Solids:
        return {}
    solid = shape
    out = {}
    faces = shape.Faces
    per = max(1, min(samples * samples, budget // max(1, len(faces))))
    side = max(1, int(math.sqrt(per)))
    steps = (0.25, 0.5, 0.75, 1.0)
    tol = max(1e-4, minimum * 0.02)
    for i, f in enumerate(faces):
        try:
            u0, u1, v0, v1 = f.ParameterRange
        except Exception:
            continue
        thin, total, best = 0, 0, None
        for a in range(side):
            for b in range(side):
                u = u0 + (u1 - u0) * (a + 0.5) / side
                v = v0 + (v1 - v0) * (b + 0.5) / side
                try:
                    if not f.isPartOfDomain(u, v):
                        continue            # outside a trimmed face (a hole)
                    p = f.valueAt(u, v)
                    n = f.normalAt(u, v)
                except Exception:
                    continue
                total += 1
                start = p - n * tol
                if not solid.isInside(start, tol * 0.5, True):
                    continue
                for s in steps:
                    q = p - n * (minimum * s)
                    if not solid.isInside(q, tol * 0.5, True):
                        thin += 1
                        best = minimum * s if best is None else min(best, minimum * s)
                        break
        if total and thin * 2 >= total:
            out[i] = best or minimum
    return out


# ---------------------------------------------------------------------- printer profiles (Tools > Options)
PROFILE_DEFAULT = {"name": "", "x": 220.0, "y": 220.0, "z": 250.0, "nozzle": 0.4, "min_wall": 0.8,
                   "overhang": 45.0, "resolution": "Fine", "slicer": ""}


def profiles():
    """The printer profiles: [{"name", "x", "y", "z", "nozzle", "min_wall", "overhang", "resolution", "slicer"}]."""
    import json
    try:
        rows = json.loads(params().GetString(P_PROFILES, "[]") or "[]")
    except ValueError:
        rows = []
    out = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and str(r.get("name") or "").strip():
            p = dict(PROFILE_DEFAULT)
            p.update(r)
            out.append(p)
    return out


def set_profiles(rows):
    import json
    params().SetString(P_PROFILES, json.dumps([dict(r) for r in rows]))


# ---------------------------------------------------------------------- what prints: bodies and components
def _hex(c):
    r, g, b = [max(0, min(255, int(round(float(x) * 255)))) for x in tuple(c)[:3]]
    return "#%02X%02X%02X" % (r, g, b)


def _face_colours(obj):
    """'#RRGGBB' of each face of an object as shown (its appearance per face), or []."""
    vobj = getattr(obj, "ViewObject", None)
    if vobj is None:
        return []
    try:
        mats = vobj.ShapeAppearance
        return [_hex(m.DiffuseColor) for m in mats] if mats else []
    except Exception:
        try:
            return [_hex(c) for c in vobj.DiffuseColor]
        except Exception:
            return []


def _container(obj):
    return obj.TypeId in ("App::Part", "Assembly::AssemblyObject", "App::DocumentObjectGroup") or \
        obj.TypeId.startswith("Assembly::Assembly")


def parts_of(objects):
    """[(name, shape where it stands, '#RRGGBB' or None)]: an assembly (App::Part, Assembly) gives one row per
    component (links followed, placements applied), a multi-body part one row per body, each with its colour."""
    import Part
    out = []

    def leaf(obj, shape, label):
        if shape is None or shape.isNull():
            return
        solids = shape.Solids
        cols = _face_colours(obj)
        whole = cols[0] if cols else None
        if len(solids) > 1:
            faces = shape.Faces
            for k, so in enumerate(solids):
                c = whole
                if len(cols) == len(faces) and cols:
                    f0 = so.Faces[0]
                    for i, f in enumerate(faces):
                        if f.isSame(f0):
                            c = cols[i]
                            break
                out.append(("%s (body %d)" % (label, k + 1), so, c))
        else:
            out.append((label, shape, whole))

    def walk(root, path, obj, depth=0):
        if depth > 12:
            return
        linked = obj.getLinkedObject(True) if hasattr(obj, "getLinkedObject") else obj
        kids = (getattr(linked, "Group", []) or []) if _container(linked) else None
        if kids is None:
            try:
                shape = Part.getShape(root, path, needSubElement=False, transform=True) if path else \
                    object_shape(obj)
            except Exception as error:
                _fw_log("part shape", error)
                shape = None
            from . import slicer as backend
            if shape is not None and not shape.isNull() and (shape.Solids or backend.is_mesh(obj)):
                leaf(linked if getattr(linked, "ViewObject", None) is not None else obj, shape, obj.Label)
            return
        for kid in kids:
            if not getattr(kid, "Visibility", True):
                continue
            if kid.TypeId.startswith(("App::Origin", "App::Line", "App::Plane", "App::Point", "Sketcher::",
                                      "Assembly::JointGroup", "Assembly::ViewGroup", "Assembly::BomGroup")):
                continue
            k_linked = kid.getLinkedObject(True) if hasattr(kid, "getLinkedObject") else kid
            if k_linked.TypeId != "PartDesign::Body" and any(p.TypeId == "PartDesign::Body" for p in kid.InList):
                continue                                    # a feature inside a body: the body prints
            walk(root, path + kid.Name + ".", kid, depth + 1)

    for obj in objects:
        try:
            walk(obj, "", obj)
        except Exception as error:
            _fw_log("parts", error)
            try:
                out.append((obj.Label, object_shape(obj), None))
            except Exception as error2:
                _fw_log("parts fallback", error2)
    return out


# ---------------------------------------------------------------------- printers
def slicer_beds():
    """[(key, "Slicer: printer", (x, y, z))] of the printer each slicer has picked (the 3D Slicer panel's)."""
    from . import slicer as backend
    rows = []
    for key in ("orca", "bambu", "prusa"):
        s = backend.get(key)
        if s is None:
            continue
        try:
            choice = {}
            try:
                from . import slicerui
                choice = slicerui.saved(key)
            except Exception as error:
                _fw_log("saved", error)
            printer = choice.get("printer") or (s.current_presets() if hasattr(s, "current_presets") else {}).get(
                "machine") or ""
            if not printer:
                continue
            data = s.resolve("machine", printer)
            area = [tuple(float(v) for v in str(p).split("x")) for p in data.get("printable_area") or []]
            height = data.get("printable_height")
            height = float(height[0] if isinstance(height, list) else height or 0)
            if not area or height <= 0:
                continue
            w = max(p[0] for p in area) - min(p[0] for p in area)
            d = max(p[1] for p in area) - min(p[1] for p in area)
            rows.append((key, "%s: %s" % (s.title, printer), (w, d, height)))
        except Exception as error:
            _fw_log("bed %s" % key, error)
    return rows


# ---------------------------------------------------------------------- the graphics area
class Overlay:
    """The printer's bed box and the cut planes, in the part's own place (drawn in the graphics area)."""

    def __init__(self):
        self.node = None

    def show(self, inverse, bed, planes, box, plate=True):
        """inverse: matrix from bed coordinates to the model's; planes [(axis, value)] in bed coordinates. plate: the
        printer's build plate (a light plate with a 10 mm grid) and its build volume."""
        from pivy import coin
        self.hide()
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if view is None:
            return
        sep = coin.SoSeparator()
        sep.setName("SWStyle_Print3DOverlay")
        style = coin.SoDrawStyle()
        style.lineWidth = 2
        sep.addChild(style)
        x, y, z = bed
        if plate:
            corners = [(0, 0, 0), (x, 0, 0), (x, y, 0), (0, y, 0), (0, 0, z), (x, 0, z), (x, y, z), (0, y, z)]
            edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
            self._plate(sep, coin, inverse, x, y)
            grid = [((i, 0, 0), (i, y, 0)) for i in range(10, int(x), 10)] + \
                   [((0, j, 0), (x, j, 0)) for j in range(10, int(y), 10)]
            if grid:
                self._lines(sep, coin, inverse, grid, (0.62, 0.70, 0.80))
            self._lines(sep, coin, inverse, [(corners[a], corners[b]) for a, b in edges], (0.25, 0.55, 0.95))
        segs = []
        for axis, value in planes:
            lo = [box.XMin, box.YMin, box.ZMin]
            hi = [box.XMax, box.YMax, box.ZMax]
            o = [i for i in range(3) if i != axis]
            quad = []
            for a, b in ((0, 0), (1, 0), (1, 1), (0, 1)):
                p = [0.0, 0.0, 0.0]
                p[axis] = value
                p[o[0]] = (lo if a == 0 else hi)[o[0]]
                p[o[1]] = (lo if b == 0 else hi)[o[1]]
                quad.append(tuple(p))
            segs += [(quad[i], quad[(i + 1) % 4]) for i in range(4)] + [(quad[0], quad[2]), (quad[1], quad[3])]
        if segs:
            self._lines(sep, coin, inverse, segs, (0.95, 0.45, 0.10))
        view.getSceneGraph().addChild(sep)
        self.node = sep

    @staticmethod
    def _plate(sep, coin, inverse, x, y):
        sub = coin.SoSeparator()
        mat = coin.SoMaterial()
        mat.diffuseColor = (0.80, 0.86, 0.93)
        mat.transparency = 0.55
        sub.addChild(mat)
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
        sub.addChild(hints)
        coords = coin.SoCoordinate3()
        pts = [tuple(inverse.multVec(App.Vector(*p))) for p in ((0, 0, -0.05), (x, 0, -0.05), (x, y, -0.05),
                                                                 (0, y, -0.05))]
        coords.point.setValues(0, 4, pts)
        sub.addChild(coords)
        face = coin.SoFaceSet()
        face.numVertices.setValue(4)
        sub.addChild(face)
        sep.addChild(sub)

    @staticmethod
    def _lines(sep, coin, inverse, segs, colour):
        mat = coin.SoBaseColor()
        mat.rgb = colour
        sep.addChild(mat)
        coords = coin.SoCoordinate3()
        pts = []
        for a, b in segs:
            pts.append(tuple(inverse.multVec(App.Vector(*a))))
            pts.append(tuple(inverse.multVec(App.Vector(*b))))
        coords.point.setValues(0, len(pts), pts)
        sep.addChild(coords)
        lines = coin.SoLineSet()
        lines.numVertices.setValues(0, len(segs), [2] * len(segs))
        sep.addChild(lines)

    def hide(self):
        if self.node is None:
            return
        try:
            view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
            if view is not None:
                view.getSceneGraph().removeChild(self.node)
        except Exception as error:
            _fw_log("overlay hide", error)
        self.node = None


# ---------------------------------------------------------------------- the PropertyManager
def _group(title, name):
    w = QtWidgets.QGroupBox(title)
    w.setObjectName(name)
    return w


def _spin(lo, hi, value, suffix, decimals=1, step=1.0):
    s = QtWidgets.QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(value)
    s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    return s


class Print3DPanel:
    ""

    current = None

    def __init__(self, objects=None):
        self.objects = list(objects if objects is not None else targets())
        self.doc = self.objects[0].Document if self.objects else App.ActiveDocument
        self.shapes = []
        for o in self.objects:
            try:
                self.shapes.append(object_shape(o))
            except Exception as error:
                _fw_log("shape", error)
        try:
            self.parts = parts_of(self.objects)      # (name, shape, colour) per body / component
        except Exception as error:
            _fw_log("parts_of", error)
            self.parts = []
        if not self.parts:
            self.parts = [(o.Label, sh, None) for o, sh in zip(self.objects, self.shapes)]
        self.rotation = App.Rotation()
        self.bottom = None                  # (object, face name) picked as the bottom
        self.overlay = Overlay()
        self.colours = {}                   # object name -> its ShapeAppearance before the analysis
        self.suggestions = []
        self._busy = False

        w = QtWidgets.QWidget()
        w.setObjectName("SWStyle_Print3D")
        w.setWindowTitle("Print3D")
        w.setProperty("swstyle_pm_title", "Print3D")
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("SWStyle_Print3DTabs")
        lay.addWidget(self.tabs)
        settings = QtWidgets.QWidget()
        sl = QtWidgets.QVBoxLayout(settings)
        for box in (self._printer_box(), self._scale_box(), self._orient_box(), self._split_box(),
                    self._export_box(), self._save_box()):
            sl.addWidget(box)
        sl.addStretch(1)
        preview = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(preview)
        pl.addWidget(self._plate_box())
        pl.addWidget(self._analysis_box())
        pl.addStretch(1)
        self.tabs.addTab(settings, "Settings")
        self.tabs.addTab(preview, "Preview")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.form = w
        cur = self.printer.currentData() or ""
        for prof in self.profiles:
            if cur == "profile:" + prof["name"]:
                self.apply_profile(prof)
        Print3DPanel.current = self
        Gui.Selection.addObserver(self)
        QtCore.QTimer.singleShot(0, self.update)

    # ---------------------------------------------------------------- boxes
    def _printer_box(self):
        w = _group("Printer", "SWStyle_Print3DPrinter")
        lay = QtWidgets.QFormLayout(w)
        self.printer = QtWidgets.QComboBox()
        self.printer.setObjectName("SWStyle_Print3DPrinterList")
        self.beds = slicer_beds()
        for key, label, size in self.beds:
            self.printer.addItem(label, key)
        self.profiles = profiles()
        for prof in self.profiles:
            self.printer.addItem(prof["name"], "profile:" + prof["name"])
        self.printer.addItem("Custom size", "custom")
        self.printer.setToolTip("The bed of the printer each slicer has picked in its 3D Slicer tab, a printer profile "
                                "(Tools > Options > Export > Print3D Printers), or a size of your own")
        lay.addRow(self.printer)
        saved = [float(v) for v in (params().GetString(P_BED, "256,256,256").split(",") + ["256"] * 3)[:3]]
        self.bed_x = _spin(10, 2000, saved[0], " mm")
        self.bed_y = _spin(10, 2000, saved[1], " mm")
        self.bed_z = _spin(10, 2000, saved[2], " mm")
        for label, s in (("X", self.bed_x), ("Y", self.bed_y), ("Z", self.bed_z)):
            s.setToolTip("Printer bed size %s (typing a size makes it Custom size)" % label)
            lay.addRow(label + ":", s)
            s.valueChanged.connect(self._bed_typed)
        want = params().GetString(P_PRINTER, "")
        i = self.printer.findData(want) if want else 0
        self.printer.setCurrentIndex(i if i >= 0 else 0)
        self._printer_changed()
        self.printer.currentIndexChanged.connect(self._printer_changed)
        self.fit_label = QtWidgets.QLabel()
        self.fit_label.setWordWrap(True)
        lay.addRow(self.fit_label)
        return w

    def _scale_box(self):
        w = _group("Scale", "SWStyle_Print3DScale")
        lay = QtWidgets.QFormLayout(w)
        self.scale_fit = QtWidgets.QCheckBox("Scale to fit")
        self.scale_fit.setToolTip("Scale the part to the largest size that fits the printer bed")
        lay.addRow(self.scale_fit)
        self.scale = _spin(1, 10000, 100, " %", 1, 5)
        self.scale.setToolTip("Scale of the printed part (typing one turns Scale to fit off)")
        lay.addRow("Scale:", self.scale)
        self.scale_fit.toggled.connect(lambda _on: self.update())
        self.scale.valueChanged.connect(self._scale_typed)
        return w

    def _orient_box(self):
        w = _group("Orientation", "SWStyle_Print3DOrientation")
        lay = QtWidgets.QVBoxLayout(w)
        self.bottom_box = QtWidgets.QListWidget()
        self.bottom_box.setObjectName("SWStyle_Print3DBottom")
        self.bottom_box.setProperty("swpickbox", True)
        self.bottom_box.setProperty("swActive", "true")
        self.bottom_box.setMaximumHeight(44)
        self.bottom_box.setToolTip("Select a flat face of the part for the bottom: it lies on the printer bed")
        lay.addWidget(QtWidgets.QLabel("Bottom face:"))
        lay.addWidget(self.bottom_box)
        lay.addWidget(QtWidgets.QLabel("Suggested:"))
        self.suggest_list = QtWidgets.QListWidget()
        self.suggest_list.setObjectName("SWStyle_Print3DSuggestions")
        self.suggest_list.setMaximumHeight(96)
        self.suggest_list.setWordWrap(True)
        self.suggest_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.suggest_list.setToolTip("Orientations with the least area needing support (then the most on the bed). "
                                     "Click one to use it.")
        self.suggest_list.itemClicked.connect(self._suggestion_picked)
        lay.addWidget(self.suggest_list)
        row = QtWidgets.QHBoxLayout()
        self.suggest_button = QtWidgets.QPushButton("Suggest")
        self.suggest_button.setToolTip("Find the orientations needing the least support")
        self.suggest_button.clicked.connect(self.suggest)
        row.addWidget(self.suggest_button)
        self.reset_button = QtWidgets.QPushButton("As Modelled")
        self.reset_button.setToolTip("Print the part the way it stands in the model")
        self.reset_button.clicked.connect(self.reset_orientation)
        row.addWidget(self.reset_button)
        lay.addLayout(row)
        return w

    def _split_box(self):
        w = _group("Split to Fit", "SWStyle_Print3DSplit")
        lay = QtWidgets.QFormLayout(w)
        self.split_check = QtWidgets.QCheckBox("Split into pieces that fit the bed")
        self.split_check.setToolTip("Cut the part where the orange planes show; each piece prints on its own")
        lay.addRow(self.split_check)
        self.split_n = []
        for axis in "XYZ":
            s = QtWidgets.QSpinBox()
            s.setRange(1, 20)
            s.setToolTip("Pieces along %s (typing a number splits the part)" % axis)
            s.valueChanged.connect(self._split_typed)
            self.split_n.append(s)
            lay.addRow("Pieces along %s:" % axis, s)
        self.split_check.toggled.connect(lambda _on: self.update())
        self.split_label = QtWidgets.QLabel()
        self.split_label.setWordWrap(True)
        lay.addRow(self.split_label)
        return w

    def _plate_box(self):
        w = _group("Build Plate", "SWStyle_Print3DPlate")
        lay = QtWidgets.QVBoxLayout(w)
        self.show_bed = QtWidgets.QCheckBox("Show the printer's build plate")
        self.show_bed.setChecked(params().GetBool(P_SHOW_BED, True))
        self.show_bed.setToolTip("The build plate and build volume under the part, as it will stand on the printer")
        self.show_bed.toggled.connect(self._bed_shown)
        lay.addWidget(self.show_bed)
        self.preview_label = QtWidgets.QLabel()
        self.preview_label.setWordWrap(True)
        lay.addWidget(self.preview_label)
        return w

    def _bed_shown(self, on):
        params().SetBool(P_SHOW_BED, bool(on))
        self.update(keep_counts=True)

    def _tab_changed(self, i):

        if i == 1 and not (self.show_support.isChecked() or self.show_thin.isChecked()):
            self.show_support.setChecked(True)
            self.show_thin.setChecked(True)

    def _analysis_box(self):
        w = _group("Analysis", "SWStyle_Print3DAnalysis")
        lay = QtWidgets.QFormLayout(w)
        self.show_support = QtWidgets.QCheckBox("Show overhang areas that need support")
        self.show_support.setToolTip("Colour the faces that overhang more than the threshold angle (red)")
        lay.addRow(self.show_support)
        self.threshold = _spin(5, 85, params().GetFloat(P_OVERHANG, 45.0), " deg", 0, 5)
        self.threshold.setToolTip("Overhangs flatter than this angle from the horizontal need support "
                                  "(typing one shows them)")
        lay.addRow("Threshold angle:", self.threshold)
        self.show_thin = QtWidgets.QCheckBox("Show areas too thin to print")
        self.show_thin.setToolTip("Colour the faces whose wall is thinner than the minimum (yellow)")
        lay.addRow(self.show_thin)
        self.min_thick = _spin(0.1, 20, params().GetFloat(P_THIN, 0.8), " mm", 2, 0.1)
        self.min_thick.setToolTip("Walls thinner than this do not print well: about two line widths of the nozzle "
                                  "(typing one shows them)")
        lay.addRow("Minimum thickness:", self.min_thick)
        self.analysis_label = QtWidgets.QLabel()
        self.analysis_label.setWordWrap(True)
        lay.addRow(self.analysis_label)
        self.show_support.toggled.connect(lambda _on: self.analyse())
        self.show_thin.toggled.connect(lambda _on: self.analyse())
        self.threshold.valueChanged.connect(lambda _v: self._analysis_typed(self.show_support))
        self.min_thick.valueChanged.connect(lambda _v: self._analysis_typed(self.show_thin))
        return w

    def _export_box(self):
        w = _group("Export Options", "SWStyle_Print3DExport")
        lay = QtWidgets.QFormLayout(w)
        name, dev, ang = resolution()
        row = QtWidgets.QHBoxLayout()
        self.res_buttons = {}
        group = QtWidgets.QButtonGroup(w)
        for n in ("Coarse", "Fine", "Custom"):
            b = QtWidgets.QRadioButton(n)
            b.setChecked(n == name)
            b.setToolTip({"Coarse": "Fewer, larger triangles (0.5 mm, 30 deg)",
                          "Fine": "Smooth curves (0.05 mm, 10 deg)",
                          "Custom": "The deviation and angle below"}[n])
            group.addButton(b)
            row.addWidget(b)
            self.res_buttons[n] = b
            b.toggled.connect(lambda on, n=n: on and self._resolution_picked(n))
        lay.addRow("Resolution:", row)
        self.deviation = _spin(0.001, 5, dev, " mm", 3, 0.01)
        self.deviation.setToolTip("How far a triangle may be from the true surface (typing one makes it Custom)")
        self.angle = _spin(0.5, 45, ang, " deg", 1, 1)
        self.angle.setToolTip("How much the surface may turn within one triangle (typing one makes it Custom)")
        lay.addRow("Deviation:", self.deviation)
        lay.addRow("Angle:", self.angle)
        self.deviation.valueChanged.connect(self._tolerance_typed)
        self.angle.valueChanged.connect(self._tolerance_typed)
        self.triangles_label = QtWidgets.QLabel()
        lay.addRow(self.triangles_label)
        self.send_solids = QtWidgets.QCheckBox("Send solids to the slicer")
        self.send_solids.setChecked(params().GetBool(P_SEND_SOLIDS, True))
        self.send_solids.setToolTip("On: the slicer gets the solids and makes its own triangles (as it does with a "
                                    "STEP file). Off: it gets the triangles made with this resolution.")
        self.send_solids.toggled.connect(lambda on: params().SetBool(P_SEND_SOLIDS, on))
        lay.addRow(self.send_solids)
        return w

    def _save_box(self):
        w = _group("Save", "SWStyle_Print3DSave")
        lay = QtWidgets.QVBoxLayout(w)
        row = QtWidgets.QHBoxLayout()
        self.send_to = QtWidgets.QComboBox()
        self.send_to.setObjectName("SWStyle_Print3DSendTo")
        from . import slicer as backend
        for key in ("orca", "bambu", "prusa"):
            s = backend.get(key)
            if s is not None:
                try:
                    have = s.exe() is not None and os.environ.get("SWSTYLE_NO_SLICER") != "1"
                except Exception:
                    have = False
                # a slicer not downloaded yet stays in the list (Send says why and offers the download)
                self.send_to.addItem(s.title if have else "%s (not downloaded)" % s.title, key)
        cur = self.printer.currentData()
        if cur in ("orca", "bambu", "prusa"):
            self.send_to.setCurrentIndex(max(0, self.send_to.findData(cur)))
        self.send_to.setToolTip("The slicer whose 3D Slicer tab gets the part")
        row.addWidget(self.send_to, 1)
        self.send_button = QtWidgets.QPushButton("Send to Slicer")
        self.send_button.setToolTip("Put the part, as set here, on the plate of the slicer's 3D Slicer tab")
        self.send_button.clicked.connect(self.send)
        row.addWidget(self.send_button)
        lay.addLayout(row)
        self.save_button = QtWidgets.QPushButton("Save to File...")
        self.save_button.setToolTip("Save the part, as set here, as a 3MF or STL file")
        self.save_button.clicked.connect(self.save)
        lay.addWidget(self.save_button)
        self.save_label = QtWidgets.QLabel()
        self.save_label.setWordWrap(True)
        lay.addWidget(self.save_label)
        return w

    # ---------------------------------------------------------------- reactions
    def _printer_changed(self, *_a):
        key = self.printer.currentData()
        params().SetString(P_PRINTER, key or "custom")
        for k, _label, size in self.beds:
            if k == key:
                for s, v in zip((self.bed_x, self.bed_y, self.bed_z), size):
                    s.blockSignals(True)
                    s.setValue(v)
                    s.blockSignals(False)
                if hasattr(self, "send_to"):
                    self.send_to.setCurrentIndex(max(0, self.send_to.findData(key)))
        for prof in getattr(self, "profiles", []):
            if key == "profile:" + prof["name"]:
                self.apply_profile(prof)
        if hasattr(self, "fit_label"):
            self.update()

    def apply_profile(self, prof):
        """A printer profile: its bed, and its wall, overhang, resolution and slicer."""
        for s, v in zip((self.bed_x, self.bed_y, self.bed_z), (prof["x"], prof["y"], prof["z"])):
            s.blockSignals(True)
            s.setValue(float(v))
            s.blockSignals(False)
        if hasattr(self, "min_thick"):
            for s, v in ((self.min_thick, prof["min_wall"]), (self.threshold, prof["overhang"])):
                s.blockSignals(True)
                s.setValue(float(v))
                s.blockSignals(False)
        if hasattr(self, "res_buttons") and prof.get("resolution") in self.res_buttons:
            self.res_buttons[prof["resolution"]].setChecked(True)
        if hasattr(self, "send_to") and prof.get("slicer"):
            i = self.send_to.findData(prof["slicer"])
            if i >= 0:
                self.send_to.setCurrentIndex(i)

    def _bed_typed(self, *_a):
        i = self.printer.findData("custom")
        if self.printer.currentIndex() != i:
            self.printer.blockSignals(True)
            self.printer.setCurrentIndex(i)
            self.printer.blockSignals(False)
            params().SetString(P_PRINTER, "custom")
        params().SetString(P_BED, "%g,%g,%g" % self.bed())
        self.update()

    def _scale_typed(self, *_a):
        if self._busy:
            return
        if self.scale_fit.isChecked():
            self.scale_fit.blockSignals(True)
            self.scale_fit.setChecked(False)
            self.scale_fit.blockSignals(False)
        self.update()

    def _split_typed(self, *_a):
        if self._busy:
            return
        if not self.split_check.isChecked():
            self.split_check.blockSignals(True)
            self.split_check.setChecked(True)
            self.split_check.blockSignals(False)
        self.update(keep_counts=True)

    def _analysis_typed(self, box):
        params().SetFloat(P_OVERHANG, self.threshold.value())
        params().SetFloat(P_THIN, self.min_thick.value())
        if box.isChecked():
            self.analyse()
        else:
            box.setChecked(True)            # analyse() follows the toggle

    def _resolution_picked(self, name):
        p = params()
        p.SetString(STL_RESOLUTION, name)
        if name in RESOLUTIONS:
            dev, ang = RESOLUTIONS[name]
            for s, v in ((self.deviation, dev), (self.angle, ang)):
                s.blockSignals(True)
                s.setValue(v)
                s.blockSignals(False)
        self._count_triangles()

    def _tolerance_typed(self, *_a):
        p = params()
        p.SetFloat(STL_DEVIATION, self.deviation.value())
        p.SetFloat(STL_ANGLE, self.angle.value())
        if not self.res_buttons["Custom"].isChecked():
            self.res_buttons["Custom"].setChecked(True)
        else:
            self._resolution_picked("Custom")

    def _suggestion_picked(self, item):
        k = self.suggest_list.row(item)
        if 0 <= k < len(self.suggestions):
            self.rotation = self.suggestions[k]["rotation"]
            self.bottom = None
            self.bottom_box.clear()
            self.update()

    # ---------------------------------------------------------------- selection (the Bottom face box)
    def addSelection(self, doc, obj, sub, pnt):
        if not sub or not sub.split(".")[-1].startswith("Face"):
            return
        found = [o for o in self.objects if o.Name == obj and o.Document.Name == doc]
        if found:
            self.pick_bottom(found[0], sub)
            return
        # a face of a feature inside a body: the body is what prints
        for o in self.objects:
            if any(x.Name == obj for x in getattr(o, "Group", []) or []):
                self.pick_bottom(o, sub.split(".")[-1])
                return

    def pick_bottom(self, obj, sub):
        try:
            face = obj.getSubObject(sub) if hasattr(obj, "getSubObject") else obj.Shape.getElement(sub)
        except Exception:
            face = None
        if face is None or "Plane" not in str(face.Surface):
            self.bottom_box.clear()
            self.bottom_box.addItem("Select a flat face for the bottom")
            return False
        u0, u1, v0, v1 = face.ParameterRange
        n = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        self.rotation = rotation_down(n)
        self.bottom = (obj, sub)
        self.bottom_box.clear()
        self.bottom_box.addItem("%s of %s" % (sub.split(".")[-1], obj.Label))
        self.update()
        return True

    # ---------------------------------------------------------------- work
    def bed(self):
        return self.bed_x.value(), self.bed_y.value(), self.bed_z.value()

    def _size(self, rotation, scale):
        m = rotation.toMatrix()
        box = None
        for s in [p[1] for p in self.parts] or self.shapes:
            b = s.transformed(m).BoundBox if not s.isNull() else None
            if b is not None:
                box = App.BoundBox(b) if box is None else box.united(b)
        if box is None:
            return (0.0, 0.0, 0.0)
        return box.XLength * scale, box.YLength * scale, box.ZLength * scale

    def scale_value(self):
        return self.scale.value() / 100.0

    def update(self, keep_counts=False):
        """Fits, scale to fit, the pieces, the overlay: after any change."""
        if not self.shapes:
            self.fit_label.setText("Nothing to print: open or select a body or solid.")
            return
        bed = self.bed()
        size1 = self._size(self.rotation, 1.0)
        if self.scale_fit.isChecked():
            fit = min(bed[i] / size1[i] for i in range(3) if size1[i] > 1e-9) if any(size1) else 1.0
            self._busy = True
            self.scale.setValue(round(fit * 100.0 - 0.05, 1))
            self._busy = False
        scale = self.scale_value()
        size = [v * scale for v in size1]
        fits = all(size[i] <= bed[i] + 1e-6 for i in range(3))
        text = "Part: %.1f x %.1f x %.1f mm. " % tuple(size)
        if fits:
            text += "It fits the printer bed."
            self.fit_label.setStyleSheet("")
        else:
            text += "It is larger than the printer bed: Scale to fit, turn it, or split it."
            self.fit_label.setStyleSheet("color: #c00000")
        self.fit_label.setText(text)
        need = pieces_needed(size, bed)
        if not keep_counts:
            self._busy = True
            for s, n in zip(self.split_n, need):
                s.setValue(n)
            self._busy = False
        counts = [s.value() for s in self.split_n]
        planes = []
        posed_shapes, matrix, shift = posed([p[1] for p in self.parts], self.rotation, scale, bed)
        box = None
        for s in posed_shapes:
            box = App.BoundBox(s.BoundBox) if box is None else box.united(s.BoundBox)
        if self.split_check.isChecked():
            planes = cut_planes(box, counts)
            piece = [size[i] / counts[i] for i in range(3)]
            ok = all(piece[i] <= bed[i] + 1e-6 for i in range(3))
            self.split_label.setText("%d pieces of up to %.1f x %.1f x %.1f mm%s" % (
                counts[0] * counts[1] * counts[2], piece[0], piece[1], piece[2],
                "." if ok else ": still larger than the bed, add pieces."))
        elif fits:
            self.split_label.setText("No split needed.")
        else:
            self.split_label.setText("Split into %d x %d x %d pieces to fit." % tuple(need))
        inverse = App.Matrix(matrix)
        inverse.move(shift)
        try:
            inverse = inverse.inverse()
            self.overlay.show(inverse, bed, planes, box, plate=self.show_bed.isChecked())
        except Exception as error:
            _fw_log("overlay", error)
        if self.show_support.isChecked() or self.show_thin.isChecked():
            self.analyse()
        self._count_triangles()

    def suggest(self):
        if not self.shapes:
            return
        import Part
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            shape = self.shapes[0] if len(self.shapes) == 1 else Part.makeCompound(self.shapes)
            self.suggestions = suggest(shape, self.threshold.value())
        except Exception as error:
            _fw_log("suggest", error)
            self.suggestions = []
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.suggest_list.clear()
        for r in self.suggestions:
            it = QtWidgets.QListWidgetItem("%s: %.0f mm\u00b2 support, %.0f mm high" % (describe(r["normal"]),
                                                                                      r["support"], r["height"]))
            it.setToolTip("Area needing support %.0f mm\u00b2, height %.1f mm, on the bed %.0f mm\u00b2" % (
                r["support"], r["height"], r["contact"]))
            self.suggest_list.addItem(it)
        if not self.suggestions:
            self.suggest_list.addItem("No suggestion: the part has no flat faces to stand on.")

    def reset_orientation(self):
        self.rotation = App.Rotation()
        self.bottom = None
        self.bottom_box.clear()
        self.suggest_list.clearSelection()
        self.update()

    def analyse(self):
        """Colour the faces needing support (red), the thin ones (yellow), both (purple); say how much."""
        self._restore_colours()
        support_on, thin_on = self.show_support.isChecked(), self.show_thin.isChecked()
        if not (support_on or thin_on):
            self.analysis_label.setText("")
            return
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        total_s, n_s, n_t, thinnest = 0.0, 0, 0, None
        try:
            for obj, shape in zip(self.objects, self.shapes):
                over = face_overhang(shape, self.rotation, self.threshold.value()) if support_on else {}
                thin = face_thin(shape, self.min_thick.value() / max(1e-9, self.scale_value())) if thin_on else {}
                total_s += sum(over.values()) * self.scale_value() ** 2
                n_s += len(over)
                n_t += len(thin)
                for v in thin.values():
                    v *= self.scale_value()
                    thinnest = v if thinnest is None else min(thinnest, v)
                self._colour(obj, shape, over, thin)
        except Exception as error:
            _fw_log("analyse", error)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        parts = []
        if support_on:
            parts.append("Needs support: %.0f mm\u00b2 on %d faces (red)." % (total_s, n_s) if n_s else
                         "No area needs support.")
        if thin_on:
            parts.append("Thin: %d faces under %.2f mm (yellow)." % (n_t, self.min_thick.value()) if n_t else
                         "No wall is thinner than %.2f mm." % self.min_thick.value())
        self.analysis_label.setText(" ".join(parts))

    def _colour(self, obj, shape, over, thin):
        vobj = getattr(obj, "ViewObject", None)
        if vobj is None or not (over or thin):
            return
        try:
            faces = len(obj.Shape.Faces)
        except Exception:
            return
        if faces != len(shape.Faces):
            return                          # a mesh object: the numbers say it
        if obj.Name not in self.colours:
            try:
                self.colours[obj.Name] = (obj, vobj.ShapeAppearance)
            except Exception as error:
                _fw_log("keep colour", error)
                return
        orig = self.colours[obj.Name][1]
        cols = []
        for i in range(faces):
            # FreeCAD 1.x: the fourth number is the opacity (1 = solid); a face keeps its own colour unless marked
            own = tuple(orig[i if i < len(orig) else 0].DiffuseColor) if orig else (0.8, 0.8, 0.8, 1.0)
            c = BOTH_COLOUR if (i in over and i in thin) else SUPPORT_COLOUR if i in over else \
                THIN_COLOUR if i in thin else own
            cols.append((float(c[0]), float(c[1]), float(c[2]), float(own[3])))
        try:
            vobj.DiffuseColor = cols
        except Exception as error:
            _fw_log("colour", error)

    def _restore_colours(self):
        for name, (obj, app) in list(self.colours.items()):
            try:
                obj.ViewObject.ShapeAppearance = app
            except Exception as error:
                _fw_log("restore colour", error)
        self.colours = {}

    def _count_triangles(self):
        if not self.shapes:
            return
        try:
            import Part
            shape = self.shapes[0] if len(self.shapes) == 1 else Part.makeCompound(self.shapes)
            if len(shape.Faces) > 400:
                self.triangles_label.setText("")
                return
            scale = self.scale_value()
            n = mesh_of(shape, self.deviation.value() / max(1e-9, scale), self.angle.value()).CountFacets
            self.triangles_label.setText("About %d triangles." % n)
        except Exception as error:
            _fw_log("count", error)

    def print_rows(self):
        """[(name, shape on the bed, '#RRGGBB' or None)]: each body / component (or its pieces) turned, scaled and
        set on the bed, with its colour."""
        bed = self.bed()
        out, _m, _s = posed([p[1] for p in self.parts], self.rotation, self.scale_value(), bed)
        names = [p[0] for p in self.parts]
        cols = [p[2] for p in self.parts]
        if self.split_check.isChecked() and any(s.value() > 1 for s in self.split_n):
            rows = split(out, [s.value() for s in self.split_n])
            return [("%s piece %d" % (names[k], n), piece, cols[k]) for k, n, piece in rows]
        return list(zip(names, out, cols))

    def print_shapes(self):
        """[(name, shape on the bed)]: as print_rows, without the colours."""
        return [(n, sh) for n, sh, _c in self.print_rows()]

    def send(self):
        """The part as set here onto the plate of the slicer's 3D Slicer tab: each body / component its own object,
        its colour a filament slot of that colour."""
        from . import slicerui, slicerplate, slicer3mf
        key = self.send_to.currentData()
        if not key:
            self._said("No slicer to send to.", True)
            return
        rows = self.print_rows()
        if not rows:
            self._said("Nothing to send: open or select a body or solid.", True)
            return
        why = slicer_missing(key)
        if why:
            # never a silent button: say why, offer the download (Slicer Updates), keep the PM open
            self._said(why, True)
            try:
                if slicerui.ask_download("Print3D", key):
                    Gui.runCommand("SWStyle_SlicerUpdate")
            except Exception as error:
                _fw_log("ask download", error)
            return
        name, dev, ang = resolution()
        meshes = [(n, sh, mesh_of(sh, dev, ang), c) for n, sh, c in rows]
        sources = {(o.Document.Name, o.Name) for o in self.objects}
        self.close_panel()
        panel = slicerui.show_panel(key)
        if panel is None:
            App.Console.PrintWarning("Print3D: the 3D Slicer tab could not open (another PropertyManager is open).\n")
            return
        bed = panel.bed
        bed.items = [it for it in bed.items if it.source not in sources]
        bed._deleted_sources = set(getattr(bed, "_deleted_sources", set())) | sources
        solids = params().GetBool(P_SEND_SOLIDS, True)
        colours = [c for _n, _s, _m, c in meshes]
        slot_of = [1] * len(meshes)
        try:
            slots = panel.slots
            if any(colours):
                wanted, slot_of = slicer3mf.colour_slots(colours, slots.limit(), "")
                while slots.count() < len(wanted) and slots.add(quiet=True):
                    pass
                for i, sl in enumerate(wanted):
                    if sl.get("colour"):
                        slots.set_colour(i, sl["colour"])
        except Exception as error:
            _fw_log("send colours", error)
        for k, (n, sh, m, _c) in enumerate(meshes):
            it = slicerplate.Item(n, sh if solids else None, m, "print3d:%s" % n)
            it.plate = bed.current
            it.pinned = True
            it.slot = slot_of[k] if k < len(slot_of) else 1
            bed.items.append(it)
        bed.selected = set()
        bed._pack()
        bed._redraw()
        bed._changed()
        try:
            panel.status.setText("From Print3D: %d object%s on the plate." % (len(meshes), "" if len(meshes) == 1 else "s"))
        except Exception as error:
            _fw_log("send status", error)

    def _said(self, text, error=False):
        self.save_label.setText(text)
        self.save_label.setStyleSheet("color: #c00000" if error else "")

    def save(self):
        rows = self.print_rows()
        if not rows:
            self.save_label.setText("Nothing to save: open or select a body or solid.")
            return
        doc = self.doc
        folder = os.path.dirname(doc.FileName) if doc is not None and doc.FileName else os.path.expanduser("~")
        stem = (doc.Label if doc is not None else "Part")
        path, flt = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save to File",
                                                          os.path.join(folder, stem + ".3mf"),
                                                          "3D Manufacturing Format (*.3mf);;STL (*.stl)")
        if not path:
            return
        ok, text = save_file(self.print_rows(), path)
        self._said(text, not ok)

    # ---------------------------------------------------------------- the task dialog
    def close_panel(self):
        self._cleanup()
        try:
            Gui.Control.closeDialog()
        except Exception as error:
            _fw_log("close", error)

    def _cleanup(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as error:
            _fw_log("observer", error)
        self._restore_colours()
        self.overlay.hide()
        if Print3DPanel.current is self:
            Print3DPanel.current = None

    def accept(self):
        self._cleanup()
        return True

    def reject(self):
        self._cleanup()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def helpRequested(self):
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), "Print3D",
            "Print3D gets the part ready for a 3D printer: pick the printer, scale it, choose the face it stands on "
            "(or a suggestion), split it to fit, check where it needs support and where walls are too thin, then "
            "send it to a slicer's 3D Slicer tab or save a 3MF or STL file. The model itself is not changed.")


def slicer_missing(key):
    """Why Send cannot go to this slicer now, in plain words, or "" when it can."""
    from . import slicer as backend
    s = backend.get(key)
    if s is None:
        return "No such slicer."
    if os.environ.get("SWSTYLE_NO_SLICER") == "1":
        return "%s is switched off for this test run (SWSTYLE_NO_SLICER)." % s.title
    try:
        if s.exe() is None:
            return ("%s is not on this computer yet. It is not part of the add-on: Slicer Updates (3D Slicer tab) "
                    "downloads it. Save to File works without it." % s.title)
    except Exception as error:
        return "%s could not be looked for: %s" % (s.title, error)
    return ""


def write_3mf(rows, path, deviation, angle):
    """A 3MF with one named object per row and its colour (3MF core base materials, which Orca Slicer, Bambu
    Studio and PrusaSlicer read). rows = [(name, shape or mesh, '#RRGGBB' or None)]. Returns the triangles."""
    import zipfile
    from xml.sax.saxutils import quoteattr
    colours = []
    for _n, _s, c in rows:
        if c and c.upper() not in colours:
            colours.append(c.upper())
    objs, build, total = [], [], 0
    for i, (name, shape, c) in enumerate(rows, 1):
        m = shape.copy() if hasattr(shape, "Facets") else mesh_of(shape, deviation, angle)
        pts, tris = m.Topology
        total += len(tris)
        mat = ' pid="1" pindex="%d"' % colours.index(c.upper()) if (c and colours) else ""
        objs.append('  <object id="%d" name=%s type="model"%s><mesh><vertices>%s</vertices><triangles>%s</triangles>'
                    '</mesh></object>' % (
                        i + 1, quoteattr(name), mat,
                        "".join('<vertex x="%.6f" y="%.6f" z="%.6f"/>' % (v.x, v.y, v.z) for v in pts),
                        "".join('<triangle v1="%d" v2="%d" v3="%d"/>' % t for t in tris)))
        build.append('<item objectid="%d"/>' % (i + 1))
    base = ""
    if colours:
        base = '  <basematerials id="1">%s</basematerials>\n' % "".join(
            '<base name="Colour %d" displaycolor="%sFF"/>' % (k + 1, c) for k, c in enumerate(colours))
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n <resources>\n%s%s\n </resources>\n'
             ' <build>%s</build>\n</model>\n') % (base, "\n".join(objs), "".join(build))
    with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/3dmodel.model", model)
    return total


def save_file(rows, path, deviation=None, angle=None):
    """Write [(name, shape[, colour])] as a 3MF (one named object each, with its colour) or one STL.
    Returns (ok, message)."""
    import Mesh
    name, dev, ang = resolution()
    dev = deviation if deviation is not None else dev
    ang = angle if angle is not None else ang
    rows = [(r[0], r[1], r[2] if len(r) > 2 else None) for r in rows]
    try:
        if path.lower().endswith(".stl"):
            mesh = Mesh.Mesh()
            for _n, sh, _c in rows:
                mesh.addMesh(mesh_of(sh, dev, ang))
            mesh.write(path)
            return True, "Saved %s (%d triangles)." % (os.path.basename(path), mesh.CountFacets)
        n = write_3mf(rows, path, dev, ang)
        cols = len({c for _n, _s, c in rows if c})
        return True, "Saved %s (%d objects, %d colours, %d triangles)." % (os.path.basename(path), len(rows), cols, n)
    except Exception as error:
        return False, "Could not save %s: %s" % (os.path.basename(path), error)


def show(objects=None):
    """File > Print3D."""
    if Print3DPanel.current is not None:
        return Print3DPanel.current
    if Gui.Control.activeDialog():
        try:
            from . import slicerui
            if slicerui.SlicerPanel.current is not None:
                slicerui.SlicerPanel.current.reject()
                Gui.Control.closeDialog()
        except Exception as error:
            _fw_log("close slicer panel", error)
    if Gui.Control.activeDialog():
        try:
            from . import slicerui
            # sl174: as every command since A510: the open PropertyManager is cancelled and Print3D starts
            if not slicerui.cancel_open_pm():
                App.Console.PrintWarning("Print3D: close the open PropertyManager first.\n")
                slicerui.busy_box("Print3D")
                return None
        except Exception as error:
            _fw_log("print3d busy box", error)
            return None
    panel = Print3DPanel(objects)
    Gui.Control.showDialog(panel)
    return panel


# ---------------------------------------------------------------------- Tools > Options > Export > Print3D Printers
def options_sections():
    """The Options page's sections: the printer profiles Print3D lists."""
    return [("Printers", [ProfilesSetting()])]


def _profiles_setting_base():
    from .sketchoptions import Setting
    return Setting


class ProfilesSetting(_profiles_setting_base()):
    """Print3D's printer profiles in Tools > Options: a list with New, Copy From Slicer, Delete, and each one's
    bed size, nozzle, minimum wall, overhang angle, resolution and slicer. Written when the Options box is OK'd."""

    FIELDS = (("x", "Bed X", " mm", 10, 2000, 1), ("y", "Bed Y", " mm", 10, 2000, 1), ("z", "Bed Z", " mm", 10, 2000, 1),
              ("nozzle", "Nozzle", " mm", 0.1, 2.0, 2), ("min_wall", "Minimum wall", " mm", 0.1, 20, 2),
              ("overhang", "Overhang threshold", " deg", 5, 85, 0))

    def __init__(self):
        super().__init__("", "print3d:profiles", "[]", "Print3D printers",
                         "The printers Print3D lists, with their bed and print limits")
        self.rows = []
        self._busy = False

    def widget(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        left = QtWidgets.QVBoxLayout()
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWStyle_Print3DProfiles")
        self.list.setMinimumWidth(180)
        self.list.currentRowChanged.connect(self._show)
        left.addWidget(self.list)
        row = QtWidgets.QHBoxLayout()
        self.new_button = QtWidgets.QPushButton("New")
        self.new_button.setToolTip("Add a printer profile")
        self.new_button.clicked.connect(self.new)
        self.copy_button = QtWidgets.QPushButton("From Slicer")
        self.copy_button.setToolTip("Add the printer each slicer has picked in its 3D Slicer tab, with its bed size")
        self.copy_button.clicked.connect(self.from_slicers)
        self.delete_button = QtWidgets.QPushButton("Delete")
        self.delete_button.setToolTip("Delete the selected profile")
        self.delete_button.clicked.connect(self.delete)
        for b in (self.new_button, self.copy_button, self.delete_button):
            row.addWidget(b)
        left.addLayout(row)
        lay.addLayout(left)
        self.form_box = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(self.form_box)
        self.name = QtWidgets.QLineEdit()
        self.name.setObjectName("SWStyle_Print3DProfileName")
        self.name.textEdited.connect(self._edited)
        form.addRow("Name:", self.name)
        self.spins = {}
        for key, label, suffix, lo, hi, dec in self.FIELDS:
            sp = _spin(lo, hi, PROFILE_DEFAULT[key], suffix, dec, 1 if dec == 0 else 10 ** -dec * 5)
            sp.valueChanged.connect(self._edited)
            self.spins[key] = sp
            form.addRow(label + ":", sp)
        self.res = QtWidgets.QComboBox()
        self.res.addItems(["Coarse", "Fine", "Custom"])
        self.res.setToolTip("Export resolution Print3D uses with this printer (Custom: Export Options' deviation and angle)")
        self.res.currentIndexChanged.connect(self._edited)
        form.addRow("Resolution:", self.res)
        self.slicer = QtWidgets.QComboBox()
        self.slicer.addItem("None", "")
        try:
            from . import slicer as backend
            for key in ("orca", "bambu", "prusa"):
                if backend.get(key) is not None:
                    self.slicer.addItem(backend.get(key).title, key)
        except Exception as error:
            _fw_log("profile slicers", error)
        self.slicer.setToolTip("The slicer Print3D's Send to Slicer picks for this printer")
        self.slicer.currentIndexChanged.connect(self._edited)
        form.addRow("Slicer:", self.slicer)
        self.empty = QtWidgets.QLabel("No printer profiles yet: New adds one, From Slicer adds the slicers' printers.")
        self.empty.setWordWrap(True)
        form.addRow(self.empty)
        lay.addWidget(self.form_box, 1)
        self.box = w
        return w

    # the rows
    def _fill(self, select=0):
        self._busy = True
        self.list.clear()
        for r in self.rows:
            self.list.addItem(r["name"])
        self._busy = False
        has = bool(self.rows)
        self.empty.setVisible(not has)
        for wdg in [self.name, self.res, self.slicer, self.delete_button] + list(self.spins.values()):
            wdg.setVisible(has)
            lbl = self.form_box.layout().labelForField(wdg)
            if lbl is not None:
                lbl.setVisible(has)
        self.delete_button.setVisible(has)
        if has:
            self.list.setCurrentRow(max(0, min(select, len(self.rows) - 1)))

    def _show(self, i):
        if self._busy or not (0 <= i < len(self.rows)):
            return
        r = self.rows[i]
        self._busy = True
        self.name.setText(r["name"])
        for key, sp in self.spins.items():
            sp.setValue(float(r.get(key, PROFILE_DEFAULT[key])))
        self.res.setCurrentText(r.get("resolution") or "Fine")
        self.slicer.setCurrentIndex(max(0, self.slicer.findData(r.get("slicer") or "")))
        self._busy = False

    def _edited(self, *_a):
        i = self.list.currentRow()
        if self._busy or not (0 <= i < len(self.rows)):
            return
        r = self.rows[i]
        r["name"] = self.name.text().strip() or r["name"]
        for key, sp in self.spins.items():
            r[key] = sp.value()
        r["resolution"] = self.res.currentText()
        r["slicer"] = self.slicer.currentData() or ""
        self.list.item(i).setText(r["name"])

    def _unique(self, name):
        names = {r["name"] for r in self.rows}
        out, k = name, 2
        while out in names:
            out = "%s %d" % (name, k)
            k += 1
        return out

    def new(self):
        r = dict(PROFILE_DEFAULT)
        r["name"] = self._unique("Printer")
        self.rows.append(r)
        self._fill(len(self.rows) - 1)
        self.name.setFocus()
        self.name.selectAll()

    def from_slicers(self):
        added = 0
        for key, label, size in slicer_beds():
            if any(r["name"] == label for r in self.rows):
                continue
            r = dict(PROFILE_DEFAULT)
            r.update(name=label, x=size[0], y=size[1], z=size[2], slicer=key)
            self.rows.append(r)
            added += 1
        self._fill(len(self.rows) - 1)
        if not added:
            self.empty.setText("Every slicer's printer is listed already (or no slicer has a printer picked yet).")
            self.empty.setVisible(True)

    def delete(self):
        i = self.list.currentRow()
        if 0 <= i < len(self.rows):
            del self.rows[i]
            self._fill(i)

    # the Options box
    def value(self):
        import json
        return json.dumps(self.rows, sort_keys=True)

    def load(self):
        self.rows = [dict(r) for r in profiles()]
        self._fill(0)
        self.loaded = self.value()

    def save(self):
        if self.changed():
            set_profiles(self.rows)
            self.loaded = self.value()
