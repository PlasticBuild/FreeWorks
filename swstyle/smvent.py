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
from PySide import QtCore, QtGui, QtWidgets

from . import naming, smfavorite
from .smbaseflange import _box, _spin
from .smedgeflange import error_label
from .smrip import _part_body
from .smunfold import _DeleteKey, _icon, _list

COMMAND = "SWStyle_SMVent"
TITLE = "Vent"
GROUP = "Vent"
ICON = "SheetMetal_AddCutout"
V = App.Vector
EPS = 1e-3
MESSAGE = "Select 2D sketch segments that define boundary, ribs, spars and support boundary to insert a vent."
ROLES = ("Boundary", "Ribs", "Spars", "FillIn")
INCH = 25.4


# ================================================================ geometry
def _edges(links):
    """The sketch edges of a link list [(sketch, ("Edge1", ...))], in place."""
    out = []
    for obj, subs in links or []:
        for sub in subs:
            if sub.startswith("Edge"):
                try:
                    out.append(obj.Shape.getElement(sub))
                except Exception as _fw_err:
                    _fw_log("smvent.py:65", _fw_err)
    return out


def _flat(edges, plane_point, n):
    """The edges moved along n onto the face's plane."""
    out = []
    for e in edges:
        c = e.copy()
        c.translate(n * (plane_point - e.Vertexes[0].Point).dot(n) if e.Vertexes else V())
        out.append(c)
    return out


def _region(edges):
    """The faces of the closed outlines the edges make (holes inside them kept)."""
    if not edges:
        return None
    wires = [w for w in (Part.Wire(g) for g in Part.sortEdges(edges)) if w.isClosed()]
    if not wires:
        return None
    return Part.makeFace(wires, "Part::FaceMakerBullseye")


def _bands(edges, width, n):
    """Bands width wide centred on each edge (ribs, spars), in the plane square to n."""
    bands = []
    for e in edges:
        w = Part.Wire([e])
        try:
            if e.Curve.TypeId == "Part::GeomLine":
                a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
                side = n.cross(b - a).normalize() * (width / 2.0)
                band = Part.Face(Part.makePolygon([a + side, b + side, b - side, a - side, a + side]))
            elif w.isClosed():
                band = Part.Face(w.makeOffset2D(width / 2.0)).cut(Part.Face(w.makeOffset2D(-width / 2.0)))
            else:
                band = w.makeOffset2D(width / 2.0, 0, True, True, False)
        except Exception:
            band = None
        if band is not None and not band.isNull():
            bands.append(band)
    if not bands:
        return None
    out = bands[0]
    for b in bands[1:]:
        out = out.fuse(b)
    return out


def taper(region, n, depth, grow):
    """The solid swept from the flat faces of region along -n by depth, its outline grown by grow at the
    bottom (shrunk when grow < 0): a drafted extrude."""
    solids = []
    for face in region.Faces:
        if abs(grow) < 1e-9:
            solids.append(face.extrude(n * -depth))
            continue
        outer = face.OuterWire

        def loft(w, d):
            w2 = w.makeOffset2D(d, 2, False, False, False)
            w2.translate(n * -depth)
            return Part.makeLoft([w, w2], True, True)
        s = loft(outer, grow)
        for w in face.Wires:
            if not w.isSame(outer):
                s = s.cut(loft(w, -grow))
        solids.append(s)
    out = solids[0]
    for s in solids[1:]:
        out = out.fuse(s)
    return out


def thickness_at(shape, face, n):
    """The wall's thickness under a flat face (outward normal n)."""
    p = face.distToShape(Part.Vertex(face.CenterOfMass))[1][0][0]
    ray = Part.LineSegment(p + n * EPS, p - n * shape.BoundBox.DiagonalLength).toShape()
    inside = shape.common(ray)
    return inside.Edges[0].Length if inside.Edges else None


def outward(shape, f):
    """The face's normal pointing out of the part: a vote over points spread on the face (one point off its centre
    could land on a rib or boss on the far side and flip it: a vent that added material, housing hs_check)."""
    n = f.normalAt(0, 0)
    pts = [f.distToShape(Part.Vertex(f.CenterOfMass))[1][0][0]]
    try:
        u0, u1, v0, v1 = f.ParameterRange
        for i in range(1, 5):
            for j in range(1, 5):
                u, v = u0 + (u1 - u0) * i / 5.0, v0 + (v1 - v0) * j / 5.0
                if f.isInside(f.valueAt(u, v), 1e-6, True):
                    pts.append(f.valueAt(u, v))
    except Exception as _fw_err:
        _fw_log("smvent.py:outward", _fw_err)
    out = sum(1 for p in pts if not shape.isInside(p + n * EPS, 1e-7, True))
    return n if out * 2 >= len(pts) else n * -1


