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
import os

import FreeCAD as App
from FreeCAD import Vector as V

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

FLUIDS = {   # name: (density kg/m3, dynamic viscosity Pa s)
    "Water": (998.2, 1.002e-3), "Air": (1.204, 1.81e-5), "Oil (SAE 30)": (891.0, 0.29),
    "Ethylene glycol": (1113.0, 1.61e-2), "Hydrogen": (0.0838, 8.8e-6), "Nitrogen": (1.165, 1.76e-5),
}
INLET_KINDS = ("Volume Flow Rate", "Mass Flow Rate", "Velocity")
UNITS = ("SI (m-kg-s)", "IPS (in-lb-s)")
STEPS = ("Welcome", "Check Geometry", "Fluid", "Flow Inlet", "Flow Outlet", "Solve", "Results")
GROUP = "FloXpressResults"


# ---------------------------------------------------------------- geometry
def model_shape(doc):
    """The solids of the part or assembly, fused."""
    import Part
    from . import asmcore as ac
    asm = ac.assembly_of(doc)
    if asm is not None:
        solids = []
        for c in ac.components(asm):
            s = getattr(c, "Shape", None)
            if s is not None and not s.isNull():
                solids += s.Solids
    else:
        solids = []
        for o in doc.Objects:
            s = getattr(o, "Shape", None)
            if s is None or s.isNull() or not s.Solids or o.getParentGeoFeatureGroup() is not None and \
                    o.TypeId != "PartDesign::Body":
                continue
            if o.TypeId == "PartDesign::Body" or not [p for p in o.InList if hasattr(p, "Shape")]:
                solids += s.Solids
    if not solids:
        return None
    shape = solids[0]
    if len(solids) > 1:
        shape = solids[0].fuse(solids[1:])
        try:
            shape = shape.removeSplitter()
        except Exception as _fw_err:
            _fw_log("floxpress.py:79", _fw_err)
    return shape


def fluid_volume(shape):
    ""

    import Part
    if shape is None:
        return None
    best = None
    for solid in shape.Solids:
        outer = solid.OuterShell
        for sh in solid.Shells:
            if sh.isSame(outer):
                continue
            try:
                cav = Part.Solid(sh)
                if cav.Volume < 0:
                    cav.reverse()
                if best is None or abs(cav.Volume) > abs(best.Volume):
                    best = cav
            except Exception:
                continue
    return best


def cavity_faces(cavity, model_faces):
    """The cavity faces lying on the model faces picked (the inner side of a lid): flat, and
    their centre on the picked face."""
    import Part
    out = []
    for f in model_faces:
        for cf in cavity.Faces:
            if cf in out or cf.Surface.TypeId != "Part::GeomPlane":
                continue
            try:
                if f.distToShape(Part.Vertex(cf.CenterOfMass))[0] < 1e-6:
                    out.append(cf)
            except Exception:
                continue
    return out


def _centre(faces):
    a = sum(f.Area for f in faces)
    c = V()
    for f in faces:
        c += f.CenterOfMass * f.Area
    return c * (1.0 / a), a


