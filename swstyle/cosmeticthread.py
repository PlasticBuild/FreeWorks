# SPDX-License-Identifier: LGPL-2.1-or-later
""















_FW_SEEN = set()



def _alive(obj):
    """False for None or an object deleted under its wrapper (teardown.alive, review 1119)."""
    from . import teardown
    return teardown.alive(obj)


def _doc_alive(doc):
    from . import teardown
    return teardown.doc_alive(doc)


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import json
import math

import FreeCAD as App
import Part

from . import simplefeature as sf
from .simplefeature import Field

V = App.Vector
COMMAND = "SWStyle_CosmeticThread"
PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/CosmeticThreads"
INCH = 25.4
TOL = 1e-4


# --------------------------------------------------------------------------- thread sizes
def _metric():
    # ISO 261 coarse and fine pitches: the sizes FreeCAD's ISO metric tap lists have, so every tap the
    # Hole Wizard makes has its cosmetic thread (PATCH-MERGE PM thread pkg148)
    coarse = [(1, .25), (1.1, .25), (1.2, .25), (1.4, .3), (1.6, .35), (1.8, .35), (2, .4), (2.2, .45), (2.5, .45),
              (3, .5), (3.5, .6), (4, .7), (4.5, .75), (5, .8), (6, 1), (7, 1), (8, 1.25), (9, 1.25), (10, 1.5),
              (11, 1.5), (12, 1.75), (14, 2), (16, 2), (18, 2.5), (20, 2.5), (22, 2.5), (24, 3), (27, 3), (30, 3.5),
              (33, 3.5), (36, 4), (39, 4), (42, 4.5), (45, 4.5), (48, 5), (52, 5), (56, 5.5), (60, 5.5), (64, 6),
              (68, 6)]
    fine = [(1, 0.2), (1.1, 0.2), (1.2, 0.2), (1.4, 0.2), (1.6, 0.2), (1.8, 0.2), (2, 0.25), (2.2, 0.25), (2.5,
            0.35), (3, 0.35), (3.5, 0.35), (4, 0.5), (4.5, 0.5), (5, 0.5), (5.5, 0.5), (6, 0.75), (7, 0.75), (8,
            0.75), (8, 1), (9, 0.75), (9, 1), (10, 0.75), (10, 1), (10, 1.25), (11, 0.75), (11, 1), (12, 1),
            (12, 1.25), (12, 1.5), (14, 1), (14, 1.25), (14, 1.5), (15, 1), (15, 1.5), (16, 1), (16, 1.5), (17,
            1), (17, 1.5), (18, 1), (18, 1.5), (18, 2), (20, 1), (20, 1.5), (20, 2), (22, 1), (22, 1.5), (22,
            2), (24, 1), (24, 1.5), (24, 2), (25, 1), (25, 1.5), (25, 2), (27, 1), (27, 1.5), (27, 2), (28, 1),
            (28, 1.5), (28, 2), (30, 1), (30, 1.5), (30, 2), (30, 3), (32, 1.5), (32, 2), (33, 1.5), (33, 2),
            (33, 3), (35, 1.5), (35, 2), (36, 1.5), (36, 2), (36, 3), (39, 1.5), (39, 2), (39, 3), (40, 1.5),
            (40, 2), (40, 3), (42, 1.5), (42, 2), (42, 3), (42, 4), (45, 1.5), (45, 2), (45, 3), (45, 4), (48,
            1.5), (48, 2), (48, 3), (48, 4), (50, 1.5), (50, 2), (50, 3), (52, 1.5), (52, 2), (52, 3), (52, 4),
            (55, 1.5), (55, 2), (55, 3), (55, 4), (56, 1.5), (56, 2), (56, 3), (56, 4), (58, 1.5), (58, 2), (58,
            3), (58, 4), (60, 1.5), (60, 2), (60, 3), (60, 4), (62, 1.5), (62, 2), (62, 3), (62, 4), (64, 1.5),
            (64, 2), (64, 3), (64, 4), (65, 1.5), (65, 2), (65, 3), (65, 4), (68, 1.5), (68, 2), (68, 3), (68,
            4), (70, 1.5), (70, 2), (70, 3), (70, 4), (70, 6), (72, 1.5), (72, 2), (72, 3), (72, 4), (72, 6),
            (75, 1.5), (75, 2), (75, 3), (75, 4), (75, 6), (76, 1.5), (76, 2), (76, 3), (76, 4), (76, 6), (80,
            1.5), (80, 2), (80, 3), (80, 4), (80, 6), (85, 2), (85, 3), (85, 4), (85, 6), (90, 2), (90, 3), (90,
            4), (90, 6), (95, 2), (95, 3), (95, 4), (95, 6), (100, 2), (100, 3), (100, 4), (100, 6)]
    pitch = lambda p: "%.1f" % p if p == int(p) else "%g" % p
    return sorted((("M%gx%s" % (d, pitch(p)), d, p) for d, p in coarse + fine), key=lambda r: (r[1], -r[2]))