def vent(shape, face, boundary, ribs=(), spars=(), fill=(), rib=(1.27, 5.08, 0.0), spar=(1.27, 2.032, 0.0),
         fill_in=(1.27, 0.0), fillet=0.0, draft=0.0, inward=False):
    """(the part with the vent, boundary area, open area). rib/spar: (depth, width, offset);
    fill_in: (depth, offset); draft: the walls' angle in degrees (0 = none)."""
    lean = math.tan(math.radians(draft)) * (1.0 if inward else -1.0)   # growth of solid parts per mm down
    n = outward(shape, face)
    p0 = face.Vertexes[0].Point
    t = thickness_at(shape, face, n) or 1.0
    bound = _region(_flat(boundary, p0, n))
    if bound is None:
        raise ValueError("The vent's boundary must be a closed outline.")
    solid2d = []
    adds = []
    for edges, (depth, width, offset) in ((ribs, rib), (spars, spar)):
        band = _bands(_flat(edges, p0, n), width, n) if edges else None
        if band is not None:
            band = band.common(bound)
            if band.Faces:
                solid2d.append(band)
                adds.append((band, depth, offset))
    if fill:
        f = _region(_flat(fill, p0, n))
        if f is None:
            raise ValueError("The fill-in boundary must be a closed outline.")
        f = f.common(bound)
        solid2d.append(f)
        adds.append((f, fill_in[0], fill_in[1]))
    hole = bound.copy()
    hole.translate(n * EPS)
    try:
        out = shape.cut(taper(hole, n, t + 2 * EPS, -lean * (t + 2 * EPS)))
        for region, depth, offset in adds:
            if depth <= 0:
                continue
            r = region.copy()
            r.translate(n * -offset)
            out = out.fuse(taper(r, n, depth, lean * depth))
    except Part.OCCError:
        raise ValueError("The draft angle is too big for this vent.")
    out = out.removeSplitter()
    if fillet > 0:
        out = _round(out, bound, n, t, fillet, draft)
    opening = bound
    for x in solid2d:       # cut one by one: a fuse of overlapping flat faces is not reliable
        opening = opening.cut(x)
    return out, bound.Area, opening.Area


def _round(shape, bound, n, t, r, draft=0.0):
    """Fillet radius: the vent's inside corners (edges across the wall, inside the boundary) rounded."""
    grow = math.tan(math.radians(draft)) * t + 2 * EPS
    zone = bound.copy()
    zone.translate(n * 2 * EPS)
    zone = taper(zone, n, t + 4 * EPS, grow) if draft else zone.extrude(n * -(t + 4 * EPS))
    tilt = math.cos(math.radians(draft)) - 1e-6
    edges = []
    for e in shape.Edges:
        if e.Curve.TypeId != "Part::GeomLine":
            continue
        d = e.Vertexes[-1].Point - e.Vertexes[0].Point
        if d.Length < EPS or abs(d.normalize().dot(n)) < tilt:
            continue
        if zone.isInside(e.CenterOfMass, 1e-6, True):
            edges.append(e)
    if not edges:
        return shape
    try:
        return shape.makeFillet(r, edges)
    except Exception:
        raise ValueError("The fillet radius is too big for this vent.")


def face_at(shape, p, normal=None):
    vp = Part.Vertex(p)
    best = None
    for i, f in enumerate(shape.Faces):
        if f.Surface.TypeId != "Part::GeomPlane":
            continue
        if normal is not None and abs(abs(f.normalAt(0, 0).dot(normal)) - 1) > 1e-7:
            continue
        d = f.distToShape(vp)[0]
        if d < 1e-4 and (best is None or d < best[0]):
            best = (d, i)
    return best[1] if best else None


# ================================================================ feature
_LAST = None        # the open Vent PropertyManager


