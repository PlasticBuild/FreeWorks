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
import math
import os

import FreeCAD as App
import Part

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

V = App.Vector

# density kg/m3, yield MPa, E MPa, poisson, kg CO2e/kg, MJ/kg, l water/kg, price per kg, machinability factor
MATERIALS = {
    "Plain Carbon Steel": (7800, 220, 210000, 0.28, 2.0, 28.0, 45, 1.2, 1.0),
    "AISI 304 Stainless": (8000, 207, 193000, 0.29, 6.2, 68.0, 120, 4.0, 1.8),
    "6061-T6 Aluminium": (2700, 275, 69000, 0.33, 9.5, 180.0, 150, 4.5, 0.6),
    "Brass": (8500, 240, 100000, 0.33, 3.9, 60.0, 200, 7.0, 0.7),
    "ABS": (1050, 40, 2200, 0.35, 3.5, 95.0, 160, 2.5, 0.4),
    "PLA": (1240, 50, 3500, 0.36, 2.0, 50.0, 60, 2.2, 0.4),
    "Nylon 6/6": (1140, 70, 2800, 0.39, 7.9, 140.0, 180, 4.0, 0.5),
}
MAKING = {"Machined": (1.4, 18.0, 4), "Cast": (2.2, 30.0, 10), "Moulded": (1.2, 22.0, 6), "3D printed": (0.9, 14.0, 1)}


def _consumed(o):
    """True when another shape feature uses o (an analysis, a PMI or a folder does not count)."""
    for p in o.InList:
        if p.isDerivedFrom("Part::Feature") and getattr(p, "SWStyleKind", "") != "PMI" \
                and not p.TypeId.startswith("Fem::"):
            return True
    return False


def _solids(doc):
    out = []
    for o in doc.Objects:
        shape = getattr(o, "Shape", None)
        if not isinstance(shape, Part.Shape) or shape.isNull() or not shape.Solids:   # FEM objects carry other Shapes
            continue
        if o.TypeId == "PartDesign::Body" or (not _consumed(o) and o.getParentGeoFeatureGroup() is None):
            out.append(o)
    return out


def _main(doc):
    s = _solids(doc)
    if not s:
        return None
    return max(s, key=lambda o: o.Shape.Volume)


# --------------------------------------------------------------------- sustainability / costing
def sustainability(shape, material, making="Machined"):
    dens, _y, _e, _p, co2, mj, water, _price, _m = MATERIALS[material]
    mass = shape.Volume * 1e-9 * dens                       # mm3 -> m3
    stock = _stock_volume(shape) * 1e-9 * dens if making == "Machined" else mass
    mf = MAKING[making]
    return {"mass_kg": mass, "material_kg": stock,
            "carbon_kg": stock * co2 + mass * mf[0], "energy_mj": stock * mj + mass * mf[1],
            "water_l": stock * water + mass * mf[2]}


def _stock_volume(shape):
    bb = shape.BoundBox
    return (bb.XLength + 2) * (bb.YLength + 2) * (bb.ZLength + 2)


def costing(shape, material, quantity=1, rate_per_hour=60.0, setup=50.0, removal_cm3_min=8.0):
    dens, _y, _e, _p, _c, _mj, _w, price, mach = MATERIALS[material]
    stock_kg = _stock_volume(shape) * 1e-9 * dens
    removed = (_stock_volume(shape) - shape.Volume) / 1000.0  # cm3
    minutes = removed / max(removal_cm3_min / mach, 1e-6) + 0.2 * len(shape.Faces)
    material_cost = stock_kg * price
    machining = minutes / 60.0 * rate_per_hour
    each = material_cost + machining + setup / max(quantity, 1)
    return {"stock_kg": stock_kg, "removed_cm3": removed, "minutes": minutes, "material": material_cost,
            "machining": machining, "setup_each": setup / max(quantity, 1), "each": each, "batch": each * quantity}


# --------------------------------------------------------------------- manufacturability
def _is_hole(face):
    s = face.Surface
    if s.TypeId != "Part::GeomCylinder":
        return False
    u0, u1, v0, v1 = face.ParameterRange
    p = face.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
    n = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    axis_pt = s.Center + s.Axis * (p - s.Center).dot(s.Axis)
    return (axis_pt - p).dot(n) > 0 and abs(u1 - u0) > 6.0


