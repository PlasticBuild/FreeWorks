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
from PySide import QtCore, QtWidgets

from . import naming
from . import simplefeature as sf

TYPE = "PartDesign::FeatureSubtractivePython"
COMMAND = "SWStyle_Thread"
ICON = "FEATURES_THREAD"
# ISO metric coarse: size -> (nominal diameter, pitch)
SIZES = [("M1.6", 1.6, 0.35), ("M2", 2.0, 0.4), ("M2.5", 2.5, 0.45), ("M3", 3.0, 0.5), ("M4", 4.0, 0.7),
         ("M5", 5.0, 0.8), ("M6", 6.0, 1.0), ("M8", 8.0, 1.25), ("M10", 10.0, 1.5), ("M12", 12.0, 1.75),
         ("M14", 14.0, 2.0), ("M16", 16.0, 2.0), ("M18", 18.0, 2.5), ("M20", 20.0, 2.5), ("M22", 22.0, 2.5),
         ("M24", 24.0, 3.0), ("M27", 27.0, 3.0), ("M30", 30.0, 3.5), ("M36", 36.0, 4.0), ("M42", 42.0, 4.5),
         ("M48", 48.0, 5.0), ("M56", 56.0, 5.5), ("M64", 64.0, 6.0)]
KINDS = ["Inch Die", "Inch Tap", "Metric Die", "Metric Tap", "SP4xx Bottle"]
BOTTLE = "SP4xx Bottle"
# SPI bottle neck finishes (SP400 / SP410 / SP415): finish mm -> (T thread diameter in, E root diameter in,
# threads per inch). SP400 has about one turn, SP410 one and a half, SP415 two (the H height grows).
SPI = {18: (0.698, 0.638, 8), 20: (0.776, 0.716, 8), 22: (0.852, 0.792, 8), 24: (0.930, 0.870, 8),
       28: (1.071, 1.000, 6), 30: (1.138, 1.069, 6), 33: (1.245, 1.175, 6), 35: (1.315, 1.245, 6),
       38: (1.460, 1.390, 6), 40: (1.535, 1.465, 6), 43: (1.630, 1.560, 6), 45: (1.720, 1.650, 6),
       48: (1.845, 1.775, 6), 51: (1.960, 1.890, 6), 53: (2.032, 1.962, 6), 58: (2.189, 2.119, 6),
       60: (2.288, 2.218, 6), 63: (2.400, 2.330, 6), 66: (2.531, 2.461, 6), 70: (2.681, 2.611, 6),
       75: (2.869, 2.799, 6), 77: (2.948, 2.878, 6), 83: (3.183, 3.093, 5), 89: (3.417, 3.327, 5),
       100: (3.815, 3.725, 5), 110: (4.252, 4.162, 5), 120: (4.567, 4.477, 5)}
SPI_SERIES = {"SP400": (1.0, None), "SP410": (1.5, 28), "SP415": (2.0, 33)}   # turns, largest finish


def _inch_sizes():
    from . import holedata
    rows = []
    for series, table in (("UNC", holedata.UNC), ("UNF", holedata.UNF)):
        for name, tpi in table.items():
            rows.append(("%s-%d %s" % (name, tpi, series), holedata._inch_d(name) * holedata.INCH,
                         holedata.INCH / tpi))
    return sorted(rows, key=lambda r: (r[1], -r[2]))


INCH_SIZES = _inch_sizes()


def _bottle_sizes():
    rows = []
    for series, (_turns, largest) in SPI_SERIES.items():
        for finish, (t, _e, tpi) in sorted(SPI.items()):
            if largest is None or finish <= largest:
                rows.append(("%s-%d" % (series, finish), t * 25.4, 25.4 / tpi))
    return rows


BOTTLE_SIZES = _bottle_sizes()


def bottle(size):
    """(thread diameter, root diameter, pitch, turns) of an SP4xx size such as "SP400-28", or None."""
    try:
        series, finish = size.split("-")
        t, e, tpi = SPI[int(finish)]
        return t * 25.4, e * 25.4, 25.4 / tpi, SPI_SERIES[series][0]
    except (ValueError, KeyError):
        return None


def sizes(kind):
    """[(name, major diameter mm, pitch mm)] for a thread type."""
    if kind == BOTTLE:
        return BOTTLE_SIZES
    return INCH_SIZES if kind.startswith("Inch") else SIZES


def spec(kind, size):
    return next((r for r in sizes(kind) if r[0] == size), None)
METHODS = ["Cut thread", "Extrude thread"]
ENDS = ["Blind", "Revolutions", "Up To Selection"]
V = App.Vector


# --------------------------------------------------------------------------- geometry
def _shape_profile(points, mirror=None, tilt=0.0):
    ""

    if not mirror and not tilt:
        return points
    xs = [p.x for p in points]; zs = [p.z for p in points]
    cx, cz = (min(xs) + max(xs)) / 2.0, (min(zs) + max(zs)) / 2.0
    out = []
    for p in points:
        x, z = p.x, p.z
        if mirror == "Horizontal":
            z = 2 * cz - z
        elif mirror == "Vertical":
            x = 2 * cx - x
        if tilt:
            a = math.radians(tilt)
            dx, dz = x - cx, z - cz
            x, z = cx + dx * math.cos(a) - dz * math.sin(a), cz + dx * math.sin(a) + dz * math.cos(a)
        out.append(V(x, 0, z))
    if mirror:
        out.reverse()                   # keep the polygon's winding
    return out


def _starts(make, starts):
    """Multiple Start: the same thread turned round by 360/starts, starts times, as one tool."""
    tool = make()
    for i in range(1, int(starts)):
        other = make()
        other.rotate(V(0, 0, 0), V(0, 0, 1), 360.0 * i / starts)
        tool = tool.fuse(other)
    return tool