class SWVent:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyLinkSubList", "Boundary", GROUP, "Boundary: a closed sketch outline")
        add("App::PropertyLinkSubList", "Ribs", GROUP, "Ribs: sketch lines")
        add("App::PropertyLinkSubList", "Spars", GROUP, "Spars: sketch curves")
        add("App::PropertyLinkSubList", "FillIn", GROUP, "Fill-in boundary: a closed sketch outline")
        add("App::PropertyString", "Face", GROUP, "The face the vent goes on")
        add("App::PropertyVector", "FacePoint", GROUP, "A point on the face")
        add("App::PropertyVector", "FaceNormal", GROUP, "The face's normal")
        _draft_props(obj)
        add("App::PropertyLength", "FilletRadius", GROUP, "Rounds the vent's inside corners")
        for role in ("Rib", "Spar", "Fill"):
            add("App::PropertyLength", role + "Depth", GROUP, role + " depth into the part")
            add("App::PropertyDistance", role + "Offset", GROUP, role + " offset from the face")
        add("App::PropertyLength", "RibWidth", GROUP, "Rib width")
        add("App::PropertyLength", "SparWidth", GROUP, "Spar width")
        add("App::PropertyFloat", "FlowArea", GROUP, "Area inside the boundary (mm^2)")
        add("App::PropertyFloat", "OpenArea", GROUP, "Open part of the area (%)")
        for name in ("FlowArea", "OpenArea"):
            obj.setEditorMode(name, 1)
        from .smbaseflange import inch_part
        inch = inch_part(obj.Document)                  # round inch sizes in an inch part, round mm otherwise
        obj.RibDepth = obj.SparDepth = obj.FillDepth = 0.05 * INCH if inch else 1.25
        obj.RibWidth = 0.20 * INCH if inch else 5.0
        obj.SparWidth = 0.08 * INCH if inch else 2.0
        obj.Proxy = self

    def execute(self, obj):
        _draft_props(obj)
        base = obj.BaseFeature
        if base is None:
            raise ValueError("Vent: needs a part")
        shape = base.Shape.copy()
        boundary = _edges(obj.Boundary)
        if not boundary or not obj.Face:
            obj.Shape = shape
            return
        i = face_at(shape, obj.FacePoint, obj.FaceNormal)
        if i is None:
            raise ValueError("Vent: the face is gone; edit the feature and pick it again")
        out, area, open_area = vent(
            shape, shape.Faces[i], boundary, _edges(obj.Ribs), _edges(obj.Spars), _edges(obj.FillIn),
            (float(obj.RibDepth), float(obj.RibWidth), float(obj.RibOffset)),
            (float(obj.SparDepth), float(obj.SparWidth), float(obj.SparOffset)),
            (float(obj.FillDepth), float(obj.FillOffset)), float(obj.FilletRadius),
            float(obj.DraftAngle) if obj.DraftOn else 0.0, bool(obj.DraftInward))
        obj.FlowArea = area
        obj.OpenArea = 100.0 * open_area / area if area > 0 else 0.0
        obj.Shape = out

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _draft_props(obj):
    """Draft On/Off, angle and inward (older vents had the angle and inward read-only)."""
    if "DraftOn" not in obj.PropertiesList:
        obj.addProperty("App::PropertyBool", "DraftOn", GROUP, "Draft On/Off")
        if "DraftAngle" not in obj.PropertiesList:
            obj.addProperty("App::PropertyAngle", "DraftAngle", GROUP, "Draft angle")
            obj.DraftAngle = 1.0
        if "DraftInward" not in obj.PropertiesList:
            obj.addProperty("App::PropertyBool", "DraftInward", GROUP, "Draft inward")
        for name in ("DraftAngle", "DraftInward"):
            obj.setEditorMode(name, 0)


# the values a Vent favorite keeps
FAVORITE = ("DraftOn", "DraftAngle", "DraftInward", "FilletRadius", "RibDepth", "RibWidth", "RibOffset",
            "SparDepth", "SparWidth", "SparOffset", "FillDepth", "FillOffset")


