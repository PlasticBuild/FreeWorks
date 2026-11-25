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

import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import evaluate
from .evaluate import ReportWindow, _f

Qt = QtCore.Qt
COMMANDS = {}


def _asm():
    from . import asmcore
    return asmcore.assembly_of()


def _suppressed(c):
    """The component suppressed, or the subassembly's own component its copy here links."""
    if getattr(c, "FwComponentSuppressed", False):
        return True
    src = getattr(c, "LinkedObject", None)
    return src is not None and src is not c and bool(getattr(src, "FwComponentSuppressed", False))


def _comps(asm, subassemblies=False):
    """The units looked at: components, or with subassemblies off the parts inside them."""
    from . import asmcore
    out = []
    for c in asmcore.components(asm):
        if _suppressed(c):
            continue
        if not subassemblies and asmcore.is_subassembly(c):
            out.extend(_sub_parts(c))
        else:
            out.append(c)
    return out


def _sub_parts(sub):
    from . import asmcore
    out = []
    for c in asmcore.sub_components(sub):
        if _suppressed(c):
            continue        # a suppressed part of the subassembly is not looked at
        if asmcore.is_subassembly(c):
            out.extend(_sub_parts(c))
        else:
            out.append(c)
    return out


def _shape(comp):
    """The component's shape where the assembly has it; an empty shape when it has none (a
    new part not modelled yet, a component whose file is missing)."""
    import Part
    try:
        from . import asmtools
        shp = asmtools._global_shape(comp)
        if shp is not None:
            return shp
    except Exception as _fw_err:
        _fw_log("asmevaluate.py:88", _fw_err)
    try:
        return comp.Shape.copy()
    except Exception:
        return Part.Shape()


def _label(comp):
    from . import asmexplode
    try:
        return asmexplode.display_name(comp)
    except Exception:
        return comp.Label


def _pick(comps):
    out = []
    for c in comps:
        out.append((c.Document.Name, c.Name, ""))
    return out


# ============================================================================= Clearance Verification
def clearances(asm, picked=None, minimum=1.0, mode="all", ignore_equal=False, subassemblies=True):
    """[(a, b, clearance)] under minimum, smallest first. mode: 'all' (every pair of the
    selection, or of the assembly), 'rest' (each picked against the rest of the assembly)."""
    units = _comps(asm, subassemblies)
    picked = [u for u in (picked or []) if u in units] or None
    if picked and mode == "rest":
        pairs = [(a, b) for a in picked for b in units if b not in picked]
    else:
        pool = picked if picked and len(picked) > 1 else units
        pairs = [(pool[i], pool[j]) for i in range(len(pool)) for j in range(i + 1, len(pool))]
    shapes, boxes = {}, {}
    out = []

    def placed(u):      # each component's placed shape and box once (300 parts: 45,000 pairs)
        key = u.Name + u.Label
        if key not in shapes:
            shapes[key] = s = _shape(u)
            try:
                box = App.BoundBox(s.BoundBox) if not s.isNull() else None
                if box is not None:
                    box.enlarge(minimum + 1e-6)
            except Exception:
                box = None
            boxes[key] = (box, None if s.isNull() else s.BoundBox)
        return shapes[key], boxes[key]
    for a, b in pairs:
        sa, (box, _ab) = placed(a)
        sb, (_bb, bbox) = placed(b)
        try:
            if box is None or bbox is None or not box.intersect(bbox):
                continue
            d = sa.distToShape(sb)[0]
        except Exception:
            continue
        if d < 1e-7:
            continue        # touching or overlapping: Interference Detection's business
        if d < minimum - 1e-9 or (not ignore_equal and abs(d - minimum) <= 1e-9):
            out.append((a, b, d))
    out.sort(key=lambda r: r[2])
    return out


class ClearanceWindow(ReportWindow):
    ""


    def __init__(self):
        super().__init__("Clearance Verification", ["Components", "Clearance"])
        self.recalc.setText("Calculate")
        self.mode = QtWidgets.QComboBox()
        self.mode.setObjectName("SWClearanceMode")
        self.mode.addItem("Selected items only", "all")
        self.mode.addItem("Selected items and the rest of the assembly", "rest")
        self.minimum = QtWidgets.QDoubleSpinBox()
        self.minimum.setObjectName("SWClearanceMinimum")
        self.minimum.setRange(0.0, 1e5)
        self.minimum.setDecimals(2)
        self.minimum.setSuffix(" mm")
        self.minimum.setValue(1.0)
        self.ignore = QtWidgets.QCheckBox("Ignore clearance equal to specified value")
        self.subs = QtWidgets.QCheckBox("Treat subassemblies as components")
        self.subs.setChecked(True)
        self.options.addWidget(self.mode)
        self.options.addWidget(QtWidgets.QLabel("Minimum:"))
        self.options.addWidget(self.minimum)
        lay2 = QtWidgets.QHBoxLayout()
        lay2.addWidget(self.ignore)
        lay2.addWidget(self.subs)
        lay2.addStretch(1)
        self.layout_.insertLayout(1, lay2)
        self.picked = [o for o in Gui.Selection.getSelection()]
        self.found = []

    def compute(self):
        asm = _asm()
        if asm is None:
            self.set_rows([])
            self.summary.setText("Open an assembly first.")
            return
        from . import asmcore
        comps = asmcore.components(asm)
        picked = [o for o in self.picked if o in comps]
        self.found = clearances(asm, picked, self.minimum.value(), self.mode.currentData(),
                                self.ignore.isChecked(), self.subs.isChecked())
        self.set_rows([(("%s - %s" % (_label(a), _label(b)), _f(d, 3) + " mm"), _pick([a, b]))
                       for a, b, d in self.found])
        self.summary.setText("%d clearance%s under %s mm" % (
            len(self.found), "" if len(self.found) == 1 else "s", _f(self.minimum.value(), 2))
            if self.found else "No clearances under %s mm" % _f(self.minimum.value(), 2))


