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
except ImportError:  # pragma: no cover
    Gui = None

KIND = "topology"
TOPO = "FwTopology"            # the study's options (json)
RHO = "FwTopoDensity"          # the last run's densities (json: ids, rho)
SHAPE = "FwTopoShape"          # the name of the Material Mass shape shown
GOALS = ("Best Stiffness to Weight ratio", "Minimize Maximum Displacement", "Minimize Mass with Displacement constraint")
DISP_MODES = ("Specify value", "Factor of the initial maximum displacement")
DEFAULTS = {"goal": GOALS[0], "reduce": 50.0, "preserve_loads": True, "faces": [], "iterations": 40,
            "threshold": 0.5, "disp_mode": DISP_MODES[1], "disp_limit": 1.0, "disp_factor": 2.0,
            "thickness_on": False, "min_thickness": 5.0, "demold_on": False, "demold_ref": "", "demold_reverse": False,
            "demold_both": False, "sym_on": False, "sym_planes": []}
PENAL = 3.0                    # SIMP penalty
RHO_MIN = 0.001
MOVE = 0.2
LEVELS = 50                    # density levels written as materials
QUANTITY, COMP = "Material Mass", "MASS"


# --------------------------------------------------------------------------- options
def is_topology(a):
    try:
        from . import simtypes
        return a is not None and getattr(a, simtypes.TYPE, "") == KIND
    except Exception:
        return False


def values(a):
    v = dict(DEFAULTS)
    try:
        v.update(json.loads(getattr(a, TOPO, "") or "{}"))
    except ValueError:
        pass
    return v


def _set(o, name, value):
    if name not in o.PropertiesList:
        o.addProperty("App::PropertyString", name, "FreeCAD", "")
        try:
            o.setEditorMode(name, 2)
        except Exception as _fw_err:
            _fw_log("simtopology.py:mode", _fw_err)
    setattr(o, name, value)


def set_values(a, **kw):
    from . import simpms
    v = values(a)
    v.update(kw)
    r = float(v["reduce"])
    if not 5.0 <= r <= 95.0:
        raise simpms.SetupError("Reduce mass by 5 % to 95 %.")
    if v["goal"] not in GOALS:
        raise simpms.SetupError("Pick a goal.")
    t = float(v["threshold"])
    if not 0.0 < t < 1.0:
        raise simpms.SetupError("The mass level is between Light and Heavy.")
    if v["goal"] == GOALS[2]:
        if v["disp_mode"] not in DISP_MODES:
            raise simpms.SetupError("Pick how the displacement constraint is given.")
        if v["disp_mode"] == DISP_MODES[0] and float(v["disp_limit"]) <= 0:
            raise simpms.SetupError("Give the largest displacement allowed.")
        if v["disp_mode"] == DISP_MODES[1] and float(v["disp_factor"]) <= 1.0:
            raise simpms.SetupError("Give a factor above 1: the full part already moves that much.")
    if v.get("thickness_on") and float(v["min_thickness"]) <= 0:
        raise simpms.SetupError("Give the minimum thickness.")
    from . import simtypes
    if v.get("demold_on") and simtypes.direction_of(a.Document, v.get("demold_ref", "")) is None:
        raise simpms.SetupError("Pick the demold direction (a plane, a flat face or a straight edge).")
    if v.get("sym_on"):
        planes = list(v.get("sym_planes", []))
        if not 1 <= len(planes) <= 3 or any(plane_of(a.Document, r) is None for r in planes):
            raise simpms.SetupError("Pick one, two or three symmetry planes (planes or flat faces).")
    _set(a, TOPO, json.dumps(v))
    return v


def plane_of(doc, ref):
    """(a point, the unit normal) of a plane or a flat face, or None."""
    from . import simtypes
    n = simtypes.direction_of(doc, ref)
    if n is None or n.Length < 1e-12:
        return None
    name, _c, sub = (ref or "").partition(":")
    o = doc.getObject(name)
    try:
        if sub:
            el = o.Shape.getElement(sub)
            if not sub.startswith("Face"):
                return None
            p = el.Vertexes[0].Point
        else:
            p = o.Placement.Base
    except Exception:
        return None
    n = App.Vector(n)
    n.normalize()
    return p, n


def control_rows(a):
    ""
    v = values(a)
    out = []
    if v.get("preserve_loads", True) or v.get("faces"):
        out.append("Preserved Region")
    if v.get("thickness_on"):
        out.append("Thickness Control (-Min: %g mm-)" % float(v["min_thickness"]))
    if v.get("demold_on"):
        out.append("Demold Direction (-%s-)" % ("Both directions" if v.get("demold_both") else "One direction"))
    if v.get("sym_on"):
        out.append("Symmetry (-%s-)" % {1: "Half", 2: "Quarter", 3: "1/8"}.get(len(v.get("sym_planes", [])), ""))
    return out


def new_study(doc, name, obj=None):
    """A Topology Study: a static study (solver, material, mesh) with Goals and Constraints."""
    from . import addintabs, simtypes
    obj = obj or addintabs._main_solid(doc)
    if obj is None:
        raise ValueError("The document has no solid body to study.")
    if simtypes._assembly(doc) is not None:
        raise ValueError("A Topology Study works on a part.")
    a = addintabs.new_study(doc, obj, "static", name)
    _set(a, simtypes.TYPE, KIND)
    _set(a, TOPO, json.dumps(dict(DEFAULTS)))
    return a


def densities(a):
    try:
        d = json.loads(getattr(a, RHO, "") or "{}")
        return dict(zip(d.get("ids", []), d.get("rho", [])))
    except ValueError:
        return {}


def history(a):
    try:
        return json.loads(getattr(a, RHO, "") or "{}").get("history", [])
    except ValueError:
        return []


