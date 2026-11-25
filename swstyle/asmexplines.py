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
from PySide import QtCore, QtWidgets

from . import asmcore as ac
from . import selguard

V = App.Vector
TYPE_PROP = "FwExplodeLines"


def _ax():
    from . import asmexplode
    return asmexplode


# ----------------------------------------------------------------------------- ends
def end_of(asm, comp, shape, point=None):
    """An end a line hangs on: {comp, p (point in the component), d (direction in the component, or
    None)}; a component's global placement turns it into the assembly."""
    p, d = None, None
    t = shape.ShapeType
    if t == "Vertex":
        p = shape.Point
    elif t == "Edge":
        c = shape.Curve
        if hasattr(c, "Center") and hasattr(c, "Axis"):
            p, d = V(c.Center), V(c.Axis)
        else:
            p = shape.CenterOfMass if point is None else point
            if len(shape.Vertexes) >= 2:
                d = shape.Vertexes[-1].Point - shape.Vertexes[0].Point
    elif t == "Face":
        s = shape.Surface
        if s.TypeId == "Part::GeomPlane":
            p = shape.CenterOfMass
            u, v = s.parameter(p)
            d = shape.normalAt(u, v)
        elif hasattr(s, "Axis"):
            centre = V(getattr(s, "Center", getattr(s, "Location", shape.CenterOfMass)))
            axis = V(s.Axis)
            mid = shape.CenterOfMass
            # the axis point level with the face's middle
            p = centre + axis * ((mid - centre).dot(axis) / max(axis.Length ** 2, 1e-12))
            d = axis
        else:
            p = shape.CenterOfMass
    if p is None:
        return None
    from .asmexplode import gplacement
    inv = gplacement(comp).inverse() if comp is not None else App.Placement()
    out = {"comp": comp.Name if comp is not None else "", "p": list(inv.multVec(p))}
    if d is not None and d.Length > 1e-9:
        out["d"] = list(inv.Rotation.multVec(d.normalize()))
    return out


def at(doc, end):
    """(point, direction or None) of an end in the assembly now."""
    from .asmexplode import gplacement
    comp = doc.getObject(end.get("comp") or "") if end.get("comp") else None
    plc = gplacement(comp) if comp is not None else App.Placement()
    p = plc.multVec(V(*end["p"]))
    d = plc.Rotation.multVec(V(*end["d"])) if end.get("d") else None
    return p, d


def path(a, da, b, along_xyz=False, db=None, alternate=False, reverse=False):
    ""



    if along_xyz:
        if alternate:
            pts = [a, V(a.x, a.y, b.z), V(a.x, b.y, b.z), b]
        else:
            pts = [a, V(b.x, a.y, a.z), V(b.x, b.y, a.z), b]
    elif alternate and db is not None and db.Length > 1e-9:
        d = V(db).normalize()
        knee = b + d * (a - b).dot(d)
        pts = [a, knee, b]
    elif reverse and da is not None and da.Length > 1e-9:
        d = V(da).normalize()
        along = (b - a).dot(d)
        span = max(abs(along), (b - a).Length * 0.25, 5.0)
        out1 = a - d * span if along >= 0 else a + d * span
        side = (b - a) - d * along
        pts = [a, out1, out1 + side, b] if side.Length > 1e-6 else [a, out1, b]
    elif da is not None and da.Length > 1e-9:
        d = V(da).normalize()
        off = (b - a)
        along = off.dot(d)
        knee = a + d * along
        pts = [a, knee, b]
    else:
        pts = [a, b]
    out = [pts[0]]
    for p in pts[1:]:
        if (p - out[-1]).Length > 1e-6:
            out.append(p)
    return out


# ----------------------------------------------------------------------------- jogs
def jogged(pts, jogs):
    """The route's points with its jogs in: each jog {seg, t0, t1, off [x, y, z]} steps the part of
    segment seg between t0 and t1 sideways by off. Also the plain segment of each edge."""
    by_seg = {}
    for j in jogs or []:
        by_seg.setdefault(int(j["seg"]), []).append(j)
    out, segs = [pts[0]], []
    for i in range(len(pts) - 1):
        p, q = pts[i], pts[i + 1]
        for j in sorted(by_seg.get(i, []), key=lambda j: j["t0"]):
            t0, t1 = max(0.0, min(1.0, j["t0"])), max(0.0, min(1.0, j["t1"]))
            off = V(*j["off"])
            a, b = p + (q - p) * t0, p + (q - p) * t1
            for x in (a, a + off, b + off, b):
                if (x - out[-1]).Length > 1e-6:
                    out.append(x)
                    segs.append(i)
        if (q - out[-1]).Length > 1e-6:
            out.append(q)
            segs.append(i)
    return out, segs


