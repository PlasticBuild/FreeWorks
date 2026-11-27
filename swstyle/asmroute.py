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

import itertools
import json

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import asmcore as ac

V = App.Vector
CP_TYPE = "SWStyle::ConnectionPoint"
ROUTE_TYPE = "SWStyle::Route"
KINDS = ("Pipe", "Tube", "Electrical", "User", "Clip")      # connection point types
ROUTE_KINDS = ("Pipe", "Tube", "Electrical", "User")
KIND_NAMES = {"User": "User Defined", "Clip": "Clip (route through)"}     # Connection Point Type list
LABELS = {"Pipe": "Pipe", "Tube": "Tube", "Electrical": "Cable", "User": "Route"}
OPEN = []
TOL = 1e-7
ORDERS = list(itertools.permutations((0, 1, 2)))


# ---------------------------------------------------------------------- connection points
def _circle(edge):
    c = getattr(edge, "Curve", None)
    return c if type(c).__name__ == "Circle" else None


def frame(obj, sub):
    """(centre, outward direction, diameter) of a round edge (or a cylinder face's end) of obj."""
    shape = obj.Shape.getElement(sub)
    if shape.ShapeType == "Face" and type(shape.Surface).__name__ == "Cylinder":
        circles = [e for e in shape.Edges if _circle(e) is not None]
        if not circles:
            return None
        shape = circles[0]
    c = _circle(shape) if shape.ShapeType == "Edge" else None
    if c is None:
        return None
    centre, axis = V(c.Center), V(c.Axis).normalize()
    solid = obj.Shape
    eps = max(0.01, c.Radius * 0.05)
    try:
        # outward: the side with no material just inside the rim
        rim = centre + _perp(axis) * (c.Radius * 0.5)
        if solid.isInside(rim + axis * eps, 1e-6, True) and not solid.isInside(rim - axis * eps, 1e-6, True):
            axis = -axis
        elif solid.isInside(centre + axis * eps, 1e-6, True) and not solid.isInside(centre - axis * eps, 1e-6, True):
            axis = -axis
    except Exception as _fw_err:
        _fw_log("asmroute.py:79", _fw_err)
    return centre, axis, 2 * c.Radius


def _perp(d):
    a = V(1, 0, 0) if abs(d.x) < 0.9 else V(0, 1, 0)
    return d.cross(a).normalize()


class ConnectionPoint:
    Type = CP_TYPE

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        props = obj.PropertiesList
        for kind, name, tip in (("App::PropertyString", "Reference", "Object:Element of the round edge"),
                                ("App::PropertyString", "RouteType", "Pipe or Tube"),
                                ("App::PropertyString", "PortID", "Port ID"),
                                ("App::PropertyFloat", "Diameter", "Port diameter (mm)"),
                                ("App::PropertyBool", "Flip", "Reverse the direction"),
                                ("App::PropertyVector", "Position", "Center (read only)"),
                                ("App::PropertyVector", "Direction", "Outward direction (read only)")):
            if name not in props:
                obj.addProperty(kind, name, "Connection Point", tip)
        for name in ("Position", "Direction"):
            obj.setEditorMode(name, 1)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def execute(self, obj):
        name, _sep, sub = obj.Reference.partition(":")
        target = obj.Document.getObject(name)
        if target is None:
            return
        f = frame(target, sub)
        if f is None:
            return
        obj.Position = f[0]
        obj.Direction = -f[1] if obj.Flip else f[1]
        if not obj.Diameter:
            obj.Diameter = f[2]

    def dumps(self):
        return None

    def loads(self, state):
        return None