# --------------------------------------------------------------------------- the mesh
def _mesh_obj(a):
    for o in a.Group:
        if o.isDerivedFrom("Fem::FemMeshObject") and "Result" not in o.TypeId:
            return o
    return None


def mesh_data(fm):
    """(ids, corners {id: 4 node ids}, centroids array, volumes array) of the solid elements."""
    import numpy as np
    nodes = fm.Nodes
    ids, corners, cents, vols = [], {}, [], []
    for e in fm.Volumes:
        en = fm.getElementNodes(e)
        c = en[:4]
        p = [nodes[n] for n in c]
        v = abs((p[1] - p[0]).dot((p[2] - p[0]).cross(p[3] - p[0]))) / 6.0
        ids.append(e)
        corners[e] = c
        cents.append([(p[0].x + p[1].x + p[2].x + p[3].x) / 4.0, (p[0].y + p[1].y + p[2].y + p[3].y) / 4.0,
                      (p[0].z + p[1].z + p[2].z + p[3].z) / 4.0])
        vols.append(v)
    return ids, corners, np.array(cents), np.array(vols)


def neighbours(cents, rmin):
    """The density filter's weights: for each element, (indices, weights) of the elements within rmin."""
    import numpy as np
    out = []
    n = len(cents)
    for s in range(0, n, 400):
        block = cents[s:s + 400]
        d = np.sqrt(((block[:, None, :] - cents[None, :, :]) ** 2).sum(axis=2))
        for row in d:
            j = np.nonzero(row < rmin)[0]
            out.append((j, rmin - row[j]))
    return out


def preserved(a, fm, ids):
    """Indices of the elements that keep full material: those touching a preserved face."""
    v = values(a)
    faces = []
    if v.get("preserve_loads", True):
        for o in a.Group:
            refs = getattr(o, "References", None)
            if not refs or o.isDerivedFrom("Fem::FemMeshObject"):
                continue
            for obj, subs in refs:
                for s in subs:
                    if s.startswith("Face"):
                        faces.append((obj, s))
    for ref in v.get("faces", []):
        name, _c, sub = ref.partition(":")
        obj = a.Document.getObject(name)
        if obj is not None and sub:
            faces.append((obj, sub))
    nodes = set()
    for obj, sub in faces:
        try:
            nodes.update(fm.getNodesByFace(obj.Shape.getElement(sub)))
        except Exception as _fw_err:
            _fw_log("simtopology.py:face", _fw_err)
    if not nodes:
        return []
    return [i for i, e in enumerate(ids) if nodes.intersection(fm.getElementNodes(e))]


# --------------------------------------------------------------------------- the solver input
SECTION = re.compile(r"\*SOLID SECTION, ELSET=([^,\n]+), MATERIAL=([^\n]+)\n")


def material_of(text):
    """(E, nu, the rest of the material card) of the input's material."""
    m = re.search(r"\*ELASTIC\n\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)", text)
    if m is None:
        raise RuntimeError("The study's material has no elastic modulus.")
    return float(m.group(1)), float(m.group(2))


def topo_input(text, ids, rho):
    """The input with one material and section per density level, and the element energies printed."""
    e0, nu = material_of(text)
    if len(SECTION.findall(text)) != 1:
        raise RuntimeError("A Topology Study works on one solid body with one material.")
    levels = {}
    for e, r in zip(ids, rho):
        levels.setdefault(max(1, int(round(r * LEVELS))), []).append(e)
    cards = ["** Topology Study: one material per relative mass density level"]
    for k in sorted(levels):
        cards.append("*ELSET,ELSET=TOPO%d" % k)
        els = levels[k]
        for i in range(0, len(els), 12):
            cards.append(", ".join(str(x) for x in els[i:i + 12]) + ",")
        r = max(RHO_MIN, k / float(LEVELS))
        cards.append("*MATERIAL, NAME=TOPO%d\n*ELASTIC\n%.6g,%.6g" % (k, e0 * r ** PENAL, nu))
        cards.append("*SOLID SECTION, ELSET=TOPO%d, MATERIAL=TOPO%d\n" % (k, k))
    text = SECTION.sub("", text, count=1)
    i = text.index("*STEP")
    text = text[:i] + "\n".join(cards) + "\n" + text[i:]
    j = text.rindex("*END STEP")
    return text[:j] + "*EL PRINT, ELSET=Eall\nELSE\n" + text[j:]


def energies_all(dat):
    """[{element: internal energy}] of each step in the .dat file (the last block of each time)."""
    blocks, cur, t = {}, None, None
    for line in open(dat, errors="replace"):
        if "internal energy (element" in line:
            m = re.search(r"time\s+([-+0-9.eE]+)", line)
            t = float(m.group(1)) if m else len(blocks)
            cur = blocks[t] = {}
            continue
        if cur is not None:
            parts = line.split()
            if len(parts) == 2:
                try:
                    cur[int(parts[0])] = float(parts[1])
                    continue
                except ValueError:
                    pass
            if cur and not line.strip():
                cur = None
    return [blocks[k] for k in sorted(blocks)]


def displacements(dat):
    """{node: (ux, uy, uz)} of the first displacement block of the .dat file."""
    out, on = {}, False
    for line in open(dat, errors="replace"):
        if "displacements (vx,vy,vz)" in line:
            if out:
                break
            on = True
            continue
        if on:
            parts = line.split()
            if len(parts) == 4:
                try:
                    out[int(parts[0])] = tuple(float(x) for x in parts[1:])
                    continue
                except ValueError:
                    pass
            if out and not line.strip():
                break
    return out


