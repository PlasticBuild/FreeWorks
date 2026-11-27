# SPDX-License-Identifier: LGPL-2.1-or-later
""
















import json
import math

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

_FW_SEEN = set()


def _fw_log(site, err):
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            App.Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return


ELASTIC = "Elastic Support"
SHELL, BEAM = "Shell", "Beam"
# stiffness units to CalculiX's N/mm^3 (Distributed: per area) and N/mm (Total)
DISTRIBUTED_UNITS = {"N/m^3": 1e-9, "N/mm^3": 1.0, "lbf/in^3": 4.4482216152605 / 25.4 ** 3}
TOTAL_UNITS = {"N/m": 1e-3, "N/mm": 1.0, "lbf/in": 4.4482216152605 / 25.4}
LENGTH_UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}
# the picked surface of a shell: where it sits in the thickness (CalculiX's OFFSET, in thicknesses along the normal)
SHELL_OFFSETS = {"Middle surface": 0.0, "Top surface": -0.5, "Bottom surface": 0.5}
# beam section shapes: FreeCAD's section type, then its sizes (label, FreeCAD property)
SECTIONS = {"Rectangular": (("Width", "RectWidth"), ("Height", "RectHeight")),
            "Circular": (("Diameter", "CircDiameter"),),
            "Pipe": (("Outside diameter", "PipeDiameter"), ("Wall thickness", "PipeThickness")),
            "Elliptical": (("Axis 1", "Axis1Length"), ("Axis 2", "Axis2Length")),
            "Box": (("Width", "BoxWidth"), ("Height", "BoxHeight"), ("Wall 1", "BoxT1"), ("Wall 2", "BoxT2"),
                    ("Wall 3", "BoxT3"), ("Wall 4", "BoxT4"))}
ROUTES = ("SIM_Elastic", "SIM_Spring", "SIM_Rigid", "SIM_Shell", "SIM_Beam", "SIM_SolverControl", "SIM_Section",
          "SIM_IsoClip", "SIM_Deform", "SIM_PlotTools")


def _simpms():
    from . import simpms
    return simpms


def ftype(o):
    t = getattr(getattr(o, "Proxy", None), "Type", None)
    return t if isinstance(t, str) and t else getattr(o, "TypeId", "")


def is_elastic(o):
    return getattr(o, "TypeId", "") == "Fem::ConstraintSpring"


def is_shell(o):
    return ftype(o) == "Fem::ElementGeometry2D"


def is_beam(o):
    return ftype(o) == "Fem::ElementGeometry1D"


# --------------------------------------------------------------------------- make / edit (no GUI needed)
def add_elastic(doc, a, obj, faces, normal, shear=0.0, unit="N/m^3", total=False, edit=None):
    """An Elastic Support on faces of obj: normal / shear stiffness per area (Distributed) or for all the faces."""
    sp = _simpms()
    import ObjectsFem
    units = TOTAL_UNITS if total else DISTRIBUTED_UNITS
    if not faces:
        raise sp.SetupError("Pick the faces the elastic support holds.")
    if unit not in units:
        raise sp.SetupError("Unknown unit %r." % unit)
    if float(normal) <= 0 and float(shear) <= 0:
        raise sp.SetupError("Give the elastic support a normal or a shear stiffness.")
    if float(normal) < 0 or float(shear) < 0:
        raise sp.SetupError("A stiffness cannot be negative.")
    area = sum(obj.Shape.getElement(f).Area for f in faces) or 1.0      # mm^2
    factor = units[unit] * (1.0 if total else area)                     # to N/mm for all the faces
    with sp.sx.fem_safe():
        o = edit if edit is not None else ObjectsFem.makeConstraintSpring(doc, "ConstraintSpring")
        o.References = [(obj, list(faces))]
        o.NormalStiffness = "%r N/mm" % (float(normal) * factor)
        o.TangentialStiffness = "%r N/mm" % (float(shear) * factor)
        sp._add(a, o, ELASTIC, edit)
    sp._keep(o, kind=ELASTIC, normal=float(normal), shear=float(shear), unit=unit, total=bool(total))
    sp.symbol(o, (0.0, 0.62, 0.0))
    doc.recompute()
    return o