def _inch():
    numbered = lambda n: 0.060 + 0.013 * n
    unc = [("#1-64", numbered(1), 64), ("#2-56", numbered(2), 56), ("#3-48", numbered(3), 48),
           ("#4-40", numbered(4), 40), ("#5-40", numbered(5), 40), ("#6-32", numbered(6), 32),
           ("#8-32", numbered(8), 32), ("#10-24", numbered(10), 24), ("#12-24", numbered(12), 24),
           ("1/4-20", .25, 20), ("5/16-18", .3125, 18), ("3/8-16", .375, 16), ("7/16-14", .4375, 14),
           ("1/2-13", .5, 13), ("9/16-12", .5625, 12), ("5/8-11", .625, 11), ("3/4-10", .75, 10),
           ("7/8-9", .875, 9), ("1-8", 1.0, 8),
           # ASME B1.1 above 1 in (PATCH-MERGE pkg148)
           ("1 1/8-7", 1.125, 7), ("1 1/4-7", 1.25, 7), ("1 3/8-6", 1.375, 6), ("1 1/2-6", 1.5, 6),
           ("1 3/4-5", 1.75, 5), ("2-4.5", 2.0, 4.5), ("2 1/4-4.5", 2.25, 4.5), ("2 1/2-4", 2.5, 4),
           ("2 3/4-4", 2.75, 4), ("3-4", 3.0, 4), ("3 1/4-4", 3.25, 4), ("3 1/2-4", 3.5, 4), ("3 3/4-4", 3.75, 4),
           ("4-4", 4.0, 4)]
    unf = [("#0-80", numbered(0), 80), ("#1-72", numbered(1), 72), ("#2-64", numbered(2), 64),
           ("#3-56", numbered(3), 56), ("#4-48", numbered(4), 48), ("#5-44", numbered(5), 44),
           ("#6-40", numbered(6), 40), ("#8-36", numbered(8), 36), ("#10-32", numbered(10), 32),
           ("#12-28", numbered(12), 28), ("1/4-28", .25, 28), ("5/16-24", .3125, 24), ("3/8-24", .375, 24),
           ("7/16-20", .4375, 20), ("1/2-20", .5, 20), ("9/16-18", .5625, 18), ("5/8-18", .625, 18),
           ("3/4-16", .75, 16), ("7/8-14", .875, 14), ("1-12", 1.0, 12),
           ("1 1/8-12", 1.125, 12), ("1 1/4-12", 1.25, 12), ("1 3/8-12", 1.375, 12), ("1 1/2-12", 1.5, 12)]
    unef = [("#12-32", numbered(12), 32), ("1/4-32", .25, 32), ("5/16-32", .3125, 32), ("3/8-32", .375, 32),
            ("7/16-28", .4375, 28), ("1/2-28", .5, 28), ("9/16-24", .5625, 24), ("5/8-24", .625, 24),
            ("11/16-24", .6875, 24), ("3/4-20", .75, 20), ("13/16-20", .8125, 20), ("7/8-20", .875, 20),
            ("15/16-20", .9375, 20), ("1-20", 1.0, 20), ("1 1/16-18", 1.0625, 18), ("1 1/8-18", 1.125, 18),
            ("1 3/16-18", 1.1875, 18), ("1 1/4-18", 1.25, 18), ("1 5/16-18", 1.3125, 18), ("1 3/8-18", 1.375, 18),
            ("1 7/16-18", 1.4375, 18), ("1 1/2-18", 1.5, 18), ("1 9/16-18", 1.5625, 18), ("1 5/8-18", 1.625, 18),
            ("1 11/16-18", 1.6875, 18)]       # ASME B1.1 UNEF (PATCH-MERGE pkg148)
    rows = [("%s UNC" % n, d * INCH, INCH / tpi) for n, d, tpi in unc] + \
           [("%s UNF" % n, d * INCH, INCH / tpi) for n, d, tpi in unf] + \
           [("%s UNEF" % n, d * INCH, INCH / tpi) for n, d, tpi in unef]
    return sorted(rows, key=lambda r: (r[1], -r[2]))