def _cload_rows(loads):
    """(the load blocks without their *CLOAD cards, {(node, dof): value} of those cards)."""
    keep, rows, on = [], {}, False
    for line in loads.splitlines():
        if line.startswith("**"):
            keep.append(line)
            continue
        if line.startswith("*"):
            on = line.split(",")[0].strip().upper() == "*CLOAD"
            if on:
                continue
        elif on and line.strip():
            n, d, val = [x.strip() for x in line.split(",")[:3]]
            rows[(int(n), int(d))] = rows.get((int(n), int(d)), 0.0) + float(val)
            continue
        keep.append(line)
    return "\n".join(keep) + "\n", rows


def _boundaries(bcs):
    """("", "") when every fixture holds at zero. With an enforced displacement (a *BOUNDARY value): the unit-load
    step gets the fixtures at zero (its own load only, so the mutual energy is right) and the third step the fixtures
    as they were."""
    def value(ln):
        f = [x.strip() for x in ln.split(",")]
        return f, (len(f) > 3 and f[3] not in ("", "0", "0.0") and abs(float(f[3])) > 0.0)
    rows = [ln for ln in bcs.splitlines() if ln.strip() and not ln.startswith("*")]
    try:
        if not any(value(ln)[1] for ln in rows):
            return "", ""
    except ValueError:
        return "", ""
    zero = "".join(",".join(value(ln)[0][:3]) + "\n" for ln in rows)
    return "*BOUNDARY, OP=NEW\n" + zero, "*BOUNDARY, OP=NEW\n" + "".join(ln + "\n" for ln in rows)


def disp_input(text, node, direction):
    """Three load cases in one run: the loads (with every node's displacement), a unit load at node along direction,
    and both together; each step prints the element energies."""
    from . import simdynamic
    head, bcs, loads = simdynamic._split_step(text)
    i = text.upper().find("\n*STEP")
    j = text.upper().rfind("*END STEP")
    step1 = text[i + 1:j] + "*NODE PRINT, NSET=Nall\nU\n*END STEP\n"
    rest, rows = _cload_rows(loads)
    unit = {(node, k + 1): c for k, c in enumerate(direction) if abs(c) > 1e-12}
    both = dict(rows)
    for k, c in unit.items():
        both[k] = both.get(k, 0.0) + c
    card = lambda r: "*CLOAD, OP=NEW\n" + "".join("%d,%d,%.9g\n" % (n, d, val) for (n, d), val in sorted(r.items()))
    out = "*EL PRINT, ELSET=Eall\nELSE\n*END STEP\n"
    zero, keep = _boundaries(bcs)
    step2 = "*STEP\n*STATIC\n" + zero + card(unit) + "*DLOAD, OP=NEW\n" + out
    step3 = "*STEP\n*STATIC\n" + keep + card(both) + "*DLOAD, OP=NEW\n" + rest.replace("*DLOAD\n", "*DLOAD\n") + out
    return text[:i + 1] + step1 + step2 + step3 + text[j + len("*END STEP"):]