def is_vent(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWVent"


def _sketches(obj):
    out = []
    for role in ROLES:
        for o, _subs in getattr(obj, role) or []:
            if o not in out:
                out.append(o)
    return out


class ViewProviderVent:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return _icon(ICON)

    def claimChildren(self):
        return _sketches(self.Object)

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
    obj = doc.addObject("PartDesign::FeaturePython", "Vent")
    SWVent(obj)
    if App.GuiUp:
        ViewProviderVent(obj.ViewObject)
    body.addObject(obj)
    obj.Label = naming.next_label(doc, "Vent")
    if base is not None:
        try:
            base.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("smvent.py:379", _fw_err)
    return obj


# ================================================================ PropertyManager
def _loop(sketch, sub):
    """The edges of the closed loop of sketch that edge sub is on (just sub when it is on none)."""
    edge = sketch.Shape.getElement(sub)
    for w in sketch.Shape.Wires:
        if w.isClosed() and any(e.isSame(edge) for e in w.Edges):
            return ["Edge%d" % (k + 1) for k, e in enumerate(sketch.Shape.Edges) if any(e.isSame(x) for x in w.Edges)]
    return [sub]


class Panel:
    """The Vent PropertyManager."""

    def __init__(self, obj, new):
        global _LAST
        _LAST = self
        self.obj = obj
        self.new = new
        self.pick_error = ""
        boundary = _box("Boundary")
        f = boundary.layout()
        self.error = error_label()
        f.addRow(self.error)
        self.boundary = _list("SWSMVentBoundary", "#d6ecff", "Boundary: a closed sketch outline", rows=2)
        f.addRow(self.boundary)

        geo = _box("Geometry Properties")
        f = geo.layout()
        self.face = _list("SWSMVentFace", "#d6ecff", "The face the vent goes on")
        f.addRow(self.face)
        _draft_props(obj)
        self.draft_on = QtWidgets.QToolButton()
        self.draft_on.setObjectName("SWSMVentDraftOn")
        self.draft_on.setCheckable(True)
        self.draft_on.setChecked(bool(obj.DraftOn))
        self.draft_on.setIcon(QtGui.QIcon(":/icons/PartDesign_Draft.svg"))
        self.draft_on.setToolTip("Draft On/Off")
        self.draft = _spin("SWSMVentDraft", float(obj.DraftAngle), 0.0, 45.0, suffix=" deg", step=1.0)
        self.draft.setToolTip("Draft angle")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.draft_on)
        row.addWidget(self.draft, 1)
        f.addRow(row)
        self.inward = QtWidgets.QCheckBox("Draft inward")
        self.inward.setObjectName("SWSMVentDraftInward")
        self.inward.setChecked(bool(obj.DraftInward))
        self.inward.setToolTip("Leans the walls the other way: solid parts get wider going into the part")
        f.addRow(self.inward)
        self.fillet = _spin("SWSMVentFillet", float(obj.FilletRadius), 0.0, 1000.0, step=0.1)
        self.fillet.setToolTip("Fillet radius")
        f.addRow("Fillet radius:", self.fillet)
        self.preview = QtWidgets.QCheckBox("Show preview")
        self.preview.setObjectName("SWSMVentPreview")
        self.preview.setChecked(True)
        f.addRow(self.preview)

        flow = _box("Flow Area")
        f = flow.layout()
        self.area = QtWidgets.QLabel()
        self.area.setObjectName("SWSMVentArea")
        self.open_area = QtWidgets.QLabel()
        self.open_area.setObjectName("SWSMVentOpen")
        f.addRow(self.area)
        f.addRow(self.open_area)

        self.spins = {}
        boxes = []
        for role, title, tip, has_width in (("Ribs", "Ribs", "Ribs: sketch lines", True),
                                            ("Spars", "Spars", "Spars: sketch curves", True),
                                            ("FillIn", "Fill-In Boundary", "Fill-in boundary: a closed outline", False)):
            b = _box(title)
            f = b.layout()
            lst = _list("SWSMVent" + role, "#ffd6ec", tip, rows=2)
            f.addRow(lst)
            key = {"Ribs": "Rib", "Spars": "Spar", "FillIn": "Fill"}[role]
            depth = _spin("SWSMVent%sDepth" % key, float(getattr(obj, key + "Depth")), 0.0, 1000.0, step=0.1)
            depth.setToolTip("Depth")
            f.addRow("Depth:", depth)
            if has_width:
                width = _spin("SWSMVent%sWidth" % key, float(getattr(obj, key + "Width")), 0.0, 1000.0, step=0.1)
                width.setToolTip("Width")
                f.addRow("Width:", width)
                self.spins[key + "Width"] = width
            offset = _spin("SWSMVent%sOffset" % key, float(getattr(obj, key + "Offset")), -1000.0, 1000.0, step=0.1)
            offset.setToolTip("Offset from the face")
            f.addRow("Offset:", offset)
            self.spins[key + "Depth"] = depth
            self.spins[key + "Offset"] = offset
            setattr(self, role.lower(), lst)
            boxes.append(b)

        fav = _box("Favorite")
        f = fav.layout()
        self.favorites = smfavorite.FavoriteRows(f, "Vent", "SWSMVent", self._values, self._load_values)
        self.favorite = self.favorites.combo

        boundary.setProperty("swstyle_pm_title", TITLE)
        boundary.setProperty("swstyle_pm_icon", ICON)
        self.form = [boundary, geo, flow] + boxes + [fav]
        self.lists = {"Boundary": self.boundary, "Ribs": self.ribs, "Spars": self.spars, "FillIn": self.fillin}
        self.active = self.boundary
        self._mark()
        self.keys = _DeleteKey(self)
        for w in list(self.lists.values()) + [self.face]:
            w.installEventFilter(self.keys)
        for s in list(self.spins.values()) + [self.fillet, self.draft]:
            s.valueChanged.connect(self._changed)
        for b in (self.draft_on, self.inward):
            b.toggled.connect(self._changed)
        self.preview.toggled.connect(self._show_preview)
        self._show_draft()
        self._fill()
        self._report()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    # ---------------------------------------------------------------- lists
    def set_active(self, w):
        if w in self.lists.values() or w is self.face:
            self.active = w
            self._mark()

    def _mark(self):
        ""
        from . import pmboxes
        for b in (self.boundary, self.face):
            pmboxes.mark(b, b is self.active)

    def _role(self, w):
        return next((r for r, lst in self.lists.items() if lst is w), None)

    def _fill(self):
        for role, lst in self.lists.items():
            lst.clear()
            for o, subs in getattr(self.obj, role) or []:
                for s in subs:
                    lst.addItem("%s@%s" % (s, o.Label))
        self.face.clear()
        if self.obj.Face:
            self.face.addItem(self.obj.Face)
        self.area.setText("Area = %.2f square mm" % self.obj.FlowArea)
        self.open_area.setText("Open area = %.2f %%" % self.obj.OpenArea)

    def remove_current(self, w):
        if w is self.face:
            self.obj.Face = ""
        else:
            role = self._role(w)
            if role is None or w.currentRow() < 0:
                return
            flat = [(o, s) for o, subs in getattr(self.obj, role) or [] for s in subs]
            del flat[w.currentRow()]
            self._set(role, flat)
        self._apply()

    def _set(self, role, flat):
        links = []
        for o, s in flat:
            if links and links[-1][0] is o:
                links[-1] = (o, links[-1][1] + (s,))
            else:
                links.append((o, (s,)))
        setattr(self.obj, role, links)

    # ---------------------------------------------------------------- picks
    def addSelection(self, doc, name, sub, point):
        at = App.Vector(*point) if point else None
        QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub, at))

    def _picked(self, doc_name, name, sub, at):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smvent.py:556", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None:
            return
        self.pick_error = ""
        if picked.TypeId == "Sketcher::SketchObject" and sub.startswith("Edge"):
            if self.active is self.face:
                self.set_active(self.boundary)
            role = self._role(self.active)
            subs = _loop(picked, sub) if role in ("Boundary", "FillIn") else [sub]
            flat = [(o, s) for o, ss in getattr(self.obj, role) or [] for s in ss]
            if any(o is picked and s == sub for o, s in flat):
                flat = [(o, s) for o, s in flat if not (o is picked and s in subs)]
            else:
                flat += [(picked, s) for s in subs if not any(o is picked and x == s for o, x in flat)]
            self._set(role, flat)
            if role == "Boundary" and not self.obj.Face:
                self._auto_face(picked)
                self.set_active(self.ribs)
            try:
                picked.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("smvent.py:578", _fw_err)
        elif sub.startswith("Face"):
            face = picked.Shape.getElement(sub)
            if face.Surface.TypeId != "Part::GeomPlane":
                self.pick_error = "Select a flat face for the vent."
            else:
                if at is None or face.distToShape(Part.Vertex(at))[0] > 1e-4:
                    at = face.distToShape(Part.Vertex(face.CenterOfMass))[1][0][0]
                self._set_face(at, face.normalAt(0, 0))
        self._apply()

    def _set_face(self, at, normal):
        base = self.obj.BaseFeature.Shape
        i = face_at(base, at, normal)
        if i is None:
            self.pick_error = "Select a flat face of the part."
            return
        self.obj.Face = "Face%d" % (i + 1)
        self.obj.FacePoint = at
        self.obj.FaceNormal = base.Faces[i].normalAt(0, 0)

    def _auto_face(self, sketch):
        """The face under the sketch: the part's flat face the boundary lies on, or the nearest one parallel."""
        base = self.obj.BaseFeature.Shape
        edges = _edges(self.obj.Boundary)
        if not edges:
            return
        pl = sketch.getGlobalPlacement()
        n = pl.Rotation.multVec(V(0, 0, 1))
        c = edges[0].CenterOfMass
        best = None
        for i, f in enumerate(base.Faces):
            if f.Surface.TypeId != "Part::GeomPlane" or abs(abs(f.normalAt(0, 0).dot(n)) - 1) > 1e-7:
                continue
            p = c + n * (f.Vertexes[0].Point - c).dot(n)
            if not f.isInside(p, 1e-6, True):
                continue
            d = abs((f.Vertexes[0].Point - c).dot(n))
            if best is None or d < best[0]:
                best = (d, i, p)
        if best is not None:
            self._set_face(best[2], base.Faces[best[1]].normalAt(0, 0))

    # ---------------------------------------------------------------- result
    def _changed(self, *_a):
        for name, spin in self.spins.items():
            setattr(self.obj, name, spin.value())
        self.obj.FilletRadius = self.fillet.value()
        self.obj.DraftOn = self.draft_on.isChecked()
        self.obj.DraftAngle = self.draft.value()
        self.obj.DraftInward = self.inward.isChecked()
        self._show_draft()
        self._apply()

    def _show_draft(self):
        self.draft.setEnabled(self.draft_on.isChecked())
        self.inward.setEnabled(self.draft_on.isChecked())

    def _values(self):
        """The values a favorite keeps."""
        return {name: (bool(getattr(self.obj, name)) if isinstance(getattr(self.obj, name), bool)
                       else float(getattr(self.obj, name))) for name in FAVORITE}

    def _load_values(self, values):
        boxes = dict(self.spins, FilletRadius=self.fillet, DraftAngle=self.draft)
        for w in list(boxes.values()) + [self.draft_on, self.inward]:
            w.blockSignals(True)
        for name, v in values.items():
            if name in boxes:
                boxes[name].setValue(float(v))
        self.draft_on.setChecked(bool(values.get("DraftOn", self.draft_on.isChecked())))
        self.inward.setChecked(bool(values.get("DraftInward", self.inward.isChecked())))
        for w in list(boxes.values()) + [self.draft_on, self.inward]:
            w.blockSignals(False)
        self._changed()

    def _apply(self):
        doc = self.obj.Document
        if doc.Recomputing:
            QtCore.QTimer.singleShot(50, self._apply)
            return
        self.obj.touch()
        doc.recompute()
        self._fill()
        self._report()

    def _show_preview(self, on):
        try:
            self.obj.ViewObject.Visibility = on
            self.obj.BaseFeature.ViewObject.Visibility = not on
        except Exception as _fw_err:
            _fw_log("smvent.py:669", _fw_err)

    def _report(self):
        if "Invalid" in self.obj.State:
            text = self.obj.getStatusString()
        elif self.pick_error:
            text = self.pick_error
        elif not self.obj.Boundary:
            text = MESSAGE
        elif not self.obj.Face:
            text = "Select the face the vent goes on."
        else:
            text = ""
        self.error.setText(text)
        self.error.setVisible(bool(text))
        return not text

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smvent.py:693", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smvent.py:699", _fw_err)

    def accept(self):
        self.pick_error = ""
        if not self._report():
            return False
        self._show_preview(True)
        for sk in _sketches(self.obj):
            try:
                sk.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("smvent.py:710", _fw_err)
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
                _fw_log("smvent.py:724", _fw_err)
        self._close()
        return True


# ================================================================ command
def start():
    body = _part_body()
    if body is None:
        return
    doc = body.Document
    sketches = [o.Object for o in Gui.Selection.getSelectionEx() if o.Object.TypeId == "Sketcher::SketchObject"]
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
    for sk in sketches:
        try:
            sk.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("smvent.py:745", _fw_err)


class Command:
    def GetResources(self):
        return {"Pixmap": _icon(ICON), "MenuText": TITLE,
                "ToolTip": "Cuts a vent from a sketch of a boundary, ribs, spars and a fill-in boundary."}

    def IsActive(self):
        return _part_body() is not None

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
