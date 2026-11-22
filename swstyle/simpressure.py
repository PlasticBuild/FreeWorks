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

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
    if not App.GuiUp:
        Gui = None
except ImportError:
    Gui = None

KIND = "pressure"
SETUP = "FwPressureVessel"
LINEAR = "FwPVLinearized"
RESULT_LABEL = "Combined Results"
METHODS = ("Linear combination", "SRSS (square root of the sum of squares)")
DEFAULTS = {"method": METHODS[0], "studies": []}
FIELDS = ("NodeStressXX", "NodeStressYY", "NodeStressZZ", "NodeStressXY", "NodeStressXZ", "NodeStressYZ",
          "NodeStrainXX", "NodeStrainYY", "NodeStrainZZ", "NodeStrainXY", "NodeStrainXZ", "NodeStrainYZ")
TENSOR = ("SX", "SY", "SZ", "TXY", "TXZ", "TYZ")
LIN_COLUMNS = TENSOR + ("P1", "P2", "P3", "INT")
LIN_ROWS = ("Membrane", "Bending", "Membrane + Bending (start)", "Membrane + Bending (end)", "Peak (start)",
            "Peak (end)", "Total (start)", "Total (end)")
SAMPLES = 41


def _set(o, name, value, kind="App::PropertyString"):
    if name not in o.PropertiesList:
        o.addProperty(kind, name, "FreeCAD", "")
        o.setPropertyStatus(name, "Hidden")
    setattr(o, name, value)


def _err(text):
    from . import simpms
    return simpms.SetupError(text)


def is_pressure(a):
    from . import simtypes
    return a is not None and getattr(a, simtypes.TYPE, "") == KIND


def new_study(doc, name):
    """A Pressure Vessel Design study; its Setup starts with the document's static studies at a factor of 1."""
    import ObjectsFem
    from . import simtypes
    a = ObjectsFem.makeAnalysis(doc, "Study")
    a.Label = name
    _set(a, simtypes.TYPE, KIND)
    v = dict(DEFAULTS)
    v["studies"] = [{"study": s.Name, "factor": 1.0} for s in candidates(doc)]
    _set(a, SETUP, json.dumps(v))
    return a


def candidates(doc):
    ""
    from . import simtypes
    return [o for o in doc.Objects if o.TypeId == "Fem::FemAnalysis" and getattr(o, simtypes.TYPE, "") != KIND
            and simtypes.study_type(o) == "static"]


def values(a):
    v = dict(DEFAULTS)
    try:
        v.update(json.loads(getattr(a, SETUP, "") or "{}"))
    except ValueError:
        pass
    v["studies"] = [dict(r) for r in v.get("studies", [])]
    return v


def studies(a):
    """[(study, factor)] the Setup combines, in order (a study since deleted is left out)."""
    doc = a.Document
    out = []
    for r in values(a)["studies"]:
        o = doc.getObject(r.get("study", ""))
        if o is not None:
            out.append((o, float(r.get("factor", 1.0))))
    return out


def set_setup(a, method=None, rows=None):
    """Pressure Vessel Setup: the method and [(study, factor)]."""
    v = values(a)
    if method is not None:
        if method not in METHODS:
            raise _err("Unknown combination %r." % method)
        v["method"] = method
    if rows is not None:
        ok = {o.Name for o in candidates(a.Document)}
        clean = []
        for st, f in rows:
            if st is None or st.Name not in ok:
                raise _err("Pick static studies of the part to combine.")
            if abs(float(f)) < 1e-12:
                raise _err("%s: give a factor other than 0." % st.Label)
            clean.append({"study": st.Name, "factor": float(f)})
        if not clean:
            raise _err("Pick at least one static study to combine.")
        v["studies"] = clean
    _set(a, SETUP, json.dumps(v))
    clear(a)
    return v


def method_word(a):
    return "SRSS" if values(a)["method"] == METHODS[1] else "Linear combination"


def clear(a):
    """Drops the combined result (the Setup changed) and its plots."""
    from . import simplots
    doc = a.Document
    for o in list(a.Group):
        if o.isDerivedFrom("Fem::FemResultObject"):
            a.removeObject(o)
            doc.removeObject(o.Name)
    if LINEAR in a.PropertiesList:
        setattr(a, LINEAR, "")
    try:
        simplots.save_plots(a, [])
    except Exception as _fw_err:
        _fw_log("simpressure.py:clear", _fw_err)