class _MarkerView:
    ""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        from pivy import coin
        self.Object = vobj.Object
        self.root = coin.SoSeparator()
        colour = coin.SoBaseColor()
        colour.rgb.setValue(0.1, 0.6, 0.1)
        self.root.addChild(colour)
        style = coin.SoDrawStyle()
        style.lineWidth = 2
        self.root.addChild(style)
        self.coords = coin.SoCoordinate3()
        self.root.addChild(self.coords)
        self.lines = coin.SoLineSet()
        self.root.addChild(self.lines)
        vobj.addDisplayMode(self.root, "Default")
        self.updateData(vobj.Object, "Position")

    def updateData(self, obj, prop):
        if prop not in ("Position", "Direction") or not hasattr(self, "coords"):
            return
        p, d = V(obj.Position), V(obj.Direction)
        if d.Length < TOL:
            return
        size = max(5.0, float(getattr(obj, "Diameter", 0) or 0))
        tip = p + d * size
        side = _perp(d) * size * 0.2
        pts = [p, tip, tip, tip - d * size * 0.3 + side, tip, tip - d * size * 0.3 - side]
        self.coords.point.setValues(0, len(pts), [(q.x, q.y, q.z) for q in pts])
        self.lines.numVertices.setValues(0, 3, [2, 2, 2])

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        return ":/icons/Std_Placement.svg"

    def doubleClicked(self, vobj):
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def connection_points(doc):
    return [o for o in (doc.Objects if doc is not None else [])
            if getattr(getattr(o, "Proxy", None), "Type", None) == CP_TYPE]


def make_connection_point(obj, sub, kind="Pipe", port="", flip=False):
    doc = obj.Document
    cp = doc.addObject("App::FeaturePython", "CPoint")
    ConnectionPoint(cp)
    if App.GuiUp:
        _MarkerView(cp.ViewObject)
    cp.Reference = "%s:%s" % (obj.Name, sub)
    cp.RouteType = kind
    cp.PortID = port
    cp.Flip = bool(flip)
    n = len(connection_points(doc))
    cp.Label = "CPoint%d" % n
    cp.recompute()
    doc.recompute()
    return cp


def _comp_placement(comp):
    from . import asmexplode as ax
    try:
        return ax.gplacement(comp)
    except Exception:
        return comp.Placement


def ports(asm):
    """[(component, connection point, global position, global direction)] of the assembly's components."""
    out = []
    for comp in ac.components(asm):
        target = getattr(comp, "LinkedObject", None)
        if target is None:
            continue
        pl = _comp_placement(comp)
        if not getattr(comp, "LinkTransform", False) and hasattr(target, "Placement"):
            pl = pl.multiply(target.Placement.inverse())     # the link's placement replaces the part's own
        for cp in connection_points(target.Document):
            ref = target.Document.getObject(cp.Reference.partition(":")[0])
            if ref is None or (ref is not target and target not in ref.InListRecursive):
                continue
            p = pl.multVec(V(cp.Position))
            d = pl.Rotation.multVec(V(cp.Direction))
            out.append((comp, cp, p, d))
    return out


def port_key(comp, cp):
    return "%s:%s" % (comp.Name, cp.Name)


def port_of(asm, key):
    for comp, cp, p, d in ports(asm):
        if port_key(comp, cp) == key:
            return comp, cp, p, d
    return None


# ---------------------------------------------------------------------- the route
def auto_route(a, da, b, db, stub, order=0):
    """Route points: out of port a along da by stub, orthogonal legs, into port b along db."""
    s0, s1 = a + da * stub, b + db * stub
    # the stubs meet: no leg back over itself (a stub that reaches past the other one is cut back
    # to it, so the route goes into the port straight, not out, back and round a kink)
    over = (s0 - s1).dot(db)
    if over < 0 and stub + over >= 0.25 * stub:
        s1 = b + db * (stub + over)
    over = (s1 - s0).dot(da)
    if over < 0 and stub + over >= 0.25 * stub:
        s0 = a + da * (stub + over)
    pts = [a, s0]
    cur = V(s0)
    for axis in ORDERS[order % len(ORDERS)]:
        nxt = V(cur)
        setattr(nxt, "xyz"[axis], getattr(s1, "xyz"[axis]))
        if (nxt - cur).Length > TOL:
            pts.append(nxt)
            cur = nxt
    pts += [s1, b]
    return simplify(pts)


def through_route(ends, stub, order=0):
    """Route points from the first port, through each clip (along its axis, in on the side the
    route comes from and out the other, so a clip passes the route straight through), into the last port.
    ends: [(position, outward direction)]; the middle ones are clips."""
    pts = []
    sides = []                                  # per clip: +1 enter on its direction's side, -1 the other
    for i in range(1, len(ends) - 1):
        v, dv = V(ends[i][0]), V(ends[i][1])
        sides.append(1.0 if (V(ends[i - 1][0]) - v).dot(dv) >= 0 else -1.0)
    for i in range(len(ends) - 1):
        (a, da), (b, db) = ends[i], ends[i + 1]
        if 0 < i:
            da = V(da) * -sides[i - 1]          # out of a clip on its far side
        if i + 1 < len(ends) - 1:
            db = V(db) * sides[i]               # into a clip from the near side
        leg = auto_route(V(a), V(da), V(b), V(db), stub, order)
        pts += leg[1:] if pts else leg
    return simplify(pts)