def groove(radius, pitch, length, internal=False, left=False, depth=None, lead=None, mirror=None, tilt=0.0):
    """Helical groove along +Z from z=0 to z=length. External: radius is the major radius and
    the groove cuts inwards; internal: radius is the minor radius and it cuts outwards. depth: the
    thread depth when not the ISO 60 degree one (an SPI bottle thread is shallower)."""
    depth = depth or (0.61343 if not internal else 0.54127) * pitch
    over = 0.15 * pitch
    lead = lead or pitch
    helix = Part.makeHelix(lead, length + 2 * lead, radius, 0, left)
    helix.translate(V(0, 0, -lead))
    if internal:
        ro, ri = radius - over, radius + depth
    else:
        ro, ri = radius + over, radius - depth
    tip = pitch / 8.0                                  # flat at the bottom of the groove
    wide = tip + depth * math.tan(math.radians(30))    # < pitch / 2: turns never touch
    if wide >= pitch / 2.0:
        wide = pitch / 2.0 - 1e-3
    z = -lead
    points = [V(ro, 0, z - wide), V(radius, 0, z - wide), V(ri, 0, z - tip),
              V(ri, 0, z + tip), V(radius, 0, z + wide), V(ro, 0, z + wide)]
    points = _shape_profile(points, mirror, tilt)
    profile = Part.makePolygon(points + [points[0]])
    solid = Part.Wire(helix).makePipeShell([profile], True, True)
    if solid.Volume < 0:
        solid.reverse()
    big = radius + 3 * lead
    ends = Part.makeBox(2 * big, 2 * big, 3 * lead, V(-big, -big, -3 * lead)).fuse(
        Part.makeBox(2 * big, 2 * big, 3 * lead, V(-big, -big, length)))
    return solid.cut(ends)


def _tooth(major, depth, pitch, length, left=False, lead=None, mirror=None, tilt=0.0):
    """A raised helical tooth from radius major - depth out to major, z 0..length (an SPI bottle
    thread on its neck: a narrow rounded tooth, wide land between the turns)."""
    root = major - depth
    lead = lead or pitch
    helix = Part.makeHelix(lead, length + 2 * lead, root - 0.05 * depth, 0, left)
    helix.translate(V(0, 0, -lead))
    half_root = min(0.3 * pitch, depth * 1.2)
    half_top = half_root * 0.45
    z = -lead
    pts = [V(root - 0.05 * depth, 0, z - half_root), V(major, 0, z - half_top),
           V(major, 0, z + half_top), V(root - 0.05 * depth, 0, z + half_root)]
    pts = _shape_profile(pts, mirror, tilt)
    solid = Part.Wire(helix).makePipeShell([Part.makePolygon(pts + [pts[0]])], True, True)
    if solid.Volume < 0:
        solid.reverse()
    big = major + 3 * lead
    ends = Part.makeBox(2 * big, 2 * big, 3 * lead, V(-big, -big, -3 * lead)).fuse(
        Part.makeBox(2 * big, 2 * big, 3 * lead, V(-big, -big, length)))
    return solid.cut(ends)


def _circle(edge):
    curve = getattr(edge, "Curve", None)
    if not isinstance(curve, Part.Circle):
        return None
    return curve.Center, curve.Axis.normalize(), curve.Radius


def _into_material(base, center, axis, radius, internal):
    """The direction along the axis that runs into the part from the edge."""
    probe = radius * (0.9 if not internal else 1.1)
    side = V(1, 0, 0) if abs(axis.x) < 0.9 else V(0, 1, 0)
    radial = axis.cross(side).normalize()
    step = max(radius * 0.05, 0.05)
    # the side with more material along the axis: just past a chamfer at the shaft's end both sides are
    # solid near the edge, so look further along (up to a radius) and count
    best, most = axis, -1
    for direction in (axis, -axis):
        inside = sum(1 for k in range(1, 21) if base.isInside(center + direction * (step * k) + radial * probe, 1e-6, True))
        if inside > most:
            best, most = direction, inside
    return best


def up_to_length(base, edge, up_to, kind, reverse=False):
    """Up To Selection: how far along the thread's way the picked face, plane or vertex is from the
    start edge."""
    if up_to is None or not up_to[1] and not hasattr(up_to[0], "Shape"):
        raise RuntimeError("Up To Selection: pick a face, plane or vertex")
    circle = _circle(edge)
    if circle is None:
        raise RuntimeError("Pick a circular edge of a shaft or a hole")
    center, axis, radius = circle
    direction = _into_material(base, center, axis, radius, kind.endswith("Tap"))
    if reverse:
        direction = -direction
    obj, subs = up_to
    target = obj.Shape.getElement(subs[0]) if subs and subs[0] else obj.Shape
    if hasattr(target, "Surface") and isinstance(getattr(target, "Surface", None), Part.Plane):
        n = V(target.Surface.Axis)
        if abs(n.dot(direction)) > 1e-9:
            return (target.Surface.Position - center).dot(n) / n.dot(direction)
    if obj.TypeId in ("PartDesign::Plane", "App::Plane"):
        n = obj.Placement.Rotation.multVec(V(0, 0, 1))
        if abs(n.dot(direction)) > 1e-9:
            return (obj.Placement.Base - center).dot(n) / n.dot(direction)
    pts = [v.Point for v in target.Vertexes] or [target.BoundBox.Center]
    return max((p - center).dot(direction) for p in pts)