# ---------------------------------------------------------------- the estimate
def solve(study):
    """study: {"cavity", "inlet" (cavity faces), "outlet", "fluid", "inlet_kind", "inlet_value"
    (SI: m3/s, kg/s or m/s), "outlet_pressure" (Pa), "trajectories"}. Returns the results."""
    cavity = study["cavity"]
    rho, mu = FLUIDS[study["fluid"]]
    cin, a_in = _centre(study["inlet"])
    cout, a_out = _centre(study["outlet"])
    a_in_m2 = a_in * 1e-6
    kind, value = study["inlet_kind"], float(study["inlet_value"])
    if kind == "Volume Flow Rate":
        q = value
    elif kind == "Mass Flow Rate":
        q = value / rho
    else:
        q = value * a_in_m2
    axis = cout - cin
    length = axis.Length
    if length < 1e-9:
        raise ValueError("inlet and outlet are at the same place")
    d = V(axis)
    d.normalize()
    n = max(10, min(80, int(length / 2.0)))
    stations = []
    for i in range(n):
        t = (i + 0.5) / float(n)            # mid-steps: a cut exactly on the lid is no section
        p = cin + axis * t
        area, perim, centre = _section(cavity, p, d)
        if area <= 0:
            continue
        stations.append({"t": t, "point": p, "centre": centre, "area": area, "perimeter": perim})
    if len(stations) < 2:
        raise ValueError("the fluid volume is not crossed between inlet and outlet")
    dp = 0.0
    vmax = 0.0
    for i, s in enumerate(stations):
        s["velocity"] = q / (s["area"] * 1e-6)
        vmax = max(vmax, s["velocity"])
        dh = 4.0 * s["area"] / max(s["perimeter"], 1e-9) * 1e-3          # m
        s["re"] = rho * s["velocity"] * dh / mu
        if i == 0:
            continue
        prev = stations[i - 1]
        seg = (s["point"] - prev["point"]).Length * 1e-3
        v = 0.5 * (s["velocity"] + prev["velocity"])
        re = max(rho * v * dh / mu, 1e-9)
        f = 64.0 / re if re < 2300 else 0.316 * re ** -0.25
        dp += f * seg / max(dh, 1e-9) * rho * v * v / 2.0
        a1, a2 = prev["area"], s["area"]
        if a2 > a1 * 1.05:            # sudden expansion (Borda-Carnot)
            dp += (1 - a1 / a2) ** 2 * rho * prev["velocity"] ** 2 / 2.0
        elif a2 < a1 * 0.95:          # contraction
            dp += 0.5 * (1 - a2 / a1) * rho * s["velocity"] ** 2 / 2.0
        s["pressure_drop"] = dp
    stations[0]["pressure_drop"] = 0.0
    covered = (stations[-1]["point"] - stations[0]["point"]).Length
    if covered > 1e-9:                   # the half steps at each end: as their neighbours
        ends = (length - covered) / covered
        dp *= 1.0 + ends
    p_out = float(study.get("outlet_pressure", 101325.0))
    for s in stations:
        s["pressure"] = p_out + dp - s["pressure_drop"]
    trajs = trajectories(stations, study["inlet"], d, int(study.get("trajectories", 25)))
    return {"stations": stations, "max_velocity": vmax, "pressure_drop": dp, "inlet_pressure": p_out + dp,
            "outlet_pressure": p_out, "volume_flow": q, "mass_flow": q * rho, "fluid": study["fluid"],
            "inlet_velocity": stations[0]["velocity"], "outlet_velocity": stations[-1]["velocity"],
            "reynolds": max(s["re"] for s in stations), "trajectories": trajs,
            "fluid_volume_mm3": cavity.Volume}


def _section(cavity, p, d):
    """(area mm2, wetted perimeter mm, centre) of the cavity cut by the plane at p normal to d."""
    try:
        wires = cavity.slice(d, d.dot(p))
    except Exception:
        return 0.0, 0.0, p
    import Part
    best = None
    for w in wires:
        try:
            f = Part.Face(w)
        except Exception:
            continue
        dist = f.distToShape(Part.Vertex(p))[0]
        if best is None or dist < best[0]:
            best = (dist, f, w)
    if best is None:
        return 0.0, 0.0, p
    _dist, f, w = best
    return abs(f.Area), w.Length, f.CenterOfMass