def simplify(pts):
    out = []
    for p in pts:
        if out and (p - out[-1]).Length < 1e-6:
            continue
        out.append(V(p))
    i = 1
    while i < len(out) - 1:
        u, w = out[i] - out[i - 1], out[i + 1] - out[i]
        if u.Length > TOL and w.Length > TOL and u.cross(w).Length < 1e-9 * u.Length * w.Length:
            del out[i]          # straight on, or straight back (a spike: the sweep would cross itself)
        else:
            i += 1
    return out


def centreline(pts, radius):
    """The route's centre line: straight runs joined by arcs of the bend (elbow) radius."""
    if len(pts) < 2:
        return None, []
    edges, bends = [], []
    start = pts[0]
    for i in range(1, len(pts) - 1):
        p, q, r = pts[i - 1], pts[i], pts[i + 1]
        u, w = (q - p), (r - q)
        lu, lw = u.Length, w.Length
        u.normalize()
        w.normalize()
        cosang = max(-1.0, min(1.0, u.dot(w)))
        import math
        angle = math.acos(cosang)
        t = radius * math.tan(angle / 2) if angle > 1e-6 else 0.0
        if t <= TOL or t > min(lu, lw) * 0.999 or angle > math.pi - 1e-6:
            if (q - start).Length > TOL:
                edges.append(Part.LineSegment(start, q).toShape())
            start = q
            continue
        a, b = q - u * t, q + w * t
        if (a - start).Length > TOL:
            edges.append(Part.LineSegment(start, a).toShape())
        bis = (w - u)
        bis.normalize()
        mid = q + bis * (radius / math.cos(angle / 2) - radius)
        edges.append(Part.Arc(a, mid, b).toShape())
        bends.append((a, b, math.degrees(angle)))
        start = b
    if (pts[-1] - start).Length > TOL:
        edges.append(Part.LineSegment(start, pts[-1]).toShape())
    return Part.Wire(edges), bends


def route_solid(pts, od, wall, radius):
    wire, _b = centreline(pts, radius)
    if wire is None:
        return Part.Shape()
    e0 = wire.Edges[0]
    p0, t0 = e0.valueAt(e0.FirstParameter), e0.tangentAt(e0.FirstParameter)

    def sweep(r):
        prof = Part.Wire(Part.makeCircle(r, p0, t0))
        return wire.makePipeShell([prof], True, True)
    outer = sweep(od / 2.0)
    if 0 < wall < od / 2.0:
        try:
            return outer.cut(sweep(od / 2.0 - wall))
        except Exception:
            return outer
    return outer


def pieces(route):
    ""
    pts = [V(p) for p in route.Points]
    wire, bends = centreline(pts, float(route.BendRadius))
    if wire is None:
        return []
    if route.Kind == "Tube":
        return [("Tube", "OD %g x %g" % (route.OD, route.Wall), round(wire.Length, 3))]
    if route.Kind == "Electrical":
        wires = wires_of(route)
        if not wires:
            return [("Cable", "D %g" % route.OD, round(wire.Length, 3))]
        return [("Wire", "%s %s" % (w.get("id", ""), w.get("spec", "")), round(wire.Length, 3)) for w in wires]
    if route.Kind == "User":
        return [("Route", "D %g" % route.OD, round(wire.Length, 3))]
    out = [("Pipe", "OD %g x %g" % (route.OD, route.Wall), round(e.Length, 3))
           for e in wire.Edges if type(e.Curve).__name__ in ("Line", "LineSegment")]
    out += [("Elbow", "%g deg R%g" % (round(a, 1), route.BendRadius), 1) for _a, _b, a in bends]
    return out


def summary(rows):
    """'Pipe OD 20 x 2: 4, 170.00mm / Elbow 90 deg R30: 3' for the PM."""
    groups = {}
    for kind, desc, n in rows:
        g = groups.setdefault((kind, desc), [0, 0.0])
        g[0] += 1
        g[1] += n
    out = []
    for (kind, desc), (count, total) in groups.items():
        if kind == "Wire":
            out.append("%s: %.2fmm" % (desc.strip(), total))
            continue
        out.append("%s %s: %d" % (kind, desc, count) if kind == "Elbow" else "%s %s: %d, %.2fmm" % (kind, desc, count, total))
    return "\n".join(out)


