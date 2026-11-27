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

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import naming, pmboxes, sketchstart
from . import simplefeature as sf


def _error_css():
    ""
    try:
        from . import propertymanager
        return propertymanager.error_css()
    except Exception:
        return "color: #c00000;"

COMMAND = "SWStyle_Rib"
TYPE = "PartDesign::FeatureAdditivePython"
SKETCH = "Sketcher::SketchObject"
MESSAGE = "Select a plane or planar face on which to sketch the feature cross-section."

_watch = {"timer": None, "before": set(), "sketch": None, "ticks": 0}


# --------------------------------------------------------------------------- geometry
SIDES = ("Both", "First", "Second")
DIRECTIONS = ("Parallel", "Normal")
EXTENSIONS = ("Linear", "Natural")
REFERENCES = ("At sketch plane", "At wall interface")


def _slab(side, thickness, normal):
    """(start, end) offsets along the sketch normal for a thickness side."""
    if side == "First":
        return 0.0, thickness
    if side == "Second":
        return -thickness, 0.0
    return -thickness / 2.0, thickness / 2.0


def rib_solid(part, wire, normal, thickness, flip=False, side="Both", direction="Parallel",
              draft=0.0, outward=False, extension="Linear", reference="At sketch plane",
              reference_index=0, others=()):
    ""














    stop = _stops(wire, others)
    if direction == "Normal":
        return _normal_rib(part, wire, normal, thickness, flip, side, extension, stop)
    pieces = _regions(part, wire, normal, extension, stop)
    if not pieces:
        return None
    sides = {}
    for s_, face in pieces:
        sides.setdefault(s_, []).append(face)
    order = sorted(sides, reverse=not flip)
    faces = sides[order[0]]
    shift = App.Vector(normal)
    shift.normalize()
    low, high = _slab(side, thickness, normal)
    rib = None
    for face in faces:
        if draft > 1e-9:
            solid = _drafted(face, wire, shift, low, high, draft, outward, order[0],
                             part if reference == "At wall interface" else None, reference_index)
            if solid is None:
                raise RuntimeError("A rib draft needs one straight rib line")
        else:
            solid = face.extrude(shift * (high - low))
            solid.translate(shift * low)
        rib = solid if rib is None else rib.fuse(solid)
    return _meet_part(rib, part, thickness)


def _meet_part(rib, part, thickness):
    ""

    if rib is None:
        return None
    out = rib
    for face in rib.Faces:
        try:
            centre = face.CenterOfMass
            if Part.Vertex(centre).distToShape(part)[0] > 1e-6:
                continue
            n = face.normalAt(0, 0)
            n.normalize()
            if rib.isInside(centre + n * 1e-3, 1e-9, False):
                n = n * -1
            prism = face.extrude(n * thickness)
            # only the air between this end and the wall: what lies in the wall or past it stays out (a

            for gap in prism.cut(part).Solids:
                if gap.Volume > 1e-9 and gap.distToShape(face)[0] < 1e-6 and \
                        any(g.common(face).Area > 1e-9 for g in gap.Faces if g.Surface.TypeId == face.Surface.TypeId):
                    out = out.fuse(gap)
        except Exception:
            continue
    if out is not rib:
        try:
            out = out.removeSplitter()
        except Exception as _fw_err:
            _fw_log("rib.py:137", _fw_err)
    return out