def line_parts(obj, n):
    parts = json.loads(obj.Lines[n])
    while len(parts) < 6:
        parts.append(False if len(parts) < 5 else [])
    return parts


def plain_points(obj, n):
    parts = line_parts(obj, n)
    a, da = at(obj.Document, parts[0])
    b, db = at(obj.Document, parts[1])
    return path(a, da, b, parts[2], db, bool(parts[3]), bool(parts[4]))


def add_jog(obj, edge, point=None, distance=10.0, normal=None, flip=False):
    """Jog Line on the edge'th edge of the sketch (EdgeN, 0-based): the jog takes the middle third of
    the segment (centred on point when given), stepping out by distance at right angles to it, in
    the plane whose normal is normal (the view direction)."""
    emap = getattr(obj.Proxy, "edge_map", None) or []
    if not (0 <= edge < len(emap)):
        obj.recompute()
        emap = getattr(obj.Proxy, "edge_map", None) or []
        if not (0 <= edge < len(emap)):
            return None
    n, seg = emap[edge]
    pts = plain_points(obj, n)
    p, q = pts[seg], pts[seg + 1]
    d = q - p
    L = d.Length
    if L < 1e-6:
        return None
    t = 0.5 if point is None else max(0.2, min(0.8, (V(point) - p).dot(d) / (L * L)))
    half = 1.0 / 6.0
    t0, t1 = max(0.02, t - half), min(0.98, t + half)
    u = V(d).normalize()
    nrm = V(normal) if normal is not None and V(normal).Length > 1e-9 else V(0, 0, 1)
    side = u.cross(nrm)
    if side.Length < 1e-6:
        side = u.cross(V(1, 0, 0)) if abs(u.x) < 0.9 else u.cross(V(0, 1, 0))
    side.normalize()
    if flip:
        side = side * -1
    off = side * float(distance)
    parts = line_parts(obj, n)
    parts[5] = list(parts[5] or []) + [{"seg": seg, "t0": t0, "t1": t1, "off": [off.x, off.y, off.z]}]
    lines = list(obj.Lines)
    lines[n] = json.dumps(parts)
    obj.Lines = lines
    obj.recompute()
    return n, seg


def undo_jog(obj):
    """The last jog put in (on any line) comes out."""
    for n in range(len(obj.Lines) - 1, -1, -1):
        parts = line_parts(obj, n)
        if parts[5]:
            parts[5] = list(parts[5])[:-1]
            lines = list(obj.Lines)
            lines[n] = json.dumps(parts)
            obj.Lines = lines
            obj.recompute()
            return True
    return False


def jog_count(obj):
    return sum(len(line_parts(obj, n)[5] or []) for n in range(len(obj.Lines)))


def set_last_jog(obj, distance=None, flip=None):
    """Jog distance / Flip Jog on the last jog."""
    for n in range(len(obj.Lines) - 1, -1, -1):
        parts = line_parts(obj, n)
        if parts[5]:
            j = dict(parts[5][-1])
            off = V(*j["off"])
            if off.Length < 1e-9:
                return False
            if distance is not None:
                off = V(off).normalize() * float(distance)
            if flip:
                off = off * -1
            j["off"] = [off.x, off.y, off.z]
            parts[5] = list(parts[5])[:-1] + [j]
            lines = list(obj.Lines)
            lines[n] = json.dumps(parts)
            obj.Lines = lines
            obj.recompute()
            return True
    return False


# ----------------------------------------------------------------------------- the sketch object
class ExplodeLines:
    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty("App::PropertyString", TYPE_PROP, "FreeCAD", "Explode line sketch")
        obj.setEditorMode(TYPE_PROP, 2)
        obj.addProperty("App::PropertyStringList", "Lines", "Explode Lines", "Each line: json [end, end, along XYZ]")
        # names, not links: a link would take the assembly out of the document's root objects
        obj.addProperty("App::PropertyString", "ViewName", "Explode Lines", "The exploded view it belongs to")
        obj.addProperty("App::PropertyString", "AssemblyName", "Explode Lines", "The assembly")

    def execute(self, obj):
        import Part
        doc = obj.Document
        wires = []
        self.edge_map = []          # per edge of the shape: (line, segment of the plain route)
        for n, text in enumerate(obj.Lines):
            try:
                parts = json.loads(text)
                e1, e2, xyz = parts[:3]
                alt = bool(parts[3]) if len(parts) > 3 else False
                rev = bool(parts[4]) if len(parts) > 4 else False
                jogs = parts[5] if len(parts) > 5 else []
                a, da = at(doc, e1)
                b, db = at(doc, e2)
                pts = path(a, da, b, xyz, db, alt, rev)
                pts, segs = jogged(pts, jogs)
                if len(pts) >= 2:
                    wires.append(Part.makePolygon(pts))
                    self.edge_map += [(n, sg) for sg in segs]
            except Exception as error:
                App.Console.PrintLog("FreeCAD: explode line: %s\n" % error)
        obj.Shape = Part.makeCompound(wires) if wires else Part.Shape()

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderExplodeLines:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return "Sketcher_Sketch"

    def doubleClicked(self, vobj):
        return edit(vobj.Object)

    def setupContextMenu(self, vobj, menu):
        a = menu.addAction("Edit Sketch")
        a.triggered.connect(lambda: edit(vobj.Object))

    def dumps(self):
        return None

    def loads(self, state):
        return None