def result(a):
    res = [o for o in a.Group if o.isDerivedFrom("Fem::FemResultObject")]
    return res[-1] if res else None


# --------------------------------------------------------------------------- the run
def _node_map(m0, m1):
    """{node of m0: node of m1} at the same place, or None when the meshes differ (a mesh made again of the same part
    with the same settings has the same nodes, maybe numbered otherwise)."""
    if m0 is m1:
        return {n: n for n in m0.Nodes}
    if m0.NodeCount != m1.NodeCount:
        return None
    tol = 1e-6 * max(1.0, m0.BoundBox.DiagonalLength)
    n1 = m1.Nodes
    out = {}
    if all(k in n1 and (p - n1[k]).Length <= tol for k, p in m0.Nodes.items()):
        return {k: k for k in m0.Nodes}
    key = lambda p: (round(p.x / tol), round(p.y / tol), round(p.z / tol))
    at = {}
    for k, p in n1.items():
        at.setdefault(key(p), k)
    for k, p in m0.Nodes.items():
        q = at.get(key(p))
        if q is None:                          # a rounding edge: look at the next cells
            c = key(p)
            q = next((at[(c[0] + i, c[1] + j, c[2] + l)] for i in (-1, 0, 1) for j in (-1, 0, 1) for l in (-1, 0, 1)
                      if (c[0] + i, c[1] + j, c[2] + l) in at and (n1[at[(c[0] + i, c[1] + j, c[2] + l)]] - p).Length <= tol), None)
        if q is None:
            return None
        out[k] = q
    return out


MESH_SETTINGS = ("CharacteristicLengthMax", "CharacteristicLengthMin", "ElementOrder", "ElementDimension", "Algorithm2D",
                 "Algorithm3D", "SecondOrderLinear", "OptimizeStd", "OptimizeNetgen", "HighOrderOptimize")


def _mesh_of(st):
    return next((m for m in st.Group if m.isDerivedFrom("Fem::FemMeshObject")), None)


def _settings(m):
    shape = getattr(m, "Shape", None)
    out = [getattr(shape, "Name", None), len(list(getattr(m, "Group", []) or []))]
    for p in MESH_SETTINGS:
        v = getattr(m, p, None)
        out.append(str(v) if v is not None else None)
    return out


def _remesh_alike(first, st, progress=None):
    ""


    from . import addintabs
    m0, m1 = _mesh_of(first), _mesh_of(st)
    if m0 is None or m1 is None or m0 is m1 or _settings(m0) != _settings(m1) or not m0.FemMesh.Nodes:
        return False
    if progress:
        progress("Meshing %s as %s" % (st.Label, first.Label))
    m1.FemMesh = m0.FemMesh.copy()
    App.Console.PrintMessage("FreeCAD: %s takes the mesh of %s (the same mesh settings), so the two can be combined\n"
                             % (st.Label, first.Label))
    addintabs.run_study(st)
    return True


STAMP = "FwRunInputs"
_SKIP_TYPES = ("Fem::PropertyFemMesh", "App::PropertyPythonObject", "App::PropertyExpressionEngine", "App::PropertyLink",
               "App::PropertyLinkList", "App::PropertyLinkHidden", "App::PropertyLinkListHidden")
_SKIP_NAMES = {"Label", "Label2", "Visibility", "Group", "ExpressionEngine", "Proxy", "Content", STAMP}