METRIC = _metric()
SIZES = {"ANSI Inch": _inch(), "ANSI Metric": METRIC, "ISO": METRIC}
STANDARDS = ["None", "ANSI Inch", "ANSI Metric", "ISO"]
ALL_SIZES = list(dict.fromkeys(r[0] for rows in SIZES.values() for r in rows))
ENDS = ["Blind", "Through", "Up to Next"]


def size(standard, name):
    """(major diameter, pitch) in mm, or None."""
    for n, d, p in SIZES.get(standard, ()):
        if n == name:
            return d, p
    return None


def nearest(standard, diameter, internal):
    """The size of standard that fits a shaft (its major diameter) or a hole (its tap drill, major
    less one pitch) of this diameter."""
    rows = SIZES.get(standard) or []
    if not rows:
        return None
    return min(rows, key=lambda r: (abs((r[1] - r[2] if internal else r[1]) - diameter), -r[2]))[0]


def callout(standard, name, internal, end, depth, diameter, thread_class=""):
    if standard == "None":
        text = "⌀%.2f Thread" % diameter
    elif standard == "ANSI Inch":
        text = "%s-%s" % (name, (thread_class or ("2B" if internal else "2A")))
    else:
        text = "%s-%s" % (name, "6H" if internal else "6g")
    if end == "Through":
        return text + " THRU"
    return text + (" x %.2f deep" % depth if end == "Blind" else "")


# --------------------------------------------------------------------------- the geometry
def _hidden(obj):
    for name, kind, doc in (("ThreadInfo", "App::PropertyString", "Where the thread is drawn (JSON)"),
                            ("SizeFor", "App::PropertyFloat", "The edge diameter the size was chosen for")):
        if name not in obj.PropertiesList:
            obj.addProperty(kind, name, "Cosmetic Thread", doc)
            obj.setEditorMode(name, 2)


def _same_cylinder(face, centre, axis, radius):
    """A cylinder of this radius on the axis, or a cone on the axis (a tapered pipe thread)."""
    s = face.Surface
    kind = type(s).__name__
    if kind not in ("Cylinder", "Cone") or (kind == "Cylinder" and abs(s.Radius - radius) > TOL):
        return False
    if abs(abs(V(s.Axis).dot(axis)) - 1) > 1e-7:
        return False
    off = V(s.Apex if kind == "Cone" else s.Center) - centre
    return (off - axis * off.dot(axis)).Length < TOL