def _drafted(face, wire, n, low, high, angle, outward, side, part=None, reference_index=0):
    """The face's rib with walls leaning by angle away from a straight line. The thickness is
    the rib's at the sketch line, or (part given: At wall interface) at the wall where the
    face meets the part; reference_index picks which wall when there are several (Next
    Reference)."""
    import math
    edges = wire.OrderedEdges
    if len(edges) != 1 or "Line" not in type(edges[0].Curve).__name__:
        return None
    a, b = edges[0].Vertexes[0].Point, edges[0].Vertexes[-1].Point
    u = b - a
    u.normalize()
    v = n.cross(u)
    v.normalize()
    if side < 0:
        v = v * -1.0
    reach = face.BoundBox.DiagonalLength * 2 + 1.0
    t = math.tan(math.radians(angle)) * (-1.0 if outward else 1.0)
    if part is not None:
        walls = [e for e in face.Edges
                 if Part.Vertex(e.valueAt((e.FirstParameter + e.LastParameter) / 2.0)).distToShape(wire)[0] > 1e-6
                 and e.distToShape(part)[0] < 1e-6]
        if walls:
            walls.sort(key=lambda e: (e.CenterOfMass - a).dot(v))
            wall = walls[reference_index % len(walls)]
            far = (wall.CenterOfMass - a).dot(v)         # the thickness holds at the wall's middle
            at_wall = far * t            # the walls have grown this much by the wall
            if low < 0:
                low += at_wall
            if high > 0:
                high -= at_wall
            if high - low < 1e-6:
                raise RuntimeError("The rib draft runs out of thickness before the sketch plane")
    grow = reach * t
    if outward:
        # the walls meet where the rib runs out of thickness
        reach = min(reach, (high - low) / 2.0 / abs(t)) if abs(t) > 1e-12 else reach
        grow = reach * t
    lo_far = low - grow if low < 0 else low
    hi_far = high + grow if high > 0 else high
    centre = a - u * (reach * 4)
    pts = [centre + n * low, centre + v * reach + n * lo_far, centre + v * reach + n * hi_far,
           centre + n * high]
    section = Part.Face(Part.makePolygon(pts + [pts[0]]))
    wedge = section.extrude(u * (reach * 8))
    lo = min(low, lo_far)
    hi = max(high, hi_far)
    slab = face.extrude(n * (hi - lo))
    slab.translate(n * lo)
    out = slab.common(wedge)
    return out if out.Volume > 1e-9 else None


def _stops(wire, others):
    """(start, end): whether each end of the line already meets another line of the sketch
    (then it is not carried on: that line's rib is the boundary it meets)."""
    vertexes = wire.OrderedVertexes
    out = []
    for p in (vertexes[0].Point, vertexes[-1].Point):
        v = Part.Vertex(p)
        out.append(any(v.distToShape(o)[0] < 1e-6 for o in others))
    return tuple(out)


def _normal_rib(part, wire, normal, thickness, flip, side, extension="Linear", stop=(False, False)):
    ""

    n = App.Vector(normal)
    n.normalize()
    vertexes = wire.OrderedVertexes
    a, b = vertexes[0].Point, vertexes[-1].Point
    u = b - a
    if u.Length < 1e-9:
        return None
    u.normalize()
    across = n.cross(u)
    across.normalize()
    reach = part.BoundBox.DiagonalLength * 2 + wire.BoundBox.DiagonalLength
    edges = wire.OrderedEdges
    head = [] if stop[0] else [_carry_on(edges[0], a, reach, extension)]
    tail = [] if stop[1] else [_carry_on(edges[-1], b, reach, extension)]
    try:
        long_wire = Part.Wire(Part.__sortEdges__(head + list(edges) + tail))
    except Exception:
        long_wire = Part.Wire(head + list(edges) + tail)
    foot = _band(wire, thickness, side, across)
    for line in (long_wire, wire):
        band = _band(line, thickness, side, across)
        if band is None or foot is None:
            return None
        for sign in ((-1.0, 1.0) if not flip else (1.0, -1.0)):
            prism = band.extrude(n * (sign * reach))
            try:
                rest = prism.cut(part)
            except Exception:
                continue
            box = part.BoundBox
            box.enlarge(1e-4)
            keep = [sol for sol in rest.Solids
                    if box.isInside(sol.BoundBox) and sol.distToShape(foot)[0] < 1e-5
                    and sol.distToShape(part)[0] < 1e-5]
            if keep:
                return keep[0] if len(keep) == 1 else keep[0].fuse(keep[1:])
    return None


def _band(line, thickness, side, across):
    """A flat strip as wide as the thickness along line (centred, or to one side). A single
    straight line has no plane of its own for FreeCAD's 2D offset: the strip is each edge
    pushed sideways in the sketch plane."""
    start = {"First": 0.0, "Second": -thickness}.get(side, -thickness / 2.0)
    strip = None
    for edge in line.Edges:
        face = edge.extrude(across * thickness)
        face.translate(across * start)
        strip = face if strip is None else strip.fuse(face)
    if strip is None:
        return None
    try:
        strip = strip.removeSplitter()
    except Exception as _fw_err:
        _fw_log("rib.py:262", _fw_err)
    return strip