def _inputs(st):
    ""

    import hashlib
    from . import simplots
    parts = []
    for o in sorted(st.Group, key=lambda x: x.Name):
        try:
            if (o.isDerivedFrom("Fem::FemResultObject") or o.isDerivedFrom("Fem::FemPostObject")
                    or o.TypeId.startswith("Fem::FemPost") or o.Name.startswith("CCX_Results")):
                continue
            row = [o.TypeId]
            for n in sorted(o.PropertiesList):
                if n in _SKIP_NAMES or o.getTypeIdOfProperty(n) in _SKIP_TYPES:
                    continue
                v = getattr(o, n, None)
                if n in ("References",):
                    v = [(x[0].Name, tuple(x[1])) for x in (v or [])]
                row.append("%s=%r" % (n, v))
            if hasattr(o, "Shape") and o.isDerivedFrom("Fem::FemMeshObject") and getattr(o, "Shape", None) is not None:
                bb = o.Shape.Shape.BoundBox
                row.append("part=%.6g,%.6g,%.6g,%.6g" % (o.Shape.Shape.Volume, bb.XLength, bb.YLength, bb.ZLength))
            parts.append("|".join(row))
        except Exception as _fw_err:
            _fw_log("simpressure.py:inputs", _fw_err)
    return hashlib.md5("\n".join(parts).encode("utf-8", "replace")).hexdigest()


def stamp(st):
    """Keeps the fingerprint of what the study solved, right after its run."""
    try:
        if STAMP not in st.PropertiesList:
            st.addProperty("App::PropertyString", STAMP, "FreeWorks", "What the last run solved")
            st.setEditorMode(STAMP, 2)
        setattr(st, STAMP, _inputs(st))
    except Exception as _fw_err:
        _fw_log("simpressure.py:stamp", _fw_err)


def out_of_date(st):
    """True when the study was changed after its last run (a study run before this was kept counts as up to date)."""
    old = getattr(st, STAMP, "") if STAMP in st.PropertiesList else ""
    return bool(old) and old != _inputs(st)


def run(a, progress=None):
    """Runs the static studies that have no result, then writes their combination as the study's result."""
    import numpy as np
    from . import addintabs, simplots
    rows = studies(a)
    if not rows:
        raise _err("Pick the static studies to combine (right-click Setup, Edit Definition).")
    srss = values(a)["method"] == METHODS[1]
    got = []
    for st, f in rows:
        if simplots.result(st) is None or out_of_date(st):
            if progress:
                progress("Running %s" % st.Label + (" (changed since its last run)" if simplots.result(st) is not None else ""))
            addintabs.run_study(st)
        r = simplots.result(st)
        if r is None:
            raise _err("%s has no result." % st.Label)
        got.append((st, f, r))
    mesh0 = got[0][2].Mesh
    maps = []
    for i, (st, f, r) in enumerate(got):
        nm = _node_map(mesh0.FemMesh, r.Mesh.FemMesh) if r.Mesh is not None else None
        if nm is None and _remesh_alike(got[0][0], st, progress):
            r = simplots.result(st)            # meshed as the first study (same settings), and run again
            got[i] = (st, f, r)
            nm = _node_map(mesh0.FemMesh, r.Mesh.FemMesh) if r is not None and r.Mesh is not None else None
        if nm is None:
            raise _err("%s and %s do not share one mesh: mesh them with the same settings (or copy the study) and run again."
                       % (got[0][0].Label, st.Label))
        maps.append(nm)
    nodes = list(got[0][2].NodeNumbers)
    data = {}
    for (_st, f, r), nm in zip(got, maps):
        order = {n: i for i, n in enumerate(r.NodeNumbers)}
        idx = np.array([order[nm[n]] for n in nodes])
        disp = np.array([(v.x, v.y, v.z) for v in r.DisplacementVectors])[idx] * f
        parts = {"DX": disp[:, 0], "DY": disp[:, 1], "DZ": disp[:, 2]}
        for name in FIELDS:
            vals = list(getattr(r, name, []) or [])
            parts[name] = (np.array(vals)[idx] * f) if len(vals) == len(order) else np.zeros(len(nodes))
        for k, x in parts.items():
            data.setdefault(k, []).append(x)
    comb = {k: (np.sqrt(sum(x * x for x in xs)) if srss else sum(xs)) for k, xs in data.items()}
    clear(a)
    import ObjectsFem
    doc = a.Document
    res = ObjectsFem.makeResultMechanical(doc, "PressureVesselResult")
    res.Label = RESULT_LABEL
    a.addObject(res)
    res.Mesh = mesh0
    res.NodeNumbers = nodes
    vec = [App.Vector(float(x), float(y), float(z)) for x, y, z in zip(comb["DX"], comb["DY"], comb["DZ"])]
    res.DisplacementVectors = vec
    res.DisplacementLengths = [v.Length for v in vec]
    for name in FIELDS:
        setattr(res, name, [float(x) for x in comb[name]])
    sx, sy, sz, txy, txz, tyz = (comb[n] for n in FIELDS[:6])
    t = np.zeros((len(nodes), 3, 3))
    t[:, 0, 0], t[:, 1, 1], t[:, 2, 2] = sx, sy, sz
    t[:, 0, 1] = t[:, 1, 0] = txy
    t[:, 0, 2] = t[:, 2, 0] = txz
    t[:, 1, 2] = t[:, 2, 1] = tyz
    ev = np.linalg.eigvalsh(t)                      # ascending
    vm = np.sqrt(0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2) + 3.0 * (txy ** 2 + txz ** 2 + tyz ** 2))
    res.vonMises = [float(x) for x in vm]
    res.PrincipalMax = [float(x) for x in ev[:, 2]]
    res.PrincipalMed = [float(x) for x in ev[:, 1]]
    res.PrincipalMin = [float(x) for x in ev[:, 0]]
    res.MaxShear = [float(x) for x in (ev[:, 2] - ev[:, 0]) / 2.0]
    try:
        res.ViewObject.Visibility = False
    except Exception as _fw_err:
        _fw_log("simpressure.py:hide", _fw_err)
    doc.recompute()
    simplots.defaults(a)
    return summary(a)