def clearance_verification():
    ""

    from . import asmevalpm
    return asmevalpm.clearance_verification()


# ============================================================================= Hole Alignment
def _holes(comp):
    from . import toolbox
    try:
        return [(n, r, c, a) for n, r, c, a in toolbox.hole_faces(comp)]
    except Exception:
        return []


def misaligned_holes(asm, deviation=0.5, subassemblies=True):
    """[(compA, faceA, compB, faceB, deviation)] for holes in different components on near
    parallel axes, overlapping along them or touching end to end, whose centres are apart by
    more than 0 and less than deviation."""
    from . import toolbox
    units = _comps(asm, subassemblies)
    holes = []
    for comp in units:
        if toolbox.is_fastener(comp):
            continue
        shp = _shape(comp)
        for name, r, c, a in _holes(comp):
            f = shp.getElement(name)
            zs = [v.Point.dot(a) for v in f.Vertexes] or [c.dot(a)]
            holes.append((comp, name, r, c, a, min(zs), max(zs)))
    out = []
    for i in range(len(holes)):
        for j in range(i + 1, len(holes)):
            ca, na, ra, pa, aa, lo_a, hi_a = holes[i]
            cb, nb, rb, pb, ab, lo_b, hi_b = holes[j]
            if ca is cb or abs(abs(aa.dot(ab)) - 1.0) > 1e-4:
                continue
            sign = 1.0 if aa.dot(ab) > 0 else -1.0
            lo_b2, hi_b2 = (lo_b, hi_b) if sign > 0 else (-hi_b, -lo_b)
            if lo_b2 > hi_a + 1e-4 or hi_b2 < lo_a - 1e-4:
                continue        # not end to end along the axis
            d = pb - pa
            off = (d - aa * d.dot(aa)).Length
            if 1e-6 < off < deviation:
                out.append((ca, na, cb, nb, off))
    out.sort(key=lambda r: -r[4])
    return out


class HoleAlignmentWindow(ReportWindow):
    ""

    def __init__(self):
        super().__init__("Hole Alignment", ["Holes", "Deviation"])
        self.recalc.setText("Calculate")
        self.deviation = QtWidgets.QDoubleSpinBox()
        self.deviation.setObjectName("SWHoleAlignmentDeviation")
        self.deviation.setRange(0.0, 1e4)
        self.deviation.setDecimals(3)
        self.deviation.setSuffix(" mm")
        self.deviation.setValue(1.0)
        self.subs = QtWidgets.QCheckBox("Treat subassemblies as components")
        self.subs.setChecked(True)
        self.options.addWidget(QtWidgets.QLabel("Hole center deviation:"))
        self.options.addWidget(self.deviation)
        self.options.addWidget(self.subs)
        self.found = []

    def compute(self):
        asm = _asm()
        if asm is None:
            self.set_rows([])
            self.summary.setText("Open an assembly first.")
            return
        self.found = misaligned_holes(asm, self.deviation.value(), self.subs.isChecked())
        self.set_rows([(("%s %s - %s %s" % (_label(a), fa, _label(b), fb), _f(d, 3) + " mm"),
                        [(a.Document.Name, a.Name, fa), (b.Document.Name, b.Name, fb)])
                       for a, fa, b, fb, d in self.found])
        self.summary.setText("%d misaligned hole%s" % (len(self.found), "" if len(self.found) == 1 else "s")
                             if self.found else "No misaligned holes found")


def hole_alignment():
    ""
    from . import asmevalpm
    return asmevalpm.hole_alignment()


# ============================================================================= Assembly Visualization
PROPERTIES = ("Mass", "Volume", "Surface Area", "Bodies", "Faces", "Triangles", "Rebuild Time")


def _value(comp, prop, density=1000.0):
    shp = _shape(comp)
    if shp.isNull() and prop != "Rebuild Time":
        return 0 if prop in ("Bodies", "Faces", "Triangles") else 0.0
    if prop == "Volume":
        return shp.Volume
    if prop == "Mass":
        over = part_mass_override(comp)
        if over:
            return over                                           # the part's Override Mass Properties
        return shp.Volume * _density(comp, density) * 1e-6       # g with kg/m^3
    if prop == "Surface Area":
        return shp.Area
    if prop == "Bodies":
        return len(shp.Solids)
    if prop == "Faces":
        return len(shp.Faces)
    if prop == "Triangles":
        return _triangles(comp, shp)
    if prop == "Rebuild Time":
        part = comp.getLinkedObject(True)
        doc = getattr(part, "Document", None)
        if doc is None:
            return 0.0
        t0 = time.perf_counter()
        for o in getattr(part, "Group", []) or [part]:
            if hasattr(o, "recompute"):
                o.touch()
        doc.recompute()
        return time.perf_counter() - t0
    return 0.0