def trajectories(stations, inlet_faces, d, count):
    """count polylines from points spread over the inlet, each keeping its relative place in the
    section; [(points, velocities)]."""
    import random
    rnd = random.Random(7)
    starts = []
    pool = []
    for f in inlet_faces:
        u0, u1, v0, v1 = f.ParameterRange
        tries = 0
        while len(pool) < count * 4 and tries < count * 40:
            tries += 1
            u, v = u0 + (u1 - u0) * rnd.random(), v0 + (v1 - v0) * rnd.random()
            if f.isInside(f.valueAt(u, v), 1e-6, True):
                pool.append(f.valueAt(u, v))
    step = max(1, len(pool) // max(count, 1))
    starts = pool[::step][:count]
    c0 = stations[0]["centre"]
    r0 = math.sqrt(stations[0]["area"] / math.pi)
    out = []
    for sp in starts:
        off = sp - c0
        off = off - d * off.dot(d)
        pts, vel = [], []
        for s in stations:
            scale = math.sqrt(s["area"] / math.pi) / max(r0, 1e-9)
            pts.append(s["centre"] + off * scale)
            frac = min(1.0, off.Length / max(r0, 1e-9))
            vel.append(s["velocity"] * 2.0 * (1 - frac * frac) if s["re"] < 2300 else s["velocity"] * 1.2 * (1 - frac) ** (1 / 7.0))
        out.append((pts, vel))
    return out


def report(res, units="SI (m-kg-s)"):
    si = units.startswith("SI")
    pa = (lambda x: "%.4g Pa" % x) if si else (lambda x: "%.4g psi" % (x / 6894.757))
    ms = (lambda x: "%.4g m/s" % x) if si else (lambda x: "%.4g in/s" % (x / 0.0254))
    rows = [("Fluid", res["fluid"]), ("Volume flow rate", "%.4g m^3/s" % res["volume_flow"] if si else "%.4g in^3/s" % (res["volume_flow"] / 1.6387e-5)),
            ("Mass flow rate", "%.4g kg/s" % res["mass_flow"] if si else "%.4g lb/s" % (res["mass_flow"] * 2.20462)),
            ("Inlet velocity", ms(res["inlet_velocity"])), ("Outlet velocity", ms(res["outlet_velocity"])),
            ("Maximum velocity", ms(res["max_velocity"])), ("Inlet pressure", pa(res["inlet_pressure"])),
            ("Outlet pressure", pa(res["outlet_pressure"])), ("Pressure drop", pa(res["pressure_drop"])),
            ("Maximum Reynolds number", "%.0f" % res["reynolds"]),
            ("Fluid volume", "%.4g mm^3" % res["fluid_volume_mm3"])]
    return rows


def save_report(res, path, units="SI (m-kg-s)"):
    with open(path, "w", encoding="utf-8") as f:
        f.write("FloXpress report\n\n")
        for k, v in report(res, units):
            f.write("%s: %s\n" % (k, v))
        f.write("\nAlong the flow (from the inlet)\n")
        f.write("Distance %, Area mm^2, Velocity m/s, Pressure Pa\n")
        for s in res["stations"]:
            f.write("%.1f, %.4g, %.4g, %.6g\n" % (s["t"] * 100, s["area"], s["velocity"], s["pressure"]))
    return path


# ---------------------------------------------------------------- the view
def _color(t):
    ""
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return (0.0, 2 * t, 1 - 2 * t)
    return (2 * t - 1, 2 - 2 * t, 0.0)


class Display:
    """The trajectories in the 3D view (Coin lines coloured per vertex) and the Play dot."""

    def __init__(self):
        self.root = None
        self.dot = None
        self.timer = None
        self.frame = 0
        self.res = None

    def show(self, res, count=None):
        from pivy import coin
        self.hide()
        self.res = res
        trajs = res["trajectories"][:count] if count else res["trajectories"]
        vmax = max([max(v) for _p, v in trajs] + [1e-9])
        root = coin.SoSeparator()
        root.setName(GROUP)
        style = coin.SoDrawStyle()
        style.lineWidth = 2
        root.addChild(style)
        for pts, vel in trajs:
            sep = coin.SoSeparator()
            mb = coin.SoMaterialBinding()
            mb.value = coin.SoMaterialBinding.PER_VERTEX
            mat = coin.SoMaterial()
            mat.diffuseColor.setValues(0, len(vel), [_color(v / vmax) for v in vel])
            co = coin.SoCoordinate3()
            co.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
            ls = coin.SoLineSet()
            ls.numVertices.setValue(len(pts))
            for n in (mb, mat, co, ls):
                sep.addChild(n)
            root.addChild(sep)
        self.dots = coin.SoSeparator()
        root.addChild(self.dots)
        self.root = root
        self.count = len(trajs)
        try:
            Gui.ActiveDocument.ActiveView.getSceneGraph().addChild(root)
        except Exception as _fw_err:
            _fw_log("floxpress.py:332", _fw_err)
        return root

    def hide(self):
        self.stop()
        if self.root is not None:
            try:
                Gui.ActiveDocument.ActiveView.getSceneGraph().removeChild(self.root)
            except Exception as _fw_err:
                _fw_log("floxpress.py:341", _fw_err)
        self.root = None

    def play(self):
        if self.res is None or self.root is None:
            return
        self.frame = 0
        if self.timer is None:
            self.timer = QtCore.QTimer()
            self.timer.timeout.connect(self._step)
        self.timer.start(60)

    def stop(self):
        if self.timer is not None:
            self.timer.stop()

    def _step(self):
        from pivy import coin
        trajs = self.res["trajectories"][:self.count]
        n = len(trajs[0][0]) if trajs else 0
        if n == 0:
            return self.stop()
        self.frame = (self.frame + 1) % n
        self.dots.removeAllChildren()
        for pts, _v in trajs:
            p = pts[self.frame]
            s = coin.SoSeparator()
            t = coin.SoTranslation()
            t.translation.setValue(p.x, p.y, p.z)
            m = coin.SoMaterial()
            m.diffuseColor.setValue(1, 1, 1)
            sp = coin.SoSphere()
            sp.radius = 0.6
            for x in (t, m, sp):
                s.addChild(x)
            self.dots.addChild(s)


# ---------------------------------------------------------------- the wizard
def _picked_faces(doc):
    out = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        for sub in sel.SubElementNames:
            try:
                s = sel.Object.getSubObject(sub)
            except Exception:
                s = None
            if s is not None and s.ShapeType == "Face":
                out.append((sel.Object.Name, sub, s))
    return out


if Gui is not None:
    class FloXpressPanel:
        def __init__(self, doc):
            self.doc = doc
            self.shape = model_shape(doc)
            self.cavity = None
            self.inlet, self.outlet = [], []
            self.res = None
            self.display = Display()
            self.fluid_shown = None
            w = QtWidgets.QWidget()
            w.setObjectName("FW_FloXpress")
            w.setWindowTitle("FloXpress")
            w.setProperty("swstyle_pm_title", "FloXpress")
            lay = QtWidgets.QVBoxLayout(w)
            self.title = QtWidgets.QLabel()
            self.title.setObjectName("FW_FloStep")
            lay.addWidget(self.title)
            self.stack = QtWidgets.QStackedWidget()
            lay.addWidget(self.stack, 1)
            row = QtWidgets.QHBoxLayout()
            self.back = QtWidgets.QPushButton("< Back")
            self.back.setObjectName("FW_FloBack")
            self.next = QtWidgets.QPushButton("Next >")
            self.next.setObjectName("FW_FloNext")
            row.addWidget(self.back)
            row.addWidget(self.next)
            lay.addLayout(row)
            self.back.clicked.connect(lambda: self.go(self.stack.currentIndex() - 1))
            self.next.clicked.connect(lambda: self.go(self.stack.currentIndex() + 1))
            for build in (self._welcome, self._geometry, self._fluid, self._inlet, self._outlet, self._solve, self._results):
                self.stack.addWidget(build())
            self.form = w
            self.go(0)

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Close

        def reject(self):
            self.display.hide()
            self._show_fluid(False)
            Gui.Control.closeDialog()
            return True

        accept = reject

        def go(self, i):
            i = max(0, min(len(STEPS) - 1, i))
            if i > self.stack.currentIndex() and not self._can_leave(self.stack.currentIndex()):
                return
            self.stack.setCurrentIndex(i)
            self.title.setText("<b>%s</b>" % STEPS[i])
            self.back.setEnabled(i > 0)
            self.next.setEnabled(i < len(STEPS) - 1 and (i != 5 or self.res is not None))

        def _can_leave(self, i):
            if i == 1 and self.cavity is None:
                self.geo_msg.setText("The model has no closed internal volume: add lids to the openings.")
                return False
            if i == 3 and not self.inlet:
                self.in_msg.setText("Select the inside face of the inlet lid.")
                return False
            if i == 4 and not self.outlet:
                self.out_msg.setText("Select the inside face of the outlet lid.")
                return False
            return True

        def _page(self, *widgets):
            p = QtWidgets.QWidget()
            l = QtWidgets.QVBoxLayout(p)
            for x in widgets:
                l.addWidget(x) if isinstance(x, QtWidgets.QWidget) else l.addLayout(x)
            l.addStretch(1)
            return p

        def _welcome(self):
            self.units = QtWidgets.QComboBox()
            self.units.setObjectName("FW_FloUnits")
            self.units.addItems(list(UNITS))
            return self._page(QtWidgets.QLabel("FloXpress shows how a fluid flows through the model.\n"
                                               "Close the openings with lids first."), QtWidgets.QLabel("Units:"), self.units)

        def _geometry(self):
            self.geo_msg = QtWidgets.QLabel()
            self.geo_msg.setObjectName("FW_FloGeometryStatus")
            self.geo_msg.setWordWrap(True)
            view = QtWidgets.QCheckBox("View fluid volume")
            view.setObjectName("FW_FloViewFluid")
            view.toggled.connect(self._show_fluid)
            self.view_fluid = view
            self.check_geometry()
            return self._page(self.geo_msg, view)

        def check_geometry(self):
            self.cavity = fluid_volume(self.shape)
            if self.cavity is None:
                self.geo_msg.setText("No closed internal volume. Add lids to the inlet and outlet openings.")
            else:
                self.geo_msg.setText("Fluid volume found: %.4g mm^3." % self.cavity.Volume)
            return self.cavity

        def _show_fluid(self, on):
            if self.fluid_shown is not None:
                try:
                    self.doc.removeObject(self.fluid_shown)
                except Exception as _fw_err:
                    _fw_log("floxpress.py:499", _fw_err)
                self.fluid_shown = None
            if on and self.cavity is not None:
                o = self.doc.addObject("Part::Feature", "FloXpressFluidVolume")
                o.Shape = self.cavity
                if o.ViewObject is not None:
                    o.ViewObject.ShapeColor = (0.2, 0.5, 1.0)
                    o.ViewObject.Transparency = 50
                self.fluid_shown = o.Name

        def _fluid(self):
            self.fluid = QtWidgets.QComboBox()
            self.fluid.setObjectName("FW_FloFluid")
            self.fluid.addItems(list(FLUIDS))
            return self._page(QtWidgets.QLabel("Fluid:"), self.fluid)

        def _face_page(self, which):
            lst = QtWidgets.QListWidget()
            lst.setObjectName("FW_Flo%sFaces" % which)
            lst.setMaximumHeight(80)
            add = QtWidgets.QPushButton("Add Selected Faces")
            add.setObjectName("FW_Flo%sAdd" % which)
            msg = QtWidgets.QLabel()
            msg.setWordWrap(True)
            return lst, add, msg

        def _inlet(self):
            self.in_list, add, self.in_msg = self._face_page("Inlet")
            add.clicked.connect(lambda: self.add_faces("inlet"))
            self.in_kind = QtWidgets.QComboBox()
            self.in_kind.setObjectName("FW_FloInletKind")
            self.in_kind.addItems(list(INLET_KINDS))
            self.in_value = QtWidgets.QDoubleSpinBox()
            self.in_value.setObjectName("FW_FloInletValue")
            self.in_value.setDecimals(6)
            self.in_value.setRange(1e-9, 1e6)
            self.in_value.setValue(0.0001)
            self.in_unit = QtWidgets.QLabel("m^3/s")
            self.in_kind.currentTextChanged.connect(
                lambda t: self.in_unit.setText({"Volume Flow Rate": "m^3/s", "Mass Flow Rate": "kg/s", "Velocity": "m/s"}[t]))
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self.in_value)
            row.addWidget(self.in_unit)
            return self._page(QtWidgets.QLabel("Select the inside faces of the inlet lids."), self.in_list, add, self.in_msg,
                              self.in_kind, row)

        def _outlet(self):
            self.out_list, add, self.out_msg = self._face_page("Outlet")
            add.clicked.connect(lambda: self.add_faces("outlet"))
            self.out_p = QtWidgets.QDoubleSpinBox()
            self.out_p.setObjectName("FW_FloOutletPressure")
            self.out_p.setRange(0, 1e8)
            self.out_p.setDecimals(1)
            self.out_p.setValue(101325.0)
            row = QtWidgets.QHBoxLayout()           # the caption over its box: the page fits the 300 px pane (look audit AO2)
            row.addWidget(self.out_p)
            row.addWidget(QtWidgets.QLabel("Pa"))
            return self._page(QtWidgets.QLabel("Select the inside faces of the outlet lids."), self.out_list, add,
                              self.out_msg, QtWidgets.QLabel("Environment pressure:"), row)

        def add_faces(self, which, faces=None):
            picked = faces if faces is not None else [s for _o, _sub, s in _picked_faces(self.doc)]
            if self.cavity is None:
                return []
            cf = cavity_faces(self.cavity, picked)
            lst = self.in_list if which == "inlet" else self.out_list
            target = self.inlet if which == "inlet" else self.outlet
            for f in cf:
                target.append(f)
                lst.addItem("Face (%.4g mm^2)" % f.Area)
            msg = self.in_msg if which == "inlet" else self.out_msg
            msg.setText("" if cf else "The selected face does not touch the fluid volume.")
            return cf

        def _solve(self):
            run = QtWidgets.QPushButton("Run")
            run.setObjectName("FW_FloRun")
            run.clicked.connect(self.run)
            self.solve_msg = QtWidgets.QLabel()
            self.solve_msg.setObjectName("FW_FloSolveStatus")
            self.solve_msg.setWordWrap(True)
            return self._page(run, self.solve_msg)

        def run(self):
            study = {"cavity": self.cavity, "inlet": self.inlet, "outlet": self.outlet,
                     "fluid": self.fluid.currentText(), "inlet_kind": self.in_kind.currentText(),
                     "inlet_value": self.in_value.value(), "outlet_pressure": self.out_p.value(),
                     "trajectories": 25}
            try:
                self.res = solve(study)
            except Exception as error:
                self.solve_msg.setText("Not solved: %s" % error)
                return None
            self.solve_msg.setText("Solved. Maximum velocity %.4g m/s, pressure drop %.4g Pa." %
                                   (self.res["max_velocity"], self.res["pressure_drop"]))
            self.fill_results()
            self.go(6)
            return self.res

        def _results(self):
            self.traj_on = QtWidgets.QCheckBox("Flow Trajectories")
            self.traj_on.setObjectName("FW_FloTrajectories")
            self.traj_on.setChecked(True)
            self.traj_n = QtWidgets.QSpinBox()
            self.traj_n.setObjectName("FW_FloTrajectoryCount")
            self.traj_n.setRange(1, 200)
            self.traj_n.setValue(25)
            play = QtWidgets.QPushButton("Play")
            play.setObjectName("FW_FloPlay")
            play.clicked.connect(self.display.play)
            stop = QtWidgets.QPushButton("Stop")
            stop.clicked.connect(self.display.stop)
            self.traj_on.toggled.connect(lambda _on: self._redraw())
            self.traj_n.valueChanged.connect(lambda _n: self._redraw())
            self.table = QtWidgets.QTableWidget(0, 2)
            self.table.setObjectName("FW_FloReport")
            self.table.setHorizontalHeaderLabels(["Result", "Value"])
            self.table.horizontalHeader().setStretchLastSection(True)
            save_b = QtWidgets.QPushButton("Save Report...")
            save_b.setObjectName("FW_FloSaveReport")
            save_b.clicked.connect(self._save)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel("Number of trajectories:"))
            row.addWidget(self.traj_n)
            prow = QtWidgets.QHBoxLayout()
            prow.addWidget(play)
            prow.addWidget(stop)
            return self._page(self.traj_on, row, prow, self.table, save_b)

        def _redraw(self):
            if self.res is None:
                return
            if self.traj_on.isChecked():
                if self.traj_n.value() > len(self.res["trajectories"]):
                    self.res["trajectories"] = trajectories(self.res["stations"], self.inlet,
                                                            _axis(self.res), self.traj_n.value())
                self.display.show(self.res, self.traj_n.value())
            else:
                self.display.hide()

        def fill_results(self):
            rows = report(self.res, self.units.currentText())
            self.table.setRowCount(len(rows))
            for r, (k, v) in enumerate(rows):
                self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(k))
                self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(v))
            self._redraw()

        def _save(self, path=None):
            if self.res is None:
                return None
            if path is None:
                base = os.path.splitext(self.doc.FileName or self.doc.Label)[0] + "-FloXpress.txt"
                path = QtWidgets.QFileDialog.getSaveFileName(self.form, "Save Report", base, "Text (*.txt)")[0]
            if path:
                return save_report(self.res, path, self.units.currentText())
            return None