def size_for(diameter, internal, kind=None):
    """The standard size that fits a shaft (die) or tap drill hole of this diameter."""
    best = None
    for name, nominal, pitch in sizes(kind or ("Metric Tap" if internal else "Metric Die")):
        fit = nominal if not internal else nominal - 1.0825 * pitch
        error = abs(fit - diameter)
        if best is None or error < best[0]:
            best = (error, name)
    return best[1]


def thread_shape(base, edge, kind, size, length, offset=0.0, reverse=False, left=False, extrude=False,
                 diameter=None, pitch=None, angle=0.0, trim_start=True, trim_end=True,
                 starts=1, mirror=None, tilt=0.0):
    ""


    circle = _circle(edge)
    if circle is None:
        raise RuntimeError("Pick a circular edge of a shaft or a hole")
    center, axis, radius = circle
    internal = kind.endswith("Tap")
    found = spec(kind, size)
    if found is None:
        raise RuntimeError("Unknown thread size %s" % size)
    _, nominal, size_pitch = found
    nominal = float(diameter) if diameter else nominal
    pitch = float(pitch) if pitch else size_pitch
    depth = None
    if kind == BOTTLE:
        # SPI bottle neck: the thread stands from the root (E) to the thread diameter (T); the land
        # between turns is wide (a short rounded tooth, not a 60 degree V)
        t_d, e_d, _p, _turns = bottle(size)
        depth = (t_d - e_d) / 2.0
    direction = _into_material(base, center, axis, radius, internal)
    if reverse:
        direction = -direction
    major = nominal / 2.0
    if extrude and not internal:

        major = radius + (depth or 0.61343 * pitch)
    if extrude and internal:
        # Extrude thread in a hole: the hole wall is the root, the teeth stand inwards from it
        major = radius + 0.54127 * pitch

    # trimmed, the thread's last turn runs on half a pitch past it (an extruded thread stands out there)
    before = 0.0 if trim_start else 0.5 * pitch
    after = 0.0 if trim_end else 0.5 * pitch
    starts = max(1, int(starts or 1))
    lead = pitch * starts
    if depth and extrude and not internal:
        tool = _starts(lambda: _tooth(major, depth, pitch, length + before + after, left, lead, mirror, tilt), starts)
    else:
        tool = _starts(lambda: groove(major if not internal else major - 0.54127 * pitch, pitch, length + before + after,
                                      internal, left, depth, lead, mirror, tilt), starts)
    tool.translate(V(0, 0, -before))
    span = length + before + after
    if extrude and not internal and depth:
        pass                                    # _tooth is the raised thread itself
    elif extrude and not internal:
        rod = Part.makeCylinder(major, span, V(0, 0, -before))
        tool = rod.cut(tool, 1e-4)
    elif extrude:
        minor = radius - 0.54127 * pitch
        ring = Part.makeCylinder(radius + 1e-3, span, V(0, 0, -before)).cut(
            Part.makeCylinder(minor, span, V(0, 0, -before)))
        tool = ring.cut(tool, 1e-4)
    rotation = App.Rotation(V(0, 0, 1), direction).multiply(App.Rotation(V(0, 0, 1), float(angle or 0.0)))
    tool.Placement = App.Placement(center + direction * offset, rotation)
    if extrude:
        result = base.fuse(tool, 1e-4)
    else:
        result = base.cut(tool, 1e-4)
    try:
        result = result.removeSplitter()
    except Exception as _fw_err:
        _fw_log("thread.py:316", _fw_err)
    if not result.isValid() or not result.Solids:
        raise RuntimeError("The thread could not be made on this edge")
    return result, tool


# --------------------------------------------------------------------------- feature
PREVIEWS = ("Shaded preview", "Wireframe preview", "Partial preview")