def part_mass_override(comp):
    """The mass (g) the component's part overrides (its Override Mass Properties), or None."""
    try:
        from . import massprops
        part = comp.getLinkedObject(True)
        doc = getattr(part, "Document", None)
        if doc is None or doc is comp.Document:
            return None
        m = massprops.overrides(doc).get("mass")
        return float(m) if m else None
    except Exception:
        return None


def _density(comp, default):
    """kg/m^3 from the part's material (its Material row, Shape material, or a Material card)."""
    part = comp.getLinkedObject(True)
    try:
        from . import material
        doc = getattr(part, "Document", None)
        value = material.current(doc)[0] if doc is not None and doc is not comp.Document else None
        if value:
            return float(value)
    except Exception as _fw_err:
        _fw_log("asmevaluate.py:352", _fw_err)
    for obj in (part, getattr(part, "Tip", None)):
        mat = getattr(obj, "ShapeMaterial", None)
        try:
            d = mat.PhysicalProperties.get("Density") if mat is not None else None
            if d:
                return float(App.Units.Quantity(d).getValueAs("kg/m^3"))
        except Exception as _fw_err:
            _fw_log("asmevaluate.py:360", _fw_err)
    return default


def visualization(asm, prop="Mass"):
    ""

    from . import asmcore
    rows = {}
    for c in _comps(asm, subassemblies=False):
        target = c.getLinkedObject(True)
        doc = getattr(target, "Document", None)
        key = doc.Label if doc is not None and doc is not asm.Document else target.Label
        row = rows.setdefault(key, [key, 0, None, []])
        row[1] += 1
        row[3].append(c)
        if row[2] is None:
            row[2] = _value(c, prop)
    out = [tuple(r) for r in rows.values()]
    out.sort(key=lambda r: -float(r[2] or 0))
    return out


def ramp(t):
    ""
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        u = t / 0.5
        return (0.0, u, 1.0 - u)
    u = (t - 0.5) / 0.5
    return (u, 1.0 - u, 0.0)


class VisualizationWindow(ReportWindow):
    ""


    def __init__(self):
        super().__init__("Assembly Visualization", ["File Name", "Quantity", "Mass"])
        self.recalc.setText("Refresh")
        self.prop = QtWidgets.QComboBox()
        self.prop.setObjectName("SWAssemblyVisualizationProperty")
        self.prop.addItems(PROPERTIES)
        self.prop.currentIndexChanged.connect(lambda *_: self.refresh())
        self.colours = QtWidgets.QCheckBox("Show colours")
        self.colours.setChecked(True)
        self.colours.toggled.connect(lambda *_: self.refresh())
        self.options.addWidget(QtWidgets.QLabel("Property:"))
        self.options.addWidget(self.prop)
        self.options.addWidget(self.colours)
        self.saved = {}
        self.rows_ = []

    def compute(self):
        asm = _asm()
        if asm is None:
            self.set_rows([])
            self.summary.setText("Open an assembly first.")
            return
        prop = self.prop.currentText()
        self.table.headerItem().setText(2, prop)
        self.rows_ = visualization(asm, prop)
        unit = {"Mass": " g", "Volume": " mm^3", "Surface Area": " mm^2", "Rebuild Time": " s"}.get(prop, "")
        self.set_rows([((name, q, (_f(v, 3) if isinstance(v, float) else v) + unit if unit else v), _pick(cs))
                       for name, q, v, cs in self.rows_])
        self._paint()
        self.summary.setText("%d parts, %d components" % (len(self.rows_), sum(r[1] for r in self.rows_)))

    def _paint(self):
        self.cleanup()
        if not self.colours.isChecked() or not self.rows_:
            return
        vals = [float(r[2] or 0) for r in self.rows_]
        lo, hi = min(vals), max(vals)
        for name, q, v, cs in self.rows_:
            t = 0.5 if hi - lo < 1e-12 else (float(v or 0) - lo) / (hi - lo)
            colour = ramp(t)
            for c in cs:
                vo = getattr(c, "ViewObject", None)
                if vo is None or not hasattr(vo, "OverrideMaterial"):
                    continue
                try:
                    self.saved[c] = (vo.OverrideMaterial, vo.ShapeMaterial)
                    mat = App.Material()
                    mat.DiffuseColor = colour + (0.0,)
                    vo.ShapeMaterial = mat
                    vo.OverrideMaterial = True
                except Exception as _fw_err:
                    _fw_log("asmevaluate.py:448", _fw_err)

    def colour_of(self, comp):
        vo = comp.ViewObject
        if not getattr(vo, "OverrideMaterial", False):
            return None
        return tuple(vo.ShapeMaterial.DiffuseColor[:3])

    def cleanup(self):
        for c, (override, mat) in list(self.saved.items()):
            try:
                vo = c.ViewObject
                if mat is not None:
                    vo.ShapeMaterial = mat
                vo.OverrideMaterial = override
            except Exception as _fw_err:
                _fw_log("asmevaluate.py:464", _fw_err)
        self.saved = {}