def summary(a):
    r = result(a)
    if r is None:
        return "Pressure Vessel Design: not run"
    return "Pressure Vessel Design, %s of %d studies\nMax von Mises stress: %.4g MPa\nMax displacement: %.4g mm" % (
        method_word(a), len(studies(a)), max(r.vonMises or [0.0]), max(r.DisplacementLengths or [0.0]))


# --------------------------------------------------------------------------- Stress Linearization
def _tensor_at(res, points):
    """The stress tensor (SX, SY, SZ, TXY, TXZ, TYZ in MPa) at each point, from the element it lies in (quadratic
    tetrahedra interpolate with their 10 nodes)."""
    import numpy as np
    fm = res.Mesh.FemMesh
    order = {n: i for i, n in enumerate(res.NodeNumbers)}
    comp = np.array([list(getattr(res, n)) for n in FIELDS[:6]]).T          # (nodes, 6)
    vols = list(fm.Volumes)
    conn = [fm.getElementNodes(e) for e in vols]
    conn = [c for c in conn if len(c) in (4, 10)]
    if not conn:
        raise _err("Stress Linearization needs a solid (tetrahedral) mesh.")
    nodes = fm.Nodes
    corners = np.array([[(nodes[c[i]].x, nodes[c[i]].y, nodes[c[i]].z) for i in range(4)] for c in conn])
    x0 = corners[:, 0, :]
    T = np.stack([corners[:, 1, :] - x0, corners[:, 2, :] - x0, corners[:, 3, :] - x0], axis=2)   # columns
    ok = np.abs(np.linalg.det(T)) > 1e-18
    inv = np.zeros_like(T)
    inv[ok] = np.linalg.inv(T[ok])
    out = []
    for p in points:
        lam = np.einsum("eij,ej->ei", inv, np.array(p) - x0)
        L = np.concatenate([1.0 - lam.sum(axis=1)[:, None], lam], axis=1)
        L[~ok] = -1e9
        e = int(np.argmax(L.min(axis=1)))
        l = np.clip(L[e], 0.0, 1.0)
        l = l / l.sum()
        c = conn[e]
        if len(c) == 4:
            w = {c[i]: l[i] for i in range(4)}
        else:
            w = {c[i]: l[i] * (2.0 * l[i] - 1.0) for i in range(4)}
            mids = [nodes[n] for n in c[4:]]
            for i, j in ((0, 1), (1, 2), (0, 2), (0, 3), (1, 3), (2, 3)):
                m = (nodes[c[i]] + nodes[c[j]]) * 0.5
                k = min(range(6), key=lambda q: (mids[q] - m).Length)       # the edge's mid-side node, by place
                w[c[4 + k]] = w.get(c[4 + k], 0.0) + 4.0 * l[i] * l[j]
        s = np.zeros(6)
        for n, wt in w.items():
            s += wt * comp[order[n]]
        out.append(s)
    return np.array(out)