def _taper(face, centre, direction):
    """How much the radius grows per mm along the thread (0 on a cylinder)."""
    if type(face.Surface).__name__ != "Cone":
        return 0.0
    rows = []
    for e in face.Edges:
        c = getattr(e, "Curve", None)
        if type(c).__name__ == "Circle":
            rows.append(((V(c.Center) - centre).dot(direction), c.Radius))
    if len(rows) < 2:
        return 0.0
    (t1, r1), (t2, r2) = min(rows), max(rows)
    return (r2 - r1) / (t2 - t1) if abs(t2 - t1) > TOL else 0.0


def _span(face, centre, direction):
    ts = [(v.Point - centre).dot(direction) for v in face.Vertexes] or [0.0]
    # a closed cylinder face may have only seam vertices: use its edges' ends too
    for e in face.Edges:
        for p in (e.valueAt(e.FirstParameter), e.valueAt(e.LastParameter)):
            ts.append((p - centre).dot(direction))
    return min(ts), max(ts)


def geometry(obj, base):
    """The thread's start centre, direction, face radius, length and whether it is in a hole."""
    picked = sf.elements(obj, "Edge")
    if not picked:
        return None
    edge = picked[0][1]
    circle = getattr(edge, "Curve", None)
    if type(circle).__name__ != "Circle":
        raise RuntimeError("Pick a circular edge of a round shaft or hole")
    centre, axis, radius = V(circle.Center), V(circle.Axis), circle.Radius
    axis.normalize()
    faces = [f for f in base.Faces if _same_cylinder(f, centre, axis, radius)]
    touching = [f for f in faces if f.distToShape(edge)[0] < TOL]
    if not touching:
        raise RuntimeError("The edge is not the end of a cylindrical face")
    face = touching[0]
    direction = axis if (face.CenterOfMass - centre).dot(axis) > 0 else -axis
    if obj.Reverse:
        direction = -direction
    # in a hole, the face looks in towards the axis
    u0, u1, v0, v1 = face.ParameterRange
    u, v = 0.5 * (u0 + u1), 0.5 * (v0 + v1)
    p = face.valueAt(u, v)
    radial = (p - centre) - axis * (p - centre).dot(axis)
    internal = face.normalAt(u, v).dot(radial) < 0
    if obj.EndCondition == "Blind":
        length = obj.Depth.Value
    elif obj.EndCondition == "Up to Next":
        length = max(0.0, _span(face, centre, direction)[1])
    else:
        # every face of this cylinder that carries on from the edge, end to end
        length, grew = max(0.0, _span(face, centre, direction)[1]), True
        while grew:
            grew = False
            for f in faces:
                lo, hi = _span(f, centre, direction)
                if lo <= length + TOL and hi > length + TOL:
                    length, grew = hi, True
    if length <= TOL:
        raise RuntimeError("The thread has no length this way: try Reverse direction")
    return {"centre": centre, "direction": direction, "radius": radius, "length": length, "internal": internal,
            "taper": _taper(face, centre, direction)}


def diameters(obj, internal):
    """(the thread's other diameter, pitch): minor on a shaft, major in a hole."""
    if obj.Standard == "None":
        return obj.Diameter.Value, 0.0
    found = size(obj.Standard, obj.Size)
    if found is None:
        raise RuntimeError("Pick a size for %s" % obj.Standard)
    major, pitch = found
    return (major if internal else major - 1.0825318 * pitch), pitch


def _compute(obj, base):
    _hidden(obj)
    g = geometry(obj, base)
    if g is None:
        obj.ThreadInfo = ""
        obj.Callout = ""
        return None, None
    other, pitch = diameters(obj, g["internal"])
    info = {"centre": list(g["centre"]), "direction": list(g["direction"]), "radius": g["radius"],
            "other": other / 2.0, "length": g["length"], "pitch": pitch, "internal": g["internal"],
            "taper": g.get("taper", 0.0)}
    text = json.dumps(info)
    if obj.ThreadInfo != text:
        obj.ThreadInfo = text
    words = callout(obj.Standard, obj.Size, g["internal"], obj.EndCondition, g["length"], other,
                    getattr(obj, "ThreadClass", "")) if getattr(obj, "WithCallout", True) else ""
    if obj.Callout != words:
        obj.Callout = words
    _Overlay.poke()
    return base, None