def _carry_on(edge, point, reach, extension):
    """The edge carried on past point: its tangent line (Linear), or the rest of its circle
    (Natural, for an arc)."""
    if extension == "Natural" and isinstance(edge.Curve, Part.Circle):
        import math
        u0, u1 = edge.FirstParameter, edge.LastParameter
        if edge.Vertexes[0].Point.isEqual(point, 1e-7):
            arc = Part.ArcOfCircle(edge.Curve, u0 - (2 * math.pi - (u1 - u0)), u0)
        else:
            arc = Part.ArcOfCircle(edge.Curve, u1, u1 + (2 * math.pi - (u1 - u0)))
        return arc.toShape()
    return Part.LineSegment(point, point + _tangent(edge, point) * reach).toShape()


def _regions(part, wire, normal, extension="Linear", stop=(False, False)):
    """[(side, face)]: closed-off pieces of the sketch plane between the line and the part."""
    vertexes = wire.OrderedVertexes
    a, b = vertexes[0].Point, vertexes[-1].Point
    if a.isEqual(b, 1e-7):
        return []
    n = App.Vector(normal)
    n.normalize()
    across = n.cross(b - a)
    if across.Length < 1e-9:
        return []
    across.normalize()
    edges = wire.OrderedEdges
    reach = part.BoundBox.DiagonalLength * 2 + wire.BoundBox.DiagonalLength
    if len(edges) == 1 and extension == "Natural" and isinstance(edges[0].Curve, Part.Circle):
        cutter = [edges[0], _carry_on(edges[0], b, reach, extension)]    # one arc: the rest of its circle
    else:
        cutter = ([] if stop[0] else [_carry_on(edges[0], a, reach, extension)]) + list(edges) + \
                 ([] if stop[1] else [_carry_on(edges[-1], b, reach, extension)])
    centre = (a + b) * 0.5
    u = b - a
    u.normalize()
    size = reach * 3
    big = Part.makePlane(2 * size, 2 * size, centre - u * size - across * size, n, u)
    try:
        # one connected wire: loose edges meeting an arc at a tangent do not split the plane
        tool = Part.Wire(Part.__sortEdges__(cutter))
    except Exception:
        tool = Part.Compound(cutter)
    try:
        split = big.generalFuse([tool])[0]
    except Exception:
        return []
    out = []
    border = big.OuterWire
    for piece in split.Faces:
        try:
            rest = piece.cut(part)
        except Exception:
            continue
        for face in rest.Faces:
            if face.Area < 1e-9 or face.distToShape(wire)[0] > 1e-6:
                continue
            if face.distToShape(border)[0] < 1e-6:
                continue  # open space reaching the edge of the plane
            side = 1 if (face.CenterOfMass - centre).dot(across) >= 0 else -1
            out.append((side, face))
    return out


def _tangent(edge, point):
    """Unit tangent at the end of edge that is at point, pointing away from the edge."""
    if edge.Vertexes[0].Point.isEqual(point, 1e-7):
        t = edge.tangentAt(edge.FirstParameter) * -1
    else:
        t = edge.tangentAt(edge.LastParameter)
    t.normalize()
    return t


def _open_wires(sketch):
    ""

    try:
        edges = [e for e in sketch.Shape.Edges]
    except Exception:
        return []
    if not edges:
        return []
    wires = []
    for group in Part.sortEdges(edges):
        try:
            wires.append(Part.Wire(group))
        except Exception:
            # a network of lines meeting at junctions (E13-15): each line is a wall of its own
            for e in group:
                try:
                    wires.append(Part.Wire([e]))
                except Exception as _fw_err:
                    _fw_log("rib.py:359", _fw_err)
    return [w for w in wires if not w.isClosed()]


def _open_wire(sketch):
    wires = _open_wires(sketch)
    return wires[0] if wires else None


def _free_rib_line(sketch):
    ""


    try:
        edges = sketch.Shape.Edges
        if not edges:
            return False
        if any(Part.Wire(group).isClosed() for group in Part.sortEdges(edges)):
            return False
    except Exception as _fw_err:
        _fw_log("rib.py:380", _fw_err)
        return False
    for user in sketch.InList:
        if user.TypeId.startswith("PartDesign::") and user.TypeId != "PartDesign::Body":
            profile = getattr(user, "Profile", None)
            if profile and profile[0] is sketch:
                return False
    return True