def elastic_values(o):
    """(normal N/mm, shear N/mm) for all of o's faces: what the PM kept, else FreeCAD's own stiffness values."""
    k = _simpms().kept(o)
    if k.get("kind") == ELASTIC:
        refs = [(r[0], s) for r in o.References for s in r[1]]
        area = sum(g.Shape.getElement(s).Area for g, s in refs) or 1.0
        units = TOTAL_UNITS if k.get("total") else DISTRIBUTED_UNITS
        f = units.get(k.get("unit"), 1.0) * (1.0 if k.get("total") else area)
        return float(k.get("normal") or 0.0) * f, float(k.get("shear") or 0.0) * f
    return (float(o.NormalStiffness.getValueAs("N/mm")), float(o.TangentialStiffness.getValueAs("N/mm")))


def add_shell(doc, a, obj, faces, thickness, unit="mm", offset="Middle surface", edit=None):
    sp = _simpms()
    import ObjectsFem
    if not faces:
        raise sp.SetupError("Pick the faces the shell covers.")
    if float(thickness) <= 0:
        raise sp.SetupError("Give the shell a thickness.")
    if offset not in SHELL_OFFSETS:
        raise sp.SetupError("Unknown offset %r." % offset)
    with sp.sx.fem_safe():
        o = edit if edit is not None else ObjectsFem.makeElementGeometry2D(doc, 1.0, "ElementGeometry2D")
        o.References = [(obj, list(faces))]
        o.Thickness = "%r mm" % (float(thickness) * LENGTH_UNITS.get(unit, 1.0))
        o.Offset = SHELL_OFFSETS[offset]
        sp._add(a, o, SHELL, edit)
    sp._keep(o, kind=SHELL, thickness=float(thickness), unit=unit, offset=offset)
    doc.recompute()
    return o


def add_beam(doc, a, obj, edges, section="Rectangular", sizes=(), unit="mm", edit=None):
    sp = _simpms()
    import ObjectsFem
    if not edges:
        raise sp.SetupError("Pick the edges the beam runs along.")
    if section not in SECTIONS:
        raise sp.SetupError("Unknown section %r." % section)
    sizes = [float(v) for v in sizes]
    names = SECTIONS[section]
    if len(sizes) != len(names) or any(v <= 0 for v in sizes):
        raise sp.SetupError("Give every size of the %s section." % section.lower())
    if section == "Pipe" and 2 * sizes[1] >= sizes[0]:
        raise sp.SetupError("The pipe's wall must be thinner than half its diameter.")
    with sp.sx.fem_safe():
        o = edit if edit is not None else ObjectsFem.makeElementGeometry1D(doc, "Rectangular", 10.0, 25.0, 2.0, "ElementGeometry1D")
        o.References = [(obj, list(edges))]
        o.SectionType = section
        for (label, prop), v in zip(names, sizes):
            setattr(o, prop, "%r mm" % (v * LENGTH_UNITS.get(unit, 1.0)))
        sp._add(a, o, BEAM, edit)
    sp._keep(o, kind=BEAM, section=section, sizes=sizes, unit=unit)
    doc.recompute()
    return o


# --------------------------------------------------------------------------- the CalculiX input
def _node_areas(femmesh, face, ids):
    """{node: its share of the face's area}: each surface element's area split over its nodes; evenly when the
    mesh keeps no surface elements on the face."""
    share = {}
    try:
        for fid in femmesh.getFacesByFace(face):
            fid = fid[0] if isinstance(fid, tuple) else fid
            nodes = femmesh.getElementNodes(fid)
            p = [femmesh.getNodeById(n) for n in nodes[:3]]
            if len(nodes) in (4, 8):
                q = femmesh.getNodeById(nodes[3])
                area = 0.5 * ((p[1] - p[0]).cross(p[2] - p[0]).Length + (p[2] - p[0]).cross(q - p[0]).Length)
            else:
                area = 0.5 * (p[1] - p[0]).cross(p[2] - p[0]).Length
            for n in nodes:
                share[n] = share.get(n, 0.0) + area / len(nodes)
    except Exception as _fw_err:
        _fw_log("simroutes.py:areas", _fw_err)
        share = {}
    ids = [n for n in ids if n in share] if share else list(ids)
    if not share:
        each = face.Area / max(len(ids), 1)
        share = dict((n, each) for n in ids)
    return dict((n, share[n]) for n in ids)


def _frame(nv):
    """Two unit vectors square to nv and to each other (the face's shear directions)."""
    t = App.Vector(1, 0, 0) if abs(nv.x) < 0.9 else App.Vector(0, 1, 0)
    t1 = nv.cross(t)
    t1.normalize()
    t2 = nv.cross(t1)
    t2.normalize()
    return t1, t2