def manufacturability(shape, min_hole=1.5, max_ratio=5.0, min_wall=1.0, check_corners=True):
    ""
    out = []
    holes = [(i, f) for i, f in enumerate(shape.Faces) if _is_hole(f)]
    ratios = []
    small = []
    flat = []
    for i, f in holes:
        d = 2 * f.Surface.Radius
        depth = abs(f.ParameterRange[3] - f.ParameterRange[2])
        ratios.append((depth / d, i))
        if d < min_hole:
            small.append(i)
        # flat bottom: a plane face sharing an edge with the hole whose normal is along the axis, inside the part
        for e in f.Edges:
            for g in shape.ancestorsOfType(e, Part.Face):
                if g.isSame(f) or g.Surface.TypeId != "Part::GeomPlane":
                    continue
                if abs(abs(g.normalAt(0, 0).dot(f.Surface.Axis)) - 1) < 1e-6 and g.Area < math.pi * f.Surface.Radius ** 2 * 1.01:
                    flat.append(i)
    bad = [i for r, i in ratios if r > max_ratio]
    out.append(("Hole depth to diameter ratio (max %g)" % max_ratio, not bad,
                ", ".join("Face%d (%.1f)" % (i + 1, r) for r, i in ratios if r > max_ratio) or "%d holes OK" % len(holes)))
    out.append(("Holes of at least %.1f mm" % min_hole, not small, ", ".join("Face%d" % (i + 1) for i in small) or "OK"))
    out.append(("Drilled holes, not flat-bottom", not flat, ", ".join("Face%d" % (i + 1) for i in sorted(set(flat))) or "OK"))
    sharp = []
    if check_corners:
        for k, e in enumerate(shape.Edges):
            fs = shape.ancestorsOfType(e, Part.Face)
            if len(fs) != 2 or e.Curve.TypeId != "Part::GeomLine":
                continue
            a, b = fs
            if a.Surface.TypeId != "Part::GeomPlane" or b.Surface.TypeId != "Part::GeomPlane":
                continue
            m = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
            na, nb = a.normalAt(0, 0), b.normalAt(0, 0)
            if abs(na.dot(nb)) > 0.99:
                continue
            probe = m + (na - nb) * 0.05          # an inside (concave) corner: this point is in the material
            if shape.isInside(probe, 1e-5, False):
                sharp.append(k)
    out.append(("Inside corners have a radius (milling)", not sharp,
                "%d sharp inside corners: %s" % (len(sharp), ", ".join("Edge%d" % (k + 1) for k in sharp[:8]))
                if sharp else "OK"))
    thin = []
    planes = [(i, f) for i, f in enumerate(shape.Faces) if f.Surface.TypeId == "Part::GeomPlane"]
    for i, f in planes:
        n = f.normalAt(0, 0)
        for j, g in planes:
            if j <= i:
                continue
            if abs(n.dot(g.normalAt(0, 0)) + 1) < 1e-6:
                d = abs((g.CenterOfMass - f.CenterOfMass).dot(n))
                if d < min_wall:
                    thin.append((i, j, d))
    out.append(("Walls of at least %.1f mm" % min_wall, not thin,
                ", ".join("Face%d/Face%d %.2f mm" % (i + 1, j + 1, d) for i, j, d in thin[:6]) or "OK"))
    return out


# --------------------------------------------------------------------- previous release check
STOCK_PREFIXES = ("Part::", "PartDesign::", "Sketcher::", "App::", "Spreadsheet::", "TechDraw::", "Mesh::",
                  "Assembly::", "Fem::", "Image::", "Points::", "Surface::")


def _tree_row(o, proxy):
    """The FeatureManager's own folders and rows (Solid Bodies, Surface Bodies, Material, a body's row): no shape,
    nothing to rebuild; stock FreeCAD just shows them as plain objects (look audit AO4)."""
    if o.isDerivedFrom("Part::Feature"):
        return False
    name = type(proxy).__name__
    return name in TREE_ROWS or name.endswith(("Folder", "Row"))