# --------------------------------------------------------------------------- feature
def ensure(obj):
    ""
    have = obj.PropertiesList
    if "ThicknessSide" not in have:
        obj.addProperty("App::PropertyEnumeration", "ThicknessSide", "Rib", "First side, both sides or second side")
        obj.ThicknessSide = list(SIDES)
        obj.ThicknessSide = "Both"
    if "ExtrusionDirection" not in have:
        obj.addProperty("App::PropertyEnumeration", "ExtrusionDirection", "Rib", "Parallel to sketch or normal to sketch")
        obj.ExtrusionDirection = list(DIRECTIONS)
        obj.ExtrusionDirection = "Parallel"
    if "DraftOn" not in have:
        obj.addProperty("App::PropertyBool", "DraftOn", "Rib", "Draft the rib walls")
    if "DraftAngle" not in have:
        obj.addProperty("App::PropertyAngle", "DraftAngle", "Rib", "Draft angle")
        obj.DraftAngle = 1.0
    if "DraftOutward" not in have:
        obj.addProperty("App::PropertyBool", "DraftOutward", "Rib", "Draft outward")
    if "Extension" not in have:
        obj.addProperty("App::PropertyEnumeration", "Extension", "Rib", "Type: Linear carries the line's ends on straight, Natural carries an arc on round its circle")
        obj.Extension = list(EXTENSIONS)
        obj.Extension = "Linear"
    if "DraftReference" not in have:
        obj.addProperty("App::PropertyEnumeration", "DraftReference", "Rib",
                        "Where the thickness is measured with a draft: at the sketch plane or at the wall interface")
        obj.DraftReference = list(REFERENCES)
        obj.DraftReference = "At sketch plane"
    if "DraftReferenceIndex" not in have:
        obj.addProperty("App::PropertyInteger", "DraftReferenceIndex", "Rib",
                        "Next Reference: which wall the thickness is measured at")


class RibFeature:
    def __init__(self, obj):
        obj.addProperty("App::PropertyLink", "Sketch", "Rib", "Sketch with the open rib line")
        obj.addProperty("App::PropertyLength", "Thickness", "Rib", "Rib thickness, centered on the sketch plane")
        obj.addProperty("App::PropertyBool", "Flip", "Rib", "Fill on the other side of the line")
        obj.Thickness = 10.0
        ensure(obj)
        obj.Proxy = self

    def execute(self, obj):
        base = obj.BaseFeature.Shape if obj.BaseFeature is not None else None
        sketch = obj.Sketch
        if base is None or base.isNull() or sketch is None:
            raise RuntimeError("Rib needs a part to attach to and a sketch")
        wires = _open_wires(sketch)
        if not wires:
            raise RuntimeError("Rib needs a sketch with an open line or chain of lines")
        normal = sketch.Placement.Rotation.multVec(App.Vector(0, 0, 1))
        ensure(obj)
        from . import fcache
        ckey = fcache.key(obj, base)
        hit = fcache.get(ckey)
        if hit is not None:
            sf.store(obj, hit[0], hit[1])
            return
        rib = None
        for wire in wires:
            one = rib_solid(base, wire, normal, float(obj.Thickness), obj.Flip, obj.ThicknessSide,
                            obj.ExtrusionDirection, float(obj.DraftAngle) if obj.DraftOn else 0.0,
                            bool(obj.DraftOutward), obj.Extension, obj.DraftReference,
                            int(obj.DraftReferenceIndex), [w for w in wires if w is not wire])
            if one is None:
                continue
            rib = one if rib is None else rib.fuse(one)
        if rib is None:
            raise RuntimeError("The rib line does not close a region against the part")
        result = base.fuse(rib)
        try:
            result = result.removeSplitter()
        except Exception as _fw_err:
            _fw_log("rib.py:461", _fw_err)
        solids = result.Solids
        final = solids[0] if len(solids) == 1 else Part.makeCompound(solids)
        fcache.put(fcache.key(obj, base), final, rib)    # inputs as the build leaves them
        sf.store(obj, final, rib)

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        ensure(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class RibView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        try:
            from . import icons
            icon = icons.family("FEATURES_RIB")
            if not icon.isNull():
                return icon         # a QIcon: FreeCAD reads a returned QPixmap as a QIcon
        except Exception as _fw_err:
            _fw_log("rib.py:492", _fw_err)
        return ":/icons/PartDesign_Pad.svg"

    def claimChildren(self):
        # FreeCAD asks before attach() when a saved part opens (the view's class comes back later)
        sketch = getattr(getattr(self, "Object", None), "Sketch", None)
        return [sketch] if sketch is not None else []

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        Gui.Control.showDialog(RibPanel(vobj.Object, new=False))
        return True

    def unsetEdit(self, vobj, mode=0):
        Gui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _side_icon(kind):
    ""
    from PySide import QtGui
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pm = _hidpi.canvas(22, 22)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    grey, blue = QtGui.QColor(120, 120, 120), QtGui.QColor(40, 110, 220)
    p.setPen(QtGui.QPen(grey, 1.5, QtCore.Qt.DashLine))
    if kind in ("First", "Both", "Second"):
        p.drawLine(11, 2, 11, 20)                      # the sketch line seen end on
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(blue)
        x = {"First": 11, "Both": 7, "Second": 3}[kind]
        p.drawRect(x, 5, 8, 12)
    elif kind == "Parallel":
        p.drawLine(2, 16, 20, 16)                      # the sketch plane
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(blue)
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(4, 16), QtCore.QPointF(18, 16), QtCore.QPointF(18, 5)]))
    else:
        p.drawLine(2, 4, 20, 4)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(blue)
        p.drawRect(8, 4, 6, 15)
    p.end()
    return QtGui.QIcon(pm)


