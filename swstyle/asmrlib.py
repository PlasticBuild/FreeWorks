# SPDX-License-Identifier: LGPL-2.1-or-later
""













import math
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import asmcore as ac
from . import asmroute as ar

V = App.Vector
IN = 25.4

# NPS: (OD, schedule 40 wall, 90 LR centre to end, 45 centre to end, tee centre to end, flange OD, flange thickness)
PIPE = {
    "1/2": (21.3, 2.77, 38.1, 15.9, 25.4, 88.9, 11.2),
    "3/4": (26.7, 2.87, 28.6, 11.1, 28.6, 98.6, 12.7),
    "1": (33.4, 3.38, 38.1, 22.2, 38.1, 108.0, 14.2),
    "1-1/4": (42.2, 3.56, 47.6, 25.4, 47.6, 117.3, 15.7),
    "1-1/2": (48.3, 3.68, 57.2, 28.6, 57.2, 127.0, 17.5),
    "2": (60.3, 3.91, 76.2, 34.9, 63.5, 152.4, 19.1),
    "3": (88.9, 5.49, 114.3, 50.8, 85.7, 190.5, 23.9),
    "4": (114.3, 6.02, 152.4, 63.5, 104.8, 228.6, 23.9),
}
TUBE = {"6 x 1": (6.0, 1.0), "8 x 1": (8.0, 1.0), "10 x 1": (10.0, 1.0), "12 x 1.5": (12.0, 1.5),
        "16 x 1.5": (16.0, 1.5), "20 x 2": (20.0, 2.0)}
PINS = (2, 3, 4, 6, 8, 12)
CLIPS = {"P-clip 6": 6.0, "P-clip 10": 10.0, "P-clip 16": 16.0, "P-clip 25": 25.0}

FITTINGS = {
    "Piping": ("90 Elbow", "45 Elbow", "Tee", "Reducer", "Cap", "Slip-on Flange", "Coupling"),
    "Tubing": ("Straight Union", "Elbow Union", "Tee Union"),
    "Electrical": ("Connector", "P-Clip"),
}


def sizes(family, kind):
    if family == "Piping":
        if kind == "Reducer":
            names = list(PIPE)
            return ["%s x %s" % (a, b) for i, a in enumerate(names) for b in names[:i]]
        return list(PIPE)
    if family == "Tubing":
        return list(TUBE)
    if kind == "Connector":
        return ["%d pin" % n for n in PINS]
    return list(CLIPS)


def library_folder():
    d = os.path.join(App.getUserAppDataDir(), "FreeWorks", "Routing Library")
    os.makedirs(d, exist_ok=True)
    return d


def file_name(family, kind, size):
    safe = "".join(ch if ch.isalnum() else "-" for ch in "%s %s" % (kind, size)).strip("-")
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe


# ------------------------------------------------------------------ the shapes
def _tube(p, d, r_out, r_in, length):
    s = Part.makeCylinder(r_out, length, p, d)
    if r_in > 0:
        s = s.cut(Part.makeCylinder(r_in, length, p, d))
    return s


def _elbow(r_out, r_in, radius, angle):
    """Bend from the origin along +X, turning toward +Y round (0, radius, 0)."""
    path = Part.Wire(Part.makeCircle(radius, V(0, radius, 0), V(0, 0, 1), -90, -90 + angle))
    e = path.Edges[0]
    p0, t0 = e.valueAt(e.FirstParameter), e.tangentAt(e.FirstParameter)
    outer = path.makePipeShell([Part.Wire(Part.makeCircle(r_out, p0, t0))], True, True)
    if r_in > 0:
        outer = outer.cut(path.makePipeShell([Part.Wire(Part.makeCircle(r_in, p0, t0))], True, True))
    end = e.valueAt(e.LastParameter)
    return outer, [(V(p0), -V(t0)), (V(end), V(e.tangentAt(e.LastParameter)))]