def _principal(s):
    import numpy as np
    t = np.array([[s[0], s[3], s[4]], [s[3], s[1], s[5]], [s[4], s[5], s[2]]])
    ev = np.linalg.eigvalsh(t)
    return [float(ev[2]), float(ev[1]), float(ev[0]), float(ev[2] - ev[0])]


def linearize(a, start, end, store=True):
    ""

    import numpy as np
    res = result(a)
    if res is None:
        raise _err("Run the study first.")
    p0, p1 = App.Vector(*start), App.Vector(*end)
    t = (p1 - p0).Length
    if t < 1e-9:
        raise _err("Pick two different locations.")
    s = np.linspace(0.0, t, SAMPLES)
    pts = [tuple(p0 + (p1 - p0) * (x / t)) for x in s]
    sig = _tensor_at(res, pts)                                     # (SAMPLES, 6)
    m = np.trapz(sig, s, axis=0) / t
    b = 6.0 / t ** 2 * np.trapz(sig * (t / 2.0 - s)[:, None], s, axis=0)
    tens = {"Membrane": m, "Bending": b, "Membrane + Bending (start)": m + b, "Membrane + Bending (end)": m - b,
            "Peak (start)": sig[0] - m - b, "Peak (end)": sig[-1] - m + b, "Total (start)": sig[0], "Total (end)": sig[-1]}
    rows = {}
    for k in LIN_ROWS:
        v = [float(x) for x in tens[k]]
        rows[k] = dict(zip(LIN_COLUMNS, v + _principal(v)))
    out = {"start": list(start), "end": list(end), "length": t, "rows": rows}
    if store:
        _set(a, LINEAR, json.dumps(out))
    return out


def last_linearization(a):
    try:
        return json.loads(getattr(a, LINEAR, "") or "{}")
    except ValueError:
        return {}


# --------------------------------------------------------------------------- the tree
def study_rows(a, Row):
    ""

    from . import simtree
    root = Row("%s (-%s-)" % (a.Label, simtree.config_name(a.Document)), "SIM_PressureVessel", a, "study")
    tip = "%s: %s" % (method_word(a), ", ".join("%s x %g" % (st.Label, f) for st, f in studies(a)) or "no study yet")
    root.add(Row("Setup", "SIM_PressureVessel", None, "pvsetup", tip=tip))
    if result(a) is not None:
        results = root.add(Row("Results", "SIM_Results", None, "results"))
        simtree._result_rows(a, results)
    return root


def menu_entries(row, a, key):
    from . import simplots, simtree, simtypes
    w = row.what
    if w == "study":
        return [("Run", lambda: simtypes._run(a)), ("Edit Definition...", lambda: open_setup(a)),
                ("Report...", lambda: simtree.run_key("SIM_Report", a, None)) if simtree.has_key("SIM_Report") else None,
                ("-", None), ("Rename", None), ("Delete", lambda: simtree.delete_study(a))]
    if w == "pvsetup":
        return [("Define/edit...", lambda: open_setup(a))]
    if w == "results":
        if result(a) is None:
            return []
        out = [("Define %s Plot..." % q, lambda q=q: simtree._define(a, q)) for q in ("Stress", "Displacement", "Strain")]
        out += [("Stress Linearization...", lambda: open_linearize(a)), ("-", None),
                ("Delete All Results", lambda: (clear(a), simtypes._refresh()))]
        return out
    return None


# --------------------------------------------------------------------------- install
def install():
    from . import simplots, simtree, simstudy
    if getattr(simplots, "_fw_pressure", False):
        return
    simplots.KINDS[KIND] = ("Stress", "Displacement", "Strain")
    simtree.KIND_WORDS.setdefault(KIND, "Pressure Vessel Design")
    simstudy.STEPS.setdefault(KIND, ())
    menu0 = simtree.menu_entries

    def menu_entries_(row, a):
        out = menu0(row, a)
        if is_pressure(a):
            out = [x for x in out if x is not None]
            if row.what == "plot":
                p = simplots.get_plot(a, row.plot)
                if p is not None and p.get("quantity") == "Stress":
                    at = next((i for i, x in enumerate(out) if x[0] == "-"), len(out))
                    out.insert(at, ("Linearize...", lambda: open_linearize(a)))
        return out
    simtree.menu_entries = menu_entries_
    from . import addintabs
    run0 = addintabs.run_study

    def run_study_(analysis, *args, **kw):
        out = run0(analysis, *args, **kw)
        stamp(analysis)                   # what this run solved: a later change marks it out of date
        return out
    addintabs.run_study = run_study_
    simplots._fw_pressure = True