def _nearest(points, cents):
    """For each point the index of the nearest centroid. A k-d tree when SciPy is there (FreeCAD ships it); else
    blocks small enough to stay near 100 MB whatever the mesh size (the |a|^2 + |b|^2 - 2ab form, no n x n x 3)."""
    import numpy as np
    try:
        from scipy.spatial import cKDTree
        return cKDTree(cents).query(points)[1]
    except Exception:
        pass
    n = len(cents)
    cc = (cents ** 2).sum(axis=1)
    rows = max(16, int(1.2e7 // max(n, 1)))
    out = np.empty(len(points), dtype=int)
    for s in range(0, len(points), rows):
        p = points[s:s + rows]
        d = (p ** 2).sum(axis=1)[:, None] + cc[None, :] - 2.0 * (p @ cents.T)
        out[s:s + rows] = d.argmin(axis=1)
    return out


def _mirror_groups(cents, planes):
    """Groups of element indices that the symmetry planes map onto each other (nearest centroid), averaged as one."""
    import numpy as np
    n = len(cents)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for p, nrm in planes:
        p = np.array([p.x, p.y, p.z])
        nv = np.array([nrm.x, nrm.y, nrm.z])
        mir = cents - 2.0 * ((cents - p) @ nv)[:, None] * nv[None, :]
        for k, j in enumerate(_nearest(mir, cents)):
            a_, b_ = find(k), find(int(j))
            if a_ != b_:
                parent[a_] = b_
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return [np.array(g) for g in groups.values() if len(g) > 1]

def _columns(cents, d, h):
    """Element indices in columns along d (cells of size h across it), each sorted along d."""
    import numpy as np
    d = np.array([d.x, d.y, d.z], dtype=float)
    d /= np.linalg.norm(d)
    u = np.cross(d, [1.0, 0.0, 0.0])
    if np.linalg.norm(u) < 1e-6:
        u = np.cross(d, [0.0, 1.0, 0.0])
    u /= np.linalg.norm(u)
    w = np.cross(d, u)
    s = cents @ d
    cells = {}
    for i, (a_, b_) in enumerate(zip(np.floor(cents @ u / h), np.floor(cents @ w / h))):
        cells.setdefault((a_, b_), []).append(i)
    return [np.array(sorted(c, key=lambda i: s[i])) for c in cells.values() if len(c) > 1]


def manufacturing(a, cents, h):
    """The projections the Manufacturing Controls make: f(rho) -> rho (symmetry averages, demold fills undercuts)."""
    import numpy as np
    v = values(a)
    doc = a.Document
    groups = []
    if v.get("sym_on"):
        planes = [plane_of(doc, r) for r in v.get("sym_planes", [])]
        groups = _mirror_groups(cents, [x for x in planes if x is not None])
    cols, both = [], bool(v.get("demold_both"))
    if v.get("demold_on"):
        from . import simtypes
        d = simtypes.direction_of(doc, v.get("demold_ref", ""))
        if d is not None:
            d = d * (-1.0 if v.get("demold_reverse") else 1.0)
            cols = _columns(cents, d, h)

    def demold(rho):
        for c in cols:                         # sorted along the pull direction: the tool comes from the far end
            r = rho[c]
            up = np.maximum.accumulate(r[::-1])[::-1]          # the most material at or beyond each element
            if both:
                down = np.maximum.accumulate(r)
                fill = np.minimum(np.concatenate([up[1:], [0.0]]), np.concatenate([[0.0], down[:-1]]))
            else:
                fill = np.concatenate([up[1:], [0.0]])
            rho[c] = np.maximum(r, fill)
        return rho

    def project(rho):
        rho = rho.copy()
        for g in groups:
            rho[g] = rho[g].mean()
        if not cols:
            return rho
        for _i in range(20):                   # both controls: fill undercuts and keep the mirror's more, until
            before = rho.copy()                # neither changes anything (each only adds material)
            rho = demold(rho)
            for g in groups:
                rho[g] = rho[g].max()
            if np.abs(rho - before).max() < 1e-9:
                break
        return rho
    return project


def energies(dat):
    """{element: internal energy} from the .dat file's ELSE block."""
    out = {}
    on = False
    for line in open(dat, errors="replace"):
        if "internal energy (element" in line:
            on = True
            out = {}                   # the last block (the last increment)
            continue
        if on:
            parts = line.split()
            if len(parts) == 2:
                try:
                    out[int(parts[0])] = float(parts[1])
                    continue
                except ValueError:
                    pass
            if out and not line.strip():
                on = False
    return out


# --------------------------------------------------------------------------- the run
def _ccx(fea, work, stem, env, it):
    from . import simxpress
    p = simxpress.run_ccx_command([fea.ccx_binary, "-i", stem], work, env, 3600)
    dat = os.path.join(work, stem + ".dat")
    if p.returncode != 0 or not os.path.isfile(dat):
        raise RuntimeError("CalculiX stopped in pass %d:\n%s" % (it, p.stdout.decode(errors="replace")[-600:]))
    return dat


def run(a, progress=None):
    """Optimises the study: returns a summary text. progress(it, objective, mass fraction, change) after each pass."""
    import numpy as np
    from femtools import ccxtools
    from . import addintabs
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
    base = open(path).read()
    fm = _mesh_obj(a).FemMesh
    ids, _corners, cents, vols = mesh_data(fm)
    n = len(ids)
    if n == 0:
        raise RuntimeError("The mesh has no solid elements.")
    v = values(a)
    goal = v["goal"]
    frac = 1.0 - float(v["reduce"]) / 100.0
    keep = np.zeros(n, dtype=bool)
    keep[preserved(a, fm, ids)] = True
    size = float(np.mean(vols)) ** (1.0 / 3.0)
    rmin = 1.6 * size
    if v.get("thickness_on"):                              # Thickness Control: members no thinner than this
        rmin = max(rmin, 0.5 * float(v["min_thickness"]))
    filt = neighbours(cents, rmin)
    project = manufacturing(a, cents, 1.2 * size)
    rho = np.full(n, 1.0 if goal == GOALS[2] else frac)
    rho[keep] = 1.0
    rho = project(rho)
    work = os.path.dirname(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    env = dict(os.environ)
    env.setdefault("OMP_NUM_THREADS", str(max(1, (os.cpu_count() or 2) - 1)))
    hist = []
    total = float(vols.sum())
    disp_goal = goal != GOALS[0]
    node, direction, limit, best = None, None, None, None
    if disp_goal:                                          # where the part moves most, before the first pass
        t0 = topo_input(base, ids, rho)
        if "*EL PRINT, ELSET=Eall\nELSE\n" not in t0:
            raise RuntimeError("The CalculiX input has no element energy output: the study cannot be optimised.")
        with open(path, "w") as f:
            f.write(t0.replace("*EL PRINT, ELSET=Eall\nELSE\n", "*NODE PRINT, NSET=Nall\nU\n"))
        u = displacements(_ccx(fea, work, stem, env, 0))
        if not u:
            raise RuntimeError("CalculiX gave no displacements for the first pass: check the fixtures and loads, "
                               "then run the static study on its own.")
        node = max(u, key=lambda k: sum(c * c for c in u[k]))
        mag = sum(c * c for c in u[node]) ** 0.5
        if mag <= 0:
            raise RuntimeError("The loads do not move the part: there is no displacement to work on.")
        direction = [c / mag for c in u[node]]
        if goal == GOALS[2]:
            limit = float(v["disp_limit"]) if v["disp_mode"] == DISP_MODES[0] else float(v["disp_factor"]) * mag
    for it in range(1, int(v.get("iterations", 40)) + 1):
        with open(path, "w") as f:
            t = topo_input(base, ids, rho)
            f.write(disp_input(t, node, direction) if disp_goal else t)
        dat = _ccx(fea, work, stem, env, it)
        if disp_goal:
            e1, e2, e3 = (energies_all(dat) + [{}, {}, {}])[:3]
            u = displacements(dat)
            un = u.get(node, (0.0, 0.0, 0.0))
            obj = abs(sum(c * d for c, d in zip(un, direction)))       # the displacement along the unit load
            mutual = np.array([e3.get(e, 0.0) - e1.get(e, 0.0) - e2.get(e, 0.0) for e in ids])
            dc = -PENAL * mutual / np.maximum(rho, RHO_MIN)
            worst = max(u, key=lambda k: sum(c * c for c in u[k])) if u else node
            size = lambda k: sum(c * c for c in u.get(k, (0.0, 0.0, 0.0))) ** 0.5
            if worst != node and size(worst) > 1.02 * size(node):       # follow the node that moves most (clearly)
                node = worst
                mag = sum(c * c for c in u[node]) ** 0.5
                direction = [c / mag for c in u[node]] if mag > 0 else direction
            peak = max((sum(c * c for c in x) ** 0.5 for x in u.values()), default=obj)
        else:
            en = energies(dat)
            uu = np.array([en.get(e, 0.0) for e in ids])
            obj = 2.0 * float(uu.sum())
            dc = -PENAL * uu / np.maximum(rho, RHO_MIN)                # dC/drho (U grows as rho^p)
            peak = None
        if goal == GOALS[2]:                               # keep the lightest layout that met the limit
            m_now = float((rho * vols).sum() / total)
            if peak <= 1.02 * limit and (best is None or m_now < best[1]):
                best = (rho.copy(), m_now, peak, it)
        elif goal == GOALS[1]:                             # keep the stiffest layout at the mass asked for
            m_now = float((rho * vols).sum() / total)
            if m_now <= frac * 1.01 and (best is None or peak < best[2]):
                best = (rho.copy(), m_now, peak, it)
        dcf = np.empty(n)
        for i, (j, w) in enumerate(filt):                  # Sigmund's sensitivity filter
            dcf[i] = (w * rho[j] * dc[j]).sum() / (max(rho[i], 1e-3) * w.sum())
        dcf = np.minimum(dcf, -1e-30)
        lo, hi = 1e-12, 1e12

        move = MOVE if goal != GOALS[2] else 0.5 * MOVE
        dcr = np.minimum(dc, 0.0)                          # the raw sensitivities, for the displacement it predicts

        def step(mid):
            new = rho * np.sqrt(-dcf / (mid * vols / total))
            new = np.clip(new, np.maximum(RHO_MIN, rho - move), np.minimum(1.0, rho + move))
            new[keep] = 1.0
            return project(new)
        while hi / lo > 1.0 + 1e-6:
            mid = (lo * hi) ** 0.5
            new = step(mid)
            if goal == GOALS[2]:                           # the least mass whose predicted displacement is the limit
                aim = limit * min(1.0, limit / peak)       # over the limit now: aim below it, by as much
                over = peak * (1.0 + float((dcr * (new - rho)).sum()) / max(obj, 1e-30)) > aim
                if over:
                    hi = mid
                else:
                    lo = mid
            elif (new * vols).sum() > frac * total:        # optimality criteria: the mass constraint
                lo = mid
            else:
                hi = mid
        new = step(lo if goal == GOALS[2] else (lo * hi) ** 0.5)
        change = float(np.abs(new - rho).max())
        rho = new
        mass = float((rho * vols).sum() / total)
        hist.append([it, obj if peak is None else peak, mass, change])
        if progress is not None:
            progress(it, hist[-1][1], mass, change)
        if it >= 8 and change < 0.01:
            break
    if goal in (GOALS[1], GOALS[2]) and best is not None:  # the best layout a pass found (lightest / least moving)
        rho = best[0]
        hist.append([len(hist) + 1, best[2], best[1], 0.0])
    _set(a, RHO, json.dumps({"ids": ids, "rho": [round(float(r), 4) for r in rho], "history": hist,
                             "frac": frac, "rmin": rmin, "goal": goal, "limit": limit,
                             "chosen": best[3] if goal == GOALS[2] and best is not None else None}))
    with open(path, "w") as f:                             # the last layout's stresses, as the results
        f.write(topo_input(base, ids, rho))
    _ccx(fea, work, stem, env, len(hist) + 1)
    try:
        fea.load_results()
    except Exception as _fw_err:
        _fw_log("simtopology.py:load", _fw_err)
    doc.recompute()
    return summary(a)


def run_meta(a):
    try:
        d = json.loads(getattr(a, RHO, "") or "{}")
    except ValueError:
        return {}
    return {k: d.get(k) for k in ("frac", "rmin", "goal", "limit")}


def summary(a):
    h = history(a)
    if not h:
        return "Topology Study: not run"
    v = values(a)
    meta = run_meta(a)
    goal = meta.get("goal") or v["goal"]
    reduce = 100.0 * (1.0 - meta["frac"]) if meta.get("frac") is not None else v["reduce"]    # as the run had it
    if goal == GOALS[0]:
        return ("Topology Study, %d passes\nGoal: %s, reduce mass by %g %%\nMass kept: %.1f %%\nCompliance: %.4g N.mm "
                "(first pass %.4g N.mm)") % (len(h), goal, reduce, h[-1][2] * 100.0, h[-1][1], h[0][1])
    head = ("reduce mass by %g %%" % reduce) if goal == GOALS[1] else ("displacement limit %.4g mm" % (meta.get("limit") or 0))
    return ("Topology Study, %d passes\nGoal: %s, %s\nMass kept: %.1f %%\nMax displacement: %.4g mm "
            "(first pass %.4g mm)") % (len(h), goal, head, h[-1][2] * 100.0, h[-1][1], h[0][1])


# --------------------------------------------------------------------------- the Material Mass shape
def kept_triangles(a, fm, threshold):
    """The outer triangles of the elements with density >= threshold."""
    rho = densities(a)
    nodes = fm.Nodes
    count = {}
    for e, r in rho.items():
        if r < threshold:
            continue
        c = fm.getElementNodes(e)[:4]
        for tri in ((c[0], c[1], c[2]), (c[0], c[1], c[3]), (c[0], c[2], c[3]), (c[1], c[2], c[3])):
            key = tuple(sorted(tri))
            if key in count:
                count[key][1] += 1
            else:
                fourth = [x for x in c if x not in tri][0]
                count[key] = [(tri, fourth), 1]
    out = []
    for (tri, fourth), k in count.values():
        if k != 1:
            continue
        p = [nodes[x] for x in tri]
        nrm = (p[1] - p[0]).cross(p[2] - p[0])
        if nrm.dot(nodes[fourth] - p[0]) > 0:              # outward
            p = [p[0], p[2], p[1]]
        out.append(p)
    return out


def make_mesh(a, threshold, smooth=0):
    import Mesh
    m = _mesh_obj(a)
    if m is None or not densities(a):
        raise RuntimeError("Run the study first.")
    tris = kept_triangles(a, m.FemMesh, threshold)
    mesh = Mesh.Mesh()
    for p in tris:
        mesh.addFacet(p[0], p[1], p[2])
    if smooth:
        try:
            mesh.smooth(Method="Taubin", Iteration=smooth)
        except TypeError:
            mesh.smooth(smooth)
    return mesh


SHOWN = {"hidden": [], "a": None}


def show(a, name=None):
    """Shows Material Mass at the study's level over the hidden part."""
    from . import addintabs
    v = values(a)
    mesh = make_mesh(a, float(v["threshold"]))
    doc = a.Document
    o = doc.getObject(getattr(a, SHAPE, "") or "") if SHAPE in a.PropertiesList else None
    if o is None:
        o = doc.addObject("Mesh::Feature", "MaterialMass")
        _set(a, SHAPE, o.Name)
    o.Label = "Material Mass (%s)" % a.Label
    o.Mesh = mesh
    try:
        vo = o.ViewObject
        vo.ShapeColor = (0.62, 0.66, 0.70)
        vo.Lighting = "One side"
        vo.Visibility = True
        if "ShowInTree" in vo.PropertiesList:
            vo.ShowInTree = False              # a plot's display, not a feature of the part
    except Exception as _fw_err:
        _fw_log("simtopology.py:colour", _fw_err)
    solid = addintabs._main_solid(doc)
    if solid is not None and solid.ViewObject is not None and solid.Visibility:
        solid.Visibility = False
        SHOWN["hidden"] = [solid.Name]
    SHOWN["a"] = a
    doc.recompute()
    return {"triangles": mesh.CountFacets, "threshold": v["threshold"]}


def hide(a=None):
    a = a or SHOWN.get("a")
    if a is None:
        return
    try:
        doc = a.Document
        o = doc.getObject(getattr(a, SHAPE, "") or "") if SHAPE in a.PropertiesList else None
        if o is not None:
            o.Visibility = False
        for n in SHOWN.get("hidden", []):
            s = doc.getObject(n)
            if s is not None:
                s.Visibility = True
    except Exception as _fw_err:
        _fw_log("simtopology.py:hide", _fw_err)
    SHOWN.update(hidden=[], a=None)


def export_smoothed(a):
    """Export Smoothed Mesh: a smoothed mesh of the shape at the study's level, kept in the document."""
    v = values(a)
    mesh = make_mesh(a, float(v["threshold"]), smooth=20)
    doc = a.Document
    o = doc.addObject("Mesh::Feature", "SmoothedMesh")
    o.Label = "Smoothed Mesh (%s)" % a.Label
    o.Mesh = mesh
    doc.recompute()
    return o


def mass_kept(a, threshold=None):
    """The share of the part's volume above the level (0..1)."""
    rho = densities(a)
    if not rho:
        return 0.0
    m = _mesh_obj(a)
    if m is None:
        return 0.0
    _ids, _c, _cents, vols = mesh_data(m.FemMesh)
    t = float(values(a)["threshold"] if threshold is None else threshold)
    tot = float(vols.sum()) or 1.0
    return float(sum(v for e, v in zip(_ids, vols) if rho.get(e, 0.0) >= t)) / tot


# --------------------------------------------------------------------------- PMs
if Gui is not None:
    class GoalsPM:
        """Goals and Constraints (the three goals, the mass or displacement constraint) with the Manufacturing
        Controls: Preserved Region, Thickness Control, Demold Direction, Symmetry."""
        PM = "Goals and Constraints"

        def __init__(self, a):
            from . import simxpress as sx
            self.a, self.doc = a, a.Document
            v = values(a)
            box = sx._box("Goals and Constraints", None, "Topology Study")
            form = QtWidgets.QFormLayout(box)
            self.goals = {}
            grp = QtWidgets.QButtonGroup(box)
            for k, g in enumerate(GOALS):
                r = QtWidgets.QRadioButton(g)
                r.setObjectName("SWTopoGoal%d" % k)
                grp.addButton(r)
                form.addRow("Goal:" if k == 0 else "", r)
                self.goals[g] = r
            self._grp = grp
            self.goals.get(v["goal"], self.goals[GOALS[0]]).setChecked(True)
            self.reduce = QtWidgets.QDoubleSpinBox()
            self.reduce.setObjectName("SWTopoReduce")
            self.reduce.setRange(5.0, 95.0)
            self.reduce.setDecimals(1)
            self.reduce.setSuffix(" %")
            self.reduce.setValue(float(v["reduce"]))
            form.addRow("Mass constraint: Reduce mass by", self.reduce)
            self.disp_value = QtWidgets.QRadioButton(DISP_MODES[0])
            self.disp_value.setObjectName("SWTopoDispValue")
            self.disp_factor_on = QtWidgets.QRadioButton(DISP_MODES[1])
            self.disp_factor_on.setObjectName("SWTopoDispFactorOn")
            dg = QtWidgets.QButtonGroup(box)
            dg.addButton(self.disp_value)
            dg.addButton(self.disp_factor_on)
            self._dg = dg
            (self.disp_value if v["disp_mode"] == DISP_MODES[0] else self.disp_factor_on).setChecked(True)
            self.limit = QtWidgets.QDoubleSpinBox()
            self.limit.setObjectName("SWTopoDispLimit")
            self.limit.setRange(1e-6, 1e6)
            self.limit.setDecimals(4)
            self.limit.setSuffix(" mm")
            self.limit.setValue(float(v["disp_limit"]))
            self.factor = QtWidgets.QDoubleSpinBox()
            self.factor.setObjectName("SWTopoDispFactor")
            self.factor.setRange(1.01, 1000.0)
            self.factor.setDecimals(2)
            self.factor.setValue(float(v["disp_factor"]))
            form.addRow("Displacement constraint:", self.disp_value)
            form.addRow("Largest displacement:", self.limit)
            form.addRow("", self.disp_factor_on)
            form.addRow("Factor:", self.factor)
            mb = sx._box("Manufacturing Controls")
            ml = QtWidgets.QFormLayout(mb)
            self.keep_loads = QtWidgets.QCheckBox("Preserve the regions where loads and fixtures are applied")
            self.keep_loads.setObjectName("SWTopoPreserveLoads")
            self.keep_loads.setChecked(bool(v.get("preserve_loads", True)))
            ml.addRow(self.keep_loads)
            self.faces = sx._PickList("SWTopoFaces")
            self.faces.setMaximumHeight(90)
            self.faces.addItems(list(v.get("faces", [])))
            self.faces.setToolTip("Pick faces in the graphics area; pick a face again to take it out")
            ml.addRow("Preserved Region (faces):", self.faces)
            self.thick_on = QtWidgets.QCheckBox("Thickness Control")
            self.thick_on.setObjectName("SWTopoThicknessOn")
            self.thick_on.setChecked(bool(v.get("thickness_on")))
            self.thick = QtWidgets.QDoubleSpinBox()
            self.thick.setObjectName("SWTopoMinThickness")
            self.thick.setRange(0.01, 1e5)
            self.thick.setDecimals(3)
            self.thick.setSuffix(" mm")
            self.thick.setValue(float(v["min_thickness"]))
            ml.addRow(self.thick_on)
            ml.addRow("Minimum thickness:", self.thick)
            self.demold_on = QtWidgets.QCheckBox("Demold Direction")
            self.demold_on.setObjectName("SWTopoDemoldOn")
            self.demold_on.setChecked(bool(v.get("demold_on")))
            self.demold = sx._PickList("SWTopoDemoldRef")
            self.demold.setFixedHeight(26)
            self.demold.setToolTip("Pick a plane, a flat face or a straight edge: the tool pulls along it")
            if v.get("demold_ref"):
                self.demold.addItem(v["demold_ref"])
            self.demold_rev = QtWidgets.QCheckBox("Reverse direction")
            self.demold_rev.setObjectName("SWTopoDemoldReverse")
            self.demold_rev.setChecked(bool(v.get("demold_reverse")))
            self.demold_both = QtWidgets.QCheckBox("Both directions (mid plane)")
            self.demold_both.setObjectName("SWTopoDemoldBoth")
            self.demold_both.setChecked(bool(v.get("demold_both")))
            ml.addRow(self.demold_on)
            ml.addRow("Pull direction:", self.demold)
            ml.addRow("", self.demold_rev)
            ml.addRow("", self.demold_both)
            self.sym_on = QtWidgets.QCheckBox("Symmetry")
            self.sym_on.setObjectName("SWTopoSymmetryOn")
            self.sym_on.setChecked(bool(v.get("sym_on")))
            self.sym = sx._PickList("SWTopoSymmetryPlanes")
            self.sym.setMaximumHeight(70)
            self.sym.setToolTip("Pick one plane (half), two (quarter) or three (1/8)")
            self.sym.addItems(list(v.get("sym_planes", [])))
            ml.addRow(self.sym_on)
            ml.addRow("Symmetry planes:", self.sym)
            self.form = [box, mb]
            self.boxes = [self.faces, self.demold, self.sym]
            for b in self.boxes:
                b.activated_box.connect(self._activate)
            self._activate(self.faces)
            for w in list(self.goals.values()) + [self.disp_value, self.disp_factor_on, self.thick_on, self.demold_on,
                                                  self.sym_on]:
                w.toggled.connect(self._enable)
            self._enable()
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)

        def goal(self):
            return next(g for g, r in self.goals.items() if r.isChecked())

        def _enable(self, *_a):
            from . import simtypes
            g = self.goal()
            on = g == GOALS[2]
            simtypes._row_visible(self.reduce, not on)
            for w in (self.disp_value, self.disp_factor_on):
                simtypes._row_visible(w, on)
            simtypes._row_visible(self.limit, on and self.disp_value.isChecked())
            simtypes._row_visible(self.factor, on and self.disp_factor_on.isChecked())
            simtypes._row_visible(self.thick, self.thick_on.isChecked())
            for w in (self.demold, self.demold_rev, self.demold_both):
                simtypes._row_visible(w, self.demold_on.isChecked())
            simtypes._row_visible(self.sym, self.sym_on.isChecked())
            if not self.current.isVisible() and self.current is not self.faces:
                self._activate(self.faces)

        def _activate(self, box):
            self.current = box
            for b in self.boxes:
                b.active(b is box)

        def addSelection(self, doc, name, sub, pnt):
            if doc != self.doc.Name:
                return
            last = (sub or "").split(".")[-1]
            if self.current is self.faces and not last.startswith("Face"):
                return
            ref = "%s:%s" % (name, last) if last else name
            QtCore.QTimer.singleShot(0, lambda: self._picked(ref))

        def _picked(self, ref):
            try:
                box = self.current
                if box is self.demold:
                    box.clear()
                    box.addItem(ref)
                elif box is self.sym and box.count() >= 3 and not box.findItems(ref, QtCore.Qt.MatchExactly):
                    box.takeItem(2)
                    box.addItem(ref)
                else:
                    box.toggle(ref)
                Gui.Selection.clearSelection()
            except RuntimeError:
                Gui.Selection.removeObserver(self)

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def _close(self):
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("simtopology.py:observer", _fw_err)
            Gui.Control.closeDialog()

        def reject(self):
            self._close()
            return True

        def accept(self):
            from . import simpms
            d = self.demold.values()
            self.doc.openTransaction(self.PM)
            try:
                set_values(self.a, goal=self.goal(), reduce=self.reduce.value(), preserve_loads=self.keep_loads.isChecked(),
                           faces=self.faces.values(),
                           disp_mode=DISP_MODES[0] if self.disp_value.isChecked() else DISP_MODES[1],
                           disp_limit=self.limit.value(), disp_factor=self.factor.value(),
                           thickness_on=self.thick_on.isChecked(), min_thickness=self.thick.value(),
                           demold_on=self.demold_on.isChecked(), demold_ref=d[0] if d else "",
                           demold_reverse=self.demold_rev.isChecked(), demold_both=self.demold_both.isChecked(),
                           sym_on=self.sym_on.isChecked(), sym_planes=self.sym.values())
            except simpms.SetupError as e:
                self.doc.abortTransaction()
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), self.PM, str(e))
                return False
            self.doc.commitTransaction()
            self._close()
            _refresh()
            return True

    class MassPM:
        """Material Mass plot: the level (Light to Heavy) and Export Smoothed Mesh."""
        PM = "Material Mass"

        def __init__(self, a, name=None):
            from . import simxpress as sx
            self.a, self.doc, self.name = a, a.Document, name
            v = values(a)
            self.old = float(v["threshold"])
            box = sx._box("Material Mass", None, "Material Mass")
            lay = QtWidgets.QVBoxLayout(box)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel("Light"))
            self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            self.slider.setObjectName("SWTopoLevel")
            self.slider.setRange(5, 95)
            self.slider.setValue(int(round(self.old * 100)))
            row.addWidget(self.slider, 1)
            row.addWidget(QtWidgets.QLabel("Heavy"))
            lay.addLayout(row)
            self.note = QtWidgets.QLabel()
            self.note.setObjectName("SWTopoMassNote")
            lay.addWidget(self.note)
            self.export = QtWidgets.QPushButton("Export Smoothed Mesh")
            self.export.setObjectName("SWTopoExport")
            self.export.clicked.connect(self._export)
            lay.addWidget(self.export)
            self.form = [box]
            self.slider.valueChanged.connect(self._level)
            self._level()

        def _level(self, *_a):
            t = self.slider.value() / 100.0
            try:
                set_values(self.a, threshold=t)
                show(self.a, self.name)
                self.note.setText("Relative mass density %.2f and above: %.1f %% of the part" % (
                    t, 100.0 * mass_kept(self.a, t)))
            except Exception as error:
                self.note.setText(str(error))

        def _export(self):
            try:
                o = export_smoothed(self.a)
                self.note.setText("Made %s" % o.Label)
            except Exception as error:
                self.note.setText(str(error))

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def accept(self):
            Gui.Control.closeDialog()
            return True

        def reject(self):
            try:
                set_values(self.a, threshold=self.old)
                show(self.a, self.name)
            except Exception as _fw_err:
                _fw_log("simtopology.py:reject", _fw_err)
            Gui.Control.closeDialog()
            return True

    def _refresh():
        try:
            from . import simtree
            simtree.refresh()
        except Exception as _fw_err:
            _fw_log("simtopology.py:refresh", _fw_err)

    def _open(pm):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        Gui.Control.showDialog(pm)
        return pm

    def open_goals(a):
        return _open(GoalsPM(a))

    def open_mass(a, name=None):
        return _open(MassPM(a, name))