def elastic_input(a, femmesh, node0, elem0, step=None):
    """The model lines of the study's elastic supports: at each face node three springs to ground (SPRINGA, which
    acts along the line between its two nodes), one along the face normal there with the normal stiffness and two
    across it with the shear stiffness, each its share of the face area. The ground nodes sit 1 mm off along each
    spring; step takes their *BOUNDARY (held in all three directions). An inclined face gets its full stiffness
    (springs along X, Y and Z alone would give a 45 degree face half its normal stiffness)."""
    lines, node, elem = [], node0, elem0
    step = [] if step is None else step
    grounds = []
    from . import asmsim
    for k, o in enumerate([o for o in a.Group if is_elastic(o) and not getattr(o, "Suppressed", False)], 1):
        kn, ks = elastic_values(o)
        refs = [(r[0], s) for r in o.References for s in r[1]]
        area = sum(g.Shape.getElement(s).Area for g, s in refs) or 1.0
        for j, (g, s) in enumerate(refs):
            face = g.Shape.getElement(s)
            shares = _node_areas(femmesh, face, asmsim.side_nodes(femmesh, g, s))
            for n, w in sorted(shares.items()):
                p = femmesh.getNodeById(n)
                try:
                    u, v = face.Surface.parameter(p)
                    nv = face.normalAt(u, v)
                except Exception:
                    nv = _simpms()._normal(face)
                nv = App.Vector(nv)
                nv.normalize()
                t1, t2 = _frame(nv)
                for d, (vec, kk) in enumerate(((nv, kn), (t1, ks), (t2, ks))):
                    kk = kk * w / area
                    if kk <= 0:
                        continue
                    q = p + vec
                    lines += ["*NODE", "%d, %.12g, %.12g, %.12g" % (node, q.x, q.y, q.z)]
                    es = "FW_ES%d_%d_%d_%d" % (k, j, n, d)
                    lines += ["*ELEMENT, TYPE=SPRINGA, ELSET=%s" % es, "%d, %d, %d" % (elem, n, node),
                              "*SPRING, ELSET=%s" % es, "", repr(float("%.12g" % kk))]
                    grounds.append(node)
                    node += 1
                    elem += 1
    if grounds:
        lines.append("*NSET, NSET=FW_ES_GROUND")
        for i in range(0, len(grounds), 12):
            lines.append(", ".join(str(x) for x in grounds[i:i + 12]))
        step += ["** FreeCAD elastic supports: their ground", "*BOUNDARY", "FW_ES_GROUND, 1, 3, 0.0"]
    return lines


def patch_input(a, path, femmesh):
    """Adds the elastic supports to the CalculiX input FreeCAD wrote (before its *STEP; the ground in the step)."""
    if not any(is_elastic(o) and not getattr(o, "Suppressed", False) for o in a.Group):
        return False
    text = open(path).read()
    ids = list(femmesh.Volumes) + list(femmesh.Faces) + list(femmesh.Edges) + list(femmesh.Nodes)
    top = max(ids) if ids else 0
    for line in text.splitlines():           # ids FreeCAD or the connectors added (rigid bodies, beams, springs)
        s = line.split(",")[0].strip()
        if s.isdigit():
            top = max(top, int(s))
    step = []
    lines = elastic_input(a, femmesh, top + 1000, top + 1000, step)
    i = text.upper().find("\n*STEP")
    if i < 0:
        raise ValueError("The solver input has no *STEP.")
    text = text[:i + 1] + "** FreeCAD elastic supports\n" + "\n".join(lines) + "\n" + text[i + 1:]
    if step:                                  # the ground held in the first step, as the connectors' pre-loads
        up = text.upper()
        k = up.find("\n*STEP", i)
        e = up.find("\n*END STEP", k)
        n = up.find("\n*NODE FILE", k)
        at = n if 0 <= n < e else e
        if at < 0:
            raise ValueError("The solver input has no *END STEP.")
        text = text[:at + 1] + "\n".join(step) + "\n" + text[at + 1:]
    with open(path, "w") as f:
        f.write(text)
    return True