def mw():
    return Gui.getMainWindow()


_current = None


def current():
    """The open Rib PropertyManager (pmhandles' thickness handle), or None."""
    return _current


class RibPanel(QtCore.QObject):
    ""




    def __init__(self, obj, new):
        super().__init__()
        global _current
        _current = self
        self.obj = obj
        self.new = new
        ensure(obj)
        if not new and not obj.Document.HasPendingTransaction:

            obj.Document.openTransaction("Edit Rib")
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Parameters")
        self.form.setProperty("swstyle_pm_title", "Rib")
        self.form.setProperty("swstyle_pm_icon", "FEATURES_RIB")
        layout = QtWidgets.QVBoxLayout(self.form)
        layout.addWidget(QtWidgets.QLabel("Thickness:"))
        row = QtWidgets.QHBoxLayout()
        self.sides = {}
        group = QtWidgets.QButtonGroup(self.form)
        tips = {"First": "First Side", "Both": "Both Sides", "Second": "Second Side"}
        for kind in ("First", "Both", "Second"):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWRibSide" + kind)
            b.setCheckable(True)
            b.setIcon(_side_icon(kind))
            b.setIconSize(QtCore.QSize(22, 22))
            b.setToolTip(tips[kind])
            b.setChecked(obj.ThicknessSide == kind)
            group.addButton(b)
            b.toggled.connect(lambda on: on and self._changed())
            row.addWidget(b)
            self.sides[kind] = b
        row.addStretch(1)
        layout.addLayout(row)
        self.thickness = QtWidgets.QDoubleSpinBox()
        self.thickness.setObjectName("SWRibThickness")
        self.thickness.setRange(0.01, 10000.0)
        self.thickness.setDecimals(2)
        self.thickness.setSuffix(" mm")
        self.thickness.setToolTip("Rib Thickness")
        self.thickness.setKeyboardTracking(False)
        self.thickness.setValue(float(obj.Thickness))
        self.thickness.valueChanged.connect(self._changed)
        layout.addWidget(self.thickness)
        layout.addWidget(QtWidgets.QLabel("Extrusion direction:"))
        row = QtWidgets.QHBoxLayout()
        self.dirs = {}
        group = QtWidgets.QButtonGroup(self.form)
        for kind, tip in (("Parallel", "Parallel to Sketch"), ("Normal", "Normal to Sketch")):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWRibDir" + kind)
            b.setCheckable(True)
            b.setIcon(_side_icon(kind))
            b.setIconSize(QtCore.QSize(22, 22))
            b.setToolTip(tip)
            b.setChecked(obj.ExtrusionDirection == kind)
            group.addButton(b)
            b.toggled.connect(lambda on: on and self._changed())
            row.addWidget(b)
            self.dirs[kind] = b
        row.addStretch(1)
        layout.addLayout(row)
        self.flip = QtWidgets.QCheckBox("Flip material side")
        self.flip.setObjectName("SWRibFlip")
        self.flip.setChecked(bool(obj.Flip))
        self.flip.toggled.connect(self._changed)
        layout.addWidget(self.flip)
        grid = QtWidgets.QGridLayout()
        self.draft_on = QtWidgets.QToolButton()
        self.draft_on.setObjectName("SWRibDraftOnOff")
        self.draft_on.setCheckable(True)
        self.draft_on.setToolTip("Draft On/Off")
        try:
            from . import icons
            icon = icons.family("FEATURES_DRAFT")
        except Exception:
            icon = None
        if icon is None or icon.isNull():
            self.draft_on.setText("Draft")
        else:
            self.draft_on.setIcon(icon)
        self.draft_on.setChecked(bool(obj.DraftOn))
        self.draft = QtWidgets.QDoubleSpinBox()
        self.draft.setObjectName("SWRibDraftAngle")
        self.draft.setRange(0.01, 89.0)
        self.draft.setDecimals(2)
        self.draft.setSuffix("°")
        self.draft.setKeyboardTracking(False)
        self.draft.setValue(float(obj.DraftAngle) or 1.0)
        self.outward = QtWidgets.QCheckBox("Draft outward")
        self.outward.setObjectName("SWRibDraftOutward")
        self.outward.setChecked(bool(obj.DraftOutward))
        grid.addWidget(self.draft_on, 0, 0)
        grid.addWidget(self.draft, 0, 1)
        self.references = {}
        group = QtWidgets.QButtonGroup(self.form)
        for i, (kind, name) in enumerate((("At sketch plane", "AtSketch"), ("At wall interface", "AtWall"))):
            b = QtWidgets.QRadioButton(kind)
            b.setObjectName("SWRibDraft" + name)
            b.setToolTip("The rib thickness is measured here")
            b.setChecked(obj.DraftReference == kind)
            group.addButton(b)
            b.toggled.connect(lambda on: on and self._changed())
            grid.addWidget(b, 1 + i, 1)
            self.references[kind] = b
        grid.addWidget(self.outward, 3, 1)
        self.next_ref = QtWidgets.QPushButton("Next Reference")
        self.next_ref.setObjectName("SWRibNextReference")
        self.next_ref.setToolTip("Measure the thickness at the next wall the rib meets")
        self.next_ref.clicked.connect(self._next_reference)
        grid.addWidget(self.next_ref, 4, 1)
        layout.addLayout(grid)
        for w in (self.draft_on, self.outward):
            w.toggled.connect(self._changed)
        self.draft.valueChanged.connect(self._changed)
        self.type_label = QtWidgets.QLabel("Type:")
        self.type_label.setObjectName("SWRibTypeLabel")
        layout.addWidget(self.type_label)
        self.types = {}
        group = QtWidgets.QButtonGroup(self.form)
        for kind, tip in (("Linear", "Carry the line's ends on straight to the part"),
                          ("Natural", "Carry an arc on round its own circle to the part")):
            b = QtWidgets.QRadioButton(kind)
            b.setObjectName("SWRibType" + kind)
            b.setToolTip(tip)
            b.setChecked(obj.Extension == kind)
            group.addButton(b)
            b.toggled.connect(lambda on: on and self._changed())
            layout.addWidget(b)
            self.types[kind] = b
        self.error = QtWidgets.QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet(_error_css())
        layout.addWidget(self.error)
        self.contours_form = QtWidgets.QWidget()
        self.contours_form.setWindowTitle("Selected Contours")
        clay = QtWidgets.QVBoxLayout(self.contours_form)
        self.contours = QtWidgets.QListWidget()
        self.contours.setObjectName("SWRibContours")
        self.contours.setFixedHeight(8 + 18 * 2)
        self.contours.setToolTip("The rib sketch. Click here, then another sketch, to use that one instead.")
        clay.addWidget(self.contours)
        clay.addStretch(1)
        self.picking = False
        self.contours.viewport().installEventFilter(self)
        self.form = [self.form, self.contours_form]
        try:
            Gui.Selection.addObserver(self)
        except Exception as _fw_err:
            _fw_log("rib.py:717", _fw_err)
        self._enable()
        self._show_state()
        self._show_contours()
        from . import safe_later as _sl; _sl.later(0, self._fold_contours, self, "contours")

    def _fold_contours(self, tries=0):
        ""

        try:
            if not self.contours.isVisible():
                if tries < 20:
                    from . import safe_later as _sl; _sl.later(100, lambda: self._fold_contours(tries + 1), self, "contours")
                return
            for group in mw().findChildren(QtWidgets.QWidget):
                if not group.inherits("QSint::ActionGroup") or not group.isAncestorOf(self.contours):
                    continue
                QtCore.QMetaObject.invokeMethod(group, "showHide")
                App.Console.PrintLog("FreeCAD: rib contours folded after %d tries\n" % tries)
                return
            App.Console.PrintLog("FreeCAD: rib contours box not found\n")
        except Exception as error:
            App.Console.PrintLog("FreeCAD: rib contours fold: %s\n" % error)

    def _next_reference(self):
        self.obj.DraftReferenceIndex = int(self.obj.DraftReferenceIndex) + 1
        self._changed()

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        try:
            if event.type() == QtCore.QEvent.MouseButtonPress:
                self.picking = not self.picking
                self._show_contours()
        except Exception as _fw_err:
            _fw_log("rib.py:753", _fw_err)
        return False

    def addSelection(self, doc, name, sub, pnt):
        try:
            self.contours.isVisible()
        except RuntimeError:          # page gone without accept/reject
            self._stop()
            return
        if not self.picking:
            return
        try:
            d = App.getDocument(doc)
            sk = d.getObject(name) if d else None
            if sk is None or sk.TypeId != SKETCH or sk is self.obj.Sketch:
                return
            old = self.obj.Sketch
            self.obj.Sketch = sk
            self.picking = False
            if old is not None:
                old.Visibility = True
            sk.Visibility = False
            self.obj.Document.recompute()
            self._show_state()
            self._show_contours()
            QtCore.QTimer.singleShot(0, Gui.Selection.clearSelection)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: rib contour: %s\n" % error)

    def _stop(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("rib.py:786", _fw_err)

    def _show_contours(self):
        sk = self.obj.Sketch
        rows = [sk.Label] if sk is not None else []
        if [self.contours.item(i).text() for i in range(self.contours.count())] != rows:
            self.contours.clear()
            for r in rows:
                self.contours.addItem(r)
        pmboxes.mark(self.contours, self.picking, need=not rows)

    def _enable(self):
        on = self.draft_on.isChecked()
        self.draft.setEnabled(on)
        self.outward.setEnabled(on)
        for b in self.references.values():      # the reference location shows with the draft
            b.setVisible(on)
        self.next_ref.setVisible(on)
        normal = self.dirs["Normal"].isChecked()
        self.type_label.setVisible(normal)
        for b in self.types.values():
            b.setVisible(normal)

    def _changed(self, *args):
        obj = self.obj
        obj.Thickness = self.thickness.value()
        obj.Flip = self.flip.isChecked()
        obj.ThicknessSide = [k for k, b in self.sides.items() if b.isChecked()][0]
        obj.ExtrusionDirection = [k for k, b in self.dirs.items() if b.isChecked()][0]
        obj.DraftOn = self.draft_on.isChecked()
        obj.DraftAngle = self.draft.value()
        obj.DraftOutward = self.outward.isChecked()
        obj.Extension = [k for k, b in self.types.items() if b.isChecked()][0]
        obj.DraftReference = [k for k, b in self.references.items() if b.isChecked()][0]
        self._enable()
        obj.Document.recompute()
        self._show_state()

    def _show_state(self):
        bad = "Invalid" in self.obj.State
        self.error.setText(self.obj.getStatusString() if bad else "")
        self.error.setVisible(bad)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        global _current
        _current = None
        doc = self.obj.Document
        doc.recompute()
        if "Invalid" in self.obj.State:
            self._show_state()
            return False
        sketch = self.obj.Sketch
        if sketch is not None:
            sketch.Visibility = False
        doc.commitTransaction()
        self._stop()
        Gui.ActiveDocument.resetEdit()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        global _current
        _current = None
        self._stop()
        doc = self.obj.Document
        doc.abortTransaction()
        doc.recompute()
        Gui.ActiveDocument.resetEdit()
        Gui.Control.closeDialog()
        return True


def make(sketch):
    """Rib on sketch, with its PropertyManager open."""
    doc = sketch.Document
    body = None
    for parent in sketch.InList:
        if parent.TypeId == "PartDesign::Body":
            body = parent
    if body is None or body.Tip is None:
        App.Console.PrintWarning("FreeCAD: Rib needs a sketch in a body with a solid\n")
        return None
    doc.openTransaction("Rib")
    try:
        obj = body.newObject(TYPE, "Rib")
        RibFeature(obj)
        if Gui.ActiveDocument is not None:
            RibView(obj.ViewObject)
        obj.Label = naming.next_label(doc, "Rib")
        obj.Sketch = sketch
        doc.recompute()
        sketch.Visibility = False
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(obj.Name)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    return obj


# --------------------------------------------------------------------------- command
def run():
    """Rib from the ribbon: on a selected sketch, or ask for a plane first."""
    doc = App.ActiveDocument
    if doc is None:
        return False
    try:
        if Gui.Control.activeDialog():
            return False
        selection = Gui.Selection.getSelection()
    except Exception as _fw_err:
        _fw_log("rib.py:905", _fw_err)
        return False
    sketches = [o for o in selection if o.TypeId == SKETCH and _free_rib_line(o)]
    if sketches:
        make(sketches[-1])
        return True
    body = sketchstart._body()
    if body is None:
        return False
    Gui.Selection.clearSelection()
    _watch["before"] = {o.Name for o in doc.Objects if o.TypeId == SKETCH}
    _watch["sketch"] = None
    _watch["ticks"] = 0
    picker = sketchstart.PlanePicker(body, title="Rib", icon="FEATURES_RIB",
                                     message=MESSAGE, tool="Sketcher_CreateLine")
    _take_rib_sketch(picker)
    Gui.Control.showDialog(picker)
    _start_watch()
    return True


def _take_rib_sketch(picker):
    ""

    own = picker.picked

    def picked():
        try:
            sel = Gui.Selection.getSelectionEx()
            if sel and not picker.done:
                entry = sel[-1]
                subs = [s for s in entry.SubElementNames if s]
                obj = entry.Object
                if obj.TypeId == SKETCH and not (subs and subs[-1].startswith("Face")) and _free_rib_line(obj):
                    if _watch.get("timer") is not None:
                        _watch["timer"].stop()
                    picker._finish(lambda: make(obj))
                    return
        except Exception as _fw_err:
            _fw_log("rib.py:take-sketch", _fw_err)
        own()
    picker.picked = picked


def _start_watch():
    if _watch["timer"] is None:
        timer = QtCore.QTimer()
        timer.setInterval(250)
        timer.timeout.connect(_tick)
        _watch["timer"] = timer
    _watch["timer"].start()


def _tick():
    """Wait for the sketch the picker opens, then for it to close."""
    doc = App.ActiveDocument
    editing = None
    try:
        edit = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument is not None else None
        if edit is not None and editobj.type_id(edit) == SKETCH:
            editing = editobj.of(edit)
    except Exception as _fw_err:
        _fw_log("rib.py:933", _fw_err)
    if _watch["sketch"] is None:
        if editing is not None and editing.Name not in _watch["before"]:
            _watch["sketch"] = (editing.Document.Name, editing.Name)
            return
        _watch["ticks"] += 1
        busy = editing is not None or bool(Gui.Control.activeDialog())
        if not busy and _watch["ticks"] > 8:
            _watch["timer"].stop()  # The picker was cancelled.
        return
    if editing is not None:
        return
    _watch["timer"].stop()
    doc_name, name = _watch["sketch"]
    _watch["sketch"] = None
    try:
        doc = App.getDocument(doc_name)
    except Exception:
        return
    sketch = doc.getObject(name) if doc is not None else None
    if sketch is None or Gui.Control.activeDialog():
        return  # Discarded, or another feature took the sketch.
    if not _open_wires(sketch):
        return  # Not a rib line; leave the sketch as it is.
    QtCore.QTimer.singleShot(0, lambda: make(sketch))


class _Command:
    def GetResources(self):
        return {"MenuText": "Rib",
                "ToolTip": "Adds a thin wall from an open sketch line to the part.",
                "Pixmap": "PartDesign_Pad"}

    def IsActive(self):
        doc = App.ActiveDocument
        return doc is not None and any(o.TypeId == "PartDesign::Body" for o in doc.Objects)

    def Activated(self):
        run()


def register():
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, _Command())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Rib command not added (%s)\n" % error)


def forget_sketch(name):
    """A feature took the open sketch over before it closed: no Rib follows."""
    if _watch["sketch"] and _watch["sketch"][1] == name:
        _watch["sketch"] = None
        if _watch["timer"] is not None:
            _watch["timer"].stop()