def view_of(obj):
    return obj.Document.getObject(obj.ViewName) if obj.ViewName else None


def assembly(obj):
    return obj.Document.getObject(obj.AssemblyName) if obj.AssemblyName else None


def sketches(asm, view=None):
    out = []
    for o in asm.Document.Objects:
        if hasattr(o, TYPE_PROP) and o.AssemblyName == asm.Name and (view is None or o.ViewName == view.Name):
            out.append(o)
    return out


def _look(obj):
    vo = getattr(obj, "ViewObject", None)
    if vo is None:
        return
    for prop, value in (("DrawStyle", "Dashdot"), ("LineWidth", 1.5), ("LineColor", (0.1, 0.1, 0.1)),
                        ("PointSize", 1.0)):
        try:
            setattr(vo, prop, value)
        except Exception as _fw_err:
            _fw_log("asmexplines.py:343", _fw_err)


def make(asm, view):
    doc = asm.Document
    obj = doc.addObject("Part::FeaturePython", "ExplodeLines")
    ExplodeLines(obj)
    if App.GuiUp and obj.ViewObject is not None:
        ViewProviderExplodeLines(obj.ViewObject)
        _look(obj)
    obj.ViewName = view.Name
    obj.AssemblyName = asm.Name
    taken = {o.Label for o in doc.Objects}
    n = 1
    while "3DExplode%d" % n in taken:
        n += 1
    obj.Label = "3DExplode%d" % n
    return obj


def add_line(obj, e1, e2, along_xyz=False, alternate=False, reverse=False):
    obj.Lines = list(obj.Lines) + [json.dumps([e1, e2, bool(along_xyz), bool(alternate), bool(reverse)])]
    obj.recompute()
    return obj


def smart_lines(asm, view, obj=None):
    """A line from each moved component back to where it sat collapsed."""
    ax = _ax()
    if view is None or not ax.is_exploded(view):
        return None
    base = dict(zip(view.FwBaseNames, view.FwBasePlacements))
    doc = asm.Document
    obj = obj or make(asm, view)
    lines = list(obj.Lines)
    for comp in ac.components(asm):
        before = base.get(comp.Name)
        if before is None:
            continue
        now = ax.gplacement(comp)
        if (now.Base - ax._frame(comp).multiply(before).Base).Length < 1e-6:
            continue
        try:
            centre = ax.gcentre(comp)
        except Exception:
            continue
        move = now.Base - ax._frame(comp).multiply(before).Base
        start = centre - move
        e1 = {"comp": comp.Name, "p": list(now.inverse().multVec(centre))}
        e2 = {"comp": "", "p": list(start)}
        lines.append(json.dumps([e1, e2, False]))
    obj.Lines = lines
    obj.recompute()
    doc.recompute()
    return obj


def show_for(asm, view, on):
    for o in sketches(asm, view):
        if o.ViewObject is not None:
            o.ViewObject.Visibility = bool(on)
        if on:
            try:
                o.recompute()
            except Exception as _fw_err:
                _fw_log("asmexplines.py:408", _fw_err)


def install():
    """The lines show only while their exploded view is exploded."""
    ax = _ax()
    if getattr(ax, "_fw_lines", False):
        return
    explode0, collapse0 = ax.explode, ax.collapse

    def explode(asm, view):
        r = explode0(asm, view)
        _patch_view_menu()
        try:
            show_for(asm, view, True)
            for o in sketches(asm, view):
                o.purgeTouched()
        except Exception as _fw_err:
            _fw_log("asmexplines.py:426", _fw_err)
        return r

    def collapse(asm, view):
        r = collapse0(asm, view)
        try:
            show_for(asm, view, False)
        except Exception as _fw_err:
            _fw_log("asmexplines.py:434", _fw_err)
        return r
    ax.explode, ax.collapse = explode, collapse
    ax._fw_lines = True
    _patch_view_menu()