# --------------------------------------------------------------------------- hooks
def install():
    """Material Mass as a plot of a Topology Study's Results (simplots shows it here)."""
    from . import simplots
    if getattr(simplots, "_fw_topology", False):
        return
    simplots.COMPONENTS.setdefault(QUANTITY, [(COMP, "Material Mass")])
    simplots.UNITS.setdefault(QUANTITY, {"": 1.0})
    simplots.DEFAULT_UNIT.setdefault(QUANTITY, "")
    simplots.TYPE_WORDS.setdefault(QUANTITY, "Material Mass")
    simplots.KINDS[KIND] = (QUANTITY,)
    try:
        from . import simtree
        simtree.COMP_WORDS.setdefault(COMP, "Material Mass")
    except Exception as _fw_err:
        _fw_log("simtopology.py:words", _fw_err)
    defaults0 = simplots.defaults
    show0 = simplots.show
    clear0 = simplots.clear

    def defaults(a):
        if is_topology(a):
            if not simplots.plots(a) and densities(a):
                simplots.new_plot(a, QUANTITY, COMP, deformed=False)
            return simplots.plots(a)
        return defaults0(a)

    def show_(a, name):
        p = simplots.get_plot(a, name) if is_topology(a) else None
        if p is not None and p["quantity"] == QUANTITY:
            clear0()
            return show(a, name)
        hide()
        return show0(a, name)

    def clear():
        hide()
        return clear0()
    simplots.defaults, simplots.show, simplots.clear = defaults, show_, clear
    simplots._fw_topology = True