TREE_ROWS = ("Folder", "SolidBodiesFolder", "SurfaceBodiesFolder", "MaterialRow", "SolidBodyRow")


def release_check(doc):
    ""
    out = []
    for o in doc.Objects:
        proxy = getattr(o, "Proxy", None)
        mod = type(proxy).__module__ if proxy is not None and not isinstance(proxy, (int, str)) else ""
        if ("swstyle" in mod or "freeworks" in mod.lower()) and _tree_row(o, proxy):
            continue
        if getattr(o, "SWStyleKind", "") == "PMI":
            out.append((o, "annotation: not shown without this interface, the model is unchanged"))
        elif "swstyle" in mod or "freeworks" in mod.lower():
            out.append((o, "Interface feature (%s): shape kept, no rebuild without this interface" % type(proxy).__name__))
        elif not o.TypeId.startswith(STOCK_PREFIXES) and "Python" not in o.TypeId:
            out.append((o, "type %s is not in stock FreeCAD" % o.TypeId))
    return out


# --------------------------------------------------------------------- on demand manufacturing
def quote_pack(doc, folder):
    import zipfile
    import Mesh
    os.makedirs(folder, exist_ok=True)
    base = os.path.join(folder, doc.Label or doc.Name)
    objs = _solids(doc)
    Part.export(objs, base + ".step")
    import MeshPart
    mesh = Mesh.Mesh()
    for o in objs:
        mesh.addMesh(MeshPart.meshFromShape(Shape=o.Shape, LinearDeflection=0.05, AngularDeflection=0.3))
    mesh.write(base + ".stl")
    doc.saveCopy(base + ".FCStd")
    main = _main(doc)
    info = {"part": doc.Label, "volume_mm3": round(main.Shape.Volume, 2) if main else 0,
            "size_mm": [round(x, 2) for x in (main.Shape.BoundBox.XLength, main.Shape.BoundBox.YLength,
                                              main.Shape.BoundBox.ZLength)] if main else []}
    with open(base + "-quote.json", "w") as f:
        json.dump(info, f, indent=1)
    out = base + "-quote.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for ext in (".step", ".stl", ".FCStd", "-quote.json"):
            z.write(base + ext, os.path.basename(base + ext))
    return out


# --------------------------------------------------------------------- simulation (FreeCAD FEM)
def simulate(doc, obj, fixed, loaded, force_n, material, mesh_size=None, run=True):
    """A linear static study: fixed faces, a force on faces, CalculiX. Returns the result summary."""
    from .simxpress import fem_safe
    with fem_safe():
        return _simulate(doc, obj, fixed, loaded, force_n, material, mesh_size, run)


def _simulate(doc, obj, fixed, loaded, force_n, material, mesh_size=None, run=True):
    import ObjectsFem
    dens, yield_mpa, e_mpa, nu = MATERIALS[material][:4]
    analysis = ObjectsFem.makeAnalysis(doc, "SimulationStudy")
    analysis.Label = "Static Study"
    solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "Solver") if hasattr(ObjectsFem, "makeSolverCalculiXCcxTools") \
        else ObjectsFem.makeSolverCalculiX(doc, "Solver")
    analysis.addObject(solver)
    mat = ObjectsFem.makeMaterialSolid(doc, "Material")
    m = mat.Material
    m.update({"Name": material, "YoungsModulus": "%g MPa" % e_mpa, "PoissonRatio": str(nu),
              "Density": "%g kg/m^3" % dens})
    mat.Material = m
    analysis.addObject(mat)
    fx = ObjectsFem.makeConstraintFixed(doc, "Fixture")
    fx.References = [(obj, fixed)]
    analysis.addObject(fx)
    ld = ObjectsFem.makeConstraintForce(doc, "Load")
    ld.References = [(obj, loaded)]
    ld.Force = "%g N" % force_n
    ld.Reversed = False
    analysis.addObject(ld)
    mesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
    mesh.Shape = obj
    from . import simxpress
    simxpress.high_quality(mesh)
    size = mesh_size or max(obj.Shape.BoundBox.DiagonalLength / 25.0, 0.5)
    mesh.CharacteristicLengthMax = "%g mm" % size
    analysis.addObject(mesh)
    doc.recompute()
    from femmesh.gmshtools import GmshTools
    err = GmshTools(mesh).create_mesh()
    if err:
        raise RuntimeError("Meshing failed: %s" % err)
    if not run:
        return {"analysis": analysis}
    from femtools import ccxtools
    fea = ccxtools.FemToolsCcx(analysis, solver)
    fea.update_objects()
    fea.setup_working_dir()
    fea.setup_ccx()
    message = fea.check_prerequisites()
    if message:
        raise RuntimeError(message)
    fea.purge_results()
    fea.write_inp_file()
    simxpress.solver_stopped(fea, simxpress.run_ccx(fea))
    fea.load_results()
    res = next((o for o in analysis.Group if o.isDerivedFrom("Fem::FemResultObject")), None)
    if res is None:
        raise RuntimeError("The solver gave no result")
    vm = max(res.vonMises) if res.vonMises else 0.0
    disp = max(res.DisplacementLengths) if res.DisplacementLengths else 0.0
    return {"analysis": analysis, "result": res, "max_von_mises_mpa": vm, "max_displacement_mm": disp,
            "factor_of_safety": (yield_mpa / vm) if vm > 0 else float("inf")}