class Route:
    Type = ROUTE_TYPE

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        props = obj.PropertiesList
        for kind, name, tip in (("App::PropertyString", "Kind", "Pipe or Tube"),
                                ("App::PropertyFloat", "OD", "Outside diameter (mm)"),
                                ("App::PropertyFloat", "Wall", "Wall thickness (mm)"),
                                ("App::PropertyFloat", "BendRadius", "Elbow / bend radius (mm)"),
                                ("App::PropertyFloat", "Stub", "Stub length out of each port (mm)"),
                                ("App::PropertyInteger", "PathOrder", "Auto Route: which orthogonal path"),
                                ("App::PropertyString", "StartPort", "Component:CPoint"),
                                ("App::PropertyString", "EndPort", "Component:CPoint"),
                                ("App::PropertyStringList", "Via", "Clips the route passes through (Component:CPoint)"),
                                ("App::PropertyString", "Wires", "Electrical: the wires (json)"),
                                ("App::PropertyString", "AssemblyName", "The assembly the route is in"),
                                ("App::PropertyVectorList", "Points", "Route points"),
                                ("App::PropertyLinkListHidden", "Ends", "The components it connects (rebuild when they move)")):
            if name not in props:
                obj.addProperty(kind, name, "Route", tip)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def execute(self, obj):
        asm = obj.Document.getObject(obj.AssemblyName) if obj.AssemblyName else None
        if asm is not None and obj.StartPort and obj.EndPort:
            keys = [obj.StartPort] + list(obj.Via or ()) + [obj.EndPort]
            found = [port_of(asm, k) for k in keys]
            if all(f is not None for f in found):
                obj.Points = through_route([(f[2], f[3]) for f in found], obj.Stub, obj.PathOrder)
        pts = [V(p) for p in obj.Points]
        obj.Shape = route_solid(pts, obj.OD, obj.Wall, obj.BendRadius) if len(pts) >= 2 else Part.Shape()

    def dumps(self):
        return None

    def loads(self, state):
        return None


class RouteView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return ":/icons/Part_Sweep.svg"

    def doubleClicked(self, vobj):
        edit(vobj.Object)
        return True

    def setupContextMenu(self, vobj, menu):
        menu.addAction("Edit Route").triggered.connect(lambda: edit(vobj.Object))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def wires_of(route):
    try:
        return json.loads(route.Wires or "[]")
    except Exception:
        return []


def routes(asm):
    return [o for o in asm.Group if getattr(getattr(o, "Proxy", None), "Type", None) == ROUTE_TYPE]


def make_route(asm, kind, start, end, od, wall, radius, stub, order=0, via=()):
    doc = asm.Document
    r = doc.addObject("Part::FeaturePython", "Route")
    Route(r)
    if App.GuiUp:
        RouteView(r.ViewObject)
        try:
            r.ViewObject.ShapeAppearance = [App.Material(DiffuseColor=(0.7, 0.7, 0.72))]
        except Exception as _fw_err:
            _fw_log("asmroute.py:481", _fw_err)
    asm.addObject(r)
    set_route(r, asm, kind, start, end, od, wall, radius, stub, order, via)
    n = len([o for o in routes(asm) if o.Kind == kind])
    r.Label = "%s%d" % (LABELS.get(kind, kind), n)
    return r


def set_route(r, asm, kind, start, end, od, wall, radius, stub, order=0, via=()):
    r.Via = list(via or ())
    if kind in ("Electrical", "User"):
        wall = 0.0                              # a solid bundle / route, no bore
    r.Kind, r.OD, r.Wall, r.BendRadius, r.Stub, r.PathOrder = kind, float(od), float(wall), float(radius), float(stub), int(order)
    r.StartPort, r.EndPort, r.AssemblyName = start, end, asm.Name
    ends = [asm.Document.getObject(k.partition(":")[0]) for k in [start, end] + list(via or ())]
    r.Ends = [o for o in ends if o is not None]
    r.recompute()
    asm.Document.recompute()