# --------------------------------------------------------------------------- the PropertyManager
class Panel(sf.Panel):
    """The fields, with Size listing only the chosen Standard's sizes, and the size nearest the
    picked edge chosen for it."""

    def __init__(self, obj):
        self._standard = None
        self._auto = False
        super().__init__(obj)
        self._sizes()
        self._show()

    def _sizes(self):
        combo = self.widgets["Size"]
        standard = self.obj.Standard
        if standard == self._standard:
            return
        self._standard = standard
        if standard == "None":
            return
        names = [r[0] for r in SIZES.get(standard, ())]
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(names)
        if self.obj.Size in names:
            combo.setCurrentText(self.obj.Size)
        combo.blockSignals(False)

    def _changed(self, *args):
        if self.busy:
            return
        standard = self.widgets["Standard"].currentText()
        if standard != self._standard:
            obj = self.obj
            g = self._geometry()
            if standard == "None" and obj.Standard != "None" and g is not None:
                try:
                    obj.Diameter = diameters(obj, g["internal"])[0]
                except Exception as _fw_err:
                    _fw_log("cosmeticthread.py:305", _fw_err)
            obj.Standard = standard
            if standard != "None" and g is not None:
                obj.Size = nearest(standard, 2 * g["radius"], g["internal"])
            self._sizes()
            self.busy = True
            for name in ("Diameter",):
                widget = self.widgets[name]
                widget.setValue(getattr(obj, name).Value)
            self.busy = False
        super()._changed(*args)

    def _geometry(self):
        try:
            base = self.obj.BaseFeature.Shape if self.obj.BaseFeature is not None else None
            return geometry(self.obj, base) if base is not None else None
        except Exception:
            return None

    def _show(self):
        obj = self.obj
        if hasattr(self, "_standard") and not self._auto and "SizeFor" in obj.PropertiesList:
            g = self._geometry()
            if g is not None and abs(obj.SizeFor - 2 * g["radius"]) > 1e-6:
                # a new edge: the nearest size, and a depth of one and a half diameters
                self._auto = True
                try:
                    first = obj.SizeFor == 0
                    obj.SizeFor = 2 * g["radius"]
                    if obj.Standard != "None":
                        obj.Size = nearest(obj.Standard, 2 * g["radius"], g["internal"])
                    else:
                        obj.Diameter = 2 * g["radius"] * (1.1 if g["internal"] else 0.85)
                    if first:
                        obj.Depth = round(1.5 * 2 * g["radius"], 2)
                    obj.Document.recompute()
                    self.busy = True
                    self._standard = None
                    self._sizes()
                    self.widgets["Size"].setCurrentText(obj.Size)
                    self.widgets["Depth"].setValue(obj.Depth.Value)
                    self.widgets["Diameter"].setValue(obj.Diameter.Value)
                    self.busy = False
                finally:
                    self._auto = False
        super()._show()


SPEC = sf.Spec(
    COMMAND, "Cosmetic Thread", "Cosmetic Thread",
    "Shows a thread on a round shaft or hole without modeling it.",
    "FEATURES_COSMETIC_THREAD", "PartDesign_Hole",
    [Field("Edge", "pick", "Circular edge", what=("Edge",), box="Thread Settings",
           tip="The circular edge where the thread starts"),
     Field("Reverse", "bool", "Reverse direction", False, box="Thread Settings"),
     Field("Standard", "enum", "Standard", "ISO", values=STANDARDS, box="Specification"),
     Field("Size", "enum", "Size", "M6x1.0", values=ALL_SIZES, box="Specification",
           shown=lambda o: o.Standard != "None"),
     Field("Diameter", "length", "Thread diameter", 5.0, box="Specification",
           shown=lambda o: o.Standard == "None",
           tip="The thread's other diameter: the minor diameter on a shaft, the major diameter in a hole"),
     Field("EndCondition", "enum", "End condition", "Blind", values=ENDS, box="Specification"),
     Field("Depth", "length", "Depth", 10.0, box="Specification", shown=lambda o: o.EndCondition == "Blind"),
     Field("ThreadClass", "enum", "Thread class", "", values=["", "1B", "2B", "3B", "1A", "2A", "3A"],
           box="Specification", shown=lambda o: o.Standard == "ANSI Inch", tip="Into the callout; blank: 2B in a hole, 2A on a shaft"),
     Field("WithCallout", "bool", "With thread callout", True, box="Thread Callout",
           tip="Off: the thread carries no callout (Hole Wizard's With thread callout)"),
     Field("Callout", "info", "Thread callout", "", box="Thread Callout")],
    _compute, refine=False, panel=Panel)


