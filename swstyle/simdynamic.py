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
import os
import re
import subprocess

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
    if not App.GuiUp:
        Gui = None
except ImportError:
    Gui = None

KIND = "lineardynamic"
OPT = "FwLinearDynamic"
STEPS = "FwDynamicSteps"
ANALYSES = ("Modal Time History", "Harmonic", "Random Vibration", "Response Spectrum Analysis")
BASE = ("Random Vibration", "Response Spectrum Analysis")     # driven by a uniform base excitation, not the loads
DIRECTIONS = ("X", "Y", "Z")
COMBINATIONS = ("SRSS", "CQC", "Absolute Sum")
G = 9806.65                                                    # 1 g in mm/s^2
DEFAULTS = {"analysis": ANALYSES[1], "modes": 10, "damping": 2.0, "f_lo": 0.0, "f_hi": 1000.0, "points": 10,
            "bias": 3.0, "end": 0.1, "increment": 0.001, "curve": [[0.0, 1.0], [0.1, 1.0]], "saved": 50,
            "direction": "Y", "psd": [[20.0, 0.01], [2000.0, 0.01]], "spectrum": [[1.0, 1.0], [1000.0, 1.0]],
            "combination": "SRSS"}
MAX_SAVED = 200


def _set(o, name, value, kind="App::PropertyString"):
    if name not in o.PropertiesList:
        o.addProperty(kind, name, "FreeCAD", "")
        o.setPropertyStatus(name, "Hidden")
    setattr(o, name, value)


def _err(text):
    from . import simpms
    return simpms.SetupError(text)


def is_dynamic(a):
    from . import simtypes
    return a is not None and getattr(a, simtypes.TYPE, "") == KIND


def values(a):
    v = dict(DEFAULTS)
    try:
        v.update(json.loads(getattr(a, OPT, "") or "{}"))
    except ValueError:
        pass
    return v


def analysis(a):
    return values(a)["analysis"]


def label_of(analysis_name):
    return analysis_name


def new_study(doc, name, analysis_name=None, obj=None):
    """A Linear Dynamic study (Harmonic or Modal Time History) on the part: a static setup plus its options."""
    from . import addintabs, simtypes
    analysis_name = analysis_name or DEFAULTS["analysis"]
    if analysis_name not in ANALYSES:
        raise ValueError("Unknown linear dynamic analysis %r." % analysis_name)
    if simtypes._assembly(doc) is not None:
        from . import asmsim
        a = asmsim.new_study(simtypes._assembly(doc), "static", name or simtypes._next_label(doc, analysis_name))
    else:
        obj = obj or addintabs._main_solid(doc)
        if obj is None:
            raise ValueError("The document has no solid body to study.")
        a = addintabs.new_study(doc, obj, "static", name or simtypes._next_label(doc, analysis_name))
    _set(a, simtypes.TYPE, KIND)
    v = dict(DEFAULTS)
    v["analysis"] = analysis_name
    _set(a, OPT, json.dumps(v))
    return a


def set_values(a, **kw):
    ""
    v = values(a)
    v.update(kw)
    if v["analysis"] not in ANALYSES:
        raise _err("Unknown linear dynamic analysis %r." % v["analysis"])
    if int(v["modes"]) < 1:
        raise _err("Give at least one frequency.")
    if not 0.0 <= float(v["damping"]) < 100.0:
        raise _err("Give a modal damping ratio from 0 to 100 %.")
    if v["analysis"] in BASE:
        if v["direction"] not in DIRECTIONS:
            raise _err("Pick the base excitation direction: X, Y or Z.")
        if v["analysis"] == BASE[1] and v["combination"] not in COMBINATIONS:
            raise _err("Pick a mode combination method: SRSS, CQC or Absolute Sum.")
        key = "psd" if v["analysis"] == BASE[0] else "spectrum"
        word = "PSD" if key == "psd" else "spectrum"
        pts = [[float(f), float(y)] for f, y in v[key]]
        if len(pts) < 2 or any(b[0] <= a_[0] for a_, b in zip(pts, pts[1:])):
            raise _err("The %s curve needs two or more points in increasing frequency." % word)
        if pts[0][0] <= 0 or any(y < 0 for _f, y in pts) or not any(y > 0 for _f, y in pts):
            raise _err("The %s curve needs frequencies above 0 Hz and values of 0 or more (not all 0)." % word)
        v[key] = pts
    elif v["analysis"] == "Harmonic":
        if float(v["f_lo"]) < 0 or float(v["f_hi"]) <= float(v["f_lo"]):
            raise _err("Give an upper frequency limit above the lower limit.")
        if int(v["points"]) < 2:
            raise _err("Give at least 2 points.")
        if float(v["bias"]) < 1.0:
            raise _err("Give a bias parameter of 1 or more.")
    else:
        if float(v["end"]) <= 0 or float(v["increment"]) <= 0 or float(v["increment"]) > float(v["end"]):
            raise _err("Give an end time and a time increment no larger than it.")
        if float(v["end"]) / float(v["increment"]) > 100000:
            raise _err("The time increment is too small for the end time (more than 100000 increments).")
        pts = [[float(t), float(f)] for t, f in v["curve"]]
        if len(pts) < 2 or any(b[0] <= a_[0] for a_, b in zip(pts, pts[1:])):
            raise _err("The time curve needs two or more points in increasing time.")
        v["curve"] = pts
    v["modes"], v["points"] = int(v["modes"]), int(v["points"])
    _set(a, OPT, json.dumps(v))
    return v