def assembly_visualization():
    ""
    from . import asmvistab
    tab = asmvistab.open_tab()
    return tab if tab is not None else evaluate._show(VisualizationWindow)


# ============================================================================= MateXpert
_TRIANGLES = {}     # the part's own shape -> its triangle count (where it is placed doesn't change it)


def _triangles(comp, shp):
    key = None
    try:
        part = comp.getLinkedObject(True)
        key = (part.Document.Name, part.Name, part.Shape.hashCode())
        if key in _TRIANGLES:
            return _TRIANGLES[key]
    except Exception:
        key = None
    try:
        n = sum(len(f.tessellate(0.5)[1]) for f in shp.Faces)
    except Exception:
        n = 0
    if key is not None:
        _TRIANGLES[key] = n
    return n


_PROBLEMS = {}      # assembly -> (its change count, the mate problems found then)


def mate_problems(asm, solve=True):
    ""




    from . import asmcore, asmgen
    tag = (asm.Document.Name, asm.Name, bool(solve))
    g = asmgen.gen(asm.Document)
    kept = _PROBLEMS.get(tag)
    if kept is not None and g >= 0 and kept[0] == g:
        try:
            if all(j.isValid() for j, _c, _w in kept[1]):
                return list(kept[1])
        except Exception as _fw_err:
            _fw_log("asmevaluate.py:515", _fw_err)
    out = _mate_problems(asm, solve)
    _PROBLEMS[tag] = (asmgen.gen(asm.Document), out)
    return list(out)


def _mate_problems(asm, solve=True):
    from . import asmcore
    if solve:
        asmcore.solve(asm)
    out = []
    for j in asmcore.mates(asm):
        err = asmcore.mate_error(j)
        if not err:
            if getattr(j, "Suppressed", False):
                continue
            try:
                if asmcore.satisfied(j):
                    continue
            except Exception:
                continue
        comps = [r[0] for r in (getattr(j, "Reference1", None), getattr(j, "Reference2", None)) if r]
        out.append((j, comps, "over defines the assembly" if err else "is not satisfied"))
    return out


def diagnose(asm):
    ""

    culprits = [p[0] for p in mate_problems(asm) if getattr(p[0], "Suppressed", False)]
    live = [p[0] for p in mate_problems(asm) if not getattr(p[0], "Suppressed", False)]
    for j in reversed(live):
        j.Suppressed = True
        culprits.append(j)
        if not [p for p in mate_problems(asm) if not getattr(p[0], "Suppressed", False)]:
            break
    return culprits


class MateXpertWindow(ReportWindow):
    ""

    def __init__(self):
        super().__init__("MateXpert", ["Mate", "Components", "Problem"])
        self.recalc.setText("Analyze Problem")
        self.diag = QtWidgets.QPushButton("Diagnose")
        self.diag.setObjectName("SWMateXpertDiagnose")
        self.diag.clicked.connect(self.do_diagnose)
        self.options.addWidget(self.diag)
        self.options.addStretch(1)
        self.found = []

    def compute(self):
        asm = _asm()
        if asm is None:
            self.set_rows([])
            self.summary.setText("Open an assembly first.")
            return
        self.found = mate_problems(asm)
        self.set_rows([((j.Label, ", ".join(_label(c) for c in cs), why), [(j.Document.Name, j.Name, "")])
                       for j, cs, why in self.found])
        self.summary.setText("All mates are satisfied." if not self.found else
                             "%d mate%s not satisfied" % (len(self.found), "" if len(self.found) == 1 else "s"))

    def do_diagnose(self):
        asm = _asm()
        if asm is None:
            return []
        doc = asm.Document
        doc.openTransaction("MateXpert Diagnose")
        try:
            off = diagnose(asm)
        finally:
            doc.commitTransaction()
        self.compute()
        self.summary.setText("Suppressed to solve: %s" % (", ".join(j.Label for j in off) or "nothing"))
        return off


def matexpert():
    ""
    from . import asmevalpm
    return asmevalpm.matexpert()


# ============================================================================= Performance Evaluation (AssemblyXpert)
def statistics(asm):
    from . import asmcore
    comps = asmcore.components(asm)
    allc = []

    def walk(cs, top=True):
        for c in cs:
            allc.append((c, top))
            if asmcore.is_subassembly(c):
                walk(asmcore.sub_components(c), False)
    walk(comps)
    parts = [c for c, _ in allc if not asmcore.is_subassembly(c)]
    subs = [c for c, _ in allc if asmcore.is_subassembly(c)]
    unique = {getattr(c.getLinkedObject(True), "Document", None) and c.getLinkedObject(True).Document.Name + c.getLinkedObject(True).Name
              for c in parts}
    tris = 0
    for c in parts:
        try:
            tris += _value(c, "Triangles")
        except Exception as _fw_err:
            _fw_log("asmevaluate.py:621", _fw_err)
    mates = asmcore.mates(asm)
    return {
        "Total components": len(allc),
        "Parts": len(parts),
        "Unique parts": len(unique),
        "Subassemblies": len(subs),
        "Flexible subassemblies": sum(1 for c in subs if asmcore.is_flexible(c)),
        "Top-level components": len(comps),
        "Suppressed components": sum(1 for c, _ in allc if getattr(c, "FwComponentSuppressed", False)),
        "Lightweight components": sum(1 for c, _ in allc if getattr(c, "FwLightweight", False)),
        "Top-level mates": len(mates),
        "Mates not satisfied": len(mate_problems(asm, solve=False)),
        "Graphics triangles": tris,
    }