# --------------------------------------------------------------------------- PMs
if Gui is not None:
    from . import simxpress as sx

    def _units():
        from . import simplots
        return list(simplots.UNITS["Stress"])

    class SetupPM:
        """Pressure Vessel Setup: Linear combination or SRSS, and the static studies with their factors."""
        PM = "Pressure Vessel Setup"

        def __init__(self, a):
            self.a = a
            self.doc = a.Document
            v = values(a)
            box = sx._box("Options", None, self.PM)
            bl = QtWidgets.QVBoxLayout(box)
            self.linear = QtWidgets.QRadioButton("Linear combination")
            self.linear.setObjectName("SWPVLinear")
            self.srss = QtWidgets.QRadioButton("SRSS (square root of the sum of squares)")
            self.srss.setObjectName("SWPVSRSS")
            (self.srss if v["method"] == METHODS[1] else self.linear).setChecked(True)
            bl.addWidget(self.linear)
            bl.addWidget(self.srss)
            tb = sx._box("Studies")
            tl = QtWidgets.QVBoxLayout(tb)
            tl.addWidget(QtWidgets.QLabel("Tick the studies to combine and give each its factor:"))
            self.table = QtWidgets.QTableWidget()
            self.table.setObjectName("SWPVStudies")
            self.table.setColumnCount(2)
            self.table.setHorizontalHeaderLabels(["Study", "Factor"])
            self.table.verticalHeader().setVisible(False)
            self.table.horizontalHeader().setStretchLastSection(True)
            have = {r["study"]: float(r.get("factor", 1.0)) for r in v["studies"]}
            self.rows = []
            cands = candidates(self.doc)
            self.table.setRowCount(len(cands))
            for i, st in enumerate(cands):
                it = QtWidgets.QTableWidgetItem(st.Label)
                it.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsUserCheckable)
                it.setCheckState(QtCore.Qt.Checked if st.Name in have else QtCore.Qt.Unchecked)
                self.table.setItem(i, 0, it)
                f = QtWidgets.QDoubleSpinBox()
                f.setRange(-1e6, 1e6)
                f.setDecimals(4)
                f.setValue(have.get(st.Name, 1.0))
                self.table.setCellWidget(i, 1, f)
                self.rows.append((st, it, f))
            self.table.setFixedHeight(28 + 26 * max(1, len(cands)))
            tl.addWidget(self.table)
            if not cands:
                tl.addWidget(QtWidgets.QLabel("The part has no static study yet: make one, then edit this Setup."))
                self.table.setVisible(False)
            self.form = [box, tb]

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def reject(self):
            Gui.Control.closeDialog()
            return True

        def accept(self):
            from . import simpms, simtypes
            rows = [(st, f.value()) for st, it, f in self.rows if it.checkState() == QtCore.Qt.Checked]
            self.doc.openTransaction(self.PM)
            try:
                set_setup(self.a, METHODS[1] if self.srss.isChecked() else METHODS[0], rows)
            except simpms.SetupError as e:
                self.doc.abortTransaction()
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), self.PM, str(e))
                return False
            self.doc.commitTransaction()
            Gui.Control.closeDialog()
            simtypes._refresh()
            return True

    class LinearizePM:
        """Stress Linearization: two locations across the wall, Calculate, the table of membrane, bending and peak."""
        PM = "Stress Linearization"

        def __init__(self, a):
            self.a = a
            self.doc = a.Document
            box = sx._box("Locations", None, self.PM)
            bl = QtWidgets.QVBoxLayout(box)
            bl.addWidget(QtWidgets.QLabel("Pick two locations on the model, one on each side of the wall:"))
            self.picks = sx._PickList("SWPVLocations")
            self.picks.setToolTip("Pick a vertex or a point on a face; a third pick replaces the second")
            bl.addWidget(self.picks)
            self.points = []
            last = last_linearization(a)
            if last.get("start"):
                for p in (last["start"], last["end"]):
                    self._add(tuple(p))
            self.calc = QtWidgets.QPushButton("Calculate")
            self.calc.setObjectName("SWPVCalculate")
            self.calc.clicked.connect(self.calculate)
            bl.addWidget(self.calc)
            rb = sx._box("Results")
            rl = QtWidgets.QFormLayout(rb)
            self.unit = QtWidgets.QComboBox()
            self.unit.setObjectName("SWPVUnit")
            self.unit.addItems(_units())
            self.unit.setCurrentText("N/m^2")
            self.unit.currentIndexChanged.connect(lambda *_a: self._fill())
            rl.addRow("Units:", self.unit)
            self.note = QtWidgets.QLabel()
            self.note.setObjectName("SWPVNote")
            self.note.setWordWrap(True)
            rl.addRow(self.note)
            self.table = QtWidgets.QTableWidget()
            self.table.setObjectName("SWPVLinearTable")
            self.table.setColumnCount(len(LIN_COLUMNS))
            self.table.setHorizontalHeaderLabels(list(LIN_COLUMNS))
            self.table.setRowCount(len(LIN_ROWS))
            self.table.setVerticalHeaderLabels(list(LIN_ROWS))
            self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            self.table.setFixedHeight(30 + 24 * len(LIN_ROWS))
            rl.addRow(self.table)
            self.form = [box, rb]
            self.data = last if last.get("rows") else None
            self._fill()
            self.picks.active(True)
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)

        def _add(self, p):
            if len(self.points) == 2:
                self.points.pop()
                self.picks.takeItem(1)
            self.points.append(tuple(p))
            self.picks.addItem("%.4g, %.4g, %.4g mm" % tuple(p))

        def addSelection(self, doc, name, sub, pnt):
            if doc != self.doc.Name:
                return
            p = (pnt[0], pnt[1], pnt[2])
            try:
                o = self.doc.getObject(name)
                if sub and sub.split(".")[-1].startswith("Vertex"):
                    v = o.Shape.getElement(sub.split(".")[-1]).Point
                    p = (v.x, v.y, v.z)
            except Exception as _fw_err:
                _fw_log("simpressure.py:vertex", _fw_err)
            QtCore.QTimer.singleShot(0, lambda: self._picked(p))

        def _picked(self, p):
            try:
                self._add(p)
                Gui.Selection.clearSelection()
            except RuntimeError:
                Gui.Selection.removeObserver(self)

        def calculate(self):
            from . import simpms
            if len(self.points) < 2:
                self.note.setText("Pick two locations first.")
                return None
            try:
                self.data = linearize(self.a, self.points[0], self.points[1])
            except simpms.SetupError as e:
                self.note.setText(str(e))
                return None
            self._fill()
            return self.data

        def _fill(self):
            from . import simplots
            k = simplots.to_unit("Stress", self.unit.currentText())
            if not self.data:
                self.note.setText("Pick two locations, then Calculate.")
                self.table.setVisible(False)
                return
            self.table.setVisible(True)
            self.note.setText("Line length %.4g mm, %d points" % (self.data["length"], SAMPLES))
            for i, r in enumerate(LIN_ROWS):
                for j, c in enumerate(LIN_COLUMNS):
                    self.table.setItem(i, j, QtWidgets.QTableWidgetItem("%.4g" % (self.data["rows"][r][c] * k)))

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Close

        def _close(self):
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("simpressure.py:observer", _fw_err)

        def reject(self):
            self._close()
            Gui.Control.closeDialog()
            return True

        def accept(self):
            return self.reject()

    def _show(pm):
        from . import simtypes
        return simtypes._show(pm)

    NO_STUDY = "You need one or more static studies of the part to combine. Make a static study first."

    def open_setup(a):
        if not candidates(a.Document):
            QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Pressure Vessel Design", NO_STUDY)
            return None
        return _show(SetupPM(a))

    def open_linearize(a):
        return _show(LinearizePM(a))
else:
    def open_setup(a):
        return None

    def open_linearize(a):
        return None