# --------------------------------------------------------------------------- the input
def _split_step(text):
    """(head, the static step's boundary blocks, its load blocks) of the input FreeCAD wrote for a static study."""
    i = text.upper().find("\n*STEP")
    head = text[:i + 1]
    rest = text[i + 1:]
    j = rest.upper().find("*END STEP")
    step = rest[:j]
    k = step.find("** Outputs")
    body = step[:k] if k >= 0 else step
    body = body.split("\n", 2)[2] if body.upper().startswith("*STEP") else body        # *STEP, *STATIC lines
    blocks = re.split(r"\n(?=\*{5,}\n)", "\n" + body)
    bcs, loads = [], []
    for b in blocks:
        kws = [ln.split(",")[0].strip().upper() for ln in b.splitlines() if ln.startswith("*") and not ln.startswith("**")]
        if not kws:
            continue
        (bcs if all(k == "*BOUNDARY" for k in kws) else loads).append(b.strip("\n") + "\n")
    return head, "".join(bcs), "".join(loads)


def _material_density(doc, name, density):
    """The density (t/mm^3) of the material FreeCAD wrote as *MATERIAL, NAME=name, else density."""
    try:
        o = doc.getObject(name) if doc is not None else None
        d = dict(getattr(o, "Material", {}) or {}).get("Density") if o is not None else None
        if d:
            v = App.Units.Quantity(d).getValueAs("t/mm^3")
            v = float(getattr(v, "Value", v))
            if v > 0:
                return v
    except Exception as _fw_err:
        _fw_log("simdynamic.py:density", _fw_err)
    return density


def _with_densities(head, density, doc=None):
    """Each *MATERIAL block gets its own *DENSITY after its *ELASTIC line (a part of several materials: each its
    own, not the first one's for all)."""
    out, name, done = [], None, False
    lines = head.split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        up = ln.upper()
        if up.startswith("*MATERIAL"):
            m = re.search(r"NAME\s*=\s*([^,\s]+)", ln, re.I)
            name, done = (m.group(1) if m else None), False
        if up.startswith("*DENSITY"):
            done = True
        out.append(ln)
        if up.startswith("*ELASTIC") and i + 1 < len(lines) and not done:
            out.append(lines[i + 1])
            i += 1
            nxt = lines[i + 1].upper() if i + 1 < len(lines) else ""
            if not nxt.startswith("*DENSITY"):
                out.append("*DENSITY")
                out.append("%.6g" % _material_density(doc, name, density))
            done = True
        i += 1
    return "\n".join(out)