ADVICE = (
    ("Flexible subassemblies", lambda v: v > 0, "Flexible subassemblies are solved with the top assembly: make them rigid where they need not move."),
    ("Mates not satisfied", lambda v: v > 0, "Some mates do not hold: run MateXpert."),
    ("Top-level mates", lambda v: v > 200, "Many top-level mates: group parts into subassemblies."),
    ("Graphics triangles", lambda v: v > 2000000, "Many graphics triangles: use SpeedPak or Lightweight for big components."),
)


def _all_components(asm):
    """[(component, depth)] every component, subassemblies' ones too (depth 1 = top level)."""
    from . import asmcore
    out = []

    def walk(cs, d):
        for c in cs:
            out.append((c, d))
            if asmcore.is_subassembly(c):
                walk(asmcore.sub_components(c), d + 1)
    walk(asmcore.components(asm), 1)
    return out


def more_statistics(asm):
    ""
    from . import asmcore
    allc = _all_components(asm)
    subs = [c for c, _d in allc if asmcore.is_subassembly(c)]
    usubs = {(getattr(getattr(c, "LinkedObject", None), "Document", None) or c.Document).Name for c in subs}
    env = 0
    tb = 0
    try:
        from . import asminsert
        env = sum(1 for c, _d in allc if asminsert.is_envelope(c))
    except Exception as _fw_err:
        _fw_log("asmevaluate.py:672", _fw_err)
    try:
        from . import toolbox
        for c, _d in allc:
            t = c.getLinkedObject(True)
            if t is not None and any(hasattr(o, toolbox.PROP) for o in t.Document.Objects):
                tb += 1
    except Exception as _fw_err:
        _fw_log("asmevaluate.py:680", _fw_err)
    bodies = 0
    for c, _d in allc:
        if asmcore.is_subassembly(c):
            continue
        try:
            bodies += len(_shape(c).Solids)
        except Exception as _fw_err:
            _fw_log("asmevaluate.py:688", _fw_err)
    sup = sum(1 for c, _d in allc if getattr(c, "FwComponentSuppressed", False))
    light = sum(1 for c, _d in allc if getattr(c, "FwLightweight", False))
    return {
        "Unique subassemblies": len(usubs),
        "Resolved components": len(allc) - sup - light,
        "Envelope components": env,
        "Toolbox components": tb,
        "Fixed top-level components": len(asmcore.grounded(asm)),
        "Deepest subassembly level": max([d for _c, d in allc] or [0]),
        "Bodies": bodies,
    }


LARGE_COUNT = 500
HEAVY_TRIANGLES = 500000
DETAILED_TRIANGLES = 5000


def xpert_checks(asm, stats=None):
    ""

    from . import asmcore
    stats = stats or statistics(asm)
    out = []
    try:
        verify = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Part/Boolean").GetBool("CheckModel", True)
    except Exception:
        verify = False
    out.append(("warning" if verify else "ok",
                "Verification on rebuild is on: rebuilds check every body and take longer." if verify else
                "Verification on rebuild is off.", [], "verify" if verify else ""))
    flex = [c for c, _d in _all_components(asm) if asmcore.is_subassembly(c) and asmcore.is_flexible(c)]
    out.append(("warning" if flex else "ok",
                "%d flexible subassembl%s: solved with the top assembly. Make them rigid where they need not move." %
                (len(flex), "y" if len(flex) == 1 else "ies") if flex else "No flexible subassemblies.", flex,
                "rigid" if flex else ""))
    bad = mate_problems(asm, solve=False)
    out.append(("warning" if bad else "ok", "%d mate%s not satisfied: run MateXpert." % (len(bad), "" if len(bad) == 1 else "s")
                if bad else "All mates are satisfied.", [], "matexpert" if bad else ""))
    heavy = []
    for c in _comps(asm, subassemblies=False):
        try:
            if _value(c, "Triangles") > HEAVY_TRIANGLES:
                heavy.append(c)
        except Exception as _fw_err:
            _fw_log("asmevaluate.py:734", _fw_err)
    out.append(("warning" if heavy else "ok", "%d component%s with many graphics triangles: use SpeedPak or Lightweight." %
                (len(heavy), "" if len(heavy) == 1 else "s") if heavy else "No component has too many graphics triangles.",
                heavy, ""))
    try:
        from . import asmlarge
        large_on = asmlarge.is_on()
    except Exception:
        large_on = True
    big = stats.get("Total components", 0) >= LARGE_COUNT
    out.append(("warning" if big and not large_on else "ok",
                "More than %d components and Large Assembly Mode is off." % LARGE_COUNT if big and not large_on else
                "Large Assembly Mode: not needed for this size." if not big else "Large Assembly Mode is on.", [],
                "large" if big and not large_on else ""))
    detailed = []
    for c in _comps(asm, subassemblies=False):
        try:
            if _value(c, "Triangles") > DETAILED_TRIANGLES:
                detailed.append(c)
        except Exception as _fw_err:
            _fw_log("asmevaluate.py:754", _fw_err)
    if detailed:
        out.append(("info", "%d part%s with more than 5,000 graphics triangles: open %s to simplify the geometry." %
                    (len(detailed), "" if len(detailed) == 1 else "s", "it" if len(detailed) == 1 else "them"),
                    detailed, "open"))
    stale = []
    try:
        from . import asmlight
        stale = [c for c in _comps(asm, subassemblies=False) if asmlight.out_of_date(c)]
    except Exception as _fw_err:
        _fw_log("asmevaluate.py:764", _fw_err)
    out.append(("warning" if stale else "ok",
                "%d out-of-date component%s: open the file to see what changed." % (len(stale), "" if len(stale) == 1 else "s")
                if stale else "No out-of-date components.", stale, "open" if stale else ""))
    many = stats.get("Top-level mates", 0) > 200
    out.append(("warning" if many else "ok", "Many top-level mates: group parts into subassemblies." if many else
                "Top-level mates: %d." % stats.get("Top-level mates", 0), [], ""))
    return out