def shape(family, kind, size):
    """(solid, [(port centre, outward direction, port diameter, route type)], properties)."""
    if family == "Piping":
        if kind == "Reducer":
            big, small = [x.strip() for x in size.split("x")]
            (D, w), (d, w2) = PIPE[big][:2], PIPE[small][:2]
            L = 2.0 * max(PIPE[big][4], 25.0)
            outer = Part.makeCone(D / 2, d / 2, L, V(0, 0, 0), V(1, 0, 0))
            inner = Part.makeCone(D / 2 - w, d / 2 - w2, L, V(0, 0, 0), V(1, 0, 0))
            return outer.cut(inner), [(V(0, 0, 0), V(-1, 0, 0), D, "Pipe"), (V(L, 0, 0), V(1, 0, 0), d, "Pipe")], \
                {"NPS": size, "OD": D, "Wall": w}
        od, wall, a90, a45, tee, fod, ft = PIPE[size]
        ro, ri = od / 2, od / 2 - wall
        if kind in ("90 Elbow", "45 Elbow"):
            ang = 90.0 if kind == "90 Elbow" else 45.0
            radius = a90                        # long radius: both bend on 1.5 x NPS
            s, ends = _elbow(ro, ri, radius, ang)
            return s, [(p, d, od, "Pipe") for p, d in ends], {"NPS": size, "OD": od, "Wall": wall, "Radius": radius}
        if kind == "Tee":
            run = _tube(V(-tee, 0, 0), V(1, 0, 0), ro, 0, 2 * tee)
            br = _tube(V(0, 0, 0), V(0, 1, 0), ro, 0, tee)
            s = run.fuse(br)
            s = s.cut(_tube(V(-tee, 0, 0), V(1, 0, 0), ri, 0, 2 * tee)).cut(_tube(V(0, 0, 0), V(0, 1, 0), ri, 0, tee))
            s = s.removeSplitter()
            return s, [(V(-tee, 0, 0), V(-1, 0, 0), od, "Pipe"), (V(tee, 0, 0), V(1, 0, 0), od, "Pipe"),
                       (V(0, tee, 0), V(0, 1, 0), od, "Pipe")], {"NPS": size, "OD": od, "Wall": wall}
        if kind == "Cap":
            L = max(od * 0.6, 20.0)
            s = Part.makeCylinder(ro, L, V(0, 0, 0), V(1, 0, 0)).cut(Part.makeCylinder(ri, L - wall, V(0, 0, 0), V(1, 0, 0)))
            return s, [(V(0, 0, 0), V(-1, 0, 0), od, "Pipe")], {"NPS": size, "OD": od, "Wall": wall}
        if kind == "Slip-on Flange":
            s = Part.makeCylinder(fod / 2, ft, V(0, 0, 0), V(1, 0, 0)).fuse(
                Part.makeCylinder(ro + wall * 2, ft * 1.6, V(0, 0, 0), V(1, 0, 0)))
            s = s.cut(Part.makeCylinder(ro, ft * 1.6, V(0, 0, 0), V(1, 0, 0)))
            pcd = (fod + od) / 2 * 0.95
            for i in range(4):
                a = math.radians(45 + 90 * i)
                s = s.cut(Part.makeCylinder(max(4.0, ft * 0.4), ft, V(0, pcd / 2 * math.cos(a), pcd / 2 * math.sin(a)),
                                            V(1, 0, 0)))
            s = s.removeSplitter()
            return s, [(V(ft * 1.6, 0, 0), V(1, 0, 0), od, "Pipe"), (V(0, 0, 0), V(-1, 0, 0), fod, "Pipe")], \
                {"NPS": size, "OD": od, "FlangeOD": fod}
        if kind == "Coupling":
            L = max(od, 30.0)
            s = _tube(V(0, 0, 0), V(1, 0, 0), ro + wall, ro, L)
            return s, [(V(0, 0, 0), V(-1, 0, 0), od, "Pipe"), (V(L, 0, 0), V(1, 0, 0), od, "Pipe")], \
                {"NPS": size, "OD": od}
    if family == "Tubing":
        od, wall = TUBE[size]
        ro, ri, nut = od / 2, od / 2 - wall, od * 0.9 + 3
        if kind == "Straight Union":
            L = od * 3 + 10
            s = _tube(V(0, 0, 0), V(1, 0, 0), nut, ri, L)
            return s, [(V(0, 0, 0), V(-1, 0, 0), od, "Tube"), (V(L, 0, 0), V(1, 0, 0), od, "Tube")], {"OD": od, "Wall": wall}
        if kind == "Elbow Union":
            a = od * 1.6 + 8
            body = Part.makeBox(nut * 2, nut * 2, nut * 2, V(-nut, -nut, -nut))
            arm1 = Part.makeCylinder(nut, a, V(0, 0, 0), V(-1, 0, 0))
            arm2 = Part.makeCylinder(nut, a, V(0, 0, 0), V(0, 1, 0))
            s = body.fuse(arm1).fuse(arm2)
            s = s.cut(Part.makeCylinder(ri, a, V(0, 0, 0), V(-1, 0, 0))).cut(Part.makeCylinder(ri, a, V(0, 0, 0), V(0, 1, 0)))
            s = s.removeSplitter()
            return s, [(V(-a, 0, 0), V(-1, 0, 0), od, "Tube"), (V(0, a, 0), V(0, 1, 0), od, "Tube")], {"OD": od, "Wall": wall}
        if kind == "Tee Union":
            a = od * 1.6 + 8
            body = Part.makeBox(nut * 2, nut * 2, nut * 2, V(-nut, -nut, -nut))
            s = body
            ports = []
            for d in (V(-1, 0, 0), V(1, 0, 0), V(0, 1, 0)):
                s = s.fuse(Part.makeCylinder(nut, a, V(0, 0, 0), d))
                ports.append((d * a, d, od, "Tube"))
            for d in (V(-1, 0, 0), V(1, 0, 0), V(0, 1, 0)):
                s = s.cut(Part.makeCylinder(ri, a, V(0, 0, 0), d))
            return s.removeSplitter(), ports, {"OD": od, "Wall": wall}
    if family == "Electrical":
        if kind == "Connector":
            n = int(size.split()[0])
            cols = min(n, 6)
            rows = int(math.ceil(n / float(cols)))
            w, h, depth = cols * 2.54 + 6, rows * 2.54 + 6, 14.0
            s = Part.makeBox(depth, w, h, V(0, -w / 2, -h / 2))
            exit_d = max(4.0, math.sqrt(n) * 2.2)
            boot = Part.makeCylinder(exit_d / 2 + 1.5, 8.0, V(depth, 0, 0), V(1, 0, 0))
            s = s.fuse(boot).cut(Part.makeCylinder(exit_d / 2, 8.0, V(depth, 0, 0), V(1, 0, 0)))
            for i in range(n):
                y = -((cols - 1) * 2.54) / 2 + (i % cols) * 2.54
                z = -((rows - 1) * 2.54) / 2 + (i // cols) * 2.54
                s = s.cut(Part.makeCylinder(0.6, 6.0, V(0, y, z), V(1, 0, 0)))
            return s.removeSplitter(), [(V(depth + 8.0, 0, 0), V(1, 0, 0), exit_d, "Electrical")], {"Pins": n}
        if kind == "P-Clip":
            d = CLIPS[size]
            band, t = max(8.0, d * 0.5), max(1.2, d * 0.08)
            ring = _tube(V(-band / 2, 0, 0), V(1, 0, 0), d / 2 + t, d / 2, band)
            tab = Part.makeBox(band, t, d * 0.8 + 6, V(-band / 2, -d / 2 - t, -(d * 0.8 + 6)))
            tab = tab.cut(Part.makeCylinder(2.0, t, V(0, -d / 2 - t, -(d * 0.8 + 6) / 2 - d / 4), V(0, 1, 0)))
            return ring.fuse(tab).removeSplitter(), [(V(-band / 2, 0, 0), V(-1, 0, 0), d, "Clip")], {"Bore": d}
    raise ValueError("no such fitting: %s %s %s" % (family, kind, size))


def _edge_at(shp, centre, diameter):
    """The round edge at a port: centred on it, of the port's diameter (or the nearest round one)."""
    best, err = None, None
    for i, e in enumerate(shp.Edges):
        c = ar._circle(e)
        if c is None or (V(c.Center) - centre).Length > 1e-3:
            continue
        de = abs(2 * c.Radius - diameter)
        if best is None or de < err:
            best, err = "Edge%d" % (i + 1), de
    return best


def make_part(family, kind, size, folder=None):
    """The fitting's part document (made and saved the first time)."""
    folder = folder or library_folder()
    name = file_name(family, kind, size)
    path = os.path.join(folder, name + ".FCStd")
    for d in App.listDocuments().values():
        if d.FileName and os.path.normcase(d.FileName) == os.path.normcase(path):
            return d
    if os.path.isfile(path):
        return App.openDocument(path)
    shp, ports, props = shape(family, kind, size)
    doc = App.newDocument(name)
    doc.Label = name
    obj = doc.addObject("Part::Feature", "Fitting")
    obj.Label = "%s %s" % (kind, size)
    obj.Shape = shp
    for k, label in (("FwRoutingFamily", family), ("FwRoutingKind", kind), ("FwRoutingSize", size)):
        obj.addProperty("App::PropertyString", k, "Routing Library", label)
        setattr(obj, k, label)
    for k, v in props.items():
        obj.addProperty("App::PropertyString", "Fw" + k, "Routing Library", k)
        setattr(obj, "Fw" + k, str(v))
    doc.recompute()
    for i, (p, d, dia, rtype) in enumerate(ports):
        sub = _edge_at(obj.Shape, p, dia)
        if sub is None:
            continue
        cp = ar.make_connection_point(obj, sub, rtype, "P%d" % (i + 1))
        cp.Diameter = dia
        f = ar.frame(obj, sub)
        if f is not None and f[1].dot(d) < 0:
            cp.Flip = True
        cp.recompute()
    doc.recompute()
    doc.saveAs(path)
    return doc


def free_ports(asm):
    """Connection points no route or fitting uses yet: [(key, label)]."""
    used = set()
    for r in ar.routes(asm):
        used.update([r.StartPort, r.EndPort] + list(r.Via or ()))
    out = []
    pts = ar.ports(asm)
    for comp, cp, p, d in pts:
        key = ar.port_key(comp, cp)
        if key in used:
            continue
        if any((p - q).Length < 1e-3 and c2.Name != comp.Name for c2, _cp2, q, _d2 in pts):
            continue                            # another part's port already sits on it
        out.append((key, "%s@%s" % (cp.Label, comp.Label)))
    return out


def _rotation(a, b):
    """The rotation taking direction a onto direction b."""
    return App.Rotation(V(a), V(b))


def insert_fitting(asm, family, kind, size, attach=None, folder=None):
    """Inserts the fitting; attach (a port key) puts its first port onto that one, face to face."""
    doc = make_part(family, kind, size, folder)
    fit = doc.getObject("Fitting")
    pl = App.Placement()
    if attach:
        target = ar.port_of(asm, attach)
        cps = ar.connection_points(doc)
        if target is not None and cps:
            cp = cps[0]
            p0, d0 = V(cp.Position), V(cp.Direction)
            rot = _rotation(d0, -V(target[3]))
            pl = App.Placement(V(target[2]) - rot.multVec(p0), rot)
    if App.GuiUp:
        Gui.setActiveDocument(asm.Document.Name)
    App.setActiveDocument(asm.Document.Name)
    comp = ac.insert(asm, fit, pl)
    asm.Document.recompute()
    return comp


class FittingPanel(ar._Panel):
    ""


    def __init__(self, asm, family="Piping"):
        self.asm, self.doc = asm, asm.Document
        self.result = None
        form = QtWidgets.QWidget()
        form.setObjectName("SWRoutingFitting")
        form.setWindowTitle("Add Fitting")
        form.setProperty("swstyle_pm_title", "Add Fitting")
        lay = QtWidgets.QVBoxLayout(form)
        box = QtWidgets.QGroupBox("Fitting", form)
        fl = QtWidgets.QFormLayout(box)
        self.family = QtWidgets.QComboBox(box)
        self.family.setObjectName("SWFittingFamily")
        self.family.addItems(list(FITTINGS))
        self.kind = QtWidgets.QComboBox(box)
        self.kind.setObjectName("SWFittingType")
        self.size = QtWidgets.QComboBox(box)
        self.size.setObjectName("SWFittingSize")
        fl.addRow("Library:", self.family)
        fl.addRow("Type:", self.kind)
        fl.addRow("Size:", self.size)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Attach to", form)
        bl = QtWidgets.QVBoxLayout(box)
        self.attach = QtWidgets.QListWidget(box)
        self.attach.setObjectName("SWFittingAttach")
        self.attach.setMaximumHeight(90)
        bl.addWidget(self.attach)
        lay.addWidget(box)
        lay.addStretch(1)
        self.form = form
        self.family.currentTextChanged.connect(self._family)
        self.kind.currentTextChanged.connect(self._kind)
        self.family.setCurrentText(family)
        self._family()
        self._ports()
        ar.OPEN.append(self)

    def _family(self, *a):
        self.kind.blockSignals(True)
        self.kind.clear()
        self.kind.addItems(list(FITTINGS[self.family.currentText()]))
        self.kind.blockSignals(False)
        self._kind()

    def _kind(self, *a):
        self.size.clear()
        self.size.addItems(sizes(self.family.currentText(), self.kind.currentText()))

    def _ports(self):
        self.attach.clear()
        it = QtWidgets.QListWidgetItem("(none: at the origin)")
        it.setData(QtCore.Qt.UserRole, "")
        self.attach.addItem(it)
        for key, label in free_ports(self.asm):
            it = QtWidgets.QListWidgetItem(label)
            it.setData(QtCore.Qt.UserRole, key)
            self.attach.addItem(it)
        self.attach.setCurrentRow(0)

    def accept(self, folder=None):
        it = self.attach.currentItem()
        key = it.data(QtCore.Qt.UserRole) if it is not None else ""
        self.doc.openTransaction("Add Fitting")
        try:
            self.result = insert_fitting(self.asm, self.family.currentText(), self.kind.currentText(),
                                         self.size.currentText(), key or None, folder)
        finally:
            self.doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        self._close()
        return True


def start_fitting(asm, family="Piping"):
    if Gui.Control.activeDialog():
        return None
    p = FittingPanel(asm, family)
    Gui.Control.showDialog(p)
    return p