def _patch_view_menu():
    ""

    ax = _ax()
    try:
        cls = ax._cv().ViewProviderExplodedView
    except Exception:
        return False
    if getattr(cls, "_fw_smart", False):
        return True
    menu0 = getattr(cls, "setupContextMenu", None)

    def setupContextMenu(self, vobj, menu):
        if menu0 is not None:
            try:
                menu0(self, vobj, menu)
            except Exception as _fw_err:
                _fw_log("asmexplines.py:458", _fw_err)
        view = vobj.Object
        asm = ac.assembly_of(view.Document)
        a = menu.addAction("Smart Explode Lines")
        a.setEnabled(asm is not None and ax.is_exploded(view))
        a.triggered.connect(lambda: _in_transaction(asm, "Smart Explode Lines", lambda: smart_lines(asm, view)))
    cls.setupContextMenu = setupContextMenu
    cls._fw_smart = True
    return True


def _in_transaction(asm, name, run):
    doc = asm.Document
    doc.openTransaction(name)
    try:
        r = run()
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()
    return r


# ----------------------------------------------------------------------------- Route Line PM
class RouteLinePanel:
    """Route Line: Items To Connect (two picks make a line), Options: Along XYZ; Lines with
    Undo Last Line; Smart Explode Lines."""

    def __init__(self, asm, obj, new=False):
        from . import asmpm
        self.asm, self.obj, self.doc, self.new = asm, obj, asm.Document, new
        self.picks = []
        box, lay = asmpm._box("Items To Connect", "Route Line", "ASSEMBLIES_EXPLODE_LINE_SKETCH")
        self.items = QtWidgets.QListWidget()
        self.items.setObjectName("FW_RouteItems")
        self.items.setStyleSheet(asmpm.PICK_STYLE)
        self.items.setFixedHeight(asmpm._rows(self.items, 3))
        lay.addWidget(self.items)
        self.reverse = QtWidgets.QPushButton("Reverse")
        self.reverse.setObjectName("FW_RouteReverse")
        self.reverse.setCheckable(True)
        self.reverse.setToolTip("Reverse the direction of the route line")
        lay.addWidget(self.reverse, 0, QtCore.Qt.AlignLeft)
        obox, olay = asmpm._box("Options")
        self.alternate = QtWidgets.QCheckBox("Alternate Path")
        self.alternate.setObjectName("FW_RouteAlternate")
        self.alternate.setToolTip("Route the line the other way round")
        olay.addWidget(self.alternate)
        self.xyz = QtWidgets.QCheckBox("Along XYZ")
        self.xyz.setObjectName("FW_RouteAlongXYZ")
        olay.addWidget(self.xyz)
        lbox, llay = asmpm._box("Lines")
        self.lines = QtWidgets.QListWidget()
        self.lines.setObjectName("FW_RouteLines")
        self.lines.setFixedHeight(asmpm._rows(self.lines, 4))
        llay.addWidget(self.lines)
        row = QtWidgets.QHBoxLayout()
        self.undo_button = QtWidgets.QPushButton("Undo Last Line")
        self.undo_button.setObjectName("FW_RouteUndoLine")
        self.undo_button.clicked.connect(self.undo_line)
        row.addWidget(self.undo_button)
        self.smart = QtWidgets.QPushButton("Smart Explode Lines")
        self.smart.setObjectName("FW_RouteSmart")
        self.smart.clicked.connect(self.smart_lines)
        row.addWidget(self.smart)
        llay.addLayout(row)
        jrow = QtWidgets.QHBoxLayout()
        self.jog = QtWidgets.QPushButton("Jog Line")
        self.jog.setObjectName("FW_RouteJog")
        self.jog.setCheckable(True)
        self.jog.setToolTip("Click a segment of a line to put a jog in it")
        jrow.addWidget(self.jog)
        self.jog_distance = QtWidgets.QDoubleSpinBox()
        self.jog_distance.setObjectName("FW_RouteJogDistance")
        self.jog_distance.setRange(0.1, 10000.0)
        self.jog_distance.setDecimals(2)
        self.jog_distance.setSuffix(" mm")
        self.jog_distance.setValue(10.0)
        self.jog_distance.setToolTip("How far the jog steps out of the line")
        self.jog_distance.valueChanged.connect(lambda v: set_last_jog(self.obj, distance=v) if jog_count(self.obj) else None)
        jrow.addWidget(self.jog_distance)
        self.jog_flip = QtWidgets.QPushButton("Flip Jog")
        self.jog_flip.setObjectName("FW_RouteJogFlip")
        self.jog_flip.clicked.connect(lambda *_: (set_last_jog(self.obj, flip=True), self._fill()))
        jrow.addWidget(self.jog_flip)
        self.undo_jog = QtWidgets.QPushButton("Undo Last Jog")
        self.undo_jog.setObjectName("FW_RouteUndoJog")
        self.undo_jog.clicked.connect(lambda *_: (undo_jog(self.obj), self._fill()))
        jrow.addWidget(self.undo_jog)
        llay.addLayout(jrow)
        self.form = [box, obox, lbox]
        if not new:                 # a new sketch's transaction is open already (start)
            self.doc.openTransaction("Edit " + obj.Label)
        self._fill()
        Gui.Selection.addObserver(self, 0)

    def _fill(self):
        self.lines.clear()
        for i, _t in enumerate(self.obj.Lines):
            self.lines.addItem("Route Line%d" % (i + 1))
        # no greyed controls: Undo and the jog buttons show once there is something for them
        self.undo_button.setVisible(bool(self.obj.Lines))
        if hasattr(self, "jog"):
            self.jog.setVisible(bool(self.obj.Lines))
            self.jog_distance.setVisible(bool(self.obj.Lines))
            has = jog_count(self.obj) > 0
            self.jog_flip.setVisible(has)
            self.undo_jog.setVisible(has)

    def addSelection(self, doc, obj, sub, pnt):
        point = V(*pnt) if pnt else None
        QtCore.QTimer.singleShot(0, lambda: selguard.quiet(lambda: self.pick(self.doc.getObject(obj), sub, point)))

    def removeSelection(self, *a):
        pass

    def clearSelection(self, *a):
        pass

    def setPreselection(self, *a):
        pass

    def pick(self, root, sub, point=None):
        if root is None or not sub:
            return False
        if getattr(self, "jog", None) is not None and self.jog.isChecked():
            return self.jog_pick(root, sub, point)
        ref = ac.reference(self.asm, root, sub)
        if ref is None:
            return False
        shape = ac.element(*ref)
        if shape is None:
            return False
        end = end_of(self.asm, ref[0], shape, point)
        if end is None:
            return False
        self.picks.append(end)
        self.items.addItem("%s@%s" % (ref[1].split(".")[-1], ref[0].Label))
        if len(self.picks) == 2:
            add_line(self.obj, self.picks[0], self.picks[1], self.xyz.isChecked(),
                     self.alternate.isChecked(), self.reverse.isChecked())
            self.obj.recompute()
            self.picks = []
            self.items.clear()
            self._fill()
        return True

    def jog_pick(self, root, sub, point=None):
        """Jog Line: a click on one of this sketch's line segments puts a jog in it."""
        name = sub.split(".")[-1]
        if not name.startswith("Edge"):
            return False
        if root is not self.obj and self.obj.Name not in sub.split(".")[:-1]:
            return False
        normal = None
        try:
            normal = Gui.activeView().getViewDirection()
        except Exception as _fw_err:
            _fw_log("asmexplines.py:614", _fw_err)
        done = add_jog(self.obj, int(name[4:]) - 1, point, self.jog_distance.value(), normal)
        self._fill()
        return done is not None

    def undo_line(self):
        if self.obj.Lines:
            self.obj.Lines = list(self.obj.Lines)[:-1]
            self.obj.recompute()
            self._fill()

    def smart_lines(self):
        smart_lines(self.asm, view_of(self.obj), self.obj)
        self._fill()

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmexplines.py:633", _fw_err)

    def accept(self):
        self._close()
        if self.new and not self.obj.Lines:
            self.doc.abortTransaction()
        else:
            self.doc.commitTransaction()
        Gui.Control.closeDialog()
        self.doc.recompute()
        return True

    def reject(self):
        self._close()
        self.doc.abortTransaction()
        Gui.Control.closeDialog()
        self.doc.recompute()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


OPEN = []


def _show(panel):
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    OPEN[:] = [panel]
    Gui.Control.showDialog(panel)
    return panel


def start(asm):
    """Insert > Explode Line Sketch."""
    view = _ax().exploded_view(asm)
    if view is None:
        return None
    asm.Document.openTransaction("Explode Line Sketch")
    try:
        obj = make(asm, view)
        return _show(RouteLinePanel(asm, obj, new=True))
    except BaseException:
        try:
            asm.Document.abortTransaction()
        except Exception:
            pass
        raise


def edit(obj):
    asm = assembly(obj)
    if asm is None:
        return False
    _show(RouteLinePanel(asm, obj))
    return True