def xpert_fix(asm, fix, comps):
    from . import asmcore
    if fix == "verify":
        App.ParamGet("User parameter:BaseApp/Preferences/Mod/Part/Boolean").SetBool("CheckModel", False)
        return True
    if fix == "rigid":
        for c in comps:
            asmcore.set_flexible(asm, c, False)
        asm.Document.recompute()
        return True
    if fix == "matexpert":
        _show_matexpert()
        return True
    if fix == "large":
        from . import asmlarge
        asmlarge.set_mode(True)
        return True
    if fix == "open":

        from . import asmmenu
        return bool(comps) and asmmenu.open_part(comps[0])
    return False


def open_time(asm):
    """The assembly's last open in this session: {total, stages, files} or None (not opened from a file)."""
    try:
        from . import asmloadprogress
        return asmloadprogress.OPENS.get(asm.Document.Name)
    except Exception:
        return None


def _show_matexpert():
    try:
        return matexpert()
    except Exception:
        return evaluate._show(MateXpertWindow)


MATE_TIME_LIMIT = 60    # at most this many mates are timed one by one (the first ones)


def mate_times(asm, limit=MATE_TIME_LIMIT):
    ""


    import UtilsAssembly
    from . import asmcore
    live = [j for j in asmcore.mates(asm) if not getattr(j, "Suppressed", False) and not asmcore.mate_error(j)]
    if not live:
        return []
    before = UtilsAssembly.saveAssemblyPartsPlacements(asm)

    def timed():
        t0 = time.perf_counter()
        try:
            asm.solve()
        except Exception as _fw_err:
            _fw_log("asmevaluate.py:833", _fw_err)
        UtilsAssembly.restoreAssemblyPartsPlacements(asm, before)
        return time.perf_counter() - t0
    out = []
    try:
        full = min(timed(), timed())
        for j in live[:limit]:
            try:
                j.Suppressed = True
                without = min(timed(), timed())
            finally:
                j.Suppressed = False
            out.append((j, max(0.0, full - without)))
    finally:
        UtilsAssembly.restoreAssemblyPartsPlacements(asm, before)
        try:
            for j in live:
                j.purgeTouched()
        except Exception as _fw_err:
            _fw_log("asmevaluate.py:852", _fw_err)
    out.sort(key=lambda t: -t[1])
    return out


def component_triangles(asm, top=10):
    """[(component, graphics triangles)] the components with the most, most first."""
    out = []
    for c in _comps(asm, subassemblies=False):
        try:
            out.append((c, int(_value(c, "Triangles"))))
        except Exception as _fw_err:
            _fw_log("asmevaluate.py:864", _fw_err)
    out.sort(key=lambda t: -t[1])
    return [t for t in out[:top] if t[1] > 0]


SECTIONS = ("Rebuild Performance", "Graphics Performance", "Mate Performance", "Settings Performance", "Statistics")
CHECK_SECTION = {"verify": "Settings Performance", "large": "Settings Performance", "rigid": "Mate Performance",
                 "matexpert": "Mate Performance"}