# ---------------------------------------------------------------------- PropertyManagers
def _spin(name, value, lo=0.0, hi=1e5):
    b = QtWidgets.QDoubleSpinBox()
    b.setObjectName(name)
    b.setRange(lo, hi)
    b.setDecimals(2)
    b.setSuffix("mm")
    b.setValue(float(value))
    return b


class _Panel:
    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmroute.py:517", _fw_err)
        if self in OPEN:
            OPEN.remove(self)
        Gui.Control.closeDialog()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def removeSelection(self, *a):
        pass

    def clearSelection(self, *a):
        pass

    def setPreselection(self, *a):
        pass


class ConnectionPointPanel(_Panel):
    ""


    def __init__(self, doc):
        self.doc = doc
        self.ref = None
        form = QtWidgets.QWidget()
        form.setObjectName("SWConnectionPoint")
        form.setWindowTitle("Connection Point")
        form.setProperty("swstyle_pm_title", "Connection Point")
        lay = QtWidgets.QVBoxLayout(form)
        box = QtWidgets.QGroupBox("Selections", form)
        bl = QtWidgets.QVBoxLayout(box)
        self.pick = QtWidgets.QListWidget(box)
        self.pick.setObjectName("SWCPointPick")
        self.pick.setMaximumHeight(28)
        bl.addWidget(self.pick)
        self.flip = QtWidgets.QCheckBox("Reverse direction", box)
        self.flip.setObjectName("SWCPointFlip")
        bl.addWidget(self.flip)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Parameters", form)
        fl = QtWidgets.QFormLayout(box)
        self.kind = QtWidgets.QComboBox(box)
        self.kind.setObjectName("SWCPointType")
        for k in KINDS:
            self.kind.addItem(KIND_NAMES.get(k, k), k)
        fl.addRow("Type:", self.kind)
        self.port = QtWidgets.QLineEdit(box)
        self.port.setObjectName("SWCPointPort")
        fl.addRow("Port ID:", self.port)
        self.dia = _spin("SWCPointDiameter", 0.0)
        self.dia_label = QtWidgets.QLabel("Nominal diameter:")
        fl.addRow(self.dia_label, self.dia)
        self.kind.currentIndexChanged.connect(lambda *a: self.dia_label.setText(
            "Nominal diameter:" if self.kind_value() in ("Pipe", "Tube") else "Diameter:"))
        lay.addWidget(box)
        lay.addStretch(1)
        self.form = form
        for sel in Gui.Selection.getSelectionEx(doc.Name):
            for sub in (sel.SubElementNames or ()):
                self._add(sel.Object, sub)
        Gui.Selection.addObserver(self)
        OPEN.append(self)

    def addSelection(self, doc, name, sub, pnt):
        if doc != self.doc.Name:
            return
        obj = self.doc.getObject(name)
        if obj is not None:
            from . import safe_later as _sl; _sl.later(0, lambda: self._add(obj, sub), self, "pick")

    def _add(self, obj, sub):
        from . import refplane
        obj, sub = refplane.resolve(obj, sub or "")
        try:
            f = frame(obj, sub)
        except Exception:
            f = None
        if f is None:
            return
        self.ref = (obj, sub)
        self.pick.clear()
        self.pick.addItem("%s@%s" % (sub, obj.Label))
        if not self.dia.value():
            self.dia.setValue(f[2])

    def kind_value(self):
        return self.kind.currentData() or self.kind.currentText()

    def accept(self):
        if self.ref is None:
            return False
        self.doc.openTransaction("Connection Point")
        try:
            cp = make_connection_point(self.ref[0], self.ref[1], self.kind_value(), self.port.text().strip(),
                                       self.flip.isChecked())
            cp.Diameter = self.dia.value()
            self.result = cp
        finally:
            self.doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        self._close()
        return True