class ThreadFeature:
    def __init__(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def setup(self, obj):
        def add(kind, name, tip):
            if name not in obj.PropertiesList:
                obj.addProperty(kind, name, "Thread", tip)
        add("App::PropertyLinkSub", "Edge", "Circular edge where the thread starts")
        add("App::PropertyEnumeration", "Kind", "Metric Die (shaft) or Metric Tap (hole)")
        add("App::PropertyEnumeration", "Size", "ISO metric coarse size")
        add("App::PropertyEnumeration", "Method", "Cut thread or Extrude thread")
        add("App::PropertyEnumeration", "EndCondition", "Blind length or a number of revolutions")
        add("App::PropertyLength", "Length", "Thread length (Blind)")
        add("App::PropertyFloat", "Revolutions", "Number of turns (Revolutions)")
        add("App::PropertyDistance", "Offset", "Start the thread this far from the edge")
        add("App::PropertyBool", "Reverse", "Run the thread the other way along the axis")
        add("App::PropertyBool", "LeftHand", "Left-hand thread")
        add("App::PropertyBool", "OverrideDiameter", "Use Diameter instead of the size's")
        add("App::PropertyLength", "Diameter", "Thread diameter (Override diameter)")
        add("App::PropertyBool", "OverridePitch", "Use PitchValue instead of the size's")
        add("App::PropertyLength", "PitchValue", "Thread pitch (Override pitch)")
        add("App::PropertyAngle", "StartAngle", "Where round the axis the thread starts")
        add("App::PropertyLinkSub", "UpTo", "Face, plane or vertex the thread runs up to (Up To Selection)")
        for name, tip in (("TrimStart", "Trim with start face: the thread cut flush at the start face"),
                          ("TrimEnd", "Trim with end face: the thread cut flush at its end")):
            if name not in obj.PropertiesList:
                add("App::PropertyBool", name, tip)
                setattr(obj, name, True)
        if "Starts" not in obj.PropertiesList:
            add("App::PropertyBool", "MultipleStart", "Multiple Start: several threads side by side (lead = pitch x starts)")
            add("App::PropertyInteger", "Starts", "Number of starts (Multiple Start)")
            obj.Starts = 2
            add("App::PropertyBool", "MirrorProfile", "Mirror the thread profile")
            add("App::PropertyEnumeration", "MirrorAxis", "Mirror horizontally or vertically")
            obj.MirrorAxis = ["Horizontal", "Vertical"]
            add("App::PropertyAngle", "ProfileAngle", "Rotation Angle: the profile turned about its center")
            add("App::PropertyEnumeration", "PreviewMode", "Preview Options while the PropertyManager is open")
            obj.PreviewMode = list(PREVIEWS)
        if "UseOffset" not in obj.PropertiesList:

            add("App::PropertyLinkSub", "StartAt", "Optional start location: a vertex, edge, plane or flat face the thread starts at")
            add("App::PropertyBool", "UseOffset", "Offset: start the thread Offset away from the edge (or the start location)")
            obj.UseOffset = abs(float(obj.Offset)) > 1e-9      # a thread made before kept its offset
        if "MaintainLength" not in obj.PropertiesList:
            add("App::PropertyBool", "MaintainLength", "Maintain thread length: with an Offset the thread keeps its length")
            obj.MaintainLength = True
        kind = getattr(obj, "Kind", None) or "Metric Die"
        for name, values in (("Kind", KINDS), ("Size", [s[0] for s in sizes(str(kind))]), ("Method", METHODS),
                             ("EndCondition", ENDS)):
            current = getattr(obj, name, None)
            setattr(obj, name, values)
            if current in values:
                setattr(obj, name, current)
            elif name == "Kind":
                obj.Kind = "Metric Die"
        if float(obj.Length) == 0:
            obj.Length = 10.0
        if not obj.Revolutions:
            obj.Revolutions = 8.0

    def onChanged(self, obj, prop):
        if prop == "Kind" and "Size" in obj.PropertiesList:
            names = [r[0] for r in sizes(str(obj.Kind))]
            if list(obj.getEnumerationsOfProperty("Size")) != names:
                current = obj.Size
                obj.Size = names
                if current in names:
                    obj.Size = current

    def pitch(self, obj):
        if obj.OverridePitch and float(obj.PitchValue) > 0:
            return float(obj.PitchValue)
        found = spec(obj.Kind, obj.Size)
        return found[2] if found else 1.0

    def execute(self, obj):
        base = obj.BaseFeature.Shape if obj.BaseFeature is not None else None
        if base is None or base.isNull():
            raise RuntimeError("Thread needs a part")
        if obj.Edge is None or not obj.Edge[1]:
            sf.store(obj, base)
            return
        source, subs = obj.Edge
        edge = source.Shape.getElement(subs[0])
        offset = float(obj.Offset) if getattr(obj, "UseOffset", True) else 0.0
        start = 0.0
        if getattr(obj, "StartAt", None) is not None:
            start = up_to_length(base, edge, obj.StartAt, obj.Kind, obj.Reverse)
        if obj.EndCondition == "Up To Selection":
            length = up_to_length(base, edge, obj.UpTo, obj.Kind, obj.Reverse) - offset
        else:
            length = float(obj.Length) if obj.EndCondition == "Blind" else obj.Revolutions * self.pitch(obj)
            if offset and not getattr(obj, "MaintainLength", True):
                length -= offset            # the end stays where it was; the offset start shortens it
        if start and obj.EndCondition == "Up To Selection":
            length -= start
        offset += start
        if length <= 1e-6:
            raise RuntimeError("The thread has no length (check the end condition and the offset)")
        starts = int(obj.Starts) if getattr(obj, "MultipleStart", False) else 1
        if getattr(self, "partial", False):          # Partial preview: one turn while the PM is open
            length = min(length, self.pitch(obj) * starts)
        result, tool = thread_shape(base, edge, obj.Kind, obj.Size, length, offset, obj.Reverse,
                                    obj.LeftHand, obj.Method == "Extrude thread",
                                    float(obj.Diameter) if obj.OverrideDiameter else None,
                                    self.pitch(obj) if obj.OverridePitch else None, float(obj.StartAngle),
                                    bool(getattr(obj, "TrimStart", True)), bool(getattr(obj, "TrimEnd", True)),
                                    starts, str(obj.MirrorAxis) if getattr(obj, "MirrorProfile", False) else None,
                                    float(getattr(obj, "ProfileAngle", 0.0)))
        solids = result.Solids
        sf.store(obj, solids[0] if len(solids) == 1 else Part.makeCompound(solids), tool)

    def onDocumentRestored(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ThreadView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        try:
            from . import icons
            icon = icons.family(ICON)
            if not icon.isNull():
                return icon         # a QIcon: FreeCAD reads a returned QPixmap as a QIcon
        except Exception as _fw_err:
            _fw_log("thread.py:454", _fw_err)
        return ":/icons/PartDesign_SubtractiveHelix.svg"

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        Gui.Control.showDialog(ThreadPanel(vobj.Object, new=False))
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


# --------------------------------------------------------------------------- PropertyManager
class _BoxClick(QtCore.QObject):
    """A click in a pick box makes it the one the next pick goes to."""

    def __init__(self, panel, key):
        super().__init__(panel.start_at)
        self.panel, self.key = panel, key

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.MouseButtonPress:
            self.panel.active = self.key
            self.panel._show()
        return False


class ThreadPanel:
    """The Thread PropertyManager."""

    def __init__(self, obj, new):
        self.obj = obj
        self.new = new
        self.busy = False
        self.form = []
        self.location = self._box("Thread Location")
        form = self.location.layout()
        self.edge = QtWidgets.QListWidget()
        self.edge.setMaximumHeight(48)
        self.edge.setToolTip("Pick the circular edge of a shaft or a hole where the thread starts")
        form.addRow(self.edge)
        self.start_at = QtWidgets.QListWidget()
        self.start_at.setObjectName("SWThreadStartAt")
        self.start_at.setMaximumHeight(40)
        self.start_at.setToolTip("Optional start location: click here, then pick a vertex, edge, plane or flat face")
        self.start_at.viewport().installEventFilter(_BoxClick(self, "start"))
        form.addRow("Optional start location", self.start_at)
        self.active = None
        self.use_offset = QtWidgets.QCheckBox("Offset")
        self.use_offset.setObjectName("SWThreadUseOffset")
        self.use_offset.setChecked(bool(getattr(obj, "UseOffset", abs(float(obj.Offset)) > 1e-9)))
        self.offset = self._length(obj.Offset, -10000)
        form.addRow(self.use_offset, self.offset)
        self.reverse = QtWidgets.QCheckBox("Reverse direction")
        self.reverse.setChecked(obj.Reverse)
        form.addRow(self.reverse)
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setRange(-360.0, 360.0)
        self.angle.setSuffix(" \u00b0")
        self.angle.setValue(float(obj.StartAngle))
        form.addRow("Start angle", self.angle)

        self.ending = self._box("End Condition")
        form = self.ending.layout()
        self.end = QtWidgets.QComboBox()
        self.end.addItems(ENDS)
        self.end.setCurrentText(obj.EndCondition)
        form.addRow(self.end)
        self.length = self._length(obj.Length, 0.01)
        form.addRow("Depth", self.length)
        self.turns = QtWidgets.QDoubleSpinBox()
        self.turns.setRange(0.25, 10000)
        self.turns.setValue(obj.Revolutions)
        form.addRow("Revolutions", self.turns)
        self.up_to = QtWidgets.QListWidget()
        self.up_to.setObjectName("SWThreadUpTo")
        self.up_to.setMaximumHeight(40)
        self.up_to.setToolTip("Up To Selection: pick the face, plane or vertex the thread runs to")
        form.addRow(self.up_to)
        self.maintain = QtWidgets.QCheckBox("Maintain thread length")
        self.maintain.setObjectName("SWThreadMaintain")
        self.maintain.setChecked(bool(getattr(obj, "MaintainLength", True)))
        form.addRow(self.maintain)

        self.spec = self._box("Specification")
        form = self.spec.layout()
        self.kind = QtWidgets.QComboBox()
        self.kind.addItems(KINDS)
        self.kind.setCurrentText(obj.Kind)
        form.addRow("Type", self.kind)
        self.size = QtWidgets.QComboBox()
        self.size.addItems([s[0] for s in sizes(obj.Kind)])
        self.size.setCurrentText(obj.Size)
        form.addRow("Size", self.size)
        self.over_d = QtWidgets.QCheckBox("Override diameter")
        self.over_d.setChecked(obj.OverrideDiameter)
        self.diameter = self._length(obj.Diameter if float(obj.Diameter) else 6.0, 0.1)
        form.addRow(self.over_d, self.diameter)
        self.over_p = QtWidgets.QCheckBox("Override pitch")
        self.over_p.setChecked(obj.OverridePitch)
        self.pitch_value = self._length(obj.PitchValue if float(obj.PitchValue) else 1.0, 0.05)
        form.addRow(self.over_p, self.pitch_value)
        self.pitch = QtWidgets.QLabel()
        form.addRow("Pitch", self.pitch)
        self.cut = QtWidgets.QRadioButton("Cut thread")
        self.extrude = QtWidgets.QRadioButton("Extrude thread")
        (self.extrude if obj.Method == "Extrude thread" else self.cut).setChecked(True)
        form.addRow(self.cut)
        form.addRow(self.extrude)
        self.mirror = QtWidgets.QCheckBox("Mirror Profile")
        self.mirror.setObjectName("SWThreadMirror")
        self.mirror.setChecked(bool(obj.MirrorProfile))
        form.addRow(self.mirror)
        self.mirror_h = QtWidgets.QRadioButton("Mirror horizontally")
        self.mirror_v = QtWidgets.QRadioButton("Mirror vertically")
        (self.mirror_v if obj.MirrorAxis == "Vertical" else self.mirror_h).setChecked(True)
        self._mirror_group = QtWidgets.QButtonGroup(self.spec)
        for b in (self.mirror_h, self.mirror_v):
            self._mirror_group.addButton(b)
            form.addRow(b)
        self.tilt = QtWidgets.QDoubleSpinBox()
        self.tilt.setObjectName("SWThreadProfileAngle")
        self.tilt.setRange(-360.0, 360.0)
        self.tilt.setSuffix(" \u00b0")
        self.tilt.setValue(float(obj.ProfileAngle))
        self.tilt.setToolTip("Turns the thread profile about its center")
        form.addRow("Rotation Angle", self.tilt)
        self.locate = QtWidgets.QPushButton("Locate Profile")
        self.locate.setObjectName("SWThreadLocateProfile")
        self.locate.setToolTip("Zooms to the start of the thread, where the profile sits")
        self.locate.clicked.connect(self.locate_profile)
        form.addRow(self.locate)

        self.options = self._box("Thread Options")
        form = self.options.layout()
        self.right = QtWidgets.QRadioButton("Right-hand thread")
        self.left = QtWidgets.QRadioButton("Left-hand thread")
        (self.left if obj.LeftHand else self.right).setChecked(True)
        form.addRow(self.right)
        form.addRow(self.left)
        self.trim_start = QtWidgets.QCheckBox("Trim with start face")
        self.trim_start.setObjectName("SWThreadTrimStart")
        self.trim_start.setChecked(bool(getattr(obj, "TrimStart", True)))
        form.addRow(self.trim_start)
        self.trim_end = QtWidgets.QCheckBox("Trim with end face")
        self.trim_end.setObjectName("SWThreadTrimEnd")
        self.trim_end.setChecked(bool(getattr(obj, "TrimEnd", True)))
        form.addRow(self.trim_end)
        self.multi = QtWidgets.QCheckBox("Multiple Start")
        self.multi.setObjectName("SWThreadMultiStart")
        self.multi.setChecked(bool(obj.MultipleStart))
        self.starts = QtWidgets.QSpinBox()
        self.starts.setObjectName("SWThreadStarts")
        self.starts.setRange(2, 10)
        self.starts.setValue(max(2, int(obj.Starts)))
        self.starts.setToolTip("Number of starts")
        form.addRow(self.multi, self.starts)
        self.error = QtWidgets.QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c00000;")
        form.addRow(self.error)

        self.preview = self._box("Preview Options")
        self.preview_buttons = []
        self._preview_group = QtWidgets.QButtonGroup(self.preview)
        for text in PREVIEWS:
            b = QtWidgets.QRadioButton(text)
            b.setChecked(obj.PreviewMode == text)
            self._preview_group.addButton(b)
            self.preview.layout().addRow(b)
            self.preview_buttons.append(b)
            b.toggled.connect(self._changed)
        self._display = getattr(obj.ViewObject, "DisplayMode", None) if obj.ViewObject is not None else None
        self.form = [self.location, self.ending, self.spec, self.options, self.preview]
        # pkg241: editing a thread opened no undo step, so Cancel kept the page's changes (Revolutions
        # stayed on after Cancel). An edit is one undo step now, and Cancel puts the values back.
        self._saved = None
        if not new:
            self._saved = [(p, getattr(obj, p)) for p in obj.PropertiesList
                           if obj.getGroupOfProperty(p) == "Thread" and p not in ("Edge", "UpTo")]
            self._saved += [(p, getattr(obj, p)) for p in ("Edge", "UpTo") if p in obj.PropertiesList]
            self._saved.sort(key=lambda kv: 0 if kv[0] == "Kind" else 1)
            try:
                if not obj.Document.HasPendingTransaction:
                    obj.Document.openTransaction("Edit Thread")
            except Exception as _fw_err:
                _fw_log("thread.py:623", _fw_err)
        self.location.setProperty("swstyle_pm_title", "Thread")
        self.location.setProperty("swstyle_pm_icon", ICON)
        for widget in (self.offset, self.length, self.turns, self.diameter, self.pitch_value, self.angle, self.tilt, self.starts):
            widget.valueChanged.connect(self._changed)
        for widget in (self.over_d, self.over_p):
            widget.toggled.connect(self._changed)
        for widget in (self.end, self.kind, self.size):
            widget.currentIndexChanged.connect(self._changed)
        for widget in (self.use_offset, self.reverse, self.extrude, self.left, self.maintain, self.trim_start, self.trim_end,
                       self.mirror, self.mirror_v, self.multi):
            widget.toggled.connect(self._changed)
        self._show()
        Gui.Selection.addObserver(self)
        try:
            from . import pmboxes          # right-click Delete / Clear Selections on the pick boxes
            pmboxes.bind(self.start_at, lambda row: self.clear_start(), self.clear_start)
            pmboxes.bind(self.up_to, lambda row: self._clear("UpTo"), lambda: self._clear("UpTo"))
            pmboxes.bind(self.edge, lambda row: self._clear("Edge"), lambda: self._clear("Edge"))
        except Exception as _fw_err:
            _fw_log("thread.py:bind boxes", _fw_err)

    def _box(self, title):
        box = QtWidgets.QWidget()
        box.setWindowTitle(title)
        QtWidgets.QFormLayout(box)
        return box

    def _length(self, value, low):
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(low, 100000.0)
        spin.setDecimals(2)
        spin.setSuffix(" mm")
        spin.setValue(float(value))
        return spin

    # selection: a circular edge of the part
    def addSelection(self, doc, name, sub, point):
        if doc != self.obj.Document.Name:
            return
        if self.active == "start":
            picked = self.obj.Document.getObject(name)
            if picked is not None and (sub.startswith(("Vertex", "Edge", "Face")) or
                                       picked.TypeId in ("PartDesign::Plane", "App::Plane")):
                if sub.startswith("Face"):
                    try:
                        if not isinstance(picked.Shape.getElement(sub).Surface, Part.Plane):
                            return
                    except Exception:
                        return
                QtCore.QTimer.singleShot(0, lambda: self.set_start(picked, sub))
            return
        if self.obj.EndCondition == "Up To Selection" and self.obj.Edge is not None and self.obj.Edge[1] \
                and (sub.startswith(("Face", "Vertex")) or not sub):
            picked = self.obj.Document.getObject(name)
            if picked is not None and (sub or picked.TypeId in ("PartDesign::Plane", "App::Plane")):
                QtCore.QTimer.singleShot(0, lambda: self.set_up_to(picked, sub))
            return
        if not sub.startswith("Edge"):
            return
        source = self.obj.BaseFeature
        if source is None:
            return
        picked = self.obj.Document.getObject(name)
        try:
            edge = source.Shape.getElement(sub) if picked is not None else None
        except Exception:
            edge = None
        if edge is None or _circle(edge) is None:
            return
        from . import safe_later as _sl; _sl.later(0, lambda: self.set_edge(sub), self, "kind")

    def set_start(self, obj, sub):
        self.obj.StartAt = (obj, [sub] if sub else [])
        self.active = None
        Gui.Selection.clearSelection()
        self._changed()

    def clear_start(self):
        self._clear("StartAt")

    def _clear(self, prop):
        setattr(self.obj, prop, None)
        self._changed()

    def locate_profile(self):
        ""
        try:
            source, subs = self.obj.Edge
            center, axis, radius = _circle(source.Shape.getElement(subs[0]))
            view = Gui.ActiveDocument.ActiveView
            cam = view.getCameraNode()
            d = view.getViewDirection()
            far = max(radius * 20.0, 20.0)
            p = center - V(d) * far
            cam.position.setValue(p.x, p.y, p.z)
            cam.focalDistance.setValue(far)
            if hasattr(cam, "height"):
                cam.height.setValue(max(radius * 8.0, 2.0))
            elif hasattr(cam, "heightAngle"):
                cam.position.setValue(*(center - V(d) * max(radius * 10.0, 10.0)))
        except Exception as error:
            _fw_log("thread.py:locate", error)

    def set_up_to(self, obj, sub):
        self.obj.UpTo = (obj, [sub] if sub else [])
        Gui.Selection.clearSelection()
        self._changed()

    def set_edge(self, sub):
        source = self.obj.BaseFeature
        edge = source.Shape.getElement(sub)
        center, _, radius = _circle(edge)
        internal = not source.Shape.isInside(center, 1e-6, True)
        self.busy = True
        family = "Inch" if self.kind.currentText().startswith("Inch") else "Metric"
        kind = "%s %s" % (family, "Tap" if internal else "Die")
        if self.kind.currentText() == BOTTLE and not internal:
            kind = BOTTLE                       # a bottle neck stays SP4xx
        self.kind.setCurrentText(kind)
        self._fill_sizes(kind)
        self.size.setCurrentText(size_for(2 * radius, internal, kind))
        self.busy = False
        self.obj.Edge = (source, [sub])
        Gui.Selection.clearSelection()
        self._changed()

    def _changed(self, *args):
        if self.busy:
            return
        obj = self.obj
        obj.UseOffset = self.use_offset.isChecked()
        obj.Offset = self.offset.value()
        obj.Reverse = self.reverse.isChecked()
        obj.EndCondition = self.end.currentText()
        obj.Length = self.length.value()
        obj.Revolutions = self.turns.value()
        if obj.Kind != self.kind.currentText():
            obj.Kind = self.kind.currentText()
            obj.Size = [r[0] for r in sizes(obj.Kind)]
            self.busy = True
            self._fill_sizes(obj.Kind)
            if obj.Kind == BOTTLE:

                self.extrude.setChecked(True)
                self.end.setCurrentText("Revolutions")
            self.busy = False
        if self.size.currentText() in obj.getEnumerationsOfProperty("Size"):
            new_size = obj.Size != self.size.currentText()
            obj.Size = self.size.currentText()
            b = bottle(obj.Size) if obj.Kind == BOTTLE else None
            if b is not None and (new_size or obj.EndCondition == "Revolutions"):
                self.busy = True
                self.turns.setValue(b[3])
                self.busy = False
                obj.Revolutions = b[3]
                obj.EndCondition = self.end.currentText()
                obj.Method = "Extrude thread" if self.extrude.isChecked() else "Cut thread"
        obj.OverrideDiameter = self.over_d.isChecked()
        obj.Diameter = self.diameter.value()
        obj.OverridePitch = self.over_p.isChecked()
        obj.PitchValue = self.pitch_value.value()
        obj.StartAngle = self.angle.value()
        obj.Method = "Extrude thread" if self.extrude.isChecked() else "Cut thread"
        obj.LeftHand = self.left.isChecked()
        obj.MaintainLength = self.maintain.isChecked()
        obj.TrimStart = self.trim_start.isChecked()
        obj.TrimEnd = self.trim_end.isChecked()
        obj.MirrorProfile = self.mirror.isChecked()
        obj.MirrorAxis = "Vertical" if self.mirror_v.isChecked() else "Horizontal"
        obj.ProfileAngle = self.tilt.value()
        obj.MultipleStart = self.multi.isChecked()
        obj.Starts = self.starts.value()
        obj.PreviewMode = next((b.text() for b in self.preview_buttons if b.isChecked()), PREVIEWS[0])
        self._apply_preview()
        obj.Document.recompute()
        self._show()

    def _show_size_values(self, obj):
        ""



        found = spec(obj.Kind, obj.Size)
        pairs = []
        if found and not obj.OverrideDiameter:
            pairs.append((self.diameter, float(found[1])))
        if found and not obj.OverridePitch:
            pairs.append((self.pitch_value, float(found[2])))
        if obj.EndCondition == "Blind":
            p = obj.Proxy.pitch(obj)
            if p > 0:
                pairs.append((self.turns, float(obj.Length) / p))
        for box, value in pairs:
            if abs(box.value() - value) > 1e-9:
                box.blockSignals(True)
                box.setValue(value)
                box.blockSignals(False)

    def _fill_sizes(self, kind):
        current = self.size.currentText()
        names = [r[0] for r in sizes(kind)]
        self.size.blockSignals(True)
        self.size.clear()
        self.size.addItems(names)
        self.size.setCurrentText(current if current in names else names[len(names) // 3])
        self.size.blockSignals(False)

    def _show(self):
        obj = self.obj
        self.edge.clear()
        if obj.Edge is not None and obj.Edge[1]:
            self.edge.addItem(obj.Edge[1][0])
        self.length.setEnabled(obj.EndCondition == "Blind")
        self.turns.setEnabled(obj.EndCondition == "Revolutions")
        self.up_to.clear()
        if obj.UpTo is not None:
            self.up_to.addItem("%s %s" % (obj.UpTo[0].Label, (obj.UpTo[1] or [""])[0]))
        self.up_to.setVisible(obj.EndCondition == "Up To Selection")
        self.start_at.clear()
        if getattr(obj, "StartAt", None) is not None:
            self.start_at.addItem("%s %s" % (obj.StartAt[0].Label, (obj.StartAt[1] or [""])[0]))
        try:
            from . import pmboxes
            pmboxes.mark(self.start_at, self.active == "start")
        except Exception as _fw_err:
            _fw_log("thread.py:start mark", _fw_err)
        self.offset.setEnabled(bool(obj.UseOffset))
        self.maintain.setEnabled(obj.EndCondition != "Up To Selection" and bool(obj.UseOffset) and abs(float(obj.Offset)) > 1e-9)
        self.pitch.setText("%g mm" % obj.Proxy.pitch(obj))
        self.diameter.setEnabled(obj.OverrideDiameter)
        self.pitch_value.setEnabled(obj.OverridePitch)
        self._show_size_values(obj)
        self.mirror_h.setEnabled(bool(obj.MirrorProfile))
        self.mirror_v.setEnabled(bool(obj.MirrorProfile))
        self.starts.setEnabled(bool(obj.MultipleStart))
        self.extrude.setEnabled(True)
        bad = "Invalid" in obj.State
        self.error.setText(obj.getStatusString() if bad else "")
        self.error.setVisible(bad)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _apply_preview(self, closing=False):
        obj = self.obj
        mode = PREVIEWS[0] if closing else obj.PreviewMode
        obj.Proxy.partial = mode == "Partial preview"
        vobj = obj.ViewObject
        if vobj is not None and self._display:
            want = "Wireframe" if mode == "Wireframe preview" else self._display
            if vobj.DisplayMode != want and want in vobj.listDisplayModes():
                vobj.DisplayMode = want

    def _close(self):
        try:
            self._apply_preview(closing=True)
        except Exception as _fw_err:
            _fw_log("thread.py:798", _fw_err)
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("thread.py:802", _fw_err)
        Gui.ActiveDocument.resetEdit()
        Gui.Control.closeDialog()

    def accept(self):
        doc = self.obj.Document
        self.obj.Proxy.partial = False          # OK builds the whole thread
        self.obj.touch()
        doc.recompute()
        if "Invalid" in self.obj.State or self.obj.Edge is None or not self.obj.Edge[1]:
            self.error.setText(self.obj.getStatusString() if "Invalid" in self.obj.State
                               else "Pick the circular edge where the thread starts")
            self.error.setVisible(True)
            return False
        doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        doc.abortTransaction()
        for name, value in (self._saved or []):
            try:
                if name == "Size" and value not in self.obj.getEnumerationsOfProperty("Size"):
                    continue
                if getattr(self.obj, name) != value:
                    setattr(self.obj, name, value)
            except Exception as error:
                App.Console.PrintLog("FreeCAD Thread: Cancel kept %s: %s\n" % (name, error))
        doc.recompute()
        self._close()
        return True


# --------------------------------------------------------------------------- command
def _body(doc):
    try:
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
    except Exception:
        body = None
    if body is None:
        bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
        body = bodies[0] if len(bodies) == 1 else None
    return body


def make(doc=None, edge=None):
    """A Thread in the active body, with its PropertyManager open; edge = (object, "EdgeN")."""
    doc = doc or App.ActiveDocument
    body = _body(doc) if doc is not None else None
    if body is None or body.Tip is None:
        App.Console.PrintWarning("FreeCAD: Thread needs a body with a solid\n")
        return None
    doc.openTransaction("Thread")
    try:
        obj = body.newObject(TYPE, "Thread")
        ThreadFeature(obj)
        if Gui.ActiveDocument is not None:
            ThreadView(obj.ViewObject)
        obj.Label = naming.next_label(doc, "Thread")
        if edge is not None:
            base = obj.BaseFeature
            shape_edge = base.Shape.getElement(edge[1])
            circle = _circle(shape_edge)
            if circle is not None:
                internal = not base.Shape.isInside(circle[0], 1e-6, True)
                obj.Kind = "Metric Tap" if internal else "Metric Die"
                obj.Size = size_for(2 * circle[2], internal)
                obj.Edge = (base, [edge[1]])
        doc.recompute()
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(obj.Name)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    return obj


def _picked_edge():
    for sel in Gui.Selection.getSelectionEx():
        for sub in sel.SubElementNames:
            if sub.startswith("Edge"):
                try:
                    if _circle(sel.Object.Shape.getElement(sub)) is not None:
                        return sel.Object, sub
                except Exception as _fw_err:
                    _fw_log("thread.py:884", _fw_err)
    return None


class _Command:
    def GetResources(self):
        return {"MenuText": "Thread",
                "ToolTip": "Cuts or adds a helical thread on a shaft or in a hole, from a circular edge.",
                "Pixmap": "PartDesign_SubtractiveHelix"}

    def IsActive(self):
        doc = App.ActiveDocument
        if doc is None or Gui.Control.activeDialog():
            return False
        from . import simplefeature as _sf
        body = _sf.body_of(doc)
        return body is not None and _sf.has_solid(body)

    def Activated(self):
        make(edge=_picked_edge())


def register():
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, _Command())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Thread command not added (%s)\n" % error)