class AssemblyXpertWindow(ReportWindow):
    ""




    ICONS = {"warning": "warning", "ok": "ok", "info": "information"}

    def __init__(self):
        super().__init__("Performance Evaluation", ["Status", "Description"])
        self.recalc.setText("Refresh")
        self.table.setRootIsDecorated(True)
        self.fix_button = QtWidgets.QPushButton("Fix")
        self.fix_button.setObjectName("SWAssemblyXpertFix")
        self.fix_button.setVisible(False)
        self.fix_button.clicked.connect(self.fix_current)
        self.options.addStretch(1)
        self.options.addWidget(self.fix_button)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.itemSelectionChanged.disconnect()
        self.table.itemSelectionChanged.connect(self._picked_item)
        self.stats = {}
        self.checks = []

    def _row(self, parent, status, text, check=None, comps=()):
        it = QtWidgets.QTreeWidgetItem(["", text])
        from . import msgicons
        it.setIcon(0, msgicons.icon(self.ICONS[status]))
        it.setToolTip(0, {"warning": "Warning", "ok": "OK", "info": "Information"}[status])
        it.setData(0, QtCore.Qt.UserRole, check)
        it.setData(1, QtCore.Qt.UserRole, _pick(comps))
        parent.addChild(it)
        return it

    def compute(self):
        asm = _asm()
        if asm is None:
            return evaluate.PerformanceWindow.compute(self)
        self.stats = statistics(asm)
        self.stats.update(more_statistics(asm))
        self.checks = xpert_checks(asm, self.stats)
        self.table.clear()
        self.rows = []
        heads = {}
        for name in SECTIONS:
            h = QtWidgets.QTreeWidgetItem(["", name])
            f = h.font(1)
            f.setBold(True)
            h.setFont(1, f)
            self.table.addTopLevelItem(h)
            heads[name] = h
        times = []
        for c in _comps(asm, subassemblies=False):
            try:
                times.append((c, _value(c, "Rebuild Time")))
            except Exception as _fw_err:
                _fw_log("asmevaluate.py:930", _fw_err)
        times.sort(key=lambda t: -t[1])
        opened = open_time(asm)
        if opened:
            st = opened.get("stages", {})
            self._row(heads["Rebuild Performance"], "info", "Total time to open the assembly: %s s (reading %s s, components %s s, display %s s)" %
                      (_f(opened["total"], 2), _f(st.get("reading", 0), 2), _f(st.get("components", 0), 2), _f(st.get("display", 0), 2)))
        else:
            self._row(heads["Rebuild Performance"], "info", "Total time to open the assembly: not opened from a file in this session")
        for c, t in times[:20]:
            self._row(heads["Rebuild Performance"], "info", "%s: %s s" % (_label(c), _f(t, 3)), None, [c])
        for i, (status, text, comps, fix) in enumerate(self.checks):
            sec = CHECK_SECTION.get(fix if fix != "open" else "") or ("Graphics Performance" if "triangles" in text else
                                            "Rebuild Performance" if "out-of-date" in text else
                                            "Mate Performance" if "mate" in text.lower() else "Settings Performance")
            self._row(heads[sec], status, text, i, comps)
        self._row(heads["Graphics Performance"], "info", "Graphics triangles: %s" % self.stats.get("Graphics triangles", 0))
        for c, n in component_triangles(asm):
            self._row(heads["Graphics Performance"], "info", "%s: %d triangles" % (_label(c), n), None, [c])
        try:
            solve_times = mate_times(asm)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: mate solve times: %s\n" % error)
            solve_times = []
        if solve_times:
            total = sum(t for _j, t in solve_times)
            self._row(heads["Mate Performance"], "info", "Mate solve time: %s s" % _f(total, 3))
            for j, t in solve_times[:20]:
                self._row(heads["Mate Performance"], "info", "%s: %s s" % (j.Label, _f(t, 4)), None, [j])
        for k, v in self.stats.items():
            if k != "Graphics triangles":
                self._row(heads["Statistics"], "info", "%s: %s" % (k, v))
        for h in heads.values():
            worst = any(h.child(i).data(0, QtCore.Qt.UserRole) is not None and
                        self.checks[h.child(i).data(0, QtCore.Qt.UserRole)][0] == "warning" for i in range(h.childCount()))
            from . import msgicons
            h.setIcon(0, msgicons.icon(self.ICONS["warning" if worst else "ok"]))
        self.table.expandAll()
        self.table.resizeColumnToContents(0)
        warn = sum(1 for c in self.checks if c[0] == "warning")
        self.summary.setText("%d check%s to look at." % (warn, "" if warn == 1 else "s") if warn else
                             "Nothing to improve found.")
        self._fix_state()

    def items(self):
        out = []
        for i in range(self.table.topLevelItemCount()):
            h = self.table.topLevelItem(i)
            out.append(h)
            out += [h.child(k) for k in range(h.childCount())]
        return out

    def _current(self):
        items = self.table.selectedItems()
        if not items:
            return None
        i = items[0].data(0, QtCore.Qt.UserRole)
        return self.checks[i] if isinstance(i, int) and 0 <= i < len(self.checks) else None

    def _picked_item(self):
        self._fix_state()
        items = self.table.selectedItems()
        if not items:
            return
        Gui.Selection.clearSelection()
        for doc, obj, sub in items[0].data(1, QtCore.Qt.UserRole) or []:
            try:
                Gui.Selection.addSelection(doc, obj, sub)
            except Exception as _fw_err:
                _fw_log("asmevaluate.py:998", _fw_err)

    def _fix_state(self):
        c = self._current()
        self.fix_button.setVisible(bool(c and c[3]))

    def fix_current(self):
        c = self._current()
        asm = _asm()
        if c and c[3] and asm is not None:
            xpert_fix(asm, c[3], c[2])
            self.refresh()

    def _menu(self, pos):
        c = self._current()
        m = QtWidgets.QMenu(self)
        a = m.addAction("Fix")
        a.setEnabled(bool(c and c[3]))
        a.triggered.connect(self.fix_current)
        s = m.addAction("Select Components")
        s.setEnabled(bool(c and c[2]))
        s.triggered.connect(self._picked_item)
        m.exec_(self.table.viewport().mapToGlobal(pos))


def assembly_performance():
    if _asm() is None:
        return evaluate.performance_evaluation()
    return evaluate._show(AssemblyXpertWindow)