class RoutePanel(_Panel):
    ""


    def __init__(self, asm, kind="Pipe", route=None):
        self.asm, self.doc, self.route = asm, asm.Document, route
        self.kind = route.Kind if route is not None else kind
        self.start = route.StartPort if route is not None else ""
        self.end = route.EndPort if route is not None else ""
        self.order = route.PathOrder if route is not None else 0
        self.points = [V(p) for p in route.Points] if route is not None else []
        self.via = list(route.Via or ()) if route is not None else []
        self.wires = wires_of(route) if route is not None else []
        self.preview = None
        form = QtWidgets.QWidget()
        form.setObjectName("SWRouteProperties")
        title = "Route Properties"
        form.setWindowTitle(title)
        form.setProperty("swstyle_pm_title", title)
        lay = QtWidgets.QVBoxLayout(form)
        box = QtWidgets.QGroupBox("Route Type", form)
        bl = QtWidgets.QGridLayout(box)
        self.pipe = QtWidgets.QRadioButton("Piping", box)
        self.pipe.setObjectName("SWRoutePipe")
        self.tube = QtWidgets.QRadioButton("Tubing", box)
        self.tube.setObjectName("SWRouteTube")
        self.elec = QtWidgets.QRadioButton("Electrical", box)
        self.elec.setObjectName("SWRouteElectrical")
        self.user = QtWidgets.QRadioButton("User Defined", box)
        self.user.setObjectName("SWRouteUser")
        self.type_buttons = {"Pipe": self.pipe, "Tube": self.tube, "Electrical": self.elec, "User": self.user}
        self.type_buttons.get(self.kind, self.pipe).setChecked(True)
        for i, b in enumerate((self.pipe, self.tube, self.elec, self.user)):
            bl.addWidget(b, i // 2, i % 2)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Connection Points", form)
        fl = QtWidgets.QFormLayout(box)
        self.start_box = QtWidgets.QListWidget(box)
        self.start_box.setObjectName("SWRouteStart")
        self.start_box.setMaximumHeight(26)
        self.end_box = QtWidgets.QListWidget(box)
        self.end_box.setObjectName("SWRouteEnd")
        self.end_box.setMaximumHeight(26)
        fl.addRow("Start:", self.start_box)
        fl.addRow("End:", self.end_box)
        self.via_box = QtWidgets.QListWidget(box)
        self.via_box.setObjectName("SWRouteVia")
        self.via_box.setMaximumHeight(60)
        self.via_label = QtWidgets.QLabel("Route through:")
        fl.addRow(self.via_label, self.via_box)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Route Specification", form)
        box.setObjectName("SWRouteSpec")
        fl = QtWidgets.QFormLayout(box)
        port = port_of(asm, self.start) if self.start else None
        d0 = route.OD if route is not None else (port[1].Diameter if port else 20.0)
        self.od = _spin("SWRouteOD", d0, 0.1)
        fl.addRow("Outside diameter:", self.od)
        self.od_label = fl.labelForField(self.od)
        self.wall = _spin("SWRouteWall", route.Wall if route is not None else max(1.0, d0 * 0.1))
        self.wall_label = QtWidgets.QLabel("Wall thickness:")
        fl.addRow(self.wall_label, self.wall)
        self.wires_btn = QtWidgets.QPushButton("Edit Wires...", box)
        self.wires_btn.setObjectName("SWRouteEditWires")
        self.wires_btn.clicked.connect(self.edit_wires)
        fl.addRow(self.wires_btn)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Bends - Elbows", form)
        box.setObjectName("SWRouteBends")
        self.bend_box = box
        fl = QtWidgets.QFormLayout(box)
        self.radius_label = QtWidgets.QLabel("")
        self.radius = _spin("SWRouteRadius", route.BendRadius if route is not None else 1.5 * d0, 0.1)
        fl.addRow(self.radius_label, self.radius)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Options", form)
        box.setObjectName("SWRouteOptions")
        fl = QtWidgets.QFormLayout(box)
        self.stub = _spin("SWRouteStub", route.Stub if route is not None else 3.0 * d0, 0.0)
        fl.addRow("Stub length:", self.stub)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Auto Route", form)
        box.setObjectName("SWRouteAutoBox")
        self.auto_box = box
        bl = QtWidgets.QHBoxLayout(box)
        self.auto = QtWidgets.QPushButton("Auto Route", box)
        self.auto.setObjectName("SWRouteAuto")
        self.alternate = QtWidgets.QPushButton("Alternate Path", box)
        self.alternate.setObjectName("SWRouteAlternate")
        bl.addWidget(self.auto)
        bl.addWidget(self.alternate)
        lay.addWidget(box)
        self.info = QtWidgets.QLabel("", form)
        self.info.setObjectName("SWRouteInfo")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        lay.addStretch(1)
        self.form = form
        self.auto.clicked.connect(self.do_auto)
        self.alternate.clicked.connect(self.do_alternate)
        for b in self.type_buttons.values():
            b.toggled.connect(lambda on: on and self._kind())
        for w in (self.od, self.wall, self.radius, self.stub):
            w.valueChanged.connect(lambda *a: self._preview())
        self.doc.openTransaction("Route")
        try:
            for sel in Gui.Selection.getSelectionEx(self.doc.Name):
                for sub in (sel.SubElementNames or ("",)):
                    self._add(sel.Object, sub)
            self._kind()
            Gui.Selection.addObserver(self)
            OPEN.append(self)
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise

    def _kind(self, *a):
        self.kind = next((k for k, b in self.type_buttons.items() if b.isChecked()), "Pipe")
        self.bend_box.setTitle("Bends - Elbows" if self.kind == "Pipe" else "Bends")
        self.radius_label.setText("Elbow radius:" if self.kind == "Pipe" else
                                  "Minimum bend radius:" if self.kind == "Electrical" else "Bend radius:")
        solid = self.kind in ("Electrical", "User")
        self.wall.setVisible(not solid)
        self.wall_label.setVisible(not solid)
        if self.od_label is not None:
            self.od_label.setText("Diameter:" if solid else "Outside diameter:")
        self.wires_btn.setVisible(self.kind == "Electrical")
        self._show()
        self._preview()

    def edit_wires(self):
        """Edit Wires: the wires the cable carries (asmelec's dialog); the diameter follows them."""
        from . import asmelec
        dlg = asmelec.EditWiresDialog(self.wires, self.asm)
        self.wire_dialog = dlg
        if dlg.exec_():
            self.set_wires(dlg.result_wires())
        return dlg

    def set_wires(self, wires):
        from . import asmelec
        self.wires = [dict(w) for w in wires]
        if self.wires:
            d = asmelec.bundle_diameter(self.wires)
            self.od.setValue(d)
            self.radius.setValue(max(self.radius.value(), 2.0 * d))     # no tighter than the bundle allows
        self._preview()

    def _label(self, key):
        p = port_of(self.asm, key) if key else None
        return "%s@%s" % (p[1].Label, p[0].Label) if p else ""

    def _show(self):
        for box, key in ((self.start_box, self.start), (self.end_box, self.end)):
            box.clear()
            if key:
                box.addItem(self._label(key))
        self.via_box.clear()
        for key in self.via:
            self.via_box.addItem(self._label(key))
        ready = bool(self.start and self.end)
        self.auto_box.setVisible(ready)         # shown once both ends are picked (never a greyed button)

    def addSelection(self, doc, name, sub, pnt):
        if doc != self.doc.Name:
            return
        obj = self.doc.getObject(name)
        if obj is not None:
            from . import safe_later as _sl; _sl.later(0, lambda: (self._add(obj, sub), self._show()), self, "via_box")

    def _add(self, obj, sub):
        """A pick of a connection point's round edge (or the connection point in the tree)."""
        key = None
        ref = None
        if sub and any(c.Name == obj.Name for c in ac.components(self.asm)):
            ref = (obj, sub)                     # the observer names the component itself
        elif sub:
            try:
                ref = ac.reference(self.asm, obj, sub)
            except Exception:
                ref = None
        if ref is not None:
            comp, elem = ref
            try:
                shape = ac.element(comp, elem)
                c = _circle(shape) if shape is not None and shape.ShapeType == "Edge" else None
            except Exception:
                c = None
            if c is not None:
                for k_comp, cp, p, d in ports(self.asm):
                    if k_comp.Name == comp.Name and (p - V(c.Center)).Length < 1e-4:
                        key = port_key(k_comp, cp)
        if key is None or key in (self.start, self.end):
            return
        self.pick_port(key)

    def _is_clip(self, key):
        p = port_of(self.asm, key)
        return p is not None and p[1].RouteType == "Clip"

    def _pick_unused(self, key):
        if key in self.via:
            return
        if self._is_clip(key):                  # Route Through Clips: in the order picked
            self.via.append(key)
            self._show()
            if self.start and self.end:
                self.do_auto()
            return
        if not self.start:
            self.start = key
            port = port_of(self.asm, key)
            if port and port[1].Diameter and self.route is None:
                self.od.setValue(port[1].Diameter)
                self.stub.setValue(3.0 * port[1].Diameter)      # the stub follows the port's size
                self.radius.setValue(1.5 * port[1].Diameter)
        else:
            self.end = key
        self._show()
        if self.start and self.end:
            self.do_auto()

    def pick_port(self, key):
        """A connection point picked (the view, the tree or the test): start, end, or a clip to pass."""
        if key in (self.start, self.end):
            return
        self._pick_unused(key)

    def do_auto(self):
        if not (self.start and self.end):
            return
        self._preview()

    def do_alternate(self):
        self.order = (self.order + 1) % len(ORDERS)
        a, b = port_of(self.asm, self.start), port_of(self.asm, self.end)
        if a is not None and b is not None:
            ends = [port_of(self.asm, k) for k in [self.start] + self.via + [self.end]]
            ends = [(f[2], f[3]) for f in ends if f is not None]
            base = through_route(ends, self.stub.value(), self.order - 1)
            for _ in range(len(ORDERS)):        # the next order that gives a different path
                new = through_route(ends, self.stub.value(), self.order)
                if [tuple(p) for p in new] != [tuple(p) for p in base]:
                    break
                self.order = (self.order + 1) % len(ORDERS)
        self._preview()

    def _preview(self):
        if not (self.start and self.end):
            return
        if self.route is None:
            self.route = make_route(self.asm, self.kind, self.start, self.end, self.od.value(), self.wall.value(),
                                    self.radius.value(), self.stub.value(), self.order, self.via)
        else:
            if self.route.Kind != self.kind:
                n = len([o for o in routes(self.asm) if o.Kind == self.kind and o is not self.route]) + 1
                self.route.Label = "%s%d" % (LABELS.get(self.kind, self.kind), n)
            set_route(self.route, self.asm, self.kind, self.start, self.end, self.od.value(), self.wall.value(),
                      self.radius.value(), self.stub.value(), self.order, self.via)
        self.route.Wires = json.dumps(self.wires) if self.kind == "Electrical" else ""
        self.points = [V(p) for p in self.route.Points]
        rows = pieces(self.route)
        self.info.setText(summary(rows))

    def accept(self):
        if self.route is None:
            return False
        self.doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        self.doc.abortTransaction()
        self.doc.recompute()
        self._close()
        return True


def start_connection_point(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None or Gui.Control.activeDialog():
        return None
    p = ConnectionPointPanel(doc)
    Gui.Control.showDialog(p)
    return p


def start_route(asm, kind="Pipe"):
    if Gui.Control.activeDialog():
        return None
    p = RoutePanel(asm, kind)
    Gui.Control.showDialog(p)
    return p


def edit(route=None, asm=None):
    if route is None and asm is not None:
        rs = routes(asm)
        sel = [s.Object for s in Gui.Selection.getSelectionEx()]
        route = next((r for r in rs if r in sel), rs[-1] if rs else None)
    if route is None or Gui.Control.activeDialog():
        return None
    asm = asm or route.Document.getObject(route.AssemblyName)
    p = RoutePanel(asm, route.Kind, route)
    Gui.Control.showDialog(p)
    return p


class _Follow:
    """Moving a component a route connects marks the route for the next rebuild (an App::Link's
    Placement change does not touch the objects that depend on it)."""

    def slotChangedObject(self, obj, prop):
        if prop not in ("Placement", "LinkPlacement"):
            return
        try:
            doc = obj.Document
            for r in doc.findObjects("Part::FeaturePython"):     # the C++ type search: routes are made as this type
                if getattr(getattr(r, "Proxy", None), "Type", None) == ROUTE_TYPE and \
                        any(e.Name == obj.Name for e in (r.Ends or ())):
                    r.touch()
                    if App.GuiUp:            # a move made by the assembly's own solve: rebuild after it
                        name, dn = r.Name, doc.Name
                        QtCore.QTimer.singleShot(0, lambda: _rebuild(dn, name))
        except Exception as _fw_err:
            _fw_log("asmroute.py:927", _fw_err)


def _rebuild(dn, name):
    try:
        r = App.getDocument(dn).getObject(name)
        if r is not None and r.isTouched():
            r.recompute()
    except Exception as _fw_err:
        _fw_log("asmroute.py:936", _fw_err)


if not getattr(App, "_fw_route_follow", None):
    App._fw_route_follow = _Follow()
    App.addDocumentObserver(App._fw_route_follow)