# --------------------------------------------------------------------------- drawing it
class _Overlay:
    """Draws every cosmetic thread of the active document over the model."""
    timer = None
    root = None
    view = None
    signature = None
    drawn = {}

    @classmethod
    def start(cls):
        if cls.timer is not None:
            return
        from PySide import QtCore
        cls.timer = QtCore.QTimer()
        cls.timer.timeout.connect(cls.tick)
        cls.timer.start(400)

    @classmethod
    def poke(cls):
        cls.signature = None

    @staticmethod
    def _shown(obj):
        body = obj.getParentGeoFeatureGroup()
        if body is None or not body.Visibility or getattr(obj, "Suppressed", False):
            return False
        if "Invalid" in obj.State or not obj.ThreadInfo:
            return False
        group = list(body.Group)
        tip = body.Tip
        # rolled back: after the tip
        return tip is None or tip not in group or obj not in group or group.index(obj) <= group.index(tip)

    @classmethod
    def tick(cls):
        try:
            import FreeCADGui as Gui
            doc = Gui.ActiveDocument
            view = doc.ActiveView if doc is not None else None
            if view is None or not hasattr(view, "getSceneGraph"):
                return
            params = App.ParamGet(PARAMS)
            show, shaded = params.GetBool("Display", True), params.GetBool("Shaded", False)
            threads = [o for o in doc.Document.Objects
                       if getattr(o, "SWStyleKind", "") == "CosmeticThread" and "ThreadInfo" in o.PropertiesList]
            items = []
            for o in threads:
                if show and cls._shown(o):
                    body = o.getParentGeoFeatureGroup()
                    items.append((o.Name, o.ThreadInfo, str(body.getGlobalPlacement())))
            signature = (id(view), shaded, tuple(items))
            if signature == cls.signature:
                return
            cls.signature = signature
            cls._draw(view, items, shaded, doc.Document)
        except Exception as error:
            App.Console.PrintLog("FreeCAD cosmetic threads: %s\n" % error)

    @classmethod
    def _draw(cls, view, items, shaded, doc):
        from pivy import coin
        if cls.root is not None and cls.view is not None and _alive(cls.view):
            try:
                cls.view.getSceneGraph().removeChild(cls.root)
            except Exception as _fw_err:
                _fw_log("cosmeticthread.py:442", _fw_err)
        cls.root, cls.view, cls.drawn = coin.SoSeparator(), view, {}
        cls.root.setName("SWStyle_CosmeticThreads")
        style = coin.SoDrawStyle()
        style.lineWidth = 1.5
        colour = coin.SoBaseColor()
        colour.rgb = (0.25, 0.25, 0.25)
        cls.root.addChild(style)
        cls.root.addChild(colour)
        for name, text, _place in items:
            obj = doc.getObject(name)
            info = json.loads(text)
            place = obj.getParentGeoFeatureGroup().getGlobalPlacement()
            centre, direction = V(*info["centre"]), V(*info["direction"])
            radius, other, length, pitch = info["radius"], info["other"], info["length"], info["pitch"]
            taper = info.get("taper", 0.0)        # a tapered pipe thread narrows (or widens) along its length
            rings = [(0.0, other), (length, max(other + taper * length, 0.01))]
            band = None
            if shaded:

                # on the air side, its helix one pitch per turn
                lift = (radius + 0.5 * taper * length) * (0.996 if info["internal"] else 1.004)
                try:
                    band = cls._band(coin, place, centre, direction, lift, length,
                                     pitch if pitch > 0 else max(0.25, radius / 4.0))
                except Exception as error:
                    App.Console.PrintLog("FreeCAD shaded cosmetic thread: %s\n" % error)
                if band is None and pitch > 0:
                    count = min(400, int(length / pitch))
                    rings += [(pitch * (k + 0.5), max(radius + taper * pitch * (k + 0.5), 0.01)) for k in range(count)]
            points, counts = [], []
            for t, r in rings:
                circle = Part.makeCircle(r, centre + direction * t, direction)
                pts = [place.multVec(p) for p in circle.discretize(Number=65)]
                points.extend((p.x, p.y, p.z) for p in pts)
                counts.append(len(pts))
            sep = coin.SoSeparator()
            sep.setName(str("SWStyle_CosmeticThread_" + name))
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, len(points), points)
            lines = coin.SoLineSet()
            lines.numVertices.setValues(0, len(counts), counts)
            if band is not None:
                sep.addChild(band)
            sep.addChild(coords)
            sep.addChild(lines)
            cls.root.addChild(sep)
            cls.drawn[name] = {"rings": len(rings), "radii": sorted(set(round(r, 4) for _, r in rings)),
                               "length": length, "shaded": band is not None}
        view.getSceneGraph().addChild(cls.root)