def _patch_ccx():
    try:
        from femtools import ccxtools
    except ImportError:
        return False
    cls = ccxtools.FemToolsCcx
    if getattr(cls, "_fw_elastic", False):
        return True
    write0 = cls.write_inp_file

    def write_inp_file(self, *args, **kw):
        r = write0(self, *args, **kw)
        try:
            a = self.analysis
            if any(is_elastic(o) for o in a.Group):
                mesh = next((m for m in a.Group if m.isDerivedFrom("Fem::FemMeshObject")), None)
                patch_input(a, self.inp_file_name, mesh.FemMesh)
        except Exception as error:
            App.Console.PrintError("FreeCAD: elastic supports not written (%s)\n" % error)
            raise
        return r

    check0 = cls.check_prerequisites

    def check_prerequisites(self, *args, **kw):
        """An elastic support holds the part: FreeCAD counts only its fixed, displacement and rigid body
        constraints, and would stop the run ("No mechanical boundary conditions")."""
        message = check0(self, *args, **kw)
        try:
            a = self.analysis
            if message and any(is_elastic(o) and not getattr(o, "Suppressed", False) for o in a.Group):
                message = "".join(line for line in message.splitlines(True) if "No mechanical boundary conditions" not in line)
        except Exception as _fw_err:
            _fw_log("simroutes.py:prereq", _fw_err)
        return message

    cls.write_inp_file = write_inp_file
    cls.check_prerequisites = check_prerequisites
    cls._fw_elastic = True
    return True