# ===================================================================== GUI
if Gui is not None:
    def _faces_picked():
        out = []
        for sel in Gui.Selection.getSelectionEx("", 0):
            for sub in sel.SubElementNames:
                if sub.split(".")[-1].startswith("Face"):
                    holder = sel.Object
                    for part in sub.split(".")[:-1]:
                        c = sel.Object.Document.getObject(part)
                        if c is not None:
                            holder = c
                    out.append((holder, sub.split(".")[-1]))
        return out

    def _material_box(default="Plain Carbon Steel"):
        box = QtWidgets.QComboBox()
        box.addItems(list(MATERIALS))
        box.setCurrentText(default)
        return box

    class _Report(QtWidgets.QDialog):
        def __init__(self, title, rows, header=("Check", "Result", "Detail"), extra=None):
            super().__init__(Gui.getMainWindow())
            self.setWindowTitle(title)
            self.resize(640, 360)
            lay = QtWidgets.QVBoxLayout(self)
            if extra is not None:
                lay.addLayout(extra)
            self.table = QtWidgets.QTableWidget(0, len(header))
            self.table.setHorizontalHeaderLabels(list(header))
            self.table.horizontalHeader().setStretchLastSection(True)
            self.table.setWordWrap(True)
            self.table.verticalHeader().setVisible(False)
            lay.addWidget(self.table)
            self.fill(rows)
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)

        def fill(self, rows):
            self.table.setRowCount(0)
            for row in rows:
                r = self.table.rowCount()
                self.table.insertRow(r)
                for c, v in enumerate(row):
                    self.table.setItem(r, c, QtWidgets.QTableWidgetItem(str(v)))
            # every column whole (look audit AO4: 640 px cut all three); the box grows to fit, up to the screen,
            # and the last column wraps past that
            t = self.table
            t.resizeColumnsToContents()
            want = sum(t.columnWidth(c) for c in range(t.columnCount())) + t.verticalScrollBar().sizeHint().width() + 40
            try:
                room = self.screen().availableGeometry().width() - 80
            except Exception:
                room = 1200
            self.resize(max(self.width(), min(want, room)), self.height())
            if want > room and t.columnCount():
                last = t.columnCount() - 1
                t.setColumnWidth(last, max(200, room - 40 - sum(t.columnWidth(c) for c in range(last))))
            t.resizeRowsToContents()

    def _dfm():
        try:                    # DFMXpress: the Task Pane tab (dfmxpress.py); the table below if it is missing
            from . import dfmxpress
            return dfmxpress.open_dfm()
        except ImportError:
            pass
        obj = _main(App.ActiveDocument)
        rows = [(rule, "Pass" if ok else "Fail", detail) for rule, ok, detail in manufacturability(obj.Shape)]
        _Report("Manufacturability Check: " + obj.Label, rows).exec_()

    def _sustain():
        try:                    # Sustainability: the Task Pane tab (sustainability.py); the table below if it is missing
            from . import sustainability
            return sustainability.open_sustainability()
        except ImportError:
            pass
        obj = _main(App.ActiveDocument)
        top = QtWidgets.QHBoxLayout()
        mat = _material_box()
        make = QtWidgets.QComboBox()
        make.addItems(list(MAKING))
        top.addWidget(QtWidgets.QLabel("Material"))
        top.addWidget(mat)
        top.addWidget(QtWidgets.QLabel("Made by"))
        top.addWidget(make)

        def rows():
            r = sustainability(obj.Shape, mat.currentText(), make.currentText())
            return [("Mass", "%.3f kg" % r["mass_kg"], ""), ("Material used", "%.3f kg" % r["material_kg"], ""),
                    ("Carbon footprint", "%.2f kg CO2e" % r["carbon_kg"], "material + making"),
                    ("Total energy", "%.1f MJ" % r["energy_mj"], ""), ("Water", "%.0f l" % r["water_l"], "")]
        d = _Report("Sustainability: " + obj.Label, rows(), ("Measure", "Value", "Note"), top)
        mat.currentTextChanged.connect(lambda *_: d.fill(rows()))
        make.currentTextChanged.connect(lambda *_: d.fill(rows()))
        d.exec_()

    def _release():
        rows = [(o.Label, "Needs this interface", why) for o, why in release_check(App.ActiveDocument)] or \
            [("All objects", "OK", "opens and rebuilds in stock FreeCAD")]
        _Report("Previous Release Check", rows, ("Object", "Result", "Why")).exec_()

    def _quote():
        doc = App.ActiveDocument
        folder = QtWidgets.QFileDialog.getExistingDirectory(Gui.getMainWindow(), "Save the quote pack to",
                                                            os.path.expanduser("~"))
        if folder:
            out = quote_pack(doc, folder)
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder))
            App.Console.PrintMessage("On Demand Manufacturing: %s\n" % out)

    class PartReviewer(QtWidgets.QDialog):
        """Steps through the part's features; each step shows the part as it was then."""

        def __init__(self):
            super().__init__(Gui.getMainWindow())
            self.setWindowTitle("Part Reviewer")
            self.doc = App.ActiveDocument
            self.body = next((o for o in self.doc.Objects if o.TypeId == "PartDesign::Body"), None)
            self.steps = [o for o in (self.body.Group if self.body else self.doc.Objects)
                          if getattr(o, "Shape", None) is not None and o.isDerivedFrom("Part::Feature")
                          and not o.TypeId.startswith("Sketcher::")]
            self.shown = {o.Name: o.ViewObject.Visibility for o in self.steps}
            self.i = 0
            lay = QtWidgets.QVBoxLayout(self)
            self.title = QtWidgets.QLabel("")
            self.title.setStyleSheet("font-weight: bold;")
            self.comment = QtWidgets.QPlainTextEdit()
            self.comment.setPlaceholderText("Comment on this feature (kept in its description)")
            lay.addWidget(self.title)
            lay.addWidget(self.comment)
            row = QtWidgets.QHBoxLayout()
            for text, step in (("|<", "first"), ("< Previous", -1), ("Next >", 1), (">|", "last")):
                b = QtWidgets.QPushButton(text)
                b.clicked.connect(lambda _c=False, s=step: self.go(s))
                row.addWidget(b)
            lay.addLayout(row)
            close = QtWidgets.QPushButton("Close")
            close.clicked.connect(self.close)
            lay.addWidget(close)
            self.go(0)

        def _save(self):
            if self.steps:
                self.steps[self.i].Label2 = self.comment.toPlainText()

        def go(self, step):
            if not self.steps:
                self.title.setText("No features to review")
                return
            self._save()
            if step == "first":
                self.i = 0
            elif step == "last":
                self.i = len(self.steps) - 1
            else:
                self.i = max(0, min(len(self.steps) - 1, self.i + step))
            for k, o in enumerate(self.steps):
                o.ViewObject.Visibility = k == self.i
            f = self.steps[self.i]
            self.title.setText("Step %d of %d: %s" % (self.i + 1, len(self.steps), f.Label))
            self.comment.setPlainText(f.Label2)
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(f)

        def closeEvent(self, e):
            self._save()
            for o in self.steps:
                o.ViewObject.Visibility = self.shown.get(o.Name, False)
            super().closeEvent(e)

    def _costing():
        from . import costing
        costing.open_costing()

    def _xpress():
        from . import simxpress
        simxpress.open_xpress()

    def _has_solid():
        return App.ActiveDocument is not None and _main(App.ActiveDocument) is not None

    def _part_or_assembly():
        doc = App.ActiveDocument
        if doc is None:
            return False
        try:
            from . import asmcore
            asm = asmcore.assembly_of(doc)
            if asm is not None:
                return bool(asmcore.components(asm))     # Costing costs its parts; the others say why
        except Exception as _fw_err:
            _fw_log("evaltools.py:469", _fw_err)
        return _main(doc) is not None

    COMMANDS = (
        ("SWStyle_SimulationWizard", "SimulationXpress Analysis Wizard",
         "A linear static study in steps: fixtures, loads, material, run, results, optimize.",
         _part_or_assembly, _xpress),
        ("SWStyle_ManufacturabilityCheck", "DFMXpress Analysis Wizard", "Checks holes, inside corners and walls for making.",
         _has_solid, _dfm),
        ("SWStyle_Sustainability", "SustainabilityXpress",
         "Carbon, energy, air and water impact of the part's (or the assembly's parts') material and making.",
         _part_or_assembly, _sustain),
        ("SWStyle_Costing", "Costing", "What the part costs to make, per part and per batch.", _part_or_assembly,
         _costing),
        ("SWStyle_PartReviewer", "Part Reviewer", "Steps through the part's features one at a time.",
         lambda: App.ActiveDocument is not None, lambda: PartReviewer().exec_()),
        ("SWStyle_PreviousReleaseCheck", "Previous Release Check", "What stock FreeCAD could not rebuild.",
         lambda: App.ActiveDocument is not None, _release),
        ("SWStyle_OnDemandManufacturing", "On Demand Manufacturing", "Packs STEP, STL and the part for a quote.",
         _has_solid, _quote),
    )

    class _Cmd:
        def __init__(self, text, tip, active, run):
            self.text, self.tip, self.active, self.run = text, tip, active, run

        def GetResources(self):
            return {"MenuText": self.text, "ToolTip": self.tip}

        def IsActive(self):
            try:
                return bool(self.active()) and not Gui.Control.activeDialog()
            except Exception:
                return False

        def Activated(self):
            self.run()