# ============================================================================= Previous Release Check
def release_needs(doc=None):
    ""

    doc = doc or App.ActiveDocument
    out = []
    if doc is None:
        return out
    for o in doc.Objects:
        proxy = getattr(o, "Proxy", None)
        if proxy is not None and o.TypeId.endswith("Python"):
            mod = type(proxy).__module__
            who = "this interface" if "swstyle" in mod else ("FreeCAD " + mod.split(".")[0] if mod.split(".")[0] in ("JointObject", "CommandCreateJoint", "UtilsAssembly") else mod.split(".")[0])
            out.append((o, "Python object (%s)" % who))
        elif o.TypeId.startswith("Assembly::"):
            out.append((o, "FreeCAD 1.0 or later (Assembly)"))
    return out


class ReleaseCheckWindow(ReportWindow):
    ""

    def __init__(self):
        super().__init__("Previous Release Check", ["Item", "Needs"])
        self.recalc.setText("Check")

    def compute(self):
        doc = App.ActiveDocument
        found = release_needs(doc)
        self.set_rows([((o.Label, why), [(doc.Name, o.Name, "")]) for o, why in found])
        ver = ""
        try:
            ver = ".".join(App.Version()[:3])
        except Exception as _fw_err:
            _fw_log("asmevaluate.py:1063", _fw_err)
        self.summary.setText(("Saved with FreeCAD %s. " % ver) + (
            "%d item%s need more than plain FreeCAD." % (len(found), "" if len(found) == 1 else "s")
            if found else "Plain FreeCAD opens everything in this document."))


def previous_release_check():
    return evaluate._show(ReleaseCheckWindow)


# ============================================================================= commands
TOOLS = (
    ("SWStyle_ClearanceVerification", "Clearance Verification",
     "Checks the gaps between components against a minimum clearance.", clearance_verification, True),
    ("SWStyle_HoleAlignment", "Hole Alignment",
     "Finds holes in different components that line up but are off centre.", hole_alignment, True),
    ("SWStyle_AssemblyVisualization", "Assembly Visualization",
     "Lists and colours the components by mass, volume, faces, triangles or rebuild time.", assembly_visualization, True),
    ("SWStyle_MateXpert", "MateXpert",
     "Finds the mates that do not hold, and the ones to suppress so the rest solve.", matexpert, True),
    ("SWStyle_AssemblyPerformance", "Performance Evaluation",
     "The assembly's counts and the components' rebuild times, with advice.", assembly_performance, False),
    ("SWStyle_PreviousReleaseCheck", "Previous Release Check",
     "Lists what in this document an older FreeCAD, or one without this interface, cannot open.", previous_release_check, False),
)


class _Cmd:
    def __init__(self, menu, tip, run, needs_asm):
        self.menu, self.tip, self.run, self.needs_asm = menu, tip, run, needs_asm

    def GetResources(self):
        return {"MenuText": self.menu, "ToolTip": self.tip}

    def Activated(self):
        self.run()

    def IsActive(self):
        if self.needs_asm:
            return _asm() is not None
        return App.ActiveDocument is not None


def register():
    have = set(Gui.listCommands())
    for name, menu, tip, run, needs in TOOLS:
        if name not in have:
            Gui.addCommand(name, _Cmd(menu, tip, run, needs))


# the catalog entries for the assembly Evaluate tab: (key, label, command, icon family, tip, caption)
CATALOG = (
    ("ClearanceVerification", "Clearance Verification", "SWStyle_ClearanceVerification", "ASSEMBLIES_CLEARANCE_VERIFICATION",
     "Checks the gaps between components against a minimum clearance.", "Clearance\nVerification"),
    ("HoleAlignment", "Hole Alignment", "SWStyle_HoleAlignment", "ASSEMBLIES_HOLE_ALIGNMENT",
     "Finds holes in different components that line up but are off centre.", "Hole\nAlignment"),
    ("AssemblyVisualization", "Assembly Visualization", "SWStyle_AssemblyVisualization", "ASSEMBLIES_VISUALIZATION",
     "Lists and colours the components by a property.", "Assembly\nVisualization"),
    ("MateXpert", "MateXpert", "SWStyle_MateXpert", "ASSEMBLIES_MATEXPERT",
     "Finds the mates that do not hold.", None),
    ("AssemblyPerformance", "Performance Evaluation", "SWStyle_AssemblyPerformance", "ASSEMBLIES_PERFORMANCE",
     "The assembly's counts and rebuild times, with advice.", "Performance\nEvaluation"),
    ("PreviousReleaseCheck", "Previous Release Check", "SWStyle_PreviousReleaseCheck", "TOOLS_PREVIOUS_RELEASE_CHECK",
     "What an older setup cannot open.", None),
)


EVALUATE = (
    ("large", "DesignStudy", None),
    ("large", "Interference", None),
    ("large", "ClearanceVerification", None),
    ("large", "HoleAlignment", None),
    ("large", "Measure", None),
    ("large", "MassProperties", None),
    ("stack", (("SectionProperties", None), ("Sensor", None), ("Markup", None))),
    ("sep",),
    ("large", "AssemblyVisualization", None),
    ("large", "AssemblyPerformance", None),
    ("stack", (("MateXpert", None), ("Check", None), ("PreviousReleaseCheck", None))),
)