def dynamic_input(a, text, density):
    """The CalculiX input of the study from the static one FreeCAD wrote: the material's density, a *FREQUENCY step
    (the fixtures; modes stored) and the response step (*STEADY STATE DYNAMICS or *MODAL DYNAMIC) with the loads and
    modal damping."""
    v = values(a)
    head, bcs, loads = _split_step(text)
    head = _with_densities(head, density, getattr(a, "Document", None))
    n = int(v["modes"])
    zeta = float(v["damping"]) / 100.0
    out = [head.rstrip("\n")]
    if v["analysis"] in BASE:                  # the modes with their stresses; the response is summed from them
        out.append("*STEP\n*FREQUENCY, STORAGE=YES\n%d\n%s*NODE FILE\nU\n*EL FILE\nS, E\n*END STEP" % (n, bcs))
        return "\n".join(out) + "\n"
    harmonic = v["analysis"] == "Harmonic"
    if not harmonic:
        pts = ", ".join("%.9g, %.9g" % (t, f) for t, f in v["curve"])
        out.append("*AMPLITUDE, NAME=FWCURVE\n" + pts)
    out.append("*STEP\n*FREQUENCY, STORAGE=YES\n%d\n%s*NODE FILE\nU\n*END STEP" % (n, bcs))
    if harmonic:
        step = "*STEP\n*STEADY STATE DYNAMICS\n%.9g, %.9g, %d, %.6g\n" % (
            max(float(v["f_lo"]), 1e-6), float(v["f_hi"]), int(v["points"]), float(v["bias"]))
        every = 1
    else:
        incs = int(round(float(v["end"]) / float(v["increment"])))
        every = max(1, incs // max(1, min(MAX_SAVED, int(v.get("saved", 50)))))
        step = "*STEP, INC=%d\n*MODAL DYNAMIC\n%.9g, %.9g\n" % (incs + 10, float(v["increment"]), float(v["end"]))
        loads = re.sub(r"^(\*(?:CLOAD|DLOAD)[^\n]*)", lambda m: m.group(1) + ", AMPLITUDE=FWCURVE", loads, flags=re.M)
    step += "*MODAL DAMPING\n1, %d, %.6g\n" % (n, zeta)
    step += loads
    freq = "" if every == 1 else ", FREQUENCY=%d" % every
    step += "*NODE FILE%s\nU\n*EL FILE%s\nS, E\n*END STEP" % (freq, freq)
    out.append(step)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- the results
def read_frd(path):
    """[(kind, value, {block: {node: [values]}})] of each result set in a CalculiX .frd: kind "MODAL" for the mode
    shapes, else "" (a frequency point or a time step)."""
    sets = []
    cur = None
    block = None
    with open(path, errors="replace") as f:
        for line in f:
            if line.startswith("  100C"):
                value = float(line[12:24])
                kind = "MODAL" if "MODAL" in line[60:] else ""
                key = (kind, value, line[58:68])
                if cur is None or cur[3] != key:
                    cur = [kind, value, {}, key]
                    sets.append(cur)
                block = None
            elif line.startswith(" -4") and cur is not None:
                block = line.split()[1]
                cur[2][block] = {}
            elif line.startswith(" -1") and block is not None:
                node = int(line[3:13])
                vals = [float(line[13 + 12 * i:25 + 12 * i]) for i in range((len(line.rstrip("\n")) - 13) // 12)]
                cur[2][block][node] = vals
            elif line.startswith(" -3"):
                block = None
    return [(k, v, b) for k, v, b, _key in sets]


def _imag(blocks, name):
    for k in (name + "I", name[:-1] + "I"):
        if k in blocks and k != name:
            return blocks[k]
    return None


def _amplitude(re_, im):
    ""
    import math
    if im is None:
        return list(re_)
    return [math.copysign(math.hypot(r, i), r if r else 1.0) for r, i in zip(re_, im)]


def _make_result(a, mesh, nodes, blocks, harmonic, label):
    import ObjectsFem
    import numpy as np
    doc = a.Document
    res = ObjectsFem.makeResultMechanical(doc, "DynamicResult")
    res.Label = label
    a.addObject(res)
    res.Mesh = mesh
    res.NodeNumbers = nodes

    def field(name, width):
        re_b = blocks.get(name, {})
        im_b = _imag(blocks, name) if harmonic else None
        cols = []
        for c in range(width):
            r = [re_b.get(n, [0.0] * width)[c] for n in nodes]
            im = [im_b.get(n, [0.0] * width)[c] for n in nodes] if im_b else None
            cols.append(_amplitude(r, im) if harmonic else r)
        return cols
    ux, uy, uz = field("DISP", 3)
    vec = [App.Vector(x, y, z) for x, y, z in zip(ux, uy, uz)]
    res.DisplacementVectors = vec
    res.DisplacementLengths = [v.Length for v in vec]
    sxx, syy, szz, sxy, syz, szx = field("STRESS", 6)
    res.NodeStressXX, res.NodeStressYY, res.NodeStressZZ = sxx, syy, szz
    res.NodeStressXY, res.NodeStressYZ, res.NodeStressXZ = sxy, syz, szx
    if "TOSTRAIN" in blocks:
        exx, eyy, ezz, exy, eyz, ezx = field("TOSTRAIN", 6)
        res.NodeStrainXX, res.NodeStrainYY, res.NodeStrainZZ = exx, eyy, ezz
        res.NodeStrainXY, res.NodeStrainYZ, res.NodeStrainXZ = exy, eyz, ezx
    s = np.array([sxx, syy, szz, sxy, szx, syz])
    t = np.zeros((len(nodes), 3, 3))
    t[:, 0, 0], t[:, 1, 1], t[:, 2, 2] = s[0], s[1], s[2]
    t[:, 0, 1] = t[:, 1, 0] = s[3]
    t[:, 0, 2] = t[:, 2, 0] = s[4]
    t[:, 1, 2] = t[:, 2, 1] = s[5]
    ev = np.linalg.eigvalsh(t)
    vm = np.sqrt(0.5 * ((s[0] - s[1]) ** 2 + (s[1] - s[2]) ** 2 + (s[2] - s[0]) ** 2) + 3.0 * (s[3] ** 2 + s[4] ** 2 + s[5] ** 2))
    res.vonMises = [float(x) for x in vm]
    res.PrincipalMax = [float(x) for x in ev[:, 2]]
    res.PrincipalMed = [float(x) for x in ev[:, 1]]
    res.PrincipalMin = [float(x) for x in ev[:, 0]]
    res.MaxShear = [float(x) for x in (ev[:, 2] - ev[:, 0]) / 2.0]
    try:
        res.ViewObject.Visibility = False
    except Exception as _fw_err:
        _fw_log("simdynamic.py:hide", _fw_err)
    return res


def clear(a):
    doc = a.Document
    for o in list(a.Group):
        if o.isDerivedFrom("Fem::FemResultObject") or (o.isDerivedFrom("Fem::FemMeshObject") and o.Name.startswith("ResultMesh")):
            a.removeObject(o)
            doc.removeObject(o.Name)
    _set(a, STEPS, "")
    try:
        from . import simplots
        simplots.save_plots(a, [])
    except Exception as _fw_err:
        _fw_log("simdynamic.py:clear", _fw_err)


def run(a, progress=None):
    """Modes, then the response: returns a summary text."""
    from femtools import ccxtools
    from . import addintabs, simplots, simtypes
    doc = a.Document
    solver = addintabs._solver(a)
    if solver is None:
        raise RuntimeError("The study has no solver.")
    addintabs._ensure_mesh(a)
    doc.recompute()
    fea = ccxtools.FemToolsCcx(a, solver)
    fea.update_objects()
    fea.setup_working_dir()
    fea.setup_ccx()
    message = fea.check_prerequisites()
    if message:
        raise RuntimeError(message)
    fea.purge_results()
    fea.write_inp_file()
    path = fea.inp_file_name
    mat = simtypes._material(a)
    rho = simtypes._q(mat, "Density", "t/mm^3", 0.0)
    if rho <= 0:
        raise _err("The material has no mass density: a dynamic study needs one.")
    text = dynamic_input(a, open(path).read(), rho)
    with open(path, "w") as f:
        f.write(text)
    work = os.path.dirname(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    env = dict(os.environ)
    env.setdefault("OMP_NUM_THREADS", str(max(1, (os.cpu_count() or 2) - 1)))
    if progress:
        progress("%s: solving the modes and the response" % a.Label)
    from . import simxpress
    p = simxpress.run_ccx_command([fea.ccx_binary, "-i", stem], work, env, 7200)
    frd = os.path.join(work, stem + ".frd")
    log = p.stdout.decode(errors="replace")
    if p.returncode != 0 or not os.path.isfile(frd) or "*ERROR" in log:
        raise RuntimeError("CalculiX stopped:\n%s" % log[-800:])
    sets = read_frd(frd)
    modes = [(v, b) for k, v, b in sets if k == "MODAL"]
    if analysis(a) in BASE:
        return _run_base(a, modes, open(os.path.join(work, stem + ".dat"), errors="replace").read(), progress)
    resp = [(v, b) for k, v, b in sets if k != "MODAL" and "DISP" in b]
    if not resp:
        raise RuntimeError("CalculiX wrote no response (check the frequency range and the loads).")
    clear(a)
    mesh = simtypes._mesh(a)
    nodes = sorted(mesh.FemMesh.Nodes)
    harmonic = analysis(a) == "Harmonic"
    out = []
    for i, (value, blocks) in enumerate(resp, 1):
        if progress and i % 10 == 0:
            progress("%s: reading step %d of %d" % (a.Label, i, len(resp)))
        word = "Frequency" if harmonic else "Time"
        r = _make_result(a, mesh, nodes, blocks, harmonic, "%s %d (%s = %.6g)" % (word, i, word.lower(), value))
        out.append([r.Name, value])
    _set(a, STEPS, json.dumps({"steps": out, "modes": [v for v, _b in modes]}))
    doc.recompute()
    simplots.defaults(a)
    return summary(a)


# --------------------------------------------------------------------------- base excitation (Random Vibration, Response Spectrum)
def participation(dat):
    """{mode: (Hz, (Gx, Gy, Gz))} from CalculiX's eigenvalue output and participation factors (mass-normalised modes)."""
    hz, gam = {}, {}
    if "E I G E N V A L U E   O U T P U T" in dat:
        block = dat.split("E I G E N V A L U E   O U T P U T", 1)[1].split("P A R T I C I P", 1)[0]
        for m in re.finditer(r"^\s*(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$", block, re.M):
            hz[int(m.group(1))] = float(m.group(4))
    if "P A R T I C I P A T I O N   F A C T O R S" in dat:
        block = dat.split("P A R T I C I P A T I O N   F A C T O R S", 1)[1].split("E F F E C T I V E", 1)[0]
        for m in re.finditer(r"^\s*(\d+)\s+(\S+)\s+(\S+)\s+(\S+)", block, re.M):
            try:
                gam[int(m.group(1))] = (float(m.group(2)), float(m.group(3)), float(m.group(4)))
            except ValueError:
                pass
    return {k: (hz[k], gam[k]) for k in hz if k in gam}


def curve_at(points, f, loglog=True):
    ""
    import numpy as np
    pts = np.array(points, dtype=float)
    f = np.asarray(f, dtype=float)
    out = np.zeros_like(f)
    inside = (f >= pts[0, 0]) & (f <= pts[-1, 0])
    if loglog and (pts[:, 1] > 0).all():
        out[inside] = np.exp(np.interp(np.log(f[inside]), np.log(pts[:, 0]), np.log(pts[:, 1])))
    else:
        out[inside] = np.interp(f[inside], pts[:, 0], pts[:, 1])
    return out


def _grid(points, fn, zeta, per=20):
    """The frequencies the PSD is integrated over: an even log spread over the curve, and points packed around each
    natural frequency inside it (a resonance peak is about 2 zeta fn wide)."""
    import numpy as np
    lo, hi = float(points[0][0]), float(points[-1][0])
    f = [np.geomspace(lo, hi, 400)]
    w = max(zeta, 1e-3)
    for x in fn:
        if lo <= x <= hi:
            f.append(x * (1.0 + w * np.sinh(np.linspace(-4.0, 4.0, 2 * per + 1)) / np.sinh(4.0) * 40.0))
    g = np.unique(np.clip(np.concatenate(f), lo, hi))
    return g


def modal_covariance(fn, gam, zeta, psd, df_grid=None):
    """C[i, j] = integral of Re(H_i conj H_j) S(f) df: the modal coordinates' covariance under a base acceleration
    PSD S (in (mm/s^2)^2/Hz), H_i = -Gamma_i / (w_i^2 - w^2 + 2 i zeta w_i w)."""
    import numpy as np
    f = df_grid if df_grid is not None else _grid(psd, fn, zeta)
    s = curve_at(psd, f) * G * G
    w = 2 * np.pi * f[None, :]
    wi = 2 * np.pi * np.asarray(fn)[:, None]
    h = -np.asarray(gam)[:, None] / (wi ** 2 - w ** 2 + 2j * zeta * wi * w)
    integrand = (h[:, None, :] * np.conj(h[None, :, :])).real * s[None, None, :]
    trap = getattr(np, "trapezoid", None) or np.trapz
    return trap(integrand, f, axis=2)


def _cqc(fn, zeta):
    import numpy as np
    w = np.asarray(fn, dtype=float)
    b = w[None, :] / w[:, None]
    z = zeta
    return 8 * z * z * (1 + b) * b ** 1.5 / ((1 - b * b) ** 2 + 4 * z * z * b * (1 + b) ** 2)


VM = None


def _vm_matrix():
    import numpy as np
    m = np.zeros((6, 6))
    m[:3, :3] = -0.5
    m[0, 0] = m[1, 1] = m[2, 2] = 1.0
    m[3, 3] = m[4, 4] = m[5, 5] = 3.0
    return m


def _run_base(a, modes, dat, progress=None):
    """Random Vibration (RMS values) or Response Spectrum (the combined peak) from the modes, as one result."""
    import numpy as np
    from . import simplots, simtypes
    v = values(a)
    part = participation(dat)
    if not modes or not part:
        raise RuntimeError("CalculiX wrote no modes or participation factors: check the fixtures and the mesh.")
    k = DIRECTIONS.index(v["direction"])
    nums = sorted(part)[:len(modes)]
    fn = np.array([part[i][0] for i in nums])
    gam = np.array([part[i][1][k] for i in nums])
    zeta = float(v["damping"]) / 100.0
    mesh = simtypes._mesh(a)
    nodes = sorted(mesh.FemMesh.Nodes)

    def mat(block, width):
        out = np.zeros((len(nodes), width, len(nums)))
        for j, (_val, b) in enumerate(modes[:len(nums)]):
            d = b.get(block, {})
            out[:, :, j] = [d.get(nd, [0.0] * width)[:width] for nd in nodes]
        return out
    U, S, E = mat("DISP", 3), mat("STRESS", 6), (mat("TOSTRAIN", 6) if "TOSTRAIN" in modes[0][1] else None)
    if progress:
        progress("%s: summing %d modes" % (a.Label, len(nums)))
    random = v["analysis"] == BASE[0]
    if random:
        C = modal_covariance(fn, gam, zeta, v["psd"])
        rms = lambda X: np.sqrt(np.maximum(np.einsum("nci,ij,ncj->nc", X, C, X), 0.0))
        u, s, e = rms(U), rms(S), (rms(E) if E is not None else None)
        cov = np.einsum("nai,ij,nbj->nab", S, C, S)                    # the stress covariance at each node
        vm = np.sqrt(np.maximum(np.einsum("ab,nba->n", _vm_matrix(), cov), 0.0))     # Segalman's RMS von Mises
        label, word = "RMS", "RMS"
    else:
        sa = curve_at(v["spectrum"], fn) * G                           # the spectrum's acceleration at each mode
        # each mode's peak modal coordinate, with Γ's sign: CQC's cross terms need it, or two close modes
        # (a square bar's pair, split at any angle) can cancel; SRSS and Absolute Sum do not care
        q = gam * sa / (2 * np.pi * fn) ** 2
        comb = v["combination"]
        rho = _cqc(fn, zeta) if comb == "CQC" else np.eye(len(fn))

        def peak(X):
            Y = X * q[None, None, :]
            if comb == "Absolute Sum":
                return np.abs(Y).sum(axis=2)
            return np.sqrt(np.maximum(np.einsum("nci,ij,ncj->nc", Y, rho, Y), 0.0))
        u, s, e = peak(U), peak(S), (peak(E) if E is not None else None)
        vm = np.sqrt(np.maximum(0.5 * ((s[:, 0] - s[:, 1]) ** 2 + (s[:, 1] - s[:, 2]) ** 2 + (s[:, 2] - s[:, 0]) ** 2)
                                + 3.0 * (s[:, 3] ** 2 + s[:, 4] ** 2 + s[:, 5] ** 2), 0.0))
        label, word = "Maximum", "Response Spectrum"
    clear(a)
    blocks = {"DISP": {nd: list(u[i]) for i, nd in enumerate(nodes)},
              "STRESS": {nd: list(s[i]) for i, nd in enumerate(nodes)}}
    if e is not None:
        blocks["TOSTRAIN"] = {nd: list(e[i]) for i, nd in enumerate(nodes)}
    r = _make_result(a, mesh, nodes, blocks, False, "%s (%s)" % (word, v["direction"]))
    r.vonMises = [float(x) for x in vm]                                # not the von Mises of the RMS components
    _set(a, STEPS, json.dumps({"steps": [[r.Name, 0.0]], "modes": [float(x) for x in fn], "base": label,
                               "gamma": [float(x) for x in gam]}))
    a.Document.recompute()
    simplots.defaults(a)
    return summary(a)


def steps(a):
    """[(number, result, frequency Hz or time s)] in order."""
    try:
        d = json.loads(getattr(a, STEPS, "") or "{}")
    except ValueError:
        return []
    doc = a.Document
    out = []
    for i, (name, v) in enumerate(d.get("steps", []), 1):
        r = doc.getObject(name)
        if r is not None:
            out.append((i, r, float(v)))
    return out


def mode_frequencies(a):
    try:
        return [float(x) for x in json.loads(getattr(a, STEPS, "") or "{}").get("modes", [])]
    except ValueError:
        return []


def peak_step(a):
    st = steps(a)
    if not st:
        return None
    return max(st, key=lambda s: max(s[1].DisplacementLengths or [0.0]))[0]


def step_words(a, value):
    if analysis(a) in BASE:
        return "RMS values" if analysis(a) == BASE[0] else "Combined peak (%s)" % values(a)["combination"]
    return ("Frequency = %.5g Hz" % value) if analysis(a) == "Harmonic" else ("Time = %.5g s" % value)


def summary(a):
    st = steps(a)
    if not st:
        return "%s: not run" % analysis(a)
    n = peak_step(a)
    r = st[n - 1][1]
    if analysis(a) in BASE:
        v = values(a)
        what = "RMS" if analysis(a) == BASE[0] else "Peak"
        return "%s, base excitation along %s, %d modes\n%s von Mises stress: %.4g MPa\n%s displacement: %.4g mm" % (
            analysis(a), v["direction"], len(mode_frequencies(a)), what, max(r.vonMises or [0.0]), what,
            max(r.DisplacementLengths or [0.0]))
    return "%s, %d %s\nPeak at %s\nMax von Mises stress: %.4g MPa\nMax displacement: %.4g mm" % (
        analysis(a), len(st), "frequencies" if analysis(a) == "Harmonic" else "time steps", step_words(a, st[n - 1][2]),
        max(r.vonMises or [0.0]), max(r.DisplacementLengths or [0.0]))


# --------------------------------------------------------------------------- install
def install():
    from . import simplots, simtree
    if getattr(simplots, "_fw_dynamic", False):
        return
    simplots.KINDS[KIND] = ("Stress", "Displacement", "Strain")
    simplots.STUDY_WORDS.setdefault(KIND, "Dynamic")
    simtree.KIND_WORDS.setdefault(KIND, "Linear Dynamic")
    defaults0 = simplots.defaults

    def defaults(a):
        if is_dynamic(a):                      # only once the run's steps are known (not while they are read)
            if not simplots.plots(a) and steps(a):
                n = peak_step(a)
                for q in ("Stress", "Displacement", "Strain"):
                    simplots.new_plot(a, q, deformed=True, step=n)
            return simplots.plots(a)
        return defaults0(a)
    simplots.defaults = defaults
    simplots._fw_dynamic = True


# --------------------------------------------------------------------------- the PM
if Gui is not None:
    from . import simxpress as sx

    def _spin(name, lo, hi, value, decimals=3, suffix=""):
        w = QtWidgets.QDoubleSpinBox()
        w.setObjectName(name)
        w.setRange(lo, hi)
        w.setDecimals(decimals)
        w.setValue(float(value))
        if suffix:
            w.setSuffix(suffix)
        return w

    class PropertiesPM:
        """Linear Dynamic Properties: Options, then the Harmonic or Modal Time History settings, Damping."""
        PM = "Linear Dynamic Properties"

        def __init__(self, a):
            from . import simtypes
            self.a = a
            self.doc = a.Document
            v = values(a)
            self.analysis = v["analysis"]
            ob = sx._box("Options", None, self.PM)
            ol = QtWidgets.QFormLayout(ob)
            ol.addRow(QtWidgets.QLabel(self.analysis))
            self.modes = QtWidgets.QSpinBox()
            self.modes.setObjectName("SWDynModes")
            self.modes.setRange(1, 500)
            self.modes.setValue(int(v["modes"]))
            ol.addRow("Number of frequencies:", self.modes)
            self.form = [ob]
            if self.analysis in BASE:
                bb = sx._box("Base Excitation")
                bl = QtWidgets.QFormLayout(bb)
                self.direction = QtWidgets.QComboBox()
                self.direction.setObjectName("SWDynDirection")
                self.direction.addItems(["Along %s" % d for d in DIRECTIONS])
                self.direction.setCurrentIndex(DIRECTIONS.index(v["direction"]))
                self.direction.setToolTip("Uniform base excitation: every fixture moves together along this axis")
                bl.addRow("Direction:", self.direction)
                random = self.analysis == BASE[0]
                bl.addRow(QtWidgets.QLabel("Acceleration PSD curve (frequency in Hz, g^2/Hz):" if random
                                           else "Acceleration spectrum (frequency in Hz, acceleration in g):"))
                self.curve = QtWidgets.QTableWidget()
                self.curve.setObjectName("SWDynCurve")
                self.curve.setColumnCount(2)
                self.curve.setHorizontalHeaderLabels(["Frequency (Hz)", "PSD (g^2/Hz)" if random else "Acceleration (g)"])
                self.curve.verticalHeader().setVisible(False)
                self.curve.horizontalHeader().setStretchLastSection(True)
                self.curve.setFixedHeight(150)
                for f_, y in v["psd" if random else "spectrum"]:
                    self._row(f_, y)
                hb2 = QtWidgets.QHBoxLayout()
                add = QtWidgets.QPushButton("Add Point")
                add.setObjectName("SWDynAddPoint")
                add.clicked.connect(lambda: self._row(self._last_time() * 2.0 or 1.0, self._last_value()))
                rem = QtWidgets.QPushButton("Delete Point")
                rem.setObjectName("SWDynDeletePoint")
                rem.clicked.connect(self._delete)
                hb2.addWidget(add)
                hb2.addWidget(rem)
                bl.addRow(self.curve)
                bl.addRow(hb2)
                self.form.append(bb)
                if not random:
                    mb = sx._box("Mode Combination Method")
                    ml = QtWidgets.QFormLayout(mb)
                    self.combination = QtWidgets.QComboBox()
                    self.combination.setObjectName("SWDynCombination")
                    self.combination.addItems(list(COMBINATIONS))
                    self.combination.setCurrentIndex(COMBINATIONS.index(v["combination"]))
                    ml.addRow("Combine the modes by:", self.combination)
                    self.form.append(mb)
            elif self.analysis == "Harmonic":
                hb = sx._box("Frequency Range")
                hl = QtWidgets.QFormLayout(hb)
                self.f_lo = _spin("SWDynLower", 0.0, 1e9, v["f_lo"], 3, " Hz")
                self.f_hi = _spin("SWDynUpper", 0.0, 1e9, v["f_hi"], 3, " Hz")
                self.points = QtWidgets.QSpinBox()
                self.points.setObjectName("SWDynPoints")
                self.points.setRange(2, 1000)
                self.points.setValue(int(v["points"]))
                self.bias = _spin("SWDynBias", 1.0, 100.0, v["bias"], 2)
                hl.addRow("Lower limit:", self.f_lo)
                hl.addRow("Upper limit:", self.f_hi)
                hl.addRow("Number of points:", self.points)
                hl.addRow("Bias parameter:", self.bias)
                for w, tip in ((self.points, "Points between the natural frequencies in the range (CalculiX)"),
                               (self.bias, "Packs the points near each natural frequency: 1 spreads them evenly")):
                    w.setToolTip(tip)
                self.form.append(hb)
            else:
                tb = sx._box("Solution Time")
                tl = QtWidgets.QFormLayout(tb)
                self.end = _spin("SWDynEnd", 1e-9, 1e6, v["end"], 8, " s")
                self.inc = _spin("SWDynIncrement", 1e-9, 1e6, v["increment"], 8, " s")
                tl.addRow("End time:", self.end)
                tl.addRow("Time increment:", self.inc)
                cb = sx._box("Variation with Time")
                cl = QtWidgets.QVBoxLayout(cb)
                cl.addWidget(QtWidgets.QLabel("The loads times this curve (time in s, factor):"))
                self.curve = QtWidgets.QTableWidget()
                self.curve.setObjectName("SWDynCurve")
                self.curve.setColumnCount(2)
                self.curve.setHorizontalHeaderLabels(["Time (s)", "Factor"])
                self.curve.verticalHeader().setVisible(False)
                self.curve.horizontalHeader().setStretchLastSection(True)
                self.curve.setFixedHeight(150)
                for t, f in v["curve"]:
                    self._row(t, f)
                hb2 = QtWidgets.QHBoxLayout()
                add = QtWidgets.QPushButton("Add Point")
                add.setObjectName("SWDynAddPoint")
                add.clicked.connect(lambda: self._row(self._last_time() + float(self.inc.value()) * 10, 1.0))
                rem = QtWidgets.QPushButton("Delete Point")
                rem.setObjectName("SWDynDeletePoint")
                rem.clicked.connect(self._delete)
                hb2.addWidget(add)
                hb2.addWidget(rem)
                cl.addWidget(self.curve)
                cl.addLayout(hb2)
                self.form += [tb, cb]
            db = sx._box("Damping")
            dl = QtWidgets.QFormLayout(db)
            self.damping = _spin("SWDynDamping", 0.0, 99.0, v["damping"], 3, " %")
            self.damping.setToolTip("Modal damping: a ratio of critical damping, for all the modes")
            dl.addRow("Modal damping ratio:", self.damping)
            self.form.append(db)

        def _row(self, t, f):
            i = self.curve.rowCount()
            self.curve.insertRow(i)
            self.curve.setItem(i, 0, QtWidgets.QTableWidgetItem("%.9g" % t))
            self.curve.setItem(i, 1, QtWidgets.QTableWidgetItem("%.9g" % f))

        def _last_time(self):
            n = self.curve.rowCount()
            try:
                return float(self.curve.item(n - 1, 0).text()) if n else 0.0
            except (AttributeError, ValueError):
                return 0.0

        def _last_value(self):
            n = self.curve.rowCount()
            try:
                return float(self.curve.item(n - 1, 1).text()) if n else 1.0
            except (AttributeError, ValueError):
                return 1.0

        def _delete(self):
            rows = sorted({i.row() for i in self.curve.selectedIndexes()}, reverse=True) or [self.curve.rowCount() - 1]
            for r in rows:
                if self.curve.rowCount() > 2 and r >= 0:
                    self.curve.removeRow(r)

        def _points(self):
            from . import simpms
            pts = []
            for i in range(self.curve.rowCount()):
                try:
                    pts.append([float(self.curve.item(i, 0).text()), float(self.curve.item(i, 1).text())])
                except (AttributeError, ValueError):
                    raise simpms.SetupError("Row %d of the curve is not two numbers." % (i + 1))
            return pts

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def reject(self):
            Gui.Control.closeDialog()
            return True

        def accept(self):
            from . import simpms, simtypes
            kw = {"modes": self.modes.value(), "damping": self.damping.value()}
            self.doc.openTransaction(self.PM)
            try:
                if self.analysis in BASE:
                    kw.update(direction=DIRECTIONS[self.direction.currentIndex()])
                    kw["psd" if self.analysis == BASE[0] else "spectrum"] = self._points()
                    if self.analysis == BASE[1]:
                        kw["combination"] = self.combination.currentText()
                elif self.analysis == "Harmonic":
                    kw.update(f_lo=self.f_lo.value(), f_hi=self.f_hi.value(), points=self.points.value(), bias=self.bias.value())
                else:
                    kw.update(end=self.end.value(), increment=self.inc.value(), curve=self._points())
                set_values(self.a, **kw)
            except simpms.SetupError as e:
                self.doc.abortTransaction()
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), self.PM, str(e))
                return False
            self.doc.commitTransaction()
            Gui.Control.closeDialog()
            simtypes._refresh()
            return True

    def open_properties(a):
        from . import simtypes
        return simtypes._show(PropertiesPM(a))
else:
    def open_properties(a):
        return None