KEYS = (("EV_Simulation", "SimulationXpress Analysis Wizard", "SWStyle_SimulationWizard", "SimulationXpress\nAnalysis Wizard",
         "FLYOUT_SIMULATION"),
        ("EV_DFM", "DFMXpress Analysis Wizard", "SWStyle_ManufacturabilityCheck", "DFMXpress\nAnalysis Wizard", "EV_MANUFACTURABILITY_CHECK"),
        ("EV_Sustainability", "SustainabilityXpress", "SWStyle_Sustainability", None, "EV_SUSTAINABILITY"),
        ("EV_Costing", "Costing", "SWStyle_Costing", None, "EV_COSTING"),
        ("EV_PartReviewer", "Part Reviewer", "SWStyle_PartReviewer", "Part\nReviewer", "EV_PART_REVIEWER"),
        ("EV_ReleaseCheck", "Previous Release Check", "SWStyle_PreviousReleaseCheck", "Previous Release\nCheck", "TOOLS_PREVIOUS_RELEASE_CHECK"),
        ("EV_OnDemand", "On Demand Manufacturing", "SWStyle_OnDemandManufacturing", "On Demand\nManufacturing", "EV_ON_DEMAND"),)


# The one layout: cmtabs.all_tabs puts it at the end of the Evaluate tab.
GROUP = (("stack", (("EV_Simulation", None), ("FloXpress", None), ("EV_DFM", None))),
         ("stack", (("DriveWorksXpress", None), ("EV_OnDemand", None), ("EV_Sustainability", None))),
         ("stack", (("EV_ReleaseCheck", None), ("EV_PartReviewer", None), ("EV_Costing", None))))


def register():
    if Gui is None:
        return
    have = set(Gui.listCommands())
    for name, text, tip, active, run in COMMANDS:
        if name not in have:
            Gui.addCommand(name, _Cmd(text, tip, active, run))