# --------------------------------------------------------------------------- GUI
if Gui is not None:

    def _study():
        doc = App.ActiveDocument
        return _simpms().active_study(doc) if doc is not None else None

    def _tell(title, text):
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), title, text)

    def _units_combo(name, items, current):
        w = QtWidgets.QComboBox()
        w.setObjectName(name)
        w.addItems(list(items))
        if current in items:
            w.setCurrentText(current)
        return w

    def _value(name, value, dec=6, hi=1e15):
        w = QtWidgets.QDoubleSpinBox()
        w.setObjectName(name)
        w.setRange(0.0, hi)
        w.setDecimals(dec)
        w.setValue(float(value))
        return w

    def _classes():
        sp = _simpms()
        sx = sp.sx

        class ElasticPM(sp._PM):
            PM = ELASTIC

            def __init__(self, doc, edit=None):
                super().__init__(doc, edit)
                k = sp.kept(edit) if edit is not None else {}
                if edit is not None and k.get("kind") != ELASTIC:        # one FreeCAD made: its values, in N/m
                    k = {"total": True, "unit": "N/m", "normal": float(edit.NormalStiffness.getValueAs("N/m")),
                         "shear": float(edit.TangentialStiffness.getValueAs("N/m"))}
                msg = sx._box("Message", None, self.PM)
                lab = QtWidgets.QLabel("Pick the faces that rest on a flexible foundation. Distributed: the stiffness "
                                       "of each unit of area; Total: of all the faces together.")
                lab.setWordWrap(True)
                QtWidgets.QVBoxLayout(msg).addWidget(lab)
                typ = sx._box("Type")
                tl = QtWidgets.QVBoxLayout(typ)
                self.faces = sx._PickList("SWSimElasticFaces")
                tl.addWidget(self.faces)
                stiff = sx._box("Stiffness")
                form = QtWidgets.QFormLayout(stiff)
                row = QtWidgets.QHBoxLayout()
                self.dist = QtWidgets.QRadioButton("Distributed")
                self.dist.setObjectName("SWSimElasticDistributed")
                self.total = QtWidgets.QRadioButton("Total")
                self.total.setObjectName("SWSimElasticTotal")
                (self.total if k.get("total") else self.dist).setChecked(True)
                row.addWidget(self.dist)
                row.addWidget(self.total)
                form.addRow(row)
                self.unit = QtWidgets.QComboBox()
                self.unit.setObjectName("SWSimElasticUnit")
                form.addRow("Units:", self.unit)
                self.normal = _value("SWSimElasticNormal", k.get("normal", 0.0))
                self.shear = _value("SWSimElasticShear", k.get("shear", 0.0))
                form.addRow("Normal:", self.normal)
                form.addRow("Shear:", self.shear)
                self._units(k.get("unit"))
                self.dist.toggled.connect(lambda *_: self._units(None))
                self.boxes = [self.faces]
                self.form = [msg, typ, stiff]
                if edit is not None:
                    for _o, subs in edit.References:
                        self.faces.addItems(list(subs))
                self._start()

            def _units(self, current):
                items = list(TOTAL_UNITS if self.total.isChecked() else DISTRIBUTED_UNITS)
                self.unit.blockSignals(True)
                self.unit.clear()
                self.unit.addItems(items)
                self.unit.setCurrentText(current if current in items else items[0])
                self.unit.blockSignals(False)

            def apply(self):
                return add_elastic(self.doc, self.a, self.obj, self.faces.values(), self.normal.value(), self.shear.value(),
                                   self.unit.currentText(), self.total.isChecked(), self.edit)

        class ShellPM(sp._PM):
            PM = "Shell Definition"

            def __init__(self, doc, edit=None):
                super().__init__(doc, edit)
                k = sp.kept(edit) if edit is not None else {}
                if edit is not None and k.get("kind") != SHELL:
                    k = {"thickness": float(edit.Thickness.getValueAs("mm")), "unit": "mm",
                         "offset": next((n for n, v in SHELL_OFFSETS.items() if abs(v - edit.Offset) < 1e-9), "Middle surface")}
                msg = sx._box("Message", None, self.PM)
                lab = QtWidgets.QLabel("Pick the faces (of a surface body) the shell covers, then its thickness.")
                lab.setWordWrap(True)
                QtWidgets.QVBoxLayout(msg).addWidget(lab)
                typ = sx._box("Type")
                form = QtWidgets.QFormLayout(typ)
                self.faces = sx._PickList("SWSimShellFaces")
                form.addRow(self.faces)
                self.unit = _units_combo("SWSimShellUnit", LENGTH_UNITS, k.get("unit", "mm"))
                self.thick = _value("SWSimShellThickness", k.get("thickness", 1.0), dec=4, hi=1e6)
                form.addRow("Units:", self.unit)
                form.addRow("Thickness:", self.thick)
                off = sx._box("Offset")
                ol = QtWidgets.QVBoxLayout(off)
                self.offsets = []
                for i, name in enumerate(SHELL_OFFSETS):
                    b = QtWidgets.QRadioButton(name)
                    b.setObjectName("SWSimShellOffset%d" % i)
                    b.setChecked(name == k.get("offset", "Middle surface"))
                    ol.addWidget(b)
                    self.offsets.append(b)
                self.boxes = [self.faces]
                self.form = [msg, typ, off]
                if edit is not None:
                    for _o, subs in edit.References:
                        self.faces.addItems(list(subs))
                self._start()

            def apply(self):
                offset = next(b.text() for b in self.offsets if b.isChecked())
                return add_shell(self.doc, self.a, self.obj, self.faces.values(), self.thick.value(),
                                 self.unit.currentText(), offset, self.edit)

        class BeamPM(sp._PM):
            PM = "Apply/Edit Beam"

            def __init__(self, doc, edit=None):
                super().__init__(doc, edit)
                k = sp.kept(edit) if edit is not None else {}
                if edit is not None and k.get("kind") != BEAM:
                    sec = str(edit.SectionType)
                    k = {"section": sec, "unit": "mm",
                         "sizes": [float(getattr(edit, p).getValueAs("mm")) for _l, p in SECTIONS.get(sec, ())]}
                msg = sx._box("Message", None, self.PM)
                lab = QtWidgets.QLabel("Pick the edges (of a wire or sketch) the beam runs along, then its section.")
                lab.setWordWrap(True)
                QtWidgets.QVBoxLayout(msg).addWidget(lab)
                sel = sx._box("Selected Beams")
                QtWidgets.QVBoxLayout(sel)
                self.edges = sx._PickList("SWSimBeamEdges")
                sel.layout().addWidget(self.edges)
                secbox = sx._box("Section")
                form = QtWidgets.QFormLayout(secbox)
                self.section = _units_combo("SWSimBeamSection", SECTIONS, k.get("section", "Rectangular"))
                self.unit = _units_combo("SWSimBeamUnit", LENGTH_UNITS, k.get("unit", "mm"))
                form.addRow("Shape:", self.section)
                form.addRow("Units:", self.unit)
                self.size_rows = []
                defaults = {"Rectangular": [10.0, 25.0], "Circular": [25.0], "Pipe": [25.0, 2.0], "Elliptical": [10.0, 25.0],
                            "Box": [10.0, 25.0, 2.0, 2.0, 2.0, 2.0]}
                self.values = {}
                for sec, names in SECTIONS.items():
                    vals = k.get("sizes") if k.get("section") == sec and k.get("sizes") else defaults[sec]
                    for i, (label, _p) in enumerate(names):
                        w = _value("SWSimBeam%s%d" % (sec, i), vals[i] if i < len(vals) else 1.0, dec=4, hi=1e6)
                        lab_w = QtWidgets.QLabel(label + ":")
                        form.addRow(lab_w, w)
                        self.size_rows.append((sec, lab_w, w))
                        self.values.setdefault(sec, []).append(w)
                self.section.currentTextChanged.connect(lambda *_: self._sizes())
                self._sizes()
                self.boxes = [self.edges]
                self.form = [msg, sel, secbox]
                if edit is not None:
                    for _o, subs in edit.References:
                        self.edges.addItems(list(subs))
                self._start()

            def _sizes(self):
                sec = self.section.currentText()
                for s, lab_w, w in self.size_rows:          # only the chosen shape's sizes show (no dead boxes)
                    lab_w.setVisible(s == sec)
                    w.setVisible(s == sec)

            def _picked(self, name, sub):
                last = (sub or "").split(".")[-1]
                if self.current is self.edges and last.startswith("Edge"):
                    self.edges.toggle(last)
                try:
                    Gui.Selection.clearSelection()
                except Exception as _fw_err:
                    _fw_log("simroutes.py:pick", _fw_err)

            def _start(self):
                super()._start()
                for i in range(self.edges.count() - 1, -1, -1):          # faces picked before opening are not edges
                    if not self.edges.item(i).text().startswith("Edge"):
                        self.edges.takeItem(i)

            def preview(self):
                return None

            def apply(self):
                sec = self.section.currentText()
                return add_beam(self.doc, self.a, self.obj, self.edges.values(), sec,
                                [w.value() for w in self.values[sec]], self.unit.currentText(), self.edit)

        return ElasticPM, ShellPM, BeamPM

    CLASSES = {}

    def pm_class(name):
        if not CLASSES:
            CLASSES.update(zip(("ElasticPM", "ShellPM", "BeamPM"), _classes()))
        return CLASSES[name]

    def open_elastic(edit=None):
        return _simpms().show(pm_class("ElasticPM")(App.ActiveDocument if edit is None else edit.Document, edit=edit))

    def open_shell(edit=None):
        return _simpms().show(pm_class("ShellPM")(App.ActiveDocument if edit is None else edit.Document, edit=edit))

    def open_beam(edit=None):
        return _simpms().show(pm_class("BeamPM")(App.ActiveDocument if edit is None else edit.Document, edit=edit))

    def open_connector(kind):
        from . import asmsim
        return asmsim.open_connector(None, kind)

    def solver_control():
        from . import simtypes
        return simtypes.open_properties(_study())

    def shown_plot(a):
        """The plot shown on the model, else the study's first plot (shown first): None without results."""
        from . import simplots
        if simplots.SHOWN.get("a") is a and simplots.SHOWN.get("name"):
            return simplots.SHOWN["name"]
        for p in simplots.plots(a):
            try:
                simplots.show(a, p["name"])
                return p["name"]
            except Exception as _fw_err:
                _fw_log("simroutes.py:show", _fw_err)
        return None

    def _on_plot(title, run):
        a = _study()
        name = shown_plot(a) if a is not None else None
        if name is None:
            _tell(title, "%s works on a result plot. Run the study, then show a plot (double-click it under Results)." % title)
            return None
        return run(a, name)

    def section_clipping():
        from . import simplotview
        return _on_plot("Section Clipping", simplotview.section_clipping)

    def iso_clipping():
        from . import simplotview
        return _on_plot("Iso Clipping", simplotview.iso_clipping)

    def deformed_result():
        from . import simtree
        return _on_plot("Deformed Result", simtree._toggle_deformed)

    class _Cmd:
        def __init__(self, text, tip, run):
            self.text, self.tip, self.run = text, tip, run

        def GetResources(self):
            return {"MenuText": self.text, "ToolTip": self.tip}

        def IsActive(self):
            return _study() is not None

        def Activated(self):
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
            self.run()

    COMMANDS = {
        "SIM_Elastic": ("SWStyle_SimElastic", _Cmd("Elastic Support", "A flexible foundation under faces: normal and "
                                                   "shear stiffness.", open_elastic)),
        "SIM_Spring": ("SWStyle_SimSpring", _Cmd("Spring", "A spring between faces of two parts.",
                                                 lambda: open_connector("Spring"))),
        "SIM_Rigid": ("SWStyle_SimRigid", _Cmd("Rigid Connection", "Two faces of two parts joined rigidly.",
                                               lambda: open_connector("Rigid"))),
        "SIM_Shell": ("SWStyle_SimShell", _Cmd("Shell Manager", "Shell thickness for faces of a surface body.",
                                               open_shell)),
        "SIM_Beam": ("SWStyle_SimBeam", _Cmd("Beam", "A beam section for edges of a wire.", open_beam)),
        "SIM_SolverControl": ("SWStyle_SimSolverControl", _Cmd("Solver Control", "The study's Properties: the solver "
                                                               "and its options.", solver_control)),
        "SIM_Section": ("SWStyle_SimSection", _Cmd("Section Clipping", "Cuts the plot shown with planes.",
                                                   section_clipping)),
        "SIM_IsoClip": ("SWStyle_SimIsoClip", _Cmd("Iso Clipping", "Shows only where the plot shown passes values.",
                                                   iso_clipping)),
        "SIM_PlotTools": ("SWStyle_SimPlotTools", _Cmd("Plot Tools", "Section Clipping on the plot shown (the arrow: "
                                                       "Iso Clipping, Probe, line plots).", section_clipping)),
        "SIM_Deform": ("SWStyle_SimDeform", _Cmd("Deformed Result", "The plot shown on its deformed shape, or back on "
                                                 "the model.", deformed_result)),
    }

    def edit_definition(o):
        """Edit Definition of an elastic support, shell or beam: its PM filled in (None: not one of them)."""
        if is_elastic(o):
            return open_elastic(o)
        if is_shell(o):
            return open_shell(o)
        if is_beam(o):
            return open_beam(o)
        return None

    def _hook_edit():
        from . import simtree
        if getattr(simtree.edit, "_fw_routes", False):
            return
        edit0 = simtree.edit

        def edit(obj):
            try:
                if edit_definition(obj) is not None:
                    return None
            except Exception as _fw_err:
                _fw_log("simroutes.py:edit", _fw_err)
            return edit0(obj)

        edit._fw_routes = True
        simtree.edit = edit

    def install():
        """Our commands first on each routed key, FreeCAD's after them; Edit Definition and the solver input."""
        from . import catalog, simtree
        have = set(Gui.listCommands())
        done = 0
        for key in ROUTES:
            simtree.CONTEXT.pop(key, None)                  # no picking command first: ours needs none
            name, cmd = COMMANDS[key]
            if name not in have:
                Gui.addCommand(name, cmd)
            c = catalog.BY_KEY.get(key)
            if c is None:
                continue
            rest = [n for n in c.natives if n != name and not n.startswith("SWStyle_SimCtx_")]
            c.natives = (name,) + tuple(rest)
            done += 1
        _hook_edit()
        _patch_ccx()
        _hook_recover()
        return done


    # study" (off by default): the document's recovery data (recovery.write, what FreeCAD's own saver writes and its
    # recovery at startup reads) is written once a mesh or a run has finished
    RECOVER_TEXT = "Save auto-recover info after meshing and after running a simulation study"

    def recover_after(doc):
        """Writes doc's auto-recover data when the option is on. The file written, or None."""
        try:
            from . import optionspages
            if doc is None or not optionspages.stored("Backup/Recover", RECOVER_TEXT, False):
                return None
            from . import recovery
            return recovery.write(doc)
        except Exception as _fw_err:
            _fw_log("simroutes.py:recover", _fw_err)
            return None

    def _hook_recover():
        from . import addintabs, simpms
        if not getattr(addintabs.run_study, "_fw_recover", False):
            run0 = addintabs.run_study

            def run_study(analysis, *args, **kw):
                try:
                    return run0(analysis, *args, **kw)
                finally:
                    recover_after(getattr(analysis, "Document", None))

            run_study._fw_recover = True
            addintabs.run_study = run_study
        if not getattr(simpms._gmsh, "_fw_recover", False):
            mesh0 = simpms._gmsh

            def _gmsh(a, m):
                err = mesh0(a, m)
                if not err:
                    recover_after(getattr(m, "Document", None))
                return err

            _gmsh._fw_recover = True
            simpms._gmsh = _gmsh