def thread_image(size=64):
    """The shaded thread's picture: light crests and dark roots, slanted so that wrapped once
    round the cylinder it climbs one pitch (a helix)."""
    rows = []
    for j in range(size):
        row = bytearray()
        for i in range(size):
            k = 0.5 + 0.5 * math.cos(2.0 * math.pi * ((j - i) / float(size)))
            v = int(70 + 150 * k)
            row += bytes((v, v, v))
        rows.append(bytes(row))
    return b"".join(rows)


def _band_impl(coin, place, centre, direction, radius, length, pitch, around=48):
    sep = coin.SoSeparator()
    hints = coin.SoShapeHints()
    hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
    hints.shapeType = coin.SoShapeHints.UNKNOWN_SHAPE_TYPE
    sep.addChild(hints)
    mat = coin.SoMaterial()
    mat.diffuseColor = (0.75, 0.75, 0.75)
    sep.addChild(mat)
    tex = coin.SoTexture2()
    tex.image.setValue(coin.SbVec2s(64, 64), 3, thread_image(64))
    tex.model = coin.SoTexture2.MODULATE
    sep.addChild(tex)
    d = V(direction)
    d.normalize()
    x = d.cross(V(0, 0, 1)) if abs(d.z) < 0.9 else d.cross(V(1, 0, 0))
    x.normalize()
    y = d.cross(x)
    pts, uv = [], []
    for row, t in enumerate((0.0, length)):
        for k in range(around + 1):
            a = 2.0 * math.pi * k / around
            p = centre + d * t + (x * math.cos(a) + y * math.sin(a)) * radius
            p = place.multVec(p)
            pts.append((p.x, p.y, p.z))
            uv.append((k / float(around), t / pitch))
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, len(pts), pts)
    tc = coin.SoTextureCoordinate2()
    tc.point.setValues(0, len(uv), uv)
    mesh = coin.SoQuadMesh()
    mesh.verticesPerRow = around + 1
    mesh.verticesPerColumn = 2
    for n in (coords, tc, mesh):
        sep.addChild(n)
    return sep


_Overlay._band = staticmethod(_band_impl)


def register():
    sf.register(SPEC)
    try:
        _Overlay.start()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: cosmetic threads are not drawn: %s\n" % error)