def _axis(res):
    d = res["stations"][-1]["point"] - res["stations"][0]["point"]
    d.normalize()
    return d


OPEN = []


def can_start():
    d = App.ActiveDocument
    if d is None or (Gui and Gui.Control.activeDialog()):
        return False
    for o in d.Objects:              # cheap: any solid (the fuse waits for the wizard)
        s = getattr(o, "Shape", None)
        try:
            if s is not None and not s.isNull() and s.Solids:
                return True
        except Exception:
            continue
    return False


def start(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None or Gui.Control.activeDialog():
        return None
    p = FloXpressPanel(doc)
    OPEN[:] = [p]
    Gui.Control.showDialog(p)
    return p


class FloXpressCommand:
    def GetResources(self):
        return {"MenuText": "FloXpress", "Pixmap": "Std_ViewIvIssueCamPos",
                "ToolTip": "A first look at a fluid flowing through the part or assembly: inlet, outlet, "
                           "flow trajectories, velocity and pressure drop."}

    def Activated(self, *a):
        start()

    def IsActive(self):
        try:
            return can_start()
        except Exception:
            return False


def register():
    if Gui is None:
        return
    if "SWStyle_FloXpress" not in Gui.listCommands():
        Gui.addCommand("SWStyle_FloXpress", FloXpressCommand())
    from . import catalog
    if "FloXpress" not in catalog.BY_KEY:
        catalog.BY_KEY["FloXpress"] = catalog.c("FloXpress", "FloXpress", ("SWStyle_FloXpress",), None,
                                                "A first look at a fluid flowing through the model.",
                                                caption="FloXpress")
